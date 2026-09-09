#!/bin/bash
# Record a field session, but refuse to start unless the data is actually there.
#
# A field session cannot be repeated cheaply, and every failure this guards against has
# already happened once on this machine:
#
#   * The recorder saw no GNSS. The host runs rmw_cyclonedds_cpp while the GNSS reaches
#     rmw_fastrtps_cpp, and cross-vendor DDS discovery does not work - measured, with the
#     host reporting an EMPTY node list at the same moment a container saw /gps_msg at
#     10.0 Hz. A bag missing GNSS cannot be compared against the deployed baseline at all.
#   * The GNSS was not RTK. Every existing recording carries quality 1 while the deployed
#     rn_global_map accepts quality 4 only, so the whole set is unusable as a baseline.
#   * The LiDAR stamped on its own oscillator, about 1.76e9 s away from host time, and a
#     SLAM tool reading such a bag processes exactly one scan and silently discards the
#     rest. Fixed for the cabin sensor in lidar_cabin_params.yaml - this checks it held.
#
# So: preflight first, record second. Nothing here changes machine state.

BAG_DIR="$1"
DURATION="$2"
if [ -z "$BAG_DIR" ]; then BAG_DIR=/home/kimm/data/field_$(date +%Y%m%d_%H%M%S); fi
if [ -z "$DURATION" ]; then DURATION=0; fi

set +u
source /opt/ros/humble/setup.bash
source /home/kimm/robot_ws/install/setup.bash
set -u

REQUIRED="/lidar_cabin/points /lidar_cabin/imu /lidar_boom/points /lidar_boom/imu /gps_msg /gps_att /excavator/sensors/swing_encoder_output /kine_data"
OPTIONAL="/tf /tf_static /excavator/sensors/gnss_position /excavator/sensors/gnss_velocity /excavator/sensors/joint_boom /excavator/sensors/joint_arm /excavator/sensors/joint_bucket /excavator/sensors/boom_inclino /excavator/sensors/swing_angle"

# Which middleware actually sees the data? Decided by counting, not by belief.
BEST_RMW=""
BEST_SEEN=-1
for CANDIDATE in rmw_cyclonedds_cpp rmw_fastrtps_cpp; do
  export RMW_IMPLEMENTATION="$CANDIDATE"
  SEEN=0
  VISIBLE=$(timeout 20 ros2 topic list 2>/dev/null)
  for T in $REQUIRED; do
    echo "$VISIBLE" | grep -qx "$T" && SEEN=$((SEEN + 1))
  done
  echo "RMW_SCAN $CANDIDATE sees $SEEN of $(echo $REQUIRED | wc -w) required topics"
  if [ "$SEEN" -gt "$BEST_SEEN" ]; then BEST_SEEN="$SEEN"; BEST_RMW="$CANDIDATE"; fi
done
export RMW_IMPLEMENTATION="$BEST_RMW"
echo "RMW_CHOSEN $BEST_RMW"

echo "--- preflight: every required topic present and publishing"
MISSING=""
for T in $REQUIRED; do
  RATE=$(timeout 12 ros2 topic hz "$T" 2>/dev/null | grep -m1 "average rate" | awk '{print $3}')
  if [ -z "$RATE" ]; then
    echo "  MISSING  $T"
    MISSING="$MISSING $T"
  else
    echo "  ok       $T  $RATE Hz"
  fi
done

echo "--- preflight: GNSS must be RTK fixed (quality 4)"
QUALITY=$(timeout 20 ros2 topic echo /gps_msg --once 2>/dev/null | grep -m1 "^quality:" | awk '{print $2}')
SATS=$(timeout 20 ros2 topic echo /gps_msg --once 2>/dev/null | grep -m1 "^sat:" | awk '{print $2}')
echo "  quality=$QUALITY sat=$SATS   (1 GPS fix, 2 DGPS, 4 RTK fix, 5 RTK float)"

echo "--- preflight: LiDAR must stamp on the ROS clock, not its own oscillator"
for T in /lidar_cabin/points /lidar_boom/points; do
  STAMP=$(timeout 15 ros2 topic echo "$T" --once --field header.stamp.sec 2>/dev/null | head -1)
  NOW=$(date +%s)
  if [ -n "$STAMP" ]; then
    SKEW=$((NOW - STAMP))
    echo "  $T header is $SKEW s from wall clock (a few seconds is fine, 1.7e9 is the bug)"
  else
    echo "  $T no message"
  fi
done

if [ -n "$MISSING" ]; then
  echo "PREFLIGHT_FAILED missing:$MISSING"
  echo "Nothing was recorded. Fix the above before spending a field session on it."
  exit 1
fi
if [ "$QUALITY" != "4" ]; then
  echo "PREFLIGHT_WARN gnss quality is $QUALITY, not 4 (RTK fix)."
  echo "Recording anyway, but this bag cannot serve as a baseline comparison."
fi
echo "PREFLIGHT_OK"

# Camera is optional and discovered rather than named: it is a second opinion for reading
# the session afterwards, never a SLAM input, and it must never cost a LiDAR packet.
ZED=$(timeout 15 ros2 topic list 2>/dev/null | grep zedx_cabin | grep -E "image_rect_color/compressed$|camera_info$|imu/data$" | tr '\n' ' ')
echo "ZED_TOPICS $ZED"

TOPICS="$REQUIRED"
for T in $OPTIONAL; do
  timeout 10 ros2 topic list 2>/dev/null | grep -qx "$T" && TOPICS="$TOPICS $T"
done
TOPICS="$TOPICS $ZED"

echo "RECORDING_TO $BAG_DIR"
echo "TOPICS $TOPICS"
if [ "$DURATION" -gt 0 ]; then
  timeout "$DURATION" ros2 bag record -o "$BAG_DIR" $TOPICS
else
  echo "(no duration given: press Ctrl-C to stop)"
  ros2 bag record -o "$BAG_DIR" $TOPICS
fi

echo "--- what landed:"
python3 - "$BAG_DIR" <<'PYEOF'
import sys, yaml
m = yaml.safe_load(open(sys.argv[1] + "/metadata.yaml"))["rosbag2_bagfile_information"]
print("duration %.1f s, %d messages" % (m["duration"]["nanoseconds"] / 1e9, m["message_count"]))
for t in sorted(m["topics_with_message_count"], key=lambda x: -x["message_count"]):
    print("  %8d  %s" % (t["message_count"], t["topic_metadata"]["name"]))
PYEOF
echo "RECORD_DONE $BAG_DIR"
