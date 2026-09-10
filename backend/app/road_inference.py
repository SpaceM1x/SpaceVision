from __future__ import annotations

from pathlib import Path

import albumentations as A
from albumentations.pytorch import ToTensorV2
import numpy as np
from PIL import Image
import segmentation_models_pytorch as smp
import torch


IMAGE_SIZE = 512
_MODEL: torch.nn.Module | None = None
_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _checkpoint_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "road_segmentation" / "checkpoints" / "best_model.pth"


def _build_transform() -> A.Compose:
    return A.Compose(
        [
            A.PadIfNeeded(min_height=IMAGE_SIZE, min_width=IMAGE_SIZE, border_mode=0, fill=0),
            A.CenterCrop(IMAGE_SIZE, IMAGE_SIZE),
            A.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
            ToTensorV2(),
        ]
    )


def _load_model() -> torch.nn.Module:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    checkpoint_path = _checkpoint_path()
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

    model = smp.Unet(
        encoder_name="resnet34",
        encoder_weights="imagenet",
        in_channels=3,
        classes=1,
        activation=None,
    ).to(_DEVICE)

    state_dict = torch.load(checkpoint_path, map_location=_DEVICE, weights_only=True)
    model.load_state_dict(state_dict)
    model.eval()
    _MODEL = model
    return model


def run_road_segmentation(image_path: Path, prediction_dir: Path, threshold: float = 0.5) -> tuple[Path, Path]:
    model = _load_model()
    transform = _build_transform()

    image_rgb = np.array(Image.open(image_path).convert("RGB"))
    transformed = transform(image=image_rgb)
    image_tensor = transformed["image"].float().unsqueeze(0).to(_DEVICE)

    with torch.no_grad():
        logits = model(image_tensor)
        probs = torch.sigmoid(logits)
        pred = (probs > threshold).float()

    pred_mask = pred.squeeze().cpu().numpy().astype(np.uint8) * 255

    normalized = image_tensor.squeeze(0).cpu().permute(1, 2, 0).numpy()
    normalized = (
        normalized * np.array([0.229, 0.224, 0.225], dtype=np.float32)
        + np.array([0.485, 0.456, 0.406], dtype=np.float32)
    )
    normalized = np.clip(normalized * 255.0, 0, 255).astype(np.uint8)

    overlay = normalized.copy()
    road_pixels = pred_mask > 0
    overlay[road_pixels] = (0.6 * overlay[road_pixels] + 0.4 * np.array([255, 0, 0])).astype(np.uint8)

    prediction_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    mask_path = prediction_dir / f"{stem}_mask.png"
    overlay_path = prediction_dir / f"{stem}_overlay.png"
    Image.fromarray(pred_mask, mode="L").save(mask_path)
    Image.fromarray(overlay, mode="RGB").save(overlay_path)
    return mask_path, overlay_path
