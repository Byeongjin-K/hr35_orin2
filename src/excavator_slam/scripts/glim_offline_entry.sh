#!/bin/bash
# Run GLIM and a bag replay together, inside ONE container, on an isolated domain.
#
# Why one container rather than a node here and a replay there. The host runs
# rmw_cyclonedds_cpp and this image runs rmw_fastrtps_cpp, and cross-vendor DDS
# discovery does not work. That is measured, not assumed: from the host "ros2 node
# list" came back EMPTY and /gps_msg looked unpublished, while a container on the same
# machine at the same moment saw every topic and /gps_msg at 10.0 Hz. Splitting the
# node from the replay across that boundary produces a run with no data and no error.
#
# Why an isolated domain. The host default is ROS_DOMAIN_ID=7, shared with the live
# sensors and the OT stack, so replaying /lidar_boom/points there would inject recorded
# scans into the running global map.
#
# Why the pose topic is discovered instead of named. Its name belongs to the release,
# not to my memory of it, and a wrong guess looks exactly like "SLAM published nothing".

set -u

BAG="$1"
CFG="$2"
OUT="$3"
RATE="$4"
MEASURE_S="$5"

if [ -z "$BAG" ]; then echo "usage: glim_offline_entry.sh BAG CFG OUT RATE MEASURE_S"; exit 2; fi
if [ -z "$CFG" ]; then CFG=/cfg; fi
if [ -z "$OUT" ]; then OUT=/out/slam_offline; fi
if [ -z "$RATE" ]; then RATE=1.0; fi
if [ -z "$MEASURE_S" ]; then MEASURE_S=30; fi

# ROS 2's setup.bash is not nounset-clean: it reads AMENT_TRACE_SETUP_FILES and
# several siblings without defaults, so under "set -u" it aborts on an unbound
# variable before this script runs a single line of its own work. Measured: the
# launch died 0.37 s in with exit code 1 and no output, which reads like a docker
# or mount failure and is neither. Relax nounset across the source only, so the
# rest of the script keeps the protection that catches a missing argument.
set +u
source /opt/ros/humble/setup.bash
set -u

# Fail here, loudly, rather than three layers down. An unreadable config makes GLIM fall
# back to empty topic names and abort on InvalidTopicNameError, which reads as a config
# authoring mistake when it is really a mount that carried symlinks but not their targets.
if ! head -c 1 "$CFG/config.json" > /dev/null 2>&1; then
  echo "CONFIG_UNREADABLE $CFG/config.json - the mount carries names but not bytes"
  ls -la "$CFG" | head -5
  exit 3
fi
rm -rf "$OUT" && mkdir -p "$OUT"

echo "SLAM_OFFLINE_START bag=$BAG domain=$ROS_DOMAIN_ID rmw=$RMW_IMPLEMENTATION"

# The node dumps on shutdown, so dump_path must be set before it starts, not after.
# The BINARY, not "ros2 run". Under ros2 run the pid belongs to a python wrapper and a
# SIGINT to it never reaches the C++ node, so the shutdown path - which is where GLIM
# writes its map and trajectory - never executes. Measured here: a full replay finished
# with TRAJECTORY 0 poses, SUBMAPS 0, DUMP_BYTES 45698 (the two log files and nothing
# else). The OT repo hit the same trap in global_map.sh and recorded the same numbers
# from the other side: exec ros2 run gave exit 137 after 10 s, the bare binary exit 0
# after 1 s.
NODE_BIN=/opt/ros/humble/lib/glim_ros/glim_rosnode
if [ ! -x "$NODE_BIN" ]; then
  echo "NODE_BINARY_MISSING $NODE_BIN"
  exit 4
fi
"$NODE_BIN" --ros-args \
  -p config_path:="$CFG" -p dump_path:="$OUT" -p dump_on_unload:=true \
  > "$OUT/node.log" 2>&1 &
NODE_PID=$!

# Readiness is process liveness, NOT "ros2 node list shows it". Measured: GLIM loaded
# every module cleanly - node.log ends at "load libmemory_monitor.so" with no error and
# the process was still alive - yet it never appeared in "ros2 node list" across 60 s of
# polling, so gating on the node list killed a perfectly healthy estimator. Whether the
# node list sees it is irrelevant anyway; what matters is whether it consumes the replay
# and publishes, and the rate measurement below tests precisely that.
for i in $(seq 1 8); do
  sleep 2
  kill -0 $NODE_PID 2>/dev/null || break
done
if ! kill -0 $NODE_PID 2>/dev/null; then
  echo "NODE_EXITED_EARLY"
  tail -25 "$OUT/node.log"
  exit 1
fi
echo "NODE_ALIVE pid=$NODE_PID"
# Recorded, not gated on: useful when reading the log afterwards, harmless when empty.
echo "DIAG_NODES $(ros2 node list 2>/dev/null | tr '\n' ' ')"
echo "DIAG_GLIM_TOPICS $(ros2 topic list 2>/dev/null | grep -i glim | tr '\n' ' ')"

ros2 bag play "$BAG" --clock --rate "$RATE" > "$OUT/replay.log" 2>&1 &
PLAY_PID=$!

# Give the estimator a few scans before asking what it publishes; an empty topic list
# right after launch would be a timing artefact, not a result.
sleep 12
POSE_TOPIC=$(ros2 topic list 2>/dev/null | grep -i glim | grep -E "pose|odom" | head -1)
if [ -z "$POSE_TOPIC" ]; then
  POSE_TOPIC=$(ros2 topic list 2>/dev/null | grep -i glim | head -1)
fi
echo "GLIM_TOPICS $(ros2 topic list 2>/dev/null | grep -i glim | tr '\n' ' ')"
echo "POSE_TOPIC $POSE_TOPIC"

if [ -n "$POSE_TOPIC" ]; then
  echo "HZ_BEGIN $POSE_TOPIC"
  timeout "$MEASURE_S" ros2 topic hz "$POSE_TOPIC" 2>&1 | grep "average rate" | tail -2
  echo "HZ_END"
else
  echo "NO_POSE_TOPIC"
fi

wait $PLAY_PID 2>/dev/null
echo "REPLAY_FINISHED"

# SIGINT, not SIGKILL: the map and trajectory are written on the normal shutdown path.
kill -INT $NODE_PID 2>/dev/null
for i in $(seq 1 90); do
  kill -0 $NODE_PID 2>/dev/null || break
  sleep 2
done
kill -0 $NODE_PID 2>/dev/null && kill -TERM $NODE_PID 2>/dev/null

echo "TRAJECTORY $(wc -l < "$OUT/traj_lidar.txt" 2>/dev/null || echo 0) poses"
echo "SUBMAPS $(ls -d "$OUT"/0* 2>/dev/null | wc -l)"
echo "DUMP_BYTES $(du -sb "$OUT" 2>/dev/null | cut -f1)"
echo "SLAM_OFFLINE_DONE"
