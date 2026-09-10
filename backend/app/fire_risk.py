"""Fire probability model (rewritten for real spatial separation).

The old additive ``S / 100`` score model is removed. The base probability is now
built from normalised ``[0, 1]`` factors derived from the OSM context plus a
small interaction term::

    road_proximity       = exp(-d_road_osm / 1000)
    settlement_proximity = exp(-d_settlement / 3000)

    P_base = clamp(
        0.05
        + 0.18 * road_proximity
        + 0.20 * settlement_proximity
        + 0.12 * road_density
        + 0.08 * settlement_density
        + 0.15 * season
        + 0.10 * diurnal
        + 0.15 * road_proximity * settlement_proximity,
        0.0, 0.90,
    )

The SHP road influence is kept separate (``road_influence.I(R)``) and adds at
most ~15 percentage points::

    P_fire = P_base + alpha * I(R) * (1 - P_base)      # alpha = 0.15

This additive form is algebraically equal to the former
``1 - (1 - P_base) * (1 - alpha * I(R))``.
"""
from __future__ import annotations

import math
from datetime import datetime

# --- Base-model coefficients -----------------------------------------------
BASE_CONSTANT = 0.05
ROAD_PROXIMITY_WEIGHT = 0.18
ROAD_PROXIMITY_SCALE = 1000.0  # metres
SETTLEMENT_PROXIMITY_WEIGHT = 0.20
SETTLEMENT_PROXIMITY_SCALE = 3000.0  # metres
ROAD_DENSITY_WEIGHT = 0.12
SETTLEMENT_DENSITY_WEIGHT = 0.08
SEASON_WEIGHT = 0.15
DIURNAL_WEIGHT = 0.10
INTERACTION_WEIGHT = 0.15
MAX_BASE_PROBABILITY = 0.90

# Continental-climate monthly risk weights (warm/dry summer is dangerous).
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


def _seasonal_factor(month: int) -> float:
    """Normalised ``[0, 1]`` seasonal factor for the continental climate."""
    weight = _SEASONAL_WEIGHTS.get(month, 0.0)
    return _clamp01((weight - _SEASONAL_MIN) / _SEASONAL_RANGE)


def _diurnal_factor(utc_dt: datetime, lon: float) -> float:
    """Normalised ``[0, 1]`` diurnal factor (afternoon peak at 15:00 local)."""
    local_hour = (utc_dt.hour + lon / 15.0) % 24.0
    return math.exp(-((local_hour - 15.0) ** 2) / (2 * 3.2**2))


def _base_components(
    *,
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    road_density: float,
    settlement_density: float,
    now_utc: datetime,
    lon: float,
) -> dict:
    """Compute every factor of the ``P_base`` model and the resulting value."""
    road_proximity = (
        math.exp(-road_distance_m / ROAD_PROXIMITY_SCALE)
        if road_distance_m is not None
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
    interaction = road_proximity * settlement_proximity

    road_contribution = ROAD_PROXIMITY_WEIGHT * road_proximity
    settlement_contribution = SETTLEMENT_PROXIMITY_WEIGHT * settlement_proximity
    road_density_contribution = ROAD_DENSITY_WEIGHT * road_density
    settlement_density_contribution = SETTLEMENT_DENSITY_WEIGHT * settlement_density
    season_contribution = SEASON_WEIGHT * season
    diurnal_contribution = DIURNAL_WEIGHT * diurnal
    interaction_contribution = INTERACTION_WEIGHT * interaction

    raw_sum = (
        BASE_CONSTANT
        + road_contribution
        + settlement_contribution
        + road_density_contribution
        + settlement_density_contribution
        + season_contribution
        + diurnal_contribution
        + interaction_contribution
    )
    p_base = _clamp(raw_sum, 0.0, MAX_BASE_PROBABILITY)

    return {
        "road_distance_m": road_distance_m,
        "settlement_distance_m": settlement_distance_m,
        "road_proximity": road_proximity,
        "settlement_proximity": settlement_proximity,
        "road_density": road_density,
        "settlement_density": settlement_density,
        "season_month": now_utc.month,
        "season": season,
        "diurnal": diurnal,
        "interaction": interaction,
        "constant": BASE_CONSTANT,
        "road_contribution": road_contribution,
        "settlement_contribution": settlement_contribution,
        "road_density_contribution": road_density_contribution,
        "settlement_density_contribution": settlement_density_contribution,
        "season_contribution": season_contribution,
        "diurnal_contribution": diurnal_contribution,
        "interaction_contribution": interaction_contribution,
        "raw_sum": raw_sum,
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
) -> float:
    """Return the base ignition probability ``P_base`` in ``[0, 0.90]``."""
    return _base_components(
        road_distance_m=road_distance_m,
        settlement_distance_m=settlement_distance_m,
        road_density=road_density,
        settlement_density=settlement_density,
        now_utc=now_utc,
        lon=lon,
    )["p_base"]


def base_probability_breakdown(
    *,
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    road_density: float,
    settlement_density: float,
    now_utc: datetime,
    lon: float,
) -> dict:
    """Return the full ``P_base`` breakdown (each additive factor + the result)."""
    return _base_components(
        road_distance_m=road_distance_m,
        settlement_distance_m=settlement_distance_m,
        road_density=road_density,
        settlement_density=settlement_density,
        now_utc=now_utc,
        lon=lon,
    )


def calculate_fire_probability(p_base: float, influence: float, alpha: float) -> float:
    """Combine ``P_base`` with the SHP road influence ``I(R)``.

    ``P_fire = P_base + alpha * I(R) * (1 - P_base)``.

    All inputs are clamped to ``[0, 1]``, so the result is guaranteed to satisfy
    ``0 <= P_fire <= 1`` and ``P_fire >= P_base`` for ``alpha >= 0``.
    """
    return calculate_fire_probability_breakdown(p_base, influence, alpha)["p_fire"]


def calculate_fire_probability_breakdown(p_base: float, influence: float, alpha: float) -> dict:
    """Return each term of ``P_fire = P_base + alpha * I(R) * (1 - P_base)``."""
    p_base = _clamp01(p_base)
    influence = _clamp01(influence)
    alpha = _clamp01(alpha)

    one_minus_p_base = 1.0 - p_base
    shp_addition = alpha * influence * one_minus_p_base
    p_fire = _clamp01(p_base + shp_addition)

    return {
        "p_base": p_base,
        "influence": influence,
        "alpha": alpha,
        "one_minus_p_base": one_minus_p_base,
        "shp_addition": shp_addition,
        "p_fire": p_fire,
    }


def risk_level_from_probability(probability: float) -> str:
    """Map a 0..100 percentage to a risk level (legacy thresholds)."""
    if probability >= 75:
        return "high"
    if probability >= 45:
        return "medium"
    return "low"
