/* VOICE ACTOR - THE PERSON ON THE STATUS BAR AND THE CAST SUBPANEL IT OPENS.
 *
 * "put an icon of a person in the basebar that allows me to bring up the
 *  voice actor subpanel. In this subpanel, I want to be able to set the
 *  voice actor for everyone on the set, enabled guest stars in the studio,
 *  select / create / dispatch / execute callers from the List ... choose
 *  the algorithm used for the voice actor and be able to load and setup
 *  host - cohost combos and individually set who the host / co-host /
 *  in-station guest / scheduled caller / random caller in a concist and
 *  elegant manner... create and add new voice actors and change who's the
 *  voice actor on the air from any tab."
 *
 * WHERE IT LIVES. The status bar is console-line.js's #pineConsoleLine on
 * both glasses (the desk chrome and the tablet's panel page). This file
 * puts its button INTO that bar beside PineLive's mic once the bar exists;
 * it does not edit console-line.js. The bar answers any click it does not
 * recognise by opening the audit list, so the button stops its own click.
 *
 * THE ROADS IT DRIVES - all existing ones, one new store:
 *   GET  /api/voice/engine-switch      the active engine + readiness (#1476)
 *   POST /api/voice/engine-switch      the Host menu's ONE global switch -
 *                                      reused exactly, never forked
 *   GET  /api/settings                 who sits where (dj.voice, cohost_voice,
 *                                      third_voice, the names, the guest)
 *   POST /api/voice-actor/seat         one seat's voice, written on the SERVER
 *                                      through api_put_settings itself (#820's
 *                                      cast-change cut fires; no browser copy of
 *                                      the settings is ever put back, so no level
 *                                      a slider moved meanwhile is undone)
 *   GET  /api/voices                   every stored actor, signatures included
 *   GET/POST /api/dj/guests, /api/dj/guest/activate, /api/dj/guest/send-home
 *   GET/POST/PUT /api/dj/callers       the caller list
 *   GET  /api/voice-actor/state        combos + prefs + seats + dispatch ledger
 *   POST /api/voice-actor/...          combos (+ /apply), prefs, scheduled,
 *                                      random-pin, dispatch (+ /cancel)
 *                                      (tools/voice_actor_backend_patch.py);
 *                                      absent -> those cards say so and stand down
 *
 * ITS WAYS OUT (#1450's rule): the close button, a tap off it (PineDismiss),
 * Escape, and the tablet's BACK key - the onBack probe answers the topmost
 * layer first (extraction, then a picker, then the popup itself).
 *
 * NO SCROLL IS EVER TAKEN (the house rule). Repaints write into the nodes
 * already on screen; nothing here ever calls scrollTo or scrollIntoView.
 *
 * THE EXTRACTION AREA is a mount point for a sibling module (see
 * SHELL_CONTRACT.md): PineVoiceActor.registerExtraction({mount, unmount,
 * tile}) - this shell only owns the door, the rail and the honest empty
 * state. It never invents pipeline facts.
 */
