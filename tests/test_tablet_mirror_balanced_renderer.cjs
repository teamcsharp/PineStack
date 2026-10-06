'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {Mirror} = require('../desktop/tablet-mirror.cjs');

const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/tablet-mirror.js'), 'utf8');
const sizing = source.slice(source.indexOf('const MOST ='), source.indexOf("glass.addEventListener('wheel'"));
const controls = source.slice(source.indexOf('async function setDetail('), source.indexOf('/* -------------------------------------------------------------- window */'));
const follow = source.slice(source.indexOf('function followMirror(said) {'), source.indexOf('async function watch() {'));
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };

function harness(real, windowSize, size = 'balanced') {
  const timers = new Map(), calls = [], buttons = new Map();
  let id = 0;
  for (const name of ['quarter', 'third', 'half', 'balanced', 'full']) {
    const handlers = new Map();
    buttons.set(name, {dataset: {size: name}, addEventListener(event, fn) { handlers.set(event, fn); }, click() { handlers.get('click')(); }});
  }
  const glass = {clientWidth: windowSize.width, clientHeight: windowSize.height, classList: {toggle() {}}};
  const live = {clientWidth: windowSize.width, clientHeight: windowSize.height, naturalWidth: 10, style: {}};
  const context = vm.createContext({
    shown: {ok: true, size, real, quality: 0.35}, glass, live,
    document: {hidden: false, getElementById() { return {}; }, querySelectorAll() { return [...buttons.values()]; }},
    api: {async mirrorSize(want) { calls.push(want); return {...context.shown, size: want}; }},
    paintButtons() {}, paintAuto() {}, cover() {}, paintQuality() {},
    mirrorClosed: false, imageFailed: false, streamUrl: '', boundAt: 0,
    qualityDragging: false, how: {}, localStorage: {setItem() {}},
    begin() {}, bindStream() {}, retryImage() {}, Date,
    setTimeout(fn, delay) { const key = ++id; timers.set(key, {fn, delay}); return key; },
    clearTimeout(key) { timers.delete(key); }
  });
  vm.runInContext(sizing + '\n' + controls + '\n' + follow, context);
  const call = code => vm.runInContext(code, context);
  return {context, glass, live, calls, buttons, call, async settle() {
    for (const [key, timer] of [...timers]) {
      if (timer.delay !== 500) continue;
      timers.delete(key); timer.fn();
    }
    await flush();
  }};
}

test('renderer candidate dimensions agree with the producer at different physical screen sizes', () => {
  for (const real of [{width: 736, height: 1340}, {width: 1080, height: 2400},
    {width: 3840, height: 2160}, {width: 801, height: 479}]) {
    const h = harness(real, real), producer = new Mirror();
    producer.real = real;
    for (const name of ['quarter', 'third', 'half', 'balanced', 'full']) {
      const expected = producer.shapeFor(name);
      const actual = h.call('detailShape(' + JSON.stringify(name) + ')');
      assert.equal(actual.width, expected.width, name + ' width');
      assert.equal(actual.height, expected.height, name + ' height');
    }
  }
});

test('Auto selects balanced above Half on a 1340-pixel display', () => {
  const h = harness({width: 736, height: 1340}, {width: 500, height: 900});
  assert.equal(h.call('deserved()'), 'balanced');
  assert.deepEqual([...h.call('detailChoices().map(value => value.name)')],
    ['quarter', 'third', 'half', 'balanced', 'full']);
});

test('Auto selects balanced below Half on a 2400-pixel display', () => {
  const h = harness({width: 1080, height: 2400}, {width: 400, height: 890});
  assert.equal(h.call('deserved()'), 'balanced');
  assert.deepEqual([...h.call('detailChoices().map(value => value.name)')],
    ['quarter', 'third', 'balanced', 'half', 'full']);
});

test('Auto raises detail using actual capture area and keeps the selected quality', async () => {
  const h = harness({width: 1080, height: 2400}, {width: 400, height: 890}, 'quarter');
  h.call('auto = true; sharpenSoon()'); await h.settle();
  assert.deepEqual(h.calls, ['balanced']);
  assert.equal(h.context.shown.size, 'balanced');
  assert.equal(h.context.shown.quality, 0.35);
});

test('a deliberate Full choice disables Auto and remains at full detail', async () => {
  const h = harness({width: 736, height: 1340}, {width: 300, height: 600});
  h.call('auto = true'); h.buttons.get('full').click(); await flush();
  h.call('sharpenSoon()'); await h.settle();
  assert.deepEqual(h.calls, ['full']);
  assert.equal(h.call('auto'), false);
  assert.equal(h.context.shown.quality, 0.35);
});

test('background display measurement updates physical coordinates and dynamic Auto sizing', () => {
  const h = harness({width: 736, height: 1340}, {width: 400, height: 890});
  h.context.report = {ok: true, running: true, width: 432, height: 960,
    real: {width: 1080, height: 2400}, frames: 1, live: true};
  h.call('followMirror(report)');
  assert.equal(h.context.shown.real.width, 1080);
  assert.equal(h.context.shown.real.height, 2400);
  assert.equal(h.context.shown.width, 432);
  assert.equal(h.context.shown.height, 960);
  assert.equal(h.call('deserved()'), 'balanced');
  assert.equal(h.call("label('balanced')"), 'balanced detail');
});
