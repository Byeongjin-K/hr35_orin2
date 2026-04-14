import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QFileDialog, QComboBox, QDoubleSpinBox, QCheckBox,
    QMessageBox, QLineEdit, QSpinBox, QScrollArea, QDialog,
    QTextBrowser, QTabWidget
)
from PyQt5.QtCore import pyqtSignal, Qt
import numpy as np
from scipy.spatial.transform import Rotation


POINT_CLOUD_FILTER = "Point Cloud (*.pcd *.csv *.txt *.las *.laz *.npy *.npz *.ply);;All Files (*)"
GRID_MAP_FILTER = "Grid Map (*.npy *.npz *.csv *.txt);;All Files (*)"

HELP_HTML = """
<h2 style="color:#64B5F6;">굴착 작업 분석 도구</h2>
<p>LiDAR 포인트 클라우드 또는 2D 그리드 맵 데이터를 이용하여 굴착 작업 결과를 목표 지형과 비교/분석하는 도구입니다.</p>
<hr style="border-color:#555;">

<h3 style="color:#81C784;">1. 데이터 로드 (왼쪽 패널)</h3>
<table style="color:#ddd; margin-left:10px;">
<tr><td style="color:#90CAF9; padding-right:12px;"><b>Before (작업 전)</b></td>
    <td>굴착 <b>이전</b>의 지형. 기준이 되는 원래 지면 상태입니다.</td></tr>
<tr><td style="color:#EF9A9A; padding-right:12px;"><b>After (작업 후)</b></td>
    <td>굴착 <b>이후</b>의 지형. 평가 대상이 되는 실제 작업 결과입니다.</td></tr>
<tr><td style="color:#A5D6A7; padding-right:12px;"><b>Target (목표)</b></td>
    <td><b>이상적인</b> 굴착 결과 지형. 정확도 오차 계산의 기준이 됩니다.</td></tr>
</table>
<p style="margin-left:10px;">
<b>Load PC</b>: 포인트 클라우드 파일 로드 (PCD, CSV, TXT, LAS/LAZ, NPY, PLY)<br>
<b>Load Grid</b>: 미리 계산된 2D 높이 그리드 맵 로드 (NPY, NPZ, CSV)<br>
<b>ROS2 Bag</b>: ROS2 bag 파일에서 PointCloud2 토픽을 직접 추출<br>
</p>

<h3 style="color:#81C784;">2. 목표 지형 생성기 (Target Generator)</h3>
<p style="margin-left:10px;">실제 데이터 없이 이상적인 굴착 목표 지형을 생성합니다:</p>
<table style="color:#ddd; margin-left:10px;">
<tr><td style="color:#FFD54F; padding-right:12px;"><b>Trench (트렌치)</b></td>
    <td>직선 도랑 형태 (예: 배관 매설용). 파라미터: 깊이, 폭, 벽면 각도</td></tr>
<tr><td style="color:#FFD54F; padding-right:12px;"><b>Grading (평탄화)</b></td>
    <td>지면을 목표 높이로 균일하게 고르는 작업</td></tr>
<tr><td style="color:#FFD54F; padding-right:12px;"><b>Pit (구덩이)</b></td>
    <td>사각형/원형 구덩이. 파라미터: 깊이, 가로/세로 폭, 벽면 각도</td></tr>
<tr><td style="color:#FFD54F; padding-right:12px;"><b>Slope (사면)</b></td>
    <td>경사면 절토 작업. 파라미터: 상단/하단 높이</td></tr>
</table>
<p style="margin-left:10px;"><b>Generate Target</b> 버튼을 누르면 평탄한 "Before" 지형과 형상이 적용된 "Target" 지형이 자동 생성됩니다.</p>

<h3 style="color:#81C784;">3. 그리드 변환 (Grid Conversion)</h3>
<p style="margin-left:10px;">로드된 포인트 클라우드를 metric 계산을 위한 2D 높이 그리드로 변환합니다.<br>
<b>Resolution</b>: 그리드 셀 크기 (미터). 작을수록 정밀하지만 처리 속도가 느려집니다.<br>
<b>Interpolation</b>: linear (빠르고 부드러움), nearest (보간 없이 정확한 값), cubic (가장 부드럽지만 느림)</p>

<h3 style="color:#81C784;">4. 3D 뷰어 (우측 상단)</h3>
<p style="margin-left:10px;">
<b>시점 조작</b>: 좌클릭 드래그=회전, 우클릭 드래그=이동, 스크롤=확대/축소<br>
<b>Top/Front/Side</b>: 상단/정면/측면 시점으로 전환<br>
<b>측정 도구</b>: 3D 뷰에서 포인트를 클릭하여 거리를 측정합니다:
</p>
<table style="color:#ddd; margin-left:10px;">
<tr><td style="color:#FFD54F; padding-right:12px;"><b>Point-Point</b></td>
    <td>두 점을 클릭하여 3D 직선 거리 측정 + dx/dy/dz 분해값 표시</td></tr>
<tr><td style="color:#FFD54F; padding-right:12px;"><b>Path</b></td>
    <td>여러 점을 순서대로 클릭하여 누적 경로 거리 측정. 우클릭으로 종료</td></tr>
<tr><td style="color:#FFD54F; padding-right:12px;"><b>Height Diff</b></td>
    <td>두 점의 수직 높이차(Z)만 측정</td></tr>
</table>

<h3 style="color:#81C784;">5. 분석 (우측 하단 - Analysis 탭)</h3>
<p style="margin-left:10px;">
<b>Run Full Analysis</b>: Before/After/Target 간 모든 metric을 계산합니다.<br>
결과 탭 설명:<br>
&nbsp;&nbsp;<b>Report</b>: 모든 metric 수치가 포함된 텍스트 리포트<br>
&nbsp;&nbsp;<b>Heatmap</b>: 깊이 변화와 오차를 색상으로 표현한 히트맵<br>
&nbsp;&nbsp;<b>Cross-Sections</b>: Before/After/Target의 단면 프로파일 비교<br>
&nbsp;&nbsp;<b>Histogram</b>: 굴착 깊이 및 오차의 분포 히스토그램<br>
&nbsp;&nbsp;<b>Comparison</b>: 기하학적 정확도 metric의 막대 차트
</p>

<h3 style="color:#81C784;">6. 실험 비교 (우측 하단 - Experiment Comparison 탭)</h3>
<p style="margin-left:10px;">
여러 실험 결과를 나란히 비교합니다:<br>
1. 실험 A의 데이터를 로드하고 분석 실행<br>
2. 이름을 입력 (예: "숙련자_작업자")하고 <b>Add Current Result</b> 클릭<br>
3. 실험 B 데이터를 로드, 분석 실행, "모델_v1" 이름으로 추가<br>
4. 필요한 만큼 반복<br>
<b>Metric Table</b>: 각 metric별 최고값=초록색, 최저값=빨간색으로 강조 표시<br>
<b>Radar Chart</b>: 정규화된 성능 비교 레이더 차트<br>
<b>Bar Chart</b>: 오차 metric 직접 비교 막대 차트<br>
<b>Export CSV</b>: 비교 테이블을 CSV 파일로 저장
</p>

<h3 style="color:#81C784;">7. Metric 상세 설명</h3>
<table style="color:#ddd; margin-left:10px;">
<tr><td style="color:#90CAF9;"><b>RMSE</b></td><td>높이 차이의 평균 제곱근 오차 (전체적인 정확도)</td></tr>
<tr><td style="color:#90CAF9;"><b>MAE</b></td><td>높이 차이의 평균 절대 오차</td></tr>
<tr><td style="color:#90CAF9;"><b>Hausdorff</b></td><td>최대 근접점 거리 (최악의 경우 편차)</td></tr>
<tr><td style="color:#90CAF9;"><b>Chamfer</b></td><td>양방향 평균 제곱 근접 거리</td></tr>
<tr><td style="color:#90CAF9;"><b>Cut/Fill Vol</b></td><td>총 굴착/성토 체적 (m&sup3;)</td></tr>
<tr><td style="color:#90CAF9;"><b>Vol Accuracy</b></td><td>실제 굴착량 / 목표 굴착량 &times; 100%</td></tr>
<tr><td style="color:#90CAF9;"><b>Completeness</b></td><td>목표 영역 중 실제로 올바르게 굴착된 비율 (%)</td></tr>
<tr><td style="color:#90CAF9;"><b>Precision</b></td><td>실제 굴착 영역 중 목표 범위 이내인 비율 (%)</td></tr>
<tr><td style="color:#90CAF9;"><b>Bottom Flatness</b></td><td>바닥면 높이의 표준편차 (낮을수록 평탄)</td></tr>
<tr><td style="color:#90CAF9;"><b>Roughness Ra/Rq</b></td><td>표면 거칠기 (ISO 표준 지표)</td></tr>
<tr><td style="color:#90CAF9;"><b>Cross-Section IoU</b></td><td>단면 프로파일 면적의 교집합/합집합 비율</td></tr>
</table>

<h3 style="color:#81C784;">8. 빠른 시작</h3>
<p style="margin-left:10px;">
<b>메뉴 &gt; Analysis &gt; Generate Sample Data</b>를 클릭하면 데모용 트렌치 데이터가 즉시 로드됩니다.<br>
이후 <b>Run Full Analysis</b> 버튼을 눌러 모든 metric과 시각화 결과를 확인할 수 있습니다.
</p>
"""


