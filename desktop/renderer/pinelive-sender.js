/* PINELIVE SENDER - THIS PC'S INTERFACES, PIPED INTO MX LIVE.
 *
 * "I also want to be able to plug up the interface to the Windows PC that
 *  I'm currently on and be able to pipe my connection into the radio
 *  station and through Pinebox Live that way as well."
 *
 * The desk's chrome is a file:// page - a trustworthy origin with a proven
 * microphone road (#1355: main.js's permission request/check/device
 * handlers are what give enumerateDevices its labels and let a named
 * input open) - so the desk itself can be a network sender. This module
 * adds "This PC's interfaces" to the PineLive popup's Input panel, inside
 * the network subgroup: pick a Windows input (the K.O. II plugged into
 * this PC included), watch its level, and pipe it into the station.
 *
 * THE WIRE is the sender-page contract, spoken exactly (pinelive.py
 * SENDER_HTML; CONTRACT.md v2; tools/pinelive_e2e_network.py proves the
 * same frames end to end against a sandboxed host):
 *
 *   connect  state.ingest_url, whole - ws://<host>:8095/ingest?t=<token>
 *            (the token rotates per event, so it is read fresh each try)
 *   text     {"type":"hello","rate":<ctx.sampleRate>,"channels":2,
 *             "format":"s16le","label":"<platform> - <input>"}
 *   answer   {"type":"ok","rate":44100,"channels":2} - the normalised
 *            shape - or {"type":"error","code","say"} and the host closes
 *   then     binary frames of interleaved s16le, eight worklet blocks
 *            (~21 ms at 48 k) per send; {"type":"stat","level_db",
 *            "peak_db","rx_ms"} comes back about once a second while
 *            audio flows - that stat is the on-air health signal.
 *
 * WHAT THIS MODULE NEVER DOES. It never calls getDisplayMedia: main.js
 * owns that handler and answers an audio-only ask with the PANEL frame -
 * the broadcast - which piped back into the broadcast would be a feedback
 * loop. It never routes the capture to the speakers: the worklet's output
 * ends in a zero-gain sink (sampler-air.js's rule: it must hear, not
 * speak), so the preview meter is muted monitoring, never a speaker loop.
 * It never arms MX Live: Go live stays the operator's own act in the
 * Event panel - the one station POST here is the no-air line check,
 * /api/pinelive/test {source:"network"} ("nothing goes on air", 60 s).
 * And it never renders speech and never touches a level anywhere.
 *
 * WHERE IT IS INERT. pinelive.js (whose buildInput calls mountInput) also
 * ships in the tablet's kiosk bundle, where the panel is plain http: no
 * navigator.mediaDevices at all (talk-dot.js:855, measured). mountInput
 * checks canCapture() first and mounts NOTHING there - the subgroup's
 * sender-page words remain the whole story - and this file at load time
 * only defines the module, so a page that never mounts runs no capture
 * code, opens no socket and adds no listener.
 *
 * THE SENDER-GONE ROAD (pinelive_host.py net_close; pinelive.py tick):
 * the host frees its single sender slot on any disconnect, and the
 * station only falls back after dropout_seconds (3 s) without frames - a
 * reconnect inside that window keeps the set on air seamlessly. So on a
 * drop this module KEEPS THE CAPTURE ALIVE and walks a retry ladder,
 * re-reading the station's state each try (the token may have rotated);
 * Stop sends a clean close (1000), and closing the app closes the wire
 * too (pagehide/beforeunload). A connected sender sending silence still
 * falls back after silence_seconds - the stat line says "silent" so the
 * operator can see that from here.
 */
