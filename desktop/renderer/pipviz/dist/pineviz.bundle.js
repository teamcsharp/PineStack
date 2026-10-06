/* PineViz bundle f71f113dec67 - built by tools/pineviz_bundle.py from desktop/renderer/pipviz; edit the sources, not this file. */
/* pineviz-build:f71f113dec67 */
/* ---- core/PineViz.js ---- */
/* PineViz - the Pine PiP's living background. One telemetry road, ten visual environments.
 *
 *   AUDIO / RADIO TELEMETRY -> provider -> SignalProcessor -> VisualizerState -> smoothing
 *   -> the active visualizer -> Three.js -> post (bloom, transitions) -> screen
 *
 * This file is the core: the namespace, the utilities every visualizer shares (noise, a seeded
 * random, colour helpers), VisualizerState, the SignalProcessor with its beat detector, the
 * palettes and the preset store. Renderer.js, VisualizerManager.js, audio/Providers.js and
 * ui/Overlay.js build on it; each visualizer registers itself with PineViz.register().
 * Plain scripts, one namespace: the Pine desktop loads scripts by tag, and the station serves
 * the bundle (tools/pineviz_bundle.py) from its vendor route into the PiP panel.
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz = root.PineViz || {};
  PineViz.VERSION = '1.0.0';

  /* ------------------------------------------------------------------ utilities */
  const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;
  const lerp = (a, b, t) => a + (b - a) * t;
  const smoothstep = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  /* an exponential approach: how far a value moves towards its target in dt seconds with time constant tau */
  const approach = (value, target, dt, tau) => tau <= 0 ? target : value + (target - value) * (1 - Math.exp(-dt / tau));
  function mulberry32(seed) {
    let a = (seed >>> 0) || 1;
    return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  }
  /* coherent value noise in 1, 2 and 3 dimensions, with fbm; good enough for drift, cheap enough for CPU paths */
  const PERM = new Uint8Array(512); { const r = mulberry32(1337); const p = []; for (let i = 0; i < 256; i++) p.push(i); for (let i = 255; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [p[i], p[j]] = [p[j], p[i]]; } for (let i = 0; i < 512; i++) PERM[i] = p[i & 255]; }
  const fade = t => t * t * t * (t * (t * 6 - 15) + 10);
  const grad3 = (h, x, y, z) => { const g = h & 15; const u = g < 8 ? x : y, v = g < 4 ? y : g === 12 || g === 14 ? x : z; return ((g & 1) ? -u : u) + ((g & 2) ? -v : v); };
  function noise3(x, y, z) {
    const X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255;
    x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z);
    const u = fade(x), v = fade(y), w = fade(z);
    const A = PERM[X] + Y, AA = PERM[A] + Z, AB = PERM[A + 1] + Z, B = PERM[X + 1] + Y, BA = PERM[B] + Z, BB = PERM[B + 1] + Z;
    return lerp(lerp(lerp(grad3(PERM[AA], x, y, z), grad3(PERM[BA], x - 1, y, z), u), lerp(grad3(PERM[AB], x, y - 1, z), grad3(PERM[BB], x - 1, y - 1, z), u), v),
      lerp(lerp(grad3(PERM[AA + 1], x, y, z - 1), grad3(PERM[BA + 1], x - 1, y, z - 1), u), lerp(grad3(PERM[AB + 1], x, y - 1, z - 1), grad3(PERM[BB + 1], x - 1, y - 1, z - 1), u), v), w);
  }
  const noise2 = (x, y) => noise3(x, y, 0.37);
  const noise1 = x => noise3(x, 0.71, 0.13);
  function fbm3(x, y, z, octaves = 4, lacunarity = 2, gain = .5) { let a = 1, f = 1, sum = 0, norm = 0; for (let i = 0; i < octaves; i++) { sum += a * noise3(x * f, y * f, z * f); norm += a; a *= gain; f *= lacunarity; } return sum / norm; }
  const fbm2 = (x, y, o) => fbm3(x, y, 0.5, o);
  /* GLSL fragments shared by the shader-driven visualizers */
  const GLSL_NOISE = `
    vec3 pv_mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
    vec4 pv_mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
    vec4 pv_permute(vec4 x){return pv_mod289(((x*34.0)+1.0)*x);}
    vec4 pv_taylor(vec4 r){return 1.79284291400159-0.85373472095314*r;}
    float pv_snoise(vec3 v){
      const vec2 C=vec2(1.0/6.0,1.0/3.0);const vec4 D=vec4(0.0,0.5,1.0,2.0);
      vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);
      vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.0-g;vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);
      vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
      i=pv_mod289(i);
      vec4 p=pv_permute(pv_permute(pv_permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
      float n_=0.142857142857;vec3 ns=n_*D.wyz-D.xzx;
      vec4 j=p-49.0*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.0*x_);
      vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.0-abs(x)-abs(y);
      vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
      vec4 s0=floor(b0)*2.0+1.0;vec4 s1=floor(b1)*2.0+1.0;vec4 sh=-step(h,vec4(0.0));
      vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
      vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
      vec4 norm=pv_taylor(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
      p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
      vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);m=m*m;
      return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
    }
    float pv_fbm(vec3 p){float a=0.5,s=0.0;for(int i=0;i<4;i++){s+=a*pv_snoise(p);p=p*2.02+vec3(13.1,7.7,3.3);a*=0.5;}return s;}
    float pv_hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453123);}
  `;
  function hexToRgb(hex) { const n = parseInt(String(hex).replace('#', ''), 16); return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]; }
  function mixHex(a, b, t) { const x = hexToRgb(a), y = hexToRgb(b); return '#' + [0, 1, 2].map(i => Math.round(lerp(x[i], y[i], t) * 255).toString(16).padStart(2, '0')).join(''); }
  PineViz.util = { clamp, lerp, smoothstep, approach, mulberry32, noise1, noise2, noise3, fbm2, fbm3, GLSL_NOISE, hexToRgb, mixHex };

  /* ------------------------------------------------------------------ VisualizerState */
  const FFT_BINS = 64;
  /** The one object every visualizer reads. Everything 0..1 except fft (64 log-spaced bins, 0..1 each). */
  class VisualizerState {
    constructor() {
      this.rms = 0; this.peak = 0; this.bass = 0; this.mid = 0; this.treble = 0; this.beat = 0;
      this.speechActivity = 0; this.stationActivity = 0; this.music = 0;
      this.fft = new Float32Array(FFT_BINS);
      this.energy = 0;          /* a slow envelope of everything: the "how alive" number idle behaviour reads */
      this.beatCount = 0;       /* beats since the start; a visualizer can notice a new one */
      this.time = 0;
    }
    copyFrom(other) { for (const k of ['rms', 'peak', 'bass', 'mid', 'treble', 'beat', 'speechActivity', 'stationActivity', 'music', 'energy', 'beatCount', 'time']) this[k] = other[k]; this.fft.set(other.fft); return this; }
  }
  PineViz.FFT_BINS = FFT_BINS;
  PineViz.VisualizerState = VisualizerState;

  /* ------------------------------------------------------------------ SignalProcessor */
  /* An envelope: separate attack and decay time constants, an optional peak hold. */
  class Envelope {
    constructor(attack, decay, hold = 0) { this.attack = attack; this.decay = decay; this.hold = hold; this.value = 0; this.held = 0; }
    step(target, dt) {
      if (target >= this.value) { this.value = approach(this.value, target, dt, this.attack); this.held = this.hold; }
      else if (this.held > 0) this.held -= dt;
      else this.value = approach(this.value, target, dt, this.decay);
      return this.value;
    }
  }
  /** Spectral-flux onset detector on the low bins with an adaptive threshold and a refractory period. */
  class BeatDetector {
    constructor() { this.prev = null; this.history = new Float32Array(43); this.at = 0; this.filled = 0; this.refractory = 0; this.value = 0; this.count = 0; this.tau = .18; }
    step(fft, dt) {
      const n = Math.max(4, Math.floor(fft.length * .3));
      let flux = 0;
      if (this.prev) for (let i = 0; i < n; i++) { const d = fft[i] - this.prev[i]; if (d > 0) flux += d; }
      else this.prev = new Float32Array(fft.length);
      this.prev.set(fft);
      let mean = 0, varsum = 0;
      const m = this.filled || 1;
      for (let i = 0; i < this.filled; i++) mean += this.history[i];
      mean /= m;
      for (let i = 0; i < this.filled; i++) { const d = this.history[i] - mean; varsum += d * d; }
      const std = Math.sqrt(varsum / m);
      this.history[this.at] = flux; this.at = (this.at + 1) % this.history.length; this.filled = Math.min(this.history.length, this.filled + 1);
      this.refractory -= dt;
      const threshold = mean + Math.max(.035, 1.6 * std);
      if (this.filled > 12 && flux > threshold && this.refractory <= 0 && flux > .05) {
        this.value = Math.min(1, .55 + (flux - threshold) * 4);
        this.refractory = .12; this.count++;
      } else this.value *= Math.exp(-dt / this.tau);
      return this.value;
    }
  }
  /**
   * Raw samples in, VisualizerState out. A provider hands `sample({fft, rms, peak, speech, activity, music})`
   * (fft: any length of 0..1 or 0..255 values, linear bins); the processor groups it into 64 log-spaced
   * bins, takes the noise floor off, normalises against a slowly adapting ceiling, runs every property
   * through its own envelope and detects beats. Nothing a visualizer reads is a raw FFT value.
   */
  class SignalProcessor {
    constructor(options = {}) {
      this.state = new VisualizerState();
      this.raw = new Float32Array(FFT_BINS);
      this.grouped = new Float32Array(FFT_BINS);
      this.floor = new Float32Array(FFT_BINS).fill(.08);
      this.ceiling = .35;
      this.sensitivity = options.sensitivity ?? 1;
      this.smoothing = options.smoothing ?? 1;
      this.env = {
        bass: new Envelope(.12, .38), mid: new Envelope(.06, .22), treble: new Envelope(.02, .09),
        rms: new Envelope(.08, .28), peak: new Envelope(.001, .5, .35), speech: new Envelope(.25, .9),
        activity: new Envelope(.6, 2.4), music: new Envelope(.5, 1.6), energy: new Envelope(.4, 1.8)
      };
      this.binEnv = { attack: .03, decay: .14 };
      this.beat = new BeatDetector();
      this.lastSample = null; this.sampleAge = 0;
    }
    sample(raw) { this.lastSample = raw; this.sampleAge = 0; }
    /* linear bins of any length into 64 log-spaced groups, 0..1 */
    group(fft) {
      const out = this.raw, n = fft.length, scale = n > 0 && fft[0] > 1.5 ? 1 / 255 : 1;
      if (!n) { out.fill(0); return out; }
      const lo = 1, hi = n;
      for (let i = 0; i < FFT_BINS; i++) {
        const a = Math.floor(lo * Math.pow(hi / lo, i / FFT_BINS)), b = Math.max(a + 1, Math.floor(lo * Math.pow(hi / lo, (i + 1) / FFT_BINS)));
        let sum = 0, count = 0;
        for (let j = a; j < b && j < n; j++) { sum += fft[j] * scale; count++; }
        out[i] = count ? sum / count : 0;
      }
      return out;
    }
    update(dt) {
      dt = clamp(dt, 1 / 240, .1);
      const s = this.state, raw = this.lastSample; this.sampleAge += dt;
      const stale = !raw || this.sampleAge > 1.2;   /* a provider that went quiet reads as silence */
      const fftIn = raw && raw.fft && raw.fft.length ? this.group(raw.fft) : this.raw.fill(0);
      /* noise floor: a slow running minimum that only rises slowly; dynamic ceiling: a running maximum that decays */
      let maxv = 0;
      for (let i = 0; i < FFT_BINS; i++) {
        const v = stale ? 0 : fftIn[i];
        this.floor[i] = v < this.floor[i] ? approach(this.floor[i], v, dt, .4) : approach(this.floor[i], v, dt, 30);
        const cleaned = Math.max(0, v - this.floor[i] * .9);
        this.grouped[i] = cleaned; if (cleaned > maxv) maxv = cleaned;
      }
      this.ceiling = maxv > this.ceiling ? approach(this.ceiling, maxv, dt, .25) : approach(this.ceiling, Math.max(.18, maxv), dt, 6);
      const gain = clamp(1 / Math.max(.08, this.ceiling), 1, 4) * this.sensitivity;
      let bass = 0, mid = 0, treble = 0, bn = 0, mn = 0, tn = 0;
      for (let i = 0; i < FFT_BINS; i++) {
        const target = clamp(this.grouped[i] * gain, 0, 1);
        const cur = s.fft[i];
        s.fft[i] = approach(cur, target, dt, (target > cur ? this.binEnv.attack : this.binEnv.decay) * this.smoothing);
        if (i < 9) { bass += target; bn++; } else if (i < 30) { mid += target; mn++; } else { treble += target; tn++; }
      }
      bass /= bn; mid /= mn; treble /= tn;
      const rmsIn = stale ? 0 : clamp(((raw.rms ?? (bass * .5 + mid * .35 + treble * .15)) * gain), 0, 1);
      const peakIn = stale ? 0 : clamp((raw.peak ?? rmsIn * 1.4) * gain, 0, 1);
      s.bass = this.env.bass.step(bass, dt * this.smoothing);
      s.mid = this.env.mid.step(mid, dt * this.smoothing);
      s.treble = this.env.treble.step(Math.min(1, treble * 1.6), dt * this.smoothing);
      s.rms = this.env.rms.step(rmsIn, dt * this.smoothing);
      s.peak = this.env.peak.step(peakIn, dt);
      s.beat = this.beat.step(this.grouped, dt); s.beatCount = this.beat.count;
      const speechIn = stale ? 0 : clamp(raw.speech ?? (mid > .12 && bass < .6 ? mid * 1.5 : 0), 0, 1);
      s.speechActivity = this.env.speech.step(speechIn, dt);
      const activityIn = stale ? 0 : clamp(raw.activity ?? Math.max(rmsIn * 1.3, speechIn), 0, 1);
      s.stationActivity = this.env.activity.step(activityIn, dt);
      s.music = this.env.music.step(stale ? 0 : clamp(raw.music ?? (bass > .35 && this.beat.count > 2 ? .7 : 0), 0, 1), dt);
      s.energy = this.env.energy.step(clamp(s.rms * .6 + s.stationActivity * .3 + s.beat * .3, 0, 1), dt);
      s.time += dt;
      return s;
    }
  }
  PineViz.Envelope = Envelope; PineViz.BeatDetector = BeatDetector; PineViz.SignalProcessor = SignalProcessor;

  /* ------------------------------------------------------------------ palettes */
  const PALETTES = {
    playstation: { name: 'PlayStation Blue', bg: '#020a26', bg2: '#0b2d73', primary: '#1f66ff', secondary: '#49d8ff', accent: '#ffffff', glow: '#7fb6ff', ink: '#dbe9ff' },
    neon: { name: 'Neon', bg: '#05020f', bg2: '#160a3a', primary: '#2ad8ff', secondary: '#8b3dff', accent: '#ff3cf0', glow: '#4a6bff', ink: '#f2e9ff' },
    mono: { name: 'Monochrome', bg: '#05070e', bg2: '#141b2d', primary: '#ffffff', secondary: '#b8c1d1', accent: '#e9edf3', glow: '#7f8aa0', ink: '#ffffff' },
    radioNight: { name: 'Radio Night', bg: '#000000', bg2: '#031028', primary: '#0f6f90', secondary: '#1ea8cc', accent: '#6fdcf0', glow: '#0a4260', ink: '#9fd6e6' }
  };
  class PaletteManager {
    constructor(name = 'playstation') { this.listeners = new Set(); this.set(name); }
    get names() { return Object.keys(PALETTES); }
    set(name) { if (!PALETTES[name]) name = 'playstation'; this.name = name; this.colors = { ...PALETTES[name] }; this.listeners.forEach(fn => { try { fn(this.colors, name); } catch (_) {} }); return this.colors; }
    next() { const names = this.names; return this.set(names[(names.indexOf(this.name) + 1) % names.length]); }
    onChange(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  }
  PineViz.PALETTES = PALETTES; PineViz.PaletteManager = PaletteManager;

  /* ------------------------------------------------------------------ presets */
  const COMMON_DEFAULTS = { intensity: 1, speed: 1, audioSensitivity: 1, smoothing: 1, bloom: .5, opacity: 1, complexity: 1, motionAmount: 1 };
  /**
   * Every visualizer's adjustable properties. Defaults come from the visualizer's registration; the
   * operator's values are kept as JSON (localStorage, or wherever `store` points). presets.json in the
   * project is the same shape, for hand editing and for shipping defaults.
   */
  class PresetManager {
    constructor(options = {}) {
      this.key = options.key || 'pineviz.presets';
      this.store = options.store || (root.localStorage ? { get: () => root.localStorage.getItem(this.key), set: v => root.localStorage.setItem(this.key, v) } : { get: () => null, set: () => {} });
      this.defaults = {}; this.values = {}; this.listeners = new Set();
      try { const saved = JSON.parse(this.store.get() || '{}'); if (saved && typeof saved === 'object') this.values = saved; } catch (_) { this.values = {}; }
    }
    define(id, defaults) { this.defaults[id] = { ...COMMON_DEFAULTS, ...(defaults || {}) }; if (!this.values[id]) this.values[id] = {}; return this.get(id); }
    get(id) { return { ...(this.defaults[id] || COMMON_DEFAULTS), ...(this.values[id] || {}) }; }
    set(id, key, value) { this.values[id] = this.values[id] || {}; this.values[id][key] = value; this.save(); this.listeners.forEach(fn => { try { fn(id, key, value); } catch (_) {} }); }
    reset(id) { delete this.values[id]; this.save(); this.listeners.forEach(fn => { try { fn(id, null, null); } catch (_) {} }); }
    load(json) { const data = typeof json === 'string' ? JSON.parse(json) : json; if (data && typeof data === 'object') { for (const [id, values] of Object.entries(data)) if (values && typeof values === 'object') this.values[id] = { ...(this.values[id] || {}), ...values }; this.save(); } }
    toJSON() { return JSON.parse(JSON.stringify(this.values)); }
    save() { try { this.store.set(JSON.stringify(this.values)); } catch (_) {} }
    onChange(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  }
  PineViz.COMMON_DEFAULTS = COMMON_DEFAULTS; PineViz.PresetManager = PresetManager;

  /* ------------------------------------------------------------------ registry */
  PineViz.registry = PineViz.registry || [];
  /** A visualizer module: {id, index, name, blurb, defaults, persist?, create(ctx) -> {init, activate, update, resize, deactivate, dispose, scene, camera, count}} */
  PineViz.register = function (def) {
    if (!def || !def.id || typeof def.create !== 'function') throw new Error('PineViz.register needs {id, create}');
    const have = PineViz.registry.findIndex(d => d.id === def.id);
    if (have >= 0) PineViz.registry[have] = def; else PineViz.registry.push(def);
    PineViz.registry.sort((a, b) => (a.index ?? 99) - (b.index ?? 99));   /* index 0 is a real place: the classic cloud comes first */
    return def;
  };
  PineViz.modes = () => PineViz.registry.map(d => ({ id: d.id, index: d.index, name: d.name, blurb: d.blurb }));
})(typeof window !== 'undefined' ? window : globalThis);

