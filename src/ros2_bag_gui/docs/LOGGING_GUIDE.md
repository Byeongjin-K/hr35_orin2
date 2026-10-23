# ros2_bag_gui 로깅 가이드 (숙련자 데이터 수집용)

- 작성: 2026-10-22, exca-orin-2 실장비 시험 결과 기준
- 장비: 붐 LiDAR(Ouster `/lidar_boom/points`), 캐빈 ZED X(ROS 드라이버 실행, S/N 49749405), 붐 ZED X(드라이버 없음, S/N 45233238), ROS_DOMAIN_ID 7, RMW cyclonedds
- GUI 실행: 새 터미널에서 `baggui` (hr35 메시지 타입까지 포함한 환경)
- 갱신: 2026-10-23 — 라이다·카메라 on/off 스위치, 용량·중복 표시와 Start 확인창, Reset 버튼, 버그 수정 (7.3)

## 1. 요약

- **데이터 무결성 양호**: 74토픽 60초 녹화에서 UDP 수신 손실 0건, 라이다 LAZ 누락 추정 0, 모든 토픽 정격 주기 유지.
- **Export 정합**: CSV 64개 모두 행 수가 bag 메시지 수와 같음. bag·LAZ·이미지가 같은 epoch 시각축.
- **용량이 실질 제약**: 라이다를 bag에 넣으면 113 GB/h, LAZ로 받으면 5.3 GB/h.
- **주의**: 캐빈 ZED 드라이버가 SVO2 정지 때 죽을 수 있음(2회 중 1회). 파일은 남지만 카메라는 센서 재시작까지 죽음.

## 2. 권장 로깅 구성

녹화 포맷은 **bag / LAZ / SVO2** 세 가지입니다. **CSV는 녹화할 때 만들지 않습니다.** 녹화가 끝난 뒤 Export 탭에서 bag으로부터 만듭니다.

| 구성 | bag | 세션 전체 | 디스크 511GB 기준 |
|---|---|---|---|
| **라이다 LAZ + 카메라 SVO2 (권장)** | 19 GB/h | 38 GB/h | 약 13시간 |
| 라이다·카메라 모두 bag | 164 GB/h | 165 GB/h | 약 3시간 |
| 라이브 토픽 전체 체크 | 906 GB/h | 908 GB/h | 약 35분 (+ 캐빈 영상 붕괴) |

### 2.1 설정 (녹화 탭 설정 패널)

| 항목 | 값 | 이유 |
|---|---|---|
| 센서 스위치 | 쓰는 라이다·카메라만 켬 | 켜면 그 센서 토픽이 자동 체크됨(라이다는 원시 `*_packets` 제외, 카메라는 가벼운 토픽 + Bag 모드면 left/right 압축 영상). 끄면 그 센서 토픽이 모두 해제되고, 카메라는 SVO2도 녹화하지 않음 |
| 붐 LiDAR | **LAZ 분리 저장** | 같은 점군이 bag 113 GB/h → LAZ 5.3 GB/h(21배 작음), 무손실 확인 |
| 캐빈 LiDAR | 쓰면 LAZ 분리 저장 | 붐과 같은 점군 형식(이번 시험에는 미포함) |
| 카메라 Mode | **SVO2 분리 저장** | 두 카메라 모두 원본(1920×1200, 15fps), 카메라당 6~7 GB/h |
| SVO2 카메라 | **붐 카메라 (zedx_boom, 45233238)** | GUI가 직접 여는 카메라. 캐빈은 드라이버가 녹화 |
| 나머지 토픽 | 가벼운 토픽 전부 체크 | rn_* 인지 출력 포함 bag 약 19 GB/h |

### 2.2 카메라 Mode별 동작 (현재 GUI)

| 카메라 Mode | 캐빈 (드라이버 실행 중) | 붐 (드라이버 없음) | 위험 |
|---|---|---|---|
| **SVO2 분리 저장 (권장)** | 드라이버가 `zedx_cabin.svo2` 녹화, 캐빈 영상 토픽은 bag에서 뺌 | GUI가 직접 `zedx_boom.svo2` | Stop 때 캐빈 드라이버 크래시 가능 |
| 둘 다 | 드라이버 SVO2 + 체크한 영상 토픽도 bag에 | GUI가 직접 SVO2 | 위와 같음. 캐빈 영상이 bag에도 남음(스트림당 +15 GB/h) |
| Bag에 포함 | 체크한 영상 토픽만 bag에(1280×800, 10Hz) | **녹화 안 됨** | 크래시 없음, 대신 붐 카메라 없음 |

