'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/system3.js'), 'utf8');
class Node {
  constructor(tag = '') {
    this.tagName = tag; this.nodeType = 1; this.children = []; this.handlers = {};
    this.value = ''; this.checked = false; this.disabled = false; this.className = '';
  }
  set value(value) { this.inputValue = String(value); }
  get value() { return this.inputValue; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  set textContent(value) { this.words = String(value); this.children = []; }
  get textContent() { return (this.words || '') + this.children.map(x => x.textContent || '').join(''); }
  setAttribute(key, value) { this[key] = String(value); }
  addEventListener(key, fn) { (this.handlers[key] ||= []).push(fn); }
  async fire(key) { for (const fn of this.handlers[key] || []) await fn({target: this}); }
  checkValidity() {
    const n = Number(this.value);
    return Number.isFinite(n) && (this.min == null || n >= Number(this.min)) &&
      (this.max == null || n <= Number(this.max)) &&
      (Number(this.step) !== 1 || Number.isInteger(n));
  }
  reportValidity() { this.validityReported = true; }
}
function nodes(root) { return [root, ...root.children.flatMap(nodes)]; }
function byLabel(root, label) { return nodes(root).find(n => n['aria-label'] === label); }
function byButton(root, label) { return nodes(root).find(n => n.tagName === 'button' && n.textContent === label); }
const context = vm.createContext({
  document: {createElement: tag => new Node(tag), createTextNode: text => { const n = new Node(); n.textContent = text; return n; }},
  pct: x => Math.round(x * 100) + '%', json: x => JSON.stringify(x, null, 2),
  eventLine: ev => ({text: ev.selected.label, dice: ev.rng && ev.rng.dice}),
  Set, Number, Array, JSON
});
vm.runInContext(source.slice(source.indexOf('function el('), source.indexOf('/* --- reading recorded events')), context);
vm.runInContext(source.slice(source.indexOf('function turnEvents('), source.indexOf('function replyCaption(')), context);
vm.runInContext(source.slice(source.indexOf('function kv('), source.indexOf('function stageStory(')), context);
const policy = context.handoffPolicyEditor, receipt = context.handoffReceipt, data = context.handoffReceiptData;
const fixture = () => {
  const events = ['threshold', 'checkpoint', 'speaker', 'mode'].map((kind, index) => ({
    event_id: kind, family: 'HANDOFF', selected: {label: kind + ' result'}, rng: {dice: 41 + index},
    meta: {kind}, stages: [{stage: kind}]
  }));
  const turn = {turn_id: 'T', speaker: 'dj', decisions: events.map(e => ({event_id: e.event_id})),
    length_trace: {original_chars: 1200, final_chars: 302, threshold: 250, hard_chars: 800,
      threshold_event: 'threshold', status: 'handoff', dropped_chars: 898, dropped_text: 'Unused tail.',
      protected: '', receipt: {draft_chars: 900, source_changes: [{stage: 'append', provenance: 'exact',
        file: 'passage.txt', before_chars: 900, inserted_chars: 300, after_chars: 1200,
        source_chars: 1500, retained_excerpt_chars: 300, cap: 300}]},
      checkpoints: [{offset: 302, event_id: 'checkpoint', outcome: 'HANDOFF', forced: false}],
      insertions: [{turn_id: 'CHILD', speaker: 'cohost', speaker_event: 'speaker', mode_event: 'mode',
        mode: 'respond', status: 'written', attempts: [{attempt: 1, chars: 880, kept_chars: 0, rejection: 'over cap'}]}]
    }};
  return {turns: [turn], decision_events: events, turn};
};
test('old recordings keep unavailable draft and source provenance', () => {
  const turn = {turn_id: 'old', text: 'A long original recording.', decisions: []};
  const got = receipt({turns: [turn], decision_events: []}, turn, () => {});
  assert.match(got.textContent, /draft length, source changes and reason for staying whole are unavailable/);
  assert.match(got.textContent, /later replay does not establish/);
  assert.equal(data({turns: [turn]}, turn).draftChars, null);
});
test('receipt uses captured draft separately from the before-handoff body', () => {
  const conv = fixture(), got = receipt(conv, conv.turn, () => {});
  assert.match(got.textContent, /Draft characters900/);
  assert.match(got.textContent, /Before handoff1200/);
  assert.match(got.textContent, /Final characters302/);
  assert.match(got.textContent, /Full source1500/);
  assert.match(got.textContent, /Retained excerpt300/);
  assert.match(got.textContent, /Dropped tail898 characters/);
  assert.match(got.textContent, /Writer attempt 1: 880 characters; 0 kept - over cap/);
});
test('every recorded threshold, sentence boundary, speaker and mode links to its actual event', async () => {
  const conv = fixture(), clicked = [], got = receipt(conv, conv.turn, ev => clicked.push(ev));
  assert.equal(data(conv, conv.turn).events.length, 4);
  for (const kind of ['threshold', 'checkpoint', 'speaker', 'mode']) {
    const button = nodes(got).find(n => n.tagName === 'button' && n.title === kind);
    assert.ok(button, kind); await button.fire('click');
  }
  assert.deepEqual(clicked, conv.decision_events);
});
test('child receipt traces its parent without attributing parent lengths to the child', () => {
  const conv = fixture();
  const child = {turn_id: 'CHILD', handoff_parent: 'T', handoff: {mode: 'respond', speaker_event: 'speaker'}, decisions: []};
  conv.turns.push(child);
  const got = receipt(conv, child, () => {});
  assert.match(got.textContent, /receipt below belongs to that original turn/);
  assert.equal(data(conv, child).trace, conv.turn.length_trace);
  assert.equal(data(conv, child).events.length, 4);
});
test('missing source mutation proof stays unknown and exemptions/skip reasons remain visible', () => {
  const conv = fixture(), trace = conv.turn.length_trace;
  delete trace.receipt.draft_chars;
  trace.status = 'protected'; trace.why = 'operator authored'; trace.protected = 'exact words';
  trace.receipt.source_changes = [{stage: 'prepend', inserted_chars: 600}];
  const got = receipt(conv, conv.turn, () => {});
  assert.match(got.textContent, /Draft charactersunavailable/);
  assert.match(got.textContent, /prepend - unknown/);
  assert.match(got.textContent, /Whyoperator authored/);
  assert.match(got.textContent, /Exemptionexact words/);
});
test('policy editor saves probability contract, thresholds and bounded limits without altering current config', async () => {
  const current = {respond_probability: 0.6, hard_chars: 900, future_flag: true};
  let saved;
  const form = policy(current, async next => { saved = next; });
  assert.equal(byLabel(form, 'Handoff thresholds in characters').value, '250, 350, 450, 550');
  byLabel(form, 'continue probability').value = '0.3';
  byLabel(form, 'respond probability').value = '0.75';
  byLabel(form, 'Handoff thresholds in characters').value = '300, 400';
  byLabel(form, 'hard chars').value = '800';
  await byButton(form, 'Save handoff policy').fire('click');
  assert.deepEqual(JSON.parse(JSON.stringify(saved)), {enabled: true, thresholds: [300, 400],
    continue_probability: 0.3, respond_probability: 0.75, hard_chars: 800,
    max_extra_turns: 3, writer_retries: 2, future_flag: true});
  assert.equal(current.hard_chars, 900);
  assert.match(form.textContent, /Saved. Future rounds/);
});
test('invalid thresholds and out-of-range probability do not invoke save', async () => {
  let count = 0;
  const form = policy({}, async () => count++);
  const thresholds = byLabel(form, 'Handoff thresholds in characters'), save = byButton(form, 'Save handoff policy');
  thresholds.value = '250, 250'; await save.fire('click');
  assert.equal(count, 0); assert.match(form.textContent, /distinct whole character counts/);
  thresholds.value = '250, 350'; byLabel(form, 'continue probability').value = '1.2';
  await save.fire('click'); assert.equal(count, 0);
  assert.match(form.textContent, /numeric limits/);
});
test('receipt is wired into focused message, prompt, and line story; config section is editable', () => {
  assert.equal((source.match(/sectionOf\('Length and handoffs'/g) || []).length, 2);
  assert.match(source, /station\('7a', 'Length and handoffs'/);
  assert.match(source, /handoffPolicyEditor\(live\(\)\.handoff/);
  assert.match(source, /config\/section\/handoff/);
});

test('measured round assembly is not mislabeled as this turn\'s draft or insertion', () => {
  const conv = fixture(), trace = conv.turn.length_trace;
  trace.draft_chars = 9999;
  trace.assembly = {scope: 'round', provenance: 'measured', stages: [
    {stage: 'writer draft', spoken_chars: 1700, turns: [{speaker: 'dj', chars: 900}, {speaker: 'cohost', chars: 800}]},
    {stage: 'source door: append', spoken_chars: 2000, added_chars: 300,
      turns: [{speaker: 'dj', chars: 1200}, {speaker: 'cohost', chars: 800}]}
  ]};
  trace.source_changes = [{stage: 'source door: append', scope: 'round', provenance: 'measured',
    before_chars: 1700, after_chars: 2000, added_chars: 300,
    source: {file: 'passage.txt', source_chars: 1500, retained_excerpt_chars: 300}}];
  const got = receipt(conv, conv.turn, () => {});
  assert.match(got.textContent, /Assembly stages \(whole round\)/);
  assert.match(got.textContent, /Draft charactersunavailable/);
  assert.match(got.textContent, /Net change in round300/);
  assert.match(got.textContent, /Full source1500/);
  assert.match(got.textContent, /Retained excerpt300/);
  assert.doesNotMatch(got.textContent, /\[object Object\]/);
});
test('engine receipt event supplies exact skip reason and exemption reason is retained', () => {
  const conv = fixture(), trace = conv.turn.length_trace;
  const event = {event_id: 'receipt', family: 'HANDOFF', meta: {kind: 'length receipt', why: 'no other speaker eligible'}, selected: {label: 'no other speaker eligible'}};
  conv.decision_events.push(event); trace.receipt = 'receipt';
  trace.exemption_reason = 'caller voice cannot be assigned to a studio reader';
  const got = receipt(conv, conv.turn, () => {});
  assert.match(got.textContent, /Whyno other speaker eligible/);
  assert.match(got.textContent, /Exemptioncaller voice cannot be assigned to a studio reader/);
  assert.ok(data(conv, conv.turn).events.includes(event));
});
test('policy rejects a threshold over the cap and engine-invalid limits', async () => {
  let count = 0;
  const form = policy({}, async () => count++);
  byLabel(form, 'hard chars').value = '300';
  await byButton(form, 'Save handoff policy').fire('click');
  assert.equal(count, 0); assert.match(form.textContent, /must not exceed/);
  byLabel(form, 'hard chars').value = '800';
  byLabel(form, 'writer retries').value = '4';
  await byButton(form, 'Save handoff policy').fire('click'); assert.equal(count, 0);
});

test('recorded before and after bodies and following-turn rewrite remain inspectable', () => {
  const conv = fixture();
  Object.assign(conv.turn.length_trace, {policy_hash: 'policy123', original_text: 'Original draft body.', final_text: 'Final body.', reanchor: {target_turn_id: 'NEXT', original_text: 'Old answer.', final_text: 'Answering the new handoff.'}});
  const got = receipt(conv, conv.turn, () => {});
  assert.match(got.textContent, /Recorded policypolicy123/);
  assert.match(got.textContent, /The recorded body before handoffOriginal draft body/);
  assert.match(got.textContent, /The recorded body after handoffFinal body/);
  assert.match(got.textContent, /Following turn rewritten to answer the handoff/);
  assert.match(got.textContent, /Answering the new handoff/);
});
