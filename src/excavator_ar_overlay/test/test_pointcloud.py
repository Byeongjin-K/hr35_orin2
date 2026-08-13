"""Tests for PointCloud2 XYZ extraction.

The buffer is read with a hand-built structured dtype rather than a library, so
the field offsets, the non-return filter and the subsample all need pinning:
a wrong offset silently yields plausible-looking garbage.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from excavator_ar_overlay.pointcloud import extract_xyz

# Matches the live Ouster layout: x,y,z at 0/4/8, intensity at 16, step 48.
POINT_STEP = 48


def make_cloud(points, extra_fields=True, point_step=POINT_STEP):
    points = np.asarray(points, dtype=np.float32)
    n = points.shape[0]
    buf = bytearray(n * point_step)
    for i, (x, y, z) in enumerate(points):
        base = i * point_step
        buf[base : base + 12] = np.array([x, y, z], dtype="<f4").tobytes()
        if extra_fields:
            buf[base + 16 : base + 20] = np.array([i], dtype="<f4").tobytes()

    fields = [
        SimpleNamespace(name="x", offset=0),
        SimpleNamespace(name="y", offset=4),
        SimpleNamespace(name="z", offset=8),
    ]
    if extra_fields:
        fields += [
            SimpleNamespace(name="intensity", offset=16),
            SimpleNamespace(name="range", offset=32),
        ]
    return SimpleNamespace(
        fields=fields, point_step=point_step, width=n, height=1, data=bytes(buf)
    )


def test_reads_xyz_at_the_declared_offsets():
    pts = [(1.0, 2.0, 3.0), (-4.0, 5.0, -6.0)]
    out = extract_xyz(make_cloud(pts), 0)
    assert out.shape == (2, 3)
    assert np.allclose(out, pts)


def test_interleaved_extra_fields_do_not_corrupt_xyz():
    """A wrong itemsize would slide into the intensity/range bytes."""
    # from 1, not 0: (0,0,0) is the non-return sentinel and is dropped by design.
    pts = [(float(i), float(-i), float(i * 2)) for i in range(1, 21)]
    out = extract_xyz(make_cloud(pts), 0)
    assert np.allclose(out, pts)


def test_exact_zero_returns_are_dropped():
    """The Ouster emits (0,0,0) for a non-return; kept, they pile up at origin."""
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 2.0, 0.0)]
    out = extract_xyz(make_cloud(pts), 0)
    assert out.shape[0] == 2
    assert np.allclose(out, [(1.0, 0.0, 0.0), (0.0, 2.0, 0.0)])


def test_non_finite_points_are_dropped():
    pts = [(1.0, 1.0, 1.0), (np.nan, 0.0, 0.0), (np.inf, 1.0, 1.0), (2.0, 2.0, 2.0)]
    out = extract_xyz(make_cloud(pts), 0)
    assert out.shape[0] == 2
    assert np.isfinite(out).all()


def test_missing_xyz_fields_yield_empty_rather_than_raising():
    cloud = make_cloud([(1.0, 2.0, 3.0)])
    cloud.fields = [SimpleNamespace(name="intensity", offset=0)]
    out = extract_xyz(cloud, 0)
    assert out.shape == (0, 3)


def test_empty_cloud_is_handled():
    cloud = make_cloud([(1.0, 1.0, 1.0)])
    cloud.width = 0
    cloud.height = 0
    assert extract_xyz(cloud, 0).shape == (0, 3)


def test_subsample_respects_the_cap():
    pts = [(float(i + 1), 0.0, 0.0) for i in range(1000)]
    out = extract_xyz(make_cloud(pts), 100)
    assert out.shape[0] <= 100


def test_subsample_strides_instead_of_truncating():
    """Striding keeps the angular spread; truncation would clip a whole sector."""
    pts = [(float(i + 1), 0.0, 0.0) for i in range(1000)]
    out = extract_xyz(make_cloud(pts), 100)
    assert out[:, 0].max() > 900.0


def test_zero_cap_disables_subsampling():
    pts = [(float(i + 1), 0.0, 0.0) for i in range(500)]
    assert extract_xyz(make_cloud(pts), 0).shape[0] == 500


def test_organized_cloud_uses_width_times_height():
    pts = [(float(i + 1), 1.0, 1.0) for i in range(12)]
    cloud = make_cloud(pts)
    cloud.width, cloud.height = 4, 3
    assert extract_xyz(cloud, 0).shape[0] == 12
