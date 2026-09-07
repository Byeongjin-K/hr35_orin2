#!/usr/bin/env python3
"""Rewrite a recording so every message carries one clock: the bag's receive time.

Why this exists
---------------
These recordings predate the driver change that made the boom LiDAR stamp on the ROS
clock (robot_ws f08b848, 2026-08). Their metadata says timestamp_mode
TIME_FROM_INTERNAL_OSC, so the cloud and IMU headers carry the sensor's uptime -
about 18300 s - while everything else in the bag, GNSS included, carries host epoch,
about 1.76e9 s. Nothing in the recording reconciles the two.

That is fatal for a SLAM tool reading the bag directly. MOLA installs its callback on
the right topic and then processes exactly ONE scan out of hundreds: once the first
host-time observation arrives, every later LiDAR scan looks about 1.76 billion seconds
stale and is dropped. The measured evidence is its own timing report - onLidar called
once, onNewObservation called 315 times, zero poses written.

So the messages are re-stamped onto the bag receive time, which is the only clock the
LiDAR chain and the GNSS ever shared in these recordings, and which is also the clock
the submap caches are keyed on. Points keep their per-point 't' offsets, which are
relative to the frame and therefore unaffected.

Writing a window rather than the whole recording is deliberate: it keeps the rewritten
bag to a few GB and, just as importantly, cuts the entry count a SLAM tool must walk
from half a million messages to a few thousand.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import rosbag2_py
from rclpy.serialization import deserialize_message, serialize_message
from rosidl_runtime_py.utilities import get_message

DEFAULT_TOPICS = ("/lidar_boom/points", "/lidar_boom/imu")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--topic", action="append", default=None)
    parser.add_argument("--start-s", type=float, default=0.0,
                        help="seconds after the bag's first message")
    parser.add_argument("--end-s", type=float, default=float("inf"))
    args = parser.parse_args()

    topics = tuple(args.topic) if args.topic else DEFAULT_TOPICS
    out = Path(args.out)
    if out.exists():
        raise SystemExit(str(out) + " already exists; remove it or choose another path")

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=args.bag, storage_id="sqlite3"),
                rosbag2_py.ConverterOptions("", ""))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    missing = [t for t in topics if t not in types]
    if missing:
        raise SystemExit("bag is missing " + ", ".join(missing))
    reader.set_filter(rosbag2_py.StorageFilter(topics=list(topics)))

    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(out), storage_id="sqlite3"),
                rosbag2_py.ConverterOptions("", ""))
    for topic in topics:
        writer.create_topic(rosbag2_py.TopicMetadata(
            name=topic, type=types[topic], serialization_format="cdr"))

    classes = {topic: get_message(types[topic]) for topic in topics}
    first = None
    written = {topic: 0 for topic in topics}
    shifts = []

    while reader.has_next():
        topic, data, stamp = reader.read_next()
        seconds = stamp * 1e-9
        if first is None:
            first = seconds
        elapsed = seconds - first
        if elapsed < args.start_s:
            continue
        if elapsed > args.end_s:
            break

        message = deserialize_message(data, classes[topic])
        header = message.header.stamp
        shifts.append(seconds - (header.sec + header.nanosec * 1e-9))
        header.sec = int(stamp // 1_000_000_000)
        header.nanosec = int(stamp % 1_000_000_000)
        writer.write(topic, serialize_message(message), stamp)
        written[topic] += 1

    del writer
    for topic in topics:
        print("wrote", written[topic], topic)
    if shifts:
        shifts.sort()
        print("header shift applied: min %.3f median %.3f max %.3f s"
              % (shifts[0], shifts[len(shifts) // 2], shifts[-1]))
    print("RESTAMP_DONE", out)


if __name__ == "__main__":
    main()
