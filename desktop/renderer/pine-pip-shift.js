/* [pip-shift] THE CHANGE BETWEEN THE APP AND PINE PIP, AS ONE MOVE.
 *
 * "I want the picture in picture transition process to be smoother from going
 *  from the app to the PIP mode. Whenever it's changing it looks distorted and
 *  cropped when really I need all the elements to fade out and I need the
 *  system to be replaced with three JS particles that are flying in and
 *  swirling and representing the system changing."
 *
 * "When I press control shift p to jump into pine pip mode, Convert the
 *  display into a 3JS simulation of particles sweeping through and show the
 *  pine box logo up here in the center as the display is being converted into
 *  the pine pip display."
 *
 * What looked distorted: the window changed shape first and the page changed
 * layout afterwards, so for a moment the whole app was squeezed into the small
 * window (or the small picture stretched across the big one).
 *
 * The order is now:
 *   1. cover    - everything fades out under one dark sheet while particles
 *                 fly in from outside the window along spiral arms, swirl
 *                 round the Pine Box mark, and fold into it;
 *   2. change   - the window takes its new shape and the page its new layout,
 *                 both while the sheet shows only the mark on plain dark, so
 *                 neither is ever seen half done;
 *   3. reveal   - the particles burst back out from behind the mark, still
 *                 turning, and leave past the edges while the new view fades
 *                 in. In PiP the mark is left exactly where PiP's own mark is.
 *
 * Nothing here decides WHEN the mode changes. The desktop's main process does
 * (pip-window.cjs); this is only what the change looks like. Every wait is
 * bounded: a sheet that could stay up would be worse than the flash it hides.
 */
