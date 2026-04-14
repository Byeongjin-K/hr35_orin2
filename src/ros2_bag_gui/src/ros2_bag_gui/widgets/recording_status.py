"""Recording status panel with live statistics."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QTableWidget, QTableWidgetItem, QProgressBar, QHeaderView
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from typing import Dict, Optional, Union
from enum import Enum
import shutil

class RecordingState(Enum):
    READY = "Ready"
    RECORDING = "Recording"
    STOPPED = "Stopped"

class DiskSpaceState(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"

class RecordingStatusPanel(QWidget):
    """Panel showing recording status and statistics."""
    
    disk_critical = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = RecordingState.READY
        self._elapsed_seconds = 0
        self._topic_stats: Dict[str, Dict] = {}
        self._target_path = "/"
        self._setup_ui()
        self._setup_timer()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        state_group = QGroupBox("Recording Status")
        state_layout = QHBoxLayout(state_group)
        
        self.state_label = QLabel("Ready")
        self.state_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        state_layout.addWidget(self.state_label)
        
        self.elapsed_label = QLabel("00:00:00")
        self.elapsed_label.setStyleSheet("font-size: 13px; font-family: monospace;")
        state_layout.addWidget(self.elapsed_label)
        state_layout.addStretch()
        
        layout.addWidget(state_group)
        
        storage_group = QGroupBox("Storage")
        storage_layout = QVBoxLayout(storage_group)
        
        sizes_layout = QHBoxLayout()
        self.rosbag_size = QLabel("Rosbag: 0 B")
        self.pointcloud_size = QLabel("PointCloud: 0 B")
        self.images_size = QLabel("Images: 0 B")
        sizes_layout.addWidget(self.rosbag_size)
        sizes_layout.addWidget(self.pointcloud_size)
        sizes_layout.addWidget(self.images_size)
        storage_layout.addLayout(sizes_layout)
        
        disk_layout = QHBoxLayout()
        self.disk_label = QLabel("Disk: -- GB free")
        self.disk_bar = QProgressBar()
        self.disk_bar.setMaximum(100)
        self.disk_bar.setMinimumWidth(100)
        disk_layout.addWidget(self.disk_label)
        disk_layout.addWidget(self.disk_bar)
        disk_layout.addStretch()
        storage_layout.addLayout(disk_layout)
        
        layout.addWidget(storage_group)
        
        stats_group = QGroupBox("Topic Statistics")
        stats_layout = QVBoxLayout(stats_group)
        
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(3)
        self.stats_table.setHorizontalHeaderLabels(["Topic", "Messages", "Hz"])
        self.stats_table.setMinimumHeight(200)
        self.stats_table.verticalHeader().setDefaultSectionSize(22)
        self.stats_table.verticalHeader().setVisible(False)
        
        header = self.stats_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 70)
        header.resizeSection(2, 45)
        
        stats_layout.addWidget(self.stats_table)
        
        layout.addWidget(stats_group, 1)
    
    def _setup_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)
    
    def _on_timer_tick(self):
        if self._state == RecordingState.RECORDING:
            self._elapsed_seconds += 1
            self._update_elapsed_display()
        self._update_disk_space(self._target_path)
    
    def _update_elapsed_display(self):
        hours = self._elapsed_seconds // 3600
        minutes = (self._elapsed_seconds % 3600) // 60
        seconds = self._elapsed_seconds % 60
        self.elapsed_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
    
    def set_state(self, state: RecordingState):
        self._state = state
        self.state_label.setText(state.value)
        
        if state == RecordingState.RECORDING:
            self.state_label.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #e74c3c;"
            )
            self._timer.start(1000)
        elif state == RecordingState.STOPPED:
            self.state_label.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #3498db;"
            )
            self._timer.stop()
        else:  # READY
            self.state_label.setStyleSheet(
                "font-size: 13px; font-weight: bold; color: #27ae60;"
            )
            self._elapsed_seconds = 0
            self._update_elapsed_display()
            self._timer.stop()
            self._update_disk_space(self._target_path)
    
    def update_topic_stats(self, stats: Dict[str, Dict]):
        self._topic_stats = stats
        self.stats_table.setRowCount(len(stats))
        
        sorted_topics = sorted(stats.keys())
        
        for row, topic in enumerate(sorted_topics):
            data = stats[topic]
            self.stats_table.setItem(row, 0, QTableWidgetItem(topic))
            self.stats_table.setItem(row, 1, QTableWidgetItem(str(data.get('count', 0))))
            self.stats_table.setItem(row, 2, QTableWidgetItem(f"{data.get('hz', 0):.1f}"))
    
    def update_storage_sizes(self, rosbag_bytes: int, pointcloud_bytes: int, images_bytes: int):
        self.rosbag_size.setText(f"Rosbag: {self._format_size(rosbag_bytes)}")
        self.pointcloud_size.setText(f"PointCloud: {self._format_size(pointcloud_bytes)}")
        self.images_size.setText(f"Images: {self._format_size(images_bytes)}")
    
    def _format_size(self, bytes_val: Union[int, float]) -> str:
        current_val = float(bytes_val)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if current_val < 1024:
                return f"{current_val:.1f} {unit}"
            current_val /= 1024
        return f"{current_val:.1f} PB"
    
    def _update_disk_space(self, path: str = "/"):
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024**3)
            used_percent = int((usage.used / usage.total) * 100)
            
            self.disk_bar.setValue(used_percent)
            
            if free_gb < 5:
                self.disk_label.setText(f"🛑 Disk critical! ({free_gb:.1f} GB)")
                self.disk_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.disk_critical.emit()
            elif free_gb < 20:
                self.disk_label.setText(f"⚠️ Disk space low ({free_gb:.1f} GB)")
                self.disk_label.setStyleSheet("color: #f39c12; font-weight: bold;")
            else:
                self.disk_label.setText(f"Disk: {free_gb:.1f} GB free")
                self.disk_label.setStyleSheet("")
            
        except Exception:
            self.disk_label.setText("Disk: N/A")
    
    def set_target_path(self, path: str):
        self._target_path = path if path else "/"
        self._update_disk_space(self._target_path)
    
    def reset(self):
        self.set_state(RecordingState.READY)
        self._topic_stats.clear()
        self.stats_table.setRowCount(0)
        self.update_storage_sizes(0, 0, 0)
