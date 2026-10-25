"""Satellite tile helpers for the point-level AI risk method.

The pretrained image classifier expects an RGB image, while the map works with
geographic coordinates.  This module converts a point to a slippy-map tile,
downloads it from Esri World Imagery and caches the bytes on disk.  No API key
is required for the public tile endpoint.
"""
from __future__ import annotations

import math
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .database import DATA_DIR

TILE_CACHE_DIR = DATA_DIR / "satellite_tiles"
DEFAULT_ZOOM = 15
_TILE_URL_TEMPLATE = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
_TIMEOUT_SECONDS = 8.0
_cache_lock = threading.Lock()


class SatelliteTileError(RuntimeError):
    """Raised when a satellite tile cannot be downloaded or read."""


def tile_xy(lat: float, lon: float, zoom: int = DEFAULT_ZOOM) -> tuple[int, int]:
    """Return the Web-Mercator tile coordinates containing ``lat``/``lon``."""
    if not (-85.05112878 <= lat <= 85.05112878):
        raise ValueError("Широта вне диапазона Web-Mercator.")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("Долгота вне диапазона.")
    if zoom < 0 or zoom > 22:
        raise ValueError("Некорректный уровень масштаба.")

    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int(
        (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    )
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_url(x: int, y: int, zoom: int = DEFAULT_ZOOM) -> str:
    return _TILE_URL_TEMPLATE.format(z=zoom, x=x, y=y)


def _cache_path(x: int, y: int, zoom: int) -> Path:
    return TILE_CACHE_DIR / str(zoom) / str(x) / f"{y}.jpg"


def fetch_satellite_tile(
    lat: float, lon: float, zoom: int = DEFAULT_ZOOM
) -> dict:
    """Download (or read from cache) the satellite tile for a point."""
    x, y = tile_xy(lat, lon, zoom)
    path = _cache_path(x, y, zoom)
    with _cache_lock:
        if path.exists() and path.stat().st_size > 0:
            return {
                "data": path.read_bytes(),
                "z": zoom,
                "x": x,
                "y": y,
                "url": tile_url(x, y, zoom),
                "cached": True,
            }

    request = Request(
        tile_url(x, y, zoom),
        headers={"User-Agent": "SpaceVision/1.0", "Accept": "image/jpeg"},
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            data = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SatelliteTileError(
            f"Не удалось загрузить космоснимок участка: {error}"
        ) from error

    if not data:
        raise SatelliteTileError("Сервер вернул пустой космоснимок участка.")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        # A cache write failure must not prevent the classification.
        pass

    return {
        "data": data,
        "z": zoom,
        "x": x,
        "y": y,
        "url": tile_url(x, y, zoom),
        "cached": False,
    }
