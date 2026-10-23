"""Recording tab widget that composes all recording-related widgets."""
import glob
import os
import shutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QInputDialog, QMessageBox, QSplitter, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QTimer
from typing import Dict, List, Optional

from ros2_bag_gui.widgets.topic_list import TopicListWidget
from ros2_bag_gui.widgets.recording_status import RecordingStatusPanel, RecordingState
from ros2_bag_gui.widgets.settings_panel import SettingsPanel
from ros2_bag_gui.config.profiles import ProfileManager, RecordingProfile
from ros2_bag_gui.ros2.ros2_thread import ROS2Thread
from ros2_bag_gui.ros2.topic_discovery import TopicDiscoveryManager
from ros2_bag_gui.ros2.recorder import (
    Recorder, RecordingConfig, should_include_in_rosbag, should_record_lidar_laz, unloadable_types,
)
from ros2_bag_gui.ros2.topic_notes import StartPlan, gb_per_hour, start_report
from ros2_bag_gui.widgets.start_check import confirm_start
from ros2_bag_gui.ros2.sensor_topics import BAG_IMAGE_MODES, CAMERAS, sensor_of, switch_topics
from ros2_bag_gui.ros2.bag_process import find_other_recorders
from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)


class RecordingTab(QWidget):
    """
    Recording tab that integrates all recording widgets.
    
    Layout:
    - Left panel (60%): TopicListWidget + Profile controls
    - Right panel (40%): SettingsPanel + RecordingStatusPanel + Start/Stop buttons
    """
    
    # Signals for MainWindow to connect
    recording_start_requested = Signal(object)  # Emits recording config dict
    recording_stop_requested = Signal()
    recording_active_changed = Signal(bool)  # True while a recording is running

    # Below this share of the rate measured before Start, a topic is reported as slow
    SLOW_TOPIC_SHARE = 0.6
    SLOW_TOPIC_MIN_HZ = 1.0  # rates below this are too uneven to judge
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile_manager = ProfileManager()
        self._topics: List[Dict] = []
        self._measured_hz: Dict[str, float] = {}
        self._measured_gb_per_hour: Dict[str, float] = {}  # kept like the rates, for the Start question
        self._seen_topics: set[str] = set()  # a sensor switch ticks a topic the first time it shows up
        self._setup_ui()
        self._camera_mode = self.settings_panel.get_settings().camera_mode
        self._connect_signals()
        self._load_profile_list()
        self._setup_ros2()
        self._setup_auto_refresh()
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_recording_stats)
    
    def _setup_ui(self):
        """Setup the UI layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Main splitter for left/right panels
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # --- LEFT PANEL (60%) ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        topic_header_layout = QHBoxLayout()
        self.connection_label = QLabel("⏳ Connecting to ROS2...")
        topic_header_layout.addWidget(self.connection_label)
        topic_header_layout.addStretch()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.clicked.connect(self._on_refresh_topics)
        topic_header_layout.addWidget(self.refresh_btn)
        left_layout.addLayout(topic_header_layout)
        
        # Topic list widget
        self.topic_list = TopicListWidget()
        left_layout.addWidget(self.topic_list)
        
        # Profile controls
        profile_group = QGroupBox("Recording Profiles")
        profile_layout = QVBoxLayout(profile_group)
        
        # Profile selector
        profile_select_layout = QHBoxLayout()
        profile_select_layout.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        profile_select_layout.addWidget(self.profile_combo, 1)
        profile_layout.addLayout(profile_select_layout)
        
        # Profile buttons
        profile_btn_layout = QHBoxLayout()
        self.save_profile_btn = QPushButton("Save Profile")
        self.load_profile_btn = QPushButton("Load Profile")
        self.delete_profile_btn = QPushButton("Delete Profile")
        
        self.save_profile_btn.clicked.connect(self._on_save_profile)
        self.load_profile_btn.clicked.connect(self._on_load_profile)
        self.delete_profile_btn.clicked.connect(self._on_delete_profile)
        
        profile_btn_layout.addWidget(self.save_profile_btn)
        profile_btn_layout.addWidget(self.load_profile_btn)
        profile_btn_layout.addWidget(self.delete_profile_btn)
        profile_layout.addLayout(profile_btn_layout)
        
        left_layout.addWidget(profile_group)
        
        # --- RIGHT PANEL (40%) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        
        # Settings panel
        self.settings_panel = SettingsPanel()
        right_layout.addWidget(self.settings_panel)
        
        # Recording status panel
        self.status_panel = RecordingStatusPanel()
        right_layout.addWidget(self.status_panel)
        
        # Start/Stop buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start Recording")
        self.stop_btn = QPushButton("■ Stop Recording")
        
        self.start_btn.setMinimumHeight(32)
        self.stop_btn.setMinimumHeight(32)
        
        self.start_btn.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.stop_btn.setStyleSheet("font-size: 12px; font-weight: bold;")
        
        self.start_btn.clicked.connect(self._on_start_clicked)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        
        self.stop_btn.setEnabled(False)
        
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.stop_btn)
        right_layout.addLayout(button_layout)
        
        # Add panels to splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        
        # Set initial sizes (60/40 split)
        splitter.setStretchFactor(0, 60)
        splitter.setStretchFactor(1, 40)
        
        layout.addWidget(splitter)
    
    def _connect_signals(self):
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.sensor_toggled.connect(self._on_sensor_toggled)
        # Queued: these come out of the status panel's one-second timer, and a
        # timer does not fire again while its own slot is inside a dialog. Shown
        # directly, the low-space warning would switch off the automatic stop
        # for as long as it stays open.
        self.status_panel.disk_critical.connect(
            self._on_disk_critical, Qt.ConnectionType.QueuedConnection)
        self.status_panel.disk_full.connect(
            self._on_disk_full, Qt.ConnectionType.QueuedConnection)
    
    def _setup_ros2(self):
        self._ros2_thread = ROS2Thread(self)
        self._ros2_thread.connection_status_changed.connect(self._on_connection_changed)
        self._ros2_thread.hz_updated.connect(self.topic_list.update_hz)
        self._ros2_thread.hz_updated.connect(self._on_hz_updated)
        self._ros2_thread.rate_updated.connect(self._on_rates_updated)
        # Rates are measured for the ticked topics only, not for every topic.
        self.topic_list.selection_changed.connect(self._on_topic_selection_changed)
        
        self._discovery = TopicDiscoveryManager(self._ros2_thread, self)
        self._discovery.topics_discovered.connect(self._on_topics_discovered)
        self._discovery.error.connect(self._on_discovery_error)
        
        self._recorder = Recorder(self)
        self._recorder.recording_started.connect(self._on_recorder_started)
        self._recorder.recording_stopped.connect(self._on_recorder_stopped)
        self._recorder.message_recorded.connect(self._on_message_recorded)
        self._recorder.error_occurred.connect(self._on_recorder_error)
        # Queued: raised from inside Start, shown once the screen says Recording.
        self._recorder.warning_occurred.connect(
            self._on_recorder_warning, Qt.ConnectionType.QueuedConnection
        )
        
        self._ros2_thread.start()
    
    def _setup_auto_refresh(self):
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_topics)
        self._refresh_timer.setInterval(5000)
    
    def _on_connection_changed(self, connected: bool):
        if connected:
            self.connection_label.setText("✅ ROS2 Connected")
            self.refresh_btn.setEnabled(True)
            self._refresh_timer.start()
            self._discovery.discover_topics()
            logger.info("ROS2 connected, starting topic discovery")
        else:
            self.connection_label.setText("❌ ROS2 Disconnected")
            self.refresh_btn.setEnabled(False)
            self._refresh_timer.stop()
            logger.warning("ROS2 disconnected")
            if self._recorder.is_recording:
                # The bag is written by its own process and goes on. What ran
                # on this node does not: live counts and LAZ recording.
                self._on_recorder_warning(
                    "The GUI lost its ROS2 connection while recording. The bag goes on, "
                    "but the live counts have stopped and LAZ point clouds are no longer "
                    "written. Stop, restart the GUI and start a new recording."
                )
    
    def _on_hz_updated(self, hz_map: Dict[str, float]):
        """Keep the rates measured before Start: at Stop they say what the bag should hold."""
        self._measured_hz.update({t: hz for t, hz in hz_map.items() if hz > 0})

    def _on_rates_updated(self, bytes_per_second: Dict[str, float]):
        self.topic_list.update_rates(bytes_per_second)
        self._measured_gb_per_hour.update(
            {t: gb_per_hour(rate) for t, rate in bytes_per_second.items() if rate > 0})

    def _confirm_size(self, topic_names: List[str], camera_mode: str, free_bytes: int) -> bool:
        """Ask before a recording that fills the disk fast or records the same data twice."""
        lidar_modes = self.settings_panel.lidar_modes()
        bag = tuple(n for n in topic_names if should_include_in_rosbag(n, lidar_modes, camera_mode))
        laz = [n for n in topic_names if should_record_lidar_laz(n, lidar_modes)]
        cameras = sum(self.settings_panel.camera_switches().values()) if camera_mode in ("svo2", "both") else 0
        plan = StartPlan(bag_topics=bag, laz_and_bag=tuple(n for n in laz if n in bag),
                         laz_lidars=len(laz), svo2_cameras=cameras)
        report = start_report(plan, self._measured_gb_per_hour, free_bytes)
        return not report.worth_asking or confirm_start(self, report)

    def _on_topic_selection_changed(self, _available: List[str]):
        # Selected topics that are not up yet are included: measured once they appear.
        self._ros2_thread.set_hz_topics(self.topic_list.get_selected_topics(include_missing=True))

    def _on_topics_discovered(self, topics: List[Dict]):
        self.set_topics(topics)
        self._tick_new_sensor_topics(topics)
        count = len(topics)
        self.connection_label.setText(f"✅ ROS2 Connected ({count} topics)")
        logger.info(f"Discovered {count} topics")
    
    def _selection(self) -> set[str]:
        return set(self.topic_list.get_selected_topics(include_missing=True))

    def _topic_types(self, topics: List[Dict]) -> List[tuple[str, str]]:
        return [(t['name'], t['type']) for t in topics]

    def _on_sensor_toggled(self, sensor: str, on: bool):
        """Switched on, a sensor ticks its topics; switched off, every topic of it is unticked."""
        if on:
            ticked = self._selection() | switch_topics(
                sensor, self._topic_types(self._topics), self._camera_mode)
        else:
            ticked = {name for name in self._selection() if sensor_of(name) != sensor}
        self.topic_list.set_selected_topics(sorted(ticked))

    def _tick_new_sensor_topics(self, topics: List[Dict]):
        """A topic seen for the first time is ticked when its sensor is switched on."""
        new = self._topic_types([t for t in topics if t['name'] not in self._seen_topics])
        self._seen_topics.update(name for name, _type in new)
        ticked = set()
        for sensor, on in self.settings_panel.sensor_switches().items():
            if on:
                ticked |= switch_topics(sensor, new, self._camera_mode)
        if ticked:
            self.topic_list.set_selected_topics(sorted(self._selection() | ticked))

    def _tick_camera_images(self):
        """Camera images go into the bag in some camera modes only: follow the mode."""
        pairs = self._topic_types(self._topics)
        ticked = self._selection()
        for sensor, on in self.settings_panel.sensor_switches().items():
            if sensor in CAMERAS and on:
                images = switch_topics(sensor, pairs, 'bag') - switch_topics(sensor, pairs, 'svo2')
                ticked = ticked | images if self._camera_mode in BAG_IMAGE_MODES else ticked - images
        self.topic_list.set_selected_topics(sorted(ticked))

    def _on_discovery_error(self, msg: str):
        self.connection_label.setText(f"⚠️ {msg}")
        logger.warning(f"Topic discovery error: {msg}")
    
    def _on_refresh_topics(self):
        if self._ros2_thread.is_connected:
            self._discovery.discover_topics()
    
    def _on_recorder_started(self):
        logger.info("Recorder started successfully")
        self._ros2_thread.set_hz_active(False)
        self._stats_timer.start(1000)
    
    def _on_recorder_stopped(self):
        logger.info("Recorder stopped")
        self._stats_timer.stop()
        self._ros2_thread.set_hz_active(True)
        self._show_bag_counts()

    def _show_bag_counts(self):
        """Show what the finished bag really holds, per topic."""
        if not self._recorder.last_bag_topics:
            return  # SVO2 only: there is no bag
        bag_counts = self._recorder.last_bag_counts
        self.status_panel.show_bag_counts(bag_counts, self._recorder.last_bag_topics)
        if bag_counts is None:
            self.status_panel.add_notice(
                "The bag has no metadata.yaml, so its message counts are unknown. "
                "Run: ros2 bag reindex -s sqlite3 <session>/rosbag"
            )
            return
        empty = [t for t in self._recorder.last_bag_topics if not bag_counts.get(t)]
        if empty:
            self.status_panel.add_notice(
                "No messages in the bag for: " + ", ".join(sorted(empty))
            )
        slow = self._topics_slower_than_measured(bag_counts)
        if slow:
            self.status_panel.add_notice(
                "Recorded slower than measured before Start (data was lost on the way): "
                + ", ".join(slow)
            )

    def _topics_slower_than_measured(self, bag_counts: Dict[str, int]) -> List[str]:
        """Topics the bag holds far fewer messages of than their measured rate implies.

        Too many subscribers can make a driver (the ZED camera above all) publish
        slower than it did before Start, and nothing else would say so.
        """
        duration = self._recorder.last_duration_s
        if duration < 5:  # too short to tell a rate from
            return []
        slow = []
        for topic, count in sorted(bag_counts.items()):
            measured = self._measured_hz.get(topic, 0.0)
            if not count or measured < self.SLOW_TOPIC_MIN_HZ:
                continue
            recorded = count / duration
            if recorded < self.SLOW_TOPIC_SHARE * measured:
                slow.append(f"{topic} {recorded:.1f}Hz of {measured:.1f}Hz")
        return slow
    
    def _on_message_recorded(self, topic_name: str, count: int):
        pass
    
    def _update_recording_stats(self):
        if not self._recorder.is_recording:
            return

        self._recorder.check_health()

        session_path = self._recorder.session_path
        if session_path:
            rosbag_dir = os.path.join(session_path, 'rosbag')
            pc_dir = os.path.join(session_path, 'pointcloud')

            rosbag_bytes = self._dir_size(rosbag_dir)
            pc_bytes = self._dir_size(pc_dir)
            svo2_bytes = sum(os.path.getsize(p) for p in glob.glob(os.path.join(session_path, '*.svo2')))
            self.status_panel.update_storage_sizes(rosbag_bytes, pc_bytes, svo2_bytes)
    
    def _dir_size(self, path: str) -> int:
        total = 0
        if os.path.isdir(path):
            for entry in os.scandir(path):
                if entry.is_file():
                    total += entry.stat().st_size
        return total
    
    def _on_recorder_error(self, error_msg: str):
        logger.error("Recording error: %s", error_msg)
        if not self._recorder.is_recording:
            # Put the screen right before the dialog, so what is behind it is true.
            self._stats_timer.stop()
            self._set_controls(recording=False)
            self.status_panel.set_state(RecordingState.ERROR)
        QMessageBox.critical(self, "Recording Error", error_msg)
    
    def _on_recorder_warning(self, message: str):
        """Recording goes on, but not the way it was asked for."""
        logger.warning("Recording warning: %s", message)
        self.status_panel.add_notice(message)
        QMessageBox.warning(self, "Recording Warning", message)

    def _set_controls(self, recording: bool):
        """Start/Stop buttons, and whoever mirrors them (the menu), follow one state."""
        self.start_btn.setEnabled(not recording)
        self.stop_btn.setEnabled(recording)
        self.recording_active_changed.emit(recording)

    def cleanup(self):
        if self._recorder.is_recording:
            self._recorder.stop_recording(self._ros2_thread.node)
            failures = self._recorder.driver_stop_failures
            if failures:
                # Shown now: the GUI is closing, a queued warning would never appear.
                QMessageBox.critical(self, "ZED Driver Still Recording", "\n\n".join(failures))
        self._stats_timer.stop()
        self._refresh_timer.stop()
        self._ros2_thread.stop()
        try:
            self._recorder.recording_started.disconnect()
            self._recorder.recording_stopped.disconnect()
            self._recorder.message_recorded.disconnect()
            self._recorder.error_occurred.disconnect()
        except RuntimeError:
            pass
    
    def _on_settings_changed(self):
        """Handle settings changes."""
        settings = self.settings_panel.get_settings()
        self.status_panel.set_target_path(settings.output_path)
        if settings.camera_mode != self._camera_mode:
            self._camera_mode = settings.camera_mode
            self._tick_camera_images()
    
    def _on_disk_critical(self):
        """Handle critical disk space warning (raised once per fall below the limit)."""
        QMessageBox.warning(
            self,
            "Disk Space Critical",
            f"Less than {self.status_panel.DISK_CRITICAL_GB} GB free on the output disk. "
            f"A running recording is stopped automatically below "
            f"{self.status_panel.DISK_STOP_GB} GB."
        )

    def _on_disk_full(self):
        """Stop while the recorder can still close its bag; a full disk leaves it unreadable."""
        if not self._recorder.is_recording:
            return
        reason = (
            "Recording was stopped automatically: less than "
            f"{self.status_panel.DISK_STOP_GB} GB free on the output disk."
        )
        self._stop_recording(reason)
        self.status_panel.add_notice(reason)
        QMessageBox.critical(self, "Recording Stopped", reason)
    
    def _on_start_clicked(self):
        """Handle start recording button click."""
        if self._recorder.is_recording:
            return

        settings = self.settings_panel.get_settings()
        selected_topic_names = self.topic_list.get_selected_topics()
        missing_topic_names = self.topic_list.get_missing_selected()
        
        svo2_wanted = (settings.camera_mode in ("svo2", "both")  # cameras need no topic
                       and any(self.settings_panel.camera_switches().values()))
        if not selected_topic_names and not missing_topic_names and not svo2_wanted:
            QMessageBox.warning(
                self,
                "No Topics Selected",
                "Please select at least one topic to record, or set the camera mode to SVO2."
            )
            return
        
        if not settings.output_path:
            QMessageBox.warning(
                self,
                "No Output Path",
                "Please select an output path in the settings panel."
            )
            return

        try:
            os.makedirs(settings.output_path, exist_ok=True)
            free_bytes = shutil.disk_usage(settings.output_path).free
            free_gb = free_bytes / 1024**3
        except OSError as e:
            QMessageBox.critical(
                self, "Output Path Not Usable",
                f"Cannot write to {settings.output_path}:\n{e}"
            )
            return
        if not os.access(settings.output_path, os.W_OK):
            QMessageBox.critical(
                self, "Output Path Not Usable",
                f"No write permission for {settings.output_path}."
            )
            return
        if self.status_panel.DISK_STOP_GB <= free_gb < self.status_panel.DISK_CRITICAL_GB:
            reply = QMessageBox.question(
                self,
                "Disk Space Critical",
                f"Only {free_gb:.1f} GB free in {settings.output_path}. The recording "
                f"will be stopped automatically below {self.status_panel.DISK_STOP_GB} GB."
                "\n\nStart anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if missing_topic_names:
            reply = QMessageBox.question(
                self,
                "Selected Topics Not Available",
                f"{len(missing_topic_names)} selected topic(s) are not available right now:\n\n"
                + "\n".join(missing_topic_names)
                + "\n\nStart anyway? They are recorded only from the moment they appear.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            # The recorder subscribes to a named topic when it shows up later.
            selected_topic_names = selected_topic_names + missing_topic_names
        
        topic_type_map = {t['name']: t['type'] for t in self._topics}
        topics_with_types = [
            {'name': name, 'type': topic_type_map.get(name, 'unknown')}
            for name in selected_topic_names
        ]

        unloadable = unloadable_types(topics_with_types)
        if unloadable:
            packages = sorted({type_name.split('/')[0] for type_name in unloadable.values()})
            reply = QMessageBox.question(
                self,
                "Message Types Not Installed",
                f"The message type of {len(unloadable)} selected topic(s) is not installed "
                "here, so ros2 bag record cannot record them:\n\n"
                + "\n".join(f"{name}  [{type_name}]" for name, type_name in sorted(unloadable.items()))
                + "\n\nLeft selected, they also keep it from subscribing to other topics. "
                "To record them, source the workspace that defines these types "
                f"({', '.join(packages)}) before starting the GUI."
                "\n\nStart without these topics?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            logger.warning("Recording without topics whose message type is not installed: %s",
                           ", ".join(sorted(unloadable)))
            topics_with_types = [t for t in topics_with_types if t['name'] not in unloadable]
            selected_topic_names = [n for n in selected_topic_names if n not in unloadable]
        
        if not self._confirm_size(selected_topic_names, settings.camera_mode, free_bytes):
            return

        split_bytes = int(settings.split_size_gb * 1024**3) if settings.split_mode == "size" else 0
        split_seconds = settings.split_time_minutes * 60 if settings.split_mode == "time" else 0
        
        recording_config = RecordingConfig(
            topics=topics_with_types,
            output_path=settings.output_path,
            session_name=settings.session_name,
            max_bagfile_size=split_bytes,
            max_bag_duration=split_seconds,
            lidar_modes=self.settings_panel.lidar_modes(),
            camera_mode=settings.camera_mode,
            svo2_camera_serial=settings.svo2_camera_serial,
            cameras=self.settings_panel.camera_switches(),
        )
        
        node = self._ros2_thread.node
        if node is None:
            QMessageBox.warning(self, "ROS2 Not Ready", "ROS2 node is not connected yet.")
            return

        stray = find_other_recorders()
        if stray:
            reply = QMessageBox.question(
                self,
                "Another Recorder Is Running",
                "ros2 bag record is already running on this machine (pid "
                + ", ".join(str(pid) for pid in stray)
                + "). It may be left over from a GUI that was killed and is still "
                "writing to disk.\n\nTo stop it: pkill -INT -f \"ros2 bag record\""
                "\n\nStart a second recording anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        self.status_panel.clear_notices()
        success = self._recorder.start_recording(recording_config, node)
        if not success and self._recorder.busy_svo_drivers:
            success = self._stop_busy_svo_drivers_and_start(recording_config, node)
        if not success:
            return
        
        self._set_controls(recording=True)
        self.status_panel.set_state(RecordingState.RECORDING)
        self.status_panel.show_recording_topics(self._recorder.last_bag_topics)
        # Rates are not measured while recording: do not leave the last ones looking live.
        measured = self.topic_list.get_selected_topics(include_missing=True)
        self.topic_list.update_hz({name: 0.0 for name in measured})
        self.topic_list.update_rates({name: 0.0 for name in measured})
        if missing_topic_names:
            self.status_panel.add_notice(
                "Not available at Start (recorded only once they appear): "
                + ", ".join(missing_topic_names)
            )
        if unloadable:
            self.status_panel.add_notice(
                "Not recorded, message type not installed: " + ", ".join(sorted(unloadable))
            )
        self.status_panel.set_target_path(settings.output_path)
        
        config = {
            'topics': selected_topic_names,
            'output_path': settings.output_path,
            'session_name': settings.session_name,
            'lidar_modes': self.settings_panel.lidar_modes(),
            'camera_mode': settings.camera_mode,
        }
        self.recording_start_requested.emit(config)
    
    def _stop_busy_svo_drivers_and_start(self, config, node) -> bool:
        """A ZED driver already records an SVO2 that this GUI did not start: ask."""
        busy = self._recorder.busy_svo_drivers
        reply = QMessageBox.question(
            self,
            "ZED Driver Already Recording",
            "These ZED drivers are already recording an SVO2 file:\n\n" + "\n".join(busy)
            + "\n\nIt may be left over from a GUI that was closed abnormally, or another "
            "program may have started it. Stop that recording and start?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False
        failures = self._recorder.stop_driver_svo2(busy, node)
        if failures:
            QMessageBox.critical(self, "Recording Error", "\n\n".join(failures))
            return False
        return self._recorder.start_recording(config, node)

    def _on_stop_clicked(self):
        """Handle stop recording button click."""
        self._stop_recording()

    def _stop_recording(self, forced_reason: Optional[str] = None):
        if not self._recorder.is_recording:
            return

        # The recorder keeps the node it started with, so Stop works even if
        # the ROS2 thread has gone away in the meantime.
        session_folder = self._recorder.stop_recording(self._ros2_thread.node, forced_reason)
        if session_folder:
            logger.info("Recording saved to: %s", session_folder)

        self._set_controls(recording=False)
        if self.status_panel.state != RecordingState.ERROR:
            self.status_panel.set_state(RecordingState.STOPPED)
        
        self.recording_stop_requested.emit()
    
    def _on_save_profile(self):
        """Save current configuration as a profile."""
        name, ok = QInputDialog.getText(
            self,
            "Save Profile",
            "Enter profile name:"
        )
        
        if not ok or not name.strip():
            return
        
        name = name.strip()
        
        if self.profile_manager.profile_exists(name):
            reply = QMessageBox.question(
                self,
                "Profile Exists",
                f"Profile '{name}' already exists. Overwrite?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        
        settings = self.settings_panel.get_settings()
        selected_topics = self.topic_list.get_selected_topics(include_missing=True)
        
        profile = RecordingProfile(
            name=name,
            selected_topics=selected_topics,
            save_path=settings.output_path,
            session_name_template=settings.session_name,
            max_bag_size_gb=settings.split_size_gb,
            lidar_boom_mode=settings.lidar_boom_mode,
            lidar_cabin_mode=settings.lidar_cabin_mode,
            camera_mode=settings.camera_mode,
        )
        
        self.profile_manager.save_profile(profile)
        self._load_profile_list()
        
        index = self.profile_combo.findText(name)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
        
        QMessageBox.information(
            self,
            "Profile Saved",
            f"Profile '{name}' saved successfully."
        )
    
    def _on_load_profile(self):
        """Load selected profile."""
        profile_name = self.profile_combo.currentText()
        
        if not profile_name:
            QMessageBox.warning(
                self,
                "No Profile Selected",
                "Please select a profile to load."
            )
            return
        
        try:
            profile = self.profile_manager.load_profile(profile_name)
            
            # Topics of the profile that are not up yet stay selected.
            self.topic_list.set_selected_topics(profile.selected_topics)
            missing_topics = self.topic_list.get_missing_selected()
            
            self.settings_panel.path_edit.setText(profile.save_path)
            self.settings_panel.session_name_edit.setText(profile.session_name_template)
            self.settings_panel.split_size_spin.setValue(profile.max_bag_size_gb)
            self.settings_panel.set_lidar_modes(
                profile.lidar_boom_mode, profile.lidar_cabin_mode)
            # Load Camera mode
            camera_mode_ok = self.settings_panel.set_camera_mode(profile.camera_mode)
            
            self.settings_panel._on_settings_changed()
            
            message = f"Profile '{profile_name}' loaded successfully."
            if missing_topics:
                message += (
                    f"\n\n{len(missing_topics)} topic(s) of the profile are not available right now:\n"
                    + "\n".join(missing_topics)
                    + "\n\nThey stay selected and are ticked as soon as they appear."
                )
            if not camera_mode_ok:
                message += (
                    f"\n\nThe profile asks for camera mode '{profile.camera_mode}', "
                    "but the ZED SDK is not installed here. "
                    "Camera images will be recorded into the bag."
                )
            QMessageBox.information(self, "Profile Loaded", message)
            
        except FileNotFoundError:
            QMessageBox.warning(
                self,
                "Profile Not Found",
                f"Profile '{profile_name}' not found."
            )
    
    def _on_delete_profile(self):
        """Delete selected profile."""
        profile_name = self.profile_combo.currentText()
        
        if not profile_name:
            QMessageBox.warning(
                self,
                "No Profile Selected",
                "Please select a profile to delete."
            )
            return
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Are you sure you want to delete profile '{profile_name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        if self.profile_manager.delete_profile(profile_name):
            self._load_profile_list()
            QMessageBox.information(
                self,
                "Profile Deleted",
                f"Profile '{profile_name}' deleted successfully."
            )
        else:
            QMessageBox.warning(
                self,
                "Delete Failed",
                f"Failed to delete profile '{profile_name}'."
            )
    
    def _load_profile_list(self):
        """Load profile list into combo box."""
        current_text = self.profile_combo.currentText()
        self.profile_combo.clear()
        
        profiles = self.profile_manager.list_profiles()
        self.profile_combo.addItems(profiles)
        
        if current_text:
            index = self.profile_combo.findText(current_text)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
    
    def set_topics(self, topics: List[Dict]):
        """
        Set the list of available topics.
        
        Args:
            topics: List of dicts with 'name', 'type', 'hz', 'category'
        """
        self._topics = topics
        self.topic_list.set_topics(topics)
    
    def reset(self):
        """Reset the recording tab to initial state."""
        self._set_controls(recording=False)
        self.status_panel.reset()
