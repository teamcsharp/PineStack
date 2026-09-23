/* The Listen and Music views, pinned where they can be pinned.
 *
 * Both views are DOM over one body of arithmetic (listen-model.js), and
 * it is the arithmetic that can be got wrong silently: a playhead that is
 * off by the difference between two machines' clocks, a "nothing is
 * playing" that reads as fifty-eight years into a record, a grab that
 * offers a moment whose audio the station swept two days ago. Those are
 * the things here. What is NOT here, said plainly: whether the screen
 * looks right, and whether it is legible from across a room. Neither is
 * knowable from node.
 *
 * Two constraints are load-bearing and are tested as behaviour rather
 * than left as comments:
 *
 *   THE SINGLE POLLER. Measured 2026-09-11 - 38 concurrent requests in
 *   flight to the station produced a 46-second media stall on the tablet,
 *   which is why it was playing no audio at all. Every live number on
 *   both views therefore has to be derivable from ONE /api/dj payload.
 *   The tests below build a single payload and take the now-playing, the
 *   playhead, what is next, the queue and the recently-played out of it,
 *   which is the proof that no second request is needed for any of them.
 *
 *   NO lean=1. DJ_LEAN_DROP (app.py:94128) removes stream_now and
 *   truncates chat to 20 rows. The last test pairs this model with
 *   lcd-dialogue.js and shows exactly what is lost: on the coalesced
 *   road - which is most of the broadcast - a lean payload has no line
 *   on air at all, so the headline silently falls back to the record and
 *   the grab button has nothing to take.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const model = require('../desktop/renderer/listen-model.js');
const {stationRows} = require('../desktop/renderer/lcd-dialogue.js');

const RENDERER = path.join(__dirname, '..', 'desktop', 'renderer');
const read = (name) => fs.readFileSync(path.join(RENDERER, name), 'utf8');

/* A fixed wall-clock moment, so nothing in here depends on when it runs. */
const T = 1789000000000;               /* the station's clock, in ms */

/* One /api/dj payload, in the shape dj_state() actually emits
 * (app.py:25212). Every field used below is really on it. */
function payload(extra) {
  return Object.assign({
    station: 'Pine Box FM',
    station_name: 'Pine Box FM',
    on: true,
    paused: false,
    server_ms: T,
    started_ms: T - 61000,             /* the record started 61s ago */
    remaining: 139.0,
    now: {id: 'trk1', title: 'Blue Ridge', artist: 'The Pines',
      album: 'Long Shadow', seconds: 200,
      url: '/music/trk1?t=sig', art: '/music/trk1/art?t=sig'},
    coming: null,
    upcoming: [
      {id: 'trk2', title: 'Second Wind', artist: 'The Pines'},
      {id: 'trk3', title: 'Third Rail', artist: 'Someone Else'}
    ],
    requests: 1,
    played: [
      {id: 'trk0', title: 'Before This', artist: 'The Pines'},
      {id: 'trkA', title: 'Older Still', artist: 'Another'}
    ],
    speaking_now: null,
    stream_now: null,
    chat: []
  }, extra || {});
}

/* ------------------------------------------------------------- the clock */

test('skew is cancelled: two terminals with wildly different clocks agree', () => {
  /* This is the whole reason server_ms exists (app.py:21821). One machine
   * believes it is the station's time; the other is half an hour fast.
   * Both must put the needle in the same place. */
  const honest = T;                    /* Date.now() here equals the station */
  const fast = T + 30 * 60000;         /* thirty minutes ahead */

  const a = model.skewOf(payload(), honest);
  const b = model.skewOf(payload(), fast);
  assert.equal(a, 0);
  assert.equal(b, -30 * 60000, 'a fast local clock gives a negative skew');

  /* Each applies its own skew to its own Date.now() and asks the model. */
  const oneSecondLater = 1000;
  const pa = model.playhead(payload(), honest + oneSecondLater + a);
  const pb = model.playhead(payload(), fast + oneSecondLater + b);
  assert.equal(pa.position, pb.position);
  assert.equal(pa.position, 62, '61s at the poll, one second of local tick');
});

