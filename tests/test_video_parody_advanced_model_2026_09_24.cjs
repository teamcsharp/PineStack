'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const M = require('../desktop/renderer/video-edit-model.js');

const sources = {
  original: {id: 'original', duration: 10},
  generated: {id: 'generated', duration: 8},
  library: {id: 'library', duration: 12},
};

test('base clips remain sequential while overlays use explicit timeline starts', () => {
  const clips = [
    M.spliceDecorate(M.spliceClip(sources.original, 0, 4)),
    M.spliceDecorate(M.spliceClip(sources.library, 1, 3), {track: 'overlay', start_s: 1.5}),
    M.spliceDecorate(M.spliceClip(sources.generated, 0, 5)),
  ];
  assert.equal(M.spliceStartOf(clips, 0), 0);
  assert.equal(M.spliceStartOf(clips, 1), 1.5);
  assert.equal(M.spliceStartOf(clips, 2), 4);
  assert.equal(M.spliceLength(clips), 9);
  assert.equal(M.spliceLocate(clips, 4.5).source_id, 'generated');
  assert.deepEqual(M.spliceActiveOverlays(clips, 2).map(row => row.index), [1]);
});

test('advanced clip fields and rotobezier keyframes survive export', () => {
  const mask = {closed: true, feather: 12, invert: true, keyframes: [
    {at: 0, points: [{x: .1, y: .2, in_x: .05, in_y: .2, out_x: .2, out_y: .2}]},
    {at: 2, points: [{x: .3, y: .4, in_x: .2, in_y: .4, out_x: .4, out_y: .4}]},
  ]};
  const clip = M.spliceDecorate(M.spliceClip(sources.library, 2, 6), {track: 'overlay', start_s: 3.5,
    volume: .65, audio_fade_in_s: .4, audio_fade_out_s: .8, transition: 'dissolve', transition_s: .6,
    opacity: .7, mask});
  const body = M.spliceBody(['library'], [clip], 'Overlay', 'permit', sources);
  assert.deepEqual(body.clips[0], {source_id: 'library', in_s: 2, out_s: 6, track: 'overlay', start_s: 3.5,
    volume: .65, audio_fade_in_s: .4, audio_fade_out_s: .8, transition: 'dissolve', transition_s: .6,
    opacity: .7, mask});
});

test('mask keyframes interpolate controls and overlay splits preserve timing and effects', () => {
  const mask = M.spliceMask({closed: true, keyframes: [
    {at: 0, points: [{x: 0, y: 0, in_x: 0, in_y: 0, out_x: .2, out_y: .2}]},
    {at: 2, points: [{x: 1, y: 1, in_x: .8, in_y: .8, out_x: 1, out_y: 1}]},
  ]}, 4);
  const middle = M.spliceMaskAt(mask, 1)[0];
  for (const [field, expected] of Object.entries({x: .5, y: .5, in_x: .4, in_y: .4, out_x: .6, out_y: .6}))
    assert.ok(Math.abs(middle[field] - expected) < 1e-10, field);
  const clip = M.spliceDecorate(M.spliceClip(sources.library, 1, 5), {track: 'overlay', start_s: 7,
    transition: 'fade', transition_s: .5, mask});
  const split = M.spliceSplit([clip], 0, 3);
  assert.equal(split[0].transition, 'fade'); assert.equal(split[1].transition, 'fade');
  assert.equal(split[0].start_s, 7); assert.equal(split[1].start_s, 9);
});

test('source order is stable and supports imported station clips', () => {
  const clips = [M.spliceClip(sources.library), M.spliceClip(sources.generated), M.spliceClip(sources.library, 2, 3)];
  assert.deepEqual(M.spliceSourceIds(clips, ['original', 'generated', 'library']), ['generated', 'library']);
  assert.deepEqual(M.spliceInsert(clips, M.spliceClip(sources.original), 1).map(clip => clip.source_id),
    ['library', 'original', 'generated', 'library']);
});
