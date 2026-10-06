/* 06 ANIME INK WAVE - hand-drawn seas. One full-stage shader paints the whole picture: a dark navy sky
 * with a pale moon and posterised clouds, two great waves travelling across the frame as cel-shaded
 * bands with ink outlines, painted foam and brush marks; a second layer of ink spray is a point cloud.
 * The big movement is fluid; the clouds, the spray and the brush marks step at 8 and 12 frames a second
 * on purpose, the way a drawn sequence does. Procedural throughout - nothing loops.
 *   bass -> swell  mids -> the second wave  treble -> foam and ink  beat -> a crest / splash  volume -> saturation
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { Spring, softSprite } = PineViz.shared;

  PineViz.register({
    id: 'anime-ink', index: 6, name: 'Anime Ink Wave', blurb: 'hand-drawn ink seas',
    defaults: { bloom: .2, ink: 1 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, sea, mat, spray, sprayMat, sprite, crest, lastBeat = 0, splashAt = -9, drops = 0, seeds;
      return {
        init() {
          scene = new THREE.Scene(); camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 10); camera.position.z = 1;
          const p = ctx.palette;
          mat = new THREE.ShaderMaterial({ depthTest: false, depthWrite: false,
            uniforms: { uTime: { value: 0 }, uAspect: { value: 1.78 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uCrest: { value: 0 }, uSplashAt: { value: -9 }, uInk: { value: 1 },
              uSky: { value: new THREE.Color(p.bg) }, uSky2: { value: new THREE.Color(p.bg2) }, uWater: { value: new THREE.Color(p.primary) }, uWater2: { value: new THREE.Color(p.secondary) }, uFoam: { value: new THREE.Color(p.accent) }, uInkColor: { value: new THREE.Color(p.bg).multiplyScalar(.4) } },
            vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
            fragmentShader: `${GLSL_NOISE}
              uniform float uTime; uniform float uAspect; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uRms; uniform float uEnergy; uniform float uCrest; uniform float uSplashAt; uniform float uInk;
              uniform vec3 uSky; uniform vec3 uSky2; uniform vec3 uWater; uniform vec3 uWater2; uniform vec3 uFoam; uniform vec3 uInkColor; varying vec2 vUv;
              float stepTime(float t, float fps){ return floor(t * fps) / fps; }
              /* a wave's surface height at x, as a drawn curve: a slow swell plus a travelling crest */
              float surface(float x, float t, float phase, float swell, float speed){
                float s = sin(x * 2.2 + t * speed + phase) * 0.5 + 0.5;
                float crest = pow(s, 2.6) * (0.9 + 0.6 * swell);
                float roll = pv_snoise(vec3(x * 1.7 - t * speed * 0.6, phase, t * 0.08)) * 0.08;
                return crest * 0.22 + roll + 0.18 * swell * sin(x * 0.7 - t * speed * 0.4 + phase);
              }
              void main(){
                vec2 uv = vUv; float x = (uv.x - 0.5) * uAspect; float t = uTime;
                float sat = 0.55 + 0.45 * clamp(uRms * 1.6 + uEnergy * 0.5, 0.0, 1.0);
                /* sky and moon */
                vec3 c = mix(uSky, uSky2, smoothstep(0.1, 0.95, uv.y) * 0.9);
                vec2 moonAt = vec2(0.28 * uAspect + sin(t * 0.03) * 0.05, 0.72);
                float moon = smoothstep(0.17, 0.165, length(vec2(x, uv.y) - moonAt));
                float moonShade = step(0.5, pv_snoise(vec3((vec2(x, uv.y) - moonAt) * 9.0, 2.0)) * 0.5 + 0.5) * 0.12;
                c = mix(c, mix(uWater2, uFoam, 0.55) * (0.85 - moonShade), moon * 0.9);
                /* clouds: posterised noise, stepping at 8 fps */
                float ct = stepTime(t, 8.0);
                float cloud = pv_fbm(vec3(x * 1.2 + ct * 0.05, uv.y * 2.6, ct * 0.02)) * 0.5 + 0.5;
                float cloudBand = smoothstep(0.52, 0.56, cloud) * smoothstep(0.35, 0.6, uv.y) * smoothstep(1.0, 0.75, uv.y);
                float cloudInk = smoothstep(0.52, 0.53, cloud) - smoothstep(0.545, 0.555, cloud);
                c = mix(c, uSky2 * 1.5, cloudBand * 0.55); c = mix(c, uInkColor, cloudInk * cloudBand * 0.9 * uInk);
                /* the far wave (mids) and the great wave (bass) */
                float swell = clamp(uBass * 1.4 + uCrest * 0.6, 0.0, 1.6);
                float far = 0.42 + surface(x + 3.0, t, 1.7, uMid * 1.2, 0.55) * 0.7;
                float near = 0.26 + surface(x, t, 0.0, swell, 0.75) + uCrest * 0.08 * exp(-pow(x - 0.3, 2.0) * 2.0);
                /* a splash: a plume above the near crest that falls back */
                float since = t - uSplashAt; float plume = exp(-since * 1.6) * smoothstep(0.0, 0.25, since) * (1.0 - smoothstep(0.0, 1.3, since));
                near += plume * 0.25 * exp(-pow(x - 0.3, 2.0) * 3.0) * (0.5 + 0.5 * pv_snoise(vec3(x * 12.0, since * 3.0, 4.0)));
                float dFar = far - uv.y, dNear = near - uv.y;
                float aa = 2.0 / 900.0;
                /* far wave: flat cel bands, an ink line on its edge */
                if (dFar > 0.0) {
                  float band = floor(clamp(dFar * 6.0, 0.0, 2.99));
                  vec3 w = mix(uWater * 0.55, uWater2 * 0.7, band * 0.5) * (0.7 + 0.3 * sat);
                  c = mix(c, w, 0.92); c = mix(c, uFoam * 0.75, smoothstep(0.012, 0.0, dFar) * 0.6);
                  c = mix(c, uInkColor, (1.0 - smoothstep(0.0, aa * 2.5, dFar)) * uInk);
                }
                /* near wave: three cel steps, painted foam along the crest, stepped spray above it */
                if (dNear > 0.0) {
                  float band = floor(clamp(dNear * 4.5, 0.0, 2.99));
                  vec3 w = mix(uWater, uWater2 * 0.9, band * 0.45) * (0.75 + 0.35 * sat);
                  float foamN = pv_snoise(vec3(x * 14.0 - t * 1.5, dNear * 60.0, stepTime(t, 12.0) * 0.5)) * 0.5 + 0.5;
                  float foam = smoothstep(0.08 + uTreble * 0.06, 0.0, dNear) * step(0.42, foamN);
                  vec3 painted = mix(w, uFoam, 0.92);
                  c = mix(w, painted, foam);
                  float inkEdge = (1.0 - smoothstep(0.0, aa * 3.0, dNear)) + step(0.985, foamN) * smoothstep(0.1, 0.0, dNear) * 0.8;
                  c = mix(c, uInkColor, clamp(inkEdge, 0.0, 1.0) * uInk);
                  /* graphic shadow bands inside the body */
                  float shade = step(0.5, fract((uv.y + x * 0.3) * 9.0 + stepTime(t, 8.0) * 0.5)) * smoothstep(0.08, 0.3, dNear) * 0.08;
                  c -= shade;
                } else {
                  float spray = step(0.975 - uTreble * 0.06 - plume * 0.08, pv_hash(floor(vec2(x * 220.0, uv.y * 220.0) + stepTime(t, 10.0) * 7.0))) * smoothstep(0.1 + plume * 0.3, 0.0, -dNear);
                  c = mix(c, uFoam, spray * 0.9);
                }
                /* brush marks: a few dry strokes that appear and dissolve on the stepped clock */
                float bt = stepTime(t, 8.0);
                vec2 sp = vec2(x * 1.3 + bt * 0.09, uv.y * 1.3);
                float stroke = pv_snoise(vec3(sp * 4.0, bt * 0.37));
                float strokeMask = smoothstep(0.78, 0.82, stroke) * smoothstep(0.6, 0.4, abs(uv.y - 0.35) * 2.0) * (0.3 + 0.7 * uEnergy);
                c = mix(c, uInkColor, strokeMask * 0.7 * uInk);
                gl_FragColor = vec4(c, 1.0);
              }` });
          sea = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat); sea.frustumCulled = false; scene.add(sea);
          /* ink spray: points flung on treble and splashes, stepping as they fall */
          sprite = softSprite(THREE, 32); drops = Math.round(400 * Math.max(.5, ctx.quality.scale));
          const geo = new THREE.BufferGeometry(); seeds = new Float32Array(drops * 3); for (let i = 0; i < drops; i++) { seeds[i * 3] = ctx.rng(); seeds[i * 3 + 1] = ctx.rng(); seeds[i * 3 + 2] = ctx.rng(); }
          geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(drops * 3), 3)); geo.setAttribute('seed', new THREE.BufferAttribute(seeds, 3));
          sprayMat = new THREE.ShaderMaterial({ transparent: true, depthTest: false, depthWrite: false, uniforms: { uTime: { value: 0 }, uAspect: { value: 1.78 }, uTreble: { value: 0 }, uSplashAt: { value: -9 }, uColor: { value: new THREE.Color(p.accent) }, uInkColor: { value: new THREE.Color(p.bg).multiplyScalar(.4) }, tSprite: { value: sprite } },
            vertexShader: `attribute vec3 seed; uniform float uTime; uniform float uAspect; uniform float uTreble; uniform float uSplashAt; varying float vInk; varying float vLife;
              void main(){ float st = floor(uTime * 12.0) / 12.0; float period = 1.4 + seed.z * 1.2; float life = fract(st / period + seed.x);
                float since = uTime - uSplashAt; float burst = exp(-since * 1.5);
                float x = (seed.x - 0.5) * 1.9 + 0.1; float y0 = -0.45 + 0.45 * sin(x * 2.2 * uAspect + st * 0.75) * 0.5;
                float vy = (0.5 + seed.y * 0.9) * (0.4 + uTreble + burst * 1.8); float h = vy * life - 1.6 * life * life;
                float px = x + (seed.y - 0.5) * 0.3 * life; float py = y0 + h * 0.6;
                vInk = step(0.5, seed.z); vLife = (1.0 - life) * step(0.02, uTreble + burst);
                gl_Position = vec4(px, py, 0.0, 1.0); gl_PointSize = (2.0 + seed.y * 5.0) * (1.0 - life * 0.6); }`,
            fragmentShader: `uniform sampler2D tSprite; uniform vec3 uColor; uniform vec3 uInkColor; varying float vInk; varying float vLife; void main(){ float a = step(0.35, texture2D(tSprite, gl_PointCoord).a); gl_FragColor = vec4(mix(uColor, uInkColor, vInk), a * vLife); }` });
          spray = new THREE.Points(geo, sprayMat); spray.frustumCulled = false; scene.add(spray);
          crest = new Spring(16, 3.4, 0);
        },
        activate() {}, deactivate() {},
        palette(p) { const u = mat.uniforms; u.uSky.value.set(p.bg); u.uSky2.value.set(p.bg2); u.uWater.value.set(p.primary); u.uWater2.value.set(p.secondary); u.uFoam.value.set(p.accent); u.uInkColor.value.set(p.bg).multiplyScalar(.4); sprayMat.uniforms.uColor.value.set(p.accent); sprayMat.uniforms.uInkColor.value.set(p.bg).multiplyScalar(.4); },
        update(s, dt, t) {
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; crest.push(2.4 * s.beat); if (s.beat > .75) splashAt = t; }
          crest.step(dt);
          const idle = .35 + .65 * clamp(s.energy * 1.5, 0, 1), u = mat.uniforms;
          u.uTime.value = t * idle * (ctx.preset.motionAmount ?? 1); u.uBass.value = s.bass * (ctx.preset.intensity || 1); u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uRms.value = s.rms; u.uEnergy.value = s.energy; u.uCrest.value = clamp(crest.value, 0, 2); u.uSplashAt.value = splashAt * idle; u.uInk.value = ctx.preset.ink ?? 1;
          sprayMat.uniforms.uTime.value = t; sprayMat.uniforms.uTreble.value = s.treble; sprayMat.uniforms.uSplashAt.value = splashAt;
        },
        resize(w, h) { mat.uniforms.uAspect.value = w / h; sprayMat.uniforms.uAspect.value = w / h; },
        dispose() { sea?.geometry.dispose(); mat?.dispose(); spray?.geometry.dispose(); sprayMat?.dispose(); sprite?.dispose(); },
        count() { return drops + 2; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
