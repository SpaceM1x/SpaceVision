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
from urllib.parse import quote, urlencode
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

# Overpass is often blocked or too slow.  These lightweight public OSM services
# are used as a last-resort fallback so the formula keeps working without an
# uploaded SHP layer:
#   * OSRM nearest -- distance to the nearest routable road;
#   * Nominatim reverse -- the nearest/containing settlement and its coordinates.
_OSM_PUBLIC_FALLBACK = _env_bool("OSM_PUBLIC_FALLBACK", True)
_OSRM_ENDPOINT = os.environ.get(
    "OSRM_ENDPOINT", "https://router.project-osrm.org/nearest/v1/driving"
).rstrip("/")
_NOMINATIM_ENDPOINT = os.environ.get(
    "NOMINATIM_ENDPOINT", "https://nominatim.openstreetmap.org/reverse"
)
_OSM_FALLBACK_TIMEOUT_SECONDS = float(
    os.environ.get("OSM_FALLBACK_TIMEOUT_SECONDS", "10")
)

_osm_cache_lock = threading.Lock()
_osm_query_cache: dict[tuple, tuple[float, dict[str, float | None]]] = {}
_settlement_query_cache: dict[tuple, tuple[float, dict]] = {}
_road_query_cache: dict[tuple, tuple[float, dict]] = {}

_SETTLEMENT_PLACES = "city|town|village|hamlet|isolated_dwelling"
_SETTLEMENT_QUERY_LIMIT = 600

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
        _settlement_query_cache.clear()
        _road_query_cache.clear()
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


def _get_json(url: str) -> dict | None:
    """Fetch a small JSON document with the shared fallback timeout."""
    request = Request(
        url,
        headers={
            "User-Agent": "SpaceVision/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=_OSM_FALLBACK_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None


def _road_distance_from_osrm(lat: float, lon: float) -> float | None:
    """Distance to the nearest routable OSM road, in metres."""
    if not _OSM_PUBLIC_FALLBACK:
        return None
    url = f"{_OSRM_ENDPOINT}/{lon:.6f},{lat:.6f}?number=1"
    payload = _get_json(url)
    if not payload or payload.get("code") != "Ok":
        return None
    waypoints = payload.get("waypoints") or []
    if not waypoints:
        return None
    try:
        return max(0.0, float(waypoints[0]["distance"]))
    except (KeyError, TypeError, ValueError):
        return None


def _settlement_distance_from_nominatim(lat: float, lon: float) -> float | None:
    """Distance to the nearest settlement reported by OSM Nominatim."""
    if not _OSM_PUBLIC_FALLBACK:
        return None
    params = urlencode(
        {
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "format": "jsonv2",
            # 13 returns a town/village; 10 is a municipality fallback.
            "zoom": "13",
            "addressdetails": "0",
        }
    )
    payload = _get_json(f"{_NOMINATIM_ENDPOINT}?{params}")
    if not payload or "lat" not in payload or "lon" not in payload:
        return None
    try:
        return haversine_meters(
            lat,
            lon,
            float(payload["lat"]),
            float(payload["lon"]),
        )
    except (TypeError, ValueError):
        return None


def _public_service_distances(
    lat: float,
    lon: float,
    *,
    need_road: bool,
    need_settlement: bool,
) -> dict[str, float | None]:
    """Last-resort distances through public OSM services (no Overpass)."""
    return {
        "road_distance_m": (
            _road_distance_from_osrm(lat, lon) if need_road else None
        ),
        "settlement_distance_m": (
            _settlement_distance_from_nominatim(lat, lon)
            if need_settlement
            else None
        ),
        "road_density": 0.0,
        "settlement_density": 0.0,
    }


def _merge_with_public_services(
    lat: float,
    lon: float,
    context: dict[str, float | None],
) -> dict[str, float | None]:
    """Fill missing distances from OSRM/Nominatim, keeping Overpass values."""
    need_road = context.get("road_distance_m") is None
    need_settlement = context.get("settlement_distance_m") is None
    if not need_road and not need_settlement:
        return context
    fallback = _public_service_distances(
        lat,
        lon,
        need_road=need_road,
        need_settlement=need_settlement,
    )
    if need_road:
        context["road_distance_m"] = fallback["road_distance_m"]
    if need_settlement:
        context["settlement_distance_m"] = fallback["settlement_distance_m"]
    return context


def _compute_nearest_distances_from_osm(lat: float, lon: float, radius_m: int = 12000) -> dict[str, float | None]:
    if _osm_circuit_open():
        return _public_service_distances(
            lat, lon, need_road=True, need_settlement=True
        )

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
        return _public_service_distances(
            lat, lon, need_road=True, need_settlement=True
        )

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
    context = {
        "road_distance_m": road_distance,
        "settlement_distance_m": settlement_distance,
        "road_density": road_density,
        "settlement_density": settlement_density,
    }
    return _merge_with_public_services(lat, lon, context)


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


def _empty_settlement_collection(source: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [],
        "source": source,
    }


def _settlement_cache_lookup(key: tuple) -> dict | None:
    with _osm_cache_lock:
        entry = _settlement_query_cache.get(key)
        if entry and (time.monotonic() - entry[0]) < _OSM_CACHE_TTL_SECONDS:
            return entry[1]
        _settlement_query_cache.pop(key, None)
    return None


def _settlement_cache_store(key: tuple, value: dict) -> None:
    with _osm_cache_lock:
        if len(_settlement_query_cache) >= _OSM_CACHE_MAX_ENTRIES:
            oldest_key = min(
                _settlement_query_cache,
                key=lambda k: _settlement_query_cache[k][0],
            )
            _settlement_query_cache.pop(oldest_key, None)
        _settlement_query_cache[key] = (time.monotonic(), value)


def _compute_settlements_geojson_from_osm(
    lat: float,
    lon: float,
    radius_m: int,
) -> dict:
    """Fetch OSM settlement points around a map point as a GeoJSON collection."""
    if _osm_circuit_open():
        return _empty_settlement_collection("none")

    query = f"""
[out:json][timeout:8];
(
  node["place"~"{_SETTLEMENT_PLACES}"](around:{radius_m},{lat},{lon});
  way["place"~"{_SETTLEMENT_PLACES}"](around:{radius_m},{lat},{lon});
  relation["place"~"{_SETTLEMENT_PLACES}"](around:{radius_m},{lat},{lon});
);
out center {_SETTLEMENT_QUERY_LIMIT};
"""
    payload = f"data={quote(query)}".encode("utf-8")
    payload_json: dict[str, object] | None = None
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
        _open_osm_circuit()
        return _empty_settlement_collection("none")

    features: list[dict] = []
    seen: set[tuple] = set()
    for element in payload_json.get("elements", []):
        tags = element.get("tags", {})
        place = str(tags.get("place", ""))
        name = str(tags.get("name", "") or place)
        elem_lat = element.get("lat")
        elem_lon = element.get("lon")
        if element.get("type") in ("way", "relation"):
            center = element.get("center", {})
            elem_lat = center.get("lat", elem_lat)
            elem_lon = center.get("lon", elem_lon)
        if elem_lat is None or elem_lon is None:
            continue
        key = (name, round(float(elem_lat), 4), round(float(elem_lon), 4))
        if key in seen:
            continue
        seen.add(key)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(elem_lon), float(elem_lat)],
                },
                "properties": {
                    "name": name,
                    "place": place,
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "source": "osm",
    }


