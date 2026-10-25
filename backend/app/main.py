"""SpaceVision API: AI road recognition + SHP fire risk."""
import logging
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pyproj import Transformer
from shapely.geometry import Point
from sqlalchemy.orm import Session

from .analytics import build_analytics_summary
from .auth import create_access_token, decode_token, hash_password, verify_password
from .config import METRIC_CRS, R0_METERS, ROADS_SHP_PATH
from .database import (
    PREDICTION_DIR,
    SessionLocal,
    UPLOAD_DIR,
    ensure_schema,
    get_db,
)
from .distance import distance_to_nearest_road, road_density_near_point
from .fire_history import FireRiskRecord, record_fire_risk
from .fire_image import (
    FireImageModelError,
    classify_image_bytes,
    model_status,
    start_preload,
)
from .fire_risk import (
    base_probability_breakdown,
    final_probability,
    risk_level_from_probability,
)
from .gis import select_metric_crs, to_metric
from .models import Upload, User
from .osm import nearest_distances_from_osm
from .road_data import (
    RoadDataError,
    RoadDataProvider,
    build_roads_cache,
    get_roads_cache,
    invalidate_roads_cache,
)
from .road_influence import road_influence
from .satellite import SatelliteTileError, fetch_satellite_tile
from .schemas import (
    AnalyticsSummaryOut,
    FireImageRiskOut,
    FireModelStatusOut,
    FireRiskRecordOut,
    LoginRequest,
    LoginResponse,
    PointRiskOut,
    UploadOut,
)
from .weather import fire_weather

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
        cache = get_roads_cache()
        if cache is None:
            cache = build_roads_cache(ROADS_SHP_PATH, METRIC_CRS)
    except RoadDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return json.loads(cache.gdf.to_crs("EPSG:4326").to_json())


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

    # Refresh the in-memory road cache now that the SHP has been replaced.
    try:
        build_roads_cache(ROADS_SHP_PATH, METRIC_CRS)
    except RoadDataError:
        invalidate_roads_cache()

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
    invalidate_roads_cache()
    return {"removed": removed, "uploaded": False}


_ROAD_SOURCE_LABELS = {"shp": "SHP", "osm": "OSM (резерв)", "none": "нет данных"}


_AI_PROB_BASE = 0.005
_AI_PROB_SCALE = 0.30
_AI_PROB_EXP = 1.6

_context_executor = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="risk-context"
)


def _collect_risk_context(lat: float, lon: float) -> tuple[dict, dict]:
    """Fetch optional OSM and fire-weather context concurrently."""
    osm_future = _context_executor.submit(nearest_distances_from_osm, lat, lon)
    weather_future = _context_executor.submit(fire_weather, lat, lon)
    return osm_future.result(), weather_future.result()


def _ai_probability(risk_score: float) -> float:
    """Calibrate the image model's 0..1 risk score to a point probability.

    The image classifier is a land-cover/fire-risk classifier, not a calibrated
    ignition forecast.  This monotone mapping keeps its ranking while placing
    the result on a plausible 0.5–30% scale for the current fire season.
    """
    score = max(0.0, min(1.0, float(risk_score or 0.0)))
    return min(0.95, _AI_PROB_BASE + _AI_PROB_SCALE * (score**_AI_PROB_EXP))


def _build_risk_reason(
    p_fire: float,
    p_base: float,
    influence: float,
    road_distance_m: float | None,
    r0_m: float,
    road_source: str,
    weather: dict | None = None,
) -> str:
    percent = p_fire * 100.0
    road_txt = (
        f"ближайшая дорога в {road_distance_m:.0f} м"
        if road_distance_m is not None
        else "нет данных о дорогах"
    )
    source_txt = _ROAD_SOURCE_LABELS.get(road_source, road_source)
    weather_txt = ""
    if weather and weather.get("source") == "nasa-power":
        weather_txt = (
            f" Индекс Нестерова N={float(weather.get('index') or 0):.0f} "
            f"(FWI={float(weather.get('normalized') or 0):.2f})."
        )
    return (
        f"Вероятность возгорания {percent:.1f}% в текущем пожароопасном сезоне. "
        f"Логит-модель: P_base {p_base * 100:.1f}%, вклад дороги учтён в P_base "
        f"(I(R)={influence:.2f}, R0={r0_m:.0f} м, источник {source_txt}), "
        f"{road_txt}.{weather_txt}"
    )


