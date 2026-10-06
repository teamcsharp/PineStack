'use strict';
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {test} = require('node:test');
const path = require('node:path');
const {TabletJpegSource, JpegFrames, MAX_FRAME_BYTES} = require(path.join(__dirname, '..', 'desktop', 'tablet-jpeg-source.cjs'));

function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return {promise, resolve, reject}; }
function tick() { return new Promise(resolve => setImmediate(resolve)); }
function frame(body = Buffer.from([1, 2, 3])) { return Buffer.concat([Buffer.from([255, 216]), body, Buffer.from([255, 217])]); }
function packet(jpeg) { const head = Buffer.alloc(4); head.writeUInt32BE(jpeg.length); return Buffer.concat([head, jpeg]); }
class FakeSocket extends EventEmitter {
  constructor() { super(); this.destroyed = false; this.noDelay = false; }
  setNoDelay(value) { this.noDelay = value; }
  destroy() { if (this.destroyed) return; this.destroyed = true; queueMicrotask(() => this.emit('close')); }
}
function harness(options = {}) {
  const calls = [], sockets = [], pictures = [], failures = [];
  let port = 41000, activeShape = null;
  const lease = {
    owner: 'pine-owner',
    async jpegStart(shape) { activeShape = shape; calls.push(['jpegStart', shape]); return {ok: true, held: true, owner: this.owner, jpeg_running: true, jpeg_owner: this.owner, jpeg_socket: 'pine_mirror', jpeg_stream_id: shape.stream_id}; },
    async jpegStop(options) { calls.push(['jpegStop', options]); return {ok: true, jpeg_running: false, jpeg_released: true}; },
    async status() { calls.push(['status']); return {ok: true, held: true, owner: this.owner, jpeg_running: true, jpeg_owner: this.owner, jpeg_stream_id: activeShape?.stream_id}; }
  };
  Object.assign(lease, options.lease);
  const runFile = options.runFile || ((exe, args, settings, callback) => {
    calls.push(['adb', exe, args, settings]);
    queueMicrotask(() => callback(null, args.includes('--remove') ? '' : String(port++)));
  });
  const connect = options.connect || (address => {
    calls.push(['connect', address]); const socket = new FakeSocket(); sockets.push(socket);
    queueMicrotask(() => socket.emit('connect')); return socket;
  });
  const makeSource = () => new TabletJpegSource({adb: 'adb.exe', serial: 'chosen-tablet', lease, runFile, connect, streamId: options.streamId,
    onFrame: jpeg => pictures.push(Buffer.from(jpeg)), onFailure: error => failures.push(error)});
  const source = makeSource();
  return {source, makeSource, lease, calls, sockets, pictures, failures};
}
const shape = {width: 1340, height: 800, quality: 0.5};

test('length framing survives every split and embedded JPEG end markers', () => {
  const first = frame(Buffer.from([5, 255, 217, 6])), second = frame(Buffer.from([7]));
  const bytes = Buffer.concat([packet(first), packet(second)]);
  for (let split = 0; split <= bytes.length; split++) {
    const seen = [], parser = new JpegFrames(value => seen.push(Buffer.from(value)));
    parser.feed(bytes.subarray(0, split)); parser.feed(bytes.subarray(split));
    assert.deepEqual(seen, [first, second], 'split ' + split);
  }
  const seen = [], parser = new JpegFrames(value => seen.push(Buffer.from(value)));
  for (const byte of bytes) parser.feed(Buffer.from([byte]));
  assert.deepEqual(seen, [first, second]);
});

test('parser rejects impossible sizes before receiving a payload and malformed JPEG bounds', () => {
  for (const length of [0, 1, 3, MAX_FRAME_BYTES + 1, 0xffffffff]) {
    const header = Buffer.alloc(4); header.writeUInt32BE(length);
    assert.throws(() => new JpegFrames(() => assert.fail('unexpected frame')).feed(header), /frame length/);
  }
  for (const bad of [Buffer.from([0, 216, 255, 217]), Buffer.from([255, 216, 255, 0])])
    assert.throws(() => new JpegFrames(() => assert.fail('unexpected frame')).feed(packet(bad)), /invalid native JPEG frame/);
});

