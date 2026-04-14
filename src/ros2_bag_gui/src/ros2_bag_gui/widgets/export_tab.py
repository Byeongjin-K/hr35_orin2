"""Export tab widget for exporting ROS2 bag data."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from typing import Optional, List
import os

from ros2_bag_gui.export.bag_loader import BagLoader, BagSessionInfo, TopicInfo
from ros2_bag_gui.export.csv_exporter import CSVExportConfig
from ros2_bag_gui.export.laz_exporter import LAZExportConfig, LAZFromBagConfig
from ros2_bag_gui.export.image_exporter import ImageExportConfig, ImageExporter, ImageSource
from ros2_bag_gui.export.sync_generator import SyncGenerator, SyncGeneratorConfig
from ros2_bag_gui.widgets.time_range import TimeRangeSelector
from ros2_bag_gui.widgets.export_progress import ExportProgressDialog, ExportTask


class ExportTab(QWidget):
    """Export tab widget for exporting ROS2 bag data."""
    
    export_completed = Signal(bool, str)  # success, summary
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._session: Optional[BagSessionInfo] = None
        self._pending_sync = False
        self._setup_ui()
        self._connect_signals()
        self._update_export_state()
    
    def _setup_ui(self):
        """Setup the UI layout."""
        layout = QVBoxLayout(self)
        
        # Session Loader Section
        session_group = QGroupBox("Session Loader")
        session_layout = QVBoxLayout(session_group)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Session Path:"))
        self.session_path_edit = QLineEdit()
        self.session_path_edit.setPlaceholderText("Select a recording session folder...")
        path_layout.addWidget(self.session_path_edit)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse_session)
        path_layout.addWidget(self.browse_btn)
        
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self._on_load_session)
        path_layout.addWidget(self.load_btn)
        
        session_layout.addLayout(path_layout)
        
        self.session_status_label = QLabel("Status: No session loaded")
        session_layout.addWidget(self.session_status_label)
        
        layout.addWidget(session_group)
        
        # Time Range Selector
        self.time_range_selector = TimeRangeSelector()
        self.time_range_selector.setEnabled(False)
        layout.addWidget(self.time_range_selector)
        
        # Export Options and Output Settings (side by side)
        options_layout = QHBoxLayout()
        
        # Left: Export Options (60%)
        export_options_group = QGroupBox("Export Options")
        export_options_layout = QVBoxLayout(export_options_group)
        
        # CSV Export
        self.csv_checkbox = QCheckBox("CSV Export")
        self.csv_checkbox.setChecked(True)
        self.csv_checkbox.stateChanged.connect(self._update_export_state)
        export_options_layout.addWidget(self.csv_checkbox)
        
        self.topic_tree = QTreeWidget()
        self.topic_tree.setHeaderLabels(["Topic", "Type", "Count"])
        self.topic_tree.setMinimumHeight(80)
        export_options_layout.addWidget(self.topic_tree)
        
        self.topic_count_label = QLabel("0 topics available")
        export_options_layout.addWidget(self.topic_count_label)
        
        # LAZ Export
        self.laz_checkbox = QCheckBox("LAZ Export")
        self.laz_checkbox.setChecked(True)
        self.laz_checkbox.stateChanged.connect(self._update_export_state)
        export_options_layout.addWidget(self.laz_checkbox)
        
        self.laz_status_label = QLabel("Status: No pointcloud data")
        export_options_layout.addWidget(self.laz_status_label)
        
        # Image Export
        self.image_checkbox = QCheckBox("Image Export")
        self.image_checkbox.setChecked(False)
        self.image_checkbox.stateChanged.connect(self._update_export_state)
        export_options_layout.addWidget(self.image_checkbox)
        
        self.image_status_label = QLabel("Status: Unavailable")
        export_options_layout.addWidget(self.image_status_label)
        
        export_options_layout.addStretch()
        options_layout.addWidget(export_options_group, 60)
        
        # Right: Output Settings (40%)
        output_group = QGroupBox("Output Settings")
        output_layout = QVBoxLayout(output_group)
        
        output_dir_layout = QHBoxLayout()
        output_dir_layout.addWidget(QLabel("Output Directory:"))
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Select output directory...")
        self.output_dir_edit.textChanged.connect(self._update_export_state)
        output_dir_layout.addWidget(self.output_dir_edit)
        
        self.output_browse_btn = QPushButton("Browse...")
        self.output_browse_btn.clicked.connect(self._on_browse_output)
        output_dir_layout.addWidget(self.output_browse_btn)
        
        output_layout.addLayout(output_dir_layout)
        
        self.generate_timestamps_cb = QCheckBox("Generate timestamps.csv")
        self.generate_timestamps_cb.setChecked(True)
        output_layout.addWidget(self.generate_timestamps_cb)
        
        self.merge_laz_cb = QCheckBox("Merge LAZ files")
        self.merge_laz_cb.setChecked(False)
        output_layout.addWidget(self.merge_laz_cb)
        
        output_layout.addStretch()
        
        self.export_btn = QPushButton("▶ Export")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export_clicked)
        output_layout.addWidget(self.export_btn)
        
        options_layout.addWidget(output_group, 40)
        
        layout.addLayout(options_layout)
    
    def _connect_signals(self):
        """Connect internal signals."""
        pass
    
    def _on_browse_session(self):
        """Browse for session directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Recording Session",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if directory:
            self.session_path_edit.setText(directory)
    
    def _on_browse_output(self):
        """Browse for output directory."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            "",
            QFileDialog.Option.ShowDirsOnly
        )
        
        if directory:
            self.output_dir_edit.setText(directory)
    
    def _on_load_session(self):
        """Load session from path."""
        session_path = self.session_path_edit.text().strip()
        
        if not session_path:
            QMessageBox.warning(self, "No Path", "Please select a session path.")
            return
        
        if not os.path.exists(session_path):
            QMessageBox.warning(self, "Invalid Path", f"Path does not exist: {session_path}")
            return
        
        try:
            self._session = BagLoader.load_session(session_path)
            
            self.time_range_selector.set_time_range(
                self._session.start_time_ns,
                self._session.end_time_ns
            )
            self.time_range_selector.setEnabled(True)
            
            self._populate_topic_list()
            self._update_laz_status()
            self._update_image_status()
            
            time_range = BagLoader.format_time_range(self._session)
            duration = BagLoader.format_duration(self._session.duration_ns)
            self.session_status_label.setText(
                f"Loaded: {len(self._session.topics)} topics, "
                f"{self._session.total_message_count} messages, "
                f"Duration: {duration}"
            )
            
            self._update_export_state()
            
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Load Error", str(e))
        except ValueError as e:
            QMessageBox.critical(self, "Parse Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Unexpected Error", f"Failed to load session: {e}")
    
    def _populate_topic_list(self):
        """Populate topic tree with numeric topics."""
        self.topic_tree.clear()
        
        if not self._session:
            return
        
        numeric_topics = BagLoader.get_numeric_topics(self._session)
        
        for topic in numeric_topics:
            item = QTreeWidgetItem([
                topic.name,
                topic.type,
                str(topic.message_count)
            ])
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, Qt.ItemDataRole.UserRole, topic)
            self.topic_tree.addTopLevelItem(item)
        
        self.topic_count_label.setText(f"{len(numeric_topics)} topics available")
    
    def _update_laz_status(self):
        """Update LAZ export status."""
        if not self._session:
            self.laz_status_label.setText("Status: No pointcloud data")
            self.laz_checkbox.setEnabled(False)
            return
        
        if self._session.has_pointcloud:
            file_count = len(self._session.pointcloud_files)
            self.laz_status_label.setText(f"Status: {file_count} LAZ files (pointcloud/ folder)")
            self.laz_checkbox.setEnabled(True)
        elif self._session.has_pointcloud_topics:
            topic_names = ', '.join(self._session.pointcloud_topic_names)
            self.laz_status_label.setText(f"Status: PointCloud2 in rosbag ({topic_names})")
            self.laz_checkbox.setEnabled(True)
        else:
            self.laz_status_label.setText("Status: No pointcloud data")
            self.laz_checkbox.setEnabled(False)
            self.laz_checkbox.setChecked(False)
    def _update_image_status(self):
        """Update Image export status."""
        if not self._session:
            self.image_status_label.setText("Status: Unavailable")
            self.image_checkbox.setEnabled(False)
            return
        
        image_source = ImageExporter.detect_image_source(self._session.session_path)
        
        if image_source == ImageSource.UNAVAILABLE:
            self.image_status_label.setText("Status: Unavailable (No SVO or Image topics)")
            self.image_checkbox.setEnabled(False)
            self.image_checkbox.setChecked(False)
        elif image_source == ImageSource.SVO:
            self.image_status_label.setText(f"Status: SVO available ({len(self._session.svo_files)} files)")
            self.image_checkbox.setEnabled(True)
        elif image_source == ImageSource.ROSBAG:
            self.image_status_label.setText("Status: Image topics available")
            self.image_checkbox.setEnabled(True)
    
    def _update_export_state(self):
        """Update export button state based on selections."""
        can_export = False
        
        if self._session and self.output_dir_edit.text().strip():
            if self.csv_checkbox.isChecked() and self._get_selected_topics():
                can_export = True
            elif self.laz_checkbox.isChecked() and self.laz_checkbox.isEnabled():
                can_export = True
            elif self.image_checkbox.isChecked() and self.image_checkbox.isEnabled():
                can_export = True
        
        self.export_btn.setEnabled(can_export)
    
    def _get_selected_topics(self) -> List[TopicInfo]:
        """Get list of selected topics from tree."""
        selected = []
        
        for i in range(self.topic_tree.topLevelItemCount()):
            item = self.topic_tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                topic = item.data(0, Qt.ItemDataRole.UserRole)
                selected.append(topic)
        
        return selected
    
    def _on_export_clicked(self):
        """Execute export operation."""
        output_dir = self.output_dir_edit.text().strip()
        
        if not output_dir:
            QMessageBox.warning(self, "No Output Directory", "Please select an output directory.")
            return
        
        os.makedirs(output_dir, exist_ok=True)
        
        tasks = self._build_export_tasks()
        
        if not tasks:
            QMessageBox.warning(self, "No Tasks", "No export tasks to execute.")
            return
        
        self._pending_sync = self.generate_timestamps_cb.isChecked()
        
        dialog = ExportProgressDialog(tasks, self)
        dialog.export_finished.connect(self._on_export_finished)
        dialog.start_export()
    
    def _build_export_tasks(self) -> List[ExportTask]:
        """Build list of export tasks from current selections."""
        tasks = []
        
        if not self._session:
            return tasks
        
        output_dir = self.output_dir_edit.text().strip()
        start_ns, end_ns = self.time_range_selector.get_selected_range()
        
        if self.csv_checkbox.isChecked():
            selected_topics = self._get_selected_topics()
            csv_output_dir = os.path.join(output_dir, "csv")
            os.makedirs(csv_output_dir, exist_ok=True)
            
            for topic in selected_topics:
                topic_filename = topic.name.replace('/', '_').strip('_') + '.csv'
                output_path = os.path.join(csv_output_dir, topic_filename)
                
                config = CSVExportConfig(
                    bag_path=self._session.rosbag_path,
                    topic_name=topic.name,
                    topic_type=topic.type,
                    output_path=output_path,
                    start_time_ns=start_ns,
                    end_time_ns=end_ns
                )
                
                tasks.append(ExportTask(
                    task_type="csv",
                    description=f"Export CSV: {topic.name}",
                    config=config
                ))
        
        if self.laz_checkbox.isChecked():
            laz_output_dir = os.path.join(output_dir, "pointcloud")
            os.makedirs(laz_output_dir, exist_ok=True)
            
            if self._session.has_pointcloud:
                # Source A: existing LAZ files in pointcloud/ folder
                config = LAZExportConfig(
                    pointcloud_dir=os.path.join(self._session.session_path, "pointcloud"),
                    output_dir=laz_output_dir,
                    start_time_ns=start_ns,
                    end_time_ns=end_ns,
                    merge=self.merge_laz_cb.isChecked()
                )
                tasks.append(ExportTask(
                    task_type="laz",
                    description="Export LAZ pointcloud files",
                    config=config
                ))
            elif self._session.has_pointcloud_topics:
                # Source B: convert PointCloud2 from rosbag → LAZ
                config = LAZFromBagConfig(
                    bag_path=self._session.rosbag_path,
                    topic_names=self._session.pointcloud_topic_names,
                    output_dir=laz_output_dir,
                    start_time_ns=start_ns,
                    end_time_ns=end_ns,
                )
                tasks.append(ExportTask(
                    task_type="laz_from_bag",
                    description="Convert PointCloud2 → LAZ from rosbag",
                    config=config
                ))
        
        if self.image_checkbox.isChecked():
            image_source = ImageExporter.detect_image_source(self._session.session_path)
            
            if image_source != ImageSource.UNAVAILABLE:
                image_output_dir = os.path.join(output_dir, "images")
                os.makedirs(image_output_dir, exist_ok=True)
                
                config = ImageExportConfig(
                    session_path=self._session.session_path,
                    output_dir=image_output_dir,
                    source=image_source,
                    start_time_ns=start_ns,
                    end_time_ns=end_ns,
                    svo_path=self._session.svo_files[0] if self._session.svo_files else None,
                    svo_paths=self._session.svo_files if self._session.svo_files else None,
                    bag_path=self._session.rosbag_path,
                    image_topics=None
                )
                
                tasks.append(ExportTask(
                    task_type="image",
                    description="Export images",
                    config=config
                ))
        
        return tasks
    
    def _on_export_finished(self, success: bool, summary: str):
        """Handle export completion."""
        if success and self._pending_sync:
            self._run_sync_generator()
        self._pending_sync = False
        
        self.export_completed.emit(success, summary)
        
        if success:
            QMessageBox.information(self, "Export Complete", summary)
        else:
            QMessageBox.warning(self, "Export Failed", summary)
    
    def _run_sync_generator(self):
        """Generate timestamps.csv after export completes."""
        if not self._session:
            return
        
        output_dir = self.output_dir_edit.text().strip()
        start_ns, end_ns = self.time_range_selector.get_selected_range()
        
        pointcloud_dir = None
        if self.laz_checkbox.isChecked() and (self._session.has_pointcloud or self._session.has_pointcloud_topics):
            pointcloud_dir = os.path.join(output_dir, "pointcloud")
        
        image_dirs = None
        if self.image_checkbox.isChecked():
            image_dirs = {"images": os.path.join(output_dir, "images")}
        
        config = SyncGeneratorConfig(
            output_path=os.path.join(output_dir, "timestamps.csv"),
            pointcloud_dir=pointcloud_dir,
            image_dirs=image_dirs,
            start_time_ns=start_ns,
            end_time_ns=end_ns
        )
        
        generator = SyncGenerator()
        result = generator.generate(config)
        
        if not result.success:
            QMessageBox.warning(
                self,
                "Sync Generation Failed",
                f"Failed to generate timestamps.csv: {result.error}"
            )
