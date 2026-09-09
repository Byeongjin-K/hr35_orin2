#!/usr/bin/env bash
# zedx_recover.sh - recover a wedged ZED X capture stack WITHOUT rebooting.
#
# Ladder, cheapest first; it stops as soon as the camera opens:
#   1 stop-clients     retire every process holding a camera (the wedge deepens
#                      while one is alive, and unbind/rmmod on an open fd is fatal)
#   2 restart-nvargus  drop argus' orphaned capture session
#   3 rebind-sensors   re-probe the zedx i2c clients: re-registers the v4l2 subdevs
#                      without unloading anything, so a damaged refcount cannot block it
#   4 repair-refcnt    ONLY when /sys/module/sl_zedx/refcnt < 0: restore the base
#                      module reference with tools/zedx_refcnt so rmmod becomes legal
#   5 reload-drivers   systemctl restart zed_x_daemon, i.e. the vendor's real
#                      rmmod+insmod, and then VERIFY it actually happened
#
# HARD GUARD: on this kernel panic_on_oops=1 and rmmod on a module whose atomic
# refcount is 0 can hit BUG_ON(ret < 0) in try_release_module_ref() -> panic.
# Step 5 therefore never runs until step 4 has driven sysfs refcnt >= 0.
#
#   --plan   print the ladder it would run for the current state, execute nothing
#
# Seams for tests: ZEDX_MODULE_DIR, ZEDX_CLIENT_PATTERN. Root via $SUDO (default sudo).
set -u

MODULE_DIR="${ZEDX_MODULE_DIR:-/sys/module}"
CLIENT_PATTERN="${ZEDX_CLIENT_PATTERN:-component_container|ZED_Explorer|ZED_Depth_Viewer|ZED_Media_Server}"
SUDO="${SUDO:-sudo}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REFCNT_TOOL="${ZEDX_REFCNT_TOOL:-$HERE/../tools/zedx_refcnt}"
SERIAL="${ZEDX_SERIAL:-49749405}"
PLAN_ONLY=0
[ "${1:-}" = "--plan" ] && PLAN_ONLY=1

refcnt="$(cat "$MODULE_DIR/sl_zedx/refcnt" 2>/dev/null || echo unknown)"
clients="$(pgrep -af "$CLIENT_PATTERN" 2>/dev/null | head -5 || true)"
client_n="$(printf '%s' "$clients" | grep -c . )"

echo "STATE refcnt=$refcnt clients=$client_n"

n=0
step() { n=$((n+1)); echo "STEP $n $1"; }
[ "$client_n" -gt 0 ] && step "stop-clients"
step "restart-nvargus"
step "rebind-sensors"
if [ "$refcnt" != "unknown" ] && [ "$refcnt" -lt 0 ] 2>/dev/null; then
  step "repair-refcnt"
  echo "GUARD reload-drivers stays blocked until refcnt >= 0 (rmmod at atomic 0 can panic this kernel)"
fi
step "reload-drivers"

if [ "$PLAN_ONLY" = 1 ]; then
  echo "PLAN ONLY - nothing was executed"
  exit 0
fi

probe_ok() {
  timeout -k 5 75 python3 - "$SERIAL" <<'PY' 2>/dev/null | grep -q '^OPEN SUCCESS'
import sys, pyzed.sl as sl
init = sl.InitParameters(); init.set_from_serial_number(int(sys.argv[1]))
init.camera_resolution = sl.RESOLUTION.HD1200; init.camera_fps = 15
init.depth_mode = sl.DEPTH_MODE.NONE
cam = sl.Camera(); st = cam.open(init)
print("OPEN", st)
if st == sl.ERROR_CODE.SUCCESS: cam.close()
PY
}
say() { echo; echo "=== $* ==="; }

