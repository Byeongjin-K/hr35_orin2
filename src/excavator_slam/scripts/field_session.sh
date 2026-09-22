#!/bin/bash
# One command for a field session: bring the cabin LiDAR up, record, put it back.
#
# record_field_session.sh deliberately changes no machine state, and it lists
# /lidar_cabin/points and /lidar_cabin/imu as required. Nothing starts that driver:
# the deployed workspace (~/robot_ws, built from main) has no cabin_only_driver.launch.py,
# only this branch does. So running the recorder alone on this machine refuses at
# preflight, every time, with the cabin missing. This file is that missing half.
#
# Three things here are not obvious from the code:
#   * The overlay order matters. ouster_ros and the excavator message types live in
#     ~/robot_ws/install; hr35_bringup must come from THIS worktree afterwards or the
#     launch file does not exist and the cabin params silently fall back to main's.
#   * Readiness is message flow, not node presence. A healthy-looking os_driver that
#     never publishes has already cost this project one debugging session.
#   * ROS_DOMAIN_ID must be exported and asserted. Sourcing ROS re-reads ~/.bashrc
#     defaults in some shells, and a domain mismatch here means recording an empty bag
#     while the sensors talk on another domain.

set -u

BAG_DIR="${1:-/home/kimm/data/field_$(date +%Y%m%d_%H%M%S)}"
DURATION="${2:-0}"
EXPECT_DOMAIN="${ROS_DOMAIN_ID:-7}"

WORKTREE=/home/kimm/robot_ws-lidar-slam
DEPLOYED=/home/kimm/robot_ws
CABIN_PARAMS="$WORKTREE/src/hr35_bringup/config/lidar_cabin_params.yaml"
LOG_DIR=/home/kimm/data/field_logs
CABIN_LOG="$LOG_DIR/cabin_driver_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"

export ROS_DOMAIN_ID="$EXPECT_DOMAIN"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

set +u
source /opt/ros/humble/setup.bash
source "$DEPLOYED/install/setup.bash"
source "$WORKTREE/install/setup.bash"
set -u

export ROS_DOMAIN_ID="$EXPECT_DOMAIN"
if [ "${ROS_DOMAIN_ID:-}" != "$EXPECT_DOMAIN" ]; then
  echo "DOMAIN_ASSERT_FAILED want=$EXPECT_DOMAIN got=${ROS_DOMAIN_ID:-unset}"
  exit 1
fi
echo "DOMAIN $ROS_DOMAIN_ID   RMW $RMW_IMPLEMENTATION"

LAUNCH_FILE=$(ros2 pkg prefix hr35_bringup 2>/dev/null)/share/hr35_bringup/launch/cabin_only_driver.launch.py
if [ ! -f "$LAUNCH_FILE" ]; then
  echo "NO_CABIN_LAUNCH $LAUNCH_FILE"
  echo "hr35_bringup resolved to a workspace without the cabin launch. Build this worktree:"
  echo "  cd $WORKTREE && colcon build --packages-select hr35_bringup"
  exit 1
fi
echo "CABIN_LAUNCH $LAUNCH_FILE"

SENSOR_IP=$(grep -m1 "sensor_hostname:" "$CABIN_PARAMS" | tr -d " '\"" | cut -d: -f2)
echo "CABIN_SENSOR $SENSOR_IP"

# GNSS first, because it needs a few seconds to advertise and the cabin needs forty to boot.
# The helper refuses to start a second publisher, so this is a no-op whenever the deployed
# signal_manager is already up. It is left running afterwards: unlike the cabin LiDAR it puts
# no sensor into a streaming mode, and /gps_msg is an input the deployed stack expects.
if [ "${START_GNSS:-1}" = "1" ]; then
  bash "$WORKTREE/src/excavator_slam/scripts/gnss_node_detached.sh"
fi

CABIN_PID=""
CABIN_WAS_MINE=0

teardown() {
  if [ "$CABIN_WAS_MINE" = "1" ] && [ -n "$CABIN_PID" ]; then
    echo "--- stopping the cabin driver this script started (process group $CABIN_PID)"
    kill -INT -- "-$CABIN_PID" 2>/dev/null
    for _ in $(seq 1 20); do
      kill -0 "$CABIN_PID" 2>/dev/null || break
      sleep 0.5
    done
    kill -0 "$CABIN_PID" 2>/dev/null && kill -TERM -- "-$CABIN_PID" 2>/dev/null
    wait "$CABIN_PID" 2>/dev/null
    pkill -f -- "__node:=tf_publisher_cabin" 2>/dev/null
    STANDBY=$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H 'Content-Type: application/json' \
      -d '"STANDBY"' "http://$SENSOR_IP/api/v1/sensor/config/operating_mode" 2>/dev/null)
    echo "CABIN_STANDBY http=$STANDBY   (204 or 200 means the sensor stopped streaming)"
    echo "CABIN_LOG $CABIN_LOG"
  fi
}
trap teardown EXIT

if timeout 15 ros2 topic list 2>/dev/null | grep -qx /lidar_cabin/points; then
  echo "CABIN_ALREADY_UP  (leaving it alone, and leaving it running afterwards)"
else
  echo "--- starting the cabin driver, log -> $CABIN_LOG"
  setsid ros2 launch hr35_bringup cabin_only_driver.launch.py \
    params_file:="$CABIN_PARAMS" > "$CABIN_LOG" 2>&1 &
  CABIN_PID=$!
  CABIN_WAS_MINE=1

  DEADLINE=$((SECONDS + 90))
  READY=0
  while [ "$SECONDS" -lt "$DEADLINE" ]; do
    if ! kill -0 "$CABIN_PID" 2>/dev/null; then
      echo "CABIN_DRIVER_DIED  see $CABIN_LOG"
      tail -20 "$CABIN_LOG"
      exit 1
    fi
    if timeout 6 ros2 topic echo /lidar_cabin/points --once --field height >/dev/null 2>&1 &&
       timeout 6 ros2 topic echo /lidar_cabin/imu --once --field header.stamp.sec >/dev/null 2>&1; then
      READY=1
      break
    fi
  done
  if [ "$READY" != "1" ]; then
    echo "CABIN_NOT_PUBLISHING after 90 s.  see $CABIN_LOG"
    tail -20 "$CABIN_LOG"
    exit 1
  fi
  echo "CABIN_READY  both /lidar_cabin/points and /lidar_cabin/imu delivered a message"
fi

"$WORKTREE/src/excavator_slam/scripts/record_field_session.sh" "$BAG_DIR" "$DURATION"
RECORD_STATUS=$?
echo "FIELD_SESSION_STATUS $RECORD_STATUS"
exit "$RECORD_STATUS"
