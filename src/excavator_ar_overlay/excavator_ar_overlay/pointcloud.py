"""PointCloud2 -> numpy, without a ros2_numpy dependency."""

from __future__ import annotations

import numpy as np

# sensor_msgs/PointField datatype constants.
_NUMPY_BY_DATATYPE = {
    1: "<i1",
    2: "<u1",
    3: "<i2",
    4: "<u2",
    5: "<i4",
    6: "<u4",
    7: "<f4",
    8: "<f8",
}

# Ouster publishes both; reflectivity is the calibrated one, which is what a
# retro-reflective target would stand out in.
_INTENSITY_NAMES = ("reflectivity", "intensity")


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


def extract_organized(cloud) -> np.ndarray:
    """(height, width, 4) float32 of x, y, z, intensity, structure intact.

    What a capture kept on disk needs, as opposed to what drawing needs.
    `extract_xyz` drops invalid returns and hands back a flat list, which
    destroys the ring/column grid: range discontinuities then have to be
    approximated by re-binning angles, and the intensity channel is gone
    entirely. Here invalid returns become NaN instead, so the grid survives and
    a consumer can still tell which returns are real.

    Intensity is NaN when the cloud carries no such field.
    """
    fields = {field.name: field for field in cloud.fields}
    count = cloud.width * cloud.height
    if not {"x", "y", "z"} <= fields.keys() or count <= 0:
        return np.empty((0, 0, 4), dtype=np.float32)

    names = ["x", "y", "z"]
    intensity = next((name for name in _INTENSITY_NAMES if name in fields), None)
    if intensity is not None:
        names.append(intensity)
    formats = [_NUMPY_BY_DATATYPE.get(fields[name].datatype) for name in names]
    if any(fmt is None for fmt in formats[:3]):
        return np.empty((0, 0, 4), dtype=np.float32)
    if formats[-1] is None:
        names, formats = names[:3], formats[:3]

    raw = np.frombuffer(
        cloud.data,
        dtype=np.dtype(
            {
                "names": names,
                "formats": formats,
                "offsets": [fields[name].offset for name in names],
                "itemsize": cloud.point_step,
            }
        ),
        count=count,
    )
    out = np.full((count, 4), np.nan, dtype=np.float32)
    for column, name in enumerate(names):
        out[:, column] = raw[name]

    xyz = out[:, :3]
    invalid = ~np.isfinite(xyz).all(axis=1) | (np.abs(xyz).sum(axis=1) <= 1e-6)
    out[invalid, :3] = np.nan
    return out.reshape(cloud.height, cloud.width, 4)
