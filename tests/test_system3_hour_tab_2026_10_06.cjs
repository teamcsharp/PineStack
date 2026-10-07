// [hour-tab] wave I - the System 3 window's Hour tab (2026-10-06).
// Static proof, no browser: the module parses, the tab is declared and routed, the parts are there, the text is ASCII,
// the window never takes the scroll, every icon-only button has its tooltip, the engine switch asks first, and the
// desk and the ?v= lines are in place.
// Run:  node --test tests/test_system3_hour_tab_2026_10_06.cjs
// S3_ROOT (env) names the spark-agent root to test; it defaults to the root above this tests folder.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = process.env.S3_ROOT || path.resolve(__dirname, '..');
const read = rel => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const js = read('frontend/system3.js');
const css = read('frontend/system3.css');
const renderer = read('desktop/renderer/renderer.js');
const scriptPage = read('desktop/renderer/script-page.js');

function span(text, start, end) {
  const i = text.indexOf(start);
  assert.ok(i >= 0, 'missing block start: ' + start);
  const j = text.indexOf(end, i);
  assert.ok(j > i, 'missing block end: ' + end);
  return text.slice(i, j + end.length);
}
const hourJs = span(js, '/* [hour-tab] THE HOUR AS A ROAD', '/* [hour-tab-end] */');
const hourCss = span(css, '/* [hour-tab] the Hour tab', '/* [hour-tab-end] */');
const count = (text, needle) => text.split(needle).length - 1;

test('system3.js parses (module syntax stripped for vm)', () => {
  const src = js
    .replace(/^import [^\n]*\n/gm, '')
    .replace(/^export (async )?/gm, '$1')
    .replace(/import\.meta/g, '({})');
  assert.doesNotThrow(() => new vm.Script(src, {filename: 'system3.js'}));
});

test('the Hour block parses on its own', () => {
  assert.doesNotThrow(() => new vm.Script(hourJs, {filename: 'hour-tab.js'}));
});

test('the Hour tab is declared in the tab row and routed by the window', () => {
  assert.match(js, /\['hour', 'Hour'\], \['director', 'Director'\]/);
  assert.equal(count(js, "else if (tab === 'hour') hourTab.show(body);"), 1);
  assert.equal(count(js, 'const hourTab = makeHourTab({'), 1);
  assert.equal(count(js, 'hourTab.stop();'), 1);
  assert.match(js, /openTable: id => \{ stopExtras\(\); listId = ''; tableId = id; draft = null; tab = 'tables'; paint\(\); \}/);
});

test('the parts are there: the road, the node controls, the dice, the ledger, the engine', () => {
  for (const fn of ['makeHourTab', 'hourButton', 'hourIcon', 'road', 'insertForm', 'entryNode', 'ledgerView',
    'modal', 'engineBar', 'hourPicker', 'diceBar', 'askEngine', 'writeSlots', 'setMinutes', 'setEnabled', 'move',
    'removeAt', 'insertAfter', 'saveInstruction', 'openInner', 'show']) {
    assert.ok(hourJs.includes('function ' + fn + '('), 'missing function ' + fn);
  }
  for (const endpoint of ['/api/schedule/hours?count=6', '/api/system3/engine', '/api/system3/hour?hour=',
    '/api/schedule/kinds', "'/api/schedule/hours', ", "'/api/schedule/hours/' + encodeURIComponent(state.key) + '/prompt'"]) {
    assert.ok(hourJs.includes(endpoint), 'missing endpoint ' + endpoint);
  }
  for (const dice of ['HOUR1', 'HOUR2', 'HOUR3']) assert.ok(hourJs.includes("'" + dice + "'"), 'missing ' + dice);
  for (const engine of ["'legacy'", "'system2'", "'system3'"]) assert.ok(hourJs.includes(engine), 'missing ' + engine);
  assert.ok(hourJs.includes('window.PineHourFlow'), 'inner shape must open PineHourFlow');
  assert.ok(hourJs.includes('open the hour-flow editor on the desk'), 'missing the desk fallback message');
  assert.ok(hourJs.includes('Inner shape'), 'missing the inner shape button');
  assert.ok(hourJs.includes('The Hour Director is not on this station yet.'), 'missing the director-off line');
  assert.ok(hourJs.includes("'on air'") && hourJs.includes('s3-hour-chip dyn'), 'missing on-air lit leg or dynamic chip');
  assert.ok(hourJs.includes('Book Time window') && hourJs.includes('Station supercut window'), 'missing dynamic chips');
  assert.ok(hourCss.includes('.s3-hour-node.inner { border-style: dashed; }'), 'the inner-shape node must be dashed');
  assert.ok(hourJs.includes('nothing booked for this leg yet') && hourJs.includes('why: '), 'missing booked or why lines');
});

