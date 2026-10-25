"""Tile math tests (no network access)."""
from __future__ import annotations

from app.satellite import tile_url, tile_xy


def test_tile_xy_for_zaigraevsky_district():
    x, y = tile_xy(51.85, 108.27, 15)
    assert x == 26238
    assert y == 10845


def test_tile_xy_is_clamped_at_edges():
    assert tile_xy(85.05112878, 180.0, 2)[0] == 3
    assert tile_xy(-85.05112878, -180.0, 2)[0] == 0


def test_tile_url_contains_esri_path():
    url = tile_url(26239, 10844, 15)
    assert "/World_Imagery/MapServer/tile/15/10844/26239" in url
