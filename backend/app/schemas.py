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
    # R — distance to the nearest SHP road, in metres.
    road_distance_m: float | None = None
    # OSM settlement distance retained by the legacy P_base model, in metres.
    settlement_distance_m: float | None = None
    # I(R) — normalised road influence, in [0, 1].
    road_influence: float
    # P_base — legacy rule-based probability, in [0, 1].
    base_probability: float
    # P_fire — final probability, in [0, 1].
    fire_probability: float
    risk_level: str
    risk_reason: str
