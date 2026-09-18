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
# Exit codes: 0 recovered, 2 --safe stopped early, 3 a camera fd is still held,
# 4 refcnt repair failed, 5 refcnt still negative, 6 the daemon reload did not happen,
# 7 every rung exhausted, 8 a camera client survived stop-clients, 64 bad usage.
#
# Seams for tests: ZEDX_MODULE_DIR, ZEDX_CLIENT_PATTERN, ZEDX_JOURNAL_CMD,
# ZEDX_SYSTEMCTL_CMD, ZEDX_PROBE_CMD, ZEDX_POLL_SLEEP, ZEDX_SOURCE_ONLY.
# Root via $SUDO (default sudo). Only READ-ONLY commands go through a seam: the mutating
# systemctl calls stay literal because /etc/sudoers.d/zedx-recovery matches them as strings.
set -u

MODULE_DIR="${ZEDX_MODULE_DIR:-/sys/module}"
CLIENT_PATTERN="${ZEDX_CLIENT_PATTERN:-component_container|ZED_Explorer|ZED_Depth_Viewer|ZED_Media_Server}"
SUDO="${SUDO:-sudo}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Resolved without ".." so it matches the sudoers rule literally: sudo compares the command
# string, and /etc/sudoers.d/zedx-recovery lists the canonical path.
REFCNT_TOOL="${ZEDX_REFCNT_TOOL:-$(cd "$HERE/.." && pwd)/tools/zedx_refcnt}"
SERIAL="${ZEDX_SERIAL:-49749405}"
# Read-only seams. Each defaults to the real command, so an unset environment behaves
# exactly as before; scripts/test_zedx_recover.sh substitutes fakes for them.
JOURNAL="${ZEDX_JOURNAL_CMD:-journalctl}"
SYSTEMCTL="${ZEDX_SYSTEMCTL_CMD:-systemctl}"
PROBE_CMD="${ZEDX_PROBE_CMD:-}"
POLL_SLEEP="${ZEDX_POLL_SLEEP:-1}"
PGREP="${ZEDX_PGREP_CMD:-pgrep}"
PKILL="${ZEDX_PKILL_CMD:-pkill}"
KILL_SLEEP="${ZEDX_KILL_SLEEP:-0.5}"

# Keep the probe's output. Throwing stderr away made "FAILED: reboot required" indistinguishable
# from "we probed while the driver was still unloaded", which is what it actually was on
# 2026-09-18.
PROBE_LAST=""
probe_ok() {
  local out
  if [ -n "$PROBE_CMD" ]; then
    out="$($PROBE_CMD 2>&1)"
  else
    out="$(timeout -k 5 75 python3 - "$SERIAL" 2>&1 <<'PY'
import sys, pyzed.sl as sl
init = sl.InitParameters(); init.set_from_serial_number(int(sys.argv[1]))
init.camera_resolution = sl.RESOLUTION.HD1200; init.camera_fps = 15
init.depth_mode = sl.DEPTH_MODE.NONE
cam = sl.Camera(); st = cam.open(init)
print("OPEN", st)
if st == sl.ERROR_CODE.SUCCESS: cam.close()
PY
)"
  fi
  PROBE_LAST="$out"
  printf '%s\n' "$out" | grep -q '^OPEN SUCCESS'
}
say() { echo; echo "=== $* ==="; }

# Returns 0 only when nothing matches the pattern any more. A supervisor (ros2 launch)
# respawns the container, so SIGKILL on the container alone does not settle it: on 2026-09-18
# component_container[886377] outlived this step and reconnected to argus at 15:54:55 and
# 15:55:35, which left every later rung working against a live client.
stop_clients() { # $1 pattern -> 0 cleared, 1 still alive
  local pat="$1" left=20
  $PKILL -CONT -f "$pat" 2>/dev/null
  $PKILL -INT  -f "$pat" 2>/dev/null
  while [ "$left" -gt 0 ]; do
    $PGREP -f "$pat" >/dev/null || return 0
    sleep "$KILL_SLEEP"; left=$((left-1))
  done
  $PKILL -KILL -f "$pat" 2>/dev/null
  left=10
  while [ "$left" -gt 0 ]; do
    $PGREP -f "$pat" >/dev/null || return 0
    sleep "$KILL_SLEEP"; left=$((left-1))
  done
  return 1
}

# systemd gives every service start a fresh InvocationID, and journald tags that start's
# lines with it. It is the only way to ask "did THIS restart finish?" without a time window.
daemon_invocation() {
  $SYSTEMCTL show -p InvocationID --value zed_x_daemon 2>/dev/null
}

