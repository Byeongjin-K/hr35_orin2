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

# 2026-09-21 REPLACES the old "repair -> open -> reload" assertion, which this session
# disproved. That probe is destructive: opening a wedged camera always fails, the failing
# teardown hits the tegracam double module_put bug, and the reference repaired one second
# earlier is gone. Measured: repair drove refcnt to 0, the probe failed at 17:00:08, refcnt
# was -1 by 17:00:09, and the reload was then refused ("sl_max9295 is in use by: sl_zedx",
# "sl_zedx.ko: File exists") so sl_zedx never unloaded and the ladder cried "reboot required"
# for a camera that came back without one. The gap between repairing the reference and
# spending it must stay probe-free, and the cheap non-kernel rung goes first.
ord_repair="$(grep -n 'say "3 repair-refcnt"' "$SCRIPT" | head -1 | cut -d: -f1)"
ord_mcu="$(grep -n 'say "4 reboot-mcu"' "$SCRIPT" | head -1 | cut -d: -f1)"
ord_reload="$(grep -n 'say "5 reload-drivers"' "$SCRIPT" | head -1 | cut -d: -f1)"
if [ -n "$ord_repair" ] && [ -n "$ord_mcu" ] && [ -n "$ord_reload" ] \
   && [ "$ord_repair" -lt "$ord_mcu" ] && [ "$ord_mcu" -lt "$ord_reload" ]; then
  ok "ordering is repair-refcnt -> reboot-mcu -> reload-drivers ($ord_repair < $ord_mcu < $ord_reload)"
else
  no "ordering must be repair -> reboot-mcu -> reload (repair=$ord_repair mcu=$ord_mcu reload=$ord_reload)"
fi

if [ -n "$ord_repair" ] && [ -n "$ord_mcu" ]; then
  gap="$(sed -n "${ord_repair},$((ord_mcu - 1))p" "$SCRIPT" | grep -n 'probe_ok' || true)"
  [ -z "$gap" ] && ok "no probe fires between repairing the reference and using it" \
    || no "a probe there burns the reference that the next rung needs" "$gap"
else
  no "cannot locate the repair/reboot-mcu rungs to check the probe-free gap"
fi

# The guard in front of reload-drivers used to test $refcnt, a value captured BEFORE a probe
# that had since driven it back to -1, so it waved through an rmmod at atomic 0. It has to
# consult the module afresh, in the quiet window, before the daemon is started again.
if [ -n "$ord_reload" ]; then
  tail_from_reload="$(sed -n "${ord_reload},\$p" "$SCRIPT")"
  g="$(printf '%s' "$tail_from_reload" | grep -n 'repair_refcnt' | head -1 | cut -d: -f1)"
  r="$(printf '%s' "$tail_from_reload" | grep -n 'systemctl start zed_x_daemon' | head -1 | cut -d: -f1)"
  if [ -n "$g" ] && [ -n "$r" ] && [ "$g" -lt "$r" ]; then
    ok "reload-drivers repairs the refcount before it starts the daemon"
  else
    no "the rmmod guard must re-read sysfs before the daemon is started (guard=$g start=$r)"
  fi

  s="$(printf '%s' "$tail_from_reload" | grep -n 'systemctl stop zed_x_daemon' | head -1 | cut -d: -f1)"
  if [ -n "$s" ] && [ -n "$g" ] && [ "$s" -lt "$g" ]; then
    ok "the daemon is stopped before the refcount is repaired ($s < $g)"
  else
    no "repairing before the daemon stops is pointless; its teardown burns the reference (stop=$s repair=$g)"
  fi
else
  no "cannot locate the reload-drivers rung to check its guard"
fi

