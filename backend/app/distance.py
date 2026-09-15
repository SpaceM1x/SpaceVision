"""Distance to the nearest road, computed in metres."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import Point


def distance_to_nearest_road(point_metric: Point, roads_metric, tree=None) -> float:
    """Distance (m) from point_metric to the nearest road (same metric CRS).

    When a prebuilt ``tree`` (shapely ``STRtree`` over the metric geometries)
    is supplied, the nearest geometry is resolved in O(log N) instead of an
    O(N) scan across every road. Without a tree it falls back to the
    vectorized GeoDataFrame distance so callers that only have the raw data
    keep working.
    """
    if roads_metric is None or roads_metric.empty:
        raise ValueError("Cannot compute distance: road data is empty.")

    if tree is not None:
        # Prefer the convenience API when the shapely version provides it,
        # otherwise fall back to ``nearest`` (index) + ``geometries``.
        if hasattr(tree, "nearest_geometry"):
            nearest = tree.nearest_geometry(point_metric)
        else:
            index = tree.nearest(point_metric)
            geoms = tree.geometries
            nearest = geoms[int(np.ravel(index)[0])]
        d = point_metric.distance(nearest)
        return float(d) if d < float("inf") else float("inf")

    distances = roads_metric.geometry.distance(point_metric)
    return float(distances.min())
