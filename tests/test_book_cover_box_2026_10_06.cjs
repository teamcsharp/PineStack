/* [book-cover-box] A cover is a tall box, whatever the engine thinks of buttons (2026-10-06).
   node --test tests/test_book_cover_box_2026_10_06.cjs
   The geometry itself is measured by tests/probe_book_cover_2026_10_06.cjs in the hidden Electron. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const copies = ['desktop/renderer/book-mode.css', 'app/src/main/assets/pine-views/book-mode.css']
  .map(p => path.join(ROOT, p)).filter(p => fs.existsSync(p));

for (const file of copies) {
  const css = fs.readFileSync(file, 'utf8');
  const short = path.relative(ROOT, file);
  test(short + ': the cover box is sized by its bottom padding, 5:7, not by aspect-ratio on a button', () => {
    assert.ok(css.includes('.bm-card .bm-cover{position:relative;display:block;width:100%;height:0;padding:0 0 140%;box-sizing:content-box;min-height:0;'));
    assert.ok(!/\.bm-cover\{[^}]*aspect-ratio:5\/7/.test(css), 'no aspect-ratio on the cover button');
  });
  test(short + ': the picture is fitted whole and the grid tiles are at least 200 px', () => {
    assert.ok(css.includes('.bm-cover img{object-fit:contain;background:transparent}'));
    assert.ok(!css.includes('.bm-cover img{object-fit:cover;background:#fff}'));
    assert.ok(css.includes('grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:34px 28px;'));
  });
}

test('both copies are identical', () => {
  if (copies.length < 2) return;
  assert.equal(fs.readFileSync(copies[0], 'utf8'), fs.readFileSync(copies[1], 'utf8'));
});
