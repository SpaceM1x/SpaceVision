"""App configuration (env-overridable)."""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_shp_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return (_PROJECT_ROOT / path).resolve()


ROADS_SHP_PATH = _resolve_shp_path(os.environ.get("ROADS_SHP_PATH", "gis/roads/roads.shp"))

# SHP road influence: characteristic distance (m) and weight.
R0_METERS = float(os.environ.get("R0_METERS", "500.0"))
ALPHA = float(os.environ.get("ALPHA", "0.30"))

# Metric CRS for distance calculations; empty -> derive UTM zone automatically.
METRIC_CRS = os.environ.get("METRIC_CRS", "").strip() or None

# Fallback map centre (Zaigraevsky district).
DEFAULT_MAP_CENTER = (51.85, 108.27)
DEFAULT_MAP_ZOOM = 9
