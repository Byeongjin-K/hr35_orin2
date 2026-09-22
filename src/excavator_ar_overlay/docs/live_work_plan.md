# 남은 작업 계획 — 라이브/실험이 필요한 항목

작성 2026-08-13. 코드로 끝낼 수 있는 부분은 모두 반영된 상태이며, 여기 있는 것은
**장비·현장·타 저장소 접근이 있어야만** 진행되는 항목이다.

> **2026-08-13 개정 — 대상 카메라가 붐 → 캐빈으로 바뀌었다.**
> 붐 하단 카메라는 각도상 버킷이 닿는 작업영역을 대부분 보지 못한다.
> 코드·설정 기본값은 모두 `zedx_cabin` 으로 교체됐다. 그런데 이건 토픽만
> 바뀌는 변경이 아니다:
>
> * 카메라는 **캐빈**, LiDAR는 **붐**에 있어 둘은 강체가 아니다. 동일 시각 실측에서
>   `gm_swing_axis` ⋯ -4.68도, `gm_lidar_mount` ⋯ -44.20도였고, 붐은 같은 날
>   오전 -31.9도에서 오후 -44.2도로 12.3도 움직였다.
> * 따라서 구해야 하는 것은 `T_camera ← lidar` 가 아니라
>   **`T_camera ← gm_swing_axis`** (캐빈 강체) 다. 이것만이 상수다.
> * **A와 B의 순서가 뒤집혔다.** 아래 B항 참조.
> * 이전 coarse extrinsic 값(2026-08-12, 붐 카메라↔LiDAR)은 이전되지 않아 0으로
>   되돌렸다.
>
> 부수적으로 큰 이득이 있다: dig 셀이 이미 `gm_swing_axis`에서 계산되므로
> 셀→픽셀이 **상수 변환 하나**로 줄고, 붐 기구학 오차가 Stage 2 오버레이로
> 아예 새지 않는다.

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

## B. LiDAR 프레임 이중화 판정 【순서 역전 — 이제 A의 선행조건】

> **2026-08-13 개정.** 이전엔 "A와 같은 데이터로 같이 해결"이라 적었으나, 카메라가
> 캐빈으로 옥기면서 **B를 먼저 풀어야 하는 구조**가 됐다.
>
> 캐빈 카메라로 클라우드를 옮기려면
> `lidar_boom/os_lidar → map → gm_swing_axis → camera` 를 거치는데, 첫 구간이
> placeholder다. 즉 B의 오차가 A의 관측식에 직접 들어온다. 붐 카메라 때는
> 센서↔센서 직접 변환이라 이 문제를 피해갔지만 이젠 아니다.
>
> 오버레이로 두 체인을 직접 비교해 봤지만 **가릴 수 없었다**: placeholder는 800점이
> 좌하단에 몰리고 `gm_os_lidar`는 13442점이 상단을 덮는데, 카메라 외부 파라미터가
> 미보정이라 두 오차가 섞여 분리되지 않는다. 비교용 파라미터는
> `lidar.override_frame` 으로 남겨둔다(빈 문자열=헤더 프레임, `gm_os_lidar`=기구학).
>
> 따라서 B는 **카메라와 무관하게** 판정해야 한다 — 붐을 스윈하며 맵 프레임에서 본
> 지면 평면 높이가 붐 각도에 의존하는지 보는 방식(`calib_a_lidar.py`)이다.
> 그 데이터는 A의 붐 각도 캡처와 동일하므로, **한 번 캡처해서 B를 먼저 풀고 그
> 결과로 A를 푸는** 순서가 된다.

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
오버레이 쪽은 `lidar.override_frame: 'gm_os_lidar'` 로 이미 우회 중이다.

### 2026-09-22 라이브 재확인 — 붐 스윕 없이, 한 포즈로 재판정

08-18 판정은 붐 8포즈가 필요했다. 그 사이 `/rn/grid_map` 이 살아나서(34×67, res 0.15,
frame `map`, 유효 2084/2278) **기계와 독립적인 지형 기준**이 생겼으므로, 이제 한
포즈에서 끝난다. 셀 481개의 중심에서 라이다 지면(하위 20 퍼센타일)과 grid map 고도를
비교했다:

| 체인 | \|dz\| 중앙값 | p90 | 편향 | 매칭 셀 |
|---|---|---|---|---|
| `gm_os_lidar` | **0.065 m** | 0.240 m | -0.021 m | 225/481 |
| `lidar_boom/os_lidar` | **1.776 m** | 2.838 m | -1.776 m | 164/481 |

