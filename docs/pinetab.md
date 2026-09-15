# PineTab — the Lenovo Tab M9 as a Pine Box terminal

This document has three parts.

**Part 0 (§0.1–0.12)** is the field guide: everything a project that has never
seen this tablet needs in order to reach it, read it, put its own software on
it, talk to the station from it, and stay out of the kiosk's way. It was
written on 2026-09-14 from the source of the kiosk, the station and the desk,
and from readings taken off the live tablet that evening. Where the two
disagree, the live reading is given and the source is named. Start here.

**Part I (§1–14)** is how a stock Lenovo Tab M9 was made ours — the unlock,
the GSI, the jack, the tailnet. **Part II (§15–29)** is the software that runs
on it as it was built, and every way it has been seen to fail. Both are the
record; Part 0 is the map of it. If something is broken, §19 is still the
place to read first.

---

# Part 0 — the field guide

## 0.1 The one-page version

| | |
|---|---|
| The tablet | Lenovo Tab M9 (TB310FU), MediaTek MT6768, arm64-v8a, 4 GB RAM, 64 GB. 9-inch, **800×1340 physical, used landscape as 1340×800**, density 200 |
| What it runs | **TrebleDroid vanilla GSI** `21.0-20260614-UNOFFICIAL-arm64_bvN` — LineageOS 21, Android 14, SDK 34, **userdebug**, bootloader unlocked (`verifiedbootstate=orange`), **no Google Play Services**, no speech recognizer, WebView 149.0.7827.114 |
| Address | `10.89.1.154` on the house Wi-Fi (`wlan0`). Tailscale node `trebledroid-vanilla` = `100.95.199.28` (installed, signed in, **offline** at the time of writing) |
| adb | `adb connect 10.89.1.154:5555` — wireless adb is **persistent across reboots** (`persist.adb.tcp.port=5555`). No pairing, no cable. The shell is `uid 2000 (shell)`; `adb root` is available on a userdebug build but restarts adbd |
| The station | `http://10.89.1.246:8096` (host `lilspark`, a DGX Spark; tailnet `100.74.95.59` / `lilspark.tail1fec29.ts.net`). Public listener door `:8097`. SSH `ehm_eckx@10.89.1.246` |
| What is on it (third-party) | `com.pinebox.kiosk` (ours: the terminal, three launcher entries), `fm.pinebox.jackfix` (ours: a platform-signed overlay on `android`, inert), `com.tailscale.ipn` |
| What the kiosk is | One Android WebView showing the station's own control panel, with the station's view code **injected from the APK's assets**, a JS bridge (`window.pineDesktop`) into native Kotlin, a native Oboe sampler, and a handful of background services |
| Ports the kiosk opens on the tablet | **TCP `127.0.0.1:8096`** (a loopback byte relay to the station, WebView-only) and the abstract unix socket **`pine_camera`**. Nothing on `0.0.0.0`; adbd on `*:5555` is the system's |
| Is it locked down? | **Not today.** No device owner is set, lock task is `NONE`, the HOME resolver is `com.android.launcher3` (the stock launcher). The kiosk *declares* HOME and *would* pin itself if it were device owner; it is not. A person can leave it with the Home button and open Settings — and was doing exactly that while this was written |
| Deploying to the kiosk | `C:\_tools\pinebox-android\PineBoxKiosk\deploy.sh` — **only** that. It platform-signs. A plain `gradle assembleDebug` + `adb install` silently kills the headphone jack (§0.8) |
| Deploying your own app | `adb -s 10.89.1.154:5555 install -r your.apk` — any signature. Nothing the kiosk does stops you (§0.6) |
| Talking to the station | Plain HTTP, poll-only, no WebSockets, no CORS. Reads need no key on the LAN today; writes need `Authorization: Bearer <key>`, and the key is printed in the page served at `/` (§0.9) |

## 0.2 Reaching the tablet

### 0.2.1 adb

There is **no `adb` on `PATH`** in the tool shells on the Windows box. Two
copies exist and both are 37.0.1:

```
C:\_tools\platform-tools\adb.exe               <- the one the desktop app resolves to
C:\_tools\android-sdk\platform-tools\adb.exe   <- the one deploy.sh and the toolchain manifest use
```

Either works. Every command below assumes:

```sh
ADB=/c/_tools/platform-tools/adb.exe          # Git Bash
D="-s 10.89.1.154:5555"                       # ALWAYS pass -s
$ADB connect 10.89.1.154:5555                 # "already connected" is fine
$ADB devices -l
#   10.89.1.154:5555  device product:lineage_arm64_bvN model:TrebleDroid_vanilla device:tdgsi_arm64_ab
```

`-s` is not optional. Once the tablet is on both USB and Wi-Fi adb has two
transports for one device and refuses every untargeted command with
*"more than one device/emulator"*.

Wireless adb survives a reboot because `persist.adb.tcp.port=5555` was set
(§8). If it ever does not answer: a USB cable and `adb tcpip 5555`, or
Android's own Wireless debugging pairing (`adb mdns services` lists the
pairing port; the six-digit code comes off the tablet's screen). `adb root`
restarts adbd and, on the TLS road, changes the port — reconnect afterwards.

The station can also find it without adb: `GET /api/tablet/look` on the
station answers whether the tablet has fetched the show lately, whether its
address is in the ARP table, and whether port 5555 answers, and
`POST /api/tablet/doctor/sweep` walks the /24 for a tablet whose lease moved
(§0.9.6). The desktop's tablet doctor (§0.10) walks those rungs and then
does the one thing the station cannot — `adb connect`.

### 0.2.2 The pid trap, and the devtools socket

```sh
$ADB $D shell pidof com.pinebox.kiosk          # INTERMITTENTLY EMPTY while the app is running
```

`pidof` and `ps -A | grep pinebox` both return nothing at random on this
device (it happened again on 2026-09-14 while writing this, twice in a row,
against a kiosk that was on screen). Never trust one attempt; loop, or take
the pid from somewhere else:

```sh
# the WebView's DevTools socket names the pid, and it is reliable:
SOCK=$($ADB $D shell "cat /proc/net/unix" | tr -d '\r' | grep -o "webview_devtools_remote_[0-9]*" | head -1)
P=${SOCK#webview_devtools_remote_}
# or the app's own boot line:
$ADB $D logcat -d | grep "panel up in" | tail -1     # field 3 is the pid
```

Note the `tr -d '\r'` — adb's shell output arrives with CRLF on Windows and
a `\r` inside a grep pattern silently matches nothing.

### 0.2.3 Seeing and touching the screen

```sh
$ADB $D exec-out screencap -p > now.png            # 1340x800, ~100 KB, does not disturb anything
$ADB $D shell "dumpsys window | grep mCurrentFocus" # who actually has the screen
$ADB $D shell "cmd statusbar collapse"             # a pulled-down shade looks exactly like a hang
$ADB $D shell input tap 670 400                    # display coordinates, landscape, integers only
$ADB $D shell input swipe 100 400 1200 400 250     # x1 y1 x2 y2 ms
$ADB $D shell input swipe 670 400 670 400 600      # a same-point swipe held 600 ms is a long press
$ADB $D shell input keyevent KEYCODE_WAKEUP        # the WebView cannot wake the tablet; the framework can
$ADB $D shell input keyevent KEYCODE_SLEEP
$ADB $D shell input text 'hello%sworld'            # %s is input's space escape
```

Coordinates are the display's, in the orientation you are looking at
(1340×800). `input` accepts **integers only** — a decimal fails with a usage
message that goes nowhere, which looks like a dead spot on the screen. The
raw touch panel reports its axes in **portrait** (0–799 by 0–1339);
`sendevent` would need the rotation undone by hand and is also the slowest
road (measured: a held `adb shell` writing `input` lines is 42 ms per tap,
a fresh `adb shell input tap` is 127 ms, raw `sendevent` is 161 ms). Keep a
shell open and write lines to it — that is what `desktop/tablet-input.cjs`
does.

Video of the screen: `screenrecord` works, and the kiosk itself already
holds a rolling 20-minute H.264 ring of the whole screen (§0.5.9), so for
"what just happened" ask the kiosk rather than starting a second encoder.

```sh
# a live MJPEG mirror, exactly the pipe the desktop uses (needs ffmpeg on the PC):
$ADB $D exec-out "screenrecord --output-format=h264 --size 670x400 --bit-rate 2948000 -" \
  | ffmpeg -hide_banner -loglevel error -f h264 -r 30 -i pipe:0 -r 15 -q:v 6 -f mjpeg pipe:1 > live.mjpg
```

The `-r 30` *before* `-i` is load-bearing: the usual low-latency flags
(`-probesize 32 -analyzeduration 0 -fflags nobuffer`) produce **zero frames**
against screenrecord's raw H.264. Sizes must be even; the encoder refuses
an odd width and blames nothing in particular. Do not pass `--time-limit` —
the cap has moved between Android versions; rebuild the pipe when it ends.

### 0.2.4 Inside the WebView — Chrome DevTools over adb

The kiosk is a debug build and `PineApp` turns on
`WebView.setWebContentsDebuggingEnabled(true)`, so the Chrome DevTools
Protocol is reachable over an adb forward. This is the single most useful
tool for the tablet, far better than screenshots for "why is it blank".

```sh
SOCK=$($ADB $D shell "cat /proc/net/unix" | tr -d '\r' | grep -o "webview_devtools_remote_[0-9]*" | head -1)
$ADB $D forward tcp:9222 localabstract:$SOCK
curl -s http://127.0.0.1:9222/json           # -> [{type:"page", url:"http://127.0.0.1:8096/", webSocketDebuggerUrl:...}]
```

Node 22+ has a built-in `WebSocket`, so no package is needed. This script
was run against the live tablet on 2026-09-14 and is the whole client:

```js
// cdp-ask.mjs — evaluate one JS expression in the kiosk's WebView.
//   node cdp-ask.mjs 9222 'document.title'
const [port, expr] = process.argv.slice(2);
const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = pages.find(p => p.type === 'page' && /127\.0\.0\.1:8096|10\.89\.1\.246/.test(p.url)) || pages[0];
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate',
  params: { expression: expr, awaitPromise: true, returnByValue: true, userGesture: true } }));
const msg = await new Promise(r => ws.onmessage = e => r(JSON.parse(e.data)));
console.log(JSON.stringify(msg.result?.result?.value ?? msg.result?.exceptionDetails ?? msg, null, 1));
ws.close();
```

`userGesture: true` matters: without it `play()` on an audio or video
element is refused. `awaitPromise: true` lets you evaluate `await
pineDesktop.get('/api/dj')` directly.

What that call returned on 2026-09-14, and what each line tells you:

```
href          http://127.0.0.1:8096/          <- the panel is loaded through the loopback door, NOT from 10.89.1.246 (§0.5.5)
isSecureContext  true                         <- which is the whole reason for the door
userAgent     Mozilla/5.0 (Linux; X11; TrebleDroid vanilla Build/UQ1A.240205.004) ... Chrome/149.0.7827.114 Safari/537.36 PineBoxKiosk/1.0.0
              ^ NOT "Android" - the kiosk rewrites its UA. Key a tablet check on "PineBoxKiosk" or "!Electron && Linux", never on /Android/
innerWidth x innerHeight   1154 x 690   devicePixelRatio 1.25   (TARGET_CSS_WIDTH 1150 + minimumFontSize 12, §9)
pineSampler.backend        "oboe"       <- the NATIVE sampler, not Web Audio (§0.5.8)
localStorage.pineLastView  "script"     <- the rail reopens the last view at boot
rail tabs (right edge, top to bottom)   TECH SAMPLER SCRIPT LISTEN MUSIC PRESENT SLIDES 3JS SC CORNERS CAM FIND-CAM ENDLESS
```

Three rules for CDP on this tablet, each learned the hard way (§15, §19):

- **Injected JS never enters the DOM.** The kiosk hands each asset to
  `evaluateJavascript`, so grepping `document.documentElement.innerHTML`
  for a function you just shipped finds nothing and proves nothing. CSS
  *does* land (a `<style>` tag), and so do the globals — test `typeof
  window.PineYourThing`, or call it.
- **A container restart reloads the page and changes the CDP target id.**
  A watcher holding the old `ws://…/page/<id>` goes silently blank. Re-read
  `/json` after any restart.
- **The rail tab toggles.** Clicking a tab whose view is open closes it. A
  view is built lazily on first press, so `getElementById` for its content
  is `null` until then; open it by clicking the rail child whose
  `textContent` matches, not by calling `mount()` without a host.

The desktop app keeps its own DevTools door on **port 9333** (`terminal-glass.cjs`),
deliberately not 9222, "the port a person debugging by hand will already have
taken". Forward whichever you like; they do not conflict.

### 0.2.5 Logs

```sh
$ADB $D logcat -d -s PineKioskActivity PineBridge PinePanel PineKiosk PineAudio PineBoot \
    PineLoopDoor PineJack PineNet PineReplay PineRecorder PineCameraSvc PineWallpaper \
    PineMic PineAirTap PineMediaFocus PineRevive PineSpark DgxTerminal
$ADB $D logcat -d | grep -E "relaunch: com.pinebox.kiosk|ANR in"     # the two lines that explain a lost view
```

`/data/anr` keeps **old** traces; check the date before blaming one.

## 0.3 What is on the tablet, and what is running

Read off the live device on 2026-09-14 21:40.

### 0.3.1 Packages, components, launcher entries

```
pm list packages -3
  com.tailscale.ipn        1.102.4     the tailnet client (VPN consent + sign-in were done by hand; always_on_vpn_app=com.tailscale.ipn, lockdown OFF)
  fm.pinebox.jackfix       1.0         a platform-signed RRO overlay targeting `android` ([x] enabled) - one of the five dead roads to the jack (§8); harmless, inert, could be removed
  com.pinebox.kiosk        1.0.0       the terminal. versionCode 1, minSdk 30, targetSdk 34, DEBUGGABLE, LARGE_HEAP, signed b4addb29 (the platform key)
```

The kiosk's components (`dumpsys package com.pinebox.kiosk`):

| component | exported | what it is |
|---|---|---|
| `.MainActivity` | yes — MAIN/LAUNCHER **and** MAIN/HOME/DEFAULT | the terminal. `singleTask`, `showWhenLocked`, `turnScreenOn`, `fullSensor` |
| `.SparkActivity` | yes — MAIN/LAUNCHER, its own `taskAffinity` | "SC Stack": loads `/spark?pictures=1` in a plain WebView with the same bridge. Not a kiosk, Back leaves it |
| `.terminal.DgxTerminalActivity` | yes — MAIN/LAUNCHER, its own `taskAffinity` | "DGX Terminal": an SSH shell to `ehm_eckx@100.74.95.59` over Tailscale SSH. No keys stored (§12) |
| `.camera.PineCameraActivity` | **no** | full-screen camera preview on the tablet's own glass |
| `.camera.PineCameraService` | **no** | foreground service (`camera`); listens on abstract socket `pine_camera`; opens the lens **only while a client is connected** |
| `.replay.PineAppRecorder` | **no** | foreground service (`specialUse`): the rolling screen recording (§0.5.9) |
| `.kiosk.BootReceiver` | yes | `BOOT_COMPLETED`, `QUICKBOOT_POWERON`, `com.htc.intent.action.QUICKBOOT_POWERON` → applies owner policies, starts the recorder and camera service, launches MainActivity |
| `.kiosk.PineDeviceAdminReceiver` | yes, `BIND_DEVICE_ADMIN` | the device-owner hook. **Not currently the owner** |
| `androidx.core.content.FileProvider` `com.pinebox.kiosk.clipboard` | no | `cache/clipboard/` — how `copyImage` puts a PNG on the clipboard |

Launcher activities on the tablet (`query-activities … LAUNCHER`): Settings,
Jelly (`org.lineageos.jelly`, the browser), the three kiosk entries above,
Tailscale. There is also `org.lineageos.glimpse` (gallery), `documentsui`,
and the AOSP camera extensions — no Google camera, no Play Store.

### 0.3.2 The kiosk's grants

`deploy.sh` prints these after every install; they are what a platform
signature buys:

```
android.permission.MODIFY_AUDIO_ROUTING   granted=true   signature|privileged - the jack (§8)
android.permission.DUMP                   granted=true   signature|privileged - reads `dumpsys input` for the cable
android.permission.CAPTURE_AUDIO_OUTPUT   granted=true   signature - AirTap (REMOTE_SUBMIX), OFF unless asked
android.permission.CAPTURE_VIDEO_OUTPUT   granted=true   signature - a VirtualDisplay mirror of the WHOLE screen, no projection dialog
android.permission.CAPTURE_SECURE_VIDEO_OUTPUT granted=true  (this display carries FLAG_SECURE)
android.permission.RECORD_AUDIO           granted=true   runtime - the talk dot; re-granted by deploy.sh after an uninstall
android.permission.CAMERA                 granted=true   runtime - same
android.permission.POST_NOTIFICATIONS     granted=false  (never asked; the two foreground services run at IMPORTANCE_MIN)
plus: INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, RECEIVE_BOOT_COMPLETED, SET_WALLPAPER, WAKE_LOCK,
      MODIFY_AUDIO_SETTINGS, FOREGROUND_SERVICE, FOREGROUND_SERVICE_CAMERA, FOREGROUND_SERVICE_SPECIAL_USE
```

If `MODIFY_AUDIO_ROUTING` or `DUMP` ever read `granted=false`, somebody
installed a debug-signed build over the top. The app looks completely
normal; only the jack is dead. `./deploy.sh` cures it.

### 0.3.3 Kiosk state — what "kiosk" currently means

Measured, not read from the manifest:

```
dumpsys device_policy      Enabled Device Admins (User 0): <empty>    -> NO device owner
dumpsys activity           mLockTaskModeState=NONE, mLockTaskPackages=<empty>
cmd package resolve-activity HOME   com.android.launcher3/.uioverrides.QuickstepLauncher   -> the stock launcher owns Home
pm list users              UserInfo{0:Owner}
settings screen_off_timeout 60000 ; stay_on_while_plugged_in 0
```

So today the kiosk is an ordinary foreground app that:

- holds `FLAG_KEEP_SCREEN_ON` / `FLAG_TURN_SCREEN_ON` / `FLAG_SHOW_WHEN_LOCKED`
  on its window (**not** a wake lock — `dumpsys power` shows the
  WindowManager's `SCREEN_BRIGHT_WAKE_LOCK` charged to uid 10212, plus
  `AudioMix` partial locks while sound plays; the kiosk itself acquires none);
- goes immersive and re-asserts it on every focus change;
- calls `startLockTask()` on every `onResume` — which without device owner
  is only *screen pinning*, and the measured state is `NONE`, so it is not
  even pinned;
- declares HOME, so the **first press of Home shows the chooser**; the
  operator has evidently chosen launcher3, or dismissed it. The Home button
  leaves the kiosk, Recents works, Settings opens;
- **would**, if made device owner (`dpm set-device-owner
  com.pinebox.kiosk/.kiosk.PineDeviceAdminReceiver`), pin HOME with
  `addPersistentPreferredActivity`, restrict lock task to its own package,
  **disable the status bar**, set `STAY_ON_WHILE_PLUGGED_IN=7`, and refuse
  every outbound link. `dpm set-device-owner` fails while any account exists
  on the device — and Tailscale's sign-in may count. Nobody has done it.

**Consequence for a second project:** nothing stops your app being launched,
foregrounded, or set as the default Home. Whether that stays true depends on
whether someone later provisions the device owner; check `dumpsys
device_policy` before assuming either way. If the kiosk *is* made owner,
your package must be added to `KioskController.applyOwnerPolicies`'s
`setLockTaskPackages` list or it will be blocked while the kiosk is
lock-tasked.

### 0.3.4 What runs in the background, always

