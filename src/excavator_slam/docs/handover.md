# 재개 안내 — 굴착기 LiDAR SLAM (feature/lidar-slam)

마지막 작업: 2026-09-09
워크트리: `/home/kimm/robot_ws-slam` (브랜치 `feature/lidar-slam`)
전체 실행 기록(모든 실패와 그 진단 과정 포함): `/home/kimm/data/ulw_slam_artifacts/notepad.md`

---

## 0. 한 줄 요약

GLIM(LiDAR-관성 SLAM)이 이 Jetson에서 **실시간의 3배**로 돌고, 재방문 정합에서 현재 배포본을
**최소 4배** 이깁니다. 다만 **지금 붐 라이다의 IMU가 안 나오고 있어서** 그것부터 풀어야
다음 단계(현장 녹화)가 진행됩니다.

방향 결정(D3)은 **(a) 현장 데이터 먼저**로 확정됐습니다.

---

## 1. 재개하면 가장 먼저 볼 것 — 막혀 있는 것 3개

### (1) ★최우선: 붐 라이다 IMU가 안 나옵니다

~~~
/lidar_boom/points        9.971 Hz   정상
/lidar_boom/imu           30초 창에서 메시지 0건   (발행자는 1개 등록돼 있음)
/lidar_boom/imu_packets   ABSENT     ← 원시 UDP 단계에서 이미 없음
~~~

**IMU가 없으면 LiDAR-관성 SLAM이 성립하지 않습니다.** GLIM이 회전오차를 1.07도에서
0.14도로 줄인 것이 전적으로 IMU 덕분입니다.

이미 배제된 원인 (전부 실측):

| 확인 항목 | 결과 | 의미 |
|---|---|---|
| `proc_mask` | `IMU|PCL|SCAN|IMG|RAW` | IMU 플래그 켜져 있음 — 드라이버 설정 문제 아님 |
| 호스트 UDP 7513 | `UNCONN *:7513` | 드라이버가 정상적으로 듣고 있음 |
| 센서 HTTP API | `udp_dest=192.168.0.10, udp_port_imu=7513` | 센서 설정도 목적지가 맞음 |
| 같은 센서의 라이다 UDP 7512 | 9.97 Hz 수신 | 네트워크 경로 자체는 살아 있음 |

즉 **양쪽 설정이 다 맞는데 IMU UDP만 안 옵니다.** 남은 후보:

1. 센서 펌웨어가 재시작 후 IMU 스트림을 안 켠 상태 (3.2 펌웨어에서 STANDBY 문제가
   이미 한 번 있었고, main의 `bd9cf97`이 `operating_mode: NORMAL`로 그걸 막았습니다.
   비슷한 성질일 가능성)
2. 방화벽/라우팅이 7512는 통과시키고 7513만 막음
3. 드라이버가 IMU 소켓을 열었지만 센서가 그 목적지로 안 보냄

**다음에 확인할 것 (순서대로):**

~~~bash
# 1) UDP가 실제로 도착하는지 커널 레벨에서 직접 본다 (ROS를 배제)
sudo tcpdump -i any -n udp port 7513 -c 5      # 라이다는 7512로 바꿔서 대조
# 2) 센서를 재설정해서 IMU 스트림을 다시 켜본다
curl -s http://192.168.0.5/api/v1/sensor/config | python3 -m json.tool
# 3) 드라이버 로그에 IMU 관련 경고가 있는지 (드라이버는 PID 11973으로 떠 있었음)
~~~

### (2) 캐빈 라이다가 안 켜져 있습니다

현재 붐 드라이버 하나만 떠 있습니다 (`os_driver ... __ns:=/lidar_boom`).
`/lidar_cabin/*` 토픽 0개.

리서치 두 레인이 공통으로 지적한 결론이 있습니다 — **SLAM 주 센서는 캐빈이어야 합니다.**
그리고 이번 세션에서 그 이유를 실측으로 확인했습니다 (아래 3-6 참조).

### (3) 브링업 수정 4개가 main에 반영돼 있지 않습니다