# 2026-09-22: `systemctl restart zed_x_daemon` can NEVER reload the driver while the daemon
# holds a GMSL port. systemd stopping it runs the port teardown, that teardown hits the
# tegracam double module_put bug, and the reference dies in the same instant -- kernel logged
# "Error turning off streaming" x2 at 09:55:38, the exact second of "Stopping ZED-X Daemon
# service", and the fresh daemon's rmmod was refused with "sl_max9295 is in use by: sl_zedx".
# The repair only lands if it happens between stop and start.
if grep -q 'systemctl restart zed_x_daemon' "$SCRIPT"; then
  no "reload-drivers must not use 'systemctl restart zed_x_daemon'" \
     "$(grep -n 'systemctl restart zed_x_daemon' "$SCRIPT")"
else
  ok "the ladder never restarts zed_x_daemon in one step"
fi

# Camera.reboot(sn, ...) is the USB entry point: on this GMSL rig it answered
# "INVALID FUNCTION CALL" and did nothing (2026-09-21). Only reboot_from_input(GMSL) reaches
# the ZED X MCU, and that call is what ended the wedge.
if grep -q 'reboot_from_input(sl.INPUT_TYPE.GMSL)' "$SCRIPT" && ! grep -q 'sl\.Camera\.reboot(' "$SCRIPT"; then
  ok "the MCU reset uses the GMSL entry point, not the USB one"
else
  no "the reset must call reboot_from_input(GMSL) and never Camera.reboot(sn)" "$(grep -n 'reboot' "$SCRIPT" | head)"
fi

# repair_refcnt has to answer from sysfs every time it is called.
rc=0
ZEDX_SOURCE_ONLY=1 ZEDX_MODULE_DIR="$(mk_mod repair_ok 0)" \
  bash -c "source '$SCRIPT'; repair_refcnt" >/dev/null 2>&1 || rc=$?
[ "$rc" = 0 ] && ok "repair_refcnt is a no-op on a healthy refcount" \
  || no "repair_refcnt must pass a refcount that is already >= 0 (rc=$rc)"

cat > "$TMP/fakesudo" <<'EOF'
#!/usr/bin/env bash
echo "$@" >> "$FAKE_SUDO_LOG"
exit 0
EOF
chmod +x "$TMP/fakesudo"
touch "$TMP/zedx_refcnt.ko"   # so the helper never shells out to `make`
: > "$TMP/sudo_log"
ZEDX_SOURCE_ONLY=1 ZEDX_MODULE_DIR="$(mk_mod repair_broken -1)" SUDO="$TMP/fakesudo" \
  ZEDX_REFCNT_TOOL="$TMP" FAKE_SUDO_LOG="$TMP/sudo_log" \
  bash -c "source '$SCRIPT'; repair_refcnt" >/dev/null 2>&1 || true
if grep -q 'insmod .*repair=1' "$TMP/sudo_log"; then
  ok "a negative refcount drives the repair module with repair=1"
else
  no "repair_refcnt must insmod the repair module when the refcount is negative" "$(cat "$TMP/sudo_log")"
fi

# The reset is only worth believing when the SDK says SUCCESS; anything else has to be
# reported, not swallowed, or the ladder blames the camera for an SDK refusal.
printf '#!/usr/bin/env bash\necho "MCU_REBOOT SUCCESS"\n' > "$TMP/mcu_ok"
printf '#!/usr/bin/env bash\necho "MCU_REBOOT INVALID FUNCTION CALL"\n' > "$TMP/mcu_bad"
chmod +x "$TMP/mcu_ok" "$TMP/mcu_bad"
rc=0
ZEDX_SOURCE_ONLY=1 ZEDX_MCU_REBOOT_CMD="$TMP/mcu_ok" \
  bash -c "source '$SCRIPT'; mcu_reboot" >/dev/null 2>&1 || rc=$?
[ "$rc" = 0 ] && ok "mcu_reboot accepts a SUCCESS answer" || no "mcu_reboot must succeed on SUCCESS (rc=$rc)"
# Ask the shell to report mcu_reboot's OWN status: `mcu_reboot; echo ...` would hand back the
# echo's status and the assertion would pass no matter what the function did.
out_mcu="$(ZEDX_SOURCE_ONLY=1 ZEDX_MCU_REBOOT_CMD="$TMP/mcu_bad" \
  bash -c "source '$SCRIPT'; if mcu_reboot; then echo RC=0; else echo RC=1; fi; echo \"LAST=\$MCU_LAST\"" 2>&1)"
