#!/usr/bin/env python3
"""Rewrite a recording onto the host clock with ONE constant offset.

Why this exists
---------------
These recordings predate the driver change that made the boom LiDAR stamp on the ROS
clock (robot_ws f08b848, 2026-08). Their metadata says timestamp_mode
TIME_FROM_INTERNAL_OSC, so cloud and IMU headers carry the sensor's uptime (~18300 s)
while everything else, GNSS included, carries host epoch (~1.76e9 s). A SLAM tool
reading such a bag processes exactly one scan and then discards the rest as ancient.

Why ONE offset rather than per-message receive time
--------------------------------------------------
The obvious fix - stamp every message with the time the bag received it - is wrong,
and measurably so. Receive time includes each topic's own buffering: on this recording
the median (receive - header) is 1762215141.0164 s for points but 1762215140.8698 s
for the IMU, so restamping each message by its own receive time silently shifts the
clouds 0.1466 s LATER than the IMU. GLIM reported exactly that damage - "imu_rate
stamp does not cover the scan duration range", and IMU-aided rotation error 2.779 deg
against 1.456 deg without the IMU, i.e. the IMU made things worse.

So a single constant offset is measured once from the promptest topic (the IMU, whose
small messages queue least) and added to every header. Relative timing between sensors
is then preserved exactly, which is the only property inertial fusion actually needs,
while absolute time still lands on the host clock.

Arithmetic is integer nanoseconds throughout: 1.76e9 seconds at nanosecond resolution
needs 19 significant digits and does not survive float64.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import rosbag2_py
from rclpy.serialization import deserialize_message, serialize_message
from rosidl_runtime_py.utilities import get_message

DEFAULT_TOPICS = ("/lidar_boom/points", "/lidar_boom/imu")
DEFAULT_REFERENCE = "/lidar_boom/imu"


def _reader(bag, topics):
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=bag, storage_id="sqlite3"),
                rosbag2_py.ConverterOptions("", ""))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    missing = [t for t in topics if t not in types]
    if missing:
        raise SystemExit("bag is missing " + ", ".join(missing))
    reader.set_filter(rosbag2_py.StorageFilter(topics=list(topics)))
    return reader, types


def measure_offset_ns(bag, reference_topic, sample):
    """Smallest (receive - header) on the reference topic, in nanoseconds.

    The minimum rather than the mean: every sample is inflated by queueing, so the
    smallest one is the closest to the true clock difference.
    """
    reader, types = _reader(bag, [reference_topic])
    message_class = get_message(types[reference_topic])
    best = None
    seen = 0
    while reader.has_next() and seen < sample:
        _, data, stamp = reader.read_next()
        header = deserialize_message(data, message_class).header.stamp
        delta = stamp - (header.sec * 1_000_000_000 + header.nanosec)
        best = delta if best is None else min(best, delta)
        seen += 1
    if best is None:
        raise SystemExit("no messages on " + reference_topic + " to measure the offset")
    return best, seen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--topic", action="append", default=None)
    parser.add_argument("--offset-from", default=DEFAULT_REFERENCE,
                        help="topic whose arrival lag defines the single offset")
    parser.add_argument("--offset-sample", type=int, default=20000)
    parser.add_argument("--start-s", type=float, default=0.0,
                        help="seconds after the bag's first message")
    parser.add_argument("--end-s", type=float, default=float("inf"))
    args = parser.parse_args()

    topics = tuple(args.topic) if args.topic else DEFAULT_TOPICS
    out = Path(args.out)
    if out.exists():
        raise SystemExit(str(out) + " already exists; remove it or choose another path")

    offset_ns, sampled = measure_offset_ns(args.bag, args.offset_from, args.offset_sample)
    print("offset measured on %s over %d messages: %.9f s"
          % (args.offset_from, sampled, offset_ns * 1e-9))

    reader, types = _reader(args.bag, topics)
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=str(out), storage_id="sqlite3"),
                rosbag2_py.ConverterOptions("", ""))
    for topic in topics:
        writer.create_topic(rosbag2_py.TopicMetadata(
            name=topic, type=types[topic], serialization_format="cdr"))

    classes = {topic: get_message(types[topic]) for topic in topics}
    first = None
    written = {topic: 0 for topic in topics}

    while reader.has_next():
        topic, data, stamp = reader.read_next()
        if first is None:
            first = stamp
        elapsed = (stamp - first) * 1e-9
        if elapsed < args.start_s:
            continue
        if elapsed > args.end_s:
            break

        message = deserialize_message(data, classes[topic])
        header = message.header.stamp
        shifted = header.sec * 1_000_000_000 + header.nanosec + offset_ns
        header.sec = shifted // 1_000_000_000
        header.nanosec = shifted % 1_000_000_000
        # The bag time is set to the same value so a reader that orders by storage time
        # sees the same sequence the headers describe.
        writer.write(topic, serialize_message(message), shifted)
        written[topic] += 1

    del writer
    for topic in topics:
        print("wrote", written[topic], topic)
    print("RESTAMP_OFFSET_NS", offset_ns)
    print("RESTAMP_DONE", out)


if __name__ == "__main__":
    main()
