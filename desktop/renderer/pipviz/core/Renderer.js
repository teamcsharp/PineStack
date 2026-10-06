/* PineViz Renderer - one WebGLRenderer, the post stage (restrained bloom), the transition compositor
 * (crossfade, dissolve, fade through darkness) and the quality ladder that steps down when frames run
 * long. Visualizers never touch the canvas: they own a scene and a camera and are drawn here.
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz;
  const { clamp, GLSL_NOISE } = PineViz.util;

  const QUALITY = {
    low: { pixelRatio: .75, scale: .35, bloom: true, post: true },      /* [viz-look] the glow is the look: bloom at every rung */
    medium: { pixelRatio: 1, scale: .6, bloom: true, post: true },
    high: { pixelRatio: 1.25, scale: 1, bloom: true, post: true },
    ultra: { pixelRatio: 2, scale: 1.5, bloom: true, post: true }
  };
  const LADDER = ['low', 'medium', 'high', 'ultra'];

  const QUAD_VERT = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
  const COMPOSITE_FRAG = `
    uniform sampler2D tA; uniform sampler2D tB; uniform sampler2D tBloom;
    uniform float uMix; uniform int uMode; uniform float uBloom; uniform float uTime; uniform vec3 uDark; uniform float uHasB;
    varying vec2 vUv;
    ${GLSL_NOISE}
    void main(){
      vec4 a = texture2D(tA, vUv);
      vec4 b = texture2D(tB, vUv);
      vec4 c = a;
      if (uHasB > 0.5) {
        if (uMode == 1) {              /* dissolve: a noisy curtain with a soft edge */
          float n = pv_fbm(vec3(vUv * 3.0, uTime * 0.2)) * 0.5 + 0.5;
          float edge = smoothstep(uMix - 0.18, uMix + 0.18, n);
          c = mix(b, a, edge);
        } else if (uMode == 2) {       /* fade through darkness */
          float down = 1.0 - smoothstep(0.0, 0.5, uMix);
          float up = smoothstep(0.5, 1.0, uMix);
          c = vec4(mix(uDark, a.rgb, down) * (1.0 - up) + mix(uDark, b.rgb, up) * up, 1.0);
          c.rgb = mix(a.rgb, uDark, smoothstep(0.0, 0.5, uMix));
          c.rgb = mix(c.rgb, b.rgb, smoothstep(0.5, 1.0, uMix));
        } else {                        /* crossfade */
          c = mix(a, b, smoothstep(0.0, 1.0, uMix));
        }
      }
      vec3 bloom = texture2D(tBloom, vUv).rgb;
      c.rgb += bloom * uBloom;
      gl_FragColor = vec4(c.rgb, 1.0);
    }`;
  const BRIGHT_FRAG = `uniform sampler2D tDiffuse; uniform float uThreshold; varying vec2 vUv;
    void main(){ vec3 c = texture2D(tDiffuse, vUv).rgb; float l = dot(c, vec3(0.2126, 0.7152, 0.0722)); float k = smoothstep(uThreshold, uThreshold + 0.35, l); gl_FragColor = vec4(c * k, 1.0); }`;
  const BLUR_FRAG = `uniform sampler2D tDiffuse; uniform vec2 uDir; varying vec2 vUv;
    void main(){ vec3 s = texture2D(tDiffuse, vUv).rgb * 0.2270270270;
      s += texture2D(tDiffuse, vUv + uDir * 1.3846153846).rgb * 0.3162162162; s += texture2D(tDiffuse, vUv - uDir * 1.3846153846).rgb * 0.3162162162;
      s += texture2D(tDiffuse, vUv + uDir * 3.2307692308).rgb * 0.0702702703; s += texture2D(tDiffuse, vUv - uDir * 3.2307692308).rgb * 0.0702702703;
      gl_FragColor = vec4(s, 1.0); }`;

  class Renderer {
    constructor(THREE, options = {}) {
      this.THREE = THREE;
      this.canvas = options.canvas || document.createElement('canvas');
      this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: options.antialias !== false, alpha: false, powerPreference: 'high-performance', preserveDrawingBuffer: !!options.preserveDrawingBuffer });
      this.renderer.autoClear = true;
      /* [viz-look] ACES at the end of the stack, exposure up: neon highlights roll off instead of clipping white */
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.15;
      this.width = 2; this.height = 2;
      this.qualityCap = options.quality || 'high';
      this.quality = this.qualityCap; this.q = QUALITY[this.quality];
      this.auto = options.autoQuality !== false;
      this.frameAvg = 16; this.slowFor = 0; this.fastFor = 0; this.listeners = new Set();
      this.bloomStrength = 1.15; this.bloomThreshold = .22;   /* [viz-look] was .5 / .55, a restraint the reference does not have */
      const pars = { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, format: THREE.RGBAFormat, depthBuffer: true, type: THREE.HalfFloatType };   /* [viz-look] HDR: values past 1 survive into the bloom */
      this.targetA = new THREE.WebGLRenderTarget(2, 2, pars); this.targetB = new THREE.WebGLRenderTarget(2, 2, pars);
      const small = { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, format: THREE.RGBAFormat, depthBuffer: false, type: THREE.HalfFloatType };
      this.bright = new THREE.WebGLRenderTarget(2, 2, small); this.blur1 = new THREE.WebGLRenderTarget(2, 2, small); this.blur2 = new THREE.WebGLRenderTarget(2, 2, small);
      this.quadScene = new THREE.Scene(); this.quadCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      this.composite = new THREE.ShaderMaterial({ vertexShader: QUAD_VERT, fragmentShader: COMPOSITE_FRAG, depthTest: false, depthWrite: false,
        uniforms: { tA: { value: this.targetA.texture }, tB: { value: this.targetB.texture }, tBloom: { value: this.blur2.texture }, uMix: { value: 0 }, uMode: { value: 0 }, uBloom: { value: 0 }, uTime: { value: 0 }, uDark: { value: new THREE.Vector3(0, .02, .08) }, uHasB: { value: 0 } } });
      this.brightMat = new THREE.ShaderMaterial({ vertexShader: QUAD_VERT, fragmentShader: BRIGHT_FRAG, depthTest: false, depthWrite: false, uniforms: { tDiffuse: { value: null }, uThreshold: { value: this.bloomThreshold } } });
      this.blurMat = new THREE.ShaderMaterial({ vertexShader: QUAD_VERT, fragmentShader: BLUR_FRAG, depthTest: false, depthWrite: false, uniforms: { tDiffuse: { value: null }, uDir: { value: new THREE.Vector2(1, 0) } } });
      this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.composite); this.quad.frustumCulled = false; this.quadScene.add(this.quad);
      this.blank = new THREE.Scene(); this.blankCamera = new THREE.PerspectiveCamera(50, 1, .1, 10);
    }
    get info() { return this.renderer.info; }
    onQuality(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
    setQuality(level, fromAuto = false) {
      if (!QUALITY[level] || level === this.quality) return;
      this.quality = level; this.q = QUALITY[level];
      if (!fromAuto) this.qualityCap = level;
      this.setSize(this.width, this.height);
      this.listeners.forEach(fn => { try { fn(level, this.q); } catch (_) {} });
    }
    setSize(width, height) {
      this.width = Math.max(2, Math.floor(width)); this.height = Math.max(2, Math.floor(height));
      const dpr = Math.min(this.q.pixelRatio, root.devicePixelRatio || 1);
      this.renderer.setPixelRatio(dpr); this.renderer.setSize(this.width, this.height, false);
      const w = Math.floor(this.width * dpr), h = Math.floor(this.height * dpr);
      this.targetA.setSize(w, h); this.targetB.setSize(w, h);
      const bw = Math.max(2, Math.floor(w / 4)), bh = Math.max(2, Math.floor(h / 4));
      this.bright.setSize(bw, bh); this.blur1.setSize(bw, bh); this.blur2.setSize(bw, bh);
      this.blurMat.uniforms.uDir.value.set(1 / bw, 1 / bh);
    }
    /* frame time bookkeeping: three seconds slow steps down; twenty seconds fast steps back up, never past the cap */
    tick(dt) {
      if (!this.auto) return;
      this.frameAvg += (dt * 1000 - this.frameAvg) * .08;
      if (this.frameAvg > 24) { this.slowFor += dt; this.fastFor = 0; } else if (this.frameAvg < 12) { this.fastFor += dt; this.slowFor = 0; } else { this.slowFor = Math.max(0, this.slowFor - dt); this.fastFor = 0; }
      const at = LADDER.indexOf(this.quality), cap = LADDER.indexOf(this.qualityCap);
      if (this.slowFor > 3 && at > 0) { this.slowFor = 0; this.setQuality(LADDER[at - 1], true); }
      else if (this.fastFor > 20 && at < cap) { this.fastFor = 0; this.setQuality(LADDER[at + 1], true); }
    }
    clearColor(hex) { this.renderer.setClearColor(new this.THREE.Color(hex), 1); const c = new this.THREE.Color(hex); this.composite.uniforms.uDark.value.set(c.r, c.g, c.b); }
    /** Draw one visualizer (or two mid-transition) to the screen. `persist` visualizers keep their own canvas history: no clear. */
    draw(active, incoming, mix, mode, time, bloom) {
      const R = this.renderer, post = this.q.post, useBloom = this.q.bloom && bloom > 0 && !(active && active.persist);
      const sceneOf = v => v && v.scene ? v.scene : this.blank, cameraOf = v => v && v.camera ? v.camera : this.blankCamera;
      if (!post || (!incoming && !useBloom)) {
        R.setRenderTarget(null); R.autoClear = !(active && active.persist);
        R.render(sceneOf(active), cameraOf(active)); R.autoClear = true; return;
      }
      R.setRenderTarget(this.targetA); R.autoClear = !(active && active.persist); R.render(sceneOf(active), cameraOf(active)); R.autoClear = true;
      if (incoming) { R.setRenderTarget(this.targetB); R.autoClear = !incoming.persist; R.render(sceneOf(incoming), cameraOf(incoming)); R.autoClear = true; }
      if (useBloom) {
        this.quad.material = this.brightMat; this.brightMat.uniforms.tDiffuse.value = this.targetA.texture; this.brightMat.uniforms.uThreshold.value = this.bloomThreshold;
        R.setRenderTarget(this.bright); R.render(this.quadScene, this.quadCamera);
        this.quad.material = this.blurMat;
        this.blurMat.uniforms.tDiffuse.value = this.bright.texture; this.blurMat.uniforms.uDir.value.set(1 / this.bright.width, 0); R.setRenderTarget(this.blur1); R.render(this.quadScene, this.quadCamera);
        this.blurMat.uniforms.tDiffuse.value = this.blur1.texture; this.blurMat.uniforms.uDir.value.set(0, 1 / this.bright.height); R.setRenderTarget(this.blur2); R.render(this.quadScene, this.quadCamera);
      }
      this.quad.material = this.composite;
      const u = this.composite.uniforms;
      u.uMix.value = clamp(mix || 0, 0, 1); u.uMode.value = mode || 0; u.uTime.value = time || 0; u.uHasB.value = incoming ? 1 : 0;
      u.uBloom.value = useBloom ? bloom * 1.25 : 0;   /* [viz-look] */
      R.setRenderTarget(null); R.render(this.quadScene, this.quadCamera);
    }
    dispose() { for (const t of [this.targetA, this.targetB, this.bright, this.blur1, this.blur2]) t.dispose(); this.quad.geometry.dispose(); this.composite.dispose(); this.brightMat.dispose(); this.blurMat.dispose(); this.renderer.dispose(); }
  }
  PineViz.QUALITY = QUALITY; PineViz.QUALITY_LADDER = LADDER; PineViz.Renderer = Renderer;
})(typeof window !== 'undefined' ? window : globalThis);
