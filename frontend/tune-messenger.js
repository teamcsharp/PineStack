/* [tune-messenger] The on-air message, on the public listener page.
 *
 * "remove the current messenger on the tailscale page, and show the one I
 *  use on the pinepip. It is more accessible. It only shows the message
 *  being spoken or clip being played actively and doesn't show history.
 *  It is a widget" (operator, 2026-10-07)
 *
 * Earlier this page ran System 3's full scrollback Messenger (the desk's
 * own `mountEmbedded`, a feed of every round) behind a Messenger/Feed
 * switch, the plain feed one tap away. Both are gone now. In their place:
 * the SAME single-message tile Pine PiP floats over the station window -
 * frontend/system3-message-tile.js, served here unmodified as
 * /tune-messenger/system3-message-tile.js (+ .css) - showing one card for
 * whatever line is on the air right now, with its recorded ES/RS/SFX/
 * SFXGUY rolls, and nothing behind it to scroll through.
 *
 * The tile's own adapters are thin:
 *   load(row)   turnEvents() + PineSystem3MessageTile.decisionRows(), read
 *               straight out of the snapshot this page already holds - no
 *               extra round fetch, the snapshot's convs already carry
 *               decision_events (that is how the old Messenger drew its
 *               tiles too).
 *   clock()     earNow(), below - the station's clock as THIS ear hears it.
 *   receive()   fed every tick with the line currently sounding; the tile
 *               decides for itself whether that is new.
 *
 * Which line is sounding, the words it is allowed to show yet, and the
 * lag this ear is running behind the station: unchanged from before, see
 * sounding() / wordsHeld() / earNow() below - a car on the stream is
 * 20-45 s behind the house, and this page must never show a word (or a
 * roll) this listener has not heard yet.
 *
 * The page's own globals are read the way car-diag.js reads them: an
 * indirect eval of the name, so this file needs nothing from the page but
 * its #patter box (hidden here - the old feed never comes back). Deferred
 * and last: if this fails, the page is exactly as it was before this
 * file existed. */
