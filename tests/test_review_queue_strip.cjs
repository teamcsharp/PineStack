/* [review-queue] 2026-09-28: the desk's review strip is still, shows each
   open item once, and every item can be closed from the pane and the queue.

   "I don't know why these are scrolling at the top of the screen anymore.
    When I tap them, there's not options to fix them or resolve them or mark
    them as complete or to get rid of them. So they just scroll forever." */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync, existsSync} = require('node:fs');
const {join} = require('node:path');

const DESKTOP = join(__dirname, '../desktop/renderer/script-page.js');
const TABLET = join(__dirname, '../app/src/main/assets/pine-views/script-page.js');
const view = require(DESKTOP).view;
const source = readFileSync(DESKTOP, 'utf8');

function region(text) {
  return text.split('  function rejectionMarker(item) {')[1].split('  function buildRejectionStrip() {')[0];
}

test('nothing in the strip moves it: no marquee, no recycled first page', () => {
  const strip = region(source);
  assert.doesNotMatch(strip, /scrollLeft\s*(\+|-)?=/, 'no code writes the strip\'s scroll position');
  assert.doesNotMatch(strip, /rejectionItems\s*=\s*rejectionFirstPage/, 'the first page is never replayed');
  assert.doesNotMatch(strip, /requestAnimationFrame|setInterval/);
  const step = source.split('  function rejectionStep() {')[1].split('\n  }\n')[0];
  assert.doesNotMatch(step, /scrollLeft/);
  assert.match(step, /width === reviewFitWidth/, 'a tick only re-fits when the width changed');
});

test('each open item is shown once, with a +N tile for the rest', () => {
  assert.deepEqual(view.reviewUnique([{id: 'a'}, {id: 'a'}, {id: 'b'}, {}, null, {id: 3}]).map((i) => String(i.id)),
    ['a', 'b', '3']);
  assert.deepEqual(view.reviewFit(1, 1, 600), {shown: 1, extra: 0}, 'one item is one tile, not eight');
  assert.deepEqual(view.reviewFit(40, 24, 200), {shown: 4, extra: 36}, 'five slots: four tiles and +36');
  assert.deepEqual(view.reviewFit(3, 3, 0), {shown: 3, extra: 0}, 'an unmeasured strip shows what it has');
  assert.deepEqual(view.reviewFit(0, 0, 600), {shown: 0, extra: 0});
});

test('tiles and controls are Carbon icons, never emoji', () => {
  assert.equal(view.reviewIconName({gate: 'timing'}), 'c:timer');
  assert.equal(view.reviewIconName({gate: 'call_contract'}), 'c:phone');
  assert.equal(view.reviewIconName({gate: 'nothing-known', kind: 'news'}), 'c:notebook');
  const block = source.split('THE REVIEW QUEUE, 2026-09-28.')[1].split('[review-queue] end')[0];
  const names = block.match(/'c:[a-z0-9-]+'/g) || [];
  assert.ok(names.length >= 15);
  assert.doesNotMatch(block, /\p{Extended_Pictographic}/u, 'no emoji anywhere in the new code');
  const vendored = readFileSync(join(__dirname, '../desktop/renderer/pine-icons.js'), 'utf8');
  for (const name of new Set(names)) {
    assert.ok(vendored.includes('"' + name.slice(1, -1) + '"'), name + ' is a vendored Carbon icon');
  }
});

test('ages read the way a person says them', () => {
  assert.equal(view.reviewAgeText(40), '40 s');
  assert.equal(view.reviewAgeText(600), '10 min');
  assert.equal(view.reviewAgeText(27.6 * 3600), '27.6 h');
  assert.equal(view.reviewAgeText(9 * 86400), '9 days');
});

