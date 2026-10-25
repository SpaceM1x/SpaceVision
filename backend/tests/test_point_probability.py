import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from app.point_probability import (
    DistanceDataError,
    calculate_point_fire_probability,
)
from app.vector_data import build_vector_cache


def _write_layer(tmp_path, name, geometries):
    path = tmp_path / name
    gdf = gpd.GeoDataFrame(
        {"name": [f"feature_{i}" for i in range(len(geometries))]},
        geometry=geometries,
        crs="EPSG:4326",
    )
    gdf.to_file(path)
    return path


def test_point_probability_uses_local_layers(tmp_path):
    roads = build_vector_cache(
        _write_layer(
            tmp_path,
            "roads.shp",
            [LineString([(108.00, 51.80), (108.10, 51.80)])],
        ),
        label="road",
    )
    settlements = build_vector_cache(
        _write_layer(
            tmp_path,
            "settlements.shp",
            [Point(108.05, 51.80), Point(108.20, 51.90)],
        ),
        label="settlement",
    )

    point = calculate_point_fire_probability(
        51.80,
        108.00,
        area_ha=1.0,
        roads=roads,
        settlements=settlements,
    )

    assert point.road.source == "shp"
    assert point.settlement.source == "shp"
    assert point.road.distance_m == pytest.approx(0.0, abs=2.0)
    assert point.settlement.distance_m > 1_000.0
    assert point.result.probability > 0.0


def test_point_probability_uses_osm_fallback():
    def osm_lookup(lat, lon):
        return {"road_distance_m": 100.0, "settlement_distance_m": 500.0}

    point = calculate_point_fire_probability(
        51.80,
        108.00,
        area_ha=1.0,
        osm_lookup=osm_lookup,
    )

    assert point.road.source == "osm"
    assert point.settlement.source == "osm"
    assert point.road.distance_m == 100.0
    assert point.settlement.distance_m == 500.0


def test_map_distances_take_priority():
    point = calculate_point_fire_probability(
        51.80,
        108.00,
        road_distance_m=25.0,
        settlement_distance_m=75.0,
        osm_lookup=lambda lat, lon: {
            "road_distance_m": 100.0,
            "settlement_distance_m": 500.0,
        },
    )

    assert point.road.source == "map"
    assert point.settlement.source == "map"
    assert point.road.distance_m == 25.0
    assert point.settlement.distance_m == 75.0


def test_point_probability_reports_missing_distances():
    with pytest.raises(DistanceDataError) as error:
        calculate_point_fire_probability(
            51.80,
            108.00,
            osm_lookup=lambda lat, lon: {
                "road_distance_m": 100.0,
                "settlement_distance_m": None,
            },
        )

    assert "населённый пункт" in str(error.value)
