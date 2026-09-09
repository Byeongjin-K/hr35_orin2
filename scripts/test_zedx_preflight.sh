#!/usr/bin/env bash
# Tests for zedx_preflight.sh -- specifically WHEN it is allowed to recover.
#
# The gate matters more than the recovery: zedx_recover.sh kills camera clients and
# restarts system daemons. Running that automatically from `sensors start` is only
# safe when nothing holds a camera and root is actually obtainable. Each case below
# asserts both the exit code and whether the recovery was invoked at all.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/zedx_preflight.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS $1"; pass=$((pass+1)); }
no() { echo "FAIL $1"; fail=$((fail+1)); [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }

# Fake health check: pops one exit code per call; the last code sticks.
make_health() { # name code...
  local name="$1"; shift
  local f="$TMP/$name.health" codes="$TMP/$name.codes"
  printf '%s\n' "$@" > "$codes"
  cat > "$f" <<EOF
#!/usr/bin/env bash
n="\$(head -1 "$codes")"
rest="\$(tail -n +2 "$codes")"
[ -n "\$rest" ] && printf '%s\n' "\$rest" > "$codes"
echo "VERDICT=FAKE_\$n"
exit "\$n"
EOF
  chmod +x "$f"; echo "$f"
}

make_recover() { # name exitcode
  local f="$TMP/$1.recover"
  cat > "$f" <<EOF
#!/usr/bin/env bash
echo called >> "$TMP/$1.calls"
echo "fake recover ran"
exit $2
EOF
  chmod +x "$f"; echo "$f"
}
calls() { [ -f "$TMP/$1.calls" ] && wc -l < "$TMP/$1.calls" | tr -d ' ' || echo 0; }

run_pf() { # health recover client_pattern root_check
  OUT="$(ZEDX_HEALTH_CMD="$1" ZEDX_RECOVER_CMD="$2" ZEDX_CLIENT_PATTERN="$3" \
         ZEDX_ROOT_CHECK_CMD="$4" bash "$SCRIPT" 2>&1)"
  RC=$?
}

check() { # name want_rc want_calls tag
  local name="$1" want_rc="$2" want_calls="$3" tag="$4"
  local got_calls; got_calls="$(calls "$tag")"
  if [ "$RC" = "$want_rc" ] && [ "$got_calls" = "$want_calls" ]; then
    ok "$name (rc=$RC recover_calls=$got_calls)"
  else
    no "$name: want rc=$want_rc calls=$want_calls, got rc=$RC calls=$got_calls" "$OUT"
  fi
}

NOCLIENT='__zedx_no_such_process__'
LIVECLIENT='test_zedx_preflight'   # matches this very test process: no race, no sleep

[ -f "$SCRIPT" ] || { echo "FAIL zedx_preflight.sh does not exist"; echo "----"; echo "passed=0 failed=1"; exit 1; }

run_pf "$(make_health a 0)" "$(make_recover a 0)" "$NOCLIENT" true
check "healthy stack never touches recovery" 0 0 a

run_pf "$(make_health b 1 0)" "$(make_recover b 0)" "$NOCLIENT" true
check "wedged + no client + root -> recovers" 0 1 b

run_pf "$(make_health c 2)" "$(make_recover c 0)" "$LIVECLIENT" true
check "live camera client blocks automatic recovery" 2 0 c
printf '%s' "$OUT" | grep -q 'SKIP' || no "live-client case must say SKIP" "$OUT"

run_pf "$(make_health d 2)" "$(make_recover d 0)" "$NOCLIENT" false
check "no root on a non-interactive shell -> skip" 2 0 d

run_pf "$(make_health e 2 2)" "$(make_recover e 7)" "$NOCLIENT" true
check "recovery that does not fix it reports failure" 1 1 e
printf '%s' "$OUT" | grep -qi 'reboot' || no "unfixed case must point at reboot" "$OUT"

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
