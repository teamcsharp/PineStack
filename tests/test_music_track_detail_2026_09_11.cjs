/* The expanding record in the Music view.
 *
 * "Be able to tap on every song in the queue and be able to expand it and
 *  see the dialogue generated for it, see the analysis that's done for
 *  it, see what online research has been done for it, see what we've
 *  queued up for the host to say about this particular track."
 *
 * What can be pinned from node is the SHAPE of that panel: which store
 * answers which question, how a payload becomes a section, and - the part
 * that actually matters here - what a section says when there is nothing
 * behind it. What cannot be pinned is whether it reads well on a tablet.
 *
 * TWO THINGS ARE TESTED AS BEHAVIOUR RATHER THAN LEFT AS COMMENTS, because
 * both have a measured incident behind them:
 *
 *   NOTHING PREPARED IS NOT NOTHING WORKING. Measured against the live
 *   station on 2026-09-11: of the 22 records in the queue, the just-played
 *   and the record on air, ZERO had a SongSight crystal and ZERO had a read
 *   on file. So the empty case is not an edge - it is the common case, and
 *   a panel that drew five blank boxes would tell the operator the feature
 *   was broken twenty times an hour. Every section must therefore carry a
 *   sentence when it is empty, and the tests below assert the sentence.
 *
 *   THE EXPENSIVE DOORS STAY SHUT. Two of the five stores cost real money:
 *   the writers' board arrives only inside /api/dj/pending, measured at
 *   773,386 bytes and 2.0 s, and the research door runs a live web search
 *   and a model call on any record the station has never looked up
 *   (track_notes, app.py:54703). Neither may be opened by a tap. The
 *   sections for both must report PENDING - a third state, distinct from
 *   "there is nothing" - so that the operator chooses to spend it.
 *
 * The fixtures below are trimmed copies of what the live station really
 * answered on 2026-09-11, not invented shapes.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const model = require('../desktop/renderer/listen-model.js');

const RENDERER = path.join(__dirname, '..', 'desktop', 'renderer');
const read = (name) => fs.readFileSync(path.join(RENDERER, name), 'utf8');

const T = 1789142400000;                 /* a fixed moment, in ms */

/* One crystal as /api/song-crystals really serves it (app.py:93391), with
 * the library track resolved onto it by crystal_with_track. */
function crystalPayload() {
  return {
    count: 22,
    crystals: [
      {
        slug: '02-red-pill', title: '02 - Red Pill',
        source: '02 - Red_Pill.mp3',
        duration_seconds: 465.0, duration_text: '7:45',
        bpm: 103.36, meter: '4/4', bars: 191,
        key: 'C minor', key_confidence: 0.39,
        chords: 'Csus4 → Cm7 → F7 → Cm7 → D#maj7 → …', chord_count: 191,
        instruments: {bass: 'distorted / layered bass', melody: 'piano / keys',
          vocals: 'vocals (sung melody)', guitar: 'piano / keys',
          drone: 'strings / pad'},
        stems: ['bass', 'drums', 'guitar', 'other', 'piano', 'vocals'],
        drums: {closed_hi_hat: 1075, snare: 692, kick: 545},
        notes: {count: 8706, lowest: 'C1', highest: 'F7'},
        lyrics: [], separation_model: 'demucs htdemucs_6s',
        built: '2026-08-07',
        track: {id: '607ab40218b06561', title: 'This playlist came from '
          + 'another timeline', artist: 'The Funkyverse', station: 'songsight',
          seconds: 465.0}
      },
      /* crystal_with_track resolves the record by the analysed file's stem
       * and falls back to a title search (app.py:93372). When neither
       * finds anything there is no `track` key at all. */
      {slug: 'orphan', title: 'nothing in the library matches this',
        built: '2026-08-07'}
    ]
  };
}

/* /api/track-reads (app.py:99955). `rows` is capped at 300 of `held`, and
 * every side is clipped to 200 characters (app.py:31046/31060). */
