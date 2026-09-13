# PineBoxKiosk

The Lenovo Tab M9 as a Pine Box terminal: one full-screen WebView showing
the station's own control panel, with the same `window.pineDesktop` bridge
the Electron desktop provides, plus the kiosk behaviour that stops the
tablet being a tablet.

## The device

| | |
|---|---|
| model | Lenovo TB310FU, serial `HA1Y7RCV` |
| SoC | MediaTek MT6768, **arm64-v8a** (the only ABI built) |
| ROM | LineageOS 21 / Android 14 / SDK 34, build type **userdebug** |
| screen | 9", used in landscape, 1340x800 |
| adb | enabled by default (userdebug); over Wi-Fi at `10.89.1.154:5555` |
| Play Services | **none** - nothing here may depend on `play-services-*` |

```sh
adb connect 10.89.1.154:5555
adb -s 10.89.1.154:5555 install -r app/build/outputs/apk/debug/app-debug.apk
adb -s 10.89.1.154:5555 logcat -s PineKioskActivity PineBridge PinePanel PineKiosk PineAudio
```

## The station

`http://10.89.1.246:8096`, plain HTTP on the LAN. Cleartext is permitted
**for that host only** - see `app/src/main/res/xml/network_security_config.xml`.
Moving the station to another address means editing that file as well as the
config; a runtime `writeConfig` deliberately cannot widen the network policy.

Auth is `Authorization: Bearer <key>`, and the key provisions itself: the
panel at `/` embeds `const SERVER_KEY = "…";`, which `KeyDiscovery` lifts out
on first launch. Most read routes answer without a bearer today; one is sent
anyway on every request.

## Building

Gradle 8.7 / AGP 8.5.2 / Kotlin 1.9.24 / JDK 17.

**The wrapper JAR is not in this repo** (it is a binary). Generate it once:

```sh
gradle wrapper --gradle-version 8.7
```

after which `./gradlew assembleDebug` works normally. Android Studio will
also fetch it on first open.

```sh
./gradlew test            # JVM unit tests, no device needed
./gradlew assembleDebug
```

### The native audio engine

`app/src/main/cpp/` is the sampler, written by a separate agent with its own
CMakeLists.txt. `app/build.gradle.kts` turns its `externalNativeBuild`
stanza on **only when that file exists**, so the project builds either way.

`ndkVersion` is pinned to **26.1.10909125** and the only ABI built is
`arm64-v8a`.

**Oboe.** `cpp/CMakeLists.txt` fetches google/oboe 1.9.0 over the network on
the first configure. On a build box with no outbound network, clone it once:

```sh
git clone --depth 1 --branch 1.9.0 https://github.com/google/oboe \
    app/src/main/cpp/third_party/oboe
```

and it is picked up with no flags.

**The JNI binding is still missing, and its package is not this one.**
`cpp/android/jni_bridge.cpp` exports `Java_fm_pinebox_kiosk_audio_PineSampler_*`,
so the class declaring those `external fun`s must be
**`fm.pinebox.kiosk.audio.PineSampler`** - JNI resolves by *class* package,
which need not match the application id, so such a class is perfectly legal
inside this `com.pinebox.kiosk` app. It has not been written yet.

`audio/NativeAudio.kt` is only the loader: it names the library
(`libpinebox_sampler.so`) in one place and reports `available = false`
instead of crashing when the engine is not in the build.

## Making it a kiosk

Three separate mechanisms, doing different jobs (see `KioskController`):

1. **HOME** - the `MAIN` + `HOME` + `DEFAULT` intent filter in the manifest.
   Decides where every boot and every back-out-of-everything lands. This is
   the mechanism that actually works on Android 14; the `BOOT_COMPLETED`
   receiver is belt and braces, because a background process may not start
   an activity since Android 10.
2. **Lock task** - `startLockTask()`. Decides whether the user can leave at
   all. Without device owner this is only *screen pinning*: a toast, and
   Back+Recents held together lets them out.
3. **Immersive** - whether the system bars are drawn. Cosmetic, and the one
   that needs re-applying on every focus change.

### Device owner

