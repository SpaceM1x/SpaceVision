"""Satellite-road segmentation using a pretrained OpenEarthMap model.

The model predicts land-cover classes; the ``road`` class is emitted as one
combined road mask (paved and unpaved roads are not separate classes). Large
images are inferred in overlapping tiles so narrow roads keep their detail.
Weights are downloaded lazily from Hugging Face and cached there; the old local
U-Net checkpoint is deliberately not consulted.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")

MODEL_ID = os.environ.get(
    "ROAD_SEGMENTATION_MODEL_ID",
    "kishan4444/upernet-swin-openearthmap-road-segmentation",
)
CACHE_DIR = os.environ.get("ROAD_MODEL_CACHE_DIR") or None
TILE_SIZE = 512
TILE_OVERLAP = 128
ROAD_THRESHOLD = float(os.environ.get("ROAD_SEGMENTATION_THRESHOLD", "0.35"))
_DEVICE_NAME = os.environ.get("ROAD_MODEL_DEVICE", "").strip()

_MODEL: Any = None
_ROAD_CLASS_ID: int | None = None
_DEVICE: Any = None
_STATE = "not_loaded"
_ERROR: str | None = None
_LOCK = threading.Lock()


class RoadInferenceError(RuntimeError):
    """Raised when the pretrained road-segmentation model cannot be used."""


def model_status() -> dict[str, Any]:
    """Return model state without triggering a model download."""
    with _LOCK:
        return {"model_id": MODEL_ID, "state": _STATE, "error": _ERROR}


def _load_model() -> tuple[Any, int, Any]:
    global _MODEL, _ROAD_CLASS_ID, _DEVICE, _STATE, _ERROR

    if _MODEL is not None:
        return _MODEL, _ROAD_CLASS_ID, _DEVICE

    with _LOCK:
        if _MODEL is not None:
            return _MODEL, _ROAD_CLASS_ID, _DEVICE
        _STATE = "loading"
        _ERROR = None
        try:
            import torch
            from transformers import AutoModelForSemanticSegmentation

            if _DEVICE_NAME:
                device = torch.device(_DEVICE_NAME)
            else:
                device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            model = AutoModelForSemanticSegmentation.from_pretrained(
                MODEL_ID, cache_dir=CACHE_DIR
            )
            labels = model.config.id2label
            road_class_id = next(
                (
                    int(index)
                    for index, label in labels.items()
                    if str(label).strip().lower() == "road"
                ),
                None,
            )
            if road_class_id is None:
                raise ValueError("В конфигурации модели отсутствует класс road.")
            model.to(device)
            model.eval()
        except Exception as error:  # report download/config/device errors to caller
            _STATE = "error"
            _ERROR = f"Не удалось загрузить модель дорог {MODEL_ID}: {error}"
            raise RoadInferenceError(_ERROR) from error

        _MODEL = model
        _ROAD_CLASS_ID = road_class_id
        _DEVICE = device
        _STATE = "ready"
        _ERROR = None
        return _MODEL, _ROAD_CLASS_ID, _DEVICE


def _tile_starts(length: int, tile_size: int = TILE_SIZE) -> list[int]:
    """Return overlapping tile offsets that cover an axis without gaps."""
    if length <= tile_size:
        return [0]
    stride = tile_size - TILE_OVERLAP
    starts = list(range(0, length - tile_size + 1, stride))
    final_start = length - tile_size
    if starts[-1] != final_start:
        starts.append(final_start)
    return starts


def _prepare_tile(image: np.ndarray, top: int, left: int) -> tuple[np.ndarray, int, int]:
    """Extract a 512px RGB tile, padding images smaller than a tile."""
    height, width = image.shape[:2]
    tile = image[top : top + TILE_SIZE, left : left + TILE_SIZE]
    valid_height, valid_width = tile.shape[:2]
    pad_height = TILE_SIZE - valid_height
    pad_width = TILE_SIZE - valid_width
    if pad_height or pad_width:
        # Edge padding is stable even for 1-pixel dimensions and avoids adding
        # artificial black borders to small snapshots.
        tile = np.pad(tile, ((0, pad_height), (0, pad_width), (0, 0)), mode="edge")
    return tile, min(valid_height, height - top), min(valid_width, width - left)


def _predict_tile(tile: np.ndarray, model: Any, road_class_id: int, device: Any) -> np.ndarray:
    """Return per-pixel road probabilities for one RGB tile."""
    import torch
    import torch.nn.functional as functional

    values = torch.from_numpy(tile.copy()).permute(2, 0, 1).float().div_(255.0)
    mean = torch.tensor((0.485, 0.456, 0.406), dtype=values.dtype)[:, None, None]
    std = torch.tensor((0.229, 0.224, 0.225), dtype=values.dtype)[:, None, None]
    values = ((values - mean) / std).unsqueeze(0).to(device)

    with torch.inference_mode():
        output = model(pixel_values=values)
        logits = output.logits
        if logits.shape[-2:] != (TILE_SIZE, TILE_SIZE):
            logits = functional.interpolate(
                logits, size=(TILE_SIZE, TILE_SIZE), mode="bilinear", align_corners=False
            )
        probabilities = logits.softmax(dim=1)[0, road_class_id]
    return probabilities.float().cpu().numpy()


def _predict_probabilities(image_rgb: np.ndarray, model: Any, road_class_id: int, device: Any) -> np.ndarray:
    """Infer an image in overlapping tiles and average their shared pixels."""
    height, width = image_rgb.shape[:2]
    probability_sum = np.zeros((height, width), dtype=np.float32)
    prediction_count = np.zeros((height, width), dtype=np.uint8)

    for top in _tile_starts(height):
        for left in _tile_starts(width):
            tile, valid_height, valid_width = _prepare_tile(image_rgb, top, left)
            probabilities = _predict_tile(tile, model, road_class_id, device)
            probability_sum[top : top + valid_height, left : left + valid_width] += probabilities[
                :valid_height, :valid_width
            ]
            prediction_count[top : top + valid_height, left : left + valid_width] += 1

    return probability_sum / np.maximum(prediction_count, 1)


def run_road_segmentation(
    image_path: Path, prediction_dir: Path, threshold: float = ROAD_THRESHOLD
) -> tuple[Path, Path]:
    model, road_class_id, device = _load_model()
    try:
        image_rgb = np.array(Image.open(image_path).convert("RGB"))
        if image_rgb.size == 0:
            raise ValueError("Изображение пустое.")
        probabilities = _predict_probabilities(image_rgb, model, road_class_id, device)
    except RoadInferenceError:
        raise
    except Exception as error:
        raise RoadInferenceError(f"Не удалось обработать снимок: {error}") from error

    road_pixels = probabilities >= threshold
    pred_mask = road_pixels.astype(np.uint8) * 255

    overlay = image_rgb.copy()
    overlay[road_pixels] = (
        0.6 * overlay[road_pixels] + 0.4 * np.array([255, 0, 0])
    ).astype(np.uint8)

    prediction_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    mask_path = prediction_dir / f"{stem}_mask.png"
    overlay_path = prediction_dir / f"{stem}_overlay.png"
    Image.fromarray(pred_mask, mode="L").save(mask_path)
    Image.fromarray(overlay, mode="RGB").save(overlay_path)
    return mask_path, overlay_path
