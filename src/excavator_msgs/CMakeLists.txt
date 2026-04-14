cmake_minimum_required(VERSION 3.8)
project(excavator_msgs)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(trajectory_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# Message files
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/UpperControlCmd.msg"
  "msg/TrackControlCmd.msg"
  "msg/ExcavatorCompleteStatus.msg"
  "msg/PressureData.msg"
  "msg/InclinometerData.msg"
  "msg/SensorStatus.msg"
  "msg/ExcavatorJoints.msg"
  "msg/BucketTrajectory.msg"
  "msg/BucketPose.msg"
  "msg/RemoteControllerFeedback.msg"
  "msg/TaskInfo.msg"
  "msg/GridmapWithTarget.msg"
  "srv/EmergencyStop.srv"
  "srv/SystemReset.srv"
  "srv/CalibrationService.srv"
  "srv/IKSolver.srv"
  "srv/IKSolverBatch.srv"
  "srv/TrajectoryGenerator.srv"
  "srv/BitControl.srv"
  "action/ExcavatorMove.action"
  "action/TaskAction.action"
  DEPENDENCIES builtin_interfaces std_msgs sensor_msgs geometry_msgs trajectory_msgs
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_export_dependencies(rosidl_default_runtime)
ament_package() 