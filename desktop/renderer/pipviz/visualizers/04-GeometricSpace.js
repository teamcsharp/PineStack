/* 04 GEOMETRIC SPACE - floating 3D geometry. Twenty-odd polyhedra, rings and hollow cubes in zero gravity
 * at different depths, each with its own spin, drift, scale and audio temperament: glass bodies with
 * emissive wire edges, a slow energy ribbon threading the scene, fragments that spawn on hard beats and
 * fade, and a camera that drifts a few centimetres. Nothing is synchronised.
 *   bass -> breathing of the large bodies  mids -> spin  treble -> edge light and the small ones' fuss
 *   rms -> ambient glow  beat -> an outward impulse through springs
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { noise2, noise1, clamp, lerp, GLSL_NOISE } = PineViz.util, { gradientBackdrop, stageCamera, Spring } = PineViz.shared;

  PineViz.register({
    id: 'geometric-space', index: 4, name: 'Geometric Space', blurb: 'floating glass geometry',
    defaults: { objects: 26, bloom: .8, glass: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, bodies = [], fragments = [], ribbon, lights = [], lastBeat = 0, impulse;
      const geometries = () => [new THREE.TetrahedronGeometry(1), new THREE.OctahedronGeometry(1), new THREE.IcosahedronGeometry(1, 0), new THREE.TorusGeometry(.9, .18, 10, 36), new THREE.BoxGeometry(1.3, 1.3, 1.3), new THREE.DodecahedronGeometry(1, 0), new THREE.ConeGeometry(.8, 1.6, 5)];
      function bodyMaterial(p, i) {
        const glass = ctx.quality.scale >= .6 && (ctx.preset.glass ?? 1) > 0;
        if (glass) return new THREE.MeshPhysicalMaterial({ color: new THREE.Color(i % 3 ? p.primary : p.secondary), metalness: .05, roughness: .18, transmission: .82, thickness: 1.2, ior: 1.35, transparent: true, opacity: .85, iridescence: .6, iridescenceIOR: 1.3, emissive: new THREE.Color(p.glow), emissiveIntensity: .08, side: THREE.DoubleSide });
        return new THREE.MeshPhongMaterial({ color: new THREE.Color(i % 3 ? p.primary : p.secondary), transparent: true, opacity: .4, shininess: 90, emissive: new THREE.Color(p.glow), emissiveIntensity: .1, side: THREE.DoubleSide });
      }
      function build() {
        for (const b of bodies) { scene.remove(b.group); b.mesh.geometry.dispose(); b.mesh.material.dispose(); b.edges.geometry.dispose(); b.edges.material.dispose(); } bodies = [];
        const n = Math.max(8, Math.round((ctx.preset.objects || 26) * (ctx.quality.scale < .5 ? .6 : 1))), p = ctx.palette, kinds = geometries();
        for (let i = 0; i < n; i++) {
          const geo = kinds[i % kinds.length].clone(), mat = bodyMaterial(p, i);
          const mesh = new THREE.Mesh(geo, mat);
          const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 12), new THREE.LineBasicMaterial({ color: new THREE.Color(i % 2 ? p.secondary : p.accent), transparent: true, opacity: .55, blending: THREE.AdditiveBlending }));
          const group = new THREE.Group(); group.add(mesh, edges);
          const size = .25 + ctx.rng() ** 2 * 1.4, angle = ctx.rng() * Math.PI * 2, radius = 3.5 + ctx.rng() * 6.5;
          group.position.set(Math.cos(angle) * radius * 1.4, Math.sin(angle) * radius * .55, -3 - ctx.rng() * 14);
          group.scale.setScalar(size);
          bodies.push({ group, mesh, edges, size, spin: new THREE.Vector3(ctx.rng() - .5, ctx.rng() - .5, ctx.rng() - .5).multiplyScalar(.6), drift: new THREE.Vector3(ctx.rng() - .5, ctx.rng() - .5, (ctx.rng() - .5) * .3).multiplyScalar(.25), home: group.position.clone(), seed: ctx.rng() * 10, temper: ctx.rng(), spring: new Spring(30 + ctx.rng() * 40, 4 + ctx.rng() * 4, 0) });
          scene.add(group);
        }
      }
      function spawnFragments(s) {
        if (ctx.quality.scale < .5) return;
        const p = ctx.palette, n = 6 + Math.round(s.beat * 10);
        for (let i = 0; i < n && fragments.length < 80; i++) {
          const geo = new THREE.TetrahedronGeometry(.12 + ctx.rng() * .14), mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(ctx.rng() > .5 ? p.accent : p.secondary), transparent: true, opacity: .9, blending: THREE.AdditiveBlending });
          const mesh = new THREE.Mesh(geo, mat); const from = bodies[Math.floor(ctx.rng() * bodies.length)];
          mesh.position.copy(from ? from.group.position : new THREE.Vector3(0, 0, -6));
          const vel = new THREE.Vector3(ctx.rng() - .5, ctx.rng() - .5, ctx.rng() - .5).normalize().multiplyScalar(2 + ctx.rng() * 3);
          fragments.push({ mesh, vel, life: 1.4 + ctx.rng(), age: 0, spin: new THREE.Vector3(ctx.rng(), ctx.rng(), ctx.rng()).multiplyScalar(4) }); scene.add(mesh);
        }
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 46, 9);
          backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop);
          const p = ctx.palette;
          lights = [new THREE.PointLight(new THREE.Color(p.secondary), 60, 60), new THREE.PointLight(new THREE.Color(p.accent), 40, 60), new THREE.AmbientLight(new THREE.Color(p.glow), .5)];
          lights[0].position.set(-8, 5, 4); lights[1].position.set(8, -4, 2); lights.forEach(l => scene.add(l));
          /* the thread: one soft ribbon of light through the field */
          const geo = new THREE.PlaneGeometry(1, 1, 120, 1);
          const mat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, uniforms: { uColor: { value: new THREE.Color(p.secondary) }, uTime: { value: 0 }, uGlow: { value: .4 } },
            vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
            fragmentShader: `${GLSL_NOISE} uniform vec3 uColor; uniform float uTime; uniform float uGlow; varying vec2 vUv; void main(){ float a = pow(1.0 - abs(vUv.y - 0.5) * 2.0, 2.2) * (0.4 + 0.6 * (pv_snoise(vec3(vUv.x * 6.0 - uTime * 0.6, 0.0, 1.0)) * 0.5 + 0.5)); gl_FragColor = vec4(uColor * (0.6 + uGlow), a * (0.25 + uGlow * 0.5) * smoothstep(0.0, 0.1, vUv.x) * smoothstep(1.0, 0.9, vUv.x)); }` });
          ribbon = new THREE.Mesh(geo, mat); ribbon.frustumCulled = false; ribbon.position.z = -7; scene.add(ribbon);
          impulse = new Spring(18, 3.2, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(p); build(); lights[0].color.set(p.secondary); lights[1].color.set(p.accent); ribbon.material.uniforms.uColor.value.set(p.secondary); },
        presetChanged(key) { if (key === 'objects' || key === 'glass' || key === null) build(); },
        update(s, dt, t) {
          backdrop.tick(s.energy, t);
          const idle = .25 + .75 * clamp(s.energy * 1.5, 0, 1), motion = (ctx.preset.motionAmount ?? 1);
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; impulse.push(2.6 * s.beat); for (const b of bodies) b.spring.push((1.2 + b.temper) * s.beat * (b.size > .9 ? .6 : 1.4)); if (s.beat > .8) spawnFragments(s); }
          impulse.step(dt);
          for (const b of bodies) {
            const spin = (.25 + s.mid * 1.6 + b.temper * .4) * idle * motion;
            b.group.rotation.x += b.spin.x * spin * dt * 2; b.group.rotation.y += b.spin.y * spin * dt * 2; b.group.rotation.z += b.spin.z * spin * dt * 2;
            const wander = new THREE.Vector3(noise1(t * .12 + b.seed), noise1(t * .1 + b.seed + 30), noise1(t * .08 + b.seed + 60)).multiplyScalar(1.4 * idle * motion);
            const out = b.spring.step(dt);
            b.group.position.copy(b.home).add(wander).add(b.home.clone().setZ(0).normalize().multiplyScalar(out * .6));
            const breathe = 1 + (b.size > .9 ? s.bass * .35 : s.treble * .25) + out * .08;
            b.group.scale.setScalar(b.size * breathe);
            b.edges.material.opacity = (.3 + s.treble * .9 + s.beat * .3) * (ctx.preset.opacity ?? 1);
            if (b.mesh.material.emissiveIntensity != null) b.mesh.material.emissiveIntensity = .06 + s.rms * .35 + out * .05;
          }
          for (let i = fragments.length - 1; i >= 0; i--) {
            const f = fragments[i]; f.age += dt; f.vel.multiplyScalar(1 - dt * 1.4); f.mesh.position.addScaledVector(f.vel, dt); f.mesh.rotation.x += f.spin.x * dt; f.mesh.rotation.y += f.spin.y * dt;
            f.mesh.material.opacity = .9 * (1 - f.age / f.life);
            if (f.age >= f.life) { scene.remove(f.mesh); f.mesh.geometry.dispose(); f.mesh.material.dispose(); fragments.splice(i, 1); }
          }
          const rp = ribbon.geometry.attributes.position, cols = 121;
          for (let i = 0; i < cols; i++) { const u = i / 120, x = (u - .5) * 30; const y = Math.sin(x * .3 + t * .4) * (1.2 + s.bass * 2) + noise2(x * .2, t * .15) * 2 - 1.5, w = .35 + s.rms * .6; rp.setXYZ(i, x, y + w, 0); rp.setXYZ(i + cols, x, y - w, 0); }
          rp.needsUpdate = true; ribbon.material.uniforms.uTime.value = t; ribbon.material.uniforms.uGlow.value = s.rms * .8 + s.beat * .4;
          lights[0].intensity = 40 + s.rms * 60; lights[1].intensity = 25 + s.treble * 50;
          camera.position.x = noise1(t * .05) * .35 * motion; camera.position.y = noise1(t * .04 + 7) * .25 * motion + impulse.value * .05; camera.lookAt(0, 0, -6);
        },
        resize(w, h) { camera.fitAspect(w / h); },
        dispose() { for (const b of bodies) { b.mesh.geometry.dispose(); b.mesh.material.dispose(); b.edges.geometry.dispose(); b.edges.material.dispose(); } bodies = []; for (const f of fragments) { f.mesh.geometry.dispose(); f.mesh.material.dispose(); } fragments = []; ribbon?.geometry.dispose(); ribbon?.material.dispose(); backdrop?.dispose(); },
        count() { return bodies.length + fragments.length; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
