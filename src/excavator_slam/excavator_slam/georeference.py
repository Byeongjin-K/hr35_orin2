"""Letting GNSS hold the datum while the LiDAR estimate keeps the detail.

DELIBERATELY ROS-FREE, like the rest of this package's maths.

The two pose sources fail in opposite directions, and both failures were measured on the
same windows of the same bag. The deployed GNSS anchor holds height to +0.007 m but its
horizontal placement of a revisit is at least 1.658 m out. GLIM places the revisit within
0.399 m and halves the height residual (0.137 m against 0.321 m), yet its height wanders
+0.209 m across 62 s because no factor anchors z.

That is not a choice between them. A LiDAR-inertial estimator is precise over seconds and
drifts over minutes; a GNSS receiver is noisy over seconds and stable over minutes. So the
correction below keeps whichever source owns each timescale: the slow part of their
disagreement is attributed to SLAM drift and removed, the fast part is left alone because
there it is the GNSS that is wrong.

A global rigid alignment cannot do this job. It shifts every window by the same amount and
so leaves the drift BETWEEN two windows exactly as it was - which is precisely the quantity
dz_bias measures.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter

MIN_OVERLAP_S = 5.0


def _smooth_slow_part(values, dt_s, cutoff_s, spike_s):
    """The slowly varying part of a signal, with brief spikes rejected first.

    The median pass is not cosmetic. This recording contains an 85.75 m position jump
    inside a single 0.1 s sample and a run of ten consecutive 1.2 m samples; a Gaussian
    would smear such a spike across its whole width and inject the drift it is supposed
    to remove. A median of a few seconds deletes them outright and leaves genuine slow
    motion untouched.
    """
    spike_width = max(int(round(spike_s / dt_s)), 1)
    if spike_width % 2 == 0:
        spike_width += 1
    despiked = median_filter(values, size=spike_width, mode="nearest")
    sigma = max(cutoff_s / dt_s, 1e-6)
    # Normalised convolution: smooth the values and the weights with the same kernel and
    # divide. Neither obvious alternative works here, and both were measured. Zero padding
    # drags the ends toward zero and invents a correction exactly where the trajectory
    # starts and ends. Edge replication is worse: at a 30 s cutoff the kernel reaches
    # 1200 samples, so beyond the array it repeats ONE raw sample of a signal whose noise
    # is 1.4 m, handing that single sample about half the weight - which is what produced
    # a 1.47 m "drift" on a trajectory that had none. Dividing by the weight actually
    # present uses only real data and stays unbiased at the ends.
    total = gaussian_filter1d(despiked, sigma=sigma, mode="constant", cval=0.0)
    weight = gaussian_filter1d(np.ones_like(despiked), sigma=sigma, mode="constant", cval=0.0)
    return total / np.where(weight > 1e-12, weight, 1.0)


def align_altitude_drift(traj_t, traj_z, ref_t, ref_z, cutoff_s=30.0,
                         spike_s=3.0, min_overlap_s=MIN_OVERLAP_S):
    """Remove the slow part of the height disagreement between a trajectory and a reference.

    traj_t / traj_z  the estimated trajectory (SLAM), any sampling
    ref_t  / ref_z   the reference height (GNSS altitude), any sampling
    cutoff_s         timescale of the split. Below it the trajectory is trusted, above it
                     the reference is. 30 s suits a receiver whose vertical 1-sigma is
                     1.4 m: averaging that long leaves roughly 4 cm.

    Returns corrected heights, same shape as traj_z.
    """
    traj_t = np.asarray(traj_t, dtype=float)
    traj_z = np.asarray(traj_z, dtype=float)
    ref_t = np.asarray(ref_t, dtype=float)
    ref_z = np.asarray(ref_z, dtype=float)
    if traj_t.shape != traj_z.shape or traj_t.ndim != 1:
        raise ValueError("traj_t and traj_z must be matching 1-D arrays")
    if ref_t.shape != ref_z.shape or ref_t.ndim != 1:
        raise ValueError("ref_t and ref_z must be matching 1-D arrays")
    if traj_t.size < 3 or ref_t.size < 3:
        raise ValueError("both tracks need at least three samples")

    overlap = min(traj_t.max(), ref_t.max()) - max(traj_t.min(), ref_t.min())
    if overlap < min_overlap_s:
        raise ValueError(
            "the trajectory and the reference overlap for only %.1f s; at least %.1f s "
            "are needed before a drift can be separated from an offset"
            % (max(overlap, 0.0), min_overlap_s))

    order = np.argsort(ref_t)
    reference_here = np.interp(traj_t, ref_t[order], ref_z[order])

    dt = float(np.median(np.diff(traj_t)))
    if not np.isfinite(dt) or dt <= 0.0:
        raise ValueError("the trajectory timestamps are not increasing")

    disagreement = traj_z - reference_here
    return traj_z - _smooth_slow_part(disagreement, dt, cutoff_s, spike_s)