test('the playhead needs no second poller - it is (clock - started_ms)', () => {
  /* The desktop polls /api/radio/clock (app.py:93327) purely for this and
   * computes (server_ms - started_ms)/1000 + age (app.py:154655). With a
   * skew-corrected clock the two are the same number, so neither view
   * asks that route. Four ticks of the shared 250 ms interpolation: */
  const seen = [0, 250, 500, 750].map(
    (ms) => model.playhead(payload(), T + ms).position);
  assert.deepEqual(seen, [61, 61.25, 61.5, 61.75]);
});

test('nothing playing is not fifty-eight years into a record', () => {
  /* started_ms is 0 when `now` is falsy (app.py:21822), and (clock - 0)
   * is the whole Unix epoch. A view that trusted it drew a full progress
   * bar over silence. */
  const quiet = model.playhead(payload({now: null, started_ms: 0}), T);
  assert.equal(quiet.following, false);
  assert.equal(quiet.position, 0);
  assert.equal(quiet.length, 0);
  assert.equal(quiet.fraction, 0);
});

test('a paused station freezes the needle instead of walking off the end', () => {
  /* #1145: `elapsed` keeps running through a pause on this road, so an
   * extrapolated playhead marches past the end of a frozen record. The
   * station's own `remaining` is the only honest figure while paused. */
  const late = T + 10 * 60000;         /* ten minutes into the pause */
  const bar = model.playhead(payload({paused: true, remaining: 139}), late);
  assert.equal(bar.paused, true);
  assert.equal(bar.position, 61, '200 - 139, not 661');
  assert.equal(bar.remaining, 139);
  assert.ok(bar.fraction < 1);
});

test('the needle is clamped short of the run-out, as the follower is', () => {
  /* app.py:154657 clamps to seconds - 0.75 so a follower never seeks into
   * the run-out. Same clamp, for the display reason: 4:13 of 4:12 looks
   * broken even when the arithmetic is right. */
  const over = model.playhead(payload(), T + 300000);
  assert.equal(over.position, 199.25);
  assert.equal(over.fraction <= 1, true);
});

/* -------------------------------------------------------- what is on air */

test('the record keeps the headline while somebody speaks (#1206)', () => {
  /* Design decision, REVERSED on the evidence of a real screen. It used to
   * read the other way - a record sits for three minutes and a spoken line
   * lasts seconds, so leading with the record was argued to make the screen
   * look frozen through every round of banter.
   *
   * What that could not know: the spoken line is ALREADY on screen in the
   * marquee, so the headline was a second copy of it; and a gallery round's
   * line is a paragraph, which at headline size pushes the record, the
   * artist and the cover off the top of the view. The operator sent a
   * picture of exactly that and asked for it "just part of the scrolling
   * marquee with the text below".
   *
   * `kind` stays 'voice' - the speaker's name, the marquee and every other
   * reader still need to know somebody is talking. Only the headline moved. */
  const speaking = {id: 'ln1', who: 'dj', name: 'Caine',
    text: 'and that was the Pines, live at the fairground'};
  const now = model.nowPlaying(payload(), speaking, T);
  assert.equal(now.kind, 'voice', 'the booth is still reported as live');
  assert.equal(now.headline, 'Blue Ridge', 'the record holds the headline');
  assert.notEqual(now.headline, speaking.text,
    'the spoken line is in the marquee, not shouted over the song');
  assert.ok(now.sub.includes('The Pines'));
  assert.equal(now.track.title, 'Blue Ridge');
  assert.equal(now.bar.following, true);
});

test('with no record the voice still takes the headline (#1206)', () => {
  /* The boundary, and the reason the change is narrow. A screen reading
   * "quiet" while the pair are plainly talking is a worse lie than the one
   * being fixed, and the marquee alone is too small to carry the room. */
  const speaking = {id: 'ln2', who: 'dj', name: 'Caine',
    text: 'we are between records and still here'};
  const bare = payload();
  delete bare.now;
  const now = model.nowPlaying(bare, speaking, T);
  assert.equal(now.kind, 'voice');
  assert.equal(now.headline, 'we are between records and still here');
  assert.equal(now.sub, 'Caine');
});