def settlements_geojson_from_osm(
    lat: float,
    lon: float,
    radius_m: int = 40000,
) -> dict:
    """Cached OSM settlement layer for the Leaflet map module."""
    key = (round(float(lat), 3), round(float(lon), 3), int(radius_m))
    cached = _settlement_cache_lookup(key)
    if cached is not None:
        return cached
    result = _compute_settlements_geojson_from_osm(lat, lon, radius_m)
    _settlement_cache_store(key, result)
    return result


_ROAD_HIGHWAY_TYPES = (
    "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
    "service|track|living_street"
)
_ROAD_QUERY_LIMIT = 3000


def _compute_roads_geojson_from_osm(lat: float, lon: float, radius_m: int) -> dict:
    """Fetch OSM road centrelines around a map point as a GeoJSON collection."""
    if _osm_circuit_open():
        return _empty_settlement_collection("none")

    query = f"""
[out:json][timeout:8];
way["highway"~"{_ROAD_HIGHWAY_TYPES}"](around:{radius_m},{lat},{lon});
out geom {_ROAD_QUERY_LIMIT};
"""
    payload = f"data={quote(query)}".encode("utf-8")
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
    payload_json: dict | None = None
    try:
        with urlopen(request, timeout=_OSM_TIMEOUT_SECONDS) as response:
            payload_json = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        payload_json = None

    if payload_json is None:
        _open_osm_circuit()
        return _empty_settlement_collection("none")

    features: list[dict] = []
    for element in payload_json.get("elements", []):
        geometry = element.get("geometry") or []
        coordinates = [
            [float(point["lon"]), float(point["lat"])]
            for point in geometry
            if "lat" in point and "lon" in point
        ]
        if len(coordinates) < 2:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {
                    "highway": str((element.get("tags") or {}).get("highway", "")),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
        "source": "osm",
    }


def roads_geojson_from_osm(
    lat: float,
    lon: float,
    radius_m: int = 5000,
) -> dict:
    """Cached OSM road layer around a point, used when no SHP roads are loaded."""
    key = (round(float(lat), 3), round(float(lon), 3), int(radius_m))
    with _osm_cache_lock:
        entry = _road_query_cache.get(key)
        if entry and (time.monotonic() - entry[0]) < _OSM_CACHE_TTL_SECONDS:
            return entry[1]
        _road_query_cache.pop(key, None)
    result = _compute_roads_geojson_from_osm(lat, lon, radius_m)
    with _osm_cache_lock:
        if len(_road_query_cache) >= _OSM_CACHE_MAX_ENTRIES:
            oldest_key = min(_road_query_cache, key=lambda k: _road_query_cache[k][0])
            _road_query_cache.pop(oldest_key, None)
        _road_query_cache[key] = (time.monotonic(), result)
    return result