기구학 체인만이 **반 셀(0.075 m) 안에서** dig 레이어가 읽는 지형과 일치한다. 이것이
Stage 2 에서 실제로 중요한 판정이다 — 절대 진리가 아니라 *두 레이어가 서로 맞는가*.

붐각 의존성도 우연히 다시 잡혔다: 같은 비교를 몇 분 간격으로 두 번 돌리는 사이 붐이
움직였고, placeholder 편향이 **+0.541 m → -1.776 m** 로 바뀌었다. 기구학 체인은 그
사이에도 0.065 m 를 유지했다.

재현: `/tmp` 스크래치로 돌렸다. 필요하면 위 설명대로 다시 작성한다 —
`ElevationGrid.from_message` + `target_pick.points_between_frames` 두 줄이 전부다.

### placeholder 근본 수정 — 2026-09-22 **적용 완료**

승인 후 붐 쪽 두 런치를 고쳤다(`boom_only_driver.launch.py`, `dual_lidar.launch.py`).
**캐빈은 손대지 않았다** — `dual_lidar.launch.py:139` 의 `map → lidar_cabin/os_sensor`
(pitch 0.25 고정)도 같은 패턴이지만, 캐빈 라이다는 떠 있지도 않고 대응하는 기구학
프레임을 실측한 적이 없다. 근거 없이 같이 고치지 않는다.

아래는 그 판단의 근거와 실측값이다.

**1) placeholder 가 런치마다 값이 다르다 — 같은 프레임, 두 개의 거짓말**

| 런치 | 발행 값 (map → `lidar_boom/os_sensor`) |
|---|---|
| `hr35_bringup/launch/boom_only_driver.launch.py:79` | xyz `[0, 0, 2]`, rpy `[0, 0, -1.5708]` |
| `hr35_bringup/launch/dual_lidar.launch.py:151` | xyz `[1.9, -0.5, -0.9]`, rpy `[-1.5708, 0, 0]` |

08-18 세션이 측정한 3.128 m / 50.37° 오차는 **boom_only 기동 때의 값**이다. dual 로
띄우면 오차의 크기와 방향이 달라질 뿐 붐각 무시라는 성질은 같다. 캐빈도 같은 패턴이다
(`dual_lidar.launch.py:139`, pitch 0.25 고정).

**2) 소비자**

| 소비자 | 영향 |
|---|---|
| `pointcloud_to_gridmap` (`config/grid_map_params.yaml`: `/lidar_boom/points` → `frame_id: map`) | TF로 map 변환하므로 실행하면 **같은 오차를 그대로 물려받는다** (붐각당 53.9 mm). 다만 2026-09-22 라이브 그래프에는 **떠 있지 않다** — 아래 4) 참조 |
| `dual_lidar_viz.rviz`, `lidar_boom_viz.rviz` | 표시 전용 |
| AR 오버레이 | `lidar.override_frame` 으로 이미 우회 |

**3) 권고: 지우지 말고 부모를 바꾼다**

드라이버가 `os_sensor → os_lidar` 를 스스로 발행하므로 앵커가 필요한 프레임은
`os_sensor` 하나다. 지금처럼 `map` 에 매달면 붐 회전이 통째로 빠지지만, 부모를
기구학 프레임으로 바꾸면 붐과 함께 움직이고 **소비자 전부가 코드 변경 없이** 맞는
값을 받는다.

```
현재:  map            --static-->  lidar_boom/os_sensor  --driver-->  lidar_boom/os_lidar
권고:  gm_os_lidar    --static-->  lidar_boom/os_sensor  --driver-->  lidar_boom/os_lidar
```

필요한 상수는 드라이버가 발행하는 `os_sensor → os_lidar` 의 역변환 하나다.
**2026-09-22 직접 실측 완료** — 유도한 값이 아니라 TF 에서 그대로 읽은 값이다:

```
$ ros2 run tf2_ros tf2_echo lidar_boom/os_lidar lidar_boom/os_sensor
- Translation: [0.000, 0.000, -0.038]
- Rotation: in RPY (degree) [0.000, -0.000, 180.000]
```

이것이 곧 `gm_os_lidar → lidar_boom/os_sensor` 에 넣을 값이다(전제는 아래).

두 런치에 들어간 인자는 다음과 같다:

```
--x 0 --y 0 --z -0.038 --roll 0 --pitch 0 --yaw 3.14159265
--frame-id gm_os_lidar --child-frame-id lidar_boom/os_sensor
```

