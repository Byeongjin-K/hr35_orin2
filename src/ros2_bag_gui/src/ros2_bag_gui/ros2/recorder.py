"""Recording logic using rosbag2_py SequentialWriter."""
import re
import os
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Set
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal

from rosbag2_py import SequentialWriter, StorageOptions, ConverterOptions, TopicMetadata
from rclpy.serialization import serialize_message
from rosidl_runtime_py.utilities import get_message

from ros2_bag_gui.compat import create_topic_metadata
from ros2_bag_gui.ros2.laz_writer import LAZWriterThread, create_payload_from_msg
from ros2_bag_gui.zed.svo_writer import SVO2WriterThread, SVO2Config
from ros2_bag_gui.zed.sdk_check import is_zed_sdk_available

logger = logging.getLogger(__name__)

# Topic pattern categories
LIDAR_TOPICS = [r'^/lidar_boom/points$', r'^/ouster/points$']
CAMERA_IMAGE_TOPICS = [
    r'^/zedx_[^/]+/[^/]+/.*image.*$',
    r'^/zedx_[^/]+/[^/]+/.*depth.*$',
]
SYSTEM_EXCLUDE = [r'^/rosout$']

@dataclass
class RecordingConfig:
    """Recording configuration."""
    topics: List[Dict[str, str]]  # List of {name, type} dicts
    output_path: str
    session_name: str
    max_bagfile_size: int = 3 * 1024**3  # 3GB
    zed_sdk_available: bool = False
    lidar_mode: str = "bag"        # "bag", "laz", "both"
    camera_mode: str = "bag"       # "bag", "svo2", "both"

def should_include_in_rosbag(
    topic_name: str,
    lidar_mode: str,
    camera_mode: str,
) -> bool:
    """Determine if topic should be included in rosbag based on recording modes.
    
    Args:
        topic_name: ROS2 topic name
        lidar_mode: 'bag', 'laz', or 'both'
        camera_mode: 'bag', 'svo2', or 'both'
    """
    # Always exclude system topics
    for p in SYSTEM_EXCLUDE:
        if re.match(p, topic_name):
            return False
    
    # LiDAR topic handling
    for p in LIDAR_TOPICS:
        if re.match(p, topic_name):
            return lidar_mode in ("bag", "both")
    
    # Camera image/depth topic handling
    for p in CAMERA_IMAGE_TOPICS:
        if re.match(p, topic_name):
            return camera_mode in ("bag", "both")
    
    # All other topics: include
    return True


def should_record_lidar_laz(topic_name: str, lidar_mode: str) -> bool:
    """Check if topic should be sent to LAZ writer."""
    for p in LIDAR_TOPICS:
        if re.match(p, topic_name):
            return lidar_mode in ("laz", "both")
    return False

