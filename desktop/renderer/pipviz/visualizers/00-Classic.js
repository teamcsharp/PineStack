/* 00 CLASSIC - the Pine Box cloud. The background the PiP had from the start: a quiet drift of fine
 * points in the station's accent colour behind the Pine Box mark, gathering as voices speak, rippling
 * with the bands, breathing with the level. Ported from the panel's first particle cloud so the
 * "traditional" look is one mode among the ten, and the one a fresh desk starts on.
 *   rms -> brightness and gather  bass -> slow sway  mids -> ripple  treble -> static shimmer  beat -> a soft pulse
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { stageCamera, softSprite, Spring } = PineViz.shared;

  PineViz.register({
    id: 'classic', index: 0, name: 'Classic', blurb: 'the Pine Box cloud',
    defaults: { particles: 1800, size: 1, bloom: .2 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, points, material, sprite, backdrop, count = 0, pulse, lastBeat = 0;
      function build() {
        if (points) { scene.remove(points); points.geometry.dispose(); }
        count = Math.max(400, Math.round((ctx.preset.particles || 1800) * Math.max(.5, ctx.quality.scale)));
        const geo = new THREE.BufferGeometry(), seeds = new Float32Array(count * 4);
        for (let i = 0; i < count; i++) { seeds[i * 4] = (ctx.rng() - .5) * 16; seeds[i * 4 + 1] = ctx.rng() * Math.PI * 2; seeds[i * 4 + 2] = ctx.rng() * 2; seeds[i * 4 + 3] = ctx.rng() * Math.PI * 2; }
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3)); geo.setAttribute('seed', new THREE.BufferAttribute(seeds, 4));
        points = new THREE.Points(geo, material); points.frustumCulled = false; scene.add(points);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 48, 9);
          const p = ctx.palette;
          /* the panel's own gradient: the theme's button colour at the lower left, the surface everywhere else */
          backdrop = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({ depthTest: false, depthWrite: false,
            uniforms: { uA: { value: new THREE.Color(p.bg) }, uB: { value: new THREE.Color(p.bg2) } },
            vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.999, 1.0); }',
            fragmentShader: 'uniform vec3 uA; uniform vec3 uB; varying vec2 vUv; void main(){ float d = distance(vUv, vec2(0.4, 0.35)); gl_FragColor = vec4(mix(uB, uA, smoothstep(0.0, 0.75, d)), 1.0); }' }));
          backdrop.frustumCulled = false; backdrop.renderOrder = -1000; scene.add(backdrop);
          sprite = softSprite(THREE, 32);
          material = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
            uniforms: { uTime: { value: 0 }, uLevel: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uPulse: { value: 0 }, uSize: { value: 1 }, uPixel: { value: 1 }, uColor: { value: new THREE.Color(p.primary) }, tSprite: { value: sprite } },
            vertexShader: `${GLSL_NOISE} attribute vec4 seed; uniform float uTime; uniform float uLevel; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uPulse; uniform float uSize; uniform float uPixel; varying float vA;
              void main(){ float t = uTime; float x = seed.x, a = seed.y, r = seed.z, ph = seed.w;
                float clump = 0.25 + 0.75 * (0.5 + 0.5 * sin(t * 0.19 + x * 0.38 + ph));
                float energy = uMid * (0.5 + 0.5 * sin(x * 0.9 + t * 1.3));
                float gather = 1.0 - uLevel * 0.38; float spread = clump * (1.0 - uLevel * 0.6);
                float ripple = sin(x * 1.8 - t * 5.5) * energy * 0.75 + sin(x * 0.75 + t * 3.0) * uLevel * 0.35;
                float statics = 0.012 + uTreble * 0.055;
                vec3 p = vec3(x * gather + sin(t * 0.13 + a) * 0.7 + sin(t * 31.0 + ph) * statics,
                              sin(x * 0.55 + t * 0.45) * 0.65 + ripple + cos(a + t * 0.12) * r * spread - 1.0 + sin(t * 37.0 + a) * statics + uBass * 0.4 * sin(x * 0.3 + t * 0.5),
                              sin(a + t * 0.09) * r * spread);
                p *= 1.0 + uPulse * 0.08;
                vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_Position = projectionMatrix * mv;
                vA = 0.65 + uLevel * 0.25; gl_PointSize = (2.6 + uLevel * 1.0 + uPulse * 0.8) * uSize * uPixel * (9.0 / max(1.0, -mv.z)); }`,
            fragmentShader: 'uniform sampler2D tSprite; uniform vec3 uColor; varying float vA; void main(){ float a = texture2D(tSprite, gl_PointCoord).a; gl_FragColor = vec4(uColor * 1.2, a * vA); }' });
          pulse = new Spring(40, 7, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) { material.uniforms.uColor.value.set(p.primary); backdrop.material.uniforms.uA.value.set(p.bg); backdrop.material.uniforms.uB.value.set(p.bg2); },
        presetChanged(key) { if (key === 'particles' || key === null) build(); },
        update(s, dt, t) {
          if (s.beat > .55 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; pulse.push(1.6 * s.beat); }
          pulse.step(dt);
          const u = material.uniforms; u.uTime.value = t * (.6 + .4 * clamp(s.energy * 1.5, 0, 1)); u.uLevel.value = clamp(s.rms * (ctx.preset.intensity || 1) * 1.3 + s.speechActivity * .3, 0, 1); u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uPulse.value = clamp(pulse.value, 0, 1.5); u.uSize.value = (ctx.preset.size || 1) * (ctx.preset.opacity ?? 1);
        },
        resize(w, h) { camera.fitAspect(w / h); material.uniforms.uPixel.value = Math.min(2, ctx.renderer.getPixelRatio()); },
        dispose() { points?.geometry.dispose(); material?.dispose(); sprite?.dispose(); backdrop?.geometry.dispose(); backdrop?.material.dispose(); points = null; },
        count() { return count; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
