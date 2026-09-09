#!/usr/bin/env bash
# Tests the ZED wiring inside ~/.local/bin/sensors.
#
# Two properties are load-bearing and both were regressions that wedged the camera:
#   - start must preflight BEFORE the tmux session exists, so a wedged stack is
#     repaired rather than launched onto.
#   - stop must wait for the sensors to actually exit. The original fixed 3 s sleep
#     killed the session mid-close, which is what leaked the module reference.
#
# Everything runs against a throwaway session and a marker process; the real
# `sensors` session and the real camera are never touched.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SENSORS="${SENSORS_BIN:-$HOME/.local/bin/sensors}"
QA_SESSION="ulw-qa-sensors"
TMP="$(mktemp -d)"
cleanup() {
  tmux kill-session -t "$QA_SESSION" 2>/dev/null
  pkill -f ulw_qa_marker 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT
pass=0; fail=0
ok() { echo "PASS $1"; pass=$((pass+1)); }
no() { echo "FAIL $1"; fail=$((fail+1)); [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }

[ -x "$SENSORS" ] || { echo "FAIL $SENSORS is missing"; echo "----"; echo "passed=0 failed=1"; exit 1; }

fake_preflight() { # exitcode
  local f="$TMP/preflight.$1"
  printf '#!/usr/bin/env bash\necho "FAKE_PREFLIGHT_RAN"\nexit %s\n' "$1" > "$f"
  chmod +x "$f"; echo "$f"
}

run_check() { # exitcode
  OUT="$(SENSORS_PREFLIGHT_CMD="$(fake_preflight "$1")" "$SENSORS" check 2>&1)"
}

run_check 0
printf '%s' "$OUT" | grep -q FAKE_PREFLIGHT_RAN && printf '%s' "$OUT" | grep -q 'camera stack ready' \
  && ok "check runs the preflight and reports ready" || no "check ready path" "$OUT"

run_check 2
printf '%s' "$OUT" | grep -q 'not safe' \
  && ok "preflight exit 2 is reported as skipped, not as ready" || no "check skip path" "$OUT"

run_check 1
printf '%s' "$OUT" | grep -qi 'reboot' \
  && ok "preflight exit 1 points at reboot" || no "check wedged path" "$OUT"

body="$(awk '/^cmd_start\(\) \{/{s=NR} s && /^\}/{print s","NR; exit}' "$SENSORS")"
from_line="${body%,*}"; to_line="${body#*,}"
pf_line="$(awk -v a="$from_line" -v b="$to_line" 'NR>=a && NR<=b && /run_preflight/ {print NR; exit}' "$SENSORS")"
sess_line="$(awk -v a="$from_line" -v b="$to_line" 'NR>=a && NR<=b && /tmux new-session/ {print NR; exit}' "$SENSORS")"
if [ -n "$pf_line" ] && [ -n "$sess_line" ] && [ "$pf_line" -lt "$sess_line" ]; then
  ok "start preflights before creating the session ($pf_line < $sess_line in cmd_start)"
else
  no "cmd_start must call run_preflight before tmux new-session (body=$body pf=$pf_line session=$sess_line)"
fi

start_marker() { # marker_cmd
  tmux kill-session -t "$QA_SESSION" 2>/dev/null
  tmux new-session -d -s "$QA_SESSION" -n marker
  tmux send-keys -t "$QA_SESSION:marker" "$1" C-m
  for _ in $(seq 1 20); do pgrep -f ulw_qa_marker >/dev/null && return 0; sleep 0.2; done
  return 1
}

if start_marker 'exec -a ulw_qa_marker_clean sleep 60'; then
  OUT="$(SENSORS_SESSION="$QA_SESSION" SENSORS_SHUTDOWN_PATTERN=ulw_qa_marker \
         SENSORS_SHUTDOWN_GRACE=20 "$SENSORS" stop 2>&1)"
  printf '%s' "$OUT" | grep -q 'exited cleanly' \
    && ok "stop waits for the process to exit before killing the session" || no "stop clean-exit path" "$OUT"
else
  no "could not start the clean marker"
fi

if start_marker 'bash -c '\''trap "" INT; while :; do sleep 1; done'\'' ulw_qa_marker_stuck'; then
  OUT="$(SENSORS_SESSION="$QA_SESSION" SENSORS_SHUTDOWN_PATTERN=ulw_qa_marker \
         SENSORS_SHUTDOWN_GRACE=2 "$SENSORS" stop 2>&1)"
  printf '%s' "$OUT" | grep -q 'still running after' \
    && ok "stop warns instead of silently killing a process that will not exit" || no "stop timeout path" "$OUT"
else
  no "could not start the stuck marker"
fi

pkill -f ulw_qa_marker 2>/dev/null
tmux has-session -t "$QA_SESSION" 2>/dev/null \
  && no "throwaway session survived the test" || ok "throwaway session cleaned up"

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
