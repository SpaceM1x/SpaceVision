"""Fire statistics from the ISDM registry (1T-ISDM yearly registers, Buryatia).

The registers are parsed once and cached. Each row is a fire registration with
coordinates, first observation date and registered area. Only fires above
200 ha are included in the registers.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(
    os.environ.get("FIRE_ML_DATA_DIR")
    or ROOT / "информация от заказчика" / "БНЦ"
)
ADMIN_SHP = (
    DATA_DIR / "Административно-территориальное_деление_Бурятии"
    / "Административно-территориальное_деление_Бурятии.shp"
)

DMS_RE = re.compile(
    r"(\d+)°\s*(\d+)'\s*(\d+)\"\s*с\.ш\.\s*\n?\s*(\d+)°\s*(\d+)'\s*(\d+)\"\s*в\.д\."
)
MONTHS_RU = [
    "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]


def _dms(deg: str, minute: str, sec: str) -> float:
    return int(deg) + int(minute) / 60 + int(sec) / 3600


@lru_cache(maxsize=1)
def load_fire_registry() -> pd.DataFrame:
    rows = []
    for path in sorted(DATA_DIR.glob("Дданные*/**/*ISDM.xls")):
        raw = pd.read_excel(path, sheet_name=0, header=None)
        for _, row in raw.iterrows():
            coords = str(row[1]) if pd.notna(row[1]) else ""
            match = DMS_RE.search(coords)
            if not match:
                continue
            first = pd.to_datetime(str(row[4]), dayfirst=True, errors="coerce")
            if pd.isna(first):
                continue
            rows.append({
                "lat": _dms(*match.group(1, 2, 3)),
                "lon": _dms(*match.group(4, 5, 6)),
                "date": first,
                "area_ha": pd.to_numeric(row[5], errors="coerce"),
            })
    return pd.DataFrame(rows).drop_duplicates(subset=["lat", "lon", "date"]).reset_index(drop=True)


@lru_cache(maxsize=1)
def _district_names() -> tuple[gpd.GeoDataFrame, list[str]]:
    admin = gpd.read_file(ADMIN_SHP).to_crs("EPSG:4326")
    names = [str(value) for value in admin["locname"]]
    return admin, names


@lru_cache(maxsize=1)
def fire_statistics() -> dict[str, Any]:
    fires = load_fire_registry()
    admin, names = _district_names()

    district_index = []
    for lat, lon in zip(fires["lat"], fires["lon"]):
        point = Point(lon, lat)
        hits = admin.index[admin.contains(point)]
        district_index.append(int(hits[0]) if len(hits) else -1)
    fires = fires.assign(district=district_index, year=fires["date"].dt.year)

    years = fires["year"]
    by_year = (
        fires.groupby("year")
        .agg(fires=("lat", "size"), area_ha=("area_ha", "sum"))
        .reset_index()
    )
    by_month = fires.groupby(fires["date"].dt.month).size()
    by_district = (
        fires[fires["district"] >= 0]
        .groupby("district")
        .agg(fires=("lat", "size"), area_ha=("area_ha", "sum"))
        .reset_index()
        .sort_values("fires", ascending=False)
    )

    return {
        "total_fires": int(len(fires)),
        "first_year": int(years.min()),
        "last_year": int(years.max()),
        "total_area_ha": float(fires["area_ha"].sum()),
        "mean_area_ha": float(fires["area_ha"].mean()),
        "by_year": [
            {"year": int(row.year), "fires": int(row.fires), "area_ha": float(row.area_ha)}
            for row in by_year.itertuples()
        ],
        "by_month": [
            {"month": MONTHS_RU[month - 1], "fires": int(count)}
            for month, count in by_month.items()
        ],
        "by_district": [
            {
                "name": names[int(row.district)],
                "fires": int(row.fires),
                "area_ha": float(row.area_ha),
            }
            for row in by_district.itertuples()
        ],
    }
