/* The M9's vendor H.264 encoder panics if replay and screenrecord overlap.
 * Borrow replay's video encoder with an acknowledged native lease. This does
 * not touch station audio, audio capture, the replay history, or camera Wi-Fi. */
'use strict';
const { execFile: systemExecFile } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const { performance } = require('node:perf_hooks');
const ACTION = 'com.pinebox.kiosk.action.MIRROR_ENCODER_LEASE';
const RECEIVER = 'com.pinebox.kiosk/.replay.MirrorLeaseReceiver';
const CALL_TIMEOUT_MS = 12000;
const RENEW_RETRY_BUDGET_MS = CALL_TIMEOUT_MS + 1000;

function parseReply(output) {
  const line = String(output || '').split(/\r?\n/).find((s) => /Broadcast completed:/.test(s));
  if (!line) throw new Error('the tablet did not acknowledge an encoder lease');
  const match = line.match(/Broadcast completed:\s*result=(-?\d+),\s*data="(.*)"(?:,\s*extras:.*)?\s*$/);
  if (!match) throw new Error('the tablet returned no encoder lease status');
  let value;
  try { value = JSON.parse(match[2]); }
  catch (error) {
    try { value = JSON.parse(JSON.parse('"' + match[2] + '"')); }
    catch (bad) { throw new Error('the tablet returned unreadable encoder lease status'); }
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid encoder lease status');
  if (Number(match[1]) !== 0) value.ok = false;
  return value;
}

class EncoderLease {
  constructor({ adb, serial, execFile, owner, ttlMs = 60000, now } = {}) {
    if (!adb || !serial) throw new Error('an ADB path and tablet serial are required');
    this.adb = adb;
    this.serial = serial;
    this.execFile = execFile || systemExecFile;
    this.owner = owner || 'mirror_' + randomUUID().replaceAll('-', '');
    if (!/^[A-Za-z0-9_-]{8,100}$/.test(this.owner)) throw new Error('invalid mirror lease owner');
    this.ttlMs = Math.min(120000, Math.max(15000, Number(ttlMs) || 60000));
    // Deadlines belong to this instance's elapsed clock, not the calendar.
    this.now = now || (() => performance.now());
    this.confirmedUntil = 0;
    this.last = null;
    this.generation = 0;
  }

  remainingMs() { return Math.max(0, this.confirmedUntil - this.now()); }
  acquire() { return this.call('acquire'); }
  async renew() {
    const generation = Number.isSafeInteger(this.generation) ? this.generation : 0;
    const confirmedUntil = this.confirmedUntil;
    const reply = await this.call('renew');
    if (reply.ok === true || reply.uncertain !== true) return reply;
    // A lost ACK cannot invent more lease time. Use only the deadline we
    // already verified, leaving room for one 12s call and its 1s guard.
    if (generation !== this.generation || confirmedUntil !== this.confirmedUntil ||
        confirmedUntil <= 0 || this.remainingMs() <= RENEW_RETRY_BUDGET_MS) return reply;
    return this.call('renew');
  }
  release() { return this.call('release'); }
  status() { return this.call('status'); }
  jpegStart(options) { return this.call('jpeg_start', options); }
  jpegStop(options) { return this.call('jpeg_stop', options); }

  async call(operation, extra = {}) {
    const started = this.now();
    if (!Number.isSafeInteger(this.generation)) this.generation = 0;
    const changesLease = operation === 'acquire' || operation === 'release';
    const generation = changesLease ? ++this.generation : this.generation;
    const args = ['-s', this.serial, 'shell', 'am', 'broadcast', '-n', RECEIVER,
      '-a', ACTION, '--es', 'operation', operation, '--es', 'owner', this.owner,
      '--el', 'ttl_ms', String(Math.round(this.ttlMs))];
    if (extra.stream_id != null) {
      if (!/^[A-Za-z0-9_-]{8,100}$/.test(String(extra.stream_id))) return {ok: false, uncertain: false, detail: 'invalid native JPEG stream token'};
      args.push('--es', 'stream_id', String(extra.stream_id));
    }
    for (const key of ['width', 'height', 'jpeg_quality', 'fps']) {
      if (extra[key] == null) continue;
      const value = Number(extra[key]);
      if (!Number.isFinite(value)) return {ok: false, uncertain: false, detail: 'invalid native JPEG parameter'};
      args.push('--ei', key, String(Math.round(value)));
    }
    try {
      const { output, commandError } = await new Promise((resolve, reject) => {
        try {
          this.execFile(this.adb, args,
            { timeout: CALL_TIMEOUT_MS, maxBuffer: 256 * 1024, windowsHide: true },
            (error, stdout, stderr) => resolve({
              output: String(stdout || '') + String(stderr || ''), commandError: error
            }));
        } catch (error) { reject(error); }
      });
      let reply;
      try { reply = parseReply(output); }
      catch (error) { throw commandError || error; }
      // Preserve a readable refusal or invalid ownership proof even when am
      // exits nonzero. Those are definitive, so renewal must not retry them.
      if (reply.ok !== true) return { ...reply, ok: false, uncertain: false,
        detail: reply.detail || 'the tablet refused the encoder lease' };
      if ((changesLease || operation === 'renew') && generation !== this.generation) {
        return { ...reply, ok: false, uncertain: false,
          detail: 'the encoder lease request was superseded' };
      }
      let left;
      if (operation === 'acquire' || operation === 'renew') {
        left = Number(reply.expires_in_ms) - Math.max(0, this.now() - started);
        if (reply.held !== true || reply.owner !== this.owner || reply.video_running !== false ||
            reply.video_released !== true || !Number.isFinite(left) || left < 5000) {
          return { ...reply, ok: false, uncertain: false,
            detail: 'the tablet did not confirm a released replay encoder and a current lease' };
        }
      } else if (operation === 'release') {
        if (reply.held !== false) return { ...reply, ok: false, uncertain: false,
          detail: 'the tablet encoder hold has not released' };
      }
      // An apparent success followed by transport failure is not confirmation.
      if (commandError) throw commandError;
      if (operation === 'acquire' || operation === 'renew') {
        this.confirmedUntil = this.now() + left;
      } else if (operation === 'release') {
        this.confirmedUntil = 0;
      }
      this.last = reply;
      return { ...reply, uncertain: false, confirmed_until_ms: this.confirmedUntil };
    } catch (error) {
      return { ok: false, uncertain: true, detail: 'encoder lease: ' + String(error.message || error) };
    }
  }
}

module.exports = { EncoderLease, parseReply, ACTION, RECEIVER };
