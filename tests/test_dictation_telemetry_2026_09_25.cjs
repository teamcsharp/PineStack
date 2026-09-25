const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sources = [
  '../desktop/renderer/talk-dot.js',
  '../app/src/main/assets/pine-views/talk-dot.js',
];

function harness(file, ear) {
  const elements = new Map();
  const frames = new Map();
  let nextFrame = 0;
  let now = 0;
  let inputPeak = 0;
  let frequency = 0;
  const overlays = [];
  const metrics = Array.from({length: 24}, (_, i) => i === 0 ? 0.4 : 0);
  let nativeMetrics = {
    rms: 0.125, peak: 0.5, speech_probability: 0.72,
    vad_state: 'speech', silence_elapsed_ms: 120,
    endpoint_timeout_ms: 4200, remaining_ms: 4080,
    threshold: 0.06, bands: metrics,
  };

  function element() {
    const attrs = {};
    const node = {
      style: {}, hidden: false, children: [],
      classList: {
        values: new Set(),
        toggle(name, on) {
          this.lastToggle = [name, on];
          if (on) this.values.add(name);
          else this.values.delete(name);
        },
        contains(name) { return this.values.has(name); },
      },
      setAttribute(name, value) { attrs[name] = value; },
      addEventListener() {},
      appendChild(child) {
        this.children.push(child);
        if (child.id) elements.set(child.id, child);
        return child;
      },
      remove() {},
      querySelector(selector) {
        if (selector === '#pineTalkFx') return element();
        if (selector === '[data-talk-spectrum]') return this.spectrum;
        if (selector === '[data-talk-phase]') return this.phase;
        const match = selector.match(/^\[data-talk-metric="([^"]+)"\]$/);
        return match ? this.metric[match[1]] : null;
      },
      querySelectorAll(selector) {
        if (selector === '.pine-talk-band') return this.spectrum.children;
        if (selector === '[data-talk-metric]') return Object.values(this.metric);
        return [];
      },
    };
    Object.defineProperty(node, 'innerHTML', {
      set(markup) {
        if (markup.includes('<i>')) {
          this.firstElementChild = {style: {}};
          this.lastElementChild = {style: {}};
          return;
        }
        if (!markup.includes('data-talk-phase')) return;
        this.phase = {textContent: ''};
        this.metric = {};
        for (const name of ['speech_probability', 'rms', 'peak', 'vad_state',
          'silence_elapsed_ms', 'endpoint_timeout_ms', 'remaining_ms', 'threshold']) {
          this.metric[name] = {textContent: ''};
        }
        this.spectrum = {children: [], appendChild: child => this.spectrum.children.push(child)};
      },
    });
    return node;
  }

  const document = {
    body: {appendChild(node) { if (node.id) elements.set(node.id, node); }},
    createElement: element,
    getElementById: id => elements.get(id),
    querySelectorAll: () => [],
    addEventListener() {},
  };
  const stream = {
    getAudioTracks: () => [{label: 'Test mic'}],
    getTracks: () => [{stop() {}}],
  };
  class AudioContext {
    constructor() { this.sampleRate = 48000; this.destination = {}; }
    createMediaStreamSource() { return {connect() {}}; }
    createAnalyser() {
      return {
        fftSize: 512, frequencyBinCount: 256,
        getByteTimeDomainData(data) {
          data.fill(128);
          data[0] = 128 + Math.round(inputPeak * 128);
        },
        getByteFrequencyData(data) { data.fill(0); data[0] = frequency; },
      };
    }
    createScriptProcessor() { return {connect() {}, disconnect() {}}; }
    createGain() { return {gain: {value: 1}, connect() {}}; }
  }
  const bridge = {
    micStart: async () => ({ok: true}),
    micStop: () => new Promise(() => {}),
    micLevel: () => 0.18,
    talkOverlay: value => overlays.push(value),
  };
  if (ear === 'native') bridge.micMetrics = () => nativeMetrics;
  const root = {
    document, pineDesktop: ear === 'web' ? null : bridge,
    AudioContext, performance: {now: () => now},
    navigator: {mediaDevices: {getUserMedia: async () => stream}},
    PineDuck: {hold() {}, release() {}},
    setInterval() { return 1; }, clearInterval() {},
    setTimeout() { return 1; }, clearTimeout() {},
    addEventListener() {},
  };
  const source = fs.readFileSync(path.join(__dirname, file), 'utf8');
  vm.runInNewContext(source, {
    window: root, document, navigator: root.navigator, performance: root.performance,
    requestAnimationFrame(fn) { frames.set(++nextFrame, fn); return nextFrame; },
    cancelAnimationFrame(id) { frames.delete(id); },
    setTimeout: root.setTimeout, clearTimeout: root.clearTimeout,
    Uint8Array, Float32Array, ArrayBuffer, DataView, Promise,
  }, {filename: file});
  function tick(at) {
    now = at;
    const [id, callback] = [...frames].at(-1);
    frames.delete(id);
    callback();
  }
  return {
    dot: root.PineTalkDot,
    bridge, overlays, tick,
    telemetry: () => elements.get('pineTalkTelemetry'),
    metric: name => elements.get('pineTalkTelemetry').metric[name].textContent,
    setNativeMetrics: value => { nativeMetrics = value; },
    setWebSignal: (peak, band) => { inputPeak = peak; frequency = band; },
  };
}