컨펌받은 A1~A7이 이 브랜치에만 있고 **실제 장비에는 적용 안 됨**입니다.
지금 도는 드라이버도 `install/hr35_bringup/.../lidar_boom_params.yaml` (main 기준)을
읽고 있어서, `scan`·이미지 4종·패킷을 여전히 전부 만들고 있습니다.

| 커밋 | 내용 |
|---|---|
| `0825809` | **캐빈 라이다 `timestamp_mode` → `TIME_FROM_ROS_TIME`** (이게 빠지면 새 bag이 못 씀) |
| `461a92c` | `proc_mask` → `IMU|PCL`, 캐빈 QoS 일치, 모드·프로파일 명시, 재접속 켬 |
| `64243d3` | `dual_lidar.launch.py` RViz 기본 끔 |
| `26e87b1` | 루트 `config/` 낡은 사본 → 심링크 |

**체리픽 예행을 이미 해봤고 4개 전부 깨끗하게 통과했습니다** (임시 워크트리에서, main 무손상).
main이 그 사이 움직였지만(`operating_mode: NORMAL` 추가, ouster-ros 0.15.1) 파일 내
다른 구역이라 충돌 없고, `operating_mode: NORMAL`도 보존됩니다.

~~~bash
cd /home/kimm/robot_ws
git cherry-pick -x 0825809 461a92c 64243d3 26e87b1
colcon build --packages-select hr35_bringup
# 그 다음 드라이버 재시작 (운영 중단 동작이므로 타이밍 선택 필요)
ros2 launch hr35_bringup dual_lidar.launch.py
~~~

**SLAM 패키지는 따라가지 않습니다** — 성능 승인 후에만.

---

## 2. 다음 작업 순서

1. **붐 IMU 복구** (위 1-(1)). 이게 안 되면 나머지가 의미 없음.
2. **브링업 4커밋 main 반영 + 빌드 + 캐빈/붐 동시 기동** (위 1-(3), 1-(2)).
3. **현장 녹화** — 스크립트 준비돼 있음:
   ~~~bash
   ~/robot_ws-slam/src/excavator_slam/scripts/record_field_session.sh <출력경로> <초>
   ~~~
   녹화 전 사전 점검을 스스로 합니다 (미들웨어 자동 선택 / GNSS quality 4 확인 /
   라이다 헤더 시각이 벽시계와 몇 초 이내인지). **점검 실패 시 녹화를 시작하지 않습니다** —
   현장 한 번 다녀와서 데이터가 못 쓰는 것이면 회복이 안 되기 때문.

   **녹화 시나리오 (5~10분)**: 정지 30초 → 주행 없이 좌우 크게 스윙 →
   **판 적 없는 지면을 30~50 m 왕복 2~3회** → 굴착 몇 사이클.
   왕복이 핵심입니다. 지금 보유한 bag에는 **주행 재방문이 0개**라서 루프클로저를
   아예 못 재고 있습니다.
4. **RTK 데이터로 baseline 재측정** → 그때 비로소 공정한 SLAM 대 배포본 판정이 됩니다.
5. (선택) `glim_ext` 소스 빌드 — ScanContext 장소인식 + GNSS 팩터. PPA에 없어서
   직접 빌드해야 합니다.

---

## 3. 측정으로 확인된 사실

### 3-1. 현재 전역맵은 구조적으로 재방문을 못 맞춥니다

`rn_global_map`은 SLAM이 아니라 **개루프 GNSS 앵커**입니다:

~~~
p_world = Rz(90 - psi_cab - s*swing - off) * p_map + ENU(GPS) - lever_arm
~~~

스캔매칭이 없으므로 "어긋났네, 맞추자"를 할 수가 없습니다. 헤딩 오차가 그대로 맵에 쌓입니다.

### 3-2. 핵심 비교 결과 (정지 스윙-재방문)

