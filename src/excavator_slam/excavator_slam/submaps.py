"""Building comparable submaps out of posed scans.

DELIBERATELY ROS-FREE, like the rest of the package's maths.

The whole point of this module is that the baseline and SLAM go through the SAME
crop. They do not share a frame: the deployed anchor emits gravity-aligned points
whose origin is the swing axis on the ground, while a LiDAR-odometry map frame is
just wherever the sensor was pointing at the first scan - here a boom-mounted sensor
tilted about 45 degrees, with an arbitrary height datum. A crop written against
either frame's zero would carve a different volume out of each, and the resulting
comparison would be measuring the crop rather than the mapping.
"""

from __future__ import annotations

import numpy as np

MIN_ANNULUS_POINTS = 50


def crop_around_machine(points, machine_xy, min_range_m, max_range_m, z_low_m, z_high_m,
                        min_annulus_points=MIN_ANNULUS_POINTS):
    """Keep the terrain ring around the machine and drop the machine itself.

    The radial bounds are measured from the machine, not from the frame origin, and
    the height band is measured from the local ground level - the median height of
    the ring - not from the frame's zero. That makes the crop invariant to where a
    frame happens to put its datum, which is what lets the same call serve the
    GNSS-anchor baseline and a SLAM map.

    The bounds themselves were decided by measurement rather than taste (see the crop
    study recorded in scripts/anchor_submaps.py): the height band is what removes the
    boom, arm and bucket, which sit above the terrain and sweep with the cab, while
    pushing the near radius outward only costs point density and lets any attitude
    error grow with range.

    Returns an (N, 3) array, empty when the ring holds too few points to locate the
    ground - a frame that saw nothing usable must contribute nothing rather than
    contribute a guess.
    """
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] < 3:
        raise ValueError(f"points must be an Nx3 array, got shape {points.shape}")
    points = points[:, :3]

    radius = np.hypot(points[:, 0] - machine_xy[0], points[:, 1] - machine_xy[1])
    annulus = (radius >= min_range_m) & (radius <= max_range_m)
    if int(annulus.sum()) < min_annulus_points:
        return np.zeros((0, 3), dtype=float)

    ground = float(np.median(points[annulus, 2]))
    keep = annulus & (points[:, 2] >= ground + z_low_m) & (points[:, 2] <= ground + z_high_m)
    return points[keep]


def poses_to_world(points_sensor, rotation, translation):
    """Apply one sensor pose to one scan: world = R @ p + t."""
    return np.asarray(points_sensor, dtype=float) @ np.asarray(rotation, dtype=float).T \
        + np.asarray(translation, dtype=float)


def quaternion_to_matrix(x, y, z, w):
    """TUM trajectories carry orientation as a quaternion; rotations need a matrix."""
    norm = np.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        raise ValueError("a zero quaternion has no rotation")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.array([
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ])


def gravity_rotation(points, sample=200000, seed=0):
    """One rotation taking the dominant plane's normal onto +Z.

    A LiDAR-odometry map inherits the sensor's attitude at the first scan, so on a
    boom-mounted sensor its z axis is tilted far off vertical, and a height-map metric
    would then be slicing the terrain at an angle. This estimates the site plane once
    over the WHOLE map and returns a single rigid rotation. Being one rotation shared
    by every window, it cannot flatter the agreement between two windows - it moves
    both identically - so it corrects the frame without touching what is measured.
    """
    points = np.asarray(points, dtype=float)[:, :3]
    if points.shape[0] > sample:
        rng = np.random.default_rng(seed)
        points = points[rng.choice(points.shape[0], size=sample, replace=False)]
    normal = np.linalg.svd(points - points.mean(axis=0), full_matrices=False)[2][-1]
    if normal[2] < 0.0:
        normal = -normal
    axis = np.cross(normal, np.array([0.0, 0.0, 1.0]))
    sine = np.linalg.norm(axis)
    cosine = float(np.dot(normal, np.array([0.0, 0.0, 1.0])))
    if sine < 1e-12:
        return np.eye(3)
    axis = axis / sine
    cross = np.array([[0.0, -axis[2], axis[1]],
                      [axis[2], 0.0, -axis[0]],
                      [-axis[1], axis[0], 0.0]])
    angle = np.arctan2(sine, cosine)
    return np.eye(3) + np.sin(angle) * cross + (1.0 - np.cos(angle)) * (cross @ cross)
