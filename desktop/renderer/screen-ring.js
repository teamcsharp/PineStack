/* THE WINDOW, RECORDING ITSELF (2026-09-15, #1182).
 *
 * "Make sure that the Pine Box app also supports the ability to record and
 *  export screen recordings of the application that are being cached in
 *  real time as the application is running."
 *
 * The main process keeps the ring (screen-ring.cjs). This is the half that
 * actually films: it captures this window and hands finished pieces down.
 *
 * WHY THE RECORDER IS RESTARTED RATHER THAN LEFT RUNNING.
 *
 * MediaRecorder with a timeslice delivers chunks, and only the FIRST chunk
 * carries the WebM header. A ring made of the rest is a ring of bytes no
 * decoder will open, and you find that out at the moment somebody asks for
 * a cut - which is the worst moment to find it out. Stopping and starting
 * makes every piece a complete file. The seam costs a few milliseconds of
 * picture; the alternative costs the whole feature, silently.
 *
 * WHY THE SIZE IS PINNED. The pieces are concatenated to make a cut, and
 * the concat demuxer refuses pieces whose codec parameters disagree. This
 * window is resizable. Asking the capture for a fixed size makes the track
 * stable across a resize - the compositor scales the surface into it - so
 * the ring stays concatenable. The main side still checks, and drops
 * pieces from an older size rather than handing ffmpeg something it will
 * refuse.
 *
 * WHAT IT COSTS. VP8 at 1.6 Mbit and 12 frames a second, encoded on the
 * GPU where there is one. Thirty seconds - the default hold - is about six
 * megabytes on disk. Ten minutes, the ceiling the operator asked for, is
 * about 120 MB. Bounded a second way by weight in the main process, so a
 * screen that suddenly encodes badly cannot fill the drive.
 */
