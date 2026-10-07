"""Tests for the ROS2 thread."""
import threading

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
