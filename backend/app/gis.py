"""GIS / CRS utilities.

The distance-to-road calculation must be done in metres, so geometries are
reprojected into a metric (metre-based) CRS before any distance is computed.
"""
from __future__ import annotations

import math

import geopandas as gpd
from pyproj import CRS

WGS84 = "EPSG:4326"


def ensure_known_crs(gdf: gpd.GeoDataFrame) -> CRS:
    """Return the CRS of *gdf* or raise a clear error when it is missing."""
    if gdf.crs is None:
        raise ValueError(
            "The road data has no CRS (missing or empty .prj file). "
            "Refusing to guess the CRS — provide a valid .prj file."
        )
    return gdf.crs


def utm_zone_epsg(longitude: float, latitude: float) -> int:
    """Return the EPSG code of the UTM zone containing the given point.

    Each UTM zone spans 6 degrees of longitude; this is a deterministic mapping
    rather than a guess about the *source* data CRS.
    """
    zone = int(math.floor((longitude + 180.0) / 6.0)) + 1
    zone = max(1, min(60, zone))
    return 32600 + zone if latitude >= 0 else 32700 + zone


def select_metric_crs(gdf: gpd.GeoDataFrame, configured_crs: str | None = None) -> CRS:
    """Pick a metric CRS for distance calculations.

    Uses *configured_crs* when provided, otherwise derives the UTM zone from the
    centroid of the data.
    """
    if configured_crs:
        return CRS.from_user_input(configured_crs)

    ensure_known_crs(gdf)
    centroid = gdf.to_crs(WGS84).geometry.union_all().centroid
    return CRS.from_epsg(utm_zone_epsg(centroid.x, centroid.y))


def to_metric(gdf: gpd.GeoDataFrame, metric_crs: CRS) -> gpd.GeoDataFrame:
    """Reproject *gdf* into the given metric CRS."""
    ensure_known_crs(gdf)
    return gdf.to_crs(metric_crs)
