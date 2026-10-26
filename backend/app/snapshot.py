"""Convert uploaded snapshots (TIFF / GeoTIFF) to the RGB PNG used by U-Net.

The georeference is kept as a WGS84 extent so the map can place the snapshot
at its real coordinates. Plain PNG/JPG uploads have no extent.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

TIFF_EXTENSIONS = {".tif", ".tiff"}


class SnapshotError(ValueError):
    """Raised when a snapshot cannot be read or converted."""


def _to_uint8(bands: np.ndarray) -> np.ndarray:
    if bands.dtype == np.uint8:
        return bands
    out = np.zeros(bands.shape, dtype=np.uint8)
    for index, band in enumerate(bands):
        low, high = np.percentile(band, [2, 98])
        scale = (high - low) or 1.0
        out[index] = np.clip((band - low) / scale * 255.0, 0, 255).astype(np.uint8)
    return out


def build_road_overlay(mask_path: Path, overlay_path: Path) -> None:
    """Write a transparent RGBA layer: road pixels red, everything else clear.

    The layer is meant to be drawn over the map, so the basemap stays visible.
    """
    mask = np.array(Image.open(mask_path).convert("L")) > 0
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask] = (220, 38, 38, 190)
    Image.fromarray(rgba, mode="RGBA").save(overlay_path)


def convert_tiff_snapshot(source: Path, png_path: Path) -> list[float] | None:
    """Write an 8-bit RGB PNG and return ``[south, west, north, east]`` in WGS84.

    Returns ``None`` when the file has no coordinate reference system.
    """
    import rasterio
    from rasterio.warp import transform_bounds

    try:
        with rasterio.open(source) as src:
            indexes = [1, 2, 3] if src.count >= 3 else [1, 1, 1]
            rgb = _to_uint8(src.read(indexes=indexes))
            if src.crs is None:
                bounds = None
            else:
                west, south, east, north = transform_bounds(
                    src.crs, "EPSG:4326", *src.bounds
                )
                bounds = [south, west, north, east]
    except Exception as error:
        raise SnapshotError(f"Не удалось прочитать TIFF: {error}") from error

    Image.fromarray(np.transpose(rgb, (1, 2, 0)), mode="RGB").save(png_path)
    return bounds
