// [reply-gap] the Script view's toolbar: the pause between replies (0.2 - 10 s,
// default 1), the roulette range, the roulette switch and the dice square -
// in every copy of the view, byte for byte, and wired to the station's door.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const read = p => fs.readFileSync(p, 'utf8');
const js = path.join(root, 'desktop/renderer/script-page.js');
const css = path.join(root, 'desktop/renderer/script-page.css');
const src = read(js);
const sheet = read(css);
const copies = [
  path.join(root, 'app/src/main/assets/pine-views'),
  'C:/_tools/pinebox-android/PineBoxKiosk/app/src/main/assets/pine-views',
];
for (const dir of copies) {
  if (!fs.existsSync(dir)) continue;
  assert.strictEqual(read(path.join(dir, 'script-page.js')), src, dir + ': script-page.js is the renderer, byte for byte');
  assert.strictEqual(read(path.join(dir, 'script-page.css')), sheet, dir + ': script-page.css is the renderer, byte for byte');
}

// 1. It is on the toolbar, right of the chat icon, and the feed drives the dice.
assert(src.includes('restore.appendChild(gapBar());'), 'the bar is appended to the toolbar');
assert(src.indexOf('restore.appendChild(gapBar());') > src.indexOf("folderIcon(mode === 'technical' ? 'm:casino' : 'c:chat'"),
  'after the chat icon');
assert(src.indexOf('restore.appendChild(gapBar());') < src.indexOf('restore.appendChild(s3Air);'), 'before System 3\'s pill');
assert(/tick\(\);\n\s+gapWatch\(\);/.test(src), 'every feed tick asks the dice');
assert(src.includes("api().get('/api/reply-gap?recent=1')"), 'reads the station setting');
assert(src.includes("api().post('/api/reply-gap', body)"), 'writes the station setting');

// 2. The bounds.
assert(/var GAP_MIN = 0, GAP_MAX = 10, GAP_RANGE_MIN = 0, GAP_RANGE_MAX = 10;/.test(src), 'slider bounds');   // [reply-gap:instant]
assert(src.includes("var gapState = {gap: 1, range: 1, roll: false};"), 'default 1 s, roulette off');
// [reply-gap:dual] one track, two thumbs, on the 0.1 s step
assert(src.includes("th.setAttribute('role', 'slider');"), 'the thumbs are sliders');
assert(src.includes("th.setAttribute('aria-valuemin', String(GAP_MIN));") && src.includes("th.setAttribute('aria-valuemax', String(GAP_MAX));"));
assert(!/type = 'range'/.test(src.slice(src.indexOf('function gapBar()'), src.indexOf('  function mount(node) {'))), 'no separate range inputs any more');

const grab = name => {
  const m = src.match(new RegExp('\\n  function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n'));
  assert(m, 'missing ' + name);
  return m[0];
};
const names = ['gapNum', 'gapClamp', 'gapWindow', 'gapHere', 'gapWatch', 'gapBars', 'gapCountStop',
  'gapCountTick', 'gapOnCue', 'gapPct', 'gapValAt'];
const body = names.map(grab).join('') + 'return {' + names.map(n => n + ': ' + n).join(', ') + '};';
const bar = () => ({style: {}});
const env = {liveStream: null, t: -1, rolled: [], kicks: 0, player: null, ups: [],
  state: {gap: 1, range: 1, roll: true}, fired: {},
  ui: {count: bar(), rowbar: bar(), wrap: {classList: {toggle() {}}}}};
// eslint-disable-next-line no-new-func
const f = new Function('GAP_MIN', 'GAP_MAX', 'env', 'gapLoad', 'gapRoll', 'gapCountKick', 'soundingPlayer', 'mvUpcomingSet',
  'var liveStream = null, gapUi = env.ui, gapFired = env.fired, gapCount = null; var gapState = env.state;'
  + 'var document = {visibilityState: "visible"};'
  + 'function streamAt() { return env.t; }'
  + 'var o = (function () {' + body + '})();'
  + 'o.sync = function () { liveStream = env.liveStream; gapState = env.state; };'
  + 'o.count = function (c) { if (arguments.length) gapCount = c; return gapCount; };'
  + 'return o;')(
  0.2, 10, env, () => {}, g => env.rolled.push(g), () => { env.kicks += 1; }, () => env.player, u => env.ups.push(u));