function readsPayload() {
  return {
    at: T / 1000, held: 558, loved: 0,
    rows: [
      {id: '1546376242d12893', title: 'Inner Palace', artist: 'Surfing',
        loved: false, last: 1789140665.893,
        parts: {outro: {aired: 1, text: "Surfing's Inner Palace on the dial; "
          + 'carries a heavy atmosphere, unsettling style.'}}},
      {id: 'longread', title: 'A Long One', artist: 'Someone',
        loved: true, last: 1789140000,
        parts: {
          intro: {aired: 4, text: 'x'.repeat(200)},
          ad: {aired: 2, text: 'an advert built round this very record'}
        }}
    ]
  };
}

/* /api/music/played (app.py:103559), newest first, with the vote. */
function playedPayload() {
  return {played: [
    {id: 'spun', title: 'Comes Round', at: 1789142548, vote: 1},
    {id: 'once', title: 'Only Once', at: 1789142499, vote: 0},
    {id: 'spun', title: 'Comes Round', at: 1789120000, vote: 1}
  ]};
}

/* track_talk_state's tracks, off /api/dj/pending (app.py:31560). */
function boardPayload() {
  return {lookahead: {ahead: 81, on: true, held: 1, tracks: [
    {at: 0, id: 'written', title: 'Words Ready', artist: 'A',
      intro: 'written', outro: '',
      intro_text: 'Words Ready by A is next on the dial.', outro_text: ''},
    {at: 1, id: 'recorded', title: 'Both Ways', artist: 'B',
      intro: 'ready', outro: 'ready',
      intro_text: 'Both Ways, coming up.', outro_text: 'That was Both Ways.'},
    {at: 2, id: 'bare', title: 'Nothing Yet', artist: 'C',
      intro: '', outro: '', intro_text: '', outro_text: ''}
  ]}};
}

/* /api/music/track/{id} (app.py:110210) - the one per-record fetch. */
function metaPayload() {
  return {
    id: '760a6870e10586e3', title: 'The Nihilist (Night)', artist: 'Kvtvlv',
    album: 'Friend of The Night', ext: '.mp3', seconds: 224.0,
    station: 'itunes', size: 9109211, vote: 0,
    tags: {bitrate: '320000', TDRC: '2023', TALB: 'Friend of The Night',
      'COMM::eng': 'Visit https://fullmetalrecords.bandcamp.com'},
    stats: {artist_tracks: 10, artist_albums: 2, album_tracks: 9}
  };
}

function section(detail, key) {
  const found = detail.sections.find((s) => s.key === key);
  assert.ok(found, 'the panel has no ' + key + ' section');
  return found;
}

/* ------------------------------------------------------- the indexes */

test('a crystal is filed under the record the STATION resolved for it', () => {
  /* crystal_with_track (app.py:93361) reads the analysed file's stem and
   * falls back to a title search, and its answer is the only one a client
   * should second-guess. Indexing by crystal.track.id is therefore the
   * whole join between the analysis library and the queue. */
  const index = model.crystalIndex(crystalPayload());
  assert.deepEqual(Object.keys(index), ['607ab40218b06561']);
  assert.equal(index['607ab40218b06561'].slug, '02-red-pill');
  /* And the unresolved one is DROPPED, not filed under "". A crystal
   * indexed under an empty id is a crystal handed to every record whose
   * id failed to read. */
  assert.equal(index[''], undefined);
});

test('the crystal reads as music, with the key confidence attached to it', () => {
  const crystal = crystalPayload().crystals[0];
  const facts = model.crystalFacts(crystal);
  const of = (label) => (facts.find((f) => f.label === label) || {}).value;

  assert.equal(of('tempo'), '103.4 BPM · 4/4 · 191 bars');
  /* Measured across the 22 crystals the confidence runs 0.39 to 0.58.
   * A key printed bare reads as a fact; these are estimates. */
  assert.equal(of('key'), 'C minor (39% sure)');
  /* Two roles share "piano / keys" in this crystal - the instruments line
   * is what is HEARD, so it must not say it twice. */
  assert.equal(of('instruments'),
    'distorted / layered bass · piano / keys · vocals (sung melody) · strings / pad');
  assert.equal(of('stems'), '6: bass, drums, guitar, other, piano, vocals');
  assert.equal(of('drum hits'), '1075 closed hi hat · 692 snare · 545 kick');
  assert.equal(of('notes'), '8706 notes, C1 to F7');
  assert.equal(of('built'), '2026-08-07 · demucs htdemucs_6s');
  /* Every fact printed has a value. A crystal with no drums at all must
   * not leave a labelled blank on screen. */
  for (const row of facts) assert.ok(row.value, row.label + ' is blank');
  assert.equal(model.crystalFacts({}).length, 0, 'an empty crystal says nothing');
  assert.equal(model.crystalChords(crystal).indexOf('Csus4'), 0);
});

