import numpy as np
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class TFPreviewDialog(QDialog):
    def __init__(
        self,
        bag_path,
        topic_name,
        n_frames,
        source_frame,
        available_frames,
        default_frame_idx=-1,
        default_target_frame="",
        parent=None,
    ):
        super().__init__(parent)
        self._bag_path = bag_path
        self._topic_name = topic_name
        self._n_frames = max(1, n_frames)
        self._source_frame = source_frame or ""
        self._available_frames = available_frames or []
        self._preview_cache = {}
        self._current_raw = None
        self._current_points = None
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._load_preview)

        initial_frame = self._n_frames - 1 if default_frame_idx < 0 else min(default_frame_idx, self._n_frames - 1)
        self._init_ui(initial_frame, default_target_frame)
        self._schedule_preview()

    def _init_ui(self, initial_frame, default_target_frame):
        self.setWindowTitle("TF Preview")
        self.setMinimumSize(950, 680)

        layout = QVBoxLayout(self)

        info = QLabel(
            f"Topic: {self._topic_name}\n"
            f"Source frame: {self._source_frame or '(unknown)'}\n"
            "슬라이더를 움직이면 선택한 frame의 point cloud preview가 갱신됩니다."
        )
        info.setStyleSheet("color: #aaa; font-size: 10px;")
        layout.addWidget(info)

        frame_row = QHBoxLayout()
        frame_row.addWidget(QLabel("Frame:"))
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setRange(0, self._n_frames - 1)
        self.frame_slider.setValue(initial_frame)
        self.frame_slider.valueChanged.connect(self._on_frame_changed)
        frame_row.addWidget(self.frame_slider, stretch=1)
        self.frame_label = QLabel("")
        self.frame_label.setMinimumWidth(120)
        frame_row.addWidget(self.frame_label)
        layout.addLayout(frame_row)

        tf_row = QHBoxLayout()
        tf_row.addWidget(QLabel("Target TF:"))
        self.tf_combo = QComboBox()
        items = ["(변환 안 함)"] + self._available_frames
        self.tf_combo.addItems(items)
        if default_target_frame and default_target_frame in items:
            self.tf_combo.setCurrentIndex(items.index(default_target_frame))
        self.tf_combo.currentIndexChanged.connect(self._schedule_preview)
        tf_row.addWidget(self.tf_combo, stretch=1)
        layout.addLayout(tf_row)

        self.status_label = QLabel("Preview loading...")
        self.status_label.setStyleSheet("color: #FFD700;")
        layout.addWidget(self.status_label)

        self.figure = Figure(figsize=(10, 5.5))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas, stretch=1)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Use This Frame")
        btn_ok.setStyleSheet("background: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _on_frame_changed(self, value):
        self.frame_label.setText(f"{value} / {self._n_frames - 1}")
        self._schedule_preview()

    def _schedule_preview(self):
        self._update_timer.start(120)

    def _load_preview(self):
        frame_idx = self.frame_slider.value()
        target_frame = self.selected_target_frame()
        cache_key = (frame_idx, target_frame)

        if cache_key in self._preview_cache:
            raw_points, points = self._preview_cache[cache_key]
            self._current_raw = raw_points
            self._current_points = points
            self._draw_preview(points)
            return

        try:
            from core.rosbag_loader import load_pointcloud_from_bag

            raw_points = load_pointcloud_from_bag(
                self._bag_path,
                self._topic_name,
                frame_index=frame_idx,
                max_points=5000,
            )
            points = raw_points

            if target_frame:
                from core.tf_transformer import transform_pointcloud_between_frames

                points = transform_pointcloud_between_frames(
                    raw_points,
                    self._bag_path,
                    self._source_frame,
                    target_frame,
                )

            dists = np.linalg.norm(points[:, :2], axis=1)
            range_mask = dists < 20.0
            points = points[range_mask]

            self._preview_cache[cache_key] = (raw_points, points)
            self._current_raw = raw_points
            self._current_points = points
            self._draw_preview(points)
        except Exception as e:
            self.status_label.setText(f"Preview error: {e}")

    def _draw_preview(self, points):
        self.status_label.setText(f"Preview: {len(points):,} pts")
        fig = self.figure
        fig.clear()

        sample = points
        if len(sample) > 3000:
            idx = np.random.choice(len(sample), 3000, replace=False)
            sample = sample[idx]

        ax1 = fig.add_subplot(121)
        ax1.scatter(sample[:, 0], sample[:, 1], c=sample[:, 2], s=0.6, cmap="terrain")
        ax1.set_title("Top (XY)")
        ax1.set_xlabel("X")
        ax1.set_ylabel("Y")
        ax1.set_aspect("equal")

        ax2 = fig.add_subplot(122)
        ax2.scatter(sample[:, 0], sample[:, 2], c=sample[:, 2], s=0.6, cmap="terrain")
        ax2.set_title("Front (XZ)")
        ax2.set_xlabel("X")
        ax2.set_ylabel("Z")

        fig.tight_layout()
        self.canvas.draw()

    def selected_frame_idx(self):
        return self.frame_slider.value()

    def selected_target_frame(self):
        text = self.tf_combo.currentText()
        return "" if text == "(변환 안 함)" else text

    def current_points(self):
        return self._current_points

    def current_raw_points(self):
        return self._current_raw
