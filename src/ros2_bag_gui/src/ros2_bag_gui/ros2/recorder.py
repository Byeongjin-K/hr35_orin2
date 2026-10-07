"""Recording orchestrator: ros2 bag record subprocess + LAZ/SVO2 writers."""
import re
import os
import shutil
import time
import threading
from datetime import datetime
from collections import deque
from typing import List, Dict, Optional
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal, Slot

from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from rosidl_runtime_py.utilities import get_message

from ros2_bag_gui.ros2.bag_process import BagProcess
from ros2_bag_gui.ros2.laz_writer import LAZWriterThread
from ros2_bag_gui.zed.svo_writer import SVO2WriterThread, SVO2Config
from ros2_bag_gui.zed.sdk_check import is_zed_sdk_available
from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)

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
    max_bag_duration: int = 0  # seconds per bag file; 0 = do not split by time
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


def _is_camera_image_topic(topic_name: str) -> bool:
    return any(re.match(p, topic_name) for p in CAMERA_IMAGE_TOPICS)


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
    warning_occurred = Signal(str)  # recording goes on, but not the way it was asked for

    SVO2_OPEN_TIMEOUT_S = 30.0
    MIN_FREE_BYTES = 1024**3  # below this, Start is refused

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bag_proc: Optional[BagProcess] = None
        self._config: Optional[RecordingConfig] = None
        self._topic_counts: Dict[str, int] = {}
        self._topic_timestamps: Dict[str, deque] = {}
        self._counts_lock = threading.Lock()
        self._hz_subscriptions: List[object] = []
        self._laz_subscriptions: List[object] = []
        self._laz_writer: Optional[LAZWriterThread] = None
        self._svo2_writers: List[SVO2WriterThread] = []
        self._session_start_time: Optional[datetime] = None
        self._recording = threading.Event()
        self._node = None
        self._effective_modes = ("bag", "bag")  # (lidar, camera) really in effect
        self._notices: List[str] = []
        self._laz_error_reported = False
        self._stuck_threads: List[object] = []
        self._bag_topics: List[str] = []
        self._bag_counts: Optional[Dict[str, int]] = None
        self._bag_warnings: List[str] = []
        self._bag_warning_reported = False
        self._suspension_reported = False
        self._laz_drop_reported = False
        self._laz_summary: Optional[Dict] = None

    def start_recording(self, config: RecordingConfig, node) -> bool:
        if self._recording.is_set():
            # A second Start would orphan the running recorder and break its bag.
            self.error_occurred.emit(
                "A recording is already running. Stop it before starting another."
            )
            return False
        try:
            self._node = node
            self._config = config
            self._topic_counts = {}
            self._topic_timestamps = {}
            self._session_start_time = datetime.now()

            session_folder = self._generate_session_path()
            rosbag_path = os.path.join(session_folder, 'rosbag')
            os.makedirs(session_folder, exist_ok=True)
            free = shutil.disk_usage(session_folder).free
            if free < self.MIN_FREE_BYTES:
                os.rmdir(session_folder)  # just created, still empty
                raise RuntimeError(
                    f"only {free / 1024**3:.1f} GB free in {config.output_path}; "
                    "a recording would fill the disk and end without a readable bag"
                )

            names = [t['name'] for t in config.topics]
            cb_group = ReentrantCallbackGroup()
            notices: List[str] = []
            self._laz_error_reported = False
            self._laz_drop_reported = False
            self._laz_summary = None

            # Side recorders come up first: a topic is left out of the bag only
            # once the recorder that takes it instead is known to be running.
            camera_mode = self._start_camera_recording(config, session_folder, names, notices)
            keep_in_bag = self._start_lidar_recording(config, session_folder, node, cb_group, notices)
            self._effective_modes = (config.lidar_mode, camera_mode)
            self._notices = notices

            bag_topics = [
                name for name in names
                if name in keep_in_bag
                or should_include_in_rosbag(name, config.lidar_mode, camera_mode)
            ]
            self._bag_topics = bag_topics
            self._bag_counts = None

            bag_proc = BagProcess(self)
            self._bag_proc = bag_proc
            bag_proc.error_occurred.connect(
                lambda msg: self.error_occurred.emit(msg)
            )
            bag_proc.stopped.connect(
                lambda _path, proc=bag_proc: self._on_bag_stopped(proc)
            )
            self._bag_warnings = []
            self._bag_warning_reported = False
            self._suspension_reported = False
            bag_proc.warning.connect(self._on_bag_warning)
            if not bag_proc.start(
                rosbag_path, bag_topics, max_bag_size=config.max_bagfile_size,
                max_bag_duration=config.max_bag_duration,
            ):
                raise RuntimeError(bag_proc.last_error)

            self._recording.set()
            if self._bag_warnings:  # said while starting up
                self._report_bag_warnings(self._bag_warnings)

            for topic in config.topics:
                self._create_hz_subscription(node, topic['name'], topic['type'], cb_group)

            self.recording_started.emit()
            for notice in notices:
                logger.warning(notice)
                self.warning_occurred.emit(notice)
            return True

        except Exception as e:
            self._abort_start()
            self.error_occurred.emit(f"Failed to start recording: {e}")
            return False

    def _abort_start(self):
        """Undo a partly started session so nothing keeps running behind a failed Start."""
        self._recording.clear()
        self._destroy_subscriptions(self._node)
        if self._bag_proc is not None:
            self._bag_proc.stop()
            self._bag_proc = None
        if self._laz_writer is not None:
            self._retire_thread(self._laz_writer)
            self._laz_writer = None
        for writer in self._svo2_writers:
            self._retire_thread(writer)
        self._svo2_writers.clear()
        # Leave no empty session folder behind a Start that did not happen.
        session_folder = self._generate_session_path()
        if session_folder:
            for folder in (os.path.join(session_folder, 'pointcloud'), session_folder):
                try:
                    os.rmdir(folder)
                except OSError:
                    pass  # not there, or it holds data

    def check_health(self) -> None:
        """Call about once a second while recording.

        Catches a recorder that has not exited but cannot record: a process
        suspended by a signal keeps its pid, and nothing else notices.
        """
        if not self._recording.is_set() or self._bag_proc is None:
            return
        if not self._bag_proc.is_suspended:
            self._suspension_reported = False
        elif not self._suspension_reported:
            self._suspension_reported = True
            self.warning_occurred.emit(
                "ros2 bag record is suspended (stopped by a signal): nothing is being "
                f"recorded. Resume it with: kill -CONT {self._bag_proc.pid} "
                "or press Stop and start a new recording."
            )

    def _retire_thread(self, thread) -> None:
        """Stop a writer thread; keep it referenced if it will not stop.

        Dropping a QThread that is still running aborts the whole program.
        """
        if not thread.stop():
            logger.warning("%s did not stop in time; left running", type(thread).__name__)
            self._stuck_threads.append(thread)

    def _start_camera_recording(self, config, session_folder, names, notices) -> str:
        """Start SVO2 recording if asked for; return the camera mode really in effect."""
        mode = config.camera_mode
        if mode not in ("svo2", "both"):
            return mode
        reason = self._start_svo2_writer(session_folder)
        if reason:
            notices.append(
                f"SVO2 recording is NOT running: {reason}. "
                "Camera images are recorded into the bag instead."
            )
            return "bag"
        cameras = sorted({n.split('/')[1] for n in names if _is_camera_image_topic(n)})
        if mode == "svo2" and len(cameras) > 1:
            notices.append(
                "SVO2 records one camera only (camera index 0), but image topics of "
                f"{len(cameras)} cameras are selected ({', '.join(cameras)}). "
                "All camera images are also kept in the bag."
            )
            return "both"
        return mode

    def _start_svo2_writer(self, session_folder: str) -> Optional[str]:
        """Returns None once SVO2 is recording, else the reason it is not."""
        if not is_zed_sdk_available():
            return "the ZED SDK (pyzed) is not installed"
        svo2_path = os.path.join(session_folder, 'camera_0.svo2')
        svo2_config = SVO2Config(output_path=svo2_path, camera_index=0)
        writer = SVO2WriterThread(svo2_config, parent=None)
        writer.error_occurred.connect(self._on_svo2_error)
        writer.start()
        if not writer.wait_until_recording(self.SVO2_OPEN_TIMEOUT_S):
            self._retire_thread(writer)
            return writer.last_error or "the camera could not be opened"
        self._svo2_writers.append(writer)
        logger.info("SVO2 writer started: %s", svo2_path)
        return None

    def _start_lidar_recording(self, config, session_folder, node, cb_group, notices) -> set:
        """Start LAZ recording if asked for; return the lidar topics that must stay in the bag."""
        if config.lidar_mode not in ("laz", "both"):
            return set()
        pointcloud_dir = os.path.join(session_folder, 'pointcloud')
        os.makedirs(pointcloud_dir, exist_ok=True)
        laz_topics = [
            t['name'] for t in config.topics
            if should_record_lidar_laz(t['name'], config.lidar_mode)
        ]
        # One lidar keeps the flat pointcloud/ folder the export tools read.
        # Two or more get a folder each: the files are named by timestamp only.
        subdirs = {}
        if len(laz_topics) > 1:
            subdirs = {t: t.strip('/').replace('/', '_') for t in laz_topics}
        self._laz_writer = LAZWriterThread(pointcloud_dir, parent=None, topic_subdirs=subdirs)
        self._laz_writer.error_occurred.connect(self._on_laz_error)
        self._laz_writer.dropped.connect(self._on_laz_dropped)
        self._laz_writer.start()
        logger.info("LAZ writer started: %s", pointcloud_dir)

        failed = set()
        for topic in config.topics:
            if should_record_lidar_laz(topic['name'], config.lidar_mode):
                if not self._create_laz_subscription(node, topic['name'], topic['type'], cb_group):
                    failed.add(topic['name'])
        if failed:
            notices.append(
                f"LAZ recording could not subscribe to {', '.join(sorted(failed))}. "
                "These topics are recorded into the bag."
            )
        return failed

    @Slot(str)
    def _on_svo2_error(self, msg: str):
        logger.error("SVO2 writer error: %s", msg)
        # A failure while opening is handled by Start itself (the writer is not listed yet).
        if self.sender() in self._svo2_writers and self._recording.is_set():
            if self._effective_modes[1] == "both":
                consequence = "Camera images are still recorded into the bag."
            else:
                consequence = (
                    "Camera images are NOT being recorded any more. "
                    "Stop and start a new recording."
                )
            self.error_occurred.emit(f"SVO2 recording failed: {msg}. {consequence}")

    @Slot(str)
    def _on_laz_error(self, msg: str):
        logger.error("LAZ writer error: %s", msg)
        if self._recording.is_set() and not self._laz_error_reported:
            self._laz_error_reported = True  # one dialog per session, the rest is in the log
            if self._effective_modes[0] == "both":
                consequence = "The point clouds are still recorded into the bag."
            else:
                consequence = "Point cloud frames are being lost."
            self.error_occurred.emit(f"LAZ writing failed: {msg}. {consequence}")

    @Slot(int)
    def _on_laz_dropped(self, count: int):
        """The LAZ queue was full and a frame was thrown away (writing is too slow)."""
        if self._recording.is_set() and not self._laz_drop_reported:
            self._laz_drop_reported = True  # the total is reported at Stop
            if self._effective_modes[0] == "both":
                consequence = "The frames are still recorded into the bag."
            else:
                consequence = "These frames are lost: in LAZ mode the lidar is not in the bag."
            self.warning_occurred.emit(
                f"LAZ writing cannot keep up: point cloud frames are being dropped. {consequence}"
            )

    def _destroy_subscriptions(self, node):
        if node is not None:
            for sub in self._hz_subscriptions + self._laz_subscriptions:
                try:
                    node.destroy_subscription(sub)
                except Exception:
                    pass
        self._hz_subscriptions.clear()
        self._laz_subscriptions.clear()

    def _on_bag_warning(self, line: str):
        """The recorder reported a problem (e.g. messages lost to a slow disk).

        This also arrives while Stop waits for the recorder to close the bag.
        """
        self._bag_warnings.append(line)
        # Outside a recording (starting up, closing the bag) the lines are
        # collected and reported together by whoever is waiting for the recorder.
        if self._recording.is_set() and not self._bag_warning_reported:
            self._report_bag_warnings([line])

    def _report_bag_warnings(self, lines: List[str]):
        self._bag_warning_reported = True  # one dialog per phase; all lines go to the log and sync_info
        self.warning_occurred.emit(
            "ros2 bag record reported a problem: " + " ".join(lines[:6]) + " "
            "Data may be missing from the bag. "
            "All recorder messages are in the log and in sync_info.json."
        )

    def _on_bag_stopped(self, proc: BagProcess):
        """The recorder process ended. During a recording that means data is being lost."""
        if proc is not self._bag_proc or not self._recording.is_set():
            return
        self._finish_session(
            self._node,
            "ros2 bag record ended while recording. "
            "Nothing has been recorded since then. "
            "Check the session folder, then start a new recording."
            f"\n\nDetails: {proc.exit_description}",
        )

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
            logger.warning("Hz subscription failed for %s: %s", topic_name, e)

    def _create_laz_subscription(self, node, topic_name: str, topic_type: str, cb_group) -> bool:
        try:
            msg_class = get_message(topic_type)

            def raw_cb(raw_bytes, topic=topic_name, cls=msg_class):
                self._on_laz_raw(topic, raw_bytes, cls)

            sub = node.create_subscription(
                msg_class, topic_name, raw_cb, SENSOR_QOS,
                callback_group=cb_group, raw=True,
            )
            self._laz_subscriptions.append(sub)
            return True
        except Exception as e:
            logger.error("LAZ subscription failed for %s: %s", topic_name, e)
            return False

    def _on_raw_tick(self, topic_name: str):
        if not self._recording.is_set():
            return
        now = time.monotonic()
        with self._counts_lock:
            self._topic_counts[topic_name] = self._topic_counts.get(topic_name, 0) + 1
            ts_list = self._topic_timestamps.setdefault(topic_name, deque())
            ts_list.append(now)
            cutoff = now - 3.0
            while ts_list and ts_list[0] < cutoff:
                ts_list.popleft()

    def _on_laz_raw(self, topic_name: str, raw_bytes, msg_class):
        if not self._recording.is_set() or self._laz_writer is None:
            return
        try:
            self._laz_writer.enqueue_raw(bytes(raw_bytes), msg_class, topic_name)
        except Exception as e:
            logger.debug("LAZ enqueue error for %s: %s", topic_name, e)

    def stop_recording(self, node=None, reason: Optional[str] = None) -> str:
        """Stop and close the session.

        reason: set when the stop was not the operator's (e.g. the disk is nearly
        full); it is written to sync_info.json as a forced stop.
        """
        if not self._recording.is_set():
            return ""
        return self._finish_session(node if node is not None else self._node, None, reason)

    def _finish_session(self, node, failure: Optional[str], forced_reason: Optional[str] = None) -> str:
        self._recording.clear()
        session_folder = ""

        try:
            self._destroy_subscriptions(node)

            if self._laz_writer is not None:
                laz = self._laz_writer
                self._retire_thread(laz)
                self._laz_summary = {
                    'dropped_frames': laz.drop_count,
                    'write_errors': laz.error_count,
                    'topics': {
                        topic: {
                            'path': os.path.join('pointcloud', laz.subdir_for(topic), ''),
                            'file_count': count,
                        }
                        for topic, count in laz.file_counts.items()
                    },
                }
                logger.info("LAZ writer stopped: %d files, %d frames dropped, %d errors",
                            laz.file_count, laz.drop_count, laz.error_count)
                if laz.drop_count or laz.error_count:
                    message = (
                        f"LAZ recording is incomplete: {laz.drop_count} frames dropped, "
                        f"{laz.error_count} write errors, {laz.file_count} files written."
                    )
                    logger.warning(message)
                    self.warning_occurred.emit(message)
                self._laz_writer = None

            if self._bag_proc is not None:
                said_before = len(self._bag_warnings)
                was_alive = self._bag_proc.stop()
                if failure is None and not was_alive:
                    failure = (
                        "ros2 bag record had already ended before Stop. "
                        "The end of this session is missing from the bag."
                        f"\n\nDetails: {self._bag_proc.exit_description}"
                    )
                elif failure is None and self._bag_proc.killed_on_stop:
                    failure = (
                        "ros2 bag record did not close the bag in time and was killed. "
                        "The bag has no metadata.yaml and its last seconds may be missing. "
                        "Recover it with: ros2 bag reindex -s sqlite3 <session>/rosbag"
                    )
                said_while_closing = self._bag_warnings[said_before:]
                if said_while_closing:
                    # e.g. "Cache buffers lost messages per topic: ... Total lost: N"
                    self._report_bag_warnings(said_while_closing)
                logger.info("ros2 bag record stopped")
                self._bag_proc = None

            for writer in self._svo2_writers:
                self._retire_thread(writer)
                logger.info("SVO2 writer stopped: %d frames at %s",
                            writer.frame_count, writer.output_path)
            self._svo2_writers.clear()

            if self._config:
                session_folder = self._generate_session_path()
                self._write_sync_info(session_folder, failure or forced_reason)

            self.recording_stopped.emit()

        except Exception as e:
            self.error_occurred.emit(f"Error stopping recording: {e}")

        if failure is not None:
            self.error_occurred.emit(failure)

        return session_folder

    def _generate_session_path(self) -> str:
        if not self._config or not self._session_start_time:
            return ""
        timestamp = self._session_start_time.strftime("%Y-%m-%d_%H-%M-%S")
        sanitized = re.sub(r'[<>:"/\\|?*]', '', self._config.session_name)
        sanitized = sanitized.replace(' ', '_')
        folder_name = f"recording_{timestamp}_{sanitized}"
        return os.path.join(self._config.output_path, folder_name)

    def _write_sync_info(self, session_folder: str, failure: Optional[str] = None):
        if self._session_start_time is None or self._config is None:
            return

        laz_file_count = 0
        pointcloud_dir = os.path.join(session_folder, 'pointcloud')
        for _root, _dirs, files in os.walk(pointcloud_dir):
            laz_file_count += len([f for f in files if f.endswith('.laz')])

        svo2_files = []
        if os.path.isdir(session_folder):
            svo2_files = [
                f for f in [os.path.join(session_folder, name) for name in os.listdir(session_folder)]
                if f.endswith('.svo2')
            ]

        from ros2_bag_gui.ros2.sync_info import create_sync_info, read_bag_message_counts
        self._bag_counts = read_bag_message_counts(os.path.join(session_folder, 'rosbag'))
        create_sync_info(
            session_folder,
            self._session_start_time,
            datetime.now(),
            self._topic_counts,
            lidar_mode=self._effective_modes[0],
            camera_mode=self._effective_modes[1],
            notices=self._notices,
            bag_message_counts=self._bag_counts,
            recorder_warnings=self._bag_warnings,
            laz_summary=self._laz_summary,
            laz_file_count=laz_file_count,
            svo2_files=svo2_files,
            forced_stop=failure is not None,
            stop_reason=failure,
        )

    @property
    def is_recording(self) -> bool:
        return self._recording.is_set()

    @property
    def session_path(self) -> str:
        return self._generate_session_path()

    @property
    def last_bag_counts(self) -> Optional[Dict[str, int]]:
        """Per-topic counts read from the last finished bag; None if unreadable."""
        return None if self._bag_counts is None else dict(self._bag_counts)

    @property
    def last_bag_topics(self) -> List[str]:
        """The topics the last recording asked the bag to hold."""
        return list(self._bag_topics)

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
                    ts_list.popleft()
                if len(ts_list) >= 2:
                    span = ts_list[-1] - ts_list[0]
                    result[topic] = (len(ts_list) - 1) / span if span > 0 else 0.0
                else:
                    result[topic] = 0.0
        return result
