"""Persistent history of fire-risk calculations.

Each calculation is stored as a :class:`FireRiskRecord` row. The ``summary``
field is a short human-readable string shown in the history list; the
``explanation_json`` field holds the full per-factor breakdown serialised as
JSON so the UI can expand a row into a detailed explanation.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .database import Base


class FireRiskRecord(Base):
    __tablename__ = "fire_risk_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    fire_probability: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(String(500))
    explanation_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def explanation(self) -> dict:
        """Return the stored explanation as a Python dictionary."""
        return json.loads(self.explanation_json)

    def to_out(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "lat": self.lat,
            "lon": self.lon,
            "fire_probability": self.fire_probability,
            "risk_level": self.risk_level,
            "summary": self.summary,
            "explanation": self.explanation(),
            "created_at": self.created_at,
        }


def record_fire_risk(
    db: Session,
    *,
    username: str,
    lat: float,
    lon: float,
    fire_probability: float,
    risk_level: str,
    summary: str,
    explanation: dict,
) -> FireRiskRecord:
    """Persist a single fire-risk calculation and return the stored record."""
    record = FireRiskRecord(
        username=username,
        lat=lat,
        lon=lon,
        fire_probability=fire_probability,
        risk_level=risk_level,
        summary=summary,
        explanation_json=json.dumps(explanation, ensure_ascii=False),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
