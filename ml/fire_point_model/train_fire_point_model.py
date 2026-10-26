"""Prototype: probability of a forest fire at a point, trained on the ISDM registry.

Positives: fire registration points from the 1T-ISDM yearly registers (Buryatia).
Negatives: random points inside Buryatia (1:1 with positives).
Features: distances to roads / settlements / railways, district, month.

The model output is converted to the project's annual intensity scale
(fires per hectare per year), so it can be compared with the formula in
backend/app/fire_probability.py:  lambda = L0 * exp(-B*R_road) * exp(-G*R_settlement).

Run from the project root:
    python ml/fire_point_model/train_fire_point_model.py
"""
from __future__ import annotations

import re
from pathlib import Path

import geopandas as gpd
import joblib
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import Point
from shapely.ops import unary_union
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
CUSTOMER = ROOT / "информация от заказчика" / "БНЦ"
OUT_DIR = Path(__file__).resolve().parent
METRIC_CRS = (  # Albers equal-area centred on Buryatia: metre-accurate distances and areas
    "+proj=aea +lat_1=50 +lat_2=57 +lat_0=53.5 +lon_0=108 +datum=WGS84 +units=m +no_defs"
)
NEG_PER_POS = 1.0
RNG = np.random.default_rng(42)
TRAIN_UNTIL_YEAR = 2020

# Same values as backend/app/fire_probability.py
LAMBDA0 = 0.0012
BETA = 0.0025
GAMMA = 0.0012

DMS_RE = re.compile(
    r"(\d+)°\s*(\d+)'\s*(\d+)\"\s*с\.ш\.\s*\n?\s*(\d+)°\s*(\d+)'\s*(\d+)\"\s*в\.д\."
)


def dms_to_deg(deg: str, minute: str, sec: str) -> float:
    return int(deg) + int(minute) / 60 + int(sec) / 3600


def load_fires() -> pd.DataFrame:
    rows = []
    for path in sorted(CUSTOMER.glob("Дданные*/**/*ISDM.xls")):
        raw = pd.read_excel(path, sheet_name=0, header=None)
        for _, row in raw.iterrows():
            coords = str(row[1]) if pd.notna(row[1]) else ""
            match = DMS_RE.search(coords)
            if not match:
                continue
            lat = dms_to_deg(*match.group(1, 2, 3))
            lon = dms_to_deg(*match.group(4, 5, 6))
            first = pd.to_datetime(str(row[4]), dayfirst=True, errors="coerce")
            area = pd.to_numeric(row[5], errors="coerce")
            if pd.isna(first):
                continue
            rows.append({"lat": lat, "lon": lon, "date": first, "area_ha": area})
    fires = pd.DataFrame(rows).drop_duplicates(subset=["lat", "lon", "date"])
    return fires.reset_index(drop=True)


def load_layers():
    admin = gpd.read_file(
        CUSTOMER / "Административно-территориальное_деление_Бурятии"
        / "Административно-территориальное_деление_Бурятии.shp"
    ).to_crs("EPSG:4326")
    roads = gpd.read_file(CUSTOMER / "Дороги с NexGIS" / "Дороги с NexGIS.shp").to_crs("EPSG:4326")
    settle_pts = gpd.read_file(
        CUSTOMER / "Границы населенных пунктов" / "settlement-point.shp"
    ).to_crs("EPSG:4326")
    settle_poly = gpd.read_file(
        CUSTOMER / "Границы населенных пунктов" / "settlement-polygon.shp"
    ).to_crs("EPSG:4326")
    rail = gpd.read_file(CUSTOMER / "Железные_дороги" / "Железные_дороги.shp").to_crs("EPSG:4326")
    return admin, roads, settle_pts, settle_poly, rail


def sample_background(admin: gpd.GeoDataFrame, n: int) -> pd.DataFrame:
    region = unary_union(admin.geometry)
    minx, miny, maxx, maxy = region.bounds
    points = []
    while len(points) < n:
        lon = RNG.uniform(minx, maxx, n)
        lat = RNG.uniform(miny, maxy, n)
        for x, y in zip(lon, lat):
            if region.contains(Point(x, y)):
                points.append((y, x))
                if len(points) >= n:
                    break
    return pd.DataFrame(points, columns=["lat", "lon"])


