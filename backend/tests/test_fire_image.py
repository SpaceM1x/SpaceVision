"""Tests for the pretrained image fire-risk classifier (no model download)."""
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

import app.fire_image as fire_image
from app.fire_image import FireImageModelError, classify_image_bytes, model_status


class _FakeConfig:
    id2label = {
        0: "very_high",
        1: "high",
        2: "moderate",
        3: "low",
        4: "very_low",
        5: "non-burnable",
        6: "water",
    }


class _FakeOutput:
    def __init__(self, logits):
        self.logits = logits


class _FakeModel:
    config = _FakeConfig()

    def __init__(self, logits):
        self._logits = logits

    def __call__(self, **_kwargs):
        return _FakeOutput(self._logits)


class _FakeProcessor:
    def __call__(self, images, return_tensors="pt"):
        assert return_tensors == "pt"
        assert images.mode == "RGB"
        return {}


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 32), color=(40, 90, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def _install_fake_model(monkeypatch, logits):
    import torch

    monkeypatch.setattr(fire_image, "_ensure_model", lambda: None)
    monkeypatch.setattr(fire_image, "_processor", _FakeProcessor())
    monkeypatch.setattr(fire_image, "_model", _FakeModel(torch.tensor([logits])))


def test_classify_image_returns_labels_and_risk_score(monkeypatch):
    # Strongly favour "very_high" (index 0).
    _install_fake_model(monkeypatch, [8.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    result = classify_image_bytes(_png_bytes())

    assert result["available"] is True
    assert result["predicted"] == "very_high"
    assert result["predicted_ru"] == "Очень высокий"
    assert result["risk_level"] == "high"
    assert result["risk_score"] > 0.9
    assert result["confidence"] > 0.9
    assert len(result["probabilities"]) == 7
    assert result["probabilities"][0]["label"] == "very_high"
    assert abs(sum(item["probability"] for item in result["probabilities"]) - 1.0) < 1e-5


def test_non_burnable_label_is_translated(monkeypatch):
    # "non-burnable" is the model's hyphenated label; it must map to CLASS_META.
    _install_fake_model(monkeypatch, [0.0, 0.0, 0.0, 0.0, 0.0, 8.0, 0.0])

    result = classify_image_bytes(_png_bytes())

    assert result["predicted"] == "non-burnable"
    assert result["predicted_ru"] == "Не горит"
    assert result["risk_level"] == "low"


def test_empty_or_invalid_image_raises():
    with pytest.raises(FireImageModelError):
        classify_image_bytes(b"")
    with pytest.raises(FireImageModelError):
        classify_image_bytes(b"not an image")


def test_model_status_reports_disabled(monkeypatch):
    monkeypatch.setattr(fire_image, "ENABLED", False)
    monkeypatch.setattr(fire_image, "_state", "not_loaded")

    status = model_status()

    assert status["enabled"] is False
    assert status["state"] == "disabled"
