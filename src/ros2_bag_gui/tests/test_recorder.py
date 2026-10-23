"""Tests for recorder."""
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace
import pytest
import yaml
from PySide6.QtWidgets import QApplication
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from ros2bag.api import convert_yaml_to_qos_profile
from ros2_bag_gui.ros2.recorder import (
    should_include_in_rosbag, should_record_lidar_laz, lidar_group_of,
    RecordingConfig, Recorder, SYSTEM_EXCLUDE, unloadable_types,
)

ALL_BAG = {'boom': 'bag', 'cabin': 'bag'}

class TestTopicExclusion:
    def test_lidar_points_excluded_in_laz_mode(self):
        assert not should_include_in_rosbag(
            '/lidar_boom/points', {'boom': 'laz'}, camera_mode='bag')

    def test_lidar_points_included_in_bag_mode(self):
        assert should_include_in_rosbag('/lidar_boom/points', ALL_BAG, camera_mode='bag')

    def test_lidar_points_included_in_both_mode(self):
        assert should_include_in_rosbag(
            '/lidar_boom/points', {'boom': 'both'}, camera_mode='bag')

    def test_rosout_excluded(self):
        assert not should_include_in_rosbag('/rosout', ALL_BAG, camera_mode='bag')

    def test_camera_image_excluded_in_svo2_mode(self):
        assert not should_include_in_rosbag(
            '/zedx_boom/zedx_node/left/image_rect_color',
            ALL_BAG, camera_mode='svo2',
        )

    def test_camera_image_included_in_bag_mode(self):
        assert should_include_in_rosbag(
            '/zedx_boom/zedx_node/left/image_rect_color',
            ALL_BAG, camera_mode='bag',
        )

    def test_normal_topic_included(self):
        assert should_include_in_rosbag('/excavator/status', ALL_BAG, camera_mode='bag')
        assert should_include_in_rosbag('/tf', ALL_BAG, camera_mode='bag')

    def test_gps_topic_included(self):
        assert should_include_in_rosbag('/gps_interface/position', ALL_BAG, camera_mode='bag')

    def test_one_lidar_leaves_the_bag_while_the_other_stays(self):
        modes = {'boom': 'laz', 'cabin': 'bag'}
        assert not should_include_in_rosbag('/lidar_boom/points', modes, camera_mode='bag')
        assert should_include_in_rosbag('/lidar_cabin/points', modes, camera_mode='bag')

    def test_the_cabin_can_be_the_one_that_leaves_the_bag(self):
        modes = {'boom': 'bag', 'cabin': 'laz'}
        assert should_include_in_rosbag('/lidar_boom/points', modes, camera_mode='bag')
        assert not should_include_in_rosbag('/lidar_cabin/points', modes, camera_mode='bag')


class TestLidarGroups:
    def test_ouster_points_is_the_boom_lidar(self):
        assert lidar_group_of('/ouster/points') == 'boom'
        assert lidar_group_of('/lidar_boom/points') == 'boom'

    def test_cabin_points_is_the_cabin_lidar(self):
        assert lidar_group_of('/lidar_cabin/points') == 'cabin'

    def test_other_topics_belong_to_no_lidar(self):
        assert lidar_group_of('/tf') is None


class TestLidarLaz:
    def test_lidar_recorded_to_laz(self):
        assert should_record_lidar_laz('/lidar_boom/points', {'boom': 'laz'})

    def test_lidar_not_recorded_in_bag_only(self):
        assert not should_record_lidar_laz('/lidar_boom/points', ALL_BAG)

    def test_non_lidar_not_recorded(self):
        assert not should_record_lidar_laz('/tf', {'boom': 'laz'})

    def test_each_lidar_follows_its_own_mode(self):
        modes = {'boom': 'laz', 'cabin': 'bag'}
        assert should_record_lidar_laz('/lidar_boom/points', modes)
        assert not should_record_lidar_laz('/lidar_cabin/points', modes)

    def test_cabin_is_recorded_to_laz_when_asked_for(self):
        assert should_record_lidar_laz('/lidar_cabin/points', {'cabin': 'both'})


class TestRecordingConfig:
    def test_default_max_bagfile_size(self):
        config = RecordingConfig(
            topics=[],
            output_path='/tmp',
            session_name='test'
        )
        assert config.max_bagfile_size == 3 * 1024**3


class TestUnloadableTypes:
    def test_types_the_recorder_cannot_load_are_found_before_start(self):
        topics = [
            {'name': '/ok', 'type': 'std_msgs/msg/String'},
            {'name': '/no_package', 'type': 'no_such_pkg/msg/Nope'},
            # The package is there, but built without this type (an older build)
            {'name': '/no_type', 'type': 'std_msgs/msg/NoSuchType'},
            {'name': '/not_up_yet', 'type': 'unknown'},
        ]

        assert unloadable_types(topics) == {
            '/no_package': 'no_such_pkg/msg/Nope',
            '/no_type': 'std_msgs/msg/NoSuchType',
        }


