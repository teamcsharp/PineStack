const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const renderer = path.join(__dirname, '..', 'desktop', 'renderer');
const line = fs.readFileSync(path.join(renderer, 'console-line.js'), 'utf8');
const trace = fs.readFileSync(path.join(renderer, 'console-trace.js'), 'utf8');
const css = fs.readFileSync(path.join(renderer, 'console-trace.css'), 'utf8');
const chrome = fs.readFileSync(path.join(renderer, 'view-chrome.css'), 'utf8');
const index = fs.readFileSync(path.join(renderer, 'index.html'), 'utf8');
const viewer = fs.readFileSync(path.join(renderer, 'ad-viewer.js'), 'utf8');

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

test('the visible basebar owns the existing station controls', () => {
  assert.match(line, /pine-console-tools/);
  assert.match(line, /\['crystalBtn', 'sampleBtn', 'sbLiveBtn'\]/);
  assert.match(line, /tools\.appendChild\(control\)/);
  assert.match(line, /oldBar\.hidden = true/);
  assert.match(chrome, /\.pine-console-tools/);
  assert.match(chrome, /\.pine-console-tools > button/);
});

test('the tablet receives working basebar controls when desktop nodes are absent', () => {
  assert.match(line, /tabletControl\('crystalBtn'/);
  assert.match(line, /root\.PineViewRail\.closeAll/);
  assert.match(line, /root\.loadCrystals/);
  assert.match(line, /tabletControl\('sampleBtn'/);
  assert.match(line, /pineViewTab-sampler/);
  assert.match(line, /tabletControl\('sbLiveBtn'/);
  assert.match(line, /root\.onAirLaunch/);
});

test('the four established quick tools remain visible beside the audit readout', () => {
  assert.match(line, /pine-console-shortcuts/);
  assert.match(line, /pine-console-gallery/);
  assert.match(line, /pine-console-orchestrator/);
  assert.match(line, /pine-console-talk-dot/);
  assert.match(line, /pine-console-change/);
  assert.match(line, /PineAdViewer\.openGallery/);
  assert.match(line, /PineOrchGlass\.toggle/);
  assert.match(line, /talk\.listen\(\)/);
  assert.match(line, /PineChangeLog\.open/);
  assert.match(chrome, /\.pine-console-shortcuts > button/);
});

test('gallery shortcut owns its carousel and hourly H3 header controls', () => {
  assert.match(index, /<script src="\.\/ad-viewer\.js"><\/script>/);
  assert.match(viewer, /root\.PineAdViewer = \{open: open, openGallery:/);
  assert.match(viewer, /pav-strip/);
  assert.match(viewer, /\/api\/h3\/hourly/);
  assert.match(viewer, /pav-h3-meter/);
  assert.match(chrome, /\.pav-h3-meter/);
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
