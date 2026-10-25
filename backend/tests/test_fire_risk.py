from datetime import datetime

from app.fire_risk import base_probability, final_probability

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


def test_base_probability_bounded():
    for road in (None, 0.0, 250.0, 5_000.0):
        for settlement in (None, 0.0, 500.0, 20_000.0):
            p = _base(road_distance_m=road, settlement_distance_m=settlement)
            assert 0.0 <= p <= 1.0


def test_final_probability_is_base():
    # The road contribution lives inside the logit: no extra additive term.
    for p in (0.0, 0.05, 0.2, 0.5, 0.95):
        assert abs(final_probability(p) - p) < 1e-12


def test_shp_distance_overrides_osm():
    # The uploaded SHP layer is authoritative even when OSM has a closer road.
    osm_only = _base(road_distance_m=10.0)
    shp_far = _base(road_distance_m=10.0, road_distance_shp_m=5_000.0)
    assert shp_far < osm_only


def test_road_proximity_monotonic_in_distance():
    near = _base(road_distance_shp_m=100.0)
    far = _base(road_distance_shp_m=2_000.0)
    assert near > far


def test_far_shp_road_matches_no_road():
    # I(R) -> 0 at 100 km, so the result converges to the "no data" case.
    assert abs(_base(road_distance_shp_m=100_000.0) - _base()) < 1e-3


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
