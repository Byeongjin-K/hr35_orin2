#!/usr/bin/env bash
# Fixture-driven tests for zedx_health.sh verdict logic.
# Module state comes from $ZEDX_MODULE_DIR, the argus log from $ZEDX_ARGUS_LOG_CMD and the
# camera-client pattern from $ZEDX_CLIENT_PATTERN, so every branch runs without touching the
# real stack — while the client branch still goes through the script's real pgrep call.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/zedx_health.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

# A pattern that matches this very test process (alive for the whole run, so no race, no sleep).
LIVE_CLIENT_PATTERN='test_zedx_health'
# A pattern no process can match.
NO_CLIENT_PATTERN='__zedx_health_no_such_process__'

mk_mod() { # name refcnt|none -> prints dir
  mkdir -p "$TMP/$1/sl_zedx"
  [ "$2" = "none" ] || printf '%s\n' "$2" > "$TMP/$1/sl_zedx/refcnt"
  echo "$TMP/$1"
}

# Every case below pins the module list too. Without it the suite would read the real
# /proc/modules and flip verdicts depending on whether this boot happened to autoload
# host1x-fence.ko -- the very nondeterminism these tests exist to pin down.
MODULES_LOADED="$TMP/modules_loaded"
printf 'host1x_fence 16384 0 - Live 0x0\nsl_zedx 28672 0 - Live 0x0\n' > "$MODULES_LOADED"
MODULES_NO_FENCE="$TMP/modules_no_fence"
printf 'sl_zedx 28672 0 - Live 0x0\n' > "$MODULES_NO_FENCE"

run_case() { # name want_code want_verdict module_dir argus_log client_pattern [modules_file]
  local name="$1" want_code="$2" want_verdict="$3" moddir="$4" arguslog="$5" pattern="$6" out code
  local modules="${7:-$MODULES_LOADED}"
  out="$(ZEDX_MODULE_DIR="$moddir" ZEDX_ARGUS_LOG_CMD="cat $arguslog" ZEDX_CLIENT_PATTERN="$pattern" \
         ZEDX_MODULES_FILE="$modules" bash "$SCRIPT" 2>&1)"
  code=$?
  if [ "$code" = "$want_code" ] && printf '%s' "$out" | grep -q "VERDICT=$want_verdict"; then
    echo "PASS $name (exit=$code VERDICT=$want_verdict)"; pass=$((pass+1))
  else
    echo "FAIL $name: want exit=$want_code VERDICT=$want_verdict, got exit=$code"
    printf '%s\n' "$out" | sed 's/^/    /'
    fail=$((fail+1))
  fi
}

clean_log="$TMP/clean.log"
cat > "$clean_log" <<'EOF'
Sep 08 10:53:19 exca-orin-2 nvargus-daemon[2574]: === NVIDIA Libargus Camera Service (0.99.33)=== Listening for connections...
Sep 08 10:53:20 exca-orin-2 nvargus-daemon[2574]: ---- imager: Found override file [/var/nvidia/nvcam/settings/zedx_imx678.isp]. ----
EOF

stale_log="$TMP/stale.log"
cat > "$stale_log" <<'EOF'
Sep 08 10:12:30 exca-orin-2 nvargus-daemon[2576]: SCF: Error InvalidState: 5 buffers still pending during EGLStreamProducer destruction (in src/services/gl/EGLStreamProducer.cpp, function freeBuffers(), line 300)
Sep 08 10:20:38 exca-orin-2 nvargus-daemon[2576]: (Argus) Error AlreadyAllocated: Device 0 (of 1) is in use (in src/api/CameraProviderImpl.cpp, function createCaptureSessionInternal(), line 286)
EOF

run_case "healthy stack"                  0 HEALTHY         "$(mk_mod healthy 2)"   "$clean_log" "$NO_CLIENT_PATTERN"
run_case "refcnt underflow"               1 RECOVERABLE     "$(mk_mod broken -1)"   "$clean_log" "$NO_CLIENT_PATTERN"
run_case "driver not loaded"              2 REBOOT_REQUIRED "$(mk_mod noload none)" "$clean_log" "$NO_CLIENT_PATTERN"
run_case "stale argus, no client"         1 RECOVERABLE     "$(mk_mod orphan 0)"    "$stale_log" "$NO_CLIENT_PATTERN"
run_case "underflow outranks argus"       1 RECOVERABLE     "$(mk_mod both -1)"     "$stale_log" "$NO_CLIENT_PATTERN"
# Regression: nvargus logs the very same lines during ordinary contention while a node legitimately
# holds the camera. A live client means the sensor is NOT orphaned. Goes through the real pgrep path.
run_case "faults but client holds camera" 0 HEALTHY         "$(mk_mod busy 3)"      "$stale_log" "$LIVE_CLIENT_PATTERN"

