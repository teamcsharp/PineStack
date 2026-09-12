/* The audio routing table, and who takes the air when the tablet goes dark.
 *
 * The operator's rule, in his words: the tablet is primary, and the desktop
 * takes over "when i turn the tablet off or switch it's broadcast off".
 * Those are two DIFFERENT events - a row set to play=false, and a device
 * that simply stops appearing in the listener roster - and both have to
 * land in the same place. That is what these pin.
 *
 * The other thing pinned here is the clamp. On the tablet a voice level of
 * 1.6 throws IndexSizeError on <audio>.volume, which is why the DJs were
 * silent while music played. The desktop survives it only because it runs
 * through a GainNode. Measured on hardware; do not relax it.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {
  decide, forMe, update, presenceOf, safeLevel, STALE_SECONDS
} = require('../desktop/terminal-audio.cjs');

const TABLE = {
  terminals: {
    pinetab: {name: 'PineTab', play: true, music: 0.8, voice: 1, reply: 1,
      addr: '10.89.1.154', listener: 'pbnvgdtefn'},
    desktop: {name: 'This app', play: false, music: 0.6, voice: 0.6,
      reply: 0.6, fallback: true, addr: '10.89.1.246'}
  }
};

const roster = (rows) => ({listeners: rows});
const tabHere = {listener: 'pbnvgdtefn', addr: '10.89.1.154', seen: 4.2};
const deskHere = {listener: 'qqq', addr: '10.89.1.246', seen: 1.1};

test('the tablet plays alone while it is switched on and present', () => {
  const out = decide(TABLE, roster([tabHere, deskHere]));
  assert.deepEqual(out.playing, ['pinetab']);
  assert.equal(out.singular, true);
  assert.equal(out.takeover, '');
  assert.equal(forMe(out, 'desktop').play, false);
  assert.equal(forMe(out, 'pinetab').play, true);
});

test('the tablet carries its own levels, set from the desktop', () => {
  const mine = forMe(decide(TABLE, roster([tabHere, deskHere])), 'pinetab');
  assert.equal(mine.music, 0.8);
  assert.equal(mine.voice, 1);
});

test('a device that is not playing is handed zeros, not its stored levels', () => {
  /* Or a client that forgets to check `play` leaks the show into the room
   * the operator just silenced. */
  const mine = forMe(decide(TABLE, roster([tabHere, deskHere])), 'desktop');
  assert.equal(mine.play, false);
  assert.equal(mine.music, 0);
  assert.equal(mine.voice, 0);
  assert.equal(mine.reply, 0);
});

test('switching the tablet off hands the air to the desktop', () => {
  const off = update(TABLE, 'pinetab', {play: false}).settings;
  const out = decide(off, roster([tabHere, deskHere]));
  assert.deepEqual(out.playing, ['desktop']);
  assert.equal(out.takeover, 'desktop');
  assert.equal(forMe(out, 'desktop').music, 0.6);
});

test('turning the tablet OFF hands the air over too - it just stops being seen', () => {
  const out = decide(TABLE, roster([deskHere]));
  assert.deepEqual(out.playing, ['desktop']);
  assert.equal(out.takeover, 'desktop');
  assert.match(out.rows.desktop.why, /PineTab/);
  assert.match(out.rows.desktop.why, /roster/);
});

test('a stale tablet counts as gone, and a fresh one does not', () => {
  const stale = decide(TABLE, roster([{...tabHere, seen: STALE_SECONDS + 5}, deskHere]));
  assert.equal(stale.takeover, 'desktop');
  assert.match(stale.rows.desktop.why, /last heard from/);

  const fresh = decide(TABLE, roster([{...tabHere, seen: STALE_SECONDS - 1}, deskHere]));
  assert.deepEqual(fresh.playing, ['pinetab']);
});

test('the tablet is found by address when its listener id has rolled', () => {
  /* The panel mints a new listener id on reload; the address outlives it. */
  const out = decide(TABLE, roster([{listener: 'brandnew', addr: '10.89.1.154', seen: 2}]));
  assert.deepEqual(out.playing, ['pinetab']);
});

test('the desktop does not take over while it is itself absent', () => {
  const out = decide(TABLE, roster([]));
  assert.deepEqual(out.playing, []);
  assert.equal(out.silent, true);
  assert.equal(out.takeover, '');
});

