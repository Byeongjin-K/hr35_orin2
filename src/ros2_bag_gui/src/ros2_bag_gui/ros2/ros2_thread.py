"""ROS2 thread for running rclpy in background."""
import time
import threading

from PySide6.QtCore import QThread, Signal
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from rosidl_runtime_py.utilities import get_message
from typing import List, Dict, Optional

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

        self._hz_lock = threading.Lock()
        self._hz_timestamps: Dict[str, List[float]] = {}
        self._hz_subs: List = []
        self._hz_subscribed: set = set()
        self._hz_active = False

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

            self._executor.spin()

        except Exception as e:
            self.error_occurred.emit(f"ROS2 error: {e}")
            self.connection_status_changed.emit(False)
        finally:
            self._cleanup()

    def _process_command(self):
        with self._command_lock:
            cmd = self._pending_command
            self._pending_command = None

        if cmd == 'discover_topics':
            self._do_discover_topics()
        elif cmd == 'stop_hz':
            self._destroy_hz_subs()

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

            self.topic_list_updated.emit(topics)
            self._update_hz_subs(topics)

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

    def _update_hz_subs(self, topics: List[Dict]):
        new_names = {t['name'] for t in topics}
        if new_names == self._hz_subscribed and self._hz_active:
            return

        self._destroy_hz_subs()

        cb_group = ReentrantCallbackGroup()
        for topic in topics:
            try:
                msg_class = get_message(topic['type'])
            except Exception:
                continue

            def raw_cb(_raw, t=topic['name']):
                self._hz_tick(t)

            try:
                sub = self._node.create_subscription(
                    msg_class, topic['name'], raw_cb, _HZ_QOS,
                    callback_group=cb_group, raw=True,
                )
                self._hz_subs.append(sub)
            except Exception:
                pass

        self._hz_subscribed = new_names
        self._hz_active = True

    def _hz_tick(self, topic_name: str):
        if not self._hz_active:
            return
        now = time.monotonic()
        with self._hz_lock:
            ts_list = self._hz_timestamps.setdefault(topic_name, [])
            ts_list.append(now)
            cutoff = now - _HZ_WINDOW
            while ts_list and ts_list[0] < cutoff:
                ts_list.pop(0)

    def _emit_hz(self):
        if not self._hz_active:
            return
        now = time.monotonic()
        result: Dict[str, float] = {}
        with self._hz_lock:
            for topic, ts_list in self._hz_timestamps.items():
                cutoff = now - _HZ_WINDOW
                while ts_list and ts_list[0] < cutoff:
                    ts_list.pop(0)
                if len(ts_list) >= 2:
                    span = ts_list[-1] - ts_list[0]
                    result[topic] = (len(ts_list) - 1) / span if span > 0 else 0.0
                else:
                    result[topic] = 0.0
        if result:
            self.hz_updated.emit(result)

    def _destroy_hz_subs(self):
        for sub in self._hz_subs:
            try:
                self._node.destroy_subscription(sub)
            except Exception:
                pass
        self._hz_subs.clear()
        self._hz_subscribed.clear()
        self._hz_active = False
        with self._hz_lock:
            self._hz_timestamps.clear()

    def set_hz_active(self, active: bool):
        if active:
            with self._command_lock:
                self._pending_command = 'discover_topics'
        else:
            self._hz_active = False
            with self._command_lock:
                self._pending_command = 'stop_hz'

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
