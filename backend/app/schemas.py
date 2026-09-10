from datetime import datetime
from typing import Any

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    role: str
    username: str


class PointRiskOut(BaseModel):
    lat: float
    lon: float
    road_distance_m: float | None = None
    settlement_distance_m: float | None = None
    road_influence: float
    base_probability: float
    fire_probability: float
    risk_level: str
    risk_reason: str
    summary: str | None = None
    explanation: dict[str, Any] | None = None


class UploadOut(BaseModel):
    id: int
    title: str
    tile_z: int
    tile_x: int
    tile_y: int
    uploaded_by: str
    created_at: datetime
    mask_url: str | None = None
    overlay_url: str | None = None

    class Config:
        from_attributes = True


class AnalyticsPointOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    road_percentage: float


class UploadAnalyticsOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    uploaded_by: str
    road_percentage: float
    background_percentage: float
    road_pixels: int
    background_pixels: int
    component_count: int
    mean_component_area: float
    largest_component_area: int
    mask_url: str | None = None
    overlay_url: str | None = None


class AnalyticsSummaryOut(BaseModel):
    total_uploads: int
    uploads_with_predictions: int
    global_road_coverage: float
    average_road_percentage: float
    max_road_percentage: float
    average_component_count: float
    timeline: list[AnalyticsPointOut]
    items: list[UploadAnalyticsOut]


class FireRiskRecordOut(BaseModel):
    id: int
    username: str
    lat: float
    lon: float
    fire_probability: float
    risk_level: str
    summary: str
    explanation: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
