cmake_minimum_required(VERSION 3.8)
project(msg_srv_action_interface_excavator)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)
# uncomment the following section in order to fill in
# further dependencies manually.
# find_package(<dependency> REQUIRED)

set(msg_files
  # "msg/ArithmeticArgument.msg"
)

set(srv_files
  "srv/TrajectoryService.srv"
  "srv/TaskService.srv"
)

set(action_files
  "action/TrajectoryAction.action"
  "action/TaskAction.action"
)

set(msg_files
  "msg/TargetPose.msg"
)

rosidl_generate_interfaces(${PROJECT_NAME}
  ${msg_files}
  ${srv_files}
  ${action_files}
  DEPENDENCIES builtin_interfaces 
  DEPENDENCIES geometry_msgs
)

################################################################################
# Macro for ament package
################################################################################
ament_export_dependencies(rosidl_default_runtime)

ament_package()
