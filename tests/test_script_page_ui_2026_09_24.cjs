const assert = require('node:assert/strict');
const {test} = require('node:test');
const view = require('../desktop/renderer/script-page.js').view;

test('live screenplay retains the API cue and interjection order across hours', () => {
  const before = [
    {type: 'scene', id: 'old-scene', at: 100},
    {type: 'dialogue', id: 'old-cue', line: 'a', block: 40, ord: 0}
  ];
  const current = [
    {type: 'scene', id: 'scene-1', at: 300},
    {type: 'dialogue', id: 'cue-1', line: 'b', block: 41, ord: 0},
    {type: 'action', id: 'board', at: 298},
    {type: 'dialogue', id: 'cue-2', line: 'c', block: 41, ord: 1},
    {type: 'scene', id: 'scene-2', at: 290},
    {type: 'dialogue', id: 'cue-3', line: 'd', block: 42, ord: 0}
  ];
  const ordered = view.screenplayOrder(before, current);
  assert.deepEqual(ordered.map((row) => row.id), [
    'old-scene', 'old-cue', 'scene-1', 'cue-1', 'board', 'cue-2',
    'scene-2', 'cue-3'
  ]);
  assert.equal(current[0].id, 'scene-1', 'the API payload remains untouched');
});

test('bank stock joins only the corresponding upcoming slot', () => {
  const at = 1800000000;
  const bank = {at, slots: [
    {commit_id: 'current:1799999900:slot-a', kind: 'banter',
      in_seconds: 0, current: true, items: [{sid: 'first'}]},
    {commit_id: 'slot-a@1800000600', kind: 'banter',
      in_seconds: 600, items: [{sid: 'second'}]},
    {commit_id: 'slot-b@1800000660', kind: 'news',
      in_seconds: 660, items: [{sid: 'third'}]}
  ]};
  const live = view.bankSlotFor({slot_id: 'slot-a', kind: 'banter',
    state: 'on air', start: at - 100}, bank);
  assert.equal(live.slot.items[0].sid, 'first');
  const next = view.bankSlotFor({slot_id: 'slot-a', kind: 'banter',
    start: at + 600}, bank, {[live.index]: 1});
  assert.equal(next.slot.items[0].sid, 'second');
  assert.equal(view.bankSlotFor({slot_id: 'slot-a', kind: 'news',
    start: at + 600}, bank), null);
  assert.equal(view.bankSlotFor({slot_id: 'slot-a', kind: 'banter',
    start: at + 1600}, bank), null);
  assert.equal(view.bankSlotFor({slot_id: 'slot-b', kind: 'news',
    start: at + 660}, bank).slot.items[0].sid, 'third');
  bank.slots.push({commit_id: 'slot-c@1800000900', kind: 'banter_caller',
    in_seconds: 900, items: []});
  assert.equal(view.bankSlotFor({slot_id: 'slot-c', kind: 'caller',
    start: at + 900}, bank).slot.kind, 'banter_caller');
});

test('missing System2 allocation is distinct from banked preparation', () => {
  const entry = {script: {turns: [], draft_turns: []}, review: {}};
  const stock = {ready_seconds: 516.5, written_only_seconds: 1042.2,
    short_seconds: 2041.3, items: [{sid: 'banked'}]};
  assert.equal(view.planReviewLabel(entry), 'No script allocated to this slot');
  assert.match(view.bankSlotText(stock), /516\.5s rendered/);
  assert.match(view.bankSlotText(stock), /1042\.2s written only/);
  assert.match(view.bankSlotText(stock), /2041\.3s missing/);
  assert.equal(view.planReviewLabel({script: {turns: [{text: 'ready'}]},
    review: {approved: true}}), 'Script approved');
});

test('visible fixed script host keeps live ticks running', () => {
  const fixed = {offsetParent: null, classList: {
    contains: (name) => name === 'pine-view-host' || name === 'open'
  }};
  assert.equal(view.scriptVisible(fixed, false), true);
  assert.equal(view.scriptVisible(fixed, true), false);
  assert.equal(view.scriptVisible({offsetParent: null, classList: {
    contains: (name) => name === 'pine-view-host'
  }}, false), false);
  assert.equal(view.scriptVisible({offsetParent: {}}, false), true);
});

