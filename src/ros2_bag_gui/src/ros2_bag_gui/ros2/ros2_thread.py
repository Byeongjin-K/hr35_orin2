"""ROS2 thread for running rclpy in background."""
import time
import threading

from PySide6.QtCore import QThread, Signal
import rclpy
from rclpy.executors import (
    SingleThreadedExecutor, ShutdownException, ExternalShutdownException,
)
from rclpy.impl.implementation_singleton import rclpy_implementation as _rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from rclpy.subscription import Subscription
from rosidl_runtime_py.utilities import get_message
from typing import Dict, Optional

_HZ_QOS = QoSProfile(
    depth=1,
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
)

# A ticked topic is subscribed to for _HZ_WINDOW seconds every _HZ_PERIOD
# seconds, not all the time: every message of a measured topic goes through a
# Python callback here, and the lidar packets, images and IMUs cost about a
# core when measured continuously (2026-10-22: 7 topics, 33% CPU).
_HZ_WINDOW = 5.0
_HZ_PERIOD = 30.0


def _rates(acc) -> tuple[float, float]:
    """(Hz, bytes per second) of a measurement [count, first time, last time, bytes after the first]."""
    count, first, last, nbytes = acc
    if count < 2 or last <= first:
        return 0.0, 0.0
    span = last - first
    return (count - 1) / span, nbytes / span


