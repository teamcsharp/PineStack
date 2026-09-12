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

---

# The overlays — #1241

> "The slideshow is one thing, but the overlays of the elements is the most
> important component and that's what I need."
>
> "Whenever I would be looking at that slideshow, I would be getting overlays
> that would be telling me everything that was happening with backend
> components in a detailed fashion."

#1240 put the pictures on the tablet and folded the telemetry into a single
summary sheet. That was backwards, and this is the correction: the desktop
application is a **wall of readouts with renders playing behind it**, and the
readouts are the product.

## 1. One module, four ways in

> "SC stack should be its own application that I'm able to access... I wanted
> to be able to access the media slideshow as its own application with all of
> its functionality inside of that, while also being able to access it as a
> pop up inside of Pinebox tab."

`desktop/renderer/spark-overlays.js` is the whole of it, and `mount(host,
{mode})` is the whole contract:

| Way in | What it is | Mode |
| --- | --- | --- |
| **Its own app** — the **SC Stack** icon | `SparkActivity`, its own launcher entry, its own task in Recents. Opens on `/spark?pictures=1` | `overlay`, renders behind |
| **A pop-up** — the **SC** tab on the rail | `SparkOverlays.popup()`: a real floating window, dragged by its bar, resized from its corner, closed with ✕ | `dashboard`, in a frame |
| **Full-bleed** — the **SLIDES** tab | the slideshow view, overlays over the pictures | `overlay` |
| **Any browser** — `GET /spark` | a phone, a laptop, a second screen. `?pictures=1` for the renders | either |

**`SparkActivity` is deliberately thin, and that is the point.** `MainActivity`
is a kiosk — it owns HOME, locks the task, and injects every view from the
APK's own assets, so changing one needs a rebuild. `SparkActivity` loads a URL
and attaches the bridge. Everything it shows is served from
`desktop/renderer/`, so **editing an overlay changes what the app shows on its
next launch with no APK in the loop.** What it still needs from native is only
the bridge: a like writes to `favorites.md` and a setting writes to the desktop
app's own state file, and both need the bearer.

It is **not** a kiosk: no HOME filter, no lock task, Back leaves, and it pads
itself for the system bars rather than going immersive — an app you are meant
to be able to leave should not hide the button you leave it with.

Only the kiosk's bundled copy is a second source, and only because its WebView
refuses the `file:///android_asset/` → `http://` crossing (`BootAssets.kt`).

**The pop-up is one at a time**, remembers where it was put (clamped on
restore, because a corner remembered in landscape is off the side in
portrait), and asks the station nothing once it is closed — its `active` gate
is simply whether it is still in the document.

## 2. The widgets, and what each is a port of

| Widget | media-slideshow class | What it actually shows |
| --- | --- | --- |
| `activity` | `TopActivityBanner` | the render happening now — model, size, sampler, scheduler, steps, cfg, LoRAs, node count, output prefix, elapsed, estimated progress, the **prompt text**; the board and the last four renders when idle |
| `perf` | `PerformanceGraph` | rolling CPU / RAM / GPU plots, **20 per-core bars**, load average, uptime |
| `stats` | `StatsPanel` | memory / CPU / disk / swap gauges, then the NVIDIA section: utilisation, temperature, power, fan, SM and memory clocks |
| `owui` | the OpenWebUI tab | version, auth, **resident models and their VRAM**, models / ollama / chats / tools / functions / knowledge / prompts / memories, and the latest chat titles |
| `services` | `ServiceLogPanel` | all 17 services in rotation, each with what it is *doing* |
| `station` | — | the station's own event loop: stalls, worst, held up, and its written verdict |
| `temp` | `TempReadout` | the hottest sensor, huge, flipping °C/°F on the desktop's four-second cadence |
| `ramring` / `tempring` | `RamCircle` / `TempCircle` | the ring gauges |

## 3. What could not be ported, and is said rather than faked

Three of the desktop's features have no road from a container, and the
payload names each one with its reason (`unavailable` in
`/api/slideshow/backend`):

* **The task list, "kill the biggest RAM hog", "kill the thermal
  contributors".** No shared PID namespace, so the host's processes are
  invisible. The rings still draw; touching one says why it cannot act.
* **`docker logs` tailers.** The socket proxy is restarts-only by design
  (`compose.yaml`: *do NOT re-add CONTAINERS=1*). `services_census()` probes
  each service live instead, which for a readout is better than a log tail.
* **The process's own FPS and RSS.** On the tablet those would be the
  WebView's, which is not a fact about the Spark.

And two fields are **absent rather than zero**:

* **GPU utilisation is not in the `_GPU_TEMP` slot** — `gpu_temp_refresh`
  copies only `c`/`zone`/`how`, so a `util` there would be permanently null
  dressed as a reading.
* **VRAM on a GB10 is `[N/A]`** — unified memory. The panel says so and
  points at the memory gauge, which is the same silicon.