창 A=[146,166]s, B=[208.5,228.5]s. 기계가 두 창 사이에 **7.7 cm**만 이동, 62초 간격,
스윙 겹침 94도. 위치 오차가 상쇄되어 **자세/헤딩 사슬만** 시험대에 남는 구간입니다.
동일 창·동일 크롭·동일 지표, 포즈 소스만 다릅니다.

| | GNSS 앵커 (배포본) | GLIM |
|---|---|---|
| **높이 불일치 rms** (탐색 없음) | 0.321 m | **0.137 m** |
| dz p90 | 0.862 m | **0.570 m** |
| **수평 어긋남** | **>=1.658 m** (포화 = 하한값) | **0.399 m** (수렴) |
| dz 중앙값 | **0.195 m** | 0.247 m |
| dz 편향 | **+0.007 m** | +0.209 m |
| 최근접점 중앙값 | 0.0495 m | 0.0495 m |

**읽는 법**: 재방문 정합(수평)은 GLIM이 최소 4배 이깁니다 — 배포본은 탐색 상자 벽에 붙어
하한값밖에 못 내고, GLIM은 실제로 수렴합니다. 높이 산포도 2.3배 좋습니다.
**지는 칸은 절대 수직 기준점 하나**뿐이고, GNSS 팩터가 없기 때문입니다.

목표치(수평 <=0.15 m, |dz| <=0.05 m)는 **양쪽 다 미달**입니다. 다만 이 데이터는 최악 조건입니다:
RTK 없음, 붐 라이다 단독, 루프클로저 확장 없음.

### 3-3. GLIM 성능

~~~
270초 bag을 88초에 처리 = RTF 3.07  (CPU 전용, CUDA 미사용)
IMU better ratio (회전)  0.13 -> 0.86
회전 오차               1.07도 -> 0.14도
~~~

실시간 게이트 1.0의 3배이므로 GPU는 ZED나 다른 작업에 남겨둘 수 있습니다.

IMU 기여를 뒤집은 수정 두 가지 (둘 다 필수):
- **단일 클록 오프셋**: 토픽별 수신시각으로 재스탬프하면 클라우드가 IMU보다 0.1466초
  밀립니다. 가장 지연 적은 IMU 기준 상수 오프셋 하나(`1762215140.866238113` ns)를
  모든 헤더에 더해야 상호 타이밍이 보존됩니다.
- **`T_lidar_imu`**: 단위행렬이 아니라 **Z축 180도 yaw** + (0.002441, 0.009725, -0.030662) m.
  Ouster의 os_lidar 프레임이 os_sensor 대비 180도 돌아 있습니다.

### 3-4. GNSS 상태 — 중요한 변화

| | 보유 bag 전부 | 지금 라이브 |
|---|---|---|
| quality | **1** (단독 GPS) | **4** (RTK Fix) |
| 위성 / HDOP | 19~24 / — | 15 / 0.7 |

배포 노드는 `min_quality_ = 4` (RTK Fixed만 수용)입니다. 즉 **보유 bag은 배포 노드가
전량 거부했을 데이터**라, 지금까지의 baseline 수치는 공정한 비교가 아닙니다.
**지금 RTK가 잡혀 있으므로 새로 녹화하면 제대로 판정할 수 있습니다.**

### 3-5. 보유 bag의 한계

- 전부 `timestamp_mode: TIME_FROM_INTERNAL_OSC` — 라이다 헤더가 센서 부팅시각(~18300초),
  GNSS는 호스트 epoch(~1.76e9초). SLAM 도구가 스캔 **한 장만** 처리하고 나머지를 버립니다.
  `scripts/restamp_bag.py`로 먼저 재스탬프해야 합니다.
- **1104 bag에 주행 재방문이 0개**입니다. 정직한 필터(창이 실제로 한 자리에 머무는지,
  GNSS 글리치가 없는지)로 152창 중 115창이 쓸 만한데, "90초 이상 간격 + 같은 자리 +
  사이에 8 m 이상 이탈" 쌍은 **하나도 없습니다.**
- 특히 375~395초 구간은 GNSS 글리치 폭풍 위입니다: t=373.4에 **한 샘플(0.1초) 만에
  85.75 m 점프**, t=388.4~389.3에 연속 10샘플 약 1.2 m(= 43 km/h 지속).