(function (root) {
  'use strict';

  var POLL_ENGINE_MS = 5000;
  var POLL_STATE_MS = 4000;
  var POLL_SLOW_MS = 30000;
  var REQUEST_MS = 9000;
  var ON_AIR_WINDOW_S = 180;
  var PANELS_KEY = 'pineVoiceActor.panels.v1';
  var PANEL_ORDER = ['cast', 'combos', 'callers'];
  var DEFAULT_OPEN = {cast: true, combos: false, callers: true};
  var SEAT_KEYS = {host: 'voice', cohost: 'cohost_voice', third: 'third_voice', guestvoice: 'third_voice'};

  /* ================================================== pure (and tested) */

  function voiceName(voices, vid) {
    if (!vid) return '';
    for (var i = 0; i < (voices || []).length; i += 1) {
      if (voices[i].id === vid) return String(voices[i].name || vid);
    }
    return String(vid);
  }

  function voiceOf(voices, vid) {
    for (var i = 0; i < (voices || []).length; i += 1) {
      if (voices[i].id === vid) return voices[i];
    }
    return null;
  }

  /** The engine badge for one actor against the active engine: word +
   *  tone + why. An actor always SPEAKS through the active engine; the
   *  badge says which engine its reference was cut for (#1476). */
  function engineBadgeOf(voice, active) {
    var eng = String((voice && voice.engine) || '').toLowerCase();
    if (!eng) return {word: 'PRESET', tone: 'mute', why: 'No capture engine recorded.'};
    var word = eng === 'xtts' ? 'XTTS' : eng === 'f5' ? 'F5' : eng.toUpperCase();
    if (!active || eng === active) {
      return {word: word, tone: 'ok', why: 'Reference cut for ' + word + '.'};
    }
    return {word: word, tone: 'warn',
      why: 'Reference cut for ' + word + '; the station is on '
        + String(active).toUpperCase()
        + ', so this actor speaks through that engine with this one reference.'};
  }

  /** The five seat rows from the live stores. `va` may be null (the
   *  voice-actor store is not on the station yet). */
  function seatModel(settings, guests, va) {
    var dj = (settings && settings.dj) || {};
    var g = guests || {};
    var activeGuest = null;
    if (g.active) {
      for (var i = 0; i < (g.guests || []).length; i += 1) {
        if (g.guests[i].id === g.active) activeGuest = g.guests[i];
      }
    }
    return [
      {seat: 'host', role: 'Host', name: String(dj.host_name || 'Host'), voiceId: String(dj.voice || '')},
      {seat: 'cohost', role: 'Co-host', name: String(dj.cohost_name || 'Co-host'), voiceId: String(dj.cohost_voice || '')},
      {seat: 'guest', role: 'In-station guest', on: !!dj.guest_mode,
        name: String(dj.third_name || ''), voiceId: String(dj.third_voice || ''),
        guestId: String(dj.guest_id || ''), guest: activeGuest,
        manualThird: !!(dj.third_name && !dj.guest_mode)},
      {seat: 'scheduled', role: 'Scheduled caller',
        callerId: String((va && va.scheduled && va.scheduled.caller_id) || ''),
        callerName: String((va && va.scheduled && va.scheduled.caller) || '')},
      {seat: 'random', role: 'Random caller',
        pin: (va && va.random_pin && va.random_pin.caller_id) ? va.random_pin : null}
    ];
  }

  function comboSummary(combo, voices, guests) {
    var seats = (combo && combo.seats) || {};
    var bits = [voiceName(voices, seats.host) || '(host unchanged)',
                voiceName(voices, seats.cohost) || '(co-host unchanged)'];
    if (seats.guest_id) {
      var gname = seats.guest_id;
      for (var i = 0; i < ((guests && guests.guests) || []).length; i += 1) {
        if (guests.guests[i].id === seats.guest_id) gname = guests.guests[i].name;
      }
      bits.push('guest: ' + gname);
    } else if (seats.third_voice) {
      bits.push('third: ' + voiceName(voices, seats.third_voice));
    }
    return bits.join(' + ');
  }

  /** One dispatch row's state word for the chips: queued | ringing |
   *  on air | done, or the ledger's honest refusal (held, missed, lost,
   *  failed, cancelled). Real timestamps only: "on air" means a line of
   *  theirs was heard within the last ON_AIR_WINDOW_S seconds. */
  function dispatchWord(row, nowS) {
    if (!row) return '';
    var state = String(row.state || '');
    if (state === 'aired') {
      var at = Number(row.last_air_at || row.aired_at || 0);
      return (nowS - at) <= ON_AIR_WINDOW_S ? 'on air' : 'done';
    }
    if (state === 'planned' || state === 'writing') return 'ringing';
    return state || '';
  }

  function dispatchTone(word) {
    if (word === 'on air') return 'live';
    if (word === 'done') return 'ok';
    if (word === 'queued' || word === 'ringing' || word === 'held') return 'warn';
    if (word === 'cancelled' || !word) return 'mute';
    return 'bad';
  }

  /** Can this dispatch still be called back? Only before any writing. */
  function dispatchOpen(row) {
    var s = String((row && row.state) || '');
    return s === 'queued' || s === 'held';
  }

  /** What the two dispatch roads mean, in the panel's words. */
  function roadWord(road) {
    return road === 'now' ? 'call in now' : road === 'next' ? 'queue next'
      : road === 'scheduled' ? 'scheduled seat' : road === 'random' ? 'random seat' : String(road || '');
  }

  function rotationLine(voicesAnswer) {
    var n = Number(voicesAnswer && voicesAnswer.in_rotation) || 0;
    var pct = Number(voicesAnswer && voicesAnswer.clone_caller_pct);
    var line = 'drawn per call - ' + n + ' voice' + (n === 1 ? '' : 's') + ' in rotation';
    if (isFinite(pct)) line += ', ' + pct + '% ring in as clones';
    return line;
  }

  function readPanels(storage) {
    try {
      var raw = storage && storage.getItem(PANELS_KEY);
      var got = raw ? JSON.parse(raw) : null;
      var out = {};
      PANEL_ORDER.forEach(function (id) {
        out[id] = got && typeof got[id] === 'boolean' ? got[id] : DEFAULT_OPEN[id];
      });
      return out;
    } catch (err) { return Object.assign({}, DEFAULT_OPEN); }
  }

  function writePanels(storage, open) {
    try { if (storage) storage.setItem(PANELS_KEY, JSON.stringify(open)); }
    catch (err) { /* a locked profile still gets the session */ }
  }

  /* ================================================== the station road */

  function httpPage() {
    try { return /^https?:$/.test(String(root.location && root.location.protocol)); } catch (err) { return false; }
  }

  function bridge() {
    var b = root.pineDesktop;
    return b && typeof b.get === 'function' ? b : null;
  }

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
    try { /* the panel's own `const SERVER_KEY` is a lexical global, not a window property */
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

  /* The desk's page is file: - every call goes through the desk bridge (it
   * holds the key, and keeps these out of the WebView's six-socket pool on
   * the tablet). A page with no bridge fetches directly with the key. */
  function request(method, path, body, ms) {
    var bound = ms > 0 ? ms : REQUEST_MS;   /* [va-strips] a longer bound on request */
    var b = bridge();
    var fn = b && (method === 'GET' ? b.get : method === 'POST' ? b.post
      : method === 'PUT' ? b.put : b.del);
    if (fn) return withTimeout(fn.call(b, path, method === 'GET' ? undefined : (body || {})), bound, path);
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to the station on this screen'));
    var headers = {};
    var key = stationKey();
    if (key) headers.Authorization = 'Bearer ' + key;
    if (method !== 'GET') headers['Content-Type'] = 'application/json';
    var ctl = typeof root.AbortController === 'function' ? new root.AbortController() : null;
    var timer = ctl ? root.setTimeout(function () { try { ctl.abort(); } catch (err) { /* done */ } }, bound) : 0;
    return root.fetch(stationUrl(path), {method: method, headers: headers, cache: 'no-store',
      body: method === 'GET' ? undefined : JSON.stringify(body || {}), signal: ctl ? ctl.signal : undefined})
      .then(function (res) {
        return res.text().then(function (text) {
          var data = {};
          try { data = text ? JSON.parse(text) : {}; } catch (err) { data = {detail: text.slice(0, 200)}; }
          if (!res.ok) {
            var e = new Error(String((data && (data.detail || data.say)) || (res.status + ' ' + res.statusText)));
            e.status = res.status;
            throw e;
          }
          return data;
        });
      }, function (err) {
        throw new Error(err && err.name === 'AbortError' ? path + ' took longer than ' + Math.round(bound / 1000) + ' s' : String((err && err.message) || err));
      })
      .then(function (v) { if (timer) root.clearTimeout(timer); return v; },
        function (e) { if (timer) root.clearTimeout(timer); throw e; });
  }

  function get(path) { return request('GET', path); }
  function post(path, body) { return request('POST', path, body); }
  function put(path, body) { return request('PUT', path, body); }

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
    var span = make('span', 'va-ico');
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
    var b = make('button', 'va-btn' + (cls ? ' ' + cls : ''));
    b.type = 'button';
    if (iconName) b.appendChild(iconNode(iconName));
    if (words) b.appendChild(make('span', 'va-btn-words', words));
    if (title) { b.title = title; b.setAttribute('aria-label', title); }
    return b;
  }

  function chip(word, tone, title) {
    var c = make('span', 'va-chip' + (tone ? ' va-chip-' + tone : ''), word);
    if (title) c.title = title;
    return c;
  }

  function guardInput(input) {
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

  function storage() {
    try { return root.localStorage || null; } catch (err) { return null; }
  }

  function emit(name, detail) {
    try { root.dispatchEvent(new root.CustomEvent('pine-voice-actor:' + name, {detail: detail || {}})); }
    catch (err) { /* an old WebView without CustomEvent constructor still works without listeners */ }
  }

  /* ================================================== the model */

  var model = {
    engines: null, enginesAt: 0, engineFailure: '',
    settings: null, voices: null, voicesAnswer: null,
    callers: null, guests: null,
    va: null, vaAbsent: false, vaFailure: '',
    lastSay: ''
  };

  var ui = {
    started: false, built: false, visible: false,
    pop: null, body: null, badge: null, barObserver: null,
    panels: {}, open: readPanels(storage()),
    sayLine: null, headSub: null, enginePill: null,
    strip: null, stripMode: 'show', stripTo: '',
    layers: [],                    /* the open overlay stack, topmost last */
    picker: null, extract: null,
    selectedCaller: '',
    unwatchers: [], unback: null,
    engineTimer: 0, stateTimer: 0, slowTimer: 0,
    extractDef: null, extractMounted: false,
    stripSig: '', topicDraft: {},
    busy: {}
  };

  /* ================================================== the badge */

  function attachBadge() {
    var bar = document.getElementById('pineConsoleLine');
    if (!bar) return false;
    var have = bar.querySelector('.pine-console-actor');
    if (have) { ui.badge = have; return true; }
    var b = make('button', 'pine-console-actor');
    b.type = 'button';
    b.setAttribute('aria-haspopup', 'dialog');
    b.setAttribute('aria-label', 'Voice actors - the cast on the air');
    b.title = 'Voice actors - the cast on the air';
    b.appendChild(make('span', 'va-badge-ico'));
    b.appendChild(make('span', 'va-badge-word'));
    b.addEventListener('click', function (e) {
      /* the bar opens its audit list on any click it does not know */
      e.stopPropagation();
      e.preventDefault();
      toggleOpen();
    });
    /* Beside the PineLive mic: right after it when it is already there,
     * else the same slot the mic itself takes (before the gallery). */
    /* [vaicon] where the operator marked it: right after the "i" (changelog), before the readout */
    var info = bar.querySelector('.pine-console-change');
    var before = info ? info.nextSibling : bar.querySelector('.pine-console-viewport');
    bar.insertBefore(b, before || null);
    ui.badge = b;
    paintBadge();
    return true;
  }

  function paintBadge() {
    var b = ui.badge;
    if (!b || !b.isConnected) return;
    var ico = b.querySelector('.va-badge-ico');
    if (ico && !ico.__vaDrawn) {
      var mark = icon('c:user--avatar', '');
      /* the sprite may not be on the page yet at document start: say CAST
       * and try again on the next paint rather than keep the words */
      if (mark) { ico.innerHTML = mark; ico.__vaDrawn = true; } else ico.textContent = 'CAST';
    }
    setClass(b, 'open', ui.visible);
    var dj = (model.settings && model.settings.dj) || null;
    var title = 'Voice actors - the cast on the air';
    if (dj) title += ' (' + String(dj.host_name || 'Host') + ' + ' + String(dj.cohost_name || 'Co-host') + ')';
    if (b.title !== title) { b.title = title; b.setAttribute('aria-label', title); }
  }

  function watchForBar() {
    if (attachBadge()) { /* keep watching: a rebuilt bar needs its person back */ }
    if (ui.barObserver || typeof root.MutationObserver !== 'function' || !document.body) return;
    ui.barObserver = new root.MutationObserver(function () {
      var bar = document.getElementById('pineConsoleLine');
      if (bar && !bar.querySelector('.pine-console-actor')) attachBadge();
      paintBadge();
    });
    ui.barObserver.observe(document.body, {childList: true});
  }

  /* ================================================== layers (one stack) */

  function layerPush(node, close) {
    ui.layers.push({node: node, close: close});
    node.hidden = false;
  }

  function layerDrop(node) {
    for (var i = ui.layers.length - 1; i >= 0; i -= 1) {
      if (ui.layers[i].node === node) ui.layers.splice(i, 1);
    }
    node.hidden = true;
  }

  function topLayer() {
    for (var i = ui.layers.length - 1; i >= 0; i -= 1) {
      if (ui.layers[i].node && !ui.layers[i].node.hidden) return ui.layers[i];
    }
    return null;
  }

  /* ================================================== the popup */

  function buildPopup() {
    if (ui.built) return;
    ui.built = true;
    var pop = make('div', 'va-pop');
    pop.id = 'pineVoiceActor';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', 'Voice actors - the cast on the air');
    pop.setAttribute('data-pine-drag', '');
    pop.hidden = true;

    var head = make('div', 'va-head');
    head.setAttribute('data-pine-drag-handle', '');
    var mark = make('div', 'va-head-mark');
    mark.appendChild(iconNode('c:user--avatar'));
    head.appendChild(mark);
    var titles = make('div', 'va-head-titles');
    titles.appendChild(make('b', '', 'Voice actors'));
    ui.headSub = make('span', '', 'the cast on the air');
    titles.appendChild(ui.headSub);
    head.appendChild(titles);
    var newActor = btn('va-mini va-new-actor', 'New actor', 'c:add',
      'Create a new voice actor - opens the extraction studio');
    newActor.addEventListener('click', function (e) { e.stopPropagation(); openExtract(); });
    head.appendChild(newActor);
    var close = make('button', 'va-close');
    close.type = 'button';
    close.title = 'Close';
    close.setAttribute('aria-label', 'Close the voice actor panel');
    close.innerHTML = icon('c:close--filled', '') || 'x';
    close.addEventListener('click', function (e) { e.stopPropagation(); closePopup(); });
    head.appendChild(close);
    pop.appendChild(head);

    ui.sayLine = make('div', 'va-say');
    ui.sayLine.hidden = true;
    ui.sayLine.setAttribute('role', 'status');
    pop.appendChild(ui.sayLine);

    pop.appendChild(buildEngineStrip());

    var body = make('div', 'va-body');
    pop.appendChild(body);
    ui.body = body;
    ui.pop = pop;

    PANEL_ORDER.forEach(function (id) { body.appendChild(buildPanel(id)); });

    pop.appendChild(buildPicker());
    pop.appendChild(buildExtract());

    document.body.appendChild(pop);

    /* Its ways out. PineDismiss for a tap off it and Escape; BACK answers
     * the TOPMOST layer first, then the popup (#1450's rule). */
    var dismiss = root.PineDismiss;
    if (dismiss && typeof dismiss.watch === 'function') {
      ui.unwatchers.push(dismiss.watch(pop, closePopup,
        [function () { return ui.badge; }], function () { return ui.visible; }));
    }
    var probe = function () {
      if (!ui.visible) return null;
      var top = topLayer();
      if (top) return {node: top.node, close: top.close};
      return {node: pop, close: closePopup};
    };
    if (dismiss && typeof dismiss.onBack === 'function') {
      ui.unback = dismiss.onBack(probe);
    } else {
      /* an older page without PineDismiss.onBack: chain pineBack itself */
      var was = root.pineBack;
      root.pineBack = function () {
        var p = probe();
        if (p) { try { p.close(); } catch (err) { /* closed anyway */ } return true; }
        return typeof was === 'function' ? was() : false;
      };
    }
  }

  function openPopup() {
    buildPopup();
    if (ui.visible) return;
    ui.visible = true;
    ui.pop.hidden = false;
    paintBadge();
    refreshAll();
    scheduleEngine(0);
    scheduleState(0);
    scheduleSlow(POLL_SLOW_MS);
    emit('open', {});
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no wall */ }
  }

  function closePopup() {
    if (!ui.visible) return;
    while (ui.layers.length) {
      var top = ui.layers[ui.layers.length - 1];
      try { top.close(); } catch (err) { layerDrop(top.node); }
    }
    ui.visible = false;
    if (ui.pop) ui.pop.hidden = true;
    if (ui.engineTimer) { root.clearTimeout(ui.engineTimer); ui.engineTimer = 0; }
    if (ui.stateTimer) { root.clearTimeout(ui.stateTimer); ui.stateTimer = 0; }
    if (ui.slowTimer) { root.clearTimeout(ui.slowTimer); ui.slowTimer = 0; }
    paintBadge();
    emit('close', {});
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (err) { /* no wall */ }
  }

  function toggleOpen() { if (ui.visible) closePopup(); else openPopup(); }

  function say(text, kind) {
    model.lastSay = String(text || '');
    if (!ui.built) return;
    setText(ui.sayLine, model.lastSay);
    ui.sayLine.className = 'va-say' + (kind ? ' ' + kind : '');
    setHidden(ui.sayLine, !model.lastSay);
  }

  function act(path, body, busyNode, method) {
    if (busyNode) { busyNode.disabled = true; setClass(busyNode, 'busy', true); }
    var road = method === 'PUT' ? put : post;
    return road(path, body).then(function (ans) {
      if (busyNode) { busyNode.disabled = false; setClass(busyNode, 'busy', false); }
      if (ans && ans.ok === false) say(ans.say || ans.detail || 'The station refused that.', 'bad');
      else if (ans && ans.say) say(ans.say, '');
      return ans || {};
    }, function (err) {
      if (busyNode) { busyNode.disabled = false; setClass(busyNode, 'busy', false); }
      say('The station did not take that: ' + String((err && err.message) || err), 'bad');
      throw err;
    });
  }

  /* ================================================== refresh + polling */

  function refreshEngines() {
    return get('/api/voice/engine-switch').then(function (ans) {
      model.engines = ans || {};
      model.enginesAt = Date.now();
      model.engineFailure = '';
      paint();
    }, function (err) {
      model.engineFailure = String((err && err.message) || err);
      paint();
    });
  }

  function refreshVaState() {
    return get('/api/voice-actor/state').then(function (ans) {
      model.va = ans || {};
      model.vaAbsent = false;
      model.vaFailure = '';
      paint();
    }, function (err) {
      if (err && (err.status === 404 || /404|not found/i.test(String(err.message || '')))) {
        model.va = null;
        model.vaAbsent = true;
      } else {
        model.vaFailure = String((err && err.message) || err);
      }
      paint();
    });
  }

  function refreshCast() {
    var jobs = [
      get('/api/settings').then(function (s) { model.settings = s || {}; }),
      get('/api/voices').then(function (v) {
        model.voicesAnswer = v || {};
        model.voices = (v && v.voices) || [];
        emit('actors', {voices: model.voices});
      }),
      get('/api/dj/callers').then(function (c) { model.callers = c || {}; }),
      get('/api/dj/guests').then(function (g) { model.guests = g || {}; })
    ];
    return Promise.all(jobs.map(function (p) {
      return p.catch(function (err) {
        say('A store did not answer: ' + String((err && err.message) || err), 'bad');
      });
    })).then(paint);
  }

  function refreshAll() {
    refreshEngines();
    refreshVaState();
    return refreshCast();
  }

  function scheduleEngine(ms) {
    if (ui.engineTimer) root.clearTimeout(ui.engineTimer);
    ui.engineTimer = root.setTimeout(function () {
      ui.engineTimer = 0;
      if (!ui.visible) return;
      refreshEngines().then(function () { scheduleEngine(POLL_ENGINE_MS); });
    }, ms);
  }

  function scheduleState(ms) {
    if (ui.stateTimer) root.clearTimeout(ui.stateTimer);
    ui.stateTimer = root.setTimeout(function () {
      ui.stateTimer = 0;
      if (!ui.visible) return;
      refreshVaState().then(function () { scheduleState(POLL_STATE_MS); });
    }, ms);
  }

  function scheduleSlow(ms) {
    if (ui.slowTimer) root.clearTimeout(ui.slowTimer);
    ui.slowTimer = root.setTimeout(function () {
      ui.slowTimer = 0;
      if (!ui.visible) return;
      refreshCast().then(function () { scheduleSlow(POLL_SLOW_MS); });
    }, ms);
  }

  /* ================================================== the engine strip */

  function buildEngineStrip() {
    var strip = make('div', 'va-engine-strip');
    strip.setAttribute('aria-label', 'The active voice engine');
    ui.strip = strip;
    paintEngineStrip();
    return strip;
  }

  function engineRow(id) {
    var e = (model.engines && model.engines.engines && model.engines.engines[id]) || {};
    return {id: id, label: String(e.label || id.toUpperCase()),
      ready: !!e.ready, detail: String(e.detail || '')};
  }

  function paintEngineStrip() {
    var strip = ui.strip;
    if (!strip) return;
    strip.replaceChildren();
    var active = String((model.engines && model.engines.engine) || '');
    if (ui.stripMode === 'confirm') {
      var to = engineRow(ui.stripTo);
      var from = engineRow(active || (ui.stripTo === 'xtts' ? 'f5' : 'xtts'));
      var box = make('div', 'va-engine-confirm');
      var words = 'Move the whole cast to ' + to.label + '? The swap takes about a minute - '
        + 'lines come from banked audio, then a stand-in voice, while it loads. '
        + 'Every per-seat engine pin is stripped (#1476).';
      if (!to.ready) {
        words += ' ' + to.label + ' is not answering right now ('
          + (to.detail || 'no detail') + ') - the switch will ask the director to load it.';
      }
      box.appendChild(make('p', '', words));
      var go = btn('va-mini', 'Switch to ' + to.label, 'c:checkmark',
        'Confirm the engine switch - the Host menu\'s road');
      go.classList.add('va-engine-go');
      go.addEventListener('click', function (e) {
        e.stopPropagation();
        act('/api/voice/engine-switch', {engine: ui.stripTo}, go).then(function () {
          ui.stripMode = 'show';
          say('The cast is moving to ' + to.label + ' - the other engine closes first.', '');
          refreshEngines();
        }, function () { /* the say line already carries the refusal */ });
      });
      box.appendChild(go);
      var keep = btn('va-mini', 'Keep ' + (from.label || 'this one'), '', 'Do not switch');
      keep.classList.add('va-engine-keep');
      keep.addEventListener('click', function (e) {
        e.stopPropagation();
        ui.stripMode = 'show';
        paintEngineStrip();
      });
      box.appendChild(keep);
      strip.appendChild(box);
      return;
    }
    strip.appendChild(make('small', '', 'Engine'));
    var seg = make('div', 'va-engine-seg');
    seg.setAttribute('role', 'radiogroup');
    seg.setAttribute('aria-label', 'The one global engine switch (the Host menu\'s road)');
    ['xtts', 'f5'].forEach(function (id) {
      var e = engineRow(id);
      var b = make('button', 'va-engine-' + id);
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', active === id ? 'true' : 'false');
      var dot = make('i', 'va-dot ' + (e.ready ? 'ok' : 'bad'));
      b.appendChild(dot);
      b.appendChild(make('span', '', e.label));
      b.title = e.label + (e.ready ? ' - loaded' : ' - down: ' + (e.detail || 'not answering'));
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if (active === id) return;
        ui.stripMode = 'confirm';
        ui.stripTo = id;
        paintEngineStrip();
      });
      seg.appendChild(b);
    });
    strip.appendChild(seg);
    var note = make('span', 'va-engine-note');
    if (model.engineFailure) {
      note.classList.add('warn');
      setText(note, 'The engine road did not answer: ' + model.engineFailure);
    } else if (model.engines) {
      var sw = model.engines.switch || {};
      var recent = sw.at && (Date.now() / 1000 - Number(sw.at)) < 120;
      if (recent && sw.to) {
        note.classList.add('warn');
        setText(note, 'Switching ' + String(sw.from || '').toUpperCase() + ' to '
          + String(sw.to || '').toUpperCase() + ' - banked audio covers while it loads.');
      } else {
        var a = engineRow(active || 'xtts');
        setText(note, 'The whole cast speaks through ' + a.label
          + (a.ready ? '.' : ' - which is NOT ready: ' + (a.detail || 'not answering')));
        if (!a.ready) note.classList.add('warn');
      }
    } else {
      setText(note, 'Reading the engine road...');
    }
    strip.appendChild(note);
  }

  /* ================================================== the cards */

  var PANELS = {
    cast: {title: 'Cast', icon: 'c:group', build: buildCast, paint: paintCast, summary: summaryCast,
      sig: function () { return sigCast(); }},
    combos: {title: 'Combos', icon: 'c:save', build: buildCombos, paint: paintCombos, summary: summaryCombos,
      sig: function () { return sigCombos(); }},
    callers: {title: 'Callers', icon: 'c:phone', build: buildCallers, paint: paintCallers, summary: summaryCallers,
      sig: function () { return sigCallers(); }}
  };

  function buildPanel(id) {
    var def = PANELS[id];
    var sec = make('section', 'va-panel va-panel-' + id);
    sec.setAttribute('data-panel', id);
    var head = make('button', 'va-panel-head');
    head.type = 'button';
    head.appendChild(iconNode('c:caret--right'));
    head.appendChild(iconNode(def.icon));
    head.appendChild(make('b', '', def.title));
    var sum = make('span', 'va-panel-sum', '');
    head.appendChild(sum);
    var body = make('div', 'va-panel-body');
    sec.appendChild(head);
    sec.appendChild(body);
    var panel = {id: id, root: sec, head: head, body: body, sum: sum, parts: {}};
    ui.panels[id] = panel;
    def.build(panel);
    head.addEventListener('click', function (e) {
      e.stopPropagation();
      ui.open[id] = !ui.open[id];
      writePanels(storage(), ui.open);
      paint();
    });
    return sec;
  }

  /* A card whose inputs are being typed into is not rebuilt under the
   * finger: its summary still moves, its body waits for the next paint. */
  function editingIn(node) {
    var a = document.activeElement;
    if (!a || !node || !node.contains(a)) return false;
    return a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || !!a.__editing;
  }

  function paint(force) {
    paintBadge();
    if (!ui.built || !ui.visible) return;
    var dj = (model.settings && model.settings.dj) || {};
    setText(ui.headSub, String(dj.host_name || 'Host') + ' + ' + String(dj.cohost_name || 'Co-host')
      + (dj.guest_mode && dj.third_name ? ' + ' + dj.third_name : ''));
    var stripSig = JSON.stringify([ui.stripMode, ui.stripTo, model.engines && model.engines.engine,
      model.engines && model.engines.engines, model.engines && model.engines.switch, model.engineFailure]);
    if (force || stripSig !== ui.stripSig) { ui.stripSig = stripSig; paintEngineStrip(); }
    PANEL_ORDER.forEach(function (id) {
      var p = ui.panels[id];
      var open = !!ui.open[id];
      setClass(p.root, 'open', open);
      p.head.setAttribute('aria-expanded', open ? 'true' : 'false');
      setHidden(p.body, !open);
      var s = '';
      try { s = PANELS[id].summary() || ''; } catch (err) { s = ''; }
      setText(p.sum, s);
      if (!open) { p.sig = ''; return; }
      /* Rebuild a card only when what it shows changed: a poll that brings
       * nothing new never replaces the button under a finger. */
      var sig = '';
      try { sig = JSON.stringify(PANELS[id].sig()); } catch (err) { sig = String(Math.random()); }
      if (!force && sig === p.sig) return;
      if (!force && editingIn(p.body)) return;
      p.sig = sig;
      try { PANELS[id].paint(p); }
      catch (err) {
        /* one card's fault must not blank the others (the one-subscriber lesson) */
        if (root.console) root.console.error('[voice-actor] ' + id + ' paint failed:', err);
      }
    });
    if (ui.picker && !ui.picker.hidden && !editingIn(ui.pickerParts.list)) paintPicker();
  }

  /* The half-minute clock the dispatch chips read ("on air" becomes "done"),
   * so a card with a live call still repaints when nothing else moved. */
  function tick() { return Math.floor(Date.now() / 30000); }

  function voicesSig() {
    return (model.voices || []).map(function (v) { return [v.id, v.name, v.engine, v.kind]; });
  }

  function sigCast() {
    var dj = (model.settings && model.settings.dj) || {};
    return [dj.host_name, dj.cohost_name, dj.voice, dj.cohost_voice, dj.third_name, dj.third_voice,
      dj.guest_mode, dj.guest_id, voicesSig(), model.engines && model.engines.engine,
      model.va && model.va.scheduled, model.va && model.va.random_pin, model.va && model.va.prefs,
      model.va && model.va.dispatch, model.guests, model.vaAbsent,
      model.voicesAnswer && [model.voicesAnswer.in_rotation, model.voicesAnswer.clone_caller_pct],
      (model.callers && model.callers.callers || []).map(function (c) { return [c.id, c.name, c.voice_id]; }),
      tick()];
  }

  function sigCombos() {
    return [model.va && model.va.combos, model.vaAbsent, voicesSig(), model.guests];
  }

  function sigCallers() {
    return [model.callers, model.va && model.va.dispatch, model.va && model.va.interjection,
      model.vaAbsent, ui.selectedCaller, voicesSig(), tick()];
  }

  /* ------------------------------------------------------------- cast */

  var SEAT_ICONS = {host: 'c:microphone--filled', cohost: 'c:microphone',
    guest: 'c:user--speaker', scheduled: 'c:phone--filled', random: 'c:shuffle'};
  var SEAT_HINTS = {
    host: 'Intros, station IDs, ads, news - the host\'s own voice',
    cohost: 'The other half of every exchange',
    guest: 'The third chair - a guest star seated in the studio',
    scheduled: 'Takes the next scheduled call in the running order - once',
    random: 'Answers the phone clock\'s next ring - once'
  };

  function buildCast(p) {
    p.parts.rows = make('div', 'va-seats');
    p.body.appendChild(p.parts.rows);
    p.parts.note = make('p', 'va-note',
      'Seat changes ride the voice desk\'s own settings road, so a change here '
      + 'cuts to the new voice at the next turn boundary (#820).');
    p.body.appendChild(p.parts.note);
  }

  function summaryCast() {
    var dj = (model.settings && model.settings.dj) || {};
    if (!model.settings) return '';
    var bits = [voiceName(model.voices, dj.voice) || 'no host voice',
                voiceName(model.voices, dj.cohost_voice) || 'no co-host voice'];
    if (dj.guest_mode && dj.third_name) bits.push(dj.third_name);
    return bits.join(' + ');
  }

  function actorChip(row) {
    var wrap = make('span', 'va-seat-actor');
    var v = voiceOf(model.voices, row.voiceId);
    var name = voiceName(model.voices, row.voiceId);
    var b = make('b', name ? '' : 'va-empty', name || 'no voice set');
    wrap.appendChild(b);
    if (v) {
      var active = String((model.engines && model.engines.engine) || '');
      var badge = engineBadgeOf(v, active);
      wrap.appendChild(chip(badge.word, badge.tone, badge.why));
      var pref = prefOf(row.voiceId);
      if (pref) wrap.appendChild(chip('prefers ' + pref.toUpperCase(), 'mute',
        'This actor\'s recorded preferred engine. Everyone still speaks through the active engine.'));
    }
    return wrap;
  }

  function paintCast(p) {
    var rows = seatModel(model.settings, model.guests, model.va);
    var host = p.parts.rows;
    host.replaceChildren();
    rows.forEach(function (row) {
      var seat = make('div', 'va-seat va-seat-' + row.seat);
      var role = make('div', 'va-seat-role');
      role.appendChild(iconNode(SEAT_ICONS[row.seat]));
      var t = make('div');
      t.appendChild(make('b', '', row.role + (row.name ? ' - ' + row.name : '')));
      var hint = make('small');
      t.appendChild(hint);
      role.appendChild(t);
      role.title = SEAT_HINTS[row.seat];
      seat.appendChild(role);

      var mid, side;
      if (row.seat === 'host' || row.seat === 'cohost') {
        setText(hint, SEAT_HINTS[row.seat]);
        seat.appendChild(actorChip(row));
        side = make('div', 'va-seat-side');
        var change = btn('va-mini', 'Change', 'c:edit', 'Pick this seat\'s voice actor');
        change.addEventListener('click', function (e) {
          e.stopPropagation();
          openPicker('voice', {
            title: row.role + '\'s voice actor', current: row.voiceId,
            choose: function (vid) { setSeatVoice(row.seat, vid); }
          });
        });
        side.appendChild(change);
        seat.appendChild(side);
      } else if (row.seat === 'guest') {
        setText(hint, row.on ? 'in the studio now' : (row.manualThird
          ? 'a manual third chair is set on the voice desk' : 'the third chair is empty'));
        setClass(seat, 'va-on', row.on);
        mid = make('span', 'va-seat-actor');
        if (row.on) {
          mid.appendChild(make('b', '', row.name || 'Guest'));
          if (row.voiceId) {
            var v = voiceOf(model.voices, row.voiceId);
            var badge = engineBadgeOf(v || {engine: ''}, String((model.engines && model.engines.engine) || ''));
            mid.appendChild(chip(voiceName(model.voices, row.voiceId), 'mute', 'The guest\'s own voice'));
            if (v) mid.appendChild(chip(badge.word, badge.tone, badge.why));
          } else {
            mid.appendChild(chip('voice drawn fresh', 'mute',
              'No voice pinned: session_voices draws a distinct third voice'));
          }
        } else if (row.manualThird) {
          mid.appendChild(make('b', '', row.name));
          mid.appendChild(chip('manual third', 'mute', 'Named on the voice desk, not a stored guest'));
        } else {
          mid.appendChild(make('b', 'va-empty', 'nobody in the third chair'));
        }
        seat.appendChild(mid);
        side = make('div', 'va-seat-side');
        var sw = make('button', 'va-switch');
        sw.type = 'button';
        sw.setAttribute('role', 'switch');
        sw.setAttribute('aria-checked', row.on ? 'true' : 'false');
        sw.title = row.on ? 'Clear the third chair now (silent - Send home plays the goodbye)'
      : 'Seat a guest star in the studio';
        sw.appendChild(make('i'));
        sw.addEventListener('click', function (e) {
          e.stopPropagation();
          if (row.on) {
            act('/api/dj/guest/activate', {on: false}, sw).then(refreshCast, function () {});
          } else {
            openPicker('guest', {title: 'Seat a guest star'});
          }
        });
        side.appendChild(sw);
        if (row.on) {
          var home = btn('va-mini', 'Send home', 'c:user', 'Play the goodbye round, then clear the seat (#718)');
          home.addEventListener('click', function (e) {
            e.stopPropagation();
            act('/api/dj/guest/send-home', {}, home).then(refreshCast, function () {});
          });
          side.appendChild(home);
        }
        var pickG = btn('va-mini', row.on ? 'Change' : 'Pick', 'c:edit', 'Pick the guest star');
        pickG.addEventListener('click', function (e) {
          e.stopPropagation();
          openPicker('guest', {title: 'Seat a guest star'});
        });
        side.appendChild(pickG);
        seat.appendChild(side);
      } else if (row.seat === 'scheduled') {
        setText(hint, SEAT_HINTS[row.seat]);
        mid = make('span', 'va-seat-actor');
        var c = callerOf(row.callerId);
        if (c || row.callerId) {
          mid.appendChild(make('b', '', (c && c.name) || row.callerName || row.callerId));
          mid.appendChild(chip('armed', 'warn', 'Takes the next scheduled call entry instead of the shelf, then the seat clears'));
          if (c && c.voice_id) mid.appendChild(chip(voiceName(model.voices, c.voice_id), 'mute', 'The caller\'s pinned clone'));
        } else {
          var lastS = lastSeatDispatch('scheduled');
          mid.appendChild(make('b', 'va-empty', model.vaAbsent
            ? 'needs the voice-actor store (backend tool)' : 'the station\'s own shelf and draw'));
          if (lastS) {
            var wordS = dispatchWord(lastS, Date.now() / 1000);
            mid.appendChild(chip(lastS.caller + ': ' + wordS, dispatchTone(wordS), lastS.why || ''));
          }
        }
        seat.appendChild(mid);
        side = make('div', 'va-seat-side');
        if (row.callerId) {
          var clearS = btn('va-mini', 'Clear', 'c:misuse', 'Back to the station\'s own draw');
          clearS.addEventListener('click', function (e) {
            e.stopPropagation();
            act('/api/voice-actor/scheduled', {caller_id: ''}, clearS).then(refreshVaState, function () {});
          });
          side.appendChild(clearS);
        }
        var pickS = btn('va-mini', row.callerId ? 'Change' : 'Arm', 'c:edit', 'Pick the scheduled caller from the list');
        pickS.disabled = !!model.vaAbsent;
        pickS.addEventListener('click', function (e) {
          e.stopPropagation();
          openPicker('caller', {title: 'Scheduled caller', current: row.callerId,
            choose: function (cid) {
              act('/api/voice-actor/scheduled', {caller_id: cid}).then(refreshVaState, function () {});
            }});
        });
        side.appendChild(pickS);
        seat.appendChild(side);
      } else if (row.seat === 'random') {
        setText(hint, SEAT_HINTS[row.seat]);
        mid = make('span', 'va-seat-actor');
        if (row.pin) {
          var pc = callerOf(row.pin.caller_id);
          mid.appendChild(make('b', '', (pc && pc.name) || row.pin.caller || row.pin.caller_id));
          mid.appendChild(chip('pinned next', 'warn',
            'The next random ring goes to this caller once, then the pin clears.'));
        } else {
          mid.appendChild(make('b', 'va-empty', rotationLine(model.voicesAnswer)));
          var lastR = lastSeatDispatch('random');
          if (lastR) {
            var wordR = dispatchWord(lastR, Date.now() / 1000);
            mid.appendChild(chip(lastR.caller + ': ' + wordR, dispatchTone(wordR), lastR.why || ''));
          }
        }
        seat.appendChild(mid);
        side = make('div', 'va-seat-side');
        if (row.pin) {
          var clearPin = btn('va-mini', 'Unpin', 'c:misuse', 'Let the rotation draw freely again');
          clearPin.addEventListener('click', function (e) {
            e.stopPropagation();
            act('/api/voice-actor/random-pin', {caller_id: ''}, clearPin).then(refreshVaState, function () {});
          });
          side.appendChild(clearPin);
        }
        var pickR = btn('va-mini', 'Pin next', 'c:pin--filled', 'Pin who the next random caller is');
        pickR.disabled = !!model.vaAbsent;
        pickR.addEventListener('click', function (e) {
          e.stopPropagation();
          openPicker('caller', {title: 'Pin the next random caller',
            current: row.pin ? row.pin.caller_id : '',
            choose: function (cid) {
              act('/api/voice-actor/random-pin', {caller_id: cid}).then(refreshVaState, function () {});
            }});
        });
        side.appendChild(pickR);
        seat.appendChild(side);
      }
      if (ui.stripDef) {                       /* [va-strips] the profile strip under this seat */
        try { ui.stripDef.seat(seat, row, stripCtx()); }
        catch (err) { if (root.console) root.console.error('[voice-actor] strip failed:', err); }
      }
      host.appendChild(seat);
    });
  }

  function setSeatVoice(seat, vid) {
    var key = SEAT_KEYS[seat];
    if (!key) return Promise.resolve(null);
    /* The server writes the one key through api_put_settings itself (the
     * voice desk's road, #820's cut included) from the STORED settings - the
     * panel never PUTs a copy of the settings back, so a level the operator
     * moved meanwhile can never be undone from here. */
    return act('/api/voice-actor/seat', {seat: seat === 'guestvoice' ? 'third' : seat,
      voice_id: String(vid || '')}).then(function () {
      return refreshCast();
    }, function (err) {
      if (err && err.status === 404) {
        say('Seat changes need the voice-actor backend (tools/voice_actor_backend_patch.py) - '
          + 'the Voices desk sets seats meanwhile.', 'bad');
      }
    });
  }

  function prefOf(vid) {
    var prefs = (model.va && model.va.prefs) || {};
    var row = prefs[vid];
    var p = row && String(row.preferred || '');
    return p === 'xtts' || p === 'f5' ? p : '';
  }

  function callerOf(cid) {
    var rows = (model.callers && model.callers.callers) || [];
    for (var i = 0; i < rows.length; i += 1) if (rows[i].id === cid) return rows[i];
    return null;
  }

  function lastDispatchFor(cid) {
    var rows = (model.va && model.va.dispatch) || [];
    for (var i = rows.length - 1; i >= 0; i -= 1) {
      if (rows[i].caller_id === cid) return rows[i];
    }
    return null;
  }

  /** The newest ledger row a seat (scheduled / random) rang - for the seat's
   *  "what happened last time" chip. Rows older than an hour say nothing. */
  function lastSeatDispatch(seat) {
    var rows = (model.va && model.va.dispatch) || [];
    var nowS = Date.now() / 1000;
    for (var i = rows.length - 1; i >= 0; i -= 1) {
      if (rows[i].road === seat) return (nowS - Number(rows[i].at || 0)) < 3600 ? rows[i] : null;
    }
    return null;
  }

  function cancelDispatch(row, busyNode) {
    return act('/api/voice-actor/dispatch/' + encodeURIComponent(row.id) + '/cancel', {}, busyNode)
      .then(function (ans) {
        if (ans && ans.ok) say('Called back: ' + (row.caller || 'the caller') + ' will not ring.', '');
        return refreshVaState();
      }, function () { /* said already */ });
  }

  /* ------------------------------------------------------------- combos */

  function buildCombos(p) {
    p.parts.note = make('p', 'va-note', '');
    p.body.appendChild(p.parts.note);
    p.parts.rows = make('div', 'va-combos');
    p.body.appendChild(p.parts.rows);
    var save = make('div', 'va-combo-save');
    p.parts.name = guardInput(make('input', 'va-input'));
    p.parts.name.type = 'text';
    p.parts.name.placeholder = 'name this pairing - e.g. late night pair';
    p.parts.name.setAttribute('aria-label', 'The new combo\'s name');
    save.appendChild(p.parts.name);
    p.parts.save = btn('', 'Save current cast', 'c:save',
      'Save the seats as they are now as a one-tap combo');
    p.parts.save.addEventListener('click', function (e) {
      e.stopPropagation();
      saveCombo(p.parts.name, p.parts.save);
    });
    save.appendChild(p.parts.save);
    p.body.appendChild(save);
  }

  function summaryCombos() {
    if (model.vaAbsent) return 'needs the backend tool';
    var rows = (model.va && model.va.combos) || [];
    return rows.length ? rows.length + ' saved' : '';
  }

  function paintCombos(p) {
    var absent = !!model.vaAbsent;
    setText(p.parts.note, absent
      ? 'The combo store is not on this station yet - apply tools/voice_actor_backend_patch.py to keep named host + co-host sets.'
      : 'One tap seats a saved pairing through the same settings road the voice desk drives.');
    p.parts.save.disabled = absent;
    var host = p.parts.rows;
    host.replaceChildren();
    var rows = (model.va && model.va.combos) || [];
    rows.forEach(function (combo) {
      var row = make('div', 'va-combo');
      var text = make('div', 'va-combo-text');
      text.appendChild(make('b', '', combo.name || 'combo'));
      text.appendChild(make('small', '', comboSummary(combo, model.voices, model.guests)));
      row.appendChild(text);
      var apply = btn('va-mini', 'Apply', 'c:checkmark', 'Seat this pairing now');
      apply.addEventListener('click', function (e) {
        e.stopPropagation();
        applyCombo(combo, apply);
      });
      row.appendChild(apply);
      var del = btn('va-mini va-danger', '', 'c:trash-can', 'Delete this combo');
      del.addEventListener('click', function (e) {
        e.stopPropagation();
        request('DELETE', '/api/voice-actor/combos/' + encodeURIComponent(combo.id))
          .then(refreshVaState, function (err) {
            say('Delete failed: ' + String((err && err.message) || err), 'bad');
          });
      });
      row.appendChild(del);
      host.appendChild(row);
    });
    if (!rows.length && !absent) {
      host.appendChild(make('p', 'va-muted', 'No combos saved yet.'));
    }
  }

  function saveCombo(nameInput, busyNode) {
    var dj = (model.settings && model.settings.dj) || {};
    var name = String(nameInput.value || '').trim();
    if (!name) {
      name = String(dj.host_name || 'Host') + ' + ' + String(dj.cohost_name || 'Co-host');
    }
    var seats = {host: String(dj.voice || ''), cohost: String(dj.cohost_voice || '')};
    if (dj.guest_mode && dj.guest_id) seats.guest_id = String(dj.guest_id);
    else if (dj.third_voice) seats.third_voice = String(dj.third_voice);
    act('/api/voice-actor/combos', {name: name, seats: seats}, busyNode).then(function () {
      nameInput.value = '';
      say('Saved "' + name + '".', '');
      refreshVaState();
    }, function () { /* said already */ });
  }

  function applyCombo(combo, busyNode) {
    /* One tap, one request: the server seats the voices through
     * api_put_settings (#820's cut) and the guest star through set_guest. */
    act('/api/voice-actor/combos/' + encodeURIComponent(combo.id) + '/apply', {}, busyNode)
      .then(function () {
        emit('combo-applied', {combo: combo});
        refreshCast();
      }, function () { /* the say line carries the refusal */ });
  }

  /* ------------------------------------------------------------- callers */

  function buildCallers(p) {
    p.parts.note = make('p', 'va-note', '');
    p.body.appendChild(p.parts.note);
    /* the armed "call in now" - who is waiting for the next diamond */
    p.parts.armed = make('div', 'va-armed');
    p.parts.armed.hidden = true;
    p.parts.armed.setAttribute('role', 'status');
    p.body.appendChild(p.parts.armed);
    p.parts.rows = make('div', 'va-callers');
    p.body.appendChild(p.parts.rows);

    var create = make('div', 'va-create');
    create.appendChild(make('b', '', 'New caller'));
    var grid = make('div', 'va-create-grid');
    p.parts.newName = guardInput(make('input', 'va-input'));
    p.parts.newName.type = 'text';
    p.parts.newName.placeholder = 'caller name';
    p.parts.newName.setAttribute('aria-label', 'The new caller\'s name');
    grid.appendChild(p.parts.newName);
    p.parts.newVoiceBtn = btn('va-mini', 'Voice: drawn', 'c:waveform',
      'Pick a voice actor for this caller (optional - unset means the rotation draws one)');
    p.parts.newVoice = '';
    p.parts.newVoiceBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      openPicker('voice', {title: 'The new caller\'s voice', current: p.parts.newVoice,
        allowNone: 'Let the rotation draw',
        choose: function (vid) {
          p.parts.newVoice = vid;
          setText(p.parts.newVoiceBtn.querySelector('.va-btn-words'),
            vid ? 'Voice: ' + voiceName(model.voices, vid) : 'Voice: drawn');
        }});
    });
    grid.appendChild(p.parts.newVoiceBtn);
    create.appendChild(grid);
    p.parts.newPersona = guardInput(make('textarea', ''));
    p.parts.newPersona.placeholder = 'persona - who is this? (optional)';
    p.parts.newPersona.setAttribute('aria-label', 'The new caller\'s persona');
    create.appendChild(p.parts.newPersona);
    p.parts.newGoal = guardInput(make('input', 'va-input'));
    p.parts.newGoal.type = 'text';
    p.parts.newGoal.placeholder = 'what do they want? (optional)';
    p.parts.newGoal.setAttribute('aria-label', 'The new caller\'s goal');
    create.appendChild(p.parts.newGoal);
    p.parts.createBtn = btn('', 'Add caller', 'c:add', 'Add this caller to the list');
    p.parts.createBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      createCaller(p);
    });
    create.appendChild(p.parts.createBtn);
    p.body.appendChild(create);
  }

  function summaryCallers() {
    var c = model.callers;
    if (!c) return '';
    var n = (c.callers || []).length;
    return n + ' caller' + (n === 1 ? '' : 's') + (c.per_hour ? ' - ' + c.per_hour + '/hr' : '');
  }

  function paintCallers(p) {
    setText(p.parts.note, model.vaAbsent
      ? 'Dispatch needs the voice-actor store (tools/voice_actor_backend_patch.py). The list below is live.'
      : 'Tap a caller, then dispatch: "Call in now" joins the CURRENT segment\'s tree at its next '
        + 'diamond; "Queue next" plans a full call chapter as soon as the line is free. Either way '
        + 'the call runs on System 3\'s rolls.');
    paintArmed(p);
    var host = p.parts.rows;
    host.replaceChildren();
    var rows = (model.callers && model.callers.callers) || [];
    var nowS = Date.now() / 1000;
    rows.forEach(function (c) {
      var row = make('div', 'va-caller');
      row.setAttribute('role', 'button');
      row.tabIndex = 0;
      setClass(row, 'sel', ui.selectedCaller === c.id);
      var text = make('div', 'va-caller-text');
      text.appendChild(make('b', '', c.name || c.id));
      text.appendChild(make('small', '', [c.persona, c.goal].filter(Boolean).join(' - ') || 'no persona'));
      row.appendChild(text);
      var side = make('div', 'va-caller-side');
      if (c.voice_id) {
        side.appendChild(chip(voiceName(model.voices, c.voice_id), 'mute', 'The caller\'s pinned clone voice'));
      }
      if (c.calls) side.appendChild(chip(c.calls + ' calls', 'mute', 'How often they have rung'));
      var d = lastDispatchFor(c.id);
      if (d) {
        var word = dispatchWord(d, nowS);
        side.appendChild(chip(word, dispatchTone(word), d.why || ('dispatched ' + (d.road || ''))));
      }
      row.appendChild(side);
      var open = function (e) {
        e.stopPropagation();
        ui.selectedCaller = ui.selectedCaller === c.id ? '' : c.id;
        paint();
      };
      row.addEventListener('click', open);
      row.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') open(e);
      });
      host.appendChild(row);
      if (ui.selectedCaller === c.id) host.appendChild(callerDetail(c));
    });
    if (!rows.length) host.appendChild(make('p', 'va-muted', 'The caller list is empty.'));
  }

  function paintArmed(p) {
    var armed = model.va && model.va.interjection;
    var box = p.parts.armed;
    box.replaceChildren();
    setHidden(box, !armed);
    if (!armed) return;
    box.appendChild(iconNode('c:phone--filled'));
    var words = make('div', 'va-armed-words');
    words.appendChild(make('b', '', (armed.caller || 'A caller') + ' is waiting on the line'));
    words.appendChild(make('small', '', 'Call in now: the next diamond System 3 reaches in '
      + (armed.segment ? '"' + armed.segment + '"' : 'this segment') + ' takes the call'
      + (armed.topic ? ' - about ' + armed.topic : '') + '.'));
    box.appendChild(words);
    var cancel = btn('va-mini', 'Call back', 'c:misuse', 'Cancel this dispatch before a diamond takes it');
    cancel.addEventListener('click', function (e) {
      e.stopPropagation();
      cancelDispatch(armed, cancel);
    });
    box.appendChild(cancel);
  }

  function callerDetail(c) {
    var box = make('div', 'va-caller-detail');
    var pbits = [];
    if (c.persona) pbits.push(c.persona);
    if (c.goal) pbits.push('Goal: ' + c.goal);
    if (pbits.length) box.appendChild(make('p', '', pbits.join(' - ')));
    var voiceRow = make('div', 'va-dispatch-row');
    var pickV = btn('va-mini', c.voice_id ? 'Voice: ' + voiceName(model.voices, c.voice_id) : 'Voice: drawn',
      'c:waveform', 'Pin a library clone to this caller');
    pickV.addEventListener('click', function (e) {
      e.stopPropagation();
      openPicker('voice', {title: c.name + '\'s voice', current: c.voice_id || '',
        allowNone: 'Let the rotation draw',
        choose: function (vid) {
          request('PUT', '/api/dj/callers/' + encodeURIComponent(c.id), {voice_id: vid})
            .then(function () { say('Saved ' + c.name + '\'s voice.', ''); refreshCast(); },
              function (err) { say('The station refused that voice: ' + String((err && err.message) || err), 'bad'); });
        }});
    });
    voiceRow.appendChild(pickV);
    var sched = btn('va-mini', 'Set scheduled', 'c:calendar', 'Arm this caller as the Scheduled caller seat');
    sched.disabled = !!model.vaAbsent;
    sched.addEventListener('click', function (e) {
      e.stopPropagation();
      act('/api/voice-actor/scheduled', {caller_id: c.id}, sched).then(refreshVaState, function () {});
    });
    voiceRow.appendChild(sched);
    var pinR = btn('va-mini', 'Pin random', 'c:pin--filled', 'This caller answers the phone clock\'s next ring');
    pinR.disabled = !!model.vaAbsent;
    pinR.addEventListener('click', function (e) {
      e.stopPropagation();
      act('/api/voice-actor/random-pin', {caller_id: c.id}, pinR).then(refreshVaState, function () {});
    });
    voiceRow.appendChild(pinR);
    box.appendChild(voiceRow);

    var topicRow = make('div', 'va-dispatch-row');
    var topic = guardInput(make('input', 'va-input'));
    topic.type = 'text';
    topic.placeholder = 'topic for the call (blank = their own goal)';
    topic.setAttribute('aria-label', 'The dispatched call\'s topic');
    /* a repaint (a poll that brought news) must not cost the typing */
    topic.value = ui.topicDraft[c.id] || '';
    topic.addEventListener('input', function () { ui.topicDraft[c.id] = topic.value; });
    topicRow.appendChild(topic);
    box.appendChild(topicRow);

    var goRow = make('div', 'va-dispatch-row');
    var now = btn('', 'Call in now', 'c:phone--filled',
      'Inject a call-interjection node into the CURRENT segment\'s tree at its next diamond');
    now.disabled = !!model.vaAbsent;
    now.addEventListener('click', function (e) {
      e.stopPropagation();
      dispatchCaller(c, 'now', topic.value, now);
    });
    goRow.appendChild(now);
    var next = btn('', 'Queue next', 'c:hourglass',
      'Plan a full call chapter next in the running order');
    next.disabled = !!model.vaAbsent;
    next.addEventListener('click', function (e) {
      e.stopPropagation();
      dispatchCaller(c, 'next', topic.value, next);
    });
    goRow.appendChild(next);
    box.appendChild(goRow);

    var d = lastDispatchFor(c.id);
    if (d) {
      var word = dispatchWord(d, Date.now() / 1000);
      var last = make('div', 'va-dispatch-row va-dispatch-last');
      last.appendChild(chip(word, dispatchTone(word), d.why || ''));
      last.appendChild(make('span', 'va-muted', 'Last dispatch: ' + roadWord(d.road)
        + (d.why ? ' - ' + d.why : '')));
      if (dispatchOpen(d)) {
        var back = btn('va-mini', 'Call back', 'c:misuse', 'Cancel this dispatch');
        back.addEventListener('click', function (e) {
          e.stopPropagation();
          cancelDispatch(d, back);
        });
        last.appendChild(back);
      }
      box.appendChild(last);
    }
    return box;
  }

  function dispatchCaller(c, road, topic, busyNode) {
    act('/api/voice-actor/dispatch',
      {caller_id: c.id, road: road, topic: String(topic || '').trim()}, busyNode)
      .then(function (ans) {
        /* act() already put the station's own words (ans.say) on the say line */
        if (ans && ans.ok !== false) {
          ui.topicDraft[c.id] = '';
          emit('dispatch', {caller: c, road: road, row: ans.row || null});
        }
        refreshVaState();
      }, function () { /* said already */ });
  }

  function createCaller(p) {
    var name = String(p.parts.newName.value || '').trim();
    if (!name) { say('A caller needs a name.', 'bad'); return; }
    act('/api/dj/callers', {name: name,
      persona: String(p.parts.newPersona.value || '').trim(),
      goal: String(p.parts.newGoal.value || '').trim()}, p.parts.createBtn)
      .then(function (row) {
        var vid = p.parts.newVoice;
        var done = function () {
          p.parts.newName.value = '';
          p.parts.newPersona.value = '';
          p.parts.newGoal.value = '';
          p.parts.newVoice = '';
          setText(p.parts.newVoiceBtn.querySelector('.va-btn-words'), 'Voice: drawn');
          say('Added ' + name + ' to the list.', '');
          refreshCast();
        };
        if (row && row.id && vid) {
          request('PUT', '/api/dj/callers/' + encodeURIComponent(row.id), {voice_id: vid})
            .then(done, function (err) {
              say('Added, but the voice was refused: ' + String((err && err.message) || err), 'bad');
              refreshCast();
            });
        } else done();
      }, function () { /* said already */ });
  }

  /* ------------------------------------------------------------- picker */

  function buildPicker() {
    var layer = make('div', 'va-layer va-picker');
    layer.hidden = true;
    /* role=group, not dialog: the house drag layer raises any tapped
     * [role=dialog] to its own z-index, and a layer with a z of its own would
     * out-rank the popup's BACK probe - BACK must see the popup's z here and
     * ask the probe, which answers this layer first. */
    layer.setAttribute('role', 'group');
    layer.setAttribute('aria-label', 'Pick an actor');
    var head = make('div', 'va-layer-head');
    var title = make('b', '', 'Pick');
    head.appendChild(title);
    var search = guardInput(make('input', 'va-input'));
    search.type = 'search';
    search.placeholder = 'filter...';
    search.setAttribute('aria-label', 'Filter the list');
    search.addEventListener('input', function () { paintPicker(); });
    head.appendChild(search);
    var close = make('button', 'va-close');
    close.type = 'button';
    close.title = 'Back';
    close.setAttribute('aria-label', 'Close the picker');
    close.innerHTML = icon('c:close--filled', '') || 'x';
    close.addEventListener('click', function (e) { e.stopPropagation(); closePicker(); });
    head.appendChild(close);
    layer.appendChild(head);
    var body = make('div', 'va-layer-body');
    var list = make('div', 'va-actors');
    body.appendChild(list);
    layer.appendChild(body);
    ui.picker = layer;
    ui.pickerParts = {title: title, search: search, list: list, mode: '', opts: {}};
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      ui.unwatchers.push(root.PineDismiss.watch(layer, closePicker, [],
        function () { return !layer.hidden; }));
    }
    return layer;
  }

  function openPicker(mode, opts) {
    if (!ui.picker) return;
    ui.pickerParts.mode = mode;
    ui.pickerParts.opts = opts || {};
    ui.pickerParts.search.value = '';
    setText(ui.pickerParts.title, (opts && opts.title) || 'Pick');
    layerPush(ui.picker, closePicker);
    paintPicker(true);
  }

  function closePicker() {
    if (!ui.picker || ui.picker.hidden) return;
    layerDrop(ui.picker);
  }

  function pickerRows() {
    var mode = ui.pickerParts.mode;
    if (mode === 'voice') {
      return (model.voices || []).map(function (v) {
        return {id: v.id, name: v.name || v.id, voice: v,
          sub: (v.kind || 'clone') + (v.airings ? ' - ' + v.airings + ' airings' : ' - never aired')};
      });
    }
    if (mode === 'guest') {
      return ((model.guests && model.guests.guests) || []).map(function (g) {
        return {id: g.id, name: g.name || g.id, guest: g,
          sub: [g.who, g.voice ? 'voice: ' + voiceName(model.voices, g.voice) : 'voice drawn']
            .filter(Boolean).join(' - ')};
      });
    }
    if (mode === 'caller') {
      return ((model.callers && model.callers.callers) || []).map(function (c) {
        return {id: c.id, name: c.name || c.id, caller: c,
          sub: [c.persona, c.voice_id ? 'voice: ' + voiceName(model.voices, c.voice_id) : '']
            .filter(Boolean).join(' - ')};
      });
    }
    return [];
  }

  /* The picker's rows are rebuilt only when what they show changed: a poll
   * that brings nothing new never swaps the row under a finger. */
  function pickerSig() {
    var parts = ui.pickerParts;
    return JSON.stringify([parts.mode, parts.search.value, parts.opts && parts.opts.current,
      parts.mode === 'voice' ? [voicesSig(), model.va && model.va.prefs, model.engines && model.engines.engine,
        model.vaAbsent] : parts.mode === 'guest' ? model.guests
        : (model.callers && model.callers.callers || []).map(function (c) { return [c.id, c.name, c.persona, c.voice_id]; })]);
  }

  function paintPicker(force) {
    if (!ui.picker || ui.picker.hidden) return;
    var parts = ui.pickerParts;
    var sig = pickerSig();
    if (!force && sig === parts.sig) return;
    parts.sig = sig;
    var want = String(parts.search.value || '').toLowerCase();
    var rows = pickerRows().filter(function (r) {
      return !want || (r.name + ' ' + r.sub).toLowerCase().indexOf(want) >= 0;
    });
    var list = parts.list;
    list.replaceChildren();
    var opts = parts.opts;
    if (parts.mode === 'voice') {
      /* the legend first: which chip is which */
      var active = String((model.engines && model.engines.engine) || '').toUpperCase();
      list.appendChild(make('p', 'va-note va-picker-legend',
        'The first badge is the engine each reference was cut for; XTTS | F5 records the actor\'s '
        + 'preferred engine. Everyone speaks through the one active engine'
        + (active ? ' (' + active + ' now)' : '') + '. New actors start from the New actor door.'));
    }
    if (opts.allowNone) {
      list.appendChild(pickerRowNode({id: '', name: opts.allowNone, sub: 'no pinned voice'}, opts));
    }
    rows.forEach(function (r) { list.appendChild(pickerRowNode(r, opts)); });
    if (!rows.length) list.appendChild(make('p', 'va-muted', 'Nothing matches.'));
  }

  function pickerRowNode(r, opts) {
    var row = make('button', 'va-actor');
    row.type = 'button';
    setClass(row, 'current', !!opts.current && r.id === opts.current);
    var text = make('div', 'va-actor-text');
    text.appendChild(make('b', '', r.name));
    text.appendChild(make('small', '', r.sub || ''));
    row.appendChild(text);
    var side = make('div', 'va-actor-side');
    if (r.voice) {
      var active = String((model.engines && model.engines.engine) || '');
      var badge = engineBadgeOf(r.voice, active);
      side.appendChild(chip(badge.word, badge.tone, badge.why));
      side.appendChild(prefControl(r.voice));
    }
    if (r.guest && model.guests && model.guests.active === r.id) {
      side.appendChild(chip('in the studio', 'ok', 'Seated now'));
    }
    row.appendChild(side);
    row.addEventListener('click', function (e) {
      e.stopPropagation();
      if (ui.pickerParts.mode === 'guest') {
        act('/api/dj/guest/activate', {on: true, id: r.id}, row).then(function () {
          closePicker();
          refreshCast();
        });
        return;
      }
      var choose = opts.choose;
      closePicker();
      if (typeof choose === 'function') choose(r.id);
    });
    return row;
  }

  /** The XTTS|F5 preferred-engine control on a picker row. The preference
   *  is RECORDED (the operator's decision); the air always uses the active
   *  engine, so this never touches a seat or a level. */
  function prefControl(voice) {
    var wrap = make('span', 'va-pref');
    wrap.setAttribute('role', 'radiogroup');
    wrap.setAttribute('aria-label', voice.name + '\'s preferred engine');
    var current = prefOf(voice.id);
    ['xtts', 'f5'].forEach(function (id) {
      var b = make('button', '', id.toUpperCase());
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', current === id ? 'true' : 'false');
      b.title = model.vaAbsent
        ? 'Recording a preference needs the voice-actor store (backend tool)'
        : 'Record ' + id.toUpperCase() + ' as ' + voice.name + '\'s preferred engine'
          + (current === id ? ' (tap again to clear)' : '');
      b.disabled = !!model.vaAbsent;
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var next = current === id ? '' : id;
        act('/api/voice-actor/prefs', {voice_id: voice.id, preferred: next}, b)
          .then(function () { refreshVaState().then(paintPicker); });
      });
      wrap.appendChild(b);
    });
    return wrap;
  }

  /* -------------------------------------------------- the extraction door */

  function buildExtract() {
    var layer = make('div', 'va-layer va-extract');
    layer.hidden = true;
    layer.setAttribute('role', 'group');                  /* see buildPicker */
    layer.setAttribute('aria-label', 'New voice actor - the extraction studio');
    var head = make('div', 'va-layer-head');
    head.appendChild(iconNode('c:chemistry'));
    head.appendChild(make('b', '', 'New voice actor'));
    var close = make('button', 'va-close');
    close.type = 'button';
    close.title = 'Back';
    close.setAttribute('aria-label', 'Close the extraction studio');
    close.innerHTML = icon('c:close--filled', '') || 'x';
    close.addEventListener('click', function (e) { e.stopPropagation(); closeExtract(); });
    head.appendChild(close);
    layer.appendChild(head);
    var body = make('div', 'va-layer-body va-extract-body');
    /* THE SIBLING'S GROUND (SHELL_CONTRACT.md): the 3JS tile rail and the
     * extraction mount. This shell only owns the door and the honest
     * empty state - it never invents pipeline facts. */
    var rail = make('div');
    rail.id = 'vaTileRail';
    rail.setAttribute('data-va-slot', 'tile-rail');
    rail.setAttribute('aria-label', 'Extraction tiles');
    body.appendChild(rail);
    var mount = make('div');
    mount.id = 'vaExtractionMount';
    mount.setAttribute('data-va-slot', 'extraction');
    body.appendChild(mount);
    layer.appendChild(body);
    ui.extract = layer;
    ui.extractParts = {mount: mount, rail: rail};
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      ui.unwatchers.push(root.PineDismiss.watch(layer, closeExtract, [],
        function () { return !layer.hidden; }));
    }
    return layer;
  }

  /** The context the extraction module is handed (SHELL_CONTRACT.md). */
  function extractCtx() {
    return {
      request: request,                    /* (method, path, body) -> Promise<json>, keyed, 9 s bound */
      stationUrl: stationUrl,              /* a station path as this page must fetch it */
      icon: icon,                          /* pineIcon('c:...') markup or '' */
      say: say,                            /* (text, 'bad'|'') - the panel's one status line */
      close: closeExtract,                 /* leave the extraction layer (BACK does the same) */
      mount: ui.extractParts.mount,        /* #vaExtractionMount - the module's ground */
      rail: ui.extractParts.rail,          /* #vaTileRail - the 3JS tile rail above it */
      isTablet: isTablet(),                /* coarse pointer / the kiosk: keep the GPU light */
      actors: function () { return (model.voices || []).slice(); },
      engines: function () { return model.engines ? JSON.parse(JSON.stringify(model.engines)) : null; },
      refreshActors: function () { return refreshCast(); },
      /* the module calls this once a harvested voice is in the library:
       * the pickers repaint, and 'pine-voice-actor:actor-created' fires */
      actorCreated: function (voice) {
        emit('actor-created', {voice: voice || null});
        return refreshCast().then(function () { paint(true); });
      },
      /* seat a voice from the extraction flow ("make this the co-host") */
      setSeat: function (seat, vid) { return setSeatVoice(seat, vid); }
    };
  }

  /* [va-strips] The profile strips' context (voice-actor-strips.js). */
  function stripCtx() {
    return {
      request: request,                    /* (method, path, body, ms?) -> Promise<json> */
      stationUrl: stationUrl,
      icon: icon,
      say: say,
      isTablet: isTablet(),
      actors: function () { return (model.voices || []).slice(); },
      engines: function () { return model.engines ? JSON.parse(JSON.stringify(model.engines)) : null; },
      callers: function () { return ((model.callers && model.callers.callers) || []).slice(); },
      /* the cast's own road: POST /api/voice-actor/seat (#820's cut included) */
      setSeat: function (seat, vid) { return setSeatVoice(seat, vid); },
      /* the Callers card's own road: the caller's pinned clone */
      setCallerVoice: function (cid, vid) {
        return request('PUT', '/api/dj/callers/' + encodeURIComponent(cid), {voice_id: String(vid || '')})
          .then(function (ans) { refreshCast(); return ans; });
      },
      pop: function () { return ui.pop || null; }
    };
  }

  /** The profile strips module's one registration door: def.seat(el, row, ctx). */
  function registerStrips(def) {
    if (!def || typeof def.seat !== 'function') return false;
    ui.stripDef = def;
    if (ui.visible) paint(true);
    return true;
  }

  function isTablet() {
    try {
      if (root.__pineViewsBooted) return true;             /* the kiosk's bundle */
      return !!(root.matchMedia && root.matchMedia('(pointer: coarse)').matches);
    } catch (err) { return false; }
  }

  function paintExtractEmpty() {
    var mount = ui.extractParts.mount;
    mount.replaceChildren();
    var empty = make('div', 'va-extract-empty');
    empty.appendChild(iconNode('c:chemistry'));
    empty.appendChild(make('b', '', 'The extraction studio mounts here'));
    empty.appendChild(make('p', '',
      'Its module registers with PineVoiceActor.registerExtraction(...) '
      + '(see SHELL_CONTRACT.md) and has not loaded on this screen. '
      + 'Captured actors land in the voice store and appear in every picker here.'));
    mount.appendChild(empty);
  }

  function mountExtract() {
    var def = ui.extractDef;
    if (!def || ui.extractMounted) { if (!def) paintExtractEmpty(); return; }
    try {
      ui.extractParts.mount.replaceChildren();
      def.mount(ui.extractParts.mount, extractCtx());
      if (typeof def.tile === 'function') def.tile(ui.extractParts.rail, extractCtx());
      ui.extractMounted = true;
    } catch (err) {
      if (root.console) root.console.error('[voice-actor] extraction mount failed:', err);
      paintExtractEmpty();
    }
  }

  function openExtract() {
    buildPopup();
    if (!ui.visible) openPopup();
    if (!ui.extract.hidden) return;
    layerPush(ui.extract, closeExtract);
    mountExtract();
    emit('extract-open', {});
  }

  function closeExtract() {
    if (!ui.extract || ui.extract.hidden) return;
    var def = ui.extractDef;
    if (def && ui.extractMounted && typeof def.unmount === 'function') {
      try { def.unmount(); } catch (err) { /* its mess, not the panel's */ }
    }
    ui.extractMounted = false;
    layerDrop(ui.extract);
    emit('extract-close', {});
  }

  /** The sibling extraction module's one registration door. */
  function registerExtraction(def) {
    if (!def || typeof def.mount !== 'function') return false;
    if (ui.extractDef && ui.extractMounted && typeof ui.extractDef.unmount === 'function') {
      try { ui.extractDef.unmount(); } catch (err) { /* replaced anyway */ }
      ui.extractMounted = false;
    }
    ui.extractDef = def;
    if (ui.extract && !ui.extract.hidden) mountExtract();
    return true;
  }

  /* ================================================== start */

  function start() {
    if (ui.started) return;
    ui.started = true;
    var go = function () { watchForBar(); };
    if (document.body) go();
    else document.addEventListener('DOMContentLoaded', go, {once: true});
  }

  var api = {
    start: start, open: openPopup, close: closePopup, toggle: toggleOpen,
    isOpen: function () { return ui.visible; },
    /* the open layer stack, topmost last (BACK answers the last one) */
    layers: function () { return ui.layers.map(function (l) { return String(l.node.className || ''); }); },
    openExtraction: openExtract,
    registerExtraction: registerExtraction,
    registerStrips: registerStrips,         /* [va-strips] */
    actors: function () { return model.voices || []; },
    refresh: refreshAll,
    /* pure helpers, for the tests */
    voiceName: voiceName, engineBadgeOf: engineBadgeOf, seatModel: seatModel,
    comboSummary: comboSummary, dispatchWord: dispatchWord, dispatchTone: dispatchTone,
    dispatchOpen: dispatchOpen, roadWord: roadWord,
    rotationLine: rotationLine, readPanels: readPanels, writePanels: writePanels,
    stationUrl: stationUrl, PANEL_ORDER: PANEL_ORDER, DEFAULT_OPEN: DEFAULT_OPEN,
    PANELS_KEY: PANELS_KEY, SEAT_KEYS: SEAT_KEYS
  };
  root.PineVoiceActor = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document !== 'undefined' && document && typeof document.createElement === 'function') start();
})(typeof window !== 'undefined' ? window : globalThis);
