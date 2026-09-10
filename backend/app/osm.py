"""OSM context lookup used by the ``P_base`` model.

Queries OpenStreetMap (Overpass) for the nearest roads and settlements around a
point. When no data is available it returns ``None`` distances and zero
densities — absence of data must not be turned into fake proximity values.
"""
from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


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
    """Return an honest "no data" context (no fake proximity values)."""
    return {
        "road_distance_m": None,
        "settlement_distance_m": None,
        "road_density": 0.0,
        "settlement_density": 0.0,
    }


def nearest_distances_from_osm(lat: float, lon: float, radius_m: int = 12000) -> dict[str, float | None]:
    query = f"""
[out:json][timeout:5];
(
  way["highway"](around:{radius_m},{lat},{lon});
  node["place"~"city|town|village|hamlet|isolated_dwelling"](around:{radius_m},{lat},{lon});
);
out center;
"""
    payload = f"data={quote(query)}".encode("utf-8")
    payload_json: dict[str, object] | None = None
    endpoints = ["https://overpass.kumi.systems/api/interpreter"]
    for endpoint in endpoints:
        request = Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": "SpaceVision/1.0 (local fire risk prototype)",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=3) as response:
                payload_json = json.loads(response.read().decode("utf-8"))
            break
        except (HTTPError, URLError, TimeoutError, ValueError):
            continue

    if payload_json is None:
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

        if element_type == "way":
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
