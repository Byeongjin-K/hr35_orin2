#!/usr/bin/env bash
# Tests for zedx_recover.sh's plan: which rungs it picks and, above all, the
# ordering guard. On this kernel panic_on_oops=1, so running rmmod while the
# atomic module refcount is 0 (sysfs -1) can hit BUG_ON in try_release_module_ref
# and panic the machine. repair-refcnt MUST come before reload-drivers, always.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/zedx_recover.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok() { echo "PASS $1"; pass=$((pass+1)); }
no() { echo "FAIL $1"; fail=$((fail+1)); [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }

mk_mod() { mkdir -p "$TMP/$1/sl_zedx"; printf '%s\n' "$2" > "$TMP/$1/sl_zedx/refcnt"; echo "$TMP/$1"; }

plan() { # module_dir client_pattern
  ZEDX_MODULE_DIR="$1" ZEDX_CLIENT_PATTERN="$2" bash "$SCRIPT" --plan 2>&1
}
step_line() { printf '%s' "$1" | grep -n "STEP .*$2" | head -1 | cut -d: -f1; }

NOCLIENT='__zedx_no_such_process__'
LIVECLIENT='test_zedx_recover'

[ -f "$SCRIPT" ] || { echo "FAIL zedx_recover.sh does not exist"; echo "----"; echo "passed=0 failed=1"; exit 1; }

# 1. healthy + idle: plan the cheap rungs, never touch the refcount
out="$(plan "$(mk_mod healthy 0)" "$NOCLIENT")"
printf '%s' "$out" | grep -q 'STEP .*restart-nvargus' && ok "healthy plans restart-nvargus" || no "healthy plans restart-nvargus" "$out"
printf '%s' "$out" | grep -q 'repair-refcnt' && no "healthy must NOT plan repair-refcnt" "$out" || ok "healthy skips repair-refcnt"
printf '%s' "$out" | grep -q 'GUARD' && no "healthy must NOT emit a GUARD line" "$out" || ok "healthy emits no GUARD"

# 2. damaged refcount: repair must be planned, and the guard announced
out="$(plan "$(mk_mod broken -1)" "$NOCLIENT")"
printf '%s' "$out" | grep -q 'STEP .*repair-refcnt' && ok "damaged plans repair-refcnt" || no "damaged plans repair-refcnt" "$out"
printf '%s' "$out" | grep -q 'GUARD .*refcnt' && ok "damaged announces the rmmod guard" || no "damaged announces the rmmod guard" "$out"

# 3. THE SAFETY PROPERTY: repair-refcnt strictly before reload-drivers
r="$(step_line "$out" 'repair-refcnt')"; d="$(step_line "$out" 'reload-drivers')"
if [ -n "$r" ] && [ -n "$d" ] && [ "$r" -lt "$d" ]; then
  ok "repair-refcnt is ordered before reload-drivers ($r < $d)"
else
  no "repair-refcnt must precede reload-drivers (repair=$r reload=$d)" "$out"
fi

# 4. a live client must be retired before anything else
out="$(plan "$(mk_mod healthy2 0)" "$LIVECLIENT")"
s="$(step_line "$out" 'stop-clients')"
if [ -n "$s" ] && [ "$s" -eq "$(printf '%s' "$out" | grep -n 'STEP ' | head -1 | cut -d: -f1)" ]; then
  ok "live client makes stop-clients the first step"
else
  no "stop-clients must be the first step when a client is alive" "$out"
fi

# 5. plan mode must not execute anything
before="$(cat /sys/module/sl_zedx/refcnt 2>/dev/null)"
plan "$(mk_mod broken2 -1)" "$NOCLIENT" >/dev/null 2>&1
after="$(cat /sys/module/sl_zedx/refcnt 2>/dev/null)"
[ "$before" = "$after" ] && ok "plan mode changed nothing on the real system (=$after)" \
  || no "plan mode must not touch the real system ($before -> $after)"

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
