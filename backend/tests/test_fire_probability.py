import math

import pytest

from app.fire_probability import (
    BETA,
    GAMMA,
    LAMBDA0,
    FireProbabilityError,
    calculate_fire_probability,
    format_percent,
    risk_level_from_percent,
)


def test_zero_distance_matches_table():
    result = calculate_fire_probability(0.0, 0.0, 1.0)

    assert result.lambda_per_ha_year == pytest.approx(LAMBDA0)
    assert result.probability == pytest.approx(-math.expm1(-LAMBDA0))
    assert result.percent == pytest.approx(0.11993, abs=1e-4)
    assert result.road_decay == pytest.approx(1.0)
    assert result.settlement_decay == pytest.approx(1.0)


def test_intensity_uses_table_parameters():
    result = calculate_fire_probability(200.0, 500.0, 1.0)

    expected_intensity = LAMBDA0 * math.exp(-BETA * 200.0) * math.exp(-GAMMA * 500.0)
    assert result.lambda_per_ha_year == pytest.approx(expected_intensity)
    assert result.road_decay == pytest.approx(math.exp(-BETA * 200.0))
    assert result.settlement_decay == pytest.approx(math.exp(-GAMMA * 500.0))
    assert result.probability == pytest.approx(-math.expm1(-expected_intensity))


def test_probability_decreases_with_distance():
    near = calculate_fire_probability(0.0, 0.0, 1.0)
    far = calculate_fire_probability(5_000.0, 20_000.0, 1.0)

    assert far.probability < near.probability
    assert far.risk_level == "very_low"


def test_area_increases_probability_by_poisson_rule():
    result = calculate_fire_probability(100.0, 500.0, 10.0)

    expected = -math.expm1(-result.lambda_per_ha_year * result.area_ha)
    assert result.probability == pytest.approx(expected)
    assert result.percent > 0.1
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


def test_explanation_contains_single_parameter_set_and_assumptions():
    result = calculate_fire_probability(100.0, 500.0, 1.0)
    explanation = result.explanation()

    assert explanation["method"] == "formula"
    assert "λ" in explanation["equation"]
    assert explanation["inputs"]["road_distance_m"] == 100.0
    assert explanation["parameters"]["lambda0"]["value"] == LAMBDA0
    assert explanation["parameters"]["beta"]["value"] == BETA
    assert explanation["parameters"]["gamma"]["value"] == GAMMA
    assert explanation["result"]["percent"] == pytest.approx(result.percent)
    assert explanation["risk_level"]["code"] == result.risk_level
    assert explanation["assumptions"]
    assert "1 га" in result.summary()
