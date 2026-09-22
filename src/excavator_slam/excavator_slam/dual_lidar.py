"""Placing the boom LiDAR's returns with the SLAM pose, through the machine's own joint.

DELIBERATELY ROS-FREE, like the rest of this package's maths.

GLIM consumes ONE point cloud. The cabin sensor is the SLAM sensor because it is rigid
with the GNSS antenna; the boom sensor is a mapping sensor, and the difference is not
cosmetic. georeference.py records what happens when a boom-mounted sensor is treated as
if it located itself: over 62 s in which the machine moved 0.095 m, the boom joint went
44.08 -> 32.46 deg and the boom LiDAR's height changed -0.555 m while the cab-mounted
antenna saw +0.016 m. The estimator was not drifting - it was correctly tracking a boom
coming down - and forcing the two to agree injected the articulation as error (dz_bias
+0.209 -> +0.563 m, every other figure worse too).

So the boom returns are PLACED, never trusted to locate themselves: their pose comes from
the SLAM sensor plus the joint that separates the two mounts.

WHY THE SWING ANGLE IS ABSENT, which is the non-obvious part
------------------------------------------------------------
The deployed anchor chain needs swing because it relates the undercarriage-fixed map
frame to the cab. Here both sensors are bolted to the SAME swinging upper body - the
cabin LiDAR on the cab, the boom hinge on the superstructure it pivots from - so swing
moves them together and cancels between them. What separates them is the boom joint
alone. A swing term reintroduced here would rotate the boom cloud relative to a cab that
had already rotated with it, i.e. it would apply the swing twice.

SIGN CONVENTION
---------------
Cab frame is x forward, y left, z up, matching the voxeliser chain and gnss_anchor. A
positive boom angle is a raised boom, so the link rotates about -Y: the tip of a link of
length r sits at (r*cos(theta), 0, r*sin(theta)). The handover's shorthand "2.8 m and
11.6 degrees is 0.55 m" is the arc length r*dtheta; the vertical component this module
computes is r*(sin a - sin b), which for those numbers is 0.445 m. The shorthand is fine
for sizing an error, not for placing a point.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from .submaps import quaternion_to_matrix


def _xyz(vector):
    return (float(vector[0]), float(vector[1]), float(vector[2]))


def _rot_y_negative(angle_rad):
    """Rotation about -Y, so a positive angle lifts a link lying along +X."""
    cosine, sine = np.cos(angle_rad), np.sin(angle_rad)
    return np.array([[cosine, 0.0, -sine],
                     [0.0, 1.0, 0.0],
                     [sine, 0.0, cosine]], dtype=float)


@dataclass(frozen=True)
class SensorPose:
    """A rigid placement: world = rotation @ local + translation."""

    translation: tuple[float, float, float]
    rotation: npt.NDArray[np.float64]

    @staticmethod
    def identity():
        return SensorPose(translation=(0.0, 0.0, 0.0), rotation=np.eye(3))

    @staticmethod
    def from_tum_row(row):
        """One row of a TUM trajectory WITHOUT its timestamp: [x y z qx qy qz qw].

        Taken as a single row rather than seven scalars because that is the shape the
        trajectories actually arrive in, and because seven positional floats is exactly
        the signature in which a quaternion silently ends up in the wrong order.
        """
        row = np.asarray(row, dtype=float).reshape(-1)
        if row.size != 7:
            raise ValueError(
                f"a TUM pose row is [x y z qx qy qz qw], got {row.size} values")
        return SensorPose(translation=(float(row[0]), float(row[1]), float(row[2])),
                          rotation=quaternion_to_matrix(*row[3:7]))

    def apply(self, points):
        return np.asarray(points, dtype=float) @ np.asarray(self.rotation, dtype=float).T \
            + np.asarray(self.translation, dtype=float)

    def invert(self):
        rotation = np.asarray(self.rotation, dtype=float)
        translation = np.asarray(self.translation, dtype=float)
        inverse = np.asarray(rotation.T, dtype=float)
        offset = _xyz(inverse @ translation)
        return SensorPose(translation=(-offset[0], -offset[1], -offset[2]),
                          rotation=inverse)


@dataclass(frozen=True)
class BoomChain:
    """The fixed geometry between the two sensors, measured once on the machine.

    cab_from_cabin_lidar maps CABIN-LIDAR points into the cab frame, which is the
    direction a mounting is naturally measured in. The placement needs the other
    direction and inverts it rather than asking the caller to pre-invert, because an
    inverted extrinsic handed in by mistake is invisible until the map is wrong.
    """

    cab_from_cabin_lidar: SensorPose
    hinge_in_cab_m: tuple[float, float, float]
    lidar_in_link_m: tuple[float, float, float]
    lidar_rotation_in_link: npt.NDArray[np.float64] = field(
        default_factory=lambda: np.eye(3, dtype=float))


@dataclass(frozen=True)
class MachineState:
    """Everything that moves, for one instant."""

    slam_pose: SensorPose
    boom_deg: float


def boom_lidar_in_cab(chain, boom_deg):
    """Where the boom LiDAR sits in the cab frame at this boom angle."""
    link = _rot_y_negative(np.radians(float(boom_deg)))
    hinge = np.asarray(chain.hinge_in_cab_m, dtype=float)
    mount = np.asarray(chain.lidar_in_link_m, dtype=float)
    mount_rotation = np.asarray(chain.lidar_rotation_in_link, dtype=float)
    return SensorPose(
        translation=_xyz(hinge + link @ mount),
        rotation=np.asarray(link @ mount_rotation, dtype=float))


def place_boom_points(points_boom, chain, state):
    """Boom-frame returns into the SLAM world frame.

    boom LiDAR -> cab (via the joint) -> cabin LiDAR (via the fixed mounting, inverted)
    -> world (via the SLAM pose).
    """
    points = np.asarray(points_boom, dtype=float)
    if points.ndim != 2 or points.shape[1] < 3:
        raise ValueError(f"points must be an Nx3 array, got shape {points.shape}")
    points = points[:, :3]

    in_cab = boom_lidar_in_cab(chain, state.boom_deg).apply(points)
    in_cabin_lidar = chain.cab_from_cabin_lidar.invert().apply(in_cab)
    return state.slam_pose.apply(in_cabin_lidar)
