"""SpaceVision API: AI road recognition + SHP fire risk."""
import logging
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pyproj import Transformer
from shapely.geometry import Point
from sqlalchemy.orm import Session

from .analytics import build_analytics_summary
from .auth import create_access_token, decode_token, hash_password, verify_password
from .config import ALPHA, METRIC_CRS, R0_METERS, ROADS_SHP_PATH
from .database import (
    PREDICTION_DIR,
    SessionLocal,
    UPLOAD_DIR,
    ensure_schema,
    get_db,
)
from .distance import distance_to_nearest_road
from .fire_history import FireRiskRecord, record_fire_risk
from .fire_risk import (
    base_probability_breakdown,
    calculate_fire_probability_breakdown,
    risk_level_from_probability,
)
from .gis import select_metric_crs, to_metric
from .models import Upload, User
from .osm import nearest_distances_from_osm
from .road_data import RoadDataError, RoadDataProvider
from .road_influence import road_influence
from .schemas import (
    AnalyticsSummaryOut,
    FireRiskRecordOut,
    LoginRequest,
    LoginResponse,
    PointRiskOut,
    UploadOut,
)

app = FastAPI(title="SpaceVision API (AI + SHP)")

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


def _prediction_paths(upload: Upload) -> tuple[Path, Path]:
    stem = Path(upload.file_path).stem
    return (
        PREDICTION_DIR / f"{stem}_mask.png",
        PREDICTION_DIR / f"{stem}_overlay.png",
    )


def serialize_upload(upload: Upload) -> UploadOut:
    mask_path, overlay_path = _prediction_paths(upload)
    mask_url = f"/uploads/{upload.id}/mask" if mask_path.exists() else None
    overlay_url = f"/uploads/{upload.id}/overlay" if overlay_path.exists() else None
    return UploadOut(
        id=upload.id,
        title=upload.title,
        tile_z=upload.tile_z,
        tile_x=upload.tile_x,
        tile_y=upload.tile_y,
        uploaded_by=upload.uploaded_by,
        created_at=upload.created_at,
        mask_url=mask_url,
        overlay_url=overlay_url,
    )


class IgnoreMissingTileAccessLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        is_tiles_request = "/tiles/" in message
        is_not_found = " 404 " in message or " 404 Not Found" in message
        return not (is_tiles_request and is_not_found)


def configure_access_logging() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(
        isinstance(log_filter, IgnoreMissingTileAccessLog)
        for log_filter in access_logger.filters
    ):
        access_logger.addFilter(IgnoreMissingTileAccessLog())


@app.on_event("startup")
def on_startup() -> None:
    configure_access_logging()
    ensure_schema()
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


@app.delete("/roads")
def clear_roads(current_user: User = Depends(get_current_user)) -> dict:
    """Delete the uploaded SHP road files."""
    del current_user
    removed = []
    for ext in sorted(ALLOWED_ROAD_EXTENSIONS):
        candidate = ROADS_SHP_PATH.with_suffix(ext)
        if candidate.exists():
            candidate.unlink()
            removed.append(candidate.name)
    return {"removed": removed, "uploaded": False}


def _build_risk_reason(
    p_fire: float,
    p_base: float,
    influence: float,
    road_distance_m: float | None,
    r0_m: float,
    alpha: float,
) -> str:
    percent = p_fire * 100.0
    road_txt = (
        f"ближайшая дорога в {road_distance_m:.0f} м"
        if road_distance_m is not None
        else "нет данных о дорогах (SHP)"
    )
    return (
        f"Вероятность пожара {percent:.1f}% в течение года. "
        f"Базовая вероятность {p_base * 100:.1f}%, влияние SHP-дороги {influence:.2f} "
        f"(R0={r0_m:.0f} м, вес={alpha:.2f}), {road_txt}."
    )


def _build_risk_summary(lat: float, lon: float, p_fire: float) -> str:
    return (
        f"{(p_fire * 100.0):.1f}% в течение года "
        f"(широта {lat:.4f}, долгота {lon:.4f})"
    )


