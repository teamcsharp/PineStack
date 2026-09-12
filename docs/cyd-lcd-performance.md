# CYD LCD performance

The installed update delivers **6.15 fps for the actual scrolling newspaper**, measured over 20 seconds with 123 drawn frames and zero failures. The previous pipeline's estimated cadence was about 2.5 fps. Removing its fixed 200 ms pause, using persistent binary transport, caching text and paper tiles, and reusing JPEG quality produced the practical improvement. The ESP32 still spends about 117 ms decoding and drawing a full frame, so this remains a small embedded display rather than a phone-rate animation surface.

## Measured baseline

The LCD owner tested the attached ESP32-2432S028R at **2026-09-07 09:56:04 UTC**, repeatedly sending the same native **320×240, 12,198-byte JPEG**. The source record was independently checked at `%TEMP%\pine-lcd-performance\http-baseline.json`; the image is `%TEMP%\pine-desktop-playback-probe\lcd-last-acknowledged.jpg`.

| Measurement | Baseline |
| --- | ---: |
| Requests / successful draw acknowledgments | 24 / 23 |
| Successful request latency, p50 / p95 | 196.7 / 384.1 ms |
| Slowest successful request | 1,176 ms |
| Mean firmware `dec` time | 112.65 ms |
| Free heap reported by successful ACKs | 88,620–98,804 bytes |

Request 13 returned `HTTP 400: empty`. The firmware draws JPEG blocks directly to the TFT on this board: `dec` includes **JPEG decoding and SPI drawing**, while `draw=0`; it does not measure CPU decoding alone. The 24-request sample is a useful comparison baseline, not a sustained reliability result.

The old `desktop/renderer/lcd.js` tick waits **200 ms after** encoding, transmission, the draw ACK and occasional event polling. Using the measured median, `1000 / (196.7 + 200) ≈ 2.5 fps` before encoding and event costs. This is an estimated cadence, not a measured desktop frame rate. Dense pages can invoke eight synchronous `canvas.toDataURL()` encodes in `lcd-frame.js`. `lcd-agent.cjs` opens a fresh HTTP connection for each base64 upload; the firmware retains parser/String copies as well as decoded JPEG bytes. These are concrete latency and memory costs.

## Hardware limits and tradeoffs

The local `quanta-screen/board_cyd_2432s028r.h` configures a classic ESP32-WROOM, ILI9341, **40 MHz HSPI**, landscape rotation 1, separate resistive touch pins and an SD gallery on VSPI. This CYD has no PSRAM.

| RGB565 storage or transfer | Calculated requirement |
| --- | ---: |
| Full 320×240 framebuffer | 153,600 bytes (150 KiB) |
| Two full framebuffers | 300 KiB |
| One 320×16 strip / two strips | 10 / 20 KiB |
| Full frame at 40 MHz, pixel payload only | 30.72 ms |
| 30 full frames per second, pixel payload only | 36.86 Mbit/s |

These are arithmetic lower bounds, excluding commands, decoding, network and scheduling. Full-frame 60 fps cannot fit the configured bus clock. A full framebuffer also exceeds the free heap observed in this test. Espressif documents internal, aligned DMA buffers and the cost of small transactions; strip staging can reduce transaction overhead without full-frame allocation. A higher SPI clock needs hardware verification. [ESP32 SPI master documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/spi_master.html)

ILI9341 hardware vertical scrolling is not a direct solution for the current landscape newspaper. Bodmer's scrolling example requires portrait rotation; Arduino_GFX rotation 1 exchanges the addressing axes. Updating only newly exposed horizontal lines therefore needs an orientation-aware design. Ordinary dirty rectangles do not avoid redrawing most pixels when an entire raster viewport moves. [TFT_eSPI scrolling example](https://github.com/Bodmer/TFT_eSPI/blob/master/examples/320%20x%20240/TFT_Terminal/TFT_Terminal.ino), [Arduino_GFX ILI9341 rotation code](https://github.com/moononournation/Arduino_GFX/blob/master/src/display/Arduino_ILI9341.cpp)

Recommended order:

