/* Native window replay. Each two-second MediaRecorder run is a complete WebM
 * file (or a supported self-contained MP4), so any retained part of the rolling cache remains independently usable.
 * Picture requests native physical pixels at 60 fps. Sound taps application
 * frames (shell, broadcast panel and loaded app guests), preserving local playback and excluding
 * unrelated desktop audio. The main process owns the bounded disk cache.
 *
 * All segment state belongs to its recorder. Stop-request timestamps share an
 * epoch-anchored monotonic clock; delayed callbacks and wall-clock adjustments
 * cannot change durations or shift audio against picture. flush() acknowledges
 * both lanes and preceding writes only after their replayPush disk promises.
 */
(function (root) {
  'use strict';
  var SEG_MS = 2000;
  var FPS = 60;
  var AUDIO_BITS = 192000;
  var doc = root.document || null;
  var stream = null, sndStream = null;
  var videoPiece = null, audioPiece = null;
  var running = false, sndRunning = false, enabled = false;
  var opening = null, sndOpening = null, replacing = null;
  var openingLifecycle = 0, sndOpeningLifecycle = 0;
  var pendingSoundInputs = [], pendingSoundContext = null, pendingSoundDestination = null;
  var explicitlyStopped = false;
  var lifecycle = 0, failures = 0, said = '', sndPieces = 0;
  var watchdog = null, resizeTimer = null, observer = null;
  var nextPictureRetry = 0, nextSoundRetry = 0;
  var pictureFailures = 0, soundFailures = 0;
  var pending = new Set();
  var blockedTypes = new Set();
  var lastVideoEncoding = null;
  var soundInputs = [], soundContext = null, soundNodes = [];
  var soundExpected = 1, soundTargets = [], audioCatalogDirty = false, audioCatalogRevision = 0;
  var nativeRequested = null;
  var sound = { present: false, state: 'unknown', detail: 'not started yet',
    supported: null, road: '' };
  var perf = root.performance;
  var epoch = Date.now() - (perf && typeof perf.now === 'function' ? perf.now() : 0);
  var lastNow = epoch;

  function now() {
    var value = perf && typeof perf.now === 'function' ? epoch + perf.now() : Date.now();
    lastNow = Math.max(lastNow, value);
    return lastNow;
  }
  function desk() { return root.pineDesktop || null; }
  function has(name) { var d = desk(); return !!(d && typeof d[name] === 'function'); }
  function note(what) {
    said = String(what || '');
    try { if (root.console && root.console.log) root.console.log('[screen ring] ' + said); } catch (err) {}
  }
  function tracks(capture, kind) {
    try { return (capture && capture[kind === 'a' ? 'getAudioTracks' : 'getVideoTracks']()) || []; }
    catch (err) { return []; }
  }
  function live(capture, kind) {
    return tracks(capture, kind).some(function (track) { return track.readyState === 'live' && !track.muted; });
  }
  function stopTracks(capture) {
    try { capture.getTracks().forEach(function (track) { try { track.stop(); } catch (err) {} }); } catch (err) {}
  }
  function audioLive() {
    return live(sndStream, 'a') && soundInputs.some(function (input) { return live(input, 'a'); }) &&
      (!soundContext || soundContext.state === 'running');
  }
  function audioComplete() {
    return has('replayAudioSources') && has('replayAudioTarget') && !audioCatalogDirty && soundExpected >= 1 &&
      soundTargets.length === soundExpected && soundInputs.length === soundExpected && audioLive() &&
      soundInputs.every(function (input) { return live(input, 'a'); });
  }
  function audioSettings() {
    return soundInputs.map(function (input) {
      var track = tracks(input, 'a')[0], value = {};
      try { value = track && track.getSettings ? track.getSettings() : {}; } catch (err) {}
      var clean = {};
      ['channelCount', 'sampleRate', 'sampleSize', 'autoGainControl', 'echoCancellation', 'noiseSuppression', 'latency', 'voiceIsolation'].forEach(function (key) {
        if (value[key] != null) clean[key] = value[key];
      });
      return clean;
    });
  }
  function view() { return doc && doc.body && doc.body.classList.contains('pine-pip') ? 'pip' : 'app'; }
  function nativeSize(source) {
    var ratio = Number(root.devicePixelRatio) > 0 ? Number(root.devicePixelRatio) : 1;
    return {
      w: Math.max(2, Math.round(Number(source && source.width) || (Number(root.outerWidth || root.innerWidth) || 1280) * ratio)),
      h: Math.max(2, Math.round(Number(source && source.height) || (Number(root.outerHeight || root.innerHeight) || 800) * ratio))
    };
  }
  function settings(capture) {
    var size = {};
    try { var track = tracks(capture, 'v')[0]; size = track && track.getSettings ? track.getSettings() : {}; } catch (err) {}
    var fallback = nativeRequested || nativeSize();
    return { w: Math.round(size.width || fallback.w), h: Math.round(size.height || fallback.h),
      fps: Number(size.frameRate) > 0 ? Number(size.frameRate) : FPS };
  }
  function bitrate(size) {
    // Scale encoder budget with native pixels, rather than compressing 60 fps
    // desktop text into the former 1.6 Mbps / 12 fps budget.
    return Math.round(Math.max(4000000, Math.min(40000000, size.w * size.h * FPS * 0.12)));
  }
  function firstSupported(want) {
    for (var i = 0; i < want.length; i += 1) {
      try { if (!blockedTypes.has(want[i]) && root.MediaRecorder && root.MediaRecorder.isTypeSupported(want[i])) return want[i]; } catch (err) {}
    }
    return '';
  }
  function tellSound() {
    if (!has('replayBegin')) return;
    try {
      Promise.resolve(desk().replayBegin({ audio: { source: sound.road || 'desk-application-frames',
        present: !!sound.present, state: sound.state, detail: sound.detail,
        supported: sound.supported, road: sound.road, complete: audioComplete(), source_settings: audioSettings(), targets: soundTargets.slice() },
        streams: { picture: { open: !!stream, running: running, fps: FPS,
          native: stream ? settings(stream) : null },
          sound: { open: !!sndStream, running: sndRunning, pieces: sndPieces } }
      })).catch(function () {});
    } catch (err) {}
  }
  function retry(kind) {
    var count = kind === 'a' ? ++soundFailures : ++pictureFailures;
    var at = now() + Math.min(30000, 1000 * Math.pow(2, Math.min(5, count - 1)));
    if (kind === 'a') nextSoundRetry = at; else nextPictureRetry = at;
  }
  function finish(piece, ok) {
    if (piece.done) return;
    piece.done = true;
    if (piece.cleanup) { piece.cleanup(); piece.cleanup = null; }
    if (piece.timer != null) root.clearTimeout(piece.timer);
    if (piece.guard != null) root.clearTimeout(piece.guard);
    pending.delete(piece);
    piece.resolve(!!ok);
  }
  function failLane(kind, why) {
    failures += 1;
    note(why);
    if (kind === 'a') {
      closeSound(why);
    } else {
      running = false;
      var old = stream; stream = null;
      requestStop(videoPiece);
      stopTracks(old);
    }
    retry(kind);
    tellSound();
  }
  function requestStop(piece) {
    if (!piece || piece.done) return;
    var isCurrent = piece === (piece.kind === 'a' ? audioPiece : videoPiece);
    var successor = piece.stopAt == null && isCurrent && enabled && piece.token === lifecycle &&
      piece.capture === (piece.kind === 'a' ? sndStream : stream) && (piece.kind === 'a' ? sndRunning : running);
    if (piece.stopAt == null) {
      piece.stopAt = now();
      piece.endView = view();
    }
    if (piece.timer != null) { root.clearTimeout(piece.timer); piece.timer = null; }
    // Retire the lane before stop: stop/data callbacks can run synchronously in
    // a stand-in and arrive much later in Chromium. The successor uses the
    // still-live stream immediately, without waiting for old encoder teardown.
    if (isCurrent) { if (piece.kind === 'a') audioPiece = null; else videoPiece = null; }
    if (successor) piece.successorRequested = true;
    if (piece.recorder.state !== 'inactive') {
      try { piece.recorder.stop(); }
      catch (err) {
        finish(piece, false);
        if (piece.capture === (piece.kind === 'a' ? sndStream : stream))
          failLane(piece.kind, 'the recorder could not stop: ' + err.message);
        return;
      }
    }
    if (successor) record(piece.kind);
    if (!piece.done && !piece.stopped && piece.guard == null) {
      piece.guard = root.setTimeout(function () {
        if (piece.done) return;
        finish(piece, false);
        if (piece.capture === (piece.kind === 'a' ? sndStream : stream) &&
            !(piece.kind === 'a' ? audioPiece : videoPiece))
          failLane(piece.kind, 'the recorder stopped answering; capture will retry');
        else note('a retired recorder stopped answering; its incomplete segment was dropped');
      }, 4000);
    }
  }
  function record(kind) {
    var capture = kind === 'a' ? sndStream : stream;
    if (!(kind === 'a' ? sndRunning : running) || !capture) return;
    var type = firstSupported(kind === 'a'
      ? ['audio/webm;codecs=opus', 'audio/webm']
      : ['video/webm;codecs=h264', 'video/mp4;codecs=avc1.42E01E',
         'video/webm;codecs=vp8', 'video/webm;codecs=vp9', 'video/webm']);
    var geometry = kind === 'a' ? null : settings(capture);
    var options = kind === 'a' ? { audioBitsPerSecond: AUDIO_BITS } : { videoBitsPerSecond: bitrate(geometry) };
    if (type) options.mimeType = type;
    var recorder;
    try { recorder = new root.MediaRecorder(capture, options); }
    catch (err) {
      if (kind === 'v' && type) { blockedTypes.add(type); note('capture codec refused; falling back: ' + type); record(kind); }
      else failLane(kind, 'the recorder would not start: ' + err.message);
      return;
    }
    var piece = { kind: kind, recorder: recorder, capture: capture, parts: [],
      at: now(), stopAt: null, view: view(), geometry: geometry, audio: kind === 'a' && audioLive(), audioComplete: kind === 'a' && audioComplete(), audioSettings: kind === 'a' ? audioSettings() : null, sourceTargets: kind === 'a' ? soundTargets.slice() : null,
      token: lifecycle, timer: null, guard: null, done: false, stopped: false, failed: false, successorRequested: false, cleanup: null };
    piece.promise = new Promise(function (resolve) { piece.resolve = resolve; });
    pending.add(piece);
    if (kind === 'a') audioPiece = piece; else videoPiece = piece;
    recorder.ondataavailable = function (ev) {
      if (!piece.done && ev && ev.data && ev.data.size) piece.parts.push(ev.data);
    };
    recorder.onerror = function (ev) {
      if (piece.done) return;
      piece.failed = true;
      if (piece.token === lifecycle && capture === (kind === 'a' ? sndStream : stream)) {
        if (kind === 'v' && type) blockedTypes.add(type);
        failLane(kind, 'the recorder complained: ' + String((ev && ev.error && ev.error.message) || 'no reason given'));
      }
      requestStop(piece);
    };
    recorder.onstop = function () {
      if (piece.done || piece.stopped) return;
      piece.stopped = true;
      if (piece.stopAt == null) { piece.stopAt = now(); piece.endView = view(); }
      if (piece.timer != null) { root.clearTimeout(piece.timer); piece.timer = null; }
      if (piece.guard != null) { root.clearTimeout(piece.guard); piece.guard = null; }
      if (kind === 'a' && audioPiece === piece) audioPiece = null;
      if (kind === 'v' && videoPiece === piece) videoPiece = null;
      if (piece.cleanup) { piece.cleanup(); piece.cleanup = null; }
      // Requested stops already started their successor synchronously. Restart
      // here only for an unsolicited stop, before serialization or IPC.
      if (!piece.successorRequested && enabled && piece.token === lifecycle && capture === (kind === 'a' ? sndStream : stream)
          && (kind === 'a' ? sndRunning : running)) record(kind);
      if (piece.failed) { finish(piece, false); return; }
      var blob;
      try { blob = new root.Blob(piece.parts, { type: type || (kind === 'a' ? 'audio/webm' : 'video/webm') }); }
      catch (err) { finish(piece, false); return; }
      piece.parts = [];
      if (!blob.size) { finish(piece, false); return; }
      var metadata = { at: piece.at, ms: Math.max(1, piece.stopAt - piece.at), a: piece.audio, kind: kind,
        mime: recorder.mimeType || type || (kind === 'a' ? 'audio/webm' : 'video/webm') };
      if (kind === 'a') { metadata.audio_complete = piece.audioComplete; metadata.source_settings = piece.audioSettings; metadata.source_targets = piece.sourceTargets; }
      if (geometry) {
        metadata.view = piece.endView === piece.view ? piece.view : 'transition';
        metadata.w = geometry.w; metadata.h = geometry.h;
        metadata.fps = geometry.fps; metadata.requested_fps = FPS;
        metadata.bitrate = Number(recorder.videoBitsPerSecond) || options.videoBitsPerSecond;
        metadata.requested_bitrate = options.videoBitsPerSecond;
      }
      blob.arrayBuffer().then(function (buffer) {
        if (!has('replayPush')) throw new Error('the replay bridge is unavailable');
        return desk().replayPush(buffer, metadata);
      }).then(function (result) {
        var accepted = result !== false && !(result && result.ok === false);
        if (!accepted) throw new Error((result && result.detail) || 'the ring refused the piece');
        if (kind === 'a') sndPieces += 1;
        finish(piece, true);
      }).catch(function (err) {
        failures += 1;
        note('a piece did not reach the ring: ' + String((err && err.message) || err));
        finish(piece, false);
      });
    };
    try {
      // Refresh immediately before start; constructor/setup time is not media.
      piece.at = now();
      recorder.start();
      if (kind === 'v') lastVideoEncoding = { mime: recorder.mimeType || type || 'video/webm',
        fps: geometry.fps, requested_fps: FPS, bitrate: Number(recorder.videoBitsPerSecond) || options.videoBitsPerSecond,
        requested_bitrate: options.videoBitsPerSecond };
      piece.timer = root.setTimeout(function () { requestStop(piece); }, SEG_MS);
    } catch (err) {
      if (kind === 'a' && audioPiece === piece) audioPiece = null;
      if (kind === 'v' && videoPiece === piece) videoPiece = null;
      finish(piece, false);
      if (kind === 'v' && type) { blockedTypes.add(type); note('capture codec could not run; falling back: ' + type); record(kind); }
      else failLane(kind, 'the recorder refused to run: ' + err.message);
    }
  }
  function openCapture() {
    var media = root.navigator && root.navigator.mediaDevices;
    if (!media) return Promise.reject(new Error('no media devices here'));
    // This Electron supports window DesktopCapturerSource via getUserMedia.
    // Native min/max dimensions prevent a resize from retaining an old scale.
    if (has('replaySource') && typeof media.getUserMedia === 'function') {
      return Promise.resolve(desk().replaySource()).then(function (source) {
        if (!source || !source.ok || !source.id) throw new Error((source && source.detail) || 'no source to record');
        var size = nativeSize(source);
        return media.getUserMedia({ audio: false, video: { mandatory: {
          chromeMediaSource: 'desktop', chromeMediaSourceId: source.id,
          minWidth: size.w, maxWidth: size.w, minHeight: size.h, maxHeight: size.h,
          minFrameRate: FPS, maxFrameRate: FPS
        } } }).then(function (got) { return { stream: got, size: size }; });
      });
    }
    if (typeof media.getDisplayMedia !== 'function') return Promise.reject(new Error('this surface has no capture road'));
    var size = nativeSize();
    return media.getDisplayMedia({ audio: false, video: { width: { ideal: size.w },
      height: { ideal: size.h }, frameRate: { ideal: FPS, max: FPS } }
    }).then(function (got) { return { stream: got, size: size }; });
  }
  function watchPicture(capture) {
    var track = tracks(capture, 'v')[0];
    if (!track) return;
    try { track.contentHint = 'detail'; } catch (err) {}
    track.addEventListener('ended', function () {
      if (enabled && stream === capture) failLane('v', 'the window capture ended; capture will retry');
    });
  }
  function startPicture() {
    if (running) return Promise.resolve(true);
    if (opening) return openingLifecycle === lifecycle ? opening
      : opening.then(function () { return enabled ? startPicture() : false; });
    var token = lifecycle; openingLifecycle = token;
    opening = openCapture().then(function (got) {
      if (!enabled || token !== lifecycle) { stopTracks(got.stream); return false; }
      if (!live(got.stream, 'v')) { stopTracks(got.stream); throw new Error('the window capture has no live picture'); }
      stream = got.stream; nativeRequested = got.size; running = true;
      pictureFailures = 0; nextPictureRetry = 0;
      watchPicture(stream); record('v'); tellSound();
      note('recording this window at native pixels, requesting ' + FPS + ' fps');
      return running;
    }).catch(function (err) {
      if (enabled && token === lifecycle) { failures += 1; retry('v'); note('the window would not be captured: ' + err.message); }
      return false;
    }).then(function (result) { opening = null; return result; });
    return opening;
  }
  function replacePicture() {
    if (!enabled || !running) return startPicture();
    if (replacing) return replacing;
    var token = lifecycle;
    replacing = openCapture().then(function (got) {
      if (!enabled || token !== lifecycle || !running) { stopTracks(got.stream); return false; }
      if (!live(got.stream, 'v')) { stopTracks(got.stream); throw new Error('replacement capture has no picture'); }
      var old = stream, piece = videoPiece;
      // Negotiate replacement while the existing capture remains live. Audio
      // keeps its capture and clock through resize/PiP changes.
      stream = got.stream; nativeRequested = got.size;
      watchPicture(stream);
      if (piece) { piece.cleanup = function () { stopTracks(old); }; requestStop(piece); }
      else stopTracks(old);
      record('v'); tellSound();
      return true;
    }).catch(function (err) { note('native resize capture will retry: ' + err.message); retry('v'); return false; })
      .then(function (result) { replacing = null; return result; });
    return replacing;
  }
  function openSoundTap(target) {
    var media = root.navigator && root.navigator.mediaDevices;
    if (!media || typeof media.getDisplayMedia !== 'function') return Promise.reject(new Error('no frame audio capture available'));
    var selected = has('replayAudioTarget') ? Promise.resolve(desk().replayAudioTarget(target)) : Promise.resolve({ ok: true });
    return selected.then(function (result) {
      if (result === false || (result && result.ok === false)) throw new Error((result && result.detail) || 'audio frame selection refused');
      // video:false is required: main deliberately supplies only frame audio.
      return media.getDisplayMedia({ video: false, audio: {
        autoGainControl: false, echoCancellation: false, noiseSuppression: false,
        channelCount: { ideal: 2 }, sampleRate: { ideal: 48000 }
      } });
    });
  }
  function closeSound(why) {
    sndRunning = false;
    requestStop(audioPiece);
    var old = sndStream, inputs = soundInputs, oldContext = soundContext;
    sndStream = null; soundInputs = []; soundContext = null; soundTargets = [];
    var waitingInputs = pendingSoundInputs, waitingContext = pendingSoundContext, waitingDestination = pendingSoundDestination;
    pendingSoundInputs = []; pendingSoundContext = null; pendingSoundDestination = null;
    inputs.forEach(stopTracks);
    if (waitingInputs !== inputs) waitingInputs.forEach(stopTracks);
    stopTracks(old);
    if (waitingDestination !== old) stopTracks(waitingDestination);
    soundNodes.forEach(function (node) { try { node.disconnect(); } catch (err) {} }); soundNodes = [];
    [oldContext, waitingContext === oldContext ? null : waitingContext].forEach(function (context) {
      if (context) { try { Promise.resolve(context.close()).catch(function () {}); } catch (err) {} }
    });
    sound = { present: false, state: 'unavailable', supported: sound.supported,
      road: has('replayAudioTarget') ? 'desk-application-frames' : 'panel-frame', detail: String(why || 'the audio capture stopped') };
    tellSound();
  }
  function audioSourcesChanged() {
    if (!enabled) return;
    audioCatalogRevision += 1; audioCatalogDirty = true;
    // Retire the complete segment exactly at the catalog change. Its successor
    // retains available audio but reports incomplete coverage until the new
    // frame set is captured, rather than claiming a newly audible guest.
    requestStop(audioPiece);
    if (sndRunning) {
      sound.state = 'partial';
      sound.detail = 'application audio sources changed; refreshing the captured frame mix';
    }
    tellSound(); startSound();
  }
  function discoverSoundTargets() {
    if (!has('replayAudioSources')) return Promise.resolve(has('replayAudioTarget') ? ['shell', 'panel'] : ['panel']);
    return Promise.resolve(desk().replayAudioSources()).then(function (got) {
      if (!got || got.ok === false || !Array.isArray(got.targets)) throw new Error('application audio source catalog is unavailable');
      var targets = Array.from(new Set(got.targets));
      if (targets.length < 1 || targets.indexOf('shell') < 0 || targets.some(function (target) {
        return typeof target !== 'string' || !/^(shell|panel|guest:\d+)$/.test(target);
      })) throw new Error('application audio source catalog contains an invalid frame');
      return targets;
    });
  }
  function disposeAudio(bundle) {
    bundle.inputs.forEach(stopTracks); stopTracks(bundle.capture);
    bundle.nodes.forEach(function (node) { try { node.disconnect(); } catch (err) {} });
    if (bundle.context) { try { Promise.resolve(bundle.context.close()).catch(function () {}); } catch (err) {} }
  }
  function startSound() {
    if (!enabled) return Promise.resolve(false);
    if (sndOpening) {
      if (sndOpeningLifecycle !== lifecycle) return sndOpening.then(function () { return enabled ? startSound() : false; });
      // A resume begun without activation can wait indefinitely. A later call
      // with main's fresh activation must resume that same pending graph.
      if (pendingSoundContext) { try { Promise.resolve(pendingSoundContext.resume()).catch(function () {}); } catch (err) {} }
      return sndOpening;
    }
    if (sndRunning && audioLive() && !audioCatalogDirty) return Promise.resolve(true);
    if (!root.MediaRecorder || !has('replayBegin')) return Promise.resolve(false);
    var token = lifecycle, revision = audioCatalogRevision;
    var captures = [], context = null, destinationCapture = null, targets = [];
    sndOpeningLifecycle = token; pendingSoundInputs = captures;
    sndOpening = Promise.resolve(desk().replayBegin({ audio: { source: 'desk-application-frames',
      present: audioLive(), complete: audioComplete(), state: sound.state, detail: sound.detail,
      supported: sound.supported, targets: soundTargets.slice()
    } })).then(function (ring) {
      if (!ring || Number(ring.rings) < 2) throw new Error('restart Pine Box to enable the separate audio cache');
      return discoverSoundTargets();
    }).then(function (found) {
      targets = found;
      // Serialized selection/capture prevents one frame request consuming the
      // other frame's selector. Captures are never attached to speaker output.
      return targets.reduce(function (chain, target) {
        return chain.then(function () {
          if (!enabled || token !== lifecycle) throw new Error('capture start was cancelled');
          return openSoundTap(target);
        }).then(function (got) {
          captures.push(got);
          if (!live(got, 'a')) throw new Error(target + ' audio capture has no live track');
          if (!enabled || token !== lifecycle) throw new Error('capture start was cancelled');
        });
      }, Promise.resolve());
    }).then(function () {
      if (!enabled || token !== lifecycle) throw new Error('capture start was cancelled');
      if (captures.length > 1) {
        var Ctor = root.AudioContext || root.webkitAudioContext;
        if (!Ctor) throw new Error('the application audio mixer is unavailable');
        context = new Ctor({ sampleRate: 48000, latencyHint: 'interactive' });
        pendingSoundContext = context;
        var destination = context.createMediaStreamDestination();
        destinationCapture = destination.stream; pendingSoundDestination = destinationCapture;
        var nodes = captures.map(function (capture) {
          var source = context.createMediaStreamSource(capture); source.connect(destination); return source;
        });
        return Promise.resolve(context.resume()).then(function () {
          if (context.state !== 'running') throw new Error('the application audio mixer is suspended');
          return { capture: destination.stream, context: context, nodes: nodes };
        });
      }
      return { capture: captures[0], context: null, nodes: [] };
    }).then(function (mixed) {
      if (!enabled || token !== lifecycle) { stopTracks(mixed.capture); throw new Error('capture start was cancelled'); }
      if (revision !== audioCatalogRevision || !captures.every(function (capture) { return live(capture, 'a'); }))
        throw new Error('application audio sources changed during capture negotiation');
      var old = { capture: sndStream, inputs: soundInputs, context: soundContext, nodes: soundNodes };
      var oldPiece = audioPiece;
      // Open the complete replacement first, then switch recorders at the same
      // monotonic instant. Existing source audio remains available throughout.
      sndStream = mixed.capture; soundInputs = captures; soundContext = mixed.context; soundNodes = mixed.nodes;
      soundTargets = targets.slice(); soundExpected = targets.length; audioCatalogDirty = false;
      sndRunning = true; soundFailures = 0; nextSoundRetry = 0;
      sound = { present: true, state: has('replayAudioSources') ? 'capturing' : 'partial', supported: true,
        road: has('replayAudioSources') || captures.length > 1 ? 'desk-application-frames' : 'panel-frame',
        detail: has('replayAudioSources') ? 'application audio, captured from ' + targets.length + ' application frame' + (targets.length === 1 ? '' : 's')
          : captures.length > 1 ? 'shell and broadcast panel audio only; restart Pine Box to include other application frames'
          : 'broadcast panel audio only; restart Pine Box to include shell music, sampler and effects' };
      captures.forEach(function (capture) {
        tracks(capture, 'a').forEach(function (track) {
          track.addEventListener('ended', function () {
            if (!enabled || soundInputs.indexOf(capture) < 0) return;
            if (has('replayAudioSources')) audioSourcesChanged();
            else failLane('a', 'an application audio capture ended; capture will retry');
          });
        });
      });
      if (soundContext && soundContext.addEventListener) soundContext.addEventListener('statechange', function () {
        if (enabled && soundContext === mixed.context && mixed.context.state !== 'running')
          failLane('a', 'the application audio mixer stopped; capture will retry');
      });
      if (oldPiece) { oldPiece.cleanup = function () { disposeAudio(old); }; requestStop(oldPiece); }
      else disposeAudio(old);
      record('a'); tellSound(); note(sound.detail);
      return sndRunning;
    }).catch(function (err) {
      captures.forEach(stopTracks); stopTracks(destinationCapture);
      if (context) { try { Promise.resolve(context.close()).catch(function () {}); } catch (ignored) {} }
      if (enabled && token === lifecycle) {
        if (sndRunning && audioLive()) {
          audioCatalogDirty = true;
          sound = { present: true, state: 'partial', supported: true, road: 'desk-application-frames',
            detail: 'available application audio retained; complete frame capture will retry: ' + String((err && err.message) || err) };
        } else sound = { present: false, state: 'unavailable', supported: sound.supported,
          road: has('replayAudioTarget') ? 'desk-application-frames' : 'panel-frame',
          detail: 'complete application audio unavailable: ' + String((err && err.message) || err) };
        failures += 1; retry('a'); tellSound(); note(sound.detail);
      }
      return false;
    }).then(function (result) {
      if (pendingSoundInputs === captures) pendingSoundInputs = [];
      if (pendingSoundContext === context) pendingSoundContext = null;
      if (pendingSoundDestination === destinationCapture) pendingSoundDestination = null;
      sndOpening = null; return result;
    });
    return sndOpening;
  }
  function startTheSound() {
    return startSound().then(function (result) { return { ok: result, audio: state().audio }; });
  }
  function tick() {
    watchdog = null;
    if (!enabled) return;
    var at = now();
    if (running && !live(stream, 'v')) failLane('v', 'the window picture was lost; capture will retry');
    if (sndRunning && !audioLive()) failLane('a', 'application audio was lost; capture will retry');
    if (!running && !opening && at >= nextPictureRetry) startPicture();
    if ((!sndRunning || audioCatalogDirty) && !sndOpening && at >= nextSoundRetry) startSound();
    if (running && !replacing && nativeRequested && at >= nextPictureRetry) {
      var wanted = nativeSize();
      if (wanted.w !== nativeRequested.w || wanted.h !== nativeRequested.h) replacePicture();
    }
    watchdog = root.setTimeout(tick, 1000);
  }
  function geometryChanged() {
    if (!enabled) return;
    if (resizeTimer != null) root.clearTimeout(resizeTimer);
    resizeTimer = root.setTimeout(function () { resizeTimer = null; replacePicture(); }, 180);
  }
  function start() {
    if (!has('replayPush') || !root.MediaRecorder) return Promise.resolve({ ok: false, detail: 'no replay capture bridge or MediaRecorder' });
    explicitlyStopped = false;
    if (!enabled) { enabled = true; lifecycle += 1; if (watchdog == null) watchdog = root.setTimeout(tick, 1000); }
    if (has('onReplayFlush') && !start.subscribed) {
      try { desk().onReplayFlush(flush); start.subscribed = true; } catch (err) {}
    }
    if (has('onReplayAudioSourcesChanged') && !start.sourcesSubscribed) {
      try { desk().onReplayAudioSourcesChanged(audioSourcesChanged); start.sourcesSubscribed = true; } catch (err) {}
    }
    startSound();
    return startPicture().then(function (result) { return { ok: result, audio: state().audio }; });
  }
  function stop() {
    explicitlyStopped = true; enabled = false; lifecycle += 1; running = false;
    if (watchdog != null) { root.clearTimeout(watchdog); watchdog = null; }
    if (resizeTimer != null) { root.clearTimeout(resizeTimer); resizeTimer = null; }
    requestStop(videoPiece);
    var old = stream; stream = null; stopTracks(old);
    closeSound('the page stopped it');
    if (has('replayStop')) { try { Promise.resolve(desk().replayStop('the page stopped it')).catch(function () {}); } catch (err) {} }
    return { ok: true };
  }
  function flush() {
    // Snapshot before closing: replacement recorders are deliberately excluded.
    // pending also includes old onstop/blob/IPC work that has not reached disk.
    var snapshot = Array.from(pending);
    requestStop(audioPiece); requestStop(videoPiece);
    if (!snapshot.length) return Promise.resolve(false);
    return Promise.all(snapshot.map(function (piece) { return piece.promise; }))
      .then(function (results) { return results.every(function (ok) { return ok; }); });
  }
  function state() {
    return { running: running, enabled: enabled, failures: failures, said: said,
      segment_ms: SEG_MS, fps: FPS, encoding: lastVideoEncoding, native: stream ? settings(stream) : null, pending: pending.size,
      streams: { picture: { open: !!stream, running: running },
        sound: { open: !!sndStream, running: sndRunning, pieces: sndPieces } },
      audio: { present: !!sound.present, state: sound.state, detail: sound.detail,
        supported: sound.supported, road: sound.road, live: audioLive(), complete: audioComplete(), source_settings: audioSettings(), targets: soundTargets.slice(),
        running: sndRunning, pieces: sndPieces } };
  }
  if (root.addEventListener) {
    root.addEventListener('resize', geometryChanged);
    root.addEventListener('beforeunload', stop);
    root.addEventListener('pagehide', stop);
  }
  function go() {
    if (!has('replayPush')) return;
    if (root.MutationObserver && doc && doc.body) {
      observer = new root.MutationObserver(function () {
        if (videoPiece && videoPiece.view !== view()) requestStop(videoPiece);
      });
      observer.observe(doc.body, { attributes: true, attributeFilter: ['class'] });
    }
    root.setTimeout(function () { if (!enabled && !explicitlyStopped) start(); }, 6000);
  }
  if (doc && doc.addEventListener) {
    ['pointerdown', 'keydown'].forEach(function (kind) {
      doc.addEventListener(kind, function () { if (enabled && (!sndRunning || audioCatalogDirty)) startSound(); }, true);
    });
  }
  if (doc) {
    if (doc.readyState === 'complete' || doc.readyState === 'interactive') go();
    else doc.addEventListener('DOMContentLoaded', go);
  }
  root.PineScreenRing = { start: start, stop: stop, state: state, flush: flush,
    startSound: startTheSound, sound: function () { return state().audio; }, SEG_MS: SEG_MS, FPS: FPS };
})(typeof window !== 'undefined' ? window : globalThis);