### 3-6. ★ 붐 장착 센서에 GNSS를 그냥 융합하면 안 됩니다 (실측)

GLIM의 높이를 GNSS로 잡아주는 보정을 만들어 붙였더니 **모든 수치가 나빠졌습니다**
(dz 편향 +0.209 → +0.563). 원인:

~~~
창 A -> B (기계는 9.5 cm 이동)
  캡 안테나 높이   62.218 -> 62.234 m   =  +0.016 m
  붐 라이다 높이   -0.552 -> -1.107 m   =  -0.555 m
  붐 관절각        44.08 -> 32.46 도    =  -11.6 도
                   (/kine_data 와 /excavator/sensors/joint_boom 이 0.03도 이내 일치)
~~~

라이다가 붐 힌지에서 약 2.8 m 나와 있으니 11.6도가 정확히 0.55 m입니다.
즉 **GLIM은 표류한 게 아니라 내려가는 붐을 정확히 추적한 것**이고, 안테나는 캡에 있어
그 움직임을 볼 수 없습니다. 둘을 억지로 맞추면 붐 동작이 오차로 주입됩니다.

**결론**: 붐 장착 SLAM 센서에 GNSS를 융합하려면 운동학 체인(스윙축→붐힌지→붐링크→
라이다마운트)을 반드시 거쳐야 하는데, 그 체인이야말로 이 프로젝트가 벗어나려던 오차원입니다.
**캐빈 장착이면 안테나와 강체라 이 요구가 사라집니다.** 리서치가 인용으로 권고한 것을
실측으로 확인한 셈입니다.

### 3-7. 후보 판정

| 후보 | 판정 | 이유 |
|---|---|---|
| **GLIM** | **채택** | koide3 PPA가 arm64/ubuntu2204 제공. 설치·동작·성능 전부 확인 |
| MOLA | 폐기 | Humble/arm64 바이너리가 nanoflann >=1.5.1 요구, Ubuntu 22.04는 1.4.2뿐. 검사가 바이너리에 컴파일돼 있고 repo에 버전이 하나뿐이라 내려서 고정 불가. 파이프라인 4종 중 3종이 동일 KDTree 오류 |
| KISS-ICP | 보류 | `AnyReaderError: Bag contains no type definitions` — rosbags가 Humble bag에 typestore를 요구하는데 kiss-icp가 안 넘김. `rosbags<0.10` 핀도 동일 실패 |
| `glim_ext` | 미설치 | PPA에 없음(`glim`, `glim_ros` + CUDA 변형뿐). ScanContext 장소인식/GNSS 팩터가 필요하면 소스 빌드. 단 `libglobal_mapping.so`(서브맵 그래프 전역최적화)는 기본 포함이고 실행 중 실제로 between-factor를 만들고 있었음 |

---

## 4. 만든 것

### 패키지 `src/excavator_slam` (ament_python, 테스트 63개 통과)

| 파일 | 역할 |
|---|---|
| `excavator_slam/revisit_metric.py` | 재방문 정합 지표. 높이맵 DEM 상호정합 |
| `excavator_slam/gnss_anchor.py` | 배포 GNSS-앵커 체인 이식 (baseline) |
| `excavator_slam/submaps.py` | 두 후보가 **공유하는** 크롭 + 중력정렬 |
| `excavator_slam/georeference.py` | GNSS 기준점 보정. **붐 센서에는 쓰면 안 됨** (3-6) |
| `scripts/restamp_bag.py` | 단일 오프셋 재스탬프 |
| `scripts/baseline_submaps.py` | bag → 창별 클라우드/nav 캐시 |
| `scripts/anchor_submaps.py` | 캐시 → GNSS 앵커 월드 서브맵 + 채점 |
| `scripts/slam_submaps.py` | TUM 궤적 + 캐시 → SLAM 월드 서브맵 + 채점 |
| `scripts/record_field_session.sh` | 현장 녹화 (사전 점검 포함) |
| `launch/slam_offline.launch.py` + `scripts/glim_offline_entry.sh` | 오프라인 SLAM 실행 |
| `docker/glim.Dockerfile` | GLIM 이미지 (PPA 기반) |
| `docs/slam_candidates.md` | 후보 조사 메모 (10행, 전 행 URL) |

