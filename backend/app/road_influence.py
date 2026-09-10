"""Road influence factor: I(R) = 1 / (1 + R / R0)."""
from __future__ import annotations


def road_influence(distance_m: float, r0_m: float) -> float:
    """Return I(R) in [0, 1] (distance_m and r0_m in metres)."""
    if r0_m <= 0:
        raise ValueError("R0 must be a positive number of metres.")
    if distance_m < 0:
        raise ValueError("Distance must be non-negative.")
    return 1.0 / (1.0 + distance_m / r0_m)
