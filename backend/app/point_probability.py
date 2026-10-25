"""Point-level distance resolution for the annual fire-probability model."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from pyproj import Transformer
from shapely.geometry import Point

from .distance import distance_to_nearest_feature
from .fire_probability import FireProbabilityResult, calculate_fire_probability
from .vector_data import VectorLayerCache


class DistanceDataError(RuntimeError):
    """Raised when a required road/settlement distance cannot be resolved."""


@dataclass(frozen=True)
class ResolvedDistance:
    """A distance and the source that supplied it."""

    distance_m: float | None
    source: str  # map | shp | osm | none


@dataclass(frozen=True)
class PointProbabilityResult:
    """Model result together with distance provenance."""

    result: FireProbabilityResult
    road: ResolvedDistance
    settlement: ResolvedDistance


def nearest_distance_m(
    lat: float,
    lon: float,
    layer: VectorLayerCache,
    *,
    label: str,
) -> float:
    """Distance in metres from a WGS84 point to the nearest layer feature."""
    transformer = Transformer.from_crs(
        "EPSG:4326", layer.metric_crs, always_xy=True
    )
    x, y = transformer.transform(lon, lat)
    point_metric = Point(x, y)
    try:
        return distance_to_nearest_feature(
            point_metric,
            layer.metric_gdf,
            layer.tree,
            label=label,
        )
    except ValueError as error:
        raise DistanceDataError(str(error)) from error


def _resolve_distance(
    *,
    map_value: float | None,
    layer: VectorLayerCache | None,
    osm_value: float | None,
    lat: float,
    lon: float,
    label: str,
) -> ResolvedDistance:
    # Distances measured by the Leaflet map module are authoritative.
    if map_value is not None:
        return ResolvedDistance(float(map_value), "map")
    if layer is not None:
        return ResolvedDistance(
            nearest_distance_m(lat, lon, layer, label=label),
            "shp",
        )
    if osm_value is not None:
        return ResolvedDistance(float(osm_value), "osm")
    return ResolvedDistance(None, "none")


def calculate_point_fire_probability(
    lat: float,
    lon: float,
    *,
    area_ha: float = 1.0,
    roads: VectorLayerCache | None = None,
    settlements: VectorLayerCache | None = None,
    road_distance_m: float | None = None,
    settlement_distance_m: float | None = None,
    osm_lookup: Callable[[float, float], Mapping[str, float | None]] | None = None,
) -> PointProbabilityResult:
    """Resolve distances and calculate the annual formula probability.

    Priority for each distance:
    1. the value measured in the Leaflet map module (``road_distance_m`` /
       ``settlement_distance_m``);
    2. the local vector layer (``roads`` or ``settlements``) as a fallback;
    3. the optional OSM lookup (``osm_lookup``) as a last resort;
    4. otherwise the distance is missing and ``DistanceDataError`` is raised.

    The map values are the normal path: the browser measures the distance to
    the nearest feature of the displayed layers and passes both numbers to the
    API.
    """
    need_osm = (
        (road_distance_m is None and roads is None)
        or (settlement_distance_m is None and settlements is None)
    )
    osm_context: Mapping[str, float | None] = {}
    if need_osm and osm_lookup is not None:
        osm_context = osm_lookup(lat, lon)

    road = _resolve_distance(
        map_value=road_distance_m,
        layer=roads,
        osm_value=osm_context.get("road_distance_m"),
        lat=lat,
        lon=lon,
        label="road",
    )
    settlement = _resolve_distance(
        map_value=settlement_distance_m,
        layer=settlements,
        osm_value=osm_context.get("settlement_distance_m"),
        lat=lat,
        lon=lon,
        label="settlement",
    )

    missing = [
        name
        for name, resolved in (("дорога", road), ("населённый пункт", settlement))
        if resolved.distance_m is None
    ]
    if missing:
        raise DistanceDataError(
            "Недостаточно данных для расчёта: нет расстояния до слоя "
            + ", ".join(missing)
            + ". Включите соответствующий слой карты или загрузите векторный слой."
        )

    result = calculate_fire_probability(
        road.distance_m,
        settlement.distance_m,
        area_ha=area_ha,
    )
    return PointProbabilityResult(result=result, road=road, settlement=settlement)
