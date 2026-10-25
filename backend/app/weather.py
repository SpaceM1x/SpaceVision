"""Fire-weather context from NASA POWER (Nesterov fire-danger index).

The point-risk model used to be driven only by static geography and a coarse
seasonal weight, so almost every point produced the same ~10% result.  This
module adds a real, date-dependent driver: the Nesterov fire-danger index,
computed from daily maximum temperature, dew point and precipitation.

NASA POWER is a free, key-less API.  Like the optional OSM lookup it must never
make ``/risk/point`` slow or unreliable, therefore the client uses:

* a short timeout;
* an in-memory TTL cache (the index changes once a day, not per map click);
* a circuit breaker after a failed request;
* a climatological fallback when the API has no data for the requested date
  (for example when the machine clock is ahead of the available archive).

The returned ``normalized`` value is in ``[0, 1]`` and is consumed by the
logistic model in :mod:`app.fire_risk`.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_POWER_ENDPOINT = "https://power.larc.nasa.gov/api/temporal/daily/point"
_TIMEOUT_SECONDS = float(os.environ.get("FIRE_WEATHER_TIMEOUT_SECONDS", "2.0"))
_CACHE_TTL_SECONDS = float(os.environ.get("FIRE_WEATHER_CACHE_TTL_SECONDS", "21600"))
_FAILURE_COOLDOWN_SECONDS = float(
    os.environ.get("FIRE_WEATHER_FAILURE_COOLDOWN_SECONDS", "600")
)
_CACHE_MAX_ENTRIES = 256
_LOOKBACK_DAYS = 30
# Nesterov index values below _INDEX_BASE are treated as "no danger"; above
# _INDEX_BASE + _INDEX_RANGE the factor saturates at 1.0.  These thresholds are
# typical for the continental forests of Eastern Siberia.
_INDEX_BASE = 300.0
_INDEX_RANGE = 4700.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


ENABLED = _env_bool("FIRE_WEATHER_ENABLED", True)

_cache_lock = threading.Lock()
_cache: dict[tuple, tuple[float, dict]] = {}
_disabled_until = 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _seasonal_prior(month: int) -> float:
    """Climatological Nesterov proxy used when live data is unavailable."""
    return {
        1: 0.0,
        2: 0.0,
        3: 0.05,
        4: 0.20,
        5: 0.40,
        6: 0.60,
        7: 0.75,
        8: 0.65,
        9: 0.35,
        10: 0.10,
        11: 0.0,
        12: 0.0,
    }.get(month, 0.0)


def nesterov_index(days: list[dict[str, float]]) -> dict[str, float | int]:
    """Compute the Nesterov index from ascending daily observations.

    Each item may contain ``tmax``, ``dewpoint`` and ``precip``.  A day with at
    least 3 mm of precipitation resets the accumulated index, as in the
    standard Russian fire-danger calculation.
    """
    index = 0.0
    dry_days = 0
    used_days = 0
    for day in days:
        try:
            tmax = float(day.get("tmax", 0.0))
            dewpoint = float(day.get("dewpoint", tmax))
            precip = float(day.get("precip", 0.0))
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (tmax, dewpoint, precip)):
            continue
        used_days += 1
        if precip >= 3.0:
            index = 0.0
            dry_days = 0
            continue
        deficit = max(0.0, tmax - dewpoint)
        index += max(0.0, tmax) * deficit
        dry_days += 1
    normalized = _clamp((index - _INDEX_BASE) / _INDEX_RANGE, 0.0, 1.0)
    return {
        "index": round(index, 1),
        "normalized": round(normalized, 4),
        "dry_days": dry_days,
        "days": used_days,
    }


def _unavailable(reason: str, month: int) -> dict:
    return {
        "index": 0.0,
        "normalized": _seasonal_prior(month),
        "dry_days": 0,
        "days": 0,
        "source": "climatology",
        "period": None,
        "error": reason,
    }


def _cache_lookup(key: tuple) -> dict | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.monotonic() - entry[0]) < _CACHE_TTL_SECONDS:
            return entry[1]
        _cache.pop(key, None)
    return None


def _cache_store(key: tuple, value: dict) -> None:
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            oldest = min(_cache, key=lambda item: _cache[item][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic(), value)


def invalidate_weather_cache() -> None:
    """Drop cached weather and reset the circuit breaker (used by tests)."""
    global _disabled_until
    with _cache_lock:
        _cache.clear()
    _disabled_until = 0.0


def _circuit_open() -> bool:
    return not ENABLED or time.monotonic() < _disabled_until


def _open_circuit() -> None:
    global _disabled_until
    _disabled_until = time.monotonic() + max(0.0, _FAILURE_COOLDOWN_SECONDS)


def _parse_power_payload(payload: dict, start: date, end: date) -> list[dict[str, float]]:
    parameters = payload.get("properties", {}).get("parameter", {})
    tmax_series = parameters.get("T2M_MAX", {})
    dew_series = parameters.get("T2MDEW", {})
    precip_series = parameters.get("PRECTOTCORR", {})

    days: list[dict[str, float]] = []
    cursor = start
    while cursor <= end:
        key = cursor.strftime("%Y%m%d")
        tmax = tmax_series.get(key)
        dew = dew_series.get(key)
        precip = precip_series.get(key)
        if tmax is not None and float(tmax) > -900:
            days.append(
                {
                    "tmax": float(tmax),
                    "dewpoint": float(dew) if dew is not None and float(dew) > -900 else float(tmax),
                    "precip": float(precip) if precip is not None and float(precip) > -900 else 0.0,
                }
            )
        cursor += timedelta(days=1)
    return days


def _fetch_weather(lat: float, lon: float, start: date, end: date) -> list[dict[str, float]]:
    query = urlencode(
        {
            "parameters": "T2M_MAX,T2MDEW,PRECTOTCORR",
            "community": "AG",
            "longitude": f"{lon:.4f}",
            "latitude": f"{lat:.4f}",
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
        }
    )
    request = Request(
        f"{_POWER_ENDPOINT}?{query}",
        headers={
            "User-Agent": "SpaceVision/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _parse_power_payload(payload, start, end)


def fire_weather(
    lat: float,
    lon: float,
    today: date | datetime | None = None,
) -> dict:
    """Return the current Nesterov fire-danger context for a point.

    The result always contains ``normalized`` and ``source`` so callers never
    have to special-case a failed lookup.  ``source`` is ``nasa-power`` when
    live data was used and ``climatology`` otherwise.
    """
    if isinstance(today, datetime):
        today = today.date()
    current = today or date.today()
    end = current - timedelta(days=1)
    start = end - timedelta(days=_LOOKBACK_DAYS)
    key = (round(float(lat), 2), round(float(lon), 2), end.isoformat())

    cached = _cache_lookup(key)
    if cached is not None:
        return cached

    if _circuit_open():
        result = _unavailable("NASA POWER временно недоступен.", current.month)
        _cache_store(key, result)
        return result

    try:
        days = _fetch_weather(lat, lon, start, end)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        _open_circuit()
        result = _unavailable(f"NASA POWER: {error}", current.month)
        _cache_store(key, result)
        return result

    if not days:
        result = _unavailable(
            "NASA POWER не вернул данные за выбранный период.", current.month
        )
        _cache_store(key, result)
        return result

    computed = nesterov_index(days)
    result = {
        **computed,
        "source": "nasa-power",
        "period": f"{start.isoformat()} — {end.isoformat()}",
        "error": None,
    }
    _cache_store(key, result)
    return result
