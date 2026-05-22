import logging
import math
import json
import importlib
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import text
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
    dynamic_bounds = _extract_geotiff_bounds(image_path) if image_path.exists() else None
    min_lat = dynamic_bounds[0] if dynamic_bounds else upload.min_lat
    max_lat = dynamic_bounds[1] if dynamic_bounds else upload.max_lat
    min_lon = dynamic_bounds[2] if dynamic_bounds else upload.min_lon
    max_lon = dynamic_bounds[3] if dynamic_bounds else upload.max_lon
    return UploadOut(
        id=upload.id,
        title=upload.title,
        tile_z=upload.tile_z,
        tile_x=upload.tile_x,
        tile_y=upload.tile_y,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        uploaded_by=upload.uploaded_by,
        created_at=upload.created_at,
        image_url=image_url,
        mask_url=mask_url,
        overlay_url=overlay_url,
    )


def _extract_geotiff_bounds(file_path: Path) -> tuple[float, float, float, float] | None:
    if file_path.suffix.lower() not in {".tif", ".tiff"}:
        return None
    try:
        with Image.open(file_path) as image:
            tags = getattr(image, "tag_v2", None)
            if tags is None:
                return None
            tiepoints = tags.get(33922)
            pixel_scale = tags.get(33550)
            geokey_directory = tags.get(34735)
            if not tiepoints or not pixel_scale or len(tiepoints) < 6 or len(pixel_scale) < 2:
                return None
            tie_i = float(tiepoints[0])
            tie_j = float(tiepoints[1])
            origin_x = float(tiepoints[3])
            origin_y = float(tiepoints[4])
            scale_x = float(pixel_scale[0])
            scale_y = float(pixel_scale[1])
            if scale_x == 0 or scale_y == 0:
                return None
            width, height = image.size

            def pixel_to_model(pixel_i: float, pixel_j: float) -> tuple[float, float]:
                model_x = origin_x + (pixel_i - tie_i) * scale_x
                model_y = origin_y + (pixel_j - tie_j) * (-scale_y)
                return model_x, model_y

            top_left = pixel_to_model(0.0, 0.0)
            bottom_right = pixel_to_model(float(width), float(height))
            left, right = sorted((top_left[0], bottom_right[0]))
            bottom, top = sorted((top_left[1], bottom_right[1]))

            def extract_epsg_code() -> int | None:
                if not geokey_directory or len(geokey_directory) < 4:
                    return None
                key_count = int(geokey_directory[3])
                expected_length = 4 + key_count * 4
                if len(geokey_directory) < expected_length:
                    return None
                keys = geokey_directory[4:expected_length]
                projected_epsg = None
                geographic_epsg = None
                for idx in range(0, len(keys), 4):
                    key_id = int(keys[idx])
                    location = int(keys[idx + 1])
                    count = int(keys[idx + 2])
                    value = int(keys[idx + 3])
                    if location == 0 and count == 1:
                        if key_id == 3072:  # ProjectedCSTypeGeoKey
                            projected_epsg = value
                        if key_id == 2048:  # GeographicTypeGeoKey
                            geographic_epsg = value
                return projected_epsg or geographic_epsg

            epsg_code = extract_epsg_code()
            if epsg_code and epsg_code != 4326:
                pyproj_module = importlib.util.find_spec("pyproj")
                if pyproj_module is None:
                    return None
                try:
                    Transformer = importlib.import_module("pyproj").Transformer
                    transformer = Transformer.from_crs(f"EPSG:{epsg_code}", "EPSG:4326", always_xy=True)
                    left, bottom = transformer.transform(left, bottom)
                    right, top = transformer.transform(right, top)
                    left, right = sorted((left, right))
                    bottom, top = sorted((bottom, top))
                except Exception:
                    return None

            min_lat, max_lat = sorted((bottom, top))
            min_lon, max_lon = sorted((left, right))
            if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
                return None
            if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
                return None
            if (max_lat - min_lat) > 40 or (max_lon - min_lon) > 40:
                return None
            return min_lat, max_lat, min_lon, max_lon
    except Exception:
        return None


