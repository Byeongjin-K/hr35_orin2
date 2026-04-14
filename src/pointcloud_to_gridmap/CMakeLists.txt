cmake_minimum_required(VERSION 3.8)
project(pointcloud_to_gridmap)

# CMake 버전 확인 (CMake 3.12 이상에서 CMP0074 사용 가능)
cmake_minimum_required(VERSION 3.12)

# CMP0074 정책 설정
cmake_policy(SET CMP0074 NEW)


if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Default to C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()


# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(grid_map_ros REQUIRED)
find_package(grid_map_msgs REQUIRED)

find_package(message_filters REQUIRED)
find_package(pcl_conversions REQUIRED)
find_package(PCL REQUIRED)

find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)
find_package(tf2_sensor_msgs REQUIRED)

find_package(visualization_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(Eigen3 REQUIRED)



add_executable(pointcloud_to_gridmap src/pointcloud_to_gridmap.cpp)

add_executable(grid_map_extractor src/grid_map_extractor.cpp)

ament_target_dependencies(pointcloud_to_gridmap
  rclcpp
  sensor_msgs
  grid_map_ros
  grid_map_msgs
  message_filters
  pcl_conversions
  
  tf2
  tf2_ros
  tf2_sensor_msgs 
)

ament_target_dependencies(grid_map_extractor
  rclcpp
  grid_map_ros
  tf2_ros
  visualization_msgs
  geometry_msgs
  std_msgs
)

target_include_directories(grid_map_extractor PUBLIC
  ${EIGEN3_INCLUDE_DIR}
)




install(TARGETS
  pointcloud_to_gridmap
  DESTINATION lib/${PROJECT_NAME})

install(TARGETS
  grid_map_extractor
  DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}/
)


if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
