import numpy as np
import pyqtgraph.opengl as gl
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QSlider, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QVector3D

from experi_analysis_gui.utils.helpers import apply_jet_colormap_fast, downsample_points


class PointCloudViewer3D(QWidget):
    measurement_updated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scatter_items = {}
        self._grid_item = None
        self._all_points_cache = {}

        self._measure_mode = None
        self._measure_points = []
        self._measure_lines = []
        self._measure_markers = []

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.setBackgroundColor('k')
        self.gl_widget.opts['distance'] = 10
        self.gl_widget.opts['elevation'] = 30
        self.gl_widget.opts['azimuth'] = 45

        grid = gl.GLGridItem()
        grid.setSize(20, 20, 1)
        grid.setSpacing(1, 1, 1)
        grid.setColor((255, 255, 255, 40))
        self.gl_widget.addItem(grid)
        self._grid_item = grid

        axis = gl.GLAxisItem()
        axis.setSize(3, 3, 3)
        self.gl_widget.addItem(axis)

        toolbar = QHBoxLayout()

        self.colormap_combo = QComboBox()
        self.colormap_combo.addItems(["Height (Z)", "Difference", "Before/After"])
        self.colormap_combo.currentIndexChanged.connect(self._on_colormap_changed)
        toolbar.addWidget(QLabel("Color:"))
        toolbar.addWidget(self.colormap_combo)

        self.point_size_slider = QSlider(Qt.Horizontal)
        self.point_size_slider.setRange(1, 20)
        self.point_size_slider.setValue(3)
        self.point_size_slider.valueChanged.connect(self._on_point_size_changed)
        toolbar.addWidget(QLabel("Size:"))
        toolbar.addWidget(self.point_size_slider)

        btn_reset = QPushButton("Reset View")
        btn_reset.clicked.connect(self.reset_view)
        toolbar.addWidget(btn_reset)

        btn_top = QPushButton("Top")
        btn_top.clicked.connect(lambda: self.set_view('top'))
        toolbar.addWidget(btn_top)

        btn_front = QPushButton("Front")
        btn_front.clicked.connect(lambda: self.set_view('front'))
        toolbar.addWidget(btn_front)

        btn_side = QPushButton("Side")
        btn_side.clicked.connect(lambda: self.set_view('side'))
        toolbar.addWidget(btn_side)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        measure_bar = QHBoxLayout()
        measure_bar.addWidget(QLabel("Measure:"))

        coord_style = "max-width: 65px;"
        self._m_spins = {}
        for label_text, prefix in [("P1", "p1"), ("P2", "p2")]:
            measure_bar.addWidget(QLabel(f" {label_text}:"))
            for ax in ['x', 'y', 'z']:
                from PyQt5.QtWidgets import QDoubleSpinBox as DSB
                sp = DSB()
                sp.setRange(-10000, 10000)
                sp.setDecimals(2)
                sp.setValue(0)
                sp.setStyleSheet(coord_style)
                sp.setToolTip(f"{label_text} {ax.upper()} 좌표")
                self._m_spins[f"{prefix}_{ax}"] = sp
                measure_bar.addWidget(sp)

        btn_calc = QPushButton("Calc")
        btn_calc.setStyleSheet("background: #FF9800; color: white; font-weight: bold; padding: 4px 8px;")
        btn_calc.setToolTip("P1-P2 거리 계산 및 3D 마커 표시")
        btn_calc.clicked.connect(self._calc_measurement)
        measure_bar.addWidget(btn_calc)

        btn_2d_pick = QPushButton("2D Pick")
        btn_2d_pick.setStyleSheet("background: #9C27B0; color: white; font-weight: bold; padding: 4px 8px;")
        btn_2d_pick.setToolTip("2D 플롯(Top/Front/Side)에서 클릭하여\n정확하게 P1/P2 선택")
        btn_2d_pick.clicked.connect(self._open_2d_pick_dialog)
        measure_bar.addWidget(btn_2d_pick)

        btn_clear_m = QPushButton("Clear")
        btn_clear_m.clicked.connect(self._clear_measurements)
        measure_bar.addWidget(btn_clear_m)

        self.measure_label = QLabel("")
        self.measure_label.setStyleSheet("color: #FFD700; font-weight: bold; font-size: 11px;")
        measure_bar.addWidget(self.measure_label, stretch=1)

        layout.addLayout(measure_bar)
        layout.addWidget(self.gl_widget, stretch=1)

    def _open_2d_pick_dialog(self):
        all_pts = []
        for name, pts in self._all_points_cache.items():
            if name in self._scatter_items:
                try:
                    if self._scatter_items[name].visible():
                        all_pts.append(pts)
                except Exception:
                    all_pts.append(pts)

        if not all_pts:
            self.measure_label.setText("점군 데이터가 없습니다")
            return

        combined = np.vstack(all_pts)
        if len(combined) == 0:
            return

        from gui.point_pick_dialog import PointPickDialog
        dlg = PointPickDialog(combined, title="Point Picker (2D)", parent=self)
        if dlg.exec_():
            p1 = dlg.get_p1()
            p2 = dlg.get_p2()
            for ax_i, ax in enumerate(['x', 'y', 'z']):
                self._m_spins[f"p1_{ax}"].setValue(float(p1[ax_i]))
                self._m_spins[f"p2_{ax}"].setValue(float(p2[ax_i]))
            self._calc_measurement()

    def _calc_measurement(self):
        p1 = np.array([self._m_spins[f"p1_{ax}"].value() for ax in ['x', 'y', 'z']])
        p2 = np.array([self._m_spins[f"p2_{ax}"].value() for ax in ['x', 'y', 'z']])
        dist = np.linalg.norm(p2 - p1)
        dx, dy, dz = abs(p2[0]-p1[0]), abs(p2[1]-p1[1]), p2[2]-p1[2]

        self._clear_measurements()
        self._add_measure_marker(p1)
        self._add_measure_marker(p2)
        self._add_measure_line(p1, p2)

        text = f"Dist: {dist:.4f}m | dx={dx:.4f} dy={dy:.4f} dz={dz:+.4f}"
        self.measure_label.setText(text)
        self.measurement_updated.emit(text)

    def _find_nearest_point_to_click(self, screen_pos):
        all_pts = []
        for name, pts in self._all_points_cache.items():
            if name in self._scatter_items:
                try:
                    if self._scatter_items[name].visible():
                        all_pts.append(pts)
                except Exception:
                    all_pts.append(pts)

        if not all_pts:
            return None

        combined = np.vstack(all_pts)
        if len(combined) == 0:
            return None

        if len(combined) > 80000:
            idx = np.random.choice(len(combined), 80000, replace=False)
            combined = combined[idx]

        view = self.gl_widget
        elev = np.radians(view.opts['elevation'])
        azim = np.radians(view.opts['azimuth'])

        ce, se = np.cos(elev), np.sin(elev)
        ca, sa = np.cos(azim), np.sin(azim)
        right = np.array([ca, sa, 0])
        up = np.array([-sa * se, ca * se, ce])

        center = np.array([view.opts['center'].x(), view.opts['center'].y(), view.opts['center'].z()])
        rel = combined - center

        proj_x = rel @ right
        proj_y = rel @ up

        w = view.width()
        h = view.height()
        dist = view.opts['distance']
        scale = w / (2 * dist) if dist > 0 else 1

        sx = float(screen_pos.x()) - w / 2
        sy = -(float(screen_pos.y()) - h / 2)

        d2 = (proj_x * scale - sx)**2 + (proj_y * scale - sy)**2
        return combined[np.argmin(d2)].copy()

    def _add_measure_marker(self, point):
        marker = gl.GLScatterPlotItem(
            pos=np.array([point]),
            color=(1, 1, 0, 1),
            size=12,
            pxMode=True
        )
        self.gl_widget.addItem(marker)
        self._measure_markers.append(marker)

    def _add_measure_line(self, p1, p2):
        line_pts = np.array([p1, p2])
        line = gl.GLLinePlotItem(
            pos=line_pts,
            color=(1, 1, 0, 1),
            width=2,
            antialias=True
        )
        self.gl_widget.addItem(line)
        self._measure_lines.append(line)

    def _clear_measurements(self):
        for item in self._measure_markers:
            self.gl_widget.removeItem(item)
        for item in self._measure_lines:
            self.gl_widget.removeItem(item)
        self._measure_markers.clear()
        self._measure_lines.clear()
        self._measure_points.clear()
        self.measure_label.setText("Measurements cleared")

    def add_pointcloud(self, name: str, points: np.ndarray,
                       color=None, size: float = None, visible: bool = True):
        if name in self._scatter_items:
            self.gl_widget.removeItem(self._scatter_items[name])

        display_points = downsample_points(points, max_points=200000)
        self._all_points_cache[name] = display_points

        if color is None:
            z = display_points[:, 2]
            color = apply_jet_colormap_fast(z)

        if isinstance(color, tuple) and len(color) in (3, 4):
            color_array = np.ones((len(display_points), 4))
            color_array[:, :len(color)] = color
            color = color_array

        if size is None:
            size = self.point_size_slider.value()

        scatter = gl.GLScatterPlotItem(
            pos=display_points,
            color=color,
            size=size,
            pxMode=True
        )
        scatter.setVisible(visible)
        self.gl_widget.addItem(scatter)
        self._scatter_items[name] = scatter

    def remove_pointcloud(self, name: str):
        if name in self._scatter_items:
            self.gl_widget.removeItem(self._scatter_items[name])
            del self._scatter_items[name]
        self._all_points_cache.pop(name, None)

    def set_pointcloud_visible(self, name: str, visible: bool):
        if name in self._scatter_items:
            self._scatter_items[name].setVisible(visible)

    def clear_all(self):
        for name in list(self._scatter_items.keys()):
            self.remove_pointcloud(name)
        self._all_points_cache.clear()

    def add_height_surface(self, name: str, grid_data: dict,
                           color=None, opacity: float = 0.7):
        grid = grid_data['grid']
        res = grid_data['resolution']
        origin = grid_data['origin']

        ny, nx = grid.shape
        x = np.arange(nx) * res + origin[0]
        y = np.arange(ny) * res + origin[1]

        safe_grid = np.nan_to_num(grid, nan=np.nanmean(grid) if not np.all(np.isnan(grid)) else 0)

        if color is None:
            colors = apply_jet_colormap_fast(safe_grid.flatten(),
                                             vmin=np.nanmin(grid),
                                             vmax=np.nanmax(grid))
            color_grid = colors[:, :3].reshape(ny, nx, 3)
            color_array = np.ones((ny, nx, 4))
            color_array[:, :, :3] = color_grid
            color_array[:, :, 3] = opacity
        else:
            color_array = np.ones((ny, nx, 4))
            color_array[:, :, :3] = color[:3] if len(color) >= 3 else color
            color_array[:, :, 3] = opacity

        surface = gl.GLSurfacePlotItem(
            x=x, y=y, z=safe_grid,
            colors=color_array,
            shader='shaded',
            smooth=True
        )

        if name in self._scatter_items:
            self.gl_widget.removeItem(self._scatter_items[name])
        self.gl_widget.addItem(surface)
        self._scatter_items[name] = surface

    def reset_view(self):
        self.gl_widget.opts['distance'] = 10
        self.gl_widget.opts['elevation'] = 30
        self.gl_widget.opts['azimuth'] = 45
        self.gl_widget.opts['center'] = QVector3D(0, 0, 0)
        self.gl_widget.update()

    def set_view(self, direction: str):
        if direction == 'top':
            self.gl_widget.opts['elevation'] = 90
            self.gl_widget.opts['azimuth'] = 0
        elif direction == 'front':
            self.gl_widget.opts['elevation'] = 0
            self.gl_widget.opts['azimuth'] = 0
        elif direction == 'side':
            self.gl_widget.opts['elevation'] = 0
            self.gl_widget.opts['azimuth'] = 90
        self.gl_widget.update()

    def auto_center(self):
        all_points = []
        for item in self._scatter_items.values():
            if isinstance(item, gl.GLScatterPlotItem) and item.visible():
                pos = item.pos
                if pos is not None and len(pos) > 0:
                    all_points.append(pos)

        if all_points:
            combined = np.vstack(all_points)
            center = combined.mean(axis=0)
            extent = combined.max(axis=0) - combined.min(axis=0)
            self.gl_widget.opts['center'] = QVector3D(float(center[0]), float(center[1]), float(center[2]))
            self.gl_widget.opts['distance'] = max(extent) * 1.5
            self.gl_widget.update()

    def _on_colormap_changed(self, index):
        pass

    def _on_point_size_changed(self, value):
        for item in self._scatter_items.values():
            if isinstance(item, gl.GLScatterPlotItem):
                item.setData(size=value)
