"""Rigid-body helpers. Pure numpy, no ROS imports.

Kept separate from the node so the maths can be exercised without a running
graph, and so the quaternion convention is stated in exactly one place.
"""

from __future__ import annotations

import math

import numpy as np


def quaternion_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    """Rotation matrix from a Hamilton quaternion, ROS (x, y, z, w) order."""
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-12:
        raise ValueError("quaternion has zero norm")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm

    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return np.array(
        [
            [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
            [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
            [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
        ],
        dtype=np.float64,
    )


def rpy_to_quaternion(
    roll: float, pitch: float, yaw: float
) -> "tuple[float, float, float, float]":
    """Fixed-axis roll-pitch-yaw (X, then Y, then Z) to ROS (x, y, z, w)."""
    cr, sr = math.cos(roll * 0.5), math.sin(roll * 0.5)
    cp, sp = math.cos(pitch * 0.5), math.sin(pitch * 0.5)
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def transform_to_matrix(translation, rotation) -> np.ndarray:
    """4x4 homogeneous matrix from a geometry_msgs Transform-like object."""
    mat = np.eye(4, dtype=np.float64)
    mat[:3, :3] = quaternion_to_matrix(
        rotation.x, rotation.y, rotation.z, rotation.w
    )
    mat[:3, 3] = (translation.x, translation.y, translation.z)
    return mat


def apply_transform(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Apply a 4x4 transform to an (N, 3) point array, returning (N, 3)."""
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"points must be (N, 3), got {points.shape}")
    if points.shape[0] == 0:
        return points.astype(np.float64, copy=False)
    return points @ matrix[:3, :3].T + matrix[:3, 3]
