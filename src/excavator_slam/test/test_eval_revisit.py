"""Revisit-consistency metric: does a second visit of the same terrain land on the first?

The metric must be able to FAIL: an injected rigid offset between two samples of the
same synthetic site has to come back as that offset, and two independent samples with
no offset must not invent one.

About the numeric bounds. They are not the estimator's own output rounded up; they are
set where the two defects this metric already hit would be caught. A search that
re-bins the moved cloud per candidate (so the compared cell set moves with the shift)
produced 0.148-0.237 m of displacement on aligned passes, and gradient-weighted cells
produced 0.33-1.05 m; both blow the 0.08 m aligned bound below. The residual-gain
assertions are the structural half: on aligned passes the best shift removes only
3-8 percent of the height residual (there is nothing to remove), on a real 0.316 m
shift it removes 79-87 percent, so the 20 / 50 percent bounds sit in a gap of more
than a factor of ten.
"""

import numpy as np
import pytest

from excavator_slam.revisit_metric import revisit_consistency


def _site(rng, n=20000, extent=12.0):
    """Flat ground plus a ridge and a mound, so horizontal misalignment is observable."""
    xy = rng.uniform(-extent / 2, extent / 2, size=(n, 2))
    z = np.zeros(n)
    ridge = np.abs(xy[:, 0] - 2.0) < 0.3
    z[ridge] += 0.6
    r_mound = np.hypot(xy[:, 0] + 3.0, xy[:, 1] - 1.5)
    mound = r_mound < 1.2
    z[mound] += 0.4 * (1.2 - r_mound[mound])
    z += rng.normal(0.0, 0.01, n)
    return np.column_stack([xy, z])


def _gain(result):
    before = result["residual_rms_before_m"]
    return (before - result["residual_rms_m"]) / before


def test_aligned_revisit_does_not_invent_a_displacement():
    first = _site(np.random.default_rng(1))
    revisit = _site(np.random.default_rng(2))
    r = revisit_consistency(first, revisit, cell_m=0.15)
    assert r["overlap_cells"] > 1000
    assert r["cost_cells"] > 500
    assert r["horizontal_m"] < 0.08
    assert r["dz_median_m"] < 0.02
    assert abs(r["yaw_deg"]) < 0.5
    assert _gain(r) < 0.20


@pytest.mark.parametrize("seeds", [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)])
def test_aligned_revisit_stays_quiet_across_samples(seeds):
    first = _site(np.random.default_rng(seeds[0]))
    revisit = _site(np.random.default_rng(seeds[1]))
    r = revisit_consistency(first, revisit, cell_m=0.15)
    assert r["horizontal_m"] < 0.08
    assert _gain(r) < 0.20


def test_shifted_revisit_reports_the_injected_offset():
    first = _site(np.random.default_rng(1))
    revisit = _site(np.random.default_rng(2)) + np.array([0.30, 0.10, 0.04])
    r = revisit_consistency(first, revisit, cell_m=0.15)
    assert r["horizontal_m"] == pytest.approx(np.hypot(0.30, 0.10), abs=0.05)
    assert r["dz_median_m"] == pytest.approx(0.04, abs=0.015)
    assert r["dz_bias_m"] == pytest.approx(0.04, abs=0.015)
    assert _gain(r) > 0.50


def test_shift_is_signed_towards_undoing_the_offset():
    first = _site(np.random.default_rng(1))
    revisit = _site(np.random.default_rng(2)) + np.array([0.30, 0.10, 0.04])
    r = revisit_consistency(first, revisit, cell_m=0.15)
    dx, dy = r["shift_xy_m"]
    assert dx == pytest.approx(-0.30, abs=0.06)
    assert dy == pytest.approx(-0.10, abs=0.06)


def test_rejects_clouds_without_overlap():
    first = _site(np.random.default_rng(1))
    revisit = _site(np.random.default_rng(2)) + np.array([100.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="overlap"):
        revisit_consistency(first, revisit, cell_m=0.15)


def test_a_displacement_beyond_the_search_box_is_flagged_saturated():
    """An answer pinned against the search wall is a lower bound, not a measurement.

    On the real 1104 bag the baseline came back with both shift components at exactly
    the box limit and yaw exactly at its range end, which reads like a 1.69 m estimate
    but is really "at least 1.69 m". A caller that cannot tell the two apart will quote
    a saturated number as a result, so the metric has to say so itself.
    """
    first = _site(np.random.default_rng(1))
    revisit = _site(np.random.default_rng(2)) + np.array([2.5, 0.0, 0.0])
    r = revisit_consistency(first, revisit, cell_m=0.15, search_radius_m=1.0)
    assert r["saturated"] is True


def test_a_displacement_inside_the_search_box_is_not_flagged():
    first = _site(np.random.default_rng(1))
    revisit = _site(np.random.default_rng(2)) + np.array([0.30, 0.10, 0.04])
    r = revisit_consistency(first, revisit, cell_m=0.15, search_radius_m=1.0)
    assert r["saturated"] is False


def test_aligned_passes_are_not_flagged_saturated():
    first = _site(np.random.default_rng(1))
    revisit = _site(np.random.default_rng(2))
    r = revisit_consistency(first, revisit, cell_m=0.15, search_radius_m=1.0)
    assert r["saturated"] is False
