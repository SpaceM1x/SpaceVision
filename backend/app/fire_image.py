"""Pretrained image fire-risk classifier.

The model is ``prithivMLmods/Fire-Risk-Detection`` (Apache-2.0), a SigLIP2
image classifier fine-tuned on the ``blanchon/FireRisk`` dataset. It predicts
seven land-cover/fire-risk classes from an RGB image:

    high, low, moderate, non-burnable, very_high, very_low, water

The module is intentionally optional and lazy:

* importing it does not import ``transformers`` or load weights;
* the first call downloads/loads the model in a background thread;
* if the model is unavailable the API reports a clear status instead of
  breaking the rest of the application.

This is an image-level assessment of the depicted area, not a forecast of an
ignition at a coordinate. The geospatial model in ``fire_risk`` remains the
authoritative point-risk calculation.
"""
from __future__ import annotations

import os
import threading
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

# transformers imports TensorFlow/Flax when they are installed, which adds
# several seconds to the first load and is not needed here. Set these before
# the lazy ``transformers`` import inside ``_ensure_model``.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")

MODEL_ID = os.environ.get("FIRE_RISK_MODEL_ID", "prithivMLmods/Fire-Risk-Detection")
CACHE_DIR = os.environ.get("FIRE_RISK_MODEL_CACHE_DIR") or None
MAX_IMAGE_BYTES = int(os.environ.get("FIRE_RISK_MAX_IMAGE_BYTES", str(20 * 1024 * 1024)))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


ENABLED = _env_bool("FIRE_RISK_MODEL_ENABLED", True)

# Class -> (Russian label, contribution to the continuous risk score in [0, 1]).
# The score is the probability-weighted mean of these contributions, so a
# confident "very_high" is close to 1.0 while water/non-burnable pull it down.
CLASS_META: dict[str, tuple[str, float]] = {
    "very_low": ("Очень низкий", 0.05),
    "low": ("Низкий", 0.20),
    "moderate": ("Средний", 0.50),
    "high": ("Высокий", 0.80),
    "very_high": ("Очень высокий", 1.00),
    "non_burnable": ("Не горит", 0.10),
    "water": ("Вода", 0.00),
}

RISK_LEVELS = {
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
}

# The displayed level follows the winning class, while ``risk_score`` stays a
# continuous probability-weighted index. This avoids showing "very low" next
# to a "medium" badge when the remaining classes are moderately dangerous.
PREDICTED_LEVEL = {
    "very_low": "low",
    "low": "low",
    "moderate": "medium",
    "high": "high",
    "very_high": "high",
    "non_burnable": "low",
    "water": "low",
}


class FireImageModelError(RuntimeError):
    """Raised when the pretrained classifier cannot be used."""


_model: Any = None
_processor: Any = None
_state = "not_loaded"  # not_loaded | loading | ready | error | disabled
_error: str | None = None
_lock = threading.Lock()


def _set_state(state: str, error: str | None = None) -> None:
    global _state, _error
    with _lock:
        _state = state
        _error = error


def model_status() -> dict[str, Any]:
    """Return the current model state without triggering a download."""
    with _lock:
        state = "disabled" if not ENABLED else _state
        error = _error
    return {
        "enabled": ENABLED,
        "model_id": MODEL_ID,
        "state": state,
        "error": error,
        "labels": list(CLASS_META),
    }


def _ensure_model() -> None:
    """Load the processor and weights once (thread-safe)."""
    global _model, _processor, _state, _error

    if not ENABLED:
        _set_state("disabled")
        raise FireImageModelError(
            "Модель отключена. Установите FIRE_RISK_MODEL_ENABLED=1, чтобы включить её."
        )

    if _model is not None and _processor is not None:
        return

    with _lock:
        if _model is not None and _processor is not None:
            return
        _state = "loading"
        _error = None

    try:
        from transformers import AutoImageProcessor, SiglipForImageClassification

        processor = AutoImageProcessor.from_pretrained(MODEL_ID, cache_dir=CACHE_DIR)
        model = SiglipForImageClassification.from_pretrained(MODEL_ID, cache_dir=CACHE_DIR)
        model.eval()
    except Exception as error:  # noqa: BLE001 - report any load failure to the UI
        message = f"Не удалось загрузить модель {MODEL_ID}: {error}"
        _set_state("error", message)
        raise FireImageModelError(message) from error

    with _lock:
        _processor = processor
        _model = model
        _state = "ready"
        _error = None


def _ensure_model_safe() -> None:
    try:
        _ensure_model()
    except FireImageModelError:
        # State and error are already recorded; the status endpoint exposes them.
        pass


def start_preload() -> dict[str, Any]:
    """Start loading the model in the background (idempotent)."""
    global _state, _error

    if not ENABLED:
        _set_state("disabled")
        return model_status()

    should_start = False
    with _lock:
        already_ready = _model is not None and _processor is not None
        already_loading = _state == "loading"
        if not already_ready and not already_loading:
            # Report "loading" immediately; the worker thread may take a while
            # to import torch/transformers and read the weights.
            _state = "loading"
            _error = None
            should_start = True

    if already_ready:
        _set_state("ready")
        return model_status()
    if should_start:
        threading.Thread(
            target=_ensure_model_safe, name="fire-model-loader", daemon=True
        ).start()
    return model_status()


def _risk_level(score: float) -> str:
    if score < 0.20:
        return "low"
    if score < 0.50:
        return "medium"
    return "high"


def classify_image_bytes(data: bytes) -> dict[str, Any]:
    """Classify an encoded RGB image and return labels plus a risk score."""
    if not data:
        raise FireImageModelError("Пустой файл изображения.")
    if len(data) > MAX_IMAGE_BYTES:
        raise FireImageModelError(
            f"Файл слишком большой (>{MAX_IMAGE_BYTES // (1024 * 1024)} МБ)."
        )

    try:
        with Image.open(BytesIO(data)) as image:
            rgb = image.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise FireImageModelError("Не удалось прочитать изображение.") from error

    _ensure_model()
    assert _processor is not None and _model is not None

    import torch

    inputs = _processor(images=rgb, return_tensors="pt")
    with torch.inference_mode():
        logits = _model(**inputs).logits
        probabilities = torch.softmax(logits, dim=-1)[0].tolist()

    id2label = getattr(_model.config, "id2label", {})
    items = []
    for index, probability in enumerate(probabilities):
        label = str(id2label.get(index, index))
        normalized = label.replace("-", "_")
        label_ru, contribution = CLASS_META.get(normalized, (label, 0.5))
        items.append(
            {
                "label": label,
                "normalized": normalized,
                "label_ru": label_ru,
                "probability": float(probability),
                "risk_contribution": contribution,
            }
        )

    items.sort(key=lambda item: item["probability"], reverse=True)
    top = items[0]
    risk_score = sum(item["probability"] * item["risk_contribution"] for item in items)
    level = PREDICTED_LEVEL.get(top["normalized"]) or _risk_level(risk_score)

    return {
        "available": True,
        "model_id": MODEL_ID,
        "predicted": top["label"],
        "predicted_ru": top["label_ru"],
        "confidence": top["probability"],
        "risk_score": risk_score,
        "risk_level": level,
        "risk_level_ru": RISK_LEVELS[level],
        "probabilities": [
            {
                "label": item["label"],
                "label_ru": item["label_ru"],
                "probability": item["probability"],
            }
            for item in items
        ],
        "reason": None,
    }
