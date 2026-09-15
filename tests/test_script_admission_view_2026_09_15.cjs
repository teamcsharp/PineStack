/* The Script view's cue-map arithmetic - what it is allowed to claim.
 *
 * The audit reproduced the fault this file exists to stop:
 *
 *   "activeRow() first searches feed metadata for the playing file, then
 *    falls back to burst rows without requiring their file identity... A
 *    read-only execution of those functions returned an old burst's line
 *    while a new file was playing."
 *
 * So everything below is about the MAPPING, not the rendering: given what
 * the selected player says it is actually sounding, and the sequence the
 * station committed, which occurrence and which line is that - and, when
 * it cannot be told, which of the eight synchronization states is it.
 *
 * The functions are the real ones. `desktop/renderer/script-page.js`
 * exports its cue module as `.cues`, and it loads in bare node because
 * nothing in it touches the document until mount().
 *
 * What these cannot tell you: whether the station's admitted map matches
 * what a speaker in the room actually emitted. Deterministic dispatch is
 * enforceable; acoustic delivery is measured against the box, never here.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const cues = require('../desktop/renderer/script-page.js').cues;

const S = cues.SYNC;

/* A payload shaped exactly as PlayoutController.cue_map() returns one.
 * Every key below is in that method's own dict in broadcast_admission.py;
 * nothing has been invented to make the mapping look good. */
function occurrence(extra) {
  return Object.assign({
    occurrence_id: 'occ-1', position: 10, positions: [10, 12],
    state: 'dispatching', outcome: '', lane: 'speech',
    producer: '_speak_turns_floorless', origin: 'producer',
    assembly_id: 'welded-round-88.wav', script_revision: 'rev-4',
    cue_map_revision: 'welded-round-1', performer_session: '',
    take_id: '', label: '', kind: '', admitted_at: 1789000000, generation: 3,
    audio: {media: 'round-88.wav', path: '/media/round-88.wav', sig: 'abc',
            hash: 'f'.repeat(64), hash_method: 'sha256-full', bytes: 1024,
            seconds: 12.0},
    cues: [
      {line_id: 'a', position: 10, ordinal: 0, start_s: 0, speech_end_s: 3.6, end_s: 4},
      {line_id: 'b', position: 11, ordinal: 1, start_s: 4, speech_end_s: 7.6, end_s: 8},
      {line_id: 'c', position: 12, ordinal: 2, start_s: 8, speech_end_s: 11.6, end_s: 12}
    ],
    replacement: null, dispatched_at: 1789000001, delivery: {}
  }, extra || {});
}

function payload(extra) {
  return Object.assign({
    schema_version: 1, generation: 3, mode: 'observe', enforce_lanes: [],
    enforce_order: false, reader_position: 10, next_position: 13,
    current: {occurrence_id: 'occ-1', position: 10, media: 'round-88.wav',
              started_at: 1789000001, seconds: 12.0},
    occurrences: [occurrence()], reservations: [], counts: {}, refusals: []
  }, extra || {});
}

function readOf(file, at, extra) {
  return Object.assign({file: file, position_s: at, source: 'bridge'}, extra || {});
}

/* ------------------------------------------------------------ reading it */

test('an absent admitted map is said to be absent, not treated as empty', () => {
  /* A station that has not been patched yet sends nothing. The view must
   * fall through to its older roads rather than believe the sequence is
   * over. `ok` is the flag those roads are gated on. */
  const map = cues.read(undefined);
  assert.equal(map.ok, false);
  assert.equal(map.count, 0);
  assert.match(map.why, /not sending an admitted cue map/);
});

test('an empty admitted sequence is a different answer from an absent one', () => {
  const map = cues.read(payload({occurrences: []}));
  assert.equal(map.ok, true);
  assert.equal(map.count, 0);
  assert.match(map.why, /empty/);
});

test('occurrences are ordered by committed position, never by arrival', () => {
  /* The station appends; the ORDER is the positions it committed. An
   * arrival-ordered list is exactly the reconstruction this replaces. */
  const late = occurrence({occurrence_id: 'occ-0', position: 4,
    audio: {media: 'earlier.wav', seconds: 3},
    cues: [{line_id: 'z', position: 4, start_s: 0, end_s: 3}]});
  const map = cues.read(payload({occurrences: [occurrence(), late]}));
  assert.deepEqual(map.order.map((o) => o.position), [4, 10]);
});

