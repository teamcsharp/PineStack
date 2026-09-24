/* THE LOGO ASSEMBLING ITSELF, AT STARTUP.
 *
 * "When the Pine Box application is starting up, I want to see the logo
 * rotating in 3D being assembled by particles coming together via a plexus
 * style undulating cloud of particles that assembles the particles,
 * causing the logo to become solid, and then it flashes into colour and
 * becomes the Pine Box."
 *
 * Four movements, and the order is the whole point - each one has to be
 * legible as a step or it reads as a single blur:
 *
 *   1. THE CLOUD.      Points adrift with near-neighbour lines between
 *                      them, the same grammar as the wall's plexus, so a
 *                      terminal that has been watched all evening opens on
 *                      something it already recognises.
 *   2. THE ASSEMBLY.   Those same points fly to positions sampled from the
 *                      logo. Nothing is created and nothing fades in over
 *                      the top: the cloud BECOMES the mark, which is what
 *                      makes it read as assembly.
 *   3. THE FLASH.      The points go white and bloom outward for a beat.
 *   4. THE COLOUR.     The real logo fades up underneath as the points
 *                      fade out, so the last frame is the actual artwork
 *                      rather than an approximation of it in dots.
 *
 * IT NEVER BLOCKS THE BOOT. The splash is decoration over a terminal whose
 * job is to be a radio station; if three.js is missing, the canvas is
 * refused, the image 404s or anything throws, it removes itself and the
 * app carries on. It also removes itself on a tap - the operator who has
 * seen it four hundred times should not have to watch it again - and on a
 * hard ceiling, so a stalled frame loop cannot leave a cover over the app.
 */
