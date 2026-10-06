#!/bin/sh
# Enable the existing Tab M9 userdebug GSI's second, local-only STA.
# Root registers a system-owned fabricated overlay: shell-owned overlays
# are discarded at boot, and data-installed APKs fail the resource policy.
# No system partition, camera credentials or primary Wi-Fi profile is edited.
# Rollback (as adb root): cmd overlay disable --user 0 android:PineCamDualWifi
# then cmd wifi reload-resources. Reboot once to verify persistence.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SDK=${ANDROID_SDK:-/c/_tools/android-sdk}
TOOLS="$SDK/build-tools/34.0.0"
OUT=${PINE_DUAL_WIFI_BUILD:-/c/_tools/pinebox-dual-wifi}
DEV=${PINE_TAB:-10.89.1.154:5555}
JAVA_HOME=${JAVA_HOME:-/c/_tools/jdk17}
export JAVA_HOME
PATH="$JAVA_HOME/bin:$PATH"
export PATH
mkdir -p "$OUT/classes"
"$JAVA_HOME/bin/javac.exe" -source 8 -target 8 -d "$OUT/classes" "$HERE/OverlayConfig.java"
"$TOOLS/d8.bat" --output "$OUT/overlay-config.jar" "$OUT/classes/fm/pinebox/dualwifi/OverlayConfig.class"
ADB="$SDK/platform-tools/adb.exe"
"$ADB" -s "$DEV" shell dumpsys wifi | grep -q 'STA + STA Concurrency Supported: true' || {
    echo 'Refusing: this device does not advertise two Wi-Fi stations.' >&2; exit 1;
}
"$ADB" -s "$DEV" root
sleep 2
"$ADB" connect "$DEV"
"$ADB" -s "$DEV" shell id | grep -q 'uid=0' || {
    echo 'Refusing: userdebug adb root is required.' >&2; exit 1;
}
DEX_WIN=$(cygpath -w "$OUT/overlay-config.jar")
MSYS_NO_PATHCONV=1 "$ADB" -s "$DEV" push "$DEX_WIN" /data/local/tmp/pinecam-overlay-config.jar
MSYS_NO_PATHCONV=1 "$ADB" -s "$DEV" shell 'CLASSPATH=/data/local/tmp/pinecam-overlay-config.jar app_process /system/bin fm.pinebox.dualwifi.OverlayConfig'
"$ADB" -s "$DEV" shell cmd wifi reload-resources
"$ADB" -s "$DEV" shell cmd overlay lookup com.android.wifi.resources \
    com.android.wifi.resources:bool/config_wifiMultiStaLocalOnlyConcurrencyEnabled
echo 'Reboot after first activation so existing app feature caches refresh; the overlay survives reboot.'
