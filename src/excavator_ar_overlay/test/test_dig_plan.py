"""Differential tests: our conversion must agree with the HR35 canon.

The point of the overlay is to expose grid/physical misalignment, so the
conversion is checked against the authoritative implementation in
``excavator_task_config_gui.core.ai_grid_alignment`` rather than against a
restatement of the same formula. If HR35 is not on the path the canon-backed
checks skip loudly instead of silently passing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

from excavator_ar_overlay.dig_plan import (
    CELL_SIZE_M,
    CENTER_COL,
    DigPlanCells,
    cell_center_m,
    cell_corners,
    gui_row_from_ai_row,
    remaining_to_color,
)

_CANON_PATH = Path(
    "/home/kimm/hr35/src/excavator_task_config_gui/excavator_task_config_gui/"
    "core/ai_grid_alignment.py"
)


def _load_canon():
    if not _CANON_PATH.is_file():
        pytest.skip(f"HR35 canon not present at {_CANON_PATH}")
    spec = importlib.util.spec_from_file_location("hr35_ai_grid_alignment", _CANON_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SWING_ROWS = (-4, -2, 0, 3)


@pytest.mark.parametrize("swing_axis_row", SWING_ROWS)
@pytest.mark.parametrize("ai_row", (0, 1, 12, 20, 35, 37))
def test_gui_row_matches_canon(swing_axis_row, ai_row):
    canon = _load_canon()
    assert gui_row_from_ai_row(ai_row, swing_axis_row) == canon.reverse_ai_row_to_gui(
        ai_row, swing_axis_row
    )


def test_default_swing_row_matches_legacy_padding():
    canon = _load_canon()
    assert canon.legacy_swing_row_default(2) == -2


@pytest.mark.parametrize("swing_axis_row", SWING_ROWS)
def test_forward_metres_match_canon_formula(swing_axis_row):
    """canon: forward_m = (gui_row - swing_axis_row) * cell_size."""
    for ai_row in range(0, 38):
        gui_row = gui_row_from_ai_row(ai_row, swing_axis_row)
        expected = (gui_row - swing_axis_row) * CELL_SIZE_M
        forward, _ = cell_center_m(ai_row, CENTER_COL)
        assert forward == pytest.approx(expected)


@pytest.mark.parametrize("ai_col", (0, 20, 33, 40, 66))
def test_lateral_metres_match_canon_formula(ai_col):
    _, lateral = cell_center_m(0, ai_col)
    assert lateral == pytest.approx((ai_col - 33) * CELL_SIZE_M)


def test_swing_axis_row_zero_forward_and_centre_column_zero_lateral():
    forward, lateral = cell_center_m(0, CENTER_COL)
    assert forward == pytest.approx(0.0)
    assert lateral == pytest.approx(0.0)


def test_lateral_sign_is_positive_left_of_centre():
    """Canon derives swing_true_deg = atan2(lateral, forward); col>33 -> +."""
    _, right_of_centre = cell_center_m(10, CENTER_COL + 5)
    _, left_of_centre = cell_center_m(10, CENTER_COL - 5)
    assert right_of_centre > 0.0
    assert left_of_centre < 0.0


def test_align_round_trip_against_canon():
    """A value written at GUI[r, c] must read back at AI[r - swing, c]."""
    canon = _load_canon()
    swing_axis_row = -2
    gui = np.zeros((34, 67), dtype=np.float64)
    gui[7, 40] = 1.0
    gui[20, 12] = 2.0

    ai = canon.align_gui_to_ai(gui, swing_axis_row)
    for gui_row, gui_col, value in ((7, 40, 1.0), (20, 12, 2.0)):
        ai_row = gui_row - swing_axis_row
        assert ai[ai_row, gui_col] == value
        assert gui_row_from_ai_row(ai_row, swing_axis_row) == gui_row


def test_extent_gate_matches_canon_for_default_grid():
    canon = _load_canon()
    assert canon.extent_ok(34, -2) is True
    assert canon.extent_ok(34, -1) is False


def test_cell_corners_form_one_cell_square_at_the_given_height():
    corners = cell_corners(np.array([10]), np.array([CENTER_COL]), np.array([1.25]))
    assert corners.shape == (1, 4, 3)

    forward = corners[0, :, 0]
    lateral = corners[0, :, 1]
    assert forward.max() - forward.min() == pytest.approx(CELL_SIZE_M)
    assert lateral.max() - lateral.min() == pytest.approx(CELL_SIZE_M)
    assert np.allclose(corners[0, :, 2], 1.25)

    centre_forward, centre_lateral = cell_center_m(10, CENTER_COL)
    assert forward.mean() == pytest.approx(centre_forward)
    assert lateral.mean() == pytest.approx(centre_lateral)


def test_cell_corners_are_counter_clockwise_from_above():
    corners = cell_corners(np.array([5]), np.array([30]), np.array([0.0]))[0]
    x, y = corners[:, 0], corners[:, 1]
    shoelace = np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))
    assert shoelace > 0.0


def test_cell_corners_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        cell_corners(np.array([1, 2]), np.array([1]), np.array([0.0]))


def test_dig_plan_cells_rejects_mismatched_selection():
    with pytest.raises(ValueError):
        DigPlanCells.from_sequences([1, 2, 3], [1, 2], 1, 1)


def test_dig_plan_cells_flags_out_of_range():
    cells = DigPlanCells.from_sequences([0, 37, 38], [0, 66, 67], 0, 0)
    assert list(cells.in_range_mask()) == [True, True, False]


def test_remaining_colour_encodes_sign():
    dig_more = remaining_to_color(2.0)
    over_dug = remaining_to_color(-2.0)
    on_target = remaining_to_color(0.0)
    assert dig_more != over_dug != on_target
    # "dig more" leans warm (red channel dominant), "over-dug" leans cool (blue).
    assert dig_more[2] > dig_more[0]
    assert over_dug[0] > over_dug[2]
