/* window.pineDesktop, on Android.
 *
 * THE PROBLEM THIS FILE SOLVES.
 *
 * The panel was written against Electron's preload (desktop/preload.js),
 * where every method is `ipcRenderer.invoke(...)` and therefore returns a
 * Promise. Android's @JavascriptInterface is the opposite: the method is
 * called on a private binder thread, it must return before the JS engine
 * continues, and it can only hand back a Java primitive or a String.
 * Anything that touches the network - which is nearly all of this API -
 * cannot be answered inside that call.
 *
 * So the native side is split in two:
 *
 *   __pineNative.invoke(id, method, argsJson) -> ack envelope, immediately
 *   __pineBridgeSettle(id, envelopeJson)      -> called back later, from
 *                                                the UI thread, with the
 *                                                real answer
 *
 * and this shim keeps a Map of request id -> {resolve, reject} between the
 * two, so that from the panel's point of view `await pineDesktop.get(...)`
 * behaves exactly as it does under Electron.
 *
 * THE TWO EXCEPTIONS ARE DELIBERATE. app.py:170463 reads
 *
 *     if (desk.copyImage(data) === false) return "the desktop clipboard..."
 *
 * - a STRICT comparison against false. A Promise is never === false, so a
 * promisified copyImage would report success on every failure. copyText and
 * copyImage are therefore wired straight through to synchronous native
 * methods returning a real boolean, matching Electron's preload, which also
 * returns a bare boolean for exactly these two.
 */
