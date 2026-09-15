const { contextBridge, ipcRenderer, clipboard, nativeImage } = require("electron");

contextBridge.exposeInMainWorld("pineDesktop", {
  readConfig: () => ipcRenderer.invoke("config:read"),
  writeConfig: (cfg) => ipcRenderer.invoke("config:write", cfg),
  startBackend: () => ipcRenderer.invoke("backend:start"),
  stopBackend: () => ipcRenderer.invoke("backend:stop"),
  setupBackend: () => ipcRenderer.invoke("backend:setup"),
  reconstituteDesktop: () => ipcRenderer.invoke("desktop:reconstitute"),
  /* 2026-09-10: what this app was built from, against what the share
   * holds now - so "am I on the latest?" has an answer. */
  buildInfo: () => ipcRenderer.invoke("desktop:build"),
  backendLog: () => ipcRenderer.invoke("backend:log"),
  onBackendLog: (callback) => ipcRenderer.on("backend-log", (_event, line) => callback(line)),
  onSupportProgress: (callback) => ipcRenderer.on("support-progress", (_event, data) => callback(data)),
  discoverKey: () => ipcRenderer.invoke("agent:discover-key"),
  get: (route) => ipcRenderer.invoke("agent:get", route),
  post: (route, body) => ipcRenderer.invoke("agent:post", route, body),
  put: (route, body) => ipcRenderer.invoke("agent:put", route, body),
  del: (route, body) => ipcRenderer.invoke("agent:del", route, body),
  openExternal: (url) => ipcRenderer.invoke("open:external", url),
  /* #1356: pull a still or a cut clip off the camera and put a Save As
     in front of it. The route is checked on the other side. */
  camSave: (opts) => ipcRenderer.invoke("cam:save", opts),
  /* #1118: the clips folder in Explorer, and a folder picker for the
     preference sheet. #1112: reveal one file. #1115: a picture of this
     window for the script view's report. */
  openFolder: (target) => ipcRenderer.invoke("open:folder", target),
  showInFolder: (target) => ipcRenderer.invoke("show:in-folder", target),
  pickFolder: (opts) => ipcRenderer.invoke("pick:folder", opts),
  shotView: () => ipcRenderer.invoke("shot:view"),
  /* #1182: THE ROLLING RECORD OF THIS WINDOW, under the names the tablet
   * answers to - hot-corners.js checks typeof on each of these and draws its
   * export sheet out of what it finds. See screen-ring.cjs.
   *
   *   replayState()  -> {ok, running, seconds, holds, bytes, detail, min, max,
   *                      audio}
   *                     `seconds` is what is HELD, which is less than `holds`
   *                     for the first half minute after the app opens.
   *                     #1205: `audio` is what the recorder's capture carries
   *                     - {source, present, state, detail, supported,
   *                     held_ratio} - and the export sheet prints its `state`
   *                     and `detail` (hot-corners.js:1553) so the operator can
   *                     see whether a cut will have the broadcast on it
   *                     BEFORE cutting. It was null until the ring learned to
   *                     film the sound with the picture.
   *   replayExport({seconds, upload, name?})
   *                  -> {ok, where, bytes, asked, seconds, uploaded, detail}
   *   replayFrames({seconds, count, back?, edge?})
   *                  -> {ok, seconds, held, from, to, frames:[{at, image}], ...}
   *   replayEdit({seconds, video_only}) opens the clip editor on the cut.
   *   replayHold(seconds) sets how long the ring keeps, and remembers it.
   *
   * replayBegin/replayStop/replayPush are the recorder's own three, used by
   * renderer/screen-ring.js and nothing else. replayPush is also the tell
   * that this is the desk: the tablet's bridge has no such name. */
  replayState: () => ipcRenderer.invoke("replay:state"),
  replayExport: (want) => ipcRenderer.invoke("replay:export", want),
  replayFrames: (want) => ipcRenderer.invoke("replay:frames", want),
  replayEdit: (want) => ipcRenderer.invoke("replay:edit", want),
  replayHold: (seconds) => ipcRenderer.invoke("replay:hold", seconds),
  /* #1182b: the edited video comes back from the station and is kept in the
   * operator's recordings folder - renderer/video-editor.js has been calling
   * this on a surface that never had it. */
  replayKeepEdited: (want) => ipcRenderer.invoke("replay:keep-edited", want),
  /* The desk's own trim window on the same cut - its trim, its channels,
   * its gains. The corner gesture uses replayEdit; this is the local one. */
  replayLocalEdit: (want) => ipcRenderer.invoke("replay:local-edit", want),
  /* The corner preferences, persisted. {enabled, tl, tr, bl, br, ring}. */
  hotCorners: () => ipcRenderer.invoke("corners:read"),
  hotCornersSet: (patch) => ipcRenderer.invoke("corners:set", patch),
  /* #1182c: this window's media source id, so the recorder can open the
   * capture without a user gesture.
   *
   * #1205: that road carries no audio, so it is the SECOND choice now - the
   * answer also says {loopback, platform, detail}, which is how the recorder
   * knows whether a silent recording is this platform's limit (Electron
   * captures application audio on Windows only) or a gesture it never got. */
  replaySource: () => ipcRenderer.invoke("replay:source"),
  /* #1182d: the main process asking the recorder to close the piece it is
   * on, so a cut can reach all the way to now. */
  onReplayFlush: (callback) => ipcRenderer.on("replay-flush", () => callback()),
  /* #1205: replayBegin also carries {audio:{source, present, state, detail,
   * supported}} - the recorder telling the ring what its capture holds, since
   * the renderer is the only side that can see the stream's track list. */
  replayBegin: (opts) => ipcRenderer.invoke("replay:begin", opts),
  replayStop: (why) => ipcRenderer.invoke("replay:stop", why),
  replayPush: (buffer, meta) => ipcRenderer.invoke("replay:push", buffer, meta),
  /* #1183: THE NAMES THE DESK'S OWN RENDERER HAS BEEN CALLING AND NOT
   * GETTING. "So it needs feature parity, so there's nothing left out."
   *
   * Every one of these is a name a file in renderer/ already calls and only
   * the TABLET answered, so the desk has been running the "this terminal
   * cannot do that" branch of its own code. The shapes are the tablet's
   * shapes, field for field, because the same renderer file reads both -
   * see bridge/PineDesktopBridge.kt and the section in main.js.
   *
   *   saveText({name, text, where})            -> {ok, where, bytes, detail}
   *     sampler-kits.js:216. `where` is 'downloads' (Downloads/Pine Box) or
   *     'recordings' (the folder named in Preferences). The answer's `where`
   *     is the full path, which is what the exporter prints.
   *   saveBytes({folder, name, mime, base64})  -> {ok, where, bytes, detail}
   *     sampler-kits.js:511, seventeen times for one MPC kit. `folder` is
   *     relative and always under Downloads.
   *   keepClip({route, said, id, where})       -> {ok, where, bytes, detail}
   *     line-actions.js:846. The bytes never enter the page: the main
   *     process fetches the clip from the station and writes it.
   *   revive()                                 -> {ok, rested, sinceMs, inARow}
   *   revive({now:true, why})                  -> {ok:false, say} or nothing
   *     deaf-watch.js:126. The rest period is owned by the main process so a
   *     wedged page cannot put the app in a relaunch loop - see app:revive.
   */
  saveText: (opts) => ipcRenderer.invoke("file:save-text", opts),
  saveBytes: (opts) => ipcRenderer.invoke("file:save-bytes", opts),
  keepClip: (opts) => ipcRenderer.invoke("line:keep-clip", opts),
  revive: (opts) => ipcRenderer.invoke("app:revive", opts),
  /* #1183: THE MPC OVER USB, which on this machine is a drive letter rather
   * than an Android document tree. sampler.js:1369-1462 and
   * sampler-kits.js:678/696. See usb-disk.cjs for what is honestly knowable
   * about a "USB device" on Windows and what is not.
   *
   *   usbState()                 -> {ok, chosen, name, canHost, anyRemovable,
   *                                  volumes}
   *   usbPick()                  -> {ok, name, detail}
   *   usbSend({folder, into?})   -> {ok, files, bytes, where, detail}
   *   usbList({path})            -> {ok, path, name, folders, files} | {ok:false,
   *                                  path, detail}
   *   usbRead({path, offset})    -> {ok, path, offset, bytes, size, eof, base64}
   */
  usbState: () => ipcRenderer.invoke("usb:state"),
  usbPick: () => ipcRenderer.invoke("usb:pick"),
  usbSend: (opts) => ipcRenderer.invoke("usb:send", opts),
  usbList: (opts) => ipcRenderer.invoke("usb:list", opts),
  usbRead: (opts) => ipcRenderer.invoke("usb:read", opts),
  lcdState: () => ipcRenderer.invoke("lcd:state"),
  lcdConfigure: (cfg) => ipcRenderer.invoke("lcd:configure", cfg),
  lcdDiscover: () => ipcRenderer.invoke("lcd:discover"),
  lcdConnect: (host) => ipcRenderer.invoke("lcd:connect", {host}),
  lcdStart: (automatic = false) => ipcRenderer.invoke("lcd:start", {automatic}),
  lcdStop: () => ipcRenderer.invoke("lcd:stop"),
  lcdDisconnect: () => ipcRenderer.invoke("lcd:disconnect"),
  lcdFrame: (jpeg) => ipcRenderer.invoke("lcd:frame", {jpeg}),
  lcdEvents: () => ipcRenderer.invoke("lcd:events"),
  lcdControl: (action, value) => ipcRenderer.invoke("lcd:control", {action, value}),
  lcdDisplayMode: (mode) => ipcRenderer.invoke("lcd:display-mode", {mode}),
  lcdPaperImage: (url) => ipcRenderer.invoke("lcd:paper-image", {url}),
  lcdFirmware: (body = {}) => ipcRenderer.invoke("lcd:firmware", body),
  lcdSampleDirectory: () => ipcRenderer.invoke("lcd:sample-directory"),
  lcdDownload: (id, at) => ipcRenderer.invoke("lcd:download", {id, at}),
  /* The terminal provisioner - turning a stock tablet into a Pine Box
   * kiosk. Read-only up to terminalUnlock, which erases the tablet and
   * therefore demands the exact confirmation string its gate expects; the
   * renderer cannot trip it by accident. */
  terminalTools: () => ipcRenderer.invoke("terminal:tools"),
  terminalSurvey: () => ipcRenderer.invoke("terminal:survey"),
  terminalSnapshot: (serial) => ipcRenderer.invoke("terminal:snapshot", serial),
  terminalBootloader: () => ipcRenderer.invoke("terminal:bootloader"),
  terminalReboot: (mode) => ipcRenderer.invoke("terminal:reboot", mode),
  terminalVerifyFirmware: (dir) => ipcRenderer.invoke("terminal:verify-firmware", dir),
  terminalVerifyGsi: (file) => ipcRenderer.invoke("terminal:verify-gsi", file),
  terminalUnlock: (confirm) => ipcRenderer.invoke("terminal:unlock", confirm),
  terminalDiscover: (options) => ipcRenderer.invoke("terminal:discover", options),
  terminalWirelessEnable: (port) => ipcRenderer.invoke("terminal:wireless-enable", port),
  terminalWirelessConnect: (host, port) => ipcRenderer.invoke("terminal:wireless-connect", host, port),
  terminalWirelessDisconnect: (host) => ipcRenderer.invoke("terminal:wireless-disconnect", host),
  terminalToolchain: () => ipcRenderer.invoke("terminal:toolchain"),
  terminalBuildApk: (options) => ipcRenderer.invoke("terminal:build-apk", options),
  terminalInstallApk: (options) => ipcRenderer.invoke("terminal:install-apk", options),
  /* Where the broadcast goes. The PineTab is not a station route - it is
   * which page-side client stays quiet - so it lives here, not in the
   * Broadcast picker's own values. */
  pinetabWhere: () => ipcRenderer.invoke("pinetab:where"),
  pinetabSend: (key) => ipcRenderer.invoke("pinetab:send", key),
  /* Who is making the noise, and how loud on each device. */
  /* The tablet's glass: a still on the clipboard, a clip on disk, and a
   * written account of what the terminal is doing. */
  glassStill: (options) => ipcRenderer.invoke("glass:still", options),
  /* What the tablet is costing: battery, heartbeat, load and frame times.
   * One sweep serves every caller - see tabletVitals in main.js. */
  tabletVitals: () => ipcRenderer.invoke("tablet:vitals"),
  /* THE TABLET, LIVE. `mirrorShow` is the sidebar icon opening the window;
   * everything after it is that window talking about itself. */
  mirrorShow: (options) => ipcRenderer.invoke("mirror:show", options),
  mirrorOpen: (shape) => ipcRenderer.invoke("mirror:open", shape),
  mirrorSize: (size) => ipcRenderer.invoke("mirror:size", size),
  mirrorHow: () => ipcRenderer.invoke("mirror:how"),
  mirrorWindow: (shape) => ipcRenderer.invoke("mirror:window", shape),
  mirrorFull: (want) => ipcRenderer.invoke("mirror:full", want),
  mirrorOnTop: () => ipcRenderer.invoke("mirror:ontop"),
  /* Reaching through the picture: a tap, a swipe, a key, or typed text, in
   * the DISPLAY's coordinates. See tablet-input.cjs. */
  mirrorTouch: (act) => ipcRenderer.invoke("mirror:touch", act),
  /* The tablet's own camera, put on its screen so the mirror carries it. */
  tabletCamera: (want) => ipcRenderer.invoke("tablet:camera", want),
  /* The camera in a window of its own, streamed - the tablet keeps the
   * station on its screen. */
  cameraOpen: (want) => ipcRenderer.invoke("camera:open", want),
  /* Waking the tablet from here, because a WebView on a sleeping tablet is
   * not running and cannot wake itself. */
  tabletWake: (want) => ipcRenderer.invoke("tablet:wake", want),
  cameraWhere: () => ipcRenderer.invoke("camera:where"),
  cameraFace: (facing) => ipcRenderer.invoke("camera:face", facing),
  /* Grabbing and clipping from the camera, through the same mills the screen
   * captures use. */
  cameraGrab: (want) => ipcRenderer.invoke("camera:grab", want),
  cameraClip: (want) => ipcRenderer.invoke("camera:clip", want),
  /* Countdown, record, save where you say - see camera:record in main.js. */
  cameraRecord: (want) => ipcRenderer.invoke("camera:record", want),
  cameraTune: (want) => ipcRenderer.invoke("camera:tune", want),
  /* The speaker on the mirror. null asks, true/false sets - and what comes
   * back is what is AUDIBLE, not what was asked for. */
  mirrorSound: (want) => ipcRenderer.invoke("mirror:sound", want),
  /* The frame picker: the recording to scrub through, and the one frame
   * chosen out of it. Picking copies it and, if asked, opens the mark-up
   * window on it - so a picked frame goes exactly where a fresh screenshot
   * would have. */
  framePending: () => ipcRenderer.invoke("frame:pending"),
  framePick: (choice) => ipcRenderer.invoke("frame:pick", choice),
  frameDone: () => ipcRenderer.invoke("frame:done"),
  /* The mark-up window asks for the picture it was opened with, and hands
   * back a marked-up one to be saved. Copying is copyImage, below. */
  shotImage: () => ipcRenderer.invoke("shot:image"),
  shotSave: (dataUrl) => ipcRenderer.invoke("shot:save", dataUrl),
  /* The editor's resolution slider and algorithm picker. Always resampled
   * from the ORIGINAL, never from the copy already on screen. */
  shotResample: (want) => ipcRenderer.invoke("shot:resample", want),
  /* Inspection mode: a region of a screenshot, turned back into the thing it
   * was a picture of. See the note in main.js. */
  inspectPlay: (region) => ipcRenderer.invoke("inspect:play", region),
  inspectDownload: (region, options) =>
    ipcRenderer.invoke("inspect:download", region, options),
  /* The flow chart window, and what it opens with. */
  inspectFlow: (region) => ipcRenderer.invoke("inspect:flow", region),
  flowPending: () => ipcRenderer.invoke("flow:pending"),

  /* The inspector's script sidebar: hear one, or save one, a round, or the
   * run of air around it. */
  inspectPlay: (what) => ipcRenderer.invoke("inspect:play", what),

  /* Changing how a line is put together and put on the air. Each is a thin
   * pass-through to a route the station already has - see line-edit.js. */
  lineEdit: (what) => ipcRenderer.invoke("line:edit", what),
  lineRevise: (what) => ipcRenderer.invoke("line:revise", what),
  lineTint: (what) => ipcRenderer.invoke("line:tint", what),
  lineRecord: (what) => ipcRenderer.invoke("line:record", what),
  lineVote: (what) => ipcRenderer.invoke("line:vote", what),
  inspectExport: (what) => ipcRenderer.invoke("inspect:export", what),

  /* WHAT THE PROMPTS ARE NO LONGER ALLOWED TO CARRY. The X in the flow
   * chart - a standing decision about every future round, so it is kept on
   * the station rather than here. */
  promptCuts: () => ipcRenderer.invoke("prompt:cuts"),
  promptCut: (what) => ipcRenderer.invoke("prompt:cut", what),
  promptKeep: (what) => ipcRenderer.invoke("prompt:keep", what),

  /* WHAT THE PROMPTS ARE NO LONGER ALLOWED TO CARRY. The X in the flow
   * chart - a standing decision about every future round, so it is kept on
   * the station rather than here. */
  promptCuts: () => ipcRenderer.invoke("prompt:cuts"),
  promptCut: (what) => ipcRenderer.invoke("prompt:cut", what),
  promptKeep: (what) => ipcRenderer.invoke("prompt:keep", what),
  inspectDeep: (region) => ipcRenderer.invoke("inspect:deep", region),
  glassClip: (seconds, options) => ipcRenderer.invoke("glass:clip", seconds, options),
  /* Stop a pull in flight and take a complete, shorter clip instead. */
  glassStop: () => ipcRenderer.invoke("glass:stop"),
  /* The export window: what is waiting, and what to make of it. */
  clipPending: () => ipcRenderer.invoke("clip:pending"),
  clipExport: (choices) => ipcRenderer.invoke("clip:export", choices),
  clipDone: () => ipcRenderer.invoke("clip:done"),
  glassReport: (options) => ipcRenderer.invoke("glass:report", options),

  terminalAudioTable: () => ipcRenderer.invoke("terminal-audio:table"),
  terminalAudioSet: (id, patch) => ipcRenderer.invoke("terminal-audio:set", id, patch),
  /* #990: THE COPY BUTTON DID NOTHING.
   *
   * The window is loaded from file://, which is not a secure context, so
   * navigator.clipboard is undefined there - and both copy sites called
   * it with an empty rejection handler, so the click failed in complete
   * silence. Electron's own clipboard has no such restriction and is
   * available right here in the preload. */
  copyText: (text) => {
    try {
      clipboard.writeText(String(text == null ? "" : text));
      return true;
    } catch (err) {
      return false;
    }
  },
  /* #1047: THE COPY BUTTON HAS TO COPY A PICTURE.
   *
   * "when i click copy, I want to copy all the pages of the paper as an
   *  image to clipboard allowing me to paste it anywhere."
   *
   * The Gazette window stitches every page into one tall PNG and hands it
   * here as a data URL. navigator.clipboard.write is refused on a file://
   * page exactly as writeText was in #990; Electron's clipboard is not,
   * and nativeImage reads a PNG data URL directly. */
  copyImage: (dataUrl) => {
    try {
      const png = nativeImage.createFromDataURL(String(dataUrl || ""));
      if (!png || png.isEmpty()) return false;
      clipboard.writeImage(png);
      return true;
    } catch (err) {
      return false;
    }
  }
});
