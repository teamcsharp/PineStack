'use strict';
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {test} = require('node:test');
const {Mirror} = require('../desktop/tablet-mirror.cjs');
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function tick() { return new Promise(resolve => setImmediate(resolve)); }
function jpeg(value = 3) { return Buffer.from([255, 216, value, 255, 217, value, 255, 217]); }
function harness({start, stop, alive = true} = {}) {
  const calls = [], sources = [];
  const lease = {
    owner: 'mirror-test-owner',
    async acquire() { calls.push('acquire'); return {ok: true, held: true, owner: this.owner, video_running: false, video_released: true}; },
    async renew() { return {ok: true}; },
    async release() { calls.push('release'); return {ok: true, held: false}; },
    async status() { assert.fail('Full JPEG cleanup must use token-checked source stop, even without generic status'); }
  };
  const mirror = new Mirror({adb: 'chosen-adb', serial: 'chosen-tablet', encoderLease: lease,
    spawn() { calls.push('spawn'); assert.fail('Full JPEG must not allocate screenrecord or ffmpeg'); },
    execFile() { assert.fail('No hardware-recorder command belongs on Full JPEG path'); },
    jpegSourceFactory(options) {
      const source = {options, opening: null, disposed: false,
        start(shape) { this.shape = shape; calls.push('source-start'); this.opening = start ? start.promise : Promise.resolve(); return this.opening; },
        async stop() { calls.push('source-stop'); try { await this.opening; } catch (_) { } if (stop) await stop.promise; calls.push('source-stopped'); },
        dispose() { calls.push('dispose'); this.disposed = true; },
        async alive() { calls.push('source-alive'); return alive; }
      };
      sources.push(source); return source;
    }});
  mirror.connect = async () => { calls.push('connect'); };
  mirror.real = {width: 1340, height: 800}; mirror.shape.size = 'full'; mirror.shape.quality = 0.5;
  mirror.running = true;
  return {mirror, calls, sources, lease};
}
function viewer(mirror) {
  const request = new EventEmitter(); request.url = '/live.mjpg';
  request.socket = {setNoDelay() {}, setKeepAlive() {}, setTimeout() {}};
  const response = new EventEmitter(); response.chunks = []; response.ends = 0;
  response.writeHead = (code, headers) => { response.code = code; response.headers = headers; };
  response.write = bytes => { response.chunks.push(Buffer.from(bytes)); return true; };
  response.end = () => { response.ends++; response.writableEnded = true; response.emit('close'); };
  mirror.serve(request, response); return {request, response};
}

test('Full mirror keeps every panel pixel and bypasses both hardware recorder and desktop decoder', async () => {
  const h = harness(); await h.mirror.pipe();
  assert.equal(h.sources.length, 1); assert.deepEqual(h.sources[0].shape, {width: 1340, height: 800, quality: 0.5});
  assert.equal(h.sources[0].options.lease, h.lease);
  assert.equal(h.mirror.record, null); assert.equal(h.mirror.convert, null); assert.equal(h.calls.includes('spawn'), false);
  assert.equal(h.mirror.where().capture, 'jpeg'); assert.equal(h.mirror.where().captureFps, 12);
  assert.equal(h.mirror.where().bitrate, 0); assert.equal(h.mirror.how().bitrate, 0);
  assert.deepEqual(h.mirror.where().real, {width: 1340, height: 800});
  assert.equal(await h.mirror.recorderAlive(), true);
  await h.mirror.closeGently();
});

test('Full native frames reach the existing multipart viewer intact, including embedded end marker', async () => {
  const h = harness(); await h.mirror.pipe(); const v = viewer(h.mirror);
  const frame = jpeg(9); h.sources[0].options.onFrame(frame);
  assert.deepEqual(h.mirror.latest, frame); assert.equal(h.mirror.frames, 1);
  assert.equal(v.response.code, 200); assert.equal(v.response.chunks.length, 1);
  const wire = v.response.chunks[0]; assert.ok(wire.includes(frame));
  assert.match(wire.toString('latin1'), /Content-Length: 8\r\n/);
  frame[2] = 55; assert.equal(h.mirror.latest[2], 9, 'fanout owns its immutable current picture');
  await h.mirror.closeGently();
});

