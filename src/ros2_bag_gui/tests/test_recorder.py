"""Tests for recorder."""
import pytest
from ros2_bag_gui.ros2.recorder import (
    should_include_in_rosbag, should_record_lidar_laz,
    RecordingConfig, Recorder, SYSTEM_EXCLUDE
)

class TestTopicExclusion:
    def test_lidar_points_excluded_in_laz_mode(self):
        assert not should_include_in_rosbag('/lidar_boom/points', lidar_mode='laz', camera_mode='bag')

    def test_lidar_points_included_in_bag_mode(self):
        assert should_include_in_rosbag('/lidar_boom/points', lidar_mode='bag', camera_mode='bag')

    def test_lidar_points_included_in_both_mode(self):
        assert should_include_in_rosbag('/lidar_boom/points', lidar_mode='both', camera_mode='bag')

    def test_rosout_excluded(self):
        assert not should_include_in_rosbag('/rosout', lidar_mode='bag', camera_mode='bag')

    def test_camera_image_excluded_in_svo2_mode(self):
        assert not should_include_in_rosbag(
            '/zedx_boom/zedx_node/left/image_rect_color',
            lidar_mode='bag', camera_mode='svo2',
        )

    def test_camera_image_included_in_bag_mode(self):
        assert should_include_in_rosbag(
            '/zedx_boom/zedx_node/left/image_rect_color',
            lidar_mode='bag', camera_mode='bag',
        )

    def test_normal_topic_included(self):
        assert should_include_in_rosbag('/excavator/status', lidar_mode='bag', camera_mode='bag')
        assert should_include_in_rosbag('/tf', lidar_mode='bag', camera_mode='bag')

    def test_gps_topic_included(self):
        assert should_include_in_rosbag('/gps_interface/position', lidar_mode='bag', camera_mode='bag')


class TestLidarLaz:
    def test_lidar_recorded_to_laz(self):
        assert should_record_lidar_laz('/lidar_boom/points', lidar_mode='laz')

    def test_lidar_not_recorded_in_bag_only(self):
        assert not should_record_lidar_laz('/lidar_boom/points', lidar_mode='bag')

    def test_non_lidar_not_recorded(self):
        assert not should_record_lidar_laz('/tf', lidar_mode='laz')


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

    def test_get_topic_hz_empty(self, qtbot):
        recorder = Recorder()
        assert recorder.get_topic_hz() == {}