/* ---- core/Renderer.js ---- */
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

/* ---- core/VisualizerManager.js ---- */
/* PineViz VisualizerManager - owns the loop, the active visualizer and the one coming in, the provider,
 * the processor, the palette, the presets, and the ways to switch (click the background, keys 1-0,
 * the selector). Visualizers are created lazily and kept: switching never rebuilds GPU resources.
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz;
  const { clamp, mulberry32 } = PineViz.util;
  const TRANSITIONS = { crossfade: 0, dissolve: 1, dark: 2 };

  class VisualizerManager {
    /**
     * @param container  the element the canvas fills
     * @param options    {THREE, palette, quality, autoQuality, provider, transition, transitionMs, mode, presets, store, click, keys, demo}
     */
    constructor(container, options = {}) {
      this.THREE = options.THREE || root.THREE;
      if (!this.THREE) throw new Error('PineViz needs THREE on the page before mount()');
      this.container = container;
      this.options = options;
      this.palette = new PineViz.PaletteManager(options.palette || 'playstation');
      this.presets = new PineViz.PresetManager({ key: options.presetKey, store: options.store });
      this.processor = new PineViz.SignalProcessor();
      this.renderer = new PineViz.Renderer(this.THREE, { quality: options.quality || 'high', autoQuality: options.autoQuality, canvas: options.canvas, preserveDrawingBuffer: options.preserveDrawingBuffer });
      this.canvas = this.renderer.canvas;
      Object.assign(this.canvas.style, { position: 'absolute', inset: '0', width: '100%', height: '100%', display: 'block' });
      this.canvas.className = 'pineviz-canvas';
      if (!options.canvas) container.appendChild(this.canvas);
      this.instances = new Map(); this.active = null; this.incoming = null;
      this.transition = { at: 0, dur: (options.transitionMs || 950) / 1000, mode: TRANSITIONS[options.transition || 'crossfade'] || 0 };
      this.listeners = new Set();
      this.time = 0; this.last = 0; this.raf = 0; this.running = false; this.fps = 60; this.frames = 0; this.fpsAt = 0;
      this.provider = null;
      this.rng = mulberry32(options.seed || 7);
      this.size = { w: 2, h: 2, aspect: 1 };
      this.stateCopy = new PineViz.VisualizerState();
      this.observer = typeof ResizeObserver === 'function' ? new ResizeObserver(() => this.resize()) : null;
      if (this.observer) this.observer.observe(container);
      this.palette.onChange(() => { this.renderer.clearColor(this.palette.colors.bg); for (const v of this.instances.values()) v.palette?.(this.palette.colors); });
      this.renderer.onQuality((level, q) => { for (const [id, v] of this.instances) { if (v === this.active || v === this.incoming) this.rebuild(id); else { this.disposeInstance(id); } } this.emit('quality', level); });
      this.presets.onChange((id, key, value) => { const v = this.instances.get(id); if (v) { v.preset = this.presets.get(id); v.presetChanged?.(key, value); } });
      this.renderer.clearColor(this.palette.colors.bg);
      this.clickMode = options.click; if (options.click !== false) this.installClick();
      if (options.keys !== false) this.installKeys();
      this.resize();
      const first = options.mode || this.remembered() || (PineViz.registry[0] && PineViz.registry[0].id);
      if (first) this.set(first, { instant: true });
    }
    /* ---------------------------------------------------------------- providers */
    setProvider(provider) {
      if (this.provider && this.provider !== provider) { try { this.provider.stop?.(); } catch (_) {} }
      this.provider = provider;
      if (provider) { provider.onSample = raw => this.processor.sample(raw); try { provider.start?.(); } catch (e) { this.emit('error', e); } }
      this.emit('provider', provider);
    }
    /* ---------------------------------------------------------------- modes */
    get modes() { return PineViz.modes(); }
    get activeId() { return this.active ? this.active.id : null; }
    remembered() { try { return root.localStorage?.getItem(this.options.modeKey || 'pineviz.mode') || null; } catch (_) { return null; } }
    remember(id) { try { root.localStorage?.setItem(this.options.modeKey || 'pineviz.mode', id); } catch (_) {} }
    context(def) {
      const self = this;
      return {
        THREE: this.THREE, renderer: this.renderer.renderer, gl: this.renderer,
        get palette() { return self.palette.colors; },
        get quality() { return { level: self.renderer.quality, ...self.renderer.q }; },
        get size() { return self.size; },
        preset: this.presets.define(def.id, def.defaults),
        rng: mulberry32((def.index || 1) * 7919 + 17),
        util: PineViz.util,
        manager: this
      };
    }
    instance(id) {
      let v = this.instances.get(id);
      if (v) return v;
      const def = PineViz.registry.find(d => d.id === id);
      if (!def) throw new Error('PineViz: no visualizer ' + id);
      const ctx = this.context(def);
      v = def.create(ctx);
      v.id = def.id; v.def = def; v.ctx = ctx; v.preset = ctx.preset; v.persist = !!def.persist; v.ready = false;
      this.instances.set(id, v);
      return v;
    }
    ensureReady(v) { if (!v.ready) { v.init?.(); v.resize?.(this.size.w, this.size.h); v.ready = true; } return v; }
    rebuild(id) { const v = this.instances.get(id); if (!v) return; try { v.dispose?.(); } catch (_) {} v.ready = false; this.ensureReady(v); if (v === this.active || v === this.incoming) v.activate?.(); }
    disposeInstance(id) { const v = this.instances.get(id); if (!v) return; try { v.deactivate?.(); v.dispose?.(); } catch (_) {} this.instances.delete(id); }
    set(id, options = {}) {
      if (!PineViz.registry.some(d => d.id === id)) return false;
      if (this.active && this.active.id === id && !this.incoming) return true;
      const next = this.ensureReady(this.instance(id));
      if (this.incoming) { try { this.incoming.deactivate?.(); } catch (_) {} this.incoming = null; }
      next.activate?.();
      if (!this.active || options.instant) {
        if (this.active && this.active !== next) { try { this.active.deactivate?.(); } catch (_) {} }
        this.active = next; this.transition.at = 0;
      } else {
        this.incoming = next; this.transition.at = 1e-6;
        this.transition.mode = TRANSITIONS[options.transition] ?? this.transition.mode;
      }
      this.remember(id);
      this.emit('mode', id);
      return true;
    }
    next(step = 1) { const ids = PineViz.registry.map(d => d.id); if (!ids.length) return null; const at = ids.indexOf(this.active?.id); const id = ids[((at < 0 ? 0 : at) + step + ids.length) % ids.length]; this.set(id); return id; }
    setByIndex(index) { const def = PineViz.registry.find(d => d.index === index) || PineViz.registry[index - 1]; if (def) this.set(def.id); return def ? def.id : null; }
    /* ---------------------------------------------------------------- input roads */
    installClick() {
      /* [viz-dblclick] click: true - a click cycles (260 ms wait so a double-click still reaches the surface's owner);
         click: 'double' - a DOUBLE-click cycles and does not reach the owner (the PiP would expand on it); a click is left alone */
      let timer = 0; const dbl = this.clickMode === 'double';
      this.canvas.addEventListener('click', e => {
        if (dbl) return;
        if (e.detail > 1) { clearTimeout(timer); timer = 0; return; }
        clearTimeout(timer);
        timer = setTimeout(() => { timer = 0; this.next(e.shiftKey ? -1 : 1); }, 260);
      });
      this.canvas.addEventListener('dblclick', e => { clearTimeout(timer); timer = 0; if (dbl) { e.stopPropagation(); e.preventDefault(); this.next(e.shiftKey ? -1 : 1); } });
    }
    installKeys() {
      this.keyHandler = e => {
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        const tag = (e.target && e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target?.isContentEditable) return;
        if (/^[0-9]$/.test(e.key)) { const n = e.key === '0' ? 10 : Number(e.key); if (this.setByIndex(n)) e.preventDefault(); }
        else if (e.key === 'p' || e.key === 'P') this.palette.next();
      };
      (this.options.keyTarget || root).addEventListener('keydown', this.keyHandler);
    }
    /* ---------------------------------------------------------------- the loop */
    resize() {
      const r = this.container.getBoundingClientRect();
      const w = Math.max(2, Math.floor(r.width || this.container.clientWidth || 2)), h = Math.max(2, Math.floor(r.height || this.container.clientHeight || 2));
      if (w === this.size.w && h === this.size.h) return;
      this.size = { w, h, aspect: w / h };
      this.renderer.setSize(w, h);
      for (const v of this.instances.values()) if (v.ready) v.resize?.(w, h);
    }
    start() { if (this.running) return this; this.running = true; this.last = 0; const step = t => { if (!this.running) return; this.raf = root.requestAnimationFrame(step); this.frame(t); }; this.raf = root.requestAnimationFrame(step); return this; }
    stop() { this.running = false; root.cancelAnimationFrame(this.raf); this.raf = 0; return this; }
    frame(now) {
      const t = now / 1000, dt = this.last ? clamp(t - this.last, 1 / 240, .1) : 1 / 60; this.last = t; this.time += dt;
      this.frames++; if (t - this.fpsAt >= .5) { this.fps = this.frames / (t - this.fpsAt); this.frames = 0; this.fpsAt = t; }
      this.provider?.update?.(dt, this.time);
      const state = this.processor.update(dt);
      if (this.active) {
        const p = this.active.preset; const sensed = this.sensed(state, p);
        this.active.update(sensed, dt * (p.speed || 1), this.time * (p.speed || 1));
      }
      let mix = 0;
      if (this.incoming) {
        this.transition.at += dt / this.transition.dur; mix = clamp(this.transition.at, 0, 1);
        const p = this.incoming.preset; this.incoming.update(this.sensed(state, p), dt * (p.speed || 1), this.time * (p.speed || 1));
        if (mix >= 1) { const old = this.active; this.active = this.incoming; this.incoming = null; try { old?.deactivate?.(); } catch (_) {} mix = 0; this.emit('settled', this.active.id); }
      }
      const bloom = this.active ? clamp((this.active.preset.bloom ?? .5), 0, 1.5) : 0;
      this.renderer.draw(this.active, this.incoming, mix, this.transition.mode, this.time, bloom);
      this.renderer.tick(dt);
      this.emit('frame', state);
    }
    /* the visualizer's own sensitivity/smoothing scale what it is handed; the processor stays shared */
    sensed(state, preset) {
      const s = this.stateCopy.copyFrom(state), k = preset.audioSensitivity ?? 1;
      if (k !== 1) { for (const key of ['rms', 'peak', 'bass', 'mid', 'treble', 'beat', 'speechActivity', 'stationActivity', 'energy']) s[key] = clamp(s[key] * k, 0, 1); for (let i = 0; i < s.fft.length; i++) s.fft[i] = clamp(s.fft[i] * k, 0, 1); }
      return s;
    }
    count() { return this.active?.count?.() || 0; }
    on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
    emit(kind, value) { this.listeners.forEach(fn => { try { fn(kind, value, this); } catch (_) {} }); }
    dispose() {
      this.stop(); this.observer?.disconnect(); if (this.keyHandler) (this.options.keyTarget || root).removeEventListener('keydown', this.keyHandler);
      try { this.provider?.stop?.(); } catch (_) {}
      for (const id of [...this.instances.keys()]) this.disposeInstance(id);
      this.renderer.dispose(); this.canvas.remove();
    }
  }
  PineViz.TRANSITIONS = TRANSITIONS; PineViz.VisualizerManager = VisualizerManager;
  /** mount(container, options) -> manager; the one call a host page needs */
  PineViz.mount = (container, options = {}) => {
    const m = new VisualizerManager(container, options);
    if (options.provider) m.setProvider(options.provider);
    else if (options.demo !== false && PineViz.DemoProvider) m.setProvider(new PineViz.DemoProvider());
    if (options.autostart !== false) m.start();
    return m;
  };
})(typeof window !== 'undefined' ? window : globalThis);

