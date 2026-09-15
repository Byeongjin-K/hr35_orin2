#!/bin/bash
# Run GLIM over a recorded bag with the ESTIMATOR reading the bag itself.
#
# The previous recipe started glim_rosnode and a separate "ros2 bag play" and let the two
# meet over DDS inside one container. That path silently voids a tuning comparison: the
# player publishes on a wall clock and hands over whatever the estimator can absorb, so a
# heavier config simply loses scans instead of running slower. Measured on this bag - the
# shipped config finishes with 2637 poses, while a finer-voxel config finished with 1953
# poses at rate 1.0 and still only 1981 at rate 0.5, "large time gap between consecutive
# LiDAR frames" warnings scaling with the loss. Scoring those against each other compares
# two amounts of data, not two configs, and the tuned config looks worse for a reason that
# has nothing to do with the tuning.
#
# glim_rosbag reads the bag inside the estimator process, so every scan is processed no
# matter how expensive the config is. The real-time question does not disappear - it comes
# back as the RTF printed below (bag seconds per wall second) instead of as invisible data
# loss, which is the form a deployment decision actually needs.
#
# Why an isolated domain is still set. librviz_viewer.so publishes the pose stream, and the
# host default ROS_DOMAIN_ID=7 carries the live sensors and the OT stack, so a replay there
# would inject recorded scans into the running global map.

set -u

BAG="$1"
CFG="$2"
OUT="$3"

if [ -z "$BAG" ]; then echo "usage: glim_offline_entry.sh BAG CFG OUT"; exit 2; fi
if [ -z "$CFG" ]; then CFG=/cfg; fi
if [ -z "$OUT" ]; then OUT=/out/slam_offline; fi

# ROS 2's setup.bash is not nounset-clean: it reads AMENT_TRACE_SETUP_FILES and several
# siblings without defaults, so under "set -u" it aborts on an unbound variable before this
# script runs a single line of its own work. Measured: the launch died 0.37 s in with exit
# code 1 and no output, which reads like a docker or mount failure and is neither.
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
echo "CONFIG_FINGERPRINT $(LC_ALL=C; cat "$CFG"/*.json | md5sum | cut -d' ' -f1)"

NODE_BIN=/opt/ros/humble/lib/glim_ros/glim_rosbag
if [ ! -x "$NODE_BIN" ]; then
  echo "NODE_BINARY_MISSING $NODE_BIN"
  exit 4
fi

BAG_NS=$(grep -A3 '^  duration:' "$BAG/metadata.yaml" 2>/dev/null | grep nanoseconds | head -1 | tr -dc '0-9')
[ -z "$BAG_NS" ] && BAG_NS=0

# auto_quit defaults to FALSE: without it the node finishes the bag and then sits there
# forever with an idle CPU and a log that stopped growing, which reads exactly like a hang.
# playback_speed defaults to real time and the reader THROTTLES to it, so the wall clock
# would report at best RTF 1.0 no matter how fast the estimator really is - measured, the
# shipped config came back as "RTF 1.10" purely because it kept waiting for the clock. A
# large speed removes the throttle, so RTF below becomes the real processing rate. Neither
# setting can drop a scan: the reader hands every message to the estimator either way.
START=$(date +%s)
"$NODE_BIN" "$BAG" --ros-args \
  -p config_path:="$CFG" -p dump_path:="$OUT" -p dump_on_unload:=true \
  -p auto_quit:=true -p playback_speed:=100.0 \
  > "$OUT/node.log" 2>&1
STATUS=$?
ELAPSED=$(( $(date +%s) - START ))
[ "$ELAPSED" -lt 1 ] && ELAPSED=1

echo "EXIT_STATUS $STATUS"
echo "WALL_SECONDS $ELAPSED"
if [ "$BAG_NS" -gt 0 ]; then
  echo "BAG_SECONDS $(( BAG_NS / 1000000000 ))"
  echo "RTF $(awk -v b="$BAG_NS" -v e="$ELAPSED" 'BEGIN{printf "%.2f", b/1e9/e}')"
fi
echo "TRAJECTORY $(wc -l < "$OUT/traj_lidar.txt" 2>/dev/null || echo 0) poses"
echo "SUBMAPS $(ls -d "$OUT"/0* 2>/dev/null | wc -l)"
echo "FRAME_GAP_WARNINGS $(grep -c 'large time gap' "$OUT/node.log" 2>/dev/null || echo 0)"
echo "DUMP_BYTES $(du -sb "$OUT" 2>/dev/null | cut -f1)"
echo "SLAM_OFFLINE_DONE"
