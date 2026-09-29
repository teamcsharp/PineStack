/* [s3-visuals] The client side of "roulette where they rotate" (2026-09-28).
 *
 * GAP 7: the slideshow view no longer holds ANY randomness of its own. The
 * shuffle seed is the station's deal (seed: 0 on the first ask, the dealt
 * seed adopted from the answer), each advance's transition is the one the
 * station dealt onto the row (slideshow.transition, a tabled pool), and the
 * shatter shards scatter off a seeded LCG. The proof the audit asked for is
 * a grep: Math.random appears NOWHERE in the file - and both surfaces (the
 * desk copy and the kiosk bundle copy) carry the same text; the desk copy is
 * LF, and the kiosk copy may be CRLF on a host checkout (git's index holds
 * LF - text=auto), which the edit tool preserves rather than rewrites.
 *
 * GAP 6: ad-viewer's usedWords() - the very function the popup paints -
 * words the hourly door's rolls when a row carries them (rec.rolls), and
 * says nothing when none were made: never fake dice. The existing preset
 * summary ("rolled by System 3: d100 ...") is untouched and lights up the
 * moment roll data arrives.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..');
const PAIRS = [
  ['desktop/renderer/slideshow.js', 'app/src/main/assets/pine-views/slideshow.js'],
  ['desktop/renderer/ad-viewer.js', 'app/src/main/assets/pine-views/ad-viewer.js']
];

test('both surfaces of each view carry the same text, the desk copy LF', () => {
  for (const [desk, kiosk] of PAIRS) {
    const a = fs.readFileSync(path.join(ROOT, desk), 'utf8');
    const b = fs.readFileSync(path.join(ROOT, kiosk), 'utf8');
    assert.equal(b.replace(/\r\n/g, '\n'), a, desk + ' and its kiosk copy have forked');
    assert.ok(!a.includes('\r\n'), desk + ' picked up CRLF');
  }
});

test('the slideshow holds no randomness of its own - the station deals', () => {
  const show = fs.readFileSync(path.join(ROOT, PAIRS[0][0]), 'utf8');
  assert.ok(!/Math\.random/.test(show),
    'Math.random is back in slideshow.js - the deal belongs to the station (slideshow.deal)');
  assert.ok(show.includes('seed: 0,'),
    'the first ask must bring no seed, so the playlist door rolls the deal');
  assert.ok(show.includes('if (body && body.seed) S.seed = body.seed;'),
    'the dealt seed must be adopted, or every reload would re-deal');
  assert.ok(show.includes('row.transition'),
    "an advance consumes the transition the station dealt onto the row");
  assert.ok(show.includes('CONCRETE[S.shown % CONCRETE.length]'),
    'an older station that dealt nothing gets a plain rotation, never dice of the page’s own');
  assert.ok(show.includes('pick(S.items[next])') && show.includes('pick(S.items[index])'),
    'every pick() call hands in the row whose entrance it is');
});

test('the slideshow module still loads under node and exports its mount', () => {
  const view = require(path.join(ROOT, PAIRS[0][0]));
  assert.equal(typeof view.mount, 'function');
  assert.equal(view.TRANSITIONS[0], 'all');
  assert.equal(view.TRANSITIONS.length, 20);
});

test("ad-viewer words the hourly door's rolls, and only real ones", () => {
  const viewer = require(path.join(ROOT, PAIRS[1][0]));
  const rec = {
    hour: 'h3h-1', at: 1790586208, how: 'dice', road: 'clip',
    preset: {id: 'p-1', name: 'Chefs at war'},
    roll: {by: 'system3', dice: 37, index: 2, of: 3},
    rolls: {
      source: {kind: 'pick', key: 'h3.hourly_source', picked: 'dialogue clip', dice: 61, index: 2, of: 2},
      fresh: {kind: 'pick', key: 'h3.hourly_fresh', picked: 'clip:00ab', dice: 14, index: 133, of: 9481},
      marker: {kind: 'roll', key: 'h3.hourly_marker', dice: 51, u: 0.502},
      host: {kind: 'chance', key: 'h3.hourly_host', hit: false, odds: 0.2, dice: 91}
    },
    goal: 'Two chefs fight', direction: 'In a kitchen.', speech: 'Pine Box FM!',
    style: '', constraints: '', audio_direction: ''
  };
  const w = viewer.usedWords({prompt_id: 'a', files: ['x.mp4'], h3_prompts: rec});
  assert.equal(w.summary, '"Chefs at war" - rolled by System 3: d100 37, 2 of 3 - clip road',
    'the existing preset summary is untouched');
  const rolls = w.items.find((i) => i.label === 'Hourly rolls');
  assert.ok(rolls, 'a row that carries the door’s rolls shows them');
  assert.ok(rolls.text.includes('source: dialogue clip (d100 61, 2 of 2)'), rolls.text);
  assert.ok(rolls.text.includes('fresh pick: clip:00ab (d100 14, 133 of 9481)'), rolls.text);
  assert.ok(rolls.text.includes('window marker: d100 51'), rolls.text);
  assert.ok(rolls.text.includes('host: no (d100 91 against 20%)'), rolls.text);

  const bare = viewer.usedWords({prompt_id: 'b', files: ['y.mp4'],
    h3_prompts: Object.assign({}, rec, {rolls: null})});
  assert.ok(!bare.items.some((i) => i.label === 'Hourly rolls'),
    'no rolls recorded, no rolls item - never fake dice');
  assert.deepEqual(bare.items.map((i) => i.label),
    ['Brief', 'Direction sent', 'Line spoken'],
    'the item list is exactly what it was before this change');
});