/* ---- audio/Providers.js ---- */
/* PineViz providers - where the telemetry comes from. Every provider hands the processor the same raw
 * sample: {fft (linear bins, 0..1 or 0..255), rms, peak, speech, activity, music}. The processor does
 * the rest, so a visualizer never knows which road fed it.
 *
 *   DemoProvider        synthetic radio life: silence, conversation, energetic talk, music, bass-heavy
 *                       music, transients, quiet ambience - cycling, so every mode can be judged without
 *                       a microphone or a station.
 *   MicrophoneProvider  Web Audio AnalyserNode on getUserMedia.
 *   ExternalProvider    frames over a WebSocket (JSON), or fed in-page by the host (the PiP panel hands
 *                       it the station's own analysers and telemetry).
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz;
  const { clamp, mulberry32, noise1 } = PineViz.util;

  class Provider {
    constructor() { this.onSample = null; this.name = 'provider'; }
    emit(raw) { if (this.onSample) this.onSample(raw); }
    start() {} stop() {} update() {}
  }

  const SCENES = [
    { name: 'silence', seconds: 7, level: 0, speech: 0, music: 0, bass: 0, beat: 0, treble: 0, activity: 0 },
    { name: 'conversation', seconds: 14, level: .42, speech: 1, music: 0, bass: .18, beat: 0, treble: .35, activity: .55 },
    { name: 'energetic conversation', seconds: 11, level: .7, speech: 1, music: 0, bass: .3, beat: 0, treble: .6, activity: .85 },
    { name: 'music', seconds: 18, level: .62, speech: 0, music: 1, bass: .55, beat: 118, treble: .5, activity: .8 },
    { name: 'bass-heavy music', seconds: 16, level: .78, speech: 0, music: 1, bass: 1, beat: 92, treble: .3, activity: .95 },
    { name: 'transients', seconds: 9, level: .3, speech: 0, music: 0, bass: .4, beat: 0, treble: .7, activity: .5, hits: true },
    { name: 'quiet ambience', seconds: 12, level: .12, speech: 0, music: .2, bass: .15, beat: 0, treble: .15, activity: .15 }
  ];
  /** Convincing synthetic station life, cycling through the scenes above with soft edges between them. */
  class DemoProvider extends Provider {
    constructor(options = {}) {
      super(); this.name = 'demo';
      this.rng = mulberry32(options.seed || 42); this.bins = new Float32Array(128); this.at = 0; this.scene = 0; this.sceneAt = 0;
      this.hold = options.hold || null;      /* a scene name to stay on, for the HUD */
      this.cur = { ...SCENES[0] }; this.beatPhase = 0; this.lastHit = 0; this.syllable = 0; this.speechGate = 0;
      if (this.hold) { const i = SCENES.findIndex(s => s.name === this.hold); if (i >= 0) this.scene = i; else this.hold = null; }
    }
    get sceneName() { return SCENES[this.scene].name; }
    setScene(name) { const i = SCENES.findIndex(s => s.name === name); if (i >= 0) { this.scene = i; this.sceneAt = 0; this.hold = name; } }
    update(dt, time) {
      this.at += dt; this.sceneAt += dt;
      const target = SCENES[this.scene];
      if (!this.hold && this.sceneAt > target.seconds) { this.scene = (this.scene + 1) % SCENES.length; this.sceneAt = 0; }
      /* ease every scene parameter so a change of scene is a change of weather, not a cut */
      for (const k of ['level', 'speech', 'music', 'bass', 'treble', 'activity']) this.cur[k] = this.cur[k] + (target[k] - this.cur[k]) * Math.min(1, dt * 1.2);
      const c = this.cur, bins = this.bins, t = this.at;
      /* speech: syllables at 3-5 Hz, phrases with pauses */
      this.syllable += dt * (3.6 + noise1(t * .7) * 1.2);
      const phrase = noise1(t * .23 + 9) > -.25 ? 1 : 0;
      this.speechGate += ((c.speech > .05 ? phrase : 0) - this.speechGate) * Math.min(1, dt * 8);
      const syl = Math.max(0, Math.sin(this.syllable * Math.PI * 2)) ** 1.6 * (.6 + .4 * noise1(t * 5 + 3)) * this.speechGate;
      /* beats */
      let kick = 0;
      if (target.beat && c.music > .3) { this.beatPhase += dt * target.beat / 60; if (this.beatPhase >= 1) { this.beatPhase -= 1; kick = 1; } kick = Math.max(kick, Math.max(0, 1 - this.beatPhase * 6)); }
      if (target.hits) { if (t - this.lastHit > .6 + this.rng() * 1.8) { this.lastHit = t; this.hitLevel = .7 + this.rng() * .3; } kick = Math.max(0, (this.hitLevel || 0) * (1 - (t - this.lastHit) * 5)); }
      const drift = .5 + .5 * noise1(t * .3);
      for (let i = 0; i < bins.length; i++) {
        const f = i / bins.length;                                        /* 0 = sub bass, 1 = top */
        const low = Math.exp(-f * 11) * (c.bass * (.45 + .55 * drift) + kick * .8 * c.music + kick * .5 * (target.hits ? 1 : 0));
        const voice = Math.exp(-((f - .18) ** 2) / .012) * syl * c.speech * .9 + Math.exp(-((f - .32) ** 2) / .02) * syl * c.speech * .5;
        const tone = c.music * (.25 + .2 * Math.sin(t * 2.1 + i * .9) + .15 * noise1(t * 1.3 + i * .37)) * Math.exp(-f * 2.2);
        const hiss = c.treble * Math.exp(-((f - .75) ** 2) / .08) * (.25 + .5 * Math.abs(noise1(t * 9 + i)) + kick * .3) + c.level * .04 * this.rng();
        const amb = c.level * .06 * (1 + noise1(t * .5 + i * .2));
        const v = clamp(low + voice + tone + hiss + amb, 0, 1);
        bins[i] += (v - bins[i]) * Math.min(1, dt * 22);
      }
      let sum = 0, peak = 0; for (const v of bins) { sum += v * v; if (v > peak) peak = v; }
      const rms = clamp(Math.sqrt(sum / bins.length) * 1.4, 0, 1);
      this.emit({ fft: bins, rms, peak, speech: c.speech * (this.speechGate * .7 + .3 * syl), activity: c.activity, music: c.music });
    }
  }

  /** Web Audio on the microphone (or any MediaStream handed in). */
  class MicrophoneProvider extends Provider {
    constructor(options = {}) { super(); this.name = 'microphone'; this.options = options; this.ctx = null; this.analyser = null; this.bins = null; this.wave = null; this.stream = options.stream || null; this.error = null; }
    async start() {
      try {
        const AC = root.AudioContext || root.webkitAudioContext; if (!AC) throw new Error('Web Audio unavailable');
        this.ctx = this.ctx || new AC();
        if (!this.stream) this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }, video: false });
        this.source = this.ctx.createMediaStreamSource(this.stream);
        this.analyser = this.ctx.createAnalyser(); this.analyser.fftSize = this.options.fftSize || 2048; this.analyser.smoothingTimeConstant = .2;
        this.source.connect(this.analyser);
        this.bins = new Uint8Array(this.analyser.frequencyBinCount); this.wave = new Float32Array(this.analyser.fftSize);
        if (this.ctx.state === 'suspended') await this.ctx.resume();
      } catch (e) { this.error = e; throw e; }
    }
    update() {
      if (!this.analyser) return;
      this.analyser.getByteFrequencyData(this.bins); this.analyser.getFloatTimeDomainData(this.wave);
      let sum = 0, peak = 0; for (const v of this.wave) { sum += v * v; const a = Math.abs(v); if (a > peak) peak = a; }
      const rms = Math.sqrt(sum / this.wave.length);
      this.emit({ fft: this.bins, rms: clamp(rms * 3.2, 0, 1), peak: clamp(peak * 1.2, 0, 1) });
    }
    stop() { try { this.source?.disconnect(); } catch (_) {} if (!this.options.stream) this.stream?.getTracks().forEach(t => t.stop()); this.stream = this.options.stream || null; this.analyser = null; }
  }

  /**
   * Telemetry from outside: a WebSocket of JSON frames ({fft:[...], rms, peak, speech, activity, music} or
   * a ready VisualizerState), or `feed(raw)` called by the host page. Frames older than `staleMs` read as
   * silence (the processor does that; this only keeps the last frame).
   */
  class ExternalProvider extends Provider {
    constructor(options = {}) { super(); this.name = 'external'; this.url = options.url || ''; this.socket = null; this.last = null; this.frames = 0; this.retry = 0; this.open = false; this.closed = false; }
    start() { if (this.url) this.connect(); }
    connect() {
      if (!this.url || this.closed) return;
      try { this.socket = new root.WebSocket(this.url); } catch (e) { this.schedule(); return; }
      this.socket.onopen = () => { this.open = true; this.retry = 0; };
      this.socket.onmessage = e => { try { const data = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; this.feed(data); } catch (_) {} };
      this.socket.onclose = () => { this.open = false; this.socket = null; this.schedule(); };
      this.socket.onerror = () => { try { this.socket?.close(); } catch (_) {} };
    }
    schedule() { if (this.closed) return; this.retry = Math.min(8, this.retry + 1); clearTimeout(this.timer); this.timer = setTimeout(() => this.connect(), 500 * 2 ** this.retry); }
    feed(raw) {
      if (!raw || typeof raw !== 'object') return;
      const fft = raw.fft ? (raw.fft instanceof Float32Array || raw.fft instanceof Uint8Array ? raw.fft : Float32Array.from(raw.fft)) : (raw.bands ? Float32Array.from(raw.bands) : null);
      this.last = { fft, rms: raw.rms, peak: raw.peak, speech: raw.speech ?? raw.speechActivity, activity: raw.activity ?? raw.stationActivity, music: raw.music };
      this.frames++; this.emit(this.last);
    }
    update() { /* frames arrive on their own; nothing to poll */ }
    stop() { this.closed = true; clearTimeout(this.timer); try { this.socket?.close(); } catch (_) {} this.socket = null; }
  }

  PineViz.Provider = Provider; PineViz.DemoProvider = DemoProvider; PineViz.MicrophoneProvider = MicrophoneProvider; PineViz.ExternalProvider = ExternalProvider;
  PineViz.DEMO_SCENES = SCENES.map(s => s.name);
})(typeof window !== 'undefined' ? window : globalThis);

