#!/usr/bin/env python3
"""Decode the Ouster OS-0-128 packets of a 2026-10-23 light bag into point clouds.

The output reproduces what the recording's ouster-ros 0.15.1 driver published on
/lidar_boom/points: point_type 'original' (x, y, z, intensity, t, reflectivity,
ring, ambient, range; 48-byte points), organized 128 x 512, destaggered, frame
lidar_boom/os_lidar, no-return points as NaN, header stamps restored from
/lidar_boom/scan (same stamp as the original point cloud).

  python3 decode_ouster_packets.py BAG_DIR --npz OUT_DIR [--start S] [--end S]
  python3 decode_ouster_packets.py BAG_DIR --bag OUT_BAG [--merge] [--start S] [--end S]

BAG_DIR is an extracted rosbag_light/ folder. --start/--end are seconds from the
first lidar packet. --npz needs numpy and ouster-sdk==0.16.2 only. --bag also
needs a sourced ROS 2 Humble environment (rclpy, rosbag2_py, sensor_msgs);
--merge copies every other topic of the light bag except the raw packet topics,
so the output bag can be played alone with `ros2 bag play`.
"""
import argparse
import array
import bisect
import glob
import heapq
import math
import os
import re
import sqlite3
import sys

import numpy as np
from ouster.sdk import core

PACKETS = '/lidar_boom/lidar_packets'
RAW_TOPICS = (PACKETS, '/lidar_boom/imu_packets')
METADATA = '/lidar_boom/metadata'
SCAN = '/lidar_boom/scan'
MIN_RANGE_MM, MAX_RANGE_MM = 0, 1_000_000
STAMP_MATCH_NS = 50_000_000
FIELDS = (('x', 0, 7), ('y', 4, 7), ('z', 8, 7), ('intensity', 16, 7), ('t', 20, 6),
          ('reflectivity', 24, 4), ('ring', 26, 4), ('ambient', 28, 4), ('range', 32, 6))
POINT_DTYPE = np.dtype({
    'names': ['x', 'y', 'z', 'w', 'intensity', 't', 'reflectivity', 'ring', 'ambient', 'range'],
    'formats': ['<f4', '<f4', '<f4', '<f4', '<f4', '<u4', '<u2', '<u2', '<u2', '<u4'],
    'offsets': [0, 4, 8, 12, 16, 20, 24, 26, 28, 32],
    'itemsize': 48,
})


def db_files(bag):
    def index(path):
        match = re.search(r'_(\d+)\.db3$', path)
        return int(match.group(1)) if match else 0
    files = sorted(glob.glob(os.path.join(bag, '*.db3')), key=index)
    if not files:
        sys.exit(f'no .db3 files in {bag}')
    return files


def connect(path):
    return sqlite3.connect(f'file:{path}?mode=ro&immutable=1', uri=True)


def read_topics(bag, names, start_ns=None, end_ns=None):
    for path in db_files(bag):
        con = connect(path)
        ids = {topic_id: name for topic_id, name in con.execute('select id, name from topics') if name in names}
        if ids:
            query = f"select topic_id, timestamp, data from messages where topic_id in ({','.join(map(str, ids))})"
            args = []
            if start_ns is not None:
                query, args = query + ' and timestamp >= ?', args + [start_ns]
            if end_ns is not None:
                query, args = query + ' and timestamp <= ?', args + [end_ns]
            for topic_id, timestamp, data in con.execute(query + ' order by timestamp, id', args):
                yield timestamp, ids[topic_id], data
        con.close()


def first_timestamp(bag, topic):
    stamps = []
    for path in db_files(bag):
        con = connect(path)
        row = con.execute('select min(m.timestamp) from messages m join topics t on m.topic_id = t.id '
                          'where t.name = ?', (topic,)).fetchone()
        con.close()
        if row and row[0] is not None:
            stamps.append(row[0])
    if not stamps:
        sys.exit(f'no {topic} messages in the bag')
    return min(stamps)


def cdr_string(data):
    length = int.from_bytes(data[4:8], 'little')
    return data[8:8 + length - 1].decode('utf-8')


def header_stamp_ns(data):
    return int.from_bytes(data[4:8], 'little', signed=True) * 1_000_000_000 + int.from_bytes(data[8:12], 'little')


class DriverScanTimestamp:
    def __init__(self, width, spacing_ns):
        self.width, self.spacing_ns = width, spacing_ns
        self.last_index, self.last_value = None, 0

    def __call__(self, column_ts):
        nonzero = np.flatnonzero(column_ts)
        first, last = int(nonzero[0]), int(nonzero[-1])
        value = int(column_ts[first])
        if first == 0:
            scan_ts = value
        elif self.last_index is None:
            scan_ts = math.floor(value - self.spacing_ns * first + 0.5)
        else:
            x0, y0, x1 = self.last_index, self.last_value, self.width + first
            scan_ts = math.floor(y0 + (value - y0) * (self.width - x0) / (x1 - x0) + 0.5)
        self.last_index, self.last_value = last, int(column_ts[last])
        return scan_ts


