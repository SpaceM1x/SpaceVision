"""Distance to the nearest road, computed in metres."""
from __future__ import annotations

import math

import geopandas as gpd
import numpy as np
from shapely.geometry import Point


def distance_to_nearest_feature(
    point_metric: Point,
    features_metric,
    tree=None,
    *,
    label: str = "feature",
) -> float:
    """Distance (m) from ``point_metric`` to the nearest vector feature.

    The function is intentionally layer-agnostic: roads, settlements and other
    vector layers use the same metric CRS and an optional prebuilt STRtree.
    """
    if features_metric is None or features_metric.empty:
        raise ValueError(f"Cannot compute distance: {label} data is empty.")

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

    distances = features_metric.geometry.distance(point_metric)
    return float(distances.min())


def distance_to_nearest_road(point_metric: Point, roads_metric, tree=None) -> float:
    """Distance (m) from point_metric to the nearest road (same metric CRS).

    Kept as a named wrapper for the road-specific call sites and tests.
    """
    return distance_to_nearest_feature(
        point_metric, roads_metric, tree, label="road"
    )


def road_density_near_point(
    point_metric: Point,
    roads_metric,
    tree=None,
    radius_m: float = 5000.0,
) -> float:
    """Road length per square kilometre inside a circular neighbourhood.

    Returns ``0.0`` when no road crosses the buffer.  The value is deliberately
    left in physical units (km/km²); callers normalise it before feeding the
    logistic model.  Using the uploaded SHP layer makes the density factor
    meaningful even when the optional OSM lookup is unavailable.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive.")
    if roads_metric is None or roads_metric.empty:
        return 0.0

    buffer = point_metric.buffer(radius_m)
    if tree is not None:
        indices = tree.query(buffer)
        geometries = roads_metric.geometry
        candidates = [
            geometries.iloc[int(index)]
            for index in np.ravel(indices)
            if 0 <= int(index) < len(geometries)
        ]
    else:
        candidates = list(roads_metric.geometry)

    total_length_m = 0.0
    for geometry in candidates:
        if geometry is None or geometry.is_empty:
            continue
        try:
            total_length_m += float(geometry.intersection(buffer).length)
        except Exception:  # pragma: no cover - invalid geometry in user SHP
            continue

    area_km2 = math.pi * (radius_m / 1000.0) ** 2
    return total_length_m / 1000.0 / area_km2 if area_km2 > 0 else 0.0
