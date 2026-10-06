'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Execute the production lifecycle functions with a deterministic browser and
// clock. This covers IPC and image timing without touching a tablet or player.
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/tablet-mirror.js'), 'utf8');
const lifecycle = source.slice(source.indexOf('const api = window.pineDesktop'),
  source.indexOf('function paintButtons() {'));
const statusLoop = source.slice(source.indexOf('function followMirror(said) {'),
  source.indexOf('if (window.pineIconUpgrade)'));
const detail = source.slice(source.indexOf('async function setDetail('),
  source.indexOf('/* -------------------------------------------------------------- window */'));
const automatic = source.slice(source.indexOf('function sharpenSoon() {'),
  source.indexOf("glass.addEventListener('wheel'"));
const flush = async () => { for (let i = 0; i < 16; i += 1) await Promise.resolve(); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function harness(t, options = {}) {
  let now = 100000, nextId = 1;
  const timers = new Map(), events = new Map(), pictures = [], sizeCalls = [], storageWrites = [];
  const storage = new Map();
  if (Object.prototype.hasOwnProperty.call(options, 'savedSize')) storage.set('pine-mirror-size', options.savedSize);
  const buttons = ['quarter', 'third', 'half', 'balanced', 'full'].map(size => ({
    dataset: {size}, handlers: new Map(), addEventListener(name, fn) { this.handlers.set(name, fn); },
    click() { this.handlers.get('click')(); }
  }));
  const liveEvents = new Map();
  const live = {
    naturalWidth: 0, _src: '',
    addEventListener(name, fn) { liveEvents.set(name, fn); },
    getAttribute(name) { return name === 'src' ? this._src : null; },
    set src(value) { this._src = value; pictures.push({at: now, value}); },
    get src() { return this._src; },
    emit(name) { if (name === 'load') this.naturalWidth = 800; liveEvents.get(name)(); }
  };
  const classes = new Map();
  const veil = {textContent: 'Connecting...', classList: {toggle(name, value) { classes.set(name, value); }}};
  const how = {textContent: ''};
  const document = {hidden: false, getElementById(id) { return ({live, veil, how, glass: {}})[id]; },
    querySelectorAll(selector) { return selector === '.res' ? buttons : []; }};
  let opens = 0, polls = 0;
  const openCalls = [];
  const api = {
    mirrorOpen(settings) {
      opens += 1; openCalls.push({at: now, settings});
      return options.open ? options.open(opens, settings) : Promise.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: 'full', quality: 0.5});
    },
    mirrorSize(size) {
      sizeCalls.push(size);
      return options.size ? options.size(size, sizeCalls.length) : Promise.resolve({ok: true,
        url: 'http://127.0.0.1:8001/live.mjpg', size, quality: 0.5});
    },
    mirrorHow() {
      polls += 1;
      return options.how ? options.how(polls) : Promise.resolve({ok: true, running: true, paused: false, closing: false, live: false, frames: 0});
    }
  };
  const context = vm.createContext({
    window: {pineDesktop: api, addEventListener(name, fn) { events.set(name, fn); }}, document,
    wantQuality: 0.5, qualityDragging: false, paintButtons() {}, paintQuality() {},
    localStorage: {
      getItem(key) { if (options.storageReadFails) throw new Error('storage disabled'); return storage.get(key) ?? null; },
      setItem(key, value) { if (options.storageWriteFails) throw new Error('storage disabled'); storage.set(key, value); storageWrites.push([key, value]); }
    },
    auto: true, sharpenAt: 0, zoom: 1, paintAuto() {},
    deserved() { return options.autoSize || 'full'; },
    detailShape(name) { return name === 'full' ? {width: 1340, height: 800} : {width: 446, height: 266}; },
    frame() { return {wide: 400, tall: 240}; },
    Promise, Date: {now: () => now},
    setTimeout(fn, delay) { const id = nextId++; timers.set(id, {at: now + delay, fn}); return id; },
    clearTimeout(id) { timers.delete(id); }
  });
  vm.runInContext(lifecycle + '\n' + detail + '\n' + automatic + '\n' + statusLoop, context, {filename: 'tablet-mirror.js'});
  const call = code => vm.runInContext(code, context);
  const follow = value => { context.report = value; call('followMirror(report)'); };
  async function advance(ms) {
    const end = now + ms;
    let steps = 0;
    for (;;) {
      await flush();
      const entry = [...timers].filter(([, timer]) => timer.at <= end)
        .sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
      if (!entry) break;
      if (++steps > 2000) throw new Error('timer loop did not settle');
      now = entry[1].at; timers.delete(entry[0]); entry[1].fn();
    }
    now = end; await flush();
  }
  t.after(async () => { call('stopMirrorView()'); await flush(); });
  return {call, follow, advance, live, veil, how, classes, document, pictures, openCalls, sizeCalls, storageWrites, storage, buttons,
    get opens() { return opens; }, get polls() { return polls; }, get now() { return now; },
    close() { events.get('beforeunload')(); }};
}
const liveReport = overrides => ({ok: true, running: true, paused: false, closing: false,
  url: 'http://127.0.0.1:8001/live.mjpg', live: true, frames: 10, watchers: 1,
  width: 800, height: 1200, quality: 0.5, ...overrides});

