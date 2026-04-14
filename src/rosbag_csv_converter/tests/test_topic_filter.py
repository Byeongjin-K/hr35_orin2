import pytest
from pathlib import Path
from rosbag_csv_converter.core.topic_filter import (
    is_excluded_type,
    get_default_excluded_types,
    is_excluded_by_prefix,
    get_default_excluded_prefixes,
    is_system_topic,
    should_exclude_topic,
    get_topic_category,
    categorize_topics,
    parse_metadata,
    TopicInfo,
    filter_topics
)


class TestIsExcludedType:
    def test_image_types_excluded(self):
        assert is_excluded_type("sensor_msgs/msg/Image") is True
        assert is_excluded_type("sensor_msgs/msg/CompressedImage") is True

    def test_pointcloud_types_excluded(self):
        assert is_excluded_type("sensor_msgs/msg/PointCloud2") is True

    def test_packet_types_excluded(self):
        assert is_excluded_type("ouster_sensor_msgs/msg/PacketMsg") is True

    def test_laserscan_excluded(self):
        assert is_excluded_type("sensor_msgs/msg/LaserScan") is True

    def test_numeric_types_not_excluded(self):
        assert is_excluded_type("std_msgs/msg/Float32") is False
        assert is_excluded_type("std_msgs/msg/Int32") is False
        assert is_excluded_type("std_msgs/msg/Bool") is False

    def test_geometry_types_not_excluded(self):
        assert is_excluded_type("geometry_msgs/msg/Point") is False
        assert is_excluded_type("geometry_msgs/msg/PointStamped") is False
        assert is_excluded_type("geometry_msgs/msg/Twist") is False

    def test_custom_types_not_excluded(self):
        assert is_excluded_type("excavator_msgs/msg/RemoteControllerFeedback") is False
        assert is_excluded_type("msg_gps_interface/msg/GPSMsg") is False

    def test_nav_types_not_excluded(self):
        assert is_excluded_type("sensor_msgs/msg/NavSatFix") is False
        assert is_excluded_type("sensor_msgs/msg/Imu") is False


class TestGetDefaultExcludedTypes:
    def test_returns_set(self):
        excluded = get_default_excluded_types()
        assert isinstance(excluded, set)

    def test_contains_image(self):
        excluded = get_default_excluded_types()
        assert "sensor_msgs/msg/Image" in excluded

    def test_contains_pointcloud(self):
        excluded = get_default_excluded_types()
        assert "sensor_msgs/msg/PointCloud2" in excluded


class TestParseMetadata:
    def test_parse_real_metadata(self, sample_metadata_path):
        topics = parse_metadata(sample_metadata_path)
        
        assert len(topics) > 0
        assert all(isinstance(t, TopicInfo) for t in topics)

    def test_topic_info_has_required_fields(self, sample_metadata_path):
        topics = parse_metadata(sample_metadata_path)
        
        for topic in topics:
            assert hasattr(topic, 'name')
            assert hasattr(topic, 'type')
            assert hasattr(topic, 'message_count')

    def test_finds_known_topics(self, sample_metadata_path):
        topics = parse_metadata(sample_metadata_path)
        topic_names = [t.name for t in topics]
        
        assert "/excavator/kinematics/bucket_orientation" in topic_names
        assert "/gps_msg" in topic_names

    def test_parse_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_metadata(tmp_path / "nonexistent.yaml")


class TestFilterTopics:
    def test_filter_excludes_image_topics(self, sample_metadata_path):
        all_topics = parse_metadata(sample_metadata_path)
        filtered = filter_topics(all_topics)
        
        filtered_types = [t.type for t in filtered]
        assert "sensor_msgs/msg/Image" not in filtered_types

    def test_filter_excludes_pointcloud_topics(self, sample_metadata_path):
        all_topics = parse_metadata(sample_metadata_path)
        filtered = filter_topics(all_topics)
        
        filtered_types = [t.type for t in filtered]
        assert "sensor_msgs/msg/PointCloud2" not in filtered_types

    def test_filter_keeps_numeric_topics(self, sample_metadata_path):
        all_topics = parse_metadata(sample_metadata_path)
        filtered = filter_topics(all_topics)
        
        filtered_names = [t.name for t in filtered]
        assert "/excavator/kinematics/bucket_orientation" in filtered_names

    def test_filter_with_custom_excludes(self):
        topics = [
            TopicInfo("/topic1", "std_msgs/msg/Float32", 100),
            TopicInfo("/topic2", "custom/msg/MyType", 50),
        ]
        
        filtered = filter_topics(topics, exclude_types={"custom/msg/MyType"})
        
        assert len(filtered) == 1
        assert filtered[0].name == "/topic1"


class TestTopicInfo:
    def test_topic_info_creation(self):
        info = TopicInfo(
            name="/test/topic",
            type="std_msgs/msg/Float32",
            message_count=100
        )
        
        assert info.name == "/test/topic"
        assert info.type == "std_msgs/msg/Float32"
        assert info.message_count == 100

    def test_topic_info_equality(self):
        info1 = TopicInfo("/topic", "type", 100)
        info2 = TopicInfo("/topic", "type", 100)
        
        assert info1 == info2


