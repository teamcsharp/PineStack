/* [pip-seen] A picture on a PiP tile is a picture seen (2026-10-06).
   node --test tests/test_pip_seen_2026_10_06.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.resolve(__dirname, '..');
const read = p => fs.readFileSync(path.join(ROOT, p), 'utf8');

test('the panel publishes showing(video) in both copies', () => {
  for (const p of ['desktop/renderer/pine-pip.js', 'app/src/main/assets/pine-views/pine-pip.js']) {
    if (!fs.existsSync(path.join(ROOT, p))) continue;
    const src = read(p);
    assert.ok(src.includes('w.PinePipPanel = { showing(video) {'), p + ' answers showing()');
    assert.ok(src.includes("if (!it || !it.painted || it.leaving || host.style.display === 'none' || !host.isConnected) return null;"), p + ': only a painted, staying tile on a shown panel counts');
  }
});

test('the seen-check takes the tile first and marks the receipt', () => {
  const src = read('desktop/renderer/sfx-seen.js');
  assert.ok(src.includes("var onTile = pipPanel && typeof pipPanel.showing === 'function' ? pipPanel.showing(el) : null;"));
  assert.ok(src.includes("if (onTile && onTile.w >= 2 && onTile.h >= 2) { out.rect = onTile; out.frac = 1; out.via = 'pip'; return out; }"));
  assert.ok(src.includes("if (m.via) r.via = m.via;"));
  // the ordinary measure still follows for an element on no tile
  assert.ok(src.indexOf("var onTile =") < src.indexOf("var r = el.getBoundingClientRect();"));
});

test('measure() as written: a tile wins, no tile falls through to the element box', () => {
  const src = read('desktop/renderer/sfx-seen.js');
  const start = src.indexOf('  function measure(el, own) {');
  const end = src.indexOf('\n  }\n', start) + 4;
  const body = src.slice(start, end);
  const answers = { el: null };
  const ctx = { root: { PinePipPanel: { showing: el => (el === answers.el ? { x: 10, y: 20, w: 300, h: 160 } : null) }, innerWidth: 800, innerHeight: 600 }, doc: { elementFromPoint: () => null } };
  vm.createContext(ctx);
  vm.runInContext(body + '\nthis.measure = measure;', ctx);
  const tiled = { isConnected: true, getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 }) };
  answers.el = tiled;
  const m = ctx.measure(tiled, null);
  assert.deepEqual(JSON.parse(JSON.stringify(m.rect)), { x: 10, y: 20, w: 300, h: 160 });
  assert.equal(m.frac, 1); assert.equal(m.via, 'pip'); assert.equal(m.why, '');
  const hidden = { isConnected: true, getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 }) };
  const n = ctx.measure(hidden, null);
  assert.equal(n.why, 'zero size'); assert.equal(n.frac, 0);
});