(function (root) {
  'use strict';

  var SEG_MS = 2000;            /* matches SEGMENT_MS in screen-ring.cjs */
  var WIDTH = 1280;
  var HEIGHT = 800;
  var FPS = 12;
  var BITS = 1600000;

  var doc = root.document || null;
  var stream = null;
  var rec = null;
  var running = false;
  var stopping = false;
  var startedAt = 0;            /* when the piece now recording began */
  var parts = [];
  var failures = 0;
  var said = '';

  function desk() {
    return root.pineDesktop || null;
  }

  function has(name) {
    var d = desk();
    return !!(d && typeof d[name] === 'function');
  }

  function note(what) {
    said = String(what || '');
    /* One line, once. A recorder that cannot start must say so somewhere a
     * person will look, and must not say it sixty times a minute. */
    try { if (root.console && root.console.log) root.console.log('[screen ring] ' + said); }
    catch (err) { /* a console that is not there is not a fault */ }
  }

  function pickType() {
    var want = ['video/webm;codecs=vp8', 'video/webm;codecs=vp9', 'video/webm'];
    for (var i = 0; i < want.length; i += 1) {
      try {
        if (root.MediaRecorder && root.MediaRecorder.isTypeSupported(want[i])) return want[i];
      } catch (err) { /* keep looking */ }
    }
    return '';
  }

  /* One piece, start to finish. Resolves when the piece is on its way down. */
  function recordOne() {
    if (!running || !stream) return;
    var type = pickType();
    var options = { videoBitsPerSecond: BITS };
    if (type) options.mimeType = type;
    try {
      rec = new root.MediaRecorder(stream, options);
    } catch (err) {
      failures += 1;
      note('the recorder would not start: ' + String((err && err.message) || err));
      running = false;
      return;
    }
    parts = [];
    startedAt = Date.now();
    rec.ondataavailable = function (ev) {
      if (ev && ev.data && ev.data.size) parts.push(ev.data);
    };
    rec.onerror = function (ev) {
      failures += 1;
      note('the recorder complained: '
        + String((ev && ev.error && ev.error.message) || 'no reason given'));
    };
    rec.onstop = function () {
      var at = startedAt;
      var ms = Date.now() - at;
      var blob = null;
      try { blob = new root.Blob(parts, { type: type || 'video/webm' }); }
      catch (err) { blob = null; }
      parts = [];
      /* The next piece starts BEFORE this one is sent down, so the seam is
       * the length of a stop-and-start rather than the length of an IPC
       * round trip with a megabyte in it. */
      if (running && !stopping) {
        try { recordOne(); } catch (err) { note('could not restart: ' + err.message); }
      }
      if (!blob || !blob.size) return;
      blob.arrayBuffer().then(function (buf) {
        if (!has('replayPush')) return;
        var track = null;
        try { track = stream.getVideoTracks()[0]; } catch (err) { track = null; }
        var size = {};
        try { size = (track && track.getSettings && track.getSettings()) || {}; }
        catch (err) { size = {}; }
        return desk().replayPush(buf, { at: at, ms: ms,
          w: Math.round(size.width || WIDTH), h: Math.round(size.height || HEIGHT) });
      }).then(null, function (err) {
        failures += 1;
        note('a piece did not reach the ring: ' + String((err && err.message) || err));
      });
    };
    try {
      rec.start();
    } catch (err) {
      failures += 1;
      note('the recorder refused to run: ' + String((err && err.message) || err));
      running = false;
      return;
    }
    root.setTimeout(function () {
      try { if (rec && rec.state === 'recording') rec.stop(); }
      catch (err) { /* onstop will not come; the next tick starts a new one */ }
    }, SEG_MS);
  }

  /* THE CAPTURE, WITHOUT A GESTURE TO SPEND (#1182c).
   *
   * Measured: the first cut of this used getDisplayMedia and no ring ever
   * appeared. getDisplayMedia requires TRANSIENT USER ACTIVATION - something
   * pressed within the last few seconds - and a recorder that starts itself
   * two seconds after the app opens has nothing to spend. Electron's request
   * handler removes the picker; it does not remove that rule.
   *
   * getUserMedia with the chromeMediaSource constraints carries no such
   * requirement. The main process names the source (replay:source, which
   * answers with THIS window and nothing else), and maxWidth/maxHeight pin
   * the capture size so a resize cannot split the ring into pieces that
   * will not concatenate.
   *
   * getDisplayMedia is kept as the second try, because when there IS a
   * gesture to spend it is the better road and the one that survives
   * whatever Electron does to the legacy constraints next. */
  function openCapture() {
    var media = root.navigator && root.navigator.mediaDevices;
    if (!media) return Promise.reject(new Error('no media devices here'));
    var byId = Promise.resolve(null);
    if (has('replaySource') && typeof media.getUserMedia === 'function') {
      byId = Promise.resolve(desk().replaySource()).then(function (got) {
        if (!got || !got.ok || !got.id) return null;
        return media.getUserMedia({
          audio: false,
          video: { mandatory: { chromeMediaSource: 'desktop',
                                chromeMediaSourceId: got.id,
                                maxWidth: WIDTH, maxHeight: HEIGHT,
                                maxFrameRate: FPS } }
        });
      }, function () { return null; });
    }
    return byId.then(function (got) {
      if (got) return got;
      if (typeof media.getDisplayMedia !== 'function') {
        throw new Error('this surface has no display capture');
      }
      return media.getDisplayMedia({
        video: { width: { ideal: WIDTH }, height: { ideal: HEIGHT },
                 frameRate: { ideal: FPS, max: FPS } },
        audio: false
      });
    });
  }

  function start() {
    if (running) return Promise.resolve({ ok: true, already: true });
    if (!root.MediaRecorder) {
      note('this surface has no MediaRecorder');
      return Promise.resolve({ ok: false, detail: 'no MediaRecorder here' });
    }
    return openCapture().then(function (got) {
      stream = got;
      running = true;
      stopping = false;
      /* The capture ending underneath us - a window closed, a device
       * changed - must not leave a recorder pointed at nothing. */
      try {
        var track = stream.getVideoTracks()[0];
        if (track) {
          track.addEventListener('ended', function () {
            note('the capture ended');
            stop();
          });
        }
      } catch (err) { /* not fatal */ }
      if (has('replayBegin')) { try { desk().replayBegin({}); } catch (err) {} }
      if (typeof desk().onReplayFlush === 'function') {
        try { desk().onReplayFlush(flush); } catch (err) { /* not fatal */ }
      }
      recordOne();
      note('recording this window');
      return { ok: true };
    }, function (err) {
      note('the window would not be captured: ' + String((err && err.message) || err));
      return { ok: false, detail: String((err && err.message) || err) };
    });
  }

  function stop() {
    stopping = true;
    running = false;
    try { if (rec && rec.state === 'recording') rec.stop(); } catch (err) {}
    try {
      if (stream) {
        var tracks = stream.getTracks();
        for (var i = 0; i < tracks.length; i += 1) { try { tracks[i].stop(); } catch (e) {} }
      }
    } catch (err) {}
    stream = null;
    rec = null;
    if (has('replayStop')) { try { desk().replayStop('the page stopped it'); } catch (err) {} }
    return { ok: true };
  }

  function state() {
    return { running: running, failures: failures, said: said, segment_ms: SEG_MS };
  }

  /* #1182d: CLOSE THE PIECE YOU ARE ON.
   *
   * Asked for by the main process just before it cuts. Stopping the recorder
   * emits the piece straight away and onstop starts the next one, so the
   * ring loses nothing and gains the seconds that were still in flight - and
   * those are the seconds the operator actually wanted, because a rolling
   * recorder is asked for the thing that just happened. */
  function flush() {
    try {
      if (rec && rec.state === 'recording') { rec.stop(); return true; }
    } catch (err) { /* the timer will close it soon enough */ }
    return false;
  }

  /* Only on the desk. The tablet has its own recorder in Kotlin and must not
   * grow a second one - see replay/ScreenReplay.kt. `replayPush` is the tell:
   * it exists only on this app's bridge. */
  function go() {
    if (!has('replayPush')) return;
    /* A moment after the first paint. Starting inside load puts a capture
     * negotiation in the middle of the slowest part of startup. */
    root.setTimeout(function () {
      start().then(null, function () { /* start() already said why */ });
    }, 2500);
  }

  if (doc) {
    if (doc.readyState === 'complete' || doc.readyState === 'interactive') go();
    else doc.addEventListener('DOMContentLoaded', go);
  }

  root.PineScreenRing = { start: start, stop: stop, state: state, flush: flush,
                          SEG_MS: SEG_MS, WIDTH: WIDTH, HEIGHT: HEIGHT, FPS: FPS };
})(typeof window !== 'undefined' ? window : globalThis);
