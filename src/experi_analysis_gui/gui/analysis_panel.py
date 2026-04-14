import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QTextEdit, QTabWidget, QSpinBox, QCheckBox,
    QFileDialog, QMessageBox, QSplitter, QComboBox
)
from PyQt5.QtCore import pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class AnalysisPanel(QWidget):
    analysis_complete = pyqtSignal(object)

    def __init__(self, data_panel, parent=None):
        super().__init__(parent)
        self.data_panel = data_panel
        self._report = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        btn_row = QHBoxLayout()

        workflow_label = QLabel(
            "권장 순서: ① Load Before/After → ② Level All → ③ Global ROI → ④ ICP (After→Before) → ⑤ Generate Target → ⑥ Run Analysis")
        workflow_label.setStyleSheet("color: #888; font-size: 9px; padding: 2px;")
        workflow_label.setWordWrap(True)
        layout.addWidget(workflow_label)

        self.btn_run = QPushButton("Run Full Analysis")
        self.btn_run.setStyleSheet("font-weight: bold; padding: 8px; background: #2196F3; color: white;")
        self.btn_run.setToolTip("Before / After / Target 간\n모든 metric 계산 실행")
        self.btn_run.clicked.connect(self.run_analysis)
        btn_row.addWidget(self.btn_run)

        self.btn_export = QPushButton("Export Report")
        self.btn_export.setToolTip("텍스트 리포트 + 그래프 이미지를 파일로 저장")
        self.btn_export.clicked.connect(self.export_report)
        btn_row.addWidget(self.btn_export)

        layout.addLayout(btn_row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Sections:"))
        self.n_sections_spin = QSpinBox()
        self.n_sections_spin.setRange(1, 20)
        self.n_sections_spin.setValue(5)
        options_row.addWidget(self.n_sections_spin)

        options_row.addWidget(QLabel("Axis:"))
        self.section_axis_combo = QComboBox()
        self.section_axis_combo.addItems(["Y (가로 단면)", "X (세로 단면)"])
        options_row.addWidget(self.section_axis_combo)
        options_row.addStretch()
        layout.addLayout(options_row)

        self.tabs = QTabWidget()

        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setFontFamily("Courier")
        self.tabs.addTab(self.report_text, "Report")

        self.heatmap_canvas = FigureCanvas(Figure(figsize=(8, 6)))
        self.tabs.addTab(self.heatmap_canvas, "Heatmap")

        self.section_canvas = FigureCanvas(Figure(figsize=(8, 6)))
        self.tabs.addTab(self.section_canvas, "Cross-Sections")

        self.histogram_canvas = FigureCanvas(Figure(figsize=(8, 6)))
        self.tabs.addTab(self.histogram_canvas, "Histogram")

        self.comparison_canvas = FigureCanvas(Figure(figsize=(8, 6)))
        self.tabs.addTab(self.comparison_canvas, "Comparison")

        layout.addWidget(self.tabs, stretch=1)

    def run_analysis(self):
        before_grid = self.data_panel.get_grid_data('before')
        after_grid = self.data_panel.get_grid_data('after')

        if before_grid is None or after_grid is None:
            QMessageBox.warning(self, "Warning",
                                "Before and After data are both required.\n"
                                "Load data or generate target first.")
            return

        target_grid = self.data_panel.get_grid_data('target')
        target_params = self.data_panel.get_target_params()

        try:
            from core.metrics import compute_full_report, format_report_text
            from core.grid_converter import align_grids

            section_axis = 'y' if self.section_axis_combo.currentIndex() == 0 else 'x'
            self._report = compute_full_report(
                before_grid, after_grid, target_grid, target_params,
                n_cross_sections=self.n_sections_spin.value(),
                section_axis=section_axis
            )

            report_text = format_report_text(self._report)
            self.report_text.setText(report_text)

            a_before, a_after = align_grids(before_grid, after_grid)
            self._plot_heatmap(a_before, a_after, target_grid)
            self._plot_cross_sections(a_before, a_after, target_grid)
            self._plot_histogram(a_before, a_after, target_grid)
            self._plot_comparison(a_before, a_after, target_grid)

            self.analysis_complete.emit(self._report)
            self.tabs.setCurrentIndex(0)

        except Exception as e:
            QMessageBox.critical(self, "Analysis Error", f"Analysis failed:\n{e}")
            import traceback
            traceback.print_exc()

    def _plot_heatmap(self, before, after, target=None):
        fig = self.heatmap_canvas.figure
        fig.clear()

        n_plots = 2 if target is None else 3

        ax1 = fig.add_subplot(1, n_plots, 1)
        diff = after['grid'] - before['grid']
        im1 = ax1.imshow(diff, cmap='RdBu_r', aspect='equal',
                         extent=[before['x_edges'][0], before['x_edges'][-1],
                                 before['y_edges'][0], before['y_edges'][-1]],
                         origin='lower')
        ax1.set_title('Depth Change\n(Before→After)')
        ax1.set_xlabel('X (m)')
        ax1.set_ylabel('Y (m)')
        fig.colorbar(im1, ax=ax1, label='Height Change (m)')

        ax2 = fig.add_subplot(1, n_plots, 2)
        im2 = ax2.imshow(after['grid'], cmap='terrain', aspect='equal',
                         extent=[before['x_edges'][0], before['x_edges'][-1],
                                 before['y_edges'][0], before['y_edges'][-1]],
                         origin='lower')
        ax2.set_title('After (Post-Work)')
        ax2.set_xlabel('X (m)')
        fig.colorbar(im2, ax=ax2, label='Height (m)')

        if target is not None:
            from core.grid_converter import align_grids
            a_after, a_target = align_grids(
                {'grid': after['grid'], 'resolution': after['resolution'], 'origin': after['origin'],
                 'x_edges': after.get('x_edges', np.array([])), 'y_edges': after.get('y_edges', np.array([]))},
                target)
            error = a_after['grid'] - a_target['grid']

            ax3 = fig.add_subplot(1, n_plots, 3)
            vmax = max(abs(np.nanmin(error)), abs(np.nanmax(error)))
            im3 = ax3.imshow(error, cmap='RdBu_r', aspect='equal',
                             vmin=-vmax, vmax=vmax,
                             extent=[a_after['x_edges'][0], a_after['x_edges'][-1],
                                     a_after['y_edges'][0], a_after['y_edges'][-1]],
                             origin='lower')
            ax3.set_title('Error\n(Actual vs Target)')
            ax3.set_xlabel('X (m)')
            fig.colorbar(im3, ax=ax3, label='Error (m)')

        fig.tight_layout()
        self.heatmap_canvas.draw()

    def _plot_cross_sections(self, before, after, target=None):
        fig = self.section_canvas.figure
        fig.clear()

        if self._report is None or not self._report.cross_sections:
            return

        n = len(self._report.cross_sections)
        cols = min(n, 3)
        rows = (n + cols - 1) // cols

        res = before['resolution']
        origin_y = before['origin'][1]

        a_target = None
        if target is not None:
            from core.grid_converter import align_grids
            _, a_target = align_grids(before, target)

        for i, cs_data in enumerate(self._report.cross_sections):
            ax = fig.add_subplot(rows, cols, i + 1)
            pos = cs_data['position']
            cs_m = cs_data['metrics']

            row_idx = int((pos - origin_y) / res)
            row_idx = np.clip(row_idx, 0, before['grid'].shape[0] - 1)
            x_vals = before.get('x_edges', np.arange(before['grid'].shape[1]) * res + before['origin'][0])

            pb = before['grid'][row_idx, :]
            pa = after['grid'][row_idx, :]

            ax.plot(x_vals, pb, 'b-', label='Before', linewidth=2)
            ax.plot(x_vals, pa, 'r-', label='After', linewidth=2)

            if a_target is not None:
                t_row = int((pos - a_target['origin'][1]) / a_target['resolution'])
                t_row = np.clip(t_row, 0, a_target['grid'].shape[0] - 1)
                t_x = a_target.get('x_edges', np.arange(a_target['grid'].shape[1]) * a_target['resolution'] + a_target['origin'][0])
                ax.plot(t_x, a_target['grid'][t_row, :], 'g--', label='Target', linewidth=2, alpha=0.8)

            ax.fill_between(x_vals, pb, pa, where=pb > pa, alpha=0.25, color='orange', label='Cut')
            ax.fill_between(x_vals, pb, pa, where=pb < pa, alpha=0.25, color='cyan', label='Fill')

            title = f"Section {i+1}  Y={pos:.1f}m"
            if cs_m.depth_at_section > 0:
                title += f"\nDepth={cs_m.depth_at_section:.2f}m  Width={cs_m.width_at_section:.2f}m"
            if cs_m.iou > 0:
                title += f"  IoU={cs_m.iou:.2f}"
            ax.set_title(title, fontsize=8, color='#ddd')
            ax.set_xlabel('X (m)', fontsize=8)
            ax.set_ylabel('Z (m)', fontsize=8)
            ax.grid(True, alpha=0.3)
            if i == 0:
                ax.legend(fontsize=7, loc='lower left')

        fig.tight_layout()
        self.section_canvas.draw()

    def _plot_histogram(self, before, after, target=None):
        fig = self.histogram_canvas.figure
        fig.clear()

        diff = after['grid'] - before['grid']
        valid = ~np.isnan(diff)
        depths = -diff[valid]

        ax1 = fig.add_subplot(1, 2, 1)
        ax1.hist(depths[depths > 0], bins=50, color='steelblue', alpha=0.7, edgecolor='black')
        ax1.set_title('Excavation Depth Distribution')
        ax1.set_xlabel('Depth (m)')
        ax1.set_ylabel('Cell Count')
        ax1.axvline(np.mean(depths[depths > 0]) if (depths > 0).any() else 0,
                     color='red', linestyle='--', label='Mean')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        if target is not None:
            from core.grid_converter import align_grids
            a_after, a_target = align_grids(
                {'grid': after['grid'], 'resolution': after['resolution'], 'origin': after['origin'],
                 'x_edges': after.get('x_edges', np.array([])), 'y_edges': after.get('y_edges', np.array([]))},
                target)
            error = a_after['grid'] - a_target['grid']
            valid_e = ~np.isnan(error)

            ax2 = fig.add_subplot(1, 2, 2)
            ax2.hist(error[valid_e], bins=50, color='coral', alpha=0.7, edgecolor='black')
            ax2.set_title('Error Distribution\n(Actual - Target)')
            ax2.set_xlabel('Error (m)')
            ax2.set_ylabel('Cell Count')
            ax2.axvline(0, color='green', linestyle='-', linewidth=2, label='Zero Error')
            ax2.axvline(np.mean(error[valid_e]), color='red', linestyle='--', label='Mean Error')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
        else:
            ax2 = fig.add_subplot(1, 2, 2)
            ax2.text(0.5, 0.5, 'Load target data\nfor error analysis',
                     ha='center', va='center', fontsize=12, transform=ax2.transAxes)

        fig.tight_layout()
        self.histogram_canvas.draw()

    def _plot_comparison(self, before, after, target=None):
        fig = self.comparison_canvas.figure
        fig.clear()

        if self._report is None:
            return

        ax = fig.add_subplot(1, 1, 1)

        categories = ['RMSE', 'MAE', 'Max Err', 'Median', '95th %']
        g = self._report.geometric
        values = [g.rmse, g.mae, g.max_error, g.median_error, g.percentile_95]

        bars = ax.bar(categories, values, color=['#2196F3', '#4CAF50', '#F44336', '#FF9800', '#9C27B0'],
                      alpha=0.8, edgecolor='black')

        for bar_item, val in zip(bars, values):
            ax.text(bar_item.get_x() + bar_item.get_width() / 2, bar_item.get_height() + 0.001,
                    f'{val:.4f}m', ha='center', va='bottom', fontsize=9, fontweight='bold')

        ax.set_title('Geometric Accuracy Metrics')
        ax.set_ylabel('Error (m)')
        ax.grid(True, alpha=0.3, axis='y')

        fig.tight_layout()
        self.comparison_canvas.draw()

    def export_report(self):
        if self._report is None:
            QMessageBox.warning(self, "Warning", "Run analysis first.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Report", "excavation_report.txt",
            "Text Files (*.txt);;All Files (*)")
        if not filepath:
            return

        from core.metrics import format_report_text
        report_text = format_report_text(self._report)
        with open(filepath, 'w') as f:
            f.write(report_text)

        fig_base = filepath.rsplit('.', 1)[0]
        self.heatmap_canvas.figure.savefig(f"{fig_base}_heatmap.png", dpi=150, bbox_inches='tight')
        self.section_canvas.figure.savefig(f"{fig_base}_sections.png", dpi=150, bbox_inches='tight')
        self.histogram_canvas.figure.savefig(f"{fig_base}_histogram.png", dpi=150, bbox_inches='tight')
        self.comparison_canvas.figure.savefig(f"{fig_base}_comparison.png", dpi=150, bbox_inches='tight')

        QMessageBox.information(self, "Exported",
                                f"Report exported to:\n{filepath}\n"
                                f"+ 4 plot images")
