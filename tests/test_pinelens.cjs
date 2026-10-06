'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {PineLens, normalizeCrop, mapPoint} = require('../desktop/pinelens.cjs');

test('crop normalization and input coordinates include negative monitor origins', () => {
  assert.deepEqual(mapPoint({x: -1800, y: 200, width: 800, height: 400}, .5, .5), {x: -1400, y: 400});
  assert.deepEqual(mapPoint({x: 250, y: 50, width: 100, height: 200}, 1, 1), {x: 349, y: 249});
  assert.throws(() => normalizeCrop({x: .9, y: .2, width: .2, height: .2}));
  assert.throws(() => normalizeCrop({x: NaN, y: 0, width: .1, height: .1}));
  assert.throws(() => mapPoint({x: 0, y: 0, width: 100, height: 100}, 1.1, .5));
});

test('new crop persists and stale input cannot land in a moved region', () => {
  const lens = Object.create(PineLens.prototype);
  let config = {pineLens: {id: 'host', crop: null}};
  lens.read = () => config;
  lens.write = next => {config = {...config, ...next};};
  lens.electron = {screen: {getAllDisplays: () => [{id: 4}]}};
  lens.send = cmd => sent.push(cmd);
  let sent = [];
  lens.ready = true;
  lens.region = {x: 400, y: 100, width: 200, height: 300};
  lens.revision = 'first';
  lens.command({type: 'pointer', action: 'down', x: .5, y: .5, revision: 'first'});
  assert.equal(sent[0].x, 500);
  lens.save({crop: {x: .2, y: .1, width: .3, height: .4}, display: 4});
  assert.deepEqual(config.pineLens.crop, {x: .2, y: .1, width: .3, height: .4});
  sent = [];
  lens.command({type: 'key', key: 'Delete', revision: 'first'});
  assert.deepEqual(sent, [{type: 'release'}]);
  assert.throws(() => lens.save({crop: config.pineLens.crop, display: 7}));
});

test('capture selects Pine display and crops actual thumbnail pixels', async () => {
  const lens = Object.create(PineLens.prototype);
  const display = {id: 2, bounds: {x: -1000, y: 0, width: 1000, height: 600}, scaleFactor: 2};
  let config = {pineLens: {crop: {x: .1, y: .2, width: .5, height: .5}, display: 2}};
  let captured;
  const image = {getSize: () => ({width: 2000, height: 1200}), isEmpty: () => false,
    crop: rect => {captured = rect; const result = {getSize: () => ({width: rect.width, height: rect.height}), toJPEG: () => Buffer.from('jpeg')}; result.resize = () => result; return result;}};
  lens.read = () => config; lens.release = () => {};
  lens.window = () => ({isDestroyed: () => false, getBounds: () => display.bounds});
  lens.electron = {screen: {getAllDisplays: () => [display], getDisplayMatching: () => display,
    dipToScreenPoint: p => ({x: p.x * 2, y: p.y * 2})},
    desktopCapturer: {getSources: async () => [{display_id: '2', thumbnail: image}]}};
  await lens.capture();
  assert.deepEqual(captured, {x: 200, y: 240, width: 1000, height: 600});
  assert.deepEqual(lens.region, {x: -1800, y: 240, width: 1000, height: 600});
  const revision = lens.revision;
  await lens.capture(); assert.equal(lens.revision, revision);
  lens.full = true;
  await lens.capture(); assert.deepEqual(captured, {x: 0, y: 0, width: 2000, height: 1200});
  config.pineLens.display = 3; lens.full = false;
  await assert.rejects(lens.capture(), /disconnected/);
});
