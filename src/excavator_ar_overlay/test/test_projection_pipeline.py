"""End-to-end geometry check for the dig-cell projection path.

Runs the real chain -- AI cell -> swing-axis corners -> camera frame -> pixels --
against hand-computed expectations, with no ROS graph and no excavator_msgs.
That matters here because the HR35 `excavator_msgs` install on this machine is
stale and does not contain AiActionStatus, so the node's guarded import
disables the layer at runtime; the geometry still has to be provably right.

Camera pose used throughout: co-located with the anchor frame and looking
straight down its +x axis, i.e. the nominal
``rpy = (-pi/2, 0, -pi/2)`` optical mapping. Under that mapping a point
``(forward, lateral, up)`` in the anchor frame becomes
``(-lateral, -up, forward)`` in the optical frame.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from excavator_ar_overlay.ai_action import ActionRetainer, DigAction
from excavator_ar_overlay.camera_model import PinholeModel
from excavator_ar_overlay.dig_plan import CELL_SIZE_M, CENTER_COL, cell_corners
from excavator_ar_overlay.geometry import (
    apply_transform,
    quaternion_to_matrix,
    rpy_to_quaternion,
)

FX = FY = 845.4851684570312
CX, CY = 626.77001953125, 395.5094909667969
WIDTH, HEIGHT = 1280, 800


def camera() -> PinholeModel:
    return PinholeModel.from_camera_info_values(
        [FX, 0.0, CX, 0.0, FY, CY, 0.0, 0.0, 1.0], WIDTH, HEIGHT
    )


def anchor_to_optical() -> np.ndarray:
    """T_optical<-anchor for a camera co-located with the anchor, facing +x.

    tf2 returns exactly this for lookup_transform(optical, anchor) when the
    broadcast transform is parent=anchor, child=optical with the nominal rpy.
    """
    rotation = quaternion_to_matrix(*rpy_to_quaternion(-math.pi / 2, 0.0, -math.pi / 2))
    matrix = np.eye(4)
    matrix[:3, :3] = rotation.T  # invert the parent->child rotation
    return matrix


def project_cells(rows, cols, heights):
    corners = cell_corners(np.asarray(rows), np.asarray(cols), np.asarray(heights))
    flat = apply_transform(anchor_to_optical(), corners.reshape(-1, 3))
    uv, keep = camera().project(flat, 0.3)
    full = np.full((flat.shape[0], 2), np.nan)
    full[keep] = uv
    return full.reshape(corners.shape[0], 4, 2), keep.reshape(corners.shape[0], 4)


def test_optical_mapping_is_forward_positive_z():
    point = np.array([[3.0, 0.0, 0.0]])  # 3 m straight ahead of the anchor
    assert np.allclose(apply_transform(anchor_to_optical(), point), [[0.0, 0.0, 3.0]])


def test_centre_column_cell_lands_on_the_principal_point():
    uv, ok = project_cells([20], [CENTER_COL], [0.0])
    assert ok.all()
    centre = uv[0].mean(axis=0)
    assert centre[0] == pytest.approx(CX, abs=1e-6)
    assert centre[1] == pytest.approx(CY, abs=1e-6)


def test_cell_left_of_the_machine_appears_left_of_centre():
    """col > 33 is +lateral, which is the machine's left, so u must decrease."""
    uv_left, _ = project_cells([20], [CENTER_COL + 10], [0.0])
    uv_right, _ = project_cells([20], [CENTER_COL - 10], [0.0])
    assert uv_left[0].mean(axis=0)[0] < CX
    assert uv_right[0].mean(axis=0)[0] > CX


def test_cell_below_the_camera_appears_below_centre():
    uv_low, _ = project_cells([20], [CENTER_COL], [-1.0])
    assert uv_low[0].mean(axis=0)[1] > CY


def test_projected_size_shrinks_with_distance():
    near, _ = project_cells([10], [CENTER_COL], [0.0])
    far, _ = project_cells([30], [CENTER_COL], [0.0])

    def span(poly):
        return poly[:, 0].max() - poly[:, 0].min()

    assert span(near[0]) > span(far[0])


def test_projected_width_matches_the_pinhole_prediction():
    """The widest edge is the NEAR one, not the cell centre.

    A cell spans depth +/- half a cell, and perspective makes the near edge
    subtend a larger angle. Predicting from the centre depth under-estimates
    the span by ~2.5% at 3 m, which is exactly the kind of quiet offset this
    overlay exists to expose.
    """
    ai_row = 20
    uv, _ = project_cells([ai_row], [CENTER_COL], [0.0])
    near_depth = ai_row * CELL_SIZE_M - CELL_SIZE_M / 2.0
    expected = FX * CELL_SIZE_M / near_depth
    width = uv[0][:, 0].max() - uv[0][:, 0].min()
    # rel=1e-5, not tighter: project() returns float32 pixels, which is worth
    # ~1e-6 relative here. A genuine half-cell depth error would be ~2.5%,
    # three orders of magnitude larger, so this still catches what matters.
    assert width == pytest.approx(expected, rel=1e-5)


def test_cells_behind_the_camera_are_culled_not_mirrored():
    """AI row 0 is the swing axis itself: the cell straddles the camera plane."""
    _, ok = project_cells([0], [CENTER_COL], [0.0])
    assert not ok.all()


def test_full_selection_projects_as_a_contiguous_band():
    """Terrain below the camera: further cells must sit higher in the image.

    Heights matter twice over. At the camera's own height every cell lands
    exactly on the horizon (v == cy) regardless of distance, proving nothing.
    Drop them too far instead (-2 m at 2.2-3.6 m range) and the whole band
    falls below the sensor, so the -0.5 m used here is the window where the
    monotonic ordering is actually observable.
    """
    rows = list(range(15, 25))
    cols = [CENTER_COL] * len(rows)
    uv, ok = project_cells(rows, cols, [-0.5] * len(rows))
    assert ok.all()
    centres_v = np.array([uv[i].mean(axis=0)[1] for i in range(len(rows))])
    assert np.all(np.diff(centres_v) < 0)


def test_cells_at_camera_height_land_on_the_horizon():
    uv, ok = project_cells([15, 25, 35], [CENTER_COL] * 3, [0.0] * 3)
    assert ok.all()
    for index in range(3):
        assert uv[index].mean(axis=0)[1] == pytest.approx(CY, abs=1e-6)


def test_retained_action_drives_the_same_pipeline():
    """The retention policy and the geometry agree on which cells to draw."""
    msg = SimpleNamespace(
        phase="dig",
        selected_rows=[18, 19, 20],
        selected_cols=[CENTER_COL, CENTER_COL, CENTER_COL + 1],
        start_row=20,
        start_col=CENTER_COL + 1,
        p_meter=3.0,
        d_meter=0.2,
        d_units=2.0,
        length_meter=0.45,
        swing_angle_excavator_deg=0.0,
        mean_remaining_delta_units=1.0,
    )
    retainer = ActionRetainer()
    action = retainer.update(DigAction.from_message(msg))
    assert action is not None and action.has_cells()

    uv, ok = project_cells(action.rows, action.cols, np.zeros(action.rows.size))
    assert ok.all()

    match = np.flatnonzero(
        (action.rows == action.start_row) & (action.cols == action.start_col)
    )
    assert match.size == 1
    assert np.isfinite(uv[match[0]]).all()
