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

function boot(withPlayer = false) {
  const store = {
    pineMixer: JSON.stringify({voice: 0.68, music: 0.21, sfx: 0.4, video: 0.7})
  };
  const voice = slider(200);
  const music = slider(31);
  const writes = [];
  const player = withPlayer ? {
    paused: false, volume: 1, muted: false, pauses: 0, listeners: {},
    pause() { this.paused = true; this.pauses += 1; },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    play() { this.paused = false; this.listeners.play?.(); }
  } : null;
  global.document = {
    getElementById(id) {
      return id === 'djGainVoice' ? voice
        : id === 'djGainMusic' ? music
        : id === 'musicPlayer' ? player : null;
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
  return {store, voice, music, player, writes, bus: global.pineLevels};
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
  assert.equal(world.voice.value, '200');
  assert.equal(world.writes.at(-1).voice, 1);
  assert.equal(JSON.parse(world.store.pineListenerLevels).voice, 2);
  assert.equal(seen.voice, 2);
});

test('every canonical stream has one persistent 0 to 200 percent ceiling', () => {
  const world = boot();
  assert.deepEqual(world.bus.CEIL, {voice: 2, music: 2, sfx: 2, video: 2});
  for (const kind of ['voice', 'music', 'sfx', 'video']) {
    world.bus.apply(kind, 20);
    assert.equal(world.bus.get()[kind], 2, kind + ' did not clamp at 200%');
  }
  assert.deepEqual(JSON.parse(world.store.pineListenerLevels),
    {voice: 2, music: 2, sfx: 2, video: 2});
});

test('legacy mixer callers are aliases of the canonical listener store', () => {
  const world = boot();
  global.pineMixer.set({music: 0.07});
  assert.equal(world.bus.get().music, 0.07);
  assert.equal(JSON.parse(world.store.pineListenerLevels).music, 0.07);
  assert.equal(global.pineMixer.get().music, 0.07);
});

test('music zero pauses the record and prevents an automatic replay', () => {
  const world = boot(true);
  world.bus.apply('music', 0);
  assert.equal(world.player.paused, true);
  assert.equal(world.player.pauses, 1);
  world.player.play();
  assert.equal(world.player.paused, true);
  world.bus.apply('music', 0.4);
  world.player.play();
  assert.equal(world.player.paused, false);
});
