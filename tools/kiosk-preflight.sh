#!/bin/sh
# Read-only deployment diagnostics for the Pine tablet. This script never
# provisions, uninstalls, removes users/accounts, or resets the device.
set -eu

PKG=${PINE_KIOSK_PACKAGE:-com.pinebox.kiosk}
ADMIN=${PINE_KIOSK_ADMIN:-com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver}
DEV=${PINE_TAB:-10.89.1.154:5555}
EXPECTED_SERIAL=${PINE_TAB_SERIAL:-HA1Y7RCV}
SDK=${ANDROID_SDK:-${ANDROID_HOME:-/c/_tools/android-sdk}}
ADB=${ADB:-$SDK/platform-tools/adb.exe}
AAPT=${AAPT:-$SDK/build-tools/34.0.0/aapt.exe}
APK=
REQUIRE_KIOSK=0
WARNINGS=0

usage() {
  cat <<'EOF'
usage: tools/kiosk-preflight.sh [--apk PATH] [--require-kiosk]

Checks the selected ADB target, installed and candidate package versions,
device-owner eligibility, and lock-task state. It is read-only.

  --apk PATH       inspect the APK that deploy.sh is about to install
  --require-kiosk  fail unless PineBox is device owner and lock task is active

Environment: PINE_TAB, PINE_TAB_SERIAL, ANDROID_SDK, ADB, AAPT,
PINE_KIOSK_PACKAGE. Set PINE_TAB_SERIAL empty to report without enforcing it.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --apk)
      [ "$#" -ge 2 ] || { echo "ERROR: --apk needs a path" >&2; exit 2; }
      APK=$2
      shift 2
      ;;
    --require-kiosk)
      REQUIRE_KIOSK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

info() { printf 'OK: %s\n' "$*"; }
warn() { WARNINGS=$((WARNINGS + 1)); printf 'WARN: %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

adb_target() {
  "$ADB" -s "$DEV" "$@"
}

echo "PineBox kiosk deployment preflight (read-only)"
echo "target: $DEV"

[ -x "$ADB" ] || fail "adb is not executable at $ADB. Set ANDROID_SDK or ADB."

STATE_OUTPUT=$(adb_target get-state 2>&1) || {
  printf '%s\n' "$STATE_OUTPUT" >&2
  fail "cannot use ADB target $DEV. Run: adb connect $DEV; then: adb -s $DEV get-state"
}
STATE=$(printf '%s\n' "$STATE_OUTPUT" | tr -d '\r' | tail -n 1)
[ "$STATE" = device ] || fail "ADB target $DEV is '$STATE', not 'device'. Re-authorize USB/Wi-Fi debugging, then run: adb -s $DEV get-state"

MODEL=$(adb_target shell getprop ro.product.model 2>/dev/null | tr -d '\r' | tail -n 1)
SERIAL=$(adb_target shell getprop ro.serialno 2>/dev/null | tr -d '\r' | tail -n 1)
SDK_LEVEL=$(adb_target shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' | tail -n 1)
[ -z "$EXPECTED_SERIAL" ] || [ "$SERIAL" = "$EXPECTED_SERIAL" ] || fail "ADB target $DEV reports serial ${SERIAL:-unknown}, expected $EXPECTED_SERIAL. Set PINE_TAB/PINE_TAB_SERIAL only after verifying the intended tablet."
info "ADB target is online: model=${MODEL:-unknown}, serial=${SERIAL:-unknown}, SDK=${SDK_LEVEL:-unknown}"

INSTALLED=0
INSTALLED_VERSION_NAME=
INSTALLED_VERSION_CODE=
PACKAGE_PATH=$(adb_target shell pm path "$PKG" 2>/dev/null) || PACKAGE_PATH=
if printf '%s\n' "$PACKAGE_PATH" | grep -q '^package:'; then
  INSTALLED=1
  PACKAGE_DUMP=$(adb_target shell dumpsys package "$PKG" 2>/dev/null | tr -d '\r')
  INSTALLED_VERSION_NAME=$(printf '%s\n' "$PACKAGE_DUMP" | sed -n 's/^[[:space:]]*versionName=//p' | head -n 1)
  INSTALLED_VERSION_CODE=$(printf '%s\n' "$PACKAGE_DUMP" | sed -n 's/^[[:space:]]*versionCode=\([0-9][0-9]*\).*/\1/p' | head -n 1)
  info "installed package: $PKG versionName=${INSTALLED_VERSION_NAME:-unknown} versionCode=${INSTALLED_VERSION_CODE:-unknown}"
else
  warn "$PKG is not installed. deploy.sh will install it; device-owner provisioning cannot run until installation succeeds."
fi

if [ -n "$APK" ]; then
  [ -f "$APK" ] || fail "candidate APK does not exist: $APK"
  [ -x "$AAPT" ] || fail "aapt is not executable at $AAPT. Set AAPT to the matching Android build-tools binary."
  BADGING=$("$AAPT" dump badging "$APK" 2>&1) || {
    printf '%s\n' "$BADGING" >&2
    fail "could not inspect candidate APK: $APK"
  }
  APK_PACKAGE=$(printf '%s\n' "$BADGING" | sed -n "s/^package: name='\([^']*\)'.*/\1/p" | head -n 1)
  APK_VERSION_CODE=$(printf '%s\n' "$BADGING" | sed -n "s/^package:.* versionCode='\([^']*\)'.*/\1/p" | head -n 1)
  APK_VERSION_NAME=$(printf '%s\n' "$BADGING" | sed -n "s/^package:.* versionName='\([^']*\)'.*/\1/p" | head -n 1)
  [ -n "$APK_PACKAGE" ] || fail "aapt did not report a package name for $APK"
  [ "$APK_PACKAGE" = "$PKG" ] || fail "candidate APK package is $APK_PACKAGE, expected $PKG; refusing to target the tablet"
  info "candidate APK: $PKG versionName=${APK_VERSION_NAME:-unknown} versionCode=${APK_VERSION_CODE:-unknown}"
  if [ "$INSTALLED" -eq 1 ] && { [ "$APK_VERSION_NAME" != "$INSTALLED_VERSION_NAME" ] || [ "$APK_VERSION_CODE" != "$INSTALLED_VERSION_CODE" ]; }; then
    warn "candidate and installed versions differ; deploy.sh will replace ${INSTALLED_VERSION_NAME:-unknown}/${INSTALLED_VERSION_CODE:-unknown} with ${APK_VERSION_NAME:-unknown}/${APK_VERSION_CODE:-unknown}."
  fi
fi

OWNERS=$(adb_target shell dpm list-owners 2>/dev/null | tr -d '\r') || fail "could not read DevicePolicyManager owner state"
OWNER_OK=0
if printf '%s\n' "$OWNERS" | grep -F "$ADMIN" | grep -Eiq 'DeviceOwner|device owner'; then
  OWNER_OK=1
  info "device owner: $ADMIN"
elif printf '%s\n' "$OWNERS" | grep -Eiq 'no owners|no owner'; then
  warn "no device owner is enrolled; PineBox can be HOME/immersive but cannot enforce a true kiosk."
else
  warn "another device/profile owner is enrolled: $(printf '%s' "$OWNERS" | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g')"
  echo "      Inspect it with: adb -s $DEV shell dpm list-owners"
  echo "      Do not remove an owner until its data and management role are understood."
fi

ACTIVITY=$(adb_target shell dumpsys activity activities 2>/dev/null | tr -d '\r') || fail "could not read ActivityManager lock-task state"
LOCK_STATE=$(printf '%s\n' "$ACTIVITY" | sed -n 's/^[[:space:]]*mLockTaskModeState=//p' | head -n 1)
LOCK_OK=0
case "$LOCK_STATE" in
  LOCKED)
    LOCK_OK=1
    info "lock task is active: $LOCK_STATE"
    ;;
  PINNED)
    warn "lock task is only PINNED (screen pinning), not owner-enforced LOCKED mode."
    ;;
  NONE|'')
    warn "lock task is not active (${LOCK_STATE:-unknown}); the app can be escaped or is not currently foregrounded."
    echo "      After owner provisioning/relaunch, verify: adb -s $DEV shell dumpsys activity activities | grep mLockTaskModeState"
    ;;
  *)
    warn "unrecognized lock-task state: $LOCK_STATE"
    ;;
