"""Layer integration checks with hand-computed pixels, heights and colours."""

from dataclasses import replace

import numpy as np
import pytest

from excavator_ar_overlay import layers, rendering
from excavator_ar_overlay.ai_action import DigAction
from excavator_ar_overlay.camera_model import PinholeModel
from excavator_ar_overlay.grid_elevation import ElevationGrid
from excavator_ar_overlay.task_info import TerrainState


def camera():
    return PinholeModel.from_camera_info_values(
        [200., 0., 100., 0., 200., 100., 0., 0., 1.], 200, 200
    )


def action():
    return DigAction(
        phase="dig", rows=np.array([20, 20, 20, 0]),
        cols=np.array([31, 33, 35, 33]), start_row=20, start_col=33,
        p_meter=3., d_meter=.2, d_units=2., length_meter=.45,
        swing_angle_excavator_deg=0., mean_remaining_delta_units=1.5,
    )


def terrain():
    current = np.zeros((38, 67))
    current[20, 31] = .375
    current[20, 33] = -.375
    mask = np.ones((38, 67), dtype=bool)
    mask[20, 35] = False
    return TerrainState(current, np.zeros_like(current), mask, .125)


def dig_matrix():
    matrix = np.eye(4)
    matrix[:3, 3] = [-3., 0., 5.]
    return matrix


def draw_dig(frame, selected=None, ground=None, **options):
    selected = action() if selected is None else selected
    settings = dict(min_depth_m=.3, fill_alpha=1., outline_thickness=0,
                    start_marker_radius_px=0, font_scale=.5)
    settings.update(options)
    return layers.draw_dig_plan(
        frame, camera(), selected, np.zeros(selected.rows.size),
        "height input", dig_matrix(), ground, **settings,
    )


@pytest.mark.parametrize("radius", [0, 2])
def test_cloud_uses_lidar_range_not_transformed_depth(radius):
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    points = np.array([[0., 0., 2.], [.3, 0., 4.], [0., 0., -5.], [20., 0., 1.]])
    matrix = np.eye(4)
    matrix[2, 3] = 2.
    count, _ = layers.draw_cloud(
        frame, camera(), points, matrix, "lidar", min_depth_m=.3,
        near_m=1., far_m=10., point_radius_px=radius,
    )
    expected = np.zeros_like(frame)
    # z becomes 4 and 6; u = 100 and 200*.3/6+100 = 110.
    colors = rendering.depth_colors(np.array([2., np.sqrt(16.09)]), 1., 10.)
    rendering.draw_points(expected, np.array([[100., 100.], [110., 100.]]), colors, radius)
    assert count == 2
    np.testing.assert_array_equal(frame, expected)


@pytest.mark.parametrize("points", [np.empty((0, 3)), np.array([[0., 0., -.5]]),
                                    np.array([[0., 0., .2]]), np.array([[100., 0., 1.]])])
def test_cloud_empty_or_culled_leaves_frame_untouched(points):
    frame = np.full((200, 200, 3), 31, dtype=np.uint8)
    count, _ = layers.draw_cloud(
        frame, camera(), points, np.eye(4), "lidar", min_depth_m=.3,
        near_m=1., far_m=10., point_radius_px=0,
    )
    assert count == 0
    assert np.all(frame == 31)


@pytest.mark.parametrize("alpha,outline", [(0., 1), (.35, 0), (1., 2)])
@pytest.mark.parametrize("per_cell", [False, True])
def test_dig_projection_fill_outline_and_visible_cell_colours(alpha, outline, per_cell):
    frame = np.full((200, 200, 3), 40, dtype=np.uint8)
    draw_dig(frame, ground=terrain() if per_cell else None,
             fill_alpha=alpha, outline_thickness=outline)
    expected = np.full_like(frame, 40)
    # 0.15 m squares at z=5 subtend 6 px; the fourth cell is entirely off-screen.
    polygons = [np.array([[97, y-3], [103, y-3], [103, y+3], [97, y+3]],
                         dtype=np.int32) for y in [88, 100, 112]]
    colors = [(0, 255, 255), (255, 90, 0), (150, 150, 150)] if per_cell else [(0, 197, 127)] * 3
    rendering.draw_filled_polygons(expected, polygons, colors, alpha, outline)
    np.testing.assert_array_equal(frame, expected)