## 4. The progress bar is an estimate, and says so

`/queue` says *what* is running, never *since when*. So `spark_overlays.py`
keeps state across polls exactly as the desktop's `_http_prev` does: a prompt
id that appears gets a timestamp, and one that disappears records how long
**that shape of workflow** took, keyed on model + sampler + resolution +
steps. The next render of the same shape is measured against it.

The bar prints its own basis underneath: *"estimated against the last render
of this shape (77.1s) — ComfyUI reports no progress over HTTP."*

Node-by-node progress exists, on ComfyUI's websocket. Holding that socket open
would mean this process — which is also recording a live radio show — carrying
a second event-loop client and reconnecting it whenever 8188 restarts. The
signature estimate costs one dict.

## 5. It sleeps

> "Make sure that we're only pulsing whenever we are in the tab and we're
> actually receiving and accessing the information. Otherwise it needs to
> sleep and relax."

The polling interval is **cleared**, not merely skipped, whenever:

* the app or browser tab is in the background (`document.hidden`), or
* `rail.js` has the view mounted but closed, or
* the operator pressed `S` and put the layer away.

What remains is a 4-second check that touches the DOM and nothing else.
`visibilitychange` short-circuits it in both directions. Measured on the
tablet: **2–3 fresh readings per 11 s with the view open, and zero — the
timestamp does not move at all — with it closed.**

Nothing in that test looks at the station. Not whether it is on air, not
whether it is paused, not which Pine Box tab is in front: the box goes on
having cores and a GPU while the radio is silent, and a monitor that stops
reporting because the show stopped is useless exactly when someone is looking
to find out why. A station that does not answer is likewise a reason to keep
asking — the interval survives, and a line says how many polls have been
missed.

## 6. Fitting on the glass, both ways up

> "Make sure the accommodations are taken for the resolution and display size
> so the elements are fitting on screen and aren't overlapping and be trimmed
> off screen." / "I want it to be compatible in both landscape and portrait."

The first version pinned each widget to its desktop counterpart's corner. On
a 1340×800 tablet two widgets shared every bottom corner and the right-hand
column ran under the rail. That cannot be nudged into correctness, because
nothing *stops* two absolutely-positioned boxes occupying the same pixels.

So the layer is a **grid of four scrolling regions**:

```
landscape   [ left | picture | right ]   with a top and a bottom band
portrait    the picture on top, every readout in one scrolling band beneath
```

Regions cannot overlap by construction, and each scrolls, so a column taller
than the glass is reachable rather than cut off. `tools/overlay-fit-probe.cjs`
drives a headless Chrome through **seven sizes** — the tablet both ways, a
1080p desk, a phone, a small window, in both modes — and measures overlap,
clipping, content overflow and the sleeping. It exits non-zero on a fault.

### Three traps this found, all invisible to the eye

1. **`padding-right` does not inset an absolutely-positioned child.** The
   host reserves the rail's strip with padding; the containing block for an
   absolute child is the padding *box*, which includes it. The panels ran
   under the rail's tabs, which paint over them at z-index 2147483001.
2. **A module cannot assume its host's `box-sizing`.** At 800px the band's
   columns were 256px and a widget rendered 270 — its padding and border
   added outside the width. Exactly the 6px overlap the probe reported.
3. **`offsetParent` is always null for `position: fixed`.** The visibility
   test used it, so on a fixed host the monitor slept on a page plainly being
   looked at.

And one of timing: at mount the rail's own box measured **0px wide** — built
at boot but not yet laid out — so the inset came out zero. It is re-measured
after a settle and by a `ResizeObserver`, which is also what makes a rotation
work.

## 7. Keeping the station out of trouble

The station is a single process that is also recording a live show, and its
own pulse report regularly counts thirty-plus stalls in ten minutes. So:

* **one request in flight, ever** — every widget paints from the same answer;
* the payload is cached 2 s, the folder scan 8 s, **`nvidia-smi` 6 s** (it is
  a process spawn; at the payload's rate that would have been 1,800 an hour);
* the **census and the OpenWebUI sweep never block the answer**. They refresh
  behind it and a stale copy is handed back. Measured: the first poll after a
  restart went from *timing out past the tablet's 20 s read limit* — which
  drew nothing and reported the station down — to **2.4 s**, then 0.76 s, then
  0.1 s cached;
* the twelve OpenWebUI endpoints are asked **concurrently**, not in a row.

## 8. Tests

```
tests/test_spark_overlays_2026_09_12.py   16   the workflow reader
tools/overlay-fit-probe.cjs                7   sizes × fit + sleeping
```

The Python tests are fixtures of the graph shapes this box really renders, and
pin the three failures that would look fine: a forwarding node between the
sampler and its text (every flux workflow has one), the negative prompt coming
back as the positive, and two renders differing only in seed failing to share
a signature — which would mean no render ever got a progress bar.