test('source starts once, preserves full dimensions, and delivers framed JPEGs', async () => {
  const h = harness();
  const first = h.source.start(shape), same = h.source.start(shape);
  assert.equal(first, same);
  await first;
  assert.deepEqual(h.calls[0], ['jpegStart', {width: 1340, height: 800, jpeg_quality: 60, fps: 12, stream_id: h.source.streamId}]);
  assert.deepEqual(h.calls.find(call => call[0] === 'adb')[2], ['-s', 'chosen-tablet', 'forward', 'tcp:0', 'localabstract:pine_mirror']);
  assert.equal(h.calls.find(call => call[0] === 'adb')[3].windowsHide, true);
  const jpeg = frame(); h.sockets[0].emit('data', packet(jpeg));
  assert.deepEqual(h.pictures, [jpeg]); assert.equal(h.sockets[0].noDelay, true);
  assert.equal(await h.source.alive(), true);
  await h.source.stop();
});

test('capture quality is bounded independently of full capture dimensions', async () => {
  for (const [quality, expected] of [[-10, 35], [10, 85]]) {
    const h = harness(); await h.source.start({...shape, quality});
    assert.equal(h.calls[0][1].jpeg_quality, expected); await h.source.stop();
  }
});

test('foreign or incomplete capture acknowledgement cannot create an ADB forward', async () => {
  for (const changes of [{ok: false}, {held: false}, {owner: 'foreign'}, {jpeg_running: false}, {jpeg_owner: 'foreign'}, {jpeg_socket: 'another_socket'}, {jpeg_stream_id: 'foreign_stream'}]) {
    const h = harness({lease: {async jpegStart(shape) { return {ok: true, held: true, owner: this.owner, jpeg_running: true, jpeg_owner: this.owner, jpeg_socket: 'pine_mirror', jpeg_stream_id: shape.stream_id, ...changes}; }}});
    await assert.rejects(h.source.start(shape));
    assert.equal(h.calls.some(call => call[0] === 'adb'), false);
    await h.source.stop();
  }
});

test('close waits for late capture acknowledgement and never connects a canceled start', async () => {
  const answer = deferred(), h = harness({lease: {jpegStart() { return answer.promise; }}});
  const opening = h.source.start(shape), closing = h.source.stop();
  let closed = false; closing.then(() => { closed = true; }); await tick(); assert.equal(closed, false);
  answer.resolve({ok: true, held: true, owner: h.lease.owner, jpeg_running: true, jpeg_owner: h.lease.owner, jpeg_socket: 'pine_mirror', jpeg_stream_id: h.source.streamId});
  await opening; await closing;
  assert.equal(h.calls.some(call => call[0] === 'connect'), false);
  assert.equal(h.calls.filter(call => call[0] === 'jpegStop').length, 1);
});

test('close removes exactly its late allocated forward before completing', async () => {
  const forward = deferred(), calls = [];
  const h = harness({runFile(exe, args, settings, callback) {
    calls.push(args);
    if (args.includes('--remove')) queueMicrotask(() => callback(null, ''));
    else forward.promise.then(value => callback(null, value));
  }});
  const opening = h.source.start(shape); await tick();
  const closing = h.source.stop(); forward.resolve('41414');
  await opening; await closing;
  assert.equal(h.sockets.length, 0);
  assert.deepEqual(calls, [
    ['-s', 'chosen-tablet', 'forward', 'tcp:0', 'localabstract:pine_mirror'],
    ['-s', 'chosen-tablet', 'forward', '--remove', 'tcp:41414']
  ]);
});

test('late old socket frames and failures cannot enter a replacement capture', async () => {
  const h = harness(); await h.source.start(shape); const old = h.sockets[0];
  await h.source.stop(); const oldSource = h.source; h.source = h.makeSource();
  assert.notEqual(h.source.streamId, oldSource.streamId);
  await h.source.start(shape); const fresh = h.sockets[1];
  old.emit('data', packet(frame(Buffer.from([1])))); old.emit('error', new Error('late old failure')); old.emit('close');
  fresh.emit('data', packet(frame(Buffer.from([2]))));
  assert.deepEqual(h.pictures, [frame(Buffer.from([2]))]); assert.equal(h.failures.length, 0);
  await h.source.stop();
});

