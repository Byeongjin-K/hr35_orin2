#!/usr/bin/env python3
"""Score two world submaps on a FIXED search grid and print one comparable row set.

Why this exists as a script rather than a scratch loop: the 2026-09-09 comparison that
produced the project's headline numbers lived in an ad-hoc file under /tmp, and when
/tmp was cleared the recipe went with it - the saved .npy artifacts next to it were
from a different window pair, so the numbers in the handover could not be reproduced
without rebuilding the whole measurement from the run log. The recipe belongs in the
package.

The one non-obvious fact this encodes: residual_rms_before_m is NOT a property of the
two clouds alone. It is evaluated on the reference cells that survive erosion by the
search margin, and that margin grows with both search_radius_m and yaw_range_deg, so
the same pair of clouds scores 0.222 at r=0.3 and 0.186 at r=1.0. Comparing a tuning
run against a control therefore requires the SAME grid on both, which is why the grid
is a constant here instead of an argument.

--floor exists because the raw scores are not comparable across runs on their own. The
floor row splits ONE pass in half at random and scores it against itself, so it carries
that run's point density and its own within-window pose jitter and no revisit error at
all. Measured on the control, the floor is rms0 0.0719 / dz_median 0.0650 - a third of
what the control scores across the 62 s gap, and high enough that a tuned run can read
BELOW the control's floor simply by jittering less. Compare each run's revisit score
with ITS OWN floor; the gap between them is the part the 62 s actually cost.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excavator_slam.revisit_metric import revisit_consistency  # noqa: E402

GRID = ((0.5, 0.0), (0.5, 2.0), (1.0, 0.0), (1.0, 2.0))
HEADLINE = (1.0, 0.0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first")
    parser.add_argument("revisit")
    parser.add_argument("--label", default="run")
    parser.add_argument("--cell-m", type=float, default=0.15)
    parser.add_argument("--floor", action="store_true",
                        help="also score a random half-split of the first pass against "
                             "itself, which is this run's own noise floor")
    args = parser.parse_args()

    first = np.load(args.first)
    revisit = np.load(args.revisit)
    print("%s: first %d pts, revisit %d pts" % (args.label, first.shape[0], revisit.shape[0]))
    print("  %-11s %8s %8s %8s %8s %8s %9s %6s %7s %8s"
          % ("r/yaw", "rms0", "dz_med", "dz_bias", "dz_p90", "nn", "horiz", "sat",
             "cells", "overlap"))

    for radius, yaw in GRID:
        try:
            result = revisit_consistency(first, revisit, cell_m=args.cell_m,
                                         search_radius_m=radius, yaw_range_deg=yaw)
        except ValueError as exc:
            print("  r=%.1f yaw=%.0f  rejected: %s" % (radius, yaw, exc))
            continue
        mark = " <-- headline" if (radius, yaw) == HEADLINE else ""
        print("  r=%.1f yaw=%.0f %8.4f %8.4f %+8.4f %8.4f %8.4f %9.4f %6s %7d %8d%s"
              % (radius, yaw, result["residual_rms_before_m"], result["dz_median_m"],
                 result["dz_bias_m"], result["dz_p90_m"], result["nn_median_m"],
                 result["horizontal_m"], result["saturated"], result["cost_cells"],
                 result["overlap_cells"], mark))

    if args.floor:
        order = np.random.default_rng(7).permutation(first.shape[0])
        half = first.shape[0] // 2
        radius, yaw = HEADLINE
        result = revisit_consistency(first[order[:half]], first[order[half:]],
                                     cell_m=args.cell_m, search_radius_m=radius,
                                     yaw_range_deg=yaw)
        print("  floor       %8.4f %8.4f %+8.4f %8.4f %8.4f %9.4f %6s %7d %8d  <-- own floor"
              % (result["residual_rms_before_m"], result["dz_median_m"],
                 result["dz_bias_m"], result["dz_p90_m"], result["nn_median_m"],
                 result["horizontal_m"], result["saturated"], result["cost_cells"],
                 result["overlap_cells"]))
    print("SCORE_REVISIT_DONE")


if __name__ == "__main__":
    main()