test('with no voice the record is the headline', () => {
  const now = model.nowPlaying(payload(), null, T);
  assert.equal(now.kind, 'track');
  assert.equal(now.headline, 'Blue Ridge');
  assert.ok(now.sub.includes('The Pines'));
  assert.ok(now.sub.includes('Long Shadow'));
});

test('a turn with no text does not become a blank headline', () => {
  /* A stream_now turn carries only {id, from, until} (app.py:25405). If
   * no chat row supplies the words there is nothing to show, and showing
   * an empty headline over a playing record is worse than showing the
   * record. */
  const now = model.nowPlaying(payload(), {id: 'ghost', who: 'dj'}, T);
  assert.equal(now.kind, 'track');
  assert.equal(now.headline, 'Blue Ridge');
  assert.equal(now.voice.who, 'dj', 'the speaker is still known');
});

test('quiet says WHICH kind of quiet, because the three differ', () => {
  const off = model.nowPlaying(payload({on: false, now: null, started_ms: 0}),
    null, T);
  assert.equal(off.kind, 'quiet');
  assert.match(off.why, /not running/);

  const paused = model.nowPlaying(
    payload({paused: true, now: null, started_ms: 0}), null, T);
  assert.match(paused.why, /off air/);
  /* The booth keeps working through an air-pause and banks what it makes;
   * a screen that said "off" would be describing a stopped station. */
  assert.match(paused.why, /banking/);

  const between = model.nowPlaying(
    payload({now: null, started_ms: 0, talk_next_in: 12.4}), null, T);
  assert.match(between.why, /12s/);

  const nothing = model.nowPlaying(payload({now: null, started_ms: 0}), null, T);
  assert.match(nothing.why, /between records/);
});

/* -------------------------------------------------- next, queue, played */

test('what is next prefers the record being introduced', () => {
  /* `coming` exists (app.py:25252, #176/#178) precisely so a screen does
   * not leave the last track up as though it were still on. It is also
   * what the pair are talking about right now, so it outranks the queue. */
  const next = model.whatsNext(payload({
    coming: {id: 'trkX', title: 'Introduced Now', artist: 'Someone'}}));
  assert.equal(next.when, 'introducing');
  assert.equal(next.title, 'Introduced Now');
  assert.equal(next.queued, 2, 'the queue is still counted');
  assert.equal(next.requests, 1);
});

test('with nothing coming the queue head is next; with nothing at all, nothing', () => {
  assert.equal(model.whatsNext(payload()).when, 'queued');
  assert.equal(model.whatsNext(payload()).title, 'Second Wind');
  const bare = model.whatsNext(payload({upcoming: [], coming: null}));
  assert.equal(bare.when, 'nothing');
  assert.equal(bare.title, '');
});

test('the playlist and the recently-played cost no request at all', () => {
  /* `upcoming` is the next twenty queued/requested tracks (app.py:25283)
   * and `played` is the last ten, newest first (app.py:25368). Both ride
   * the feed both views are already subscribed to. This is the single
   * poller rule paying for itself. */
  const one = payload();
  assert.deepEqual(model.queueRows(one).map((t) => t.title),
    ['Second Wind', 'Third Rail']);
  assert.deepEqual(model.playedRows(one).map((t) => t.title),
    ['Before This', 'Older Still']);
  /* Missing fields never become the string "undefined" on screen. */
  const rough = model.queueRows({upcoming: [{id: 'x'}]})[0];
  assert.equal(rough.title, '');
  assert.equal(rough.artist, '');
  assert.equal(rough.seconds, 0);
});

/* ---------------------------------------------------------- the fetched */

test('the shelf is a sample and reports the library it came from', () => {
  /* /api/music/browse (app.py:93073) is not a catalogue listing: 35,000
   * tracks are too many to list, so it hands back a stable random sample.
   * The count is shown so "the shelf" is never read as "the library". */
  const rows = model.shelfRows({total: 35120, results: [
    {id: 'a', title: 'One', artist: 'X', url: '/music/a?t=s'},
    {id: '', title: 'Nameless'},
    {id: 'b', title: 'Two', artist: 'Y'}
  ]});
  assert.deepEqual(rows.map((r) => r.id), ['a', 'b'],
    'a row with no id cannot be asked for, so it is not offered');
  assert.equal(model.shelfTotal({total: 35120}), 35120);
});