test('malformed live frame fails the producer and destroys its socket', async () => {
  const h = harness(); await h.source.start(shape);
  h.sockets[0].emit('data', packet(Buffer.from([0, 216, 255, 217])));
  assert.equal(h.sockets[0].destroyed, true); assert.match(h.failures[0].message, /invalid native JPEG frame/);
  await h.source.stop();
});

test('unknown native release remains an error but owned forward is still removed', async () => {
  const h = harness({lease: {async jpegStop() { return {ok: true, jpeg_running: false, jpeg_released: false, detail: 'release pending'}; }}});
  await h.source.start(shape);
  const one = h.source.stop(), two = h.source.stop(); assert.equal(one, two);
  await assert.rejects(one, /release pending/);
  assert.equal(h.source.port, 0); assert.equal(h.source.socket, null);
  assert.equal(h.calls.filter(call => call[0] === 'adb' && call[2].includes('--remove')).length, 1);
});

test('a rejected native stop acknowledgement also removes only its owned forward', async () => {
  const h = harness({lease: {async jpegStop() { throw new Error('broadcast timeout'); }}});
  await h.source.start(shape); await assert.rejects(h.source.stop(), /broadcast timeout/);
  assert.equal(h.calls.filter(call => call[0] === 'adb' && call[2].includes('--remove')).length, 1);
});

test('late alive reply cannot report a capture healthy after it was closed', async () => {
  const answer = deferred(), h = harness({lease: {status() { return answer.promise; }}});
  await h.source.start(shape); const checking = h.source.alive();
  await h.source.stop();
  answer.resolve({ok: true, held: true, owner: h.lease.owner, jpeg_running: true, jpeg_owner: h.lease.owner, jpeg_stream_id: h.source.streamId});
  assert.equal(await checking, false);
});

test('the one-shot source rejects reopening during stop and cannot kill a later stream', async () => {
  const release = deferred(), h = harness();
  await h.source.start(shape);
  const oldSource = h.source;
  h.lease.jpegStop = options => { h.calls.push(['jpegStop', options]); return release.promise; };
  const closing = oldSource.stop(); await tick();
  await assert.rejects(oldSource.start(shape), /stopping or stopped/);
  assert.equal(h.calls.filter(call => call[0] === 'jpegStart').length, 1);
  release.resolve({ok: true, jpeg_running: false, jpeg_released: true}); await closing;
  await assert.rejects(oldSource.start(shape), /stopping or stopped/);
  const newSource = h.makeSource(); await newSource.start(shape);
  const stopsBefore = h.calls.filter(call => call[0] === 'jpegStop').length;
  await oldSource.stop();
  assert.equal(h.calls.filter(call => call[0] === 'jpegStop').length, stopsBefore, 'retired source cannot send another native stop');
  assert.equal(newSource.active, true); assert.equal(newSource.port, 41001);
  assert.notEqual(oldSource.streamId, newSource.streamId);
  assert.deepEqual(h.calls.find(call => call[0] === 'jpegStop')[1], {stream_id: oldSource.streamId});
  await newSource.stop();
});

test('starting an already connected source rejects without leaking another socket or forward', async () => {
  const h = harness(); await h.source.start(shape);
  await assert.rejects(h.source.start(shape), /already started/);
  assert.equal(h.sockets.length, 1); assert.equal(h.calls.filter(call => call[0] === 'jpegStart').length, 1);
  await h.source.stop();
});

test('alive rejects a foreign stream token under the same desktop owner', async () => {
  const h = harness({lease: {async status() { return {ok: true, held: true, owner: this.owner, jpeg_running: true, jpeg_owner: this.owner, jpeg_stream_id: 'another_stream'}; }}});
  await h.source.start(shape); assert.equal(await h.source.alive(), false); await h.source.stop();
});

test('invalid stream tokens are rejected before any native IPC', () => {
  for (const streamId of ['tiny', 'bad token!', 'x'.repeat(101)])
    assert.throws(() => harness({streamId}), /stream token/);
});
