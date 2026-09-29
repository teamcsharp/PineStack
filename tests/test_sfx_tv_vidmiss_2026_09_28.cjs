/* [vidmiss] "ON THE TABLET SOMETIMES VIDEOS ARE NOT COMING UP."
 *
 * Measured 2026-09-28 on the PineTab (SFX guy at 100% MP4, endless off, the
 * native wall off - every picture through this set), by recording the
 * station's /api/dj/video ring every 2 s and the tablet's set every second
 * over CDP. The pictures that never came up were never fetched-and-failed:
 * the set THREW THEM AWAY as "missed" because
 *
 *   1. its queue was ARRIVAL order - a sting rung 70 s ahead of its air sat
 *      at the head, and the board's silent pictures due before it queued
 *      behind it and expired there;
 *   2. a silent picture (the picture of a board clip whose sound is already
 *      in the round) was held to the 8 s LATE rule for stings;
 *   3. a clip sat on its last frame for 11 s before `ended`.
 *
 * These tests REPLAY the two recorded windows through the set's own
 * scheduler - next(), missed(), queueTrim(), airInto() and queueOrder()
 * lifted out of the SHIPPED file - with a stub clock, and count what comes
 * up. Run against the pre-fix file (SFX_TV_SRC=...) the replays fail with
 * the misses the tablet showed.
 *
 *     node --test tests/test_sfx_tv_vidmiss_2026_09_28.cjs
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const SRC = process.env.SFX_TV_SRC
  || path.join(__dirname, '..', 'desktop', 'renderer', 'sfx-tv.js');
const source = fs.readFileSync(SRC, 'utf8').replace(/\r\n/g, '\n');

function fn(name, optional) {
  const at = source.indexOf('function ' + name + '(');
  if (at < 0 && optional) return null;
  assert.ok(at >= 0, 'no function ' + name + ' in ' + SRC);
  let depth = 0;
  for (let i = source.indexOf('{', at); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(at, i + 1);
    }
  }
  throw new Error('unterminated ' + name);
}

function num(name, fallback) {
  const m = new RegExp('var\\s+' + name + '\\s*=\\s*([0-9.]+)\\s*;').exec(source);
  if (!m && fallback !== undefined) return fallback;
  assert.ok(m, 'no constant ' + name);
  return Number(m[1]);
}

const HAS_TAIL_WATCH = source.includes('var tailWatch = setInterval(');

/* The tablet's measured costs (2026-09-28, tab2.jsonl): a picture is up
   ~1.5 s after next() hands it to play() (timer + blob decode + CRT), and
   the collapse + teardown rest is OFF_MS + 120 ms. */
const START_S = 1.5;
const OFF_S = (num('OFF_MS') + 120) / 1000;
const POLL_S = num('POLL_MS') / 1000;

