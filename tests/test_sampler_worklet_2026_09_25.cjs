const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/sampler-air.js'), 'utf8');
const settle = () => new Promise((resolve) => setImmediate(resolve));

function harness({rejectModule = false, detached = false} = {}) {
  const nodes = [], worklets = [], revoked = [];
  let finishModule;
  function node(kind) {
    const value = {kind, outputs: new Set(), gain: {value: 1}, frequencyBinCount: 64,
      connect(target) { this.outputs.add(target); },
      disconnect(target) { if (target) this.outputs.delete(target); else this.outputs.clear(); }};
    nodes.push(value);
    return value;
  }
  const context = {sampleRate: 48000, currentTime: 0, state: 'running',
    destination: node('destination'),
    createGain: () => node('gain'), createAnalyser: () => node('analyser'),
    createScriptProcessor: () => node('script'),
    audioWorklet: {addModule: () => new Promise((resolve, reject) => {
      finishModule = () => rejectModule ? reject(new Error('CSP denied')) : resolve();
    })}};
  const player = {id: 'djVoiceAudio1', tagName: 'AUDIO', paused: false, dataset: {}};
  const analyser = node('player');
  const root = {pineAudioCtx: context, audioScope: () => ({analyser, context}),
    document: {querySelectorAll: () => detached ? [] : [player], addEventListener() {}, getElementById() {}},
    localStorage: {getItem: () => null},
    AudioWorkletNode: function () { const value = node('worklet'); value.port = {}; worklets.push(value); return value; },
    URL: {createObjectURL: () => 'blob:tap', revokeObjectURL: (url) => revoked.push(url)},
    Blob, console, setInterval: () => 1};
  vm.runInNewContext(source, root);
  root.PineAir.start();
  if (detached) root.audioScope(player);
  return {root, nodes, worklets, revoked, analyser, finish: () => finishModule()};
}

test('players remain connected to both capture rings after the async worklet switch', async () => {
  const h = harness();
  const inputs = [...h.analyser.outputs].filter((node) => node.kind === 'gain');
  assert.equal(inputs.length, 2);
  assert.ok(inputs.every((input) => [...input.outputs].some((node) => node.kind === 'script')));
  h.finish();
  await settle();
  assert.equal(h.root.PineAir.drops().how, 'worklet');
  assert.equal(h.worklets.length, 2);
  assert.ok(inputs.every((input) => [...input.outputs].some((node) => node.kind === 'worklet')));
  assert.ok(inputs.every((input) => ![...input.outputs].some((node) => node.kind === 'script')));
  assert.ok(h.nodes.filter((node) => node.kind === 'script').every((node) => !node.outputs.size));
  for (const tap of h.worklets) tap.port.onmessage({data: new Float32Array(4096).fill(0.25)});
  assert.equal(h.root.PineAir.seconds(), 4096 / 48000);
  assert.equal(h.root.PineAir.seconds(true), 4096 / 48000);
  assert.equal(h.root.PineAir.ready(), true);
  assert.deepEqual(h.revoked, ['blob:tap']);
});

test('a refused module leaves the script processors connected and releases its URL', async () => {
  const h = harness({rejectModule: true});
  h.finish();
  await settle();
  assert.match(h.root.PineAir.drops().how, /script processor/);
  assert.match(h.root.PineAir.drops().why, /CSP denied/);
  const processors = h.nodes.filter((node) => node.kind === 'script');
  assert.equal(processors.length, 2);
  assert.ok(processors.every((node) => node.outputs.size && typeof node.onaudioprocess === 'function'));
  processors.forEach((node) => node.onaudioprocess({playbackTime: 1,
    inputBuffer: {numberOfChannels: 1, getChannelData: () => new Float32Array(4096).fill(0.2)}}));
  assert.equal(h.root.PineAir.seconds(), 4096 / 48000);
  assert.equal(h.root.PineAir.seconds(true), 4096 / 48000);
  assert.deepEqual(h.revoked, ['blob:tap']);
});

test('an already playing detached voice joins the voice ring through the scope hook', async () => {
  const h = harness({detached: true});
  assert.equal([...h.analyser.outputs].filter((node) => node.kind === 'gain').length, 2);
  h.finish();
  await settle();
  h.worklets[1].port.onmessage({data: new Float32Array(4096).fill(0.3)});
  assert.equal(h.root.PineAir.seconds(true), 4096 / 48000);
});

test('the audio-thread processor folds stereo and preserves consecutive blocks', () => {
  const definition = source.slice(source.indexOf('var WORKLET_SOURCE ='), source.indexOf('var workletReady ='));
  const sandbox = {};
  vm.runInNewContext(definition, sandbox);
  let Processor;
  const blocks = [];
  vm.runInNewContext(sandbox.WORKLET_SOURCE, {
    AudioWorkletProcessor: class { constructor() { this.port = {postMessage: (data) => blocks.push([...data])}; } },
    registerProcessor: (name, value) => { assert.equal(name, 'pine-tap'); Processor = value; }
  });
  const tap = new Processor({processorOptions: {size: 4}});
  assert.equal(tap.process([[new Float32Array([1, 0.5]), new Float32Array([-1, 0.5])]]), true);
  tap.process([[new Float32Array([0.25, -0.25, 1, 0, -1, 0.5])]]);
  assert.deepEqual(blocks, [[0, 0.5, 0.25, -0.25], [1, 0, -1, 0.5]]);
});