**적용 전에 라이브로 검증했다** — 옛 값이 위치 인자(`x y z yaw pitch roll`)였던 탓에
규약 착오가 바로 이 버그의 출발점이었으므로, 인자 해석 자체를 확인해야 했다. 같은
인자로 `lidar_boom/os_sensor_test` 라는 임시 프레임을 띄우고, 거기에 드라이버의
`os_sensor → os_lidar` 를 합성한 결과를 살아 있는 `map → gm_os_lidar` 와 비교했다:

```
map -> os_sensor_test           t = [1.9687, 0.7359, 1.9168]
  o driver os_sensor->os_lidar
  = predicted map -> os_lidar   t = [1.9524, 0.7704, 1.9166]
live map -> gm_os_lidar         t = [1.9525, 0.7702, 1.9166]
difference: 0.19 mm, 0.0000 deg   -> MATCH
```

(0.19 mm 는 두 조회 사이에 붐이 미세하게 움직인 양이다. 임시 프레임은 검증 후 내렸다.)

**부작용 하나는 알고 있어야 한다**: 이제 `map → lidar_boom/*` 는 `gm_` 프레임을 발행하는
스택이 떠 있을 때만 존재한다. 안 떠 있으면 변환이 **틀린 값이 아니라 아예 없다.** 위
4-(c) 에 적은 대로 그 스택은 간헐적이므로, RViz 나 `pointcloud_to_gridmap` 이 조용히
비는 구간이 생길 수 있다 — 종전의 "항상 있지만 몇 m 틀린" 상태보다 낫다고 판단했다.

**기동 확인 (같은 날 13:13 재기동분)**. 고친 런치로 올라온 `tf_publisher_boom` 에서
실제 트리를 읽었다:

```
$ ros2 run tf2_ros tf2_echo gm_os_lidar lidar_boom/os_sensor
- Translation: [0.000, 0.000, -0.038]      rpy [0, 0, 180 deg]     <- 새 static

$ ros2 run tf2_ros tf2_echo gm_os_lidar lidar_boom/os_lidar
- Translation: [0.000, 0.000, 0.000]       rpy [0, 0, 0]           <- 드라이버까지 합성
```

두 번째가 **항등**이다 — 헤더 프레임 `lidar_boom/os_lidar` 가 이제 기구학 프레임과
같은 것을 가리킨다는 뜻이고, 이 수정이 목표한 바로 그 상태다. 덕분에 AR 의
`lidar.override_frame` 은 결과에 영향을 주지 않는 값이 됐다(고치기 전 bringup 으로
띄운 세션을 위해 남겨 둔다).

예고한 부작용도 같이 관측됐다: 그 시점 rn 스택이 내려가 있어
`tf2_echo map lidar_boom/os_lidar` 는 `frame does not exist` 로 실패한다. 의도된
동작이다.

전제: `gm_os_lidar` 가 물리 os_lidar 프레임과 위치·자세 모두 일치한다는 것(08-18 지면
불변량 검증과 09-22 grid map 대조가 이를 지지한다). 적용 직후
`tf2_echo map lidar_boom/os_lidar` 와 `tf2_echo map gm_os_lidar` 가 일치하는지 확인하면
전제까지 함께 검증된다.

현재 어긋난 양(2026-09-22 한 포즈 실측, `tf2_echo gm_os_lidar lidar_boom/os_lidar`):

```
- Translation: [2.219, 0.531, 0.181]      -> 2.289 m
- Rotation: in RPY (degree) [-0.24, 0.64, -0.26]
```

회전은 이 포즈에서 우연히 0.7° 안으로 맞는다 — **자세만 보고 placeholder 가 맞다고
판단하면 안 되는 이유다.** 08-18 에는 같은 쌍이 yaw 17.2° 로 어긋나 있었다.

적용하면 오버레이의 `lidar.override_frame` 은 빈 문자열로 되돌릴 수 있고, B의 판정
근거였던 "맵 프레임 지면 높이의 붐각 무의존성"이 그리드맵에도 성립하게 된다.

**4) 곁가지로 발견한 것 (AR 범위 밖, 미수정)**

**(a) 이름이 겹친다 — 헷갈리지 말 것.** 라이브 그래프에 `/grid_map_node` 가 있지만
이것은 이 워크스페이스의 `pointcloud_to_gridmap` 이 **아니다.** rn 파이프라인 쪽
노드이며(`/rn/original/voxel_point_cloud` 구독 → `/rn/grid_map`·`/height_array` 발행),
`pointcloud_to_gridmap` 은 아예 떠 있지 않다. 더 나쁜 것은 `/grid_map_node` 라는
**동일 이름의 노드가 두 개** 떠 있다는 점이다(`ros2 node list` 가 경고를 낸다.
하나가 voxel cloud 를 발행하고 다른 하나가 그것을 구독한다). 파라미터 서비스·이름
해석이 어느 쪽으로 갈지 보장되지 않으므로 rn 쪽에 보고할 값어치가 있다.