test('a read carries how many times it has actually gone out', () => {
  /* track_read_keep increments `aired` every time the words are taken
   * (app.py:30965), so this count IS the answer to "what have the pair
   * said about this record before". */
  const index = model.readsIndex(readsPayload());
  const one = model.readLines(index['1546376242d12893']);
  assert.equal(one.length, 1);
  assert.equal(one[0].part, 'outro');
  assert.equal(one[0].label, 'the send-off');
  assert.equal(one[0].tail, 'aired once');
  assert.equal(one[0].clipped, false);

  /* Three sides exist, and the #1061 case the operator asked for by name -
   * an advert built round a song - is one of them. Order is the order a
   * show uses them in, not the order the JSON happens to hold. */
  const many = model.readLines(index.longread);
  assert.deepEqual(many.map((r) => r.part), ['intro', 'ad']);
  assert.equal(many[0].tail, 'aired 4×');
  /* app.py:31046 clips every side at 200 characters, so a read AT the clip
   * is the head of a read and the panel has to be able to say so. */
  assert.equal(many[0].clipped, true);
  assert.equal(model.TRACK_READ_CLIP, 200);
  assert.deepEqual(model.readLines(null), []);
  assert.deepEqual(model.readLines({parts: {intro: {text: '  '}}}), [],
    'a blank side is not a read');
});

test('play history folds a record that came round twice into one entry', () => {
  const index = model.playedIndex(playedPayload());
  assert.equal(index.spun.spins, 2);
  assert.equal(index.spun.last, 1789142548, 'the NEWEST spin, not the last row');
  assert.equal(index.spun.first, 1789120000);
  assert.equal(index.spun.vote, 1);
  assert.equal(index.once.spins, 1);
  assert.equal(index.missing, undefined);
});

test('the writers\' board tells written from written-and-recorded', () => {
  /* app.py:31567 - "ready" means the words AND the recording are in hand,
   * "written" means the words only, "" means nothing. Those are three
   * different answers to "is the host ready to talk over this record" and
   * collapsing them would hide the one that costs a live render. */
  const index = model.lookaheadIndex(boardPayload());
  assert.deepEqual(Object.keys(index), ['written', 'recorded', 'bare']);

  const half = model.lookaheadLines(index.written);
  assert.equal(half.length, 1, 'the empty send-off is not a line');
  assert.equal(half[0].tail, 'written, not yet recorded');

  const both = model.lookaheadLines(index.recorded);
  assert.deepEqual(both.map((r) => r.tail),
    ['written and recorded', 'written and recorded']);

  assert.deepEqual(model.lookaheadLines(index.bare), []);
  assert.deepEqual(model.lookaheadIndex({}), {});
});

test('the per-record fetch is the tag sheet, and it reads as one', () => {
  const facts = model.metaFacts(metaPayload());
  const of = (label) => (facts.find((f) => f.label === label) || {}).value;
  assert.equal(of('album'), 'Friend of The Night');
  assert.equal(of('year'), '2023');
  assert.equal(of('runs'), '3:44');
  assert.equal(of('file'), 'MP3 · 320 kbps · 9 MB');
  assert.equal(of('shelf'), 'itunes');
  assert.equal(of('this artist'), '10 tracks on 2 albums here');
  assert.equal(of('tagged'), 'Visit https://fullmetalrecords.bandcamp.com');
  assert.equal(model.metaFacts(null).length, 0);
  assert.equal(model.metaFacts({tape: true, id: 'x'})[0].value,
    'one of the MX tapes');
});

