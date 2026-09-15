import app.osm as osm
from app.osm import invalidate_osm_cache, nearest_distances_from_osm


def test_nearest_distances_from_osm_caches(monkeypatch):
    calls = {"n": 0}

    def fake_compute(lat, lon, radius_m=12000):
        calls["n"] += 1
        return {"road_distance_m": 10.0, "settlement_distance_m": None,
                "road_density": 0.5, "settlement_density": 0.0}

    monkeypatch.setattr(osm, "_compute_nearest_distances_from_osm", fake_compute)
    invalidate_osm_cache()

    first = nearest_distances_from_osm(51.80, 108.05, 5000)
    second = nearest_distances_from_osm(51.80, 108.05, 5000)
    assert calls["n"] == 1, "second call should be served from cache"
    assert first == second
    invalidate_osm_cache()
