"""Tests for per-cell terrain state parsing.

The indexing convention is the whole point: TaskInfo flattens row-major over the
AI grid, so an off-by-one or a transpose reads a different cell entirely and the
overlay would colour the wrong ground while looking perfectly plausible.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from excavator_ar_overlay.task_info import TerrainState

ROWS, COLS = 38, 67
RES = 0.1


def make_msg(current=None, target=None, mask=None, rows=ROWS, cols=COLS, res=RES):
    n = rows * cols
    if current is None:
        current = np.zeros(n)
    if target is None:
        target = np.zeros(n)
    if mask is None:
        mask = np.ones(n, dtype=np.uint8)
    return SimpleNamespace(
        grid_length=rows,
        grid_width=cols,
        height_resolution=res,
        cell_heights=list(np.asarray(current, dtype=np.float32).ravel()),
        target_heights=list(np.asarray(target, dtype=np.float32).ravel()),
        target_mask=list(np.asarray(mask, dtype=np.uint8).ravel()),
    )


def ramp():
    """Unique value per cell so a transpose or off-by-one cannot pass."""
    r = np.arange(ROWS).reshape(-1, 1)
    c = np.arange(COLS).reshape(1, -1)
    return (r * 1000.0 + c).astype(np.float64)


def test_row_major_indexing_matches_the_message_layout():
    grid = ramp()
    state = TerrainState.from_message(make_msg(current=grid))
    assert state is not None
    assert state.shape == (ROWS, COLS)
    for r, c in ((0, 0), (0, 66), (37, 0), (12, 45)):
        got, valid = state.heights_m(np.array([r]), np.array([c]))
        assert valid.all()
        assert got[0] == pytest.approx(r * 1000.0 + c)


def test_a_transpose_would_be_caught():
    state = TerrainState.from_message(make_msg(current=ramp()))
    assert state is not None
    got, _ = state.heights_m(np.array([3]), np.array([7]))
    assert got[0] == pytest.approx(3007.0)
    assert got[0] != pytest.approx(7003.0)


def test_remaining_units_sign_and_scale():
    """positive = still to dig, negative = over-dug, unit = height_resolution."""
    current = np.zeros((ROWS, COLS))
    target = np.zeros((ROWS, COLS))
    current[5, 10] = 0.30   # 0.30 m above target -> +3.0 units
    current[6, 11] = -0.20  # 0.20 m below target -> -2.0 units
    state = TerrainState.from_message(make_msg(current=current, target=target))
    assert state is not None

    vals, valid = state.remaining_units(np.array([5, 6, 7]), np.array([10, 11, 12]))
    assert valid.all()
    assert vals[0] == pytest.approx(3.0)
    assert vals[1] == pytest.approx(-2.0)
    assert vals[2] == pytest.approx(0.0)


def test_remaining_uses_target_not_absolute_height():
    current = np.full((ROWS, COLS), 5.0)
    target = np.full((ROWS, COLS), 4.5)
    state = TerrainState.from_message(make_msg(current=current, target=target))
    assert state is not None
    vals, valid = state.remaining_units(np.array([10]), np.array([33]))
    assert valid.all()
    assert vals[0] == pytest.approx(5.0)


def test_cells_outside_the_work_mask_are_invalid():
    mask = np.ones((ROWS, COLS), dtype=np.uint8)
    mask[9, 20] = 0
    state = TerrainState.from_message(make_msg(mask=mask))
    assert state is not None
    _, valid = state.remaining_units(np.array([9, 9]), np.array([20, 21]))
    assert list(valid) == [False, True]


def test_out_of_range_cells_are_invalid_not_wrapped():
    state = TerrainState.from_message(make_msg(current=ramp()))
    assert state is not None
    vals, valid = state.remaining_units(
        np.array([-1, ROWS, 0]), np.array([0, 0, COLS])
    )
    assert list(valid) == [False, False, False]
    assert np.isnan(vals[:2]).all()


def test_nan_heights_are_invalid():
    current = np.zeros((ROWS, COLS))
    current[2, 3] = np.nan
    state = TerrainState.from_message(make_msg(current=current))
    assert state is not None
    _, valid = state.remaining_units(np.array([2]), np.array([3]))
    assert not valid.any()


def test_wrong_payload_size_is_rejected():
    msg = make_msg()
    msg.cell_heights = msg.cell_heights[:-5]
    assert TerrainState.from_message(msg) is None


def test_degenerate_dimensions_are_rejected():
    assert TerrainState.from_message(make_msg(rows=0, cols=0)) is None


def test_missing_mask_defaults_to_everything_valid():
    msg = make_msg()
    msg.target_mask = []
    state = TerrainState.from_message(msg)
    assert state is not None
    assert state.mask.all()


def test_zero_height_resolution_falls_back_instead_of_dividing_by_zero():
    current = np.zeros((ROWS, COLS))
    current[1, 1] = 0.2
    state = TerrainState.from_message(make_msg(current=current, res=0.0))
    assert state is not None
    assert state.height_resolution_m == pytest.approx(0.1)
    vals, valid = state.remaining_units(np.array([1]), np.array([1]))
    assert valid.all() and vals[0] == pytest.approx(2.0)


def test_shape_mismatch_between_rows_and_cols_raises():
    state = TerrainState.from_message(make_msg())
    assert state is not None
    with pytest.raises(ValueError):
        state.remaining_units(np.array([1, 2]), np.array([1]))
