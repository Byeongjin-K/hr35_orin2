# 남은 작업 계획 — 라이브/실험이 필요한 항목

작성 2026-08-13. 코드로 끝낼 수 있는 부분은 모두 반영된 상태이며, 여기 있는 것은
**장비·현장·타 저장소 접근이 있어야만** 진행되는 항목이다.

---

## 현재 상태 요약

| 구성요소 | 상태 |
|---|---|
| 1단계 LiDAR 투영 노드 | 완료. 실측 2.0 Hz / 57 KB, RELIABLE·KEEP_LAST(10)·VOLATILE |
| 2단계 dig-plan 레이어 | 코드 완료. 셀 폴리곤·start 마커·HUD·per-cell 색인코딩 |
| 좌표 변환 | 완료. hr35 `ai_grid_alignment` 정본과 차등 검증 |
| grid map 높이 샘플링 | 완료. `info.pose` + column-major 순환버퍼 반영 |
| per-cell 잔여량 색 | 완료. `/task_info`의 current−target 사용 |
| 테스트 | 133개 통과 |
| **카메라 외부 파라미터** | **미보정 — 아래 A** |
| **Stage 2 수용 검증** | **미실시 — 아래 C** |
| **GUI 표시 패널** | **부재 — 아래 D** |

의뢰서 §8 수용 기준 중 5(발행 안정성)와 부분적으로 6(범례·텍스트)만 충족. 1·2·3·4는
보정이 선행되어야 판정 가능하다.

---

## A. LiDAR ↔ 카메라 외부 파라미터 보정 【최우선 · 임계경로】

### 왜 최우선인가
TF 트리에서 카메라만 고아라 `map` → 픽셀 경로가 없다. 이게 없으면 오버레이의 모든
기하 산출물이 "그럴듯하지만 틀린 그림"이다. 나머지 항목 대부분이 여기에 걸려 있다.

### 현재 값과 그 한계
`config/lidar_projection_params.yaml`의 `extrinsic.xyz/rpy`에 **coarse 값**이 들어 있다.
2026-08-12 팔레트 장면 1장으로 엣지 정합을 돌려 얻은 값이며, 신뢰할 수 없다:

| | 실측 | 요구치 | 배수 |
|---|---|---|---|
| 회전 (5회 재시작 편차) | 평균 2.94°, 최대 4.32° | ≤0.72° | 4~6배 부족 |
| 병진 편차 (x/y/z) | 0.108 / 0.134 / 0.210 m | ≤0.075 m | 최대 2.8배 |
| \|t\| 수렴 | 탐색 경계 0.60 m에 붙음 | — | 미수렴 |

병진을 자유롭게 두면 t_x = 4.36 m가 나온다. 같은 붐 브래킷의 두 센서 사이로는 불가능한
값으로, **단일 시점 축퇴**의 직접 증거다.

### 필요 정확도의 근거
grid 셀 0.15 m를 셀 1/2(0.075 m)까지 판정하려면, 대표 굴착 거리 6 m에서 **0.72°**가
필요하다. 눈대중은 1~2°로 6 m에서 셀 1개 이상 오차 — 이 프로젝트가 잡아내려는 오차와
같은 크기라 자기모순이 된다.

### 해야 할 실험
상세 절차: `docs/lidar_camera_calibration_protocol.md`

기계·붐 고정, **팔레트만 옮기며** 20초씩:
```bash
src/excavator_ar_overlay/scripts/record_calib_capture.sh pose01 20
```

| # | 배치 | 목적 |
|---|---|---|
| 1 | 4.5 m 중앙 | 기준 |
| 2 | **2.5 m 중앙** | 거리 다양성 — 축퇴 해소의 핵심 |
| 3 | **7~8 m 중앙** | 거리 다양성 |
| 4 | 4.5 m 화면 좌단 | 주점 부근 축퇴 해소 |
| 5 | 4.5 m 화면 우단 | 동상 |
| 6~8 | 붐 각도 2~3개로 위 반복 | 교차검증 |

