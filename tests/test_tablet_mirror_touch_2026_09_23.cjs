const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const mirror = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer',
  'tablet-mirror.js'), 'utf8');
const tv = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer',
  'sfx-tv.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer',
  'sfx-tv.css'), 'utf8');

test('Ctrl click is a momentary tablet touch without latching Touch on', () => {
  assert.match(mirror,
    /if \(\(!touching && !event\.ctrlKey\) \|\| event\.button !== 0\) return;/);
  assert.match(mirror, /momentary: !touching && event\.ctrlKey/);
  assert.match(mirror, /if \(event\.ctrlKey\) return;\s*\n\s*goFull/,
    'a Ctrl double-click can still toggle the mirror fullscreen');
});

test('clip inspector has large immediate close targets', () => {
  assert.match(tv, /sfx-tv-sheetrow sfx-tv-sheet-close/);
  assert.match(tv,
    /shut\.addEventListener\('pointerup',[\s\S]{0,160}sheetClose\(\)/);
  assert.match(tv,
    /quit\.addEventListener\('pointerup',[\s\S]{0,160}sheetClose\(\)/);
  assert.match(css,
    /\.sfx-tv-sheet \.sfx-tv-sheet-close button\.quiet \{ flex: 1 1 0;/);
});