class ROS2Thread(QThread):

    topic_list_updated = Signal(list)
    connection_status_changed = Signal(bool)
    error_occurred = Signal(str)
    hz_updated = Signal(dict)  # topic -> Hz, of the topics whose measurement just ended
    rate_updated = Signal(dict)  # topic -> bytes per second, of the same topics

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._node: Optional[Node] = None
        self._executor: Optional[SingleThreadedExecutor] = None
        self._command_lock = threading.Lock()
        self._pending_command: Optional[str] = None

        # Rates are measured for the topics the GUI asks for (the ticked ones)
        # only. A subscription to every topic pulls every image and point cloud
        # of the robot into this process, and makes drivers that publish only
        # for a subscriber (the cameras) produce all of their streams.
        # Everything below except _hz_topics/_hz_dirty is used on the ROS thread only.
        self._hz_topics: set[str] = set()  # asked for by the GUI; under _command_lock
        self._hz_dirty = False  # _hz_topics or _hz_active changed; under _command_lock
        self._hz_subs: Dict[str, tuple[Subscription, str, float]] = {}  # topic -> (subscription, type, start)
        self._hz_acc: Dict[str, list[float]] = {}  # topic -> [count, first time, last time, bytes after the first]
        self._hz_result: Dict[str, tuple[float, float]] = {}  # topic -> (Hz, bytes/s) of the last measurement
        self._hz_next: Dict[str, float] = {}  # topic -> when its next measurement is due
        self._topic_types: Dict[str, str] = {}  # from the last discovery
        self._hz_active = threading.Event()  # cleared while recording
        self._hz_active.set()

    def run(self):
        try:
            rclpy.init()
            self._node = rclpy.create_node('ros2_bag_gui')
            # One thread: the callbacks hold the GIL anyway, and a thread pool
            # only adds a hand-off per message.
            self._executor = SingleThreadedExecutor()
            self._executor.add_node(self._node)

            self._node.create_timer(0.2, self._process_command)
            self._node.create_timer(1.0, self._measure_rates)

            self._running = True
            self.connection_status_changed.emit(True)

            while self._running and rclpy.ok():
                try:
                    self._executor.spin_once(timeout_sec=0.1)
                except _rclpy.InvalidHandle:
                    # A subscription was destroyed (Stop, topic refresh) while the
                    # executor was waiting on it. That spoils this pass, not the node:
                    # ending the thread here would leave the GUI disconnected for good.
                    continue
                except (ShutdownException, ExternalShutdownException):
                    break

            if self._running:
                # Not our stop(): the ROS context was shut down from outside
                # (rclpy does that on SIGTERM). Say so instead of "Connected".
                self.connection_status_changed.emit(False)

        except Exception as e:
            self.error_occurred.emit(f"ROS2 error: {e}")
            self.connection_status_changed.emit(False)
        finally:
            self._cleanup()

    def _process_command(self):
        with self._command_lock:
            cmd = self._pending_command
            self._pending_command = None
            hz_dirty = self._hz_dirty
            self._hz_dirty = False

        if cmd == 'discover_topics':
            self._do_discover_topics()  # also brings the rate subscriptions up to date
        elif hz_dirty:
            self._sync_hz_subs()

    def _do_discover_topics(self):
        try:
            if self._node is None:
                return

            topic_list = self._node.get_topic_names_and_types()
            topics = []
            for name, types in topic_list:
                topic_type = types[0] if types else 'unknown'
                category = self._categorize_topic(name)
                topics.append({
                    'name': name,
                    'type': topic_type,
                    'hz': self._hz_result.get(name, (0.0, 0.0))[0],
                    'category': category,
                })

            self._topic_types = {t['name']: t['type'] for t in topics}
            self.topic_list_updated.emit(topics)
            self._sync_hz_subs()

        except Exception as e:
            self.error_occurred.emit(f"Discovery error: {e}")

    def _categorize_topic(self, name: str) -> str:
        if name.startswith('/excavator'):
            return 'excavator'
        elif name.startswith('/lidar'):
            return 'lidar'
        elif name.startswith('/zedx'):
            return 'zed'
        elif name.startswith('/gps') or name.startswith('/gnss'):
            return 'gps'
        elif name in ['/tf', '/tf_static', '/rosout']:
            return 'system'
        else:
            return 'other'

    def request_discover_topics(self):
        with self._command_lock:
            self._pending_command = 'discover_topics'

    def set_hz_topics(self, names) -> None:
        """Measure the rates of these topics only (called from the GUI thread)."""
        names = set(names)
        with self._command_lock:
            if names != self._hz_topics:
                self._hz_topics = names
                self._hz_dirty = True

    def _wanted(self) -> set[str]:
        with self._command_lock:
            return set(self._hz_topics) if self._hz_active.is_set() else set()

    def _sync_hz_subs(self):
        """Drop what is no longer asked for, and start the measurements that are due.

        A topic ticked just now is measured at once; a measurement under way
        or a result already shown is kept through refreshes and other ticks.
        """
        wanted = self._wanted()
        for name, (_sub, sub_type, _start) in list(self._hz_subs.items()):
            if name not in wanted or self._topic_types.get(name, sub_type) != sub_type:
                self._destroy_hz_sub(name)
        with self._command_lock:
            ticked = set(self._hz_topics)
        for name in (self._hz_result.keys() | self._hz_next.keys()) - ticked:
            self._hz_result.pop(name, None)
            self._hz_next.pop(name, None)
        if not self._hz_active.is_set():
            self._hz_next.clear()  # measured anew once the recording is over
            return
        self._start_due_measurements(wanted, time.monotonic())

    def _start_due_measurements(self, wanted: set[str], now: float):
        for name in sorted(wanted - self._hz_subs.keys()):
            if self._hz_next.get(name, 0.0) > now:
                continue
            topic_type = self._topic_types.get(name)
            if topic_type is None:
                continue  # not up yet: measured once a discovery lists it
            try:
                msg_class = get_message(topic_type)
            except Exception:
                continue

            def raw_cb(raw, t=name):
                self._hz_tick(t, len(raw))

            try:
                sub = self._node.create_subscription(
                    msg_class, name, raw_cb, _HZ_QOS, raw=True,
                )
            except Exception:
                continue
            self._hz_subs[name] = (sub, topic_type, now)
            self._hz_acc[name] = [0, 0.0, 0.0, 0]
            self._hz_next[name] = now + _HZ_PERIOD

    def _hz_tick(self, topic_name: str, size: int = 0):
        acc = self._hz_acc.get(topic_name)
        if acc is None:
            return  # a message delivered after its measurement ended
        now = time.monotonic()
        if acc[0] == 0:
            acc[1] = now
        else:
            acc[3] += size
        acc[0] += 1
        acc[2] = now

    def _measure_rates(self):
        """Once a second: end the measurements whose window is over, start the ones due."""
        if not self._hz_active.is_set():
            return
        now = time.monotonic()
        hz: Dict[str, float] = {}
        sizes: Dict[str, float] = {}
        for name, (_sub, _type, start) in list(self._hz_subs.items()):
            if now - start < _HZ_WINDOW:
                continue
            hz[name], sizes[name] = self._hz_result[name] = _rates(self._hz_acc[name])
            self._destroy_hz_sub(name)
        if hz:
            self.hz_updated.emit(hz)
            self.rate_updated.emit(sizes)
        self._start_due_measurements(self._wanted(), now)

    def _destroy_hz_sub(self, name: str):
        sub, _type, _start = self._hz_subs.pop(name)
        self._hz_acc.pop(name, None)
        try:
            self._node.destroy_subscription(sub)
        except Exception:
            pass

    def _destroy_hz_subs(self):
        for name in list(self._hz_subs):
            self._destroy_hz_sub(name)

    def set_hz_active(self, active: bool):
        """Off while recording. It stays off through topic refreshes until set on again."""
        if active:
            self._hz_active.set()
        else:
            self._hz_active.clear()
        with self._command_lock:
            self._hz_dirty = True

    def stop(self):
        self._running = False
        if self._executor is not None:
            self._executor.shutdown()
        self.wait(5000)

    def _cleanup(self):
        self._destroy_hz_subs()
        if self._node is not None:
            self._node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass

    @property
    def node(self) -> Optional[Node]:
        return self._node if self._running else None

    @property
    def is_connected(self) -> bool:
        return self._running and self._node is not None
