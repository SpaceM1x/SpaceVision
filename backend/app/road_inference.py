from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
import segmentation_models_pytorch as smp
import torch


IMAGE_SIZE = 512
_MODEL: torch.nn.Module | None = None
_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _checkpoint_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "road_segmentation" / "checkpoints" / "best_model.pth"


def _prepare_image_for_model(image_rgb: np.ndarray) -> tuple[np.ndarray, tuple[int, int], tuple[int, int], tuple[int, int]]:
    orig_h, orig_w = image_rgb.shape[:2]
    scale = min(IMAGE_SIZE / max(orig_h, 1), IMAGE_SIZE / max(orig_w, 1))
    resized_h = max(1, int(round(orig_h * scale)))
    resized_w = max(1, int(round(orig_w * scale)))

    resized = np.array(
        Image.fromarray(image_rgb, mode="RGB").resize((resized_w, resized_h), resample=Image.Resampling.BILINEAR)
    )

    canvas = np.zeros((IMAGE_SIZE, IMAGE_SIZE, 3), dtype=np.uint8)
    pad_y = (IMAGE_SIZE - resized_h) // 2
    pad_x = (IMAGE_SIZE - resized_w) // 2
    canvas[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w] = resized
    return canvas, (orig_h, orig_w), (resized_h, resized_w), (pad_y, pad_x)


def _restore_mask_to_original_size(
    mask_512: np.ndarray, original_shape: tuple[int, int], resized_shape: tuple[int, int], pad: tuple[int, int]
) -> np.ndarray:
    orig_h, orig_w = original_shape
    resized_h, resized_w = resized_shape
    pad_y, pad_x = pad
    cropped = mask_512[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w]
    restored = Image.fromarray(cropped, mode="L").resize((orig_w, orig_h), resample=Image.Resampling.NEAREST)
    return np.array(restored, dtype=np.uint8)


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

    image_rgb = np.array(Image.open(image_path).convert("RGB"), dtype=np.uint8)
    prepared, original_shape, resized_shape, pad = _prepare_image_for_model(image_rgb)
    normalized = prepared.astype(np.float32) / 255.0
    normalized = (normalized - _IMAGENET_MEAN) / _IMAGENET_STD
    image_tensor = torch.from_numpy(normalized).permute(2, 0, 1).unsqueeze(0).float().to(_DEVICE)

    with torch.no_grad():
        logits = model(image_tensor)
        probs = torch.sigmoid(logits)
        pred = (probs > threshold).float()

    pred_mask_512 = pred.squeeze().cpu().numpy().astype(np.uint8) * 255
    pred_mask = _restore_mask_to_original_size(pred_mask_512, original_shape, resized_shape, pad)

    overlay = image_rgb.copy()
    road_pixels = pred_mask > 0
    overlay[road_pixels] = (0.6 * overlay[road_pixels] + 0.4 * np.array([255, 0, 0])).astype(np.uint8)

    prediction_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    mask_path = prediction_dir / f"{stem}_mask.png"
    overlay_path = prediction_dir / f"{stem}_overlay.png"
    Image.fromarray(pred_mask, mode="L").save(mask_path)
    Image.fromarray(overlay, mode="RGB").save(overlay_path)
    return mask_path, overlay_path