test('initial open failure recovers without another click, using bounded backoff', async t => {
  const h = harness(t, {open: n => Promise.resolve(n < 6 ? {ok: false, why: 'ADB offline'} :
    {ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: 'full', quality: 0.5}),
    how: () => Promise.resolve({ok: false, why: 'Not ready'})});
  h.call('begin()'); await h.advance(43999);
  assert.equal(h.opens, 5);
  assert.deepEqual(h.openCalls.map(x => x.at - 100000), [0, 2000, 6000, 14000, 29000]);
  assert.match(h.veil.textContent, /Retrying/);
  await h.advance(1);
  assert.equal(h.opens, 6);
  assert.equal(h.pictures.length, 1);
  assert.match(h.live.src, /connection=1$/);
});

test('concurrent open and polling requests cannot duplicate an in-flight open', async t => {
  const pending = deferred();
  const h = harness(t, {open: () => pending.promise, how: () => Promise.resolve({ok: false})});
  h.call('begin(); begin(); begin();'); await h.advance(20000);
  assert.equal(h.opens, 1);
  assert.ok(h.polls >= 20);
  pending.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg', quality: 0.5});
  await h.advance(0);
  assert.equal(h.pictures.length, 1);
});

test('late open and status replies after closing cannot reopen or repaint the view', async t => {
  const pendingOpen = deferred(), pendingHow = deferred();
  const h = harness(t, {open: () => pendingOpen.promise, how: () => pendingHow.promise});
  h.call('begin()'); await flush();
  h.close();
  const words = h.how.textContent, cover = h.veil.textContent;
  pendingOpen.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg'});
  pendingHow.resolve(liveReport());
  await h.advance(30000);
  h.live.emit('error'); h.live.emit('load');
  assert.equal(h.opens, 1); assert.equal(h.polls, 1);
  assert.equal(h.pictures.length, 0);
  assert.equal(h.how.textContent, words); assert.equal(h.veil.textContent, cover);
});

test('encoder reconnect and quiet frames retain a healthy multipart image connection', async t => {
  const h = harness(t);
  h.call('begin()'); await h.advance(0); h.live.emit('load');
  h.follow(liveReport({live: false, reconnecting: true, sinceFrameMs: 30000, restartReason: 'encoder restart'}));
  assert.equal(h.classes.get('gone'), true);
  h.follow(liveReport({restarts: 1}));
  h.follow(liveReport({live: false, still: true, sinceFrameMs: 90000}));
  await h.advance(0);
  assert.equal(h.pictures.length, 1);
  assert.equal(h.classes.get('gone'), true);
});

test('a restarted local server changes the image URL once and preserves URL parameters', async t => {
  const h = harness(t);
  h.call('begin()'); await h.advance(0); h.live.emit('load');
  const changed = liveReport({url: 'http://127.0.0.1:9002/live.mjpg?mode=full'});
  h.follow(changed); await h.advance(0);
  assert.equal(h.pictures.length, 2);
  assert.equal(h.live.src, 'http://127.0.0.1:9002/live.mjpg?mode=full&connection=2');
  h.follow(changed); await h.advance(0);
  assert.equal(h.pictures.length, 2);
});

