# MOLA LiDAR odometry + loop closure + GNSS georeferencing, as apt binaries.
#
# Why a container at all: the SLAM stack needs apt packages and this host's apt needs
# a password we do not have in the session, while docker does not. The image is also
# the honest unit of "what did we run" - the host ROS installation stays untouched.
#
# Why MOLA first: every piece is a released arm64 Humble binary, so this lane reaches
# a real number in minutes instead of a source build, and mola-input-rosbag2 reads the
# recording directly, which removes DDS and replay timing from the experiment entirely.
FROM ros:humble-ros-base

RUN apt-get update && apt-get install -y --no-install-recommends \
      # The metapackage, not a hand-picked list. MOLA loads map and filter classes as
      # runtime plugins named inside the pipeline YAML, so a missing package does not
      # fail at startup - it throws on the first scan, discards every later one, and
      # still exits 0 with an empty trajectory. Naming packages individually turns that
      # into a guessing game; pulling the metapackage ends it.
      ros-humble-mola \
      ros-humble-mola-lidar-odometry \
      # lidar3d-default.yaml builds its local map from a mola_metric_maps voxel class and
      # loads it as a plugin at runtime. Without this package the very first scan throws
      # "Could not find 'libmola_metric_maps.so'", MOLA discards every later scan, and the
      # run still exits 0 with an empty trajectory - a silent failure worth naming.
      ros-humble-mola-metric-maps \
      ros-humble-mola-state-estimation-simple \
      ros-humble-mola-state-estimation \
      ros-humble-mola-sm-loop-closure \
      ros-humble-mola-georeferencing \
      ros-humble-mola-input-rosbag2 \
      ros-humble-mola-bridge-ros2 \
      ros-humble-mola-demos \
      ros-humble-mola-viz \
      ros-humble-mp2p-icp \
      ros-humble-rmw-cyclonedds-cpp \
      python3-numpy \
    && rm -rf /var/lib/apt/lists/*

ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV MOLA_USE_FIXED_LIDAR_POSE=1