(async () => {
  for (const file of sources) {
    const native = harness(file, 'native');
    await native.dot.listen();
    assert.equal(native.telemetry().hidden, false);
    assert.equal(native.telemetry().phase.textContent, 'Capturing');
    native.tick(500);
    assert.equal(native.metric('speech_probability'), '72%');
    assert.equal(native.metric('rms'), '0.125');
    assert.equal(native.metric('peak'), '0.500');
    assert.equal(native.metric('vad_state'), 'speech');
    assert.equal(native.metric('silence_elapsed_ms'), '120 ms');
    assert.equal(native.metric('endpoint_timeout_ms'), '4200 ms');
    assert.equal(native.metric('remaining_ms'), '4080 ms');
    assert.equal(native.metric('threshold'), '0.060');
    const first = native.telemetry().spectrum.children[0];
    assert.equal(first.firstElementChild.style.height, '40%');
    assert.equal(first.lastElementChild.style.bottom, '40%');
    native.setNativeMetrics({
      rms: 0, peak: 0, speech_probability: 0, vad_state: 'silence',
      silence_elapsed_ms: 500, endpoint_timeout_ms: 4200,
      remaining_ms: 3700, threshold: 0.06, bands: Array(24).fill(0.1),
    });
    native.tick(600);
    assert.equal(first.lastElementChild.style.bottom, '40%', 'peak holds briefly');
    native.tick(900);
    assert.ok(parseFloat(first.lastElementChild.style.bottom) < 40, 'peak falls');
    native.dot.finish();
    assert.equal(native.telemetry().phase.textContent, 'Transcribing');
    assert.equal(native.telemetry().classList.lastToggle[1], false);
    assert.equal(native.telemetry().classList.contains('transcribing'), true);

    const fallback = harness(file, 'fallback');
    await fallback.dot.listen();
    fallback.tick(500);
    assert.equal(fallback.metric('peak'), '0.180');
    assert.equal(fallback.metric('rms'), '--');
    assert.equal(fallback.metric('speech_probability'), '--');
    assert.equal(fallback.telemetry().classList.lastToggle[1], false);
    assert.equal(fallback.overlays.at(-1).level, 0.18);

    const web = harness(file, 'web');
    await web.dot.listen();
    web.tick(100);
    assert.equal(web.metric('vad_state'), 'Calibrating');
    web.setWebSignal(0.5, 255);
    web.tick(500);
    assert.equal(web.metric('rms'), '0.022');
    assert.equal(web.metric('peak'), '0.500');
    assert.equal(web.metric('speech_probability'), '100% est.');
    assert.equal(web.metric('vad_state'), 'Speech');
    assert.equal(web.metric('threshold'), '0.012');
    assert.equal(web.metric('endpoint_timeout_ms'), '4200 ms');
    assert.equal(web.telemetry().classList.lastToggle[1], true);
    assert.equal(web.telemetry().spectrum.children[0].firstElementChild.style.height, '100%');
    web.setWebSignal(0, 0);
    web.tick(600);
    web.tick(900);
    assert.equal(web.metric('vad_state'), 'Silence');
    assert.equal(web.metric('silence_elapsed_ms'), '300 ms');
    assert.equal(web.metric('remaining_ms'), '3900 ms');
    web.dot.cancel();
    assert.equal(web.telemetry().hidden, true);
  }
  console.log('dictation telemetry: native, fallback, web, peak decay, phases passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
