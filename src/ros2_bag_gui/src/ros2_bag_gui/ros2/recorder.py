"""Recording orchestrator: ros2 bag record subprocess + LAZ/SVO2 writers."""
import re
import os
import contextlib
import ctypes
import shutil
import threading
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from PySide6.QtCore import QObject, Signal, Slot

from ament_index_python.packages import get_package_prefix
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from rosidl_runtime_py.utilities import get_message, get_service

from ros2_bag_gui.ros2.bag_process import BagProcess
from ros2_bag_gui.ros2.laz_writer import LAZWriterThread
from ros2_bag_gui.ros2.qos_overrides import (
    OVERRIDES_FILE, mixed_durability_overrides, write_qos_overrides,
)
from ros2_bag_gui.zed.svo_writer import SVO2WriterThread, SVO2Config
from ros2_bag_gui.zed.sdk_check import is_zed_sdk_available, list_zed_cameras
from ros2_bag_gui.zed.camera_names import camera_label, camera_names_by_serial
from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)

# Each lidar is recorded on its own terms, so its point cloud topics are named
# per lidar. /ouster/points is the boom lidar under a single-sensor bringup.
LIDAR_GROUPS = {
    'boom': [r'^/lidar_boom/points$', r'^/ouster/points$'],
    'cabin': [r'^/lidar_cabin/points$'],
}
DEFAULT_LIDAR_MODES = {group: "bag" for group in LIDAR_GROUPS}
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

# The LAZ writer's subscription, when every publisher of the lidar topic is
# reliable (the Ouster driver is). A point cloud travels in many fragments: a
# best-effort reader loses the whole frame with one of them, and gets no resend.
LAZ_RELIABLE_QOS = QoSProfile(
    depth=10,
    reliability=QoSReliabilityPolicy.RELIABLE,
    history=QoSHistoryPolicy.KEEP_LAST,
)

# What ros2 bag record says (Humble). The first comes at every start when the
# graph has hidden topics; the second, with its reason on the next line, on each
# discovery pass (several a second) that fails to subscribe to a topic.
_HIDDEN_NOT_RECORDED = "Hidden topics are not recorded"
_DISCOVERY_FAILURE = "Failure in topics discovery"


@dataclass
class RecordingConfig:
    topics: List[Dict[str, str]]
    output_path: str
    session_name: str
    max_bagfile_size: int = 3 * 1024**3
    max_bag_duration: int = 0  # seconds per bag file; 0 = do not split by time
    lidar_modes: Dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_LIDAR_MODES))
    camera_mode: str = "bag"
    svo2_camera_serial: str = ""  # "" = the first camera that opens


def lidar_group_of(topic_name: str) -> Optional[str]:
    for group, patterns in LIDAR_GROUPS.items():
        if any(re.match(p, topic_name) for p in patterns):
            return group
    return None


def should_include_in_rosbag(
    topic_name: str,
    lidar_modes: Dict[str, str],
    camera_mode: str,
) -> bool:
    for p in SYSTEM_EXCLUDE:
        if re.match(p, topic_name):
            return False
    group = lidar_group_of(topic_name)
    if group is not None:
        return lidar_modes.get(group, "bag") in ("bag", "both")
    for p in CAMERA_IMAGE_TOPICS:
        if re.match(p, topic_name):
            return camera_mode in ("bag", "both")
    return True


def _is_camera_image_topic(topic_name: str) -> bool:
    return any(re.match(p, topic_name) for p in CAMERA_IMAGE_TOPICS)


def should_record_lidar_laz(topic_name: str, lidar_modes: Dict[str, str]) -> bool:
    group = lidar_group_of(topic_name)
    if group is None:
        return False
    return lidar_modes.get(group, "bag") in ("laz", "both")


def unloadable_types(topics: List[Dict[str, str]]) -> Dict[str, str]:
    """The topics whose message type ros2 bag record cannot load here: name -> type.

    It cannot subscribe to them, and in Humble each failed try also ends the
    discovery pass it is in, so topics it had not reached yet are left out too.
    Looked up the way rosbag2 does it: the package's C++ type support library
    and the type's symbol in it. Topics not up yet (type 'unknown') are skipped.
    """
    loadable: Dict[str, bool] = {}
    result = {}
    for topic in topics:
        type_name = topic['type']
        if type_name == 'unknown':
            continue
        if type_name not in loadable:
            loadable[type_name] = _recorder_can_load(type_name)
        if not loadable[type_name]:
            result[topic['name']] = type_name
    return result


