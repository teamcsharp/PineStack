const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('multi-option message roulettes display the earned turn on the winning reel', () => {
  const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/script-page.js'), 'utf8');
  const start = source.indexOf('  function mvDecisionRow(');
  const end = source.indexOf('\n  function ', start + 1);
  const context = {mvStageOf: (ev, name) => ev.stages.find(s => s.stage === name),
    mvRrFailed: () => [], mvRrVerdicts: () => [],
    mvReel: (s, dice) => ({dice, opts: s.candidates.map(c => c.label),
      hit: s.candidates.findIndex(c => c.id === s.selected),
      label: s.candidates.find(c => c.id === s.selected).label})};
  vm.createContext(context); vm.runInContext(source.slice(start, end), context);
  const ev = {family:'GRAPH', event_id:'reply', selected:{id:'last',label:'Skip',table:'Reply target'},
    meta:{kind:'Reply target',turn_credit:1}, stages:[{stage:'reply_target',selected:'last',
      draw:{dice:64},candidates:[{id:'initiator',label:'Host'},{id:'last',label:'Skip'}]}]};
  const row = context.mvDecisionRow(ev);
  assert.equal(row.main.dice, 64);
  assert.equal(row.table, 'Reply target');
  assert.equal(row.main.label, 'Skip · +1 turn restored');
  assert.equal(row.main.opts[row.main.hit], row.main.label);
  assert.equal(ev.stages[0].candidates[1].label, 'Skip');
});