/* ------------------------------------------------ the panel, when full */

test('a record the station knows everything about opens with everything', () => {
  const crystal = model.crystalIndex(crystalPayload())['607ab40218b06561'];
  const detail = model.trackDetail({
    id: '607ab40218b06561',
    meta: metaPayload(),
    crystal,
    crystalsBuilt: 22, libraryTotal: 35982,
    read: model.readsIndex(readsPayload()).longread,
    readsHeld: 558, readsServed: 300,
    board: model.lookaheadIndex(boardPayload()).recorded,
    boardAhead: 81,
    history: model.playedIndex(playedPayload()).spun,
    historyWindow: 200,
    research: {id: '607ab40218b06561', notes: 'Listeners call it a sleeper.'},
    at: T
  });

  /* All four of the operator's asks, plus the record itself and its
   * airings, and every one of them with something in it. */
  assert.deepEqual(detail.sections.map((s) => s.key),
    ['record', 'analysis', 'said', 'prepared', 'history', 'research']);
  for (const one of detail.sections) {
    assert.ok((one.facts || []).length || (one.lines || []).length,
      one.key + ' is empty on a record that has everything');
    assert.equal(one.empty, undefined, one.key + ' claims to be empty');
    assert.equal(one.pending, undefined, one.key + ' claims to be unasked');
  }

  assert.equal(section(detail, 'analysis').lines[0].label, 'chords');
  assert.equal(section(detail, 'said').lines[0].text.length, 200);
  assert.equal(section(detail, 'said').note,
    'the station serves the first 200 characters of a read');
  assert.equal(section(detail, 'prepared').lines.length, 2);
  assert.equal(section(detail, 'research').lines[0].text,
    'Listeners call it a sleeper.');

  const spins = section(detail, 'history').facts;
  assert.equal(spins[0].value, '2 in the last 200 records played');
  assert.equal(spins.find((f) => f.label === 'your vote').value, 'up');
});

/* ----------------------------------------------- the panel, when empty */

