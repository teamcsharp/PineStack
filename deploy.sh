#!/bin/sh
# BUILD, PLATFORM-SIGN, INSTALL - AND NEVER THE THREE APART.
#
# WHY THIS SCRIPT EXISTS AT ALL.
#
# The terminal needs two permissions that Android will not grant an ordinary
# app: MODIFY_AUDIO_ROUTING (to hand the sound to the headphone jack) and DUMP
# (to read `dumpsys input` and see whether a cable is actually in). Both are
# signature|privileged, so they are granted only to an APK signed with the
# same key as the framework - here the AOSP platform test key this GSI ships.
#
# Gradle cannot produce that APK. `assembleDebug` always signs with the debug
# key, so the platform signature is a SEPARATE STEP AFTERWARDS, and the moment
# anybody runs the ordinary two commands -
#
#     ./gradlew assembleDebug && adb install -r app-debug.apk
#
# - the tablet quietly goes back to a debug-signed build, both permissions
# read granted=false, and the jack stops working. That has now happened twice.
# It is not a mistake anyone notices, because the app still launches and looks
# entirely normal; the only symptom is that audio stays on the speaker, or
# worse, stays on a headset that is not plugged in.
#
# So the build and the signature are welded together here, and the script
# REFUSES TO INSTALL an APK whose signer does not match the framework's. A
# check that can be skipped is a check that will be skipped.
#
#   ./deploy.sh            build, sign, install, verify
#   ./deploy.sh --no-build just re-sign and install what is already built
#
# Before installation, tools/kiosk-preflight.sh reports the exact ADB target,
# package versions, device-owner status, and lock-task state. It is read-only:
# deployment never factory-resets, removes users/accounts, or changes owners.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SDK=${ANDROID_SDK:-/c/_tools/android-sdk}
TOOLS="$SDK/build-tools/34.0.0"
ADB="$SDK/platform-tools/adb.exe"
GRADLE=${GRADLE:-/c/_tools/gradle/bin/gradle.bat}
DEV=${PINE_TAB:-10.89.1.154:5555}
PKG=com.pinebox.kiosk

# JAVA. apksigner is a java program and Git Bash inherits no JAVA_HOME here,
# which is what stopped this script the first time it ran. The JDK is pinned
# rather than searched for: gradle and apksigner must agree on one.
JAVA_HOME=${JAVA_HOME:-/c/_tools/jdk17}
export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"
export PATH

# The Android plugin finds the SDK through ANDROID_HOME or local.properties,
# and this project has neither checked in (local.properties is gitignored on
# purpose - it is one machine's path). Exported rather than written to a file
# so a fresh clone builds without a manual step.
ANDROID_HOME=$SDK
ANDROID_SDK_ROOT=$SDK
export ANDROID_HOME ANDROID_SDK_ROOT

DEBUG="$HERE/app/build/outputs/apk/debug/app-debug.apk"
SIGNED="$HERE/app/build/outputs/apk/debug/app-platform.apk"
KEY="$HERE/keys/platform.pk8"
CERT="$HERE/keys/platform.x509.pem"
PREFLIGHT="$HERE/tools/kiosk-preflight.sh"

say() { printf '\n== %s\n' "$1"; }

[ -f "$KEY" ] || { echo "no platform key at $KEY - the jack cannot work without it"; exit 1; }

if [ "${1:-}" != "--no-build" ]; then
  say "building"
  # There is NO gradle wrapper in this project - the distribution at
  # /c/_tools/gradle is used directly, with its cache pinned to
  # /c/_tools/_gradlehome so a build does not go looking on the slow share.
  (cd "$HERE" && GRADLE_USER_HOME=${GRADLE_USER_HOME:-/c/_tools/_gradlehome}     "$GRADLE" --console=plain assembleDebug)
fi
[ -f "$DEBUG" ] || { echo "no $DEBUG"; exit 1; }

say "platform-signing"
rm -f "$SIGNED"
"$TOOLS/zipalign.exe" -p -f 4 "$DEBUG" "$SIGNED"
"$TOOLS/apksigner.bat" sign --key "$KEY" --cert "$CERT" \
  --v1-signing-enabled true --v2-signing-enabled true "$SIGNED"