def decode_frames(bag, start_s=None, end_s=None):
    meta = next(read_topics(bag, {METADATA}), None)
    if meta is None:
        sys.exit(f'no {METADATA} message in the bag')
    info = core.SensorInfo(cdr_string(meta[2]))
    width, height = info.format.columns_per_frame, info.format.pixels_per_column
    spacing_ns = 1e9 / (width * info.format.fps)
    scan_stamps = sorted(header_stamp_ns(data) for _, _, data in read_topics(bag, {SCAN}))
    lut = core.XYZLut(info, use_extrinsics=False)
    lidar_to_sensor = np.asarray(info.lidar_to_sensor_transform, dtype=np.float64)
    rotation, translation = lidar_to_sensor[:3, :3], lidar_to_sensor[:3, 3] / 1000.0
    first_mid_offset = 8 + core.PacketFormat(info).packet_header_size + 8
    rings = np.repeat(np.arange(height, dtype=np.uint16)[:, None], width, axis=1)

    origin_ns = first_timestamp(bag, PACKETS)
    window_start = None if start_s is None else origin_ns + int(start_s * 1e9)
    window_end = None if end_s is None else origin_ns + int(end_s * 1e9)
    read_from = None if window_start is None else window_start - 2_000_000_000

    batcher, scan = core.ScanBatcher(info), core.LidarScan(info)
    scan_ts_of = DriverScanTimestamp(width, spacing_ns)
    first_packet = {}
    for bag_ns, _, data in read_topics(bag, {PACKETS}, read_from):
        buf = np.frombuffer(data, dtype=np.uint8, offset=8)
        frame_id = int.from_bytes(data[10:12], 'little')
        first_packet.setdefault(frame_id, (bag_ns, int.from_bytes(data[first_mid_offset:first_mid_offset + 2], 'little')))
        packet = core.LidarPacket(buf.size)
        packet.buf[:] = buf
        packet.host_timestamp = bag_ns
        if not batcher(packet, scan):
            continue
        done, scan = scan, core.LidarScan(info)
        arrival_ns, first_mid = first_packet.pop(int(done.frame_id), (bag_ns, 0))
        for stale in [k for k in first_packet if k != frame_id]:
            first_packet.pop(stale)
        column_ts = np.asarray(done.timestamp, dtype=np.uint64)
        if not column_ts.any():
            continue
        scan_ts = scan_ts_of(column_ts)
        estimate = int(arrival_ns - spacing_ns * first_mid)
        i = bisect.bisect_left(scan_stamps, estimate)
        near = min(scan_stamps[max(i - 1, 0):i + 1], key=lambda s: abs(s - estimate), default=None)
        matched = near is not None and abs(near - estimate) < STAMP_MATCH_NS
        stamp_ns = near if matched else estimate
        if window_start is not None and stamp_ns < window_start:
            continue
        if window_end is not None and stamp_ns > window_end:
            break
        rng = np.asarray(done.field(core.ChanField.RANGE), dtype=np.uint32)
        invalid = (rng == 0) | (rng < MIN_RANGE_MM) | (rng > MAX_RANGE_MM)
        xyz = ((lut(rng) - translation) @ rotation).astype(np.float32)
        xyz[invalid] = np.nan
        delta = column_ts.astype(np.int64) - np.int64(scan_ts)
        t_col = np.where(column_ts > np.uint64(scan_ts), delta, 0).astype(np.uint32)
        staggered = {
            'x': xyz[..., 0], 'y': xyz[..., 1], 'z': xyz[..., 2],
            'intensity': np.asarray(done.field(core.ChanField.SIGNAL)).astype(np.float32),
            't': np.repeat(t_col[None, :], height, axis=0),
            'reflectivity': np.asarray(done.field(core.ChanField.REFLECTIVITY)).astype(np.uint16),
            'ambient': np.asarray(done.field(core.ChanField.NEAR_IR)).astype(np.uint16),
            'range': rng,
        }
        frame = {name: np.ascontiguousarray(core.destagger(info, np.ascontiguousarray(values)))
                 for name, values in staggered.items()}
        frame['ring'] = rings
        yield {
            'fields': frame, 'stamp_ns': stamp_ns, 'stamp_source': 'scan' if matched else 'estimated',
            'missing_columns': int(width - np.count_nonzero(column_ts)), 'frame_id': int(done.frame_id),
            'publish_ns': bag_ns,
        }


def count(stats, frame):
    stats['frames'] += 1
    stats['incomplete'] += frame['missing_columns'] > 0
    stats['estimated_stamp'] += frame['stamp_source'] != 'scan'


