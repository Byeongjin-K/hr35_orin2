"""ROS2 bag 파일에서 PointCloud2 토픽을 추출하여 numpy array로 변환"""
import numpy as np
from pathlib import Path


def _detect_storage_id(bag_path: str) -> str:
    """경로 유형에 따라 storage_id를 자동 감지"""
    p = Path(bag_path)
    if p.is_dir():
        return ''
    suffix = p.suffix.lower()
    if suffix == '.db3':
        return 'sqlite3'
    if suffix == '.mcap':
        return 'mcap'
    return ''


def _open_reader(bag_path: str, topic_filter: list = None):
    """SequentialReader를 열고 반환. storage_id 자동 감지 + fallback."""
    import rosbag2_py

    storage_id = _detect_storage_id(bag_path)

    reader = rosbag2_py.SequentialReader()
    storage_options = rosbag2_py.StorageOptions(uri=bag_path, storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format='cdr',
        output_serialization_format='cdr'
    )

    try:
        reader.open(storage_options, converter_options)
    except RuntimeError:
        if storage_id == '':
            for fallback_id in ['sqlite3', 'mcap']:
                try:
                    reader = rosbag2_py.SequentialReader()
                    so = rosbag2_py.StorageOptions(uri=bag_path, storage_id=fallback_id)
                    reader.open(so, converter_options)
                    break
                except RuntimeError:
                    continue
            else:
                raise RuntimeError(
                    f"bag 파일을 열 수 없습니다: {bag_path}\n"
                    f"디렉토리 bag은 metadata.yaml이 필요하고,\n"
                    f"단일 파일은 .db3(sqlite3) 또는 .mcap 형식이어야 합니다."
                )
        else:
            raise

    if topic_filter:
        storage_filter = rosbag2_py.StorageFilter(topics=topic_filter)
        reader.set_filter(storage_filter)

    return reader


def list_pointcloud_topics(bag_path: str) -> list:
    """bag 파일 내 PointCloud2 토픽 목록 반환"""
    reader = _open_reader(bag_path)
    topic_types = reader.get_all_topics_and_types()
    pc_topics = []
    for topic_info in topic_types:
        if topic_info.type in ('sensor_msgs/msg/PointCloud2', 'sensor_msgs/msg/PointCloud'):
            pc_topics.append({
                'name': topic_info.name,
                'type': topic_info.type,
            })
    return pc_topics


def load_pointcloud_from_bag(bag_path: str, topic_name: str = None,
                              frame_index: int = -1,
                              max_points: int = None) -> np.ndarray:
    """
    ROS2 bag에서 PointCloud2 메시지를 읽어 (N,3) numpy array로 변환.

    frame_index=-1이면 마지막 프레임, 범위 초과 시 마지막 프레임으로 클램프.
    메모리 절약을 위해 frame_index가 양수이면 해당 프레임까지만 읽음.
    """
    from rclpy.serialization import deserialize_message
    from sensor_msgs.msg import PointCloud2

    if topic_name is None:
        topics = list_pointcloud_topics(bag_path)
        if not topics:
            raise ValueError(f"bag에 PointCloud2 토픽이 없습니다: {bag_path}")
        topic_name = topics[0]['name']

    reader = _open_reader(bag_path, topic_filter=[topic_name])

    if frame_index >= 0:
        idx = 0
        target_data = None
        while reader.has_next():
            (topic, data, t) = reader.read_next()
            if idx == frame_index:
                target_data = data
                break
            idx += 1

        if target_data is None:
            if idx == 0:
                raise ValueError(f"토픽 '{topic_name}'에 메시지가 없습니다")
            reader = _open_reader(bag_path, topic_filter=[topic_name])
            last_data = None
            while reader.has_next():
                (topic, data, t) = reader.read_next()
                last_data = data
            target_data = last_data
    else:
        last_data = None
        count = 0
        while reader.has_next():
            (topic, data, t) = reader.read_next()
            last_data = data
            count += 1

        if last_data is None:
            raise ValueError(f"토픽 '{topic_name}'에 메시지가 없습니다")
        target_data = last_data

    msg = deserialize_message(target_data, PointCloud2)
    points = _pointcloud2_to_numpy(msg)

    if max_points is not None and len(points) > max_points:
        indices = np.random.choice(len(points), max_points, replace=False)
        points = points[indices]

    return points


def get_bag_info(bag_path: str) -> dict:
    """bag 파일의 메타 정보 반환"""
    reader = _open_reader(bag_path)
    metadata = reader.get_metadata()
    topic_types = reader.get_all_topics_and_types()

    topics = [{'name': t.name, 'type': t.type} for t in topic_types]

    duration_ns = 0
    if hasattr(metadata, 'duration'):
        dur = metadata.duration
        if hasattr(dur, 'nanoseconds'):
            duration_ns = dur.nanoseconds
        elif hasattr(dur, 'total_seconds'):
            duration_ns = int(dur.total_seconds() * 1e9)

    return {
        'path': bag_path,
        'topics': topics,
        'total_messages': metadata.message_count,
        'duration_ns': duration_ns,
    }


GRIDMAP_TYPES = (
    'nav_msgs/msg/OccupancyGrid',
    'grid_map_msgs/msg/GridMap',
)