# 2026-09-22: this script reported HEALTHY on a boot where host1x-fence.ko had not autoloaded.
# The refcount was 0, argus was quiet, all four sensors had probed and the GMSL link was up --
# and every ZED SDK open still dumped core inside DrmCreateEventPollFd, because
# /dev/host1x-fence did not exist. A verdict of HEALTHY sent the whole session chasing the GMSL
# stack. The missing module has to outrank everything else, because nothing else can open the
# camera while it is absent.
run_case "missing host1x_fence"           1 RECOVERABLE     "$(mk_mod fence_missing 0)"  "$clean_log" "$NO_CLIENT_PATTERN" "$MODULES_NO_FENCE"
run_case "missing fence outranks healthy" 1 RECOVERABLE     "$(mk_mod fence_busy 2)"     "$clean_log" "$NO_CLIENT_PATTERN" "$MODULES_NO_FENCE"

out="$(ZEDX_MODULE_DIR="$(mk_mod fence_reason 0)" ZEDX_ARGUS_LOG_CMD="cat $clean_log" \
       ZEDX_CLIENT_PATTERN="$NO_CLIENT_PATTERN" ZEDX_MODULES_FILE="$MODULES_NO_FENCE" \
       bash "$SCRIPT" 2>&1)" || true
if printf '%s' "$out" | grep -q 'host1x_fence : MISSING' \
   && printf '%s' "$out" | grep -q 'modprobe host1x_fence'; then
  ok_fence=1
else
  ok_fence=0
fi
if [ "$ok_fence" = 1 ]; then
  echo "PASS the missing-fence report names the module and the one-line fix"; pass=$((pass+1))
else
  echo "FAIL the report must show 'host1x_fence : MISSING' and the modprobe fix"
  printf '%s\n' "$out" | sed 's/^/    /'
  fail=$((fail+1))
fi

# 2026-09-18: recovery had just restarted argus and the camera was fine, yet this script
# printed "argus faults: 2 ... VERDICT=RECOVERABLE". Those two lines were the 15:55:18
# EGLStreamProducer fault the recovery ITSELF had produced, still inside the -15min window.
# A time window cannot separate "the stack is wedged" from "we just restarted argus", so the
# default log command has to be scoped to the argus instance running NOW.
# The fakes go on PATH rather than through a seam on purpose: this must exercise the DEFAULT
# command, which is the thing that was wrong.
mkdir -p "$TMP/fakebin"
cat > "$TMP/fakebin/journalctl" <<'EOF'
#!/usr/bin/env bash
scoped=0
for a in "$@"; do case "$a" in _SYSTEMD_INVOCATION_ID=*) scoped=1 ;; esac; done
echo 'Sep 18 15:56:00 host nvargus-daemon[887951]: === NVIDIA Libargus Camera Service (0.99.33)=== Listening for connections...'
if [ "$scoped" = 0 ]; then
  # an unscoped window also picks up the PREVIOUS argus instance: the recovery's own noise
  echo 'Sep 18 15:55:18 host nvargus-daemon[886064]: SCF: Error InvalidState: 2 buffers still pending during EGLStreamProducer destruction (in src/services/gl/EGLStreamProducer.cpp, function freeBuffers(), line 300)'
fi
exit 0
EOF
cat > "$TMP/fakebin/systemctl" <<'EOF'
#!/usr/bin/env bash
# only the read-only InvocationID lookup is expected here
case "$*" in
  *InvocationID*nvargus-daemon*) echo "CURRENTARGUSINVOCATION" ;;
  *) echo "unexpected systemctl call: $*" >&2; exit 1 ;;
esac
exit 0
EOF
chmod +x "$TMP/fakebin/journalctl" "$TMP/fakebin/systemctl"

out="$(PATH="$TMP/fakebin:$PATH" ZEDX_MODULE_DIR="$(mk_mod after_recovery 0)" \
       ZEDX_CLIENT_PATTERN="$NO_CLIENT_PATTERN" ZEDX_MODULES_FILE="$MODULES_LOADED" \
       bash "$SCRIPT" 2>&1)"
code=$?
if [ "$code" = 0 ] && printf '%s' "$out" | grep -q 'VERDICT=HEALTHY'; then
  echo "PASS a fault from a previous argus instance does not count (exit=$code)"; pass=$((pass+1))
else
  echo "FAIL a restarted argus must not be judged by the previous instance's faults (exit=$code)"
  printf '%s\n' "$out" | sed 's/^/    /'
  fail=$((fail+1))
fi

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
