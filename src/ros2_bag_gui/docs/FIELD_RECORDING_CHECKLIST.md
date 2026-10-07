# 현장 녹화 점검표 (ros2_bag_gui)

로거가 스스로 알려 주는 것과, 여전히 사람이 확인해야 하는 것을 나눠 적었다.
`<S>`는 세션 폴더(`<출력경로>/recording_<날짜>_<시각>_<이름>`)다.

## 1. 로거가 알려 주는 것

| 상황 | 화면에 보이는 것 | 남는 기록 |
|---|---|---|
| `ros2 bag record`가 녹화 중에 끝남 (신호, 자체 오류, 크래시) | 상태가 빨간 `ERROR - NOT RECORDING`으로 바뀌고 오류 창에 종료 코드와 recorder의 마지막 출력이 나온다 | `sync_info.json`의 `forced_stop`, `stop_reason` |
| recorder를 시작하지 못함 (`ros2` 없음 등) | Start가 실패하고 오류 창이 뜬다. 상태는 Recording이 되지 않는다 | 세션 로그 |
| Stop을 눌렀는데 recorder가 이미 죽어 있었음 | 오류 창 "had already ended before Stop" | `forced_stop` |
| Camera = SVO2인데 ZED SDK가 없거나 카메라가 30초 안에 열리지 않음 | 노란 알림과 경고 창. 이미지 토픽은 bag에 그대로 기록된다 | `sync_info.json`의 `notices`, `recording_modes`(실제 적용된 모드) |
| Camera = SVO2이고 카메라 2대의 이미지 토픽이 선택됨 | 알림. SVO2는 카메라 1대(index 0)만 기록하므로 이미지는 전부 bag에도 남긴다 | `notices` |
| SVO2/LAZ 기록이 녹화 도중 실패 | 오류 창 (녹화는 계속된다) | 세션 로그 |
| LAZ 구독 실패 | 알림. 그 라이다 토픽은 bag에 기록된다 | `notices` |
| LAZ 프레임 드롭 | 첫 드롭 때 경고, Stop 때 합계 | `data_sources.pointcloud.dropped_frames`, `write_errors` |
| recorder가 경고를 출력 (느린 디스크로 메시지 유실 등) | 첫 경고를 알림과 경고 창으로 보여 준다 | `recorder_warnings`, 세션 로그 |
| 선택한 토픽이 지금 없음 | 목록 아래 빨간 글씨, Start 때 확인 창. "Yes"면 그 토픽도 recorder에 넘겨 나타나는 순간부터 기록한다 | 알림 |
| 다른 `ros2 bag record`가 이미 돌고 있음 | Start 때 pid와 함께 확인 창 | - |
| 디스크 여유 5 GB 미만 | Start 때 확인 창, 녹화 중에는 경고 1회 | - |
| 디스크 여유 1 GB 미만 | Start 거부. 녹화 중이면 정상 Stop으로 자동 정지하고 사유를 보여 준다 | `forced_stop`, `stop_reason` |
| Stop 후 | 표가 "In bag"(bag에서 읽은 실제 개수)과 "Received (GUI)"로 바뀐다. bag에 0건인 선택 토픽은 알림으로 나온다 | `topic_message_counts`(bag 기준), `gui_received_counts` |

녹화 중 표의 숫자("Received (GUI)")는 GUI가 따로 만든 best-effort 구독이 받은 개수다.
데이터가 흐르는지 보는 참고값이며 bag에 쓰인 개수가 아니다. bag의 실제 개수는 Stop 후에 나온다.

GUI 프로세스가 죽으면(`kill -9`, OOM, 세션 끊김) recorder는 SIGINT를 받아 bag을 닫고 끝난다.

## 2. 녹화 전

1. `echo $ROS_DOMAIN_ID`가 차량 값인지 확인하고 로거를 띄운다. 도메인이 다르면 토픽이 보이지 않는다.
2. `df -h <출력경로>`: 예상 세션 용량의 2배 이상, 최소 20 GB.
3. 설정: LiDAR = "Bag에 포함", Camera = "Bag에 포함"이 기본이다. "둘 다"와 "SVO2/LAZ 분리 저장"은 4장의 실차 확인을 통과한 뒤에 쓴다. Split은 "By Size" 3 GB 이하 또는 "By Time".
4. 센서가 다 뜬 뒤에 토픽을 체크하거나 프로필을 불러온다. 먼저 불러와도 선택은 유지되지만, 목록 아래에 "selected but not available now"가 남아 있으면 그 센서가 아직 안 뜬 것이다.
5. Start를 누른다. 확인 창(없는 토픽, 남아 있는 recorder, 디스크 부족)이 뜨면 내용을 읽고 답한다.

## 3. 녹화 중과 녹화 후

녹화 중:

1. Start 후 5초 기다렸다가 작업을 시작한다. 큰 토픽은 첫 기록까지 3초쯤 걸린다.
2. 상태 표시가 `Recording`인지, 노란 알림이 생겼는지 본다. 오류 창이 뜨면 그 시점부터 기록이 멈춘 것이다. Stop/Start로 새 세션을 시작한다.
3. 작업 사이에 Stop/Start로 세션을 끊으면 한 세션의 위험이 줄어든다.

