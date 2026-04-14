# 굴삭기 관절 각도 메시지
# 모든 각도값은 degree 단위

# Header 정보
std_msgs/Header header

# 관절 각도값
float32 boom_joint_angle      # 붐 관절 각도
float32 arm_joint_angle       # 암 관절 각도  
float32 bucket_joint_angle    # 버킷 관절 각도
float32 swing_joint_angle     # 스윙 관절 각도

# 관절 각속도 (옵션)
float32 boom_joint_velocity
float32 arm_joint_velocity
float32 bucket_joint_velocity
float32 swing_joint_velocity

# 계산 상태
bool joints_calculated
bool kinematics_valid

# 오프셋 정보
float32 boom_offset
float32 arm_offset
float32 bucket_offset 