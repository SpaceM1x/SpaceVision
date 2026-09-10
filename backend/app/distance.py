"""Distance to the nearest road, computed in metres."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point


def distance_to_nearest_road(point_metric: Point, roads_metric: gpd.GeoDataFrame) -> float:
    """Distance (m) from point_metric to the nearest road (same metric CRS)."""
    if roads_metric is None or roads_metric.empty:
        raise ValueError("Cannot compute distance: road data is empty.")
    distances = roads_metric.geometry.distance(point_metric)
    return float(distances.min())
