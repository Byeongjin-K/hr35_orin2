import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QHeaderView, QTabWidget, QLineEdit, QComboBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class ComparisonPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._experiments = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        ctrl_row = QHBoxLayout()

        self.exp_name_input = QLineEdit()
        self.exp_name_input.setPlaceholderText("Experiment name (e.g. Model_A)")
        self.exp_name_input.setToolTip("현재 분석 결과에 붙일\n실험 이름을 입력하세요")
        ctrl_row.addWidget(self.exp_name_input)

        btn_add = QPushButton("Add Current Result")
        btn_add.setStyleSheet("background: #4CAF50; color: white; font-weight: bold;")
        btn_add.setToolTip("현재 분석 결과를 입력한\n실험 이름으로 비교 목록에 추가")
        btn_add.clicked.connect(self._add_current_experiment)
        ctrl_row.addWidget(btn_add)

        btn_remove = QPushButton("Remove Selected")
        btn_remove.setToolTip("선택한 실험 열을\n비교 목록에서 제거")
        btn_remove.clicked.connect(self._remove_selected)
        ctrl_row.addWidget(btn_remove)

        btn_clear = QPushButton("Clear All")
        btn_clear.setToolTip("모든 실험을 비교 목록에서 제거")
        btn_clear.clicked.connect(self._clear_all)
        ctrl_row.addWidget(btn_clear)

        btn_export = QPushButton("Export CSV")
        btn_export.setToolTip("비교 테이블을 CSV 파일로 내보내기")
        btn_export.clicked.connect(self._export_csv)
        ctrl_row.addWidget(btn_export)

        layout.addLayout(ctrl_row)

        self.tabs = QTabWidget()

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabs.addTab(self.table, "Metric Table")

        self.radar_canvas = FigureCanvas(Figure(figsize=(8, 6)))
        self.tabs.addTab(self.radar_canvas, "Radar Chart")

        self.bar_canvas = FigureCanvas(Figure(figsize=(8, 6)))
        self.tabs.addTab(self.bar_canvas, "Bar Comparison")

        layout.addWidget(self.tabs, stretch=1)

    def set_analysis_panel(self, analysis_panel):
        self._analysis_panel = analysis_panel

    def _add_current_experiment(self):
        if not hasattr(self, '_analysis_panel') or self._analysis_panel._report is None:
            QMessageBox.warning(self, "Warning", "Run analysis first before adding to comparison.")
            return

        name = self.exp_name_input.text().strip()
        if not name:
            count = len(self._experiments) + 1
            name = f"Experiment_{count}"

        report = self._analysis_panel._report
        self._experiments[name] = self._extract_metrics(report)
        self._update_table()
        self._update_radar_chart()
        self._update_bar_chart()
        self.exp_name_input.clear()

    def _extract_metrics(self, report):
        g = report.geometric
        v = report.volume
        e = report.excavation
        s = report.surface

        return {
            'RMSE (m)': g.rmse,
            'MAE (m)': g.mae,
            'Max Error (m)': g.max_error,
            '95th Pctl (m)': g.percentile_95,
            'Cut Vol (m³)': v.cut_volume,
            'Vol Accuracy (%)': v.volume_accuracy,
            'Over-exc (%)': v.over_excavation_ratio,
            'Under-exc (%)': v.under_excavation_ratio,
            'Depth Mean (m)': e.depth_mean,
            'Depth RMSE (m)': e.depth_error_rmse,
            'Width Error (m)': abs(e.width_error),
            'Flatness (m)': e.bottom_flatness,
            'Completeness (%)': e.completeness,
            'Precision (%)': e.precision,
            'Roughness Ra (m)': s.roughness_ra,
            'Slope Consist.': s.slope_consistency,
        }

    def _update_table(self):
        if not self._experiments:
            self.table.clear()
            return

        exp_names = list(self._experiments.keys())
        metric_names = list(next(iter(self._experiments.values())).keys())

        self.table.setRowCount(len(metric_names))
        self.table.setColumnCount(len(exp_names) + 1)
        self.table.setHorizontalHeaderLabels(["Metric"] + exp_names)

        LOWER_IS_BETTER = {
            'RMSE (m)', 'MAE (m)', 'Max Error (m)', '95th Pctl (m)',
            'Over-exc (%)', 'Under-exc (%)', 'Depth RMSE (m)',
            'Width Error (m)', 'Flatness (m)', 'Roughness Ra (m)'
        }

        for row, metric in enumerate(metric_names):
            self.table.setItem(row, 0, QTableWidgetItem(metric))

            values = [self._experiments[name].get(metric, 0) for name in exp_names]
            valid_values = [v for v in values if v != 0 and not np.isnan(v)]

            for col, name in enumerate(exp_names):
                val = self._experiments[name].get(metric, 0)
                item = QTableWidgetItem(f"{val:.4f}")
                item.setTextAlignment(Qt.AlignCenter)

                if len(valid_values) >= 2:
                    is_lower_better = metric in LOWER_IS_BETTER
                    best = min(valid_values) if is_lower_better else max(valid_values)
                    worst = max(valid_values) if is_lower_better else min(valid_values)

                    if val == best:
                        item.setBackground(QColor(76, 175, 80, 80))
                    elif val == worst:
                        item.setBackground(QColor(244, 67, 54, 80))

                self.table.setItem(row, col + 1, item)

    def _update_radar_chart(self):
        fig = self.radar_canvas.figure
        fig.clear()

        if len(self._experiments) < 1:
            self.radar_canvas.draw()
            return

        radar_metrics = [
            'RMSE (m)', 'MAE (m)', 'Vol Accuracy (%)',
            'Completeness (%)', 'Precision (%)', 'Slope Consist.'
        ]

        exp_names = list(self._experiments.keys())
        angles = np.linspace(0, 2 * np.pi, len(radar_metrics), endpoint=False).tolist()
        angles.append(angles[0])

        ax = fig.add_subplot(111, polar=True)
        colors = ['#2196F3', '#4CAF50', '#F44336', '#FF9800', '#9C27B0',
                  '#00BCD4', '#795548', '#607D8B']

        for idx, name in enumerate(exp_names):
            values = []
            for m in radar_metrics:
                val = self._experiments[name].get(m, 0)
                if '%' in m:
                    val = val / 100.0
                elif m == 'Slope Consist.':
                    pass
                else:
                    val = max(0, 1.0 - val * 10)
                values.append(np.clip(val, 0, 1))
            values.append(values[0])

            color = colors[idx % len(colors)]
            ax.plot(angles, values, 'o-', linewidth=2, label=name, color=color)
            ax.fill(angles, values, alpha=0.15, color=color)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(radar_metrics, fontsize=8)
        ax.set_ylim(0, 1)
        ax.set_title('Performance Comparison (higher = better)', fontsize=10, pad=20)
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=8)

        fig.tight_layout()
        self.radar_canvas.draw()

    def _update_bar_chart(self):
        fig = self.bar_canvas.figure
        fig.clear()

        if len(self._experiments) < 1:
            self.bar_canvas.draw()
            return

        bar_metrics = ['RMSE (m)', 'MAE (m)', 'Max Error (m)', 'Depth RMSE (m)', 'Flatness (m)']
        exp_names = list(self._experiments.keys())

        x = np.arange(len(bar_metrics))
        width = 0.8 / max(len(exp_names), 1)
        colors = ['#2196F3', '#4CAF50', '#F44336', '#FF9800', '#9C27B0',
                  '#00BCD4', '#795548', '#607D8B']

        ax = fig.add_subplot(111)
        for idx, name in enumerate(exp_names):
            values = [self._experiments[name].get(m, 0) for m in bar_metrics]
            offset = (idx - len(exp_names) / 2 + 0.5) * width
            bars = ax.bar(x + offset, values, width * 0.9,
                          label=name, color=colors[idx % len(colors)], alpha=0.8)
            for bar_item, val in zip(bars, values):
                if val > 0:
                    ax.text(bar_item.get_x() + bar_item.get_width() / 2,
                            bar_item.get_height(), f'{val:.3f}',
                            ha='center', va='bottom', fontsize=7)

        ax.set_xticks(x)
        ax.set_xticklabels(bar_metrics, fontsize=9)
        ax.set_ylabel('Error (m)')
        ax.set_title('Error Metrics Comparison')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, axis='y')

        fig.tight_layout()
        self.bar_canvas.draw()

    def _remove_selected(self):
        rows = set(item.row() for item in self.table.selectedItems())
        if not rows:
            selected_col = self.table.currentColumn()
            if selected_col > 0:
                name = self.table.horizontalHeaderItem(selected_col).text()
                if name in self._experiments:
                    del self._experiments[name]
                    self._update_table()
                    self._update_radar_chart()
                    self._update_bar_chart()

    def _clear_all(self):
        self._experiments.clear()
        self._update_table()
        self._update_radar_chart()
        self._update_bar_chart()

    def _export_csv(self):
        if not self._experiments:
            QMessageBox.warning(self, "Warning", "No experiments to export.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Comparison CSV", "comparison.csv", "CSV Files (*.csv)")
        if not filepath:
            return

        exp_names = list(self._experiments.keys())
        metric_names = list(next(iter(self._experiments.values())).keys())

        with open(filepath, 'w') as f:
            f.write("Metric," + ",".join(exp_names) + "\n")
            for metric in metric_names:
                values = [f"{self._experiments[name].get(metric, 0):.6f}" for name in exp_names]
                f.write(f"{metric}," + ",".join(values) + "\n")

        QMessageBox.information(self, "Exported", f"Comparison exported to:\n{filepath}")
