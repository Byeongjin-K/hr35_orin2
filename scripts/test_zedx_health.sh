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

run_case() { # name want_code want_verdict module_dir argus_log client_pattern
  local name="$1" want_code="$2" want_verdict="$3" moddir="$4" arguslog="$5" pattern="$6" out code
  out="$(ZEDX_MODULE_DIR="$moddir" ZEDX_ARGUS_LOG_CMD="cat $arguslog" ZEDX_CLIENT_PATTERN="$pattern" \
         bash "$SCRIPT" 2>&1)"
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
run_case "refcnt underflow"               2 REBOOT_REQUIRED "$(mk_mod broken -1)"   "$clean_log" "$NO_CLIENT_PATTERN"
run_case "driver not loaded"              2 REBOOT_REQUIRED "$(mk_mod noload none)" "$clean_log" "$NO_CLIENT_PATTERN"
run_case "stale argus, no client"         1 RECOVERABLE     "$(mk_mod orphan 0)"    "$stale_log" "$NO_CLIENT_PATTERN"
run_case "underflow outranks argus"       2 REBOOT_REQUIRED "$(mk_mod both -1)"     "$stale_log" "$NO_CLIENT_PATTERN"
# Regression: nvargus logs the very same lines during ordinary contention while a node legitimately
# holds the camera. A live client means the sensor is NOT orphaned. Goes through the real pgrep path.
run_case "faults but client holds camera" 0 HEALTHY         "$(mk_mod busy 3)"      "$stale_log" "$LIVE_CLIENT_PATTERN"

echo "----"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
