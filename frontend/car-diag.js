/* frontend/car-diag.js - #1471: ONE TAP IN THE CAR CAPTURES THE STUTTER.
 *
 * "It stuttered on the motorway" arrives at the desk hours later with
 * nothing attached, and by then the station's own ledgers have moved on.
 * This module rides the tune page (served at /car-diag.js through the
 * public door) and does three things:
 *
 *   1. keeps a rolling ten-minute ring of what the PLAYER was doing - one
 *      sample every five seconds, mirrored to sessionStorage so a reload
 *      keeps the minutes before it;
 *   2. on a tap, runs an ACTIVE PROBE over the same road the audio takes
 *      (round trips, a throughput fetch, the newest HLS segment) and asks
 *      the phone once where it is and how fast it is moving;
 *   3. posts the lot to /api/car/report, where the station adds what IT
 *      was doing at that instant and files the pair as a Pine Box report.
 *
 * #1476: THE BLACK BOX. The first real drive (2026-09-27) showed that three
 * taps are not a record, and that two of their numbers lied:
 *
 *   - "15/34/53 stalls" were iOS `stalled` events, which native HLS fires
 *     about once per 5 s sample while the buffer is FULL. They are kept,
 *     but reported as `idle_stalled` and never counted as a stall. A stall
 *     is now an EPISODE: `waiting` until the playhead moves again, counted
 *     when it lasts 1.5 s. A FREEZE is the playhead not moving over a
 *     sample while the element is not paused - silence nobody announced.
 *   - the 5-minute numbers averaged in rows RESTORED from an earlier failed
 *     session; every restored row is now stamped `restored` and no window
 *     reads it.
 *   - the page decided its road once at load, so a phone that fell off
 *     Tailscale onto the Funnel still said "tailnet". The station's view
 *     of the road comes back on every upload and is the truth.
 *   - the operator could not type a note while driving: in the driving
 *     layout the tap records eight seconds of voice instead.
 *
 * And the only real failure of that drive was a station outage the phone
 * had to ride, which three taps could never show. So the page now keeps an
 * event log beside the samples and uploads both every 30 s (at once when
 * trouble happens) to /api/car/telemetry, queueing on the phone when the
 * station cannot be reached and flushing the backlog when it can.
 *
 * Plain ES5 on purpose: no build step, and it has to run in the WebView
 * of whatever phone is in the holder. Every browser API is behind a
 * try/catch; nothing here may ever touch the audio element's playback
 * (the one exception, #1476: after a voice note, a stream the audio-session
 * switch paused is started again), and nothing here ever reloads the page.
 * The page's own state is READ, never duplicated: the stream element is the
 * one stamped data-pine-live="stream", the road flags and reconnect counters
 * are the page's top-level bindings (let/const, so not window properties -
 * read through an indirect eval that returns undefined when they are absent).
 */
