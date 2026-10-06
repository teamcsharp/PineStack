/* PineViz - what the ten visualizers share: a gradient backdrop, a soft sprite for points, a spring
 * (mass and damping, so beats are impulses with inertia rather than jumps), a lazy-updating value and
 * a few geometry helpers. Each visualizer keeps its own identity; this is only the plumbing.
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz;
  const { clamp, lerp, approach, GLSL_NOISE } = PineViz.util;

  /** A damped spring: push() adds velocity, step() integrates; `value` eases back to `rest`. */
  class Spring {
    constructor(stiffness = 60, damping = 8, rest = 0) { this.k = stiffness; this.c = damping; this.rest = rest; this.value = rest; this.velocity = 0; }
    push(impulse) { this.velocity += impulse; return this; }
    step(dt) { const n = Math.max(1, Math.ceil(dt / (1 / 120))); const h = dt / n; for (let i = 0; i < n; i++) { const a = -this.k * (this.value - this.rest) - this.c * this.velocity; this.velocity += a * h; this.value += this.velocity * h; } return this.value; }
  }

  /** The vertical gradient every mode sits on: palette.bg at the bottom, bg2 above, a touch of glow in the middle. */
  function gradientBackdrop(THREE, palette) {
    const geo = new THREE.PlaneGeometry(2, 2);
    const mat = new THREE.ShaderMaterial({ depthTest: false, depthWrite: false, uniforms: { uA: { value: new THREE.Color(palette.bg) }, uB: { value: new THREE.Color(palette.bg2) }, uGlow: { value: new THREE.Color(palette.glow) }, uEnergy: { value: 0 }, uTime: { value: 0 } },
      vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.999, 1.0); }`,
      fragmentShader: `${GLSL_NOISE} uniform vec3 uA; uniform vec3 uB; uniform vec3 uGlow; uniform float uEnergy; uniform float uTime; varying vec2 vUv;
        void main(){ float y = smoothstep(0.0, 1.0, vUv.y); vec3 c = mix(uA, uB, y * 0.85);
          float haze = pv_fbm(vec3(vUv * 2.0, uTime * 0.03)) * 0.5 + 0.5;
          c += uGlow * (0.05 + 0.12 * uEnergy) * haze * (1.0 - abs(vUv.y - 0.45) * 1.6);
          gl_FragColor = vec4(c, 1.0); }` });
    const mesh = new THREE.Mesh(geo, mat); mesh.frustumCulled = false; mesh.renderOrder = -1000;
    mesh.setPalette = p => { mat.uniforms.uA.value.set(p.bg); mat.uniforms.uB.value.set(p.bg2); mat.uniforms.uGlow.value.set(p.glow); };
    mesh.tick = (energy, time) => { mat.uniforms.uEnergy.value = energy; mat.uniforms.uTime.value = time; };
    mesh.dispose = () => { geo.dispose(); mat.dispose(); };
    return mesh;
  }

  /** A soft round sprite drawn once on a canvas. */
  function softSprite(THREE, size = 64) {
    const c = document.createElement('canvas'); c.width = c.height = size; const g = c.getContext('2d');
    const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grad.addColorStop(0, 'rgba(255,255,255,1)'); grad.addColorStop(.35, 'rgba(255,255,255,.55)'); grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad; g.fillRect(0, 0, size, size);
    const tex = new THREE.CanvasTexture(c); tex.needsUpdate = true; return tex;
  }

  /** A strip of `segments` quads along X with uv.x 0..1, for ribbons and lines with width. */
  function stripGeometry(THREE, segments, width = 1) {
    const geo = new THREE.PlaneGeometry(width, 1, segments, 1);
    return geo;
  }

  /** A camera for a 16:9 stage that keeps composition on wide and tall surfaces alike. */
  function stageCamera(THREE, aspect, fov = 42, z = 10) {
    const cam = new THREE.PerspectiveCamera(fov, aspect, .1, 200); cam.position.set(0, 0, z); cam.lookAt(0, 0, 0);
    cam.fitAspect = a => { cam.aspect = a; cam.fov = a < 1 ? clamp(fov * (1.25 / a), fov, 90) : fov; cam.updateProjectionMatrix(); };
    cam.fitAspect(aspect); return cam;
  }

  /** Visible half-extent of the z=0 plane for a perspective camera at distance d. */
  function halfExtent(cam, d) { const h = Math.tan(cam.fov * Math.PI / 360) * d; return { x: h * cam.aspect, y: h }; }

  const toColor = (THREE, hex) => new THREE.Color(hex);

  PineViz.shared = { Spring, gradientBackdrop, softSprite, stripGeometry, stageCamera, halfExtent, toColor, clamp, lerp, approach };
})(typeof window !== 'undefined' ? window : globalThis);
