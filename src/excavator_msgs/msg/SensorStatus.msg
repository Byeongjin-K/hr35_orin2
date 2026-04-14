# 굴삭기 센서 상태 메시지

# Header 정보
std_msgs/Header header

# CAN 통신 상태
bool can_bridge_active
bool can_bus_connected
uint32 can_error_count

# 압력 센서 상태
bool pressure_sensors_active
uint32 pressure_sensor_count
float64 last_pressure_update

# 경사계 센서 상태
bool inclinometer_sensors_active
uint32 inclinometer_sensor_count
float64 last_inclinometer_update

# GNSS GPS 상태
bool gnss_active
uint8 gnss_fix_type
uint8 satellite_count
float64 last_gnss_update

# 전체 시스템 상태
bool system_healthy
bool emergency_stop_active
uint8 overall_status        # 0: OK, 1: Warning, 2: Error, 3: Critical

# 에러 메시지
string[] error_messages
string[] warning_messages 