### 지표 설계에서 배운 것 (여기 시간을 가장 많이 썼습니다)

**실패할 수 없는 지표는 쓸모가 없습니다.** 세 번 갈아엎었고 전부 측정으로 판정했습니다:

- **NN 거리로 수평 오차를 재면 안 됨** — 평탄지에서 점밀도를 재게 되어 정합이 틀려도
  작게 나옵니다. (실증: baseline과 GLIM이 **동일하게 0.0495**)
- **후보 이동마다 재-binning 하면 안 됨** — 비교 셀 집합이 바뀌어 정합된 데이터에서
  **0.148 m 가짜 변위**. 점을 60k로 늘려도 동일.
- **침식은 셀 점유가 아니라 커버리지에** — 셀당 3점이면 점유 마스크가 34% 구멍이라
  23x23 구조요소로 침식하면 남는 셀이 0.
- **두 맵을 같은 커널로 저역통과** — 안 하면 이중선형 샘플링이 분수 오프셋에서 분산을
  줄여줘 탐색이 "정합" 대신 "평활화"를 삽니다. 가짜 변위 0.237 → 0.060 m.
- **기울기 가중은 역효과** (가짜 변위 0.33~1.05 m). 기각.
- **가우시안 `mode="nearest"`도 함정** — 30초 컷오프면 커널 반경이 1200샘플이라
  가장자리에서 원시 샘플 하나에 절반의 가중치가 갑니다. 표류 0인 궤적에 **1.47 m
  가짜 보정**. 정규화 합성곱으로 교체.
- 탐색 상자 경계에 붙으면 `saturated=True`로 보고 (값은 하한일 뿐).

---

## 5. 함정 목록 — 이미 한 번씩 당한 것

재개할 때 같은 데서 시간 쓰지 않도록:

| 함정 | 증상 | 진실 |
|---|---|---|
| **호스트 cyclonedds vs 컨테이너 fastrtps** | 호스트 `ros2 node list`가 **빈 출력**, `/gps_msg` 안 보임 | 두 벤더는 디스커버리가 안 됨. 같은 순간 컨테이너에서는 10 Hz로 보임. **벤더를 맞춰서 보라** |
| **`--symlink-install` + docker 디렉토리 마운트** | `ls /cfg`는 성공하는데 GLIM이 `failed to open config_sensors.json` | 심링크 대상(`build/...`)이 컨테이너에 없음. 목록은 되고 **읽기만 실패**. 실제 파일 경로로 마운트할 것 |
| **`set -u` + ROS `setup.bash`** | 스크립트가 0.4초 만에 exit 1, 자기 출력 0줄 | `AMENT_TRACE_SETUP_FILES: unbound variable`. source 구간만 `set +u` |
| **`ros2 run`이 SIGINT를 안 넘김** | 처리는 정상인데 종료 시 덤프가 0바이트 | 파이썬 래퍼. **바이너리를 직접 exec**할 것. OT 팀도 `global_map.sh` 주석에 같은 걸 기록해 둠 |
| **`ros2 node list`로 준비 판정** | `NODE_DID_NOT_START` | 노드는 멀쩡했음(모듈 4개 로드 완료, 에러 0줄). **판정 로직이 건강한 대상을 죽이고 대상이 고장났다고 보고**한 형태. 준비 판정은 프로세스 생존으로 |
| **GLIM 설정을 못 읽으면 조용히 폴백** | `InvalidTopicNameError: topic name must not be empty` | 에러 대신 **빈 토픽 이름**으로 폴백. 진입 스크립트에 `head -c 1 config.json` 가드 넣어둠 |
| **GLIM 토픽 발행은 `librviz_viewer.so`가 함** | 노드는 도는데 토픽 0개 | 헤드리스에서 못 도는 건 GLFW를 여는 `libstandard_viewer.so`뿐. rviz_viewer까지 끄면 포즈가 안 나옴 |
| **호스트 `ROS_DOMAIN_ID=7`은 라이브 센서와 공유** | — | 오프라인 재생은 **반드시 도메인 99** 등으로 격리. 안 그러면 bag 데이터가 운영 전역맵에 주입됨 |
| **NavSatFix 공분산이 `APPROXIMATED`** | 1σ 1.4 m로 보여서 "GNSS가 노이즈투성이"로 오판 | HDOP 유도 추정치라 무의미. 실제 정지 중 고도 산포는 **0.027 m p2p** |

