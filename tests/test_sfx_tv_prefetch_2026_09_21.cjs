/* #1421: THE SET DOES NOT SEEK THE CLIP IT IS PLAYING, AND IT HOLDS THE
 * BYTES BEFORE IT SHOWS THE PICTURE.
 *
 * Both halves of this failed SILENTLY and would again:
 *
 * 1. THE SEEK. Nothing reports a decode flush. The set re-seeking a clip
 *    it is halfway through looks, from every log and every counter on the
 *    station, exactly like a set playing a clip - the station is not even
 *    involved. It is visible only to somebody watching the tube, which is
 *    how it survived from #1173 to now. So the rule that decides whether
 *    a jump is worth making is tested as arithmetic, against the clip
 *    lengths the endless set actually serves.
 *
 * 2. THE CACHE. A pre-fetch that quietly does nothing is indistinguishable
 *    from one that works, right up until the tube stalls; a pre-fetch that
 *    revokes the object URL of the clip currently playing is a BLACK TUBE
 *    with no error anywhere. And every one of its failure paths has to
 *    hand back the station's own URL, because an optimisation that can
 *    fail the picture is not one.
 *
 * The functions are lifted out of the SHIPPED file rather than copied, so
 * this cannot drift from what actually runs.
 *
 *     node --test tests/test_sfx_tv_prefetch_2026_09_21.cjs
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const SRC = process.env.SFX_TV_SRC
  || path.join(__dirname, '..', 'desktop', 'renderer', 'sfx-tv.js');
const source = fs.readFileSync(SRC, 'utf8');

/* ------------------------------------------------- lifting the source */

function fn(name) {
  const at = source.indexOf('function ' + name + '(');
  assert.ok(at >= 0, 'no function ' + name + ' in ' + SRC);
  let depth = 0;
  let i = source.indexOf('{', at);
  const from = i;
  for (; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    else if (source[i] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(at, i + 1);
    }
  }
  throw new Error('unterminated ' + name);
}

function num(name) {
  const m = new RegExp('var\\s+' + name + '\\s*=\\s*([0-9.*\\s]+);').exec(source);
  assert.ok(m, 'no constant ' + name);
  // eslint-disable-next-line no-eval
  return eval(m[1]);
}

const SLIP_MAX = num('SLIP_MAX');
const SLIP_SHARE = num('SLIP_SHARE');
const JOIN_MIN = num('JOIN_MIN');
const CACHE_MOST = num('CACHE_MOST');
const CACHE_BYTES_MOST = num('CACHE_BYTES_MOST');
const CACHE_FILE_MOST = num('CACHE_FILE_MOST');

/* One sandbox holding the real function text and stubs for everything it
   reaches outside itself. */
function sandbox(opts) {
  const it = opts || {};
  const box = {
    now: () => Date.now(),
    base: 'http://station',
    video: it.video || null,
    warm: it.warm || null,
    mounted: true,
    cache: [],
    fetching: Object.create(null),
    revoked: [],
    made: 0,
    asked: [],
    SLIP_MAX, SLIP_SHARE, JOIN_MIN,
    CACHE_MOST, CACHE_BYTES_MOST, CACHE_FILE_MOST,
  };
  box.URL = {
    createObjectURL(blob) {
      box.made += 1;
      return 'blob:' + box.made + ':' + blob.size;
    },
    revokeObjectURL(href) { box.revoked.push(href); },
  };
  box.fetch = it.fetch || function (url) {
    box.asked.push(url);
    return Promise.resolve({
      ok: true,
      headers: {get: () => String(it.bytes || 1000)},
      blob: () => Promise.resolve({size: it.bytes || 1000}),
    });
  };
  const body = [
    fn('srcOf'), fn('cacheFind'), fn('cacheHeld'), fn('cacheTrim'),
    fn('canHold'), fn('preFetch'), fn('heldSrc'), fn('worthSeeking'),
  ].join('\n');
  const keys = Object.keys(box);
  // eslint-disable-next-line no-new-func
  const build = new Function(keys.join(','), body
    + '\nreturn {srcOf, cacheFind, cacheTrim, canHold, preFetch, heldSrc,'
    + ' worthSeeking, box: {get cache() { return cache; },'
    + ' get fetching() { return fetching; }}};');
  const api = build.apply(null, keys.map((k) => box[k]));
  api.stub = box;
  return api;
}

const clip = (n) => ({url: '/sfx/' + n + '?t=sig' + n, endless: true});

/* ------------------------------------------- 1. the seek that chokes */