/* ---- ui/Overlay.js ---- */
/* PineViz UI - DOM layers over the canvas: the radio overlay (station, program, host, now playing,
 * caller, time, signal), the development HUD (toggled with the backquote key; off in production) and
 * the visualizer selector (01..10, keys 1-0). Nothing here is drawn in WebGL.
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz;
  const { clamp } = PineViz.util;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  const CSS = `
.pineviz-ui{position:absolute;inset:0;pointer-events:none;font:13px/1.35 "Inter","Segoe UI",system-ui,sans-serif;color:#e6f0ff;letter-spacing:.01em}
.pineviz-ui *{box-sizing:border-box}
.pineviz-radio{position:absolute;inset:0;display:grid;grid-template-rows:auto 1fr auto;padding:clamp(14px,2.6vw,34px)}
.pineviz-radio .pv-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.pineviz-radio .pv-row.bottom{align-items:flex-end}
.pineviz-radio .pv-station{font-weight:700;font-size:clamp(14px,1.5vw,20px);letter-spacing:.14em;text-transform:uppercase;display:flex;align-items:center;gap:10px}
.pineviz-radio .pv-onair{display:inline-flex;align-items:center;gap:6px;font-size:11px;letter-spacing:.2em;padding:3px 8px;border:1px solid rgba(255,255,255,.35);border-radius:3px;text-transform:uppercase}
.pineviz-radio .pv-onair i{width:7px;height:7px;border-radius:50%;background:#ff3b3b;box-shadow:0 0 10px #ff3b3b;animation:pv-blink 1.6s ease-in-out infinite}
.pineviz-radio .pv-onair.off i{background:#5b6b86;box-shadow:none;animation:none}
.pineviz-radio .pv-time{font-variant-numeric:tabular-nums;font-size:clamp(13px,1.4vw,18px);opacity:.9}
.pineviz-radio .pv-block{display:grid;gap:2px;max-width:46%}
.pineviz-radio .pv-label{font-size:10px;letter-spacing:.22em;text-transform:uppercase;opacity:.55}
.pineviz-radio .pv-big{font-size:clamp(16px,2vw,26px);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pineviz-radio .pv-small{font-size:clamp(12px,1.2vw,15px);opacity:.8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pineviz-radio .pv-right{text-align:right;justify-items:end}
.pineviz-radio .pv-signal{display:inline-grid;grid-auto-flow:column;gap:3px;align-items:end;height:16px;margin-top:4px}
.pineviz-radio .pv-signal i{display:block;width:4px;background:rgba(255,255,255,.35);border-radius:1px;transition:height .12s}
.pineviz-radio .pv-note{position:absolute;left:50%;top:clamp(14px,2.6vw,34px);transform:translateX(-50%);padding:5px 12px;border-radius:14px;background:rgba(0,0,0,.45);font-size:12px;opacity:0;transition:opacity .3s}
.pineviz-radio .pv-note.show{opacity:1}
@keyframes pv-blink{0%,100%{opacity:1}50%{opacity:.35}}
.pineviz-selector{position:absolute;left:50%;bottom:10px;transform:translateX(-50%);display:flex;gap:4px;pointer-events:auto;padding:4px;border-radius:10px;background:rgba(3,8,22,.55);backdrop-filter:blur(6px);opacity:.25;transition:opacity .25s}
.pineviz-selector:hover,.pineviz-selector:focus-within,.pineviz-selector.show{opacity:1}
.pineviz-selector button{border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.04);color:#dbe9ff;border-radius:6px;padding:4px 7px;font:11px/1 system-ui,sans-serif;cursor:pointer;min-width:30px}
.pineviz-selector button[aria-pressed=true]{background:rgba(120,170,255,.28);border-color:rgba(140,190,255,.7)}
.pineviz-selector button:hover{border-color:rgba(255,255,255,.45)}
.pineviz-hud{position:absolute;right:10px;top:10px;width:264px;max-height:calc(100% - 20px);overflow:auto;pointer-events:auto;padding:10px 12px;border-radius:10px;background:rgba(2,6,18,.86);border:1px solid rgba(120,170,255,.25);font:11px/1.4 ui-monospace,Consolas,monospace;color:#cfe3ff;display:none}
.pineviz-hud.show{display:block}
.pineviz-hud h4{margin:0 0 6px;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#8fc4ff}
.pineviz-hud .pv-kv{display:grid;grid-template-columns:92px 1fr 42px;gap:4px 6px;align-items:center;margin:2px 0}
.pineviz-hud .pv-bar{height:6px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden}
.pineviz-hud .pv-bar i{display:block;height:100%;background:linear-gradient(90deg,#1f66ff,#49d8ff);width:0}
.pineviz-hud .pv-val{text-align:right;font-variant-numeric:tabular-nums}
.pineviz-hud label{display:grid;grid-template-columns:92px 1fr 42px;gap:4px 6px;align-items:center;margin:3px 0}
.pineviz-hud input[type=range]{width:100%;margin:0;accent-color:#49d8ff}
.pineviz-hud select,.pineviz-hud button{font:inherit;background:#0d1a33;color:inherit;border:1px solid rgba(120,170,255,.3);border-radius:4px;padding:2px 4px}
.pineviz-hud .pv-hudrow{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
.pineviz-hud .pv-stats{opacity:.8;white-space:pre-wrap}
`;
  function ensureStyle(doc) { if (doc.getElementById('pineviz-ui-style')) return; const s = doc.createElement('style'); s.id = 'pineviz-ui-style'; s.textContent = CSS; doc.head.appendChild(s); }

  /** The radio layer: placeholders a host fills with setInfo({...}); optional; the canvas works without it. */
  class RadioOverlay {
    constructor(container, info = {}) {
      ensureStyle(container.ownerDocument);
      this.root = el('div', 'pineviz-ui pineviz-radio'); container.appendChild(this.root);
      const top = el('div', 'pv-row'), bottom = el('div', 'pv-row bottom');
      this.station = el('div', 'pv-station'); this.onair = el('span', 'pv-onair'); this.onair.append(el('i'), document.createTextNode('On air'));
      this.stationName = el('span', '', 'Pine Box FM'); this.station.append(this.stationName, this.onair);
      this.time = el('div', 'pv-time', '');
      top.append(this.station, this.time);
      const left = el('div', 'pv-block'); this.programLabel = el('div', 'pv-label', 'Program'); this.program = el('div', 'pv-big', ''); this.host = el('div', 'pv-small', ''); this.nowLabel = el('div', 'pv-label', 'Now playing'); this.track = el('div', 'pv-small', ''); this.artist = el('div', 'pv-small', '');
      left.append(this.programLabel, this.program, this.host, this.nowLabel, this.track, this.artist);
      const right = el('div', 'pv-block pv-right'); this.callerLabel = el('div', 'pv-label', 'Caller'); this.caller = el('div', 'pv-small', ''); this.statusLabel = el('div', 'pv-label', 'Signal'); this.status = el('div', 'pv-small', '');
      this.signal = el('div', 'pv-signal'); for (let i = 0; i < 12; i++) this.signal.appendChild(el('i'));
      right.append(this.callerLabel, this.caller, this.statusLabel, this.status, this.signal);
      bottom.append(left, right);
      this.note = el('div', 'pv-note', '');
      this.root.append(top, el('div'), bottom, this.note);
      this.setInfo({ station: 'Pine Box FM', onAir: true, program: 'The Pine Box Hour', host: 'Dill and Skip', track: '', artist: '', caller: '', status: 'Live', ...info });
      this.clock = setInterval(() => this.tick(), 1000); this.tick();
    }
    setInfo(info) {
      if (info.station != null) this.stationName.textContent = info.station;
      if (info.onAir != null) this.onair.classList.toggle('off', !info.onAir);
      if (info.program != null) this.program.textContent = info.program;
      if (info.host != null) this.host.textContent = info.host;
      if (info.track != null) this.track.textContent = info.track; if (info.artist != null) this.artist.textContent = info.artist;
      this.nowLabel.style.display = this.track.textContent || this.artist.textContent ? '' : 'none';
      if (info.caller != null) { this.caller.textContent = info.caller; this.callerLabel.style.display = info.caller ? '' : 'none'; this.caller.style.display = info.caller ? '' : 'none'; }
      if (info.status != null) this.status.textContent = info.status;
      if (info.recording != null) this.status.textContent = (this.status.textContent.replace(/ \u00b7 REC$/, '')) + (info.recording ? ' \u00b7 REC' : '');
    }
    tick() { const d = new Date(); this.time.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }); }
    /** called every frame by whoever has the state */
    update(state) { const bars = this.signal.children; for (let i = 0; i < bars.length; i++) { const v = state.fft[Math.floor(i / bars.length * state.fft.length)] || 0; bars[i].style.height = Math.max(8, Math.round(v * 100)) + '%'; } }
    notify(text, ms = 2600) { this.note.textContent = text; this.note.classList.add('show'); clearTimeout(this.noteTimer); this.noteTimer = setTimeout(() => this.note.classList.remove('show'), ms); }
    show(on = true) { this.root.style.display = on ? '' : 'none'; }
    dispose() { clearInterval(this.clock); this.root.remove(); }
  }

  /** 01..10 buttons; keys 1-0 are the manager's. */
  class VisualizerSelector {
    constructor(container, manager, options = {}) {
      ensureStyle(container.ownerDocument);
      this.manager = manager; this.root = el('div', 'pineviz-selector' + (options.alwaysShow ? ' show' : '')); container.appendChild(this.root);
      this.buttons = new Map();
      for (const mode of manager.modes) { const b = el('button', '', String(mode.index).padStart(2, '0')); b.title = mode.name + (mode.blurb ? ' - ' + mode.blurb : ''); b.setAttribute('aria-label', mode.name); b.addEventListener('click', () => manager.set(mode.id)); this.root.appendChild(b); this.buttons.set(mode.id, b); }
      this.off = manager.on((kind, id) => { if (kind === 'mode') this.paint(id); });
      this.paint(manager.activeId);
    }
    paint(id) { for (const [key, b] of this.buttons) b.setAttribute('aria-pressed', String(key === id)); }
    dispose() { this.off(); this.root.remove(); }
  }

  /** The development HUD. Toggled with the backquote key (or options.key); `production: true` never builds it. */
  class DebugHUD {
    constructor(container, manager, options = {}) {
      this.manager = manager; this.options = options;
      if (options.production) { this.root = null; return; }
      ensureStyle(container.ownerDocument);
      this.root = el('div', 'pineviz-hud'); container.appendChild(this.root);
      this.root.appendChild(el('h4', '', 'PineViz'));
      this.lines = {};
      const kv = (key, label) => { const row = el('div', 'pv-kv'); const bar = el('div', 'pv-bar'); bar.appendChild(el('i')); const val = el('span', 'pv-val', '0'); row.append(el('span', '', label), bar, val); this.root.appendChild(row); this.lines[key] = { bar: bar.firstChild, val }; };
      this.fps = el('div', 'pv-stats', ''); this.root.appendChild(this.fps);
      for (const [k, l] of [['rms', 'rms'], ['peak', 'peak'], ['bass', 'bass'], ['mid', 'mid'], ['treble', 'treble'], ['beat', 'beat'], ['speechActivity', 'speech'], ['stationActivity', 'activity'], ['energy', 'energy']]) kv(k, l);
      const row = el('div', 'pv-hudrow');
      this.modeSel = el('select'); for (const m of manager.modes) { const o = el('option', '', String(m.index).padStart(2, '0') + ' ' + m.name); o.value = m.id; this.modeSel.appendChild(o); } this.modeSel.addEventListener('change', () => manager.set(this.modeSel.value));
      this.palSel = el('select'); for (const n of manager.palette.names) { const o = el('option', '', PineViz.PALETTES[n].name); o.value = n; this.palSel.appendChild(o); } this.palSel.value = manager.palette.name; this.palSel.addEventListener('change', () => manager.palette.set(this.palSel.value));
      this.qSel = el('select'); for (const q of PineViz.QUALITY_LADDER) { const o = el('option', '', q); o.value = q; this.qSel.appendChild(o); } this.qSel.value = manager.renderer.quality; this.qSel.addEventListener('change', () => manager.renderer.setQuality(this.qSel.value));
      this.transSel = el('select'); for (const t of Object.keys(PineViz.TRANSITIONS)) { const o = el('option', '', t); o.value = t; this.transSel.appendChild(o); } this.transSel.addEventListener('change', () => { manager.transition.mode = PineViz.TRANSITIONS[this.transSel.value]; });
      row.append(this.modeSel, this.palSel, this.qSel, this.transSel); this.root.appendChild(row);
      const prov = el('div', 'pv-hudrow');
      this.provSel = el('select'); for (const [v, l] of [['demo', 'demo'], ['microphone', 'microphone'], ['external', 'external']]) { const o = el('option', '', l); o.value = v; this.provSel.appendChild(o); }
      this.provSel.value = manager.provider?.name || 'demo';
      this.provSel.addEventListener('change', () => { const v = this.provSel.value; if (v === 'demo') manager.setProvider(new PineViz.DemoProvider()); else if (v === 'microphone') manager.setProvider(new PineViz.MicrophoneProvider()); else manager.setProvider(new PineViz.ExternalProvider({ url: options.externalUrl || '' })); this.sceneSel.style.display = v === 'demo' ? '' : 'none'; });
      this.sceneSel = el('select'); const auto = el('option', '', 'scenes: cycle'); auto.value = ''; this.sceneSel.appendChild(auto); for (const s of PineViz.DEMO_SCENES) { const o = el('option', '', s); o.value = s; this.sceneSel.appendChild(o); }
      this.sceneSel.addEventListener('change', () => { const p = manager.provider; if (p && p.name === 'demo') { if (this.sceneSel.value) p.setScene(this.sceneSel.value); else p.hold = null; } });
      const reset = el('button', '', 'reset preset'); reset.addEventListener('click', () => { if (manager.activeId) { manager.presets.reset(manager.activeId); this.buildSliders(); } });
      prov.append(this.provSel, this.sceneSel, reset); this.root.appendChild(prov);
      this.sliders = el('div'); this.root.appendChild(this.sliders);
      this.stats = el('div', 'pv-stats', ''); this.root.appendChild(this.stats);
      this.off = manager.on((kind, value, m) => { if (kind === 'frame') this.paint(value); if (kind === 'mode') { this.modeSel.value = value; this.buildSliders(); } if (kind === 'quality') this.qSel.value = value; });
      this.keyHandler = e => { if (e.key === (options.key || '`') && !e.ctrlKey && !e.metaKey) { e.preventDefault(); this.toggle(); } };
      (options.keyTarget || root).addEventListener('keydown', this.keyHandler);
      this.buildSliders(); this.shown = false; this.frameSkip = 0;
      if (options.show) this.toggle(true);
    }
    buildSliders() {
      if (!this.root) return; this.sliders.replaceChildren();
      const id = this.manager.activeId; if (!id) return;
      const values = this.manager.presets.get(id);
      const ranges = { intensity: [0, 2, .05], speed: [0, 3, .05], audioSensitivity: [0, 3, .05], smoothing: [.2, 3, .05], bloom: [0, 1.5, .05], opacity: [0, 1, .05], complexity: [.2, 2, .05], motionAmount: [0, 2, .05] };
      for (const [key, value] of Object.entries(values)) {
        if (typeof value !== 'number') continue;
        const [lo, hi, step] = ranges[key] || [0, Math.max(1, value * 3), value >= 10 ? 1 : .05];
        const label = el('label', '', key), input = el('input'), out = el('span', 'pv-val', String(value));
        input.type = 'range'; input.min = String(lo); input.max = String(hi); input.step = String(step); input.value = String(value);
        input.addEventListener('input', () => { const n = Number(input.value); out.textContent = String(n); this.manager.presets.set(id, key, n); });
        label.append(input, out); this.sliders.appendChild(label);
      }
    }
    toggle(force) { if (!this.root) return; this.shown = force == null ? !this.shown : !!force; this.root.classList.toggle('show', this.shown); }
    paint(state) {
      if (!this.shown || !this.root) return;
      if ((this.frameSkip = (this.frameSkip + 1) % 3) !== 0) return;
      const m = this.manager;
      for (const [k, line] of Object.entries(this.lines)) { const v = clamp(state[k] || 0, 0, 1); line.bar.style.width = (v * 100).toFixed(0) + '%'; line.val.textContent = v.toFixed(2); }
      this.fps.textContent = `fps ${m.fps.toFixed(0)}  mode ${m.activeId || '-'}  quality ${m.renderer.quality}  objects ${m.count()}  beats ${state.beatCount}`;
      const info = m.renderer.info; this.stats.textContent = `calls ${info.render.calls}  tris ${info.render.triangles}  points ${info.render.points}  lines ${info.render.lines}\ngeometries ${info.memory.geometries}  textures ${info.memory.textures}  programs ${(info.programs || []).length}` + (m.provider?.name === 'demo' && m.provider.sceneName ? `\nscene ${m.provider.sceneName}` : '');
    }
    dispose() { if (!this.root) return; this.off(); (this.options.keyTarget || root).removeEventListener('keydown', this.keyHandler); this.root.remove(); }
  }

  PineViz.RadioOverlay = RadioOverlay; PineViz.VisualizerSelector = VisualizerSelector; PineViz.DebugHUD = DebugHUD;
})(typeof window !== 'undefined' ? window : globalThis);

