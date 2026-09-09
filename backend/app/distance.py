"""Distance to the nearest road, computed in metres."""
from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point


def distance_to_nearest_road(point_metric: Point, roads_metric: gpd.GeoDataFrame) -> float:
    """Return the distance in metres from *point_metric* to the nearest road.

    Both the point and the roads must already be expressed in the same metric
    (metre-based) CRS. The returned value is therefore in metres. A point that
    lies exactly on a road yields ``0.0``.
    """
    if roads_metric is None or roads_metric.empty:
        raise ValueError("Cannot compute distance: road data is empty.")
    distances = roads_metric.geometry.distance(point_metric)
    return float(distances.min())