test('a jump must be small against the clip it lands in', () => {
  const s = sandbox();
  const worth = s.worthSeeking;

  /* THE CASE THAT WAS CHOKING. The endless set serves 2-3.5 s clips
     (measured off the live ring: length 2.02 and 3.44 in 6.0 s slots),
     and a clip that starts 0.8 s late is permanently 0.8 s behind a
     clock that keeps climbing. Before #1421 that re-seeked every
     SLIP_REST for the whole clip. */
  assert.equal(worth(0.8, 2.02, SLIP_MAX), false,
    '0.8s is 40% of a 2.02s clip - seeking it flushes the decoder to '
    + 'throw away nearly half the picture');
  assert.equal(worth(0.9, 3.44, SLIP_MAX), false);

  /* AND THE CASE #1173 WAS BUILT FOR IS UNTOUCHED: the tablet whose
     WebView slept, on a long wallpaper clip, still gets put back. */
  assert.equal(worth(8.0, 60.0, SLIP_MAX), true,
    'a quarter of a minute is fifteen seconds of allowance');
  assert.equal(worth(2.0, 20.0, SLIP_MAX), true);

  /* The old rule survives inside the new one: a drift too small to be
     worth correcting is still not corrected, however long the clip. */
  assert.equal(worth(0.5, 60.0, SLIP_MAX), false);
  assert.equal(worth(0.5, 60.0, JOIN_MIN), true, 'the join starts lower');

  /* Exactly on the share bound is allowed; past it is not. */
  assert.equal(worth(5.0, 20.0, SLIP_MAX), true);
  assert.equal(worth(5.01, 20.0, SLIP_MAX), false);

  /* A duration we do not have yet is a reason to leave the decoder
     alone, not a reason to guess. */
  assert.equal(worth(2.0, NaN, SLIP_MAX), false);
  assert.equal(worth(2.0, 0, SLIP_MAX), false);
  assert.equal(worth(NaN, 20.0, SLIP_MAX), false);

  /* It is the SIZE of the jump, not its direction - a clip ahead of the
     station chokes exactly as hard as one behind it. */
  assert.equal(worth(-0.8, 2.02, SLIP_MAX), false);
  assert.equal(worth(-8.0, 60.0, SLIP_MAX), true);
});

/* --------------------------------------------- 2. holding the bytes */

test('a clip is fetched whole, once, and played from memory', async () => {
  const s = sandbox({bytes: 600000});
  const one = clip('aaa');

  assert.equal(s.heldSrc(one), 'http://station/sfx/aaa?t=sigaaa',
    'before the fetch, the station is the answer');

  const href = await s.preFetch(one);
  assert.match(href, /^blob:/);
  assert.equal(s.heldSrc(one), href, 'after it, the bytes are');
  assert.equal(s.stub.asked.length, 1);

  /* Asked ONCE, however many times it airs - and a second ask while the
     first is still in flight joins it rather than starting another. */
  await s.preFetch(one);
  const together = await Promise.all([s.preFetch(clip('bbb')),
    s.preFetch(clip('bbb'))]);
  assert.equal(together[0], together[1]);
  assert.equal(s.stub.asked.length, 2, 'two clips, two fetches');
});

test('every way it can fail hands back the station URL', async () => {
  const url = 'http://station/sfx/ccc?t=sigccc';

  const refused = sandbox({fetch: () => Promise.resolve({ok: false,
    status: 404, headers: {get: () => '10'}})});
  assert.equal(await refused.preFetch(clip('ccc')), null);
  assert.equal(refused.heldSrc(clip('ccc')), url, 'a 404 is not a black tube');

  const thrown = sandbox({fetch: () => Promise.reject(new Error('CORS'))});
  assert.equal(await thrown.preFetch(clip('ccc')), null);
  assert.equal(thrown.heldSrc(clip('ccc')), url,
    'a cross-origin shell without CORS plays off the station, as before');

  /* A clip too big to hold streams, exactly as it used to. */
  const huge = sandbox({bytes: CACHE_FILE_MOST + 1});
  assert.equal(await huge.preFetch(clip('ccc')), null);
  assert.equal(huge.heldSrc(clip('ccc')), url);

  /* And a failed clip is not remembered as in-flight for ever. */
  assert.deepEqual(Object.keys(thrown.box.fetching), []);

  /* No fetch at all in this runtime: the whole road is skipped and the
     set behaves as it did before #1421. */
  const bare = sandbox();
  bare.stub.URL.createObjectURL = null;
  assert.equal(bare.canHold(), false);
  assert.equal(bare.preFetch(clip('ccc')), null);
});

test('the cache is bounded and never revokes what is on the tube',
  async () => {
    const s = sandbox({bytes: 1000});
    let i;
    for (i = 0; i < CACHE_MOST + 6; i += 1) {
      /* eslint-disable no-await-in-loop */
      await s.preFetch(clip('c' + i));
    }
    assert.ok(s.box.cache.length <= CACHE_MOST,
      'held ' + s.box.cache.length + ', cap is ' + CACHE_MOST);
    assert.ok(s.stub.revoked.length >= 6, 'the evicted ones were released');

    /* The newest survive; the oldest are the ones let go. */
    const urls = s.box.cache.map((row) => row.url);
    assert.ok(urls.some((u) => u.indexOf('c' + (CACHE_MOST + 5)) >= 0));
    assert.ok(!urls.some((u) => u.indexOf('/sfx/c0?') >= 0));
  });

