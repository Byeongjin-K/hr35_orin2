import numpy as np
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class TimelineDialog(QDialog):
    def __init__(self, bag_path, topic_name, source_frame, target_frame,
                 n_frames, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Timeline Viewer")
        self.setMinimumSize(1000, 650)

        self._bag_path = bag_path
        self._topic_name = topic_name
        self._source_frame = source_frame
        self._target_frame = target_frame
        self._n_frames = n_frames
        self._cache = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance_frame)

        self._init_ui()
        self._load_frame(0)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        ctrl_row = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play")
        self.btn_play.setCheckable(True)
        self.btn_play.clicked.connect(self._toggle_play)
        ctrl_row.addWidget(self.btn_play)

        ctrl_row.addWidget(QLabel("Speed:"))
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(1, 50)
        self.speed_spin.setValue(5)
        self.speed_spin.setSuffix(" fps")
        ctrl_row.addWidget(self.speed_spin)

        ctrl_row.addWidget(QLabel("Frame:"))
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setRange(0, max(0, self._n_frames - 1))
        self.frame_slider.valueChanged.connect(self._on_slider)
        ctrl_row.addWidget(self.frame_slider, stretch=1)

        self.frame_label = QLabel(f"0 / {self._n_frames - 1}")
        self.frame_label.setMinimumWidth(80)
        ctrl_row.addWidget(self.frame_label)
        layout.addLayout(ctrl_row)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #FFD700;")
        layout.addWidget(self.status)

        self.figure = Figure(figsize=(10, 5))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas, stretch=1)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

    def _toggle_play(self, checked):
        if checked:
            self.btn_play.setText("⏸ Pause")
            interval = max(20, int(1000 / self.speed_spin.value()))
            self._timer.start(interval)
        else:
            self.btn_play.setText("▶ Play")
            self._timer.stop()

    def _advance_frame(self):
        current = self.frame_slider.value()
        nxt = current + 1
        if nxt >= self._n_frames:
            nxt = 0
        self.frame_slider.setValue(nxt)

    def _on_slider(self, value):
        self.frame_label.setText(f"{value} / {self._n_frames - 1}")
        self._load_frame(value)

    def _load_frame(self, idx):
        if idx in self._cache:
            self._draw(self._cache[idx], idx)
            return

        try:
            from core.rosbag_loader import load_pointcloud_from_bag
            pts = load_pointcloud_from_bag(
                self._bag_path, self._topic_name,
                frame_index=idx, max_points=8000)

            if self._target_frame and self._source_frame:
                from core.tf_transformer import transform_pointcloud_between_frames
                pts = transform_pointcloud_between_frames(
                    pts, self._bag_path, self._source_frame, self._target_frame)

            self._cache[idx] = pts
            self._draw(pts, idx)
            self.status.setText(f"Frame {idx}: {len(pts):,} pts")
        except Exception as e:
            self.status.setText(f"Error frame {idx}: {e}")

    def _draw(self, pts, idx):
        fig = self.figure
        fig.clear()

        sample = pts
        if len(sample) > 5000:
            i = np.random.choice(len(sample), 5000, replace=False)
            sample = sample[i]

        ax1 = fig.add_subplot(121)
        ax1.scatter(sample[:, 0], sample[:, 1], c=sample[:, 2], s=0.4, cmap='terrain')
        ax1.set_title(f'Top (XY) - Frame {idx}')
        ax1.set_xlabel('X'); ax1.set_ylabel('Y')
        ax1.set_aspect('equal')

        ax2 = fig.add_subplot(122)
        ax2.scatter(sample[:, 0], sample[:, 2], c=sample[:, 2], s=0.4, cmap='terrain')
        ax2.set_title(f'Front (XZ) - Frame {idx}')
        ax2.set_xlabel('X'); ax2.set_ylabel('Z')

        fig.tight_layout()
        self.canvas.draw()
