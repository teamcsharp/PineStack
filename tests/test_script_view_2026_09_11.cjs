/* The Script view's lineage model - what it is allowed to claim.
 *
 * The view answers one question: how did this moment come to be? It gets
 * its answer from GET /api/dj/provenance/{id} (app.py:95141) and from the
 * feed it already has. STAGE 1 ONLY - no sid join, no durable provenance,
 * no tint, no verdict, no return path to the writer room.
 *
 * So most of what is pinned here is about HONESTY rather than rendering:
 * that a station the server cannot report never lights up, that an expired
 * line reads as expired rather than as broken, and that "this shard was
 * staged nearby" never quietly becomes "this shard wrote the line". A pane
 * that guesses is worse than no pane, because the operator believes it.
 *
 * What these cannot tell you: whether the live station agrees. Provenance
 * parity - the same id in this view and in the desktop's own provenance
 * window - is measured against the running box, never inferred here.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const lineage = require('../desktop/renderer/script-lineage.js');

/* A payload shaped exactly as dj_provenance_api returns one. Every key
 * below is in the route's own `return {...}` (app.py:95264-95300); nothing
 * has been invented to make the model look good. */
function payload(extra) {
  return Object.assign({
    ok: true,
    id: 'line-7',
    line: {
      id: 'line-7', ts: 1789000000, who: 'dj', name: 'Caine', kind: 'banter',
      text: 'the tower leans and the wire hums',
      voice: 'caine', engine: 'xtts', aired: 'stream', seconds: 4.2,
      source: 'doom/bars.txt',
      clip_media: 'round-88.mp3', clip_from: 5.5, clip_until: 9.7
    },
    render: {engine: 'xtts', voice: 'caine', ms: 3100, kb: 62,
             tried: ['f5'], fallback: 'f5', service: 'xtts on :9010'},
    written: {
      model: 'gemma4:e2b', ms: 2400, chars: 480, temp: 1.2, num_ctx: 8192,
      kind: 'banter', armed: 'Pine Box', sched: 'the late show',
      prompt: 'THE DOOM CRYSTAL IS ON (70%)\n- he asked for blue monday 12 times\nthe tower leans',
      script: 'A: the tower leans and the wire hums\nB: and the wire answers'
    },
    prepared: 'prepared ahead - served off the shelf',
    how: 'shelf',
    material: [{text: 'he asked for blue monday 12 times', tally: true,
                track_id: 'tr-9'}],
    documents: [
      {file: 'doom/bars.txt', how: 'the swath this line was seeded from',
       quoted: true},
      {file: 'doom/extra.txt', how: 'a booth vector search around this line',
       quoted: false}
    ],
    crystal: [
      {text: 'the tower leans', file: 'doom/bars.txt', in_prompt: true},
      {text: 'a colder room', file: 'doom/cold.txt', in_prompt: false}
    ],
    vectors: [{file: 'doom/extra.txt', query: 'towers', score: 0.81}],
    schedule: {kind: 'banter', prompt: 'the late show', kind_now: 'news',
               prompt_now: 'the bulletin'},
    system: {name: 'Pine Box', armed_now: 'Pine Box', text: 'you are the agent',
             followed: false, station: 'keep it moving', station_followed: true},
    burst: 3,
    requests: [{title: 'blue monday', count: 12}]
  }, extra || {});
}

/* ------------------------------------------------------------- the spine */