def test_dig_start_marker_is_at_the_selected_cell_centre():
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    draw_dig(frame, fill_alpha=0., start_marker_radius_px=5)
    expected = np.zeros_like(frame)
    rendering.draw_start_marker(expected, (100, 100), 5, "start", .5)
    np.testing.assert_array_equal(frame, expected)


@pytest.mark.parametrize("row,col", [(0, 33), (99, 99)])
def test_hidden_or_absent_start_cell_does_not_draw_marker(row, col):
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    draw_dig(frame, replace(action(), start_row=row, start_col=col),
             fill_alpha=0., start_marker_radius_px=5)
    assert not frame.any()


def test_first_matching_start_cell_controls_marker_visibility():
    selected = replace(action(), rows=np.array([20, 20]), cols=np.array([33, 33]))
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    uv = np.array([[[10., 10.]] * 4, [[100., 100.]] * 4])
    layers.draw_start_marker(frame, selected, uv, np.array([False, True]), 5, .5)
    assert not frame.any()


def test_partial_cell_is_not_clipped_and_drawn():
    # u=1 at the centre but the near corners have u=-2, so reject the whole cell.
    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    selected = replace(action(), rows=np.array([20]), cols=np.array([33]))
    matrix = dig_matrix()
    matrix[0, 3] = -5.475
    layers.draw_dig_plan(
        frame, camera(), selected, np.zeros(1), "height input", matrix, None,
        min_depth_m=.3, fill_alpha=1., outline_thickness=1,
        start_marker_radius_px=5, font_scale=.5,
    )
    assert not frame.any()


@pytest.mark.parametrize("ground", [None, "outside"])
def test_cell_colour_falls_back_to_action_mean(ground):
    ground = None if ground is None else replace(terrain(), mask=np.zeros((38, 67), dtype=bool))
    colors, _ = layers.cell_colors(action(), np.array([0, 1, 2]), ground)
    assert colors == [(0, 197, 127)] * 3


def test_cell_colour_uses_shown_indices_and_preserves_invalid_grey():
    colors, _ = layers.cell_colors(action(), np.array([2, 0, 1]), terrain())
    assert colors == [(150, 150, 150), (0, 255, 255), (255, 90, 0)]


def height_action():
    return replace(action(), rows=np.array([10, 20, 30]), cols=np.array([33, 33, 33]))


def elevation(frame_id="anchor"):
    values = np.arange(12, dtype=float).reshape(6, 2)
    values[3, 1] = np.nan
    return ElevationGrid(values, 1., 6., 2., (3., 0.), frame_id)


def test_height_samples_grid_and_keeps_nan_fallback():
    heights, _ = layers.cell_heights(height_action(), "anchor", elevation(), -.5)
    np.testing.assert_array_equal(heights, [9., -.5, 3.])


def test_height_transforms_xy_but_does_not_transform_sampled_z():
    matrix = np.eye(4)
    matrix[:3, 3] = [1., 0., 40.]
    heights, _ = layers.cell_heights(height_action(), "anchor", elevation("map"), -.5, matrix)
    np.testing.assert_array_equal(heights, [-.5, 5., 1.])


@pytest.mark.parametrize("grid", [None, elevation("map")])
def test_height_fallback_without_grid_or_required_transform(grid):
    heights, _ = layers.cell_heights(height_action(), "anchor", grid, -.5)
    np.testing.assert_array_equal(heights, [-.5, -.5, -.5])


def test_height_outside_grid_keeps_fallback():
    selected = replace(height_action(), rows=np.array([100, 20, 30]))
    heights, _ = layers.cell_heights(selected, "anchor", elevation(), -.5)
    np.testing.assert_array_equal(heights, [-.5, -.5, 3.])