if printf '%s' "$out_mcu" | grep -q 'RC=1' \
   && printf '%s' "$out_mcu" | grep -q 'LAST=.*INVALID FUNCTION CALL'; then
  ok "a refused reset fails and keeps the SDK's answer"
else
  no "mcu_reboot must fail and record the refusal" "$out_mcu"
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

# ---------------------------------------------------------------------------
# 2026-09-18: the ladder printed "FAILED: every rung exhausted; reboot required" while the
# recovery had actually worked. STEP 4 waited with a RELATIVE window
# (journalctl --since '-2min'), and that window still contained the PREVIOUS reload's
# "ZED-X Driver loaded" (15:54:39, triggered by step 2 restarting argus). The loop broke
# instantly at 15:55:49, probe_ok then ran while the driver was unloaded -- the daemon logged
# no OPENING at all -- and the script exited 7. The real load finished 11 s later at 15:56:00
# and the camera opened on the first try at 15:59:42, no reboot needed.
# So the wait must be scoped to THIS restart, and it must also wait for the daemon to finish
# coming up: right after "Driver loaded" it restarts NVArgus, and a probe fired into that
# gap cannot reach the camera.
mk_fake_journal() { # $1 path, $2 poll that loads the driver, $3 poll that finishes bring-up
  cat > "$1" <<EOF
#!/usr/bin/env bash
scoped=0
for a in "\$@"; do case "\$a" in _SYSTEMD_INVOCATION_ID=*) scoped=1 ;; esac; done
n=\$(( \$(cat "\$FAKE_CALLS" 2>/dev/null || echo 0) + 1 )); echo "\$n" > "\$FAKE_CALLS"
echo 'ZED-X Daemon  ** Start ZED-X Daemon'
echo 'ZED-X Daemon ZED-X Driver removed'
if [ "\$scoped" = 1 ]; then
  [ "\$n" -ge $2 ] && echo 'ZED-X Daemon ZED-X Driver loaded'
  [ "\$n" -ge $3 ] && echo 'ZED-X Daemon  ** Created Pub Endpoint "tcp://127.0.0.1:20027"'
else
  echo 'ZED-X Daemon ZED-X Driver loaded'
fi
exit 0
EOF
  chmod +x "$1"
}

wait_probe() { # $1 fake journal, $2 calls file, $3 poll budget -> prints "rc polls"
  local rc=0
  : > "$2"
  ZEDX_SOURCE_ONLY=1 ZEDX_JOURNAL_CMD="$1" ZEDX_POLL_SLEEP=0 FAKE_CALLS="$2" \
    bash -c "source '$SCRIPT'; wait_for_driver_reload THISINV $3" >/dev/null 2>&1 || rc=$?
  echo "$rc $(cat "$2" 2>/dev/null || echo 0)"
}

fj="$TMP/fakejournal"; mk_fake_journal "$fj" 3 5
read -r rc polls <<<"$(wait_probe "$fj" "$TMP/calls" 20)"
if [ "$rc" = 0 ] && [ "$polls" -ge 5 ]; then
  ok "the reload wait is scoped to this restart and waits for bring-up (polls=$polls)"
else
  no "the wait must ignore the previous restart's 'Driver loaded' and wait for this one (rc=$rc polls=$polls)"
fi

# A restart that never completes must be reported, not silently treated as done: that is the
# difference between "recovery failed" and "we probed too early".
fj2="$TMP/fakejournal_stuck"; mk_fake_journal "$fj2" 99 99
read -r rc2 polls2 <<<"$(wait_probe "$fj2" "$TMP/calls2" 3)"
if [ "$rc2" != 0 ] && [ "$polls2" -ge 3 ]; then
  ok "a reload that never finishes exhausts the budget and fails (rc=$rc2 polls=$polls2)"
