from __future__ import annotations

from pathlib import Path

import albumentations as A
from albumentations.pytorch import ToTensorV2
import numpy as np
from PIL import Image
import segmentation_models_pytorch as smp
import torch


IMAGE_SIZE = 512
TILE_OVERLAP = 128
_MODEL: torch.nn.Module | None = None
_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _checkpoint_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "road_segmentation" / "checkpoints" / "best_model.pth"


def _build_transform() -> A.Compose:
    return A.Compose(
        [
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


def _tile_starts(length: int) -> list[int]:
    last = length - IMAGE_SIZE
    starts = list(range(0, last + 1, IMAGE_SIZE - TILE_OVERLAP))
    if starts[-1] != last:
        starts.append(last)
    return starts


def _predict_probabilities(image_rgb: np.ndarray, model: torch.nn.Module) -> np.ndarray:
    """Road probability for every pixel of the whole image, averaged over tiles."""
    height, width = image_rgb.shape[:2]
    pad_h = max(0, IMAGE_SIZE - height)
    pad_w = max(0, IMAGE_SIZE - width)
    padded = np.pad(image_rgb, ((0, pad_h), (0, pad_w), (0, 0)))
    padded_h, padded_w = padded.shape[:2]

    transform = _build_transform()
    total = np.zeros((padded_h, padded_w), dtype=np.float32)
    count = np.zeros((padded_h, padded_w), dtype=np.float32)
    for row in _tile_starts(padded_h):
        for col in _tile_starts(padded_w):
            tile = padded[row:row + IMAGE_SIZE, col:col + IMAGE_SIZE]
            tensor = transform(image=tile)["image"].float().unsqueeze(0).to(_DEVICE)
            with torch.no_grad():
                probs = torch.sigmoid(model(tensor)).squeeze().cpu().numpy()
            total[row:row + IMAGE_SIZE, col:col + IMAGE_SIZE] += probs
            count[row:row + IMAGE_SIZE, col:col + IMAGE_SIZE] += 1
    return (total / count)[:height, :width]


def run_road_segmentation(image_path: Path, prediction_dir: Path, threshold: float = 0.5) -> tuple[Path, Path]:
    model = _load_model()
    image_rgb = np.array(Image.open(image_path).convert("RGB"))
    probs = _predict_probabilities(image_rgb, model)

    road_pixels = probs > threshold
    pred_mask = road_pixels.astype(np.uint8) * 255

    overlay = image_rgb.copy()
    overlay[road_pixels] = (0.6 * overlay[road_pixels] + 0.4 * np.array([255, 0, 0])).astype(np.uint8)

    prediction_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    mask_path = prediction_dir / f"{stem}_mask.png"
    overlay_path = prediction_dir / f"{stem}_overlay.png"
    Image.fromarray(pred_mask, mode="L").save(mask_path)
    Image.fromarray(overlay, mode="RGB").save(overlay_path)
    return mask_path, overlay_path
