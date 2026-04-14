# 굴삭기 압력 센서 데이터 메시지
# 모든 압력값은 bar 단위

# Header 정보
std_msgs/Header header

# 붐 실린더 압력
float32 boom_load_pressure     # 붐 로드측 압력
float32 boom_head_pressure     # 붐 헤드측 압력

# 암 실린더 압력
float32 arm_load_pressure      # 암 로드측 압력
float32 arm_head_pressure      # 암 헤드측 압력

# 버킷 실린더 압력
float32 bucket_load_pressure   # 버킷 로드측 압력
float32 bucket_head_pressure   # 버킷 헤드측 압력

# 스윙 모터 압력 (옵션)
float32 swing_pressure

# 압력 센서 상태
bool boom_pressure_valid
bool arm_pressure_valid
bool bucket_pressure_valid
bool swing_pressure_valid

# 압력 범위 체크
float32 max_pressure_limit
float32 min_pressure_limit 