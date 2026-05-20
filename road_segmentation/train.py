from __future__ import annotations

from pathlib import Path

import albumentations as A
import numpy as np
from PIL import Image
import segmentation_models_pytorch as smp
import torch
from torch import nn
from torch.optim import Adam
from torch.utils.data import DataLoader, Dataset, random_split


EPOCHS = 20
BATCH_SIZE = 4
LEARNING_RATE = 1e-4
IMAGE_SIZE = 512
SPLIT_SEED = 42


class RoadDataset(Dataset):
    def __init__(self, images_dir: Path, masks_dir: Path, train: bool) -> None:
        self.images_dir = images_dir
        self.masks_dir = masks_dir
        self.file_names = sorted(path.name for path in images_dir.glob("*.png"))
        self.file_names = [name for name in self.file_names if (masks_dir / name).exists()]
        if not self.file_names:
            raise ValueError("No matching image/mask PNG pairs found in data directories.")

        transforms = [A.Resize(IMAGE_SIZE, IMAGE_SIZE)]
        if train:
            transforms.extend(
                [
                    A.HorizontalFlip(p=0.5),
                    A.VerticalFlip(p=0.5),
                    A.RandomRotate90(p=0.5),
                ]
            )
        transforms.append(
            A.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            )
        )
        self.transform = A.Compose(transforms)

    def __len__(self) -> int:
        return len(self.file_names)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        name = self.file_names[idx]
        image_path = self.images_dir / name
        mask_path = self.masks_dir / name

        image = np.array(Image.open(image_path).convert("RGB"))
        mask = np.array(Image.open(mask_path).convert("L"))

        transformed = self.transform(image=image, mask=mask)
        image_np = transformed["image"].astype(np.float32)
        mask_np = transformed["mask"].astype(np.float32) / 255.0

        image_tensor = torch.from_numpy(image_np).permute(2, 0, 1)
        mask_tensor = torch.from_numpy(mask_np).unsqueeze(0)
        return image_tensor, mask_tensor


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
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
    criterion: nn.Module,
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

    train_dataset = RoadDataset(images_dir=images_dir, masks_dir=masks_dir, train=True)
    train_dataset.file_names = [full_dataset.file_names[i] for i in train_subset.indices]
    val_dataset = RoadDataset(images_dir=images_dir, masks_dir=masks_dir, train=False)
    val_dataset.file_names = [full_dataset.file_names[i] for i in val_subset.indices]

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

    optimizer = Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.BCEWithLogitsLoss()

    best_iou = -1.0
    best_model_path = checkpoints_dir / "best_model.pth"

    for epoch in range(1, EPOCHS + 1):
        train_loss = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_iou = validate(model, val_loader, criterion, device)

        if val_iou > best_iou:
            best_iou = val_iou
            torch.save(model.state_dict(), best_model_path)

        print(
            f"Epoch {epoch}/{EPOCHS} | train_loss: {train_loss:.4f} | "
            f"val_loss: {val_loss:.4f} | val_iou: {val_iou:.4f}"
        )

    print(f"Training done. Best IoU: {best_iou:.4f}")


if __name__ == "__main__":
    main()
