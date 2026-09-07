#!/usr/bin/env python3
"""Turn cached map-frame windows into world submaps through the deployed anchor.

Two modes.

--sweep prints, for each heading/swing convention, how badly ONE window disagrees
with itself when it is split in time. This is needed because the convention is not
knowable a priori: the upstream GNSS node publishes a mirrored heading whose inverse
has two candidates exactly 180 degrees apart, and the swing sign was retuned when the
voxeliser moved from the heading-derived joint_swing to the physical encoder. A wrong
convention shows up as the two time halves of a single window disagreeing about the
same ground, because the cab swings between them - so the data picks the convention
instead of a guess doing it. The same trick resolved the same ambiguity in
gridmap-shake/gridmap_diag/replay_global_map.py.

The sweep is only informative if the cab actually swings inside the window, so the
swing excursion is printed next to the residuals; a couple of degrees means the test
is blind and the verdict should not be trusted.

Without --sweep it writes the world-frame submaps for the chosen convention.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excavator_slam.gnss_anchor import (  # noqa: E402
    AnchorParams,
    cab_heading_from_published,
    compute_anchor,
    enu_from_llh,
    map_to_world,
)
from excavator_slam.revisit_metric import revisit_consistency  # noqa: E402


def interpolate_angle(t, samples_t, samples_deg):
    """Interpolate a bearing without letting it jump at the wrap."""
    radians = np.radians(samples_deg)
    sin = np.interp(t, samples_t, np.sin(radians))
    cos = np.interp(t, samples_t, np.cos(radians))
    return np.degrees(np.arctan2(sin, cos))


def wrap180(degrees):
    """Fold an angle difference into [-180, 180) so a wrap does not look like a swing."""
    return (np.asarray(degrees, float) + 180.0) % 360.0 - 180.0


def crop_map_frame(points, crop):
    """Keep the terrain, drop the machine, in the gravity-aligned map frame.

    Decided by measurement on window A of the 1104 bag, split in time (crop_study):
    the HEIGHT BAND is what matters - replacing |z| <= 5 m with -2..+1 m takes the
    median height disagreement from 0.309 m to 0.211 m and p90 from 1.548 m to
    0.855 m - because the boom, arm and bucket sit above the terrain and sweep with
    the cab. Pushing the NEAR crop out instead makes it monotonically worse (0.211 at
    3 m, 0.260 at 5 m, 0.335 at 8 m, 0.362 at 10 m), so the near field is not the
    contaminant: range only costs density (14.8 -> 2.3 points per cell) and lets any
    attitude error grow linearly with distance. Whatever crop is used here must be
    used for SLAM too, or the comparison is rigged.
    """
    min_r, max_r, z_lo, z_hi = crop
    radius = np.hypot(points[:, 0], points[:, 1])
    keep = ((radius >= min_r) & (radius <= max_r)
            & (points[:, 2] >= z_lo) & (points[:, 2] <= z_hi))
    return points[keep]


def frame_slices(counts):
    edges = np.concatenate([[0], np.cumsum(counts)])
    return [slice(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:])]


def to_world(cache, name, params, mirrored, frame_filter=None, crop=None):
    """Anchor every frame of a window and stack the result in world ENU."""
    points = cache["points_" + name]
    times = cache["t_" + name]
    slices = frame_slices(cache["counts_" + name])

    gps = cache["gps"]
    swing = cache["swing"]
    datum = (float(gps[0, 1]), float(gps[0, 2]), float(gps[0, 3]))

    latitude = np.interp(times, gps[:, 0], gps[:, 1])
    longitude = np.interp(times, gps[:, 0], gps[:, 2])
    altitude = np.interp(times, gps[:, 0], gps[:, 3])
    heading = interpolate_angle(times, gps[:, 0], gps[:, 4])
    swing_deg = np.interp(times, swing[:, 0], swing[:, 1])

    out = []
    for index, span in enumerate(slices):
        if frame_filter is not None and not frame_filter(index, times[index]):
            continue
        cab = float(cab_heading_from_published(heading[index], mirrored))
        antenna = enu_from_llh(latitude[index], longitude[index], altitude[index], datum)
        origin, yaw = compute_anchor(antenna, cab, float(swing_deg[index]), params)
        frame = points[span].astype(float)
        if crop is not None:
            frame = crop_map_frame(frame, crop)
        if frame.shape[0] == 0:
            continue
        out.append(map_to_world(frame, origin, yaw))
    if not out:
        raise SystemExit("no frames selected in window " + name)
    return np.concatenate(out, axis=0), swing_deg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--window", action="append", required=True)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--mirrored", dest="mirrored", action="store_true", default=False)
    parser.add_argument("--swing-sign", type=float, default=-1.0)
    parser.add_argument("--heading-offset-deg", type=float, default=-4.6135)
    parser.add_argument("--cell-m", type=float, default=0.15)
    parser.add_argument("--min-range-m", type=float, default=3.0)
    parser.add_argument("--max-range-m", type=float, default=20.0)
    parser.add_argument("--z-low-m", type=float, default=-2.0)
    parser.add_argument("--z-high-m", type=float, default=1.0)
    parser.add_argument("--compare", action="store_true",
                        help="anchor two windows and report their revisit consistency")
    parser.add_argument("--out-prefix")
    args = parser.parse_args()

    cache = np.load(args.cache, allow_pickle=True)
    print("cloud frame_id", cache["cloud_frame_id"], "crop", cache["crop"])

    if args.sweep:
        name = args.window[0]
        times = cache["t_" + name]
        midpoint = 0.5 * (times[0] + times[-1])
        swing_all = np.interp(times, cache["swing"][:, 0], cache["swing"][:, 1])
        print("window", name, "frames", len(times),
              "span %.1f-%.1f s" % (times[0], times[-1]),
              "swing %.1f..%.1f deg (excursion %.1f)"
              % (swing_all.min(), swing_all.max(), swing_all.max() - swing_all.min()))
        heading = interpolate_angle(times, cache["gps"][:, 0], cache["gps"][:, 4])
        print()
        print("The undercarriage does not turn while the cab swings, so the convention that")
        print("keeps the undercarriage bearing constant across a %.0f deg swing is the right"
              % (swing_all.max() - swing_all.min()))
        print("one. Terrain self-disagreement is the second opinion.")
        print()
        print("mirrored  swing_sign  under_ptp  under_std  overlap  dz_median  dz_p90   rms0")
        for mirrored in (False, True):
            for sign in (-1.0, 1.0):
                params = AnchorParams(swing_to_heading_sign=sign,
                                      heading_offset_deg=args.heading_offset_deg)
                cab = np.asarray(cab_heading_from_published(heading, mirrored), float)
                under = cab - sign * swing_all + args.heading_offset_deg
                spread = wrap180(under - np.median(under))
                early, _ = to_world(cache, name, params, mirrored,
                                    lambda i, t: t < midpoint)
                late, _ = to_world(cache, name, params, mirrored,
                                   lambda i, t: t >= midpoint)
                try:
                    r = revisit_consistency(early, late, cell_m=args.cell_m)
                    tail = "%-8d %-10.4f %-8.4f %.4f" % (
                        r["overlap_cells"], r["dz_median_m"], r["dz_p90_m"],
                        r["residual_rms_before_m"])
                except ValueError as error:
                    tail = "rejected: " + str(error)[:48]
                print("%-9s %-11.0f %-10.1f %-10.2f %s"
                      % (mirrored, sign, spread.max() - spread.min(), spread.std(), tail))
        return

    params = AnchorParams(swing_to_heading_sign=args.swing_sign,
                          heading_offset_deg=args.heading_offset_deg)
    crop = (args.min_range_m, args.max_range_m, args.z_low_m, args.z_high_m)

    if args.compare:
        if len(args.window) != 2:
            raise SystemExit("--compare needs exactly two --window arguments")
        first_name, revisit_name = args.window
        first, _ = to_world(cache, first_name, params, args.mirrored, crop=crop)
        revisit, _ = to_world(cache, revisit_name, params, args.mirrored, crop=crop)
        print("crop", crop, "first", first.shape[0], "revisit", revisit.shape[0])
        result = revisit_consistency(first, revisit, cell_m=args.cell_m)
        gain = ((result["residual_rms_before_m"] - result["residual_rms_m"])
                / result["residual_rms_before_m"])
        for key in sorted(result):
            print("  %-22s %s" % (key, result[key]))
        print("  %-22s %.3f" % ("residual_gain", gain))
        print("BASELINE_COMPARE_DONE")
        return

    for name in args.window:
        world, _ = to_world(cache, name, params, args.mirrored, crop=crop)
        print("window", name, "world points", world.shape[0],
              "extent %.1f x %.1f m" % (world[:, 0].ptp(), world[:, 1].ptp()),
              "z %.2f..%.2f" % (world[:, 2].min(), world[:, 2].max()))
        if args.out_prefix:
            out = args.out_prefix + name + ".npy"
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            np.save(out, world.astype(np.float32))
            print("wrote", out)
    print("ANCHOR_DONE")


if __name__ == "__main__":
    main()
