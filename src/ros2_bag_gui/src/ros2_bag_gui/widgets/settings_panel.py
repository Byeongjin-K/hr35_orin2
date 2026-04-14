"""Settings panel widget."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QPushButton, QFileDialog, QComboBox, QSpinBox,
    QDoubleSpinBox, QCheckBox
)
from PySide6.QtCore import Signal
from ros2_bag_gui.config.settings import SettingsManager, AppSettings
from ros2_bag_gui.zed.sdk_check import is_zed_sdk_available
from pathlib import Path

class SettingsPanel(QWidget):
    """Panel for recording settings."""
    
    settings_changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings_manager = SettingsManager()
        self._setup_ui()
        self._load_settings()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Output path section
        path_group = QGroupBox("Output Path")
        path_layout = QHBoxLayout(path_group)
        
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select output directory...")
        self.path_edit.setReadOnly(True)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse)
        
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_btn)
        layout.addWidget(path_group)
        
        # Session settings
        session_group = QGroupBox("Session Settings")
        session_layout = QVBoxLayout(session_group)
        
        # Session name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Session Name:"))
        self.session_name_edit = QLineEdit()
        self.session_name_edit.setPlaceholderText("Enter session name...")
        self.session_name_edit.textChanged.connect(self._on_settings_changed)
        name_layout.addWidget(self.session_name_edit)
        session_layout.addLayout(name_layout)
        
        # File split mode
        split_layout = QHBoxLayout()
        split_layout.addWidget(QLabel("Split Mode:"))
        self.split_combo = QComboBox()
        self.split_combo.addItems(["By Size", "By Time", "No Split"])
        self.split_combo.currentIndexChanged.connect(self._on_split_mode_changed)
        split_layout.addWidget(self.split_combo)
        session_layout.addLayout(split_layout)
        
        # Split size
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Split Size (GB):"))
        self.split_size_spin = QDoubleSpinBox()
        self.split_size_spin.setRange(0.5, 100.0)
        self.split_size_spin.setValue(3.0)
        self.split_size_spin.setSingleStep(0.5)
        self.split_size_spin.valueChanged.connect(self._on_settings_changed)
        size_layout.addWidget(self.split_size_spin)
        session_layout.addLayout(size_layout)
        
        # Split time
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Split Time (min):"))
        self.split_time_spin = QSpinBox()
        self.split_time_spin.setRange(1, 1440)
        self.split_time_spin.setValue(30)
        self.split_time_spin.valueChanged.connect(self._on_settings_changed)
        time_layout.addWidget(self.split_time_spin)
        session_layout.addLayout(time_layout)
        
        layout.addWidget(session_group)
        
        # LiDAR recording mode
        lidar_group = QGroupBox("LiDAR Recording Mode")
        lidar_layout = QVBoxLayout(lidar_group)
        
        lidar_mode_layout = QHBoxLayout()
        lidar_mode_layout.addWidget(QLabel("Mode:"))
        self.lidar_mode_combo = QComboBox()
        self.lidar_mode_combo.addItems(["Bag에 포함", "LAZ 분리 저장", "둘 다"])
        self.lidar_mode_combo.currentIndexChanged.connect(self._on_settings_changed)
        lidar_mode_layout.addWidget(self.lidar_mode_combo)
        lidar_layout.addLayout(lidar_mode_layout)
        
        self.lidar_info_label = QLabel("ℹ️ LAZ 모드: LiDAR PointCloud2 → pointcloud/ 폴더에 프레임별 저장")
        self.lidar_info_label.setStyleSheet("color: gray; font-size: 11px;")
        self.lidar_info_label.setWordWrap(True)
        lidar_layout.addWidget(self.lidar_info_label)
        
        layout.addWidget(lidar_group)
        
        # Camera recording mode
        camera_group = QGroupBox("Camera Recording Mode")
        camera_layout = QVBoxLayout(camera_group)
        
        camera_mode_layout = QHBoxLayout()
        camera_mode_layout.addWidget(QLabel("Mode:"))
        self.camera_mode_combo = QComboBox()
        self.camera_mode_combo.addItems(["Bag에 포함", "SVO2 분리 저장", "둘 다"])
        self.camera_mode_combo.currentIndexChanged.connect(self._on_settings_changed)
        camera_mode_layout.addWidget(self.camera_mode_combo)
        camera_layout.addLayout(camera_mode_layout)
        
        # ZED SDK status label
        self._zed_available = is_zed_sdk_available()
        if not self._zed_available:
            self.camera_sdk_label = QLabel("⚠️ ZED SDK 미설치 — SVO2 옵션 비활성화됨")
            self.camera_sdk_label.setStyleSheet("color: #e67e22; font-size: 11px;")
            self.camera_sdk_label.setWordWrap(True)
            camera_layout.addWidget(self.camera_sdk_label)
            # Disable SVO2 options (index 1 = SVO2, index 2 = both)
            model = self.camera_mode_combo.model()
            model.item(1).setEnabled(False)
            model.item(2).setEnabled(False)
        else:
            self.camera_sdk_label = QLabel("✅ ZED SDK 사용 가능 — SVO2 녹화 지원")
            self.camera_sdk_label.setStyleSheet("color: #27ae60; font-size: 11px;")
            camera_layout.addWidget(self.camera_sdk_label)
        
        layout.addWidget(camera_group)
        layout.addStretch()
    
    def _on_browse(self):
        """Open folder selection dialog."""
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            self.path_edit.text() or str(Path.home())
        )
        if path:
            self.path_edit.setText(path)
            self._on_settings_changed()
    
    def _on_split_mode_changed(self, index: int):
        """Handle split mode change."""
        # Enable/disable relevant controls
        self.split_size_spin.setEnabled(index == 0)
        self.split_time_spin.setEnabled(index == 1)
        self._on_settings_changed()
    
    def _on_settings_changed(self):
        """Save settings when changed."""
        self._save_settings()
        self.settings_changed.emit()
    
    def _load_settings(self):
        """Load settings into UI."""
        s = self._settings_manager.settings
        self.path_edit.setText(s.output_path)
        self.session_name_edit.setText(s.session_name)
        
        # Split mode
        mode_map = {"size": 0, "time": 1, "none": 2}
        self.split_combo.setCurrentIndex(mode_map.get(s.split_mode, 0))
        
        self.split_size_spin.setValue(s.split_size_gb)
        self.split_time_spin.setValue(s.split_time_minutes)
        # LiDAR mode
        lidar_mode_map = {"bag": 0, "laz": 1, "both": 2}
        self.lidar_mode_combo.setCurrentIndex(lidar_mode_map.get(s.lidar_mode, 0))
        
        # Camera mode
        camera_mode_map = {"bag": 0, "svo2": 1, "both": 2}
        idx = camera_mode_map.get(s.camera_mode, 0)
        if not self._zed_available and idx > 0:
            idx = 0  # Fallback to bag if SDK not available
        self.camera_mode_combo.setCurrentIndex(idx)
        
        self._on_split_mode_changed(self.split_combo.currentIndex())
    
    def _save_settings(self):
        """Save UI state to settings."""
        mode_map = {0: "size", 1: "time", 2: "none"}
        lidar_mode_map = {0: "bag", 1: "laz", 2: "both"}
        camera_mode_map = {0: "bag", 1: "svo2", 2: "both"}
        
        self._settings_manager.update(
            output_path=self.path_edit.text(),
            session_name=self.session_name_edit.text(),
            split_mode=mode_map[self.split_combo.currentIndex()],
            split_size_gb=self.split_size_spin.value(),
            split_time_minutes=self.split_time_spin.value(),
            lidar_mode=lidar_mode_map[self.lidar_mode_combo.currentIndex()],
            camera_mode=camera_mode_map[self.camera_mode_combo.currentIndex()]
        )
    
    def get_settings(self) -> AppSettings:
        """Get current settings."""
        return self._settings_manager.settings