녹화 후, 장비를 끄기 전:

1. 화면의 "In bag" 열에서 꼭 필요한 토픽의 개수가 Hz x 시간과 맞는지 본다. `unknown`이면 bag에 `metadata.yaml`이 없는 것이다.
2. 알림에 "No messages in the bag for"나 recorder 경고가 있는지 본다.
3. 터미널에서 한 번 더 확인한다.

```bash
ls -la <S> <S>/rosbag                      # metadata.yaml 이 있어야 한다
ros2 bag info <S>/rosbag                   # Duration, 토픽별 Count
python3 -m json.tool <S>/sync_info.json    # forced_stop, notices, recorder_warnings, topic_message_counts
pgrep -af "ros2 bag record"                # 비어 있어야 한다
```

`metadata.yaml`이 없으면 `ros2 bag reindex -s sqlite3 <S>/rosbag`으로 복구한다.
디스크가 가득 찬 상태라면 다른 디스크로 복사한 뒤에 한다.

## 4. 실차에서 아직 확인해야 하는 것

개발 환경에는 ZED 카메라, Ouster 라이다, CAN이 없었다. 아래는 대역(stand-in)과 합성 퍼블리셔로만 검증했다.

### 4.1 ZED SVO2 경로

1. ZED 래퍼를 평소대로 띄우고 Camera = "SVO2 분리 저장", 이미지 토픽 1개를 체크해 30초 녹화한다.
2. 합격: 알림 없이 시작되고 `<S>/camera_0.svo2`가 0보다 크며 세션 로그의 "SVO2 writer stopped: N frames"의 N이 약 15 x 30이다.
3. "SVO2 recording is NOT running" 알림이 뜨면(래퍼가 카메라를 잡고 있어 열지 못하는 경우가 유력하다) 이미지는 bag에 기록된다. 이 차량에서는 SVO2 분리 저장을 쓸 수 없다는 뜻이므로 Bag 모드를 쓴다.
4. 카메라가 열리는 데 걸리는 시간도 본다. Start는 카메라가 열릴 때까지(최대 30초) 기다린다.
5. SVO2 파일에는 ROS 타임스탬프가 들어가지 않는다. 프레임 시각은 카메라 시각이다.

### 4.2 Ouster 라이다 / LAZ 경로

1. `ros2 topic hz /lidar_boom/points`로 주기를 재고 LiDAR = "둘 다"로 60초 녹화한다.
2. 합격: "In bag"의 라이다 개수가 Hz x 60의 99% 이상이고, `sync_info.json`의 `dropped_frames`가 0이며, LAZ 파일 수가 bag 개수와 같다.
3. bag 개수 자체가 낮으면 전송 유실이다(best-effort 대용량 토픽). 해당 토픽의 QoS와 수신 버퍼(`net.core.rmem_max`)를 본다.
4. LAZ는 x, y, z, intensity만 남긴다. ring, 점별 시간, reflectivity가 필요하면 bag에 남겨야 한다. 캐빈 라이다는 LAZ 대상이 아니며 항상 bag에 기록된다.
5. 라이다 2대를 LAZ로 기록하면 `pointcloud/<토픽이름>/` 폴더로 나뉜다. 1대면 `pointcloud/`에 바로 쌓인다.

### 4.3 실제 디스크 속도

```bash
ros2 topic bw <큰 토픽>     # 체크할 큰 토픽마다
dd if=/dev/zero of=<출력경로>/ddtest bs=1M count=2000 oflag=direct && rm <출력경로>/ddtest
```

합격: 디스크 쓰기 속도가 체크한 토픽 대역폭 합계의 2배 이상. 그 다음 실제 프로필로 2분 시험 녹화를 한다.
디스크가 따라가지 못하면 recorder는 메시지를 버리고, 그 사실을 **bag을 닫을 때에야** 출력한다
("Cache buffers lost messages per topic", "Total lost: N"). 로거는 이것을 Stop 때 경고로 보여 주지만
녹화 도중에는 알 수 없다. 시험 녹화에서 이 경고가 나오면 compressed 토픽을 고르거나 주기를 낮춘다.

### 4.4 recorder 사망 훈련 (1분)

시험 세션 녹화 중에 다른 터미널에서 `pkill -INT -f "ros2 bag record"`를 실행한다.
화면이 `ERROR - NOT RECORDING`으로 바뀌고 오류 창이 뜨는지 확인한다.

## 5. 알려진 한계

- Stop은 recorder가 bag을 닫을 때까지 화면을 멈춘다(최대 13초). 10초 안에 닫히지 않으면 강제 종료하며 이때는 `metadata.yaml`이 없다.
- Start 시점에 없던 토픽은 확인 창에서 "Yes"를 고른 경우에만 recorder에 넘어간다. 체크하지 않은 토픽이 나중에 나타나도 기록되지 않는다.
- bag의 타임스탬프는 수신 시각이다. 센서 간 동기는 헤더 시각으로 한다.
- 전원 차단은 시험하지 못했다. 분할 크기를 작게 두면 잃는 범위가 마지막 파일로 줄어든다.
