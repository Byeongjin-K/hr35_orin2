#!/usr/bin/env bash
# zedx_preflight.sh - check the ZED X capture stack before a launch, and repair it
# when doing so is safe. Called by `sensors start`.
#
# Exit codes are a contract; ~/.local/bin/sensors branches on them:
#   0  ready    already healthy, or the recovery fixed it
#   1  wedged   the recovery ran and did not fix it -> reboot
#   2  skipped  repair was needed but running it would not have been safe
#
# zedx_recover.sh kills camera clients and restarts system daemons, so it runs from
# here ONLY when nothing holds a camera. If something does, this prints what to stop
# and exits 2; `sensors restart` stops the clients first, so the retry can act.
#
# Background: a ZED node killed mid-close leaves the camera FROZEN, the ZED-X daemon
# then restarts nvargus on a still-streaming sensor, and tegracam's failing stop path
# leaks a module_put() that drives /sys/module/sl_zedx/refcnt negative -- after which
# every launch fails and the vendor's own driver reload silently no-ops.
# See docs/zedx_camera_recovery.md.
#
# Seams: ZEDX_HEALTH_CMD ZEDX_RECOVER_CMD ZEDX_CLIENT_PATTERN ZEDX_ROOT_CHECK_CMD SUDO
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUDO="${SUDO:-sudo}"
HEALTH_CMD="${ZEDX_HEALTH_CMD:-$HERE/zedx_health.sh}"
RECOVER_CMD="${ZEDX_RECOVER_CMD:-$HERE/zedx_recover.sh}"
CLIENT_PATTERN="${ZEDX_CLIENT_PATTERN:-component_container|ZED_Explorer|ZED_Depth_Viewer|ZED_Media_Server}"
ROOT_CHECK_CMD="${ZEDX_ROOT_CHECK_CMD:-$SUDO -n true}"

say() { printf '[zedx-preflight] %s\n' "$*"; }
verdict_of() { printf '%s' "$1" | grep -o 'VERDICT=[A-Z_]*' | head -1; }

health_out="$("$HEALTH_CMD" 2>&1)"; health_rc=$?
verdict="$(verdict_of "$health_out")"

if [ "$health_rc" -eq 0 ]; then
  say "stack is ready (${verdict:-VERDICT=?})"
  exit 0
fi

say "stack needs attention (${verdict:-rc=$health_rc}):"
printf '%s\n' "$health_out" | sed 's/^/    /'

clients="$(pgrep -af "$CLIENT_PATTERN" 2>/dev/null | head -3 || true)"
if [ -n "$clients" ]; then
  say "SKIP recovery: a camera client is still running and recovery would kill it."
  printf '%s\n' "$clients" | cut -c1-100 | sed 's/^/    /'
  say "stop it first (sensors stop), then this runs on its own -- or: sudo $RECOVER_CMD"
  exit 2
fi

if ! eval "$ROOT_CHECK_CMD" >/dev/null 2>&1 && [ ! -t 0 ]; then
  say "SKIP recovery: it needs root, sudo wants a password, and this shell has no tty."
  say "run it yourself: sudo $RECOVER_CMD"
  exit 2
fi

say "no camera client is running -- recovering now: $RECOVER_CMD"
"$RECOVER_CMD" 2>&1 | sed 's/^/    /'

health_out="$("$HEALTH_CMD" 2>&1)"; health_rc=$?
verdict="$(verdict_of "$health_out")"
if [ "$health_rc" -eq 0 ]; then
  say "recovered (${verdict:-ok})"
  exit 0
fi

say "STILL WEDGED after recovery (${verdict:-rc=$health_rc})."
say "'sudo reboot' is the remaining option. Evidence: journalctl -k | grep module.c:1095"
exit 1
