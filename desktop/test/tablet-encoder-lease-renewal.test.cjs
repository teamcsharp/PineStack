 'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { EncoderLease } = require('../tablet-encoder-lease.cjs');
const owner = 'mirror_renewal_test';
const healthy = () => ({ ok: true, held: true, owner, video_running: false,
  video_released: true, expires_in_ms: 60000 });
const broadcast = (reply, result = 0) => 'Broadcast completed: result=' + result + ', data="' + JSON.stringify(reply) + '"\n';

async function fixture(actions, remaining = 40000) {
  const clock = { value: 1000 };
  const calls = [], pending = [];
  const lease = new EncoderLease({ adb: 'fake-adb', serial: 'fake-tablet', owner,
    now: () => clock.value,
    execFile(exe, args, options, done) {
      const operation = args[args.indexOf('operation') + 1];
      calls.push({ operation, args, options });
      if (operation === 'acquire') return done(null, broadcast(healthy()), '');
      if (operation === 'release') return done(null, broadcast({ ok: true, held: false, owner: '' }), '');
      const action = actions.shift();
      assert.ok(action, 'unexpected extra renewal attempt');
      if (action.pending) { pending.push(done); return; }
      clock.value += action.advance || 0;
      done(action.error || null, action.output === undefined ? broadcast(action.reply || healthy(), action.result || 0) : action.output, '');
    } });
  assert.equal((await lease.acquire()).ok, true);
  clock.value += 60000 - remaining;
  return { lease, clock, calls, pending, renewalCalls: () => calls.filter(call => call.operation === 'renew') };
}

test('one uncertain transport loss retries once within the verified remaining budget', async () => {
  const f = await fixture([{ error: new Error('ADB timeout'), output: '', advance: 12000 }, {}]);
  const deadline = f.lease.confirmedUntil;
  const reply = await f.lease.renew();
  assert.equal(reply.ok, true);
  assert.equal(reply.uncertain, false);
  assert.equal(f.renewalCalls().length, 2);
  assert.ok(f.lease.confirmedUntil > deadline);
  for (const call of f.renewalCalls()) {
    assert.equal(call.options.timeout, 12000);
    assert.equal(call.args[call.args.indexOf('owner') + 1], owner);
  }
});

test('an unreadable native ACK permits only the same single bounded retry', async () => {
  const f = await fixture([{ output: 'Broadcast completed: result=0, data="not-json"' }, {}]);
  assert.equal((await f.lease.renew()).ok, true);
  assert.equal(f.renewalCalls().length, 2);
});

test('native explicit refusal never retries even if it carries an uncertain field', async () => {
  const f = await fixture([{ reply: { ok: false, uncertain: true, held: false, detail: 'lease expired' } }]);
  const deadline = f.lease.confirmedUntil;
  const reply = await f.lease.renew();
  assert.equal(reply.ok, false);
  assert.equal(reply.uncertain, false);
  assert.equal(reply.detail, 'lease expired');
  assert.equal(f.renewalCalls().length, 1);
  assert.equal(f.lease.confirmedUntil, deadline);
});

test('nonzero command exit preserves a native refusal without retry', async () => {
  const f = await fixture([{ error: new Error('am exit1'), result: 1,
    reply: { ok: false, held: true, owner: 'another_owner', detail: 'held by another owner' } }]);
  const reply = await f.lease.renew();
  assert.equal(reply.uncertain, false);
  assert.equal(reply.detail, 'held by another owner');
  assert.equal(reply.owner, 'another_owner');
  assert.equal(f.renewalCalls().length, 1);
});

test('readable invalid ownership or replay-release proof is definitive including nonzero exit', async () => {
  for (const patch of [{ owner: 'another_owner' }, { held: false }, { video_running: true },
      { video_released: false }, { expires_in_ms: 4000 }]) {
    for (const error of [null, new Error('am exit1')]) {
      const f = await fixture([{ error, reply: { ...healthy(), ...patch } }]);
      const deadline = f.lease.confirmedUntil;
      const reply = await f.lease.renew();
      assert.equal(reply.ok, false);
      assert.equal(reply.uncertain, false);
      assert.equal(f.renewalCalls().length, 1);
      assert.equal(f.lease.confirmedUntil, deadline);
    }
  }
});

test('two uncertain failures stop without any third attempt or deadline extension', async () => {
  const f = await fixture([{ error: new Error('timeout'), output: '', advance: 12000 },
    { error: new Error('still offline'), output: '', advance: 12000 }]);
  const deadline = f.lease.confirmedUntil;
  const reply = await f.lease.renew();
  assert.equal(reply.ok, false);
  assert.equal(reply.uncertain, true);
  assert.equal(f.renewalCalls().length, 2);
  assert.equal(f.lease.confirmedUntil, deadline);
  assert.equal(f.lease.remainingMs(), 16000);
});

test('an apparent success combined with transport failure does not confirm more time', async () => {
  const f = await fixture([{ error: new Error('transport failed'), reply: healthy() },
    { reply: { ok: false, held: false, detail: 'no hold' } }]);
  const deadline = f.lease.confirmedUntil;
  assert.equal((await f.lease.renew()).ok, false);
  assert.equal(f.renewalCalls().length, 2);
  assert.equal(f.lease.confirmedUntil, deadline);
});