- **캐빈 카메라 스위치를 끄면** SVO2 모드에서도 캐빈 드라이버에 SVO2를 요청하지 않습니다(정지 때 드라이버가 죽는 문제를 피함). 붐만 SVO2로 녹화됩니다.
- **"캐빈은 bag, 붐만 SVO2"**: SVO2 모드 + 캐빈 카메라 끔 + 캐빈 압축 영상 토픽을 직접 체크. 2026-10-23 실장비 확인: 10초에 캐빈 압축 영상 103개가 bag에 들어가고 `zedx_boom.svo2`만 생겼으며, 캐빈 드라이버 SVO2 요청은 0회. Start 때 확인창에 캐빈 영상(약 15 GB/h)이 bag에 들어갈 큰 토픽으로 나옵니다.
- 캐빈 영상을 bag으로 받을 때 체크할 토픽: `/zedx_cabin/zedx_cabin_node/left/image_rect_color/compressed` + `left/camera_info` (스테레오가 필요하면 `right`도). 스트림당 약 15 GB/h.

### 2.3 체크하지 말 토픽

- ZED 영상의 `rgb/*`(left와 같은 그림), `*_gray`(흑백판), `*_raw*`(보정 전), `stereo/*`(좌우를 붙인 중복), 압축하지 않은 `image_rect_color`
- 이유: 용량만 폭증하고, 영상 토픽을 다 체크한 시험(Run C)에서 캐빈 영상이 10Hz → 3.9Hz로 떨어짐
- rn_* 인지 출력은 오프라인에서 다시 만들 수 있으면 빼도 됨(빼면 bag 약 2 GB/h)
- 토픽 목록의 **Note 열**이 이런 중복을 `중복: <원본 토픽>`으로 표시합니다(라이다 `lidar_packets`→`points`, `imu_packets`→`imu`도 포함).

## 3. 운영 수칙

1. **세션은 20~30분 단위**로 나누세요(Stop → Start). bag은 기본 3GB마다 분할되지만 LAZ·SVO2는 세션 단위라, 문제가 생겨도 그 구간만 잃습니다.
2. **매 Stop 직후 상태 패널 알림 확인**
   - `No messages in the bag for: ...`: 메시지가 없던 토픽(자율작업이 꺼져 있으면 제어 토픽은 비는 게 정상)
   - `Recorded slower than measured before Start ...`: Start 전 측정 Hz의 60% 미만으로 기록됨 → 유실 의심
   - `The ZED driver ... is no longer running`: 캐빈 드라이버 크래시 → 다음 Start 전에 ZED 재시작
3. **Start 전에 토픽 목록에 `/zedx_cabin/zedx_cabin_node/...` 토픽이 보이는지 확인.** 안 보이면 캐빈 드라이버가 죽은 상태입니다(시험에서 크래시 뒤 28개 → 1개). 이 상태로 SVO2 녹화를 하면 캐빈은 녹화되지 않습니다(GUI가 직접 여는 카메라는 1대).
4. 세션 폴더 `sync_info.json`의 `data_sources.pointcloud.topics./lidar_boom/points.missing_frames_est`가 0이면 라이다 누락 없음.
5. GUI는 새 터미널에서 `baggui`로 실행하고, 녹화는 Stop으로 끝낸 뒤 GUI를 닫으세요.
6. 디스크 여유가 5GB 미만이면 경고, 1GB 미만이면 자동 정지합니다.
7. **GB/h 열과 Start 확인창**: 목록의 GB/h 열은 체크한 토픽이 시간당 쌓는 양을 Start 전에 측정한 값입니다(주황 1 이상, 빨강 5 이상, `큰 타입`은 체크하지 않은 이미지·점군 등). bag에 들어갈 토픽 중 시간당 5GB 이상이 있거나 같은 데이터를 두 번 저장하면(라이다 LAZ+bag `둘 다` 포함) Start 때 큰 토픽, 예상 GB/h(LAZ·SVO2 포함), 남은 디스크 시간을 보여주고 계속할지 묻습니다.
8. **Reset 버튼**: 센서나 ZED를 다시 켰을 때, 또는 연결이 끊겼을 때 GUI를 다시 띄우지 말고 Reset을 누르세요. ROS에 새로 연결해 토픽·카메라 목록을 다시 읽고, 체크한 토픽과 설정은 그대로 둡니다(녹화 중에는 쓸 수 없음).

## 4. 5분 리허설

1. 센서 상태 확인
   ```bash
   sstat                              # sensors status
   sysctl net.core.rmem_max           # 26214400 이어야 함
   ros2 topic list | grep -E "lidar_boom/points|zedx_cabin"
   ```
2. 새 터미널에서 `baggui` 실행
3. 설정: 붐 LiDAR = **LAZ 분리 저장**, 카메라 Mode = **SVO2 분리 저장**, SVO2 카메라 = **붐 카메라 (zedx_boom, 45233238)**
4. 가벼운 토픽 전부 체크(2.3의 영상 토픽은 제외)
5. Start → 5분 → Stop
6. 확인
   - 상태 패널에 `Recorded slower ...`, `The ZED driver ...` 알림이 없는지
   - 세션 폴더: `rosbag/`, `pointcloud/`(약 3000개 LAZ), `zedx_boom.svo2`, `zedx_cabin.svo2`, `sync_info.json`
   - `sync_info.json`의 `missing_frames_est` = 0
