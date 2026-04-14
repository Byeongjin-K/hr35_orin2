from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class TopicInfo:
    name: str
    type: str
    message_count: int
    
    def __eq__(self, other):
        if not isinstance(other, TopicInfo):
            return False
        return (self.name == other.name and 
                self.type == other.type and 
                self.message_count == other.message_count)


_DEFAULT_EXCLUDED_TYPES = {
    "sensor_msgs/msg/Image",
    "sensor_msgs/msg/CompressedImage",
    "sensor_msgs/msg/PointCloud2",
    "sensor_msgs/msg/LaserScan",
    "ouster_sensor_msgs/msg/PacketMsg",
    "stereo_msgs/msg/DisparityImage",
}

_DEFAULT_EXCLUDED_PREFIXES = (
    "/lidar_",
    "/zedx_",
)

_SYSTEM_TOPICS = {
    "/rosout",
    "/tf_static",
    "/initialpose",
    "/parameter_events",
    "/robot_description",
    "/clock",
}


def get_default_excluded_types() -> set[str]:
    return _DEFAULT_EXCLUDED_TYPES.copy()


def get_default_excluded_prefixes() -> tuple[str, ...]:
    return _DEFAULT_EXCLUDED_PREFIXES


def is_excluded_by_prefix(topic_name: str, exclude_prefixes: Optional[tuple[str, ...]] = None) -> bool:
    if exclude_prefixes is None:
        exclude_prefixes = _DEFAULT_EXCLUDED_PREFIXES
    return topic_name.startswith(exclude_prefixes)


def is_excluded_type(msg_type: str, exclude_types: Optional[set[str]] = None) -> bool:
    if exclude_types is None:
        exclude_types = _DEFAULT_EXCLUDED_TYPES
    return msg_type in exclude_types


def is_system_topic(topic_name: str) -> bool:
    if topic_name in _SYSTEM_TOPICS:
        return True
    if topic_name.endswith("/transition_event"):
        return True
    if topic_name.endswith("/robot_description"):
        return True
    if "_check_fields" in topic_name:
        return True
    return False


def should_exclude_topic(topic_name: str, msg_type: str, message_count: int = 1) -> bool:
    if message_count == 0:
        return True
    return is_excluded_type(msg_type) or is_excluded_by_prefix(topic_name) or is_system_topic(topic_name)


def parse_metadata(metadata_path: Path | str) -> list[TopicInfo]:
    metadata_path = Path(metadata_path)
    
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
    
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = yaml.safe_load(f)
    
    topics = []
    bag_info = metadata.get('rosbag2_bagfile_information', {})
    topics_with_count = bag_info.get('topics_with_message_count', [])
    
    for topic_data in topics_with_count:
        topic_meta = topic_data.get('topic_metadata', {})
        topics.append(TopicInfo(
            name=topic_meta.get('name', ''),
            type=topic_meta.get('type', ''),
            message_count=topic_data.get('message_count', 0)
        ))
    
    return topics


def filter_topics(
    topics: list[TopicInfo],
    exclude_types: Optional[set[str]] = None
) -> list[TopicInfo]:
    if exclude_types is None:
        exclude_types = _DEFAULT_EXCLUDED_TYPES
    
    return [
        t for t in topics 
        if not should_exclude_topic(t.name, t.type, t.message_count)
        and t.type not in exclude_types
    ]


def get_topic_category(topic_name: str) -> str:
    if topic_name.startswith("/excavator/"):
        return "excavator"
    elif topic_name.startswith("/lidar_"):
        return "lidar"
    elif topic_name.startswith("/zedx_"):
        return "zedx"
    else:
        return "other"


def categorize_topics(topics: list[TopicInfo]) -> dict[str, list[TopicInfo]]:
    categories: dict[str, list[TopicInfo]] = {}
    for topic in topics:
        cat = get_topic_category(topic.name)
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(topic)
    
    for cat_topics in categories.values():
        cat_topics.sort(key=lambda t: t.name)
    
    return categories
