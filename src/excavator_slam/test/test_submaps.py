"""One crop, used by both sides of the comparison.

The baseline and SLAM do not live in the same frame. The deployed anchor produces
points in a gravity-aligned map frame whose origin is the swing axis on the ground,
so a plain z band means "height above ground" there. A LiDAR-odometry map frame is
whatever pose the sensor happened to hold at the first scan - on this machine the
boom sensor is tilted about 45 degrees and its height datum is arbitrary - so the
same numeric band would carve a different volume, and the comparison would be
measuring the crop instead of the mapping.

So the crop is machine-relative on both sides and its height band is taken relative
to the local ground level rather than to the frame's zero. The datum-shift test below
is the one that matters: the same terrain, moved bodily in z, has to survive
identically. If it does not, no baseline-versus-SLAM number means anything.
"""

import numpy as np
import pytest

from excavator_slam.submaps import crop_around_machine


def _scene(rng, z_offset=0.0, n_ring=6000):
    """Ground annulus, the machine itself, a boom arm overhead, and distant ground."""
    angle = rng.uniform(0.0, 2.0 * np.pi, n_ring)
    radius = rng.uniform(4.0, 18.0, n_ring)
    ground = np.column_stack([radius * np.cos(angle), radius * np.sin(angle),
                              rng.normal(0.0, 0.02, n_ring)])

    mast_angle = rng.uniform(0.0, 2.0 * np.pi, 800)
    mast_radius = rng.uniform(0.2, 2.0, 800)
    mast = np.column_stack([mast_radius * np.cos(mast_angle),
                            mast_radius * np.sin(mast_angle),
                            rng.uniform(0.0, 3.0, 800)])

    boom = np.column_stack([rng.uniform(5.0, 8.0, 900), rng.uniform(-0.4, 0.4, 900),
                            rng.uniform(2.0, 4.0, 900)])

    far_angle = rng.uniform(0.0, 2.0 * np.pi, 1200)
    far_radius = rng.uniform(22.0, 30.0, 1200)
    far = np.column_stack([far_radius * np.cos(far_angle), far_radius * np.sin(far_angle),
                           rng.normal(0.0, 0.02, 1200)])

    scene = np.vstack([ground, mast, boom, far])
    scene[:, 2] += z_offset
    return scene, ground.shape[0]


CROP = dict(min_range_m=3.0, max_range_m=20.0, z_low_m=-2.0, z_high_m=1.0)


def test_keeps_the_terrain_annulus_and_drops_the_machine():
    scene, n_ground = _scene(np.random.default_rng(0))
    kept = crop_around_machine(scene, (0.0, 0.0), **CROP)
    radius = np.hypot(kept[:, 0], kept[:, 1])
    assert radius.min() >= 3.0
    assert radius.max() <= 20.0
    assert kept.shape[0] > 0.9 * n_ground
    assert kept.shape[0] < 1.1 * n_ground


def test_the_height_band_follows_the_ground_not_the_frame_datum():
    scene_low, _ = _scene(np.random.default_rng(0), z_offset=0.0)
    scene_high, _ = _scene(np.random.default_rng(0), z_offset=37.25)
    kept_low = crop_around_machine(scene_low, (0.0, 0.0), **CROP)
    kept_high = crop_around_machine(scene_high, (0.0, 0.0), **CROP)
    assert kept_high.shape[0] == kept_low.shape[0]
    assert kept_high[:, 2] - 37.25 == pytest.approx(kept_low[:, 2], abs=1e-9)


def test_the_crop_follows_the_machine_rather_than_the_origin():
    scene, n_ground = _scene(np.random.default_rng(1))
    moved = scene + np.array([120.0, -80.0, 0.0])
    kept = crop_around_machine(moved, (120.0, -80.0), **CROP)
    assert kept.shape[0] > 0.9 * n_ground


def test_a_frame_with_nothing_in_the_annulus_yields_no_points():
    rng = np.random.default_rng(2)
    only_close = np.column_stack([rng.uniform(-1.0, 1.0, 500), rng.uniform(-1.0, 1.0, 500),
                                  rng.uniform(0.0, 2.0, 500)])
    kept = crop_around_machine(only_close, (0.0, 0.0), **CROP)
    assert kept.shape == (0, 3)
