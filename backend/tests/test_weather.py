"""Pure tests for the Nesterov fire-danger calculation."""
from __future__ import annotations

from datetime import date

from app.weather import _seasonal_prior, fire_weather, nesterov_index


def _day(tmax: float, dewpoint: float, precip: float = 0.0) -> dict:
    return {"tmax": tmax, "dewpoint": dewpoint, "precip": precip}


def test_nesterov_accumulates_on_dry_days():
    result = nesterov_index(
        [_day(30.0, 10.0), _day(30.0, 10.0), _day(30.0, 10.0)]
    )
    assert result["index"] == 1800.0
    assert result["dry_days"] == 3
    assert 0.0 < result["normalized"] < 1.0


def test_nesterov_resets_after_significant_rain():
    result = nesterov_index(
        [_day(30.0, 10.0), _day(30.0, 10.0), _day(20.0, 10.0, precip=4.0)]
    )
    assert result["index"] == 0.0
    assert result["normalized"] == 0.0
    assert result["dry_days"] == 0


def test_nesterov_ignores_missing_values():
    result = nesterov_index([_day(30.0, 10.0), {"tmax": None, "precip": None}])
    assert result["days"] == 1
    assert result["index"] == 600.0


def test_weather_falls_back_to_climatology(monkeypatch):
    import app.weather as weather

    weather.invalidate_weather_cache()
    monkeypatch.setattr(weather, "_fetch_weather", lambda *args, **kwargs: [])

    result = fire_weather(51.85, 108.27, today=date(2026, 7, 15))

    assert result["source"] == "climatology"
    assert result["normalized"] == _seasonal_prior(7)
    assert result["error"]


def test_live_weather_uses_nasa_power(monkeypatch):
    import app.weather as weather

    weather.invalidate_weather_cache()
    monkeypatch.setattr(
        weather,
        "_fetch_weather",
        lambda *args, **kwargs: [_day(30.0, 10.0)] * 10,
    )

    result = fire_weather(51.85, 108.27, today=date(2026, 7, 15))

    assert result["source"] == "nasa-power"
    assert result["index"] == 6000.0
    assert result["normalized"] == 1.0
