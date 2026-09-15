# Tablet video capture and editing

Implemented 2026-09-14. The top-right capture gesture opens a video editor
over the running station page. Choose the recent recording window, then
select **Open video editor**.

## Operator controls

- Drag the yellow handles to set the in and out points; numeric fields and
  **Start here / End here** provide finer adjustment.
- Preview the selection. **Include audio** controls preview sound and whether
  the saved MP4 has an audio track.
- The audio row contains a waveform from the captured samples. **Show
  frequencies** switches to the recording's spectrogram.
- Draw freehand, arrows or boxes; crop with handles or aspect presets; rotate
  in 90-degree steps; adjust brightness, contrast and saturation.
- Undo and redo edits. **Save copy** creates a new MP4 in the tablet's
  configured recordings folder. The original capture is retained.
- Failed network polling or device saving retries the existing export.

## Captured audio

The foreground recorder captures eligible Android media playback through a
render-and-loopback policy. This preserves the primary output route, including
speaker/headphone selection, and copies the digital mix into stereo 48 kHz
AAC at 128 kbit/s. Neither the microphone nor a separately fetched station
stream supplies the soundtrack.

Android's physical volume setting does not scale this digital capture.
It is a recording of the playback mix, not a measurement of sound pressure
or the analog headphone signal. Capture restrictions on another app's audio
can still prevent its samples from appearing.

The video and audio use monotonic capture timestamps. A missing interval stays
a missing interval rather than shifting later speech earlier. Ordinary capture
requires audio coverage; an explicit option permits retaining an incomplete
recording with a visible notice. A genuinely silent captured interval remains
valid evidence and is distinguished from an absent track.

The audio worker has bounded retry delays, packet coverage checks and a short
failure history. Capturing and encoding run independently of WebView rendering.
The policy-bound PCM buffer provides one second of scheduling headroom. Screen
encoder input is capped at 12 fps; the encoder's frame-rate metadata alone does
not enforce that limit.

## Implementation

Android project: `C:/_tools/pinebox-android/PineBoxKiosk`.

The Android checkout has its own Git history, published on the
[`android/main` branch of PineStack](https://github.com/teamcsharp/PineStack/tree/android/main).
The station lives on `main`. To obtain the tablet project separately:

```sh
git clone --branch android/main --single-branch https://github.com/teamcsharp/PineStack.git PineBoxKiosk
```

- `replay/PineAppRecorder.kt`: foreground service lifetime and screen state.
- `audio/PlaybackLoopback.kt`: platform policy and buffered playback capture.
- `replay/ReplayAudioCapture.kt`, `ReplayAudioWindow.kt`: AAC, sample clock,
  bounded retention, coverage and failure evidence.
- `replay/ReplayRing.kt`, `ScreenReplay.kt`: common timeline and MP4 muxing.
- `bridge/PineDesktopBridge.kt`: streamed upload and saving edited copies.
- `net/VideoEditorContract.kt`: identifiers, paths and header validation.

Station project:

- `desktop/renderer/hot-corners.js` and `.css`: capture sheet and editor host.
- `desktop/renderer/video-editor.html`, `.js`, `.css`, `video-edit-model.js`:
  touch editor, original-frame overlay geometry and export selection.
- `video_editor.py`: isolated router and one bounded background media worker.
- `data/video_edits/sources/<id>`: retained capture and bounded analysis assets.
- `data/video_edits/exports/<id>`: copied export, its edit recipe and job state.

The backend streams uploads, validates geometry and numeric edits, and uses
argument arrays for FFmpeg. Color correction precedes drawing, then crop and
rotation. Video and audio share the selected trim; audio resampling preserves
timestamp gaps. Media work has lower CPU priority and limited threads. Shutdown
terminates active processing rather than delaying a station restart indefinitely.
Writes require the station's existing authentication; reads follow its existing
read-authentication policy. No API key is embedded in editor URLs.

PyAV reads actual stream metadata when the bundled FFmpeg distribution has no
ffprobe. The dependency is pinned and included in station requirements. See
the [PyAV container documentation](https://pyav.basswood.io/docs/stable/api/container.html).
The frame-rate cap uses Android's
[MAX_FPS_TO_ENCODER setting](https://developer.android.com/reference/android/media/MediaFormat#KEY_MAX_FPS_TO_ENCODER).

## Validation evidence

- Seventeen isolated Python tests pass, including real encoded video/audio,
  preservation of an initial audio delay after trimming, actual drawing and
  geometry in exports, color changes, removal of unchecked audio, ranged
  reads, authentication and bounded process shutdown. Tests do not import the
  live station application.
- Twelve editor model tests and four capture-flow tests pass. All 89 native
  unit tests pass, covering recording clocks, gaps, silence, bounded retention,
  retries and bridge contracts. The Android build also passes.
- Browser pointer tests exercised trim, drawing, crop, rotation, adjustments
  and audio selection at 1000 by 597 CSS pixels. Native-save retry reused one
  export job. No browser runtime exceptions were observed.
- Physical tablet screenshots show the actual video and waveform. Android
  WebView CDP screenshots omit hardware-rendered canvas layers and falsely
  showed them black; use an ADB physical-display screenshot for visual QA.
- A live 10.17-second capture, source `579f030a91674a0489d658597061829c`,
  has 477 nonzero AAC packets, no packet gaps and 99.916% coverage; the initial
  frame boundary is 8.4 ms. Decoded audio RMS is 0.042482.
- Export `f729c3f4033440bcb2f70db769f9c6d8` preserves seven seconds of that
  capture with drawing, crop, rotation and color adjustments, plus stereo
  audio. Native saving produced the verified file
  `Download/Pine Box recordings/Pine-capture-audio-check.mp4` (373,275 bytes).
- Independent decoding of an earlier partial capture reproduced both reported
  gaps exactly (1.515 s and 2.502 s). The editor identifies that recording as
  incomplete rather than claiming its audio can be restored.

- The installed build uses a 48,000-frame PCM buffer. More than six minutes of
  live capture completed with zero retries and an empty failure history. The
  previous 3,072-frame buffer had a confirmed overrun under load; the larger
  buffer addresses that observed failure without delaying each read.
- Source `91e98bdc1cc24e079a2e4e7fee5641e5` contains 117 video frames over
  10.284 seconds (11.38 fps), verifying the input frame-rate cap. Audio coverage
  is 99.796%, with no packet gaps and a 20.6 ms initial AAC frame boundary.
- The output-timed synchronization check, source
  `d50bb406150a4d24a3e2ff5e41d0c0dd`, has 99.988% audio coverage and no packet
  gaps. Its three tone onsets agree with the recorded dark-to-white frame
  intervals after accounting for logged DOM scheduling delay (one onset is
  about 10 ms outside its interval). This supports alignment at the recorder's
  frame resolution; it is not a sample-accurate measurement of the speaker.
  An earlier test incorrectly timed flashes from Web Audio's rendering clock,
  which led actual output by roughly 0.2 seconds. The corrected test uses the
  [output timestamp mapping](https://www.w3.org/TR/webaudio-1.0/#dom-audiocontext-getoutputtimestamp).
  No arbitrary audio timestamp correction was applied.

The connected output during testing is the speaker; no physical headphone
insertion/removal test has been performed. Retained video history depends on
encoded size: the 600 kbit/s variable-rate target is not a hard ceiling, and
the 100 MiB video ring does not guarantee twenty minutes on every screen.
The capture sheet uses the actual available history.