def _build_risk_summary(
    lat: float,
    lon: float,
    p_fire: float,
    *,
    method: str = "formula",
    ai_label: str | None = None,
) -> str:
    if method == "ai":
        label = f", класс «{ai_label}»" if ai_label else ""
        return (
            f"{(p_fire * 100.0):.1f}% по снимку{label} "
            f"(широта {lat:.4f}, долгота {lon:.4f})"
        )
    return (
        f"{(p_fire * 100.0):.1f}% в текущем пожароопасном сезоне "
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
    p_fire: float,
    weather: dict | None = None,
) -> dict:
    """Build a structured, per-factor explanation of one calculation."""
    coefficients = base["coefficients"]
    source_txt = _ROAD_SOURCE_LABELS.get(base["road_source"], base["road_source"])
    return {
        "method": "formula",
        "equation": (
            "P_fire = 1 / (1 + exp(−logit)),  "
            "logit = b0 + Σ b_i·x_i + b_FWI·FWI"
        ),
        "coordinates": {"lat": lat, "lon": lon},
        "weather": weather,
        "base": {
            "label": "Вероятность P_fire (логит-модель)",
            "formula": (
                f"{coefficients['constant']:.2f} "
                f"+ {coefficients['road']:.2f}·дорога "
                f"+ {coefficients['settlement']:.2f}·поселение "
                f"+ {coefficients['road_density']:.2f}·ρ_дорог "
                f"+ {coefficients['settlement_density']:.2f}·ρ_поселений "
                f"+ {coefficients['season']:.2f}·сезон "
                f"+ {coefficients['diurnal']:.2f}·суточ "
                f"+ {coefficients['fire_weather']:.2f}·FWI "
                f"+ {coefficients['interaction']:.2f}·дорога·поселение"
            ),
            "result": base["p_base"],
            "logit": base["logit"],
            "factors": [
                {"name": "Свободный член b0", "value": base["constant"], "note": "смещение логита"},
                {
                    "name": "Близость к дороге",
                    "value": base["road_contribution"],
                    "input": base["road_distance_m"],
                    "note": (
                        f"{coefficients['road']:.2f}·I(R), источник {source_txt}"
                    ),
                },
                {
                    "name": "Близость к поселению",
                    "value": base["settlement_contribution"],
                    "input": base["settlement_distance_m"],
                    "note": (
                        f"{coefficients['settlement']:.2f}·exp(−d/3000 м)"
                    ),
                },
                {
                    "name": "Плотность дорог",
                    "value": base["road_density_contribution"],
                    "input": base["road_density"],
                    "note": f"{coefficients['road_density']:.2f}·ρ_дорог (SHP/OSM)",
                },
                {
                    "name": "Плотность поселений",
                    "value": base["settlement_density_contribution"],
                    "input": base["settlement_density"],
                    "note": f"{coefficients['settlement_density']:.2f}·ρ_поселений",
                },
                {
                    "name": "Сезонный фактор",
                    "value": base["season_contribution"],
                    "input": base["season"],
                    "note": (
                        f"{coefficients['season']:.2f}·сезон "
                        f"(месяц {base['season_month']})"
                    ),
                },
                {
                    "name": "Суточный фактор",
                    "value": base["diurnal_contribution"],
                    "input": base["diurnal"],
                    "note": f"{coefficients['diurnal']:.2f}·пик (15:00)",
                },
                {
                    "name": "Погодная опасность (FWI)",
                    "value": base["fire_weather_contribution"],
                    "input": base["fire_weather_index"],
                    "note": (
                        f"{coefficients['fire_weather']:.2f}·FWI "
                        f"(индекс Нестерова: {weather.get('index', '—') if weather else '—'})"
                    ),
                },
                {
                    "name": "Взаимодействие дорога×поселение",
                    "value": base["interaction_contribution"],
                    "input": base["interaction"],
                    "note": f"{coefficients['interaction']:.2f}·дорога·поселение",
                },
            ],
        },
        "road": {
            "label": "Дорога в модели (учтена в P_base)",
            "formula": "I(R) = 1 / (1 + R / R0)",
            "R": road_distance_m,
            "R0": base["road_r0_m"],
            "source": base["road_source"],
            "result": influence,
        },
        "final": {
            "label": "Итоговая вероятность P_fire (текущий сезон)",
            "formula": "P_fire = P_base (вклад дороги уже внутри логита)",
            "result": p_fire,
            "terms": [
                {"name": "logit(P)", "value": base["logit"]},
                {"name": "P_base", "value": base["p_base"]},
                {"name": "P_fire", "value": p_fire},
            ],
        },
    }


