# SLAM 후보 조사 메모 — HR35 굴착기 전역맵 루프클로저 (2026-09-07)

목적: GNSS 앵커 전역맵(rn_global_map)의 재방문 정합 실패를 SLAM(LiDAR-inertial + GNSS + loop closure)으로 대체하기 위한 후보 선정. 리서치 레인 2개(slam-landscape, slam-excavator-feasibility) 결과를 이 호스트에서 직접 검증한 사실과 합쳤다.

> **2026-09-09 갱신 — 아래 순위는 `예측`이었고, 이후 실측으로 결론이 났습니다.**
> 재개하는 사람은 이 절만 읽고 행동하면 됩니다. 아래 원문은 당시 조사 기록으로 보존합니다.

## 판정 결과 (실측, 2026-09-09)

| 후보 | 예측 | **실측 판정** | 근거 |
|---|---|---|---|
| **GLIM** | 1순위 | **채택 — 유일하게 동작** | koide3 PPA가 arm64/ubuntu2204 제공(도커허브 이미지는 amd64 전용). 270초 bag을 88초에 처리 = **RTF 3.07** (CPU 전용). 재방문 정합에서 배포본을 최소 4배 앞섬 |
| MOLA | 2순위 (apt 비교군) | **폐기 — 이 플랫폼에서 실행 불가** | Humble/arm64 바이너리가 RKNN 탐색에 nanoflann >= 1.5.1 을 요구하는데 Ubuntu 22.04 는 1.4.2 뿐. 검사가 배포 바이너리에 컴파일돼 있어 헤더 교체로 못 고침. packages.ros.org 에 mp2p_icp/MRPT 버전이 하나씩뿐이라 내려서 고정할 수도 없음. 파이프라인 4종 중 3종이 동일 KDTree 오류로 실패. 살리려면 MRPT + mp2p_icp 소스 재빌드 필요 |
| KISS-ICP | 8순위 | **보류 — bag 을 못 읽음** | `AnyReaderError: Bag contains no type definitions`. rosbags 가 Humble 이 기록한 bag 에 typestore 를 요구하는데 kiss-icp 가 넘기지 않음. `rosbags<0.10` 핀도 동일 실패. 우회하려면 스캔을 KITTI .bin 으로 내보내야 함 |
| LIO-SAM | 4순위 | 제외 유지 | 상류가 9축 IMU 를 요구하고 Ouster 내장 6축을 명시적으로 미지원 |
| `glim_ext` | — | **PPA 에 없음** | `glim`, `glim_ros` + CUDA 변형뿐. ScanContext 장소인식과 GNSS 팩터가 필요하면 소스 빌드. 단 `libglobal_mapping.so`(서브맵 그래프 전역최적화)는 기본 포함이고 실행 중 실제로 between-factor 를 만들고 있었음 |

**D2 답변**: GLIM. 사용자가 (c) KISS-ICP 수치 확인 후 (a) GLIM 으로 승인했고, 이후 MOLA/KISS-ICP 가
플랫폼 제약으로 탈락하면서 GLIM 이 유일한 실행 가능 후보로 남았습니다.

**메모가 예측하지 못했던 것** — 조사 단계에서는 보이지 않고 설치해 봐야만 드러난 것들:

- `apt` 로 설치된다는 사실이 **이 플랫폼에서 실행된다는 뜻이 아니다.** MOLA 를 고른 이유가
  ``값싼 apt 레인`` 이었는데, 정작 그 바이너리가 배포판의 nanoflann 과 맞지 않았습니다.
  후보 평가에 **``의존 라이브러리 버전이 배포판에 실재하는가``** 항목이 있어야 했습니다.
- 도커허브 이미지의 **아키텍처**를 확인해야 합니다. koide3/glim_ros 태그는 전부 amd64 라
  pull 이 불가능했고, PPA 가 arm64 를 제공한다는 사실이 그걸 구했습니다.
- **붐 장착 센서에 GNSS 를 그대로 융합하면 안 됩니다.** 리서치 두 레인이 ``캐빈 장착 권장`` 을
  인용으로 권고했는데, 실측으로 이유가 확인됐습니다: 두 창 사이 캡 안테나 높이는 +0.016 m,
  붐 라이다 높이는 -0.555 m (붐 관절 -11.6도). 안테나와 라이다가 서로 다른 강체라,
  높이를 억지로 맞추면 붐 동작이 오차로 주입됩니다 (dz 편향 +0.209 -> +0.563 m).

