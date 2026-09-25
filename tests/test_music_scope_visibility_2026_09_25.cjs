const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
const start = source.indexOf('let musicScopeVisible = true;');
const end = source.indexOf('// #1413: THE SCOPE AT A TABLET', start);
assert.ok(start >= 0 && end > start);
const scopeCode = source.slice(start, end);

function harness({tablet = true, observer = true} = {}) {
  const paints = {clears: 0, bars: 0, audio: 0, resumes: 0};
  const observers = [];
  class FakeObserver {
    constructor(callback) { this.callback = callback; observers.push(this); }
    observe(canvas) { this.canvas = canvas; }
    unobserve(canvas) { this.unobserved = canvas; }
    emit(canvas, visible) {
      this.callback([{target: canvas, isIntersecting: visible}]);
    }
  }
  const context2d = {
    clearRect() { paints.clears += 1; },
    createLinearGradient() { return {addColorStop() {}}; },
    fillRect() { paints.bars += 1; },
  };
  const canvas = (id = 'musicScope') => ({
    id, offsetParent: {}, clientWidth: 100, clientHeight: 20,
    width: 100, height: 20, getContext() { return context2d; },
  });
  const scope = {
    context: {
      state: 'running',
      resume() { paints.resumes += 1; return Promise.resolve(); },
    },
    analyser: {getByteFrequencyData() {}},
    bins: new Uint8Array(256),
  };
  const context = {
    PINE_TABLET: tablet,
    IntersectionObserver: observer ? FakeObserver : undefined,
    window: {devicePixelRatio: 1},
    performance: {now: () => 1000},
    audioScope() { paints.audio += 1; return scope; },
    scopeAccentNow: () => '#46a',
  };
  vm.createContext(context);
  vm.runInContext(scopeCode, context);
  return {context, canvas, scope, paints, observers};
}

test('the offscreen tablet scope stops painting while audio still resumes', () => {
  const h = harness();
  const canvas = h.canvas();
  const player = {paused: false, ended: false};
  h.context.drawScope(canvas, player);
  assert.equal(h.paints.clears, 1, 'initial frame remains visible until observed');
  assert.equal(h.observers.length, 1);
  h.observers[0].emit(canvas, false);

  h.scope.context.state = 'suspended';
  h.context.drawScope(canvas, player);
  assert.equal(h.paints.clears, 1);
  assert.equal(h.paints.bars, 64);
  assert.equal(h.paints.audio, 2, 'audio graph stays connected offscreen');
  assert.equal(h.paints.resumes, 1, 'audio context resumes without a paint');
});

test('the scope paints again when scrolled onscreen and follows replacement nodes', () => {
  const h = harness();
  const first = h.canvas();
  const player = {paused: false, ended: false};
  h.context.drawScope(first, player);
  h.observers[0].emit(first, false);
  h.observers[0].emit(first, true);
  h.context.drawScope(first, player);
  assert.equal(h.paints.clears, 2);
  assert.equal(h.paints.bars, 128);

  const replacement = h.canvas();
  h.context.drawScope(replacement, player);
  assert.equal(h.observers[0].unobserved, first);
  assert.equal(h.observers[0].canvas, replacement);
  assert.equal(h.paints.clears, 3);
});

test('non-tablet and missing observer retain the original painting path', () => {
  for (const options of [{tablet: false}, {observer: false}]) {
    const h = harness(options);
    const player = {paused: true, ended: false};
    h.context.drawScope(h.canvas(), player);
    h.context.drawScope(h.canvas(), player);
    assert.equal(h.paints.clears, 2);
    assert.equal(h.observers.length, 0);
  }
});
