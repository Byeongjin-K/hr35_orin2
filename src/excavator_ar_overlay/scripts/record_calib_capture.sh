#!/bin/bash
# Capture one LiDAR<->camera calibration pose.
#
#   ./record_calib_capture.sh <label> [seconds]
#
# Everything must stay STILL for the whole capture: boom, machine, target, and
# anything in the scene. That is not a nicety -- the Ouster stamps its clouds
# with sensor uptime (order 1e4 s) while the ZED stamps with epoch time (order
# 1e9 s), so the two streams cannot be time-aligned. A static scene removes the
# question entirely.
set -euo pipefail

LABEL="${1:?usage: $0 <label> [seconds]}"
SECONDS_TO_RECORD="${2:-20}"
OUT_ROOT="${CALIB_OUT_ROOT:-/home/kimm/data/lidar_cam_calib}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${OUT_ROOT}/${STAMP}_${LABEL}"

TOPICS=(
  /lidar_boom/points
  /zedx_boom/zedx_boom_node/rgb/image_rect_color/compressed
  /zedx_boom/zedx_boom_node/rgb/camera_info
  /tf
  /tf_static
)

echo "=============================================================="
echo " capture : ${LABEL}"
echo " output  : ${OUT}"
echo " duration: ${SECONDS_TO_RECORD}s  (~$((SECONDS_TO_RECORD * 33)) MB)"
echo "=============================================================="
echo
echo "  [ ] boom parked and NOT moving"
echo "  [ ] engine idle / machine not rocking"
echo "  [ ] target fully inside the camera view"
echo "  [ ] target face angled ~20-40 deg away from straight-on"
echo "  [ ] nobody walking through the scene"
echo
read -r -p "all still? press ENTER to record, Ctrl+C to abort " _

mkdir -p "${OUT_ROOT}"
timeout "$((SECONDS_TO_RECORD + 5))" \
  ros2 bag record -o "${OUT}" "${TOPICS[@]}" &
REC_PID=$!
sleep "${SECONDS_TO_RECORD}"
kill -INT "${REC_PID}" 2>/dev/null || true
wait "${REC_PID}" 2>/dev/null || true

echo
echo "recorded -> ${OUT}"
ros2 bag info "${OUT}" 2>/dev/null | grep -aE "Duration|Messages|Topic information" || true
echo
echo "next: move the target (or the boom) and run this again with a new label."
