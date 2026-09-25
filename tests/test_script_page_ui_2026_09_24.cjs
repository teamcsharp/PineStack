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

test('live cue window follows playout order, then feed order when the burst ends', () => {
  const stream = {rows: [
    {id: 'line-b', text: 'Second', name: 'Host', kind: 'banter'},
    {id: 'sting', text: 'Station sting', kind: 'sfx'},
    {id: 'line-a', text: 'First', name: 'Guest', kind: 'banter'}
  ]};
  const feed = [
    {id: 'late', text: 'Later', air_at: 300},
    {id: 'sting', text: 'Station sting', air_at: 200},
    {id: 'line-a', text: 'First', air_at: 100},
    {id: 'next', text: 'Next line', air_at: 400}
  ];
  const screenplay = [{type: 'dialogue', line: 'line-a', text: 'Old copy'}];
  const inBurst = view.liveCueWindow({id: 'sting'}, stream, screenplay, 2, feed);
  assert.deepEqual(inBurst.map((row) => row.id), ['line-b', 'sting', 'line-a']);
  assert.deepEqual(inBurst.map((row) => row.relative), [-1, 0, 1]);
  assert.equal(inBurst[1].current, true);
  const afterBurst = view.liveCueWindow({id: 'late'}, stream, screenplay, 2, feed);
  assert.deepEqual(afterBurst.map((row) => row.id), ['line-a', 'sting', 'late', 'next']);
  assert.equal(afterBurst[2].current, true);
  assert.equal(view.liveCueWindow(null, stream, screenplay, 2, feed).length, 0);
});

test('upcoming desk keeps each scheduled occurrence once and skips aired slots', () => {
  const now = 1800000000;
  const live = {occurrence: 'live', slot_id: 'banter', state: 'on air',
    start: now - 30, deadline: now + 30, label: 'Live'};
  const next = {occurrence: 'next', slot_id: 'banter', state: 'planned',
    start: now + 30, deadline: now + 90, label: 'Next'};
  const later = {occurrence: 'later', slot_id: 'banter', state: 'planned',
    start: now + 90, deadline: now + 150, label: 'Later'};
  const aired = {occurrence: 'past', slot_id: 'news', state: 'aired',
    start: now - 90, deadline: now - 30};
  const hours = [
    {hour: 'current', entries: [aired, live, next, later]},
    {hour: 'next', entries: [next, later]}
  ];
  const queue = view.readinessQueue(hours, null, now, 8);
  assert.deepEqual(queue.map((item) => item.key), ['live', 'next', 'later']);
  assert.equal(queue[0].live, true);
  assert.equal(view.readinessWhen(queue[1]), '30s');
  assert.equal(view.readinessWhen(view.readinessOf({state: 'unplanned'}, null, now)), '--:--');
});

test('readiness distinguishes draft review from recorded allocation', () => {
  const now = 1800000000;
  const entry = {occurrence: 'slot-1', state: 'planned', start: now + 60,
    minutes: 2, script: {state: 'bound', seconds: 85, turns: [
      {text: 'Opening', candidate_index: 0, performance_index: 0},
      {text: 'Response', candidate_index: 0, performance_index: 1}
    ], performances: [{index: 0, turns: 1, seconds: 40},
      {index: 1, turns: 1, seconds: 45}]}, review: {approved: false},
    orchestration: {status: 'ready', have: {lines: 2, events: 2, seconds: 85},
      target: {lines: 4, events: 4, seconds: 100}, short: {seconds: 15},
      stages: {written: true, reviewed: false, recorded: true,
        scheduled: true, executed: false}}};
  const pending = view.readinessOf(entry, null, now);
  assert.equal(pending.ready, false);
  assert.equal(pending.status, 'awaiting-review');
  assert.equal(pending.readySeconds, 85);
  assert.equal(pending.targetSeconds, 100);
  assert.deepEqual(pending.performances.map((row) => row.seconds), [40, 45]);
  entry.orchestration.stages.reviewed = true;
  assert.equal(view.readinessOf(entry, null, now).ready, true);

  const draft = view.readinessOf({state: 'drafts waiting', start: now + 120,
    script: {state: 'drafts', selected_candidate: 'draft-a', draft_turns: [
      {text: 'Draft opening', candidate_index: 0, performance_index: 0}
    ], draft_variants: [{id: 'draft-a', turns: [{text: 'Draft opening'}]}]}}, null, now);
  assert.equal(draft.draftOnly, true);
  assert.equal(draft.turns[0].text, 'Draft opening');
  assert.equal(draft.readySeconds, 0);
  assert.equal(draft.ready, false);
  assert.deepEqual(view.turnEditBody({text: 'Original', candidate_index: 1,
    performance_index: 2, candidate: 'take-c'}, 9, 'Revision'), {
    index: 1, candidate_index: 1, performance_index: 2,
    text: 'Revision', was: 'Original', candidate: 'take-c'
  });
});