test('the request book is the book, not the tally', () => {
  /* /api/dj/requested (app.py:95021) is every song asked for AND
   * fulfilled, newest first. /api/dj/requests is a different shape -
   * `top` ranked by count - and reading one as the other gives a list
   * that never changes. */
  const rows = model.requestRows({requested: [
    {title: 'Blue Ridge', artist: 'The Pines', count: 3, last: 1789000},
    {title: '', artist: 'nobody', count: 9}
  ]});
  assert.equal(rows.length, 1);
  assert.equal(rows[0].count, 3);
});

test('the running order is flattened across hours and trusts the booth', () => {
  /* #963: `past` must NOT be recomputed from the wall clock. The booth
   * seats its own walk wherever it was last seated, so a nominal walk of
   * the minutes greys out every remaining tile late in an hour whether or
   * not the booth reached them - "a screenful of grey". The station
   * already decides this (app.py:47629) and the model takes it as given. */
  const rows = model.scheduleRows({hours: [
    {key: '2026-09-11T21', label: '21:00', slots: [
      {id: 's1', kind: 'banter', label: 'Chat', minutes: 3,
        starts_at: '21:00', state: 'done', past: true, enabled: true},
      {id: 's2', kind: 'news', label: 'Bulletin', minutes: 2,
        starts_at: '21:03', state: 'on air', past: false, enabled: true},
      {id: 's3', kind: 'ad', label: 'Advert', minutes: 1,
        starts_at: '21:05', state: 'coming', past: false, enabled: false}
    ]},
    {key: '2026-09-11T22', label: '22:00', slots: [
      {id: 's4', kind: 'banter', label: 'Chat', minutes: 3,
        starts_at: '22:00', state: 'coming', past: false, enabled: true}
    ]}
  ]});
  assert.equal(rows.length, 4, 'both hours, one list');
  assert.equal(rows[1].live, true, 'state "on air" is the live entry');
  assert.equal(rows[0].past, true);
  assert.equal(rows[2].enabled, false, 'disabled is not the same as past');
  assert.equal(rows[2].past, false);
  assert.equal(rows[3].hour, '22:00');

  /* The cap is real: the sheet can run to 24 hours and this view shows
   * two, so a wider answer must not become a thousand rows of DOM. */
  const many = {hours: [{key: 'k', label: '00:00',
    slots: Array.from({length: 60}, (_, i) => ({id: 'x' + i, label: 'e'}))}]};
  assert.equal(model.scheduleRows(many, 24).length, 24);
});

/* ------------------------------------------------------------- gallery */

test('the backdrop takes stills only, and not the newspaper', () => {
  /* Stills, because /api/generations/image (app.py:112044) has no Range
   * support and Listen is the view most likely to be left running for
   * hours on a 4 GB tablet. The Gazette filter matches lcd-gallery.js: a
   * regenerated picture can keep gazette tags, so tags alone must never
   * hide an ordinary picture. */
  const files = model.galleryStills({generations: [
    {files: ['a nice picture-01.png', 'clip.mp4', 'shot.webm']},
    {kind: 'paper', files: ['gazette-3.png']},
    {model: 'gazette', files: ['front.png']},
    {tags: 'gazette edition', files: ['gazette-4.png']},
    {tags: 'gazette edition', files: ['ordinary.png']},
    {files: ['../../etc/passwd.png', 'sub/dir.png', 'a nice picture-01.png']},
    {files: ['fine.jpeg']}
  ]});
  assert.deepEqual(files,
    ['a nice picture-01.png', 'ordinary.png', 'fine.jpeg']);
  /* Spaces and hyphens are ordinary in ComfyUI output. Rejecting them -
   * which an over-eager path guard does - empties the gallery. */
  assert.ok(files[0].includes(' ') && files[0].includes('-'));
});

/* ---------------------------------------------------------- the one tap */

