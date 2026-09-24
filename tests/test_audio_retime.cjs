const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../app.py'), 'utf8');
const start = source.indexOf('function djVoiceRetime(');
const end = source.indexOf('\nfunction djVoicePlay(', start);
assert.ok(start >= 0 && end > start);

function harness(queue) {
  const context = {djVoiceQueue: queue, djVoiceTimer: 7, calls: 0, clears: [],
    clearTimeout(id) { context.clears.push(id); },
    djVoiceNext() { context.calls += 1; }};
  vm.createContext(context);
  vm.runInContext(source.slice(start, end), context);
  return context;
}

test('a repaired day-long reservation wakes the original ordered queue without losing dialogue', () => {
  const queue = [
    {delivery_id: 'first', broadcastAt: 90000000, text: 'Every original word.', resumeAt: 2, retryAt: 8000},
    {delivery_id: 'second', broadcastAt: 90010000, text: 'The reply.'},
  ];
  const first = queue[0], second = queue[1];
  const ctx = harness(queue);
  assert.equal(ctx.djVoiceRetime([
    {delivery_id: 'first', broadcast_ms: 1000},
    {delivery_id: 'second', broadcast_ms: 11000},
  ], 1000, 5000), true);
  assert.equal(queue[0], first);
  assert.equal(queue[1], second);
  assert.equal(first.broadcastAt, 5000);
  assert.equal(second.broadcastAt, 15000);
  assert.equal(first.text, 'Every original word.');
  assert.equal(first.resumeAt, 2);
  assert.equal(first.retryAt, 8000);
  assert.deepEqual(ctx.clears, [7]);
  assert.equal(ctx.calls, 1);
});

test('active or completed deliveries are never requeued by repeated corrections', () => {
  const ctx = harness([{delivery_id: 'queued', broadcastAt: 5000}]);
  assert.equal(ctx.djVoiceRetime([{delivery_id: 'active', broadcast_ms: 1000}], 1000, 5000), false);
  assert.equal(ctx.djVoiceRetime([{delivery_id: 'queued', broadcast_ms: 1000}], 1000, 5000), false);
  assert.equal(ctx.djVoiceRetime([{delivery_id: 'queued', broadcast_ms: 'invalid'}], 1000, 5000), false);
  assert.equal(ctx.calls, 0);
  assert.equal(ctx.djVoiceQueue.length, 1);
});

test('a retimed reply cannot hold already-due speech behind future airtime', () => {
  const queue = [
    {delivery_id: 'reply', kind: 'reply', broadcastAt: 90000000},
    {delivery_id: 'due', broadcastAt: 5000},
  ];
  const ctx = harness(queue);
  assert.equal(ctx.djVoiceRetime([{delivery_id: 'reply', broadcast_ms: 20000}], 1000, 5000), true);
  assert.deepEqual(queue.map((clip) => clip.delivery_id), ['due', 'reply']);
  assert.equal(ctx.calls, 1);
});

test('new replies win an exact airtime tie but not an earlier booked slot', () => {
  const queue = [
    {kind: 'line', broadcastAt: 5000},
    {kind: 'reply', broadcastAt: 20000},
    {kind: 'sting', broadcastAt: 20000},
  ];
  const ctx = harness(queue);
  queue.sort(ctx.djVoiceCompare);
  assert.deepEqual(queue.map((clip) => clip.kind), ['line', 'reply', 'sting']);
});
