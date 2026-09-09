"""Zaigraevsky district fire-risk API — no-ML version.

Roads are loaded from an ESRI Shapefile (no neural network), the distance to the
nearest road is computed in metres in a metric CRS, and the road influence
``I(R) = 1 / (1 + R / R0)`` is combined with the legacy ``P_base`` model:

    P_fire = 1 - (1 - P_base) * (1 - alpha * I(R))
"""
import json
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pyproj import Transformer
from shapely.geometry import Point
from sqlalchemy.orm import Session

from .auth import create_access_token, decode_token, hash_password, verify_password
from .config import ALPHA, METRIC_CRS, R0_METERS, ROADS_SHP_PATH
from .database import Base, SessionLocal, engine, get_db
from .distance import distance_to_nearest_road
from .fire_risk import (
    base_probability,
    calculate_fire_probability,
    risk_level_from_probability,
)
from .gis import select_metric_crs, to_metric
from .models import User
from .osm import nearest_distances_from_osm
from .road_data import RoadDataError, RoadDataProvider
from .road_influence import road_influence
from .schemas import LoginRequest, LoginResponse, PointRiskOut

app = FastAPI(title="Zaigraevsky Fire Risk API (no-ML)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=(
        r"^http://("
        r"localhost|127\.0\.0\.1|\[::1\]|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"26\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"):5173$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_default_users()


def ensure_default_users() -> None:
    with SessionLocal() as db:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            db.add(
                User(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role="admin",
                )
            )
        user = db.query(User).filter(User.username == "operator").first()
        if not user:
            db.add(
                User(
                    username="operator",
                    password_hash=hash_password("operator123"),
                    role="viewer",
                )
            )
        db.commit()


def get_current_user(
    authorization: str = Header(default=""), db: Session = Depends(get_db)
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Требуется Bearer токен.")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="Недействительный токен.") from error
    username = payload.get("sub", "")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден.")
    return user


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")
    token = create_access_token(user.username, user.role)
    return LoginResponse(access_token=token, role=user.role, username=user.username)


@app.get("/roads/geojson")
def roads_geojson(current_user: User = Depends(get_current_user)) -> dict:
    """Return the SHP roads as a WGS84 GeoJSON FeatureCollection."""
    del current_user
    try:
        gdf = RoadDataProvider(ROADS_SHP_PATH).load()
    except RoadDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return json.loads(gdf.to_crs("EPSG:4326").to_json())


ALLOWED_ROAD_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


@app.get("/roads/status")
def roads_status(current_user: User = Depends(get_current_user)) -> dict:
    """Return whether the SHP roads have been uploaded and which files exist."""
    del current_user
    files = []
    for ext in sorted(ALLOWED_ROAD_EXTENSIONS):
        candidate = ROADS_SHP_PATH.with_suffix(ext)
        if candidate.exists():
            files.append(candidate.name)
    return {
        "uploaded": ROADS_SHP_PATH.exists(),
        "files": files,
        "roads_shp": str(ROADS_SHP_PATH),
    }


@app.post("/roads/upload")
async def upload_roads(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Upload the roads shapefile (.shp/.shx/.dbf/.prj/.cpg)."""
    del current_user
    if not files:
        raise HTTPException(status_code=400, detail="Файлы не загружены.")

    target_dir = ROADS_SHP_PATH.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for upload in files:
        ext = Path(upload.filename).suffix.lower()
        if ext not in ALLOWED_ROAD_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Недопустимый файл: {upload.filename}. Ожидаются .shp/.shx/.dbf/.prj/.cpg.",
            )
        dest = target_dir / f"roads{ext}"
        dest.write_bytes(await upload.read())
        saved.append(dest.name)

    if not (target_dir / "roads.shp").exists():
        raise HTTPException(status_code=400, detail="Отсутствует файл .shp.")
    if not (target_dir / "roads.prj").exists():
        raise HTTPException(
            status_code=400,
            detail="Отсутствует файл .prj — он обязателен (содержит CRS).",
        )

    return {"uploaded": saved, "roads_shp": str(ROADS_SHP_PATH)}


def _build_risk_reason(
    p_fire: float,
    p_base: float,
    influence: float,
    road_distance_m: float | None,
    r0_m: float,
    alpha: float,
) -> str:
    percent = p_fire * 100.0
    level = risk_level_from_probability(percent)
    road_txt = (
        f"ближайшая дорога в {road_distance_m:.0f} м"
        if road_distance_m is not None
        else "нет данных о дорогах (SHP)"
    )
    return (
        f"Вероятность пожара {percent:.1f}% ({level}). "
        f"Базовая вероятность {p_base * 100:.1f}%, влияние дороги {influence:.2f} "
        f"(R0={r0_m:.0f} м, alpha={alpha:.2f}), {road_txt}."
    )


@app.get("/risk/point", response_model=PointRiskOut)
def point_risk(
    lat: float,
    lon: float,
    current_user: User = Depends(get_current_user),
) -> PointRiskOut:
    del current_user

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Некорректные координаты.")

    try:
        gdf = RoadDataProvider(ROADS_SHP_PATH).load()
    except RoadDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    metric_crs = select_metric_crs(gdf, METRIC_CRS)
    roads_metric = to_metric(gdf, metric_crs)

    transformer = Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    point_metric = Point(x, y)

    r = distance_to_nearest_road(point_metric, roads_metric)
    influence = road_influence(r, R0_METERS)

    # Legacy P_base model (OSM settlement/road context + seasonal/daytime factors).
    osm_context = nearest_distances_from_osm(lat, lon)
    p_base = base_probability(
        road_distance_m=osm_context["road_distance_m"],
        settlement_distance_m=osm_context["settlement_distance_m"],
        road_density=float(osm_context["road_density"] or 0.0),
        settlement_density=float(osm_context["settlement_density"] or 0.0),
        now_utc=datetime.utcnow(),
        lon=lon,
    )

    p_fire = calculate_fire_probability(p_base, influence, ALPHA)

    return PointRiskOut(
        lat=lat,
        lon=lon,
        road_distance_m=r,
        settlement_distance_m=osm_context["settlement_distance_m"],
        road_influence=influence,
        base_probability=p_base,
        fire_probability=p_fire,
        risk_level=risk_level_from_probability(p_fire * 100.0),
        risk_reason=_build_risk_reason(p_fire, p_base, influence, r, R0_METERS, ALPHA),
    )

