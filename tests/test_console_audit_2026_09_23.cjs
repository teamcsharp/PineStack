const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const renderer = path.join(__dirname, '..', 'desktop', 'renderer');
const line = fs.readFileSync(path.join(renderer, 'console-line.js'), 'utf8');
const trace = fs.readFileSync(path.join(renderer, 'console-trace.js'), 'utf8');
const css = fs.readFileSync(path.join(renderer, 'console-trace.css'), 'utf8');
const chrome = fs.readFileSync(path.join(renderer, 'view-chrome.css'), 'utf8');

test('repeated full activity snapshots do not churn the retained audit window', () => {
  const vm = require('node:vm');
  const code = line.slice(line.indexOf('  function keyOf('), line.indexOf('  function icon('));
  const h = vm.runInNewContext('var seen = [], keys = Object.create(null), SEEN_MAX = 300;'
    + code + '\n({remember, history})');
  const rows = Array.from({length: 600}, (_, i) => ({at: i + 1, stage: 'voice', detail: 'line ' + i}));
  rows.forEach(h.remember);
  assert.equal(h.history().length, 300);
  assert.equal(rows.filter(h.remember).length, 0);
  assert.equal(h.remember({id: 1, at: 601, stage: 'flow'}), true);
  assert.equal(rows.filter(h.remember).length, 0);
  assert.equal(h.history()[0].id, 1);
});

test('the marquee follows the durable journal incrementally and retains 300 events', () => {
  assert.match(line, /var SEEN_MAX = 300/);
  assert.match(line, /\/api\/dj\/flow\?lean=1&limit=/);
  assert.match(line, /&after=/);
  assert.match(line, /FLOW_POLL_MS = 2500/);
  assert.match(line, /seen\.slice\(-24\)/);
  assert.match(chrome, /animation: pineConsoleMarquee/);
  assert.match(line, /animationiteration/);
  assert.match(line, /pendingMarqueeRows/);
  assert.doesNotMatch(line, /classList\.remove\('running'\)/);
  assert.match(chrome, /translate3d\(-50%, 0, 0\)/);
});

test('a horizontal swipe changes and remembers marquee playback speed', () => {
  assert.match(line, /pineConsoleMarqueeSpeed/);
  assert.match(line, /viewport\.addEventListener\('pointermove'/);
  assert.match(line, /updatePlaybackRate\(speed\)/);
  assert.match(line, /Math\.exp\(-dx \/ width \* 2\.2\)/);
  assert.match(chrome, /touch-action: pan-y/);
});

test('each moving event and terminal row opens the granular trace', () => {
  assert.match(line, /pine-console-audit/);
  assert.match(chrome, /\.pine-console-audit/);
  assert.match(chrome, /flex: 0 1 50%/);
  assert.match(line, /closest\('\.pine-console-entry'\)/);
  assert.match(line, /PineConsoleTrace\.open\(entry\.__row\)/);
  assert.match(line, /history\(\)\.slice\(0, SEEN_MAX\)/);
  assert.match(trace, /this exact journal event/);
  assert.match(trace, /JSON\.stringify\(openFor\._flow, null, 2\)/);
});

test('the terminal and detail view are draggable dialogs above page video', () => {
  assert.match(line, /data-pine-drag/);
  assert.match(line, /pine-console-list-head.*data-pine-drag-handle/);
  assert.match(trace, /box\.setAttribute\('data-pine-drag', ''\)/);
  assert.match(css, /\.pine-console-list-head[\s\S]*touch-action: none/);
});

test('action events expose the actual questions and the orchestrator decision', () => {
  assert.match(trace, /\/api\/retire\/questions\?most=50/);
  assert.match(trace, /\/api\/retire\/decide-model/);
  assert.match(trace, /Let the orchestrator decide/);
  assert.match(trace, /asked_because/);
  assert.match(css, /\.ct-decision-list/);
});
