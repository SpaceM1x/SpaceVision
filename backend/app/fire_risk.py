"""Fire probability model (logistic / log-odds form).

``P_base`` is a logistic model over normalised ``[0, 1]`` features:

    logit(P) = B0 + B_ROAD·x_road + B_SETTLEMENT·x_settlement
                  + B_ROAD_DENSITY·ρ_roads + B_SETTLEMENT_DENSITY·ρ_settlements
                  + B_SEASON·season + B_DIURNAL·diurnal
                  + B_FIRE_WEATHER·fwi
                  + B_INTERACTION·x_road·x_settlement

    P_base = 1 / (1 + exp(−logit(P)))

Roads are accounted exactly once: ``x_road`` uses the SHP road distance when
the uploaded layer is available (authoritative) and falls back to the OSM
distance otherwise. The legacy additive term ``alpha·I(R)·(1 − P_base)`` is
gone, so the final probability is ``P_fire = P_base``.

The coefficients below are provisional hand-set log-odds weights. They keep
the model monotonic and bounded, and are meant to be replaced by coefficients
fitted/calibrated on historical fire data.
"""
from __future__ import annotations

import math
from datetime import datetime

from .road_influence import road_influence

# Logistic coefficients (log-odds units).  The intercept is intentionally low:
# an average remote point should not show a double-digit annual probability.
# The weather term (Nesterov index) supplies most of the temporal variation.
B0 = -7.0
B_ROAD = 1.6
B_SETTLEMENT = 1.0
B_ROAD_DENSITY = 0.5
B_SETTLEMENT_DENSITY = 0.3
B_SEASON = 0.6
B_DIURNAL = 0.2
B_INTERACTION = 0.6
B_FIRE_WEATHER = 2.4

# Default road-influence scale used when no explicit R0 is supplied.
DEFAULT_ROAD_R0_METERS = 500.0
SETTLEMENT_PROXIMITY_SCALE = 3000.0  # metres

# Continental-climate monthly risk weights.
_SEASONAL_WEIGHTS = {
    1: -4.0, 2: -3.0, 3: -1.0, 4: 3.0, 5: 7.0, 6: 10.0,
    7: 11.0, 8: 8.0, 9: 4.0, 10: 1.0, 11: -2.0, 12: -4.0,
}
_SEASONAL_MIN = min(_SEASONAL_WEIGHTS.values())
_SEASONAL_RANGE = max(_SEASONAL_WEIGHTS.values()) - _SEASONAL_MIN


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _sigmoid(value: float) -> float:
    """Numerically stable logistic function."""
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _seasonal_factor(month: int) -> float:
    """Normalised ``[0, 1]`` seasonal factor for the continental climate."""
    weight = _SEASONAL_WEIGHTS.get(month, 0.0)
    return _clamp01((weight - _SEASONAL_MIN) / _SEASONAL_RANGE)


def _diurnal_factor(utc_dt: datetime, lon: float) -> float:
    """Normalised ``[0, 1]`` diurnal factor (afternoon peak at 15:00 local)."""
    local_hour = (utc_dt.hour + lon / 15.0) % 24.0
    return math.exp(-((local_hour - 15.0) ** 2) / (2 * 3.2**2))


def _effective_road_distance(
    road_distance_m: float | None, road_distance_shp_m: float | None
) -> tuple[float | None, str]:
    """Pick one road distance: the SHP layer wins over the OSM fallback."""
    if road_distance_shp_m is not None:
        return road_distance_shp_m, "shp"
    if road_distance_m is not None:
        return road_distance_m, "osm"
    return None, "none"