def _build_risk_explanation(
    *,
    lat: float,
    lon: float,
    road_distance_m: float | None,
    settlement_distance_m: float | None,
    influence: float,
    base: dict,
    fire: dict,
    p_fire: float,
) -> dict:
    """Build a structured, per-factor explanation of one calculation."""
    return {
        "equation": "P_fire = P_base + α · I(R) · (1 − P_base)",
        "coordinates": {"lat": lat, "lon": lon},
        "base": {
            "label": "Базовая вероятность P_base",
            "formula": (
                "0.05 + 0.18·road + 0.20·settlement + 0.12·ρ_дорог "
                "+ 0.08·ρ_поселений + 0.15·сезон + 0.10·суточ + 0.15·road·settlement"
            ),
            "result": base["p_base"],
            "factors": [
                {"name": "Константа (минимум)", "value": base["constant"], "note": "база"},
                {
                    "name": "Близость к дороге (OSM)",
                    "value": base["road_contribution"],
                    "input": base["road_distance_m"],
                    "note": "0.18·exp(−d/1000 м)",
                },
                {
                    "name": "Близость к поселению",
                    "value": base["settlement_contribution"],
                    "input": base["settlement_distance_m"],
                    "note": "0.20·exp(−d/3000 м)",
                },
                {
                    "name": "Плотность дорог",
                    "value": base["road_density_contribution"],
                    "input": base["road_density"],
                    "note": "0.12·ρ_дорог",
                },
                {
                    "name": "Плотность поселений",
                    "value": base["settlement_density_contribution"],
                    "input": base["settlement_density"],
                    "note": "0.08·ρ_поселений",
                },
                {
                    "name": "Сезонный фактор",
                    "value": base["season_contribution"],
                    "input": base["season"],
                    "note": f"0.15·сезон (месяц {base['season_month']})",
                },
                {
                    "name": "Суточный фактор",
                    "value": base["diurnal_contribution"],
                    "input": base["diurnal"],
                    "note": "0.10·пик (15:00)",
                },
                {
                    "name": "Взаимодействие дорога×поселение",
                    "value": base["interaction_contribution"],
                    "input": base["interaction"],
                    "note": "0.15·road·settlement",
                },
            ],
        },
        "road": {
            "label": "Влияние SHP-дороги I(R)",
            "formula": "I(R) = 1 / (1 + R / R0)",
            "R": road_distance_m,
            "R0": R0_METERS,
            "alpha": ALPHA,
            "result": influence,
        },
        "final": {
            "label": "Итоговая вероятность P_fire",
            "formula": "P_fire = P_base + α · I(R) · (1 − P_base)",
            "result": p_fire,
            "terms": [
                {"name": "P_base", "value": fire["p_base"]},
                {"name": "I(R)", "value": fire["influence"]},
                {"name": "α (вес SHP)", "value": fire["alpha"]},
                {"name": "1 − P_base", "value": fire["one_minus_p_base"]},
                {"name": "α · I(R) · (1−P_base)", "value": fire["shp_addition"]},
                {"name": "P_fire", "value": fire["p_fire"]},
            ],
        },
    }


