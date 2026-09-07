#!/usr/bin/env python3
"""Cache the map-frame clouds and nav state of chosen bag windows.

This is the ONE expensive pass. Reading a 31 GB bag to pull a couple of 20 s windows
takes minutes, and the anchor convention that turns those clouds into a world map is
not settled in advance (the published heading is mirrored by an amount stationary data
cannot resolve, and the swing sign was retuned when the voxeliser moved off
joint_swing). So this script deliberately stops BEFORE the anchor: it stores the
map-frame points and the nav sample that belongs to each frame, and anchoring becomes
a cheap operation that can be repeated under different conventions without touching
the bag again.

The clouds come from the voxeliser's own output rather than the raw LiDAR, because
that is the frame the deployed anchor consumes: gravity aligned, origin at the swing
axis on the ground. Reproducing the boom kinematic chain here instead would be a
second implementation of something the recording already contains.

Points are cropped in the map frame before anything else. The near crop removes the
machine itself - the boom and bucket swing through the near field and are not terrain -
and the far crop removes the long thin returns whose height is mostly range noise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The deployed rn_global_map subscribes to rn/original/voxel_point_cloud, which is the
# one published with frame_id "map"; rn/original/transformed_points carries the same
# chain-transformed geometry but forwards the sensor's header, so its frame_id reads
# lidar_boom/os_lidar and invites exactly the wrong assumption.
DEFAULT_CLOUD_TOPIC = "/rn/original/voxel_point_cloud"
GPS_TOPIC = "/gps_msg"
ATT_TOPIC = "/gps_att"
SWING_TOPIC = "/excavator/sensors/swing_encoder_output"

_NUMPY_OF_ROS = {1: "i1", 2: "u1", 3: "i2", 4: "u2", 5: "i4", 6: "u4", 7: "f4", 8: "f8"}


def cloud_xyz(msg):
    """PointCloud2 to an (N,3) float32 array, straight off the buffer.

    The field layout is read from the message rather than assumed, so an extra
    intensity or ring column does not silently shift x, y and z.
    """
    names, formats, offsets = [], [], []
    for field in msg.fields:
        if field.datatype not in _NUMPY_OF_ROS or field.name in names:
            continue
        names.append(field.name)
        formats.append(_NUMPY_OF_ROS[field.datatype])
        offsets.append(field.offset)
    dtype = np.dtype({"names": names, "formats": formats, "offsets": offsets,
                      "itemsize": msg.point_step})
    record = np.frombuffer(msg.data, dtype=dtype, count=msg.width * msg.height)
    xyz = np.stack([record["x"], record["y"], record["z"]], axis=-1).astype(np.float32)
    return xyz[np.isfinite(xyz).all(axis=1)]


def parse_window(text):
    name, start, end = text.split(":")
    return name, float(start), float(end)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--window", action="append", required=True,
                        help="NAME:START_S:END_S, relative to the first message in the bag")
    parser.add_argument("--min-range-m", type=float, default=3.0,
                        help="near crop in the map frame; below this is the machine itself")
    parser.add_argument("--max-range-m", type=float, default=20.0)
    parser.add_argument("--max-abs-height-m", type=float, default=5.0)
    parser.add_argument("--cloud-topic", default=DEFAULT_CLOUD_TOPIC)
    parser.add_argument("--max-points-per-frame", type=int, default=40000)
    args = parser.parse_args()

    windows = [parse_window(w) for w in args.window]

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=args.bag, storage_id="sqlite3"),
                rosbag2_py.ConverterOptions("", ""))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    cloud_topic = args.cloud_topic
    for topic in (cloud_topic, GPS_TOPIC, ATT_TOPIC, SWING_TOPIC):
        if topic not in types:
            raise SystemExit("bag is missing " + topic)
    reader.set_filter(rosbag2_py.StorageFilter(
        topics=[cloud_topic, GPS_TOPIC, ATT_TOPIC, SWING_TOPIC]))

    # Everything is keyed on the bag receive time, not on header stamps: the LiDAR
    # chain runs on the sensor's internal oscillator in this recording while the GNSS
    # runs on host time, so the receive clock is the only common one.
    nav = {"gps": [], "att": [], "swing": []}
    # Two clocks are kept per frame on purpose. Everything nav-related is keyed on the
    # bag receive time, because that is the only clock the LiDAR chain and the GNSS
    # share in this recording. A SLAM trajectory, however, is stamped with the message
    # header - the sensor's own oscillator, about 1.76e9 s away from host time - so
    # without the header stamp stored alongside, SLAM poses could not be joined back
    # to these frames at all.
    frames = {name: {"points": [], "counts": [], "t": [], "t_header": []}
              for name, _, _ in windows}
    first_stamp = None
    clouds_seen = 0
    frame_id = None

    while reader.has_next():
        topic, data, stamp = reader.read_next()
        seconds = stamp * 1e-9
        if first_stamp is None:
            first_stamp = seconds
        elapsed = seconds - first_stamp

        if topic == GPS_TOPIC:
            msg = deserialize_message(data, get_message(types[topic]))
            nav["gps"].append((elapsed, msg.lat, msg.lon, msg.alt, msg.heading,
                               float(msg.quality)))
        elif topic == ATT_TOPIC:
            msg = deserialize_message(data, get_message(types[topic]))
            nav["att"].append((elapsed, msg.roll, msg.pitch, msg.heading))
        elif topic == SWING_TOPIC:
            msg = deserialize_message(data, get_message(types[topic]))
            nav["swing"].append((elapsed, float(msg.data)))
        elif topic == cloud_topic:
            clouds_seen += 1
            for name, start, end in windows:
                if not (start <= elapsed < end):
                    continue
                msg = deserialize_message(data, get_message(types[topic]))
                frame_id = msg.header.frame_id
                points = cloud_xyz(msg)
                radius = np.hypot(points[:, 0], points[:, 1])
                keep = ((radius >= args.min_range_m) & (radius <= args.max_range_m)
                        & (np.abs(points[:, 2]) <= args.max_abs_height_m))
                points = points[keep]
                if points.shape[0] > args.max_points_per_frame:
                    stride = int(np.ceil(points.shape[0] / args.max_points_per_frame))
                    points = points[::stride]
                if points.shape[0] == 0:
                    continue
                header = msg.header.stamp
                frames[name]["points"].append(points)
                frames[name]["counts"].append(points.shape[0])
                frames[name]["t"].append(elapsed)
                frames[name]["t_header"].append(header.sec + header.nanosec * 1e-9)
                break

    payload = {
        "cloud_frame_id": np.array(frame_id if frame_id else "", dtype=object),
        "cloud_topic": np.array(cloud_topic, dtype=object),
        "clouds_seen": np.array(clouds_seen),
        "gps": np.array(nav["gps"], dtype=float),
        "att": np.array(nav["att"], dtype=float),
        "swing": np.array(nav["swing"], dtype=float),
        "window_names": np.array([name for name, _, _ in windows], dtype=object),
        "crop": np.array([args.min_range_m, args.max_range_m, args.max_abs_height_m]),
    }
    for name, _, _ in windows:
        block = frames[name]
        stacked = (np.concatenate(block["points"], axis=0) if block["points"]
                   else np.zeros((0, 3), dtype=np.float32))
        payload["points_" + name] = stacked
        payload["counts_" + name] = np.array(block["counts"], dtype=np.int64)
        payload["t_" + name] = np.array(block["t"], dtype=float)
        payload["t_header_" + name] = np.array(block["t_header"], dtype=float)
        print("window", name, "frames", len(block["counts"]), "points", stacked.shape[0])

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, **payload)
    print("cloud frame_id", frame_id, "clouds in bag", clouds_seen,
          "gps", len(nav["gps"]), "att", len(nav["att"]), "swing", len(nav["swing"]))
    print("CACHE_WRITTEN", args.out)


if __name__ == "__main__":
    main()
