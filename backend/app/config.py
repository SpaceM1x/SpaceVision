"""Configuration for the Zaigraevsky (no-ML) GIS version.

Every road/risk parameter is configurable via environment variables so that no
value is hard-coded inside the pipeline logic itself.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Road source (ESRI Shapefile) -----------------------------------------
# Path to the roads shapefile. A valid shapefile consists of the companion
# files: .shp, .shx, .dbf, .prj (and optionally .cpg).
ROADS_SHP_PATH = Path(os.environ.get("ROADS_SHP_PATH", "gis/roads/roads.shp")).resolve()

# --- Road influence model --------------------------------------------------
# Characteristic influence distance, in metres.
R0_METERS = float(os.environ.get("R0_METERS", "500.0"))

# Maximum road influence (0..1).
ALPHA = float(os.environ.get("ALPHA", "0.5"))

# --- Metric CRS for distance calculations ---------------------------------
# When set (e.g. "EPSG:32648"), this CRS is used for the metre-based distance
# computation. When empty, the UTM zone is derived automatically from the
# centroid of the loaded road data (a well-established mapping, not a guess).
METRIC_CRS = os.environ.get("METRIC_CRS", "").strip() or None

# --- Target area -----------------------------------------------------------
# Zaigraevsky district, Republic of Buryatia, Russia.
# Used only as a fallback map centre in the frontend when no road data has been
# loaded yet. It is an approximate, well-known location of the district.
DEFAULT_MAP_CENTER = (51.85, 108.27)
DEFAULT_MAP_ZOOM = 9
