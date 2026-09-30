// [bridge-take] a big bridge answer is pulled as a string, never spliced into
// script source (16 MB/min of settle scripts; 51.6 MB live under (PARSER)).
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const file = path.join(__dirname, '..', 'app/src/main/assets/pine-bridge.js');
const src = fs.readFileSync(file, 'utf8');

function load() {
  const parked = new Map();
  const calls = [];
  const native = {
    invoke(id, method, args) { calls.push({id, method, args}); return JSON.stringify({accepted: true}); },
    take(id) { const v = parked.get(id); parked.delete(id); return v === undefined ? null : v; },
  };
  const win = {__pineNative: native, console: {warn() {}}};
  win.window = win;
  vm.runInNewContext(src, {window: win, Map, Promise, JSON, Error, Array, Date, setTimeout, clearTimeout});
  return {win, native, parked, calls};
}

(async () => {
  // 1. a parked answer is taken and resolves like a spliced one
  {
    const {win, parked, calls} = load();
    const p = win.pineDesktop.get('/api/dj');
    const id = calls[0].id;
    const big = {chat: 'x'.repeat(40000)};
    parked.set(id, JSON.stringify({id, ok: true, value: big}));
    assert.strictEqual(win.__pineBridgeSettle(id, null, 1), true);
    assert.deepStrictEqual(await p, big);
    assert.strictEqual(parked.size, 0, 'taken once, freed natively');
  }
  // 2. the small road is unchanged
  {
    const {win, calls} = load();
    const p = win.pineDesktop.get('/api/playout');
    const id = calls[0].id;
    win.__pineBridgeSettle(id, JSON.stringify({id, ok: true, value: {n: 1}}));
    assert.deepStrictEqual(await p, {n: 1});
  }
  // 3. a late parked reply (no pending slot) still frees its native copy
  {
    const {win, parked} = load();
    parked.set('gone', '{"ok":true,"value":1}');
    assert.strictEqual(win.__pineBridgeSettle('gone', null, 1), false);
    assert.strictEqual(parked.size, 0);
  }
  // 4. a parked answer that is missing rejects instead of hanging
  {
    const {win, calls} = load();
    const p = win.pineDesktop.get('/api/dj');
    win.__pineBridgeSettle(calls[0].id, null, 1);
    await assert.rejects(p, /lost a large answer/);
  }
  console.log('bridge-take ok');
})().catch(err => { console.error(err); process.exit(1); });
