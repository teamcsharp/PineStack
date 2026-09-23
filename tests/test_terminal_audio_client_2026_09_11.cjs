/* The page half of the routing table: does the tablet actually obey it?
 *
 * The decision is tested in test_terminal_audio; what is pinned here is the
 * carrying out - that the desktop can move the tablet's levels, that a
 * silenced device goes quiet without losing its numbers, that a hand on the
 * tablet's own desk still wins, and that a volume above 1.0 no longer
 * throws. That last one is the measured hardware bug that left the DJs
 * inaudible on the tablet while music played.
 *
 * No jsdom here - a fake document is enough and stays honest about which
 * DOM surface this file actually depends on, which is four methods.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');

/* ---- the smallest DOM this file can work against ------------------- */

class FakeInput {
  constructor(id, value) {
    this.id = id; this.value = String(value); this.listeners = {};
  }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  dispatchEvent(event) {
    for (const fn of this.listeners[event.type] || []) fn(event);
    return true;
  }
}

class FakeMedia {
  constructor(where) { this.muted = false; this.where = where || ''; this._v = 1; this.dataset = {}; }
  closest(sel) { return this.where && sel.includes(this.where) ? {} : null; }
}

class FakeDoc {
  constructor(elements, media) {
    this.elements = elements || {};
    this.media = media || [];
  }
  getElementById(id) { return this.elements[id] || null; }
  querySelectorAll() { return this.media; }
}

/* window.Event, which setDesk constructs. */
global.Event = global.Event || class { constructor(type) { this.type = type; } };

const audio = require('../desktop/terminal-audio.cjs');
const {
  Client, clamp, deskLevels, setDesk, mute, clampMediaVolume
} = require('../desktop/renderer/terminal-audio-client.js');

const TABLE = {
  terminals: {
    pinetab: {name: 'PineTab', play: true, music: 0.8, voice: 1, reply: 1,
      addr: '10.89.1.154'},
    desktop: {name: 'This app', play: false, music: 0.6, voice: 0.6,
      reply: 0.6, fallback: true, addr: '10.89.1.246'}
  }
};
const ROSTER = {listeners: [
  {listener: 'a', addr: '10.89.1.154', seen: 3},
  {listener: 'b', addr: '10.89.1.246', seen: 2}
]};

function harness(overrides) {
  const doc = new FakeDoc(
    {djGainMusic: new FakeInput('djGainMusic', 100),
      djGainVoice: new FakeInput('djGainVoice', 160)},
    [new FakeMedia(), new FakeMedia(), new FakeMedia('#sampler')]
  );
  const state = {settings: JSON.parse(JSON.stringify(TABLE)), puts: 0};
  const client = new Client(Object.assign({
    id: 'pinetab',
    document: doc,
    decide: audio.decide,
    update: audio.update,
    fetchJson: async (route, options) => {
      if (options && options.method === 'PUT') {
        state.puts += 1;
        state.settings = options.body;
        return {ok: true};
      }
      if (route === '/api/settings') return state.settings;
      if (route === '/api/radio/listeners') return ROSTER;
      throw new Error('unexpected route ' + route);
    }
  }, overrides || {}));
  return {doc, state, client};
}

/* ---- the clamp ------------------------------------------------------ */

test('a volume above 1.0 is clamped instead of throwing', () => {
  /* Modelled on the real setter, which raises IndexSizeError - the throw
   * aborted the routine that was setting it, so the DJs never started. */
  let held = 1;
  class Media {}
  Object.defineProperty(Media.prototype, 'volume', {
    configurable: true,
    get() { return held; },
    set(value) {
      if (value < 0 || value > 1) throw new RangeError('IndexSizeError ' + value);
      held = value;
    }
  });
  const saved = global.HTMLMediaElement;
  global.HTMLMediaElement = Media;
  try {
    assert.equal(clampMediaVolume(), true);
    const element = new Media();
    element.volume = 1.6;                 /* would have thrown */
    assert.equal(held, 1);
    element.volume = 0.4;
    assert.equal(element.volume, 0.4);
    element.volume = -2;
    assert.equal(held, 0);
  } finally { global.HTMLMediaElement = saved; }
});

test('the clamp is installed once, not stacked on every start', () => {
  assert.equal(clampMediaVolume(), false, 'already clamped above');
});

/* ---- the desk ------------------------------------------------------- */

test('the desk is read as fractions, not percentages', () => {
  const {doc} = harness();
  const levels = deskLevels(doc);
  assert.equal(levels.music, 1);
  /* Raw, not clamped: 160% must NOT read as 100%, or the table could never
   * pull a boosted slider down - it would look like it already agreed. */
  assert.equal(Math.round(levels.voice * 100), 160);
  assert.equal(levels.reply, null, 'the panel has no reply slider');
});