const watch = () => { f.sync(); f.gapWatch(); };
assert.deepStrictEqual(f.gapWindow(1, 1.9), [1, 1.9], '[reply-gap:between] rolls land between the two sliders');
assert.deepStrictEqual(f.gapWindow(9, 3), [3, 9], 'either way round');
assert.strictEqual(f.gapClamp(0, 0.2, 10, 1), 0.2);
assert.strictEqual(f.gapClamp(42, 0.2, 10, 1), 10);
assert.strictEqual(f.gapClamp('x', 0.2, 10, 1), 1);
assert.strictEqual(f.gapValAt(0, 0, 200), 0.2, 'the left end of the track is 0.2 s');
assert.strictEqual(f.gapValAt(200, 0, 200), 10, 'its right end 10 s');
assert.strictEqual(f.gapValAt(100, 0, 200), 5.1, 'the middle, on the step');
assert.strictEqual(f.gapValAt(-50, 0, 200), 0.2, 'a finger off the end holds the end');
assert.strictEqual(f.gapPct(0.2), 0);
assert.strictEqual(f.gapPct(10), 100);

// 3. Inside a welded round: the dice roll when the reply ends in the audio - once -
//    and the countdown runs on that clip's own playhead.
const rows = [
  {id: 'a', from: 0, until: 6.7, gap: {s: 1.7, inside: 1.7, rolled: true, dice: 42, lo: 0.2, hi: 2}},
  {id: 'b', from: 6.7, until: 10, gap: {s: 1, inside: 1, rolled: false}},
];
env.liveStream = {at: 111, rows};
env.t = 4.0; watch();
assert.strictEqual(env.rolled.length, 0, 'mid-reply: nothing yet');
env.t = 5.05; watch();
assert.strictEqual(env.rolled.length, 1, 'the reply ended: the dice roll');
assert.strictEqual(env.rolled[0].s, 1.7);
assert.deepStrictEqual(f.count(), {file: 's:111', end: 6.7, total: 1.7}, 'the countdown is the pause, on the playhead');
assert.strictEqual(env.ui.count.style.transform, 'scaleX(1.0000)', 'both bars start full');
env.t = 5.85; f.gapCountTick();
assert.strictEqual(env.ui.count.style.transform, env.ui.rowbar.style.transform, 'the two bars agree');
assert(/^scaleX\(0\.5/.test(env.ui.count.style.transform), 'half the pause left: ' + env.ui.count.style.transform);
env.t = 6.8; f.gapCountTick();
assert.strictEqual(env.ui.count.style.transform, 'scaleX(0.0000)', 'empty as the next reply begins');
assert.strictEqual(f.count(), null);
env.t = 5.5; watch();
assert.strictEqual(env.rolled.length, 1, 'once per reply');
env.t = 9.2; watch();
assert.strictEqual(env.rolled.length, 1, 'a fixed pause does not roll');
// the sounding clip's own rows outrank the station's stream_now
env.player = {currentTime: 5.2, pineDeliveryClip: {delivery_id: 'D1', stream: {rows}}};
watch();
assert.strictEqual(env.rolled.length, 2, 'this page\'s own player: rolled');
assert.strictEqual(f.count().file, 'd:D1');
env.player = null;
env.state = {gap: 1, range: 1, roll: false}; env.liveStream = {at: 222, rows}; env.t = 5.05; watch();
assert.strictEqual(env.rolled.length, 2, 'roulette off: no dice');

// 4. Between two clips: the player's cue at the words' end, draining to the
//    moment the player's own timer starts the next message.
env.state = {gap: 1, range: 1.9, roll: true}; f.sync();
const now = Date.now();
f.gapOnCue({detail: {s: 2.2, rolled: true, dice: 76, lo: 0.2, hi: 2.9, startsAt: now + 2200}});
assert.strictEqual(env.rolled.length, 3, 'a message ended: the dice roll');
assert.strictEqual(env.rolled[2].s, 2.2);
assert(f.count().to === now + 2200, 'drains to the player\'s start');
f.count({from: Date.now() - 1000, to: Date.now() + 1000}); f.gapCountTick();
assert(/^scaleX\(0\.(49|50|51)/.test(env.ui.rowbar.style.transform), env.ui.rowbar.style.transform);
f.gapOnCue({detail: {s: 1, rolled: false, startsAt: now + 1000}});
assert.strictEqual(env.rolled.length, 3, 'a fixed pause does not roll');
env.state = {gap: 1, range: 1.9, roll: false}; f.sync();
f.gapOnCue({detail: {s: 2, rolled: true, startsAt: now + 2000}});
assert.strictEqual(env.rolled.length, 3, 'roulette off: idle');
assert(src.includes("root.addEventListener('pine-reply-gap', gapOnCue);"), 'the view hears the player');

// 4b. [reply-gap:buildup] pause, then buildup, then words: the dice count the
//     pause only, and the next card is told when to start building.
env.state = {gap: 1, range: 3.1, roll: true}; f.sync();
env.ups.length = 0;
const n2 = Date.now();
f.gapOnCue({detail: {s: 2, rolled: true, dice: 50, lo: 1, hi: 3.1, startsAt: n2 + 9000, buildup_ms: 7000,
  lid: 'L2', who: 'cohost', name: 'DILL', text: 'next words'}});
assert.strictEqual(f.count().to, n2 + 2000, 'the countdown ends where the buildup begins');
assert.strictEqual(env.ups.length, 1);
assert.deepStrictEqual([env.ups[0].lid, env.ups[0].audioAt, env.ups[0].ms], ['L2', n2 + 9000, 7000], 'the card builds for 7 s before its words');
env.state = {gap: 1, range: 3.1, roll: false}; f.sync();
f.gapOnCue({detail: {s: 1, rolled: false, startsAt: n2 + 6000, buildup_ms: 4000, lid: 'L3'}});
assert.strictEqual(env.ups.length, 2, 'roulette off: no dice, but the card still builds before its words');
env.state = {gap: 1, range: 3.1, roll: true}; f.sync();
const rows2 = [
  {id: 'x', from: 0, until: 10, gap: {s: 1.5, inside: 6.5, buildup_ms: 5000, rolled: true, dice: 9}},
  {id: 'y', from: 10, until: 14, who: 'third', name: 'SAM', text: 'the next'},
];
env.player = {currentTime: 3.55, pineDeliveryClip: {delivery_id: 'D9', stream: {rows: rows2}}};
env.ups.length = 0;
watch();
assert.deepStrictEqual(f.count(), {file: 'd:D9', end: 5, total: 1.5}, 'in a round: the pause first, on the playhead');
assert.strictEqual(env.ups.length, 1);
assert.strictEqual(env.ups[0].lid, 'y');
assert.strictEqual(env.ups[0].ms, 5000);
assert(Math.abs(env.ups[0].audioAt - (Date.now() + 6450)) < 50, 'its words when the file reaches them');
env.player = null;

// 5. Every control has a tooltip; Carbon icons that are vendored; no emoji.
const block = src.slice(src.indexOf('/* [reply-gap] THE PAUSE BETWEEN REPLIES, ON THE TOOLBAR.'), src.indexOf('  function mount(node) {'));
for (const tip of ['gapUi.a.title', 'gapUi.b.title', 'gapUi.dual.title', 'gapUi.sw.title', 'gapUi.die.title']) {
  assert(block.includes(tip + ' = '), 'tooltip: ' + tip);
}
assert.strictEqual((block.match(/Station-wide - every listener hears this\./g) || []).length, 3,
  'the pause, the range and the switch say they are the whole station\'s');
assert(!/localStorage|sessionStorage/.test(block), 'nothing about the pause is kept per device');
const icons = read(path.join(root, 'desktop/renderer/pine-icons.js'));
for (const name of ['c:hourglass', 'm:casino']) {
  assert(block.includes("'" + name + "'"), 'uses ' + name);
  assert(icons.includes('"' + name + '": ['), name + ' is in the vendored set');
}
for (const ch of block) {
  const c = ch.codePointAt(0);
  assert(!(c >= 0x1F000 || (c >= 0x2600 && c <= 0x27BF)), 'no emoji in the bar: U+' + c.toString(16));
}

// 6. The sheet: pinned sizes on a 28 px row, the switch, the square.
for (const rule of ['.sp-gap {', '.sp-gap-slider {', '.sp-gap-switch {', '.sp-gap .sp-gap-die {',
  '.sp-gap-switch[aria-checked="true"]::after']) {
  assert(sheet.includes(rule), 'css: ' + rule);
}
assert(/\.sp-gap \.sp-gap-die \{[^}]*max-height: 28px/.test(sheet), 'the square cannot grow past the row');
for (const rule of ['.sp-gap-dual {', '.sp-gap-track {', '.sp-gap-thumb {', '.sp-gap-span {',
  '.sp-band-restore > .sp-band-reopen {', '.sp-gap-countwell {', '.sp-gap-rowbar {', '.sp-gap:not(.sp-gap-on) .sp-gap-count, .sp-gap:not(.sp-gap-on) .sp-gap-rowbar { display: none; }']) {
  assert(sheet.includes(rule), 'css: ' + rule);
}
assert(/\.sp-gap-track \{[^}]*touch-action: none/.test(sheet), 'the track takes the finger');
assert(/\.sp-gap-thumb \{[^}]*width: 30px; height: 30px/.test(sheet), 'thumbs a finger can find: 30 px');
assert(/\.sp-band-restore > \.sp-band-reopen \{[^}]*width: 34px;[^}]*height: 34px;[^}]*max-height: 34px/.test(sheet), 'square icons');
assert(/\.sp-band-restore \{ align-items: center; \}/.test(sheet), 'not stretched to the row');
console.log('reply-gap ui: ok');
