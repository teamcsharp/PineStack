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
  var PANEL_ORDER = ['scope', 'event', 'input', 'picture', 'recording', 'system3', 'troubleshoot'];
  var DEFAULT_OPEN = {scope: true, event: true, input: false, picture: false,
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
    return ui.visible ? POLL_OPEN_MS : POLL_CLOSED_MS;
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
    var dev = chosenDevice(model.devices, model.settings, model.state);
    return ui.prefs.troubleDevice || (dev && dev.id) || '';
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

  function goLive(unpause) {
    var st = model.state || {};
    var road = ui.prefs.road || (st.source && st.source.kind) || 'usb';
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

  /* ================================================== the status-bar mic */

  function attachBadge() {
    var bar = document.getElementById('pineConsoleLine');
    if (!bar) return false;
    var have = bar.querySelector('.pine-console-live');
    if (have) { ui.badge = have; return true; }
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
    ui.headClock = make('span', 'pl-head-clock', '');
    head.appendChild(ui.headClock);
    ui.headWarn = make('span', 'pl-head-warn', '');
    ui.headWarn.hidden = true;
    head.appendChild(ui.headWarn);
    var close = btn('pl-close', '', 'c:close--filled', 'Close PineLive');
    close.addEventListener('click', function (e) { e.stopPropagation(); closePopup(); });
    head.appendChild(close);
    pop.appendChild(head);

    ui.sayLine = make('div', 'pl-say');
    ui.sayLine.hidden = true;
    ui.sayLine.setAttribute('role', 'status');
    pop.appendChild(ui.sayLine);

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

    document.body.appendChild(pop);

    /* Its ways out. PineDismiss: a tap off it and Escape. BACK: the probe
     * answers this popup's node with ITS topmost closer - the lightbox,
     * when one is open, before the popup itself. */
    var dismiss = root.PineDismiss;
    if (dismiss && typeof dismiss.watch === 'function') {
      ui.unwatch = dismiss.watch(pop, closePopup, [function () { return ui.badge; }], function () { return ui.visible; });
      ui.unwatchLb = dismiss.watch(lb, closeLightbox, [], function () { return !lb.hidden; });
    }
    var probe = function () {
      if (!ui.visible) return null;
      return {node: pop, close: function () { if (ui.lightbox && !ui.lightbox.root.hidden) closeLightbox(); else closePopup(); }};
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

  function openPopup() {
    buildPopup();
    if (ui.visible) return;
    ui.visible = true;
    ui.pop.hidden = false;
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
    var test = btn('', 'Test 4 s', 'c:timer', 'Open the capture for four seconds without going on air, and draw it here');
    test.addEventListener('click', function (e) { e.stopPropagation(); runTest(); });
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
    setText(p.parts.test.querySelector('.pl-btn-words'), testing ? 'Testing...' : 'Test 4 s');
    p.parts.test.disabled = !!testing || !model.state;
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
    if (!ui.visible || !ui.open.scope || !ui.scope || !ui.scopeSeen) return false;
    var hidden = false;
    try { hidden = !!document.hidden; } catch (err) { hidden = false; }
    if (hidden) return false;
    return !!(model.state && model.state.levels_url);
  }

  /* One EventSource while the audiograph is on screen; none otherwise. It
   * holds one of the page's sockets, which on the tablet is one of six
   * (#1324) - so it is closed the moment nobody can see it. */
  function syncLevels() {
    var want = wantLevels();
    if (ui.scope) { if (ui.visible && ui.open.scope && ui.scopeSeen) ui.scope.resume(); else ui.scope.pause(); }
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
      if (!next && model.state && model.state.armed) {
        confirmTap('disable', node, 'Tap again to end the set and switch MX Live off', function () {
          act('/api/pinelive/event', {enabled: false}, node);
        });
        return;
      }
      act('/api/pinelive/event', {enabled: next}, node);
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
    ], function (v) { ui.prefs.road = v; writePrefs(); paint(); }, 'Where the sound comes from');
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
      silence_seconds: numberRow({label: 'Silence for', caption: 'frames arrive but below the floor', min: 1, max: 600, step: 1, unit: 's'},
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
    parts.sw.set(st.enabled !== false && s.enabled !== false);
    parts.sw.sw.disabled = !model.state;
    var sub = st.enabled === false ? 'MX Live is off: nothing can start.' : 'Off: nothing can start. Switching it off during a set ends the set first.';
    if (ui.confirmUntil.disable && Date.now() < ui.confirmUntil.disable) sub = 'Tap the switch again to end the set and switch MX Live off.';
    setText(parts.sw.caption, sub);

    var road = ui.prefs.road || (st.source && st.source.kind) || 'usb';
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
      /* immediate: the switch moves now, the station stops the picture now,
       * and the answer's state puts it right if it refused */
      ts.set(next);
      if (!model.settings) model.settings = {};
      model.settings.tailscale_video = next;
      if (model.state && model.state.picture) model.state.picture.tailscale_video = next;
      act('/api/pinelive/settings', {tailscale_video: next}, node);
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
    var f = p.parts.facts;
    setText(f.showing, {cam: 'the Pine Cam', ads: 'the station ads', none: 'nothing', art: 'the record\'s sleeve'}[pic.showing] || (pic.showing || '--'));
    setText(f.cam, pic.cam_live ? 'linked and fresh' : 'not linked');
    setText(f.ads, isFinite(num(pic.ads)) ? String(pic.ads) : '--');
    setText(f.pub, st.armed ? (tv ? 'the live picture' : 'no picture (video off)') : 'the usual art (no set running)');
    setHidden(p.parts.prev, !st.art_url);
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
    var img = ui.previewImg;
    if (!img) return;
    var st = model.state || {};
    var want = ui.visible && ui.open.picture && st.art_url ? stationUrl(st.art_url) : '';
    if (want) { if (img.__src !== want) { img.__src = want; img.src = want; } }
    else if (img.__src) { img.__src = ''; img.removeAttribute('src'); }
  }

  /* ------------------------------------------------------------ recording */

  function buildRecording(p) {
    var b = p.body;
    var rec = toggle('Write the cuts', 'Every cut is two files: the live input alone in stereo, and the full broadcast mix.', function (next) {
      saveSetting('record', next);
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
    parts.rec.set(s.record !== undefined ? !!s.record : r.on !== false);
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
    if (st.armed && r.cut_index) {
      setText(parts.nowWords, 'Cut ' + r.cut_index + ' · ' + fmtDur(r.cut_elapsed) + ' of ' + fmtDur(r.cut_seconds || cut));
      setText(parts.nowMore, (r.cuts || 0) + ' closed this event');
      var frac = Math.max(0, Math.min(1, num(r.cut_elapsed) / Math.max(1, num(r.cut_seconds || cut))));
      parts.fill.style.transform = 'scaleX(' + (isFinite(frac) ? frac.toFixed(3) : 0) + ')';
    } else {
      setText(parts.nowWords, st.armed ? 'Starting the first cut...' : 'No set running');
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
    if (!G) return 'ep-133';
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

  var api = {
    start: start, open: openPopup, close: closePopup, toggle: toggleOpen,
    isOpen: function () { return ui.visible; },
    state: function () { return model.state; },
    refresh: function () { schedulePoll(0); },
    /* pure helpers, for the tests */
    badgeOf: badgeOf, phaseWord: phaseWord, fmtDur: fmtDur, fmtAgo: fmtAgo, readPanels: readPanels,
    writePanels: writePanels, refusal: refusal, pairsFor: pairsFor, chosenDevice: chosenDevice,
    stationUrl: stationUrl, PANEL_ORDER: PANEL_ORDER, DEFAULT_OPEN: DEFAULT_OPEN, PANELS_KEY: PANELS_KEY
  };
  root.PineLive = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined' && document && typeof document.createElement === 'function') start();
})(typeof window !== 'undefined' ? window : globalThis);
