'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/script-page.js'), 'utf8');
const begin = source.indexOf('  var MV_LV_MAX_BYTES = ');
const end = source.indexOf('  function mvLevelsAt(', begin);
assert.ok(begin >= 0 && end > begin, 'exercise the actual waveform queue functions');
const queueSource = source.slice(begin, end);
const flush = async () => { for (let i = 0; i < 24; i += 1) await Promise.resolve(); };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function response(sid, body) {
  const bytes = new ArrayBuffer(100); bytes.sid = sid;
  return {ok: true, status: 206, headers: {get() { return '100'; }},
    arrayBuffer() { return body ? body.promise : Promise.resolve(bytes); }};
}
function harness(options = {}) {
  const timers = new Map(), requests = [], decodes = [], computed = [], shapes = [];
  let clock = 0, key = 0, active = 0, peak = 0;
  class OfflineAudioContext {
    constructor(...args) { shapes.push(args); }
    decodeAudioData(bytes, ok, bad) {
      const wait = deferred(); active += 1; peak = Math.max(peak, active);
      const item = {sid: bytes.sid, resolve() { active -= 1; wait.resolve({sid: bytes.sid}); },
        reject(error = new Error('bad audio')) { active -= 1; wait.reject(error); }};
      decodes.push(item);
      if (options.callbacks) { wait.promise.then(ok, bad); return; }
      return wait.promise;
    }
  }
  const root = {OfflineAudioContext,
    fetch(url, init) { requests.push({url, init}); return options.fetch ? options.fetch(url, init) : Promise.resolve(response(url)); }};
  if (options.abort !== false) root.AbortController = AbortController;
  const context = vm.createContext({mv: {}, root, stationUrl: value => value, Promise, ArrayBuffer,
    setTimeout(fn, delay) { const id = ++key; timers.set(id, {fn, at: clock + delay, delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    mvLevelsCompute(level, buffer) { computed.push(buffer.sid); if (options.compute) return options.compute(level, buffer);
      level.ready = true; return Promise.resolve(level); }});
  vm.runInContext(queueSource, context);
  function ask(sid) { context.sid = sid; vm.runInContext('mvLevelsAsk(sid, sid)', context); }
  async function advance(ms) {
    const until = clock + ms;
    for (;;) {
      const next = [...timers].filter(([,timer]) => timer.at <= until).sort((a,b) => a[1].at - b[1].at)[0];
      if (!next) break;
      clock = next[1].at; timers.delete(next[0]); next[1].fn(); await flush();
    }
    clock = until; await flush();
  }
  return {context, root, ask, advance, requests, decodes, computed, shapes, timers,
    get active() { return active; }, get peak() { return peak; }};
}

test('canonical queue and tablet APK asset match', () => {
  const asset = fs.readFileSync(path.join(__dirname, '../app/src/main/assets/pine-views/script-page.js'), 'utf8');
  const start = asset.indexOf('  var MV_LV_MAX_BYTES = '), stop = asset.indexOf('  function mvLevelsAt(', start);
  assert.equal(asset.slice(start, stop).replace(/\r\n/g, '\n'), queueSource.replace(/\r\n/g, '\n'));
});

test('an uncancellable decode keeps its slot after the deadline and skips late computation', async () => {
  const h = harness(); h.ask('first'); await h.advance(0);
  h.ask('second'); await h.advance(0);
  assert.equal(h.active, 1);
  await h.advance(30250);
  assert.equal(h.context.mv.levelBusy.sid, 'first');
  assert.equal(h.context.mv.levels.first.failed, 'timed out');
  assert.equal(h.requests[0].init.signal.aborted, true);
  assert.equal(h.requests.length, 1);
  assert.equal(h.active, 1);
  h.decodes[0].resolve(); await flush();
  assert.deepEqual(h.computed, []);
  await h.advance(250);
  assert.equal(h.decodes[1].sid, 'second');
  assert.equal(h.peak, 1);
  h.decodes[1].resolve(); await flush();
  assert.deepEqual(h.computed, ['second']);
  assert.equal(h.context.mv.levelBusy, null);
});

test('an aborted fetch settles before the next job and creates no decoder', async () => {
  const h = harness({fetch(url, init) {
    if (url !== 'blocked') return Promise.resolve(response(url));
    return new Promise((resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('The operation was aborted', 'AbortError')), {once:true}));
  }});
  h.ask('blocked'); await h.advance(0); h.ask('next'); await h.advance(0);
  await h.advance(30000);
  assert.equal(h.context.mv.levels.blocked.failed, 'timed out');
  assert.equal(h.context.mv.levelBusy, null);
  assert.equal(h.decodes.length, 0);
  await h.advance(250);
  assert.equal(h.decodes[0].sid, 'next');
  h.decodes[0].resolve(); await flush();
});

test('a late fetch that ignores cancellation cannot start decoding', async () => {
  const late = deferred(); const h = harness({fetch() { return late.promise; }});
  h.ask('late'); await h.advance(0); await h.advance(30000);
  assert.equal(h.context.mv.levelBusy.sid, 'late');
  late.resolve(response('late')); await flush();
  assert.equal(h.decodes.length, 0);
  assert.equal(h.context.mv.levels.late.failed, 'timed out');
  assert.equal(h.context.mv.levelBusy, null);
});

test('a body arriving after the deadline cannot start decoding without AbortController', async () => {
  const body = deferred(); const h = harness({abort:false, fetch(url) { return Promise.resolve(response(url, body)); }});
  h.ask('late-body'); await h.advance(0); await h.advance(30000);
  const bytes = new ArrayBuffer(100); bytes.sid = 'late-body'; body.resolve(bytes); await flush();
  assert.equal(h.decodes.length, 0);
  assert.equal(h.context.mv.levelBusy, null);
  assert.equal(h.context.mv.levels['late-body'].failed, 'timed out');
});

test('computing retains its slot through timeout until the computation settles', async () => {
  const work = deferred(); const h = harness({compute() { return work.promise; }});
  h.ask('first'); await h.advance(0); h.ask('second'); await h.advance(0);
  h.decodes[0].resolve(); await flush();
  assert.deepEqual(h.computed, ['first']);
  await h.advance(30250);
  assert.equal(h.context.mv.levelBusy.sid, 'first');
  assert.equal(h.requests.length, 1);
  work.resolve(); await flush(); await h.advance(250);
  assert.equal(h.decodes[1].sid, 'second');
  h.decodes[1].reject(); await flush();
});

test('the queue remains bounded, newest first, and dropped jobs can be requested again', async () => {
  const h = harness(); h.ask('active'); await h.advance(0);
  for (const sid of ['b','c','d','e']) h.ask(sid);
  await h.advance(0);
  assert.equal(h.context.mv.levelQ.length, 3);
  assert.equal(h.context.mv.levels.b, undefined);
  h.decodes[0].resolve(); await flush(); await h.advance(250);
  assert.equal(h.decodes[1].sid, 'e');
  h.decodes[1].resolve(); await flush(); await h.advance(250);
  assert.equal(h.decodes[2].sid, 'd');
  h.decodes[2].resolve(); await flush(); await h.advance(250);
  assert.equal(h.decodes[3].sid, 'c');
  h.decodes[3].resolve(); await flush(); h.ask('b'); await h.advance(0);
  assert.equal(h.decodes[4].sid, 'b');
  h.decodes[4].resolve(); await flush();
  assert.equal(h.peak, 1);
  assert.equal(h.context.mv.levelBusy, null);
  assert.deepEqual(h.shapes[0], [1, 1, 22050]);
  assert.equal(h.requests[0].init.headers.Range, 'bytes=0-1999999');
});

test('callback-only decoding settles once and clears its deadline', async () => {
  const h = harness({callbacks:true}); h.ask('callback'); await h.advance(0);
  h.decodes[0].resolve(); await flush();
  assert.deepEqual(h.computed, ['callback']);
  assert.equal(h.context.mv.levelBusy, null);
  assert.equal([...h.timers.values()].filter(timer => timer.delay === 30000).length, 0);
  await h.advance(30000);
  assert.equal(h.context.mv.levels.callback.failed, '');
});

test('synchronous fetch failures release the slot and allow the next queued job', async () => {
  const h = harness({fetch(url) { if (url === 'bad') throw new Error('network unavailable'); return Promise.resolve(response(url)); }});
  h.ask('bad'); h.ask('next'); await h.advance(0);
  assert.equal(h.decodes[0].sid, 'next');
  h.decodes[0].resolve(); await flush(); await h.advance(250);
  assert.equal(h.context.mv.levels.bad.failed, 'network unavailable');
  assert.equal(h.context.mv.levelBusy, null);
});

test('decode failure keeps its original failure and releases the next job normally', async () => {
  const h = harness(); h.ask('bad'); await h.advance(0); h.ask('next'); await h.advance(0);
  h.decodes[0].reject(new Error('unsupported clip')); await flush();
  assert.equal(h.context.mv.levels.bad.failed, 'unsupported clip');
  await h.advance(250); assert.equal(h.decodes[1].sid, 'next');
  h.decodes[1].resolve(); await flush();
  assert.equal(h.peak, 1);
});