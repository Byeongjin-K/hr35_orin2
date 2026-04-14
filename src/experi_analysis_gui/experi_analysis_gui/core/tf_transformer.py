"""ROS2 bag의 TF 데이터를 이용한 포인트 클라우드 좌표 변환"""
import numpy as np
from pathlib import Path
from scipy.spatial.transform import Rotation

_tf_cache = {}


def extract_tf_frames(bag_path: str, max_messages: int = 5000) -> dict:
    """bag에서 TF 트리 구조와 static/dynamic 여부를 추출"""
    cache_key = str(Path(bag_path).resolve())
    if cache_key in _tf_cache:
        return _tf_cache[cache_key]

    frames = _read_tf_from_bag(bag_path, max_messages)

    has_static = any(info['static'] for info in frames.values())
    if not has_static:
        parent_dir = Path(bag_path).parent
        metadata_yaml = parent_dir / 'metadata.yaml'
        if metadata_yaml.exists():
            dir_key = str(parent_dir.resolve())
            if dir_key in _tf_cache:
                dir_frames = _tf_cache[dir_key]
            else:
                dir_frames = _read_tf_from_bag(str(parent_dir), max_messages)
                _tf_cache[dir_key] = dir_frames
            for key, info in dir_frames.items():
                if info['static'] and key not in frames:
                    frames[key] = info

    _tf_cache[cache_key] = frames

    return frames


def _read_tf_from_bag(bag_path: str, max_messages: int) -> dict:
    from .rosbag_loader import _open_reader
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from tf2_msgs.msg import TFMessage

    reader = _open_reader(bag_path, topic_filter=['/tf', '/tf_static'])

    frames = {}
    count = 0
    while reader.has_next() and count < max_messages:
        topic, data, t = reader.read_next()
        msg = deserialize_message(data, TFMessage)
        for tf in msg.transforms:
            parent = tf.header.frame_id
            child = tf.child_frame_id
            is_static = (topic == '/tf_static')
            tr = tf.transform.translation
            ro = tf.transform.rotation

            key = f"{parent} -> {child}"
            if key not in frames:
                frames[key] = {
                    'parent': parent,
                    'child': child,
                    'static': is_static,
                    'samples': [],
                }
            if len(frames[key]['samples']) < 10:
                frames[key]['samples'].append({
                    'stamp_sec': tf.header.stamp.sec + tf.header.stamp.nanosec * 1e-9,
                    'translation': [tr.x, tr.y, tr.z],
                    'rotation': [ro.x, ro.y, ro.z, ro.w],
                })
        count += 1

    return frames


def list_available_frames(bag_path: str) -> list:
    """bag에서 사용 가능한 모든 프레임 이름 목록"""
    tf_data = extract_tf_frames(bag_path, max_messages=2000)
    frame_set = set()
    for info in tf_data.values():
        frame_set.add(info['parent'])
        frame_set.add(info['child'])
    return sorted(frame_set)


def get_transform_at_time(bag_path: str, parent_frame: str, child_frame: str,
                           target_time_sec: float = None) -> dict:
    """
    parent_frame → child_frame 변환을 반환.
    target_time_sec=None이면 가장 가까운 시간의 변환 사용.

    반환: {'translation': [x,y,z], 'rotation': [qx,qy,qz,qw]} 또는 None
    """
    tf_data = extract_tf_frames(bag_path, max_messages=10000)

    direct_key = f"{parent_frame} -> {child_frame}"
    if direct_key in tf_data:
        return _pick_sample(tf_data[direct_key], target_time_sec)

    inverse_key = f"{child_frame} -> {parent_frame}"
    if inverse_key in tf_data:
        sample = _pick_sample(tf_data[inverse_key], target_time_sec)
        if sample:
            return _invert_transform(sample)

    chain = _find_tf_chain(tf_data, parent_frame, child_frame)
    if chain is None:
        return None

    return _compose_chain(tf_data, chain, target_time_sec)


def transform_pointcloud(points: np.ndarray, translation: list, rotation_quat: list) -> np.ndarray:
    """포인트 클라우드에 변환 적용. rotation_quat = [qx, qy, qz, qw]"""
    rot = Rotation.from_quat(rotation_quat)
    transformed = rot.apply(points) + np.array(translation)
    return transformed


def transform_pointcloud_between_frames(points: np.ndarray, bag_path: str,
                                         source_frame: str, target_frame: str,
                                         time_sec: float = None) -> np.ndarray:
    """소스 프레임의 점군을 타겟 프레임으로 변환"""
    tf = get_transform_at_time(bag_path, target_frame, source_frame, time_sec)
    if tf is None:
        raise ValueError(
            f"TF를 찾을 수 없습니다: {source_frame} -> {target_frame}\n"
            f"사용 가능한 프레임: {list_available_frames(bag_path)}"
        )
    return transform_pointcloud(points, tf['translation'], tf['rotation'])


def _pick_sample(frame_info: dict, target_time: float = None) -> dict:
    samples = frame_info['samples']
    if not samples:
        return None

    if target_time is None or frame_info['static']:
        s = samples[0]
    else:
        s = min(samples, key=lambda s: abs(s['stamp_sec'] - target_time))

    return {
        'translation': s['translation'],
        'rotation': s['rotation'],
    }


def _invert_transform(tf: dict) -> dict:
    rot = Rotation.from_quat(tf['rotation'])
    inv_rot = rot.inv()
    inv_trans = -inv_rot.apply(tf['translation'])
    return {
        'translation': inv_trans.tolist(),
        'rotation': inv_rot.as_quat().tolist(),
    }


def _find_tf_chain(tf_data: dict, start: str, end: str) -> list:
    """BFS로 start→end TF 체인 탐색. 반환: [(parent, child, inverted), ...]"""
    adjacency = {}
    for info in tf_data.values():
        p, c = info['parent'], info['child']
        if p not in adjacency:
            adjacency[p] = []
        if c not in adjacency:
            adjacency[c] = []
        adjacency[p].append((c, False))
        adjacency[c].append((p, True))

    if start not in adjacency or end not in adjacency:
        return None

    from collections import deque
    queue = deque([(start, [])])
    visited = {start}

    while queue:
        current, path = queue.popleft()
        if current == end:
            return path

        for neighbor, inverted in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                if inverted:
                    queue.append((neighbor, path + [(neighbor, current, True)]))
                else:
                    queue.append((neighbor, path + [(current, neighbor, False)]))

    return None


def _compose_chain(tf_data: dict, chain: list, target_time: float) -> dict:
    """TF 체인을 합성하여 최종 변환 반환"""
    combined_trans = np.array([0.0, 0.0, 0.0])
    combined_rot = Rotation.identity()

    for parent, child, inverted in chain:
        key = f"{parent} -> {child}"
        if key not in tf_data:
            key = f"{child} -> {parent}"
            inverted = not inverted

        if key not in tf_data:
            return None

        sample = _pick_sample(tf_data[key], target_time)
        if sample is None:
            return None

        if inverted:
            sample = _invert_transform(sample)

        step_rot = Rotation.from_quat(sample['rotation'])
        step_trans = np.array(sample['translation'])

        combined_trans = combined_rot.apply(step_trans) + combined_trans
        combined_rot = combined_rot * step_rot

    return {
        'translation': combined_trans.tolist(),
        'rotation': combined_rot.as_quat().tolist(),
    }
