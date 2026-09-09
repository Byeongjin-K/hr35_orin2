"""Letting GNSS hold the datum while SLAM keeps the detail.

Measured on the stationary swing-revisit windows, the two candidates fail in opposite
directions: the GNSS anchor drifts 1.658 m horizontally (and that figure is only a lower
bound, the search hit its box) while holding height to +0.007 m, and GLIM holds shape far
better (height residual 0.137 m against 0.321 m, horizontal 0.399 m and converged) but its
height wanders +0.209 m across 62 s because nothing anchors its z.

Neither is a defect to pick between; they are the two halves of the same answer. A LiDAR
estimator is precise over seconds and drifts over minutes, a GNSS receiver is noisy over
seconds and stable over minutes. So the correction here removes only the SLOW part of the
disagreement between them.

The tests exist to stop the two ways this goes wrong. Doing nothing leaves the drift, and
snapping the trajectory onto GNSS imports its metre-scale noise and destroys the very
local precision SLAM was chosen for - so a naive traj_z - (traj_z - ref_z) = ref_z passes
no test below.
"""

import numpy as np
import pytest

from excavator_slam.georeference import align_altitude_drift

SPAN_S = 270.0
RATE_HZ = 10.0
GNSS_SIGMA_M = 1.4  # measured 1-sigma of the vertical channel in this recording


def _tracks(rng, drift_m=1.5, wiggle_m=0.10, wiggle_period_s=2.0):
    """A true height, a SLAM track that slowly drifts off it, and a noisy GNSS view of it."""
    t = np.arange(0.0, SPAN_S, 1.0 / RATE_HZ)
    true_z = 0.3 * np.sin(2.0 * np.pi * t / 120.0)
    wiggle = wiggle_m * np.sin(2.0 * np.pi * t / wiggle_period_s)
    drift = drift_m * (t / SPAN_S)
    slam_z = true_z + wiggle + drift
    gnss_z = true_z + rng.normal(0.0, GNSS_SIGMA_M, t.size)
    return t, true_z, wiggle, slam_z, gnss_z


def _window_offset(t, z, a0, a1, b0, b1):
    """How far apart two time windows sit in height - the quantity dz_bias measures."""
    a = (t >= a0) & (t < a1)
    b = (t >= b0) & (t < b1)
    return float(np.median(z[b]) - np.median(z[a]))


def test_slow_drift_between_two_windows_is_removed():
    rng = np.random.default_rng(0)
    t, true_z, _, slam_z, gnss_z = _tracks(rng)
    before = abs(_window_offset(t, slam_z - true_z, 16.0, 36.0, 78.0, 98.0))
    fixed = align_altitude_drift(t, slam_z, t, gnss_z, cutoff_s=30.0)
    after = abs(_window_offset(t, fixed - true_z, 16.0, 36.0, 78.0, 98.0))
    assert before > 0.08, "the fixture must inject a drift worth removing"
    # No correction can beat the floor set by averaging the reference: 1.4 m of white
    # noise smoothed over 30 s at 10 Hz leaves about 4 cm, and comparing two windows
    # doubles that in quadrature. The injected drift is therefore sized so that a real
    # reduction is visible well above that floor rather than buried in it.
    assert after < 0.3 * before


def test_the_fast_detail_survives():
    """The correction must not be a copy of GNSS: SLAM's own short-scale motion has to live."""
    rng = np.random.default_rng(1)
    t, true_z, wiggle, slam_z, gnss_z = _tracks(rng)
    fixed = align_altitude_drift(t, slam_z, t, gnss_z, cutoff_s=30.0)
    recovered = fixed - np.median(fixed)
    reference = (true_z + wiggle) - np.median(true_z + wiggle)
    assert np.corrcoef(recovered, reference)[0, 1] > 0.9


def test_gnss_noise_is_not_imported():
    rng = np.random.default_rng(2)
    t, _, _, slam_z, gnss_z = _tracks(rng)
    fixed = align_altitude_drift(t, slam_z, t, gnss_z, cutoff_s=30.0)
    correction = fixed - slam_z
    # Measured on the DIFFERENCE, not on the correction itself: a genuine drift correction
    # is large but smooth, while snapping onto the reference is small-mean but jagged, so
    # only the derivative separates them. Total magnitude would flag the drift as noise.
    assert np.std(np.diff(correction)) < 0.02 * np.std(np.diff(gnss_z))


def test_a_trajectory_already_on_the_datum_is_left_alone():
    rng = np.random.default_rng(3)
    t, true_z, wiggle, _, gnss_z = _tracks(rng, drift_m=0.0)
    slam_z = true_z + wiggle
    fixed = align_altitude_drift(t, slam_z, t, gnss_z, cutoff_s=30.0)
    correction = fixed - slam_z
    # With no drift to remove, whatever the correction still does is the reference's own
    # noise surviving the average. That floor belongs to the fixture, not to the code:
    # 1.4 m of white noise averaged over 30 s at 10 Hz leaves a few centimetres, and the
    # extreme of a smooth process over 2700 samples runs a couple of times its own spread.
    # Demanding better than the floor would be demanding the impossible; what is worth
    # asserting is that the correction sits AT the floor rather than at the raw noise
    # level, which a snap onto the reference misses by a factor of twenty.
    assert float(np.std(correction)) < 0.10 * GNSS_SIGMA_M
    assert float(np.max(np.abs(correction))) < 0.25 * GNSS_SIGMA_M


def test_reference_that_does_not_overlap_in_time_is_refused():
    rng = np.random.default_rng(4)
    t, _, _, slam_z, gnss_z = _tracks(rng)
    with pytest.raises(ValueError, match="overlap"):
        align_altitude_drift(t, slam_z, t + 10_000.0, gnss_z, cutoff_s=30.0)