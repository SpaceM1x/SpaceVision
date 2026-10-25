"""Optional settlements layer loaded from an ESRI Shapefile.

The application can work with OSM settlements, but a local vector layer is more
stable and is preferred when present.  Set ``SETTLEMENTS_SHP_PATH`` to a
shapefile with point (or polygon) settlement features.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from .vector_data import (
    VectorDataError,
    VectorLayerCache,
    build_vector_cache,
)


class SettlementDataError(VectorDataError):
    """Raised when the optional settlements layer cannot be loaded."""


_cache: Optional[VectorLayerCache] = None
_cache_lock = threading.Lock()


def build_settlements_cache(
    shp_path: str | Path,
    configured_crs: str | None = None,
) -> VectorLayerCache:
    """Load the settlements layer and keep it in memory for later requests."""
    try:
        cache = build_vector_cache(
            shp_path, configured_crs, label="settlement"
        )
    except VectorDataError as error:
        raise SettlementDataError(str(error)) from error

    global _cache
    with _cache_lock:
        _cache = cache
    return cache


def get_settlements_cache() -> Optional[VectorLayerCache]:
    """Return the current settlements cache, if it has been built."""
    with _cache_lock:
        return _cache


def invalidate_settlements_cache() -> None:
    """Drop the cached settlements layer (useful after replacing the SHP)."""
    global _cache
    with _cache_lock:
        _cache = None
