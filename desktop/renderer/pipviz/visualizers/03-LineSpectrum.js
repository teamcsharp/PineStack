/* 03 LINE SPECTRUM - luminous contour lines. Thirty-odd thin lines flow across the stage as a family:
 * each takes the same hills (slow oscillation, coherent noise, the low spectrum) and adds its own small
 * independence and an offset from its neighbour, like a topographic map breathing. Thin vertical
 * spectrum indicators rise behind them now and then. Lines only; almost nothing filled.
 *   bass -> broad hills  mids -> local deformation  treble -> fine ripples  volume -> brightness  beat -> a travelling pulse
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { noise2, noise1, clamp, lerp } = PineViz.util, { gradientBackdrop, stageCamera, halfExtent, Spring } = PineViz.shared;

  PineViz.register({
    id: 'line-spectrum', index: 3, name: 'Line Spectrum', blurb: 'luminous contour lines',
    defaults: { lines: 34, bloom: .45, indicators: 28 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, lines = [], bars, barGeo, extent = { x: 8, y: 4.5 }, pulse = null, lastBeat = 0, pulseX = -99, heights = null, peaks = null;
      const POINTS = 170;
      function build() {
        for (const l of lines) { scene.remove(l.mesh); l.mesh.geometry.dispose(); l.mesh.material.dispose(); } lines = [];
        const n = Math.max(12, Math.round((ctx.preset.lines || 34) * (ctx.quality.scale < .5 ? .6 : 1)));
        const p = ctx.palette, a = new THREE.Color(p.secondary), b = new THREE.Color(p.primary), v = new THREE.Color(ctx.palette.name === 'Monochrome' ? p.glow : '#8a5cff');
        for (let i = 0; i < n; i++) {
          const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(POINTS * 3), 3));
          const f = i / (n - 1), col = f < .5 ? a.clone().lerp(b, f * 2) : b.clone().lerp(v, (f - .5) * 2);
          const mat = new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: .35, blending: THREE.AdditiveBlending, depthWrite: false });
          const mesh = new THREE.Line(geo, mat); mesh.frustumCulled = false; scene.add(mesh);
          lines.push({ mesh, f, seed: ctx.rng() * 50, phase: ctx.rng() * 6 });
        }
        if (bars) { scene.remove(bars); barGeo.dispose(); bars.material.dispose(); }
        const m = Math.max(8, Math.round(ctx.preset.indicators || 28)); heights = new Float32Array(m); peaks = new Float32Array(m);
        barGeo = new THREE.BufferGeometry(); barGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(m * 2 * 3), 3));
        bars = new THREE.LineSegments(barGeo, new THREE.LineBasicMaterial({ color: new THREE.Color(p.glow), transparent: true, opacity: .4, blending: THREE.AdditiveBlending, depthWrite: false })); bars.frustumCulled = false; scene.add(bars);
      }
      /* the family's shared terrain, then each line's own small voice */
      function terrain(x, t, s, l) {
        const hills = Math.sin(x * .32 + t * .25 + noise1(t * .05 + l.seed) * 2) * (.35 + s.bass * 1.4) + noise2(x * .18 + l.seed * .1, t * .12) * (.5 + s.bass * 1.2);
        const local = noise2(x * .9 + l.seed, t * .55 + l.phase) * (.1 + s.mid * .75);
        const ripple = noise2(x * 4.5 + l.seed, t * 3.1) * (.015 + s.treble * .16);
        const spectral = s.fft[Math.floor(((x / extent.x + 1) / 2) * 20) % 64] * s.rms * .5;
        return hills + local + ripple + spectral;
      }
      return {
        init() { scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 40, 10); backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop); pulse = new Spring(40, 6, 0); build(); },
        activate() {}, deactivate() {},
        palette() { backdrop.setPalette(ctx.palette); build(); },
        presetChanged(key) { if (key === 'lines' || key === 'indicators' || key === null) build(); },
        update(s, dt, t) {
          backdrop.tick(s.energy, t);
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; pulseX = -extent.x * 1.3; pulse.push(3 * s.beat); }
          pulse.step(dt); pulseX += dt * extent.x * 1.8;
          const idle = .3 + .7 * clamp(s.energy * 1.5, 0, 1), amp = extent.y * .16 * (ctx.preset.intensity || 1) * (ctx.preset.motionAmount ?? 1), gap = extent.y * 1.5 / Math.max(1, lines.length - 1);
          const base = -extent.y * .78;
          for (const l of lines) {
            const pos = l.mesh.geometry.attributes.position, offset = base + l.f * extent.y * 1.5;
            for (let i = 0; i < POINTS; i++) {
              const u = i / (POINTS - 1), x = (u - .5) * 2 * extent.x * 1.1;
              const y = offset + terrain(x, t * idle, s, l) * amp * (.6 + .6 * l.f) + Math.exp(-Math.abs(x - pulseX) * 1.1) * pulse.value * amp * .5;
              pos.setXYZ(i, x, y, -l.f * 1.5);
            }
            pos.needsUpdate = true;
            l.mesh.material.opacity = (.14 + .5 * s.rms + .18 * s.energy) * (ctx.preset.opacity ?? 1) * (.55 + .45 * (1 - l.f));
          }
          const pos = bars.geometry.attributes.position, m = heights.length;
          for (let i = 0; i < m; i++) {
            const bin = Math.floor(i / m * 44), target = s.fft[bin] || 0;
            heights[i] = target > heights[i] ? lerp(heights[i], target, 1 - Math.exp(-dt / .04)) : lerp(heights[i], target, 1 - Math.exp(-dt / .3));
            peaks[i] = Math.max(heights[i], peaks[i] - dt * .5);
            const x = (i / (m - 1) - .5) * 2 * extent.x * .95 + Math.sin(t * .2 + i) * .1, y0 = -extent.y * .9, h = heights[i] * extent.y * 1.4;
            pos.setXYZ(i * 2, x, y0, -2); pos.setXYZ(i * 2 + 1, x, y0 + h + .02, -2);
          }
          pos.needsUpdate = true; bars.material.opacity = (.12 + .45 * s.rms) * (ctx.preset.opacity ?? 1);
        },
        resize(w, h) { camera.fitAspect(w / h); extent = halfExtent(camera, 10); },
        dispose() { for (const l of lines) { l.mesh.geometry.dispose(); l.mesh.material.dispose(); } lines = []; barGeo?.dispose(); bars?.material.dispose(); backdrop?.dispose(); },
        count() { return lines.length + (heights ? heights.length : 0); },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
