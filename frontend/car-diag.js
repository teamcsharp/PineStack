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
 * Plain ES5 on purpose: no build step, and it has to run in the WebView
 * of whatever phone is in the holder. Every browser API is behind a
 * try/catch; nothing here may ever touch the audio element's playback,
 * and nothing here ever reloads the page. The page's own state is READ,
 * never duplicated: the stream element is the one stamped
 * data-pine-live="stream", the road flags and reconnect counters are the
 * page's top-level bindings (let/const, so not window properties - read
 * through an indirect eval that returns undefined when they are absent).
 */
(function () {
  'use strict';
  if (window.PineCarDiag) return;

  var VERSION = '1471.1';
  var RING_MAX = 120;               // 120 x 5 s = ten minutes
  var SAMPLE_MS = 5000;
  var STORE_KEY = 'pbfm.cardiag.ring';
  var RES_KEEP_MS = 15 * 60 * 1000;
  var GLYPH = '🩺';       // U+1FA7A stethoscope -> c:stethoscope in PineIcons

  var loadedAt = Date.now();
  var ring = [];
  var restored = 0;
  var fresh = function () {
    return {waiting: 0, stalled: 0, playing: 0, error: 0, seeking: 0,
            pause: 0, play: 0, ended: 0, emptied: 0, srcchange: 0};
  };
  var counters = fresh();           // since the last sample
  var totals = fresh();             // since page load
  var attached = null;              // the element the listeners are on
  var lastSrc = '';
  var last = {t: 0, ct: 0};         // for the advance ratio
  var resources = [];               // {k, s, e, d, b}
  var pos = null;
  var watchId = null;
  var battery = null;
  var busy = false;
  var lastReport = null;
  var lastResult = null;
  var glyphOk = false;

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
     * fallback for a page served without it. */
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
    try { if (typeof window.wantsHls === 'function') return !!window.wantsHls(); } catch (e) {}
    try {
      var p = document.createElement('audio');
      return !!(p.canPlayType && p.canPlayType('application/vnd.apple.mpegurl'));
    } catch (e) { return false; }
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
  function attach(el) {
    if (!el || attached === el) return;
    var names = ['waiting', 'stalled', 'playing', 'error', 'seeking', 'pause', 'play', 'ended', 'emptied'];
    names.forEach(function (n) {
      try {
        el.addEventListener(n, function () { counters[n]++; totals[n]++; }, false);
      } catch (e) {}
    });
    attached = el;
    try { lastSrc = el.currentSrc || el.src || ''; } catch (e) {}
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
  function startWatch() {
    if (watchId !== null) return;
    try {
      watchId = navigator.geolocation.watchPosition(function (p) {
        pos = posOf(p);
      }, function () {}, {enableHighAccuracy: false, maximumAge: 15000, timeout: 20000});
    } catch (e) { watchId = null; }
  }
  function geoOnce(ms) {
    return new Promise(function (resolve) {
      var done = false;
      var finish = function (v) { if (!done) { done = true; resolve(v); } };
      try {
        if (!navigator.geolocation) return finish({err: 'no geolocation API'});
        setTimeout(function () { finish({err: 'no fix within ' + ms + ' ms'}); }, ms + 800);
        navigator.geolocation.getCurrentPosition(function (p) {
          pos = posOf(p);
          startWatch();                     // later samples carry pos
          finish(pos);
        }, function (e) {
          finish({err: (e && e.message) || 'denied', code: e && e.code});
        }, {timeout: ms, enableHighAccuracy: false, maximumAge: 30000});
      } catch (e) { finish({err: 'geolocation threw: ' + (e && e.message)}); }
    });
  }

  // ---- the ring -----------------------------------------------------------
  function persist() {
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify(ring)); } catch (e) {}
  }
  function restore() {
    try {
      var raw = sessionStorage.getItem(STORE_KEY);
      var got = raw ? JSON.parse(raw) : null;
      if (got && got.length) {
        ring = got.slice(-RING_MAX);
        restored = ring.length;
        // the reload itself is a fact worth a row
        ring.push({t: Math.round(Date.now() / 1000), reload: true, road: road()});
      }
    } catch (e) { ring = []; }
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
      try {
        var src = el.currentSrc || el.src || '';
        if (src !== lastSrc) { counters.srcchange++; totals.srcchange++; lastSrc = src; }
      } catch (e) {}
      var ct = Number(el.currentTime || 0);
      if (last.t && !el.paused) {
        var dw = (now - last.t) / 1000;
        if (ct < last.ct - 0.5) s.reset = true;        // a new src restarted the clock
        else if (dw > 0) s.adv = round((ct - last.ct) / dw, 3);
      }
      last = {t: now, ct: ct};
    } else {
      last = {t: 0, ct: 0};
    }
    s.ev = counters; counters = fresh();
    var c = conn(); if (c) s.conn = c;
    if (battery) s.bat = battery;
    try { if (navigator.deviceMemory) s.mem = navigator.deviceMemory; } catch (e) {}
    s.res = resourceWindow(now - SAMPLE_MS, now);
    if (pos) s.pos = pos;
    var pc = pageCounters(); if (pc.tries !== undefined || pc.stuck_s !== undefined) s.pg = pc;
    ring.push(s);
    if (ring.length > RING_MAX) ring.splice(0, ring.length - RING_MAX);
    persist();
  }
  function lastFive() {
    // the card's numbers: the last 60 samples (five minutes)
    var rows = ring.slice(-60);
    var stalls = 0, advs = [], n = 0, resets = 0, errs = 0;
    rows.forEach(function (r) {
      if (r.reload) return;
      n++;
      var ev = r.ev || {};
      stalls += (ev.waiting || 0) + (ev.stalled || 0);
      errs += (ev.error || 0);
      if (r.reset) resets++;
      if (typeof r.adv === 'number') advs.push(r.adv);
    });
    var mean = advs.length ? advs.reduce(function (a, b) { return a + b; }, 0) / advs.length : null;
    return {samples: n, stalls: stalls, errors: errs, resets: resets,
            advance: round(mean, 3), advance_min: advs.length ? round(Math.min.apply(null, advs), 3) : null};
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
  function thruProbe(probe, tok) {
    return timed('/api/car/blob?kb=256&t=' + encodeURIComponent(tok) + '&_=' + Date.now(), 8000)
      .then(function (r) {
        probe.thru_bytes = r.bytes; probe.thru_ms = r.ms; probe.thru_status = r.status;
        probe.thru_kbps = (r.ms > 0 && r.status === 200) ? round(r.bytes * 8 / r.ms, 0) : null;
      }, function (e) { probe.thru_kbps = null; probe.errors.push('throughput: ' + (e && e.message)); });
  }
  function playlistUrl(el, tok) {
    // THE SAME URL THE PLAYER USES, so the station answers from the encoder
    // it already runs for this listener instead of starting another one.
    try {
      var src = el && (el.currentSrc || el.src);
      if (src && src.indexOf('.m3u8') >= 0) return src;
    } catch (e) {}
    try { if (typeof window.streamUrl === 'function') { var u = window.streamUrl(); if (u.indexOf('.m3u8') >= 0) return u; } } catch (e) {}
    return '/stream.m3u8?t=' + encodeURIComponent(tok);
  }
  function hlsProbe(probe, el, tok) {
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
    var url = playlistUrl(el, tok);
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
      '#pineCarDiagOverlay .pcd-filed{margin-top:12px;font-weight:700}',
      '#pineCarDiagOverlay .pcd-hint{margin-top:10px;color:#7f8ea3;font-size:13px}',
      'body.car #pineCarDiagOverlay{font-size:22px}',
      'body.car #pineCarDiagOverlay h2{font-size:26px}'
    ].join('');
    document.head.appendChild(st);
  }
  var overlay = null;
  function showOverlay(html, dismissable) {
    hideOverlay();
    overlay = document.createElement('div');
    overlay.id = 'pineCarDiagOverlay';
    var card = document.createElement('div');
    card.className = 'pcd-card';
    card.innerHTML = html;
    overlay.appendChild(card);
    if (dismissable) {
      overlay.addEventListener('click', hideOverlay, false);
      setTimeout(hideOverlay, 60000);     // never left covering a moving car's screen
    }
    document.body.appendChild(overlay);
  }
  function hideOverlay() {
    try { if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay); } catch (e) {}
    overlay = null;
  }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function row(label, value) {
    return '<div class="pcd-row"><span>' + esc(label) + '</span><span>' + esc(value) + '</span></div>';
  }
  function fmt(v, unit, p) {
    return (typeof v === 'number' && isFinite(v)) ? (round(v, p || 0) + (unit || '')) : '-';
  }
  function card(report, result, err) {
    var p = report.probe || {}, n = report.now || {}, f = report.five || {};
    var lines = '<h2>Car diagnostics</h2>';
    lines += row('road', report.page.road + ' · ' + report.page.mode);
    if (result && result.road_seen) lines += row('road (station saw)', esc(String(result.road_seen)));   /* #1475 */
    lines += row('round trip (median of 5)', fmt(p.rtt_med, ' ms'));
    lines += row('throughput (256 KB)', fmt(p.thru_kbps, ' kbit/s'));
    lines += row('buffer ahead', fmt(n.ahead, ' s', 1));
    lines += row('stalls, last 5 min', (f.stalls === undefined ? '-' : f.stalls) + (f.resets ? ' (+' + f.resets + ' restarts)' : ''));
    lines += row('advance ratio', fmt(f.advance, '', 2) + (typeof f.advance_min === 'number' ? ' (min ' + fmt(f.advance_min, '', 2) + ')' : ''));
    lines += row('HLS segment (median of 3)', p.seg_med_ms !== undefined && p.seg_med_ms !== null ? fmt(p.seg_med_ms, ' ms') : (p.hls_playlist && p.hls_playlist.skipped ? 'n/a' : '-'));
    var mv = report.pos && typeof report.pos.kmh === 'number' ? ('moving ' + report.pos.kmh + ' km/h')
           : (report.pos && report.pos.lat !== undefined ? 'position known, speed unknown'
           : ('position: ' + ((report.pos && report.pos.err) || 'not given')));
    lines += row('movement', mv);
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
    lines += '<div class="pcd-hint">tap to dismiss</div>';
    showOverlay(lines, true);
  }

  // ---- the tap ----------------------------------------------------------------
  function capture(opts) {
    opts = opts || {};
    if (busy) return Promise.resolve(lastResult);
    busy = true;
    var btn = q('pineCarDiag'); if (btn) btn.className = 'busy';
    var tok = token();
    var el = findAudio();
    var startedAt = Date.now();
    var probe = {rtt_ms: [], rtt_med: null, thru_kbps: null, seg: [], hls_playlist: null, errors: []};
    try { showOverlay('<h2>Capturing… 10 s</h2><div class="pcd-hint">Round trips, a throughput fetch, the newest segment, and where the phone is. The audio is not touched.</div>', false); } catch (e) {}
    try { sample(); } catch (e) {}          // a fresh row at the moment of the tap
    var chain = rttProbe(probe, 5)
      .then(function () { return thruProbe(probe, tok); })
      .then(function () { return hlsProbe(probe, el, tok); });
    var geo = geoOnce(6000);
    return Promise.all([bounded(chain, 14000, 'probe'), bounded(geo, 8000, 'geo')]).then(function (got) {
      if (got[0] && got[0].timeout) probe.errors.push('probe chain hit the 14 s bound');
      var where = got[1] && !got[1].timeout ? got[1] : (pos || {err: 'no fix'});
      var note = '';
      if (opts.note !== undefined) note = String(opts.note || '');
      else if (!carOn() && !opts.silent) {
        try { note = String(window.prompt('What did you notice? (optional)') || ''); } catch (e) { note = ''; }
      }
      var scr = {w: 0, h: 0};
      try { scr = {w: screen.width, h: screen.height, iw: window.innerWidth, ih: window.innerHeight}; } catch (e) {}
      var report = {
        v: 1,
        at: new Date().toISOString(),
        page: {
          build: build(), road: road(), mode: mode(), host: (function () { try { return location.host; } catch (e) { return ''; } })(),
          away: pageVar('AWAY'), ua: navigator.userAgent,
          standalone: (typeof navigator.standalone === 'boolean') ? navigator.standalone : null,
          lang: navigator.language, screen: scr, dpr: window.devicePixelRatio || 1,
          car: carOn(), playing: pagePlaying(), hls_native: hlsWanted(),
          up_s: round((Date.now() - loadedAt) / 1000, 0), diag: VERSION,
          conn: conn(), conn_note: conn() ? '' : 'navigator.connection absent (iOS has no Network Information API)',
          battery: battery, battery_note: battery ? '' : 'no Battery API',
          mem: (function () { try { return navigator.deviceMemory || null; } catch (e) { return null; } })(),
          counters_since_load: totals, page_state: pageCounters(),
          visibility: document.visibilityState, online: navigator.onLine
        },
        probe: probe,
        now: snapshot(el, true),
        five: lastFive(),
        ring: ring.slice(),
        ring_restored: restored,
        resources_60s: resourceWindow(Date.now() - 60000, Date.now()),
        pos: where,
        note: note.slice(0, 500),
        took_ms: Date.now() - startedAt
      };
      lastReport = report;
      var body = '';
      try { body = JSON.stringify(report); } catch (e) { body = JSON.stringify({v: 1, at: report.at, err: 'stringify: ' + e.message, page: report.page, probe: probe}); }
      return timedPost('/api/car/report?t=' + encodeURIComponent(tok), 20000, body);
    }).then(function (r) {
      var res = null;
      try { res = JSON.parse(r.text || '{}'); } catch (e) { res = {ok: false, error: 'the station answered ' + r.status + ' without JSON'}; }
      if (r.status !== 200 && res && !res.error) res = {ok: false, error: 'HTTP ' + r.status + (res.detail ? ' - ' + res.detail : '')};
      lastResult = res;
      card(lastReport, res, null);
      return res;
    }, function (e) {
      lastResult = {ok: false, error: String(e && e.message)};
      try { card(lastReport || {page: {road: road(), mode: mode()}, probe: probe, now: snapshot(el, true), five: lastFive()}, null, String(e && e.message)); } catch (e2) { hideOverlay(); }
      return lastResult;
    }).then(function (v) {
      busy = false; if (btn) btn.className = '';
      return v;
    }, function (e) {
      busy = false; if (btn) btn.className = '';
      hideOverlay();
      return {ok: false, error: String(e && e.message)};
    });
  }
  function timedPost(url, ms, body) {
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
    }, false);
    var drop = function (ev) {
      if (!from || (ev && ev.pointerId !== from.id)) return;
      try { b.releasePointerCapture(from.id); } catch (e) {}
      var wasMoved = moved;
      from = null; moved = false;
      b.classList.remove('pcd-drag');
      if (wasMoved) {
        try { localStorage.setItem(POS_KEY, JSON.stringify({x: parseFloat(b.style.left) || 0, y: parseFloat(b.style.top) || 0})); } catch (e) {}
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
      window.addEventListener('resize', function () { place(b, readPos()); }, false);
      if (window.MutationObserver) {
        new MutationObserver(showRule).observe(document.body, {attributes: true, attributeFilter: ['class']});
      }
    } catch (e) {}
  }

  // ---- start ---------------------------------------------------------------------
  function start() {
    try { css(); } catch (e) {}
    try { restore(); } catch (e) {}
    try { observing = watchResources(); } catch (e) {}
    try { watchBattery(); } catch (e) {}
    try { button(); } catch (e) {}
    try { sample(); } catch (e) {}
    setInterval(function () { try { sample(); } catch (e) {} }, SAMPLE_MS);
    try {
      document.addEventListener('visibilitychange', function () {
        // a phone that was asleep is a phone whose timers did not run
        if (document.visibilityState === 'visible') { try { sample(); } catch (e) {} }
      }, false);
    } catch (e) {}
  }

  window.PineCarDiag = {
    version: VERSION,
    state: function () {
      return {ring: ring.slice(), totals: totals, restored: restored, pos: pos, battery: battery,
              attached: !!attached, mode: mode(), road: road(), five: lastFive(),
              resources_60s: resourceWindow(Date.now() - 60000, Date.now()),
              glyph: glyphOk, up_s: round((Date.now() - loadedAt) / 1000, 0)};
    },
    capture: capture,
    /* #1471b: the dot's own state, and a way to bring it back from a console. */
    dot: function (show) {
      if (show !== undefined) { setHiddenPref(!show); showRule(); }
      var b = q('pineCarDiag');
      return {hidden: hiddenPref(), shown: !!(b && b.style.display !== 'none'), pos: readPos(), car: carOn()};
    },
    sample: function () { sample(); return ring[ring.length - 1]; },
    last: function () { return {report: lastReport, result: lastResult}; }
  };

  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start, false);
})();
