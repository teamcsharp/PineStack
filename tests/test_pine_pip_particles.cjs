// Run the injected particle panel with deterministic seeds and an existing analyser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/pine-pip.js'), 'utf8');
const panel = source.slice(source.indexOf('  function pinePipPanel(w)'), source.indexOf('\n  let state, overlay'));

async function fixture(palette) {
  let callback, geometry, material, energy = 0, reduced = false, renders = 0, borrowed = 0;
  const classes = new Set();
  class Element {
    constructor() { this.children = []; this.style = { setProperty(key, value) { this[key] = value; } }; this.clientWidth = 800; this.clientHeight = 450; }
    append(...nodes) { this.children.push(...nodes); }
    appendChild(n) { this.append(n); }
    addEventListener() {}
    remove() {}
  }
  class Geometry {
    constructor() { geometry = this; this.attributes = {}; }
    setAttribute(key, value) { this.attributes[key] = value; }
    dispose() {}
  }
  const audio = { tagName: 'AUDIO', id: 'voicePlayer', dataset: { pineLive: 'voice' }, paused: false, ended: false };
  const w = {
    document: { head: new Element(), body: new Element(), createElement: () => new Element(), querySelectorAll: () => [audio],
      documentElement: { classList: { toggle(key, on) { on ? classes.add(key) : classes.delete(key); } } } },
    addEventListener() {}, postMessage() {}, devicePixelRatio: 1,
    requestAnimationFrame(fn) { callback = fn; return 1; }, cancelAnimationFrame() { callback = null; },
    matchMedia: () => ({ matches: reduced }),
    pineAudioCtx: { state: 'running' },
    audioScope(el) { assert.equal(el, audio); borrowed++; return { analyser: { frequencyBinCount: 48, getByteFrequencyData(bins) { bins.fill(energy); } } }; },
    THREE: {
      WebGLRenderer: class { constructor() { this.domElement = new Element(); } setPixelRatio() {} setSize() {} render() { renders++; } dispose() {} forceContextLoss() {} },
      Scene: class { add() {} }, PerspectiveCamera: class { constructor() { this.position = {}; } updateProjectionMatrix() {} },
      BufferGeometry: Geometry, BufferAttribute: class { constructor(array) { this.array = array; } },
      PointsMaterial: class { constructor(options) { Object.assign(this, options); this.color = { value: options.color, set(value) { this.value = value; } }; material = this; } dispose() {} },
      Points: class { constructor() { this.rotation = {}; } }, AdditiveBlending: 2
    }
  };
  const deterministicMath = Object.create(Math); deterministicMath.random = () => .37;
  vm.runInNewContext(panel + '\npinePipPanel(w);', { w, Math: deterministicMath });
  if (palette) w.PinePipPanel.appearance(palette);
  w.PinePipPanel.set(true, '', false);
  await Promise.resolve();
  const tick = t => callback(t);
  return { w, audio, classes, tick, energy: value => (energy = value), reduced: value => (reduced = value),
    positions: () => Array.from(geometry.attributes.position.array), opacity: () => material.opacity,
    borrowed: () => borrowed, renders: () => renders, colour: () => material.color.value, host: w.document.body.children[0] };
}

(async () => {
  const amber = { surface: '32 23 10', text: '#fff1d5', accent: '#ffd180', button: '#4e381c' };
  const plum = { surface: '30 15 36', text: '#f5e6ff', accent: '#dbadff', button: '#493052' };
  const themed = await fixture(amber);
  assert.equal(themed.colour(), amber.accent, 'particles created after theme selection use its palette');
  themed.w.PinePipPanel.appearance(plum);
  assert.equal(themed.colour(), plum.accent, 'changing theme recolours the existing particle material');
  assert.equal(themed.host.style['--pip-surface'], plum.surface, 'webview background follows selected theme');
  assert.equal(themed.host.style['--pip-accent'], plum.accent, 'webview glow follows selected theme');
  themed.w.PinePipPanel.set(false);
  themed.w.PinePipPanel.set(true, '', false); await Promise.resolve();
  assert.equal(themed.colour(), plum.accent, 're-entering PiP keeps the selected particle colour');
  themed.w.PinePipPanel.set(false);
  const idle = await fixture(), talking = await fixture();
  talking.energy(150);
  for (let t = 100; t <= 1100; t += 40) { idle.tick(t); talking.tick(t); }
  assert.ok(talking.borrowed() > 0, 'samples voice audio even with voice widgets disabled');
  const sleeping = await fixture(); sleeping.w.pineAudioCtx.state = 'suspended'; sleeping.tick(100);
  assert.equal(sleeping.borrowed(), 0, 'particles cannot route playing audio into a suspended graph');
  delete sleeping.w.pineAudioCtx; sleeping.tick(200);
  assert.equal(sleeping.borrowed(), 0, 'particles cannot create a new audio graph without a gesture');
  assert.ok(talking.opacity() > idle.opacity() + .1, 'speech brightens the cloud');
  assert.ok(Math.abs(talking.positions()[0]) < Math.abs(idle.positions()[0]), 'speech gathers particles toward the center');
  assert.ok(Math.abs(talking.positions()[1] - idle.positions()[1]) > .1, 'spectrum adds vertical ripples');
  talking.audio.paused = true;
  for (let t = 1140; t < 3500; t += 40) talking.tick(t);
  assert.ok(talking.opacity() < .66, 'paused voice releases to idle');
  talking.reduced(true); talking.audio.paused = false;
  talking.tick(3600); const still = talking.positions(); talking.tick(3800);
  assert.deepEqual(talking.positions(), still, 'reduced motion renders a still cloud');
  assert.ok(talking.renders() > 0);
  assert.ok(talking.classes.has('pine-pip'), 'PiP locks the document root');
  talking.w.PinePipPanel.set(false);
  assert.ok(!talking.classes.has('pine-pip'), 'exit restores document scrolling');
  console.log('PiP particles: analyser sampling, speech gathering/ripples, pause release, reduced motion and root cleanup passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