**정지 필수**: Ouster는 센서 uptime(약 1e4 s), ZED는 epoch(약 1e9 s)로 스탬프를 찍어
두 스트림을 시간 정렬할 수 없다. 정지 장면이면 이 문제가 사라진다.

체커보드는 불필요하다. 현 장면의 계단·난간(2~15 m 직선), 펜스(평면), 연석(수평 엣지),
팔레트(근거리 실루엣)로 충분하다는 것을 실측으로 확인했다. 방위각도 272~277°로 좁게
수렴했다.

### 캡처 후 (코드 작업, 실험 아님)
1. 다중 시점 번들 최적화 → `T_camera ← lidar_boom/os_lidar`
2. 자세를 학습/검증으로 분할해 교차검증, 잔차 리포트
3. `extrinsic.xyz/rpy` 갱신 → 확정 시 `static_transform_publisher`나 URDF로 이관하고
   `extrinsic.publish_static_tf: false`

### 완료 판정
- 붐 각도별로 따로 풀어도 값이 일치 (흩어지면 체인에 모델링 안 된 자유도가 있다는 신호,
  `gridmap_diag/calib_crossval.py`와 같은 논리)
- 오버레이에서 LiDAR 점의 깊이 불연속이 실제 물체 윤곽에 걸침 (의뢰서 §8-1)

---

## B. LiDAR 프레임 이중화 판정 【A와 같은 데이터로 해결】

### 문제
같은 물리 센서가 TF에 두 개의 다른 pose로 존재한다.
```
map → gm_os_lidar           [2.209, 0.065, 2.113]   붐 기구학 (붐 따라 움직임)
map → lidar_boom/os_sensor  [0, 0, 2.0]             bringup 하드코딩 placeholder
차이: 2.141 m, yaw 17.2°
```
출처는 `hr35_bringup/launch/boom_only_driver.launch.py:79`의
`'0','0','2','0','0','-1.5708'`. 포인트클라우드는 **placeholder 쪽**에 매달려 있다.

### 왜 지금 결정해야 하나
A의 보정은 센서↔센서 직접 변환이라 이 문제와 무관하게 풀린다. 그러나 grid map(`map`
프레임)을 카메라로 투영하려면 카메라를 **기구학 체인**에 앵커해야 하므로, 어느 쪽이
물리적으로 맞는지 확정되어야 Stage 2가 정합성을 갖는다.

### 판별 방법
붐을 스윕하며 지면 평면 높이가 붐 각도에 의존하는지 본다 — 지면은 안 움직이므로 맵
프레임에서 본 높이는 붐 각도와 무관해야 한다. 판별 스크립트가 이미 있다:
`~/repos/ontariotech_koceti_jetson_docker/gridmap_diag/calib_a_lidar.py`.

**A의 6~8번(붐 각도 캡처)이 이 검증 데이터로 그대로 쓰인다.** 별도 실험 불필요.

### 결정 후 조치
`grid.anchor_frame` 파라미터로 이미 노출되어 있어 코드 변경 없이 전환 가능하다.
placeholder를 제거할지 여부는 다른 노드(ouster 드라이버 등)의 의존을 확인해야 한다.

---

## C. Stage 2 수용 기준 검증 【A 완료 후】

의뢰서 §8의 2·3·4번은 보정 없이는 판정 자체가 무의미하다.

| # | 기준 | 검증 방법 | 선행조건 |
|---|---|---|---|
| 2 | AI가 dig를 선택했을 때 오버레이 셀이 실제 굴착 위치와 일치 | 굴착 전/후 영상 비교 | A |
| 3 | 오버레이 셀의 물리좌표가 `/ai_coordinate_diagnostics`의 `commanded_physical`·`true_cell_physical`과 일치 | JSON 대조 | A |
| 4 | phase=idle에서 사라지고, dig 중엔 메시지 없어도 유지 | 실기 phase 전이 관찰 | 없음 — **지금 가능** |

