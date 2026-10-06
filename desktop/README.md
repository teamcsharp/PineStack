# Pine Box Desktop

Electron shell for PineBoxAgent. It can launch the local FastAPI agent or
attach to an agent that is already running.

## Run

```powershell
npm install
npm run desktop
```

On Windows, run from a local path rather than a UNC network share if Electron
is blocked with `Access is denied`.

## Python Agent

The desktop app starts:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8096
```

Use the Settings view to set a Python command, API key, custom agent URL, or
data directory. The default development data directory is `./data`; packaged
apps use the app user-data folder and set `SPARK_AGENT_DATA_DIR` for the
Python process.

If dependencies are missing, use **Install Python Deps** in the Logs/Settings
workflow or run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux uses `.venv/bin/python` after the same setup.

## Build

```powershell
npm run desktop:dist:win
npm run desktop:dist:linux
```

Build outputs land in `dist-desktop/`.

## PinePiP

Click **PiP** in the right-hand rail (or press **Ctrl+Shift+P**) to reduce the
desktop to a freely resizable picture-in-picture window. Drag the picture to move it.
Your chosen width and height stay fixed when videos change, start, or stop.
Each video fits inside its tile without cropping or stretching, with black bars
where the aspect ratios differ. Double-click
the picture or choose **Expand Pine** in its right-click menu to restore the
previous desktop window. PiP size, position, always-on-top preference, and widget
visibility, order, and top/bottom placement are saved separately from desktop bounds.

The picture combines playing videos from the station panel and desktop surfaces
without starting new players or audio streams. Clips enter and leave with the
VCR effect; the existing seamless and endless playback modes continue running
and can be toggled in the right-click menu. With no video, a Three.js particle
wave surrounds the Pine Box logo.

The dialogue strip includes a continuously rotating Three.js die displaying
recorded roulette results for the line on air (a dash means no recorded draw).
Right-click to enable task status, station audit, production/recording/banking/
emotion audit, music controls and votes, or the chat/roulette/SFX overlay.
Drag a widget's dotted handle to dock it at the top or bottom and reorder it.
Widgets overlay the picture; they do not change the window size. Music playback
controls the device's existing broadcast monitor; votes use the music vote store.
The right-click menu offers **Color theme** (Pine green, Midnight blue, Plum,
Amber, or Graphite) and **Overlay transparency...**, which opens a live slider
from solid to 90% transparent. Both preferences are saved. The slider adjusts
the overlays, including their text and controls, while the picture stays unchanged.

Enable **System3 message tile** in PiP's right-click menu for the Digital feed's
exact indented roulette listing, recorded RNG results and typed message. Each
category rolls before its indented subentry; completed rows remain above the
active row in their original reel boxes. The tile follows the current on-air message and
immediately replaces an unfinished animation when a new message starts.
The message item itself defines the overlay bounds and grows with its content.
Its scrollbar and persistent header/buttons are hidden. Drag the item to move
it; drag its invisible edges/corners to resize it. Width controls wrapping, and
vertical resizing adjusts text size. Position and preferred size are saved.
The tile keeps its width, font size and anchored position as it grows downward.
At the available screen limit it scrolls older rows upward without a visible
scrollbar. Landing, typing and completion keep the same rows and formatting.

**System3 message tile options** offers **Hold until the next message** (default),
**Fade after a delay**, and **Keep a scrolling history**. **Configure text, opacity
and animation...** opens text size, tile opacity, roll speed, typing speed, fade
delay and playback timing controls. Typing speed applies when playback timing
is disabled. History retains up to 12 completed messages.

The reusable `PineSystem3MessageTile` component in
`renderer/system3-message-tile.js` owns the original roulette DOM, styles,
sequential animation, typed message and lifecycle. Its `mount(container, adapters)`
API accepts a recorded-roll loader, clock and entry callbacks, and returns
`receive`, `configure`, `visible`, `dispose` and diagnostic `state` methods.
The Digital feed, replay views, System3 Messenger, Director Conversation and tune feed use the same
roulette renderer and typing helper; PiP supplies its on-air adapter and positioning
controls. Late decisions append to the existing sheet instead of rebuilding it.
`renderer.append()` retains existing rows; `renderer.reset()` replays the same nodes.
Run `tools/sync-system3-tile.ps1` after changing the canonical renderer to update
the tablet, frontend and desktop tool copies together.

**Audio mixer...** opens a separate, always-on-top Levels window, even when
PiP is small. Master, Voices, Music, SFX, Videos, and Pads use the existing
station levels and apply as you drag. Reset restores these six levels to 100%.
Close the window with its close button or Escape. Reopening reads the current
levels; opening it again focuses the existing mixer. Run
`tests/test_audio_mixer.cjs` with Electron for the isolated mixer check.

Run `tests/test_pine_pip.cjs` with Electron to exercise the feature against a
local fixture station and synthetic silent video streams, without station writes.

The right-click menu offers **Pine Cam overlay**, which floats over the PiP
picture. Drag the camera picture or its label to move it, and drag any edge or
corner to resize it independently in both dimensions. Its position and size
are saved. **Pine Cam only** locks the main picture to the camera; clips and the
particle background stay hidden, including when the camera is offline. Turning
camera-only mode off restores the overlay's saved geometry. The camera remains
visible when the other overlays/UI are hidden.

**Troubleshoot station...** is the first menu item. It opens a separate,
always-on-top desktop window with checks and repair actions for DJ audio,
broadcast delivery, Pine Cam/its PiP picture, and Pine Tab/its display. Audio
repairs use PineRevive's existing recovery ladder and show each step as it runs.
They restore zeroed DJ/video channels, resume the station audio graph with a
playback gesture, check Windows device/application mute and volume, and measure
the app's Windows audio session after recovery. PiP's particle meter samples
only an already-running audio graph, so it cannot silence native playback by
creating a suspended one. The desktop shell and its DJ panel share playback
ownership, so videos in the shell are not muted for that panel.
Camera recovery follows the link doctor's recommended cure and verifies a
displayed picture. Tablet recovery uses the existing tablet doctor and checks
the resulting attachment. Failed checks keep their explanations and manual
steps; they do not stop checks for other components. **Reload app display**
recovers an unresponsive desktop renderer while the troubleshooting window
stays open. **Show Pine window** brings the app back to the front and recreates
its main window if it was closed while troubleshooting remained open.

**Resolve playback + restore DJs**, the first item in the PiP menu, runs the
complete playback repair immediately and shows its results. It stops hidden H3
previews in Pine and its tools, clears their audio holds, resets stuck video
controllers, reconnects the station page, resumes DJ players and audio graphs,
and asks the orchestrator to diagnose and repair speech production and delivery.
Music playback alone cannot verify this repair: the result also checks recent
DJ speech acknowledgements and advancing, audible speech in this app. A gap
between DJ lines is reported as waiting for speech. Individual failures are reported while the remaining
steps continue. Repeated clicks share the active repair. A slow recording job
continues in the background and the result reports it as pending.

Station views retry a failed main-page connection with backoff and a finite
budget. Successful loading cancels old retries; a network-online event or the
playback repair button starts another attempt. DJ players track actual playhead
progress, discard obsolete callbacks and recover interrupted speech at its saved
position. Hidden H3 decoders are paused and released when their viewer closes
or its load fails.

**Camera source** selects **Pine Cam**, **PineTab front camera**, or **PineTab rear
camera**. The tablet lenses stream into the same draggable, freely resizable
overlay and camera-only display without replacing the tablet's station screen.
Switching sources or disabling the overlay releases its tablet camera connection;
an independently opened tablet camera window keeps its shared connection.
Camera troubleshooting reconnects the selected source and checks for a picture.

**Export last...** offers 1, 2, 3, 5, 10, 15, or 30 minutes and one hour, with
**Broadcast mix (WAV)** and **PiP video + broadcast mix (MP4)** for each duration.
Both save directly to the configured Pine Box recordings folder. The rolling
cache starts automatically and retains up to one hour, bounded by 4 GiB of
combined video and audio. History accumulates while the app runs; exports report
the duration actually available if startup, recovery, or the byte limit shortened it.
Exports pin their snapshot so recording and cache eviction can continue safely.

Picture capture requests the window's native physical pixels and 60 fps. A resize
opens the replacement capture before releasing the old one; an export spanning
sizes pads smaller pictures onto the largest native canvas without scaling them.
H.264 capture is preferred when Chromium supports it, with codec fallback. Export
probes a real hardware encode and uses NVIDIA NVENC, Intel QSV, or AMD AMF when
available, then retries with the CPU while preserving the same audio timeline.
Encoder workers use below-normal CPU priority when the operating system permits it.
MP4 uses H.264, stereo 48 kHz AAC, constant frame cadence, and a front-loaded index
for playback. These are compressed recordings; capture cannot reconstruct frames
that the application, source media, or display never rendered.

Recent video exports preserve the application mix captured during the selected
minutes, including volume changes, mutes, ducking, sampler, radio, video and effects.
Shell, DJ panel and loaded application frame taps preserve speaker playback and
exclude unrelated applications. The cut ends when export is requested; flushing
and encoding cannot move the selected window. Audio remains stereo, with no
export-time gain adjustment, normalization or replacement soundtrack.
Capture failures recover automatically. Exports and editor captures require the
complete recorded mix by default and report missing audio. Explicit picture-only
exports remain available. Tablet replay exports retain their embedded playback mix.

After updating capture code, reopen Pine Box so the main process, preload, and
renderer load together. A renderer-only reload cannot update the export backend.
To audit a saved file with FFmpeg and ffprobe installed, run:

```powershell
node tools/verify_pip_recording.cjs "C:\path\to\recording.mp4" --fps 60 --require-audio --require-faststart
```

The audit fully decodes the file and reports frame cadence, timestamp gaps,
track endpoints, codecs, and MP4 index placement. Real picture/audio event alignment
needs a synchronized flash/pulse or equivalent content reference; matching track
metadata alone cannot establish lip sync.

Say **"export the last five minutes of PinePiP display"** to export an MP4
with the broadcast mix to PineBox recordings and the station export courier.
The export uses the latest continuous PinePiP recording, even after expanding
the app; ordinary app footage and resize transitions are excluded.

The Audio mixer popup stays above PinePiP and remains available when overlays
are hidden. Closing an H3 viewer releases its video immediately; entering
PinePiP also closes that viewer and stops hidden gallery/lightbox previews.

PineTab front and rear webcams use 640 × 480 preview capture with a 30 fps
target, rather than repeated still photographs. Capture buffers are reused,
and slow viewers drop obsolete frames instead of accumulating playback delay.
The camera's optional slow-shutter mode still trades frame rate for low-light
exposure.

Silent DJ picture cues on the tablet use the native player with preloaded
local MP4s. Cached fragmented MP4s are remuxed without re-encoding so their
positions can follow the audio cue; playback corrects small timing drift
without repeatedly seeking through the same clip.

## Pine Lens

The magnifying glass beside the PineTab drawer title opens the desktop session
picker. Choose a computer, then **Saved lens** for its saved PiP region or
**Full display** for its monitor. Tap, drag, scroll with two fingers, and use the
keyboard controls to operate that computer. Draw and save a region from the
desktop's Pine Lens view.

Say **“export the last five minutes of Pine Lens”**, or use **Export last minutes**
in the session view. The selected computer exports its own recording history,
saves an MP4 in the configured recordings folder, and uploads it through the
station's export courier. The spoken command selects the most recently viewed
computer that is still recording.

Recording starts when a session is opened, or on launch with a saved region,
and continues after the viewer closes. The ring retains up to ten minutes and
256 MiB; exports report when less history is available. These recordings contain
screen video without computer audio, captured at up to four frames per second.

Pine Lens supports pinch zoom and two-finger panning when zoomed. **Pan view** changes one-finger or mouse dragging to view panning; **Control desktop** restores remote input. **Reset view** fits the image again. At the fitted size, two-finger vertical dragging scrolls the remote computer.

Lens uses the PinePiP Three.js particle animation and PineVcr picture opening/closing effects while loading, between views, and when disconnected. The local SFX picture yields the display to Lens until the view closes.
