import numpy as np
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QPushButton, QGroupBox
)
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from scipy.spatial import KDTree


class PointPickDialog(QDialog):
    def __init__(self, all_points: np.ndarray, title="Point Picker", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(1000, 700)

        self._pts = all_points.copy()
        self._sample_idx = np.arange(len(self._pts))
        if len(self._pts) > 50000:
            self._sample_idx = np.random.choice(len(self._pts), 50000, replace=False)
        self._sample = self._pts[self._sample_idx]

        self._tree_xy = KDTree(self._sample[:, :2])
        self._tree_xz = KDTree(self._sample[:, [0, 2]])
        self._tree_yz = KDTree(self._sample[:, [1, 2]])

        self._p1 = None
        self._p2 = None
        self._picking = None

        self._init_ui()
        self._draw()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel("플롯에서 클릭하여 P1/P2 선택, 또는 좌표를 직접 입력하세요.")
        info.setStyleSheet("color: #aaa;")
        layout.addWidget(info)

        pick_row = QHBoxLayout()
        self.btn_pick_p1 = QPushButton("◉ Pick P1")
        self.btn_pick_p1.setCheckable(True)
        self.btn_pick_p1.setStyleSheet("color: #FFD700; font-weight: bold;")
        self.btn_pick_p1.clicked.connect(lambda c: self._set_picking('p1' if c else None))
        pick_row.addWidget(self.btn_pick_p1)

        self.btn_pick_p2 = QPushButton("◉ Pick P2")
        self.btn_pick_p2.setCheckable(True)
        self.btn_pick_p2.setStyleSheet("color: #64B5F6; font-weight: bold;")
        self.btn_pick_p2.clicked.connect(lambda c: self._set_picking('p2' if c else None))
        pick_row.addWidget(self.btn_pick_p2)

        self.pick_status = QLabel("")
        self.pick_status.setStyleSheet("color: #FF9800; font-weight: bold;")
        pick_row.addWidget(self.pick_status, stretch=1)
        layout.addLayout(pick_row)

        coord_row = QHBoxLayout()
        self._spins = {}
        for prefix, color in [("P1", "#FFD700"), ("P2", "#64B5F6")]:
            grp = QGroupBox(prefix)
            grp.setStyleSheet(f"QGroupBox {{ color: {color}; }}")
            gl = QHBoxLayout()
            for ax in ['x', 'y', 'z']:
                sp = QDoubleSpinBox()
                sp.setRange(-10000, 10000)
                sp.setDecimals(3)
                sp.setValue(0)
                gl.addWidget(QLabel(f"{ax.upper()}:"))
                gl.addWidget(sp)
                self._spins[f"{prefix.lower()}_{ax}"] = sp
            grp.setLayout(gl)
            coord_row.addWidget(grp)
        layout.addLayout(coord_row)

        self.result_label = QLabel("")
        self.result_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 13px;")
        layout.addWidget(self.result_label)

        self.figure = Figure(figsize=(10, 5))
        self.canvas = FigureCanvas(self.figure)
        self.canvas.mpl_connect('button_press_event', self._on_plot_click)
        layout.addWidget(self.canvas, stretch=1)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Done (Close)")
        btn_ok.setStyleSheet("background: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def _set_picking(self, target):
        self._picking = target
        self.btn_pick_p1.setChecked(target == 'p1')
        self.btn_pick_p2.setChecked(target == 'p2')
        if target:
            self.pick_status.setText(f"Click on plot to pick {target.upper()}...")
        else:
            self.pick_status.setText("")

    def _on_plot_click(self, event):
        if self._picking is None or event.inaxes is None:
            return

        click_x, click_y = event.xdata, event.ydata
        axes = self.figure.axes
        if event.inaxes not in axes:
            return

        ax_idx = axes.index(event.inaxes)
        if ax_idx == 0:
            _, idx = self._tree_xy.query([click_x, click_y])
        elif ax_idx == 1:
            _, idx = self._tree_xz.query([click_x, click_y])
        elif ax_idx == 2:
            _, idx = self._tree_yz.query([click_x, click_y])
        else:
            return

        point = self._sample[idx]

        if self._picking == 'p1':
            self._p1 = point.copy()
            for ax_name in ['x', 'y', 'z']:
                self._spins[f"p1_{ax_name}"].setValue(float(point[['x', 'y', 'z'].index(ax_name)]))
            self.pick_status.setText(f"P1 = ({point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f})")
        elif self._picking == 'p2':
            self._p2 = point.copy()
            for ax_name in ['x', 'y', 'z']:
                self._spins[f"p2_{ax_name}"].setValue(float(point[['x', 'y', 'z'].index(ax_name)]))
            self.pick_status.setText(f"P2 = ({point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f})")

        self._set_picking(None)
        self._update_result()
        self._draw()

    def _update_result(self):
        p1 = np.array([self._spins[f"p1_{ax}"].value() for ax in ['x', 'y', 'z']])
        p2 = np.array([self._spins[f"p2_{ax}"].value() for ax in ['x', 'y', 'z']])
        dist = np.linalg.norm(p2 - p1)
        dx, dy, dz = p2 - p1
        self.result_label.setText(
            f"Distance: {dist:.4f} m  |  "
            f"dx={dx:.4f}  dy={dy:.4f}  dz={dz:.4f}")

    def _draw(self):
        fig = self.figure
        fig.clear()

        s = self._sample
        if len(s) > 20000:
            idx = np.random.choice(len(s), 20000, replace=False)
            s = s[idx]

        for i, (proj_name, x_idx, y_idx, xl, yl) in enumerate([
            ("Top (XY)", 0, 1, "X", "Y"),
            ("Front (XZ)", 0, 2, "X", "Z"),
            ("Side (YZ)", 1, 2, "Y", "Z"),
        ]):
            ax = fig.add_subplot(1, 3, i + 1)
            ax.scatter(s[:, x_idx], s[:, y_idx], c=s[:, 2], s=0.3, cmap='terrain', alpha=0.6)
            ax.set_title(proj_name, fontsize=9)
            ax.set_xlabel(xl); ax.set_ylabel(yl)
            if i == 0:
                ax.set_aspect('equal')

            if self._p1 is not None:
                ax.plot(self._p1[x_idx], self._p1[y_idx], 'o', color='#FFD700',
                        markersize=10, markeredgecolor='white', markeredgewidth=1.5, zorder=10)
                ax.annotate('P1', (self._p1[x_idx], self._p1[y_idx]),
                            color='#FFD700', fontsize=8, fontweight='bold',
                            xytext=(5, 5), textcoords='offset points')

            if self._p2 is not None:
                ax.plot(self._p2[x_idx], self._p2[y_idx], 's', color='#64B5F6',
                        markersize=10, markeredgecolor='white', markeredgewidth=1.5, zorder=10)
                ax.annotate('P2', (self._p2[x_idx], self._p2[y_idx]),
                            color='#64B5F6', fontsize=8, fontweight='bold',
                            xytext=(5, 5), textcoords='offset points')

            if self._p1 is not None and self._p2 is not None:
                ax.plot([self._p1[x_idx], self._p2[x_idx]],
                        [self._p1[y_idx], self._p2[y_idx]],
                        '--', color='#FF9800', linewidth=1.5, zorder=9)

        fig.tight_layout()
        self.canvas.draw()

    def get_p1(self):
        return np.array([self._spins[f"p1_{ax}"].value() for ax in ['x', 'y', 'z']])

    def get_p2(self):
        return np.array([self._spins[f"p2_{ax}"].value() for ax in ['x', 'y', 'z']])
