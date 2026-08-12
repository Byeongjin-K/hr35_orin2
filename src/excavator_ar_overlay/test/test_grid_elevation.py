"""Tests for the GridMap elevation sampler.

Built around a synthetic map so the two things most likely to be wrong are
pinned down: honouring ``info.pose`` (the spec calls out that the existing GUI
discards it) and unrolling the column-major circular buffer.
"""

from __future__ import annotations

import numpy as np
import pytest
from grid_map_msgs.msg import GridMap
from std_msgs.msg import Float32MultiArray, MultiArrayDimension

from excavator_ar_overlay.grid_elevation import ELEVATION_LAYER, ElevationGrid

RES = 0.15
N_ROWS = 34
N_COLS = 67


def make_message(
    values: np.ndarray,
    center=(0.0, 0.0),
    outer_start=0,
    inner_start=0,
    layer=ELEVATION_LAYER,
    frame_id="map",
) -> GridMap:
    """Serialise (n_rows, n_cols) exactly the way grid_map_ros does."""
    n_rows, n_cols = values.shape

    stored = values
    if outer_start:
        stored = np.roll(stored, outer_start, axis=0)
    if inner_start:
        stored = np.roll(stored, inner_start, axis=1)

    array = Float32MultiArray()
    array.layout.dim = [
        MultiArrayDimension(
            label="column_index", size=n_cols, stride=n_rows * n_cols
        ),
        MultiArrayDimension(label="row_index", size=n_rows, stride=n_rows),
    ]
    # Column-major, straight out of an Eigen matrix.
    array.data = stored.T.reshape(-1).astype(np.float32).tolist()

    msg = GridMap()
    msg.header.frame_id = frame_id
    msg.layers = [layer]
    msg.data = [array]
    msg.info.resolution = RES
    msg.info.length_x = n_rows * RES
    msg.info.length_y = n_cols * RES
    msg.info.pose.position.x = float(center[0])
    msg.info.pose.position.y = float(center[1])
    msg.info.pose.orientation.w = 1.0
    msg.outer_start_index = outer_start
    msg.inner_start_index = inner_start
    return msg


def ramp_values() -> np.ndarray:
    rows = np.arange(N_ROWS, dtype=np.float32).reshape(-1, 1)
    cols = np.arange(N_COLS, dtype=np.float32).reshape(1, -1)
    return rows * 100.0 + cols


def test_missing_layer_returns_none():
    msg = make_message(ramp_values(), layer="something_else")
    assert ElevationGrid.from_message(msg) is None


def test_layer_is_unrolled_to_row_major():
    grid = ElevationGrid.from_message(make_message(ramp_values()))
    assert grid is not None
    assert grid.values.shape == (N_ROWS, N_COLS)
    assert grid.values[0, 0] == pytest.approx(0.0)
    assert grid.values[5, 7] == pytest.approx(507.0)
    assert grid.values[N_ROWS - 1, N_COLS - 1] == pytest.approx(
        (N_ROWS - 1) * 100.0 + (N_COLS - 1)
    )


@pytest.mark.parametrize("outer,inner", [(0, 0), (7, 0), (0, 13), (31, 60)])
def test_circular_buffer_is_undone(outer, inner):
    expected = ramp_values()
    grid = ElevationGrid.from_message(
        make_message(expected, outer_start=outer, inner_start=inner)
    )
    assert grid is not None
    assert np.allclose(grid.values, expected)


@pytest.mark.parametrize("center", [(0.0, 0.0), (2.5, -1.25), (-4.0, 3.0)])
def test_sample_round_trips_through_position_of(center):
    """The strongest invariant: sampling a cell's own centre returns its value."""
    expected = ramp_values()
    grid = ElevationGrid.from_message(make_message(expected, center=center))
    assert grid is not None

    probes = [(0, 0), (1, 2), (17, 33), (N_ROWS - 1, N_COLS - 1)]
    xy = np.array([grid.position_of(r, c) for r, c in probes])
    heights, valid = grid.sample(xy)

    assert valid.all()
    for index, (r, c) in enumerate(probes):
        assert heights[index] == pytest.approx(expected[r, c])


def test_ignoring_info_pose_would_be_detected():
    """A map offset by info.pose must NOT read like a map centred at origin."""
    expected = ramp_values()
    offset = (3.0, 1.5)
    shifted = ElevationGrid.from_message(make_message(expected, center=offset))
    centred = ElevationGrid.from_message(make_message(expected, center=(0.0, 0.0)))
    assert shifted is not None and centred is not None

    # Must lie inside BOTH footprints, otherwise the test proves nothing:
    #   centred spans x[-2.55, 2.55] y[-5.025, 5.025]
    #   shifted spans x[ 0.45, 5.55] y[-3.525, 6.525]
    probe = np.array([[1.5, 0.0]])
    shifted_h, shifted_ok = shifted.sample(probe)
    centred_h, centred_ok = centred.sample(probe)
    assert shifted_ok.all() and centred_ok.all()
    assert shifted_h[0] != pytest.approx(centred_h[0])


def test_samples_outside_the_map_are_invalid():
    grid = ElevationGrid.from_message(make_message(ramp_values()))
    assert grid is not None
    far = np.array([[1e3, 0.0], [0.0, -1e3]])
    heights, valid = grid.sample(far)
    assert not valid.any()
    assert np.isnan(heights).all()


def test_nan_cells_are_invalid():
    values = ramp_values()
    values[4, 9] = np.nan
    grid = ElevationGrid.from_message(make_message(values))
    assert grid is not None
    xy = np.array([grid.position_of(4, 9)])
    _, valid = grid.sample(xy)
    assert not valid.any()


def test_empty_query_is_handled():
    grid = ElevationGrid.from_message(make_message(ramp_values()))
    assert grid is not None
    heights, valid = grid.sample(np.empty((0, 2)))
    assert heights.size == 0 and valid.size == 0


def test_bad_query_shape_raises():
    grid = ElevationGrid.from_message(make_message(ramp_values()))
    assert grid is not None
    with pytest.raises(ValueError):
        grid.sample(np.zeros((3, 3)))