test('setting the desk fires the events the panel listens for', () => {
  const {doc} = harness();
  const seen = [];
  doc.elements.djGainMusic.addEventListener('input', (e) => seen.push(e.type));
  doc.elements.djGainMusic.addEventListener('change', (e) => seen.push(e.type));
  assert.equal(setDesk(doc, 'music', 0.35), true);
  assert.equal(doc.elements.djGainMusic.value, '35');
  assert.deepEqual(seen, ['input', 'change']);
  assert.equal(setDesk(doc, 'music', 0.35), false, 'no needless second event');
});

test('muting leaves the sampler alone', () => {
  const {doc} = harness();
  assert.equal(mute(doc, true), 2, 'the two broadcast elements, not the pad');
  assert.equal(doc.media[0].muted, true);
  assert.equal(doc.media[2].muted, false, 'a pad is the operator, not the show');
});

/* ---- the loop ------------------------------------------------------- */

test('the tablet takes its levels from the table, set on another machine', () => {
  const {doc, client} = harness();
  return client.tick().then(() => {
    assert.equal(doc.elements.djGainMusic.value, '80');
    assert.equal(doc.elements.djGainVoice.value, '100');
    assert.equal(doc.media[0].muted, false, 'it is the one playing');
  });
});

test('a device switched off goes quiet but KEEPS its levels', () => {
  /* Zeroing the sliders would be written back as the operator's chosen
   * levels the next time this device took the air. */
  const {doc, client, state} = harness();
  state.settings.terminals.pinetab.play = false;
  return client.tick().then(() => {
    assert.equal(doc.media[0].muted, true);
    assert.equal(doc.media[1].muted, true);
    assert.equal(doc.elements.djGainMusic.value, '100', 'untouched');
  });
});

test('the desktop unmutes itself when it takes over from a dark tablet', () => {
  const {doc, client, state} = harness({id: 'desktop'});
  state.settings.terminals.pinetab.addr = '10.89.9.99';   /* gone */
  mute(doc, true);
  return client.tick().then((decision) => {
    assert.equal(decision.takeover, 'desktop');
    assert.equal(doc.media[0].muted, false);
    assert.equal(doc.elements.djGainMusic.value, '60');
  });
});

test('a decorative video stays muted through a solo-gate handover', () => {
  const {doc} = harness();
  const decor = doc.media[1];
  decor.dataset.pineDecor = '1';
  decor.muted = true;
  mute(doc, true);
  mute(doc, false);
  assert.equal(decor.muted, true, 'an intentional mute is not a gate mute');
});

test('a hand on the tablet\'s own slider wins and is written back', async () => {
  const {doc, client, state} = harness();
  client.watchDesk();
  doc.elements.djGainMusic.value = '25';
  doc.elements.djGainMusic.dispatchEvent({type: 'change'});
  await new Promise((r) => setImmediate(r));
  assert.equal(state.settings.terminals.pinetab.music, 0.25,
    'the table followed the hand');
  assert.equal(state.puts, 1);
});

test('the station being unreachable does not silence a device that is playing', async () => {
  /* A dropped poll is not an instruction. */
  const {doc, client} = harness();
  await client.tick();
  assert.equal(doc.media[0].muted, false);
  client.fetchJson = async () => { throw new Error('ECONNREFUSED'); };
  const out = await client.tick();
  assert.equal(out, null);
  assert.equal(doc.media[0].muted, false, 'still playing');
});

test('claiming a row names this device and leaves the rest of settings alone', async () => {
  const {client, state} = harness({id: 'booth'});
  state.settings.dj = {voice: 'caine'};
  await client.claim({addr: '10.89.1.7', play: false});
  assert.equal(state.settings.terminals.booth.name, 'booth');
  assert.equal(state.settings.terminals.booth.addr, '10.89.1.7');
  assert.deepEqual(state.settings.dj, {voice: 'caine'});
  assert.equal(state.settings.terminals.pinetab.music, 0.8, 'the tablet survives');
});

test('a claim does not overwrite a name the operator gave the device', async () => {
  const {client, state} = harness();
  await client.claim({addr: '10.89.1.154'});
  assert.equal(state.settings.terminals.pinetab.name, 'PineTab');
});

test('clamp refuses nonsense rather than passing it to the element', () => {
  assert.equal(clamp('loud', 0.5), 0.5);
  assert.equal(clamp(2), 1);
  assert.equal(clamp(-1), 0);
});