test('the grab lands on the next free pad and never overwrites one', () => {
  /* Lean-back has no drag and no chosen pad, so "keep this" has to pick.
   * Silently replacing a pad recorded an hour ago is the kind of quiet
   * destruction the sampler's CHOP undo exists to prevent. */
  const banks = () => [new Array(4).fill(null), new Array(4).fill(null)];
  const empty = banks();
  assert.deepEqual(model.firstFreePad(empty, 0), {bank: 0, pad: 0});

  const partly = banks();
  partly[0][0] = {label: 'kept'};
  partly[0][1] = {label: 'kept'};
  assert.deepEqual(model.firstFreePad(partly, 0), {bank: 0, pad: 2});

  /* The bank on screen is full: go forward to the next bank, not back
   * over the operator's work. */
  const full0 = banks();
  full0[0] = [1, 2, 3, 4].map((n) => ({label: 'kept' + n}));
  assert.deepEqual(model.firstFreePad(full0, 0), {bank: 1, pad: 0});

  /* Started on the last bank, it wraps rather than giving up. */
  const full1 = banks();
  full1[1] = [1, 2, 3, 4].map((n) => ({label: 'kept' + n}));
  assert.deepEqual(model.firstFreePad(full1, 1), {bank: 0, pad: 0});

  const allFull = [[{}, {}], [{}, {}]];
  assert.equal(model.firstFreePad(allFull, 0), null,
    'full is reported, not worked around');
});

test('the grab takes the line on air, and the last thing said otherwise', () => {
  /* Not the record: a four-minute track decodes to roughly 45 MB of PCM,
   * and it is not a moment - it is in the library forever and is one tap
   * away in the Music view. `takeable` is handed in from sampler.js so
   * this never grows a second opinion about where a row's audio lives. */
  const rows = [
    {id: 'r1', text: 'first', ts: T / 1000 - 40, media: 'm1', sig: 's'},
    {id: 'r2', text: 'second', ts: T / 1000 - 20, media: 'm2', sig: 's'},
    {id: 'r3', text: 'third', ts: T / 1000 - 5}          /* no audio yet */
  ];
  const takeable = (row) => !!(row.media && row.sig);

  const live = model.grabTarget(rows, {id: 'r1'}, takeable, T);
  assert.equal(live.row.id, 'r1');
  assert.match(live.why, /on air/);

  /* Nothing speaking: the newest row that actually has audio. r3 is the
   * newest row, but there is nothing behind it yet. */
  const last = model.grabTarget(rows, null, takeable, T);
  assert.equal(last.row.id, 'r2');
  assert.match(last.why, /last thing said/);

  /* The line on air has no audio behind it yet - fall back rather than
   * offer a fetch that will fail. */
  const notYet = model.grabTarget(rows, {id: 'r3'}, takeable, T);
  assert.equal(notYet.row.id, 'r2');

  const none = model.grabTarget(rows, null, () => false, T);
  assert.equal(none.row, null);
  assert.match(none.why, /nothing in the feed/);
  assert.equal(model.grabTarget([], null, takeable, T).row, null);
});

test('a moment past the 48 h media sweep is refused, not fetched', () => {
  /* AIRLOG_KEEP_S = 48 * 3600 (app.py:112182). Line ids resolve for two
   * days and the media is then swept, so a row that still reads perfectly
   * well in a list has nothing behind it. Better a sentence than a
   * 90-second fetch that ends in a 404. */
  const fresh = {id: 'a', ts: T / 1000 - 3600, media: 'm', sig: 's'};
  const old = {id: 'b', ts: T / 1000 - model.MEDIA_WINDOW_S - 60,
    media: 'm', sig: 's'};
  assert.equal(model.mediaStale(fresh, T), false);
  assert.equal(model.mediaStale(old, T), true);

  /* A row with no timestamp is treated as fresh: the live ring is by
   * definition recent, and refusing on a missing field would make the
   * button useless. */
  assert.equal(model.mediaStale({id: 'c'}, T), false);

  const target = model.grabTarget([old, fresh], null, () => true, T);
  assert.equal(target.row.id, 'a', 'the swept row is skipped over');
  assert.equal(model.grabTarget([old], {id: 'b'}, () => true, T).row, null);
});

/* ----------------------------------------------------------- the sleep */