test('the media index is keyed on the basename the player can actually report', () => {
  const map = cues.read(payload());
  assert.ok(map.byMedia['round-88.wav']);
  assert.equal(cues.key('http://box/media/round-88.wav?t=abc'), 'round-88.wav');
  assert.equal(cues.key('C:\\media\\round-88.wav'), 'round-88.wav');
});

/* --------------------------------------------------- the player's own file */

test('a read position inside a committed cue names that line and its window', () => {
  const got = cues.locate(cues.read(payload()), readOf('round-88.wav', 5.0));
  assert.equal(got.sync, S.READ);
  assert.equal(got.line_id, 'b');
  assert.equal(got.occurrence_id, 'occ-1');
  assert.equal(got.position, 11);
  assert.equal(got.from, 4);
  assert.equal(got.until, 8);
  assert.equal(got.trustworthy, true);
});

test('speech end is carried separately from the cue end', () => {
  /* "Retain separate speech-end and cue-end positions so an inserted pause
   *  does not falsely start the next line." */
  const got = cues.locate(cues.read(payload()), readOf('round-88.wav', 5.0));
  assert.equal(got.speechEnd, 7.6);
  assert.ok(got.speechEnd < got.until);
});

test('a file nothing admitted is named as unmapped, never mapped to a burst row', () => {
  /* THE REPRODUCED FAULT. The old road let a finished burst's window
   * bracket a new file's currentTime and lit a line that was not being
   * said. With the file guard first, the answer is a state, not a line. */
  const got = cues.locate(cues.read(payload()), readOf('a-different-file.wav', 5.0));
  assert.equal(got.sync, S.UNMAPPED);
  assert.equal(got.line_id, '');
  assert.equal(got.trustworthy, false);
  assert.match(got.why, /nothing admitted names a-different-file\.wav/);
});

test('an unmapped read still holds up the last trustworthy line, and says so', () => {
  const last = {line_id: 'b', occurrence_id: 'occ-1', position: 11,
                media: 'round-88.wav'};
  const got = cues.locate(cues.read(payload()),
    readOf('a-different-file.wav', 5.0, {last: last}));
  assert.equal(got.sync, S.UNMAPPED);
  assert.equal(got.line_id, 'b', 'the last true mark is preserved');
  assert.equal(got.carried, true);
  assert.equal(got.trustworthy, false, 'and is never presented as current');
});

test('a player past the end of the cue sheet is a fault with a name', () => {
  const got = cues.locate(cues.read(payload()), readOf('round-88.wav', 40));
  assert.equal(got.sync, S.OUTSIDE);
  assert.equal(got.occurrence_id, 'occ-1');
  assert.equal(got.line_id, '');
  assert.match(got.why, /past the end of the cue sheet/);
});

test('a gap between two committed lines is not a missing line', () => {
  /* An inserted pause is part of the committed sheet. A stationary cursor
   * across it is correct, and must be told apart from a lost mark. */
  const sparse = occurrence({cues: [
    {line_id: 'a', position: 10, start_s: 0, end_s: 4},
    {line_id: 'b', position: 11, start_s: 6, end_s: 10}]});
  const got = cues.locate(cues.read(payload({occurrences: [sparse]})),
    readOf('round-88.wav', 5.0));
  assert.equal(got.sync, S.GAP);
  assert.equal(got.trustworthy, true);
  assert.equal(got.line_id, '');
});

/* ------------------------------------------------- the same sample, twice */

test('two plays of one sting are two occurrences, and the live one is chosen', () => {
  /* "A reusable sample's content ID is not its playback occurrence ID.
   *  Playing the same sting twice produces two distinct occurrences." */
  const first = occurrence({occurrence_id: 'occ-a', position: 5,
    state: 'finished', outcome: 'accepted', dispatched_at: 100,
    audio: {media: 'bell.wav', seconds: 2},
    cues: [{line_id: 'bell:1', position: 5, start_s: 0, end_s: 2}]});
  const second = occurrence({occurrence_id: 'occ-b', position: 20,
    state: 'dispatching', dispatched_at: 200,
    audio: {media: 'bell.wav', seconds: 2},
    cues: [{line_id: 'bell:2', position: 20, start_s: 0, end_s: 2}]});
  const map = cues.read(payload({occurrences: [first, second],
    current: {occurrence_id: 'occ-b', position: 20, media: 'bell.wav'}}));
  const got = cues.locate(map, readOf('bell.wav', 0.5));
  assert.equal(got.occurrence_id, 'occ-b');
  assert.equal(got.line_id, 'bell:2');
  assert.equal(got.position, 20);
});