7. (선택) Export 탭에서 CSV와 `timestamps.csv`를 뽑아 열어보기

## 5. 시험 결과 (근거)

### 5.1 녹화 시험 (출력 `/home/kimm/data/_exp_check_20261022`)

| Run | 구성 | 길이 | 결과 |
|---|---|---|---|
| A | 74토픽, 라이다 bag+LAZ, 카메라 SVO2(캐빈 드라이버 + 붐 직접) | 60초 | 대화상자 0, LAZ 602개 누락 추정 0, UDP 수신 손실 0, bag 133 GB/h, 세션 쓰기 42.5 MB/s |
| B | 74토픽, 라이다·카메라 모두 bag | 30초 | 164 GB/h, 캐빈 영상 9.96Hz, GUI 종료 때 1회 세그폴트(저장이 끝난 뒤, 데이터 완전) |
| C | 라이브 토픽 전체 120개 | 20초 | 906 GB/h, 캐빈 영상 3.86Hz로 떨어짐 |
| D | **권장: 라이다 LAZ, 카메라 SVO2** | 30초 | bag 19 GB/h, 세션 38 GB/h, LAZ 302개 누락 0, SVO2 2개 정상(붐 478, 캐빈 529프레임) / **캐빈 ZED 드라이버가 정지 중 크래시** |
| 종료 반복 | 가벼운 토픽 5회(약 5초) + 영상 포함 3회(약 8초) | - | 8/8 정상 종료, 매번 데이터 완전 |

### 5.2 시간당 데이터량

| 항목 | 시간당 |
|---|---|
| 라이다 포인트 (bag) | 113 GB |
| 라이다 포인트 (LAZ) | 5.3 GB |
| 캐빈 compressed 영상 (스트림당, 1280×800 10Hz) | 약 15 GB |
| SVO2 (카메라당, 1920×1200 15fps) | 6~7 GB |
| rn_* 인지 출력 합계 | 약 17 GB |

### 5.3 Export 정합 (Run A 세션)

- 산출물: CSV 64개 + `timestamps.csv`(2420행), LAZ 602개, 이미지(카메라당 909장, 15fps)
- **CSV 64개 모두 행 수가 bag 메시지 수와 같음.** 그중 7개 토픽은 타임스탬프 집합까지 비교해 동일. 점군 토픽은 CSV가 아니라 LAZ로 나감
- CSV 열: `timestamp_sec/nanosec`(bag 수신 시각)와 `header_stamp_*`(센서 시각) 둘 다 포함
- 시간축: bag, LAZ, 두 카메라 이미지가 모두 같은 epoch 시각(ns)이고, LAZ·이미지 파일명이 그 시각
- `timestamps.csv` 열: `timestamp_ns, datetime_local, pointcloud_file`과 카메라마다 `image_<카메라 폴더>`(예: `image_zedx_boom`, `image_zedx_cabin`). 각 열에는 그 카메라의 가장 가까운 이미지만 들어갑니다. 카메라 폴더 없이 내보낸 경우는 예전처럼 `image_left, image_right, image_depth`
- 2026-10-22 판은 두 카메라 이미지가 `image_left` 한 열에 섞였습니다(2026-10-23 수정, exp1 재생성에서 14,093행 모두 카메라별로 분리됨 확인)

## 6. 알려진 문제

