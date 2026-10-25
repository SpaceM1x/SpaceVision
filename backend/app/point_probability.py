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
    source: str  # manual | shp | osm | none


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
    explicit: float | None,
    layer: VectorLayerCache | None,
    osm_value: float | None,
    lat: float,
    lon: float,
    label: str,
) -> ResolvedDistance:
    if explicit is not None:
        return ResolvedDistance(float(explicit), "manual")
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
    """Resolve distances automatically and calculate lower/base/upper risk.

    Priority for each distance:
    1. an explicit ``*_distance_m`` argument (manual/what-if mode);
    2. a local vector layer (``roads`` or ``settlements``);
    3. the optional OSM lookup (``osm_lookup``);
    4. otherwise the distance is missing and ``DistanceDataError`` is raised.

    The caller can pass preloaded ``VectorLayerCache`` objects, so this function
    does not know how the SHP files were obtained.  Use
    :func:`app.vector_data.build_vector_cache` to load a layer from a file.
    """
    need_osm = (
        road_distance_m is None
        and roads is None
        or settlement_distance_m is None
        and settlements is None
    )
    osm_context: Mapping[str, float | None] = {}
    if need_osm and osm_lookup is not None:
        osm_context = osm_lookup(lat, lon)

    road = _resolve_distance(
        explicit=road_distance_m,
        layer=roads,
        osm_value=osm_context.get("road_distance_m"),
        lat=lat,
        lon=lon,
        label="road",
    )
    settlement = _resolve_distance(
        explicit=settlement_distance_m,
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
            + ". Загрузите векторный слой или передайте расстояние явно."
        )

    result = calculate_fire_probability(
        road.distance_m,
        settlement.distance_m,
        area_ha=area_ha,
    )
    return PointProbabilityResult(result=result, road=road, settlement=settlement)
