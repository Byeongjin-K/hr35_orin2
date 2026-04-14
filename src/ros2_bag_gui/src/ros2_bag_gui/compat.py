"""ROS2 version compatibility layer for Kilted/Humble.

This module provides compatibility wrappers for rosbag2_py API differences
between ROS2 Kilted (dev) and Humble (deploy) distributions.

Key differences:
- TopicMetadata constructor signature (id parameter)
- Python version (3.12 vs 3.10)
"""

import os
from typing import Optional

from rosbag2_py import TopicMetadata as _TopicMetadata

ROS_DISTRO = os.environ.get('ROS_DISTRO', 'unknown')


def create_topic_metadata(
    topic_id: int,
    name: str,
    type_: str,
    serialization_format: str = 'cdr',
    offered_qos_profiles: Optional[list] = None,
    type_description_hash: str = ''
) -> _TopicMetadata:
    """Create TopicMetadata with version-specific handling.

    Args:
        topic_id: Topic identifier (required in Kilted, may not be in Humble)
        name: Topic name (e.g., '/camera/image')
        type_: Message type (e.g., 'sensor_msgs/msg/Image')
        serialization_format: Serialization format (default: 'cdr')
        offered_qos_profiles: QoS profiles list (default: empty list)
        type_description_hash: Type description hash (default: empty string)

    Returns:
        TopicMetadata instance compatible with current ROS distribution

    Raises:
        TypeError: If neither Kilted nor Humble signature works
    """
    if offered_qos_profiles is None:
        offered_qos_profiles = []

    try:
        # Kilted style (with id parameter)
        return _TopicMetadata(
            id=topic_id,
            name=name,
            type=type_,
            serialization_format=serialization_format,
            offered_qos_profiles=offered_qos_profiles,
            type_description_hash=type_description_hash
        )
    except TypeError:
        # Humble style fallback (no id parameter)
        # Try without id and type_description_hash
        try:
            return _TopicMetadata(
                name=name,
                type=type_,
                serialization_format=serialization_format,
                offered_qos_profiles=offered_qos_profiles
            )
        except TypeError:
            # Minimal fallback (only required parameters)
            return _TopicMetadata(
                name=name,
                type=type_,
                serialization_format=serialization_format
            )


def get_ros_distro() -> str:
    """Get current ROS distribution name.

    Returns:
        ROS distribution name (e.g., 'kilted', 'humble', 'unknown')
    """
    return ROS_DISTRO


def is_kilted() -> bool:
    """Check if running on ROS2 Kilted.

    Returns:
        True if ROS_DISTRO is 'kilted'
    """
    return ROS_DISTRO == 'kilted'


def is_humble() -> bool:
    """Check if running on ROS2 Humble.

    Returns:
        True if ROS_DISTRO is 'humble'
    """
    return ROS_DISTRO == 'humble'


def get_python_version() -> tuple[int, int, int]:
    """Get Python version as tuple.

    Returns:
        Tuple of (major, minor, micro) version numbers
    """
    import sys
    return sys.version_info[:3]


def is_python_310_compatible() -> bool:
    """Check if Python version is 3.10 or higher.

    Returns:
        True if Python >= 3.10
    """
    import sys
    return sys.version_info >= (3, 10)