class DataPanel(QWidget):
    data_loaded = pyqtSignal(str, object, str)
    data_cleared = pyqtSignal(str)
    visibility_changed = pyqtSignal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded_data = {}
        self._last_load_params = {}
        self._undo_stacks = {'before': [], 'after': [], 'target': []}
        self._redo_stacks = {'before': [], 'after': [], 'target': []}
        from PyQt5.QtCore import QSettings
        self._settings = QSettings("ExcavationAnalysis", "DataPanel")
        self._base_data_dir = self._settings.value("base_data_dir", "")
        self._init_ui()

    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(3)
        layout.setContentsMargins(2, 2, 2, 2)

        top_row = QHBoxLayout()
        btn_help = QPushButton("  ?  Help  ")
        btn_help.setToolTip("전체 도움말 보기")
        btn_help.setStyleSheet(
            "background: #FFD700; color: #222; font-weight: bold; "
            "font-size: 12px; padding: 4px 10px; border-radius: 4px;")
        btn_help.clicked.connect(self._show_help_dialog)
        top_row.addWidget(btn_help)

        btn_set_dir = QPushButton("📂 Data Folder")
        btn_set_dir.setToolTip("기본 데이터 폴더 설정 (기억됨)")
        btn_set_dir.setStyleSheet("background: #555; color: #8BC34A; padding: 4px 8px;")
        btn_set_dir.clicked.connect(self._set_base_data_dir)
        top_row.addWidget(btn_set_dir)

        dir_display = self._base_data_dir if self._base_data_dir else "(미설정)"
        self.dir_label = QLabel(dir_display[-40:] if len(dir_display) > 40 else dir_display)
        self.dir_label.setStyleSheet("color: #888; font-size: 9px;")
        self.dir_label.setToolTip(self._base_data_dir)
        top_row.addWidget(self.dir_label, stretch=1)
        layout.addLayout(top_row)

        self._add_data_group(layout, "before", "Before")
        self._add_data_group(layout, "after", "After")
        self._add_data_group(layout, "target", "Target")

        tools_tab = QTabWidget()
        tools_tab.setStyleSheet("QTabBar::tab { padding: 4px 10px; font-size: 11px; }")

        tab_gen = QWidget()
        tg_layout = QVBoxLayout(tab_gen)
        tg_layout.setSpacing(2); tg_layout.setContentsMargins(4, 4, 4, 4)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self.target_type_combo = QComboBox()
        self.target_type_combo.addItems(["Trench", "Grading", "Pit", "Slope"])
        self.target_type_combo.setToolTip("Trench/Grading/Pit/Slope")
        self.target_type_combo.currentTextChanged.connect(self._on_target_type_changed)
        type_row.addWidget(self.target_type_combo)
        tg_layout.addLayout(type_row)

        self.param_widgets = {}
        param_grid = QHBoxLayout()
        col1 = QVBoxLayout()
        col2 = QVBoxLayout()
        self._add_param_row(col1, "x_min", "X Min (m)", -5.0, -100, 100)
        self._add_param_row(col1, "x_max", "X Max (m)", 5.0, -100, 100)
        self._add_param_row(col1, "y_min", "Y Min (m)", -5.0, -100, 100)
        self._add_param_row(col1, "y_max", "Y Max (m)", 5.0, -100, 100)
        self._add_param_row(col1, "resolution", "Res (m)", 0.05, 0.01, 1.0, 3)
        self._add_param_row(col2, "base_height", "Base H (m)", 0.0, -50, 50)
        self._add_param_row(col2, "depth", "Depth (m)", 1.0, 0.01, 20)
        self._add_param_row(col2, "width", "Width (m)", 0.6, 0.1, 20)
        self._add_param_row(col2, "wall_angle", "Angle (°)", 90.0, 10, 90)
        param_grid.addLayout(col1)
        param_grid.addLayout(col2)
        tg_layout.addLayout(param_grid)

        gen_row = QHBoxLayout()
        btn_auto_range = QPushButton("Auto Range from Before")
        btn_auto_range.setToolTip("Before 데이터의 범위와 지면 높이로 자동 설정")
        btn_auto_range.clicked.connect(self._auto_fill_ranges_from_before)
        gen_row.addWidget(btn_auto_range)
        tg_layout.addLayout(gen_row)

        btn_generate = QPushButton("Generate Target (Before 지면 기준)")
        btn_generate.setStyleSheet("background: #2196F3; color: white; font-weight: bold; padding: 6px;")
        btn_generate.setToolTip("Before 점군의 지면 높이/기울기를 기준으로 이상적 target 생성")
        btn_generate.clicked.connect(self._generate_target)
        tg_layout.addWidget(btn_generate)

        self.grid_resolution_spin = QDoubleSpinBox()
        self.grid_resolution_spin.setRange(0.01, 5.0); self.grid_resolution_spin.setValue(0.05)
        self.grid_resolution_spin.setDecimals(3)
        self.grid_resolution_spin.setVisible(False)
        tg_layout.addWidget(self.grid_resolution_spin)

        self.interp_combo = QComboBox()
        self.interp_combo.addItems(["linear", "nearest", "cubic"])
        self.interp_combo.setVisible(False)
        tg_layout.addWidget(self.interp_combo)

        tg_layout.addStretch()

        tab_roi = QWidget()
        roi_layout = QVBoxLayout(tab_roi)
        roi_layout.setSpacing(2); roi_layout.setContentsMargins(4, 4, 4, 4)

        roi_layout.addWidget(QLabel("Global ROI (XYZ 범위 → 전체 적용):"))
        self._global_roi_spins = {}
        for axis_name, color in [('X', '#2196F3'), ('Y', '#4CAF50'), ('Z', '#F44336')]:
            row = QHBoxLayout()
            lbl = QLabel(f"{axis_name}:")
            lbl.setStyleSheet(f"color: {color}; font-weight: bold;"); lbl.setFixedWidth(16)
            row.addWidget(lbl)
            lo = QDoubleSpinBox(); lo.setRange(-10000, 10000); lo.setValue(-100); lo.setDecimals(1)
            row.addWidget(lo)
            row.addWidget(QLabel("~"))
            hi = QDoubleSpinBox(); hi.setRange(-10000, 10000); hi.setValue(100); hi.setDecimals(1)
            row.addWidget(hi)
            roi_layout.addLayout(row)
            self._global_roi_spins[f"{axis_name.lower()}_min"] = lo
            self._global_roi_spins[f"{axis_name.lower()}_max"] = hi

        groi_row = QHBoxLayout()
        btn_gf = QPushButton("From Before")
        btn_gf.setToolTip("Before 범위로 ROI 자동 설정")
        btn_gf.clicked.connect(self._global_roi_from_before)
        groi_row.addWidget(btn_gf)
        btn_ge = QPushButton("Visual Edit")
        btn_ge.setToolTip("ROI Editor로 드래그 설정")
        btn_ge.clicked.connect(self._global_roi_visual_edit)
        groi_row.addWidget(btn_ge)
        btn_ga = QPushButton("Apply to All")
        btn_ga.setStyleSheet("background:#FF9800;color:white;font-weight:bold;")
        btn_ga.setToolTip("Before/After/Target 전체에 ROI 적용")
        btn_ga.clicked.connect(self._global_roi_apply_all)
        groi_row.addWidget(btn_ga)
        roi_layout.addLayout(groi_row)

        sep2 = QLabel("─── Ground Leveling ───")
        sep2.setStyleSheet("color: #666; font-size: 9px;"); sep2.setAlignment(Qt.AlignCenter)
        roi_layout.addWidget(sep2)

        lv_row = QHBoxLayout()
        btn_lb = QPushButton("Level Before"); btn_lb.clicked.connect(lambda: self._level_ground('before')); lv_row.addWidget(btn_lb)
        btn_la = QPushButton("Level After"); btn_la.clicked.connect(lambda: self._level_ground('after')); lv_row.addWidget(btn_la)
        btn_lall = QPushButton("Level All"); btn_lall.setStyleSheet("background:#9C27B0;color:white;font-weight:bold;")
        btn_lall.clicked.connect(self._level_ground_all_same); lv_row.addWidget(btn_lall)
        roi_layout.addLayout(lv_row)
        self.level_result_label = QLabel("")
        self.level_result_label.setStyleSheet("color: #CE93D8; font-size: 9px;")
        roi_layout.addWidget(self.level_result_label)
        roi_layout.addStretch()

        tab_icp = QWidget()
        icp_layout = QVBoxLayout(tab_icp)
        icp_layout.setSpacing(2); icp_layout.setContentsMargins(4, 4, 4, 4)

        zr = QHBoxLayout()
        zr.addWidget(QLabel("Z:"))
        self.icp_z_min = QDoubleSpinBox(); self.icp_z_min.setRange(-1000,1000); self.icp_z_min.setValue(-0.5); self.icp_z_min.setDecimals(2)
        zr.addWidget(self.icp_z_min); zr.addWidget(QLabel("~"))
        self.icp_z_max = QDoubleSpinBox(); self.icp_z_max.setRange(-1000,1000); self.icp_z_max.setValue(0.5); self.icp_z_max.setDecimals(2)
        zr.addWidget(self.icp_z_max)
        icp_layout.addLayout(zr)

        opts_row = QHBoxLayout()
        self.icp_auto_z = QCheckBox("Z 자동"); self.icp_auto_z.setChecked(True); opts_row.addWidget(self.icp_auto_z)
        self.icp_lock_yaw = QCheckBox("Yaw-lock"); self.icp_lock_yaw.setChecked(True); self.icp_lock_yaw.setToolTip("Z축 회전만 허용 (기본 ON)"); opts_row.addWidget(self.icp_lock_yaw)
        opts_row.addStretch()
        icp_layout.addLayout(opts_row)

        btn_icp = QPushButton("Align After → Before")
        btn_icp.setStyleSheet("background:#2196F3;color:white;font-weight:bold;")
        btn_icp.clicked.connect(self._run_icp_alignment)
        icp_layout.addWidget(btn_icp)
        self.icp_result_label = QLabel("")
        self.icp_result_label.setStyleSheet("color: #FFD700; font-size: 9px;")
        icp_layout.addWidget(self.icp_result_label)
        icp_layout.addStretch()

        tools_tab.addTab(tab_roi, "① ROI / Level")
        tools_tab.addTab(tab_icp, "② ICP")
        tools_tab.addTab(tab_gen, "③ Generate")

        layout.addWidget(tools_tab, stretch=1)

        scroll.setWidget(scroll_content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _add_data_group(self, parent_layout, key: str, title: str):
        group = QGroupBox(title)
        g_layout = QVBoxLayout()
        g_layout.setSpacing(2); g_layout.setContentsMargins(4, 10, 4, 4)

        info_label = QLabel("No data loaded")
        info_label.setObjectName(f"info_{key}")
        g_layout.addWidget(info_label)

        btn_row = QHBoxLayout()
        btn_pc = QPushButton("Load PC")
        btn_pc.setToolTip("포인트 클라우드 파일 로드 (PCD/CSV/LAS/NPY/PLY)")
        btn_pc.clicked.connect(lambda _, k=key: self._load_pointcloud(k))
        btn_row.addWidget(btn_pc)

        btn_grid = QPushButton("Load Grid")
        btn_grid.setToolTip("2D 높이 그리드 맵 로드 (NPY/NPZ/CSV)")
        btn_grid.clicked.connect(lambda _, k=key: self._load_gridmap(k))
        btn_row.addWidget(btn_grid)

        btn_bag = QPushButton("ROS2 Bag")
        btn_bag.setToolTip("ROS2 bag에서 PointCloud2 로드")
        btn_bag.clicked.connect(lambda _, k=key: self._load_rosbag(k))
        btn_row.addWidget(btn_bag)
        g_layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        btn_bagg = QPushButton("Bag GridMap")
        btn_bagg.setToolTip("ROS2 bag에서 OccupancyGrid/GridMap 로드")
        btn_bagg.clicked.connect(lambda _, k=key: self._load_rosbag_gridmap(k))
        btn_row2.addWidget(btn_bagg)

        btn_clear = QPushButton("Clear")
        btn_clear.setToolTip("데이터 제거")
        btn_clear.setStyleSheet("color: #F44336;")
        btn_clear.clicked.connect(lambda _, k=key: self._clear_data(k))
        btn_row2.addWidget(btn_clear)
        g_layout.addLayout(btn_row2)

        tools_row = QHBoxLayout()
        chk = QCheckBox("Visible")
        chk.setChecked(True)
        chk.setObjectName(f"visible_{key}")
        chk.stateChanged.connect(lambda state, k=key: self.visibility_changed.emit(k, state == Qt.Checked))
        tools_row.addWidget(chk)

        btn_tf = QPushButton("TF Frame")
        btn_tf.setToolTip("ROS2 bag TF를 이용하여 다른 프레임으로 변환")
        btn_tf.clicked.connect(lambda _, k=key: self._reapply_tf_frame(k))
        tools_row.addWidget(btn_tf)

        btn_roi = QPushButton("Edit ROI")
        btn_roi.setToolTip("점군 유효 범위 편집 / 필터링")
        btn_roi.clicked.connect(lambda _, k=key: self._edit_roi(k))
        tools_row.addWidget(btn_roi)

        btn_xfm = QPushButton("Transform")
        btn_xfm.setToolTip("RPY/XYZ 수동 좌표 변환")
        btn_xfm.clicked.connect(lambda _, k=key: self._show_transform_dialog(k))
        tools_row.addWidget(btn_xfm)

        btn_undo = QPushButton("↩")
        btn_undo.setFixedWidth(28)
        btn_undo.setToolTip("Undo (이전 상태로 되돌리기)")
        btn_undo.clicked.connect(lambda _, k=key: self.undo(k))
        tools_row.addWidget(btn_undo)

        btn_redo = QPushButton("↪")
        btn_redo.setFixedWidth(28)
        btn_redo.setToolTip("Redo")
        btn_redo.clicked.connect(lambda _, k=key: self.redo(k))
        tools_row.addWidget(btn_redo)
        g_layout.addLayout(tools_row)

        group.setLayout(g_layout)
        parent_layout.addWidget(group)

    def _add_param_row(self, layout, key, label, default, min_val, max_val, decimals=2, tip=""):
        row = QHBoxLayout()
        lbl = QLabel(label)
        if tip:
            lbl.setToolTip(tip)
        row.addWidget(lbl)
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setValue(default)
        spin.setDecimals(decimals)
        if tip:
            spin.setToolTip(tip)
        row.addWidget(spin)
        layout.addLayout(row)
        self.param_widgets[key] = spin

    def _push_undo(self, key: str):
        current = self._loaded_data.get(key)
        if current is not None:
            import copy
            snapshot = {k: v for k, v in current.items() if k != '_raw_data'}
            if current.get('type') == 'pointcloud':
                snapshot['data'] = current['data'].copy()
            self._undo_stacks[key].append(snapshot)
            if len(self._undo_stacks[key]) > 20:
                self._undo_stacks[key].pop(0)
            self._redo_stacks[key].clear()

    def undo(self, key: str):
        if not self._undo_stacks[key]:
            return
        current = self._loaded_data.get(key)
        if current:
            snap = {k: v for k, v in current.items() if k != '_raw_data'}
            if current.get('type') == 'pointcloud':
                snap['data'] = current['data'].copy()
            self._redo_stacks[key].append(snap)

        prev = self._undo_stacks[key].pop()
        self._loaded_data[key] = prev
        pts = prev['data']
        dtype = prev['type']
        self._update_info_label(key, f"Undo: {len(pts) if hasattr(pts, '__len__') else '?'} pts")
        self.data_loaded.emit(key, pts, dtype)

    def redo(self, key: str):
        if not self._redo_stacks[key]:
            return
        current = self._loaded_data.get(key)
        if current:
            snap = {k: v for k, v in current.items() if k != '_raw_data'}
            if current.get('type') == 'pointcloud':
                snap['data'] = current['data'].copy()
            self._undo_stacks[key].append(snap)

        nxt = self._redo_stacks[key].pop()
        self._loaded_data[key] = nxt
        pts = nxt['data']
        dtype = nxt['type']
        self._update_info_label(key, f"Redo: {len(pts) if hasattr(pts, '__len__') else '?'} pts")
        self.data_loaded.emit(key, pts, dtype)

    def _set_base_data_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "기본 데이터 폴더 선택", self._base_data_dir)
        if dir_path:
            self._base_data_dir = dir_path
            self._settings.setValue("base_data_dir", dir_path)
            display = dir_path if len(dir_path) < 40 else "..." + dir_path[-37:]
            self.dir_label.setText(display)
            self.dir_label.setToolTip(dir_path)

    def _apply_prev_roi_to_dialog(self, dlg):
        prev = self._last_load_params
        roi = prev.get('roi_ranges')
        if roi:
            for ax in ['x', 'y', 'z']:
                for bound in ['min', 'max']:
                    k = f"{ax}_{bound}"
                    if k in roi and k in dlg._spins:
                        dlg._spins[k].setValue(roi[k])
        if prev.get('roi_max_range'):
            dlg.max_range_spin.setValue(prev['roi_max_range'])
        if prev.get('roi_remove_body'):
            dlg.chk_remove_body.setChecked(True)
        if prev.get('roi_ground_only'):
            dlg.chk_ground_only.setChecked(True)
        dlg._update_preview()

    def _save_roi_from_dialog(self, dlg):
        self._last_load_params['roi_ranges'] = {
            f"{ax}_{bound}": dlg._spins[f"{ax}_{bound}"].value()
            for ax in ['x', 'y', 'z'] for bound in ['min', 'max']
        }
        self._last_load_params['roi_max_range'] = dlg.max_range_spin.value()
        self._last_load_params['roi_remove_body'] = dlg.chk_remove_body.isChecked()
        self._last_load_params['roi_ground_only'] = dlg.chk_ground_only.isChecked()

    def _auto_roi_and_emit(self, key: str, points: np.ndarray, filepath: str):
        from gui.roi_dialog import ROIDialog
        dlg = ROIDialog(points, title=f"ROI Editor - {key}", parent=self)
        self._apply_prev_roi_to_dialog(dlg)

        if dlg.exec_() == QDialog.Accepted:
            result = dlg.get_result()
            if result is not None and len(result) > 0:
                points = result
            self._save_roi_from_dialog(dlg)
        self._loaded_data[key] = {'type': 'pointcloud', 'data': points, 'path': filepath}
        self._update_info_label(key, f"PC: {len(points):,} pts | {os.path.basename(filepath)}")
        self.data_loaded.emit(key, points, 'pointcloud')

    def _load_pointcloud(self, key: str):
        filepath, _ = QFileDialog.getOpenFileName(
            self, f"Load Point Cloud ({key})", self._base_data_dir, POINT_CLOUD_FILTER)
        if not filepath:
            return

        try:
            from core.data_loader import load_point_cloud
            points = load_point_cloud(filepath)
            self._auto_roi_and_emit(key, points, filepath)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load: {e}")

    def _load_gridmap(self, key: str):
        filepath, _ = QFileDialog.getOpenFileName(
            self, f"Load Grid Map ({key})", self._base_data_dir, GRID_MAP_FILTER)
        if not filepath:
            return

        try:
            from core.data_loader import load_grid_map
            grid_data = load_grid_map(filepath)
            self._loaded_data[key] = {'type': 'grid', 'data': grid_data, 'path': filepath}
            shape = grid_data['grid'].shape
            res = grid_data['resolution']
            self._update_info_label(key, f"Grid: {shape[1]}x{shape[0]} @ {res}m | {os.path.basename(filepath)}")
            self.data_loaded.emit(key, grid_data, 'grid')
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load: {e}")

    def _load_rosbag(self, key: str):
        filepath, _ = QFileDialog.getOpenFileName(
            self, f"ROS2 Bag 파일 선택 ({key})", self._base_data_dir,
            "ROS2 Bag (*.db3 *.mcap);;All Files (*)")
        if not filepath:
            return

        try:
            from core.rosbag_loader import list_pointcloud_topics, load_pointcloud_from_bag, count_frames
            from PyQt5.QtWidgets import QInputDialog

            prev = self._last_load_params

            topics = list_pointcloud_topics(filepath)
            if not topics:
                QMessageBox.warning(self, "Warning", "No PointCloud2 topics found in this bag.")
                return

            topic_name = topics[0]['name']
            if len(topics) > 1:
                items = [t['name'] for t in topics]
                default_idx = items.index(prev.get('topic', '')) if prev.get('topic', '') in items else 0
                chosen, ok = QInputDialog.getItem(self, "Select Topic",
                                                   "PointCloud2 Topics:", items, default_idx, False)
                if ok and chosen:
                    topic_name = chosen
                else:
                    return

            n_frames = count_frames(filepath, topic_name)
            frame_idx = prev.get('frame_idx', -1)
            target_frame_used = ""

            try:
                from core.tf_transformer import list_available_frames, transform_pointcloud_between_frames
                from gui.tf_preview_dialog import TFPreviewDialog

                available = list_available_frames(filepath)
                pc_frame = self._detect_pc_frame_id(filepath, topic_name)

                preview = TFPreviewDialog(
                    bag_path=filepath,
                    topic_name=topic_name,
                    n_frames=n_frames,
                    source_frame=pc_frame,
                    available_frames=available,
                    default_frame_idx=frame_idx,
                    default_target_frame=prev.get('tf_frame', ''),
                    parent=self,
                )
                if preview.exec_() != QDialog.Accepted:
                    return

                frame_idx = preview.selected_frame_idx()
                target_frame_used = preview.selected_target_frame()

                raw_points = load_pointcloud_from_bag(filepath, topic_name, frame_idx)
                points = raw_points.copy()

                if target_frame_used and pc_frame:
                    points = transform_pointcloud_between_frames(
                        raw_points, filepath, pc_frame, target_frame_used)
                    topic_name += f" → {target_frame_used}"

            except ImportError:
                raw_points = load_pointcloud_from_bag(filepath, topic_name, frame_idx)
                points = raw_points.copy()
            except Exception as tf_err:
                QMessageBox.warning(self, "TF Warning", f"TF 프리뷰 실패, 기본 로드:\n{tf_err}")
                raw_points = load_pointcloud_from_bag(filepath, topic_name, frame_idx)
                points = raw_points.copy()

            MAX_RANGE = 20.0
            dists = np.linalg.norm(points[:, :2], axis=1)
            range_mask = dists < MAX_RANGE
            points = points[range_mask]
            raw_points = raw_points[range_mask] if len(raw_points) == len(range_mask) else raw_points

            self._last_load_params = {
                'topic': topic_name.split(' →')[0],
                'frame_idx': frame_idx,
                'tf_frame': target_frame_used or prev.get('tf_frame', ''),
                'bag_path': filepath,
            }

            from gui.roi_dialog import ROIDialog
            dlg = ROIDialog(points, title=f"ROI Editor - {key} (Bag)", parent=self)

            self._apply_prev_roi_to_dialog(dlg)

            if dlg.exec_() == QDialog.Accepted:
                result = dlg.get_result()
                if result is not None and len(result) > 0:
                    points = result
                self._save_roi_from_dialog(dlg)

            self._loaded_data[key] = {
                'type': 'pointcloud', 'data': points, 'path': filepath,
                '_raw_data': raw_points,
            }
            self._update_info_label(key,
                f"Bag: {len(points):,} pts | {topic_name} [frame {frame_idx}]")
            self.data_loaded.emit(key, points, 'pointcloud')

        except ImportError as e:
            QMessageBox.critical(self, "Error",
                f"ROS2 packages not available:\n{e}\n\n"
                "Make sure to source ROS2 setup before running.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load bag:\n{e}")

    def _load_rosbag_gridmap(self, key: str):
        from PyQt5.QtWidgets import QInputDialog

        choices = ["db3/mcap 파일 선택", "Bag 디렉토리 선택"]
        choice, ok = QInputDialog.getItem(self, "ROS2 Bag GridMap", "선택:", choices, 0, False)
        if not ok:
            return

        if choice == choices[1]:
            filepath = QFileDialog.getExistingDirectory(self, "Bag Directory", self._base_data_dir)
        else:
            filepath, _ = QFileDialog.getOpenFileName(self, "Bag File", self._base_data_dir, "ROS2 Bag (*.db3 *.mcap);;All (*)")
        if not filepath:
            return

        try:
            from core.rosbag_loader import list_gridmap_topics, load_gridmap_from_bag, count_frames

            topics = list_gridmap_topics(filepath)
            if not topics:
                QMessageBox.warning(self, "Warning",
                    "GridMap 토픽을 찾을 수 없습니다.\n"
                    "지원 타입: nav_msgs/OccupancyGrid, grid_map_msgs/GridMap")
                return

            topic_name = topics[0]['name']
            if len(topics) > 1:
                items = [f"{t['name']} ({t['type']})" for t in topics]
                chosen, ok = QInputDialog.getItem(self, "GridMap Topic", "선택:", items, 0, False)
                if not ok:
                    return
                topic_name = topics[items.index(chosen)]['name']

            n = count_frames(filepath, topic_name)
            frame_idx = -1
            if n > 1:
                frame_idx, ok = QInputDialog.getInt(self, "Frame", f"0~{n-1}, -1=last:", -1, -1, n-1)
                if not ok:
                    return

            grid_data = load_gridmap_from_bag(filepath, topic_name, frame_idx)
            self._loaded_data[key] = {'type': 'grid', 'data': grid_data, 'path': filepath}
            shape = grid_data['grid'].shape
            self._update_info_label(key, f"BagGrid: {shape[1]}x{shape[0]} @ {grid_data['resolution']}m | {topic_name}")
            self.data_loaded.emit(key, grid_data, 'grid')

        except ImportError as e:
            QMessageBox.critical(self, "Error", f"ROS2 패키지 필요:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"GridMap 로드 실패:\n{e}")

    def _clear_data(self, key: str):
        if key in self._loaded_data:
            del self._loaded_data[key]
        self._update_info_label(key, "No data loaded")
        self.data_cleared.emit(key)

    def _update_info_label(self, key: str, text: str):
        label = self.findChild(QLabel, f"info_{key}")
        if label:
            label.setText(text)

    def _global_roi_from_before(self):
        data = self.get_data('before')
        if data is None:
            QMessageBox.warning(self, "Warning", "Before 데이터가 없습니다.")
            return
        pts = data['data'] if data['type'] == 'pointcloud' else self._grid_to_pts(data)
        if pts is None or len(pts) == 0:
            return
        for ax_i, ax in enumerate(['x', 'y', 'z']):
            self._global_roi_spins[f"{ax}_min"].setValue(float(pts[:, ax_i].min()))
            self._global_roi_spins[f"{ax}_max"].setValue(float(pts[:, ax_i].max()))

    def _global_roi_visual_edit(self):
        data = self.get_data('before')
        if data is None:
            QMessageBox.warning(self, "Warning", "Before 데이터를 먼저 로드하세요.")
            return
        pts = data['data'] if data['type'] == 'pointcloud' else self._grid_to_pts(data)
        if pts is None or len(pts) == 0:
            return

        from gui.roi_dialog import ROIDialog
        dlg = ROIDialog(pts, title="Global ROI 설정 (Before 기준)", parent=self)
        if dlg.exec_() == QDialog.Accepted:
            for ax in ['x', 'y', 'z']:
                self._global_roi_spins[f"{ax}_min"].setValue(dlg._spins[f"{ax}_min"].value())
                self._global_roi_spins[f"{ax}_max"].setValue(dlg._spins[f"{ax}_max"].value())

    def _global_roi_apply_all(self):
        for key in ['before', 'after', 'target']:
            if key in self._loaded_data:
                self._push_undo(key)
        roi = {}
        for ax in ['x', 'y', 'z']:
            roi[f"{ax}_min"] = self._global_roi_spins[f"{ax}_min"].value()
            roi[f"{ax}_max"] = self._global_roi_spins[f"{ax}_max"].value()

        applied = 0
        for key in ['before', 'after', 'target']:
            data = self.get_data(key)
            if data is None:
                continue
            if data['type'] == 'pointcloud':
                pts = data['data']
            else:
                pts = self._grid_to_pts(data)
            if pts is None or len(pts) == 0:
                continue

            mask = np.ones(len(pts), dtype=bool)
            for ax_i, ax in enumerate(['x', 'y', 'z']):
                mask &= (pts[:, ax_i] >= roi[f"{ax}_min"]) & (pts[:, ax_i] <= roi[f"{ax}_max"])
            filtered = pts[mask]

            if len(filtered) == 0:
                continue

            self._loaded_data[key] = {
                'type': 'pointcloud', 'data': filtered,
                'path': data.get('path', ''),
            }
            if '_raw_data' in data:
                self._loaded_data[key]['_raw_data'] = data['_raw_data']
            self._update_info_label(key, f"ROI: {len(filtered):,} pts (from {len(pts):,})")
            self.data_loaded.emit(key, filtered, 'pointcloud')
            applied += 1

        if applied == 0:
            QMessageBox.warning(self, "Warning", "적용할 데이터가 없습니다.")
        else:
            QMessageBox.information(self, "Done", f"{applied}개 데이터에 Global ROI 적용 완료")

    def _grid_to_pts(self, data):
        if data['type'] == 'grid':
            from core.grid_converter import grid_to_pointcloud
            return grid_to_pointcloud(data['data'])
        return data.get('data')

    def _level_ground(self, key: str):
        self._push_undo(key)
        data = self.get_data(key)
        if data is None:
            QMessageBox.warning(self, "Warning", f"{key} 데이터가 없습니다.")
            return

        pts = data['data'] if data['type'] == 'pointcloud' else self._grid_to_pts(data)
        if pts is None or len(pts) < 10:
            return

        try:
            from core.point_filter import estimate_ground_plane, level_to_ground_plane
            normal, d, inlier_mask = estimate_ground_plane(pts)
            leveled, R = level_to_ground_plane(pts, normal)

            tilt_deg = np.degrees(np.arccos(np.clip(np.dot(normal, [0, 0, 1]), -1, 1)))

            self._loaded_data[key] = {
                'type': 'pointcloud', 'data': leveled,
                'path': data.get('path', ''),
            }
            self._update_info_label(key, f"Leveled: {len(leveled):,} pts (tilt={tilt_deg:.1f}°)")
            self.data_loaded.emit(key, leveled, 'pointcloud')
            self.level_result_label.setText(
                f"{key}: tilt={tilt_deg:.1f}° | normal=({normal[0]:.3f},{normal[1]:.3f},{normal[2]:.3f})")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Ground leveling 실패:\n{e}")

    def _level_ground_all_same(self):
        for key in ['before', 'after', 'target']:
            if key in self._loaded_data:
                self._push_undo(key)
        before = self.get_data('before')
        if before is None:
            QMessageBox.warning(self, "Warning", "Before 데이터가 필요합니다.")
            return

        pts_before = before['data'] if before['type'] == 'pointcloud' else self._grid_to_pts(before)
        if pts_before is None or len(pts_before) < 10:
            return

        try:
            from core.point_filter import estimate_ground_plane, level_to_ground_plane
            normal, d, _ = estimate_ground_plane(pts_before)
            tilt_deg = np.degrees(np.arccos(np.clip(np.dot(normal, [0, 0, 1]), -1, 1)))

            applied = 0
            for key in ['before', 'after', 'target']:
                data = self.get_data(key)
                if data is None:
                    continue
                pts = data['data'] if data['type'] == 'pointcloud' else self._grid_to_pts(data)
                if pts is None or len(pts) == 0:
                    continue

                leveled, _ = level_to_ground_plane(pts, normal)
                self._loaded_data[key] = {
                    'type': 'pointcloud', 'data': leveled,
                    'path': data.get('path', ''),
                }
                self._update_info_label(key, f"Leveled: {len(leveled):,} pts")
                self.data_loaded.emit(key, leveled, 'pointcloud')
                applied += 1

            self.level_result_label.setText(
                f"Before 기준 tilt={tilt_deg:.1f}° → {applied}개 데이터 수평 보정 완료")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Ground leveling 실패:\n{e}")

    def _run_icp_alignment(self):
        self._push_undo('after')
        before = self.get_data('before')
        after = self.get_data('after')
        if before is None or after is None:
            QMessageBox.warning(self, "Warning", "Before와 After 데이터가 모두 필요합니다.")
            return

        from core.grid_converter import grid_to_pointcloud

        if before['type'] == 'grid':
            pts_before = grid_to_pointcloud(before['data'])
        else:
            pts_before = before['data']

        if after['type'] == 'grid':
            pts_after = grid_to_pointcloud(after['data'])
        else:
            pts_after = after['data']

        z_range = None
        if not self.icp_auto_z.isChecked():
            z_range = (self.icp_z_min.value(), self.icp_z_max.value())

        try:
            from core.icp_align import icp_align_stable_region
            result = icp_align_stable_region(pts_after, pts_before, z_range=z_range,
                                                        lock_yaw=self.icp_lock_yaw.isChecked())

            self._loaded_data['after'] = {
                'type': 'pointcloud',
                'data': result['transformed'],
                'path': after.get('path', ''),
            }
            self._update_info_label('after',
                f"Aligned to Before: {len(result['transformed'])} pts (RMSE={result['rmse']:.4f}m, iter={result['iterations']})")
            self.data_loaded.emit('after', result['transformed'], 'pointcloud')

            info = (f"RMSE: {result['rmse']:.4f}m | Iterations: {result['iterations']}\n"
                    f"Stable pts: src={result.get('stable_count_source',0)}, tgt={result.get('stable_count_target',0)}")
            self.icp_result_label.setText(info)

        except Exception as e:
            QMessageBox.critical(self, "ICP Error", f"ICP 정합 실패:\n{e}")

    def _auto_fill_ranges_from_before(self):
        before_data = self.get_data('before')
        if before_data is None:
            return

        if before_data['type'] == 'pointcloud':
            pts = before_data['data']
        elif before_data['type'] == 'grid':
            from core.grid_converter import grid_to_pointcloud
            pts = grid_to_pointcloud(before_data['data'])
        else:
            return

        if len(pts) == 0:
            return

        margin = 1.0
        self.param_widgets['x_min'].setValue(float(pts[:, 0].min()) - margin)
        self.param_widgets['x_max'].setValue(float(pts[:, 0].max()) + margin)
        self.param_widgets['y_min'].setValue(float(pts[:, 1].min()) - margin)
        self.param_widgets['y_max'].setValue(float(pts[:, 1].max()) + margin)

        z_median = float(np.median(pts[:, 2]))
        self.param_widgets['base_height'].setValue(z_median)

    def _generate_target(self):
        if 'target' in self._loaded_data:
            self._push_undo('target')
        from core.target_generator import (
            generate_trench_target, generate_grading_target,
            generate_pit_target, generate_slope_target,
            generate_flat_terrain
        )

        p = {k: w.value() for k, w in self.param_widgets.items()}
        x_range = (p['x_min'], p['x_max'])
        y_range = (p['y_min'], p['y_max'])
        res = p['resolution']
        target_type = self.target_type_combo.currentText()

        try:
            before_data = self.get_data('before')
            if before_data is not None:
                pts_before = before_data['data'] if before_data['type'] == 'pointcloud' else self._grid_to_pts(before_data)
                if pts_before is not None and len(pts_before) > 50:
                    from core.point_filter import estimate_ground_plane
                    normal, d, inlier_mask = estimate_ground_plane(pts_before)
                    ground_pts = pts_before[inlier_mask]
                    base_h = float(np.median(ground_pts[:, 2]))
                    p['base_height'] = base_h
                    self.param_widgets['base_height'].setValue(base_h)

            if target_type == "Trench":
                target = generate_trench_target(
                    x_range, y_range, res, p['base_height'],
                    trench_depth=p['depth'], trench_width=p['width'],
                    wall_angle=p['wall_angle']
                )
            elif target_type == "Grading":
                target = generate_grading_target(
                    x_range, y_range, res, target_height=p['base_height'] - p['depth']
                )
            elif target_type == "Pit":
                target = generate_pit_target(
                    x_range, y_range, res, p['base_height'],
                    pit_depth=p['depth'],
                    pit_width_x=p['width'], pit_width_y=p['width'],
                    wall_angle=p['wall_angle']
                )
            elif target_type == "Slope":
                target = generate_slope_target(
                    x_range, y_range, res,
                    top_height=p['base_height'],
                    bottom_height=p['base_height'] - p['depth']
                )
            else:
                return

            self._loaded_data['target'] = {'type': 'grid', 'data': target, 'path': 'generated'}
            self._update_info_label('target',
                f"Target: {target_type} @ base={p['base_height']:.2f}m, depth={p['depth']:.2f}m")
            self.data_loaded.emit('target', target, 'grid')

            if before_data is None:
                before = generate_flat_terrain(x_range, y_range, res, p['base_height'])
                self._loaded_data['before'] = {'type': 'grid', 'data': before, 'path': 'generated'}
                self._update_info_label('before', f"Grid (generated): flat @ {p['base_height']:.2f}m")
                self.data_loaded.emit('before', before, 'grid')

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Target generation failed: {e}")
            import traceback; traceback.print_exc()

    def _convert_to_grid(self):
        from core.grid_converter import pointcloud_to_grid, pointcloud_to_grid_binned
        res = self.grid_resolution_spin.value()
        method = self.interp_combo.currentText()

        converted_count = 0
        errors = []
        for key in ['before', 'after', 'target']:
            if key not in self._loaded_data or self._loaded_data[key]['type'] != 'pointcloud':
                continue
            try:
                points = self._loaded_data[key]['data']
                x_span = points[:, 0].max() - points[:, 0].min()
                y_span = points[:, 1].max() - points[:, 1].min()
                est_cells = (x_span / res) * (y_span / res)

                if est_cells > 5e6 or len(points) > 500000:
                    grid_data = pointcloud_to_grid_binned(points, resolution=res, aggregation='mean')
                else:
                    grid_data = pointcloud_to_grid(points, resolution=res, method=method)

                self._loaded_data[key] = {'type': 'grid', 'data': grid_data, 'path': self._loaded_data[key].get('path', '')}
                shape = grid_data['grid'].shape
                self._update_info_label(key, f"Grid (converted): {shape[1]}x{shape[0]} @ {res}m")
                self.data_loaded.emit(key, grid_data, 'grid')
                converted_count += 1
            except Exception as e:
                errors.append(f"{key}: {e}")

        if errors:
            QMessageBox.warning(self, "Conversion Errors", "\n".join(errors))
        elif converted_count == 0:
            QMessageBox.information(self, "Info", "변환할 포인트 클라우드 데이터가 없습니다.")
        else:
            QMessageBox.information(self, "Done", f"{converted_count}개 포인트 클라우드를 그리드로 변환했습니다.")

    def _edit_roi(self, key: str):
        self._push_undo(key)
        data = self.get_data(key)
        if data is None:
            QMessageBox.warning(self, "Warning", "데이터가 없습니다.")
            return

        if data['type'] == 'grid':
            from core.grid_converter import grid_to_pointcloud
            points = grid_to_pointcloud(data['data'])
        else:
            points = data['data']

        if len(points) == 0:
            QMessageBox.warning(self, "Warning", "포인트가 없습니다.")
            return

        from gui.roi_dialog import ROIDialog
        dlg = ROIDialog(points, title=f"ROI Editor - {key}", parent=self)
        if dlg.exec_() == QDialog.Accepted:
            result = dlg.get_result()
            if result is not None and len(result) > 0:
                self._loaded_data[key] = {
                    'type': 'pointcloud',
                    'data': result,
                    'path': data.get('path', ''),
                }
                if '_raw_data' in data:
                    self._loaded_data[key]['_raw_data'] = data['_raw_data']
                self._update_info_label(key, f"ROI filtered: {len(result):,} pts")
                self.data_loaded.emit(key, result, 'pointcloud')

    def _detect_pc_frame_id(self, bag_path: str, topic_name: str) -> str:
        try:
            from core.rosbag_loader import _open_reader
            from rclpy.serialization import deserialize_message
            from sensor_msgs.msg import PointCloud2
            reader = _open_reader(bag_path, topic_filter=[topic_name])
            if reader.has_next():
                _, data, _ = reader.read_next()
                msg = deserialize_message(data, PointCloud2)
                return msg.header.frame_id
        except Exception:
            pass
        return ''

    def _reapply_tf_frame(self, key: str):
        data = self.get_data(key)
        if data is None:
            QMessageBox.warning(self, "Warning", "데이터가 없습니다.")
            return

        bag_path = data.get('path', '')
        if not bag_path or bag_path in ('generated', 'sample', 'test', 't'):
            QMessageBox.warning(self, "Warning",
                "ROS2 bag 경로가 없습니다.\nbag에서 로드한 데이터만 TF 재변환이 가능합니다.")
            return

        try:
            from core.tf_transformer import list_available_frames, transform_pointcloud_between_frames
            available = list_available_frames(bag_path)
            if not available:
                QMessageBox.warning(self, "Warning", "TF 프레임을 찾을 수 없습니다.")
                return

            from PyQt5.QtWidgets import QInputDialog
            target_frame, ok = QInputDialog.getItem(
                self, "TF 기준 프레임 변경",
                f"현재 데이터의 소스 프레임과 목표 프레임을 선택합니다.\n"
                f"사용 가능: {', '.join(available)}\n\n"
                f"목표 프레임:",
                available, 0, False)
            if not ok:
                return

            source_frame, ok2 = QInputDialog.getItem(
                self, "소스 프레임",
                "현재 점군의 소스 프레임:",
                available, 0, False)
            if not ok2:
                return

            if data['type'] == 'grid':
                from core.grid_converter import grid_to_pointcloud
                points = grid_to_pointcloud(data['data'])
            else:
                points = data['data']

            if '_raw_data' in data:
                points = data['_raw_data'].copy()

            transformed = transform_pointcloud_between_frames(
                points, bag_path, source_frame, target_frame)

            self._loaded_data[key] = {
                'type': 'pointcloud',
                'data': transformed,
                'path': bag_path,
                '_raw_data': points,
            }
            self._update_info_label(key,
                f"TF: {len(transformed)} pts | {source_frame} → {target_frame}")
            self.data_loaded.emit(key, transformed, 'pointcloud')

        except ImportError as e:
            QMessageBox.critical(self, "Error", f"ROS2 패키지 필요:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "TF Error", f"TF 재변환 실패:\n{e}")

    def _show_transform_dialog(self, key: str):
        self._push_undo(key)
        data = self.get_data(key)
        if data is None:
            QMessageBox.warning(self, "Warning", "데이터가 없습니다.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Transform - {key}")
        dlg.setMinimumWidth(300)
        dl = QVBoxLayout(dlg)

        tf_spins = {}
        for label_text, names in [("RPY (°):", ['roll', 'pitch', 'yaw']),
                                   ("XYZ (m):", ['tx', 'ty', 'tz'])]:
            row = QHBoxLayout()
            row.addWidget(QLabel(label_text))
            for n in names:
                sp = QDoubleSpinBox()
                sp.setRange(-1000, 1000); sp.setValue(0); sp.setDecimals(2)
                tf_spins[n] = sp
                row.addWidget(sp)
            dl.addLayout(row)

        btn = QPushButton("Apply")
        btn.setStyleSheet("background: #4CAF50; color: white; font-weight: bold;")
        def on_apply():
            pts = data['data'] if data['type'] == 'pointcloud' else self._grid_to_pts(data)
            if pts is None:
                return
            pts = pts.copy()
            r = tf_spins['roll'].value(); p = tf_spins['pitch'].value(); y = tf_spins['yaw'].value()
            tx = tf_spins['tx'].value(); ty = tf_spins['ty'].value(); tz = tf_spins['tz'].value()
            rot = Rotation.from_euler('xyz', [r, p, y], degrees=True)
            pts = rot.apply(pts)
            pts[:, 0] += tx; pts[:, 1] += ty; pts[:, 2] += tz
            self._loaded_data[key] = {'type': 'pointcloud', 'data': pts, 'path': data.get('path', '')}
            self._update_info_label(key, f"XFM: {len(pts):,} pts")
            self.data_loaded.emit(key, pts, 'pointcloud')
            dlg.accept()
        btn.clicked.connect(on_apply)
        dl.addWidget(btn)
        dlg.exec_()

    def _apply_transform(self, key: str):
        self._push_undo(key)
        data = self.get_data(key)
        if data is None:
            QMessageBox.warning(self, "Warning", "데이터가 없습니다.")
            return

        roll = self.findChild(QDoubleSpinBox, f"tf_roll_{key}").value()
        pitch = self.findChild(QDoubleSpinBox, f"tf_pitch_{key}").value()
        yaw = self.findChild(QDoubleSpinBox, f"tf_yaw_{key}").value()
        tx = self.findChild(QDoubleSpinBox, f"tf_tx_{key}").value()
        ty = self.findChild(QDoubleSpinBox, f"tf_ty_{key}").value()
        tz = self.findChild(QDoubleSpinBox, f"tf_tz_{key}").value()

        if data['type'] == 'pointcloud':
            points = data['data'].copy()
        elif data['type'] == 'grid':
            from core.grid_converter import grid_to_pointcloud
            points = grid_to_pointcloud(data['data'])
        else:
            return

        rot = Rotation.from_euler('xyz', [roll, pitch, yaw], degrees=True)
        points = rot.apply(points)
        points[:, 0] += tx
        points[:, 1] += ty
        points[:, 2] += tz

        self._loaded_data[key] = {'type': 'pointcloud', 'data': points, 'path': data.get('path', '')}
        self._update_info_label(key, f"Transformed: {len(points)} pts (R={roll:.0f},{pitch:.0f},{yaw:.0f} T={tx:.1f},{ty:.1f},{tz:.1f})")
        self.data_loaded.emit(key, points, 'pointcloud')

    def _on_target_type_changed(self, text):
        pass

    def _show_help_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Excavation Analysis Tool - Help")
        dlg.setMinimumSize(600, 500)
        dlg_layout = QVBoxLayout(dlg)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet("background: #1e1e1e; color: #d4d4d4; border: none; padding: 8px;")
        browser.setHtml(HELP_HTML)
        dlg_layout.addWidget(browser)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dlg.close)
        dlg_layout.addWidget(btn_close)
        dlg.exec_()

    def get_data(self, key: str):
        if key in self._loaded_data:
            return self._loaded_data[key]
        return None

    def get_grid_data(self, key: str):
        data = self.get_data(key)
        if data is None:
            return None
        if data['type'] == 'grid':
            return data['data']
        if data['type'] == 'pointcloud':
            from core.grid_converter import pointcloud_to_grid
            return pointcloud_to_grid(data['data'],
                                      resolution=self.grid_resolution_spin.value(),
                                      method=self.interp_combo.currentText())
        return None

    def get_target_params(self):
        p = {k: w.value() for k, w in self.param_widgets.items()}
        return {
            'type': self.target_type_combo.currentText().lower(),
            'depth': p['depth'],
            'width': p['width'],
            'wall_angle': p['wall_angle'],
        }