class TestRecorder:
    def test_initial_state(self, qtbot):
        recorder = Recorder()
        assert not recorder.is_recording

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

    def test_sync_info_holds_the_counts_of_the_bag(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        monkeypatch.setenv('FAKE_ROS2_COUNTS', json.dumps({'/excavator/status': 42}))
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
        qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)

        recorder.stop_recording(fake_node)

        sync = _sync_info(recorder)
        assert sync['topic_message_counts'] == {'/excavator/status': 42}
        assert recorder.last_bag_counts == {'/excavator/status': 42}

    def test_sync_info_of_a_killed_recorder_has_no_made_up_counts(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True

        with qtbot.waitSignal(recorder.error_occurred, timeout=10000):
            os.kill(recorder._bag_proc._proc.processId(), signal.SIGKILL)

        sync = _sync_info(recorder)
        assert sync['topic_message_counts'] is None
        assert sync['data_sources']['rosbag']['topic_count'] == 1  # the topics asked for
        assert recorder.last_bag_counts is None

    def test_start_is_refused_when_the_disk_is_nearly_full(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        from collections import namedtuple
        usage = namedtuple('usage', 'total used free')
        monkeypatch.setattr('shutil.disk_usage', lambda path: usage(400 * 1024**2, 0, 400 * 1024**2))
        recorder, log = _recorder_with_log()

        assert recorder.start_recording(_config(tmp_path), fake_node) is False

        assert not recorder.is_recording
        assert recorder._bag_proc is None
        assert len(log['errors']) == 1
        assert os.listdir(tmp_path / 'out') == []

    def test_disk_reason_survives_a_session_folder_that_already_holds_data(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        from collections import namedtuple
        usage = namedtuple('usage', 'total used free')
        monkeypatch.setattr('shutil.disk_usage', lambda path: usage(400 * 1024**2, 0, 400 * 1024**2))
        session = tmp_path / 'out' / 'recording_2026-01-01_00-00-00_t'
        session.mkdir(parents=True)
        leftover = session / 'rosbag_0.db3'
        leftover.write_bytes(b'x')
        monkeypatch.setattr(Recorder, '_generate_session_path', lambda self: str(session))
        recorder, log = _recorder_with_log()

        assert recorder.start_recording(_config(tmp_path), fake_node) is False

        assert 'GB free' in log['errors'][0]
        assert leftover.exists()

    def test_forced_stop_reason_is_written_to_sync_info(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True

        recorder.stop_recording(fake_node, "disk nearly full")

        sync = _sync_info(recorder)
        assert sync['forced_stop'] is True
        assert sync['stop_reason'] == "disk nearly full"
        assert log['errors'] == []

    def test_split_by_time_is_passed_to_the_recorder(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        args_file = tmp_path / 'bag_args.json'
        monkeypatch.setenv('FAKE_ROS2_ARGS', str(args_file))
        recorder, log = _recorder_with_log()

        assert recorder.start_recording(
            _config(tmp_path, max_bagfile_size=0, max_bag_duration=1800), fake_node) is True
        ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
        qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)
        recorder.stop_recording(fake_node)

        bag_args = json.loads(args_file.read_text())
        assert bag_args[bag_args.index('--max-bag-duration') + 1] == '1800'
        assert '--max-bag-size' not in bag_args

    def test_recorder_problem_output_reaches_the_log(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch, caplog):
        monkeypatch.setenv('FAKE_ROS2_MODE', 'warn')
        # Under pytest in a ROS environment the package loggers do not propagate
        # (test_logging_config.py works around the same thing).
        monkeypatch.setattr(logging.getLogger('ros2_bag_gui.ros2.bag_process'), 'propagate', True)
        caplog.set_level(logging.INFO)
        recorder, log = _recorder_with_log()

        assert recorder.start_recording(_config(tmp_path), fake_node) is True

        # The session log file keeps INFO and above; the console shows WARNING and above.
        qtbot.waitUntil(
            lambda: any(r.levelno >= logging.WARNING and 'lost messages' in r.getMessage()
                        for r in caplog.records),
            timeout=10000,
        )
        recorder.stop_recording(fake_node)

    def test_recorder_problem_output_is_shown_and_kept(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        monkeypatch.setenv('FAKE_ROS2_MODE', 'warn')
        recorder, log = _recorder_with_log()
        warnings = []
        recorder.warning_occurred.connect(warnings.append)

        with qtbot.waitSignal(recorder.warning_occurred, timeout=10000):
            recorder.start_recording(_config(tmp_path), fake_node)
        recorder.stop_recording(fake_node)

        assert len(warnings) == 1
        assert log['errors'] == []
        assert len(_sync_info(recorder)['recorder_warnings']) == 1

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

    def test_recorder_that_exits_right_after_start_is_a_failed_start(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        from ros2_bag_gui.ros2.bag_process import BagProcess
        monkeypatch.setattr(BagProcess, 'STARTUP_GRACE_MS', 5000, raising=False)
        monkeypatch.setenv('FAKE_ROS2_MODE', 'fail')
        recorder, log = _recorder_with_log()
        warnings = []
        recorder.warning_occurred.connect(warnings.append)

        started = recorder.start_recording(_config(tmp_path), fake_node)
        QApplication.processEvents()

        assert started is False
        assert not recorder.is_recording
        assert len(log['errors']) == 1 and warnings == []  # one event, one dialog
        assert 'exit code 3' in log['errors'][0]
        assert fake_node.live_subscriptions == []
        assert os.listdir(tmp_path / 'out') == []

    def test_stop_that_has_to_kill_the_recorder_is_reported(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        from ros2_bag_gui.ros2.bag_process import BagProcess
        monkeypatch.setattr(BagProcess, 'STOP_GRACE_MS', 300, raising=False)
        monkeypatch.setattr(BagProcess, 'STOP_POLL_MS', 100, raising=False)
        monkeypatch.setenv('FAKE_ROS2_MODE', 'hang')
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
        qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)

        recorder.stop_recording(fake_node)

        assert len(log['errors']) == 1
        sync = _sync_info(recorder)
        assert sync['forced_stop'] is True
        assert sync['topic_message_counts'] is None

    def test_stop_waits_for_a_recorder_that_is_still_writing(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        from ros2_bag_gui.ros2.bag_process import BagProcess
        monkeypatch.setattr(BagProcess, 'STOP_GRACE_MS', 200)  # shorter than the slow close
        monkeypatch.setattr(BagProcess, 'STOP_POLL_MS', 100)
        monkeypatch.setenv('FAKE_ROS2_MODE', 'slowclose')
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        rosbag = os.path.join(recorder.session_path, 'rosbag')
        qtbot.waitUntil(lambda: os.path.exists(os.path.join(rosbag, 'ready')), timeout=10000)

        recorder.stop_recording(fake_node)

        assert log['errors'] == []
        assert os.path.exists(os.path.join(rosbag, 'metadata.yaml'))

    def test_what_the_recorder_says_while_closing_is_shown(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        monkeypatch.setenv('FAKE_ROS2_MODE', 'warn_on_close')
        recorder, log = _recorder_with_log()
        warnings = []
        recorder.warning_occurred.connect(warnings.append)
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
        qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)

        recorder.stop_recording(fake_node)

        assert len(warnings) == 1 and 'Total lost: 12' in warnings[0]
        assert 'Total lost: 12' in _sync_info(recorder)['recorder_warnings']

    def test_info_line_that_mentions_lost_is_not_a_problem(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        monkeypatch.setenv('FAKE_ROS2_MODE', 'info_lost')
        recorder, log = _recorder_with_log()
        warnings = []
        recorder.warning_occurred.connect(warnings.append)
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
        qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)
        QApplication.processEvents()

        recorder.stop_recording(fake_node)

        assert warnings == []
        assert 'recorder_warnings' not in _sync_info(recorder)

    @pytest.mark.parametrize("topic, warned", [
        ('/excavator/status', False),  # the note is about topics nobody asked for
        ('/_internal/status', True),   # a hidden topic was asked for: it is not recorded
    ])
    def test_hidden_topics_note_matters_only_for_a_selected_hidden_topic(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch, topic, warned):
        monkeypatch.setenv('FAKE_ROS2_MODE', 'hidden')
        recorder, log = _recorder_with_log()
        warnings = []
        recorder.warning_occurred.connect(warnings.append)
        config = _config(tmp_path)
        config.topics = [{'name': topic, 'type': 'std_msgs/msg/String'}]
        assert recorder.start_recording(config, fake_node) is True
        ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
        qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)

        recorder.stop_recording(fake_node)  # also reads what it said before it ended

        assert len(warnings) == int(warned)
        assert ('recorder_warnings' in _sync_info(recorder)) == warned
        assert log['errors'] == []

    def test_a_topic_the_recorder_cannot_subscribe_to_is_an_error_shown_once(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        monkeypatch.setenv('FAKE_ROS2_MODE', 'discovery_failure')
        recorder = Recorder()
        errors, warnings = [], []
        recorder.error_occurred.connect(errors.append)
        recorder.warning_occurred.connect(warnings.append)

        with qtbot.waitSignal(recorder.error_occurred, timeout=10000):
            recorder.start_recording(_config(tmp_path), fake_node)
        recorder.stop_recording(fake_node)

        assert len(errors) == 1
        assert 'excavator_msgs/WorkAnchorStatus' in errors[0]
        assert warnings == []
        sync = _sync_info(recorder)
        assert len(sync['recorder_subscription_failures']) == 1  # said on every pass, kept once
        assert 'recorder_warnings' not in sync

    def test_suspended_recorder_is_reported_and_can_still_be_stopped(
            self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        warnings = []
        recorder.warning_occurred.connect(warnings.append)
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        rosbag = os.path.join(recorder.session_path, 'rosbag')
        qtbot.waitUntil(lambda: os.path.exists(os.path.join(rosbag, 'ready')), timeout=10000)
        pid = recorder._bag_proc.pid
        os.kill(pid, signal.SIGSTOP)
        os.waitid(os.P_PID, pid, os.WSTOPPED | os.WNOWAIT)

        recorder.check_health()
        recorder.check_health()

        assert len(warnings) == 1  # once, not once a second
        recorder.stop_recording(fake_node)
        assert log['errors'] == []
        assert os.path.exists(os.path.join(rosbag, 'metadata.yaml'))

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

    def test_second_start_is_refused_and_first_keeps_recording(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        first = recorder._bag_proc

        assert recorder.start_recording(_config(tmp_path), fake_node) is False

        assert recorder.is_recording
        assert recorder._bag_proc is first and first.is_running
        assert len(log['errors']) == 1
        recorder.stop_recording(fake_node)
        assert not first.is_running

    def test_stop_works_without_a_node(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True

        recorder.stop_recording(None)

        assert not recorder.is_recording
        assert fake_node.live_subscriptions == []
        assert log['errors'] == []


# A minimal "GUI": starts the recorder through BagProcess, prints its pid, then idles.
_GUI_PROCESS = """
import sys
from PySide6.QtCore import QCoreApplication
from ros2_bag_gui.ros2.bag_process import BagProcess
app = QCoreApplication([])
bag = BagProcess()
bag.start(sys.argv[1], ['/excavator/status'])
print(bag._proc.processId(), flush=True)
app.exec()
"""


class TestOrphanedRecorder:

    def test_recorder_closes_the_bag_when_the_gui_is_killed(self, qtbot, tmp_path, fake_ros2):
        rosbag = tmp_path / 'rosbag'
        gui = subprocess.Popen(
            [sys.executable, '-c', _GUI_PROCESS, str(rosbag)], stdout=subprocess.PIPE, text=True)
        recorder_pid = int(gui.stdout.readline())
        try:
            qtbot.waitUntil(lambda: (rosbag / 'ready').exists(), timeout=10000)

            gui.kill()
            gui.wait()

            # The stand-in recorder writes metadata.yaml only when it is told to stop.
            qtbot.waitUntil(lambda: (rosbag / 'metadata.yaml').exists(), timeout=10000)
        finally:
            try:
                os.kill(recorder_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_a_recorder_left_running_is_found(self, qtbot, tmp_path, fake_ros2):
        from ros2_bag_gui.ros2.bag_process import find_other_recorders
        rosbag = tmp_path / 'rosbag'
        stray = subprocess.Popen([fake_ros2, 'bag', 'record', '-o', str(rosbag), '/excavator/status'])
        try:
            qtbot.waitUntil(lambda: (rosbag / 'ready').exists(), timeout=10000)

            assert stray.pid in find_other_recorders()
            assert stray.pid not in find_other_recorders(exclude_pids=[stray.pid])
        finally:
            stray.kill()
            stray.wait()


STATUS = {'name': '/excavator/status', 'type': 'std_msgs/msg/String'}
BOOM_IMAGE = {'name': '/zedx_boom/zed_node/left/image_rect_color', 'type': 'sensor_msgs/msg/Image'}
CABIN_IMAGE = {'name': '/zedx_cabin/zed_node/left/image_rect_color', 'type': 'sensor_msgs/msg/Image'}
BOOM_CLOUD = {'name': '/lidar_boom/points', 'type': 'sensor_msgs/msg/PointCloud2'}
OUSTER_CLOUD = {'name': '/ouster/points', 'type': 'sensor_msgs/msg/PointCloud2'}
CABIN_CLOUD = {'name': '/lidar_cabin/points', 'type': 'sensor_msgs/msg/PointCloud2'}


def _cloud_bytes(stamp_sec):
    """A serialized two-point PointCloud2, as the LAZ subscription receives it."""
    import numpy as np
    from rclpy.serialization import serialize_message
    from sensor_msgs.msg import PointCloud2, PointField
    msg = PointCloud2()
    msg.header.stamp.sec = stamp_sec
    msg.height, msg.width, msg.point_step, msg.row_step, msg.is_dense = 1, 2, 12, 24, True
    msg.fields = [PointField(name=n, offset=4 * i, datatype=7, count=1) for i, n in enumerate('xyz')]
    msg.data = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32).tobytes()
    return serialize_message(msg)


def _laz_callback(node, topic):
    """The LAZ subscription of a topic: it is created before the monitoring one."""
    return next(s['callback'] for s in node.subscriptions if s['topic'] == topic)


def _laz_files(recorder):
    found = []
    for root, _dirs, files in os.walk(os.path.join(recorder.session_path, 'pointcloud')):
        found += [os.path.join(root, f) for f in files if f.endswith('.laz')]
    return found


def _fake_zed_sdk(monkeypatch, opens=True, fail_after_grabs=None,
                  cameras=(('45233238', 'ZED X', True),)):
    """A stand-in for pyzed.sl: a camera that opens (or not) and delivers frames."""
    sl = SimpleNamespace(grabs=0, frame_period=threading.Event(), serial_asked_for=None)
    sl.ERROR_CODE = SimpleNamespace(
        SUCCESS='SUCCESS', END_OF_SVOFILE_REACHED='EOF', FAILURE='CAMERA NOT DETECTED')
    sl.DEPTH_MODE = SimpleNamespace(NONE=0)
    sl.RESOLUTION = SimpleNamespace(HD1200=1)
    sl.SVO_COMPRESSION_MODE = SimpleNamespace(H265=1)
    class InitParameters(SimpleNamespace):
        def set_from_serial_number(self, serial):
            sl.serial_asked_for = serial

    sl.InitParameters = InitParameters
    sl.RecordingParameters = SimpleNamespace
    sl.RuntimeParameters = SimpleNamespace

    class Camera:
        def open(self, params):
            return sl.ERROR_CODE.SUCCESS if opens else sl.ERROR_CODE.FAILURE

        def enable_recording(self, params):
            open(params.video_filename, 'wb').close()
            return sl.ERROR_CODE.SUCCESS

        def grab(self, runtime):
            sl.frame_period.wait(0.005)  # the camera's frame period
            sl.grabs += 1
            if fail_after_grabs is not None and sl.grabs > fail_after_grabs:
                raise RuntimeError("camera disconnected")
            return sl.ERROR_CODE.SUCCESS

        def disable_recording(self):
            pass

        def close(self):
            pass

    sl.Camera = Camera
    monkeypatch.setattr('ros2_bag_gui.zed.svo_writer.get_sl_module', lambda: sl)
    monkeypatch.setattr('ros2_bag_gui.ros2.recorder.is_zed_sdk_available', lambda: True)
    monkeypatch.setattr('ros2_bag_gui.ros2.recorder.list_zed_cameras', lambda: list(cameras))
    return sl


def _fake_zed_driver(node, camera='zedx_cabin', recording=False, fails=None):
    """A running ZED ROS driver: records its camera to SVO2 on request, as zed_wrapper does."""
    path = f'/{camera}/{camera}_node'
    driver = SimpleNamespace(recording=recording, files=[], stops=0)

    def start(request):
        if fails:
            return SimpleNamespace(success=False, message=fails)
        if driver.recording:
            return SimpleNamespace(success=False, message='SVO Recording is already enabled')
        driver.recording = True
        driver.files.append(request.svo_filename)
        open(request.svo_filename, 'wb').close()
        return SimpleNamespace(success=True, message='SVO Recording started')

    def stop(_request):
        driver.stops += 1
        was_recording, driver.recording = driver.recording, False
        return SimpleNamespace(success=was_recording, message='SVO Recording stopped')

    node.services[f'{path}/start_svo_rec'] = ('zed_msgs/srv/StartSvoRec', start)
    node.services[f'{path}/stop_svo_rec'] = ('std_srvs/srv/Trigger', stop)
    return driver


class TestSideRecorders:
    """A topic leaves the bag only when the recorder that takes it instead is running."""

    @pytest.fixture
    def session(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        args_file = tmp_path / 'bag_args.json'
        monkeypatch.setenv('FAKE_ROS2_ARGS', str(args_file))
        recorder, log = _recorder_with_log()
        log['warnings'] = []
        recorder.warning_occurred.connect(log['warnings'].append)

        def start(topics, **modes):
            config = RecordingConfig(
                topics=topics, output_path=str(tmp_path / 'out'), session_name='t', **modes)
            assert recorder.start_recording(config, fake_node) is True
            ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
            qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)
            return json.loads(args_file.read_text())

        yield SimpleNamespace(recorder=recorder, log=log, start=start, node=fake_node)
        recorder.stop_recording(fake_node)

    def test_svo2_without_sdk_keeps_images_in_bag(self, session, monkeypatch):
        monkeypatch.setattr('ros2_bag_gui.ros2.recorder.is_zed_sdk_available', lambda: False)

        bag_args = session.start([STATUS, BOOM_IMAGE], camera_mode='svo2')

        assert BOOM_IMAGE['name'] in bag_args
        assert len(session.log['warnings']) == 1
        session.recorder.stop_recording()
        sync = _sync_info(session.recorder)
        assert sync['recording_modes']['camera'] == 'bag'
        assert len(sync['notices']) == 1

    def test_svo2_camera_that_does_not_open_keeps_images_in_bag(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch, opens=False)

        bag_args = session.start([STATUS, BOOM_IMAGE], camera_mode='svo2')
        QApplication.processEvents()  # deliver the writer's queued error, if any

        assert BOOM_IMAGE['name'] in bag_args
        assert len(session.log['warnings']) == 1
        assert session.log['errors'] == []  # reported once, as the warning

    def test_svo2_recording_takes_images_out_of_the_bag(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch)

        bag_args = session.start([STATUS, BOOM_IMAGE], camera_mode='svo2')

        assert BOOM_IMAGE['name'] not in bag_args
        assert STATUS['name'] in bag_args
        assert session.log['warnings'] == []
        session.recorder.stop_recording()
        assert os.path.exists(os.path.join(session.recorder.session_path, 'camera_0.svo2'))
        assert _sync_info(session.recorder)['recording_modes']['camera'] == 'svo2'

    def test_svo2_keeps_images_that_ros_publishes_in_the_bag(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch)
        # The cabin driver publishes, so it holds the cabin camera: SVO2 records another one.
        session.node.publishers[CABIN_IMAGE['name']] = [SimpleNamespace()]

        bag_args = session.start([STATUS, CABIN_IMAGE], camera_mode='svo2')

        assert CABIN_IMAGE['name'] in bag_args
        assert session.log['warnings'] == []
        session.recorder.stop_recording()
        sync = _sync_info(session.recorder)
        assert sync['recording_modes']['camera'] == 'both'
        assert sync['data_sources']['svo2']['file_count'] == 1

    def test_svo2_failure_while_recording_is_reported(self, session, qtbot, monkeypatch):
        _fake_zed_sdk(monkeypatch, fail_after_grabs=3)

        with qtbot.waitSignal(session.recorder.error_occurred, timeout=10000):
            session.start([STATUS, BOOM_IMAGE], camera_mode='svo2')

        assert len(session.log['errors']) == 1
        assert session.recorder.is_recording  # the bag goes on

    def test_lidar_that_laz_cannot_subscribe_to_stays_in_bag(self, session):
        cloud = {'name': BOOM_CLOUD['name'], 'type': 'no_such_pkg/msg/Nope'}

        bag_args = session.start([STATUS, cloud], lidar_modes={'boom': 'laz'})

        assert cloud['name'] in bag_args
        assert len(session.log['warnings']) == 1

    def test_lidar_mode_says_bag_when_no_laz_subscription_starts(self, session):
        cloud = {'name': BOOM_CLOUD['name'], 'type': 'no_such_pkg/msg/Nope'}

        session.start([STATUS, cloud], lidar_modes={'boom': 'laz'})
        session.recorder.stop_recording()

        assert _sync_info(session.recorder)['recording_modes']['lidar'] == {'boom': 'bag'}

    def test_laz_recording_takes_lidar_out_of_the_bag(self, session):
        bag_args = session.start([STATUS, BOOM_CLOUD], lidar_modes={'boom': 'laz'})

        assert BOOM_CLOUD['name'] not in bag_args
        assert session.log['warnings'] == []

    def test_two_lidars_do_not_overwrite_each_others_laz_files(self, session):
        session.start([STATUS, BOOM_CLOUD, OUSTER_CLOUD], lidar_modes={'boom': 'laz'})
        same_instant = _cloud_bytes(1_700_000_000)

        _laz_callback(session.node, BOOM_CLOUD['name'])(same_instant)
        _laz_callback(session.node, OUSTER_CLOUD['name'])(same_instant)
        session.recorder.stop_recording()

        files = _laz_files(session.recorder)
        assert len(files) == 2
        assert len({os.path.dirname(f) for f in files}) == 2
        pointcloud = _sync_info(session.recorder)['data_sources']['pointcloud']
        assert pointcloud['file_count'] == 2
        assert {t: v['file_count'] for t, v in pointcloud['topics'].items()} == {
            BOOM_CLOUD['name']: 1, OUSTER_CLOUD['name']: 1,
        }

    def test_one_lidar_keeps_the_flat_pointcloud_folder(self, session):
        session.start([STATUS, BOOM_CLOUD], lidar_modes={'boom': 'laz'})

        _laz_callback(session.node, BOOM_CLOUD['name'])(_cloud_bytes(1_700_000_000))
        session.recorder.stop_recording()

        pointcloud_dir = os.path.join(session.recorder.session_path, 'pointcloud')
        assert os.listdir(pointcloud_dir) == ['1700000000000000000.laz']

    def test_only_the_lidar_asked_for_laz_leaves_the_bag(self, session):
        bag_args = session.start(
            [BOOM_CLOUD, CABIN_CLOUD], lidar_modes={'boom': 'laz', 'cabin': 'bag'})

        assert BOOM_CLOUD['name'] not in bag_args
        assert CABIN_CLOUD['name'] in bag_args
        session.recorder.stop_recording()
        assert _sync_info(session.recorder)['recording_modes']['lidar'] == {
            'boom': 'laz', 'cabin': 'bag'}

    def test_the_cabin_alone_can_be_recorded_to_laz(self, session):
        bag_args = session.start(
            [BOOM_CLOUD, CABIN_CLOUD], lidar_modes={'boom': 'bag', 'cabin': 'laz'})

        assert BOOM_CLOUD['name'] in bag_args
        assert CABIN_CLOUD['name'] not in bag_args
        _laz_callback(session.node, CABIN_CLOUD['name'])(_cloud_bytes(1_700_000_001))
        session.recorder.stop_recording()

        assert len(_laz_files(session.recorder)) == 1
        pointcloud = _sync_info(session.recorder)['data_sources']['pointcloud']
        assert list(pointcloud['topics']) == [CABIN_CLOUD['name']]

    def test_start_is_refused_when_no_topic_would_go_into_the_bag(
            self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        config = RecordingConfig(
            topics=[BOOM_CLOUD, CABIN_CLOUD],
            output_path=str(tmp_path / 'out'),
            session_name='t',
            lidar_modes={'boom': 'laz', 'cabin': 'laz'},
        )

        assert recorder.start_recording(config, fake_node) is False

        assert not recorder.is_recording
        assert recorder._bag_proc is None
        assert 'into the bag' in log['errors'][0]
        assert os.listdir(tmp_path / 'out') == []

    def test_both_lidars_in_laz_get_a_folder_each(self, session):
        session.start(
            [STATUS, BOOM_CLOUD, CABIN_CLOUD],
            lidar_modes={'boom': 'laz', 'cabin': 'laz'})
        same_instant = _cloud_bytes(1_700_000_000)

        _laz_callback(session.node, BOOM_CLOUD['name'])(same_instant)
        _laz_callback(session.node, CABIN_CLOUD['name'])(same_instant)
        session.recorder.stop_recording()

        files = _laz_files(session.recorder)
        assert len(files) == 2
        assert len({os.path.dirname(f) for f in files}) == 2
        pointcloud = _sync_info(session.recorder)['data_sources']['pointcloud']
        assert {t: v['file_count'] for t, v in pointcloud['topics'].items()} == {
            BOOM_CLOUD['name']: 1, CABIN_CLOUD['name']: 1,
        }

    def test_dropped_laz_frames_are_counted_and_reported(self, session, monkeypatch):
        from ros2_bag_gui.ros2.laz_writer import LAZWriterThread
        writer_may_run = threading.Event()
        write = LAZWriterThread._handle_item

        def slow_disk(self, item):
            writer_may_run.wait(10)
            write(self, item)

        monkeypatch.setattr(LAZWriterThread, '_handle_item', slow_disk)
        monkeypatch.setattr(LAZWriterThread, 'QUEUE_MAXSIZE', 1)
        session.start([STATUS, BOOM_CLOUD], lidar_modes={'boom': 'laz'})

        for i in range(5):
            _laz_callback(session.node, BOOM_CLOUD['name'])(_cloud_bytes(1_700_000_000 + i))
        writer_may_run.set()
        session.recorder.stop_recording()

        pointcloud = _sync_info(session.recorder)['data_sources']['pointcloud']
        assert pointcloud['dropped_frames'] >= 3
        assert pointcloud['dropped_frames'] + len(_laz_files(session.recorder)) == 5
        assert len(session.log['warnings']) >= 1

    def test_frames_missing_between_laz_files_are_reported(self, session):
        session.start([STATUS, BOOM_CLOUD], lidar_modes={'boom': 'laz'})

        for second in (0, 1, 2, 5):  # the frames of seconds 3 and 4 never arrive
            _laz_callback(session.node, BOOM_CLOUD['name'])(_cloud_bytes(1_700_000_000 + second))
        session.recorder.stop_recording()

        pointcloud = _sync_info(session.recorder)['data_sources']['pointcloud']
        assert pointcloud['topics'][BOOM_CLOUD['name']]['missing_frames_est'] == 2
        assert pointcloud['dropped_frames'] == 0
        assert any('about 2 of 6 frames' in w for w in session.log['warnings'])

    @pytest.mark.parametrize("publishers, expected", [
        (['RELIABLE'], 'RELIABLE'),                    # the Ouster driver
        (['RELIABLE', 'BEST_EFFORT'], 'BEST_EFFORT'),  # reliable would not match the second
        ([], 'BEST_EFFORT'),                           # not up yet: matches whatever comes
    ])
    def test_laz_subscription_is_reliable_when_every_publisher_is(
            self, session, publishers, expected):
        from rclpy.qos import QoSProfile, QoSReliabilityPolicy
        session.node.publishers[BOOM_CLOUD['name']] = [
            SimpleNamespace(qos_profile=QoSProfile(depth=1, reliability=QoSReliabilityPolicy[r]))
            for r in publishers
        ]

        session.start([STATUS, BOOM_CLOUD], lidar_modes={'boom': 'laz'})

        qos = next(s['qos'] for s in session.node.subscriptions if s['topic'] == BOOM_CLOUD['name'])
        assert qos.reliability == QoSReliabilityPolicy[expected]

    def test_recorded_topics_are_not_received_again_just_to_count_them(self, session):
        session.start([STATUS, BOOM_IMAGE, BOOM_CLOUD], lidar_modes={'boom': 'both'})

        # Only the LAZ writer subscribes; what is in the bag is read from it at Stop.
        assert [s['topic'] for s in session.node.subscriptions] == [BOOM_CLOUD['name']]

    def test_a_camera_whose_driver_runs_is_recorded_by_the_driver(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False)])  # held by its driver
        driver = _fake_zed_driver(session.node)
        session.node.publishers[CABIN_IMAGE['name']] = [SimpleNamespace()]

        bag_args = session.start([STATUS, CABIN_IMAGE], camera_mode='svo2')

        assert CABIN_IMAGE['name'] not in bag_args  # the driver's SVO2 has that camera
        assert driver.files == [os.path.join(session.recorder.session_path, 'zedx_cabin.svo2')]
        assert session.log['warnings'] == []
        session.recorder.stop_recording()
        assert not driver.recording
        sync = _sync_info(session.recorder)
        assert sync['recording_modes']['camera'] == 'svo2'
        assert sync['data_sources']['svo2']['path'] == ['zedx_cabin.svo2']

    def test_driver_and_direct_svo2_record_both_cameras(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False), ('45233238', 'ZED X', True)])
        _fake_zed_driver(session.node)

        session.start([STATUS, CABIN_IMAGE], camera_mode='svo2')
        session.recorder.stop_recording()

        svo2 = _sync_info(session.recorder)['data_sources']['svo2']['path']
        assert sorted(svo2) == ['camera_0.svo2', 'zedx_cabin.svo2']

    def test_a_driver_that_cannot_record_keeps_its_images_in_the_bag(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False)])
        _fake_zed_driver(session.node, fails='Error starting SVO recording: NO GPU COMPATIBLE')
        session.node.publishers[CABIN_IMAGE['name']] = [SimpleNamespace()]

        bag_args = session.start([STATUS, CABIN_IMAGE], camera_mode='svo2')

        assert CABIN_IMAGE['name'] in bag_args
        assert len(session.log['warnings']) == 1

    def test_a_driver_already_recording_holds_the_start(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False)])
        driver = _fake_zed_driver(fake_node, recording=True)  # left over from a GUI that was killed
        recorder = Recorder()
        errors = []
        recorder.error_occurred.connect(errors.append)
        config = _config(tmp_path, camera_mode='svo2')

        assert recorder.start_recording(config, fake_node) is False
        assert errors == []  # the operator is asked instead
        assert recorder.busy_svo_drivers == ['/zedx_cabin/zedx_cabin_node']
        assert os.listdir(tmp_path / 'out') == []

        assert recorder.stop_driver_svo2(recorder.busy_svo_drivers, fake_node) == []
        assert recorder.start_recording(config, fake_node) is True
        recorder.stop_recording(fake_node)
        assert driver.stops == 2  # the left-over recording, then this session's
        assert errors == []

    def test_svo2_only_records_without_a_bag(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False)])
        driver = _fake_zed_driver(fake_node)
        recorder = Recorder()
        errors = []
        recorder.error_occurred.connect(errors.append)
        config = RecordingConfig(
            topics=[], output_path=str(tmp_path / 'out'), session_name='t', camera_mode='svo2')

        assert recorder.start_recording(config, fake_node) is True
        assert recorder._bag_proc is None  # no ros2 bag record
        recorder.stop_recording(fake_node)

        assert not driver.recording
        assert errors == []
        sync = _sync_info(recorder)
        assert 'rosbag' not in sync['data_sources']
        assert sync['data_sources']['svo2']['path'] == ['zedx_cabin.svo2']

    def test_start_is_refused_when_nothing_at_all_would_be_recorded(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[])  # no camera to open, no driver to ask
        recorder, log = _recorder_with_log()
        config = RecordingConfig(
            topics=[], output_path=str(tmp_path / 'out'), session_name='t', camera_mode='svo2')

        assert recorder.start_recording(config, fake_node) is False

        assert recorder._bag_proc is None
        assert os.listdir(tmp_path / 'out') == []

    def test_stopping_a_driver_waits_longer_than_starting_it(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False)])
        _fake_zed_driver(session.node)
        waits = []
        call = Recorder._call_service

        def note(self, node, srv_type, name, timeout_s=None, **fields):
            waits.append((name.rsplit('/', 1)[-1], timeout_s))
            return call(self, node, srv_type, name, timeout_s=timeout_s, **fields)

        monkeypatch.setattr(Recorder, '_call_service', note)
        session.start([STATUS], camera_mode='svo2')
        session.recorder.stop_recording()

        # Closing the SVO2 file flushes its encoder, so it may answer later than a start
        assert waits == [('start_svo_rec', None), ('stop_svo_rec', Recorder.SVO_STOP_TIMEOUT_S)]
        assert Recorder.SVO_STOP_TIMEOUT_S > Recorder.SERVICE_TIMEOUT_S

    def test_a_driver_that_does_not_stop_is_reported_with_the_command_to_stop_it(
            self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False)])
        _fake_zed_driver(fake_node)
        fake_node.services['/zedx_cabin/zedx_cabin_node/stop_svo_rec'] = (
            'std_srvs/srv/Trigger', lambda _request: SimpleNamespace(success=False, message='busy'))
        recorder = Recorder()
        warnings = []
        recorder.warning_occurred.connect(warnings.append)
        config = RecordingConfig(
            topics=[], output_path=str(tmp_path / 'out'), session_name='t', camera_mode='svo2')
        assert recorder.start_recording(config, fake_node) is True

        recorder.stop_recording(fake_node)

        assert len(recorder.driver_stop_failures) == 1
        assert 'ros2 service call /zedx_cabin/zedx_cabin_node/stop_svo_rec' in recorder.driver_stop_failures[0]
        assert warnings == recorder.driver_stop_failures

    def test_svo2_opens_the_camera_chosen_by_serial(self, session, monkeypatch):
        sl = _fake_zed_sdk(monkeypatch)

        session.start([STATUS, BOOM_IMAGE], camera_mode='svo2', svo2_camera_serial='45233238')

        assert sl.serial_asked_for == 45233238

    def test_the_svo2_file_is_named_after_the_camera_it_holds(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch)
        monkeypatch.setattr('ros2_bag_gui.ros2.recorder.camera_names_by_serial',
                            lambda: {'45233238': 'zedx_boom'})

        session.start([STATUS, BOOM_IMAGE], camera_mode='svo2', svo2_camera_serial='45233238')
        session.recorder.stop_recording()

        assert _sync_info(session.recorder)['data_sources']['svo2']['path'] == ['zedx_boom.svo2']

    def test_the_camera_opened_without_a_choice_is_named_too(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch, cameras=[('49749405', 'ZED X', False), ('45233238', 'ZED X', True)])
        monkeypatch.setattr('ros2_bag_gui.ros2.recorder.camera_names_by_serial',
                            lambda: {'45233238': 'zedx_boom', '49749405': 'zedx_cabin'})

        session.start([STATUS, BOOM_IMAGE], camera_mode='svo2')  # no serial chosen
        session.recorder.stop_recording()

        assert _sync_info(session.recorder)['data_sources']['svo2']['path'] == ['zedx_boom.svo2']

    def test_an_unknown_camera_keeps_the_old_file_name(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch)

        session.start([STATUS, BOOM_IMAGE], camera_mode='svo2', svo2_camera_serial='45233238')
        session.recorder.stop_recording()

        assert _sync_info(session.recorder)['data_sources']['svo2']['path'] == ['camera_0.svo2']


