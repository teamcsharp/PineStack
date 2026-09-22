/* Which row is PLAYING, on the road the station actually uses.
 *
 * `stationRows()` feeds the LCD, the sampler's drag-from-feed panel and the
 * tablet's Kotlin port. All three ask it the same question: what is on the
 * air right now?
 *
 * It used to answer "nothing" for most of the show. `/api/dj` serialises a
 * stream_now turn as `{id, from, until}` and NOTHING ELSE (app.py:25295) -
 * no text. The current-speaker branch then guarded on `live.text`, which is
 * never set on such a turn, so the row was dropped by absorb() and nothing
 * was marked Playing. The single-line road (speaking_now) carries text and
 * worked, which is why it went unnoticed: the failing road is the coalesced
 * one, and the coalesced one is most of the broadcast.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {stationRows} = require('../desktop/renderer/lcd-dialogue.js');

const NOW = 1789000000000;
const AT = NOW / 1000 - 3;          /* three seconds into the round */

/* Exactly the shape app.py:25295 emits. Note: no `text` anywhere in rows. */
function coalesced(extra) {
  return Object.assign({
    chat: [
      {id: 'one', who: 'dj', name: 'Caine', kind: 'banter',
        text: 'the first line of the round', aired: 'stream'},
      {id: 'two', who: 'dj', name: 'Caine', kind: 'banter',
        text: 'the second line of the round', aired: 'stream'}
    ],
    stream_now: {at: AT, length: 30,
      rows: [{id: 'one', from: 0, until: 5}, {id: 'two', from: 5, until: 30}]},
    speaking_now: null
  }, extra || {});
}

test('a coalesced round marks the turn on the air as Playing', () => {
  const rows = stationRows(coalesced(), NOW);
  const playing = rows.filter((row) => row.lcdStatus === 'Playing');
  assert.equal(playing.length, 1, 'exactly one row is on the air');
  assert.equal(playing[0].id, 'one', 'three seconds in is inside [0,5)');
  /* The text has to survive, or the row is useless to every consumer. */
  assert.equal(playing[0].text, 'the first line of the round');
  assert.equal(playing[0].lcdAudio, true, 'a playing row is grabbable');
});

test('the playhead moves between turns as the round runs', () => {
  const later = stationRows(coalesced({
    stream_now: {at: NOW / 1000 - 12, length: 30,
      rows: [{id: 'one', from: 0, until: 5}, {id: 'two', from: 5, until: 30}]}
  }), NOW);
  const playing = later.filter((row) => row.lcdStatus === 'Playing');
  assert.equal(playing.length, 1);
  assert.equal(playing[0].id, 'two', 'twelve seconds in is inside [5,30)');
  assert.equal(playing[0].text, 'the second line of the round');
});

test('the current speaker stays in script order, so it does not jump around', () => {
  const rows = stationRows(coalesced(), NOW);
  assert.deepEqual(rows.map((row) => row.id), ['one', 'two']);
  assert.equal(rows[0].lcdStatus, 'Playing');
  assert.equal(rows[1].lcdStatus, 'Aired');
});

test('the single-line road still works - it always did', () => {
  const rows = stationRows({
    chat: [{id: 'solo', who: 'dj', name: 'Caine', kind: 'banter',
      text: 'a single line', aired: 'stream'}],
    stream_now: null,
    speaking_now: {id: 'solo', who: 'dj', text: 'a single line'}
  }, NOW);
  const playing = rows.filter((row) => row.lcdStatus === 'Playing');
  assert.equal(playing.length, 1);
  assert.equal(playing[0].text, 'a single line');
});

test('a turn whose id is in no chat row is not invented out of nothing', () => {
  /* absorb() drops a row with no text, and there is no text to be had:
   * better to show nothing than a blank bubble. */
  const rows = stationRows({
    chat: [],
    stream_now: {at: AT, length: 30, rows: [{id: 'ghost', from: 0, until: 30}]},
    speaking_now: null
  }, NOW);
  assert.deepEqual(rows, []);
});

test('a round that has finished stops claiming to be on the air', () => {
  const rows = stationRows(coalesced({
    /* started a full two minutes ago; length 30 plus the 4s grace is past */
    stream_now: {at: NOW / 1000 - 120, length: 30,
      rows: [{id: 'one', from: 0, until: 5}, {id: 'two', from: 5, until: 30}]}
  }), NOW);
  assert.equal(rows.some((row) => row.lcdStatus === 'Playing'), false);
  assert.equal(rows.length, 2, 'but the lines are still listed');
});

test('rows without audio are still listed, just not grabbable', () => {
  const rows = stationRows({
    chat: [{id: 'held', who: 'dj', text: 'written but never aired',
      kind: 'banter', aired: 'page'}],
    stream_now: null, speaking_now: null
  }, NOW);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].lcdAudio, false);
  assert.equal(rows[0].lcdStatus, 'Awaiting playback');
});