def list_gridmap_topics(bag_path: str) -> list:
    reader = _open_reader(bag_path)
    topic_types = reader.get_all_topics_and_types()
    topics = []
    for t in topic_types:
        if t.type in GRIDMAP_TYPES:
            topics.append({'name': t.name, 'type': t.type})
    return topics


def load_gridmap_from_bag(bag_path: str, topic_name: str,
                           frame_index: int = -1) -> dict:
    """
    ROS2 bag에서 OccupancyGrid 또는 GridMap을 읽어 높이 grid dict로 변환.
    OccupancyGrid: 0~100 값을 높이로 매핑 (occupancy 기반).
    GridMap: 'elevation' 레이어가 있으면 그것을 사용.
    """
    from rclpy.serialization import deserialize_message

    reader = _open_reader(bag_path)
    all_topics = {t.name: t.type for t in reader.get_all_topics_and_types()}
    msg_type_str = all_topics.get(topic_name, '')

    reader = _open_reader(bag_path, topic_filter=[topic_name])

    if frame_index >= 0:
        idx = 0
        target_data = None
        while reader.has_next():
            _, data, _ = reader.read_next()
            if idx == frame_index:
                target_data = data
                break
            idx += 1
        if target_data is None:
            raise ValueError(f"토픽 '{topic_name}'에 메시지가 없거나 프레임 인덱스 초과")
    else:
        last_data = None
        while reader.has_next():
            _, data, _ = reader.read_next()
            last_data = data
        if last_data is None:
            raise ValueError(f"토픽 '{topic_name}'에 메시지가 없습니다")
        target_data = last_data

    if 'OccupancyGrid' in msg_type_str:
        from nav_msgs.msg import OccupancyGrid
        msg = deserialize_message(target_data, OccupancyGrid)
        return _occupancy_grid_to_dict(msg)

    raise ValueError(f"지원하지 않는 GridMap 타입: {msg_type_str}")


def _occupancy_grid_to_dict(msg) -> dict:
    width = msg.info.width
    height = msg.info.height
    resolution = msg.info.resolution
    origin_x = msg.info.origin.position.x
    origin_y = msg.info.origin.position.y

    data = np.array(msg.data, dtype=np.float64).reshape(height, width)
    data[data < 0] = np.nan

    x_edges = np.arange(width) * resolution + origin_x
    y_edges = np.arange(height) * resolution + origin_y

    return {
        'grid': data,
        'resolution': resolution,
        'origin': (origin_x, origin_y),
        'x_edges': x_edges,
        'y_edges': y_edges,
    }


def count_frames(bag_path: str, topic_name: str) -> int:
    """특정 토픽의 메시지(프레임) 수 반환"""
    reader = _open_reader(bag_path, topic_filter=[topic_name])
    count = 0
    while reader.has_next():
        reader.read_next()
        count += 1
    return count


def _pointcloud2_to_numpy(msg) -> np.ndarray:
    """PointCloud2 메시지를 (N, 3) numpy array로 변환"""
    try:
        from sensor_msgs_py import point_cloud2
        cloud_arr = point_cloud2.read_points(msg, field_names=('x', 'y', 'z'), skip_nans=True)
        structured = np.array(list(cloud_arr))
        if structured.size == 0:
            return np.empty((0, 3))

        if structured.dtype.names:
            x = structured['x'].astype(np.float64)
            y = structured['y'].astype(np.float64)
            z = structured['z'].astype(np.float64)
            return np.column_stack([x, y, z])

        return structured.astype(np.float64).reshape(-1, 3)
    except ImportError:
        pass

    return _parse_pointcloud2_manual(msg)


def _parse_pointcloud2_manual(msg) -> np.ndarray:
    """sensor_msgs_py 없이 numpy 기반으로 PointCloud2 파싱 (vectorized)"""
    import struct

    field_map = {}
    for f in msg.fields:
        field_map[f.name] = {'offset': f.offset, 'datatype': f.datatype}

    if 'x' not in field_map or 'y' not in field_map or 'z' not in field_map:
        raise ValueError("PointCloud2에 x, y, z 필드가 없습니다")

    NUMPY_DTYPES = {
        1: np.int8, 2: np.uint8, 3: np.int16, 4: np.uint16,
        5: np.int32, 6: np.uint32, 7: np.float32, 8: np.float64,
    }

    point_step = msg.point_step
    data = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    n_points = msg.width * msg.height

    if len(data) < n_points * point_step:
        n_points = len(data) // point_step

    points = np.empty((n_points, 3), dtype=np.float64)
    for col_idx, field_name in enumerate(('x', 'y', 'z')):
        info = field_map[field_name]
        dt = NUMPY_DTYPES.get(info['datatype'], np.float32)
        byte_offset = info['offset']
        dt_size = np.dtype(dt).itemsize

        raw = np.lib.stride_tricks.as_strided(
            data[byte_offset:],
            shape=(n_points,),
            strides=(point_step,),
        )
        points[:, col_idx] = np.frombuffer(raw.tobytes(), dtype=dt).astype(np.float64)

    valid = ~(np.isnan(points[:, 0]) | np.isnan(points[:, 1]) | np.isnan(points[:, 2]))
    return points[valid]
