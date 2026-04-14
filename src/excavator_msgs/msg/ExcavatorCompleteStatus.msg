# 굴삭기 전체 상태 메시지
# 모든 센서 데이터를 통합한 완전한 상태 정보

# Header 정보
std_msgs/Header header

# 압력 데이터
PressureData pressure_data

# 경사계 데이터
InclinometerData inclinometer_data

# 관절 각도 데이터
ExcavatorJoints joint_angles

# GNSS 위치 정보
sensor_msgs/NavSatFix gnss_position
geometry_msgs/TwistWithCovariance gnss_velocity

# 센서 상태
SensorStatus sensor_status

# 제어 상태
UpperControlCmd last_upper_command
TrackControlCmd last_track_command

# 시스템 상태
bool system_initialized
bool emergency_stop
uint8 operation_mode        # 0: Manual, 1: Semi-Auto, 2: Auto
float32 system_voltage
float32 hydraulic_temperature

# 작업 정보
float64 operating_hours
float64 fuel_level
string operator_id

# 안전 상태
bool safety_systems_ok
bool hydraulic_pressure_ok
bool engine_temperature_ok
bool track_tension_ok 