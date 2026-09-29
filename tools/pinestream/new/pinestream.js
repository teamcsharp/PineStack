/* PINESTREAM - THIS SCREEN, ON THE LISTENERS' PAGE.  [pinestream]
 *
 * "add a section here for enabling a pip stream of the pinetab / pineapp to be
 *  streamed to the stream page. I want users able to enable and disable it at
 *  will like the pinecam and call it pinestream."        (operator, 2026-09-29)
 *
 * The switch and the source live in PineLive (pinelive.js, the header's
 * PineStream switch); the station holds the one frame (pinestream.py). This
 * file is the screen's own half, the same file on both screens:
 *
 *   the PineTab (the kiosk injects it from pine-views; the capture is native,
 *     PineStreamPush.kt, a VirtualDisplay mirror - no MediaProjection prompt)
 *   the Pine app (index.html; the capture is Electron's main process,
 *     pinestream-push.cjs, webContents.capturePage)
 *
 * WHAT IT DOES, every few seconds, and nothing else:
 *   1. asks the station whether PineStream is on and which screen it shows;
 *   2. when it is THIS screen: says `run` to the native pusher (which is also
 *      the dead man's handle - the pusher stops by itself if `run` stops
 *      coming), with the rate, the width, the quality and whether the screen
 *      is private right now; and puts up the red "LIVE to listeners" badge
 *      with a stop button, so the operator can never forget this screen is
 *      being watched;
 *   3. otherwise: says `stop` once, and takes the badge down.
 * The station is the master either way: every frame's answer can stop the
 * pusher, and while the switch is off nothing is captured or served.
 *
 * PRIVATE: a password field that is really on the glass (not covered, not
 * display:none) or anything marked [data-pine-private] veils the picture -
 * the pusher sends no pixels and listeners read "private screen". On the desk
 * the station panel is a <webview>, so it is asked the same question inside.
 *
 * Nothing here scrolls anything, and nothing runs on a screen that is neither
 * the tablet nor the desk (a browser tab on the panel does no work at all).
 */
