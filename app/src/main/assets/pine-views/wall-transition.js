/* THE LOADER: A PLEXUS, AND NEVER A STRETCHED LOGO.
 *
 * "I don't like seeing it. I just want to see a three JS simulation of
 * plexus graphics representing things floating, loading is happening in the
 * background, but I don't wanna see a logo being stretched into a
 * rectangle."
 *
 * THE OBLONG CIRCLE IS NOT A SCALING BUG, and this is worth stating because
 * it looks exactly like one. A <video> element with no decodable frame is
 * painted by the browser with its OWN placeholder - a round play badge,
 * scaled to fill the element box. It ignores `object-fit` entirely, so no
 * amount of CSS on the element changes it. `.pv-video` already carried
 * `object-fit: contain` while that badge was stretched across the screen.
 *
 * The only cure is to never show an empty video element at all. So every
 * place that plays a clip hides the element until it genuinely holds a
 * frame, and puts THIS in the gap. The gap is real: the gallery route has
 * no Range support, so a clip is downloaded whole before it can play.
 *
 * WHY A PLEXUS RATHER THAN A SPINNER. It says "work is happening" without
 * claiming to know how much is left, which is the truth here - the station
 * is fetching something and nobody has a percentage. And it cannot be
 * mistaken for a logo.
 *
 * SMALL ON PURPOSE. 34 points, one reused renderer, a capped pixel ratio.
 * This tablet was measured at 148 MB free under a load average of 25, with
 * 28 WebGL scenes already registered in the panel. The link pass is O(n^2):
 * at 300 points that would be 45,000 distance checks a frame for wallpaper.
 * There is a 2D fallback for when a GL context cannot be had, because a
 * loader that fails to load is a poor joke.
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
  var loading = null;

  function three() {
    if (root.THREE) return Promise.resolve(root.THREE);
    if (loading) return loading;
    loading = new Promise(function (resolve) {
      var tag = document.createElement('script');
      tag.src = threeUrl();
      tag.onload = function () { resolve(root.THREE || null); };
      tag.onerror = function () { resolve(null); };
      document.head.appendChild(tag);
    });
    return loading;
  }

  function Plexus(canvas) {
    this.canvas = canvas;
    this.frame = 0;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this.points = [];
    this.started = 0;
    this.mode = 'flat';
  }

  var COUNT = 34;
  var NEAR = 4.4;          /* squared distance a link is drawn within */

  Plexus.prototype.build = function build() {
    var self = this;
    return three().then(function (THREE) {
      if (!THREE) { self.mode = 'flat'; return self; }
      try {
        self.renderer = new THREE.WebGLRenderer({
          canvas: self.canvas, antialias: false, alpha: true,
          powerPreference: 'low-power'
        });
        self.renderer.setPixelRatio(Math.min(1.5, root.devicePixelRatio || 1));
        self.scene = new THREE.Scene();
        self.camera = new THREE.PerspectiveCamera(50, 16 / 9, 0.1, 100);
        self.camera.position.set(0, 0, 9);

        var dotGeo = new THREE.SphereGeometry(0.055, 6, 6);
        var dotMat = new THREE.MeshBasicMaterial({
          color: 0x65c7da, transparent: true, opacity: 0.9
        });
        /* Held, because ONE material is shared by every point (and by the
         * ones assemble() adds later). Brightness is therefore one write a
         * frame rather than one per point, which is what makes it cheap
         * enough to do on a tablet measured at 148 MB free. */
        self.dotMat = dotMat;
        for (var i = 0; i < COUNT; i += 1) {
          var dot = new THREE.Mesh(dotGeo, dotMat);
          dot.position.set((Math.random() - 0.5) * 11,
            (Math.random() - 0.5) * 6.2, (Math.random() - 0.5) * 4);
          dot.userData.drift = new THREE.Vector3(
            (Math.random() - 0.5) * 0.011,
            (Math.random() - 0.5) * 0.009,
            (Math.random() - 0.5) * 0.007);
          self.scene.add(dot);
          self.points.push(dot);
        }

        /* ONE line object, rebuilt in place each frame. Allocating geometry
         * per frame is what turns a plexus into a memory leak. */
        self.linkMax = COUNT * 6;
        self.linkPos = new Float32Array(self.linkMax * 6);
        self.linkGeo = new THREE.BufferGeometry();
        self.linkGeo.setAttribute('position',
          new THREE.BufferAttribute(self.linkPos, 3));
        self.links = new THREE.LineSegments(self.linkGeo,
          new THREE.LineBasicMaterial({
            color: 0x65c7da, transparent: true, opacity: 0.32
          }));
        self.scene.add(self.links);
        self.mode = 'three';
      } catch (err) {
        self.mode = 'flat';
      }
      return self;
    });
  };

  Plexus.prototype.size = function size() {
    var w = this.canvas.clientWidth;
    var h = this.canvas.clientHeight;
    if (!w || !h) return false;
    if (this.mode === 'three' && this.renderer) {
      /* `false` IS CORRECT HERE, and the note it replaces had it backwards.
       *
       * setSize(w, h) with updateStyle on writes `style.width = w + 'px'`
       * onto the canvas - which then OUT-RANKS the `width:100%` these two
       * canvases get from their stylesheets (.pv-wallfx is `inset:0;
       * width:100%;height:100%` inside .pv-wallbox; .pl-back the same inside
       * the Listen host). From that frame on, `canvas.clientWidth` is just
       * reading back the pixel size this function last wrote, so the
       * measurement is SELF-REFERENTIAL and can never shrink. Sized once in
       * landscape, the canvas stayed landscape-wide forever: measured on the
       * tablet at 690x1154 as #pvWallFx standing 68px past the usable right
       * edge and .pv-wallbox clipping 78px of it, and 113px past at 600x1100.
       *
       * The rule the old note was guarding against is "never pass false
       * unless the canvas has an explicit CSS size" - and both of these have
       * one. With updateStyle off, CSS keeps the layout size, setPixelRatio
       * (set in build()) keeps the drawing buffer sharp, and a rotation is
       * picked up on the next frame because clientWidth is measuring the box
       * again rather than the last buffer. */
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    } else {
      var dpr = Math.min(2, root.devicePixelRatio || 1);
      if (this.canvas.width !== Math.round(w * dpr)) {
        this.canvas.width = Math.round(w * dpr);
        this.canvas.height = Math.round(h * dpr);
      }
    }
    return true;
  };

  /* Drift, then rewire the near ones. The box is a soft wall: a point that
   * reaches it turns around rather than being teleported, which would read
   * as a glitch to somebody actually watching. */
  /* HOW LOUD THE VOICE IS, 0..1.
   *
   * "I want that dot to basically explosion into a 3GS simulation of
   * undulating particles reacting to me talking." Reacting means the
   * points must MOVE with the voice, not merely be on screen while it
   * happens - so the loudness is pushed in here and the drift is scaled
   * by it. Smoothed on the way in, because a raw peak makes the cloud
   * jitter rather than breathe, and floored above zero so a quiet room
   * still drifts instead of freezing. */
  Plexus.prototype.level = function level(v) {
    var want = Math.max(0, Math.min(1, Number(v) || 0));
    this.voice = this.voice === undefined ? want
      : this.voice * 0.72 + want * 0.28;
    /* A SECOND, FASTER FOLLOWER, and the reason there are two.
     *
     * `voice` is smoothed both ways, which is right for the drift - a
     * raw peak makes the cloud jitter rather than breathe. It is wrong
     * for a swell: smoothed on the way UP, the cloud grows a beat after
     * the syllable that caused it, and a reaction that lags is read as a
     * reaction to something else. So `punch` rises INSTANTLY to whatever
     * was just heard and only the fall is eased. The cloud jumps on the
     * consonant and settles through the vowel, which is what a voice
     * looks like. */
    this.punch = this.punch === undefined ? want
      : Math.max(want, this.punch * 0.86);
  };

  /* THE VOICE ON THE SCALE THE EYE USES, 0..1.
   *
   * Measured on the tablet with the microphone open and the show playing
   * quietly beside it: the room sits at 0.02-0.05 and speech was measured
   * at a peak of 0.7385 (-2.6 dBFS). A linear reading would make the room
   * visible and speech merely more so. Multiplied by 2.6 and clamped, the
   * room is a twelfth of the range - a still cloud - and ordinary speech
   * fills it. The operator asked to be able to SEE that it is hearing him;
   * that means the difference between silence and his voice has to be the
   * whole picture, not a percentage of it. */
  Plexus.prototype.said = function said() {
    return Math.min(1, (this.punch || 0) * 2.6);
  };

  /* THE CLOUD PULSES, IT DOES NOT JUST HURRY.
   *
   * "I want to see the 3JS simulation undulate and pulse in accordance to
   * my voice signature as it's interpreting my voice coming through so
   * that way I know that it's happening."
   *
   * What was here did one thing with the loudness: it scaled the drift
   * SPEED. Measured on the device by driving level(0) and level(0.55) into
   * a scene and summing how far each point travelled over thirty frames -
   * 0.1285 against 0.5778, a real 4.5x - while the scene scale stayed at
   * 1, every point's scale stayed at 1 and both opacities never moved. So
   * the cloud was answering, but only by fidgeting faster inside the same
   * box, and points that bounce off a wall sooner do not read as a voice.
   * From a foot away it is indistinguishable from the idle animation,
   * which is exactly the complaint: there was no way to tell it was
   * hearing anything.
   *
   * Four things move now, and they are deliberately different KINDS of
   * movement so that no single one has to carry it:
   *   - the whole cloud SWELLS, which is the pulse itself;
   *   - it sways, slower than the swell, which is the undulation;
   *   - each point throbs on a travelling wave, so the cloud has an
   *     internal life rather than being one object being inflated;
   *   - points and links BRIGHTEN, which is what reads at a glance and
   *     across a room.
   * The drift keeps its speed term underneath all of it. */
  Plexus.prototype.drift = function drift() {
    var pts = this.points;
    var pos = this.linkPos;
    /* 1 at rest, up to about 4.5 when someone is talking into it. */
    var push = 1 + Math.min(1, (this.voice || 0) * 3.2) * 3.5;
    /* ONLY A CLOUD SOMEBODY IS TALKING TO PULSES. This same Plexus is the
     * video wall's transition, where level() is never called - it must
     * keep the rest appearance it was built with rather than being dimmed
     * to a talk dot's idle. `punch` is undefined until a voice arrives,
     * which is the honest test for "is anyone speaking to this one". */
    var voiced = this.punch !== undefined;
    var said = voiced ? this.said() : 0;
    var now = (root.performance && root.performance.now
      ? root.performance.now() : Date.now()) / 1000;

    if (voiced) {
      if (this.scene) {
        /* Scaling the SCENE and not the points moves the links with them -
         * the plexus swells as one thing, which is what a pulse is. */
        this.scene.scale.setScalar(
          1 + said * 0.40 + Math.sin(now * 5.4) * said * 0.11);
        this.scene.rotation.z = Math.sin(now * 1.3) * said * 0.14;
      }
      if (this.dotMat) this.dotMat.opacity = 0.5 + said * 0.5;
      if (this.links && this.links.material) {
        this.links.material.opacity = 0.16 + said * 0.6;
      }
      /* THE FOLLOWERS DECAY IN THE FRAME LOOP, NOT IN level().
       *
       * Nothing calls level() once the take is over - the dot stops
       * watching the moment it sends the clip - so a value that only fell
       * when it was written would hold the last syllable's swell through
       * the assembly of the words and all the way through the station's
       * thinking, and the cloud would look like it was still hearing
       * something. Decaying here means the pulse always returns to rest on
       * its own, whatever happens to the caller. */
      this.punch *= 0.90;
      this.voice = (this.voice || 0) * 0.94;
    }

    for (var i = 0; i < pts.length; i += 1) {
      /* The phase term is the point's index, so the throb travels across
       * the cloud instead of every point breathing in unison - which at
       * this count looks like one flashing object. */
      if (voiced) {
        pts[i].scale.setScalar(
          1 + said * (0.9 + Math.sin(now * 6.4 - i * 0.55) * 1.5));
      }
      var p = pts[i].position;
      var d = pts[i].userData.drift;
      var want = pts[i].userData.target;
      if (want) {
        /* Ease in, and keep easing: the letters hold while the reply is
         * being fetched, which is the moment the operator is reading
         * them. A one-shot tween would land and immediately wander. */
        p.x += (want.x - p.x) * 0.10;
        p.y += (want.y - p.y) * 0.10;
        p.z += (want.z - p.z) * 0.10;
        continue;
      }
      p.x += d.x * push;
      p.y += d.y * push;
      p.z += d.z * push;
      if (Math.abs(p.x) > 5.6) d.x = -d.x;
      if (Math.abs(p.y) > 3.2) d.y = -d.y;
      if (Math.abs(p.z) > 2.1) d.z = -d.z;
    }
    var n = 0;
    for (var a = 0; a < pts.length && n < this.linkMax; a += 1) {
      for (var b = a + 1; b < pts.length && n < this.linkMax; b += 1) {
        var pa = pts[a].position;
        var pb = pts[b].position;
        var dx = pa.x - pb.x, dy = pa.y - pb.y, dz = pa.z - pb.z;
        if (dx * dx + dy * dy + dz * dz > NEAR) continue;
        var o = n * 6;
        pos[o] = pa.x; pos[o + 1] = pa.y; pos[o + 2] = pa.z;
        pos[o + 3] = pb.x; pos[o + 4] = pb.y; pos[o + 5] = pb.z;
        n += 1;
      }
    }
    /* Only the filled part is drawn, or segments from a busier frame linger
     * as stray lines across the screen. */
    this.linkGeo.setDrawRange(0, n * 2);
    this.linkGeo.attributes.position.needsUpdate = true;
  };

  /* ASSEMBLE THE WORDS OUT OF THE CLOUD.
   *
   * "After I dictate something through it, I want to see the three JS
   * simulation build my speech and assemble it as it is put together with
   * particles and line work."
   *
   * The text is rastered once into a small offscreen canvas, its lit
   * pixels are sampled into target positions, and the existing points are
   * flown to them. The drifting cloud IS the speech coming together -
   * nothing new is created and nothing is faded in over the top, which is
   * what makes it read as assembly rather than as a caption appearing.
   *
   * The cloud is grown to fit the sentence. Thirty-four points spell
   * nothing; the count rises with the sampled target count and is capped,
   * because this tablet was measured at 148 MB free under a load average
   * of 25 and a legible word is not worth a stutter.
   *
   * Links are left to the ordinary drift code: once the points sit in the
   * shape of letters, the near-neighbour rule draws the strokes between
   * them by itself. That is the "line work", and it costs nothing extra.
   */
  /* A wrapped sentence has far more to draw than a single rule of tiny
   * type did, and a transcript that is not legible is not a transcript. */
  var ASSEMBLE_MAX = 420;

  Plexus.prototype.assemble = function assemble(text, THREE) {
    if (this.mode !== 'three' || !text) return;
    var targets = this.raster(String(text));
    if (!targets.length) return;

    /* Grow to fit. New points start where the cloud already is, so they
     * arrive as part of it rather than appearing from nowhere. */
    var want = Math.min(ASSEMBLE_MAX, targets.length);
    var Three = THREE || root.THREE;
    while (this.points.length < want && Three) {
      var seed = this.points[Math.floor(Math.random() * this.points.length)];
      var dot = new Three.Mesh(this.points[0].geometry, this.points[0].material);
      dot.position.copy(seed ? seed.position : new Three.Vector3());
      dot.userData.drift = new Three.Vector3(
        (Math.random() - 0.5) * 0.011,
        (Math.random() - 0.5) * 0.009,
        (Math.random() - 0.5) * 0.007);
      this.scene.add(dot);
      this.points.push(dot);
    }
    /* The link buffer was sized for the old count. */
    if (Three && this.points.length * 6 > this.linkMax) {
      this.linkMax = this.points.length * 6;
      this.linkPos = new Float32Array(this.linkMax * 6);
      this.linkGeo.setAttribute('position',
        new Three.BufferAttribute(this.linkPos, 3));
    }

    for (var i = 0; i < this.points.length; i += 1) {
      var t = targets[i % targets.length];
      this.points[i].userData.target = {x: t.x, y: t.y, z: (Math.random() - 0.5) * 0.5};
    }
    this.assembling = 1;          /* 1 -> 0 as it settles */
    this.holdUntil = 0;
  };

  /* Let the cloud go again. */
  Plexus.prototype.disperse = function disperse() {
    for (var i = 0; i < this.points.length; i += 1) {
      this.points[i].userData.target = null;
    }
    this.assembling = 0;
  };

  /* Where the letters are, in scene units. Sampled coarsely on purpose:
   * every lit pixel would be thousands of points and an unreadable smear. */
  /* WHERE THE LETTERS ARE, IN SCENE UNITS.
   *
   * "Instead of the particles becoming a line at the end, I want them to
   * become a transcript of what I'm saying."
   *
   * They were becoming a line, and this is why: the whole sentence was
   * laid on ONE row 220 px wide, and the fit loop shrank the type until it
   * got there - as far down as 7 px in a 54 px canvas. Sampled every two
   * pixels, a 7 px glyph contributes three or four dots, so a request of
   * any length arrived as a thin horizontal band. It was doing exactly
   * what it was told and what it was told was wrong.
   *
   * So the sentence is WRAPPED. Type is chosen to fill the block rather
   * than to squeeze onto a rule: the largest size at which the words fit
   * in at most LINES rows, which for a spoken request is normally two or
   * three and leaves the glyphs tall enough to sample properly.
   */
  var RASTER_W = 300;
  var RASTER_H = 120;
  var LINES = 3;

  Plexus.prototype.raster = function raster(text) {
    var pad = document.createElement('canvas');
    pad.width = RASTER_W; pad.height = RASTER_H;
    var g = pad.getContext('2d');
    if (!g) return [];
    g.fillStyle = '#000'; g.fillRect(0, 0, RASTER_W, RASTER_H);

    var words = String(text).trim().slice(0, 120);
    if (!words) return [];

    /* Come DOWN from a large size: the first one that fits is the biggest
     * one that fits, and big is the whole point. */
    var size = 34;
    var rows = null;
    while (size >= 9) {
      g.font = '700 ' + size + 'px system-ui, sans-serif';
      rows = wrap(g, words, RASTER_W - 12);
      if (rows.length <= LINES && rows.length * size * 1.22 <= RASTER_H - 8) break;
      size -= 2;
    }
    if (!rows || !rows.length) return [];

    g.fillStyle = '#fff';
    g.textBaseline = 'middle';
    g.textAlign = 'center';
    var step = size * 1.22;
    var top = (RASTER_H - (rows.length - 1) * step) / 2;
    for (var r = 0; r < rows.length; r += 1) {
      g.fillText(rows[r], RASTER_W / 2, top + r * step);
    }

    var data;
    try { data = g.getImageData(0, 0, RASTER_W, RASTER_H).data; }
    catch (err) { return []; }

    /* SPAN AND ASPECT TOGETHER. The block is RASTER_W by RASTER_H, so the
     * scene box must be SPAN by SPAN * (H / W) or the words come out
     * stretched - the same arithmetic slip that once turned the boot logo
     * into a vertical streak. */
    var SPAN = 11;
    var out = [];
    for (var y = 0; y < RASTER_H; y += 2) {
      for (var x = 0; x < RASTER_W; x += 2) {
        if (data[(y * RASTER_W + x) * 4] < 128) continue;
        out.push({
          x: (x / RASTER_W - 0.5) * SPAN,
          y: -(y / RASTER_H - 0.5) * SPAN * (RASTER_H / RASTER_W)
        });
      }
    }
    if (out.length > ASSEMBLE_MAX) {
      var keep = [];
      var stride = out.length / ASSEMBLE_MAX;
      for (var k = 0; k < ASSEMBLE_MAX; k += 1) keep.push(out[Math.floor(k * stride)]);
      return keep;
    }
    return out;
  };

  /* Greedy word wrap against a measured width. A word longer than the line
   * is left whole and allowed to overhang rather than being cut in half -
   * half a word is not a transcript. */
  function wrap(g, text, width) {
    var words = text.split(/\s+/).filter(Boolean);
    var rows = [];
    var line = '';
    for (var i = 0; i < words.length; i += 1) {
      var next = line ? line + ' ' + words[i] : words[i];
      if (line && g.measureText(next).width > width) {
        rows.push(line);
        line = words[i];
      } else {
        line = next;
      }
    }
    if (line) rows.push(line);
    return rows;
  }

  Plexus.prototype.flat = function flat() {
    var g = this.canvas.getContext('2d');
    if (!g) return;
    var dpr = Math.min(2, root.devicePixelRatio || 1);
    var w = this.canvas.width / dpr;
    var h = this.canvas.height / dpr;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    if (!this.flatPts) {
      this.flatPts = [];
      for (var k = 0; k < 26; k += 1) {
        this.flatPts.push({x: Math.random(), y: Math.random(),
          dx: (Math.random() - 0.5) * 0.0016,
          dy: (Math.random() - 0.5) * 0.0013});
      }
    }
    /* The flat fallback reacts to the voice as well - a terminal without
     * WebGL should still look like it is listening. */
    var flatPush = 1 + Math.min(1, (this.voice || 0) * 3.2) * 3.5;
    var flatSaid = this.said();
    var pts = this.flatPts;
    for (var i = 0; i < pts.length; i += 1) {
      pts[i].x += pts[i].dx * flatPush; pts[i].y += pts[i].dy * flatPush;
      if (pts[i].x < 0 || pts[i].x > 1) pts[i].dx = -pts[i].dx;
      if (pts[i].y < 0 || pts[i].y > 1) pts[i].dy = -pts[i].dy;
    }
    /* The flat road pulses too, by the same rule: a terminal without
     * WebGL still has to show that it is hearing. Reach and radius swell,
     * alpha lifts - the 3D road's swell, throb and brightness in the two
     * dimensions this one has. */
    var reach = Math.min(w, h) * (0.28 + flatSaid * 0.16);
    g.strokeStyle = '#65c7da';
    g.lineWidth = 1;
    for (var a = 0; a < pts.length; a += 1) {
      for (var b = a + 1; b < pts.length; b += 1) {
        var dx = (pts[a].x - pts[b].x) * w;
        var dy = (pts[a].y - pts[b].y) * h;
        var dist = Math.sqrt(dx * dx + dy * dy);
        if (dist > reach) continue;
        g.globalAlpha = (0.3 + flatSaid * 0.45) * (1 - dist / reach);
        g.beginPath();
        g.moveTo(pts[a].x * w, pts[a].y * h);
        g.lineTo(pts[b].x * w, pts[b].y * h);
        g.stroke();
      }
    }
    g.globalAlpha = 0.85;
    g.fillStyle = '#65c7da';
    var beat = (root.performance && root.performance.now
      ? root.performance.now() : Date.now()) / 1000;
    for (var p = 0; p < pts.length; p += 1) {
      g.beginPath();
      g.arc(pts[p].x * w, pts[p].y * h,
        1.7 * (1 + flatSaid * (0.9 + Math.sin(beat * 6.4 - p * 0.55) * 1.5)),
        0, Math.PI * 2);
      g.fill();
    }
    g.globalAlpha = 1;
  };

  Plexus.prototype.start = function start() {
    var self = this;
    if (this.frame) return;
    this.started = performance.now();
    this.canvas.style.display = 'block';
    var tick = function () {
      self.frame = requestAnimationFrame(tick);
      if (!self.size()) return;
      if (self.mode === 'three') {
        self.drift();
        self.renderer.render(self.scene, self.camera);
      } else {
        self.flat();
      }
    };
    this.frame = requestAnimationFrame(tick);
  };

  Plexus.prototype.stop = function stop() {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.canvas.style.display = 'none';
  };

  Plexus.prototype.dispose = function dispose() {
    this.stop();
    if (this.renderer) { try { this.renderer.dispose(); } catch (err) { /* gone */ } }
    this.renderer = null;
    this.points = [];
  };

  root.PineWallTransition = {
    create: function (canvas) { return new Plexus(canvas).build(); },
    ASSEMBLE_MAX: ASSEMBLE_MAX
  };
  /* The name it deserves now that it is used in more than one place. */
  root.PinePlexus = root.PineWallTransition;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineWallTransition;
  }
})(typeof window !== 'undefined' ? window : globalThis);