def _ensure_upload_geo_columns():
    with engine.begin() as connection:
        existing_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(uploads)")).fetchall()
        }
        alter_queries = {
            "min_lat": "ALTER TABLE uploads ADD COLUMN min_lat FLOAT",
            "max_lat": "ALTER TABLE uploads ADD COLUMN max_lat FLOAT",
            "min_lon": "ALTER TABLE uploads ADD COLUMN min_lon FLOAT",
            "max_lon": "ALTER TABLE uploads ADD COLUMN max_lon FLOAT",
        }
        for column_name, query in alter_queries.items():
            if column_name not in existing_columns:
                connection.execute(text(query))


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


def _nominatim_fallback_context(lat: float, lon: float) -> dict[str, float | None]:
    params = urlencode(
        {
            "format": "jsonv2",
            "lat": f"{lat:.7f}",
            "lon": f"{lon:.7f}",
            "zoom": "17",
            "addressdetails": "1",
        }
    )
    endpoint = f"https://nominatim.openstreetmap.org/reverse?{params}"
    request = Request(
        endpoint,
        headers={
            "User-Agent": "SpaceVision/1.0 (local fire risk prototype)",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload_json = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError):
        return {
            "road_distance_m": None,
            "settlement_distance_m": None,
            "road_density": 0.0,
            "settlement_density": 0.0,
        }

    address = payload_json.get("address", {})
    has_road = any(key in address for key in {"road", "pedestrian", "footway", "cycleway"})
    has_settlement = any(
        key in address
        for key in {"city", "town", "village", "hamlet", "municipality", "county", "state_district"}
    )

    return {
        "road_distance_m": 120.0 if has_road else None,
        "settlement_distance_m": 450.0 if has_settlement else None,
        "road_density": 0.52 if has_road else 0.0,
        "settlement_density": 0.58 if has_settlement else 0.0,
    }


def _nearest_distances_from_osm(lat: float, lon: float, radius_m: int = 12000) -> dict[str, float | None]:
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
        return _nominatim_fallback_context(lat, lon)

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
        return _nominatim_fallback_context(lat, lon)
    return {
        "road_distance_m": road_distance,
        "settlement_distance_m": settlement_distance,
        "road_density": road_density,
        "settlement_density": settlement_density,
    }


def _risk_level_from_probability(probability: float) -> str:
    if probability >= 75:
        return "high"
    if probability >= 45:
        return "medium"
    return "low"


def _distance_decay_score(distance_m: float | None, max_score: float, scale_m: float) -> float:
    if distance_m is None:
        return 0.0
    return max_score * math.exp(-distance_m / scale_m)


def _seasonal_component(month: int) -> float:
    # Approximation for continental climate: higher fire risk in warm dry season.
    month_weights = {
        1: -4.0,
        2: -3.0,
        3: -1.0,
        4: 3.0,
        5: 7.0,
        6: 10.0,
        7: 11.0,
        8: 8.0,
        9: 4.0,
        10: 1.0,
        11: -2.0,
        12: -4.0,
    }
    return month_weights.get(month, 0.0)


def _diurnal_component(utc_dt: datetime, lon: float) -> float:
    # Local solar time approximation from longitude without timezone DB.
    local_hour = (utc_dt.hour + lon / 15.0) % 24.0
    afternoon_peak = math.exp(-((local_hour - 15.0) ** 2) / (2 * 3.2**2))
    return -1.0 + afternoon_peak * 5.0


def _build_risk_reason(
    probability: float,
    road_distance: float | None,
    settlement_distance: float | None,
    road_density: float,
    settlement_density: float,
    season_score: float,
    diurnal_score: float,
) -> str:
    if road_distance is None and settlement_distance is None:
        return (
            "Риск оценен по ограниченным данным OSM: рядом не удалось надежно определить дороги и поселения, "
            "поэтому вероятность снижена и требует ручной проверки."
        )

    proximity_pressure = max(
        _distance_decay_score(road_distance, max_score=1.0, scale_m=2100.0),
        _distance_decay_score(settlement_distance, max_score=1.0, scale_m=6200.0),
    )
    anthropogenic_pressure = max(
        proximity_pressure,
        0.7 * road_density + 0.6 * settlement_density,
    )
    temporal_pressure = season_score + diurnal_score

    risk_level = _risk_level_from_probability(probability)
    if risk_level == "high":
        if anthropogenic_pressure >= 0.72:
            return (
                "Высокий риск: точка расположена в зоне сильного антропогенного влияния "
                "(близко к дорогам/населенным пунктам), где выше вероятность возгораний от деятельности человека."
            )
        if temporal_pressure >= 10:
            return (
                "Высокий риск: сезонный и дневной факторы сейчас близки к пиковым, "
                "поэтому даже при умеренной удаленности от инфраструктуры вероятность пожара повышена."
            )
        return (
            "Высокий риск: совокупность факторов (инфраструктура поблизости, плотность объектов и текущие временные условия) "
            "сформировала критически высокую вероятность возгорания."
        )

    if risk_level == "medium":
        if anthropogenic_pressure >= 0.55:
            return (
                "Средний риск: есть заметная близость к дорогам или населенным пунктам, "
                "что увеличивает вероятность антропогенного источника огня."
            )
        if temporal_pressure >= 5:
            return (
                "Средний риск: ключевой вклад вносят сезон и время суток, "
                "поэтому вероятность пожара выше фоновой даже без экстремальной близости к инфраструктуре."
            )
        return (
            "Средний риск: факторы опасности выражены умеренно и не достигают критических значений, "
            "но требуют наблюдения."
        )

    if anthropogenic_pressure < 0.25 and temporal_pressure < 3:
        return (
            "Низкий риск: точка достаточно удалена от основных источников антропогенного воздействия, "
            "а текущие сезонно-временные условия близки к фоновым."
        )
    return (
        "Низкий риск: существенных факторов, указывающих на высокую вероятность возгорания, не выявлено."
    )


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
    _ensure_upload_geo_columns()
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
    if extension not in {".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail="Поддерживаются только TIFF файлы (.tif, .tiff).")
    filename = f"{uuid4().hex}{extension}"
    destination = UPLOAD_DIR / filename
    content = await file.read()
    destination.write_bytes(content)
    geotiff_bounds = _extract_geotiff_bounds(destination)
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
        min_lat=geotiff_bounds[0] if geotiff_bounds else None,
        max_lat=geotiff_bounds[1] if geotiff_bounds else None,
        min_lon=geotiff_bounds[2] if geotiff_bounds else None,
        max_lon=geotiff_bounds[3] if geotiff_bounds else None,
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

    osm_context = _nearest_distances_from_osm(lat, lon)
    road_distance = osm_context["road_distance_m"]
    settlement_distance = osm_context["settlement_distance_m"]
    road_density = float(osm_context["road_density"] or 0.0)
    settlement_density = float(osm_context["settlement_density"] or 0.0)

    # Rule-based wildfire ignition model:
    # human access pressure (roads + settlements) + temporal (season + daytime).
    base_score = 14.0
    road_distance_score = _distance_decay_score(road_distance, max_score=28.0, scale_m=2100.0)
    settlement_distance_score = _distance_decay_score(settlement_distance, max_score=24.0, scale_m=6200.0)
    road_density_score = 16.0 * road_density
    settlement_density_score = 14.0 * settlement_density
    now_utc = datetime.utcnow()
    season_score = _seasonal_component(now_utc.month)
    diurnal_score = _diurnal_component(now_utc, lon)
    data_penalty = -8.0 if road_distance is None and settlement_distance is None else 0.0

    probability = (
        base_score
        + road_distance_score
        + settlement_distance_score
        + road_density_score
        + settlement_density_score
        + season_score
        + diurnal_score
        + data_penalty
    )
    probability = max(0.0, min(100.0, probability))
    risk_reason = _build_risk_reason(
        probability=probability,
        road_distance=road_distance,
        settlement_distance=settlement_distance,
        road_density=road_density,
        settlement_density=settlement_density,
        season_score=season_score,
        diurnal_score=diurnal_score,
    )

    return PointRiskOut(
        lat=lat,
        lon=lon,
        road_distance_m=road_distance,
        settlement_distance_m=settlement_distance,
        fire_probability=probability,
        risk_level=_risk_level_from_probability(probability),
        risk_reason=risk_reason,
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