(function (root) {
  'use strict';
  if (!root || !root.document || root.PineStream) return;

  var POLL_OFF_MS = 6000;
  var POLL_ON_MS = 3000;
  var POLL_ERR_MS = 15000;
  var PROBE_MS = 1500;

  var doc = root.document;
  var state = {surface: '', on: false, mine: false, running: false, info: null,
    privateWhy: '', lastError: '', badge: null, timer: 0, polls: 0, pushed: null};

  function surface() {
    try { if (root.__pineNative) return 'pinetab'; } catch (err) { /* not the kiosk */ }
    try {
      var b = root.pineDesktop;
      var ua = String((root.navigator && root.navigator.userAgent) || '');
      if (b && typeof b.pineStream === 'function' && /Electron/.test(ua)) return 'pineapp';
    } catch (err) { /* not the desk */ }
    return '';
  }

  function bridge() {
    var b = root.pineDesktop;
    return b && typeof b.get === 'function' ? b : null;
  }

  function icon(name) {
    try { return typeof root.pineIcon === 'function' ? (root.pineIcon(name) || '') : ''; } catch (err) { return ''; }
  }

  /* ------------------------------------------------------------ private? */

  /** Why this document must not be streamed right now, or ''. Serialised and
   *  run inside the desk's webviews too, so it uses nothing from outside. */
  function privateReason(d) {
    var w = d.defaultView || window;
    var vw = w.innerWidth || 0, vh = w.innerHeight || 0;
    function onGlass(n) {
      if (!n || n.hidden || !n.isConnected) return false;
      var r = n.getBoundingClientRect();
      if (!(r.width > 2 && r.height > 2) || r.right <= 0 || r.bottom <= 0 || r.left >= vw || r.top >= vh) return false;
      var cs = w.getComputedStyle(n);
      if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) return false;
      var x = Math.min(vw - 1, Math.max(0, r.left + r.width / 2));
      var y = Math.min(vh - 1, Math.max(0, r.top + r.height / 2));
      var top = d.elementFromPoint(x, y);
      return !!top && (top === n || n.contains(top) || top.contains(n));
    }
    var keys = d.querySelectorAll('input[type="password"]');
    for (var i = 0; i < keys.length; i += 1) if (onGlass(keys[i])) return 'a key field is on the screen';
    var marked = d.querySelectorAll('[data-pine-private]');
    for (var j = 0; j < marked.length; j += 1) {
      if (onGlass(marked[j])) return String(marked[j].getAttribute('data-pine-private') || 'a private panel is on the screen');
    }
    return '';
  }

  function withTimeout(p, ms) {
    return new Promise(function (resolve) {
      var done = false;
      var t = root.setTimeout(function () { if (!done) { done = true; resolve(''); } }, ms);
      Promise.resolve(p).then(function (v) { if (!done) { done = true; root.clearTimeout(t); resolve(v); } },
        function () { if (!done) { done = true; root.clearTimeout(t); resolve(''); } });
    });
  }

  function privateNow() {
    var here = '';
    try { here = privateReason(doc); } catch (err) { here = ''; }
    if (here || state.surface !== 'pineapp') return Promise.resolve(here);
    /* the desk: the panel and the other pages are <webview>s */
    var views = [];
    try { views = Array.prototype.slice.call(doc.querySelectorAll('webview')); } catch (err) { views = []; }
    var code = '(' + privateReason.toString() + ')(document)';
    var asks = views.filter(function (v) {
      var r = v.getBoundingClientRect();
      return r.width > 2 && r.height > 2 && typeof v.executeJavaScript === 'function';
    }).map(function (v) {
      try { return withTimeout(v.executeJavaScript(code), PROBE_MS); } catch (err) { return Promise.resolve(''); }
    });
    return Promise.all(asks).then(function (got) {
      for (var i = 0; i < got.length; i += 1) if (got[i]) return String(got[i]);
      return '';
    });
  }

  /* ------------------------------------------------------------ the badge */

  function badge() {
    if (state.badge) return state.badge;
    if (!doc.getElementById('pineStreamStyle')) {
      var s = doc.createElement('style');
      s.id = 'pineStreamStyle';
      s.textContent = [
        /* bottom left, above the console line: clear of every popup's header
         * and its switches; only the stop button takes a tap */
        '#pineStreamBadge{position:fixed;left:12px;bottom:36px;z-index:2147483300;pointer-events:none;',
        'display:flex;align-items:center;gap:8px;height:32px;padding:0 4px 0 12px;border-radius:16px;',
        'background:#b3261e;color:#fff;font:700 12px/1 system-ui,Segoe UI,sans-serif;letter-spacing:.02em;',
        'box-shadow:0 4px 16px rgba(0,0,0,.45);border:1px solid #ff8a80;white-space:nowrap;user-select:none}',
        '#pineStreamBadge[hidden]{display:none}',
        '#pineStreamBadge.private{background:#6b4a12;border-color:#e3be63}',
        '#pineStreamBadge .psb-dot{display:inline-flex;animation:psbPulse 1.6s ease-in-out infinite}',
        '#pineStreamBadge .psb-dot svg{width:10px;height:10px;fill:currentColor}',
        '#pineStreamBadge .psb-words{font-weight:600;opacity:.92}',
        '#pineStreamBadge button{pointer-events:auto;width:26px;height:26px;border-radius:13px;border:1px solid rgba(255,255,255,.45);',
        'background:rgba(0,0,0,.25);color:#fff;display:inline-flex;align-items:center;justify-content:center;',
        'padding:0;cursor:pointer}',
        '#pineStreamBadge button svg{width:14px;height:14px;fill:currentColor}',
        '@keyframes psbPulse{0%,100%{opacity:1}50%{opacity:.35}}',
        '@media (prefers-reduced-motion:reduce){#pineStreamBadge .psb-dot{animation:none}}'
      ].join('');
      (doc.head || doc.documentElement).appendChild(s);
    }
    var b = doc.createElement('div');
    b.id = 'pineStreamBadge';
    b.setAttribute('role', 'status');
    b.hidden = true;
    var dot = doc.createElement('span');
    dot.className = 'psb-dot';
    dot.innerHTML = icon('c:circle--filled');
    var head = doc.createElement('span');
    head.textContent = 'LIVE to listeners';
    var words = doc.createElement('span');
    words.className = 'psb-words';
    var stop = doc.createElement('button');
    stop.type = 'button';
    stop.title = 'Stop PineStream now - listeners stop seeing this screen';
    stop.setAttribute('aria-label', stop.title);
    stop.innerHTML = icon('c:stop--filled') || '<b>&#9632;</b>';
    stop.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      stopNow();
    });
    b.appendChild(dot);
    b.appendChild(head);
    b.appendChild(words);
    b.appendChild(stop);
    (doc.body || doc.documentElement).appendChild(b);
    state.badge = {root: b, words: words};
    return state.badge;
  }

  function paintBadge() {
    var show = state.mine && state.on;
    if (!show && !state.badge) return;
    var bd = badge();
    if (bd.root.hidden !== !show) bd.root.hidden = !show;
    if (!show) return;
    var info = state.info || {};
    var bits = ['PineStream'];
    if (state.privateWhy) bits.push('veiled: ' + state.privateWhy);
    else if (isFinite(Number(info.watching))) bits.push(Number(info.watching) + ' watching');
    var text = '· ' + bits.join(' · ');
    if (bd.words.textContent !== text) bd.words.textContent = text;
    bd.root.classList.toggle('private', !!state.privateWhy);
    bd.root.title = 'This screen is being shown to listeners on the stream page (PineStream, '
      + (info.fps || 2) + ' a second). The stop button switches it off for everyone.';
  }

  /* ------------------------------------------------------------ the roads */

  function native(verb, opts) {
    try {
      var b = root.pineDesktop;
      if (b && typeof b.pineStream === 'function') return Promise.resolve(b.pineStream(verb, opts || {}));
    } catch (err) { return Promise.reject(err); }
    return Promise.reject(new Error('no PineStream road on this screen'));
  }

  function stopNow() {
    var b = bridge();
    state.on = false;
    paintBadge();
    native('stop', {why: 'stopped from the LIVE badge'}).catch(function () { /* the station stops it anyway */ });
    if (b && typeof b.post === 'function') {
      Promise.resolve(b.post('/api/pinelive/settings', {stream_on: false})).then(function () { schedule(300); },
        function (err) { state.lastError = String((err && err.message) || err); schedule(1000); });
    }
  }

  function schedule(ms) {
    if (state.timer) root.clearTimeout(state.timer);
    state.timer = root.setTimeout(poll, ms);
  }

  function poll() {
    state.timer = 0;
    var b = bridge();
    if (!b) { schedule(POLL_ERR_MS); return; }
    state.polls += 1;
    Promise.resolve(b.get('/api/pinestream/state')).then(function (info) {
      info = info || {};
      state.info = info;
      state.lastError = '';
      state.on = !!info.on;
      state.mine = state.on && info.source === state.surface;
      if (!state.mine) {
        state.privateWhy = '';
        paintBadge();
        if (state.running) {
          state.running = false;
          native('stop', {why: state.on ? 'another screen is streaming' : 'PineStream is off'}).catch(function () {});
        }
        schedule(POLL_OFF_MS);
        return;
      }
      return privateNow().then(function (why) {
        state.privateWhy = why || '';
        paintBadge();
        var opts = {fps: info.fps, width: info.width, quality: info.quality,
          private: !!state.privateWhy, why: state.privateWhy};
        return native('run', opts).then(function (got) {
          state.running = true;
          state.pushed = got || null;
        }, function (err) {
          state.lastError = String((err && err.message) || err);
        }).then(function () { schedule(POLL_ON_MS); });
      });
    }, function (err) {
      state.lastError = String((err && err.message) || err);
      /* a station that does not answer: the pusher's dead man stops it */
      schedule(POLL_ERR_MS);
    });
  }

  state.surface = surface();
  root.PineStream = {
    version: 1,
    privateReason: privateReason,
    state: function () {
      return {surface: state.surface, on: state.on, mine: state.mine, running: state.running,
        privateWhy: state.privateWhy, lastError: state.lastError, polls: state.polls,
        info: state.info, pushed: state.pushed};
    },
    poll: function () { schedule(0); },
    stop: stopNow
  };
  if (!state.surface) return;          /* neither the tablet nor the desk: no work at all */
  schedule(2500);
})(typeof window !== 'undefined' ? window : globalThis);
