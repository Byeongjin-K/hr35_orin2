#!/usr/bin/env python3
"""Turn a GLIM run's submap dump into a map file that knows where on Earth it is.

  python3 scripts/export_glim_map.py \
    --dump /home/kimm/data/ulw_slam_runs/<name>/slam_offline \
    --datum 37.239,127.083,61.4 --origin-enu 0,0,0 --yaw-deg 0 \
    --out /home/kimm/data/maps/<name>.npz

The anchor arguments are taken, not derived: gnss_anchor.compute_anchor is what turns a
GNSS fix and a heading into origin_enu and yaw, and keeping that out of here leaves this
script with one job. Points stay in the map's own local metres - the datum lives in the
frame, which is the whole point of the format.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excavator_slam.glim_dump import dump_points_in_map  # noqa: E402
from excavator_slam.map_export import Datum, MapFrame, save_map  # noqa: E402


def triple(text):
    values = [float(part) for part in text.split(",")]
    if len(values) != 3:
        raise argparse.ArgumentTypeError(f"expected three comma-separated numbers, got {text}")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", required=True,
                        help="GLIM output directory holding the numbered submap dirs")
    parser.add_argument("--datum", required=True, type=triple, help="lat,lon,alt of the site datum")
    parser.add_argument("--origin-enu", required=True, type=triple,
                        help="where the map origin sits in the datum's ENU, in metres")
    parser.add_argument("--yaw-deg", required=True, type=float,
                        help="rotation from map frame to ENU, about up")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    points = dump_points_in_map(args.dump)
    frame = MapFrame(datum=Datum(*args.datum),
                     origin_enu=tuple(args.origin_enu),
                     yaw_rad=float(np.radians(args.yaw_deg)))

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    save_map(args.out, points, frame)

    span = points.max(axis=0) - points.min(axis=0)
    print(f"EXPORTED {args.out}")
    print(f"  points {len(points)}  span_m {np.round(span, 2).tolist()}")
    print(f"  datum {frame.datum.as_tuple()}  origin_enu {frame.origin_enu}  "
          f"yaw_deg {args.yaw_deg}")


if __name__ == "__main__":
    main()
