from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image
import torch
import torch.nn as nn


MODEL_INPUT_SIZE = 256
THRESHOLD = 0.5
_MODEL: torch.nn.Module | None = None
_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _checkpoint_path() -> Path:
    configured = os.environ.get("ROAD_MODEL_PATH")
    if configured:
        return Path(configured)
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "road_segmentation" / "checkpoints" / "best_road_seg_unet.pth"


class ConvBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
        )

    def forward(self, x):
        return self.conv(x)


class UNet(nn.Module):
    """U-Net with a sigmoid output, matching the checkpoint's layer layout."""

    def __init__(self, in_channels: int = 3, out_channels: int = 1):
        super().__init__()
        self.enc1 = ConvBlock(in_channels, 64)
        self.enc2 = ConvBlock(64, 128)
        self.enc3 = ConvBlock(128, 256)
        self.enc4 = ConvBlock(256, 512)
        self.pool = nn.MaxPool2d(2)
        self.bottleneck = ConvBlock(512, 1024)
        self.upconv4 = nn.ConvTranspose2d(1024, 512, kernel_size=2, stride=2)
        self.dec4 = ConvBlock(1024, 512)
        self.upconv3 = nn.ConvTranspose2d(512, 256, kernel_size=2, stride=2)
        self.dec3 = ConvBlock(512, 256)
        self.upconv2 = nn.ConvTranspose2d(256, 128, kernel_size=2, stride=2)
        self.dec2 = ConvBlock(256, 128)
        self.upconv1 = nn.ConvTranspose2d(128, 64, kernel_size=2, stride=2)
        self.dec1 = ConvBlock(128, 64)
        self.conv_final = nn.Conv2d(64, out_channels, kernel_size=1)

    def forward(self, x):
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        e4 = self.enc4(self.pool(e3))
        b = self.bottleneck(self.pool(e4))
        d4 = self.dec4(torch.cat([self.upconv4(b), e4], dim=1))
        d3 = self.dec3(torch.cat([self.upconv3(d4), e3], dim=1))
        d2 = self.dec2(torch.cat([self.upconv2(d3), e2], dim=1))
        d1 = self.dec1(torch.cat([self.upconv1(d2), e1], dim=1))
        return torch.sigmoid(self.conv_final(d1))


def _load_model() -> torch.nn.Module:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    checkpoint_path = _checkpoint_path()
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

    model = UNet(in_channels=3, out_channels=1)
    state_dict = torch.load(checkpoint_path, map_location=_DEVICE, weights_only=True)
    model.load_state_dict(state_dict)
    model.to(_DEVICE)
    model.eval()
    _MODEL = model
    return model


def _predict_probabilities(image_rgb: np.ndarray, model: torch.nn.Module) -> np.ndarray:
    """Road probability per pixel of the original image.

    The whole image is resized to the model input size, as in the model's own
    inference script, and the result is resized back to the original size.
    """
    height, width = image_rgb.shape[:2]
    small = Image.fromarray(image_rgb).resize((MODEL_INPUT_SIZE, MODEL_INPUT_SIZE), Image.BILINEAR)
    tensor = torch.from_numpy(np.array(small).transpose(2, 0, 1)).float().unsqueeze(0) / 255.0
    with torch.no_grad():
        probs = model(tensor.to(_DEVICE))[0, 0].cpu().numpy()
    full = Image.fromarray(probs.astype(np.float32), mode="F").resize((width, height), Image.BILINEAR)
    return np.array(full)


def run_road_segmentation(image_path: Path, prediction_dir: Path, threshold: float = THRESHOLD) -> tuple[Path, Path]:
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
