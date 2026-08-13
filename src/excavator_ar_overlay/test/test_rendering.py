"""Tests for the drawing primitives.

Focus on the properties the operator depends on rather than exact pixels:
the colour ramp must be monotonic and ordered, overlapping cell fills must not
compound into an opaque blob, and nothing may write outside the canvas.
"""

from __future__ import annotations

import numpy as np
import pytest

from excavator_ar_overlay import rendering

W, H = 320, 200


def canvas(value=120):
    return np.full((H, W, 3), value, dtype=np.uint8)


def test_depth_colors_are_ordered_near_to_far():
    cols = rendering.depth_colors(np.array([1.0, 8.0, 15.0]), 1.0, 15.0)
    assert cols.shape == (3, 3)
    # TURBO runs blue -> red, so blue falls and red rises with distance.
    assert cols[0][0] > cols[2][0]
    assert cols[2][2] > cols[0][2]


def test_depth_colors_clamp_outside_the_ramp():
    inside = rendering.depth_colors(np.array([1.0, 15.0]), 1.0, 15.0)
    outside = rendering.depth_colors(np.array([-50.0, 900.0]), 1.0, 15.0)
    assert np.array_equal(inside, outside)


def test_depth_colors_empty_input():
    assert rendering.depth_colors(np.empty(0), 1.0, 15.0).shape == (0, 3)


def test_depth_colors_rejects_inverted_range():
    with pytest.raises(ValueError):
        rendering.depth_colors(np.array([1.0]), 15.0, 1.0)


def test_draw_points_writes_single_pixels_when_radius_is_zero():
    img = canvas()
    uv = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)
    cols = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
    rendering.draw_points(img, uv, cols, 0)
    assert tuple(img[20, 10]) == (255, 0, 0)
    assert tuple(img[40, 30]) == (0, 255, 0)
    assert int((img != 120).any(axis=2).sum()) == 2


def test_draw_points_clamps_out_of_bounds_instead_of_raising():
    img = canvas()
    uv = np.array([[-5.0, -5.0], [W + 50.0, H + 50.0]], dtype=np.float32)
    cols = np.array([[255, 255, 255], [255, 255, 255]], dtype=np.uint8)
    rendering.draw_points(img, uv, cols, 0)
    assert img.shape == (H, W, 3)


def test_draw_points_empty_is_a_noop():
    img = canvas()
    rendering.draw_points(img, np.empty((0, 2)), np.empty((0, 3), np.uint8), 0)
    assert (img == 120).all()


def square(x0, y0, size):
    return np.array(
        [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size]],
        dtype=np.int32,
    )


def test_overlapping_fills_do_not_compound_to_opaque():
    """Two cells over the same ground must stay as see-through as one."""
    single = canvas()
    rendering.draw_filled_polygons(single, [square(50, 50, 40)], [(255, 0, 0)], 0.35, 0)
    both = canvas()
    rendering.draw_filled_polygons(
        both,
        [square(50, 50, 40), square(50, 50, 40)],
        [(255, 0, 0), (255, 0, 0)],
        0.35,
        0,
    )
    assert int(single[70, 70][0]) == pytest.approx(int(both[70, 70][0]), abs=2)


def test_fill_alpha_zero_leaves_the_frame_untouched():
    img = canvas()
    rendering.draw_filled_polygons(img, [square(20, 20, 40)], [(0, 0, 255)], 0.0, 0)
    assert (img == 120).all()


def test_outline_is_drawn_even_with_no_fill():
    img = canvas()
    rendering.draw_filled_polygons(img, [square(20, 20, 40)], [(0, 0, 255)], 0.0, 2)
    assert (img != 120).any()


def test_empty_polygon_list_is_a_noop():
    img = canvas()
    rendering.draw_filled_polygons(img, [], [], 0.35, 1)
    assert (img == 120).all()


def test_hud_draws_inside_the_canvas():
    img = canvas()
    rendering.draw_hud(img, ["phase: dig", "cells: 12"], 0.5)
    assert img.shape == (H, W, 3)
    assert (img[:60, :200] != 120).any()


def test_hud_with_no_lines_is_a_noop():
    img = canvas()
    rendering.draw_hud(img, [], 0.5)
    assert (img == 120).all()


def test_legend_is_baked_into_the_bottom_right():
    img = canvas()
    rendering.draw_depth_legend(img, 1.0, 15.0, 0.5)
    assert (img[H // 2 :, W // 2 :] != 120).any()
    assert (img[: H // 3, : W // 3] == 120).all()


def test_legend_survives_a_canvas_too_small_to_hold_it():
    tiny = np.full((24, 40, 3), 120, dtype=np.uint8)
    rendering.draw_depth_legend(tiny, 1.0, 15.0, 0.5)
    assert tiny.shape == (24, 40, 3)


def test_start_marker_and_banner_stay_in_bounds():
    img = canvas()
    rendering.draw_start_marker(img, (W - 3, H - 3), 7, "start", 0.5)
    rendering.draw_banner(img, "no camera image", 0.8)
    assert img.shape == (H, W, 3)


def test_start_marker_with_zero_radius_is_a_noop():
    img = canvas()
    rendering.draw_start_marker(img, (100, 100), 0, "start", 0.5)
    assert (img == 120).all()