test('image errors retry with one timer and capped backoff, and a decoded image clears the failure', async t => {
  const h = harness(t);
  h.call('begin()'); await h.advance(0);
  const delays = [700, 1400, 2800, 5600, 10000, 10000];
  for (const delay of delays) {
    const count = h.pictures.length;
    h.live.emit('error'); h.live.emit('error');
    await h.advance(delay - 1); assert.equal(h.pictures.length, count);
    await h.advance(1); assert.equal(h.pictures.length, count + 1);
  }
  h.live.emit('error'); h.live.emit('load');
  const count = h.pictures.length;
  await h.advance(10000);
  assert.equal(h.pictures.length, count);
  assert.equal(h.classes.get('gone'), true);
  h.live.emit('error'); await h.advance(700);
  assert.equal(h.pictures.length, count + 1);
});

test('intentional pause, close, or a hidden window never starts recovery', async t => {
  const h = harness(t);
  h.follow(liveReport({running: false, paused: true, url: 'http://127.0.0.1:9002/live.mjpg'}));
  h.follow(liveReport({running: false, closing: true}));
  h.document.hidden = true;
  h.follow(liveReport({running: false})); h.follow({ok: false});
  await h.advance(30000);
  assert.equal(h.opens, 0); assert.equal(h.pictures.length, 0);
});

test('a cleanly closed image stream is reattached only when its local watcher is missing', async t => {
  const h = harness(t);
  h.call('begin()'); await h.advance(0); h.live.emit('load');
  await h.advance(2999); h.follow(liveReport({watchers: 0})); await h.advance(0);
  assert.equal(h.pictures.length, 1);
  await h.advance(1); h.follow(liveReport({watchers: 1})); await h.advance(1000);
  assert.equal(h.pictures.length, 1);
  h.follow(liveReport({watchers: 0})); await h.advance(700);
  assert.equal(h.pictures.length, 2);
  assert.equal(h.opens, 1);
});

test('polling errors recover startup, and a stopped unpaused mirror uses the same reopen path', async t => {
  const h = harness(t, {open: n => Promise.resolve(n === 1 ? {ok: false} :
    {ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: 'half', quality: 0.4}),
    how: n => n < 3 ? Promise.reject(new Error('IPC unavailable')) : Promise.resolve({ok: false})});
  h.call('begin()'); await h.advance(2000);
  assert.equal(h.opens, 2); assert.equal(h.pictures.length, 1);
  h.follow(liveReport({running: false, live: false, quality: 0.4})); await h.advance(0);
  assert.equal(h.opens, 3);
  assert.equal(h.openCalls[2].settings.size, 'half');
  assert.equal(h.openCalls[2].settings.quality, 0.4);
  assert.equal(h.pictures.length, 1);
});
test('closing before the queued IPC open is sent prevents starting a producer', async t => {
  const h = harness(t);
  h.call('begin()'); h.close();
  await h.advance(30000);
  assert.equal(h.opens, 0);
  assert.equal(h.pictures.length, 0);
});

test('status can attach to an already starting producer while open is still pending', async t => {
  const pending = deferred();
  const h = harness(t, {open: () => pending.promise, how: () => Promise.resolve(liveReport())});
  h.call('begin()'); await h.advance(0);
  assert.equal(h.opens, 1); assert.equal(h.pictures.length, 1);
  pending.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: 'full', quality: 0.5});
  await h.advance(0);
  assert.equal(h.pictures.length, 1);
});

test('opening starts at Balanced and reconnecting preserves an explicit Full choice and quality', async t => {
  const h = harness(t, {open: (_n, settings) => Promise.resolve({ok: true,
    url: 'http://127.0.0.1:8001/live.mjpg', size: settings.size, quality: settings.quality})});
  h.call('begin()'); await h.advance(0);
  assert.equal(h.openCalls[0].settings.size, 'balanced');
  assert.equal(h.openCalls[0].settings.quality, 0.5);
  h.call("shown.size = 'full'; shown.quality = 0.35");
  h.follow(liveReport({running: false, live: false, quality: 0.35})); await h.advance(0);
  assert.equal(h.openCalls[1].settings.size, 'full');
  assert.equal(h.openCalls[1].settings.quality, 0.35);
});