test('the pane says what a close did, and how a closed item was closed', () => {
  assert.equal(view.reviewActSaid('note', {}), 'Note saved');
  assert.match(view.reviewActSaid('dismiss', {changed: true}), /^Dismissed - it left the strip/);
  assert.match(view.reviewActSaid('resolve', {changed: true}), /^Marked complete/);
  assert.equal(view.reviewActSaid('dismiss', {changed: false, say: 'Already closed - it is noted.'}),
    'Already closed - it is noted.');
  assert.equal(view.reviewActSaid('allow', {effect: {say: 'Approved words are queued.'}}), 'Approved words are queued.');
  const at = Date.UTC(2026, 8, 28, 9, 0, 0) / 1000;
  const dismissed = view.reviewClosedText({review_status: 'noted'},
    {status: 'dismissed', by: 'operator', at: at, say: 'Dismissed by the operator'});
  assert.match(dismissed, /^Dismissed by the operator on /);
  assert.equal((dismissed.match(/Dismissed/g) || []).length, 1, 'the effect\'s own words are not said twice');
  assert.match(view.reviewClosedText({review_status: 'noted'}, {status: 'round_gone', by: 'station',
    say: 'the round this line belonged to has aired'}), /^Closed by the station: .*\. the round this line/);
  assert.match(view.reviewClosedText({read_only: true}, null), /newer one is open/);
});

test('the pane opens on its ways out; review all opens the queue', () => {
  const render = source.split('  function rejectionRender() {')[1].split('  function rejectionFetch() {')[0];
  const head = render.indexOf('overlay.appendChild(reviewActionBar(record))');
  assert.ok(head > 0 && head < render.indexOf('var scroll = make('), 'the action bar sits above the scroll');
  assert.match(render, /scroll\.appendChild\(reviewS3Section\(record\)\)/);
  assert.match(render, /scroll\.appendChild\(reviewWhatSection\(record\)\)/);
  assert.match(source, /function rejectionControlsOpen\(\) \{\n\s+reviewQueueOpen\(\);/);
  assert.match(source, /'\/api\/orchestrator\/rejections\/bulk-close'/);
  assert.match(source, /'\/api\/orchestrator\/rejections\/queue\?limit=200'/);
  assert.match(source, /'\/api\/orchestrator\/rejections\/history\?limit=80'/);
  assert.match(source, /mod\.mountLineStory\(node, \{request: s3Request/, 'System 3 draws the turn\'s own story');
});

test('BACK closes the review overlay through window.pineBack (#1450c)', () => {
  const block = source.split('THE REVIEW QUEUE, 2026-09-28.')[1].split('[review-queue] end')[0];
  assert.match(block, /dismiss\.onBack\(function \(\) \{/);
  assert.match(block, /return \{node: overlay, close: reviewBack\}/);
  assert.match(block, /rejectionSelection\.fromQueue\) \{ reviewQueueOpen\(\); return; \}/,
    'a pane opened from the queue goes back to the queue');
  const bar = block.split('function reviewActionBar(record) {')[1];
  assert.match(bar.slice(0, 80), /reviewBackWire\(\);/, 'wired when a pane is drawn, whatever the load order');
});

test('the tablet copy carries the same strip and pane', {skip: !existsSync(TABLET)}, () => {
  const tablet = readFileSync(TABLET, 'utf8');
  for (const needle of ['function reviewQueueOpen()', 'function reviewS3Section(record)',
    'overlay.appendChild(reviewActionBar(record))', 'width === reviewFitWidth']) {
    assert.ok(tablet.includes(needle), needle);
  }
  assert.doesNotMatch(region(tablet), /scrollLeft\s*(\+|-)?=/);
});

test('the pane imports System 3 under the newest version the page already uses', () => {
  for (const file of [DESKTOP, TABLET].filter((f) => existsSync(f))) {
    const text = readFileSync(file, 'utf8');
    const used = (text.match(/system3\.js\?v=(\d+)/g) || []).map((m) => Number(m.split('=')[1]));
    const mine = /var REVIEW_S3_VERSION = '(\d+)';/.exec(text);
    assert.ok(mine, file);
    assert.equal(Number(mine[1]), Math.max(...used), file);
    assert.match(text, /import\(techUrl\('\/system3\/system3\.js\?v=' \+ REVIEW_S3_VERSION\)\)/);
  }
});