def _build_ai_explanation(
    *,
    lat: float,
    lon: float,
    p_ai: float,
    ai: dict,
    tile: dict,
) -> dict:
    """Explain the point-level image-model method and its calibration."""
    return {
        "method": "ai",
        "equation": (
            f"P_AI = {_AI_PROB_BASE:.3f} + {_AI_PROB_SCALE:.2f} · "
            f"risk_score^{_AI_PROB_EXP:.1f}"
        ),
        "coordinates": {"lat": lat, "lon": lon},
        "ai": {
            "label": "Предобученная модель SigLIP2",
            "model_id": ai["model_id"],
            "predicted": ai["predicted"],
            "predicted_ru": ai["predicted_ru"],
            "confidence": ai["confidence"],
            "risk_score": ai["risk_score"],
            "probabilities": ai["probabilities"],
            "tile": {
                "z": tile["z"],
                "x": tile["x"],
                "y": tile["y"],
                "url": tile["url"],
            },
        },
        "final": {
            "label": "Вероятность возгорания по снимку",
            "formula": (
                f"P_AI = {_AI_PROB_BASE:.3f} + {_AI_PROB_SCALE:.2f} · "
                f"risk_score^{_AI_PROB_EXP:.1f}"
            ),
            "result": p_ai,
            "terms": [
                {"name": "Класс модели", "value": ai["predicted_ru"]},
                {"name": "Уверенность", "value": ai["confidence"]},
                {"name": "Индекс риска (0..1)", "value": ai["risk_score"]},
                {"name": "P_AI", "value": p_ai},
            ],
        },
    }