(function (root) {
  'use strict';

  var BATCH_BLOCKS = 8;                    /* the sender page's cadence: ~21 ms at 48 k */
  var METER_FLOOR_DB = -60;
  var RETRY_LADDER_MS = [400, 1000, 2000, 4000, 8000];
  var RETRY_REST_MS = 10000;               /* past the ladder (and while the slot is busy) */
  var AUTH_GIVE_UP = 3;                    /* fresh-token retries before asking for a hand */
  var SEND_BUFFER_CAP = 2 * 1024 * 1024;   /* a stalled socket sheds sound, not memory */
  var HELLO_LABEL_MAX = 80;                /* the host cuts labels here; cut first ourselves */
  var PICK_KEY = 'pineLiveSender.input.v1';
  var PAINT_MS = 200;

  /* ================================================== pure (and tested) */

  function num(v) { v = Number(v); return isFinite(v) ? v : NaN; }

  function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

  /** One float sample to s16 - the sender page's exact arithmetic. */
  function s16(x) {
    return Math.round(Math.max(-1, Math.min(1, x)) * 32767);
  }

  /** Two float channels folded to interleaved s16le stereo; a mono input
   *  goes to both ears, as the worklet does it. Exported so the tests can
   *  hold the module to the worklet's own math. */
  function foldToS16(left, right) {
    var n = left.length;
    var out = new Int16Array(n * 2);
    for (var i = 0; i < n; i += 1) {
      var l = left[i];
      var r = right ? right[i] : l;
      out[2 * i] = s16(l);
      out[2 * i + 1] = s16(r);
    }
    return out;
  }

  /** RMS and peak of an interleaved s16 batch, in dBFS. */
  function levelOf(samples) {
    var n = samples.length;
    if (!n) return {rms_db: -120, peak_db: -120};
    var sum = 0;
    var peak = 0;
    for (var i = 0; i < n; i += 1) {
      var v = samples[i] / 32768;
      sum += v * v;
      var a = v < 0 ? -v : v;
      if (a > peak) peak = a;
    }
    var rms = Math.sqrt(sum / n);
    var floor = -120;
    return {
      rms_db: rms > 0 ? Math.max(floor, 20 * Math.log(rms) / Math.LN10) : floor,
      peak_db: peak > 0 ? Math.max(floor, 20 * Math.log(peak) / Math.LN10) : floor
    };
  }

  /** The hello frame, exactly as the ingest expects it. */
  function helloFor(rate, label) {
    return {type: 'hello', rate: rate, channels: 2, format: 's16le',
      label: String(label || 'a sender').slice(0, HELLO_LABEL_MAX)};
  }

  /** "<platform> - <input>", the sender page's naming, cut to the host's 80. */
  function senderLabel(platform, inputLabel) {
    var name = (String(platform || '') || 'PC') + ' - ' + (String(inputLabel || '') || 'audio input');
    return name.slice(0, HELLO_LABEL_MAX);
  }

  /** Where to send, from the station's state - or, in words, which act is
   *  missing. The url exists only while armed-or-testing on the network
   *  road with a live token (pinelive.py state()); everything else here
   *  is the honest reason and the door that opens it. */
  function ingestOf(st) {
    if (!st) return {url: '', why: 'the station has not answered yet'};
    if (st.enabled === false) return {url: '', why: 'the MX Live event is switched off (Event panel)'};
    if (st.host && st.host.up === false) {
      return {url: '', why: 'the PineLive host service is not answering' + (st.host.why ? ': ' + st.host.why : '')};
    }
    var u = String(st.ingest_url || '');
    if (u) return {url: u, why: ''};
    if (st.armed && !(st.source && st.source.kind === 'network')) {
      return {url: '', why: 'the set is running on the USB road - this PC can only send on the Network road'};
    }
    return {url: '', why: 'the station has not handed out an ingest address - press Line check (60 s, off air), or Go live on the Network road (Event panel)'};
  }

  /** The audioinput rows for the picker, unnamed ones numbered rather than
   *  hidden (talk-dot's rule: labels are empty until the microphone has
   *  been opened once - a browser rule, not a fault). */
  function numberedInputs(all) {
    var n = 0;
    return (all || []).filter(function (d) { return d && d.kind === 'audioinput'; })
      .map(function (d) {
        n += 1;
        return {id: String(d.deviceId || ''),
          label: String(d.label || '').trim() || ('Input ' + n)};
      });
  }

  function fmtDb(db) {
    db = num(db);
    if (!isFinite(db) || db <= -119) return '--';
    return (db > 0 ? '+' : '') + db.toFixed(1);
  }

  /** The status line, one sentence per state. Pure so the tests can read
   *  every word this section can ever say. */
  function wordsFor(state, info) {
    info = info || {};
    switch (String(state || 'idle')) {
      case 'idle': return 'not sending';
      case 'preview': return 'previewing - the meter is this PC hearing itself; nothing leaves this machine and nothing sounds';
      case 'opening': return 'opening the input...';
      case 'reading': return 'reading the station...';
      case 'connecting': return 'connecting to the ingest...';
      case 'hello': return 'waiting for the station\'s ok...';
      case 'sending': {
        var ldb = num(info.localDb);
        var here = isFinite(ldb) && ldb > -119 ? fmtDb(ldb) + ' dBFS' : 'quiet';
        var there = info.statDb === null || info.statDb === undefined ? 'silent' : fmtDb(info.statDb) + ' dBFS';
        var line = 'sending - ' + here + ' here, the station hears ' + there;
        if (info.shed) line += ' (a stalled wire shed ' + Math.round(info.shed / 1024) + ' KB)';
        return line;
      }
      case 'dropout': {
        var inS = Math.max(0, Math.ceil((info.retryInMs || 0) / 1000));
        return 'the wire dropped - trying again' + (inS ? ' in ' + inS + ' s' : ' now')
          + (info.why ? ' (' + info.why + ')' : '')
          + '; after 3 s of quiet the station takes the air back itself';
      }
      case 'refused': return String(info.why || 'the station refused this sender');
      default: return String(state || '');
    }
  }

  /** Can this page capture at all? False on the tablet's plain-http panel
   *  (no mediaDevices) and anywhere without a worklet road. */
  function canCapture(w) {
    w = w || root;
    try {
      var nav = w.navigator;
      if (!nav || !nav.mediaDevices || typeof nav.mediaDevices.getUserMedia !== 'function') {
        return {ok: false, why: 'this screen has no capture road (no mediaDevices) - use the sender page or the ffmpeg line above'};
      }
      if (w.isSecureContext === false) {
        return {ok: false, why: 'this page is not a secure context, so the browser hides the microphone - use the sender page road above'};
      }
      if (typeof w.AudioContext !== 'function' || typeof w.AudioWorkletNode !== 'function') {
        return {ok: false, why: 'this screen has no AudioWorklet to shape the sound with'};
      }
      return {ok: true, why: ''};
    } catch (err) {
      return {ok: false, why: String((err && err.message) || err)};
    }
  }

  /* The worklet, compiled from a blob: URL (sampler-air.js's way - these
   * views cannot own a file on every page they reach). It is the sender
   * page's processor: fold the input to interleaved s16le stereo and post
   * each 128-frame block off the audio thread; the batching to eight
   * blocks stays on the main thread where the socket lives. */
  function workletSource() {
    return 'class PlSend extends AudioWorkletProcessor{process(i){const c=i[0];'
      + 'if(c&&c.length&&c[0]&&c[0].length){const n=c[0].length,s=c.length>1&&c[1]?c[1]:c[0],'
      + 'o=new Int16Array(n*2);for(let j=0;j<n;j++){'
      + 'o[2*j]=Math.round(Math.max(-1,Math.min(1,c[0][j]))*32767);'
      + 'o[2*j+1]=Math.round(Math.max(-1,Math.min(1,s[j]))*32767);}'
      + 'this.port.postMessage(o.buffer,[o.buffer]);}return true;}}'
      + 'registerProcessor("plsend",PlSend);';
  }

  /* ================================================== the run */

  var tools = null;      /* {request, say} handed in by pinelive.js's hook */
  var ui = null;         /* the mounted DOM, once */
  var run = {
    state: 'idle', why: '',
    pick: '',            /* chosen deviceId; '' follows the Windows default */
    devices: [],
    cap: null,           /* {stream, ac, node, sink, label, rate} */
    ws: null,
    piping: false,       /* the operator's intent: keep the wire up */
    registered: false,   /* the host said ok at least once this run */
    stat: null,          /* the host's last stat frame */
    statAt: 0,
    localDb: -120, localPeak: -120, meterAt: 0,
    blocks: [], bytesOut: 0, shed: 0,
    retryTimer: 0, retryAt: 0, retryN: 0, authFails: 0,
    paintTimer: 0, unloadHooked: false
  };

  function readPick() {
    try { return root.localStorage.getItem(PICK_KEY) || ''; } catch (err) { return ''; }
  }

  function writePick(id) {
    try {
      if (id) root.localStorage.setItem(PICK_KEY, id);
      else root.localStorage.removeItem(PICK_KEY);
    } catch (err) { /* private mode keeps the session's choice */ }
  }

  /* ------------------------------------------------------- small DOM */

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function setText(node, text) {
    text = text === undefined || text === null ? '' : String(text);
    if (node && node.textContent !== text) node.textContent = text;
  }

  function setHidden(node, hidden) {
    if (node && node.hidden !== !!hidden) node.hidden = !!hidden;
  }

  function iconNode(name) {
    var span = make('span', 'pl-ico');
    try {
      if (typeof root.pineIcon === 'function') {
        var markup = root.pineIcon(name, '') || '';
        if (markup) span.innerHTML = markup;
      }
    } catch (err) { /* the words on the button carry it */ }
    span.setAttribute('aria-hidden', 'true');
    return span;
  }

  function btn(cls, words, iconName, title) {
    var b = make('button', 'pl-btn' + (cls ? ' ' + cls : ''));
    b.type = 'button';
    if (iconName) b.appendChild(iconNode(iconName));
    if (words) b.appendChild(make('span', 'pl-btn-words', words));
    if (title) { b.title = title; b.setAttribute('aria-label', title); }
    return b;
  }

  function stationState() {
    try {
      var pl = root.PineLive;
      if (pl && typeof pl.state === 'function') return pl.state();
    } catch (err) { /* the popup's model is a convenience, not a need */ }
    return null;
  }

  function say(text, kind) {
    try { if (tools && typeof tools.say === 'function') tools.say(text, kind); } catch (err) { /* words stay local */ }
  }

  /* ------------------------------------------------------- the capture */

  function constraintsFor(pick) {
    /* The sender profile (pinelive.py SENDER_HTML): a bit-honest
     * instrument feed - every browser "help" off, two channels. Not
     * talk-dot's voice profile, which keeps all three ON for a human
     * over the room's speakers. */
    var audio = {channelCount: 2, echoCancellation: false,
      noiseSuppression: false, autoGainControl: false};
    if (pick) audio.deviceId = {exact: pick};
    else audio.deviceId = {ideal: 'default'};
    return {audio: audio};
  }

  function openInput() {
    var pick = run.pick;
    return navigator.mediaDevices.getUserMedia(constraintsFor(pick)).catch(function (err) {
      if (!pick) throw err;
      /* The pinned interface has gone (unplugged, or a DAW holds it in
       * exclusive mode). Fall back to the default rather than refusing
       * to send at all - a pin is a preference, not a requirement
       * (talk-dot's rule). */
      run.pick = '';
      writePick('');
      return navigator.mediaDevices.getUserMedia(constraintsFor(''));
    });
  }

  function ensureCapture() {
    if (run.cap) return Promise.resolve(run.cap);
    var cc = canCapture(root);
    if (!cc.ok) return Promise.reject(new Error(cc.why));
    return openInput().then(function (stream) {
      var ac = new root.AudioContext({latencyHint: 'interactive'});
      /* the chrome runs with autoplay allowed (main.js appendSwitch), so
       * this is a no-op there; anywhere stricter it wakes the graph */
      try { if (ac.state === 'suspended') ac.resume().catch(function () { /* the meter will say so */ }); } catch (err) { /* older ctx */ }
      var url = '';
      try {
        url = URL.createObjectURL(new Blob([workletSource()], {type: 'text/javascript'}));
      } catch (err) {
        try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e2) { /* gone */ }
        try { ac.close(); } catch (e3) { /* gone */ }
        throw new Error('a blob URL could not be made: ' + err.message);
      }
      return ac.audioWorklet.addModule(url).then(function () {
        try { URL.revokeObjectURL(url); } catch (err) { /* already gone */ }
        var srcNode = ac.createMediaStreamSource(stream);
        var node = new root.AudioWorkletNode(ac, 'plsend',
          {channelCount: 2, channelCountMode: 'explicit'});
        /* The zero-gain sink: the graph must reach the destination to be
         * pulled at all, and it must arrive there at zero - it hears, it
         * never speaks. NEVER raise this gain: the input may be the same
         * room as the speakers. */
        var sink = ac.createGain();
        sink.gain.value = 0;
        srcNode.connect(node);
        node.connect(sink);
        sink.connect(ac.destination);
        node.port.onmessage = onBlock;
        var track = stream.getAudioTracks()[0];
        run.cap = {stream: stream, ac: ac, node: node, sink: sink,
          label: String((track && track.label) || '').trim() || 'audio input',
          rate: ac.sampleRate};
        /* the first grant of the session names the unnamed inputs */
        refreshInputs();
        return run.cap;
      }, function (err) {
        try { URL.revokeObjectURL(url); } catch (e2) { /* already gone */ }
        try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e3) { /* gone */ }
        try { ac.close(); } catch (e4) { /* gone */ }
        throw new Error('the page refused the worklet module: ' + err.message);
      });
    });
  }

  function stopCapture() {
    var cap = run.cap;
    run.cap = null;
    run.blocks = [];
    if (!cap) return;
    try { cap.node.port.onmessage = null; } catch (err) { /* gone */ }
    try { cap.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (err) { /* gone */ }
    try { cap.ac.close(); } catch (err) { /* gone */ }
  }

  function onBlock(e) {
    run.blocks.push(e.data);
    if (run.blocks.length < BATCH_BLOCKS) return;
    var total = 0;
    var i;
    for (i = 0; i < run.blocks.length; i += 1) total += run.blocks[i].byteLength;
    var out = new Uint8Array(total);
    var at = 0;
    for (i = 0; i < run.blocks.length; i += 1) {
      out.set(new Uint8Array(run.blocks[i]), at);
      at += run.blocks[i].byteLength;
    }
    run.blocks = [];
    var lv = levelOf(new Int16Array(out.buffer));
    run.localDb = lv.rms_db;
    if (lv.peak_db > run.localPeak || Date.now() - run.meterAt > 1200) run.localPeak = lv.peak_db;
    run.meterAt = Date.now();
    if (run.piping && run.ws && run.ws.readyState === 1) {
      if (run.ws.bufferedAmount > SEND_BUFFER_CAP) {
        /* the socket has stalled: shed sound rather than grow without
         * bound - the host pads short reads with silence and the ladder
         * below will notice a real drop */
        run.shed += out.byteLength;
      } else {
        run.ws.send(out.buffer);
        run.bytesOut += out.byteLength;
      }
    }
  }

  /* ------------------------------------------------------- the wire */

  function setState(state, why) {
    run.state = state;
    run.why = String(why || '');
    paint();
  }

  function clearRetry() {
    if (run.retryTimer) { root.clearTimeout(run.retryTimer); run.retryTimer = 0; }
    run.retryAt = 0;
  }

  function scheduleRetry(why) {
    if (!run.piping) return;
    clearRetry();
    var wait = run.retryN < RETRY_LADDER_MS.length ? RETRY_LADDER_MS[run.retryN] : RETRY_REST_MS;
    run.retryN += 1;
    run.retryAt = Date.now() + wait;
    setState('dropout', why || '');
    run.retryTimer = root.setTimeout(function () {
      run.retryTimer = 0;
      attempt();
    }, wait);
  }

  function pipeStart() {
    var cc = canCapture(root);
    if (!cc.ok) { setState('refused', cc.why); return; }
    if (!tools || typeof tools.request !== 'function') {
      setState('refused', 'this screen has no road to the station');
      return;
    }
    hookUnload();
    run.piping = true;
    run.registered = false;
    run.retryN = 0;
    run.authFails = 0;
    run.shed = 0;
    run.bytesOut = 0;
    attempt();
  }

  function attempt() {
    if (!run.piping) return;
    setState('reading');
    tools.request('GET', '/api/pinelive/state').then(function (st) {
      if (!run.piping) return;
      var road = ingestOf(st);
      if (!road.url) {
        /* Not a wire fault: the road is not open. If a set was flowing
         * and has now ended, fold up cleanly; otherwise say the act
         * that is missing and wait for the operator. */
        run.piping = false;
        stopCapture();
        setState(run.registered ? 'idle' : 'refused',
          run.registered ? '' : road.why);
        if (run.registered) say('The network road closed - the sender stopped.', '');
        return;
      }
      setState('opening');
      ensureCapture().then(function () {
        if (!run.piping) return;
        openWs(road.url);
      }, function (err) {
        run.piping = false;
        stopCapture();
        setState('refused', 'the input would not open: ' + String((err && err.message) || err));
      });
    }, function (err) {
      if (!run.piping) return;
      scheduleRetry('the station did not answer: ' + String((err && err.message) || err));
    });
  }

  function openWs(url) {
    closeWs(4000);
    var ws;
    try {
      ws = new root.WebSocket(url);
    } catch (err) {
      scheduleRetry('the socket would not open: ' + String((err && err.message) || err));
      return;
    }
    ws.binaryType = 'arraybuffer';
    run.ws = ws;
    setState('connecting');
    ws.onopen = function () {
      if (run.ws !== ws) return;
      setState('hello');
      try {
        ws.send(JSON.stringify(helloFor(run.cap.rate,
          senderLabel(root.navigator && root.navigator.platform, run.cap.label))));
      } catch (err) { try { ws.close(); } catch (e2) { /* closing anyway */ } }
    };
    ws.onmessage = function (m) {
      if (run.ws !== ws) return;
      var j = null;
      try { j = JSON.parse(m.data); } catch (err) { j = null; }
      if (!j) return;
      if (j.type === 'ok') {
        run.registered = true;
        run.retryN = 0;
        run.authFails = 0;
        run.stat = null;
        run.statAt = 0;
        setState('sending');
        say('This PC is the station\'s sender' + (run.cap ? ' (' + run.cap.label + ')' : '') + '.', '');
        return;
      }
      if (j.type === 'stat') {
        run.stat = j;
        run.statAt = Date.now();
        paint();
        return;
      }
      if (j.type === 'error') {
        /* the host says why and then closes; onclose decides what is next */
        run.lastError = {code: String(j.code || ''), say: String(j.say || '')};
      }
    };
    ws.onclose = function () {
      if (run.ws !== ws) return;
      run.ws = null;
      if (!run.piping) { setState('idle'); return; }
      var err = run.lastError || null;
      run.lastError = null;
      if (err && (err.code === 'not_armed' || err.code === 'not_network' || err.code === 'ingest_format')) {
        /* the road itself refused: retrying the same wire cannot help */
        run.piping = false;
        stopCapture();
        setState('refused', err.say || ('the station refused this sender (' + err.code + ')'));
        return;
      }
      if (err && err.code === 'ingest_busy') {
        /* one sender at a time; keep asking gently - when the other
         * sender leaves, the slot is ours */
        run.retryN = RETRY_LADDER_MS.length;
        scheduleRetry(err.say || 'another sender holds the ingest');
        return;
      }
      if (!run.registered) {
        /* refused before the ok - most likely the 403 before the
         * upgrade (a wrong or rotated token, which a browser socket
         * cannot read the status of). Each retry re-reads the state
         * for a fresh token; after a few, ask for a hand. */
        run.authFails += 1;
        if (run.authFails >= AUTH_GIVE_UP) {
          run.piping = false;
          stopCapture();
          setState('refused', 'the ingest would not admit this sender - the token may have rotated, another sender may hold the slot, or the road is not armed (Troubleshoot knows)');
          return;
        }
      }
      scheduleRetry(err ? err.say : '');
    };
    ws.onerror = function () { /* the close that follows carries the decision */ };
  }

  function closeWs(code) {
    var ws = run.ws;
    run.ws = null;
    if (!ws) return;
    ws.onclose = null;
    ws.onmessage = null;
    ws.onerror = null;
    try { ws.close(code || 1000); } catch (err) { /* closing anyway */ }
  }

  function pipeStop(words) {
    run.piping = false;
    clearRetry();
    closeWs(1000);                 /* the clean goodbye frees the slot at once */
    stopCapture();
    run.stat = null;
    run.registered = false;
    setState('idle');
    if (words) say(words, '');
  }

  function previewToggle() {
    if (run.piping) return;        /* the pipe already owns the capture */
    if (run.state === 'preview') {
      stopCapture();
      setState('idle');
      return;
    }
    var cc = canCapture(root);
    if (!cc.ok) { setState('refused', cc.why); return; }
    setState('opening', '');
    ensureCapture().then(function () {
      setState('preview');
    }, function (err) {
      setState('refused', 'the input would not open: ' + String((err && err.message) || err));
    });
  }

  function lineCheck(node) {
    if (!tools || typeof tools.request !== 'function') return;
    node.disabled = true;
    tools.request('POST', '/api/pinelive/test', {source: 'network'}).then(function (ans) {
      node.disabled = false;
      if (ans && ans.ok === false) {
        setState('refused', ans.say || 'the station refused the line check');
        return;
      }
      say((ans && ans.say) || 'the station listens for 60 seconds - nothing goes on air', '');
      pipeStart();
    }, function (err) {
      node.disabled = false;
      setState('refused', 'the station did not take the line check: ' + String((err && err.message) || err));
    });
  }

  function hookUnload() {
    if (run.unloadHooked) return;
    run.unloadHooked = true;
    var bye = function () {
      /* closing the app is a goodbye, not a dropout: free the slot */
      run.piping = false;
      clearRetry();
      closeWs(1000);
      stopCapture();
    };
    try {
      root.addEventListener('pagehide', bye);
      root.addEventListener('beforeunload', bye);
    } catch (err) { /* no window to leave */ }
  }

  /* ------------------------------------------------------- the devices */

  function refreshInputs() {
    if (!ui) return;
    var cc = canCapture(root);
    if (!cc.ok) return;
    navigator.mediaDevices.enumerateDevices().then(function (all) {
      run.devices = numberedInputs(all);
      var sel = ui.sel;
      var keep = run.pick;
      sel.replaceChildren();
      var d0 = make('option', '', 'The Windows default input');
      d0.value = '';
      sel.appendChild(d0);
      var found = false;
      run.devices.forEach(function (d) {
        var o = make('option', '', d.label);
        o.value = d.id;
        if (d.id === keep) found = true;
        sel.appendChild(o);
      });
      sel.value = found ? keep : '';
      setText(ui.devLine, run.devices.length
        ? (run.devices.length + ' input' + (run.devices.length === 1 ? '' : 's') + ' on this PC')
        : 'no audio inputs on this PC');
    }, function (err) {
      setText(ui.devLine, 'the inputs would not list: ' + String((err && err.message) || err));
    });
  }

  /* ------------------------------------------------------- the paint */

  function meterPct(db) {
    return clamp01((num(db) - METER_FLOOR_DB) / -METER_FLOOR_DB);
  }

  function paint() {
    if (!ui) return;
    var capturing = !!run.cap;
    var live = capturing && Date.now() - run.meterAt < 1500;
    var db = live ? run.localDb : -120;
    ui.fill.style.transform = 'scaleX(' + meterPct(db).toFixed(3) + ')';
    ui.fill.style.background = db > -3 ? '#ef6f5e' : db > -12 ? '#e3be63' : '#54d18b';
    ui.peak.style.left = (meterPct(live ? run.localPeak : -120) * 100).toFixed(1) + '%';
    ui.peak.style.opacity = live ? '0.75' : '0';
    setText(ui.db, live ? fmtDb(db) + ' dBFS' : '--');
    var statDb = run.stat && Date.now() - run.statAt < 4000 ? run.stat.level_db : undefined;
    setText(ui.words, wordsFor(run.state, {
      localDb: db,
      statDb: run.state === 'sending' ? (statDb === undefined ? null : statDb) : undefined,
      retryInMs: run.retryAt ? run.retryAt - Date.now() : 0,
      why: run.why,
      shed: run.shed
    }));
    ui.words.style.color = run.state === 'refused' ? '#ef6f5e'
      : run.state === 'dropout' ? '#e3be63'
        : run.state === 'sending' ? '#54d18b' : '#8fa0ad';
    var st = stationState();
    var road = ingestOf(st);
    var idle = run.state === 'idle' || run.state === 'refused';
    setText(ui.prevBtn.querySelector('.pl-btn-words'), run.state === 'preview' ? 'Stop the preview' : 'Preview');
    ui.prevBtn.disabled = run.piping;
    ui.pipeBtn.disabled = run.piping;
    setHidden(ui.pipeBtn, run.piping);
    setHidden(ui.stopBtn, !run.piping);
    setHidden(ui.againBtn, !(idle && run.registered) && run.state !== 'refused');
    setHidden(ui.lineBtn, !!(st && st.armed) || run.piping || !!road.url);
    if (idle && !run.why) {
      setText(ui.roadLine, road.url ? 'the station is ready for a network sender - Pipe when you are'
        : road.why);
    } else {
      setText(ui.roadLine, '');
    }
    setHidden(ui.roadLine, !ui.roadLine.textContent);
  }

  function paintLoop() {
    if (run.paintTimer) return;
    run.paintTimer = root.setInterval(function () {
      if (!ui || !ui.block.isConnected) return;
      var hidden = false;
      try { hidden = !!document.hidden; } catch (err) { hidden = false; }
      if (!hidden) paint();
    }, PAINT_MS);
  }

  /* ------------------------------------------------------- the mount */

  /** Build "This PC's interfaces" into the Input panel's network subgroup.
   *  `container` is that subgroup's body; `handed` is pinelive.js's own
   *  {request, say}. Mounts nothing where the page cannot capture. */
  function mountInput(container, handed) {
    if (!container || ui) return !!ui;
    var cc = canCapture(root);
    if (!cc.ok) return false;      /* the tablet's panel: stay silent */
    tools = handed || tools || {};
    run.pick = readPick();

    var block = make('div', 'pls-block');
    block.style.borderTop = '1px dashed #293a44';
    block.style.marginTop = '10px';
    block.style.paddingTop = '8px';

    var head = make('div', 'pl-row');
    var headText = make('div', 'pl-row-text');
    var headB = make('b');
    var headIco = iconNode('c:audio-console');
    headIco.style.display = 'inline-flex';
    headIco.style.verticalAlign = '-2px';
    headIco.style.marginRight = '6px';
    headB.appendChild(headIco);
    headB.appendChild(make('span', '', 'This PC\'s interfaces'));
    headText.appendChild(headB);
    var devLine = make('small', '', 'the desk itself as the sender - pick an input, watch its level, pipe it in');
    headText.appendChild(devLine);
    head.appendChild(headText);
    var scan = btn('pl-mini', 'Rescan', 'c:renew', 'List this PC\'s audio inputs again');
    scan.addEventListener('click', function (e) { e.stopPropagation(); refreshInputs(); });
    head.appendChild(scan);
    block.appendChild(head);

    var selRow = make('div', 'pl-row');
    var sel = make('select', 'pls-dev');
    sel.setAttribute('aria-label', 'Which of this PC\'s inputs to send');
    sel.style.flex = '1';
    sel.style.minWidth = '0';
    sel.style.font = 'inherit';
    sel.style.fontSize = '12px';
    sel.style.color = '#dbe7eb';
    sel.style.background = '#0b1418';
    sel.style.border = '1px solid #293a44';
    sel.style.borderRadius = '6px';
    sel.style.padding = '6px 8px';
    sel.addEventListener('click', function (e) { e.stopPropagation(); });
    sel.addEventListener('change', function () {
      run.pick = sel.value;
      writePick(sel.value);
      /* a running capture follows the hand: reopen on the new input */
      if (run.cap && !run.piping) {
        stopCapture();
        setState('opening');
        ensureCapture().then(function () { setState('preview'); },
          function (err) { setState('refused', 'the input would not open: ' + String((err && err.message) || err)); });
      } else if (run.cap && run.piping) {
        /* a new input can open at a new sample rate, and the rate was
         * said in the hello: say a clean goodbye and hello again - the
         * host frees the slot on the close, and the reconnect lands
         * inside the station's 3 s dropout window */
        closeWs(1000);
        stopCapture();
        run.retryN = 0;
        attempt();
      }
    });
    selRow.appendChild(sel);
    block.appendChild(selRow);

    var meterRow = make('div', 'pls-meter-row');
    meterRow.style.display = 'flex';
    meterRow.style.alignItems = 'center';
    meterRow.style.gap = '8px';
    meterRow.style.margin = '8px 0 2px';
    var bar = make('div', 'pls-meter');
    bar.style.flex = '1';
    bar.style.height = '10px';
    bar.style.background = '#0b1418';
    bar.style.border = '1px solid #293a44';
    bar.style.borderRadius = '5px';
    bar.style.overflow = 'hidden';
    bar.style.position = 'relative';
    var fill = make('i');
    fill.style.display = 'block';
    fill.style.height = '100%';
    fill.style.width = '100%';
    fill.style.transformOrigin = 'left';
    fill.style.transform = 'scaleX(0)';
    /* solid, recoloured by level - a gradient on a scaled fill squashes
     * with it and paints red on a healthy mid level */
    fill.style.background = '#54d18b';
    fill.style.transition = 'transform .12s linear';
    bar.appendChild(fill);
    var peak = make('em');
    peak.style.position = 'absolute';
    peak.style.top = '0';
    peak.style.bottom = '0';
    peak.style.width = '2px';
    peak.style.left = '0%';
    peak.style.background = '#dbe7eb';
    peak.style.opacity = '0.75';
    bar.appendChild(peak);
    meterRow.appendChild(bar);
    var db = make('b', 'pls-db', '--');
    db.style.width = '84px';
    db.style.textAlign = 'right';
    db.style.fontSize = '12px';
    db.style.color = '#dbe7eb';
    meterRow.appendChild(db);
    block.appendChild(meterRow);

    var actions = make('div', 'pl-actions');
    var prevBtn = btn('pl-mini', 'Preview', 'c:waveform', 'Open the input and watch its level here - muted monitoring, nothing sounds and nothing is sent');
    prevBtn.addEventListener('click', function (e) { e.stopPropagation(); previewToggle(); });
    actions.appendChild(prevBtn);
    var lineBtn = btn('pl-mini', 'Line check 60 s', 'c:timer', 'Ask the station to listen to the network road for a minute - nothing goes on air - then pipe this input to it');
    lineBtn.addEventListener('click', function (e) { e.stopPropagation(); lineCheck(lineBtn); });
    actions.appendChild(lineBtn);
    var pipeBtn = btn('', 'Pipe to the station', 'c:plug', 'Send this input to the station\'s ingest - the set takes the air only when MX Live is armed');
    pipeBtn.addEventListener('click', function (e) { e.stopPropagation(); pipeStart(); });
    actions.appendChild(pipeBtn);
    var stopBtn = btn('pl-mini', 'Stop sending', 'c:stop--filled', 'Close the wire cleanly and free the sender slot');
    stopBtn.hidden = true;
    stopBtn.addEventListener('click', function (e) { e.stopPropagation(); pipeStop('The sender stopped.'); });
    actions.appendChild(stopBtn);
    var againBtn = btn('pl-mini', 'Reconnect', 'c:renew', 'Read the station again and reopen the wire');
    againBtn.hidden = true;
    againBtn.addEventListener('click', function (e) { e.stopPropagation(); pipeStart(); });
    actions.appendChild(againBtn);
    block.appendChild(actions);

    var words = make('small', 'pls-words', wordsFor('idle'));
    words.style.display = 'block';
    words.style.marginTop = '6px';
    words.style.color = '#8fa0ad';
    block.appendChild(words);
    var roadLine = make('small', 'pl-muted pls-road');
    roadLine.style.display = 'block';
    roadLine.style.marginTop = '2px';
    roadLine.hidden = true;
    block.appendChild(roadLine);

    container.appendChild(block);
    ui = {block: block, sel: sel, devLine: devLine, fill: fill, peak: peak, db: db,
      words: words, roadLine: roadLine, prevBtn: prevBtn, lineBtn: lineBtn,
      pipeBtn: pipeBtn, stopBtn: stopBtn, againBtn: againBtn};

    refreshInputs();
    try {
      navigator.mediaDevices.addEventListener('devicechange', refreshInputs);
    } catch (err) { /* Rescan stays */ }
    paintLoop();
    paint();
    return true;
  }

  /* ================================================== the api */

  var api = {
    mountInput: mountInput,
    stop: function () { pipeStop(''); },
    state: function () { return {state: run.state, piping: run.piping, registered: run.registered, bytesOut: run.bytesOut, shed: run.shed, why: run.why}; },
    /* pure helpers, for the tests */
    canCapture: canCapture, foldToS16: foldToS16, s16: s16, levelOf: levelOf,
    helloFor: helloFor, senderLabel: senderLabel, ingestOf: ingestOf,
    numberedInputs: numberedInputs, wordsFor: wordsFor, workletSource: workletSource,
    meterPct: meterPct, fmtDb: fmtDb,
    BATCH_BLOCKS: BATCH_BLOCKS, RETRY_LADDER_MS: RETRY_LADDER_MS,
    RETRY_REST_MS: RETRY_REST_MS, SEND_BUFFER_CAP: SEND_BUFFER_CAP,
    HELLO_LABEL_MAX: HELLO_LABEL_MAX, METER_FLOOR_DB: METER_FLOOR_DB
  };
  root.PineLiveSender = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
