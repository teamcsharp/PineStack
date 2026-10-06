 'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EncoderLease, parseReply, ACTION, RECEIVER } = require('../tablet-encoder-lease.cjs');
const owner = 'mirror_test_owner';
const healthy = () => ({ ok: true, held: true, owner, video_running: false,
  video_released: true, expires_in_ms: 60000 });
const broadcast = (value, result = 0) => 'Broadcasting: Intent\nBroadcast completed: result=' + result + ', data="' + JSON.stringify(value) + '"\n';
function leaseWith(reply, options = {}) {
  const calls = [];
  const lease = new EncoderLease({ adb: 'adb-test', serial: 'tablet-test', owner,
    execFile: (exe, args, opts, done) => {
      calls.push({ exe, args, opts });
      if (reply instanceof Error) return done(reply);
      done(null, typeof reply === 'function' ? reply(args) : reply, '');
    }, ...options });
  return { lease, calls };
}

test('parses raw and shell-escaped ordered JSON replies', () => {
  assert.deepEqual(parseReply(broadcast(healthy())), healthy());
  const escaped = JSON.stringify(JSON.stringify(healthy()));
  assert.deepEqual(parseReply('Broadcast completed: result=0, data=' + escaped), healthy());
});

test('missing receiver/empty acknowledgement cannot permit screenrecord', async () => {
  for (const reply of ['Broadcast completed: result=0', 'Broadcasting: Intent', 'Broadcast completed: result=0, data="bad"']) {
    assert.equal((await leaseWith(reply).lease.acquire()).ok, false);
  }
});

test('acquire verifies actual replay release and ownership', async () => {
  for (const patch of [{ video_running: true }, { video_released: false }, { video_released: undefined },
    { held: false }, { owner: 'another_owner' }, { expires_in_ms: 4000 }, { expires_in_ms: 'NaN' }]) {
    assert.equal((await leaseWith(broadcast({ ...healthy(), ...patch })).lease.acquire()).ok, false);
  }
  const { lease, calls } = leaseWith(broadcast(healthy()));
  assert.equal((await lease.acquire()).ok, true);
  assert.ok(lease.remainingMs() > 55000);
  assert.equal(calls[0].exe, 'adb-test');
  assert.deepEqual(calls[0].args.slice(0, 5), ['-s', 'tablet-test', 'shell', 'am', 'broadcast']);
  assert.ok(calls[0].args.includes(RECEIVER));
  assert.ok(calls[0].args.includes(ACTION));
  assert.equal(calls[0].opts.timeout, 12000);
});

test('nonzero broadcast result or transport failure remains a failure', async () => {
  assert.equal((await leaseWith(broadcast(healthy(), 1)).lease.acquire()).ok, false);
  assert.equal((await leaseWith(new Error('offline')).lease.acquire()).ok, false);
});

test('renewal failure preserves last verified deadline without inventing time', async () => {
  let clock = 1000;
  let renew = false;
  const { lease } = leaseWith(() => renew ? 'Broadcast completed: result=0' : broadcast(healthy()), { now: () => clock });
  assert.equal((await lease.acquire()).ok, true);
  clock += 10000;
  renew = true;
  assert.equal((await lease.renew()).ok, false);
  assert.equal(lease.remainingMs(), 50000);
});

test('handshake latency is removed from the confirmed lease lifetime', async () => {
  let clock = 1000;
  const { lease } = leaseWith(() => { clock += 3000; return broadcast(healthy()); }, { now: () => clock });
  assert.equal((await lease.acquire()).ok, true);
  assert.equal(lease.remainingMs(), 57000);
});

test('failed release cannot claim restoration, successful release clears deadline', async () => {
  let releasing = false;
  let stopped = false;
  const { lease } = leaseWith(() => releasing
    ? broadcast({ ok: stopped, held: !stopped, owner: stopped ? '' : owner,
      video_running: stopped, detail: stopped ? null : 'external recorder still exists' }, stopped ? 0 : 1)
    : broadcast(healthy()));
  await lease.acquire();
  releasing = true;
  assert.equal((await lease.release()).ok, false);
  assert.ok(lease.remainingMs() > 0);
  stopped = true;
  assert.equal((await lease.release()).ok, true);
  assert.equal(lease.remainingMs(), 0);
});

test('invalid owner never reaches the tablet shell', () => {
  assert.throws(() => leaseWith('', { owner: 'bad; shell' }), /invalid mirror lease owner/);
});


test('native refusal with nonzero am exit preserves exact ownership reason', async () => {
  const lease = new EncoderLease({ adb: 'adb-test', serial: 'tablet-test', owner,
    execFile: (exe, args, opts, done) => done(new Error('am exited 1'),
      broadcast({ ok: false, held: true, owner: 'another_mirror_owner',
        detail: 'the mirror encoder is held by another owner' }, 1), '') });
  const refused = await lease.acquire();
  assert.equal(refused.ok, false);
  assert.equal(refused.owner, 'another_mirror_owner');
  assert.equal(refused.detail, 'the mirror encoder is held by another owner');
  assert.equal(lease.remainingMs(), 0);
});

test('command failure cannot turn an apparent native success into a verified lease', async () => {
  const lease = new EncoderLease({ adb: 'adb-test', serial: 'tablet-test', owner,
    execFile: (exe, args, opts, done) => done(new Error('transport failed'), broadcast(healthy()), '') });
  assert.equal((await lease.acquire()).ok, false);
  assert.equal(lease.remainingMs(), 0);
});
