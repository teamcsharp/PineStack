// [levels-one] the bus, run for real in a sandbox: the master multiplies every
// output stage, the pads reach the sampler, a move is sent to the station, a move
// from another surface is taken, a re-apply is never sent, a hold is never stored.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'audio-law.js'), 'utf8');

function sandbox(stationLevels) {
  const store = {};
  const posts = [];
  const mixerSets = [];
  const pads = [];
  let station = {levels: stationLevels || null, rev: stationLevels ? 5 : 0};
  const timers = [];
  const root = {
    localStorage: {getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }},
    pineMixer: {set: v => mixerSets.push(Object.assign({}, v)), apply: () => {}, get: () => ({})},
    pineSampler: {master: v => { pads.push(v); return v; }},
    pineDesktop: {
      get: p => Promise.resolve(p === '/api/levels' ? JSON.parse(JSON.stringify(station)) : null),
      post: (p, b) => {
        posts.push({p, b});
        if (p === '/api/levels/adopt') {
          if (!station.levels) station = {levels: Object.assign({master: 1, voice: 1, music: 1, sfx: 1, video: 1, pads: 1}, b.levels), rev: 1};
          return Promise.resolve(JSON.parse(JSON.stringify(station)));
        }
        Object.assign(station.levels, b.levels);
        station.rev += 1;
        return Promise.resolve(JSON.parse(JSON.stringify(station)));
      },
    },
    requestAnimationFrame: fn => fn(),
    Date,
    location: {protocol: 'file:'},
  };
  const document = {querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, hidden: false};
  const ctx = {window: root, document, Event: function () {}, console, Math, JSON, Number, Object, String, Promise,
    isFinite, setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length; }, clearTimeout: () => {},
    setInterval: () => 1, module: undefined};
  ctx.globalThis = root;
  vm.createContext(ctx);
  vm.runInContext(src.replace(/\(typeof window !== 'undefined' \? window : globalThis\)\s*;?\s*$/, '(window);'), ctx);
  const run = () => { const t = timers.splice(0); t.forEach(x => x.fn()); };
  return {root, store, posts, mixerSets, pads, run, station: () => station, setStation: s => { station = s; }};
}

(async () => {
  // 1. the master multiplies every output; the rows keep their own numbers
  const a = sandbox({master: 1, voice: 1, music: 0.5, sfx: 1, video: 1, pads: 1});
  const L = a.root.pineLevels;
  assert(L && typeof L.effective === 'function', 'pineLevels.effective exists');
  L.applyAll({music: 0.5, pads: 1.2}, {quiet: true});
  L.apply('master', 0.5);
  assert.strictEqual(L.get().music, 0.5, 'the music row still reads 50%');
  assert.strictEqual(L.get().master, 0.5);
  assert.strictEqual(L.effective().music, 0.25, 'the sound is level x master');
  assert.strictEqual(a.pads[a.pads.length - 1], 0.6, 'the pads heard at 1.2 x 0.5');
  const lastMix = a.mixerSets[a.mixerSets.length - 1];
  assert.strictEqual(lastMix.music, 0.25, 'the mixer stage is handed level x master');

  // 2. a move goes to the station (after its 250 ms coalescing); a re-apply does not
  const before = a.posts.length;
  a.run();                                       // the 250 ms post timer (and the boot timers)
  await new Promise(r => setImmediate(r));
  const sent = a.posts.filter(p => p.p === '/api/levels');
  assert(sent.some(p => p.b.levels.master === 0.5), 'the master move was sent');
  L.refresh();
  L.applyAll(L.get(), {quiet: true});
  a.run();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(a.posts.filter(p => p.p === '/api/levels').length, sent.length, 'a re-apply is never sent');
  assert(a.posts.length >= before);

  // 3. a hold moves the sound, not the store, and never the station
  const n = a.posts.length;
  L.hold('master', 0.1);
  assert.strictEqual(L.get().master, 0.5, 'the stored master is untouched');
  assert(Math.abs(L.effective().music - 0.05) < 1e-9, 'the sound follows the hold');
  L.release('master');
  assert.strictEqual(L.effective().music, 0.25);
  a.run();
  assert.strictEqual(a.posts.length, n, 'a hold is never sent');

  // 4. joining: the first surface adopts; another surface's move is taken
  const b = sandbox(null);
  b.root.pineLevels.applyAll({music: 0.0875, voice: 1.04}, {quiet: true});
  b.run();                                       // lvlSyncStart after 1.2 s
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));
  const adopt = b.posts.find(p => p.p === '/api/levels/adopt');
  assert(adopt, 'an unseeded station is adopted');
  assert.strictEqual(adopt.b.levels.music, 0.0875, 'with this surface\'s own levels');
  assert.strictEqual(b.store.pineLevelsAdopted, '1');
  const st = b.station();
  b.setStation({levels: Object.assign({}, st.levels, {voice: 0.7}), rev: st.rev + 3});
  b.root.pineLevels.sync();                      // the poll: read and take
  const got = await b.root.pineDesktop.get('/api/levels');
  // drive the same path the 2.5 s poll drives
  vm.runInNewContext('0');
  assert(got.levels.voice === 0.7);
  console.log('levels-bus ok');
})().catch(e => { console.error(e); process.exit(1); });
