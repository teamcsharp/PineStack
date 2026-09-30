// [reply-gap:door] the page players: the pause after every message is kept on
// the page, the silent tail gives way to a shorter pause, and the views are
// told the moment the words end and exactly when the next message starts.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const app = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
const HEAD = '/* [reply-gap:door] THE PAUSE BETWEEN MESSAGES, ON THIS PAGE.';
const first = app.indexOf(HEAD);
assert(first > 0, 'the panel carries the helpers');
const second = app.indexOf(HEAD, first + 1);
assert(second > first, 'the tune page carries them too');
assert(app.indexOf(HEAD, second + 1) < 0, 'exactly two pages');
const panelEnd = app.indexOf('function djVoiceNext() {', first);
assert(panelEnd > first && panelEnd < app.indexOf('RADIO_PAGE_HTML = r"""'), 'the panel\'s are right above djVoiceNext');
assert(app.indexOf('function voiceNext() {', second) > second, 'the tune page\'s are right above voiceNext');
const code = app.slice(first, panelEnd);

function load() {
  const events = [];
  const window = {dispatchEvent: e => events.push(e)};
  class CustomEvent { constructor(type, init) { this.type = type; this.detail = init.detail; } }
  // eslint-disable-next-line no-new-func
  const api = new Function('window', 'CustomEvent',
    code.replace('let pineReplyGapEndAt = 0;', 'var pineReplyGapEndAt = 0;')
    + ';return {floor: pineReplyGapFloor, cue: pineReplyGapCue, ended: pineReplyGapWordsEnded,'
    + ' early: pineReplyGapEarly, due: pineReplyGapDue, endAt: () => pineReplyGapEndAt};')(window, CustomEvent);
  return {api, events};
}

// 1. Before any words have ended there is no floor.
{
  const {api} = load();
  assert.strictEqual(api.floor({gap_before: {s: 2}}), 0);
  assert.strictEqual(api.floor({}), 0);
}

// 2. The words end 0.2 s before the tail's start was crossed: the pause runs
//    from there, the next clip is cued with the moment it will start.
{
  const {api, events} = load();
  const now = Date.now();
  const next = {gap_before: {s: 1.5, rolled: true, dice: 9, lo: 0.2, hi: 2.9, id: 'r1'},
    broadcastAt: now - 5000, text: 'DILL: hello'};
  const el = {currentTime: 2.3, duration: 3};
  api.ended({tail_s: 0.9}, el, [next]);
  const endAt = api.endAt();
  assert(Math.abs(endAt - (now - 200)) < 60, 'the words ended at duration - tail: ' + (now - endAt));
  assert.strictEqual(api.floor(next), endAt + 1500);
  assert.strictEqual(events.length, 1, 'the views are told');
  const d = events[0].detail;
  assert.strictEqual(events[0].type, 'pine-reply-gap');
  assert.strictEqual(d.s, 1.5);
  assert.strictEqual(d.rolled, true);
  assert.strictEqual(d.dice, 9);
  assert(Math.abs(d.startsAt - (endAt + 1500)) < 60, 'it starts when the page\'s timer will start it');
  api.cue(next, 0);
  assert.strictEqual(events.length, 1, 'once per message');
}

// 3. A late page keeps the pause: a clip stamped in the past still waits it out.
{
  const {api} = load();
  api.ended({tail_s: 0}, null, []);
  const next = {gap_before: {s: 3}, broadcastAt: Date.now() - 60000};
  assert(api.due(next) - Date.now() > 2900, 'three seconds of pause, however late');
}

// 4. The silent tail gives way to a shorter pause, never to a longer one.
{
  const {api} = load();
  const el = {currentTime: 2.25, duration: 3};
  const soon = {gap_before: {s: 0.2}, broadcastAt: 0};
  assert.strictEqual(api.early({tail_s: 0.9}, el, [soon]), true, 'a 0.2 s pause: hand over inside the tail');
  const {api: api2} = load();
  const later = {gap_before: {s: 2}, broadcastAt: 0};
  assert.strictEqual(api2.early({tail_s: 0.9}, el, [later]), false, 'a 2 s pause: the tail plays on');
  const {api: api3} = load();
  assert.strictEqual(api3.early({tail_s: 0.9}, {currentTime: 1.0, duration: 3}, [soon]), false, 'still talking');
  assert.strictEqual(api3.early({tail_s: 0}, el, [soon]), false, 'no measured tail: never cut');
  assert.strictEqual(api3.early({tail_s: 0.9}, el, [{broadcastAt: 0}]), false, 'a reply with no pause: untouched');
}

// 5. Wired where the players decide.
assert.strictEqual((app.match(/pineReplyGapFloor\(clip\)\) - Date\.now\(\);\n  pineReplyGapCue\(clip, waitForAir\);/g) || []).length, 2,
  'both players wait at least the pause and cue it');
assert(app.includes('if (pineReplyGapEarly(clip, player, djVoiceQueue)) {'), 'the panel hands over at the words\' end');
assert(app.includes('if (pineReplyGapEarly(clip, voice, voiceQueue)) {'), 'the tune page too');
console.log('reply-gap player: ok');