say "1 stop-clients"
if [ "$client_n" -gt 0 ]; then
  pkill -CONT -f "$CLIENT_PATTERN" 2>/dev/null
  pkill -INT  -f "$CLIENT_PATTERN" 2>/dev/null
  for _ in $(seq 1 20); do pgrep -f "$CLIENT_PATTERN" >/dev/null || break; sleep 0.5; done
  pgrep -f "$CLIENT_PATTERN" >/dev/null && pkill -KILL -f "$CLIENT_PATTERN"
fi
held="$(ls -l /proc/[0-9]*/fd 2>/dev/null | grep -cE '/dev/video')"
echo "camera fds held: $held"
[ "$held" -eq 0 ] || { echo "ABORT: something still holds /dev/video*; refusing to touch drivers"; exit 3; }

say "2 restart-nvargus"
$SUDO systemctl restart nvargus-daemon
for _ in $(seq 1 30); do [ "$($SUDO systemctl is-active nvargus-daemon)" = active ] && break; sleep 0.5; done
probe_ok && { echo "RECOVERED after restart-nvargus"; exit 0; }

say "3 rebind-sensors"
for d in 10-0020 10-0028; do echo "$d" | $SUDO tee /sys/bus/i2c/drivers/zedx/unbind >/dev/null 2>&1; done
for d in 10-0020 10-0028; do echo "$d" | $SUDO tee /sys/bus/i2c/drivers/zedx/bind   >/dev/null 2>&1; done
$SUDO systemctl restart nvargus-daemon
for _ in $(seq 1 30); do [ "$($SUDO systemctl is-active nvargus-daemon)" = active ] && break; sleep 0.5; done
probe_ok && { echo "RECOVERED after rebind-sensors"; exit 0; }

say "4 repair-refcnt"
refcnt="$(cat /sys/module/sl_zedx/refcnt 2>/dev/null || echo unknown)"
if [ "$refcnt" != "unknown" ] && [ "$refcnt" -lt 0 ] 2>/dev/null; then
  [ -f "$REFCNT_TOOL/zedx_refcnt.ko" ] || (cd "$REFCNT_TOOL" && make) || { echo "ABORT: cannot build zedx_refcnt"; exit 4; }
  $SUDO rmmod zedx_refcnt 2>/dev/null
  $SUDO insmod "$REFCNT_TOOL/zedx_refcnt.ko" target=sl_zedx driver=zedx repair=1 || { echo "ABORT: repair failed"; exit 4; }
  $SUDO rmmod zedx_refcnt 2>/dev/null
  refcnt="$(cat /sys/module/sl_zedx/refcnt)"
  echo "refcnt after repair: $refcnt"
else
  echo "refcnt=$refcnt, nothing to repair"
fi

say "5 reload-drivers"
if [ "$refcnt" = "unknown" ] || [ "$refcnt" -lt 0 ] 2>/dev/null; then
  echo "ABORT: refcnt=$refcnt is still negative. Refusing to let zed_x_daemon run rmmod:"
  echo "       BUG_ON in try_release_module_ref() would panic this kernel (panic_on_oops=1)."
  echo "       Reboot is the only remaining option."
  exit 5
fi
$SUDO systemctl restart zed_x_daemon
for _ in $(seq 1 40); do
  $SUDO journalctl -u zed_x_daemon --no-pager --since '-2min' | grep -q 'ZED-X Driver loaded' && break; sleep 1
done
# The daemon logs "ZED-X Driver loaded" even when every rmmod/insmod inside it failed.
if $SUDO journalctl -u zed_x_daemon --no-pager --since '-2min' | grep -qE 'is in use|File exists'; then
  echo "reload did NOT happen (rmmod/insmod refused):"
  $SUDO journalctl -u zed_x_daemon --no-pager --since '-2min' | grep -E 'rmmod|insmod' | tail -6
  echo "FAILED: reboot required"
  exit 6
fi
echo "driver reload verified (no 'is in use' / 'File exists' in the daemon log)"
probe_ok && { echo "RECOVERED after reload-drivers"; exit 0; }

echo "FAILED: every rung exhausted; reboot required"
exit 7
