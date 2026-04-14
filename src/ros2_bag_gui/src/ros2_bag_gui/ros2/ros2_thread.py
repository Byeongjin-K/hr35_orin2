"""ROS2 thread for running rclpy in background."""
from PySide6.QtCore import QThread, Signal
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from typing import List, Tuple, Optional
import threading


class ROS2Thread(QThread):
    """Background thread for ROS2 operations."""
    
    # Signals for UI updates
    topic_list_updated = Signal(list)  # List of (name, type) tuples
    connection_status_changed = Signal(bool)  # True = connected
    error_occurred = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._node: Optional[Node] = None
        self._executor: Optional[SingleThreadedExecutor] = None
        self._command_lock = threading.Lock()
        self._pending_command: Optional[str] = None
    
    def run(self):
        """ROS2 event loop in background thread."""
        try:
            rclpy.init()
            self._node = rclpy.create_node('ros2_bag_gui_discovery')
            self._executor = SingleThreadedExecutor()
            self._executor.add_node(self._node)
            
            self._running = True
            self.connection_status_changed.emit(True)
            
            while self._running:
                self._executor.spin_once(timeout_sec=0.1)
                self._process_command()
            
        except Exception as e:
            self.error_occurred.emit(f"ROS2 error: {e}")
            self.connection_status_changed.emit(False)
        finally:
            self._cleanup()
    
    def _process_command(self):
        """Process pending command from main thread."""
        with self._command_lock:
            cmd = self._pending_command
            self._pending_command = None
        
        if cmd == 'discover_topics':
            self._do_discover_topics()
    
    def _do_discover_topics(self):
        """Discover topics (runs in ROS2 thread)."""
        try:
            if self._node is None:
                return
            
            topic_list = self._node.get_topic_names_and_types()
            # Convert to list of dicts for UI
            topics = []
            for name, types in topic_list:
                topic_type = types[0] if types else 'unknown'
                # Categorize topic
                category = self._categorize_topic(name)
                topics.append({
                    'name': name,
                    'type': topic_type,
                    'hz': 0.0,  # Hz estimation would need subscription
                    'category': category
                })
            
            self.topic_list_updated.emit(topics)
            
        except Exception as e:
            self.error_occurred.emit(f"Discovery error: {e}")
    
    def _categorize_topic(self, name: str) -> str:
        """Categorize topic by name prefix."""
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
        """Request topic discovery (called from main thread)."""
        with self._command_lock:
            self._pending_command = 'discover_topics'
    
    def stop(self):
        """Stop the ROS2 thread."""
        self._running = False
        self.wait(5000)  # 5 second timeout
    
    def _cleanup(self):
        """Cleanup ROS2 resources."""
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
