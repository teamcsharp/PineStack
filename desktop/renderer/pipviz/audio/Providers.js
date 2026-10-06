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