test('no retry starts at or below the 13 second verified budget boundary', async () => {
  for (const remaining of [0, 5000, 12999, 13000]) {
    const f = await fixture([{ error: new Error('offline'), output: '' }], remaining);
    const deadline = f.lease.confirmedUntil;
    assert.equal((await f.lease.renew()).ok, false);
    assert.equal(f.renewalCalls().length, 1);
    assert.equal(f.lease.confirmedUntil, deadline);
  }
  const f = await fixture([{ error: new Error('offline'), output: '' }, {}], 13001);
  assert.equal((await f.lease.renew()).ok, true);
  assert.equal(f.renewalCalls().length, 2);
});

test('the first attempt consuming retry headroom prevents retry even after a large initial budget', async () => {
  const f = await fixture([{ error: new Error('timeout'), output: '', advance: 12000 }], 25000);
  const deadline = f.lease.confirmedUntil;
  assert.equal((await f.lease.renew()).ok, false);
  assert.equal(f.renewalCalls().length, 1);
  assert.equal(f.lease.remainingMs(), 13000);
  assert.equal(f.lease.confirmedUntil, deadline);
});

test('a delayed ACK cannot confirm a stale short lease or trigger retry of that definitive proof', async () => {
  const f = await fixture([{ advance: 3000, reply: { ...healthy(), expires_in_ms: 7000 } }]);
  const deadline = f.lease.confirmedUntil;
  const reply = await f.lease.renew();
  assert.equal(reply.ok, false);
  assert.equal(reply.uncertain, false);
  assert.equal(f.renewalCalls().length, 1);
  assert.equal(f.lease.confirmedUntil, deadline);
});

test('second verified ACK still subtracts its handshake latency from the renewed lease', async () => {
  const f = await fixture([{ error: new Error('timeout'), output: '', advance: 12000 }, { advance: 3000 }]);
  assert.equal((await f.lease.renew()).ok, true);
  assert.equal(f.lease.remainingMs(), 57000);
  assert.equal(f.renewalCalls().length, 2);
});

test('release generation prevents retry and a late successful renewal from resurrecting a lease', async () => {
  for (const error of [null, new Error('transport failed')]) {
    const f = await fixture([{ pending: true }]);
    const pendingRenew = f.lease.renew();
    assert.equal(f.pending.length, 1);
    assert.equal((await f.lease.release()).ok, true);
    f.pending[0](error, error ? '' : broadcast(healthy()), '');
    assert.equal((await pendingRenew).ok, false);
    assert.equal(f.lease.confirmedUntil, 0);
    assert.equal(f.renewalCalls().length, 1);
  }
});

test('a late renewal cannot overwrite a later acquisition deadline', async () => {
  const f = await fixture([{ pending: true }]);
  const pendingRenew = f.lease.renew();
  f.clock.value += 1000;
  assert.equal((await f.lease.acquire()).ok, true);
  const newest = f.lease.confirmedUntil;
  f.pending[0](null, broadcast(healthy()), '');
  assert.equal((await pendingRenew).ok, false);
  assert.equal(f.lease.confirmedUntil, newest);
  assert.equal(f.renewalCalls().length, 1);
});

test('release during the second attempt also fences its successful late ACK', async () => {
  const f = await fixture([{ error: new Error('transient'), output: '' }, { pending: true }]);
  const pendingRenew = f.lease.renew();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.pending.length, 1);
  assert.equal((await f.lease.release()).ok, true);
  f.pending[0](null, broadcast(healthy()), '');
  assert.equal((await pendingRenew).ok, false);
  assert.equal(f.lease.confirmedUntil, 0);
  assert.equal(f.renewalCalls().length, 2);
});

test('copying new call and renew methods onto an old instance preserves its calendar clock and deadline', async () => {
  const f = await fixture([{ error: new Error('transient'), output: '' }, {}]);
  const oldNow = f.lease.now;
  const oldDeadline = f.lease.confirmedUntil;
  delete f.lease.generation;
  const oldPrototype = { remainingMs() { return Math.max(0, this.confirmedUntil - this.now()); } };
  Object.setPrototypeOf(f.lease, oldPrototype);
  Object.assign(oldPrototype, { call: EncoderLease.prototype.call, renew: EncoderLease.prototype.renew });
  assert.equal(f.lease.now, oldNow);
  assert.equal(f.lease.confirmedUntil, oldDeadline);
  assert.equal((await f.lease.renew()).ok, true);
  assert.equal(f.renewalCalls().length, 2);
  assert.equal(f.lease.now, oldNow);
  assert.equal(f.lease.generation, 0);
});

test('new default lease clocks are elapsed-time based and ignore calendar jumps', async () => {
  const previousDateNow = Date.now;
  let calendar = 1000000000000;
  Date.now = () => calendar;
  try {
    const calls = [];
    const lease = new EncoderLease({ adb: 'fake-adb', serial: 'fake-tablet', owner,
      execFile(exe, args, options, done) {
        calls.push(args[args.indexOf('operation') + 1]);
        if (calls.length === 2) { calendar += 1000000000; done(new Error('transient'), '', ''); }
        else done(null, broadcast(healthy()), '');
      } });
    assert.equal((await lease.acquire()).ok, true);
    assert.ok(lease.confirmedUntil < calendar);
    assert.equal((await lease.renew()).ok, true);
    assert.deepEqual(calls, ['acquire', 'renew', 'renew']);
    calendar -= 2000000000;
    assert.ok(lease.remainingMs() > 55000 && lease.remainingMs() <= 60000);
  } finally { Date.now = previousDateNow; }
});
