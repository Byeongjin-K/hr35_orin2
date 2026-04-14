import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QCheckBox, QSlider
)
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure


class GridMapViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._grids = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("View:"))
        self.view_combo = QComboBox()
        self.view_combo.addItems([
            "Height Map (2D)", "Contour", "3D Surface",
            "Difference (After - Before)", "Error (Actual vs Target)",
            "Volume 3D (Cut/Fill)"
        ])
        self.view_combo.currentIndexChanged.connect(self._refresh)
        toolbar.addWidget(self.view_combo)

        toolbar.addWidget(QLabel("CMap:"))
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(['terrain', 'viridis', 'RdBu_r', 'jet', 'coolwarm', 'gray'])
        self.cmap_combo.currentIndexChanged.connect(self._refresh)
        toolbar.addWidget(self.cmap_combo)

        self.chk_before = QCheckBox("Before")
        self.chk_before.setChecked(True)
        self.chk_before.setStyleSheet("color: #64B5F6;")
        self.chk_before.stateChanged.connect(self._refresh)
        toolbar.addWidget(self.chk_before)

        self.chk_after = QCheckBox("After")
        self.chk_after.setChecked(True)
        self.chk_after.setStyleSheet("color: #EF5350;")
        self.chk_after.stateChanged.connect(self._refresh)
        toolbar.addWidget(self.chk_after)

        self.chk_target = QCheckBox("Target")
        self.chk_target.setChecked(False)
        self.chk_target.setStyleSheet("color: #66BB6A;")
        self.chk_target.stateChanged.connect(self._refresh)
        toolbar.addWidget(self.chk_target)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.figure = Figure(figsize=(10, 6))
        self.canvas = FigureCanvas(self.figure)
        self.nav_toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.nav_toolbar)
        layout.addWidget(self.canvas, stretch=1)

    def set_grid(self, key: str, grid_data: dict):
        self._grids[key] = grid_data
        self._refresh()

    def remove_grid(self, key: str):
        self._grids.pop(key, None)
        self._refresh()

    def _get_extent(self, gd):
        g = gd['grid']
        res = gd['resolution']
        ox, oy = gd['origin']
        ny, nx = g.shape
        return [ox, ox + nx * res, oy, oy + ny * res]

    def _refresh(self):
        fig = self.figure
        fig.clear()

        view = self.view_combo.currentText()
        cmap = self.cmap_combo.currentText()

        if view == "Difference (After - Before)":
            self._plot_difference(fig, cmap)
        elif view == "Error (Actual vs Target)":
            self._plot_error(fig, cmap)
        elif view == "3D Surface":
            self._plot_3d_surface(fig, cmap)
        elif view == "Contour":
            self._plot_contour(fig, cmap)
        elif view == "Volume 3D (Cut/Fill)":
            self._plot_volume_3d(fig)
        else:
            self._plot_heatmaps(fig, cmap)

        fig.tight_layout()
        self.canvas.draw()

    def _visible_keys(self):
        keys = []
        if self.chk_before.isChecked() and 'before' in self._grids:
            keys.append('before')
        if self.chk_after.isChecked() and 'after' in self._grids:
            keys.append('after')
        if self.chk_target.isChecked() and 'target' in self._grids:
            keys.append('target')
        return keys

    def _plot_heatmaps(self, fig, cmap):
        keys = self._visible_keys()
        if not keys:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, 'No grid data', ha='center', va='center', fontsize=14,
                    transform=ax.transAxes, color='gray')
            return

        titles = {'before': 'Before', 'after': 'After', 'target': 'Target'}
        colors = {'before': '#64B5F6', 'after': '#EF5350', 'target': '#66BB6A'}
        n = len(keys)
        for i, key in enumerate(keys):
            ax = fig.add_subplot(1, n, i + 1)
            gd = self._grids[key]
            im = ax.imshow(gd['grid'], cmap=cmap, aspect='equal',
                           extent=self._get_extent(gd), origin='lower')
            ax.set_title(titles.get(key, key), fontsize=10, color=colors.get(key, 'white'))
            ax.set_xlabel('X (m)'); ax.set_ylabel('Y (m)')
            fig.colorbar(im, ax=ax, label='Height (m)', shrink=0.8)

    def _plot_contour(self, fig, cmap):
        keys = self._visible_keys()
        if not keys:
            return

        ax = fig.add_subplot(111)
        line_styles = {'before': '-', 'after': '--', 'target': ':'}
        colors_map = {'before': 'blue', 'after': 'red', 'target': 'green'}

        for key in keys:
            gd = self._grids[key]
            g = gd['grid']
            ext = self._get_extent(gd)
            ny, nx = g.shape
            x = np.linspace(ext[0], ext[1], nx)
            y = np.linspace(ext[2], ext[3], ny)
            X, Y = np.meshgrid(x, y)
            safe = np.nan_to_num(g, nan=np.nanmean(g) if not np.all(np.isnan(g)) else 0)
            cs = ax.contour(X, Y, safe, levels=15, colors=colors_map.get(key, 'white'),
                            linestyles=line_styles.get(key, '-'), linewidths=0.8)
            ax.clabel(cs, inline=True, fontsize=6, fmt='%.2f')

        ax.set_xlabel('X (m)'); ax.set_ylabel('Y (m)')
        ax.set_title('Contour Overlay')
        ax.set_aspect('equal')
        from matplotlib.lines import Line2D
        legend_items = [Line2D([0], [0], color=colors_map.get(k, 'white'),
                               linestyle=line_styles.get(k, '-'), label=k.capitalize())
                        for k in keys]
        ax.legend(handles=legend_items, fontsize=8)

    def _plot_3d_surface(self, fig, cmap):
        keys = self._visible_keys()
        if not keys:
            return

        n = len(keys)
        alphas = {'before': 0.7, 'after': 0.8, 'target': 0.5}
        titles = {'before': 'Before', 'after': 'After', 'target': 'Target'}

        for i, key in enumerate(keys):
            ax = fig.add_subplot(1, n, i + 1, projection='3d')
            gd = self._grids[key]
            g = gd['grid']
            ext = self._get_extent(gd)
            ny, nx = g.shape
            x = np.linspace(ext[0], ext[1], nx)
            y = np.linspace(ext[2], ext[3], ny)
            X, Y = np.meshgrid(x, y)
            safe = np.nan_to_num(g, nan=np.nanmean(g) if not np.all(np.isnan(g)) else 0)

            stride = max(1, max(nx, ny) // 100)
            ax.plot_surface(X[::stride, ::stride], Y[::stride, ::stride], safe[::stride, ::stride],
                            cmap=cmap, alpha=alphas.get(key, 0.7), linewidth=0, antialiased=True)
            ax.set_xlabel('X'); ax.set_ylabel('Y'); ax.set_zlabel('Z')
            ax.set_title(titles.get(key, key), fontsize=9)

    def _plot_difference(self, fig, cmap):
        if 'before' not in self._grids or 'after' not in self._grids:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, 'Before + After data required', ha='center', va='center',
                    fontsize=12, transform=ax.transAxes, color='orange')
            return

        from core.grid_converter import align_grids
        a, b = align_grids(self._grids['before'], self._grids['after'])
        diff = b['grid'] - a['grid']

        ax = fig.add_subplot(111)
        vmax = max(abs(np.nanmin(diff)), abs(np.nanmax(diff)), 0.01)
        im = ax.imshow(diff, cmap='RdBu_r', aspect='equal', vmin=-vmax, vmax=vmax,
                       extent=self._get_extent(a), origin='lower')
        ax.set_title('Height Change (After - Before)\nBlue=excavated, Red=filled', fontsize=10)
        ax.set_xlabel('X (m)'); ax.set_ylabel('Y (m)')
        fig.colorbar(im, ax=ax, label='ΔHeight (m)')

    def _plot_error(self, fig, cmap):
        if 'after' not in self._grids or 'target' not in self._grids:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, 'After + Target data required', ha='center', va='center',
                    fontsize=12, transform=ax.transAxes, color='orange')
            return

        from core.grid_converter import align_grids
        a, t = align_grids(self._grids['after'], self._grids['target'])
        error = a['grid'] - t['grid']

        ax = fig.add_subplot(111)
        vmax = max(abs(np.nanmin(error)), abs(np.nanmax(error)), 0.01)
        im = ax.imshow(error, cmap='RdBu_r', aspect='equal', vmin=-vmax, vmax=vmax,
                       extent=self._get_extent(a), origin='lower')
        ax.set_title('Error (Actual - Target)\nBlue=under-excavated, Red=over-excavated', fontsize=10)
        ax.set_xlabel('X (m)'); ax.set_ylabel('Y (m)')
        fig.colorbar(im, ax=ax, label='Error (m)')

    def _plot_volume_3d(self, fig):
        if 'before' not in self._grids or 'after' not in self._grids:
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, 'Before + After data required', ha='center', va='center',
                    fontsize=12, transform=ax.transAxes, color='orange')
            return

        from core.grid_converter import align_grids
        a, b = align_grids(self._grids['before'], self._grids['after'])
        diff = b['grid'] - a['grid']
        ext = self._get_extent(a)
        ny, nx = diff.shape
        x = np.linspace(ext[0], ext[1], nx)
        y = np.linspace(ext[2], ext[3], ny)
        X, Y = np.meshgrid(x, y)
        safe_diff = np.nan_to_num(diff, nan=0)

        ax = fig.add_subplot(111, projection='3d')
        cut_mask = safe_diff < -0.01
        fill_mask = safe_diff > 0.01

        stride = max(1, max(nx, ny) // 80)
        Xs, Ys = X[::stride, ::stride], Y[::stride, ::stride]
        Ds = safe_diff[::stride, ::stride]

        colors = np.ones((*Ds.shape, 4))
        colors[Ds < -0.01] = [1, 0.4, 0, 0.7]
        colors[Ds > 0.01] = [0, 0.6, 1, 0.7]
        colors[(Ds >= -0.01) & (Ds <= 0.01)] = [0.5, 0.5, 0.5, 0.2]

        ax.plot_surface(Xs, Ys, Ds, facecolors=colors, linewidth=0, antialiased=True, shade=False)
        ax.set_xlabel('X (m)'); ax.set_ylabel('Y (m)'); ax.set_zlabel('ΔZ (m)')
        ax.set_title('Volume 3D: Orange=Cut, Blue=Fill', fontsize=10)
