const {test} = require('node:test');
const assert = require('node:assert/strict');
const controls = require('../desktop/renderer/lcd-controls.js');
const {encode, jpegBudget} = require('../desktop/renderer/lcd-frame.js');

test('top-edge swipes do not become taps or accidental avatar switches', () => {
  assert.equal(controls.gesture({x: 10, y: 6}, {x: 18, y: 90}), 'down');
  assert.equal(controls.gesture({x: 10, y: 6}, {x: 13, y: 9}), 'tap');
  assert.equal(controls.gesture({x: 90, y: 180}, {x: 85, y: 100}), 'up');
  assert.equal(controls.gesture({x: 90, y: 110}, {x: 95, y: 190}), '');
  assert.equal(controls.gesture({x: 10, y: 8}, {x: 110, y: 38}), '');
});

test('mode switch owns a separate corner target ahead of drawer controls', () => {
  for (const [width, height] of [[320, 240], [240, 320], [800, 480]]) {
    const region = controls.corner(width, height), badge = region.badge;
    assert.equal(controls.hit(badge.x + badge.w / 2, badge.y + badge.h / 2, width, height), 'swap');
    assert.ok(badge.x + badge.w < region.w && badge.y + badge.h < region.h);
    assert.equal(controls.cornerHit(-1, 20, width, height), false);
    assert.equal(controls.cornerHit(20, -1, width, height), false);
    assert.equal(controls.cornerHit(region.w, 20, width, height), false);
    assert.equal(controls.cornerHit(20, region.h, width, height), false);
    for (const tile of controls.tiles({}, width, height)) assert.ok(tile.y >= region.h);
  }
});

test('every settings target survives landscape and portrait scaling', () => {
  for (const [width, height] of [[320, 240], [240, 320], [800, 480]]) {
    const targets = controls.tiles({}, width, height);
    assert.equal(targets.length, 8);
    for (const tile of targets) {
      assert.equal(controls.hit(tile.x + tile.w / 2, tile.y + tile.h / 2, width, height, {}), tile.id);
      assert.ok(tile.y >= height / 4, 'No tile overlaps the firmware top-left toggle');
      assert.ok(tile.y + tile.h < height * 210 / 240, 'No tile overlaps the timer footer');
      for (const other of targets) if (other !== tile) {
        assert.ok(tile.x + tile.w <= other.x || other.x + other.w <= tile.x || tile.y + tile.h <= other.y || other.y + other.h <= tile.y);
      }
    }
    assert.equal(controls.hit(width * .3, height * .93, width, height), 'timer');
    assert.equal(controls.hit(width * .85, height * .93, width, height), 'close');
  }
});

test('newspaper choice overrides automatic cupboard while overlay and timer are independent', () => {
  let config = {mode: 'paper', pausedCupboard: true, chatOverlay: true, screensaverSeconds: 300};
  config = {...config, ...controls.change('tabloid', config)};
  assert.equal(config.paperStyle, 'tabloid'); assert.equal(config.pausedCupboard, false);
  assert.equal(config.chatOverlay, false);
  config = {...config, ...controls.change('chat', config)};
  assert.equal(config.chatOverlay, true); assert.equal(config.paperStyle, 'tabloid');
  config = {...config, ...controls.change('timer', config)};
  assert.equal(config.screensaverSeconds, 900); assert.equal(config.screensaverEnabled, undefined);
  config = {...config, ...controls.change('saver', config)};
  assert.equal(config.screensaverEnabled, true);
  assert.deepEqual(controls.change('scroll', {scrollEnabled: false}), {scrollEnabled: true});
});

test('pure newspaper and gallery choices stay distinct from mixed paper and Quanta avatars', () => {
  const start = {mode: 'cupboard', paperStyle: 'tabloid', chatOverlay: true, pausedCupboard: true, screensaverEnabled: true, galleryIntervalSeconds: 11};
  const paper = {...start, ...controls.change('newspaper', start)};
  assert.deepEqual(controls.change('newspaper', start), {mode: 'paper', paperStyle: 'broadsheet', chatOverlay: false, pausedCupboard: false});
  assert.equal(controls.view(paper), 'newspaper');
  assert.equal(paper.screensaverEnabled, true);
  const gallery = {...start, ...controls.change('gallery', start)};
  assert.equal(controls.view(gallery), 'gallery');
  assert.equal(gallery.pausedCupboard, false);
  assert.equal(gallery.galleryIntervalSeconds, 11);
  assert.equal(gallery.chatOverlay, true, 'Gallery preserves the newspaper overlay preference');
  assert.equal(controls.tiles(gallery).find(tile => tile.id === 'chat').active, false);
  assert.equal(controls.tiles(gallery).find(tile => tile.id === 'gallery').active, true);
  assert.equal(controls.change('avatar', gallery), null, 'Quanta view remains a separate device action');
  const mixed = {...gallery, ...controls.change('paper', gallery)};
  assert.equal(controls.view(mixed), 'paper');
  assert.equal(mixed.chatOverlay, true);
  assert.equal(mixed.paperStyle, 'broadsheet');
  assert.deepEqual(controls.change('chat', gallery), {mode: 'paper', chatOverlay: true, pausedCupboard: false});
});

test('content cycle switches pure newspaper and Pine gallery without changing the AV/PB corner', () => {
  let config = {mode: 'paper', chatOverlay: true, paperStyle: 'tabloid'};
  for (const expected of ['newspaper', 'gallery', 'newspaper', 'gallery']) {
    config = {...config, ...controls.cycle(config)};
    assert.equal(controls.view(config), expected);
    assert.equal(controls.hit(32, 28, 320, 240, config), 'swap');
  }
  for (const mode of ['dialogue', 'cupboard']) {
    assert.equal(controls.view({mode}), mode);
    const changed = {...{mode}, ...controls.cycle({mode})};
    assert.equal(controls.view(changed), 'newspaper');
  }
  assert.equal(controls.view({}), 'paper');
  assert.equal(controls.view({mode: 'paper', paperStyle: 'tabloid', chatOverlay: false}), 'tabloid');
});

test('dense frame quality is learned and reused in a single subsequent encode', () => {
  let calls = 0;
  const canvas = {toDataURL: (_mime, quality) => { calls++; return 'data:image/jpeg;base64,' + Buffer.alloc(1200 + Math.round(quality * 42000)).toString('base64'); }};
  const first = encode(canvas, {});
  assert.ok(first.bytes <= 12288); assert.ok(calls <= 5);
  calls = 0;
  const next = encode(canvas, {});
  assert.ok(next.bytes <= 12288); assert.equal(calls, 1);
  assert.equal(jpegBudget({pineProtocol: 2, streamPort: 3233, maxJpeg: 24576}), 24576);
  assert.equal(jpegBudget({pineProtocol: 1, streamPort: 0, maxJpeg: 24576}), 12288);
  assert.throws(() => encode({toDataURL: () => 'data:image/jpeg;base64,' + Buffer.alloc(25000).toString('base64')}, {}), /cannot fit/);
});
