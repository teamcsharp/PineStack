/* [tune-messenger] System 3's Messenger on the public listener page.
 *
 * "on the tailscale radio station, I want the conversation feed animation
 *  like we have the messenger tab. It is showing progress. I want users on
 *  the tailscale using the same version with the most current line
 *  assembling the same way" (operator, 2026-09-28)
 *
 * The desk's own Messenger - frontend/system3.js mountEmbedded, served to the
 * listener door as /tune-messenger/system3.js - mounted in place of the tune
 * page's feed (a switch keeps the old feed one tap away), and driven by THIS
 * page's playhead exactly as the desk's Script tab drives it from its own:
 *
 *   view.live(lineId)              the line this page is sounding
 *   view.clock(lineId, at, total)  where that line has got to, in its window
 *
 * The Messenger asks its usual station paths. request() below answers every
 * one of them out of ONE snapshot polled from the listener door,
 * GET /api/system3/public/messenger (tune_messenger.py): at most one small
 * request every few seconds, and only while the Messenger is on screen - the
 * rounds this page already holds come back as a revision stub. It never
 * writes, and a path it does not know is refused here, not asked.
 *
 * Which line is sounding:
 *   "Live with the house"   the voice element's clip - the row of a welded
 *                           round whose [from, until) holds currentTime, or
 *                           the one line - the desk's s3Clock, line for line;
 *   "Car stream" / not      each published line's own on-air moment (the
 *   tuned in                snapshot's public_air: on, seconds), held back by
 *                           this ear's lag (tvLagSeconds, the model the
 *                           picture already rides) - no lag when this page is
 *                           not playing, so the Messenger follows the station.
 *
 * Words: the door releases a clip's words as the clip reaches the
 * station's air, one message per run of lines inside one clip. This page
 * then holds back, for its OWN ear, the words and the receipts of any clip
 * this ear has not reached (a car on the stream is 20-45 s behind the
 * station), releasing them GRACE_MS before it does - so the Messenger never
 * draws a word this listener has not heard, even on its first paint before
 * the air is known. A line that starts sounding before its words are in the
 * Messenger's copy waits for them (at most TEXT_WAIT - the air is never held
 * for ever), so the reveal types the real words in step with the audio.
 *
 * The page's own globals are read the way car-diag.js reads them: an
 * indirect eval of the name, so this file needs nothing from the page but
 * its #patter box. Deferred and last: if this fails, the page and its old
 * feed are exactly as they were. */