def nearest_distance(tree: STRtree, geoms_metric, points_metric: np.ndarray) -> np.ndarray:
    pts = [Point(x, y) for x, y in points_metric]
    idx_point, idx_geom = tree.query_nearest(pts, return_distance=False, all_matches=False)
    dist = np.full(len(pts), np.nan)
    for p_i, g_i in zip(idx_point, idx_geom):
        dist[p_i] = pts[p_i].distance(geoms_metric[g_i])
    return dist


def to_metric(geoms, crs_from="EPSG:4326"):
    return gpd.GeoSeries(geoms, crs=crs_from).to_crs(METRIC_CRS).values


def build_features(df: pd.DataFrame, layers) -> pd.DataFrame:
    admin, roads, settle_pts, settle_poly, rail = layers
    transformer = Transformer.from_crs("EPSG:4326", METRIC_CRS, always_xy=True)
    xs, ys = transformer.transform(df["lon"].values, df["lat"].values)
    pts = np.column_stack([xs, ys])

    road_geoms = to_metric(roads.geometry.values)
    rail_geoms = to_metric(rail.geometry.values)
    settle_geoms = np.concatenate([
        to_metric(settle_pts.geometry.values),
        to_metric(settle_poly.geometry.boundary.values),
    ])

    out = pd.DataFrame(index=df.index)
    out["dist_road_m"] = nearest_distance(STRtree(road_geoms), road_geoms, pts)
    out["dist_settlement_m"] = nearest_distance(STRtree(settle_geoms), settle_geoms, pts)
    out["dist_railway_m"] = nearest_distance(STRtree(rail_geoms), rail_geoms, pts)

    admin_m = admin.to_crs(METRIC_CRS)
    district = np.full(len(df), -1)
    for i, (x, y) in enumerate(pts):
        point = Point(x, y)
        hit = admin_m.index[admin_m.contains(point)]
        if len(hit):
            district[i] = int(hit[0])
    out["district"] = district
    out["month"] = df["date"].dt.month.values
    return out


def fit_formula_parameters(X: pd.DataFrame, y: np.ndarray, fires_per_year: float, area_ha: float) -> dict:
    """Fit lambda0, beta, gamma of the project formula to the ISDM data.

    The background is uniform and sampled 1:1, so log-odds of a point equal
    log(lambda / (fires_per_year / area_ha)) up to the scale of the intercept.
    A logistic regression on the two distances therefore gives the formula's
    exponents directly: log lambda = log lambda0 - beta * R_road - gamma * R_settlement.
    """
    from sklearn.linear_model import LogisticRegression

    distances_km = X[["dist_road_m", "dist_settlement_m"]].values / 1000
    logit = LogisticRegression(C=1e6, max_iter=1000).fit(distances_km, y)
    coef_road_km, coef_settlement_km = logit.coef_[0]
    intercept = logit.intercept_[0]
    lambda0 = fires_per_year / area_ha * np.exp(intercept)
    return {
        "LAMBDA0": float(lambda0),
        "BETA": float(-coef_road_km / 1000),
        "GAMMA": float(-coef_settlement_km / 1000),
    }


def formula_lambda(dist_road: np.ndarray, dist_settlement: np.ndarray) -> np.ndarray:
    return formula_lambda_with(
        {"LAMBDA0": LAMBDA0, "BETA": BETA, "GAMMA": GAMMA}, dist_road, dist_settlement
    )


def formula_lambda_with(params: dict, dist_road: np.ndarray, dist_settlement: np.ndarray) -> np.ndarray:
    return (
        params["LAMBDA0"]
        * np.exp(-params["BETA"] * dist_road)
        * np.exp(-params["GAMMA"] * dist_settlement)
    )


def compare_with_formula(X: pd.DataFrame, lam_model: np.ndarray) -> None:
    bins = [0, 0.5, 1, 2, 5, 10, np.inf]
    labels = ["0-0.5", "0.5-1", "1-2", "2-5", "5-10", ">10"]
    frame = pd.DataFrame({
        "road_km": X["dist_road_m"].values / 1000,
        "model_p": 1 - np.exp(-lam_model),
        "formula_p": 1 - np.exp(-formula_lambda(X["dist_road_m"].values, X["dist_settlement_m"].values)),
    })
    frame["bin"] = pd.cut(frame["road_km"], bins=bins, labels=labels, right=False)
    table = frame.groupby("bin", observed=True)[["model_p", "formula_p"]].mean()
    table["ratio_model_to_formula"] = table["model_p"] / table["formula_p"]
    print("\nAnnual probability for 1 ha, mean by distance to road (km):")
    print(table.to_string(float_format=lambda v: f"{v:.6f}"))
    print(f"\nOverall mean  model: {frame['model_p'].mean():.6f}   formula: {frame['formula_p'].mean():.6f}")