1. Schedule against frame deadlines, retain only the latest pending frame, reuse successful JPEG quality, and keep input/preview work responsive while a frame is in flight.
2. Send bounded binary frames with explicit length and sequence, partial-read handling, timeouts and a draw-complete ACK. Preserve display ownership and reconnection identity checks. Persistent HTTP is another supported option, but simply enabling keep-alive in the existing Arduino String path does not solve its body handling. [Espressif HTTP server documentation](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/protocols/esp_http_server.html)
3. Draw gesture feedback and simple drawer animation locally; play existing SD avatars locally. Benchmark binary JPEG before adding RGB565 transport. Raw full-frame RGB565 sends about 12.6 times this JPEG's bytes; decoded MCU-row strip staging is a smaller possible optimization. Half-resolution JPEG upscaling still writes the full number of TFT pixels and reduces text detail.

## Implementation status

The current changes use one acknowledged frame at a time, subtract elapsed work from the next frame deadline, cache eight short newspaper canvas segments, and reuse a fitting JPEG quality. The 30 fps scheduler target is not a measured display rate. Binary-capable Wi-Fi firmware negotiates a maximum JPEG size of 24,576 bytes; the legacy/USB paths retain their smaller limit.

The first normal-app run revealed a second host bottleneck that the hidden renderer did not exhibit: a single canvas export often took 20–50 ms. The LCD canvas and its cached tiles now request `willReadFrequently: true`, because every frame is exported as JPEG. This lets Chromium favor CPU storage and avoid repeated GPU readback; it is the optimization described for frequent `toDataURL()`/`toBlob()` use in the [HTML canvas standard](https://html.spec.whatwg.org/multipage/canvas.html#concept-canvas-will-read-frequently). Normal-app measurements below verify its effect rather than assuming the hint guarantees a speedup.

Input polling is independent of frame acknowledgments. Firmware samples the separate resistive touch GPIOs every 20 ms during JPEG callbacks into a fixed queue, then dispatches gestures after drawing to avoid reentrant TFT operations. Firmware runs the idle timer and SD avatars locally; **the quick-settings drawer is rendered by the desktop and transmitted as an image**. Device-native drawer drawing and RGB565 strip transport remain possible future optimizations.

The six controls are Chat overlay, Newspaper, Tabloid, Avatars, Screensaver and Auto-scroll. The timer defaults to five minutes and is opt-in; the desktop selector supports 15 seconds through one hour. Manual avatars stay selected until a mode change. A screensaver wake consumes the whole contact, so it cannot also favorite a chat line. Selecting Newspaper or Tabloid explicitly overrides the automatic paused cupboard view. Quanta retains its original commands and all 33 SD galleries.

The following alternatives were tested rather than assumed faster:

| Experiment | Outcome |
| --- | --- |
| 10 KiB decoded MCU-row staging | Approximately 2 ms saved in device work, at a 10 KiB memory cost; removed |
| True single-component grayscale JPEG | 30/30 ACKs, but about 115 ms combined decode/draw versus 110.6 ms color in that trial; removed |
| Private JPEG decoder lookup configuration | Final firmware uses the tested private configuration; it did not establish a standalone decoder speedup |
| CPU and Wi-Fi settings | Runtime confirms 240 MHz and disabled Wi-Fi power saving; they were already configured correctly |

The early HTTP and binary experiments ran while the older desktop was still open, so background draws can affect those latency samples. The final fixed-image benchmark and actual-renderer test below ran with the old desktop closed and each helper's socket released before the next test. Initial and final sample sizes differ; the measured renderer rate is the stronger end-to-end result.

## Activating the desktop changes

Read-only inspection found the running app under `%LOCALAPPDATA%\PineBoxDesktop\runner`, with mode `attach` to the existing station and LCD auto-start enabled. The current Start-menu `Pine Box.lnk` targets that runner's `node_modules\electron\dist\electron.exe`, argument `.`, working directory `runner`.

`desktop/main.js` requires and constructs the LCD agent before `selfSyncFromShare()` runs at `whenReady`. A direct shortcut restart can therefore load the old transport for that boot even though the renderer receives fresh files. After tests, use one coordinated graceful close during a speech gap, wait for the Pine main process to exit, then launch the existing `%USERPROFILE%\Desktop\Launch Pine Box Desktop.cmd`. It runs the normal `pine_box.exe`, which mirrors the shared desktop **before** starting Electron. Merely opening the launcher while Pine is running triggers its single-instance focus behavior.

The normal launcher was used after a graceful close during a verified paused, quiet period. The local runner's renderer and transport hashes matched the shared source after launch. Existing LCD preferences, station pause, routes and physical volume were retained. In attach mode, closing the desktop leaves the remote backend running.

## Final measurements

| Final evidence | Result |
| --- | --- |
| Firmware identity/version/hash | CYD `b4:bf:e9:12:81:9c`, Quanta 49 + Pine protocol 2; SHA-256 `76f40231c64c113f431dd45a92cc5da0b872ec8dc24abf1fe725e985da4eabcc` |
| Same 12,198-byte JPEG | 60/60 draw ACKs, zero failures; p50 **155.6 ms**, p95 **364.1 ms**, max **620.2 ms** |
| Combined decode/SPI and memory | Mean **116.98 ms**; ACK free heap **82,000–82,204 bytes**, **108,220 bytes** after closing; largest free block was not measured |
| Actual newspaper renderer, sole producer | **123 frames / 20.01 s = 6.15 fps**, zero failures; representative frame: rendering **0.2 ms**, one JPEG encode **1.9 ms**, ACK **152.9 ms**, **15,134 bytes**, native 320×240 |
| Layout and screensaver integration | 164 total frames, zero failures; fresh ACKs and images verified for drawer and tabloid; screensaver preview entered SD avatars and a desktop preview tap woke Pine |
| Touch and idle behavior | 11 tests execute the actual C++ controller, including an 80 ms swipe captured during drawing and consumed wake; on-device 15-second idle entry and command wake passed. Real physical taps reached the app. Finger swipe and tap-to-wake confirmation remains requested |
| Final normal desktop observation | **868 drawn frames, zero failures over 181.37 seconds**; **4.87 fps** after startup in the denser paused cupboard view; application responsive, binary transport connected, source/runner hashes identical |
| Normal-app canvas export | Sampled median **27 → 1.3 ms**, p95 **53.7 → 1.8 ms** after readback optimization. The preceding normal-app run drew 787 frames without failure at 4.44 fps after startup. These were separate runs with naturally varying Wi-Fi latency and cupboard content |

The station remained paused throughout the final observations. Its backend was left running, and no routing, playback, or volume changes were used to obtain these results. The pause view was preserved as requested earlier; its denser 18–24 KiB frames explain part of the difference from the 6.15 fps newspaper test. Native rendering and network variability still produce visible frame steps; the remaining measured bottleneck is the device's combined JPEG/SPI work and frame delivery.

The 37 normal-app samples were collected once every five seconds and the diagnostic stopped automatically. The encode percentiles therefore describe sampled frames rather than every frame in the run. [Normal-app evidence and source hashes](cyd-lcd-desktop-check.json).

Evidence: [fixed-image benchmark](cyd-lcd-final-benchmark.json), [actual renderer integration](cyd-lcd-renderer-check.json), [acknowledged newspaper](cyd-lcd-newspaper.jpg), [acknowledged quick settings](cyd-lcd-quick-settings.jpg). `node --test tests/test_lcd_controls.cjs tests/test_lcd_agent.cjs tests/test_lcd_stream.cjs` passed 30 tests; the hidden UI smoke passed 32 checks. The concurrently completed newspaper work passed all 344 Python tests.

Related operating and recovery instructions: [Pine Box LCD agent](pine-box-lcd.md).

## Corner switch correction

The subsequent physical report described a flashing, unclickable corner switch overlapping another button. The old native indicator was painted over by each host or avatar JPEG, then cleared and redrawn by the main loop. Separately, the desktop drawer handled taps before the corner control, and the header did not reserve the complete native corner hit region.

The renderer now reserves the top-left fifth of the width and quarter of the height, places a visible AV / PB button inside it, and draws it after every content view and drawer. At native 320×240, this is a 64×60 hit region containing a 56×48 button. Header text begins to its right and scrollable content begins below the header. Corner handling runs before busy, drawer and content actions; a screensaver wake still consumes the first contact. Firmware handles physical mode changes once, while preview clicks send one explicit mode command.

On this CYD's direct-display path, JPEG blocks and letterbox clears skip the protected region throughout rendering, including SD avatar frames. The native button owns those pixels and redraws after a mode, size or full-screen clear change. This removes the per-frame erase/redraw cycle. Quanta touch ripples that intersect the corner are suppressed, and its gallery-copy banner stays to the right. Pixel-recording C++ checks execute the actual compositor and verify the protected pixels after every native, scaled, portrait and straddling tile, alongside correct source strides for every outside pixel. The physical touch calibration is retained; raw-coordinate diagnostics help distinguish a future calibration problem from drawing or hit testing.

The desktop regression covers the original failure directly: open Quick Settings, click AV, verify one avatar transition and a closed drawer, then click PB and verify one return to Pine. The hidden Electron smoke passes 38 checks; the combined host/control/transport suite passes 31 tests. Live-device and deployment evidence for this correction is recorded separately from the earlier performance benchmarks.

The corrected firmware, SHA-256 `4004ffc58c773bffc105b3ada9c155a9ade9d381fd27420a60343d264c4bd562`, was installed by OTA and re-identified with all 33 SD avatars intact. At 11:14 UTC, the isolated real-renderer check drew **121 newspaper frames in 20.003 seconds (6.05 fps)** with no failures, and **170 total frames with no failures** across drawer, tabloid, avatar/Pine transitions and screensaver preview/wake. Clicking the preview's corner while the drawer was open changed the actual device to avatars; the second corner click returned it to Pine and fresh draw acknowledgments resumed. These are verified device mode changes through the desktop preview, not a physical finger test. The native pixel compositor tests establish protection during image writes; the saved host JPEG is not a photograph of the TFT.

The normal launcher then refreshed and reopened Pine Box. Both deployed renderer files matched their shared-source hashes, and the regular app resumed binary streaming with zero failures in the initial observation. The updated device also recorded **three actual physical corner releases**, at `(22,12)`, `(23,14)` and `(26,8)`, alternating Pine → avatars → Pine. Raw diagnostics confirm the retained uncalibrated mapping and landscape rotation. The separate preview test verifies switching with the drawer open; a physical drawer-open tap and visual steadiness still depend on user observation. [Correction evidence](cyd-lcd-corner-check.json) and [acknowledged drawer frame](cyd-lcd-corner-button.jpg) are retained separately from the original performance evidence.

The final normal-app observation completed with **903 drawn frames and zero failures over 181.722 seconds**, across 37 samples. The app remained responsive and connected; the station remained paused. Its [last acknowledged desktop frame](cyd-lcd-corner-desktop.jpg) shows the reserved button beside the paused cupboard header. The diagnostic stopped automatically, leaving the regular desktop and LCD stream running.

## Image-only slideshow

The subsequent gallery update caches two display-size pictures on the desktop, shuffles the gallery image list and preloads the next picture. Randomized 1.2-second transitions use dissolve, horizontal slide, vertical slide or wipe, avoiding an immediate repeated effect. Only the permanent AV/PB corner remains over the pictures; chat, newspaper and automatic cupboard content are excluded. Gallery and newspaper-only choices are explicit and can be cycled from the desktop or selected in the swipe-down drawer.

Held pictures reuse their image and send a one-second JPEG heartbeat to retain native host ownership. Transitions use the established one-frame-at-a-time cadence, with no added transport delay. This avoids continuously retransmitting a static picture at the maximum device rate. Opening the drawer freezes slideshow progress; failed downloads preserve the current picture and back off before retrying.

The real-image test displayed five pictures and all four effects over 20.207 seconds, with 49 draw ACKs and zero failures, using a three-second hold. Newspaper scrolling remained 5.95 fps in the accompanying 20-second test, and all 234 frames across the combined integration checks were acknowledged without failure. [Gallery evidence](cyd-lcd-gallery-check.json) and [operating instructions](pine-box-lcd.md) describe the separate timing, memory and user-interface checks.

The subsequent normal-app run drew 869 frames in 181.303 seconds, with one frame-connection closure in the saved paused view. The connection was healthy again by the next five-second observation and remained connected at completion; its cause was not established. This observed recovery is recorded separately from the gallery phase's zero-failure result. The desktop was left responsive and streaming, with source and deployed hashes matching.
