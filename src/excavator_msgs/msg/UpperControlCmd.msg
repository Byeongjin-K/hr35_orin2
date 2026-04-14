# 굴삭기 상부 제어 명령 메시지
# 각 제어값은 -1.0 ~ 1.0 범위의 정규화된 속도값

# Header 정보
std_msgs/Header header

# 붐 제어 (-1.0: 하강, 0.0: 정지, 1.0: 상승)
float32 boom_velocity

# 암 제어 (-1.0: 덤프, 0.0: 정지, 1.0: 크라우드)
float32 arm_velocity

# 버킷 제어 (-1.0: 덤프, 0.0: 정지, 1.0: 크라우드)
float32 bucket_velocity

# 스윙 제어 (-1.0: 좌회전, 0.0: 정지, 1.0: 우회전)
float32 swing_velocity

# 제어 모드 (0: 수동, 1: 자동, 2: 보조)
uint8 control_mode

# 안전 플래그
bool emergency_stop
bool safety_override 