"""Tests for recorder."""
import pytest
from ros2_bag_gui.ros2.recorder import (
    should_include_in_rosbag, RecordingConfig, Recorder, ALWAYS_EXCLUDE
)

class TestTopicExclusion:
    def test_lidar_points_excluded(self):
        assert not should_include_in_rosbag('/lidar_boom/points', False, True)
    
    def test_rosout_excluded(self):
        assert not should_include_in_rosbag('/rosout', False, True)
    
    def test_zed_image_excluded_with_sdk(self):
        assert not should_include_in_rosbag(
            '/zedx_boom/zedx_node/left/image_rect_color',
            zed_sdk_available=True,
            include_images_without_sdk=False
        )
    
    def test_zed_image_included_without_sdk_with_flag(self):
        assert should_include_in_rosbag(
            '/zedx_boom/zedx_node/left/image_rect_color',
            zed_sdk_available=False,
            include_images_without_sdk=True
        )
    
    def test_normal_topic_included(self):
        assert should_include_in_rosbag('/excavator/status', False, True)
        assert should_include_in_rosbag('/tf', False, True)
    
    def test_gps_topic_included(self):
        assert should_include_in_rosbag('/gps_interface/position', False, True)

class TestRecordingConfig:
    def test_default_max_bagfile_size(self):
        config = RecordingConfig(
            topics=[],
            output_path='/tmp',
            session_name='test'
        )
        assert config.max_bagfile_size == 3 * 1024**3

class TestRecorder:
    def test_initial_state(self, qtbot):
        recorder = Recorder()
        assert not recorder.is_recording
        assert recorder.topic_counts == {}
    
    def test_generate_session_path_format(self, qtbot):
        from datetime import datetime
        recorder = Recorder()
        recorder._config = RecordingConfig(
            topics=[],
            output_path='/tmp/data',
            session_name='Test Session'
        )
        recorder._session_start_time = datetime(2026, 1, 22, 14, 30, 0)
        
        path = recorder._generate_session_path()
        assert '/tmp/data/recording_2026-01-22_14-30-00_Test_Session' == path
    
    def test_get_timestamp_ns_with_header(self, qtbot):
        from unittest.mock import Mock
        recorder = Recorder()
        
        msg = Mock()
        msg.header.stamp.sec = 1700000000
        msg.header.stamp.nanosec = 123456789
        
        ts = recorder._get_timestamp_ns(msg)
        assert ts == 1700000000 * 10**9 + 123456789
