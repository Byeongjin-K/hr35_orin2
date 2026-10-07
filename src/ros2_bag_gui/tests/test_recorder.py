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
from PySide6.QtWidgets import QApplication
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

    def test_sync_info_holds_the_counts_of_the_bag(self, qtbot, tmp_path, fake_node, fake_ros2, monkeypatch):
        monkeypatch.setenv('FAKE_ROS2_COUNTS', json.dumps({'/excavator/status': 42}))
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        ready = os.path.join(recorder.session_path, 'rosbag', 'ready')
        qtbot.waitUntil(lambda: os.path.exists(ready), timeout=10000)
        # The GUI's own subscription sees a different number than the recorder writes.
        for _ in range(7):
            fake_node.subscriptions[0]['callback'](b'')

        recorder.stop_recording(fake_node)

        sync = _sync_info(recorder)
        assert sync['topic_message_counts'] == {'/excavator/status': 42}
        assert sync['gui_received_counts'] == {'/excavator/status': 7}
        assert recorder.last_bag_counts == {'/excavator/status': 42}

    def test_sync_info_of_a_killed_recorder_has_no_made_up_counts(self, qtbot, tmp_path, fake_node, fake_ros2):
        recorder, log = _recorder_with_log()
        assert recorder.start_recording(_config(tmp_path), fake_node) is True
        fake_node.subscriptions[0]['callback'](b'')

        with qtbot.waitSignal(recorder.error_occurred, timeout=10000):
            os.kill(recorder._bag_proc._proc.processId(), signal.SIGKILL)

        sync = _sync_info(recorder)
        assert sync['topic_message_counts'] is None
        assert sync['gui_received_counts'] == {'/excavator/status': 1}
        assert recorder.last_bag_counts is None

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


def _fake_zed_sdk(monkeypatch, opens=True, fail_after_grabs=None):
    """A stand-in for pyzed.sl: a camera that opens (or not) and delivers frames."""
    sl = SimpleNamespace(grabs=0, frame_period=threading.Event())
    sl.ERROR_CODE = SimpleNamespace(
        SUCCESS='SUCCESS', END_OF_SVOFILE_REACHED='EOF', FAILURE='CAMERA NOT DETECTED')
    sl.DEPTH_MODE = SimpleNamespace(NONE=0)
    sl.RESOLUTION = SimpleNamespace(HD1200=1)
    sl.SVO_COMPRESSION_MODE = SimpleNamespace(H265=1)
    sl.InitParameters = SimpleNamespace
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
    return sl


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

        yield SimpleNamespace(recorder=recorder, log=log, start=start)
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

    def test_svo2_with_two_cameras_keeps_images_in_bag(self, session, monkeypatch):
        _fake_zed_sdk(monkeypatch)

        bag_args = session.start([BOOM_IMAGE, CABIN_IMAGE], camera_mode='svo2')

        assert BOOM_IMAGE['name'] in bag_args and CABIN_IMAGE['name'] in bag_args
        assert len(session.log['warnings']) == 1

    def test_svo2_failure_while_recording_is_reported(self, session, qtbot, monkeypatch):
        _fake_zed_sdk(monkeypatch, fail_after_grabs=3)

        with qtbot.waitSignal(session.recorder.error_occurred, timeout=10000):
            session.start([STATUS, BOOM_IMAGE], camera_mode='svo2')

        assert len(session.log['errors']) == 1
        assert session.recorder.is_recording  # the bag goes on

    def test_lidar_that_laz_cannot_subscribe_to_stays_in_bag(self, session):
        cloud = {'name': BOOM_CLOUD['name'], 'type': 'no_such_pkg/msg/Nope'}

        bag_args = session.start([STATUS, cloud], lidar_mode='laz')

        assert cloud['name'] in bag_args
        assert len(session.log['warnings']) == 1

    def test_laz_recording_takes_lidar_out_of_the_bag(self, session):
        bag_args = session.start([STATUS, BOOM_CLOUD], lidar_mode='laz')

        assert BOOM_CLOUD['name'] not in bag_args
        assert session.log['warnings'] == []
