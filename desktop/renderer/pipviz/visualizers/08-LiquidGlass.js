/* 08 LIQUID GLASS - a membrane of thick, refractive glass flowing through the stage, deformed by noise in
 * its vertex shader, lit by coloured lights with a Fresnel rim and an internal glow that rises with the
 * level; a dozen or more glass droplets drift around it and shiver when the energy near them climbs.
 * Quality levels: transmission and iridescence on high/ultra; a translucent phong glass below that.
 *   bass -> deformation and thickness  mids -> surface movement  treble -> highlights and ripples
 *   rms -> internal illumination  beat -> a pressure wave through the material
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, noise1, GLSL_NOISE } = PineViz.util, { gradientBackdrop, stageCamera, Spring } = PineViz.shared;

  PineViz.register({
    id: 'liquid-glass', index: 8, name: 'Liquid Glass', blurb: 'refractive liquid membrane',
    defaults: { droplets: 18, bloom: .45, thickness: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, membrane, mat, drops = [], lights, pressure, lastBeat = 0, waveAt = -9, glow;
      const uniforms = { uTime: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uWaveAt: { value: -9 }, uWave: { value: 0 }, uThick: { value: 1 } };
      /* the displacement, shared by the membrane's vertex program through onBeforeCompile */
      const displace = `${GLSL_NOISE} uniform float uTime; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uRms; uniform float uWaveAt; uniform float uWave; uniform float uThick;
        vec3 pv_displace(vec3 p){
          float x = p.x; float t = uTime;
          float swell = pv_snoise(vec3(x * 0.18, t * 0.12, 1.0)) * (1.4 + uBass * 2.4) + sin(x * 0.35 + t * 0.3) * (0.6 + uBass);
          float surface = pv_snoise(vec3(x * 0.7, p.y * 0.8 + t * 0.4, 2.0)) * (0.25 + uMid * 0.9);
          float ripple = pv_snoise(vec3(x * 3.0, p.y * 3.0, t * 2.5)) * (0.03 + uTreble * 0.18);
          float since = t - uWaveAt; float ring = exp(-abs(abs(x) - since * 7.0) * 0.9) * uWave * exp(-since * 1.2);
          float thick = (1.0 + uBass * 0.5 + ring * 0.8) * uThick;
          return vec3(p.x, p.y * thick + swell + surface + ripple + ring * 0.6, p.z * thick + surface * 0.6 + ring * 0.3);
        }`;
      function glassMaterial(p, high) {
        const m = high
          ? new THREE.MeshPhysicalMaterial({ color: new THREE.Color(p.secondary), metalness: 0, roughness: .08, transmission: .92, thickness: 2.2, ior: 1.42, iridescence: .8, iridescenceIOR: 1.25, iridescenceThicknessRange: [120, 480], clearcoat: 1, clearcoatRoughness: .05, transparent: true, opacity: 1, side: THREE.DoubleSide, emissive: new THREE.Color(p.primary), emissiveIntensity: .12 })
          : new THREE.MeshPhongMaterial({ color: new THREE.Color(p.secondary), specular: new THREE.Color(p.accent), shininess: 160, transparent: true, opacity: .55, side: THREE.DoubleSide, emissive: new THREE.Color(p.primary), emissiveIntensity: .15 });
        m.onBeforeCompile = shader => {
          Object.assign(shader.uniforms, uniforms);
          shader.vertexShader = displace + shader.vertexShader.replace('#include <begin_vertex>', `vec3 transformed = pv_displace(position);
            vec3 dx = pv_displace(position + vec3(0.08, 0.0, 0.0)) - transformed; vec3 dy = pv_displace(position + vec3(0.0, 0.08, 0.0)) - transformed;`)
            .replace('#include <beginnormal_vertex>', 'vec3 objectNormal = normal;')
            .replace('#include <defaultnormal_vertex>', `vec3 pvN = normalize(cross(dx, dy)); vec3 transformedNormal = normalMatrix * pvN; #ifdef FLIP_SIDED transformedNormal = -transformedNormal; #endif`);
        };
        m.customProgramCacheKey = () => 'pineviz-liquid-' + (high ? 'hi' : 'lo');
        return m;
      }
      function build() {
        for (const d of drops) { scene.remove(d.mesh); d.mesh.geometry.dispose(); } drops = [];
        const n = Math.max(6, Math.round((ctx.preset.droplets || 18) * (ctx.quality.scale < .5 ? .5 : 1))), p = ctx.palette;
        const dropMat = ctx.quality.scale >= 1 ? new THREE.MeshPhysicalMaterial({ color: new THREE.Color(p.secondary), roughness: .05, transmission: .95, thickness: 1, ior: 1.4, transparent: true, clearcoat: 1 }) : new THREE.MeshPhongMaterial({ color: new THREE.Color(p.secondary), specular: new THREE.Color(p.accent), shininess: 200, transparent: true, opacity: .5 });
        for (let i = 0; i < n; i++) {
          const r = .15 + ctx.rng() ** 2 * .55, mesh = new THREE.Mesh(new THREE.SphereGeometry(r, 24, 18), dropMat);
          const home = new THREE.Vector3((ctx.rng() - .5) * 22, (ctx.rng() - .5) * 8, -2 - ctx.rng() * 8);
          mesh.position.copy(home); drops.push({ mesh, home, r, seed: ctx.rng() * 20, shiver: new Spring(50, 5, 0) }); scene.add(mesh);
        }
        drops.material = dropMat;
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 42, 12);
          backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop);
          const p = ctx.palette, high = ctx.quality.scale >= .6;
          mat = glassMaterial(p, high);
          membrane = new THREE.Mesh(new THREE.PlaneGeometry(34, 3.2, high ? 220 : 120, high ? 16 : 8), mat); membrane.frustumCulled = false; membrane.position.z = -2; scene.add(membrane);
          glow = new THREE.Mesh(new THREE.PlaneGeometry(34, 3.2, 60, 2), new THREE.MeshBasicMaterial({ color: new THREE.Color(p.primary), transparent: true, opacity: .12, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
          glow.material.onBeforeCompile = shader => { Object.assign(shader.uniforms, uniforms); shader.vertexShader = displace + shader.vertexShader.replace('#include <begin_vertex>', 'vec3 transformed = pv_displace(position); transformed.z -= 0.4;'); };
          glow.material.customProgramCacheKey = () => 'pineviz-liquid-glow'; glow.frustumCulled = false; glow.position.z = -2; scene.add(glow);
          lights = [new THREE.PointLight(new THREE.Color(p.accent), 90, 80), new THREE.PointLight(new THREE.Color(p.secondary), 70, 80), new THREE.PointLight(new THREE.Color('#ff7bd5'), 30, 60), new THREE.AmbientLight(new THREE.Color(p.glow), .35)];
          lights[0].position.set(-9, 6, 6); lights[1].position.set(9, -3, 5); lights[2].position.set(0, 5, -6); lights.forEach(l => scene.add(l));
          pressure = new Spring(24, 4, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(p); mat.color.set(p.secondary); if (mat.emissive) mat.emissive.set(p.primary); glow.material.color.set(p.primary); lights[0].color.set(p.accent); lights[1].color.set(p.secondary); if (drops.material) drops.material.color.set(p.secondary); },
        presetChanged(key) { if (key === 'droplets' || key === null) build(); },
        update(s, dt, t) {
          backdrop.tick(s.energy, t);
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; waveAt = t; pressure.push(3 * s.beat); uniforms.uWave.value = clamp(s.beat * 1.3, 0, 1.5); }
          pressure.step(dt);
          const idle = .3 + .7 * clamp(s.energy * 1.5, 0, 1);
          uniforms.uTime.value = t * idle * (ctx.preset.motionAmount ?? 1); uniforms.uBass.value = s.bass * (ctx.preset.intensity || 1); uniforms.uMid.value = s.mid; uniforms.uTreble.value = s.treble; uniforms.uRms.value = s.rms; uniforms.uWaveAt.value = waveAt * idle * (ctx.preset.motionAmount ?? 1); uniforms.uThick.value = (ctx.preset.thickness || 1) * (1 + pressure.value * .1);
          if (mat.emissiveIntensity != null) mat.emissiveIntensity = .08 + s.rms * .55 + s.beat * .2;
          glow.material.opacity = (.06 + s.rms * .3) * (ctx.preset.opacity ?? 1);
          lights[0].intensity = 60 + s.treble * 90; lights[1].intensity = 50 + s.rms * 60; lights[2].intensity = 20 + s.mid * 40;
          for (const d of drops) {
            const near = Math.exp(-Math.abs(d.home.x) * .12) * s.bass + s.treble * .3;
            if (s.beat > .6 && d.shiver.lastBeat !== s.beatCount) { d.shiver.lastBeat = s.beatCount; d.shiver.push(.6 * s.beat * Math.exp(-Math.abs(d.home.x) * .08)); }
            d.shiver.step(dt);
            d.mesh.position.set(d.home.x + noise1(t * .09 + d.seed) * 1.6, d.home.y + noise1(t * .07 + d.seed + 40) * 1.2 + Math.sin(t * .5 + d.seed) * .2 * near, d.home.z + noise1(t * .05 + d.seed + 80));
            d.mesh.scale.setScalar(1 + near * .25 + d.shiver.value);
          }
          camera.position.x = noise1(t * .04) * .6 * (ctx.preset.motionAmount ?? 1); camera.position.y = noise1(t * .03 + 3) * .4 * (ctx.preset.motionAmount ?? 1); camera.lookAt(0, 0, -2);
        },
        resize(w, h) { camera.fitAspect(w / h); },
        dispose() { membrane?.geometry.dispose(); mat?.dispose(); glow?.geometry.dispose(); glow?.material.dispose(); for (const d of drops) d.mesh.geometry.dispose(); drops.material?.dispose(); drops = []; backdrop?.dispose(); },
        count() { return drops.length + 2; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
