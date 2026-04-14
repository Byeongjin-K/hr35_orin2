# Excavation Analysis Tool — 굴착 작업 성능 평가 도구

## 1. 개요

자율 굴착기의 작업 성능을 정량적으로 평가하기 위한 GUI 분석 도구입니다. LiDAR로 스캔한 **작업 전/후 지형 점군(Point Cloud)**을 비교하여, 이상적 목표 대비 실제 작업 결과의 정확도를 다양한 metric으로 측정합니다.

**주요 용도**: 숙련 작업자(사람) vs 자율 작업 모델의 굴착 결과를 동일 기준으로 비교 분석

| 항목 | 내용 |
|------|------|
| 개발 환경 | Python 3.10+, PyQt5, ROS2 (Humble/Kilted) |
| 입력 데이터 | ROS2 bag (PointCloud2), PCD, CSV, LAS/LAZ, NPY |
| 출력 | 텍스트 리포트, 히트맵/차트, PDF, CSV 비교표 |
| 실행 | `python3 run_experi_analysis.py` (ROS2 sourced 상태 권장) |

---

## 2. 주요 기능

### 2.1 데이터 로드 및 전처리

```
ROS2 Bag → TF Preview (프레임/좌표계 선택, 프리뷰) → ROI 편집 (범위/필터) → 로드 완료
```

- **ROS2 Bag 직접 로드**: db3/mcap 파일에서 PointCloud2 토픽 추출, 프레임 인덱스 선택
- **TF 기반 좌표 변환**: bag 내 TF 토픽으로 LiDAR 프레임 → 기준 프레임(map 등) 자동 변환. 슬라이더로 프레임별 프리뷰 확인 후 선택
- **ROI 편집**: 마우스 드래그로 XY/XZ/YZ 영역 선택. Self-body 제거, 지면 추출, KNN 이상치 제거, 거리 제한 필터 내장
- **Global ROI**: Before/After/Target에 동일 범위를 일괄 적용
- **Before 파라미터 기억**: Before에서 설정한 TF, ROI, 필터 값이 After 로드 시 기본값으로 자동 적용
- **Undo/Redo**: 모든 데이터 변형(Transform, ROI, Level, ICP, Target 생성)에 대해 20단계 되돌리기

### 2.2 좌표계 정렬

| 기능 | 설명 |
|------|------|
| **Ground Leveling** | RANSAC 지면 평면 추정 → 전체 점군을 수평으로 회전 보정. Level All로 Before/After/Target 동시 적용 |
| **ICP 정합** | 안정 영역(비굴착 지면)만으로 ICP 수행 → After를 Before에 정합. Yaw-lock 옵션(Z축 회전만 허용) |
| **수동 Transform** | RPY(°) + XYZ(m) 직접 입력하여 점군 변환 |

### 2.3 Target 지형 생성

Before 데이터의 **실제 지면 높이**(RANSAC 추정)를 기준으로 이상적 굴착 목표 지형을 자동 생성:

| 유형 | 파라미터 |
|------|---------|
| **Trench** (도랑) | 깊이, 폭, 벽면 각도 |
| **Grading** (평탄화) | 목표 높이, X/Y 경사 |
| **Pit** (구덩이) | 깊이, 가로/세로 폭, 사각형/원형, 벽면 각도 |
| **Slope** (사면) | 상단/하단 높이, 경사각 |

### 2.4 분석 Metric (30+ 항목)

**기하학적 정확도**
- RMSE, MAE, Max Error, Hausdorff Distance, Chamfer Distance, 95th Percentile

**체적 분석**
- Cut/Fill Volume (m³), Volume Accuracy (%), Over/Under-excavation 비율

**굴착 특성**
- 깊이 통계 (Mean/Std/Min/Max), 폭 오차, 바닥 평탄도, Completeness, Precision

**단면 분석**
- Y축/X축 방향 Cross-Section, 단면 IoU, Profile RMSE

**표면 품질**
- Roughness Ra/Rq, Slope Consistency

### 2.5 시각화

