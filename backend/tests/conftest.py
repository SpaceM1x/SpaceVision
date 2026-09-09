import geopandas as gpd
import pytest
from shapely.geometry import LineString


@pytest.fixture
def make_roads_shp(tmp_path):
    """Return a factory that writes a roads shapefile into the test tmp dir."""

    def _make(name, geometries, crs="EPSG:4326"):
        path = tmp_path / name
        gdf = gpd.GeoDataFrame(
            {"name": [f"road_{i}" for i in range(len(geometries))]},
            geometry=geometries,
            crs=crs,
        )
        gdf.to_file(path)
        return path

    return _make


@pytest.fixture
def roads_shp(make_roads_shp):
    return make_roads_shp(
        "roads.shp",
        [
            LineString([(108.00, 51.80), (108.10, 51.80)]),
            LineString([(108.20, 51.90), (108.30, 51.90)]),
        ],
    )


@pytest.fixture
def single_road_shp(make_roads_shp):
    return make_roads_shp(
        "single.shp",
        [LineString([(108.00, 51.80), (108.10, 51.80)])],
    )
