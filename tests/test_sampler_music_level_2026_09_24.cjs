const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'sampler-air.js'), 'utf8');

function boot(canonical) {
  const writes = [];
  const gain = {
    value: 1,
    setTargetAtTime(value) { this.value = value; writes.push(value); }
  };
  const record = {id: 'musicPlayer', tagName: 'AUDIO', paused: false, ended: false, muted: false, volume: 1};
  const clip = {id: 'djVoiceAudio1', tagName: 'AUDIO', paused: false, ended: false, muted: false, volume: 1};
  const intervals = [];
  const root = {
    document: {
      getElementById: (id) => id === 'musicPlayer' ? record : null,
      querySelectorAll: () => [record, clip],
      addEventListener() {}
    },
    localStorage: {getItem: () => null},
    gainFor: () => ({node: {gain}, context: {currentTime: 0}}),
    djLevels: () => ({music: 1, voice: 1.6, duck: 0.7}),
    pineLevels: {get: () => ({music: canonical.value})},
    setInterval: (fn) => { intervals.push(fn); return intervals.length; },
    setTimeout: () => 1,
    clearTimeout() {},
    URL,
    console
  };
  vm.runInNewContext(source, root, {filename: 'sampler-air.js'});
  root.PineAir.start();
  return {air: root.PineAir, canonical, clip, gain, writes, tick: intervals[0]};
}

test('clip duck and release never raise music above a listener zero', () => {
  const world = boot({value: 0});
  world.tick();
  assert.equal(world.air.duckState().clipDucked, true);
  world.clip.paused = true;
  world.tick();
  assert.deepEqual(world.writes, [0, 0]);
  assert.equal(world.gain.value, 0);
});

test('pad release uses the latest listener setting, including zero', () => {
  const canonical = {value: 0.25};
  const world = boot(canonical);
  world.tick();
  assert.ok(Math.abs(world.gain.value - 0.075) < 0.000001);
  world.air.duck('pad');
  canonical.value = 0;
  world.air.release('pad');
  assert.equal(world.gain.value, 0);
  assert.equal(world.writes.at(-1), 0);
});
