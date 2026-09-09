import geopandas as gpd
import pytest
from shapely.geometry import Point

from app.gis import ensure_known_crs, select_metric_crs, to_metric, utm_zone_epsg
from app.road_data import RoadDataProvider


def test_utm_zone_north():
    assert utm_zone_epsg(108.0, 51.8) == 32649


def test_utm_zone_south():
    assert utm_zone_epsg(108.0, -51.8) == 32749


def test_select_metric_crs_is_projected(roads_shp):
    gdf = RoadDataProvider(roads_shp).load()
    crs = select_metric_crs(gdf)
    assert crs.is_projected


def test_to_metric_reprojects(roads_shp):
    gdf = RoadDataProvider(roads_shp).load()
    crs = select_metric_crs(gdf)
    metric = to_metric(gdf, crs)
    assert metric.crs == crs
    assert len(metric) == 2


def test_configured_crs_override(roads_shp):
    gdf = RoadDataProvider(roads_shp).load()
    crs = select_metric_crs(gdf, configured_crs="EPSG:32648")
    assert crs.to_epsg() == 32648


def test_missing_crs_raises():
    gdf = gpd.GeoDataFrame(geometry=[Point(0, 0)], crs=None)
    with pytest.raises(ValueError):
        ensure_known_crs(gdf)