@app.get("/risk/point", response_model=PointRiskOut)
def point_risk(
    lat: float,
    lon: float,
    method: Literal["formula", "ai"] = "formula",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PointRiskOut:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Некорректные координаты.")

    cache = get_roads_cache()
    if cache is None:
        try:
            cache = build_roads_cache(ROADS_SHP_PATH, METRIC_CRS)
        except RoadDataError:
            # The SHP layer is optional: the formula can fall back to OSM,
            # and the AI method does not need roads at all.
            cache = None

    roads_metric = cache.roads_metric if cache is not None else None
    point_metric = None
    r = None
    if cache is not None:
        transformer = Transformer.from_crs(
            "EPSG:4326", cache.metric_crs, always_xy=True
        )
        x, y = transformer.transform(lon, lat)
        point_metric = Point(x, y)
        r = distance_to_nearest_road(point_metric, roads_metric, cache.tree)

    influence = road_influence(r, R0_METERS) if r is not None else 0.0
    road_source = "shp" if r is not None else "none"

    if method == "ai":
        status = model_status()
        if status["state"] in {"not_loaded", "loading"}:
            start_preload()
            raise HTTPException(
                status_code=503,
                detail=(
                    "ИИ-модель ещё загружается. Первый запуск может занять "
                    "несколько минут — повторите расчёт после подготовки модели."
                ),
            )
        if status["state"] != "ready":
            raise HTTPException(
                status_code=503,
                detail=status.get("error")
                or "ИИ-модель недоступна. Проверьте её состояние в разделе «ИИ-оценка снимка».",
            )

        try:
            tile = fetch_satellite_tile(lat, lon)
            ai = classify_image_bytes(tile["data"])
        except (SatelliteTileError, FireImageModelError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        p_ai = _ai_probability(float(ai.get("risk_score") or 0.0))
        level = risk_level_from_probability(p_ai * 100.0)
        summary = _build_risk_summary(
            lat, lon, p_ai, method="ai", ai_label=ai.get("predicted_ru")
        )
        explanation = _build_ai_explanation(
            lat=lat, lon=lon, p_ai=p_ai, ai=ai, tile=tile
        )
        reason = (
            f"ИИ-модель по космоснимку участка: класс «{ai.get('predicted_ru')}», "
            f"уверенность {(float(ai.get('confidence') or 0.0) * 100):.1f}%, "
            f"индекс риска {(float(ai.get('risk_score') or 0.0) * 100):.0f}%. "
            f"Итоговая вероятность {p_ai * 100:.1f}% в текущем пожароопасном сезоне."
        )

        record_fire_risk(
            db,
            username=current_user.username,
            lat=lat,
            lon=lon,
            fire_probability=p_ai,
            risk_level=level,
            summary=summary,
            explanation=explanation,
        )

        return PointRiskOut(
            lat=lat,
            lon=lon,
            method="ai",
            road_distance_m=r,
            settlement_distance_m=None,
            road_influence=influence,
            road_source=road_source,
            base_probability=p_ai,
            fire_probability=p_ai,
            risk_level=level,
            risk_reason=reason,
            summary=summary,
            explanation=explanation,
        )

    # Formula method: OSM settlement/density context, live fire weather, season
    # and time of day. The road factor is taken from the SHP layer (OSM is a
    # fallback when no SHP is available).
    osm_context, weather = _collect_risk_context(lat, lon)
    if (
        cache is not None
        and roads_metric is not None
        and point_metric is not None
        and not roads_metric.empty
    ):
        try:
            shp_density = road_density_near_point(
                point_metric, roads_metric, cache.tree
            )
            road_density = min(1.0, shp_density)
        except Exception:  # pragma: no cover - defensive for invalid user geometry
            road_density = 0.0
    else:
        road_density = float(osm_context["road_density"] or 0.0)

    base = base_probability_breakdown(
        road_distance_m=osm_context["road_distance_m"],
        settlement_distance_m=osm_context["settlement_distance_m"],
        road_density=road_density,
        settlement_density=float(osm_context["settlement_density"] or 0.0),
        now_utc=datetime.utcnow(),
        lon=lon,
        road_distance_shp_m=r,
        road_r0_m=R0_METERS,
        fire_weather_index=float(weather.get("normalized") or 0.0),
    )
    influence = base["road_proximity"]
    p_base = base["p_base"]
    p_fire = final_probability(p_base)
    level = risk_level_from_probability(p_fire * 100.0)

    explanation = _build_risk_explanation(
        lat=lat,
        lon=lon,
        road_distance_m=base["road_distance_m"],
        settlement_distance_m=osm_context["settlement_distance_m"],
        influence=influence,
        base=base,
        p_fire=p_fire,
        weather=weather,
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
        method="formula",
        road_distance_m=base["road_distance_m"],
        settlement_distance_m=osm_context["settlement_distance_m"],
        road_influence=influence,
        road_source=base["road_source"],
        base_probability=p_base,
        fire_probability=p_fire,
        risk_level=level,
        risk_reason=_build_risk_reason(
            p_fire,
            p_base,
            influence,
            base["road_distance_m"],
            R0_METERS,
            base["road_source"],
            weather=weather,
        ),
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


@app.get("/ai/fire-risk/status", response_model=FireModelStatusOut)
def ai_fire_risk_status(
    current_user: User = Depends(get_current_user),
) -> FireModelStatusOut:
    """Report whether the pretrained image fire-risk model is ready."""
    del current_user
    return FireModelStatusOut(**model_status())


@app.post("/ai/fire-risk/preload", response_model=FireModelStatusOut)
def ai_fire_risk_preload(
    current_user: User = Depends(get_current_user),
) -> FireModelStatusOut:
    """Start loading the pretrained model in the background."""
    del current_user
    return FireModelStatusOut(**start_preload())


@app.post("/ai/fire-risk/image", response_model=FireImageRiskOut)
async def ai_fire_risk_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> FireImageRiskOut:
    """Classify an uploaded image with the pretrained fire-risk model."""
    del current_user
    data = await file.read()
    try:
        result = classify_image_bytes(data)
    except FireImageModelError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return FireImageRiskOut(**result)


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