test('nothing prepared says so in a sentence, on every section', () => {
  /* THE COMMON CASE, not the edge. Measured 2026-09-11: none of the 22
   * records in the live queue, just-played and on-air had a crystal or a
   * read. Five blank boxes would read as a broken feature. */
  const detail = model.trackDetail({
    id: 'unknown', meta: null,
    crystal: null, crystalsBuilt: 22, libraryTotal: 35982,
    read: null, readsHeld: 558, readsServed: 300,
    board: null, boardAhead: 81,
    history: null, historyWindow: 200,
    research: null,
    at: T
  });

  for (const one of detail.sections) {
    assert.ok(one.empty, one.key + ' is blank instead of saying it is empty');
    assert.equal((one.facts || []).length, 0);
    assert.equal((one.lines || []).length, 0);
  }

  assert.equal(section(detail, 'analysis').empty,
    'no analysis has been done for this track yet');
  /* And the coverage beside it, because 22 of 35,982 is the real reason
   * the answer is "no" and the operator should not have to guess at it. */
  assert.match(section(detail, 'analysis').note, /22 crystals/);
  assert.match(section(detail, 'analysis').note, /35982/);

  assert.match(section(detail, 'said').empty, /nothing has been said/);
  /* app.py:31060 serves 300 of 558. "Nothing" about a record whose read
   * simply fell past that cap is a quiet lie, so the cap is printed. */
  assert.match(section(detail, 'said').note, /300 of 558/);

  assert.match(section(detail, 'prepared').empty,
    /not in the writers' lookahead \(the next 81\)/);
  assert.match(section(detail, 'history').empty, /last 200 played/);
  assert.match(section(detail, 'research').empty, /nothing on file/);
});

test('a record in the lookahead with nothing written says exactly that', () => {
  /* Two different noes. "Not in the lookahead" means the writers were
   * never going to get to it; "in the lookahead with nothing written"
   * means they have and have not. Measured on the live board: 81 ahead,
   * held 0, every intro_text and outro_text empty - so this is the state
   * the station was ACTUALLY in on the day this was built. */
  const bare = model.trackDetail({
    id: 'bare', board: model.lookaheadIndex(boardPayload()).bare,
    boardAhead: 81, at: T
  });
  assert.match(section(bare, 'prepared').empty,
    /in the writers' lookahead with nothing written for it yet/);

  const missing = model.trackDetail({id: 'nope', board: null, boardAhead: 81,
    at: T});
  assert.match(section(missing, 'prepared').empty,
    /not in the writers' lookahead/);
});

test('the two expensive doors report PENDING, which is not the same as empty', () => {
  /* THE WHOLE DISCIPLINE, IN ONE ASSERTION. /api/dj/pending measured
   * 773,386 bytes; /api/music/notes runs a live web search and a model
   * call on a record never looked up (app.py:54703). Until the operator
   * presses, the honest answer is "nobody has asked" - NEVER "there is
   * nothing", which is what a panel that fetched on tap would have had to
   * pretend in order to stay cheap. */
  const detail = model.trackDetail({id: 'x', at: T});  /* nothing supplied */

  const prepared = section(detail, 'prepared');
  assert.ok(prepared.pending, 'the board reports empty instead of unasked');
  assert.equal(prepared.empty, undefined);
  assert.match(prepared.note, /773 kB/);

  const research = section(detail, 'research');
  assert.ok(research.pending, 'the research door reports empty instead of unasked');
  assert.equal(research.empty, undefined);
  assert.match(research.note, /model call/);

  /* And the record's own tag sheet, which IS fetched on the tap, says it
   * is being read rather than saying the library has nothing. */
  assert.equal(section(detail, 'record').empty, 'reading the library…');
});

test('an empty answer from the research door is reported as an empty answer', () => {
  /* /api/music/notes returns {"id": …, "notes": ""} both for a record the
   * station looked up and found nothing about AND for one it has just
   * searched for in vain - measured on the live station, the two are
   * indistinguishable through that route. The panel says what it knows and
   * does not invent the difference. */
  const detail = model.trackDetail({id: 'x', research: {id: 'x', notes: ''},
    at: T});
  const found = section(detail, 'research');
  assert.ok(found.empty);
  assert.equal(found.pending, undefined, 'it HAS been asked now');
  /* 87 of the 400 records the station has researched came back with a
   * note. That ratio is why an empty answer here is ordinary. */
  assert.match(found.note, /87 of the 400/);
});

/* ------------------------------------------------------- the discipline */

test('the detail adds no poller and no per-row fan-out', () => {
  const source = read('music.js');

  /* Measured 2026-09-11: 38 concurrent requests in flight produced a
   * 46-second media stall on the tablet. A panel that fetched five things
   * per row would have put thirty-odd in flight on one scroll. */
  assert.ok(!/setInterval\s*\(/.test(source), 'music.js has a setInterval');
  assert.ok(!/setTimeout\s*\(/.test(source), 'music.js has a setTimeout');

  /* CALL SITES, not mentions - these routes are named in prose and in
   * button tooltips all over this file, and counting the string would
   * count the explanation of the rule as a breach of it. */
  const callsTo = (route) => (source.match(new RegExp(
    'api\\(\\)\\.get\\(\\s*"' + route.replace(/[/?]/g, '\\$&'),
    'g')) || []).length;

  /* The three whole-library reads happen once, behind a single-flight
   * promise, and IN SERIES - four fast taps on four rows must not become
   * twelve requests. */
  for (const route of ['/api/song-crystals', '/api/track-reads',
    '/api/music/played']) {
    assert.equal(callsTo(route), 1,
      route + ' is fetched from ' + callsTo(route) + ' places, not one');
  }
  assert.match(source, /if \(libraryState === "ready"\) return;/);
  assert.match(source, /if \(libraryWait\) return libraryWait;/);

  /* The one per-record call, and its cache. */
  assert.equal(callsTo('/api/music/track/'), 1);
  assert.match(source, /if \(!id \|\| meta\.has\(id\)\) return;/);

  /* The 773 kB read exists exactly once and is not reachable from a tap:
   * nothing calls loadBoard but the press built in sectionNode. */
  assert.equal(callsTo('/api/dj/pending'), 1);
  assert.equal(callsTo('/api/music/notes/'), 1);
  assert.equal(source.split('loadBoard()').length - 1, 2,
    'loadBoard is called from somewhere other than its one press');
  assert.equal(source.split('loadResearch(id)').length - 1, 2,
    'loadResearch is called from somewhere other than its one press');
});

test('a tap opens the record; it no longer asks for it', () => {
  /* It used to: tapping a shelf row or a just-played row fired
   * /api/dj/request, which runs a library search AND a live render so the
   * pair can acknowledge it. A gesture that expensive must not be the one
   * a finger makes while reading, so asking moved inside the open panel. */
  const source = read('music.js');
  const item = source.slice(source.indexOf('function item('),
    source.indexOf('function paintShelf('));
  assert.ok(item.includes('toggle(track, node)'),
    'the row does not open on a tap');
  assert.ok(!item.includes('ask('),
    'tapping a record still asks the station for it');
  /* And the ask is still reachable - from the panel, and from the box. */
  assert.ok(source.includes('"ask for this"'));
  assert.ok(source.includes('root.PineMusic = {mount, isMounted: () => mounted, ask}'));
});

test('one record is open at a time, and it survives the feed rebuilding the list', () => {
  /* The queue list is rebuilt whenever its fingerprint changes - the
   * station moving on to the next record does that. Without the reopen in
   * item(), an open panel would slam shut under the operator's eyes every
   * time a track ended. */
  const source = read('music.js');
  assert.match(source, /if \(openId && String\(track\.id \|\| ""\) === openId\)/);
  assert.match(source, /if \(openId === id\) \{ closeOpen\(\); return; \}/);
  assert.match(source, /closeOpen\(\);\s*\n\s*openId = id;/);
});

/* ------------------------------------------------------- the real tap */

/* A SMOKE TEST WITH A HAND-ROLLED DOM, AND WHY IT IS WORTH THE SIXTY
 * LINES. Every other test in this file reads the source or the model. A
 * view that opens a record and throws on the first tap would pass all of
 * them and fail on the tablet, and there is no jsdom in this repo. So the
 * five DOM calls this panel actually makes - createElement, appendChild,
 * replaceChildren, classList and querySelectorAll - are stubbed just far
 * enough to run mount, one feed payload and one tap for real. */
function fakeDom() {
  const byId = new Map();
  const root = {name: 'ROOT'};

  function node(tag) {
    const self = {
      tag, parent: null, children: [], className: '', textContent: '',
      title: '', hidden: false, dataset: {}, style: {}, handlers: {},
      classList: {
        add: (...names) => { for (const n of names) self.classes.add(n); },
        remove: (...names) => { for (const n of names) self.classes.delete(n); },
        toggle: (n, on) => { if (on) self.classes.add(n); else self.classes.delete(n); },
        contains: (n) => self.classes.has(n)
      },
      classes: new Set(),
      attrs: {},
      setAttribute: (name, value) => { self.attrs[name] = String(value); },
      addEventListener: (type, fn) => {
        (self.handlers[type] = self.handlers[type] || []).push(fn);
      },
      appendChild: (child) => {
        if (child.tag === '#fragment') {
          for (const one of child.children) { one.parent = self; self.children.push(one); }
          child.children = [];
        } else { child.parent = self; self.children.push(child); }
        return child;
      },
      replaceChildren: (...args) => {
        self.children = [];
        for (const one of args) self.appendChild(one);
      },
      querySelector: (sel) => find(self, sel)[0] || null,
      click: () => { for (const fn of (self.handlers.click || [])) fn({stopPropagation() {}}); }
    };
    /* className is what row() sets; keep the class SET in step with it. */
    Object.defineProperty(self, 'cls', {get: () => self.className});
    return new Proxy(self, {
      set(target, key, value) {
        target[key] = value;
        if (key === 'className') {
          target.classes = new Set(String(value).split(/\s+/).filter(Boolean));
        }
        if (key === 'innerHTML') {
          /* build() writes one HTML string. Only the ids matter here:
           * everything afterwards reaches them through getElementById. */
          for (const m of String(value).matchAll(/id="([\w-]+)"/g)) {
            const made = node('div');
            made.parent = target;
            /* Into the TREE, not just into the map: closeOpen() finds the
             * open record with querySelectorAll from the document root,
             * and an id that is only in a lookup table is not in the
             * document. */
            target.children.push(made);
            byId.set(m[1], made);
          }
        }
        return true;
      }
    });
  }

  function matches(one, part) {
    return part.split('.').filter(Boolean).every((n) => one.classes.has(n));
  }
  function walk(from, out) {
    for (const child of from.children) { out.push(child); walk(child, out); }
    return out;
  }
  function find(from, sel) {
    const parts = sel.trim().split(/\s+/);
    let pool = walk(from, []).filter((one) => matches(one, parts[0]));
    for (const part of parts.slice(1)) {
      const next = [];
      for (const one of pool) {
        for (const deep of walk(one, [])) {
          if (matches(deep, part)) next.push(deep);
        }
      }
      pool = next;
    }
    return pool;
  }

  root.children = [];
  root.classes = new Set();
  return {
    byId, root,
    document: {
      readyState: 'complete',
      createElement: node,
      createDocumentFragment: () => node('#fragment'),
      getElementById: (id) => byId.get(id) || null,
      querySelectorAll: (sel) => find(root, sel),
      addEventListener: () => {}
    },
    host: (() => { const h = node('div'); h.parent = root; root.children.push(h); return h; })()
  };
}

test('mounting, a feed payload and one real tap do not throw', async () => {
  const dom = fakeDom();
  const asked = [];
  globalThis.document = dom.document;
  globalThis.PineListenModel = model;
  globalThis.PineStationFeed = {subscribe: (fn) => { dom.paint = fn; return () => {}; }};
  globalThis.pineDesktop = {
    get: async (url) => {
      asked.push(url);
      if (url.indexOf('/api/music/browse') === 0) return {total: 35982, results: []};
      if (url.indexOf('/api/schedule/hours') === 0) return {hours: []};
      if (url.indexOf('/api/dj/requested') === 0) return {requested: []};
      if (url.indexOf('/api/song-crystals') === 0) return crystalPayload();
      if (url.indexOf('/api/track-reads') === 0) return readsPayload();
      if (url.indexOf('/api/music/played') === 0) return playedPayload();
      if (url.indexOf('/api/music/track/') === 0) return metaPayload();
      if (url.indexOf('/api/dj/pending') === 0) return boardPayload();
      if (url.indexOf('/api/music/notes/') === 0) {
        return {id: '607ab40218b06561', notes: 'Listeners call it a sleeper.'};
      }
      throw new Error('unexpected route ' + url);
    },
    post: async () => ({ok: true})
  };
  delete require.cache[require.resolve('../desktop/renderer/music.js')];
  require('../desktop/renderer/music.js');

  await globalThis.PineMusic.mount(dom.host);
  assert.equal(globalThis.PineMusic.isMounted(), true);
  /* Mount asks for three things and NOT for any of the detail's - an
   * operator who never opens a record pays nothing for the panel. */
  assert.equal(asked.length, 3);
  assert.ok(!asked.some((url) => url.indexOf('/api/song-crystals') === 0));

  dom.paint({at: T, station: {
    on: true, server_ms: T, started_ms: T - 61000,
    now: {id: 'spun', title: 'Comes Round', artist: 'A', seconds: 200},
    upcoming: [{id: '607ab40218b06561', title: 'Analysed', artist: 'B'}],
    played: [{id: 'longread', title: 'A Long One', artist: 'C'}]
  }, now: null});

  const queue = dom.byId.get('muQueue');
  assert.equal(queue.children.length, 1, 'the queue drew no record');

  /* THE TAP. */
  const head = queue.children[0].children[0];
  head.click();
  await new Promise((done) => setImmediate(done));
  await new Promise((done) => setImmediate(done));

  assert.ok(queue.children[0].classes.has('open'), 'the record did not open');
  /* Three library reads and exactly one per-record read, and no more. */
  assert.deepEqual(asked.slice(3), [
    '/api/song-crystals', '/api/track-reads', '/api/music/played?limit=200',
    '/api/music/track/607ab40218b06561'
  ]);

  const panel = queue.children[0].children[1];
  const heads = panel.children.map((box) => (box.children[0] || {}).textContent);
  /* All four of the operator's asks are on screen, in order, plus the
   * record itself and its airings. The last child is the ask button. */
  assert.deepEqual(heads.slice(0, 6), ['The record',
    'What the station has analysed', 'What the pair have said about it',
    'What is queued for the host to say', 'On air',
    'What was looked up online']);
  assert.equal(heads[6], 'ask for this');

  /* THE TWO PRESSES, DRIVEN FOR REAL. Both sections start PENDING, both
   * carry their own button, and pressing each must fetch exactly the one
   * route it names and then repaint the open record in place. */
  const pressIn = (box) => box.children[box.children.length - 2];
  pressIn(panel.children[3]).click();
  await new Promise((done) => setImmediate(done));
  await new Promise((done) => setImmediate(done));
  assert.equal(asked[7], '/api/dj/pending');

  const repainted = queue.children[0].children[1];
  const prepared = repainted.children[3];
  assert.equal(prepared.children[0].textContent,
    'What is queued for the host to say');
  /* 607ab40218b06561 is not in the fixture board, so the honest answer
   * changes from "nobody has asked" to "not in the lookahead" - and the
   * button is gone, because there is nothing left to press. */
  assert.match(prepared.children[1].textContent, /not in the writers' lookahead/);

  pressIn(repainted.children[5]).click();
  await new Promise((done) => setImmediate(done));
  await new Promise((done) => setImmediate(done));
  assert.equal(asked[8], '/api/music/notes/607ab40218b06561');
  const research = queue.children[0].children[1].children[5];
  assert.equal(research.children[1].children[1].textContent,
    'Listeners call it a sleeper.');

  /* A SECOND TAP ON A SECOND ROW COSTS ONE REQUEST, NOT FOUR - the three
   * library reads are already in hand. That is the single-poller rule
   * paying off, and it is the thing most likely to be undone by accident. */
  const played = dom.byId.get('muPlayed');
  played.children[0].children[0].click();
  await new Promise((done) => setImmediate(done));
  await new Promise((done) => setImmediate(done));
  assert.deepEqual(asked.slice(9), ['/api/music/track/longread']);
  assert.ok(!queue.children[0].classes.has('open'), 'two records are open');

  delete globalThis.document;
  delete globalThis.PineListenModel;
  delete globalThis.PineStationFeed;
  delete globalThis.pineDesktop;
  delete globalThis.PineMusic;
});

test('every element the detail paints is an element the view builds', () => {
  /* The same cheap check the Listen/Music pair already carry: a paint
   * aimed at an element the build no longer creates fails silently in a
   * browser, forever. muLibNote is new with this change. */
  const source = read('music.js');
  const built = new Set();
  for (const match of source.matchAll(/\bid="([A-Za-z][\w-]*)"/g)) {
    built.add(match[1]);
  }
  for (const match of source.matchAll(/\b(?:el|put)\("([A-Za-z][\w-]*)"/g)) {
    assert.ok(built.has(match[1]),
      'music.js paints #' + match[1] + ' but never builds it');
  }
  assert.ok(built.has('muLibNote'));

  /* And the classes the panel paints are classes the stylesheet knows.
   * An unstyled .mu-empty is an invisible "nothing prepared", which is
   * the exact failure this whole change exists to prevent. */
  const css = read('listen-music.css');
  for (const name of ['mu-item', 'mu-detail', 'mu-sec', 'mu-fact', 'mu-line',
    'mu-empty', 'mu-fine', 'mu-feet']) {
    assert.ok(css.includes('.' + name), '.' + name + ' has no style');
  }
});
