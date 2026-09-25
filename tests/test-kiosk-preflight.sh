#!/bin/sh
set -eu

HERE=$(cd "$(dirname "$0")/.." && pwd)
PREFLIGHT="$HERE/tools/kiosk-preflight.sh"
TMP=${TMPDIR:-/tmp}/pinebox-preflight-test-$$
mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

cat >"$TMP/adb" <<'EOF'
#!/bin/sh
shift 2 # -s TARGET
case "${MOCK_SCENARIO:-ready}:$*" in
  unauthorized:get-state)
    echo 'error: device unauthorized' >&2
    exit 1 ;;
  *:get-state) echo device ;;
  *:'shell getprop ro.product.model') echo 'Test Tablet' ;;
  wrong_serial:'shell getprop ro.serialno') echo WRONG999 ;;
  *:'shell getprop ro.serialno') echo TEST123 ;;
  *:'shell getprop ro.build.version.sdk') echo 34 ;;
  missing_package:'shell pm path com.pinebox.kiosk') : ;;
  *:'shell pm path com.pinebox.kiosk') echo package:/data/app/base.apk ;;
  *:'shell dumpsys package com.pinebox.kiosk')
    echo '  versionCode=1 minSdk=30 targetSdk=34'
    echo '  versionName=1.0.0' ;;
  ready:'shell dpm list-owners') echo 'User 0: admin=com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver,DeviceOwner' ;;
  profile_owner:'shell dpm list-owners') echo 'User 0: admin=com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver,ProfileOwner' ;;
  *:'shell dpm list-owners') echo 'no owners' ;;
  ready:'shell dumpsys activity activities') echo '  mLockTaskModeState=LOCKED' ;;
  profile_owner:'shell dumpsys activity activities') echo '  mLockTaskModeState=LOCKED' ;;
  *:'shell dumpsys activity activities') echo '  mLockTaskModeState=NONE' ;;
  *:'shell pm list users')
    echo 'Users:'
    echo '  UserInfo{0:Owner:4c13} running' ;;
  *:'shell dumpsys account') echo '  Accounts: 0' ;;
  *:'shell settings get global device_provisioned') echo 1 ;;
  *:'shell settings get secure user_setup_complete') echo 1 ;;
  *) echo "unhandled mock adb call: $*" >&2; exit 99 ;;
esac
EOF

cat >"$TMP/aapt" <<'EOF'
#!/bin/sh
if [ "${MOCK_SCENARIO:-ready}" = wrong_apk ]; then
  echo "package: name='example.wrong' versionCode='9' versionName='9.0'"
else
  echo "package: name='com.pinebox.kiosk' versionCode='1' versionName='1.0.0'"
fi
EOF
chmod +x "$TMP/adb" "$TMP/aapt"
: >"$TMP/app.apk"

run_case() {
  CASE=$1
  shift
  set +e
  OUTPUT=$(MOCK_SCENARIO="$CASE" ADB="$TMP/adb" AAPT="$TMP/aapt" PINE_TAB=test:5555 PINE_TAB_SERIAL=TEST123 sh "$PREFLIGHT" --apk "$TMP/app.apk" "$@" 2>&1)
  STATUS=$?
  set -e
}

contains() {
  printf '%s\n' "$OUTPUT" | grep -F "$1" >/dev/null || {
    echo "missing output: $1" >&2
    printf '%s\n' "$OUTPUT" >&2
    exit 1
  }
}

run_case ready
[ "$STATUS" -eq 0 ] || { printf '%s\n' "$OUTPUT"; exit 1; }
contains 'OK: device owner: com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver'
contains 'OK: lock task is active: LOCKED'
contains 'preflight result: PASS with 0 warning(s)'

run_case unprovisioned
[ "$STATUS" -eq 0 ] || { printf '%s\n' "$OUTPUT"; exit 1; }
contains 'WARN: no device owner is enrolled'
contains 'adb -s test:5555 shell dpm set-device-owner'
contains 'this tool never performs a reset'

run_case unprovisioned --require-kiosk
[ "$STATUS" -eq 1 ] || { echo "--require-kiosk should fail"; printf '%s\n' "$OUTPUT"; exit 1; }
contains 'ERROR: --require-kiosk requested'

run_case profile_owner --require-kiosk
[ "$STATUS" -eq 1 ] || { echo "profile owner must not pass kiosk check"; printf '%s\n' "$OUTPUT"; exit 1; }
contains 'WARN: another device/profile owner is enrolled'

run_case missing_package
[ "$STATUS" -eq 0 ] || { printf '%s\n' "$OUTPUT"; exit 1; }
contains 'WARN: com.pinebox.kiosk is not installed'

run_case unauthorized
[ "$STATUS" -eq 1 ] || { echo "unauthorized target should fail"; printf '%s\n' "$OUTPUT"; exit 1; }
contains 'cannot use ADB target test:5555'

run_case wrong_serial
[ "$STATUS" -eq 1 ] || { echo "wrong serial should fail"; printf '%s\n' "$OUTPUT"; exit 1; }
contains 'reports serial WRONG999, expected TEST123'

run_case wrong_apk
[ "$STATUS" -eq 1 ] || { echo "wrong APK should fail"; printf '%s\n' "$OUTPUT"; exit 1; }
contains 'candidate APK package is example.wrong, expected com.pinebox.kiosk'

echo 'kiosk preflight tests: PASS'
