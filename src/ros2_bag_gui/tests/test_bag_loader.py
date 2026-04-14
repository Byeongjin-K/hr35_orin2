"""Tests for bag_loader module."""

import os
import tempfile
from pathlib import Path

import pytest

from ros2_bag_gui.export.bag_loader import BagLoader, BagSessionInfo, TopicInfo


class TestBagLoader:
    
    @pytest.fixture
    def sample_session_path(self):
        test_dir = Path(__file__).parent
        return str(test_dir / "fixtures" / "sample_60s")
    
    def test_load_session_standard_format(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        assert isinstance(session, BagSessionInfo)
        assert session.session_path == os.path.abspath(sample_session_path)
        assert session.metadata_path.endswith("metadata.yaml")
        assert session.rosbag_path == os.path.abspath(sample_session_path)
        assert session.storage_identifier == "sqlite3"
    
    def test_load_session_rosbag_subfolder_format(self, tmp_path):
        session_dir = tmp_path / "test_session"
        rosbag_dir = session_dir / "rosbag"
        rosbag_dir.mkdir(parents=True)
        
        metadata_content = """rosbag2_bagfile_information:
  version: 9
  storage_identifier: sqlite3
  duration:
    nanoseconds: 1000000000
  starting_time:
    nanoseconds_since_epoch: 1700000000000000000
  message_count: 10
  topics_with_message_count:
    - topic_metadata:
        name: /test_topic
        type: std_msgs/msg/String
        serialization_format: cdr
      message_count: 10
  relative_file_paths:
    - test_0.db3
"""
        metadata_path = rosbag_dir / "metadata.yaml"
        metadata_path.write_text(metadata_content)
        
        db3_file = rosbag_dir / "test_0.db3"
        db3_file.touch()
        
        session = BagLoader.load_session(str(session_dir))
        
        assert session.rosbag_path == str(rosbag_dir)
        assert session.metadata_path == str(metadata_path)
        assert len(session.db3_files) == 1
        assert session.db3_files[0] == str(db3_file)
    
    def test_parse_topics_correctly(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        assert len(session.topics) == 87
        
        gnss_topics = [t for t in session.topics if "gnss_position" in t.name]
        assert len(gnss_topics) == 1
        
        gnss_topic = gnss_topics[0]
        assert gnss_topic.name == "/excavator/sensors/gnss_position"
        assert gnss_topic.type == "sensor_msgs/msg/NavSatFix"
        assert gnss_topic.message_count == 536
        assert gnss_topic.serialization_format == "cdr"
    
    def test_calculate_time_range_correctly(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        assert session.start_time_ns == 1765331708854518630
        assert session.duration_ns == 53701894901
        assert session.end_time_ns == session.start_time_ns + session.duration_ns
        assert session.end_time_ns == 1765331762556413531
    
    def test_total_message_count(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        assert session.total_message_count == 104205
        
        manual_sum = sum(t.message_count for t in session.topics)
        assert session.total_message_count == manual_sum
    
    def test_db3_file_resolution(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        assert len(session.db3_files) == 1
        assert session.db3_files[0].endswith("sample_60s_0.db3")
        assert os.path.isabs(session.db3_files[0])
        assert os.path.exists(session.db3_files[0])
    
    def test_pointcloud_detection_absent(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        assert session.has_pointcloud is False
        assert len(session.pointcloud_files) == 0
    
    def test_pointcloud_detection_present(self, tmp_path):
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        
        metadata_content = """rosbag2_bagfile_information:
  version: 9
  storage_identifier: sqlite3
  duration:
    nanoseconds: 1000000000
  starting_time:
    nanoseconds_since_epoch: 1700000000000000000
  message_count: 5
  topics_with_message_count:
    - topic_metadata:
        name: /test
        type: std_msgs/msg/String
        serialization_format: cdr
      message_count: 5
  relative_file_paths:
    - test_0.db3
"""
        (session_dir / "metadata.yaml").write_text(metadata_content)
        
        pointcloud_dir = session_dir / "pointcloud"
        pointcloud_dir.mkdir()
        (pointcloud_dir / "cloud_001.laz").touch()
        (pointcloud_dir / "cloud_002.laz").touch()
        (pointcloud_dir / "other.txt").touch()
        
        session = BagLoader.load_session(str(session_dir))
        
        assert session.has_pointcloud is True
        assert len(session.pointcloud_files) == 2
        assert all(f.endswith('.laz') for f in session.pointcloud_files)
    
    def test_svo_detection_absent(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        assert session.has_svo is False
        assert len(session.svo_files) == 0
    
    def test_svo_detection_present(self, tmp_path):
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        
        metadata_content = """rosbag2_bagfile_information:
  version: 9
  storage_identifier: sqlite3
  duration:
    nanoseconds: 1000000000
  starting_time:
    nanoseconds_since_epoch: 1700000000000000000
  message_count: 5
  topics_with_message_count:
    - topic_metadata:
        name: /test
        type: std_msgs/msg/String
        serialization_format: cdr
      message_count: 5
  relative_file_paths:
    - test_0.db3
"""
        (session_dir / "metadata.yaml").write_text(metadata_content)
        (session_dir / "camera1.svo2").touch()
        (session_dir / "camera2.svo2").touch()
        
        session = BagLoader.load_session(str(session_dir))
        
        assert session.has_svo is True
        assert len(session.svo_files) == 2
        assert all(f.endswith('.svo2') for f in session.svo_files)
    
    def test_missing_metadata_raises_error(self, tmp_path):
        session_dir = tmp_path / "empty_session"
        session_dir.mkdir()
        
        with pytest.raises(FileNotFoundError, match="metadata.yaml not found"):
            BagLoader.load_session(str(session_dir))
    
    def test_malformed_metadata_missing_root_key(self, tmp_path):
        session_dir = tmp_path / "bad_session"
        session_dir.mkdir()
        
        (session_dir / "metadata.yaml").write_text("invalid: data")
        
        with pytest.raises(ValueError, match="missing 'rosbag2_bagfile_information'"):
            BagLoader.load_session(str(session_dir))
    
    def test_malformed_metadata_missing_duration(self, tmp_path):
        session_dir = tmp_path / "bad_session"
        session_dir.mkdir()
        
        metadata_content = """rosbag2_bagfile_information:
  version: 9
  starting_time:
    nanoseconds_since_epoch: 1700000000000000000
"""
        (session_dir / "metadata.yaml").write_text(metadata_content)
        
        with pytest.raises(ValueError, match="missing duration"):
            BagLoader.load_session(str(session_dir))
    
    def test_malformed_metadata_missing_start_time(self, tmp_path):
        session_dir = tmp_path / "bad_session"
        session_dir.mkdir()
        
        metadata_content = """rosbag2_bagfile_information:
  version: 9
  duration:
    nanoseconds: 1000000000
"""
        (session_dir / "metadata.yaml").write_text(metadata_content)
        
        with pytest.raises(ValueError, match="missing starting_time"):
            BagLoader.load_session(str(session_dir))
    
    def test_get_topics_by_type_filtering(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        image_topics = BagLoader.get_topics_by_type(session, "sensor_msgs/msg/Image")
        assert len(image_topics) > 0
        assert all("Image" in t.type for t in image_topics)
        
        imu_topics = BagLoader.get_topics_by_type(session, "sensor_msgs/msg/Imu")
        assert len(imu_topics) > 0
        assert all("Imu" in t.type for t in imu_topics)
        
        nonexistent = BagLoader.get_topics_by_type(session, "nonexistent/msg/Type")
        assert len(nonexistent) == 0
    
    def test_get_numeric_topics_excludes_binary_types(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        numeric_topics = BagLoader.get_numeric_topics(session)
        
        excluded_types = {
            "sensor_msgs/msg/Image",
            "sensor_msgs/msg/PointCloud2",
            "sensor_msgs/msg/CompressedImage",
            "stereo_msgs/msg/DisparityImage",
            "nav_msgs/msg/Path",
            "rcl_interfaces/msg/Log",
        }
        
        for topic in numeric_topics:
            assert topic.type not in excluded_types
        
        all_topics_count = len(session.topics)
        numeric_count = len(numeric_topics)
        assert numeric_count < all_topics_count
    
    def test_get_numeric_topics_includes_standard_types(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        numeric_topics = BagLoader.get_numeric_topics(session)
        numeric_types = {t.type for t in numeric_topics}
        
        assert "sensor_msgs/msg/Imu" in numeric_types
        assert "sensor_msgs/msg/NavSatFix" in numeric_types
        assert "std_msgs/msg/Float32" in numeric_types
    
    def test_format_time_range_same_day(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        time_range = BagLoader.format_time_range(session)
        
        assert "2025-12-10" in time_range
        assert "~" in time_range
        assert time_range.count("2025-12-10") == 1
    
    def test_format_time_range_different_days(self, tmp_path):
        session_dir = tmp_path / "test_session"
        session_dir.mkdir()
        
        one_day_ns = 24 * 60 * 60 * 1_000_000_000
        
        metadata_content = f"""rosbag2_bagfile_information:
  version: 9
  storage_identifier: sqlite3
  duration:
    nanoseconds: {one_day_ns * 2}
  starting_time:
    nanoseconds_since_epoch: 1700000000000000000
  message_count: 5
  topics_with_message_count:
    - topic_metadata:
        name: /test
        type: std_msgs/msg/String
        serialization_format: cdr
      message_count: 5
  relative_file_paths:
    - test_0.db3
"""
        (session_dir / "metadata.yaml").write_text(metadata_content)
        
        session = BagLoader.load_session(str(session_dir))
        time_range = BagLoader.format_time_range(session)
        
        assert "~" in time_range
        parts = time_range.split("~")
        assert len(parts) == 2
        assert len(parts[0].strip().split()) == 2
        assert len(parts[1].strip().split()) == 2
    
    def test_format_duration_hours(self):
        duration_ns = 3661 * 1_000_000_000
        
        result = BagLoader.format_duration(duration_ns)
        
        assert result == "1h 1m 1s"
    
    def test_format_duration_minutes(self):
        duration_ns = 125 * 1_000_000_000
        
        result = BagLoader.format_duration(duration_ns)
        
        assert result == "2m 5s"
    
    def test_format_duration_seconds(self):
        duration_ns = 45 * 1_000_000_000
        
        result = BagLoader.format_duration(duration_ns)
        
        assert result == "45s"
    
    def test_format_duration_sample_session(self, sample_session_path):
        session = BagLoader.load_session(sample_session_path)
        
        result = BagLoader.format_duration(session.duration_ns)
        
        assert "s" in result
        assert result == "53s"
    
    def test_topic_info_dataclass(self):
        topic = TopicInfo(
            name="/test/topic",
            type="std_msgs/msg/String",
            message_count=100,
            serialization_format="cdr"
        )
        
        assert topic.name == "/test/topic"
        assert topic.type == "std_msgs/msg/String"
        assert topic.message_count == 100
        assert topic.serialization_format == "cdr"
    
    def test_bag_session_info_dataclass(self):
        session = BagSessionInfo(
            session_path="/path/to/session",
            metadata_path="/path/to/metadata.yaml",
            rosbag_path="/path/to/rosbag",
            topics=[],
            total_message_count=0,
            duration_ns=1000000000,
            start_time_ns=1700000000000000000,
            end_time_ns=1700000001000000000,
            db3_files=[],
            storage_identifier="sqlite3",
            has_pointcloud=False,
            has_svo=False,
            pointcloud_files=[],
            svo_files=[]
        )
        
        assert session.session_path == "/path/to/session"
        assert session.duration_ns == 1000000000
        assert session.has_pointcloud is False