@app.get("/risk/point", response_model=PointRiskOut)
def point_risk(
    lat: float,
    lon: float,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointRiskOut:
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

    # P_base model (OSM road/settlement context + seasonal/daytime factors).
    osm_context = nearest_distances_from_osm(lat, lon)
    base = base_probability_breakdown(
        road_distance_m=osm_context["road_distance_m"],
        settlement_distance_m=osm_context["settlement_distance_m"],
        road_density=float(osm_context["road_density"] or 0.0),
        settlement_density=float(osm_context["settlement_density"] or 0.0),
        now_utc=datetime.utcnow(),
        lon=lon,
    )
    p_base = base["p_base"]

    fire = calculate_fire_probability_breakdown(p_base, influence, ALPHA)
    p_fire = fire["p_fire"]
    level = risk_level_from_probability(p_fire * 100.0)

    explanation = _build_risk_explanation(
        lat=lat,
        lon=lon,
        road_distance_m=r,
        settlement_distance_m=osm_context["settlement_distance_m"],
        influence=influence,
        base=base,
        fire=fire,
        p_fire=p_fire,
    )
    summary = _build_risk_summary(lat, lon, p_fire)

    # Persist the calculation into the history module.
    record_fire_risk(
        db,
        username=current_user.username,
        lat=lat,
        lon=lon,
        fire_probability=p_fire,
        risk_level=level,
        summary=summary,
        explanation=explanation,
    )

    return PointRiskOut(
        lat=lat,
        lon=lon,
        road_distance_m=r,
        settlement_distance_m=osm_context["settlement_distance_m"],
        road_influence=influence,
        base_probability=p_base,
        fire_probability=p_fire,
        risk_level=level,
        risk_reason=_build_risk_reason(p_fire, p_base, influence, r, R0_METERS, ALPHA),
        summary=summary,
        explanation=explanation,
    )


@app.get("/risk/history", response_model=list[FireRiskRecordOut])
def risk_history(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    del current_user
    records = db.query(FireRiskRecord).order_by(FireRiskRecord.created_at.desc()).all()
    return [record.to_out() for record in records]


@app.post("/uploads", response_model=UploadOut)
async def create_upload(
    file: UploadFile = File(...),
    title: str = Form(...),
    tile_z: str = Form(default=""),
    tile_x: str = Form(default=""),
    tile_y: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    def parse_tile_value(raw_value: str, field_name: str) -> int:
        value = (raw_value or "").strip()
        if value == "":
            return 0
        try:
            return int(value)
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail=f"Неверное значение {field_name}: {raw_value}"
            ) from error

    parsed_tile_z = parse_tile_value(tile_z, "tile_z")
    parsed_tile_x = parse_tile_value(tile_x, "tile_x")
    parsed_tile_y = parse_tile_value(tile_y, "tile_y")

    extension = Path(file.filename).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Поддерживаются только PNG/JPG.")
    filename = f"{uuid4().hex}{extension}"
    destination = UPLOAD_DIR / filename
    content = await file.read()
    destination.write_bytes(content)
    try:
        # Imported lazily so the app still starts without the heavy AI stack.
        from .road_inference import run_road_segmentation

        run_road_segmentation(destination, PREDICTION_DIR)
    except Exception as error:
        if destination.exists():
            destination.unlink()
        raise HTTPException(status_code=500, detail=f"Ошибка инференса дорог: {error}") from error

    upload = Upload(
        title=title,
        file_path=str(destination),
        tile_z=parsed_tile_z,
        tile_x=parsed_tile_x,
        tile_y=parsed_tile_y,
        uploaded_by=current_user.username,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return serialize_upload(upload)


@app.get("/uploads", response_model=list[UploadOut])
def list_uploads(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    del current_user
    items = db.query(Upload).order_by(Upload.created_at.desc()).all()
    return [serialize_upload(item) for item in items]


@app.get("/analytics/summary", response_model=AnalyticsSummaryOut)
def analytics_summary(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    del current_user
    items = db.query(Upload).order_by(Upload.created_at.desc()).all()
    return build_analytics_summary(items, PREDICTION_DIR)


@app.get("/uploads/{upload_id}/mask")
def get_upload_mask(upload_id: int, db: Session = Depends(get_db)):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    mask_path, _ = _prediction_paths(upload)
    if not mask_path.exists():
        raise HTTPException(status_code=404, detail="Mask not found")
    return FileResponse(mask_path)


@app.get("/uploads/{upload_id}/overlay")
def get_upload_overlay(upload_id: int, db: Session = Depends(get_db)):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    _, overlay_path = _prediction_paths(upload)
    if not overlay_path.exists():
        raise HTTPException(status_code=404, detail="Overlay not found")
    return FileResponse(overlay_path)


@app.get("/tiles/{z}/{x}/{y}")
def get_tile(z: int, x: int, y: int, db: Session = Depends(get_db)):
    tile = (
        db.query(Upload)
        .filter(Upload.tile_z == z, Upload.tile_x == x, Upload.tile_y == y)
        .order_by(Upload.created_at.desc())
        .first()
    )
    if not tile:
        raise HTTPException(status_code=404, detail="Tile not found")
    return FileResponse(tile.file_path)