Lock task without a pinning prompt, `setLockTaskPackages`, a sticky HOME and
a disabled status bar all require device owner. Provision it with:

```sh
adb -s 10.89.1.154:5555 shell dpm set-device-owner \
    com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver
```

This **fails** unless:

* the app is already installed,
* there are **no accounts on the device** (`Settings > Accounts` empty - a
  fresh LineageOS install with no Google account qualifies), and
* no other device owner or profile owner is set.

If it refuses with "Not allowed to set the device owner because there are
already several users on the device", remove the extra users first:

```sh
adb shell pm list users
adb shell pm remove-user <id>
```

To undo it (the tablet becomes an ordinary tablet again):

```sh
adb shell dpm remove-active-admin com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver
```

## Why the panel is zoomed

The panel's narrow layout is `@media (max-width: 900px)` (app.py:132011).
The M9's 1340x800 landscape screen at the default WebView scale lays out at
about **893 CSS px** - the phone layout, by seven pixels.

`MainActivity.initialScalePercent()` therefore sets an initial scale of
`widthPx * 100 / 1000`, which on this device is 134% and gives roughly
1000x597 CSS px. It is computed rather than hard-coded so the same APK does
something sensible on the next tablet. `onPageFinished` runs a guard that
forces `width=1000` on the viewport meta if `innerWidth` still came out at
900 or less, and says so in the console.

## The bridge

`assets/pine-bridge.js` installs `window.pineDesktop` with every method
`desktop/preload.js` exposes. Async methods are Promises over
`__pineNative.invoke(id, method, argsJson)`, settled later by
`__pineBridgeSettle`. `copyText` and `copyImage` are **synchronous
booleans**, because app.py:170463 tests `copyImage(data) === false` - a
Promise would report success on every failure.

Refused-but-resolved (`{ok:false, unsupported:true}`), because the hardware
is on the box and not on the terminal:

* `startBackend` / `stopBackend` / `setupBackend` / `reconstituteDesktop`
* every `lcd*`
* every `terminal*`

`copyImage` writes the PNG to `cache/clipboard/` and puts a `content://` URI
on the clipboard through the FileProvider in the manifest - Android's
clipboard cannot carry a bitmap the way Electron's can.

## The poll

`StationFeed` is the **one** poller of `/api/dj`, at **4 seconds**, with the
playhead interpolated locally at 250 ms from `stream_now`.

That is the station's own contract (app.py:155440: "the round clock every
250ms, speaking_now every 4s") and the desktop implements the same split.
Polling `/api/dj` at 250 ms would be sixteen times the traffic for the same
answer, against a station with a documented history of being starved by
chatty clients. **Do not shorten `POLL_MS`.**

## Routes this app knows about

Nothing here invents an endpoint. `net/StationUrls.kt` is the closed list:

```
/api/dj                        /api/dj/provenance/{id}
/api/booth/clip?line=&whole=   /api/airlog
/api/dj/sfx                    /api/sfx/stats
/music/{id}?t=                 /media/{key}?t=
/api/generations               /api/generations/image/{file}
```

The panel itself reaches whatever it likes through `pineDesktop.get/post` -
it is the station's own HTML and knows its own API.

## Deliberately left for later

* **The JNI binding for the sampler** - `fm.pinebox.kiosk.audio.PineSampler`,
  about thirty `external fun`s matching `cpp/android/jni_bridge.cpp`. The
  engine and its CMake are in the tree; the Kotlin class that reaches them
  is not. `NativeAudio` loads the library and stops there, and nothing in
  the app calls into the engine yet.
* **Call-in / microphone.** `onPermissionRequest` denies. Turning the
  terminal into a call-in point needs `RECORD_AUDIO` in the manifest, a
  runtime request, and `grant()` - in that order.
* **A native view of the feed.** The feed is collected today only to drive
  the offline banner; the panel draws itself. `FeedRow` is ready for a
  native now-playing strip if one is ever wanted.
* **Release signing.** The release build uses the debug key, on purpose:
  private LAN, no Play listing. Swap in a real `signingConfig` if that
  changes.
* **The gradle wrapper JAR** - see Building.