(function (root) {
  'use strict';
  var doc = root.document;
  /* Milliseconds. Kept on the object the module publishes, so a test (or a
   * later preference) can slow the change down and look at it. */
  var TIME = {
    gather: 600,      /* fly in, swirl, fold                          */
    burst: 720,       /* burst, swirl, leave                          */
    fadeIn: 240,      /* the old view going                           */
    fadeOut: 440,     /* the new view arriving                        */
    quick: 150,       /* the whole of it, for reduced motion          */
    hold: 3600        /* covered and nobody said reveal: reveal       */
  };
  var COUNT = 4200, ARMS = 3;

  var host = null, canvas = null, logo = null, gl = null, raf = 0;
  var phase = 'idle';       /* idle | gather | dark | burst                 */
  var startedAt = 0, holdTimer = 0, doneTimer = 0, run = 0;
  var whenDark = null, darkResolve = null, whenGone = null, goneResolve = null;
  var plan = null, loading = null, threeFailed = false;

  function now() { return root.performance && root.performance.now ? root.performance.now() : Date.now(); }
  function still() { try { return !!root.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (_) { return false; } }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function smooth(a, b, v) { var t = clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); }

  /* three.js from the app's own folder first: a mode change must not wait on
   * the station, and must still have its particles while the station restarts. */
  function three() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threeFailed) return Promise.reject(new Error('Three.js unavailable'));
    if (loading) return loading;
    var sources = ['../vendor/three.min.js'];
    try { if (typeof root.pineThreeUrl === 'function') sources.push(root.pineThreeUrl()); } catch (_) {}
    loading = new Promise(function (resolve, reject) {
      (function next() {
        if (root.THREE) return resolve(root.THREE);
        var src = sources.shift();
        if (!src) { loading = null; threeFailed = true; return reject(new Error('Three.js unavailable')); }
        var tag = doc.createElement('script');
        tag.src = src;
        tag.onload = function () { root.THREE ? resolve(root.THREE) : next(); };
        tag.onerror = next;
        doc.head.appendChild(tag);
      })();
    });
    return loading;
  }

  function colours() {
    var style = null;
    try { style = root.getComputedStyle(doc.documentElement); } catch (_) {}
    var read = function (name, fallback) { var v = style ? String(style.getPropertyValue(name) || '').trim() : ''; return v || fallback; };
    var surface = read('--pip-surface', '8 23 19').split(/[\s,]+/).map(Number);
    if (surface.length < 3 || surface.some(function (n) { return !isFinite(n); })) surface = [8, 23, 19];
    return { surface: surface.slice(0, 3), accent: read('--pip-accent', '#98e9ae'), text: read('--pip-text', '#e1f8ea') };
  }

  function build() {
    if (host) return host;
    host = doc.createElement('div');
    host.id = 'pinePipShift';
    host.setAttribute('aria-hidden', 'true');
    host.hidden = true;
    logo = doc.createElement('img');
    logo.className = 'pip-shift-logo';
    logo.alt = '';
    logo.draggable = false;
    host.appendChild(logo);
    /* On <html>, beside <body>: the PiP sheet hides every body child it does
     * not know by name, and this must outlive both layouts. */
    doc.documentElement.appendChild(host);
    return host;
  }

  /* Every particle is placed by the shader from four random numbers and the
   * few uniforms below, so a frame costs one draw call and no loop in script:
   * the page is busiest exactly when this runs.
   *   seed.x  which arm it rides, and how far along that arm's width
   *   seed.y  its size, and how far outside the window it starts
   *   seed.z  when it sets off; which of the two colours it leans to
   *   seed.w  its lane: near the eye of the swirl, or out on the rim       */
  var VERTEX = [
    'attribute vec4 seed;',
    'uniform float uTime, uGather, uBurst, uRadius, uFar, uRatio, uArms;',
    'uniform vec2 uCentre, uView;',
    'varying float vAlpha; varying float vMix;',
    'float ease(float t) { return t * t * (3.0 - 2.0 * t); }',
    'void main() {',
    '  float arm = floor(seed.x * uArms);',
    '  float within = fract(seed.x * uArms);',
    '  float lane = 0.16 + 0.84 * sqrt(seed.w);',
    '  float angle0 = (arm + within * within * 0.55) / uArms * 6.2831853 + lane * 2.6;',
    '  float spin = uTime * (1.5 + 3.2 * (1.0 - lane));',
    '  float far = uFar * (1.06 + 0.5 * seed.y);',
    '  float rho; float angle; float alpha;',
    '  if (uBurst <= 0.0) {',
    '    float p = clamp((uGather - seed.z * 0.30) / 0.62, 0.0, 1.0);',
    '    float inward = 1.0 - pow(1.0 - p, 3.0);',
    '    float fold = 1.0 - ease(clamp((uGather - 0.72) / 0.28, 0.0, 1.0));',
    '    rho = mix(far, uRadius * lane, inward) * pow(fold, 1.5);',
    '    angle = angle0 - (1.0 - inward) * 3.4 + spin;',
    '    alpha = smoothstep(0.0, 0.10, p) * (1.0 - smoothstep(0.88, 1.0, uGather));',
    '  } else {',
    '    float q = clamp((uBurst - seed.z * 0.22) / 0.78, 0.0, 1.0);',
    '    float outward = ease(q);',
    '    rho = far * outward * outward + uRadius * lane * sin(q * 3.14159) * 0.7;',
    '    angle = angle0 + outward * 2.6 + spin;',
    '    alpha = smoothstep(0.0, 0.08, q) * (1.0 - smoothstep(0.70, 1.0, q));',
    '  }',
    '  vec2 px = uCentre + rho * vec2(cos(angle), sin(angle) * 0.82);',
    '  gl_Position = vec4(px.x / uView.x * 2.0 - 1.0, 1.0 - px.y / uView.y * 2.0, 0.0, 1.0);',
    '  gl_PointSize = (1.6 + 5.4 * seed.y * seed.y) * uRatio;',
    '  vAlpha = alpha * (0.42 + 0.58 * fract(seed.x * 7.31));',
    '  vMix = seed.z;',
    '}'
  ].join('\n');
  var FRAGMENT = [
    'precision mediump float;',
    'uniform vec3 uColourA, uColourB;',
    'varying float vAlpha; varying float vMix;',
    'void main() {',
    '  float d = length(gl_PointCoord - 0.5);',
    '  float soft = smoothstep(0.5, 0.05, d);',
    '  gl_FragColor = vec4(mix(uColourA, uColourB, vMix * vMix) * soft * vAlpha, soft * vAlpha);',
    '}'
  ].join('\n');
  /* The veil drawn over the last frame before each new one: what was there
   * dims instead of vanishing, which is what gives the particles their tails. */
  var VEIL_VERTEX = 'void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }';
  var VEIL_FRAGMENT = 'precision mediump float; uniform vec3 uSurface; uniform float uFade; void main() { gl_FragColor = vec4(uSurface, uFade); }';

  function makeScene(T) {
    var tint = colours();
    canvas = doc.createElement('canvas');
    host.insertBefore(canvas, logo);       /* the mark sits over the particles */
    var renderer = new T.WebGLRenderer({ canvas: canvas, alpha: false, antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
    var ratio = Math.min(root.devicePixelRatio || 1, 2);
    var surface = new T.Color('rgb(' + tint.surface.join(',') + ')');
    renderer.setPixelRatio(ratio);
    renderer.setClearColor(surface, 1);
    renderer.autoClear = false;
    var seeds = new Float32Array(COUNT * 4), positions = new Float32Array(COUNT * 3);
    for (var i = 0; i < seeds.length; i++) seeds[i] = Math.random();
    var geometry = new T.BufferGeometry();
    geometry.setAttribute('position', new T.BufferAttribute(positions, 3));
    geometry.setAttribute('seed', new T.BufferAttribute(seeds, 4));
    var uniforms = {
      uTime: { value: 0 }, uGather: { value: 0 }, uBurst: { value: 0 }, uRadius: { value: 100 }, uFar: { value: 1000 },
      uRatio: { value: ratio }, uArms: { value: ARMS }, uCentre: { value: new T.Vector2(0, 0) }, uView: { value: new T.Vector2(1, 1) },
      uColourA: { value: new T.Color(tint.accent) }, uColourB: { value: new T.Color(tint.text) }
    };
    var material = new T.ShaderMaterial({ uniforms: uniforms, vertexShader: VERTEX, fragmentShader: FRAGMENT,
      transparent: true, depthTest: false, depthWrite: false, blending: T.AdditiveBlending });
    var points = new T.Points(geometry, material);
    points.frustumCulled = false;          /* the shader places them, not the geometry */
    points.renderOrder = 2;
    var veilUniforms = { uSurface: { value: surface }, uFade: { value: 0.3 } };
    var veilGeometry = new T.PlaneGeometry(2, 2);
    var veilMaterial = new T.ShaderMaterial({ uniforms: veilUniforms, vertexShader: VEIL_VERTEX, fragmentShader: VEIL_FRAGMENT,
      transparent: true, depthTest: false, depthWrite: false });
    var veil = new T.Mesh(veilGeometry, veilMaterial);
    veil.frustumCulled = false; veil.renderOrder = 1;
    var scene = new T.Scene(), camera = new T.Camera();
    scene.add(veil); scene.add(points);
    var size = '';
    return {
      uniforms: uniforms,
      draw: function (wipe) {
        var w = Math.max(1, host.clientWidth || root.innerWidth || 1), h = Math.max(1, host.clientHeight || root.innerHeight || 1);
        var next = w + ':' + h;
        if (next !== size) { size = next; renderer.setSize(w, h, false); uniforms.uView.value.set(w, h); wipe = true; }
        if (wipe) renderer.clear();
        renderer.render(scene, camera);
      },
      dispose: function () {
        try { geometry.dispose(); material.dispose(); veilGeometry.dispose(); veilMaterial.dispose(); renderer.dispose(); renderer.forceContextLoss(); } catch (_) {}
        if (canvas) canvas.remove();
        canvas = null;
      }
    };
  }

  function farthest(cx, cy, w, h) {
    return Math.max(Math.hypot(cx, cy), Math.hypot(w - cx, cy), Math.hypot(cx, h - cy), Math.hypot(w - cx, h - cy));
  }
  /* PiP draws its own mark in the middle at 8.4% of the window's width. The
   * sheet's mark ends at that size and place, so lifting the sheet leaves it. */
  function pipMark(width) { return clamp(width * 0.084, 30, 96); }
  function mark(x, y, size, opacity) {
    if (!logo) return;
    logo.style.width = size.toFixed(1) + 'px'; logo.style.height = size.toFixed(1) + 'px';
    logo.style.transform = 'translate(' + (x - size / 2).toFixed(1) + 'px,' + (y - size / 2).toFixed(1) + 'px)';
    logo.style.opacity = clamp(opacity, 0, 1).toFixed(3);
  }

  /* Where the swirl folds to (before the change) and bursts from (after it),
   * in this window's own pixels, so the point stays put on the SCREEN across
   * the change: it folds onto where the small window will be, and bursts from
   * where the small window was. Without the shell's numbers it is the middle. */
  function foldPoint() {
    var w = root.innerWidth || 1, h = root.innerHeight || 1;
    var p = plan || {};
    if (p.to === 'pip' && p.from && p.target && p.from.width > 0) {
      var k = w / p.from.width;
      return { x: clamp((p.target.x + p.target.width / 2 - p.from.x) * k, 24, w - 24),
               y: clamp((p.target.y + p.target.height / 2 - p.from.y) * k, 24, h - 24),
               r: clamp(Math.min(p.target.width, p.target.height) * k * 0.46, 60, Math.min(w, h) * 0.42),
               mark: pipMark(p.target.width * k) };
    }
    return { x: w / 2, y: h / 2, r: Math.min(w, h) * 0.36, mark: p.to === 'pip' ? pipMark(Math.min(w * 0.42, 520)) : pipMark(w) };
  }
  function burstPoint() {
    var w = root.innerWidth || 1, h = root.innerHeight || 1;
    var p = plan || {};
    if (p.to === 'app' && p.before) {
      var x = p.before.x + p.before.w / 2 - (root.screenX || 0), y = p.before.y + p.before.h / 2 - (root.screenY || 0);
      if (x > -1 && y > -1 && x < w + 1 && y < h + 1 && p.before.w < w) return { x: x, y: y, r: Math.min(w, h) * 0.34, mark: pipMark(p.before.w) };
    }
    return { x: w / 2, y: h / 2, r: Math.min(w, h) * 0.36, mark: pipMark(p.to === 'app' ? Math.min(w * 0.42, 520) : w) };
  }
  /* The mark while the sheet is plain dark: at the fold before the window has
   * changed, at the burst point once it has. */
  function markDark() {
    if (!plan) return;
    var at = plan.changed ? burstPoint() : foldPoint();
    mark(at.x, at.y, at.mark, 1);
  }

  function frame() {
    raf = 0;
    if (phase === 'idle') return;
    var t = now(), u = gl && gl.uniforms;
    var w = root.innerWidth || 1, h = root.innerHeight || 1;
    if (phase === 'gather') {
      var g = clamp((t - startedAt) / (plan.quick ? TIME.quick : TIME.gather), 0, 1);
      var fold = foldPoint(), k = g * g * (3 - 2 * g), wide = Math.min(w, h) * 0.40;
      var cx = w / 2 + (fold.x - w / 2) * k, cy = h / 2 + (fold.y - h / 2) * k;
      var big = plan.to === 'pip' ? clamp(Math.min(w, h) * 0.17, fold.mark, 150) : fold.mark;
      mark(cx, cy, big + (fold.mark - big) * k, plan.to === 'pip' ? smooth(0.10, 0.45, g) : smooth(0, 0.2, g));
      if (u) {
        u.uGather.value = g; u.uBurst.value = 0; u.uTime.value = (t - plan.t0) / 1000;
        u.uCentre.value.set(cx, cy);
        u.uRadius.value = wide + (fold.r - wide) * k;
        u.uFar.value = farthest(cx, cy, w, h);
      }
      if (g >= 1) settleDark();
    } else if (phase === 'burst') {
      var b = clamp((t - startedAt) / (plan.quick ? TIME.quick : TIME.burst), 0, 1);
      var from = plan.burst || (plan.burst = burstPoint());
      /* Into PiP the mark stays (PiP's own is under it); into the app it opens out and goes. */
      if (plan.to === 'app') mark(from.x, from.y, from.mark * (1 + 0.7 * smooth(0, 1, b)), 1 - smooth(0.25, 0.8, b));
      else mark(from.x, from.y, from.mark, 1);
      if (u) {
        u.uGather.value = 1; u.uBurst.value = Math.max(b, 0.0001); u.uTime.value = (t - plan.t0) / 1000;
        u.uCentre.value.set(from.x, from.y); u.uRadius.value = from.r; u.uFar.value = farthest(from.x, from.y, w, h);
      }
      if (b >= 1) { finish(); return; }
    }
    if (gl) { try { gl.draw(false); } catch (_) { dropScene(); } }
    if (phase === 'gather' || phase === 'burst') raf = root.requestAnimationFrame(frame);
  }
  function tick() { if (!raf && phase !== 'idle') raf = root.requestAnimationFrame(frame); }
  function dropScene() { if (gl) { gl.dispose(); gl = null; } }
  /* Plain dark, tails and all: this is the frame the window changes under. */
  function wipe() { if (gl) { try { gl.uniforms.uGather.value = 1; gl.uniforms.uBurst.value = 0; gl.draw(true); } catch (_) { dropScene(); } } }
  /* The window changed shape under the sheet: the mark moves to its new middle
   * at once, without waiting for the reveal to start. */
  function resized() {
    if (phase !== 'dark' || !plan) return;
    plan.changed = true;
    wipe(); markDark();
  }

  function settleDark() {
    if (phase === 'dark') return;
    phase = 'dark';
    wipe(); markDark();
    clearTimeout(holdTimer);
    /* Covered and never told to reveal - the change failed, or the page that
     * would have said so was reloaded. The view comes back by itself. */
    holdTimer = setTimeout(function () { if (phase === 'dark') reveal(); }, TIME.hold);
    if (darkResolve) { var done = darkResolve; darkResolve = null; done(true); }
  }

  function finish() {
    clearTimeout(holdTimer); clearTimeout(doneTimer);
    if (raf) { root.cancelAnimationFrame(raf); raf = 0; }
    phase = 'idle';
    if (host) { host.hidden = true; host.classList.remove('on', 'instant', 'leaving'); }
    if (logo) logo.style.opacity = '0';
    dropScene();
    plan = null;
    if (darkResolve) { var a = darkResolve; darkResolve = null; a(false); }
    if (goneResolve) { var b = goneResolve; goneResolve = null; b(true); }
    whenDark = whenGone = null;
  }

  /* Cover the window. Resolves when it is covered and plain dark - the moment
   * the window may change shape. An "instant" cover is for a change nobody
   * announced: the window has ALREADY changed, so there is nothing to fade
   * from. */
  function begin(to, options) {
    options = options || {};
    build();
    var mine = ++run;
    clearTimeout(holdTimer); clearTimeout(doneTimer);
    if (raf) { root.cancelAnimationFrame(raf); raf = 0; }
    if (goneResolve) { var g = goneResolve; goneResolve = null; g(false); }
    if (darkResolve) { var d = darkResolve; darkResolve = null; d(false); }
    var quick = still();
    plan = { to: to === 'app' ? 'app' : 'pip', quick: quick, from: options.from || null, target: options.target || null, changed: !!options.instant,
      before: { x: root.screenX || 0, y: root.screenY || 0, w: root.innerWidth || 1, h: root.innerHeight || 1 }, t0: now() };
    var tint = colours();
    host.style.setProperty('--pip-shift-surface', 'rgb(' + tint.surface.join(' ') + ')');
    host.style.setProperty('--pip-shift-in', (quick ? TIME.quick : TIME.fadeIn) + 'ms');
    host.style.setProperty('--pip-shift-out', (quick ? TIME.quick : TIME.fadeOut) + 'ms');
    var src = root.__pineLogo || '';
    logo.hidden = !src;
    if (src && logo.getAttribute('src') !== src) logo.src = src;
    logo.style.opacity = '0';
    host.hidden = false;
    host.classList.remove('leaving');
    whenGone = new Promise(function (resolve) { goneResolve = resolve; });
    whenDark = new Promise(function (resolve) { darkResolve = resolve; });
    var ready = whenDark;
    if (options.instant) {
      host.classList.add('instant', 'on');
      phase = 'gather'; settleDark();
    } else {
      host.classList.remove('instant');
      void host.offsetWidth;                 /* so the fade starts from clear */
      host.classList.add('on');
      phase = 'gather'; startedAt = now();
      wipe();                                /* a sheet left over from the last change starts clean */
      /* Timed by the clock as well as by frames: a window that is not being
       * painted (minimised, covered) still gets its change. */
      doneTimer = setTimeout(function () { if (run === mine && phase === 'gather') settleDark(); }, (quick ? TIME.quick : TIME.gather) + 120);
      tick();
    }
    if (!quick && !gl) {
      three().then(function (T) {
        if (run !== mine || phase === 'idle' || gl) return;
        try { gl = makeScene(T); } catch (_) { gl = null; return; }
        if (phase === 'dark') wipe();
        tick();
      }).catch(function () { /* no particles: the fade and the mark still cover the change */ });
    }
    return ready;
  }

  /* Uncover. Resolves when the sheet is gone. */
  function reveal() {
    if (phase === 'idle' || !host) return Promise.resolve(true);
    if (phase === 'burst') return whenGone || Promise.resolve(true);
    var mine = run, gone = whenGone || Promise.resolve(true);
    clearTimeout(holdTimer); clearTimeout(doneTimer);
    if (darkResolve) { var d = darkResolve; darkResolve = null; d(false); }
    phase = 'burst'; startedAt = now();
    plan = plan || { to: 'pip', quick: still(), t0: now() };
    plan.burst = null;
    var total = plan.quick ? TIME.quick : TIME.burst, fade = plan.quick ? TIME.quick : TIME.fadeOut;
    host.classList.remove('instant');
    /* The new view starts arriving while the particles are still leaving. */
    setTimeout(function () { if (run === mine && phase === 'burst' && host) host.classList.add('leaving'); }, Math.max(0, total - fade));
    doneTimer = setTimeout(function () { if (run === mine && phase === 'burst') finish(); }, total + 160);
    tick();
    return gone;
  }

  /* The mode HAS changed (the page has its new layout). Cover if nobody did,
   * wait for the new layout to be painted - bounded - then reveal. */
  function landed(to, settled) {
    if (phase === 'idle') begin(to, { instant: true });
    else if (phase === 'gather') { if (plan) plan.to = to === 'app' ? 'app' : 'pip'; settleDark(); }
    else if (phase === 'burst') return whenGone || Promise.resolve(true);
    if (plan) { plan.changed = true; markDark(); }
    var mine = run;
    var frames = function () { return new Promise(function (resolve) {
      var left = 2, step = function () { if (--left <= 0) resolve(); else root.requestAnimationFrame(step); };
      root.requestAnimationFrame(step); setTimeout(resolve, 260);
    }); };
    var bound = function (ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); };
    return Promise.race([Promise.resolve(settled).catch(function () {}).then(frames).then(function () { return bound(90); }), bound(1300)])
      .then(function () { return run === mine ? reveal() : true; });
  }

  if (root.addEventListener) root.addEventListener('resize', resized);
  root.PinePipShift = {
    begin: begin, reveal: reveal, landed: landed,
    phase: function () { return phase; },
    covering: function () { return phase === 'gather' || phase === 'dark'; },
    warm: function () { return three().then(function () { return true; }).catch(function () { return false; }); },
    timings: TIME
  };
  /* Have three.js in hand before the first change asks for it. */
  var idle = root.requestIdleCallback || function (fn) { return setTimeout(fn, 1500); };
  try { idle(function () { if (!still()) three().catch(function () {}); }); } catch (_) {}
})(window);
