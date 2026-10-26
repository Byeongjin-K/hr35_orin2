#!/usr/bin/env python3
"""Extract video frames and timestamps from a ZED X SVO2 file without the ZED SDK.

  python3 extract_svo2.py FILE.svo2 OUT_DIR [--images png|jpg] [--start S] [--end S] [--every N] [--split] [--imu]

SVO2 is an MCAP container. Each Camera_SN<serial>/side_by_side message holds one
left|right frame (3840x1200, unrectified) as an 8-byte prefix plus one H.265
Annex-B access unit; its MCAP log_time is the image timestamp (epoch ns).

Always writes OUT_DIR/<name>.h265 (the full stream) and OUT_DIR/<name>_frames.csv
(frame index, log_time_ns, publish_time_ns, bytes). --images decodes the selected
frames with ffmpeg into OUT_DIR/<name>_images/<log_time_ns>.<ext> (left/ and right/
subfolders with --split); for PNG the pixels equal the ZED SDK LEFT/RIGHT_UNRECTIFIED
views. --start/--end are seconds from the first frame, --every keeps every N-th frame.
--imu writes the Camera_SN<serial>/sensors messages to OUT_DIR/<name>_sensors.jsonl.
Needs Python 3.8+, the lz4 package, and ffmpeg for --images.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys

import lz4.frame

MAGIC = b'\x89MCAP0\r\n'
OP_MESSAGE, OP_CHANNEL, OP_CHUNK, OP_FOOTER, OP_DATA_END = 0x05, 0x04, 0x06, 0x02, 0x0F
SCALE = ('scale=in_range=pc:out_range=pc:in_color_matrix=bt601:out_color_matrix=bt601:'
         'flags=neighbor+accurate_rnd+full_chroma_int')


def u16(b, o):
    return int.from_bytes(b[o:o + 2], 'little')


def u32(b, o):
    return int.from_bytes(b[o:o + 4], 'little')


def u64(b, o):
    return int.from_bytes(b[o:o + 8], 'little')


def parse_records(buf):
    pos = 0
    while pos + 9 <= len(buf):
        op, length = buf[pos], u64(buf, pos + 1)
        yield op, buf[pos + 9:pos + 9 + length]
        pos += 9 + length


def file_records(path):
    with open(path, 'rb') as f:
        if f.read(8) != MAGIC:
            sys.exit(f'{path} is not an MCAP/SVO2 file')
        while True:
            head = f.read(9)
            if len(head) < 9:
                return
            op, length = head[0], u64(head, 1)
            if op in (OP_FOOTER, OP_DATA_END):
                return
            yield op, f.read(length)


def chunk_records(body):
    pos = 24 + 4
    compression_len = u32(body, pos)
    compression = body[pos + 4:pos + 4 + compression_len].decode()
    pos += 4 + compression_len
    records_len = u64(body, pos)
    data = body[pos + 8:pos + 8 + records_len]
    if compression == 'lz4':
        data = lz4.frame.decompress(data)
    elif compression == 'zstd':
        import zstandard
        data = zstandard.ZstdDecompressor().decompress(data, max_output_size=u64(body, 16))
    elif compression:
        sys.exit(f'unsupported MCAP chunk compression: {compression}')
    return parse_records(data)


def messages(path):
    channels = {}
    for op, body in file_records(path):
        inner = chunk_records(body) if op == OP_CHUNK else [(op, body)]
        for rec_op, rec in inner:
            if rec_op == OP_CHANNEL:
                topic_len = u32(rec, 4)
                channels[u16(rec, 0)] = rec[8:8 + topic_len].decode()
            elif rec_op == OP_MESSAGE:
                yield channels.get(u16(rec, 0), ''), u64(rec, 6), u64(rec, 14), rec[22:]


def select_frames(frames, start_s, end_s, every):
    if not frames:
        return []
    t0 = frames[0][1]
    chosen = [i for i, (_, log_ns, _, _) in enumerate(frames)
              if (start_s is None or log_ns >= t0 + start_s * 1e9) and (end_s is None or log_ns <= t0 + end_s * 1e9)]
    return chosen[::max(every, 1)]


def decode_images(stream, out_dir, frames, chosen, ext, split):
    if shutil.which('ffmpeg') is None:
        sys.exit('ffmpeg not found; install it or omit --images')
    targets = ['left', 'right'] if split else ['']
    for target in targets:
        os.makedirs(os.path.join(out_dir, target), exist_ok=True)
    pick = '+'.join(f'eq(n\\,{i})' for i in chosen) if len(chosen) < 2000 else None
    select = f"select='{pick}'," if pick else ''
    quality = ['-q:v', '2'] if ext == 'jpg' else []
    if split:
        graph = (f'[0:v]{select}{SCALE},split[a][b];[a]crop=iw/2:ih:0:0[l];[b]crop=iw/2:ih:iw/2:0[r]')
        outputs = ['-map', '[l]', *quality, os.path.join(out_dir, 'left', f'%08d.{ext}'),
                   '-map', '[r]', *quality, os.path.join(out_dir, 'right', f'%08d.{ext}')]
        cmd = ['ffmpeg', '-v', 'error', '-f', 'hevc', '-i', stream, '-filter_complex', graph, '-vsync', '0', *outputs]
    else:
        cmd = ['ffmpeg', '-v', 'error', '-f', 'hevc', '-i', stream, '-vf', f'{select}{SCALE}', '-vsync', '0',
               *quality, os.path.join(out_dir, f'%08d.{ext}')]
    subprocess.run(cmd, check=True)
    names = chosen if pick else list(range(len(frames)))
    keep = set(chosen)
    for target in targets:
        folder = os.path.join(out_dir, target)
        for k, index in enumerate(names, start=1):
            src = os.path.join(folder, f'{k:08d}.{ext}')
            if not os.path.exists(src):
                continue
            if index in keep:
                os.replace(src, os.path.join(folder, f'{frames[index][1]}.{ext}'))
            else:
                os.remove(src)


def main():
    parser = argparse.ArgumentParser(description='Extract H.265 video, frame timestamps and images from an SVO2 file.')
    parser.add_argument('svo2')
    parser.add_argument('out_dir')
    parser.add_argument('--images', choices=('png', 'jpg'))
    parser.add_argument('--start', type=float, help='seconds from the first frame')
    parser.add_argument('--end', type=float, help='seconds from the first frame')
    parser.add_argument('--every', type=int, default=1, help='keep every N-th selected frame')
    parser.add_argument('--split', action='store_true', help='write left and right images separately')
    parser.add_argument('--imu', action='store_true', help='also write the sensors channel as JSON lines')
    args = parser.parse_args()

    name = os.path.splitext(os.path.basename(args.svo2))[0]
    os.makedirs(args.out_dir, exist_ok=True)
    stream = os.path.join(args.out_dir, f'{name}.h265')
    frames, channels_seen, imu_count = [], {}, 0
    imu_file = open(os.path.join(args.out_dir, f'{name}_sensors.jsonl'), 'w', encoding='utf-8') if args.imu else None
    with open(stream, 'wb') as video:
        for topic, log_ns, publish_ns, data in messages(args.svo2):
            channels_seen[topic] = channels_seen.get(topic, 0) + 1
            if topic.endswith('/side_by_side'):
                video.write(data[8:])
                frames.append((len(frames), log_ns, publish_ns, len(data) - 8))
            elif imu_file and topic.endswith('/sensors'):
                text = data.decode('utf-8', errors='replace')
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = text
                imu_file.write(json.dumps({'log_time_ns': log_ns, 'message': payload}) + '\n')
                imu_count += 1
    if imu_file:
        imu_file.close()
    with open(os.path.join(args.out_dir, f'{name}_frames.csv'), 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['frame_index', 'log_time_ns', 'publish_time_ns', 'bytes'])
        writer.writerows(frames)
    print(f'{name}: {len(frames)} frames, channels {channels_seen}' + (f', imu {imu_count}' if args.imu else ''))
    if args.images and frames:
        chosen = select_frames(frames, args.start, args.end, args.every)
        decode_images(stream, os.path.join(args.out_dir, f'{name}_images'), frames, chosen, args.images, args.split)
        print(f'{name}: decoded {len(chosen)} images')


if __name__ == '__main__':
    main()