(function () {
  'use strict';
  if (window.PineCarDiag) return;

  var VERSION = '1478.1';
  var RING_MAX = 120;               // 120 x 5 s = ten minutes
  var SAMPLE_MS = 5000;
  var STORE_KEY = 'pbfm.cardiag.ring';
  var RES_KEEP_MS = 15 * 60 * 1000;
  var GLYPH = '🐛';       // U+1F41B bug -> c:debug in PineIcons (the operator asked for a bug)

  /* #1476: the black box's own keys and bounds. */
  var EV_KEY = 'pbfm.cardiag.events';   // sessionStorage: the event log survives a reload
  var SID_KEY = 'pbfm.cardiag.sid';     // sessionStorage: {sid, at, prev}
  var BOOT_KEY = 'pbfm.cardiag.boot';   // sessionStorage: the station boot this tab last saw
  var GEO_KEY = 'pbfm.cardiag.geo';     // sessionStorage: 'denied' = never ask again this session
  var Q_KEY = 'pbfm.cardiag.queue';     // localStorage: rows the station has not had yet
  var VOICE_KEY = 'pbfm.cardiag.voice'; // localStorage: '0' turns the voice note off
  var EV_MAX = 400;
  var Q_MAX = 600;
  var UPLOAD_MS = 30000;
  var RTT_MS = 30000;
  var CHUNK_MAX = 200 * 1024;       // a batch stays well under the station's 256 KB 413
  var BEACON_MAX = 60000;           // sendBeacon/keepalive share a 64 KB budget per page
  var POST_MS = 8000;
  var STALL_MIN_S = 1.5;
  var FREEZE_ADV = 0.5;
  var POS_EVERY_MS = 15000;
  var VOICE_S = 8;
  var VOICE_B64_MAX = 700 * 1024;
  var FUNNEL_HINT = 'Tailscale is not carrying this phone right now - open the Tailscale app';

  var loadedAt = Date.now();
  var ring = [];
  var restored = 0;
  var fresh = function () {
    /* #1476: `stalled` is counted as idle_stalled - on iOS native HLS it is
     * the idle heartbeat of a full buffer, not trouble. `stall`/`freeze`
     * are the episodes that are. */
    return {waiting: 0, idle_stalled: 0, playing: 0, error: 0, seeking: 0,
            pause: 0, play: 0, ended: 0, emptied: 0, srcchange: 0,
            stall: 0, stall_s: 0, freeze: 0};
  };
  var counters = fresh();           // since the last sample
  var totals = fresh();             // since page load
  totals.freeze_s = 0;
  totals.silent_s = 0;
  var attached = null;              // the element the listeners are on
  var lastSrc = '';
  var last = {t: 0, ct: 0, paused: true};   // for the advance ratio
  var resources = [];               // {k, s, e, d, b}
  var pos = null;
  var watchId = null;
  var battery = null;
  var busy = false;
  var lastReport = null;
  var lastResult = null;
  var lastVoice = null;
  var glyphOk = false;

  /* #1476: the session, the log, the uplink. */
  var sid = (function () {
    var r = '';
    try { r = Math.random().toString(36).slice(2, 10); } catch (e) {}
    return r + '-' + loadedAt.toString(36);
  })();
  var prevSession = {sid: null, at: null};
  var ROAD0 = '';
  try { ROAD0 = String(window.PINE_ROAD || ''); } catch (e) {}
  var evlog = [];
  var evTotal = 0;
  var pend = {s: [], e: []};        // made this page load, not yet delivered
  var queue = [];                   // mirror of the localStorage queue
  var media = {episode: null, playedSinceSrc: false, srcAt: 0, freezeRun: null, stalledEv: null};
  var roadSeen = null, roadSeenAt = 0, addrSeen = '', bootId = null, skewMs = null;
  var stationRestarts = 0, autoReport = null, lastAutoKey = '';
  var rtt = {busy: false, at: loadedAt - RTT_MS + 12000, n: 0};
  var rttNext = null;
  var geoNo = false, lastPosEvAt = 0, lastGeoErrAt = 0;
  var micDenied = false, recording = false;
  var HLS_NATIVE = null;
  var up = {seq: 0, inflight: null, lastAttempt: 0, lastLive: loadedAt - UPLOAD_MS + 3000,
            lastOk: 0, ok: 0, failed: 0, gap: 0, status: null, err: '', again: false,
            timer: 0, timerAt: 0, route404: false, budget: CHUNK_MAX, trouble: null,
            soon: false, flushing: false, down: 0, downStatus: null, dropped: 0, beacons: 0, sentRows: 0};
  var offlineAt = 0;

  // ---- reading the page --------------------------------------------------
  function pageVar(name) {
    // Top-level let/const in the page's script are global lexical bindings,
    // visible to an indirect eval but not on window. Undeclared -> undefined.
    try { return (0, eval)(name); } catch (e) { return undefined; }
  }
  function q(id) { try { return document.getElementById(id); } catch (e) { return null; } }
  function round(v, p) {
    var m = Math.pow(10, p || 0);
    return (typeof v === 'number' && isFinite(v)) ? Math.round(v * m) / m : null;
  }
  function median(arr) {
    var a = arr.filter(function (x) { return typeof x === 'number' && isFinite(x); })
               .sort(function (x, y) { return x - y; });
    if (!a.length) return null;
    var mid = a.length >> 1;
    return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
  }
  function scrub(url) {
    // A report is read by people and kept on disk: the token stays out.
    try { return String(url || '').replace(/([?&]t=)[^&]+/g, '$1<t>'); } catch (e) { return ''; }
  }
  function shortSrc(url) {
    /* #1476: the event log says WHICH road and mix a src was, not the
     * cache-buster and never the token. */
    if (!url) return '';
    try {
      var u = new URL(url, location.href);
      var out = u.pathname;
      var mix = u.searchParams.get('mix'), br = u.searchParams.get('br');
      if (mix) out += '?mix=' + mix;
      if (br) out += (mix ? '&' : '?') + 'br=' + br;
      return out.slice(0, 120);
    } catch (e) { return scrub(url).slice(0, 120); }
  }
  function token() {
    var k = pageVar('KEY');
    if (typeof k === 'string' && /^\d+\.[a-f0-9]+\.[a-f0-9]+$/.test(k)) return k;
    try {
      var m = /\/tune\/([^/?#]+)/.exec(location.pathname);
      if (m) return decodeURIComponent(m[1]);
    } catch (e) {}
    try {
      var s = document.currentScript && document.currentScript.src;
      var mm = s && /[?&]t=([^&]+)/.exec(s);
      if (mm) return decodeURIComponent(mm[1]);
    } catch (e) {}
    return '';
  }
  var TOKEN0 = token();             // #1476: read while currentScript still points at us
  function tok() { return token() || TOKEN0; }
  function build() {
    var b = pageVar('BUILD');
    if (typeof b === 'string' && b && b !== '__BUILD__') return b;
    try {
      var el = q('build');
      var m = el && /player (\w+)/.exec(el.textContent || '');
      if (m) return m[1];
    } catch (e) {}
    return '';
  }
  function road() {
    /* #1475: the station tells the page which road it came in on
     * (tailnet / lan / house / funnel); the hostname guess is the
     * fallback for a page served without it. #1476: and every telemetry
     * answer re-tells it, so this follows the phone when the road moves. */
    try {
      if (typeof window.PINE_ROAD === 'string' && window.PINE_ROAD) return window.PINE_ROAD;
    } catch (e) {}
    var h = '';
    try { h = String(location.hostname || ''); } catch (e) {}
    if (/\.ts\.net$/i.test(h)) return 'funnel';
    if (/^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(h)) return 'tailnet';
    if (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(h)) return 'lan';
    if (/^(127\.|localhost$)/i.test(h)) return 'loopback';
    return h ? 'other' : 'unknown';
  }
  function streamMode() {
    var v = pageVar('streamMode');
    if (typeof v === 'boolean') return v;
    var m = q('lvMode');
    return !!(m && m.value === 'stream');
  }
  function hlsWanted() {
    if (HLS_NATIVE !== null) return HLS_NATIVE;
    try { if (typeof window.wantsHls === 'function') return (HLS_NATIVE = !!window.wantsHls()); } catch (e) {}
    try {
      var p = document.createElement('audio');
      HLS_NATIVE = !!(p.canPlayType && p.canPlayType('application/vnd.apple.mpegurl'));
    } catch (e) { HLS_NATIVE = false; }
    return HLS_NATIVE;
  }
  function mode() {
    if (!streamMode()) return 'house';
    return hlsWanted() ? 'hls' : 'mp3';
  }
  function findAudio() {
    var r = pageVar('radio');
    if (r && typeof r === 'object' && 'currentTime' in r) return r;
    try {
      var el = document.querySelector('audio[data-pine-live="stream"]');
      if (el) return el;
      if (!streamMode()) return document.querySelector('audio[data-pine-live="music"]');
    } catch (e) {}
    return null;
  }
  function pagePlaying() {
    var p = pageVar('playing');
    if (typeof p === 'boolean') return p;
    var b = q('tune');
    return !!(b && /stop/i.test(b.textContent || ''));
  }
  function pageCounters() {
    var out = {};
    var tries = pageVar('streamTries');
    if (typeof tries === 'number') out.tries = tries;
    var since = pageVar('streamAtSince');
    if (typeof since === 'number' && since > 0) out.stuck_s = round((Date.now() - since) / 1000, 1);
    var started = pageVar('streamStartMs');
    if (typeof started === 'number' && started > 0) out.socket_s = round((Date.now() - started) / 1000, 1);
    try { var n = q('note'); if (n) out.note = String(n.textContent || '').slice(0, 80); } catch (e) {}
    return out;
  }
  function carOn() {
    try { return document.body.classList.contains('car'); } catch (e) { return false; }
  }
  function host() { try { return location.host; } catch (e) { return ''; } }
  function standalone() {
    try { if (typeof navigator.standalone === 'boolean') return navigator.standalone; } catch (e) {}
    try { return window.matchMedia('(display-mode: standalone)').matches; } catch (e) { return null; }
  }
  function nowS(p) { return round(Date.now() / 1000, p || 0); }

  // ---- the event log (#1476) ---------------------------------------------
  function clip(d) {
    // A copy, bounded: a detail must never grow a batch past the budget or
    // change after it was logged.
    if (d === undefined || d === null) return null;
    try {
      var s = JSON.stringify(d);
      if (s === undefined) return null;
      if (s.length > 600) return {clipped: s.slice(0, 600)};
      return JSON.parse(s);
    } catch (e) {
      try { return {unserialisable: String(d).slice(0, 200)}; } catch (e2) { return null; }
    }
  }
  function logEvent(k, d, by) {
    var e = {t: nowS(3), k: String(k)};
    var c = clip(d);
    if (c !== null) e.d = c;
    if (by) e.by = by;
    evlog.push(e);
    if (evlog.length > EV_MAX) evlog.splice(0, evlog.length - EV_MAX);
    pend.e.push(e);
    evTotal++;
    spill();
    return e;
  }
  function spill() {
    /* A page whose uplink never runs (a tab frozen in the background) must
     * not grow without bound: the oldest unsent rows go to the queue, which
     * is bounded itself. */
    if (pend.e.length + pend.s.length <= 400) return;
    try { enqueue(pend.s.splice(0, 100), pend.e.splice(0, 100), sid); } catch (e) {}
  }
  function pendHas(e) { return pend.e.indexOf(e) >= 0; }

  // ---- the audio element ------------------------------------------------
  function bufferedAhead(el) {
    try {
      var b = el.buffered;
      if (!b || !b.length) return 0;
      var ct = Number(el.currentTime || 0);
      // the range the playhead is in, else the last one
      for (var i = 0; i < b.length; i++) {
        if (b.start(i) <= ct && ct <= b.end(i)) return round(b.end(i) - ct, 2);
      }
      return round(b.end(b.length - 1) - ct, 2);
    } catch (e) { return null; }
  }
  function ranges(tr) {
    var out = [];
    try { for (var i = 0; i < tr.length; i++) out.push([round(tr.start(i), 2), round(tr.end(i), 2)]); } catch (e) {}
    return out;
  }
  function srcOf(el) {
    // The attribute changes the instant the page assigns .src; currentSrc
    // lags until the load algorithm runs.
    try { return el.getAttribute('src') || el.currentSrc || ''; } catch (e) { return ''; }
  }
  function audioSessionState() {
    // Optional, passive evidence. The browser cannot identify CarPlay's
    // physical output; an unavailable session stays explicitly unknown.
    try {
      var a = navigator.audioSession;
      return a && typeof a.state === 'string' ? a.state.slice(0, 40) : null;
    } catch (e) { return null; }
  }
  function mstate(el) {
    var o = {};
    try {
      o.ct = round(el.currentTime, 2); o.ahead = bufferedAhead(el);
      o.rs = el.readyState; o.ns = el.networkState;
      o.paused = !!el.paused; o.ended = !!el.ended;
      o.rate = round(el.playbackRate, 2);
      o.intent = pagePlaying(); o.hidden = !!document.hidden;
      o.audio_session = audioSessionState();
    } catch (e) {}
    return o;
  }
  var MEDIA = ['waiting', 'stalled', 'playing', 'error', 'seeking', 'pause', 'play',
               'ended', 'emptied', 'loadstart', 'timeupdate'];
  function attach(el) {
    if (!el || attached === el) return;
    if (!el.__pcd1476) {
      el.__pcd1476 = true;
      MEDIA.forEach(function (n) {
        try {
          el.addEventListener(n, function () {
            // an element the page has since replaced counts for nothing
            if (el !== attached) return;
            try { onMedia(n, el); } catch (e) {}
          }, false);
        } catch (e) {}
      });
    }
    var was = !!attached;
    attached = el;
    media.episode = null; media.freezeRun = null;
    var tag = '';
    try { tag = el.getAttribute('data-pine-live') || el.tagName.toLowerCase(); } catch (e) {}
    logEvent('attach', {el: tag, again: was});
    /* #1476: the page appends the stream element and sets its src in the
     * same breath, before this sees it - so a src already there IS the new
     * src, and the startup that follows is timed from here. */
    lastSrc = '';
    checkSrc(el, 'attach');
    try { if (!el.paused && el.readyState >= 3) media.playedSinceSrc = true; } catch (e) {}
    last = {t: 0, ct: 0, paused: true};
  }
  function checkSrc(el, via) {
    var src = srcOf(el);
    if (src === lastSrc) return false;
    var was = lastSrc;
    lastSrc = src;
    counters.srcchange++; totals.srcchange++;
    if (media.episode) endEpisode('srcchange', el);
    media.playedSinceSrc = false;
    media.srcAt = Date.now();
    media.freezeRun = null;
    logEvent('srcchange', {src: shortSrc(src), was: shortSrc(was), via: via});
    return true;
  }
  function onMedia(n, el) {
    var nowMs = Date.now();
    if (n === 'timeupdate') {
      // #1476: the episode ends when the playhead really moves again
      var ep = media.episode;
      if (ep && Number(el.currentTime || 0) > ep.ct + 0.25) endEpisode('progress', el);
      return;
    }
    if (n === 'loadstart') { checkSrc(el, 'loadstart'); return; }
    if (n === 'emptied') checkSrc(el, 'emptied');
    var key = (n === 'stalled') ? 'idle_stalled' : n;
    if (counters.hasOwnProperty(key)) { counters[key]++; totals[key]++; }
    if (n === 'stalled') { idleStalled(el); return; }
    var d = mstate(el);
    if (n === 'error') {
      try {
        var er = el.error;
        d.code = er ? er.code : null;
        d.msg = er ? String(er.message || '').slice(0, 160) : '';
      } catch (e) {}
    }
    if (n === 'waiting' && !media.episode) {
      var ep0 = {t0: nowMs, ct: Number(el.currentTime || 0), startup: !media.playedSinceSrc};
      media.episode = ep0;
      if (!ep0.startup) {
        // trouble the moment it has lasted long enough to be heard
        setTimeout(function () {
          if (media.episode !== ep0) return;
          trouble('stall', {ongoing: true, s: round((Date.now() - ep0.t0) / 1000, 2),
                            ahead: bufferedAhead(el), rs: el.readyState});
        }, STALL_MIN_S * 1000 + 100);
      }
    }
    if (n === 'playing') {
      if (!media.playedSinceSrc && media.srcAt) d.startup_s = round((nowMs - media.srcAt) / 1000, 2);
      media.playedSinceSrc = true;
    }
    if (media.episode && (n === 'playing' || n === 'pause' || n === 'ended' || n === 'emptied' || n === 'error')) {
      endEpisode(n, el);
    }
    logEvent(n, d);
    if (n === 'error') trouble('error', d);
  }
  function idleStalled(el) {
    /* #1476: iOS fires this about every 5 s while the buffer is full. One
     * row per upload batch (the row is only grown while it is unsent),
     * counted, with the buffer it had - not 700 rows an hour pushing the
     * real events out of a 400-row log. */
    var ahead = bufferedAhead(el);
    var le = media.stalledEv;
    if (le && le.d && pendHas(le)) {
      le.d.n = (le.d.n || 1) + 1;
      le.d.last = nowS(1);
      if (typeof ahead === 'number' && (typeof le.d.ahead_min !== 'number' || ahead < le.d.ahead_min)) le.d.ahead_min = ahead;
      return;
    }
    media.stalledEv = logEvent('idle_stalled', {n: 1, ahead: ahead, ahead_min: ahead});
  }
  function endEpisode(by, el) {
    var ep = media.episode;
    if (!ep) return;
    media.episode = null;
    var s = (Date.now() - ep.t0) / 1000;
    var d = {s: round(s, 2), by: by};
    if (el) d.ahead = bufferedAhead(el);
    if (ep.startup) { logEvent('startup_wait', d); return; }
    if (s >= STALL_MIN_S) {
      counters.stall++; totals.stall++;
      counters.stall_s += s; totals.stall_s += s;
      logEvent('stall', d);
      trouble('stall', d);
    } else {
      logEvent('waiting_end', d);
    }
  }
  function snapshot(el, full) {
    var s = {};
    if (!el) { s.el = 'none'; return s; }
    try {
      s.ct = round(el.currentTime, 2);
      s.ahead = bufferedAhead(el);
      s.rs = el.readyState;
      s.ns = el.networkState;
      s.paused = !!el.paused;
      s.rate = round(el.playbackRate, 2);
      s.ended = !!el.ended;
      s.intent = pagePlaying();
      s.audio_session = audioSessionState();
      s.err = el.error ? {code: el.error.code, msg: String(el.error.message || '').slice(0, 120)} : null;
      if (full) {
        s.muted = !!el.muted;
        s.vol = round(el.volume, 2);
        s.dur = (isFinite(el.duration) ? round(el.duration, 2) : 'live');
        s.src = scrub(el.currentSrc || el.src);
        s.buffered = ranges(el.buffered);
        s.seekable = ranges(el.seekable);
        s.preload = el.preload;
      }
    } catch (e) { s.err = {msg: 'snapshot: ' + (e && e.message)}; }
    return s;
  }

  // ---- what else is on the link ------------------------------------------
  function kindOf(name) {
    if (name.indexOf('/hls/') >= 0) return 'hls';
    if (name.indexOf('/stream.m3u8') >= 0) return 'm3u8';
    if (name.indexOf('/stream.mp3') >= 0) return 'mp3';
    if (name.indexOf('frame.jpg') >= 0) return 'frame';
    if (name.indexOf('/api/car/') >= 0) return 'probe';
    if (name.indexOf('/healthz') >= 0) return 'probe';
    if (name.indexOf('/api/') >= 0) return 'api';
    return 'other';
  }
  function origin0() {
    try {
      if (performance.timeOrigin) return performance.timeOrigin;
      if (performance.timing) return performance.timing.navigationStart;
    } catch (e) {}
    return Date.now();
  }
  function noteResource(e) {
    try {
      var name = String(e.name || '');
      var k = kindOf(name);
      var s = origin0() + e.startTime;
      resources.push({k: k, s: s, e: s + e.duration, d: e.duration,
                      b: e.transferSize || e.encodedBodySize || 0});
      if (resources.length > 6000) resources.splice(0, resources.length - 6000);
    } catch (err) {}
  }
  function watchResources() {
    var ok = false;
    try {
      if (typeof PerformanceObserver !== 'undefined') {
        var po = new PerformanceObserver(function (list) {
          try { list.getEntries().forEach(noteResource); } catch (e) {}
        });
        try { po.observe({type: 'resource', buffered: true}); ok = true; }
        catch (e) { po.observe({entryTypes: ['resource']}); ok = true; }
      }
    } catch (e) { ok = false; }
    if (!ok) {
      // no observer: read the buffer each sample instead
      try { performance.setResourceTimingBufferSize(1000); } catch (e) {}
    }
    return ok;
  }
  var observing = false;
  var readBuffer = {n: 0};
  function pullBuffer() {
    if (observing) return;
    try {
      var all = performance.getEntriesByType('resource');
      for (var i = readBuffer.n; i < all.length; i++) noteResource(all[i]);
      readBuffer.n = all.length;
      if (all.length > 900) { performance.clearResourceTimings(); readBuffer.n = 0; }
    } catch (e) {}
  }
  function resourceWindow(from, to) {
    var by = {};
    var cut = Date.now() - RES_KEEP_MS;
    var keep = [];
    for (var i = 0; i < resources.length; i++) {
      var r = resources[i];
      if (r.e < cut) continue;
      keep.push(r);
      if (r.e <= from || r.e > to) continue;
      var g = by[r.k] || (by[r.k] = {n: 0, kb: 0, ms: [], zero: 0});
      g.n++; g.kb += r.b / 1024; g.ms.push(r.d);
      if (!r.d || !r.b) g.zero++;
    }
    resources = keep;
    var out = {};
    for (var k in by) {
      if (!by.hasOwnProperty(k)) continue;
      var gg = by[k];
      out[k] = {n: gg.n, kb: round(gg.kb, 1), med: round(median(gg.ms), 0),
                max: round(Math.max.apply(null, gg.ms), 0), zero: gg.zero};
    }
    return out;
  }

  // ---- the phone ----------------------------------------------------------
  function conn() {
    try {
      var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
      if (!c) return null;
      return {type: c.type || null, eff: c.effectiveType || null,
              down: (typeof c.downlink === 'number') ? c.downlink : null,
              rtt: (typeof c.rtt === 'number') ? c.rtt : null,
              save: !!c.saveData};
    } catch (e) { return null; }
  }
  function watchBattery() {
    try {
      if (!navigator.getBattery) return;
      navigator.getBattery().then(function (b) {
        var upd = function () {
          try { battery = {level: round(b.level, 2), charging: !!b.charging}; } catch (e) {}
        };
        upd();
        try { b.addEventListener('levelchange', upd); b.addEventListener('chargingchange', upd); } catch (e) {}
      }, function () {});
    } catch (e) {}
  }
  function posOf(p) {
    var c = p && p.coords;
    if (!c) return null;
    var out = {lat: round(c.latitude, 5), lon: round(c.longitude, 5),
               acc: round(c.accuracy, 0), at: Math.round((p.timestamp || Date.now()) / 1000)};
    if (typeof c.speed === 'number' && isFinite(c.speed) && c.speed >= 0) {
      out.speed = round(c.speed, 1);            // m/s, as the API gives it
      out.kmh = round(c.speed * 3.6, 0);
    }
    if (typeof c.heading === 'number' && isFinite(c.heading)) out.heading = round(c.heading, 0);
    return out;
  }
  function geoRefused() {
    if (geoNo) return true;
    try { if (sessionStorage.getItem(GEO_KEY) === 'denied') { geoNo = true; return true; } } catch (e) {}
    return false;
  }
  function geoDenied(msg) {
    /* #1476: refused once is refused for the session - a permission sheet
     * popping up on a dashboard at speed is worse than no position. */
    geoNo = true;
    try { sessionStorage.setItem(GEO_KEY, 'denied'); } catch (e) {}
    try { if (watchId !== null) navigator.geolocation.clearWatch(watchId); } catch (e) {}
    watchId = null;
    logEvent('geo_denied', {msg: String(msg || '').slice(0, 80)});
  }
  function onFix(p) {
    var got = posOf(p);
    if (!got) return;
    pos = got;
    var nowMs = Date.now();
    if (nowMs - lastPosEvAt >= POS_EVERY_MS) { lastPosEvAt = nowMs; logEvent('pos', got); }
  }
  function startWatch(why) {
    /* #1476: position runs by itself in the driving layout (or once a
     * speed has been seen): lat/lon/speed/heading ride in every sample, so
     * a stall has a place on the map. Low accuracy - it is for "where on
     * the road", not turn-by-turn, and it must not cost the battery. */
    if (watchId !== null || geoRefused()) return;
    try {
      if (!navigator.geolocation) { geoNo = true; logEvent('geo_none', {why: why}); return; }
      watchId = navigator.geolocation.watchPosition(onFix, function (e) {
        if (e && e.code === 1) { geoDenied(e.message || 'denied'); return; }
        if (Date.now() - lastGeoErrAt > 300000) {
          lastGeoErrAt = Date.now();
          logEvent('geo_err', {code: e && e.code, msg: String((e && e.message) || '').slice(0, 80)});
        }
      }, {enableHighAccuracy: false, maximumAge: 10000, timeout: 30000});
      logEvent('geo_watch', {why: why});
    } catch (e) { watchId = null; }
  }
  function geoOnce(ms) {
    return new Promise(function (resolve) {
      var done = false;
      var finish = function (v) {
        if (done) return;
        done = true;
        // #1476: in drive mode the watch already holds a fix; a tap's own
        // request timing out must not throw that away. A running watch only
        // calls back when the phone moves, so its fix is as good as its age
        // says (carried with it); without a watch, two minutes at most.
        var age = (pos && pos.at) ? Date.now() / 1000 - pos.at : null;
        if (v && v.err && pos && age !== null && (watchId !== null || age < 120)) {
          var w = {}; for (var k in pos) if (pos.hasOwnProperty(k)) w[k] = pos[k];
          w.via = 'watch'; w.age_s = Math.round(age); w.tap_err = v.err;
          v = w;
        }
        resolve(v);
      };
      try {
        if (!navigator.geolocation) return finish({err: 'no geolocation API'});
        if (geoRefused()) return finish(pos || {err: 'location refused earlier this session - not asked again'});
        setTimeout(function () { finish({err: 'no fix within ' + ms + ' ms'}); }, ms + 800);
        navigator.geolocation.getCurrentPosition(function (p) {
          pos = posOf(p);
          startWatch(pos && typeof pos.speed === 'number' ? 'speed seen' : 'tap');   // later samples carry pos
          finish(pos);
        }, function (e) {
          if (e && e.code === 1) geoDenied(e.message || 'denied');
          finish({err: (e && e.message) || 'denied', code: e && e.code});
        }, {timeout: ms, enableHighAccuracy: false, maximumAge: 30000});
      } catch (e) { finish({err: 'geolocation threw: ' + (e && e.message)}); }
    });
  }

  // ---- the ring -----------------------------------------------------------
  function persist() {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(ring)); } catch (e) {}
    try { sessionStorage.setItem(EV_KEY, JSON.stringify(evlog)); } catch (e) {}
  }
  function restore() {
    /* #1476: a reload is a NEW session (a new sid), but the rows it brings
     * back know which session they came from and are stamped `restored`,
     * so no window of this page load ever averages them in. */
    try {
      var o = JSON.parse(sessionStorage.getItem(SID_KEY) || 'null');
      if (o && o.sid) prevSession = {sid: String(o.sid), at: typeof o.at === 'number' ? o.at : null};
    } catch (e) {}
    try { sessionStorage.setItem(SID_KEY, JSON.stringify({sid: sid, at: loadedAt, prev: prevSession.sid})); } catch (e) {}
    var stamp = function (r) {
      if (!r || typeof r !== 'object') return null;
      r.restored = true;
      if (!r.sid && prevSession.sid) r.sid = prevSession.sid;
      return r;
    };
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      var got = raw ? JSON.parse(raw) : null;
      if (got && got.length) {
        ring = got.slice(-RING_MAX).map(stamp).filter(function (r) { return !!r; });
        restored = ring.length;
        // the reload itself is a fact worth a row
        ring.push({t: nowS(), reload: true, road: road(), prev_sid: prevSession.sid});
      }
    } catch (e) { ring = []; restored = 0; }
    try {
      var ev = JSON.parse(sessionStorage.getItem(EV_KEY) || 'null');
      if (ev && ev.length) evlog = ev.slice(-EV_MAX).map(stamp).filter(function (r) { return !!r; });
    } catch (e) { evlog = []; }
    try { var b = sessionStorage.getItem(BOOT_KEY); if (b) prevSession.boot = b; } catch (e) {}
    logEvent(prevSession.sid ? 'reload' : 'load', {
      prev_sid: prevSession.sid, restored_rows: restored,
      prev_age_s: prevSession.at ? round((loadedAt - prevSession.at) / 1000, 0) : null,
      road: road(), build: build(), car: carOn(), standalone: standalone(), diag: VERSION});
  }
  function compact(c) {
    var o = {}, any = false;
    for (var k in c) {
      if (!c.hasOwnProperty(k) || !c[k]) continue;
      o[k] = (k === 'stall_s') ? round(c[k], 2) : c[k];
      any = true;
    }
    return any ? o : null;
  }
  function sample() {
    var now = Date.now();
    pullBuffer();
    var el = findAudio();
    attach(el);
    var s = {t: Math.round(now / 1000), road: road(), mode: mode(),
             play: pagePlaying(), vis: document.visibilityState, online: navigator.onLine};
    var snap = snapshot(el, false);
    for (var k in snap) if (snap.hasOwnProperty(k)) s[k] = snap[k];
    if (el) {
      try { checkSrc(el, 'poll'); } catch (e) {}
      var ct = Number(el.currentTime || 0);
      var paused = !!el.paused;
      /* #1476: the advance is only measured over a window the element spent
       * unpaused at BOTH ends, on one src - a window that starts at the tap
       * of Tune in or spans a new src is not a playhead that stopped. */
      if (last.t && !paused && !last.paused && lastSrc && media.srcAt <= last.t) {
        var dw = (now - last.t) / 1000;
        if (dw > SAMPLE_MS * 3 / 1000) s.gap_s = round(dw, 1);   // the phone slept the timers
        if (ct < last.ct - 0.5) s.reset = true;                   // a new src restarted the clock
        else if (dw > 0) {
          s.adv = round((ct - last.ct) / dw, 3);
          if (s.adv < FREEZE_ADV) {
            s.dw = round(dw, 1);
            totals.silent_s += dw;
            if (!media.playedSinceSrc || !last.played) {
              // it had not started when the window opened: a slow start, not a freeze
              s.starting = true;
            } else {
              s.frz = media.episode ? 'waiting' : 'silent';       // silent = nobody said so
              totals.freeze_s += dw;
              if (!media.freezeRun) {
                media.freezeRun = {t0: last.t, s: 0};
                counters.freeze++; totals.freeze++;
                var fd = {s: round(dw, 1), adv: s.adv, dw: round(dw, 1), why: s.frz, ahead: s.ahead, rs: s.rs};
                logEvent('freeze', fd);
                trouble('freeze', fd);
              }
              media.freezeRun.s += dw;
            }
          } else if (media.freezeRun) {
            logEvent('freeze_end', {s: round(media.freezeRun.s, 1)});
            media.freezeRun = null;
          }
        }
      } else if (media.freezeRun && paused) {
        logEvent('freeze_end', {s: round(media.freezeRun.s, 1), by: 'pause'});
        media.freezeRun = null;
      }
      last = {t: now, ct: ct, paused: paused, played: media.playedSinceSrc};
    } else {
      last = {t: 0, ct: 0, paused: true};
    }
    var ev = compact(counters);
    if (ev) s.ev = ev;
    counters = fresh();
    var c = conn(); if (c) s.conn = c;
    if (battery) s.bat = battery;
    try { if (navigator.deviceMemory) s.mem = navigator.deviceMemory; } catch (e) {}
    s.res = resourceWindow(now - SAMPLE_MS, now);
    if (pos) s.pos = pos;
    if (rttNext) { s.rtt = rttNext; rttNext = null; }   // #1476: the round-trip timeline
    var pc = pageCounters(); if (pc.tries !== undefined || pc.stuck_s !== undefined) s.pg = pc;
    ring.push(s);
    if (ring.length > RING_MAX) ring.splice(0, ring.length - RING_MAX);
    pend.s.push(s);
    spill();
    persist();
    return s;
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }
  function fmtS(s) {
    s = Number(s) || 0;
    return (s < 10 ? round(s, 1) : Math.round(s)) + ' s';
  }
  function playLine(o) {
    // #1476: the one line a person reads; stalled is named for what it is
    return plural(o.stalls, 'stall', 'stalls') + ' (' + fmtS(o.stall_s) + ')'
      + ' · ' + plural(o.freezes, 'freeze', 'freezes') + (o.freezes ? ' (' + fmtS(o.freeze_s) + ')' : '')
      + ' · ' + o.idle_stalled + " idle 'stalled' event" + (o.idle_stalled === 1 ? '' : 's') + ' (iOS, harmless)';
  }
  function ongoing(o) {
    // a stall still running at the moment of reading counts - it is the one being heard
    var ep = media.episode;
    if (!ep || ep.startup) return;
    var s = (Date.now() - ep.t0) / 1000;
    if (s < STALL_MIN_S) return;
    o.stalls++; o.stall_s += s; o.stalling = round(s, 1);
  }
  function summarise(rows, live) {
    var o = {samples: 0, stalls: 0, stall_s: 0, freezes: 0, freeze_s: 0, idle_stalled: 0,
             errors: 0, resets: 0, silent_s: 0, starting_s: 0, advance: null, advance_min: null};
    var advs = [];
    rows.forEach(function (r) {
      if (!r || r.reload || r.restored) return;     // #1476: only this page load
      o.samples++;
      var ev = r.ev || {};
      o.stalls += ev.stall || 0; o.stall_s += ev.stall_s || 0;
      o.freezes += ev.freeze || 0; o.idle_stalled += ev.idle_stalled || 0;
      o.errors += ev.error || 0;
      if (r.reset) o.resets++;
      if (r.frz) o.freeze_s += r.dw || 0;
      if (r.frz || r.starting) o.silent_s += r.dw || 0;
      if (r.starting) o.starting_s += r.dw || 0;
      if (typeof r.adv === 'number') advs.push(r.adv);
    });
    if (live) {
      // the seconds since the last sample count too: a stall that just ended is in the line at once
      o.stalls += live.stall || 0; o.stall_s += live.stall_s || 0;
      o.freezes += live.freeze || 0; o.idle_stalled += live.idle_stalled || 0;
      o.errors += live.error || 0;
    }
    ongoing(o);
    var mean = advs.length ? advs.reduce(function (a, b) { return a + b; }, 0) / advs.length : null;
    o.advance = round(mean, 3);
    o.advance_min = advs.length ? round(Math.min.apply(null, advs), 3) : null;
    o.stall_s = round(o.stall_s, 1); o.freeze_s = round(o.freeze_s, 1);
    o.silent_s = round(o.silent_s, 1); o.starting_s = round(o.starting_s, 1);
    o.line = playLine(o);
    return o;
  }
  function lastFive() {
    // the card's numbers: the last 60 samples (five minutes) OF THIS PAGE LOAD
    var mine = ring.filter(function (r) { return r && !r.restored && !r.reload; });
    return summarise(mine.slice(-60), counters);
  }
  function sinceLoad() {
    var o = {samples: ring.filter(function (r) { return r && !r.restored && !r.reload; }).length,
             stalls: totals.stall, stall_s: totals.stall_s, freezes: totals.freeze,
             freeze_s: totals.freeze_s, idle_stalled: totals.idle_stalled, errors: totals.error,
             silent_s: totals.silent_s, srcchange: totals.srcchange,
             up_s: round((Date.now() - loadedAt) / 1000, 0)};
    ongoing(o);
    o.stall_s = round(o.stall_s, 1); o.freeze_s = round(o.freeze_s, 1); o.silent_s = round(o.silent_s, 1);
    o.line = playLine(o);
    return o;
  }

  // ---- the probe -----------------------------------------------------------
  function now() { try { return performance.now(); } catch (e) { return Date.now(); } }
  function timed(url, ms, as) {
    return new Promise(function (resolve, reject) {
      var ac = null, done = false;
      try { if (typeof AbortController !== 'undefined') ac = new AbortController(); } catch (e) {}
      var timer = setTimeout(function () {
        if (done) return;
        done = true;
        try { if (ac) ac.abort(); } catch (e) {}
        reject(new Error('timeout after ' + ms + ' ms'));
      }, ms);
      var o = {cache: 'no-store', credentials: 'same-origin'};
      if (ac) o.signal = ac.signal;
      var t0 = now();
      try {
        fetch(url, o).then(function (r) {
          var t1 = now();
          var body = as === 'text' ? r.text() : r.arrayBuffer();
          return body.then(function (b) {
            if (done) return;
            done = true; clearTimeout(timer);
            resolve({ms: round(now() - t0, 1), ttfb: round(t1 - t0, 1), status: r.status,
                     bytes: as === 'text' ? b.length : b.byteLength,
                     text: as === 'text' ? b : null});
          });
        }, function (e) {
          if (done) return;
          done = true; clearTimeout(timer);
          reject(e);
        }).then(null, function (e) {
          if (done) return;
          done = true; clearTimeout(timer);
          reject(e);
        });
      } catch (e) { done = true; clearTimeout(timer); reject(e); }
    });
  }
  function rttProbe(probe, n) {
    var i = 0;
    function one() {
      if (i >= n) return Promise.resolve();
      i++;
      return timed('/healthz?c=' + i + '&_=' + Math.random().toString(36).slice(2), 4000)
        .then(function (r) { probe.rtt_ms.push(r.ms); },
              function (e) { probe.rtt_ms.push(null); probe.errors.push('rtt ' + i + ': ' + (e && e.message)); })
        .then(one);
    }
    return one().then(function () { probe.rtt_med = round(median(probe.rtt_ms), 0); });
  }
  function thruProbe(probe, tk) {
    return timed('/api/car/blob?kb=256&t=' + encodeURIComponent(tk) + '&_=' + Date.now(), 8000)
      .then(function (r) {
        probe.thru_bytes = r.bytes; probe.thru_ms = r.ms; probe.thru_status = r.status;
        probe.thru_kbps = (r.ms > 0 && r.status === 200) ? round(r.bytes * 8 / r.ms, 0) : null;
      }, function (e) { probe.thru_kbps = null; probe.errors.push('throughput: ' + (e && e.message)); });
  }
  function playlistUrl(el, tk) {
    // THE SAME URL THE PLAYER USES, so the station answers from the encoder
    // it already runs for this listener instead of starting another one.
    try {
      var src = el && (el.currentSrc || el.src);
      if (src && src.indexOf('.m3u8') >= 0) return src;
    } catch (e) {}
    try { if (typeof window.streamUrl === 'function') { var u = window.streamUrl(); if (u.indexOf('.m3u8') >= 0) return u; } } catch (e) {}
    return '/stream.m3u8?t=' + encodeURIComponent(tk);
  }
  function hlsProbe(probe, el, tk) {
    if (mode() !== 'hls') {
      probe.hls_playlist = {skipped: mode() === 'mp3' ? 'mp3 road - no playlist' : 'house road - no stream'};
      return Promise.resolve();
    }
    if (!el || !pagePlaying()) {
      // Asking for a playlist nobody is playing makes the station START an
      // encoder for it. A tap must never spawn work; it only measures.
      probe.hls_playlist = {skipped: 'not playing - no encoder to time'};
      return Promise.resolve();
    }
    var url = playlistUrl(el, tk);
    url += (url.indexOf('?') >= 0 ? '&' : '?') + '_p=' + Date.now();
    /* #1475: the station answers the player's URL with an ABR MASTER now.
     * Its entries are variant playlists, not segments - time the master,
     * then follow one variant (64k when listed) and time ITS segments. */
    function variantOf(r) {
      var text = String(r.text || '');
      if (text.indexOf('#EXT-X-STREAM-INF') < 0) return Promise.resolve(r);
      var uris = text.split('\n').map(function (ln) { return ln.replace(/\r$/, ''); })
        .filter(function (ln) { return ln && ln.charAt(0) !== '#'; });
      probe.hls_master = {ms: r.ms, status: r.status, variants: uris.length, url: scrub(url)};
      if (!uris.length) return Promise.resolve(r);
      var pick = uris.filter(function (u) { return /\/64[-\/]/.test(u); })[0] || uris[0];
      var vabs;
      try { vabs = new URL(pick, location.href).href; } catch (e) { vabs = pick; }
      url = vabs + (vabs.indexOf('?') >= 0 ? '&' : '?') + '_p=' + Date.now();
      return timed(url, 8000, 'text');
    }
    return timed(url, 8000, 'text').then(variantOf).then(function (r) {
      var segs = [], target = null, seq = null;
      String(r.text || '').split('\n').forEach(function (ln) {
        ln = ln.replace(/\r$/, '');
        if (!ln) return;
        if (ln.charAt(0) === '#') {
          var m = /^#EXT-X-TARGETDURATION:(\d+)/.exec(ln); if (m) target = Number(m[1]);
          var s = /^#EXT-X-MEDIA-SEQUENCE:(\d+)/.exec(ln); if (s) seq = Number(s[1]);
          return;
        }
        segs.push(ln);
      });
      probe.hls_playlist = {ms: r.ms, status: r.status, segments: segs.length, target: target,
                            seq: seq, url: scrub(url)};
      if (!segs.length) return;
      var newest = segs[segs.length - 1];
      var abs;
      try { abs = new URL(newest, location.href).href; } catch (e) { abs = newest; }
      var i = 0;
      function one() {
        if (i >= 3) return Promise.resolve();
        i++;
        var u = abs + (abs.indexOf('?') >= 0 ? '&' : '?') + '_p=' + i;
        return timed(u, 6000).then(function (rr) {
          probe.seg.push({url: scrub(newest), ms: rr.ms, ttfb: rr.ttfb, bytes: rr.bytes, status: rr.status});
        }, function (e) {
          probe.seg.push({url: scrub(newest), ms: null, err: String(e && e.message).slice(0, 80)});
        }).then(one);
      }
      return one().then(function () {
        var ms = probe.seg.map(function (x) { return x.ms; });
        probe.seg_med_ms = round(median(ms), 0);
        var kb = probe.seg.filter(function (x) { return x.ms && x.bytes; });
        if (kb.length) probe.seg_kbps = round(median(kb.map(function (x) { return x.bytes * 8 / x.ms; })), 0);
      });
    }, function (e) {
      probe.hls_playlist = {err: String(e && e.message).slice(0, 100), url: scrub(url)};
    });
  }
  function bounded(p, ms, label) {
    return new Promise(function (resolve) {
      var done = false;
      setTimeout(function () { if (!done) { done = true; resolve({timeout: label}); } }, ms);
      p.then(function (v) { if (!done) { done = true; resolve(v); } },
             function (e) { if (!done) { done = true; resolve({err: String(e && e.message)}); } });
    });
  }
  function rttTick() {
    /* #1476: one tiny round trip every 30 s while playing, so the drive has
     * a latency timeline and not just the three taps. A hidden page with
     * nothing playing asks for nothing. */
    var nowMs = Date.now();
    if (rtt.busy || nowMs - rtt.at < RTT_MS) return;
    var playingNow = pagePlaying();
    if (!playingNow && document.hidden) return;
    rtt.busy = true; rtt.at = nowMs; rtt.n++;
    timed('/healthz?c=' + rtt.n + '&_=' + Math.random().toString(36).slice(2, 8), POST_MS)
      .then(function (r) { rttNext = {ms: r.ms, st: r.status, play: playingNow}; },
            function (e) { rttNext = {ms: null, err: String((e && e.message) || e).slice(0, 60), play: playingNow}; })
      .then(function () { rtt.busy = false; }, function () { rtt.busy = false; });
  }

  // ---- the uplink: the black box (#1476) ----------------------------------
  function sizeOf(o) { try { return JSON.stringify(o).length; } catch (e) { return 1000; } }
  function takeRows(srcS, srcE, budget) {
    // Oldest first, events before samples (they are the smaller, rarer and
    // more telling rows); the rest waits for the next batch.
    var outS = [], outE = [], used = 0, z;
    while (srcE.length) {
      z = sizeOf(srcE[0]) + 1;
      if (used + z > budget && (outS.length || outE.length)) break;
      outE.push(srcE.shift()); used += z;
    }
    while (srcS.length) {
      z = sizeOf(srcS[0]) + 1;
      if (used + z > budget && (outS.length || outE.length)) break;
      outS.push(srcS.shift()); used += z;
    }
    return {s: outS, e: outE, bytes: used};
  }
  function pageBlock() {
    return {build: build(), road: road(), road_page: ROAD0, mode: mode(), host: host(),
            ua: (function () { try { return navigator.userAgent; } catch (e) { return ''; } })(),
            standalone: standalone(), car: carOn(), playing: pagePlaying(), hls_native: hlsWanted(),
            up_s: round((Date.now() - loadedAt) / 1000, 0), diag: VERSION,
            vis: document.visibilityState, online: navigator.onLine, skew_ms: skewMs};
  }
  function envelope(forSid, s, e, tr, queuedS) {
    var b = {v: 2, sid: forSid, seq: ++up.seq, page: pageBlock(), samples: s, events: e,
             trouble: tr || null, queued_s: queuedS || 0};
    if (forSid !== sid) b.carried_by = sid;   // an earlier page load's rows, delivered late
    return b;
  }
  function enqueue(s, e, forSid) {
    try {
      var qq = nowS();
      (e || []).forEach(function (r) { queue.push({sid: forSid || sid, q: qq, e: r}); });
      (s || []).forEach(function (r) { queue.push({sid: forSid || sid, q: qq, s: r}); });
      if (queue.length > Q_MAX) { up.dropped += queue.length - Q_MAX; queue.splice(0, queue.length - Q_MAX); }
      saveQueue();
    } catch (x) {}
  }
  function unqueue(rows) {
    try {
      queue = queue.filter(function (w) { return rows.indexOf(w) < 0; });
      saveQueue();
    } catch (x) {}
  }
  function saveQueue() {
    for (var tries = 0; tries < 4; tries++) {
      try {
        if (queue.length) localStorage.setItem(Q_KEY, JSON.stringify(queue));
        else localStorage.removeItem(Q_KEY);
        return true;
      } catch (x) {
        // full storage: the oldest quarter goes, the newest minutes stay
        if (!queue.length) return false;
        var cut = Math.max(1, Math.floor(queue.length / 4));
        up.dropped += cut;
        queue.splice(0, cut);
      }
    }
    return false;
  }
  function loadQueue() {
    try {
      var got = JSON.parse(localStorage.getItem(Q_KEY) || 'null');
      if (got && got.length) {
        queue = got.filter(function (w) { return w && (w.s || w.e); }).slice(-Q_MAX);
        up.flushing = queue.length > 0;   // flushed after the first live batch lands
      }
    } catch (x) { queue = []; }
  }
  function schedule(ms) {
    ms = Math.max(0, ms || 0);
    var at = Date.now() + ms;
    if (up.timer && up.timerAt <= at) return;
    if (up.timer) clearTimeout(up.timer);
    up.timerAt = at;
    up.timer = setTimeout(function () { up.timer = 0; up.timerAt = 0; pump('timer'); }, ms);
  }
  function trouble(kind, detail) {
    // #1476: trouble does not wait for the 30 s beat
    try {
      var t = {kind: String(kind), at: nowS(3), detail: clip(detail)};
      // the first trouble since the last batch leads; the rest ride along whole
      if (!up.trouble) up.trouble = t;
      else {
        up.trouble.more = (up.trouble.more || 0) + 1;
        up.trouble.last = String(kind);
        if (!up.trouble.also) up.trouble.also = [];
        if (up.trouble.also.length < 8) up.trouble.also.push(t);
      }
      pump('trouble');
    } catch (e) {}
  }
  function pump(why) {
    try {
      if (up.inflight) { if (why !== 'tick') up.again = true; return null; }
      var nowMs = Date.now();
      var liveDue = !!up.trouble || up.soon || why === 'force'
        || (pend.s.length + pend.e.length > 300)
        || (nowMs - up.lastLive >= (up.route404 ? 60000 : UPLOAD_MS));
      var flushDue = up.flushing && queue.length > 0;
      if (!liveDue && !flushDue) return null;
      var gap = (why === 'force') ? 0 : up.gap;
      var since = nowMs - up.lastAttempt;
      if (since < gap) { schedule(gap - since + 30); return null; }
      if (liveDue) return live();
      return flushChunk();
    } catch (e) { return null; }
  }
  function live() {
    up.soon = false;
    var b = takeRows(pend.s, pend.e, up.budget - 6144);
    if (pend.s.length || pend.e.length) up.soon = true;   // the budget left some behind
    var tr = up.trouble; up.trouble = null;
    up.lastLive = Date.now();
    return send(envelope(sid, b.s, b.e, tr, 0), b.s, b.e, null, tr);
  }
  function flushChunk() {
    var first = queue[0];
    if (!first) { up.flushing = false; return null; }
    var theSid = first.sid || sid, picked = [], used = 0, oldest = first.q || nowS();
    for (var i = 0; i < queue.length; i++) {
      var w = queue[i];
      if ((w.sid || sid) !== theSid) break;
      var z = sizeOf(w.s || w.e) + 1;
      if (used + z > up.budget - 6144 && picked.length) break;
      picked.push(w); used += z;
      if (w.q && w.q < oldest) oldest = w.q;
    }
    var s = [], e = [];
    picked.forEach(function (w) { if (w.s) s.push(w.s); else if (w.e) e.push(w.e); });
    var body = envelope(theSid, s, e, null, Math.max(0, nowS() - oldest));
    body.resent = true;
    return send(body, s, e, picked, null);
  }
  function send(body, s, e, fromQueue, tr) {
    var json = '';
    try { json = JSON.stringify(body); } catch (x) { return Promise.resolve({ok: false, error: 'stringify'}); }
    var fl = {s: s, e: e, q: fromQueue, beaconed: false};
    up.inflight = fl;
    up.lastAttempt = Date.now();
    var t0 = Date.now();
    // a page going into the background may be suspended mid-request; keepalive lets it finish
    var keep = !!document.hidden && json.length < BEACON_MAX;
    var url = '/api/car/telemetry?t=' + encodeURIComponent(tok());
    return timedPost(url, POST_MS, json, keep).then(function (r) {
      up.inflight = null;
      if (r.status === 200) return landed(r, fl, t0);
      var detail = '';
      try { var j = JSON.parse(r.text || '{}'); detail = j && j.detail ? ' - ' + String(j.detail).slice(0, 80) : ''; } catch (x) {}
      return failed(r.status, 'HTTP ' + r.status + detail, fl, tr);
    }, function (x) {
      up.inflight = null;
      return failed(0, String((x && x.message) || x || 'network'), fl, tr);
    }).then(null, function (x) {
      up.inflight = null;
      return {ok: false, error: String(x && x.message)};
    });
  }
  function landed(r, fl, t0) {
    var t1 = Date.now();
    var res = null;
    try { res = JSON.parse(r.text || 'null'); } catch (x) {}
    up.ok++; up.lastOk = t1; up.err = ''; up.status = 200; up.gap = 4500; up.route404 = false;
    up.sentRows += fl.s.length + fl.e.length;
    if (up.down) {
      var downS = round((t1 - up.down) / 1000, 0);
      logEvent('uplink', {ok: true, down_s: downS, queued: queue.length, was: up.downStatus});
      /* a station (or a link) the phone could not reach for 20 s or more is
       * the outage the drive had to ride - trouble for the next batch. A
       * missing route is a deploy, not an outage. */
      if (downS >= 20 && up.downStatus !== 404 && up.downStatus !== 405) {
        trouble('offline', {s: downS, via: 'uplink', status: up.downStatus, queued: queue.length});
      }
      up.down = 0;
    }
    if (fl.q) unqueue(fl.q);
    try { ack(res, t0, t1); } catch (x) {}
    up.flushing = queue.length > 0;
    if (up.again || up.soon || up.flushing || up.trouble) { up.again = false; schedule(up.gap); }
    try { paintBadge(); } catch (x) {}
    return {ok: true, status: 200, res: res, sent: {samples: fl.s.length, events: fl.e.length, resent: !!fl.q}};
  }
  function failed(status, err, fl, tr) {
    up.status = status; up.err = String(err).slice(0, 120);
    up.flushing = false;
    if (status === 429) {
      // too soon for this sid: put the rows back and ride the next batch
      if (!fl.q && !fl.beaconed) { pend.s = fl.s.concat(pend.s); pend.e = fl.e.concat(pend.e); }
      if (tr && !up.trouble) up.trouble = tr;
      up.gap = 5000; up.soon = true;
      schedule(5000);
      return {ok: false, status: status, error: up.err, requeued: 'pending'};
    }
    up.failed++;
    if (!fl.q && !fl.beaconed) enqueue(fl.s, fl.e, sid);
    if (status === 404 || status === 405) { up.route404 = true; up.gap = 60000; }   // not deployed: every 60 s
    else if (status === 413) { up.budget = Math.max(32768, Math.floor(up.budget / 2)); up.gap = 4500; }
    else if (status === 401 || status === 403) up.gap = 60000;
    else up.gap = 15000;
    if (!up.down) {
      up.down = Date.now();
      up.downStatus = status;
      logEvent('uplink', {ok: false, status: status, err: up.err});
    }
    if (up.again) { up.again = false; schedule(up.gap); }
    try { paintBadge(); } catch (x) {}
    return {ok: false, status: status, error: up.err, requeued: fl.q ? 'still queued' : 'queued'};
  }
  function ack(res, t0, t1) {
    /* #1476: THE STATION'S VIEW COMES BACK. Its road is the truth (the page
     * decided its own once, at load), its boot id says whether it restarted
     * under the listener, and its clock lets the two timelines line up. */
    if (!res || typeof res !== 'object') return;
    if (typeof res.server_ms === 'number') skewMs = Math.round(res.server_ms - (t0 + t1) / 2);
    if (res.addr_seen) addrSeen = String(res.addr_seen).slice(0, 80);
    if (typeof res.road_seen === 'string' && res.road_seen) applyRoad(res.road_seen, 'telemetry');
    if (res.boot_id !== undefined && res.boot_id !== null && res.boot_id !== '') applyBoot(String(res.boot_id));
    var ar = res.auto_report;
    if (ar && typeof ar === 'object' && (ar.id || ar.file)) {
      var key = String(ar.id || '') + '|' + String(ar.file || '');
      if (key !== lastAutoKey) {
        lastAutoKey = key; autoReport = {id: ar.id || null, file: ar.file || '', at: nowS()};
        logEvent('auto_report', {id: ar.id || null, file: String(ar.file || '').slice(0, 120)});
      }
    }
  }
  function applyRoad(r, via) {
    r = String(r).toLowerCase().slice(0, 20);
    var was = roadSeen;
    var pageWas = '';
    try { pageWas = String(window.PINE_ROAD || ''); } catch (e) {}
    roadSeen = r; roadSeenAt = Date.now();
    /* trouble kinds are the station's (CAR_AUTO_KINDS): road_change with
     * from/to, so its auto-report can say "Tailscale dropped at 16:02". */
    if (was === null) {
      logEvent('road', {road: r, was: pageWas || null, from: pageWas || null, to: r, first: true, addr: addrSeen || null, via: via});
      // the page was told one road at load and the station now sees another
      if (pageWas && pageWas !== r) trouble('road_change', {from: pageWas, to: r, first: true, addr: addrSeen || null});
    } else if (was !== r) {
      logEvent('road', {road: r, was: was, from: was, to: r, addr: addrSeen || null, via: via});
      trouble('road_change', {from: was, to: r, addr: addrSeen || null});
    }
    if (pageWas !== r) {
      try { window.PINE_ROAD = r; } catch (e) {}
      try {
        // the page's camera code listens for this: it picks its lane by road
        window.dispatchEvent(new CustomEvent('pine-road', {detail: {road: r, was: pageWas || null}}));
      } catch (e) {
        try {
          var ce = document.createEvent('CustomEvent');
          ce.initCustomEvent('pine-road', false, false, {road: r, was: pageWas || null});
          window.dispatchEvent(ce);
        } catch (e2) {}
      }
    }
    paintBadge();
  }
  function applyBoot(b) {
    var was = bootId || prevSession.boot || null;
    if (was && was !== b) {
      // the station restarted while this phone listened - the drive needs to know
      stationRestarts++;
      logEvent('station_restart', {was: was, now: b, from: was, to: b, across_reload: !bootId});
      trouble('station_restart', {from: was, to: b, across_reload: !bootId});
    }
    bootId = b;
    prevSession.boot = b;
    try { sessionStorage.setItem(BOOT_KEY, b); } catch (e) {}
  }
  function beacon() {
    /* #1476: the page is going away. Whatever the station has not had goes
     * in a beacon (the newest rows that fit its 64 KB); anything left, or a
     * beacon the browser refuses, waits in the queue for the next load. */
    try {
      var s = pend.s.splice(0, pend.s.length), e = pend.e.splice(0, pend.e.length);
      var fl = up.inflight;
      if (fl && !fl.q && !fl.beaconed) { fl.beaconed = true; s = fl.s.concat(s); e = fl.e.concat(e); }
      if (!s.length && !e.length) return;
      var keepE = [], keepS = [], used = 0, z, i;
      for (i = e.length - 1; i >= 0; i--) { z = sizeOf(e[i]) + 1; if (used + z > BEACON_MAX - 6144) break; keepE.unshift(e[i]); used += z; }
      for (i = s.length - 1; i >= 0; i--) { z = sizeOf(s[i]) + 1; if (used + z > BEACON_MAX - 6144) break; keepS.unshift(s[i]); used += z; }
      var restE = e.slice(0, e.length - keepE.length), restS = s.slice(0, s.length - keepS.length);
      if (up.status !== 200) {
        // a beacon is fire-and-forget: onto a missing route or a dead link it
        // would lose the rows without a word, so they wait in the queue instead
        enqueue(s, e, sid);
        return;
      }
      var tr = up.trouble; up.trouble = null;
      var body = envelope(sid, keepS, keepE, tr, 0);
      body.beacon = true;
      var json = JSON.stringify(body);
      var url = '/api/car/telemetry?t=' + encodeURIComponent(tok());
      var sent = false;
      if (navigator.sendBeacon) {
        try { sent = navigator.sendBeacon(url, new Blob([json], {type: 'application/json'})); } catch (x) { sent = false; }
        // some engines refuse a JSON-typed blob: the same bytes as text/plain
        if (!sent) { try { sent = navigator.sendBeacon(url, json); } catch (x) { sent = false; } }
      }
      if (sent) up.beacons++;
      else { restE = e; restS = s; }
      if (restE.length || restS.length) enqueue(restS, restE, sid);
    } catch (x) {}
  }
  function flush() {
    // for a console: send now (pending first, then the queue)
    try {
      if (up.inflight) return Promise.resolve({ok: false, error: 'an upload is in flight', queued: queue.length});
      var p = (pend.s.length || pend.e.length || !queue.length) ? live() : flushChunk();
      return (p || Promise.resolve({ok: false, error: 'nothing to send'})).then(function (r) {
        r = r || {};
        r.queued = queue.length; r.pending = pend.s.length + pend.e.length;
        return r;
      });
    } catch (e) { return Promise.resolve({ok: false, error: String(e && e.message)}); }
  }
  function mark(kind, detail) {
    /* #1476: the page's own facts - its reconnect loop, Tune in / Stop, and
     * the MediaSession handlers (the car's steering-wheel buttons). A
     * reconnect is trouble and goes up at once. */
    try {
      var k = String(kind || 'mark').replace(/[^\w.:-]/g, '_').slice(0, 40) || 'mark';
      var e = logEvent(k, detail === undefined ? null : detail, 'page');
      var tk = /reconn|recover|retry|give.?up/i.test(k) ? 'reconnect' : (/fail|error/i.test(k) ? 'error' : '');
      if (tk) {
        var d2 = {};
        if (e.d && typeof e.d === 'object') {
          for (var x in e.d) { if (e.d.hasOwnProperty(x)) d2[x] = e.d[x]; }
        } else if (e.d !== undefined) {
          d2.detail = e.d;
        }
        d2.mark = k;
        trouble(tk, d2);
      }
      return {t: e.t, k: e.k};
    } catch (err) { return null; }
  }

  // ---- the voice note (#1476) -------------------------------------------------
  function voicePref() { try { return localStorage.getItem(VOICE_KEY) !== '0'; } catch (e) { return true; } }
  function voiceSupported() {
    try {
      return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia
                && typeof window.MediaRecorder !== 'undefined');
    } catch (e) { return false; }
  }
  function pickMime() {
    // iOS records mp4/AAC; Chrome and Firefox record webm/opus
    var c = ['audio/mp4', 'audio/mp4;codecs=mp4a.40.2', 'audio/aac',
             'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
    try {
      if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
      for (var i = 0; i < c.length; i++) if (MediaRecorder.isTypeSupported(c[i])) return c[i];
    } catch (e) {}
    return '';
  }
  function recordNote(seconds, tick) {
    /* "I skipped the note prompt because I was driving." Eight seconds of
     * voice, only ever after a DIAG tap. The phone's audio session switches
     * to record, which can pause the stream: if it did, it is started
     * again and how long it was out is logged. */
    return new Promise(function (resolve) {
      var out = {ok: false, err: '', mime: '', seconds: 0, blob: null, paused_s: null, resumed: null};
      if (!voiceSupported()) { out.err = 'this phone cannot record here'; resolve(out); return; }
      if (micDenied) { out.err = 'microphone refused earlier - not asked again'; resolve(out); return; }
      var el = findAudio(), wasPlaying = false, pausedAt = 0, stream = null, rec = null;
      var chunks = [], t0 = 0, done = false, iv = 0, timers = [];
      try { wasPlaying = !!(el && !el.paused); } catch (e) {}
      var onPause = function () { if (!pausedAt) pausedAt = Date.now(); };
      try { if (el) el.addEventListener('pause', onPause, false); } catch (e) {}
      function stopTracks(st) {
        try { st.getTracks().forEach(function (t) { try { t.stop(); } catch (e) {} }); } catch (e) {}
      }
      function finish() {
        if (done) return;
        done = true;
        if (iv) clearInterval(iv);
        timers.forEach(function (t) { clearTimeout(t); });
        if (stream) stopTracks(stream);
        recording = false;
        setTimeout(function () {
          try { if (el) el.removeEventListener('pause', onPause, false); } catch (e) {}
          try {
            if (el && wasPlaying && el.paused && pagePlaying()) {
              var pausedFor = pausedAt ? round((Date.now() - pausedAt) / 1000, 2) : null;
              out.paused_s = pausedFor;
              out.resumed = true;
              var logIt = function (ok, err) {
                logEvent('voice_resume', {paused_s: pausedFor, ok: ok, err: err || null});
              };
              var p = null;
              try { p = el.play(); } catch (e) { logIt(false, String(e && e.message).slice(0, 80)); }
              if (p && p.then) p.then(function () { logIt(true); }, function (e) { logIt(false, String(e && e.message).slice(0, 80)); });
              else if (p !== null) logIt(true);
            } else if (el && wasPlaying) {
              out.resumed = false;
              out.paused_s = pausedAt ? 0 : null;
            }
          } catch (e) {}
          resolve(out);
        }, 400);
      }
      var gum = null;
      try { gum = navigator.mediaDevices.getUserMedia({audio: true}); }
      catch (e) { out.err = 'microphone: ' + String(e && e.message).slice(0, 80); finish(); return; }
      timers.push(setTimeout(function () {
        if (!stream) { out.err = 'no answer from the microphone prompt'; finish(); }
      }, 20000));
      recording = true;
      gum.then(function (st) {
        if (done) { stopTracks(st); return; }   // a late yes after we gave up: let go at once
        stream = st;
        var mime = pickMime();
        try { rec = mime ? new MediaRecorder(st, {mimeType: mime, audioBitsPerSecond: 64000}) : new MediaRecorder(st); }
        catch (e) {
          try { rec = new MediaRecorder(st); }
          catch (e2) { out.err = 'recorder: ' + String(e2 && e2.message).slice(0, 80); finish(); return; }
        }
        out.mime = rec.mimeType || mime || '';
        rec.ondataavailable = function (ev) { try { if (ev.data && ev.data.size) chunks.push(ev.data); } catch (e) {} };
        rec.onstop = function () {
          out.seconds = round((Date.now() - t0) / 1000, 1);
          try { out.blob = new Blob(chunks, {type: String(out.mime || 'audio/mp4').split(';')[0]}); } catch (e) {}
          out.ok = !!(out.blob && out.blob.size);
          if (!out.ok && !out.err) out.err = 'the recording came back empty';
          finish();
        };
        rec.onerror = function () {
          out.err = 'the recorder failed';
          try { if (rec.state !== 'inactive') rec.stop(); else finish(); } catch (e) { finish(); }
        };
        t0 = Date.now();
        try { rec.start(); } catch (e) { out.err = 'recorder: ' + String(e && e.message).slice(0, 80); finish(); return; }
        var left = seconds;
        try { if (tick) tick(left); } catch (e) {}
        iv = setInterval(function () {
          left--;
          if (left > 0) { try { if (tick) tick(left); } catch (e) {} return; }
          clearInterval(iv); iv = 0;
          try { if (rec.state !== 'inactive') rec.stop(); else finish(); } catch (e) { finish(); }
        }, 1000);
        // backstop: a recorder that never calls onstop still lets go of the mic
        timers.push(setTimeout(function () {
          try { if (rec.state !== 'inactive') rec.stop(); } catch (e) {}
          setTimeout(finish, 1500);
        }, seconds * 1000 + 4000));
      }, function (e) {
        var name = (e && e.name) || '';
        if (/NotAllowed|Security|PermissionDenied/i.test(name)) { micDenied = true; out.err = 'microphone refused'; }
        else if (/NotFound|DevicesNotFound/i.test(name)) out.err = 'no microphone';
        else out.err = 'microphone: ' + (name + ' ' + String((e && e.message) || '')).slice(0, 80);
        logEvent('voice_mic', {err: out.err});
        finish();
      });
    });
  }
  function blobB64(blob) {
    return new Promise(function (resolve, reject) {
      try {
        var fr = new FileReader();
        fr.onload = function () {
          var s = String(fr.result || '');
          var i = s.indexOf(',');
          resolve(i >= 0 ? s.slice(i + 1) : s);
        };
        fr.onerror = function () { reject(new Error('could not read the recording')); };
        fr.readAsDataURL(blob);
      } catch (e) { reject(e); }
    });
  }
  function sendVoice(note, res) {
    return blobB64(note.blob).then(function (b64) {
      if (b64.length > VOICE_B64_MAX) {
        return {ok: false, error: 'the note is too large to send (' + Math.round(b64.length / 1024) + ' KB)'};
      }
      var body = JSON.stringify({sid: sid, report_file: (res && res.file) || '',
                                 pine_id: (res && res.id !== undefined) ? res.id : null,
                                 mime: note.mime || (note.blob && note.blob.type) || '',
                                 seconds: note.seconds, b64: b64});
      // transcription takes a while: this one gets longer than a telemetry post
      return timedPost('/api/car/voice?t=' + encodeURIComponent(tok()), 45000, body).then(function (r) {
        var j = null;
        try { j = JSON.parse(r.text || '{}'); } catch (e) {}
        j = j || {};
        var out;
        if (r.status === 200) out = {ok: j.ok !== false, status: 200, text: String(j.text || ''), file: String(j.file || '')};
        else if (r.status === 503) out = {ok: false, saved: true, status: 503, file: String(j.file || ''), error: 'saved, not transcribed'};
        else out = {ok: false, status: r.status, error: 'HTTP ' + r.status + (j.detail ? ' - ' + String(j.detail).slice(0, 80) : '')};
        logEvent('voice_note', {status: r.status, seconds: note.seconds, kb: round(b64.length * 0.75 / 1024, 0),
                                chars: out.text ? out.text.length : 0, file: out.file || null});
        return out;
      }, function (e) {
        logEvent('voice_note', {status: 0, err: String(e && e.message).slice(0, 80)});
        return {ok: false, error: String(e && e.message)};
      });
    }, function (e) { return {ok: false, error: String(e && e.message)}; });
  }
  function voiceOutcome(v) {
    if (!v) return {state: 'err', err: 'not sent'};
    if (v.ok) return v.text ? {state: 'said', text: v.text, file: v.file} : {state: 'saved', file: v.file, why: 'nothing was heard'};
    if (v.saved) return {state: 'saved', file: v.file};
    return {state: 'err', err: 'not sent: ' + (v.error || 'no answer')};
  }
  function voiceArea(st) {
    var box = q('pcdVoice');
    if (!box) return;
    var h = '';
    if (st.state === 'recording') h = row('voice note', 'recording · ' + st.left + ' s');
    else if (st.state === 'waiting') h = row('voice note', 'waiting for the microphone…');
    else if (st.state === 'sending') h = row('voice note', 'sending…');
    else if (st.state === 'said') h = row('voice note', 'transcribed') + '<div class="pcd-said">' + esc(st.text) + '</div>';
    else if (st.state === 'saved') h = row('voice note', 'saved, not transcribed' + (st.why ? ' (' + st.why + ')' : ''))
                                      + (st.file ? '<div class="pcd-hint">' + esc(st.file) + '</div>' : '');
    else if (st.state === 'err') h = row('voice note', st.err);
    else if (st.state === 'offer') h = '<button type="button" class="pcd-btn" id="pcdSpeak">Speak a note</button>';
    box.innerHTML = h;
    var b = q('pcdSpeak');
    if (b) {
      b.addEventListener('click', function (ev) {
        try { ev.stopPropagation(); ev.preventDefault(); } catch (e) {}
        speakFromCard();
      }, false);
    }
  }
  function canOfferVoice() { return voicePref() && voiceSupported() && !micDenied; }
  function speakFromCard() {
    // out of drive mode: the card's button, a real gesture, the same 8 s
    if (recording) return;
    var res = lastResult;
    voiceArea({state: 'waiting'});
    recordNote(VOICE_S, function (n) { voiceArea({state: 'recording', left: n}); }).then(function (note) {
      if (!note.ok) { voiceArea({state: 'err', err: note.err || 'no recording'}); return null; }
      voiceArea({state: 'sending'});
      return sendVoice(note, res).then(function (v) {
        lastVoice = {seconds: note.seconds, mime: note.mime, paused_s: note.paused_s, result: v};
        voiceArea(voiceOutcome(v));
      });
    }).then(null, function (e) { recording = false; voiceArea({state: 'err', err: String(e && e.message)}); });
  }

  // ---- the overlay ----------------------------------------------------------
  function css() {
    var st = document.createElement('style');
    st.textContent = [
      '#pineCarDiag{position:fixed;right:max(12px,env(safe-area-inset-right));',
      'bottom:max(12px,env(safe-area-inset-bottom));width:64px;height:64px;border-radius:50%;',
      'background:#e6edf5;color:#04060b;border:2px solid #04060b;box-shadow:0 2px 14px rgba(0,0,0,.6);',
      'z-index:60;display:flex;flex-direction:column;align-items:center;justify-content:center;',
      'font:700 12px/1 system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:.06em;',
      'padding:0;cursor:pointer;-webkit-tap-highlight-color:transparent;touch-action:none;',
      'user-select:none;-webkit-user-select:none}',
      '#pineCarDiag.pcd-drag{opacity:.85;box-shadow:0 6px 24px rgba(0,0,0,.7)}',
      '#pineCarDiag .pcd-g{font:22px/1 PineIcons,"PineIcons";display:block;height:22px;margin-bottom:3px}',
      '#pineCarDiag .pcd-g:empty{display:none}',
      '#pineCarDiag:active{background:#c9d4e0}',
      '#pineCarDiag.busy{opacity:.55}',
      'body.car #pineCarDiag{width:80px;height:80px;font-size:15px}',
      'body.car #pineCarDiag .pcd-g{font-size:28px;height:28px}',
      /* #1476: the road badge - a Carbon-style tag: a status dot and the
       * road in capitals. Green = the private roads; amber = the Funnel. */
      '#pineCarRoad{position:fixed;left:0;top:0;z-index:60;display:none;align-items:center;gap:6px;',
      'padding:4px 10px 4px 8px;border-radius:999px;border:1px solid #24a148;background:#071f10;color:#a7f0ba;',
      'font:600 11px/1.25 system-ui,-apple-system,"Segoe UI",sans-serif;letter-spacing:.1em;white-space:nowrap;',
      'box-shadow:0 2px 10px rgba(0,0,0,.5);cursor:pointer;-webkit-tap-highlight-color:transparent;',
      'user-select:none;-webkit-user-select:none}',
      '#pineCarRoad .pcr-d{width:7px;height:7px;border-radius:50%;background:#42be65;flex:0 0 auto}',
      '#pineCarRoad.pcr-amber{border-color:#f1c21b;background:#2b2200;color:#fddc69}',
      '#pineCarRoad.pcr-amber .pcr-d{background:#f1c21b}',
      '#pineCarRoad.pcr-grey{border-color:#6f6f6f;background:#161616;color:#c6c6c6}',
      '#pineCarRoad.pcr-grey .pcr-d{background:#8d8d8d}',
      '#pineCarRoad.pcr-guess{opacity:.72;border-style:dashed}',
      '#pineCarRoad.pcr-corner{left:auto!important;top:calc(max(10px,env(safe-area-inset-top)) + 50px)!important;',
      'right:max(10px,env(safe-area-inset-right))}',
      '#pineCarRoad.pcr-stale .pcr-d{background:#8d8d8d}',
      'body.car #pineCarRoad{font-size:14px;padding:6px 13px 6px 10px}',
      'body.car #pineCarRoad .pcr-d{width:9px;height:9px}',
      '#pineCarDiagOverlay{position:fixed;left:0;top:0;right:0;bottom:0;z-index:70;',
      'background:rgba(4,6,11,.9);display:flex;align-items:center;justify-content:center;',
      'padding:max(20px,env(safe-area-inset-top)) max(20px,env(safe-area-inset-right)) ',
      'max(20px,env(safe-area-inset-bottom)) max(20px,env(safe-area-inset-left));',
      'color:#e6edf5;font:17px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}',
      '#pineCarDiagOverlay .pcd-card{max-width:560px;width:100%;background:#070b12;',
      'border:1px solid #1b2735;border-radius:14px;padding:20px 22px;max-height:92vh;overflow:auto}',
      '#pineCarDiagOverlay h2{margin:0 0 10px;font-size:20px;letter-spacing:.01em}',
      '#pineCarDiagOverlay .pcd-row{display:flex;justify-content:space-between;gap:12px;',
      'padding:6px 0;border-bottom:1px solid #121a26}',
      '#pineCarDiagOverlay .pcd-row span:last-child{font-variant-numeric:tabular-nums;text-align:right}',
      '#pineCarDiagOverlay .pcd-row.pcd-wide{flex-direction:column;gap:2px}',
      '#pineCarDiagOverlay .pcd-row.pcd-wide span:last-child{text-align:left;font-weight:600}',
      '#pineCarDiagOverlay .pcd-filed{margin-top:12px;font-weight:700}',
      '#pineCarDiagOverlay .pcd-hint{margin-top:10px;color:#7f8ea3;font-size:13px}',
      '#pineCarDiagOverlay .pcd-big{font:800 104px/1 system-ui,-apple-system,"Segoe UI",sans-serif;',
      'text-align:center;margin:18px 0 6px;font-variant-numeric:tabular-nums;color:#4bb3ff}',
      '#pineCarDiagOverlay .pcd-btn{margin-top:12px;width:100%;font:inherit;font-weight:700;padding:12px 18px;',
      'border-radius:10px;border:1px solid #4bb3ff;background:#4bb3ff;color:#04121e;cursor:pointer}',
      '#pineCarDiagOverlay .pcd-voice{margin-top:8px}',
      '#pineCarDiagOverlay .pcd-said{margin-top:8px;padding:10px 12px;border-left:3px solid #4bb3ff;',
      'background:#0b121c;border-radius:6px;white-space:pre-wrap}',
      '#pineCarDiagOverlay .pcd-warn{margin-top:10px;color:#fddc69;font-weight:600}',
      'body.car #pineCarDiagOverlay{font-size:22px}',
      'body.car #pineCarDiagOverlay h2{font-size:26px}'
    ].join('');
    document.head.appendChild(st);
  }
  var overlay = null;
  function showOverlay(html, dismissable) {
    hideOverlay();
    var mine = document.createElement('div');
    overlay = mine;
    mine.id = 'pineCarDiagOverlay';
    var cardEl = document.createElement('div');
    cardEl.className = 'pcd-card';
    cardEl.innerHTML = html;
    mine.appendChild(cardEl);
    if (dismissable) {
      // #1476: never dismissed mid-recording, and a timer only ever hides its OWN card
      mine.addEventListener('click', function () { if (!recording && overlay === mine) hideOverlay(); }, false);
      var autoHide = function () {
        if (overlay !== mine) return;
        if (recording) { setTimeout(autoHide, 10000); return; }
        hideOverlay();
      };
      setTimeout(autoHide, 60000);     // never left covering a moving car's screen
    }
    document.body.appendChild(mine);
  }
  function hideOverlay() {
    try { if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay); } catch (e) {}
    overlay = null;
  }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function row(label, value) {
    return '<div class="pcd-row"><span>' + esc(label) + '</span><span>' + esc(value) + '</span></div>';
  }
  function rowWide(label, value) {
    // a sentence-long value reads under its label, not squeezed beside it
    return '<div class="pcd-row pcd-wide"><span>' + esc(label) + '</span><span>' + esc(value) + '</span></div>';
  }
  function fmt(v, unit, p) {
    return (typeof v === 'number' && isFinite(v)) ? (round(v, p || 0) + (unit || '')) : '-';
  }
  function blackBoxLine() {
    var bits = [];
    if (up.ok) bits.push(up.ok + ' upload' + (up.ok === 1 ? '' : 's'));
    if (up.route404) bits.push('the station has no telemetry route yet');
    else if (up.status && up.status !== 200) bits.push('last: ' + (up.err || up.status));
    if (queue.length) bits.push(queue.length + ' row' + (queue.length === 1 ? '' : 's') + ' waiting on the phone');
    if (up.lastOk) bits.push('last ' + Math.round((Date.now() - up.lastOk) / 1000) + ' s ago');
    return bits.length ? bits.join(' · ') : 'nothing sent yet';
  }
  function card(report, result, err) {
    var p = report.probe || {}, n = report.now || {}, f = report.five || {};
    var lines = '<h2>Car diagnostics</h2>';
    // #1476: the station's view of the road first - the page's own can be stale
    var seen = (result && result.road_seen) || roadSeen;
    lines += row('road (station saw)', seen ? (String(seen) + (addrSeen ? ' · ' + addrSeen : '')) : 'no answer from the station yet');
    lines += row('road (page loaded on)', (ROAD0 || report.page.road) + ' · ' + report.page.mode);
    if (seen === 'funnel') lines += '<div class="pcd-warn">' + esc(FUNNEL_HINT) + '</div>';
    lines += row('round trip (median of 5)', fmt(p.rtt_med, ' ms'));
    lines += row('throughput (256 KB)', fmt(p.thru_kbps, ' kbit/s'));
    lines += row('buffer ahead', fmt(n.ahead, ' s', 1));
    lines += rowWide('last 5 min', f.line || '-');
    var L = report.load || {};
    if (L.line && L.up_s > 330) lines += rowWide('since the page loaded', L.line);
    if (f.silent_s) lines += row('silent while playing, 5 min', fmtS(f.silent_s));
    if (f.resets) lines += row('stream restarts, 5 min', String(f.resets));
    lines += row('advance ratio', fmt(f.advance, '', 2) + (typeof f.advance_min === 'number' ? ' (min ' + fmt(f.advance_min, '', 2) + ')' : ''));
    lines += row('HLS segment (median of 3)', p.seg_med_ms !== undefined && p.seg_med_ms !== null ? fmt(p.seg_med_ms, ' ms') : (p.hls_playlist && p.hls_playlist.skipped ? 'n/a' : '-'));
    var mv = report.pos && typeof report.pos.kmh === 'number' ? ('moving ' + report.pos.kmh + ' km/h')
           : (report.pos && report.pos.lat !== undefined ? ('position known, speed unknown' + (report.pos.age_s ? ' (fix ' + report.pos.age_s + ' s old)' : ''))
           : ('position: ' + ((report.pos && report.pos.err) || 'not given')));
    lines += row('movement', mv);
    lines += rowWide('black box', blackBoxLine());
    if (stationRestarts) lines += row('station restarts while listening', String(stationRestarts));
    if (result && result.station) {
      if (result.station.pulse) lines += row('station loop', result.station.pulse);
      if (typeof result.station.gaps_15m === 'number') lines += row('dead air, last 15 min', result.station.gaps_15m + ' gap(s)');
    }
    if (result && result.ok) {
      lines += '<div class="pcd-filed">Filed as Pine Box report ' + (result.id ? '#' + esc(result.id) : '(no inbox number)') + '</div>';
      if (result.file) lines += '<div class="pcd-hint">' + esc(result.file) + '</div>';
      if (result.inbox_error) lines += '<div class="pcd-hint">inbox: ' + esc(result.inbox_error) + '</div>';
    } else {
      lines += '<div class="pcd-filed">Not filed: ' + esc(err || (result && (result.detail || result.error)) || 'no answer from the station') + '</div>';
      lines += '<div class="pcd-hint">The capture is kept in this tab: PineCarDiag.last() in a console.</div>';
    }
    lines += '<div class="pcd-voice" id="pcdVoice"></div>';
    lines += '<div class="pcd-hint">tap to dismiss</div>';
    showOverlay(lines, true);
  }
  function countdown(left) {
    var a = q('pcdCount'), b = q('pcdBig');
    if (a) a.textContent = String(left);
    if (b) b.textContent = String(left);
  }

  // ---- the tap ----------------------------------------------------------------
  function parseReport(r) {
    var res = null;
    try { res = JSON.parse(r.text || '{}'); } catch (e) { res = {ok: false, error: 'the station answered ' + r.status + ' without JSON'}; }
    if (r.status !== 200 && res && !res.error) res = {ok: false, error: 'HTTP ' + r.status + (res.detail ? ' - ' + res.detail : '')};
    return res;
  }
  function capture(opts) {
    opts = opts || {};
    if (busy) return Promise.resolve(lastResult);
    busy = true;
    var btn = q('pineCarDiag');
    try { if (btn) btn.classList.add('busy'); } catch (e) {}
    var tk = tok();
    var el = findAudio();
    var startedAt = Date.now();
    var driving = carOn();
    // #1476: in the driving layout the note is spoken, never typed
    var wantVoice = driving && voicePref() && opts.note === undefined && !opts.silent;
    var probe = {rtt_ms: [], rtt_med: null, thru_kbps: null, seg: [], hls_playlist: null, errors: []};
    try { logEvent('diag_tap', {car: driving, voice: wantVoice}); } catch (e) {}
    try {
      showOverlay('<h2>Capturing… 10 s</h2><div class="pcd-hint">Round trips, a throughput fetch, the newest segment, and where the phone is.'
        + (wantVoice ? ' Then eight seconds to say what you noticed.' : ' The audio is not touched.') + '</div>', false);
    } catch (e) {}
    try { sample(); } catch (e) {}          // a fresh row at the moment of the tap
    var chain = rttProbe(probe, 5)
      .then(function () { return thruProbe(probe, tk); })
      .then(function () { return hlsProbe(probe, el, tk); });
    var geo = geoOnce(6000);
    return Promise.all([bounded(chain, 14000, 'probe'), bounded(geo, 8000, 'geo')]).then(function (got) {
      if (got[0] && got[0].timeout) probe.errors.push('probe chain hit the 14 s bound');
      var where = got[1] && !got[1].timeout ? got[1] : (pos || {err: 'no fix'});
      var note = '';
      if (opts.note !== undefined) note = String(opts.note || '');
      else if (!driving && !opts.silent) {
        try { note = String(window.prompt('What did you notice? (optional)') || ''); } catch (e) { note = ''; }
      }
      var scr = {w: 0, h: 0};
      try { scr = {w: screen.width, h: screen.height, iw: window.innerWidth, ih: window.innerHeight}; } catch (e) {}
      var report = {
        v: 1,
        at: new Date().toISOString(),
        sid: sid,                                                  // #1476
        page: {
          build: build(), road: road(), mode: mode(), host: host(),
          away: pageVar('AWAY'), ua: navigator.userAgent,
          standalone: (typeof navigator.standalone === 'boolean') ? navigator.standalone : null,
          lang: navigator.language, screen: scr, dpr: window.devicePixelRatio || 1,
          car: driving, playing: pagePlaying(), hls_native: hlsWanted(),
          up_s: round((Date.now() - loadedAt) / 1000, 0), diag: VERSION,
          conn: conn(), conn_note: conn() ? '' : 'navigator.connection absent (iOS has no Network Information API)',
          battery: battery, battery_note: battery ? '' : 'no Battery API',
          mem: (function () { try { return navigator.deviceMemory || null; } catch (e) { return null; } })(),
          counters_since_load: totals, page_state: pageCounters(),
          visibility: document.visibilityState, online: navigator.onLine,
          road_page: ROAD0, road_seen: roadSeen, addr_seen: addrSeen || null
        },
        road_seen: roadSeen,                                       // #1476: the station's view
        probe: probe,
        now: snapshot(el, true),
        five: lastFive(),                                          // #1476: corrected, this load only
        load: sinceLoad(),
        ring: ring.slice(),
        ring_restored: restored,
        events: evlog.slice(-150),                                 // #1476
        queued: queue.length,                                      // #1476: the offline queue's depth
        uploads: {ok: up.ok, failed: up.failed, last_ok: up.lastOk ? round(up.lastOk / 1000, 0) : null,
                  status: up.status, error: up.err || null, route_missing: up.route404,
                  pending: pend.s.length + pend.e.length, dropped: up.dropped},
        boot_id: bootId, station_restarts: stationRestarts, skew_ms: skewMs,
        resources_60s: resourceWindow(Date.now() - 60000, Date.now()),
        pos: where,
        note: note.slice(0, 500),
        voice_note: wantVoice ? (voiceSupported() && !micDenied ? 'recording' : 'unavailable') : null,
        took_ms: Date.now() - startedAt
      };
      lastReport = report;
      var body = '';
      try { body = JSON.stringify(report); } catch (e) { body = JSON.stringify({v: 1, at: report.at, sid: sid, err: 'stringify: ' + e.message, page: report.page, probe: probe}); }
      // the report goes now, so the station's reading is of the moment of the tap
      var postP = timedPost('/api/car/report?t=' + encodeURIComponent(tk), 20000, body)
        .then(parseReport, function (e) { return {ok: false, error: String(e && e.message), neterr: true}; });
      var voiceP = null, reportBack = false;
      postP = postP.then(function (r) { reportBack = true; return r; });
      if (wantVoice) {
        showOverlay('<h2>Say what you noticed · <span id="pcdCount">' + VOICE_S + '</span>…</h2>'
          + '<div class="pcd-big" id="pcdBig">' + VOICE_S + '</div>'
          + '<div class="pcd-hint">Eight seconds, then the card. If the phone pauses the stream to listen, it is started again.</div>', false);
        voiceP = recordNote(VOICE_S, countdown).then(function (vn) {
          if (!reportBack) { try { showOverlay('<h2>Filing the report…</h2>', false); } catch (e) {} }
          return vn;
        });
      }
      return Promise.all([postP, voiceP || Promise.resolve(null)]);
    }).then(function (pair) {
      var res = pair[0] || {ok: false, error: 'no answer'};
      var vn = pair[1];
      lastResult = res;
      try { if (res && res.road_seen) applyRoad(res.road_seen, 'report'); } catch (e) {}
      card(lastReport, res, res && res.neterr ? res.error : null);
      if (vn) {
        if (vn.ok) {
          voiceArea({state: 'sending'});
          return sendVoice(vn, res).then(function (v) {
            lastVoice = {seconds: vn.seconds, mime: vn.mime, paused_s: vn.paused_s, resumed: vn.resumed, result: v};
            voiceArea(voiceOutcome(v));
            return res;
          });
        }
        // "if the mic is denied or unsupported, skip silently and say so on the card"
        voiceArea({state: 'err', err: vn.err || 'no recording'});
      } else if (!driving && canOfferVoice()) {
        voiceArea({state: 'offer'});
      }
      return res;
    }).then(null, function (e) {
      lastResult = {ok: false, error: String(e && e.message)};
      try { card(lastReport || {page: {road: road(), mode: mode()}, probe: probe, now: snapshot(el, true), five: lastFive()}, null, String(e && e.message)); } catch (e2) { hideOverlay(); }
      return lastResult;
    }).then(function (v) {
      busy = false;
      try { if (btn) btn.classList.remove('busy'); } catch (e) {}
      up.soon = true; pump('tap');                       // the tap's events ride up promptly
      return v;
    }, function (e) {
      busy = false; recording = false;
      try { if (btn) btn.classList.remove('busy'); } catch (e2) {}
      hideOverlay();
      return {ok: false, error: String(e && e.message)};
    });
  }
  function timedPost(url, ms, body, keep) {
    return new Promise(function (resolve, reject) {
      var ac = null, done = false;
      try { if (typeof AbortController !== 'undefined') ac = new AbortController(); } catch (e) {}
      var timer = setTimeout(function () {
        if (done) return;
        done = true;
        try { if (ac) ac.abort(); } catch (e) {}
        reject(new Error('timeout after ' + ms + ' ms'));
      }, ms);
      var o = {method: 'POST', cache: 'no-store', credentials: 'same-origin',
               headers: {'Content-Type': 'application/json'}, body: body};
      if (keep) o.keepalive = true;
      if (ac) o.signal = ac.signal;
      var t0 = now();
      try {
        fetch(url, o).then(function (r) {
          return r.text().then(function (t) {
            if (done) return;
            done = true; clearTimeout(timer);
            resolve({ms: round(now() - t0, 1), status: r.status, bytes: t.length, text: t});
          });
        }, function (e) { if (done) return; done = true; clearTimeout(timer); reject(e); })
        .then(null, function (e) { if (done) return; done = true; clearTimeout(timer); reject(e); });
      } catch (e) { done = true; clearTimeout(timer); reject(e); }
    });
  }

  // ---- the button --------------------------------------------------------------
  function glyph(btn) {
    // The icon font maps the real codepoint, so the glyph is only shown once
    // PineIcons has actually loaded it: a fallback would be a colour emoji,
    // and the station draws none anywhere.
    try {
      if (!document.fonts || !document.fonts.load) return;
      document.fonts.load('22px PineIcons', GLYPH).then(function (faces) {
        try {
          var ok = false;
          (faces || []).forEach(function (f) { if (f && f.status === 'loaded') ok = true; });
          if (ok) { glyphOk = true; var g = btn.querySelector('.pcd-g'); if (g) g.textContent = GLYPH; }
        } catch (e) {}
      }, function () {});
    } catch (e) {}
  }
  /* #1471b: "allow me to drag around the diagnostics dot to place it out of
   * the way ... double tap it in order to make it go away where it only
   * shows up if I'm in full screen drive mode." A press that travels is a
   * drag and the spot is remembered; a lone tap captures (after a beat, so
   * a double tap is never two captures); a double tap hides the dot, and a
   * hidden dot comes back only while the driving layout is on. */
  var POS_KEY = 'pbfm.cardiag.pos';
  var HIDE_KEY = 'pbfm.cardiag.hidden';
  function readPos() {
    try { var p = JSON.parse(localStorage.getItem(POS_KEY) || 'null'); return (p && isFinite(p.x) && isFinite(p.y)) ? p : null; }
    catch (e) { return null; }
  }
  function place(b, p) {
    if (!b || !p) return;
    var w = b.offsetWidth || 64, h = b.offsetHeight || 64;
    var x = Math.max(0, Math.min(window.innerWidth - w, p.x));
    var y = Math.max(0, Math.min(window.innerHeight - h, p.y));
    b.style.left = x + 'px'; b.style.top = y + 'px';
    b.style.right = 'auto'; b.style.bottom = 'auto';
  }
  function hiddenPref() { try { return localStorage.getItem(HIDE_KEY) === '1'; } catch (e) { return false; } }
  function setHiddenPref(on) { try { localStorage.setItem(HIDE_KEY, on ? '1' : '0'); } catch (e) {} }
  function showRule() {
    var b = q('pineCarDiag'); if (!b) return;
    var show = carOn() || !hiddenPref();
    b.style.display = show ? '' : 'none';
    if (show) place(b, readPos());
    placeBadge();
  }
  function button() {
    if (q('pineCarDiag')) return;
    var b = document.createElement('button');
    b.id = 'pineCarDiag';
    b.type = 'button';
    b.setAttribute('aria-label', 'Capture diagnostics and file a Pine Box report');
    b.title = 'Diagnostics: tap to capture and file a report; drag to move; double-tap to hide (it returns in drive mode)';
    var g = document.createElement('span'); g.className = 'pcd-g';
    var t = document.createElement('span'); t.textContent = 'DIAG';
    b.appendChild(g); b.appendChild(t);
    var from = null, moved = false, tapAt = 0, tapTimer = 0;
    function tapped() {
      var now = Date.now();
      if (tapAt && now - tapAt < 350) {
        tapAt = 0;
        if (tapTimer) { clearTimeout(tapTimer); tapTimer = 0; }
        setHiddenPref(true);
        showRule();
        return;
      }
      tapAt = now;
      if (tapTimer) clearTimeout(tapTimer);
      tapTimer = setTimeout(function () { tapTimer = 0; tapAt = 0; capture(); }, 350);
    }
    b.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0 && ev.pointerType === 'mouse') return;
      var r = b.getBoundingClientRect();
      from = {x: ev.clientX, y: ev.clientY, left: r.left, top: r.top, id: ev.pointerId};
      moved = false;
      try { b.setPointerCapture(ev.pointerId); } catch (e) {}
      try { ev.preventDefault(); } catch (e) {}
    }, false);
    b.addEventListener('pointermove', function (ev) {
      if (!from || ev.pointerId !== from.id) return;
      var dx = ev.clientX - from.x, dy = ev.clientY - from.y;
      if (!moved && Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      if (!moved) { moved = true; b.classList.add('pcd-drag'); }
      place(b, {x: from.left + dx, y: from.top + dy});
      placeBadge();                                   // #1476: the badge travels with the dot
    }, false);
    var drop = function (ev) {
      if (!from || (ev && ev.pointerId !== from.id)) return;
      try { b.releasePointerCapture(from.id); } catch (e) {}
      var wasMoved = moved;
      from = null; moved = false;
      b.classList.remove('pcd-drag');
      if (wasMoved) {
        try { localStorage.setItem(POS_KEY, JSON.stringify({x: parseFloat(b.style.left) || 0, y: parseFloat(b.style.top) || 0})); } catch (e) {}
        placeBadge();
        return;
      }
      tapped();
    };
    b.addEventListener('pointerup', drop, false);
    b.addEventListener('pointercancel', function () { from = null; moved = false; b.classList.remove('pcd-drag'); }, false);
    /* the pointer road above is the whole gesture; the click that follows a
       tap must not capture a second time */
    b.addEventListener('click', function (ev) { try { ev.preventDefault(); } catch (e) {} }, false);
    document.body.appendChild(b);
    glyph(b);
    showRule();
    try {
      window.addEventListener('resize', function () { place(b, readPos()); placeBadge(); }, false);
      if (window.MutationObserver) {
        new MutationObserver(function (recs) {
          var cls = false, audio = false;
          for (var i = 0; i < recs.length; i++) {
            var r = recs[i];
            if (r.type === 'attributes') cls = true;
            else if (r.addedNodes) {
              for (var j = 0; j < r.addedNodes.length; j++) {
                var nd = r.addedNodes[j];
                if (nd && nd.tagName === 'AUDIO') audio = true;
              }
            }
          }
          if (cls) {
            showRule();
            if (carOn()) startWatch('drive mode');
          }
          // #1476: the stream element is created on Tune in; its first events matter
          if (audio) { try { var el = findAudio(); if (el) attach(el); } catch (e) {} }
        }).observe(document.body, {attributes: true, attributeFilter: ['class'], childList: true});
      }
    } catch (e) {}
  }

  // ---- the road badge (#1476) ------------------------------------------------------
  function badge() {
    if (q('pineCarRoad')) return;
    var b = document.createElement('div');
    b.id = 'pineCarRoad';
    b.setAttribute('role', 'status');
    var d = document.createElement('span'); d.className = 'pcr-d';
    var t = document.createElement('span'); t.className = 'pcr-t';
    b.appendChild(d); b.appendChild(t);
    b.addEventListener('click', function (ev) {
      try { ev.stopPropagation(); } catch (e) {}
      roadCard();
    }, false);
    document.body.appendChild(b);
    paintBadge();
  }
  function paintBadge() {
    var b = q('pineCarRoad');
    if (!b) return;
    var r = roadSeen || road();
    var guess = !roadSeen;
    var stale = !!roadSeen && !!up.lastOk && (Date.now() - up.lastOk > 95000);
    var cls = (r === 'funnel') ? 'pcr-amber'
            : (r === 'tailnet' || r === 'lan' || r === 'house' || r === 'loopback') ? '' : 'pcr-grey';
    if (guess) cls += ' pcr-guess';
    if (stale) cls += ' pcr-stale';
    if (b.classList.contains('pcr-corner')) cls += ' pcr-corner';
    if (b.className !== cls.replace(/^\s+/, '')) b.className = cls.replace(/^\s+/, '');
    var t = b.querySelector('.pcr-t');
    var txt = String(r || 'unknown').toUpperCase();
    if (t && t.textContent !== txt) t.textContent = txt;
    var title = (r === 'funnel') ? FUNNEL_HINT
      : guess ? 'the page\'s own guess - the station has not confirmed it yet'
      : 'the station saw this phone arrive on the ' + r + (addrSeen ? ' from ' + addrSeen : '');
    if (r === 'funnel' && guess) title += ' (the page\'s own guess)';
    if (stale) title += ' - the station has not answered for ' + Math.round((Date.now() - up.lastOk) / 1000) + ' s';
    if (b.title !== title) b.title = title;
    b.setAttribute('aria-label', 'road: ' + txt + '. ' + title);
    placeBadge();
  }
  function rectsHit(a, b) {
    return !(a.x + a.w <= b.left || b.right <= a.x || a.y + a.h <= b.top || b.bottom <= a.y);
  }
  function placeBadge() {
    /* #1476: beside the DIAG dot, shown and hidden by the dot's own rule,
     * and never over the play button: the first side of the dot that fits
     * on the glass and clears #tune / #wake wins. */
    try {
      var dot = q('pineCarDiag'), r = q('pineCarRoad');
      if (!r) return;
      var shown = !!dot && dot.style.display !== 'none';
      if (!shown) { if (r.style.display !== 'none') r.style.display = 'none'; return; }
      if (r.style.display !== 'flex') r.style.display = 'flex';
      var br = dot.getBoundingClientRect();
      var w = r.offsetWidth || 80, h = r.offsetHeight || 22;
      var W = window.innerWidth, H = window.innerHeight, m = 6;
      var avoid = [];
      ['tune', 'wake', 'carToggle'].forEach(function (id) {
        var el = q(id);
        // display:none reads as a zero box (offsetParent is null for fixed elements, so not that)
        if (el) { var rr = el.getBoundingClientRect(); if (rr.width && rr.height) avoid.push(rr); }
      });
      var cx = br.left + br.width / 2 - w / 2, cy = br.top + br.height / 2 - h / 2;
      var cands = [{x: cx, y: br.top - h - m}, {x: br.left - w - m, y: cy},
                   {x: cx, y: br.bottom + m}, {x: br.right + m, y: cy}];
      var pick = null;
      for (var i = 0; i < cands.length; i++) {
        var c = cands[i];
        var fits = c.x >= 4 && c.y >= 4 && c.x + w <= W - 4 && c.y + h <= H - 4;
        var box = {x: c.x, y: c.y, w: w, h: h};
        var clear = true;
        for (var j = 0; j < avoid.length; j++) if (rectsHit(box, avoid[j])) { clear = false; break; }
        if (fits && clear) { pick = c; break; }
      }
      if (!pick) {
        /* every side of the dot is over the play button (the driving layout
         * on a short screen): the top-right corner under the Drive toggle,
         * inset for the notch by the stylesheet's env() */
        if (!r.classList.contains('pcr-corner')) r.classList.add('pcr-corner');
        r.style.left = ''; r.style.top = '';
        return;
      }
      if (r.classList.contains('pcr-corner')) r.classList.remove('pcr-corner');
      var x = Math.max(4, Math.min(W - w - 4, pick.x)), y = Math.max(4, Math.min(H - h - 4, pick.y));
      r.style.left = Math.round(x) + 'px';
      r.style.top = Math.round(y) + 'px';
    } catch (e) {}
  }
  function roadCard() {
    if (busy || overlay) return;
    var r = roadSeen || road();
    var h = '<h2>Road: ' + esc(String(r).toUpperCase()) + '</h2>';
    h += row('the station saw', roadSeen ? roadSeen + (addrSeen ? ' · ' + addrSeen : '') : 'no answer yet');
    h += row('the page loaded on', ROAD0 || '-');
    if (r === 'funnel') h += '<div class="pcd-warn">' + esc(FUNNEL_HINT) + '</div>';
    h += row('black box', blackBoxLine());
    if (stationRestarts) h += row('station restarts while listening', String(stationRestarts));
    h += '<div class="pcd-hint">tap to dismiss</div>';
    showOverlay(h, true);
  }

  // ---- start ---------------------------------------------------------------------
  function lifecycle() {
    try {
      var session = navigator.audioSession;
      if (session && session.addEventListener) {
        session.addEventListener('statechange', function () {
          var el = findAudio();
          logEvent('audio_session', el ? mstate(el) : {
            audio_session: audioSessionState(), intent: pagePlaying(), hidden: !!document.hidden
          });
        }, false);
      }
    } catch (e) {}
    /* #1476: the page's own life is part of the drive: a phone that slept,
     * a tab iOS froze, a network that came and went. */
    try {
      document.addEventListener('visibilitychange', function () {
        var v = document.visibilityState;
        logEvent('visibilitychange', {state: v, playing: pagePlaying()});
        if (v === 'visible') { try { sample(); } catch (e) {} }   // a phone that was asleep is a phone whose timers did not run
        else { persist(); up.soon = true; pump('hidden'); }        // get it up before iOS suspends us
      }, false);
    } catch (e) {}
    try {
      window.addEventListener('pagehide', function (ev) {
        logEvent('pagehide', {persisted: !!(ev && ev.persisted)});
        beacon();
        persist();
      }, false);
      window.addEventListener('pageshow', function (ev) {
        if (ev && ev.persisted) { logEvent('pageshow', {persisted: true}); up.soon = true; pump('pageshow'); }
      }, false);
    } catch (e) {}
    try {
      // named page_* so nobody reads them as a playhead freeze
      document.addEventListener('freeze', function () { logEvent('page_freeze', null); persist(); }, false);
      document.addEventListener('resume', function () { logEvent('page_resume', null); }, false);
    } catch (e) {}
    try {
      window.addEventListener('offline', function () { offlineAt = Date.now(); logEvent('offline', null); }, false);
      window.addEventListener('online', function () {
        var gone = offlineAt ? round((Date.now() - offlineAt) / 1000, 1) : null;
        offlineAt = 0;
        logEvent('online', {offline_s: gone});
        if (!up.route404) up.gap = Math.min(up.gap, 4500);
        // offline -> online: the station hears about the hole at once
        trouble('offline', {s: gone, back: true});
      }, false);
    } catch (e) {}
  }
  function tick() {
    try { sample(); } catch (e) {}
    try { rttTick(); } catch (e) {}
    try { paintBadge(); } catch (e) {}
    try { pump('tick'); } catch (e) {}
  }
  function start() {
    try { css(); } catch (e) {}
    try { restore(); } catch (e) {}
    try { loadQueue(); } catch (e) {}
    try { observing = watchResources(); } catch (e) {}
    try { watchBattery(); } catch (e) {}
    try { button(); } catch (e) {}
    try { badge(); } catch (e) {}
    try { lifecycle(); } catch (e) {}
    try { if (carOn()) startWatch('drive mode'); } catch (e) {}
    try { sample(); } catch (e) {}
    setInterval(tick, SAMPLE_MS);
    // the first batch goes early, so the badge learns the station's road within seconds
    setTimeout(function () { try { up.soon = true; pump('first'); } catch (e) {} }, 2500);
  }

  window.PineCarDiag = {
    version: VERSION,
    state: function () {
      return {version: VERSION, sid: sid, prev_sid: prevSession.sid,
              ring: ring.slice(), totals: totals, restored: restored, pos: pos, battery: battery,
              attached: !!attached, mode: mode(), road: road(), road_page: ROAD0,
              road_seen: roadSeen, addr_seen: addrSeen || null, boot_id: bootId,
              road_seen_age_s: roadSeenAt ? round((Date.now() - roadSeenAt) / 1000, 0) : null,
              station_restarts: stationRestarts, skew_ms: skewMs, auto_report: autoReport,
              five: lastFive(), load: sinceLoad(),
              resources_60s: resourceWindow(Date.now() - 60000, Date.now()),
              glyph: glyphOk, up_s: round((Date.now() - loadedAt) / 1000, 0),
              events_n: evlog.length, events_total: evTotal,
              queued: queue.length, pending: pend.s.length + pend.e.length,
              uploads_ok: up.ok, uploads_failed: up.failed,
              last_upload_at: up.lastOk ? new Date(up.lastOk).toISOString() : null,
              last_status: up.status, last_error: up.err || null, route_missing: up.route404,
              next_gap_ms: up.gap, dropped: up.dropped, beacons: up.beacons,
              stalls: totals.stall, stall_s: round(totals.stall_s, 1),
              freezes: totals.freeze, freeze_s: round(totals.freeze_s, 1),
              idle_stalled: totals.idle_stalled,
              stalling: media.episode ? {startup: media.episode.startup, s: round((Date.now() - media.episode.t0) / 1000, 1)} : null,
              geo: {watching: watchId !== null, refused: geoNo},
              voice: {on: voicePref(), supported: voiceSupported(), mic_refused: micDenied, recording: recording}};
    },
    capture: capture,
    /* #1471b: the dot's own state, and a way to bring it back from a console. */
    dot: function (show) {
      if (show !== undefined) { setHiddenPref(!show); showRule(); }
      var b = q('pineCarDiag');
      return {hidden: hiddenPref(), shown: !!(b && b.style.display !== 'none'), pos: readPos(), car: carOn()};
    },
    sample: function () { sample(); return ring[ring.length - 1]; },
    last: function () { return {report: lastReport, result: lastResult, voice: lastVoice}; },
    /* #1476 */
    mark: mark,
    flush: flush,
    events: function (n) { return evlog.slice(-(n || EV_MAX)); },
    queue: function () { return {rows: queue.length, oldest_q: queue.length ? queue[0].q : null, sids: queue.reduce(function (a, w) { if (a.indexOf(w.sid) < 0) a.push(w.sid); return a; }, [])}; },
    voice: function (on) {
      if (on !== undefined) {
        var v = !(on === false || on === 0 || on === 'off' || on === '0');
        try { localStorage.setItem(VOICE_KEY, v ? '1' : '0'); } catch (e) {}
      }
      return {on: voicePref(), supported: voiceSupported(), mic_refused: micDenied};
    }
  };

  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start, false);
})();
