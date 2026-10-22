"""ROS2 thread for running rclpy in background."""
import time
import threading

from PySide6.QtCore import QThread, Signal
import rclpy
from rclpy.executors import (
    MultiThreadedExecutor, ShutdownException, ExternalShutdownException,
)
from rclpy.impl.implementation_singleton import rclpy_implementation as _rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from rclpy.subscription import Subscription
from rosidl_runtime_py.utilities import get_message
from collections import deque
from typing import Dict, Optional

_HZ_QOS = QoSProfile(
    depth=1,
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
)

_HZ_WINDOW = 5.0


class ROS2Thread(QThread):

    topic_list_updated = Signal(list)
    connection_status_changed = Signal(bool)
    error_occurred = Signal(str)
    hz_updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._node: Optional[Node] = None
        self._executor: Optional[MultiThreadedExecutor] = None
        self._command_lock = threading.Lock()
        self._pending_command: Optional[str] = None

        # Rates are measured for the topics the GUI asks for (the ticked ones)
        # only. A subscription to every topic pulls every image and point cloud
        # of the robot into this process, and makes drivers that publish only
        # for a subscriber (the cameras) produce all of their streams.
        self._hz_lock = threading.Lock()
        self._hz_timestamps: Dict[str, deque] = {}
        self._hz_topics: set[str] = set()  # asked for by the GUI; under _command_lock
        self._hz_dirty = False  # _hz_topics or _hz_active changed; under _command_lock
        self._hz_subs: Dict[str, tuple[Subscription, str]] = {}  # topic -> (subscription, type); ROS thread only
        self._topic_types: Dict[str, str] = {}  # from the last discovery; ROS thread only
        self._hz_cb_group = ReentrantCallbackGroup()
        self._hz_active = threading.Event()  # cleared while recording: the recorder counts then
        self._hz_active.set()

    def run(self):
        try:
            rclpy.init()
            self._node = rclpy.create_node('ros2_bag_gui')
            self._executor = MultiThreadedExecutor(num_threads=4)
            self._executor.add_node(self._node)

            self._node.create_timer(0.2, self._process_command)
            self._node.create_timer(1.0, self._emit_hz)

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
                    'hz': self._cached_hz(name),
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

    def _cached_hz(self, topic_name: str) -> float:
        with self._hz_lock:
            ts_list = self._hz_timestamps.get(topic_name)
            if ts_list and len(ts_list) >= 2:
                span = ts_list[-1] - ts_list[0]
                return (len(ts_list) - 1) / span if span > 0 else 0.0
        return 0.0

    def set_hz_topics(self, names) -> None:
        """Measure the rates of these topics only (called from the GUI thread)."""
        names = set(names)
        with self._command_lock:
            if names != self._hz_topics:
                self._hz_topics = names
                self._hz_dirty = True

    def _sync_hz_subs(self):
        """Subscribe to the asked-for topics that are up, and drop the others.

        A subscription that is still right is kept: a refresh or another tick
        does not reset the rates of the topics already measured.
        """
        with self._command_lock:
            wanted = set(self._hz_topics) if self._hz_active.is_set() else set()

        for name, (_sub, sub_type) in list(self._hz_subs.items()):
            if name not in wanted or self._topic_types.get(name, sub_type) != sub_type:
                self._destroy_hz_sub(name)

        for name in sorted(wanted - self._hz_subs.keys()):
            topic_type = self._topic_types.get(name)
            if topic_type is None:
                continue  # not up yet: subscribed once a discovery lists it
            try:
                msg_class = get_message(topic_type)
            except Exception:
                continue

            def raw_cb(_raw, t=name):
                self._hz_tick(t)

            try:
                sub = self._node.create_subscription(
                    msg_class, name, raw_cb, _HZ_QOS,
                    callback_group=self._hz_cb_group, raw=True,
                )
            except Exception:
                continue
            self._hz_subs[name] = (sub, topic_type)

    def _hz_tick(self, topic_name: str):
        if not self._hz_active.is_set():
            return
        now = time.monotonic()
        with self._hz_lock:
            ts_list = self._hz_timestamps.setdefault(topic_name, deque())
            ts_list.append(now)
            cutoff = now - _HZ_WINDOW
            while ts_list and ts_list[0] < cutoff:
                ts_list.popleft()

    def _emit_hz(self):
        if not self._hz_active.is_set() or not self._hz_subs:
            return
        now = time.monotonic()
        result: Dict[str, float] = {}
        with self._hz_lock:
            for topic in self._hz_subs:  # a measured topic with no message yet is 0.0
                ts_list = self._hz_timestamps.get(topic)
                cutoff = now - _HZ_WINDOW
                while ts_list and ts_list[0] < cutoff:
                    ts_list.popleft()
                if ts_list and len(ts_list) >= 2:
                    span = ts_list[-1] - ts_list[0]
                    result[topic] = (len(ts_list) - 1) / span if span > 0 else 0.0
                else:
                    result[topic] = 0.0
        if result:
            self.hz_updated.emit(result)

    def _destroy_hz_sub(self, name: str):
        sub, _type = self._hz_subs.pop(name)
        try:
            self._node.destroy_subscription(sub)
        except Exception:
            pass
        with self._hz_lock:
            self._hz_timestamps.pop(name, None)

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
