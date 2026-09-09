#!/usr/bin/env python3
"""Put a SLAM trajectory onto the GNSS height datum without giving up its detail.

Reads a TUM trajectory and a GNSS track, removes the slow part of their height
disagreement, and writes a new TUM file. Rotation and horizontal position are untouched:
the measured gap between the two candidates is vertical, and correcting more than what was
measured would be guessing.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excavator_slam.georeference import align_altitude_drift  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True, help="TUM in")
    parser.add_argument("--gnss-csv", required=True,
                        help="columns t (absolute seconds) and alt")
    parser.add_argument("--out", required=True, help="TUM out")
    parser.add_argument("--cutoff-s", type=float, default=30.0)
    args = parser.parse_args()

    traj = np.loadtxt(args.trajectory)
    rows = list(csv.DictReader(open(args.gnss_csv)))
    ref_t = np.array([float(r["t"]) for r in rows])
    ref_z = np.array([float(r["alt"]) for r in rows])

    fixed_z = align_altitude_drift(traj[:, 0], traj[:, 3], ref_t, ref_z,
                                   cutoff_s=args.cutoff_s)
    correction = fixed_z - traj[:, 3]
    print("poses %d, span %.1f s" % (traj.shape[0], traj[-1, 0] - traj[0, 0]))
    print("correction: median %+.3f m, std %.3f m, range %+.3f..%+.3f m"
          % (np.median(correction), np.std(correction), correction.min(), correction.max()))
    print("slow component removed over the record: %+.3f m"
          % (correction[-1] - correction[0]))

    out = traj.copy()
    out[:, 3] = fixed_z
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(args.out, out, fmt="%.9f " + " ".join(["%.6f"] * 7))
    print("wrote", args.out)
    print("GEOREF_DONE")


if __name__ == "__main__":
    main()
