#!/bin/bash
# Run GLIM against LIVE sensor topics instead of a recorded bag.
#
# The offline sibling (glim_offline_entry.sh) hands the estimator a file and the run ends
# when the file does. This one has the estimator subscribe, so the run ends when it is
# stopped, and the interesting failure is no longer "did it process every scan" but "did
# it see the publisher at all".
#
# THE DDS TRAP, and why the caller must match it. The host default is
# rmw_cyclonedds_cpp; this image is rmw_fastrtps_cpp; cross-vendor discovery does not
# work. That is measured, not assumed: from the host "ros2 node list" came back EMPTY and
# /gps_msg looked unpublished, while a container on the same machine at the same moment
# saw every topic at 10.0 Hz. Offline that never mattered because the estimator read the
# bag itself. Live it is the whole game: a driver publishing under cyclonedds is INVISIBLE
# here, and the symptom is not an error - it is a node that runs forever and estimates
# nothing. So the sensor driver must be launched with RMW_IMPLEMENTATION=rmw_fastrtps_cpp
# on the SAME ROS_DOMAIN_ID, and this script reports what it can see before it commits.
#
# Why the domain is never 7. The host default carries the live sensors and the OT stack;
# a GLIM instance there would publish a competing map frame into a running deployment.

set -u

CFG="$1"
OUT="$2"
RUN_S="$3"

if [ -z "$CFG" ]; then CFG=/cfg; fi
if [ -z "$OUT" ]; then OUT=/out/slam_live; fi
if [ -z "$RUN_S" ]; then RUN_S=0; fi

# ROS 2's setup.bash is not nounset-clean: it reads AMENT_TRACE_SETUP_FILES and several
# siblings without defaults, so under "set -u" it aborts on an unbound variable before this
# script runs a single line of its own work.
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

echo "SLAM_LIVE_START domain=$ROS_DOMAIN_ID rmw=$RMW_IMPLEMENTATION"
echo "CONFIG_FINGERPRINT $(LC_ALL=C; cat "$CFG"/*.json | md5sum | cut -d' ' -f1)"

WANT_POINTS=$(python3 -c "
import json,re,sys
t=open('$CFG/config_ros.json').read()
t=re.sub(r'/\*.*?\*/','',t,flags=re.S)
t='\n'.join(re.sub(r'//.*\$','',l) for l in t.splitlines())
print(json.loads(t)['glim_ros']['points_topic'])
")
WANT_IMU=$(python3 -c "
import json,re,sys
t=open('$CFG/config_ros.json').read()
t=re.sub(r'/\*.*?\*/','',t,flags=re.S)
t='\n'.join(re.sub(r'//.*\$','',l) for l in t.splitlines())
print(json.loads(t)['glim_ros']['imu_topic'])
")
echo "SUBSCRIBING_TO $WANT_POINTS $WANT_IMU"

# Report visibility BEFORE starting the estimator. A live run that sees nothing is the
# expensive failure here, and it is silent, so it gets named up front instead of being
# inferred from an empty pose stream twenty minutes later.
VISIBLE=$(timeout 15 ros2 topic list 2>/dev/null)
for T in "$WANT_POINTS" "$WANT_IMU"; do
  if echo "$VISIBLE" | grep -qx "$T"; then
    echo "  VISIBLE  $T"
  else
    echo "  NOT_VISIBLE $T  <- publisher missing, or publishing under a different RMW"
  fi
done

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
# every module cleanly and the process was alive, yet it never appeared in "ros2 node
# list" across 60 s of polling, so gating on the node list kills a healthy estimator.
sleep 5
if ! kill -0 $NODE_PID 2>/dev/null; then
  echo "NODE_EXITED_EARLY"
  tail -25 "$OUT/node.log"
  exit 1
fi
echo "NODE_ALIVE pid=$NODE_PID"

POSE_TOPIC=$(timeout 15 ros2 topic list 2>/dev/null | grep -i glim | grep -E "pose|odom" | head -1)
echo "POSE_TOPIC ${POSE_TOPIC:-NONE}"
if [ -n "$POSE_TOPIC" ]; then
  echo "HZ_BEGIN $POSE_TOPIC"
  timeout 12 ros2 topic hz "$POSE_TOPIC" 2>&1 | grep "average rate" | tail -2
  echo "HZ_END"
fi

if [ "$RUN_S" -gt 0 ]; then
  echo "RUNNING_FOR ${RUN_S}s"
  sleep "$RUN_S"
else
  echo "(no duration given: waiting for signal)"
  wait $NODE_PID
fi

# SIGINT, not SIGKILL: the map and trajectory are written on the normal shutdown path.
kill -INT $NODE_PID 2>/dev/null
for i in $(seq 1 60); do
  kill -0 $NODE_PID 2>/dev/null || break
  sleep 1
done
kill -0 $NODE_PID 2>/dev/null && kill -TERM $NODE_PID 2>/dev/null

echo "TRAJECTORY $(wc -l < "$OUT/traj_lidar.txt" 2>/dev/null || echo 0) poses"
echo "SUBMAPS $(ls -d "$OUT"/0* 2>/dev/null | wc -l)"
echo "SLAM_LIVE_DONE"
