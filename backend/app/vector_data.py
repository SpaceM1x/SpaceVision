"""Generic ESRI Shapefile loader and metric cache.

Roads have their own long-lived cache in :mod:`app.road_data` because they are
uploaded and invalidated through the API.  This module provides the same basic
loading/validation behaviour for any other optional vector layer (for example,
settlements) without coupling it to the road upload workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from pyproj import CRS
from shapely.strtree import STRtree

from .gis import select_metric_crs, to_metric


class VectorDataError(RuntimeError):
    """Raised when an optional vector layer cannot be loaded or validated."""


class VectorDataProvider:
    """Load and validate a vector layer from an ESRI Shapefile."""

    def __init__(self, shp_path: str | Path, *, label: str = "vector"):
        self.shp_path = Path(shp_path)
        self.label = label

    def load(self) -> gpd.GeoDataFrame:
        if not self.shp_path.exists():
            raise VectorDataError(
                f"{self.label.capitalize()} shapefile not found: {self.shp_path}. "
                "Provide a valid ESRI Shapefile (.shp/.shx/.dbf/.prj/.cpg)."
            )

        self._ensure_sidecar_files()

        try:
            gdf = gpd.read_file(self.shp_path)
        except Exception as exc:  # pragma: no cover - depends on the OGR driver
            raise VectorDataError(
                f"Failed to read {self.label} shapefile {self.shp_path}: {exc}"
            ) from exc

        if gdf.empty:
            raise VectorDataError(
                f"{self.label.capitalize()} shapefile {self.shp_path} "
                "contains no geometries."
            )
        if gdf.crs is None:
            raise VectorDataError(
                f"{self.label.capitalize()} shapefile {self.shp_path} has no CRS. "
                "A valid .prj file is required; refusing to guess the CRS."
            )

        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        if gdf.empty:
            raise VectorDataError(
                f"{self.label.capitalize()} shapefile {self.shp_path} "
                "contains no valid geometries."
            )
        return gdf

    def _ensure_sidecar_files(self) -> None:
        base = self.shp_path.with_suffix("")
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            candidate = Path(f"{base}{ext}")
            if not candidate.exists():
                raise VectorDataError(
                    f"Missing sidecar file {candidate.name} for "
                    f"{self.label} shapefile {self.shp_path.name}."
                )


@dataclass
class VectorLayerCache:
    """Loaded layer plus its metric projection and spatial index."""

    gdf: gpd.GeoDataFrame
    metric_crs: CRS
    metric_gdf: gpd.GeoDataFrame
    tree: STRtree


def build_vector_cache(
    shp_path: str | Path,
    configured_crs: str | None = None,
    *,
    label: str = "vector",
) -> VectorLayerCache:
    """Load a vector layer, reproject it and build an STRtree."""
    gdf = VectorDataProvider(shp_path, label=label).load()
    metric_crs = select_metric_crs(gdf, configured_crs)
    metric_gdf = to_metric(gdf, metric_crs)
    tree = STRtree(list(metric_gdf.geometry))
    return VectorLayerCache(
        gdf=gdf,
        metric_crs=metric_crs,
        metric_gdf=metric_gdf,
        tree=tree,
    )
