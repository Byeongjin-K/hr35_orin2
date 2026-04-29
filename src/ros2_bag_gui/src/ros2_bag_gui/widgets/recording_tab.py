"""Recording tab widget that composes all recording-related widgets."""
import os
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
from ros2_bag_gui.ros2.recorder import Recorder, RecordingConfig
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
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile_manager = ProfileManager()
        self._topics: List[Dict] = []
        self._setup_ui()
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
        self.status_panel.disk_critical.connect(self._on_disk_critical)
    
    def _setup_ros2(self):
        self._ros2_thread = ROS2Thread(self)
        self._ros2_thread.connection_status_changed.connect(self._on_connection_changed)
        self._ros2_thread.hz_updated.connect(self.topic_list.update_hz)
        
        self._discovery = TopicDiscoveryManager(self._ros2_thread, self)
        self._discovery.topics_discovered.connect(self._on_topics_discovered)
        self._discovery.error.connect(self._on_discovery_error)
        
        self._recorder = Recorder(self)
        self._recorder.recording_started.connect(self._on_recorder_started)
        self._recorder.recording_stopped.connect(self._on_recorder_stopped)
        self._recorder.message_recorded.connect(self._on_message_recorded)
        self._recorder.error_occurred.connect(self._on_recorder_error)
        
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
    
    def _on_topics_discovered(self, topics: List[Dict]):
        self._topics = topics
        self.set_topics(topics)
        count = len(topics)
        self.connection_label.setText(f"✅ ROS2 Connected ({count} topics)")
        logger.info(f"Discovered {count} topics")
    
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
    
    def _on_message_recorded(self, topic_name: str, count: int):
        pass
    
    def _update_recording_stats(self):
        if not self._recorder.is_recording:
            return

        counts = self._recorder.topic_counts
        hz_map = self._recorder.get_topic_hz()
        stats = {}
        for topic_name, msg_count in counts.items():
            stats[topic_name] = {'count': msg_count, 'hz': hz_map.get(topic_name, 0.0)}
        self.status_panel.update_topic_stats(stats)
        self.topic_list.update_hz(hz_map)

        session_path = self._recorder.session_path
        if session_path:
            rosbag_dir = os.path.join(session_path, 'rosbag')
            pc_dir = os.path.join(session_path, 'pointcloud')

            rosbag_bytes = self._dir_size(rosbag_dir)
            pc_bytes = self._dir_size(pc_dir)
            self.status_panel.update_storage_sizes(rosbag_bytes, pc_bytes, 0)
    
    def _dir_size(self, path: str) -> int:
        total = 0
        if os.path.isdir(path):
            for entry in os.scandir(path):
                if entry.is_file():
                    total += entry.stat().st_size
        return total
    
    def _on_recorder_error(self, error_msg: str):
        logger.error("Recording error: %s", error_msg)
        QMessageBox.critical(self, "Recording Error", error_msg)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_panel.set_state(RecordingState.STOPPED)
    
    def cleanup(self):
        if self._recorder.is_recording:
            node = self._ros2_thread.node
            if node is not None:
                self._recorder.stop_recording(node)
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
    
    def _on_disk_critical(self):
        """Handle critical disk space warning."""
        QMessageBox.warning(
            self,
            "Disk Space Critical",
            "Disk space is critically low! Recording may fail or stop automatically."
        )
    
    def _on_start_clicked(self):
        """Handle start recording button click."""
        settings = self.settings_panel.get_settings()
        selected_topic_names = self.topic_list.get_selected_topics()
        
        if not selected_topic_names:
            QMessageBox.warning(
                self,
                "No Topics Selected",
                "Please select at least one topic to record."
            )
            return
        
        if not settings.output_path:
            QMessageBox.warning(
                self,
                "No Output Path",
                "Please select an output path in the settings panel."
            )
            return
        
        topic_type_map = {t['name']: t['type'] for t in self._topics}
        topics_with_types = [
            {'name': name, 'type': topic_type_map.get(name, 'unknown')}
            for name in selected_topic_names
        ]
        
        split_bytes = int(settings.split_size_gb * 1024**3) if settings.split_mode == "size" else 0
        
        recording_config = RecordingConfig(
            topics=topics_with_types,
            output_path=settings.output_path,
            session_name=settings.session_name,
            max_bagfile_size=split_bytes,
            lidar_mode=settings.lidar_mode,
            camera_mode=settings.camera_mode,
        )
        
        node = self._ros2_thread.node
        if node is None:
            QMessageBox.warning(self, "ROS2 Not Ready", "ROS2 node is not connected yet.")
            return
        
        success = self._recorder.start_recording(recording_config, node)
        if not success:
            return
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_panel.set_state(RecordingState.RECORDING)
        self.status_panel.set_target_path(settings.output_path)
        
        config = {
            'topics': selected_topic_names,
            'output_path': settings.output_path,
            'session_name': settings.session_name,
            'lidar_mode': settings.lidar_mode,
            'camera_mode': settings.camera_mode,
        }
        self.recording_start_requested.emit(config)
    
    def _on_stop_clicked(self):
        """Handle stop recording button click."""
        node = self._ros2_thread.node
        if node is not None:
            session_folder = self._recorder.stop_recording(node)
            if session_folder:
                logger.info("Recording saved to: %s", session_folder)
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
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
        selected_topics = self.topic_list.get_selected_topics()
        
        profile = RecordingProfile(
            name=name,
            selected_topics=selected_topics,
            save_path=settings.output_path,
            session_name_template=settings.session_name,
            max_bag_size_gb=settings.split_size_gb,
            lidar_mode=settings.lidar_mode,
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
            
            for i in range(self.topic_list.tree.topLevelItemCount()):
                item = self.topic_list.tree.topLevelItem(i)
                self._uncheck_item_recursive(item)
            
            self._check_topics(profile.selected_topics)
            
            self.settings_panel.path_edit.setText(profile.save_path)
            self.settings_panel.session_name_edit.setText(profile.session_name_template)
            self.settings_panel.split_size_spin.setValue(profile.max_bag_size_gb)
            # Load LiDAR mode
            lidar_mode_map = {"bag": 0, "laz": 1, "both": 2}
            self.settings_panel.lidar_mode_combo.setCurrentIndex(lidar_mode_map.get(profile.lidar_mode, 0))
            # Load Camera mode
            camera_mode_map = {"bag": 0, "svo2": 1, "both": 2}
            self.settings_panel.camera_mode_combo.setCurrentIndex(camera_mode_map.get(profile.camera_mode, 0))
            
            self.settings_panel._on_settings_changed()
            
            QMessageBox.information(
                self,
                "Profile Loaded",
                f"Profile '{profile_name}' loaded successfully."
            )
            
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
    
    def _uncheck_item_recursive(self, item):
        """Recursively uncheck an item and its children."""
        item.setCheckState(0, Qt.CheckState.Unchecked)
        for i in range(item.childCount()):
            self._uncheck_item_recursive(item.child(i))
    
    def _check_topics(self, topic_names: List[str]):
        """Check topics by name in the topic list."""
        def check_item_recursive(item):
            if item.childCount() == 0:
                topic_name = item.data(0, Qt.ItemDataRole.UserRole)
                if topic_name in topic_names:
                    item.setCheckState(0, Qt.CheckState.Checked)
            else:
                for i in range(item.childCount()):
                    check_item_recursive(item.child(i))
        
        for i in range(self.topic_list.tree.topLevelItemCount()):
            check_item_recursive(self.topic_list.tree.topLevelItem(i))
    
    def set_topics(self, topics: List[Dict]):
        """
        Set the list of available topics.
        
        Args:
            topics: List of dicts with 'name', 'type', 'hz', 'category'
        """
        self.topic_list.set_topics(topics)
    
    def reset(self):
        """Reset the recording tab to initial state."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_panel.reset()