**(b) 파라미터 키 불일치.** `config/grid_map_params.yaml` 의 최상위 키는
`grid_map_node:` 인데, 이 워크스페이스의 노드는 자신을 `pointcloud_to_gridmap` 으로
이름 짓는다(`pointcloud_to_gridmap.cpp:108`, 런치의 `name=` 도 동일). 키가 안 맞으면
파라미터 파일이 통째로 무시되어 기본값 `pointcloud_topic: /ouster/points` 로 뜬다 —
그 토픽은 이 워크스페이스에 없다. 공교롭게도 그 yaml 키는 rn 쪽 노드 이름과 같아서
더 헷갈린다. 띄울 일이 생기면
`ros2 param get /pointcloud_to_gridmap pointcloud_topic` 으로 먼저 확인할 것.

**(c) `/rn/grid_map` 발행이 간헐적이다.** 09-22 관측에서 10 Hz 로 나오다가 수 분간
완전히 멎었고(그 구간엔 `gm_*` TF 도 함께 사라졌다), 다시 살아났다. 상류
`/lidar_boom/points`(9.9 Hz)와 `/local_pc`(9.9 Hz)는 그 동안에도 살아 있었으므로
끊김은 rn voxelizer 단계다. **캡처 세션을 잡기 전에 `gm_*` TF 가 안정적으로 나오는지
먼저 확인해야 한다** — 캡처 노드는 이제 TF 가 없으면 저장을 거부하므로 세션 도중
조용히 건너뛰는 구간이 생길 수 있다.

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
실측에서는 정상 수신됐다(2 Hz, 프레임 캡처 성공).

**2026-09-22 재측정으로 정리됨**: 캐빈 카메라에서 `rgb/image_rect_color/compressed`
10.1 Hz, `left/image_rect_color/compressed` 10.3 Hz 로 **둘 다 정상 발행**이다. GUI
파라미터 설명의 "rgb 계열 0장" 기록은 이 날짜 기준으로 재현되지 않는다. 그래도 GUI 연결
시점에 오버레이 입력이 비면 `topics.image_in`을 left/ 계열로 바꿔 볼 것. 파라미터라
재빌드는 필요 없다.

---

## E. 코드 품질 잔여 (실험 불필요, 낮은 우선순위)

> **2026-09-22 갱신.** 아래 두 항목은 모두 닫혔고, 캡처 저장 형식도 개선했다.

- ~~`lidar_projection_node.py` 549 LOC~~ → 2026-09-07 `layers.py` / `projection_render.py`
  분리로 해소.
- ~~노드 통합 테스트 없음~~ → `test/test_snapshot_capture_node.py` 가 rclpy 픽스처로
  캡처 노드를 합성 메시지로 구동해 실제로 쓰이는 파일(클라우드·이미지·meta)을 검증한다.
  하드웨어·토픽 불필요. 현재 전체 195개 통과.
- 캡처 클라우드가 조직화 `(height, width, 4)` x·y·z·intensity 로 저장된다
  (무반사 빔은 NaN). 08-18 세션 노트가 지적한 "평탄화 때문에 거리 불연속을 각도
  재binning 으로 근사" 문제와 §9 대안(반사강도 기반 검출)의 선행 코드 작업이 함께 닫혔다.
  기존 평면 `(N, 3)` 캡처는 `target_pick.xyz_from_capture` 가 그대로 읽는다.
- 남은 것: 투영 노드(`LidarProjectionNode`) 자체의 통합 테스트. 캡처 노드와 달리
  이미지·TF·GridMap 픽스처가 전부 필요해 비용이 크고, 순수 모듈 커버리지가 이미 높다.

---

## 권장 순서

```
0. D 연결 (파라미터 1줄)     ← 가장 싸다. C-4를 GUI에서 보려면 선행 필요
1. C-4 phase 전이 검증       ← A와 무관. 지금 가능
2. 캡처 (현장 30분)          ← 붐 각도 3개 × 거리 3구간. B와 A가 같은 데이터를 쓴다
3. B 판정 (코드)            ← 카메라 무관. 지면 높이의 붐각 무의존성
4. A 보정 (코드)            ← B가 고른 체인 위에서 T_camera←gm_swing_axis 풀이
5. C-2, C-3 수용 검증
6. E 정리
```

C-4(phase 전이)만 A와 무관하게 지금 검증 가능하므로, 현장 일정이 안 잡히면 그것부터
해도 된다.