test('a new mirror view reopens at remembered explicit Full or Third detail', async t => {
  for (const savedSize of ['full', 'third']) {
    const h = harness(t, {savedSize, open: (_n, settings) => Promise.resolve({ok: true,
      url: 'http://127.0.0.1:8001/live.mjpg', size: settings.size, quality: settings.quality})});
    h.call('begin()'); await h.advance(0);
    assert.equal(h.openCalls[0].settings.size, savedSize);
    assert.equal(h.storageWrites.length, 0, 'opening a remembered choice does not rewrite preferences');
  }
});

test('invalid or inaccessible saved detail falls back to Balanced', async t => {
  for (const savedSize of [null, '', 'giant', 'Full', ' full ', 'constructor']) {
    const h = harness(t, {savedSize}); h.call('begin()'); await h.advance(0);
    assert.equal(h.openCalls[0].settings.size, 'balanced'); assert.equal(h.storageWrites.length, 0);
  }
  const h = harness(t, {savedSize: 'full', storageReadFails: true});
  h.call('begin()'); await h.advance(0); assert.equal(h.openCalls[0].settings.size, 'balanced');
});

test('only a successful explicit detail button selection is remembered', async t => {
  const answer = deferred();
  const h = harness(t, {savedSize: 'third', size: () => answer.promise,
    open: (_n, settings) => Promise.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: settings.size})});
  h.call('begin()'); await h.advance(0); h.buttons.find(button => button.dataset.size === 'full').click();
  await flush(); assert.deepEqual(h.sizeCalls, ['full']); assert.equal(h.storage.get('pine-mirror-size'), 'third');
  answer.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: 'full'}); await flush();
  assert.deepEqual(h.storageWrites, [['pine-mirror-size', 'full']]); assert.equal(h.call('wantSize'), 'full');
  assert.equal(h.call('auto'), false, 'manual choice continues to turn off automatic resizing');
});

test('refused or rejected explicit detail changes do not overwrite the saved preference', async t => {
  for (const size of [() => Promise.resolve({ok: false}), () => Promise.reject(new Error('IPC disconnected'))]) {
    const h = harness(t, {savedSize: 'third', size,
      open: (_n, settings) => Promise.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: settings.size})});
    h.call('begin()'); await h.advance(0); h.buttons.find(button => button.dataset.size === 'full').click(); await flush();
    assert.equal(h.storage.get('pine-mirror-size'), 'third'); assert.equal(h.storageWrites.length, 0);
    assert.equal(h.call('wantSize'), 'third'); assert.equal(h.call('shown.size'), 'third');
  }
});

test('explicitly selecting the already active detail saves it without rebuilding capture', async t => {
  const h = harness(t, {savedSize: 'third'}); h.call('begin()'); await h.advance(0);
  assert.equal(h.call('shown.size'), 'full');
  h.buttons.find(button => button.dataset.size === 'full').click(); await flush();
  assert.deepEqual(h.storageWrites, [['pine-mirror-size', 'full']]); assert.equal(h.sizeCalls.length, 0);
});

test('automatic resize and direct status reports never replace the explicit saved detail', async t => {
  const h = harness(t, {savedSize: 'third', open: (_n, settings) => Promise.resolve({ok: true,
    url: 'http://127.0.0.1:8001/live.mjpg', size: settings.size, real: {width:1340,height:800}})});
  h.call('begin()'); await h.advance(0); h.call('sharpenSoon()'); await h.advance(500);
  assert.deepEqual(h.sizeCalls, ['full']); assert.equal(h.call('shown.size'), 'full');
  assert.equal(h.storage.get('pine-mirror-size'), 'third'); assert.equal(h.call('wantSize'), 'third');
  h.follow(liveReport({size:'balanced'})); await h.advance(0);
  assert.equal(h.storage.get('pine-mirror-size'), 'third'); assert.equal(h.storageWrites.length, 0);
});

test('a deliberate detail remains usable when local storage writes are unavailable', async t => {
  const h = harness(t, {savedSize: 'third', storageWriteFails: true,
    open: (_n, settings) => Promise.resolve({ok: true, url: 'http://127.0.0.1:8001/live.mjpg', size: settings.size})});
  h.call('begin()'); await h.advance(0);
  h.buttons.find(button => button.dataset.size === 'full').click(); await flush();
  assert.equal(h.call('wantSize'), 'full'); assert.equal(h.call('shown.size'), 'full');
  assert.equal(h.storage.get('pine-mirror-size'), 'third');
});
