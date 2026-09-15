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

# rebind-sensors is not a rung any more. On 2026-09-14 it unbound the sensor out from
# under a live Argus thread, the re-bind failed ("ar0234 initialization failed"), and the
# next fput dereferenced the dead subdev: Oops in tegra_channel_set_power -> panic_on_oops
# -> reboot. Evidence: ~/data/zedx_incidents/20260914-panic/
out="$(plan "$(mk_mod norebind -1)" "$NOCLIENT")"
if printf '%s' "$out" | grep -q 'rebind-sensors'; then
  no "the ladder must not plan rebind-sensors" "$out"
else
  ok "rebind-sensors is gone from the ladder"
fi

# --safe is what the tmux launcher runs unattended. Restoring the lost module reference is
# allowed there: one atomic increment, no BUG_ON path, and it is what actually revived the
# camera on 2026-09-14. Unloading modules is not, so no reload rung may be planned.
safe="$(ZEDX_MODULE_DIR="$(mk_mod safemode -1)" ZEDX_CLIENT_PATTERN="$NOCLIENT" \
        bash "$SCRIPT" --safe --plan 2>&1)"
if printf '%s' "$safe" | grep -q 'restart-nvargus' \
   && printf '%s' "$safe" | grep -q 'repair-refcnt' \
   && ! printf '%s' "$safe" | grep -qE 'STEP [0-9]+ reload-drivers'; then
  ok "--safe plans restart-nvargus and repair-refcnt, but never unloads modules"
else
  no "--safe must repair the reference and stop before unloading modules" "$safe"
fi

# 2026-09-14: `--safe --plan` executed the real ladder because only $1 was inspected.
# It SIGKILLed a streaming node and wedged the stack. Nothing runs without --run now.
for args in "" "--safe" "--plan" "--safe --plan" "--plan --safe"; do
  o="$(ZEDX_MODULE_DIR="$(mk_mod dryrun 0)" ZEDX_CLIENT_PATTERN="$NOCLIENT" bash "$SCRIPT" $args 2>&1)"
  if printf '%s' "$o" | grep -q 'PLAN ONLY'; then
    ok "'${args:-<no args>}' is a dry run"
  else
    no "'${args:-<no args>}' must not execute anything" "$o"
  fi
done

# nvargus-daemon holds /dev/video* itself, so the "nothing holds a camera" guard only
# means anything AFTER restart-nvargus has had its chance to release them. Checking earlier
# made the ladder abort forever (2026-09-14).
nv="$(grep -n 'RECOVERED after restart-nvargus' "$SCRIPT" | head -1 | cut -d: -f1)"
fd="$(grep -n 'camera fds held' "$SCRIPT" | head -1 | cut -d: -f1)"
if [ -n "$nv" ] && [ -n "$fd" ] && [ "$fd" -gt "$nv" ]; then
  ok "the /dev/video fd guard sits after restart-nvargus ($fd > $nv)"
else
  no "the fd guard must come after restart-nvargus (nvargus=$nv guard=$fd)"
fi

# 2026-09-14: restart-nvargus + repair-refcnt + open is what actually revived the camera
# (refcnt -1 == atomic 0 makes try_module_get fail, so tegracam never starts the stream and
# the camera reports FROZEN). reload-drivers is NOT needed and its daemon bring-up burns the
# repaired reference before anyone can use it, which is why the 12:21 attempt failed.
ord_repair="$(grep -n 'say "3 repair-refcnt"' "$SCRIPT" | head -1 | cut -d: -f1)"
ord_probe="$(grep -n 'RECOVERED after repair-refcnt' "$SCRIPT" | head -1 | cut -d: -f1)"
ord_reload="$(grep -n 'say "4 reload-drivers"' "$SCRIPT" | head -1 | cut -d: -f1)"
if [ -n "$ord_repair" ] && [ -n "$ord_probe" ] && [ -n "$ord_reload" ] \
   && [ "$ord_repair" -lt "$ord_probe" ] && [ "$ord_probe" -lt "$ord_reload" ]; then
  ok "the camera is tried right after repair-refcnt, before reload-drivers"
else
  no "repair -> open -> reload ordering broken (repair=$ord_repair probe=$ord_probe reload=$ord_reload)"
fi

safe2="$(ZEDX_MODULE_DIR="$(mk_mod safe_repair -1)" ZEDX_CLIENT_PATTERN="$NOCLIENT" \
         bash "$SCRIPT" --safe --plan 2>&1)"
if printf '%s' "$safe2" | grep -q 'repair-refcnt' \
   && ! printf '%s' "$safe2" | grep -q 'reload-drivers'; then
  ok "--safe repairs the refcount but never unloads modules"
else
  no "--safe must include repair-refcnt and exclude reload-drivers" "$safe2"
fi

# The NOPASSWD rule in /etc/sudoers.d/zedx-recovery matches the insmod command as a literal
# string, so a path containing ".." would silently fall back to a password prompt and hang the
# unattended path in `sensors start`.
cmd="$(ZEDX_MODULE_DIR="$(mk_mod canon -1)" ZEDX_CLIENT_PATTERN="$NOCLIENT" bash "$SCRIPT" --plan 2>&1 \
       | grep '^CMD ' | head -1)"
if [ -n "$cmd" ] && ! printf '%s' "$cmd" | grep -q '\.\.'; then
  ok "the planned repair command is a canonical path"
else
  no "the repair command must be a canonical path (no ..)" "${cmd:-<no CMD line>}"
fi

# /etc/sudoers.d/zedx-recovery whitelists only the four mutating commands. Routing a read-only
# command through sudo would sit on a password prompt and hang `sensors start` forever.
if grep -nE '\$SUDO +(systemctl is-active|journalctl)' "$SCRIPT" >/dev/null; then
  no "read-only commands must not go through sudo" "$(grep -nE '\$SUDO +(systemctl is-active|journalctl)' "$SCRIPT")"
else
  ok "no read-only command is routed through sudo"
fi

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
