const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const view = require('../desktop/renderer/script-page.js').view;
const source = readFileSync(join(__dirname, '../desktop/renderer/script-page.js'), 'utf8');

test('marquee reads only pending items, never the much larger event stream', () => {
  const payload = {
    items: [
      {id: 'pending-1', review_status: 'pending', kind: 'caller', reasons: ['call contract']},
      {id: 'done-1', review_status: 'kept'},
      {id: 'pending-2', review_status: 'pending', kind: 'news'}
    ],
    events: [{id: 'historical-event', review_status: 'pending'}],
    next_before: 86041,
    has_more: true
  };
  assert.deepEqual(view.rejectionPageItems(payload).map((item) => item.id),
    ['pending-1', 'pending-2']);
  assert.equal(view.rejectionListUrl(),
    '/api/orchestrator/rejections?status=pending&limit=24');
  assert.equal(view.rejectionListUrl(payload.next_before),
    '/api/orchestrator/rejections?status=pending&limit=24&before=86041');
  assert.throws(() => view.rejectionPageItems({events: payload.events}),
    /Invalid review queue/);
});

test('markers name their issue for assistive technology', () => {
  assert.equal(view.rejectionGlyph({kind: 'caller'}), '🎙️');
  assert.equal(view.rejectionGlyph({kind: 'video'}), '🎬');
  assert.equal(view.rejectionLabel({kind: 'caller', reasons: ['bad source']}),
    'caller: bad source');
  assert.equal(view.rejectionLabel({}), 'script: Review needed');
});

test('private note has no decision action; decisions carry optimistic revisions', () => {
  const detail = {revision: 4, event_seq: 86223, latest_seq: 86224};
  const item = {event_seq: 86200};
  assert.deepEqual(view.rejectionBody(detail, item, 'note', 'Check source'), {
    note: 'Check source', expected_revision: 4, expected_event_seq: 86223
  });
  assert.deepEqual(view.rejectionBody(detail, item, 'allow', 'Reviewed'), {
    note: 'Reviewed', expected_revision: 4, expected_event_seq: 86223,
    action: 'allow'
  });
  assert.equal(view.rejectionBody({revision: 0}, item, 'keep', '').action, 'keep');
});

test('reply appends dictated text and keeps a one-shot orchestrator instruction', () => {
  assert.deepEqual(view.rejectionDirectorBody({kind: 'caller'}, {context: {kind: 'news'}}, '  Slow the intro  '), {
    kind: 'news', text: 'Slow the intro', scope: 'next', who: 'operator'
  });
  assert.deepEqual(view.rejectionDirectorBody({}, {context: {kind: 'news'}}, '  Verify names  '), {
    kind: 'news', text: 'Verify names', scope: 'next', who: 'operator'
  });
  assert.equal(view.rejectionDirectorBody({kind: 'caller'},
    {context: {kind: 'news'}}, 'Check this').kind, 'news',
  'the review record kind is the one the reply endpoint actually directs');
  assert.equal(view.rejectionDirectorBody({kind: 'caller'}, {}, 'Check this').kind, '',
    'the UI cannot direct a kind the review endpoint does not know');
  assert.equal(view.rejectionBody({revision: 4, event_seq: 8}, {event_seq: 8}, 'allow', '')
    .scope, undefined, 'review decisions never carry director scope');
  assert.equal(view.rejectionAppendWords('typed first', ' dictated later '),
    'typed first dictated later');
  assert.equal(view.rejectionAppendWords('typed first dictated later', ' again '),
    'typed first dictated later again');
  assert.equal(view.rejectionAppendWords('typed first', ''), 'typed first');
  const decisions = source.split('function rejectionAct(action) {')[1]
    .split('function rejectionDirectNext() {')[0];
  const direction = source.split('function rejectionDirectNext() {')[1]
    .split('/* ------------------------------------------------------------ 1, 2, 3 */')[0];
  assert.doesNotMatch(decisions, /\/reply/);
  assert.match(direction, /api\/orchestrator\/rejections\/.*\/reply/);
  assert.match(source, /dot\.captureNext\(function \(words\)/);
  assert.match(source, /rejectionAppendWords\(selected\.draft, words\)/);
  assert.match(source, /selected\.sendAfterDictation = true/);
  assert.match(source, /if \(rejectionSelection\) rejectionClose\(\)/);
  assert.match(source, /selected !== rejectionSelection\) return/);
});

test('the live mark is unique and the strip uses the same active row', () => {
  const tick = source.split('function tick() {')[1].split('/* #1286:')[0];
  assert.match(tick, /var row = activeRow\(\)/);
  assert.match(tick, /var shown = paintSaying\(row\)/);
  assert.match(tick, /placeMarks\(lastDecision, fallback\)/);
  assert.match(tick, /paintSaying\(row\)/);
  const mark = source.split('function markNow(id) {')[1].split('function markRun(row) {')[0];
  assert.match(mark, /oldMarks\[m\] === same/);
  assert.match(mark, /oldMarks\[m\]\.classList\.remove\('sp-now'\)/);
});

test('editorial master switch only changes enabled state with revision', () => {
  assert.deepEqual(view.rejectionPolicyBody({enabled: true, revision: 7}),
    {enabled: false, expected_revision: 7});
  assert.deepEqual(view.rejectionPolicyBody({enabled: false, revision: 8}),
    {enabled: true, expected_revision: 8});
});

test('review evidence retains historical evaluation and technical state', () => {
  const evidence = view.rejectionEvidence({
    evaluation: {faults: ['voice']},
    technical: true,
    system_path: {observed: {gate: 'call_contract'}}
  });
  assert.deepEqual(evidence.map(([label]) => label),
    ['Evaluation at rejection (historical)', 'Technical flag at rejection (historical)',
      'System path at rejection (historical)']);
  assert.equal(evidence[1][1], true);
});

test('profile check shows stored/current comparison and ignored future-turn fields', () => {
  const profile = view.rejectionProfileView({
    context: {entry: {profile: 'old raw profile'}},
    profile_check: {
      compatible: false,
      stored: {voice: 'old', turns: [8, 11]},
      current: {voice: 'new', turns: [6, 6]},
      compared_fields: ['voice'], differences: ['voice'],
      ignored_fields: ['turns', 'plot'],
      impact: 'Writing-profile compatibility; audio readiness is checked separately.'
    }
  });
  assert.equal(profile.compatible, false);
  assert.equal(profile.stored.voice, 'old');
  assert.equal(profile.current.voice, 'new');
  assert.deepEqual(profile.compared, ['voice']);
  assert.deepEqual(profile.differences, ['voice']);
  assert.deepEqual(profile.ignored, ['turns', 'plot']);
  assert.match(profile.impact, /audio readiness is checked separately/);
  assert.deepEqual(view.rejectionProfileView({context: {entry: {profile: 'legacy'}}}), {
    compatible: null, stored: 'legacy', current: null,
    compared: [], differences: [], ignored: [], impact: ''
  });
});

test('current tint is separate from historical rejection evidence', () => {
  assert.match(view.rejectionTintSummary({crystals_on: 0, tint_share: 0, two_pass: false}),
    /Current tint: off for new scripts.*0 active crystals.*share 0%.*two-pass off/);
  assert.match(view.rejectionTintSummary({crystals_on: 2, tint_share: 0, two_pass: false}),
    /2 active crystal\(s\).*share 0%.*two-pass off/);
  assert.doesNotMatch(view.rejectionTintSummary({crystals_on: null, tint_share: null,
    two_pass: false}), /off for new scripts/);
  assert.match(source, /api\/tint/);
  assert.match(source, /api\/orchestrator\/logic/);
});
