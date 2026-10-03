'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Run the listener's production JavaScript, without importing the server or
// contacting a station. Timers and media events are deterministic browser fakes.
const source = fs.readFileSync(path.join(__dirname, '../app.py'), 'utf8');
function between(text, first, last) {
  const from = text.indexOf(first);
  const to = text.indexOf(last, from + first.length);
  assert.ok(from >= 0 && to > from, 'production extraction boundaries exist: ' + first);
  return text.slice(from, to);
}
const streamState = between(source, 'let streamMode = AWAY;', '/* #1253: HLS WHERE IT IS NATIVE');
const streamRoad = between(source, 'function wantsHls() {', '/* #1264: the driving layout');
const playback = between(source, 'function stopEverything() {', 'function burst(anchor, up) {');
const flush = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function ranges(rows = []) {
  return {length: rows.length, start: i => rows[i][0], end: i => rows[i][1]};
}
function harness(t, options = {}) {
  let now = 100000, nextId = 1;
  const timers = new Map(), events = new Map(), documentEvents = new Map();
  const actions = new Map(), marks = [], elements = [], sourceWrites = [];
  class FakeAudio {
    constructor() {
      this._src = ''; this.paused = true; this.ended = false; this.error = null;
      this.currentTime = 0; this.readyState = 0; this.networkState = 0;
      this.playbackRate = 1; this.volume = 1; this.buffered = ranges();
      this.dataset = {}; this.style = {}; this.playCalls = 0;
      this.pauseCalls = 0; this.loadCalls = 0; elements.push(this);
    }
    get src() { return this._src; }
    set src(value) {
      this._src = value; this.currentTime = 0; this.readyState = value ? 1 : 0;
      this.error = null; this.ended = false; this.buffered = ranges();
      sourceWrites.push({at: now, value, element: this});
    }
    get currentSrc() { return this._src; }
    getAttribute(name) { return name === 'src' ? this._src || null : null; }
    setAttribute() {}
    removeAttribute(name) { if (name === 'src') this.src = ''; }
    canPlayType() { return options.hls === false ? '' : 'probably'; }
    pause() { this.pauseCalls += 1; this.paused = true; }
    load() { this.loadCalls += 1; }
    play() {
      this.playCalls += 1; this.paused = false;
      return options.play ? options.play(this, this.playCalls) : Promise.resolve();
    }
    emit(name) {
      if (name === 'playing') { this.paused = false; this.readyState = 4; }
      const handler = this['on' + name];
      if (handler) handler();
    }
  }
  const note = {textContent: ''}, button = {textContent: 'Stop'};
  const sliders = {lvMusic: {value: 100}, lvVoice: {value: 100}, lvSfx: {value: 100}};
  const document = {hidden: false, body: {appendChild() {}},
    getElementById(id) { return id === 'note' ? note : id === 'tune' ? button : sliders[id] || null; },
    createElement() { return {canPlayType: () => options.hls === false ? '' : 'probably'}; },
    addEventListener(name, fn) { documentEvents.set(name, fn); }};
  const storage = new Map();
  const context = vm.createContext({
    Audio: FakeAudio, Promise, Error, AbortController, encodeURIComponent,
    AWAY: true, GUEST: false, KEY: '', voiceRate: 0, playing: true,
    audio: null, voice: null, voiceBusy: false, voiceNowTs: 0, voiceCurrentClip: null,
    trackId: '', ducking: false, streamStartMs: 0, pineReloadOwed: false,
    listenerAudioContext: null, listenerGain() {}, applyLevels() {}, voiceAck() {},
    poll: () => Promise.resolve(), signIn: () => Promise.resolve(), linkSuspect() {},
    currentRoad: () => 'tailnet', carMark: (name, detail) => marks.push({name, detail, at: now}),
    fetch: () => Promise.resolve({status: 200, ok: true}), document,
    window: {addEventListener(name, fn) { events.set(name, fn); }},
    navigator: {onLine: true, mediaSession: {setActionHandler(name, fn) { actions.set(name, fn); }}},
    MediaMetadata: class { constructor(value) { Object.assign(this, value); } },
    sessionStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    Date: {now: () => now},
    setTimeout(fn, delay) { const id = nextId++; timers.set(id, {at: now + delay, fn, interval: 0}); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval(fn, delay) { const id = nextId++; timers.set(id, {at: now + delay, fn, interval: delay}); return id; },
    clearInterval(id) { timers.delete(id); }
  });
  vm.runInContext(streamState + '\n' + streamRoad + '\n' + playback, context, {filename: 'listener-playback-from-app.py'});
  const call = code => vm.runInContext(code, context);
  async function advance(ms) {
    const end = now + ms;
    let steps = 0;
    for (;;) {
      await flush();
      const entry = [...timers].filter(([, timer]) => timer.at <= end)
        .sort((a, b) => a[1].at - b[1].at || a[0] - b[0])[0];
      if (!entry) break;
      if (++steps > 2000) throw new Error('timer loop did not settle');
      const [id, timer] = entry;
      now = timer.at;
      if (timer.interval) timer.at += timer.interval;
      else timers.delete(id);
      timer.fn();
    }
    now = end; await flush();
  }
  async function start() {
    call('startStream(); paintMediaSession(null);'); await flush();
    return call('radio');
  }
  t.after(() => { call('playing = false; stopEverything();'); timers.clear(); });
  return {call, advance, start, actions, marks, sourceWrites, events, documentEvents, document, note,
    get radio() { return call('radio'); }, get now() { return now; }};
}

test('steering-wheel Play resumes a paused stream despite existing playing intent', async t => {
  const h = harness(t), el = await h.start();
  el.currentTime = 26; el.readyState = 4; el.buffered = ranges([[0, 56]]);
  const src = el.src, buffer = el.buffered;
  el.paused = true;
  h.actions.get('play')(); await flush();
  assert.equal(el.playCalls, 2);
  assert.equal(el.src, src); assert.equal(el.buffered, buffer);
  assert.equal(h.sourceWrites.length, 1); assert.equal(h.call('playing'), true);
});

test('visibility and online wakes preserve a healthy HLS buffer during idle stalls', async t => {
  const h = harness(t), el = await h.start();
  el.currentTime = 30; el.readyState = 4; el.buffered = ranges([[0, 60]]);
  el.emit('playing');
  await h.advance(20000);
  const src = el.src, buffer = el.buffered, plays = el.playCalls;
  h.documentEvents.get('visibilitychange')(); h.events.get('online')(); h.events.get('pageshow')();
  el.emit('stalled'); el.emit('waiting'); await flush();
  assert.equal(el.src, src); assert.equal(el.buffered, buffer);
  assert.equal(el.playCalls, plays); assert.equal(h.sourceWrites.length, 1);
});

test('wake resumes a route-paused HLS element without replacing its source', async t => {
  const h = harness(t), el = await h.start();
  el.currentTime = 12; el.readyState = 4; el.buffered = ranges([[0, 42]]);
  await h.advance(3000); el.paused = true;
  const src = el.src, buffer = el.buffered;
  h.events.get('pageshow')(); await flush();
  assert.equal(el.playCalls, 2); assert.equal(el.src, src); assert.equal(el.buffered, buffer);
  h.events.get('online')(); h.documentEvents.get('visibilitychange')(); await flush();
  assert.equal(el.playCalls, 2, 'adjacent wake events share one resume attempt');
});

test('natural playing cancels a pending reconnect before it discards the recovered buffer', async t => {
  const h = harness(t), el = await h.start();
  h.call('streamRecover("error");');
  assert.ok(h.call('streamTimer'));
  el.currentTime = 10; el.readyState = 4; el.buffered = ranges([[0, 40]]);
  el.emit('playing');
  assert.equal(h.call('streamTimer'), null);
  await h.advance(1000);
  assert.equal(h.sourceWrites.length, 1); assert.equal(el.playCalls, 1);
});

test('a rejection from an earlier source cannot reconnect over the newer stream', async t => {
  const old = deferred();
  const h = harness(t, {play: (_el, n) => n === 1 ? old.promise : Promise.resolve()});
  const el = await h.start();
  await h.advance(3000);
  el.error = {code: 2}; h.events.get('online')(); await flush();
  assert.equal(h.sourceWrites.length, 2);
  const latest = el.src;
  old.reject(new Error('the previous stream failed')); await flush();
  assert.equal(h.call('streamTimer'), null);
  await h.advance(1000);
  assert.equal(el.src, latest); assert.equal(h.sourceWrites.length, 2);
});

test('an Audio play AbortError does not create a reconnect loop', async t => {
  const aborted = Object.assign(new Error('The play request was interrupted'), {name: 'AbortError'});
  const h = harness(t, {play: () => Promise.reject(aborted)});
  const el = await h.start();
  assert.equal(h.call('streamTimer'), null);
  await h.advance(1000);
  assert.equal(h.sourceWrites.length, 1); assert.equal(el.playCalls, 1);
});

test('user Stop cancels recovery and prevents late promises and lifecycle wakes from restarting', async t => {
  const pending = deferred();
  const h = harness(t, {play: () => pending.promise}), el = await h.start();
  h.call('streamRecover("error");');
  h.actions.get('stop')();
  const plays = el.playCalls, writes = h.sourceWrites.length;
  assert.equal(h.call('playing'), false); assert.equal(el.src, '');
  assert.equal(h.call('streamTimer'), null); assert.equal(h.call('streamWatch'), null);
  pending.reject(new Error('old source failed after Stop')); await flush();
  h.events.get('online')(); h.events.get('pageshow')(); h.documentEvents.get('visibilitychange')();
  el.emit('ended'); el.emit('error'); await h.advance(60000);
  assert.equal(el.playCalls, plays); assert.equal(h.sourceWrites.length, writes);
});

test('wake reloads an errored stream and an empty stream', async t => {
  const h = harness(t), el = await h.start();
  await h.advance(3000); el.error = {code: 2}; h.events.get('online')(); await flush();
  assert.equal(h.sourceWrites.length, 2); assert.equal(el.playCalls, 2);
  assert.equal(el.error, null); assert.match(el.src, /^\/stream\.m3u8\?/);
  await h.advance(3000); el.removeAttribute('src');
  const emptyWrites = h.sourceWrites.length;
  h.events.get('pageshow')(); await flush();
  assert.equal(h.sourceWrites.length, emptyWrites + 1); assert.equal(el.playCalls, 3);
  assert.ok(el.src);
});

test('unpaused low-readyState buffering gets the 40 second watchdog runway', async t => {
  const h = harness(t), el = await h.start();
  el.currentTime = 10; el.readyState = 1;
  await h.advance(15000);
  h.events.get('online')(); h.documentEvents.get('visibilitychange')(); await flush();
  assert.equal(h.sourceWrites.length, 1); assert.equal(h.call('streamTimer'), null);
  await h.advance(30000);
  assert.equal(h.sourceWrites.length, 1); assert.equal(h.call('streamTimer'), null,
    'exactly 40 seconds since first progress sample does not discard the source');
  await h.advance(5000);
  assert.ok(h.call('streamTimer'));
  assert.equal(h.sourceWrites.length, 1);
  await h.advance(499);
  assert.equal(h.sourceWrites.length, 1);
  await h.advance(1);
  assert.equal(h.sourceWrites.length, 2);
  assert.ok(h.marks.some(mark => mark.name === 'reconnect' && /40s/.test(mark.detail.why)));
});

test('the watchdog resumes an unexpectedly paused element using its existing source', async t => {
  const h = harness(t), el = await h.start();
  el.currentTime = 15; el.readyState = 4; el.buffered = ranges([[0, 45]]); el.paused = true;
  const src = el.src, buffer = el.buffered;
  await h.advance(5000);
  assert.equal(el.playCalls, 2); assert.equal(el.src, src); assert.equal(el.buffered, buffer);
});

const recorder = fs.readFileSync(path.join(__dirname, '../frontend/car-diag.js'), 'utf8');
const diagHelpers = between(recorder, '  function audioSessionState() {', '  var MEDIA =');
const diagSnapshot = between(recorder, '  function snapshot(el, full) {', '  // ---- what else is on the link');
function diagnostics(navigator) {
  const context = vm.createContext({navigator, document: {hidden: true},
    round: (value, digits) => Number.isFinite(value) ? Number(value.toFixed(digits)) : null,
    bufferedAhead: () => 30, pagePlaying: () => true});
  vm.runInContext(diagHelpers + '\n' + diagSnapshot, context);
  context.el = {currentTime: 12, readyState: 4, networkState: 2,
    paused: true, ended: false, playbackRate: 1, error: null};
  return code => vm.runInContext(code, context);
}
test('diagnostics tolerate absent or throwing optional audioSession and retain paused versus intent', () => {
  const badNavigator = {};
  Object.defineProperty(badNavigator, 'audioSession', {get() { throw new Error('unavailable'); }});
  for (const navigator of [{}, badNavigator]) {
    const call = diagnostics(navigator);
    assert.equal(call('audioSessionState()'), null);
    for (const expression of ['mstate(el)', 'snapshot(el, false)']) {
      const state = call(expression);
      assert.equal(state.intent, true); assert.equal(state.paused, true);
      assert.equal(state.audio_session, null); assert.equal(state.rate, 1);
    }
    assert.equal(call('mstate(el).hidden'), true);
  }
});
test('diagnostics record an interrupted audio session without changing media playback', () => {
  const call = diagnostics({audioSession: {state: 'interrupted'}});
  assert.equal(call('mstate(el).audio_session'), 'interrupted');
  assert.equal(call('snapshot(el, false).audio_session'), 'interrupted');
  assert.equal(call('el.paused'), true); assert.equal(call('el.currentTime'), 12);
});


test('a genuinely ended stream reloads instead of resuming its exhausted source', async t => {
  const h = harness(t), el = await h.start();
  await h.advance(3000);
  el.ended = true; el.paused = true; el.emit('ended');
  assert.ok(h.call('streamTimer'));
  h.actions.get('play')(); await flush();
  assert.equal(h.sourceWrites.length, 2); assert.equal(el.playCalls, 2);
  assert.equal(el.ended, false); assert.equal(h.call('streamTimer'), null);
  await h.advance(1000);
  assert.equal(h.sourceWrites.length, 2);
});

test('a stale rejection from an earlier same-source play cannot undo wheel resume', async t => {
  const old = deferred();
  const h = harness(t, {play: (_el, n) => n === 1 ? old.promise : Promise.resolve()});
  const el = await h.start();
  el.paused = true; el.readyState = 4;
  h.actions.get('play')(); el.emit('playing'); await flush();
  old.reject(new Error('earlier output interruption')); await flush();
  assert.equal(h.call('streamTimer'), null);
  await h.advance(1000);
  assert.equal(h.sourceWrites.length, 1); assert.equal(el.playCalls, 2);
});

test('the diagnostic microphone owns its pause until recording has finished', async t => {
  const h = harness(t), el = await h.start();
  h.call('window.PineCarDiag = {state: () => ({voice: {recording: true}})};');
  el.currentTime = 15; el.readyState = 4; el.buffered = ranges([[0, 45]]); el.paused = true;
  const src = el.src, buffer = el.buffered;
  h.actions.get('play')(); h.events.get('pageshow')(); await h.advance(10000);
  assert.equal(el.playCalls, 1); assert.equal(el.src, src); assert.equal(el.buffered, buffer);
  assert.equal(h.call('streamTimer'), null);
  h.call('window.PineCarDiag = {state: () => ({voice: {recording: false}})};');
  h.events.get('pageshow')(); await flush();
  assert.equal(el.playCalls, 2); assert.equal(el.src, src); assert.equal(el.buffered, buffer);
});

