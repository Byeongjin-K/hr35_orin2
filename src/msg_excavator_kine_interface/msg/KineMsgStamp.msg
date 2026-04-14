#
# Bigdata 저장용으로 각각을 ex_kinematics_rclcpp_pkg에서 처리해서 동기화할때 동기화정도 파악을 위한 timestamp를 같이 보낼 수 있도록 해당 필드 추가
#

# Message
std_msgs/Header header

builtin_interfaces/Time stamp_gnss
builtin_interfaces/Time stamp_autobox
builtin_interfaces/Time stamp_slope

KineMsg kinemsg