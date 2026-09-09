from app.fire_risk import calculate_fire_probability


def test_example_r_zero():
    # P_base=0.2, alpha=0.5, I(R)=1 (R=0) -> 0.6
    assert abs(calculate_fire_probability(0.2, 1.0, 0.5) - 0.6) < 1e-12


def test_example_r_equals_r0():
    # I(R)=0.5 -> 1 - 0.8 * 0.75 = 0.4
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
