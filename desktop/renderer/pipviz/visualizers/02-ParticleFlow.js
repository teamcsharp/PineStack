/* 02 PARTICLE FLOW - luminous matter. Tens of thousands of points (one GPU buffer, animated in the vertex
 * shader) ride a coherent flow: a great horizontal current whose centreline drifts, curl noise around it,
 * depth from near the camera into darkness, and small clusters that detach now and then and are drawn
 * back. Nothing is re-randomised per frame: each point has a seed and the field decides where it is.
 *   bass -> the current's large displacement  mids -> density and lift  treble -> micro-jitter and sparkle
 *   rms -> luminosity  beat -> a shockwave travelling down the stream
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { gradientBackdrop, softSprite, stageCamera } = PineViz.shared;

  PineViz.register({
    id: 'particle-flow', index: 2, name: 'Particle Flow', blurb: 'swarming luminous matter',
    defaults: { particles: 36000, size: .85, bloom: .9 },   /* [viz-look] a swarm of fine sparks, not discs */
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, points, material, sprite, count = 0, shock = { at: -10, strength: 0 }, lastBeat = 0;
      function build() {
        if (points) { scene.remove(points); points.geometry.dispose(); }
        count = Math.max(2000, Math.round((ctx.preset.particles || 24000) * ctx.quality.scale));
        const geo = new THREE.BufferGeometry();
        const seeds = new Float32Array(count * 4);
        for (let i = 0; i < count; i++) { seeds[i * 4] = ctx.rng(); seeds[i * 4 + 1] = ctx.rng(); seeds[i * 4 + 2] = ctx.rng(); seeds[i * 4 + 3] = ctx.rng(); }
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
        geo.setAttribute('seed', new THREE.BufferAttribute(seeds, 4));
        points = new THREE.Points(geo, material); points.frustumCulled = false; scene.add(points);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 50, 12);
          backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop);
          sprite = softSprite(THREE, 64);
          const p = ctx.palette;
          material = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
            uniforms: { uTime: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uShockAt: { value: -10 }, uShock: { value: 0 }, uSize: { value: 1 }, uAspect: { value: 1.78 }, uPixel: { value: 1 },
              uA: { value: new THREE.Color(p.secondary) }, uB: { value: new THREE.Color(p.primary) }, uC: { value: new THREE.Color(p.accent) }, uV: { value: new THREE.Color(ctx.palette.name === 'Monochrome' ? p.secondary : '#b36bff') }, tSprite: { value: sprite } },
            vertexShader: `${GLSL_NOISE} attribute vec4 seed; uniform float uTime; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uRms; uniform float uEnergy; uniform float uShockAt; uniform float uShock; uniform float uSize; uniform float uAspect; uniform float uPixel;
              varying float vDepth; varying float vHeat; varying float vCluster;
              void main(){
                float idle = 0.3 + 0.7 * uEnergy;
                float t = uTime * (0.35 + 0.65 * idle);
                /* along the current: each point has a station on x that scrolls; wraps across the stage */
                float span = 11.0 * uAspect;
                float x = mod(seed.x * span + t * (0.6 + seed.w * 1.2) * (0.5 + uRms), span) - span * 0.5;
                /* the centreline drifts with slow noise and the bass; the stream is a band around it */
                float centre = pv_snoise(vec3(x * 0.16, t * 0.09, 3.0)) * (1.2 + uBass * 2.4) + sin(x * 0.35 + t * 0.3) * 0.6;
                float band = (seed.y - 0.5) * (1.4 + uMid * 2.2);
                vec3 p = vec3(x, centre + band, (seed.z - 0.5) * 9.0);
                /* curl of the field moves the matter coherently; treble adds the fine shimmer */
                vec3 q = p * 0.35 + vec3(0.0, 0.0, t * 0.25);
                vec3 curl = vec3(pv_snoise(q + vec3(0.0, 1.7, 0.0)) - pv_snoise(q - vec3(0.0, 1.7, 0.0)), pv_snoise(q + vec3(2.3, 0.0, 0.0)) - pv_snoise(q - vec3(2.3, 0.0, 0.0)), 0.0) * 0.5;
                p += curl * (0.5 + uMid * 1.2 + uBass * 0.6) * idle;
                p += vec3(pv_snoise(vec3(seed.xy * 40.0, t * 6.0)), pv_snoise(vec3(seed.yz * 40.0, t * 6.0 + 9.0)), 0.0) * uTreble * 0.35;
                /* clusters: some points belong to a cluster that detaches for a while, then is drawn back */
                float cl = step(0.86, seed.w);
                float detach = smoothstep(0.2, 0.8, pv_snoise(vec3(floor(seed.w * 97.0), t * 0.07, 1.0)) * 0.5 + 0.5);
                vec3 away = vec3(0.0, 2.6 * (seed.y - 0.5) * 2.0, 1.5) * detach * cl;
                p += away;
                /* the beat's shockwave: a ring in x sweeping down the stream from the centre */
                float ring = abs(abs(x) - (uTime - uShockAt) * 9.0);
                float hit = uShock * exp(-ring * 1.2) * exp(-(uTime - uShockAt) * 1.4);
                p.y += hit * 1.6 * sign(band + 0.001);
                vHeat = clamp(uRms * 0.8 + hit + detach * cl * 0.5, 0.0, 1.0);
                vCluster = cl;
                vec4 mv = modelViewMatrix * vec4(p, 1.0);
                vDepth = clamp(1.0 - (-mv.z - 3.0) / 18.0, 0.0, 1.0);
                gl_Position = projectionMatrix * mv;
                float sz = (0.8 + seed.w * 1.6) * uSize * uPixel * (1.0 + uTreble * 0.6 + hit) * (34.0 / max(1.0, -mv.z));
                gl_PointSize = clamp(sz, 1.0, 26.0);
              }`,
            fragmentShader: `uniform sampler2D tSprite; uniform vec3 uA; uniform vec3 uB; uniform vec3 uC; uniform vec3 uV; uniform float uRms; uniform float uEnergy; varying float vDepth; varying float vHeat; varying float vCluster;
              void main(){ float a = texture2D(tSprite, gl_PointCoord).a;
                vec3 c = mix(uB, uA, vDepth);
                c = mix(c, uV, vCluster * 0.7 + vHeat * 0.35);
                c = mix(c, uC, pow(vHeat, 2.0) * 0.6);
                float lum = (0.45 + 0.55 * uRms + 0.3 * uEnergy) * (0.35 + 0.65 * vDepth);
                gl_FragColor = vec4(c * lum * 1.6, a * lum); }` });
          build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(p); const u = material.uniforms; u.uA.value.set(p.secondary); u.uB.value.set(p.primary); u.uC.value.set(p.accent); u.uV.value.set(ctx.palette.name === 'Monochrome' ? p.secondary : '#b36bff'); },
        presetChanged(key) { if (key === 'particles' || key === null) build(); },
        update(s, dt, t) {
          const u = material.uniforms; u.uTime.value = t; u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uRms.value = s.rms * (ctx.preset.intensity || 1); u.uEnergy.value = s.energy;
          if (s.beat > .55 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; u.uShockAt.value = t; u.uShock.value = clamp(s.beat * 1.2, 0, 1.4); }
          u.uSize.value = (ctx.preset.size || 1) * (ctx.preset.opacity ?? 1);
          backdrop.tick(s.energy, t);
        },
        resize(w, h) { camera.fitAspect(w / h); material.uniforms.uAspect.value = w / h; material.uniforms.uPixel.value = Math.min(2, ctx.renderer.getPixelRatio()); },
        dispose() { points?.geometry.dispose(); material?.dispose(); sprite?.dispose(); backdrop?.dispose(); points = null; },
        count() { return count; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
