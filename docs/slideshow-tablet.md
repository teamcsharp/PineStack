# The slideshow, on the tablet — #1240

`~/bin/media-slideshow` is 25,000 lines of PySide6 that has been the Spark's
own glass since May. The operator asked for it on the PineTab: the same
pictures, the same settings, the same connection to the SC stack — not a
second gallery that happens to show renders.

This is what could be moved, what could not, and why the difference is the
whole design.

---

## 1. What the desktop application actually is

It is not a slideshow with a diagnostics panel bolted on. Reading its class
list, roughly half the file is the SC stack's console:

| | |
| --- | --- |
| The show | `SlideshowView`, `Playlist`, `Favorites`, `HotLoadQueue`, 20 transitions, the trash disc |
| The stack | `ServiceLogTailer`, `SysMonTailer`, `NvidiaSampler`, `RamActionTailer`, `CFreeActionTailer`, `WeightTailer`, `ToolServersTailer`, `SCStatusTailer`, `ReachyStackTailer`, `PySpyTailer`, `StackActionTailer` |
| The models | `LLMDiscovery`, `ConversationFeedTailer`, the OpenWebUI reader, the ComfyUI workflow analyser |
| Keeping itself alive | `MemoryGuard`, `IdleInhibitor`, `SelfHealRunner`, a freeze watchdog off the event loop |

Every one of those eleven tailers is a **subprocess** — `nvidia-smi`,
`py-spy`, `docker`, `ssh ehm_eckx@lilspark`. That is the fact that decides
the shape of the port.

## 2. What the tablet is

A WebView on a GApps-less LineageOS GSI, on a MediaTek MT6768, measured at
**148 MB free under a load average of 25**. It reaches exactly one HTTP
origin and can spawn nothing.

So the split is: **the reading stays on the station**, where those things
are already running on their own clocks, and **the tablet gets the view**.

## 3. What is genuinely shared, and what only looks shared

This is the part worth being exact about, because "ported" can mean two very
different things and only one of them is what was asked for.

### The material is the same material

`compose.yaml` binds `../ComfyUI/output` to `/comfy-output`, and the desktop
app's own diagnostic names `root dir /home/ehm_eckx/ComfyUI/output` — the
host side of that same mount. Nothing is copied and nothing is mirrored:

* the playlist is that folder, scanned (1,357 files at the time of writing);
* every picture is served straight off it;
* **`favorites.md` is the same file.** `class Favorites` writes it *next to
  the media*, not in a config directory, so it is inside the mount. A like
  on the tablet is a line in the file the box reads.

Verified live: a tap on the tablet took the file from 3 favourites to 4, and
the station read it back as 4.

### The settings are the same settings — with one compose line

`screensaver_state.json` does **not** live next to the media. It sits beside
the app's `output.md` in the launcher's directory, `~/bin`, and that was
never mounted. So `/api/slideshow/state` reports **which file it read**:

```
"source": "station"   — ~/bin is not mounted; the tablet keeps its own
"source": "host"      — this IS the desktop app's file, shared both ways
```

and the tablet's own stack panel prints the same thing rather than implying
a link it does not have. The line has been added to `compose.yaml`; it needs
a **recreate**, not a restart:

```
docker compose up -d --force-recreate spark-agent
```

A write from the tablet **merges**. The desktop app persists keys this one
has no opinion about — the two dragged diagnostic circles, the service
panel's cyberpunk colours — and a tablet that wrote a whole state object
would silently reset them on the box's next launch.

### The tailers could not come, and are not pretended

`/api/slideshow/stack` answers the console in **one request**: the folder
and its growth, the GPU off the station's own sampler slot, ComfyUI's queue,
the event loop's pulse report, and `system_stats`.

It is one request because of a measurement, not tidiness:
`pine-media-origin.js` records **38 concurrent requests to this station
producing a 46-second media stall on this tablet**. A slideshow is the worst
possible shape for that hazard.

Two things are deliberately *absent* rather than empty:

* **No GPU utilisation dial.** `_gpu_temp_blocking` asks nvidia-smi for it,
  but `gpu_temp_refresh` copies only `c`/`zone`/`how` into the slot. A
  `util` field would have been permanently null dressed as a reading. (The
  figure does appear in the `system_stats` line, which reads it separately.)
* **No claim about the desktop process.** `/api/slideshow` has said since
  #1165 that this container has no shared PID namespace and cannot see
  whether the slideshow is running. That is still true and still said.

## 4. The station's side

| Route | What it is for |
| --- | --- |
| `GET /api/slideshow/playlist` | the whole folder, paged, filtered, with favourite flags |
| `GET /api/slideshow/playlist?since=` | the hot load — only what is newer |
| `GET /api/slideshow/media/{file}` | the bytes, **with Range**, and `?w=` thumbnails |
| `GET/POST /api/slideshow/favorites` | the desktop app's own `favorites.md` |
| `GET/POST /api/slideshow/state` | `screensaver_state.json`, both directions |
| `POST /api/slideshow/aside/{file}` | out of the rotation, still on disk |
| `GET /api/slideshow/stack` | the SC stack, in one answer |