test('upcoming desk gates director readiness on measured bank contract and shows room debts', (t) => {
  const now = 1800000000;
  const entry = {occurrence: 'banter-next', slot_id: 'banter-a', kind: 'banter',
    state: 'planned', start: now + 120, label: 'Banter', minutes: 2,
    script: {state: 'bound', turns: [{text: 'Opening'}]},
    review: {approved: true}, orchestration: {status: 'ready',
      have: {seconds: 120, lines: 1}, target: {seconds: 120, lines: 1},
      short: {seconds: 0}, stages: {written: true, reviewed: true,
        recorded: true, scheduled: true, executed: false}}};
  const slot = {commit_id: 'banter-a@1800000120', kind: 'banter',
    in_seconds: 120, coverage: {ready: false, target_seconds: 120,
      scripted_seconds: 55, recorded_seconds: 45, covered_seconds: 70,
      short_seconds: 65, script_short_seconds: 65,
      recording_short_seconds: 75, duration_short_seconds: 50,
      missing_roles: ['host', 'guest'], missing_turns: 2,
      missing_events: 1, missing_bookends: ['outro'],
      missing_recorded_bookends: ['intro']}, tasks: [
      {room: 'schedule', ready: true, want_seconds: 0},
      {room: 'writing', ready: false, want_seconds: 65,
        prepare_by_in_seconds: 60},
      {room: 'recording', ready: false, want_seconds: 75,
        prepare_by_in_seconds: 60},
      {room: 'assembly', ready: false, want_seconds: 50,
        prepare_by_in_seconds: 60},
      {room: 'pantry', ready: false, want_seconds: 65,
        prepare_by_in_seconds: 60}
    ]};
  const item = view.readinessQueue([{entries: [entry]}],
    {at: now, slots: [slot]}, now, 8)[0];
  assert.equal(item.ready, false);
  assert.equal(item.status, 'contract-incomplete');
  assert.match(view.readinessCardCoverage(item), /70\/120s measured \/ 65s short/);
  const detail = view.readinessBankDetail(item.bank);
  assert.equal(detail.ready, false);
  assert.deepEqual(detail.facts, ['55.0s scripted', '45.0s recorded',
    '70.0s/120.0s playable coverage']);
  assert.ok(detail.gaps.includes('65.0s script short'));
  assert.ok(detail.gaps.includes('50.0s playable short'));
  assert.ok(detail.gaps.includes('Roles: host, guest'));
  assert.ok(detail.gaps.includes('2 turns missing'));
  assert.ok(detail.gaps.includes('Write bookends: outro'));
  assert.ok(detail.gaps.includes('Record bookends: intro'));
  assert.deepEqual(detail.tasks.filter((task) => !task.ready)
    .map((task) => task.room), ['writing', 'recording', 'assembly', 'pantry']);

  const oldDocument = global.document;
  t.after(() => { global.document = oldDocument; });
  const makeNode = (tag) => ({tag, className: '', textContent: '',
    children: [], dataset: {}, scrollTop: 0,
    appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    setAttribute() {}, addEventListener() {}});
  const detailNode = makeNode('div');
  global.document = {createElement: makeNode,
    getElementById: (id) => id === 'spReadinessDetail' ? detailNode : null};
  view.paintReadinessDetail(item);
  const collect = (node) => [node.textContent, ...node.children.flatMap(collect)];
  const contractNode = detailNode.children.find((node) =>
    node.className === 'sp-ready-contract');
  assert.ok(contractNode);
  const rendered = collect(contractNode).join(' ');
  assert.match(rendered, /Measured contract incomplete/);
  assert.match(rendered, /Roles: host, guest/);
  assert.match(rendered, /Write bookends: outro/);
  assert.match(rendered, /writing owed \/ 65\.0s \/ due in 1m/);
  assert.match(rendered, /pantry owed \/ 65\.0s \/ due in 1m/);

  const legacy = view.readinessOf(entry, {ready_seconds: 120}, now);
  assert.equal(legacy.ready, true);
  assert.equal(legacy.status, 'ready');
  assert.equal(view.readinessBankDetail(legacy.bank), null);
  assert.match(view.readinessCardCoverage(legacy), /120\/120s$/);
  assert.equal(view.readinessOf(entry,
    {coverage: {...slot.coverage, ready: true}}, now).ready, true);
});
