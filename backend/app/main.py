import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .auth import create_access_token, decode_token, hash_password, verify_password
from .database import Base, SessionLocal, UPLOAD_DIR, engine, get_db
from .models import Upload, User
from .schemas import LoginRequest, LoginResponse, UploadOut

app = FastAPI(title="SpaceVision API")


class IgnoreMissingTileAccessLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return '"/tiles/' not in message or " 404 " not in message


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
    tile_z: int = Form(...),
    tile_x: int = Form(...),
    tile_y: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extension = Path(file.filename).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="Поддерживаются только PNG/JPG.")
    filename = f"{uuid4().hex}{extension}"
    destination = UPLOAD_DIR / filename
    content = await file.read()
    destination.write_bytes(content)

    upload = Upload(
        title=title,
        file_path=str(destination),
        tile_z=tile_z,
        tile_x=tile_x,
        tile_y=tile_y,
        uploaded_by=current_user.username,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


@app.get("/uploads", response_model=list[UploadOut])
def list_uploads(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    del current_user
    items = db.query(Upload).order_by(Upload.created_at.desc()).all()
    return items


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
