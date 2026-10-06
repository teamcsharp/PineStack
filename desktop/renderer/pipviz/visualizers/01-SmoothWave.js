/* 01 SMOOTH WAVE - flowing ribbons. Four to eight translucent silk ribbons across a deep blue field,
 * each a strip mesh laid along its own drifting spline (noise-driven oscillators, never a plain sine),
 * at its own depth and speed for parallax. The centre stays open for the radio UI.
 *   rms -> amplitude  bass -> the long slow swell  mids -> ripples  treble -> edge light
 *   beat -> a width pulse through a spring  silence -> a slow, graceful idle
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { noise2, noise1, clamp, lerp, GLSL_NOISE } = PineViz.util, { Spring, gradientBackdrop, stageCamera, halfExtent } = PineViz.shared;

  PineViz.register({
    id: 'smooth-wave', index: 1, name: 'Smooth Wave', blurb: 'flowing ribbons',
    defaults: { ribbons: 6, width: 1, bloom: .55, intensity: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, ribbons = [], pulse, time = 0, extent = { x: 8, y: 4.5 };
      const SEGMENTS = 160;
      function ribbonMaterial(colorA, colorB) {
        return new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
          uniforms: { uA: { value: new THREE.Color(colorA) }, uB: { value: new THREE.Color(colorB) }, uWhite: { value: new THREE.Color(ctx.palette.accent) }, uOpacity: { value: .45 }, uEdge: { value: 0 }, uTime: { value: 0 }, uShift: { value: 0 } },
          vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
          fragmentShader: `${GLSL_NOISE} uniform vec3 uA; uniform vec3 uB; uniform vec3 uWhite; uniform float uOpacity; uniform float uEdge; uniform float uTime; uniform float uShift; varying vec2 vUv;
            void main(){ float across = abs(vUv.y - 0.5) * 2.0;
              float body = pow(1.0 - across, 1.15);                              /* silk: bright core, soft edges */
              float sheen = pow(1.0 - abs(across - 0.55) * 2.2, 6.0) * (0.5 + 0.5 * sin(vUv.x * 18.0 - uTime * 2.0 + uShift));
              float grain = pv_fbm(vec3(vUv.x * 9.0 + uShift, vUv.y * 3.0, uTime * 0.25)) * 0.5 + 0.5;
              vec3 c = mix(uA, uB, vUv.x * 0.6 + grain * 0.4) * body + uWhite * max(0.0, sheen) * (0.35 + uEdge);
              float ends = smoothstep(0.0, 0.08, vUv.x) * smoothstep(1.0, 0.92, vUv.x);
              gl_FragColor = vec4(c, (body * 0.85 + sheen * 0.4) * uOpacity * ends); }` });
      }
      function build() {
        const n = Math.max(3, Math.min(8, Math.round((ctx.preset.ribbons || 6) * (ctx.quality.scale < .5 ? .7 : 1))));
        for (const r of ribbons) { scene.remove(r.mesh); r.mesh.geometry.dispose(); r.mesh.material.dispose(); }
        ribbons = [];
        const p = ctx.palette;
        for (let i = 0; i < n; i++) {
          const geo = new THREE.PlaneGeometry(1, 1, SEGMENTS, 1);
          const mat = ribbonMaterial(i % 2 ? p.primary : p.secondary, i % 3 ? p.secondary : p.glow);
          const mesh = new THREE.Mesh(geo, mat); mesh.frustumCulled = false;
          const seed = ctx.rng() * 100, depth = -2 - i * 1.1 - ctx.rng() * .6;
          ribbons.push({ mesh, seed, depth, speed: .22 + ctx.rng() * .25, y: (ctx.rng() - .5) * 1.4, baseWidth: .38 + ctx.rng() * .5, phase: ctx.rng() * 9, tilt: (ctx.rng() - .5) * .3 });
          mesh.position.z = depth; mat.uniforms.uOpacity.value = .32 + .18 * (1 - i / n); mat.uniforms.uShift.value = seed;
          scene.add(mesh);
        }
      }
      /* the centreline of a ribbon: drifting oscillators and fbm, scaled by the audio terms */
      function centre(r, x, t, s) {
        const slow = noise2(x * .22 + r.seed, t * .11 + r.phase) * (1.1 + s.bass * 2.6);
        const swell = Math.sin(x * .55 + t * .35 * r.speed * 2 + noise1(t * .07 + r.seed) * 3) * (.35 + s.bass * 1.1);
        const ripple = noise2(x * 1.3 + r.seed * 2, t * .6) * (.12 + s.mid * .7);
        const fine = noise2(x * 2.4 + r.seed, t * 1.6) * (.01 + s.treble * .09);
        const amp = (.45 + s.rms * 1.1 + s.energy * .4) * (ctx.preset.intensity || 1) * (ctx.preset.motionAmount ?? 1) + .1;
        return r.y * extent.y * .55 + (slow + swell + ripple + fine) * amp * extent.y * .32 + x * r.tilt;
      }
      function layout(r, s, t) {
        const pos = r.mesh.geometry.attributes.position, span = extent.x * 1.35, scroll = t * r.speed * .35;
        const widthScale = (ctx.preset.width || 1) * (1 + pulse.value * .5) * (1 + s.bass * .35) * (.8 + s.energy * .4) * extent.y * .3;
        const cols = SEGMENTS + 1;
        for (let i = 0; i < cols; i++) {
          const u = i / SEGMENTS, x = (u - .5) * 2 * span;
          const y = centre(r, x * .6 + scroll + r.seed, t, s);
          const dy = centre(r, (x + .06) * .6 + scroll + r.seed, t, s) - y;
          const nx = -dy, ny = 1, nl = Math.hypot(nx, ny);
          const w = widthScale * r.baseWidth * (.65 + .35 * noise2(u * 3 + r.seed, t * .4)) * (.55 + .45 * Math.sin(u * Math.PI));
          /* PlaneGeometry rows: first row is top (v=1), second row bottom */
          pos.setXYZ(i, x + nx / nl * w, y + ny / nl * w, 0);
          pos.setXYZ(i + cols, x - nx / nl * w, y - ny / nl * w, 0);
        }
        pos.needsUpdate = true;
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 40, 10);
          backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop);
          pulse = new Spring(70, 9, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(p); ribbons.forEach((r, i) => { r.mesh.material.uniforms.uA.value.set(i % 2 ? p.primary : p.secondary); r.mesh.material.uniforms.uB.value.set(i % 3 ? p.secondary : p.glow); r.mesh.material.uniforms.uWhite.value.set(p.accent); }); },
        presetChanged(key) { if (key === 'ribbons' || key === null) build(); },
        update(s, dt, t) {
          time = t; if (s.beat > .5 && pulse.lastBeat !== s.beatCount) { pulse.lastBeat = s.beatCount; pulse.push(2.2 * s.beat); }
          pulse.step(dt);
          backdrop.tick(s.energy, t);
          const idle = .35 + .65 * clamp(s.energy * 1.4, 0, 1);
          for (const r of ribbons) { layout(r, s, t * idle); const u = r.mesh.material.uniforms; u.uTime.value = t; u.uEdge.value = s.treble * 1.3 + s.beat * .4; u.uOpacity.value = (.3 + .35 * idle) * (ctx.preset.opacity ?? 1); }
        },
        resize(w, h) { camera.fitAspect(w / h); extent = halfExtent(camera, 10 - (-2)); },
        dispose() { for (const r of ribbons) { r.mesh.geometry.dispose(); r.mesh.material.dispose(); } ribbons = []; backdrop?.dispose(); },
        count() { return ribbons.length; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
