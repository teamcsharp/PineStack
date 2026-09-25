/* THE DOT YOU TALK TO.
 *
 * "A dot that I'm able to tap on and use to begin talking to the tablet and
 * make a request... it'll temporarily mute the audio while I talk to it and
 * then it'll send a command just like it does through the other clients...
 * that dot basically explodes into a 3JS simulation of undulating particles
 * reacting to me talking, and it shows it on screen just like it would if I
 * was talking to Siri, and then it sends that command through and I'm able
 * to get a notification of the command I sent through and it being executed."
 *
 * THE TABLET CANNOT HEAR BY ITSELF, and this shaped the whole design.
 * Measured on the device: `cmd package query-services -a
 * android.speech.RecognitionService` returns "No services found", no speech
 * package is installed, and both voice_recognition_service and
 * speech_recognition_service read null. That is what a GApps-less LineageOS
 * GSI is - there is no recognizer on it to ask. So the words are heard by
 * the STATION: the clip is recorded here and posted to
 * /api/listen/transcribe, which bridges to wyoming-whisper.
 *
 * THE PARTICLES REACT TO THE REAL MICROPHONE. An animation that merely
 * looked busy would be a lie about whether anything is being heard - and on
 * a device with no recognizer, "is it hearing me?" is the first question
 * anyone will ask. The undulation is driven by an AnalyserNode on the live
 * input stream, so a silent room shows a still dot.
 *
 * THE SHOW IS DUCKED, NOT STOPPED. Talking over the station would put the
 * DJs into the microphone and the microphone into the command. Ducking is
 * local and reversible; pausing the air is a station-wide act and wrong for
 * one person holding a tablet.
 */
