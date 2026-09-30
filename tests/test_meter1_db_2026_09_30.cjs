// [meter1-db] the music row's ceiling follows the Music level as it is HEARD (dB).
// "This element isn't increasing in vertical scale to show the audio playing for
// music ... the amount that it goes out is based on exactly the level I have the
// volume set." At Music 0.0875 the linear cap drew under 2 px of a 22 px row.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
const kiosk = path.join(root, 'app/src/main/assets/pine-views/script-page.js');
if (fs.existsSync(kiosk)) assert.strictEqual(fs.readFileSync(kiosk, 'utf8'), src, 'the kiosk copy is the renderer, byte for byte');

const grab = re => { const m = src.match(re); assert(m, 'missing ' + re); return m[0]; };
const body = [
  grab(/var M1_CAP_DB = [^;]+;/),
  grab(/var M1_CAP_MIN = [^;]+;/),
  grab(/function meterOneCap\(\) \{[\s\S]*?\n  \}\n/),
].join('\n');

function capAt(level, player) {
  // eslint-disable-next-line no-new-func
  const make = new Function('levelNow', 'el', body + '\nreturn meterOneCap;');
  return make(() => level, () => player || null)();
}

// 0 is the thin line; 100% is full height; any level above zero is visible.
assert.strictEqual(capAt(0), 0);
assert.strictEqual(capAt(1), 1);
assert.strictEqual(capAt(2), 1, 'over 100% still tops out at full height');
assert(capAt(0.0005) >= 0.1, 'a level above zero never draws the flat line');

// The measured case: 0.0875 (-21 dB) swings over half the row, not 8.75%.
const c = capAt(0.0875);
assert(c > 0.5 && c < 0.62, 'Music 0.0875 -> ' + c);

// Monotonic: every nudge of the slider moves the ceiling the same way.
let last = -1;
for (let lv = 0; lv <= 1.0001; lv += 0.01) {
  const v = capAt(lv);
  assert(v >= last, 'not monotonic at ' + lv);
  last = v;
}

// This terminal's own volume and mute ride on top of the level.
assert.strictEqual(capAt(1, {volume: 1, muted: true}), 0);
assert(capAt(1, {volume: 0.5, muted: false}) < 1);
assert(Math.abs(capAt(0.5, {volume: 1}) - capAt(1, {volume: 0.5})) < 1e-9);

console.log('meter1-db ok: 0.0875 ->', c.toFixed(3), '| 0.5 ->', capAt(0.5).toFixed(3), '| 0.01 ->', capAt(0.01).toFixed(3));