test('without a named current, the most recently dispatched play wins', () => {
  const first = occurrence({occurrence_id: 'occ-a', position: 5,
    state: 'finished', dispatched_at: 100,
    audio: {media: 'bell.wav', seconds: 2},
    cues: [{line_id: 'bell:1', position: 5, start_s: 0, end_s: 2}]});
  const second = occurrence({occurrence_id: 'occ-b', position: 20,
    state: 'finished', dispatched_at: 200,
    audio: {media: 'bell.wav', seconds: 2},
    cues: [{line_id: 'bell:2', position: 20, start_s: 0, end_s: 2}]});
  const map = cues.read(payload({occurrences: [first, second], current: null}));
  assert.equal(cues.locate(map, readOf('bell.wav', 0.5)).occurrence_id, 'occ-b');
});

test('an admitted but undispatched play is not chosen over the one in flight', () => {
  const flying = occurrence({occurrence_id: 'occ-a', position: 5,
    state: 'dispatching', dispatched_at: 100,
    audio: {media: 'bell.wav', seconds: 2},
    cues: [{line_id: 'bell:1', position: 5, start_s: 0, end_s: 2}]});
  const waiting = occurrence({occurrence_id: 'occ-b', position: 20,
    state: 'admitted', dispatched_at: null,
    audio: {media: 'bell.wav', seconds: 2},
    cues: [{line_id: 'bell:2', position: 20, start_s: 0, end_s: 2}]});
  const map = cues.read(payload({occurrences: [flying, waiting], current: null}));
  assert.equal(cues.locate(map, readOf('bell.wav', 0.5)).occurrence_id, 'occ-a');
});

/* ---------------------------------------- what is NOT a playback position */

test('the station wall clock is an estimate and can never claim a line', () => {
  /* "Buffered outputs need their own playback position, rather than the
   *  server's current wall-clock position." A clock has no file behind it,
   * so it can bracket any window it likes; it is refused by source. */
  const got = cues.locate(cues.read(payload()),
    {file: '', position_s: 5.0, source: 'estimated'});
  assert.equal(got.sync, S.ESTIMATED);
  assert.equal(got.line_id, '');
  assert.equal(got.trustworthy, false);
  assert.match(got.why, /station clock, not a playhead/);
});

test('no evidence at all is held, with the last true line still shown', () => {
  const last = {line_id: 'c', occurrence_id: 'occ-1', position: 12};
  const got = cues.locate(cues.read(payload()),
    {source: 'unavailable', position_s: null, last: last});
  assert.equal(got.sync, S.HELD);
  assert.equal(got.line_id, 'c');
  assert.equal(got.carried, true);
  assert.equal(got.trustworthy, false);
});

test('a paused station is its own state and outranks every other reading', () => {
  const got = cues.locate(cues.read(payload()),
    readOf('round-88.wav', 5.0, {paused: true}));
  assert.equal(got.sync, S.PAUSED);
  assert.equal(got.trustworthy, false);
});

test('a player that names no file cannot be mapped', () => {
  const got = cues.locate(cues.read(payload()), readOf('', 5.0));
  assert.equal(got.sync, S.UNMAPPED);
  assert.match(got.why, /did not name its file/);
});

test('a negative or missing offset is no evidence rather than offset zero', () => {
  assert.equal(cues.locate(cues.read(payload()), readOf('round-88.wav', -1)).sync,
    S.HELD);
  assert.equal(cues.locate(cues.read(payload()), readOf('round-88.wav', null)).sync,
    S.HELD);
});

/* -------------------------------------------------------------- a stall */

test('a mapped line whose playhead has stopped moving is a fault, not a line', () => {
  /* The audit is explicit that a stationary cursor must not be smoothed
   * away: "Merely preventing a backward visual movement would hide an
   * audio fault." The line is still reported - the operator needs to know
   * WHICH line stopped - but the state says the sound stopped. */
  const got = cues.locate(cues.read(payload()),
    readOf('round-88.wav', 5.0, {stalledMs: 20000}));
  assert.equal(got.sync, S.STALL);
  assert.equal(got.line_id, 'b');
  assert.equal(got.trustworthy, false);
  assert.match(got.why, /has not moved for 20s/);
});

test('a moving playhead under the stall limit stays in step', () => {
  const got = cues.locate(cues.read(payload()),
    readOf('round-88.wav', 5.0, {stalledMs: 900, stallLimitMs: 8000}));
  assert.equal(got.sync, S.READ);
});

