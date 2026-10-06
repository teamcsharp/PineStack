/* 07 3D AUDIO BARS - a dimensional spectrum. Sixty-four to ninety-six luminous columns (one InstancedMesh)
 * with translucent bodies, a bright cap, a peak indicator that sinks slowly, and their reflection in a
 * glossy dark floor that runs off into perspective. Neighbouring bins are smoothed into hills; heights
 * attack fast and decay slow. The camera sits a little above and breathes.
 *   fft -> heights  rms -> glow  beat -> the floor lights up
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, lerp, noise1, GLSL_NOISE } = PineViz.util, { gradientBackdrop, Spring } = PineViz.shared;

  PineViz.register({
    id: 'audio-bars', index: 7, name: 'Audio Bars', blurb: 'dimensional spectrum columns',
    defaults: { columns: 80, bloom: .55, height: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, body, cap, peakMesh, mirror, floor, floorMat, n = 0, heights, peaks, dummy, lights, floorPulse, lastBeat = 0, bodyMat, capMat, peakMat, mirrorMat;
      const WIDTH = 16;
      function build() {
        for (const m of [body, cap, peakMesh, mirror]) if (m) { scene.remove(m); m.geometry.dispose(); }
        n = Math.max(32, Math.min(128, Math.round((ctx.preset.columns || 80) * (ctx.quality.scale < .5 ? .7 : 1))));
        heights = new Float32Array(n); peaks = new Float32Array(n);
        const w = WIDTH / n * .62;
        body = new THREE.InstancedMesh(new THREE.BoxGeometry(w, 1, w), bodyMat, n); cap = new THREE.InstancedMesh(new THREE.BoxGeometry(w * 1.05, .04, w * 1.05), capMat, n);
        peakMesh = new THREE.InstancedMesh(new THREE.BoxGeometry(w * .9, .03, w * .9), peakMat, n); mirror = new THREE.InstancedMesh(new THREE.BoxGeometry(w, 1, w), mirrorMat, n);
        for (const m of [body, cap, peakMesh, mirror]) { m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.frustumCulled = false; scene.add(m); }
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(38, ctx.size.aspect, .1, 100); camera.position.set(0, 3.4, 17); camera.lookAt(0, .4, 0);
          backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop);
          const p = ctx.palette; dummy = new THREE.Object3D();
          bodyMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(p.primary), emissive: new THREE.Color(p.primary), emissiveIntensity: .25, transparent: true, opacity: .55, roughness: .3, metalness: .1, transmission: ctx.quality.scale >= .6 ? .35 : 0, thickness: .4 });
          capMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(p.accent), transparent: true, opacity: .95, blending: THREE.AdditiveBlending });
          peakMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(p.secondary), transparent: true, opacity: .8, blending: THREE.AdditiveBlending });
          mirrorMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(p.primary), transparent: true, opacity: .18, blending: THREE.AdditiveBlending, depthWrite: false });
          floorMat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, uniforms: { uColor: { value: new THREE.Color(p.bg2) }, uGlow: { value: new THREE.Color(p.secondary) }, uPulse: { value: 0 }, uRms: { value: 0 }, uTime: { value: 0 } },
            vertexShader: 'varying vec2 vUv; varying vec3 vPos; void main(){ vUv = uv; vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
            fragmentShader: `${GLSL_NOISE} uniform vec3 uColor; uniform vec3 uGlow; uniform float uPulse; uniform float uRms; uniform float uTime; varying vec2 vUv; varying vec3 vPos;
              void main(){ float depth = smoothstep(1.0, 0.0, vUv.y);                       /* far edge fades to nothing */
                float grid = (1.0 - smoothstep(0.0, 0.08, abs(fract(vPos.x * 0.6) - 0.5))) * 0.08 * depth;
                float ring = exp(-abs(length(vPos.xz) - uPulse * 14.0) * 0.6) * step(0.01, uPulse) * (1.0 - uPulse);
                float gloss = pow(max(0.0, 1.0 - abs(vUv.x - 0.5) * 1.6), 2.0) * 0.12 * (0.5 + uRms);
                vec3 c = uColor * (0.18 + gloss * 0.5) + uGlow * (grid + ring * 0.9 + gloss * 0.25);
                gl_FragColor = vec4(c, depth * 0.95); }` });
          floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 40, 1, 1), floorMat); floor.rotation.x = -Math.PI / 2; floor.position.set(0, -.01, -6); scene.add(floor);
          lights = [new THREE.PointLight(new THREE.Color(p.secondary), 50, 50), new THREE.AmbientLight(new THREE.Color(p.glow), .6)]; lights[0].position.set(0, 6, 6); lights.forEach(l => scene.add(l));
          floorPulse = new Spring(12, 5, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(p); bodyMat.color.set(p.primary); bodyMat.emissive.set(p.primary); capMat.color.set(p.accent); peakMat.color.set(p.secondary); mirrorMat.color.set(p.primary); floorMat.uniforms.uColor.value.set(p.bg2); floorMat.uniforms.uGlow.value.set(p.secondary); lights[0].color.set(p.secondary); },
        presetChanged(key) { if (key === 'columns' || key === null) build(); },
        update(s, dt, t) {
          backdrop.tick(s.energy, t);
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; floorPulse.value = 0; floorPulse.velocity = 4 * s.beat; }
          floorPulse.step(dt);
          const idle = .2 + .8 * clamp(s.energy * 1.5, 0, 1), scale = (ctx.preset.height || 1) * (ctx.preset.intensity || 1);
          for (let i = 0; i < n; i++) {
            /* a hill, not a spike: each column takes a weighted window of its neighbours */
            const f = i / (n - 1), bin = f * 60; let v = 0, wsum = 0;
            for (let k = -3; k <= 3; k++) { const b = Math.round(bin + k); if (b < 0 || b >= 64) continue; const w = 1 - Math.abs(k) / 4; v += (s.fft[b] || 0) * w; wsum += w; }
            v = v / wsum * (1 + f * .5);   /* the top end is quieter by nature; lift it a little */
            const target = clamp(v * scale, 0, 1) * (.15 + .85 * idle) + .02;
            heights[i] = target > heights[i] ? lerp(heights[i], target, 1 - Math.exp(-dt / .035)) : lerp(heights[i], target, 1 - Math.exp(-dt / .32));
            peaks[i] = heights[i] >= peaks[i] ? heights[i] : Math.max(heights[i], peaks[i] - dt * (.25 + .5 * peaks[i]));
            const x = (f - .5) * WIDTH, h = .06 + heights[i] * 2.4, z = Math.sin(f * Math.PI) * -.8;
            dummy.position.set(x, h / 2, z); dummy.scale.set(1, h, 1); dummy.rotation.set(0, 0, 0); dummy.updateMatrix(); body.setMatrixAt(i, dummy.matrix);
            dummy.position.set(x, -h / 2 - .01, z); dummy.updateMatrix(); mirror.setMatrixAt(i, dummy.matrix);
            dummy.position.set(x, h + .02, z); dummy.scale.set(1, 1, 1); dummy.updateMatrix(); cap.setMatrixAt(i, dummy.matrix);
            dummy.position.set(x, .06 + peaks[i] * 2.4 + .14, z); dummy.updateMatrix(); peakMesh.setMatrixAt(i, dummy.matrix);
          }
          body.instanceMatrix.needsUpdate = cap.instanceMatrix.needsUpdate = peakMesh.instanceMatrix.needsUpdate = mirror.instanceMatrix.needsUpdate = true;
          bodyMat.emissiveIntensity = .08 + s.rms * .3; bodyMat.opacity = (.3 + .25 * s.rms) * (ctx.preset.opacity ?? 1); capMat.opacity = (.5 + .4 * s.rms) * (ctx.preset.opacity ?? 1); mirrorMat.opacity = .06 + s.rms * .1;
          floorMat.uniforms.uPulse.value = clamp(floorPulse.value, 0, 1); floorMat.uniforms.uRms.value = s.rms; floorMat.uniforms.uTime.value = t; lights[0].intensity = 20 + s.rms * 35;
          const m = (ctx.preset.motionAmount ?? 1); camera.position.x = noise1(t * .06) * .9 * m; camera.position.y = 3.4 + noise1(t * .05 + 5) * .3 * m + s.bass * .15; camera.lookAt(0, .6 + s.rms * .3, 0);
        },
        resize(w, h) { camera.aspect = w / h; camera.fov = w / h < 1 ? 60 : 38; camera.updateProjectionMatrix(); },
        dispose() { for (const m of [body, cap, peakMesh, mirror]) m?.geometry.dispose(); floor?.geometry.dispose(); for (const m of [bodyMat, capMat, peakMat, mirrorMat, floorMat]) m?.dispose(); backdrop?.dispose(); },
        count() { return n * 4 + 1; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
