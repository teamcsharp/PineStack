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
    PineViz.registry.sort((a, b) => (a.index || 99) - (b.index || 99));
    return def;
  };
  PineViz.modes = () => PineViz.registry.map(d => ({ id: d.id, index: d.index, name: d.name, blurb: d.blurb }));
})(typeof window !== 'undefined' ? window : globalThis);
