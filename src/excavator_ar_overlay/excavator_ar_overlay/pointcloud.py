"""PointCloud2 -> (N, 3) numpy, without a ros2_numpy dependency."""

from __future__ import annotations

import numpy as np


def extract_xyz(cloud, max_points: int) -> np.ndarray:
    """Vectorised XYZ extraction straight from the PointCloud2 buffer.

    Invalid returns are dropped: non-finite values, and the exact zeros the
    Ouster emits for a non-return, which would otherwise pile up at the sensor
    origin and smear across the image once projected.

    `max_points` > 0 subsamples by striding, which keeps the angular spread of
    the cloud instead of clipping it to whichever rows happen to come first.
    """
    offsets = {field.name: field.offset for field in cloud.fields}
    if not {"x", "y", "z"} <= offsets.keys():
        return np.empty((0, 3), dtype=np.float64)

    dtype = np.dtype(
        {
            "names": ["x", "y", "z"],
            "formats": ["<f4", "<f4", "<f4"],
            "offsets": [offsets["x"], offsets["y"], offsets["z"]],
            "itemsize": cloud.point_step,
        }
    )
    count = cloud.width * cloud.height
    if count <= 0:
        return np.empty((0, 3), dtype=np.float64)

    raw = np.frombuffer(cloud.data, dtype=dtype, count=count)
    points = np.stack((raw["x"], raw["y"], raw["z"]), axis=1).astype(np.float64)

    finite = np.isfinite(points).all(axis=1)
    nonzero = np.abs(points).sum(axis=1) > 1e-6
    points = points[finite & nonzero]

    if max_points > 0 and points.shape[0] > max_points:
        stride = int(np.ceil(points.shape[0] / max_points))
        points = points[::stride]
    return points
