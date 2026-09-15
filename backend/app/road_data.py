"""Loading road geometries from an ESRI Shapefile."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import geopandas as gpd
from pyproj import CRS
from shapely.strtree import STRtree

from .gis import select_metric_crs, to_metric


class RoadDataError(RuntimeError):
    """Raised when the road source cannot be loaded or validated."""


class RoadDataProvider:
    """Loads and validates road geometries from a Shapefile."""

    def __init__(self, shp_path: str | Path):
        self.shp_path = Path(shp_path)

    def load(self) -> gpd.GeoDataFrame:
        """Read and validate the shapefile (no CRS guessing)."""
        if not self.shp_path.exists():
            raise RoadDataError(
                f"Road shapefile not found: {self.shp_path}. "
                "Provide a valid ESRI Shapefile (.shp/.shx/.dbf/.prj/.cpg)."
            )

        self._ensure_sidecar_files()

        try:
            gdf = gpd.read_file(self.shp_path)
        except Exception as exc:  # pragma: no cover - depends on the OGR driver
            raise RoadDataError(f"Failed to read shapefile {self.shp_path}: {exc}") from exc

        if gdf.empty:
            raise RoadDataError(f"Shapefile {self.shp_path} contains no geometries.")

        if gdf.crs is None:
            raise RoadDataError(
                f"Shapefile {self.shp_path} has no CRS. "
                "A valid .prj file is required; refusing to guess the CRS."
            )

        # Drop null/empty geometries.
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        if gdf.empty:
            raise RoadDataError(
                f"Shapefile {self.shp_path} contains no valid road geometries."
            )
        return gdf

    def _ensure_sidecar_files(self) -> None:
        base = self.shp_path.with_suffix("")
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            candidate = Path(f"{base}{ext}")
            if not candidate.exists():
                raise RoadDataError(
                    f"Missing sidecar file {candidate.name} for shapefile {self.shp_path.name}."
                )


@dataclass
class RoadsCache:
    """Persistent in-memory cache of the loaded road network.

    Holds the validated GeoDataFrame, the chosen metric CRS, the reprojected
    metric GeoDataFrame, and an STRtree over the metric geometries so that
    per-request work (re-reading the SHP, reprojection, tree building) is done
    once and reused until the roads are re-uploaded or cleared.
    """

    gdf: gpd.GeoDataFrame
    metric_crs: CRS
    roads_metric: gpd.GeoDataFrame
    tree: STRtree


_cache: Optional[RoadsCache] = None
_cache_lock = threading.Lock()


def build_roads_cache(
    shp_path: str | Path, configured_crs: str | None = None
) -> RoadsCache:
    """Load, validate and precompute the road cache; store it globally."""
    gdf = RoadDataProvider(shp_path).load()
    metric_crs = select_metric_crs(gdf, configured_crs)
    roads_metric = to_metric(gdf, metric_crs)
    tree = STRtree(list(roads_metric.geometry))
    cache = RoadsCache(gdf=gdf, metric_crs=metric_crs, roads_metric=roads_metric, tree=tree)
    global _cache
    with _cache_lock:
        _cache = cache
    return cache


def get_roads_cache() -> Optional[RoadsCache]:
    """Return the current road cache (or ``None`` if not built yet)."""
    with _cache_lock:
        return _cache


def invalidate_roads_cache() -> None:
    """Drop the cached road data (call after upload/clear of the SHP)."""
    global _cache
    with _cache_lock:
        _cache = None