test('a stationary cursor during a declared gap is not reported as a stall', () => {
  /* "Validate speech continuity separately from ordering: a stationary
   *  cursor during an intended music section is not an order failure." */
  const sparse = occurrence({cues: [
    {line_id: 'a', position: 10, start_s: 0, end_s: 4},
    {line_id: 'b', position: 11, start_s: 6, end_s: 10}]});
  const got = cues.locate(cues.read(payload({occurrences: [sparse]})),
    readOf('round-88.wav', 5.0, {stalledMs: 30000}));
  assert.equal(got.sync, S.GAP);
});

/* --------------------------------------------------------- the eight states */

test('there are exactly eight synchronization states and each has a sentence', () => {
  const names = Object.keys(S).map((k) => S[k]);
  assert.equal(names.length, 8);
  assert.equal(new Set(names).size, 8);
  names.forEach((name) => {
    const said = cues.say({sync: name});
    assert.ok(said && said.length > 3, name + ' has no sentence');
  });
});

test('only the two read-and-mapped states are ever trustworthy', () => {
  const trusted = [S.READ, S.GAP];
  Object.keys(S).forEach((key) => {
    const name = S[key];
    const got = cues.locate(cues.read(payload()),
      name === S.PAUSED ? readOf('round-88.wav', 5, {paused: true})
        : name === S.ESTIMATED ? {source: 'estimated', position_s: 5}
        : name === S.HELD ? {source: 'unavailable', position_s: null}
        : name === S.UNMAPPED ? readOf('elsewhere.wav', 5)
        : name === S.OUTSIDE ? readOf('round-88.wav', 99)
        : name === S.STALL ? readOf('round-88.wav', 5, {stalledMs: 99000})
        : name === S.GAP ? readOf('round-88.wav', 5.0)
        : readOf('round-88.wav', 5.0));
    if (trusted.indexOf(got.sync) >= 0) assert.equal(got.trustworthy, true, got.sync);
    else assert.equal(got.trustworthy, false, got.sync);
  });
});

/* ------------------------------------------------- what the map hands on */

test('an occurrence carries the incident references the note asks for', () => {
  /* Section 5: script revision, performer session, accepted cut, assembly
   * and playback occurrence. The view reports what the STATION sent; a
   * field the station leaves blank is left blank here, never invented. */
  const map = cues.read(payload());
  const one = map.order[0];
  assert.equal(one.script_revision, 'rev-4');
  assert.equal(one.assembly_id, 'welded-round-88.wav');
  assert.equal(one.cue_map_revision, 'welded-round-1');
  assert.equal(one.performer_session, '', 'the station did not carry one');
  assert.equal(one.take_id, '');
  assert.equal(one.hash.length, 64);
  assert.equal(map.generation, 3);
  assert.equal(map.mode, 'observe');
  assert.equal(map.reader, 10);
});

test('a cue with an unusable window is dropped rather than mapped at zero', () => {
  const broken = occurrence({cues: [
    {line_id: 'a', position: 10, start_s: 0, end_s: 4},
    {line_id: 'b', position: 11, start_s: null, end_s: null},
    {line_id: 'c', position: 12, start_s: 8, end_s: 12}]});
  const map = cues.read(payload({occurrences: [broken]}));
  assert.deepEqual(map.order[0].cues.map((c) => c.line_id), ['a', 'c']);
  assert.equal(cues.locate(map, readOf('round-88.wav', 5.0)).sync, S.GAP);
});

test('an occurrence with no id is not admitted into the view either', () => {
  const map = cues.read(payload({occurrences: [
    occurrence(), Object.assign(occurrence(), {occurrence_id: ''})]}));
  assert.equal(map.count, 1);
});

test('the origin of an observed dispatch is carried through to the operator', () => {
  /* In observe mode the controller records dispatches nobody committed so
   * the script stays complete. They are labelled, and the label survives
   * into the view: an operator must be able to see that a line on screen
   * was never admitted. */
  const loose = occurrence({origin: 'observed_dispatch', producer: 'dj_sting',
    audio: {media: 'sting.wav', seconds: 1.5},
    cues: [{line_id: 'observed:sting.wav', position: 30, start_s: 0, end_s: 1.5}]});
  const map = cues.read(payload({occurrences: [loose], current: null}));
  const got = cues.locate(map, readOf('sting.wav', 0.5));
  assert.equal(got.origin, 'observed_dispatch');
  assert.equal(map.order[0].producer, 'dj_sting');
});

test('reading a payload never mutates it', () => {
  const given = payload();
  const snapshot = JSON.stringify(given);
  cues.locate(cues.read(given), readOf('round-88.wav', 5.0));
  assert.equal(JSON.stringify(given), snapshot);
});
