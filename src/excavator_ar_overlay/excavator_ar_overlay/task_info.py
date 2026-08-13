"""Per-cell terrain state from excavator_msgs/TaskInfo.

The spec asks for dig cells coloured by how much material is still above target,
which needs a *per-cell* number. AiActionStatus only carries the scalar
`mean_remaining_delta_units` for the whole selection, so colouring from it paints
every cell identically and throws away the very distribution the operator wants
to see. TaskInfo carries both `cell_heights` (current) and `target_heights`
(designed) for all 38x67 cells, so the difference is available per cell.

Pure numpy, no ROS imports, so the indexing convention is testable offline.

Layout, per the TaskInfo definition:
    index = row * grid_width + col,  size = grid_length * grid_width = 38 * 67
    rows are AI rows (grid_length = 38, the AR policy grid), columns are shared
    remaining_units = (current - target) / height_resolution
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_HEIGHT_RESOLUTION_M = 0.1


@dataclass(frozen=True)
class TerrainState:
    """Current and target height grids indexed by AI (row, col)."""

    current_m: np.ndarray  # (rows, cols)
    target_m: np.ndarray  # (rows, cols)
    mask: np.ndarray  # (rows, cols) bool, True where the cell is a work target
    height_resolution_m: float

    @classmethod
    def from_message(cls, msg) -> "TerrainState | None":
        rows = int(msg.grid_length)
        cols = int(msg.grid_width)
        if rows <= 0 or cols <= 0:
            return None
        expected = rows * cols

        current = np.asarray(msg.cell_heights, dtype=np.float64)
        target = np.asarray(msg.target_heights, dtype=np.float64)
        if current.size != expected or target.size != expected:
            return None

        raw_mask = np.asarray(msg.target_mask, dtype=np.uint8)
        mask = (
            raw_mask.reshape(rows, cols) != 0
            if raw_mask.size == expected
            else np.ones((rows, cols), dtype=bool)
        )

        resolution = float(msg.height_resolution) or DEFAULT_HEIGHT_RESOLUTION_M
        return cls(
            current_m=current.reshape(rows, cols),
            target_m=target.reshape(rows, cols),
            mask=mask,
            height_resolution_m=resolution,
        )

    @property
    def shape(self) -> "tuple[int, int]":
        return self.current_m.shape

    def remaining_units(
        self, ai_rows: np.ndarray, ai_cols: np.ndarray
    ) -> "tuple[np.ndarray, np.ndarray]":
        """Per-cell material still above target, in height-units.

        Positive means dig more, negative means over-dug, matching the sign
        convention of AiActionStatus.mean_remaining_delta_units.

        Returns `(values, valid)`; `valid` is False for cells outside the grid,
        outside the work mask, or holding a non-finite height.
        """
        ai_rows = np.asarray(ai_rows, dtype=np.int64)
        ai_cols = np.asarray(ai_cols, dtype=np.int64)
        if ai_rows.shape != ai_cols.shape:
            raise ValueError(
                f"row/col shape mismatch: {ai_rows.shape} vs {ai_cols.shape}"
            )

        rows, cols = self.shape
        inside = (
            (ai_rows >= 0) & (ai_rows < rows) & (ai_cols >= 0) & (ai_cols < cols)
        )

        values = np.full(ai_rows.shape, np.nan, dtype=np.float64)
        if np.any(inside):
            r, c = ai_rows[inside], ai_cols[inside]
            delta = self.current_m[r, c] - self.target_m[r, c]
            values[inside] = delta / self.height_resolution_m
            in_mask = np.zeros(ai_rows.shape, dtype=bool)
            in_mask[inside] = self.mask[r, c]
            inside = inside & in_mask

        return values, inside & np.isfinite(values)

    def heights_m(
        self, ai_rows: np.ndarray, ai_cols: np.ndarray
    ) -> "tuple[np.ndarray, np.ndarray]":
        """Current surface height per cell, for placing the polygons in 3D."""
        ai_rows = np.asarray(ai_rows, dtype=np.int64)
        ai_cols = np.asarray(ai_cols, dtype=np.int64)
        rows, cols = self.shape
        inside = (
            (ai_rows >= 0) & (ai_rows < rows) & (ai_cols >= 0) & (ai_cols < cols)
        )
        values = np.full(ai_rows.shape, np.nan, dtype=np.float64)
        if np.any(inside):
            values[inside] = self.current_m[ai_rows[inside], ai_cols[inside]]
        return values, inside & np.isfinite(values)
