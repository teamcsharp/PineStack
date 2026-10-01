/* [mirror-quality] "Halve the quality and have a slider where I can adjust
 * that." The desk mirror rests at half the bitrate; the slider moves it. */
const assert = require('node:assert/strict');
const {test} = require('node:test');

const {Mirror} = require('../desktop/tablet-mirror.cjs');

test('the mirror rests at half quality: full detail is half the old 11.8 Mbit', () => {
  const mirror = new Mirror();
  assert.equal(mirror.shape.quality, 0.5);
  assert.equal(mirror.shapeFor('full').bitrate, 5896000);
});

test('the slider scales the bitrate and rebuilds a running pipe', () => {
  const mirror = new Mirror();
  let why = '';
  mirror.running = true;
  mirror.rebuild = value => { why = value; };
  const said = mirror.requality(1);
  assert.equal(said.quality, 1);
  assert.equal(mirror.shapeFor('full').bitrate, 11792000);
  assert.equal(why, 'capture quality changed');
});

test('nonsense is ignored and the range is clamped', () => {
  const mirror = new Mirror();
  mirror.requality('loud');
  assert.equal(mirror.shape.quality, 0.5);
  mirror.requality(5);
  assert.equal(mirror.shape.quality, 1);
  mirror.requality(0);
  assert.equal(mirror.shape.quality, 0.1);
});

test('the same quality twice does not rebuild the encoder', () => {
  const mirror = new Mirror();
  let rebuilt = 0;
  mirror.running = true;
  mirror.rebuild = () => { rebuilt += 1; };
  mirror.requality(0.5);
  assert.equal(rebuilt, 0);
});