test('the spine is always the ten RapAssembly stations, in order', () => {
  /* docs/RapAssembly.md and rap_assembly_state() (app.py:129825+) name
   * these ten. The 3D presentation reuses that scene grammar, and an
   * operator who knows the 🎛 view must not have to learn a second
   * vocabulary to read this one. */
  const got = lineage.read(payload());
  assert.deepEqual(got.spine.map((s) => s.key), [
    'ideation', 'writing', 'crystal', 'tint', 'grader',
    'recording', 'stores', 'schedule', 'air', 'learning']);
  assert.deepEqual(got.spine.map((s) => s.n),
    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
});

test('an empty payload still draws ten stations, all of them dark', () => {
  /* The SHAPE of the pane is part of the diagnosis. If stations with
   * nothing in them vanished, a line whose paperwork is thin would look
   * like a different kind of line rather than a thinner record of the
   * same one. */
  const got = lineage.read({});
  assert.equal(got.spine.length, 10);
  assert.equal(got.spine.filter((s) => s.filled).length, 0);
  assert.equal(got.said, '');
  assert.equal(got.prompt, '');
});

test('read survives being handed nonsense instead of a payload', () => {
  for (const bad of [null, undefined, 'a string', 42, []]) {
    const got = lineage.read(bad);
    assert.equal(got.spine.length, 10, 'still ten stations for ' + typeof bad);
  }
});

/* --------------------------------------------------- the three dark ones */

test('tint, grader and learning are never lit, and say what stage 2 needs', () => {
  /* This is the whole honesty argument of stage 1. /api/dj/provenance
   * carries NO tint before/after, NO grader verdict and nothing about
   * learning. A station drawn empty because nothing happened and one
   * drawn empty because the server does not report it are different
   * facts; merging them is how a pane starts lying. */
  const got = lineage.read(payload());
  const dark = got.spine.filter((s) => s.stage2).map((s) => s.key);
  assert.deepEqual(dark, ['tint', 'grader', 'learning']);
  for (const one of got.spine.filter((s) => s.stage2)) {
    assert.equal(one.filled, false, one.key + ' must never light up');
    assert.ok(one.note.length > 40, one.key + ' must name the missing work');
  }
  assert.equal(got.pending, 3);
});

test('a stage 2 station stays dark even if a payload grows the field', () => {
  /* Defensive on purpose. If some future payload starts carrying a
   * `tint` key, this view must not silently start presenting it as
   * though it had been verified - the join that makes it trustworthy is
   * the thing stage 2 builds, not the field. */
  const got = lineage.read(payload({tint: {plain: 'x', tinted: 'y'},
                                    verdict: {ok: true}}));
  const tint = got.spine.find((s) => s.key === 'tint');
  assert.equal(tint.filled, false);
  assert.equal(tint.stage2, true);
});

/* ----------------------------------------------- staged vs in the prompt */

test('a crystal shard staged nearby is kept, and marked as not in the prompt', () => {
  /* The route computes `in_prompt` by substring against the prompt as
   * sent, so this is the station's own answer. Dropping the unused shard
   * would hide what the crystal offered and the writer did not take,
   * which is exactly the interesting half. */
  const got = lineage.read(payload());
  const crystal = got.spine.find((s) => s.key === 'crystal');
  assert.equal(crystal.leaves.length, 2);
  assert.equal(crystal.head, '1 of 2 shard(s) reached the prompt');
  const used = crystal.leaves.find((l) => l.text.indexOf('tower') >= 0);
  const spare = crystal.leaves.find((l) => l.text.indexOf('colder') >= 0);
  assert.equal(used.on, true);
  assert.equal(spare.on, false);
  assert.ok(spare.why.indexOf('not in this prompt') >= 0);
});

test('a document quoted in the prompt is distinguished from one merely reached', () => {
  const got = lineage.read(payload());
  const ideation = got.spine.find((s) => s.key === 'ideation');
  const quoted = ideation.leaves.find((l) => l.text.indexOf('bars.txt') >= 0);
  const notQuoted = ideation.leaves.find((l) => l.text.indexOf('extra.txt') >= 0
    && l.text.indexOf('vector search') >= 0);
  assert.equal(quoted.on, true);
  assert.ok(notQuoted, 'the document list and the vector list both land here');
});

test('the two prompts are reported as two, the way #983 forced the route to', () => {
  /* app.py's own comment: reporting the AGENT's armed prompt under "the
   * booth is following it" was true when written and became a lie. The
   * booth follows the station's disposition layer; the agent's prompt
   * governs the assistant. */
  const got = lineage.read(payload());
  const writing = got.spine.find((s) => s.key === 'writing');
  assert.ok(writing.rows.some((r) => r.indexOf('station\'s standing') >= 0));

  const unbound = lineage.read(payload({
    system: {name: 'Pine Box', station_followed: false}}));
  const row = unbound.spine.find((s) => s.key === 'writing');
  assert.ok(row.rows.some((r) => r.indexOf('not bound to the agent') >= 0));
});

/* ------------------------------------------------------------ divergence */

test('a line that appears in the returned script is called verbatim', () => {
  const got = lineage.read(payload());
  assert.equal(got.diverged.known, true);
  assert.equal(got.diverged.verbatim, true);
});

test('punctuation, case and the A:/B: marks are not treated as a change', () => {
  /* The script comes back with speaker marks and the aired row does not,
   * and the recording room normalises punctuation. Comparing raw strings
   * would report every single line as rewritten, which would make the
   * one genuinely rewritten line invisible. */
  const got = lineage.read(payload({
    line: Object.assign(payload().line, {text: 'The tower leans, and the wire hums!'})
  }));
  assert.equal(got.diverged.verbatim, true);
});

test('a line the model never wrote is flagged, and no culprit is named', () => {
  /* It could be the tint, a repair, or the trim. Stage 1 genuinely
   * cannot tell - the tint history is keyed by the round's sid and no
   * sid reaches an aired line (app.py:7660). Guessing would be worse
   * than the gap. */
  const got = lineage.read(payload({
    line: Object.assign(payload().line, {text: 'a line nobody wrote'})
  }));
  assert.equal(got.diverged.known, true);
  assert.equal(got.diverged.verbatim, false);
  assert.ok(got.diverged.why.indexOf('sid') >= 0, 'it names the missing join');
});

test('no script kept means unknown, not "rewritten"', () => {
  /* Older rows and analysis rows carry the paperwork elsewhere or not at
   * all (app.py:95180). Absence of the script is not evidence that the
   * line was changed. */
  const got = lineage.read(payload({
    written: {model: 'gemma4:e2b', prompt: 'something', script: ''}}));
  assert.equal(got.diverged.known, false);
  assert.equal(got.diverged.verbatim, false);
  assert.ok(got.diverged.why.indexOf('not kept') >= 0);
});

/* ------------------------------------------------------- failure reading */

test('the 404 sentence is recognised as an expired line, not a fault', () => {
  /* THE COUPLING THIS TEST EXISTS TO PIN. The bridge throws away the
   * status code: main.js fetchJson (desktop/main.js:434) raises
   * new Error(detail) and nothing else, so by the time the view sees a
   * 404 it is only the string app.py:95171 wrote. If that detail is ever
   * reworded, this test fails and names the coupling instead of the
   * operator discovering a blank pane. */
  const got = lineage.readFailure(new Error('That line is no longer in the booth'));
  assert.equal(got.kind, 'gone');
  assert.ok(got.say.indexOf('240') >= 0, 'it says how big the ring is');
  assert.ok(got.say.indexOf('Nothing is broken') >= 0);
  assert.equal(lineage.RING_ROWS, 240);
});

test('an expired line names the durable record that does exist', () => {
  /* Found while building this: the plan assumed nothing survives the
   * ring. data/screenplay_lines.jsonl (#1050, app.py:113313) keeps the
   * model call and the render for 48 h and
   * /api/screenplay/{hour_key}/line/{line_id} already serves it. This
   * view does not read it yet - and saying so is better than implying
   * the paperwork burned. */
  const got = lineage.readFailure(new Error('That line is no longer in the booth'));
  assert.ok(got.stage2.indexOf('screenplay_lines') >= 0);
  assert.ok(got.stage2.indexOf('48 h') >= 0);
});

test('a bare 404 with no detail still reads as an expired line', () => {
  const got = lineage.readFailure(new Error('404 Not Found'));
  assert.equal(got.kind, 'gone');
});

test('an unreachable station is not confused with an expired line', () => {
  /* Different cause, different next action: one means "that moment is
   * too old", the other means "the box is busy or down". Telling the
   * operator the wrong one sends him looking in the wrong place. */
  for (const message of ['fetch failed', 'connect ECONNREFUSED 10.89.1.246:8096',
                         'The operation timed out']) {
    assert.equal(lineage.readFailure(new Error(message)).kind, 'unreachable',
      message);
  }
});

test('an error nobody recognised is repeated verbatim, never paraphrased', () => {
  const got = lineage.readFailure(new Error('the booth caught fire'));
  assert.equal(got.kind, 'unknown');
  assert.equal(got.say, 'the booth caught fire');
});

test('an error with no message at all still produces a sentence', () => {
  /* The pane must never go blank. A blank pane is the one state where
   * the operator cannot tell a broken view from an empty answer. */
  for (const bad of [new Error(''), null, undefined, {}]) {
    const got = lineage.readFailure(bad);
    assert.ok(got.title && got.say, 'a sentence for ' + JSON.stringify(bad));
  }
});

/* ------------------------------------------------------ the feed's round */

test('rows sharing a clip_media are the round, ordered by their spans', () => {
  /* A welded round is ONE audio file and every turn inside it carries the
   * same clip_media with its own clip_from/clip_until (app.py #908). So
   * the round can be rebuilt from the feed with no server change at all -
   * which is what the Transcript presentation shows. */
  const rows = [
    {id: 'b', clip_media: 'r1.mp3', clip_from: 5, clip_until: 9, text: 'second'},
    {id: 'a', clip_media: 'r1.mp3', clip_from: 0, clip_until: 5, text: 'first'},
    {id: 'z', clip_media: 'r2.mp3', clip_from: 0, clip_until: 4, text: 'elsewhere'}
  ];
  const got = lineage.roundOf(rows, 'b');
  assert.equal(got.welded, true);
  assert.deepEqual(got.rows.map((r) => r.text), ['first', 'second']);
  assert.deepEqual(got.rows.map((r) => r.here), [false, true]);
});

test('a line with its own take is a round of one, not an empty transcript', () => {
  const rows = [{id: 'solo', text: 'on its own', media: 'x.mp3', sig: 'abc'}];
  const got = lineage.roundOf(rows, 'solo');
  assert.equal(got.found, true);
  assert.equal(got.welded, false);
  assert.equal(got.rows.length, 1);
  assert.equal(got.rows[0].here, true);
});

test('a row that has rolled out of the feed says so rather than answering blank', () => {
  const got = lineage.roundOf([{id: 'a'}], 'gone');
  assert.equal(got.found, false);
  assert.deepEqual(got.rows, []);
});

/* --------------------------------------------------------- the row hints */

test('a sting is hinted as keeping no paperwork, and stays tappable anyway', () => {
  /* screenplay_pick_lines (app.py:113490) skips a ring row with no trace:
   * "a sting has no provenance to keep". That is worth showing on the
   * row - but it is a HINT. The route gates on the id being in the ring,
   * not on the kind, so gating the tap here would invent a refusal the
   * station never made. */
  const sting = lineage.paperworkHint({id: 's1', kind: 'sfx', sfx: true});
  assert.equal(sting.keeps, false);
  assert.equal(sting.tappable, true);
  assert.ok(sting.why.indexOf('sting') >= 0);

  const spoken = lineage.paperworkHint({id: 'l1', kind: 'banter'});
  assert.equal(spoken.keeps, true);
  assert.equal(spoken.tappable, true);
});

test('a row with no id is the one thing that cannot be asked about', () => {
  const got = lineage.paperworkHint({kind: 'banter'});
  assert.equal(got.tappable, false);
});

/* -------------------------------------------------------------- the page */

test('the Script page reads backwards in time: line, answer, prompt, then sources', () => {
  const got = lineage.page(lineage.read(payload()));
  assert.deepEqual(got.slice(0, 3).map((s) => s.key),
    ['said', 'answered', 'prompt']);
  assert.equal(got.length, 13, 'three blocks plus the ten stations');
  assert.deepEqual(got.slice(3).map((s) => s.key),
    lineage.SPINE.map((s) => s.key));
});

test('the prompt is carried whole, never truncated', () => {
  /* The prompt as sent is what the operator opened this view for. A
   * clipped prompt answers a different question from the one he asked -
   * and the desktop's own provenance window already clips its copies to
   * 220 characters, which is why this one deliberately does not. */
  const long = 'x'.repeat(9000);
  const got = lineage.page(lineage.read(payload({
    written: {model: 'm', prompt: long, script: 'a'}})));
  const block = got.find((s) => s.key === 'prompt');
  assert.equal(block.body.length, 9000);
  assert.equal(block.note, '9000 characters');
});

test('the page tolerates a lineage it was never given', () => {
  assert.equal(lineage.page(null).length, 3);
});

/* ------------------------------------------------------------- the stores */

test('prepared-ahead and made-live are carried through as the room stamped them', () => {
  /* The recording room stamps every take "shelf" or "live" and that is
   * the only honest source for it (app.py:95189). Whether the audience
   * heard something written days ago or something made while they were
   * listening is one of the few questions this view can answer outright. */
  const shelf = lineage.read(payload());
  const stores = shelf.spine.find((s) => s.key === 'stores');
  assert.equal(stores.filled, true);
  assert.ok(stores.head.indexOf('prepared ahead') >= 0);

  const live = lineage.read(payload({
    prepared: 'made live, while you were listening', how: 'live'}));
  assert.ok(live.spine.find((s) => s.key === 'stores').head.indexOf('live') >= 0);
});

test('the running order says when the hour has moved on since the line was written', () => {
  const got = lineage.read(payload());
  const sched = got.spine.find((s) => s.key === 'schedule');
  assert.ok(sched.rows.some((r) => r.indexOf('news') >= 0),
    'the slot it was written for is not the slot running now');
});

test('the render fallback is shown, because a fallback is a fault that worked', () => {
  const got = lineage.read(payload());
  const room = got.spine.find((s) => s.key === 'recording');
  assert.ok(room.rows.some((r) => r.indexOf('fell back from f5') >= 0));
  assert.ok(room.rows.some((r) => r.indexOf('tried: f5') >= 0));
});

/* ------------------------------------------------- the 3D stage geometry */

/* script-stage.js is three.js, but its two load-bearing decisions are
 * plain arithmetic and can be checked without a GPU: where the ten plates
 * go, and where the camera has to sit to contain them. Both are exported
 * for exactly that reason. */
const stage = require('../desktop/renderer/script-stage.js');

test('ten stations fold into two rows that run serpentine', () => {
  /* A single row of ten plates is 42 units wide - which is the shape that
   * forces the RapAssembly camera out to +/-43 and makes the line
   * unreadable on a 9" screen. Folded to 5x2 it is 17 wide. The second
   * row runs BACKWARDS so the connectors form one continuous path rather
   * than jumping the full width between station 5 and station 6. */
  const spots = stage.spots(10);
  assert.equal(spots.length, 10);
  const top = spots.slice(0, 5).map((p) => p[0]);
  const bottom = spots.slice(5).map((p) => p[0]);
  assert.deepEqual(top, [...top].sort((a, b) => a - b), 'top row runs left to right');
  assert.deepEqual(bottom, [...bottom].sort((a, b) => b - a), 'bottom row comes back');
  assert.ok(spots[0][1] > spots[5][1], 'the second row is below the first');
  /* Station 5 and station 6 are the fold: same column, one above the
   * other, so the hand-off between them is a short vertical hop. */
  assert.ok(Math.abs(spots[4][0] - spots[5][0]) < 1e-9);
});

test('the layout is centred on the origin, so the camera needs no offset', () => {
  const spots = stage.spots(10);
  const sumX = spots.reduce((s, p) => s + p[0], 0);
  const sumY = spots.reduce((s, p) => s + p[1], 0);
  assert.ok(Math.abs(sumX) < 1e-9);
  assert.ok(Math.abs(sumY) < 1e-9);
});

function fakeCamera(fov) {
  return {
    fov: fov || 46,
    position: {x: 0, y: 0, z: 0,
      set(x, y, z) { this.x = x; this.y = y; this.z = z; }},
    updateProjectionMatrix() { this.fitted = true; }
  };
}

/* Is every plate inside the frustum at the distance the fit chose? */
function allInFrame(camera, spots, aspect) {
  const halfV = Math.tan((camera.fov * Math.PI) / 360) * camera.position.z;
  const halfH = halfV * aspect;
  return spots.every(([x, y]) =>
    Math.abs(x) + stage.PLATE_W / 2 <= halfH + 1e-9
    && Math.abs(y) + stage.PLATE_H / 2 <= halfV + 1e-9);
}

test('the camera is FITTED to the plates, in both axes and both shapes', () => {
  /* THE REASON THIS EXISTS. Every other 3js panel on this station places
   * the camera by hand - `camera.position.set(0, 0.6, 15.5)` - against a
   * wide desktop stage. On the tablet (about 1000x600 CSS px in
   * landscape) a hand-placed camera puts part of the line off the edge,
   * and nothing tells the operator that something is missing. */
  const spots = stage.spots(10);
  for (const aspect of [1000 / 600, 1920 / 900, 0.9]) {
    const camera = fakeCamera();
    stage.fitCamera(camera, spots, aspect);
    assert.ok(allInFrame(camera, spots, aspect),
      'every plate is in frame at aspect ' + aspect);
    assert.equal(camera.fitted, true, 'the projection is recomputed');
    assert.equal(camera.position.x, 0);
  }
});

test('a narrower window pulls the camera back rather than cropping the line', () => {
  const spots = stage.spots(10);
  const wide = fakeCamera();
  const narrow = fakeCamera();
  stage.fitCamera(wide, spots, 1920 / 900);
  stage.fitCamera(narrow, spots, 900 / 700);
  assert.ok(narrow.position.z > wide.position.z,
    'the tablet sees the whole line, smaller - never a cropped one');
});
