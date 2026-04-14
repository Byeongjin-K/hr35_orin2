# RemoteControllerFeedback.msg
# 리모트 컨트롤러에서 굴착기로 보내는 제어 신호 피드백 (0x18B)
# 28B 송신과 동일한 맵핑으로 8바이트 데이터 구조

# 상부 제어 피드백 (0-3번 바이트)
float32 arm_remote_controller          # 0번 바이트: 아암 제어 피드백 (-1.0 ~ 1.0)
float32 swing_remote_controller        # 1번 바이트: 스윙 제어 피드백 (-1.0 ~ 1.0)
float32 boom_remote_controller         # 2번 바이트: 붐 제어 피드백 (-1.0 ~ 1.0)
float32 bucket_remote_controller       # 3번 바이트: 버킷 제어 피드백 (-1.0 ~ 1.0)

# 트랙 제어 피드백 (4-5번 바이트)
float32 right_track_remote_controller  # 4번 바이트: 우측 트랙 제어 피드백 (-1.0 ~ 1.0)
float32 left_track_remote_controller   # 5번 바이트: 좌측 트랙 제어 피드백 (-1.0 ~ 1.0)

# 예약 바이트 (6-7번 바이트)
uint8 reserved_6_remote_controller     # 6번 바이트: 예약 필드
uint8 reserved_7_remote_controller     # 7번 바이트: 예약 필드

# 메시지 타임스탬프
builtin_interfaces/Time stamp
