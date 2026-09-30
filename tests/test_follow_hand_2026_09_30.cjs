// [follow-hand] "Unless I scroll away from the latest entry, always bring up the
// latest entry into feed." Only a hand may leave the latest; a scroll nobody made
// (trim, anchoring, a card growing) keeps the follow and returns to the bottom.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
const kiosk = path.join(root, 'app/src/main/assets/pine-views/script-page.js');
if (fs.existsSync(kiosk)) assert.strictEqual(fs.readFileSync(kiosk, 'utf8'), src, 'the kiosk copy is the renderer, byte for byte');

const grab = name => {
  const m = src.match(new RegExp('\\n  function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n'));
  assert(m, 'missing ' + name);
  return m[0];
};
const hand = src.match(/var MV_HAND_MS = \d+;/);
assert(hand, 'MV_HAND_MS is declared');

function harness() {
  const on = {};
  const stage = {
    scrollTop: 0, clientHeight: 273, scrollHeight: 1000,
    classList: {add() {}, contains: () => true},
    addEventListener(n, fn) { (on[n] = on[n] || []).push(fn); },
    fire(n) { (on[n] || []).forEach(fn => fn()); },
  };
  const pane = {appendChild() {}};
  const make = () => ({hidden: false, textContent: '', title: '', setAttribute() {}, appendChild() {}, addEventListener() {}});
  const mv = {};
  let now = 100000;
  const body = hand[0] + grab('mvAtLatest') + grab('mvChipPaint') + grab('mvHistoryWire') + 'return {mvHistoryWire};';
  // eslint-disable-next-line no-new-func
  const fns = new Function('mv', 'make', 'mvGlyph', 'mvHistoryMore', 'Date', body)(
    mv, make, () => ({}), () => {}, {now: () => now});
  fns.mvHistoryWire(pane, stage);
  stage.scrollTop = stage.scrollHeight - stage.clientHeight;   // at the latest
  return {stage, mv, tick: ms => { now += ms; }};
}

// 1. following; the list grows 358 px and a scroll event arrives that nobody made
{
  const h = harness();
  h.tick(5000);
  h.stage.scrollHeight += 358;           // the newest card grew / a card was appended
  h.stage.fire('scroll');                // trim, anchoring or a late follow scroll
  assert.strictEqual(h.mv.follow, true, 'no hand: the follow stays on');
  assert.strictEqual(h.stage.scrollTop, h.stage.scrollHeight, 'and the view returns to the latest');
}

// 2. a hand scrolls up: the follow ends and the page never moves again on its own
{
  const h = harness();
  h.tick(5000);
  h.stage.fire('touchstart');
  h.stage.scrollTop -= 500;
  h.stage.fire('scroll');
  assert.strictEqual(h.mv.follow, false, 'a hand left the latest');
  const at = h.stage.scrollTop;
  h.tick(60000);
  h.stage.scrollHeight += 400;
  h.stage.fire('scroll');                // content changes much later
  assert.strictEqual(h.mv.follow, false, 'no timed re-follow');
  assert.strictEqual(h.stage.scrollTop, at, 'the page does not move for them');
}

// 3. scrolling back to the bottom resumes the follow
{
  const h = harness();
  h.stage.fire('wheel');
  h.stage.scrollTop -= 300;
  h.stage.fire('scroll');
  assert.strictEqual(h.mv.follow, false);
  h.stage.fire('wheel');
  h.stage.scrollTop = h.stage.scrollHeight - h.stage.clientHeight;
  h.stage.fire('scroll');
  assert.strictEqual(h.mv.follow, true, 'back at the latest follows again');
}

console.log('follow-hand ok');
