const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'deaf-watch.js'), 'utf8');

function harness({bridge = () => Promise.resolve({}), web = () => Promise.resolve({status: 200}), media = [], location, stationBase} = {}) {
  let id = 0, bridgeCalls = 0, webCalls = 0;
  const timers = new Map(), intervals = new Map(), revivals = [];
  const context = vm.createContext({Promise, WeakMap, AbortController,
    document: {querySelectorAll: () => media},
    setTimeout(fn, delay) { const key = ++id; timers.set(key, {fn, delay}); return key; },
    clearTimeout(key) { timers.delete(key); },
    setInterval(fn, delay) { const key = ++id; intervals.set(key, {fn, delay}); return key; },
    clearInterval(key) { intervals.delete(key); },
    window: {
      location,
      pineStationBase: stationBase,
      pineDesktop: {get: () => { bridgeCalls++; return bridge(); },
        revive: request => { revivals.push(request); return Promise.resolve({say: 'test declined'}); }},
      fetch: (...args) => { webCalls++; return web(...args); }
    }
  });
  vm.runInContext(source, context);
  return {watch: context.window.PineDeafWatch, timers, intervals, revivals,
    counts: () => ({bridgeCalls, webCalls}),
    expire(delay) {
      for (const [key, row] of [...timers]) if (row.delay === delay) { timers.delete(key); row.fn(); }
    }};
}

test('deaf watch permits one probe and bounds both hung roads', async () => {
  const h = harness({bridge: () => new Promise(() => {}), web: () => new Promise(() => {})});
  const first = h.watch.look(); h.watch.look();
  assert.deepEqual(h.counts(), {bridgeCalls: 1, webCalls: 1});
  h.expire(25000); await first;
  assert.equal(h.watch.state().bridge, false);
  assert.equal(h.watch.state().strikes, 0); assert.equal(h.revivals.length, 0);
  const second = h.watch.look(); h.expire(25000); await second;
  assert.deepEqual(h.counts(), {bridgeCalls: 2, webCalls: 2});
});

test('loading rounds belong to the same media source', () => {
  const el = {id: 'dj', tagName: 'AUDIO', src: '/first.wav', currentSrc: '',
    getAttribute(name) { return this[name]; }, networkState: 2, readyState: 0};
  const h = harness({media: [el]});
  assert.equal(h.watch.media().stuck, 0);
  el.src = '/second.wav'; assert.equal(h.watch.media().stuck, 0);
  assert.equal(h.watch.media().stuck, 1);
  el.readyState = 4; assert.equal(h.watch.media().stuck, 0);
});

test('successful probes retire deadlines, and stop cancels its warmup', async () => {
  const h = harness(); await h.watch.look();
  assert.equal([...h.timers.values()].some(row => row.delay === 25000), false);
  h.watch.stop();
  assert.equal(h.timers.size, 0); assert.equal(h.intervals.size, 0);
});

test('stopped watch cannot revive from an obsolete third result', async () => {
  const h = harness({web: () => Promise.reject(new Error('web down'))});
  await h.watch.look(); await h.watch.look();
  assert.equal(h.watch.state().strikes, 2);
  const pending = h.watch.look(); h.watch.stop(); await pending;
  assert.equal(h.watch.state().strikes, 0); assert.equal(h.revivals.length, 0);
});

test('desktop probe uses the station URL and an unknown base cannot trigger revival', async () => {
  const urls = [];
  const h = harness({location: {protocol: 'file:'}, stationBase: () => 'http://10.89.1.246:8096/',
    web: url => { urls.push(url); return Promise.resolve({status: 200}); }});
  await h.watch.look();
  assert.deepEqual(urls, ['http://10.89.1.246:8096/api/dj/sections']);
  assert.equal(h.watch.state().strikes, 0);
  const missing = harness({location: {protocol: 'file:'}});
  await missing.watch.look(); await missing.watch.look(); await missing.watch.look();
  assert.equal(missing.counts().webCalls, 0); assert.equal(missing.revivals.length, 0);
  assert.equal(missing.watch.state().strikes, 0);
});

test('file document accepts opaque reachability without requiring station CORS', async () => {
  const modes = [];
  const h = harness({location: {protocol: 'file:'}, stationBase: () => 'http://station:8096',
    web: (_url, options) => { modes.push(options.mode); return Promise.resolve({status: 0, type: 'opaque'}); }});
  await h.watch.look(); await h.watch.look(); await h.watch.look();
  assert.deepEqual(modes, ['no-cors', 'no-cors', 'no-cors']);
  assert.equal(h.watch.state().web, true);
  assert.equal(h.watch.state().strikes, 0); assert.equal(h.revivals.length, 0);
});