/* One run of the set's own scheduler over a recorded ring. */
function replay(rows) {
  const body = [
    fn('queueOrder', true) || 'function queueOrder() {}',
    fn('queueTrim'), fn('missed'), fn('airInto'), fn('next'),
  ].join('\n');
  const names = ['now', 'setTimeout', 'clearTimeout', 'play', 'videoReceipt',
    'warmSync', 'warmUp', 'reportNow', 'state', 'LATE', 'SILENT_TAIL',
    'QUEUE_ROWS_MOST', 'QUEUE_AHEAD_S'];
  const glue = `
    var queue = state.queue;
    var reportUp = false, endlessOn = false, mounted = true;
    Object.defineProperty(state, 'showing', {get: function () { return showing; },
      set: function (v) { showing = v; }});
    Object.defineProperty(state, 'hold', {get: function () { return hold; },
      set: function (v) { hold = v; }});
    var showing = false, hold = null;
    ${body}
    return {next: next, queueTrim: queueTrim, airInto: airInto};`;
  // eslint-disable-next-line no-new-func
  const make = new Function(...names, glue);

  let T = 0;
  const timers = [];
  let seq = 0;
  const state = {queue: []};
  const shown = [];
  const dropped = [];
  const api = make(
    () => T,
    (f, ms) => { const t = {at: T + Math.max(0, ms), f, id: ++seq}; timers.push(t); return t; },
    (t) => { const i = timers.indexOf(t); if (i >= 0) timers.splice(i, 1); },
    (clip) => {
      /* the tube: joined where its sound is (airInto), held for what is
         left of it, and a clip that stalls on its last frame holds it for
         the stall - or for the tail watch, where the shipped file has one */
      const into = api.airInto(clip);
      let stall = clip.stall || 0;
      if (stall && HAS_TAIL_WATCH) stall = Math.min(stall, num('TAIL_STALL_MS') / 1000 + 0.5);
      shown.push({id: clip.id, late: (T - clip.at) / 1000});
      const hold = (START_S + Math.max(0, clip.seconds - into) + stall + OFF_S) * 1000;
      timers.push({at: T + hold, id: ++seq, f: () => { state.showing = false; api.next(); }});
    },
    (clip, ev) => { if (ev === 'error') dropped.push(clip.id); },
    () => {}, () => {}, () => false,
    state, num('LATE'), num('SILENT_TAIL', 0), num('QUEUE_ROWS_MOST'), num('QUEUE_AHEAD_S'));

  const t0 = Math.min(...rows.map((r) => r.seen)) - 1;
  const arrivals = rows.map((r) => Object.assign({}, r, {
    at: (r.air - t0) * 1000, seen: Math.round((r.seen - t0) * 10) * 100, delivery_id: r.id}));
  const end = Math.max(...arrivals.map((r) => r.at + r.seconds * 1000)) + 60000;
  let nextPoll = 0;
  while (T <= end) {
    arrivals.filter((r) => r.seen === T).forEach((clip) => {
      state.queue.push(clip);                 /* offer(): push, trim, next */
      api.queueTrim();
      api.next();
    });
    if (T >= nextPoll) {                      /* poll(): drop the hold, next */
      nextPoll += POLL_S * 1000;
      if (state.hold) { timers.splice(timers.indexOf(state.hold), 1); state.hold = null; }
      api.next();
    }
    timers.sort((a, b) => a.at - b.at || a.id - b.id);
    while (timers.length && timers[0].at <= T) {
      const t = timers.shift();
      if (t === state.hold) state.hold = null;
      t.f();
    }
    T += 100;
  }
  return {shown, dropped};
}

/* ---------------- the two windows recorded on the tablet, 2026-09-28 ----
   air/seen are the station's seconds (mod 10000); seen is when the ring
   first carried the row. `silent` = a board clip's picture (its sound is in
   the round). ring2.jsonl / ring.jsonl in the vidmiss scratch folder. */
const ROUND2 = [
  {id: '35b836bf', air: 2892.9, seconds: 7.04, seen: 2890.0, silent_picture: true},
  {id: '1c1de84b', air: 2980.2, seconds: 12.28, seen: 2910.0},
  {id: 'b79ab189', air: 2930.6, seconds: 4.36, seen: 2930.3, silent_picture: true},
  {id: '0e9ce7eb', air: 2954.4, seconds: 5.99, seen: 2949.0, silent_picture: true},
  {id: '48f42c7d', air: 3012.3, seconds: 13.75, seen: 2959.6},
];

const ROUND1 = [
  {id: 'fc53ddf0', air: 2420.8, seconds: 9.66, seen: 2407.7},
  /* this one sat on its last frame from ~469.2 to ~480.4 */
  {id: '8dc5cbb6', air: 2457.7, seconds: 8.88, seen: 2451.2, stall: 11.2},
  {id: '5ec39606', air: 2472.7, seconds: 12.84, seen: 2467.1},
  {id: '72cd9cb4', air: 2486.4, seconds: 4.22, seen: 2481.3, silent_picture: true},
  {id: 'dae9e1d9', air: 2527.1, seconds: 18.83, seen: 2521.7},
];

test('replay 1: pictures due before a sting rung far ahead are not stuck behind it', () => {
  const got = replay(ROUND2);
  /* On the tablet: b79ab189 and 0e9ce7eb expired behind 1c1de84b (queue
     3 -> 1 at 2994.4). Every one of them must come up now. */
  assert.deepEqual(got.dropped, [], 'thrown away as missed: ' + got.dropped.join(', '));
  assert.deepEqual(got.shown.map((s) => s.id).sort(), ROUND2.map((r) => r.id).sort());
  const late = Object.fromEntries(got.shown.map((s) => [s.id, s.late]));
  assert.ok(late.b79ab189 < 1 && late['0e9ce7eb'] < 1,
    'the board pictures come up at their own moment, not after the sting: '
    + JSON.stringify(late));
});