# A RELATIVE window is wrong here. On 2026-09-18 step 2 had already made the daemon reload at
# 15:54:39, so at 15:55:49 the '-2min' window still held that line: the wait broke on its first
# poll, probe_ok ran while the driver was unloaded (the daemon logged no OPENING at all) and the
# ladder reported "reboot required" for a stack that was fine. Scope to THIS start instead.
daemon_log() { # $1 invocation id
  local inv="${1:-}"
  if [ -n "$inv" ]; then
    $JOURNAL -u zed_x_daemon --no-pager "_SYSTEMD_INVOCATION_ID=$inv" 2>/dev/null
  else
    $JOURNAL -u zed_x_daemon --no-pager --since '-2min' 2>/dev/null
  fi
}

wait_for_driver_reload() { # $1 invocation id, $2 poll count
  local inv="${1:-}" left="${2:-40}" log
  while [ "$left" -gt 0 ]; do
    log="$(daemon_log "$inv")"
    # "Driver loaded" alone is not the finish line: the daemon restarts NVArgus immediately
    # after it, and a probe fired into that gap cannot reach the camera. "Created Pub Endpoint"
    # is the daemon's own last start-up line (2026-09-18: loaded and endpoint both at 15:56:00,
    # while the premature probe had already run at 15:55:50).
    if printf '%s' "$log" | grep -q 'ZED-X Driver loaded' \
       && printf '%s' "$log" | grep -q 'Created Pub Endpoint'; then
      return 0
    fi
    sleep "$POLL_SLEEP"; left=$((left-1))
  done
  return 1
}

wait_for_argus_active() { # $1 poll count
  local left="${1:-30}"
  while [ "$left" -gt 0 ]; do
    [ "$($SYSTEMCTL is-active nvargus-daemon 2>/dev/null)" = active ] && return 0
    sleep "$POLL_SLEEP"; left=$((left-1))
  done
  return 1
}

# The daemon prints "ZED-X Driver loaded" even when every rmmod/insmod inside it failed,
# so the reload has to be verified separately.
reload_refused() { # $1 invocation id
  daemon_log "$1" | grep -qE 'is in use|File exists'
}

reload_refusal_lines() { # $1 invocation id
  daemon_log "$1" | grep -E 'rmmod|insmod' | tail -6
}

# Tests load the functions above without running the ladder.
if [ "${ZEDX_SOURCE_ONLY:-0}" = 1 ]; then
  return 0 2>/dev/null || exit 0
fi

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

say "1 stop-clients"
if [ "$client_n" -gt 0 ]; then
  if ! stop_clients "$CLIENT_PATTERN"; then
    echo "ABORT: a camera client survived SIGKILL, so something keeps respawning it:"
    $PGREP -af "$CLIENT_PATTERN" 2>/dev/null | head -5 | sed 's/^/    /'
    echo "       Every rung below assumes nothing is touching the camera; running them against"
    echo "       a live client is what made the 2026-09-18 recovery fight a moving target."
    echo "       Stop the launcher first (sensors stop, or Ctrl-C the launch), then re-run."
    exit 8
  fi
fi

say "2 restart-nvargus"
$SUDO systemctl restart nvargus-daemon
for _ in $(seq 1 30); do [ "$($SYSTEMCTL is-active nvargus-daemon)" = active ] && break; sleep 0.5; done
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
inv="$(daemon_invocation)"
if ! wait_for_driver_reload "$inv" 40; then
  echo "FAILED: zed_x_daemon never finished starting after the restart"
  echo "        (no 'ZED-X Driver loaded' + 'Created Pub Endpoint' for invocation ${inv:-<unknown>})"
  exit 6
fi
# The daemon restarts NVArgus as part of its own start-up; probing before argus is back is
# what produced the false "reboot required" on 2026-09-18.
wait_for_argus_active 30 || echo "WARNING: nvargus-daemon is not active yet; the probe may fail"
if reload_refused "$inv"; then
  echo "reload did NOT happen (rmmod/insmod refused):"
  reload_refusal_lines "$inv"
  echo "FAILED: reboot required"
  exit 6
fi
echo "driver reload verified (no 'is in use' / 'File exists' in the daemon log)"
probe_ok && { echo "RECOVERED after reload-drivers"; exit 0; }

echo "the camera still does not open. Last probe output:"
printf '%s\n' "${PROBE_LAST:-<no probe output>}" | tail -5 | sed 's/^/    /'
echo "FAILED: every rung exhausted; reboot required"
exit 7
