from pyproj import Transformer
from shapely.geometry import Point

from app.distance import distance_to_nearest_road
from app.gis import select_metric_crs, to_metric
from app.road_data import RoadDataProvider


def _point_metric(lon, lat, crs):
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    return Point(x, y)


def test_point_on_road(single_road_shp):
    gdf = RoadDataProvider(single_road_shp).load()
    crs = select_metric_crs(gdf)
    roads_metric = to_metric(gdf, crs)
    d = distance_to_nearest_road(_point_metric(108.05, 51.80, crs), roads_metric)
    assert d < 5.0


def test_point_far_from_road(single_road_shp):
    gdf = RoadDataProvider(single_road_shp).load()
    crs = select_metric_crs(gdf)
    roads_metric = to_metric(gdf, crs)
    d = distance_to_nearest_road(_point_metric(108.05, 51.90, crs), roads_metric)
    # ~0.1 degree of latitude ~ 11.1 km
    assert 10000 < d < 12000


def test_nearest_of_multiple_roads(roads_shp):
    gdf = RoadDataProvider(roads_shp).load()
    crs = select_metric_crs(gdf)
    roads_metric = to_metric(gdf, crs)
    # A point ~0.02 degree north of the first road (lat 51.80).
    d = distance_to_nearest_road(_point_metric(108.05, 51.82, crs), roads_metric)
    assert 2000 < d < 2500


def test_strtree_matches_scan(roads_shp):
    from shapely.strtree import STRtree

    gdf = RoadDataProvider(roads_shp).load()
    crs = select_metric_crs(gdf)
    roads_metric = to_metric(gdf, crs)
    tree = STRtree(list(roads_metric.geometry))
    p = _point_metric(108.05, 51.82, crs)
    d_scan = distance_to_nearest_road(p, roads_metric)
    d_tree = distance_to_nearest_road(p, roads_metric, tree)
    assert abs(d_scan - d_tree) < 1e-3
