/* 02 PARTICLE FLOW - a river of sparks. Tens of thousands of small crisp points (one GPU buffer, placed by
 * the vertex shader) make ONE flowing sheet across a near-black field, as in the panel: dense and bright
 * along its crest, a spray falling away below it, a thin mist above, blue on the left turning violet and
 * pink on the right, white where the crest burns, and one point in ten loose in the field as dust. The
 * sheet travels slowly; the points keep their places in it. No curl, no clusters, no chaos.
 *   bass -> the sheet's swell  mids -> how deep the spray falls  treble -> the twinkle  rms -> luminosity
 *   beat -> a pulse of light travelling down the river
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { gradientBackdrop, stageCamera, halfExtent } = PineViz.shared;

  PineViz.register({
    id: 'particle-flow', index: 2, name: 'Particle Flow', blurb: 'a river of fine sparks',
    defaults: { particles: 32000, size: 1, bloom: .35 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, points, material, count = 0, clock = 0, lastBeat = 0, half = { x: 8, y: 4.5 };
      const DIST = 12;
      const dark = (hex, k) => new THREE.Color(hex).multiplyScalar(k);
      const field = p => ({ bg: dark(p.bg, .35), bg2: dark(p.bg2, .32), glow: dark(p.glow, .6) });
      const violet = p => ctx.palette.name === 'Monochrome' ? p.secondary : '#8a4dff';
      const pink = p => ctx.palette.name === 'Monochrome' ? p.accent : '#d36cff';
      function build() {
        if (points) { scene.remove(points); points.geometry.dispose(); }
        count = Math.max(2000, Math.round((ctx.preset.particles || 32000) * ctx.quality.scale));
        const geo = new THREE.BufferGeometry();
        const seeds = new Float32Array(count * 4);
        for (let i = 0; i < count; i++) { seeds[i * 4] = ctx.rng(); seeds[i * 4 + 1] = ctx.rng(); seeds[i * 4 + 2] = ctx.rng(); seeds[i * 4 + 3] = ctx.rng(); }
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
        geo.setAttribute('seed', new THREE.BufferAttribute(seeds, 4));
        points = new THREE.Points(geo, material); points.frustumCulled = false; scene.add(points);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 50, DIST);
          half = halfExtent(camera, DIST);
          backdrop = gradientBackdrop(THREE, field(ctx.palette)); scene.add(backdrop);
          const p = ctx.palette;
          material = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
            uniforms: { uTime: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uBeatAt: { value: -10 }, uBeat: { value: 0 },
              uSize: { value: 1 }, uPixel: { value: 1 }, uSeed: { value: ctx.rng() * 10 }, uHalf: { value: new THREE.Vector2(half.x, half.y) },
              uBlue: { value: new THREE.Color(p.primary) }, uCyan: { value: new THREE.Color(p.secondary) }, uViolet: { value: new THREE.Color(violet(p)) }, uPink: { value: new THREE.Color(pink(p)) }, uWhite: { value: new THREE.Color(p.accent) } },
            vertexShader: `${GLSL_NOISE}
              attribute vec4 seed;
              uniform float uTime; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uRms; uniform float uEnergy; uniform float uBeatAt; uniform float uBeat;
              uniform float uSize; uniform float uPixel; uniform float uSeed; uniform vec2 uHalf;
              varying float vHeat; varying float vX; varying float vDust; varying float vTwinkle; varying float vSoft; varying float vFold;
              float crest(float x, float t) {
                float u = x / uHalf.x;                                                  /* -1..1 across the stage */
                float rise = u * uHalf.y * 0.26;                                        /* low on the left, high on the right */
                float s = sin(u * 2.4 + t * 0.12 + uSeed) * uHalf.y * (0.20 + 0.12 * uBass);
                float s2 = sin(u * 5.1 - t * 0.07 + uSeed * 1.3) * uHalf.y * 0.05;
                float n = pv_snoise(vec3(u * 1.3 + uSeed, t * 0.04, 2.0)) * uHalf.y * 0.06;
                return rise + s + s2 + n - uHalf.y * 0.04;
              }
              void main() {
                float dust = step(seed.w, 0.13);                                        /* one in eight is loose in the field */
                float fold = step(0.74, fract(seed.w * 5.3)) * (1.0 - dust);           /* a second fold of the sheet behind the first */
                float t = uTime;
                float u = fract(seed.x + t * (0.004 + 0.006 * seed.z));                 /* slow travel along the river */
                float x = (u - 0.5) * 2.0 * uHalf.x * 1.1;
                float yc = mix(crest(x, t), crest(x, t + 9.0) - uHalf.y * 0.22, fold);
                /* across the river: dense at the crest, a spray falling below, a thin mist above */
                float g = seed.y;
                float below = pow(g, 1.5) * uHalf.y * (0.50 + 0.18 * uMid);
                float mist = step(0.8, fract(seed.w * 13.7));
                float above = pow(fract(seed.z * 7.31), 4.0) * uHalf.y * 0.12 * mist;
                float off = -below * (1.0 - mist) + above + (fract(seed.y * 51.7) - 0.5) * uHalf.y * 0.02;
                vec3 p = vec3(x, yc + off, (seed.z - 0.5) * 3.0);
                /* dust: scattered over the whole field, drifting slowly */
                vec3 d = vec3((fract(seed.x * 3.7 + t * 0.002) - 0.5) * 2.2 * uHalf.x, (fract(seed.y * 5.3 + t * 0.0015) - 0.5) * 2.2 * uHalf.y, (seed.z - 0.5) * 4.0);
                p = mix(p, d, dust);
                /* the beat travels down the river as light, not as displacement */
                float wave = exp(-abs(u - fract((t - uBeatAt) * 0.35)) * 12.0) * uBeat;
                float depthBelow = (below * (1.0 - mist) + above) / uHalf.y;
                float nearCrest = 1.0 - smoothstep(0.0, 0.12, depthBelow);
                vHeat = (1.0 - dust) * clamp(nearCrest * (0.7 + 0.4 * uRms) + wave * 0.6, 0.0, 1.0) * (1.0 - 0.4 * fold);
                vX = u; vDust = dust; vFold = fold;
                float tw = fract(seed.w * 97.3);
                vTwinkle = step(0.86, tw) * (0.5 + 0.5 * sin(t * (5.0 + tw * 9.0) + seed.x * 300.0)) * (0.25 + uTreble);
                vSoft = step(0.975, fract(seed.z * 31.1));                              /* a few soft glowing points */
                vec4 mv = modelViewMatrix * vec4(p, 1.0);
                gl_Position = projectionMatrix * mv;
                float base = mix(1.3, 2.0, fract(seed.w * 7.7)) + vSoft * 3.0 + nearCrest * 0.6 + vTwinkle * 1.2;
                float sz = base * uSize * uPixel * (14.0 / max(1.0, -mv.z)) * mix(1.0, 0.75, dust);
                gl_PointSize = clamp(sz, 1.0, 9.0);
              }`,
            fragmentShader: `
              uniform vec3 uBlue; uniform vec3 uCyan; uniform vec3 uViolet; uniform vec3 uPink; uniform vec3 uWhite; uniform float uRms; uniform float uEnergy;
              varying float vHeat; varying float vX; varying float vDust; varying float vTwinkle; varying float vSoft; varying float vFold;
              void main() {
                vec2 q = gl_PointCoord - 0.5; float r = length(q) * 2.0;
                float crisp = 1.0 - smoothstep(0.45, 1.0, r);
                float soft = exp(-r * r * 2.5);
                float a = mix(crisp, soft, vSoft);
                if (a < 0.02) discard;
                vec3 c = mix(uBlue, uCyan, smoothstep(0.1, 0.5, vX) * 0.5);
                c = mix(c, uViolet, smoothstep(0.45, 0.8, vX));
                c = mix(c, uPink, smoothstep(0.78, 1.0, vX) * 0.8);
                c = mix(c, uWhite, vHeat * vHeat * 0.85 + vTwinkle * 0.8);
                float lum = mix(0.3, 1.0, vHeat) * (0.65 + 0.4 * uRms + 0.2 * uEnergy);
                lum = mix(lum, 0.26, vDust) * (1.0 - 0.35 * vFold) + vTwinkle * 0.8;
                gl_FragColor = vec4(c * (0.8 + 0.9 * lum), a * clamp(lum, 0.0, 1.0)); }` });
          build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(field(p)); const u = material.uniforms; u.uBlue.value.set(p.primary); u.uCyan.value.set(p.secondary); u.uViolet.value.set(violet(p)); u.uPink.value.set(pink(p)); u.uWhite.value.set(p.accent); },
        presetChanged(key) { if (key === 'particles' || key === null) build(); },
        update(s, dt, t) {
          const u = material.uniforms;
          clock += dt * (0.5 + 0.6 * clamp(s.energy * 1.3, 0, 1)) * (ctx.preset.speed || 1);
          u.uTime.value = clock; u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uRms.value = clamp(s.rms * (ctx.preset.intensity || 1), 0, 1.5); u.uEnergy.value = s.energy;
          if (s.beat > .55 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; u.uBeatAt.value = clock; u.uBeat.value = clamp(s.beat, 0, 1); }
          u.uBeat.value *= Math.max(0, 1 - dt * .5);
          u.uSize.value = (ctx.preset.size || 1) * (ctx.preset.opacity ?? 1);
          backdrop.tick(s.energy, t);
        },
        resize(w, h) { camera.fitAspect(w / h); half = halfExtent(camera, DIST); material.uniforms.uHalf.value.set(half.x, half.y); material.uniforms.uPixel.value = Math.min(2, ctx.renderer.getPixelRatio()); },
        dispose() { points?.geometry.dispose(); material?.dispose(); backdrop?.dispose(); points = null; },
        count() { return count; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
