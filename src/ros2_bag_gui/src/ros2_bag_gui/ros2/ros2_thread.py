"""ROS2 thread for running rclpy in background."""
from PySide6.QtCore import QThread, Signal
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from typing import List, Optional
import threading


class ROS2Thread(QThread):

    topic_list_updated = Signal(list)
    connection_status_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._node: Optional[Node] = None
        self._executor: Optional[MultiThreadedExecutor] = None
        self._command_lock = threading.Lock()
        self._pending_command: Optional[str] = None

    def run(self):
        try:
            rclpy.init()
            self._node = rclpy.create_node('ros2_bag_gui')
            self._executor = MultiThreadedExecutor(num_threads=4)
            self._executor.add_node(self._node)

            self._node.create_timer(0.2, self._process_command)

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
                    'hz': 0.0,
                    'category': category
                })

            self.topic_list_updated.emit(topics)

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

    def stop(self):
        self._running = False
        if self._executor is not None:
            self._executor.shutdown()
        self.wait(5000)

    def _cleanup(self):
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
