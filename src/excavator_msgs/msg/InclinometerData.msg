# 굴삭기 경사계 센서 데이터 메시지
# 모든 각도값은 degree 단위

# Header 정보
std_msgs/Header header

# 붐 경사계 데이터
float32 boom_longitude     # 붐 종축 각도
float32 boom_latitude      # 붐 횡축 각도

# 암 경사계 데이터
float32 arm_longitude      # 암 종축 각도
float32 arm_latitude       # 암 횡축 각도

# 버킷 경사계 데이터
float32 bucket_longitude   # 버킷 종축 각도
float32 bucket_latitude    # 버킷 횡축 각도

# 스윙 각도 (CAN에서 수신)
float32 swing_angle

# 센서 상태
bool boom_sensor_valid
bool arm_sensor_valid
bool bucket_sensor_valid
bool swing_sensor_valid

# 캘리브레이션 상태
bool boom_calibrated
bool arm_calibrated
bool bucket_calibrated 