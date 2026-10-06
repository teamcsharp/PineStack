'use strict';
const net = require('node:net');
const {randomUUID} = require('node:crypto');
const {execFile} = require('node:child_process');
const MAX_FRAME_BYTES = 2 * 1024 * 1024;
class JpegFrames {
  constructor(onFrame) { this.onFrame = onFrame; this.spare = Buffer.alloc(0); this.length = 0; }
  feed(bytes) {
    this.spare = this.spare.length ? Buffer.concat([this.spare, bytes]) : bytes;
    for (;;) {
      if (!this.length) {
        if (this.spare.length < 4) return;
        this.length = this.spare.readUInt32BE(0);
        this.spare = this.spare.subarray(4);
        if (this.length < 4 || this.length > MAX_FRAME_BYTES) throw new Error('invalid native JPEG frame length');
      }
      if (this.spare.length < this.length) return;
      const frame = this.spare.subarray(0, this.length);
      this.spare = this.spare.subarray(this.length);
      this.length = 0;
      if (frame[0] !== 255 || frame[1] !== 216 || frame[frame.length - 2] !== 255 || frame[frame.length - 1] !== 217) throw new Error('invalid native JPEG frame');
      this.onFrame(frame);
    }
  }
}
class TabletJpegSource {
  constructor({adb, serial, lease, runFile, connect, onFrame, onFailure, streamId} = {}) {
    this.adb = adb; this.serial = serial; this.lease = lease;
    this.runFile = runFile || execFile; this.connect = connect || net.createConnection;
    this.onFrame = onFrame || (() => {}); this.onFailure = onFailure || (() => {});
    this.streamId = streamId || 'jpeg_' + randomUUID().replaceAll('-', '');
    if (!/^[A-Za-z0-9_-]{8,100}$/.test(this.streamId)) throw new Error('invalid native JPEG stream token');
    this.used = false; this.stopped = false;
    this.socket = null; this.port = 0; this.active = false; this.generation = 0; this.starting = null; this.stopping = null;
  }
  run(args) {
    return new Promise((resolve, reject) => {
      this.runFile(this.adb, ['-s', this.serial, ...args], {timeout: 6000, maxBuffer: 256 * 1024, windowsHide: true},
        (error, stdout) => error ? reject(error) : resolve(String(stdout || '').trim()));
    });
  }
  start(shape) {
    if (this.stopping || this.stopped) return Promise.reject(new Error('native JPEG capture is stopping or stopped'));
    if (this.starting) return this.starting;
    if (this.used) return Promise.reject(new Error('native JPEG capture is already started'));
    this.used = true;
    this.active = true;
    const generation = ++this.generation;
    const operation = this.begin(shape, generation);
    this.starting = operation;
    operation.finally(() => { if (this.starting === operation) this.starting = null; }).catch(() => {});
    return operation;
  }
  async begin(shape, generation) {
    const reply = await this.lease.jpegStart({width: shape.width, height: shape.height,
      jpeg_quality: Math.min(85, Math.max(35, Math.round(35 + shape.quality * 50))), fps: 12, stream_id: this.streamId});
    if (reply.ok !== true || reply.held !== true || reply.owner !== this.lease.owner ||
        reply.jpeg_running !== true || reply.jpeg_owner !== this.lease.owner ||
        reply.jpeg_socket !== 'pine_mirror' || reply.jpeg_stream_id !== this.streamId) throw new Error(reply.detail || 'the tablet did not start its bounded full-detail capture');
    if (!this.active || generation !== this.generation) return;
    const port = Number(await this.run(['forward', 'tcp:0', 'localabstract:pine_mirror']));
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('invalid tablet JPEG forwarding port');
    this.port = port;
    if (!this.active || generation !== this.generation) return;
    const parser = new JpegFrames(frame => { if (this.active && generation === this.generation) this.onFrame(frame); });
    const socket = this.connect({port, host: '127.0.0.1'});
    this.socket = socket;
    socket.setNoDelay?.(true);
    let failed = false;
    const fail = error => { if (!failed && this.active && generation === this.generation) { failed = true; this.onFailure(error); } };
    socket.on('data', bytes => {
      if (!this.active || generation !== this.generation) return;
      try { parser.feed(bytes); } catch (error) { fail(error); socket.destroy(); }
    });
    socket.on('error', fail);
    socket.on('close', () => fail(new Error('the native full-detail stream ended')));
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { socket.destroy(); reject(new Error('native JPEG connection timeout')); }, 4000);
      const done = error => { clearTimeout(timer); socket.removeListener('connect', connected); socket.removeListener('error', errored); socket.removeListener('close', closed); error ? reject(error) : resolve(); };
      const connected = () => done();
      const errored = error => done(error);
      const closed = () => done(new Error('native JPEG connection closed before opening'));
      socket.once('connect', connected); socket.once('error', errored); socket.once('close', closed);
    });
  }
  async alive() {
    if (!this.active || !this.socket || this.socket.destroyed) return false;
    const generation = this.generation, socket = this.socket;
    const reply = await this.lease.status();
    return this.active && generation === this.generation && socket === this.socket && !socket.destroyed && reply.ok === true && reply.held === true && reply.owner === this.lease.owner &&
      reply.jpeg_running === true && reply.jpeg_owner === this.lease.owner && reply.jpeg_stream_id === this.streamId;
  }
  dispose() { this.active = false; ++this.generation; this.socket?.destroy(); this.socket = null; }
  stop() {
    if (this.stopping) return this.stopping;
    if (this.stopped) return Promise.resolve();
    this.dispose();
    const operation = (async () => {
      if (this.starting) { try { await this.starting; } catch (error) { /* clean up even if ACK was lost */ } }
      try {
        const reply = await this.lease.jpegStop({stream_id: this.streamId});
        if (reply.ok !== true || reply.jpeg_running !== false || reply.jpeg_released !== true) throw new Error(reply.detail || 'the native JPEG display has not released');
        this.stopped = true;
      } finally {
        if (this.port) { const port = this.port; this.port = 0; await this.run(['forward', '--remove', 'tcp:' + port]).catch(() => {}); }
      }
    })();
    this.stopping = operation;
    operation.finally(() => { if (this.stopping === operation) this.stopping = null; }).catch(() => {});
    return operation;
  }
}
module.exports = {TabletJpegSource, JpegFrames, MAX_FRAME_BYTES};