(function () {
  'use strict';
  if (window.PineTuneMessenger) return;

  var VERSION = '2';
  var TILE_JS = '/tune-messenger/system3-message-tile.js?v=' + VERSION;
  var TILE_CSS = '/tune-messenger/system3-message-tile.css?v=' + VERSION;
  var ROAD = '/api/system3/public/messenger';
  var POLL_GAP = 3500;       /* the network is asked at most this often */
  var KICK_GAP = 2000;       /* a sounding line nobody knows yet may ask sooner, this often */
  var TEXT_WAIT = 8000;      /* a line waits this long for its words before the air moves anyway */
  var GRACE_MS = 6000;       /* a clip's words reach this page this long before this ear does */
  var TICK_MS = 250;
  var KEEP_ROUNDS = 24;

  function pageVar(name) {
    try { return (0, eval)(name); } catch (e) { return undefined; }
  }
  function $(id) { try { return document.getElementById(id); } catch (e) { return null; } }
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /* ---- the one road -------------------------------------------------------- */
  function ownGet(path) {
    var key = pageVar('KEY');
    var guest = pageVar('GUEST');
    var url = path;
    var opts = {};
    if (guest !== false && typeof key === 'string' && key) {
      url += (path.indexOf('?') >= 0 ? '&' : '?') + 't=' + encodeURIComponent(key);
    } else if (typeof key === 'string' && key) {
      opts.headers = {Authorization: 'Bearer ' + key};
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(data.detail || 'Request failed');
        return data;
      });
    });
  }
  function ask(path) {
    var api = window.api;
    return typeof api === 'function' ? api(path) : ownGet(path);
  }

  var snap = {
    convs: new Map(),        /* cid -> {rev, conv, meta} */
    order: [],               /* cids, as the door listed them */
    lines: new Map(),        /* line id -> {cid, turn, who, on, len, spoken} */
    cursor: 1, fetchedAt: 0, inflight: null, off: false, errors: 0,
    skew: 0, samples: []
  };

  function shape(conv) {
    (conv.decision_events || []).forEach(function (ev) {
      (ev.stages || []).forEach(function (st) {
        (st.candidates || []).forEach(function (c) { if (c.weight == null) c.weight = c.p; });
      });
    });
    if (!conv.subject) conv.subject = {};
    return conv;
  }

  function reindex() {
    var lines = new Map();
    snap.convs.forEach(function (held, cid) {
      var air = held.conv.public_air || {};
      (held.conv.lines || []).forEach(function (l) {
        var a = air[l.line_id] || {};
        var who = String(l.who || '');
        lines.set(String(l.line_id), {cid: cid, turn: String(l.turn_id || ''), who: who,
          on: Number(a.on) || 0, len: Number(a.seconds) || 0,
          spoken: !!l.turn_id && who !== 'board' && who !== 'drop'});
      });
    });
    snap.lines = lines;
  }

  function merge(got, t0, t1) {
    if (!got || typeof got !== 'object') return;
    snap.off = !!got.off;
    var sm = Number(got.server_ms);
    if (isFinite(sm) && sm > 0) {
      snap.samples.push({rtt: t1 - t0, skew: sm - (t0 + t1) / 2});
      if (snap.samples.length > 8) snap.samples.shift();
      var best = snap.samples.reduce(function (a, b) { return b.rtt < a.rtt ? b : a; });
      snap.skew = best.skew;
    }
    var convs = got.convs || {};
    var next = [];
    (Array.isArray(got.order) ? got.order : []).forEach(function (o) {
      var cid = String((o && o.conversation_id) || '');
      var part = cid ? convs[cid] : null;
      if (!part) return;
      var rev = String(part.rev || '');
      if (part.conv) snap.convs.set(cid, {rev: rev, conv: shape(part.conv), meta: o});
      else {
        var held = snap.convs.get(cid);
        if (!held || held.rev !== rev) return;      /* a stub for a round this page never held */
        held.meta = o;
      }
      next.push(cid);
    });
    snap.order = next;
    if (snap.convs.size > KEEP_ROUNDS) {
      Array.from(snap.convs.keys()).filter(function (cid) { return next.indexOf(cid) < 0; })
        .slice(0, snap.convs.size - KEEP_ROUNDS)
        .forEach(function (cid) { snap.convs.delete(cid); });
    }
    reindex();
  }

  function fetchSnap(force) {
    if (snap.inflight) return snap.inflight;
    var gap = Date.now() - snap.fetchedAt;
    if (snap.fetchedAt && gap < (force ? KICK_GAP : POLL_GAP)) return Promise.resolve(false);
    var have = [];
    snap.order.forEach(function (cid) {
      var held = snap.convs.get(cid);
      if (held && held.rev) have.push(cid + ':' + held.rev);
    });
    var path = ROAD + (have.length ? '?have=' + encodeURIComponent(have.join(',')) : '');
    var t0 = Date.now();
    snap.inflight = ask(path).then(function (got) {
      merge(got, t0, Date.now());
      snap.errors = 0;
      return true;
    }, function () {
      snap.errors += 1;
      return false;
    }).then(function (ok) {
      snap.inflight = null;
      snap.fetchedAt = Date.now();
      return ok;
    });
    return snap.inflight;
  }

  /* ---- this ear ------------------------------------------------------------ */
  function lagSeconds() {
    if (pageVar('playing') !== true || pageVar('streamMode') !== true) return 0;
    if (typeof window.tvLagSeconds !== 'function') return 0;
    try { return Number(window.tvLagSeconds()) || 0; } catch (e) { return 0; }
  }
  function earNow() { return Date.now() + (snap.skew || 0) - lagSeconds() * 1000; }

  /* The round as this ear may see it: a clip it has not reached (less the
     grace) keeps its words back. Cached per revision and mask, so an
     unchanged round is the same object. */
  function viewOf(cid) {
    var held = snap.convs.get(cid);
    if (!held) return null;
    var conv = held.conv;
    var air = conv.public_air || {};
    var edge = earNow() + GRACE_MS;
    var hide = [];
    (conv.lines || []).forEach(function (l) {
      var a = air[l.line_id];
      if (a && l.who !== 'board' && Number(a.clip_on || a.on) > edge) hide.push(String(l.line_id));
    });
    var key = held.rev + '|' + hide.join(',');
    if (held.viewKey === key && held.view) return held.view;
    var shown = conv;
    if (hide.length) {
      var gone = new Set(hide);
      var lines = (conv.lines || []).map(function (l) {
        if (!gone.has(String(l.line_id)) || l.text == null) return l;
        var c = Object.assign({}, l);
        delete c.text;
        return c;
      });
      var receipts = {};
      Object.keys(air).forEach(function (k) { if (!gone.has(k)) receipts[k] = air[k]; });
      shown = Object.assign({}, conv, {lines: lines, public_air: receipts});
    }
    held.viewKey = key;
    held.view = shown;
    return shown;
  }

  /* The ES/RS/SFX/SFXGUY events recorded for one turn - the same filter
     frontend/system3.js's own turnEvents() uses to feed this same tile
     engine on the desk. */
  function turnEvents(conv, turn) {
    var ids = new Set();
    (turn.decisions || []).forEach(function (d) { ids.add(d.event_id); });
    (turn.speakerbox || []).forEach(function (s) { ids.add(s.event_id); });
    if (turn.sfx) ids.add(turn.sfx.event_id);
    if (turn.sfxguy && turn.sfxguy.event_id) ids.add(turn.sfxguy.event_id);
    return (conv.decision_events || []).filter(function (e) { return ids.has(e.event_id); });
  }

  function loadTile(row) {
    var hit = snap.lines.get(String(row.id));
    if (!hit) { fetchSnap(true); return {answered: false}; }
    var conv = viewOf(hit.cid);
    if (!conv) { fetchSnap(true); return {answered: false}; }
    var turn = (conv.turns || []).find(function (t) { return String(t.turn_id) === hit.turn; });
    if (!turn) return {rows: [], answered: true};
    return {rows: window.PineSystem3MessageTile.decisionRows(turnEvents(conv, turn)), answered: true};
  }

  /* A sounding line nobody on this page knows yet: the door is asked
     sooner, twice at most. */
  var kicks = new Map();
  function kick(lid) {
    var k = kicks.get(lid) || {n: 0, at: 0};
    if (k.n >= 2 || Date.now() - k.at < KICK_GAP) return;
    kicks.set(lid, {n: k.n + 1, at: Date.now()});
    if (kicks.size > 300) kicks.clear();
    fetchSnap(true);
  }

  /* The sounding line's own words are in the round this page holds. */
  var waitFor = {line: '', since: 0, last: 0};
  function wordsHeld(lid, hit) {
    var conv = viewOf(hit.cid);
    var l = conv && (conv.lines || []).find(function (x) { return String(x.line_id) === lid; });
    if (l && l.text) { waitFor.line = ''; return true; }
    var now = Date.now();
    if (!waitFor.line || now - waitFor.last > 1500) waitFor = {line: lid, since: now, last: now};
    waitFor.line = lid;
    waitFor.last = now;
    if (now - waitFor.since > TEXT_WAIT) return true;
    fetchSnap(true);
    return false;
  }

  /* ---- the line this page is sounding -------------------------------------- */
  function sounding() {
    var playing = pageVar('playing') === true;
    var stream = pageVar('streamMode') === true;
    if (playing && !stream) {
      var clip = pageVar('voiceCurrentClip');
      var el = pageVar('voice');
      if (!clip || !el || el.paused || !el.src) return null;
      var t = Number(el.currentTime) || 0;
      var rows = clip.stream && Array.isArray(clip.stream.rows) ? clip.stream.rows : null;
      if (rows && rows.length) {
        for (var i = 0; i < rows.length; i += 1) {
          var r = rows[i] || {};
          var a = Number(r.from), b = Number(r.until);
          if (isFinite(a) && isFinite(b) && b > a && t >= a && t < b) {
            return {line: String(r.id || r.line_id || ''), at: t - a, total: b - a};
          }
        }
        return null;
      }
      var id = String(clip.row_id || '');
      if (!id) return null;
      var d = isFinite(el.duration) && el.duration > 0 ? el.duration : Number(clip.seconds) || 0;
      return {line: id, at: t, total: d};
    }
    var now = earNow();
    var best = null;
    snap.lines.forEach(function (x, lid) {
      if (!x.on || !(x.len > 0)) return;
      if (now >= x.on && now < x.on + x.len * 1000 && (!best || x.on > best.on)) best = {line: lid, on: x.on, len: x.len};
    });
    return best ? {line: best.line, at: (now - best.on) / 1000, total: best.len} : null;
  }

  /* ---- the page ---------------------------------------------------------------- */
  var ui = null, tile = null, mounting = null;
  var earLag = 0;
  var trail = [];
  function note(what) {
    if (trail.length && trail[trail.length - 1].what === what) { trail[trail.length - 1].n += 1; return; }
    trail.push({at: Math.round(performance.now()), what: what, n: 1});
    if (trail.length > 40) trail.shift();
  }

  function style() {
    if ($('tuneS3Style')) return;
    var s = make('style');
    s.id = 'tuneS3Style';
    s.textContent = [
      '.tune-s3-tile{margin:14px 0 6px;--pip-message-max-height:46vh}',
      '.tune-s3-tile .pip-system3-message{font-size:13px}',
      /* the driving layout hides every considered tap, and this with them */
      'body.car .tune-s3-tile{display:none!important}'
    ].join('\n');
    document.head.appendChild(s);
  }

  function build() {
    var patter = $('patter');
    if (!patter || !patter.parentNode) return false;
    patter.hidden = true;             /* the old plain feed never comes back */
    style();
    var host = make('section', 'tune-s3-tile');
    host.setAttribute('aria-label', 'What is on the air right now');
    patter.parentNode.insertBefore(host, patter);
    ui = {patter: patter, host: host};
    return true;
  }

  function onScreen() {
    return !!ui && !document.hidden && ui.host.getClientRects().length > 0;
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (window.PineSystem3MessageTile) { resolve(); return; }
      var el = make('script');
      el.src = src;
      el.onload = function () { resolve(); };
      el.onerror = function () { reject(new Error('could not load ' + src)); };
      document.head.appendChild(el);
    });
  }

  function mount() {
    if (tile) return Promise.resolve(tile);
    if (mounting) return mounting;
    if (!ui) return Promise.resolve(null);
    if (!document.getElementById('tuneS3TileCss')) {
      var css = make('link');
      css.id = 'tuneS3TileCss';
      css.rel = 'stylesheet';
      css.href = TILE_CSS;
      document.head.appendChild(css);
    }
    mounting = loadScript(TILE_JS).then(function () {
      tile = window.PineSystem3MessageTile.mount(ui.host, {
        load: function (row) { return loadTile(row); },
        clock: function () { return earNow(); }
      });
      mounting = null;
      return tile;
    }, function (err) {
      mounting = null;
      note('tile failed: ' + String((err && err.message) || err));
      return null;
    });
    return mounting;
  }

  /* THE EAR MOVED BACK IN TIME. Tuning in to the car stream puts this ear
     20-45 s behind the station the tile was following; rather than let it
     show a line "newer" than what is actually audible now, start clean. */
  function earMoved() {
    var lag = lagSeconds();
    if (lag - earLag > 8) {
      earLag = lag;
      note('ear moved back ' + Math.round(lag) + ' s');
      try { tile.dispose(); } catch (e) { /* already gone */ }
      tile = null;
      waitFor = {line: '', since: 0, last: 0};
      mount();
      return true;
    }
    if (lag < earLag) earLag = lag;
    return false;
  }

  function tick() {
    if (!ui) return;
    if (!tile) { if (!mounting && onScreen()) mount(); return; }
    if (!onScreen()) { note(document.hidden ? 'page hidden' : 'off screen'); return; }
    if (earMoved()) return;
    var s = null;
    try { s = sounding(); } catch (e) { s = null; }
    if (!s || !s.line) { note('silent'); return; }
    var hit = snap.lines.get(s.line);
    var tag = s.line.slice(-6);
    if (!hit) { note('unknown ' + tag); kick(s.line); return; }
    if (hit.spoken && !wordsHeld(s.line, hit)) { note('words? ' + tag); return; }
    var conv = viewOf(hit.cid);
    var line = conv && (conv.lines || []).find(function (l) { return String(l.line_id) === s.line; });
    var row = {id: s.line, cid: hit.cid, tid: hit.turn, text: String((line && line.text) || ''),
      from: 0, until: s.total || 0, music: hit.who === 'board' || hit.who === 'drop'};
    var at = earNow() / 1000 - s.at;
    try {
      tile.receive({now: row, rows: [row],
        station: {stream_now: {at: at, rows: [{id: s.line, from: 0, until: s.total || 0}]}}});
    } catch (e) { note('receive threw ' + (e && e.message)); return; }
    note('air ' + tag);
  }

  function start() {
    if (ui || !build()) return;
    setInterval(function () { try { tick(); } catch (e) { /* the page goes on */ } }, TICK_MS);
    document.addEventListener('visibilitychange', function () { try { tick(); } catch (e) { /* later */ } });
  }

  window.PineTuneMessenger = {
    version: VERSION,
    showing: function () { return onScreen(); },
    sounding: function () { try { return sounding(); } catch (e) { return null; } },
    tile: function () { return tile; },
    state: function () {
      return {waitFor: waitFor.line, waitingMs: waitFor.line ? Date.now() - waitFor.since : 0,
        trail: trail.slice(-12).map(function (x) { return x.what + (x.n > 1 ? ' x' + x.n : ''); }),
        tileState: tile ? tile.state() : null};
    },
    snapshot: function () {
      return {order: snap.order.slice(), rounds: snap.convs.size, lines: snap.lines.size, skew: snap.skew,
        fetchedAt: snap.fetchedAt, errors: snap.errors, off: snap.off};
    }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
