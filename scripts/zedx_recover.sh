#!/usr/bin/env bash
# zedx_recover.sh - recover a wedged ZED X capture stack WITHOUT rebooting.
#
# Ladder, cheapest first; it stops as soon as the camera opens:
#   1 stop-clients     retire every process holding a camera (the wedge deepens
#                      while one is alive, and unbind/rmmod on an open fd is fatal)
#   2 restart-nvargus  drop argus' orphaned capture session
#   (removed) rebind-sensors  unbinding the zedx i2c clients oopsed the kernel on
#                      2026-09-14: the re-bind failed and a live Argus thread then
#                      dereferenced the dead subdev in tegra_channel_set_power.
#                      panic_on_oops=1 turned that into a reboot. Never again.
#   3 repair-refcnt    ONLY when /sys/module/sl_zedx/refcnt < 0: restore the base
#                      module reference with tools/zedx_refcnt so rmmod becomes legal
#   4 reload-drivers   systemctl restart zed_x_daemon, i.e. the vendor's real
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
# Resolved without ".." so it matches the sudoers rule literally: sudo compares the command
# string, and /etc/sudoers.d/zedx-recovery lists the canonical path.
REFCNT_TOOL="${ZEDX_REFCNT_TOOL:-$(cd "$HERE/.." && pwd)/tools/zedx_refcnt}"
SERIAL="${ZEDX_SERIAL:-49749405}"
# Dry run is the DEFAULT. On 2026-09-14 `--safe --plan` executed the real ladder because
# only $1 was inspected, which killed a streaming node and wedged the stack. A script that
# kills processes and restarts daemons must never execute by accident: --run is required.
PLAN_ONLY=1
SAFE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --run)  PLAN_ONLY=0 ;;
    --plan) PLAN_ONLY=1 ;;
    --safe) SAFE=1 ;;
    *) echo "unknown option: $1" >&2
       echo "usage: $(basename "$0") [--run] [--safe]   (default: plan only)" >&2
       exit 64 ;;
  esac
  shift
done

refcnt="$(cat "$MODULE_DIR/sl_zedx/refcnt" 2>/dev/null || echo unknown)"
clients="$(pgrep -af "$CLIENT_PATTERN" 2>/dev/null | head -5 || true)"
client_n="$(printf '%s' "$clients" | grep -c . )"

echo "STATE refcnt=$refcnt clients=$client_n"

n=0
step() { n=$((n+1)); echo "STEP $n $1"; }
[ "$client_n" -gt 0 ] && step "stop-clients"
step "restart-nvargus"
damaged=0
if [ "$refcnt" != "unknown" ] && [ "$refcnt" -lt 0 ] 2>/dev/null; then
  step "repair-refcnt"
  echo "CMD  insmod $REFCNT_TOOL/zedx_refcnt.ko target=sl_zedx driver=zedx repair=1"
  damaged=1
fi
if [ "$SAFE" = 1 ]; then
  echo "SAFE stops after the repair: the last rung unloads kernel modules, and that needs a human."
else
  if [ "$damaged" = 1 ]; then
    echo "GUARD the last rung stays blocked until refcnt >= 0 (rmmod at atomic 0 can panic this kernel)"
  fi
  step "reload-drivers"
fi

if [ "$PLAN_ONLY" = 1 ]; then
  echo "PLAN ONLY - nothing was executed. Add --run to execute."
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

say "2 restart-nvargus"
$SUDO systemctl restart nvargus-daemon
for _ in $(seq 1 30); do [ "$(systemctl is-active nvargus-daemon)" = active ] && break; sleep 0.5; done
probe_ok && { echo "RECOVERED after restart-nvargus"; exit 0; }

# The fd guard belongs HERE, not before restart-nvargus: nvargus-daemon is itself the
# legitimate holder of /dev/video*, and restarting it is what makes it let go. Checking
# first made the ladder abort forever on a wedged stack (2026-09-14). Everything below
# touches the kernel, so nothing may hold a camera fd past this line.
held="$(ls -l /proc/[0-9]*/fd 2>/dev/null | grep -cE '/dev/video')"
echo "camera fds held: $held"
if [ "$held" -ne 0 ]; then
  echo "ABORT: something still holds /dev/video* after restarting argus; refusing to touch the kernel:"
  ls -l /proc/[0-9]*/fd 2>/dev/null | grep -E '/dev/video' | head -5 | sed 's/^/    /'
  exit 3
fi


say "3 repair-refcnt"
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

# This is the rung that actually revived the camera on 2026-09-14. Try it BEFORE touching
# any module: reloading the drivers makes zed_x_daemon re-open the GMSL ports on its own, and
# that failing attempt spends the reference we just restored.
probe_ok && { echo "RECOVERED after repair-refcnt"; exit 0; }

if [ "$SAFE" = 1 ]; then
  echo
  echo "SAFE MODE: repairing the reference was not enough, and the rest unloads kernel modules."
  echo "Run it yourself, watching the output:  sudo $0 --run"
  exit 2
fi

say "4 reload-drivers"
if [ "$refcnt" = "unknown" ] || [ "$refcnt" -lt 0 ] 2>/dev/null; then
  echo "ABORT: refcnt=$refcnt is still negative. Refusing to let zed_x_daemon run rmmod:"
  echo "       BUG_ON in try_release_module_ref() would panic this kernel (panic_on_oops=1)."
  echo "       Reboot is the only remaining option."
  exit 5
fi
$SUDO systemctl restart zed_x_daemon
for _ in $(seq 1 40); do
  journalctl -u zed_x_daemon --no-pager --since '-2min' | grep -q 'ZED-X Driver loaded' && break; sleep 1
done
# The daemon logs "ZED-X Driver loaded" even when every rmmod/insmod inside it failed.
if journalctl -u zed_x_daemon --no-pager --since '-2min' | grep -qE 'is in use|File exists'; then
  echo "reload did NOT happen (rmmod/insmod refused):"
  journalctl -u zed_x_daemon --no-pager --since '-2min' | grep -E 'rmmod|insmod' | tail -6
  echo "FAILED: reboot required"
  exit 6
fi
echo "driver reload verified (no 'is in use' / 'File exists' in the daemon log)"
probe_ok && { echo "RECOVERED after reload-drivers"; exit 0; }

echo "FAILED: every rung exhausted; reboot required"
exit 7
