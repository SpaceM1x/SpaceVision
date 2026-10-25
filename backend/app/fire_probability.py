"""Annual probability of at least one fire at a point.

The model is an exponential distance-decay intensity model:

    lambda = lambda0 * exp(-beta * R_road) * exp(-gamma * R_settlement)
    P      = 1 - exp(-lambda * A)

where
    lambda0   -- base fire intensity, fires per hectare per year;
    beta      -- road-distance decay, 1 / metre;
    gamma     -- settlement-distance decay, 1 / metre;
    R_road    -- distance to the nearest road, metres;
    R_settlement -- distance to the nearest settlement, metres;
    A         -- calculation area, hectares (1 ha by default).

The three parameter sets below are not a statistical confidence interval.
They are provisional lower / average / upper scenarios for average Russian
conditions, not coefficients calibrated on historical fires.  The lower
scenario is deliberately conservative (low risk), the upper one describes a
more fire-prone landscape.  Local conditions (forest type, fuel load, drought,
land-use, ignition regime) can shift the result and should eventually be
calibrated on regional fire statistics.

The result is the probability of *at least one* fire on the selected area
during one year.  It is not a forecast for a particular day and it does not
estimate burned area or fire severity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Scenario:
    """One parameter set of the distance-decay model."""

    key: str
    label: str
    lambda0: float
    beta: float
    gamma: float


# Provisional parameter sets for average Russian conditions (not calibrated).
LOWER_SCENARIO = Scenario(
    key="lower",
    label="Нижняя граница (консервативная)",
    lambda0=0.0006,
    beta=0.0035,
    gamma=0.0018,
)
BASE_SCENARIO = Scenario(
    key="base",
    label="Средний (базовый) вариант",
    lambda0=0.0012,
    beta=0.0025,
    gamma=0.0012,
)
UPPER_SCENARIO = Scenario(
    key="upper",
    label="Верхняя граница (повышенный риск)",
    lambda0=0.0025,
    beta=0.0018,
    gamma=0.0009,
)

SCENARIOS = (LOWER_SCENARIO, BASE_SCENARIO, UPPER_SCENARIO)

# Annual probability thresholds for the *base* scenario, in percent.
# These are relative classes for a one-hectare point estimate, not official
# fire-danger classes.  They are deliberately low because the model returns
# annual probability, not a daily forecast.
RISK_THRESHOLDS: tuple[tuple[float, str, str], ...] = (
    (0.01, "very_low", "очень низкий"),
    (0.05, "low", "низкий"),
    (0.15, "moderate", "умеренный"),
)
ELEVATED_LEVEL = ("elevated", "повышенный")


class FireProbabilityError(ValueError):
    """Raised for invalid model inputs."""


@dataclass(frozen=True)
class ScenarioProbability:
    """Result for one scenario."""

    key: str
    label: str
    lambda0: float
    beta: float
    gamma: float
    lambda_per_ha_year: float
    probability: float
    percent: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "lambda0": self.lambda0,
            "beta": self.beta,
            "gamma": self.gamma,
            "lambda_per_ha_year": self.lambda_per_ha_year,
            "probability": self.probability,
            "percent": self.percent,
        }


@dataclass(frozen=True)
class FireProbabilityResult:
    """Complete lower / base / upper result for one point and area."""

    road_distance_m: float
    settlement_distance_m: float
    area_ha: float
    lower: ScenarioProbability
    base: ScenarioProbability
    upper: ScenarioProbability
    risk_level: str
    risk_level_ru: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "area_ha": self.area_ha,
            "lower": self.lower.as_dict(),
            "base": self.base.as_dict(),
            "upper": self.upper.as_dict(),
            "risk_level": self.risk_level,
            "risk_level_ru": self.risk_level_ru,
        }

    def summary(self) -> str:
        return (
            f"Базовая вероятность {format_percent(self.base.percent)}% "
            f"({self.risk_level_ru}); диапазон "
            f"{format_percent(self.lower.percent)}–"
            f"{format_percent(self.upper.percent)}% "
            f"за год на {self.area_ha:g} га."
        )

    def explanation(self) -> dict[str, Any]:
        """Detailed, JSON-serialisable explanation of the calculation."""
        return {
            "method": "range",
            "equation": (
                "λ = λ₀ · exp(−β · R_road) · exp(−γ · R_settlement); "
                "P = 1 − exp(−λ · A)"
            ),
            "inputs": {
                "road_distance_m": self.road_distance_m,
                "settlement_distance_m": self.settlement_distance_m,
                "area_ha": self.area_ha,
            },
            "parameters": {
                "lambda0": {
                    "description": (
                        "Базовая интенсивность пожаров, пожаров на 1 га в год. "
                        "Задаёт масштаб риска при нулевых расстояниях."
                    ),
                    "unit": "пожаров / (га · год)",
                    "lower": LOWER_SCENARIO.lambda0,
                    "base": BASE_SCENARIO.lambda0,
                    "upper": UPPER_SCENARIO.lambda0,
                },
                "beta": {
                    "description": (
                        "Скорость затухания влияния дороги. Чем больше β, "
                        "тем быстрее риск падает при удалении от дороги."
                    ),
                    "unit": "1 / м",
                    "lower": LOWER_SCENARIO.beta,
                    "base": BASE_SCENARIO.beta,
                    "upper": UPPER_SCENARIO.beta,
                },
                "gamma": {
                    "description": (
                        "Скорость затухания влияния населённого пункта. "
                        "Чем больше γ, тем быстрее риск падает при удалении "
                        "от населённого пункта."
                    ),
                    "unit": "1 / м",
                    "lower": LOWER_SCENARIO.gamma,
                    "base": BASE_SCENARIO.gamma,
                    "upper": UPPER_SCENARIO.gamma,
                },
                "area_ha": {
                    "description": (
                        "Площадь расчёта. Вероятность хотя бы одного пожара "
                        "растёт с площадью: P = 1 − exp(−λ·A)."
                    ),
                    "unit": "га",
                    "value": self.area_ha,
                },
            },
            "scenarios": {
                "lower": self.lower.as_dict(),
                "base": self.base.as_dict(),
                "upper": self.upper.as_dict(),
            },
            "risk_level": {
                "code": self.risk_level,
                "label_ru": self.risk_level_ru,
                "basis": "базовый сценарий",
                "thresholds_percent": {
                    "very_low": "< 0.01",
                    "low": "0.01–0.05",
                    "moderate": "0.05–0.15",
                    "elevated": "≥ 0.15",
                },
                "note": (
                    "Это относительные классы годовой вероятности для 1 га, "
                    "а не официальные классы пожарной опасности."
                ),
            },
            "logic": [
                "λ — ожидаемое число пожаров на 1 га за год.",
                "Множитель exp(−β·R_road) уменьшает интенсивность с удалением от дорог.",
                "Множитель exp(−γ·R_settlement) уменьшает интенсивность с удалением от населённых пунктов.",
                "P = 1 − exp(−λ·A) — вероятность хотя бы одного события при пуассоновском потоке пожаров.",
                "Три набора λ₀, β, γ задают нижнюю, среднюю и верхнюю оценки, а не доверительный интервал.",
            ],
            "assumptions": [
                "Расстояния измеряются в метрах, площадь — в гектарах.",
                "Поток пожаров приближённо считается пуассоновским и стационарным в течение года.",
                "Параметры — предварительные сценарии для средних российских условий, а не калибровка по историческим пожарам; для региона нужна локальная калибровка.",
                "Модель не учитывает тип леса, запас горючего, засуху, рельеф и погоду конкретного дня.",
                "Результат — вероятность хотя бы одного пожара, а не прогноз площади или тяжести.",
            ],
        }


def format_percent(percent: float) -> str:
    """Human-readable percentage without turning small risks into ``0.00``."""
    value = float(percent)
    if value == 0:
        return "0"
    if value < 0.0001:
        return "<0.0001"
    if value < 0.01:
        return f"{value:.4f}"
    if value < 1:
        return f"{value:.3f}"
    return f"{value:.2f}"


def risk_level_from_percent(percent: float) -> tuple[str, str]:
    """Return ``(code, russian_label)`` for a base-scenario percentage."""
    value = float(percent)
    for threshold, code, label in RISK_THRESHOLDS:
        if value < threshold:
            return code, label
    return ELEVATED_LEVEL


def _validate_distance(name: str, value: float | None) -> float:
    if value is None:
        raise FireProbabilityError(
            f"{name} is required: provide a vector layer or an explicit distance."
        )
    distance = float(value)
    if not math.isfinite(distance) or distance < 0:
        raise FireProbabilityError(f"{name} must be a finite non-negative number.")
    return distance


def _validate_area(area_ha: float) -> float:
    area = float(area_ha)
    if not math.isfinite(area) or area <= 0:
        raise FireProbabilityError("area_ha must be a finite positive number.")
    return area


def _scenario_probability(
    scenario: Scenario,
    road_distance_m: float,
    settlement_distance_m: float,
    area_ha: float,
) -> ScenarioProbability:
    # One exponent avoids multiplying two very small numbers.
    exponent = -scenario.beta * road_distance_m - scenario.gamma * settlement_distance_m
    intensity = scenario.lambda0 * math.exp(exponent)
    # expm1 is more accurate than 1 - exp(x) for small intensities.
    probability = -math.expm1(-intensity * area_ha)
    probability = min(1.0, max(0.0, probability))
    return ScenarioProbability(
        key=scenario.key,
        label=scenario.label,
        lambda0=scenario.lambda0,
        beta=scenario.beta,
        gamma=scenario.gamma,
        lambda_per_ha_year=intensity,
        probability=probability,
        percent=probability * 100.0,
    )


def calculate_fire_probability(
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    area_ha: float = 1.0,
) -> FireProbabilityResult:
    """Calculate lower, base and upper annual fire probabilities.

    Parameters
    ----------
    road_distance_m:
        Distance to the nearest road in metres.  Must be non-negative.
    settlement_distance_m:
        Distance to the nearest settlement in metres.  Must be non-negative.
    area_ha:
        Calculation area in hectares.  Defaults to 1.0.

    Returns
    -------
    FireProbabilityResult
        Contains ``lower``, ``base`` and ``upper`` scenario results, each with
        a fraction (``probability``) and a percentage (``percent``), plus the
        risk level derived from the base scenario.
    """
    road_distance = _validate_distance("road_distance_m", road_distance_m)
    settlement_distance = _validate_distance(
        "settlement_distance_m", settlement_distance_m
    )
    area = _validate_area(area_ha)

    results = {
        scenario.key: _scenario_probability(
            scenario, road_distance, settlement_distance, area
        )
        for scenario in SCENARIOS
    }
    base = results[BASE_SCENARIO.key]
    level_code, level_ru = risk_level_from_percent(base.percent)
    return FireProbabilityResult(
        road_distance_m=road_distance,
        settlement_distance_m=settlement_distance,
        area_ha=area,
        lower=results[LOWER_SCENARIO.key],
        base=base,
        upper=results[UPPER_SCENARIO.key],
        risk_level=level_code,
        risk_level_ru=level_ru,
    )


def _table_percent(value: float) -> str:
    """Keep the example table readable for very small probabilities."""
    return "<0.0001" if 0 < value < 0.0001 else f"{value:.4f}"


def _print_examples() -> None:
    """Print a small demonstration table (``python -m app.fire_probability``)."""
    examples = (
        (0.0, 0.0, 1.0, "точка на дороге и в населённом пункте"),
        (100.0, 500.0, 1.0, "рядом с дорогой и посёлком"),
        (500.0, 2_000.0, 1.0, "типичная удалённость"),
        (2_000.0, 5_000.0, 1.0, "глухой участок"),
        (10_000.0, 20_000.0, 1.0, "сильно удалённый участок"),
        (100.0, 500.0, 10.0, "рядом с дорогой, площадь 10 га"),
        (100.0, 500.0, 100.0, "рядом с дорогой, площадь 100 га"),
    )
    header = (
        f"{'R_road, м':>10} {'R_settle, м':>12} {'A, га':>7} "
        f"{'нижняя, %':>11} {'средняя, %':>12} {'верхняя, %':>12}  уровень"
    )
    print(header)
    print("-" * len(header))
    for road, settlement, area, _note in examples:
        result = calculate_fire_probability(road, settlement, area)
        print(
            f"{road:10.0f} {settlement:12.0f} {area:7.1f} "
            f"{_table_percent(result.lower.percent):>11} "
            f"{_table_percent(result.base.percent):>12} "
            f"{_table_percent(result.upper.percent):>12}  "
            f"{result.risk_level_ru}"
        )


if __name__ == "__main__":
    _print_examples()
