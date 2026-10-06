const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const start = source.indexOf('function replayFlush(ms) {');
const end = source.indexOf('\nipcMain.handle("replay:frames"', start);
function fixture(execute, running = true) {
  let timer, cleared = 0, calls = 0;
  const context = { Promise, screenRing: { running },
    win: { isDestroyed: () => false, webContents: { executeJavaScript(code, gesture) {
      calls++; assert.match(code, /PineScreenRing\.flush\(\)/); assert.equal(gesture, true);
      return execute();
    } } },
    setTimeout(fn, ms) { timer = fn; assert.ok(ms >= 200); return 1; },
    clearTimeout() { cleared++; } };
  vm.runInNewContext(source.slice(start, end), context);
  return { flush: context.replayFlush, timeout: () => timer(),
    calls: () => calls, cleared: () => cleared };
}
(async () => {
  let commitSound;
  const f = fixture(() => new Promise(resolve => { commitSound = resolve; }));
  let settled = false;
  const pending = f.flush(900).then(value => { settled = true; return value; });
  await Promise.resolve();
  assert.equal(settled, false, 'a fresh picture cannot finish flush while sound is uncommitted');
  commitSound(true);
  assert.equal(await pending, true); assert.equal(f.cleared(), 1);
  const unavailable = fixture(() => { throw new Error('must not call'); }, false);
  assert.equal(await unavailable.flush(), false); assert.equal(unavailable.calls(), 0);
  const rejected = fixture(() => Promise.reject(new Error('renderer unavailable')));
  assert.equal(await rejected.flush(), false);
  let late;
  const slow = fixture(() => new Promise(resolve => { late = resolve; }));
  const bounded = slow.flush(900); slow.timeout();
  assert.equal(await bounded, false, 'a dead renderer cannot hang export');
  late(true); await Promise.resolve(); assert.equal(slow.cleared(), 1);
  const malformed = fixture(() => undefined);
  assert.equal(await malformed.flush(), false, 'old renderers do not claim completed flush');
  let sourceHandler;
  const sourceStart = source.indexOf('ipcMain.handle("replay:source"');
  const sourceEnd = source.indexOf('\n});', sourceStart) + 4;
  vm.runInNewContext(source.slice(sourceStart, sourceEnd), {
    ipcMain: { handle: (_name, fn) => { sourceHandler = fn; } },
    win: { isDestroyed: () => false, getMediaSourceId: () => 'window:pine',
      getBounds: () => ({ x: 0, y: 0, width: 441, height: 249 }) },
    require: name => { assert.equal(name, 'electron'); return { screen: {
      getDisplayMatching: bounds => { assert.equal(bounds.width, 441); return { scaleFactor: 1.5 }; }
    } }; }, LOOPBACK_HERE: true, process
  });
  const geometry = sourceHandler();
  assert.equal(geometry.id, 'window:pine');
  assert.equal(geometry.width, 662); assert.equal(geometry.height, 374);
  console.log('PiP flush: both streams committed, bounded failures and physical source geometry passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
