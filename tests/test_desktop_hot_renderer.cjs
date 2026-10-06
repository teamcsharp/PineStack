'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const vm = require('node:vm');
const { stageRendererUpdates } = require('../desktop/hot-renderer.cjs');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'pine-hot-test-'));
  const source = path.join(root, 'source'), mirror = path.join(root, 'mirror');
  await fs.mkdir(source); await fs.mkdir(mirror);
  t.after(async () => {
    const absolute = path.resolve(root), temporary = path.resolve(os.tmpdir()) + path.sep;
    assert.ok(absolute.startsWith(temporary) && path.basename(absolute).startsWith('pine-hot-test-'));
    await fs.rm(absolute, { recursive: true, force: true });
  });
  const logs = [], pending = new Set(), calls = { reload: 0, scripts: [] };
  const window = { isDestroyed: () => false, webContents: {
    reloadIgnoringCache() { calls.reload++; throw new Error('Live players must survive source updates'); },
    async executeJavaScript(code, activation) { calls.scripts.push({ code, activation }); }
  } };
  const run = (changed, overrides = {}) => stageRendererUpdates({ source, mirror, changed,
    window, pending, log: message => logs.push(message), ...overrides });
  return { source, mirror, logs, pending, calls, window, run };
}

test('JS and HTML are copied for an explicit reload while live players continue', async t => {
  const f = await fixture(t);
  await fs.writeFile(path.join(f.source, 'player.js'), 'new player module');
  await fs.writeFile(path.join(f.source, 'index.html'), 'new page');
  assert.deepEqual(await f.run(['player.js', 'index.html']), ['player.js', 'index.html']);
  assert.equal(await fs.readFile(path.join(f.mirror, 'player.js'), 'utf8'), 'new player module');
  assert.equal(await fs.readFile(path.join(f.mirror, 'index.html'), 'utf8'), 'new page');
  assert.deepEqual([...f.pending], ['player.js', 'index.html']);
  assert.equal(f.calls.reload, 0); assert.deepEqual(f.calls.scripts, []);
  assert.ok(f.logs.some(line => line.includes('staged for an explicit reload')));
});

test('CSS swaps only matching stylesheets without reloading or minting a gesture', async t => {
  const f = await fixture(t); await fs.writeFile(path.join(f.source, 'layout.css'), 'new styles');
  const links = ['layout.css?hot=old', 'other.css'].map(href => ({ href,
    getAttribute() { return this.href; }, setAttribute(_, value) { this.href = value; } }));
  assert.deepEqual(await f.run(['layout.css']), ['layout.css']);
  vm.runInNewContext(f.calls.scripts[0].code, { document: { querySelectorAll: () => links }, Date: { now: () => 42 } });
  assert.equal(links[0].href, 'layout.css?hot=42'); assert.equal(links[1].href, 'other.css');
  assert.equal(f.calls.scripts[0].activation, false); assert.equal(f.calls.reload, 0);
  assert.equal(f.pending.size, 0);
});

test('a mixed CSS and JS update applies styles and stages the script', async t => {
  const f = await fixture(t);
  for (const name of ['mix.css', 'mix.js']) await fs.writeFile(path.join(f.source, name), name);
  assert.deepEqual(await f.run(['mix.css', 'mix.js']), ['mix.css', 'mix.js']);
  assert.equal(f.calls.scripts.length, 1); assert.equal(f.calls.reload, 0);
  assert.deepEqual([...f.pending], ['mix.js']);
});

test('copy failures preserve the old module and are returned as unlanded for retry', async t => {
  const f = await fixture(t); await fs.writeFile(path.join(f.mirror, 'missing.js'), 'working player');
  assert.deepEqual(await f.run(['missing.js']), []);
  assert.equal(await fs.readFile(path.join(f.mirror, 'missing.js'), 'utf8'), 'working player');
  assert.equal(f.pending.size, 0); assert.equal(f.calls.reload, 0);
  assert.ok(f.logs.some(line => line.includes('could not copy missing.js')));
});

test('a failed atomic rename removes the temporary copy and preserves the old module', async t => {
  const f = await fixture(t); await fs.writeFile(path.join(f.source, 'locked.js'), 'new player');
  await fs.writeFile(path.join(f.mirror, 'locked.js'), 'working player');
  const fsImpl = { copyFile: fs.copyFile, unlink: fs.unlink, rename: async () => { throw new Error('locked'); } };
  assert.deepEqual(await f.run(['locked.js'], { fsImpl, pid: 7 }), []);
  assert.equal(await fs.readFile(path.join(f.mirror, 'locked.js'), 'utf8'), 'working player');
  assert.deepEqual(await fs.readdir(f.mirror), ['locked.js']); assert.equal(f.calls.reload, 0);
});

test('failed CSS swap keeps the copied file for later and never falls back to reload', async t => {
  const f = await fixture(t); await fs.writeFile(path.join(f.source, 'styles.css'), 'new styles');
  f.window.webContents.executeJavaScript = async () => { throw new Error('window navigating'); };
  assert.deepEqual(await f.run(['styles.css']), ['styles.css']);
  assert.equal(await fs.readFile(path.join(f.mirror, 'styles.css'), 'utf8'), 'new styles');
  assert.equal(f.calls.reload, 0); assert.ok(f.logs.some(line => line.includes('live swap failed')));
});

test('main hot watcher uses the staged updater and has no automatic reload fallback', async () => {
  const main = await fs.readFile(path.join(__dirname, '../desktop/main.js'), 'utf8');
  const body = main.slice(main.indexOf('async function applyHot(source, changed) {'), main.indexOf('/* main.js and preload.js are THIS process.'));
  assert.match(body, /stageRendererUpdates\(/); assert.doesNotMatch(body, /reloadIgnoringCache|\.reload\(/);
});