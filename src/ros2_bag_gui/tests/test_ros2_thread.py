"""Tests for the ROS2 thread."""
import threading
from types import SimpleNamespace

import pytest

from rclpy.executors import MultiThreadedExecutor
from rclpy.impl.implementation_singleton import rclpy_implementation as _rclpy

from ros2_bag_gui.ros2.ros2_thread import ROS2Thread


def test_thread_survives_a_subscription_destroyed_under_the_executor(qtbot, monkeypatch):
    """Stop and topic refresh destroy subscriptions while the executor waits on them."""
    spin_once = MultiThreadedExecutor.spin_once
    passes = {'count': 0}
    kept_spinning = threading.Event()

    def spin_once_with_one_invalid_handle(self, *args, **kwargs):
        passes['count'] += 1
        if passes['count'] == 1:
            raise _rclpy.InvalidHandle("cannot use Destroyable because destruction was requested")
        if passes['count'] == 4:
            kept_spinning.set()
        return spin_once(self, *args, **kwargs)

    monkeypatch.setattr(MultiThreadedExecutor, 'spin_once', spin_once_with_one_invalid_handle)
    thread = ROS2Thread()
    connection = []
    thread.connection_status_changed.connect(connection.append)

    with qtbot.waitSignal(thread.connection_status_changed, timeout=10000):
        thread.start()
    try:
        assert kept_spinning.wait(10)
        assert thread.is_connected and thread.isRunning()
    finally:
        thread.stop()

    assert thread.isFinished()
    assert connection == [True]


GRAPH = [
    ('/excavator/status', ['std_msgs/msg/String']),
    ('/lidar_boom/points', ['sensor_msgs/msg/PointCloud2']),
    ('/zedx_boom/left/image', ['sensor_msgs/msg/Image']),
]


def _thread_on(fake_node, graph):
    """A ROS2Thread on a fake node, driven by hand instead of by the executor."""
    thread = ROS2Thread()
    fake_node.get_topic_names_and_types = lambda: graph
    thread._node = fake_node
    return thread


def _refresh(thread):
    thread.request_discover_topics()
    thread._process_command()


def _measured(fake_node):
    return sorted(sub['topic'] for sub in fake_node.live_subscriptions)


def test_rates_are_measured_for_the_ticked_topics_only(qtbot, fake_node):
    """Not for every topic: that pulls every image and point cloud into the GUI."""
    thread = _thread_on(fake_node, GRAPH)
    _refresh(thread)
    assert _measured(fake_node) == []

    thread.set_hz_topics(['/excavator/status'])
    thread._process_command()
    assert _measured(fake_node) == ['/excavator/status']

    thread.set_hz_topics(['/excavator/status', '/lidar_boom/points'])
    _refresh(thread)
    assert _measured(fake_node) == ['/excavator/status', '/lidar_boom/points']
    assert fake_node.destroyed == []  # the measured topic keeps its subscription and rate

    thread.set_hz_topics(['/lidar_boom/points'])
    thread._process_command()
    assert _measured(fake_node) == ['/lidar_boom/points']


def test_rates_stay_off_while_recording_through_refreshes(qtbot, fake_node):
    thread = _thread_on(fake_node, GRAPH)
    thread.set_hz_topics(['/excavator/status', '/lidar_boom/points'])
    _refresh(thread)

    thread.set_hz_active(False)
    thread._process_command()
    _refresh(thread)  # the 5 s topic refresh goes on during a recording
    assert _measured(fake_node) == []

    thread.set_hz_active(True)
    thread._process_command()
    assert _measured(fake_node) == ['/excavator/status', '/lidar_boom/points']


def test_the_measured_topics_report_their_size_in_bytes_per_second(qtbot, fake_node, monkeypatch):
    clock = {'now': 100.0}
    monkeypatch.setattr('ros2_bag_gui.ros2.ros2_thread.time', SimpleNamespace(monotonic=lambda: clock['now']))
    thread = _thread_on(fake_node, GRAPH)
    thread.set_hz_topics(['/lidar_boom/points'])
    _refresh(thread)
    receive = fake_node.live_subscriptions[0]['callback']
    for _ in range(11):  # 10 Hz for a second, 2000 bytes a message
        receive(b'x' * 2000)
        clock['now'] += 0.1
    sizes = []
    thread.rate_updated.connect(sizes.append)

    thread._emit_hz()

    assert sizes == [{'/lidar_boom/points': pytest.approx(20000.0)}]


def test_a_ticked_topic_is_measured_once_it_comes_up(qtbot, fake_node):
    thread = _thread_on(fake_node, GRAPH)
    thread.set_hz_topics(['/gps/fix'])
    _refresh(thread)
    assert _measured(fake_node) == []

    fake_node.get_topic_names_and_types = lambda: GRAPH + [('/gps/fix', ['sensor_msgs/msg/NavSatFix'])]
    _refresh(thread)
    assert _measured(fake_node) == ['/gps/fix']


def test_thread_says_disconnected_when_ros_is_shut_down_from_outside(qtbot):
    """rclpy shuts its context down on SIGTERM; the label must not stay on Connected."""
    import rclpy
    thread = ROS2Thread()
    connection = []
    thread.connection_status_changed.connect(connection.append)
    with qtbot.waitSignal(thread.connection_status_changed, timeout=10000):
        thread.start()

    try:
        with qtbot.waitSignal(thread.connection_status_changed, timeout=10000):
            rclpy.shutdown()
    finally:
        thread.stop()

    assert connection == [True, False]
