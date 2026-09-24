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

# The renderer is the official copy of every shared tablet view. The APK
# carries the video controller twice because the panel and sampler are
# separate injected pages; silently building any stale view recreates bugs
# already fixed on the desktop. Sync when the canonical workspace is mounted,
# then refuse an internal video split on every machine.
VIEW_CANON=${PINE_VIEW_CANON:-//10.89.1.246/ehm_eckx/pinevoice-stack/spark-agent/desktop/renderer}
VIEW_PANEL="$HERE/app/src/main/assets/pine-views"
VIEW_SAMPLER="$HERE/app/src/main/assets/pine-sampler"
if [ -f "$VIEW_CANON/sfx-tv.js" ]; then
  say "syncing canonical shared views"
  # Every file already carried by pine-views is a declared injection asset.
  # Sync the intersection instead of maintaining a second hand-written list:
  # that list omitted boot-splash.js and line-actions.js and quietly shipped
  # stale startup and dialogue behavior in otherwise current APKs.
  for target in "$VIEW_PANEL"/*; do
    [ -f "$target" ] || continue
    asset=${target##*/}
    # Android owns the field microphone's focus/append handling here. A
    # renderer sync would replace it just before packaging the APK.
    [ "$asset" = talk-dot.js ] && continue
    [ -f "$VIEW_CANON/$asset" ] && cp "$VIEW_CANON/$asset" "$target"
  done
  for asset in sfx-tv.js sfx-tv.css; do
    [ -f "$VIEW_CANON/$asset" ] && cp "$VIEW_CANON/$asset" "$VIEW_SAMPLER/$asset"
  done
  for asset in sampler-air.js sampler-feed.js sampler.js; do
    [ -f "$VIEW_CANON/$asset" ] && [ -f "$VIEW_SAMPLER/$asset" ] && \
      cp "$VIEW_CANON/$asset" "$VIEW_SAMPLER/$asset"
  done
fi
cmp -s "$VIEW_PANEL/sfx-tv.js" "$VIEW_SAMPLER/sfx-tv.js" || {
  echo "REFUSING: the panel and sampler have different sfx-tv.js copies."
  echo "Run with PINE_VIEW_CANON pointing at desktop/renderer."
  exit 1
}
cmp -s "$VIEW_PANEL/sfx-tv.css" "$VIEW_SAMPLER/sfx-tv.css" || {
  echo "REFUSING: the panel and sampler have different sfx-tv.css copies."
  echo "Run with PINE_VIEW_CANON pointing at desktop/renderer."
  exit 1
}

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
# Never turn a failed update into an uninstall. The old path assumed every
# install error was a signature mismatch, removed the live kiosk, and could
# then be interrupted before its second install. A transient ADB/storage/link
# failure consequently left the tablet with no PineBox package at all.
# Signature migration is an explicit maintenance operation; ordinary deploys
# either update the known package in place or leave the working copy intact.
INSTALL_RC=0
if INSTALL_OUT=$("$ADB" -s "$DEV" install -r "$SIGNED" 2>&1); then
  INSTALL_RC=0
else
  INSTALL_RC=$?
fi
printf '%s\n' "$INSTALL_OUT"
if [ "$INSTALL_RC" -ne 0 ] || ! printf '%s\n' "$INSTALL_OUT" | grep -q '^Success'; then
  echo "DEPLOY FAILED - the installed PineBox app was left untouched." >&2
  if printf '%s\n' "$INSTALL_OUT" | grep -q 'INSTALL_FAILED_UPDATE_INCOMPATIBLE'; then
    echo "The installed signer differs. Verify both signers and perform the" >&2
    echo "one-time uninstall/reinstall deliberately; this script will not" >&2
    echo "remove the kiosk automatically." >&2
  fi
  exit 1
fi

# These survive an in-place update. Reasserting them is harmless and also
# repairs a package restored with Android's install-existing machinery.
"$ADB" -s "$DEV" shell pm grant "$PKG" android.permission.RECORD_AUDIO || true
"$ADB" -s "$DEV" shell pm grant "$PKG" android.permission.CAMERA || true

say "what the tablet granted"
"$ADB" -s "$DEV" shell dumpsys package "$PKG" \
  | grep -E 'MODIFY_AUDIO_ROUTING|android.permission.DUMP|RECORD_AUDIO' || true
echo
echo "Both MODIFY_AUDIO_ROUTING and DUMP must say granted=true."
echo "If either says false, the jack will not follow the cable."
