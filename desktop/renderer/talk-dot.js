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
  var SILENCE_MS = 1400;       /* quiet this long and we assume you are done */

  var state = IDLE;
  var stream = null;
  var recorder = null;
  var chunks = [];
  var ctx = null;
  var analyser = null;
  var data = null;
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
    say.className = 'pine-talk-say';
    say.hidden = true;
    document.body.appendChild(say);
    return dot;
  }

  function announce(text, bad) {
    var box = el('pineTalkSay') || mount() && el('pineTalkSay');
    if (!box) return;
    box.textContent = text || '';
    box.hidden = !text;
    box.classList.toggle('bad', !!bad);
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
      box.__timer = setTimeout(function () { box.hidden = true; }, dwell);
    }
  }

  function setState(next) {
    state = next;
    var dot = el('pineTalkDot');
    if (!dot) return;
    dot.classList.toggle('listening', next === LISTENING);
    dot.classList.toggle('thinking', next === THINKING);
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

  function loudness() {
    if (native) return Number(root.pineDesktop.micLevel()) || 0;
    if (!analyser || !data) return 0;
    analyser.getByteTimeDomainData(data);
    var peak = 0;
    for (var i = 0; i < data.length; i += 1) {
      var v = Math.abs(data[i] - 128) / 128;
      if (v > peak) peak = v;
    }
    return peak;
  }

  /* ---- the gesture ---------------------------------------------------- */

  function toggle() {
    if (state === LISTENING) { finish(); return; }
    if (state === THINKING) return;
    listen();
  }

  async function listen() {
    mount();

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
      announce('Listening...' + (opened.effects && opened.effects !== 'none'
        ? ' (' + opened.effects + ')' : ''));
      startScene();
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
    announce('Listening...' + (micLabel ? ' (' + micLabel + ')' : ''));
    startScene();

    ctx = ctx || new (root.AudioContext || root.webkitAudioContext)();
    if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) { /* later */ } }
    var source = ctx.createMediaStreamSource(stream);
    analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    data = new Uint8Array(analyser.fftSize);
    /* NOT connected to the destination. Routing the microphone to the
     * speakers is a feedback loop, and on a tablet held near the speaker it
     * is an immediate one. */
    source.connect(analyser);

    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size) chunks.push(event.data);
    };
    recorder.onstop = send;
    recorder.start();

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
      var loud = loudness();
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

      if (since < 400) {
        floor += loud; floorFrames += 1;
        return;                      /* still listening to the room */
      }
      if (floorFrames && bar === 0.05) {
        var room = floor / floorFrames;
        bar = Math.min(0.22, Math.max(0.012, room * 3.5 + 0.008));
      }

      if (loud > bar) { quietSince = 0; heardAnything = true; }
      else if (!quietSince) quietSince = now;

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

  function finish() {
    if (state !== LISTENING) return;
    setState(THINKING);
    announce('Sending it through...');
    cancelAnimationFrame(frame);
    if (native) { sendNative(); return; }
    try { recorder.stop(); } catch (err) { send(); }
  }

  /* The native road: stop, and the words come back. The clip never enters
   * the page - moving a ten-second WAV through the bridge as base64 would
   * cost a third more bytes and buy nothing, since nothing here wants the
   * audio, only what was said. */
  async function sendNative() {
    /* The scene is NOT stopped here any more: it has the words to assemble
     * next. Ducking also holds, because the spoken reply follows. */
    duck(false);
    var got;
    try {
      got = await root.pineDesktop.micStop();
    } catch (err) {
      setState(IDLE);
      announce(String((err && err.message) || err), true);
      return;
    }
    var text = String((got && got.text) || '').trim();
    if (!text) {
      setState(IDLE);
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
    duck(false);
    if (stream) {
      stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) { /* gone */ } });
      stream = null;
    }
    var blob = new Blob(chunks, {type: (recorder && recorder.mimeType) || 'audio/webm'});
    chunks = [];
    if (blob.size < 2000) {
      setState(IDLE);
      announce('That was too short to hear.', true);
      return;
    }
    try {
      var heard = await postAudio(blob);
      var text = String((heard && heard.text) || '').trim();
      if (!text) {
        setState(IDLE);
        announce('Nothing was made out of that.', true);
        return;
      }
      await act(text);
    } catch (err) {
      setState(IDLE);
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
  async function act(text) {
    setState(THINKING);
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
    } catch (err) { /* fall through to the last resort */ }
    return 'http://127.0.0.1:8096';
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
  function postAudio(blob) {
    var url = '/api/listen/transcribe';
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
        body: blob
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
    state: function () { return state; }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineTalkDot;
})(typeof window !== 'undefined' ? window : globalThis);
