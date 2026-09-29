/* window.PineVcr - the ONE way a picture comes on and goes off. [vcrfx]
 *
 * "Across the application and then broadcast, anytime a video pops up, use
 *  the same V CR animation effect for displaying the video and showing it
 *  animate in ... And same thing if it goes away." (operator, 2026-09-29)
 *
 * The effect is the SFX guy's CRT set (#1263, sfx-tv.css sfxTvOn/sfxTvOff),
 * lifted out of that one stylesheet so every surface draws the same thing:
 *
 *   in   a bright dot, opened out into a line, the line pulled open into the
 *        picture, with a white pop across the frame  (420 ms)
 *   out  the picture collapses into a line, the line into a dot, and the dot
 *        fades                                        (460 ms)
 *
 * The keyframes, the offsets and the curves are the stylesheet's own, number
 * for number. A CSS animation-timing-function eases EACH KEYFRAME INTERVAL,
 * not the whole run, so every keyframe here carries the curve itself and the
 * run is linear - that is what keeps a Web Animation identical to the class
 * it replaces. The tablet's native surfaces (PineVideoWall, PineCamWall) play
 * the same table in Kotlin (video/VcrFx.kt), from the numbers exported below.
 *
 * API (every call is safe on a missing or detached element):
 *   PineVcr.in(el, opts)   -> Promise<boolean>  true = it finished, false = superseded
 *   PineVcr.out(el, opts)  -> Promise<boolean>  the element is left collapsed
 *   PineVcr.set(el, on, {show, hide, flash})
 *                          -> Promise<boolean>  THE STATE MACHINE: last call wins;
 *                             show(el) runs before an in, hide(el) after an out
 *                             that was not overtaken. Never stuck: an in asked for
 *                             during an out starts at once from the dot, and the
 *                             other way round.
 *   PineVcr.flip(el, on, count, opts)
 *                          -> Promise<boolean>  plays `count` switch flips that
 *                             ended at `on` (out/in/out...), one after another,
 *                             so a viewer sees every flip the operator made even
 *                             when several landed between two polls. Queued, capped,
 *                             and always ending in `on`.
 *   PineVcr.cancel(el)     drop whatever is running and any queued flips
 *   PineVcr.state(el)      'idle' | 'in' | 'shown' | 'out' | 'hidden'
 *   PineVcr.sample(dir, t) the pure table at 0..1 (tests, the native twin)
 *
 * opts.flash: an element to pop (the SFX TV passes its own), false for none;
 * left out, a white pop is laid over the element's own rectangle for 300 ms.
 * prefers-reduced-motion: a 160 ms fade and no pop, in both directions.
 */
