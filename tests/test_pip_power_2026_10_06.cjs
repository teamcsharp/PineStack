/* [pip-power] A painter nobody can see does not paint (2026-10-06).
   node --test tests/test_pip_power_2026_10_06.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const APP = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8').replace(/\r\n/g, '\n');

function helperSource() {
  const start = APP.indexOf('function pineSeen(el) {');
  assert.ok(start > 0, 'pineSeen is defined');
  const end = APP.indexOf('\n}\n', start) + 3;
  return APP.slice(start, end);
}

test('every painter gate asks pineSeen and no offsetParent-only gate remains', () => {
  const count = s => APP.split(s).length - 1;
  assert.equal(count('if (!pineSeen(canvas)) return;'), 3, 'two scopes and the booth glass');
  assert.equal(count('if (!pineSeen(renderer.domElement)) return;'), 5, 'five three.js stages');
  assert.equal(count('if (!pineSeen(host)) return;'), 1);
  assert.equal(count('if (!canvas.offsetParent) return;'), 0);
  assert.equal(count('if (document.hidden || !renderer.domElement.offsetParent) return;'), 0);
  assert.equal(count('if (document.hidden || !host.offsetParent) return;'), 0);
  assert.equal(count('if (!canvas || !canvas.offsetParent || document.hidden) return;'), 0);
});

test('pineSeen: display:none, a hidden document and visibility:hidden are not seen; the rest is', () => {
  const run = (hidden, el) => {
    const ctx = { document: { hidden } };
    vm.createContext(ctx);
    vm.runInContext(helperSource() + '\nthis.out = pineSeen(el);', Object.assign(ctx, { el }));
    return ctx.out;
  };
  const seen = { offsetParent: {}, checkVisibility: () => true };
  const veiled = { offsetParent: {}, checkVisibility: () => false };            // visibility:hidden under the PiP
  const gone = { offsetParent: null, checkVisibility: () => true };             // display:none
  const old = { offsetParent: {} };                                              // an engine without checkVisibility
  const throwing = { offsetParent: {}, checkVisibility: () => { throw new Error('no'); } };
  assert.equal(run(false, seen), true);
  assert.equal(run(false, veiled), false);
  assert.equal(run(false, gone), false);
  assert.equal(run(true, seen), false);
  assert.equal(run(false, old), true);
  assert.equal(run(false, throwing), true);
  assert.equal(run(false, null), false);
});

test('pineSeen asks for the visibility chain, not only the CSS display chain', () => {
  assert.ok(helperSource().includes('checkVisibility({checkVisibilityCSS: true, visibilityProperty: true})'));
});