def write_npz(frames, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    stats = {'frames': 0, 'incomplete': 0, 'estimated_stamp': 0}
    for frame in frames:
        np.savez_compressed(
            os.path.join(out_dir, f"{frame['stamp_ns']}.npz"), **frame['fields'],
            stamp_ns=np.int64(frame['stamp_ns']), stamp_source=np.str_(frame['stamp_source']),
            missing_columns=np.int32(frame['missing_columns']), frame_id=np.int32(frame['frame_id']))
        count(stats, frame)
    return stats


def write_bag(bag, frames, out_bag, merge, frame_id, topic, start_s, end_s):
    try:
        import rosbag2_py
        from rclpy.serialization import serialize_message
        from sensor_msgs.msg import PointCloud2, PointField
    except ImportError as exc:
        sys.exit(f'--bag needs a sourced ROS 2 Humble environment: {exc}')
    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=out_bag, storage_id='sqlite3', max_bagfile_size=3 * 1024 ** 3),
                rosbag2_py.ConverterOptions('cdr', 'cdr'))
    writer.create_topic(rosbag2_py.TopicMetadata(name=topic, type='sensor_msgs/msg/PointCloud2',
                                                 serialization_format='cdr', offered_qos_profiles=''))
    fields = [PointField(name=name, offset=offset, datatype=datatype, count=1) for name, offset, datatype in FIELDS]
    stats = {'frames': 0, 'incomplete': 0, 'estimated_stamp': 0, 'copied_messages': 0}

    def clouds():
        for frame in frames:
            values = frame['fields']
            height, width = values['range'].shape
            points = np.zeros(height * width, dtype=POINT_DTYPE)
            for name, _, _ in FIELDS:
                points[name] = values[name].reshape(-1)
            points['w'] = 1.0
            msg = PointCloud2()
            msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(frame['stamp_ns'], 1_000_000_000)
            msg.header.frame_id = frame_id
            msg.height, msg.width, msg.fields = height, width, fields
            msg.is_bigendian, msg.point_step, msg.row_step = False, POINT_DTYPE.itemsize, POINT_DTYPE.itemsize * width
            msg.data = array.array('B', points.tobytes())
            msg.is_dense = bool(np.isfinite(values['x']).all())
            count(stats, frame)
            yield frame['publish_ns'], topic, serialize_message(msg)

    def copied(names, start_ns, end_ns):
        for item in read_topics(bag, names, start_ns, end_ns):
            stats['copied_messages'] += 1
            yield item

    streams = [clouds()]
    if merge:
        origin_ns = first_timestamp(bag, PACKETS)
        start_ns = None if start_s is None else origin_ns + int(start_s * 1e9)
        end_ns = None if end_s is None else origin_ns + int(end_s * 1e9)
        con = connect(db_files(bag)[0])
        topics = con.execute('select name, type, serialization_format, offered_qos_profiles from topics').fetchall()
        con.close()
        others = {name for name, _, _, _ in topics if name not in RAW_TOPICS and name != topic}
        for name, msg_type, serialization, qos in topics:
            if name in others:
                writer.create_topic(rosbag2_py.TopicMetadata(name=name, type=msg_type,
                                                             serialization_format=serialization,
                                                             offered_qos_profiles=qos or ''))
        streams.append(copied(others, start_ns, end_ns))
    for timestamp, name, data in heapq.merge(*streams, key=lambda m: m[0]):
        writer.write(name, data, timestamp)
    del writer
    return stats


def main():
    parser = argparse.ArgumentParser(description='Decode /lidar_boom/lidar_packets of a light bag into point clouds.')
    parser.add_argument('input_bag', metavar='BAG_DIR', help='extracted rosbag_light/ folder (sqlite3 rosbag2 bag)')
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--npz', metavar='OUT_DIR', help='write one compressed npz per frame, named <stamp_ns>.npz')
    output.add_argument('--bag', dest='out_bag', metavar='OUT_BAG', help='write a rosbag2 sqlite3 bag with PointCloud2')
    parser.add_argument('--merge', action='store_true', help='with --bag: also copy every non-packet topic of the input')
    parser.add_argument('--start', type=float, help='seconds from the first lidar packet')
    parser.add_argument('--end', type=float, help='seconds from the first lidar packet')
    parser.add_argument('--frame-id', default='lidar_boom/os_lidar')
    parser.add_argument('--topic', default='/lidar_boom/points')
    args = parser.parse_args()
    frames = decode_frames(args.input_bag, args.start, args.end)
    if args.npz:
        stats = write_npz(frames, args.npz)
    else:
        if os.path.exists(args.out_bag):
            sys.exit(f'output bag {args.out_bag} already exists')
        stats = write_bag(args.input_bag, frames, args.out_bag, args.merge, args.frame_id, args.topic,
                          args.start, args.end)
    print(' '.join(f'{key}={value}' for key, value in stats.items()))


if __name__ == '__main__':
    main()
