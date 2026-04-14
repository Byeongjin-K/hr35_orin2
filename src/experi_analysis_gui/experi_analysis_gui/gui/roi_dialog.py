import numpy as np
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QPushButton, QGroupBox, QCheckBox, QSpinBox
)
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import RectangleSelector


class ROIDialog(QDialog):
    def __init__(self, points: np.ndarray, title: str = "ROI Editor", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(1000, 700)

        self._original = points.copy()
        self._result = None
        self._selectors = []
        self._init_ui()
        self._update_preview()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        stats = self._original
        info = QLabel(
            f"총 포인트: {len(stats):,}  |  "
            f"X: [{stats[:,0].min():.2f}, {stats[:,0].max():.2f}]  "
            f"Y: [{stats[:,1].min():.2f}, {stats[:,1].max():.2f}]  "
            f"Z: [{stats[:,2].min():.2f}, {stats[:,2].max():.2f}]"
        )
        info.setStyleSheet("color: #aaa; font-size: 10px;")
        layout.addWidget(info)

        drag_info = QLabel("플롯 위에서 마우스 드래그로 영역 선택 가능 (Top: XY, Front: XZ)")
        drag_info.setStyleSheet("color: #FFD700; font-size: 10px;")
        layout.addWidget(drag_info)

        controls = QHBoxLayout()
        self._spins = {}
        for axis_name, axis_idx, color in [('X', 0, '#2196F3'), ('Y', 1, '#4CAF50'), ('Z', 2, '#F44336')]:
            grp = QGroupBox(f"{axis_name} Range")
            grp.setStyleSheet(f"QGroupBox {{ color: {color}; }}")
            gl = QVBoxLayout()

            vals = self._original[:, axis_idx]
            lo_spin = QDoubleSpinBox()
            lo_spin.setRange(-10000, 10000)
            lo_spin.setValue(float(vals.min()))
            lo_spin.setDecimals(2)
            lo_spin.setObjectName(f"roi_{axis_name.lower()}_min")

            hi_spin = QDoubleSpinBox()
            hi_spin.setRange(-10000, 10000)
            hi_spin.setValue(float(vals.max()))
            hi_spin.setDecimals(2)
            hi_spin.setObjectName(f"roi_{axis_name.lower()}_max")

            self._spins[f"{axis_name.lower()}_min"] = lo_spin
            self._spins[f"{axis_name.lower()}_max"] = hi_spin

            row_lo = QHBoxLayout()
            row_lo.addWidget(QLabel("Min:"))
            row_lo.addWidget(lo_spin)
            gl.addLayout(row_lo)

            row_hi = QHBoxLayout()
            row_hi.addWidget(QLabel("Max:"))
            row_hi.addWidget(hi_spin)
            gl.addLayout(row_hi)

            grp.setLayout(gl)
            controls.addWidget(grp)

        layout.addLayout(controls)

        ds_row = QHBoxLayout()
        ds_row.addWidget(QLabel("Downsample (max pts):"))
        self.downsample_spin = QSpinBox()
        self.downsample_spin.setRange(1000, 10000000)
        self.downsample_spin.setValue(min(len(self._original), 5000000))
        self.downsample_spin.setSingleStep(100000)
        ds_row.addWidget(self.downsample_spin)

        self.chk_remove_outliers = QCheckBox("Z outliers (±3σ)")
        self.chk_remove_outliers.setChecked(False)
        ds_row.addWidget(self.chk_remove_outliers)

        btn_reset = QPushButton("Reset")
        btn_reset.clicked.connect(self._reset_ranges)
        ds_row.addWidget(btn_reset)

        btn_preview = QPushButton("Preview")
        btn_preview.setStyleSheet("background: #2196F3; color: white; padding: 4px 12px;")
        btn_preview.clicked.connect(self._update_preview)
        ds_row.addWidget(btn_preview)
        ds_row.addStretch()
        layout.addLayout(ds_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filters:"))

        self.chk_remove_body = QCheckBox("Self-body 제거")
        self.chk_remove_body.setToolTip("원점 근처 굴착기 자체 포인트 제거\n(반경/높이 기본값 사용)")
        filter_row.addWidget(self.chk_remove_body)

        self.chk_ground_only = QCheckBox("Ground only")
        self.chk_ground_only.setToolTip("지면 포인트만 추출\n(cell-based lowest point)")
        filter_row.addWidget(self.chk_ground_only)

        self.chk_stat_outlier = QCheckBox("KNN outlier 제거")
        self.chk_stat_outlier.setToolTip("통계적 이상치 제거\n(KNN 거리 기반)")
        filter_row.addWidget(self.chk_stat_outlier)

        filter_row.addWidget(QLabel("Max range:"))
        self.max_range_spin = QDoubleSpinBox()
        self.max_range_spin.setRange(1, 500)
        self.max_range_spin.setValue(50)
        self.max_range_spin.setSuffix("m")
        self.max_range_spin.setToolTip("원점으로부터 최대 거리 (m)")
        filter_row.addWidget(self.max_range_spin)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.canvas = FigureCanvas(Figure(figsize=(10, 4.5)))
        layout.addWidget(self.canvas, stretch=1)

        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color: #FFD700;")
        layout.addWidget(self.result_label)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Apply && Close")
        btn_ok.setStyleSheet("background: #4CAF50; color: white; padding: 8px; font-weight: bold;")
        btn_ok.clicked.connect(self._apply)
        btn_row.addWidget(btn_ok)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _reset_ranges(self):
        for axis_idx, axis_name in enumerate(['x', 'y', 'z']):
            vals = self._original[:, axis_idx]
            self._spins[f"{axis_name}_min"].setValue(float(vals.min()))
            self._spins[f"{axis_name}_max"].setValue(float(vals.max()))
        self._update_preview()

    def _on_xy_select(self, eclick, erelease):
        x0, x1 = sorted([eclick.xdata, erelease.xdata])
        y0, y1 = sorted([eclick.ydata, erelease.ydata])
        self._spins['x_min'].setValue(x0)
        self._spins['x_max'].setValue(x1)
        self._spins['y_min'].setValue(y0)
        self._spins['y_max'].setValue(y1)
        self._update_preview()

    def _on_xz_select(self, eclick, erelease):
        x0, x1 = sorted([eclick.xdata, erelease.xdata])
        z0, z1 = sorted([eclick.ydata, erelease.ydata])
        self._spins['x_min'].setValue(x0)
        self._spins['x_max'].setValue(x1)
        self._spins['z_min'].setValue(z0)
        self._spins['z_max'].setValue(z1)
        self._update_preview()

    def _on_yz_select(self, eclick, erelease):
        y0, y1 = sorted([eclick.xdata, erelease.xdata])
        z0, z1 = sorted([eclick.ydata, erelease.ydata])
        self._spins['y_min'].setValue(y0)
        self._spins['y_max'].setValue(y1)
        self._spins['z_min'].setValue(z0)
        self._spins['z_max'].setValue(z1)
        self._update_preview()

    def _get_filtered(self) -> np.ndarray:
        pts = self._original.copy()

        from core.point_filter import remove_self_body, extract_ground, remove_statistical_outliers, remove_range_outliers

        max_range = self.max_range_spin.value()
        pts = remove_range_outliers(pts, max_range=max_range)

        for axis_name, axis_idx in [('x', 0), ('y', 1), ('z', 2)]:
            lo = self._spins[f"{axis_name}_min"].value()
            hi = self._spins[f"{axis_name}_max"].value()
            mask = (pts[:, axis_idx] >= lo) & (pts[:, axis_idx] <= hi)
            pts = pts[mask]

        if self.chk_remove_body.isChecked() and len(pts) > 0:
            pts = remove_self_body(pts)

        if self.chk_ground_only.isChecked() and len(pts) > 0:
            pts, _ = extract_ground(pts)

        if self.chk_remove_outliers.isChecked() and len(pts) > 10:
            z_mean = np.mean(pts[:, 2])
            z_std = np.std(pts[:, 2])
            mask = np.abs(pts[:, 2] - z_mean) < 3 * z_std
            pts = pts[mask]

        if self.chk_stat_outlier.isChecked() and len(pts) > 50:
            pts = remove_statistical_outliers(pts)

        max_pts = self.downsample_spin.value()
        if len(pts) > max_pts:
            idx = np.random.choice(len(pts), max_pts, replace=False)
            pts = pts[idx]

        return pts

    def _update_preview(self):
        pts = self._get_filtered()
        self.result_label.setText(
            f"Filtered: {len(pts):,} points (원본: {len(self._original):,}, "
            f"제거: {len(self._original) - len(pts):,})")

        fig = self.canvas.figure
        fig.clear()
        self._selectors.clear()

        sample = pts
        if len(sample) > 30000:
            idx = np.random.choice(len(sample), 30000, replace=False)
            sample = sample[idx]

        if len(sample) == 0:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, 'No points in range', ha='center', va='center',
                    fontsize=14, color='red', transform=ax.transAxes)
            fig.tight_layout()
            self.canvas.draw()
            return

        rect_props = dict(facecolor='yellow', alpha=0.2, edgecolor='yellow', linewidth=1.5)

        ax1 = fig.add_subplot(131)
        ax1.scatter(sample[:, 0], sample[:, 1], c=sample[:, 2], s=0.3, cmap='terrain')
        ax1.set_title('Top (XY) - drag to select', fontsize=8)
        ax1.set_xlabel('X'); ax1.set_ylabel('Y')
        ax1.set_aspect('equal')
        sel1 = RectangleSelector(ax1, self._on_xy_select,
                                  useblit=True, button=[1],
                                  interactive=True, props=rect_props)
        self._selectors.append(sel1)

        ax2 = fig.add_subplot(132)
        ax2.scatter(sample[:, 0], sample[:, 2], c=sample[:, 2], s=0.3, cmap='terrain')
        ax2.set_title('Front (XZ) - drag to select', fontsize=8)
        ax2.set_xlabel('X'); ax2.set_ylabel('Z')
        sel2 = RectangleSelector(ax2, self._on_xz_select,
                                  useblit=True, button=[1],
                                  interactive=True, props=rect_props)
        self._selectors.append(sel2)

        ax3 = fig.add_subplot(133)
        ax3.scatter(sample[:, 1], sample[:, 2], c=sample[:, 2], s=0.3, cmap='terrain')
        ax3.set_title('Side (YZ) - drag to select', fontsize=8)
        ax3.set_xlabel('Y'); ax3.set_ylabel('Z')
        sel3 = RectangleSelector(ax3, self._on_yz_select,
                                  useblit=True, button=[1],
                                  interactive=True, props=rect_props)
        self._selectors.append(sel3)

        fig.tight_layout()
        self.canvas.draw()

    def _apply(self):
        self._result = self._get_filtered()
        self.accept()

    def get_result(self) -> np.ndarray:
        return self._result
