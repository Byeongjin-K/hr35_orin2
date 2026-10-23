"""Which sensor a topic belongs to, and which of its topics a sensor's switch ticks."""
import re
from typing import Final, Iterable

# hr35_bringup tells the hardware instances apart by namespace.
# /ouster is the boom lidar under a single-sensor bringup.
LIDARS: Final[dict[str, tuple[str, ...]]] = {
    'lidar_boom': ('/lidar_boom/', '/ouster/'),
    'lidar_cabin': ('/lidar_cabin/',),
}
CAMERAS: Final[dict[str, tuple[str, ...]]] = {
    'camera_boom': ('/zedx_boom/',),
    'camera_cabin': ('/zedx_cabin/',),
}
SENSORS: Final = {**LIDARS, **CAMERAS}
BAG_IMAGE_MODES: Final = frozenset({'bag', 'both'})

_HEAVY_CAMERA_TYPES: Final = frozenset({
    'sensor_msgs/msg/Image',
    'sensor_msgs/msg/CompressedImage',
    'sensor_msgs/msg/PointCloud2',
    'stereo_msgs/msg/DisparityImage',
    'nav_msgs/msg/Path',  # holds the whole path so far: grows with every message
})
_RAW_PACKETS: Final = re.compile(r'_packets$')
_CAMERA_INFO: Final = re.compile(r'/camera_info$')
_KEPT_CAMERA_INFO: Final = re.compile(r'/(left|right)/camera_info$')
_RECOMMENDED_IMAGE: Final = re.compile(r'/(left|right)/image_rect_color/compressed$')


def sensor_of(topic_name: str) -> str | None:
    """The sensor a topic belongs to (lidar_boom, ..., camera_cabin); None for any other topic."""
    return next(
        (sensor for sensor, prefixes in SENSORS.items() if topic_name.startswith(prefixes)), None)


def switch_topics(sensor: str, topics: Iterable[tuple[str, str]], camera_mode: str) -> set[str]:
    """The topics, of (name, type) pairs, that switching a sensor on ticks.

    A lidar: all of its topics but the raw packets, which hold its point clouds and
    images again. A camera: its light topics (camera_info of left and right only)
    and, when camera images go into the bag, the compressed left and right images.
    """
    own = [(name, type_name) for name, type_name in topics if sensor_of(name) == sensor]
    if sensor in LIDARS:
        return {name for name, _type in own if not _RAW_PACKETS.search(name)}
    picked = set()
    for name, type_name in own:
        if _RECOMMENDED_IMAGE.search(name):
            if camera_mode in BAG_IMAGE_MODES:
                picked.add(name)
        elif type_name in _HEAVY_CAMERA_TYPES:
            continue
        elif _CAMERA_INFO.search(name) and not _KEPT_CAMERA_INFO.search(name):
            continue
        else:
            picked.add(name)
    return picked
