"""Turn a capture bundle into the 3D half of a correspondence.

Picking the pixel half off the grid overlay is quick; the 3D half used to be an
ad-hoc numpy session per shot, done on site with the machine waiting. The two
steps it needs are mechanical: move the cloud out of the LiDAR frame into the
frame the extrinsic is solved in, and isolate the target from the ground around
it. Both are here so they can be tested, and so the field session runs a command
instead of a paste.

No ROS imports: the transforms come frozen in each capture's meta.json, so this
works offline, exactly as it did at capture time.
"""

from __future__ import annotations

import numpy as np

from excavator_ar_overlay.geometry import quaternion_to_matrix


def frozen_transform_matrix(entry: dict) -> np.ndarray:
    """4x4 map<-frame matrix from a meta.json ``transforms`` entry."""
    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = quaternion_to_matrix(*entry["rotation_xyzw"])
    matrix[:3, 3] = entry["translation"]
    return matrix


def points_between_frames(points, source: dict, target: dict) -> np.ndarray:
    """Re-express points given in ``source`` in ``target``.

    Both arguments are meta.json entries, i.e. map<-frame, so the composition is
    (map<-target)^-1 @ (map<-source).
    """
    points = np.asarray(points, dtype=np.float64)
    relative = np.linalg.inv(frozen_transform_matrix(target)) @ frozen_transform_matrix(
        source
    )
    return points @ relative[:3, :3].T + relative[:3, 3]


def find_target(
    points,
    near_xy,
    search_radius_m: float = 1.0,
    min_height_m: float = 0.25,
    min_points: int = 20,
) -> "dict | None":
    """Isolate the target standing on the ground near ``near_xy``.

    Returns its ground contact point, which is what a pixel picked at the base
    of the target in the image corresponds to.

    The ground height is taken locally rather than from a global plane fit: the
    site is not level, and an error in z is an error in the correspondence.
    """
    points = np.asarray(points, dtype=np.float64)
    if points.size == 0:
        return None
    near = np.asarray(near_xy, dtype=np.float64)
    local = points[np.linalg.norm(points[:, :2] - near, axis=1) <= search_radius_m]
    if local.shape[0] < min_points:
        return None

    ground_z = float(np.percentile(local[:, 2], 20.0))
    blob = local[local[:, 2] > ground_z + min_height_m]
    if blob.shape[0] < min_points:
        return None

    centroid = blob.mean(axis=0)
    return {
        "base_xyz": [float(centroid[0]), float(centroid[1]), ground_z],
        "centroid_xyz": [float(v) for v in centroid],
        "ground_z": ground_z,
        "n_points": int(blob.shape[0]),
    }
