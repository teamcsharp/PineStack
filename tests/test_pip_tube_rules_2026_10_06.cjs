/* [pip-tube-rules] What the tube refuses, and what it no longer refuses (2026-10-06).
   node --test tests/test_pip_tube_rules_2026_10_06.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const copies = ['desktop/renderer/pine-pip.js', 'app/src/main/assets/pine-views/pine-pip.js']
  .map(p => path.join(ROOT, p)).filter(p => fs.existsSync(p));

for (const file of copies) {
  const src = fs.readFileSync(file, 'utf8');
  const short = path.relative(ROOT, file);
  test(short + ': a loop, a warm copy and a bubble copy are refused', () => {
    assert.match(src, /function repeatOf\(v\) \{\s*if \(v\.loop\) return 'loops';/);
    assert.ok(src.includes("if (v.dataset && v.dataset.pineWarm === '1') return 'warm copy';"), 'the CRT set\'s warm element is never tiled');
    assert.ok(src.includes("if (v.classList && v.classList.contains('sp-mv-video')) return 'bubble copy';"), 'the script page\'s bubble thumbnail is never tiled');
  });
  test(short + ': a source shown before, and a clock that jumps back, are program', () => {
    assert.ok(!src.includes("return 'already shown'"), 'the ten-minute once-only rule is gone');
    assert.ok(!/\.rewound\b/.test(src), 'no rewind rule remains');
    assert.ok(src.includes('if (repeatOf(video)) return false;'), 'active() asks repeatOf for every element, tiled or not');
  });
  test(short + ': the record of shown sources is still kept for probes', () => {
    assert.ok(src.includes('function noteShown(v)'));
    assert.ok(src.includes('noteShown(v)'));
  });
}

test('both copies of pine-pip.js are identical', () => {
  if (copies.length < 2) return;
  assert.equal(fs.readFileSync(copies[0], 'utf8'), fs.readFileSync(copies[1], 'utf8'));
});
