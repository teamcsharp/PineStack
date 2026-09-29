/* [hcprev] "When I swipe up from the bottom right corner, it's supposed to
 * basically play the previous clip that played, but in my case it's not
 * doing that." (operator, 2026-09-29)
 *
 * The corner resolved "the last clip" from the /api/dj chat ring (a PUBLISH
 * log, array order) and then opened the H3 stinger maker on every replay.
 * The chat ring below was recorded on the PineTab at the moment of the
 * complaint's aftermath: "29 So when you try" sat in it 330 s ahead of its
 * air_at, and the newest row ("68 shark things") was an audio cadence sample
 * the set never showed.
 *
 *     node --test tests/test_hot_corner_previous_clip_2026_09_29.cjs
 * HOT_CORNERS_SRC=... points it at another copy (the kiosk's, a pre-fix one).
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const path = require('node:path');

const SRC = process.env.HOT_CORNERS_SRC
  || path.join(__dirname, '..', 'desktop', 'renderer', 'hot-corners.js');

/* Recorded 2026-09-29 on the PineTab (tail of the chat ring's sfx rows). */
const CHAT = [
  {kind: 'sfx', text: '\u{1F50A} 29 So when you try', ts: 1790661081, air_at: 1790661410.76, sfx_sample_id: '6c2cabd9bdfc5376'},
  {kind: 'sfx', text: '26 with Tommy. I', ts: 1790661451, air_at: 1790661451.84, video: true, url: '/sfx/aaaaaaaaaaaaaaa1?t=x'},
  {kind: 'sfx', text: '1268 shortly. Mr', ts: 1790661466, air_at: 1790661476.33, video: true, url: '/sfx/aaaaaaaaaaaaaaa2?t=x'},
  {kind: 'sfx', text: '27 glass there', ts: 1790661472, air_at: 1790661495.95, video: true, url: '/sfx/aaaaaaaaaaaaaaa3?t=x'},
  {kind: 'sfx', text: '106 clip-3', ts: 1790661473, air_at: 1790661473.60, video: false, url: '/sfx/aaaaaaaaaaaaaaa4?t=x'},
  {kind: 'chat', text: 'a spoken line', ts: 1790661480},
  {kind: 'sfx', text: '\u{1F50A} 11 clip-63', ts: 1790661483, air_at: 1790661517.03, sfx_sample_id: 'f635007400ff8e12'},
  {kind: 'sfx', text: '707 Look who we', ts: 1790661534, air_at: 1790661534.21, video: true, url: '/sfx/427f2fbce024a0c9?t=x'},
  {kind: 'sfx', text: '\u{1F50A} 68 shark things', ts: 1790661547, air_at: 1790661559.29, sfx_sample_id: '422208aa9e5a4e39'},
];
const T = 1790661575 * 1000;   /* the probe's clock */

function load() {
  delete require.cache[require.resolve(SRC)];
  return require(SRC);
}

test('the resolver exists and is exported', () => {
  const hc = load();
  assert.equal(typeof hc._previousClip, 'function', 'no _previousClip in ' + SRC);
});

test('the SFX TV play ring wins over every chat row', () => {
  const hc = load();
  const played = [
    {id: 'd1e0000000000a01', url: '/sfx/d1e0000000000a01?t=1', sting: 'Demon Erasers - Unrest', at: T - 20000},
    {id: 'd1e0000000000a02', url: '/sfx/d1e0000000000a02?t=2', sting: 'Demon Erasers - Dystopia', at: T - 9000},
  ];
  const got = hc._previousClip(played, CHAT, T);
  assert.equal(got.from, 'tv');
  assert.equal(got.row.sting, 'Demon Erasers - Dystopia');
});

test('a clip that went up a moment ago is the set rolling on: the one before it', () => {
  const hc = load();
  const played = [
    {url: '/a', sting: 'just finished', at: T - 30000},
    {url: '/b', sting: 'rolled on as the finger moved', at: T - 1200},
  ];
  assert.equal(hc._previousClip(played, [], T).row.sting, 'just finished');
  assert.equal(hc._previousClip(played, [], T + 5000).row.sting, 'rolled on as the finger moved');
  /* alone, even a fresh one is the answer */
  assert.equal(hc._previousClip([played[1]], [], T).row.sting, 'rolled on as the finger moved');
});