---

## 6. 자산 위치

~~~
워크트리        /home/kimm/robot_ws-slam            (feature/lidar-slam, origin에 푸시됨)
전체 실행 기록   /home/kimm/data/ulw_slam_artifacts/notepad.md
캐시/결과물     /home/kimm/data/ulw_slam_artifacts/  (354 MB)
                  submaps_1104*.npz   31 GB bag 재독 없이 재사용 가능
                  baseline_A/B.npy, slam_A/B.npy   비교에 쓴 서브맵
                  glim_dump/          GLIM 궤적(traj_lidar.txt, 2637포즈) + 서브맵 28개
                  gps_*.csv           GNSS 궤적
재스탬프 bag    /home/kimm/data/ulw_slam_1104_restamped_v2   (7.9 GB, 130~400초)
도커 이미지     excavator-slam-glim:humble  (+ mola, kiss — 둘 다 폐기/보류)
~~~

**주의**: GLIM 설정(`config/glim/`)은 CPU 모듈로 바꿔놨습니다. 기본값이 GPU라
`.so`를 못 찾고 죽습니다. CUDA 12.6 변형(`libgtsam-points-cuda12.6-dev`,
`ros-humble-glim-ros-cuda12.6`)으로 올리려면 이미지를 다시 빌드해야 합니다.
지금은 CPU만으로 RTF 3.07이라 급하지 않습니다.

---

## 7. 판정 기준 대비 현재 상태

| | 상태 |
|---|---|
| C1 리서치 메모 | **통과** — 10행 전부 URL, GLIM 선정·동작 확인 |
| C2 격리 | **통과** — main 무손상, 워크트리 분리, OT 컨테이너 4개 Up |
| C3 오프라인 실행 | **부분** — GLIM 종료코드 0, RTF 3.07, 궤적 2637포즈, 서브맵 28개(오프라인 CLI 경로). **워크트리 launch 파일 경로는 미완** (마지막 실행이 궤적 0포즈. 원인 2개 수정 완료했으나 재실행 검증 전) |
| C4 재방문 지표 | **부분** — RED→GREEN 완료, 양쪽 수치 확보. 단 "SLAM <= baseline 둘 다"는 dz에서 미충족. 목표치는 양쪽 다 미달 |
| C5 회귀 | **통과** — 63개 통과, skip/xfail 없음 |

---

## 8. 마지막에 하던 일 (중단 지점)

`launch/slam_offline.launch.py`로 오프라인 실행을 돌리다가 궤적이 0포즈로 나왔고,
원인 두 개(`ros2 run`의 SIGINT 미전달, `librviz_viewer.so` 비활성)를 고쳐 **재실행을
막 걸었을 때 중단**했습니다. 다음에 재개하면 그 재실행부터 하면 C3가 닫힙니다:

~~~bash
cd ~/robot_ws-slam && source install/setup.bash
ros2 launch excavator_slam slam_offline.launch.py \
  bag:=/home/kimm/data/ulw_slam_1104_restamped_v2
~~~

단, 그건 **이미 아는 사실을 형식적으로 확인하는 작업**입니다(같은 GLIM이 오프라인 CLI
경로로는 이미 2637포즈를 냈음). 우선순위는 **붐 IMU 복구 → 캐빈 기동 → 현장 녹화**입니다.
