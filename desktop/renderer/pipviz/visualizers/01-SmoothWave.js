/* 01 SMOOTH WAVE - silk light. Three bundles of fine translucent filaments rise from the lower left and
 * cross to the upper right over a deep blue field, as in the panel: each bundle is a band whose strands
 * fan out and converge (where they converge the light adds up into a bright crest), under each band a
 * wide soft veil carries the glow, and a few bright white filaments ride the crest. Every layer is one
 * strip mesh shaped in the vertex shader; nothing is re-randomised per frame.
 *   rms -> brightness  bass -> the long swell  mids -> ripple along the strands  treble -> the crest light
 *   beat -> a width pulse through a spring  silence -> a slow, graceful drift
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { Spring, stageCamera, halfExtent } = PineViz.shared;

  PineViz.register({
    id: 'smooth-wave', index: 1, name: 'Smooth Wave', blurb: 'flowing silk ribbons',
    defaults: { bands: 3, strands: 26, width: 1, bloom: .5, intensity: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, field, layers = [], pulse, clock = 0, lastBeat = 0, half = { x: 8, y: 4.5 };
      const SEG = 180, DIST = 11.5;

      /* ---- the field: dark at the top, a blue bloom low on the left and a faint one where the crest lands */
      function fieldBackdrop(p) {
        const geo = new THREE.PlaneGeometry(2, 2);
        const mat = new THREE.ShaderMaterial({ depthTest: false, depthWrite: false,
          uniforms: { uA: { value: new THREE.Color(p.bg) }, uB: { value: new THREE.Color(p.bg2) }, uEnergy: { value: 0 } },
          vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.999, 1.0); }`,
          fragmentShader: `uniform vec3 uA; uniform vec3 uB; uniform float uEnergy; varying vec2 vUv;
            void main(){
              vec3 c = mix(uA * 1.5, uA * 0.55, smoothstep(0.0, 1.0, vUv.y));
              vec2 d1 = (vUv - vec2(0.20, 0.28)) * vec2(1.0, 1.6);
              vec2 d2 = vUv - vec2(0.80, 0.72);
              c += uB * (0.42 * exp(-dot(d1, d1) * 3.2) + 0.16 * exp(-dot(d2, d2) * 7.0)) * (0.85 + 0.35 * uEnergy);
              gl_FragColor = vec4(c, 1.0); }` });
        const mesh = new THREE.Mesh(geo, mat); mesh.frustumCulled = false; mesh.renderOrder = -1000;
        mesh.setPalette = q => { mat.uniforms.uA.value.set(q.bg); mat.uniforms.uB.value.set(q.bg2); };
        mesh.tick = e => { mat.uniforms.uEnergy.value = e; };
        mesh.dispose = () => { geo.dispose(); mat.dispose(); };
        return mesh;
      }

      /* ---- a strip mesh: `count` strands, each SEG quads, with the band and the strand's place in it */
      function strips(count, bands, place) {
        const rows = SEG + 1, verts = count * rows * 2;
        const aU = new Float32Array(verts), aSide = new Float32Array(verts), aInfo = new Float32Array(verts * 4);
        const index = new Uint32Array(count * SEG * 6);
        let v = 0, k = 0;
        for (let s = 0; s < count; s++) {
          const band = s % bands, frac = place === 'centre' ? .5 : (Math.floor(s / bands) + .5) / Math.max(1, Math.ceil(count / bands));
          const r1 = ctx.rng(), r2 = ctx.rng(), base = s * rows * 2;
          for (let i = 0; i < rows; i++) {
            for (let side = -1; side <= 1; side += 2) {
              aU[v] = i / SEG; aSide[v] = side;
              aInfo[v * 4] = place === 'centre' ? .5 : frac + (r1 - .5) * .06; aInfo[v * 4 + 1] = band; aInfo[v * 4 + 2] = r1; aInfo[v * 4 + 3] = r2;
              v++;
            }
            if (i < SEG) { const a = base + i * 2; index[k++] = a; index[k++] = a + 1; index[k++] = a + 2; index[k++] = a + 1; index[k++] = a + 3; index[k++] = a + 2; }
          }
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute('aU', new THREE.BufferAttribute(aU, 1)); geo.setAttribute('aSide', new THREE.BufferAttribute(aSide, 1));
        geo.setAttribute('aInfo', new THREE.BufferAttribute(aInfo, 4)); geo.setIndex(new THREE.BufferAttribute(index, 1));
        /* three.js wants a position attribute to count vertices; the shader ignores it */
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(verts * 3), 3));
        return geo;
      }

      const VERT = `${GLSL_NOISE}
        attribute float aU; attribute float aSide; attribute vec4 aInfo;
        uniform float uTime; uniform float uBass; uniform float uMid; uniform float uPulse; uniform float uSeed; uniform float uWidth; uniform float uSpread; uniform float uVeil;
        uniform vec2 uHalf;
        varying float vSide; varying float vU; varying float vFan; varying float vBand; varying float vRand;
        float band_y(float x, float band, float t) {
          float ph = band * 2.3 + uSeed;
          float u = x / uHalf.x;
          float rise = u * uHalf.y * (0.24 + 0.07 * band);                                   /* lower left to upper right */
          float swell = sin(u * 2.6 + t * 0.21 + ph) * uHalf.y * (0.15 + 0.12 * uBass);
          float wave = sin(u * 5.4 - t * 0.13 + ph * 1.7) * uHalf.y * (0.07 + 0.05 * uBass);
          float drift = pv_snoise(vec3(u + ph, t * 0.06, band)) * uHalf.y * 0.09;
          return rise + swell + wave + drift + (band - 1.0) * uHalf.y * 0.14;
        }
        float fan_at(float x, float band, float t, float r) {
          /* how far the bundle is opened here: 0 = converged (the light adds up), 1 = fanned */
          return 0.5 + 0.5 * sin(x / uHalf.x * 2.4 + t * 0.17 + band * 1.9 + uSeed * 0.7 + r * 0.9);
        }
        float strand_y(float x, vec4 info, float t) {
          float fan = fan_at(x, info.y, t, info.z);
          float off = (info.x - 0.5) * 2.0;
          float y = band_y(x, info.y, t) + off * mix(0.12, 1.0, fan) * uSpread * uHalf.y * (0.75 + 0.5 * info.w);
          y += sin(x * 1.3 + t * 0.7 + info.w * 7.0) * uHalf.y * (0.006 + 0.05 * uMid) * (0.5 + info.z);
          return y;
        }
        void main() {
          float x = (aU - 0.5) * 2.0 * uHalf.x * 1.15;
          float t = uTime;
          float y = strand_y(x, aInfo, t);
          float y2 = strand_y(x + 0.05, aInfo, t);
          vec2 tang = normalize(vec2(0.05, y2 - y)); vec2 nrm = vec2(-tang.y, tang.x);
          float fan = fan_at(x, aInfo.y, t, aInfo.z);
          float w = uWidth * (0.5 + aInfo.w) * (1.0 + uPulse * 0.6);
          w *= mix(1.0, 0.7 + 0.6 * fan, uVeil);                                                 /* a veil breathes with the fan */
          vec3 p = vec3(vec2(x, y) + nrm * aSide * w, -0.5 - aInfo.y * 1.5);
          vSide = aSide; vU = aU; vFan = fan; vBand = aInfo.y; vRand = aInfo.w;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        }`;
      const FRAG = `
        uniform vec3 uA; uniform vec3 uB; uniform vec3 uWhite; uniform float uRms; uniform float uTreble; uniform float uEnergy; uniform float uAlpha; uniform float uVeil;
        varying float vSide; varying float vU; varying float vFan; varying float vBand; varying float vRand;
        void main() {
          float a = exp(-vSide * vSide * mix(3.5, 2.0, uVeil));
          float ends = smoothstep(0.0, 0.10, vU) * smoothstep(1.0, 0.90, vU);
          float conv = 1.0 - vFan;                                                              /* converged = bright */
          float depth = 1.0 - vBand * 0.2;
          float lum = (0.5 + 0.5 * conv) * (0.75 + 0.5 * uRms + 0.3 * uEnergy) * depth;
          vec3 c = mix(uA, uB, conv * 0.6 + vRand * 0.2);
          c = mix(c, uWhite, conv * conv * (0.45 + 0.45 * uTreble) * (1.0 - uVeil * 0.8));
          gl_FragColor = vec4(c * lum, a * ends * uAlpha); }`;

      function material(colorA, colorB, alpha, width, spread, veil) {
        return new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
          uniforms: { uTime: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uPulse: { value: 0 }, uSeed: { value: ctx.rng() * 20 },
            uWidth: { value: width }, uSpread: { value: spread }, uVeil: { value: veil }, uAlpha: { value: alpha }, uHalf: { value: new THREE.Vector2(half.x, half.y) },
            uA: { value: new THREE.Color(colorA) }, uB: { value: new THREE.Color(colorB) }, uWhite: { value: new THREE.Color(ctx.palette.accent) } },
          vertexShader: VERT, fragmentShader: FRAG });
      }
      function build() {
        for (const l of layers) { scene.remove(l.mesh); l.mesh.geometry.dispose(); l.mesh.material.dispose(); }
        layers = [];
        const p = ctx.palette, bands = clamp(Math.round(ctx.preset.bands || 3), 2, 4);
        const strands = Math.max(8, Math.round((ctx.preset.strands || 26) * (ctx.quality.scale < .5 ? .6 : 1))) * bands;
        const w = (ctx.preset.width || 1);
        const seed = ctx.rng() * 20;
        const add = (geo, mat) => { const mesh = new THREE.Mesh(geo, mat); mesh.frustumCulled = false; mat.uniforms.uSeed.value = seed; scene.add(mesh); layers.push({ mesh, mat }); };
        add(strips(bands * 2, bands, 'centre'), material(p.glow, p.secondary, .14, .95 * w, .34, 1));      /* the veils: wide, soft, pale, one glow per band */
        add(strips(strands, bands, 'spread'), material(p.secondary, p.glow, .34, .022 * w, .34, 0));   /* the silk: many fine filaments */
        add(strips(bands * 3, bands, 'spread'), material(p.accent, p.secondary, .6, .024 * w, .30, 0)); /* a few bright white threads on the crest */
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 40, 10);
          half = halfExtent(camera, DIST);
          field = fieldBackdrop(ctx.palette); scene.add(field);
          pulse = new Spring(70, 9, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) {
          field.setPalette(p);
          const cols = [[p.glow, p.secondary], [p.secondary, p.glow], [p.accent, p.secondary]];
          layers.forEach((l, i) => { l.mat.uniforms.uA.value.set(cols[i][0]); l.mat.uniforms.uB.value.set(cols[i][1]); l.mat.uniforms.uWhite.value.set(p.accent); });
        },
        presetChanged(key) { if (key === 'bands' || key === 'strands' || key === 'width' || key === null) build(); },
        update(s, dt) {
          if (s.beat > .5 && lastBeat !== s.beatCount) { lastBeat = s.beatCount; pulse.push(1.6 * s.beat); }
          pulse.step(dt);
          clock += dt * (0.45 + 0.65 * clamp(s.energy * 1.4, 0, 1)) * (ctx.preset.speed || 1);
          field.tick(s.energy);
          const gain = (ctx.preset.intensity || 1) * (ctx.preset.opacity ?? 1);
          for (const l of layers) {
            const u = l.mat.uniforms; u.uTime.value = clock; u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble;
            u.uRms.value = s.rms * gain; u.uEnergy.value = s.energy; u.uPulse.value = clamp(pulse.value, -.4, 1.2);
          }
        },
        resize(w, h) { camera.fitAspect(w / h); half = halfExtent(camera, DIST); for (const l of layers) l.mat.uniforms.uHalf.value.set(half.x, half.y); },
        dispose() { for (const l of layers) { l.mesh.geometry.dispose(); l.mat.dispose(); } layers = []; field?.dispose(); },
        count() { return layers.reduce((n, l) => n + l.mesh.geometry.index.count / 6, 0); },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
