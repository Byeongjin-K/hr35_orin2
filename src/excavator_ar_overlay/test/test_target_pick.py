"""Extracting the 3D half of a correspondence from a capture bundle."""

from __future__ import annotations

import math

import numpy as np
import pytest

from excavator_ar_overlay.target_pick import (
    find_target,
    frozen_transform_matrix,
    points_between_frames,
)

IDENTITY = {"translation": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, 0.0, 1.0]}


def yaw90(tx=0.0, ty=0.0, tz=0.0):
    half = math.sqrt(0.5)
    return {"translation": [tx, ty, tz], "rotation_xyzw": [0.0, 0.0, half, half]}


def ground_with_target(x=2.5, y=-1.0, ground_z=0.155, height=0.6):
    rng = np.random.default_rng(0)
    gx, gy = np.meshgrid(np.linspace(0, 8, 90), np.linspace(-4, 4, 90))
    ground = np.column_stack(
        [gx.ravel(), gy.ravel(), np.full(gx.size, ground_z)]
    )
    n = 300
    blob = np.column_stack([
        x + rng.normal(0, 0.05, n),
        y + rng.normal(0, 0.05, n),
        ground_z + rng.uniform(0.05, height, n),
    ])
    return np.vstack([ground, blob])


def test_translation_only_frame_change():
    source = {"translation": [1.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, 0.0, 1.0]}
    moved = points_between_frames(np.array([[1.0, 2.0, 3.0]]), source, IDENTITY)
    assert np.allclose(moved, [[2.0, 2.0, 3.0]])


def test_rotation_is_applied_when_frames_differ_in_yaw():
    """Source yawed +90 deg: its +x is the target frame's +y."""
    moved = points_between_frames(np.array([[1.0, 0.0, 0.0]]), yaw90(), IDENTITY)
    assert np.allclose(moved, [[0.0, 1.0, 0.0]], atol=1e-9)


def test_frozen_transform_matrix_round_trips_a_point():
    matrix = frozen_transform_matrix(yaw90(2.0, 0.0, 1.0))
    point = np.array([1.0, 0.0, 0.0, 1.0])
    assert np.allclose((matrix @ point)[:3], [2.0, 1.0, 1.0], atol=1e-9)


def test_finds_the_ground_contact_point_of_the_target():
    found = find_target(ground_with_target(), (2.5, -1.0))
    assert found is not None
    assert found["n_points"] >= 20
    assert found["base_xyz"][0] == pytest.approx(2.5, abs=0.05)
    assert found["base_xyz"][1] == pytest.approx(-1.0, abs=0.05)
    assert found["base_xyz"][2] == pytest.approx(0.155, abs=0.05)


def test_returns_none_when_only_ground_is_there():
    rng = np.random.default_rng(1)
    gx, gy = np.meshgrid(np.linspace(0, 8, 90), np.linspace(-4, 4, 90))
    ground = np.column_stack([gx.ravel(), gy.ravel(), np.full(gx.size, 0.155)])
    assert find_target(ground, (2.5, -1.0)) is None


def test_ignores_a_target_outside_the_search_radius():
    points = ground_with_target(x=6.0, y=2.0)
    assert find_target(points, (2.5, -1.0), search_radius_m=1.0) is None