/* ---- visualizers/_shared.js ---- */
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

/* ---- visualizers/00-Classic.js ---- */
/* 00 CLASSIC - the Pine Box cloud. The background the PiP had from the start: a quiet drift of fine
 * points in the station's accent colour behind the Pine Box mark, gathering as voices speak, rippling
 * with the bands, breathing with the level. Ported from the panel's first particle cloud so the
 * "traditional" look is one mode among the ten, and the one a fresh desk starts on.
 *   rms -> brightness and gather  bass -> slow sway  mids -> ripple  treble -> static shimmer  beat -> a soft pulse
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { stageCamera, softSprite, Spring } = PineViz.shared;

  PineViz.register({
    id: 'classic', index: 0, name: 'Classic', blurb: 'the Pine Box cloud',
    defaults: { particles: 1800, size: 1, bloom: .2 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, points, material, sprite, backdrop, count = 0, pulse, lastBeat = 0;
      function build() {
        if (points) { scene.remove(points); points.geometry.dispose(); }
        count = Math.max(400, Math.round((ctx.preset.particles || 1800) * Math.max(.5, ctx.quality.scale)));
        const geo = new THREE.BufferGeometry(), seeds = new Float32Array(count * 4);
        for (let i = 0; i < count; i++) { seeds[i * 4] = (ctx.rng() - .5) * 16; seeds[i * 4 + 1] = ctx.rng() * Math.PI * 2; seeds[i * 4 + 2] = ctx.rng() * 2; seeds[i * 4 + 3] = ctx.rng() * Math.PI * 2; }
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3)); geo.setAttribute('seed', new THREE.BufferAttribute(seeds, 4));
        points = new THREE.Points(geo, material); points.frustumCulled = false; scene.add(points);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 48, 9);
          const p = ctx.palette;
          /* the panel's own gradient: the theme's button colour at the lower left, the surface everywhere else */
          backdrop = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.ShaderMaterial({ depthTest: false, depthWrite: false,
            uniforms: { uA: { value: new THREE.Color(p.bg) }, uB: { value: new THREE.Color(p.bg2) } },
            vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.999, 1.0); }',
            fragmentShader: 'uniform vec3 uA; uniform vec3 uB; varying vec2 vUv; void main(){ float d = distance(vUv, vec2(0.4, 0.35)); gl_FragColor = vec4(mix(uB, uA, smoothstep(0.0, 0.75, d)), 1.0); }' }));
          backdrop.frustumCulled = false; backdrop.renderOrder = -1000; scene.add(backdrop);
          sprite = softSprite(THREE, 32);
          material = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
            uniforms: { uTime: { value: 0 }, uLevel: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uPulse: { value: 0 }, uSize: { value: 1 }, uPixel: { value: 1 }, uColor: { value: new THREE.Color(p.primary) }, tSprite: { value: sprite } },
            vertexShader: `${GLSL_NOISE} attribute vec4 seed; uniform float uTime; uniform float uLevel; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uPulse; uniform float uSize; uniform float uPixel; varying float vA;
              void main(){ float t = uTime; float x = seed.x, a = seed.y, r = seed.z, ph = seed.w;
                float clump = 0.25 + 0.75 * (0.5 + 0.5 * sin(t * 0.19 + x * 0.38 + ph));
                float energy = uMid * (0.5 + 0.5 * sin(x * 0.9 + t * 1.3));
                float gather = 1.0 - uLevel * 0.38; float spread = clump * (1.0 - uLevel * 0.6);
                float ripple = sin(x * 1.8 - t * 5.5) * energy * 0.75 + sin(x * 0.75 + t * 3.0) * uLevel * 0.35;
                float statics = 0.012 + uTreble * 0.055;
                vec3 p = vec3(x * gather + sin(t * 0.13 + a) * 0.7 + sin(t * 31.0 + ph) * statics,
                              sin(x * 0.55 + t * 0.45) * 0.65 + ripple + cos(a + t * 0.12) * r * spread - 1.0 + sin(t * 37.0 + a) * statics + uBass * 0.4 * sin(x * 0.3 + t * 0.5),
                              sin(a + t * 0.09) * r * spread);
                p *= 1.0 + uPulse * 0.08;
                vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_Position = projectionMatrix * mv;
                vA = 0.65 + uLevel * 0.25; gl_PointSize = (2.6 + uLevel * 1.0 + uPulse * 0.8) * uSize * uPixel * (9.0 / max(1.0, -mv.z)); }`,
            fragmentShader: 'uniform sampler2D tSprite; uniform vec3 uColor; varying float vA; void main(){ float a = texture2D(tSprite, gl_PointCoord).a; gl_FragColor = vec4(uColor * 1.2, a * vA); }' });
          pulse = new Spring(40, 7, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) { material.uniforms.uColor.value.set(p.primary); backdrop.material.uniforms.uA.value.set(p.bg); backdrop.material.uniforms.uB.value.set(p.bg2); },
        presetChanged(key) { if (key === 'particles' || key === null) build(); },
        update(s, dt, t) {
          if (s.beat > .55 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; pulse.push(1.6 * s.beat); }
          pulse.step(dt);
          const u = material.uniforms; u.uTime.value = t * (.6 + .4 * clamp(s.energy * 1.5, 0, 1)); u.uLevel.value = clamp(s.rms * (ctx.preset.intensity || 1) * 1.3 + s.speechActivity * .3, 0, 1); u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uPulse.value = clamp(pulse.value, 0, 1.5); u.uSize.value = (ctx.preset.size || 1) * (ctx.preset.opacity ?? 1);
        },
        resize(w, h) { camera.fitAspect(w / h); material.uniforms.uPixel.value = Math.min(2, ctx.renderer.getPixelRatio()); },
        dispose() { points?.geometry.dispose(); material?.dispose(); sprite?.dispose(); backdrop?.geometry.dispose(); backdrop?.material.dispose(); points = null; },
        count() { return count; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);

