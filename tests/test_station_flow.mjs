import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

// Browser module has no top-level DOM effects, so the event-contract tests
// execute the production helpers without a browser or a synthetic station.
const source = await readFile(new URL('../frontend/station-flow.js', import.meta.url), 'utf8');
const flow = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const events = [
  {id:41, at:1, node:'draft', status:'ok', trace_id:'call-7', summary:'Caller draft', details:{source:'speakerbox fragment'}},
  {id:42, at:2, node:'conversation', status:'fail', trace_id:'call-7', parent_id:41, summary:'Missing ending', details:{faults:['no farewell']}},
  {id:43, at:3, node:'repair', status:'start', trace_id:'call-7', from:'conversation', summary:'Repair ending'},
];
const edges = [
  {id:'draft-review',from:'draft',to:'conversation'},
  {id:'review-repair',from:'conversation',to:'repair',feedback:true},
];

test('overlapping journal pages retain details, deduplicate and order by cursor',()=>{
  const merged=flow.mergeFlowEvents(events.slice(1),[events[0],events[1]]);
  assert.deepEqual(merged.map(row=>row.id),[41,42,43]);
  assert.equal(merged[1].details.faults[0],'no farewell');
});
test('a server session change cannot conflate reused event identifiers',()=>{
  const replacement={id:41,node:'received',status:'received'};
  assert.deepEqual(flow.mergeFlowEvents(events,[replacement],true),[replacement]);
});
test('malformed cursors do not enter the event journal',()=>{
  assert.deepEqual(flow.mergeFlowEvents([],[{id:null},{id:'oops'},{id:-1},{id:0}]),[]);
});
test('temporal proximity alone never fabricates an animated handoff',()=>{
  assert.equal(flow.flowEventEdge({id:44,node:'conversation'},events,edges),null);
  assert.equal(flow.flowEventEdge({id:44,node:'playing',from:'draft'},events,edges),null);
});
test('explicit parents and source steps resolve their actual graph edges',()=>{
  assert.equal(flow.flowEventEdge(events[1],events,edges).id,'draft-review');
  assert.equal(flow.flowEventEdge(events[2],events,edges).id,'review-repair');
});
test('trace filtering preserves the full call and searches nested evidence',()=>{
  assert.equal(flow.filterFlowEvents(events,'','CALL-7').length,3);
  assert.deepEqual(flow.filterFlowEvents(events,'conversation','farewell').map(row=>row.id),[42]);
  assert.equal(flow.filterFlowEvents(events,'draft','farewell').length,0);
});
test('all 23 pipeline steps have distinct coordinates, including paper and feedback',()=>{
  const ids='schedule speakerbox pivots draft conversation crystal rewrite tint_judge repair tts pantry publish received canplay playing ended error watchdog reflection repeat gazette paper_tint edition'.split(' ');
  const points=ids.map(id=>JSON.stringify(flow.flowNodePosition(id)));
  assert.equal(new Set(points).size,23);
});
test('late-added backend nodes get a usable separate layout position',()=>{
  const at=flow.flowNodePosition('new-stage',26);
  assert.equal(Number.isFinite(at.x)&&Number.isFinite(at.y),true);
  assert.ok(at.y < flow.flowNodePosition('watchdog').y);
});