else
  no "a stale 'Driver loaded' must not satisfy the wait (rc=$rc2 polls=$polls2)"
fi

# 2026-09-18: STEP 1 printed nothing and the ladder moved on, but component_container[886377]
# was still alive -- it reconnected to argus at 15:54:55 and again at 15:55:35, so every later
# rung ran against a live client. A supervisor (ros2 launch) respawns the container, which is
# why SIGKILL on the container alone does not settle it. Surviving the kill has to abort the
# ladder, not pass silently.
mk_fake_proc() { # $1 dir, $2 pgrep call after which the client is gone (0 = it never dies)
  mkdir -p "$1"
  cat > "$1/pgrep" <<EOF
#!/usr/bin/env bash
n=\$(( \$(cat "\$FAKE_PGREP_CALLS" 2>/dev/null || echo 0) + 1 )); echo "\$n" > "\$FAKE_PGREP_CALLS"
gone=$2
if [ "\$gone" != 0 ] && [ "\$n" -ge "\$gone" ]; then exit 1; fi
[ "\${1:-}" = "-af" ] && echo "12345 component_container_isolated --ros-args"
exit 0
EOF
  cat > "$1/pkill" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$1/pgrep" "$1/pkill"
}

run_stop_clients() { # $1 fake dir, $2 calls file -> prints rc
  local rc=0
  : > "$2"
  ZEDX_SOURCE_ONLY=1 ZEDX_PGREP_CMD="$1/pgrep" ZEDX_PKILL_CMD="$1/pkill" ZEDX_KILL_SLEEP=0 \
    FAKE_PGREP_CALLS="$2" \
    bash -c "source '$SCRIPT'; stop_clients 'zedx-fake-client'" >/dev/null 2>&1 || rc=$?
  echo "$rc"
}

d1="$TMP/proc_survives"; mk_fake_proc "$d1" 0
rc="$(run_stop_clients "$d1" "$TMP/pgrep_calls1")"
if [ "$rc" != 0 ]; then
  ok "a client that survives SIGKILL is reported, not ignored (rc=$rc)"
else
  no "stop_clients must fail when a client is still alive after SIGKILL (rc=$rc)"
fi

d2="$TMP/proc_dies"; mk_fake_proc "$d2" 2
rc="$(run_stop_clients "$d2" "$TMP/pgrep_calls2")"
if [ "$rc" = 0 ]; then
  ok "a client that exits clears stop-clients (rc=$rc)"
else
  no "stop_clients must succeed once the client is gone (rc=$rc)"
fi

# The abort must be wired into the ladder, not just available as a function.
if grep -q 'stop_clients "$CLIENT_PATTERN"' "$SCRIPT" \
   && grep -A4 'stop_clients "$CLIENT_PATTERN"' "$SCRIPT" | grep -q 'ABORT'; then
  ok "the ladder aborts when stop-clients cannot clear the camera"
else
  no "step 1 must abort the ladder when a client survives" "$(grep -A4 'stop_clients "\$CLIENT_PATTERN"' "$SCRIPT")"
fi

# probe_ok threw its stderr away (2>/dev/null), so when the ladder ended in
# "FAILED: reboot required" there was no way to tell "the camera is dead" from "we probed
# 10 s too early" -- exactly the ambiguity that cost the 2026-09-18 session a reboot scare.
cat > "$TMP/fakeprobe_fail" <<'EOF'
#!/usr/bin/env bash
echo "OPEN ERROR_CODE.CAMERA_NOT_DETECTED"
exit 0
EOF
chmod +x "$TMP/fakeprobe_fail"

probe_out="$(ZEDX_SOURCE_ONLY=1 ZEDX_PROBE_CMD="$TMP/fakeprobe_fail" \
  bash -c "source '$SCRIPT'; probe_ok; echo \"LAST=\${PROBE_LAST:-<unset>}\"" 2>&1)"
if printf '%s' "$probe_out" | grep -q 'LAST=.*CAMERA_NOT_DETECTED'; then
  ok "a failed probe keeps its output for the report"