test('gentle close waits for late native startup, stops its resources, then disposes and releases lease', async () => {
  const start = deferred(), h = harness({start}); const opening = h.mirror.pipe(); await tick();
  assert.equal(h.sources.length, 1);
  const closing = h.mirror.closeGently(); await tick();
  assert.equal(h.calls.includes('release'), false); assert.equal(h.calls.includes('dispose'), false);
  h.sources[0].options.onFrame(jpeg()); assert.equal(h.mirror.frames, 0, 'closed generation rejects late first image');
  start.resolve(); await opening; await closing;
  assert.ok(h.calls.indexOf('source-stopped') < h.calls.indexOf('dispose'));
  assert.ok(h.calls.indexOf('dispose') < h.calls.indexOf('release'));
  assert.equal(h.mirror.jpegSource, null); assert.equal(h.mirror.running, false); assert.equal(h.mirror.retryTimer, null);
  h.sources[0].options.onFailure(new Error('old connection closed')); assert.equal(h.mirror.retryTimer, null);
});

test('a close during pending lease acquisition never starts a native capture', async () => {
  const acquisition = deferred(), h = harness(); h.lease.acquire = () => acquisition.promise;
  const opening = h.mirror.pipe(); await tick();
  const closing = h.mirror.closeGently(); await tick(); assert.equal(h.calls.includes('release'), false);
  acquisition.resolve({ok: true, held: true, owner: h.lease.owner, video_running: false, video_released: true});
  await opening; await closing;
  assert.equal(h.sources.length, 0); assert.equal(h.calls.includes('release'), true);
});

test('Full rebuild waits for native cleanup while retaining the same HTTP viewer and server', async () => {
  const stop = deferred(), h = harness({stop}); await h.mirror.pipe();
  const server = {close() {}}; h.mirror.server = server; h.mirror.port = 45123;
  const before = h.mirror.where(), v = viewer(h.mirror), old = h.sources[0];
  old.options.onFrame(jpeg(1)); h.mirror.rebuild('connection dropped'); await tick();
  assert.equal(h.mirror.server, server); assert.equal(h.mirror.watchers.has(v.response), true); assert.equal(v.response.ends, 0);
  assert.equal(h.mirror.retryTimer, null); assert.equal(h.sources.length, 1);
  old.options.onFrame(jpeg(2)); old.options.onFailure(new Error('stale failure'));
  assert.equal(h.mirror.frames, 1); assert.equal(h.mirror.restarts, 1);
  stop.resolve(); if (h.mirror.stopping) await h.mirror.stopping; await tick();
  assert.ok(h.mirror.retryTimer);
  // Drive the scheduled retry directly after establishing the real stop barrier.
  clearTimeout(h.mirror.retryTimer); h.mirror.retryTimer = null; h.mirror.rebuilding = false;
  await h.mirror.pipe();
  assert.equal(h.sources.length, 2); assert.equal(h.mirror.where().url, before.url); assert.equal(h.mirror.server, server);
  assert.equal(v.response.ends, 0); h.sources[1].options.onFrame(jpeg(3));
  assert.equal(h.mirror.frames, 2); assert.equal(v.response.chunks.length, 2);
  old.options.onFrame(jpeg(4)); old.options.onFailure(new Error('old retry callback'));
  assert.equal(h.mirror.frames, 2); assert.equal(h.mirror.restarts, 1);
  await h.mirror.closeGently();
});

test('Full quiet-screen health probes the JPEG source instead of an encoder process', async () => {
  const h = harness(); await h.mirror.pipe(); h.sources[0].options.onFrame(jpeg());
  h.mirror.lastFrameAt = Date.now() - 6000;
  const restarts = h.mirror.restarts; h.mirror.health(Date.now()); await tick();
  assert.equal(h.calls.includes('source-alive'), true); assert.equal(h.mirror.still, true); assert.equal(h.mirror.restarts, restarts);
  await h.mirror.closeGently();
});
