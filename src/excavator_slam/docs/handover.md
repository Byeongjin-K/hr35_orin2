# 재개 안내 — 굴착기 LiDAR SLAM (feature/lidar-slam)

마지막 작업: 2026-09-15
작업 위치: `/home/kimm/robot_ws` (브랜치 `feature/lidar-slam`)
전체 실행 기록(모든 실패와 그 진단 과정 포함): `/home/kimm/data/ulw_slam_artifacts/notepad.md`

> **2026-09-15 갱신 — 아래 본문보다 이 블록이 우선한다.**
>
> - **워크트리 이름이 바뀌었다: `~/robot_ws-slam` → `~/robot_ws-lidar-slam`.**
>   운영 규칙은 **브랜치 1개 : 워크트리 1개, 이름을 맞춰서 묶는다** 이다.
>   `main` ↔ `~/robot_ws`, `feature/lidar-slam` ↔ `~/robot_ws-lidar-slam`.
> - `main` 을 이 브랜치에 병합했다(`f961397`). 병합 전까지 이 브랜치의
>   `lidar_boom_params.yaml` 에는 `udp_profile_imu` 가 없어서, **이 브랜치로 브링업하면
>   센서가 LEGACY 로 돌아가 아래 1-(1) 블로커를 그대로 재생산했을 것**이다.
> - 1-(1) 붐 IMU 블로커는 **해소됐다**. 아래 그 절의 머리에 결론을 적어 뒀다.
> - 캐빈 설정에도 같은 함정을 막아 뒀다(`e9aad85`). 단 센서가 꺼져 있어 펌웨어는 미확인이다.
> - **8. 마지막에 하던 일(오프라인 launch 가 0 pose)은 닫혔다.** 2026-09-15 재실행에서
>   `slam_offline.launch.py` 가 TRAJECTORY **2203 poses**, SUBMAPS 17, DUMP 33.2 MB 를 냈다.
>   (replay 도중 종료시킨 부분 실행이라 포즈 수는 전체 실행의 2637 보다 적다.)
> - 지금의 유일한 하드 블로커는 **캐빈 라이다 전원 꺼짐**이다(192.168.0.6 ping/HTTP 무응답).
>
> **2026-09-15 후속 — 정합 오차 작업. 아래 3-2 의 수치는 이 블록으로 갱신된다.**
>
> - **전역맵 정합 오차의 원인을 찾아 고쳤다**: `sub_mapping` 의 `enable_optimization` 이
>   꺼져 있어서 서브맵이 **그 순간 오도메트리 포즈로 굳은 강체 스택**이었다. 약 9초치
>   드리프트가 서브맵마다 박제되고, 전역 그래프는 그 굳은 덩어리를 밀 수밖에 없었다.
> - **`enable_optimization` + `create_between_factors` 를 켰다**(둘은 한 쌍이다, 아래 주의).
>   정지 스윙-재방문 창에서, 같은 2637 포즈·같은 크롭·같은 지표로. **GLIM 이 런마다
>   재현되지 않으므로 모든 수치는 여러 런의 범위로 적는다**(컨트롤 3런, 변경 3런):
>
>   | 지표 | 배포 설정 | 변경 후 |
>   |---|---|---|
>   | dz_median (창1) | 0.1061 ~ 0.2544 m | **0.0339 ~ 0.0582 m** |
>   | dz_median (창2, 독립) | 0.1641 m | **0.0279 ~ 0.0621 m** |
>   | dz_bias | +0.063 ~ +0.222 m | **+0.008 ~ +0.038 m** |
>   | 맵 중력 기울기 | 10.0 ~ 11.7° | **1.77 ~ 2.06°** |
>
>   두 집단은 **어느 지표에서도 겹치지 않는다**. `dz_bias` 는 **모든 런에서 D1 목표
>   `|dz| <= 0.05 m` 안**에 들어온다(배포 설정은 한 번도 못 들어온다). `dz_median` 은
>   0.028~0.062 로 목표선을 걸친다 — **"충족"이 아니라 "걸친다"가 정확한 표현이다.**
> - 비용은 `RTF 2.65 → 1.53` (bag 초/벽시계 초, 컨테이너 CPU 4개). 여전히 실시간보다 빠르다.
> - **주의 — 두 플래그는 반드시 함께 켠다.** `enable_optimization` 만 켜면 서브맵 내부
>   그래프가 정합오차 팩터만으로 버티다 **변형된다**: dz_bias 는 좋아지는데(+0.012)
>   `rms0 0.278/0.391`, `dz_p90 0.63/0.72` 로 **배포 설정보다 나빠진다**.
> - **전역 매핑 복셀 노브는 기여가 0이었다**(다중해상도 복셀맵, 0.25 m 복셀, 샘플링 0.4).
>   단독으로 켜면 컨트롤과 구분되지 않으면서 RTF 만 2.70 → 1.17 로 깎아먹는다. 채택하지 않았다.
> - **GLIM 은 런간 재현되지 않는다.** 같은 설정·같은 bag·같은 2637 포즈인데 궤적이 평균
>   1.42 m 다르고 서브맵 개수까지 달라진다(21 vs 28). 원인은 전처리의
>   `use_random_grid_downsampling`(매 프레임 무작위 10000점)이고 시드 노브가 없다.
>   → **단일 런 A/B 비교는 무효다.** 컨트롤을 3회 돌려 분산을 먼저 재고, 그 폭을 넘는
>   효과만 결과로 인정할 것.
> - **오프라인 실행 방식을 바꿨다**: `ros2 bag play` 대신 **`glim_rosbag`** 이 bag 을
>   추정기 프로세스 안에서 직접 읽는다. 무거운 설정이 스캔을 조용히 버리는 일이 사라졌고
>   (예전에는 2637 → 1953 포즈), 실시간 가능 여부가 **RTF 숫자**로 나온다.
>   `slam_offline.launch.py` 에서 `rate:=` / `measure_s:=` 는 없어졌고 `cpus:=` 가 생겼다.
> - 측정 레시피는 이제 `scripts/score_revisit.py` 에 상수로 박혀 있다(/tmp 와 함께 증발하지
>   않도록). 두 창 캐시는 `~/data/ulw_slam_artifacts/submaps_1104_sta_raw.npz`(창 쌍 1),
>   `submaps_1104_sta2_raw.npz`(창 쌍 2).
>
> **2026-09-22 — 캐빈 라이다 블로커 해소. 아래 1-(2) 는 이 블록으로 대체된다.**
>
> - **캐빈 센서를 처음으로 읽었다.** `OS-0-32-U1`, SN `122228000973`, PN `840-103574-06`,
>   펌웨어 `ousteros-image-prod-aries-v2.5.3`. **붐과 하드웨어 세대가 다르다**
>   (붐: PN `860-105000-07`, `bootes` v3.2.0).
> - **원인은 전원 순서가 아니라 고정 IP 부재였다.** `/api/v1/system/network/ipv4` 가
>   붐은 `override "192.168.0.5/24"`, 캐빈은 `override null` 이라 링크로컬
>   (169.254.157.137)로 떨어져 있었다. 이 서브넷에는 캐빈용 DHCP 예약도 없으므로 매 부팅
>   재발했을 상태다. `PUT .../ipv4/override "192.168.0.6/24"` (HTTP 200) 로 박았고 즉시 응답.
>   **센서가 안 보이면 먼저 mDNS 로 찾아라**: `avahi-browse -rt _roger._tcp`. IPv6 링크로컬
>   (`http://[fe80::be0f:a7ff:fe00:7325%eno1]/...`)은 호스트 설정 없이 항상 붙는다.
> - **펌웨어는 이미 최신이다.** Ouster changelog: v2.5.3 은 Rev06/Rev05/RevC/RevD 용이고
>   Rev7 OS0/OS1/OSDome 만 v3.x 를 쓴다 → **2.5.x 로 도는 OS-0 은 정의상 Rev7 이 아니다.**
>   올릴 상위 버전이 없다. 붐의 `bootes` 이미지를 이 센서에 올리면 안 된다.
> - **설정 두 개를 실측으로 고쳤다**(커밋 `806c50c`, `58b476c`):
>   `udp_profile_imu` 는 `ACCEL32_GYRO32_NMEA`(3.2 전용, 이 센서엔 없음) → **`LEGACY`**,
>   `udp_profile_lidar` 는 `RNG19_RFL8_SIG16_NIR16` → **`LEGACY`**. 후자가 없으면
>   드라이버가 활성화 직후 `std::out_of_range: Field 'WINDOW' not found in LidarScan`
>   으로 죽는다(아래 함정 표).
> - **캐빈 전용 런치를 만들었다**: `hr35_bringup/launch/cabin_only_driver.launch.py`.
>   `dual_lidar.launch.py` 는 붐 드라이버까지 재시작시켜 라이브 OT 스택을 끊으므로,
>   캐빈만 올릴 안전한 경로가 없었다. 이 파일은 실행 경로 어디에서도 붐을 언급하지 않고,
>   TF 퍼블리셔 노드 이름도 `tf_publisher_cabin` 으로 분리해 이름 충돌을 피한다.
> - **라이브 실측 (ROS_DOMAIN_ID=98 격리, 붐·OT 무손상)**:
>   `/lidar_cabin/points` **10.000 Hz**, `/lidar_cabin/imu` **100.003 Hz**,
>   라이프사이클 `active`, 프레임 `lidar_cabin/os_lidar` · `os_imu`,
>   포인트 필드에 `t`·`ring`·`range`·`intensity`·`reflectivity`·`ambient` 전부 존재.
> - **부하는 문제가 아니다**: 캐빈 드라이버 CPU **2.3%** (붐 16.5%), OT 컨테이너 점유
>   변동 없음, eno1 약 **8.6 → 10.1 MB/s** (1 GbE 의 약 8%).
> - **캐빈 `T_lidar_imu`**(센서 자체 메타데이터에서 계산, 합성 잔차 0):
>   `[-0.006253, 0.011775, -0.028535, 0.0, 0.0, 1.0, 0.0]`. **붐 값을 재사용하지 말 것**
>   (붐은 `[0.002441, 0.009725, -0.030662, ...]`). 회전은 붐과 같은 Z축 180도.
> - **캐빈용 GLIM 설정을 분리했다**: `src/excavator_slam/config/glim_cabin/`.
>   토픽이 `/lidar_cabin/*`, `T_lidar_imu` 가 캐빈 값, 그리고 09-15 에 검증된
>   `enable_optimization` + `create_between_factors` 를 그대로 승계한다.
>   실행: `ros2 launch excavator_slam slam_offline.launch.py bag:=<bag> \`
>   `config_dir:=$PWD/src/excavator_slam/config/glim_cabin cpus:=4`
>
> **2026-09-22 후속 — 실험 없이 가능한 백로그 8건. 위 22행 블록의 재현성 진단은 이 블록으로 정정된다.**
>
> - **★정정: 런간 비재현성의 원인은 무작위 샘플링이 아니다.** 위 블록과 함정 표는
>   `use_random_grid_downsampling` 의 시드 없는 무작위 10000점 추출을 원인으로 적었다.
>   **틀렸다.** 같은 bag, 같은 설정, 2런씩 실측(2637포즈·타임스탬프 동일):
>
>   | 설정 | 궤적 차이(평균/최대) | 서브맵 | RTF |
>   |---|---|---|---|
>   | 랜딩본 (`num_threads` 2) | **0.1015 / 0.2697 m** | 22 / 22 | 1.83 / 1.75 |
>   | 무작위 OFF (복셀 1.0 m) | **3.0417 / 5.1873 m** | 147 / 147 | 1.10 |
>   | `num_threads` 1 | **0.0028 / 0.0558 m** | 25 / 25 | 1.57 |
>
>   무작위를 끄면 재현성이 **30배 나빠지고** 정합도 무너진다(창1 `dz_median` 0.9786,
>   `dz_bias` +0.7878, `dz_p90` 1.8271, 수평 1.6892 **탐색 포화**, 자체 floor 도 0.0776 로
>   악화. 랜딩본은 0.0329 / +0.0039 / 0.2701). 이유는 단순하다 — `downsample_resolution`
>   이 **1.0 m 로 한 번도 쓰인 적 없는 기본값**이었고, 100 m 장면에 1 m 복셀이다.
> - **실제로 듣는 손잡이는 스레드 수다.** `num_threads` 1 은 분산을 **36배** 좁히면서
>   정합은 그대로다(창1 `dz_median` 0.0320 · `dz_bias` +0.0062, 창2 0.0344 · +0.0050 —
>   09-15 의 3런 범위 안). 비용은 RTF 1.79 → **1.57** (12%, 여전히 실시간의 1.5배).
>   **비트 단위 재현은 아니다**(최대 0.0558 m 남음). 얻는 것은 분산이 측정 대상 효과
>   크기(0.05~0.2 m)보다 확실히 작아져 **설정당 1런이 신뢰 가능해진다**는 점이다.
>   활성 CPU 경로의 `num_threads` 는 `config_preprocess.json` 과 `config_odometry_cpu.json`
>   **딱 두 곳**이고, 두 설정 디렉터리에 반영했다.
> - **비재현성은 런 길이·지도 크기와 함께 자란다.** 14초 캐빈 bag(서브맵 1개) 4런은
>   평균 **0.0003 m** 밖에 안 벌어진다. 전역 최적화가 증폭기라는 해석과 맞는다.
> - **`exit 139` 의 정체를 잡았다 — `librviz_viewer.so`.** 확장 모듈 이분탐색(캐빈 bag,
>   네 경우 모두 포즈 111·서브맵 1 동일): 둘 다 **139**, 아무것도 **0**,
>   `libmemory_monitor.so` 단독 **0**, `librviz_viewer.so` 단독 **139**. 백트레이스:
>
>   ~~~
>   #0 glim::TrajectoryManager::update_anchor(double, Eigen::Transform<double,3,1,0> const&)
>   #1 glim::RvizViewer::globalmap_on_update_submaps(vector<shared_ptr<SubMap>> const&)
>   #2 glim::GlobalMapping::optimize()
>   #3 glim::GlobalMapping::save(string const&)
>   ~~~
>
>   `save()` 가 마지막 `optimize()` 를 돌리고 그 콜백에서 뷰어가 `update_anchor` 를
>   부르다 죽는다. **경쟁 상태다**: `num_threads` 1 의 두 런이 각각 0 과 139 로 갈렸다.
>   산출물은 온전하고(궤적 차이 0.3 mm 수준) 오프라인에서는 뷰어를 빼면 **exit 0** 이지만,
>   **라이브에서는 뺄 수 없다** — 아래 `config_ros.json` 주석대로 ROS 퍼블리셔가 그 안에 있다.
>   상주 노드로 만들면 매 종료마다 139 를 받게 되므로 수퍼바이저가 정상 종료와 구분 못 한다.
> - **`glim_ext` GNSS 모듈을 빌드해서 GLIM 이 로드하는 것까지 확인했다.**
>   `scripts/build_glim_ext.sh` 가 그 레시피다. 이미지에 gtsam·gtsam_points 헤더
>   (`/usr/local/include`), glim cmake 설정, Eigen 이 전부 있어서 그대로 붙는다.
>   런타임 로그: `load libgnss_global.so` → `gnss_global_config_path=/cfg/config_gnss_global.json`
>   → `starting GNSS global thread` → `- /gnss (ext)` 구독, 포즈 111.
>   - **ScanContext 는 PCL 때문에 막혔다.** 이미지에 `libpcl` 패키지가 **0개**다. 주행
>     재방문 녹화 없이는 검증도 못 하는 루프 검출기를 위해 런타임 이미지에 PCL 을 넣는
>     것은 아직 이득이 아니라고 판단해 껐다.
>   - **지금 데이터로는 GNSS 팩터가 애초에 발동하지 않는다.** `min_baseline` 기본값이
>     **10 m** 인데 1104 bag 의 총 이동은 **0.095 m** 다. 두 자릿수 차이다.
>   - **상류 기본값은 GNSS 고도를 버린다**: `prior_inf_scale` 이 `[1e3, 1e3, 0.0]`.
>     이 프로젝트가 재는 지표가 `dz_bias` 인데 정반대다. 주행 녹화로 재보기 전에 올리는
>     것은 추측이라 상류 값 그대로 뒀다.
>   - **함정**: `config.json` 의 `config_ext` 와 `config_ext.json` 의 `config_path` 는
>     둘 다 **파일이 아니라 디렉터리**다. 파일명을 넣으면 `config_ext.json/config_ext.json`
>     을 열려다 실패하고 **모듈은 기본값으로 그냥 뜬다** — 설정 없이 도는데 정상처럼 보인다.
> - **라이브 경로가 생겼다** (`launch/slam_live.launch.py`, `scripts/glim_live_entry.sh`).
>   FastDDS 는 디스커버리를 UDP, 페이로드를 **공유메모리**로 보낸다. 네트워크 네임스페이스만
>   공유하면 토픽은 다 보이고 GLIM 도 다 뜨는데 콜백이 한 번도 안 불린다.
>   `--ipc=host` 는 **필요하지만 충분하지 않다**: 리더가 root 로 `/dev/shm` 세그먼트를
>   0644 로 만들고, 라이터는 그 세그먼트에 써야 하므로 uid 1000 호스트 퍼블리셔는
>   **쓰기 권한이 없어 전부 조용히 버린다**. 같은 재생 세션 실측 — 호스트 2.504 Hz,
>   `--network host` 0, `+--ipc=host` 0, `+--user 1000:1000` **1.801 Hz**,
>   `--ipc=host` + UDP 전용 FastDDS 프로파일(root) **1.802 Hz**. `--user` 를 택했다
>   (공유메모리를 살려 CPU 를 아끼고, 산출물이 root 소유가 되지 않는다).
>   캐빈 bag 재생 상대 실측: `/glim_ros/lidar_odom` **2.558 / 2.543 Hz** (0.25배 재생의
>   공칭 2.5 Hz = 프레임 누락 없음), 26포즈, 서브맵 1.
> - **캐빈 설정 경로를 처음 실행했다** (C1): 붐 설정 × 캐빈 bag = **0포즈**(토픽 불일치),
>   캐빈 설정 × 캐빈 bag = **111포즈 · 서브맵 1 · RTF 4.74**, 로그에
>   `estimate initial IMU state` 확인.
> - **두 라이다 융합의 수학을 코드로 고정했다** (`excavator_slam/dual_lidar.py`, 9테스트).
>   붐 반사는 SLAM 포즈 + 붐 조인트로 **배치**하고 스스로 위치를 찾게 하지 않는다.
>   **스윙 각은 일부러 빠진다** — 두 센서가 같은 상부체에 달려 있어 상쇄되므로 넣으면
>   이중 적용이다(테스트가 이걸 고정한다). 수직 성분은 `r*(sinα-sinβ)` = **0.445 m** 이고,
>   위 블록의 0.55 m 는 호장 `r*Δθ` 다(오차 크기 가늠에는 되고 점 배치에는 안 된다).
> - **변이 `denser` 는 기각이다** (3런, 두 창 쌍 모두 채점). `denser` 는 랜딩본에
>   서브맵 밀도만 바꾼 단일 축 변이다(`submap_downsample_resolution` 0.3 → 0.1,
>   `submap_target_num_points` 50000).
>
>   | 창 쌍 | | `dz_median` | `dz_bias` | `dz_p90` |
>   |---|---|---|---|---|
>   | 1 | denser 3런 | 0.0282~0.0355 | +0.0066~+0.0168 | 0.2119~0.2662 |
>   | 1 | 랜딩본 (09-15 3런) | 0.034~0.058 | +0.015~+0.023 | — |
>   | 2 | denser 3런 | 0.0255~0.0267 | +0.0078~+0.0082 | 0.2116~0.2368 |
>   | 2 | 랜딩본 (09-15 3런) | 0.028~0.062 | +0.008~+0.038 | — |
>
>   **모든 항목에서 범위가 겹친다** → 컨트롤 분산을 넘는 효과가 없다. 게다가 느리다
>   (RTF 1.19 / 2.05 / 1.24 대 랜딩본 1.83 / 1.75). 서브맵 개수도 28 / 20 / 28 로 튄다.
>   위 09-15 블록의 "(선택) GLIM 기본 밀도 복원" 항목은 **이걸로 닫힌다.**
> - **변이 `stock` 은 안 돌렸다 — 중단 게이트가 걸려서 멈췄다.** 배포 파이프라인의
>   `버림` 카운터가 03:39:54 에 1 → 03:40:04 에 **2** 로 올라갔다(융합 96,998 프레임 중
>   1개, 0.001%). 그 10초에 돌던 것은 내 채점 단계(수백 MB npz 읽기)와 cpus 1 오프라인
>   검증 런이 겹친 구간이다. NIC 카운터는 끝까지 전부 0 이었으니 네트워크 드롭이 아니라
>   순간적인 CPU/IO 경쟁으로 융합 노드가 자체 큐에서 버린 것이다. 규칙대로 큐와 라이브
>   재검증이 **각자 스스로 멈췄다**(`exit 9`). 붐 PID 163882 와 OT 컨테이너 4개 ID 는
>   끝까지 그대로고, 캐빈 센서는 STANDBY 다. 참고로 `stock` 은 랜딩된 서브맵 최적화까지
>   되돌린 **두 축 변이**라, 09-15 에 3런으로 이미 측정된 컨트롤의 재측정에 가깝다.
> - **지도 영속화가 datum 을 들고 다닌다** (`excavator_slam/map_export.py` 8테스트,
>   `excavator_slam/glim_dump.py` 7테스트, `scripts/export_glim_map.py`).
>   GLIM 덤프는 서브맵당 디렉터리 하나이고 `points_compact.bin` 은 **헤더 없는
>   리틀엔디안 float32 x,y,z** 다(문서 없음, 테스트로 고정). 실제 1104 덤프로 검증:
>   **28서브맵 1,044,799점**, 축당 약 196 m, 내보낸 뒤 다시 읽어 datum·yaw 보존,
>   ENU 중심이 선언한 원점에 떨어진다. 점은 **로컬 미터 + float32** 로 저장하고
>   절대좌표(UTM/ECEF)는 거부한다 — float32 간격이 크기에 비례해서 500 km easting 은
>   3 cm 격자에 얹히기 때문이다.

---

## 0. 한 줄 요약

GLIM(LiDAR-관성 SLAM)이 이 Jetson에서 **실시간의 3배**로 돌고, 재방문 정합에서 현재 배포본을
**최소 4배** 이깁니다. 다만 **지금 붐 라이다의 IMU가 안 나오고 있어서** 그것부터 풀어야
다음 단계(현장 녹화)가 진행됩니다.

방향 결정(D3)은 **(a) 현장 데이터 먼저**로 확정됐습니다.

---

## 1. 재개하면 가장 먼저 볼 것 — 막혀 있는 것 3개

### (1) ~~★최우선: 붐 라이다 IMU가 안 나옵니다~~ → **해결됨 (2026-09-09, main `44268ff`)**

> **원인**: 펌웨어 3.2 가 LEGACY IMU UDP 프로파일을 폐기했다. 완전히 실패하지 않고 설정을 쓴
> 직후 몇 분간 흐르다 조용히 멈춘다 — 라이다는 10 Hz 를 유지하고 HTTP 도 계속 응답하므로
> 아래 표의 "양쪽 설정이 다 맞는데 IMU 만 안 온다" 가 정확히 이 증상이었다.
> **해법**: `udp_profile_imu: 'ACCEL32_GYRO32_NMEA'` (3.2 가 추가한 포맷).
>
> **2026-09-15 라이브 재확인**: `imu_packets` 80.000 Hz(드롭 0), 드라이버 캐시 메타데이터의
> `imu_measurements_per_packet = 8` → 정상 발행 640 Hz, 헤더 간격 중앙값 1.5625 ms
> (= 정확히 1/640). 드라이버와 센서의 프로파일이 일치하므로 오파싱도 아니다.
>
> **판정할 때 함정**: `ros2 topic hz` 나 rclpy 구독자는 640 Hz 를 못 따라가 421~437 Hz 로
> 낮게 보고한다. 그 숫자가 `44268ff` 가 기록한 오파싱 증상(433 Hz, 패킷당 5.4 메시지)과
> 겹쳐서 건강한 스트림을 고장으로 오판하기 쉽다. 토픽 레이트가 아니라
> **`imu_packets` 레이트 × `imu_measurements_per_packet`** 과
> **드라이버/센서 프로파일 일치** 로 판정하라.

아래는 당시의 진단 기록이다(원인 추적 과정이 남아 있어 보존한다).


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

### (2) ~~캐빈 라이다가 안 켜져 있습니다~~ → **해결됨 (2026-09-22)**

> 센서 정체·고정 IP·프로파일·실측 레이트는 **위 2026-09-22 블록**에 있습니다. 요약하면
> `192.168.0.6` 고정, `/lidar_cabin/points` 10.000 Hz, `/lidar_cabin/imu` 100.003 Hz 로
> 캐빈 전용 런치에서 확인됐고, 붐 드라이버와 OT 스택은 건드리지 않았습니다.
> 남은 것은 **현장 녹화**(아래 2절 3번)입니다.

아래는 당시 기록입니다(센서가 왜 안 보였는지의 맥락으로 보존합니다).

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
   ~/robot_ws-lidar-slam/src/excavator_slam/scripts/record_field_session.sh <출력경로> <초>
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
| `scripts/score_revisit.py` | **고정 그리드** 채점 + 각 런의 자기 노이즈 바닥(`--floor`) |
| `launch/slam_offline.launch.py` + `scripts/glim_offline_entry.sh` | 오프라인 SLAM 실행 (`glim_rosbag`, 무손실) |
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
| **`ros2 bag play` + 무거운 설정** | 튜닝했더니 점수가 나빠짐 → "그 노브는 나쁘다"로 오판 | 재생기가 실시간으로 밀어넣어 **스캔이 유실**된다(2637 → 1953 포즈, 0.5배속에서도 1981). 설정이 아니라 **데이터 양이 달라진 것**. `glim_rosbag` 으로 바꿔서 원천 차단했고, 포즈 수를 항상 컨트롤과 대조할 것 |
| **`glim_rosbag` 의 `auto_quit` 기본값 false** | bag 을 다 처리한 뒤 CPU 는 놀고 로그는 멈춘 채 영원히 대기 — 행으로 보임 | 정상 종료 대기 상태다. `-p auto_quit:=true` |
| **`glim_rosbag` 이 실시간으로 스로틀** | RTF 가 1.0 언저리로만 나와 "겨우 실시간"으로 오판 | 리더가 `playback_speed` 에 맞춰 기다린다. 처리속도를 재려면 `-p playback_speed:=100.0` |
| **GLIM 이 런간 재현되지 않음** | 같은 설정을 두 번 돌렸는데 점수가 다름 | 원인은 **`num_threads`** 다(2026-09-22 실측). ~~전처리의 시드 없는 무작위 10000점 추출~~ 은 원인이 아니다 — 끄면 재현성이 30배 나빠지고(3.04 m) 정합까지 무너진다. `num_threads` 1 로 분산이 0.1015 → **0.0028 m**(최대 0.0558), RTF 1.79 → 1.57, 정합은 불변. 두 설정 디렉터리에 이미 반영했다. 비트 단위 재현은 아니므로, **측정 효과가 0.05 m 미만이면 여전히 3회 반복**할 것 |
| **서브맵 최적화만 켜기** | dz_bias 가 좋아져서 성공처럼 보임 | `create_between_factors` 없이는 서브맵이 변형된다 — `rms0 0.278/0.391`, `dz_p90 0.63/0.72` 로 **배포 설정보다 나쁨**. 두 플래그는 한 쌍 |
| **오프라인 런의 종료코드 139/134** | 실패한 런으로 오판 | 덤프(`[global] saved`)가 끝난 **뒤의 teardown 크래시**고, 범인은 **`librviz_viewer.so`** 다(2026-09-22 이분탐색 + 백트레이스). `GlobalMapping::save()` → `optimize()` → `RvizViewer::globalmap_on_update_submaps()` → `TrajectoryManager::update_anchor()` 에서 죽는다. **경쟁 상태**라 같은 설정이 0 과 139 로 갈린다. 확장 모듈을 다 빼면 exit 0 이고 산출물은 동일하지만(포즈·서브맵 같고 궤적 차이 0.3 mm) **라이브에서는 뺄 수 없다** — 그 라이브러리가 ROS 퍼블리셔를 들고 있다. 판정은 계속 `TRAJECTORY` 포즈 수로 |
| **호스트 드라이버 → 컨테이너 GLIM 에 데이터가 안 온다** | `ros2 topic list` 에 토픽이 다 보이고 GLIM 도 모듈을 다 올리는데 **콜백이 한 번도 안 불린다**. 로그는 모듈 로드 후 SIGINT 까지 조용하고 `TRAJECTORY 0 poses` | FastDDS 는 디스커버리를 UDP, 페이로드를 **공유메모리**로 보낸다. `--network host` 로는 디스커버리만 살아 **고장이 정상처럼 보인다**. `--ipc=host` 는 필요하지만 **불충분**하다 — 리더가 `/dev/shm` 세그먼트를 root·0644 로 만들고 라이터가 **그 세그먼트에 써야** 하므로 uid 1000 호스트 퍼블리셔는 쓰기 권한이 없어 전부 조용히 버린다. `--user $(id -u):$(id -g)` 를 같이 줘라(실측 0 → 1.801 Hz). root 로 돌려야 하면 UDPv4 전용 FastDDS 프로파일도 된다(1.802 Hz) |
| **`glim_ext` 모듈이 설정 없이 조용히 돈다** | `starting GNSS global thread` 까지 찍히니 정상으로 보임 | `config.json` 의 `config_ext` 와 `config_ext.json` 의 `config_path` 는 **파일이 아니라 디렉터리**다. 파일명을 주면 `config_ext.json/config_ext.json` 을 열려다 실패하고 **기본값으로 그냥 뜬다**. `gnss_global_config_path=` 줄이 실제 파일을 가리키는지, `failed to open` 이 없는지 확인할 것 |
| **캐빈 라이다에 3.2 전용 라이다 프로파일** | 드라이버가 센서 설정·메타데이터까지 정상 통과한 뒤 **활성화 순간** `terminate called ... std::out_of_range: Field 'WINDOW' not found in LidarScan` 로 abort (exit -6) | ouster-ros 0.16.2 는 FW < 3.2 에서 LidarScan 의 WINDOW 채널을 **제거**하는데(`lidar_scan.cpp`), 네이티브 포인트 변환기의 `Profile_RNG19_RFL8_SIG16_NIR16` 은 여전히 WINDOW 를 **무조건 요구**한다. 설정 오류처럼 보이지만 드라이버 내부 불일치다. Rev06 에서는 `udp_profile_lidar: 'LEGACY'` 로 간다 — t·ring·range·signal·reflectivity·near-IR 이 전부 남아 SLAM 에 필요한 건 하나도 안 잃는다 |
| **ouster 드라이버 `metadata: ''`** | 워크트리 루트의 **추적 중인 붐 메타데이터가 덮어써진다**(`git status` 에 `M 192.168.0-metadata.json`) | 빈 값은 "프로세스 CWD 에 `<udp_dest>-metadata.json`" 이라, 캐빈 드라이버가 붐 파일명과 충돌한다. 센서별로 경로를 명시할 것(`/tmp/lidar_cabin-metadata.json`) |
| **캐빈 센서가 ping·HTTP 무응답** | "전원이 안 들어왔나" 로 오판 | 고정 IP override 가 **설정된 적이 없으면** 링크로컬(169.254/16)로 떨어지고, 그 주소는 docker0 라우트에 먹혀 호스트에서 못 간다. `avahi-browse -rt _roger._tcp` 로 찾고 **IPv6 링크로컬 HTTP** 로 붙어서 `PUT /api/v1/system/network/ipv4/override` 로 박아라 |
| **실행 중인 컨테이너에 마운트된 스크립트 편집** | `/entry.sh: line 90: unexpected EOF`, 런이 요약 출력 없이 exit 2 | bash 는 스크립트를 **바이트 오프셋으로 증분 읽기** 한다. 앞부분에 한 줄만 길어져도 남은 실행이 줄 중간부터 재개된다. 실측: 덤프(2637포즈, 서브맵 29)는 멀쩡히 끝났고 **요약 줄만 날아갔다**. 런이 도는 동안에는 `entry.sh` 를 건드리지 말 것 |

---

## 6. 자산 위치

~~~
워크트리        /home/kimm/robot_ws-lidar-slam            (feature/lidar-slam, origin에 푸시됨)
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
| C3 오프라인 실행 | **통과** (2026-09-15) — launch 경로가 `glim_rosbag` 으로 닫혔다. 매 런 궤적 2637포즈(= 배포 설정과 동일, bag 의 points 메시지는 2668), 갭 경고 2건, 서브맵 21~29. 종료코드는 139/134 로 나오는데 **덤프가 끝난 뒤의 teardown 크래시**이고 산출물은 온전하다(그래서 `EXIT_STATUS` 로 항상 찍는다) |
| C4 재방문 지표 | **수직은 통과, 수평은 이 데이터로 판정 불가** (2026-09-15) — 서브맵 내부 최적화를 켠 뒤 `dz_bias` 가 **3런 모두 +0.008~+0.038 m 로 D1 목표 안**(배포 설정은 +0.063~+0.222 로 한 번도 못 들어옴). `dz_median` 은 0.028~0.062 로 0.05 선을 걸친다. 수평은 이 창 쌍에서 탐색 이득이 0.03 수준(비용 지형이 거의 평평)이라 같은 설정이 0.09~0.87 로 튄다 — **주행 재방문이 있는 새 녹화 전에는 수평을 판정하지 말 것** |
| C5 회귀 | **통과** — 63개 통과, skip/xfail 없음 |

---

## 8. 마지막에 하던 일 (중단 지점)

**2026-09-15 갱신.** C3 는 닫혔고, 정합 오차 작업이 한 단계 끝났습니다. 오프라인 실행은
이제 이 한 줄이고, 매번 같은 프레임 수로 끝납니다:

~~~bash
cd ~/robot_ws-lidar-slam && source install/setup.bash
ros2 launch excavator_slam slam_offline.launch.py \
  bag:=/home/kimm/data/ulw_slam_1104_restamped_v2 \
  output_dir:=/home/kimm/data/ulw_slam_runs/<이름> cpus:=4
~~~

채점은 두 단계입니다(두 창 쌍 모두 돌려서 한쪽 창의 우연을 배제할 것):

~~~bash
cd ~/robot_ws-lidar-slam/src/excavator_slam
python3 scripts/slam_submaps.py \
  --trajectory /home/kimm/data/ulw_slam_runs/<이름>/slam_offline/traj_lidar.txt \
  --cache /home/kimm/data/ulw_slam_artifacts/submaps_1104_sta_raw.npz \
  --window A --window B --cache-time-offset 1762233307.217859745 \
  --out-prefix /tmp/<이름>_
python3 scripts/score_revisit.py /tmp/<이름>_A.npy /tmp/<이름>_B.npy --label <이름> --floor
~~~

**다음에 할 것 (우선순위 순)**

1. ~~**캐빈 라이다 전원**~~ → **해결됨 (2026-09-22)**. 고정 IP 를 박았고, 전용 런치·전용
   GLIM 설정·오프라인 실행·라이브 실행까지 전부 실측으로 닫혔습니다(위 블록 참조).
2. **현장 녹화 — 이제 유일한 하드 블로커이고, 필요한 이유가 세 개로 늘었습니다.**
   - **수평 정합 판정**: 보유 bag 에 주행 재방문이 0개라 수평 수치가 거의 평평한 비용
     지형 위에서 흔들립니다(수직은 09-15 에 목표 충족).
   - **GNSS 팩터**: `glim_ext` 의 `gnss_global` 은 빌드·로드·구독까지 확인했지만
     `min_baseline` 기본값이 **10 m** 이고 1104 bag 의 총 이동은 **0.095 m** 라
     팩터가 애초에 하나도 안 붙습니다. 코드가 아니라 데이터가 없는 것입니다.
   - **GNSS 고도 가중치**: 상류 `prior_inf_scale` 이 `[1e3, 1e3, 0.0]` 로 고도를 버립니다.
     이 프로젝트의 지표가 `dz_bias` 이므로 반드시 올려야 하는데, 주행 녹화 없이 올리는
     것은 추측입니다.
   녹화 시 **캐빈 라이다를 SLAM 주 센서로** 켜고(GNSS 안테나와 강체), 붐은 매핑 센서로
   두고, 붐 조인트 각도를 같이 기록하십시오(`dual_lidar.py` 가 그걸로 배치합니다).
3. **브링업 4커밋 main 반영** (아래 1-(3)) — 하드웨어를 건드리므로 확인 후.
4. **변이 `stock` 1런** — 위 09-22 블록대로 중단 게이트에 걸려 못 돌렸습니다. 다만
   `stock` 은 랜딩된 서브맵 최적화까지 되돌린 **두 축 변이**라 09-15 컨트롤의 재측정에
   가깝고, 단일 축 변이 `denser` 는 **기각으로 닫혔습니다**. 우선순위는 낮습니다.
5. **`librviz_viewer.so` teardown 세그폴트** — 상주 라이브 노드로 만들 때만 문제입니다.
   백트레이스는 위 블록에 있습니다. 상류(`koide3/glim`)에 보고하거나, 퍼블리셔만 따로
   내보내는 경량 확장으로 뷰어를 대체하는 것이 근본 해법입니다.
6. **`num_threads` 를 라이브에서 재확인** — 재현성 때문에 1 로 내렸고 오프라인 RTF 는
   1.57 입니다. 캐빈 센서 라이브에서 포즈 발행률이 10 Hz 를 따라가는지는 센서를 켠
   상태에서 한 번 더 재보십시오(bag 재생 0.25배 기준으로는 만율이었습니다).
