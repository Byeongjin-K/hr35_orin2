"""The boom LiDAR is placed, never trusted to locate itself.

These tests exist because the project already paid for the lesson once, in
georeference.py: forcing a boom-mounted sensor to agree with a cab-mounted reference
made every figure worse, because 11.6 degrees of boom joint is about half a metre of
sensor height and the reference cannot see it. The chain below is the fix, so the tests
are written to fail loudly if any part of it is dropped.
"""

from __future__ import annotations

import numpy as np
import pytest

from excavator_slam.dual_lidar import (
    BoomChain,
    MachineState,
    SensorPose,
    boom_lidar_in_cab,
    place_boom_points,
)

# The field measurement this module exists to honour: the boom joint swung from 44.08 to
# 32.46 degrees between two windows 62 s apart, and the boom LiDAR's height changed by
# 0.555 m while the cab-mounted antenna saw +0.016 m.
BOOM_HIGH_DEG = 44.08
BOOM_LOW_DEG = 32.46
LIDAR_FROM_HINGE_M = 2.8


def _chain(lidar_from_hinge_m=LIDAR_FROM_HINGE_M):
    return BoomChain(
        cab_from_cabin_lidar=SensorPose.identity(),
        hinge_in_cab_m=(1.9, 0.0, 0.6),
        lidar_in_link_m=(lidar_from_hinge_m, 0.0, 0.0),
    )


def _identity_chain():
    return BoomChain(
        cab_from_cabin_lidar=SensorPose.identity(),
        hinge_in_cab_m=(0.0, 0.0, 0.0),
        lidar_in_link_m=(0.0, 0.0, 0.0),
    )


def test_an_identity_chain_at_zero_boom_leaves_points_where_they_were():
    points = np.array([[1.0, 2.0, 3.0], [-4.0, 0.5, 0.25]])
    state = MachineState(slam_pose=SensorPose.identity(), boom_deg=0.0)
    placed = place_boom_points(points, _identity_chain(), state)
    assert placed == pytest.approx(points, abs=1e-12)


def test_the_boom_joint_raises_the_sensor_by_the_arc_the_geometry_implies():
    """Exact trigonometry, not the small-angle shorthand the handover quotes.

    The handover says "2.8 m and 11.6 degrees is 0.55 m", which is the arc length
    r*dtheta. The chain must use the real vertical component, r*(sin a - sin b), so the
    expected value here is computed from the same geometry rather than copied from that
    shorthand - otherwise the test would pin the approximation instead of the chain.
    """
    high = boom_lidar_in_cab(_chain(), BOOM_HIGH_DEG)
    low = boom_lidar_in_cab(_chain(), BOOM_LOW_DEG)

    expected_drop = LIDAR_FROM_HINGE_M * (
        np.sin(np.radians(BOOM_HIGH_DEG)) - np.sin(np.radians(BOOM_LOW_DEG)))
    assert expected_drop == pytest.approx(0.4451, abs=1e-3)
    assert high.translation[2] - low.translation[2] == pytest.approx(expected_drop, abs=1e-9)


def test_dropping_the_boom_joint_would_mislocate_the_ground_by_tenths_of_a_metre():
    """The regression this module prevents, asserted as a difference.

    A chain that ignored the joint would place the same boom return at the same world
    point for both boom angles. Asserting the placements DIFFER by the measured amount
    is what makes this test fail if the joint term is ever removed.
    """
    ground_return = np.array([[12.0, 0.0, -2.0]])
    state_high = MachineState(slam_pose=SensorPose.identity(), boom_deg=BOOM_HIGH_DEG)
    state_low = MachineState(slam_pose=SensorPose.identity(), boom_deg=BOOM_LOW_DEG)

    placed_high = place_boom_points(ground_return, _chain(), state_high)
    placed_low = place_boom_points(ground_return, _chain(), state_low)

    separation = float(np.linalg.norm(placed_high - placed_low))
    assert separation > 0.4


