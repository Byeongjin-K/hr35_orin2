"""AI dig-plan cells -> 3D polygons anchored on the swing axis.

Pure geometry, no ROS imports, so the conversion that this whole feature exists
to validate can itself be unit tested offline.

Conventions, all verified against the authoritative implementation in
``excavator_task_config_gui/core/ai_grid_alignment.py`` and
``core/ai_coordinate_diagnostics.py`` rather than assumed:

* ``AI[i, j] = GUI[swing_axis_row + i, j]``, so ``gui_row = ai_row + swing_axis_row``.
  Columns are shared: ``ai_col == gui_col``.
* ``forward_m = (gui_row - swing_axis_row) * cell_size``, which reduces to
  ``ai_row * cell_size``. AI row 0 is the swing axis itself.
* ``lateral_m = (ai_col - CENTER_COL) * cell_size`` with ``CENTER_COL = 33``.
* Those two values locate the *centre* of the cell: the diagnostic node compares
  ``forward_m`` directly against a bucket FK position, which is only meaningful
  for a cell centre.

Axis directions in the anchor frame were read off the live TF tree, not guessed.
``map -> gm_boom_link`` sits at (0.860, 0.017, 1.273) and
``map -> gm_lidar_mount`` at (2.201, 0.065, 2.119): both are boom-mounted and
both differ from the swing axis almost purely in +x. The boom points forward,
therefore +x is forward, +y is lateral (left, right-handed about +z up). That
also matches ``grid_map_processor`` where ``x = row * CELL_SIZE`` and
``y = col * CELL_SIZE``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CELL_SIZE_M = 0.15
CENTER_COL = 33
HEIGHT_UNIT_M = 0.1
AI_ROWS = 38
AI_COLS = 67


def gui_row_from_ai_row(ai_row: int, swing_axis_row: int) -> int:
    """Inverse of ``AI[i, j] = GUI[swing_axis_row + i, j]``."""
    return int(ai_row) + int(swing_axis_row)


def cell_center_m(
    ai_row: int, ai_col: int, cell_size: float = CELL_SIZE_M
) -> "tuple[float, float]":
    """Cell centre as (forward, lateral) metres from the swing axis."""
    return (int(ai_row) * cell_size, (int(ai_col) - CENTER_COL) * cell_size)


@dataclass(frozen=True)
class DigPlanCells:
    """A dig selection reduced to what the overlay needs to draw."""

    rows: np.ndarray  # (N,) AI rows
    cols: np.ndarray  # (N,) AI cols
    start_row: int
    start_col: int

    @classmethod
    def from_sequences(
        cls, rows, cols, start_row: int, start_col: int
    ) -> "DigPlanCells":
        r = np.asarray(list(rows), dtype=np.int32)
        c = np.asarray(list(cols), dtype=np.int32)
        if r.shape != c.shape:
            raise ValueError(
                f"selected_rows/selected_cols length mismatch: {r.shape} vs {c.shape}"
            )
        return cls(rows=r, cols=c, start_row=int(start_row), start_col=int(start_col))

    def __len__(self) -> int:
        return int(self.rows.shape[0])

    def in_range_mask(self) -> np.ndarray:
        """Cells that fall inside the declared AI grid extent."""
        return (
            (self.rows >= 0)
            & (self.rows < AI_ROWS)
            & (self.cols >= 0)
            & (self.cols < AI_COLS)
        )


def cell_corners(
    ai_rows: np.ndarray,
    ai_cols: np.ndarray,
    heights_m: np.ndarray,
    cell_size: float = CELL_SIZE_M,
) -> np.ndarray:
    """Corner polygons for each cell, in the swing-axis frame.

    Returns (N, 4, 3) ordered counter-clockwise seen from above:
    near-right, far-right, far-left, near-left. `heights_m` is the z of each
    cell, one per cell, normally sampled from the grid map elevation layer.
    """
    ai_rows = np.asarray(ai_rows, dtype=np.float64)
    ai_cols = np.asarray(ai_cols, dtype=np.float64)
    heights_m = np.asarray(heights_m, dtype=np.float64)
    if not (ai_rows.shape == ai_cols.shape == heights_m.shape):
        raise ValueError(
            f"shape mismatch: rows{ai_rows.shape} cols{ai_cols.shape} "
            f"heights{heights_m.shape}"
        )

    half = cell_size * 0.5
    forward = ai_rows * cell_size
    lateral = (ai_cols - CENTER_COL) * cell_size

    near, far = forward - half, forward + half
    right, left = lateral - half, lateral + half

    corners = np.empty((ai_rows.shape[0], 4, 3), dtype=np.float64)
    corners[:, 0] = np.stack((near, right, heights_m), axis=1)
    corners[:, 1] = np.stack((far, right, heights_m), axis=1)
    corners[:, 2] = np.stack((far, left, heights_m), axis=1)
    corners[:, 3] = np.stack((near, left, heights_m), axis=1)
    return corners


def remaining_to_color(remaining_units: float) -> "tuple[int, int, int]":
    """BGR for a remaining-depth value in height-units.

    Positive means material is still above target and must be removed; negative
    means the cell is already over-dug. Amber for "dig more", blue-ish for
    "over-dug", green when within a tenth of a unit of target.
    """
    if remaining_units > 0.1:
        strength = min(1.0, remaining_units / 3.0)
        return (0, int(140 + 115 * strength), int(255 * strength))
    if remaining_units < -0.1:
        strength = min(1.0, -remaining_units / 3.0)
        return (int(120 + 135 * strength), int(90 * strength), 0)
    return (90, 220, 90)


def remaining_to_colors(
    remaining_units: np.ndarray, valid: "np.ndarray | None" = None
) -> np.ndarray:
    """Vectorised per-cell version of `remaining_to_color`, returning (N, 3) BGR.

    Per-cell colour is the point of the encoding: AiActionStatus only carries one
    scalar mean for the whole selection, so colouring from that paints every cell
    the same and hides the distribution the operator is looking for. Cells with
    `valid` False fall back to neutral grey rather than to a misleading colour.
    """
    values = np.asarray(remaining_units, dtype=np.float64)
    out = np.full((values.size, 3), 150, dtype=np.uint8)
    if values.size == 0:
        return out

    usable = np.isfinite(values)
    if valid is not None:
        usable &= np.asarray(valid, dtype=bool)

    dig = usable & (values > 0.1)
    over = usable & (values < -0.1)
    near = usable & ~dig & ~over

    if np.any(dig):
        s = np.clip(values[dig] / 3.0, 0.0, 1.0)
        out[dig] = np.stack(
            (np.zeros_like(s), 140 + 115 * s, 255 * s), axis=1
        ).astype(np.uint8)
    if np.any(over):
        s = np.clip(-values[over] / 3.0, 0.0, 1.0)
        out[over] = np.stack(
            (120 + 135 * s, 90 * s, np.zeros_like(s)), axis=1
        ).astype(np.uint8)
    out[near] = (90, 220, 90)
    return out
