"""Topics that hold the same data as another one, and what a recording costs on disk."""
import re
from dataclasses import dataclass
from typing import Final, Iterable, Mapping

# Measured on this robot (2026-10-22/23), per hour: the LAZ of one lidar, the SVO2 of one camera.
LAZ_GB_PER_HOUR: Final = 5.3
SVO2_GB_PER_HOUR: Final = 6.5
HEAVY_GB_PER_HOUR: Final = 5.0     # one such topic is worth a question at Start
NOTABLE_GB_PER_HOUR: Final = 1.0   # listed in that question
HEAVY_TYPES: Final = frozenset({
    'sensor_msgs/msg/Image',
    'sensor_msgs/msg/CompressedImage',
    'sensor_msgs/msg/PointCloud2',
    'stereo_msgs/msg/DisparityImage',
    'grid_map_msgs/msg/GridMap',
    'ouster_sensor_msgs/msg/PacketMsg',
    'nav_msgs/msg/Path',
})

_TRANSPORTS: Final = r'(?:/(?:compressed|compressedDepth|theora|zstd))?'
_ZED_STREAM: Final = re.compile(
    r'^(?P<camera>/zedx_[^/]+/[^/]+)/(?P<stream>[a-z_]+)/'
    rf'(?P<kind>image_[a-z_]+|depth_registered|disparity_image|cloud_registered){_TRANSPORTS}$')
_TRANSPORT: Final = re.compile(r'^(?P<raw>.+)/(?:compressed|compressedDepth|theora|zstd)$')
_PACKETS: Final = re.compile(r'^(?P<lidar>/lidar_[^/]+|/ouster)/(?P<data>lidar|imu)_packets$')
_DECODED: Final = {'lidar': 'points', 'imu': 'imu'}
# The form kept when the same images come several times
_KEPT_FIRST: Final = ('/image_rect_color/compressed', '/image_rect_color', '/depth/depth_registered')


def gb_per_hour(bytes_per_second: float) -> float:
    return bytes_per_second * 3600 / 1e9


def _zed_group(stream: str) -> str | None:
    """ZED streams of one picture: rgb is left, *_gray and *_raw are left or right again."""
    if stream.startswith(('left', 'rgb', 'stereo')):
        return 'left'
    if stream.startswith('right'):
        return 'right'
    if stream in ('depth', 'disparity', 'point_cloud'):
        return 'depth'
    return None


def _kept_first(name: str) -> tuple[int, int, str]:
    rank = next((i for i, suffix in enumerate(_KEPT_FIRST) if name.endswith(suffix)), len(_KEPT_FIRST))
    stream_rank = 0 if re.search(r'/(left|right|depth)/', name) else 1
    return (rank, stream_rank, name)


def duplicates(names: Iterable[str]) -> dict[str, str]:
    """Each topic that holds the data of another one of these topics again, mapped to that one."""
    present = set(names)
    found: dict[str, str] = {}
    zed_groups: dict[tuple[str, str], list[str]] = {}
    for name in sorted(present):
        if packets := _PACKETS.match(name):
            decoded = f"{packets['lidar']}/{_DECODED[packets['data']]}"
            if decoded in present:
                found[name] = decoded
        elif zed := _ZED_STREAM.match(name):
            group = _zed_group(zed['stream'])
            if group is not None:
                zed_groups.setdefault((zed['camera'], group), []).append(name)
        elif (transport := _TRANSPORT.match(name)) and transport['raw'] in present:
            found[transport['raw']] = name
    for members in zed_groups.values():
        kept, *others = sorted(members, key=_kept_first)
        found.update({name: kept for name in others})
    return found


@dataclass(frozen=True, slots=True)
class StartPlan:
    """What a Start is about to record."""

    bag_topics: tuple[str, ...]
    laz_and_bag: tuple[str, ...]  # lidar topics that go to LAZ and into the bag ('both')
    laz_lidars: int
    svo2_cameras: int


@dataclass(frozen=True, slots=True)
class StartReport:
    heavy: tuple[tuple[str, float], ...]  # bag topics of NOTABLE_GB_PER_HOUR or more, biggest first
    bag_gb_per_hour: float                # the measured topics going into the bag
    side_gb_per_hour: float               # LAZ and SVO2 beside the bag, estimated
    duplicates: tuple[tuple[str, str], ...]
    laz_and_bag: tuple[str, ...]
    hours_left: float | None              # until the disk is full; None if nothing is measured

    @property
    def worth_asking(self) -> bool:
        return bool(self.duplicates or self.laz_and_bag) or any(
            size >= HEAVY_GB_PER_HOUR for _topic, size in self.heavy)


def start_report(plan: StartPlan, measured_gb_per_hour: Mapping[str, float], free_bytes: int) -> StartReport:
    """What a recording will put on the disk per hour, from the rates measured before Start."""
    sizes = {topic: measured_gb_per_hour.get(topic, 0.0) for topic in plan.bag_topics}
    heavy = sorted(((t, s) for t, s in sizes.items() if s >= NOTABLE_GB_PER_HOUR), key=lambda ts: -ts[1])
    bag = sum(sizes.values())
    side = plan.laz_lidars * LAZ_GB_PER_HOUR + plan.svo2_cameras * SVO2_GB_PER_HOUR
    total = bag + side
    return StartReport(
        heavy=tuple(heavy), bag_gb_per_hour=bag, side_gb_per_hour=side,
        duplicates=tuple(sorted(duplicates(plan.bag_topics).items())),
        laz_and_bag=plan.laz_and_bag,
        hours_left=free_bytes / (total * 1e9) if total > 0 else None,
    )