test('rows without a url in the play ring are ignored', () => {
  const hc = load();
  const played = [{url: '/a', sting: 'real', at: T - 9000}, {url: '', sting: 'broken', at: T - 8000}];
  assert.equal(hc._previousClip(played, [], T).row.sting, 'real');
});

test('chat fallback: newest by AIR time, not array order, and only what has aired', () => {
  const hc = load();
  /* by array order the newest replayable row is "68 shark things"; at T it
     has aired and its air_at is the latest - it is the answer at T */
  assert.equal(hc._previousClip([], CHAT, T).row.text, '\u{1F50A} 68 shark things');
  /* ten seconds earlier it was published but not aired: the newest AIRED
     row is "707 Look who we" (the old resolver named "68 shark things") */
  const early = 1790661550 * 1000;
  assert.equal(hc._previousClip([], CHAT, early).row.text, '707 Look who we');
  assert.equal(hc._lastSfx(CHAT).text, '\u{1F50A} 68 shark things');
  /* "29 So when you try" was published at 1790661081 but aired at
     1790661410: in between it is not "the clip that just played" */
  const mid = 1790661300 * 1000;
  assert.equal(hc._previousClip([], CHAT.slice(0, 1), mid), null);
  /* air order beats array order: "27 glass there" (air 495.9) sits BEFORE
     "106 clip-3" (air 473.6) in the ring */
  const at500 = 1790661500 * 1000;
  assert.equal(hc._previousClip([], CHAT, at500).row.text, '27 glass there');
});

test('nothing played anywhere: null (the corner says so)', () => {
  const hc = load();
  assert.equal(hc._previousClip([], [], T), null);
  assert.equal(hc._previousClip(null, [{kind: 'chat', text: 'x', ts: 1}], T), null);
});

test('the corner replays the set\'s last clip and does NOT open the H3 stinger sheet', async () => {
  const cuts = [];
  const gets = [];
  const saved = {PineSfxTv: globalThis.PineSfxTv, pineDesktop: globalThis.pineDesktop};
  globalThis.PineSfxTv = {
    played: () => [
      {id: 'd1e0000000000a01', url: '/sfx/d1e0000000000a01?t=1', sting: 'Unrest', video: true, at: Date.now() - 20000},
      {id: 'd1e0000000000a02', url: '/sfx/d1e0000000000a02?t=2', sting: 'Dystopia', video: true, at: Date.now() - 9000},
    ],
    cut: (clip) => { cuts.push(clip); return true; },
  };
  globalThis.pineDesktop = {
    get: (p) => {
      gets.push(p);
      if (p === '/api/dj') return Promise.resolve({chat: CHAT});
      const m = /^\/api\/sfx\/([0-9a-f]{16})\/replay-source$/.exec(p);
      return Promise.resolve(m ? {id: m[1], name: m[1] === 'd1e0000000000a02' ? 'Dystopia' : '?', url: '/sfx/' + m[1] + '?t=fresh', video: true, seconds: 3} : {});
    },
    post: () => Promise.reject(new Error('the replay must not post anything')),
  };
  try {
    const hc = load();
    hc.act('sfx');
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(cuts.length, 1);
    assert.equal(cuts[0].id, 'd1e0000000000a02');
    assert.equal(cuts[0].sting, 'Dystopia');
    assert.ok(!gets.includes('/api/dj'), 'the set had a history: the chat ring must not be asked');
    assert.equal(typeof hc.stinger, 'function', 'the stinger sheet keeps an explicit door');
  } finally {
    globalThis.PineSfxTv = saved.PineSfxTv;
    globalThis.pineDesktop = saved.pineDesktop;
  }
});

test('the replay road never calls the stinger sheet (source)', () => {
  const src = require('node:fs').readFileSync(SRC, 'utf8').replace(/\r\n/g, '\n');
  const start = src.indexOf('  function replaySfx() {');
  const end = src.indexOf('/* ----------------------------------------------------------- "report" */');
  assert.ok(start > 0 && end > start);
  assert.ok(!/offerReplayStinger\(/.test(src.slice(start, end)), 'replaySfx/replayRow still open the H3 sheet');
});
