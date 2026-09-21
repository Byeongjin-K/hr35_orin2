#!/usr/bin/env bash
# zedx_health.sh — classify the ZED X (GMSL2) capture stack and print the cheapest
# recovery step that can still work. Read-only: it never restarts anything.
#
# Exit code / VERDICT:
#   0 HEALTHY          nothing to do
#   1 RECOVERABLE      a capture session outlived its client -> restart nvargus-daemon (no reboot)
#   2 REBOOT_REQUIRED  sl_zedx module use-count is broken -> rmmod impossible,
#                      `systemctl restart zed_x_daemon` is a silent no-op, only a reboot clears it
#
# Why the client check matters: nvargus logs "AlreadyAllocated: Device N is in use" every time a
# second process (ZED_Explorer, a probe, a second launch) touches a camera a running node already
# holds. That is normal contention. The same line with NO client process alive means the sensor is
# allocated to nobody -> the session is orphaned and only a daemon restart releases it.
#
# Test seams (used by scripts/test_zedx_health.sh):
#   ZEDX_MODULE_DIR      default /sys/module
#   ZEDX_ARGUS_LOG_CMD   default: nvargus-daemon journal over $ZEDX_ARGUS_WINDOW
#   ZEDX_ARGUS_WINDOW    default -15min
#   ZEDX_CLIENT_PATTERN  default: pgrep -af pattern for processes that open a ZED camera
set -u

MODULE_DIR="${ZEDX_MODULE_DIR:-/sys/module}"
REFCNT_FILE="$MODULE_DIR/sl_zedx/refcnt"
ARGUS_WINDOW="${ZEDX_ARGUS_WINDOW:--15min}"
JOURNAL="${ZEDX_JOURNAL_CMD:-journalctl}"
SYSTEMCTL="${ZEDX_SYSTEMCTL_CMD:-systemctl}"
# Scope the fault count to the argus instance running NOW. A time window cannot tell a wedged
# stack from one whose argus was just restarted by a recovery: on 2026-09-18 this script still
# saw the EGLStreamProducer fault that the recovery itself had produced 90 s earlier, and
# called a healthy stack RECOVERABLE. Faults from a dead argus instance describe the past.
ARGUS_INVOCATION="${ZEDX_ARGUS_INVOCATION:-$($SYSTEMCTL show -p InvocationID --value nvargus-daemon 2>/dev/null)}"
if [ -n "$ARGUS_INVOCATION" ]; then
  ARGUS_SCOPE="the running nvargus-daemon instance"
  ARGUS_LOG_CMD="${ZEDX_ARGUS_LOG_CMD:-$JOURNAL -u nvargus-daemon --no-pager _SYSTEMD_INVOCATION_ID=$ARGUS_INVOCATION}"
else
  ARGUS_SCOPE="$ARGUS_WINDOW"
  ARGUS_LOG_CMD="${ZEDX_ARGUS_LOG_CMD:-$JOURNAL -u nvargus-daemon --no-pager --since $ARGUS_WINDOW}"
fi
CLIENT_PATTERN="${ZEDX_CLIENT_PATTERN:-component_container|ZED_Explorer|ZED_Depth_Viewer|ZED_Media_Server}"

# A capture session that outlived its client: the sensor stays allocated and every open() fails.
ARGUS_FAULT_RE='AlreadyAllocated|buffers still pending during EGLStreamProducer'

refcnt="$(cat "$REFCNT_FILE" 2>/dev/null || true)"
argus_log="$(eval "$ARGUS_LOG_CMD" 2>/dev/null || true)"
argus_faults="$(printf '%s\n' "$argus_log" | grep -cE "$ARGUS_FAULT_RE")"
clients="$(pgrep -af "$CLIENT_PATTERN" 2>/dev/null | head -5 || true)"
client_n="$(printf '%s' "$clients" | grep -c . )"

verdict=""; code=0; reason=""
if [ -z "$refcnt" ]; then
  verdict=REBOOT_REQUIRED; code=2
  reason="sl_zedx driver is not loaded ($REFCNT_FILE unreadable)."
elif ! printf '%s' "$refcnt" | grep -qE '^-?[0-9]+$'; then
  verdict=REBOOT_REQUIRED; code=2
  reason="cannot parse sl_zedx refcnt ('$refcnt')."
elif [ "$refcnt" -lt 0 ]; then
  verdict=RECOVERABLE; code=1
  reason="sl_zedx module use-count underflowed (refcnt=$refcnt, i.e. atomic 0). try_module_get() then fails, tegracam never starts the stream, and BOTH cameras report FROZEN. Restoring the lost base reference and resetting the camera MCU fixes it without a reboot (proven 2026-09-14 and 2026-09-21): $(dirname "$0")/zedx_recover.sh --run"
elif [ "$argus_faults" -gt 0 ] && [ "$client_n" -eq 0 ]; then
  verdict=RECOVERABLE; code=1
  reason="nvargus-daemon reports $argus_faults capture-session fault line(s) from $ARGUS_SCOPE while no process holds a camera: a streaming client died without releasing the sensor."
else
  verdict=HEALTHY; code=0
  if [ "$argus_faults" -gt 0 ]; then
    reason="module refcount intact; $argus_faults argus contention line(s) explained by $client_n live camera client(s)."
  else
    reason="module refcount intact and no stale argus session."
  fi
fi

echo "=== ZED X stack health — $(hostname) $(date '+%F %T') ==="
echo "sl_zedx refcnt : ${refcnt:-<driver not loaded>}   (0 = idle; 1 per open camera; NEGATIVE = broken)"
echo "argus faults   : $argus_faults line(s) in $ARGUS_SCOPE"
if [ "$client_n" -gt 0 ]; then
  echo "camera clients : $client_n"; printf '%s\n' "$clients" | cut -c1-110 | sed 's/^/                 /'
else
  echo "camera clients : none"
fi
echo "reason         : $reason"
echo "VERDICT=$verdict"
echo
case "$verdict" in
  HEALTHY)
    echo "next step: nothing to do. If a camera still refuses to open, another process holds it —"
    echo "           check 'camera clients' above before touching any daemon."
    ;;
  RECOVERABLE)
    echo "next step: $(dirname "$0")/zedx_recover.sh --run"
    echo "           It restarts argus, restores the lost module reference, resets the camera MCU"
    echo "           over GMSL, and opens the camera. One command; no reboot."
    echo "           Run it WITHOUT sudo: /etc/sudoers.d/zedx-recovery whitelists the four commands"
    echo "           the script runs, not the script itself, so 'sudo bash ...' only earns a"
    echo "           password prompt that stalls the unattended path."
    ;;
  REBOOT_REQUIRED)
    echo "next step: sudo reboot   — no userspace action can fix this state."
    echo "           Do NOT trust 'systemctl restart zed_x_daemon': it prints 'ZED-X Driver loaded'"
    echo "           even when every rmmod/insmod inside it failed."
    ;;
esac
exit "$code"