/* ---- visualizers/01-SmoothWave.js ---- */
/* 01 SMOOTH WAVE - flowing ribbons. Four to eight translucent silk ribbons across a deep blue field,
 * each a strip mesh laid along its own drifting spline (noise-driven oscillators, never a plain sine),
 * at its own depth and speed for parallax. The centre stays open for the radio UI.
 *   rms -> amplitude  bass -> the long slow swell  mids -> ripples  treble -> edge light
 *   beat -> a width pulse through a spring  silence -> a slow, graceful idle
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { noise2, noise1, clamp, lerp, GLSL_NOISE } = PineViz.util, { Spring, gradientBackdrop, stageCamera, halfExtent } = PineViz.shared;

  PineViz.register({
    id: 'smooth-wave', index: 1, name: 'Smooth Wave', blurb: 'flowing ribbons',
    defaults: { ribbons: 8, width: .9, bloom: .9, intensity: 1.15 },   /* [viz-look] thinner silk, more of it, glowing */
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, ribbons = [], pulse, time = 0, extent = { x: 8, y: 4.5 };
      const SEGMENTS = 160;
      function ribbonMaterial(colorA, colorB) {
        return new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
          uniforms: { uA: { value: new THREE.Color(colorA) }, uB: { value: new THREE.Color(colorB) }, uWhite: { value: new THREE.Color(ctx.palette.accent) }, uOpacity: { value: .45 }, uEdge: { value: 0 }, uTime: { value: 0 }, uShift: { value: 0 } },
          vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
          fragmentShader: `${GLSL_NOISE} uniform vec3 uA; uniform vec3 uB; uniform vec3 uWhite; uniform float uOpacity; uniform float uEdge; uniform float uTime; uniform float uShift; varying vec2 vUv;
            void main(){ float across = abs(vUv.y - 0.5) * 2.0;
              float body = pow(1.0 - across, 1.15);                              /* silk: bright core, soft edges */
              float sheen = pow(1.0 - abs(across - 0.55) * 2.2, 6.0) * (0.5 + 0.5 * sin(vUv.x * 18.0 - uTime * 2.0 + uShift));
              float grain = pv_fbm(vec3(vUv.x * 9.0 + uShift, vUv.y * 3.0, uTime * 0.25)) * 0.5 + 0.5;
              vec3 c = mix(uA, uB, vUv.x * 0.6 + grain * 0.4) * body + uWhite * max(0.0, sheen) * (0.35 + uEdge);
              float ends = smoothstep(0.0, 0.08, vUv.x) * smoothstep(1.0, 0.92, vUv.x);
              gl_FragColor = vec4(c, (body * 0.85 + sheen * 0.4) * uOpacity * ends); }` });
      }
      function build() {
        const n = Math.max(3, Math.min(8, Math.round((ctx.preset.ribbons || 6) * (ctx.quality.scale < .5 ? .7 : 1))));
        for (const r of ribbons) { scene.remove(r.mesh); r.mesh.geometry.dispose(); r.mesh.material.dispose(); }
        ribbons = [];
        const p = ctx.palette;
        for (let i = 0; i < n; i++) {
          const geo = new THREE.PlaneGeometry(1, 1, SEGMENTS, 1);
          const mat = ribbonMaterial(i % 2 ? p.primary : p.secondary, i % 3 ? p.secondary : p.glow);
          const mesh = new THREE.Mesh(geo, mat); mesh.frustumCulled = false;
          const seed = ctx.rng() * 100, depth = -2 - i * 1.1 - ctx.rng() * .6;
          ribbons.push({ mesh, seed, depth, speed: .22 + ctx.rng() * .25, y: (ctx.rng() - .5) * 1.4, baseWidth: .38 + ctx.rng() * .5, phase: ctx.rng() * 9, tilt: (ctx.rng() - .5) * .3 });
          mesh.position.z = depth; mat.uniforms.uOpacity.value = .32 + .18 * (1 - i / n); mat.uniforms.uShift.value = seed;
          scene.add(mesh);
        }
      }
      /* the centreline of a ribbon: drifting oscillators and fbm, scaled by the audio terms */
      function centre(r, x, t, s) {
        const slow = noise2(x * .22 + r.seed, t * .11 + r.phase) * (1.1 + s.bass * 2.6);
        const swell = Math.sin(x * .55 + t * .35 * r.speed * 2 + noise1(t * .07 + r.seed) * 3) * (.35 + s.bass * 1.1);
        const ripple = noise2(x * 1.3 + r.seed * 2, t * .6) * (.12 + s.mid * .7);
        const fine = noise2(x * 2.4 + r.seed, t * 1.6) * (.01 + s.treble * .09);
        const amp = (.45 + s.rms * 1.1 + s.energy * .4) * (ctx.preset.intensity || 1) * (ctx.preset.motionAmount ?? 1) + .1;
        return r.y * extent.y * .55 + (slow + swell + ripple + fine) * amp * extent.y * .32 + x * r.tilt;
      }
      function layout(r, s, t) {
        const pos = r.mesh.geometry.attributes.position, span = extent.x * 1.35, scroll = t * r.speed * .35;
        const widthScale = (ctx.preset.width || 1) * (1 + pulse.value * .5) * (1 + s.bass * .35) * (1.0 + s.energy * .4) * extent.y * .3;
        const cols = SEGMENTS + 1;
        for (let i = 0; i < cols; i++) {
          const u = i / SEGMENTS, x = (u - .5) * 2 * span;
          const y = centre(r, x * .6 + scroll + r.seed, t, s);
          const dy = centre(r, (x + .06) * .6 + scroll + r.seed, t, s) - y;
          const nx = -dy, ny = 1, nl = Math.hypot(nx, ny);
          const w = widthScale * r.baseWidth * (.65 + .35 * noise2(u * 3 + r.seed, t * .4)) * (.55 + .45 * Math.sin(u * Math.PI));
          /* PlaneGeometry rows: first row is top (v=1), second row bottom */
          pos.setXYZ(i, x + nx / nl * w, y + ny / nl * w, 0);
          pos.setXYZ(i + cols, x - nx / nl * w, y - ny / nl * w, 0);
        }
        pos.needsUpdate = true;
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 40, 10);
          backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop);
          pulse = new Spring(70, 9, 0); build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(p); ribbons.forEach((r, i) => { r.mesh.material.uniforms.uA.value.set(i % 2 ? p.primary : p.secondary); r.mesh.material.uniforms.uB.value.set(i % 3 ? p.secondary : p.glow); r.mesh.material.uniforms.uWhite.value.set(p.accent); }); },
        presetChanged(key) { if (key === 'ribbons' || key === null) build(); },
        update(s, dt, t) {
          time = t; if (s.beat > .5 && pulse.lastBeat !== s.beatCount) { pulse.lastBeat = s.beatCount; pulse.push(2.2 * s.beat); }
          pulse.step(dt);
          backdrop.tick(s.energy, t);
          const idle = .35 + .65 * clamp(s.energy * 1.4, 0, 1);
          for (const r of ribbons) { layout(r, s, t * idle); const u = r.mesh.material.uniforms; u.uTime.value = t; u.uEdge.value = s.treble * 1.3 + s.beat * .4; u.uOpacity.value = (.6 + .3 * idle) * (ctx.preset.opacity ?? 1); }
        },
        resize(w, h) { camera.fitAspect(w / h); extent = halfExtent(camera, 10 - (-2)); },
        dispose() { for (const r of ribbons) { r.mesh.geometry.dispose(); r.mesh.material.dispose(); } ribbons = []; backdrop?.dispose(); },
        count() { return ribbons.length; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);

