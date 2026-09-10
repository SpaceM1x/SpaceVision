"""Fire probability model.

Two layers are combined:

1. ``base_probability`` — the pre-existing rule-based ignition model (``P_base``),
   kept intact from the AI version and normalised to ``[0, 1]``.
2. ``calculate_fire_probability`` — combines ``P_base`` with the road influence
   ``I(R)``::

       P_fire = 1 - (1 - P_base) * (1 - alpha * I(R))
"""
from __future__ import annotations

import math
from datetime import datetime


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _distance_decay_score(distance_m: float | None, max_score: float, scale_m: float) -> float:
    if distance_m is None:
        return 0.0
    return max_score * math.exp(-distance_m / scale_m)


def _seasonal_component(month: int) -> float:
    # Approximation for a continental climate: higher risk in the warm dry season.
    month_weights = {
        1: -4.0, 2: -3.0, 3: -1.0, 4: 3.0, 5: 7.0, 6: 10.0,
        7: 11.0, 8: 8.0, 9: 4.0, 10: 1.0, 11: -2.0, 12: -4.0,
    }
    return month_weights.get(month, 0.0)


def _diurnal_component(utc_dt: datetime, lon: float) -> float:
    # Local solar time approximation from longitude without a timezone database.
    local_hour = (utc_dt.hour + lon / 15.0) % 24.0
    afternoon_peak = math.exp(-((local_hour - 15.0) ** 2) / (2 * 3.2**2))
    return -1.0 + afternoon_peak * 5.0


def _base_components(
    *,
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    road_density: float,
    settlement_density: float,
    now_utc: datetime,
    lon: float,
) -> dict:
    """Compute every additive component of the legacy ``P_base`` model."""
    base_score = 14.0
    road_distance_score = _distance_decay_score(road_distance_m, max_score=28.0, scale_m=2100.0)
    settlement_distance_score = _distance_decay_score(
        settlement_distance_m, max_score=24.0, scale_m=6200.0
    )
    road_density_score = 16.0 * road_density
    settlement_density_score = 14.0 * settlement_density
    season_score = _seasonal_component(now_utc.month)
    diurnal_score = _diurnal_component(now_utc, lon)
    data_penalty = -8.0 if (road_distance_m is None and settlement_distance_m is None) else 0.0

    total_score = (
        base_score
        + road_distance_score
        + settlement_distance_score
        + road_density_score
        + settlement_density_score
        + season_score
        + diurnal_score
        + data_penalty
    )
    return {
        "base_score": base_score,
        "road_distance_m": road_distance_m,
        "road_distance_score": road_distance_score,
        "settlement_distance_m": settlement_distance_m,
        "settlement_distance_score": settlement_distance_score,
        "road_density": road_density,
        "road_density_score": road_density_score,
        "settlement_density": settlement_density,
        "settlement_density_score": settlement_density_score,
        "season_month": now_utc.month,
        "season_score": season_score,
        "diurnal_score": diurnal_score,
        "data_penalty": data_penalty,
        "total_score": total_score,
        "p_base": _clamp01(total_score / 100.0),
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
    """Return the pre-existing rule-based ignition probability, in ``[0, 1]``.

    This is the legacy ``P_base`` formula (human access pressure from roads and
    settlements + seasonal/daytime factors), unchanged except for normalisation
    from a 0..100 score to a 0..1 probability.
    """
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
    """Combine the base probability with the road influence.

    ``P_fire = 1 - (1 - P_base) * (1 - alpha * I(R))``.

    All inputs are clamped to ``[0, 1]``, so the result is guaranteed to satisfy
    ``0 <= P_fire <= 1`` and ``P_fire >= P_base`` for ``alpha >= 0``.
    """
    return calculate_fire_probability_breakdown(p_base, influence, alpha)["p_fire"]


def calculate_fire_probability_breakdown(p_base: float, influence: float, alpha: float) -> dict:
    """Return each term of ``P_fire = 1 - (1 - P_base) * (1 - alpha * I(R))``."""
    p_base = _clamp01(p_base)
    influence = _clamp01(influence)
    alpha = _clamp01(alpha)

    one_minus_p_base = 1.0 - p_base
    alpha_times_influence = alpha * influence
    one_minus_alpha_influence = 1.0 - alpha_times_influence
    product = one_minus_p_base * one_minus_alpha_influence
    p_fire = 1.0 - product

    return {
        "p_base": p_base,
        "influence": influence,
        "alpha": alpha,
        "one_minus_p_base": one_minus_p_base,
        "alpha_times_influence": alpha_times_influence,
        "one_minus_alpha_influence": one_minus_alpha_influence,
        "product": product,
        "p_fire": p_fire,
    }


def risk_level_from_probability(probability: float) -> str:
    """Map a 0..100 percentage to a risk level (legacy thresholds)."""
    if probability >= 75:
        return "high"
    if probability >= 45:
        return "medium"
    return "low"
