"""Topic discovery utilities."""
from typing import List, Dict
from PySide6.QtCore import QTimer, Signal, QObject
from ros2_bag_gui.ros2.ros2_thread import ROS2Thread


class TopicDiscoveryManager(QObject):
    """Manages topic discovery with timeout handling."""
    
    topics_discovered = Signal(list)
    discovery_timeout = Signal()
    error = Signal(str)
    
    def __init__(self, ros2_thread: ROS2Thread, parent=None):
        super().__init__(parent)
        self._ros2_thread = ros2_thread
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_timeout)
        
        # Connect to ROS2 thread signals
        self._ros2_thread.topic_list_updated.connect(self._on_topics_received)
        self._ros2_thread.error_occurred.connect(self._on_error)
    
    def discover_topics(self, timeout_ms: int = 5000):
        """Start topic discovery with timeout."""
        self._timeout_timer.start(timeout_ms)
        self._ros2_thread.request_discover_topics()
    
    def _on_topics_received(self, topics: List[Dict]):
        """Called when topics are discovered."""
        self._timeout_timer.stop()
        self.topics_discovered.emit(topics)
    
    def _on_timeout(self):
        """Called on discovery timeout."""
        self.discovery_timeout.emit()
        self.error.emit("Topic discovery timed out (5s)")
    
    def _on_error(self, msg: str):
        """Called on error."""
        self._timeout_timer.stop()
        self.error.emit(msg)