def _base_components(
    *,
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    road_density: float,
    settlement_density: float,
    now_utc: datetime,
    lon: float,
    road_distance_shp_m: float | None = None,
    road_r0_m: float = DEFAULT_ROAD_R0_METERS,
    fire_weather_index: float = 0.0,
) -> dict:
    """Compute every logit feature of the model and the resulting probability."""
    effective_road_distance, road_source = _effective_road_distance(
        road_distance_m, road_distance_shp_m
    )
    road_proximity = (
        road_influence(effective_road_distance, road_r0_m)
        if effective_road_distance is not None
        else 0.0
    )
    settlement_proximity = (
        math.exp(-settlement_distance_m / SETTLEMENT_PROXIMITY_SCALE)
        if settlement_distance_m is not None
        else 0.0
    )
    road_density = _clamp01(road_density or 0.0)
    settlement_density = _clamp01(settlement_density or 0.0)
    season = _seasonal_factor(now_utc.month)
    diurnal = _diurnal_factor(now_utc, lon)
    fire_weather = _clamp01(fire_weather_index or 0.0)
    interaction = road_proximity * settlement_proximity

    coefficients = {
        "constant": B0,
        "road": B_ROAD,
        "settlement": B_SETTLEMENT,
        "road_density": B_ROAD_DENSITY,
        "settlement_density": B_SETTLEMENT_DENSITY,
        "season": B_SEASON,
        "diurnal": B_DIURNAL,
        "fire_weather": B_FIRE_WEATHER,
        "interaction": B_INTERACTION,
    }

    # Per-factor contributions in log-odds units.
    constant = B0
    road_contribution = B_ROAD * road_proximity
    settlement_contribution = B_SETTLEMENT * settlement_proximity
    road_density_contribution = B_ROAD_DENSITY * road_density
    settlement_density_contribution = B_SETTLEMENT_DENSITY * settlement_density
    season_contribution = B_SEASON * season
    diurnal_contribution = B_DIURNAL * diurnal
    fire_weather_contribution = B_FIRE_WEATHER * fire_weather
    interaction_contribution = B_INTERACTION * interaction

    logit = (
        constant
        + road_contribution
        + settlement_contribution
        + road_density_contribution
        + settlement_density_contribution
        + season_contribution
        + diurnal_contribution
        + fire_weather_contribution
        + interaction_contribution
    )
    p_base = _sigmoid(logit)

    return {
        "road_distance_m": effective_road_distance,
        "road_distance_osm_m": road_distance_m,
        "road_distance_shp_m": road_distance_shp_m,
        "road_source": road_source,
        "road_r0_m": road_r0_m,
        "settlement_distance_m": settlement_distance_m,
        "road_proximity": road_proximity,
        "settlement_proximity": settlement_proximity,
        "road_density": road_density,
        "settlement_density": settlement_density,
        "season_month": now_utc.month,
        "season": season,
        "diurnal": diurnal,
        "fire_weather_index": fire_weather,
        "interaction": interaction,
        "coefficients": coefficients,
        "constant": constant,
        "road_contribution": road_contribution,
        "settlement_contribution": settlement_contribution,
        "road_density_contribution": road_density_contribution,
        "settlement_density_contribution": settlement_density_contribution,
        "season_contribution": season_contribution,
        "diurnal_contribution": diurnal_contribution,
        "fire_weather_contribution": fire_weather_contribution,
        "interaction_contribution": interaction_contribution,
        "logit": logit,
        "p_base": p_base,
    }


def base_probability(
    *,
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    road_density: float,
    settlement_density: float,
    now_utc: datetime,
    lon: float,
    road_distance_shp_m: float | None = None,
    road_r0_m: float = DEFAULT_ROAD_R0_METERS,
    fire_weather_index: float = 0.0,
) -> float:
    """Return the logistic probability ``P_base`` in ``(0, 1)``."""
    return _base_components(
        road_distance_m=road_distance_m,
        settlement_distance_m=settlement_distance_m,
        road_density=road_density,
        settlement_density=settlement_density,
        now_utc=now_utc,
        lon=lon,
        road_distance_shp_m=road_distance_shp_m,
        road_r0_m=road_r0_m,
        fire_weather_index=fire_weather_index,
    )["p_base"]


def base_probability_breakdown(
    *,
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    road_density: float,
    settlement_density: float,
    now_utc: datetime,
    lon: float,
    road_distance_shp_m: float | None = None,
    road_r0_m: float = DEFAULT_ROAD_R0_METERS,
    fire_weather_index: float = 0.0,
) -> dict:
    """Return the full model breakdown (logit, each factor, the result)."""
    return _base_components(
        road_distance_m=road_distance_m,
        settlement_distance_m=settlement_distance_m,
        road_density=road_density,
        settlement_density=settlement_density,
        now_utc=now_utc,
        lon=lon,
        road_distance_shp_m=road_distance_shp_m,
        road_r0_m=road_r0_m,
        fire_weather_index=fire_weather_index,
    )


def final_probability(p_base: float) -> float:
    """Return ``P_fire``: the road contribution is already inside ``P_base``."""
    return _clamp01(p_base)


def risk_level_from_probability(probability: float) -> str:
    """Map a 0..100 percentage to a risk level.

    The thresholds follow the recalibrated model: a typical remote point is
    well below 2%, while a dry summer point near a road and a settlement can
    exceed 10%.
    """
    if probability >= 10.0:
        return "high"
    if probability >= 2.0:
        return "medium"
    return "low"