4번은 지금 검증 가능하다. `/ai_status/action`이 살아 있고(hr35 `excavator_msgs`
재빌드 완료) 노드가 `ActionRetainer`로 보존 정책을 구현하고 있으므로, AI를 한 사이클
돌리며 오버레이가 30초 침묵을 견디는지, idle에서 지워지는지 보면 된다.

### 지금 바로 할 수 있는 것
```bash
source /opt/ros/humble/setup.bash
source ~/robot_ws/install/setup.bash
source ~/hr35/install/setup.bash      # AiActionStatus / TaskInfo
ros2 launch excavator_ar_overlay lidar_projection.launch.py
```
HUD에 `dig plan: <phase>`와 `colour: per-cell (n/m)`이 뜨면 배선이 살아 있는 것이다.

---

## D. GUI 연결 【파라미터 1줄 — 구현 불필요】

> **정정 (2026-08-13).** 이 항목은 처음에 "GUI 패널이 없으니 새로 만들어야 한다"고
> 적었으나 **틀렸다.** hr35 소스 트리 grep으로는 안 나왔는데, 이 머신의 hr35 체크아웃이
> 8개월 낡아서였다. 실행 중인 GUI 노드를 직접 조회하니 패널이 이미 있고 토픽까지
> 파라미터화되어 있다. 의뢰서 §2의 주장이 맞았다.

### 실제 상태
```
$ ros2 param get /task_config_gui_node ai_camera_image_topic
/zedx_boom/zedx_boom_node/left/image_rect_color/compressed
$ ros2 param get /task_config_gui_node ai_camera_max_fps
10.0
```
`ros2 param describe` 결과 read_only 표시가 없으므로 런타임 설정을 받는다.
오버레이는 2 Hz라 `ai_camera_max_fps: 10.0` 상한에 걸리지 않는다.

### 연결 방법
```bash
ros2 param set /task_config_gui_node ai_camera_image_topic \
  /excavator/perception/dig_overlay/compressed
```
값은 받아들여지지만 **GUI가 콜백에서 실제로 재구독하는지는 확인되지 않았다.** 화면이
안 바뀌면 GUI 설정 파일을 고치고 재시작해야 한다. 되돌리려면 위 기본값을 다시 넣으면 된다.

### 주의 — 입력 토픽 계열 불일치
GUI 파라미터 설명에 이런 실측 기록이 있다:

> rgb/ 계열은 ZED 노드가 살아있어도 프레임을 발행하지 않는 것이 실측돼(18초 0장)
> left/ 를 기본값으로 쓴다. 둘은 동일 센서다.

그런데 이 오버레이 노드는 `topics.image_in`에 **rgb/ 계열**을 쓰고 있고, 2026-08-12~13
실측에서는 정상 수신됐다(2 Hz, 프레임 캡처 성공). 두 관측이 엇갈리므로, GUI 연결 시점에
오버레이 입력이 비면 `topics.image_in`을 left/ 계열로 바꿔 볼 것. 파라미터라 재빌드는
필요 없다.

---

## E. 코드 품질 잔여 (실험 불필요, 낮은 우선순위)

- `lidar_projection_node.py`가 549 LOC로 프로젝트 가이드라인(250) 초과.
  dig 레이어(~140줄)와 LiDAR 레이어(~40줄)를 별도 모듈로 분리하면 해소된다.
  기능 영향 없음.
- 노드 자체의 통합 테스트 없음(순수 모듈은 133개로 커버). rclpy 픽스처가 필요해
  비용 대비 효용을 따져볼 것.

---

## 권장 순서

```
0. D 연결 (파라미터 1줄)     ← 가장 싸다. C-4를 GUI에서 보려면 선행 필요
1. C-4 phase 전이 검증       ← A와 무관. 지금 가능
2. A 캡처 (현장 20분)        ← 임계경로. 나머지 대부분이 여기 걸림
3. A 후처리 + B 판정 (코드)   ← 같은 데이터로 둘 다 해결
4. C-2, C-3 수용 검증
5. E 정리
```

C-4(phase 전이)만 A와 무관하게 지금 검증 가능하므로, 현장 일정이 안 잡히면 그것부터
해도 된다.