ALERT = {'name': '/excavator/safety/operator_alert', 'type': 'std_msgs/msg/String'}
ACTION_STATUS = {'name': '/task_manager/execute_task/_action/status',
                 'type': 'action_msgs/msg/GoalStatusArray'}


def _publisher(durability, reliability=QoSReliabilityPolicy.RELIABLE):
    return SimpleNamespace(
        qos_profile=QoSProfile(depth=10, durability=durability, reliability=reliability))


class TestBagRecordOptions:
    """What ros2 bag record is told besides the topics."""

    @pytest.fixture
    def record(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        args_file = tmp_path / 'bag_args.json'
        monkeypatch.setenv('FAKE_ROS2_ARGS', str(args_file))

        def record(topics):
            recorder, _log = _recorder_with_log()
            config = RecordingConfig(topics=topics, output_path=str(tmp_path / 'out'), session_name='t')
            assert recorder.start_recording(config, fake_node) is True
            ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
            qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)
            recorder.stop_recording(fake_node)
            return json.loads(args_file.read_text())

        return record

    def test_a_hidden_topic_is_recorded_with_hidden_topics_on(self, record):
        bag_args = record([STATUS, ACTION_STATUS])

        assert '--include-hidden-topics' in bag_args
        assert ACTION_STATUS['name'] in bag_args

    def test_hidden_topics_stay_off_when_none_is_selected(self, record):
        assert '--include-hidden-topics' not in record([STATUS])

    def test_a_topic_whose_publishers_mix_durability_is_recorded_volatile(self, record, fake_node):
        fake_node.publishers[ALERT['name']] = [
            _publisher(QoSDurabilityPolicy.TRANSIENT_LOCAL), _publisher(QoSDurabilityPolicy.VOLATILE)]
        fake_node.publishers[STATUS['name']] = [
            _publisher(QoSDurabilityPolicy.VOLATILE), _publisher(QoSDurabilityPolicy.VOLATILE)]

        bag_args = record([STATUS, ALERT])

        path = bag_args[bag_args.index('--qos-profile-overrides-path') + 1]
        with open(path, encoding='utf-8') as f:
            profiles = convert_yaml_to_qos_profile(yaml.safe_load(f))  # as ros2 bag record reads it
        assert list(profiles) == [ALERT['name']]
        assert profiles[ALERT['name']].durability == QoSDurabilityPolicy.VOLATILE
        assert profiles[ALERT['name']].reliability == QoSReliabilityPolicy.RELIABLE

    def test_publishers_that_agree_get_no_qos_override(self, record, fake_node):
        fake_node.publishers[STATUS['name']] = [
            _publisher(QoSDurabilityPolicy.TRANSIENT_LOCAL),
            _publisher(QoSDurabilityPolicy.TRANSIENT_LOCAL)]

        assert '--qos-profile-overrides-path' not in record([STATUS])