else
  no "probe_ok must record why the open failed" "$probe_out"
fi

if grep -q 'PROBE_LAST' "$SCRIPT" && grep -B4 'FAILED: every rung exhausted' "$SCRIPT" | grep -q 'PROBE_LAST'; then
  ok "the final failure prints the last probe output"
else
  no "the 'reboot required' message must show the last probe output" \
     "$(grep -B4 'FAILED: every rung exhausted' "$SCRIPT")"
fi

# 2026-09-22: a boot without host1x-fence.ko looks perfect to every other check -- refcount 0,
# zero module_put underflows, all four sensors probed, GMSL link up -- and yet a bare pyzed open
# dumps core inside DrmCreateEventPollFd, because /dev/host1x-fence does not exist. The ladder
# has to notice and load it, otherwise running it by hand can never help.
loaded_modules="$TMP/modules_loaded"
printf 'host1x_fence 16384 0 - Live 0x0\nsl_zedx 28672 0 - Live 0x0\n' > "$loaded_modules"
: > "$TMP/modules_missing"

out="$(ZEDX_MODULE_DIR="$(mk_mod fence_ok 0)" ZEDX_CLIENT_PATTERN="$NOCLIENT" \
       ZEDX_MODULES_FILE="$TMP/modules_missing" bash "$SCRIPT" --plan 2>&1)"
printf '%s' "$out" | grep -q 'STEP 1 load-fence' \
  && ok "a missing host1x_fence makes load-fence the very first step" \
  || no "load-fence must be planned first when the module is missing" "$out"

out="$(ZEDX_MODULE_DIR="$(mk_mod fence_ok2 0)" ZEDX_CLIENT_PATTERN="$NOCLIENT" \
       ZEDX_MODULES_FILE="$loaded_modules" bash "$SCRIPT" --plan 2>&1)"
printf '%s' "$out" | grep -q 'load-fence' \
  && no "load-fence must not be planned when the module is already loaded" "$out" \
  || ok "a loaded host1x_fence plans no load-fence rung"

# The node lingers in devtmpfs after the module is unloaded, so testing for it would pass while
# every open still crashed.
if grep -q 'MODULES_FILE' "$SCRIPT" && ! grep -qE 'test -[ec] .*/dev/host1x-fence|\[ -[ec] .*/dev/host1x-fence' "$SCRIPT"; then
  ok "the fence check reads /proc/modules, not the lingering device node"
else
  no "the fence check must not rely on /dev/host1x-fence existing" "$(grep -n 'host1x-fence' "$SCRIPT")"
fi

# 2026-09-22 13:17: the container had died, `ros2 launch ... zedx_cabin.launch.py` (pid 10955)
# was still alive, and CLIENT_PATTERN did not match it -- so client_n was 0, rung 1 was skipped,
# and every rung below fought a launcher that kept coming back. That is the "manual recovery
# almost always fails" report. The Ouster bringup must stay out of the pattern.
pat="$(grep -m1 '^CLIENT_PATTERN=' "$SCRIPT" | sed 's/^CLIENT_PATTERN="\${ZEDX_CLIENT_PATTERN:-//; s/}"$//')"
zed_launch='/usr/bin/python3 /opt/ros/humble/bin/ros2 launch hr35_bringup zedx_cabin.launch.py'
ouster_launch='/usr/bin/python3 /opt/ros/humble/bin/ros2 launch hr35_bringup boom_only_driver.launch.py'
if printf '%s' "$zed_launch" | grep -qE "$pat"; then
  ok "the client pattern matches the ZED launch supervisor"
else
  no "the ladder must see 'ros2 launch ... zedx_cabin.launch.py' as a client" "pattern=$pat"
fi
if printf '%s' "$ouster_launch" | grep -qE "$pat"; then
  no "the client pattern must NOT match the Ouster lidar bringup" "pattern=$pat"
else
  ok "the client pattern leaves the Ouster lidar bringup alone"
fi

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
