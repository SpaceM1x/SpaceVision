from datetime import datetime

import math
import pytest
from pyproj import Transformer
from shapely.geometry import Point

from app.distance import distance_to_nearest_road
from app.fire_risk import base_probability, final_probability
from app.gis import select_metric_crs, to_metric
from app.road_data import RoadDataProvider
from app.road_influence import road_influence


def test_integration_single_road(single_road_shp):
    r0 = 500.0

    # 1) load SHP
    gdf = RoadDataProvider(single_road_shp).load()

    # 2) transform CRS
    crs = select_metric_crs(gdf)
    roads_metric = to_metric(gdf, crs)

    # 3) distance to the nearest road (a point exactly on the road)
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = transformer.transform(108.05, 51.80)
    point = Point(x, y)
    r = distance_to_nearest_road(point, roads_metric)

    # 4) road influence
    influence = road_influence(r, r0)

    # 5) fire probability (the road factor is inside the logistic model)
    p_base = base_probability(
        road_distance_m=120.0,
        settlement_distance_m=450.0,
        road_density=0.52,
        settlement_density=0.58,
        now_utc=datetime(2026, 6, 15, 12, 0, 0),
        lon=108.0,
        road_distance_shp_m=r,
        road_r0_m=r0,
    )
    p_fire = final_probability(p_base)

    assert r < 5.0
    assert 0.99 < influence <= 1.0
    assert 0.0 <= p_fire <= 1.0
    assert abs(p_fire - p_base) < 1e-12


def test_end_to_end_risk_point(roads_shp, monkeypatch, tmp_path, request):
    import os
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.main as main_mod
    from app.database import Base
    from app.models import User

    # Never touch the real gis/roads/roads.shp: the upload endpoint writes to
    # the module-level path, so redirect it into the test tmp dir.
    target = tmp_path / "gis" / "roads" / "roads.shp"
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main_mod, "ROADS_SHP_PATH", target)
    main_mod.invalidate_roads_cache()
    request.addfinalizer(main_mod.invalidate_roads_cache)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    db = testing_session()
    user = User(username="e2e", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()

    monkeypatch.setitem(main_mod.app.dependency_overrides, main_mod.get_db, override_get_db)
    monkeypatch.setitem(
        main_mod.app.dependency_overrides, main_mod.get_current_user, lambda authorization="", db=None: user
    )
    # Keep the test offline/deterministic.
    monkeypatch.setattr(
        main_mod, "nearest_distances_from_osm",
        lambda lat, lon, radius_m=12000: {
            "road_distance_m": 120.0, "settlement_distance_m": 450.0,
            "road_density": 0.52, "settlement_density": 0.58,
        },
    )

    client = TestClient(main_mod.app)
    base = str(roads_shp)
    if base.endswith(".shp"):
        base = base[: -len(".shp")]
    files = []
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        path = base + ext
        with open(path, "rb") as fh:
            data = fh.read()
        files.append(("files", (os.path.basename(path), data, "application/octet-stream")))

    up = client.post("/roads/upload", files=files)
    assert up.status_code == 200, up.text

    r = client.get("/risk/point", params={"lat": 51.80, "lon": 108.05})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["road_distance_m"] < 5.0
    assert 0.99 < body["road_influence"] <= 1.0
    assert body["road_source"] == "shp"
    assert abs(body["fire_probability"] - body["base_probability"]) < 1e-12
    assert body["method"] == "formula"
    assert body["explanation"]["method"] == "formula"
    assert body["explanation"]["parameters"]["lambda0"]["value"] == 0.0012
    assert body["explanation"]["distance_sources"] == {
        "road": "shp",
        "settlement": "osm",
    }

    # Distances measured in the Leaflet map module take priority over the
    # backend SHP/OSM fallback.
    map_formula = client.get(
        "/risk/point",
        params={
            "lat": 51.80,
            "lon": 108.05,
            "method": "formula",
            "road_distance_m": 200,
            "settlement_distance_m": 500,
        },
    )
    assert map_formula.status_code == 200, map_formula.text
    map_body = map_formula.json()
    assert map_body["method"] == "formula"
    assert map_body["road_distance_m"] == 200.0
    assert map_body["settlement_distance_m"] == 500.0
    assert map_body["road_source"] == "map"
    assert map_body["explanation"]["distance_sources"] == {
        "road": "map",
        "settlement": "map",
    }
    assert map_body["fire_probability"] == pytest.approx(
        -math.expm1(
            -0.0012 * math.exp(-0.0025 * 200) * math.exp(-0.0012 * 500)
        )
    )

    # ML method: model trained on the ISDM registry, distances from server layers.
    ml = client.get("/risk/point", params={"lat": 51.80, "lon": 108.05, "method": "ml"})
    assert ml.status_code == 200, ml.text
    ml_body = ml.json()
    assert ml_body["method"] == "ml"
    assert ml_body["explanation"]["method"] == "ml"
    assert ml_body["road_source"] == "ml"
    assert 0.0 <= ml_body["fire_probability"] < 1.0

    # AI method: use a fake ready model and a fake tile, but exercise the real
    # endpoint, calibration, explanation and history persistence.
    monkeypatch.setattr(
        main_mod,
        "model_status",
        lambda: {
            "enabled": True,
            "model_id": "fake/model",
            "state": "ready",
            "error": None,
            "labels": [],
        },
    )
    monkeypatch.setattr(
        main_mod,
        "fetch_satellite_tile",
        lambda lat, lon: {
            "data": b"fake-tile",
            "z": 15,
            "x": 1,
            "y": 2,
            "url": "https://example.test/tile.jpg",
            "cached": True,
        },
    )
    monkeypatch.setattr(
        main_mod,
        "classify_image_bytes",
        lambda data: {
            "available": True,
            "model_id": "fake/model",
            "predicted": "moderate",
            "predicted_ru": "Средний",
            "confidence": 0.72,
            "risk_score": 0.5,
            "risk_level": "medium",
            "risk_level_ru": "Средний",
            "probabilities": [
                {"label": "moderate", "label_ru": "Средний", "probability": 0.72}
            ],
            "reason": None,
        },
    )

    ai_response = client.get(
        "/risk/point", params={"lat": 51.80, "lon": 108.05, "method": "ai"}
    )
    assert ai_response.status_code == 200, ai_response.text
    ai_body = ai_response.json()
    assert ai_body["method"] == "ai"
    assert ai_body["risk_level"] == "high"
    assert 0.10 < ai_body["fire_probability"] < 0.11
    assert ai_body["explanation"]["ai"]["predicted"] == "moderate"
    assert ai_body["explanation"]["ai"]["tile"]["url"].endswith("tile.jpg")
    assert ai_body["summary"].startswith("10.4%")

    # Without a SHP layer the formula falls back to OSM roads, and the AI
    # method still works because it does not depend on the road network.
    cleared = client.delete("/roads")
    assert cleared.status_code == 200, cleared.text

    fallback = client.get("/risk/point", params={"lat": 51.80, "lon": 108.05})
    assert fallback.status_code == 200, fallback.text
    fallback_body = fallback.json()
    assert fallback_body["road_source"] == "osm"
    assert abs(fallback_body["road_distance_m"] - 120.0) < 1e-6
    assert fallback_body["explanation"]["distance_sources"] == {
        "road": "osm",
        "settlement": "osm",
    }

    ai_without_shp = client.get(
        "/risk/point", params={"lat": 51.80, "lon": 108.05, "method": "ai"}
    )
    assert ai_without_shp.status_code == 200, ai_without_shp.text
    assert ai_without_shp.json()["road_distance_m"] is None