| 탭 | 내용 |
|----|------|
| **3D Point Cloud** | pyqtgraph 기반 3D 뷰어. 포인트 크기/색상 조절, Top/Front/Side 시점 |
| **2.5D Grid Map** | Height Map, Contour, 3D Surface, Difference Map, Error Map, Volume 3D (Cut/Fill 색상) |
| **Analysis** | Report(텍스트), Heatmap, Cross-Sections, Histogram, Bar Chart |
| **Experiment Comparison** | 복수 실험 결과를 테이블 + Radar Chart + Bar Chart로 비교 |

### 2.6 부가 기능

- **거리 측정**: 2D 플롯(Top/Front/Side)에서 클릭하여 정확한 포인트 선택 → P1-P2 3D 거리 계산
- **Timeline Viewer**: bag 내 여러 프레임을 슬라이더로 순차 재생 (작업 과정 확인)
- **Kinematics Viewer**: boom/arm/bucket/swing 관절 각도 시계열 그래프 + 굴착기 측면도 애니메이션
- **세션 저장/로드**: 분석 결과를 JSON으로 저장, 나중에 복원
- **PDF 리포트**: 텍스트 리포트 + 모든 차트를 멀티페이지 PDF로 내보내기
- **CSV 비교 내보내기**: 복수 실험 metric을 CSV로 저장

---

## 3. 권장 워크플로우

```
① Before/After 점군 로드
   └─ ROS2 Bag → TF Preview (프레임/좌표계 선택) → ROI 편집 (범위/필터)

② 좌표계 정렬
   └─ ICP Alignment (Yaw-lock) → Ground Level All (수평 보정)

③ 공통 범위 적용
   └─ Global ROI → From Before → Apply to All

④ Target 생성
   └─ Auto Range from Before → Trench/Pit/Slope 선택 → Generate Target

⑤ 분석 실행
   └─ Run Full Analysis → Report / Heatmap / Cross-Sections / Histogram 확인

⑥ 비교 (반복)
   └─ 실험별로 ①~⑤ 반복 → Experiment Comparison 탭에서 비교
```

### 소프트웨어 구조

```
experi_analysis_gui/
├── run_experi_analysis.py            ← 실행 진입점
├── core/                            ← 핵심 알고리즘
│   ├── data_loader.py               ← 다중 포맷 점군 I/O
│   ├── rosbag_loader.py             ← ROS2 bag PointCloud2/GridMap 추출
│   ├── tf_transformer.py            ← TF 기반 좌표 변환 (BFS 체인 탐색)
│   ├── grid_converter.py            ← Point Cloud ↔ 2D Grid 변환
│   ├── target_generator.py          ← 이상적 굴착 목표 지형 생성
│   ├── metrics.py                   ← 30+ 평가 metric 엔진
│   ├── icp_align.py                 ← ICP 정합 (안정 영역 기반, Yaw-lock)
│   ├── point_filter.py              ← 필터링 (self-body, 지면 추출, RANSAC, KNN)
│   └── session_manager.py           ← 세션 저장/로드
├── gui/                             ← GUI 컴포넌트
│   ├── main_window.py               ← 메인 윈도우
│   ├── data_panel.py                ← 데이터 로드/전처리 패널
│   ├── viewer_3d.py                 ← 3D 점군 뷰어 + 거리 측정
│   ├── gridmap_viewer.py            ← 2.5D Grid Map 시각화
│   ├── analysis_panel.py            ← 분석 결과 탭 (Report/Heatmap/Sections/Histogram)
│   ├── comparison_panel.py          ← 복수 실험 비교 (Table/Radar/Bar)
│   ├── roi_dialog.py                ← ROI 편집 다이얼로그 (드래그 선택, 필터)
│   ├── tf_preview_dialog.py         ← TF 프레임 프리뷰 (슬라이더+2D뷰)
│   ├── point_pick_dialog.py         ← 2D 플롯 기반 포인트 선택
│   ├── timeline_dialog.py           ← 시계열 프레임 뷰어
│   └── kinematics_dialog.py         ← 굴착기 기구학 시각화
└── requirements.txt
```

**총 27개 파일, ~6,400 라인**