class TestIsExcludedByPrefix:
    def test_lidar_prefix_excluded(self):
        assert is_excluded_by_prefix("/lidar_boom/points") is True
        assert is_excluded_by_prefix("/lidar_cabin/imu") is True

    def test_zedx_prefix_excluded(self):
        assert is_excluded_by_prefix("/zedx_boom/plane") is True
        assert is_excluded_by_prefix("/zedx_cabin/zedx_cabin_node/odom") is True

    def test_excavator_prefix_not_excluded(self):
        assert is_excluded_by_prefix("/excavator/sensors/gnss_position") is False

    def test_other_topics_not_excluded(self):
        assert is_excluded_by_prefix("/gps_msg") is False
        assert is_excluded_by_prefix("/tf") is False


class TestGetDefaultExcludedPrefixes:
    def test_returns_tuple(self):
        prefixes = get_default_excluded_prefixes()
        assert isinstance(prefixes, tuple)

    def test_contains_lidar(self):
        prefixes = get_default_excluded_prefixes()
        assert "/lidar_" in prefixes

    def test_contains_zedx(self):
        prefixes = get_default_excluded_prefixes()
        assert "/zedx_" in prefixes


class TestIsSystemTopic:
    def test_rosout_is_system(self):
        assert is_system_topic("/rosout") is True

    def test_tf_static_is_system(self):
        assert is_system_topic("/tf_static") is True
    
    def test_tf_is_not_system(self):
        assert is_system_topic("/tf") is False

    def test_initialpose_is_system(self):
        assert is_system_topic("/initialpose") is True

    def test_transition_event_is_system(self):
        assert is_system_topic("/some_node/transition_event") is True
        assert is_system_topic("/lidar_boom/os_driver/transition_event") is True

    def test_robot_description_is_system(self):
        assert is_system_topic("/robot_description") is True
        assert is_system_topic("/zedx_boom/robot_description") is True

    def test_normal_topics_not_system(self):
        assert is_system_topic("/excavator/sensors/gnss_position") is False
        assert is_system_topic("/gps_msg") is False


class TestShouldExcludeTopic:
    def test_excludes_by_type(self):
        assert should_exclude_topic("/some/image", "sensor_msgs/msg/Image") is True

    def test_excludes_by_prefix(self):
        assert should_exclude_topic("/lidar_boom/imu", "sensor_msgs/msg/Imu") is True
        assert should_exclude_topic("/zedx_boom/odom", "nav_msgs/msg/Odometry") is True

    def test_excludes_system_topics(self):
        assert should_exclude_topic("/rosout", "rcl_interfaces/msg/Log") is True
        assert should_exclude_topic("/tf_static", "tf2_msgs/msg/TFMessage") is True
    
    def test_tf_is_not_excluded(self):
        assert should_exclude_topic("/tf", "tf2_msgs/msg/TFMessage") is False

    def test_excludes_zero_message_count(self):
        assert should_exclude_topic("/some/topic", "std_msgs/msg/Float32", message_count=0) is True

    def test_includes_normal_topics(self):
        assert should_exclude_topic("/excavator/sensors/gnss_position", "sensor_msgs/msg/NavSatFix") is False
        assert should_exclude_topic("/gps_msg", "msg_gps_interface/msg/GPSMsg", message_count=100) is False


class TestGetTopicCategory:
    def test_excavator_category(self):
        assert get_topic_category("/excavator/sensors/gnss_position") == "excavator"
        assert get_topic_category("/excavator/kinematics/bucket_position") == "excavator"

    def test_lidar_category(self):
        assert get_topic_category("/lidar_boom/points") == "lidar"
        assert get_topic_category("/lidar_cabin/imu") == "lidar"

    def test_zedx_category(self):
        assert get_topic_category("/zedx_boom/plane") == "zedx"
        assert get_topic_category("/zedx_cabin/zedx_cabin_node/odom") == "zedx"

    def test_other_category(self):
        assert get_topic_category("/gps_msg") == "other"
        assert get_topic_category("/tf") == "other"
        assert get_topic_category("/rosout") == "other"


class TestCategorizeTopics:
    def test_categorizes_correctly(self):
        topics = [
            TopicInfo("/excavator/sensors/angle", "std_msgs/msg/Float32", 100),
            TopicInfo("/lidar_boom/points", "sensor_msgs/msg/PointCloud2", 50),
            TopicInfo("/zedx_boom/odom", "nav_msgs/msg/Odometry", 30),
            TopicInfo("/gps_msg", "msg_gps_interface/msg/GPSMsg", 20),
        ]
        
        categorized = categorize_topics(topics)
        
        assert "excavator" in categorized
        assert "lidar" in categorized
        assert "zedx" in categorized
        assert "other" in categorized
        
        assert len(categorized["excavator"]) == 1
        assert len(categorized["lidar"]) == 1
        assert len(categorized["zedx"]) == 1
        assert len(categorized["other"]) == 1

    def test_sorts_topics_within_category(self):
        topics = [
            TopicInfo("/excavator/z_topic", "type", 10),
            TopicInfo("/excavator/a_topic", "type", 10),
            TopicInfo("/excavator/m_topic", "type", 10),
        ]
        
        categorized = categorize_topics(topics)
        names = [t.name for t in categorized["excavator"]]
        
        assert names == ["/excavator/a_topic", "/excavator/m_topic", "/excavator/z_topic"]