test('the sleep timer counts down, fades, and then is done', () => {
  /* It silences THIS terminal and nothing else - never the air-pause,
   * never /api/dj/stop. The station is shared, and a tablet going to
   * sleep on a bedside table must not take the show off the air for the
   * house. The last 45 seconds fade because a radio that stops mid-word
   * wakes you up. */
  const plan = model.sleepPlan(30, T);
  assert.equal(plan.until, T + 30 * 60000);

  const early = model.sleepTick(plan, T + 60000);
  assert.equal(early.state, 'running');
  assert.equal(early.gain, 1);

  const fading = model.sleepTick(plan, plan.until - model.FADE_S * 1000 / 2);
  assert.equal(fading.state, 'fading');
  assert.ok(fading.gain > 0 && fading.gain < 1);
  /* Monotonic: further in is quieter, or it is not a fade. */
  const later = model.sleepTick(plan, plan.until - 5000);
  assert.ok(later.gain < fading.gain);

  const done = model.sleepTick(plan, plan.until + 1);
  assert.equal(done.state, 'done');
  assert.equal(done.gain, 0);

  assert.equal(model.sleepPlan(0, T), null, 'off is off');
  assert.equal(model.sleepTick(null, T).state, 'off');
  assert.equal(model.sleepTick(null, T).gain, 1,
    'no timer must never mean silence');
});

/* -------------------------------------------------------- the type on it */

test('the station clock is the STATION\'s clock', () => {
  /* Two terminals in two rooms must not show different times for the same
   * broadcast, so the wall clock is drawn from the corrected clock rather
   * than from Date.now(). A machine half an hour out shows a different
   * time until the correction is applied - which is the point. */
  const fast = T + 30 * 60000;
  assert.notEqual(model.wallClock(fast), model.wallClock(T));
  assert.equal(model.wallClock(fast + model.skewOf(payload(), fast)),
    model.wallClock(T));
  assert.match(model.wallClock(T), /^\d\d:\d\d$/);
});

test('durations and ages read as a person would say them', () => {
  assert.equal(model.clockText(0), '0:00');
  assert.equal(model.clockText(61.6), '1:02');
  assert.equal(model.clockText(200), '3:20');
  assert.equal(model.clockText(-5), '0:00');
  assert.equal(model.agoText(0, T), '');
  assert.equal(model.agoText(T / 1000 - 30, T), '30s ago');
  assert.equal(model.agoText(T / 1000 - 600, T), '10 min ago');
  assert.equal(model.agoText(T / 1000 - 7200, T), '2 h ago');
});

/* --------------------------------------------------------- the wiring */

/* These two are cheap and they catch a real class of bug that no amount
 * of arithmetic testing will: a paint that writes into an element the
 * build no longer creates. That is not hypothetical - an "on air" strip
 * was cut from Listen's markup during this build because it repeated the
 * headline, and three paint calls were still aimed at it. In a browser
 * that fails silently forever. */

