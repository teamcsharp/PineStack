'use strict';
/* [pip-rec] [pip-video-folder] [cam-words] The album recorder widget and the Video folder menu, without a window.
 *
 * Run on local disk, never from the share:  node --test tests/test_pip_recorder_2026_10_05.cjs
 * The widget in a real (hidden) shell: tests/test_pip_recorder_browser_2026_10_05.cjs, with Electron.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(ROOT, name), 'utf8');
const lf = text => text.replace(/\r\n/g, '\n');
const plain = value => JSON.parse(JSON.stringify(value));

function shell(options = {}) {
  const handlers = new Map(), sent = [];
  let template = null, cfg = options.cfg || { pip: {} };
  const webContents = { send: (...args) => sent.push(args), on() {} };
  const bounds = { x: 100, y: 100, width: 1200, height: 800 };
  const window = { __pinePip: true, webContents, isDestroyed: () => false, isVisible: () => true, isMinimized: () => false, getBounds: () => ({ ...bounds }), getContentBounds: () => ({ ...bounds }), getNormalBounds: () => ({ ...bounds }), setBounds(n) { Object.assign(bounds, n); }, isMaximized: () => false, isFullScreen: () => false, isAlwaysOnTop: () => false, isMenuBarVisible: () => false, getTitle: () => 'Pine Box', isMaximizable: () => true, setMaximizable() {}, setMenuBarVisibility() {}, setMinimumSize() {}, setAspectRatio() {}, setAlwaysOnTop() {}, setTitle() {}, setFullScreen() {}, unmaximize() {}, maximize() {}, on() {} };
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  const electron = { screen: { getDisplayNearestPoint: () => ({ workArea: area, bounds: area }), getDisplayMatching: () => ({ workArea: area, bounds: area }) }, Menu: { buildFromTemplate(value) { template = value; return { popup() {} }; } } };
  const ipcMain = { handle: (channel, fn) => handlers.set(channel, fn), on() {}, removeListener() {} };
  const module = { exports: {} };
  vm.runInNewContext(read('desktop/pip-window.cjs'), { module, exports: module.exports, require: name => { assert.equal(name, 'electron'); return electron; }, setTimeout, clearTimeout, console });
  module.exports.install({ ipcMain, getWindow: () => window, readConfig: () => cfg, writeConfig: next => { cfg = { ...cfg, ...next }; } });
  const event = { sender: webContents };
  return { native: module.exports, window, sent, cfg: () => cfg, template: () => template, invoke: (name, args) => handlers.get('pip:' + name)(event, args) };
}

test('[pip-rec] the recorder is a widget the menu can show, off by default, with a layout entry of its own', () => {
  const h = shell();
  const prefs = h.native.preferences({});
  assert.equal(prefs.widgets.rec, false);
  assert.equal(h.native.preferences({ widgets: { rec: true } }).widgets.rec, true);
  assert.deepEqual(plain(h.native.preferences({ layout: { rec: { x: .4, y: .6, s: 1.2 } } }).layout.rec), { x: .4, y: .6, s: 1.2 });
  h.invoke('menu', {});
  const row = h.template().find(item => item.label === 'Album recorder (K.O. Sidekick)');
  assert.ok(row, 'the menu names it'); assert.equal(row.type, 'checkbox'); assert.equal(row.checked, false);
  row.click(); assert.equal(h.cfg().pip.widgets.rec, true);
});

test('[pip-video-folder] the Video submenu lists every folder the station handed over, marks the pinned one, and asks for an hour', () => {
  const h = shell();
  const folders = [{ path: 'sfx/clips/madv', name: 'madv', video: 120, audio: 3 }, { path: 'sfx/clips/consp', name: 'consp', video: 40, audio: 0 }];
  h.invoke('menu', { folders, pin: { path: 'sfx/clips/consp', name: 'consp', minutes_left: 41 } });
  const video = h.template().find(item => item.label === 'Video');
  assert.ok(video, 'the Video entry is on the menu');
  const labels = plain(video.submenu.map(item => item.label || item.type));
  assert.deepEqual(labels, ['Every folder (clear: consp, 41 min left)', 'separator', 'madv  (120 video, 3 audio)', 'consp  (40 video, 0 audio)']);
  assert.equal(video.submenu[3].checked, true, 'the pinned folder is marked'); assert.equal(video.submenu[2].checked, false); assert.equal(video.submenu[0].checked, false);
  video.submenu[2].click();
  assert.deepEqual(plain(h.sent.at(-1)), ['pip:action', { type: 'video-folder', path: 'sfx/clips/madv' }]);
  video.submenu[0].click();
  assert.deepEqual(plain(h.sent.at(-1)), ['pip:action', { type: 'video-folder', clear: true }]);
  const h2 = shell(); h2.invoke('menu', {});
  const bare = h2.template().find(item => item.label === 'Video');
  assert.equal(bare.submenu[0].label, 'Every folder (no pin)'); assert.equal(bare.submenu[0].checked, true); assert.equal(bare.submenu.length, 2, 'no folders yet: only the clear entry');
  const before = h2.template().findIndex(item => item.label === 'Video'), endless = h2.template().findIndex(item => item.label === 'Endless video');
  assert.equal(endless, before + 1, 'Video sits just above Endless video');
});

test('[pip-rec] the page: the widget, its roads, its clock, its sizes; both copies the same', () => {
  const page = lf(read('desktop/renderer/pine-pip.js'));
  for (const piece of ["function buildRecorder() {", "api().get('/api/pinelive/state')", "recPost('/api/pinelive/stop'", "recPost('/api/pinelive/start', body", "recPost('/api/dj/next'", "api().get('/api/pinelive/troubleshoot')", "api().get('/api/pinelive/settings')", "'/api/pinelive/cover'", "api().get('/api/sfx/folders')", "api().post('/api/sfx/folder-pin', body)", "const REC_KBPS = 320, REC_BAR_S = 360, REC_BAR_GROW_S = 120, clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;", "grip(notch, 'rec', notch);", "function recRolodex(out, text) {", "'pip-rec-track'", "DEFAULT_LAYOUT = { rec: { x: .3, y: .5 } }", "name !== 'rec'; }"]) {
    assert.ok(page.includes(piece), 'the page has: ' + piece);
  }
  /* the clock and the size, lifted and run */
  const fn = name => { const at = page.indexOf('  function ' + name + '('); const end = page.indexOf('\n  function ', at + 10); return page.slice(at, end); };
  const scope = {}; vm.runInNewContext(fn('recTime') + fn('recShort') + fn('recSize') + '\nthis.recTime = recTime; this.recShort = recShort; this.recSize = recSize;', scope);
  assert.equal(scope.recTime(0), '00:00:00:00'); assert.equal(scope.recTime(3725.5), '01:02:05:50'); assert.equal(scope.recTime(59.999), '00:00:59:99');
  assert.equal(scope.recShort(360), '6:00'); assert.equal(scope.recShort(3661), '1:01:01');
  assert.equal(scope.recSize(40000 * 12), '480 KB', 'twelve seconds at 320 kb/s'); assert.equal(scope.recSize(40000 * 30), '1.20 MB', 'thirty seconds crosses into MB');
  assert.equal(read('desktop/renderer/pine-pip.js'), read('app/src/main/assets/pine-views/pine-pip.js'), 'the tablet copy is the same file');
  assert.doesNotMatch(page, /[^\x00-\x7f]/, 'the page stays ASCII');
});

test('[cam-words] the camera text lives below its title; [pip-rec] the recorder has its styles, in both copies', () => {
  const css = lf(read('desktop/renderer/pine-pip.css'));
  assert.match(css, /\.pip-camera-status \{ position: absolute; left: 0; right: 0; top: 28px; bottom: 0; display: grid; place-content: center; padding: 4px 10px 8px;/);
  for (const sel of ['#pinePipWidgets .pip-rec {', '.pip-rec-notch', '.pip-rec-track { grid-area: track; font: 700 70px/1', '.pip-rec.mini {', '.pip-rec-size b.flip', '@keyframes pip-rec-sheen']) assert.ok(css.includes(sel), 'css has ' + sel);
  assert.equal(read('desktop/renderer/pine-pip.css'), read('app/src/main/assets/pine-views/pine-pip.css'));
});
