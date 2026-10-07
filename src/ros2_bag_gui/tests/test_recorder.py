"""Tests for recorder."""
import json
import os
import signal
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


def _config(tmp_path, **kwargs):
    return RecordingConfig(
        topics=[{'name': '/excavator/status', 'type': 'std_msgs/msg/String'}],
        output_path=str(tmp_path / 'out'),
        session_name='t',
        **kwargs,
    )


def _recorder_with_log():
    recorder = Recorder()
    log = {'errors': [], 'stopped': 0}
    recorder.error_occurred.connect(log['errors'].append)
    recorder.recording_stopped.connect(lambda: log.__setitem__('stopped', log['stopped'] + 1))
    return recorder, log


def _sync_info(recorder):
    with open(os.path.join(recorder.session_path, 'sync_info.json')) as f:
        return json.load(f)


class TestRecorderProcessLifecycle:
    """The real QProcess path, against a stand-in for `ros2` (conftest.fake_ros2)."""

    def test_start_fails_when_recorder_cannot_start(self, qtbot, tmp_path, fake_node, monkeypatch):
        empty_dir = tmp_path / 'empty_bin'
        empty_dir.mkdir()
        monkeypatch.setenv('PATH', str(empty_dir))  # no `ros2` to be found
        recorder, log = _recorder_with_log()

        assert recorder.start_recording(_config(tmp_path), fake_node) is False

        assert not recorder.is_recording
        assert len(log['errors']) == 1
        assert fake_node.live_subscriptions == []

    def test_clean_stop_reports_no_error(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        rosbag = os.path.join(recorder.session_path, 'rosbag')
        qtbot.waitUntil(lambda: os.path.exists(os.path.join(rosbag, 'ready')), timeout=10000)

        recorder.stop_recording(fake_node)

        assert log == {'errors': [], 'stopped': 1}
        assert os.path.exists(os.path.join(rosbag, 'metadata.yaml'))
        assert 'forced_stop' not in _sync_info(recorder)

    def test_recorder_exit_during_recording_is_reported(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        pid = recorder._bag_proc._proc.processId()

        with qtbot.waitSignal(recorder.error_occurred, timeout=10000):
            os.kill(pid, signal.SIGINT)

        assert not recorder.is_recording
        assert len(log['errors']) == 1
        assert log['stopped'] == 1
        assert fake_node.live_subscriptions == []
        assert _sync_info(recorder)['forced_stop'] is True

    def test_recorder_that_exits_right_after_start_is_reported(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        monkeypatch.setenv('FAKE_ROS2_MODE', 'fail')
        recorder, log = _recorder_with_log()

        with qtbot.waitSignal(recorder.error_occurred, timeout=10000):
            recorder.start_recording(_config(tmp_path), fake_node)

        assert not recorder.is_recording
        assert len(log['errors']) == 1
        assert 'exit code 3' in log['errors'][0]

    def test_stop_reports_recorder_that_had_already_died(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        pid = recorder._bag_proc._proc.processId()
        os.kill(pid, signal.SIGKILL)
        # Wait for the death without letting Qt see it: Stop arrives before the event loop does.
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)

        recorder.stop_recording(fake_node)

        assert not recorder.is_recording
        assert len(log['errors']) == 1
        assert _sync_info(recorder)['forced_stop'] is True

    def test_stop_works_without_a_node(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True

        recorder.stop_recording(None)

        assert not recorder.is_recording
        assert fake_node.live_subscriptions == []
        assert log['errors'] == []
