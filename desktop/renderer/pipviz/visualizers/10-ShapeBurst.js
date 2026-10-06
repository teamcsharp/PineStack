/* 10 REACTIVE SHAPE BURST - playful symbols. Hundreds of abstract glyphs (an original set: circle, diamond,
 * cross, ring, triangle, star, hexagon, a bracket glyph; SDFs drawn on instanced quads) ride four
 * invisible drifting splines at different depths, spinning and breathing. A hard beat throws a burst:
 * dozens leave the stream with their own velocity, slow, and are drawn back by springs. Faint trails
 * come from persistence (the veil), as in Speed Lines.
 *   bass -> size and path deformation  mids -> travel speed  treble -> the small ones  rms -> glow  beat -> the burst
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, noise1, GLSL_NOISE } = PineViz.util, { stageCamera, halfExtent } = PineViz.shared;

  PineViz.register({
    id: 'shape-burst', index: 10, name: 'Shape Burst', blurb: 'reactive floating symbols', persist: true,
    defaults: { symbols: 480, trail: .6, bloom: .8 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, veil, veilMat, mesh, material, n = 0, items = [], paths = [], extent = { x: 8, y: 4.5 }, lastBeat = 0, dummy, burstLeft = 0, glyphAttr, sizeAttr, heatAttr;
      const KINDS = 8;
      function buildPaths() {
        paths = [];
        for (let i = 0; i < 4; i++) paths.push({ y: (i - 1.5) * .5, z: -2 - i * 2.2, seed: ctx.rng() * 30, amp: .5 + ctx.rng() * .8, speed: .25 + ctx.rng() * .3 });
      }
      function pointOn(path, u, t, s) {
        const x = (u - .5) * 2 * extent.x * 1.25;
        const y = path.y * extent.y + Math.sin(x * .33 + t * .22 + path.seed) * path.amp * extent.y * .32 * (1 + s.bass * .9) + noise1(x * .2 + t * .1 + path.seed) * extent.y * .14;
        return [x, y, path.z];
      }
      function build() {
        if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
        n = Math.max(80, Math.round((ctx.preset.symbols || 360) * ctx.quality.scale));
        const geo = new THREE.InstancedBufferGeometry(); const base = new THREE.PlaneGeometry(1, 1); geo.index = base.index; geo.attributes.position = base.attributes.position; geo.attributes.uv = base.attributes.uv;
        glyphAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1); sizeAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1); heatAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1);
        glyphAttr.setUsage(THREE.DynamicDrawUsage); heatAttr.setUsage(THREE.DynamicDrawUsage);
        geo.setAttribute('glyph', glyphAttr); geo.setAttribute('gsize', sizeAttr); geo.setAttribute('heat', heatAttr); geo.instanceCount = n;
        items = [];
        for (let i = 0; i < n; i++) {
          const small = ctx.rng() < .45;
          items.push({ path: i % 4, u: ctx.rng(), speed: .02 + ctx.rng() * .04, spin: (ctx.rng() - .5) * 2.4, angle: ctx.rng() * 6.3, size: small ? .12 + ctx.rng() * .14 : .25 + ctx.rng() * .4, small, kind: Math.floor(ctx.rng() * KINDS), seed: ctx.rng() * 10, burst: 0, vx: 0, vy: 0, vz: 0, ox: 0, oy: 0, oz: 0 });
          glyphAttr.setX(i, items[i].kind); sizeAttr.setX(i, items[i].size);
        }
        mesh = new THREE.Mesh(geo, material); mesh.frustumCulled = false; scene.add(mesh); dummy = new THREE.Object3D();
        mesh.instanceMatrix = new THREE.InstancedBufferAttribute(new Float32Array(n * 16), 16); mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage); geo.setAttribute('instanceMatrix', mesh.instanceMatrix);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 42, 10);
          const p = ctx.palette;
          veilMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(p.bg), transparent: true, opacity: .4, depthTest: false, depthWrite: false });
          veil = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), veilMat); veil.frustumCulled = false; veil.renderOrder = -10;
          veil.onBeforeRender = () => {}; const veilScene = veil; veilScene.material.onBeforeCompile = shader => { shader.vertexShader = shader.vertexShader.replace('#include <project_vertex>', 'gl_Position = vec4(position.xy, 0.9999, 1.0);'); }; veilMat.customProgramCacheKey = () => 'pineviz-veil';
          scene.add(veil);
          material = new THREE.ShaderMaterial({ transparent: true, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
            uniforms: { uTime: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uA: { value: new THREE.Color(p.secondary) }, uB: { value: new THREE.Color(p.primary) }, uC: { value: new THREE.Color(p.accent) }, uV: { value: new THREE.Color(ctx.palette.name === 'Monochrome' ? p.glow : '#b86bff') } },
            vertexShader: `attribute mat4 instanceMatrix; attribute float glyph; attribute float gsize; attribute float heat; varying vec2 vUv; varying float vGlyph; varying float vHeat; varying float vDepth;
              void main(){ vUv = uv; vGlyph = glyph; vHeat = heat; vec4 mv = modelViewMatrix * instanceMatrix * vec4(position * gsize, 1.0); vDepth = clamp(1.0 - (-mv.z - 4.0) / 14.0, 0.0, 1.0); gl_Position = projectionMatrix * mv; }`,
            fragmentShader: `uniform float uRms; uniform float uEnergy; uniform vec3 uA; uniform vec3 uB; uniform vec3 uC; uniform vec3 uV; varying vec2 vUv; varying float vGlyph; varying float vHeat; varying float vDepth;
              float sdCircle(vec2 p, float r){ return length(p) - r; }
              float sdBox(vec2 p, vec2 b){ vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
              float sdTri(vec2 p, float r){ const float k = sqrt(3.0); p.x = abs(p.x) - r; p.y = p.y + r / k; if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) / 2.0; p.x -= clamp(p.x, -2.0 * r, 0.0); return -length(p) * sign(p.y); }
              float sdHex(vec2 p, float r){ const vec3 k = vec3(-0.866025404, 0.5, 0.577350269); p = abs(p); p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy; p -= vec2(clamp(p.x, -k.z * r, k.z * r), r); return length(p) * sign(p.y); }
              float sdStar(vec2 p, float r){ const float an = 0.628318; const float en = 0.9; vec2 acs = vec2(cos(an), sin(an)); vec2 ecs = vec2(cos(en), sin(en)); float bn = mod(atan(p.x, p.y), 2.0 * an) - an; p = length(p) * vec2(cos(bn), abs(sin(bn))); p -= r * acs; p += ecs * clamp(-dot(p, ecs), 0.0, r * acs.y / ecs.y); return length(p) * sign(p.x); }
              void main(){ vec2 p = vUv - 0.5; int g = int(vGlyph + 0.5); float d = 1.0; float w = 0.055;
                if (g == 0) d = abs(sdCircle(p, 0.3)) - w;                                                  /* ring */
                else if (g == 1) d = abs(sdBox(vec2(p.x + p.y, p.x - p.y) * 0.7071, vec2(0.26))) - w;        /* diamond outline */
                else if (g == 2) d = min(sdBox(p, vec2(0.34, w)), sdBox(p, vec2(w, 0.34)));                   /* cross */
                else if (g == 3) d = sdCircle(p, 0.24);                                                       /* filled dot */
                else if (g == 4) d = abs(sdTri(p * 1.1, 0.26)) - w;                                           /* triangle */
                else if (g == 5) d = sdStar(p * 1.2, 0.3);                                                    /* star */
                else if (g == 6) d = abs(sdHex(p, 0.28)) - w;                                                 /* hexagon */
                else d = min(abs(sdBox(p + vec2(0.18, 0.0), vec2(0.06, 0.3))) - w * 0.6, abs(sdBox(p - vec2(0.18, 0.0), vec2(0.06, 0.3))) - w * 0.6);   /* bracket glyph */
                float edge = fwidth(d) * 1.2; float a = 1.0 - smoothstep(0.0, edge, d);
                float glowA = exp(-max(d, 0.0) * 14.0) * 0.35;
                vec3 c = mix(uB, uA, vDepth * 0.7); c = mix(c, uV, step(4.5, vGlyph) * 0.5); c = mix(c, uC, vHeat * 0.7);
                float lum = (0.35 + 0.4 * uRms + 0.25 * uEnergy + vHeat * 0.5) * (0.35 + 0.65 * vDepth);
                gl_FragColor = vec4(c * lum, (a + glowA) * lum); }` });
          buildPaths(); build();
        },
        activate() {}, deactivate() {},
        palette(p) { veilMat.color.set(p.bg); const u = material.uniforms; u.uA.value.set(p.secondary); u.uB.value.set(p.primary); u.uC.value.set(p.accent); u.uV.value.set(p.name === 'Monochrome' ? p.glow : '#b86bff'); },
        presetChanged(key) { if (key === 'symbols' || key === null) build(); },
        update(s, dt, t) {
          const idle = .25 + .75 * clamp(s.energy * 1.5, 0, 1), m = (ctx.preset.motionAmount ?? 1);
          let burst = false;
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; if (s.beat > .78 && burstLeft <= 0) { burst = true; burstLeft = .6; } }
          burstLeft -= dt;
          let thrown = 0;
          for (let i = 0; i < n; i++) {
            const it = items[i], path = paths[it.path];
            it.u = (it.u + dt * it.speed * (.4 + s.mid * 2.2 + .3 * idle) * m) % 1;
            const [px, py, pz] = pointOn(path, it.u, t * idle, s);
            if (burst && thrown < 40 && ctx.rng() < .35) { thrown++; it.burst = 1; const a = ctx.rng() * 6.283, sp = 3 + ctx.rng() * 5; it.vx = Math.cos(a) * sp; it.vy = Math.sin(a) * sp; it.vz = (ctx.rng() - .5) * 4; }
            if (it.burst > 0) {
              /* thrown: drag slows it; a spring draws it home; the burst ends when it is back */
              it.vx -= it.ox * 6 * dt + it.vx * 1.6 * dt; it.vy -= it.oy * 6 * dt + it.vy * 1.6 * dt; it.vz -= it.oz * 6 * dt + it.vz * 1.6 * dt;
              it.ox += it.vx * dt; it.oy += it.vy * dt; it.oz += it.vz * dt;
              it.burst = Math.max(0, it.burst - dt * .25); if (Math.hypot(it.ox, it.oy, it.oz) < .05 && Math.hypot(it.vx, it.vy) < .2) { it.burst = 0; it.ox = it.oy = it.oz = 0; }
            }
            it.angle += dt * it.spin * (.5 + s.mid + it.burst * 2) * m;
            const grow = 1 + s.bass * (it.small ? .2 : .55) + it.burst * .4 + Math.sin(t * 1.3 + it.seed) * .08;
            const show = it.small ? clamp((s.treble - .08) * 4 + it.burst, 0, 1) : 1;
            dummy.position.set(px + it.ox, py + it.oy, pz + it.oz); dummy.rotation.set(0, 0, it.angle); dummy.scale.setScalar(grow * show * (ctx.preset.intensity || 1)); dummy.updateMatrix();
            dummy.matrix.toArray(mesh.instanceMatrix.array, i * 16);
            heatAttr.setX(i, clamp(it.burst * 1.2 + s.beat * .4, 0, 1));
          }
          mesh.instanceMatrix.needsUpdate = true; heatAttr.needsUpdate = true;
          material.uniforms.uTime.value = t; material.uniforms.uRms.value = s.rms; material.uniforms.uEnergy.value = s.energy;
          veilMat.opacity = clamp(1 - (ctx.preset.trail ?? .55), .08, .9);
        },
        resize(w, h) { camera.fitAspect(w / h); extent = halfExtent(camera, 10 + 4); },
        dispose() { mesh?.geometry.dispose(); material?.dispose(); veil?.geometry.dispose(); veilMat?.dispose(); mesh = null; },
        count() { return n; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
