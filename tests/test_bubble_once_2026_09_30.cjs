// [bubble-once] a Message-view bubble plays its clip while the AIR carries it,
// not for as long as its line stays the newest. "It was a pine box ad stinger
// that was looping in the background": the receipts had PineBox-H3_00190_
// (a 10 s clip) up for 57 s, and 2-3 s stings for 79-159 s.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
const kiosk = path.join(root, 'app/src/main/assets/pine-views/script-page.js');
if (fs.existsSync(kiosk)) assert.strictEqual(fs.readFileSync(kiosk, 'utf8'), src, 'the kiosk copy is the renderer, byte for byte');

const grab = name => {
  const m = src.match(new RegExp('\\n  function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n'));
  assert(m, 'missing ' + name);
  return m[0];
};

function fakeVideo() {
  const on = {};
  return {
    on, attrs: {}, style: {}, muted: false, loop: null, paused: true, ended: false, currentTime: 0, plays: 0,
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(n, fn) { (on[n] = on[n] || []).push(fn); },
    play() { this.paused = false; this.ended = false; this.plays += 1; return Promise.resolve(); },
    fire(n) { (on[n] || []).forEach(fn => fn()); },
    end() { this.paused = true; this.ended = true; this.fire('ended'); },
  };
}

function harness() {
  const made = [];
  const mv = {video: null, pip: null};
  const released = [];
  const document = {createElement: () => { const v = fakeVideo(); made.push(v); return v; }};
  const body = grab('mvVideoStart') + grab('mvMediaFrame') + 'return {mvVideoStart, mvMediaFrame};';
  const mvVideoRelease = () => { const m = mv.video; mv.video = null; if (m && m.video) { released.push(m.video); m.video = null; } };
  // eslint-disable-next-line no-new-func
  const fns = new Function('document', 'mv', 'mvVideoRelease', 'videoFirstFrame', 'root', 'mvBoomAsk', 'stationUrl', 'mvLedFrame', body)(
    document, mv, mvVideoRelease, () => {}, {}, () => null, u => u, () => {});
  const m = {mode: 'video', info: {url: '/sfx/abc', sid: 'abc'}, box: {appendChild() {}}, item: {}, failed: false};
  const cur = {media: m, phase: 'air'};
  return {fns, m, cur, made, released, mv};
}

// 1. The clip ends while the air is still carrying the line: it plays again.
{
  const h = harness();
  h.fns.mvMediaFrame(h.cur, 0.2);
  const v = h.made[0];
  assert(v, 'the bubble made its video');
  assert.strictEqual(v.loop, false, 'the bubble video is not a loop');
  assert.strictEqual(v.plays, 1);
  h.fns.mvMediaFrame(h.cur, 0.6);
  v.end();
  assert.strictEqual(v.plays, 2, 'still on air: another pass');
  assert.strictEqual(h.released.length, 0);
}

// 2. The air is over (f reached 1) and the pass ends: the thumbnail comes back,
//    and no later frame of the same airing starts it again.
{
  const h = harness();
  h.fns.mvMediaFrame(h.cur, 0.5);
  const v = h.made[0];
  h.fns.mvMediaFrame(h.cur, 1);
  v.end();
  assert.strictEqual(h.released.length, 1, 'released to the thumbnail');
  for (let i = 0; i < 50; i += 1) h.fns.mvMediaFrame(h.cur, 1);
  assert.strictEqual(h.made.length, 1, 'no new video for the same airing');
  assert.strictEqual(v.plays, 1);
}

// 3. The air cannot say (f null - the timeline does not know the line): ONE pass.
{
  const h = harness();
  h.fns.mvMediaFrame(h.cur, null);
  const v = h.made[0];
  v.end();
  for (let i = 0; i < 50; i += 1) h.fns.mvMediaFrame(h.cur, null);
  assert.strictEqual(h.made.length, 1);
  assert.strictEqual(h.released.length, 1, 'one pass, then the thumbnail');
}

// 4. A frame that sees the ended element never restarts it behind the handler's back.
{
  const h = harness();
  h.fns.mvMediaFrame(h.cur, 1);
  const v = h.made[0];
  v.paused = true; v.ended = true;          // ended, handler not yet run
  h.fns.mvMediaFrame(h.cur, 1);
  assert.strictEqual(v.plays, 1, 'an ended clip is not replayed by the frame loop');
}

// 5. A pinned bubble's re-run is a new airing: it plays again.
{
  const h = harness();
  h.fns.mvMediaFrame(h.cur, null);
  h.made[0].end();
  h.cur.phase = 'roll';
  h.fns.mvMediaFrame(h.cur, null);
  h.cur.phase = 'air';
  h.fns.mvMediaFrame(h.cur, 0.1);
  assert.strictEqual(h.made.length, 2, 'the re-run plays its clip');
}

console.log('bubble-once ok');
