/* 05 SPEED LINES - hyperdrive. Hundreds of luminous streaks race from a wandering vanishing point to the
 * edges: curved, of different widths and lengths, with persistence (the frame is not cleared; a veil of
 * the background colour is laid over it instead, so every streak leaves a trail). Not a starfield: the
 * streaks are quads animated on the GPU along bent rays.
 *   rms -> travel velocity  bass -> thickness of the big streaks  mids -> curvature  treble -> small streak count
 *   beat -> a surge  silence -> near suspension, still drifting
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { noise1, clamp, GLSL_NOISE } = PineViz.util, { Spring, stageCamera } = PineViz.shared;

  PineViz.register({
    id: 'speed-lines', index: 5, name: 'Speed Lines', blurb: 'hyperdrive streaks', persist: true,
    defaults: { streaks: 520, trail: .82, bloom: .5 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, veil, streaks, material, count = 0, surge, lastBeat = 0, vp = { x: 0, y: 0 }, travel = 0, veilMat;
      function build() {
        if (streaks) { scene.remove(streaks); streaks.geometry.dispose(); }
        count = Math.max(120, Math.round((ctx.preset.streaks || 520) * ctx.quality.scale));
        const base = new THREE.PlaneGeometry(1, 1, 1, 1);
        const geo = new THREE.InstancedBufferGeometry(); geo.index = base.index; geo.attributes.position = base.attributes.position; geo.attributes.uv = base.attributes.uv;
        const seed = new Float32Array(count * 4);
        for (let i = 0; i < count; i++) { seed[i * 4] = ctx.rng(); seed[i * 4 + 1] = ctx.rng(); seed[i * 4 + 2] = ctx.rng(); seed[i * 4 + 3] = ctx.rng(); }
        geo.setAttribute('seed', new THREE.InstancedBufferAttribute(seed, 4)); geo.instanceCount = count;
        streaks = new THREE.Mesh(geo, material); streaks.frustumCulled = false; scene.add(streaks);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 10); camera.position.z = 1;
          const p = ctx.palette;
          /* the veil: lays a sheet of background over the last frame; its alpha is the trail length */
          veilMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(p.bg), transparent: true, opacity: .18, depthTest: false, depthWrite: false });
          veil = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), veilMat); veil.renderOrder = -10; veil.frustumCulled = false; scene.add(veil);
          material = new THREE.ShaderMaterial({ transparent: true, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending,
            uniforms: { uTime: { value: 0 }, uTravel: { value: 0 }, uVp: { value: new THREE.Vector2(0, 0) }, uAspect: { value: 1.78 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uSurge: { value: 0 }, uA: { value: new THREE.Color(p.accent) }, uB: { value: new THREE.Color(p.secondary) }, uC: { value: new THREE.Color(p.primary) }, uV: { value: new THREE.Color(ctx.palette.name === 'Monochrome' ? p.glow : '#c26bff') } },
            vertexShader: `${GLSL_NOISE} attribute vec4 seed; uniform float uTime; uniform float uTravel; uniform vec2 uVp; uniform float uAspect; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uEnergy; uniform float uSurge;
              varying float vAlong; varying float vAcross; varying float vKind; varying float vHeat;
              void main(){
                float big = step(0.8, seed.w);                                   /* a fifth of them are the thick ones */
                float small = step(seed.w, 0.45);
                float show = 1.0 - small * step(uTreble + 0.35, seed.x);         /* treble brings the small ones out */
                float angle = seed.x * 6.2831853 + pv_snoise(vec3(seed.x * 9.0, uTime * 0.05, 0.0)) * 0.3;
                float speed = (0.45 + seed.y * 1.1) * (big > 0.5 ? 0.7 : 1.0);
                float along = fract(seed.z + uTravel * speed * 0.25);           /* 0 at the vanishing point, 1 at the rim */
                float len = (0.08 + seed.y * 0.22 + big * 0.25) * (0.6 + uEnergy * 0.8);
                float r0 = along * 1.9, r1 = min(2.4, r0 + len * (0.5 + along));
                float t = mix(r0, r1, uv.x);
                float bend = (seed.w - 0.5) * (0.35 + uMid * 1.4) * t;           /* mids bend the rays */
                float a = angle + bend;
                vec2 dir = vec2(cos(a), sin(a));
                float width = (0.0025 + seed.z * 0.004 + big * (0.008 + uBass * 0.02)) * (0.6 + along) * (1.0 + uSurge * 0.6);
                vec2 normal = vec2(-dir.y, dir.x) * (uv.y - 0.5) * width;
                vec2 pos = uVp + dir * t + normal;
                pos.x /= uAspect;
                vAlong = uv.x; vAcross = uv.y; vKind = big; vHeat = along * show;
                gl_Position = vec4(pos, 0.0, 1.0);
                if (show < 0.5) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
              }`,
            fragmentShader: `uniform vec3 uA; uniform vec3 uB; uniform vec3 uC; uniform vec3 uV; uniform float uRms; uniform float uEnergy; uniform float uSurge; varying float vAlong; varying float vAcross; varying float vKind; varying float vHeat;
              void main(){ float core = pow(1.0 - abs(vAcross - 0.5) * 2.0, 1.4);
                float head = smoothstep(0.0, 0.25, vAlong) * smoothstep(1.0, 0.75, vAlong);
                vec3 c = mix(uC, uB, vHeat); c = mix(c, uA, pow(vAlong, 3.0) * 0.8); c = mix(c, uV, vKind * 0.35 * (1.0 - vAlong));
                float lum = (0.25 + 0.6 * uRms + 0.3 * uEnergy + uSurge * 0.4) * (0.35 + 0.65 * vHeat);
                gl_FragColor = vec4(c * lum * 1.5, core * head * lum); }` });
          surge = new Spring(14, 3.5, 0); build();
        },
        activate() { travel = 0; }, deactivate() {},
        palette(p) { veilMat.color.set(p.bg); const u = material.uniforms; u.uA.value.set(p.accent); u.uB.value.set(p.secondary); u.uC.value.set(p.primary); u.uV.value.set(ctx.palette.name === 'Monochrome' ? p.glow : '#c26bff'); },
        presetChanged(key) { if (key === 'streaks' || key === null) build(); },
        update(s, dt, t) {
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; surge.push(5 * s.beat); }
          surge.step(dt);
          const velocity = (.08 + s.rms * 1.6 + s.energy * .5 + Math.max(0, surge.value) * .6) * (ctx.preset.speed || 1) * (ctx.preset.motionAmount ?? 1);
          travel += dt * velocity;
          vp.x = noise1(t * .07) * .35 * (ctx.preset.motionAmount ?? 1); vp.y = noise1(t * .05 + 11) * .25 * (ctx.preset.motionAmount ?? 1);
          const u = material.uniforms; u.uTime.value = t; u.uTravel.value = travel; u.uVp.value.set(vp.x, vp.y); u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uRms.value = s.rms * (ctx.preset.intensity || 1); u.uEnergy.value = s.energy; u.uSurge.value = clamp(surge.value, 0, 2);
          veilMat.opacity = clamp(1 - (ctx.preset.trail ?? .82), .04, .6) * (velocity > .4 ? 1 : 1.6);   /* slower travel, shorter trails */
        },
        resize(w, h) { material.uniforms.uAspect.value = w / h; },
        dispose() { streaks?.geometry.dispose(); material?.dispose(); veil?.geometry.dispose(); veilMat?.dispose(); streaks = null; },
        count() { return count; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
