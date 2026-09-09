"""Road influence factor.

A smoothed, normalised form of a 1/R relationship that avoids the singularity
at R = 0::

    I(R) = 1 / (1 + R / R0)

Properties:
    I(0)   = 1
    I(R0)  = 0.5
    I(2R0) ~ 0.333
    I(4R0) = 0.2
    I(R)   -> 0  as  R -> +inf
"""
from __future__ import annotations


def road_influence(distance_m: float, r0_m: float) -> float:
    """Return the normalised road influence in ``[0, 1]``.

    *distance_m* and *r0_m* must both be in metres (the same dimension), so the
    ratio ``R / R0`` is dimensionless.
    """
    if r0_m <= 0:
        raise ValueError("R0 must be a positive number of metres.")
    if distance_m < 0:
        raise ValueError("Distance must be non-negative.")
    return 1.0 / (1.0 + distance_m / r0_m)
