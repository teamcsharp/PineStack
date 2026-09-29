/* [vcrfx] PineVcr: the table is the SFX TV's, the state machine never strands a
 * picture, and a burst of switch flips plays every flip and ends where the
 * switch ended.
 *
 *   node --test tests/test_pine_vcr_2026_09_29.cjs
 * (copy the test and desktop/renderer/{pine-vcr.js,sfx-tv.css} to a local
 *  directory first - node --test wedges with its cwd on the share.)
 */
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const R = path.join(__dirname, '..', 'desktop', 'renderer');

/* A fake element with a controllable Web Animations clock. */
function fakeWorld() {
  const anims = [];
  function el(name) {
    return {
      nodeType: 1, name, hidden: false, isConnected: true, style: {},
      getClientRects() { return this.hidden ? [] : [1]; },
      getBoundingClientRect() { return {left: 0, top: 0, width: 0, height: 0}; },
      animate(frames, opts) {
        const a = {el: this, frames, opts, done: false, cancelled: false, onfinish: null,
          cancel() { this.cancelled = true; },
          finish() { if (this.cancelled || this.done) return; this.done = true; if (this.onfinish) this.onfinish(); }};
        anims.push(a);
        return a;
      }
    };
  }
  return {el, anims, live: () => anims.filter((a) => !a.done && !a.cancelled)};
}

function load() {
  delete require.cache[require.resolve(path.join(R, 'pine-vcr.js'))];
  globalThis.window = undefined;
  return require(path.join(R, 'pine-vcr.js'));
}

const tick = () => new Promise((r) => setImmediate(r));

