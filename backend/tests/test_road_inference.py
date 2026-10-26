"""Road-model tiling tests; they do not download the pretrained weights."""
from __future__ import annotations

import numpy as np

import app.road_inference as road_inference


def test_tile_starts_cover_full_axis_with_overlap():
    starts = road_inference._tile_starts(1000)

    assert starts[0] == 0
    assert starts[-1] == 1000 - road_inference.TILE_SIZE
    assert all(
        current - previous <= road_inference.TILE_SIZE
        for previous, current in zip(starts, starts[1:])
    )


def test_short_axis_uses_single_tile():
    assert road_inference._tile_starts(200) == [0]


def test_small_image_is_edge_padded_to_tile_size():
    image = np.zeros((12, 20, 3), dtype=np.uint8)
    image[-1, -1] = (10, 20, 30)

    tile, valid_height, valid_width = road_inference._prepare_tile(image, 0, 0)

    assert tile.shape == (512, 512, 3)
    assert (valid_height, valid_width) == (12, 20)
    np.testing.assert_array_equal(tile[11, 19], (10, 20, 30))
    np.testing.assert_array_equal(tile[-1, -1], (10, 20, 30))


def test_overlapping_predictions_cover_image(monkeypatch):
    monkeypatch.setattr(
        road_inference,
        "_predict_tile",
        lambda *_args: np.full((512, 512), 0.75, dtype=np.float32),
    )
    image = np.zeros((700, 900, 3), dtype=np.uint8)

    probabilities = road_inference._predict_probabilities(image, None, 3, None)

    assert probabilities.shape == (700, 900)
    np.testing.assert_allclose(probabilities, 0.75)