esac

if [ "$OWNER_OK" -eq 0 ]; then
  USERS=$(adb_target shell pm list users 2>/dev/null | tr -d '\r')
  USER_COUNT=$(printf '%s\n' "$USERS" | grep -c 'UserInfo{' || true)
  ACCOUNTS=$(adb_target shell dumpsys account 2>/dev/null | tr -d '\r')
  ACCOUNT_COUNTS=$(printf '%s\n' "$ACCOUNTS" | sed -n 's/^[[:space:]]*Accounts:[[:space:]]*//p')
  HAS_ACCOUNTS=0
  if printf '%s\n' "$ACCOUNT_COUNTS" | grep -Evq '^0$|^[[:space:]]*$'; then HAS_ACCOUNTS=1; fi
  PROVISIONED=$(adb_target shell settings get global device_provisioned 2>/dev/null | tr -d '\r' | tail -n 1)
  SETUP=$(adb_target shell settings get secure user_setup_complete 2>/dev/null | tr -d '\r' | tail -n 1)

  echo "owner eligibility: users=${USER_COUNT:-unknown}, accounts=$([ "$HAS_ACCOUNTS" -eq 0 ] && echo none || echo present), device_provisioned=${PROVISIONED:-unknown}, user_setup_complete=${SETUP:-unknown}"
  if [ "$INSTALLED" -eq 0 ]; then
    echo "      Install with ./deploy.sh before attempting owner enrollment."
  elif [ "${USER_COUNT:-0}" -gt 1 ] || [ "$HAS_ACCOUNTS" -ne 0 ]; then
    warn "device-owner enrollment is blocked while extra users or accounts exist."
    echo "      Review users:    adb -s $DEV shell pm list users"
    echo "      Review accounts: adb -s $DEV shell dumpsys account"
    echo "      Remove accounts in Android Settings; remove only disposable extra users with: adb -s $DEV shell pm remove-user USER_ID"
  else
    echo "      Non-destructive enrollment attempt:"
    echo "      adb -s $DEV shell dpm set-device-owner $ADMIN"
    echo "      If Android reports that the already-provisioned device cannot accept an owner, owner enrollment is impossible in place."
    echo "      The supported next step is a deliberate backup + factory reset + enrollment during initial setup; this tool never performs a reset."
  fi
fi

if [ "$REQUIRE_KIOSK" -eq 1 ] && { [ "$OWNER_OK" -ne 1 ] || [ "$LOCK_OK" -ne 1 ]; }; then
  fail "--require-kiosk requested, but device-owner and active lock-task checks did not both pass"
fi

echo "preflight result: PASS with $WARNINGS warning(s)"
