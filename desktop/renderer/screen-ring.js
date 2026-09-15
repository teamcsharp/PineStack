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
 *
 * ---------------------------------------------------------------------------
 * AND #1205 WAS WRONG ABOUT HOW (2026-09-15, #1207).
 *
 * The comment above says the handler answers `{ video: win, audio: 'loopback' }`
 * and that the sound comes with the picture. It never did - every capture
 * fell straight through to the legacy road and every recording was silent.
 * The diagnostic in the temp folder is what finally said so, in one line:
 *
 *     the window would not give up its sound: Error starting capture
 *
 * Measured against Electron 37.10.3: `{ video: win, audio: 'loopback' }` is
 * refused, and so is `{ video: win, audio: <panel frame> }`. System loopback
 * is offered for a SCREEN and not beside one window; and a BrowserWindow is
 * not a thing this Electron will take as `video` at all ("video must be a
 * WebFrameMain or DesktopCapturerSource"). So getDisplayMedia has always
 * failed here and the picture has always come from the getUserMedia road
 * below - which is exactly why the picture is right and the file is silent.
 *
 * Pointing the capture at the panel frame for BOTH streams was accepted and
 * did carry 48 kHz opus, but then the picture is the panel's own control
 * page: no rail, no menu, not the view he was watching.
 *
 * WHAT IS ACCEPTED IS A SECOND CAPTURE WITH NO PICTURE IN IT AT ALL:
 *
 *     getDisplayMedia({ video: false, audio: true })
 *       answered with { audio: <panel frame>, enableLocalEcho: true }
 *
 * Measured: one audio track, labelled "Tab audio", no video track; it may run
 * beside the window capture; and asking with `video: true` instead fails the
 * whole request, because the handler must then produce a picture it has not
 * got. So the constraint below says `video: false` and that is load-bearing.
 *
 * enableLocalEcho IS NOT OPTIONAL, AND IT WAS MEASURED BY LISTENING. With a
 * tone playing in the panel and the machine's own speaker mix read back
 * through a screen-loopback capture, one FFT bin, tone on minus tone off:
 *
 *     nothing capturing the frame        -28.1 dB
 *     capturing it, enableLocalEcho true -28.0 dB   (the speakers keep it)
 *     capturing it, flag left off        -85.4 dB   (the speakers lose it)
 *
 * That is the worst outcome available here - the operator listening to his
 * own station and the recorder silencing it - and it is one missing property
 * away at all times.
 *
 * THE PICTURE RECORDER BELOW IS UNCHANGED except that it now asks for
 * `audio: false`. It never got sound and cannot; saying so makes the request
 * honest, lets main.js tell the two captures apart by what they asked for,
 * and removes the reason the old code had to reopen the window capture on a
 * gesture - so the picture is now opened once and never disturbed again.
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
  /* #1207: THE SECOND RECORDER. Its own capture, its own MediaRecorder, its
   * own two-second loop. Deliberately not coupled to the picture's: they
   * cannot be made to start on the same millisecond, so the cut is built to
   * measure the difference instead - and keeping them independent means
   * either one can die without stopping the other. */
  var sndStream = null;
  var sndRec = null;
  var sndRunning = false;
  var sndStopping = false;
  var sndStartedAt = 0;
  var sndParts = [];
  var sndPieces = 0;
  /* #1207: the open that is already in flight. start() asks for the sound and
   * main.js asks again a moment later with its own user activation, so two
   * calls can be in the air before either has resolved. Without this they
   * would both open a capture of the panel and the second would overwrite the
   * first - two encoders on one frame, one of them orphaned and never
   * stopped. Callers share the one promise instead. */
  var sndOpening = null;
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
    return firstSupported(want);
  }

  /* #1207: the sound ring's own container. Opus in WebM, which is what the
   * capture hands over anyway, so nothing is transcoded until the cut. */
  function pickSoundType() {
    return firstSupported(['audio/webm;codecs=opus', 'audio/webm']);
  }

  function firstSupported(want) {
    for (var i = 0; i < want.length; i += 1) {
      try {
        if (root.MediaRecorder && root.MediaRecorder.isTypeSupported(want[i])) return want[i];
      } catch (err) { /* keep looking */ }
    }
    return '';
  }

  /* Is there a live audio track on the SOUND capture right now? Asked per
   * piece, because a capture that ends underneath the recorder - the panel
   * reloaded, an output switched - must show up as a gap in the ring's
   * coverage rather than as a file that is quietly silent halfway through.
   *
   * #1207: it asks the sound capture, not the picture's. The picture capture
   * has no audio track and asking it would report silence forever. */
  function audioLive() {
    var tracks = [];
    try { tracks = (sndStream && sndStream.getAudioTracks && sndStream.getAudioTracks()) || []; }
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
    try { desk().replayBegin({ audio: { source: 'desk-broadcast-frame',
      present: !!sound.present, state: sound.state, detail: sound.detail,
      supported: sound.supported, road: sound.road },
      /* #1207: both streams named on the one road that writes the
       * diagnostic, because a fault in either is read out of that file. */
      streams: { picture: { open: !!stream, running: !!running },
                 sound: { open: !!sndStream, running: !!sndRunning,
                          pieces: sndPieces } } }); }
    catch (err) { /* a bridge that will not take it is not a failed capture */ }
  }

  /* One piece, start to finish. Resolves when the piece is on its way down. */
  function recordOne() {
    if (!running || !stream) return;
    /* #1207: false, always. The picture capture is opened with `audio: false`
     * and this Electron has no road that would put sound on it; the sound is
     * the second ring below. Kept as a variable rather than folded away so
     * the shape of this function still matches recordSound(). */
    var withAudio = false;
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
         * claimed by the piece it died in. #1207: on a picture piece that is
         * always false, and the ring reads coverage off the sound ring. */
        return desk().replayPush(buf, { at: at, ms: ms, a: !!withAudio,
          kind: 'v',
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

  /* THE PICTURE CAPTURE, AND ONLY THE PICTURE (#1182c, #1205, #1207).
   *
   * #1182c measured this and the measurement still stands: getDisplayMedia
   * requires TRANSIENT USER ACTIVATION - something pressed within the last
   * few seconds - and a recorder that starts itself after the first paint has
   * nothing to spend. Electron's request handler removes the picker; it does
   * not remove that rule. getUserMedia with the chromeMediaSource constraints
   * carries no such requirement, which is why the ring has been opened that
   * way.
   *
   * #1205 turned the order round in the belief that getDisplayMedia was the
   * only road that could carry the desk's sound. #1207 measured what actually
   * happened when it did: the handler answers `{ video: win, ... }`, this
   * Electron refuses a BrowserWindow as `video` outright, and EVERY capture
   * has fallen through to the legacy road below. That is not a fault to fix
   * here - the legacy road is the one producing the correct picture, window
   * frame, rail, menu bar and all - so the order is left exactly as it is and
   * the sound is taken by a second capture instead.
   *
   * What changed: this function no longer says anything about sound. It has
   * none and never had; the sound ring reports itself. A picture road that
   * wrote its own reasons into the sound's state is how "no loopback on this
   * platform" came to be printed on a Windows desk that had simply been
   * refused for a different reason entirely. */
  function openCapture(gesture) {
    var media = root.navigator && root.navigator.mediaDevices;
    if (!media) return Promise.reject(new Error('no media devices here'));
    var first = Promise.resolve(null);
    if (typeof media.getDisplayMedia === 'function') {
      try {
        first = media.getDisplayMedia({
          /* #1207: `audio: false`, and it is load-bearing. This capture has
           * never been given sound and cannot be - measured, twice. Saying so
           * is what lets main.js tell this request from the sound ring's by
           * what each one asked for, rather than guessing. */
          video: { width: { ideal: WIDTH }, height: { ideal: HEIGHT },
                   frameRate: { ideal: FPS, max: FPS } },
          audio: false
        }).then(function (got) { return { stream: got, road: 'display-media' }; },
          function (err) {
            note('display capture would not film the window ('
              + String((err && err.message) || err)
              + '), so the window is filmed the legacy way');
            return null;
          });
      } catch (err) {
        note('display capture refused the ask: ' + String((err && err.message) || err));
        first = Promise.resolve(null);
      }
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
        return media.getUserMedia({
          audio: false,
          video: { mandatory: { chromeMediaSource: 'desktop',
                                chromeMediaSourceId: source.id,
                                maxWidth: WIDTH, maxHeight: HEIGHT,
                                maxFrameRate: FPS } }
        }).then(function (opened) { return { stream: opened, road: 'window-only' }; });
      });
    });
  }

  /* #1205: WHY THE CAPTURE IS SAID TO HAVE SOUND, OR NOT.
   *
   * Asked of the stream rather than of the request: a handler that answered
   * without audio produces a perfectly good stream with no audio track on it
   * and no error anywhere. The only honest test is to count the tracks.
   *
   * #1207: it is the SOUND capture that is asked now. */
  function settleSound() {
    if (audioLive()) {
      sound = { present: true, state: 'capturing', supported: true,
        road: 'panel-frame',
        detail: 'the broadcast, captured from the panel' };
      return;
    }
    /* The capture resolved and has no audio track on it. That is this
     * machine's answer, not a missing gesture and not a stale reason from
     * some earlier attempt, so it is stated outright rather than deferring to
     * whatever `detail` happened to be holding. */
    sound = { present: false, state: 'unavailable', supported: false,
      road: 'panel-frame',
      detail: 'the sound capture came back with no audio track' };
  }

  /* #1207: THE SECOND CAPTURE. NO PICTURE IN IT, AND THAT IS THE POINT.
   *
   * `video: false` is what makes this work at all. Asking with `video: true`
   * and letting main.js answer with audio alone fails the whole request -
   * measured: the handler throws "Video was requested, but no video stream
   * was provided" and the page is given AbortError "Error starting capture".
   *
   * Nothing here names a device. main.js chooses the panel frame and the page
   * is given no say in it, for the same reason it is given no say in which
   * window is filmed: the wrong choice would put somebody else's sound into a
   * ring that gets exported. No microphone is opened on this road or any
   * other - `audio: true` on getDisplayMedia means "the thing being captured",
   * never an input device, and that is the whole of what is asked for here. */
  function openSound() {
    var media = root.navigator && root.navigator.mediaDevices;
    if (!media || typeof media.getDisplayMedia !== 'function') {
      return Promise.reject(new Error('this surface has no display capture, '
        + 'so it has no road to the broadcast'));
    }
    /* getDisplayMedia can throw where it stands rather than rejecting - no
     * transient activation is one way. A synchronous throw here would come up
     * through start(), and start() is what is filming the window: the sound
     * is never allowed to cost the picture, so it is turned into a rejection
     * before it can leave this function. */
    try {
      return media.getDisplayMedia({ video: false, audio: true });
    } catch (err) {
      return Promise.reject(err instanceof Error ? err : new Error(String(err)));
    }
  }

  /* One piece of sound, start to finish. The same shape as recordOne() on
   * purpose: the two recorders stamp their pieces the same way, at the same
   * point in the same kind of function, so whatever delay there is between
   * Date.now() and the encoder actually latching is the SAME delay in both
   * rings and cancels out of the shift the cut computes. */
  function recordSound() {
    if (!sndRunning || !sndStream) return;
    var live = audioLive();
    var type = pickSoundType();
    var options = { audioBitsPerSecond: AUDIO_BITS };
    if (type) options.mimeType = type;
    try {
      sndRec = new root.MediaRecorder(sndStream, options);
    } catch (err) {
      failures += 1;
      note('the sound recorder would not start: ' + String((err && err.message) || err));
      sndRunning = false;
      return;
    }
    sndParts = [];
    sndStartedAt = Date.now();
    sndRec.ondataavailable = function (ev) {
      if (ev && ev.data && ev.data.size) sndParts.push(ev.data);
    };
    sndRec.onerror = function (ev) {
      failures += 1;
      note('the sound recorder complained: '
        + String((ev && ev.error && ev.error.message) || 'no reason given'));
    };
    sndRec.onstop = function () {
      var at = sndStartedAt;
      var ms = Date.now() - at;
      var blob = null;
      try { blob = new root.Blob(sndParts, { type: type || 'audio/webm' }); }
      catch (err) { blob = null; }
      sndParts = [];
      if (sndRunning && !sndStopping) {
        try { recordSound(); }
        catch (err) { note('could not restart the sound: ' + err.message); }
      }
      if (!blob || !blob.size) return;
      blob.arrayBuffer().then(function (buf) {
        if (!has('replayPush')) return;
        sndPieces += 1;
        return desk().replayPush(buf, { at: at, ms: ms, a: !!live, kind: 'a' });
      }).then(null, function (err) {
        failures += 1;
        note('a piece of sound did not reach the ring: '
          + String((err && err.message) || err));
      });
    };
    try {
      sndRec.start();
    } catch (err) {
      failures += 1;
      note('the sound recorder refused to run: ' + String((err && err.message) || err));
      sndRunning = false;
      return;
    }
    root.setTimeout(function () {
      try { if (sndRec && sndRec.state === 'recording') sndRec.stop(); }
      catch (err) { /* onstop will not come; the next tick starts a new one */ }
    }, SEG_MS);
  }

  /* Open the sound ring and keep it. Returns a promise that never rejects:
   * a desk that cannot capture the broadcast must still film the window, and
   * every road out of here leaves `sound` saying plainly which it was. */
  /* #1207: ASK THE RING WHETHER IT CAN KEEP THE TWO APART, BEFORE CAPTURING.
   *
   * This file is re-evaluated whenever the share changes; main.js and
   * screen-ring.cjs are only reloaded when Pine Box is restarted. So a new
   * renderer against an old main process is the normal state of affairs for
   * minutes at a time, and it is the one pairing that does real damage: an
   * older ring has never heard of `kind`, files every piece of sound in with
   * the picture, and a cut then concatenates opus pieces with video ones and
   * is refused outright. Measured on the live desk while this was written.
   *
   * `rings` is the handshake. An older build does not answer it, and gets no
   * second capture - the window is filmed silently, exactly as before, and
   * the reason says what to do about it. */
  function ringKeepsSound() {
    if (!has('replayBegin')) return Promise.resolve(false);
    try {
      return Promise.resolve(desk().replayBegin({
        audio: { source: 'desk-broadcast-frame', present: false,
          state: sound.state, detail: sound.detail, supported: sound.supported },
        streams: { picture: { open: !!stream, running: !!running },
                   sound: { open: false, running: false, pieces: sndPieces } }
      })).then(function (got) {
        return !!(got && Number(got.rings) >= 2);
      }, function () { return false; });
    } catch (err) { return Promise.resolve(false); }
  }

  function startSound() {
    if (sndRunning) return Promise.resolve(true);
    if (sndOpening) return sndOpening;
    if (!root.MediaRecorder) return Promise.resolve(false);
    sndOpening = ringKeepsSound().then(function (keeps) {
      if (!keeps) {
        sound = { present: false, state: 'unavailable', supported: sound.supported,
          road: 'panel-frame',
          detail: 'this Pine Box is still running an older recorder in its main '
            + 'process, which would file the broadcast in with the picture and '
            + 'spoil the cut; restart Pine Box and the sound comes with it' };
        note(sound.detail);
        tellSound();
        /* Rejected rather than resolved false, so the branch below that
         * tears a half-open capture down is not run against a capture that
         * was never opened. `quiet` tells the rejection handler that the
         * reason has already been set and said, and must not be overwritten
         * with the generic one. */
        var stop = new Error('the ring in this build keeps one lane only');
        stop.quiet = true;
        throw stop;
      }
      return openSound();
    }).then(function (got) {
      sndStream = got;
      sndRunning = true;
      sndStopping = false;
      settleSound();
      if (!sound.present) {
        /* A capture with no track on it is not a capture. Let it go rather
         * than leaving a dead recorder running for the rest of the evening. */
        try { got.getTracks().forEach(function (t) { t.stop(); }); } catch (err) {}
        sndStream = null;
        sndRunning = false;
        /* Said out loud, because this is the shape the export sheet reads and
         * the diagnostic writes: a capture that opened and carried nothing is
         * a different fault from one that was refused, and the two have to be
         * told apart from outside the app. */
        tellSound();
        note(sound.detail);
        return false;
      }
      try {
        var track = sndStream.getAudioTracks()[0];
        if (track) {
          track.addEventListener('ended', function () {
            note('the broadcast capture ended');
            stopSound('the capture ended');
          });
        }
      } catch (err) { /* not fatal */ }
      tellSound();
      recordSound();
      note('recording the broadcast from the panel');
      return true;
    }, function (err) {
      /* The handshake above has already set a better reason and said it out
       * loud; the generic one would bury it. */
      if (err && err.quiet) return false;
      sound = { present: false, state: 'unavailable', supported: sound.supported,
        road: 'panel-frame',
        detail: 'the panel would not give up its sound: '
          + String((err && err.message) || err) };
      tellSound();
      note(sound.detail);
      return false;
    });
    /* Cleared whichever way it went, so a later gesture can try again. */
    sndOpening = sndOpening.then(function (got) {
      sndOpening = null;
      return got;
    }, function () {
      sndOpening = null;
      return false;
    });
    return sndOpening;
  }

  /* The sound ring stops on its own, and the picture carries on without it.
   * The ring keeps whatever sound it already has; the cut will report the
   * coverage it really found and the recording stays a recording. */
  function stopSound(why) {
    sndStopping = true;
    sndRunning = false;
    try { if (sndRec && sndRec.state === 'recording') sndRec.stop(); } catch (err) {}
    try {
      if (sndStream) {
        var tracks = sndStream.getTracks();
        for (var i = 0; i < tracks.length; i += 1) { try { tracks[i].stop(); } catch (e) {} }
      }
    } catch (err) {}
    sndStream = null;
    sndRec = null;
    if (sound.present) {
      sound = { present: false, state: 'unavailable', supported: sound.supported,
        road: 'panel-frame', detail: String(why || 'the sound capture stopped') };
      tellSound();
    }
    if (running) watchForGesture();
  }

  /* #1207: the sound ring can be opened on its own, and is - main.js spends
   * a second user activation on it so that neither capture has to share one
   * gesture with the other. Safe to call twice: startSound() returns early
   * when it is already running. */
  function startTheSound(opts) {
    if (!has('replayPush')) return Promise.resolve({ ok: false, audio: sound });
    try {
      return startSound().then(function (got) {
        if (!got && running) watchForGesture();
        return { ok: !!got, audio: sound };
      }, function () { return { ok: false, audio: sound }; });
    } catch (err) {
      note('the sound could not be started: ' + String((err && err.message) || err));
      return Promise.resolve({ ok: false, audio: sound });
    }
  }

  function start(opts) {
    if (running) {
      /* The picture is already up; the sound may still be missing, and this
       * is the one road that gets a fresh gesture from main.js. */
      try { startTheSound(opts); } catch (err) { /* said by startTheSound */ }
      return Promise.resolve({ ok: true, already: true, audio: sound });
    }
    if (!root.MediaRecorder) {
      note('this surface has no MediaRecorder');
      return Promise.resolve({ ok: false, detail: 'no MediaRecorder here' });
    }
    var gesture = !!(opts && opts.gesture);
    return openCapture(gesture).then(function (opened) {
      stream = opened.stream;
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
      /* The sound is declared before the first piece lands, so the export
       * sheet can say what the recording carries even if nobody has cut
       * anything yet. */
      tellSound();
      if (typeof desk().onReplayFlush === 'function') {
        try { desk().onReplayFlush(flush); } catch (err) { /* not fatal */ }
      }
      recordOne();
      note('recording this window');
      /* #1207: THE PICTURE IS UP BEFORE THE SOUND IS ASKED FOR, AND THE
       * SOUND IS NEVER ALLOWED TO COST IT. Everything below this line is
       * already recording; a throw from the sound road reaching here would
       * turn a running capture into a rejected start() and lose the window. */
      try { startTheSound(opts); } catch (err) { /* said by startTheSound */ }
      return { ok: true, audio: sound };
    }, function (err) {
      note('the window would not be captured: ' + String((err && err.message) || err));
      return { ok: false, detail: String((err && err.message) || err) };
    });
  }

  /* #1205, rebuilt for #1207: THE FIRST GESTURE RETRIES THE SOUND RING.
   *
   * It used to reopen the WINDOW capture to try to grow an audio track on it,
   * and swap the recorder onto the new one mid-flight. None of that is needed
   * now and all of it was risk to the picture: the sound is a separate
   * capture, so a retry opens that capture and nothing else. The window is
   * opened once at startup and is never touched again.
   *
   * Three tries, ten seconds apart, so a desk where the panel simply has no
   * sound to give does not reopen a capture on every click all evening. A
   * press inside the panel webview is a different document and never reaches
   * this listener; that is why main.js supplies the activation up front and
   * this is only the backstop. */
  var watching = false;
  function watchForGesture() {
    if (watching || !doc || !doc.addEventListener) return;
    if (sndRunning) return;
    watching = true;
    var kinds = ['pointerdown', 'keydown'];
    var take = function () {
      if (sndRunning || !running) return unwatch();
      if (upgrades >= 3) return unwatch();
      var now = Date.now();
      if (now - lastUpgrade < 10000) return;
      lastUpgrade = now;
      upgrades += 1;
      /* Opened INSIDE the event, so the activation is still transient. */
      startSound().then(function (got) {
        if (got) {
          note('the broadcast was added to the recording');
          return unwatch();
        }
        if (upgrades >= 3) unwatch();
      }, function () { /* startSound() never rejects */ });
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

  function stop() {
    stopping = true;
    running = false;
    /* #1207: the sound goes with it. A sound ring left running under a
     * stopped picture would hold a capture open on the panel - and keep
     * enableLocalEcho's promise alive - for no recording at all. */
    stopSound('the page stopped it');
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
             /* #1207: both rings, named, because "is it recording" now has
              * two answers and a person reading this has to see which one
              * went wrong. */
             streams: { picture: { open: !!stream, running: !!running },
                        sound: { open: !!sndStream, running: !!sndRunning,
                                 pieces: sndPieces } },
             audio: { present: !!sound.present, state: sound.state,
                      detail: sound.detail, supported: sound.supported,
                      road: sound.road, live: audioLive(), upgrades: upgrades,
                      running: !!sndRunning, pieces: sndPieces } };
  }

  /* #1182d: CLOSE THE PIECE YOU ARE ON.
   *
   * Asked for by the main process just before it cuts. Stopping the recorder
   * emits the piece straight away and onstop starts the next one, so the
   * ring loses nothing and gains the seconds that were still in flight - and
   * those are the seconds the operator actually wanted, because a rolling
   * recorder is asked for the thing that just happened. */
  function flush() {
    var closed = false;
    /* #1207: BOTH rings are closed, and the sound first. The cut asks for
     * this just before it runs, and a sound ring still holding the last two
     * seconds while the picture has already handed them down would make the
     * newest stretch of the cut silent - the exact stretch the operator
     * reached for. */
    try {
      if (sndRec && sndRec.state === 'recording') { sndRec.stop(); closed = true; }
    } catch (err) { /* the timer will close it soon enough */ }
    try {
      if (rec && rec.state === 'recording') { rec.stop(); closed = true; }
    } catch (err) { /* likewise */ }
    return closed;
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
                          /* #1207: main.js spends a second user activation on
                           * this one, so the two captures never have to share
                           * a gesture. */
                          startSound: startTheSound,
                          sound: function () { return state().audio; },
                          SEG_MS: SEG_MS, WIDTH: WIDTH, HEIGHT: HEIGHT, FPS: FPS };
})(typeof window !== 'undefined' ? window : globalThis);
