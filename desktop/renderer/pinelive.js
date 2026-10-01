/* PINELIVE - THE MIC ON THE STATUS BAR AND THE POPUP IT OPENS.
 *
 * "at the bottom of the status bar of the pinebox app, I want an icon of a
 *  mic that if i tap it opens the pine box live popup, In this I am able to
 *  expand categories to adjust setting pertaining to the streaming settings
 *  in panels that can be expanded and collapsed containing grouped
 *  suboptions. ... I want to be able to configure everything to do with the
 *  live performance on the PineLive tab. In this popup, I want toggles for
 *  enabling video to be broadcasted to the tailscale and the toggling of it
 *  ceases the video display immediately. I also want a toggle to turn off
 *  the "MX Live" event."
 *
 * THE STATION'S HALF is PineLive core, and its contract is CONTRACT.md (v2):
 *   GET  /api/pinelive/state         1 Hz while this popup is open, 5 s otherwise
 *   GET  /api/pinelive/devices       the host's USB/ALSA scan (?fresh=1 rescans)
 *   GET  /api/pinelive/troubleshoot  the ordered checks the flowchart draws
 *   GET/POST /api/pinelive/settings  every setting below
 *   POST /api/pinelive/start|stop|test|event
 *   levels_url                       Server-Sent Events, the audiograph's frames
 * Every POST answers {ok, say, code, state}, so a press repaints from its
 * own answer without a second request.
 *
 * WHERE IT LIVES. The status bar is console-line.js's #pineConsoleLine,
 * which rail.js mounts along the bottom of every screen - the desktop's
 * chrome (index.html) and the tablet's panel page (the kiosk evaluates the
 * views bundle into it). This file puts its button INTO that bar once the
 * bar exists; it does not edit console-line.js. The bar answers any click
 * it does not recognise by opening the audit list, so the button stops its
 * own click from reaching it.
 *
 * ITS WAYS OUT (#1450's rule: an overlay never depends on the thing it
 * covers for its way out): the close button in its corner, a tap anywhere
 * off it (PineDismiss), Escape, and the tablet's BACK key - pineBack()
 * asks PineDismiss.onBack for the topmost overlay, and this popup answers
 * with its enlarged manual page first, then itself.
 *
 * NO SCROLL IS EVER TAKEN (the house rule). Nothing here scrolls the popup:
 * a repaint writes values into the nodes already on screen and leaves the
 * view where the operator put it.
 */
