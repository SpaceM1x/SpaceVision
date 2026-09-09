import pytest

from app.road_influence import road_influence


def test_influence_at_zero():
    assert road_influence(0.0, 500.0) == 1.0


def test_influence_at_r0():
    assert road_influence(500.0, 500.0) == 0.5


def test_influence_at_2r0():
    assert abs(road_influence(1000.0, 500.0) - (1 / 3)) < 1e-9


def test_influence_at_4r0():
    assert abs(road_influence(2000.0, 500.0) - 0.2) < 1e-9


def test_influence_far_tends_to_zero():
    assert road_influence(1_000_000.0, 500.0) < 1e-3


def test_influence_monotonically_decreasing():
    values = [road_influence(r, 500.0) for r in (0, 100, 500, 1000, 2000, 10000)]
    for previous, current in zip(values, values[1:]):
        assert current < previous


def test_invalid_r0():
    with pytest.raises(ValueError):
        road_influence(10.0, 0.0)


def test_negative_distance():
    with pytest.raises(ValueError):
        road_influence(-1.0, 500.0)