| 문제 | 영향 | 대응 |
|---|---|---|
| 캐빈 ZED 드라이버가 `stop_svo_rec`에서 세그폴트(2회 중 1회) | 파일은 정상, 카메라는 센서 재시작까지 죽음 | ZED 래퍼/SDK 내부 문제. GUI는 정지 응답을 30초까지 기다리고, 드라이버가 사라졌으면 그렇게 알림. 알림이 뜨면 다음 Start 전에 ZED 재시작 |
| 영상 토픽 전체 체크 시 캐빈 영상 붕괴 | 10Hz → 3.9Hz, 908 GB/h | 2.3의 토픽 제외. Stop 때 속도 저하 알림 |
| Export 후 프로세스가 끝나지 않음(시험 스크립트에서 관찰) | SVO 이미지 추출 뒤 작업 스레드가 남음, 산출물은 완전 | 창이 안 닫히면 강제 종료해도 데이터 영향 없음 |
| GUI 종료 때 드물게 세그폴트 | 저장이 끝난 뒤 발생, 데이터 영향 없음 | Stop으로 녹화를 끝낸 뒤 GUI를 닫기 |
| 녹화 중 UDP 송신 버퍼 오류(유휴 시 0) | RELIABLE 재전송으로 손실 관측 0 | `CYCLONEDDS_URI`는 `.bashrc`에서 주석 처리돼 cyclonedds 기본 설정 사용 중 |
| `/excavator/safety/operator_alert` durability 불일치 | VOLATILE 발행자 메시지가 기록 안 됨 | **수정됨(2026-10-23)**: 발행자 durability가 섞인 토픽은 VOLATILE로 구독(`<세션>/qos_overrides.yaml`), 두 발행자 메시지가 모두 기록됨 |
| 체크한 숨김 토픽(액션 feedback/status) 미기록 | rosbag2가 "Hidden topics are not recorded"로 뺌 | **수정됨(2026-10-23)**: 숨김 토픽을 체크하면 `--include-hidden-topics` |
| 같은 GUI 창에서 두 번째 Start 실패 | `'ascii' codec can't decode byte 0xed` (ZED SDK가 로케일을 C로 바꾼 뒤 한글 주석이 든 설정 파일을 읽다 실패) | **수정됨(2026-10-23)**: 텍스트 파일을 모두 UTF-8로 읽고 씀 |
| `/tf_static` CSV Export 실패 | 메시지마다 transform 개수가 달라 열이 맞지 않음 | **수정됨(2026-10-23)**: 모든 메시지의 열을 모아 씀 |

## 7. 참고

### 7.1 세션 폴더 구조

```
recording_<날짜>_<시각>_<세션명>/
├── rosbag/              # ros2 bag (sqlite3, 기본 3GB마다 분할) + metadata.yaml
├── pointcloud/          # 라이다 LAZ, 파일명 = 시각(ns)
├── zedx_boom.svo2       # GUI가 직접 연 카메라
├── zedx_cabin.svo2      # 드라이버가 녹화한 카메라
└── sync_info.json       # 모드, 토픽별 bag 메시지 수, LAZ 누락 추정, 강제 정지 사유
```

- bag에 넣을 토픽이 없으면(SVO2만 녹화) `rosbag/`이 생기지 않고, Export 탭은 `sync_info.json`으로 세션을 엽니다.
- 이름을 모르는 카메라(hr35_bringup ZED 설정에 없는 시리얼)는 `camera_0.svo2`로 저장됩니다.

### 7.2 이번 시험 과정에서 바뀐 GUI 동작

- Stop 때 Start 전 측정 Hz의 60% 미만으로 기록된 토픽 알림
- 녹화 중 개수 세기 구독 제거(GUI CPU 1.16 → 0.16코어). 개수는 Stop 때 bag에서 읽음
- SVO2: 드라이버가 켜진 카메라는 드라이버에 녹화 요청, 꺼진 카메라는 GUI가 직접. 파일명은 카메라 이름
- 설정 패널에 "붐/캐빈 카메라 (이름, 시리얼)"과 사용 가능 여부 표시(`hr35_bringup/config/zedx_*_params.yaml` 기준)
- SVO2만 녹화(bag 없이) 지원. GUI 종료(창·메뉴·Ctrl+C·SIGTERM·터미널 닫기) 때 드라이버 녹화도 정지. 강제 종료·크래시 뒤에는 다음 Start에서 드라이버가 아직 녹화 중인지 물어봄
- 드라이버 SVO2 정지 응답 대기 5초 → 30초
- 재부팅 후에도 DDS 소켓 버퍼(26214400) 유지: `/etc/systemd/system/dds-socket-buffers.service`

### 7.3 2026-10-23 바뀐 동작 (실장비 확인)

- **라이다·카메라 붐/캐빈 스위치**(설정 패널): 켜면 그 센서 토픽 자동 체크, 끄면 모두 해제. 처음 보이는 토픽은 켜진 센서 것이면 자동 체크되고, 직접 해제한 토픽은 다시 체크하지 않음. 카메라 Mode를 바꾸면 켜진 카메라의 압축 영상이 따라서 체크·해제됨. 스위치 상태는 설정에 저장
- **카메라 스위치와 SVO2**: 꺼진 카메라는 드라이버 SVO2도, GUI 직접 SVO2도 하지 않음. 실장비: 캐빈 끔·SVO2 15초 → `zedx_boom.svo2`만, 캐빈 드라이버 요청 0회
- **GB/h 열, Note 열, Start 확인창**: 실장비 측정 `/lidar_boom/points` 113, `lidar_packets` 27, 캐빈 압축 영상 15, Ouster 영상 4.7 GB/h(10-22 bag 실측과 일치). 확인창에서 아니요를 누르면 세션 폴더도 만들지 않음
- **Reset 버튼**: 실장비에서 133 → 136개 토픽으로 재연결, 체크 유지, Reset 뒤 녹화 정상
- 숨김 토픽·QoS override·두 번째 Start·Export 두 건 수정(6장 표)