test('two devices switched on DELIBERATELY are both honoured', () => {
  /* "Make sure i can shift + click to map audio to multiple devices."
   *
   * An earlier cut resolved this down to one. That was aimed at the wrong
   * thing: what produced two rooms by ACCIDENT was routing to `here` with
   * no solo owner, so every open page sounded - fixed in the destination
   * picker, not here. This table is an explicit statement, and overriding
   * it silently is worse than either outcome. */
  const both = update(TABLE, 'desktop', {play: true}).settings;
  const out = decide(both, roster([tabHere, deskHere]));
  assert.deepEqual(out.playing.sort(), ['desktop', 'pinetab']);
  assert.equal(out.contested, true, 'and it SAYS two rooms are playing');
  assert.equal(out.singular, false, 'reported, not enforced');
  assert.equal(out.takeover, '', 'nothing was taken over');
  assert.equal(forMe(out, 'pinetab').play, true);
  assert.equal(forMe(out, 'pinetab').music, 0.8, 'each keeps its own levels');
  assert.equal(forMe(out, 'desktop').music, 0.6);
});

test('one device switched on is not reported as contested', () => {
  const out = decide(TABLE, roster([tabHere, deskHere]));
  assert.equal(out.contested, false);
  assert.equal(out.singular, true);
});

test('a device with no row in the table stays quiet', () => {
  const out = decide(TABLE, roster([tabHere]));
  const mine = forMe(out, 'somebody-elses-laptop');
  assert.equal(mine.play, false);
  assert.match(mine.why, /no row/);
});

test('levels above 1.0 are clamped - <audio>.volume THROWS above one', () => {
  assert.equal(safeLevel(1.6), 1);
  assert.equal(safeLevel(-3), 0);
  assert.equal(safeLevel('0.4'), 0.4);
  assert.equal(safeLevel(undefined, 0.5), 0.5);
  assert.equal(safeLevel('loud', 0.5), 0.5);
  const row = update(TABLE, 'pinetab', {voice: 1.6}).row;
  assert.equal(row.voice, 1);
});

test('an update returns the WHOLE settings document, other keys intact', () => {
  /* PUT /api/settings replaces the document, so a partial write would drop
   * every other setting on the station. */
  const before = {...TABLE, dj: {voice: 'caine'}, pinetab: {audio: true}};
  const after = update(before, 'pinetab', {music: 0.3}).settings;
  assert.deepEqual(after.dj, {voice: 'caine'});
  assert.deepEqual(after.pinetab, {audio: true});
  assert.equal(after.terminals.pinetab.music, 0.3);
  assert.equal(after.terminals.pinetab.voice, 1, 'untouched levels survive');
  assert.equal(after.terminals.desktop.name, 'This app', 'the other device survives');
  assert.equal(before.terminals.pinetab.music, 0.8, 'the input is not mutated');
});

test('an update names a device that has never been seen before', () => {
  const out = update({}, 'Booth', {play: true, name: 'Booth iPad', music: 0.5});
  assert.equal(out.ok, true);
  assert.equal(out.settings.terminals.booth.name, 'Booth iPad');
  assert.ok(out.settings.terminals.booth.at > 0, 'stamped so clients see it change');
});

test('an update with no device named is refused rather than guessed at', () => {
  assert.equal(update(TABLE, '', {play: true}).ok, false);
});

test('presence survives a roster handed over as a bare array', () => {
  const seen = presenceOf({addr: '10.89.1.154'}, [tabHere]);
  assert.equal(seen.present, true);
  assert.ok(seen.seen < 5);
});

test('a roster row with no age is not treated as present', () => {
  /* A missing `seen` is an unknown age, and an unknown age must never be
   * read as "here" - that is how a dark tablet holds a silent room. */
  const seen = presenceOf({addr: '10.89.1.154'}, [{addr: '10.89.1.154'}]);
  assert.equal(seen.present, false);
});

test('an empty table is silent rather than everyone at once', () => {
  const out = decide({}, roster([tabHere, deskHere]));
  assert.deepEqual(out.playing, []);
  assert.equal(out.silent, true);
});