test('the clip in the tube and the one warmed behind it are never let go',
  async () => {
    /* This is the one that is a BLACK TUBE if it is wrong, with no error
       anywhere: the budget comes due while the clip on screen is the
       oldest thing in the cache, and revoking its object URL pulls the
       picture out from under a playing element. */
    const holder = {src: ''};
    const warmEl = {src: ''};
    const s = sandbox({bytes: 1000, video: holder, warm: {el: warmEl}});

    const onTube = await s.preFetch(clip('keep-me'));
    const onDeck = await s.preFetch(clip('keep-me-too'));
    holder.src = onTube;
    warmEl.src = onDeck;

    let i;
    for (i = 0; i < CACHE_MOST + 8; i += 1) {
      /* eslint-disable no-await-in-loop */
      await s.preFetch(clip('filler' + i));
    }
    assert.ok(!s.stub.revoked.includes(onTube),
      'the clip being played was revoked - that is a black tube');
    assert.ok(!s.stub.revoked.includes(onDeck),
      'the warmed clip was revoked - that is a stalled hand-over');
    assert.equal(s.heldSrc(clip('keep-me')), onTube);
  });

test('the memory budget is enforced as well as the count', async () => {
  /* Ten clips is a cheap cap when they are 600 kB and a ruinous one when
     they are twenty megabytes, which is why there are two bounds. */
  const big = Math.floor(CACHE_BYTES_MOST / 3);
  const s = sandbox({bytes: big});
  let i;
  for (i = 0; i < 6; i += 1) {
    /* eslint-disable no-await-in-loop */
    await s.preFetch(clip('big' + i));
  }
  const held = s.box.cache.reduce((sum, row) => sum + row.bytes, 0);
  assert.ok(held <= CACHE_BYTES_MOST,
    'holding ' + held + ' bytes, budget is ' + CACHE_BYTES_MOST);
  assert.ok(s.box.cache.length < CACHE_MOST,
    'the byte bound bit before the count bound did');
});

/* ------------------------------- 3. WHICH seek the bound is put on */

test('the bound is on the hold, not on the join', () => {
  /* #1421b. I first put the share bound on both seeks, and
     test_sfx_tv_2026_09_12.cjs caught it: "a late endless clip is JOINED
     where the station is, not restarted" went red, because bounding the
     JOIN throws away the whole of #1173 - two surfaces on the same
     frame, and drift that cannot ratchet (+1.16 s a clip when it does).
     The two seeks are not the same seek. The join happens ONCE, before a
     frame is shown, and costs nothing to look at. The hold happens over
     and over on a picture somebody is already watching, and THAT is the
     decode flush.

     This reads the shipped file because the distinction is invisible
     from behaviour until somebody is watching a tube. */
  const join = source.slice(source.indexOf('var joinNow = function'),
    source.indexOf('screen.addEventListener(\'loadedmetadata\', joinNow)'));
  assert.ok(join.length > 60, 'joinNow not found - has it been renamed?');
  assert.ok(!join.includes('worthSeeking'),
    'the JOIN must not be share-bounded: that is #1173 itself, and '
    + 'bounding it puts the surfaces back on different frames');

  const hold = source.slice(source.indexOf('var fixedAt = 0;'),
    source.indexOf('if (isFinite(to) && to > 0) {'));
  assert.ok(hold.length > 60, 'the slip handler not found');
  assert.ok(hold.includes('worthSeeking'),
    'the HOLD must be share-bounded: unbounded, it re-seeks a 2s clip '
    + 'every SLIP_REST for an 0.8s start delay that never closes');
});

/* ------------------------ 4. timed dialogue cues are not endless runway */

function trimQueue(clips) {
  const queue = clips.slice();
  const body = fn('queueTrim');
  // eslint-disable-next-line no-new-func
  const trim = new Function('queue', 'QUEUE_ROWS_MOST', 'QUEUE_AHEAD_S',
    body + '\nqueueTrim(); return queue;');
  return trim(queue, 24, 30);
}

test('a long dialogue round keeps its nearest timed MP4 cues', () => {
  const due = Array.from({length: 8}, (_, i) => ({
    id: 'cue-' + i,
    at: 1000 + i * 20000,
    seconds: 10,
    endless: false,
  }));
  const kept = trimQueue(due);
  assert.deepEqual(kept.map((clip) => clip.id), due.map((clip) => clip.id),
    'the 30-second endless runway discarded line-timed cues from the front');
});

test('the endless set still keeps only its bounded runway', () => {
  const endless = Array.from({length: 8}, (_, i) => ({
    id: 'wall-' + i,
    seconds: 10,
    endless: true,
  }));
  const kept = trimQueue(endless);
  assert.deepEqual(kept.map((clip) => clip.id), ['wall-5', 'wall-6', 'wall-7']);
});

test('the timed cue row guard discards the farthest future cue', () => {
  const due = Array.from({length: 27}, (_, i) => ({
    id: 'cue-' + i,
    at: 1000 + i * 20000,
    seconds: 2,
    endless: false,
  }));
  const kept = trimQueue(due);
  assert.equal(kept.length, 24);
  assert.equal(kept[0].id, 'cue-0');
  assert.equal(kept[23].id, 'cue-23');
});
