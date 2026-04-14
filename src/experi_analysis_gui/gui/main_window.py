import sys
import json
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QAction, QMenuBar, QStatusBar, QLabel,
    QMessageBox, QFileDialog, QDockWidget, QProgressBar
)
from PyQt5.QtCore import Qt
import numpy as np

from gui.data_panel import DataPanel
from gui.viewer_3d import PointCloudViewer3D
from gui.analysis_panel import AnalysisPanel
from gui.comparison_panel import ComparisonPanel
from gui.gridmap_viewer import GridMapViewer


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Excavation Analysis Tool - Point Cloud & Grid Comparison")
        self.setMinimumSize(1400, 800)
        self._init_menu()
        self._init_ui()
        self._init_statusbar()

    def _init_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        act_load_before = QAction("Load Before Data...", self)
        act_load_before.setShortcut("Ctrl+1")
        file_menu.addAction(act_load_before)

        act_load_after = QAction("Load After Data...", self)
        act_load_after.setShortcut("Ctrl+2")
        file_menu.addAction(act_load_after)

        act_load_target = QAction("Load Target Data...", self)
        act_load_target.setShortcut("Ctrl+3")
        file_menu.addAction(act_load_target)

        file_menu.addSeparator()

        act_save_session = QAction("Save Session...", self)
        act_save_session.setShortcut("Ctrl+S")
        act_save_session.triggered.connect(self._save_session)
        file_menu.addAction(act_save_session)

        act_load_session = QAction("Load Session...", self)
        act_load_session.setShortcut("Ctrl+O")
        act_load_session.triggered.connect(self._load_session)
        file_menu.addAction(act_load_session)

        file_menu.addSeparator()

        act_export = QAction("Export Report...", self)
        act_export.setShortcut("Ctrl+E")
        file_menu.addAction(act_export)

        act_export_pdf = QAction("Export PDF Report...", self)
        act_export_pdf.triggered.connect(self._export_pdf)
        file_menu.addAction(act_export_pdf)

        file_menu.addSeparator()

        act_quit = QAction("Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        view_menu = menubar.addMenu("View")
        act_reset_view = QAction("Reset 3D View", self)
        act_reset_view.setShortcut("Ctrl+R")
        view_menu.addAction(act_reset_view)

        act_top = QAction("Top View", self)
        view_menu.addAction(act_top)
        act_front = QAction("Front View", self)
        view_menu.addAction(act_front)

        analysis_menu = menubar.addMenu("Analysis")
        act_run = QAction("Run Full Analysis", self)
        act_run.setShortcut("Ctrl+Return")
        analysis_menu.addAction(act_run)

        act_generate_sample = QAction("Generate Sample Data", self)
        analysis_menu.addAction(act_generate_sample)
        act_generate_sample.triggered.connect(self._generate_sample_data)

        analysis_menu.addSeparator()
        act_timeline = QAction("Timeline Viewer...", self)
        act_timeline.triggered.connect(self._open_timeline)
        analysis_menu.addAction(act_timeline)

        act_kine = QAction("Kinematics Viewer...", self)
        act_kine.triggered.connect(self._open_kinematics)
        analysis_menu.addAction(act_kine)

        help_menu = menubar.addMenu("Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

        act_metrics_info = QAction("Metrics Reference", self)
        act_metrics_info.triggered.connect(self._show_metrics_info)
        help_menu.addAction(act_metrics_info)

        act_run.triggered.connect(lambda: self.analysis_panel.run_analysis())
        act_reset_view.triggered.connect(lambda: self.viewer_3d.reset_view())
        act_top.triggered.connect(lambda: self.viewer_3d.set_view('top'))
        act_front.triggered.connect(lambda: self.viewer_3d.set_view('front'))
        act_export.triggered.connect(lambda: self.analysis_panel.export_report())

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_splitter = QSplitter(Qt.Horizontal)

        self.data_panel = DataPanel()
        self.data_panel.setMinimumWidth(320)
        self.data_panel.setMaximumWidth(450)
        self.data_panel.data_loaded.connect(self._on_data_loaded)
        self.data_panel.data_cleared.connect(self._on_data_cleared)
        self.data_panel.visibility_changed.connect(self._on_visibility_changed)

        right_splitter = QSplitter(Qt.Vertical)

        from PyQt5.QtWidgets import QTabWidget

        top_tabs = QTabWidget()
        self.viewer_3d = PointCloudViewer3D()
        top_tabs.addTab(self.viewer_3d, "3D Point Cloud")

        self.gridmap_viewer = GridMapViewer()
        top_tabs.addTab(self.gridmap_viewer, "2.5D Grid Map")

        self.analysis_panel = AnalysisPanel(self.data_panel)

        bottom_tabs = QTabWidget()
        bottom_tabs.addTab(self.analysis_panel, "Analysis")

        self.comparison_panel = ComparisonPanel()
        self.comparison_panel.set_analysis_panel(self.analysis_panel)
        bottom_tabs.addTab(self.comparison_panel, "Experiment Comparison")

        right_splitter.addWidget(top_tabs)
        right_splitter.addWidget(bottom_tabs)
        right_splitter.setSizes([500, 400])

        main_splitter.addWidget(self.data_panel)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([300, 1100])

        layout = QHBoxLayout(central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(main_splitter)

    def _init_statusbar(self):
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().showMessage("Ready - Load data to begin analysis")

    def show_progress(self, value: int, maximum: int = 100, text: str = ""):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(value < maximum)
        if text:
            self.statusBar().showMessage(text)

    def _on_data_loaded(self, key: str, data, data_type: str):
        color_map = {
            'before': (0.3, 0.3, 1.0, 0.8),
            'after': (1.0, 0.3, 0.3, 0.8),
            'target': (0.3, 1.0, 0.3, 0.6),
        }

        if data_type == 'pointcloud':
            self.viewer_3d.add_pointcloud(key, data, color=color_map.get(key))
            self.viewer_3d.auto_center()
            self.statusBar().showMessage(f"Loaded {key}: {len(data)} points")

            self._update_gridmap_viewer(key, data, 'pointcloud')

        elif data_type == 'grid':
            from core.grid_converter import grid_to_pointcloud
            points = grid_to_pointcloud(data)
            if len(points) > 0:
                self.viewer_3d.add_pointcloud(key, points, color=color_map.get(key))
                self.viewer_3d.auto_center()

            self.gridmap_viewer.set_grid(key, data)
            self.statusBar().showMessage(f"Loaded {key}: {data['grid'].shape} grid")

    def _update_gridmap_viewer(self, key: str, data, data_type: str):
        if data_type == 'pointcloud':
            res = self.data_panel.grid_resolution_spin.value()
            from core.grid_converter import pointcloud_to_grid_binned
            try:
                grid_data = pointcloud_to_grid_binned(data, resolution=res, aggregation='mean')
                self.gridmap_viewer.set_grid(key, grid_data)
            except Exception:
                pass
        elif data_type == 'grid':
            self.gridmap_viewer.set_grid(key, data)

    def _on_data_cleared(self, key: str):
        self.viewer_3d.remove_pointcloud(key)
        self.gridmap_viewer.remove_grid(key)
        self.statusBar().showMessage(f"Cleared {key} data")

    def _on_visibility_changed(self, key: str, visible: bool):
        self.viewer_3d.set_pointcloud_visible(key, visible)

    def _generate_sample_data(self):
        try:
            from sample_data.generate_samples import generate_full_sample
            before, after, target = generate_full_sample()

            self.data_panel._loaded_data['before'] = {'type': 'grid', 'data': before, 'path': 'sample'}
            self.data_panel._loaded_data['after'] = {'type': 'grid', 'data': after, 'path': 'sample'}
            self.data_panel._loaded_data['target'] = {'type': 'grid', 'data': target, 'path': 'sample'}

            self.data_panel._update_info_label('before', "Grid (sample): flat terrain")
            self.data_panel._update_info_label('after', "Grid (sample): excavated (noisy)")
            self.data_panel._update_info_label('target', "Grid (sample): ideal trench")

            self._on_data_loaded('before', before, 'grid')
            self._on_data_loaded('after', after, 'grid')
            self._on_data_loaded('target', target, 'grid')

            self.statusBar().showMessage("Sample data generated - ready for analysis")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Sample generation failed: {e}")
            import traceback
            traceback.print_exc()

    def _show_about(self):
        QMessageBox.about(self, "About",
            "Excavation Analysis Tool v1.0\n\n"
            "Autonomous Excavator Performance Evaluation\n"
            "Point Cloud & Grid Map Comparison Tool\n\n"
            "Metrics based on:\n"
            "- RMSE, MAE, Hausdorff Distance\n"
            "- Chamfer Distance (DCD variant)\n"
            "- Cut/Fill Volume Analysis\n"
            "- Cross-Section IoU\n"
            "- Surface Roughness (Ra, Rq)\n\n"
            "References:\n"
            "- Density Aware Chamfer Distance (arXiv:2511.02994)\n"
            "- Slope Excavation Quality Assessment (KSCE 2019)\n"
            "- Earthwork Volume Estimation (ISARC 2021)")

    def _show_metrics_info(self):
        info = (
            "=== METRIC REFERENCE ===\n\n"
            "[Geometric Accuracy]\n"
            "  RMSE: Root Mean Square Error of height differences\n"
            "  MAE: Mean Absolute Error\n"
            "  Hausdorff: Maximum nearest-point distance (worst case)\n"
            "  Chamfer: Average bidirectional squared nearest distance\n"
            "  95th Percentile: 95% of errors below this value\n\n"
            "[Volume Analysis]\n"
            "  Cut Volume: Total excavated volume (m^3)\n"
            "  Fill Volume: Total filled volume (m^3)\n"
            "  Volume Accuracy: (Actual cut / Target cut) x 100%\n"
            "  Over-excavation: Volume excavated beyond target\n"
            "  Under-excavation: Volume remaining un-excavated\n\n"
            "[Excavation Specifics]\n"
            "  Depth Mean/Std/Min/Max: Excavation depth statistics\n"
            "  Width: Average width of excavated region\n"
            "  Bottom Flatness: Std dev of bottom surface height\n"
            "  Completeness: % of target area properly excavated\n"
            "  Precision: % of excavated area within target boundary\n\n"
            "[Surface Quality]\n"
            "  Roughness Ra: Average absolute deviation from smooth\n"
            "  Roughness Rq: RMS deviation from smooth surface\n"
            "  Slope Consistency: 1.0 = perfect slope match\n\n"
            "[Cross-Section]\n"
            "  IoU: Intersection over Union of section profile areas\n"
            "  Profile RMSE: Height error along section line"
        )
        QMessageBox.information(self, "Metrics Reference", info)

    def _open_timeline(self):
        bag_path = self.data_panel._last_load_params.get('bag_path', '')
        if not bag_path:
            QMessageBox.warning(self, "Warning", "먼저 ROS2 bag에서 데이터를 로드하세요.")
            return
        topic = self.data_panel._last_load_params.get('topic', '/lidar_boom/points')
        tf_frame = self.data_panel._last_load_params.get('tf_frame', '')
        try:
            from core.rosbag_loader import count_frames
            n = count_frames(bag_path, topic)
            pc_frame = self.data_panel._detect_pc_frame_id(bag_path, topic)
            from gui.timeline_dialog import TimelineDialog
            dlg = TimelineDialog(bag_path, topic, pc_frame, tf_frame, n, parent=self)
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Timeline failed:\n{e}")

    def _open_kinematics(self):
        bag_path = self.data_panel._last_load_params.get('bag_path', '')
        if not bag_path:
            QMessageBox.warning(self, "Warning", "먼저 ROS2 bag에서 데이터를 로드하세요.")
            return
        try:
            from gui.kinematics_dialog import KinematicsDialog
            dlg = KinematicsDialog(bag_path, parent=self)
            dlg.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Kinematics failed:\n{e}")

    def _save_session(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "", "JSON (*.json);;All Files (*)")
        if not filepath:
            return
        try:
            from core.session_manager import save_session
            report = self.analysis_panel._report
            data_info = {}
            for key in ['before', 'after', 'target']:
                d = self.data_panel.get_data(key)
                if d:
                    n = len(d['data']) if hasattr(d['data'], '__len__') else 0
                    data_info[key] = {'type': d['type'], 'path': d.get('path', ''), 'n_points': n}
            params = self.data_panel.get_target_params()
            save_session(filepath, report, data_info, params)
            self.statusBar().showMessage(f"Session saved: {filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")

    def _load_session(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "", "JSON (*.json);;All Files (*)")
        if not filepath:
            return
        try:
            from core.session_manager import load_session
            session = load_session(filepath)
            if session.get('report'):
                self.analysis_panel.report_text.setText(
                    json.dumps(session['report'], indent=2, ensure_ascii=False))
            self.statusBar().showMessage(f"Session loaded: {filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Load failed:\n{e}")

    def _export_pdf(self):
        if self.analysis_panel._report is None:
            QMessageBox.warning(self, "Warning", "Run analysis first.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export PDF Report", "report.pdf", "PDF (*.pdf)")
        if not filepath:
            return
        try:
            from matplotlib.backends.backend_pdf import PdfPages
            from core.metrics import format_report_text
            with PdfPages(filepath) as pdf:
                from matplotlib.figure import Figure
                fig_text = Figure(figsize=(8.5, 11))
                ax = fig_text.add_subplot(111)
                ax.axis('off')
                report_str = format_report_text(self.analysis_panel._report)
                ax.text(0.05, 0.95, report_str, transform=ax.transAxes,
                        fontsize=7, verticalalignment='top', fontfamily='monospace')
                pdf.savefig(fig_text)

                for canvas in [self.analysis_panel.heatmap_canvas,
                               self.analysis_panel.section_canvas,
                               self.analysis_panel.histogram_canvas,
                               self.analysis_panel.comparison_canvas]:
                    pdf.savefig(canvas.figure)

            self.statusBar().showMessage(f"PDF exported: {filepath}")
            QMessageBox.information(self, "Done", f"PDF exported:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"PDF export failed:\n{e}")
