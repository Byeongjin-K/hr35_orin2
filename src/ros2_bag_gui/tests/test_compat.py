import pytest
from ros2_bag_gui.compat import (
    create_topic_metadata,
    get_ros_distro,
    is_kilted,
    is_humble,
    get_python_version,
    is_python_310_compatible
)


def test_create_topic_metadata_basic():
    meta = create_topic_metadata(
        topic_id=1,
        name='/test_topic',
        type_='std_msgs/msg/String'
    )
    assert meta.name == '/test_topic'
    assert meta.type == 'std_msgs/msg/String'
    assert meta.serialization_format == 'cdr'


def test_create_topic_metadata_with_qos():
    meta = create_topic_metadata(
        topic_id=2,
        name='/camera/image',
        type_='sensor_msgs/msg/Image',
        serialization_format='cdr',
        offered_qos_profiles=[]
    )
    assert meta.name == '/camera/image'
    assert meta.type == 'sensor_msgs/msg/Image'


def test_create_topic_metadata_with_hash():
    meta = create_topic_metadata(
        topic_id=3,
        name='/odom',
        type_='nav_msgs/msg/Odometry',
        type_description_hash='abc123'
    )
    assert meta.name == '/odom'
    assert meta.type == 'nav_msgs/msg/Odometry'


def test_get_ros_distro():
    distro = get_ros_distro()
    assert isinstance(distro, str)
    assert len(distro) > 0


def test_is_kilted_or_humble():
    assert isinstance(is_kilted(), bool)
    assert isinstance(is_humble(), bool)


def test_distro_mutual_exclusion():
    if get_ros_distro() in ['kilted', 'humble']:
        assert is_kilted() != is_humble()


def test_get_python_version():
    version = get_python_version()
    assert isinstance(version, tuple)
    assert len(version) == 3
    assert all(isinstance(v, int) for v in version)
    assert version[0] == 3


def test_is_python_310_compatible():
    assert is_python_310_compatible() is True
    version = get_python_version()
    assert version >= (3, 10)


def test_topic_metadata_multiple_topics():
    topics = []
    for i in range(5):
        meta = create_topic_metadata(
            topic_id=i,
            name=f'/topic_{i}',
            type_='std_msgs/msg/String'
        )
        topics.append(meta)
    
    assert len(topics) == 5
    for i, meta in enumerate(topics):
        assert meta.name == f'/topic_{i}'


def test_topic_metadata_special_characters():
    meta = create_topic_metadata(
        topic_id=99,
        name='/robot/sensor_data/lidar_scan',
        type_='sensor_msgs/msg/LaserScan'
    )
    assert meta.name == '/robot/sensor_data/lidar_scan'
    assert '/' in meta.name
