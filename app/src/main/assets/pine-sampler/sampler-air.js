/* THE LAST TWO MINUTES OF THE BROADCAST, KEPT, AND THE MUTE THAT GOES WITH IT.
 *
 * Three of the operator's asks land here:
 *
 *   "Allow me to tap and hold on a pad that is idle or blank to sample the
 *    current playing broadcast to the pad."
 *   "Whenever I sample the broadcast to the sampler, capture it at the current
 *    levels and the current audio. Allow me to grab from previous seconds that
 *    the broadcast was playing and capture that."
 *   "Put a toggle in the sampler that makes it where whenever I tap on a sample
 *    pad, the broadcast is muted while it is playing the sample pad."
 *
 * WHY A RING BUFFER AND NOT A SERVER CALL. "Previous seconds of the broadcast"
 * is an arbitrary window, and the station has exactly one road that cuts one -
 * POST /api/radio-cache/span - which is full-auth, serialised, and takes
 * MINUTES. That is a background job; it is not a thing a finger waits for. So
 * the page keeps the last two minutes of what it actually played, and a grab is
 * a copy out of memory: instant, and by construction the real thing.
 *
 * "AT THE CURRENT LEVELS AND THE CURRENT AUDIO" IS THE DESIGN, NOT A DETAIL.
 * The tap sits AFTER the desk - after djGainMusic/djGainVoice/djDuck and after
 * the terminals table has moved them - so what lands on the pad is what came
 * out of the speaker, mix and all. Sampling the source files instead would be
 * easier and would be a different recording.
 *
 * HOW EVERY PLAYER IS FOUND, including the ones nothing can see. The panel
 * creates players with `new Audio(url)` all over renderer.js, and those never
 * enter the DOM - querySelectorAll cannot find them, which is half of why
 * detached players have leaked past this project before (#1147). So this
 * wraps HTMLMediaElement.prototype.play instead: anything that ever makes a
 * sound announces itself by definition. terminal-audio-client.js already
 * clamps the volume setter the same way, "for every element in the page,
 * including ones this file has never heard of".
 *
 * IT TAPS THE PANEL'S OWN GRAPH, AND HAD TO LEARN TO. The first version of
 * this called createMediaElementSource on each player itself. Measured on the
 * tablet with music genuinely playing, that produced eight seconds of digital
 * silence - peak 0.0037, rms 0.00118 - because the panel HAS ALREADY DONE IT:
 * `audioScope(player)` builds
 *
 *     source -> analyser -> [gain] -> destination
 *
 * in its own context, `window.pineAudioCtx`. A second createMediaElementSource
 * on the same element throws, and the element was left untapped; worse, the
 * two contexts are different objects and Web Audio REFUSES to connect nodes
 * across contexts, so there was no way to route one into the other.
 *
 * So the tap now asks `audioScope` for the player it wants and connects the
 * analyser the panel already made. One per player, memoised by the panel in a
 * WeakMap, so it cannot be taken twice and cannot double-count.
 *
 * WHAT "THE CURRENT LEVELS" MEANS, EXACTLY. The analyser sits after the
 * element (so its own `volume` is in the recording - the music element was
 * measured at 0.34) and before the desk gain that djApplyGain inserts for
 * boost. A voice monitored at 160% is therefore sampled at unity rather than
 * clipped, which is the right way round for a sampler: the monitoring level
 * is not part of the recording.
 *
 * WHERE IT CANNOT WORK, AND WHY IT SAYS SO. createMediaElementSource on a
 * CROSS-ORIGIN element without CORS yields silence - the graph is tainted, and
 * because tapping moves the element's output into the graph, tapping one would
 * not merely fail to record, it would MUTE THE BROADCAST. The station sets no
 * CORS headers (there is no CORSMiddleware in app.py). So an element is tapped
 * only when it is same-origin with the page, which is true on the tablet - the
 * views are injected into the station's own panel at :8096 - and false in the
 * desktop renderer, which runs from file://. There it reports honestly rather
 * than recording silence. A feature that quietly captures nothing is worse than
 * one that says it cannot.
 */
