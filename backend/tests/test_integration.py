from datetime import datetime

from pyproj import Transformer
from shapely.geometry import Point

from app.distance import distance_to_nearest_road
from app.fire_risk import base_probability, calculate_fire_probability
from app.gis import select_metric_crs, to_metric
from app.road_data import RoadDataProvider
from app.road_influence import road_influence


def test_integration_single_road(single_road_shp):
    r0 = 500.0
    alpha = 0.15

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

    # 5) fire probability
    p_base = base_probability(
        road_distance_m=120.0,
        settlement_distance_m=450.0,
        road_density=0.52,
        settlement_density=0.58,
        now_utc=datetime(2026, 6, 15, 12, 0, 0),
        lon=108.0,
    )
    p_fire = calculate_fire_probability(p_base, influence, alpha)

    assert r < 5.0
    assert 0.99 < influence <= 1.0
    assert 0.0 <= p_fire <= 1.0
    assert p_fire >= p_base


def test_end_to_end_risk_point(roads_shp, monkeypatch):
    import os
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.main as main_mod
    from app.database import Base
    from app.models import User

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

