import geopandas as gpd
import pytest
from shapely.geometry import LineString

from app.road_data import RoadDataError, RoadDataProvider


def test_load_shapefile(roads_shp):
    gdf = RoadDataProvider(roads_shp).load()
    assert len(gdf) == 2
    assert gdf.crs is not None


def test_load_multiple_roads(roads_shp):
    gdf = RoadDataProvider(roads_shp).load()
    assert len(gdf) == 2


def test_missing_shapefile(tmp_path):
    with pytest.raises(RoadDataError):
        RoadDataProvider(tmp_path / "missing.shp").load()


def test_missing_prj(make_roads_shp):
    path = make_roads_shp("noprj.shp", [LineString([(108.0, 51.8), (108.1, 51.8)])])
    path.with_suffix(".prj").unlink()
    with pytest.raises(RoadDataError):
        RoadDataProvider(path).load()


def test_empty_shapefile(tmp_path):
    path = tmp_path / "empty.shp"
    gdf = gpd.GeoDataFrame({"name": []}, geometry=[], crs="EPSG:4326")
    gdf.to_file(path)
    with pytest.raises(RoadDataError):
        RoadDataProvider(path).load()