(function (win) {
  "use strict";

  if (win.pineDesktop && win.pineDesktop.__pineKiosk) return;

  var native = win.__pineNative;
  if (!native) {
    /* The shim is injected on every page start, including error pages,
     * where the interface may not be attached yet. Say so once and leave
     * the page alone rather than half-installing an API. */
    if (win.console) console.warn("[pine] native bridge absent; pineDesktop not installed");
    return;
  }

  var pending = new Map();
  var seq = 0;

  /* Called by Kotlin via evaluateJavascript once the work is done. The
   * envelope is {id, ok:true, value} or {id, ok:false, error}. */
  win.__pineBridgeSettle = function (id, envelopeJson) {
    var slot = pending.get(id);
    if (!slot) return false;            /* already settled, or a late reply */
    pending["delete"](id);
    var env;
    try {
      env = JSON.parse(envelopeJson);
    } catch (err) {
      slot.reject(new Error("bridge returned unparseable JSON: " + envelopeJson));
      return true;
    }
    if (env && env.ok) slot.resolve(env.value === undefined ? null : env.value);
    else slot.reject(new Error((env && env.error) || "the bridge refused it"));
    return true;
  };

  function call(method, args) {
    return new Promise(function (resolve, reject) {
      var id = "r" + (++seq) + "-" + Date.now();
      pending.set(id, { resolve: resolve, reject: reject });
      var ack;
      try {
        ack = native.invoke(id, method, JSON.stringify(args || []));
      } catch (err) {
        pending["delete"](id);
        reject(err instanceof Error ? err : new Error(String(err)));
        return;
      }
      /* A refusal that is knowable without doing any work - an unknown
       * method, a closed bridge - comes back in the ack, and no settle
       * callback will ever arrive for it. Settle it here instead. */
      var parsed = null;
      try { parsed = JSON.parse(ack); } catch (err) { parsed = null; }
      if (!parsed || parsed.accepted !== true) {
        pending["delete"](id);
        reject(new Error((parsed && parsed.error) || "the bridge did not accept the call"));
      }
    });
  }

  function promised(method) {
    return function () {
      return call(method, Array.prototype.slice.call(arguments));
    };
  }

  /* The two on* subscriptions. Electron pushes these from the main process;
   * here nothing pushes them (there is no local backend to log), but the
   * callbacks are kept so a later native push has somewhere to land and,
   * more importantly, so a panel that registers one does not throw. */
  var subscribers = { "backend-log": [], "support-progress": [] };
  function subscribe(channel, cb) {
    if (typeof cb === "function" && subscribers[channel]) subscribers[channel].push(cb);
    return function () {
      var list = subscribers[channel] || [];
      var at = list.indexOf(cb);
      if (at >= 0) list.splice(at, 1);
    };
  }
  win.__pineBridgeEmit = function (channel, payloadJson) {
    var list = subscribers[channel];
    if (!list || !list.length) return false;
    var payload;
    try { payload = JSON.parse(payloadJson); } catch (err) { payload = payloadJson; }
    for (var i = 0; i < list.length; i++) {
      try { list[i](payload); } catch (err) { /* a bad subscriber never stops the feed */ }
    }
    return true;
  };

  /* Every name Electron's preload exposes, so a panel that feature-detects
   * with `typeof pineDesktop.x === "function"` sees the same surface. The
   * ones the tablet genuinely cannot do (the station's own process, the LCD
   * hardware, the adb-driven terminal provisioner - all of which live on
   * the BOX, not on the terminal) resolve with {ok:false, unsupported:true}
   * rather than rejecting: a resolved refusal shows up in the panel as
   * "not available here", a rejection shows up as a crashed handler. */
  var api = {
    __pineKiosk: true,

    /* --- configuration ---------------------------------------------- */
    readConfig: promised("readConfig"),
    writeConfig: promised("writeConfig"),

    /* --- the station API -------------------------------------------- */
    discoverKey: promised("discoverKey"),
    get: promised("get"),
    post: promised("post"),
    put: promised("put"),
    del: promised("del"),

    /* --- shell ------------------------------------------------------- */
    openExternal: promised("openExternal"),
    buildInfo: promised("buildInfo"),

    /* --- backend lifecycle: no-ops by design -------------------------
     * The station is not on the tablet. It runs on the box at
     * 10.89.1.246:8096 and was already running before this terminal was
     * switched on. There is nothing here to start, stop or set up. */
    startBackend: promised("startBackend"),
    stopBackend: promised("stopBackend"),
    setupBackend: promised("setupBackend"),
    reconstituteDesktop: promised("reconstituteDesktop"),
    backendLog: promised("backendLog"),
    onBackendLog: function (cb) { return subscribe("backend-log", cb); },
    onSupportProgress: function (cb) { return subscribe("support-progress", cb); },

    /* --- the LCD: stubs -----------------------------------------------
     * The LCD is a serial/USB panel wired to the box. The tablet has no
     * line to it, so these answer honestly and immediately. */
    lcdState: promised("lcdState"),
    lcdConfigure: promised("lcdConfigure"),
    lcdDiscover: promised("lcdDiscover"),
    lcdConnect: promised("lcdConnect"),
    lcdStart: promised("lcdStart"),
    lcdStop: promised("lcdStop"),
    lcdDisconnect: promised("lcdDisconnect"),
    lcdFrame: promised("lcdFrame"),
    lcdEvents: promised("lcdEvents"),
    lcdControl: promised("lcdControl"),
    lcdDisplayMode: promised("lcdDisplayMode"),
    lcdPaperImage: promised("lcdPaperImage"),
    lcdFirmware: promised("lcdFirmware"),
    lcdSampleDirectory: promised("lcdSampleDirectory"),
    lcdDownload: promised("lcdDownload"),

    /* --- the terminal provisioner: stubs ------------------------------
     * This IS the terminal. The provisioner drives adb from the operator's
     * PC at a tablet; asking the tablet to provision itself is meaningless,
     * and terminalUnlock erases the device. Refused here, never forwarded. */
    terminalTools: promised("terminalTools"),
    terminalSurvey: promised("terminalSurvey"),
    terminalSnapshot: promised("terminalSnapshot"),
    terminalBootloader: promised("terminalBootloader"),
    terminalReboot: promised("terminalReboot"),
    terminalVerifyFirmware: promised("terminalVerifyFirmware"),
    terminalVerifyGsi: promised("terminalVerifyGsi"),
    terminalUnlock: promised("terminalUnlock"),
    terminalDiscover: promised("terminalDiscover"),
    terminalWirelessEnable: promised("terminalWirelessEnable"),
    terminalWirelessConnect: promised("terminalWirelessConnect"),
    terminalWirelessDisconnect: promised("terminalWirelessDisconnect"),

    /* --- the microphone ------------------------------------------------
     * NOT getUserMedia. Measured on this device: the panel is served from
     * http://10.89.1.246:8096, which is not a secure context, and Chromium
     * removes `navigator.mediaDevices` ENTIRELY from such a page - the
     * object the browser API would be called on does not exist, and no
     * Android permission puts it back. So the listening is done in Kotlin
     * and only the WORDS cross the bridge.
     *
     * micStart()  -> {ok, rate, effects, detail}
     * micStop()   -> {ok, text, heard, seconds, level, detail}
     * micCancel() -> {ok}    throw the take away
     * micState()  -> {running, seconds, level, effects, error}
     * micLevel()  -> 0..1, SYNCHRONOUS: the talk dot reads it every frame
     *                and a promise per frame would flood the settle path. */
    /* micTake()  -> {ok, bytes, rate, seconds, wall, level, quiet}
     *   Stops the take and PARKS it instead of transcribing it - the
     *   desktop's screen recorder wants the sound, not the words.
     * micChunk({at, much}) -> {ok, at, bytes, sent, done, b64}
     *   One slice of the parked take. Chunked because a thirty-second take
     *   is 1.3 MB of base64 and a bridge return that size is the kind of
     *   thing that works in a test and fails on a long clip. */
    /* THE ROLLING RECORD OF THE SCREEN.
     *
     * replayState() -> {ok, running, seconds, holds, bytes, detail}
     *   `seconds` is what is HELD, which is less than `holds` for the first
     *   minute and after the screen has been dark.
     * replaySave({seconds}) -> {ok, bytes, asked, seconds}
     *   Writes the last N and parks it. `seconds` is what was actually
     *   written, which can be less than asked for.
     * replayChunk({at, much}) -> {ok, at, bytes, sent, done, b64} */
    /* WHAT THE TERMINAL CONFIRMED ON ITS WAY UP.
     *
     * readyReport() -> {ok, at, network, tailnet, road, roadMs, steps[]}
     *   Each step is {what, ok, said}. Written once at startup - see
     *   net/Readiness.kt - so this is a record, not a fresh probe. */
    readyReport: promised("readyReport"),

    replayState: promised("replayState"),
    replaySave: promised("replaySave"),
    replayChunk: promised("replayChunk"),

    micTake: promised("micTake"),
    micChunk: promised("micChunk"),
    micStart: promised("micStart"),
    micStop: promised("micStop"),
    micCancel: promised("micCancel"),
    micState: promised("micState"),
    micLevel: function () {
      try { return Number(native.micLevel()) || 0; }
      catch (err) { return 0; }
    },
    /* A page can ask whether there is an ear at all before drawing a dot
     * that cannot work. On the desktop this is absent and the renderer
     * falls back to getUserMedia, which IS available there. */
    micNative: function () { return true; },

    /* Keep a line: {route, said, id, where:"downloads"|"recordings"}
     * -> {ok, where, bytes, detail}. The audio is fetched and written
     * natively; it never crosses this bridge. */
    keepClip: promised("keepClip"),

    /* THE HEADPHONE JACK. `jack({on:true})` hands the broadcast to the
     * cable, `{on:false}` takes it back, and no argument reports where
     * things stand: {ok, on, canDetect, say}.
     *
     * This exists because the framework will not do it: measured on this
     * GSI, the kernel sees the plug (SwitchValues: 4) and the framework
     * does not (mMainType=0x0), because config_useDevInputEventForAudioJack
     * ships false. The terminal makes the announcement itself. */
    jack: promised("jack"),

    /* THE GALLERY ON THE GLASS. With no argument it reports what is hanging;
     * `{now:true}` makes it look again rather than waiting out the five
     * minutes. The wallpaper itself runs natively on its own timer - this is
     * only the page's window onto it. */
    wallpaper: promised("wallpaper"),

    /* WRITING A FILE OUT. saveText takes a string (a sampler preset, which
     * is JSON); saveBytes takes base64 (the WAVs of an MPC kit - audio put
     * through a JSON string comes back corrupted, silently).
     *
     * These exist because an <a download> is INERT inside this WebView. The
     * kit exporter used to fall back to one and report success, so it
     * cheerfully announced a kit that had never been written. */
    saveText: promised("saveText"),
    saveBytes: promised("saveBytes"),

    /* THE MPC OVER THE CABLE. usbState says what is plugged in and whether a
     * disk has been pointed at; usbPick shows the system folder picker once,
     * and the grant is persisted; usbSend copies an already-written kit
     * folder from Downloads onto that disk. */
    usbState: promised("usbState"),
    usbPick: promised("usbPick"),
    usbSend: promised("usbSend"),

    /* And the READ half: list the MPC's disk, and pull a file off it in
     * pieces - a kit is WAVs, and a whole one in a single answer would be a
     * multi-megabyte base64 string through a channel built for JSON. */
    usbList: promised("usbList"),
    usbRead: promised("usbRead"),

    /* --- the clipboard: SYNCHRONOUS, see the header ------------------- */
    copyText: function (text) {
      try { return native.copyText(text == null ? "" : String(text)); }
      catch (err) { return false; }
    },
    copyImage: function (dataUrl) {
      try { return native.copyImage(String(dataUrl || "")); }
      catch (err) { return false; }
    },
    /* From desktop/renderer/webview-preload.js: lets a page tell a real
     * bridge from a stub without attempting a copy. */
    clipboardReady: function () { return true; }
  };

  win.pineDesktop = api;

  /* Two marks the panel and any diagnostic page can read: which shell this
   * is, and that a clipboard road exists. app.py already branches on
   * pineDesktop being present; this says WHICH pineDesktop. */
  win.pineKiosk = { platform: "android", version: 1 };

  try { win.dispatchEvent(new Event("pine-desktop-ready")); } catch (err) { /* pre-DOM */ }
})(window);
