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
 *
 * ---------------------------------------------------------------------------
 * AND NOW IT FILMS THE SOUND TOO (2026-09-15, #1205).
 *
 *   "Similar to the tablet, I always want to capture the broadcast audio of
 *    the recording. So any time that I go into the video editor, I need the
 *    audio of the broadcast."
 *
 * WHY THE ROAD CHANGED ORDER. #1182c chose getUserMedia with the legacy
 * chromeMediaSource constraints and wrote down exactly why: getDisplayMedia
 * needs TRANSIENT USER ACTIVATION and a recorder that starts itself two
 * seconds after the app opens has no gesture to spend. That reasoning still
 * holds - and it is also the reason the ring was silent, because the audio
 * this app can capture is offered through the display-media handler and
 * nowhere else. main.js answers that handler with
 *
 *     { video: win, audio: 'loopback' }
 *
 * which is the machine's playback mix. That matters for a reason particular
 * to this app: the broadcast does NOT play in this document. It plays in the
 * panel, `<webview id="controlFrame">` (index.html:542), a separate renderer
 * process - so anything that hooks media elements HERE (PineAir does) taps a
 * document with no broadcast in it. A loopback tap sits below that boundary
 * and hears the panel, the shell, the sampler and the SFX set alike.
 *
 * SO THE GESTURE IS SUPPLIED RATHER THAN WAITED FOR. main.js starts this
 * recorder through executeJavaScript(code, userGesture = true), which gives
 * Blink a real transient activation, and start() calls
 * getDisplayMedia SYNCHRONOUSLY so none of it is spent on an IPC round trip
 * first. Two backstops behind that, because an activation that does not
 * arrive must not cost the whole ring:
 *
 *   - if getDisplayMedia is refused, the old getUserMedia road opens the
 *     window with no audio at all and the ring is told, in words, that the
 *     recording is silent and why;
 *   - the first real gesture anywhere in the shell after that UPGRADES the
 *     capture: one stop-and-start, and the pieces carry sound from then on.
 *
 * WHAT IS NOT CAPTURED: the microphone. Nothing here opens an input device,
 * and the desk's clip window still only offers a mic channel for recordings
 * that arrived from the tablet with one. Recording the room because somebody
 * asked for the broadcast would be a different feature and a worse one.
 */
(function (root) {
  'use strict';

  var SEG_MS = 2000;            /* matches SEGMENT_MS in screen-ring.cjs */
  var WIDTH = 1280;
  var HEIGHT = 800;
  var FPS = 12;
  var BITS = 1600000;

  /* #1205: the sound. 128k Opus is transparent enough for a broadcast and is
   * a twentieth of the picture's weight, so the ring's size note above still
   * stands. */
  var AUDIO_BITS = 128000;

  var doc = root.document || null;
  var stream = null;
  var rec = null;
  var running = false;
  var stopping = false;
  var startedAt = 0;            /* when the piece now recording began */
  var parts = [];
  var failures = 0;
  var said = '';
  /* #1205: what this capture carries, as a thing that can be ASKED rather
   * than assumed. `state` is one of capturing / unavailable, `detail` is the
   * plain reason the editor and the export sheet print. */
  var sound = { present: false, state: 'unknown', detail: 'not started yet',
                supported: null, road: '' };
  var upgrades = 0;             /* gesture-driven retries spent */
  var lastUpgrade = 0;

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

  /* #1205: the codec pair, asked for together. A recorder given a video-only
   * mime type on a stream that HAS audio drops the audio without a word, so
   * the list is chosen from what the stream actually holds. */
  function pickType(withAudio) {
    var want = withAudio
      ? ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp9,opus', 'video/webm']
      : ['video/webm;codecs=vp8', 'video/webm;codecs=vp9', 'video/webm'];
    for (var i = 0; i < want.length; i += 1) {
      try {
        if (root.MediaRecorder && root.MediaRecorder.isTypeSupported(want[i])) return want[i];
      } catch (err) { /* keep looking */ }
    }
    return '';
  }

  /* Is there a live audio track on the capture RIGHT NOW? Asked per piece,
   * because a loopback that ends underneath the recorder - a device changed,
   * an output switched - must show up as a gap in the ring's coverage rather
   * than as a file that is quietly silent halfway through. */
  function audioLive() {
    var tracks = [];
    try { tracks = (stream && stream.getAudioTracks && stream.getAudioTracks()) || []; }
    catch (err) { return false; }
    for (var i = 0; i < tracks.length; i += 1) {
      if (tracks[i] && tracks[i].readyState === 'live' && !tracks[i].muted) return true;
    }
    return false;
  }

  /* The ring is told what the recorder carries, in the shape screen-ring.cjs
   * keeps and hot-corners.js prints. Sent at every start and at every change,
   * never inferred down there. */
  function tellSound() {
    if (!has('replayBegin')) return;
    try { desk().replayBegin({ audio: { source: 'desk-loopback-mix',
      present: !!sound.present, state: sound.state, detail: sound.detail,
      supported: sound.supported } }); }
    catch (err) { /* a bridge that will not take it is not a failed capture */ }
  }

  /* One piece, start to finish. Resolves when the piece is on its way down. */
  function recordOne() {
    if (!running || !stream) return;
    var withAudio = audioLive();
    var type = pickType(withAudio);
    var options = { videoBitsPerSecond: BITS };
    if (withAudio) options.audioBitsPerSecond = AUDIO_BITS;
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
        /* #1205: `a` is this piece's own answer about sound - the state the
         * recorder was STARTED with, so a track that died mid-piece is not
         * claimed by the piece it died in. */
        return desk().replayPush(buf, { at: at, ms: ms, a: !!withAudio,
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

  /* THE CAPTURE, AND THE ONE ROAD THAT CARRIES SOUND (#1182c, #1205).
   *
   * #1182c measured this and the measurement still stands: getDisplayMedia
   * requires TRANSIENT USER ACTIVATION - something pressed within the last
   * few seconds - and a recorder that starts itself after the first paint has
   * nothing to spend. Electron's request handler removes the picker; it does
   * not remove that rule. getUserMedia with the chromeMediaSource constraints
   * carries no such requirement, which is why the ring has been opened that
   * way.
   *
   * #1205 is why the ORDER is now the other way round. The application's own
   * audio is offered through the display-media handler and nowhere else:
   * main.js answers it with `audio: 'loopback'`. The legacy constraints road
   * has no equivalent that this Electron will honour, so a ring opened that
   * way can only ever be silent - and silent was the whole complaint.
   *
   * So: getDisplayMedia FIRST, called synchronously so that a supplied
   * activation is spent on the capture rather than on an IPC round trip;
   * the legacy road second, for when there is no activation to spend, and
   * with an honest note that the recording will have no sound until a gesture
   * upgrades it. Never the reverse - a video-only capture that succeeded
   * first would keep the ring silent for the whole session. */
  function openCapture(gesture) {
    var media = root.navigator && root.navigator.mediaDevices;
    if (!media) return Promise.reject(new Error('no media devices here'));
    var first = Promise.resolve(null);
    if (typeof media.getDisplayMedia === 'function') {
      try {
        first = media.getDisplayMedia({
          video: { width: { ideal: WIDTH }, height: { ideal: HEIGHT },
                   frameRate: { ideal: FPS, max: FPS } },
          /* Asked for explicitly: Electron ignores an audio answer for a
           * request that did not want audio, so `audio: true` here is what
           * makes the handler's loopback reachable at all. */
          audio: true
        }).then(function (got) { return { stream: got, road: 'display-media' }; },
          function (err) {
            withoutSound('the window would not give up its sound: '
              + String((err && err.message) || err));
            return null;
          });
      } catch (err) {
        withoutSound('display capture refused the ask: '
          + String((err && err.message) || err));
        first = Promise.resolve(null);
      }
    } else {
      withoutSound('this surface has no display capture, so it has no loopback');
    }
    return first.then(function (got) {
      if (got) return got;
      if (!has('replaySource') || typeof media.getUserMedia !== 'function') {
        throw new Error('this surface has no capture road at all');
      }
      return Promise.resolve(desk().replaySource()).then(function (source) {
        if (!source || !source.ok || !source.id) {
          throw new Error((source && source.detail) || 'no source to record');
        }
        /* The main process knows what this platform can do - loopback is
         * Windows-only in this Electron - so a silent recording says which
         * of the two reasons it is: a limit, or a gesture that never came. */
        if (source.loopback === false) {
          sound = { present: false, state: 'unavailable', supported: false,
            road: '', detail: source.detail
              || 'this platform has no loopback capture, so the recording is silent' };
        }
        return media.getUserMedia({
          audio: false,
          video: { mandatory: { chromeMediaSource: 'desktop',
                                chromeMediaSourceId: source.id,
                                maxWidth: WIDTH, maxHeight: HEIGHT,
                                maxFrameRate: FPS } }
        }).then(function (opened) { return { stream: opened, road: 'window-only' }; });
      });
    });
    function withoutSound(why) {
      if (!gesture) {
        sound = { present: false, state: 'unavailable', supported: sound.supported,
          detail: 'the recorder had no user gesture to open the sound with; '
            + 'the next click or key press will add it', road: '' };
        return;
      }
      sound = { present: false, state: 'unavailable', supported: sound.supported,
        detail: why, road: '' };
    }
  }

  /* #1205: WHY THE CAPTURE IS SAID TO HAVE SOUND, OR NOT.
   *
   * Asked of the stream rather than of the request: a handler that answered
   * `audio: false` - which is what an unsupported platform gets - produces a
   * perfectly good video stream with no audio track on it, and no error
   * anywhere. The only honest test is to count the tracks. */
  function settleSound(opened) {
    var road = (opened && opened.road) || '';
    if (audioLive()) {
      sound = { present: true, state: 'capturing', supported: true, road: road,
        detail: 'the desk mix, captured with the picture' };
      return;
    }
    var why = sound.detail;
    if (road === 'display-media') {
      /* The handler answered, and it answered without audio: the capture
       * this machine gave back has no audio track on it. That is not a
       * missing gesture - the gesture worked - so it is reported as the
       * machine's answer, with the known limit named beside it. `supported`
       * here means "loopback worked on this machine"; main.js reports the
       * platform's own answer separately as loopback_supported. */
      sound = { present: false, state: 'unavailable', supported: false, road: road,
        detail: 'the capture came back with no audio track, so the recording '
          + 'is silent (Electron captures application audio on Windows only)' };
      return;
    }
    sound = { present: false, state: 'unavailable', supported: sound.supported,
      road: road, detail: why || 'the capture came back with no audio track' };
  }

  function start(opts) {
    if (running) return Promise.resolve({ ok: true, already: true, audio: sound });
    if (!root.MediaRecorder) {
      note('this surface has no MediaRecorder');
      return Promise.resolve({ ok: false, detail: 'no MediaRecorder here' });
    }
    var gesture = !!(opts && opts.gesture);
    return openCapture(gesture).then(function (opened) {
      stream = opened.stream;
      running = true;
      stopping = false;
      settleSound(opened);
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
      /* The sound is declared before the first piece lands, so the export
       * sheet can say what the recording carries even if nobody has cut
       * anything yet. */
      tellSound();
      if (typeof desk().onReplayFlush === 'function') {
        try { desk().onReplayFlush(flush); } catch (err) { /* not fatal */ }
      }
      recordOne();
      note('recording this window' + (sound.present ? ' with the desk mix'
        : ' without sound: ' + sound.detail));
      if (!sound.present) watchForGesture();
      return { ok: true, audio: sound };
    }, function (err) {
      note('the window would not be captured: ' + String((err && err.message) || err));
      return { ok: false, detail: String((err && err.message) || err) };
    });
  }

  /* #1205: THE FIRST GESTURE UPGRADES A SILENT RING.
   *
   * A capture opened without an activation has no sound and can never grow
   * one: the track list on a live MediaStream is fixed. So the first real
   * press anywhere in the shell reopens it - one stop-and-start, the seam of
   * a single piece - and from then on the pieces carry the broadcast. Three
   * tries, ten seconds apart, because a platform with no loopback at all must
   * not reopen its capture on every click for the rest of the evening.
   *
   * A press inside the panel webview is a different document and never
   * reaches this listener; that is why main.js supplies the activation up
   * front and this is only the backstop. */
  var watching = false;
  function watchForGesture() {
    if (watching || !doc || !doc.addEventListener) return;
    if (sound.supported === false) return;
    watching = true;
    var kinds = ['pointerdown', 'keydown'];
    var take = function () {
      if (sound.present || !running) return unwatch();
      if (sound.supported === false) return unwatch();
      if (upgrades >= 3) return unwatch();
      var now = Date.now();
      if (now - lastUpgrade < 10000) return;
      lastUpgrade = now;
      upgrades += 1;
      /* Opened INSIDE the event, so the activation is still transient. */
      var media = root.navigator && root.navigator.mediaDevices;
      if (!media || typeof media.getDisplayMedia !== 'function') return unwatch();
      var asking;
      try {
        asking = media.getDisplayMedia({
          video: { width: { ideal: WIDTH }, height: { ideal: HEIGHT },
                   frameRate: { ideal: FPS, max: FPS } },
          audio: true
        });
      } catch (err) { return; }
      asking.then(function (got) {
        var tracks = [];
        try { tracks = (got.getAudioTracks && got.getAudioTracks()) || []; }
        catch (e) { tracks = []; }
        if (!tracks.length) {
          /* No sound on this platform either way; stop the capture we just
           * opened rather than leaving two running. */
          try { got.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
          sound = { present: false, state: 'unavailable', supported: false,
            road: 'display-media', detail: 'this platform has no loopback '
              + 'capture, so the recording is silent (Electron offers it on '
              + 'Windows only)' };
          tellSound();
          return unwatch();
        }
        swapTo(got);
      }, function (err) {
        note('the sound could not be added on that press: '
          + String((err && err.message) || err));
      });
    };
    var unwatch = function () {
      watching = false;
      for (var i = 0; i < kinds.length; i += 1) {
        try { doc.removeEventListener(kinds[i], take, true); } catch (e) {}
      }
    };
    for (var i = 0; i < kinds.length; i += 1) {
      try { doc.addEventListener(kinds[i], take, true); } catch (e) {}
    }
  }

  /* Move the recorder onto a new capture without losing the ring. The old
   * piece is closed first so nothing half-recorded reaches the disk, and the
   * old tracks are stopped so two captures of the same window are never live
   * together - two encoders on one screen is the thing that makes a desk
   * stutter. */
  function swapTo(got) {
    var old = stream;
    /* THE NEW CAPTURE IS INSTALLED FIRST, AND THAT ORDER IS THE WHOLE TRICK.
     * Stopping the running recorder restarts it from inside its own onstop,
     * and onstop starts the next piece from `stream` - so `stream` has to be
     * the new one BEFORE the stop, or the very next piece is recorded off
     * the capture that is about to be thrown away and lands marked as having
     * sound it does not have. Whether onstop is coming also decides who
     * starts that piece: calling recordOne() here as well would leave two
     * encoders on one window. */
    stream = got;
    settleSound({ road: 'display-media' });
    var willRestart = !!(rec && rec.state === 'recording');
    try { if (willRestart) rec.stop(); } catch (err) { willRestart = false; }
    try {
      var track = stream.getVideoTracks()[0];
      if (track) { track.addEventListener('ended', function () { note('the capture ended'); stop(); }); }
    } catch (err) {}
    try {
      if (old) {
        var tracks = old.getTracks();
        for (var i = 0; i < tracks.length; i += 1) { try { tracks[i].stop(); } catch (e) {} }
      }
    } catch (err) {}
    tellSound();
    note('the desk mix was added to the recording');
    if (running && !willRestart) recordOne();
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
    return { running: running, failures: failures, said: said, segment_ms: SEG_MS,
             audio: { present: !!sound.present, state: sound.state,
                      detail: sound.detail, supported: sound.supported,
                      road: sound.road, live: audioLive(), upgrades: upgrades } };
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
     * negotiation in the middle of the slowest part of startup.
     *
     * #1205: main.js starts this recorder itself, with a supplied user
     * activation, as soon as the page has finished loading - that is the only
     * road that opens the capture WITH the desk's sound on it. This timer is
     * the backstop for a main process that does not (an older build, a
     * window that never fired did-finish-load): it waits long enough for the
     * kick to have happened, and `start()` returns early if the ring is
     * already running, so the two cannot both open a capture. */
    root.setTimeout(function () {
      if (running) return;
      start().then(null, function () { /* start() already said why */ });
    }, 6000);
  }

  if (doc) {
    if (doc.readyState === 'complete' || doc.readyState === 'interactive') go();
    else doc.addEventListener('DOMContentLoaded', go);
  }

  root.PineScreenRing = { start: start, stop: stop, state: state, flush: flush,
                          sound: function () { return state().audio; },
                          SEG_MS: SEG_MS, WIDTH: WIDTH, HEIGHT: HEIGHT, FPS: FPS };
})(typeof window !== 'undefined' ? window : globalThis);