say "kiosk deployment preflight"
ADB="$ADB" AAPT="$TOOLS/aapt.exe" ANDROID_SDK="$SDK" PINE_TAB="$DEV" \
  sh "$PREFLIGHT" --apk "$SIGNED"

# IS THIS THE PLATFORM KEY? Asked twice, because neither question alone is
# enough.
#
# `dumpsys package android` prints only a short hashCode of the framework's
# certificate (b4addb29 on this GSI) - eight hex digits that are NOT a prefix
# of any SHA-256, so an APK's digest cannot be compared against it directly.
# An earlier version of this check tried exactly that, got an empty string out
# of the dumpsys parse, and then matched everything against it. A guard that
# passes when it fails to read its input is worse than no guard, so:
#
#   1. the APK's signer must be the AOSP platform test key, by full SHA-256;
#   2. the tablet's framework must still be signed by the certificate whose
#      hashCode is b4addb29 - so that reflashing the tablet with a differently
#      signed GSI is noticed here rather than discovered as a dead jack.
PLATFORM_SHA=c8a2e9bccf597c2fb6dc66bee293fc13f2fc47ec77bc6b2b0d52c11f51192ab8
FRAMEWORK_HASH=b4addb29

say "checking the signature against the framework"
GOT=$("$TOOLS/apksigner.bat" verify --print-certs "$SIGNED" 2>/dev/null   | sed -n 's/.*SHA-256 digest: *//p' | head -1)
WANT=$("$ADB" -s "$DEV" shell dumpsys package android 2>/dev/null \
  | sed -n 's/.*signatures:\[\([0-9a-f][0-9a-f]*\)\].*/\1/p' | head -1) || true
echo "this apk signer : ${GOT:-<could not read>}"
echo "framework key   : ${WANT:-<could not read>}"

[ -n "$GOT" ] || { echo "REFUSING: could not read this apk's signer."; exit 1; }
[ "$GOT" = "$PLATFORM_SHA" ] || {
  echo "REFUSING TO INSTALL - this apk is not signed with the platform key."
  echo "MODIFY_AUDIO_ROUTING and DUMP would both be denied and the jack would"
  echo "stop following the cable. Fix the key, not this check."
  exit 1; }
[ -n "$WANT" ] || { echo "REFUSING: could not read the tablet's framework key."; exit 1; }
[ "$WANT" = "$FRAMEWORK_HASH" ] || {
  echo "REFUSING - this tablet's framework is signed with $WANT, not"
  echo "$FRAMEWORK_HASH. It has been reflashed with a different GSI, and the"
  echo "platform key in keys/ no longer matches it."
  exit 1; }

say "installing"
if ! "$ADB" -s "$DEV" install -r "$SIGNED" 2>&1 | tee /dev/stderr | grep -q Success; then
  # A signature change cannot be installed over the top; the old one has to go
  # first. Done only on that failure, because an uninstall loses the app's own
  # settings and the device-owner grant with it.
  say "signature differs from what is installed - removing the old one first"
  "$ADB" -s "$DEV" uninstall "$PKG" || true
  "$ADB" -s "$DEV" install "$SIGNED"
  # An uninstall takes the RUNTIME grants with it, and the talk dot is silently
  # useless without RECORD_AUDIO - it records, gets zeros, and the station
  # transcribes nothing. There is no prompt to fall back on in a kiosk that
  # owns HOME, so it is granted here.
  "$ADB" -s "$DEV" shell pm grant "$PKG" android.permission.RECORD_AUDIO || true
  # Looking through the tablet's camera from the desktop. Runtime, so an
  # uninstall takes it with it, same as the microphone above.
  "$ADB" -s "$DEV" shell pm grant "$PKG" android.permission.CAMERA || true
fi

say "what the tablet granted"
"$ADB" -s "$DEV" shell dumpsys package "$PKG" \
  | grep -E 'MODIFY_AUDIO_ROUTING|android.permission.DUMP|RECORD_AUDIO' || true
echo
echo "Both MODIFY_AUDIO_ROUTING and DUMP must say granted=true."
echo "If either says false, the jack will not follow the cable."