def main() -> None:
    fires = load_fires()
    print(f"fire points parsed: {len(fires)}")

    layers = load_layers()
    admin = layers[0]

    background = sample_background(admin, int(len(fires) * NEG_PER_POS))
    background["date"] = pd.to_datetime(
        {
            "year": RNG.choice(fires["date"].dt.year.values, len(background)),
            "month": RNG.choice(fires["date"].dt.month.values, len(background)),
            "day": 15,
        }
    )

    fires = fires.assign(label=1)
    background = background.assign(label=0)
    data = pd.concat([fires[["lat", "lon", "date", "label"]], background], ignore_index=True)

    X = build_features(data, layers)
    y = data["label"].values
    year = data["date"].dt.year.values

    train = year <= TRAIN_UNTIL_YEAR
    test = ~train
    model = HistGradientBoostingClassifier(
        max_iter=300,
        learning_rate=0.05,
        categorical_features=[list(X.columns).index("district")],
        random_state=42,
    )
    model.fit(X[train], y[train])
    proba = model.predict_proba(X[test])[:, 1]

    print(f"train rows: {train.sum()}, test rows: {test.sum()} (test years {TRAIN_UNTIL_YEAR + 1}-2025)")
    print(f"ROC-AUC: {roc_auc_score(y[test], proba):.3f}")
    print(f"PR-AUC:  {average_precision_score(y[test], proba):.3f}")

    importance = permutation_importance(
        model, X[test], y[test], n_repeats=5, random_state=42, scoring="roc_auc"
    )
    print("\nPermutation importance (drop in ROC-AUC on test):")
    for name, mean in sorted(zip(X.columns, importance.importances_mean), key=lambda t: -t[1]):
        print(f"  {name:>20}: {mean:.4f}")

    model.fit(X, y)

    years_observed = fires["date"].dt.year.nunique()
    fires_per_year = len(fires) / years_observed
    area_ha = unary_union(admin.to_crs(METRIC_CRS).geometry).area / 10_000
    print(f"\nfires per year: {fires_per_year:.1f}, Buryatia area: {area_ha:,.0f} ha")

    p_all = model.predict_proba(X)[:, 1]
    odds = p_all / (1 - p_all)
    lam_model = fires_per_year / area_ha * odds
    compare_with_formula(X[y == 0], lam_model[y == 0])

    lam_formula_all = formula_lambda(X["dist_road_m"].values, X["dist_settlement_m"].values)
    print(f"\nROC-AUC of the formula alone (test years): "
          f"{roc_auc_score(y[test], lam_formula_all[test]):.3f}")
    formula_scale = fires_per_year / area_ha / lam_formula_all[y == 0].mean()
    print(f"Formula scale factor k (observed / formula, region mean): {formula_scale:.2f}")
    lam_hybrid = formula_scale * lam_formula_all
    fitted = fit_formula_parameters(X, y, fires_per_year, area_ha)
    print(f"\nFitted formula parameters: LAMBDA0={fitted['LAMBDA0']:.6g}, "
          f"BETA={fitted['BETA']:.6g} 1/m, GAMMA={fitted['GAMMA']:.6g} 1/m")
    lam_fitted = formula_lambda_with(
        fitted, X["dist_road_m"].values, X["dist_settlement_m"].values
    )
    print(f"ROC-AUC of the fitted formula (all data): {roc_auc_score(y, lam_fitted):.3f}")
    background_mask = y == 0
    print(f"Region mean annual probability for 1 ha (background points)  "
          f"model: {(1 - np.exp(-lam_model[background_mask])).mean():.6f}  "
          f"formula x k: {(1 - np.exp(-lam_hybrid[background_mask])).mean():.6f}")

    joblib.dump(
        {
            "model": model,
            "columns": list(X.columns),
            "metric_crs": METRIC_CRS,
            "fires_per_year": fires_per_year,
            "area_ha": area_ha,
            "formula_scale": formula_scale,
            "formula_parameters": fitted,
        },
        OUT_DIR / "fire_point_model.joblib",
    )
    print(f"\nsaved: {OUT_DIR / 'fire_point_model.joblib'}")


if __name__ == "__main__":
    main()
