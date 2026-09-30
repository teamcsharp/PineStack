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
assert(/var GAP_MIN = 0\.2, GAP_MAX = 10, GAP_RANGE_MIN = 0\.1, GAP_RANGE_MAX = 10;/.test(src), 'slider bounds');
assert(src.includes("var gapState = {gap: 1, range: 1, roll: false};"), 'default 1 s, roulette off');
assert(src.includes("input.step = '0.1';"), 'a tenth of a second a step');

const grab = name => {
  const m = src.match(new RegExp('\\n  function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n'));
  assert(m, 'missing ' + name);
  return m[0];
};
const body = ['gapNum', 'gapClamp', 'gapWindow', 'gapWatch'].map(grab).join('')
  + 'return {gapNum: gapNum, gapClamp: gapClamp, gapWindow: gapWindow, gapWatch: gapWatch};';
const env = {liveStream: null, t: -1, rolled: [], state: {gap: 1, range: 1, roll: true}, fired: {}};
// eslint-disable-next-line no-new-func
const f = new Function('GAP_MIN', 'GAP_MAX', 'env', 'gapLoad', 'gapRoll',
  'var liveStream, gapUi = {}, gapFired = env.fired; var gapState = env.state;'
  + 'function streamAt() { return env.t; }'
  + 'return (function () { var o = (function () {' + body + '})();'
  + 'return {gapNum: o.gapNum, gapClamp: o.gapClamp, gapWindow: o.gapWindow,'
  + 'watch: function () { liveStream = env.liveStream; return o.gapWatch(); }}; })();')(
  0.2, 10, env, () => {}, g => env.rolled.push(g));
assert.deepStrictEqual(f.gapWindow(1, 1), [0.2, 2], 'gap 1 +/- 1 is 0.2 - 2.0');
assert.deepStrictEqual(f.gapWindow(9, 3), [6, 10]);
assert.strictEqual(f.gapClamp(0, 0.2, 10, 1), 0.2);
assert.strictEqual(f.gapClamp(42, 0.2, 10, 1), 10);
assert.strictEqual(f.gapClamp('x', 0.2, 10, 1), 1);

// 3. The dice roll when the reply ends in the audio - once.
env.liveStream = {at: 111, rows: [
  {id: 'a', from: 0, until: 6.7, gap: {s: 1.7, inside: 1.7, rolled: true, dice: 42, lo: 0.2, hi: 2}},
  {id: 'b', from: 6.7, until: 10, gap: {s: 1, inside: 1, rolled: false}},
]};
env.t = 4.0; f.watch();
assert.strictEqual(env.rolled.length, 0, 'mid-reply: nothing yet');
env.t = 5.05; f.watch();
assert.strictEqual(env.rolled.length, 1, 'the reply ended: the dice roll');
assert.strictEqual(env.rolled[0].s, 1.7);
env.t = 5.5; f.watch();
assert.strictEqual(env.rolled.length, 1, 'once per reply');
env.t = 9.2; f.watch();
assert.strictEqual(env.rolled.length, 1, 'a fixed pause does not roll');
env.state.roll = false; env.liveStream = {at: 222, rows: env.liveStream.rows}; env.t = 5.05; f.watch();
assert.strictEqual(env.rolled.length, 1, 'roulette off: no dice');

// 4. Every control has a tooltip; Carbon icons that are vendored; no emoji.
const block = src.slice(src.indexOf('/* [reply-gap] THE PAUSE BETWEEN REPLIES, ON THE TOOLBAR.'), src.indexOf('  function mount(node) {'));
for (const tip of ['gapUi.oneBox.title', 'gapUi.twoBox.title', 'gapUi.sw.title', 'gapUi.die.title']) {
  assert(block.includes(tip + ' = '), 'tooltip: ' + tip);
}
const icons = read(path.join(root, 'desktop/renderer/pine-icons.js'));
for (const name of ['c:hourglass', 'c:shuffle', 'm:casino']) {
  assert(block.includes("'" + name + "'"), 'uses ' + name);
  assert(icons.includes('"' + name + '": ['), name + ' is in the vendored set');
}
for (const ch of block) {
  const c = ch.codePointAt(0);
  assert(!(c >= 0x1F000 || (c >= 0x2600 && c <= 0x27BF)), 'no emoji in the bar: U+' + c.toString(16));
}

// 5. The sheet: pinned sizes on a 28 px row, the switch, the square.
for (const rule of ['.sp-gap {', '.sp-gap-slider {', '.sp-gap-switch {', '.sp-gap .sp-gap-die {',
  '.sp-gap-switch[aria-checked="true"]::after']) {
  assert(sheet.includes(rule), 'css: ' + rule);
}
assert(/\.sp-gap \.sp-gap-die \{[^}]*max-height: 28px/.test(sheet), 'the square cannot grow past the row');
console.log('reply-gap ui: ok');
