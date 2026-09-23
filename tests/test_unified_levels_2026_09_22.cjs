const assert = require('node:assert/strict');
const {test} = require('node:test');
const path = require('node:path');

const LAW = path.join(__dirname, '..', 'desktop', 'renderer', 'audio-law.js');

function slider(value) {
  return {
    value: String(value), min: '0', max: '600', events: [],
    dispatchEvent(event) { this.events.push(event.type); return true; }
  };
}

function boot() {
  const store = {
    pineMixer: JSON.stringify({voice: 0.68, music: 0.21, sfx: 0.4, video: 0.7})
  };
  const voice = slider(200);
  const music = slider(31);
  const writes = [];
  global.document = {
    getElementById(id) {
      return id === 'djGainVoice' ? voice : id === 'djGainMusic' ? music : null;
    },
    querySelector: () => null,
    querySelectorAll: () => []
  };
  global.localStorage = {
    getItem: (key) => Object.prototype.hasOwnProperty.call(store, key) ? store[key] : null,
    setItem: (key, value) => { store[key] = String(value); }
  };
  global.Event = class { constructor(type) { this.type = type; } };
  global.pineMixer = {
    get: () => JSON.parse(store.pineMixer),
    set: (patch) => { writes.push({...patch}); return patch; }
  };
  global.djApplyGain = () => {};
  delete global.pineLevels;
  delete global.PineAudioLaw;
  delete require.cache[require.resolve(LAW)];
  require(LAW);
  return {store, voice, music, writes, bus: global.pineLevels};
}

test('legacy cut and gain stages migrate to their actual audible product', async () => {
  const world = boot();
  const levels = world.bus.get();
  assert.equal(Math.round(levels.voice * 100), 136);
  assert.equal(Math.round(levels.music * 10000), 651);
  assert.equal(levels.sfx, 0.4);
  assert.equal(levels.video, 0.7);
  await new Promise((resolve) => setTimeout(resolve, 30));
  const saved = JSON.parse(world.store.pineListenerLevels);
  assert.equal(Math.round(saved.voice * 100), 136);
  assert.equal(Math.round(saved.music * 10000), 651);
});

test('one bus write updates the cut, boost, store, and every watching view', () => {
  const world = boot();
  let seen = null;
  world.bus.onApply((levels) => { seen = levels; });
  const road = world.bus.apply('voice', 2.4);
  assert.match(road, /local/);
  assert.equal(world.voice.value, '240');
  assert.equal(world.writes.at(-1).voice, 1);
  assert.equal(JSON.parse(world.store.pineListenerLevels).voice, 2.4);
  assert.equal(seen.voice, 2.4);
});
