"""Point fire probability from the model trained on the ISDM registry.

The model is produced by ``ml/fire_point_model/train_fire_point_model.py``.
Features are computed on the server from the customer's vector layers, so the
method works without an uploaded roads file.

The model returns the odds of a fire relative to a random background point.
They are converted to annual intensity (fires per hectare per year) with the
registry's fire count and the area of the region, then to the probability of
at least one fire on the calculation area, as in the formula method.
"""
from __future__ import annotations

import math
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = Path(
    os.environ.get("FIRE_ML_MODEL_PATH")
    or ROOT / "ml" / "fire_point_model" / "fire_point_model.joblib"
)
DATA_DIR = Path(
    os.environ.get("FIRE_ML_DATA_DIR")
    or ROOT / "информация от заказчика" / "БНЦ"
)


class FireMLError(RuntimeError):
    """Raised when the point model or its data layers are not available."""


def _read_layer(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FireMLError(f"Слой не найден: {path}")
    return gpd.read_file(path).to_crs("EPSG:4326")


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    if not MODEL_PATH.exists():
        raise FireMLError(
            f"Модель не найдена: {MODEL_PATH}. Запустите ml/fire_point_model/train_fire_point_model.py."
        )
    saved = joblib.load(MODEL_PATH)
    crs = saved["metric_crs"]

    admin = _read_layer(
        DATA_DIR / "Административно-территориальное_деление_Бурятии"
        / "Административно-территориальное_деление_Бурятии.shp"
    ).to_crs(crs)
    roads = _read_layer(DATA_DIR / "Дороги с NexGIS" / "Дороги с NexGIS.shp")
    settle_pts = _read_layer(DATA_DIR / "Границы населенных пунктов" / "settlement-point.shp")
    settle_poly = _read_layer(DATA_DIR / "Границы населенных пунктов" / "settlement-polygon.shp")
    rail = _read_layer(DATA_DIR / "Железные_дороги" / "Железные_дороги.shp")

    road_geoms = gpd.GeoSeries(roads.geometry.values, crs="EPSG:4326").to_crs(crs).values
    rail_geoms = gpd.GeoSeries(rail.geometry.values, crs="EPSG:4326").to_crs(crs).values
    settle_geoms = np.concatenate([
        gpd.GeoSeries(settle_pts.geometry.values, crs="EPSG:4326").to_crs(crs).values,
        gpd.GeoSeries(settle_poly.geometry.boundary.values, crs="EPSG:4326").to_crs(crs).values,
    ])

    return {
        **saved,
        "transformer": Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        "admin": admin,
        "roads": (road_geoms, STRtree(road_geoms)),
        "rail": (rail_geoms, STRtree(rail_geoms)),
        "settlements": (settle_geoms, STRtree(settle_geoms)),
    }


def _nearest(geoms_and_tree: tuple, point: Point) -> float:
    geoms, tree = geoms_and_tree
    index = tree.query_nearest([point])[1][0]
    return float(point.distance(geoms[index]))


def _district(admin: gpd.GeoDataFrame, point: Point) -> int:
    hit = admin.index[admin.contains(point)]
    return int(hit[0]) if len(hit) else -1


def point_fire_probability(lat: float, lon: float, month: int | None = None) -> dict[str, Any]:
    """Annual probability of at least one fire on 1 ha at the point."""
    bundle = _bundle()
    x, y = bundle["transformer"].transform(lon, lat)
    point = Point(x, y)

    features = {
        "dist_road_m": _nearest(bundle["roads"], point),
        "dist_settlement_m": _nearest(bundle["settlements"], point),
        "dist_railway_m": _nearest(bundle["rail"], point),
        "district": _district(bundle["admin"], point),
        "month": month or date.today().month,
    }
    row = pd.DataFrame([[features[name] for name in bundle["columns"]]], columns=bundle["columns"])

    p_sample = float(bundle["model"].predict_proba(row)[0, 1])
    odds = p_sample / (1 - p_sample)
    intensity = bundle["fires_per_year"] / bundle["area_ha"] * odds
    probability = -math.expm1(-intensity)

    return {
        "features": features,
        "intensity_per_ha_year": intensity,
        "probability": probability,
        "odds": odds,
        "fires_per_year": bundle["fires_per_year"],
        "area_ha": bundle["area_ha"],
    }
