const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const js = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.css'), 'utf8');
const start = js.indexOf("  var BAND_STORAGE_KEY = 'pine.script.bands.v1';");
const end = js.indexOf('  var REJECTION_PAGE', start);
assert.ok(start > 0 && end > start, 'band controller is present');

function fixture(saved = null) {
  const storage = new Map();
  if (saved !== null) storage.set('pine.script.bands.v1', saved);
  const localStorage = {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
  };
  const context = {root: {localStorage}};
  vm.runInNewContext(js.slice(start, end), context);
  const items = {};
  for (const key of ['current', 'sequence', 'sync', 'readiness']) {
    const attributes = {};
    items[key] = {
      wrap: {hidden: false}, content: {hidden: key === 'sequence'},
      restore: {hidden: true, setAttribute: (name, value) => { attributes['restore:' + name] = value; }},
      collapse: {setAttribute: (name, value) => { attributes[name] = value; }},
      attributes,
    };
  }
  const bands = {hidden: false}, toolbar = {hidden: true};
  const controller = context.bandController(bands, toolbar, items);
  return {items, bands, toolbar, controller, storage};
}

test('four controls mount with named accessible collapse and restore buttons', () => {
  for (const key of ['current', 'sequence', 'sync', 'readiness']) {
    assert.match(js, new RegExp("addBand\\('" + key + "'"));
  }
  assert.match(js, /collapse\.setAttribute\('aria-label', 'Collapse ' \+ label\)/);
  assert.match(js, /reopen\.setAttribute\('aria-label', 'Restore ' \+ label\)/);
  assert.match(js, /top\.appendChild\(restore\);\s+right\.appendChild\(top\);/);
  assert.match(css, /\.sp-band-row\[hidden\].*display: none/);
});

test('bands collapse independently, reclaim space, and persist', () => {
  const f = fixture();
  assert.equal(f.toolbar.hidden, false,
    'the permanent System Prompt command keeps the top toolbar reachable');
  f.controller.set('current', true);
  f.controller.set('sync', true);
  assert.equal(f.items.current.wrap.hidden, true);
  assert.equal(f.items.readiness.wrap.hidden, false);
  assert.equal(f.items.current.restore.hidden, false);
  assert.equal(f.items.current.attributes['aria-expanded'], 'false');
  assert.equal(f.toolbar.hidden, false);
  assert.deepEqual(JSON.parse(f.storage.get('pine.script.bands.v1')),
    {current: true, sequence: false, sync: true, readiness: false});
  f.controller.set('current', false);
  assert.equal(f.items.current.wrap.hidden, false);
  assert.equal(f.items.current.restore.hidden, true);
  assert.equal(f.items.current.attributes['aria-expanded'], 'true');
});

test('stored state survives remount and empty live sequence stays naturally hidden', () => {
  const f = fixture('{"current":true,"sequence":true,"sync":false,"readiness":true}');
  assert.equal(f.items.current.wrap.hidden, true);
  assert.equal(f.items.sequence.wrap.hidden, true);
  assert.equal(f.items.readiness.wrap.hidden, true);
  f.controller.set('sequence', false);
  assert.equal(f.items.sequence.wrap.hidden, true);
  assert.equal(f.items.sequence.restore.hidden, true);
  f.items.sequence.content.hidden = false;
  f.controller.refresh();
  assert.equal(f.items.sequence.wrap.hidden, false);
});

test('all collapsed leaves only the compact restore toolbar', () => {
  const f = fixture();
  for (const key of Object.keys(f.items)) f.controller.set(key, true);
  assert.equal(f.bands.hidden, true);
  assert.equal(f.toolbar.hidden, false);
  for (const item of Object.values(f.items)) assert.equal(item.restore.hidden, false);
});

test('all open still leaves the System Prompt toolbar reachable', () => {
  const f = fixture();
  assert.equal(f.toolbar.hidden, false);
  for (const item of Object.values(f.items)) assert.equal(item.restore.hidden, true);
});