function idsUsed(source) {
  const ids = new Set();
  for (const match of source.matchAll(/\b(?:el|put)\("([A-Za-z][\w-]*)"/g)) {
    ids.add(match[1]);
  }
  return ids;
}

function idsBuilt(source) {
  const ids = new Set();
  for (const match of source.matchAll(/\bid="([A-Za-z][\w-]*)"/g)) {
    ids.add(match[1]);
  }
  return ids;
}

test('every element Listen paints is an element Listen builds', () => {
  const source = read('listen.js');
  const built = idsBuilt(source);
  /* The only ids that legitimately belong to somebody else. Both are
   * seams this view drives rather than owns: the shell's master volume
   * slider, which renderer.js listens to, and the Sampler's own host,
   * which the one-tap grab mounts when it has to. */
  const borrowedShell = new Set(['appVolume', 'sampler']);
  const borrowedPanel = new Set(['musicPlayer', 'djGainMusic']);
  for (const id of idsUsed(source)) {
    if (borrowedShell.has(id) || borrowedPanel.has(id)) continue;
    assert.ok(built.has(id), 'listen.js paints #' + id + ' but never builds it');
  }
  /* The shell-owned seams really are somebody else's, in index.html.
   * The panel-owned ids belong to the station panel app.py serves into the
   * shell; their presence is covered by the panel's own contract tests. */
  const page = read('index.html');
  for (const id of borrowedShell) {
    assert.ok(page.includes('id="' + id + '"'),
      '#' + id + ' is borrowed from a page that no longer has it');
  }
});

test('every element Music paints is an element Music builds', () => {
  const source = read('music.js');
  const built = idsBuilt(source);
  for (const id of idsUsed(source)) {
    assert.ok(built.has(id), 'music.js paints #' + id + ' but never builds it');
  }
});

test('both views are wired into the page, and neither adds a poller', () => {
  const page = read('index.html');
  for (const file of ['listen-model.js', 'listen.js', 'music.js']) {
    assert.ok(page.includes('"./' + file + '"'),
      file + ' is not loaded by index.html, so the view cannot exist');
  }
  assert.ok(page.includes('./listen-music.css'));
  /* The tabs the two bootstraps bind to, and the hosts they mount into.
   * A view whose tab id is misspelt never mounts and never says why. */
  for (const id of ['listenTabBtn', 'musicTabBtn']) {
    assert.ok(page.includes('id="' + id + '"'), id + ' is missing from the rail');
  }
  for (const id of ['listen', 'music']) {
    assert.ok(page.includes('<section id="' + id + '"'),
      'the ' + id + ' view has no host section to mount into');
  }

  /* THE SINGLE-POLLER RULE, enforced rather than trusted. Measured
   * 2026-09-11: 38 concurrent requests in flight to the station caused a
   * 46-second media stall on the tablet. Neither view may hold a repeating
   * timer, and neither may ask for the lean payload. */
  for (const file of ['listen.js', 'music.js', 'listen-model.js']) {
    const source = read(file);
    assert.ok(!/setInterval\s*\(/.test(source),
      file + ' has a setInterval - the shared feed is the only clock');
    /* In a query string, not in prose - listen-model.js explains at
     * length why lean=1 is refused, and saying so must not trip this. */
    assert.ok(!/[?&]lean=/.test(source),
      file + ' asks for lean=1, which drops stream_now and truncates chat');
  }
  /* Both must go through the one shared feed, or they are not sharing. */
  for (const file of ['listen.js', 'music.js']) {
    assert.ok(read(file).includes('PineStationFeed.subscribe'),
      file + ' does not subscribe to the shared feed');
  }
});

/* ------------------------------------------------------------- lean=1 */

test('lean=1 would blind both views, which is why neither asks for it', () => {
  /* DJ_LEAN_DROP (app.py:94128) removes stream_now. On the coalesced
   * road - most of the broadcast - that is the ONLY place the per-turn
   * timeline lives, so the line on air becomes unfindable. Paired with
   * lcd-dialogue.js, which is what PineStationFeed uses to work out the
   * rows, here is exactly what is lost. */
  const at = T / 1000 - 3;
  const full = payload({
    chat: [
      {id: 'one', who: 'dj', name: 'Caine', text: 'the first line',
        aired: 'stream'},
      {id: 'two', who: 'dj', name: 'Caine', text: 'the second line',
        aired: 'stream'}
    ],
    stream_now: {at, length: 30,
      rows: [{id: 'one', from: 0, until: 5}, {id: 'two', from: 5, until: 30}]}
  });

  const rows = stationRows(full, T);
  const playing = rows.filter((r) => r.lcdStatus === 'Playing');
  assert.equal(playing.length, 1);
  const live = model.nowPlaying(full, playing[0], T);
  /* #1206: this test is about whether the line on air can be FOUND, not
   * about where it is drawn. It used to prove that by reading the headline,
   * which was a proxy; since the record now holds the headline it reads the
   * row it found instead, which is a more direct test of its own claim. */
  assert.equal(live.kind, 'voice', 'the booth is known to be live');
  assert.equal(playing[0].text, 'the first line',
    'and the exact line on air was identified from stream_now');
  assert.equal(live.voice.text, 'the first line',
    'it reaches nowPlaying, which is what the marquee and the grab read');

  /* Now the same payload as lean=1 would deliver it. */
  const lean = Object.assign({}, full);
  delete lean.stream_now;
  const leanRows = stationRows(lean, T);
  assert.equal(leanRows.filter((r) => r.lcdStatus === 'Playing').length, 0,
    'no line is on air, on a station that is plainly talking');
  const blind = model.nowPlaying(lean, null, T);
  assert.equal(blind.kind, 'track',
    'the headline falls back to the record and the grab has nothing to take');
});