def test_swing_does_not_enter_the_chain_because_both_sensors_ride_the_superstructure():
    """The cabin LiDAR and the boom hinge are both bolted to the swinging upper body.

    So the swing angle moves them together and cancels between them: the boom sensor's
    pose RELATIVE to the SLAM sensor depends on the boom joint alone. This test fails if
    someone reintroduces a swing term, by checking that a pure yaw applied to the SLAM
    pose rotates the placed points by exactly that yaw and nothing else.
    """
    points = np.array([[3.0, 1.0, -0.5], [7.0, -2.0, -1.25]])
    state = MachineState(slam_pose=SensorPose.identity(), boom_deg=BOOM_HIGH_DEG)
    placed = place_boom_points(points, _chain(), state)

    yaw = np.radians(37.0)
    rotation = np.array([[np.cos(yaw), -np.sin(yaw), 0.0],
                         [np.sin(yaw), np.cos(yaw), 0.0],
                         [0.0, 0.0, 1.0]])
    swung = MachineState(
        slam_pose=SensorPose(translation=(0.0, 0.0, 0.0), rotation=rotation),
        boom_deg=BOOM_HIGH_DEG)
    placed_swung = place_boom_points(points, _chain(), swung)

    assert placed_swung == pytest.approx(placed @ rotation.T, abs=1e-9)


def test_the_slam_pose_carries_the_points_into_the_world_frame():
    points = np.array([[1.0, 0.0, 0.0]])
    state = MachineState(
        slam_pose=SensorPose(translation=(10.0, -5.0, 2.0), rotation=np.eye(3)),
        boom_deg=0.0)
    placed = place_boom_points(points, _identity_chain(), state)
    assert placed == pytest.approx(np.array([[11.0, -5.0, 2.0]]), abs=1e-12)


def test_a_non_identity_cabin_mounting_is_inverted_and_not_applied_twice():
    """The branch a sign error hides in, pinned by an invariant instead of a number.

    place_boom_points goes cab -> cabin LiDAR by INVERTING the mounting, then cabin LiDAR
    -> world by the SLAM pose. So if the SLAM pose happens to equal the mounting, the two
    cancel exactly and the points must come back in cab coordinates. Applying the mounting
    the wrong way round, or twice, breaks this and nothing else in this file would notice.
    """
    yaw = np.radians(90.0)
    mounting = SensorPose(
        translation=(1.0, 2.0, 3.0),
        rotation=np.array([[np.cos(yaw), -np.sin(yaw), 0.0],
                           [np.sin(yaw), np.cos(yaw), 0.0],
                           [0.0, 0.0, 1.0]]))
    chain = BoomChain(cab_from_cabin_lidar=mounting,
                      hinge_in_cab_m=(0.0, 0.0, 0.0),
                      lidar_in_link_m=(0.0, 0.0, 0.0))
    points = np.array([[5.0, -1.0, 0.5], [0.0, 0.0, 0.0]])

    placed = place_boom_points(points, chain, MachineState(slam_pose=mounting, boom_deg=0.0))
    assert placed == pytest.approx(points, abs=1e-9)


def test_a_malformed_point_array_is_rejected_rather_than_reshaped():
    state = MachineState(slam_pose=SensorPose.identity(), boom_deg=0.0)
    with pytest.raises(ValueError):
        place_boom_points(np.zeros((4, 2)), _identity_chain(), state)


def test_from_tum_row_reads_the_quaternion_order_the_trajectories_use():
    """TUM is [x y z qx qy qz qw]; a 180 degree yaw is q = (0, 0, 1, 0)."""
    pose = SensorPose.from_tum_row([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
    turned = np.array([[1.0, 0.0, 0.0]])
    assert pose.rotation @ turned[0] == pytest.approx(np.array([-1.0, 0.0, 0.0]), abs=1e-12)


def test_from_tum_row_rejects_a_row_that_still_has_its_timestamp():
    with pytest.raises(ValueError):
        SensorPose.from_tum_row([123.456, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