/* ---- visualizers/02-ParticleFlow.js ---- */
/* 02 PARTICLE FLOW - luminous matter. Tens of thousands of points (one GPU buffer, animated in the vertex
 * shader) ride a coherent flow: a great horizontal current whose centreline drifts, curl noise around it,
 * depth from near the camera into darkness, and small clusters that detach now and then and are drawn
 * back. Nothing is re-randomised per frame: each point has a seed and the field decides where it is.
 *   bass -> the current's large displacement  mids -> density and lift  treble -> micro-jitter and sparkle
 *   rms -> luminosity  beat -> a shockwave travelling down the stream
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, GLSL_NOISE } = PineViz.util, { gradientBackdrop, softSprite, stageCamera } = PineViz.shared;

  PineViz.register({
    id: 'particle-flow', index: 2, name: 'Particle Flow', blurb: 'swarming luminous matter',
    defaults: { particles: 36000, size: .85, bloom: .9 },   /* [viz-look] a swarm of fine sparks, not discs */
    create(ctx) {
      const { THREE } = ctx; let scene, camera, backdrop, points, material, sprite, count = 0, shock = { at: -10, strength: 0 }, lastBeat = 0;
      function build() {
        if (points) { scene.remove(points); points.geometry.dispose(); }
        count = Math.max(2000, Math.round((ctx.preset.particles || 24000) * ctx.quality.scale));
        const geo = new THREE.BufferGeometry();
        const seeds = new Float32Array(count * 4);
        for (let i = 0; i < count; i++) { seeds[i * 4] = ctx.rng(); seeds[i * 4 + 1] = ctx.rng(); seeds[i * 4 + 2] = ctx.rng(); seeds[i * 4 + 3] = ctx.rng(); }
        geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
        geo.setAttribute('seed', new THREE.BufferAttribute(seeds, 4));
        points = new THREE.Points(geo, material); points.frustumCulled = false; scene.add(points);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 50, 12);
          backdrop = gradientBackdrop(THREE, ctx.palette); scene.add(backdrop);
          sprite = softSprite(THREE, 64);
          const p = ctx.palette;
          material = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
            uniforms: { uTime: { value: 0 }, uBass: { value: 0 }, uMid: { value: 0 }, uTreble: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uShockAt: { value: -10 }, uShock: { value: 0 }, uSize: { value: 1 }, uAspect: { value: 1.78 }, uPixel: { value: 1 },
              uA: { value: new THREE.Color(p.secondary) }, uB: { value: new THREE.Color(p.primary) }, uC: { value: new THREE.Color(p.accent) }, uV: { value: new THREE.Color(ctx.palette.name === 'Monochrome' ? p.secondary : '#b36bff') }, tSprite: { value: sprite } },
            vertexShader: `${GLSL_NOISE} attribute vec4 seed; uniform float uTime; uniform float uBass; uniform float uMid; uniform float uTreble; uniform float uRms; uniform float uEnergy; uniform float uShockAt; uniform float uShock; uniform float uSize; uniform float uAspect; uniform float uPixel;
              varying float vDepth; varying float vHeat; varying float vCluster;
              void main(){
                float idle = 0.3 + 0.7 * uEnergy;
                float t = uTime * (0.35 + 0.65 * idle);
                /* along the current: each point has a station on x that scrolls; wraps across the stage */
                float span = 11.0 * uAspect;
                float x = mod(seed.x * span + t * (0.6 + seed.w * 1.2) * (0.5 + uRms), span) - span * 0.5;
                /* the centreline drifts with slow noise and the bass; the stream is a band around it */
                float centre = pv_snoise(vec3(x * 0.16, t * 0.09, 3.0)) * (1.2 + uBass * 2.4) + sin(x * 0.35 + t * 0.3) * 0.6;
                float band = (seed.y - 0.5) * (1.4 + uMid * 2.2);
                vec3 p = vec3(x, centre + band, (seed.z - 0.5) * 9.0);
                /* curl of the field moves the matter coherently; treble adds the fine shimmer */
                vec3 q = p * 0.35 + vec3(0.0, 0.0, t * 0.25);
                vec3 curl = vec3(pv_snoise(q + vec3(0.0, 1.7, 0.0)) - pv_snoise(q - vec3(0.0, 1.7, 0.0)), pv_snoise(q + vec3(2.3, 0.0, 0.0)) - pv_snoise(q - vec3(2.3, 0.0, 0.0)), 0.0) * 0.5;
                p += curl * (0.5 + uMid * 1.2 + uBass * 0.6) * idle;
                p += vec3(pv_snoise(vec3(seed.xy * 40.0, t * 6.0)), pv_snoise(vec3(seed.yz * 40.0, t * 6.0 + 9.0)), 0.0) * uTreble * 0.35;
                /* clusters: some points belong to a cluster that detaches for a while, then is drawn back */
                float cl = step(0.86, seed.w);
                float detach = smoothstep(0.2, 0.8, pv_snoise(vec3(floor(seed.w * 97.0), t * 0.07, 1.0)) * 0.5 + 0.5);
                vec3 away = vec3(0.0, 2.6 * (seed.y - 0.5) * 2.0, 1.5) * detach * cl;
                p += away;
                /* the beat's shockwave: a ring in x sweeping down the stream from the centre */
                float ring = abs(abs(x) - (uTime - uShockAt) * 9.0);
                float hit = uShock * exp(-ring * 1.2) * exp(-(uTime - uShockAt) * 1.4);
                p.y += hit * 1.6 * sign(band + 0.001);
                vHeat = clamp(uRms * 0.8 + hit + detach * cl * 0.5, 0.0, 1.0);
                vCluster = cl;
                vec4 mv = modelViewMatrix * vec4(p, 1.0);
                vDepth = clamp(1.0 - (-mv.z - 3.0) / 18.0, 0.0, 1.0);
                gl_Position = projectionMatrix * mv;
                float sz = (0.8 + seed.w * 1.6) * uSize * uPixel * (1.0 + uTreble * 0.6 + hit) * (34.0 / max(1.0, -mv.z));
                gl_PointSize = clamp(sz, 1.0, 26.0);
              }`,
            fragmentShader: `uniform sampler2D tSprite; uniform vec3 uA; uniform vec3 uB; uniform vec3 uC; uniform vec3 uV; uniform float uRms; uniform float uEnergy; varying float vDepth; varying float vHeat; varying float vCluster;
              void main(){ float a = texture2D(tSprite, gl_PointCoord).a;
                vec3 c = mix(uB, uA, vDepth);
                c = mix(c, uV, vCluster * 0.7 + vHeat * 0.35);
                c = mix(c, uC, pow(vHeat, 2.0) * 0.6);
                float lum = (0.45 + 0.55 * uRms + 0.3 * uEnergy) * (0.35 + 0.65 * vDepth);
                gl_FragColor = vec4(c * lum * 1.6, a * lum); }` });
          build();
        },
        activate() {}, deactivate() {},
        palette(p) { backdrop.setPalette(p); const u = material.uniforms; u.uA.value.set(p.secondary); u.uB.value.set(p.primary); u.uC.value.set(p.accent); u.uV.value.set(ctx.palette.name === 'Monochrome' ? p.secondary : '#b36bff'); },
        presetChanged(key) { if (key === 'particles' || key === null) build(); },
        update(s, dt, t) {
          const u = material.uniforms; u.uTime.value = t; u.uBass.value = s.bass; u.uMid.value = s.mid; u.uTreble.value = s.treble; u.uRms.value = s.rms * (ctx.preset.intensity || 1); u.uEnergy.value = s.energy;
          if (s.beat > .55 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; u.uShockAt.value = t; u.uShock.value = clamp(s.beat * 1.2, 0, 1.4); }
          u.uSize.value = (ctx.preset.size || 1) * (ctx.preset.opacity ?? 1);
          backdrop.tick(s.energy, t);
        },
        resize(w, h) { camera.fitAspect(w / h); material.uniforms.uAspect.value = w / h; material.uniforms.uPixel.value = Math.min(2, ctx.renderer.getPixelRatio()); },
        dispose() { points?.geometry.dispose(); material?.dispose(); sprite?.dispose(); backdrop?.dispose(); points = null; },
        count() { return count; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);

/* ---- visualizers/03-LineSpectrum.js ---- */
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
    defaults: { lines: 40, bloom: .75, indicators: 28 },
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

/* ---- visualizers/04-GeometricSpace.js ---- */
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

/* ---- visualizers/05-SpeedLines.js ---- */
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
    defaults: { streaks: 640, trail: .84, bloom: .8 },
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

/* ---- visualizers/06-AnimeInk.js ---- */
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

/* ---- visualizers/07-AudioBars.js ---- */
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
    defaults: { columns: 80, bloom: .85, height: 1 },
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

/* ---- visualizers/08-LiquidGlass.js ---- */
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
    defaults: { droplets: 22, bloom: .75, thickness: 1 },
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
          shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\n' + displace + '\n').replace('#include <begin_vertex>', `vec3 transformed = pv_displace(position);
            vec3 dx = pv_displace(position + vec3(0.08, 0.0, 0.0)) - transformed; vec3 dy = pv_displace(position + vec3(0.0, 0.08, 0.0)) - transformed;`)
            .replace('#include <beginnormal_vertex>', 'vec3 objectNormal = normal;')
            .replace('#include <defaultnormal_vertex>', `vec3 pvN = normalize(cross(dx, dy)); vec3 transformedNormal = normalMatrix * pvN;
#ifdef FLIP_SIDED
            transformedNormal = -transformedNormal;