(function (root) {
  'use strict';

  var IN_MS = 420;
  var OUT_MS = 460;
  var FLASH_MS = 300;
  var FADE_MS = 160;
  var HOLD_MS = 260;          // flip(): how long a picture stands between flips
  var FLIP_CAP = 8;           // flip(): the most transitions ever queued
  var IN_EASE = 'cubic-bezier(.18, .9, .3, 1)';
  var OUT_EASE = 'cubic-bezier(.7, 0, .9, .35)';
  var FLASH_EASE = 'ease-out';
  /* sfx-tv.css, @keyframes sfxTvOn / sfxTvOff - offset, scaleX, scaleY,
     brightness, opacity. */
  var IN_FRAMES = [
    [0, 0.004, 0.004, 4, 1],
    [0.34, 1, 0.006, 3.4, 1],
    [0.58, 1, 0.06, 2, 1],
    [1, 1, 1, 1, 1]
  ];
  var OUT_FRAMES = [
    [0, 1, 1, 1, 1],
    [0.40, 1, 0.014, 3.2, 1],
    [0.62, 1, 0.006, 5, 1],
    [1, 0.004, 0.004, 7, 0]
  ];

  /* ------------------------------------------------ the pure table */

  function bezier(x1, y1, x2, y2) {
    /* The CSS cubic-bezier, solved for y at x (Newton, then bisection). */
    function cx(t) { return ((1 - 3 * x2 + 3 * x1) * t + (3 * x2 - 6 * x1)) * t * t + 3 * x1 * t; }
    function cy(t) { return ((1 - 3 * y2 + 3 * y1) * t + (3 * y2 - 6 * y1)) * t * t + 3 * y1 * t; }
    function dx(t) { return 3 * (1 - 3 * x2 + 3 * x1) * t * t + 2 * (3 * x2 - 6 * x1) * t + 3 * x1; }
    return function (x) {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      var t = x, i;
      for (i = 0; i < 8; i++) {
        var e = cx(t) - x, d = dx(t);
        if (Math.abs(e) < 1e-6) return cy(t);
        if (Math.abs(d) < 1e-6) break;
        t -= e / d;
      }
      var lo = 0, hi = 1;
      t = x;
      for (i = 0; i < 40; i++) {
        var v = cx(t);
        if (Math.abs(v - x) < 1e-6) break;
        if (v < x) lo = t; else hi = t;
        t = (lo + hi) / 2;
      }
      return cy(t);
    };
  }
  var CURVE = {in: bezier(0.18, 0.9, 0.3, 1), out: bezier(0.7, 0, 0.9, 0.35)};

  /* The value at progress t (0..1) of a run, eased per interval as CSS does. */
  function sample(dir, t) {
    var F = dir === 'out' ? OUT_FRAMES : IN_FRAMES;
    var ease = CURVE[dir === 'out' ? 'out' : 'in'];
    t = Math.max(0, Math.min(1, Number(t) || 0));
    var i = 0;
    while (i < F.length - 2 && t > F[i + 1][0]) i++;
    var a = F[i], b = F[i + 1];
    var span = b[0] - a[0];
    var k = span > 0 ? ease((t - a[0]) / span) : 1;
    function mix(n) { return a[n] + (b[n] - a[n]) * k; }
    return {sx: mix(1), sy: mix(2), bright: mix(3), opacity: mix(4)};
  }

  /* ------------------------------------------------ the page side */

  function reduced() {
    try { return !!(root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches); }
    catch (e) { return false; }
  }

  var scaleProp = null;
  function useScaleProperty() {
    /* The individual `scale` property composes with whatever `transform` the
       element already has (a drag, a centring translate), so the effect never
       moves a picture it only meant to squash. Older engines: transform. */
    if (scaleProp === null) {
      try { scaleProp = !!(root.CSS && root.CSS.supports && root.CSS.supports('scale', '1 1')); }
      catch (e) { scaleProp = false; }
    }
    return scaleProp;
  }

  function keyframes(dir) {
    var F = dir === 'out' ? OUT_FRAMES : IN_FRAMES;
    var ease = dir === 'out' ? OUT_EASE : IN_EASE;
    var sp = useScaleProperty();
    return F.map(function (f) {
      var k = {offset: f[0], filter: 'brightness(' + f[3] + ')', opacity: f[4], easing: ease};
      if (sp) k.scale = f[1] + ' ' + f[2];
      else k.transform = 'scale(' + f[1] + ', ' + f[2] + ')';
      return k;
    });
  }

  var states = (typeof WeakMap === 'function') ? new WeakMap() : null;
  function st(el) {
    var s = states ? states.get(el) : el.__pineVcr;
    if (!s) {
      s = {phase: 'idle', gen: 0, anim: null, hold: null, promise: null, flashEl: null, settle: null, want: null,
           queue: [], running: false, qgen: 0};
      if (states) states.set(el, s); else el.__pineVcr = s;
    }
    return s;
  }

  function usable(el) { return !!(el && el.nodeType === 1); }

  function dropFlash(s) {
    var f = s.flashEl;
    s.flashEl = null;
    if (f && f.parentNode) { try { f.parentNode.removeChild(f); } catch (e) { /* gone */ } }
  }

  function stop(s, outcome) {
    /* End whatever is running; its promise answers `outcome` (false = overtaken).
       A finished out's hold goes too: left alive, its fill would win again the
       moment the next in finished, and the picture would sit collapsed. */
    var a = s.anim;
    s.anim = null;
    s.gen++;
    if (a) { try { a.cancel(); } catch (e) { /* already done */ } }
    var h = s.hold;
    s.hold = null;
    if (h) { try { h.cancel(); } catch (e) { /* already gone */ } }
    dropFlash(s);
    var settle = s.settle;
    s.settle = null;
    if (settle) settle(outcome);
  }

  function popOver(el, flash) {
    /* The white pop across the frame. Given an element (the SFX TV's), that
       one is animated; otherwise a pane is laid over the picture's own box,
       beside it in a positioned parent, else fixed over it. Never scaled with
       the picture: the pop is the whole screen lighting up, not the dot. */
    if (flash === false || reduced()) return null;
    if (flash && flash.nodeType === 1) {
      try { flash.animate([{opacity: 0.8}, {opacity: 0}], {duration: FLASH_MS, easing: FLASH_EASE, fill: 'both'}); }
      catch (e) { /* the picture comes on either way */ }
      return null;
    }
    var doc = el.ownerDocument || root.document;
    if (!doc || !doc.body || typeof el.getBoundingClientRect !== 'function') return null;
    var r = el.getBoundingClientRect();
    if (!(r.width > 2 && r.height > 2)) return null;
    var pane = doc.createElement('div');
    pane.className = 'pine-vcr-flash';
    pane.setAttribute('aria-hidden', 'true');
    var css = 'pointer-events:none;background:#fff;opacity:0;margin:0;padding:0;border:0;';
    var parent = el.parentNode;
    var positioned = false;
    try {
      positioned = !!(parent && parent.nodeType === 1 && el.offsetParent === parent
        && root.getComputedStyle(parent).position !== 'static');
    } catch (e) { positioned = false; }
    var z = 0;
    try { z = parseInt(root.getComputedStyle(el).zIndex, 10) || 0; } catch (e) { z = 0; }
    if (positioned) {
      pane.style.cssText = css + 'position:absolute;left:' + el.offsetLeft + 'px;top:' + el.offsetTop
        + 'px;width:' + el.offsetWidth + 'px;height:' + el.offsetHeight + 'px;z-index:' + (z + 1) + ';';
      parent.appendChild(pane);
    } else {
      pane.style.cssText = css + 'position:fixed;left:' + r.left + 'px;top:' + r.top + 'px;width:'
        + r.width + 'px;height:' + r.height + 'px;z-index:2147483600;';
      doc.body.appendChild(pane);
    }
    try {
      pane.animate([{opacity: 0.8}, {opacity: 0}], {duration: FLASH_MS, easing: FLASH_EASE, fill: 'both'});
    } catch (e) { /* no pop on an engine without animate() */ }
    return pane;
  }

  function run(el, dir, opts) {
    opts = opts || {};
    if (!usable(el)) return Promise.resolve(false);
    var s = st(el);
    stop(s, false);
    var gen = s.gen;
    s.phase = dir;
    s.promise = new Promise(function (resolve) {
      var settled = false;
      var settle = function (ok) {
        if (settled) return;
        settled = true;
        resolve(!!ok);
      };
      s.settle = settle;
      var finish = function () {
        if (s.gen !== gen) return;         // overtaken: stop() already answered
        s.settle = null;
        dropFlash(s);
        s.phase = dir === 'in' ? 'shown' : 'hidden';
        var a = s.anim;
        s.anim = null;
        /* An in leaves nothing behind (no promoted layer, no filter); an out
           holds the collapsed frame until the caller hides the element or the
           next in replaces it. */
        if (dir === 'in' && a) { try { a.cancel(); } catch (e) { /* done */ } }
        else if (a) s.hold = a;
        settle(true);
      };
      var calm = reduced();
      var ms = calm ? FADE_MS : (dir === 'in' ? IN_MS : OUT_MS);
      if (typeof el.animate !== 'function') {
        /* No Web Animations: the state still moves, on time. */
        setTimeout(finish, 0);
        return;
      }
      var frames = calm
        ? (dir === 'in' ? [{opacity: 0}, {opacity: 1}] : [{opacity: 1}, {opacity: 0}])
        : keyframes(dir);
      /* the pop is laid over the picture's box BEFORE the dot shrinks it */
      if (dir === 'in' && !calm) s.flashEl = popOver(el, opts.flash);
      try {
        s.anim = el.animate(frames, {duration: ms, easing: 'linear',
          fill: dir === 'in' ? 'backwards' : 'forwards'});
      } catch (e) {
        s.anim = null;
        setTimeout(finish, 0);
        return;
      }
      s.anim.onfinish = finish;
      /* A finished event can be lost (a hidden tab, an element taken out of
         the tree mid-run); the watch makes sure the state still arrives. */
      var watch = function () {
        if (s.gen !== gen || s.phase !== dir) return;
        /* held on purpose (a frame-by-frame proof pauses it): wait on */
        if (s.anim && s.anim.playState === 'paused' && !(Number(s.anim.currentTime) >= ms - 1)) {
          setTimeout(watch, ms);
          return;
        }
        finish();
      };
      setTimeout(watch, ms + 400);
    });
    return s.promise;
  }

  function vin(el, opts) { return run(el, 'in', opts); }
  function vout(el, opts) { return run(el, 'out', opts); }

  function rendered(el) {
    try { return !!(el.isConnected !== false && el.getClientRects && el.getClientRects().length); }
    catch (e) { return false; }
  }

  function call(fn, el) {
    if (typeof fn !== 'function') return;
    try { fn(el); } catch (e) { /* a caller's hook never breaks the machine */ }
  }

  /* THE STATE MACHINE. The switch is never debounced - every call lands - but
     the animation only ever runs toward the newest wish. */
  function set(el, on, opts) {
    opts = opts || {};
    if (!usable(el)) return Promise.resolve(false);
    var s = st(el);
    on = !!on;
    s.want = on;
    if (on) {
      if (s.phase === 'shown' && !s.anim) return Promise.resolve(true);
      if (s.phase === 'in' && s.promise) return s.promise;       // already coming on
      call(opts.show, el);
      return vin(el, opts);
    }
    if (s.phase === 'hidden') { call(opts.hide, el); return Promise.resolve(true); }
    if (s.phase === 'out' && s.promise) {                        // already going off
      return s.promise.then(function (ok) {
        if (ok && s.want === false) call(opts.hide, el);
        return ok;
      });
    }
    if (s.phase === 'idle' && !rendered(el)) {
      s.phase = 'hidden';
      call(opts.hide, el);
      return Promise.resolve(true);
    }
    return vout(el, opts).then(function (ok) {
      if (ok && s.want === false) call(opts.hide, el);
      return ok;
    });
  }

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  /* A burst of switch flips, each one seen. `count` flips that ended at `on`
     are the transitions ...!on, on (newest last); they join the queue behind
     anything still playing, the queue is capped with its parity kept, and the
     last one queued is always `on`. */
  function flip(el, on, count, opts) {
    if (!usable(el)) return Promise.resolve(false);
    var s = st(el);
    on = !!on;
    var n = Math.max(1, Math.min(FLIP_CAP, Math.floor(Number(count) || 1)));
    for (var i = n - 1; i >= 0; i--) s.queue.push(i % 2 === 0 ? on : !on);
    while (s.queue.length > FLIP_CAP) s.queue.splice(0, 2);   // keeps the parity
    if (s.running) return Promise.resolve(true);
    s.running = true;
    var qgen = ++s.qgen;
    var step = function () {
      if (s.qgen !== qgen) return Promise.resolve(false);
      if (!s.queue.length) { s.running = false; return Promise.resolve(true); }
      var want = s.queue.shift();
      var shownNow = s.phase === 'shown' || s.phase === 'in';
      if (want === shownNow && !(s.phase === 'idle')) return step();
      var guard = new Promise(function (r) { setTimeout(function () { r('late'); }, IN_MS + OUT_MS + 900); });
      return Promise.race([set(el, want, opts), guard]).then(function () {
        return (want && s.queue.length) ? wait(HOLD_MS) : null;
      }).then(step, step);
    };
    return step();
  }

  function cancel(el) {
    if (!usable(el)) return;
    var s = st(el);
    s.queue = [];
    s.qgen++;
    s.running = false;
    stop(s, false);
  }

  function state(el) {
    if (!usable(el)) return 'idle';
    return st(el).phase;
  }

  root.PineVcr = {
    version: '2026-09-29.1',
    IN_MS: IN_MS, OUT_MS: OUT_MS, FLASH_MS: FLASH_MS, FADE_MS: FADE_MS, HOLD_MS: HOLD_MS,
    IN_EASE: IN_EASE, OUT_EASE: OUT_EASE,
    IN_FRAMES: IN_FRAMES, OUT_FRAMES: OUT_FRAMES,
    in: vin, out: vout, set: set, flip: flip, cancel: cancel, state: state,
    sample: sample, reduced: reduced
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineVcr;
}(typeof window !== 'undefined' ? window : globalThis));