(function (root) {
  'use strict';

  /* Resolved, not assumed: a leading slash is the station on the tablet and
   * the root of the DISK under file://. See pineThreeUrl in renderer.js. */
  function threeUrl() {
    if (window.pineThreeUrl) return window.pineThreeUrl();
    if (/^https?:$/.test(location.protocol)) return '/vendor/three.min.js';
    return 'http://127.0.0.1:8096/vendor/three.min.js';
  }
  var POINTS = 360;          /* a full star field that still stays light on the tablet */
  var CEILING_MS = 7000;     /* it is gone by then, whatever happened */

  var threeLoad = null;

  /* WAIT FOR THE COPY THAT IS ALREADY COMING before asking the network.
   *
   * At boot this runs from a document-start script, and the kiosk hands
   * the page three.js out of the APK moments later - 594 kB with no
   * network, which is the whole point of that arrangement. Fetching
   * /vendor/three.min.js here would race it, ask the station for something
   * the tablet already has, and make the startup animation depend on the
   * network being up at precisely the moment a terminal most wants to look
   * like it is working.
   *
   * So: watch briefly for the local copy, and only then fall back. */
  function waitForThree(ms) {
    if (root.THREE) return Promise.resolve(root.THREE);
    return new Promise(function (resolve) {
      var until = Date.now() + ms;
      (function look() {
        if (root.THREE) return resolve(root.THREE);
        if (Date.now() > until) return resolve(null);
        setTimeout(look, 90);
      })();
    });
  }

  function three() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threeLoad) return threeLoad;
    threeLoad = waitForThree(2200).then(function (got) {
      if (got) return got;
      threeLoad = null;
      return fromNetwork();
    });
    return threeLoad;
  }

  function fromNetwork() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (threeLoad) return threeLoad;
    threeLoad = new Promise(function (resolve, reject) {
      var tag = document.createElement('script');
      tag.src = threeUrl();
      tag.onload = function () { resolve(root.THREE); };
      tag.onerror = function () { threeLoad = null; reject(new Error('no three.js')); };
      document.head.appendChild(tag);
    });
    return threeLoad;
  }

  /* Sample the logo into positions. Coarse on purpose: every lit pixel
   * would be tens of thousands of points and an unreadable smear. Alpha is
   * what is read, not brightness - the mark is a shape on transparency,
   * and a dark logo on a dark page has no brightness to speak of. */
  var SPAN = 8;              /* how wide the assembled mark is, in scene units */

  function shapeOf(image, want) {
    var W = 120;
    var H = Math.max(1, Math.round(W * (image.height || 1) / (image.width || 1)));
    var pad = document.createElement('canvas');
    pad.width = W; pad.height = H;
    var g = pad.getContext('2d');
    if (!g) return [];
    g.drawImage(image, 0, 0, W, H);
    var data;
    try { data = g.getImageData(0, 0, W, H).data; } catch (err) { return []; }

    var lit = [];
    for (var y = 0; y < H; y += 1) {
      for (var x = 0; x < W; x += 1) {
        var at = (y * W + x) * 4;
        var alpha = data[at + 3];
        var bright = (data[at] + data[at + 1] + data[at + 2]) / 3;
        if (alpha < 70 || bright < 26) continue;
        /* ASPECT, DONE ONCE AND PROPERLY.
         *
         * This read `* 9 * (H / W) * (W / H) * 4.6`, and those two factors
         * cancel to 1 - so the height was 9 * 4.6 against a width of 9,
         * and the mark came out as a bright vertical streak down the
         * middle of the boot screen. The rule is simply: the sampled grid
         * is W by H, so the scene box must be SPAN by SPAN * (H / W). */
        lit.push({
          x: (x / W - 0.5) * SPAN,
          y: -(y / H - 0.5) * SPAN * (H / W),
          z: (Math.random() - 0.5) * 0.7,
          r: data[at] / 255, g: data[at + 1] / 255, b: data[at + 2] / 255
        });
      }
    }
    if (!lit.length) return [];
    /* Thin evenly, so the whole mark is represented rather than its top. */
    if (lit.length > want) {
      var keep = [];
      var stride = lit.length / want;
      for (var k = 0; k < want; k += 1) keep.push(lit[Math.floor(k * stride)]);
      return keep;
    }
    return lit;
  }

  var showing = null;
  var played = false;

  function show(options) {
    var settings = options || {};
    /* ONCE PER PAGE, AND THE MODULE ENFORCES IT.
     *
     * Two things call this - the boot screen at document start, and the
     * rail when it goes up - and each had its own guard flag. Measured: the
     * mark assembled, finished, and then the whole animation started over
     * from the cloud, because the second caller arrived after the first had
     * already released. A guard that lives in the callers is a guard that
     * every new caller has to remember; this one lives here. */
    if (played && !settings.again) return Promise.resolve(false);
    if (showing) return showing;
    played = true;
    var src = String(settings.src || '');
    if (!src) return Promise.resolve(false);

    /* WHERE IT PLAYS. By default it makes its own full-screen cover. Given
     * an `into`, it lays itself inside that element instead - which is how
     * it rides the kiosk's existing boot screen, whose own canvas renders
     * nothing (its scene is on a Worker with an OffscreenCanvas, and the
     * file's own comments record that path measuring "NOTHING on screen").
     * Filling that empty middle beats covering a screen that is already
     * saying something true about the boot. */
    var cover = document.createElement('div');
    cover.className = 'pine-splash' + (settings.into ? ' inside' : '');
    cover.innerHTML = '<canvas class="pine-splash-fx"></canvas>'
      + '<img class="pine-splash-logo" alt="">';
    (settings.into || document.body).appendChild(cover);

    var done = false;
    function finish() {
      if (done) return;
      done = true;
      cover.classList.add('gone');
      setTimeout(function () {
        if (cover.parentNode) cover.parentNode.removeChild(cover);
      }, 700);
      showing = null;
      if (typeof settings.onDone === 'function') {
        try { settings.onDone(); } catch (err) { /* not our business */ }
      }
    }
    /* A tap skips it, and nothing keeps it past the ceiling. */
    cover.addEventListener('pointerdown', finish);
    var ceiling = setTimeout(finish, CEILING_MS);

    showing = new Promise(function (resolve) {
      var image = new Image();
      image.onerror = function () { clearTimeout(ceiling); finish(); resolve(false); };
      image.onload = function () {
        three().then(function (THREE) {
          try {
            run(THREE, cover, image, finish);
            resolve(true);
          } catch (err) {
            clearTimeout(ceiling); finish(); resolve(false);
          }
        }, function () {
          /* No WebGL: show the logo plainly rather than nothing. It is
           * still a splash, just not a performance. */
          var flat = cover.querySelector('.pine-splash-logo');
          if (flat) { flat.src = src; flat.classList.add('lit'); }
          setTimeout(finish, 1200);
          resolve(false);
        });
      };
      image.src = src;
    });
    return showing;
  }

  function run(THREE, cover, image, finish) {
    var canvas = cover.querySelector('.pine-splash-fx');
    var logo = cover.querySelector('.pine-splash-logo');
    var targets = shapeOf(image, POINTS);
    if (!targets.length) { finish(); return; }

    var renderer = new THREE.WebGLRenderer({canvas: canvas, antialias: true,
      alpha: true});
    renderer.setPixelRatio(Math.min(2, root.devicePixelRatio || 1));
    var w = cover.clientWidth || 800;
    var h = cover.clientHeight || 500;
    renderer.setSize(w, h, false);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 100);
    camera.position.set(0, 0, 15);

    /* TWO VIEWS OF ONE SET OF STARS. Points supply the heads; line segments
     * supply velocity trails. Both buffers are allocated once and updated
     * in place, so the very first rendered frame is a deep star field and
     * no intermediate plane or edge-on logo can ever be exposed. */
    var stars = [];
    var pointPos = new Float32Array(targets.length * 3);
    var streakPos = new Float32Array(targets.length * 6);
    var pointGeo = new THREE.BufferGeometry();
    var pointAttr = new THREE.BufferAttribute(pointPos, 3);
    if (pointAttr.setUsage && THREE.DynamicDrawUsage) pointAttr.setUsage(THREE.DynamicDrawUsage);
    pointGeo.setAttribute('position', pointAttr);
    var pointMat = new THREE.PointsMaterial({
      color: 0x8de8ee, size: 0.095, sizeAttenuation: true,
      transparent: true, opacity: 0.98, depthWrite: false
    });
    var points = new THREE.Points(pointGeo, pointMat);
    scene.add(points);

    var streakGeo = new THREE.BufferGeometry();
    var streakAttr = new THREE.BufferAttribute(streakPos, 3);
    if (streakAttr.setUsage && THREE.DynamicDrawUsage) streakAttr.setUsage(THREE.DynamicDrawUsage);
    streakGeo.setAttribute('position', streakAttr);
    var streakMat = new THREE.LineBasicMaterial({
      color: 0x65c7da, transparent: true, opacity: 0.74,
      depthWrite: false, blending: THREE.AdditiveBlending
    });
    var streaks = new THREE.LineSegments(streakGeo, streakMat);
    scene.add(streaks);

    /* A sparse plexus appears only after the rush has slowed. This is the
     * graceful hand-off from flight to the station's familiar undulating
     * pattern, never a rotating sheet. */
    var linkMax = targets.length * 2;
    var linkPos = new Float32Array(linkMax * 6);
    var linkGeo = new THREE.BufferGeometry();
    var linkAttr = new THREE.BufferAttribute(linkPos, 3);
    if (linkAttr.setUsage && THREE.DynamicDrawUsage) linkAttr.setUsage(THREE.DynamicDrawUsage);
    linkGeo.setAttribute('position', linkAttr);
    var linkMat = new THREE.LineBasicMaterial({
      color: 0x65c7da, transparent: true, opacity: 0, depthWrite: false
    });
    var links = new THREE.LineSegments(linkGeo, linkMat);
    scene.add(links);

    var fieldX = 12.5;
    var fieldY = Math.max(6.2, fieldX * h / Math.max(1, w));
    for (var i = 0; i < targets.length; i += 1) {
      var z = -7 + Math.random() * 13;
      var depthSpeed = 0.78 + (z + 7) / 13 * 0.7;
      stars.push({
        x: (Math.random() * 2 - 1) * fieldX,
        y: (Math.random() * 2 - 1) * fieldY,
        z: z,
        vx: (4.8 + Math.random() * 4.2) * depthSpeed,
        vy: -(3.2 + Math.random() * 3.6) * depthSpeed,
        phase: Math.random() * Math.PI * 2,
        target: targets[i]
      });
    }

    var NEAR = 1.42 * 1.42;
    var t0 = performance.now();
    var raf = 0;
    var stopped = false;

    function frame() {
      if (stopped) return;
      raf = requestAnimationFrame(frame);
      var t = (performance.now() - t0) / 1000;

      /* Rush hard toward the lower right, then bleed that speed into a
       * smooth attraction. The smoothstep starts before velocity reaches
       * zero, so there is no frozen or flattened intermediate frame. */
      var brake = Math.max(0, Math.min(1, t / 1.75));
      var brakeEase = brake * brake * (3 - 2 * brake);
      var pull = Math.max(0, Math.min(1, (t - 0.82) / 2.35));
      var eased = pull * pull * (3 - 2 * pull);
      var dt = 1 / 60;

      for (var i = 0; i < stars.length; i += 1) {
        var star = stars[i];
        var speed = 1 - brakeEase;
        star.x += star.vx * speed * dt;
        star.y += star.vy * speed * dt;
        if (pull < 0.36) {
          if (star.x > fieldX + 1.5) star.x = -fieldX - Math.random() * 2;
          if (star.y < -fieldY - 1.5) star.y = fieldY + Math.random() * 2;
        }
        var breathe = Math.sin(t * 1.65 + star.phase) * (0.16 - eased * 0.09);
        var wantX = star.target.x + breathe;
        var wantY = star.target.y + Math.cos(t * 1.35 + star.phase) * (0.12 - eased * 0.06);
        var wantZ = star.target.z + Math.sin(t * 1.1 + star.phase) * 0.16;
        var catchUp = 0.018 + eased * 0.105;
        star.x += (wantX - star.x) * catchUp;
        star.y += (wantY - star.y) * catchUp;
        star.z += (wantZ - star.z) * catchUp;

        var p3 = i * 3;
        pointPos[p3] = star.x; pointPos[p3 + 1] = star.y; pointPos[p3 + 2] = star.z;
        var p6 = i * 6;
        var trail = (0.25 + speed * 1.55) * (0.76 + (star.z + 7) / 18);
        streakPos[p6] = star.x; streakPos[p6 + 1] = star.y; streakPos[p6 + 2] = star.z;
        streakPos[p6 + 3] = star.x - star.vx * trail * 0.18;
        streakPos[p6 + 4] = star.y - star.vy * trail * 0.18;
        streakPos[p6 + 5] = star.z - trail * 0.14;
      }
      pointAttr.needsUpdate = true;
      streakAttr.needsUpdate = true;
      streakMat.opacity = 0.74 * (1 - eased) + 0.08 * (1 - Math.min(1, pull * 1.4));

      /* Lines only while it is still a cloud and while it is coming
       * together - once it IS the mark they clutter it. */
      var n = 0;
      if (pull > 0.28 && eased < 0.99) {
        for (var a = 0; a < stars.length && n < linkMax; a += 1) {
          for (var b = a + 1; b < stars.length && n < linkMax; b += 1) {
            var pa = stars[a];
            var pb = stars[b];
            var dx = pa.x - pb.x, dy = pa.y - pb.y, dz = pa.z - pb.z;
            if (dx * dx + dy * dy + dz * dz > NEAR) continue;
            var o = n * 6;
            linkPos[o] = pa.x; linkPos[o + 1] = pa.y; linkPos[o + 2] = pa.z;
            linkPos[o + 3] = pb.x; linkPos[o + 4] = pb.y; linkPos[o + 5] = pb.z;
            n += 1;
          }
        }
      }
      linkGeo.setDrawRange(0, n * 2);
      linkAttr.needsUpdate = true;
      linkMat.opacity = Math.min(0.34, Math.max(0, (pull - 0.28) * 0.58)) * (1 - eased * 0.45);

      /* THE FLASH, then the colour. */
      if (t > 3.25) {
        var flash = Math.min(1, (t - 3.25) / 0.34);
        pointMat.color.setRGB(0.56 + 0.44 * flash, 0.91 + 0.09 * flash, 0.93 + 0.07 * flash);
        pointMat.size = 0.095 + flash * 0.07;
      }
      if (t > 3.5 && !logo.classList.contains('lit')) {
        logo.src = image.src;
        logo.classList.add('lit');
      }
      if (t > 3.68) {
        pointMat.opacity = Math.max(0, 0.98 - (t - 3.68) * 1.75);
        streakMat.opacity *= Math.max(0, 1 - (t - 3.68) * 2.2);
        linkMat.opacity *= Math.max(0, 1 - (t - 3.68) * 2.2);
      }
      if (t > 4.55) {
        stopped = true;
        cancelAnimationFrame(raf);
        try {
          pointGeo.dispose(); streakGeo.dispose(); linkGeo.dispose();
          pointMat.dispose(); streakMat.dispose(); linkMat.dispose(); renderer.dispose();
        } catch (err) { /* gone */ }
        finish();
        return;
      }
      renderer.render(scene, camera);
    }
    frame();
  }

  var api = {show: show, isShowing: function () { return !!showing; }};
  root.PineBootSplash = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
