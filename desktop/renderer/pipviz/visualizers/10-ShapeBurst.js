/* 10 REACTIVE SHAPE BURST - the panel: a near-black field, one stream of blue light sweeping up from the
 * lower left, and glyphs floating in depth at every scale - a few HUGE outlined ones (a cross, a square,
 * a triangle, a ring), some medium, hundreds tiny - blue on the left turning violet on the right, each a
 * thin neon outline that the bloom lights. The Pine Box mark (the stacked pine on its base) floats among
 * them in the same outline, at the same spread of sizes. Glyphs are SDFs on instanced quads, tilted a
 * little in 3D so the big ones read as plates drifting past; the stream is one strip mesh of filaments.
 *   bass -> the stream's swell and the glyphs' breathing  mids -> drift  treble -> the tiny ones twinkle
 *   rms -> glow  beat -> a burst: a handful leave the field with their own velocity and are drawn back
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { Spring, stageCamera, halfExtent } = PineViz.shared;

  PineViz.register({
    id: 'shape-burst', index: 10, name: 'Shape Burst', blurb: 'reactive floating symbols',
    defaults: { symbols: 320, pine: .28, bloom: .7, intensity: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, field, mesh, material, n = 0, items = [], extent = { x: 8, y: 4.5 }, half = { x: 8, y: 4.5 };
      let lastBeat = 0, burstLeft = 0, dummy, glyphAttr, sizeAttr, heatAttr, stream = [], pulse, clock = 0;
      const DIST = 12, SEG = 160, KINDS = 5;   /* 0 ring, 1 square, 2 cross, 3 triangle, 4 the Pine Box mark */

      /* ---- the field: near black, a blue haze low on the left where the stream rises */
      function fieldBackdrop(p) {
        const geo = new THREE.PlaneGeometry(2, 2);
        const mat = new THREE.ShaderMaterial({ depthTest: false, depthWrite: false,
          uniforms: { uA: { value: new THREE.Color(p.bg) }, uB: { value: new THREE.Color(p.bg2) }, uEnergy: { value: 0 } },
          vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.999, 1.0); }`,
          fragmentShader: `uniform vec3 uA; uniform vec3 uB; uniform float uEnergy; varying vec2 vUv;
            void main(){
              vec3 c = uA * mix(0.55, 0.25, smoothstep(0.0, 1.0, vUv.y));
              vec2 d1 = (vUv - vec2(0.18, 0.22)) * vec2(1.0, 1.5);
              c += uB * 0.22 * exp(-dot(d1, d1) * 3.5) * (0.8 + 0.4 * uEnergy);
              gl_FragColor = vec4(c, 1.0); }` });
        const m = new THREE.Mesh(geo, mat); m.frustumCulled = false; m.renderOrder = -1000;
        m.setPalette = q => { mat.uniforms.uA.value.set(q.bg); mat.uniforms.uB.value.set(q.bg2); };
        m.tick = e => { mat.uniforms.uEnergy.value = e; };
        m.dispose = () => { geo.dispose(); mat.dispose(); };
        return m;
      }

      /* ---- the stream of light: a strip mesh of filaments, one band, shaped in the vertex shader */
      function strips(count, place) {
        const rows = SEG + 1, verts = count * rows * 2;
        const aU = new Float32Array(verts), aSide = new Float32Array(verts), aInfo = new Float32Array(verts * 4);
        const index = new Uint32Array(count * SEG * 6);
        let v = 0, k = 0;
        for (let s = 0; s < count; s++) {
          const frac = place === 'centre' ? .5 : (s + .5) / count, r1 = ctx.rng(), r2 = ctx.rng(), base = s * rows * 2;
          for (let i = 0; i < rows; i++) {
            for (let side = -1; side <= 1; side += 2) {
              aU[v] = i / SEG; aSide[v] = side;
              aInfo[v * 4] = place === 'centre' ? .5 : frac + (r1 - .5) * .06; aInfo[v * 4 + 1] = 0; aInfo[v * 4 + 2] = r1; aInfo[v * 4 + 3] = r2;
              v++;
            }
            if (i < SEG) { const a = base + i * 2; index[k++] = a; index[k++] = a + 1; index[k++] = a + 2; index[k++] = a + 1; index[k++] = a + 3; index[k++] = a + 2; }
          }
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('aU', new THREE.BufferAttribute(aU, 1)); geo.setAttribute('aSide', new THREE.BufferAttribute(aSide, 1));
        geo.setAttribute('aInfo', new THREE.BufferAttribute(aInfo, 4)); geo.setIndex(new THREE.BufferAttribute(index, 1));
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts * 3), 3));
        return geo;
      }
      const STREAM_VERT = `${GLSL_NOISE}
        attribute float aU; attribute float aSide; attribute vec4 aInfo;
        uniform float uTime; uniform float uBass; uniform float uMid; uniform float uPulse; uniform float uSeed; uniform float uWidth; uniform float uSpread; uniform float uVeil;
        uniform vec2 uHalf;
        varying float vSide; varying float vU; varying float vFan; varying float vRand;
        float band_y(float x, float t) {
          float u = x / uHalf.x;
          float rise = u * uHalf.y * 0.34 - uHalf.y * 0.22;                                 /* low left, across to the right middle */
          float swell = sin(u * 2.2 + t * 0.19 + uSeed) * uHalf.y * (0.12 + 0.10 * uBass);
          float wave = sin(u * 4.8 - t * 0.11 + uSeed * 1.7) * uHalf.y * (0.05 + 0.04 * uBass);
          float drift = pv_snoise(vec3(u + uSeed, t * 0.05, 1.0)) * uHalf.y * 0.07;
          return rise + swell + wave + drift;
        }
        float fan_at(float x, float t, float r) { return 0.5 + 0.5 * sin(x / uHalf.x * 2.1 + t * 0.15 + uSeed * 0.7 + r * 0.9); }
        float strand_y(float x, vec4 info, float t) {
          float fan = fan_at(x, t, info.z);
          float off = (info.x - 0.5) * 2.0;
          float y = band_y(x, t) + off * mix(0.15, 1.0, fan) * uSpread * uHalf.y * (0.75 + 0.5 * info.w);
          y += sin(x * 1.4 + t * 0.6 + info.w * 7.0) * uHalf.y * (0.004 + 0.04 * uMid) * (0.5 + info.z);
          return y;
        }
        void main() {
          float x = (aU - 0.5) * 2.0 * uHalf.x * 1.15;
          float t = uTime;
          float y = strand_y(x, aInfo, t), y2 = strand_y(x + 0.05, aInfo, t);
          vec2 tang = normalize(vec2(0.05, y2 - y)); vec2 nrm = vec2(-tang.y, tang.x);
          float fan = fan_at(x, t, aInfo.z);
          float w = uWidth * (0.5 + aInfo.w) * (1.0 + uPulse * 0.5);
          w *= mix(1.0, 0.7 + 0.6 * fan, uVeil);
          vec3 p = vec3(vec2(x, y) + nrm * aSide * w, -3.0);
          vSide = aSide; vU = aU; vFan = fan; vRand = aInfo.w;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        }`;
      const STREAM_FRAG = `
        uniform vec3 uA; uniform vec3 uB; uniform vec3 uWhite; uniform float uRms; uniform float uTreble; uniform float uEnergy; uniform float uAlpha; uniform float uVeil;
        varying float vSide; varying float vU; varying float vFan; varying float vRand;
        void main() {
          float a = exp(-vSide * vSide * mix(3.5, 2.0, uVeil));
          float ends = smoothstep(0.0, 0.12, vU) * smoothstep(1.0, 0.86, vU);
          float conv = 1.0 - vFan;
          float lum = (0.5 + 0.5 * conv) * (0.7 + 0.5 * uRms + 0.3 * uEnergy);
          vec3 c = mix(uA, uB, conv * 0.5 + vRand * 0.2);
          c = mix(c, uWhite, conv * conv * (0.35 + 0.45 * uTreble) * (1.0 - uVeil * 0.8));
          gl_FragColor = vec4(c * lum, a * ends * uAlpha); }`;
      function streamMaterial(colorA, colorB, alpha, width, spread, veil, seed) {
        return new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
          uniforms: { uTime: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uPulse: { value: 0 }, uSeed: { value: seed },
            uWidth: { value: width }, uSpread: { value: spread }, uVeil: { value: veil }, uAlpha: { value: alpha }, uHalf: { value: new THREE.Vector2(half.x, half.y) },
            uA: { value: new THREE.Color(colorA) }, uB: { value: new THREE.Color(colorB) }, uWhite: { value: new THREE.Color(ctx.palette.accent) } },
          vertexShader: STREAM_VERT, fragmentShader: STREAM_FRAG });
      }
      function buildStream() {
        for (const l of stream) { scene.remove(l.mesh); l.mesh.geometry.dispose(); l.mat.dispose(); }
        stream = [];
        const p = ctx.palette, seed = ctx.rng() * 20, strands = Math.max(8, Math.round(22 * (ctx.quality.scale < .5 ? .6 : 1)));
        const add = (geo, mat) => { const m = new THREE.Mesh(geo, mat); m.frustumCulled = false; scene.add(m); stream.push({ mesh: m, mat }); };
        add(strips(2, 'centre'), streamMaterial(p.glow, p.secondary, .12, .8, .3, 1, seed));       /* the soft veil under the light */
        add(strips(strands, 'spread'), streamMaterial(p.secondary, p.glow, .3, .02, .3, 0, seed));   /* the filaments */
        add(strips(3, 'spread'), streamMaterial(p.accent, p.secondary, .5, .022, .26, 0, seed));     /* a few white threads */
      }

      /* ---- the glyphs: a power law of sizes, every kind, floating in depth */
      function build() {
        if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
        n = Math.max(60, Math.round((ctx.preset.symbols || 320) * ctx.quality.scale));
        const geo = new THREE.InstancedBufferGeometry(); const base = new THREE.PlaneGeometry(1, 1); geo.index = base.index; geo.attributes.position = base.attributes.position; geo.attributes.uv = base.attributes.uv;
        glyphAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1); sizeAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1); heatAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1);
        heatAttr.setUsage(THREE.DynamicDrawUsage);
        geo.setAttribute('glyph', glyphAttr); geo.setAttribute('gsize', sizeAttr); geo.setAttribute('heat', heatAttr); geo.instanceCount = n;
        items = [];
        const pineShare = clamp(ctx.preset.pine ?? .28, 0, 1);
        for (let i = 0; i < n; i++) {
          const r = ctx.rng();
          /* the scale differential of the panel: most tiny, some medium, a few large, two or three huge */
          const tier = r < .66 ? 0 : r < .9 ? 1 : r < .982 ? 2 : 3;
          const size = tier === 0 ? .07 + ctx.rng() * .1 : tier === 1 ? .24 + ctx.rng() * .26 : tier === 2 ? .7 + ctx.rng() * .6 : 2.2 + ctx.rng() * 1.3;
          const kind = ctx.rng() < pineShare ? 4 : Math.floor(ctx.rng() * 4);
          items.push({ kind, size, tier, seed: ctx.rng() * 100,
            x: (ctx.rng() - .5) * 2, y: (ctx.rng() - .5) * 2, z: tier === 3 ? -1 + ctx.rng() * 2.5 : tier === 2 ? -4 + ctx.rng() * 4 : -8 + ctx.rng() * 9,
            vx: (ctx.rng() - .5) * .04, vy: .01 + ctx.rng() * .03, spin: (ctx.rng() - .5) * (tier >= 2 ? .25 : .9),
            angle: ctx.rng() * 6.3, tiltX: (ctx.rng() - .5) * .9, tiltY: (ctx.rng() - .5) * .9, wobble: ctx.rng() * 6.3,
            ox: 0, oy: 0, oz: 0, bvx: 0, bvy: 0, bvz: 0, burst: 0 });
          glyphAttr.setX(i, kind); sizeAttr.setX(i, size);
        }
        mesh = new THREE.Mesh(geo, material); mesh.frustumCulled = false; scene.add(mesh); dummy = new THREE.Object3D();
        mesh.instanceMatrix = new THREE.InstancedBufferAttribute(new Float32Array(n * 16), 16); mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage); geo.setAttribute('instanceMatrix', mesh.instanceMatrix);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 44, DIST);
          half = halfExtent(camera, DIST + 3); extent = halfExtent(camera, DIST);
          field = fieldBackdrop(ctx.palette); scene.add(field);
          pulse = new Spring(70, 9, 0);
          const p = ctx.palette;
          material = new THREE.ShaderMaterial({ transparent: true, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
            uniforms: { uTime: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uTreble: { value: 0 }, uHalfX: { value: half.x },
              uBlue: { value: new THREE.Color(p.secondary) }, uDeep: { value: new THREE.Color(p.primary) }, uWhite: { value: new THREE.Color(p.accent) },
              uViolet: { value: new THREE.Color(p.name === 'Monochrome' ? p.glow : '#9b5cff') } },
            vertexShader: `attribute mat4 instanceMatrix; attribute float glyph; attribute float gsize; attribute float heat;
              uniform float uHalfX;
              varying vec2 vUv; varying float vGlyph; varying float vHeat; varying float vDepth; varying float vHue; varying float vSize;
              void main(){ vUv = uv; vGlyph = glyph; vHeat = heat; vSize = gsize;
                vec4 world = instanceMatrix * vec4(position * gsize, 1.0);
                vHue = clamp(world.x / uHalfX * 0.5 + 0.5, 0.0, 1.0);
                vec4 mv = modelViewMatrix * world;
                vDepth = clamp(1.0 - (-mv.z - 5.0) / 16.0, 0.0, 1.0);
                gl_Position = projectionMatrix * mv; }`,
            fragmentShader: `uniform float uRms; uniform float uEnergy; uniform float uTreble; uniform vec3 uBlue; uniform vec3 uDeep; uniform vec3 uWhite; uniform vec3 uViolet;
              varying vec2 vUv; varying float vGlyph; varying float vHeat; varying float vDepth; varying float vHue; varying float vSize;
              float sdCircle(vec2 p, float r){ return length(p) - r; }
              float sdRBox(vec2 p, vec2 b, float r){ vec2 d = abs(p) - b + r; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r; }
              float sdTri(vec2 p, float r){ const float k = sqrt(3.0); p.x = abs(p.x) - r; p.y = p.y + r / k; if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) / 2.0; p.x -= clamp(p.x, -2.0 * r, 0.0); return -length(p) * sign(p.y); }
              float sdIso(vec2 p, vec2 q){ p.x = abs(p.x); vec2 a = p - q * clamp(dot(p, q) / dot(q, q), 0.0, 1.0); vec2 b = p - q * vec2(clamp(p.x / q.x, 0.0, 1.0), 1.0); float s = -sign(q.y); vec2 d = min(vec2(dot(a, a), s * (p.x * q.y - p.y * q.x)), vec2(dot(b, b), s * (p.y - q.y))); return -sqrt(d.x) * sign(d.y); }
              float sdPine(vec2 p){
                /* the Pine Box mark: three tiers of one pine pointing up (apex at the top of each tier), on a rounded base */
                float t1 = sdIso(p - vec2(0.0, 0.38), vec2(0.15, -0.26));
                float t2 = sdIso(p - vec2(0.0, 0.24), vec2(0.21, -0.30));
                float t3 = sdIso(p - vec2(0.0, 0.08), vec2(0.27, -0.34));
                float tree = min(min(t1, t2), t3);
                float base = sdRBox(p - vec2(0.0, -0.35), vec2(0.30, 0.07), 0.06);
                return min(tree, base);
              }
              void main(){ vec2 p = vUv - 0.5; int g = int(vGlyph + 0.5); float d = 1.0;
                float w = clamp(0.014 + 0.004 / max(0.05, vSize), 0.012, 0.05);                 /* thin neon strokes; the tiny ones a touch heavier */
                if (g == 0) d = abs(sdCircle(p, 0.31)) - w;                                       /* ring */
                else if (g == 1) d = abs(sdRBox(p, vec2(0.27), 0.05)) - w;                        /* rounded square */
                else if (g == 2) { vec2 q = vec2(p.x + p.y, p.x - p.y) * 0.7071; d = min(sdRBox(q, vec2(0.34, w * 0.9), w * 0.9), sdRBox(q, vec2(w * 0.9, 0.34), w * 0.9)); }   /* the cross */
                else if (g == 3) d = abs(sdTri(vec2(p.x, -p.y) * 1.05, 0.27)) - w;                /* triangle, point up */
                else d = abs(sdPine(p)) - w;                                                      /* the Pine Box mark */
                float edge = fwidth(d) * 1.2; float a = 1.0 - smoothstep(0.0, edge, d);
                float glowA = max(0.0, exp(-max(d, 0.0) * mix(24.0, 11.0, clamp(vSize, 0.0, 1.0))) - 0.03) * 0.5;   /* the glow dies before the quad's edge, so a big glyph never shows its plate */
                vec3 c = mix(uBlue, uViolet, smoothstep(0.25, 0.85, vHue));
                c = mix(c, uDeep, (1.0 - vDepth) * 0.35);
                c = mix(c, uWhite, vHeat * 0.5 + (1.0 - vHue) * 0.12 * step(0.5, vSize));
                float lum = min(1.0, (0.62 + 0.25 * uRms + 0.2 * uEnergy + vHeat * 0.3 + 0.12 * step(0.5, vSize)) * (0.45 + 0.55 * vDepth));
                gl_FragColor = vec4(c * lum, (a + glowA) * lum); }` });
          buildStream(); build();
        },
        activate() {}, deactivate() {},
        palette(p) {
          field.setPalette(p);
          const u = material.uniforms; u.uBlue.value.set(p.secondary); u.uDeep.value.set(p.primary); u.uWhite.value.set(p.accent); u.uViolet.value.set(p.name === 'Monochrome' ? p.glow : '#9b5cff');
          const cols = [[p.glow, p.secondary], [p.secondary, p.glow], [p.accent, p.secondary]];
          stream.forEach((l, i) => { l.mat.uniforms.uA.value.set(cols[i][0]); l.mat.uniforms.uB.value.set(cols[i][1]); l.mat.uniforms.uWhite.value.set(p.accent); });
        },
        presetChanged(key) { if (key === 'symbols' || key === 'pine' || key === null) build(); },
        update(s, dt, t) {
          const idle = .3 + .7 * clamp(s.energy * 1.5, 0, 1), m = (ctx.preset.motionAmount ?? 1);
          clock += dt * (0.5 + 0.6 * clamp(s.energy * 1.3, 0, 1)) * (ctx.preset.speed || 1);
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; pulse.push(1.4 * s.beat); }
          pulse.step(dt);
          let burst = false;
          if (s.beat > .78 && burstLeft <= 0 && s.beatCount !== (update.burstBeat || -1)) { burst = true; burstLeft = .6; update.burstBeat = s.beatCount; }
          burstLeft -= dt;
          let thrown = 0;
          const gain = (ctx.preset.intensity || 1);
          for (let i = 0; i < n; i++) {
            const it = items[i];
            /* a slow drift upward and across; wrap at the edges so the field never empties */
            it.x += it.vx * dt * (.4 + s.mid * 1.5) * m; it.y += it.vy * dt * (.4 + s.mid * 1.5) * m * idle;
            if (it.y > 1.25) { it.y = -1.25; it.x = (ctx.rng() - .5) * 2; }
            if (it.x > 1.3) it.x = -1.3; else if (it.x < -1.3) it.x = 1.3;
            if (burst && thrown < 24 && it.tier <= 1 && ctx.rng() < .3) { thrown++; it.burst = 1; const a = ctx.rng() * 6.283, sp = 2 + ctx.rng() * 4; it.bvx = Math.cos(a) * sp; it.bvy = Math.sin(a) * sp; it.bvz = (ctx.rng() - .5) * 3; }
            if (it.burst > 0) {
              it.bvx -= it.ox * 6 * dt + it.bvx * 1.6 * dt; it.bvy -= it.oy * 6 * dt + it.bvy * 1.6 * dt; it.bvz -= it.oz * 6 * dt + it.bvz * 1.6 * dt;
              it.ox += it.bvx * dt; it.oy += it.bvy * dt; it.oz += it.bvz * dt;
              it.burst = Math.max(0, it.burst - dt * .25); if (Math.hypot(it.ox, it.oy, it.oz) < .05 && Math.hypot(it.bvx, it.bvy) < .2) { it.burst = 0; it.ox = it.oy = it.oz = 0; }
            }
            it.angle += dt * it.spin * (.4 + s.mid * .8 + it.burst * 2) * m;
            const breathe = 1 + s.bass * (it.tier >= 2 ? .12 : .3) + it.burst * .35 + Math.sin(clock * 1.1 + it.seed) * .05;
            const show = it.tier === 0 ? .55 + .45 * clamp((s.treble - .05) * 3 + it.burst, 0, 1) : 1;
            const px = it.x * extent.x * 1.05 + it.ox, py = it.y * extent.y * 1.05 + it.oy, pz = it.z + it.oz;
            dummy.position.set(px, py, pz);
            dummy.rotation.set(it.tiltX * Math.sin(clock * .2 + it.wobble), it.tiltY * Math.cos(clock * .17 + it.wobble), it.angle);
            dummy.scale.setScalar(breathe * show * gain); dummy.updateMatrix();
            dummy.matrix.toArray(mesh.instanceMatrix.array, i * 16);
            heatAttr.setX(i, clamp(it.burst * 1.2 + s.beat * .35 * (it.tier >= 2 ? 1 : .5), 0, 1));
          }
          mesh.instanceMatrix.needsUpdate = true; heatAttr.needsUpdate = true;
          material.uniforms.uTime.value = t; material.uniforms.uRms.value = s.rms; material.uniforms.uEnergy.value = s.energy; material.uniforms.uTreble.value = s.treble;
          field.tick(s.energy);
          for (const l of stream) {
            const u = l.mat.uniforms; u.uTime.value = clock; u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble;
            u.uRms.value = s.rms * gain; u.uEnergy.value = s.energy; u.uPulse.value = clamp(pulse.value, -.4, 1.2);
          }
        },
        resize(w, h) {
          camera.fitAspect(w / h); half = halfExtent(camera, DIST + 3); extent = halfExtent(camera, DIST);
          material.uniforms.uHalfX.value = extent.x;
          for (const l of stream) l.mat.uniforms.uHalf.value.set(half.x, half.y);
        },
        dispose() { mesh?.geometry.dispose(); material?.dispose(); for (const l of stream) { l.mesh.geometry.dispose(); l.mat.dispose(); } stream = []; field?.dispose(); mesh = null; },
        count() { return n; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
