#!/usr/bin/env python3
# Did the bag actually catch every scan? Answer it from the bag, not from a rate meter.
#
# `ros2 topic hz` is not an answer here: on this machine it under-reports a healthy 640 Hz
# IMU as 432 Hz, and it measures its own subscriber rather than the recording. The bag's
# timestamps are what the estimator will actually be fed, so they are the only honest
# record. A median gap at the nominal period with a much larger maximum means whole frames
# were dropped - measured on this rig at 0.100 s median against 0.311 s maximum.
#
# It reads sqlite directly instead of the rosbag2 python API because a field bag carries
# custom types (msg_gps_interface, msg_excavator_kine_interface) that the API insists on
# resolving before it will open the file. Timestamps need no type at all.

import glob
import os
import sqlite3
import sys


def collect(bag_dir):
    stamps = {}
    for db in sorted(glob.glob(os.path.join(bag_dir, "*.db3"))):
        con = sqlite3.connect(db)
        try:
            names = {tid: name for tid, name in con.execute("SELECT id, name FROM topics")}
            for tid, ts in con.execute("SELECT topic_id, timestamp FROM messages"):
                stamps.setdefault(names[tid], []).append(ts)
        finally:
            con.close()
    for ts in stamps.values():
        ts.sort()
    return stamps


def main():
    if len(sys.argv) < 2:
        print("usage: bag_timing.py <bag_dir> [topic_substring ...]")
        return 2

    bag_dir = sys.argv[1]
    wanted = sys.argv[2:]

    stamps = collect(bag_dir)
    if not stamps:
        print("no messages found in", bag_dir)
        return 1

    print("%-42s %6s %8s %8s %9s %9s" % ("topic", "n", "span_s", "rate", "gap_med", "gap_max"))
    for name in sorted(stamps):
        if wanted and not any(w in name for w in wanted):
            continue
        ts = stamps[name]
        if len(ts) < 2:
            print("%-42s %6d %8s" % (name, len(ts), "-"))
            continue
        span = (ts[-1] - ts[0]) / 1e9
        gaps = sorted((b - a) / 1e9 for a, b in zip(ts, ts[1:]))
        print("%-42s %6d %8.3f %8.3f %9.4f %9.4f"
              % (name, len(ts), span, (len(ts) - 1) / span, gaps[len(gaps) // 2], gaps[-1]))

    size = sum(os.path.getsize(f) for f in glob.glob(os.path.join(bag_dir, "*.db3")))
    first = min(t[0] for t in stamps.values())
    last = max(t[-1] for t in stamps.values())
    duration = (last - first) / 1e9
    print("\n%.1f MB over %.1f s -> %.2f MB/s -> %.1f GB per 10 min"
          % (size / 1e6, duration, size / 1e6 / duration, size / 1e6 / duration * 0.6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
