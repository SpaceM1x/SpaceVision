from datetime import datetime

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    role: str
    username: str


class UploadOut(BaseModel):
    id: int
    title: str
    tile_z: int
    tile_x: int
    tile_y: int
    uploaded_by: str
    created_at: datetime

    class Config:
        from_attributes = True