test('the keyframes ARE sfx-tv.css sfxTvOn / sfxTvOff, and the timing its classes', () => {
  const V = load();
  const css = fs.readFileSync(path.join(R, 'sfx-tv.css'), 'utf8');
  function frames(name) {
    const body = css.split('@keyframes ' + name)[1].split(/\n\}/)[0];
    return [...body.matchAll(/(\d+)%\s*\{\s*transform:\s*scale\(([\d.]+),\s*([\d.]+)\);\s*filter:\s*brightness\(([\d.]+)\);\s*opacity:\s*([\d.]+)/g)]
      .map((m) => [Number(m[1]) / 100, Number(m[2]), Number(m[3]), Number(m[4]), Number(m[5])]);
  }
  assert.deepStrictEqual(V.IN_FRAMES, frames('sfxTvOn'));
  assert.deepStrictEqual(V.OUT_FRAMES, frames('sfxTvOff'));
  assert.match(css, /\.sfx-tv-tube\.on\s*\{\s*animation: sfxTvOn \.42s cubic-bezier\(\.18, \.9, \.3, 1\)/);
  assert.match(css, /\.sfx-tv-tube\.off\s*\{\s*animation: sfxTvOff \.46s cubic-bezier\(\.7, 0, \.9, \.35\)/);
  assert.strictEqual(V.IN_MS, 420);
  assert.strictEqual(V.OUT_MS, 460);
  assert.strictEqual(V.FLASH_MS, 300);
});

test('each keyframe carries the curve (CSS eases per interval) and the run is linear', () => {
  const V = load();
  const w = fakeWorld();
  const e = w.el('tube');
  V.in(e);
  const a = w.anims[0];
  assert.strictEqual(a.opts.easing, 'linear');
  assert.strictEqual(a.opts.duration, 420);
  assert.ok(a.frames.every((k) => k.easing === V.IN_EASE));
  assert.deepStrictEqual(a.frames.map((k) => k.offset), [0, 0.34, 0.58, 1]);
});

test('sample() lands on every keyframe exactly', () => {
  const V = load();
  for (const [dir, F] of [['in', V.IN_FRAMES], ['out', V.OUT_FRAMES]]) {
    for (const f of F) {
      const s = V.sample(dir, f[0]);
      assert.ok(Math.abs(s.sx - f[1]) < 1e-9 && Math.abs(s.sy - f[2]) < 1e-9, dir + '@' + f[0]);
    }
  }
});

test('set(): the newest wish wins; hide runs only after an out nobody overtook', async () => {
  const V = load();
  const w = fakeWorld();
  const box = w.el('box');
  let hides = 0, shows = 0;
  const o = {show: (el) => { shows++; el.hidden = false; }, hide: (el) => { hides++; el.hidden = true; }};
  const p1 = V.set(box, true, o);
  assert.strictEqual(V.state(box), 'in');
  w.live()[0].finish();
  assert.strictEqual(await p1, true);
  assert.strictEqual(V.state(box), 'shown');
  const p2 = V.set(box, false, o);            // off...
  const p3 = V.set(box, true, o);             // ...and on again before it finished
  assert.strictEqual(await p2, false);        // the off was overtaken
  assert.strictEqual(hides, 0);               // so nothing hid the box
  w.live()[0].finish();
  assert.strictEqual(await p3, true);
  assert.strictEqual(V.state(box), 'shown');
  assert.strictEqual(box.hidden, false);
  const p4 = V.set(box, false, o);
  w.live()[0].finish();
  assert.strictEqual(await p4, true);
  assert.strictEqual(hides, 1);
  assert.strictEqual(box.hidden, true);
  assert.strictEqual(V.state(box), 'hidden');
  assert.strictEqual(await V.set(box, false, o), true);   // idempotent
  assert.strictEqual(w.live().length, 0);
});

test('flip(): six fast flips are six transitions, in order, ending where the switch is', async () => {
  const V = load();
  const w = fakeWorld();
  const box = w.el('cam');
  const seen = [];
  const o = {show: (el) => { el.hidden = false; }, hide: (el) => { el.hidden = true; }};
  await (async () => { const p = V.set(box, true, o); w.live()[0].finish(); await p; })();
  /* the viewer's poll saw 3 flips (on->off->on->off), then 3 more (->on->off->on) */
  V.flip(box, false, 3, o);
  V.flip(box, true, 3, o);
  for (let guard = 0; guard < 400 && (w.live().length || V.state(box) === 'in' || V.state(box) === 'out'); guard++) {
    const a = w.live()[0];
    if (a) { seen.push(a.frames[0].offset === 0 && a.frames.length === 4 && a.frames[3].opacity === 0 ? 'out' : 'in'); a.finish(); }
    await new Promise((r) => setTimeout(r, 5));
    if (!w.live().length) await new Promise((r) => setTimeout(r, V.HOLD_MS + 20));
  }
  assert.deepStrictEqual(seen, ['out', 'in', 'out', 'in', 'out', 'in']);
  assert.strictEqual(V.state(box), 'shown');
  assert.strictEqual(box.hidden, false);
});

test('an out is held collapsed only until the next in: then nothing of it is left', async () => {
  const V = load();
  const w = fakeWorld();
  const box = w.el('box');
  let p = V.out(box); const out = w.live()[0]; out.finish(); await p;
  assert.strictEqual(out.opts.fill, 'forwards');
  assert.strictEqual(out.cancelled, false);          // the collapsed frame is held...
  p = V.in(box); w.live()[0].finish(); await p;
  assert.strictEqual(out.cancelled, true);           // ...and let go by the next in
  assert.ok(w.anims.every((a) => a.cancelled || !a.done || a.opts.fill !== 'forwards'));
  V.out(box); w.live()[0].finish(); await tick();
  V.cancel(box);                                      // cancel() makes it whole too
  assert.ok(w.anims.filter((a) => a.opts.fill === 'forwards').every((a) => a.cancelled));
});

test('reduced motion: a short fade both ways, no pop', async () => {
  const V = load();
  globalThis.matchMedia = () => ({matches: true});
  try {
    const w = fakeWorld();
    const e = w.el('tube');
    V.in(e);
    const a = w.anims[0];
    assert.strictEqual(a.opts.duration, V.FADE_MS);
    assert.deepStrictEqual(a.frames, [{opacity: 0}, {opacity: 1}]);
    assert.strictEqual(w.anims.length, 1);   // no flash
  } finally { delete globalThis.matchMedia; }
});

test('a lost finish event still lands the state (the watch)', async () => {
  const V = load();
  const w = fakeWorld();
  const e = w.el('tube');
  const p = V.out(e);
  const t0 = Date.now();
  assert.strictEqual(await p, true);          // never finished by the "engine"
  assert.ok(Date.now() - t0 >= V.OUT_MS);
  assert.strictEqual(V.state(e), 'hidden');
});

test('no element, a text node, no animate(): every call answers', async () => {
  const V = load();
  assert.strictEqual(await V.in(null), false);
  assert.strictEqual(await V.set({nodeType: 3}, true), false);
  const bare = {nodeType: 1, style: {}, getClientRects: () => [1]};
  assert.strictEqual(await V.in(bare), true);
  assert.strictEqual(V.state(bare), 'shown');
  V.cancel(null);
});
