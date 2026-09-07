# KISS-ICP as a second, independent LiDAR-odometry lane.
#
# Why a second lane at all: the MOLA binaries for Humble/arm64 cannot run here. Their
# matcher needs nanoflann >= 1.5.1 for a radius-limited kNN search, Ubuntu 22.04 ships
# 1.4.2, the check is compiled into the shipped binaries, and packages.ros.org carries
# exactly one version of mp2p_icp/MRPT - so there is nothing to pin to and the only fix
# is rebuilding MRPT and mp2p_icp from source. That is a large bill for what was chosen
# as the CHEAP lane, so the premise no longer holds.
#
# KISS-ICP shares none of that: pure Python packaging over its own C++ core, reads
# rosbag2 through the pure-python 'rosbags' reader, and needs no ROS installation. It
# has no loop closure, which is the point of the project - but it answers the question
# that has to be answered first: does scan-matching odometry beat the open-loop GNSS
# anchor on revisit consistency at all?
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git \
    && rm -rf /var/lib/apt/lists/*

# rosbags >= 0.10 refuses a bag without embedded message definitions, which Humble's
# rosbag2 writer never stores - but sensor_msgs/PointCloud2 is a standard type the
# library already knows, so this is a packaging mismatch rather than a real limitation.
RUN pip install --no-cache-dir "kiss-icp[all]" "rosbags<0.10"
