const assert = require('node:assert/strict');
const {test} = require('node:test');
const view = require('../desktop/renderer/script-page.js').view;

test('sixteen scripted turns played as eighteen clips stay eighteen aired lines', () => {
  const turns = Array.from({length: 16}, (_, index) => ({
    seat: index % 2 ? 'B' : 'A',
    who: index % 2 ? 'Co-host' : 'Host',
    text: index === 4 || index === 11
      ? `Opening ${index}. Closing ${index}.` : `Line ${index}.`,
    candidate: 'take-one', candidate_index: index, performance_index: 0
  }));
  const aired = turns.flatMap((turn, index) => {
    const pieces = index === 4 || index === 11
      ? [`Opening ${index}.`, `Closing ${index}.`] : [turn.text];
    return pieces.map((text, piece) => ({
      line: `clip-${index}-${piece}`, text, kind: 'chat',
      who: turn.seat === 'A' ? 'dj' : 'cohost', at: index + piece / 10
    }));
  });
  const shown = view.itinConversationTurns({script: {turns}, aired});
  assert.equal(aired.length, 18);
  assert.equal(shown.length, 18);
  assert.ok(shown.every((turn) => turn.aired));
  assert.deepEqual(shown.map((turn) => turn.line), aired.map((row) => row.line));
  assert.match(view.itinBanked({script: {turns}}), /^16 turns banked/);
  assert.match(view.itinAired({aired}), /^18 aired feed rows/);
});

test('partial clips and unrelated seat or SFX do not consume a prepared turn', () => {
  const turn = {seat: 'A', who: 'Host',
    text: 'First sentence. Second sentence.', candidate: 'take-two',
    candidate_index: 7, performance_index: 2};
  const aired = [
    {line: 'first', text: 'First sentence.', who: 'dj', kind: 'chat'},
    {line: 'other', text: 'Second sentence.', who: 'cohost', kind: 'chat'},
    {line: 'effect', text: 'First sentence. Second sentence.', who: 'board', kind: 'sfx'},
    {line: 'marker', text: 'First sentence. Second sentence.', who: 'host', kind: 'marker'}
  ];
  const shown = view.itinConversationTurns({script: {turns: [turn]}, aired});
  assert.deepEqual(shown.slice(0, 4).map((row) => row.line),
    ['first', 'other', 'effect', 'marker']);
  assert.equal(shown.length, 5);
  assert.equal(shown[4].aired, undefined);
  assert.equal(shown[4].candidate_index, 7);
  assert.deepEqual(view.turnEditBody(shown[4], 4, 'Revision'), {
    index: 7, candidate_index: 7, performance_index: 2,
    text: 'Revision', was: turn.text, candidate: 'take-two'
  });
});

test('one aired copy cannot consume two identical scripted turns', () => {
  const turns = [0, 1].map((index) => ({seat: 'A', text: 'Station ID.',
    candidate: 'take-three', candidate_index: index}));
  const shown = view.itinConversationTurns({script: {turns}, aired: [
    {line: 'only-clip', text: 'Station ID.', who: 'dj', kind: 'chat'}
  ]});
  assert.equal(shown.length, 2);
  assert.equal(shown[0].line, 'only-clip');
  assert.equal(shown[1].candidate_index, 1);
  assert.equal(shown[1].aired, undefined);
});

test('a matching phrase from another seat and draft fragments remain visible', () => {
  const turn = {seat: 'A', text: 'Opening. Ending.', candidate_index: 3};
  const aired = [
    {line: 'wrong-seat', text: turn.text, who: 'cohost', kind: 'chat'},
    {line: 'part-one', text: 'Opening.', who: 'dj', kind: 'chat'},
    {line: 'part-two', text: 'Ending.', who: 'dj', kind: 'chat'}
  ];
  const bound = view.itinConversationTurns({script: {turns: [turn]}, aired});
  assert.equal(bound.length, 3, 'the two same-seat clips complete only the bound turn');
  const draft = view.itinConversationTurns({script: {draft_turns: [turn]},
    aired: aired.slice(1)});
  assert.equal(draft.length, 3, 'drafts are not treated as recorded allocations');
  assert.equal(draft[2].candidate_index, 3);
});

test('heard and still-planned lines stay in separate ordered sections', () => {
  const aired = [
    {line: 'actual-1', text: 'The actual opening.', who: 'dj', kind: 'chat'},
    {line: 'actual-2', text: 'The actual reply.', who: 'cohost', kind: 'chat'}
  ];
  const shown = view.itinConversationTurns({
    script: {turns: [
      {text: 'A different planned opening.', seat: 'A', candidate: 'booked'},
      {text: 'A different planned reply.', seat: 'B', candidate: 'booked'}
    ]}, aired
  });
  const sections = view.itinConversationSections(shown);
  assert.deepEqual(sections.heard.map((turn) => turn.line),
    ['actual-1', 'actual-2']);
  assert.deepEqual(sections.planned.map((turn) => turn.candidate),
    ['booked', 'booked']);
  assert.equal(sections.heard.some((turn) => turn.candidate === 'booked'), false);
});
