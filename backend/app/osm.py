"""OSM road/settlement context lookup (Overpass). No data -> None/0.

The lookup is optional context, not a hard dependency: a failed or slow
Overpass request must never delay ``/risk/point``. The client therefore uses a
short timeout, a small in-memory cache and a circuit breaker that disables
Overpass for a cooldown period after the first failure.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


# Overpass is optional context. Disable it with OSM_ENABLED=0 for fully
# offline/fast operation; the model then falls back to the SHP road layer only.
_OSM_ENABLED = _env_bool("OSM_ENABLED", True)
_OSM_TIMEOUT_SECONDS = float(os.environ.get("OSM_TIMEOUT_SECONDS", "1.5"))
_OSM_FAILURE_COOLDOWN_SECONDS = float(
    os.environ.get("OSM_FAILURE_COOLDOWN_SECONDS", "300")
)

# In-memory TTL cache for Overpass results so repeated /risk/point calls for the
# same location/radius within the window skip the (slow, rate-limited) HTTP call.
_OSM_CACHE_TTL_SECONDS = float(os.environ.get("OSM_CACHE_TTL_SECONDS", "600"))
_OSM_CACHE_MAX_ENTRIES = 256
_osm_cache_lock = threading.Lock()
_osm_query_cache: dict[tuple, tuple[float, dict[str, float | None]]] = {}

# Circuit breaker: once Overpass fails, skip further calls for a while. This is
# what keeps the first slow request from being repeated for every map click.
_osm_disabled_until = 0.0


def _osm_cache_lookup(key: tuple) -> dict[str, float | None] | None:
    with _osm_cache_lock:
        entry = _osm_query_cache.get(key)
        if entry and (time.monotonic() - entry[0]) < _OSM_CACHE_TTL_SECONDS:
            return entry[1]
        _osm_query_cache.pop(key, None)
    return None


def _osm_cache_store(key: tuple, value: dict[str, float | None]) -> None:
    with _osm_cache_lock:
        if len(_osm_query_cache) >= _OSM_CACHE_MAX_ENTRIES:
            oldest_key = min(_osm_query_cache, key=lambda k: _osm_query_cache[k][0])
            _osm_query_cache.pop(oldest_key, None)
        _osm_query_cache[key] = (time.monotonic(), value)


def invalidate_osm_cache() -> None:
    """Drop all cached OSM results and reset the circuit breaker."""
    global _osm_disabled_until
    with _osm_cache_lock:
        _osm_query_cache.clear()
    _osm_disabled_until = 0.0


def _osm_circuit_open() -> bool:
    return not _OSM_ENABLED or time.monotonic() < _osm_disabled_until


def _open_osm_circuit() -> None:
    global _osm_disabled_until
    _osm_disabled_until = time.monotonic() + max(0.0, _OSM_FAILURE_COOLDOWN_SECONDS)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def _no_osm_data() -> dict[str, float | None]:
    """Return an empty context (no fake proximity values)."""
    return {
        "road_distance_m": None,
        "settlement_distance_m": None,
        "road_density": 0.0,
        "settlement_density": 0.0,
    }


def _compute_nearest_distances_from_osm(lat: float, lon: float, radius_m: int = 12000) -> dict[str, float | None]:
    if _osm_circuit_open():
        return _no_osm_data()

    place_filter = "city|town|village|hamlet|isolated_dwelling"
    query = f"""
[out:json][timeout:6];
(
  way["highway"](around:{radius_m},{lat},{lon});
  node["place"~"{place_filter}"](around:{radius_m},{lat},{lon});
  way["place"~"{place_filter}"](around:{radius_m},{lat},{lon});
  relation["place"~"{place_filter}"](around:{radius_m},{lat},{lon});
);
out center;
"""
    payload = f"data={quote(query)}".encode("utf-8")
    payload_json: dict[str, object] | None = None
    # Use a single endpoint with a short timeout. Trying several public mirrors
    # sequentially multiplied the worst-case latency by three (12 s+).
    endpoint = os.environ.get(
        "OSM_ENDPOINT", "https://overpass-api.de/api/interpreter"
    )
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "User-Agent": "SpaceVision/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=_OSM_TIMEOUT_SECONDS) as response:
            payload_json = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        payload_json = None

    if payload_json is None:
        # Fail fast: don't retry Overpass for every subsequent map click.
        _open_osm_circuit()
        return _no_osm_data()

    road_distances: list[float] = []
    settlement_distances: list[float] = []
    road_proximity_sum = 0.0
    settlement_proximity_sum = 0.0

    road_class_weight = {
        "motorway": 1.0,
        "trunk": 0.95,
        "primary": 0.85,
        "secondary": 0.72,
        "tertiary": 0.58,
        "residential": 0.45,
        "unclassified": 0.42,
        "service": 0.30,
        "track": 0.22,
        "path": 0.15,
    }
    settlement_weight = {
        "city": 1.0,
        "town": 0.78,
        "village": 0.54,
        "hamlet": 0.36,
        "isolated_dwelling": 0.22,
    }

    for element in payload_json.get("elements", []):
        element_type = element.get("type")
        tags = element.get("tags", {})
        elem_lat = element.get("lat")
        elem_lon = element.get("lon")

        if element_type in ("way", "relation"):
            center = element.get("center", {})
            elem_lat = center.get("lat", elem_lat)
            elem_lon = center.get("lon", elem_lon)

        if elem_lat is None or elem_lon is None:
            continue

        distance = haversine_meters(lat, lon, float(elem_lat), float(elem_lon))
        if "highway" in tags:
            road_distances.append(distance)
            highway_type = str(tags.get("highway", ""))
            road_weight = road_class_weight.get(highway_type, 0.35)
            road_proximity_sum += math.exp(-distance / 2200.0) * road_weight
        if tags.get("place") in {"city", "town", "village", "hamlet", "isolated_dwelling"}:
            settlement_distances.append(distance)
            place_type = str(tags.get("place", ""))
            place_weight = settlement_weight.get(place_type, 0.4)
            settlement_proximity_sum += math.exp(-distance / 6500.0) * place_weight

    road_distance = min(road_distances) if road_distances else None
    settlement_distance = min(settlement_distances) if settlement_distances else None
    road_density = max(0.0, min(1.0, road_proximity_sum / 2.8))
    settlement_density = max(0.0, min(1.0, settlement_proximity_sum / 1.8))
    if road_distance is None and settlement_distance is None:
        return _no_osm_data()
    return {
        "road_distance_m": road_distance,
        "settlement_distance_m": settlement_distance,
        "road_density": road_density,
        "settlement_density": settlement_density,
    }


def nearest_distances_from_osm(lat: float, lon: float, radius_m: int = 12000) -> dict[str, float | None]:
    """OSM context lookup with a ~60s in-memory cache per (location, radius)."""
    # ~11 m grid: map clicks at nearly the same spot hit the cache instead of
    # triggering a new Overpass request for every metre of movement.
    key = (round(float(lat), 4), round(float(lon), 4), int(radius_m))
    cached = _osm_cache_lookup(key)
    if cached is not None:
        return cached
    result = _compute_nearest_distances_from_osm(lat, lon, radius_m)
    _osm_cache_store(key, result)
    return result
