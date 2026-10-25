import math

import pytest

from app.fire_probability import (
    BASE_SCENARIO,
    LOWER_SCENARIO,
    UPPER_SCENARIO,
    FireProbabilityError,
    calculate_fire_probability,
    format_percent,
    risk_level_from_percent,
)


def test_known_values_at_zero_distance():
    result = calculate_fire_probability(0.0, 0.0, 1.0)

    assert result.lower.probability == pytest.approx(-math.expm1(-LOWER_SCENARIO.lambda0))
    assert result.base.probability == pytest.approx(-math.expm1(-BASE_SCENARIO.lambda0))
    assert result.upper.probability == pytest.approx(-math.expm1(-UPPER_SCENARIO.lambda0))
    assert result.lower.percent == pytest.approx(0.05998, abs=1e-4)
    assert result.base.percent == pytest.approx(0.11993, abs=1e-4)
    assert result.upper.percent == pytest.approx(0.24969, abs=1e-4)


def test_scenarios_are_ordered_and_monotonic():
    result = calculate_fire_probability(100.0, 500.0, 1.0)

    assert result.lower.probability < result.base.probability < result.upper.probability

    farther = calculate_fire_probability(5_000.0, 20_000.0, 1.0)
    assert farther.base.probability < result.base.probability
    assert farther.lower.probability < result.lower.probability
    assert farther.upper.probability < result.upper.probability


def test_area_increases_probability_by_poisson_rule():
    result = calculate_fire_probability(100.0, 500.0, 10.0)

    expected = -math.expm1(
        -result.base.lambda_per_ha_year * result.area_ha
    )
    assert result.base.probability == pytest.approx(expected)
    assert result.base.percent > 0.1
    assert result.risk_level == "elevated"
    assert result.risk_level_ru == "повышенный"


def test_invalid_inputs_are_rejected():
    with pytest.raises(FireProbabilityError):
        calculate_fire_probability(None, 500.0)
    with pytest.raises(FireProbabilityError):
        calculate_fire_probability(-1.0, 500.0)
    with pytest.raises(FireProbabilityError):
        calculate_fire_probability(100.0, float("nan"))
    with pytest.raises(FireProbabilityError):
        calculate_fire_probability(100.0, 500.0, 0.0)
    with pytest.raises(FireProbabilityError):
        calculate_fire_probability(100.0, 500.0, -1.0)


@pytest.mark.parametrize(
    ("percent", "code", "label"),
    [
        (0.0, "very_low", "очень низкий"),
        (0.009, "very_low", "очень низкий"),
        (0.01, "low", "низкий"),
        (0.049, "low", "низкий"),
        (0.05, "moderate", "умеренный"),
        (0.149, "moderate", "умеренный"),
        (0.15, "elevated", "повышенный"),
        (10.0, "elevated", "повышенный"),
    ],
)
def test_risk_level_thresholds(percent, code, label):
    assert risk_level_from_percent(percent) == (code, label)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "0"),
        (0.00001, "<0.0001"),
        (0.0031, "0.0031"),
        (0.0513, "0.051"),
        (1.234, "1.23"),
        (12.4664, "12.47"),
    ],
)
def test_percent_formatting(value, expected):
    assert format_percent(value) == expected


def test_explanation_contains_parameters_and_assumptions():
    result = calculate_fire_probability(100.0, 500.0, 1.0)
    explanation = result.explanation()

    assert explanation["method"] == "range"
    assert "λ" in explanation["equation"]
    assert explanation["inputs"]["road_distance_m"] == 100.0
    assert explanation["parameters"]["lambda0"]["base"] == BASE_SCENARIO.lambda0
    assert explanation["scenarios"]["base"]["percent"] == pytest.approx(
        result.base.percent
    )
    assert explanation["risk_level"]["code"] == result.risk_level
    assert explanation["assumptions"]
    assert "1 га" in result.summary()