## 이 호스트에서 검증한 사실 (2026-09-07)
- Jetson Orin, JetPack R36.4, Ubuntu 22.04, ROS 2 Humble, aarch64, CUDA 12.6 (nvcc 12.6.r12.6).
- apt 가능: ros-humble-gtsam 4.2.0, ros-humble-libg2o, libceres-dev 2.0, ros-humble-mola-lidar-odometry 3.0.0, ros-humble-mola-sm-loop-closure 1.2.2, ros-humble-mola-georeferencing, ros-humble-mola-state-estimation 2.4.2, ros-humble-mp2p-icp 2.12, ros-humble-rtabmap-ros 0.23.7, ros-humble-slam-toolbox, ros-humble-libpointmatcher. pip: kiss-icp 1.3.0. GLIM은 apt 미제공(소스 또는 PPA).
- GLIM README 원문: 'Tested on Ubuntu 22.04 / 24.04 with CUDA 12.2 / 12.6 / 13.1, and NVIDIA Jetson Orin (Jetpack 6.1).' (https://github.com/koide3/glim)
- glim_ext README 섹션: 'GNSS constraints (libgnss_global.so, ROS2 only)', 'ScanContext Loop Detector', 'Velocity supressor'. (https://github.com/koide3/glim_ext)
- LiDAR: Ouster OS-0-128 fw 3.1, 6축 IMU ~100 Hz(자력계/절대 yaw 없음). 2안테나 RTK GNSS는 스윙 캡에 장착(/gps_msg, /gps_att).
- 오프라인 bag(rosbag2_2025_11_04-14_15_07, 424 s): /lidar_boom/points 4198(≈9.9 Hz), imu 42098, gps_msg 3995, gps_att 3992, swing_encoder 8276, kine 3961, /tf 없음, /tf_static 2.
- 타임스탬프 검사 결과:
  [INFO] [1788762005.885633661] [rosbag2_storage]: Opened database '/home/kimm/data/rosbag2_2025_11_04-14_15_07/rosbag2_2025_11_04-14_15_07_0.db3' for READ_ONLY.
  tf_static [('lidar_boom/os_sensor', 'lidar_boom/os_lidar'), ('lidar_boom/os_sensor', 'lidar_boom/os_imu')]
  metadata keys ['beam_intrinsics', 'calibration_status', 'config_params', 'imu_data_format', 'imu_intrinsics', 'lidar_data_format', 'lidar_intrinsics', 'ouster-sdk'] mode 512x10 ts TIME_FROM_INTERNAL_OSC
  /lidar_boom/imu recv=1762233307.245 stamp=18166.379 recv-stamp=1762215140.867s frame=lidar_boom/os_imu acc=(-0.25,-7.97,-3.64)
  /lidar_boom/imu recv=1762233307.256 stamp=18166.389 recv-stamp=1762215140.868s frame=lidar_boom/os_imu acc=(2.49,-7.76,3.77)
  /lidar_boom/points recv=1762233307.287 stamp=18166.270 recv-stamp=1762215141.017s frame=lidar_boom/os_lidar fields=x,y,z,intensity,t,reflectivity,ring,ambient,range w=512 h=128
  /lidar_boom/points recv=1762233307.384 stamp=18166.370 recv-stamp=1762215141.014s frame=lidar_boom/os_lidar fields=x,y,z,intensity,t,reflectivity,ring,ambient,range w=512 h=128
  /gps_msg recv=1762233331.614 stamp=1762233331.610 recv-stamp=0.004s frame=gps
  /gps_att recv=1762233331.614 stamp=1762233331.610 recv-stamp=0.004s frame=gps
  /gps_att recv=1762233331.715 stamp=1762233331.711 recv-stamp=0.005s frame=gps
  /gps_msg recv=1762233331.715 stamp=1762233331.710 recv-stamp=0.005s frame=gps

## 추천 (D2 결정용)
1. **GLIM (1순위, 첫 프로토타입)** — Jetson Orin/JetPack 6 + CUDA를 상류가 명시적으로 테스트한 유일한 후보. ROS 2 네이티브(glim_ros2), 6축 IMU 지원, 서브맵 기반 전역 최적화(GTSAM) + glim_ext의 GNSS 제약/ScanContext 루프 검출 확장, MIT, 2026-09-06 커밋. 리스크: 소스 빌드(gtsam_points, Iridescence), GNSS 모듈이 위치 제약 위주라 2안테나 heading은 커스텀 팩터가 필요할 수 있음(콜백 슬롯으로 삽입 가능).
2. **MOLA-LO + mola_sm_loop_closure + mola_georeferencing (2순위, apt 30분 비교군)** — 전부 apt로 설치되고 CPU만 쓴다. GNSS 지오레퍼런싱이 내장. 루프클로저는 simplemap 기반 오프라인 모듈이라 온라인 재정합 능력을 확인해야 함. GLIM 빌드가 막히면 즉시 대체.
3. **FAST-LIO2 + FAST-LIO-LC/SAM** — 6축 IMU에 강하고 가볍지만 ROS 2 포트·루프클로저 포크·GNSS 브리지가 전부 커뮤니티 코드라 통합 리스크가 가장 큼.
4. **LIO-SAM ros2** — 상류가 9축 IMU를 요구하고 Ouster 내장 6축 IMU를 명시적으로 미지원. 제외(ZED IMU를 쓰는 변형만 가능).
5. **RTAB-Map** — 다중 세션 DB·루프클로저는 성숙하지만 LIO 전단이 약함. 나중에 전역 계층으로만 고려.
제외: KISS-ICP(루프클로저·GNSS·IMU 없음), DLIO/Point-LIO(루프클로저·GNSS 없음, ROS1 중심), hdl_graph_slam/lidarslam_ros2(정체), ZED positional tracking(보조용).

## 후보 비교표
| 순위 | 후보 | 유형 | ROS 2 Humble | Jetson/arm64 근거 | 의존성 | 루프클로저 | GNSS 융합 | IMU | CPU/GPU | 라이선스/활동 | URL |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | GLIM | LIO + 전역 최적화 | 네이티브(glim_ros2) | README: Jetson Orin JetPack 6.1, CUDA 12.6 | Eigen, GTSAM, gtsam_points, Iridescence, CUDA(선택) | 있음(서브맵 그래프 + ScanContext 확장) | glim_ext gnss_global (ROS2) | 6축 OK | GPU GICP, CPU 백엔드 | MIT, 2026-09 | https://github.com/koide3/glim |
| 2 | MOLA-LO + sm_loop_closure + georeferencing | 모듈형 LO + 그래프 | apt 바이너리(3.0.0) | 이 호스트 apt 확인 | mrpt, mp2p_icp, GTSAM 팩터 | 있음(simplemap 오프라인 모듈) | mola_georeferencing | 선택(preintegration 모듈) | CPU | BSD-3, 활발 | https://github.com/MOLAorg/mola |
| 3 | FAST-LIO2 + FAST-LIO-LC | iEKF LIO + 포즈그래프 | 커뮤니티 ROS 2 포트 | README: ARM(TX2 등) 지원 | Eigen, ikd-Tree, PCL; LC는 GTSAM/ScanContext | 애드온 | 없음(브리지 필요) | 6축 설계 | CPU | GPLv2, 2025-01 | https://github.com/hku-mars/FAST_LIO |
| 4 | LIO-SAM (ros2 브랜치) | 팩터그래프 LIO | 포트 의존 | 근거 없음 | GTSAM, PCL | 있음 | GPS 팩터 내장 | 9축 필수(Ouster 6축 미지원 명시) | CPU | BSD-3, 2025-02 | https://github.com/TixiaoShan/LIO-SAM |
| 5 | RTAB-Map (LiDAR 모드) | 그래프 SLAM | apt 0.23.7 | 이 호스트 apt 확인 | PCL, OpenCV, g2o/GTSAM | 있음(다중 세션 DB) | 프라이어로 주입 | 선택 | CPU(+선택 GPU) | BSD-3, 2026-09 | https://github.com/introlab/rtabmap_ros |
| 6 | DLIO | 연속시간 LIO | feature/ros2 브랜치 | 커뮤니티 보고 | Eigen, PCL, OpenMP | 없음 | 없음 | 6축 | CPU | BSD-3 | https://github.com/vectr-ucla/direct_lidar_inertial_odometry |
| 7 | Point-LIO | 점단위 LIO | ROS1 상류 | 없음 | Eigen, ikd-Tree | 없음 | 없음 | 6축 | CPU | GPLv2 | https://github.com/hku-mars/Point-LIO |
| 8 | KISS-ICP / Kinematic-ICP | 기하 LO | ROS 2 + pip 1.3.0 | pip arm64 확인 | Eigen, Sophus | 없음 | 없음 | 불필요 | CPU 저부하 | MIT | https://github.com/PRBonn/kiss-icp |
| 9 | hdl_graph_slam / lidarslam_ros2 | 그래프 SLAM | lidarslam_ros2 포트 | 없음 | PCL, g2o | 있음 | GPS 제약(어댑터 필요) | 선택 | CPU 무거움 | BSD-2 / 확인 필요 | https://github.com/rsasaki0109/lidarslam_ros2 |
| 10 | ZED SDK positional tracking | 스테레오 VIO | zed-ros2-wrapper | Jetson 1급 지원 | ZED SDK, CUDA | 재위치화만 | 외부 융합 | 카메라 IMU | GPU | 독점 SDK | https://github.com/stereolabs/zed-ros2-wrapper |

## 굴착기 적용 시 함정 (두 레인 공통 지적)
- 캡 yaw ≠ 차체 yaw: LiDAR·GNSS가 스윙 캡에 있으므로 map→cab→track 프레임을 분리해 모델링해야 한다(REP-105). 지금 전역맵 오류의 본질도 이 프레임 문제다. https://www.ros.org/reps/rep-0105.html
- 붐 라이다는 비강체: 붐 관절각(KineMsg)과 캘리브레이션된 체인 없이는 전역 오도메트리 센서로 쓰면 안 된다. 암/버킷이 시야를 점유해 거짓 루프·거짓 이동을 만든다 → TF 기반 self-filter/박스 크롭 필수(기존 bucket self-filter 체인 재사용 가능).
- 정지 구간은 yaw 축퇴: 6축 IMU는 절대 yaw를 못 본다. GNSS heading은 기준선 품질이 좋을 때만 팩터로 넣고 정지 시 적분 금지.
- 반복 지형(흙더미·관로)에서 루프클로저 오탐: 기하 검증 + GNSS 일관성 게이트 필요. https://github.com/irapkaist/scancontext
- 캡 진동/IMU 바이어스: 이전 세션이 Mahony 바이어스 오염을 실측했으므로 IMU 노이즈 파라미터를 실측값으로.
- 라이다 2대 병용 시 단일 클록 + 외부 파라미터 캘리브레이션 선행. https://github.com/ouster-lidar/ouster-ros

## 선행 연구
| 출처 | 기계 | SLAM | 센서 위치 | 자기가림 처리 | GNSS | URL |
|---|---|---|---|---|---|---|
| ETH HEAP 자율 굴착기 | 굴착기 | LiDAR/카메라 지각·매핑 | 상부체 | 지각 스택 내부 처리 | RTK | https://ethz.ch/en/news-and-events/eth-news/news/2023/02/autonomous-excavator.html |
| GLIM 논문 | 범용 | LIO + 전역 최적화 | 강체 | 없음 | 확장 | https://arxiv.org/abs/2407.10344 |
| LIO-SAM 논문 | 차량/보행 | 팩터그래프 | 강체 | 없음 | GPS 팩터 | https://arxiv.org/abs/2010.08196 |
붐 장착 LiDAR SLAM에 대한 공개 사례는 찾지 못했다 — 캐빈 장착이 표준이다.

## 출처
https://github.com/koide3/glim · https://github.com/koide3/glim_ros2 · https://github.com/koide3/glim_ext · https://github.com/koide3/gtsam_points · https://koide3.github.io/glim/ · https://github.com/MOLAorg/mola · https://github.com/MOLAorg/mola_georeferencing · https://github.com/hku-mars/FAST_LIO · https://github.com/yanliang-wu/FAST-LIO-LC · https://github.com/TixiaoShan/LIO-SAM · https://github.com/TixiaoShan/LIO-SAM/blob/master/config/doc/info.md · https://github.com/introlab/rtabmap · https://github.com/introlab/rtabmap_ros · https://github.com/vectr-ucla/direct_lidar_inertial_odometry · https://github.com/hku-mars/Point-LIO · https://github.com/PRBonn/kiss-icp · https://github.com/koide3/hdl_graph_slam · https://github.com/rsasaki0109/lidarslam_ros2 · https://github.com/stereolabs/zed-ros2-wrapper · https://github.com/borglab/gtsam · https://github.com/irapkaist/scancontext · https://www.ros.org/reps/rep-0105.html · https://static.ouster.dev/sensor-docs/ · https://github.com/ouster-lidar/ouster-ros · https://github.com/HViktorTsoi/FAST_LIO_LOCALIZATION · https://ethz.ch/en/news-and-events/eth-news/news/2023/02/autonomous-excavator.html · https://arxiv.org/abs/2407.10344 · https://arxiv.org/abs/2010.08196
