"""Annual probability of at least one fire at a point.

The model is the exponential distance-decay intensity model from the project
methodology:

    lambda = lambda0 * exp(-beta * R_road) * exp(-gamma * R_settlement)
    P      = 1 - exp(-lambda * A)

where
    lambda0      -- base fire intensity, fires per hectare per year;
    beta         -- road-distance decay, 1 / metre;
    gamma        -- settlement-distance decay, 1 / metre;
    R_road       -- distance to the nearest road, metres;
    R_settlement -- distance to the nearest settlement, metres;
    A            -- calculation area, hectares (1 ha by default).

The distances are supplied by the Leaflet map module: the client measures them
against the road and settlement layers displayed on the map and sends the two
values together with the point coordinates.

The result is the probability of *at least one* fire on the selected area
during one year.  It is not a forecast for a particular day and it does not
estimate burned area or fire severity.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Average Russian parameters from the methodology table. The formula deliberately
# uses national averages; the ISDM-fitted model is a separate, data-driven method.
LAMBDA0 = 0.0012
BETA = 0.01
GAMMA = 0.0001

LEVEL_NAMES: tuple[tuple[str, str], ...] = (
    ("very_low", "очень низкий"),
    ("low", "низкий"),
    ("moderate", "средний"),
    ("high", "относительно высокий"),
)


def _thresholds(cuts_percent: tuple[float, ...]) -> tuple[tuple[float, str, str], ...]:
    """Cut points (percent): below each cut -> that level, the rest -> the top level."""
    return tuple(
        (cut, code, label) for cut, (code, label) in zip(cuts_percent, LEVEL_NAMES)
    )


def thresholds_text(thresholds: tuple[tuple[float, str, str], ...]) -> dict[str, str]:
    cuts = [cut for cut, _, _ in thresholds]
    text = {thresholds[0][1]: f"< {cuts[0]:.4g}"}
    for index in range(1, len(thresholds)):
        text[thresholds[index][1]] = f"{cuts[index - 1]:.4g}–{cuts[index]:.4g}"
    text[LEVEL_NAMES[-1][0]] = f"≥ {cuts[-1]:.4g}"
    return text


# Formula: classes are 20/40/60% of the highest value the formula can give
# (a point right next to a road and a settlement, LAMBDA0 per hectare).
# Everything from 60% up is the top level.
_FORMULA_MAX_PERCENT = (1.0 - math.exp(-LAMBDA0)) * 100.0
FORMULA_RISK_THRESHOLDS = _thresholds(
    tuple(share * _FORMULA_MAX_PERCENT for share in (0.2, 0.4, 0.6))
)

# Kept for the legend text in the explanation.
RISK_THRESHOLDS = FORMULA_RISK_THRESHOLDS
TOP_RISK_LEVEL = LEVEL_NAMES[-1]

LARGE_FIRE_NOTE = (
    "Считаются шансы крупных пожаров (более 200 га по реестру ИСДМ), "
    "а не любых возгораний, таких как костры или сжигание мусора."
)


class FireProbabilityError(ValueError):
    """Raised for invalid model inputs."""


@dataclass(frozen=True)
class FireProbabilityResult:
    """Formula result for one point and area."""

    road_distance_m: float
    settlement_distance_m: float
    area_ha: float
    lambda_per_ha_year: float
    probability: float
    percent: float
    road_decay: float
    settlement_decay: float
    risk_level: str
    risk_level_ru: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "road_distance_m": self.road_distance_m,
            "settlement_distance_m": self.settlement_distance_m,
            "area_ha": self.area_ha,
            "lambda_per_ha_year": self.lambda_per_ha_year,
            "probability": self.probability,
            "percent": self.percent,
            "road_decay": self.road_decay,
            "settlement_decay": self.settlement_decay,
            "risk_level": self.risk_level,
            "risk_level_ru": self.risk_level_ru,
        }

    def summary(self) -> str:
        return (
            f"Годовая вероятность крупного пожара (более 200 га) "
            f"{format_percent(self.percent)}% ({self.risk_level_ru}) на {self.area_ha:g} га."
        )

    def explanation(self) -> dict[str, Any]:
        """Detailed, JSON-serialisable explanation of the calculation."""
        return {
            "method": "formula",
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
                    "label": "λ₀",
                    "value": LAMBDA0,
                    "unit": "пожаров / (га · год)",
                    "description": (
                        "Базовая интенсивность у самой инфраструктуры. "
                        "Среднее по России с учётом концентрации 60–80 % "
                        "антропогенных пожаров вблизи дорог и населённых пунктов."
                    ),
                },
                "beta": {
                    "label": "β",
                    "value": BETA,
                    "unit": "1 / м",
                    "description": (
                        "Коэффициент затухания по дорогам. Риск падает "
                        "в e раз примерно на 100 м."
                    ),
                },
                "gamma": {
                    "label": "γ",
                    "value": GAMMA,
                    "unit": "1 / м",
                    "description": (
                        "Коэффициент затухания по населённым пунктам. Риск "
                        "падает в e раз примерно на 10 км."
                    ),
                },
                "area_ha": {
                    "label": "A",
                    "value": self.area_ha,
                    "unit": "га",
                    "description": (
                        "Площадь расчёта. Вероятность хотя бы одного пожара "
                        "растёт с площадью: P = 1 − exp(−λ·A)."
                    ),
                },
            },
            "factors": [
                {
                    "key": "road",
                    "label": "Затухание по дороге",
                    "formula": "exp(−β · R_road)",
                    "input": self.road_distance_m,
                    "value": self.road_decay,
                },
                {
                    "key": "settlement",
                    "label": "Затухание по населённому пункту",
                    "formula": "exp(−γ · R_settlement)",
                    "input": self.settlement_distance_m,
                    "value": self.settlement_decay,
                },
                {
                    "key": "lambda",
                    "label": "Интенсивность",
                    "formula": "λ = λ₀ · затухание",
                    "value": self.lambda_per_ha_year,
                    "unit": "пожаров / (га · год)",
                },
                {
                    "key": "probability",
                    "label": "Вероятность за год",
                    "formula": "P = 1 − exp(−λ · A)",
                    "value": self.probability,
                },
            ],
            "result": {
                "lambda_per_ha_year": self.lambda_per_ha_year,
                "probability": self.probability,
                "percent": self.percent,
            },
            "risk_level": {
                "code": self.risk_level,
                "label_ru": self.risk_level_ru,
                "thresholds_percent": thresholds_text(FORMULA_RISK_THRESHOLDS),
                "note": (
                    "Классы — доли от максимума формулы (точка у дороги и посёлка). "
                    "Это относительные классы, а не официальные классы пожарной опасности."
                ),
            },
            "logic": [
                "λ — ожидаемое число пожаров на 1 га за год.",
                "Множитель exp(−β·R_road) уменьшает интенсивность с удалением от дорог.",
                "Множитель exp(−γ·R_settlement) уменьшает интенсивность с удалением от населённых пунктов.",
                "P = 1 − exp(−λ·A) — вероятность хотя бы одного события при пуассоновском потоке пожаров.",
            ],
            "assumptions": [
                LARGE_FIRE_NOTE,
                "Параметры λ₀, β, γ — усреднённые значения по России из методики.",
                "Расстояния до дорог и населённых пунктов измеряются по слоям карты Leaflet.",
                "Расстояния измеряются в метрах, площадь — в гектарах.",
                "Поток пожаров приближённо считается пуассоновским и стационарным в течение года.",
                "Модель не учитывает тип леса, запас горючего, засуху, рельеф и погоду конкретного дня.",
                "Результат — вероятность хотя бы одного крупного пожара, а не прогноз площади или тяжести.",
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


def risk_level_from_percent(
    percent: float,
    thresholds: tuple[tuple[float, str, str], ...] = FORMULA_RISK_THRESHOLDS,
) -> tuple[str, str]:
    """Return ``(code, russian_label)`` for an annual probability in percent."""
    value = float(percent)
    for threshold, code, label in thresholds:
        if value < threshold:
            return code, label
    return TOP_RISK_LEVEL


def _validate_distance(name: str, value: float | None) -> float:
    if value is None:
        raise FireProbabilityError(
            f"{name} is required: provide the distance from the map."
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


def calculate_fire_probability(
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    area_ha: float = 1.0,
) -> FireProbabilityResult:
    """Calculate the annual fire probability with the single formula model.

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
        Contains the intensity (``lambda_per_ha_year``), the probability as a
        fraction (``probability``) and a percentage (``percent``), plus the
        risk level and both exponential distance factors.
    """
    road_distance = _validate_distance("road_distance_m", road_distance_m)
    settlement_distance = _validate_distance(
        "settlement_distance_m", settlement_distance_m
    )
    area = _validate_area(area_ha)

    road_decay = math.exp(-BETA * road_distance)
    settlement_decay = math.exp(-GAMMA * settlement_distance)
    intensity = LAMBDA0 * road_decay * settlement_decay
    # expm1 is more accurate than 1 - exp(x) for small intensities.
    probability = -math.expm1(-intensity * area)
    probability = min(1.0, max(0.0, probability))
    percent = probability * 100.0
    level_code, level_ru = risk_level_from_percent(percent)

    return FireProbabilityResult(
        road_distance_m=road_distance,
        settlement_distance_m=settlement_distance,
        area_ha=area,
        lambda_per_ha_year=intensity,
        probability=probability,
        percent=percent,
        road_decay=road_decay,
        settlement_decay=settlement_decay,
        risk_level=level_code,
        risk_level_ru=level_ru,
    )


def _print_examples() -> None:
    """Print a small demonstration table (``python -m app.fire_probability``)."""
    examples = (
        (0.0, 0.0, 1.0, "точка на дороге и в населённом пункте"),
        (200.0, 500.0, 1.0, "рядом с дорогой и посёлком"),
        (500.0, 1_000.0, 1.0, "типичная удалённость"),
        (1_500.0, 3_000.0, 1.0, "удалённый участок"),
        (10_000.0, 20_000.0, 1.0, "сильно удалённый участок"),
    )
    header = (
        f"{'R_road, м':>10} {'R_settle, м':>12} {'A, га':>7} "
        f"{'λ, пож./(га·год)':>18} {'вероятность, %':>16}  уровень"
    )
    print(header)
    print("-" * len(header))
    for road, settlement, area, _note in examples:
        result = calculate_fire_probability(road, settlement, area)
        print(
            f"{road:10.0f} {settlement:12.0f} {area:7.1f} "
            f"{result.lambda_per_ha_year:18.8f} "
            f"{format_percent(result.percent):>16}  "
            f"{result.risk_level_ru}"
        )


if __name__ == "__main__":
    _print_examples()
