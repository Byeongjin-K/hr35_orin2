"""Recording orchestrator: ros2 bag record subprocess + LAZ/SVO2 writers."""
import re
import os
import time
import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal

from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from rosidl_runtime_py.utilities import get_message

from ros2_bag_gui.ros2.bag_process import BagProcess
from ros2_bag_gui.ros2.laz_writer import LAZWriterThread, create_payload_from_msg
from ros2_bag_gui.zed.svo_writer import SVO2WriterThread, SVO2Config
from ros2_bag_gui.zed.sdk_check import is_zed_sdk_available

logger = logging.getLogger(__name__)

LIDAR_TOPICS = [r'^/lidar_boom/points$', r'^/ouster/points$']
CAMERA_IMAGE_TOPICS = [
    r'^/zedx_[^/]+/[^/]+/.*image.*$',
    r'^/zedx_[^/]+/[^/]+/.*depth.*$',
]
SYSTEM_EXCLUDE = [r'^/rosout$']

SENSOR_QOS = QoSProfile(
    depth=10,
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
)


@dataclass
class RecordingConfig:
    topics: List[Dict[str, str]]
    output_path: str
    session_name: str
    max_bagfile_size: int = 3 * 1024**3
    lidar_mode: str = "bag"
    camera_mode: str = "bag"


def should_include_in_rosbag(
    topic_name: str,
    lidar_mode: str,
    camera_mode: str,
) -> bool:
    for p in SYSTEM_EXCLUDE:
        if re.match(p, topic_name):
            return False
    for p in LIDAR_TOPICS:
        if re.match(p, topic_name):
            return lidar_mode in ("bag", "both")
    for p in CAMERA_IMAGE_TOPICS:
        if re.match(p, topic_name):
            return camera_mode in ("bag", "both")
    return True


def should_record_lidar_laz(topic_name: str, lidar_mode: str) -> bool:
    for p in LIDAR_TOPICS:
        if re.match(p, topic_name):
            return lidar_mode in ("laz", "both")
    return False


