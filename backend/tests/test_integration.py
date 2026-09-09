from datetime import datetime

from pyproj import Transformer
from shapely.geometry import Point

from app.distance import distance_to_nearest_road
from app.fire_risk import base_probability, calculate_fire_probability
from app.gis import select_metric_crs, to_metric
from app.road_data import RoadDataProvider
from app.road_influence import road_influence


def test_integration_single_road(single_road_shp):
    r0 = 500.0
    alpha = 0.5

    # 1) load SHP
    gdf = RoadDataProvider(single_road_shp).load()

    # 2) transform CRS
    crs = select_metric_crs(gdf)
    roads_metric = to_metric(gdf, crs)

    # 3) distance to the nearest road (a point exactly on the road)
    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = transformer.transform(108.05, 51.80)
    point = Point(x, y)
    r = distance_to_nearest_road(point, roads_metric)

    # 4) road influence
    influence = road_influence(r, r0)

    # 5) fire probability
    p_base = base_probability(
        road_distance_m=120.0,
        settlement_distance_m=450.0,
        road_density=0.52,
        settlement_density=0.58,
        now_utc=datetime(2026, 6, 15, 12, 0, 0),
        lon=108.0,
    )
    p_fire = calculate_fire_probability(p_base, influence, alpha)

    assert r < 5.0
    assert 0.99 < influence <= 1.0
    assert 0.0 <= p_fire <= 1.0
    assert p_fire >= p_base
