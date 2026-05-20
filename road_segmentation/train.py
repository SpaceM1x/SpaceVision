from __future__ import annotations

from pathlib import Path
from typing import Callable

import albumentations as A
from albumentations.pytorch import ToTensorV2
import numpy as np
from PIL import Image
import segmentation_models_pytorch as smp
from segmentation_models_pytorch.losses import DiceLoss, SoftBCEWithLogitsLoss
import torch
from torch import nn
from torch.optim import Adam
from torch.utils.data import DataLoader, Dataset, random_split


EPOCHS = 40
BATCH_SIZE = 4
LEARNING_RATE = 1e-4
IMAGE_SIZE = 512
SPLIT_SEED = 42


class RoadDataset(Dataset):
    def __init__(self, images_dir: Path, masks_dir: Path, train: bool, multiplier: int = 1) -> None:
        self.images_dir = images_dir
        self.masks_dir = masks_dir
        self.train = train
        self.multiplier = multiplier
        self.images = sorted(path.name for path in images_dir.glob("*.png"))
        self.images = [name for name in self.images if (masks_dir / name).exists()]
        if not self.images:
            raise ValueError("No matching image/mask PNG pairs found in data directories.")

        if train:
            self.transform = A.Compose(
                [
                    A.RandomCrop(IMAGE_SIZE, IMAGE_SIZE),
                    A.HorizontalFlip(p=0.5),
                    A.VerticalFlip(p=0.5),
                    A.RandomRotate90(p=0.5),
                    A.RandomBrightnessContrast(p=0.3),
                    A.Normalize(
                        mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225],
                    ),
                    ToTensorV2(),
                ]
            )
        else:
            self.transform = A.Compose(
                [
                    A.CenterCrop(IMAGE_SIZE, IMAGE_SIZE),
                    A.Normalize(
                        mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225],
                    ),
                    ToTensorV2(),
                ]
            )

    def __len__(self) -> int:
        return len(self.images) * self.multiplier

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        idx = idx % len(self.images)
        name = self.images[idx]
        image_path = self.images_dir / name
        mask_path = self.masks_dir / name

        image = np.array(Image.open(image_path).convert("RGB"))
        mask = np.array(Image.open(mask_path).convert("L"))

        transformed = self.transform(image=image, mask=mask)
        image_tensor = transformed["image"].float()
        mask_tensor = transformed["mask"].float()
        if mask_tensor.ndim == 2:
            mask_tensor = mask_tensor.unsqueeze(0)
        mask_tensor = mask_tensor / 255.0
        return image_tensor, mask_tensor


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: Callable[[torch.Tensor, torch.Tensor], torch.Tensor],
    optimizer: Adam,
    device: torch.device,
) -> float:
    model.train()
    total_loss = 0.0
    total_samples = 0

    for images, masks in loader:
        images = images.to(device)
        masks = masks.to(device)

        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, masks)
        loss.backward()
        optimizer.step()

        batch_size = images.size(0)
        total_loss += loss.item() * batch_size
        total_samples += batch_size

    return total_loss / max(total_samples, 1)


@torch.no_grad()
def validate(
    model: nn.Module,
    loader: DataLoader,
    criterion: Callable[[torch.Tensor, torch.Tensor], torch.Tensor],
    device: torch.device,
) -> tuple[float, float]:
    model.eval()
    total_loss = 0.0
    total_iou = 0.0
    total_samples = 0

    for images, masks in loader:
        images = images.to(device)
        masks = masks.to(device)

        outputs = model(images)
        loss = criterion(outputs, masks)
        preds = (torch.sigmoid(outputs) > 0.5).float()
        intersection = (preds * masks).sum()
        union = preds.sum() + masks.sum() - intersection
        iou = (intersection + 1e-6) / (union + 1e-6)

        batch_size = images.size(0)
        total_loss += loss.item() * batch_size
        total_iou += iou.item() * batch_size
        total_samples += batch_size

    avg_loss = total_loss / max(total_samples, 1)
    avg_iou = total_iou / max(total_samples, 1)
    return avg_loss, avg_iou


def main() -> None:
    root_dir = Path(__file__).resolve().parent
    images_dir = root_dir / "data" / "images"
    masks_dir = root_dir / "data" / "masks"
    checkpoints_dir = root_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    full_dataset = RoadDataset(images_dir=images_dir, masks_dir=masks_dir, train=False)
    train_size = int(0.8 * len(full_dataset))
    val_size = len(full_dataset) - train_size
    generator = torch.Generator().manual_seed(SPLIT_SEED)
    train_subset, val_subset = random_split(full_dataset, [train_size, val_size], generator=generator)

    train_dataset = RoadDataset(images_dir=images_dir, masks_dir=masks_dir, train=True, multiplier=8)
    train_dataset.images = [full_dataset.images[i] for i in train_subset.indices]
    val_dataset = RoadDataset(images_dir=images_dir, masks_dir=masks_dir, train=False, multiplier=1)
    val_dataset.images = [full_dataset.images[i] for i in val_subset.indices]

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = smp.Unet(
        encoder_name="resnet34",
        encoder_weights="imagenet",
        in_channels=3,
        classes=1,
        activation=None,
    ).to(device)

    epochs = EPOCHS
    optimizer = Adam(model.parameters(), lr=LEARNING_RATE)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    dice_loss = DiceLoss(mode="binary")
    bce_loss = SoftBCEWithLogitsLoss(pos_weight=torch.tensor([3.0], device=device))

    def criterion(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return 0.5 * bce_loss(pred, target) + 0.5 * dice_loss(pred, target)

    best_iou = -1.0
    best_model_path = checkpoints_dir / "best_model.pth"

    for epoch in range(1, epochs + 1):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_iou = validate(model, val_loader, criterion, device)

        if val_iou > best_iou:
            best_iou = val_iou
            torch.save(model.state_dict(), best_model_path)

        current_lr = optimizer.param_groups[0]["lr"]
        print(
            f"Epoch {epoch}/{epochs} | train_loss: {train_loss:.4f} | "
            f"val_loss: {val_loss:.4f} | val_iou: {val_iou:.4f} | lr: {current_lr:.6f}"
        )
        scheduler.step()

    print(f"Training done. Best IoU: {best_iou:.4f}")


if __name__ == "__main__":
    main()