class Recorder(QObject):
    """Handles rosbag recording."""
    
    # Signals
    recording_started = Signal()
    recording_stopped = Signal()
    message_recorded = Signal(str, int)  # topic_name, count
    error_occurred = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._writer: Optional[SequentialWriter] = None
        self._config: Optional[RecordingConfig] = None
        self._topic_counts: Dict[str, int] = {}
        self._subscriptions: List[object] = []
        self._laz_writer: Optional[LAZWriterThread] = None
        self._svo2_writers: List[SVO2WriterThread] = []
        self._session_start_time: Optional[datetime] = None
        self._recording = False
    
    def start_recording(self, config: RecordingConfig, node) -> bool:
        """Start recording to rosbag.
        
        Args:
            config: Recording configuration
            node: rclpy.Node for subscriptions
        Returns:
            True if started successfully
        """
        try:
            self._config = config
            self._topic_counts = {}
            self._session_start_time = datetime.now()
            
            # Create output directory
            session_folder = self._generate_session_path()
            rosbag_path = os.path.join(session_folder, 'rosbag')
            os.makedirs(session_folder, exist_ok=True)
            
            # Create writer
            self._writer = SequentialWriter()
            storage_options = StorageOptions(
                uri=rosbag_path,
                storage_id='sqlite3',
                max_bagfile_size=config.max_bagfile_size
            )
            converter_options = ConverterOptions(
                input_serialization_format='cdr',
                output_serialization_format='cdr'
            )
            self._writer.open(storage_options, converter_options)
            
            # Register topics and create subscriptions
            topic_id = 0
            for topic in config.topics:
                if not should_include_in_rosbag(
                    topic['name'],
                    config.lidar_mode,
                    config.camera_mode
                ):
                    continue
                
                topic_id += 1
                try:
                    topic_meta = create_topic_metadata(
                        topic_id=topic_id,
                        name=topic['name'],
                        type_=topic['type'],
                        serialization_format='cdr'
                    )
                    self._writer.create_topic(topic_meta)
                    self._topic_counts[topic['name']] = 0
                    
                    # Create subscription
                    self._create_subscription(node, topic['name'], topic['type'])
                    
                except Exception as e:
                    logger.error("Failed to setup topic %s: %s", topic['name'], e)

            if config.lidar_mode in ("laz", "both"):
                pointcloud_dir = os.path.join(session_folder, 'pointcloud')
                self._laz_writer = LAZWriterThread(pointcloud_dir, parent=None)
                self._laz_writer.error_occurred.connect(
                    lambda msg: logger.error("LAZ writer error: %s", msg)
                )
                self._laz_writer.start()
                logger.info("LAZ writer started: %s", pointcloud_dir)

            if config.camera_mode in ("svo2", "both") and is_zed_sdk_available():
                svo2_path = os.path.join(session_folder, 'camera_0.svo2')
                svo2_config = SVO2Config(
                    output_path=svo2_path,
                    camera_index=0,
                )
                writer = SVO2WriterThread(svo2_config, parent=None)
                writer.error_occurred.connect(
                    lambda msg: logger.error("SVO2 writer error: %s", msg)
                )
                writer.start()
                self._svo2_writers.append(writer)
                logger.info("SVO2 writer started: %s", svo2_path)
            
            self._recording = True
            self.recording_started.emit()
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to start recording: {e}")
            return False
    
    def _create_subscription(self, node, topic_name: str, topic_type: str):
        """Create subscription for a topic."""
        try:
            msg_class = get_message(topic_type)
            
            def callback(msg, topic=topic_name):
                self._on_message_received(topic, msg)
            
            sub = node.create_subscription(
                msg_class,
                topic_name,
                callback,
                10  # QoS depth
            )
            self._subscriptions.append(sub)
        except Exception as e:
            logger.error("Failed to create subscription for %s: %s", topic_name, e)
    
    def _on_message_received(self, topic_name: str, msg):
        """Callback when message is received."""
        if not self._recording or self._writer is None:
            return
        
        try:
            # Get timestamp
            timestamp_ns = self._get_timestamp_ns(msg)
            config = self._config

            serialized = serialize_message(msg)
            self._writer.write(topic_name, serialized, timestamp_ns)  # pyright: ignore[reportArgumentType]

            if self._laz_writer is not None and config is not None and should_record_lidar_laz(topic_name, config.lidar_mode):
                try:
                    laz_payload = create_payload_from_msg(msg, timestamp_ns)
                    self._laz_writer.enqueue(laz_payload)
                except Exception as e:
                    logger.debug("LAZ enqueue error for %s: %s", topic_name, e)

            if self._svo2_writers:
                import re as _re
                for p in CAMERA_IMAGE_TOPICS:
                    if _re.match(p, topic_name):
                        for svo2_writer in self._svo2_writers:
                            svo2_writer.set_ros_timestamp(timestamp_ns)
                        break
            
            self._topic_counts[topic_name] = self._topic_counts.get(topic_name, 0) + 1
            self.message_recorded.emit(topic_name, self._topic_counts[topic_name])
            
        except Exception as e:
            logger.error("Error writing message for %s: %s", topic_name, e)
    
    def _get_timestamp_ns(self, msg) -> int:
        """Extract timestamp from message (from plan)."""
        if hasattr(msg, 'header') and hasattr(msg.header, 'stamp'):
            return msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
        elif hasattr(msg, 'transforms') and len(msg.transforms) > 0:
            # TFMessage
            stamp = msg.transforms[0].header.stamp
            return stamp.sec * 10**9 + stamp.nanosec
        else:
            # Fallback: current time
            import time
            return int(time.time() * 10**9)
    
    def stop_recording(self, node) -> str:
        """Stop recording and return session folder path."""
        if not self._recording:
            return ""
        
        self._recording = False
        session_folder = ""

        try:
            if self._laz_writer is not None:
                self._laz_writer.stop()
                logger.info("LAZ writer stopped: %d files", self._laz_writer.file_count)
                self._laz_writer = None

            for writer in self._svo2_writers:
                writer.stop()
                logger.info("SVO2 writer stopped: %d frames at %s", writer.frame_count, writer._config.output_path)
            self._svo2_writers.clear()

            # Destroy subscriptions
            for sub in self._subscriptions:
                try:
                    node.destroy_subscription(sub)
                except Exception:
                    pass
            self._subscriptions.clear()
            
            if self._writer is not None:
                del self._writer
                self._writer = None
            
            # Generate session folder path
            if self._config:
                session_folder = self._generate_session_path()
                
                # Write sync_info.json
                self._write_sync_info(session_folder)
            
            self.recording_stopped.emit()
            
        except Exception as e:
            self.error_occurred.emit(f"Error stopping recording: {e}")
        
        return session_folder
    
    def _generate_session_path(self) -> str:
        """Generate session folder path (from plan)."""
        if not self._config or not self._session_start_time:
            return ""
        
        timestamp = self._session_start_time.strftime("%Y-%m-%d_%H-%M-%S")
        
        # Sanitize session name
        sanitized = re.sub(r'[<>:"/\\|?*]', '', self._config.session_name)
        sanitized = sanitized.replace(' ', '_')
        
        folder_name = f"recording_{timestamp}_{sanitized}"
        return os.path.join(self._config.output_path, folder_name)
    
    def _write_sync_info(self, session_folder: str):
        if self._session_start_time is None or self._config is None:
            return

        laz_file_count = 0
        pointcloud_dir = os.path.join(session_folder, 'pointcloud')
        if os.path.isdir(pointcloud_dir):
            laz_file_count = len([f for f in os.listdir(pointcloud_dir) if f.endswith('.laz')])

        svo2_files = [
            f for f in [os.path.join(session_folder, name) for name in os.listdir(session_folder)]
            if f.endswith('.svo2')
        ]

        from ros2_bag_gui.ros2.sync_info import create_sync_info
        create_sync_info(
            session_folder,
            self._session_start_time,
            datetime.now(),
            self._topic_counts,
            lidar_mode=self._config.lidar_mode,
            camera_mode=self._config.camera_mode,
            laz_file_count=laz_file_count,
            svo2_files=svo2_files,
        )
    
    @property
    def is_recording(self) -> bool:
        return self._recording
    
    @property
    def topic_counts(self) -> Dict[str, int]:
        return self._topic_counts.copy()
