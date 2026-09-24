const assert = require('node:assert/strict');
const {test} = require('node:test');

const {Mirror} = require('../desktop/tablet-mirror.cjs');

test('a live process pair with no first frame is actively rebuilt', () => {
  const mirror = new Mirror();
  mirror.running = true;
  mirror.pipeAt = 1000;
  mirror.pipeFrames = 0;
  mirror.frames = 0;
  let why = '';
  mirror.rebuild = value => { why = value; };
  assert.equal(mirror.health(13001), true);
  assert.equal(why, 'no first frame arrived');
});

test('a process pair that stops producing frames is actively rebuilt', () => {
  const mirror = new Mirror();
  mirror.running = true;
  mirror.pipeAt = 1000;
  mirror.pipeFrames = 2;
  mirror.frames = 3;
  mirror.lastFrameAt = 2000;
  let why = '';
  mirror.rebuild = value => { why = value; };
  assert.equal(mirror.health(7001), true);
  assert.equal(why, 'frame pipe stalled');
});

test('a slow local viewer drops stale frames instead of growing a queue', () => {
  const mirror = new Mirror();
  let writes = 0;
  const response = {
    destroyed: false, writableEnded: false, writableNeedDrain: true,
    write() { writes += 1; return true; }
  };
  mirror.watchers.add(response);
  assert.equal(mirror.push(response, Buffer.from([0xff, 0xd8, 0xff, 0xd9])), false);
  assert.equal(writes, 0);
  assert.equal(mirror.watchers.has(response), true);
});