(function (root) {
  'use strict';

  var POLL_OPEN_MS = 1000;
  var POLL_CLOSED_MS = 5000;
  var POLL_ERROR_MS = 15000;
  var POLL_ABSENT_MS = 60000;
  var REQUEST_MS = 8000;
  var TROUBLE_EVERY_MS = 4000;
  var PANELS_KEY = 'pineLive.panels.v1';
  var PREFS_KEY = 'pineLive.prefs.v1';
  var S3_DEFAULT_V = '8';
  var PANEL_ORDER = ['scope', 'event', 'input', 'picture', 'stream', 'recording', 'system3', 'troubleshoot'];   /* [pinestream] */
  var DEFAULT_OPEN = {scope: true, event: true, input: false, picture: false, stream: false,
    recording: false, system3: false, troubleshoot: false};
  var DEFAULT_DEST = '\\\\10.89.1.125\\QuickSwap\\PineBoxRecordings\\Live Events';
  var CUT_PRESETS = [[60, '1 min'], [120, '2 min'], [210, '3.5 min'], [300, '5 min'], [600, '10 min']];

  /* ================================================== pure (and tested) */

  function num(v) { v = Number(v); return isFinite(v) ? v : NaN; }

  /** The badge's state from the station's state: idle | arming | live |
   *  problem | off | absent | unknown - and why, in one sentence. */
  function badgeOf(st, failure) {
    if (failure && failure.absent) return {state: 'absent', why: 'PineLive is not on this station yet.'};
    if (!st) return {state: 'unknown', why: failure ? 'The station did not answer: ' + failure.message : 'Reading the station...'};
    if (st.enabled === false) return {state: 'off', why: 'The MX Live event is switched off.'};
    var phase = String(st.phase || 'idle');
    var src = st.source || {};
    var armed = !!st.armed || phase === 'arming' || phase === 'live' || phase === 'fallback' || phase === 'stopping';
    if (!armed) return {state: 'idle', why: 'MX Live is ready. Tap to open PineLive.'};
    var latest = (Array.isArray(st.errors) && st.errors[0]) || null;
    if (st.host && st.host.up === false) return {state: 'problem', why: 'The PineLive host service is not answering' + (st.host.why ? ': ' + st.host.why : '.')};
    if (phase === 'fallback') return {state: 'problem', why: 'The input dropped out; the station has the air' + (latest && latest.say ? ' - ' + latest.say : '.')};
    if (src.connected === false) return {state: 'problem', why: 'The input is not connected' + (latest && latest.say ? ' - ' + latest.say : '.')};
    if (src.clipping) return {state: 'problem', why: 'The input is clipping.'};
    if (phase === 'live' && src.signal === false) return {state: 'problem', why: 'No signal is arriving from the input.'};
    if (phase === 'arming') return {state: 'arming', why: 'Armed - waiting for the first real audio.'};
    if (phase === 'stopping') return {state: 'arming', why: 'Stopping - closing the last cut.'};
    return {state: 'live', why: 'LIVE - the input is the music on air.'};
  }

  var PHASE_WORDS = {idle: 'Idle', arming: 'Arming', live: 'LIVE', fallback: 'Fallback', stopping: 'Stopping'};
  function phaseWord(st) {
    if (!st) return '...';
    if (st.enabled === false) return 'Off';
    return PHASE_WORDS[String(st.phase || 'idle')] || String(st.phase || 'idle');
  }

  function fmtDur(s) {
    s = Math.max(0, Math.floor(num(s) || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    var two = function (n) { return (n < 10 ? '0' : '') + n; };
    return h ? h + ':' + two(m) + ':' + two(x) : m + ':' + two(x);
  }

  function fmtAgo(s) {
    s = num(s);
    if (!isFinite(s)) return 'never';
    if (s < 1.5) return 'just now';
    if (s < 90) return Math.round(s) + ' s ago';
    if (s < 5400) return Math.round(s / 60) + ' min ago';
    return Math.round(s / 3600) + ' h ago';
  }

  function fmtClock(at) {
    at = num(at);
    if (!isFinite(at) || at <= 0) return '';
    var d = new Date(at * 1000);
    var two = function (n) { return (n < 10 ? '0' : '') + n; };
    return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
  }

  function fmtDbShort(db) {
    db = num(db);
    if (!isFinite(db)) return '--';
    if (db <= -99) return '-inf';
    return (db > 0 ? '+' : '') + db.toFixed(1);
  }

  /** The panels that are open, per viewer (this screen's localStorage). */
  function readPanels(storage) {
    var out = {};
    for (var k in DEFAULT_OPEN) if (Object.prototype.hasOwnProperty.call(DEFAULT_OPEN, k)) out[k] = DEFAULT_OPEN[k];
    try {
      var raw = storage && storage.getItem(PANELS_KEY);
      var saved = raw ? JSON.parse(raw) : null;
      if (saved && typeof saved === 'object') {
        for (var key in saved) if (Object.prototype.hasOwnProperty.call(out, key) || /^sub:/.test(key)) out[key] = !!saved[key];
      }
    } catch (err) { /* a locked profile gets the defaults */ }
    return out;
  }

  function writePanels(storage, open) {
    try { if (storage) storage.setItem(PANELS_KEY, JSON.stringify(open)); } catch (err) { /* private mode */ }
  }

  /** What a refusal code means for the operator, and what can be done. */
  function refusal(code) {
    switch (String(code || '')) {
      case 'station_paused': return {retry: 'unpause', words: 'The station is paused (off air).'};
      case 'station_off': return {words: 'The show is switched off. Turn the station on first.'};
      case 'disabled': return {words: 'The MX Live event is switched off.'};
      case 'no_host': return {words: 'The PineLive host service is not answering.', trouble: true};
      case 'no_device': return {words: 'No ready USB capture device.', trouble: true};
      case 'already_live': return {words: 'A set is already running.'};
      case 'device_busy': return {words: 'Another program holds the capture.', trouble: true};
      case 'open_failed': return {words: 'The capture would not open.', trouble: true};
      default: return {words: ''};
    }
  }

  /** The stereo pairs a device with `channels` channels offers. */
  function pairsFor(channels) {
    channels = Math.max(2, Math.floor(num(channels) || 2));
    var out = [];
    for (var c = 1; c + 1 <= channels; c += 2) out.push([c, c + 1]);
    return out;
  }

  /** Which device the popup is about: the chosen one, else the first
   *  ready USB capture, else the first USB device at all. */
  function chosenDevice(devices, settings, st) {
    var list = (devices && devices.usb) || [];
    var want = (settings && settings.device) || (st && st.source && st.source.kind === 'usb' && st.source.device) || '';
    var i;
    if (want) for (i = 0; i < list.length; i += 1) if (list[i].id === want) return list[i];
    /* [plair] nothing chosen: the instrument by its USB descriptor, not the
     * first ready row (a keyboard dongle's 8 kHz mic sits ahead of the K.O. Sidekick) */
    var G = root.PineLiveGuide;
    if (G && G.pickInstrument) { var inst = G.pickInstrument(devices); if (inst) return inst; }
    for (i = 0; i < list.length; i += 1) if (list[i].capture && list[i].status === 'ready') return list[i];
    return list[0] || null;
  }

  /* ================================================== the station road */

  function httpPage() {
    try { return /^https?:$/.test(String(root.location && root.location.protocol)); } catch (err) { return false; }
  }

  function bridge() {
    var b = root.pineDesktop;
    return b && typeof b.get === 'function' ? b : null;
  }

  /* The set's rule (script-page.js stationUrl, hot-corners.js): on a page
   * the station served, a station path is already right; on the desk's
   * file: page, the chrome knows the station's base. */
  function stationUrl(u) {
    u = String(u || '');
    if (!u || /^(https?|wss?|blob|data):/i.test(u)) return u;
    if (httpPage()) return u;
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (err) { b = ''; }
    return (b || 'http://127.0.0.1:8096').replace(/\/$/, '') + u;
  }

  function stationKey() {
    try { if (typeof root.key === 'function') { var k = root.key(); if (typeof k === 'string' && k) return k; } } catch (err) { /* not the panel page */ }
    try { /* the panel's own `const SERVER_KEY` is a global lexical binding, not a window property */
      /* eslint-disable-next-line no-undef */
      if (typeof SERVER_KEY === 'string' && SERVER_KEY) return SERVER_KEY;
    } catch (err) { /* not declared on this page */ }
    try { return String(root.__PINE_VIDEO_EDITOR_KEY || root.PINE_KEY || ''); } catch (err) { return ''; }
  }

  function withTimeout(promise, ms, what) {
    return new Promise(function (resolve, reject) {
      var done = false;
      var timer = root.setTimeout(function () {
        if (done) return;
        done = true;
        reject(new Error(what + ' took longer than ' + Math.round(ms / 1000) + ' s'));
      }, ms);
      Promise.resolve(promise).then(function (v) {
        if (done) return; done = true; root.clearTimeout(timer); resolve(v);
      }, function (e) {
        if (done) return; done = true; root.clearTimeout(timer); reject(e);
      });
    });
  }

  function isAbsent(err) {
    var m = String((err && err.message) || err || '');
    return /(^|\b)404\b|not found/i.test(m);
  }

  /* The desk's page is file: and the station answers a cross-origin
   * preflight with 405, so there every call goes through the desk's own
   * bridge (it holds the key). The tablet's bridge does the same through
   * the native side, which also keeps these calls out of the WebView's
   * six-socket pool (#1324). A page with no bridge fetches directly. */
  function request(method, path, body) {
    var b = bridge();
    var fn = b && (method === 'GET' ? b.get : method === 'POST' ? b.post : method === 'PUT' ? b.put : b.del);
    if (fn) return withTimeout(fn.call(b, path, method === 'GET' ? undefined : (body || {})), REQUEST_MS, path);
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to the station on this screen'));
    var headers = {};
    var key = stationKey();
    if (key) headers.Authorization = 'Bearer ' + key;
    if (method !== 'GET') headers['Content-Type'] = 'application/json';
    var ctl = typeof root.AbortController === 'function' ? new root.AbortController() : null;
    var timer = ctl ? root.setTimeout(function () { try { ctl.abort(); } catch (err) { /* done */ } }, REQUEST_MS) : 0;
    return root.fetch(stationUrl(path), {method: method, headers: headers, cache: 'no-store',
      body: method === 'GET' ? undefined : JSON.stringify(body || {}), signal: ctl ? ctl.signal : undefined})
      .then(function (res) {
        return res.text().then(function (text) {
          var data = {};
          try { data = text ? JSON.parse(text) : {}; } catch (err) { data = {detail: text.slice(0, 200)}; }
          if (!res.ok) throw new Error(String((data && (data.detail || data.say)) || (res.status + ' ' + res.statusText)));
          return data;
        });
      }, function (err) {
        throw new Error(err && err.name === 'AbortError' ? path + ' took longer than ' + Math.round(REQUEST_MS / 1000) + ' s' : String((err && err.message) || err));
      })
      .then(function (v) { if (timer) root.clearTimeout(timer); return v; },
        function (e) { if (timer) root.clearTimeout(timer); throw e; });
  }

  function get(path) { return request('GET', path); }
  function post(path, body) { return request('POST', path, body); }

  function openOutside(url) {
    url = stationUrl(url);
    try {
      var b = root.pineDesktop;
      if (b && typeof b.openExternal === 'function') { b.openExternal(url); return; }
    } catch (err) { /* fall through */ }
    try { root.open(url, '_blank', 'noopener'); } catch (err) { /* nothing more to try */ }
  }

  /* ================================================== small DOM helpers */

  function make(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function icon(name, label) {
    try { if (typeof root.pineIcon === 'function') return root.pineIcon(name, label) || ''; } catch (err) { /* text fallback */ }
    return '';
  }

  function iconNode(name, label) {
    var span = make('span', 'pl-ico');
    var markup = icon(name, label);
    if (markup) span.innerHTML = markup;
    span.setAttribute('aria-hidden', label ? 'false' : 'true');
    return span;
  }

  function setText(node, text) {
    text = text === undefined || text === null ? '' : String(text);
    if (node && node.textContent !== text) node.textContent = text;
  }

  function setClass(node, cls, on) {
    if (node && node.classList.contains(cls) !== !!on) node.classList.toggle(cls, !!on);
  }

  function setHidden(node, hidden) {
    if (node && node.hidden !== !!hidden) node.hidden = !!hidden;
  }
  /* [vcrfx] setHidden for a picture: PineVcr.set is idempotent per state,
     so the four-a-second paint costs nothing once the picture has settled. */
  function vcrHidden(node, hidden) {
    var V = root.PineVcr;
    if (!node || !V || typeof V.set !== 'function') { setHidden(node, hidden); return; }
    V.set(node, !hidden, {
      show: function (el) { el.hidden = false; },
      hide: function (el) { el.hidden = true; }
    });
  }

  function btn(cls, words, iconName, title) {
    var b = make('button', 'pl-btn' + (cls ? ' ' + cls : ''));
    b.type = 'button';
    if (iconName) b.appendChild(iconNode(iconName));
    if (words) b.appendChild(make('span', 'pl-btn-words', words));
    if (title) { b.title = title; b.setAttribute('aria-label', title); }
    return b;
  }

  /* An editor the repaint must not overwrite while the operator's hand is
   * on it: marked from pointerdown/focus until a moment after it lets go. */
  function guard(input) {
    var release = 0;
    var hold = function () { input.__editing = true; if (release) root.clearTimeout(release); };
    var letGo = function () {
      if (release) root.clearTimeout(release);
      release = root.setTimeout(function () { input.__editing = false; }, 1500);
    };
    input.addEventListener('pointerdown', hold);
    input.addEventListener('focus', hold);
    input.addEventListener('pointerup', letGo);
    input.addEventListener('blur', letGo);
    input.addEventListener('change', letGo);
    return input;
  }

  function toggle(labelText, caption, onFlip) {
    var row = make('div', 'pl-row pl-toggle-row');
    var text = make('div', 'pl-row-text');
    text.appendChild(make('b', '', labelText));
    var cap = make('small', '', caption || '');
    text.appendChild(cap);
    var sw = make('button', 'pl-switch');
    sw.type = 'button';
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', 'false');
    sw.setAttribute('aria-label', labelText);
    sw.appendChild(make('i'));
    sw.addEventListener('click', function (e) {
      e.stopPropagation();
      var next = sw.getAttribute('aria-checked') !== 'true';
      onFlip(next, sw);
    });
    row.appendChild(text);
    row.appendChild(sw);
    return {root: row, sw: sw, caption: cap,
      set: function (on) { var v = on ? 'true' : 'false'; if (sw.getAttribute('aria-checked') !== v) sw.setAttribute('aria-checked', v); },
      busy: function (on) { setClass(sw, 'busy', on); sw.disabled = !!on; }};
  }

  function segmented(options, onPick, labelText) {
    var box = make('div', 'pl-seg');
    box.setAttribute('role', 'radiogroup');
    if (labelText) box.setAttribute('aria-label', labelText);
    var buttons = options.map(function (opt) {
      var b = make('button', '', opt.label);
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', 'false');
      if (opt.title) b.title = opt.title;
      b.__value = opt.value;
      b.addEventListener('click', function (e) { e.stopPropagation(); onPick(opt.value, b); });
      box.appendChild(b);
      return b;
    });
    return {root: box, buttons: buttons, set: function (value) {
      var key = JSON.stringify(value);
      buttons.forEach(function (b) {
        var on = JSON.stringify(b.__value) === key ? 'true' : 'false';
        if (b.getAttribute('aria-checked') !== on) b.setAttribute('aria-checked', on);
      });
    }};
  }

  function slider(opts, onValue) {
    var row = make('div', 'pl-row pl-slider-row');
    var text = make('div', 'pl-row-text');
    text.appendChild(make('b', '', opts.label));
    if (opts.caption) text.appendChild(make('small', '', opts.caption));
    var ctl = make('div', 'pl-slider');
    var input = guard(make('input'));
    input.type = 'range';
    input.min = String(opts.min); input.max = String(opts.max); input.step = String(opts.step || 1);
    input.setAttribute('aria-label', opts.label);
    var out = make('output', 'pl-slider-out', '--');
    ctl.appendChild(input);
    ctl.appendChild(out);
    if (opts.reset !== undefined) {
      var zero = btn('pl-mini', opts.resetLabel || String(opts.reset), null, 'Reset ' + opts.label + ' to ' + (opts.resetLabel || opts.reset));
      zero.addEventListener('click', function (e) {
        e.stopPropagation();
        input.value = String(opts.reset);
        out.textContent = opts.fmt(Number(opts.reset));
        onValue(Number(opts.reset), true);
      });
      ctl.appendChild(zero);
    }
    input.addEventListener('input', function () { out.textContent = opts.fmt(Number(input.value)); onValue(Number(input.value), false); });
    input.addEventListener('change', function () { onValue(Number(input.value), true); });
    row.appendChild(text);
    row.appendChild(ctl);
    return {root: row, input: input, set: function (v) {
      v = num(v);
      if (!isFinite(v) || input.__editing) return;
      if (String(input.value) !== String(v)) input.value = String(v);
      setText(out, opts.fmt(v));
    }};
  }

  function numberRow(opts, onValue) {
    var row = make('div', 'pl-row pl-number-row');
    var text = make('div', 'pl-row-text');
    text.appendChild(make('b', '', opts.label));
    if (opts.caption) text.appendChild(make('small', '', opts.caption));
    var wrap = make('div', 'pl-number');
    var input = guard(make('input'));
    input.type = 'number';
    input.min = String(opts.min); input.max = String(opts.max); input.step = String(opts.step || 1);
    input.inputMode = 'decimal';
    input.setAttribute('aria-label', opts.label);
    wrap.appendChild(input);
    if (opts.unit) wrap.appendChild(make('span', 'pl-unit', opts.unit));
    input.addEventListener('change', function () {
      var v = num(input.value);
      if (!isFinite(v)) return;
      v = Math.max(opts.min, Math.min(opts.max, v));
      input.value = String(v);
      onValue(v);
    });
    row.appendChild(text);
    row.appendChild(wrap);
    return {root: row, input: input, set: function (v) {
      v = num(v);
      if (!isFinite(v) || input.__editing || document.activeElement === input) return;
      if (String(input.value) !== String(v)) input.value = String(v);
    }};
  }

  function fact(grid, labelText) {
    var cell = make('div', 'pl-fact');
    cell.appendChild(make('small', '', labelText));
    var val = make('b', '', '--');
    cell.appendChild(val);
    grid.appendChild(cell);
    return val;
  }

  function subgroup(key, title, iconName) {
    var box = make('div', 'pl-sub');
    var head = make('button', 'pl-sub-head');
    head.type = 'button';
    head.appendChild(iconNode('c:caret--right'));
    if (iconName) head.appendChild(iconNode(iconName));
    head.appendChild(make('span', '', title));
    var body = make('div', 'pl-sub-body');
    box.appendChild(head);
    box.appendChild(body);
    var id = 'sub:' + key;
    function paint() {
      var open = !!ui.open[id];
      setClass(box, 'open', open);
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
      setHidden(body, !open);
    }
    head.addEventListener('click', function (e) {
      e.stopPropagation();
      ui.open[id] = !ui.open[id];
      writePanels(storage(), ui.open);
      paint();
    });
    paint();
    return {root: box, body: body};
  }

  function storage() {
    try { return root.localStorage || null; } catch (err) { return null; }
  }

  function readPrefs() {
    try { var raw = storage() && storage().getItem(PREFS_KEY); return raw ? JSON.parse(raw) || {} : {}; }
    catch (err) { return {}; }
  }

  function writePrefs() {
    try { if (storage()) storage().setItem(PREFS_KEY, JSON.stringify(ui.prefs)); } catch (err) { /* private */ }
  }

  /* ================================================== the model */

  var model = {
    state: null, failure: null, stateAt: 0,
    settings: null, devices: null, devicesAt: 0,
    trouble: null, troubleAt: 0, troubleBusy: false,
    shelf: null, guideDocs: {}, libPages: {},
    testing: 0, lastSay: ''
  };

  var ui = {
    built: false, pop: null, body: null, badge: null, panels: {}, open: readPanels(storage()),
    prefs: readPrefs(), visible: false, pollTimer: 0, polling: false, troubleTimer: 0,
    levels: null, levelsFailed: 0, levelsRefused: false, levelsRetry: 0, levelsGotAny: false,
    scope: null, scopeSeen: true, io: null, monitor: null, lightbox: null, picked: '',
    unwatch: null, unback: null, confirmUntil: {}, saveTimers: {}
  };

  function applyAnswer(ans) {
    if (ans && ans.state && typeof ans.state === 'object') { model.state = ans.state; model.stateAt = Date.now(); model.failure = null; }
    if (ans && ans.settings && typeof ans.settings === 'object') model.settings = ans.settings;
    return ans;
  }

  /* ================================================== polling */

  function schedulePoll(ms) {
    if (ui.pollTimer) root.clearTimeout(ui.pollTimer);
    ui.pollTimer = root.setTimeout(pollState, ms);
  }

  function nextDelay() {
    if (model.failure && model.failure.absent) return POLL_ABSENT_MS;
    if (model.failure) return ui.visible ? 4000 : POLL_ERROR_MS;
    return (ui.visible || (model.state && model.state.armed)) ? POLL_OPEN_MS : POLL_CLOSED_MS;   /* [plcount] */
  }

  function pollState() {
    ui.pollTimer = 0;
    if (ui.polling) return;
    var hidden = false;
    try { hidden = !!document.hidden; } catch (err) { hidden = false; }
    if (hidden && !ui.visible) { schedulePoll(POLL_CLOSED_MS); return; }
    ui.polling = true;
    get('/api/pinelive/state').then(function (st) {
      ui.polling = false;
      model.state = st || {};
      model.failure = null;
      model.stateAt = Date.now();
      paint();
      syncLevels();
      try { paintCountdown(); } catch (err) { /* [plcount] never breaks the poll */ }
      try { djDuckSync(); } catch (err) { /* [plduck] never breaks the poll */ }
      schedulePoll(nextDelay());
    }, function (err) {
      ui.polling = false;
      model.failure = {message: String((err && err.message) || err), absent: isAbsent(err)};
      if (model.failure.absent) model.state = null;
      paint();
      syncLevels();
      schedulePoll(nextDelay());
    });
  }

  function refreshDevices(fresh) {
    return get('/api/pinelive/devices' + (fresh ? '?fresh=1' : '')).then(function (d) {
      model.devices = d || {};
      model.devicesAt = Date.now();
      paint();
      return d;
    }, function (err) {
      model.devices = model.devices || {error: String((err && err.message) || err)};
      paint();
    });
  }

  function refreshSettings() {
    return get('/api/pinelive/settings').then(function (s) {
      model.settings = (s && s.settings) || s || {};
      paint();
    }, function () { /* the state still carries most of it */ });
  }

  function troubleDevice() {
    if (ui.prefs.troubleDevice) return ui.prefs.troubleDevice;
    /* [pldetect] with nothing chosen, grade the PROFILE-MATCHING instrument,
     * not the first capture row (today that row is a mono 8 kHz headset
     * dongle, and grading it would print the wrong device's numbers) */
    var G = root.PineLiveGuide;
    if (!(model.settings && model.settings.device) && G && G.pickInstrument) {
      var inst = G.pickInstrument(model.devices);
      if (inst) return inst.id;
    }
    var dev = chosenDevice(model.devices, model.settings, model.state);
    return (dev && dev.id) || '';
  }

  function refreshTrouble() {
    if (model.troubleBusy) return Promise.resolve(model.trouble);
    model.troubleBusy = true;
    paint();
    var dev = troubleDevice();
    return get('/api/pinelive/troubleshoot' + (dev ? '?device=' + encodeURIComponent(dev) : '')).then(function (t) {
      model.troubleBusy = false;
      model.trouble = t || {};
      model.troubleAt = Date.now();
      paint();
      return t;
    }, function (err) {
      model.troubleBusy = false;
      model.trouble = {error: String((err && err.message) || err), checks: (model.trouble && model.trouble.checks) || []};
      paint();
    });
  }

  function scheduleTrouble() {
    if (ui.troubleTimer) { root.clearTimeout(ui.troubleTimer); ui.troubleTimer = 0; }
    if (!ui.visible || !ui.open.troubleshoot || !ui.prefs.troubleAuto) return;
    ui.troubleTimer = root.setTimeout(function () {
      ui.troubleTimer = 0;
      refreshTrouble().then(scheduleTrouble, scheduleTrouble);
    }, TROUBLE_EVERY_MS);
  }

  /* ================================================== actions */

  function say(text, kind) {
    model.lastSay = String(text || '');
    if (!ui.built) return;
    setText(ui.sayLine, model.lastSay);
    ui.sayLine.className = 'pl-say' + (kind ? ' ' + kind : '');
    setHidden(ui.sayLine, !model.lastSay);
  }

  function act(path, body, busyNode) {
    if (busyNode) { busyNode.disabled = true; setClass(busyNode, 'busy', true); }
    return post(path, body).then(function (ans) {
      if (busyNode) { busyNode.disabled = false; setClass(busyNode, 'busy', false); }
      applyAnswer(ans);
      if (ans && ans.ok === false) say(ans.say || 'The station refused that.', 'bad');
      else if (ans && ans.say) say(ans.say, '');
      paint();
      return ans || {};
    }, function (err) {
      if (busyNode) { busyNode.disabled = false; setClass(busyNode, 'busy', false); }
      say('The station did not take that: ' + String((err && err.message) || err), 'bad');
      paint();
      return {ok: false, say: String((err && err.message) || err), code: 'request_failed'};
    });
  }

  function saveSetting(key, value, delay) {
    if (!model.settings) model.settings = {};
    model.settings[key] = value;
    if (ui.saveTimers[key]) root.clearTimeout(ui.saveTimers[key]);
    ui.saveTimers[key] = root.setTimeout(function () {
      ui.saveTimers[key] = 0;
      var body = {};
      body[key] = value;
      act('/api/pinelive/settings', body);
    }, delay || 0);
  }

  /* [plroad] WHICH ROAD THE SOUND TAKES. "the spark is unable to detect my
   * interface" (the operator, 2026-10-01) - the third time a remembered
   * Network choice (this screen's prefs, or the last set's source on the
   * server) sent every start and every Detect down the network road while
   * the K.O. Sidekick sat on the USB list, ready, and nothing opened it.
   * The hardware outranks the memory: on the network road with NO sender
   * connected, a ready instrument on USB takes the USB road - and the
   * switch says so, because the pref is moved to match. A connected sender
   * keeps the network road; so does a bus with no instrument on it, and so
   * does Network picked on this screen since it opened - only a REMEMBERED
   * choice is overruled, never one just made. */
  function liveRoad() {
    var st = model.state || {};
    var road = ui.prefs.road || (st.source && st.source.kind) || 'usb';
    if (road !== 'network') return 'usb';
    if (ui.roadPicked) return 'network';
    var net = (model.devices && model.devices.network) || {};
    if (net.sender) return 'network';
    var G = root.PineLiveGuide;
    var inst = G && G.pickInstrument ? G.pickInstrument(model.devices) : null;
    if (!inst || inst.status !== 'ready') return 'network';
    ui.prefs.road = 'usb';
    writePrefs();
    return 'usb';
  }

  function goLive(unpause) {
    var st = model.state || {};
    var road = liveRoad();
    var body = {source: road};
    if (road === 'usb') {
      var dev = (model.settings && model.settings.device) || '';
      if (dev) body.device = dev;
    }
    if (unpause) body.unpause = true;
    ui.refused = null;
    return act('/api/pinelive/start', body, ui.goBtn).then(function (ans) {
      if (ans && ans.ok === false) ui.refused = {code: ans.code || '', say: ans.say || ''};
      paint();
    });
  }

  function endSet() {
    return act('/api/pinelive/stop', {}, ui.goBtn);
  }

  /* [plair] "If I tap this, stop the current track on the broadcast and play
   * the interface in its place ... mixed with the DJ's ducking and sound
   * effects": the ON-AIR test - the set's own road, never recorded, ended by
   * a second tap or by itself after ten minutes. */
  function airTest() {
    var st = model.state || {};
    if (st.armed && st.event && st.event.rehearse) return act('/api/pinelive/stop', {}, null);
    var road = liveRoad();
    var body = {source: road, rehearse: true};
    if (road === 'usb' && model.settings && model.settings.device) body.device = model.settings.device;
    return act('/api/pinelive/start', body, null);
  }

  function runTest() {
    var dev = troubleDevice() || ((model.settings && model.settings.device) || '');
    model.testing = Date.now();
    paint();
    return act('/api/pinelive/test', dev ? {device: dev} : {}).then(function () {
      root.setTimeout(function () {
        model.testing = 0;
        paint();
        if (ui.visible && ui.open.troubleshoot) refreshTrouble();
      }, 4600);
    });
  }

  /* A second tap within three seconds confirms: ending a performance by a
   * stray tap on a nine-inch screen is the one thing this popup must not
   * make easy. */
  function confirmTap(key, node, words, then) {
    var now = Date.now();
    if (ui.confirmUntil[key] && now < ui.confirmUntil[key]) {
      ui.confirmUntil[key] = 0;
      then();
      return;
    }
    ui.confirmUntil[key] = now + 3000;
    if (node) {
      node.__confirmWords = words;
      setClass(node, 'confirm', true);
    }
    paint();
    root.setTimeout(function () {
      if (ui.confirmUntil[key] && Date.now() >= ui.confirmUntil[key]) { ui.confirmUntil[key] = 0; paint(); }
    }, 3100);
  }

  /* ================================================== [pltoggle] the header's switches */
  /* Three switches in the header, each the SAME road as its section twin:
   *   PineCam to live = Picture, Video to Tailscale listeners (settings.tailscale_video)
   *   Pine Live       = Event, MX Live event - the [plair] switch IS the set
   *   Album recording = Recording (settings.record, remembered for the next set)
   * One model value paints both twins; one function flips both. */
  function tailscaleOn() {
    var s = model.settings || {};
    var pic = (model.state && model.state.picture) || {};
    return s.tailscale_video !== undefined ? !!s.tailscale_video : !!pic.tailscale_video;
  }

  function albumOn() {
    var s = model.settings || {};
    var r = (model.state && model.state.recording) || {};
    if (s.record !== undefined) return !!s.record;
    if (r.album !== undefined) return !!r.album;
    return r.on !== false;
  }

  /* immediate: both switches move now, the station stops the public
   * picture now, and the answer's state puts them right if it refused */
  function flipTailscale(next, node) {
    if (!model.settings) model.settings = {};
    model.settings.tailscale_video = next;
    if (model.state && model.state.picture) model.state.picture.tailscale_video = next;
    paint();
    return act('/api/pinelive/settings', {tailscale_video: next}, node);
  }

  /* the [plair] road: on arms the set now on the chosen road (event mode -
   * the interface takes the broadcast as soon as it sounds); off ends it,
   * and only on a second tap */
  function flipSet(next, node) {
    var st = model.state || {};
    if (!next && st.armed) {
      confirmTap('disable', node, 'Tap again to end the set and switch MX Live off', function () {
        act('/api/pinelive/event', {enabled: false}, node);
      });
      return;
    }
    var road = liveRoad();
    var body = {enabled: next, source: road};
    if (road === 'usb' && model.settings && model.settings.device) body.device = model.settings.device;
    act('/api/pinelive/event', body, node);
  }

  /* the station remembers it (settings.record); mid-set it starts or
   * suspends the recording from this moment */
  function flipAlbum(next) {
    saveSetting('record', next);
    paint();
  }

  /* ================================================== [pinestream] PineStream */
  /* "add a section here for enabling a pip stream of the pinetab / pineapp to
   *  be streamed to the stream page. I want users able to enable and disable
   *  it at will like the pinecam and call it pinestream."
   * The switch is settings.stream_on on the same road as PineCam to live
   * (/api/pinelive/settings, remembered by the station); the screen is
   * settings.stream_source. Off by default, and while it is off nothing is
   * captured or served anywhere (pinestream.py). One model value paints the
   * header's switch and the panel's twin; one function flips both. */
  var STREAM_SOURCES = [
    {value: 'pinetab', label: 'PineTab', icon: 'c:screen', title: 'PineStream shows the PineTab\'s screen'},
    {value: 'pineapp', label: 'Pine app', icon: 'c:laptop', title: 'PineStream shows the Pine app\'s window on the desk'}
  ];

  function streamBlock() { return (model.state && model.state.stream) || {}; }

  function streamOn() {
    var s = model.settings || {};
    return s.stream_on !== undefined ? !!s.stream_on : !!streamBlock().on;
  }

  function streamSource() {
    var s = model.settings || {};
    var v = s.stream_source || streamBlock().source || 'pinetab';
    return v === 'pineapp' ? 'pineapp' : 'pinetab';
  }

  function streamSourceName(v) { return (v || streamSource()) === 'pineapp' ? 'the Pine app' : 'the PineTab'; }

  /* immediate, like PineCam to live: both twins move now, the station stops
   * serving now, and the answer's state puts them right if it refused */
  function flipStream(next, node) {
    /* [pinestream-choose] ON asks which screen first: nothing streams without a choice */
    if (next) { openChooser(node); return Promise.resolve({ok: true, say: ''}); }
    closeChooser();
    if (!model.settings) model.settings = {};
    model.settings.stream_on = next;
    if (model.state && model.state.stream) model.state.stream.on = next;
    paint();
    return act('/api/pinelive/settings', {stream_on: next}, node);
  }

  function pickStreamSource(v) {
    if (v !== 'pinetab' && v !== 'pineapp') return;
    saveSetting('stream_source', v);
    paint();
  }

  /* two small icon buttons under one another, the header's height */
  function streamSourcePicker(parent) {
    var box = make('div', 'pl-hsw-src');
    box.setAttribute('role', 'radiogroup');
    box.setAttribute('aria-label', 'Which screen PineStream shows');
    var buttons = STREAM_SOURCES.map(function (o) {
      var b = make('button');
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', 'false');
      b.title = o.title;
      b.setAttribute('aria-label', o.title);
      b.appendChild(iconNode(o.icon));
      b.__value = o.value;
      b.addEventListener('click', function (e) { e.stopPropagation(); pickStreamSource(o.value); });
      box.appendChild(b);
      return b;
    });
    parent.appendChild(box);
    return {root: box, buttons: buttons, set: function (v) {
      buttons.forEach(function (b) {
        var on = b.__value === v ? 'true' : 'false';
        if (b.getAttribute('aria-checked') !== on) b.setAttribute('aria-checked', on);
      });
    }};
  }

  function paintStreamSwitch(h) {
    if (!h || !h.stream) return;
    var on = streamOn();
    var src = streamSource();
    h.stream.set(on);
    var live = on ? 'true' : 'false';
    if (h.stream.root.getAttribute('data-live') !== live) h.stream.root.setAttribute('data-live', live);
    setText(h.stream.label, on ? 'PineStream · LIVE' : 'PineStream');
    h.stream.root.title = on
      ? 'PineStream is LIVE to listeners: they see ' + streamSourceName(src) + ' in a corner of the stream page. Tap to stop it at once - nothing is captured or served while it is off.'
      : 'PineStream is OFF: nothing is captured or served. Tap to show ' + streamSourceName(src) + ' to listeners as a picture-in-picture on the stream page.';
    if (h.streamSrc) paintStreamPicker(h.streamSrc, src, on);   /* [pinestream-choose] inert while off */
    var p = ui.panels && ui.panels.stream;
    if (p && p.chip) {
      setText(p.chip, on ? 'LIVE to listeners' : '');
      setClass(p.chip, 'pl-chip-live', on);
      setHidden(p.chip, !on);
    }
  }

  /* ================================================== [camgrey] PineCam to live, offline */
  /* "grey this out if the camera's offline." The reading is the one this
   * popup already polls: /api/pinelive/state's picture block carries the
   * station's own pinelink_state() - cam_live (state "live" AND fresh, the
   * rule the Pine Cam box uses), cam_state, cam_why and how long ago it was
   * last live. No new poll. Greyed is not disabled: a flip still records the
   * preference and takes effect the moment the camera is back. Unknown (no
   * state yet) is never greyed on a guess. */
  var CAM_STATE_WORDS = {
    'no-link': 'the camera\'s Wi-Fi isn\'t on the air',
    'never-run': 'the camera link has never run on this station',
    'linked': 'the camera is joined but no picture is arriving',
    'joining': 'the camera link is still joining'
  };

  function camLink() {
    var pic = (model.state && model.state.picture) || null;
    if (!pic || pic.cam_live === undefined) return null;
    return {live: !!pic.cam_live, state: String(pic.cam_state || ''), why: String(pic.cam_why || ''),
      seenAgo: pic.cam_seen_ago == null ? NaN : num(pic.cam_seen_ago)};
  }

  function camOfflineWords(c) {
    var why = c.why || CAM_STATE_WORDS[c.state]
      || (c.state === 'live' ? 'its last picture is stale' : c.state ? 'the link says "' + c.state + '"' : 'the link is not live');
    return 'Pine Cam is offline - ' + why + (isFinite(c.seenAgo) ? ' (last seen ' + fmtAgo(c.seenAgo) + ')' : '')
      + '. The switch is kept and takes effect when it reconnects.';
  }

  /* grey `node` (and title `tipNode`) while the camera is not live; `base`
   * is the title it carries when the camera is fine */
  function paintCamGrey(node, tipNode, base) {
    if (!node) return;
    var c = camLink();
    var off = !!(c && !c.live);
    setClass(node, 'pl-cam-offline', off);
    var tip = off ? camOfflineWords(c) + (base ? '\n' + base : '') : (base || '');
    [node, tipNode].forEach(function (n) {
      if (n && n.title !== tip) n.title = tip;
    });
  }

  /* ================================================== [pinestream-choose] which screen */
  /* "grayed out and inert if the pine stream is off. But I do want to be
   * able to select which one I'm streaming whenever I enable the pine
   * stream." Off: both source buttons are inert, the last-used one marked
   * faintly. On: a small chooser anchored to the switch - two big buttons,
   * the last-used preselected and focused; a tap starts streaming that
   * screen. Its X, Escape, BACK or a tap beside it cancel, and PineStream
   * stays OFF: nothing streams without a choice, and nothing auto-starts.
   * No thumbnails: a picture of a screen that is not streaming would mean
   * capturing it while the switch is off. */
  var STREAM_OFF_TIP = 'PineStream is off - turn it on to choose a screen';

  function streamHere() {
    try { var s = root.PineStream && root.PineStream.state(); if (s && s.surface) return s.surface; } catch (err) { /* no agent */ }
    return httpPage() ? 'pinetab' : 'pineapp';
  }

  function chooserLabel(v) {
    var here = streamHere() === v;
    if (v === 'pineapp') return here ? 'Pine app (this desk)' : 'Pine app (the desk)';
    return here ? 'PineTab (this tablet)' : 'PineTab';
  }

  /** {ok, why} for a screen, from the station's check-ins (pinestream.js
   *  says it is there every few seconds; a missing or asleep one says so). */
  function streamSourceReady(v) {
    var src = (streamBlock().sources || {})[v];
    if (!src) return {ok: true, why: ''};
    return {ok: src.ok !== false, why: String(src.why || '')};
  }

  function inertButtons(buttons, on) {
    (buttons || []).forEach(function (b) {
      if (b.__title === undefined) b.__title = b.title || '';
      var dis = !model.state || !on;
      if (b.disabled !== dis) b.disabled = dis;
      var tip = on ? b.__title : STREAM_OFF_TIP;
      if (b.title !== tip) { b.title = tip; b.setAttribute('aria-label', tip); }
    });
  }

  function paintStreamPicker(picker, src, on) {
    picker.set(src);
    inertButtons(picker.buttons, on);
    var off = on ? 'false' : 'true';
    if (picker.root.getAttribute('data-off') !== off) picker.root.setAttribute('data-off', off);
    try { if (ui.chooser) paintChooser(); } catch (err) { /* the chooser never breaks the header */ }
  }

  function openChooser(anchor) {
    closeChooser();
    var host = ui.pop;
    if (!host) return;
    var back = make('div', 'pl-choose-back');
    var card = make('div', 'pl-choose');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'PineStream - which screen');
    card.appendChild(make('b', 'pl-choose-title', 'Stream which screen?'));
    card.appendChild(make('small', 'pl-choose-sub', 'Listeners see it in a corner of the stream page. Nothing streams until you pick one.'));
    var row = make('div', 'pl-choose-row');
    var buttons = {};
    STREAM_SOURCES.forEach(function (o) {
      var b = make('button', 'pl-choose-btn');
      b.type = 'button';
      b.setAttribute('data-source', o.value);
      b.appendChild(iconNode(o.icon));
      b.appendChild(make('b', '', chooserLabel(o.value)));
      var note = make('small', 'pl-choose-note', '');
      b.appendChild(note);
      b.title = 'Stream ' + streamSourceName(o.value) + ' to listeners now';
      b.setAttribute('aria-label', b.title);
      b.addEventListener('click', function (e) { e.stopPropagation(); chooseStream(o.value, b); });
      row.appendChild(b);
      buttons[o.value] = {root: b, note: note};
    });
    card.appendChild(row);
    back.appendChild(card);
    back.addEventListener('click', function (e) { if (e.target === back) { e.stopPropagation(); closeChooser(); } });
    card.addEventListener('click', function (e) { e.stopPropagation(); });
    host.appendChild(back);
    /* anchored under the switch that asked, kept inside the popup */
    try {
      var pr = host.getBoundingClientRect();
      var ar = (anchor || host).getBoundingClientRect();
      var w = card.offsetWidth || 360;
      card.style.top = Math.max(8, Math.round(ar.bottom - pr.top + 6)) + 'px';
      card.style.left = Math.max(8, Math.min(Math.round(ar.left - pr.left - 24), Math.round(pr.width - w - 8))) + 'px';
    } catch (err) { /* the stylesheet's own spot */ }
    var x = null;
    try { if (typeof root.pineCloseX === 'function') x = root.pineCloseX(card, function () { closeChooser(); }, {label: 'Cancel - PineStream stays off'}); } catch (err) { x = null; }
    if (!x) {
      x = btn('pl-choose-x', '', 'c:close--filled', 'Cancel - PineStream stays off');
      x.addEventListener('click', function (e) { e.stopPropagation(); closeChooser(); });
      card.appendChild(x);
    }
    /* Escape is this chooser's before it is the popup's: the window's
     * capture phase runs ahead of every document listener */
    var key = function (e) {
      if (e.key !== 'Escape' && e.key !== 'Esc') return;
      e.preventDefault();
      e.stopPropagation();
      if (e.stopImmediatePropagation) e.stopImmediatePropagation();
      closeChooser();
    };
    root.addEventListener('keydown', key, true);
    ui.chooser = {back: back, card: card, buttons: buttons, key: key, focused: false};
    paintChooser();
    paint();
  }

  function paintChooser() {
    var c = ui.chooser;
    if (!c) return;
    var last = streamSource();
    var other = last === 'pinetab' ? 'pineapp' : 'pinetab';
    var ready = {};
    STREAM_SOURCES.forEach(function (o) {
      var r = streamSourceReady(o.value);
      ready[o.value] = r;
      var b = c.buttons[o.value];
      setClass(b.root, 'unready', !r.ok);
      setText(b.note, r.ok ? (o.value === last ? 'last used' : '') : r.why + ' - you can still pick it');
    });
    /* the last-used screen, unless it cannot stream and the other can */
    var pre = (!ready[last].ok && ready[other].ok) ? other : last;
    STREAM_SOURCES.forEach(function (o) {
      var on = o.value === pre;
      setClass(c.buttons[o.value].root, 'pre', on);
      c.buttons[o.value].root.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    if (!c.focused) {
      c.focused = true;
      try { c.buttons[pre].root.focus({preventScroll: true}); } catch (err) { /* focus is a nicety */ }
    }
  }

  function closeChooser() {
    var c = ui.chooser;
    if (!c) return;
    ui.chooser = null;
    try { root.removeEventListener('keydown', c.key, true); } catch (err) { /* gone */ }
    if (c.back.parentNode) c.back.parentNode.removeChild(c.back);
    paint();
  }

  function chooseStream(v, node) {
    closeChooser();
    if (!model.settings) model.settings = {};
    model.settings.stream_source = v;
    model.settings.stream_on = true;
    if (model.state && model.state.stream) { model.state.stream.on = true; model.state.stream.source = v; }
    paint();
    return act('/api/pinelive/settings', {stream_source: v, stream_on: true}, node);
  }

  function headSwitch(parent, cls, labelText, onFlip) {
    var b = make('button', 'pl-hsw ' + cls);
    b.type = 'button';
    b.setAttribute('role', 'switch');
    b.setAttribute('aria-checked', 'false');
    b.setAttribute('aria-label', labelText);
    var word = make('span', 'pl-hsw-label', labelText);
    var track = make('span', 'pl-hsw-track');
    track.appendChild(make('i'));
    b.appendChild(word);
    b.appendChild(track);
    b.addEventListener('click', function (e) {
      e.stopPropagation();
      onFlip(b.getAttribute('aria-checked') !== 'true', b);
    });
    parent.appendChild(b);
    return {root: b, label: word, set: function (on) {
      var v = on ? 'true' : 'false';
      if (b.getAttribute('aria-checked') !== v) b.setAttribute('aria-checked', v);
    }};
  }

  var HSW_PHASE = {arming: 'armed', live: 'LIVE', fallback: 'fallback', stopping: 'ending'};
  function paintHeadSwitches() {
    var h = ui.hsw;
    if (!h) return;
    var st = model.state;
    var cam = tailscaleOn();
    h.cam.set(cam);
    h.cam.root.title = cam
      ? 'PineCam to live is ON: Tailscale listeners see the Pine Cam during the set. Tap to stop the public picture at once.'
      : 'PineCam to live is OFF: the picture stays on your own screens - the camera keeps capturing. Tap to share it on the Tailscale stream.';
    try { paintCamGrey(h.cam.root, h.cam.root, h.cam.root.title); }   /* [camgrey] */
    catch (err) { if (root.console) root.console.error('[pinelive] camgrey paint failed:', err); }
    var rehearse = !!(st && st.armed && st.event && st.event.rehearse);
    var setOn = !!(st && st.armed) && !rehearse;
    var phase = setOn ? String(st.phase || 'arming') : 'idle';
    var confirming = !!(ui.confirmUntil.disable && Date.now() < ui.confirmUntil.disable);
    h.live.set(setOn);
    if (h.live.root.getAttribute('data-phase') !== phase) h.live.root.setAttribute('data-phase', phase);
    setClass(h.live.root, 'confirm', confirming);
    setText(h.live.label, confirming ? 'Tap again to end' : rehearse ? 'Pine Live · test'
      : setOn ? 'Pine Live · ' + (HSW_PHASE[phase] || phase) : 'Pine Live');
    h.live.root.title = setOn
      ? 'Pine Live is ' + (HSW_PHASE[phase] || phase) + ': the set has the station whenever the interface sounds. Tap twice to end the set.'
      : 'Pine Live: tap to go live - event mode arms and the interface takes the broadcast as soon as it sounds.';
    var album = albumOn();
    h.album.set(album);
    h.album.root.title = album
      ? 'Album recording is ON: the set is written as tracks (split on ' + quietSecs('split_seconds') + ' s of silence), MP3, a folder per set in Live Events. Remembered for the next set.'
      : 'Album recording is OFF: the set still airs and takes the music, nothing is written. Remembered for the next set.';
    try { paintStreamSwitch(h); }                                   /* [pinestream] */
    catch (err) { if (root.console) root.console.error('[pinelive] PineStream switch paint failed:', err); }
    [h.cam, h.stream, h.live, h.album].forEach(function (x) {
      if (!x.root.classList.contains('busy')) x.root.disabled = !st;
    });
    /* the detection box keeps the middle while the row leaves it room */
    var head = h.row.parentNode;
    if (head && ui.visible) {
      var hr = head.getBoundingClientRect();
      var end = Math.max(h.row.getBoundingClientRect().right,
        ui.headClock ? ui.headClock.getBoundingClientRect().right : 0);
      setClass(head, 'pl-head-crowded', hr.width > 0 && end > hr.left + hr.width / 2 - 32);
    }
  }

  /* ================================================== [pltray] the desk's tools */
  /* The desk's status bar carries Crystals, Add sample and Go LIVE; the tablet
   * never had that footer. On a screen without #statusBar they ride the base
   * bar beside the mic, on the desk's own station calls. */
  function trayIcon(name, fallback) {
    var span = make('span', 'pl-tray-ico');
    var markup = icon(name, '');
    if (markup) span.innerHTML = markup; else span.textContent = fallback;
    return span;
  }

  function trayButton(cls, iconName, fallback, title, onClick) {
    var b = make('button', 'pl-tray-b ' + cls);
    b.type = 'button';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.appendChild(trayIcon(iconName, fallback));
    b.addEventListener('click', function (e) {
      /* the bar opens its audit list on any click it does not know */
      e.stopPropagation();
      e.preventDefault();
      onClick();
    });
    return b;
  }

  function attachTray(bar) {
    if (!bar || bar.querySelector('.pl-tray')) return;
    if (document.getElementById('statusBar')) return;       /* the desk has its own */
    var tray = make('span', 'pl-tray');
    tray.appendChild(trayButton('gem', 'c:gem', 'C', 'Crystals - the station\'s crystal cabinet', function () {
      if (typeof root.crystalOpen !== 'function') return;
      /* [pltray2] the station builds the crystal box at z 146 - under the full-screen
       * view host (z 2147483000); lift it just above, below the base bar */
      Promise.resolve(root.crystalOpen()).then(function () {
        var box = document.getElementById('crystalBox');
        if (box) box.style.zIndex = '2147483001';
      }, function () {});
    }));
    tray.appendChild(trayButton('sample', 'm:movie', 'S', 'Add sample - paste a link, cut moments into the DJs\' rotation', openSampleSheet));
    tray.appendChild(trayButton('golive', 'c:satellite', 'L', 'Go LIVE - the public listen link', openShareSheet));
    /* [plbar] the right corner, before the terminal button - where the desk keeps them */
    bar.insertBefore(tray, bar.querySelector('.pine-console-more') || null);
  }

  function traySheet(title) {
    var old = document.getElementById('plTraySheet');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var back = make('div', 'pl-tray-back');
    back.id = 'plTraySheet';
    var sheet = make('div', 'pl-tray-sheet');
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-label', title);
    var head = make('div', 'pl-tray-head');
    head.appendChild(make('span', '', title));
    var x = btn('', '', 'c:close', 'Close');
    if (!x.textContent && !x.querySelector('svg')) x.textContent = 'X';
    head.appendChild(x);
    sheet.appendChild(head);
    var body = make('div', 'pl-tray-body');
    sheet.appendChild(body);
    back.appendChild(sheet);
    var close = function () { if (back.parentNode) back.parentNode.removeChild(back); if (back.__onclose) back.__onclose(); };
    x.addEventListener('click', function (e) { e.stopPropagation(); close(); });
    back.addEventListener('click', function (e) { if (e.target === back) close(); });
    sheet.addEventListener('click', function (e) { e.stopPropagation(); });
    document.body.appendChild(back);
    return {back: back, body: body, close: close};
  }

  function copyText(text) {
    try { if (root.navigator && root.navigator.clipboard) return root.navigator.clipboard.writeText(text); } catch (err) { /* fall through */ }
    try {
      var t = make('textarea', '');
      t.value = text;
      document.body.appendChild(t);
      t.select();
      document.execCommand('copy');
      document.body.removeChild(t);
    } catch (err) { /* nothing more to try */ }
    return Promise.resolve();
  }

  function openShareSheet() {
    var s = traySheet('Go LIVE - the public listen link');
    /* [pinestream-veil] a tune-in link on the glass: PineStream shows "Private screen" */
    s.back.setAttribute('data-pine-private', 'a tune-in link is on the screen');
    var line = make('p', 'pl-muted', 'Checking for a public link...');
    var link = make('input', 'pl-tray-input');
    link.readOnly = true;
    link.hidden = true;
    var row = make('div', 'pl-actions');
    var makeB = btn('', 'Make a public listen link', 'c:satellite');
    var copyB = btn('', 'Copy the link', 'c:copy');
    var endB = btn('', 'End the public broadcast', 'c:close');
    [makeB, copyB, endB].forEach(function (b) { b.hidden = true; row.appendChild(b); });
    s.body.appendChild(line);
    s.body.appendChild(link);
    s.body.appendChild(row);
    var show = function (url) {
      link.value = url || '';
      link.hidden = !url;
      copyB.hidden = endB.hidden = !url;
      makeB.hidden = !!url;
      line.textContent = url ? 'The station is public - anyone with this link can listen.' : 'No public listen link is out.';
    };
    get('/api/share').then(function (r) {
      var l = ((r && r.links) || [])[0];
      show((l && l.url) || '');
    }, function (err) { line.textContent = 'The station did not answer: ' + (err && err.message || err); makeB.hidden = false; });
    makeB.addEventListener('click', function () {
      makeB.disabled = true;
      post('/api/share', {scope: 'listen'}).then(function (m) {
        var u = (m && (m.url || (m.urls && m.urls[0] && m.urls[0].url))) || '';
        show(u);
        if (u) copyText(u);
        makeB.disabled = false;
      }, function (err) { line.textContent = 'No link: ' + (err && err.message || err); makeB.disabled = false; });
    });
    copyB.addEventListener('click', function () {
      copyText(link.value);
      line.textContent = 'Copied - the link is on the clipboard.';
    });
    endB.addEventListener('click', function () {
      confirmTap('shareEnd', endB, 'Tap again to end the public broadcast - every listen link stops', function () {
        post('/api/share/revoke', {all: true}).then(function () { show(''); }, function (err) { line.textContent = err && err.message || String(err); });
      });
    });
  }

  function openSampleSheet() {
    var s = traySheet('Add sample - cut moments into the DJs\' rotation');
    var url = make('input', 'pl-tray-input');
    url.placeholder = 'Paste a link - a video or a clip page';
    var fetchB = btn('', 'Fetch', 'c:download');
    var status = make('p', 'pl-muted', '');
    var audio = make('audio', 'pl-tray-audio');
    audio.controls = true;
    audio.hidden = true;
    var marks = make('div', 'pl-actions');
    var inB = btn('', 'Mark IN', 'c:skip-back');
    var outB = btn('', 'Mark OUT', 'c:skip-forward');
    var cutB = btn('', 'Extract all', 'c:cut');
    marks.appendChild(inB);
    marks.appendChild(outB);
    marks.appendChild(cutB);
    marks.hidden = true;
    var ranges = make('div', 'pl-tray-list');
    var staged = make('div', 'pl-tray-list');
    var folder = make('input', 'pl-tray-input');
    folder.hidden = true;
    try { folder.value = root.localStorage.getItem('pineSampleFolder') || 'Samples'; } catch (err) { folder.value = 'Samples'; }
    var saveB = btn('', 'Save the batch', 'c:save');
    saveB.hidden = true;
    [url, fetchB, status, audio, marks, ranges, staged, folder, saveB].forEach(function (n) { s.body.appendChild(n); });
    var job = '', a = -1, list = [], timer = 0, t0 = 0;
    s.back.__onclose = function () { if (timer) root.clearTimeout(timer); try { audio.pause(); } catch (err) { /* gone */ } };
    var fmt = function (x) { return (Math.round(x * 10) / 10).toFixed(1) + ' s'; };
    var paintRanges = function () {
      ranges.innerHTML = '';
      list.forEach(function (r, i) {
        var row = make('div', 'pl-tray-row');
        row.appendChild(make('span', '', 'Moment ' + (i + 1) + ': ' + fmt(r.a) + ' - ' + fmt(r.b)));
        var x = btn('', 'Drop', '');
        x.addEventListener('click', function () { list.splice(i, 1); paintRanges(); });
        row.appendChild(x);
        ranges.appendChild(row);
      });
      cutB.disabled = !list.length;
    };
    var poll = function () {
      timer = 0;
      if (Date.now() - t0 > 900000) { status.textContent = 'The fetch took too long - try again.'; return; }
      get('/api/samples/job/' + encodeURIComponent(job)).then(function (st) {
        st = st || {};
        if (st.stage === 'done' && st.audio) {
          audio.src = st.audio;
          audio.hidden = false;
          marks.hidden = false;
          paintRanges();
          status.textContent = (st.title || 'Ready') + ' - play it, Mark IN and Mark OUT round each moment, then Extract all.';
        } else if (st.error || st.stage === 'error' || st.stage === 'failed') {
          status.textContent = 'Could not fetch it: ' + (st.error || st.stage);
          fetchB.disabled = false;
        } else {
          status.textContent = 'Fetching... ' + (st.stage || '');
          timer = root.setTimeout(poll, 2500);
        }
      }, function () { timer = root.setTimeout(poll, 2500); });
    };
    fetchB.addEventListener('click', function () {
      var u = url.value.trim();
      if (!u) { status.textContent = 'Paste a link first.'; return; }
      fetchB.disabled = true;
      status.textContent = 'Fetching...';
      post('/api/samples/fetch', {url: u}).then(function (r) {
        job = (r && r.job_id) || '';
        if (!job) { status.textContent = 'The station gave no job for that link.'; fetchB.disabled = false; return; }
        t0 = Date.now();
        timer = root.setTimeout(poll, 2500);
      }, function (err) { status.textContent = 'Could not start: ' + (err && err.message || err); fetchB.disabled = false; });
    });
    inB.addEventListener('click', function () { a = audio.currentTime || 0; status.textContent = 'IN at ' + fmt(a) + ' - now Mark OUT.'; });
    outB.addEventListener('click', function () {
      var b = audio.currentTime || 0;
      if (a < 0 || b <= a) { status.textContent = 'Mark IN first, then Mark OUT after it.'; return; }
      list.push({a: a, b: b});
      a = -1;
      paintRanges();
      status.textContent = list.length + ' moment(s) marked - Extract all when you are done.';
    });
    cutB.addEventListener('click', function () {
      if (!list.length) return;
      cutB.disabled = true;
      status.textContent = 'Cutting and naming...';
      post('/api/samples/extract', {job_id: job, ranges: list, stage_only: true}).then(function (got) {
        var rows = (got && got.staged) || [];
        list = [];
        paintRanges();
        staged.innerHTML = '';
        rows.forEach(function (r) {
          var row = make('div', 'pl-tray-row');
          row.dataset.id = r.id;
          var name = make('input', 'pl-tray-input');
          name.value = r.name || '';
          row.appendChild(name);
          staged.appendChild(row);
        });
        folder.hidden = saveB.hidden = !rows.length;
        status.textContent = rows.length + ' cut(s) staged - name them, then Save the batch.';
      }, function (err) { status.textContent = err && err.message || String(err); cutB.disabled = false; });
    });
    saveB.addEventListener('click', function () {
      var items = [].map.call(staged.querySelectorAll('.pl-tray-row'), function (row) {
        return {id: row.dataset.id, name: row.querySelector('input').value.trim()};
      });
      if (!items.length) return;
      var f = folder.value.trim() || 'Samples';
      try { root.localStorage.setItem('pineSampleFolder', f); } catch (err) { /* per screen only */ }
      saveB.disabled = true;
      post('/api/samples/commit', {items: items, folder: f}).then(function (got) {
        var saved = (got && got.saved) || [];
        status.textContent = saved.length + ' sample(s) saved into ' + ((got && got.folder) || f) + ' - the DJs have them in rotation now.';
        staged.innerHTML = '';
        folder.hidden = saveB.hidden = true;
        saveB.disabled = false;
      }, function (err) { status.textContent = err && err.message || String(err); saveB.disabled = false; });
    });
  }

  /* ================================================== the status-bar mic */

  function attachBadge() {
    var bar = document.getElementById('pineConsoleLine');
    if (!bar) return false;
    var have = bar.querySelector('.pine-console-live');
    if (have) { ui.badge = have; try { attachTray(bar); } catch (err) { /* [pltray] */ } return true; }
    var b = make('button', 'pine-console-live');
    b.type = 'button';
    b.setAttribute('aria-haspopup', 'dialog');
    b.setAttribute('aria-label', 'PineLive');
    b.title = 'PineLive';
    b.appendChild(make('span', 'pl-badge-ico'));
    b.appendChild(make('span', 'pl-badge-word'));
    b.addEventListener('click', function (e) {
      /* the bar opens its audit list on any click it does not know */
      e.stopPropagation();
      e.preventDefault();
      toggleOpen();
    });
    var before = bar.querySelector('.pine-console-gallery') || bar.querySelector('.pine-console-viewport');
    bar.insertBefore(b, before || null);
    ui.badge = b;
    try { attachTray(bar); } catch (err) { /* [pltray] */ }
    ui.badgeState = '';
    paintBadge();
    return true;
  }

  function paintBadge() {
    var b = ui.badge;
    if (!b || !b.isConnected) return;
    var info = badgeOf(model.state, model.failure);
    var live = info.state === 'live';
    if (ui.badgeState !== info.state) {
      b.className = 'pine-console-live pl-badge-' + info.state + (ui.visible ? ' open' : '');
      var ico = b.querySelector('.pl-badge-ico');
      var mark = icon(live ? 'c:microphone--filled' : 'c:microphone', '');
      /* the sprite may not be on the page yet at document start: say MIC
       * and try again on the next paint rather than keep the words */
      if (mark) { ico.innerHTML = mark; ui.badgeState = info.state; } else ico.textContent = 'MIC';
      if (info.state === 'problem') {
        var warn = icon('c:warning--alt', '');
        if (warn) { var w = make('span', 'pl-badge-warn'); w.innerHTML = warn; ico.appendChild(w); }
      }
    }
    setClass(b, 'open', ui.visible);
    var word = live ? 'LIVE' : info.state === 'arming' ? 'ARMED' : '';
    setText(b.querySelector('.pl-badge-word'), word);
    var title = 'PineLive - ' + info.why;
    if (b.title !== title) { b.title = title; b.setAttribute('aria-label', title); }
  }

  function watchForBar() {
    if (attachBadge()) { /* keep watching: a rebuilt bar needs its mic back */ }
    if (ui.barObserver || typeof root.MutationObserver !== 'function' || !document.body) return;
    ui.barObserver = new root.MutationObserver(function () {
      var bar = document.getElementById('pineConsoleLine');
      if (bar && !bar.querySelector('.pine-console-live')) attachBadge();
    });
    ui.barObserver.observe(document.body, {childList: true});
  }

  /* ================================================== the popup */

  function buildPopup() {
    if (ui.built) return;
    ui.built = true;
    var pop = make('div', 'pl-pop');
    pop.id = 'pineLive';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'PineLive - the MX Live event');
    pop.hidden = true;

    var head = make('div', 'pl-head');
    var mark = make('div', 'pl-head-mark');
    mark.appendChild(iconNode('c:microphone--filled'));
    head.appendChild(mark);
    var titles = make('div', 'pl-head-titles');
    titles.appendChild(make('b', '', 'PineLive'));
    ui.headSub = make('span', '', 'MX Live');
    titles.appendChild(ui.headSub);
    head.appendChild(titles);
    ui.phasePill = make('span', 'pl-phase', '...');
    head.appendChild(ui.phasePill);
    /* [pltoggle] slots 1, 2 and one more: the header's three switches */
    var hswRow = make('div', 'pl-hsw-row');
    ui.hsw = {row: hswRow,
      cam: headSwitch(hswRow, 'pl-hsw-cam', 'PineCam to live', function (next, node) { flipTailscale(next, node); }),
      /* [pinestream] beside PineCam to live: the switch, then which screen */
      stream: headSwitch(hswRow, 'pl-hsw-stream', 'PineStream', function (next, node) { flipStream(next, node); }),
      streamSrc: streamSourcePicker(hswRow),
      live: headSwitch(hswRow, 'pl-hsw-live', 'Pine Live', function (next, node) { flipSet(next, node); }),
      album: headSwitch(hswRow, 'pl-hsw-album', 'Album recording', function (next) { flipAlbum(next); })};
    head.appendChild(hswRow);
    ui.headClock = make('span', 'pl-head-clock', '');
    head.appendChild(ui.headClock);
    /* [plpopup] the centred middle slot: the detection wizard's door
     * lands here later; empty it takes no room at all (display:none). */
    ui.headMid = make('span', 'pl-head-mid');
    head.appendChild(ui.headMid);
    ui.headWarn = make('span', 'pl-head-warn', '');
    ui.headWarn.hidden = true;
    head.appendChild(ui.headWarn);
    /* [pldetect] the exclamation-in-a-box: the detection wizard's door.
     * The stylesheet sits it in the middle of the header; while a warning
     * is showing on a wide screen the warn line keeps the middle and the
     * box steps in beside the close X - the warning wins. */
    var detect = btn('pl-detect-btn', '', 'c:warning-square', 'Find the instrument and get it on the air');
    detect.setAttribute('aria-haspopup', 'dialog');
    detect.addEventListener('click', function (e) { e.stopPropagation(); openDetect(); });
    head.appendChild(detect);
    ui.detectBtn = detect;
    var close = btn('pl-close', '', 'c:close--filled', 'Close PineLive');
    close.addEventListener('click', function (e) { e.stopPropagation(); closePopup(); });
    head.appendChild(close);
    pop.appendChild(head);

    ui.sayLine = make('div', 'pl-say');
    ui.sayLine.hidden = true;
    ui.sayLine.setAttribute('role', 'status');
    /* [plquiet] the status row: the say line, then the two silence sliders */
    var sayRow = make('div', 'pl-sayrow');
    sayRow.appendChild(ui.sayLine);
    sayRow.appendChild(buildQuiet());
    pop.appendChild(sayRow);

    var body = make('div', 'pl-body');
    pop.appendChild(body);
    ui.body = body;
    ui.pop = pop;

    PANEL_ORDER.forEach(function (id) { body.appendChild(buildPanel(id)); });

    /* the lightbox for a manual page, inside the popup */
    var lb = make('div', 'pl-lightbox');
    lb.hidden = true;
    lb.setAttribute('role', 'dialog');
    lb.setAttribute('aria-label', 'Manual page');
    var lbClose = btn('pl-close', '', 'c:close--filled', 'Close the manual page');
    lbClose.addEventListener('click', function (e) { e.stopPropagation(); closeLightbox(); });
    var lbBody = make('div', 'pl-lightbox-body');
    lb.appendChild(lbClose);
    lb.appendChild(lbBody);
    lb.addEventListener('click', function (e) { if (e.target === lb) { e.stopPropagation(); closeLightbox(); } });
    pop.appendChild(lb);
    ui.lightbox = {root: lb, body: lbBody};

    /* [pldetect] the detection wizard, an overlay like the lightbox: its
     * own X, a tap on its own backdrop, Escape and BACK all close it. Not
     * role=dialog - PineDrag raises any dialog under a tap, and a raised
     * wizard would bury the manual lightbox that opens above it. */
    var dz = make('div', 'pl-detect');
    dz.hidden = true;
    dz.setAttribute('role', 'region');
    dz.setAttribute('aria-label', 'Find the instrument and get it on the air');
    var dzTop = make('div', 'pl-dz-top');
    var dzTitles = make('div', 'pl-dz-titles');
    dzTitles.appendChild(make('b', '', 'Find the instrument'));
    dzTitles.appendChild(make('small', '', 'Every step probes the station\'s own roads; the run re-walks itself while this is open.'));
    dzTop.appendChild(dzTitles);
    var dzClose = btn('pl-close', '', 'c:close--filled', 'Close the detection wizard');
    dzClose.addEventListener('click', function (e) { e.stopPropagation(); closeDetect(); });
    dzTop.appendChild(dzClose);
    var dzBody = make('div', 'pl-detect-body');
    dz.appendChild(dzTop);
    dz.appendChild(dzBody);
    dz.addEventListener('click', function (e) { if (e.target === dz) { e.stopPropagation(); closeDetect(); } });
    pop.appendChild(dz);
    ui.detect = {root: dz, body: dzBody, open: false, timer: 0, beat: 0,
      skelRoad: '', rows: {}, roadSeg: null, again: null, banner: null, bannerSig: '', pick: null};

    document.body.appendChild(pop);
    installDrag(pop, head);        /* [plpopup] the header is the handle */

    /* Its ways out. PineDismiss: a tap off it and Escape. BACK: the probe
     * answers this popup's node with ITS topmost closer - the lightbox,
     * when one is open, before the popup itself. */
    var dismiss = root.PineDismiss;
    if (dismiss && typeof dismiss.watch === 'function') {
      ui.unwatch = dismiss.watch(pop, closePopup, [function () { return ui.badge; }], function () { return ui.visible; });
      /* [pldetect] registered before the lightbox's watch, so Escape peels
       * the lightbox first, then the wizard, then the popup. The lightbox
       * is spared: a tap on the manual page floating above the wizard must
       * not fell the wizard underneath it. */
      ui.unwatchDz = dismiss.watch(dz, closeDetect, [function () { return ui.lightbox && ui.lightbox.root; }], function () { return !dz.hidden; });
      ui.unwatchLb = dismiss.watch(lb, closeLightbox, [], function () { return !lb.hidden; });
    }
    var probe = function () {
      if (!ui.visible) return null;
      /* [pldetect] BACK unwinds one layer at a time: lightbox, wizard, popup */
      return {node: pop, close: function () {
        if (ui.chooser) closeChooser();   /* [pinestream-choose] the chooser first */
        else if (ui.lightbox && !ui.lightbox.root.hidden) closeLightbox();
        else if (ui.detect && !ui.detect.root.hidden) closeDetect();
        else closePopup();
      }};
    };
    if (dismiss && typeof dismiss.onBack === 'function') {
      ui.unback = dismiss.onBack(probe);
    } else {
      /* an older page without PineDismiss.onBack: chain pineBack itself */
      var before = root.pineBack;
      root.pineBack = function () {
        var p = probe();
        if (p) { try { p.close(); } catch (err) { /* closed anyway */ } return true; }
        return typeof before === 'function' ? before() : false;
      };
    }

    /* pause the audiograph when it scrolls out of sight inside the popup */
    if (typeof root.IntersectionObserver === 'function' && ui.scope) {
      ui.io = new root.IntersectionObserver(function (entries) {
        entries.forEach(function (en) { ui.scopeSeen = en.isIntersecting; });
        syncLevels();
      }, {root: body, threshold: 0});
      ui.io.observe(ui.scope.canvas);
    }
    document.addEventListener('visibilitychange', function () { syncLevels(); });
  }

  /* ================================================== [plpopup] drag
   *
   * The stylesheet keeps the popup fixed, centred and viewport-sized
   * (left/right/top/bottom insets), so the drag never touches those: it
   * moves a TRANSLATE on top of the base spot, clamped so the whole
   * popup stays on the glass, and remembers the offset per surface in
   * localStorage. Reopened - even on a screen that shrank meanwhile -
   * the popup returns to the operator's spot, pulled fully on-screen.
   * Nothing here scrolls anything, and a press that starts on a control
   * is never a drag. */
  var POS_KEY = 'pineLive.pos.v1';

  function posSurface() { return httpPage() ? 'panel' : 'desktop'; }

  /** Clamp a wanted translate so base+delta keeps the whole box visible.
   *  Pure: base is {left, top, width, height} BEFORE any translate;
   *  a box wider or taller than the glass pins its left/top edge. */
  function clampDelta(dx, dy, base, vw, vh) {
    dx = num(dx) || 0; dy = num(dy) || 0;
    var loX = -base.left, hiX = vw - base.width - base.left;
    var loY = -base.top, hiY = vh - base.height - base.top;
    dx = Math.max(loX, Math.min(dx, Math.max(loX, hiX)));
    dy = Math.max(loY, Math.min(dy, Math.max(loY, hiY)));
    return {dx: Math.round(dx), dy: Math.round(dy)};
  }

  function readPos() {
    try {
      var s = storage();
      var raw = s && s.getItem(POS_KEY);
      var all = raw ? JSON.parse(raw) : null;
      var p = all && all[posSurface()];
      var dx = p && Number(p.dx), dy = p && Number(p.dy);
      if (isFinite(dx) && isFinite(dy)) return {dx: dx, dy: dy};
    } catch (err) { /* a locked profile: the popup opens at its base spot */ }
    return null;
  }

  function writePos(dx, dy) {
    try {
      var s = storage();
      if (!s) return;
      var all = null;
      try { all = JSON.parse(s.getItem(POS_KEY)); } catch (err2) { all = null; }
      if (!all || typeof all !== 'object' || Array.isArray(all)) all = {};
      all[posSurface()] = {dx: Math.round(num(dx) || 0), dy: Math.round(num(dy) || 0)};
      s.setItem(POS_KEY, JSON.stringify(all));
    } catch (err) { /* a locked profile: the spot lives until the close */ }
  }

  function rootWidth() { return root.innerWidth || (document.documentElement && document.documentElement.clientWidth) || 0; }
  function rootHeight() { return root.innerHeight || (document.documentElement && document.documentElement.clientHeight) || 0; }

  function applyDelta(d) {
    ui.dragApplied = d;
    ui.pop.style.transform = (d.dx || d.dy) ? 'translate(' + d.dx + 'px, ' + d.dy + 'px)' : '';
  }

  /** The popup's rect with the current translate backed out. */
  function baseRect() {
    var r = ui.pop.getBoundingClientRect();
    var a = ui.dragApplied || {dx: 0, dy: 0};
    return {left: r.left - a.dx, top: r.top - a.dy, width: r.width, height: r.height};
  }

  /** Put the popup where this surface last had it - clamped to the glass
   *  it is opening on NOW, which may be smaller than the one it left. */
  function restoreDragPos() {
    if (!ui.pop || ui.pop.hidden) return;
    var want = ui.dragDelta || readPos();
    if (!want) { ui.dragDelta = {dx: 0, dy: 0}; ui.dragApplied = {dx: 0, dy: 0}; return; }
    var d = clampDelta(want.dx, want.dy, baseRect(), rootWidth(), rootHeight());
    ui.dragDelta = d;
    applyDelta(d);
  }

  function installDrag(pop, head) {
    head.addEventListener('pointerdown', function (e) {
      if (e.button !== undefined && e.button !== null && e.button > 0) return;
      var t = e.target;
      if (t && t.closest && t.closest('button, a, input, select, textarea, [role="button"], [role="switch"]')) return;
      var base = baseRect();
      var from = ui.dragApplied || {dx: 0, dy: 0};
      var sx = e.clientX, sy = e.clientY;
      var moved = false;
      var move = function (ev) {
        if (!moved && Math.abs(ev.clientX - sx) < 3 && Math.abs(ev.clientY - sy) < 3) return;
        moved = true;
        setClass(pop, 'pl-dragging', true);
        var d = clampDelta(from.dx + (ev.clientX - sx), from.dy + (ev.clientY - sy), base, rootWidth(), rootHeight());
        ui.dragDelta = d;
        applyDelta(d);
        if (ev.cancelable) ev.preventDefault();
      };
      var done = function (ev) {
        head.removeEventListener('pointermove', move);
        head.removeEventListener('pointerup', done);
        head.removeEventListener('pointercancel', done);
        setClass(pop, 'pl-dragging', false);
        if (moved && ui.dragDelta) writePos(ui.dragDelta.dx, ui.dragDelta.dy);
        if (ev && ev.pointerId !== undefined && head.hasPointerCapture && head.hasPointerCapture(ev.pointerId)) {
          try { head.releasePointerCapture(ev.pointerId); } catch (err) { /* released already */ }
        }
      };
      try { if (e.pointerId !== undefined && head.setPointerCapture) head.setPointerCapture(e.pointerId); } catch (err) { /* a mouse without capture still drags */ }
      head.addEventListener('pointermove', move);
      head.addEventListener('pointerup', done);
      head.addEventListener('pointercancel', done);
    });
    root.addEventListener('resize', function () { if (ui.visible) restoreDragPos(); });
  }

  function openPopup() {
    buildPopup();
    if (ui.visible) return;
    ui.visible = true;
    ui.pop.hidden = false;
    restoreDragPos();              /* [plpopup] the saved spot, clamped to THIS screen */
    ui.picked = '';
    ui.levelsRefused = false;       /* every opening tries the stream again */
    ui.levelsFailed = 0;
    paint();
    schedulePoll(0);
    refreshSettings();
    refreshDevices(false);
    if (ui.open.troubleshoot) refreshTrouble().then(scheduleTrouble, scheduleTrouble);
    loadShelf();
    syncLevels();
    syncPreview();
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no wall */ }
  }

  function closePopup() {
    if (!ui.visible) return;
    closeLightbox();
    closeDetect();            /* [pldetect] no timer may outlive the popup */
    closeChooser();                 /* [pinestream-choose] cancelled: PineStream stays off */
    ui.visible = false;
    if (ui.pop) ui.pop.hidden = true;
    stopMonitor();
    syncLevels();
    syncPreview();
    if (ui.troubleTimer) { root.clearTimeout(ui.troubleTimer); ui.troubleTimer = 0; }
    paintBadge();
    schedulePoll(POLL_CLOSED_MS);
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no wall */ }
  }

  function toggleOpen() { if (ui.visible) closePopup(); else openPopup(); }

  /* ------------------------------------------------------------ panels */

  var PANELS = {
    scope: {title: 'Audiograph', icon: 'c:waveform', build: buildScope, paint: paintScope, summary: summaryScope},
    event: {title: 'Event', icon: 'c:microphone--filled', build: buildEvent, paint: paintEvent, summary: summaryEvent},
    input: {title: 'Input', icon: 'c:plug', build: buildInput, paint: paintInput, summary: summaryInput},
    picture: {title: 'Picture', icon: 'c:image', build: buildPicture, paint: paintPicture, summary: summaryPicture},
    stream: {title: 'PineStream', icon: 'c:screen', build: buildStream, paint: paintStream, summary: summaryStream},   /* [pinestream] */
    recording: {title: 'Recording', icon: 'c:recording--filled', build: buildRecording, paint: paintRecording, summary: summaryRecording},
    system3: {title: 'System 3', icon: 'c:chat', build: buildSystem3, paint: paintSystem3, summary: summarySystem3},
    troubleshoot: {title: 'Troubleshoot', icon: 'c:stethoscope', build: buildTrouble, paint: paintTrouble, summary: summaryTrouble}
  };

  function buildPanel(id) {
    var def = PANELS[id];
    var sec = make('section', 'pl-panel pl-panel-' + id);
    sec.setAttribute('data-panel', id);
    var head = make('button', 'pl-panel-head');
    head.type = 'button';
    head.appendChild(iconNode('c:caret--right'));
    head.appendChild(iconNode(def.icon));
    head.appendChild(make('b', '', def.title));
    var sum = make('span', 'pl-panel-sum', '');
    head.appendChild(sum);
    var chip = make('span', 'pl-panel-chip', '');
    chip.hidden = true;
    head.appendChild(chip);
    var body = make('div', 'pl-panel-body');
    sec.appendChild(head);
    sec.appendChild(body);
    var panel = {id: id, root: sec, head: head, body: body, sum: sum, chip: chip, parts: {}};
    ui.panels[id] = panel;
    def.build(panel);
    head.addEventListener('click', function (e) {
      e.stopPropagation();
      ui.open[id] = !ui.open[id];
      writePanels(storage(), ui.open);
      if (id === 'troubleshoot' && ui.open[id]) { refreshTrouble().then(scheduleTrouble, scheduleTrouble); refreshDevices(false); }
      if (id === 'troubleshoot' && !ui.open[id] && ui.troubleTimer) { root.clearTimeout(ui.troubleTimer); ui.troubleTimer = 0; }
      if (id === 'input' && ui.open[id]) refreshDevices(false);
      paint();
      syncLevels();
      syncPreview();
    });
    return sec;
  }

  function paint() {
    paintBadge();
    if (!ui.built || !ui.visible) return;
    var st = model.state;
    setText(ui.phasePill, phaseWord(st));
    ui.phasePill.className = 'pl-phase pl-phase-' + (st ? (st.enabled === false ? 'off' : String(st.phase || 'idle')) : 'none');
    var ev = st && st.event;
    setText(ui.headSub, (ev && ev.name) || 'MX Live');
    setText(ui.headClock, st && st.armed && ev ? fmtDur(ev.live_seconds) + ' on air' : '');
    var info = badgeOf(st, model.failure);
    var warn = info.state === 'problem' || info.state === 'absent' || (model.failure && !model.failure.absent) ? info.why : '';
    setText(ui.headWarn, warn);
    setHidden(ui.headWarn, !warn);
    paintDetectBtn();         /* [pldetect] the box's tint follows the state */
    try { paintHeadSwitches(); }   /* [pltoggle] */
    catch (err) { if (root.console) root.console.error('[pinelive] header switches paint failed:', err); }
    if (ui.detect && ui.detect.open) {
      try { paintDetect(); }
      catch (err) {
        /* the wizard's fault must not blank the panels (one-subscriber rule) */
        if (root.console) root.console.error('[pinelive] detect paint failed:', err);
      }
    }
    try { paintQuiet(); }                                          /* [plquiet] */
    catch (err) { if (root.console) root.console.error('[pinelive] silence sliders paint failed:', err); }
    PANEL_ORDER.forEach(function (id) {
      var p = ui.panels[id];
      var open = !!ui.open[id];
      setClass(p.root, 'open', open);
      p.head.setAttribute('aria-expanded', open ? 'true' : 'false');
      setHidden(p.body, !open);
      var s = '';
      try { s = PANELS[id].summary() || ''; } catch (err) { s = ''; }
      setText(p.sum, s);
      if (open) {
        try { PANELS[id].paint(p); }
        catch (err) {
          /* one panel's fault must not blank the others (one-subscriber-paints-many-panes) */
          if (root.console) root.console.error('[pinelive] ' + id + ' paint failed:', err);
        }
      }
    });
  }

  /* ------------------------------------------------------------ audiograph */

  function buildScope(p) {
    var host = make('div', 'pl-scope-host');
    p.body.appendChild(host);
    if (root.PineLiveScope) ui.scope = root.PineLiveScope.mount(host);
    else host.appendChild(make('p', 'pl-muted', 'The audiograph did not load on this screen (pinelive-scope.js).'));
    var row = make('div', 'pl-actions');
    var test = btn('', 'Test on air', 'c:timer', 'Put the interface on the broadcast in place of the record - DJs, ducking and SFX as usual - until you tap again (ten minutes at most, never recorded)');
    test.addEventListener('click', function (e) { e.stopPropagation(); airTest(); });   /* [plair] */
    row.appendChild(test);
    var listen = btn('pl-listen', 'Listen here', 'c:headphones', 'Hear the live input alone on this screen (a headphone check)');
    listen.addEventListener('click', function (e) { e.stopPropagation(); toggleMonitor(); });
    row.appendChild(listen);
    var stream = make('span', 'pl-muted pl-stream-line', '');
    row.appendChild(stream);
    p.body.appendChild(row);
    p.parts = {test: test, listen: listen, stream: stream};
  }

  function paintScope(p) {
    var st = model.state || {};
    var testing = model.testing && Date.now() - model.testing < 5000;
    /* [plair] the on-air test's own words; a running SET holds the air */
    var rehearsing = !!(st.armed && st.event && st.event.rehearse);
    var setArmed = !!st.armed && !rehearsing;
    setText(p.parts.test.querySelector('.pl-btn-words'),
      rehearsing ? 'End test' : (setArmed ? 'The set is on air' : (testing ? 'Testing...' : 'Test on air')));
    setClass(p.parts.test, 'on', rehearsing);
    p.parts.test.disabled = !model.state || setArmed;
    var canListen = !!st.monitor_url;
    setHidden(p.parts.listen, !canListen);
    setClass(p.parts.listen, 'on', !!ui.monitor);
    var line = '';
    if (ui.levelsRefused) line = 'The levels stream would not open on this screen; the meter follows the 1 s state instead.';
    else if (ui.levels) line = ui.levelsGotAny ? 'Levels: live from the host' : 'Levels: connected, waiting for audio';
    else if (!st.levels_url) line = model.failure ? '' : 'The station has not handed out a levels stream.';
    setText(p.parts.stream, line);
    if (ui.scope) {
      var fresh = Date.now() - ui.scope.lastAt() < 2000;
      if (model.failure && model.failure.absent) ui.scope.note('PineLive is not on this station yet.', 'bad');
      else if (!model.state) ui.scope.note('Reading the station...', '');
      else if (!fresh && !st.armed && !testing) ui.scope.note('No audio yet. Frames flow while MX Live is armed, or for four seconds after Test.', '');
      else if (!fresh && testing) ui.scope.note('Testing the capture...', '');
      else if (!fresh) ui.scope.note('Armed, but no audio is arriving.', 'warn');
      else ui.scope.note('');
      /* no levels stream on this screen: feed the meter from the 1 s state,
       * once per state */
      if (ui.levelsRefused && ui.fedAt !== model.stateAt && st.source && isFinite(num(st.source.level_db))) {
        ui.fedAt = model.stateAt;
        ui.scope.push({t: Date.now() / 1000, rms: st.source.level_db, peak: st.source.peak_db,
          clip: !!st.source.clipping, duck: st.duck && st.duck.now_db, bands: null});
      }
    }
  }

  function summaryScope() {
    var src = (model.state && model.state.source) || {};
    if (!model.state) return '';
    if (!isFinite(num(src.level_db))) return 'no audio path';
    return 'RMS ' + fmtDbShort(src.level_db) + ' · peak ' + fmtDbShort(src.peak_db) + (src.clipping ? ' · CLIPPING' : '');
  }

  function wantLevels() {
    /* [plbars] a live set keeps the feed open for the player's strip */
    if (model.state && model.state.live && model.state.levels_url) {
      var hid = false;
      try { hid = !!document.hidden; } catch (err) { hid = false; }
      if (!hid) return true;
    }
    if (!ui.visible || !ui.open.scope || !ui.scope || !ui.scopeSeen) return false;
    var hidden = false;
    try { hidden = !!document.hidden; } catch (err) { hidden = false; }
    if (hidden) return false;
    return !!(model.state && model.state.levels_url);
  }

  /* [plmonitor] The waterfall falls only while the host captures, and the
   * host captures only while armed or for four seconds after Test. So while
   * the audiograph is on screen, not armed, on the USB road, the station's
   * own off-air test is renewed every 2.5 s (its lease is 4 s). Never on
   * the network road - each test there mints a new sender token. Silent:
   * post(), not act(). */
  function monitorLease() {
    var st = model.state || {};
    var src = st.source || {};
    var road = liveRoad();
    if (!(ui.visible && ui.open.scope && ui.scopeSeen)) return;
    if (road !== 'usb' || st.armed || model.testing) return;
    var now = Date.now();
    if (ui.monitorAt && now - ui.monitorAt < 2500) return;
    ui.monitorAt = now;
    var dev = (model.settings && model.settings.device) || '';
    post('/api/pinelive/test', dev ? {source: 'usb', device: dev} : {source: 'usb'})
      .then(function () {}, function () {});
  }

  /* One EventSource while the audiograph is on screen; none otherwise. It
   * holds one of the page's sockets, which on the tablet is one of six
   * (#1324) - so it is closed the moment nobody can see it. */
  /* [plcount] "a loading bar representing the fail over countdown ... for
   * when live is enabled": over the Script view's player, full while the
   * interface sounds, draining as it stays quiet; empty = the records take
   * the air back. Gone when no set is armed. */
  /* [plduck] while a set holds the air and a DJ line plays, the set's own
   * player drops to LIVE_DUCK (-10.8 dB, the station mix's duck) - the
   * terminal that owns the air plays the set directly, so the mix's duck
   * never reached it and the DJs were buried under the K.O. Sidekick. */
  var LIVE_DUCK = 0.29;
  function djDuckSync() {
    var st = model.state || {};
    var music = document.getElementById('musicPlayer');
    if (!music) return;
    var voices = document.querySelectorAll('audio[id^="djVoiceAudio"]');
    var talking = false, i;
    for (i = 0; i < voices.length; i += 1) {
      var v = voices[i];
      if (!v.__plduck) {
        v.__plduck = true;
        ['playing', 'pause', 'ended', 'emptied'].forEach(function (ev) {
          v.addEventListener(ev, function () { try { djDuckSync(); } catch (err) { /* never throws out */ } });
        });
      }
      if (!v.paused && !v.ended) talking = true;
    }
    var want = !!(st.live && talking);
    if (want && !ui.djDucked) {
      ui.djDucked = {was: music.volume, set: Math.max(0, music.volume * LIVE_DUCK)};
      music.volume = ui.djDucked.set;
    } else if (!want && ui.djDucked) {
      if (Math.abs(music.volume - ui.djDucked.set) < 0.01) music.volume = ui.djDucked.was;
      ui.djDucked = null;
    }
  }

  /* ================================================== [plquiet] the silence sliders
   * The thin row under the header: how long the set may stay silent before
   * the DJ gets the music back (settings.silence_seconds), and how much
   * silence makes the album recorder start a new track (settings.split_seconds).
   * Both are the station's settings (remembered, read live - no restart), and
   * a "silent N s" readout counts toward each while the input is quiet. */
  var QUIET = {
    handoff: {key: 'silence_seconds', min: 10, max: 180, def: 45},
    split: {key: 'split_seconds', min: 5, max: 120, def: 15}
  };

  function quietSecs(key) {
    var spec = key === 'split_seconds' ? QUIET.split : QUIET.handoff;
    var v = num(model.settings && model.settings[key]);
    if (!isFinite(v)) {
      var q = model.state && model.state.quiet;
      v = num(q && (key === 'split_seconds' ? q.split_s : q.handoff_s));
    }
    if (!isFinite(v)) v = spec.def;
    return Math.round(Math.max(spec.min, Math.min(spec.max, v)));
  }

  function quietSlider(box, spec, lead, tip) {
    var wrap = make('label', 'pl-quiet-one');
    wrap.title = tip;
    wrap.appendChild(make('span', 'pl-quiet-lead', lead));
    var input = guard(make('input'));
    input.type = 'range';
    input.min = String(spec.min); input.max = String(spec.max); input.step = '1';
    input.value = String(spec.def);
    input.setAttribute('aria-label', lead + ' this many seconds of silence');
    var out = make('output', 'pl-quiet-out', spec.def + ' s');
    wrap.appendChild(input);
    wrap.appendChild(out);
    wrap.appendChild(make('span', 'pl-quiet-tail', 'of silence'));
    box.appendChild(wrap);
    return {root: wrap, input: input, out: out, spec: spec};
  }

  /* A new track has to come before the hand-back (past it the DJ already has
   * the air), so the split stays under the hand-back; the station clamps the
   * same way, this only says so at once. */
  function quietPick(which, v, final) {
    var q = ui.quiet;
    var spec = QUIET[which];
    v = Math.round(Math.max(spec.min, Math.min(spec.max, Number(v))));
    var capped = false;
    if (which === 'split') {
      var hand = quietSecs('silence_seconds');
      if (v >= hand) { v = Math.max(QUIET.split.min, hand - 1); capped = true; }
    }
    setText(q[which].out, v + ' s');
    setClass(q[which].root, 'capped', capped);
    if (!final) return;
    q[which].input.value = String(v);
    if (!model.settings) model.settings = {};
    model.settings[spec.key] = v;
    var note = '';
    if (which === 'handoff' && quietSecs('split_seconds') >= v) {
      model.settings.split_seconds = Math.max(QUIET.split.min, v - 1);
      note = 'Saved. The new-track split follows the hand-back down to ' + model.settings.split_seconds + ' s - a track has to close before the DJ takes over.';
    } else if (capped) {
      note = 'Saved. A new track has to come before the hand-back (' + quietSecs('silence_seconds') + ' s), so the split stops at ' + v + ' s.';
    }
    var body = {};
    body[spec.key] = v;
    act('/api/pinelive/settings', body).then(function (ans) {
      if (note && ans && ans.ok !== false) say(note, '');
    });
    paintQuiet();
  }

  function buildQuiet() {
    var box = make('div', 'pl-quiet');
    var q = ui.quiet = {box: box};
    q.handoff = quietSlider(box, QUIET.handoff, 'Hand back to the DJ after',
      'How long the set may stay silent before the station hands the music back to the DJ (default 45 s, 10-180 s). '
      + 'Sound before then keeps the set on the air; once the DJ has it, the set takes the air back as soon as you play again. '
      + 'A cable or sender that stops arriving at all still hands back at once (Event: "No frames for"). '
      + 'The new-track split below always comes first, so it is kept shorter than this.');
    q.split = quietSlider(box, QUIET.split, 'New album track after',
      'With Album recording on: silence longer than this closes the running track, and the next sound starts the next numbered track (default 15 s, 5-120 s). '
      + 'Shorter silences stay inside the track. The closed track keeps 2 s of the silence as its ring-out and the rest is cut; the new one opens half a second before the sound. '
      + 'It must be shorter than the hand-back above - past the hand-back the DJ already has the air - so it stops just under it.');
    q.handoff.input.addEventListener('input', function () { quietPick('handoff', q.handoff.input.value, false); });
    q.handoff.input.addEventListener('change', function () { quietPick('handoff', q.handoff.input.value, true); });
    q.split.input.addEventListener('input', function () { quietPick('split', q.split.input.value, false); });
    q.split.input.addEventListener('change', function () { quietPick('split', q.split.input.value, true); });
    q.now = make('span', 'pl-quiet-now');
    q.now.setAttribute('role', 'timer');
    q.now.title = 'How long the input has been silent, and what happens next';
    q.now.appendChild(iconNode('c:time'));
    q.nowWords = make('span', '', '');
    q.now.appendChild(q.nowWords);
    q.now.hidden = true;
    box.appendChild(q.now);
    return box;
  }

  function quietReadout(st) {
    if (!st || !st.armed) return '';
    var q = st.quiet || {};
    var f = st.failover || {};
    var silent = num(q.silent_s);
    if (!isFinite(silent)) silent = num(f.quiet_s);
    if (!isFinite(silent) || silent < 1) return '';
    var hand = quietSecs('silence_seconds'), split = quietSecs('split_seconds');
    var parts = ['Silent ' + Math.floor(silent) + ' s'];
    var sp = st.recording && st.recording.split;
    var album = q.album !== undefined ? !!q.album : !!(st.recording && st.recording.on);
    if (album) {
      if (sp && sp.waiting) parts.push('track ' + Math.max(1, (sp.track || 2) - 1) + ' closed');
      else parts.push('new track in ' + Math.max(0, Math.ceil(split - silent)) + ' s');
    }
    if (st.phase === 'fallback') parts.push('the DJ has the music until you play');
    else parts.push('back to the DJ in ' + Math.max(0, Math.ceil(hand - silent)) + ' s');
    return parts.join(' · ');
  }

  function paintQuiet() {
    var q = ui.quiet;
    if (!q) return;
    ['handoff', 'split'].forEach(function (which) {
      var s = q[which];
      if (s.input.__editing) return;
      setClass(s.root, 'capped', false);
      var v = quietSecs(s.spec.key);
      if (String(s.input.value) !== String(v)) s.input.value = String(v);
      setText(s.out, v + ' s');
    });
    var st = model.state;
    var albumOff = !!(model.settings && model.settings.record === false);
    setClass(q.split.root, 'off', albumOff);
    var words = quietReadout(st);
    setText(q.nowWords, words);
    setHidden(q.now, !words);
    var silent = st && st.quiet ? num(st.quiet.silent_s) : NaN;
    setClass(q.now, 'near', isFinite(silent) && silent >= quietSecs('silence_seconds') * 0.67);
    setClass(q.now, 'gone', !!(st && st.phase === 'fallback'));
  }

  function paintCountdown() {
    var st = model.state || {};
    var host = document.querySelector('.sp-player');
    var bar = document.getElementById('plCountdown');
    if (!st.armed || !host || !host.parentNode) {
      if (bar && bar.parentNode) bar.parentNode.removeChild(bar);
      return;
    }
    if (!bar || bar.nextSibling !== host) {
      if (bar && bar.parentNode) bar.parentNode.removeChild(bar);
      bar = make('div', 'pl-countdown');
      bar.id = 'plCountdown';
      bar.appendChild(make('div', 'pl-countdown-fill'));
      bar.appendChild(make('div', 'pl-countdown-split'));          /* [plsplit] */
      bar.appendChild(make('span', 'pl-countdown-words', ''));
      host.parentNode.insertBefore(bar, host);
    }
    var f = st.failover, frac = 1, text = '';
    var test = st.event && st.event.rehearse ? 'On-air test' : 'Live';
    if (st.phase === 'live' && f && f.after_s) {
      var quiet = Math.max(0, Number(f.quiet_s) || 0);
      frac = Math.max(0, 1 - quiet / f.after_s);
      text = quiet < 1 ? test + ' - the interface has the air'
        : test + ' - quiet ' + Math.round(quiet) + ' s: the records take the air back in '
          + Math.max(0, Math.ceil(f.after_s - quiet)) + ' s';
    } else if (st.phase === 'fallback') {
      frac = 0;
      text = test + ' - the records have the air; the set takes it back the moment the interface sounds';
    } else {
      text = test + ' - armed, waiting for the first sound';
    }
    /* [plsplit] the track split: quiet fills a blue strip toward the split */
    var sp = st.recording && st.recording.split;
    var strip = bar.querySelector('.pl-countdown-split');
    var sfrac = 0;
    if (sp && sp.waiting) {
      sfrac = 1;
      text = 'Track ' + Math.max(1, sp.track - 1) + ' recorded - track ' + sp.track + ' starts when you play'
        + (st.phase === 'fallback' ? ' (the records have the air)' : '');
    } else if (sp && sp.after_s && Number(sp.quiet_s) >= 1) {
      sfrac = Math.min(1, Number(sp.quiet_s) / sp.after_s);
      text = 'Quiet ' + Math.round(sp.quiet_s) + ' s - splitting track ' + sp.track + ' in '
        + Math.max(0, Math.ceil(sp.after_s - sp.quiet_s)) + ' s'
        + (st.phase === 'live' && f && f.after_s ? '; the records take the air in '
          + Math.max(0, Math.ceil(f.after_s - Number(f.quiet_s || 0))) + ' s' : '');
    }
    /* [plend] 30 s of silence: offer to end the set (never without the tap) */
    var quietAll = sp ? (Number(sp.quiet_s) || 0) : 0;
    if (quietAll < 30) ui.endOfferDismissed = false;
    var showOffer = !!(sp && quietAll >= 30 && !ui.endOfferDismissed);
    var offer = bar.querySelector('.pl-countdown-offer');
    if (showOffer && !offer) {
      offer = make('span', 'pl-countdown-offer');
      var endB = make('button', 'pl-countdown-end', 'End the set');
      endB.type = 'button';
      endB.addEventListener('click', function (e) {
        e.stopPropagation();
        act('/api/pinelive/stop', {}, endB).then(function () { try { paintCountdown(); } catch (err) { /* next poll */ } });
      });
      var keepB = make('button', 'pl-countdown-keep', 'Keep going');
      keepB.type = 'button';
      keepB.addEventListener('click', function (e) {
        e.stopPropagation();
        ui.endOfferDismissed = true;
        try { paintCountdown(); } catch (err) { /* next poll */ }
      });
      offer.appendChild(endB);
      offer.appendChild(keepB);
      bar.insertBefore(offer, bar.querySelector('.pl-countdown-words'));
    }
    if (offer) offer.hidden = !showOffer;
    setClass(bar, 'offer', showOffer);
    if (showOffer) text = 'Silent ' + Math.round(quietAll) + ' s - end the set, its stream and its recording?';
    if (strip) strip.style.width = (sfrac * 100).toFixed(1) + '%';
    setClass(bar, 'splitting', sfrac > 0);
    bar.firstChild.style.width = (frac * 100).toFixed(1) + '%';
    setClass(bar, 'warn', frac > 0 && frac < 0.67);
    setClass(bar, 'down', frac <= 0);
    setText(bar.lastChild, text);
  }

  function syncLevels() {
    var want = wantLevels();
    if (ui.scope) { if (ui.visible && ui.open.scope && ui.scopeSeen) ui.scope.resume(); else ui.scope.pause(); }
    monitorLease();                      /* [plmonitor] */
    if (!want || ui.levelsRefused) { closeLevels(); return; }
    var url = stationUrl(model.state.levels_url);
    if (ui.levels && ui.levels.__url === url) return;
    closeLevels();
    if (typeof root.EventSource !== 'function') { ui.levelsRefused = true; paint(); return; }
    var es;
    try { es = new root.EventSource(url); } catch (err) { ui.levelsRefused = true; paint(); return; }
    es.__url = url;
    ui.levels = es;
    ui.levelsGotAny = false;
    es.addEventListener('frame', function (e) {
      var f = null;
      try { f = JSON.parse(e.data); } catch (err) { f = null; }
      if (f) { ui.lastFrame = f; ui.lastFrameAt = Date.now(); }   /* [plbars] */
      if (!f || !ui.scope) return;
      if (!ui.levelsGotAny) { ui.levelsGotAny = true; ui.levelsFailed = 0; }
      ui.scope.push(f);
    });
    es.addEventListener('state', function (e) {
      var s = null;
      try { s = JSON.parse(e.data); } catch (err) { s = null; }
      if (s && model.state && s.phase && s.phase !== model.state.phase) schedulePoll(0);
    });
    es.onerror = function () {
      if (es.readyState !== 2) return;          /* CONNECTING: the browser retries by itself */
      if (ui.levels === es) ui.levels = null;
      ui.levelsFailed += 1;
      /* never a frame, closed at once, on a file: page: the cross-origin
       * answer was refused. Say so and use the state's numbers. */
      if (!ui.levelsGotAny && !httpPage()) { ui.levelsRefused = true; paint(); return; }
      if (ui.levelsRetry) root.clearTimeout(ui.levelsRetry);
      ui.levelsRetry = root.setTimeout(function () { ui.levelsRetry = 0; schedulePoll(0); root.setTimeout(syncLevels, 600); },
        Math.min(30000, 3000 * ui.levelsFailed));
      paint();
    };
  }

  function closeLevels() {
    if (ui.levels) { try { ui.levels.close(); } catch (err) { /* closed */ } ui.levels = null; }
  }

  function toggleMonitor() {
    if (ui.monitor) { stopMonitor(); paint(); return; }
    var st = model.state || {};
    if (!st.monitor_url) { say('Nothing to listen to until a set or a test is running.', ''); return; }
    var a = new root.Audio();
    a.preload = 'none';
    a.src = stationUrl(st.monitor_url);
    ui.monitor = a;
    var p = a.play();
    if (p && typeof p.then === 'function') {
      p.then(null, function (err) { say('This screen would not play the input: ' + String((err && err.message) || err), 'bad'); stopMonitor(); paint(); });
    }
    paint();
  }

  function stopMonitor() {
    if (!ui.monitor) return;
    try { ui.monitor.pause(); ui.monitor.removeAttribute('src'); ui.monitor.load(); } catch (err) { /* gone */ }
    ui.monitor = null;
  }

  /* ------------------------------------------------------------ event */

  function buildEvent(p) {
    var b = p.body;
    var sw = toggle('MX Live event', 'Off: nothing can start. Switching it off during a set ends the set first.', function (next, node) {
      /* [plair] the switch IS the set; [pltoggle] one owner with the header's Pine Live */
      flipSet(next, node);
    });
    b.appendChild(sw.root);

    var roadRow = make('div', 'pl-row');
    var roadText = make('div', 'pl-row-text');
    roadText.appendChild(make('b', '', 'Where the sound comes from'));
    var roadCap = make('small', '', '');
    roadText.appendChild(roadCap);
    roadRow.appendChild(roadText);
    var road = segmented([
      {value: 'usb', label: 'USB into the DGX', title: 'The instrument plugged into the DGX Spark by USB - the main road'},
      {value: 'network', label: 'Network', title: 'A sender page on another machine, over Wi-Fi or the tailnet'}
    ], function (v) { ui.prefs.road = v; ui.roadPicked = true; writePrefs(); paint(); }, 'Where the sound comes from');
    roadRow.appendChild(road.root);
    b.appendChild(roadRow);

    var go = make('div', 'pl-go-row');
    var goBtn = btn('pl-go', 'Go live', 'c:microphone--filled', 'Start MX Live');
    goBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var st = model.state || {};
      if (st.armed) confirmTap('stop', goBtn, 'Tap again to end the set', endSet);
      else goLive(false);
    });
    go.appendChild(goBtn);
    ui.goBtn = goBtn;
    var refused = make('div', 'pl-refused');
    refused.hidden = true;
    var refusedText = make('span', '', '');
    var unpauseBtn = btn('pl-mini', 'Lift the pause and go live', null, 'Take the station off pause, then start the set');
    unpauseBtn.addEventListener('click', function (e) { e.stopPropagation(); goLive(true); });
    var troubleBtn = btn('pl-mini', 'Open Troubleshoot', 'c:stethoscope', 'Open the troubleshooter');
    troubleBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (!ui.open.troubleshoot) { ui.open.troubleshoot = true; writePanels(storage(), ui.open); refreshTrouble().then(scheduleTrouble, scheduleTrouble); paint(); }
    });
    refused.appendChild(refusedText);
    refused.appendChild(unpauseBtn);
    refused.appendChild(troubleBtn);
    go.appendChild(refused);
    b.appendChild(go);

    var grid = make('div', 'pl-facts');
    var facts = {
      phase: fact(grid, 'Phase'), onair: fact(grid, 'On air for'), started: fact(grid, 'Started'),
      fallbacks: fact(grid, 'Fallbacks'), music: fact(grid, 'The station\'s records'), air: fact(grid, 'Heard on')
    };
    b.appendChild(grid);

    var errBox = subgroup('event-errors', 'What went wrong, newest first', 'c:warning--alt');
    var errList = make('ol', 'pl-errors');
    errBox.body.appendChild(errList);
    b.appendChild(errBox.root);

    var drop = subgroup('event-dropout', 'When the input drops out', 'c:time');
    var fields = {
      dropout_seconds: numberRow({label: 'No frames for', caption: 'cable, device or sender gone - the station takes the air back', min: 0.5, max: 60, step: 0.5, unit: 's'},
        function (v) { saveSetting('dropout_seconds', v); }),
      silence_seconds: numberRow({label: 'Silence for', caption: 'frames arrive but below the floor - then the DJ gets the music back (the slider under the header)', min: 10, max: 180, step: 1, unit: 's'},
        function (v) { saveSetting('silence_seconds', v); }),
      silence_db: numberRow({label: 'Silence floor', caption: 'below this counts as silence', min: -90, max: -20, step: 1, unit: 'dBFS'},
        function (v) { saveSetting('silence_db', v); }),
      return_seconds: numberRow({label: 'Take the air back after', caption: 'of signal, once it returns', min: 0.5, max: 30, step: 0.5, unit: 's'},
        function (v) { saveSetting('return_seconds', v); }),
      arm_timeout: numberRow({label: 'Wait for first audio', caption: 'after Go live, before falling back', min: 3, max: 300, step: 1, unit: 's'},
        function (v) { saveSetting('arm_timeout', v); })
    };
    for (var k in fields) if (Object.prototype.hasOwnProperty.call(fields, k)) drop.body.appendChild(fields[k].root);
    b.appendChild(drop.root);

    p.parts = {sw: sw, road: road, roadCap: roadCap, goBtn: goBtn, refused: refused, refusedText: refusedText,
      unpauseBtn: unpauseBtn, troubleBtn: troubleBtn, facts: facts, errList: errList, fields: fields, errSig: ''};
  }

  function paintEvent(p) {
    var st = model.state || {};
    var s = model.settings || {};
    var parts = p.parts;
    /* [plair] the switch shows the SET, not a permission: on = a set is armed */
    var setOn = !!st.armed && !(st.event && st.event.rehearse);
    parts.sw.set(setOn);
    parts.sw.sw.disabled = !model.state;
    var sub = setOn
      ? 'On: the interface has the broadcast whenever it sounds - the record steps aside, the DJs talk over you, and the records come back when it goes quiet. Switch off to end the set.'
      : 'Off: the station plays its records. Switch on and the interface takes the broadcast as soon as it sounds.';
    if (ui.confirmUntil.disable && Date.now() < ui.confirmUntil.disable) sub = 'Tap the switch again to end the set and switch MX Live off.';
    setText(parts.sw.caption, sub);

    var road = liveRoad();
    parts.road.set(road);
    var dev = chosenDevice(model.devices, model.settings, st);
    setText(parts.roadCap, road === 'usb'
      ? (dev ? (dev.name || dev.id) + (dev.usb_name && dev.usb_name !== dev.name ? ' (the DGX sees "' + dev.usb_name + '")' : '') : 'the first ready USB capture on the DGX')
      : 'a sender page on another machine (Input, Network)');
    parts.road.buttons.forEach(function (b) { b.disabled = !!st.armed; });

    var armed = !!st.armed;
    var confirming = ui.confirmUntil.stop && Date.now() < ui.confirmUntil.stop;
    setClass(parts.goBtn, 'stop', armed);
    setClass(parts.goBtn, 'confirm', !!confirming);
    setText(parts.goBtn.querySelector('.pl-btn-words'), armed ? (confirming ? 'Tap again to end the set' : 'End the set') : 'Go live');
    var gi = parts.goBtn.querySelector('.pl-ico');
    var want = armed ? 'c:stop--filled' : 'c:microphone--filled';
    if (gi.__icon !== want) { gi.__icon = want; gi.innerHTML = icon(want, ''); }
    parts.goBtn.disabled = !model.state || st.enabled === false || st.phase === 'stopping';

    var ref = ui.refused;
    var r = ref ? refusal(ref.code) : null;
    setHidden(parts.refused, !ref || armed);
    if (ref) {
      setText(parts.refusedText, ref.say || (r && r.words) || 'The station refused to start.');
      setHidden(parts.unpauseBtn, !(r && r.retry === 'unpause'));
      setHidden(parts.troubleBtn, !(r && r.trouble));
    }

    var ev = st.event || null;
    var f = parts.facts;
    setText(f.phase, phaseWord(st));
    setText(f.onair, ev ? fmtDur(ev.live_seconds) : '--');
    setText(f.started, ev ? fmtClock(ev.started_at) : '--');
    setText(f.fallbacks, ev ? String(ev.fallbacks || 0) : '--');
    var held = st.held_record;
    setText(f.music, st.music_paused ? ('held' + (held && held.title ? ': ' + held.title + (held.artist ? ' - ' + held.artist : '') : '')) : 'playing as usual');
    var air = st.air || {};
    var roads = [];
    if (air.stream) roads.push('stream');
    if (air.pages) roads.push('pages');
    if (air.box) roads.push('the box');
    setText(f.air, st.live ? (roads.length ? roads.join(', ') : 'nowhere yet') + (air.why_not ? ' - ' + air.why_not : '') : (air.why_not || 'not live'));

    var errs = Array.isArray(st.errors) ? st.errors.slice(0, 20) : [];
    var sig = JSON.stringify(errs.map(function (e) { return [e.at, e.code]; }));
    if (sig !== parts.errSig) {
      parts.errSig = sig;
      parts.errList.replaceChildren();
      if (!errs.length) parts.errList.appendChild(make('li', 'pl-muted', 'Nothing has gone wrong this event.'));
      errs.forEach(function (e) {
        var li = make('li');
        li.appendChild(make('time', '', fmtClock(e.at)));
        li.appendChild(make('code', '', String(e.code || '')));
        li.appendChild(make('span', '', String(e.say || '')));
        parts.errList.appendChild(li);
      });
    }

    var s2 = model.settings || {};
    for (var k in parts.fields) if (Object.prototype.hasOwnProperty.call(parts.fields, k)) parts.fields[k].set(s2[k]);
  }

  function summaryEvent() {
    var st = model.state;
    if (!st) return model.failure ? (model.failure.absent ? 'not on this station' : 'station not answering') : '';
    if (st.enabled === false) return 'switched off';
    var ev = st.event;
    if (st.phase === 'live') return 'LIVE · ' + fmtDur(ev && ev.live_seconds);
    if (st.phase === 'arming') return 'armed, waiting for audio';
    if (st.phase === 'fallback') return 'fallback - the station has the air';
    if (st.phase === 'stopping') return 'closing the last cut';
    return 'ready';
  }

  /* ------------------------------------------------------------ input */

  function buildInput(p) {
    var b = p.body;
    var devHead = make('div', 'pl-row pl-dev-head');
    var devText = make('div', 'pl-row-text');
    devText.appendChild(make('b', '', 'Devices on the DGX'));
    var scanned = make('small', '', '');
    devText.appendChild(scanned);
    devHead.appendChild(devText);
    var scan = btn('pl-mini', 'Scan again', 'c:renew', 'Ask the host to scan its USB and ALSA devices now');
    scan.addEventListener('click', function (e) { e.stopPropagation(); scan.disabled = true; refreshDevices(true).then(function () { scan.disabled = false; }); });
    devHead.appendChild(scan);
    b.appendChild(devHead);
    var devList = make('div', 'pl-devices');
    b.appendChild(devList);

    var pairRow = make('div', 'pl-row');
    var pairText = make('div', 'pl-row-text');
    pairText.appendChild(make('b', '', 'Channel pair'));
    var pairCap = make('small', '', 'which two of the device\'s channels are the stereo pair');
    pairText.appendChild(pairCap);
    pairRow.appendChild(pairText);
    var pairBox = make('div', 'pl-seg-host');
    pairRow.appendChild(pairBox);
    b.appendChild(pairRow);

    var modeRow = make('div', 'pl-row');
    var modeText = make('div', 'pl-row-text');
    modeText.appendChild(make('b', '', 'Channels'));
    var modeCap = make('small', '', '');
    modeText.appendChild(modeCap);
    modeRow.appendChild(modeText);
    var mode = segmented([
      {value: 'auto', label: 'Auto', title: 'Mono, or one dead side, goes to both ears'},
      {value: 'stereo', label: 'Stereo'},
      {value: 'left', label: 'Left'},
      {value: 'right', label: 'Right'},
      {value: 'mix', label: 'Mix', title: 'Both sides summed to mono'}
    ], function (v) { saveSetting('channel_mode', v); paint(); }, 'Channel mode');
    modeRow.appendChild(mode.root);
    b.appendChild(modeRow);

    var gain = slider({label: 'Trim', caption: 'on the input; the set sits where a record sits', min: -24, max: 12, step: 0.5,
      fmt: function (v) { return (v > 0 ? '+' : '') + v.toFixed(1) + ' dB'; }, reset: 0, resetLabel: '0 dB'},
    function (v, final) { saveSetting('live_gain_db', v, final ? 0 : 250); });
    b.appendChild(gain.root);

    var duck = subgroup('input-duck', 'Under the DJs (the duck)', 'c:volume--down');
    duck.body.appendChild(make('p', 'pl-note', 'The DJs keep talking during the set. Under each line the set dips like a record does, then comes back up.'));
    var duckDb = slider({label: 'Depth', caption: 'how far the set dips; a record dips -10.8 dB', min: -30, max: 0, step: 0.5,
      fmt: function (v) { return v.toFixed(1) + ' dB'; }, reset: -10.8, resetLabel: 'record'},
    function (v, final) { saveSetting('duck_db', v, final ? 0 : 250); });
    var duckA = slider({label: 'Attack', caption: 'into the dip', min: 10, max: 2000, step: 10,
      fmt: function (v) { return Math.round(v) + ' ms'; }},
    function (v, final) { saveSetting('duck_attack_ms', v, final ? 0 : 250); });
    var duckR = slider({label: 'Release', caption: 'back up after the line', min: 10, max: 5000, step: 10,
      fmt: function (v) { return Math.round(v) + ' ms'; }},
    function (v, final) { saveSetting('duck_release_ms', v, final ? 0 : 250); });
    duck.body.appendChild(duckDb.root);
    duck.body.appendChild(duckA.root);
    duck.body.appendChild(duckR.root);
    var duckNow = make('div', 'pl-duck-now');
    duckNow.appendChild(make('small', '', 'Dipped right now'));
    var duckBar = make('div', 'pl-duck-bar');
    var duckFill = make('i');
    duckBar.appendChild(duckFill);
    duckNow.appendChild(duckBar);
    var duckVal = make('b', '', '0 dB');
    duckNow.appendChild(duckVal);
    duck.body.appendChild(duckNow);
    b.appendChild(duck.root);

    var net = subgroup('input-network', 'The network road (another machine)', 'c:network--4');
    var netFacts = make('div', 'pl-facts');
    var nf = {status: fact(netFacts, 'Ingest'), sender: fact(netFacts, 'Sender')};
    net.body.appendChild(netFacts);
    var urls = make('div', 'pl-urls');
    net.body.appendChild(urls);
    var senderRow = make('div', 'pl-actions');
    var openSender = btn('', 'Open the sender page', 'c:laptop', 'Open the sender page - use it on the machine the instrument is plugged into');
    openSender.addEventListener('click', function (e) {
      e.stopPropagation();
      var st = model.state || {};
      if (st.sender_url) openOutside(st.sender_url);
      else say('The station has not handed out a sender page.', 'bad');
    });
    senderRow.appendChild(openSender);
    net.body.appendChild(senderRow);
    net.body.appendChild(make('p', 'pl-note', 'A browser can capture only from a secure page; where it cannot, the sender page shows an ffmpeg line to run instead.'));
    /* [plsender] This PC's interfaces. The desk's chrome IS a secure
     * page with a proven microphone road (#1355), so the desk itself can
     * be the sender: pick a Windows input, watch its level, pipe it to
     * the station's ingest. The module mounts only where it can capture;
     * anywhere else (the tablet's plain-http panel) this call mounts
     * nothing and the sender-page words above stay the whole story. */
    try {
      if (root.PineLiveSender && typeof root.PineLiveSender.mountInput === 'function') {
        root.PineLiveSender.mountInput(net.body, {request: request, say: say});
      }
    } catch (err) { /* the sender-page road above stands on its own */ }
    b.appendChild(net.root);

    p.parts = {scanned: scanned, devList: devList, devSig: '', pairRow: pairRow, pairBox: pairBox, pairSeg: null, pairSig: '',
      mode: mode, modeCap: modeCap, gain: gain, duckDb: duckDb, duckA: duckA, duckR: duckR, duckFill: duckFill, duckVal: duckVal,
      nf: nf, urls: urls, urlSig: '', openSender: openSender};
  }

  function deviceCard(dev, chosen, inUse) {
    var card = make('div', 'pl-dev' + (chosen ? ' chosen' : ''));
    var prof = root.PineLiveGuide ? root.PineLiveGuide.profileFor(dev) : null;
    var art = make('div', 'pl-dev-art');
    var P = prof && root.PineLiveGuide.PROFILES[prof];
    if (P && P.hero) {
      var img = make('img');
      img.alt = P.name;
      img.loading = 'lazy';
      img.src = stationUrl('/api/te/asset/' + P.guide + '/' + P.hero.image);
      art.appendChild(img);
    } else {
      art.appendChild(iconNode('c:audio-console'));
    }
    card.appendChild(art);
    var text = make('div', 'pl-dev-text');
    var title = make('b', '', dev.name || dev.card_id || dev.id);
    text.appendChild(title);
    var line = [];
    if (dev.usb_name && dev.usb_name !== dev.name) line.push('USB says "' + dev.usb_name + '"');
    if (dev.usb_id) line.push(dev.usb_id);
    if (dev.card_id) line.push('card ' + dev.card_id);
    text.appendChild(make('small', '', line.join(' · ')));
    var caps = [];
    if (dev.capture) caps.push((dev.channels || '?') + ' ch in');
    if (dev.playback) caps.push('out');
    if (Array.isArray(dev.rates) && dev.rates.length) caps.push(dev.rates.map(function (r) { return Math.round(r / 100) / 10 + 'k'; }).join('/'));
    if (Array.isArray(dev.formats) && dev.formats.length) caps.push(dev.formats.join('/'));
    if (dev.class_compliant) caps.push('class compliant');
    text.appendChild(make('small', '', caps.join(' · ')));
    if (dev.hint) text.appendChild(make('small', 'pl-dev-hint', dev.hint));
    card.appendChild(text);
    var side = make('div', 'pl-dev-side');
    var status = String(dev.status || (dev.capture ? 'ready' : 'no_capture'));
    side.appendChild(make('span', 'pl-chip pl-chip-' + (status === 'ready' ? 'ok' : status === 'busy' ? 'warn' : 'bad'),
      status.replace(/_/g, ' ')));
    if (inUse) side.appendChild(make('span', 'pl-chip pl-chip-live', 'in use'));
    var use = btn('pl-mini', chosen ? 'Chosen' : 'Use this', null, 'Make this the device PineLive captures');
    use.disabled = !!chosen || !dev.capture;
    use.addEventListener('click', function (e) { e.stopPropagation(); saveSetting('device', dev.id); paint(); });
    side.appendChild(use);
    card.appendChild(side);
    return card;
  }

  function paintInput(p) {
    var st = model.state || {};
    var s = model.settings || {};
    var d = model.devices;
    var parts = p.parts;
    setText(parts.scanned, d ? (d.error ? 'The scan did not answer: ' + d.error
      : 'scanned ' + (d.scanned_at ? fmtAgo(Date.now() / 1000 - d.scanned_at) : '...')) : 'asking the host...');
    var list = (d && d.usb) || [];
    var chosen = chosenDevice(d, s, st);
    var sig = JSON.stringify([list, chosen && chosen.id, st.source && st.source.device, st.armed]);
    if (sig !== parts.devSig) {
      parts.devSig = sig;
      parts.devList.replaceChildren();
      if (!list.length) {
        parts.devList.appendChild(make('p', 'pl-muted', d && !d.error ? 'No USB audio device is plugged into the DGX. Troubleshoot walks through it.' : ''));
      }
      list.forEach(function (dev) {
        var inUse = !!(st.armed && st.source && st.source.device === dev.id);
        parts.devList.appendChild(deviceCard(dev, chosen && chosen.id === dev.id && (!!s.device || list.length === 1), inUse));
      });
      var other = (d && d.alsa_other) || [];
      if (other.length) {
        parts.devList.appendChild(make('small', 'pl-muted', 'Also on the DGX, not USB: ' + other.map(function (o) { return o.name || o.card_id || o.id; }).join(', ')));
      }
    }

    var channels = Number((chosen && chosen.channels) || (st.source && st.source.channels) || 2);
    var pairs = pairsFor(channels);
    var pairSig = JSON.stringify(pairs);
    if (pairSig !== parts.pairSig) {
      parts.pairSig = pairSig;
      parts.pairBox.replaceChildren();
      parts.pairSeg = segmented(pairs.map(function (pr) { return {value: pr, label: pr[0] + '+' + pr[1]}; }),
        function (v) { saveSetting('channel_pair', v); paint(); }, 'Channel pair');
      parts.pairBox.appendChild(parts.pairSeg.root);
    }
    setHidden(parts.pairRow, pairs.length < 2);
    var pair = Array.isArray(s.channel_pair) ? s.channel_pair : (st.source && st.source.channel_pair) || [1, 2];
    parts.pairSeg.set(pair);

    var mode = s.channel_mode || (st.source && st.source.channel_mode) || 'auto';
    parts.mode.set(mode);
    setText(parts.modeCap, {auto: 'mono, or one dead side, goes to both ears', stereo: 'left to left, right to right',
      left: 'the left channel in both ears', right: 'the right channel in both ears', mix: 'both sides summed to mono'}[mode] || '');

    parts.gain.set(isFinite(num(s.live_gain_db)) ? s.live_gain_db : 0);
    var duck = st.duck || {};
    parts.duckDb.set(isFinite(num(s.duck_db)) ? s.duck_db : duck.db);
    parts.duckA.set(isFinite(num(s.duck_attack_ms)) ? s.duck_attack_ms : duck.attack_ms);
    parts.duckR.set(isFinite(num(s.duck_release_ms)) ? s.duck_release_ms : duck.release_ms);
    var now = num(duck.now_db);
    var depth = isFinite(now) ? Math.min(1, Math.max(0, -now / 30)) : 0;
    parts.duckFill.style.transform = 'scaleX(' + depth.toFixed(3) + ')';
    setText(parts.duckVal, isFinite(now) ? now.toFixed(1) + ' dB' : '--');

    var net = (d && d.network) || {};
    setText(parts.nf.status, net.status || (d ? 'unknown' : '...'));
    var snd = net.sender;
    setText(parts.nf.sender, snd ? (snd.label || snd.addr || 'connected') + (snd.rate ? ' · ' + Math.round(snd.rate / 100) / 10 + ' kHz' : '') + (snd.since ? ' · since ' + fmtClock(snd.since) : '') : 'none connected');
    var rows = [['On the LAN', net.url], ['On the tailnet', net.tailnet_url], ['For ffmpeg', net.http_url]].filter(function (r) { return r[1]; });
    var urlSig = JSON.stringify(rows);
    if (urlSig !== parts.urlSig) {
      parts.urlSig = urlSig;
      parts.urls.replaceChildren();
      rows.forEach(function (r) {
        var row = make('div', 'pl-url');
        row.appendChild(make('small', '', r[0]));
        row.appendChild(make('code', '', r[1]));
        var copy = btn('pl-mini', 'Copy', 'c:copy--to-clipboard', 'Copy ' + r[0]);
        copy.addEventListener('click', function (e) { e.stopPropagation(); copyText(r[1]); });
        row.appendChild(copy);
        parts.urls.appendChild(row);
      });
    }
    parts.openSender.disabled = !st.sender_url;
  }

  function copyText(text) {
    var done = function () { say('Copied.', ''); };
    try {
      if (root.navigator && root.navigator.clipboard && root.navigator.clipboard.writeText) {
        root.navigator.clipboard.writeText(text).then(done, function () { say(text, ''); });
        return;
      }
    } catch (err) { /* fall through */ }
    say(text, '');
  }

  function summaryInput() {
    var st = model.state || {};
    var s = model.settings || {};
    var dev = chosenDevice(model.devices, model.settings, model.state);
    var bits = [];
    if (dev) bits.push(dev.name || dev.id);
    else if (st.source && st.source.label) bits.push(st.source.label);
    var pair = Array.isArray(s.channel_pair) ? s.channel_pair : (st.source && st.source.channel_pair);
    if (pair) bits.push('ch ' + pair.join('+'));
    if (isFinite(num(s.live_gain_db)) && num(s.live_gain_db) !== 0) bits.push('trim ' + fmtDbShort(s.live_gain_db));
    if (st.duck && isFinite(num(st.duck.db))) bits.push('duck ' + num(st.duck.db).toFixed(1));
    return bits.join(' · ');
  }

  /* ------------------------------------------------------------ picture */

  function buildPicture(p) {
    var b = p.body;
    var modeRow = make('div', 'pl-row');
    var modeText = make('div', 'pl-row-text');
    modeText.appendChild(make('b', '', 'The album art shows'));
    var modeCap = make('small', '', '');
    modeText.appendChild(modeCap);
    modeRow.appendChild(modeText);
    var mode = segmented([
      {value: 'cam', label: 'Pine Cam', title: 'Your video feed from the Pine Cam'},
      {value: 'ads', label: 'Station ads', title: 'The station\'s generated ads, one after another'}
    ], function (v) { saveSetting('picture_mode', v); paint(); }, 'What the album art shows');
    modeRow.appendChild(mode.root);
    b.appendChild(modeRow);

    var ts = toggle('Video to Tailscale listeners', 'Off stops the public picture at once. Your own screens always see it.', function (next, node) {
      /* [pltoggle] one owner with the header's PineCam to live */
      ts.set(next);
      flipTailscale(next, node);
    });
    b.appendChild(ts.root);

    var grid = make('div', 'pl-facts');
    var facts = {showing: fact(grid, 'Showing now'), cam: fact(grid, 'Pine Cam'), ads: fact(grid, 'Ads ready'), pub: fact(grid, 'Listeners see')};
    b.appendChild(grid);

    var prev = make('figure', 'pl-preview');
    var img = make('img');
    img.alt = 'What the album art shows now';
    prev.appendChild(img);
    var cap = make('figcaption', '', '');
    prev.appendChild(cap);
    b.appendChild(prev);
    p.parts = {mode: mode, modeCap: modeCap, ts: ts, facts: facts, prev: prev, img: img, cap: cap};
    ui.previewImg = img;
  }

  function paintPicture(p) {
    var st = model.state || {};
    var s = model.settings || {};
    var pic = st.picture || {};
    var mode = s.picture_mode || pic.mode || 'cam';
    p.parts.mode.set(mode);
    setText(p.parts.modeCap, mode === 'cam' ? 'your video feed while the set is live' : 'the station\'s generated ads while the set is live');
    var tv = s.tailscale_video !== undefined ? !!s.tailscale_video : !!pic.tailscale_video;
    p.parts.ts.set(tv);
    p.parts.ts.sw.disabled = !model.state;
    paintCamGrey(p.parts.ts.root, p.parts.ts.sw, '');   /* [camgrey] */
    var f = p.parts.facts;
    setText(f.showing, {cam: 'the Pine Cam', ads: 'the station ads', none: 'nothing', art: 'the record\'s sleeve'}[pic.showing] || (pic.showing || '--'));
    setText(f.cam, pic.cam_live ? 'linked and fresh' : 'not linked');
    setText(f.ads, isFinite(num(pic.ads)) ? String(pic.ads) : '--');
    setText(f.pub, st.armed ? (tv ? 'the live picture' : 'no picture (video off)') : 'the usual art (no set running)');
    vcrHidden(p.parts.prev, !st.art_url);   /* [vcrfx] the picture comes on like the SFX TV */
    setText(p.parts.cap, st.art_url ? 'What the album art shows now (your own view)' : '');
    syncPreview();
  }

  function summaryPicture() {
    var st = model.state || {};
    var s = model.settings || {};
    var pic = st.picture || {};
    var mode = s.picture_mode || pic.mode;
    if (!mode) return '';
    var tv = s.tailscale_video !== undefined ? !!s.tailscale_video : !!pic.tailscale_video;
    return (mode === 'ads' ? 'station ads' : 'Pine Cam') + ' · Tailscale video ' + (tv ? 'on' : 'off');
  }

  /* The art stream is an MJPEG: while it is on screen it holds a socket
   * and a trickle of frames, so it only runs while the Picture panel is
   * open in a visible popup. */
  function syncPreview() {
    try { syncStreamPreview(); } catch (err) { /* [pinestream] never breaks the art preview */ }
    var img = ui.previewImg;
    if (!img) return;
    var st = model.state || {};
    var want = ui.visible && ui.open.picture && st.art_url ? stationUrl(st.art_url) : '';
    if (want) { if (img.__src !== want) { img.__src = want; img.src = want; } }
    else if (img.__src) {
      img.__src = '';
      /* [vcrfx: the last frame stays through the collapse] */
      setTimeout(function () { if (!img.__src) img.removeAttribute('src'); },
        root.PineVcr ? root.PineVcr.OUT_MS + 80 : 0);
    }
  }

  /* ------------------------------------------------------------ [pinestream] stream */

  var STREAM_FPS = [[1, '1'], [2, '2'], [3, '3'], [5, '5']];
  var STREAM_WIDTH = [[480, '480'], [640, '640'], [800, '800']];
  var STREAM_QUALITY = [[45, 'Low'], [60, 'Medium'], [75, 'High']];

  function buildStream(p) {
    var b = p.body;
    var live = make('div', 'pl-stream-live');
    live.setAttribute('role', 'status');
    live.appendChild(iconNode('c:circle--filled'));
    live.appendChild(make('b', '', 'LIVE to listeners'));
    var liveWords = make('span', '', '');
    live.appendChild(liveWords);
    live.hidden = true;
    b.appendChild(live);

    var sw = toggle('Stream to listeners', 'A small picture-in-picture on the stream page, for tailnet and public links. Off: nothing is captured or served. Each listener can hide it on their own page.', function (next, node) {
      sw.set(next);                    /* one owner with the header's PineStream */
      flipStream(next, node);
    });
    b.appendChild(sw.root);

    var srcRow = make('div', 'pl-row');
    var srcText = make('div', 'pl-row-text');
    srcText.appendChild(make('b', '', 'Source'));
    var srcCap = make('small', '', '');
    srcText.appendChild(srcCap);
    srcRow.appendChild(srcText);
    var src = segmented(STREAM_SOURCES.map(function (o) { return {value: o.value, label: o.label, title: o.title}; }),
      function (v) { pickStreamSource(v); }, 'Which screen PineStream shows');
    srcRow.appendChild(src.root);
    b.appendChild(srcRow);

    function pickRow(label, caption, opts, key, aria) {
      var row = make('div', 'pl-row');
      var text = make('div', 'pl-row-text');
      text.appendChild(make('b', '', label));
      text.appendChild(make('small', '', caption));
      row.appendChild(text);
      var seg = segmented(opts.map(function (o) { return {value: o[0], label: o[1]}; }),
        function (v) { saveSetting(key, v); paint(); }, aria);
      row.appendChild(seg.root);
      b.appendChild(row);
      return seg;
    }
    var fps = pickRow('Frames a second', 'Pictures of a screen, not video: two is plenty. Car and Funnel listeners get one every two seconds or slower.',
      STREAM_FPS, 'stream_fps', 'PineStream frames a second');
    var width = pickRow('Width', 'Pixels across, as the screen sends them.', STREAM_WIDTH, 'stream_width', 'PineStream picture width');
    var quality = pickRow('Quality', 'JPEG quality: higher is sharper and heavier on a phone.', STREAM_QUALITY, 'stream_quality', 'PineStream picture quality');

    var grid = make('div', 'pl-facts');
    var facts = {picture: fact(grid, 'Listeners see'), frame: fact(grid, 'Last frame'),
      size: fact(grid, 'Picture'), watching: fact(grid, 'Watching')};
    b.appendChild(grid);

    var prev = make('figure', 'pl-preview pl-stream-prev');
    var img = make('img');
    img.alt = 'What listeners see in the PineStream window';
    prev.appendChild(img);
    var cap = make('figcaption', '', '');
    prev.appendChild(cap);
    prev.hidden = true;
    b.appendChild(prev);
    b.appendChild(make('p', 'pl-muted', 'While it streams, the streamed screen carries a red LIVE badge with a stop button. A key field on that screen veils the picture (listeners read "private screen") until it is gone.'));
    p.parts = {live: live, liveWords: liveWords, sw: sw, src: src, srcCap: srcCap, fps: fps, width: width,
      quality: quality, facts: facts, prev: prev, img: img, cap: cap};
    ui.streamPrev = img;
  }

  function streamPictureWords(ps, on) {
    if (!on) return 'nothing (switched off)';
    var name = streamSourceName(ps.source);
    var pic = String(ps.picture || 'waiting');
    if (pic === 'live') return name + ', live';
    if (pic === 'private') return 'a veil: private screen' + (ps.why ? ' (' + ps.why + ')' : '');
    return 'a veil: waiting for ' + name;
  }

  function paintStream(p) {
    var on = streamOn();
    var s = model.settings || {};
    var ps = streamBlock();
    var src = streamSource();
    p.parts.sw.set(on);
    p.parts.sw.sw.disabled = !model.state;
    p.parts.src.set(src);
    inertButtons(p.parts.src.buttons, on);   /* [pinestream-choose] */
    setText(p.parts.srcCap, src === 'pineapp'
      ? 'the Pine app\'s window on the desk (the app captures itself while it is open)'
      : 'the PineTab\'s screen (the tablet captures itself - no prompt)');
    p.parts.fps.set(Number(s.stream_fps || ps.fps || 2));
    p.parts.width.set(Number(s.stream_width || ps.width || 640));
    p.parts.quality.set(Number(s.stream_quality || ps.quality || 60));
    setHidden(p.parts.live, !on);
    var watching = num(ps.watching);
    setText(p.parts.liveWords, on ? ' · ' + streamSourceName(src) + (isFinite(watching) ? ' · ' + watching + ' watching' : '') : '');
    var f = p.parts.facts;
    setText(f.picture, streamPictureWords(ps, on));
    setText(f.frame, on && isFinite(num(ps.frame_age)) ? fmtAgo(ps.frame_age) + (ps.agent ? ' · ' + ps.agent : '') : '--');
    var sz = Array.isArray(ps.size) && ps.size[0] ? ps.size[0] + '×' + ps.size[1] + (ps.kb ? ' · ' + ps.kb + ' kB' : '') : '--';
    setText(f.size, on ? sz : '--');
    setText(f.watching, on && isFinite(watching) ? String(watching) : '--');
    var showPrev = on && !!ps.preview && ps.picture === 'live';
    vcrHidden(p.parts.prev, !showPrev);
    setText(p.parts.cap, showPrev ? 'What listeners see now (once a second while this panel is open)' : '');
    syncStreamPreview();
  }

  function summaryStream() {
    if (!model.state && !model.settings) return '';
    if (!streamOn()) return 'off';
    var s = model.settings || {};
    return (streamSource() === 'pineapp' ? 'Pine app' : 'PineTab') + ' · ' + (s.stream_fps || streamBlock().fps || 2) + ' fps · LIVE';
  }

  /* The preview is the JPEG the listeners get, asked for once a second
   * (signed, so the desk's file: page needs no header) - and only while the
   * PineStream panel is open in a visible popup and the stream is live. */
  function streamPreviewUrl() {
    var ps = streamBlock();
    return ui.visible && ui.open.stream && streamOn() && ps.preview && ps.picture === 'live' ? stationUrl(ps.preview) : '';
  }

  function syncStreamPreview() {
    var img = ui.streamPrev;
    if (!img) return;
    if (streamPreviewUrl()) {
      if (ui.streamPrevTimer) return;
      var tick = function () {
        ui.streamPrevTimer = 0;
        var url = streamPreviewUrl();
        if (!url) return;
        img.src = url + (url.indexOf('?') >= 0 ? '&' : '?') + '_=' + Date.now();
        ui.streamPrevTimer = root.setTimeout(tick, 1000);
      };
      tick();
      return;
    }
    if (ui.streamPrevTimer) { root.clearTimeout(ui.streamPrevTimer); ui.streamPrevTimer = 0; }
    if (img.getAttribute('src') && !streamOn()) {
      /* the last frame stays through the collapse, then goes */
      root.setTimeout(function () { if (!streamPreviewUrl()) img.removeAttribute('src'); },
        root.PineVcr ? root.PineVcr.OUT_MS + 80 : 0);
    }
  }

  /* ------------------------------------------------------------ recording */

  function buildRecording(p) {
    var b = p.body;
    var rec = toggle('Album recording', 'Every cut is two files: the live input alone in stereo, and the full broadcast mix. Off: the set still airs and takes the music; nothing is written. Remembered for the next set.', function (next) {
      flipAlbum(next);                  /* [pltoggle] one owner with the header's Album recording */
      rec.set(next);
    });
    b.appendChild(rec.root);

    var cutRow = make('div', 'pl-row');
    var cutText = make('div', 'pl-row-text');
    cutText.appendChild(make('b', '', 'Cut length'));
    var cutCap = make('small', '', '');
    cutText.appendChild(cutCap);
    cutRow.appendChild(cutText);
    var cutCtl = make('div', 'pl-cut');
    var presets = segmented(CUT_PRESETS.map(function (c) { return {value: c[0], label: c[1]}; }),
      function (v) { saveSetting('cut_seconds', v); paint(); }, 'Cut length');
    cutCtl.appendChild(presets.root);
    cutRow.appendChild(cutCtl);
    b.appendChild(cutRow);
    var custom = numberRow({label: 'Or exactly', caption: '30 s to an hour', min: 30, max: 3600, step: 5, unit: 's'},
      function (v) { saveSetting('cut_seconds', v); paint(); });
    b.appendChild(custom.root);

    var fmtRow = make('div', 'pl-row');
    var fmtText = make('div', 'pl-row-text');
    fmtText.appendChild(make('b', '', 'Format'));
    fmtText.appendChild(make('small', '', 'WAV is 16-bit 44.1 kHz stereo'));
    fmtRow.appendChild(fmtText);
    var fmt = segmented([{value: 'wav', label: 'WAV'}, {value: 'flac', label: 'FLAC'}],
      function (v) { saveSetting('format', v); paint(); }, 'File format');
    fmtRow.appendChild(fmt.root);
    b.appendChild(fmtRow);

    var destRow = make('div', 'pl-row pl-dest-row');
    var destText = make('div', 'pl-row-text');
    destText.appendChild(make('b', '', 'The folder they are carried to'));
    var destCap = make('small', '', 'a folder per event is made inside it');
    destText.appendChild(destCap);
    destRow.appendChild(destText);
    var destCtl = make('div', 'pl-dest');
    var dest = guard(make('input'));
    dest.type = 'text';
    dest.spellcheck = false;
    dest.setAttribute('aria-label', 'Destination folder');
    dest.addEventListener('change', function () { saveSetting('dest', dest.value.trim() || DEFAULT_DEST); });
    var destReset = btn('pl-mini', 'Default', null, 'Back to ' + DEFAULT_DEST);
    destReset.addEventListener('click', function (e) { e.stopPropagation(); dest.value = DEFAULT_DEST; saveSetting('dest', DEFAULT_DEST); });
    destCtl.appendChild(dest);
    destCtl.appendChild(destReset);
    destRow.appendChild(destCtl);
    b.appendChild(destRow);

    var nowBox = make('div', 'pl-cutnow');
    var nowLine = make('div', 'pl-cutnow-line');
    var nowWords = make('b', '', '');
    nowLine.appendChild(nowWords);
    var nowMore = make('span', 'pl-muted', '');
    nowLine.appendChild(nowMore);
    nowBox.appendChild(nowLine);
    var bar = make('div', 'pl-progress');
    var fill = make('i');
    bar.appendChild(fill);
    nowBox.appendChild(bar);
    b.appendChild(nowBox);

    var grid = make('div', 'pl-facts');
    var facts = {last: fact(grid, 'Last cut'), input: fact(grid, 'Input file'), mix: fact(grid, 'Mix file'),
      folder: fact(grid, 'On the DGX'), courier: fact(grid, 'The desk\'s courier'), desk: fact(grid, 'A desk last took a job')};
    b.appendChild(grid);
    p.parts = {rec: rec, presets: presets, custom: custom, cutCap: cutCap, fmt: fmt, dest: dest, destCap: destCap,
      nowWords: nowWords, nowMore: nowMore, fill: fill, facts: facts};
  }

  function paintRecording(p) {
    var st = model.state || {};
    var s = model.settings || {};
    var r = st.recording || {};
    var parts = p.parts;
    parts.rec.set(albumOn());          /* [pltoggle] */
    var cut = Number(s.cut_seconds || r.cut_seconds || 210);
    parts.presets.set(cut);
    parts.custom.set(cut);
    setText(parts.cutCap, 'a new pair every ' + (root.PineLiveGuide ? root.PineLiveGuide.fmtCut(cut) : cut + ' s'));
    parts.fmt.set(s.format || r.format || 'wav');
    if (!parts.dest.__editing && document.activeElement !== parts.dest) {
      var dv = s.dest || DEFAULT_DEST;
      if (parts.dest.value !== dv) parts.dest.value = dv;
    }
    setText(parts.destCap, r.dest && st.armed ? 'this event goes to ' + r.dest : 'a folder per event is made inside it');
    if (st.armed && r.cut_index && albumOn()) {   /* [pltoggle] */
      setText(parts.nowWords, 'Cut ' + r.cut_index + ' · ' + fmtDur(r.cut_elapsed) + ' of ' + fmtDur(r.cut_seconds || cut));
      setText(parts.nowMore, (r.cuts || 0) + ' closed this event');
      var frac = Math.max(0, Math.min(1, num(r.cut_elapsed) / Math.max(1, num(r.cut_seconds || cut))));
      parts.fill.style.transform = 'scaleX(' + (isFinite(frac) ? frac.toFixed(3) : 0) + ')';
    } else {
      setText(parts.nowWords, !st.armed ? 'No set running' : albumOn() ? 'Starting the first cut...'
        : 'Album recording is off - the set airs, nothing is written');   /* [pltoggle] */
      setText(parts.nowMore, r.cuts ? r.cuts + ' closed' : '');
      parts.fill.style.transform = 'scaleX(0)';
    }
    var last = r.last_cut;
    var f = parts.facts;
    setText(f.last, last ? '#' + last.index + ' · ' + fmtDur(last.seconds) + ' · ' + fmtClock(last.start) : 'none yet');
    setText(f.input, last && last.input ? last.input : '--');
    setText(f.mix, last && last.mix ? last.mix : '--');
    setText(f.folder, r.dir || '--');
    var c = r.courier || {};
    setText(f.courier, (c.pending || 0) + ' waiting · ' + (c.carried || 0) + ' carried' + (c.failed ? ' · ' + c.failed + ' failed' : ''));
    var stale = c.pending && (c.desk_seen_ago === null || c.desk_seen_ago === undefined || num(c.desk_seen_ago) > 120);
    setText(f.desk, c.desk_seen_ago === null || c.desk_seen_ago === undefined ? 'never - open Pine Box Desktop' : fmtAgo(c.desk_seen_ago));
    setClass(f.desk, 'pl-warn-text', !!stale);
  }

  function summaryRecording() {
    var st = model.state || {};
    var s = model.settings || {};
    var r = st.recording || {};
    var on = s.record !== undefined ? !!s.record : r.on !== false;
    if (!model.state) return '';
    if (!on) return 'not recording';
    var cut = Number(s.cut_seconds || r.cut_seconds || 210);
    var bits = ['every ' + (root.PineLiveGuide ? root.PineLiveGuide.fmtCut(cut) : cut + ' s')];
    if (r.cuts) bits.push(r.cuts + ' cut' + (r.cuts === 1 ? '' : 's'));
    var c = r.courier || {};
    if (c.pending) bits.push(c.pending + ' waiting for the desk');
    return bits.join(' · ');
  }

  /* ------------------------------------------------------------ system 3 */

  function buildSystem3(p) {
    var b = p.body;
    b.appendChild(make('p', 'pl-note', 'During the set the DJs keep talking over it. System 3 writes their lines as it always does; the set dips under each one like a record (Input, Under the DJs).'));
    var grid = make('div', 'pl-facts');
    var facts = {event: fact(grid, 'MX Live, as System 3 reads it'), duck: fact(grid, 'The duck'), djs: fact(grid, 'The record on air')};
    b.appendChild(grid);
    var extra = make('div', 'pl-s3-options');
    b.appendChild(extra);
    var row = make('div', 'pl-actions');
    var open = btn('', 'Open System 3', 'c:chart--network', 'Open the System 3 director');
    open.addEventListener('click', function (e) { e.stopPropagation(); openSystem3(open); });
    row.appendChild(open);
    b.appendChild(row);
    p.parts = {facts: facts, extra: extra, extraSig: ''};
  }

  function paintSystem3(p) {
    var st = model.state || {};
    var f = p.parts.facts;
    setText(f.event, st.enabled === false ? 'switched off' : (st.armed ? phaseWord(st) + (st.event ? ' · ' + st.event.name : '') : 'on, no set running'));
    var d = st.duck || {};
    setText(f.duck, isFinite(num(d.db)) ? num(d.db).toFixed(1) + ' dB · in ' + Math.round(num(d.attack_ms) || 0) + ' ms · out ' + Math.round(num(d.release_ms) || 0) + ' ms' : '--');
    setText(f.djs, st.live ? 'the live set ("MX Live")' : 'the station\'s own records');
    /* Anything more the event exposes to System 3 is drawn as it comes,
     * read-only: the rows are System 3's to edit, in System 3. */
    var opts = st.system3 && Array.isArray(st.system3.options) ? st.system3.options : [];
    var sig = JSON.stringify(opts);
    if (sig !== p.parts.extraSig) {
      p.parts.extraSig = sig;
      p.parts.extra.replaceChildren();
      opts.forEach(function (o) {
        var row = make('div', 'pl-row');
        var t = make('div', 'pl-row-text');
        t.appendChild(make('b', '', String(o.label || o.key || '')));
        if (o.help) t.appendChild(make('small', '', String(o.help)));
        row.appendChild(t);
        row.appendChild(make('span', 'pl-chip', String(o.value === undefined ? '' : o.value)));
        p.parts.extra.appendChild(row);
      });
    }
  }

  function summarySystem3() {
    var d = (model.state && model.state.duck) || {};
    return isFinite(num(d.db)) ? 'DJs over the set, duck ' + num(d.db).toFixed(1) + ' dB' : '';
  }

  function s3Url() {
    var v = S3_DEFAULT_V;
    try {
      var seen = (root.performance && root.performance.getEntriesByType) ? root.performance.getEntriesByType('resource') : [];
      for (var i = seen.length - 1; i >= 0; i -= 1) {
        var m = /\/system3\/system3\.js\?v=([\w.-]+)/.exec(String(seen[i].name || ''));
        if (m) { v = m[1]; break; }
      }
    } catch (err) { /* the default */ }
    return stationUrl('/system3/system3.js?v=' + v);
  }

  function openSystem3(node) {
    node.disabled = true;
    /* System 3 asks with fetch's shape (path, {method, body}); answer it
     * through this screen's road to the station. */
    var s3request = function (path, options) {
      options = options || {};
      var method = String(options.method || 'GET').toUpperCase();
      var body = options.body;
      if (typeof body === 'string') { try { body = JSON.parse(body); } catch (err) { /* as is */ } }
      return request(method, path, body);
    };
    if (!document.querySelector('link[data-pine-s3]')) {
      var link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = stationUrl('/system3/system3.css?v=3');
      link.setAttribute('data-pine-s3', '');
      document.head.appendChild(link);
    }
    import(s3Url()).then(function (mod) {
      node.disabled = false;
      closePopup();
      return mod.openSystem3({request: s3request});
    })['catch'](function (err) {
      node.disabled = false;
      say('System 3 could not be opened here: ' + String((err && err.message) || err), 'bad');
    });
  }

  /* ------------------------------------------------------------ troubleshoot */

  function buildTrouble(p) {
    var b = p.body;
    var bar = make('div', 'pl-trouble-bar');
    var hwWrap = make('label', 'pl-select');
    hwWrap.appendChild(make('small', '', 'Hardware'));
    var hw = make('select');
    hw.setAttribute('aria-label', 'Which hardware the manual pages are for');
    hwWrap.appendChild(hw);
    hw.addEventListener('change', function () { ui.prefs.profile = hw.value; writePrefs(); p.parts.detailSig = ''; paint(); });
    bar.appendChild(hwWrap);
    var run = btn('', 'Run checks', 'c:renew', 'Ask the station to run every check again');
    run.addEventListener('click', function (e) { e.stopPropagation(); refreshTrouble(); });
    bar.appendChild(run);
    var test = btn('', 'Test 4 s', 'c:timer', 'Open the capture for four seconds without going on air, then check again');
    test.addEventListener('click', function (e) { e.stopPropagation(); runTest(); });
    bar.appendChild(test);
    var scan = btn('', 'Scan devices', 'c:search', 'Ask the host to scan its USB and ALSA devices now');
    scan.addEventListener('click', function (e) { e.stopPropagation(); refreshDevices(true).then(function () { refreshTrouble(); }); });
    bar.appendChild(scan);
    var auto = make('label', 'pl-check');
    var autoBox = make('input');
    autoBox.type = 'checkbox';
    autoBox.addEventListener('change', function () { ui.prefs.troubleAuto = autoBox.checked; writePrefs(); scheduleTrouble(); });
    auto.appendChild(autoBox);
    auto.appendChild(make('span', '', 'Keep checking'));
    bar.appendChild(auto);
    b.appendChild(bar);

    var sayLine = make('p', 'pl-trouble-say', '');
    b.appendChild(sayLine);
    var seen = make('p', 'pl-note pl-hw-note', '');
    seen.hidden = true;
    b.appendChild(seen);

    var conn = make('div', 'pl-conn-host');
    b.appendChild(conn);

    var grid = make('div', 'pl-trouble-grid');
    var chart = make('div', 'pl-fc-host');
    var detail = make('div', 'pl-detail');
    grid.appendChild(chart);
    grid.appendChild(detail);
    b.appendChild(grid);

    chart.addEventListener('click', function (e) {
      var node = e.target && e.target.closest ? e.target.closest('[data-check]') : null;
      if (!node) return;
      e.stopPropagation();
      ui.picked = node.getAttribute('data-check');
      p.parts.chartSig = '';
      p.parts.detailSig = '';
      paint();
    });
    chart.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var node = e.target && e.target.closest ? e.target.closest('[data-check]') : null;
      if (!node) return;
      e.preventDefault();
      ui.picked = node.getAttribute('data-check');
      p.parts.chartSig = '';
      p.parts.detailSig = '';
      paint();
      var again = chart.querySelector('[data-check="' + ui.picked + '"]');
      if (again && again.focus) again.focus({preventScroll: true});
    });

    p.parts = {hw: hw, hwSig: '', run: run, test: test, autoBox: autoBox, sayLine: sayLine, seen: seen,
      conn: conn, connSig: '', chart: chart, chartSig: '', detail: detail, detailSig: ''};
  }

  function currentProfile() {
    var G = root.PineLiveGuide;
    if (!G) return 'ep-136';
    var dev = chosenDevice(model.devices, model.settings, model.state);
    var detected = G.profileFor(dev);
    var pick = ui.prefs.profile || 'auto';
    if (pick !== 'auto' && G.PROFILES[pick]) return pick;
    return detected || G.DEFAULT_PROFILE;
  }

  function troubleChecks() {
    var t = model.trouble;
    var checks = (t && Array.isArray(t.checks)) ? t.checks.slice() : [];
    var testing = model.testing && Date.now() - model.testing < 5000;
    if (testing) {
      checks = checks.map(function (c) {
        return ['capture', 'signal', 'level'].indexOf(c.id) >= 0 ? Object.assign({}, c, {result: 'running'}) : c;
      });
    }
    return checks;
  }

  function paintTrouble(p) {
    var G = root.PineLiveGuide;
    var parts = p.parts;
    if (!G) { setText(parts.sayLine, 'The troubleshooter did not load on this screen (pinelive-guide.js).'); return; }
    var dev = chosenDevice(model.devices, model.settings, model.state);
    var detected = G.profileFor(dev);
    var hwSig = String(detected);
    if (hwSig !== parts.hwSig) {
      parts.hwSig = hwSig;
      parts.hw.replaceChildren();
      var auto = make('option', '', 'As detected' + (detected ? ' (' + G.PROFILES[detected].name + ')' : ''));
      auto.value = 'auto';
      parts.hw.appendChild(auto);
      Object.keys(G.PROFILES).forEach(function (k) {
        var o = make('option', '', G.PROFILES[k].name);
        o.value = k;
        parts.hw.appendChild(o);
      });
    }
    var pick = ui.prefs.profile || 'auto';
    if (parts.hw.value !== pick) parts.hw.value = pick;
    parts.autoBox.checked = !!ui.prefs.troubleAuto;
    setClass(parts.run, 'busy', !!model.troubleBusy);
    var testing = model.testing && Date.now() - model.testing < 5000;
    parts.test.disabled = !!testing;
    setText(parts.test.querySelector('.pl-btn-words'), testing ? 'Testing...' : 'Test 4 s');

    var t = model.trouble;
    var profile = currentProfile();
    var P = G.PROFILES[profile];
    setText(parts.sayLine, t ? (t.error ? 'The station did not answer the checks: ' + t.error : (t.say || (t.first_fail ? '' : 'Every check passed.')))
      : (model.troubleBusy ? 'Running the checks...' : ''));

    /* The DGX reports what the hardware calls itself; when that is not the
     * profile the operator chose, say so plainly. */
    var note = '';
    var byUsb = dev && dev.usb_name ? G.profileFor(String(dev.usb_name)) : null;
    if (dev && byUsb && byUsb !== profile) {
      /* The operator's word and the USB descriptor disagree. Say what the
       * DGX reports, and what each maker's page says the device is. */
      note = 'The DGX reports this device as "' + dev.usb_name + '"' + (dev.usb_id ? ' (USB ' + dev.usb_id + ')' : '')
        + (dev.channels ? ', delivering ' + dev.channels + ' channels' : '') + '. '
        + G.PROFILES[byUsb].name + ' is ' + (byUsb === 'ep-136' ? 'the K.O.-sidekick, which its guide calls an 8 in / 4 out USB audio interface'
          : 'the K.O. II, which its notebook calls a 2-in/2-out USB audio interface')
        + '. The pages below are the ' + P.name + '\'s; if the ' + G.PROFILES[byUsb].short + ' is what is plugged into the DGX, choose it above.';
    }
    setText(parts.seen, note);
    setHidden(parts.seen, !note);

    var checks = troubleChecks();
    var road = (t && t.source) || (model.state && model.state.source && model.state.source.kind) || ui.prefs.road || 'usb';
    var connSig = JSON.stringify([checks.map(function (c) { return [c.id, c.result]; }), profile, road,
      model.state && [model.state.live, model.state.armed, model.state.air, model.state.source && model.state.source.channel_pair,
        model.state.source && model.state.source.rate, model.state.recording && model.state.recording.cut_seconds],
      dev && [dev.card_id, dev.rates]]);
    if (connSig !== parts.connSig) {
      parts.connSig = connSig;
      parts.conn.replaceChildren(G.connection({checks: checks, state: model.state, device: dev, profile: profile,
        road: road === 'network' ? 'network' : 'usb'}));
    }

    var first = (t && t.first_fail) || '';
    var selected = ui.picked || first || (checks.length ? lastPassed(checks) : '');
    var chartSig = JSON.stringify([checks.map(function (c) { return [c.id, c.result, c.evidence, c.fix, c.label]; }), first, selected, P.short]);
    if (chartSig !== parts.chartSig) {
      parts.chartSig = chartSig;
      parts.chart.replaceChildren();
      if (!checks.length) {
        parts.chart.appendChild(make('p', 'pl-muted', t && t.error ? '' : 'Asking the station for its checks...'));
      } else {
        parts.chart.appendChild(G.flowchart(checks, {selected: selected, firstFail: first,
          start: road === 'network' ? 'The sender plays' : 'The ' + P.short + ' plays', end: 'On the air, and recorded'}));
      }
    }

    var check = null;
    for (var i = 0; i < checks.length; i += 1) if (checks[i].id === selected) { check = checks[i]; break; }
    var detailSig = JSON.stringify([check, profile, !!model.manualSig, model.state && model.state.host, model.state && model.state.air]);
    if (detailSig !== parts.detailSig) {
      parts.detailSig = detailSig;
      paintDetail(parts.detail, check, profile, dev);
    }
  }

  function lastPassed(checks) {
    var id = '';
    for (var i = 0; i < checks.length; i += 1) {
      if (checks[i].result === 'pass') id = checks[i].id;
      else break;
    }
    return id || (checks[0] && checks[0].id) || '';
  }

  function paintDetail(box, check, profile, dev) {
    var G = root.PineLiveGuide;
    box.replaceChildren();
    var P = G.PROFILES[profile];
    if (!check) {
      var intro = make('div', 'pl-card');
      intro.appendChild(make('h4', '', 'Getting the ' + P.name + ' onto the air'));
      intro.appendChild(make('p', '', 'The chart follows the sound from the instrument to the air. Each question is one of the station\'s own checks; the first "no" is the one to fix. Tap any step to see what the station saw and what the manual says.'));
      if (P.hero) intro.appendChild(figure({guide: P.hero.guide, image: P.hero.image}, profile, true));
      box.appendChild(intro);
      return;
    }
    var result = G.resultOf(check);
    var card = make('div', 'pl-card pl-card-' + result);
    var head = make('div', 'pl-card-head');
    head.appendChild(make('span', 'pl-chip pl-chip-' + ({pass: 'ok', fail: 'bad', skip: 'mute', running: 'live'}[result] || 'mute'),
      {pass: 'yes', fail: 'no - fix this', skip: 'not on this road', running: 'checking', unknown: 'not checked yet'}[result] || result));
    head.appendChild(make('h4', '', check.label || check.id));
    card.appendChild(head);

    if (check.evidence) {
      var ev = make('div', 'pl-said');
      ev.appendChild(make('small', '', 'The station saw'));
      ev.appendChild(make('code', '', check.evidence));
      card.appendChild(ev);
    }
    if (check.fix) {
      var fx = make('div', 'pl-said pl-said-fix');
      fx.appendChild(make('small', '', 'The station says'));
      fx.appendChild(make('span', '', check.fix));
      card.appendChild(fx);
    }
    var steps = G.stepsFor(check.id, {state: model.state, device: dev, profile: profile, settings: model.settings});
    if (steps.length) {
      var ol = make('ol', 'pl-steps');
      steps.forEach(function (s) { ol.appendChild(make('li', '', s)); });
      var sh = make('div', 'pl-steps-head');
      sh.appendChild(iconNode('c:tools'));
      sh.appendChild(make('b', '', result === 'pass' ? 'What this step is' : 'What to do'));
      card.appendChild(sh);
      card.appendChild(ol);
    }
    var acts = make('div', 'pl-actions');
    if (['usb', 'alsa', 'class', 'free'].indexOf(check.id) >= 0) {
      var sc = btn('', 'Scan devices', 'c:search');
      sc.addEventListener('click', function (e) { e.stopPropagation(); refreshDevices(true).then(function () { refreshTrouble(); }); });
      acts.appendChild(sc);
    }
    if (['capture', 'signal', 'level', 'free'].indexOf(check.id) >= 0) {
      var ts = btn('', 'Test 4 s (not on air)', 'c:timer');
      ts.addEventListener('click', function (e) { e.stopPropagation(); runTest(); });
      acts.appendChild(ts);
    }
    if (check.id === 'signal' || check.id === 'level') {
      var inp = btn('', 'Open Input', 'c:plug');
      inp.addEventListener('click', function (e) {
        e.stopPropagation();
        ui.open.input = true; writePanels(storage(), ui.open); refreshDevices(false); paint();
      });
      acts.appendChild(inp);
    }
    if (check.id === 'routed' && model.state && !model.state.armed) {
      var gl = btn('', 'Go live', 'c:microphone--filled');
      gl.addEventListener('click', function (e) { e.stopPropagation(); goLive(false); });
      acts.appendChild(gl);
    }
    var again = btn('', 'Check again', 'c:renew');
    again.addEventListener('click', function (e) { e.stopPropagation(); refreshTrouble(); });
    acts.appendChild(again);
    card.appendChild(acts);
    box.appendChild(card);

    var refs = G.manualRefs(check.id, profile);
    if (refs.length) {
      var man = make('div', 'pl-card pl-manual');
      var mh = make('div', 'pl-steps-head');
      mh.appendChild(iconNode('c:book'));
      mh.appendChild(make('b', '', 'From the manual - ' + P.name));
      man.appendChild(mh);
      var figs = make('div', 'pl-figs');
      refs.forEach(function (ref) { figs.appendChild(ref.image ? figure(ref, profile, false) : quote(ref, profile)); });
      man.appendChild(figs);
      box.appendChild(man);
    }
  }

  /* ---- the manual, read from the station when shown */

  function loadShelf() {
    if (model.shelf || model.shelfBusy) return;
    model.shelfBusy = true;
    get('/api/manuals').then(function (s) { model.shelf = s || {}; model.shelfBusy = false; bumpManual(); },
      function () { model.shelf = {documents: []}; model.shelfBusy = false; });
  }

  function bumpManual() {
    model.manualSig = (model.manualSig || 0) + 1;
    var tp = ui.panels.troubleshoot;
    if (tp) tp.parts.detailSig = '';
    paint();
  }

  function guideDoc(slug) {
    if (model.guideDocs[slug]) return model.guideDocs[slug];
    var slot = {doc: null, failed: false, promise: null};
    model.guideDocs[slug] = slot;
    slot.promise = get('/api/te/manual/' + encodeURIComponent(slug)).then(function (d) { slot.doc = d; return d; },
      function () { slot.failed = true; return null; });
    return slot;
  }

  function libPage(slug, n) {
    var key = slug + '#' + n;
    if (model.libPages[key]) return model.libPages[key];
    var slot = {page: null, failed: false, promise: null};
    model.libPages[key] = slot;
    slot.promise = get('/api/manuals/page/' + encodeURIComponent(slug) + '/' + n).then(function (pg) { slot.page = pg; return pg; },
      function () { slot.failed = true; return null; });
    return slot;
  }

  function figure(ref, profile, hero) {
    var G = root.PineLiveGuide;
    var P = G.PROFILES[profile];
    var fig = make('figure', 'pl-fig' + (hero ? ' hero' : ''));
    var imgBtn = make('button', 'pl-fig-img');
    imgBtn.type = 'button';
    imgBtn.setAttribute('aria-label', 'Enlarge this manual picture');
    var img = make('img');
    img.loading = 'lazy';
    img.alt = P.name + ' guide, page ' + ref.guide;
    img.src = stationUrl('/api/te/asset/' + P.guide + '/' + ref.image);
    imgBtn.appendChild(img);
    fig.appendChild(imgBtn);
    var cap = make('figcaption');
    var src = make('small', 'pl-fig-src', P.name + ' guide · p.' + ref.guide);
    cap.appendChild(src);
    var q = make('q', '', '');
    cap.appendChild(q);
    fig.appendChild(cap);
    var slot = guideDoc(P.guide);
    var fill = function () {
      var pg = slot.doc ? G.guidePage(slot.doc, ref.guide) : null;
      if (pg) {
        if (pg.heading && !/^(divider|headline|hero|top|checkout menu)$/i.test(pg.heading)) setText(src, P.name + ' guide · p.' + ref.guide + ' · ' + pg.heading);
        setText(q, hero ? '' : G.excerpt(pg.text, ref.find, 220));
      }
      setHidden(q, !q.textContent);
    };
    if (slot.doc || slot.failed) fill(); else slot.promise.then(fill);
    imgBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      openLightbox({img: img.src, alt: img.alt, source: src.textContent,
        text: slot.doc ? (G.guidePage(slot.doc, ref.guide) || {}).text : ''});
    });
    return fig;
  }

  function quote(ref, profile) {
    var G = root.PineLiveGuide;
    var P = G.PROFILES[profile];
    var box = make('figure', 'pl-quote');
    var src = make('small', 'pl-fig-src', '');
    var q = make('q', '', '');
    var open = btn('pl-mini', 'Read the page', 'c:book');
    box.appendChild(src);
    box.appendChild(q);
    box.appendChild(open);
    if (ref.lib) {
      var doc = G.libraryDoc(model.shelf, profile);
      setText(src, (doc ? doc.title : 'The Library') + ' · PDF page ' + ref.lib);
      if (!model.shelf) { setText(q, 'Reading the Library...'); }
      else if (!doc) { setText(q, 'This notebook is not on the Library shelf.'); open.hidden = true; }
      else {
        var slot = libPage(doc.slug, ref.lib);
        var fill = function () {
          var pg = slot.page;
          if (!pg) { setText(q, 'The Library did not answer for this page.'); return; }
          var printed = G.printedPage(pg.heading);
          setText(src, doc.title + ' · p.' + (printed || ref.lib) + (printed ? ' (PDF ' + ref.lib + ')' : ''));
          setText(q, G.excerpt(pg.text, ref.find, 260));
        };
        if (slot.page || slot.failed) fill(); else slot.promise.then(fill);
        open.addEventListener('click', function (e) {
          e.stopPropagation();
          if (httpPage()) openLightbox({frame: '/manuals/read/' + encodeURIComponent(doc.slug) + '/' + ref.lib, source: src.textContent});
          else openOutside('/api/manuals/file/' + encodeURIComponent(doc.slug) + '#page=' + ref.lib);
        });
      }
    } else {
      setText(src, P.name + ' guide · p.' + ref.guide);
      var gs = guideDoc(P.guide);
      var gfill = function () {
        var pg = gs.doc ? G.guidePage(gs.doc, ref.guide) : null;
        if (pg && pg.heading && !/^(divider|headline|top|checkout menu)$/i.test(pg.heading)) setText(src, P.name + ' guide · p.' + ref.guide + ' · ' + pg.heading);
        setText(q, pg ? G.excerpt(pg.text, ref.find, 260) : 'The guide did not answer for this page.');
      };
      if (gs.doc || gs.failed) gfill(); else gs.promise.then(gfill);
      open.hidden = true;
    }
    return box;
  }

  function openLightbox(what) {
    var lb = ui.lightbox;
    if (!lb) return;
    lb.body.replaceChildren();
    if (what.img) {
      var img = make('img');
      img.src = what.img;
      img.alt = what.alt || '';
      lb.body.appendChild(img);
    }
    if (what.frame) {
      var fr = make('iframe');
      fr.src = stationUrl(what.frame);
      fr.title = what.source || 'Manual page';
      lb.body.appendChild(fr);
    }
    var cap = make('div', 'pl-lightbox-cap');
    if (what.source) cap.appendChild(make('b', '', what.source));
    if (what.text && root.PineLiveGuide) cap.appendChild(make('p', '', root.PineLiveGuide.excerpt(what.text, '', 600)));
    lb.body.appendChild(cap);
    lb.root.hidden = false;
  }

  function closeLightbox() {
    var lb = ui.lightbox;
    if (!lb || lb.root.hidden) return;
    lb.root.hidden = true;
    lb.body.replaceChildren();
  }

  function summaryTrouble() {
    var t = model.trouble;
    if (!t || !Array.isArray(t.checks)) return '';
    if (t.first_fail) {
      for (var i = 0; i < t.checks.length; i += 1) if (t.checks[i].id === t.first_fail) return 'stops at: ' + (t.checks[i].label || t.first_fail);
      return 'stops at: ' + t.first_fail;
    }
    var passed = t.checks.filter(function (c) { return c.result === 'pass'; }).length;
    return passed + ' of ' + t.checks.length + ' checks pass';
  }

  /* ==================================== [pldetect] the detection wizard
   *
   * "whenever I tap on it do a detection process of attempting to identify
   *  and connect to and ... locate the device on the network that is the
   *  interface that we're sending music through" - the operator.
   *
   * Every step is an ACTIVE probe through roads that already exist:
   *   GET devices?fresh=1        the live rescan - the host re-reads lsusb
   *                              and /proc/asound within half a second
   *   GET troubleshoot?device=   re-grades the host's half-second state
   *   POST test                  opens the capture four seconds OFF AIR
   * Nothing here starts a set, changes a level, or touches the air on its
   * own: Go live stays behind the operator's own double tap, and the one
   * setting the wizard offers to write (the device id) moves no volume.
   * The manual step quotes the maker's pages fetched at view time, and
   * says plainly where those pages are silent. */

  var DETECT_EVERY_MS = 4000;
  var DETECT_ROADS = {
    usb: ['host', 'find', 'device', 'choose', 'capture', 'signal', 'level', 'routed', 'recording', 'courier'],
    network: ['host', 'network', 'sender', 'signal', 'level', 'routed', 'recording', 'courier']
  };
  var DETECT_TITLES = {
    host: 'The station road on the DGX',
    find: 'Find the interface on USB',
    device: 'On the instrument itself (the manual)',
    choose: 'Point the station at it',
    capture: 'Open the capture',
    signal: 'Hear a signal',
    level: 'A sane level',
    routed: 'The station head audio (on the air)',
    recording: 'Recording in tandem',
    courier: 'The pairs reach QuickSwap',
    network: 'The network door (port 8095)',
    sender: 'The sender is connected'
  };
  /* the checks on the road BEFORE the air - a fail here is amber; the same
   * fail while the set is on the air is red */
  var DETECT_PRE_AIR = ['host', 'usb', 'alsa', 'class', 'free', 'capture', 'signal', 'level', 'network', 'sender'];

  /** grey ok / amber for a fault on the road to the air (or no instrument
   *  on the bus at all) / red when the set is on the air with a fault -
   *  pure, exported for the tests. */
  function detectTintOf(st, failure, trouble, noInstrument) {
    var info = badgeOf(st, failure);
    var fail = (trouble && !trouble.error && trouble.first_fail) ? String(trouble.first_fail) : '';
    var phase = st && st.enabled !== false ? String(st.phase || 'idle') : 'idle';
    if (phase === 'live' || phase === 'fallback') {
      return (fail || info.state === 'problem' || phase === 'fallback') ? 'bad' : 'ok';
    }
    var preAir = !!fail && DETECT_PRE_AIR.indexOf(fail) >= 0;
    return (preAir || noInstrument || info.state === 'problem') ? 'warn' : 'ok';
  }

  function paintDetectBtn() {
    var b = ui.detectBtn;
    if (!b || !b.isConnected) return;
    var G = root.PineLiveGuide;
    /* an amber box when USB is scanned and the instrument is not on it -
     * the checks may all pass (a dongle IS a working capture) and still
     * nothing on the bus is the thing the music comes from */
    var noInst = !!(detectRoad() === 'usb' && model.devices && !model.devices.error
      && G && G.pickInstrument && !G.pickInstrument(model.devices));
    var tint = detectTintOf(model.state, model.failure, model.trouble, noInst);
    var cls = 'pl-btn pl-detect-btn pl-detect-' + tint + (ui.detect && ui.detect.open ? ' on' : '');
    if (b.className !== cls) b.className = cls;
    var ico = b.querySelector('.pl-ico');
    if (ico && !ico.firstElementChild) {
      /* the sprite may not carry the glyph yet: the box with a '!' IS the
       * exclamation point in a box, so nothing is lost while it waits */
      var mark = icon('c:warning-square', '');
      if (mark) { ico.innerHTML = mark; ico.classList.remove('pl-detect-fallback'); }
      else if (ico.textContent !== '!') { ico.textContent = '!'; ico.classList.add('pl-detect-fallback'); }
    }
    var why = {ok: 'every check that can run is clean',
      warn: 'something on the road to the air needs a look',
      bad: 'the set is on the air with a fault'}[tint];
    var title = 'Find the instrument - ' + why;
    if (b.title !== title) { b.title = title; b.setAttribute('aria-label', title); }
  }

  function detectRoad() {
    return liveRoad();
  }

  function detectProfile(pick) {
    var G = root.PineLiveGuide;
    if (!G) return 'ep-136';
    /* the USB descriptor first: the host's friendly label can disagree
     * with what the hardware says it is */
    var p = pick ? (G.profileFor(String(pick.usb_name || '')) || G.profileFor(pick)) : null;
    return p || currentProfile();
  }

  function troubleById() {
    var out = {};
    var t = model.trouble;
    if (t && Array.isArray(t.checks)) t.checks.forEach(function (c) { if (c && c.id) out[c.id] = c; });
    return out;
  }

  function rateWords(devRow) {
    var rate = 0;
    if (devRow && Array.isArray(devRow.rates)) {
      for (var i = 0; i < devRow.rates.length; i += 1) rate = Math.max(rate, Number(devRow.rates[i]) || 0);
    }
    return rate ? ' at ' + (Math.round(rate / 100) / 10) + ' kHz' : '';
  }

  /* A test aimed at the instrument the wizard found, not the first row. */
  function runDetectTest() {
    var G = root.PineLiveGuide;
    var pick = G && G.pickInstrument ? G.pickInstrument(model.devices) : null;
    var dev = (model.settings && model.settings.device) || (pick && pick.id) || troubleDevice();
    model.testing = Date.now();
    paint();
    return act('/api/pinelive/test', dev ? {device: dev} : {}).then(function () {
      root.setTimeout(function () {
        model.testing = 0;
        refreshTrouble();
      }, 4600);
    });
  }

  /** Every step of the run, graded from what is on hand right now. */
  function detectSteps() {
    var G = root.PineLiveGuide;
    var st = model.state || {};
    var src = st.source || {};
    var s = model.settings || {};
    var d = model.devices;
    var by = troubleById();
    var road = detectRoad();
    var testing = model.testing && Date.now() - model.testing < 5000;
    var pick = G.pickInstrument ? G.pickInstrument(d) : chosenDevice(d, s, st);
    var profile = detectProfile(pick);
    var P = G.PROFILES[profile] || G.PROFILES[G.DEFAULT_PROFILE];
    var rec = st.recording || {};
    var cour = rec.courier || {};
    var ev = st.event || null;
    var steps = [];
    var chooseFail = false;

    function fromCheck(id) {
      var step = {id: id, status: 'wait', found: '', next: '', acts: {}};
      var t = model.trouble;
      if (!t || t.error) {
        if (t && t.error) { step.status = 'fail'; step.found = 'The station did not answer the checks: ' + t.error; step.next = 'Tap "Detect again".'; }
        else step.status = 'probing';
        return step;
      }
      var c = by[id];
      if (!c) { step.next = 'The station did not grade this on the ' + road + ' road.'; return step; }
      var r = String(c.result || 'unknown');
      step.status = r === 'pass' ? 'pass' : r === 'fail' ? 'fail' : 'wait';
      if (testing && ['capture', 'signal', 'level'].indexOf(id) >= 0) step.status = 'probing';
      if (c.evidence) step.found = 'The station saw: ' + c.evidence;
      if (r === 'fail' && c.fix) step.next = c.fix;
      return step;
    }

    steps.push(fromCheck('host'));

    if (road === 'usb') {
      var find = {id: 'find', status: 'probing', found: '', next: '', acts: {scan: 1}};
      if (!d) find.next = 'Asking the DGX for its USB scan...';
      else if (d.error) { find.status = 'fail'; find.found = 'The scan did not answer: ' + d.error; find.next = 'Tap "Scan USB now".'; }
      else if (!pick || !pick.capture) {
        find.status = 'fail';
        var seen = (d.usb || []).map(function (x) { return x.usb_name || x.name || x.id; });
        find.found = seen.length ? 'On USB the DGX sees only: ' + seen.join('; ') + ' - and none of it is the instrument.'
          : 'No USB audio device is on the DGX at all.';
        find.next = 'Plug the instrument\'s USB-C port straight into the DGX Spark with a DATA cable (a charge-only lead powers it but the DGX never sees it), switch it on, then tap "Scan USB now".';
      } else {
        find.status = 'pass';
        find.found = 'Found ' + (pick.name || pick.id) + ' - USB says "' + (pick.usb_name || '?') + '"' + (pick.usb_id ? ' (' + pick.usb_id + ')' : '')
          + (pick.channels ? ' - ' + pick.channels + ' ch in' : '') + rateWords(pick)
          + (pick.status === 'ready' ? ' - ready.' : ' - ' + String(pick.status || '') + '.');
        var others = G.notInstrument ? G.notInstrument(d, pick) : [];
        if (others.length) {
          find.next = 'Also on USB, and NOT the instrument: ' + others.map(function (o) {
            return (o.usb_name || o.name || o.id) + (o.usb_id ? ' (' + o.usb_id + ')' : '') + (o.channels ? ', ' + o.channels + ' ch' : '') + rateWords(o);
          }).join('; ') + '. The wizard keeps the station off ' + (others.length === 1 ? 'it' : 'them') + '.';
        }
      }
      var note = pick && G.mismatchNote ? G.mismatchNote(pick, profile) : '';
      find.extraSig = note;
      if (note) find.extra = function () { return make('p', 'pl-hw-note', note); };
      steps.push(find);

      var man = {id: 'device', status: 'info', found: '', next: '', acts: {}};
      var spec = G.DEVICE_SETTINGS && G.DEVICE_SETTINGS[profile];
      man.found = spec ? spec.summary : 'No manual pages are mapped for this hardware.';
      man.extraSig = profile + '|' + (model.manualSig || 0);
      man.extra = function () { return detectManualExtra(profile); };
      steps.push(man);

      var choose = {id: 'choose', status: 'wait', found: '', next: '', acts: {}};
      if (!pick || !pick.capture) choose.next = 'Waits on the instrument being found above.';
      else {
        var wrote = String(s.device || '');
        var def = chosenDevice(d, null, null);
        if (wrote === pick.id) {
          choose.status = 'pass';
          choose.found = 'The station is set to open ' + (pick.name || 'it') + ' (' + pick.id + ').';
        } else if (wrote) {
          choose.status = 'fail'; choose.acts.use = 1;
          choose.found = 'The written setting points at "' + wrote + '", not the instrument the wizard found.';
          choose.next = 'Tap "Use the ' + P.short + '" to point the station at ' + pick.id + '.';
        } else if (def && def.id === pick.id) {
          choose.status = 'pass'; choose.acts.use = 1;
          choose.found = 'Nothing is written, but the instrument is the first capture the station would take anyway.';
          choose.next = 'Tap "Use the ' + P.short + '" to pin it, so a stray dongle can never steal the slot.';
        } else {
          choose.status = 'fail'; choose.acts.use = 1;
          choose.found = 'Nothing is written, so the station would open the FIRST capture it sees - today '
            + (def ? (def.name || def.id) + ' ("' + (def.usb_name || '') + '"' + (def.channels ? ', ' + def.channels + ' ch' : '') + rateWords(def) + ')' : 'nothing')
            + ' - not the instrument.';
          choose.next = 'Tap "Use the ' + P.short + '" to write the device setting (it changes no level).';
        }
      }
      chooseFail = choose.status === 'fail';
      steps.push(choose);

      var cap = fromCheck('capture');
      cap.acts.test = 1;
      if (cap.status === 'wait') cap.next = 'Tap "Test 4 s" - the station opens the ' + P.short + ' for four seconds, OFF the air, and grades capture, signal and level.';
      steps.push(cap);
    } else {
      var net = fromCheck('network');
      var nd = (d && d.network) || null;
      if (nd) {
        var urls = [nd.url, nd.tailnet_url].filter(function (u) { return u; });
        if (urls.length) net.found = (net.found ? net.found + ' - ' : '') + 'listening on ' + urls.join(' and ');
      }
      steps.push(net);

      var snd = fromCheck('sender');
      snd.acts.sender = 1;
      if (snd.status === 'pass' && nd && nd.sender) {
        snd.found = (snd.found ? snd.found + ' - ' : '')
          + (nd.sender.label || nd.sender.addr || 'a sender')
          + (nd.sender.rate ? ' at ' + Math.round(nd.sender.rate / 100) / 10 + ' kHz' : '');
      } else if (snd.status !== 'pass') {
        snd.next = 'Open the sender page on the machine the music comes from. The host only lets a sender in while MX Live is armed on the Network road; its refusals are honest - not_armed, not_network, ingest_busy (one sender at a time) - and the token rotates each event.';
      }
      steps.push(snd);
    }

    var sig = fromCheck('signal');
    if (road === 'usb') sig.acts.test = 1;
    if (sig.status === 'wait' && !sig.next) sig.next = 'Graded while sound flows (Test, or the set itself). Play the instrument - pads, a pattern - and watch the meter.';
    if (sig.status === 'fail' && pick && Number(pick.channels) > 2) {
      var pairNow = Array.isArray(src.channel_pair) ? src.channel_pair.join('+')
        : (Array.isArray(s.channel_pair) ? s.channel_pair.join('+') : '1+2');
      sig.next = (sig.next ? sig.next + ' ' : '') + 'The manual never says which of the ' + pick.channels
        + ' USB channels carry the main mix - try another pair (Input, Channel pair; the station listens to ' + pairNow + ' now) and Test again.';
    }
    steps.push(sig);

    var lvl = fromCheck('level');
    if (road === 'usb') lvl.acts.test = 1;
    if (lvl.status === 'wait' && !lvl.next) lvl.next = 'Graded while sound flows: aim for peaks around -6 dBFS - in the gold, never the red.';
    steps.push(lvl);

    var air = fromCheck('routed');
    var phase = String(st.phase || 'idle');
    if (st.live) {
      air.status = 'pass';
      var duck = st.duck || {};
      var airTo = st.air || {};
      var roadsOn = [];
      if (airTo.stream) roadsOn.push('the stream');
      if (airTo.pages) roadsOn.push('the pages');
      if (airTo.box) roadsOn.push('the box');
      air.found = 'LIVE - the set is the broadcast bed, ducked ' + (isFinite(num(duck.db)) ? num(duck.db).toFixed(1) : '-10.8')
        + ' dB under the DJ lines' + (ev ? ' - on air ' + fmtDur(ev.live_seconds) : '')
        + (roadsOn.length ? ' - heard on ' + roadsOn.join(', ') : '') + '.';
    } else if (phase === 'arming') {
      air.status = 'probing';
      air.found = 'Armed - the station plays on until the first real sound arrives, then the set takes the air.';
    } else if (phase === 'fallback') {
      air.status = 'fail';
      var latest = Array.isArray(st.errors) && st.errors[0];
      air.found = 'The input dropped out and the station took the air back' + (latest && latest.say ? ' - ' + latest.say : '.');
      air.next = 'Bring the signal back; after ' + (s.return_seconds || 2) + ' s of sound the set retakes the air by itself.';
    } else if (air.status === 'wait') {
      air.next = 'Go live is your own tap (it asks twice). The station keeps playing until the first sound is heard; then the set becomes the station head audio, ducked under the DJ lines like a record.';
    }
    if (ui.refused && !st.armed) {
      air.status = 'fail';
      air.found = 'The station refused to start: ' + (ui.refused.say || ui.refused.code || 'no reason given');
    }
    if (!st.armed && st.enabled !== false) {
      air.acts.golive = 1;
      /* going live with the station pointed at the wrong capture would put
       * the dongle on the air - the choose step above is the way through */
      if (road === 'usb' && chooseFail) air.goliveBlock = 'Point the station at the instrument first (the step above), then go live.';
    }
    steps.push(air);

    var recS = fromCheck('recording');
    var recOn = s.record !== undefined ? !!s.record : rec.on !== false;
    if (st.armed && rec.cut_index) {
      recS.status = 'pass';
      recS.found = 'Cut ' + rec.cut_index + ' is writing - ' + fmtDur(rec.cut_elapsed) + ' of ' + fmtDur(rec.cut_seconds || 210)
        + ' - ' + (rec.cuts || 0) + ' pair' + (rec.cuts === 1 ? '' : 's') + ' closed this event.'
        + (rec.last_cut ? ' Last: #' + rec.last_cut.index + ' (' + (rec.last_cut.input || '') + ' + ' + (rec.last_cut.mix || '') + ').' : '')
        + (rec.dir ? ' On the DGX at ' + rec.dir + '.' : '');
    } else if (st.armed && !recOn) {
      recS.status = 'fail';
      recS.found = '"Write the cuts" is off, so the set is airing UNRECORDED.';
      recS.next = 'Recording panel, Write the cuts.';
    } else if (!st.armed && recS.status === 'wait') {
      recS.found = 'The cuts run in tandem with the set - the station keeps its own duties while every '
        + G.fmtCut(rec.cut_seconds || 210) + ' TWO files close: the live input alone, and the full broadcast mix.';
      recS.next = '"Write the cuts" is ' + (recOn ? 'on - nothing to do' : 'OFF (Recording panel)') + '. Cuts begin the moment the set takes the air.';
    }
    steps.push(recS);

    var courS = fromCheck('courier');
    var deskAgo = cour.desk_seen_ago;
    var deskLine = deskAgo === null || deskAgo === undefined
      ? 'no desk has EVER taken a job - open Pine Box Desktop on the PC'
      : 'a desk last took a job ' + fmtAgo(deskAgo);
    courS.found = (courS.found ? courS.found + ' - ' : '') + (cour.pending || 0) + ' waiting - ' + (cour.carried || 0) + ' carried'
      + (cour.failed ? ' - ' + cour.failed + ' failed' : '') + ' - ' + deskLine + '.';
    if (cour.pending && (deskAgo === null || deskAgo === undefined || num(deskAgo) > 120)) {
      courS.status = 'fail';
      courS.next = 'The pairs wait on the DGX until Pine Box Desktop is open; its courier carries each pair to ' + (s.dest || rec.dest || DEFAULT_DEST) + '.';
    } else if (courS.status === 'wait') {
      courS.next = 'Each closed pair is handed to the desk\'s courier for ' + (s.dest || rec.dest || DEFAULT_DEST) + '; unclaimed pairs are re-offered every minute.';
    }
    steps.push(courS);

    var anyFail = false;
    for (var i = 0; i < steps.length; i += 1) if (steps[i].status === 'fail') anyFail = true;
    var banner = null;
    if (st.live && !anyFail) {
      var duck2 = st.duck || {};
      banner = {title: recOn ? 'You are live and recording' : 'You are live - but NOT recording', facts: [
        ['On air for', ev ? fmtDur(ev.live_seconds) : '--'],
        ['The bed under the DJs', isFinite(num(duck2.db)) ? 'ducked ' + num(duck2.db).toFixed(1) + ' dB per line' : '--'],
        ['Cut running', rec.cut_index ? '#' + rec.cut_index + ' - ' + fmtDur(rec.cut_elapsed) + ' of ' + fmtDur(rec.cut_seconds || 210) : (recOn ? 'starting' : 'recording is OFF')],
        ['Pairs closed', String(rec.cuts || 0)],
        ['Carried to QuickSwap', (cour.carried || 0) + ' carried - ' + (cour.pending || 0) + ' waiting'],
        ['Every pair is', 'the live input alone + the full mix']
      ]};
    }
    return {steps: steps, banner: banner, pick: pick && pick.capture ? pick : null, profile: profile};
  }

  /* The manual step's body: the maker's pages, fetched at view time by the
   * same figure()/quote() the troubleshooter uses (page numbers and all),
   * then the honest list of what those pages nowhere say. */
  function detectManualExtra(profile) {
    var G = root.PineLiveGuide;
    var spec = G.DEVICE_SETTINGS && G.DEVICE_SETTINGS[profile];
    var box = make('div', 'pl-dz-manual');
    if (!spec) {
      box.appendChild(make('p', 'pl-note', 'No manual pages are mapped for this hardware.'));
      return box;
    }
    var figs = make('div', 'pl-figs');
    spec.quotes.forEach(function (ref) {
      var cell = make('div', 'pl-dz-quote');
      if (ref.why) cell.appendChild(make('small', 'pl-dz-why', ref.why));
      cell.appendChild(ref.image ? figure(ref, profile, false) : quote(ref, profile));
      figs.appendChild(cell);
    });
    box.appendChild(figs);
    var ah = make('div', 'pl-steps-head');
    ah.appendChild(iconNode('c:warning--alt'));
    ah.appendChild(make('b', '', 'What the manual does NOT say'));
    box.appendChild(ah);
    var ul = make('ul', 'pl-dz-absent');
    spec.absences.forEach(function (a) { ul.appendChild(make('li', '', a)); });
    box.appendChild(ul);
    return box;
  }

  function buildDetectActs(id, host) {
    var btns = {};
    if (id === 'find') {
      btns.scan = btn('pl-mini', 'Scan USB now', 'c:search', 'Ask the host to rescan lsusb and ALSA now');
      btns.scan.addEventListener('click', function (e) {
        e.stopPropagation();
        btns.scan.disabled = true;
        refreshDevices(true).then(function () { btns.scan.disabled = false; refreshTrouble(); });
      });
      host.appendChild(btns.scan);
    }
    if (id === 'choose') {
      btns.use = btn('pl-mini', 'Use it', null, 'Write the device setting - it changes no level');
      btns.use.addEventListener('click', function (e) {
        e.stopPropagation();
        var dz = ui.detect;
        if (!dz || !dz.pick) return;
        saveSetting('device', dz.pick.id);
        paint();
        root.setTimeout(function () { refreshTrouble(); }, 400);
      });
      host.appendChild(btns.use);
    }
    if (id === 'capture' || id === 'signal' || id === 'level') {
      btns.test = btn('pl-mini', 'Test 4 s (off air)', 'c:timer', 'Open the capture for four seconds without going on air');
      btns.test.addEventListener('click', function (e) { e.stopPropagation(); runDetectTest(); });
      host.appendChild(btns.test);
    }
    if (id === 'routed') {
      btns.golive = btn('pl-mini', 'Go live (tap twice)', 'c:microphone--filled', 'Start MX Live - a second tap within three seconds confirms');
      btns.golive.addEventListener('click', function (e) {
        e.stopPropagation();
        if (btns.golive.disabled) return;
        confirmTap('detect-go', btns.golive, 'Tap again to go live', function () { goLive(false); });
      });
      host.appendChild(btns.golive);
    }
    if (id === 'sender') {
      btns.sender = btn('pl-mini', 'Open the sender page', 'c:laptop', 'Open the sender page - use it on the machine the music comes from');
      btns.sender.addEventListener('click', function (e) {
        e.stopPropagation();
        var st = model.state || {};
        if (st.sender_url) openOutside(st.sender_url);
        else say('The station has not handed out a sender page.', 'bad');
      });
      host.appendChild(btns.sender);
    }
    return btns;
  }

  function buildDetectSkeleton() {
    var dz = ui.detect;
    var road = detectRoad();
    if (dz.skelRoad === road) return;
    dz.skelRoad = road;
    dz.rows = {};
    dz.bannerSig = '';
    var body = dz.body;
    body.replaceChildren();

    var bar = make('div', 'pl-dz-bar');
    dz.roadSeg = segmented([
      {value: 'usb', label: 'USB into the DGX', title: 'The instrument on a USB cable into the DGX Spark - the road in use now'},
      {value: 'network', label: 'Network / desktop app', title: 'A sender on another machine, over Wi-Fi or the tailnet'}
    ], function (v) {
      ui.prefs.road = v; ui.roadPicked = true; writePrefs();
      buildDetectSkeleton(); paintDetect(); detectProbe();
    }, 'Which road the music takes');
    dz.roadSeg.set(road);
    bar.appendChild(dz.roadSeg.root);
    dz.again = btn('', 'Detect again', 'c:renew', 'Rescan the USB bus and run every check now');
    dz.again.addEventListener('click', function (e) { e.stopPropagation(); detectProbe(); });
    bar.appendChild(dz.again);
    body.appendChild(bar);

    dz.banner = make('div', 'pl-dz-banner');
    dz.banner.hidden = true;
    body.appendChild(dz.banner);

    var list = make('ol', 'pl-dz-steps');
    DETECT_ROADS[road].forEach(function (id) {
      var li = make('li', 'pl-dz-step');
      li.setAttribute('data-step', id);
      var dot = make('span', 'pl-dz-dot');
      dot.setAttribute('aria-hidden', 'true');
      li.appendChild(dot);
      var text = make('div', 'pl-dz-text');
      var tt = make('div', 'pl-dz-title');
      tt.appendChild(make('b', '', DETECT_TITLES[id] || id));
      var chip = make('span', 'pl-chip', '');
      tt.appendChild(chip);
      text.appendChild(tt);
      var found = make('small', 'pl-dz-found', '');
      text.appendChild(found);
      var next = make('small', 'pl-dz-next', '');
      text.appendChild(next);
      var extra = make('div', 'pl-dz-extra');
      extra.hidden = true;
      text.appendChild(extra);
      var acts = make('div', 'pl-actions pl-dz-acts');
      acts.hidden = true;
      text.appendChild(acts);
      li.appendChild(text);
      list.appendChild(li);
      dz.rows[id] = {root: li, dot: dot, chip: chip, found: found, next: next,
        extra: extra, extraSig: '\u0000unset', acts: acts, btns: buildDetectActs(id, acts)};
    });
    body.appendChild(list);
  }

  /* A repaint writes into the nodes already on screen; the pane's scroll
   * stays where the operator put it (the house rule). */
  function paintDetect() {
    var dz = ui.detect;
    if (!dz || !dz.open) return;
    var G = root.PineLiveGuide;
    if (!G) { setText(dz.body, 'The wizard needs pinelive-guide.js on this screen.'); return; }
    buildDetectSkeleton();
    var comp = detectSteps();
    dz.pick = comp.pick;

    var bSig = JSON.stringify(comp.banner);
    if (bSig !== dz.bannerSig) {
      dz.bannerSig = bSig;
      dz.banner.replaceChildren();
      if (comp.banner) {
        dz.banner.appendChild(make('b', '', comp.banner.title));
        var grid = make('div', 'pl-facts');
        comp.banner.facts.forEach(function (f) { setText(fact(grid, f[0]), f[1]); });
        dz.banner.appendChild(grid);
      }
      setHidden(dz.banner, !comp.banner);
    }

    comp.steps.forEach(function (stp) {
      var row = dz.rows[stp.id];
      if (!row) return;
      var cls = 'pl-dz-step pl-dz-' + stp.status;
      if (row.root.className !== cls) row.root.className = cls;
      setText(row.chip, {pass: 'yes', fail: 'no - fix this', probing: 'probing', wait: 'waits', info: 'read'}[stp.status] || stp.status);
      row.chip.className = 'pl-chip pl-chip-' + ({pass: 'ok', fail: 'bad', probing: 'live', wait: 'mute', info: 'mute'}[stp.status] || 'mute');
      setText(row.found, stp.found);
      setHidden(row.found, !stp.found);
      setText(row.next, stp.next);
      setHidden(row.next, !stp.next);
      if ((stp.extraSig || '') !== row.extraSig) {
        row.extraSig = stp.extraSig || '';
        row.extra.replaceChildren();
        if (stp.extra) {
          var node = stp.extra();
          if (node) row.extra.appendChild(node);
        }
        setHidden(row.extra, !row.extra.firstChild);
      }
      var acts = stp.acts || {};
      var any = false;
      for (var k in row.btns) {
        if (!Object.prototype.hasOwnProperty.call(row.btns, k)) continue;
        setHidden(row.btns[k], !acts[k]);
        if (acts[k]) any = true;
      }
      setHidden(row.acts, !any);
      if (row.btns.golive) {
        var block = String(stp.goliveBlock || '');
        row.btns.golive.disabled = !!block;
        row.btns.golive.title = block || 'Start MX Live - a second tap within three seconds confirms';
      }
    });

    if (dz.rows.choose && dz.rows.choose.btns.use) {
      setText(dz.rows.choose.btns.use.querySelector('.pl-btn-words'),
        'Use the ' + ((G.PROFILES[comp.profile] || {}).short || 'instrument'));
    }
    if (dz.rows.routed && dz.rows.routed.btns.golive) {
      var confirming = ui.confirmUntil['detect-go'] && Date.now() < ui.confirmUntil['detect-go'];
      setText(dz.rows.routed.btns.golive.querySelector('.pl-btn-words'), confirming ? 'Tap again to go live' : 'Go live (tap twice)');
      setClass(dz.rows.routed.btns.golive, 'confirm', !!confirming);
    }
    if (dz.again) setClass(dz.again, 'busy', !!model.troubleBusy);
  }

  /* Tap = detect NOW: devices?fresh=1 makes the host re-read lsusb and
   * /proc/asound (its 0.2 s control loop sees scan_at), then the checks
   * re-grade against the fresh scan. */
  function detectProbe() {
    if (!ui.detect || !ui.detect.open) return;
    refreshDevices(true).then(function () { refreshTrouble(); });
  }

  /* The run re-walks itself while the wizard is open: the same cadence as
   * "Keep checking" (4 s), through the same guarded refreshTrouble - one
   * chain, no parallel loops, nothing the tablet's socket pool feels. */
  function scheduleDetect() {
    var dz = ui.detect;
    if (!dz) return;
    if (dz.timer) { root.clearTimeout(dz.timer); dz.timer = 0; }
    if (!dz.open || !ui.visible) return;
    dz.timer = root.setTimeout(function () {
      dz.timer = 0;
      dz.beat = (dz.beat || 0) + 1;
      var again = function () { scheduleDetect(); };
      if (dz.beat % 3 === 0) refreshDevices(false).then(function () { refreshTrouble().then(again, again); }, again);
      else refreshTrouble().then(again, again);
    }, DETECT_EVERY_MS);
  }

  function openDetect() {
    buildPopup();
    var dz = ui.detect;
    if (!dz || dz.open) return;
    dz.open = true;
    dz.root.hidden = false;
    dz.beat = 0;
    buildDetectSkeleton();
    paintDetect();
    paintDetectBtn();
    detectProbe();
    scheduleDetect();
  }

  function closeDetect() {
    var dz = ui.detect;
    if (!dz || !dz.open) return;
    dz.open = false;
    dz.root.hidden = true;
    if (dz.timer) { root.clearTimeout(dz.timer); dz.timer = 0; }
    paintDetectBtn();
  }

  /* ================================================== start */

  function start() {
    if (ui.started) return;
    ui.started = true;
    var go = function () {
      watchForBar();
      schedulePoll(1500);
    };
    if (document.body) go();
    else document.addEventListener('DOMContentLoaded', go, {once: true});
  }

  /* [plbars] the live set's 48 input bands as PineMeters bars (64, 0..1),
   * or null when no set holds the air or the feed is stale. */
  function liveBars() {
    var st = model.state || {};
    var f = ui.lastFrame;
    if (!st.live || !f || !f.bands || Date.now() - (ui.lastFrameAt || 0) > 1500) return null;
    var raw;
    try { raw = root.atob(f.bands); } catch (err) { return null; }
    var n = raw.length;
    if (!n) return null;
    /* [pllevel] after this terminal's Music level and the DJ duck, in dB */
    var g = 1;
    /* [plmeter] the gain actually applied (slider x duck), else the slider */
    try {
      var mpl = document.getElementById('musicPlayer');
      var gfn = mpl && typeof root.gainFor === 'function' ? root.gainFor(mpl, 'music') : null;
      if (gfn && gfn.node && gfn.node.gain) g *= gfn.node.gain.value;
      else { var mx = root.pineMixer && root.pineMixer.get ? root.pineMixer.get() : null; if (mx && isFinite(mx.music)) g *= Number(mx.music); }
    } catch (err) { g = 1; }
    try { var mp = document.getElementById('musicPlayer'); if (mp) g *= mp.volume; } catch (err) { /* keep g */ }
    var shift = 20 * Math.log(Math.max(0.001, g)) / Math.LN10;
    var bars = [], peak = 0;
    for (var i = 0; i < 64; i += 1) {
      var p = i * (n - 1) / 63, a = Math.floor(p), b = Math.min(n - 1, a + 1), t = p - a;
      var byte = raw.charCodeAt(a) * (1 - t) + raw.charCodeAt(b) * t;
      var v = Math.max(0, Math.min(1, (byte - 10) / 86)) * Math.max(0, Math.min(1, g));   /* [plmeter2] */
      bars.push(v);
      if (v > peak) peak = v;
    }
    return {bars: bars, peak: peak};
  }

  var api = {
    liveBars: liveBars,                                        /* [plbars] */
    start: start, open: openPopup, close: closePopup, toggle: toggleOpen,
    isOpen: function () { return ui.visible; },
    state: function () { return model.state; },
    refresh: function () { schedulePoll(0); },
    /* [plpopup] drag, the pure pieces, for the tests */
    dragClamp: clampDelta, dragPosKey: POS_KEY, dragSurface: posSurface,
    /* pure helpers, for the tests */
    badgeOf: badgeOf, phaseWord: phaseWord, fmtDur: fmtDur, fmtAgo: fmtAgo, readPanels: readPanels,
    writePanels: writePanels, refusal: refusal, pairsFor: pairsFor, chosenDevice: chosenDevice,
    stationUrl: stationUrl, PANEL_ORDER: PANEL_ORDER, DEFAULT_OPEN: DEFAULT_OPEN, PANELS_KEY: PANELS_KEY,
    /* [pldetect] the wizard's doors and its pure grader, for the tests */
    detectTintOf: detectTintOf, openDetect: openDetect, closeDetect: closeDetect,
    detectOpen: function () { return !!(ui.detect && ui.detect.open); }
  };
  root.PineLive = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined' && document && typeof document.createElement === 'function') start();
})(typeof window !== 'undefined' ? window : globalThis);