class Recorder(QObject):

    recording_started = Signal()
    recording_stopped = Signal()
    message_recorded = Signal(str, int)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bag_proc: Optional[BagProcess] = None
        self._config: Optional[RecordingConfig] = None
        self._topic_counts: Dict[str, int] = {}
        self._topic_timestamps: Dict[str, List[float]] = {}
        self._counts_lock = threading.Lock()
        self._hz_subscriptions: List[object] = []
        self._laz_subscriptions: List[object] = []
        self._laz_writer: Optional[LAZWriterThread] = None
        self._svo2_writers: List[SVO2WriterThread] = []
        self._session_start_time: Optional[datetime] = None
        self._recording = False

    def start_recording(self, config: RecordingConfig, node) -> bool:
        try:
            self._config = config
            self._topic_counts = {}
            self._topic_timestamps = {}
            self._session_start_time = datetime.now()

            session_folder = self._generate_session_path()
            rosbag_path = os.path.join(session_folder, 'rosbag')
            os.makedirs(session_folder, exist_ok=True)

            bag_topics = [
                t['name'] for t in config.topics
                if should_include_in_rosbag(t['name'], config.lidar_mode, config.camera_mode)
            ]

            self._bag_proc = BagProcess(self)
            self._bag_proc.error_occurred.connect(
                lambda msg: self.error_occurred.emit(msg)
            )
            self._bag_proc.start(
                rosbag_path, bag_topics, max_bag_size=config.max_bagfile_size
            )

            cb_group = ReentrantCallbackGroup()

            for topic in config.topics:
                self._create_hz_subscription(node, topic['name'], topic['type'], cb_group)

            if config.lidar_mode in ("laz", "both"):
                pointcloud_dir = os.path.join(session_folder, 'pointcloud')
                self._laz_writer = LAZWriterThread(pointcloud_dir, parent=None)
                self._laz_writer.error_occurred.connect(
                    lambda msg: logger.error("LAZ writer error: %s", msg)
                )
                self._laz_writer.start()
                logger.info("LAZ writer started: %s", pointcloud_dir)

                for topic in config.topics:
                    if should_record_lidar_laz(topic['name'], config.lidar_mode):
                        self._create_laz_subscription(node, topic['name'], topic['type'], cb_group)

            if config.camera_mode in ("svo2", "both") and is_zed_sdk_available():
                svo2_path = os.path.join(session_folder, 'camera_0.svo2')
                svo2_config = SVO2Config(output_path=svo2_path, camera_index=0)
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

    def _create_hz_subscription(self, node, topic_name: str, topic_type: str, cb_group):
        try:
            msg_class = get_message(topic_type)

            def raw_cb(_raw_bytes, topic=topic_name):
                self._on_raw_tick(topic)

            sub = node.create_subscription(
                msg_class, topic_name, raw_cb, SENSOR_QOS,
                callback_group=cb_group, raw=True,
            )
            self._hz_subscriptions.append(sub)
        except Exception as e:
            logger.debug("Hz subscription failed for %s: %s", topic_name, e)

    def _create_laz_subscription(self, node, topic_name: str, topic_type: str, cb_group):
        try:
            msg_class = get_message(topic_type)

            def typed_cb(msg, topic=topic_name):
                self._on_laz_message(topic, msg)

            sub = node.create_subscription(
                msg_class, topic_name, typed_cb, SENSOR_QOS,
                callback_group=cb_group,
            )
            self._laz_subscriptions.append(sub)
        except Exception as e:
            logger.error("LAZ subscription failed for %s: %s", topic_name, e)

    def _on_raw_tick(self, topic_name: str):
        if not self._recording:
            return
        now = time.monotonic()
        with self._counts_lock:
            self._topic_counts[topic_name] = self._topic_counts.get(topic_name, 0) + 1
            ts_list = self._topic_timestamps.setdefault(topic_name, [])
            ts_list.append(now)
            cutoff = now - 3.0
            while ts_list and ts_list[0] < cutoff:
                ts_list.pop(0)

    def _on_laz_message(self, topic_name: str, msg):
        if not self._recording or self._laz_writer is None:
            return
        try:
            timestamp_ns = self._get_timestamp_ns(msg)
            laz_payload = create_payload_from_msg(msg, timestamp_ns)
            self._laz_writer.enqueue(laz_payload)
        except Exception as e:
            logger.debug("LAZ enqueue error for %s: %s", topic_name, e)

    def _get_timestamp_ns(self, msg) -> int:
        if hasattr(msg, 'header') and hasattr(msg.header, 'stamp'):
            return msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
        elif hasattr(msg, 'transforms') and len(msg.transforms) > 0:
            stamp = msg.transforms[0].header.stamp
            return stamp.sec * 10**9 + stamp.nanosec
        else:
            return time.time_ns()

    def stop_recording(self, node) -> str:
        if not self._recording:
            return ""

        self._recording = False
        session_folder = ""

        try:
            if self._bag_proc is not None:
                self._bag_proc.stop()
                logger.info("ros2 bag record stopped")
                self._bag_proc = None

            if self._laz_writer is not None:
                self._laz_writer.stop()
                logger.info("LAZ writer stopped: %d files", self._laz_writer.file_count)
                self._laz_writer = None

            for writer in self._svo2_writers:
                writer.stop()
                logger.info("SVO2 writer stopped: %d frames at %s",
                            writer.frame_count, writer._config.output_path)
            self._svo2_writers.clear()

            for sub in self._hz_subscriptions + self._laz_subscriptions:
                try:
                    node.destroy_subscription(sub)
                except Exception:
                    pass
            self._hz_subscriptions.clear()
            self._laz_subscriptions.clear()

            if self._config:
                session_folder = self._generate_session_path()
                self._write_sync_info(session_folder)

            self.recording_stopped.emit()

        except Exception as e:
            self.error_occurred.emit(f"Error stopping recording: {e}")

        return session_folder

    def _generate_session_path(self) -> str:
        if not self._config or not self._session_start_time:
            return ""
        timestamp = self._session_start_time.strftime("%Y-%m-%d_%H-%M-%S")
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

        svo2_files = []
        if os.path.isdir(session_folder):
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
        with self._counts_lock:
            return self._topic_counts.copy()

    def get_topic_hz(self) -> Dict[str, float]:
        now = time.monotonic()
        window = 3.0
        result: Dict[str, float] = {}
        with self._counts_lock:
            for topic, ts_list in self._topic_timestamps.items():
                cutoff = now - window
                while ts_list and ts_list[0] < cutoff:
                    ts_list.pop(0)
                if len(ts_list) >= 2:
                    span = ts_list[-1] - ts_list[0]
                    result[topic] = (len(ts_list) - 1) / span if span > 0 else 0.0
                else:
                    result[topic] = 0.0
        return result
