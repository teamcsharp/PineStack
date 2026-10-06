/* 09 RETRO GRID LANDSCAPE - a wireframe terrain running under the camera towards a horizon with a banded
 * sun. The grid's height is coherent noise over time and distance, weighted by the bands at different
 * spatial scales (bass: mountains, mids: hills, treble: ripples) - never a bin per row. Fog eats the
 * distance; a beat sends a bright pulse racing down the grid. The orb is the station's energy gauge.
 *   rms -> horizon and orb brightness  music -> orb size  beat -> the grid pulse
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, noise1, GLSL_NOISE } = PineViz.util;

  PineViz.register({
    id: 'retro-grid', index: 9, name: 'Retro Grid', blurb: 'wireframe landscape and sun',
    defaults: { bloom: .85, density: 1, fog: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, grid, gridMat, sun, sunMat, sky, skyMat, lastBeat = 0, pulseZ = 99, speed = 0;
      function build() {
        if (grid) { scene.remove(grid); grid.geometry.dispose(); }
        const d = Math.max(.5, Math.min(2, ctx.preset.density || 1)) * (ctx.quality.scale < .5 ? .6 : 1);
        const cols = Math.round(56 * d), rows = Math.round(72 * d);
        const geo = new THREE.PlaneGeometry(60, 80, cols, rows); geo.rotateX(-Math.PI / 2);
        grid = new THREE.Mesh(geo, gridMat); grid.position.set(0, -1.6, -36); grid.frustumCulled = false; scene.add(grid);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(58, ctx.size.aspect, .1, 120); camera.position.set(0, 1.1, 6); camera.lookAt(0, .4, -30);
          const p = ctx.palette;
          skyMat = new THREE.ShaderMaterial({ depthTest: false, depthWrite: false, uniforms: { uA: { value: new THREE.Color(p.bg) }, uB: { value: new THREE.Color(p.bg2) }, uGlow: { value: new THREE.Color('#7a3cff') }, uRms: { value: 0 }, uMono: { value: ctx.palette.name === 'Monochrome' ? 1 : 0 } },
            vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.9999, 1.0); }',
            fragmentShader: `uniform vec3 uA; uniform vec3 uB; uniform vec3 uGlow; uniform float uRms; uniform float uMono; varying vec2 vUv; void main(){ float y = vUv.y; vec3 c = mix(uB, uA, smoothstep(0.42, 1.0, y)); float horizon = exp(-abs(y - 0.47) * 9.0) * (0.25 + uRms * 0.5); c += mix(uGlow, uB, uMono) * horizon; float stars = step(0.9985, fract(sin(dot(floor(vUv * vec2(640.0, 360.0)), vec2(12.98, 78.23))) * 43758.5)) * smoothstep(0.55, 0.8, y); c += stars * 0.6; gl_FragColor = vec4(c, 1.0); }` });
          sky = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), skyMat); sky.frustumCulled = false; sky.renderOrder = -1000; scene.add(sky);
          gridMat = new THREE.ShaderMaterial({ wireframe: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
            uniforms: { uTime: { value: 0 }, uScroll: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uPulseZ: { value: 99 }, uFog: { value: 1 }, uLine: { value: new THREE.Color(p.primary) }, uLine2: { value: new THREE.Color(p.secondary) }, uAccent: { value: new THREE.Color(ctx.palette.name === 'Monochrome' ? p.accent : '#b55cff') }, uFogColor: { value: new THREE.Color(p.bg) } },
            vertexShader: `${GLSL_NOISE} uniform float uTime; uniform float uScroll; uniform float uBass; uniform float uMid; uniform float uTreble; varying float vH; varying float vDist; varying float vX;
              void main(){ vec3 p = position; float z = p.z + uScroll;                /* the terrain scrolls; the mesh stays */
                float side = smoothstep(2.0, 14.0, abs(p.x));                          /* a valley for the road and the UI */
                float mountains = pv_fbm(vec3(p.x * 0.045, z * 0.045, 0.0)) * (2.5 + uBass * 7.0) * side;
                float hills = pv_snoise(vec3(p.x * 0.14, z * 0.14, 1.0)) * (0.6 + uMid * 1.8) * (0.3 + side);
                float ripple = pv_snoise(vec3(p.x * 0.7, z * 0.7, uTime * 0.6)) * (0.04 + uTreble * 0.35);
                p.y += max(0.0, mountains) + hills + ripple;
                vH = p.y; vX = p.x; vec4 mv = modelViewMatrix * vec4(p, 1.0); vDist = -mv.z; gl_Position = projectionMatrix * mv; }`,
            fragmentShader: `uniform vec3 uLine; uniform vec3 uLine2; uniform vec3 uAccent; uniform vec3 uFogColor; uniform float uRms; uniform float uPulseZ; uniform float uFog; varying float vH; varying float vDist; varying float vX;
              void main(){ float fog = exp(-vDist * 0.028 * uFog); vec3 c = mix(uLine, uLine2, clamp(vH * 0.12, 0.0, 1.0)); c = mix(c, uAccent, smoothstep(2.0, 7.0, vH) * 0.7);
                float pulse = exp(-abs(vDist - uPulseZ) * 0.25) * 1.4; c += (uLine2 + uAccent) * pulse * 0.6;
                float lum = (0.35 + uRms * 0.65) * fog + pulse * fog; gl_FragColor = vec4(mix(uFogColor, c, fog) * lum, clamp(lum, 0.05, 1.0)); }` });
          sunMat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, uniforms: { uTime: { value: 0 }, uA: { value: new THREE.Color(p.secondary) }, uB: { value: new THREE.Color(ctx.palette.name === 'Monochrome' ? p.primary : '#ff6fd8') }, uGlow: { value: new THREE.Color(p.accent) }, uLevel: { value: 0 }, uBeat: { value: 0 } },
            vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
            fragmentShader: `uniform float uTime; uniform vec3 uA; uniform vec3 uB; uniform vec3 uGlow; uniform float uLevel; uniform float uBeat; varying vec2 vUv;
              void main(){ vec2 q = vUv - 0.5; float r = length(q) * 2.0; float disc = smoothstep(1.0, 0.97, r);
                float bands = step(0.5, fract(vUv.y * 14.0 - uTime * 0.4)) * smoothstep(0.55, 0.2, vUv.y);     /* the synthwave slats, low on the disc */
                vec3 c = mix(uB, uA, smoothstep(0.1, 0.9, vUv.y)); c = mix(c, uGlow, pow(1.0 - r, 2.0) * (0.2 + uLevel * 0.5));
                float halo = exp(-max(0.0, r - 1.0) * 2.4) * (0.35 + uLevel * 0.6 + uBeat * 0.5) * smoothstep(1.42, 1.0, r);
                gl_FragColor = vec4(c * (0.55 + uLevel * 0.8 + uBeat * 0.4), (disc * (1.0 - bands * 0.9) + halo * (1.0 - disc)) * 0.95); }` });
          sun = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), sunMat); sun.position.set(0, 3.2, -60); sun.scale.setScalar(12); scene.add(sun);
          build();
        },
        activate() {}, deactivate() {},
        palette(p) { skyMat.uniforms.uA.value.set(p.bg); skyMat.uniforms.uB.value.set(p.bg2); skyMat.uniforms.uMono.value = p.name === 'Monochrome' ? 1 : 0; gridMat.uniforms.uLine.value.set(p.primary); gridMat.uniforms.uLine2.value.set(p.secondary); gridMat.uniforms.uFogColor.value.set(p.bg); gridMat.uniforms.uAccent.value.set(p.name === 'Monochrome' ? p.accent : '#b55cff'); sunMat.uniforms.uA.value.set(p.secondary); sunMat.uniforms.uB.value.set(p.name === 'Monochrome' ? p.primary : '#ff6fd8'); sunMat.uniforms.uGlow.value.set(p.accent); },
        presetChanged(key) { if (key === 'density' || key === null) build(); },
        update(s, dt, t) {
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; pulseZ = 70; }
          pulseZ -= dt * 55; if (pulseZ < -10) pulseZ = 99;
          const idle = .25 + .75 * clamp(s.energy * 1.5, 0, 1), m = (ctx.preset.motionAmount ?? 1);
          speed += (((1.5 + s.rms * 6 + s.music * 2) * (ctx.preset.speed || 1) * idle * m) - speed) * Math.min(1, dt * 1.5);
          const u = gridMat.uniforms; u.uScroll.value += dt * speed; u.uTime.value = t; u.uBass.value = s.bass * (ctx.preset.intensity || 1); u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uRms.value = s.rms; u.uPulseZ.value = pulseZ; u.uFog.value = ctx.preset.fog ?? 1;
          skyMat.uniforms.uRms.value = s.rms;
          sunMat.uniforms.uTime.value = t; sunMat.uniforms.uLevel.value = clamp(s.rms * .6 + s.speechActivity * .5 + s.energy * .3, 0, 1); sunMat.uniforms.uBeat.value = s.beat;
          sun.scale.setScalar(8 + s.music * 7 + s.speechActivity * 2 + s.beat * 1.2); sun.position.x = noise1(t * .02) * 4 * m;
          camera.position.x = noise1(t * .05) * .5 * m; camera.position.y = 1.1 + noise1(t * .04 + 2) * .15 * m + s.bass * .1; camera.lookAt(sun.position.x * .3, .4, -30);
        },
        resize(w, h) { camera.aspect = w / h; camera.fov = w / h < 1 ? 78 : 58; camera.updateProjectionMatrix(); },
        dispose() { grid?.geometry.dispose(); gridMat?.dispose(); sun?.geometry.dispose(); sunMat?.dispose(); sky?.geometry.dispose(); skyMat?.dispose(); },
        count() { return grid ? grid.geometry.attributes.position.count : 0; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