**Why the media route is new.** `/api/generations/image` reads the whole
file into memory and answers with it — right for one picture on the panel,
wrong for both things a slideshow does. It has no `Accept-Ranges`, so a
video cannot be sought (`video-wall.js` already had to download clips whole
to work around that), and no small size, so a filmstrip of seven thumbnails
would have cost seven full-size PNGs. **Measured: 1,229,882 bytes for the
picture, 5,084 for its 128px thumbnail — 241× smaller.**

The folder scan is cached for 8s under a lock. #1237 is the standing lesson:
the draw walked 7,180 clips twice every three seconds because nothing held
the result.

## 5. The tablet's side

`pine-views/slideshow.js`, `slideshow-source.js`, `slideshow.css`, reached
by a **SLIDES** tab on the right-hand rail.

### The keyboard is gone, and that changes the controls

The desktop app is driven by twenty single keys. Each becomes a surface, and
the key letter is printed on the control anyway, so an operator who knows
the box does not learn a second vocabulary:

| On the tablet | On the box |
| --- | --- |
| swipe left / right | `←` `→` |
| swipe up / down | filter pictures / video |
| double tap | `L` — like |
| press and hold | `DEL` — the destructive menu |
| tap | show or hide the bar |

**The two ways to remove a picture are not one tap apart.** The desktop's
trash disc has an outer ring that *moves* an item into `smut/` — out of the
show, still on disk — and the unlink is a separate act. Under a thumb on a
nine-inch screen, an undoable and an un-undoable act had to stay separated,
so both live behind a sheet and the unlink asks twice.

### All twenty transitions

The same list in the same order, so "cycle" means the same thing on both
screens and a state file written by either names something the other can
show — pinned by a test that reads `app.py` rather than trusting that both
were edited.

Eighteen are CSS keyframes on transform, opacity and clip-path only; a
full-screen image animated on `width` or `top` is a repaint of the whole
glass per frame on this GPU. Two could not be faked and are not:

* **mosaic** genuinely resamples through a canvas in four steps — CSS has no
  pixelate, and a blur is a *different effect* that reads as the tablet
  being out of focus;
* **shatter** clips eight real shards and throws them (eight, not the
  desktop's many, because each is a composited layer).

Where a QGraphicsView effect has only an approximation here, the CSS says so
in the block.

## 6. Two faults found by building it

**The view gave up for good on one miss.** The first playlist request
answered `timeout` and the view showed a note and stopped — a black screen
for the session. The same request from the same WebView a minute later took
**242 ms**. Nothing was wrong with the route: `rail.js` reopens the
remembered view 1.2s after boot, exactly when the panel is pulling a
two-megabyte document, and OkHttp allows five requests per host. *Busy* and
*down* need different behaviour, so a failure now backs off — 2s, 4s, 8s,
capped at 30 — and the note says which it thinks it is.

**A finished request stayed "in flight" for one microtask.** Found by a
test, not by reading. The gate settled the caller's promise and cleared
`inflight` in a later `.then`, so anything asking in that window got the
finished promise *past its own maxAge*. It made the hot-load poll wrong: two
"anything newer?" questions in one turn produced one answer, so a stale
*yes* was possible. The slot is now cleared before the caller is answered.

**And one of layout.** `console-line.js` welds a fixed one-line readout
across the foot of every screen — measured at 26px — and the control bar was
drawn underneath it, with the key letters clipped off every button. The bar
now measures that line at mount and publishes it as `--sl-console`, so a
change to that file moves the bar rather than breaking it.

## 7. Tests

```
tests/test_slideshow_tablet_2026_09_12.py    12   the three shared files
tests/test_slideshow_view_2026_09_12.cjs      9   the gate, and the two lists agreeing
```

The Python ones pin the three files the two applications share: every shape
`class Favorites.reload()` accepts, a `favorites.md` written **byte-for-byte**
as `Favorites._write` produces it, and a state write that keeps the keys the
desktop app owns. The Node ones pin the traffic gate — that two callers
share one request, that the station never sees two of this view's questions
at once, that a runaway caller is refused with a sentence — and read
`app.py` to prove the twenty transitions still match.

## 8. Deploying a change

The view files live in **two** places and are kept byte-identical:
`desktop/renderer/` (the Electron app, and the tracked copy) and
`PineBoxKiosk/app/src/main/assets/pine-views/` (bundled into the APK).

```
# station routes:  app.py is bind-mounted, but uvicorn has no reload
POST /api/service/restart  {"name": "spark-agent"}

# tablet views:    assets are bundled, so it is a rebuild, not a reload
gradle assembleDebug  &&  adb -s 10.89.1.154:5555 install -r app-debug.apk
```

A renderer edit that is not copied to the assets tree is a desktop that
changed and a tablet that did not.
