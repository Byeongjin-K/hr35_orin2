"""Sample the elevation layer of a grid_map_msgs/GridMap at arbitrary points.

Pure numpy, no ROS imports: takes the plain fields off the message so it can be
unit tested against a synthetic map.

Two details that are easy to get wrong and that this feature exists to catch:

* ``info.pose`` is the pose of the map *centre* in ``header.frame_id``. Ignoring
  it silently offsets every sample by however far the map has drifted from the
  origin, which is exactly the class of error the overlay is meant to expose.
* GridMap stores its layers in a circular buffer. ``outer_start_index`` /
  ``inner_start_index`` rotate the row/column axes, and the payload is
  **column-major** (flat = col * n_rows + row) because it comes straight out of
  an Eigen matrix. Reading it as a plain row-major image gives a map that looks
  plausible but is rotated and wrapped.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ELEVATION_LAYER = "elevation"


@dataclass(frozen=True)
class ElevationGrid:
    """An elevation layer plus everything needed to index it by position."""

    values: np.ndarray  # (n_rows, n_cols), circular buffer already unrolled
    resolution: float
    length_x: float
    length_y: float
    center_xy: "tuple[float, float]"  # info.pose position, in frame_id
    frame_id: str

    @classmethod
    def from_message(cls, msg, layer: str = ELEVATION_LAYER) -> "ElevationGrid | None":
        """Build from a GridMap message, or None if the layer is absent/degenerate."""
        if layer not in msg.layers:
            return None
        array = msg.data[list(msg.layers).index(layer)]
        dims = array.layout.dim
        if len(dims) < 2:
            return None

        n_cols = int(dims[0].size)
        n_rows = int(dims[1].size)
        if n_rows <= 0 or n_cols <= 0:
            return None

        flat = np.asarray(array.data, dtype=np.float32)
        if flat.size != n_rows * n_cols:
            return None

        # Column-major payload -> (n_rows, n_cols).
        values = flat.reshape((n_cols, n_rows)).T

        # Undo the circular buffer so index (0, 0) is the map's far/left corner.
        outer = int(getattr(msg, "outer_start_index", 0)) % n_rows
        inner = int(getattr(msg, "inner_start_index", 0)) % n_cols
        if outer:
            values = np.roll(values, -outer, axis=0)
        if inner:
            values = np.roll(values, -inner, axis=1)

        resolution = float(msg.info.resolution)
        if resolution <= 0.0:
            return None

        return cls(
            values=values,
            resolution=resolution,
            length_x=float(msg.info.length_x),
            length_y=float(msg.info.length_y),
            center_xy=(
                float(msg.info.pose.position.x),
                float(msg.info.pose.position.y),
            ),
            frame_id=msg.header.frame_id,
        )

    def sample(self, xy: np.ndarray) -> "tuple[np.ndarray, np.ndarray]":
        """Nearest-cell elevation at (N, 2) positions expressed in `frame_id`.

        Returns `(heights, valid)`. `valid` is False where the query falls
        outside the map or the cell holds NaN.
        """
        xy = np.asarray(xy, dtype=np.float64)
        if xy.ndim != 2 or xy.shape[1] != 2:
            raise ValueError(f"xy must be (N, 2), got {xy.shape}")
        if xy.shape[0] == 0:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=bool)

        local_x = xy[:, 0] - self.center_xy[0]
        local_y = xy[:, 1] - self.center_xy[1]

        # grid_map: index 0 sits at the maximum x (and maximum y) edge.
        rows = np.floor((self.length_x * 0.5 - local_x) / self.resolution)
        cols = np.floor((self.length_y * 0.5 - local_y) / self.resolution)

        n_rows, n_cols = self.values.shape
        inside = (
            (rows >= 0) & (rows < n_rows) & (cols >= 0) & (cols < n_cols)
        )

        heights = np.full(xy.shape[0], np.nan, dtype=np.float64)
        if np.any(inside):
            ri = rows[inside].astype(np.int64)
            ci = cols[inside].astype(np.int64)
            heights[inside] = self.values[ri, ci]

        valid = inside & np.isfinite(heights)
        return heights, valid

    def position_of(self, row: int, col: int) -> "tuple[float, float]":
        """Centre position of a cell, in `frame_id`. Inverse of `sample`."""
        x = self.center_xy[0] + self.length_x * 0.5 - (row + 0.5) * self.resolution
        y = self.center_xy[1] + self.length_y * 0.5 - (col + 0.5) * self.resolution
        return x, y