| thing | started by | what it costs / does |
|---|---|---|
| `StationFeed` (Kotlin, OkHttp) | `PineApp` | **the one poller** of `/api/dj` every 4 s, playhead interpolated at 250 ms. Every native consumer reads its snapshot |
| `WallpaperWatch` | `PineApp` | every 5 min chooses the piece the station is selling (`selling_now`, else newest still in `/api/generations`) and hangs it on home + lock — but only when no view is on the glass (#1296, §19.2), because hanging it relaunches the Activity |
| `PineAppRecorder` + `ScreenReplay` | boot, and every `onResume` | a `VirtualDisplay` mirror of the **whole screen** into an H.264 ring: 0.5 scale, 12 fps, 600 kbps, **1200 s held in RAM**. Sleeps on `SCREEN_OFF`. No consent dialog (signature permission). **Your app's UI is in this ring while it is on screen** |
| `PineCameraService` | boot, and every `onResume` | the `pine_camera` socket. The lens is closed until a reader connects |
| `JackWatch` | `onResume` | every 2 s runs `dumpsys input`, reads `SwitchValues`, and *announces* the cable to the framework via reflection (`AudioManager.setWiredDeviceConnectionState`) because this GSI never notices it. The announcement lives in the framework and outlives the app (§8) |
| `LockWatch` | `onResume` | draws the kiosk's own lock screen (`lock.js`) over the keyguard on `SCREEN_OFF/ON/USER_PRESENT`. Not a keyguard replacement |
| `MediaFocus` | `onResume` | holds **`AUDIOFOCUS_GAIN`** (USAGE_MEDIA) while in front. Your app taking focus in the foreground works normally; the kiosk re-takes it on its next resume |
| `keepTimersAlive` | `onResume` | `webView.resumeTimers()` every 20 s from the main-thread Handler, because Android suspends the WebView's JS timers while rAF keeps firing (§19.3) |
| `Revive` + `deaf-watch.js` | the view | every 30 s compares "the bridge answers" against "a plain fetch does not"; two strikes → the app ends its own process and an `AlarmManager` relaunch fires ~2.5 s later. Five-minute rest, gives up after three in thirty minutes (§19.1) |
| `LoopDoor` | `MainActivity.load()` | the `127.0.0.1:8096` relay (§0.5.5) |
| `Reach` | `load()` | probes `/healthz` on the LAN, then the tailnet address, then the MagicDNS name; keeps the first that answers |

Memory at the time of the reading: 3,863 MB total, **353 MB free**. The
kiosk process, its WebView sandbox and `webview_zygote` are the three
processes that matter; load average has been measured at 25–27. Anything
you add runs beside that.

## 0.4 The network, from the tablet's side

| road | address | when |
|---|---|---|
| the LAN | `http://10.89.1.246:8096` | at home; tried first because Tailscale would route two machines on one switch through a userspace TUN |
| the tailnet | `http://100.74.95.59:8096` | from anywhere, once Tailscale is up on the tablet |
| MagicDNS | `http://lilspark.tail1fec29.ts.net:8096` | same, needs the tablet to accept Tailscale DNS |
| the public door | `http://<any of the above>:8097` | a second uvicorn in the same station process, allowlisted routes only, `Authorization` stripped, `?t=<share token>` is the only credential (§0.9.2) |
| SSH to the box | `100.74.95.59:22` (`SSH-2.0-Tailscale`) | the DGX Terminal app. The LAN's `10.89.1.246:22` is real OpenSSH and would want a password, so it is deliberately **not** offered |
| the Pine Cam | `192.168.1.254` (its own access point `H88_…`) | held by the DGX's spare USB radio, never by the tablet. The tablet only ever sees `/api/pinelink/frame.jpg` |

The kiosk's `network_security_config.xml` permits cleartext for exactly
`10.89.1.246`, `100.74.95.59`, `lilspark.tail1fec29.ts.net` (with
subdomains), `127.0.0.1` and `localhost`. **That policy is the kiosk's, not
the device's.** Your app ships its own; a plain `http://` to the station from
a targetSdk 34 app needs `android:usesCleartextTraffic="true"` or its own
domain-config, or the request is refused before a packet leaves and nothing
in the failure says so.

Everything the panel needs resolves **relative** to whatever origin it was
loaded from — the served page contains no absolute `http://10.89.1.246:`
references and media arrives as `/sfx/<id>?t=…`, `/music/<id>?t=…` — so the
same page works over any road with no station change.

## 0.5 Anatomy of the kiosk

Source: `C:\_tools\pinebox-android\PineBoxKiosk` on the Windows box — a git
repository on branch `main` (an older note in this project's memory said it
was not; it is). It is on local disk on purpose: gradle refuses a UNC
working directory outright. Two source roots:
`app/src/main/java/com/pinebox/kiosk/` (the app) and
`app/src/main/kotlin/fm/pinebox/kiosk/audio/` (the sampler's JNI class —
its package must match what `cpp/android/jni_bridge.cpp` exports,
`Java_fm_pinebox_kiosk_audio_PineSampler_*`, and JNI resolves by class
package, which need not match the application id).

### 0.5.1 One Activity, one WebView, and four document-start injections

`MainActivity.load()` runs, in order: show "Reaching the station…" → read
the config → `Reach` probes the roads → `Readiness.take()` records what the
terminal confirmed about itself → `LoopDoor.open(base)` → `webView.loadUrl("$load/")`
where `load` is the door's origin (`http://127.0.0.1:8096`) or the station's
if the door would not open.

Before the page runs, `WebViewCompat.addDocumentStartJavaScript` registers,
in this order (registration order is evaluation order):

1. `assets/pine-bridge.js` — builds `window.pineDesktop` over `window.__pineNative`
2. `assets/pine-touch.js` — `touch-action` fixes so three.js canvases get their drags and taps lose the 300 ms delay
3. `assets/tablet.css` (as a style injector, id `pine-tablet-css`) — the 9-inch layout; its `@media (max-width: 1250px)` **must stay above `TARGET_CSS_WIDTH` (1150)** or every rule silently switches off
4. `assets/pine-media-origin.js` — measured 38 in-flight requests producing a 46 s media stall; records the lesson and does not move media to `:8097` (cross-origin media produced no audio track in this WebView)
5. `PineSamplerBridge.SHIM_JS` — `window.pineSampler` over the native engine (only if the `.so` loaded)
6. `BootAssets` — the logo, the splash, `pine-boot/boot-sequence.js`, and `vendor/three.min.js` handed over as a string

Then, at `onPageFinished`, `ViewAssets` and `SamplerAssets` are evaluated:
every file in `SCRIPTS` concatenated and handed to `evaluateJavascript`,
every file in `STYLES` concatenated into one `<style>`. A file that fails to
parse throws the whole bundle — the guard logs `[pine] views failed` and
**nothing is injected**.

`ViewAssets.SCRIPTS`, in evaluation order (models before the views that read them, `rail.js` near the end because it looks for the globals the others define):

```
pine-logo.js  boot-splash.js  pine-dismiss.js  view-chrome.js  console-line.js  console-trace.js
audio-law.js  talk-dot.js  vote-arrows.js  listen-model.js  pine-meters.js  script-lineage.js
script-stage.js  script.js  script-page.js  listen.js  music.js  wall-transition.js  video-wall.js
presentation-source.js  presentation.js  busy.js  three-full.js  line-deep.js  line-actions.js
sfx-tv.js  clip-doctor.js  pine-cam.js  lock.js  spark-overlays.js  slideshow-source.js
slideshow.js  deaf-watch.js  rail.js  hot-corners.js
```

`ViewAssets.STYLES`: `view-chrome boot-splash console-trace script script-page listen-music presentation lock vote-arrows line-actions sfx-tv clip-doctor pine-cam three-full busy slideshow spark-overlays hot-corners` (all `.css`).

`SamplerAssets.SCRIPTS` (a separate bundle with its **own copies** of shared files): `lcd-dialogue sampler-engine sampler-feed sampler-air sampler sampler-trim sampler-face sampler-grab sampler-kits sfx-tv deaf-watch` (+ `boot.js`, `sampler.css`, `sfx-tv.css`). Also in `pine-sampler/` but not in that list: `pinetab-route.js` and `terminal-audio.js`, which are `desktop/pinetab-route.cjs` and `desktop/terminal-audio.cjs` self-publishing as `window.PineBroadcastTo` / the routing-table client, and `terminal-audio-client.js`, `view-chrome.js/.css`.

**Why two copies of every view exist.** The page is `http://127.0.0.1:8096`
and the assets are `file:///android_asset/`; the WebView refuses that
crossing, so the files cannot be referenced, only read and evaluated. The
same files also live in `spark-agent/desktop/renderer/` for the Electron
desk and are served from there at `/spark/asset/<name>` for `SparkActivity`.
A renderer edit on the share changes the desk within seconds (its hot
watcher) and **changes the tablet not at all** until copied into
`app/src/main/assets/` and shipped with `deploy.sh` (§0.8).

### 0.5.2 The rail (what the tabs are)

`rail.js` builds a fixed strip on the **right** edge (`#pineViewRail`,
z-index 2147483001; the left edge belongs to the app's native drawer). Each
view is a `position:fixed; inset:0` host, built lazily on first press, one
open at a time; TECH is the panel itself and closes whatever is open. Live
on 2026-09-14, top to bottom:

| tab | what opens | source |
|---|---|---|
| TECH | the station's panel, nothing over it | — |
| SAMPLER | the sampler page (16 pads × 5 banks, native oboe engine) | `pine-sampler/` |
| SCRIPT | the screenplay view: the running order, the player card, the mixer dot, the loop and search controls (§26–29) | `script-page.js` |
| LISTEN | lean-back radio | `listen.js` |
| MUSIC | the same feed from the record library's side | `music.js` |
| PRESENT | six panes off one poll | `presentation.js` |
| SLIDES | the ComfyUI output folder as a slideshow with the SC overlays (`docs/slideshow-tablet.md`) | `slideshow.js` |
| 3JS | every three.js experience full-screen | `three-full.js` |
| SC | the SC stack overlays as a floating pop-up | `spark-overlays.js` |
| CORNERS | hot-corner preferences (§0.5.11) | `hot-corners.js` |
| CAM / FIND CAM | the Pine Cam picture-in-picture, and its troubleshooter | `pine-cam.js` |
| ENDLESS | the SFX guy's endless video mode (§27) | `script-page.js` / `sfx-tv.js` |

`console-line.js` owns the bottom ~26 px of every screen; measure
`#pineConsoleLine` rather than drawing at `bottom:0`. The lock screen
(`lock.js`, `#pineLock`, z-index 2147483050) is drawn over the keyguard by the
kiosk itself; tap the X top-right (about 1274, 43) to reach the panel.

### 0.5.3 The bridge — `window.pineDesktop`

`bridge/PineDesktopBridge.kt` is `window.__pineNative` (five raw
`@JavascriptInterface` methods: `invoke(id, method, argsJson)` returning a
sync ack and settling later through `window.__pineBridgeSettle`, plus the
synchronous `micLevel()`, `copyText()`, `copyImage()`, `clipboardReady()`).
`assets/pine-bridge.js` hangs one function per method off
`window.pineDesktop`, mirroring `desktop/preload.js` name for name so the
same view code runs on both surfaces. Every method is a Promise except the
four synchronous ones and `micNative()` (returns `true`). Read off the live
page:

```
config      readConfig writeConfig
station     discoverKey get post put del          <- HTTP to the station through the APP's OkHttp client, not the WebView
shell       openExternal buildInfo
backend     startBackend stopBackend setupBackend reconstituteDesktop   -> resolve {ok:false, unsupported:true}
            backendLog (returns "") onBackendLog onSupportProgress
lcd*        15 names                                -> unsupported ("the LCD is wired to the box, not to this terminal")
terminal*   12 names                                -> unsupported ("this device is the terminal; it cannot provision itself")
readiness   readyReport
mic         micTake micChunk micStart micStop micCancel micState micLevel micNative
air tap     airStart airStop airState airSlice     <- REMOTE_SUBMIX capture of the system mix, 120 s ring; OFF unless asked
camera      cameraOpen cameraClose cameraTune cameraRange cameraShow cameraHide
replay      replayState replaySave replayChunk screenShot replayExport
corners     hotCorners hotCornersSet
files       keepClip saveText saveBytes
hardware    jack wallpaper
recovery    revive
usb / MPC   usbState usbPick usbSend usbList usbRead
clipboard   copyText copyImage clipboardReady     (synchronous booleans)
```

Refusals *resolve* with `{ok:false, unsupported:true}` — a rejection would
show as a crashed handler; a resolved refusal shows as "not available here".
Envelopes: ack `{"accepted":true,"id":"r1-…"}`; settle `{"id":…,"ok":true,"value":…}`
or `{"ok":false,"error":"401 from the station"}`.

**The bridge does not use the WebView's network.** `get/post/put/del` go
through OkHttp (connect 3 s, read/write 20 s, call 30 s; a slow client with
150 s read for the long roads; 600 s for uploads). This is why the feed keeps
painting when Chromium's own network stack is dead (§19.1), and why anything
that must not fail goes on the bridge. It is also why *"the tablet's bridge
gives up at 20 s"* is a number the station's routes are designed around.

**Adding a bridge method is three edits** and missing the third is the usual
bug: the name in `ASYNC_METHODS` in `PineDesktopBridge.kt` (dispatch), a
`"name" -> { … }` branch in the `when` (behaviour), and `name:
promised("name")` in `assets/pine-bridge.js` (exposure). Skip the shim line
and `pineDesktop.name` is `undefined` with no error anywhere.

The panel's own inline script calls only two bridge methods
(`clipboardReady`, `copyImage`) and reads one property
(`window.__pineDesktopVolume`). Everything else on the bridge is for the
injected views.

### 0.5.4 `PineNet` — two URL prefixes served by OkHttp, everything else by Chromium

`shouldInterceptRequest` handles **GET** on `/vendor/*` (three.js from the
APK, `X-Pine-Source: apk`) and `/api/generations/image/*` (fetched by OkHttp,
re-encoded to WebP ≤768 px, 256 MB disk cache, 4 lanes). Everything else —
media Range requests, POSTs, the API polls — returns `null` and goes through
the WebView. Consequence: **images keep loading while the WebView's network
is dead**, which is the diagnostic for §19.1.

### 0.5.5 `LoopDoor` — why `location.origin` is `http://127.0.0.1:8096`

A raw TCP byte relay bound to **`127.0.0.1:8096` on the tablet** (ephemeral
loopback port if 8096 is taken), aimed at whichever road `Reach` chose. It
parses nothing. It exists because `BaseAudioContext.audioWorklet` is gated on
`isSecureContext`, the panel is plain http, no certificate is obtainable for
a LAN address that is also reached over a tailnet, and the WebView's
`--unsafely-treat-insecure-origin-as-secure` flag never reached the renderer
(the command-line file *is* honoured on this `ro.debuggable=1` build; that
switch just does not work). Loopback is potentially trustworthy by spec.
Result: the sampler's air tap runs its AudioWorklet instead of a
main-thread ScriptProcessor that lost 17–23 % of its buffers.

It is **WebView-only**. The kiosk's OkHttp talks to the station directly.
Do not "improve" it into an HTTP proxy, and **do not bind `127.0.0.1:8096`
from your own app** — the door will fall back to a random port and keep
working, but you will have made the panel's origin unpredictable for
everyone debugging it.

### 0.5.6 Provisioning itself, and the station's key

`KeyDiscovery` does one unauthenticated `GET /` and lifts
`const SERVER_KEY = "…";` out of the page (same regex as Electron's
`discoverAgentKey`). The kiosk then sends `Authorization: Bearer <key>` on
every request. `ConfigStore` is a Preferences DataStore named
`pinebox-desktop` with keys `baseUrl apiKey mode port dataDir python
tailnetUrl tailnetName recordingFolder hotCornersOn hotCornerTl hotCornerTr
hotCornerBl hotCornerBr`; `writeConfig` writes exactly that list (a key not
on it appears to save and reads back the default — `tailnetUrl` and
`recordingFolder` were lost that way once). `BuildConfig` carries the three
default roads.

### 0.5.7 Audio: focus, the jack, the mic, the graph

- **Focus.** `MediaFocus` requests `AUDIOFOCUS_GAIN`; `DuckController`
  takes `AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK` while a pad rings.
  `OutputRoute` only *listens* to route changes (to reopen the oboe stream);
  it never forces a route.
- **The jack** is announced by the app, not the framework (§8). Audio on
  `headset(4)` with no cable is a stale announcement, and audio on
  `headset(4)` *is* usually correct here because a cable runs to a bigger
  system — ask before "restoring" the speaker. On 2026-09-14 the route read
  `speaker(2)`.
- **The mic** is `AudioRecord` at 16 kHz on `MIC` (`VOICE_RECOGNITION` is
  dead on this device: 0.0004 against 0.63). There is no speech recognizer on
  the GSI, so the clip goes to the station's `POST /api/listen/transcribe`
  (wyoming-whisper). `onPermissionRequest` grants the page **audio capture
  only**; the camera is never granted to the page.
- **The Web Audio graph** belongs to the panel: `window.pineAudioCtx`,
  `audioScope(el)` (one analyser per element, memoised; a second
  `createMediaElementSource` on the same element **throws**), `gainFor()`,
  ducking `music × (1 − duck)` while `djSpeaking`. Anything wanting levels
  borrows the analyser. Players are built with `new Audio(url)` and never
  enter the DOM. The `<audio>` volume setter is clamped page-wide because
  the desk's 160 % voice slider threw `IndexSizeError` on the tablet and
  silenced the DJs (§8).

### 0.5.8 The native sampler (oboe)

`app/src/main/cpp/` builds `libpinebox_sampler.so` (core: `engine mixer pad
voice duck analysis window sample_buffer audio_format`; android: `jni_bridge
media_decode oboe_output`; Oboe 1.9.0 via FetchContent or vendored at
`cpp/third_party/oboe`; NDK 26.1.10909125, CMake 3.22.1, `-std=c++17
-fno-finite-math-only`, `c++_shared`, arm64-v8a only). `PineSampler.kt`
declares the `external fun`s (the README's "the JNI binding is still
missing" is stale — it exists), `PineSamplerBridge` is `window.PineSamplerNative`
(all synchronous: `beginLoad/pushChunk/finishLoad`, `fire/release/stopPad/stopAll`,
`peaks/zeroCross/levels/footprint`, `setFastPads/claimFire/fastState`, …),
and the shim publishes `window.pineSampler` with `backend === "oboe"`.
`sampler-engine.js` (Web Audio) still loads as `window.PineSamplerEngine` —
it is what the *desktop* uses and what provides an `AudioContext` here; its
pads are unused on the tablet. Two features once shipped broken by being
added to the Web Audio engine only; keep per-voice bookkeeping in the view.

The oboe stream asks for `SharingMode::Exclusive` + `LowLatency`; `onPause`
calls `PineSampler.sleep()` to hand the exclusive AAudio port back, which is
what lets **another app in front open a low-latency stream**.

### 0.5.9 The screen recorder and the camera

`ScreenReplay` mirrors the real display into an encoder through a
`VirtualDisplay` with `VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR | FLAG_SECURE` — no
`MediaProjection`, no consent dialog, because `CAPTURE_VIDEO_OUTPUT` is
signature-granted. `PineAppRecorder` keeps it alive as a foreground service
(notification 4301, `pine-recorder`, `IMPORTANCE_MIN`), started at boot and
at every `onResume`, resting on `SCREEN_OFF`. The hot corners (§0.5.11) and
the desk's "reach backwards" clip both read this ring
(`pineDesktop.replayState/replayExport/replayChunk`).

`PineCameraService` (notification 4302, `pine-camera`) listens on the
abstract unix socket **`pine_camera`** from boot. A connection opens the
lens; the last disconnect closes it. Wire format is **4-byte big-endian
length + JPEG**, not marker-scanned, because an ImageReader's JPEG carries an
EXIF thumbnail that is itself a JPEG and a marker scan stops at its end.
From a PC:

```sh
$ADB $D forward tcp:9999 localabstract:pine_camera
# connect to 127.0.0.1:9999, read [u32be len][jpeg] frames; the lens is on while you are connected
```

If the desktop app has its camera window open, the same frames are already
on **`http://127.0.0.1:8791/camera.mjpg`** and **`/camera.jpg`** on the PC
(loopback only, fixed port so OBS / ComfyUI / a browser can be pointed at
it). The desk's *screen* mirror, by contrast, listens on an OS-assigned
loopback port that must be read out of `pineDesktop.mirrorHow()`.

### 0.5.10 Wallpaper, lock screen, USB, DGX terminal, Spark

- `WallpaperWatch` — every 5 min, `selling_now` from the feed else the newest
  still in `/api/generations?limit=N` (newest-first; filter `.mp4/.webm`
  out), centre-cropped, onto `FLAG_SYSTEM` and `FLAG_LOCK` in two calls.
  Hanging it raises `CONFIG_ASSETS_PATHS` (0x80000000), which has no name in
  `configChanges` and relaunches the Activity — so it is held until
  `onPause` (§19.2).
- `LockWatch` + `lock.js` — the station on the lock screen: clock, now
  playing, the screenplay (45 s rest), the slideshow (30 s rest), the request
  box, the talk dot. Zero extra polls of `/api/dj`.
- `UsbBrowse` / `UsbTarget` — browse and write a USB stick (an MPC) through
  the Storage Access Framework (`ACTION_OPEN_DOCUMENT_TREE`). MediaStore
  renames a file whose extension disagrees with its MIME; use
  `application/octet-stream` when the extension matters.
- `DgxSsh` — `com.github.mwiede:jsch 0.2.18`, `PreferredAuthentications
  none,publickey`, no key on the tablet: Tailscale SSH authorises on tailnet
  identity. Reads the banner first and refuses anything that is not
  `SSH-2.0-Tailscale`. Writes on one thread (`dgx-ssh-write`), because a
  socket write from the key callback is `NetworkOnMainThreadException` and
  the failed write left JSch closed for good (§12).
- `SparkActivity` — loads `/spark?pictures=1`; everything it shows is served
  from `desktop/renderer/` on the station, so an overlay edit reaches it on
  its next launch with **no APK in the loop**. It pads for the system bars
  instead of hiding them: an app you are meant to leave should not hide the
  button you leave with.

### 0.5.11 Hot corners

`hot-corners.js` (in `ViewAssets` last; `CORNERS` rail tab; 40 KB — an
earlier reading of this file as a 129-byte stub was a parallel session
mid-copy). A primary pointer down inside a 110 px corner square, ≥150 px
toward the centre within 35° of the diagonal, inside 1.5 s, one finger;
only a committed swipe is swallowed. Defaults (`HotCornerPrefs`): top-left
**shot** (screenshot → red-ink markup → the Pine inbox), top-right
**export** (the last 5 s … 20 min of the screen ring to the recording
folder), bottom-left **inspect** (the line on air and how it came to be),
bottom-right **sfx** (replay the last sting); `off` and `report` are the
other actions. Bridge: `screenShot`, `replayState`, `replayExport({seconds,
upload})`, `hotCorners`, `hotCornersSet`; the Kotlin side calls
`window.PineHotCorners.configure(cfg)` on load and on every change.

### 0.5.12 Numbers the kiosk is tuned to

```
StationFeed.POLL_MS 4000   TICK_MS 250           "Do not shorten POLL_MS."
TARGET_CSS_WIDTH 1150 -> initial scale = widthPx*100/1150, clamped 75..400  (134% here); minimumFontSize 12
tablet.css breakpoint max-width:1250px         must stay above TARGET_CSS_WIDTH
TIMER_GUARD_MS 20000       RETRY_MS 4000 (main-frame load failure)
Revive: REST_MS 5 min, GIVE_UP_AFTER 3 in RUN_WINDOW_MS 30 min, relaunch delay ~2.5 s (900 ms lands inside the dying process)
deaf-watch EVERY_MS 30000, two strikes
JackWatch POLL_MS 2000, SW_HEADPHONE_INSERT bit 2 (SwitchValues 4 = in)
ScreenReplay: SCALE 0.5, FPS 12, BITRATE 600000, HOLD_SECONDS 1200
AirTap HOLD_SECONDS 120     MicCapture RATE 16000
PineNet: MAX_EDGE 768, WEBP_QUALITY 80, LANES 4, cache 256 MB; OkHttp 16 per host
WallpaperWatch EVERY_MS 5 min
z-index bands: views 2147483000, rail 2147483001, trace console ...004, SC pop-up ...010, PiP ...020, sampler overlays ...030+, hold sheets ...046, lock ...050, view-chrome ...200
```

## 0.6 Putting your own app on the tablet

### 0.6.1 Install

```sh
$ADB $D install -r path/to/your.apk      # any signature; -r keeps data on a reinstall
$ADB $D shell am start -n your.package/.YourActivity
$ADB $D shell pm grant your.package android.permission.RECORD_AUDIO   # runtime grants, no prompt needed on a kiosk
```

Build for **arm64-v8a** (`abilist arm64-v8a,armeabi-v7a,armeabi` — 32-bit
runs too). `minSdk` up to 34 is fine. **Nothing may depend on
`play-services-*` or Firebase** — there are none, and a Play-dependent app
fails at first use, not at install. There is no `RecognitionService`, so
speech has to go to the station's whisper (§0.9.5). The device is
`userdebug`, so `adb shell` can `run-as` any debuggable package and
`adb root` is available if you need more.

You do **not** need the platform key unless you want signature-level
permissions (the jack, `DUMP`, screen capture without a projection). If you
do, the key is `PineBoxKiosk/keys/platform.pk8` + `platform.x509.pem` — the
AOSP test platform key this GSI's framework is signed with (`b4addb29`,
SHA-256 `c8a2e9bc…92ab8`), and you sign with `apksigner` after building
exactly as `deploy.sh` does. A platform-signed app is a system-trusted app;
`sharedUserId` is not needed and the kiosk does not declare one.

### 0.6.2 Coexisting with the kiosk

What the kiosk will and will not do to you, from its source and the live state:

| concern | today | if it is ever made device owner |
|---|---|---|
| Launching you | `am start`, the launcher, or a HOME chooser all work | lock task allows only `com.pinebox.kiosk`; add your package to `setLockTaskPackages` in `KioskController.applyOwnerPolicies` |
| Being Home | launcher3 is Home; you can be | the kiosk pins itself with `addPersistentPreferredActivity` |
| Status bar / Quick Settings | normal | disabled by policy |
| Audio focus | the kiosk holds `AUDIOFOCUS_GAIN` while in front; you take it normally when you are in front; it re-takes it on resume | same |
| Low-latency audio | the kiosk sleeps its exclusive oboe stream in `onPause`; yours can open one | same |
| Camera | the lens is **free** unless someone is connected to `pine_camera` or `PineCameraActivity` is up | same |
| Microphone | free unless a talk-dot take is in progress (`AudioRecord` on `MIC`) or the air tap is on | same |
| Screen recording | `ScreenReplay` is recording the **whole screen** at 12 fps whenever the display is on — including your app. It is RAM-only and rolls over after 20 min, but it is there | same |
| Ports | `127.0.0.1:8096` is the door — avoid it. `pine_camera` abstract socket — avoid the name | same |
| Network policy | yours is yours (`network_security_config` is per-app) | same |
| Wake / screen | the kiosk keeps the screen on only while its window is in front; behind you the 60 s timeout applies | `STAY_ON_WHILE_PLUGGED_IN` |
| Wallpaper | the kiosk repaints home + lock every 5 min while it is *not* on screen — i.e. while you are. Expect `CONFIG_ASSETS_PATHS` relaunches of *your* Activity too if you do not handle configuration changes; that flag cannot be declared away | same |
| Boot | `BootReceiver` launches the kiosk at boot. Yours can declare its own; whichever `HOME` wins decides what is on screen | the kiosk |
| Intents you can send it | `am start -n com.pinebox.kiosk/.MainActivity` (and `.SparkActivity`, `.terminal.DgxTerminalActivity`). `com.htc.intent.action.QUICKBOOT_POWERON` is an unprotected broadcast `BootReceiver` accepts — it would start the recorder and camera service and launch the kiosk; do not | same |
| Intents it can send you | **none**. There is no configurable intent, no bridge method that starts an arbitrary component. `openExternal(url)` is `ACTION_VIEW` on a URL (refused when device owner). The only other `startActivity` is the battery-saver settings page | same |
| Content you can read from it | nothing — the FileProvider is not exported; the DataStore is private | same |

**Ways to be reached *from* the kiosk**, in order of cost: (1) an `ACTION_VIEW`
intent filter on a custom scheme or an http host — the panel or a view can
call `pineDesktop.openExternal('yourscheme://…')` and, absent device owner,
`shouldOverrideUrlLoading` sends any non-station host out to the system
chooser (Jelly today; yours if you claim the host); (2) a new `ViewAssets`
entry and rail tab whose "view" is a button that calls a new bridge method
that does `startActivity(...)` — a kiosk change, §0.8; (3) `adb` from the
desk, which the desktop app already does for the kiosk kick. There is no
road that does not involve either the URL chooser or editing the kiosk.

**The cheapest correct shape for your own Activity** is the one
`SparkActivity` and `DgxTerminalActivity` already use: `MAIN`+`LAUNCHER`
only, your own `android:taskAffinity`, `launchMode="singleTop"` or
`singleTask`, `resizeableActivity="true"`, `screenOrientation="fullSensor"`,
the long `configChanges` list, **no HOME filter, no lock task**, and pad for
the system bars rather than going immersive. The station's panel is a
12,000-node document on a tablet measured at 148 MB free under a load of 25;
budget your own memory and CPU against that, and do not run a second
`/api/dj` poller at 4 s if you can read what the kiosk already fetched
(§0.7.3).

### 0.6.3 A WebView of your own

If your app is also a WebView on the station, three things measured here
will bite you within a day:

- **Chromium's per-origin socket pool is six.** The panel runs ~35 network
  pollers and was measured with 274 requests queued on `127.0.0.1:8096`,
  oldest 74 s. The station now shares identical in-flight GETs and aborts at
  8 s (`API_TIMEOUT_MS`) in the panel's own `api()`. Use a native HTTP
  client (OkHttp) for anything that must arrive; it never touches that pool
  — measured 15 native requests completing at 0 s during a fault where the
  WebView completed 21 in 75 s.
- **The WebView's JS timers freeze** while `requestAnimationFrame` keeps
  firing; the kiosk pokes `resumeTimers()` every 20 s from a Handler. Ride
  rAF for anything that must keep moving, and expect no web-side cure to
  reach a frozen timer.
- **The WebView's network stack wedges** (§19.1): the process keeps running,
  images through your own client keep loading, and every `fetch` and
  `<audio>` fails in 40–100 ms. A page reload hands the new page the same
  dead stack; only `am force-stop` cures it. The kiosk's `deaf-watch` +
  `Revive` is the shape of the cure: compare a native road against a
  WebView road, and end your own process.
- `isSecureContext` is false on `http://10.89.1.246`; AudioWorklet,
  `getUserMedia` and the clipboard API are gone with it. The loopback door
  is the only road that worked (§0.5.5).
- Key a tablet check on the UA string `PineBoxKiosk/…` or `!Electron &&
  Linux`, never on `/Android/` — the kiosk's WebView calls itself `Linux;
  X11; TrebleDroid`.

## 0.7 Talking to the station from the tablet

The station is `app.py` on the DGX (FastAPI, ~211,000 lines, 715 routes, one
process that is also recording a live radio show). It is **poll-only**:
there are no WebSocket routes, no `EventSource` in any page, and one SSE
route (`POST /v1/chat/completions` with `stream:true`). There is **no CORS
middleware**, so a browser page on another origin cannot XHR it; a native
client is unaffected. Responses are not gzipped; `/api/dj` is ~120 KB a
poll. §0.9 has the route inventory; this section is the contract for a
device that wants to *listen*.

### 0.7.1 Identity: the listener id, the roster, the `terminals` row

1. **Mint one id and keep it in persistent storage.** The panel mints
   `pb<8 base-36>` in `sessionStorage`, the Electron shell mints
   `desktop-<rand>`, the tune page mints a bare base-36 string. A fresh id
   per launch is why the air keeps changing hands (`AUDIO_OWNER_QUICK`
   exists to hand it back within 12 s). Prefix yours distinctly.
2. **Send it as `?listener=<id>`** on `GET /api/radio/clock` (every 1.5 s)
   and `GET /api/dj` (every 4 s, `&lean=1`). That is the whole registration —
   there is no join route; the roster entry is created by the poll and
   pruned after 30 s without one. `POST /api/dj/join {listener, name}` is
   the *social* hello (the DJs welcome you); it is optional.
3. **Ask the operator for a row** in `settings.terminals`, or write it
   yourself with the key. `GET /api/settings`, add
   `"yourdev": {"name":"…","play":true,"listener":"<your id>","addr":"10.89.1.154","fallback":false,"music":1.0,"voice":1.0,"reply":1.0}`,
   `PUT /api/settings` **the whole document back** — PUT replaces, and the
   validator rebuilds from a whitelist, so a partial PUT resets everything
   you omitted. A row that names a `listener` is matched by id first and is
   DHCP-proof; `addr` is the fallback. Sixteen rows max, key `[a-z0-9_.-]`,
   levels clamped 0–1, `play` defaults **false**. Every client reads the
   table and obeys its own row — that is how the tablet's volume is set
   from the desk. The live table on 2026-09-14:

   ```
   pinetab  play=true  addr 10.89.1.154  music .8 voice 1.0 reply 1.0  fallback=false
   desktop  play=true  addr 10.89.1.13   music .6 voice .6  reply .6   fallback=true
   ```

4. **Read the roster** at `GET /api/radio/listeners`:
   `{listeners:[{listener, seen, since, addr, what:"the desktop app"|"a browser tab", owns_air}], audio_owner, say}`.
   `what` is derived from `"Electron" in User-Agent` and nothing else — a
   native client, the kiosk, and a phone all read "a browser tab"; tell them
   apart by `addr` and by your id's prefix.

### 0.7.2 Who plays out loud — the air owner, and acking honestly

Only one player in the house may sound at once, or "the DJs overlap each
other" (one show three times, a few hundred milliseconds apart). The rule
is enforced by the **air owner**: `GET /api/radio/clock` carries
`audio_owner`; if it is non-empty and not your id, **mute**. `music_here ===
false` means the box has the record and you must not play a second copy.
`paused` means go quiet. Remote listeners through `:8097` are exempt (a car
is not in the room).

`POST /api/radio/solo {"listener":"<id>"}` (key required) hands one
listener the air and gags every other page; `{"clear":true}` releases it.
It refuses (HTTP 200 with `refused`/`why`) a device whose row says
`play=false`, and a device the station has judged **deaf**. Resolution
order in `audio_owner()` (app.py ~27782): a quiet owner (>12 s) whose
device is back under a new id hands over at once; a live owner is refused if
its row says `play=false` or if it has held the air 75 s having acknowledged
nothing audible (`OWNER_DEAF_SECONDS`, then refused for `OWNER_DEAF_REST` =
300 s); nobody → the first `play=true` row with a live listener,
non-fallback rows first.

**Acking is what "heard" means.** `POST /api/dj/voice/ack`:

```json
{"event":"received|canplay|playing|ended|error", "delivery_id":"<from the clip>",
 "listener_id":"<your id>", "sequence":3, "current_time":4.21,
 "volume":1.0, "audible_volume":1.0, "muted":false, "error":""}
```

`audible_volume > 0` on `playing`/`ended` is what sets the station's "the
dialogue was heard" mark. If you hold the air and ack silently (or never),
you lose it after 75 s and are refused for 300 s; if *nobody* acks audibly,
the unattended `AIR_LADDER` runs — relieve at 90 s, flush at 120 s, release
at 180 s, reload every page at 240 s, **restart the station process at 360
s**. A polite listener acks with the truth.

### 0.7.3 What to poll, how often, and what comes back

| route | cadence | bytes | what |
|---|---|---|---|
| `GET /api/radio/clock?listener=<id>` | **1.5 s** | ~0.5 KB | `server_ms started_ms on playing paused id music_here title seconds url art listeners audio_owner` — the record and the gate |
| `GET /api/dj?listener=<id>&lean=1` | **4 s** | ~120 KB full / less lean | everything: `station playing paused dj now elapsed queued build reload_at kiosk_kick coming on steward station_name dj_names remaining upcoming requests music_to voice_to output listeners history played last_said speaking speaking_now talk_next_in dialogue_flow chat stream_now selling_now gallery_now ad_now box pulse library activity activity_log airtime playback …`. `lean=1` drops `dialogue_flow last_said upcoming activity_log vector_access repair_log stream_now airtime playback history pipeline` and truncates `chat` to 20 |
| `GET /api/dj/voice?since=<ms>` | 4 s | small | `{server_ms, cut_ms, clips:[{broadcast_ms, delivery_id, delivery_state, engine, kind, speech, stream, text, ts, url, voice, who, …}], reservation_updates}`. Clips with `ts > cut_ms` are playable; a line is offered for `broadcast_ms − 7 s` lead and not past 45 s late |
| `GET /api/dj/video` | 2.5 s | small | `{clips, server_ms, cut_ms, endless}` — the SFX guy's picture. (Two handlers share this path; the first registered, `dj_video_api`, is live — parse `clips`, not `videos`) |
| `GET /api/pulse` | on demand | small | the event loop's stalls, worst, and the named blocking frame. **Read this before blaming your own client** |
| `GET /api/broadcast/health` / `/console` | on demand | | is anyone hearing it; the whole repair-step table and log |
| `GET /api/tablet/look` | on demand | | the tablet as the station sees it (§0.9.6) |

The panel itself runs the clock at 1.5 s, the DJ poll at 4 s, the voice
poll at 4 s, the video poll at 2.5 s, and ~35 other timers; the tune page
slows to 3 s / 8 s in stream mode. **Do not go faster.** One request in
flight per endpoint, with an 8–20 s deadline, and a single-flight latch that
only its owner clears (a latch cleared by a successor put the overlap back).

Rather than a second poller, a companion app on the same tablet can read
the kiosk's `StationFeed` snapshot only by living inside the kiosk (there is
no content provider). From outside, poll — at the cadences above.

### 0.7.4 Playing sound

- **Clip road (what the panel does):** poll `/api/dj/voice`, fetch each
  clip's `url` exactly as given (it carries `?t=<HMAC sig>`; you cannot mint
  it without the key), start it at `broadcast_ms`, ack. Music is
  `/music/<id>?t=…` from the clock, with `/music/<id>/art`. Optional
  `&br=32|48|64|96|128` picks a lower-rate derivative — a whitelist, not a
  clamp, and a `(key, rate)` that once served the original keeps serving it
  for 900 s.
- **Stream road (simpler, ~30 s behind live):** `GET /stream.mp3?t=<share token>`
  — endless mp3, 32–192 kbps via `?br=`, ICY metadata on `Icy-MetaData: 1`,
  30 s join burst so the first packet has audio, never closes (a paused
  station is fed silence). `/stream.m3u8` + `/hls/<rate>/segNNN.ts` for HLS
  (4 s segments, 8 in the list; iOS wants this). `?split=1` sends the
  record on the left and the DJs on the right so a client can balance them
  instantly with its own gains — opt in only if you will un-split it.
  `GET /api/stream/state` reports `listeners bitrate rates hls_rates
  up_seconds produced_seconds underruns holes …`. The mixer's format is
  s16le stereo 44.1 kHz in 100 ms frames.
- The share token: `POST /api/share {"hours":168,"label":"…","scope":"listen"}`
  (key required) → `{token, url, expires}`; the URL is `/tune/<token>` and the
  token is what `?t=` wants on every `require_listen_auth` route. A `full`
  scope token opens the real panel and is accepted as a bearer.

### 0.7.5 Sending things in

| what | route | gate | body |
|---|---|---|---|
| a song request | `POST /api/dj/request` | listen token or key | `{q, now?}` — 400 "Name a song", 404 no match |
| a shout or a react | `POST /api/dj/shout` | listen | `{who≤32, text≤280}` or `{react≤8}`; text spawns a banter round so the DJs answer on air |
| a vote | `POST /api/music/vote` | listen | |
| wake a paused station | `POST /api/radio/unpause` | listen | one-way: a guest may only wake it |
| speech to text | `POST /api/listen/transcribe` | **key** | raw WAV/PCM bytes, 2 kB–12 MB → `{text, heard}` (+`detail, bytes` when empty) |
| a spoken call-in | `POST /api/dj/callin/voice?rate=16000` | key | raw 16-bit mono PCM ≥3,200 bytes → a request or a call-in |
| a request to the operator | `POST /api/pine-requests` | key | `{text, debug:true, images:[dataurl…], files:[…]}` → the inbox (`data/pine_requests.md`). Identical text within 30 min folds into the open request; `debug` (absent = true) appends a "Station at the time" block. Read it back with `GET /api/pine-requests`; `POST …/{id}/resolve {reply}` closes it |
| a report from a view with a picture | `POST /api/script/report` | key | `{view, text≤20000, image, reason≤1200}` |
| a line to the LLM / the inbox by dictation | `POST /v1/chat/completions` | key | OpenAI-shaped; inbox dictation outranks the model and answers as `"model":"pine-inbox"` |
| a broadcast recording | `PUT /api/export/upload?name=&what=&seconds=` | key | bytes; how the kiosk's air tap hands a slice to the station |

## 0.8 Contributing to the kiosk itself

### 0.8.1 The toolchain

```
C:\_tools\jdk17                 Temurin 17.0.20.1
C:\_tools\android-sdk           platforms/android-34, build-tools/34.0.0, ndk/26.1.10909125, cmake/3.22.1, platform-tools 37.0.1
C:\_tools\gradle                gradle 8.14.5  (the project pins AGP 8.5.2, Kotlin 1.9.24; there is NO gradle wrapper JAR checked in)
C:\_tools\_gradlehome           GRADLE_USER_HOME - without it AGP re-downloads from scratch and the build "hangs" for minutes
C:\_tools\pinebox-toolchain.json   the manifest desktop/android-build.cjs reads; written by PowerShell WITH A UTF-8 BOM that JSON.parse refuses unless stripped
C:\_tools\pinebox-android\PineBoxKiosk   the project, git branch main
C:\_tools\pinebox-jackfix       the dead RRO road (§8), source of fm.pinebox.jackfix
C:\_tools\pinebox-gsi           GSI images
```

Dependencies: AndroidX core/appcompat/activity/lifecycle/datastore/webkit/drawerlayout/documentfile,
coroutines 1.8.1, OkHttp 4.12.0, jsch 0.2.18 (mwiede), junit + mockwebserver + org.json for JVM tests.
`FAIL_ON_PROJECT_REPOS`; R8 off in both build types; `lint.abortOnError=false`
("a kiosk that stops building because a lint rule turned into an error is a
kiosk nobody can patch at 3am").

### 0.8.2 The build-and-deploy loop

```sh
cd /c/_tools/pinebox-android/PineBoxKiosk          # LOCAL cwd - gradle refuses a UNC one
./deploy.sh                                          # build -> zipalign -> platform-sign -> verify -> install
./deploy.sh --no-build                               # re-sign and install what is already built
$ADB $D shell am start -n com.pinebox.kiosk/.MainActivity   # deploy.sh leaves the app STOPPED
```

`deploy.sh` pins `JAVA_HOME=/c/_tools/jdk17`, `ANDROID_HOME=/c/_tools/android-sdk`,
`GRADLE_USER_HOME=/c/_tools/_gradlehome`, device `PINE_TAB=10.89.1.154:5555`,
runs `gradle.bat --console=plain assembleDebug`, then `zipalign -p -f 4`,
`apksigner sign --key keys/platform.pk8 --cert keys/platform.x509.pem`, and
**two** checks before it will install: the APK's signer must be the platform
key by full SHA-256, and the tablet's framework must still be `b4addb29`.
Either failing is a refusal, not a warning. On a signature clash it
uninstalls first and re-grants `RECORD_AUDIO` and `CAMERA`. Its own header
says the plain two-command install has killed the jack "twice"; the memory
notes say three. If it says *"could not read the tablet's framework key"*,
adb has dropped the tablet — reconnect, it is not a signing fault.

**`desktop/android-build.cjs` does not do this.** The desktop's
`terminalBuildApk` / `terminalInstallApk` run `gradle assembleDebug
--no-daemon` and `adb install -r` — debug-signed, no platform key, no
`deploy.sh`. Using them on the kiosk reverts the signature. (Its default
project path is also written as a single-quoted JS string whose backslashes
collapse, so it needs `cfg.androidProject` set to work at all.) They are
fine for building *your* app, which does not need the platform key.

Build time is ~20 s warm. Verify the install by **size and timestamp** of
`pm path com.pinebox.kiosk` against your own APK — a second session installs
to this tablet too, and on 2026-09-14 the kiosk project's assets were being
rewritten at 21:41 while this guide was written. Then verify by calling
your code over CDP (§0.2.4), never by grepping the DOM.

### 0.8.3 Adding a view, a style, a bridge method

A view is a plain IIFE hanging one global off `window`
(`window.PineYourThing = {mount, close, …}`); no modules, no bundler.
Three registration points, and missing each fails differently:

| file | what it does | if you forget it |
|---|---|---|
| `desktop/renderer/rail.js` `VIEWS[]` (`{id, cls, label, mount:[globals…]}`) | the tab and its host | no tab at all |
| `PineBoxKiosk/…/bridge/ViewAssets.kt` `SCRIPTS` / `STYLES` | bundles + evaluates the file | tab opens to "has not been loaded on this terminal" |
| `desktop/renderer/index.html` | the Electron half | works on the tablet, not on the desk |

Order in `SCRIPTS` matters; `rail.js` goes after the views. The `cls` in a
`VIEWS` row is the **host's** class, not your view's — give the host its own
(`sl-host`, not `sl`), or your stylesheet lands on the element that reserves
the rail's strip. If the view must also exist on the sampler page, repeat
for `pine-sampler/` and `SamplerAssets`. Copy the file into **both**
`desktop/renderer/` and `app/src/main/assets/pine-views/` — there is no sync
script; compare by size before building (`view-chrome.css` genuinely
differs between the two asset dirs; a basename diff cries wolf on it).

Rules that came from measurements on this glass: talk to the station
through `pineDesktop`, not `fetch`; ride rAF, not `setInterval`, for
anything that must keep moving; float at body level in the z-index bands
(§0.5.12); borrow the panel's analyser, never build a second source on an
element; `padding-right` on the host does **not** inset an absolutely
positioned child (the containing block is the padding box) — measure
`#pineViewRail` and inset with a CSS variable, and re-measure after ~1.4 s
and with a `ResizeObserver` because the rail can be 0 px wide at mount;
`offsetParent` is always `null` for `position:fixed`; tear down floating
`<video>`s by class over the document, clearing `src` and calling `load()`
before removing (a leaked loading video eats one of the six sockets for
good); the panel's `[hidden]` is a UA type-level rule, so any class-level
`display` outranks it; icons are Carbon through `pineIcon('c:name')`, never
emoji; ES5 only in anything the WebView evaluates. `tests/` holds the
node and python tests that pin the shared files (`test_slideshow_*`,
`test_sfx_tv_*`, `test_pinetab_route_*`, `test_terminal_*`, …).

A new native capability is the three edits in §0.5.3, and every
`@JavascriptInterface` method runs on the WebView's JavaBridge thread — not
the UI thread, not a thread with a Looper.

### 0.8.4 The parallel-session rule

More than one agent session edits this project and `app.py` at once, and a
read-modify-write over the other's changes has clobbered whole patches
three times in a day. Re-read before every patch, patch with anchors that
must match exactly once, write atomically, and verify the **served** page
(`node --check` the extracted `<script>`) rather than the file — a single
`SyntaxError` in the panel's inline script kills `pollDJ`, the voice poll
and the music player together while every server meter stays green (§19.0).

## 0.9 The station's API, for a device

### 0.9.1 Auth in one table

| gate | what it checks | where it applies |
|---|---|---|
| `require_read_auth` | **nothing** unless `SPARK_AGENT_LOCK_READS=true` (it is `false`) | ~330 read routes: `/api/dj`, `/api/radio/clock`, `/api/radio/listeners`, `/api/settings` GET, `/api/pulse`, `/api/generations`, … — all answered on the LAN with no header today |
| `require_auth` | `Authorization: Bearer <SPARK_AGENT_API_KEY>` (64 hex) **or** a full-scope share token | every write: `/api/radio/solo`, `/api/dj/output`, `PUT /api/settings`, `/api/service/restart`, `/api/pine-requests` POST, `/api/listen/transcribe`, `/api/share`, `/api/tablet/doctor/*`, … |
| `require_listen_auth` | `?t=<share token>` **or** the bearer | the guest surface: `/stream.*`, `/hls/*`, `/api/dj/join|request|shout`, `/api/music/vote`, `/api/radio/unpause`, `/api/generations/image/*`, `/api/pinelink/mine|frame.jpg` |
| `media_sign` | `?t=<32 hex HMAC(key, name)>` **or** the bearer | `/media/<key>`, `/music/<id>`, `/sfx/<id>`, `/tape/<key>`, `/nabu-audio`, … — the sig arrives *inside* the JSON that named the file |
| `?key=` fallback | the bearer in the query string | a dozen page-opening routes (`/api/tablet/look`, `/api/said/search`, `/api/pine-journal`, `/api/cupboard/*`, …) |
| none | | `/`, `/healthz`, `/health`, `/radio`, `/spark`, `/spark/asset/*`, `/api/slideshow`, `/tune/<token>` (the token gates it), `/vendor/*`, `/icons/*`, the `/api/director/*` family, and ~60 more |

Where the key comes from: `GET /` embeds `const SERVER_KEY = "…";`
(`SPARK_AGENT_AUTOFILL_KEY=true`), which is how both the kiosk and the
desktop provision themselves. Over SSH:
`docker exec spark-agent printenv SPARK_AGENT_API_KEY`. It is **not** in
`data/settings.json`.

### 0.9.2 The public door, `:8097`

A second uvicorn in the same process, wrapped by `PublicListenerGate`: any
path not on the allowlist is 404 before a handler runs; **`Authorization` is
stripped** and `x-pinebox-public: 1` is added; WebSocket scopes are dropped.
Allowed GETs: `/healthz /api/dj /api/dj/voice /api/dj/reacts /api/dj/video
/manifest.webmanifest /api/radio/clock /stream.mp3 /stream.m3u /stream.m3u8
/api/stream/state /spark/asset/{sfx-tv.js,sfx-tv.css,slideshow.css}
/api/pinelink/mine /api/pinelink/frame.jpg` plus prefixes `/app-icon-
/tune/ /media/ /music/ /data/vendor/ /icons/ /api/generations/image/ /hls/
/sfx/`. Allowed POSTs: `/api/dj/join /api/dj/request /api/dj/shout
/api/music/vote /api/radio/unpause`. So through the public door `?t=` is the
only credential that works, and `/tune/<full token>` is downgraded to the
radio page. `GET /` on 8097 is a 404 by design.

### 0.9.3 Reads

`/api/dj`, `/api/radio/clock`, `/api/dj/voice`, `/api/dj/video` — §0.7.3.
Also: `GET /api/dj/state` (`dj_state()` + `died`), `GET /api/radio` (the 11
transport keys), `GET /api/radio/pause`, `GET /api/radio/next` (signed
`url`/`art`), `GET /api/dj/flow`, `GET /api/airlog?since&until&who&kinds&most`
(≤5000 rows of everything that aired), `GET /api/said/search?q=`, `GET
/api/perf` (RAM/CPU/GPU/temps of the DGX), `GET /api/health/details`
(20 s memo; 5–32 s uncached — do not poll it), `GET /api/library`, `GET
/api/sfx/stats` (every sting with a signed `url`), `GET /api/generations?limit=`
(newest-first, includes `.mp4/.webm`), `GET /api/slideshow/playlist?limit&offset&kind&favorites&order=shuffle&seed&since`
and `GET /api/slideshow/media/<file>?w=` (**Range and thumbnails** — use
this, not `/api/generations/image`, for anything that seeks or lists),
`GET /api/slideshow/stack` (the eleven desktop tailers in one 10 s-cached
answer), `GET /api/broadcast/{health,console,watch}`, `GET /api/routing/moves`,
`GET /api/export/courier`, `GET /api/pinelink/{look,state,doctor,ladder,clips}`,
`GET /api/manuals*`, `GET /api/system2/{status,hours,hour,script,binding,line,download}`.

### 0.9.4 Writes that move the broadcast

- `POST /api/dj/output` — `{music|voice|reply: "box"|"here"|"both"|"off"|"nabu", voice_device:"pine"|"nabu", music_level|voice_level|reply_level: 0..1, music_control, box_talk, system:true}`.
  One destination is enforced (music is dragged to where the voice points;
  `off` is a mute, not a place); moving the voice to `box`/`off` clears the
  voice clip ring at once. Returns `dj_state()`.
- `POST /api/radio/solo` — §0.7.2. **Order for "make X the only sound":
  solo first, then output, then `PUT /api/settings`** — the other way round
  has a window where the show is routed to a page and no page believes it
  is the sink.
- `PUT /api/settings` — replaces; read-modify-write the whole document.
  `model` is ignored here (use `POST /api/model`); a blank `ha_token` is
  restored from disk.
- `POST /api/radio/pause {paused}` / `POST /api/dj/{start,stop,next,prev,say,interject,replay,announce,drain}`.
- `POST /api/broadcast/fix/<step>` — the reinitialise ladder one rung at a
  time (§23): `look speed triangulate` change nothing; `onair relieve
  ungag floor flush drain stock terminals release reload_pages kiosk stream
  engines deep steward disk restart`. `kiosk` stamps `kiosk_kick` on
  `/api/dj`; the **desktop** sees it and runs `am force-stop` + `am start`
  on the tablet — the station has no adb.
- `POST /api/broadcast/reload-pages` — stamps `reload_at`; every open page
  whose start predates it reloads 0.8–4.8 s later, the caller's included.
- `POST /api/service/restart {"name":"spark-agent"}` — the process
  `os._exit(3)`s half a second later and docker brings it back (~20 s of
  silence). Any other container name goes to the restarts-only docker
  proxy. **The body is required**; without it the route 500s.

### 0.9.5 The tablet's services on the station

- `POST /api/listen/transcribe` — raw audio → text (§0.7.5). The reason: no
  `RecognitionService` on the GSI.
- `GET /api/slideshow/*` — the lock screen's and SLIDES tab's material
  (§0.9.3), `favorites.md` and `screensaver_state.json` shared with the
  desktop slideshow (`source: host|station` says whether `~/bin` is mounted).
- `GET /spark`, `/spark/asset/<name>` — `SparkActivity`'s page and its
  seven allowlisted renderer files, served from `/app/desktop/renderer`.
- `GET /api/pinelink/frame.jpg?t=` — the Pine Cam picture at 4 fps (refuses a
  half-written JPEG; on the public door a token with the camera tick is
  mandatory), `POST /api/pinelink/announce` (stamps `announce_at` so the
  tablet puts a notice mid-screen), `/api/pinelink/{cut,keep,prefs,on-air,public,viewers,mine}`.
- `GET /api/sfx/video/neighbour?id&dir=next|prev` — answered from the clip
  book (`data/sfx_clips.db`), never by walking the 18,570-file CIFS folder,
  because "the tablet's bridge gives up at 20 s".
- `PUT /api/export/upload` — where the air tap's slices go.

### 0.9.6 The tablet as the station sees it

`GET /api/tablet/look` (read; `?key=` accepted) →
`{at, host, configured, port, arp{ip,flags,mac,device}, adb{open,ms}, seen{first,hits,at,what,agent}, seen_ago, fetching, on_network, adb_port_open, kiosk_kick, steps[], verdict, cure, say, steps_available[]}`.
On 2026-09-14 it read: *"the tablet is here and ready — it is playing the
station and its debugging port is open"*, seen 0.4 s ago via `okhttp/4.12.0`
(the kiosk's client, not its WebView), MAC `36:63:f9:5d:06:32` on the box's
`wlP9s9`.

`POST /api/tablet/doctor/{look|ping|arp|sweep|adopt|wake}` (key) — every
rung but `adopt` (writes the swept address to `data/tablet_link.json`) and
`wake` (stamps `kiosk_kick`) is a question. `sweep` connects to port 5555 on
all 254 hosts of the /24 in 0.35 s each. `GET /api/tablet/seen` lists every
address that has fetched the show. Constants: `PINE_TABLET_HOST=10.89.1.154`,
`PINE_TABLET_ADB_PORT=5555`. There is **no** `/api/terminals` — the device
table lives in `settings.json` only.

### 0.9.7 Rules the station is built around

- `/api/dj` at 4 s, the clock at 1.5 s, nothing faster; `lean=1` when you
  do not need the big keys.
- 38 concurrent requests from the tablet produced a 46 s media stall; every
  tablet-facing road since is one request or a cached one.
- The event loop stalls are the baseline (121 of 144 dead-air gaps in one
  window were loop stalls; some endpoints answer in 10–15 s). A slow answer
  is not your fault and not the tablet's; `GET /api/pulse` names the frame.
- Caches you are reading through: settings 1 s, terminals 5 s, health
  details 20 s, slideshow stack 10 s, storage 30 s.
- Two routes on one path: the first registered wins, silently.
- `VOICE_BROADCAST_LEAD_MS 7000`, `VOICE_LATE_OFFER_MS 45000`,
  `AUDIO_OWNER_LIFE 90`, `AUDIO_OWNER_QUICK 12`, `OWNER_DEAF_SECONDS 75`,
  `OWNER_DEAF_REST 300`, roster window 30 s.

## 0.10 The desk's side (Electron, on the Windows PC)

`spark-agent/desktop/` is the Pine Box Desktop, launched via `pine_box.exe`
into a runner mirror at `%LOCALAPPDATA%\PineBoxDesktop\runner` (the share is
too slow to run from), hot-reloading `desktop/renderer/` every 1.5 s. Its
tablet modules, all driven from `window.pineDesktop` in the renderer:

| module | what it does | reach it from another program |
|---|---|---|
| `terminal-host.cjs` / `terminal.cjs` / `terminal-net.cjs` | finds adb (`C:\_tools\platform-tools`, `C:\platform-tools`, `%LOCALAPPDATA%\Android\Sdk\platform-tools`), discovers the tablet by mDNS then a bounded private-subnet sweep, `adb tcpip`/`connect`, the provisioner (survey, snapshot, bootloader, unlock behind the string `ERASE THIS TABLET`) | — |
| `tablet-vitals.cjs` | **one** adb shell: `dumpsys battery; current_now; /proc/loadavg; /proc/meminfo; dumpsys gfxinfo com.pinebox.kiosk`, split on `---pine---` → `{battery{percent,status,volts,tempC,chargeMah,drawMa,watts,hoursLeft}, load, memory, graphics{frames,janky,p50,p90,p95,p99,missedVsync}, rttMs}`. Polled at 4 s when present, 20 s when absent, coalesced (2.5 s hold) so the sidebar and the mirror window share one sweep | copy the shell line |
| `tablet-mirror.cjs` `Mirror` | the screen: `screenrecord … -` piped through ffmpeg to MJPEG, sizes `quarter/third/half/full` of the measured `deviceWidth×deviceHeight`, bitrate `w×h×11` (floor 800 kbps), 15 fps, rebuilt whenever screenrecord ends. Served on **an OS-assigned loopback port**: `/live.mjpg`, `/frame.jpg` | read the port from `mirrorHow()`; or run the pipe yourself (§0.2.3) |
| `tablet-mirror.cjs` `CameraGlass` | the tablet's camera via `adb forward tcp:<9230–9629> localabstract:pine_camera`, re-served on **`127.0.0.1:8791`** as `/camera.mjpg` and `/camera.jpg` (falls back to a random port if 8791 is taken; `where().known` says which) | `http://127.0.0.1:8791/camera.jpg` while the camera window is open |
| `tablet-input.cjs` | one held `adb shell`; `input tap/swipe/keyevent/text` lines, integers, display coordinates | copy the recipe |
| `pinetab-route.cjs` | the six destinations (`pinetab app web box nabu off` — `both` deliberately absent); resolves the tablet in the roster by `addr` against `settings.terminals.pinetab.addr`, freshness `seen ≤ 30`; sends solo → output → settings; refuses a page that is not looking at the station. Same file ships in the APK as `pine-sampler/pinetab-route.js` | `pineDesktop.pinetabWhere()/pinetabSend(key)` |
| `terminal-audio.cjs` + `renderer/terminal-audio-client.js` | the `terminals` table client, shared by the desk and the tablet page | |
| `terminal-glass.cjs` | stills (`exec-out screencap -p`, fallback pull), clips (`screenrecord --time-limit N --bit-rate 6000000 /sdcard/pinebox-glass.mp4` + pull), wake/sleep by keyevent, a DevTools door on **port 9333**, a written report | |
| `renderer/tablet-doctor.js` | the ladder: station `look` → `sweep`/`adopt`/`wake` → `adb connect` → `look` again; "attached" is measured. Desktop-only by design | the wrench beside *The tablet* in the sidebar |
| `android-build.cjs` | `gradle assembleDebug` + `adb install -r` from the toolchain manifest — **debug-signed, not for the kiosk** (§0.8.2) | fine for your own APK |
| `gsi.cjs` / `firmware.cjs` | the GSI matcher (`ro.*` props vs the image's bytes) and the stock-firmware verifier; the flash plan as data with `where: bootloader|fastbootd` per step and the wipe **last and in the bootloader** (fastbootd's `-w` wiped nothing in 4 ms and said it had) | |

The desk also watches `/api/dj` for `kiosk_kick` (new stamp → `am
force-stop` + `am start` on the kiosk) and `reload_at`. It, not the station,
is the thing with adb.

## 0.11 When it does not work — the short table

Full detail in §19; this is the order to look.

| you see | it is probably | check | cure |
|---|---|---|---|
| panel alive, feed moving, **no sound at all**, images still load | the WebView's network stack wedged (§19.1) | CDP: `fetch('/api/dj')` → `TypeError` in 40–100 ms; `musicPlayer.networkState 2 readyState 0` | `am force-stop com.pinebox.kiosk; am start …` — a reload will **not** do it; `deaf-watch` should have done this itself |
| nothing on screen responds | the notification shade, or the lock screen's X | `dumpsys window | grep mCurrentFocus`; screenshot | `cmd statusbar collapse`; tap (1274, 43) |
| view lost its scroll / folds every ~5 min | the wallpaper relaunching the Activity (§19.2) | `logcat | grep "relaunch: com.pinebox.kiosk"` | fixed by #1296; if it recurs, `WallpaperWatch.reading` is not being set |
| meters/marks frozen, music playing | JS timers suspended (§19.3) | CDP: a fresh `setTimeout` never fires; rAF does | `keepTimersAlive` should cover it; force-stop if not |
| audio on `headset(4)` with nothing plugged in | a stale jack announcement (§19.4) | `dumpsys audio | grep Devices`; `dumpsys input | grep SwitchValues` | `await pineDesktop.jack({on:false})` — but ask first; a cable usually *is* in |
| the jack ignores the cable after a deploy | a debug-signed build over the platform one | `dumpsys package com.pinebox.kiosk | grep -E "MODIFY_AUDIO_ROUTING|DUMP"` → `granted=false` | `./deploy.sh` |
| the mic "hears nothing" | `RECORD_AUDIO` lost in an uninstall | same dumpsys | `pm grant com.pinebox.kiosk android.permission.RECORD_AUDIO` |
| your new view: tab present, "has not been loaded on this terminal" | not in `ViewAssets.SCRIPTS`, or the bundle threw | `logcat -s PineKioskActivity | grep "views failed"` | fix the parse error; every file in the bundle must parse |
| your new bridge method is `undefined` | the shim line in `pine-bridge.js` | `typeof pineDesktop.yourMethod` | the third edit |
| "your fix isn't running" but the CSS class is there | you grepped the DOM for injected JS | `typeof window.PineYourThing` | it *is* running |
| the tablet holds the air and the house is silent | its row `play=false`, or it is deaf (never acks) | `/api/radio/listeners`, `/api/broadcast/console` | `POST /api/broadcast/fix/terminals`, `/release`; the DEVICES rung acts only when every switch is off |
| everything looks fine, the DJs are not heard, for an hour | a `SyntaxError` in the served panel (§19.0) | `node --check` the extracted `<script>` from `GET /` | fix the template, restart, **reload the pages** |
| 87 fetches outstanding, nothing completes | a leaked loading `<video>` holding a socket (§19.5) | CDP: `performance.getEntriesByType('resource')` | clear `src`, `load()`, remove; force-stop |
| everything is slow, stutters | the tablet's main thread or audio thread saturated (§28) | `cat /proc/<pid>/task/*/stat` twice; CDP `Performance.getMetrics` | it is what #1413a–g and #1420 fixed; a stutter that *returns* after a reload is something growing |
| `deploy.sh`: "could not read the tablet's framework key" | adb dropped the tablet | `adb devices` | `adb connect` first |
| `adb` says "more than one device" | USB and Wi-Fi both attached | | `-s 10.89.1.154:5555` |

## 0.12 Quick reference

```sh
ADB=/c/_tools/platform-tools/adb.exe; D="-s 10.89.1.154:5555"; B=http://10.89.1.246:8096
K=$(curl -s $B/ | grep -o 'SERVER_KEY = "[^"]*"' | cut -d'"' -f2)

$ADB connect 10.89.1.154:5555
$ADB $D exec-out screencap -p > now.png
$ADB $D shell "dumpsys window | grep mCurrentFocus"
$ADB $D shell "am force-stop com.pinebox.kiosk"; sleep 4; $ADB $D shell "am start -n com.pinebox.kiosk/.MainActivity"
$ADB $D shell "am start -n com.pinebox.kiosk/.SparkActivity"          # the SC stack app
$ADB $D shell "am start -n com.pinebox.kiosk/.terminal.DgxTerminalActivity"
$ADB $D shell "dumpsys audio | grep -iE 'Devices:'"
$ADB $D shell "dumpsys package com.pinebox.kiosk | grep -E 'MODIFY_AUDIO_ROUTING|DUMP|RECORD_AUDIO|signatures'"
$ADB $D shell "dumpsys device_policy | grep -A2 'Enabled Device Admins'"
$ADB $D shell "cmd package resolve-activity -a android.intent.action.MAIN -c android.intent.category.HOME | grep packageName"
$ADB $D shell "ss -ltnp"                                              # 127.0.0.1:8096 and *:5555, nothing else
SOCK=$($ADB $D shell "cat /proc/net/unix" | tr -d '\r' | grep -o "webview_devtools_remote_[0-9]*" | head -1)
$ADB $D forward tcp:9222 localabstract:$SOCK; curl -s http://127.0.0.1:9222/json
$ADB $D forward tcp:9999 localabstract:pine_camera                    # [u32be len][jpeg] frames while connected
$ADB $D install -r your.apk

curl -s $B/healthz
curl -s "$B/api/radio/clock?listener=<id>"
curl -s "$B/api/dj?lean=1&listener=<id>" | python -c "import sys,json;d=json.load(sys.stdin);print(d['listeners'],d['audio_owner'] if 'audio_owner' in d else '',d['on'],d['paused'])"
curl -s $B/api/radio/listeners
curl -s -H "Authorization: Bearer $K" $B/api/tablet/look
curl -s -H "Authorization: Bearer $K" $B/api/settings | python -c "import sys,json;print(json.load(sys.stdin)['terminals'])"
curl -s -XPOST -H "Authorization: Bearer $K" -H "Content-Type: application/json" -d '{"listener":"<id>"}' $B/api/radio/solo
curl -s -XPOST -H "Authorization: Bearer $K" -H "Content-Type: application/json" -d '{"text":"…","debug":true}' $B/api/pine-requests
curl -s -XPOST -H "Authorization: Bearer $K" -H "Content-Type: application/json" -d '{"name":"spark-agent"}' $B/api/service/restart
curl -s $B/api/pulse | python -c "import sys,json;d=json.load(sys.stdin);print(d['stalls'],d['worst_s'],[r['top'] for r in d['recent'][:3]])"

cd /c/_tools/pinebox-android/PineBoxKiosk && ./deploy.sh && $ADB $D shell "am start -n com.pinebox.kiosk/.MainActivity"
```

### Known discrepancies between this document's older sections, the READMEs, and the device (as of 2026-09-14)

- `PineBoxKiosk/README.md` says the JNI binding "has not been written yet" and that call-in/microphone is "left for later" — both exist (`fm.pinebox.kiosk.audio.PineSampler`, `MicCapture`). It also gives `initialScalePercent` as `/1000`; the code is `/1150`. And it shows the raw `adb install -r app-debug.apk` — do not; see §0.8.2.
- §15 says `adb shell id` returns uid 0. It returns `uid=2000(shell)`; root is `adb root` away on this userdebug build.
- §16.6 and §0.3.3: the kiosk is written as a HOME app with lock task; on the device, launcher3 holds HOME, no device owner is set, lock task is `NONE`.
- The project memory said the kiosk project "is NOT a git repo"; it is (`main`, with uncommitted asset edits from a parallel session).
- `desktop/android-build.cjs` cannot deploy the kiosk correctly (debug key); `deploy.sh` is the only road.
- `app.py` registers `/api/dj/video` twice; the first (`dj_video_api`, `{clips}`) is live and, being `require_read_auth`, is open on the public door without a token.
- Two `adb.exe` copies at `C:\_tools\platform-tools` and `C:\_tools\android-sdk\platform-tools`; same version, either works.

---

# Part I — how a stock Lenovo Tab M9 was made ours

## 1. The device

| | |
| --- | --- |
| Model | Lenovo Tab M9, **TB310FU** (Wi-Fi, 4 GB / 64 GB) |
| Serial | `HA1Y7RCV` |
| Panel serial | `8SSP69A6PVC1MF1545L22CL` |
| SoC | MediaTek **MT6768** (`t6100a_wifi`), USB VID `0E8D` |
| Android | 13, SDK 33, build `TP1A.220624.014` |
| Shipped build | `TB310FU_USR_S000914_2601052017_mp1V969_ROW` |
| Partition layout | **A/B**, 2 slots, booted on slot `a`, dynamic `super` |
| Bootloader | `t6100a_wifi-4babc561b-20250515134948-20` |
| Warranty | expired 2025-08-13 — unlocking forfeits nothing that remained |

Two facts shape everything that follows. It is an **A/B device with a dynamic
super partition**, so any GSI has to be the arm64 A/B variant and images go to
the active slot. And its bootloader reports `max-download-size: 0x8000000`
(128 MB), while `super.img` is 6.28 GB — so that partition can only be written
in sparse chunks.

## 2. Getting the tablet to talk

The tablet was connected by USB with USB debugging enabled, and **nothing
happened**. `adb devices` was empty; not `unauthorized`, simply absent.

The cause was not the tablet. **There was no adb on the machine at all** — no
`platform-tools` in Program Files, the local SDK path, or Downloads. The
"Allow USB debugging?" dialog with its RSA fingerprint is raised *by an ADB
server asking the device for permission*. With no server, nothing ever asked,
so no prompt was ever shown. Installing Google's platform-tools (37.0.1,
extracted to `C:\_tools\platform-tools`) and running `adb devices` produced the
prompt immediately.

Worth keeping, because the symptom points the wrong way: **an empty device list
means Windows cannot see an ADB interface; `unauthorized` means it can, and is
waiting on a human.** They are different problems and only the second one is
about the tablet.

Windows enumerated the device twice under different product ids — `PID_201D` as
a composite (MTP + ADB) and `PID_201C` as a plain `Android ADB Interface`.
Windows already had drivers bound for both. A `Present: False` entry in
`Get-PnpDevice` is a *remembered* device, not a connected one; the live one is
found with `-PresentOnly`.

The RSA prompt then sat unaccepted for a while because **it does not render
while the screen is locked or while a system update is applying.** The transport
id changing (1 → 2) is the tell that the device re-enumerated across a reboot.

Once accepted:

```
HA1Y7RCV   device   product:TB310FU model:TB310FU device:TB310FU
```

## 3. The gate that mattered: OEM unlocking

The single biggest risk to the whole plan was that **OEM unlocking would be
greyed out**. Lenovo and MediaTek tablets frequently lock that toggle until the
device has been online for some time and sometimes until an account has signed
in — which is in direct tension with wanting no Google account on it. If it will
not move, the custom-ROM route is simply unavailable.

It moved:

```
sys.oem_unlock_allowed : 1        → allowed
ro.oem_unlock_supported: 1
ro.boot.flash.locked   : 1        → still locked, as expected
ro.boot.verifiedbootstate: green
```

Both lock signals are read, not just one, because a vendor that lies in one
sometimes tells the truth in the other.

## 4. The restore image

Unlocking erases the tablet. Before touching it, a verified way back had to
exist on disk — otherwise the exercise is a one-way door.

**Lenovo Rescue and Smart Assistant** (shipped as *Software Fix* v7.6.2.10) is
the official route, and it is keyed to the device: enter the serial and it
fetches the matching firmware, no tablet needed. It downloaded to
`C:\ProgramData\RSA\Download` — **not** `\LMSA` as most guides claim — and
brought SP Flash Tool along with it.

What arrived: `TB310FU_S000915_260703_ROW`, a 3.4 GB archive expanding to
**6.5 GB across 21 partition images**. Note it is a *newer* build than the
`S000914_260105_ROW` on the device; same model, official Lenovo, so restoring
moves the tablet forward a build rather than back.

### The scatter is encrypted

The MediaTek scatter file — the map SP Flash Tool needs — is **ciphertext**, and
its extension is truncated on the way out of LMSA:

```
image/MT6768_Android_scatter.t     21,328 bytes   e97c fb81 0178 82d5 ...
image/MT6768_Android_scatter.x     35,808 bytes   dde3 7578 08bd cba7 ...
image/efuse_t6100a_wifi.x           2,560 bytes   9358 9364 928f b2a2 ...
```

This is how Lenovo ships it, not a corrupt download. The consequence is real
though: **SP Flash Tool cannot use this package as it stands**, which also means
the BROM rescue path is not available from it. The tool LMSA helpfully
downloaded alongside the firmware is, for this package, inert.

### The images themselves are plain

Every actual partition image is ordinary and verifiable:

| File | First bytes | Verdict |
| --- | --- | --- |
| `boot.img` | `ANDROID!` | Android boot image |
| `vbmeta.img`, `_system`, `_vendor` | `AVB0` | AVB metadata |
| `super.img` (6.28 GB) | `3aff26ed` | Android **sparse** image |
| `super_empty.img` | `gDla` | raw **LP metadata** |
| `dtbo.img` | `d7b7ab1e` | DTBO |
| `preloader_raw.img`, `preloader_t6100a_wifi.bin` | `MMM…FILE_INFO` | raw MTK preloader |
| `preloader.img`, `_emmc`, `_ufs` | `EMMC_BOOT` … `MMM` at `0x800` | wrapped MTK preloader |
| `lk`, `logo`, `tee`, `gz`, `scp`, `sspm`, `spmfw`, `md1img` | `88168858` | MTK bootloader blobs |

So the restore path survives: **LMSA Rescue** (primary — it decrypts internally),
or **`fastboot flash`** of these verified images once unlocked. Keep LMSA
installed; it is the way back.

Package manifest hash, over every image name and digest:

```
d390ca9892572566d8ed8ddeec9e4ef5cf561145dafd55791c4172ce3d8d5d9b
```

Full record in [terminal-m9-firmware-2026-09-10.json](terminal-m9-firmware-2026-09-10.json),
device survey in [terminal-m9-snapshot-2026-09-10.json](terminal-m9-snapshot-2026-09-10.json)
(229 packages installed, **93 of them Google** — the ones a GApps-free GSI removes).

### Two false alarms worth keeping

The verifier flagged good files twice, and both corrections are now rules with
tests behind them:

1. **Three preloaders "corrupt".** They were not. `preloader.img`, `_emmc` and
   `_ufs` are the same payload inside an `EMMC_BOOT` wrapper with the real `MMM`
   header at offset `0x800`; only `preloader_raw` and `preloader_<board>.bin`
   start with `MMM` at zero. Insisting on offset zero condemned three valid
   files.
2. **`super_empty.img` "corrupt".** Also not. `super.img` is a sparse image and
   `super_empty.img` is raw LP metadata — two formats, both legitimate, and the
   rule only knew the first.

A verifier that cries corruption over a good download is worse than none,
because it burns the operator's trust exactly when it matters.

## 5. Drivers — less than expected

The widely repeated advice is that MediaTek devices need the **USB VCOM driver**
or `fastboot` hangs at *waiting for device*. On this machine that turned out not
to apply: Windows had already bound `Android ADB Interface` to
`USB\VID_0E8D&PID_201C`, and `fastboot devices` answered immediately after
`adb reboot bootloader`:

```
HA1Y7RCV    fastboot
```

Google's official USB driver package (rev 13) was downloaded and inspected —
it contains **zero** `VID_0E8D` entries, only Google's own — so it would not
have bound anyway, and was not needed.

VCOM is only required for **SP Flash Tool / BROM** work, which the encrypted
scatter has ruled out for this package. If a BROM rescue is ever needed, the
right tool is [bkerler/mtkclient](https://github.com/bkerler/mtkclient) with
UsbDk — open source and auditable. Note that `mtkclient.com` is **not** the
official project, and the driver zips on ad-supported mirror sites are a genuine
malware vector for something that installs an unsigned kernel driver.

## 5b. Off the cable

The tablet is reachable over Wi-Fi and can be found, connected to and updated
from the app with no USB at all.

```
10.89.1.154:5555 -> TrebleDroid vanilla running 21.0-20260614-UNOFFICIAL-arm64_bvN
```

Discovery asks **mDNS** first (`adb mdns services`) and falls back to a bounded
sweep of only the private subnets this machine is actually on — the same
restraint the LCD's own discovery shows, because a scan that wanders off the
local network is a nuisance rather than a feature.

Three things measured here that no amount of reading would have produced:

1. **The advertisement has two shapes.** A tablet switched on with `adb tcpip`
   publishes the bare `adb-HA1Y7RCV`; one paired for wireless debugging adds a
   random suffix, `adb-HA1Y7RCV-vWmDCe`. A pattern that assumed the suffix
   returned a **blank serial** for the real tablet.
2. **`adb tcpip` restarts adbd.** The very next shell command lands while the
   daemon is gone, so reading the address immediately reported *"no Wi-Fi
   address yet"* for a tablet that plainly had one. It now retries.
3. **Two transports make adb ambiguous.** Once the tablet is on both the cable
   and the network, adb has two transports for one device and answers
   *"error: more than one device/emulator"* to any untargeted command. Every
   wireless call now targets the cabled serial explicitly, and "more than one
   device" is treated as a failure rather than a success.

Also: adb has been observed handing back `0.0.0.0` as a service address once a
TCP transport already existed. That is not somewhere anything can connect, so
non-routable addresses are dropped rather than offered as targets.

One honest limitation: `adb tcpip` does **not** survive a reboot on a build that
does not persist it, and this GSI does not. Reconnecting after a restart needs
the cable once — the app says so rather than leaving it to be discovered.

## 6. What was built

The provisioning logic lives in the Pine Box desktop, modelled on the existing
CYD LCD firmware manager ([pine-box-lcd.md](pine-box-lcd.md)) and reusing its
discipline: identify by something the device cannot change, record what you find
with a hash and a timestamp, refuse anything that does not match, verify after
acting rather than trusting the tool's own success message.

**[`desktop/terminal.cjs`](../desktop/terminal.cjs)** — device discovery and the
bootloader.

- `devices()` / `identify()` — parses `adb devices -l`, then a single batched
  `getprop` and `dumpsys battery`. It will not shell into a tablet that has not
  accepted the RSA prompt.
- `readiness()` — the survey gate: not connected, not authorized, OEM unlocking
  off or unsupported, battery below 50%.
- `snapshot()` — props, packages, features and global settings, hashed. Its own
  `caveat` field states plainly that it is **not a restorable image**.
- `bootloader()` — parses `fastboot getvar all` into a typed state.
- `unlockReadiness()` — the last gate before erasure.
- `unlock()` — runs `flashing unlock` only past that gate, then **re-reads the
  bootloader to prove it worked** rather than believing `OKAY`.

**[`desktop/firmware.cjs`](../desktop/firmware.cjs)** — the restore-image gate.
Finds the scatter (including LMSA's truncated `.t`/`.x`), tells ciphertext from
a readable map, verifies every image by **magic bytes at possibly several
offsets**, SHA-256s each file and folds them into one package manifest, and
refuses a package missing `preloader`, `lk`, `boot`, `vbmeta` or `super`.

**[`desktop/gsi.cjs`](../desktop/gsi.cjs)** — matching an image to the tablet.
It keeps three things apart that are easy to conflate: what the **tablet
requires** (read from its own properties), what an **image actually is** (ext4
magic at `0x438`, EROFS at `0x400` — the filename is a claim, not evidence), and
whether the two **agree**. It refuses A-only on an A/B device, 32-bit on arm64,
a vndklite mismatch, a locked bootloader, or a still-compressed file — and it
names a failed download as a rejection page rather than calling it corrupt.

**[`desktop/terminal-host.cjs`](../desktop/terminal-host.cjs)** — the wiring.
It owns the only thing the modules above deliberately do not: where `adb` and
`fastboot` live, and how to run them. Its `survey()` answers the whole screen in
one round trip — what is plugged in, whether it is fit to touch, whether there is
a way back, and whether the image on hand is the right one.

**[`desktop/renderer/terminal.js`](../desktop/renderer/terminal.js)** — the
Terminal panel, reachable from the rail. It reads as a checklist of refusals, in
the same words the modules use, so a blockage is visible before anything is
pressed rather than discovered from a failure. Blockers and warnings are never
merged: one stops the work and the other does not, and blurring them teaches an
operator to skim both. The unlock control makes you type the confirmation out and
stays disabled until a verified restore image exists — and the main process
checks all of it again regardless of what the page believes.

Both take their shell runners by injection, so every path — including the ones
that would wipe a tablet — is tested without hardware.

### The refusals, in one place

`unlock()` will not run unless **all** of these hold:

- the bootloader actually says whether it is locked (silence is never taken as unlocked)
- it is the real bootloader, not fastbootd
- the bootloader's own `battery-soc-ok` is `yes`
- the serial matches the tablet that was surveyed
- a **verified restore image** exists
- the caller passes the exact string `ERASE THIS TABLET`

Tests, all without a tablet attached:
[test_terminal_provisioner](../tests/test_terminal_provisioner_2026_09_10.cjs) (14),
[test_terminal_unlock](../tests/test_terminal_unlock_2026_09_10.cjs) (14),
[test_terminal_host](../tests/test_terminal_host_2026_09_10.cjs) (6),
[test_firmware_restore](../tests/test_firmware_restore_2026_09_10.cjs) (17),
[test_gsi_match](../tests/test_gsi_match_2026_09_10.cjs) (14).

## 7. State as of this writing

| Gate | Status |
| --- | --- |
| Tablet identified and authorized | done — `HA1Y7RCV` |
| OEM unlocking available | **allowed** |
| Device survey captured and hashed | done |
| Verified restore image on disk | done — 6.5 GB, 21 images, 0 bad |
| fastboot reachable | done — no extra drivers needed |
| Bootloader | **unlocked** |
| GSI flashed | **LineageOS 21, Android 14** — `21.0-20260614-UNOFFICIAL-arm64_bvN` |
| Hardware acceptance | **passed** — audio, mic, Wi-Fi, touch, sensors |
| Google packages | **93 → 6** (Play Services gone) |
| Reaches the station | yes — HTTP 200 from `10.89.1.246:8096` |
| Kiosk APK, launcher, lock task | not started |

### The unlock

Run through the app's own code path, not by hand. It verified the restore image
was still on disk, surveyed the tablet, rebooted to the bootloader, and only then
issued `flashing unlock`. The tablet asked for confirmation on its own screen;
fastboot waited **62.5 s** for it.

```
before:  unlocked: false   secure: true
after:   unlocked: true    secure: false
```

The result was **re-read from the bootloader rather than taken from fastboot's
`OKAY`**, and confirmed again from Android afterwards:
`ro.boot.flash.locked = 0`, `ro.boot.verifiedbootstate = orange`. Every boot now
shows an orange "bootloader unlocked" warning; that is permanent and not a fault.

Userdata was erased, as expected. Developer options and USB debugging had to be
re-enabled afterwards, and the RSA prompt reappeared with a fresh fingerprint.

### The flash

Run as a plan rather than a run of commands, each step declaring the mode it
needs. The GSI: 2.37 GB ext4, `sha256 644722fc8c8a8b594187218c6dcacabe02ca77e9e17dd0e1a7f18a373028d27c`.

```
1 [bootloader] disable verified boot   flash vbmeta --disable-verity --disable-verification
2 [bootloader] enter fastbootd         reboot fastboot            (20.3s)
3 [fastbootd ] flash system            resized system_a, 10 sparse chunks
4 [bootloader] wipe data               mkfs.f2fs over 49,500 MB
5 [any       ] reboot
```

It booted in about 40 seconds to `ro.lineage.version 21.0-20260614-UNOFFICIAL-arm64_bvN`,
Android 14 / SDK 34. Being a **userdebug** build, ADB is enabled and authorized
out of the box, which removes the re-enable dance after every wipe.

Afterwards: all hardware features present, audio routed to `speaker(2)`, **ten
vendor `soundfx` libraries loaded** — the MediaTek audio HAL survives the GSI,
which was the single risk that could have killed the whole project — and the
tablet answered `HTTP 200` from the Pine Box agent at `10.89.1.246:8096`.

### The wipe that wiped nothing

Worth recording, because it was silent and it mattered.

`fastboot -w` was first placed in **fastbootd**, where it answered:

```
wipe task partition not found: userdata
wipe task partition not found: cache
wipe task partition not found: metadata
Finished. Total time: 0.004s
```

Four milliseconds, exit zero, reported as a clean wipe — and the tablet then
booted LineageOS with Lenovo's `/data` intact, **Play Services and all**. A
Google-free build with Google Play Services alive on it.

The cause is a real distinction: **fastbootd exposes the LOGICAL partitions
inside `super`, and `userdata` is not one of them.** It is a physical partition
the bootloader owns. Moving the wipe back to the bootloader — after the system
flash, so a failed flash never empties the tablet for nothing — produced what a
real wipe looks like:

```
F2FS-tools: mkfs.f2fs ... total sectors = 101377984 (49500 MB)
```

Google packages went 93 → 6, and the six that remain are AOSP framework
resource overlays on the vendor partition (networkstack, wifi resources,
cellbroadcast UI), not Google services.

Two lessons are now code. The plan puts `wipe data` in `bootloader`, with a test
asserting that mode specifically. And `runPlan` flags a **hollow success** — a
command that exits clean while saying "partition not found", "No such file" or
"Command not supported" — as a note on the step, without failing it. A step that
quietly did not happen is worse than one that failed loudly.

### What the tablet says it needs

Read from the device itself after unlocking, never guessed from the model:

```
ro.treble.enabled          true
ro.build.ab_update         true          -> A/B
ro.product.cpu.abilist64   arm64-v8a     -> arm64
ro.vndk.lite               (empty)       -> full VNDK, not lite
ro.virtual_ab.enabled      true          -> super goes through fastbootd
ro.boot.dynamic_partitions true
ro.board.platform          mt6768
```

So the image wanted is **arm64 · A/B · vanilla · full VNDK**.

### On root

Root was chosen, but neither current build publishes a superuser variant —
`bvS` exists only in the June 2025 image, a year behind. Rather than give up a
year of MediaTek fixes on the subsystem that decides whether this project works
at all, the plan is the **newest TrebleDroid base plus Magisk**, patching the
boot image separately. Magisk is better maintained than PHH Superuser, and the
stock `boot.img` needed to patch is already on disk from the Lenovo package.

---

## 8. The audio, and the rule that shapes it

Everything in this section exists to satisfy one sentence from the operator:

> "My goal is to have the broadcast going to singularly the PineTab or the Pine
> Box or the Nabu device, the app instance or the application loaded on PC.
> Individually but never at the same time."

That is a stronger rule than the station's own model, and the gap is the whole
reason `desktop/pinetab-route.cjs` and `rail/AirOwners.kt` exist.

### Why the station cannot say it alone

Each stream routes to one of `box`, `here`, `both`, `off`, `nabu`
(app.py:93361). Two of the five break the rule by themselves:

| route | why it is not singular |
| --- | --- |
| `both` | the box **and** a page, by definition |
| `here` | **every** browser looking at the station |

`here` is the one that bites. The tablet, the Electron app and any web page open
on the PC are all "here" clients. Measured on the live station with all three
up, in the station's own words:

```
3 players are on this broadcast - if that is one machine,
they will be playing over each other. Give one of them the air.
```

That is what "I'm hearing a different broadcast coming out of the application
than out of the Pine Box tab" actually was: not two different shows, but **one
show played three times, a few hundred milliseconds apart**.

### The station already had the answer

`#1008` (app.py:25001) gives ONE listener the air; every other page gags itself
in `pineSoloGate` (app.py:154557), and an owner that stops polling releases it
after `AUDIO_OWNER_LIFE` (90 s).

That "stops polling" is doing more work than it looks, and it has been wrong
twice. `#1187` added the second release condition: a device whose row says
`play=false` may not keep, recover, or be given the air, because holding the
exclusive while refusing to sound silences everything. `#1332` added the
third, and it is the one that shows why "can never leave the house silent"
was too strong — a device can have `play=true`, poll perfectly, and still
acknowledge **nothing**. Measured: a freshly launched desktop held the air
that way while two tablets that had played 52 and 50 clips sat muted 75 and
74 times each, waiting for it. Polling is not consuming. An owner that holds
the air for `OWNER_DEAF_SECONDS` (75 s) having taken no clip at all now loses
it, and is refused re-entry for `OWNER_DEAF_REST` (300 s) — because without
that it simply claimed it back on the next poll and the house went quiet for
another seventy-five seconds, over and over.

```
GET  /api/radio/listeners   the roster, plus audio_owner
POST /api/radio/solo        {"listener": id} | {"clear": true}
```

**It must not be reimplemented.** The terminal drives it; it does not replace
it. A destination is therefore two decisions made together — the route, and who
holds the air — and exclusivity falls out by construction: a route is a single
value, and when it is `here`, exactly one listener id is left unmuted.

### A listener id is not an identity

This is the trap that made "only the tablet" keep coming undone. The id is
minted fresh on every page load. Measured across three relaunches of the kiosk
app: `pbnvgdtefn`, then `pbq8gj5qvq`, then another. So the tablet would hold the
air until it reloaded, at which point the owner it named stopped polling, the
station released it after 90 s, and every page started sounding again.

Nothing durable is ever stored against a listener id. The durable statement is
the **destination**, kept in settings; the id is re-resolved from the roster
every time it is needed. Devices are identified two ways, both measured:

- the Electron app mints `desktop-<rand>` (`renderer.js` `desktopListenerId`), so
  it is self-identifying wherever it runs;
- everything else mints `pb<rand>` and is placed by **address** against the
  `terminals` table — which is why the tablet's row carries an `addr`.

A `terminals` row that pins a `listener` is never matched by address to anything
else. Two tabs on one machine share an address — the Electron app and a browser
window both sat on `10.89.1.13` — so an address alone cannot tell them apart.

### The half the desktop was missing

`renderer.js` read `window.__pineGagged` to decide whether another listener owned
the air, but **nothing in that file ever set it**. `pineSoloGate` sets it inside
the station page, which is a `<webview>` and therefore a different JS context, so
the shell's own players never learned they had been gagged and kept sounding.
`/api/radio/clock` already carries `audio_owner`, so the shell only had to ask
the same question about itself.

> Renderer changes need a **desktop relaunch** to take effect. A running app
> keeps the old `renderer.js` and will look exactly like an unfixed bug.

### The routing table

Beside the destination sits a table of devices in settings (`terminals`,
validated by `validate_terminals` in app.py), one row per device:

```
pinetab  play=true   music .8  voice 1    addr 10.89.1.154
desktop  play=false  music .6  voice .6   addr 10.89.1.13   fallback=true
```

Every client reads the same table and obeys its own row, which is what makes the
tablet's volume settable from the computer. The levels drive the panel's own desk
(`djGainMusic` / `djGainVoice`, read by `djLevels()` at app.py:149377) rather
than a second audio path, so the panel's existing GainNode machinery does the
work.

**The clamp is not cosmetic.** The voice slider defaults to 160%, and on the
tablet the DJs play through a plain `<audio>` element, whose volume setter throws
above 1.0:

```
IndexSizeError: The volume provided (1.6) is outside the range [0, 1]
```

The throw aborted the routine that was setting it, so **the DJs were silent on
the tablet while music played**. The desktop never saw it because its GainNode
accepts boost. The setter is clamped for every element in the page, including
ones the code has never heard of.

Two rules that were **wrong in the first cut**, recorded so they are not
reintroduced:

- *"More than one device switched on is legitimate — the box and the tablet."*
  It is not. More than one is a fault, resolved by id order so the desktop and
  the tablet reach the same answer without talking to each other.
- *Reading the desk clamped.* That made 160% and 100% indistinguishable, so the
  table could never pull a boosted slider down — it always appeared to agree
  already. The desk is read **raw**.

### The 3.5 mm jack — the six roads, and the one that worked

> "It is tantamount that I get the audio working through the jack as well. That
> is one of the reasons I bought this unit. Typically I have the audio being
> piped into a major system."

Symptom: plugging an aux cable into the tablet did nothing; audio stayed on the
speaker. Measured end to end, with a cable in the socket:

| check | result |
| --- | --- |
| `/sys/class/switch/` | **empty** — no `h2w` node |
| `/dev/input/event0` `ACCDET` | `SW (0005): 0002*` — `SW_HEADPHONE_INSERT` **set** |
| `dumpsys input` Device 5 | `Switch Input Mapper: SwitchValues: 4` |
| `/vendor/etc/audio_policy_configuration.xml` | declares `AUDIO_DEVICE_OUT_WIRED_HEADSET` and `..._HEADPHONE` |
| `cmd overlay lookup android android:bool/config_useDevInputEventForAudioJack` | **`false`** |
| `dumpsys audio` | `mMainType=0x0` — the audio layer is unaware |

The kernel detects the plug, InputReader reports it, and the vendor policy has
somewhere to send it — and then the framework drops it on the floor.
InputManagerService's own bytecode says why:

```
iget-boolean v0, v6, InputManagerService.mUseDevInputEventForAudioJack
if-eqz v0, 0080                 <- false, so jump past everything
...
invoke-interface WiredAccessoryCallbacks.notifyWiredAccessoryChanged
```

**Five roads round it were tried and every one is dead.** They are recorded
because each looks plausible and each costs an afternoon:

1. **A platform-signed RRO flipping that boolean true.** It installs and it
   survives a reboot — and it still does not work, because a `/data` overlay is
   applied **after** IMS constructs. Measured: IMS at 15:12:43, the overlay at
   15:12:44. That is a hard ordering wall, not a bug with a fix.
2. **A fabricated overlay.** Wiped on every framework start.
3. **`cmd audio` / a vendor force-route property.** Neither exists on this build.
4. **`AudioTrack.setPreferredDevice`.** Needs the device to appear in
   `getDevices()`, which needs the framework to know about it. Circular.
5. **Forcing the codec by hand as root.** `HPL/HPR Mux` was set to Audio Playback
   and *held*, unopposed, for twenty seconds — and there was still nothing in the
   headphones. The vendor's own `audio_device.xml` explains it:
   `headphoneSpeaker_output` drives the **speaker** through the same headphone
   pins in LoudSPK mode, so the amplifier's power follows whichever path the HAL
   opened. **A mixer poke cannot open a path.**

### What actually worked: say it ourselves

The sixth road is to make the announcement the framework refuses to make —
`AudioManager.setWiredDeviceConnectionState`, the same call
`WiredAccessoryManager` would have made. It is `@SystemApi`, so it is reached by
reflection, and it is gated on `MODIFY_AUDIO_ROUTING`, which is
`signature|privileged`. **That is why the kiosk is signed with the platform key**
— see *Platform signing* below. `DUMP` comes along for the same reason, because
the terminal also has to *read* the switch and `getSwitchState` exists on neither
`InputManager` nor `InputManagerGlobal` on this Android 14 build. What does know
is the input service's own dump: `dumpsys input` prints `SwitchValues: 4` with a
cable in and `0` without, and bit 2 is `SW_HEADPHONE_INSERT`.

`audio/JackWatch.kt` polls that every two seconds — a question, not an event,
because there is no callback for a device the framework has decided not to track.
Verified through a full cycle:

```
cable out  ->  SwitchValues 0  ->  "the jack is out — audio back to the speaker"
               dumpsys audio: mMainType=0x0, headset port gone from the policy
cable in   ->  SwitchValues 1  ->  "the jack is in — audio handed to it"
```

### The announcement outlives the app

This one cost a working jack twice, and it is not obvious.

The announcement lives in the **framework**, not in the app. It survives the app
being killed, force-stopped, crashed or reinstalled, because **none of those run
`stop()`**. A fresh `JackWatch` that assumed `announced = false` then read
`SwitchValues 0`, decided the two already agreed, and said nothing — leaving the
tablet routed to a headset that was not plugged in:

```
dumpsys audio          mMainType=0x1                      (MAIN_HEADSET)
media.audio_policy     "Wired Headset" Port 278 available
dumpsys input          SwitchValues: 0                    (no cable)
```

And unplugging could never fix it, because unplugging is exactly the transition
it believed had already happened. `announced` is therefore a `Boolean?` — `null`
until we have spoken in this process — so the **first** reading is always
announced, whatever it says. One redundant binder call at startup, against a
terminal silently routed to nothing.

**The general rule:** any state pushed into a system service must be reconciled
on startup, never assumed.

### Platform signing, and why the deploy is one script

The jack needs `MODIFY_AUDIO_ROUTING` and `DUMP`. Both are
`signature|privileged`, so they are granted only to a build signed with the same
key as the framework — here the AOSP platform test key, SHA-256
`c8a2e9bc…92ab8`, whose framework certificate hashCode is `b4addb29`
(`dumpsys package android`).

**Gradle cannot produce that APK.** `assembleDebug` always signs with the debug
key (`4c7dcfcf`), so the platform signature is a separate step afterwards — and
the moment anyone runs the two obvious commands:

```
gradle assembleDebug && adb install -r app-debug.apk
```

the tablet is quietly back on a debug-signed build, both permissions read
`granted=false`, and the jack stops following the cable. **The app still launches
and looks entirely normal.** There is no symptom except the audio, which is why
this happened twice before it was caught.

So `deploy.sh` welds build → zipalign → platform-sign → **verify** → install, and
refuses to install an APK that is not platform-signed. Two things it checks, not
one: that the APK's signer is the platform key by full SHA-256, *and* that the
tablet's framework is still `b4addb29`, so reflashing with a differently signed
GSI is noticed here rather than discovered later as a dead jack.

> A guard that fails to read its input and then passes is worse than no guard.
> The first version of that check parsed the framework hash into an empty string
> and then matched everything against it.

A signature change cannot be installed over the top, so the script uninstalls
first when it has to — and **re-grants `RECORD_AUDIO` afterwards**, because an
uninstall takes the runtime grants with it and the talk dot is silently useless
without it: it records, gets zeros, and the station transcribes nothing. There is
no permission prompt to fall back on in a kiosk that owns HOME.

### The microphone, and a measurement that was wrong

The terminal has **no speech recognizer of its own** — `cmd package
query-services -a android.speech.RecognitionService` returns *"No services
found"* on this GApps-less GSI. So `audio/MicCapture.kt` records 16 kHz mono
here and the **station** hears it, through `/api/listen/transcribe` to
wyoming-whisper.

Two things worth keeping:

- **`VOICE_RECOGNITION` is dead on this device.** Measured against `MIC`:
  0.0004 against 0.63. My first sweep found them equivalent — it was taken in a
  silent room, so it was comparing two noise floors. A level comparison is
  meaningless without a signal.
- **Wyoming sends the transcript in the `data_length` blob, not inline.** Reading
  the header only gives an empty transcript and a 504 further up. This fix went
  missing once and had to be applied twice, because `app.py` is edited from more
  than one session.

### The wallpaper is the gallery

> "Constantly every five minutes be replacing the wallpaper with the latest image
> being hawked by the Pine Box gallery on the station. I want the lock screen and
> the home screen to always have images from the Pine Box Gallery as they are
> being chosen by the station and being sold."

`gallery/WallpaperWatch.kt`, every five minutes, onto `FLAG_SYSTEM` **and**
`FLAG_LOCK` — set in two calls rather than one, because a build can refuse the
keyguard alone and a single combined call that throws would leave both unchanged.

Which picture, and in what order:

1. **`selling_now`** — the station's own single answer to "what art is being sold
   right now" (#900, app.py ~45587). It folds the three roads that sell things —
   the sales floor `hawking_now`, the ad break `ad_now`, and the gallery press —
   into one dict carrying a bare gallery filename, and it rides on `/api/dj`.
2. **The newest still in the gallery**, when nothing is on the block — which is
   most of the time, since `selling_now` is `None` between spots. Without this
   the tablet would revert to a black rectangle, which is not "always have images
   from the Pine Box Gallery".

Two traps in that fallback. `/api/generations?limit=N` is **newest-first**
(`read_generations` slices the tail and reverses), and it serves `.mp4`/`.webm`
alongside stills — so anything wanting a *picture* must filter by extension.

It reads `StationFeed.snapshot()` when that is fresh and only fetches `/api/dj`
itself when nothing is collecting the feed. That is the single-poller rule, and
it is also correctness: the snapshot goes stale the moment no view is attached,
which on a locked tablet is most of the time, so trusting it outright would hang
whatever was selling when the screen was last unlocked, forever. It runs from the
Application rather than the Activity for the same reason — started from the
activity it would stop at the moment it starts mattering.

Renders are several thousand pixels square and the screen is not, so the bitmap
is decoded at `inSampleSize` and then **centre-cropped to the screen's shape**.
Left to itself the wallpaper service letterboxes or stretches it.

### Wireless adb does not survive a reboot

`adb tcpip 5555` is a runtime mode, not a setting. After a reboot the tablet
pings but refuses adb, and **rebooting it is how remote access gets lost**. Two
recoveries:

- **Wireless debugging** (Android 11+): `adb mdns services` lists both
  `_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp` with their ports, so only
  the six-digit pairing code has to come off the tablet's screen. This is how
  access was recovered without a cable.
- **USB**, then `adb tcpip 5555` again.

Either way, make it permanent once you are back in:

```
adb shell setprop persist.adb.tcp.port 5555
```

Verified: after the next reboot, 5555 came back on its own.

Note that `adb root` **restarts adbd and changes the TLS port**, so a wireless
session must re-discover by mDNS afterwards. Reconnecting by the mDNS service
name rather than the old `ip:port` is the reliable form.

## 9. Making the panel fit a 9-inch screen

"It is still scaled too big... the application is still very cramped even on
mobile... I need to be able to spread the UI out."

Two complaints that pull opposite ways, so the page was surveyed over the
devtools socket in landscape before anything was changed:

```
viewport            1000 x 598 CSS px   (dpr 1.25, 1340x800 physical)
controls on screen  112, of which 94 under 32px tall, median 30
text on screen      123 elements at 9-11px
flex rows           60, of which 22 have neighbours under 6px apart
```

**The type was never too big — most of it was tiny.** What was too big was the
scale: at 1000 CSS px across a 1340 px panel everything renders at 1.34x, so the
furniture ate a 598 px-tall viewport and the content was squeezed into what was
left. Height is the scarce axis in landscape, and nothing was being spent on it.

The fix is `TARGET_CSS_WIDTH` 1000 → **1150**, paid for by a WebView
`minimumFontSize = 12`: the layout gains 15% while the smallest text ends up
*larger* in real pixels than it was. Measured after:

| | before | after |
| --- | --- | --- |
| viewport | 1000 × 598 | **1154 × 690** |
| text under 12 px | 123 elements | **0** |
| rows with <6 px gaps | 22 of 60 | **3 of 21** |
| clipped overflow | 4 | **0** |

> **Keep `tablet.css`'s breakpoint above `TARGET_CSS_WIDTH`.** It was
> `max-width: 1100px` while the target was 1000; raising the target without
> moving the query would leave it not matching and **every tablet rule silently
> off** — which looks exactly like the stylesheet having no effect rather than
> like a bug. It is now 1250.

### Square pads

"The point of the sampler's pads is that they are square pads that I tap on."

The grid was 4×4 of `1fr` stretched across whatever box it was handed — and that
box is square in neither orientation, so pads came out wide in landscape and tall
in portrait. A 4×4 of rectangles is a spreadsheet.

`.pb-padwrap` is a **size container**, so `min(100%, 100cqh)` inside it is "the
smaller of this box's two sides" — the largest square that fits. Four equal
columns and rows with equal gaps in both axes then give square cells with no
per-pad rule. Measured in the real WebView:

| viewport | pad | ratio |
| --- | --- | --- |
| 1066 × 1786 | 189 × 189 | 1.0000 |
| 1154 × 690 | 251 × 251 | 1.0000 |
| 1150 × 1924 | 208 × 208 | 1.0001 |
| 1000 × 1834 | 172 × 172 | 1.0000 |

### CHOP was never a mode

"I am stuck in chop mode. I need the ability to exit chop mode."

There was no chop mode. CHOP is one destructive press that writes sixteen slices
of the selected pad across the whole bank, over whatever was there — but it sat
in the row of toggles wearing the same button as POLY and GATE, so it *read* as a
state, and with every pad relabelled `[3/16]` and no way back, that is exactly
what it became.

Both halves were needed: the bank is snapshotted first — **bytes, not just
labels**, because the chop overwrites the other pads' records and a layout-only
undo would restore fifteen names in front of the wrong audio — and the button now
says what it will do next, CHOP then UNCHOP. One-shot actions (TAP, CHOP, STOP)
are drawn dashed so they never again look like a light that could be left on.

---

## 10. What has been put on it since

* **The slideshow** — [slideshow-tablet.md](slideshow-tablet.md). `~/bin/media-slideshow`,
  the Spark's own 25,000-line PySide6 glass, ported to the **SLIDES** tab:
  the same `/comfy-output` folder, the same `favorites.md`, the same twenty
  transitions, and the SC stack's console folded into one poll because
  eleven subprocesses cannot run here.
* **The overlays** — same document, `#1241`. The readouts are the product:
  the render ComfyUI is working on and its prompt, the per-core CPU, the
  NVIDIA section, the OpenWebUI rolodex with its resident models. One module
  that also runs standalone at `/spark`, and that stops polling the moment
  nobody is looking at it.

* **The headphone jack** — working, after five dead roads. See
  *The 3.5 mm jack* above. The terminal makes the wired-device announcement the
  GSI's framework refuses to make, which is why it is platform-signed.

* **The gallery as wallpaper** — `gallery/WallpaperWatch.kt` hangs whatever the
  station is selling on the home screen and the keyguard every five minutes.

* **The microphone** — recorded here, transcribed by the station, because this
  GSI ships no speech recognizer at all.

---

## 11. Off the LAN: the tailnet road

"I want to be able to connect the tablet up to my phone through 3G or the
localized network and be able to connect and interact with the radio and be
able to start it, have it broadcast to me and be able to download samples to
the sampler."

**The station and the DGX Spark are the same machine.** Worth stating plainly,
because the ask named them separately: `lilspark` is aarch64 with an NVIDIA
GB10 and carries `~/oww-train`. One host, one Tailscale node, no subnet router
and no second hop to arrange.

| | |
| --- | --- |
| tailnet | `tail1fec29.ts.net`, account masterxeon1001@ |
| the box | `lilspark` — `100.74.95.59`, MagicDNS `lilspark.tail1fec29.ts.net` |
| also on it | `iphone184` (the phone), and this desktop, offline since ~89 days |
| Tailscale SSH | enabled 2026-09-12 (`tailscale set --ssh=true`) |
| sshd host keys | ED25519 `SHA256:uDi74jxpAQMe49eTEkTJy+oaokvfcVI6U1x7EVQyzlE` |
| | RSA `SHA256:bxWiwv8E4GMpk3Ejwh+vaAEIoEU0iKTsszjwehC8THU` |

### Three roads, and the terminal picks

`net/Reach.kt` holds an ordered list and uses the first that answers:

    http://10.89.1.246:8096            the LAN, at home
    http://100.74.95.59:8096           the tailnet, from anywhere
    http://lilspark.tail1fec29.ts.net  the same, by MagicDNS name

The LAN goes first because Tailscale will happily carry traffic between two
machines on the same switch and it is a longer path through a userspace TUN —
and the panel is one very large document. The address goes before the name
because `100.74.95.59` needs no resolver, while MagicDNS needs the tablet to
be accepting Tailscale's DNS, which is a setting inside their app and
therefore not something the terminal can promise.

The road is chosen by `StationClient.reachable()`, which the offline banner
already calls on its own retry — so a tablet carried out of the house
re-chooses with no second timer and no "the network changed" listener.

### Two things that will bite

**The network policy fails closed.** `res/xml/network_security_config.xml`
permits cleartext per host BY NAME. A road added to Reach and not to that file
is refused before a packet leaves, and nothing in the failure says so. Both
tailnet hosts are named there now.

**A probe must confirm the STATION, not merely an answer.** `answers()` first
accepted `200..499`, inherited from the old reachable() where the question was
"is the station I already know about up?". As a road chooser that is wrong,
and the first test proved it: pointed at `:8099` — the restart bridge — the
terminal announced "station on the LAN" and loaded the panel from a service
whose whole vocabulary is `{"error": "GET /status or POST /restart/<name>"}`.
It now requires 200 and a body saying `"status"` and `ok`. The case that
matters is a captive portal: exactly what sits between this tablet and the
internet on somebody else's wifi, and it answers everything.

Measured after the fix: pointed at the decoy it logged
`station over the tailnet` and loaded from the second road; pointed at the
real config it logged `station on the LAN`, panel up in 3.5s.

### Why remote listening needs no station change

The served panel contains **no absolute `http://10.89.1.246:` references at
all**, and the feed hands out media as relative paths (`/sfx/<id>?t=<sig>`, and
`media` as a bare filename). Everything therefore resolves against whatever
origin the page was loaded from: load the panel from the tailnet address and
the audio, the API and the sampler's clip cuts all follow it. Nothing on the
station had to learn about Tailscale.

### ConfigStore wrote an explicit key list

`tailnetUrl` and `tailnetName` are settings rather than constants, so a tailnet
address can move without a new build — but `ConfigStore` writes a named list of
keys and they were not on it, so `writeConfig` appeared to work and read back
the compiled-in default. `recordingFolder` was missing from that same list and
had been since it was added, so "download it to the local recording folder"
had never survived a restart. All three are stored now.

### What still needs a human

Tailscale 1.102.4 is installed on the tablet (`tailscale-android-universal`,
SHA-256 verified against Tailscale's published checksum, signature verified).
Two things cannot be done for the operator and should not be:

1. **The VPN consent dialog** — `com.android.vpndialogs.ConfirmDialog`. Android
   is asking the person, not the tool.
2. **The sign-in** — the tailnet is an account.

There is a browser on this GSI (`org.lineageos.jelly`), so the login flow can
complete on the tablet itself. Until both are done the second and third roads
cannot answer, and the terminal simply stays on the LAN — which is the correct
behaviour when it is at home anyway.

## 12. DGX Terminal

"I want to be able to SSH into the Spark. I want to be able to access the
console. I want to be able to type in commands and be able to work through a
terminal in a separate app called DGX Terminal."

A third launcher activity in the same APK, following SparkActivity's shape:
its own label, its own taskAffinity, no HOME filter and no lock task. The
terminal is a thing you open, use and leave; the one screen that must never go
blank is the radio.

### No keys, and that is the whole point

Measured from the tablet before any of it was written:

    100.74.95.59:22   ->  SSH-2.0-Tailscale
    10.89.1.246:22    ->  SSH-2.0-OpenSSH_9.6p1

Tailscale SSH intercepts port 22 for tailnet peers, so the WireGuard tunnel
has already proved who the device is before an SSH packet is sent and the
server authorises on tailnet identity. No private key on the tablet, no
passphrase to type on a nine-inch screen, no `authorized_keys` to maintain,
and nothing to steal if the tablet is lost — revoking the device in the
Tailscale console revokes the shell with it.

The LAN address is deliberately NOT offered as a fallback here, although
everything else in this terminal falls back to it happily: sshd on `:22` would
demand a password, and putting a password box on a kiosk for a road nobody
asked to take is how credentials end up typed into the wrong thing. The app
reads the banner first and refuses anything that is not Tailscale answering.

`com.github.mwiede:jsch` rather than `com.jcraft:jsch` (last released 2018,
cannot negotiate with a 2024 OpenSSH) or sshj (drags in BouncyCastle at
several megabytes).

### Three bugs, and only the third was found by looking

Typing did nothing, and two plausible readings of that were shipped before
either was tested:

1. **the composing region** — a soft keyboard types into an underlined
   composing region and only commits at a space, so overriding `commitText`
   without `setComposingText` loses everything. This was real and is fixed:
   composing text is forwarded as it changes, with what has already gone out
   remembered so a correction rubs it out rather than sending the word twice.
2. **the input connection generally** — guessed at, not the cause.
3. **the actual cause**, found by adding one log point:

        onKeyDown 37 unicode=105 wired=true
        send failed: android.os.NetworkOnMainThreadException

   `send()` wrote to the socket straight from the key callback, which is the
   main thread, and Android forbids network I/O there. Worse than the refusal:
   the failed write left JSch's stream closed, so every keystroke after the
   first said "Already closed" — dead from the first letter with no sign why.

Writes now go through a **single-threaded** executor. Single on purpose:
keystrokes are ordered, and `ls` typed quickly must not arrive as `lsl`.
`resize()` goes the same way — it is also a network write, and it fires every
time the keyboard opens.

The lesson is the ordering: the log point cost one build and settled in
minutes what two readings of the symptom had got wrong.

### The keystroke logging was removed with the bug

While this was being chased every callback logged the character it received.
That would have written any password typed at that prompt into logcat, where
anything holding READ_LOGS can read it. A debugging aid that records what a
person types is a keylogger with good intentions. What is left logs only
whether the keyboard attached and whether the shell was wired.

### The emulator

`DgxScreen` is a character grid with enough VT100 to make `TERM=xterm`
honest — printable text, the control characters, cursor movement, the erase
family, scrolling regions and SGR colour, which covers ls, git, grep, tail -f,
python, nvidia-smi, docker and journalctl. Not the alternate screen buffer's
finer points, DEC line drawing or mouse reporting: vim and htop run and mostly
look right, and are not the reason it exists.

Plain arrays rather than a cell class: a 100x30 screen is 3,000 cells redrawn
on every frame of a `tail -f`, and this tablet has had an ANR from the console
before.

### Staying signed in

Two things were set on the tablet so the tunnel does not need re-establishing:

    dumpsys deviceidle whitelist +com.tailscale.ipn
    settings put global always_on_vpn_app com.tailscale.ipn
    settings put global always_on_vpn_lockdown 0

Lockdown is deliberately OFF. On it blocks all traffic whenever the tunnel is
down, which would break the LAN road and leave the kiosk dead at home during
any Tailscale hiccup.

**Still needs the admin console:** the tablet's node key expires on the
tailnet default. Machines → `trebledroid-vanilla` → Disable key expiry, or it
will ask to be signed in again when the key runs out.

## 13. What comes next

1. **Unlock** — through the app, past the gate above, with the tablet confirming
   on its own screen.
2. **Flash a LineageOS 21 arm64 A/B GSI**, no GApps, with
   `fastboot --disable-verity --disable-verification flash vbmeta vbmeta.img`.
   `fastbootd` is where a driver problem would actually appear, since it
   enumerates differently from the bootloader.
3. ~~**Hardware acceptance**~~ — **walked, and passed.** Speakers, microphone
   and the 3.5 mm jack all work on the GSI; the jack needed the terminal to
   announce the cable itself, and the mic needed the station to do the
   listening. The sampler premise stands.
4. **The kiosk app** — `PineDesktopBridge` so the Windows renderer runs in an
   Android WebView, HOME launcher, lock task, boot receiver, foreground audio,
   and the native Oboe sampler engine.
5. **Wireless from then on** — terminal configuration held on the agent and
   polled by the tablet, so every install on the network shares one master
   configuration, as the station already does for its other settings.

---

## 14. Things that cost time, recorded so they do not again

- No adb on the machine means **no RSA prompt ever appears**. The empty device
  list is the symptom; the missing tool is the cause.
- The RSA dialog does not render on a locked screen or during a system update.
- `Get-PnpDevice` without `-PresentOnly` shows remembered devices; `Present:
  False` is not a fault.
- LMSA downloads to `C:\ProgramData\RSA\Download`, and **deletes the archive
  after extracting it**.
- Lenovo's support site blocks scripted requests outright (403 to plain fetches,
  HEAD requests and browser user-agents alike), so LMSA must be fetched by hand.
- MTK scatter files are YAML wearing an `.xml` extension — and in an LMSA
  package, encrypted YAML wearing a truncated extension.
- A partition image can legitimately ship in more than one wrapping. Verify by
  magic bytes, allow several, and check more than one offset.
- **A platform signature is not sticky.** Gradle signs with the debug key every
  time, so any plain `assembleDebug` + `install -r` silently reverts the tablet
  and takes `MODIFY_AUDIO_ROUTING` and `DUMP` with it. Deploy with `deploy.sh`,
  which refuses to install anything that is not platform-signed.
- **An uninstall takes the runtime grants with it.** A signature change forces
  one, and `RECORD_AUDIO` does not come back on its own — the mic then records
  silence rather than failing, which reads as "it did not hear me".
- **State pushed into a system service outlives the app that pushed it.** The
  wired-device announcement survived kills and reinstalls, so a watch that
  assumed its own default fought a route it had itself set in a previous life.
  Reconcile on startup; never assume.
- **A level comparison in a silent room compares noise floors.** `MIC` and
  `VOICE_RECOGNITION` measured identical until there was something to hear, and
  then differed by three orders of magnitude.
- **The platform keys must not live in a scratch directory.** They did, and the
  directory was temporary. They belong beside the project that needs them.
- **`[hidden]` is a UA type-level rule**, so any class-level `display` out-ranks
  it. That is the whole of the "I still cannot close this overlay" bug.

---

# Part II — the software on it, and how to work with it

Sections 1–14 are how a stock Lenovo Tab M9 was made ours. What follows is how
the thing that runs on it is built, how to build for it, and every way it has
been seen to fail. Written 2026-09-13, after a night that found most of §19 the
expensive way.

If you are an LLM handed this document with no other context: **§15 tells you
how to reach the tablet, §16 how the app is put together, §17 the hardware
surfaces, §19 the faults, §20 how to add something new.** Read §19 before you
conclude anything is broken.

---

## 15. Reaching it, day to day

```sh
export PATH="$PATH:/c/_tools/android-sdk/platform-tools"
adb connect 10.89.1.154:5555
D="-s 10.89.1.154:5555"        # ALWAYS use -s: USB and Wi-Fi are often both attached
```

`adb shell id` returns **uid 0** — this is a userdebug GSI and root is there when
you need it.

### The pid, and why your script will fail without this

`adb shell ps -A | grep pinebox` **returns nothing at random on this device**,
while the process is plainly running. It has cost hours across several nights.

```sh
P=$(adb $D shell "pidof com.pinebox.kiosk" | tr -d '\r\n ' | awk '{print $1}')
```

`pidof` can hand back **two** pids mid-restart — hence `awk '{print $1}'`. Loop
and retry rather than trusting a single attempt. The app's own log is a third
road: `adb $D logcat -d | grep "panel up in"` — field 3 is the pid.

### Looking inside the page

The panel is a WebView, so Chrome DevTools Protocol works over adb:

```sh
adb $D forward tcp:9600 localabstract:webview_devtools_remote_$P
curl -s http://127.0.0.1:9600/json          # -> webSocketDebuggerUrl
node cdp-ask.js "<ws url>" "<a JS expression>"
```

Three helpers exist and the difference matters:

| tool | when |
|---|---|
| `cdp-ask.js` | evaluate, print the result |
| `cdp-ask-long.js` | 45 s budget, awaits promises |
| `cdp-tap.js` | sets `userGesture: true` — **required to start audio or video** |

**The trap:** the kiosk injects its view code with `evaluateJavascript`, so
**injected JS never enters the DOM**. Searching
`document.documentElement.innerHTML` for a function you just shipped finds
nothing, and you will wrongly conclude the deploy failed — this has happened
twice. **CSS does** land in the DOM, so a stylesheet rule is a reliable "did my
build arrive" probe. Better: call the function and see if it answers.

### Screen frozen, nothing responds

Check the **notification shade first**. It takes focus and covers everything and
is indistinguishable from a hung kiosk:

```sh
adb $D shell "cmd statusbar collapse"
adb $D shell "dumpsys window | grep mCurrentFocus"      # names what actually has it
```

Lock-task pinning is a separate thing (`dumpsys activity activities | grep
mLockTaskModeState`) and is usually **NONE** — see §16.6.

---

## 16. How the app is built

### 16.1 One Activity, one WebView, injected views

`MainActivity` owns a WebView that loads the station's panel. Everything that
makes it *the Pine Box* is **injected at document start** from the APK's own
assets — the station serves the panel, the tablet supplies the views:

| bundle | file | carries |
|---|---|---|
| Boot | `bridge/BootAssets.kt` | the logo and splash, before anything else |
| Views | `bridge/ViewAssets.kt` | `assets/pine-views/*` — Script, Listen, Music, Presentation, the rail, the meters, the CRT set, the deaf-watch |
| Sampler | `bridge/SamplerAssets.kt` | `assets/pine-sampler/*` — its own page, its own copies |

**Order is not cosmetic.** `SCRIPTS` is evaluated in list order: models first,
then the views that read them, `rail.js` last because it looks for the globals
the others define. Wrong position, silent `undefined`.

**A file on one surface is not on the other.** The sampler page is a separate
bundle with its own copy of shared files. `sfx-tv.js` lived only in the desktop
shell for weeks, which is why the video window never appeared on the tablet —
the operator was tapping a button whose window did not exist there. A shared
view goes in **both** lists and **both** asset directories.

### 16.2 The bridge — `window.pineDesktop`

`bridge/PineDesktopBridge.kt` plus the shim `assets/pine-bridge.js`. The shim
hangs **one function per method** off `window.pineDesktop`:

```js
await pineDesktop.get('/api/dj')                 // the station, via the APP's HTTP client
await pineDesktop.post('/api/sfx/fill', {road:'video'})
await pineDesktop.jack({on:true})                // hand audio to the cable
await pineDesktop.wallpaper({now:true})
await pineDesktop.revive({now:true, why:'…'})    // restart the terminal
```

**A new bridge method needs THREE edits. Missing the third is the usual bug:**

1. the name in the method set in `PineDesktopBridge.kt` — dispatch
2. a `"name" -> { … }` branch in the `when` — behaviour
3. **`name: promised("name")` in `assets/pine-bridge.js`** — exposure

Skip (3) and `pineDesktop.yourMethod` is `undefined`, with no error anywhere.
(Measured: added `revive` to the dispatch set, rebuilt, and it was still
undefined on the page until the shim line went in.)

**The bridge does not use the WebView's network.** It goes through the app's own
HTTP client. This is the single most important fact for debugging this tablet —
see §19.1 — and the reason anything that must not fail belongs on the bridge.

### 16.3 `PineNet` — the request interceptor

`net/PineNet.kt`, hooked from `PanelClient.shouldInterceptRequest`. It owns two
prefixes and returns `null` for everything else:

- `/vendor/*` — served straight from APK assets (three.js and friends)
- `/api/generations/image/*` — fetched by the **app's** HTTP client, cached on disk

Why: the panel draws ~180 full-size 1024×1024 PNGs as thumbnails, which
saturates an HTTP/1.1 connection pool and starves everything behind it —
measured with `/vendor/three.min.js` still unanswered after three minutes.

Consequence to remember: **images keep loading when the WebView's network is
dead**, because they never touch it. That asymmetry is the diagnostic in §19.1.

### 16.4 `LoopDoor` — the loopback proxy, and why the origin is 127.0.0.1

`net/LoopDoor.kt` runs a proxy on `127.0.0.1:8096`, and the panel is loaded from
**there**, not from `10.89.1.246:8096`. It forwards raw bytes upstream.

This is not an optimisation, it is the only road that worked. `sampler-air.js`
wants an **AudioWorklet** for the broadcast tap, because the fallback
`ScriptProcessorNode` runs on the main thread and *loses* 17–23 % of buffers,
85 ms at a time, whenever the panel is laying out (§8 has the rest).
`BaseAudioContext.audioWorklet` is gated on `isSecureContext`, and the panel is
plain http.

Three roads were tried:

- **a certificate** — none obtainable for a LAN address that is also reached on
  a tailnet
- **a command-line flag** — the flag file *is* read on this device (proved with
  `--force-device-scale-factor`), but
  `--unsafely-treat-insecure-origin-as-secure` never reached the renderer, and
  it would need every road's origin listed
- **loopback** — potentially trustworthy *by spec*, no certificate, no flag,
  and it stays http so the panel's own cleartext media is not blocked as mixed
  content

Measured: a page on `127.0.0.1` reports `isSecureContext: true` with a live
`audioWorklet`; the same page on `10.89.1.246` reports `false` and `undefined`.

**So `location.origin` is `http://127.0.0.1:8096` and that is correct.** Do not
"fix" it. If you see a fetch to 127.0.0.1 failing, the door is not the first
suspect — read §19.1.

### 16.5 Provisioning itself — `KeyDiscovery`

The station embeds its key in every page it serves (`const SERVER_KEY = "…"`),
so a terminal on the LAN provisions itself with one unauthenticated `GET /`
rather than being told a secret by hand. The regex must stay identical to
Electron's `discoverAgentKey`.

### 16.6 What makes it a kiosk

Three separate mechanisms, and confusing them is how a "kiosk" ends up with a
Recents button:

1. **HOME** — declared in the manifest, made sticky with
   `addPersistentPreferredActivity`. Decides where every boot and every
   back-out-of-everything lands.
2. **LOCK TASK** — `startLockTask()`. Without device owner this is only screen
   pinning: a toast, and Back+Recents together lets you out. Usually reports
   `mLockTaskModeState=NONE`.
3. **IMMERSIVE** — whether the bars are drawn. Cosmetic, and the one that keeps
   needing re-applying, because the system restores the bars on every focus
   change.

---

## 17. The hardware surfaces

Permissions held (manifest): `CAMERA`, `RECORD_AUDIO`, `MODIFY_AUDIO_ROUTING`,
`MODIFY_AUDIO_SETTINGS`, `CAPTURE_AUDIO_OUTPUT`, `CAPTURE_VIDEO_OUTPUT`,
`CAPTURE_SECURE_VIDEO_OUTPUT`, `DUMP`, `SET_WALLPAPER`, `WAKE_LOCK`,
`RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE*`, `POST_NOTIFICATIONS`,
`INTERNET`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`.

Several of those are **signature-level** and only exist because the app is
platform-signed (§637 and §18).

| surface | file | the shape of it |
|---|---|---|
| The jack | `audio/JackWatch.kt` | announces the cable to the framework, because this GSI never notices it (§8 and §19.4) |
| Output routing | `audio/OutputRoute.kt` | where the sound goes |
| The mix | `audio/AirTap.kt` | the broadcast captured natively, off the page — the ScriptProcessor version lost 85 ms at a time |
| The ear | `audio/MicCapture.kt` | native capture; a level comparison in a silent room compares noise floors (§14) |
| The sampler engine | `audio/NativeAudio.kt` + `app/src/main/cpp/` | oboe. **Not written by this project.** A build with no engine still installs and the panel's own HTML5 audio carries the show |
| Focus | `audio/MediaFocus.kt` | give the speaker back when something else is in front |
| Camera | `camera/PineCameraService.kt` | **no preview and no Activity** — Camera2 renders into an `ImageReader`, so looking through the camera never takes the terminal off the air |
| Screen | `replay/ScreenReplay.kt` | a `VirtualDisplay` mirrors the real screen into an encoder, held in a rolling ring, extractable through the app |
| Power | `power/PowerWatch.kt` | how long the radio has left, computed rather than guessed — Android only answers `computeChargeTimeRemaining` while charging |
| USB | `gallery/UsbBrowse.kt`, `UsbTarget.kt` | browse and write a stick |
| Wallpaper | `gallery/WallpaperWatch.kt` | the gallery on the home screen and keyguard (§19.2) |
| DGX terminal | `terminal/Dgx*.kt` | ssh to the workstation, no keys stored (§12) |
| Rail | `rail/*` | the side rail, quick jumps, who owns the air |

### The one rule that governs the audio graph

`window.audioScope(el)` memoises **one analyser per element** and adopts
`window.pineAudioCtx`. An element may have exactly **one**
`createMediaElementSource`; a second **throws** and takes the audio with it.

So anything wanting levels **borrows**, never builds. `sampler-air.js` states
this; `pine-meters.js` had to learn it — it called `createMediaElementSource`
itself, threw every time, caught, returned `null` for ever, and the player's
spectrum was blank while the code drawing it ran perfectly. Measured cure:
ink 0 → 4033 on the music meter, 0 → 2569 on the voice meter.

Pads **duck the broadcast** (`PineAir.duck('pad')`, released when nothing is
sounding and no pad is held). If everything reports "playing" and you hear
nothing, check `PineAir.duckState()` before anything else.

---

## 18. Deploying

```sh
cd /c/_tools/pinebox-android/PineBoxKiosk
export JAVA_HOME=C:/_tools/jdk17 ANDROID_HOME=C:/_tools/android-sdk \
       GRADLE_USER_HOME=C:/_tools/_gradlehome
./deploy.sh
```

**Always `deploy.sh`. Never `gradle assembleDebug` + `adb install`.** Gradle
signs with the debug key every time, so a plain install silently reverts the
platform signature and takes `MODIFY_AUDIO_ROUTING` and `DUMP` with it — and the
headphone jack stops working with no error. `deploy.sh` re-signs with
`keys/platform.pk8` / `platform.x509.pem`, refuses to install anything that is
not platform-signed, and prints the proof:

```
android.permission.MODIFY_AUDIO_ROUTING: granted=true
android.permission.DUMP: granted=true
```

If either says `false`, stop. Also: an uninstall takes **runtime** grants with
it, and `RECORD_AUDIO` does not come back on its own — the mic then records
silence rather than failing, which reads as "it did not hear me".

**`deploy.sh` leaves the app stopped.** Start it yourself:

```sh
adb $D shell "am start -n com.pinebox.kiosk/.MainActivity"
```

**A view change still needs a rebuild.** The views live inside the APK, so
copying a `.js` onto the station changes the desktop shell only. Copy to all the
places that need it:

```
…/spark-agent/desktop/renderer/<file>                     # the shell
…/PineBoxKiosk/app/src/main/assets/pine-views/<file>      # the tablet's panel
…/PineBoxKiosk/app/src/main/assets/pine-sampler/<file>    # the tablet's sampler
```

---

## 19. Failure modes, with their cures

### 19.0 The panel's script does not parse — the one every meter misses

**Symptom (2026-09-14, 52 minutes):** the station is on, a record is
playing, the voice ring holds dozens of clips, a listener is registered and
even *holds the air* — and `broadcast/health` says *"Nobody has heard the
DJs say anything for N minutes. The station is on and something is sounding,
so this is not a dead broadcast — the dialogue is not reaching the air."*
LOOK, DEVICES and RELEASE all report nothing wrong.

**Cause:** one JavaScript `SyntaxError` in the control panel's inline script
(served line 36838 of `/`). A rewrite over `app.py` had turned eight
`font: "…"` entries into `font: PineIcons, "…, PineIcons"` and eaten the
trailing comma. A SyntaxError kills the **entire** script block: `pollDJ`,
`djVoicePoll`, the music player — none of it ever existed. The heartbeat
that kept the roster looking alive was the Electron top page's, not the
panel's. `ast.parse` proves `app.py`; it proves nothing about the JavaScript
inside its string templates.

**Signature:**

```
webview   Runtime.exceptionThrown  SyntaxError: Unexpected identifier …
          Object.keys(window).filter(k => /^dj|^poll/.test(k))  -> []
          musicPlayer src=""   sayAudio src=""     (music silent too — the tell)
station   heard_seconds_ago=null  clips_waiting=0  "0 clip(s) handed over"
```

**Check, in one line, after any template edit** (node is on the DGX host):

```sh
K=$(docker exec spark-agent printenv SPARK_AGENT_API_KEY)
curl -s -H "Authorization: Bearer $K" http://127.0.0.1:8096/ -o /tmp/p.html
S=$(grep -n "<script>" /tmp/p.html | head -1 | cut -d: -f1)
E=$(grep -n "</script>" /tmp/p.html | tail -1 | cut -d: -f1)
awk -v s=$((S+1)) -v e=$((E-1)) 'NR>=s && NR<=e' /tmp/p.html > /tmp/p.js && node --check /tmp/p.js
```

**Cure:** fix the line, restart, and then **reload the open pages** — a
station restart does not reload a webview that is already showing the broken
page. On the desktop, `Page.reload` over `--remote-debugging-port`; on the
tablet, the TERMINAL rung.

**And the second half:** once the panel lived again the desktop still played
nothing, because its out-loud switch (`settings.terminals.desktop.play`) was
OFF while the tablet's was ON and the tablet was not polling. The DEVICES
rung refuses that case on purpose (it acts only when *every* switch is off).
`POST /api/broadcast/fix/terminals` prints the switches; round-trip
`GET`→`PUT /api/settings` to turn one on.

### 19.1 The WebView goes deaf — the one that will fool you

**Symptom:** the panel looks completely alive — feed updating, views painting —
and there is **no audio at all**.

**Why it looks alive:** the feed and every API call go through the bridge
(§16.2), which is the app's HTTP client. Images load for the same reason
(§16.3). What has died is **Chromium's own network stack**, and with it every
`fetch`, every `<audio>` and every `<video>` — the only three things the
broadcast needs.

**Signature:**

```
musicPlayer        net=2 ready=0        stuck loading, never plays
djVoiceAudio0/1    src="" or ready=0
djVoiceSeen        stuck  (seen 51 minutes behind)
fetch('/api/…')     TypeError: Failed to fetch in 40–100 ms
                   — a PRISTINE fetch from a fresh <iframe> fails too,
                     so it is not a page-level override
images             still 200 in ~500 ms       <-- the tell
```

**Ruled out, each measured. Do not spend a night on these again:** no proxy
(`settings get global http_proxy` null, Wi-Fi `Proxy settings: NONE`);
Tailscale up but `ip route get 10.89.1.246 uid 10212` goes straight out
`wlan0`; `mediaPlaybackRequiresUserGesture` already false; nothing ducked, all
elements volume 1 and unmuted; `LoopDoor` healthy (two requests on one
connection, 200 each in 0.02 s, keep-alive reused).

**The cure is a fresh process:**

```sh
adb $D shell "am force-stop com.pinebox.kiosk"; sleep 4
adb $D shell "am start -n com.pinebox.kiosk/.MainActivity"
```

Measured: `fetch` went from `TypeError` to `200 in 442 ms` on the instant, and
audio returned. **A WebView reload will not do it** — the network service lives
in the app process, so the same dead stack is handed to the new page.

**The self-heal** is `deaf-watch.js` (a view) + `net/Revive.kt` (the app). It
does **not** watch the audio: "no sound for a while" cannot tell deafness from a
quiet show, and this station has real quiet stretches. It compares the two
roads — *the bridge answers and a plain fetch does not* — which is a pattern no
amount of genuine dead air can produce. Three consecutive strikes, a 25 s probe
budget, and any round where the bridge itself was slow is thrown away.

Two things it had to learn, both measured on this device:

- `setExactAndAllowWhileIdle` is **refused**: *"Package com.pinebox.kiosk, uid
  10212 lost permission to set exact alarms"*. Use `setAndAllowWhileIdle`.
- **The relaunch delay must be ~2.5 s, not 900 ms.** At 900 ms the app came back
  and the panel **never loaded** — no `panel up in` line at all, `listeners=0` —
  because the launch landed inside a process that was still dying, while
  Android was also restarting the foreground activity itself. Two launches
  fighting.
- The rest period lives **on disk**, not in a field: a field is reborn with the
  process, so a terminal that came back still deaf would revive for ever. It
  gives up after three in thirty minutes, because a restart loop is worse than a
  silent screen — you can at least read a silent screen.

**Watch for:** if the probe budget is shorter than the station's worst
event-loop stall, this watch will restart a perfectly healthy tablet. It did
exactly that at an 8 s budget against a station that stalls 10–15 s.

### 19.2 The wallpaper relaunches the Activity

Hanging gallery art makes systemui regenerate the Material You overlays, which
raises `CONFIG_ASSETS_PATHS` (`0x80000000`) — a config change with **no name in
the `android:configChanges` flag set**, so it cannot be declared away and the
Activity is **relaunched**. Measured: seven times in thirty-three minutes, on
exactly `WallpaperWatch.EVERY_MS` (5 min), each taking the operator's scroll
position and folds with it.

Cure: still choose a piece every round, but **hang it only when no view is on
the glass** — `reading` set in `onResume`, `released()` from `onPause`. That is
faithful to `PineApp`'s own note: *"the wallpaper's whole point is to be right
when the app is NOT the thing on screen."* Verified: zero relaunches after.

### 19.3 JS timers freeze; rAF does not

The WebView **suspends JS timers** while `requestAnimationFrame` keeps firing.
Anything that must keep moving — a mark, a meter, a countdown — rides rAF, not
`setInterval`. No web-side cure can reach the timer that would fix it, because
that cure would itself be a timer.

### 19.4 Audio going to a jack with nothing in it

The announcement **outlives the app** (§8), so a stale one routes the broadcast
into an empty socket. `dumpsys audio | grep Devices:` shows `headset(4)` —
which on this tablet is usually **correct**, because a cable runs to a larger
system. Confirm with the operator before "restoring" the speaker.

```js
await pineDesktop.jack()                // report
await pineDesktop.jack({on:false})      // hand it back
```

### 19.5 The connection pool, and leaked media elements

A WebView allows roughly **six connections per origin**, and the panel holds
several long-lived polls. Anything that leaks a loading `<video>` eats a slot
permanently — measured: two orphaned videos at `net=2`, after which **87 fetches
were outstanding and not one completed in 25 s**, including `/api/pulse`.

If you build a floating player, tear it down **by class over the document**, not
through the module's own references. Under rapid cutting the references have
moved on and the old node is left attached, still loading. Removing a `<video>`
does **not** stop it: clear `src` and call `load()` first, then remove the node.

### 19.6 Floating above the views

Every view is `display:none` the moment another tab is chosen and three of them
are separate documents, so anything that must float mounts at **body level**.
Then it has to out-rank the view layer:

```
the kiosk floats every injected view at   z-index 2147483000
the sampler's own overlays                2147483030+
the hold sheets                           2147483046
the lock screen                           2147483050
```

A picture-in-picture belongs around **2147483020** — above the views, below the
things meant to cover it.

Measured before this was understood: the video window was built, playing and
**completely buried**, with `elementFromPoint` at its own centre returning a
script line.

**#1322 — and the same number applies in the shell.** This used to lift the
kiosk only, told apart by `location.protocol`, on the reasoning that 900 was
right in the Electron renderer because that shell's own chrome is at 1000. That
reasoning has not held: the shell now carries the same high bands the kiosk
does — `view-chrome` at 2147483200, the hold sheets at 2147483046, the trace
console at 2147483004, the SC pop-up at 2147483010, the panel's own 3JS windows
at 2147483020 — and its Agent tab is a `<webview>` with a compositing layer of
its own. A set at 900 behind any of those is this same fault on the other
surface, with nothing on screen to say so. **Both surfaces lift.** The 900 in
`sfx-tv.css` is now only the fallback for a surface where an inline style is
refused; `tests/test_sfx_tv_2026_09_12.cjs` asserts the lifted number in a
world with no `location` at all, which is the shell's case.

### 19.7 Stale ANRs

`/data/anr` keeps old traces. **Check the date** before blaming one for
something happening now.

---

### 19.8 The script highlight, and which document the audio is in

The SCRIPT view places its live mark by matching a position against each
row's `from`/`until` window. Those windows are offsets into one welded
file, so the position has to be the DJ voice element's `currentTime` — the
same coordinate — and not a clock estimate. Measured over 308 samples, the
clock estimate was behind the sound in **81.3%** of them, off by more than
three seconds in 58.5%, median −2.99 s; 29.8% of its moves were skips and
20.5% were backward.

It looked for that element with `document.querySelectorAll('audio')`. On
**this tablet that works**, because the panel *is* the document and
`djVoiceAudio0/1` are in it. On the **desktop it never worked at all**: the
SCRIPT view runs in the Electron chrome, whose document holds exactly one
`<audio>` (`desktopRadioPlayer`), while the panel runs inside
`<webview id="radioFrame">` — a separate DOM the chrome cannot reach. So the
scan returned `null` *every* time, not sometimes, and the view silently ran
on the estimator that three tickets had been written to replace.

The tell is that it is **not intermittent**. A timing bug wanders; this one
was a clean 0%. When a renderer feature works on the tablet and never on the
desktop, ask which document it is running in before you measure anything
else.

The cure is a bridge: `webview-preload.js` posts `{id, t, file, duration}`
every 250 ms, `renderer.js` stamps it on arrival, and `window.pinePlayhead()`
returns `null` once the reading is older than 1200 ms.

> **Stale must mean absent.** A bridge that keeps handing back its last value
> pins the mark to one line and *looks* like it is working. That is strictly
> worse than no bridge, because falling back to the clock at least keeps
> moving. The same rule as §19.1: the failure that imitates health is the
> expensive one.

The tablet needs no bridge — it has the elements — but it shares the rest of
the chain, so a script that will not follow on the tablet is a real fault and
not this one.

**The order comes from a ledger, not a clock.** `data/script_ledger.jsonl` is
written *before* a round is audible, keyed `(block, ord)`, assigned once and
never rewritten. The screenplay applies it last, after the older corrective
passes, so what you read is the order the round was written in — including
the SFX guy, who sits where he was rolled in rather than being placed
afterwards by a timestamp. **Everything that has been heard now carries a
`block`/`ord`** (#1339, below), so the absence of one is no longer the
signal it used to be — the element's `scripted` flag is. `true` means the
booth wrote that line down before it was audible; `false` means the station
reached for it and the ledger caught it once it had aired.

**And it reads downwards.** The first cut of that merge gave every row of a
block ONE sort time — the block's earliest — and put unledgered events after
it by their own clock. That keeps a conversation together and it is wrong,
because a block is not an instant: anything that happened *during* a round
sorted to the far side of it. Measured on the live hour: **15 backward pairs
in 365, worst 93.3 s**, and every single one the same shape — `dialogue (in a
block) → action (unledgered)`. A sting thirty seconds into a round was drawn
after the round ended, so the stamps read 08:14:53, 08:14:56, … 08:16:26,
then 08:14:53 again.

So a block carries no single time. Each row keeps its own, and the written
order is held by making those times **monotone** across the block: walking in
`ord`, each row sits at `max(its own stamp, the previous one + a hair)`.
Where the clock agrees with the script nothing moves at all; where `air_at`
was rewritten backwards the row is nudged just far enough to stay behind the
line it followed. Everything then sorts on one axis, so an interjection lands
where it actually interrupted.

After: **0 backward pairs in 558 elements**, 0 order inversions inside a
block, 23 of 23 SFX guy rows still inside their conversation, and 47
unledgered events now sitting *inside* a block — which is the point, because
that is where they happened.

> A script is read downwards. Holding a conversation together is worth
> nothing if it throws the reader up and down the page to do it.

**And one conversation at a time.** Making each row monotone fixed the
reader being thrown backwards and left a second fault standing: blocks
whose time spans *overlap* got shuffled into each other. Measured on the
live hour — 14 of 37 neighbouring blocks overlapped, and the rendered
order came out `55 56 56 55 56 55 57 56 57 56 57`: three conversations
shredded together a line at a time. Every stamp ascends, so it passes the
downwards test, and it is still unreadable.

Only one thing can be on the air at once, so overlapping blocks are a
stamping artefact rather than a fact about the broadcast. They are laid
out one after another — blocks in the order they started, and a block
that would begin before the previous one finished is pushed just past it.
The monotone walk then runs across the whole document instead of
restarting per block, so a conversation is contiguous *and* the page
reads downwards.

Where that correction moved a row, the element carries `air_at` with the
stamp it arrived with. Its presence is the signal: this row is not where
its own clock said it was. Final state on the live hour — **0 backward
pairs, 0 blocks re-entered, 0 order inversions, 38 of 38 SFX rows inside
their conversation**.

**And half the spoken lines had no place in it at all.** The ledger is
written from the booth, and the booth is not where half the air comes from.
Measured on one live hour: **194 of 399 dialogue rows carried no
`(block, ord)`** — 151 gold bars, 33 of the SFX guy's quips, 9 adverts — and
every one of them had aired. They are minted by the fill and rescue roads
and appended straight to the ring, so `script_ledger_commit` never saw them,
and the screenplay had nothing to order them by but raw `air_at`.

That is what "the script jumps around" actually was. Dropped into a ledgered
conversation they push its own turns apart: conversation b90 opened at
element 14 with turn 0, and its turn 2 did not appear until element 39 —
**24 elements of other material between two consecutive turns.**

They cannot be written down before they are audible, because nothing knows
they are coming. So they are written the moment they have been **heard** —
one block each, in air order, by `script_ledger_catch_up`, called from
`airlog_keeper`, whose own docstring calls it *"the one hook that catches all
twenty-five ring append sites"*. Patching the roads one at a time would have
missed the next one somebody adds. A one-row block is contiguous by
construction, so it can never split anything. They carry **`scripted:
false`**, because a reader is entitled to know which lines were planned and
which the station reached for. After: **100% of dialogue rows placed** over
the last three minutes, block runs reading `b126/0..5` and
`b166/0,2,3,4,6,7,9,10,11,13`, with the stings landing exactly in the `ord`
gaps they punctuate (#1339).

> **The metric said it was fine.** Three counters watched that document and
> all three read clean for fifteen minutes while it was wrong. "0 backward
> pairs" was true *by construction* — #1336b rewrites every element's stamp
> ascending **after** the sort, so nothing downstream can measure backwards;
> the check was reading its own output. The other two ranged only over rows
> **the ledger knew**, and every row it knew was in perfect order — the
> fault lived entirely in the rows they could not see. Dumping the actual
> sequence and reading it is what found it. A meter built out of the thing
> it measures cannot fail, and a meter that cannot fail is not evidence.

**And it must not re-sort an hour it knows nothing about.** The whole merge
was gated on `if _ord:` — and `_ord` is the entire 48-hour ledger, not the
hour being composed. So it was true on every compose, including hours that
predate the ledger, and it re-keyed every row on raw `air_at` with the list
position only a third tiebreak. But #1259, #1265 and #1299 express their
results **as positions in that list**: re-sorting on `air_at` throws all
three away. Those hours quietly reverted to the combed `air_at` order that
those passes exist to repair — and then the monotone sweep painted clean
ascending stamps over the top, so they measured perfect. The gate is now the
hour actually having ledger rows; an hour the ledger does not cover is left
exactly as the repair passes built it, which is how it read before #1330
(#1337).

**What the action lines say.** A record entry reads *"A record is spinning:"*
while that record is on the deck and *"A record drops:"* once it has
finished, and carries a `playing` flag the panel tints from. Before that the
two read identically, so a record that began forty seconds ago looked exactly
like one that finished an hour ago — which is what made a script that had
simply not caught up with a track change look like one that had skipped it.
The entry is never queued ahead: `_music_log_append` writes the row when the
record *starts*, so an entry here always describes a record already turning.
The lag it was hiding is the composition cache (20 s) plus the client's own
rest (20 s).

---

## 20. Building something new for this tablet

1. Write the view as a plain IIFE hanging one global off `window`
   (`window.PineYourThing = {…}`). No modules, no bundler — files are
   concatenated and evaluated in order.
2. Put it in `assets/pine-views/` **and** name it in `ViewAssets.SCRIPTS` at the
   right point in the order; a `.css` goes in `STYLES` the same way.
3. If it must also live on the sampler page, repeat for `pine-sampler/` and
   `SamplerAssets`.
4. Talk to the station through **`pineDesktop`**, not `fetch` — the bridge
   survives §19.1 and `fetch` does not.
5. New native capability? **Three edits** (§16.2), and remember the shim.
6. Anything that must not stop when the screen is idle rides **rAF** (§19.3).
7. Floating? Body level, and mind the z-index bands (§19.6).
8. Media? One owner of the audio graph — **borrow** the analyser (§17).
9. Deploy with `./deploy.sh`, then `am start`, then verify by **calling** your
   code over CDP — never by grepping the DOM for it (§15).

---

## 21. Quick reference

```sh
D="-s 10.89.1.154:5555"

# alive?
adb $D shell "pidof com.pinebox.kiosk"
adb $D shell "dumpsys window | grep mCurrentFocus"

# the cure for §19.1
adb $D shell "am force-stop com.pinebox.kiosk"; sleep 4
adb $D shell "am start -n com.pinebox.kiosk/.MainActivity"

# the app's own voice
adb $D logcat -d | grep -E "PineKioskActivity|PineRevive|PineWallpaper"

# audio routing
adb $D shell "dumpsys audio | grep -iE 'Devices:|Current:'"

# is the tablet actually hearing the station?  listeners>0 means it is polling
curl -s http://10.89.1.246:8096/api/dj | python -c "import sys,json;d=json.load(sys.stdin);print('listeners',d['listeners'],'|',d['dialogue_flow']['why_quiet']['why'])"

# screen covered by nothing you can see
adb $D shell "cmd statusbar collapse"
```

---

## 22. The standing rules

- **`deploy.sh`, always.** Platform signing is what makes the jack and the
  routing work, and a plain install silently takes them away.
- **The bridge outlives the WebView's network.** Anything that must not fail
  goes on the bridge.
- **One owner of the audio graph.** Borrow the analyser; never build a second
  source on an element.
- **Measure on the device.** Every number in Part II came off this tablet, and
  several contradicted a reasonable guess.
- **A meter that can only ever print one answer is not a meter.** Two separate
  nights were lost to checks that could not fail — a highlight measured against
  the arithmetic it was testing, and a "0 nodes rebuilt" reading taken during
  the one condition that cannot produce the fault.
- **Ruling something out is worth writing down.** Half of §19.1 is a list of
  things that were *not* the cause, and that list is what makes the next
  occurrence a ten-minute job instead of a night.

---

## 23. Getting the broadcast back

The `⟳` tab on the left edge of the panel (or a 24 px swipe from that edge)
opens **Reinitialise**. One button. It is the thing to press when the room
has gone quiet and you do not yet know why.

It exists because the fault is almost never where it looks. A wedge presents
as silence whether the cause is a shut pause door, a page that gagged itself,
a dead voice engine, a deadlocked floor or a stalling event loop — and the
first four of those survive a restart, which is the reflex it is there to
replace.

### What one tap does

Every rung re-checks and **stops the moment sound comes back**, so a healthy
station pays for almost none of this.

| # | Rung | What it reaches |
|---|---|---|
| 0 | IDENTIFY | Reads every page's own acknowledgments, names the one fault, runs its cure, checks, escalates once |
| 1 | ON AIR | Lifts a pause. Only if one is set |
| 2 | RELIEVE | Stands the writing and recording rooms down so the loop can serve the air |
| 3 | UNGAG | Local: drops this page's own hold, bumps the voice epoch, restarts the player |
| 4 | FLOOR | Takes the floor back from a hold that has gone silent |
| 5 | FLUSH | Advances the feed epoch — every page abandons the clip it cannot start |
| 6 | DRAIN | Sends out audio that already exists: the clips held on the box's shelf, and the lines that could not be rendered when they were written |
| 7 | STOCK | Takes the longest-unheard finished round off the cupboard shelf and airs it out of turn; replays the last segment if the cupboard refuses |
| 8 | DEVICES | Reads every device's out-loud switch; turns them on only if **every** one is off |
| 9 | RELEASE | Releases the audio exclusive so every player may sound |
| 10 | PAGES | Asks **every** page in the house to reload, not just this one |
| 11 | TERMINAL | Force-stops and relaunches **the tablet's kiosk** — the one cure a page reload cannot be |
|   | *listens for eight seconds* | |
| 12 | STREAM | The public door on :8097 and the mp3 mixer behind `/stream.mp3` — probed for real, and the mixer revived |
| 13 | ENGINES | F5, the voice-director and XTTS's reload — the engines the services table does not cover |
| 14 | DEEP | The whole repair tree: engines, the box, routing, the writer's lifeboat, the deaf-device reboot |
| 15 | SERVICES | Steward census — restarts xtts, ollama, comfy, a sick container; warms the music library |
| 16 | RELOAD | Reloads this page, and resumes the ladder afterwards |
| 17 | DISK | Runs the bounded retention sweep and names what is over its cap. Deletes nothing the rules would not have |
| 18 | RESTART | Restarts the station process. About twenty seconds of silence |

### Five of those rungs were unreachable before #1331

Worth knowing, because each one was a night:

- **RELIEVE** was missing although the station's own `AIR_LADDER` puts it
  *first*, with the note: *"the only rung that touches a congested loop —
  every other one assumes the clip never arrived, and a stalling loop
  delivers it late instead."*
- **PAGES** was a `location.reload()` of the operator's own tab. The wedged
  listener is frequently a *different* tablet, and it was never touched.
- **DEEP** and **SERVICES** were never called at all, so a dead voice engine
  got "cured" by restarting the station around it, indefinitely.
- **DEVICES** was nobody's job at all. `play` is the per-device out-loud
  switch, and a terminal with `play=false` that nevertheless claims the air
  gags every other page for a device that then plays nothing — measured at
  #1187: *"the desktop panel re-claimed the air every few seconds while its
  own row read play=false, so the tablet was gagged and the house heard
  nothing."* Releasing the exclusive does not help, because the same page
  re-claims it. The rung acts only when **every** switch is off, which is
  silence by construction and nothing anybody configures on purpose; a
  device deliberately set quiet is left alone.
- **FLOOR** (`_floor_break`) had exactly one caller — the silence branch of
  `dead_air_watch`, which needs 20 s of quiet *and* nothing speaking *and* the
  station unpaused before it will even look. There was no operator path to it.
  It is the cure for the deadlock that put the station off the air for six
  minutes with 134 finished rounds sitting on the shelf.

RELEASE had a fifth, quieter problem, and it took three goes to kill.

It read `health.gagged`, and `/api/broadcast/health` never returned that key.
In JavaScript a missing key is `undefined`, so the condition collapsed to
`!health.holding_the_air` — it fired only when *nobody* held the air, which is
the one case where releasing does nothing, and was skipped whenever a page
really was holding the exclusive and gagging the others. The rung written for
that fault had never once run.

Adding the key was not enough. `page_wedge_state`'s `gagged` means the page
holding the air **stopped polling**; the live fault was the opposite — an
owner polling happily while muting the whole house. So the rung was still
skipped, through 317 seconds of silence, with `gagged=False` and triangulate
saying `gagged` on every poll. Two genuinely different faults wearing one
word. They are reported separately now: `gagged` keeps its meaning and
`solo_gagged` carries triangulate's.

Then the gate went altogether. There is nothing left to gate on — every
branch above returns the moment sound is heard, so the ladder only *arrives*
at RELEASE when nothing is being heard, and releasing is right at that point
whatever the reason. The old else-branch said "the air is held by a page that
is answering — left alone", and a page that is ANSWERING is not a page that
is being HEARD. That distinction is the entire reason this endpoint exists.

> Three diagnostics in a row, each one fixed and each one still lying. The
> fix is never done until it has been watched against the real fault.

### And five more after it (#1338)

That audit asked which cures the operator had no button for. The next one
asked a different question — which *rooms* the ladder never walks into at
all. Five:

- **DRAIN** (6). Two shelves hold finished renders that only their own
  timers drain: the box's hold queue and the render backlog. A starved air
  can be silent standing next to speech that is already on disk. It belongs
  beside FLUSH — FLUSH throws away what the page cannot start, DRAIN puts
  back what the station already made — and it is cheap, because that audio
  exists.
- **STOCK** (7). `unheard_stock_air(force=True)` drops the seven-minute
  interval and the floor test (#1313) and puts the longest-unheard finished
  round on the air out of turn (#1260). Its only callers were watchdog
  timers. If the cupboard refuses it says why, and falls back to replaying
  the last segment.
- **STREAM** (12). Everything above that line is about the speakers in this
  house. The public door on :8097 and the mp3 mixer behind `/stream.mp3`
  are how the broadcast *leaves* it, and neither had a rung: the door is an
  unsupervised startup task, and the mixer's own `running` flag is set true
  before its thread has made a single frame and stays true after that thread
  is dead. The rung deliberately ignores that flag and samples the frame
  counter instead, then revives the mixer.
- **ENGINES** (13). The steward's table is xtts, ollama and comfyui. F5
  carries the clones whenever XTTS is offloaded, and the voice-director is
  the middleman every engine handle goes through — when *it* is the
  casualty, restarting the station around it changes nothing. The director
  is bounced **only when it does not answer**, because a healthy one holds
  every engine loaded behind it. Before DEEP, because a deep ladder asking
  a dead director is asking nobody.
- **DISK** (17). A box with no room left writes nothing — no render, no
  larder, no log — and that fault survives a restart. It presses the
  bounded retention sweep and **names** what is big and what is over its
  cap. It deliberately **refuses** the three purge routes that require
  areas to be named by hand: those take named areas on purpose, and a
  ladder guessing a cutoff is exactly the slip that guard exists to stop.

All five were exercised against the live station.

**A rung that can block past the client's timeout silently kills every rung
after it.** STOCK waits for the line to actually reach the air — a render
*and* a playout — and from the console it ran past **120 s**, at which point
the caller gave up. On a ladder that is not one slow step: the run ends
there, and DEVICES, RELEASE, PAGES, TERMINAL and everything below them
never happen, with nothing in the transcript saying so. It is bounded to
**25 s** now, and the wait was never the work — the round is queued either
way and the page starts it at its next poll — so the honest thing is to
stop waiting and say so (#1340).

And say it in words. The handler's broad `except Exception` sat **above**
the narrow `except asyncio.TimeoutError`, and a `TimeoutError` *is* an
`Exception`, so the narrow clause could never run — and a `TimeoutError`
carries no message, so the transcript read *"the cupboard raised: "* with
nothing after the colon (#1340b). An empty reason is worse than no line at
all: it tells the operator something went wrong and refuses to say what.

### The rung that exists because of §19.1

For a long time the ladder's entire client-side vocabulary was `fixUngag()`
— this tab only — and a page reload. Against the fault documented in §19.1
that is nothing: the WebView's network service lives in the app process, so
a reload hands the new page **the same dead stack**. Two of the rungs were
therefore no-ops on this tablet, and both printed as successes.

`9 TERMINAL` is the cure §19.1 already names. The station has no adb and no
reach into the tablet; the desktop app has both. So the station *stamps*
`kiosk_kick` onto the state the desktop is already polling, and the desktop
runs `am force-stop` then `am start` — the same shape as `reload_pages`,
which is how a flag on the far side of a process boundary gets reached at
all.

It acts only on a **new** stamp, so a station restart — which re-sends the
last value — cannot put the tablet into a restart loop.

> Everything before this could reload a client. Nothing could restart one.

### And it could not reach its own rung eleven

`reload_pages` stamps `_RADIO["reload_at"]`; every open page sees it on the
next poll and reloads 0.8–4.8 s later — **including the operator's own**. The
run was sitting in the eight-second wait with no resume mark written, so
`fixResume` found nothing and it simply ended. Everything below it — STREAM,
ENGINES, DEEP, SERVICES, RELOAD, DISK and RESTART — never ran, and the
transcript's last line read *"10 PAGES asked every page in the house to
reload itself"*, which looks exactly like success.

That is why the deep repair had to be run by hand against a live wedge: the
button could not reach its own rung 11. The mark is now written **before**
the reload is asked for.

Two more from the same audit. **ON AIR never touched the switch** —
triangulate returns `off_air → onair` when `_RADIO["on"]` is false, and the
step only ever looked at `radio_paused()`, so the one cure named for a
switched-off station changed nothing. And **DEVICES now runs before
RELEASE**, because for the `#1187` fault they are cause and symptom:
releasing first hands the exclusive to a second device whose switch is also
off, so the "sound is back" check could never pass.

> **A cure the operator cannot reach during the fault it cures is not a cure
> the station has.** Four of these existed as working code for months.

### Reaching past the button

Every rung is also a step you can run alone, which is what to do when you
already know the answer:

```sh
B=http://10.89.1.246:8096
K=$(curl -s $B/ | grep -o 'SERVER_KEY = "[^"]*"' | cut -d'"' -f2)

curl -s $B/api/broadcast/health          | jq .   # is anyone hearing it
curl -s $B/api/broadcast/console         | jq .   # the whole step table + log
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/look
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/terminals
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/floor
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/drain
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/stock
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/stream
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/engines
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/steward
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/deep
curl -s -XPOST -H "Authorization: Bearer $K" $B/api/broadcast/fix/disk
```

`look`, `speed` and `triangulate` change nothing and are always safe.

**The tune-in page has no rail.** `RADIO_PAGE_HTML` carries no Reinitialise
drawer — a listener there has `retime()` and the one-way unpause and nothing
else. If the tablet is on the tune page rather than the panel, the button you
want is not on the screen you are looking at.

**The Electron shell has a second, separate one-tap.** `panicRecover()` in
`renderer.js` walks `/api/service/restart` → `/api/pinebox/initialize` →
`/api/pinebox/recover`. It does not touch `/api/broadcast/*`, and Reinitialise
does not touch `/api/pinebox/*`. Two buttons, two disjoint trees; if one has
not helped, the other is not a repeat.

## 24. The Pine Cam

A 4K Wi-Fi body camera (`H88_…`, an access point at `192.168.1.254`). It is
held by the **spare USB radio** on the DGX (`wlx984827b6b478`, an RTL8821AU),
never by the station's own (`wlP9s9`, which carries `10.89.1.246` and the
broadcast); `tools/pinelink.py` refuses to run at all unless the station's
radio still holds that address, and the camera's NetworkManager profile is
pinned to the spare interface at priority −10 so it cannot be brought up on
the wrong one. One ffmpeg pulls the RTSP stream and writes two things with
`-c copy`: five-minute recordings under `data/pinelink/clips/` and an HLS
playlist, plus a `frame.jpg` four times a second. That JPEG is what every
surface shows — Chromium plays no HLS without a library this project does
not vendor, and the tablet's WebView is the same engine.

### On the tablet

The tablet has no glass bar to hang a camera button in, so `pine-cam.js`
builds its own: a small pulsing **CAM** flag on the right edge, above the
view rail, that appears only while the link is live and goes when the camera
does. Tap it for the picture-in-picture box — draggable, remembers where you
left it, closes itself if the link drops rather than freezing on the last
frame. (Before #1358 the file answered `undefined` for the station's address
off the desktop and looked for a button that only the Electron chrome has,
so on this tablet it did nothing at all.)

### On the desktop

The **Pine Cam** row in the sidebar reads like the tablet's row: what it is,
whether it is reachable, what it is costing. It is always listed, because a
device that only appears when it is working cannot tell you it is not. The
tools icon beside the fold is the whole ladder from one press: ask the
doctor, press the cure it names, wait for the link, open the picture — or
say plainly that the camera itself is not on the air, because then the next
move is a button on the camera. Under the fold: Look, Troubleshoot, **Reset
radio**, Snapshot, Record, the on-air preference, and the viewer picker.

Record is a **cut, not a capture**: the link is recording continuously
anyway, so the button marks a moment, marks another, and the station cuts
that span out of what is already on disk (`POST /api/pinelink/cut`). Nothing
is missed at the head while a stream opens, stopping is instant, and the
camera is never asked for a second client — these access-point cameras
commonly refuse one. Save As goes through the Electron shell; a page cannot
save a file where you want it.

### Who may see it

Three positions, not a switch: **nobody**, **picked**, **anyone with a
link**. "Picked" is a tick beside each tune-in link on the Share panel, and
the tick is stored *on the link* (`shares.json`), so revoking the link
revokes the camera and no orphan permission is left pointing at nobody. The
tune-in page asks `GET /api/pinelink/mine?t=<token>` — which answers for
that token and lists no one else — and draws the same JPEG in a corner box.
Every branch was measured against the running station: ticked 200, unticked
403, forged tag 403, mode off 403, no token on `:8097` 403. That last one was
a hole this work opened and closed on the same day; see `docs/extending.md`
§6.1.

### When it will not join

The troubleshooter names the fault and the cure, and asks the questions in
the order that matters:

1. **Is the kernel still accepting neighbours?** On 2026-09-14 the camera was
   on, the radio associated, and authentication timed out three tries
   running while every reading said "healthy". The ARP table held 1,019
   entries against a ceiling of 1,024 — five Docker bridges holding ~250
   each — and a kernel that cannot record a new neighbour cannot finish an
   ARP exchange with a device it has just met. `tools/99-pine-neigh.conf`
   raises the ceiling (1024/4096/8192) and lets the collector run; the
   table went from 1,019 to 23 the moment it did.
2. **Does the radio see anything at all?** After refused associations this
   chipset stops scanning entirely — admin-UP, no carrier, zero networks
   with no error. `ip link` down/up does not clear it. **Reset radio** does:
   an unbind/re-bind on the USB bus, through the host bridge
   (`pinelink-kick.path`), because there is no `systemctl` inside the
   container and the old Connect button could never have worked.
3. **Is the camera on the air?** If the radio sees other networks and not
   the camera's, the camera has slept its Wi-Fi to save battery or is out of
   its ten-metre reach. Press the camera's Wi-Fi button; bring it closer.

## 25. The clip doctor and the clip book

### The day the station played no clips

`/samples` inside the container held **zero files** while the same path on
the host held 44 entries and 32,367 video clips. The share had not gone
away; the container's bind had. On the host `/home/ehm_eckx/samples` was
`dev=122` (the CIFS filesystem); inside, `/samples` was `dev=66306` — the
host's root disk. The container was looking at the empty directory
*underneath* the mount.

A Docker bind is resolved when the container is **created** and is
`rprivate`, so a share mounted on the host afterwards never propagates in.
`docker compose restart` does not recreate the container — restarting, the
obvious move and the ladder's last rung, could never have fixed this. Only
`docker compose up -d --force-recreate spark-agent` does. Every reader in
the station answered "no samples", which is indistinguishable from an empty
library, so nothing could see it. `GET /api/sfx/doctor` now prints the tell
first: the device id of `SFX_ROOT` against the station's own data directory.

### The book (#1362)

Four earlier attempts at "the video button must be instant" were all a memo
in RAM in front of the same share walk, so every restart put the button back
at *still warming* for as long as the walk took — and the walk was dying
silently behind an `except Exception: pass`. `data/sfx_clips.db` is a SQLite
book of every clip: path, length, playable. An indexer thread writes it,
commits **per folder**, and starts at boot; a tap is one indexed read on a
reader connection of its own, on an executor of its own, and never touches
the share. Measured with the indexer still walking: `/healthz` 5–22 ms, the
tap 11–25 ms on eleven of twelve; after a restart the book already held
20,724 playable video clips before any walk began.

Two things only measuring found: a random-rowid pick returned the **same
clip four times in ten** (rows are written a folder at a time, so the first
clip after each run of audio wins — it is `COUNT`+`OFFSET` now, uniform);
and the length lookup keyed the ledger by `path:mtime`, a stat on CIFS —
the book hands the length over with the path.

### The popup

A miss on the video button used to print *"still warming — tap again"* for
four different faults, only one of which tapping again cures. It opens the
**clip doctor** instead: the station's verdict, the steps, the counts, and
four thumb-sized buttons — **Rebuild** (every clip cache cleared and the
library read again), **Ping the server** (is the share answering, and how
fast — a slow answer is as much the diagnosis as a failed one), **Query the
folders** (what is actually in each named clip folder), **Try a clip**. The
cure the doctor named gets the accent. One file serves both surfaces:
`clip-doctor.js` uses bare paths where the page is served by the station and
the bridge where the document is `file://`.

### The dead air was not the script

The operator's model was that the hour has holes because the scripts are not
dense enough. `GET /api/deadair` reads the gap ledger and says which of two
*opposite* faults an hour was — a famine (write more) or a stall (take the
named function off the loop). Over 24 hours: **93% of all dead air was a
blocked event loop**, and the record named the blockers. The largest single
one was the sample pool's `publish` callback re-filtering the whole
accumulated list through `sfx_id()` twice per path on every emit, on the
loop, ~2,500 times per walk, once a minute (#1370). The next were the
learning desks writing SQLite synchronously from inside the tint pass
(#1371). `air_first()` now reads the pulse sentinel and stands the desks
down the moment the loop is late rather than after twelve seconds of
silence (#1372). The census carries the numbers; the note
`docs/notes/the-bind-underneath-the-mount.md` carries the day.

## 26. The SCRIPT view's two new controls, and every report's telemetry

**The loop button** beside the video button (#1385) puts the SFX guy into
endless video: clips one after another, chosen at random from the whole
collection, until you press it again. It is a *held* setting on the station
(`/api/sfx/video/mode`, #1366), so it survives a restart and this view
coming and going; turning it off takes effect at the end of the clip on the
tube rather than cutting it. Lit red while it runs. His picture dial
(`sfx_video_share`, default 67) is what decides the mp4:mp3 mix the rest of
the time — two mp4s for every mp3, as asked in #1100.

**The search box** in the same bar (#1385, for #1110): type a word, press
Enter, and the station answers with every time it was said on the air in
the last two days and — the part that was actually asked for — *why*. The
verdict is one of four shapes, each with a different cure: **REPEATS** (a
few lines re-aired over and over; the repetition desk, not a prompt),
**ONE ROAD** (one writing road leans on it; look at what that road is
written from), **ONE VOICE** (a persona or a seat's prompt), or **SPREAD**
(the word is simply common in what the station writes; the crystal's
banned-words list is the lever). Under it: the counts by road and voice,
the most-repeated lines with their tallies, and the airings newest first.
`GET /api/said/search?q=` is the road; the box only draws what it says.

**Every report now carries the station's own account of the moment**
(#1379, for #1094/#1095/#1098). A request filed from the Pine Chat panel —
on the tablet, the desktop or a phone — gets a `### Station at the time`
block appended before its attachments: what is playing, what is being said,
the last five lines, the script position (block/ord), the listeners and
each device's out-loud switch, the loop's pulse, the last hour's dead air
with its verdict, the ladder's LOOK, the tablet's state and the learning
desk. Repeats still fold into the request they repeat, because the gist
stops at the marker. The point is the one #1095 made: *"the station is
playing on the tablet, yet the application is saying it's unable to locate
the tablet"* — the report now arrives with the evidence that would have
settled it.

## 27. The endless set is a playlist, and the desktop's tube lights itself

**Clip after clip (#1395).** The loop button's first cut rang *one* clip, a
second before the one on the tube ran out, and drew it from the memo pool.
Measured on the desktop with the mode lit and "the room is quiet" on the
strip, three things made that gap-ridden: the sets poll `/api/dj/video`
every 2.5 s, so a clip rung one second early was seen up to 1.5 s *after*
the tube went dark; a set discards a clip more than 8 s late, and this
station's loop stalled for 8 s often enough that a stall at the wrong
moment dropped the clip and the tube stayed dark for the whole length of
the one that never played; and the memo pool is empty for minutes after
every restart while the clip book (#1362) already holds tens of thousands
of playable clips. Now the station keeps a short playlist rung *ahead*
from the book: each clip is stamped with a start after the previous one's
end, three deep and about twenty seconds ahead. The sets hold the next clip
before they need it and light each on its own timer ("early is not late"),
so a stall of a few seconds on the station changes nothing on the screen.
`/api/sfx/video/mode` says how far ahead it is — `queued` (clips the sets
hold), `ahead_s`, `book` (48,103 playable video clips today), `rung` (total
since boot). Measured: three different clips on the tablet in twelve
seconds with no black between them; on the desktop the tube's `currentTime`
went 2.5 → 7.5 s across a five-second probe at readyState 4. The picture
door's own rule still holds — no lead, no reservation, no claim on the air —
so an endless set cannot mortgage the show.

**The desktop's tube (#1399).** On the desktop the set lives in the *shell*,
not the panel webview, so it floats over every view — and it used to wait
for the shell to mount it. After a reload the shell never did: `PineSfxTv`
was there, the tube was not, and the loop button lit a set nobody could
see. `sfx-tv.js` now mounts itself when it loads in the desktop shell (base
URL from the station setting, `http://127.0.0.1:8096` as the fallback) and
on any http(s) page with `baseUrl ''`; inside the kiosk the bridge still
mounts it with the tablet's base. Verified over CDP: `.sfx-tv` present with
a playing `<video>` thirteen minutes after a reload. (Numbered #1399 — the
continuity agent's #1397 in `app.py` is a different thing.)

**Pictures are not a stuck queue (#1405).** The reinitialise ladder's LOOK
and the wedge detector counted every delivery the page had *received* and
not *started* as "handed over and not started". With the playlist rung
ahead that read *19 waiting, the head 690 s old* on a station that was
audibly playing — past `PAGE_WEDGE_WAITING` (4), which is to say the ladder
could have cured a fault that did not exist. `page_delivery_waits()` now
excludes picture-only rows and any clip whose `broadcast_ms` is still to
come, and every counter — the wedge state, the LOOK line, the ladder's rung
and the oldest-waiting list — reads through it.

**…and a clip whose moment passed long ago is history (#1410).** A video sting
handed to the tube (`djVideoTv`) acks nothing after "received", so it sat in
that count for ever — eleven of them, the head 568 s old, on a station heard one
second before. A wedge is clips *not starting now*: the count is the last two
minutes (`PAGE_WAIT_LATE_S`), the rest is a ledger. The ack itself — from the
tube on play and skip, in the panel and in `sfx-tv.js` — is written up as open in
the continuity note.

**The set holds the next clip in its hand (#1411).** The station rings the
list ahead; the set used to hold it as URLs and build a `<video>` at the
moment, then wait for tens of megabytes to come over the link — measured on
the desktop as 24 of 39 seconds *not* playing, one dark run of eleven
seconds. Now the head of the queue is warmed: a detached `<video
preload=auto>` starts fetching once the tube reports `canplaythrough` for the
clip on screen (or 1.5 s after its first frame, and at once when a clip
arrives while the tube already has what it needs), and `play()` puts *that*
element in the tube. One warm element at a time, released when played, cut,
dropped as late or the set stops. After: 26 of 39 seconds playing, longest
dark run 8 s — and the rest of the dark is the station's own request
latency while its loop is busy, which is the dead-air work, not the set's.

## 28. The tablet's pace, and the tune-in gallery

**Why the station stuttered (#1413).** Profiled on the PineTab over adb —
`/proc/<pid>/task` by thread name and the Chrome profiler over the WebView's
devtools socket — the tablet had **five cores busy** with the video set OFF:
the WebView's main thread saturated, its WebAudio render thread at ~80% of a
core, the kiosk's in-process GPU thread, `RenderThread` and the Mali backend
another ~150% between them. The page was animating at 60 fps under a view
that covered most of it: two bar scopes (`drawScope`, `paintScope`), the
meters, the cover flow, two 3JS scenes, the marquee — twelve
`requestAnimationFrame` loops — and, when those were paced, still 72% of the
main thread inside Chromium's own style/layout/paint: `document.getAnimations()`
counted **380** — `rhetFloat` on 110 `<i>`s of the rhetoric cloud, `left/top/
filter` transitions on its words (a layout *and* a repaint every frame), and
`pendSweep`/`pendBar` on 29 pending rows. The audio engine shares those cores;
that is what a stutter is.

The cures live at the top of the panel script and are tablet-only (the
kiosk's WebView calls itself `Linux; X11; TrebleDroid`, not Android, so the
key is *not Electron and Linux*): `#1413d` paces every `requestAnimationFrame`
to every fourth frame (15 fps) with one wrapper the injected views inherit —
`cancelAnimationFrame` follows the re-armed id; `#1413e` injects a stylesheet
that switches those animations off; `#1413a–c` throttle the two scopes and
the meters themselves and read `clientWidth` once a second instead of once a
frame (a layout read forces a layout of a document the feed keeps dirty).
The desktop keeps 60 fps and every animation.

**The tune-in gallery takes the clip (#1414).** The tailnet page has had the
machinery all along — `tvPoll` polls `/api/dj/video`, and `#galleryStage.tv`
swaps the artwork for a muted `<video>` at the clip's on-air moment, corrected
by the listener's own lag — but it read `data.videos` and the ring answers
`data.clips`, so the stage never took a picture; every other surface saw the
SFX guy's clips and the tailnet listener kept the painting. Fixed, with the
caption from the clip's `sting`, and the floating set no longer offered a
second copy on a page that has a stage to give the clip to.

**A frame is asked for only when a group is due (#1413f).** The first pacing
wrapper skipped callbacks by re-arming a *real* `requestAnimationFrame` on
every skipped frame, with a counter loop at every vsync besides — so the page
still produced a frame at every vsync and Chromium ran the full
style/layout/paint/commit lifecycle for each: traced on the tablet as
`ProxyMain::BeginMainFrame` at 66% of wall time with the callbacks themselves
at 15%. Now callbacks queue and one real frame is asked for per 67 ms group;
between groups the page asks for nothing. Measured after: rAF requests 7/s.
What the trace named next was not an animation at all — the SCRIPT view's
`paintFeed` re-dressing every feed row on every poll, ~1,000 layout
invalidations a second (#1413g, below).

**The hand-back is one of the slideshow's transitions (#1415).** On the
tailnet page, when a clip ends and the gallery comes back, the stage keeps
both pictures up for 600 ms and runs one of the ported `media_slideshow`
effects at random — `slide, swirl, rotate, flip, fold, bump, bash, unroll,
origami, sand, cube, tv, crt, vaporwave, unfold, liquid` — the same
`sl-t-<name>` + `sl-in`/`sl-out` classes the tablet's slideshow uses, from the
same `slideshow.css`, now served through the public door. `mosaic` and
`shatter` are built by the slideshow's own JS (a canvas resample, tiles) and
`delete` is its 900 ms special, so those three stay out. The artwork keeps
rotating underneath the whole time, as before, and the stage gets the
slideshow's `perspective` so `flip` and `cube` have a camera.

**An SFX slider on the tailnet page (#1416).** A third level beside *music*
and *DJs*: **SFX**, default 60%, kept in this browser like the other two
(`pbfmSfx`). It sets the volume of the clip on the gallery stage — which had
been muted for good, so once the stage took the clip (#1414) the tailnet
listener would have seen it silent — and of any sting the page plays through
its voice element, and it is handed to the floating set where a page has one.
At 0% the stage video is muted rather than merely quiet. The listener pressed
play to get here, so an unmuted clip is allowed; if the engine still refuses,
the picture goes up muted rather than not at all.

**Same-value writes are dropped on the tablet (#1413g).** Counted over five
seconds: 158 of ~200 `textContent` writes set the value already there
(`spTitle`, `spWho`, `spAt`, `spLen`, `spNow`, on every beat), and Blink
replaces the text node and invalidates layout for each; likewise a style
property or an attribute set to itself. On the tablet those writes are
dropped at the prototype, where every writer meets them. Measured after the
whole series (#1413a–g): the WebView process 289% → 157%, the kiosk 255% →
132%, the audio render thread with a third of a core to spare, main-thread
task time 98% → 84%.

**In endless mode the tube belongs to the cycle (#1417).** "Whenever endless
video mode is active, don't have the SFX guy play a clip during a clip he is
already playing. Have him do it after." A video sting went down the voice
feed to the page's *own* little tube (`djVideoTv`, with its own queue) while
the set played the cycle's clip — two pictures, two sounds, at once. Now,
while the loop button is lit, the SFX guy hands his clip to the cycle
(`sfx_cycle_request`), which rings it in turn, after the one on the tube; the
cycle keeps one clip rung ahead instead of three (`SFX_CYCLE_QUEUE` 2,
`SFX_CYCLE_AHEAD` 12 s) so "after" means the next slot, not a minute later,
and the warm slot (#1411) still has a clip's length to fetch it. His clip
gets the same feed row and history entry it always did, marked `endless`. An
audio-only sting waits for the tube to be free — in endless mode that is his
next cadence after the set has nothing planned. `/api/sfx/video/mode` shows
`asked`: his clips waiting their turn.

**"Suddenly the Pine Tab stream started stuttering" (#1420).** Not the
station (its pulse was calm) and not the frame pipeline (paced): the WebView's
audio render thread was at **103% of a core**, up from 33% after a reload
twenty minutes earlier. `sampler-air.js` — the sampler's record-from-the-air
tap — hooks `HTMLMediaElement.play` and taps *every element that plays*: a
`createMediaElementSource` plus the panel's analyser, cached by element and
connected for good. The SFX guy's set builds a **new `<video>` for every clip**
(#1312), so with the endless set on the graph grew by one dead source per
clip — measured after a reload: four new sources a minute, all on
`VIDEO.sfx-tv-tube` — until the render thread could not keep up, which the ear
hears as a stutter. Now only an element with an id (the station's fixed
players) is tapped, and never a video; a clip is heard through its own
element and is not sampled from the air. Both copies carry it: the tablet's
(`pine-sampler/sampler-air.js` in the kiosk, the one with the worklet) and the
desktop shell's.

## 29. The mixer dot

**A dot on the player card, and four sliders (#1419).** "Put a dot here that
whenever I click it or tap it it brings up a pop-up that shows volume sliders
for the voices, the music, the SFX, and the videos … and have it retain these
settings and remember it next time." The dot sits in the top-right corner of
the SCRIPT view's player card. Tap it and a sheet opens with **Voices, Music,
SFX, Videos** (0–100%) and a Reset. The levels are multipliers on top of
whatever the station and the shell already set, kept on *this device*
(`localStorage.pineMixer`) and applied again at load, before the dot is ever
touched.

How it reaches the sound, which differs by surface: on the tablet the view is
injected into the panel page, and the panel's `window.pineMixer` applies the
levels where it writes them — the music gain node, the voice elements (a
sting, flagged `pineSting` at play time, takes the SFX level; a line takes
the voices'), the page's own tube and the set (`PineSfxTv.level`). On the
desktop the view runs in the shell, whose `window.pineMixer` (same name, same
shape) folds the levels into the master × share arithmetic it already
injects into the panel webview (`__pineDesktopMixer`, by what each element is
carrying: a video, a sting, music, a voice) and into the SFX television's
level. Inside the desktop app the panel's own copy stays at 1 so the two
never multiply.
