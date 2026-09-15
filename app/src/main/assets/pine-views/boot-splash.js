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
  var POINTS = 260;          /* enough to read a mark, few enough to fly */
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

    /* One geometry and one material for every point: 260 spheres each with
     * their own would be 260 draw setups on a tablet that has to keep a
     * radio station running behind this. */
    var geo = new THREE.SphereGeometry(0.075, 8, 6);
    var mat = new THREE.MeshBasicMaterial({color: 0x65c7da, transparent: true,
      opacity: 0.95});
    var group = new THREE.Group();
    scene.add(group);

    var dots = [];
    for (var i = 0; i < targets.length; i += 1) {
      var dot = new THREE.Mesh(geo, mat);
      dot.position.set((Math.random() - 0.5) * 16, (Math.random() - 0.5) * 10,
        (Math.random() - 0.5) * 8);
      dot.userData = {
        target: targets[i],
        drift: new THREE.Vector3((Math.random() - 0.5) * 0.03,
          (Math.random() - 0.5) * 0.025, (Math.random() - 0.5) * 0.02)
      };
      group.add(dot);
      dots.push(dot);
    }

    /* The plexus lines, one buffer reused - the same discipline the wall
     * learned: geometry allocated per frame is how a plexus becomes a
     * memory leak. */
    var linkMax = dots.length * 3;
    var linkPos = new Float32Array(linkMax * 6);
    var linkGeo = new THREE.BufferGeometry();
    linkGeo.setAttribute('position', new THREE.BufferAttribute(linkPos, 3));
    var links = new THREE.LineSegments(linkGeo,
      new THREE.LineBasicMaterial({color: 0x65c7da, transparent: true,
        opacity: 0.3}));
    group.add(links);

    var NEAR = 2.2 * 2.2;
    var t0 = performance.now();
    var raf = 0;
    var stopped = false;

    function frame() {
      if (stopped) return;
      raf = requestAnimationFrame(frame);
      var t = (performance.now() - t0) / 1000;

      /* 0 -> 1 across the assembly, eased so the points arrive rather than
       * stop dead. */
      var pull = t < 1.1 ? 0 : Math.min(1, (t - 1.1) / 1.7);
      var eased = pull * pull * (3 - 2 * pull);

      for (var i = 0; i < dots.length; i += 1) {
        var d = dots[i];
        var want = d.userData.target;
        if (eased <= 0) {
          var p = d.position;
          var v = d.userData.drift;
          p.add(v);
          if (Math.abs(p.x) > 8) v.x = -v.x;
          if (Math.abs(p.y) > 5) v.y = -v.y;
          if (Math.abs(p.z) > 4) v.z = -v.z;
        } else {
          d.position.x += (want.x - d.position.x) * 0.06 * (0.4 + eased);
          d.position.y += (want.y - d.position.y) * 0.06 * (0.4 + eased);
          d.position.z += (want.z - d.position.z) * 0.06 * (0.4 + eased);
        }
      }

      /* Lines only while it is still a cloud and while it is coming
       * together - once it IS the mark they clutter it. */
      var n = 0;
      if (eased < 0.92) {
        for (var a = 0; a < dots.length && n < linkMax; a += 1) {
          for (var b = a + 1; b < dots.length && n < linkMax; b += 1) {
            var pa = dots[a].position;
            var pb = dots[b].position;
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
      linkGeo.attributes.position.needsUpdate = true;
      links.material.opacity = 0.3 * (1 - eased);

      /* ROTATING THROUGHOUT, settling square to the camera as it solidifies
       * so the finished mark is not left at an angle. */
      group.rotation.y = Math.sin(t * 0.7) * 0.9 * (1 - eased) + (1 - eased) * 0.5;
      group.rotation.x = Math.cos(t * 0.5) * 0.35 * (1 - eased);

      /* THE FLASH, then the colour. */
      if (t > 2.9) {
        var flash = Math.min(1, (t - 2.9) / 0.32);
        mat.color.setRGB(0.4 + 0.6 * flash, 0.78 + 0.22 * flash, 0.85 + 0.15 * flash);
        var bloom = 1 + flash * 0.5;
        group.scale.setScalar(bloom > 1.3 ? 1.3 : bloom);
      }
      if (t > 3.15 && !logo.classList.contains('lit')) {
        logo.src = image.src;
        logo.classList.add('lit');
      }
      if (t > 3.3) {
        mat.opacity = Math.max(0, 0.95 - (t - 3.3) * 2.4);
      }
      if (t > 4.3) {
        stopped = true;
        cancelAnimationFrame(raf);
        try { renderer.dispose(); } catch (err) { /* gone */ }
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
