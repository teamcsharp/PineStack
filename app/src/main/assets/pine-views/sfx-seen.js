/* sfx-seen.js - [sfxseen] DID THE PICTURE REACH THE SCREEN?
 *
 * "Make sure that you are able to access a diagnostics based on the script
 *  system to see which SFX play and also have a follow up that also is able
 *  to tell you if they displayed on the screen and how they were able to
 *  display and react with the Pine tablet."           - the operator
 *
 * PineSfxTv.played() ([hcprev]) notes the first 'playing' event, and a
 * veiled, occluded, 0x0 or hidden <video> fires 'playing' all the same. So
 * every surface that is handed a clip now writes a DISPLAY RECEIPT:
 *
 *   surface      tube (the web CRT set) | native_wall (PineVideoWall) |
 *                bubble (the Message view) | audio_only | none
 *   first frame  requestVideoFrameCallback where the engine has it (it only
 *                fires for a frame actually composited); else currentTime
 *                advancing while the element is visible
 *   rect         where it was, and the fraction unoccluded - elementFromPoint
 *                at the four corners and the centre
 *   display      document.hidden, and the kiosk's screen state via the bridge
 *   the rest     frames, dropped, stalls, the error, seconds on screen, and
 *                why it did not show; the operator's taps, holds, the radial,
 *                the replay corner and the parody sheet, during or after.
 *
 * Keyed by the script's line id (clip.line), the delivery id and the sfx id,
 * so the station joins it to the "A sting off the board" row
 * (GET /api/sfx/display-audit). Batched to POST /api/sfx/display-receipts
 * every few seconds; NEVER in the way of playback (no await on any play
 * road, one shared 1 s sampler only while a receipt is open, nothing per
 * frame), and buffered in localStorage while the station cannot be reached.
 *
 * Loaded before sfx-tv.js and script-page.js; every hook in them reads
 * `root.PineSfxSeen &&`, so a surface without this file is untouched. */