(function (root) {
  'use strict';

  var IDLE = 'idle', LISTENING = 'listening', THINKING = 'thinking';
  var MAX_MS = 12000;          /* a command is a sentence, not a monologue */
  /* 2026-09-15 (#1174): "dictation is finishing too fast. Like the moment
   * I take a pause it stops. I actually need double the threshold or
   * triple the threshold before it." Was 1400 ms, which is inside the
   * pause a person takes mid-sentence while they think - so a report cut
   * itself off at the comma. Tripled. The ceiling that ends a runaway
   * recording is elsewhere and unchanged, so this cannot strand him. */
  var SILENCE_MS = 4200;       /* quiet this long and we assume you are done */

  var state = IDLE;
  var fieldCapture = null;
  var stream = null;
  var recorder = null;
  var chunks = [];
  /* [#1224] `chunks` now holds Float32Array blocks off the tap below
     rather than MediaRecorder Blobs - the station only decodes WAV. */
  var pcmTap = null;
  var pcmGate = null;
  var pcmRate = 48000;
  var ctx = null;
  var analyser = null;
  var data = null;
  var frequencies = null;
  var frame = 0;
  var ducked = [];
  var startedAt = 0;
  var quietSince = 0;
  var scene = null;

  /* #1355: WHICH MICROPHONE.
   *
   * getUserMedia({audio: true}) asks for 'an' audio input, and what it
   * hands back is whatever Chromium picked - which on a machine with a
   * webcam, a headset and a line-in is frequently not the one the
   * operator has set as their Windows default. It is also silent about
   * its choice, so a dot that hears nothing and a dot that is listening
   * to an unplugged jack look identical.
   *
   * Three changes, each earning its place:
   *   - ask for deviceId 'default' explicitly. That is a real device id
   *     in Chromium, not a synonym for 'any': it FOLLOWS the system
   *     default, so changing it in Windows changes this without a
   *     relaunch.
   *   - say the track's label out loud when listening starts, so the
   *     answer to 'is it hearing me' includes 'with what'.
   *   - let it be pinned, because a default is a guess and the operator
   *     is not. Right-click the dot.
   *
   * `ideal`, never `exact`, for the default - an exact constraint on a
   * device that has gone is an OverconstrainedError and no microphone
   * at all, which is strictly worse than the wrong one.
   */
  var MIC_KEY = 'pineTalkMic';
  var micLabel = '';

  function micPin() {
    try { return localStorage.getItem(MIC_KEY) || ''; }
    catch (err) { return ''; }
  }

  function micConstraints(pin) {
    var audio = {
      /* The room is a room: the operator is talking over a broadcast
       * coming out of the same machine's speakers. */
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    };
    if (pin) audio.deviceId = {exact: pin};
    else audio.deviceId = {ideal: 'default'};
    return {audio: audio};
  }

  async function openMic() {
    var pin = micPin();
    try {
      return await navigator.mediaDevices.getUserMedia(micConstraints(pin));
    } catch (err) {
      if (!pin) throw err;
      /* The pinned device has gone - unplugged, or a Bluetooth headset
       * that wandered off. Forget it and take the default rather than
       * refusing to listen at all; a pin is a preference, not a
       * requirement. */
      try { localStorage.removeItem(MIC_KEY); } catch (e) { /* fine */ }
      return await navigator.mediaDevices.getUserMedia(micConstraints(''));
    }
  }

  function micName(got) {
    try {
      var track = got && got.getAudioTracks && got.getAudioTracks()[0];
      var name = String((track && track.label) || '').trim();
      /* Chromium prefixes the follow-the-system entry; the prefix is
       * the useful part of the answer, so keep it and trim the rest. */
      return name.length > 42 ? name.slice(0, 41) + '\u2026' : name;
    } catch (err) { return ''; }
  }

  /* The list, for the picker. Labels are empty until the microphone has
   * been opened once in this session - that is a browser rule, not a
   * fault - so an unnamed device is numbered rather than hidden. */
  async function mics() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
      return [];
    }
    var all = await navigator.mediaDevices.enumerateDevices();
    var n = 0;
    return all.filter(function (d) { return d.kind === 'audioinput'; })
      .map(function (d) {
        n += 1;
        return {id: d.deviceId,
          label: String(d.label || '').trim() || ('Microphone ' + n)};
      });
  }

  function useMic(id) {
    try {
      if (id) localStorage.setItem(MIC_KEY, id);
      else localStorage.removeItem(MIC_KEY);
    } catch (err) { /* an unremembered choice still works this session */ }
  }

  /* ---- the picker ----------------------------------------------- */

  function closeMicMenu() {
    var old = el('pineTalkMics');
    if (old) old.remove();
  }

  async function micMenu() {
    closeMicMenu();
    var list;
    try { list = await mics(); } catch (err) { list = []; }
    var box = document.createElement('div');
    box.id = 'pineTalkMics';
    box.className = 'pine-talk-mics';
    var head = document.createElement('div');
    head.className = 'pine-talk-mics-head';
    head.textContent = 'Which microphone';
    box.appendChild(head);
    var pin = micPin();
    var rows = [{id: '', label: 'System default'}].concat(list);
    rows.forEach(function (m) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pine-talk-mic' + (m.id === pin ? ' on' : '');
      b.textContent = m.label;
      b.addEventListener('click', function () {
        useMic(m.id);
        closeMicMenu();
        announce(m.id ? ('Listening with ' + m.label + ' from now on')
          : 'Back to whichever microphone the system says is default');
      });
      box.appendChild(b);
    });
    if (!list.length) {
      var none = document.createElement('div');
      none.className = 'pine-talk-mics-none';
      none.textContent = 'This machine reports no audio input.';
      box.appendChild(none);
    }
    document.body.appendChild(box);
    /* One dismissal road, attached after this click has finished
     * bubbling or it would close the menu it just opened. */
    setTimeout(function () {
      document.addEventListener('click', function away(ev) {
        if (box.contains(ev.target)) return;
        document.removeEventListener('click', away);
        closeMicMenu();
      });
    }, 0);
  }

  function api() {
    return root.pineDesktop || {
      post: function () { return Promise.reject(new Error('no bridge')); }
    };
  }
  function el(id) { return document.getElementById(id); }

  /* ---- the furniture -------------------------------------------------- */

  function mount() {
    if (el('pineTalkDot')) return el('pineTalkDot');
    /* Before anything else: put back whatever a previous life of this page
     * left ducked. See duck() for the measurement that made this needed. */
    try { unstick(); } catch (err) { /* never block the mount */ }
    var dot = document.createElement('button');
    dot.id = 'pineTalkDot';
    dot.className = 'pine-talk-dot';
    dot.title = 'Hold a moment and speak - the station will hear you';
    dot.innerHTML = '<canvas id="pineTalkFx" class="pine-talk-fx"></canvas>'
      + '<i class="pine-talk-core"></i>';
    dot.addEventListener('click', toggle);
    /* 2026-09-14: the canvas is the voice window; a tap on it while
       listening cancels rather than sends (see cancel()). */
    var fx = dot.querySelector('#pineTalkFx');
    if (fx) fx.addEventListener('click', function (ev) {
      if (state !== LISTENING) return;
      ev.stopPropagation();
      ev.preventDefault();
      cancel();
    });
    /* #1355: and the other button picks the ear. A right-click rather
     * than a second piece of chrome - the dot is deliberately one
     * object, and this is a setting that is changed once. */
    dot.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      micMenu();
    });
    dot.title = 'Click and speak - the station will hear you. '
      + 'Right-click to choose which microphone.';
    document.body.appendChild(dot);

    var say = document.createElement('div');
    say.id = 'pineTalkSay';
    say.addEventListener('click', function (ev) { if (state === LISTENING) { ev.stopPropagation(); cancel(); } });   /* 2026-09-14 */
    say.className = 'pine-talk-say';
    say.hidden = true;
    document.body.appendChild(say);
    var telemetry = document.createElement('div');
    telemetry.id = 'pineTalkTelemetry';
    telemetry.className = 'pine-talk-telemetry';
    telemetry.hidden = true;
    telemetry.setAttribute('aria-hidden', 'true');
    telemetry.innerHTML = '<div class="pine-talk-phase" data-talk-phase>Capturing</div>'
      + '<div class="pine-talk-spectrum" data-talk-spectrum></div>'
      + '<div class="pine-talk-spectrum-empty" data-talk-spectrum-empty>Spectrum unavailable</div>'
      + '<div class="pine-talk-metrics">'
      + '<div><span>Speech est.</span><b data-talk-metric="speech_probability">--</b></div>'
      + '<div><span>RMS</span><b data-talk-metric="rms">--</b></div>'
      + '<div><span>Peak</span><b data-talk-metric="peak">--</b></div>'
      + '<div><span>VAD</span><b data-talk-metric="vad_state">--</b></div>'
      + '<div><span>Silence</span><b data-talk-metric="silence_elapsed_ms">--</b></div>'
      + '<div><span>Timeout</span><b data-talk-metric="endpoint_timeout_ms">--</b></div>'
      + '<div><span>Remaining</span><b data-talk-metric="remaining_ms">--</b></div>'
      + '<div><span>Threshold</span><b data-talk-metric="threshold">--</b></div>'
      + '</div>';
    document.body.appendChild(telemetry);
    for (var i = 0; i < 24; i += 1) {
      var band = document.createElement('span');
      band.className = 'pine-talk-band';
      band.innerHTML = '<i></i><em></em>';
      telemetry.querySelector('[data-talk-spectrum]').appendChild(band);
    }
    return dot;
  }


  /* [#1224] THE DICTATION SURFACE, ABOVE EVERY WINDOW.
   *
   * "The text overlay isn't on top of all the windows. So the graphic of
   *  it responding to my speech needs to be on top of every window."
   *
   * In the page, view-chrome.css already puts the dot and its note at
   * 2147483080 (#1193), which settles it against every sheet this shell
   * can open and is the whole answer on the tablet.  It cannot be the
   * answer on the desk: Pine Box opens a dozen separate windows - the
   * shot editor, the inspector, the SC popup, the LCD, the video editor -
   * and #pineTalkDot lives in the main window's document only, so
   * whichever of those is in front is in front of it.  No value in a
   * stylesheet reaches outside its own page.
   *
   * So the shell owns a frameless, transparent, click-through,
   * always-on-top window and this tells it what to show.  Where the door
   * is not there - the tablet, or a desk that has not been relaunched
   * yet - every call is a no-op and nothing changes. */
  var overlayAt = 0;
  var overlayText = '';
  var overlayBad = false;

  function overlayMode() {
    if (state === LISTENING) return 'listening';
    if (state === THINKING) return 'thinking';
    return overlayText ? 'idle' : 'off';
  }

  function overlay(mode, level, force) {
    if (fieldCapture) mode = 'off';
    var bridge = root.pineDesktop;
    if (!bridge || typeof bridge.talkOverlay !== 'function') return;
    /* The level road calls this every animation frame. ~9 a second is
     * enough to look alive and is not an IPC message per vsync. */
    var now = (root.performance && root.performance.now)
      ? root.performance.now() : Date.now();
    if (!force && now - overlayAt < 110) return;
    overlayAt = now;
    try {
      bridge.talkOverlay({mode: String(mode || 'off'),
                          level: Number(level) || 0,
                          text: overlayText, bad: overlayBad});
    } catch (err) { /* an overlay is never worth an exception */ }
  }

  /* [#1224] THE TAKE, CACHED AS PCM AND TURNED INTO A REAL WAV.
   *
   * "there's just not the ability for it to cache my audio and then turn
   *  it into text"
   *
   * MediaRecorder gave webm/opus and the station's whisper door only
   * decodes WAV - measured: the same speech transcribes as WAV and comes
   * back with no words in it as webm.  The blocks are kept at the audio
   * context's own rate and the station resamples (audioop.ratecv in
   * whisper_transcribe); a 48 kHz WAV was proven through the live route. */
  function pcmWav(pieces, rate) {
    var total = 0;
    var i;
    var j;
    for (i = 0; i < pieces.length; i += 1) {
      total += (pieces[i] && pieces[i].length) || 0;
    }
    if (!total) return null;
    var hz = Math.max(8000, Math.round(Number(rate) || 48000));
    var buf = new ArrayBuffer(44 + total * 2);
    var view = new DataView(buf);
    var put = function (at, word) {
      for (var k = 0; k < word.length; k += 1) {
        view.setUint8(at + k, word.charCodeAt(k));
      }
    };
    put(0, 'RIFF');
    view.setUint32(4, 36 + total * 2, true);
    put(8, 'WAVE');
    put(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);            /* PCM */
    view.setUint16(22, 1, true);            /* mono */
    view.setUint32(24, hz, true);
    view.setUint32(28, hz * 2, true);       /* bytes a second */
    view.setUint16(32, 2, true);            /* block align */
    view.setUint16(34, 16, true);           /* bits a sample */
    put(36, 'data');
    view.setUint32(40, total * 2, true);
    var at = 44;
    for (i = 0; i < pieces.length; i += 1) {
      var piece = pieces[i];
      for (j = 0; j < piece.length; j += 1) {
        var v = piece[j];
        if (v > 1) v = 1; else if (v < -1) v = -1;
        view.setInt16(at, v < 0 ? v * 0x8000 : v * 0x7fff, true);
        at += 2;
      }
    }
    return buf;
  }

  function pcmStop() {
    try {
      if (pcmTap) { pcmTap.onaudioprocess = null; pcmTap.disconnect(); }
    } catch (err) { /* already gone */ }
    pcmTap = null;
  }

  /* [#1224] The spoken reply, once the bytes are in hand, whichever road
   * brought them. */
  function playReply(blob) {
    var src = URL.createObjectURL(blob);
    var player = new Audio(src);
    player.volume = 1;
    /* The show is still ducked from the capture; hold it down until the
     * answer has finished, or the reply lands under the broadcast. */
    player.onended = function () {
      URL.revokeObjectURL(src);
      duck(false);
      release(600);
    };
    player.onerror = function () { URL.revokeObjectURL(src); duck(false); };
    duck(true);
    var go = player.play();
    if (go && go.catch) {
      go.catch(function () { duck(false); });
    }
  }

  function announce(text, bad) {
    var box = el('pineTalkSay') || mount() && el('pineTalkSay');
    if (!box) return;
    box.textContent = text || '';
    box.hidden = !text;
    box.classList.toggle('bad', !!bad);
    /* [#1224] and on top of every WINDOW, not only on top of this page. */
    overlayText = String(text || '');
    overlayBad = !!bad;
    overlay(overlayMode(), 0, true);
    if (text && !bad) {
      clearTimeout(box.__timer);
      /* AN ANSWER STAYS UP LONGER THAN A STATUS.
       *
       * Six seconds is right for "Listening..." and wrong for a reply the
       * operator is meant to read - especially one that names what the
       * station did with the request. Long answers get longer still,
       * roughly at reading speed, and are capped so the screen does not
       * keep a stale answer all evening. */
      var dwell = 6000;
      var size = String(text || '').length;
      if (size > 40) dwell = Math.min(26000, 6000 + size * 55);
      box.__timer = setTimeout(function () {
        box.hidden = true;
        overlayText = '';                                 /* [#1224] */
        overlayBad = false;
        overlay(overlayMode(), 0, true);
      }, dwell);
    }
  }

  function setState(next) {
    state = next;
    overlay(overlayMode(), 0, true);                      /* [#1224] */
    var telemetry = el('pineTalkTelemetry');
    if (telemetry) {
      telemetry.hidden = next === IDLE;
      telemetry.classList.toggle('field-capture', !!fieldCapture && next !== IDLE);
      telemetry.classList.toggle('transcribing', next === THINKING);
      telemetry.querySelector('[data-talk-phase]').textContent =
        next === LISTENING ? 'Capturing' : 'Transcribing';
      if (next === LISTENING) resetTelemetry();
      if (next === THINKING) drawSpectrum(null, performance.now());
    }
    var dot = el('pineTalkDot');
    if (!dot) return;
    dot.classList.toggle('listening', next === LISTENING);
    dot.classList.toggle('thinking', next === THINKING);
    dot.classList.toggle('field-capture', !!fieldCapture && next !== IDLE);
  }

  /* ---- ducking -------------------------------------------------------- */

  /* Quieten the show while the microphone is open, and put every level back
   * exactly as it was. The sampler is spared - a pad is the operator's own
   * hands, not the broadcast, and the same rule is written into
   * PineTerminalAudio.mute and PineAudioLaw. */
  /* A DUCK THAT ALWAYS COMES BACK UP.
   *
   * Measured on the tablet: two media elements sitting at volume 0.12 with
   * nothing listening and the dot idle - a duck applied and never
   * released. Every road out of the exchange calls duck(false), but "every
   * road" is exactly the assumption that fails: a thrown promise, a view
   * torn down mid-take, a page that navigates. The operator then finds his
   * broadcast mysteriously quiet and no control that explains it.
   *
   * So the duck arms its own release. Nothing can leave the audio down for
   * longer than a take could possibly last, whatever happens upstream. */
  var duckSafety = 0;
  var DUCK_CEILING_MS = 30000;

  function duck(on) {
    clearTimeout(duckSafety);
    /* 2026-09-14: "any time that I'm dealing with dictation, always duck
       the audio completely or to 2%." PineDuck (pine-duck.js) is the one
       levelled road every surface shares; the 0.12 below is only the
       fallback for a page that loaded without it. */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      if (on) { root.PineDuck.hold('dictation', root.PineDuck.DICTATION); return 1; }
      root.PineDuck.release('dictation');
      return 0;
    }
    if (on) {
      /* Re-ducking without an intervening release would record 0.12 as the
       * volume to restore, and the sound would never come back. */
      if (ducked.length) duck(false);
      ducked = [];
      var nodes = document.querySelectorAll('audio, video');
      for (var i = 0; i < nodes.length; i += 1) {
        var node = nodes[i];
        if (node.closest && node.closest('#sampler, .pb-sampler')) continue;
        ducked.push({node: node, was: node.volume});
        node.volume = Math.min(node.volume, 0.12);
      }
      duckSafety = setTimeout(function () {
        if (ducked.length) {
          duck(false);
          announce('the audio was still ducked, so it has been put back', true);
        }
      }, DUCK_CEILING_MS);
      return ducked.length;
    }
    for (var k = 0; k < ducked.length; k += 1) {
      try { ducked[k].node.volume = ducked[k].was; } catch (err) { /* gone */ }
    }
    ducked = [];
    return 0;
  }

  /* Anything stuck down from a previous life of this page, put back. Runs
   * once at mount, because a reload does not un-duck what a crash left. */
  function unstick() {
    var nodes = document.querySelectorAll('audio, video');
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (node.closest && node.closest('#sampler, .pb-sampler')) continue;
      if (node.volume > 0.1 && node.volume < 0.13) node.volume = 1;
    }
  }

  /* ---- the particles -------------------------------------------------- */

  /* THE SCENE IS BUILT ASYNCHRONOUSLY - three.js is fetched on first use -
   * so this answers with a promise. An earlier version checked `scene`
   * synchronously before assembling the words, and on the first press
   * there was nothing there to assemble with: the cloud never spelled
   * anything, silently. */
  function startScene() {
    var canvas = el('pineTalkFx');
    if (!canvas || !root.PinePlexus) return Promise.resolve(null);
    if (scene) { scene.start(); return Promise.resolve(scene); }
    if (!sceneLoad) {
      sceneLoad = root.PinePlexus.create(canvas).then(function (made) {
        scene = made;
        return made;
      }, function () { sceneLoad = null; return null; });
    }
    return sceneLoad.then(function (made) {
      if (made) made.start();
      return made;
    });
  }
  var sceneLoad = null;
  function stopScene() { if (scene) scene.stop(); }

  /* The canvas is the dot's own overlay and must actually be the size it
   * is painted at, or the letters are rastered into the 300x150 default
   * and land off screen. */
  function sizeScene() {
    var canvas = el('pineTalkFx');
    if (!canvas) return;
    var box = canvas.getBoundingClientRect();
    var dpr = Math.min(2, root.devicePixelRatio || 1);
    var w = Math.max(1, Math.round(box.width * dpr));
    var h = Math.max(1, Math.round(box.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  }

  /* How loud the room is, 0..1, straight off the microphone. */
  /* WHICH EAR. The desktop opens the microphone in the page, because it
   * runs from file:// - a trustworthy origin - and getUserMedia is there.
   * The tablet cannot: its panel is served over plain http from the LAN
   * address, which is NOT a secure context, and Chromium removes
   * `navigator.mediaDevices` from such a page entirely. So the tablet
   * listens in Kotlin and only the words cross the bridge. Measured, not
   * assumed: `window.isSecureContext` is false and `navigator.mediaDevices`
   * is undefined on the device. */
  var native = false;
  function haveNativeEar() {
    var b = root.pineDesktop;
    return !!(b && typeof b.micStart === 'function' && typeof b.micLevel === 'function');
  }

  var spectrumPeaks = [];
  var spectrumHeldAt = [];

  function finite(value) {
    return value !== null && value !== undefined && value !== ''
      && isFinite(Number(value)) ? Number(value) : null;
  }

  function clamp01(value) {
    return Math.max(0, Math.min(1, value));
  }

  function resetTelemetry() {
    spectrumPeaks = [];
    spectrumHeldAt = [];
    var telemetry = el('pineTalkTelemetry');
    if (!telemetry) return;
    var values = telemetry.querySelectorAll('[data-talk-metric]');
    for (var i = 0; i < values.length; i += 1) values[i].textContent = '--';
    drawSpectrum(null, 0);
  }

  function drawSpectrum(bands, now) {
    var telemetry = el('pineTalkTelemetry');
    if (!telemetry) return;
    var valid = bands && bands.length === 24;
    telemetry.classList.toggle('has-spectrum', !!valid);
    if (!valid) return;
    var bars = telemetry.querySelectorAll('.pine-talk-band');
    for (var i = 0; i < 24; i += 1) {
      var value = finite(bands[i]);
      value = value === null ? 0 : clamp01(value);
      if (value >= (spectrumPeaks[i] || 0)) {
        spectrumPeaks[i] = value;
        spectrumHeldAt[i] = now;
      } else if (now - (spectrumHeldAt[i] || 0) > 180) {
        spectrumPeaks[i] = Math.max(value, (spectrumPeaks[i] || 0) - 0.025);
      }
      bars[i].firstElementChild.style.height = (value * 100) + '%';
      bars[i].lastElementChild.style.bottom = (spectrumPeaks[i] * 100) + '%';
    }
  }

  function showMetric(telemetry, name, value) {
    telemetry.querySelector('[data-talk-metric="' + name + '"]').textContent = value;
  }

  function formatAmplitude(value) {
    var n = finite(value);
    return n === null ? '--' : n.toFixed(3);
  }

  function formatMs(value) {
    var n = finite(value);
    return n === null ? '--' : Math.max(0, Math.round(n)) + ' ms';
  }

  function renderTelemetry(metrics, now, bar, heardAnything) {
    var telemetry = el('pineTalkTelemetry');
    if (!telemetry) return;
    var source = metrics.raw;
    var estimated = !native;
    var probability, vad, silence, timeout, remaining, threshold;
    if (native) {
      probability = source && finite(source.speech_probability);
      vad = source && source.vad_state;
      silence = source && source.silence_elapsed_ms;
      timeout = source && source.endpoint_timeout_ms;
      remaining = source && source.remaining_ms;
      threshold = source && source.threshold;
    } else {
      probability = bar === null ? null
        : clamp01((metrics.level - bar) / Math.max(bar * 2, 0.001));
      vad = bar === null ? 'Calibrating'
        : metrics.level > bar ? 'Speech' : heardAnything ? 'Silence' : 'Waiting';
      silence = bar === null ? null : quietSince ? now - quietSince : 0;
      timeout = SILENCE_MS;
      remaining = bar === null || !heardAnything ? null
        : Math.max(0, SILENCE_MS - silence);
      threshold = bar;
    }
    showMetric(telemetry, 'speech_probability',
      probability === null || probability === undefined ? '--'
        : Math.round(clamp01(probability) * 100) + '%' + (estimated ? ' est.' : ''));
    showMetric(telemetry, 'rms', formatAmplitude(metrics.rms));
    showMetric(telemetry, 'peak', formatAmplitude(metrics.peak));
    showMetric(telemetry, 'vad_state', vad == null || vad === '' ? '--' : String(vad));
    showMetric(telemetry, 'silence_elapsed_ms', formatMs(silence));
    showMetric(telemetry, 'endpoint_timeout_ms', formatMs(timeout));
    showMetric(telemetry, 'remaining_ms', formatMs(remaining));
    showMetric(telemetry, 'threshold', formatAmplitude(threshold));
    drawSpectrum(metrics.bands, now);
  }

  function micMetrics() {
    if (native) {
      var raw = null;
      try {
        if (typeof root.pineDesktop.micMetrics === 'function') {
          raw = root.pineDesktop.micMetrics();
          if (!raw || typeof raw !== 'object') raw = null;
        }
      } catch (err) { raw = null; }
      var fallback = null;
      if (!raw || finite(raw.peak) === null) {
        try { fallback = finite(root.pineDesktop.micLevel()); }
        catch (err) { /* the bridge may be closing */ }
      }
      var peak = raw && finite(raw.peak);
      return {
        raw: raw,
        level: peak === null || peak === undefined ? (fallback || 0) : peak,
        rms: raw && raw.rms,
        peak: peak === null || peak === undefined ? fallback : peak,
        bands: raw && raw.bands
      };
    }
    if (!analyser || !data) return {level: 0, rms: null, peak: null, bands: null};
    analyser.getByteTimeDomainData(data);
    var peak = 0, power = 0;
    for (var i = 0; i < data.length; i += 1) {
      var v = Math.abs(data[i] - 128) / 128;
      if (v > peak) peak = v;
      power += v * v;
    }
    var bands = null;
    if (frequencies && typeof analyser.getByteFrequencyData === 'function') {
      analyser.getByteFrequencyData(frequencies);
      bands = [];
      for (var b = 0; b < 24; b += 1) {
        var lo = Math.floor(Math.pow(b / 24, 1.7) * frequencies.length);
        var hi = Math.max(lo + 1,
          Math.floor(Math.pow((b + 1) / 24, 1.7) * frequencies.length));
        var strongest = 0;
        for (var j = lo; j < hi && j < frequencies.length; j += 1) {
          if (frequencies[j] > strongest) strongest = frequencies[j];
        }
        bands.push(strongest / 255);
      }
    }
    return {level: peak, rms: Math.sqrt(power / data.length),
      peak: peak, bands: bands};
  }

  /* ---- the gesture ---------------------------------------------------- */

  function toggle() {
    if (state === LISTENING) { finish(); return; }
    if (state === THINKING) return;
    listen();
  }

  async function listen() {
    mount();
    cancelled = false;

    /* The native ear first, where there is one. */
    if (haveNativeEar()) {
      native = true;
      var opened;
      try {
        opened = await root.pineDesktop.micStart();
      } catch (err) {
        announce('The microphone could not be opened: '
          + ((err && err.message) || err), true);
        return;
      }
      if (!opened || !opened.ok) {
        announce(String((opened && opened.detail)
          || 'The microphone could not be opened.'), true);
        return;
      }
      duck(true);
      setState(LISTENING);
      /* Say which effects the hardware gave us. On a terminal that plays
       * the show out of its own speaker, whether the echo canceller is
       * there is the difference between hearing the operator and hearing
       * the broadcast. */
      if (!fieldCapture) {
        announce('Listening...' + (opened.effects && opened.effects !== 'none'
          ? ' (' + opened.effects + ')' : ''));
        startScene();
      }
      startedAt = performance.now();
      quietSince = 0;
      watch();
      return;
    }

    native = false;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      announce('This terminal has no microphone the page can open.', true);
      return;
    }
    try {
      stream = await openMic();
    } catch (err) {
      /* The usual cause is the WebView not having been granted RECORD_AUDIO,
       * which is a native permission the page cannot ask for itself. */
      announce('The microphone was refused: ' + (err && err.name || err), true);
      return;
    }

    duck(true);
    setState(LISTENING);
    /* #1355: WITH WHAT. A dot that is listening to the wrong jack and a
     * dot that is listening to a quiet room look the same, and the
     * operator can only tell them apart if the name is on screen. */
    micLabel = micName(stream);
    if (!fieldCapture) {
      announce('Listening...' + (micLabel ? ' (' + micLabel + ')' : ''));
      startScene();
    }

    ctx = ctx || new (root.AudioContext || root.webkitAudioContext)();
    if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) { /* later */ } }
    var source = ctx.createMediaStreamSource(stream);
    analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    data = new Uint8Array(analyser.fftSize);
    frequencies = new Uint8Array(analyser.frequencyBinCount);
    /* NOT connected to the destination. Routing the microphone to the
     * speakers is a feedback loop, and on a tablet held near the speaker it
     * is an immediate one. */
    source.connect(analyser);

    chunks = [];
    /* [#1224] CACHE THE AUDIO, AS SOMETHING THE STATION CAN READ.
     *
     * This was `new MediaRecorder(stream)`, which on this shell produces
     * audio/webm;codecs=opus - and whisper_transcribe() only decodes WAV,
     * so every take the operator made on the desk arrived as bytes the
     * station could not hear.  Measured with one piece of real speech:
     * as WAV it transcribes, as webm it comes back "found no words in it".
     *
     * The tap hangs off the SAME MediaStreamSource the level meter uses,
     * so what is sent and what he watched react are one signal.  It is
     * connected through a gain of 0 because a ScriptProcessor only runs
     * when it reaches the destination - and routing the microphone to the
     * speakers of a machine playing the broadcast is a feedback loop. */
    pcmRate = ctx.sampleRate || 48000;
    pcmStop();
    pcmTap = ctx.createScriptProcessor(4096, 1, 1);
    pcmTap.onaudioprocess = function (event) {
      if (state !== LISTENING) return;
      var raw = event.inputBuffer.getChannelData(0);
      var copy = new Float32Array(raw.length);
      copy.set(raw);
      chunks.push(copy);
    };
    pcmGate = pcmGate || ctx.createGain();
    pcmGate.gain.value = 0;
    source.connect(pcmTap);
    pcmTap.connect(pcmGate);
    pcmGate.connect(ctx.destination);

    startedAt = performance.now();
    quietSince = 0;
    watch();
  }

  /* Stop on a pause, or on the ceiling. Neither is a timer the operator has
   * to think about: they stop talking, and it goes. */
  /* THE THRESHOLD IS THE ROOM'S, NOT A NUMBER I CHOSE.
   *
   * It was a fixed 0.06, and on the operator's first real take the level
   * sat around 0.014 - so every frame counted as silence and the dot was
   * ready to stop 1.4 seconds after he began speaking. A fixed threshold
   * is a guess about a microphone's sensitivity, and this one turned out
   * to be a bad guess by a factor of four.
   *
   * So the first 400 ms are taken as the room: whatever is in it with
   * nobody speaking. Speech is then anything well above that, with a floor
   * so that a silent room does not make the threshold zero and a ceiling
   * so that a noisy one does not make it unreachable. The dot also refuses
   * to call it silence until it has heard SOMETHING, which stops a slow
   * start being cut off before the first word. */
  function watch() {
    cancelAnimationFrame(frame);
    var floor = 0;
    var floorFrames = 0;
    var bar = 0.05;
    var heardAnything = false;
    var tick = function () {
      frame = requestAnimationFrame(tick);
      if (state !== LISTENING) return;
      var now = performance.now();
      var metrics = micMetrics();
      var loud = metrics.level;
      var since = now - startedAt;

      /* THE CLOUD FOLLOWS THE VOICE, FROM THE FIRST FRAME.
       *
       * Same reading that decides when to stop, so what the operator sees
       * and what the dot believes are the same number - a cloud that
       * reacts to something else is worse than one that does not react at
       * all.
       *
       * This used to sit BELOW the room-measuring return, so for the first
       * 400 ms of every take the cloud was told nothing and sat still.
       * That is precisely the moment the operator is looking at it to find
       * out whether it is listening, and on a take he starts talking into
       * immediately it was the only moment that mattered. Measuring the
       * room and showing the room are not in conflict; both happen now. */
      if (scene && scene.level) scene.level(loud);
      overlay('listening', loud);                         /* [#1224] */

      if (since < 400) {
        floor += loud; floorFrames += 1;
        renderTelemetry(metrics, now, null, heardAnything);
        return;                      /* still listening to the room */
      }
      if (floorFrames && bar === 0.05) {
        var room = floor / floorFrames;
        bar = Math.min(0.22, Math.max(0.012, room * 3.5 + 0.008));
      }

      if (loud > bar) { quietSince = 0; heardAnything = true; }
      else if (!quietSince) quietSince = now;
      renderTelemetry(metrics, now, bar, heardAnything);

      if (since > MAX_MS) { finish(); return; }
      if (!heardAnything) {
        /* Nothing yet. Give it a while before deciding nobody spoke. */
        if (since > 4000) { finish(); return; }
        return;
      }
      if (quietSince && now - quietSince > SILENCE_MS && since > 900) {
        finish();
      }
    };
    frame = requestAnimationFrame(tick);
  }

  /* 2026-09-14: "During dictation if I tap on the voice window, cancel it."
   * The dot's core still finishes and SENDS (a tap on the dot is how it
   * has always ended); the WINDOW - the particle canvas that grows while
   * it listens, and the "Listening..." note - now cancels: the recording
   * stops and is thrown away, nothing is sent, the show comes back up. */
  var cancelled = false;
  function cancel() {
    if (state !== LISTENING) return;
    cancelled = true;
    cancelAnimationFrame(frame);
    duck(false);
    try { if (native && root.pineDesktop && root.pineDesktop.micStop) root.pineDesktop.micStop(); } catch (e) { /* the ear closes by itself */ }
    try { if (recorder && recorder.state !== 'inactive') recorder.stop(); } catch (e) { /* already stopped */ }
    pcmStop();                                            /* [#1224] */
    if (stream) {
      stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) { /* gone */ } });
      stream = null;
    }
    chunks = [];
    capture = null;
    setState(IDLE);
    announce('Cancelled - nothing was sent.');
    release(1500);
  }

  function finish() {
    if (state !== LISTENING) return;
    setState(THINKING);
    if (!fieldCapture) announce('Sending it through...');
    cancelAnimationFrame(frame);
    if (native) { sendNative(); return; }
    pcmStop();                                            /* [#1224] */
    send();
  }

  /* The native road: stop, and the words come back. The clip never enters
   * the page - moving a ten-second WAV through the bridge as base64 would
   * cost a third more bytes and buy nothing, since nothing here wants the
   * audio, only what was said. */
  async function sendNative() {
    if (cancelled) { cancelled = false; return; }   /* 2026-09-14: thrown away */
    /* The scene is NOT stopped here any more: it has the words to assemble
     * next. Ducking also holds, because the spoken reply follows. */
    duck(false);
    var got;
    try {
      got = await root.pineDesktop.micStop();
    } catch (err) {
      setState(IDLE);
      finishEmptyCapture();
      announce(String((err && err.message) || err), true);
      return;
    }
    var text = String((got && got.text) || '').trim();
    if (!text) {
      setState(IDLE);
      finishEmptyCapture();
      /* EVERY EMPTY ANSWER NAMES ITSELF.
       *
       * "Nothing was made out of that" used to be the sentence for all of
       * them, and it cost three takes to find a bug that was nowhere near
       * the operator's voice: the station was reading whisper's transcript
       * out of a field wyoming does not use, so his words were sitting in
       * the container log while this said, in effect, "you were not
       * understood". A message that blames the wrong half of the system is
       * worse than no message.
       *
       * The native side now returns a detail for every road out - a stale
       * take, a short take, a silent room, a refusal, a timeout, an
       * unparseable answer, and whisper genuinely hearing no words - and
       * the station puts its own reason in the body. So this shows what it
       * was told. The fallback below is not a description of the audio any
       * more; it says that the terminal was left without a reason, which
       * is itself the fault to chase. */
      announce(String((got && got.detail)
        || 'the ear came back with no words and no reason - which is a '
           + 'fault in the terminal, not in what you said'), true);
      release(300);
      return;
    }
    await act(text);
  }

  async function send() {
    if (cancelled) { cancelled = false; return; }   /* 2026-09-14: thrown away */
    duck(false);
    if (stream) {
      stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) { /* gone */ } });
      stream = null;
    }
    pcmStop();                                            /* [#1224] */
    var wav = pcmWav(chunks, pcmRate);                    /* [#1224] */
    chunks = [];
    if (!wav || wav.byteLength < 2000) {
      setState(IDLE);
      finishEmptyCapture();
      announce('That was too short to hear.', true);
      return;
    }
    try {
      var heard = await postAudio(wav);
      var text = String((heard && heard.text) || '').trim();
      if (!text) {
        setState(IDLE);
        finishEmptyCapture();
        /* [#1224] An empty transcript carries its own reason now - the
           station puts one in `detail` and sendNative() has repeated it
           since the day "Nothing was made out of that" cost three takes
           to a bug nowhere near the operator's voice. */
        announce(String((heard && heard.detail)
          || 'Nothing was made out of that.'), true);
        return;
      }
      await act(text);
    } catch (err) {
      setState(IDLE);
      finishEmptyCapture();
      announce(String((err && err.message) || err), true);
    }
  }

  /* ONE PLACE that decides what a heard sentence does, whichever ear
   * produced it. Keeping this out of the capture path is what lets the
   * same dot serve a song request, a chat line and a wake word.
   *
   * THE WHOLE EXCHANGE, the way the other boxes do it:
   *
   *   "Have the dot responsive to me talking while I'm talking and then I
   *    want it to tell me that it understood what I said and then generate
   *    a response to the command just like it does normally with the pine
   *    box agent. I want the same experience I have with the other boxes."
   *
   * The Nabu's experience is: it hears you, Home Assistant transcribes,
   * the sentence goes to /v1/chat/completions, and HA SPEAKS the string
   * that comes back. The station deliberately does not say it itself -
   * app.py:96487, "calling speak() here as well would say it twice AND cut
   * itself off" - so whoever asked owns the saying.
   *
   * That last step is the one the tablet was missing. It showed the reply
   * as text and stopped, which is a different experience from the one the
   * operator has everywhere else. So the reply is now spoken here, through
   * the station's own voice bench (/v1/audio/speech), and the text stays
   * on screen underneath it.
   */
  /* 2026-09-14: THE DICTATED PINE REPORT.
   *
   * "tap on the dot on the tablet and say I want to make a pine report
   *  and it converts into a setup of a pop-up window where I can basically
   *  file a pine report through dictation and then make corrections
   *  through typing on the keyboard if necessary and then file that
   *  report ... either confirm or decline sending it through."
   *
   * The dot already hears a sentence and hands it to act(). Two things are
   * added and nothing is bypassed: a sentence that ASKS for a report opens
   * the pad instead of going to the model, and while the pad is open a
   * `capture` hook takes the NEXT heard sentence into the pad's text
   * instead of to the model. Everything typed stays editable; Send posts
   * to /api/pine-requests like the panel's own box (with the station's
   * debug block by choice); Cancel throws it away. */
  var capture = null;
  var pad = null;

  function finishEmptyCapture() {
    if (!capture) return false;
    var take = capture;
    capture = null;
    try { take(''); } catch (err) { /* the caller still gets its UI back */ }
    return true;
  }

  function wantsReport(text) {
    var t = String(text || '').toLowerCase();
    if (!/\breport\b/.test(t)) return false;
    return /\b(pine|inbox|make|file|new|create|start|write|submit|send)\b/.test(t);
  }

  function padClose() {
    capture = null;
    if (pad && pad.parentNode) pad.parentNode.removeChild(pad);
    pad = null;
  }

  var padImage = '';
  /* 2026-09-15, #1148: `note` is the OPTIONAL fourth argument and it is a
     line the pad opens with, above whatever was dictated. It exists so the
     scrub strip can say which frame the operator actually chose:

       "Whenever I access the screen capture to follow report, I also want
        to be able to scrub between the last five seconds of the broadcast
        to find the right frame."

     A picture from 2.4 s before the capture is not the picture the report
     would otherwise claim to be, so the inbox item must say so in words -
     the image alone cannot. Blank means nothing is added and the pad opens
     exactly as it did before. */
  function reportOpen(heard, image, dictateNow, firstLine) {
    padClose();
    padImage = String(image || '');
    /* Not called `note`: the pad already has a `note` element below. */
    var padNote = String(firstLine || '').trim();
    pad = document.createElement('div');
    pad.id = 'pineReportPad';
    pad.setAttribute('style', 'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);'
      + 'width:min(92vw,560px);max-height:88vh;display:flex;flex-direction:column;gap:10px;'
      + 'padding:14px 16px;border:1px solid #2a3a44;border-radius:12px;background:#0b1116;'
      + 'color:#dfe7ee;font:14px/1.4 system-ui,sans-serif;z-index:2147483040;'
      + 'box-shadow:0 18px 60px rgba(0,0,0,.6)');
    var head = document.createElement('b');
    head.textContent = 'A Pine report';
    head.style.fontSize = '16px';
    var hint = document.createElement('div');
    hint.setAttribute('style', 'color:#9fb3c0;font-size:12px');
    hint.textContent = 'Dictate it, fix it on the keyboard, then Send it to the inbox - or Cancel.';
    var area = document.createElement('textarea');
    area.setAttribute('style', 'width:100%;min-height:160px;resize:vertical;padding:10px;'
      + 'border:1px solid #2a3a44;border-radius:8px;background:#05080a;color:#dfe7ee;'
      + 'font:15px/1.45 system-ui,sans-serif;box-sizing:border-box');
    area.placeholder = 'What should the Pine Box do?';
    var note = document.createElement('div');
    note.setAttribute('style', 'color:#65c7da;font-size:12px;min-height:16px');
    var debugRow = document.createElement('label');
    debugRow.setAttribute('style', 'display:flex;align-items:center;gap:8px;font-size:12px;color:#9fb3c0');
    var debug = document.createElement('input');
    debug.type = 'checkbox';
    /* 2026-09-15 (#1171): "Remember if I have this toggled off and retain
       that setting so that way it's not enabled accidentally for things
       that it's not needed for." It was rebuilt ticked every time the pad
       opened, so a deliberate no lasted exactly one report. Remembered per
       glass in localStorage - the same key the panel's Pine Chat uses, so
       one answer covers both places he files from on this screen - and on
       by default only until he says otherwise. Every access is wrapped:
       the accessor itself throws in some contexts on this stack, and a
       preference is never worth an exception. */
    debug.checked = true;
    try {
      var savedDebug = localStorage.getItem('pineDebugAttach');
      if (savedDebug !== null) debug.checked = savedDebug === '1';
    } catch (err) { /* the default stands */ }
    debug.addEventListener('change', function () {
      try { localStorage.setItem('pineDebugAttach', debug.checked ? '1' : '0'); }
      catch (err) { /* a glass that cannot remember still works */ }
    });
    debugRow.appendChild(debug);
    debugRow.appendChild(document.createTextNode("Attach the station's debug information to this report"));
    var row = document.createElement('div');
    row.setAttribute('style', 'display:flex;gap:8px;flex-wrap:wrap');
    function btn(label, style, go) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.setAttribute('style', 'flex:1 1 auto;min-height:40px;padding:8px 12px;border-radius:8px;'
        + 'border:1px solid #2a3a44;background:#111922;color:#dfe7ee;font-size:14px;' + (style || ''));
      b.addEventListener('click', function (ev) { ev.stopPropagation(); go(b); });
      row.appendChild(b);
      return b;
    }
    var dictate = btn('Dictate', '', function () {
      note.textContent = 'listening - speak, then wait a moment';
      capture = function (words) {
        /* #1148: a pad opened with a frame note ends in a NEWLINE, and the
           dictation must land under that line, not beside it - the note is
           the first line of the report or it is nothing. Anywhere else this
           behaves exactly as it always did: one space between sentences. */
        var raw = area.value;
        var had = raw.replace(/\s+$/, '');
        var join = had ? (/\n\s*$/.test(raw) ? '\n' : ' ') : '';
        area.value = had + join + String(words || '').trim();
        note.textContent = 'heard - fix anything on the keyboard, or Dictate more';
        try { area.focus(); } catch (e) {}
      };
      try { listen(); } catch (err) { note.textContent = 'could not listen: ' + (err && err.message || err); capture = null; }
    });
    btn('Send to the inbox', 'background:#1d4d5a;border-color:#2c7a8c', function (b) {
      var text = area.value.trim();
      if (!text) { note.textContent = 'there is nothing to send yet'; return; }
      b.disabled = true;
      note.textContent = 'sending...';
      Promise.resolve(api().post('/api/pine-requests', {text: text, debug: !!debug.checked, images: padImage ? [padImage] : []}))
        .then(function (got) {
          var id = got && got.submitted && got.submitted.id;
          var said = 'Filed as Pine report #' + id + '.';
          note.textContent = said;
          announce(said);
          try { speak(said); } catch (e) {}
          setTimeout(padClose, 1600);
        }, function (err) {
          b.disabled = false;
          note.textContent = 'the station refused it: ' + ((err && err.message) || err);
        });
    });
    btn('Cancel', '', function () { padClose(); announce('Report cancelled.'); });
    pad.appendChild(head);
    pad.appendChild(hint);
    if (padImage) {
      /* 2026-09-14: the picture the key chord took rides the report. */
      var shot = document.createElement('img');
      shot.src = padImage;
      shot.alt = 'the screen as it was';
      shot.setAttribute('style', 'width:100%;max-height:34vh;object-fit:contain;border:1px solid #2a3a44;border-radius:8px;background:#000');
      pad.appendChild(shot);
    }
    pad.appendChild(area);
    pad.appendChild(debugRow);
    pad.appendChild(row);
    pad.appendChild(note);
    document.body.appendChild(pad);
    /* 2026-09-14: "Whenever I'm filing a report ... lower the broadcast to
       10%." The hold is tied to the pad: when the pad leaves, so does it. */
    if (root.PineDuck) root.PineDuck.hold('report-pad', root.PineDuck.REPORT, pad);
    /* The sentence that opened the pad may carry the report already:
       "make a pine report: the sampler is silent". Keep what follows. */
    var body = String(heard || '').replace(/^.*?\breport\b[\s:,.-]*/i, '').trim();
    if (body.split(/\s+/).length >= 3) area.value = body;
    /* #1148: the chosen frame goes in as the FIRST LINE, and the dictated
       words (if any) keep the rest. It is plain text in the report body on
       purpose: the inbox item then says which frame this is without anyone
       having to open the picture and guess. */
    if (padNote) area.value = padNote + (area.value ? '\n' + area.value : '\n');
    note.textContent = body ? 'that is what was heard after "report" - edit it, or Dictate more' : 'press Dictate and say the report';
    if (padNote && !body) note.textContent = 'the frame is noted above - press Dictate and say the report';
    try { (body ? area : dictate).focus(); } catch (e) {}
    if (dictateNow) {
      /* the chord: the dot comes up listening at once */
      setTimeout(function () { try { dictate.click(); } catch (e) { /* the button is there */ } }, 350);
    }
  }

  /* 2026-09-14: THE KEY CHORD ON THE TABLET. "if I press the lock button
   * and the volume up button ... take a picture of the screen ... flash
   * like a photograph ... the dot should come up and begin taking my
   * speech ... then come up showing a notepad with my message on it."
   * Android never hands an app the power key, so the kiosk listens for
   * volume-up pressed TWICE within a moment (MainActivity.onKeyDown),
   * takes the picture with PixelCopy, and calls this with it. */
  /* 2026-09-15, #1148: THE SECOND ARGUMENT IS OPTIONAL AND THE OLD CALL
   * MUST KEEP WORKING. MainActivity.reportShot evaluates
   * `PineReport.fromKey("data:...")` with one argument and that road does
   * not change: no note, the pad opens as it always has.
   *
   * "Whenever I access the screen capture to follow report, I also want to
   *  be able to scrub between the last five seconds of the broadcast to
   *  find the right frame."
   *
   * When the annotator's scrub strip has been used, hot-corners.js passes
   * `note` as the second argument - "(the frame from 2.4s before the
   * capture)" - and it becomes the first line of the report body, so the
   * inbox item says which frame the picture actually is. */
  function fromKey(dataUrl, note) {
    try {
      var flash = document.createElement('div');
      flash.setAttribute('style', 'position:fixed;inset:0;background:#fff;opacity:.92;z-index:2147483045;pointer-events:none;transition:opacity .45s ease-out');
      document.body.appendChild(flash);
      setTimeout(function () { flash.style.opacity = '0'; }, 30);
      setTimeout(function () { if (flash.parentNode) flash.parentNode.removeChild(flash); }, 520);
    } catch (e) { /* the pad still opens */ }
    reportOpen('', String(dataUrl || ''), true, String(note || ''));
  }
  root.PineReport = {
    fromKey: fromKey,
    open: function (image, note) { reportOpen('', image || '', false, String(note || '')); }
  };

  async function act(text) {
    /* 2026-09-14: the pad first. A capture takes the sentence as text;
     * a request for a report opens the pad; neither reaches the model. */
    if (capture) {
      var take = capture;
      capture = null;
      setState(IDLE);
      if (!fieldCapture) announce('Heard: "' + text + '"');
      try { take(text); } catch (err) { /* the pad still stands */ }
      release(400);
      return;
    }
    if (wantsReport(text)) {
      setState(IDLE);
      announce('A Pine report - dictate it, then send it.');
      reportOpen(text);
      release(400);
      return;
    }
    setState(THINKING);
    var telemetry = el('pineTalkTelemetry');
    if (telemetry) telemetry.querySelector('[data-talk-phase]').textContent = 'Processing';
    /* Tell him it understood BEFORE the thinking starts. The answer can
     * take seconds; being told you were heard should not wait for it. */
    announce('Heard: "' + text + '"');

    /* AND SHOW IT BEING UNDERSTOOD. The cloud that was reacting to the
     * voice now flies into the shape of the words it turned into - so the
     * confirmation is the same object that was listening, not a caption
     * that appears beside it. It holds while the station thinks, which is
     * exactly when the operator is reading it. */
    sizeScene();
    /* SHOW HIM WHAT IT HEARD, AND HOLD IT THERE, BEFORE ACTING.
     *
     * "I want them to become a transcript of what I'm saying, displaying
     * it for a moment before going away and executing the command."
     *
     * The order matters and it was wrong: the words were assembled and the
     * request was sent in the same breath, so on a fast answer the
     * transcript was on screen for less than a second before the reply
     * replaced it. Now the cloud spells the sentence, holds it long enough
     * to be read, and only then does the command go.
     *
     * The hold is not free - it is a second of latency on every spoken
     * command - and it is spent deliberately: this is the moment the
     * operator finds out whether he was heard correctly, which is worth
     * more than a second saved on a request that was misheard anyway. */
    try {
      var made = await startScene();
      if (made && made.assemble) {
        try { made.assemble(text); } catch (err) { /* a cloud is not the point */ }
        await rest(HOLD_MS);
      }
    } catch (err) { /* the transcript is a courtesy; never block on it */ }

    try {
      /* NO `model` FIELD. It is passed straight through to Ollama, and a
       * name that is not a loaded model comes back as
       *     {"error":"model 'pine-box' not found"}
       * - which is what happened when this sent an invented one. Omitted,
       * the station uses its own (measured: gemma4:e2b), which is the
       * right answer anyway: the terminal should not be choosing the
       * station's brain. */
      var done = await api().post('/v1/chat/completions', {
        messages: [{role: 'user', content: text}]
      });
      var said = '';
      var which = '';
      try {
        var choice = (done && done.choices && done.choices[0]) || {};
        said = String((choice.message && choice.message.content) || '').trim();
        which = doorOf(done);
      } catch (err) { /* an odd shape is not a failure to act */ }

      setState(IDLE);
      announce('"' + text + '"' + (said ? '  ·  ' + said : '  ·  sent.')
        + (which ? '  [' + which + ']' : ''));
      if (said) speak(said);
      /* Hold the words up while the answer plays, then let the cloud go.
       * 9 seconds covers a spoken reply; speak() shortens it on `ended`. */
      release(said ? 9000 : 2600);
    } catch (err) {
      setState(IDLE);
      announce('Heard "' + text + '" but the station refused it: '
        + ((err && err.message) || err), true);
      release(3000);
    }
  }

  /* Let the letters go back to being a cloud, and stop the scene. */
  /* Long enough to read a short sentence aloud in your head. */
  var HOLD_MS = 1500;
  function rest(ms) {
    return new Promise(function (done) { setTimeout(done, ms); });
  }

  var releasing = 0;
  function release(after) {
    clearTimeout(releasing);
    releasing = setTimeout(function () {
      if (scene && scene.disperse) { try { scene.disperse(); } catch (e) { /* gone */ } }
      setTimeout(stopScene, 1400);
    }, Math.max(400, Number(after) || 1200));
  }

  /* WHICH DOOR ANSWERED.
   *
   * `spark_agent` is not one field. Some roads name themselves outright
   * (station_intent, dj_wake, dj_request); the general answer instead
   * carries a row of booleans - image_requested, web_search_used,
   * memory_used and so on. An earlier version took Object.keys(mark)[0]
   * and so labelled every general answer "web_search_used", including the
   * ones where it was false. Naming the flags that are actually TRUE is
   * both honest and more useful. */
  var DOORS = {
    image_requested: 'made an image',
    web_search_used: 'searched the web',
    game_lookup_used: 'looked it up',
    from_library: 'from the library',
    system_status_used: 'read the system',
    openwebui_used: 'asked OpenWebUI',
    memory_saved: 'remembered it',
    memory_used: 'used memory'
  };

  function doorOf(done) {
    var mark = (done && done.spark_agent) || {};
    var named = mark.route || mark.door || mark.kind;
    if (named) return String(named);
    var on = [];
    Object.keys(DOORS).forEach(function (key) {
      if (mark[key]) on.push(DOORS[key]);
    });
    return on.join(', ');
  }

  /* SAY IT OUT LOUD, in the station's own voice.
   *
   * /v1/audio/speech (app.py:84272) is the station's OpenAI-compatible TTS
   * over its whole voice bench, and it answers with audio bytes rather
   * than JSON - so it is fetched, not asked for through the bridge, the
   * same way the clip is posted. The page is the station's own panel and
   * therefore same-origin, and the panel's SERVER_KEY is in scope.
   *
   * A failure here is not a failure of the command: the command already
   * ran. So it is reported quietly and the text stays on screen. */
  /* THE BEARER, AND WHY IT IS NOT JUST A GLOBAL.
   *
   * This read only `window.SERVER_KEY`, on the reasoning that the page IS
   * the station's panel so the key must be in scope. Measured on the
   * tablet: `typeof window.SERVER_KEY` is "undefined". The kiosk's WebView
   * does not run the panel's key-defining script in a world this code can
   * see, so every reply was silently dropped - speak() returned at its
   * first line and the operator got no answer at all, which is exactly the
   * fault reported as "the voice request didn't make it through".
   *
   * The bridge has the key: it is in the terminal's own config, put there
   * by discoverKey at provisioning time. So the global is tried first (the
   * desktop panel really does define it) and the bridge is the fallback
   * that makes this work on the tablet. Cached, because a reply should not
   * cost a config read every time. */
  var cachedKey = '';
  var cachedBase = '';                                    /* [#1224] */
  /* #1360: WHERE THE STATION IS, FOR THE TWO ROADS THAT BYPASS THE
   * BRIDGE.
   *
   * "Failed to fetch", in the red box over the dot, on the desktop.
   *
   * Both of the fetches below were written with a bare '/api/...' path,
   * and on the tablet that is correct - the panel IS served by the
   * station there, so a relative URL follows the host it was opened on.
   * In the Electron chrome the document is file://, so the same string
   * resolves to file:///api/listen/transcribe, which is a path on the
   * disk, is not there, and fails with exactly that message.
   *
   * So the orb could hear you on the desktop and could never send what
   * it heard, and could never speak its answer. Everything else in this
   * file goes through pineDesktop, which builds an absolute URL out in
   * the shell - which is why only these two broke, and why it broke
   * silently on the one surface nobody tests the tablet on.
   *
   * Same shape as slideshow-source's base() (#1348): empty where the
   * document is already served over http, so nothing about the tablet
   * changes.
   */
  function where() {
    try {
      if (root.location && /^https?:$/.test(root.location.protocol)) {
        return '';
      }
      if (root.pineStationBase) return root.pineStationBase();
      /* [#1224] `pineStationBase` IS DEFINED NOWHERE - grep the shell:
         only the two calls exist - so #1360's road always fell through to
         the loopback below, and on this desk nothing listens there.  The
         config knows (baseUrl http://10.89.1.246:8096); serverKey()'s
         readConfig() caches it here. */
      if (cachedBase) return cachedBase;
    } catch (err) { /* fall through to the last resort */ }
    return cachedBase || 'http://127.0.0.1:8096';
  }

  function serverKey() {
    if (cachedKey) return Promise.resolve(cachedKey);
    if (typeof root.SERVER_KEY === 'string' && root.SERVER_KEY) {
      cachedKey = root.SERVER_KEY;
      return Promise.resolve(cachedKey);
    }
    var bridge = root.pineDesktop;
    if (!bridge || typeof bridge.readConfig !== 'function') {
      return Promise.resolve('');
    }
    return bridge.readConfig().then(function (cfg) {
      cachedKey = String((cfg && (cfg.apiKey || cfg.api_key)) || '');
      /* [#1224] and where the station actually is - see where(). */
      cachedBase = String((cfg && (cfg.baseUrl || cfg.base_url)) || '')
        .replace(/\/+$/, '');
      return cachedKey;
    }, function () { return ''; });
  }

  /* THE SAME VOICE THE OTHER DEVICES REPLY IN.
   *
   * "Make sure that the voice used for the reply on the tablet is the same
   * one that's used for all the devices."
   *
   * It was not. /v1/audio/speech with no `voice` falls through to the
   * station's default engine, and that is a different voice from the one
   * the Nabu and the Pine Box answer in - measured, same sentence, 25644
   * bytes against 20002.
   *
   * WHERE THIS VALUE COMES FROM. The other devices do not synthesise
   * through this station at all: Home Assistant speaks the string that
   * /v1/chat/completions returns, using whichever pipeline is wired to the
   * station's conversation agent. Read off HA's own
   * .storage/assist_pipeline.pipelines:
   *
   *     DGX Spark | tts: tts.piper | voice: en_US-libritts-high
   *               | conversation: conversation.spark_agent
   *
   * That is the pipeline the station answers through, so that is the voice
   * the operator hears everywhere else, and it is what the tablet asks for
   * here.
   *
   * IT IS OVERRIDABLE WITHOUT A REBUILD. If the pipeline's voice is ever
   * changed in Home Assistant, put the new one in the terminal's config as
   * `replyVoice` and this follows it - a constant in an APK is a poor
   * place to keep a setting that lives in another program. */
  var REPLY_VOICE = 'piper:en_US-libritts-high';
  var replyVoice = null;

  function voiceForReply() {
    if (replyVoice !== null) return Promise.resolve(replyVoice);
    var bridge = root.pineDesktop;
    if (!bridge || typeof bridge.readConfig !== 'function') {
      replyVoice = REPLY_VOICE;
      return Promise.resolve(replyVoice);
    }
    return bridge.readConfig().then(function (cfg) {
      replyVoice = String((cfg && (cfg.replyVoice || cfg.reply_voice)) || '')
        || REPLY_VOICE;
      return replyVoice;
    }, function () {
      replyVoice = REPLY_VOICE;
      return replyVoice;
    });
  }

  function speak(words) {
    serverKey().then(function (key) {
      if (!key) {
        /* Say so rather than being silently mute: an answer the operator
         * can read is still an answer, and knowing WHY it did not speak is
         * what lets it be fixed. */
        announce('(no station key on this terminal, so the reply is text '
          + 'only)', true);
        return;
      }
      voiceForReply().then(function (voice) { sayIt(words, key, voice); });
    });
  }

  function sayIt(words, key, voice) {
    /* [#1224] Same two faults as the clip: file:// has no road to the
       station that CORS will allow, and where() named a loopback with
       nothing on it.  Out through the shell where there is one. */
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge.speechSay === 'function') {
      Promise.resolve(bridge.speechSay({
        input: String(words).slice(0, 600),
        voice: String(voice || REPLY_VOICE),
        format: 'mp3'
      })).then(function (got) {
        if (!got || !got.ok || !got.bytes) {
          throw new Error(String((got && got.why) || 'no audio came back'));
        }
        playReply(new Blob([got.bytes],
                           {type: String(got.type || 'audio/mpeg')}));
      }, function () {
        /* Said nothing, showed everything. The words are already up. */
        duck(false);
      });
      return;
    }
    var headers = {'Content-Type': 'application/json'};
    headers.Authorization = 'Bearer ' + key;
    fetch(where() + '/v1/audio/speech', {   /* #1360 */
      method: 'POST', headers: headers,
      body: JSON.stringify({
        input: String(words).slice(0, 600),
        voice: String(voice || REPLY_VOICE),
        response_format: 'mp3'
      })
    }).then(function (res) {
      if (!res.ok) throw new Error('the voice bench said ' + res.status);
      return res.blob();
    }).then(function (blob) {
      playReply(blob);                                    /* [#1224] */
    }, function () {
      /* Said nothing, showed everything. The words are already on screen. */
      duck(false);
    });
  }

  /* POST the raw clip.
   *
   * The bridge speaks JSON, and this is bytes - so it goes by fetch. The
   * page IS the station's own panel, so it is same-origin and the panel's
   * own SERVER_KEY is in scope; /api/listen/transcribe is require_auth, so
   * the bearer is not optional. Where the key is not in scope (the desktop
   * shell loads from file://) the bridge is asked for one. */
  function postAudio(wav) {
    var url = '/api/listen/transcribe';
    var bytes = (wav instanceof ArrayBuffer) ? new Uint8Array(wav) : wav;
    /* [#1224] THE SHELL CARRIES IT, WHERE THERE IS A SHELL.
     *
     * The desk renderer is file://.  A POST from it with Authorization
     * and Content-Type is preflighted, and the station answers OPTIONS
     * with 405 and sends no Access-Control-Allow-Origin on anything, so
     * this fetch could never have completed however right the address
     * was.  In the main process there is no origin and no preflight, and
     * the key is already there.  The fetch below stays for the tablet,
     * where the page IS the station's own panel and is same-origin. */
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge.listenTranscribe === 'function') {
      return Promise.resolve(bridge.listenTranscribe(bytes))
        .then(function (got) {
          if (!got || !got.ok) {
            throw new Error(String((got && got.why)
              || 'the desk could not reach the station'));
          }
          return got;
        });
    }
    return serverKey().then(function (key) {
      if (!key) {
        throw new Error('no station key on this terminal to authorise the clip');
      }
      return fetch(where() + url, {          /* #1360 */
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + key,
          'Content-Type': 'application/octet-stream'
        },
        body: new Blob([bytes], {type: 'audio/wav'})      /* [#1224] */
      });
    }).then(function (res) {
      return res.json().then(function (body) {
        if (!res.ok) throw new Error(String(body.detail || res.status));
        return body;
      });
    });
  }

  /* #1355: a device list that changed under a pinned choice is worth
   * knowing about before the next press, not during it. */
  try {
    if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
      navigator.mediaDevices.addEventListener('devicechange', function () {
        var pin = micPin();
        if (!pin) return;
        mics().then(function (list) {
          var still = list.some(function (m) { return m.id === pin; });
          if (still) return;
          useMic('');
          announce('That microphone has gone - back to the system '
            + 'default');
        }).catch(function () { /* asked again on the next press */ });
      });
    }
  } catch (err) { /* not every engine has this */ }

  root.PineTalkDot = {
    mics: mics,
    useMic: useMic,
    micPin: micPin,
    mount: mount, listen: listen, finish: finish, duck: duck,
    /* `act` is the door for a sentence that arrived some other way - a
     * wake word, a typed command, or a test - and it deliberately does
     * everything the spoken road does from the transcript onwards:
     * assemble, ask, answer, speak. Anything that bypassed it would be a
     * second, quietly different experience. */
    act: act,
    cancel: cancel,
    cancelCapture: function () {
      capture = null;
      if (state === LISTENING) cancel();
    },
    /* 2026-09-14: lend the ear - the next heard sentence goes to `fn`
       instead of the model (the caution sheet dictates its reason
       this way). Starts listening at once. */
    captureNext: function (fn) {
      capture = typeof fn === 'function' ? fn : null;
      try {
        var pending = listen();
        if (pending && typeof pending['catch'] === 'function') {
          return pending['catch'](function (err) { capture = null; throw err; });
        }
        return pending;
      } catch (e) { capture = null; throw e; }
    },
    /* 2026-09-14: the report pad, for a button or a test. */
    report: reportOpen,
    state: function () { return state; }
  };
  /* Field dictation stays in the field, including fields created by later
   * popups. The overlay avoids changing the layout of established forms. */
  if (root.document && root.document.addEventListener) {
    var fieldButtons = new Map();
    var fieldLayer = root.document.createElement('div');
    fieldLayer.className = 'pine-field-mics';
    var micBusy = false;
    var micMonitor = 0;
    var finishWhenReady = false;
    var scanQueued = false;
    var placeQueued = false;
    var placeHitTest = false;
    var visibleFields = new Set();
    var fieldObserver = null;
    function nextFrame(job) {
      if (typeof root.requestAnimationFrame === 'function') return root.requestAnimationFrame(job);
      if (typeof root.setTimeout === 'function') return root.setTimeout(job, 0);
      job();
      return 0;
    }
    function afterDelay(job, delay) {
      if (typeof root.setTimeout === 'function') return root.setTimeout(job, delay);
      if (typeof setTimeout === 'function') return setTimeout(job, delay);
      job();
      return 0;
    }
    function cancelDelay(timer) {
      if (typeof root.clearTimeout === 'function') root.clearTimeout(timer);
      else if (typeof clearTimeout === 'function') clearTimeout(timer);
    }
    function textField(node) {
      if (!node || node.disabled || node.readOnly) return false;
      if (node.tagName === 'TEXTAREA') return true;
      if (node.tagName === 'INPUT') return /^(text|search|url|email|tel|number)$/.test(node.type || 'text');
      return node.isContentEditable === true && !node.parentElement?.isContentEditable;
    }
    function viewport() {
      return root.visualViewport || {width: root.innerWidth, height: root.innerHeight,
        offsetLeft: 0, offsetTop: 0};
    }
    function setMicHidden(button, hidden) {
      if (button.hidden !== hidden) button.hidden = hidden;
    }
    function placeMic(field, button, hitTest) {
      if (!field.isConnected || !textField(field)) { setMicHidden(button, true); return; }
      var rect = field.getBoundingClientRect();
      var view = viewport();
      var size = Math.min(32, Math.max(0, rect.height - 4), Math.max(0, rect.width - 4));
      var x = rect.right - size - 3;
      var y = rect.top + Math.max(2, (rect.height - size) / 2);
      setMicHidden(button, size < 22 || rect.width < 48 || rect.right <= 0
        || rect.left >= view.width || rect.bottom <= 0 || rect.top >= view.height
        || !!(field.closest && field.closest('[hidden], [aria-hidden="true"]')));
      /* An elementFromPoint walks the whole document. Do it on first reveal
         and focus, not after every live-feed DOM change. The observer below
         keeps the ordinary placement set to fields that are actually visible. */
      if (hitTest && !button.hidden && root.document.elementFromPoint) {
        button.style.pointerEvents = 'none';
        var hit = root.document.elementFromPoint(
          Math.max(rect.left + 2, Math.min(rect.right - 2, rect.left + rect.width / 2)),
          Math.max(rect.top + 2, Math.min(rect.bottom - 2, rect.top + rect.height / 2)));
        button.style.pointerEvents = '';
        if (hit !== field && !(field.contains && field.contains(hit))) button.hidden = true;
      }
      if (button.hidden) return;
      button.style.width = size + 'px';
      button.style.height = size + 'px';
      button.style.left = x + 'px';
      button.style.top = y + 'px';
    }
    function placeTelemetry() {
      var telemetry = el('pineTalkTelemetry');
      if (!telemetry || !fieldCapture || !fieldCapture.isConnected) return;
      var rect = fieldCapture.getBoundingClientRect();
      var view = viewport();
      var width = Math.min(540, Math.max(230, view.width - 16));
      var belowSpace = Math.max(0, view.height - rect.bottom - 5);
      var aboveSpace = Math.max(0, rect.top - 5);
      var below = belowSpace >= 58 || belowSpace >= aboveSpace;
      var height = Math.min(72, Math.max(50, below ? belowSpace : aboveSpace));
      var top = below ? rect.bottom + 2 : Math.max(2, rect.top - height - 2);
      telemetry.style.left = Math.max(8, Math.min(view.width - width - 8, rect.left)) + 'px';
      telemetry.style.top = top + 'px';
      telemetry.style.width = width + 'px';
      telemetry.style.height = height + 'px';
    }
    function placeAll(hitTest) {
      var fields = fieldObserver ? visibleFields : fieldButtons;
      fields.forEach(function (value, key) {
        var field = fieldObserver ? value : key;
        var button = fieldObserver ? fieldButtons.get(field) : value;
        if (!field || !button || !field.isConnected) {
          if (button) button.remove();
          fieldButtons.delete(field);
          visibleFields.delete(field);
          return;
        }
        placeMic(field, button, hitTest);
      });
      placeTelemetry();
    }
    function queuePlace(hitTest) {
      placeHitTest = placeHitTest || !!hitTest;
      if (placeQueued) return;
      placeQueued = true;
      nextFrame(function () {
        var probe = placeHitTest;
        placeQueued = false;
        placeHitTest = false;
        placeAll(probe);
      });
    }
    function queueScan() {
      if (scanQueued) return;
      scanQueued = true;
      nextFrame(function () { scanQueued = false; scan(); });
    }
    function scan() {
      var fields = root.document.querySelectorAll
        ? root.document.querySelectorAll('input, textarea, [contenteditable="true"]') : [];
      var added = false;
      for (var i = 0; i < fields.length; i += 1) {
        var field = fields[i];
        if (!textField(field) || fieldButtons.has(field)) continue;
        var button = makeMic(field);
        fieldButtons.set(field, button);
        added = true;
        if (fieldObserver) fieldObserver.observe(field);
      }
      if (added && !fieldObserver) queuePlace(true);
    }
    function reserveSpace(field) {
      if (!field.style || !field.style.setProperty) return;
      var style = root.getComputedStyle ? root.getComputedStyle(field) : null;
      var right = style ? parseFloat(style.paddingRight) || 0 : 0;
      field.style.setProperty('padding-right', (right + 36) + 'px', 'important');
    }
    function appendWords(field, words) {
      if (!field || !field.isConnected || !words) return;
      var stillFocused = !root.document || root.document.activeElement === field;
      var old = field.isContentEditable ? field.textContent : field.value;
      var joined = old + (old && !/\s$/.test(old) ? ' ' : '') + words;
      if (field.isContentEditable) field.textContent = joined;
      else field.value = joined;
      field.dispatchEvent(new Event('input', {bubbles: true}));
      if (stillFocused) field.focus();
      if (stillFocused && field.setSelectionRange) field.setSelectionRange(joined.length, joined.length);
    }
    function clearMic() {
      root.clearInterval(micMonitor);
      micMonitor = 0;
      micBusy = false;
      finishWhenReady = false;
      fieldButtons.forEach(function (button) { button.setAttribute('aria-pressed', 'false'); });
      fieldCapture = null;
    }
    function startMic(field, button) {
      if (micBusy || state !== IDLE || !textField(field)) return;
      micBusy = true;
      fieldCapture = field;
      button.setAttribute('aria-pressed', 'true');
      if (root.document && typeof root.document.getElementById === 'function') {
        mount();
        placeTelemetry();
      }
      var started = Date.now();
      root.clearInterval(micMonitor);
      micMonitor = root.setInterval(function () {
        if (Date.now() - started < 3000 || root.PineTalkDot.state() !== IDLE) return;
        clearMic();
      }, 500);
      Promise.resolve(root.PineTalkDot.captureNext(function (words) {
        appendWords(field, String(words || '').trim());
        clearMic();
      })).then(function () {
        if (finishWhenReady) root.PineTalkDot.finish();
      }).catch(clearMic);
    }
    function stopMic() {
      if (!micBusy) return;
      if (root.PineTalkDot.state() === LISTENING) root.PineTalkDot.finish();
      else finishWhenReady = true;
    }
    function makeMic(field) {
      reserveSpace(field);
      var button = root.document.createElement('button');
      var pressedAt = 0;
      var wasListening = false;
      var holdTimer = 0;
      var held = false;
      button.type = 'button';
      button.className = 'pine-field-mic';
      button.hidden = true;
      button.title = 'Tap to dictate or stop; hold to talk and release to transcribe';
      button.setAttribute('aria-label', button.title);
      button.setAttribute('aria-pressed', 'false');
      button.innerHTML = (typeof root.pineIcon === 'function'
        ? root.pineIcon('c:microphone', 'Dictate') : '') || '&#127908;';
      button.addEventListener('pointerdown', function (event) {
        event.preventDefault();
        pressedAt = Date.now();
        wasListening = micBusy;
        held = false;
        if (micBusy) stopMic(); else startMic(field, button);
        cancelDelay(holdTimer);
        holdTimer = afterDelay(function () {
          holdTimer = 0;
          held = true;
        }, 450);
        try { button.setPointerCapture(event.pointerId); } catch (err) { /* released */ }
      });
      button.addEventListener('pointerup', function () {
        if (holdTimer) cancelDelay(holdTimer);
        holdTimer = 0;
        if (pressedAt && !wasListening && (held || Date.now() - pressedAt >= 450)) stopMic();
        pressedAt = 0;
        held = false;
      });
      button.addEventListener('pointercancel', function () {
        if (holdTimer) cancelDelay(holdTimer);
        holdTimer = 0;
        if (pressedAt && !wasListening) stopMic();
        pressedAt = 0;
        held = false;
      });
      button.addEventListener('click', function (event) {
        if (event.detail !== 0) return;
        if (micBusy) stopMic(); else startMic(field, button);
      });
      if (fieldLayer.appendChild) fieldLayer.appendChild(button);
      return button;
    }
    (root.document.body || root.document.documentElement).appendChild(fieldLayer);
    if (typeof root.IntersectionObserver === 'function') {
      fieldObserver = new root.IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          var field = entry.target;
          var button = fieldButtons.get(field);
          if (!button) return;
          if (entry.isIntersecting) {
            visibleFields.add(field);
            placeMic(field, button, true);
          } else {
            visibleFields.delete(field);
            setMicHidden(button, true);
          }
        });
        placeTelemetry();
      });
    }
    root.document.addEventListener('focusin', function (event) {
      var field = event.target;
      if (!textField(field)) return;
      var button = fieldButtons.get(field);
      if (!button) {
        button = makeMic(field);
        fieldButtons.set(field, button);
        if (fieldObserver) fieldObserver.observe(field);
      }
      visibleFields.add(field);
      placeMic(field, button, true);
      queueScan();
    });
    root.addEventListener('resize', queuePlace);
    root.addEventListener('scroll', queuePlace, true);
    if (root.visualViewport) {
      root.visualViewport.addEventListener('resize', queuePlace);
      root.visualViewport.addEventListener('scroll', queuePlace);
    }
    if (typeof MutationObserver !== 'undefined') {
      new MutationObserver(function (records) {
        for (var i = 0; i < records.length; i += 1) {
          var nodes = records[i].addedNodes || [];
          for (var j = 0; j < nodes.length; j += 1) {
            var node = nodes[j];
            if (node && node.nodeType === 1 && (textField(node)
                || (node.querySelector && node.querySelector('input, textarea, [contenteditable="true"]')))) {
              queueScan();
              return;
            }
          }
        }
      }).observe(root.document.body || root.document.documentElement,
        {childList: true, subtree: true});
    }
    scan();
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineTalkDot;
})(typeof window !== 'undefined' ? window : globalThis);
