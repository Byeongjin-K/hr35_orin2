#!/usr/bin/env bash
# Tests for zedx_refcnt.ko.
#
# All mutating tests run against sl_zedxpro (the ZED X Pro sensor driver): it is
# loaded but idle on this machine (no ZED X Pro attached), so its reference count
# can be moved and restored without touching a streaming camera. sl_zedx itself is
# only read.
#
# Needs root. Set SUDO to whatever grants it (default: sudo).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KO="$HERE/zedx_refcnt.ko"
SUDO="${SUDO:-sudo}"
SAFE_DRV="${ZEDX_TEST_DRIVER:-zedxpro}"
SAFE_MOD="${ZEDX_TEST_MODULE:-sl_zedxpro}"
LIVE_MOD="${ZEDX_LIVE_MODULE:-sl_zedx}"
pass=0; fail=0

refcnt() { cat "/sys/module/$1/refcnt" 2>/dev/null || echo MISSING; }
load()   { $SUDO insmod "$KO" "$@" >/dev/null 2>&1; }
unload() { $SUDO rmmod zedx_refcnt >/dev/null 2>&1; }

ok() { echo "PASS $1"; pass=$((pass+1)); }
no() { echo "FAIL $1"; fail=$((fail+1)); }

expect_eq() { # name want got
  if [ "$2" = "$3" ]; then ok "$1 (=$3)"; else no "$1: want $2, got $3"; fi
}

[ -f "$KO" ] || { echo "FAIL module not built: $KO"; echo "----"; echo "passed=0 failed=1"; exit 1; }

# 1. read-only: reports the true atomic refcount, which must be sysfs + 1
base_live="$(refcnt "$LIVE_MOD")"
unload
if load target="$LIVE_MOD" driver=zedx; then
  line="$($SUDO dmesg | grep -a 'zedx_refcnt:' | tail -5 | grep -a 'atomic_refcnt=' | tail -1)"
  atomic="$(printf '%s' "$line" | sed -nE 's/.*atomic_refcnt=(-?[0-9]+).*/\1/p')"
  unload
  expect_eq "read-only reports atomic == sysfs+1" "$((base_live + 1))" "${atomic:-none}"
  expect_eq "read-only leaves $LIVE_MOD untouched" "$base_live" "$(refcnt "$LIVE_MOD")"
else
  no "read-only load on $LIVE_MOD"
  unload
fi

# 2. refuses an unknown driver, changes nothing
before="$(refcnt "$SAFE_MOD")"
if load target="$SAFE_MOD" driver=__no_such_driver__; then no "unknown driver must refuse"; unload
else ok "unknown driver refused"; fi
expect_eq "unknown driver left refcnt alone" "$before" "$(refcnt "$SAFE_MOD")"

# 3. refuses a target/owner name mismatch
if load target=sl_bogus driver="$SAFE_DRV"; then no "name mismatch must refuse"; unload
else ok "name mismatch refused"; fi
expect_eq "name mismatch left refcnt alone" "$before" "$(refcnt "$SAFE_MOD")"

# 4. +1 / -1 is exactly reversible
load target="$SAFE_MOD" driver="$SAFE_DRV" delta=1; unload
up="$(refcnt "$SAFE_MOD")"
expect_eq "delta=+1 raises refcnt" "$((before + 1))" "$up"
load target="$SAFE_MOD" driver="$SAFE_DRV" delta=-1; unload
expect_eq "delta=-1 restores refcnt" "$before" "$(refcnt "$SAFE_MOD")"

# 5. never drops below the load-time base reference (cannot create the damage)
load target="$SAFE_MOD" driver="$SAFE_DRV" delta=-5; unload
expect_eq "delta=-5 refuses to pass the base ref" "$before" "$(refcnt "$SAFE_MOD")"

# 6. repair is a no-op on an undamaged module
load target="$SAFE_MOD" driver="$SAFE_DRV" repair=1; unload
expect_eq "repair leaves a healthy module alone" "$before" "$(refcnt "$SAFE_MOD")"

# 7. THE POINT: break the base ref exactly like the tegracam bug does, then repair it
load target="$SAFE_MOD" driver="$SAFE_DRV" unsafe_break=1; unload
expect_eq "unsafe_break reproduces the wedge signature" "-1" "$(refcnt "$SAFE_MOD")"
load target="$SAFE_MOD" driver="$SAFE_DRV" repair=1; unload
expect_eq "repair restores the base ref" "$before" "$(refcnt "$SAFE_MOD")"

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
