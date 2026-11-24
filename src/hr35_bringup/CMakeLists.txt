cmake_minimum_required(VERSION 3.8)
project(hr35_bringup)

find_package(ament_cmake REQUIRED)

# Install launch files
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# Install config files
install(DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
)

# Install executable scripts
install(PROGRAMS scripts/gui_camera_preview.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
