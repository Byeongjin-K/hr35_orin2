#!/usr/bin/env python3
"""Build world submaps from a SLAM trajectory and score their revisit consistency.

The mirror image of anchor_submaps.py: same windows, same crop, same metric, only the
pose source differs. That is the whole experiment - if the two scripts differed in
anything but the pose source, the comparison would be measuring the difference between
the scripts.

Two frame facts drive the shape of this. A LiDAR-odometry map frame is wherever the
sensor was at the first scan, so on this boom-mounted sensor it is tilted far off
vertical and its height datum is arbitrary; the map is therefore gravity-aligned once,
globally, before anything is measured. And the crop is machine-relative with its height
band tied to the local ground, so it means the same thing here as it does in the
anchor's map frame.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from excavator_slam.revisit_metric import revisit_consistency  # noqa: E402
from excavator_slam.submaps import (  # noqa: E402
    crop_around_machine,
    gravity_rotation,
    quaternion_to_matrix,
)


def load_tum(path):
    """TUM trajectory: timestamp tx ty tz qx qy qz qw, one pose per line."""
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        rows.append([float(value) for value in parts[:8]])
    if not rows:
        raise SystemExit("no poses parsed from " + str(path))
    table = np.array(rows, dtype=float)
    return table[:, 0], table[:, 1:4], table[:, 4:8]


def join(frame_times, pose_times, tolerance_s):
    """Nearest pose per frame; -1 where nothing lands inside the tolerance."""
    order = np.argsort(pose_times)
    sorted_times = pose_times[order]
    slot = np.searchsorted(sorted_times, frame_times)
    best = np.full(frame_times.shape[0], -1, dtype=np.int64)
    for index, (t, position) in enumerate(zip(frame_times, slot)):
        candidates = [c for c in (position - 1, position) if 0 <= c < sorted_times.size]
        if not candidates:
            continue
        nearest = min(candidates, key=lambda c: abs(sorted_times[c] - t))
        if abs(sorted_times[nearest] - t) <= tolerance_s:
            best[index] = order[nearest]
    return best


def posed_frames(cache, name, pose_times, translations, quaternions, time_key, tolerance_s,
                 time_offset=0.0):
    """Every frame of a window, posed into the SLAM world frame."""
    points = cache["points_" + name]
    counts = cache["counts_" + name]
    edges = np.concatenate([[0], np.cumsum(counts)])
    frame_times = cache[time_key + name] + time_offset

    matched = join(frame_times, pose_times, tolerance_s)
    posed, machines = [], []
    for index in range(len(counts)):
        pose = matched[index]
        if pose < 0:
            continue
        rotation = quaternion_to_matrix(*quaternions[pose])
        translation = translations[pose]
        scan = points[edges[index]:edges[index + 1]].astype(float)
        posed.append(scan @ rotation.T + translation)
        machines.append(translation)
    return posed, machines, int((matched >= 0).sum()), len(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True, help="TUM file from the SLAM run")
    parser.add_argument("--cache", required=True, help="raw sensor-frame window cache")
    parser.add_argument("--window", action="append", required=True)
    parser.add_argument("--time-key",
                        choices=("auto", "header", "receive", "receive_abs"), default="auto")
    parser.add_argument("--cache-time-offset", type=float, default=0.0,
                        help="seconds to add to the cache's receive times; use the source "
                             "bag's first receive timestamp when the trajectory was built "
                             "from a restamped bag and therefore speaks absolute host time")
    parser.add_argument("--tolerance-s", type=float, default=0.05)
    parser.add_argument("--min-range-m", type=float, default=3.0)
    parser.add_argument("--max-range-m", type=float, default=20.0)
    parser.add_argument("--z-low-m", type=float, default=-2.0)
    parser.add_argument("--z-high-m", type=float, default=1.0)
    parser.add_argument("--cell-m", type=float, default=0.15)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--out-prefix")
    args = parser.parse_args()

    pose_times, translations, quaternions = load_tum(args.trajectory)
    cache = np.load(args.cache, allow_pickle=True)
    print("poses %d, span %.3f..%.3f" % (pose_times.size, pose_times.min(), pose_times.max()))

    # Which clock the trajectory speaks is a property of the SLAM tool's bag reader,
    # not something to assume: the cache carries both, so let the match rate decide.
    # Three candidates, because none of them is obviously right. The cache stores frame
    # times as seconds elapsed from the start of the source bag and, separately, the
    # sensor's own header stamps; a trajectory built from a RESTAMPED bag speaks absolute
    # host epoch and matches neither until the bag's start time is added back.
    keys = {"header": ("t_header_", 0.0),
            "receive": ("t_", 0.0),
            "receive_abs": ("t_", args.cache_time_offset)}
    if args.time_key == "auto":
        scored = {}
        for label, (prefix, offset) in keys.items():
            if prefix + args.window[0] not in cache:
                continue
            hits = join(cache[prefix + args.window[0]] + offset, pose_times, args.tolerance_s)
            scored[label] = int((hits >= 0).sum())
            print("  time key %-12s matches %d/%d"
                  % (label, scored[label], cache[prefix + args.window[0]].size))
        if not scored or max(scored.values()) == 0:
            raise SystemExit("no frame matched any pose on any clock; check the trajectory "
                             "and --cache-time-offset")
        chosen = max(scored, key=scored.get)
    else:
        chosen = args.time_key
    prefix, offset = keys[chosen]
    print("using the %s clock" % chosen)

    windows = {}
    for name in args.window:
        posed, machines, matched, total = posed_frames(
            cache, name, pose_times, translations, quaternions, prefix, args.tolerance_s,
            time_offset=offset)
        if not posed:
            raise SystemExit("window %s matched no poses" % name)
        windows[name] = (posed, machines)
        print("window %s: %d/%d frames posed" % (name, matched, total))

    # One rotation for the whole run, estimated on everything at once. Shared by every
    # window, it cannot make two windows agree with each other - it moves them together.
    everything = np.concatenate([scan for posed, _ in windows.values() for scan in posed])
    rotation = gravity_rotation(everything)
    tilt = np.degrees(np.arccos(np.clip(rotation[2, 2], -1.0, 1.0)))
    print("gravity alignment rotated the map by %.2f deg" % tilt)
    del everything

    submaps = {}
    for name, (posed, machines) in windows.items():
        kept = []
        for scan, machine in zip(posed, machines):
            world = scan @ rotation.T
            centre = rotation @ machine
            cropped = crop_around_machine(world, (centre[0], centre[1]),
                                          args.min_range_m, args.max_range_m,
                                          args.z_low_m, args.z_high_m)
            if cropped.shape[0]:
                kept.append(cropped)
        if not kept:
            raise SystemExit("window %s kept no points after cropping" % name)
        submaps[name] = np.concatenate(kept, axis=0)
        print("window %s: %d points after crop" % (name, submaps[name].shape[0]))
        if args.out_prefix:
            out = args.out_prefix + name + ".npy"
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            np.save(out, submaps[name].astype(np.float32))
            print("wrote", out)

    if args.compare:
        if len(args.window) != 2:
            raise SystemExit("--compare needs exactly two --window arguments")
        first, revisit = (submaps[name] for name in args.window)
        result = revisit_consistency(first, revisit, cell_m=args.cell_m)
        gain = ((result["residual_rms_before_m"] - result["residual_rms_m"])
                / result["residual_rms_before_m"])
        for key in sorted(result):
            print("  %-22s %s" % (key, result[key]))
        print("  %-22s %.3f" % ("residual_gain", gain))
    print("SLAM_SUBMAPS_DONE")


if __name__ == "__main__":
    main()
