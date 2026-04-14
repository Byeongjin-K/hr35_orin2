# 굴삭기 트랙 제어 명령 메시지
# 각 제어값은 -1.0 ~ 1.0 범위의 정규화된 속도값

# Header 정보
std_msgs/Header header

# 좌측 트랙 제어 (-1.0: 후진, 0.0: 정지, 1.0: 전진)
float32 left_track_velocity

# 우측 트랙 제어 (-1.0: 후진, 0.0: 정지, 1.0: 전진)
float32 right_track_velocity

# 제어 모드 (0: 수동, 1: 자동, 2: 보조)
uint8 control_mode

# 안전 플래그
bool emergency_stop
bool traction_control_enabled 