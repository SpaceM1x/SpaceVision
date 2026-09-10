from datetime import datetime

from app.fire_risk import base_probability, calculate_fire_probability

# A winter morning: low seasonal factor and low diurnal factor, so the spatial
# factors dominate and "no data" clearly maps to a low (deep-forest) risk.
WINTER_MORNING = datetime(2026, 1, 15, 2, 0, 0)


def _base(**kwargs):
    defaults = dict(
        road_distance_m=None,
        settlement_distance_m=None,
        road_density=0.0,
        settlement_density=0.0,
        now_utc=WINTER_MORNING,
        lon=108.0,
    )
    defaults.update(kwargs)
    return base_probability(**defaults)


def test_example_r_zero():
    # P_base=0.2, alpha=0.5, I(R)=1 -> 0.2 + 0.5*1*0.8 = 0.6
    assert abs(calculate_fire_probability(0.2, 1.0, 0.5) - 0.6) < 1e-12


def test_example_r_equals_r0():
    # I(R)=0.5 -> 0.2 + 0.5*0.5*0.8 = 0.4
    assert abs(calculate_fire_probability(0.2, 0.5, 0.5) - 0.4) < 1e-12


def test_far_road_returns_base():
    # I(R) -> 0 => P_fire -> P_base
    assert abs(calculate_fire_probability(0.2, 0.0, 0.5) - 0.2) < 1e-12


def test_probability_in_bounds():
    for p in (0.0, 0.1, 0.5, 1.0):
        for i in (0.0, 0.5, 1.0):
            for a in (0.0, 0.5, 1.0):
                assert 0.0 <= calculate_fire_probability(p, i, a) <= 1.0


def test_fire_not_less_than_base():
    for p in (0.0, 0.1, 0.3, 0.7):
        for i in (0.0, 0.5, 1.0):
            for a in (0.0, 0.5, 1.0):
                assert calculate_fire_probability(p, i, a) >= p - 1e-12


def test_base_probability_no_data_is_low():
    # Absence of OSM data must NOT become an artificial medium risk.
    p = _base()
    assert 0.05 <= p <= 0.12


def test_base_probability_near_road_above_no_data():
    assert _base(road_distance_m=100.0) > _base()


def test_base_probability_near_settlement_above_no_data():
    assert _base(settlement_distance_m=100.0) > _base()


def test_base_probability_road_and_settlement_highest():
    both = _base(road_distance_m=100.0, settlement_distance_m=100.0)
    road = _base(road_distance_m=100.0)
    settlement = _base(settlement_distance_m=100.0)
    assert both > road
    assert both > settlement


def test_base_probability_dangerous_season_higher():
    spatial = dict(
        road_distance_m=50.0,
        settlement_distance_m=50.0,
        road_density=0.5,
        settlement_density=0.5,
        lon=108.0,
    )
    winter = base_probability(now_utc=datetime(2026, 1, 15, 2, 0, 0), **spatial)
    summer = base_probability(now_utc=datetime(2026, 7, 15, 8, 0, 0), **spatial)
    assert summer > winter


def test_base_probability_clamped_to_0_9():
    p = base_probability(
        road_distance_m=0.0,
        settlement_distance_m=0.0,
        road_density=1.0,
        settlement_density=1.0,
        now_utc=datetime(2026, 7, 15, 8, 0, 0),
        lon=108.0,
    )
    assert p <= 0.90


def test_base_probability_clear_spatial_separation():
    deep_forest = _base()
    road_settlement = _base(
        road_distance_m=0.0,
        settlement_distance_m=0.0,
        road_density=0.5,
        settlement_density=0.5,
    )
    assert road_settlement - deep_forest > 0.15