test('the text is ASCII in the new blocks', () => {
  assert.doesNotMatch(hourJs, /[^\x00-\x7f]/);
  assert.doesNotMatch(hourCss, /[^\x00-\x7f]/);
  const added = renderer.split('\n').filter(l => /hour-tab|Hour tab|pine:system3-open/.test(l));
  const addedPage = scriptPage.split('\n').filter(l => /hour-tab|pine:system3-open/.test(l));
  for (const line of added.concat(addedPage)) assert.doesNotMatch(line, /[^\x00-\x7f]/, line);
});

test('no scroll takeover: a repaint only restores the reader\'s place', () => {
  assert.doesNotMatch(hourJs, /scrollIntoView|scrollTo\(|scrollBy|\.scroll\(\{/);
  assert.match(hourJs, /const top = box \? box\.scrollTop : 0;/);
  assert.match(hourJs, /if \(box && box\.scrollTop !== top\) box\.scrollTop = top;/);
  assert.match(hourJs, /if \(!alive \|\| !active\(\) \|\| document\.hidden \|\| busy\(\) \|\| editing\(\)\) return;/);
  assert.match(js, /scroll: \(\) => scrollBox\(\), busy: \(\) => reading\(\)/);
});

test('every popup has a top-right X and every icon-only button a tooltip', () => {
  assert.match(hourJs, /hourButton\('', \(\) => close\(true\), \{cls: 's3-hour-x', icon: 'c:close--filled', title: 'Close'\}\)/);
  assert.match(hourJs, /class: 's3-hour-mhead'/);
  assert.match(hourJs, /'aria-label': o\.title \|\| text \|\| 'button'/);
  let at = -1, checked = 0;
  while ((at = hourJs.indexOf("hourButton('',", at + 1)) >= 0) {
    const call = hourJs.slice(at, hourJs.indexOf('\n', at) + 1);
    assert.match(call, /title: /, 'icon-only button without a tooltip: ' + call.trim());
    checked++;
  }
  assert.ok(checked >= 5, 'expected the icon-only node buttons, found ' + checked);
});

test('the engine switch asks first: the only POST is inside the confirm', () => {
  const posts = count(hourJs, "post('/api/system3/engine'");
  assert.equal(posts, 1, 'the engine may be posted from one place only');
  const ask = span(hourJs, 'function askEngine(', '    return m;\n  }');
  assert.ok(ask.indexOf("modal('Switch the engine?'") >= 0, 'askEngine must open the confirm');
  assert.ok(ask.indexOf("modal('Switch the engine?'") < ask.indexOf("post('/api/system3/engine'"),
    'the POST must come from the confirm button, after the modal');
  assert.match(hourJs, /onchange: e => askEngine\(cur, e\.target\.checked\)/, 'the fallback box asks too');
  assert.match(hourJs, /hourButton\('Cancel', \(\) => m\.dismiss\(\)/, 'the confirm has a cancel');
});

test('the css block is balanced and styles the road, the nodes and the phone width', () => {
  assert.equal(count(hourCss, '{'), count(hourCss, '}'), 'unbalanced braces');
  for (const sel of ['.s3-hour-road', '.s3-hour-node.inner', '.s3-hour-node.on-air', '.s3-hour-modal', '@media (max-width: 560px)']) {
    assert.ok(hourCss.includes(sel), 'missing css ' + sel);
  }
});

test('the desk: worksSchedule says where the sheet is edited and opens the Hour tab', () => {
  assert.ok(renderer.includes("Edited in the System 3 window's Hour tab now."), 'missing the line');
  assert.ok(renderer.includes('window.dispatchEvent(new CustomEvent("pine:system3-open", {detail: {tab: "hour"}}))'));
  assert.ok(scriptPage.includes("root.addEventListener('pine:system3-open', function (event) {"), 'the window must listen');
  assert.ok(scriptPage.includes("s3Window((event && event.detail && event.detail.tab) || 'tables');"));
});

test('the ?v= lines are bumped where the window script and styles load', () => {
  assert.equal(count(scriptPage, "system3.js?v=10'"), 5, 'four window openers and the embedded panel');
  assert.equal(count(scriptPage, "system3.css?v=8'"), 5, 'five style loads');
  assert.equal(count(scriptPage, "system3.js?v=9'"), 0, 'a stale module version is left');
  assert.equal(count(scriptPage, "system3.css?v=7'"), 0, 'a stale style version is left');
});
