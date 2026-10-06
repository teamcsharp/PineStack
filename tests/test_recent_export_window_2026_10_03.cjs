'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const mux = require('../desktop/clip-mux.cjs');
const { ScreenRing } = require('../desktop/screen-ring.cjs');

function fixture() {
  const ring = new ScreenRing();
  const base = Date.now() - 10000;
  for (let i = 0; i < 5; i++) {
    ring.take(Buffer.from('picture'), { at: base + i * 2000, ms: 2000, w: 320, h: 180, fps: 60, view: 'pip' });
    ring.take(Buffer.from('sound'), { at: base + i * 2000, ms: 2000, kind: 'a', a: true, audio_complete: true });
  }
  return { ring, base };
}

test('flush completion cannot move the selected past window forward', async () => {
  const { ring, base } = fixture();
  const endAt = base + 6750;
  const oldEncode = mux.encodeVideo;
  let made, args;
  mux.encodeVideo = async (_bin, build) => {
    args = build('libx264');
    fs.writeFileSync(args.at(-1), 'encoded');
    return { encoder: 'libx264' };
  };
  try {
    const shot = ring.window(3.25, .5, undefined, 'pip', { clock: endAt });
    assert.equal(shot.end, endAt - 500);
    assert.equal(shot.start, endAt - 3750);
    made = await ring.cut({ seconds: 3.25, back: .5, view: 'pip', end_at: endAt });
    assert.equal(made.ok, true, made.detail);
    assert.equal(made.seconds, 3.3);
    assert.equal(made.from, 3.8);
    assert.equal(made.to, .5);
    for (const list of args.filter(value => value.endsWith('.txt'))) {
      const content = fs.readFileSync(list, 'utf8');
      for (const lane of [ring.pieces, ring.sound]) {
        assert.equal(content.includes(lane.at(-1).file.replace(/\\/g, '/')), false);
      }
    }
    assert.equal(args[args.indexOf('-t') + 1], '3.250000');
    assert.equal(made.audio.complete, true);
  } finally {
    mux.encodeVideo = oldEncode;
    if (made?.dir) mux.forget(made.dir);
    ring.forget();
  }
});

test('a missing flush tail shortens the selected interval instead of replacing its head', () => {
  const { ring, base } = fixture();
  try {
    const shot = ring.window(6, 0, undefined, undefined, { clock: base + 12000 });
    assert.equal(shot.start, base + 6000);
    assert.equal(shot.end, base + 10000);
    assert.equal(shot.seconds, 4);
    assert.equal(shot.clamped, true);
    assert.equal(shot.from, 6);
    assert.equal(shot.to, 2);
  } finally { ring.forget(); }
});

test('audio-only exports use the request interval even when later sound is buffered', async () => {
  const { ring, base } = fixture();
  const oldRun = mux.run;
  let made, args;
  mux.run = async (_bin, supplied) => {
    args = supplied;
    fs.writeFileSync(args.at(-1), 'wave');
  };
  try {
    made = await ring.cutAudio({ seconds: 3, end_at: base + 7000 });
    assert.equal(made.ok, true, made.detail);
    assert.equal(made.seconds, 3);
    const list = fs.readFileSync(args[args.indexOf('-i') + 1], 'utf8');
    assert.equal(list.includes(ring.sound.at(-1).file.replace(/\\/g, '/')), false);
    assert.match(args[args.indexOf('-filter_complex') + 1], /asetpts=PTS-\(0.000000\)\/TB/);
    assert.equal(args[args.indexOf('-ac') + 1], '2');
  } finally {
    mux.run = oldRun;
    if (made?.dir) mux.forget(made.dir);
    ring.forget();
  }
});

test('scrub frames keep the same request interval while pending writes arrive', async () => {
  const { ring, base } = fixture();
  const oldRun = mux.run;
  let list;
  mux.run = async (_bin, supplied) => {
    list = fs.readFileSync(supplied[supplied.indexOf('-i') + 1], 'utf8');
    fs.writeFileSync(supplied.at(-1).replace('f%03d', 'f001'), 'jpeg');
  };
  try {
    const frames = await ring.frames({ seconds: 3, end_at: base + 7000 });
    assert.equal(frames.ok, true, frames.detail);
    assert.equal(frames.from, 3);
    assert.equal(frames.to, 0);
    assert.equal(list.includes(ring.pieces.at(-1).file.replace(/\\/g, '/')), false);
  } finally { mux.run = oldRun; ring.forget(); }
});