test('playout receipt carries audible line identity, words and timing', () => {
  const heard = view.playoutRead({mode: 'linear', sounding: {
    occurrence_id: 'occ-1', line_id: '5b9078f27646491db73d64686a9849be',
    block: 12, ord: 3, file: 'round.mp3', position_s: 41.2,
    line_from: 38.5, line_until: 44.0, line_position_s: 2.7,
    position_basis: 'listener', last_heard_at: 1800000000,
    speaker: 'Athens', text: 'I moved closer and checked it twice.'
  }});
  assert.equal(heard.line_id, '5b9078f27646491db73d64686a9849be');
  assert.equal(heard.offset_s, 41.2);
  assert.equal(heard.line_from, 38.5);
  assert.equal(heard.line_until, 44);
  assert.equal(heard.position_basis, 'listener');
  assert.equal(heard.speaker, 'Athens');
  assert.equal(heard.text, 'I moved closer and checked it twice.');
});

test('live utterance paints its words and idle state on the strip', (t) => {
  const oldDocument = global.document;
  t.after(() => { global.document = oldDocument; });
  const who = {textContent: ''};
  const words = {textContent: '', scrollTop: 0};
  const classes = [];
  const strip = {dataset: {}, title: '', classList: {
    toggle(name, enabled) { classes.push([name, enabled]); }
  }};
  global.document = {
    getElementById(id) {
      return {spSayingWho: who, spSayingText: words, spSaying: strip}[id] || null;
    },
    querySelector() { return null; }
  };
  view.paintSaying({id: 'line-for-live-strip', road: 'playout',
    speaker: 'Skip', text: 'I checked the transmitter again.'});
  assert.equal(who.textContent, 'Skip');
  assert.equal(words.textContent, 'I checked the transmitter again.');
  assert.equal(strip.dataset.line, 'line-for-live-strip');
  assert.equal(strip.dataset.spoken, 'true');
  assert.deepEqual(classes.at(-1), ['sp-saying-idle', false]);
  view.paintSaying({id: 'clip-for-live-strip', road: 'playout',
    text: 'A sting off the board.'});
  assert.equal(strip.dataset.spoken, 'false');
  global.document.querySelector = () => ({className: 'sp-el sp-action',
    textContent: 'A clip cue.', previousElementSibling: null});
  view.paintSaying({id: 'clip-with-speaker-metadata', road: 'playout',
    speaker: 'Host', text: 'A clip cue.'});
  assert.equal(strip.dataset.spoken, 'false',
    'an action cue cannot offer dry voice or spoken ad actions');
});

test('content gate enables require explicit approval and do not enable peers', () => {
  const policy = {revision: 7, master_enabled: false,
    gates: {profile: false, tint: false}};
  assert.deepEqual(view.contentGateBody(policy, 'master', true),
    {expected_revision: 7, master_enabled: true,
      gates: {profile: false, tint: false}, approval: 'enable'});
  assert.deepEqual(view.contentGateBody({...policy, master_enabled: true,
    gates: {profile: true, tint: true}}, 'master', false),
    {expected_revision: 7, master_enabled: false,
      gates: {profile: false, tint: false}});
  assert.deepEqual(view.contentGateBody(policy, 'profile', true),
    {expected_revision: 7, gates: {profile: true}, approval: 'enable'});
  assert.deepEqual(view.contentGateBody(policy, 'profile', false),
    {expected_revision: 7, gates: {profile: false}});
  assert.equal(view.contentGateEffective(policy, 'profile'), false);
  assert.equal(view.contentGateEffective({...policy, master_enabled: true}, 'tint'), false);
  assert.equal(view.contentGateEffective({...policy, master_enabled: true,
    gates: {...policy.gates, profile: true}}, 'profile'), true);
});