def _recorder_can_load(type_name: str) -> bool:
    try:
        package, interface, name = type_name.split('/')
        library = ctypes.CDLL(os.path.join(
            get_package_prefix(package), 'lib', f'lib{package}__rosidl_typesupport_cpp.so'))
        getattr(library, 'rosidl_typesupport_cpp__get_message_type_support_handle__'
                         f'{package}__{interface}__{name}')
        return True
    except (ValueError, LookupError, OSError, AttributeError):
        return False


def _is_hidden(topic_name: str) -> bool:
    return any(token.startswith('_') for token in topic_name.split('/'))


class SvoDriverBusy(Exception):
    """A ZED driver already records an SVO2 that this session did not start."""


class Recorder(QObject):

    recording_started = Signal()
    recording_stopped = Signal()
    message_recorded = Signal(str, int)
    error_occurred = Signal(str)
    warning_occurred = Signal(str)  # recording goes on, but not the way it was asked for

    SVO2_OPEN_TIMEOUT_S = 30.0
    SERVICE_TIMEOUT_S = 5.0  # a ZED driver's answer to a start request
    # Stopping flushes the SVO2 file through its H.265 encoder, which takes longer
    # than a start; timing out here would report a recording as forced-stopped.
    SVO_STOP_TIMEOUT_S = 30.0
    MIN_FREE_BYTES = 1024**3  # below this, Start is refused

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bag_proc: Optional[BagProcess] = None
        self._config: Optional[RecordingConfig] = None
        self._laz_subscriptions: List[object] = []
        self._laz_writer: Optional[LAZWriterThread] = None
        self._svo2_writers: List[SVO2WriterThread] = []
        self._session_start_time: Optional[datetime] = None
        self._last_duration_s = 0.0
        self._recording = threading.Event()
        self._node = None
        # (per-lidar modes, camera mode) really in effect
        self._effective_modes = (dict(DEFAULT_LIDAR_MODES), "bag")
        self._laz_groups = set()  # lidars whose LAZ subscription really started
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
        # Why ros2 bag record could not subscribe to a topic, each reason once
        self._discovery_failures: List[str] = []
        self._discovery_reason_next = False
        self._discovery_failure_reported = False
        self._driver_svo: List[str] = []  # ZED drivers recording SVO2 for this session
        self._driver_stop_failures: List[str] = []  # ...that did not stop at the last Stop
        self._busy_svo_drivers: List[str] = []  # ZED drivers that already recorded at Start

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
            self._busy_svo_drivers = []
            self._session_start_time = datetime.now()

            session_folder = self._generate_session_path()
            rosbag_path = os.path.join(session_folder, 'rosbag')
            os.makedirs(session_folder, exist_ok=True)
            free = shutil.disk_usage(session_folder).free
            if free < self.MIN_FREE_BYTES:
                try:
                    os.rmdir(session_folder)  # just created, still empty
                except OSError:
                    pass  # it already holds data: keep it, and still report the disk
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
            camera_mode, keep_images = self._start_camera_recording(
                config, session_folder, names, node, notices)
            keep_in_bag = keep_images | self._start_lidar_recording(
                config, session_folder, node, cb_group, notices)
            self._effective_modes = (
                self._effective_lidar_modes(config), "both" if keep_images else camera_mode)
            self._notices = notices

            bag_topics = [
                name for name in names
                if name in keep_in_bag
                or should_include_in_rosbag(name, config.lidar_modes, camera_mode)
            ]
            self._bag_topics = bag_topics
            self._bag_counts = None
            self._bag_warnings = []
            self._bag_warning_reported = False
            self._discovery_failures = []
            self._discovery_reason_next = False
            self._discovery_failure_reported = False
            self._suspension_reported = False
            # ros2 bag record refuses an empty topic list (it would only say "Invalid
            # choice" from inside a failed Start): with nothing for the bag, SVO2 alone.
            if bag_topics:
                bag_proc = BagProcess(self)
                self._bag_proc = bag_proc
                bag_proc.error_occurred.connect(
                    lambda msg: self.error_occurred.emit(msg)
                )
                bag_proc.stopped.connect(
                    lambda _path, proc=bag_proc: self._on_bag_stopped(proc)
                )
                bag_proc.warning.connect(self._on_bag_warning)
                if not bag_proc.start(
                    rosbag_path, bag_topics, max_bag_size=config.max_bagfile_size,
                    max_bag_duration=config.max_bag_duration,
                    include_hidden_topics=any(map(_is_hidden, bag_topics)),
                    qos_overrides_path=write_qos_overrides(
                        session_folder, mixed_durability_overrides(node, bag_topics)),
                ):
                    raise RuntimeError(bag_proc.last_error)
            elif self._driver_svo or self._svo2_writers:
                logger.info("Recording SVO2 only: no selected topic goes into the bag")
            elif config.camera_mode in ("svo2", "both"):
                raise RuntimeError(
                    "nothing would be recorded: no selected topic goes into the bag and "
                    f"SVO2 recording did not start. {' '.join(notices)}"
                )
            else:
                raise RuntimeError(
                    "no selected topic would go into the bag: every selected lidar is "
                    "recorded to LAZ and nothing else is selected. Select another topic, "
                    'or set a lidar to "both" so its point clouds are in the bag too'
                )

            self._recording.set()
            if self._discovery_failures:  # said while starting up
                self._report_discovery_failure()
            if self._bag_warnings:
                self._report_bag_warnings(self._bag_warnings)

            # Recorded topics are not received a second time just to count them live:
            # on the robot that cost the GUI about a core (rclpy callbacks of /tf, the
            # IMUs, ...). What is in the bag is read from it at Stop.
            self.recording_started.emit()
            for notice in notices:
                logger.warning(notice)
                self.warning_occurred.emit(notice)
            return True

        except SvoDriverBusy:
            self._abort_start()
            return False  # the operator decides: see busy_svo_drivers and stop_driver_svo2
        except Exception as e:
            self._abort_start()
            self.error_occurred.emit(f"Failed to start recording: {e}")
            return False

    def _abort_start(self):
        """Undo a partly started session so nothing keeps running behind a failed Start."""
        self._recording.clear()
        self._destroy_subscriptions(self._node)
        for failure in self._stop_driver_svo2(self._node, self._driver_svo):
            logger.error(failure)
        self._driver_svo = []
        if self._bag_proc is not None:
            self._bag_proc.stop()
            self._bag_proc = None
        if self._laz_writer is not None:
            self._retire_thread(self._laz_writer)
            self._laz_writer = None
        for writer in self._svo2_writers:
            self._retire_thread(writer)
        self._svo2_writers.clear()
        # Leave no empty session folder behind a Start that did not happen. Only
        # empty directories go: bottom-up rmdir keeps anything that holds data.
        session_folder = self._generate_session_path()
        if session_folder:
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(session_folder, OVERRIDES_FILE))
            for root, dirs, _files in os.walk(session_folder, topdown=False):
                for name in dirs:
                    try:
                        os.rmdir(os.path.join(root, name))
                    except OSError:
                        pass
            try:
                os.rmdir(session_folder)
            except OSError:
                pass

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

    def _start_camera_recording(self, config, session_folder, names, node, notices) -> Tuple[str, set[str]]:
        """Start SVO2 recording if asked for.

        A camera whose ZED ROS driver runs is recorded by that driver: it holds the
        camera open and goes on publishing. A camera without a driver is opened here.
        Returns the camera mode for the bag, and the image topics that stay in the
        bag anyway because no SVO2 records their camera.
        """
        mode = config.camera_mode
        if mode not in ("svo2", "both"):
            return mode, set()
        by_driver, failures = self._start_driver_svo2(node, session_folder)
        reason = self._start_direct_svo2(config.svo2_camera_serial, session_folder, bool(by_driver))
        if reason:
            failures.append(reason)
        if not by_driver and not self._svo2_writers:
            notices.append(
                f"SVO2 recording is NOT running: {'; '.join(failures) or 'no ZED camera to record'}. "
                "Camera images are recorded into the bag instead."
            )
            return "bag", set()
        notices.extend(f"SVO2 recording is incomplete: {failure}." for failure in failures)
        if mode == "both":
            return mode, set()
        # Images published through ROS are of a camera a driver holds: unless that
        # driver records the SVO2, nothing does, so they stay in the bag.
        keep = {n for n in names if _is_camera_image_topic(n)
                and n.split('/')[1] not in by_driver and node.count_publishers(n) > 0}
        return mode, keep

    @staticmethod
    def _svo2_drivers(node) -> List[str]:
        """The running ZED ROS drivers that record SVO2 on request, by node path."""
        suffix = '/start_svo_rec'
        return sorted(
            name[:-len(suffix)] for name, types in node.get_service_names_and_types()
            if name.endswith(suffix) and 'zed_msgs/srv/StartSvoRec' in types
        )

    def _start_driver_svo2(self, node, session_folder: str) -> Tuple[set[str], List[str]]:
        """Have each running ZED ROS driver record its camera into the session folder.

        Returns the cameras it records (e.g. zedx_cabin) and what failed.
        """
        recording, failures = set(), []
        for path in self._svo2_drivers(node):  # e.g. /zedx_cabin/zedx_cabin_node
            camera = path.split('/')[1]
            filename = os.path.join(os.path.abspath(session_folder), f'{camera}.svo2')
            ok, message = self._call_service(
                node, 'zed_msgs/srv/StartSvoRec', f'{path}/start_svo_rec',
                compression_mode=2, svo_filename=filename)  # 2: H.265 in the driver's numbering
            if ok:
                self._driver_svo.append(path)
                recording.add(camera)
                logger.info("SVO2 recorded by the %s driver: %s", camera, filename)
            elif 'already enabled' in message:
                self._busy_svo_drivers.append(path)
            else:
                failures.append(f"the {camera} driver did not start ({message})")
        if self._busy_svo_drivers:
            raise SvoDriverBusy(", ".join(self._busy_svo_drivers))
        return recording, failures

    def _start_direct_svo2(self, serial: str, session_folder: str, drivers_record: bool) -> Optional[str]:
        """Open a camera no driver holds and record it; return why that did not happen.

        A camera that is held open is taken to be held by its driver: while drivers
        record, that is no failure.
        """
        if not is_zed_sdk_available():
            return "the ZED SDK (pyzed) is not installed"
        free = {s: available for s, _model, available in list_zed_cameras()}
        if serial and not free.get(serial):
            if serial in free and drivers_record:
                return None
            return f"{camera_label(serial)} is not connected or is held by another program"
        if not serial and not any(free.values()):
            return None if drivers_record else "no ZED camera is free to open"
        # "auto" is resolved here, not left to the SDK, so the file can be named after the camera
        chosen = serial or next(s for s, available in free.items() if available)
        return self._start_svo2_writer(session_folder, chosen)

    def _call_service(self, node, srv_type_name: str, name: str,
                      timeout_s: Optional[float] = None, **fields) -> Tuple[bool, str]:
        """Call a service and wait for its answer, which the ROS thread's executor delivers."""
        timeout_s = self.SERVICE_TIMEOUT_S if timeout_s is None else timeout_s
        srv_type = get_service(srv_type_name)
        client = node.create_client(srv_type, name, callback_group=ReentrantCallbackGroup())
        try:
            if not client.wait_for_service(timeout_sec=self.SERVICE_TIMEOUT_S):
                return False, "its service is not available"
            answered = threading.Event()
            future = client.call_async(srv_type.Request(**fields))
            future.add_done_callback(lambda _future: answered.set())
            if not answered.wait(timeout_s):
                return False, f"no answer within {timeout_s:.0f} s"
            response = future.result()
            return response.success, response.message
        finally:
            node.destroy_client(client)

    def _stop_driver_svo2(self, node, paths: List[str]) -> List[str]:
        """Ask ZED drivers to stop recording SVO2; return what failed."""
        failures = []
        for path in paths:
            ok, message = self._call_service(
                node, 'std_srvs/srv/Trigger', f'{path}/stop_svo_rec',
                timeout_s=self.SVO_STOP_TIMEOUT_S)
            if ok:
                continue
            if path not in self._svo2_drivers(node):
                # Seen on this robot: the driver died inside its own stop (SIGSEGV in
                # the SVO2 encoder teardown). The file is closed, the camera is gone.
                failures.append(
                    f"The ZED driver {path} is no longer running: it ended while closing its "
                    "SVO2 file. The recorded file is in the session folder, but this camera "
                    "publishes nothing until the sensors are started again."
                )
            else:
                failures.append(
                    f"The ZED driver {path} did not stop recording SVO2 ({message}). It goes on "
                    f"writing until stopped: ros2 service call {path}/stop_svo_rec std_srvs/srv/Trigger"
                )
        return failures

    @property
    def driver_stop_failures(self) -> List[str]:
        """ZED drivers that did not stop recording SVO2 at the last Stop, with how to stop them."""
        return list(self._driver_stop_failures)

    @property
    def busy_svo_drivers(self) -> List[str]:
        """ZED drivers that already recorded an SVO2 at the last Start, which then stopped."""
        return list(self._busy_svo_drivers)

    def stop_driver_svo2(self, paths: List[str], node) -> List[str]:
        """Stop SVO2 recordings this session did not start (the operator said so)."""
        self._busy_svo_drivers = []
        return self._stop_driver_svo2(node, paths)

    def _start_svo2_writer(self, session_folder: str, camera_serial: str = "") -> Optional[str]:
        """Returns None once SVO2 is recording, else the reason it is not.

        camera_serial: the ZED camera to record; "" records the first that opens.
        """
        if not is_zed_sdk_available():
            return "the ZED SDK (pyzed) is not installed"
        # Named after the camera when its name is known, so the file says which one it is
        name = camera_names_by_serial().get(camera_serial, '') if camera_serial else ''
        svo2_path = os.path.join(session_folder, f'{name or "camera_0"}.svo2')
        svo2_config = SVO2Config(
            output_path=svo2_path, camera_serial=camera_serial, camera_index=0)
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
        self._laz_groups = set()
        laz_topics = [
            t['name'] for t in config.topics
            if should_record_lidar_laz(t['name'], config.lidar_modes)
        ]
        if not laz_topics:
            return set()
        pointcloud_dir = os.path.join(session_folder, 'pointcloud')
        os.makedirs(pointcloud_dir, exist_ok=True)
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
            if topic['name'] not in laz_topics:
                continue
            if self._create_laz_subscription(node, topic['name'], topic['type'], cb_group):
                self._laz_groups.add(lidar_group_of(topic['name']))
            else:
                failed.add(topic['name'])
        if failed:
            notices.append(
                f"LAZ recording could not subscribe to {', '.join(sorted(failed))}. "
                "These topics are recorded into the bag."
            )
        return failed

    def _effective_lidar_modes(self, config) -> Dict[str, str]:
        """A lidar asked for LAZ whose subscription never started is in the bag instead."""
        return {
            group: ("bag" if mode in ("laz", "both") and group not in self._laz_groups
                    else mode)
            for group, mode in config.lidar_modes.items()
        }

    def _laz_frames_also_in_bag(self) -> bool:
        modes = self._effective_modes[0]
        recording = [modes.get(group) for group in self._laz_groups]
        return bool(recording) and all(mode == "both" for mode in recording)

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
            if self._laz_frames_also_in_bag():
                consequence = "The point clouds are still recorded into the bag."
            else:
                consequence = "Point cloud frames are being lost."
            self.error_occurred.emit(f"LAZ writing failed: {msg}. {consequence}")

    @Slot(int)
    def _on_laz_dropped(self, count: int):
        """The LAZ queue was full and a frame was thrown away (writing is too slow)."""
        if self._recording.is_set() and not self._laz_drop_reported:
            self._laz_drop_reported = True  # the total is reported at Stop
            if self._laz_frames_also_in_bag():
                consequence = "The frames are still recorded into the bag."
            else:
                consequence = "These frames are lost: in LAZ mode the lidar is not in the bag."
            self.warning_occurred.emit(
                f"LAZ writing cannot keep up: point cloud frames are being dropped. {consequence}"
            )

    def _destroy_subscriptions(self, node):
        if node is not None:
            for sub in self._laz_subscriptions:
                try:
                    node.destroy_subscription(sub)
                except Exception:
                    pass
        self._laz_subscriptions.clear()

    def _on_bag_warning(self, line: str):
        """The recorder reported a problem (e.g. messages lost to a slow disk).

        This also arrives while Stop waits for the recorder to close the bag.
        """
        if _HIDDEN_NOT_RECORDED in line and not any(map(_is_hidden, self._bag_topics)):
            return  # no hidden topic was asked for; the line is in the log
        if _DISCOVERY_FAILURE in line:
            self._discovery_reason_next = True  # the reason is on the next line
            return
        if self._discovery_reason_next:
            self._discovery_reason_next = False
            if line not in self._discovery_failures:
                self._discovery_failures.append(line)
            if self._recording.is_set():
                self._report_discovery_failure()
            return
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

    def _report_discovery_failure(self):
        """ros2 bag record cannot subscribe to a topic, e.g. its message type is not installed."""
        if self._discovery_failure_reported:
            return
        self._discovery_failure_reported = True  # it tries again several times a second
        self.error_occurred.emit(
            "ros2 bag record cannot subscribe to a selected topic. "
            f"It says: {self._discovery_failures[0]}\n\n"
            "Each failed try also ends its search for the other topics, so selected "
            "topics it has not subscribed to yet may be missing from the bag. Stop, "
            "then deselect that topic or start the GUI with the workspace that defines "
            "its message type sourced, and record again."
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

    def _create_laz_subscription(self, node, topic_name: str, topic_type: str, cb_group) -> bool:
        try:
            msg_class = get_message(topic_type)

            def raw_cb(raw_bytes, topic=topic_name, cls=msg_class):
                self._on_laz_raw(topic, raw_bytes, cls)

            qos = self._laz_qos(node, topic_name)
            sub = node.create_subscription(
                msg_class, topic_name, raw_cb, qos,
                callback_group=cb_group, raw=True,
            )
            self._laz_subscriptions.append(sub)
            logger.info("LAZ subscription to %s: %s", topic_name,
                        "reliable" if qos is LAZ_RELIABLE_QOS else "best effort")
            return True
        except Exception as e:
            logger.error("LAZ subscription failed for %s: %s", topic_name, e)
            return False

    @staticmethod
    def _laz_qos(node, topic_name: str) -> QoSProfile:
        """Reliable when every publisher of the topic is; best effort matches any publisher.

        A lidar that is not up yet gets best effort: it still matches once it appears.
        """
        publishers = node.get_publishers_info_by_topic(topic_name)
        if publishers and all(
                p.qos_profile.reliability == QoSReliabilityPolicy.RELIABLE for p in publishers):
            return LAZ_RELIABLE_QOS
        return SENSOR_QOS

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
                missing = laz.missing_frames()
                topics = {}
                for topic in sorted(set(laz.file_counts) | set(missing)):
                    topics[topic] = {
                        'path': os.path.join('pointcloud', laz.subdir_for(topic), ''),
                        'file_count': laz.file_counts.get(topic, 0),
                    }
                    if topic in missing:
                        topics[topic]['missing_frames_est'] = missing[topic][0]
                self._laz_summary = {
                    'dropped_frames': laz.drop_count,
                    'write_errors': laz.error_count,
                    'topics': topics,
                }
                gaps = [f"{topic}: about {n} of {expected} frames"
                        for topic, (n, expected) in sorted(missing.items()) if n]
                logger.info("LAZ writer stopped: %d files, %d frames dropped, %d errors",
                            laz.file_count, laz.drop_count, laz.error_count)
                if laz.drop_count or laz.error_count or gaps:
                    message = (
                        f"LAZ recording is incomplete: {laz.drop_count} frames dropped, "
                        f"{laz.error_count} write errors, {laz.file_count} files written."
                    )
                    if gaps:
                        # Lost on the way, or dropped from the writer's full queue
                        message += (" Missing between the frames received, going by their "
                                    "time stamps: " + "; ".join(gaps) + ".")
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
            self._driver_stop_failures = self._stop_driver_svo2(node, self._driver_svo)
            for failure in self._driver_stop_failures:
                logger.error(failure)
                self.warning_occurred.emit(failure)
            self._driver_svo = []

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

        self._last_duration_s = (datetime.now() - self._session_start_time).total_seconds()
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
            self._bag_topics,
            lidar_modes=self._effective_modes[0],
            camera_mode=self._effective_modes[1],
            notices=self._notices,
            bag_message_counts=self._bag_counts,
            recorder_warnings=self._bag_warnings,
            recorder_subscription_failures=self._discovery_failures,
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
    def last_duration_s(self) -> float:
        """How long the last recording ran, for judging the rates it recorded."""
        return self._last_duration_s

    @property
    def last_bag_topics(self) -> List[str]:
        """The topics the last recording asked the bag to hold."""
        return list(self._bag_topics)