(function () {
  'use strict';
  if (window.PineTuneMessenger) return;

  var VERSION = '1';
  var S3_JS = '/tune-messenger/system3.js?v=' + VERSION;
  var S3_CSS = '/tune-messenger/system3.css?v=' + VERSION;
  var ROAD = '/api/system3/public/messenger';
  var POLL_GAP = 3500;       /* the Messenger asks every 2.5 s; the network is asked at most this often */
  var KICK_GAP = 2000;       /* a sounding line nobody knows yet may ask sooner, this often */
  var TEXT_WAIT = 8000;      /* a line waits this long for its words before the air moves anyway */
  var GRACE_MS = 6000;       /* a clip's words reach the Messenger this long before this ear does */
  var TICK_MS = 250;
  var KEEP_ROUNDS = 24;
  var MODE_KEY = 'pbfm.feedMode';

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
    /* the page's api() does this (token, deadline, shared flight); this is
       only for a page without one */
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
    told: new Map(),         /* cid -> the view (revision + what this ear has reached) it was told about */
    served: new Map(),       /* cid -> the round object the Messenger last took */
    cursor: 1, fetchedAt: 0, inflight: null, off: false, errors: 0,
    skew: 0, samples: []
  };

  function shape(conv) {
    /* the door sends each candidate's share of the wheel once; the roulette
       strips read it as the slice's weight */
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
      /* the server's clock against this one: the sample with the shortest
         round trip is the truest (transit only ever widens it) */
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
    /* rounds that left the door stay a while: the Messenger may ask again */
    if (snap.convs.size > KEEP_ROUNDS) {
      Array.from(snap.convs.keys()).filter(function (cid) { return next.indexOf(cid) < 0; })
        .slice(0, snap.convs.size - KEEP_ROUNDS)
        .forEach(function (cid) { snap.convs.delete(cid); snap.served.delete(cid); snap.told.delete(cid); });
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
  /* the station's clock as this ear hears it: the car stream plays the
     station's air lag seconds late; the house road and a page not tuned in
     are on the station's own time */
  function earNow() { return Date.now() + (snap.skew || 0) - lagSeconds() * 1000; }

  /* The round as this ear may see it: a clip it has not reached (less the
     grace) keeps its words and its receipts back. Cached per revision and
     mask, so an unchanged round is the same object. */
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
      var quiet = new Set();
      var lines = (conv.lines || []).map(function (l) {
        if (!gone.has(String(l.line_id))) return l;
        if (l.turn_id) quiet.add(String(l.turn_id));
        if (l.text == null) return l;
        var c = Object.assign({}, l);
        delete c.text;
        return c;
      });
      var turns = (conv.turns || []).map(function (t) {
        if (!quiet.has(String(t.turn_id)) || t.text == null) return t;
        var c = Object.assign({}, t);
        delete c.text;
        return c;
      });
      var receipts = {};
      Object.keys(air).forEach(function (k) { if (!gone.has(k)) receipts[k] = air[k]; });
      shown = Object.assign({}, conv, {lines: lines, turns: turns, public_air: receipts});
    }
    held.viewKey = key;
    held.view = shown;
    return shown;
  }

  /* ---- what the Messenger asks, answered here -------------------------------- */
  function events(q) {
    return fetchSnap(false).then(function () {
      if (!Number(q.get('after') || 0)) return {events: [], cursor: snap.cursor, head: snap.cursor};
      var out = [];
      snap.order.forEach(function (cid) {
        var held = snap.convs.get(cid);
        if (!held) return;
        viewOf(cid);
        var was = snap.told.get(cid);
        if (was === held.viewKey) return;
        snap.cursor += 1;
        /* a round new to this page is a decision (the Messenger adds it,
           message by message); news on one it holds - the door's, or this
           ear reaching a clip - is an observation */
        out.push({conversation_id: cid, kind: was === undefined ? 'decision' : 'observation', cursor: snap.cursor});
        snap.told.set(cid, held.viewKey);
      });
      return {events: out, cursor: snap.cursor, head: snap.cursor};
    });
  }

  function rounds() {
    return (snap.fetchedAt ? Promise.resolve(true) : fetchSnap(true)).then(function () {
      var rows = snap.order.map(function (cid) {
        var held = snap.convs.get(cid);
        var meta = held.meta || {};
        viewOf(cid);
        snap.told.set(cid, held.viewKey);
        return {conversation_id: cid, mode: 'active', road: meta.road || '', status: meta.status || '',
          created: Number(meta.created || held.conv.created || 0)};
      });
      rows.sort(function (a, b) { return b.created - a.created; });
      return {conversations: rows};
    });
  }

  function round(cid) {
    var held = snap.convs.get(cid);
    var got = held ? Promise.resolve(held) : fetchSnap(true).then(function () { return snap.convs.get(cid); });
    return got.then(function (h) {
      if (!h) throw new Error('that round is not on the listener door');
      var shown = viewOf(cid);
      snap.told.set(cid, h.viewKey);
      snap.served.set(cid, shown);
      return shown;
    });
  }

  function inspect(block) {
    var lines = [];
    snap.convs.forEach(function (held, cid) {
      var shown = viewOf(cid);
      var air = shown.public_air || {};
      (shown.lines || []).forEach(function (l) {
        if (Number(l.block) === block && air[l.line_id]) lines.push(air[l.line_id]);
      });
    });
    return {block: block, lines: lines};
  }

  function lineOf(lid) {
    var hit = snap.lines.get(lid);
    var got = hit ? Promise.resolve(hit) : fetchSnap(true).then(function () { return snap.lines.get(lid); });
    return got.then(function (h) {
      if (!h) throw new Error('that line is not on the listener door');
      var conv = viewOf(h.cid);
      var turn = (conv.turns || []).find(function (t) { return t.turn_id === h.turn; }) || null;
      return {line: {line_id: lid, conversation_id: h.cid, turn_id: h.turn || null}, turn: turn,
        conversation: {conversation_id: h.cid}};
    });
  }

  function request(path, options) {
    var method = String((options && options.method) || 'GET').toUpperCase();
    if (method !== 'GET') return Promise.reject(new Error('the listener page only reads'));
    var u;
    try { u = new URL(path, location.href); } catch (e) { return Promise.reject(e); }
    var p = u.pathname, q = u.searchParams;
    if (p === '/api/system3/events') return events(q);
    if (p === '/api/system3/conversations') return rounds();
    var m = /^\/api\/system3\/conversation\/([^/]+)$/.exec(p);
    if (m) return round(decodeURIComponent(m[1]));
    if (p === '/api/segment/inspect') return Promise.resolve(inspect(Number(q.get('block') || 0)));
    if (p === '/api/system3/line') return lineOf(String(q.get('line_id') || ''));
    /* settings, dials, the cut panel, the speaker box, prompt history, a
       clip's replay source: operator roads, not on the listener door */
    return Promise.reject(new Error('not on the listener door'));
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
  var ui = null, view = null, mounting = null, mode = 'messenger';
  var lastClock = '', showPending = false;
  var waitFor = {line: '', since: 0, last: 0};
  var kicks = new Map();
  var earLag = 0;                 /* the lag the Messenger's air was built against */
  var trail = [];                 /* the last decisions, for PineTuneMessenger.state() */
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
      '.tune-feed-switch{display:flex;gap:6px;margin:14px 0 6px}',
      '.tune-feed-switch button{padding:6px 14px;font-size:13px;border-radius:999px}',
      '.tune-feed-switch button[aria-pressed="true"]{background:#16324a;border-color:#4bb3ff;color:#e6edf5}',
      '.tune-s3{display:flex;flex-direction:column;height:min(66vh,600px);min-height:300px;border:1px solid #1b2735;',
      'border-radius:14px;background:#0f171b;overflow:hidden}',
      '.tune-s3[hidden]{display:none}',
      '.tune-s3-bar{display:flex;align-items:center;gap:8px;min-width:0;padding:7px 10px;background:#0b111b;',
      'border-bottom:1px solid #1b2735;font-size:12px;color:#9fb0c4}',
      '.tune-s3-bar>b{flex:none;font-size:13px;color:#dce8f5;display:inline-flex;align-items:center;gap:6px}',
      '.tune-s3-bar>b::before{content:"";width:7px;height:7px;border-radius:50%;background:#90dab9;box-shadow:0 0 6px #90dab9}',
      '.tune-s3-air{flex:none}',
      '.tune-s3-facts{flex:1 1 auto;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}',
      '.tune-s3-facts .s3-embed-facts{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.tune-s3>.tune-s3-body.s3.s3-embed{flex:1 1 auto;height:auto;min-height:0;margin:0;overflow:auto;',
      '-webkit-overflow-scrolling:touch;overscroll-behavior:contain}',
      '.tune-s3-say{margin:14px;color:#9fb0c4;font-size:13px}',
      '.tune-s3-say button{margin:8px 8px 0 0;padding:6px 12px;font-size:13px}',
      /* the page's own #1472 feed styles share four class names with System 3;
         inside the Messenger, System 3's own rules stand */
      '.tune-s3 .s3-card{cursor:auto;font-size:inherit;color:inherit;margin:0}',
      '.tune-s3 .s3-drum{-webkit-mask-image:linear-gradient(transparent,#000 30%,#000 70%,transparent)}',
      /* the driving layout hides every considered tap, and this with them */
      'body.car .tune-s3,body.car .tune-feed-switch{display:none!important}'
    ].join('\n');
    document.head.appendChild(s);
  }

  function build() {
    var patter = $('patter');
    if (!patter || !patter.parentNode) return false;
    style();
    var sw = make('div', 'tune-feed-switch');
    sw.setAttribute('role', 'group');
    sw.setAttribute('aria-label', 'How the conversation is shown');
    var bMsg = make('button', '', 'Messenger');
    var bFeed = make('button', '', 'Feed');
    [bMsg, bFeed].forEach(function (b) { b.type = 'button'; });
    bMsg.title = 'The conversation as it is assembled: each line rolls its dice, then its words arrive with the audio';
    bFeed.title = 'The plain feed of what was said';
    bMsg.addEventListener('click', function () { setMode('messenger', true); });
    bFeed.addEventListener('click', function () { setMode('feed', true); });
    sw.appendChild(bMsg);
    sw.appendChild(bFeed);
    var host = make('section', 'tune-s3');
    host.setAttribute('aria-label', 'The conversation, message by message');
    var bar = make('div', 'tune-s3-bar');
    var air = make('span', 'tune-s3-air');
    var facts = make('span', 'tune-s3-facts');
    bar.appendChild(make('b', '', 'Messenger'));
    bar.appendChild(air);
    bar.appendChild(facts);
    var body = make('div', 'tune-s3-body');
    var sink = make('span', 'tune-s3-sink');
    sink.hidden = true;           /* the operator's buttons: not on the listener page */
    host.appendChild(bar);
    host.appendChild(body);
    host.appendChild(sink);
    patter.parentNode.insertBefore(sw, patter);
    patter.parentNode.insertBefore(host, patter);
    ui = {patter: patter, sw: sw, bMsg: bMsg, bFeed: bFeed, host: host, air: air, facts: facts, body: body, sink: sink};
    var saved = '';
    try { saved = String(localStorage.getItem(MODE_KEY) || ''); } catch (e) { saved = ''; }
    setMode(saved === 'feed' ? 'feed' : 'messenger', false);
    return true;
  }

  function setMode(next, save) {
    mode = next === 'feed' ? 'feed' : 'messenger';
    if (!ui) return;
    ui.host.hidden = mode !== 'messenger';
    ui.patter.hidden = mode === 'messenger';
    ui.bMsg.setAttribute('aria-pressed', String(mode === 'messenger'));
    ui.bFeed.setAttribute('aria-pressed', String(mode === 'feed'));
    if (save) { try { localStorage.setItem(MODE_KEY, mode); } catch (e) { /* not kept */ } }
    if (mode === 'messenger' && onScreen()) mount();
  }

  function onScreen() {
    return !!ui && mode === 'messenger' && !document.hidden && ui.host.getClientRects().length > 0;
  }

  function say(text, retry) {
    if (!ui) return;
    ui.body.textContent = '';
    var p = make('div', 'tune-s3-say', text);
    var feed = make('button', '', 'Show the feed');
    feed.type = 'button';
    feed.addEventListener('click', function () { setMode('feed', true); });
    p.appendChild(make('br'));
    p.appendChild(feed);
    if (retry) {
      var again = make('button', '', 'Try again');
      again.type = 'button';
      again.addEventListener('click', function () { mount(); });
      p.appendChild(again);
    }
    ui.body.appendChild(p);
  }

  function mount() {
    if (view) return Promise.resolve(view);
    if (mounting) return mounting;
    if (!ui) return Promise.resolve(null);
    if (!document.getElementById('tuneS3Css')) {
      var css = make('link');
      css.id = 'tuneS3Css';
      css.rel = 'stylesheet';
      css.href = S3_CSS;
      document.head.appendChild(css);
    }
    say('Loading the Messenger...', false);
    mounting = import(S3_JS).then(function (mod) {
      ui.body.textContent = '';
      return mod.mountEmbedded(ui.body, {
        request: request,
        view: 'conversation',
        /* the "what built this message" fold (prompts, blocks) is the
           operator's: never on the listener page */
        details: false,
        /* the on-air pill and the round's facts in this page's own bar; the
           operator's buttons (cut panel, turn by turn, open System 3) go
           nowhere a listener can reach */
        chrome: {tools: ui.sink, air: ui.air, facts: ui.facts}
      });
    }).then(function (face) {
      view = face;
      mounting = null;
      return face;
    }, function (err) {
      mounting = null;
      say('The Messenger could not load: ' + String((err && err.message) || err), true);
      return null;
    });
    return mounting;
  }

  /* The round of a sounding line is shown when the Messenger does not hold
     it; one at a time. */
  function focus(cid) {
    if (showPending || !view) return;
    showPending = true;
    Promise.resolve(view.show({conversationId: cid})).catch(function () { /* the next tick asks again */ })
      .then(function () { showPending = false; });
  }

  /* A sounding line nobody on this page knows (a round the snapshot has
     not caught yet - or a line no System 3 node made): the door is asked
     sooner, twice at most. */
  function kick(lid) {
    var k = kicks.get(lid) || {n: 0, at: 0};
    if (k.n >= 2 || Date.now() - k.at < KICK_GAP) return;
    kicks.set(lid, {n: k.n + 1, at: Date.now()});
    if (kicks.size > 300) kicks.clear();
    fetchSnap(true);
  }

  /* The sounding line's own words are in the round the Messenger holds. */
  function wordsHeld(lid, hit) {
    var has = function (conv) {
      var l = conv && (conv.lines || []).find(function (x) { return String(x.line_id) === lid; });
      return !!(l && l.text);
    };
    if (has(snap.served.get(hit.cid))) { waitFor.line = ''; return true; }
    /* one wait for a run of lines whose words are late, not one per line
       (lines shorter than TEXT_WAIT must not hold the air for ever); a wait
       that stopped a while ago is not the same wait */
    var now = Date.now();
    if (!waitFor.line || now - waitFor.last > 1500) waitFor = {line: lid, since: now, last: now};
    waitFor.line = lid;
    waitFor.last = now;
    if (now - waitFor.since > TEXT_WAIT) return true;
    /* not at the door yet: ask it; here but not taken yet: the Messenger's
       next look (at most 2.5 s) takes it - its event says the round moved */
    var held = snap.convs.get(hit.cid);
    if (!(held && has(held.conv))) fetchSnap(true);
    return false;
  }

  /* THE EAR MOVED BACK IN TIME. Tuning in to the car stream puts this ear
     20-45 s behind the station the Messenger was following; its air only
     ever moves forward (a line behind it never plays again), so the lines
     this ear is about to hear would stay drawn as heard. The Messenger is
     built again from this page's own copy - no request - and follows the
     ear from where it is. Forward jumps (tuning out) it handles itself. */
  function earMoved() {
    var lag = lagSeconds();
    if (lag - earLag > 8) {
      earLag = lag;
      note('ear moved back ' + Math.round(lag) + ' s');
      try { view.dispose(); } catch (e) { /* already gone */ }
      view = null;
      snap.told.clear();
      snap.served.clear();
      lastClock = '';
      waitFor = {line: '', since: 0, last: 0};
      mount();
      return true;
    }
    if (lag < earLag) earLag = lag;
    return false;
  }

  function tick() {
    if (!ui) return;
    if (!view) {
      if (!mounting && onScreen()) mount();
      return;
    }
    if (!onScreen()) { note(document.hidden ? 'page hidden' : 'off screen'); return; }
    if (earMoved()) return;
    var s = null;
    try { s = sounding(); } catch (e) { s = null; }
    if (!s || !s.line) {
      note('silent');
      if (lastClock) {
        try { view.clock('', 0, 0); } catch (e) { /* closing */ }
        lastClock = '';
      }
      return;
    }
    var hit = snap.lines.get(s.line);
    var tag = s.line.slice(-6);
    if (!hit) { note('unknown ' + tag); kick(s.line); return; }
    if (!snap.served.has(hit.cid)) { note('show ' + tag); focus(hit.cid); return; }
    if (hit.spoken && !wordsHeld(s.line, hit)) { note('words? ' + tag); return; }
    var where = 'elsewhere';
    try { where = view.live(s.line); } catch (e) { where = 'threw ' + (e && e.message); }
    if (where !== 'here') { note(where + ' ' + tag); focus(hit.cid); return; }
    try { view.clock(s.line, s.at, s.total); } catch (e) { note('clock threw ' + (e && e.message)); }
    note('air ' + tag);
    lastClock = s.line;
  }

  function start() {
    if (ui || !build()) return;
    setInterval(function () { try { tick(); } catch (e) { /* the page goes on */ } }, TICK_MS);
    document.addEventListener('visibilitychange', function () { try { tick(); } catch (e) { /* later */ } });
  }

  window.PineTuneMessenger = {
    version: VERSION,
    showing: function () { return onScreen(); },
    mode: function (next) { if (next) setMode(next, true); return mode; },
    view: function () { return view; },
    sounding: function () { try { return sounding(); } catch (e) { return null; } },
    /* what the page last told the Messenger, and what it is waiting for */
    state: function () {
      return {lastClock: lastClock, waitFor: waitFor.line, waitingMs: waitFor.line ? Date.now() - waitFor.since : 0,
        trail: trail.slice(-12).map(function (x) { return x.what + (x.n > 1 ? ' x' + x.n : ''); }),
        served: Array.from(snap.served.keys()), told: Array.from(snap.told.entries()).map(function (e) { return e[0] + '=' + String(e[1]).slice(0, 40); })};
    },
    snapshot: function () {
      return {order: snap.order.slice(), rounds: snap.convs.size, lines: snap.lines.size, skew: snap.skew,
        fetchedAt: snap.fetchedAt, errors: snap.errors, off: snap.off};
    },
    request: request
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