#endif
`);
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
          glow.material.onBeforeCompile = shader => { Object.assign(shader.uniforms, uniforms); shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\n' + displace + '\n').replace('#include <begin_vertex>', 'vec3 transformed = pv_displace(position); transformed.z -= 0.4;'); };
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

/* ---- visualizers/09-RetroGrid.js ---- */
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

/* ---- visualizers/10-ShapeBurst.js ---- */
/* 10 REACTIVE SHAPE BURST - playful symbols. Hundreds of abstract glyphs (an original set: circle, diamond,
 * cross, ring, triangle, star, hexagon, a bracket glyph; SDFs drawn on instanced quads) ride four
 * invisible drifting splines at different depths, spinning and breathing. A hard beat throws a burst:
 * dozens leave the stream with their own velocity, slow, and are drawn back by springs. Faint trails
 * come from persistence (the veil), as in Speed Lines.
 *   bass -> size and path deformation  mids -> travel speed  treble -> the small ones  rms -> glow  beat -> the burst
 */
(function (root) {
  'use strict';
  const PineViz = root.PineViz, { clamp, noise1, GLSL_NOISE } = PineViz.util, { stageCamera, halfExtent } = PineViz.shared;

  PineViz.register({
    id: 'shape-burst', index: 10, name: 'Shape Burst', blurb: 'reactive floating symbols', persist: true,
    defaults: { symbols: 480, trail: .6, bloom: .8 },
    create(ctx) {
      const { THREE } = ctx; let scene, camera, veil, veilMat, mesh, material, n = 0, items = [], paths = [], extent = { x: 8, y: 4.5 }, lastBeat = 0, dummy, burstLeft = 0, glyphAttr, sizeAttr, heatAttr;
      const KINDS = 8;
      function buildPaths() {
        paths = [];
        for (let i = 0; i < 4; i++) paths.push({ y: (i - 1.5) * .5, z: -2 - i * 2.2, seed: ctx.rng() * 30, amp: .5 + ctx.rng() * .8, speed: .25 + ctx.rng() * .3 });
      }
      function pointOn(path, u, t, s) {
        const x = (u - .5) * 2 * extent.x * 1.25;
        const y = path.y * extent.y + Math.sin(x * .33 + t * .22 + path.seed) * path.amp * extent.y * .32 * (1 + s.bass * .9) + noise1(x * .2 + t * .1 + path.seed) * extent.y * .14;
        return [x, y, path.z];
      }
      function build() {
        if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
        n = Math.max(80, Math.round((ctx.preset.symbols || 360) * ctx.quality.scale));
        const geo = new THREE.InstancedBufferGeometry(); const base = new THREE.PlaneGeometry(1, 1); geo.index = base.index; geo.attributes.position = base.attributes.position; geo.attributes.uv = base.attributes.uv;
        glyphAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1); sizeAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1); heatAttr = new THREE.InstancedBufferAttribute(new Float32Array(n), 1);
        glyphAttr.setUsage(THREE.DynamicDrawUsage); heatAttr.setUsage(THREE.DynamicDrawUsage);
        geo.setAttribute('glyph', glyphAttr); geo.setAttribute('gsize', sizeAttr); geo.setAttribute('heat', heatAttr); geo.instanceCount = n;
        items = [];
        for (let i = 0; i < n; i++) {
          const small = ctx.rng() < .45;
          items.push({ path: i % 4, u: ctx.rng(), speed: .02 + ctx.rng() * .04, spin: (ctx.rng() - .5) * 2.4, angle: ctx.rng() * 6.3, size: small ? .12 + ctx.rng() * .14 : .25 + ctx.rng() * .4, small, kind: Math.floor(ctx.rng() * KINDS), seed: ctx.rng() * 10, burst: 0, vx: 0, vy: 0, vz: 0, ox: 0, oy: 0, oz: 0 });
          glyphAttr.setX(i, items[i].kind); sizeAttr.setX(i, items[i].size);
        }
        mesh = new THREE.Mesh(geo, material); mesh.frustumCulled = false; scene.add(mesh); dummy = new THREE.Object3D();
        mesh.instanceMatrix = new THREE.InstancedBufferAttribute(new Float32Array(n * 16), 16); mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage); geo.setAttribute('instanceMatrix', mesh.instanceMatrix);
      }
      return {
        init() {
          scene = new THREE.Scene(); camera = stageCamera(THREE, ctx.size.aspect, 42, 10);
          const p = ctx.palette;
          veilMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(p.bg), transparent: true, opacity: .4, depthTest: false, depthWrite: false });
          veil = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), veilMat); veil.frustumCulled = false; veil.renderOrder = -10;
          veil.onBeforeRender = () => {}; const veilScene = veil; veilScene.material.onBeforeCompile = shader => { shader.vertexShader = shader.vertexShader.replace('#include <project_vertex>', 'gl_Position = vec4(position.xy, 0.9999, 1.0);'); }; veilMat.customProgramCacheKey = () => 'pineviz-veil';
          scene.add(veil);
          material = new THREE.ShaderMaterial({ transparent: true, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
            uniforms: { uTime: { value: 0 }, uRms: { value: 0 }, uEnergy: { value: 0 }, uA: { value: new THREE.Color(p.secondary) }, uB: { value: new THREE.Color(p.primary) }, uC: { value: new THREE.Color(p.accent) }, uV: { value: new THREE.Color(ctx.palette.name === 'Monochrome' ? p.glow : '#b86bff') } },
            vertexShader: `attribute mat4 instanceMatrix; attribute float glyph; attribute float gsize; attribute float heat; varying vec2 vUv; varying float vGlyph; varying float vHeat; varying float vDepth;
              void main(){ vUv = uv; vGlyph = glyph; vHeat = heat; vec4 mv = modelViewMatrix * instanceMatrix * vec4(position * gsize, 1.0); vDepth = clamp(1.0 - (-mv.z - 4.0) / 14.0, 0.0, 1.0); gl_Position = projectionMatrix * mv; }`,
            fragmentShader: `uniform float uRms; uniform float uEnergy; uniform vec3 uA; uniform vec3 uB; uniform vec3 uC; uniform vec3 uV; varying vec2 vUv; varying float vGlyph; varying float vHeat; varying float vDepth;
              float sdCircle(vec2 p, float r){ return length(p) - r; }
              float sdBox(vec2 p, vec2 b){ vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
              float sdTri(vec2 p, float r){ const float k = sqrt(3.0); p.x = abs(p.x) - r; p.y = p.y + r / k; if (p.x + k * p.y > 0.0) p = vec2(p.x - k * p.y, -k * p.x - p.y) / 2.0; p.x -= clamp(p.x, -2.0 * r, 0.0); return -length(p) * sign(p.y); }
              float sdHex(vec2 p, float r){ const vec3 k = vec3(-0.866025404, 0.5, 0.577350269); p = abs(p); p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy; p -= vec2(clamp(p.x, -k.z * r, k.z * r), r); return length(p) * sign(p.y); }
              float sdStar(vec2 p, float r){ const float an = 0.628318; const float en = 0.9; vec2 acs = vec2(cos(an), sin(an)); vec2 ecs = vec2(cos(en), sin(en)); float bn = mod(atan(p.x, p.y), 2.0 * an) - an; p = length(p) * vec2(cos(bn), abs(sin(bn))); p -= r * acs; p += ecs * clamp(-dot(p, ecs), 0.0, r * acs.y / ecs.y); return length(p) * sign(p.x); }
              void main(){ vec2 p = vUv - 0.5; int g = int(vGlyph + 0.5); float d = 1.0; float w = 0.055;
                if (g == 0) d = abs(sdCircle(p, 0.3)) - w;                                                  /* ring */
                else if (g == 1) d = abs(sdBox(vec2(p.x + p.y, p.x - p.y) * 0.7071, vec2(0.26))) - w;        /* diamond outline */
                else if (g == 2) d = min(sdBox(p, vec2(0.34, w)), sdBox(p, vec2(w, 0.34)));                   /* cross */
                else if (g == 3) d = sdCircle(p, 0.24);                                                       /* filled dot */
                else if (g == 4) d = abs(sdTri(p * 1.1, 0.26)) - w;                                           /* triangle */
                else if (g == 5) d = sdStar(p * 1.2, 0.3);                                                    /* star */
                else if (g == 6) d = abs(sdHex(p, 0.28)) - w;                                                 /* hexagon */
                else d = min(abs(sdBox(p + vec2(0.18, 0.0), vec2(0.06, 0.3))) - w * 0.6, abs(sdBox(p - vec2(0.18, 0.0), vec2(0.06, 0.3))) - w * 0.6);   /* bracket glyph */
                float edge = fwidth(d) * 1.2; float a = 1.0 - smoothstep(0.0, edge, d);
                float glowA = exp(-max(d, 0.0) * 14.0) * 0.35;
                vec3 c = mix(uB, uA, vDepth * 0.7); c = mix(c, uV, step(4.5, vGlyph) * 0.5); c = mix(c, uC, vHeat * 0.7);
                float lum = (0.35 + 0.4 * uRms + 0.25 * uEnergy + vHeat * 0.5) * (0.35 + 0.65 * vDepth);
                gl_FragColor = vec4(c * lum, (a + glowA) * lum); }` });
          buildPaths(); build();
        },
        activate() {}, deactivate() {},
        palette(p) { veilMat.color.set(p.bg); const u = material.uniforms; u.uA.value.set(p.secondary); u.uB.value.set(p.primary); u.uC.value.set(p.accent); u.uV.value.set(p.name === 'Monochrome' ? p.glow : '#b86bff'); },
        presetChanged(key) { if (key === 'symbols' || key === null) build(); },
        update(s, dt, t) {
          const idle = .25 + .75 * clamp(s.energy * 1.5, 0, 1), m = (ctx.preset.motionAmount ?? 1);
          let burst = false;
          if (s.beat > .5 && s.beatCount !== lastBeat) { lastBeat = s.beatCount; if (s.beat > .78 && burstLeft <= 0) { burst = true; burstLeft = .6; } }
          burstLeft -= dt;
          let thrown = 0;
          for (let i = 0; i < n; i++) {
            const it = items[i], path = paths[it.path];
            it.u = (it.u + dt * it.speed * (.4 + s.mid * 2.2 + .3 * idle) * m) % 1;
            const [px, py, pz] = pointOn(path, it.u, t * idle, s);
            if (burst && thrown < 40 && ctx.rng() < .35) { thrown++; it.burst = 1; const a = ctx.rng() * 6.283, sp = 3 + ctx.rng() * 5; it.vx = Math.cos(a) * sp; it.vy = Math.sin(a) * sp; it.vz = (ctx.rng() - .5) * 4; }
            if (it.burst > 0) {
              /* thrown: drag slows it; a spring draws it home; the burst ends when it is back */
              it.vx -= it.ox * 6 * dt + it.vx * 1.6 * dt; it.vy -= it.oy * 6 * dt + it.vy * 1.6 * dt; it.vz -= it.oz * 6 * dt + it.vz * 1.6 * dt;
              it.ox += it.vx * dt; it.oy += it.vy * dt; it.oz += it.vz * dt;
              it.burst = Math.max(0, it.burst - dt * .25); if (Math.hypot(it.ox, it.oy, it.oz) < .05 && Math.hypot(it.vx, it.vy) < .2) { it.burst = 0; it.ox = it.oy = it.oz = 0; }
            }
            it.angle += dt * it.spin * (.5 + s.mid + it.burst * 2) * m;
            const grow = 1 + s.bass * (it.small ? .2 : .55) + it.burst * .4 + Math.sin(t * 1.3 + it.seed) * .08;
            const show = it.small ? clamp((s.treble - .08) * 4 + it.burst, 0, 1) : 1;
            dummy.position.set(px + it.ox, py + it.oy, pz + it.oz); dummy.rotation.set(0, 0, it.angle); dummy.scale.setScalar(grow * show * (ctx.preset.intensity || 1)); dummy.updateMatrix();
            dummy.matrix.toArray(mesh.instanceMatrix.array, i * 16);
            heatAttr.setX(i, clamp(it.burst * 1.2 + s.beat * .4, 0, 1));
          }
          mesh.instanceMatrix.needsUpdate = true; heatAttr.needsUpdate = true;
          material.uniforms.uTime.value = t; material.uniforms.uRms.value = s.rms; material.uniforms.uEnergy.value = s.energy;
          veilMat.opacity = clamp(1 - (ctx.preset.trail ?? .55), .08, .9);
        },
        resize(w, h) { camera.fitAspect(w / h); extent = halfExtent(camera, 10 + 4); },
        dispose() { mesh?.geometry.dispose(); material?.dispose(); veil?.geometry.dispose(); veilMat?.dispose(); mesh = null; },
        count() { return n; },
        get scene() { return scene; }, get camera() { return camera; }
      };
    }
  });
})(typeof window !== 'undefined' ? window : globalThis);