test('replay 2: a clip stuck on its last frame does not cost the pictures after it', () => {
  const got = replay(ROUND1);
  /* On the tablet: 72cd9cb4 (the silent picture of "95 Oh, what do you")
     was thrown away behind 5ec39606, which started 9 s late because
     8dc5cbb6 held the tube 11 s past its end. */
  assert.deepEqual(got.dropped, [], 'thrown away as missed: ' + got.dropped.join(', '));
  assert.equal(got.shown.length, ROUND1.length);
});

test('a silent picture is joined where its sound is, a sting is not', () => {
  const body = fn('airInto');
  // eslint-disable-next-line no-new-func
  const airInto = new Function('now', body + '\nreturn airInto;')(() => 10000);
  assert.equal(airInto({at: 6000, silent_picture: true, seconds: 8}), 4,
    'four seconds into its sound: the picture joins there');
  assert.equal(airInto({at: 6000, seconds: 8}), 0,
    'a sting is punctuation - it starts at its own first frame');
  assert.equal(airInto({at: 6000, endless: true, seconds: 8}), 4);
});

test('a silent picture is late only once its sound has run', () => {
  const body = fn('missed');
  // eslint-disable-next-line no-new-func
  const missed = new Function('now', 'LATE', 'SILENT_TAIL', body + '\nreturn missed;')(
    () => 20000, num('LATE'), num('SILENT_TAIL', 0));
  /* 10 s late, 12 s long: 2 s of its sound are still in the room */
  assert.equal(missed({at: 10000, seconds: 12, silent_picture: true}), false);
  /* 10 s late, 10.5 s long: under a second left - not worth the set */
  assert.equal(missed({at: 10000, seconds: 10.5, silent_picture: true}), true);
  /* a sting keeps #1173's LATE rule */
  assert.equal(missed({at: 10000, seconds: 30}), true);
  assert.equal(missed({at: 15000, seconds: 30}), false);
});

test('the queue is air order, stable, and rows with no stamp keep their place', () => {
  const body = fn('queueOrder');
  const order = (rows) => {
    const queue = rows.slice();
    // eslint-disable-next-line no-new-func
    new Function('queue', body + '\nqueueOrder();')(queue);
    return queue.map((r) => r.id);
  };
  assert.deepEqual(order([{id: 'far', at: 80}, {id: 'near', at: 30}, {id: 'mid', at: 50}]),
    ['near', 'mid', 'far']);
  assert.deepEqual(order([{id: 'a', at: 50}, {id: 'b', at: 50}, {id: 'c', at: 10}]),
    ['c', 'a', 'b'], 'ties keep arrival order');
  assert.deepEqual(order([{id: 'x', at: 60}, {id: 'cut'}, {id: 'y', at: 20}]),
    ['y', 'x', 'cut'], 'a row with no stamp stays behind the row it followed');
  /* the endless runway alone is not touched (its order is the ring's) */
  assert.deepEqual(order([{id: 'w2', at: 9, endless: true}, {id: 'w1', at: 3, endless: true}]),
    ['w2', 'w1']);
});

test('the tail watch is in play(), bounded to the clip that armed it', () => {
  const play = fn('play');
  const at = play.indexOf('var tailWatch = setInterval(');
  assert.ok(at > 0, 'play() has no tail watch');
  const watch = play.slice(at, play.indexOf('}, 500);', at));
  assert.ok(/if \(done \|\| video !== screen\) \{ clearInterval\(tailWatch\); return; \}/.test(watch),
    'every timer in this module outlives the clip that armed it - it must let go');
  assert.ok(watch.includes('screen.paused') && watch.includes('JOIN_TAIL'),
    'only an UNPAUSED playhead at the very end is a stall');
  assert.ok(/passed = true;\s*ended\(\);/.test(watch), 'it takes the road `ended` takes');
});