(function (root) {
  'use strict';
  if (!root || root.PineSfxSeen) return;
  var doc = root.document;

  var ENDPOINT = '/api/sfx/display-receipts';
  var AUDIT = '/api/sfx/display-audit';
  var STORE_KEY = 'pineSfxSeenQueue';
  var FLUSH_MS = 4000, FLUSH_MOST_MS = 60000;
  var BATCH_MOST = 40, QUEUE_MOST = 300;
  var SAMPLE_MS = 1000;
  var BEAT_MS = 120000;
  var SHOWN_MIN_S = 0.5;
  var AFTER_MS = 30000;          // an interaction this soon after a clip is a reaction to it
  var OPEN_MOST_MS = 15 * 60000; // a receipt nobody closed is closed by age

  function now() { return Date.now(); }
  function bridge() { return root.pineDesktop || null; }

  var PLAYER = (function () {
    try { if (root.PINE_PLAYER) return String(root.PINE_PLAYER); } catch (e) { /* none */ }
    var ua = String((root.navigator && root.navigator.userAgent) || '');
    if (/Electron/i.test(ua)) return 'desk';
    /* the kiosk's UA is "Linux; X11; TrebleDroid" - never key on /Android/ */
    if (bridge() && /Linux/i.test(ua)) return 'pinetab';
    return 'browser';
  })();

  /* ---- the outbox ---------------------------------------------------- */

  var queue = [];
  try {
    var kept = root.localStorage && root.localStorage.getItem(STORE_KEY);
    if (kept) queue = (JSON.parse(kept) || []).slice(-QUEUE_MOST);
  } catch (e) { queue = []; }
  var flushTimer = 0, backoff = FLUSH_MS, inFlight = false, sent = 0, failed = 0, lastError = '';

  function persist() {
    try { if (root.localStorage) root.localStorage.setItem(STORE_KEY, JSON.stringify(queue.slice(-QUEUE_MOST))); }
    catch (e) { /* a private window: the memory copy stands */ }
  }
  function enqueue(row) {
    row.player = PLAYER;
    queue.push(row);
    if (queue.length > QUEUE_MOST) queue.splice(0, queue.length - QUEUE_MOST);
    persist();
    arm(FLUSH_MS);
  }
  function arm(ms) {
    if (flushTimer) return;
    flushTimer = setTimeout(function () { flushTimer = 0; flush(); }, ms);
  }
  function post(body) {
    var b = bridge();
    if (b && typeof b.post === 'function') return Promise.resolve(b.post(ENDPOINT, body));
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to the station'));
    var headers = {'Content-Type': 'application/json'};
    try { if (root.SERVER_KEY) headers.Authorization = 'Bearer ' + root.SERVER_KEY; } catch (e) { /* none */ }
    return root.fetch(ENDPOINT, {method: 'POST', headers: headers, body: JSON.stringify(body)})
      .then(function (res) { if (!res.ok) throw new Error('HTTP ' + res.status); return res.json(); });
  }
  function flush() {
    if (inFlight || !queue.length) return;
    if (root.navigator && root.navigator.onLine === false) { arm(backoff); return; }
    var batch = queue.slice(0, BATCH_MOST);
    inFlight = true;
    var done = false;
    var guard = setTimeout(function () { settle(false, 'no answer in 15 s'); }, 15000);
    function settle(ok, err) {
      if (done) return;
      done = true;
      clearTimeout(guard);
      inFlight = false;
      if (ok) {
        queue.splice(0, batch.length);
        sent += batch.length;
        backoff = FLUSH_MS;
        persist();
        if (queue.length) arm(FLUSH_MS);
      } else {
        failed += 1;
        lastError = String(err || 'failed').slice(0, 120);
        backoff = Math.min(FLUSH_MOST_MS, backoff * 2);
        arm(backoff);
      }
    }
    try {
      post({player: PLAYER, sent_ms: now(), rows: batch}).then(
        function () { settle(true); }, function (err) { settle(false, err && err.message); });
    } catch (err) { settle(false, err && err.message); }
  }
  if (root.addEventListener) root.addEventListener('online', function () { backoff = FLUSH_MS; arm(500); });

  /* ---- identity ------------------------------------------------------- */

  var ridSeq = 0;
  function rid() { return PLAYER.slice(0, 3) + now().toString(36) + (ridSeq += 1).toString(36); }
  function sfxOf(clip) {
    var m = /\/sfx\/([0-9A-Za-z_-]{6,64})/.exec(String((clip && clip.url) || ''));
    if (m) return m[1];
    var id = String((clip && (clip.sfx || clip.sfx_video_id || clip.id)) || '');
    return /^[0-9A-Za-z_-]{6,64}$/.test(id) ? id : '';
  }
  function keyOf(clip) {
    clip = clip || {};
    return {line: String(clip.line || clip.line_id || ''),
            delivery_id: String(clip.delivery_id || ''),
            sfx: sfxOf(clip), url: String(clip.url || '').split('?')[0],
            sting: String(clip.sting || clip.text || clip.name || '').slice(0, 120)};
  }
  function fresh(clip, surface) {
    var k = keyOf(clip);
    var due = Number(clip && clip.broadcast_ms) || 0;
    return {kind: 'receipt', rid: rid(), surface: surface, line: k.line, delivery_id: k.delivery_id,
            sfx: k.sfx, url: k.url, sting: k.sting, due_ms: due, requested_ms: now(),
            first_frame_ms: 0, first_frame_via: '', first_frame_lag_ms: null,
            shown_s: 0, hidden_s: 0, frames: 0, dropped: 0, stalls: 0, error: '', error_code: 0,
            rect: {x: 0, y: 0, w: 0, h: 0}, unoccluded: 0, occluder: '', reason: '', outcome: '',
            display: {hidden: !!(doc && doc.hidden), screen_on: screenOn},
            silent: !!(clip && clip.silent_picture), endless: !!(clip && clip.endless),
            replay: !!(clip && clip.__pineReplay), interactions: [], closed_ms: 0};
  }

  /* ---- the display: page hidden, screen off ---------------------------- */

  var screenOn = null;            // null = the bridge has not said
  function askScreen() {
    var b = bridge();
    if (!b || typeof b.videoWall !== 'function') return;
    try {
      Promise.resolve(b.videoWall('state')).then(function (got) {
        var st = typeof got === 'string' ? JSON.parse(got) : got;
        if (st && typeof st.screen_on === 'boolean') screenOn = st.screen_on;
      }, function () { /* the next ask */ });
    } catch (e) { /* no answer */ }
  }

  /* ---- where it is, and how much of it can be seen --------------------- */

  function describe(node) {
    if (!node || !node.tagName) return '';
    var s = node.tagName.toLowerCase();
    if (node.id) s += '#' + node.id;
    var c = String(node.className && node.className.baseVal != null ? node.className.baseVal : node.className || '');
    if (c) s += '.' + c.trim().split(/\s+/).slice(0, 2).join('.');
    return s.slice(0, 80);
  }
  function measure(el, own) {
    var out = {rect: {x: 0, y: 0, w: 0, h: 0}, frac: 0, occluder: '', why: ''};
    if (!el || !el.isConnected) { out.why = 'the element left the page'; return out; }
    /* [pip-seen] in Pine PiP the set's host is hidden and the panel draws this element on a tile of its
       own: the tile's rectangle is where the picture is seen, fully, whatever the element's own box says */
    try {
      var pipPanel = root.PinePipPanel;
      var onTile = pipPanel && typeof pipPanel.showing === 'function' ? pipPanel.showing(el) : null;
      if (onTile && onTile.w >= 2 && onTile.h >= 2) { out.rect = onTile; out.frac = 1; out.via = 'pip'; return out; }
    } catch (e) { /* the element's own box, below */ }
    var r = el.getBoundingClientRect();
    out.rect = {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)};
    if (r.width < 2 || r.height < 2) { out.why = 'zero size'; return out; }
    var W = root.innerWidth || 0, H = root.innerHeight || 0;
    if (r.right <= 0 || r.bottom <= 0 || r.left >= W || r.top >= H) {
      out.why = (r.left < -1000 || r.top < -1000 || r.left > W + 1000) ? 'veiled (moved off-screen)' : 'off-screen';
      return out;
    }
    try {
      if (typeof el.checkVisibility === 'function'
          && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) {
        out.why = 'hidden by style (visibility/opacity/display)';
        return out;
      }
    } catch (e) { /* older engine */ }
    var ix = 3, pts = [[r.left + ix, r.top + ix], [r.right - ix, r.top + ix], [r.left + ix, r.bottom - ix],
      [r.right - ix, r.bottom - ix], [(r.left + r.right) / 2, (r.top + r.bottom) / 2]];
    var hits = 0;
    for (var i = 0; i < pts.length; i += 1) {
      var x = pts[i][0], y = pts[i][1];
      if (x < 0 || y < 0 || x >= W || y >= H) continue;          // cut by the edge of the glass
      var hit = null;
      try { hit = doc.elementFromPoint(x, y); } catch (e) { hit = null; }
      if (hit && (hit === el || el.contains(hit) || (own && own.contains(hit)))) hits += 1;
      else if (hit && !out.occluder) out.occluder = describe(hit);
    }
    out.frac = hits / pts.length;
    if (!hits) out.why = 'occluded' + (out.occluder ? ' by ' + out.occluder : '');
    return out;
  }

  /* ---- open receipts and the one sampler ------------------------------- */

  var open = [];                  // {r, el, own, ...state}
  var closed = [];                // the last few closed, for a reaction after the fact
  var sampler = 0;
  function samplerArm() {
    if (sampler || !open.length) return;
    sampler = setInterval(sample, SAMPLE_MS);
  }
  function samplerStop() { if (sampler && !open.length) { clearInterval(sampler); sampler = 0; } }

  function sample() {
    var t = now();
    for (var i = open.length - 1; i >= 0; i -= 1) {
      var o = open[i];
      if (o.native) continue;
      try { tick(o, t); } catch (e) { /* a receipt never breaks the set */ }
    }
    samplerStop();
  }

  function tick(o, t) {
    var el = o.el, r = o.r;
    if (!el.isConnected) { close(o, o.shownAny ? '' : 'the element left the page before a frame'); return; }
    if (t - r.requested_ms > OPEN_MOST_MS) { close(o, 'still open after 15 minutes'); return; }
    var dt = Math.min(5, (t - (o.lastAt || t)) / 1000);
    o.lastAt = t;
    var hidden = !!(doc && doc.hidden);
    if (hidden) { r.hidden_s = Math.round((r.hidden_s + dt) * 100) / 100; r.display.hidden = true; }
    var m = measure(el, o.own);
    o.lastWhy = m.why;
    if (m.rect.w * m.rect.h > r.rect.w * r.rect.h || !r.rect.w) r.rect = m.rect;
    var ct = Number(el.currentTime) || 0;
    var moving = !el.paused && ct > (o.lastCt || 0) + 0.02;
    o.lastCt = ct;
    if (moving && m.frac > 0) {
      o.minFrac = Math.min(o.minFrac == null ? 1 : o.minFrac, m.frac);
      if (m.occluder && !r.occluder) r.occluder = m.occluder;
    }
    /* the fallback first frame: time moves, the element can be seen */
    if (!r.first_frame_ms && moving && m.frac > 0 && !hidden && screenOn !== false) firstFrame(o, 'time');
    if (moving && m.frac >= 0.6 && !hidden && screenOn !== false) {
      r.shown_s = Math.round((r.shown_s + dt) * 100) / 100;
      o.shownAny = true;
    }
    if (!o.bestFrac || m.frac > o.bestFrac) o.bestFrac = m.frac;
  }

  function firstFrame(o, via) {
    var r = o.r;
    if (r.first_frame_ms) return;
    r.first_frame_ms = now();
    r.first_frame_via = via;
    /* from the clip's own air moment when the set knew it (a late start
       shows as a late first frame), else from the hand-over */
    var due = Number(o.dueLocal) || 0;
    var from = due > 0 ? due : r.requested_ms;
    r.first_frame_lag_ms = r.first_frame_ms - from;
    var m = measure(o.el, o.own);
    r.rect = m.rect;
    if (m.via) r.via = m.via;                                /* [pip-seen] seen on a PiP tile */
    r.unoccluded = Math.round(m.frac * 100) / 100;
    if (m.occluder) r.occluder = m.occluder;
    askScreen();
  }

  function quality(el) {
    try {
      var q = el.getVideoPlaybackQuality && el.getVideoPlaybackQuality();
      if (q) return {total: q.totalVideoFrames || 0, dropped: q.droppedVideoFrames || 0};
    } catch (e) { /* none */ }
    return {total: Number(el.webkitDecodedFrameCount) || 0, dropped: Number(el.webkitDroppedFrameCount) || 0};
  }

  var MEDIA_ERRORS = {1: 'aborted', 2: 'network error fetching the file', 3: 'undecodable file (decode error)',
    4: 'undecodable file (format not supported)'};

  function close(o, why) {
    var i = open.indexOf(o);
    if (i < 0) return;
    open.splice(i, 1);
    var r = o.r;
    r.closed_ms = now();
    if (o.el && !o.native) {
      var q = quality(o.el);
      r.frames = Math.max(0, q.total - (o.q0 ? o.q0.total : 0));
      r.dropped = Math.max(0, q.dropped - (o.q0 ? o.q0.dropped : 0));
      if (o.minFrac != null) r.unoccluded = Math.round(Math.min(r.unoccluded || 1, o.minFrac) * 100) / 100;
      else if (!r.first_frame_ms) r.unoccluded = Math.round((o.bestFrac || 0) * 100) / 100;
      o.unhook();
    }
    r.display.screen_on = screenOn;
    decide(r, why, o);
    closed.push(r);
    if (closed.length > 12) closed.shift();
    enqueue(r);
    samplerStop();
  }

  function decide(r, why, o) {
    var shownish = r.first_frame_ms && r.shown_s > 0;
    if (shownish && r.shown_s >= SHOWN_MIN_S) r.outcome = 'shown';
    else if (r.first_frame_ms) r.outcome = 'partial';
    else r.outcome = 'not_shown';
    if (r.outcome === 'shown') { r.reason = r.error ? 'shown, then: ' + r.error : ''; return; }
    var reason = why || '';
    if (r.surface === 'audio_only') reason = 'audio-only clip: no picture';
    else if (r.error) reason = r.error;
    else if (screenOn === false) reason = 'display off';
    else if (r.hidden_s > 0 && !r.shown_s) reason = 'the page was hidden';
    else if (o && o.lastWhy && !reason) reason = o.lastWhy;
    else if (o && o.native && o.nativeWhy && !reason) reason = o.nativeWhy;
    if (!reason) reason = r.first_frame_ms ? 'on screen under half a second' : 'no frame was painted';
    r.reason = reason.slice(0, 160);
  }

  /* ---- the public roads ------------------------------------------------- */

  /* A <video> (or <audio>) handed a clip. `surface`: 'tube' | 'bubble'. */
  function track(el, clip, surface, opts) {
    if (!el || !clip) return null;
    opts = opts || {};
    for (var i = 0; i < open.length; i += 1) if (open[i].el === el) close(open[i], 'replaced by the next clip');
    var isAudio = String(el.tagName || '').toUpperCase() === 'AUDIO' || clip.video === false;
    var r = fresh(clip, isAudio ? 'audio_only' : (surface || 'tube'));
    if (opts.replay || (lastReplay.url && lastReplay.url === r.url && now() - lastReplay.at < 5000)) r.replay = true;
    var o = {r: r, el: el, own: opts.own || (el.closest && el.closest('.sfx-tv, .sp-mv-media')) || null,
             dueLocal: Number(clip.at) || 0, q0: quality(el), minFrac: null, bestFrac: 0, lastAt: now(),
             lastCt: Number(el.currentTime) || 0};
    var fns = {
      waiting: function () { r.stalls += 1; },
      error: function () {
        var code = (el.error && el.error.code) || 0;
        r.error_code = code;
        r.error = MEDIA_ERRORS[code] || 'media error';
        close(o, r.error);
      },
      ended: function () { tick(o, now()); close(o, ''); },
      playing: function () { if (!o.playingAt) o.playingAt = now(); }
    };
    Object.keys(fns).forEach(function (k) { el.addEventListener(k, fns[k]); });
    o.unhook = function () {
      Object.keys(fns).forEach(function (k) { try { el.removeEventListener(k, fns[k]); } catch (e) { /* gone */ } });
    };
    if (isAudio) {
      r.outcome = 'not_shown';
      /* an audio element has no picture; it is still a receipt of the road */
    } else if (typeof el.requestVideoFrameCallback === 'function') {
      /* ONE callback: it fires only for a frame the compositor presented,
         which is the whole question. Nothing per frame after it. */
      /* A frame the set is still hiding (the CRT's dot and line, a
         bubble's picture held under its poster) is not yet ON the screen:
         ask again on the next frame, for at most ~3 s, then leave it to
         the sampler's fallback. */
      var tries = 0;
      var onFrame = function () {
        if (open.indexOf(o) < 0 || r.first_frame_ms) return;
        if ((doc && doc.hidden) || screenOn === false) return;   /* painted to nobody */
        if (measure(el, o.own).frac > 0) { firstFrame(o, 'rvfc'); return; }
        if ((tries += 1) < 90) { try { el.requestVideoFrameCallback(onFrame); } catch (e) { /* sampler */ } }
      };
      try { el.requestVideoFrameCallback(onFrame); } catch (e) { /* the sampler's fallback */ }
    }
    open.push(o);
    samplerArm();
    return r.rid;
  }

  /* The set dropped a clip before any surface had it. */
  function drop(clip, surface, reason) {
    if (!clip) return;
    var r = fresh(clip, surface || 'none');
    r.outcome = 'not_shown';
    r.reason = String(reason || 'dropped').slice(0, 160);
    r.closed_ms = now();
    closed.push(r);
    if (closed.length > 12) closed.shift();
    enqueue(r);
  }

  /* The native PineVideoWall, from its own state() (sfx-tv.js wallFollow).
     `row` is the ring row the page holds for that id, when it has one. */
  var wallOpen = null;
  function wall(st, row) {
    if (!st) return;
    if (typeof st.screen_on === 'boolean') screenOn = st.screen_on;
    var id = String(st.playing || '');
    var t = now();
    if (wallOpen && (wallOpen.id !== id || !st.on)) {
      close(wallOpen, wallOpen.nativeWhy || '');
      wallOpen = null;
    }
    if (!st.on || !id) return;
    if (!wallOpen) {
      var clip = row || {id: id, url: '/sfx/' + id, endless: true};
      var r = fresh(clip, 'native_wall');
      if (!r.sfx) r.sfx = id;
      wallOpen = {r: r, id: id, native: true, lastAt: t, lastPos: -1, frames0: -1, dropped0: -1};
      open.push(wallOpen);
    }
    var o = wallOpen, rr = o.r;
    var dt = Math.min(5, (t - o.lastAt) / 1000);
    o.lastAt = t;
    var w = Number(st.w) || 0, h = Number(st.h) || 0;
    rr.rect = {x: Number(st.x) || 0, y: Number(st.y) || 0, w: w, h: h};
    var why = '';
    if (st.screen_on === false) why = 'display off';
    else if (st.veiled) why = 'veiled';
    else if (st.menu_hidden) why = 'retired for a menu';
    else if (w < 2 || h < 2) why = 'the native surface was 0x0';
    else if (st.visible === false) why = 'the native surface was not visible';
    else if (st.playback && st.playback !== 'ready') why = 'the native player was ' + st.playback;
    o.nativeWhy = why;
    var pos = Number(st.position_ms);
    var moving = isFinite(pos) && o.lastPos >= 0 && pos > o.lastPos;
    o.lastPos = isFinite(pos) ? pos : o.lastPos;
    /* the wall's own first frame (onRenderedFirstFrame) when the build has it */
    if (!rr.first_frame_ms && st.first_frame_id === id && Number(st.first_frame_at) > 0 && !why) {
      rr.first_frame_ms = Number(st.first_frame_at);
      rr.first_frame_via = 'native';
      if (Number(st.shown_since) > 0) rr.first_frame_lag_ms = rr.first_frame_ms - Number(st.shown_since);
      rr.unoccluded = 1;               // an overlay plane: nothing in the page can cover it
    } else if (!rr.first_frame_ms && moving && !why) {
      rr.first_frame_ms = t;
      rr.first_frame_via = 'position';
      rr.unoccluded = 1;
    }
    if (moving && !why) rr.shown_s = Math.round((rr.shown_s + dt) * 100) / 100;
    if (typeof st.frames_rendered === 'number') rr.frames = st.frames_rendered;
    if (typeof st.frames_dropped === 'number') rr.dropped = st.frames_dropped;
    if (st.last_error && String(st.last_error).indexOf(id) >= 0) rr.error = String(st.last_error).slice(0, 160);
  }

  /* The operator did something to a clip: tap, hold, radial, replay, parody, sheet... */
  var lastReplay = {url: '', at: 0};
  function interact(what, clip) {
    var t = now();
    var k = clip ? keyOf(clip) : null;
    if (what === 'replay' && k) lastReplay = {url: k.url, at: t};
    var target = null, during = false;
    function same(r) {
      if (!k) return true;
      return (k.line && r.line === k.line) || (k.sfx && r.sfx === k.sfx) || (k.url && r.url === k.url);
    }
    for (var i = open.length - 1; i >= 0 && !target; i -= 1) {
      if (same(open[i].r)) { target = open[i].r; during = true; }
    }
    for (var j = closed.length - 1; j >= 0 && !target; j -= 1) {
      if (t - closed[j].closed_ms <= AFTER_MS && same(closed[j])) target = closed[j];
    }
    if (target && during) target.interactions.push({what: String(what), at_ms: t});
    enqueue({kind: 'interaction', what: String(what), at_ms: t, during: during,
             rid: target ? target.rid : '', line: target ? target.line : (k ? k.line : ''),
             sfx: target ? target.sfx : (k ? k.sfx : ''), url: target ? target.url : (k ? k.url : ''),
             sting: target ? target.sting : (k ? k.sting : '')});
  }

  /* ---- the heartbeat: which state the player was in when nothing came ---- */

  function beat() {
    var tv = root.PineSfxTv, on = false;
    /* mounted = the set is running (the TV is on); on() = a clip is on the tube now */
    try { on = !!(tv && (typeof tv.mounted === 'function' ? tv.mounted() : (typeof tv.on === 'function' && tv.on()))); }
    catch (e) { on = false; }
    enqueue({kind: 'beat', at_ms: now(), tv_on: on, wall_on: !!wallOpen,
             hidden: !!(doc && doc.hidden), screen_on: screenOn, open: open.length});
  }
  setTimeout(function () { askScreen(); beat(); setInterval(function () { askScreen(); beat(); }, BEAT_MS); }, 5000);

  /* ---- what the station says: the line popup and the "SFX seen" panel ---- */

  function stationGet(path) {
    var b = bridge();
    if (b && typeof b.get === 'function') return Promise.resolve(b.get(path));
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to the station'));
    var headers = {};
    try { if (root.SERVER_KEY) headers.Authorization = 'Bearer ' + root.SERVER_KEY; } catch (e) { /* none */ }
    return root.fetch(path, {headers: headers}).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    });
  }
  function make(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function icon(name, label) {
    try { if (typeof root.pineIcon === 'function') return root.pineIcon(name, label) || ''; } catch (e) { /* text */ }
    return '';
  }
  function styleOnce() {
    if (doc.getElementById('pineSfxSeenStyle')) return;
    var s = doc.createElement('style');
    s.id = 'pineSfxSeenStyle';
    s.textContent = [
      '.sfxseen-strip{margin:4px 0 6px;padding:5px 8px;border-radius:6px;font-size:12px;line-height:1.35;',
      'background:rgba(120,160,255,.10);border:1px solid rgba(120,160,255,.25)}',
      '.sfxseen-strip .ok{color:#7fd48a}.sfxseen-strip .no{color:#ff9f7a}.sfxseen-strip i{opacity:.75}',
      '.sfxseen-panel{position:fixed;right:12px;top:56px;width:min(560px,calc(100vw - 24px));',
      'max-height:calc(100vh - 80px);display:flex;flex-direction:column;overflow:hidden;z-index:2147482000;background:#15181f;color:#e8ecf3;',
      'border:1px solid #3a4150;border-radius:10px;box-shadow:0 10px 40px rgba(0,0,0,.5);padding:12px 14px;',
      'font:13px/1.4 system-ui,sans-serif}',
      '.sfxseen-panel h3{margin:0 34px 6px 0;font-size:15px}',
      '.sfxseen-scroll{overflow:auto;min-height:0;flex:1 1 auto}',
      '.sfxseen-x{position:absolute;top:6px;right:6px;width:30px;height:30px;border:0;border-radius:6px;',
      'background:transparent;color:inherit;font-size:18px;cursor:pointer}',
      '.sfxseen-x:hover{background:rgba(255,255,255,.1)}',
      '.sfxseen-panel table{width:100%;border-collapse:collapse;font-size:12px}',
      '.sfxseen-panel td{padding:3px 4px;border-top:1px solid #2a303c;vertical-align:top}',
      '.sfxseen-panel .ok{color:#7fd48a}.sfxseen-panel .no{color:#ff9f7a}.sfxseen-panel .dim{opacity:.7}',
      '.sfxseen-hours{margin:4px 0 8px}.sfxseen-hours button{margin-right:4px}',
      '.sp-sfxseen-btn{margin-left:4px}'
    ].join('');
    doc.head.appendChild(s);
  }

  /* Under the line popup's tab strip, so it reads on every tab - System 3,
     Timing, the Roll tab - for a sting row. `tabs.strip` from lineTabsStrip. */
  function lineStrip(box, item, tabs) {
    try {
      if (!box || !item) return;
      var kind = String(item.kind || '');
      if (kind !== 'sting' && !item.sfx) return;
      var line = String(item.line || '');
      if (!line) return;
      styleOnce();
      var strip = make('div', 'sfxseen-strip', 'Asking whether this picture reached a screen...');
      strip.title = 'SFX display receipts: which player painted this clip, where, and for how long';
      var after = tabs && tabs.strip && tabs.strip.parentNode === box ? tabs.strip.nextSibling : null;
      box.insertBefore(strip, after);
      stationGet(AUDIT + '?line=' + encodeURIComponent(line)).then(function (rep) {
        strip.replaceChildren();
        var row = rep && rep.rows && rep.rows[0];
        if (!row) { strip.textContent = 'No display receipt for this line (none sent, or older than the store).'; return; }
        var played = row.played || {};
        strip.appendChild(make('i', '', played.state === 'heard' ? 'Heard' + (played.by ? ' (' + played.by + ')' : '')
          : (played.state || '')));
        Object.keys(row.displays || {}).forEach(function (p) {
          var d = row.displays[p];
          var ok = d.outcome === 'shown' || d.outcome === 'partial';
          strip.appendChild(make('div', ok ? 'ok' : 'no', d.sentence));
          (d.also || []).forEach(function (t) { strip.appendChild(make('div', 'dim', 'also: ' + t)); });
        });
        if (!Object.keys(row.displays || {}).length) strip.appendChild(make('div', 'no', 'No player sent a display receipt.'));
        (row.reactions || []).forEach(function (x) {
          strip.appendChild(make('div', 'dim', 'Reaction: ' + x.what + (x.during ? ' (while on screen)' : ' (after)')
            + ' on ' + x.player));
        });
      }, function (err) {
        strip.textContent = 'Display receipts could not be read: ' + String((err && err.message) || err).slice(0, 80);
      });
    } catch (e) { /* the popup stands without it */ }
  }

  var panelEl = null, panelUnwatch = null;
  function panelClose() {
    if (panelUnwatch) { try { panelUnwatch(); } catch (e) { /* gone */ } panelUnwatch = null; }
    if (panelEl && panelEl.parentNode) panelEl.parentNode.removeChild(panelEl);
    panelEl = null;
  }
  function panel(hours) {
    styleOnce();
    panelClose();
    hours = Number(hours) || 1;
    var box = make('div', 'sfxseen-panel');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'SFX seen');
    var x = make('button', 'sfxseen-x', '');
    x.type = 'button';
    x.title = 'Close';
    x.setAttribute('aria-label', 'Close');
    x.innerHTML = icon('c:close--filled', 'Close') || '✕';
    x.addEventListener('click', panelClose);
    box.appendChild(x);
    box.appendChild(make('h3', '', 'SFX seen - did the pictures reach a screen?'));
    var hrs = make('div', 'sfxseen-hours');
    [1, 3, 12].forEach(function (h) {
      var b = make('button', 'sp-btn', h + ' h');
      b.type = 'button';
      b.title = 'The last ' + h + ' hour' + (h > 1 ? 's' : '') + ' of script SFX rows';
      b.setAttribute('aria-pressed', String(h === hours));
      b.addEventListener('click', function () { panel(h); });
      hrs.appendChild(b);
    });
    box.appendChild(hrs);
    /* the X and the heading stay put; only the rows scroll */
    var scroll = make('div', 'sfxseen-scroll');
    box.appendChild(scroll);
    var body = make('div', '', 'Reading the display receipts...');
    scroll.appendChild(body);
    var mine = make('div', 'dim', '');
    mine.textContent = 'This player (' + PLAYER + '): ' + sent + ' receipts sent, ' + queue.length + ' waiting'
      + (failed ? ', ' + failed + ' failed sends (' + lastError + ')' : '') + ', ' + open.length + ' open.';
    scroll.appendChild(mine);
    doc.body.appendChild(box);
    panelEl = box;
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      try { panelUnwatch = root.PineDismiss.watch(box, panelClose, [], function () { return panelEl === box; }); }
      catch (e) { panelUnwatch = null; }
    }
    stationGet(AUDIT + '?hours=' + hours).then(function (rep) {
      if (panelEl !== box) return;
      body.replaceChildren();
      var s = rep.summary || {};
      body.appendChild(make('p', '', (s.script_sfx_rows || 0) + ' script SFX rows (' + (s.picture_rows || 0)
        + ' with a picture, ' + (s.audio_only_rows || 0) + ' audio only); heard ' + (s.played_heard || 0)
        + '; displayed somewhere ' + (s.displayed_anywhere || 0) + '; reactions ' + (s.reactions || 0) + '.'));
      Object.keys(s.players || {}).forEach(function (p) {
        var v = s.players[p];
        var line = p + ': displayed ' + v.displayed + ' of ' + v.picture_rows
          + (v.displayed_rate != null ? ' (' + Math.round(v.displayed_rate * 100) + '%)' : '')
          + ', partial ' + v.partial + ', not ' + v.not_displayed
          + (v.first_frame_lag_ms_median != null ? '; first frame ~' + Math.round(v.first_frame_lag_ms_median) + ' ms' : '');
        body.appendChild(make('div', '', line));
        Object.keys(v.not_displayed_by_reason || {}).forEach(function (why) {
          body.appendChild(make('div', 'dim', '    ' + v.not_displayed_by_reason[why] + '  ' + why));
        });
      });
      var table = make('table', '');
      (rep.rows || []).slice(-80).reverse().forEach(function (r) {
        var tr = make('tr', '');
        var when = new Date(r.at * 1000);
        tr.appendChild(make('td', 'dim', when.toTimeString().slice(0, 8)));
        var what = make('td', '', r.text || r.script);
        what.title = 'line ' + r.line + (r.sfx ? '  sfx ' + r.sfx : '');
        tr.appendChild(what);
        var seen = make('td', '');
        seen.appendChild(make('div', 'dim', (r.played && r.played.state) || ''));
        Object.keys(r.displays || {}).forEach(function (p) {
          var d = r.displays[p];
          seen.appendChild(make('div', (d.outcome === 'shown' || d.outcome === 'partial') ? 'ok' : 'no', d.sentence));
        });
        (r.reactions || []).forEach(function (xx) {
          seen.appendChild(make('div', 'dim', 'reaction: ' + xx.what + ' (' + xx.player + ')'));
        });
        tr.appendChild(seen);
        table.appendChild(tr);
      });
      body.appendChild(table);
    }, function (err) {
      if (panelEl === box) body.textContent = 'The audit could not be read: ' + String((err && err.message) || err).slice(0, 120);
    });
    return box;
  }

  /* The icon button for the script view's diagnostics (next to the report pad). */
  function button() {
    var b = make('button', 'sp-caution sp-sfxseen-btn', '');
    b.type = 'button';
    b.title = 'SFX seen: which script SFX played, and whether their pictures reached a screen';
    b.setAttribute('aria-label', 'SFX seen');
    b.innerHTML = icon('c:view', 'SFX seen') || '';
    if (!b.innerHTML) b.textContent = 'SFX';
    b.addEventListener('click', function (ev) { ev.stopPropagation(); ev.preventDefault(); panel(1); });
    return b;
  }

  root.PineSfxSeen = {
    player: PLAYER,
    track: track, drop: drop, wall: wall, interact: interact,
    lineStrip: lineStrip, panel: panel, panelClose: panelClose, button: button,
    flush: function () { if (flushTimer) { clearTimeout(flushTimer); flushTimer = 0; } flush(); },
    /* a plain copy for diagnostics and the harness */
    state: function () {
      return {player: PLAYER, queued: queue.length, sent: sent, failed: failed, last_error: lastError,
              open: open.map(function (o) { return {rid: o.r.rid, surface: o.r.surface, sting: o.r.sting}; }),
              closed: closed.map(function (r) { return JSON.parse(JSON.stringify(r)); }),
              screen_on: screenOn};
    },
    pending: function () { return queue.map(function (r) { return JSON.parse(JSON.stringify(r)); }); }
  };
})(typeof window !== 'undefined' ? window : this);