(function (root) {
  'use strict';

  /* Two minutes. Mono float at 48k is 23 MB, which the tablet holds without
   * complaint; the operator asked for "previous seconds", and two minutes is
   * comfortably more than anyone scrubs back through by hand. */
  var HISTORY_S = 120;
  /* See the two-rings note above: long enough to reach a line you just
   * heard, short enough not to cost a second 23 MB. */
  var VOICE_HISTORY_S = 60;

  /* AN AUDIOWORKLET WHERE THE PAGE ALLOWS ONE, AND THE OLD ROAD WHERE IT
   * DOES NOT.
   *
   * This used to be a ScriptProcessor on purpose, with a real reason: "a
   * worklet needs a module fetched from a URL, and these views are injected
   * into a page whose origin and CSP this file does not control". The answer
   * to that is a blob: URL, which needs no origin and no server - and where
   * a CSP refuses even that, the ScriptProcessor is still here and still
   * runs.
   *
   * The reason it had to move is measured rather than argued. The drop
   * counter below, read over twenty seconds on a live tablet:
   *
   *     29 gaps, 3.429 seconds of audio lost - seventeen per cent
   *
   * A ScriptProcessor runs on the MAIN thread, and a blocked main thread
   * does not delay a buffer, it loses it. The ring then writes the next
   * buffer hard against the last, so the waveform steps - and THAT is the
   * "static and noise" in a captured broadcast. Nothing was ever added to
   * the signal; silence was cut out of it, hundreds of times a minute, on a
   * tablet running the station, eleven canvases, a screen encoder and a
   * camera at a load average of 22. */
  var BLOCK = 4096;

  /* WHAT THE CAPTURE MISSES.
   *
   * A ScriptProcessor runs on the main thread, and a blocked main thread does
   * not delay a buffer, it loses it. playbackTime is the AUDIO clock, so the
   * distance between two callbacks is exactly how much audio should have
   * arrived; anything beyond one buffer is what was dropped on the floor. */
  var gaps = 0;             /* callbacks that came late enough to lose audio */
  var gapSeconds = 0;       /* how much audio went missing in total          */
  var lastHeard = 0;        /* the previous callback's playbackTime          */

  /* TWO RINGS, BECAUSE "THE AIR" MEANS TWO DIFFERENT THINGS.
   *
   * "The samples I am capturing from the air appear to be double playing and
   *  overlap. I think it is recording multiple clips on top of each other."
   *
   * Nothing is recorded twice - that was measured three ways: a known probe
   * came back as 440 Hz, silence, 880 Hz in order at rms 0.355 for a 0.5
   * sine, which is EXACTLY unity gain and so not summed twice; the load path
   * takes a fresh token and replaces; and one tap produces exactly one voice.
   *
   * What is actually happening is that the MIX contains several things at
   * once. This station routinely has three or four players sounding
   * together - a record underneath, a line over it, a sting across the top -
   * and a tap placed after the desk faithfully records all of them. That is
   * right for "keep what I just heard" and wrong for "keep what they said",
   * and the operator wanted the second one.
   *
   * So the voices are kept SEPARATELY, from the same analysers minus the
   * record. A grab off a pad takes that one; the mix is still there and the
   * grab window can still offer it.
   *
   * THE VOICE RING IS SHORTER - sixty seconds against the mix's two minutes.
   * You reach for a line you just heard; nobody scrubs back two minutes for
   * one. And a second full-length ring is another 23 MB on a 4 GB tablet for
   * history that would never be read. */
  var ctx = null;
  var capture = null;       /* the ScriptProcessor doing the copying   */
  var voiceCapture = null;  /* the same, for everything but the record */
  var voiceRing = null;
  var voiceWrite = 0;
  var voiceFilled = 0;
  var sink = null;          /* a silent destination for it to feed     */
  var ring = null;          /* Float32Array, HISTORY_S * sampleRate    */
  var write = 0;            /* next write index                        */
  var filled = 0;           /* how much of the ring is real            */
  var loudest = 0;          /* peak since the last level() read        */

  var taps = new WeakMap(); /* element -> {joined}                     */
  /* A SPECTRUM OF THE VOICES ONLY, for the feed's playing row.
   *
   * "For the actively playing sound effect, put an audio spectrogram showing
   * the actively playing sound effect so we know exactly which clip is being
   * played."
   *
   * Fed by every player EXCEPT the record, so the bars are the clip and not
   * the music under it - which is the whole point of putting them on the row
   * that says Playing. */
  var speechAnalyser = null;
  var speechBins = null;
  /* Declared up here because tap() reads them: a player that starts while
   * the broadcast is ducked has to be caught on arrival. */
  var ducked = false;
  var silenced = [];
  /* Whether the pad solo took the record's gain down as well as muting it. */
  var mutedMusic = false;
  var known = [];           /* every element we have seen play         */
  var reason = 'not started';
  var live = false;

  /* ------------------------------------------------------------ the context */

  /* THE BROADCAST'S CONTEXT, NOT THE SAMPLER'S.
   *
   * This must be the context the broadcast graph lives in, because nodes
   * cannot be connected across contexts - that is the whole reason the first
   * version of this recorded silence. The panel calls its own
   * `window.pineAudioCtx`.
   *
   * Keeping it separate from the ENGINE's context is also what stops the
   * sampler recording itself: the pads are BufferSources in the engine's
   * context and can never reach a capture node in this one, so holding a pad
   * to sample the air cannot capture the pad that is playing. */
  function context() {
    if (ctx) return ctx;
    if (root.pineAudioCtx) { ctx = root.pineAudioCtx; return ctx; }
    /* No panel graph here - the desktop renderer, or the panel has not made
     * a sound yet. One of our own, which audioScope will then adopt because
     * it looks for window.pineAudioCtx before creating one. */
    var Ctor = root.AudioContext || root.webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
    if (!root.pineAudioCtx) root.pineAudioCtx = ctx;
    return ctx;
  }

  function wake() {
    var c = context();
    if (c && c.state === 'suspended') c.resume().catch(function () {});
  }

  /* ------------------------------------------------------------ the worklet */

  /* THE PROCESSOR, AS SOURCE. It is compiled from a blob: URL because these
   * views are injected into a page whose origin this file does not own.
   *
   * It does exactly what the ScriptProcessor did - fold stereo to mono - and
   * then gathers into a block before posting, so the main thread is woken
   * about a dozen times a second rather than four hundred. Crucially it
   * gathers in ITS OWN memory on the audio thread: a main thread that is busy
   * now makes the ring LATE, which is inaudible, instead of making the audio
   * MISSING, which is not. */
  var WORKLET_SOURCE = [
    'class PineTap extends AudioWorkletProcessor {',
    '  constructor(options) {',
    '    super();',
    '    this.size = (options && options.processorOptions',
    '      && options.processorOptions.size) || 4096;',
    '    this.held = new Float32Array(this.size);',
    '    this.at = 0;',
    '  }',
    '  process(inputs) {',
    '    const input = inputs[0];',
    '    if (!input || !input.length) return true;',
    '    const left = input[0];',
    '    const right = input.length > 1 ? input[1] : null;',
    '    if (!left) return true;',
    '    for (let i = 0; i < left.length; i += 1) {',
    '      this.held[this.at] = right ? (left[i] + right[i]) * 0.5 : left[i];',
    '      this.at += 1;',
    '      if (this.at === this.size) {',
    '        /* Transferred, not copied: the buffer leaves this thread and a',
    '           fresh one takes its place. */',
    '        const out = this.held;',
    '        this.held = new Float32Array(this.size);',
    '        this.at = 0;',
    '        this.port.postMessage(out, [out.buffer]);',
    '      }',
    '    }',
    '    return true;',
    '  }',
    '}',
    'registerProcessor("pine-tap", PineTap);'
  ].join('\n');

  var workletReady = null;      /* a promise, once, or null if refused */
  var workletWhy = '';

  function haveWorklet(c) {
    if (workletReady) return workletReady;
    if (typeof AudioWorkletNode !== 'function' || !c.audioWorklet) {
      workletWhy = 'this WebView has no AudioWorklet';
      workletReady = Promise.reject(new Error(workletWhy));
      workletReady.catch(function () {});
      return workletReady;
    }
    var url;
    try {
      url = URL.createObjectURL(new Blob([WORKLET_SOURCE],
        { type: 'text/javascript' }));
    } catch (err) {
      workletWhy = 'a blob URL could not be made: ' + err.message;
      workletReady = Promise.reject(new Error(workletWhy));
      workletReady.catch(function () {});
      return workletReady;
    }
    workletReady = c.audioWorklet.addModule(url).then(function () {
      try { URL.revokeObjectURL(url); } catch (err) { /* fine */ }
      return true;
    }).catch(function (err) {
      /* A page whose CSP refuses blob: scripts lands here, which is exactly
       * the case the old comment worried about. The ScriptProcessor below
       * still works; this is a fall back, not a failure. */
      workletWhy = 'the page refused the worklet module: ' + err.message;
      throw err;
    });
    return workletReady;
  }

  /** How the capture is actually running, for the diagnostics road. */
  var captureHow = 'starting';

  /* --------------------------------------------------------------- the ring */

  function ensureRing() {
    var c = context();
    if (!c || ring) return !!ring;
    ring = new Float32Array(Math.round(HISTORY_S * c.sampleRate));
    sink = c.createGain();
    sink.gain.value = 0;          /* it must hear, not speak */
    sink.connect(c.destination);
    /* THE WORKLET FIRST. It is asked for asynchronously, so the
     * ScriptProcessor below is wired up immediately and REPLACED when the
     * worklet is ready - a capture that is silent for the two hundred
     * milliseconds a module takes to compile is a capture that has lost the
     * two hundred milliseconds. */
    haveWorklet(c).then(function () {
      try {
        var tap = new AudioWorkletNode(c, 'pine-tap', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
          processorOptions: { size: BLOCK }
        });
        tap.port.onmessage = function (event) {
          var block = event.data;
          if (!block || !block.length) return;
          for (var i = 0; i < block.length; i += 1) {
            var v = block[i];
            ring[write] = v;
            write = write + 1 === ring.length ? 0 : write + 1;
            var a = v < 0 ? -v : v;
            if (a > loudest) loudest = a;
          }
          if (filled < ring.length) {
            filled = Math.min(ring.length, filled + block.length);
          }
        };
        /* The old node is taken out of the graph only once the new one is
         * in it, so nothing is deaf in between. */
        if (sink) tap.connect(sink);
        if (capture) {
          try { capture.disconnect(); } catch (err) { /* gone */ }
          capture.onaudioprocess = null;
        }
        capture = tap;
        captureHow = 'worklet';
      } catch (err) {
        captureHow = 'script processor (' + err.message + ')';
      }
    }).catch(function () {
      captureHow = 'script processor (' + workletWhy + ')';
    });

    capture = c.createScriptProcessor(BLOCK, 2, 1);
    capture.onaudioprocess = function (event) {
      var due = event.playbackTime;
      if (lastHeard) {
        var slip = due - lastHeard - (BLOCK / c.sampleRate);
        /* Half a buffer of slack: the clock is not exact and a drop is a
         * WHOLE buffer, so nothing borderline is counted. */
        if (slip > (BLOCK / c.sampleRate) * 0.5) {
          gaps += 1;
          gapSeconds += slip;
        }
      }
      lastHeard = due;
      var input = event.inputBuffer;
      var left = input.getChannelData(0);
      var right = input.numberOfChannels > 1 ? input.getChannelData(1) : null;
      var n = left.length;
      for (var i = 0; i < n; i += 1) {
        var v = right ? (left[i] + right[i]) * 0.5 : left[i];
        ring[write] = v;
        write = write + 1 === ring.length ? 0 : write + 1;
        var a = v < 0 ? -v : v;
        if (a > loudest) loudest = a;
      }
      if (filled < ring.length) filled = Math.min(ring.length, filled + n);
    };
    capture.connect(sink);

    /* The voices-only ring. Same shape, its own clock, fed in tap(). */
    voiceRing = new Float32Array(Math.round(VOICE_HISTORY_S * c.sampleRate));
    haveWorklet(c).then(function () {
      try {
        var tap = new AudioWorkletNode(c, 'pine-tap', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
          processorOptions: { size: BLOCK }
        });
        tap.port.onmessage = function (event) {
          var block = event.data;
          if (!block || !block.length) return;
          for (var i = 0; i < block.length; i += 1) {
            voiceRing[voiceWrite] = block[i];
            voiceWrite = voiceWrite + 1 === voiceRing.length ? 0 : voiceWrite + 1;
          }
          if (voiceFilled < voiceRing.length) {
            voiceFilled = Math.min(voiceRing.length, voiceFilled + block.length);
          }
        };
        if (sink) tap.connect(sink);
        if (voiceCapture) {
          try { voiceCapture.disconnect(); } catch (err) { /* gone */ }
          voiceCapture.onaudioprocess = null;
        }
        voiceCapture = tap;
      } catch (err) { /* the ScriptProcessor below carries on */ }
    }).catch(function () { /* likewise */ });

    voiceCapture = c.createScriptProcessor(BLOCK, 2, 1);
    voiceCapture.onaudioprocess = function (event) {
      var input = event.inputBuffer;
      var left = input.getChannelData(0);
      var right = input.numberOfChannels > 1 ? input.getChannelData(1) : null;
      var n = left.length;
      for (var i = 0; i < n; i += 1) {
        var v = right ? (left[i] + right[i]) * 0.5 : left[i];
        voiceRing[voiceWrite] = v;
        voiceWrite = voiceWrite + 1 === voiceRing.length ? 0 : voiceWrite + 1;
      }
      if (voiceFilled < voiceRing.length) {
        voiceFilled = Math.min(voiceRing.length, voiceFilled + n);
      }
    };
    voiceCapture.connect(sink);
    return true;
  }

  /* --------------------------------------------------------------- the taps */

  /* Same-origin, or we do not touch it - see the header. A relative or blank
   * src is the page's own origin by definition. */
  function safeToTap(element) {
    var src = String(element.currentSrc || element.src || '');
    if (!src) return false;
    if (src.indexOf('blob:') === 0 || src.indexOf('data:') === 0) return true;
    try {
      var url = new URL(src, root.location.href);
      if (url.origin === root.location.origin) return true;
    } catch (err) { return false; }
    /* An element the page explicitly opted into CORS for is fine IF the
     * server answered - which we cannot know from here, so it is trusted
     * only when the media actually decoded. */
    return element.crossOrigin === 'anonymous' && element.readyState >= 2 &&
      !!element.duration;
  }

  /* #1420: ONLY THE FIXED PLAYERS ARE TAPPED.
   *
   * tap() ran for every element that ever played - the play() hook below
   * and the audioScope hook both fed it - and each tap is a
   * createMediaElementSource plus the panel's analyser, cached by element
   * and connected for good. The SFX guy's set builds a NEW <video> for
   * every clip (#1312), so with the endless set on the graph grew by one
   * dead source per clip: measured on the PineTab 2026-09-14, four new
   * sources a minute, the WebAudio render thread from 33% after a reload
   * to 103% of a core twenty minutes later - which is what the operator
   * heard as "suddenly the Pine Tab stream started stuttering". A clip
   * is heard through its own element; it is not sampled from the air.
   * Only an element with an id - the station's fixed players - is
   * tapped, and never a video. */
  function tappable(element) {
    if (!element || !element.tagName) return false;
    if (String(element.tagName).toUpperCase() === 'VIDEO') return false;
    if (!element.id) return false;
    return true;
  }

  function tap(element) {
    if (!tappable(element)) return null;                 /* #1420 */
    if (!element || taps.has(element)) return taps.get(element) || null;
    if (known.indexOf(element) < 0) known.push(element);

    /* A PLAYER THAT ARRIVES MID-DUCK IS DUCKED TOO. The broadcast is a
     * stream of separate players - a record, a voice, a sting - and one that
     * starts while a pad is sounding would otherwise talk straight over it.
     * Measured: three players muted, a fourth started, and it was audible. */
    if (ducked && !element.muted) {
      try { element.muted = true; silenced.push(element); } catch (err) { /* fine */ }
    }

    /* THE PANEL'S OWN SCOPE FIRST. audioScope memoises one analyser per
     * player and is what every meter in the panel already reads, so joining
     * it costs nothing and cannot collide. */
    if (typeof root.audioScope === 'function') {
      var scope = null;
      try { scope = root.audioScope(element); } catch (err) { scope = null; }
      if (scope && scope.analyser && scope.context) {
        ctx = ctx || scope.context;
        if (scope.context === context() && ensureRing()) {
          try {
            scope.analyser.connect(capture);
            listenForSpectrum(element, scope.analyser);
            taps.set(element, {joined: true});
            live = true;
            reason = 'listening';
            return taps.get(element);
          } catch (err) { /* fall through and try our own */ }
        }
      }
    }

    var c = context();
    if (!c || !ensureRing()) return null;
    if (!safeToTap(element)) {
      /* Known but not recorded. It can still be DUCKED, which is the half of
       * this that never needs the graph at all. */
      taps.set(element, {joined: false});
      if (!live) reason = 'the broadcast is coming from another origin, so it ' +
        'cannot be sampled here - the tablet can, the desktop cannot';
      return taps.get(element);
    }
    var made;
    try {
      var source = c.createMediaElementSource(element);
      source.connect(c.destination);   /* it must still be heard */
      source.connect(capture);         /* and now it is also kept */
      made = {joined: true, source: source};
      live = true;
      reason = 'listening';
    } catch (err) {
      /* Someone else owns this element's source and there is no audioScope to
       * join. It keeps playing; it simply is not recorded. */
      made = {joined: false};
      if (!live) reason = 'this player would not be tapped: ' +
        ((err && err.message) || err);
    }
    taps.set(element, made);
    return made;
  }

  /* ANYTHING THAT MAKES A SOUND ANNOUNCES ITSELF. See the header: detached
   * `new Audio()` players are invisible to the DOM and are most of what the
   * panel uses. */
  var wrapped = false;
  function watchPlayers() {
    if (wrapped) return;
    wrapped = true;

    var proto = root.HTMLMediaElement && root.HTMLMediaElement.prototype;
    if (proto && proto.play) {
      var original = proto.play;
      proto.play = function () {
        try {
          if (!isOurs(this) && tappable(this)) tap(this);   /* #1420 */
        } catch (err) { /* never let bookkeeping stop playback */ }
        return original.apply(this, arguments);
      };
    }

    /* AND THE ONE THAT ACTUALLY CATCHES THE CURRENT TRACK.
     *
     * The play() hook only fires on the NEXT play call, and the panel builds
     * its players with `new Audio(url)`, which never enter the DOM - so a
     * track already playing when the sampler loads is invisible to both the
     * hook and querySelectorAll. Measured exactly that way: eight seconds of
     * ring at rms 0.0000 while music was demonstrably playing, which came
     * right the moment the track changed and play() was called again.
     *
     * The panel meters that player continuously, and every meter tick asks
     * audioScope for its scope. Wrapping THAT adopts whatever is playing
     * within one tick, attached or detached, new or already running. */
    if (typeof root.audioScope === 'function' && !root.audioScope.__pineAir) {
      var scoped = root.audioScope;
      var hook = function (player) {
        var scope = scoped.apply(this, arguments);
        try {
          if (scope && scope.analyser && player && !isOurs(player)
            && tappable(player) && !taps.has(player)) {   /* #1420 */
            ctx = ctx || scope.context;
            if (scope.context === context() && ensureRing()) {
              scope.analyser.connect(capture);
              taps.set(player, {joined: true});
              if (known.indexOf(player) < 0) known.push(player);
              live = true;
              reason = 'listening';
            }
          }
        } catch (err) { /* the panel's meter must not care */ }
        return scope;
      };
      hook.__pineAir = true;
      root.audioScope = hook;
    }
  }

  /* The sampler's own auditions must not be recorded into the ring, or a
   * grab would sample the thing you just grabbed. Anything the sampler
   * previews is marked. */
  function isOurs(element) {
    return !!(element && element.dataset && element.dataset.pineSelf === '1');
  }

  /* ---------------------------------------------------------------- ducking */

  /* "By default I would have it on so that way whenever I tap on a sample pad,
   * I am hearing just the sound of that sample pad." */
  var duckOn = true;
  var holders = Object.create(null);

  function setDuckEnabled(on) {
    duckOn = !!on;
    if (!duckOn) lower(false);
    try { root.localStorage.setItem('pineSamplerDuck', duckOn ? '1' : '0'); }
    catch (err) { /* a preference is not worth an exception */ }
  }

  function duckEnabled() { return duckOn; }

  function restoreDuckPreference() {
    try {
      var saved = root.localStorage.getItem('pineSamplerDuck');
      if (saved !== null) duckOn = saved === '1';
    } catch (err) { /* default stands */ }
  }

  /* REFERENCE COUNTED, because more than one thing ducks. A pad is held while
   * a clip is auditioned in the grab window; whichever finishes first must not
   * bring the broadcast back under the other. */
  /* A DUCK MUST NEVER OUTLIVE ITS REASON.
   *
   * Every holder gets a deadline. A caller that forgets to release - an
   * audition whose `ended` never fires, a pad whose voice count never
   * reaches zero, a sheet closed by a route nobody thought about - silently
   * leaves the radio muted, and a silent radio reads as a broken station
   * rather than as a stuck flag. Measured exactly that: musicGain 0,
   * padMuted true, nothing playing, and no way for the operator to know why.
   *
   * Ninety seconds is longer than any single thing that ducks here (the
   * longest welded round measured on this station is 107 s, and an audition
   * of one is the outlier the ceiling is FOR), and short enough that a
   * forgotten hold is a hiccup rather than an evening. */
  var DUCK_CEILING_MS = 90000;
  var deadlines = Object.create(null);

  function duck(who, seconds) {
    if (!duckOn) return;
    var key = who || 'pad';
    holders[key] = true;
    if (deadlines[key]) clearTimeout(deadlines[key]);
    var wait = Number(seconds) > 0
      ? Math.min(DUCK_CEILING_MS, Number(seconds) * 1000 + 2000)
      : DUCK_CEILING_MS;
    deadlines[key] = setTimeout(function () {
      if (!holders[key]) return;
      if (root.console) {
        root.console.warn('pine air: "' + key + '" held the duck for '
          + Math.round(wait / 1000) + 's and never let go - giving the radio back');
      }
      release(key);
    }, wait);
    lower(true);
  }

  function release(who) {
    var key = who || 'pad';
    if (deadlines[key]) { clearTimeout(deadlines[key]); delete deadlines[key]; }
    delete holders[key];
    for (var held in holders) if (holders[held]) return;
    lower(false);
  }

  /* Hand the radio back whatever is holding it. For a view tearing down, and
   * for the operator who just wants the sound to come back. */
  function releaseAll() {
    for (var key in holders) {
      if (deadlines[key]) clearTimeout(deadlines[key]);
      delete deadlines[key];
      delete holders[key];
    }
    lower(false);
  }

  /* `muted`, NOT `volume`.
   *
   * Muting is an independent boolean, so it cannot lose the operator's level:
   * setting volume to 0 and restoring it means remembering a number that the
   * terminals table, djApplyGain or the operator himself may have changed in
   * between, and restoring a stale one. It is also the primitive the panel's
   * own solo gate uses on these same elements. Every known player is muted,
   * tapped or not - the duck is about what comes out of the speaker, and that
   * half never needed the graph. */
  /* ONLY WHAT WE MUTED IS UNMUTED, and this is not fussiness. The panel's own
   * solo gate (#1008) mutes players deliberately - it is what stops two
   * terminals playing the same show a few hundred milliseconds apart - and a
   * blanket `muted = false` on release would undo that and put the house back
   * into exactly the fault the gate exists to prevent. So the duck remembers
   * which players it silenced and gives back only those. */
  function lower(down) {
    if (down === ducked) return;
    ducked = down;
    if (down) {
      silenced = [];
      for (var i = 0; i < known.length; i += 1) {
        var element = known[i];
        if (!element || element.muted) continue;   /* already quiet: not ours */
        try {
          element.muted = true;
          silenced.push(element);
        } catch (err) { /* nothing to be done */ }
      }
      /* AND THE RECORD'S GAIN TO ZERO ON TOP OF THE MUTE.
       *
       * "I need the radio COMPLETELY muted while the pad is playing so I can
       * hear the pad cleanly." Muting the elements is the right primitive
       * and covers every player this file has seen - but the record also
       * runs through a gain node the panel owns and writes on its own
       * schedule, and a player that starts a moment later is not in `known`
       * yet. Zeroing the gain closes both, and it is restored from the
       * desk's own number rather than a remembered one, so a level changed
       * while a pad was sounding is not undone. */
      mutedMusic = setMusicGain(0);
      return;
    }
    for (var j = 0; j < silenced.length; j += 1) {
      try { silenced[j].muted = false; } catch (err) { /* gone */ }
    }
    silenced = [];
    if (mutedMusic) {
      var level = musicLevels();
      /* Back to wherever the desk says it should be - ducked if something is
       * still talking, full if not. */
      setMusicGain(clipDucked ? level.music * (1 - level.duck) : level.music);
      mutedMusic = false;
    }
  }

  /* ------------------------------------------------- the music, specifically
   *
   * TWO THINGS NEED THE MUSIC ALONE, and both were asked for:
   *
   *   "Make sure that whenever someone is speaking or a clip is playing that
   *    the music ducks."
   *   "Whenever I tap on a pad, I need the radio completely muted while the
   *    pad is playing so I can hear the pad cleanly."
   *
   * The panel already ducks, and correctly - measured on the tablet, the
   * music gain goes 1.000 -> 0.300 the moment djSpeaking flips, which is
   * exactly music x (1 - duck). But djSpeaking is set for the DJ VOICE path
   * only. A sting, an advert preview, a clip fired from a console - anything
   * else that makes a sound - leaves the record at full level underneath it.
   *
   * So this watches every player it already knows about (see the header: it
   * knows about all of them, attached or not) and ducks the music whenever
   * anything ELSE is sounding. It writes the same node the panel writes,
   * with the same ramp, so the two cannot disagree about the shape - only
   * about the moment, and the later writer wins, which is the correct
   * answer for "is something talking right now". */

  function musicPlayer() {
    if (typeof document === 'undefined') return null;
    return document.getElementById('musicPlayer');
  }

  /** The panel's own gain node for the record, or null off the panel. */
  function musicGain() {
    var player = musicPlayer();
    if (!player || typeof root.gainFor !== 'function') return null;
    var entry = null;
    try { entry = root.gainFor(player, 'music'); } catch (err) { entry = null; }
    return entry && entry.node ? entry : null;
  }

  function musicLevels() {
    if (typeof root.djLevels === 'function') {
      try { return root.djLevels(); } catch (err) { /* fall through */ }
    }
    return {music: 1, voice: 1.6, duck: 0.7};
  }

  /* Set the record's gain, with the panel's own ramp - a step is a click. */
  function setMusicGain(value) {
    var entry = musicGain();
    if (!entry) return false;
    try {
      entry.node.gain.setTargetAtTime(value, entry.context.currentTime, 0.12);
    } catch (err) {
      try { entry.node.gain.value = value; } catch (inner) { return false; }
    }
    return true;
  }

  /* Is anything OTHER than the record making a sound? */
  function somethingElseTalking() {
    var record = musicPlayer();
    for (var i = 0; i < known.length; i += 1) {
      var element = known[i];
      if (!element || element === record) continue;
      if (element.paused || element.ended || element.muted) continue;
      if (isOurs(element)) continue;
      /* A player at zero volume is not talking, whatever its clock says. */
      if (Number(element.volume) === 0) continue;
      return true;
    }
    return false;
  }

  /* THE CLIP DUCK, on its own clock.
   *
   * 250 ms because that is the pace the station itself uses for the round
   * clock, and because a duck that arrives late on a one-second sting has
   * ducked nothing. It only ever writes when the answer CHANGES, so a quiet
   * minute costs one comparison every quarter second and no audio work. */
  var clipDucked = false;
  var clipTimer = 0;

  function watchClips() {
    if (clipTimer) return;
    clipTimer = setInterval(function () {
      /* The pad solo is a full mute and outranks a duck; while it holds,
       * this must not write the gain back up underneath it. */
      if (ducked) return;
      var talking = somethingElseTalking();
      if (talking === clipDucked) return;
      clipDucked = talking;
      var level = musicLevels();
      setMusicGain(talking ? level.music * (1 - level.duck) : level.music);
    }, 250);
  }

  /* The record is deliberately left out - see speechAnalyser. */
  function listenForSpectrum(element, from) {
    if (element === musicPlayer()) return;
    var c = context();
    if (!c) return;
    /* The same signal, into the voices-only ring. */
    if (voiceCapture) {
      try { from.connect(voiceCapture); } catch (err) { /* already, or refused */ }
    }
    if (!speechAnalyser) {
      speechAnalyser = c.createAnalyser();
      speechAnalyser.fftSize = 128;
      speechAnalyser.smoothingTimeConstant = 0.72;
      speechBins = new Uint8Array(speechAnalyser.frequencyBinCount);
    }
    try { from.connect(speechAnalyser); } catch (err) { /* already, or refused */ }
  }

  /** The current spectrum as 0..1 bars, or null when nothing is listening. */
  function spectrum() {
    if (!speechAnalyser || !speechBins) return null;
    try { speechAnalyser.getByteFrequencyData(speechBins); } catch (err) { return null; }
    var out = new Array(speechBins.length);
    for (var i = 0; i < speechBins.length; i += 1) out[i] = speechBins[i] / 255;
    return out;
  }

  /* ------------------------------------------------------------ reading out */

  function seconds(voicesOnly) {
    var c = context();
    if (!c) return 0;
    if (voicesOnly) return voiceRing ? voiceFilled / c.sampleRate : 0;
    return ring ? filled / c.sampleRate : 0;
  }

  /* Is there anything in the voices ring worth taking? A terminal where the
   * panel never built an analyser for a voice player has an empty one, and a
   * grab must fall back to the mix rather than hand back silence. */
  function haveVoices() { return !!(voiceRing && voiceFilled > 0); }

  function level() {
    var was = loudest;
    loudest = 0;
    return was;
  }

  /**
   * HOW LOUD A WINDOW OF THE PAST ACTUALLY IS.
   *
   * The ring fills whether or not anything is playing - a ScriptProcessor runs
   * on the clock, not on the signal - so `seconds()` says how long the tap has
   * been connected and NOT that there is anything in it. Without this, holding
   * a pad during a quiet stretch produced a silent sample and looked exactly
   * like a broken feature. The same lesson is already written into
   * MicCapture: "there was nothing to hear" is a different answer from "it did
   * not hear me", and the operator is owed the difference.
   */
  function measure(fromAgo, toAgo) {
    var c = context();
    if (!c || !ring || !filled) return {peak: 0, rms: 0};
    var rate = c.sampleRate;
    var older = Math.min(Math.max(0, Number(fromAgo) || 0), filled / rate);
    var newer = Math.max(0, Number(toAgo) || 0);
    if (older <= newer) return {peak: 0, rms: 0};
    var count = Math.round((older - newer) * rate);
    var end = write - Math.round(newer * rate);
    var peak = 0, sum = 0;
    for (var i = 0; i < count; i += 1) {
      var at = end - count + i;
      while (at < 0) at += ring.length;
      var v = ring[at % ring.length];
      var a = v < 0 ? -v : v;
      if (a > peak) peak = a;
      sum += v * v;
    }
    return {peak: peak, rms: Math.sqrt(sum / Math.max(1, count))};
  }

  /* The floor MicCapture uses for "this was a silent room", and for the same
   * reason: below it there is nothing worth putting on a pad. */
  var QUIET = 0.0025;
  function quiet(fromAgo, toAgo) {
    return measure(fromAgo, toAgo).rms < QUIET;
  }

  /**
   * A WINDOW OF THE PAST, AS WAV BYTES.
   *
   * @param fromAgo seconds ago the window STARTS (the older edge)
   * @param toAgo   seconds ago it ENDS (the newer edge; 0 is "now")
   *
   * Both are measured backwards from the present because that is how the
   * operator thinks about it - "the last eight seconds" - and because the
   * present keeps moving while the window is being chosen.
   */
  /**
   * @param voicesOnly take it from the voices ring - the broadcast WITHOUT
   *   the record underneath. That is what a pad grab wants: "what they
   *   said", not "what the room sounded like".
   */
  function sliceWav(fromAgo, toAgo, voicesOnly) {
    var c = context();
    /* Deliberately NOT named ring/write/filled: shadowing the module's own
     * cursors here would make a mix slice read the voice ring's head. */
    var useVoice = !!voicesOnly && voiceRing && voiceFilled > 0;
    var from = useVoice ? voiceRing : ring;
    var head = useVoice ? voiceWrite : write;
    var much = useVoice ? voiceFilled : filled;
    if (!c || !from || !much) return null;
    var rate = c.sampleRate;
    var older = Math.max(0, Number(fromAgo) || 0);
    var newer = Math.max(0, Number(toAgo) || 0);
    if (older <= newer) return null;
    var have = much / rate;
    if (older > have) older = have;
    if (newer >= older) return null;

    var count = Math.round((older - newer) * rate);
    if (count < 1) return null;
    var out = new Float32Array(count);
    /* `head` is where the NEXT sample goes, so it is also "now". */
    var end = head - Math.round(newer * rate);
    var start = end - count;
    var peak = 0;
    for (var i = 0; i < count; i += 1) {
      var at = start + i;
      while (at < 0) at += from.length;
      var v = from[at % from.length];
      out[i] = v;
      var a = v < 0 ? -v : v;
      if (a > peak) peak = a;
    }
    /* ONLY IF IT WOULD CLIP. Several players sum into this tap - music, a
     * voice and a sting can all be live at once - and their sum routinely
     * passes unity: measured at peak 1.1482 over six seconds of ordinary
     * broadcast. Sixteen-bit PCM cannot hold that, so without this the loud
     * moments, which are exactly the ones worth sampling, would come back
     * with their tops squared off. The scale is applied ONLY when there is
     * an overflow, so a normal take keeps the level it was heard at. */
    if (peak > 1) {
      var scale = 0.99 / peak;
      for (var j = 0; j < count; j += 1) out[j] *= scale;
    }
    return wav(out, rate);
  }

  /** Mono 16-bit PCM, because that is what decodeAudioData will always take
   *  and what the pad store already holds elsewhere. */
  function wav(samples, rate) {
    var bytes = new ArrayBuffer(44 + samples.length * 2);
    var view = new DataView(bytes);
    var text = function (at, s) {
      for (var i = 0; i < s.length; i += 1) view.setUint8(at + i, s.charCodeAt(i));
    };
    text(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    text(8, 'WAVE');
    text(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    text(36, 'data');
    view.setUint32(40, samples.length * 2, true);
    var at = 44;
    for (var i = 0; i < samples.length; i += 1) {
      var v = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(at, v < 0 ? v * 0x8000 : v * 0x7fff, true);
      at += 2;
    }
    return bytes;
  }

  /* ---------------------------------------------------------------- startup */

  var started = false;
  function start() {
    if (started) return;
    started = true;
    restoreDuckPreference();
    watchPlayers();
    /* Elements already playing when this loaded - the panel starts the
     * broadcast long before the sampler is opened. */
    try {
      var now = document.querySelectorAll('audio,video');
      for (var i = 0; i < now.length; i += 1) {
        if (!now[i].paused && !isOurs(now[i])) tap(now[i]);
      }
    } catch (err) { /* nothing playing yet is the normal case */ }
    /* The context is asleep until a gesture; the first press of anything
     * is a gesture. */
    ['pointerdown', 'keydown'].forEach(function (kind) {
      document.addEventListener(kind, wake, true);
    });
    watchClips();
    reason = live ? 'listening' : 'waiting for the broadcast to start';
  }

  function ready() { return live && filled > 0; }
  function why() { return reason; }

  var api = {
    start: start, ready: ready, why: why, seconds: seconds, level: level,
    /* For the diagnostics road and for proving a capture change worked:
     * how many buffers the ring has lost since it started. */
    drops: function () {
      return { gaps: gaps, seconds: gapSeconds,
               /* WHAT IS ACTUALLY CARRYING THE CAPTURE, not what the browser
                * is capable of. The old answer said "worklet-capable" while
                * a ScriptProcessor was dropping seventeen per cent of the
                * audio, which is a meter describing the wrong thing. */
               how: captureHow,
               able: (typeof AudioWorkletNode === 'function'),
               why: workletWhy,
               block: BLOCK };
    },
    sliceWav: sliceWav, measure: measure, quiet: quiet, spectrum: spectrum,
    haveVoices: haveVoices,
    /* Visible so the behaviour can be checked rather than believed. */
    duckState: function () {
      return {clipDucked: clipDucked, padMuted: ducked,
              musicGain: (musicGain() || {node: {gain: {value: null}}}).node.gain.value,
              talking: somethingElseTalking()};
    },
    duck: duck, release: release, releaseAll: releaseAll,
    setDuckEnabled: setDuckEnabled, duckEnabled: duckEnabled,
    /* Marks a player as the sampler's own, so auditioning a clip in the grab
     * window is not itself recorded into the ring. */
    mine: function (element) {
      if (element && element.dataset) element.dataset.pineSelf = '1';
      return element;
    }
  };
  root.PineAir = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
