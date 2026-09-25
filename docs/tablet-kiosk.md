# Pine Box tablet

The Android kiosk source is in `app/` alongside the station. Its target is the
Lenovo TB310FU (`HA1Y7RCV`) on LineageOS 21, reachable at
`10.89.1.154:5555`. It loads the station at `http://10.89.1.246:8096` and
uses the same Script renderer as the desktop panel.

## Build and deploy

Use JDK 17, Android SDK 34, NDK 26.1.10909125, and Gradle 8.7. The Gradle
wrapper properties are tracked; a local Gradle installation is needed if the
wrapper JAR is absent. Run `testDebugUnitTest` and `assembleDebug` before
deployment. `deploy.sh` then syncs shared renderer assets, checks the kiosk
state, platform-signs the APK, installs it, and verifies its signature and
privileged audio-routing permissions. **Do not install `app-debug.apk`
directly:** its debug signature cannot retain those permissions.

```sh
gradle testDebugUnitTest assembleDebug
./deploy.sh --no-build
sh tools/kiosk-preflight.sh --require-kiosk
```

`keys/` is intentionally ignored and must stay outside Git. The deployer
requires the device's platform signing material there. It refuses an unsigned
or mismatched APK and does not reset, reprovision, or remove device data.

## Shared views

`desktop/renderer/` is canonical for shared panel files. Run
`tools/sync-tablet-assets.ps1` before a local Windows build; `deploy.sh`
performs its own sync and consistency checks. The Android-owned
`talk-dot.js` is deliberately not overwritten.

## Verification

Run `node --test tests/test-field-dictation.cjs` and
`sh tests/test-kiosk-preflight.sh` for bridge and preflight regressions.
`tools/profile-tablet-webview.cjs` profiles the installed Script WebView;
also inspect `adb shell dumpsys gfxinfo com.pinebox.kiosk` and an actual
screen capture at the target orientation. A passing unit suite does not prove
smooth on-device frames or uninterrupted audio.
