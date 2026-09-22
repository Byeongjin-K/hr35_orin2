#!/bin/bash
# Run the GNSS node so it outlives the shell that started it.
#
# /gps_msg and /gps_att come from ~/hr35 (excavator_signal_manager), not from this
# workspace, and on this machine that stack is not running - measured: zero publishers on
# every ROS domain scanned, and no signal-manager process on the host. The GNSS itself is
# fine: the receiver at 192.168.0.7 broadcasts NMEA to UDP 5017 at 10 Hz, quality 4.
# gnss_gps_node binds that socket and republishes it, so running this one node is enough
# to put RTK GNSS on the live domain without touching CAN or any control node.
#
# Two details that are not free choices:
#   * setsid. Started from an agent or an SSH shell, the node inherits that session and
#     dies with it. A field recording that loses GNSS halfway is not repairable.
#   * exec of the installed binary, not "ros2 run". The python wrapper does not forward
#     SIGINT, which this project has already paid for once (a SLAM dump that ended up
#     0 bytes because the wrapper swallowed the signal).

set -u

DOMAIN="${ROS_DOMAIN_ID:-7}"
HR35=/home/kimm/hr35/install
CFG="$HR35/excavator_signal_manager/share/excavator_signal_manager/config/gnss_config.yaml"
BIN="$HR35/excavator_signal_manager/lib/excavator_signal_manager/gnss_gps_node"
LOG_DIR=/home/kimm/data/field_logs
LOG="$LOG_DIR/gnss_gps_node_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"

if [ ! -x "$BIN" ]; then
  echo "NO_GNSS_BINARY $BIN"
  exit 1
fi

if pgrep -f -- "$BIN" >/dev/null; then
  echo "GNSS_ALREADY_RUNNING pid=$(pgrep -f -- "$BIN" | tr '\n' ' ')"
  exit 0
fi

set +u
source /opt/ros/humble/setup.bash
source /home/kimm/robot_ws/install/setup.bash
set -u
export ROS_DOMAIN_ID="$DOMAIN"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"

# The process check above only sees this host. The deployed signal_manager may be running
# somewhere else on the network, and two parsers of the same UDP broadcast would put two
# copies of every fix on /gps_msg. Ask the graph, not the process table.
PUBS=$(timeout 12 ros2 topic info /gps_msg 2>/dev/null | grep -m1 'Publisher count:' | awk '{print $3}')
if [ "${PUBS:-0}" -gt 0 ]; then
  echo "GNSS_ALREADY_PUBLISHED /gps_msg has ${PUBS} publisher(s) on domain $DOMAIN - not starting a second one"
  exit 0
fi

setsid env \
  ROS_DOMAIN_ID="$DOMAIN" \
  RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}" \
  bash -c "
    set +u
    source /opt/ros/humble/setup.bash
    source /home/kimm/robot_ws/install/setup.bash
    source $HR35/setup.bash
    set -u
    exec '$BIN' --ros-args --params-file '$CFG' -r __node:=gnss_gps_node
  " >> "$LOG" 2>&1 < /dev/null &

sleep 3
PID=$(pgrep -f -- "$BIN" | head -1)
if [ -z "$PID" ]; then
  echo "GNSS_FAILED_TO_START  see $LOG"
  tail -20 "$LOG"
  exit 1
fi
echo "GNSS_STARTED pid=$PID domain=$DOMAIN log=$LOG"
