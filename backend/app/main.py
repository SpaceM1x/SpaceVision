import logging
import math
import json
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .analytics import build_analytics_summary
from .auth import create_access_token, decode_token, hash_password, verify_password
from .database import Base, PREDICTION_DIR, SessionLocal, UPLOAD_DIR, engine, get_db
from .models import Upload, User
from .road_inference import run_road_segmentation
from .schemas import AnalyticsSummaryOut, LoginRequest, LoginResponse, PointRiskOut, UploadOut

app = FastAPI(title="SpaceVision API")


def _prediction_paths(upload: Upload) -> tuple[Path, Path]:
    stem = Path(upload.file_path).stem
    return (
        PREDICTION_DIR / f"{stem}_mask.png",
        PREDICTION_DIR / f"{stem}_overlay.png",
    )


def serialize_upload(upload: Upload) -> UploadOut:
    mask_path, overlay_path = _prediction_paths(upload)
    image_path = Path(upload.file_path)
    image_url = f"/uploads/{upload.id}/image" if image_path.exists() else None
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
        image_url=image_url,
        mask_url=mask_url,
        overlay_url=overlay_url,
    )


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


def _nearest_distances_from_osm(lat: float, lon: float, radius_m: int = 20000) -> tuple[float | None, float | None]:
    query = f"""
[out:json][timeout:20];
(
  way["highway"](around:{radius_m},{lat},{lon});
  node["place"~"city|town|village|hamlet|isolated_dwelling"](around:{radius_m},{lat},{lon});
);
out center;
"""
    endpoint = "https://overpass-api.de/api/interpreter?data="
    request_url = f"{endpoint}{quote(query)}"
    try:
        with urlopen(request_url, timeout=25) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"Не удалось получить данные OSM: {error}") from error

    road_distances: list[float] = []
    settlement_distances: list[float] = []

    for element in payload.get("elements", []):
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
        if tags.get("place") in {"city", "town", "village", "hamlet", "isolated_dwelling"}:
            settlement_distances.append(distance)

    road_distance = min(road_distances) if road_distances else None
    settlement_distance = min(settlement_distances) if settlement_distances else None
    return road_distance, settlement_distance


def _distance_factor(distance_m: float | None, scale_m: float) -> float:
    if distance_m is None:
        return 0.0
    return math.exp(-distance_m / scale_m)


def _risk_level_from_probability(probability: float) -> str:
    if probability >= 70:
        return "high"
    if probability >= 40:
        return "medium"
    return "low"


class IgnoreMissingTileAccessLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        is_tiles_request = "/tiles/" in message
        is_not_found = " 404 " in message or " 404 Not Found" in message
        return not (is_tiles_request and is_not_found)


def configure_access_logging():
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(log_filter, IgnoreMissingTileAccessLog) for log_filter in access_logger.filters):
        access_logger.addFilter(IgnoreMissingTileAccessLog())


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    configure_access_logging()
    Base.metadata.create_all(bind=engine)
    ensure_default_users()


def ensure_default_users():
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
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль.")
    token = create_access_token(user.username, user.role)
    return LoginResponse(access_token=token, role=user.role, username=user.username)


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
            raise HTTPException(status_code=400, detail=f"Неверное значение {field_name}: {raw_value}") from error

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
def list_uploads(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del current_user
    items = db.query(Upload).order_by(Upload.created_at.desc()).all()
    return [serialize_upload(item) for item in items]


@app.get("/analytics/summary", response_model=AnalyticsSummaryOut)
def analytics_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del current_user
    items = db.query(Upload).order_by(Upload.created_at.desc()).all()
    return build_analytics_summary(items, PREDICTION_DIR)


@app.get("/risk/point", response_model=PointRiskOut)
def point_risk(
    lat: float,
    lon: float,
    current_user: User = Depends(get_current_user),
):
    del current_user

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Некорректные координаты.")

    road_distance, settlement_distance = _nearest_distances_from_osm(lat, lon)
    road_score = _distance_factor(road_distance, scale_m=2500.0)
    settlement_score = _distance_factor(settlement_distance, scale_m=5000.0)
    # Anthropogenic fire ignition proxy: closer to roads/settlements -> higher risk.
    probability = (0.4 + 0.25 * road_score + 0.35 * settlement_score) * 100.0
    probability = max(0.0, min(100.0, probability))

    return PointRiskOut(
        lat=lat,
        lon=lon,
        road_distance_m=road_distance,
        settlement_distance_m=settlement_distance,
        fire_probability=probability,
        risk_level=_risk_level_from_probability(probability),
    )


@app.get("/uploads/{upload_id}/mask")
def get_upload_mask(upload_id: int, db: Session = Depends(get_db)):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    mask_path, _ = _prediction_paths(upload)
    if not mask_path.exists():
        raise HTTPException(status_code=404, detail="Mask not found")
    return FileResponse(mask_path)


@app.get("/uploads/{upload_id}/image")
def get_upload_image(upload_id: int, db: Session = Depends(get_db)):
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")
    image_path = Path(upload.file_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image_path)


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
