'use strict';
/* [pip-free] [pip-art] [pip-favorites-az] [pip-export-bar] [cam-words] [pip-panel-ready]
 * The second PiP wave of 2026-10-05, without a window.
 *
 *   the shell   - every widget's layout entry is a preference (normalised, merged, removed, reset);
 *                 the favorites submenu is alphabetical; the art-only player is a preference
 *   the export  - ffmpeg's -progress lines become seconds; the cut turns them into a share;
 *                 the export tells the window every step
 *   the camera  - the popup says what the station knows, with the evidence
 *   the page    - the panel is unreadied only by a main-frame navigation
 *
 * Run on local disk, never from the share:  node --test tests/test_pip_widgets_2026_10_05.cjs
 * The same in a real (hidden) shell window: tests/test_pip_widgets_browser_2026_10_05.cjs, with Electron.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(ROOT, name), 'utf8');
const lf = text => text.replace(/\r\n/g, '\n');
const plain = value => JSON.parse(JSON.stringify(value));   /* objects born in a vm context are compared by value */

/* ------------------------------------------------------------------ the shell: pip-window.cjs */
function shell(options = {}) {
  const handlers = new Map(), sent = [];
  let template = null, cfg = options.cfg || { pip: {} };
  const webContents = { send: (...args) => sent.push(args), on() {} };
  const bounds = { x: 100, y: 100, width: 1200, height: 800 };
  const window = {
    __pinePip: false, webContents, isDestroyed: () => false, isVisible: () => true, isMinimized: () => false,
    getBounds: () => ({ ...bounds }), getContentBounds: () => ({ ...bounds }), getNormalBounds: () => ({ ...bounds }),
    setBounds(next) { Object.assign(bounds, next); },
    isMaximized: () => false, isFullScreen: () => false, isAlwaysOnTop: () => false, isMenuBarVisible: () => false, getTitle: () => 'Pine Box',
    isMaximizable: () => true, setMaximizable() {}, setMenuBarVisibility() {}, setMinimumSize() {}, setAspectRatio() {}, setAlwaysOnTop() {}, setTitle() {},
    setFullScreen() {}, unmaximize() {}, maximize() {}, on() {},
  };
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  const electron = { screen: { getDisplayNearestPoint: () => ({ workArea: area, bounds: area }), getDisplayMatching: () => ({ workArea: area, bounds: area }) },
    Menu: { buildFromTemplate(value) { template = value; return { popup() {} }; } } };
  const ipcMain = { handle: (channel, fn) => handlers.set(channel, fn), on() {}, removeListener() {} };
  const module = { exports: {} };
  vm.runInNewContext(read('desktop/pip-window.cjs'), { module, exports: module.exports, require: name => { assert.equal(name, 'electron'); return electron; }, setTimeout, clearTimeout, console });
  module.exports.install({ ipcMain, getWindow: () => window, readConfig: () => cfg, writeConfig: next => { cfg = { ...cfg, ...next }; } });
  const event = { sender: webContents };
  return { native: module.exports, window, sent, cfg: () => cfg, template: () => template, invoke: (name, args) => handlers.get('pip:' + name)(event, args) };
}

test('[pip-free] a layout entry is normalised: shares clamped, scale and opacity bounded, trims kept only when they trim', () => {
  const { preferences } = shell().native;
  const got = preferences({ layout: {
    dialogue: { x: 1.4, y: -.2, w: .5, h: .25, s: 9, o: 0, t: [0, 10, 0, 60] },
    chat: { x: .1, y: .2, t: [0, 0, 0, 0] },
    cast: { s: 1.25 },
    camera: { o: .5 },
    nobody: { x: .5, y: .5 },
    music: 'not an object',
    voices: { s: 'big' },
  } });
  assert.deepEqual(plain(got.layout.dialogue), { x: 1, y: 0, w: .5, h: .25, s: 3, o: .1, t: [0, 10, 0, 45] });
  assert.deepEqual(plain(got.layout.chat), { x: .1, y: .2 }, 'four zero trims are no trims');
  assert.deepEqual(plain(got.layout.cast), { s: 1.25 });
  assert.deepEqual(plain(got.layout.camera), { o: .5 }, 'the camera carries an entry too');
  assert.equal(got.layout.nobody, undefined, 'a name that is no widget is dropped');
  assert.equal(got.layout.music, undefined); assert.equal(got.layout.voices, undefined, 'an entry with nothing usable is no entry');
  assert.deepEqual(plain(preferences({}).layout), {}, 'no entries by default');
  assert.equal(preferences({ musicArtOnly: true }).musicArtOnly, true); assert.equal(preferences({}).musicArtOnly, false);
});

test('[pip-free] update() merges one widget at a time, null removes an entry and a null layout resets them all', () => {
  const h = shell();
  h.invoke('update', { layout: { dialogue: { x: .2, y: .3 }, cast: { s: 1.5 } } });
  h.invoke('update', { layout: { dialogue: { s: .8, t: [5, 0, 0, 0] } } });
  let pip = h.cfg().pip;
  assert.deepEqual(plain(pip.layout.dialogue), { x: .2, y: .3, s: .8, t: [5, 0, 0, 0] }, 'the place stays when the scale changes');
  assert.deepEqual(plain(pip.layout.cast), { s: 1.5 });
  h.invoke('update', { layout: { cast: null } });
  pip = h.cfg().pip; assert.equal(pip.layout.cast, undefined); assert.ok(pip.layout.dialogue);
  h.invoke('update', { layout: { dialogue: { t: [0, 0, 0, 0] } } });
  assert.deepEqual(plain(h.cfg().pip.layout.dialogue), { x: .2, y: .3, s: .8 }, 'trims set to nothing are removed');
  h.invoke('update', { musicArtOnly: true });
  assert.equal(h.cfg().pip.musicArtOnly, true);
  h.invoke('update', { layout: null });
  assert.deepEqual(plain(h.cfg().pip.layout), {});
  const state = h.invoke('state');
  assert.deepEqual(plain(state.layout), {}); assert.equal(state.musicArtOnly, true, 'the published state carries both');
});

test('[pip-free] the menu\'s reset puts every widget back, the player and slate and camera included', () => {
  const h = shell();
  h.invoke('update', { layout: { dialogue: { x: .2, y: .3 } }, musicPosition: { x: .9, y: .9 }, roulettePosition: { x: .7, y: .7 }, musicArtOnly: true, cameraBounds: { x: .1, y: .1 } });
  h.window.__pinePip = true; h.invoke('menu', {});
  const reset = h.template().find(item => item.label === 'Reset widget layout');
  assert.ok(reset, 'the reset is on the menu'); reset.click();
  const pip = h.cfg().pip;
  assert.deepEqual(plain(pip.layout), {}); assert.deepEqual(plain(pip.musicPosition), { x: .03, y: .6 }); assert.deepEqual(plain(pip.roulettePosition), { x: .04, y: .18 });
  assert.equal(pip.musicArtOnly, false); assert.equal(pip.cameraBounds.x, .58);
  const hints = h.template().filter(item => item.enabled === false && /handle/.test(item.label)).map(item => item.label);
  assert.equal(hints.length, 2, 'the menu says how: ' + hints.join(' | '));
  assert.match(hints[0], /anywhere/); assert.match(hints[1], /Ctrl\+wheel/);
});

test('[pip-favorites-az] favorites are listed alphabetically, whatever order they were added in', () => {
  const h = shell({ cfg: { pip: { popupFavorites: ['tool:PineLive', 'tool:ad-viewer', 'tool:AudioMixer', 'tool:album', 'tool:Cam', 'tool:flow-chart', 'tool:Zebra', 'tool:tool 10', 'tool:tool 2'] } } });
  h.window.__pinePip = true; h.invoke('menu', {});
  const favorites = h.template().find(item => item.label === 'Favorites');
  assert.ok(favorites, 'the submenu is there');
  const labels = plain(favorites.submenu.map(item => item.label));
  const sorted = [...labels].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true }));
  assert.deepEqual(labels, sorted, labels.join(' | '));
  assert.ok(labels.indexOf('tool 2') < labels.indexOf('tool 10'), 'numbers sort as numbers');
  assert.equal(labels[0].toLowerCase()[0], 'a', 'case does not decide the order');
});

/* ------------------------------------------------------------------ the export: clip-mux.cjs + screen-ring.cjs + main.js */
test('[pip-export-bar] ffmpeg\'s -progress lines become seconds, across chunk boundaries, in either dialect', () => {
  const clipMux = require(path.join(ROOT, 'desktop', 'clip-mux.cjs'));
  const seen = [];
  const feed = clipMux.progressFeed(seconds => seen.push(seconds));
  feed('frame=12\nfps=0.0\nout_time_us=1500000\nout_time_ms=1500000\nout_time=00:00:01.500000\nprogress=continue\nout_ti');
  feed('me_us=3000000\r\nprogress=continue\r\nout_time_us=N/A\nout_time=00:01:05.25\nprogress=end\n');
  assert.deepEqual(seen, [1.5, 1.5, 1.5, 3, 65.25]);
});

test('[pip-export-bar] run() asks ffmpeg for its clock only when someone listens; encodeVideo passes the listener; the cut turns it into a share', () => {
  const mux = lf(read('desktop/clip-mux.cjs')), ring = lf(read('desktop/screen-ring.cjs'));
  assert.match(mux, /function run\(exe, args, timeoutMs, onProgress\)/);
  assert.match(mux, /const spawnArgs = told \? \['-progress', 'pipe:1', '-nostats', \.\.\.args\] : args;/);
  assert.match(mux, /execFile\(exe, spawnArgs,/);
  assert.match(mux, /worker\.stdout\.on\('data', progressFeed\(told\)\)/);
  assert.match(mux, /await run\(exe, build\(encoder\), \(options \|\| \{\}\)\.timeoutMs \|\| 600000, \(options \|\| \{\}\)\.onProgress\);/);
  assert.match(ring, /onProgress: typeof opts\.onProgress === 'function' \? seconds => opts\.onProgress\(Math\.min\(1, Math\.max\(0, seconds\) \/ total\)\) : undefined/);
});

test('[pip-export-bar] with a real ffmpeg, a short encode reports a rising clock (skipped without ffmpeg)', async t => {
  const clipMux = require(path.join(ROOT, 'desktop', 'clip-mux.cjs'));
  let ffmpeg = '';
  try {
    const found = clipMux.findFfmpeg((JSON.parse(fs.readFileSync(path.join(process.env.APPDATA || '', 'pinebox-desktop', 'pinebox-desktop.json'), 'utf8')) || {}).ffmpeg);
    if (found.found) ffmpeg = found.path;
  } catch (_) { /* no desktop config here */ }
  if (!ffmpeg) { const found = clipMux.findFfmpeg(); if (found.found) ffmpeg = found.path; }
  if (!ffmpeg) { t.skip('no ffmpeg on this machine'); return; }
  const seen = [];
  const out = path.join(require('node:os').tmpdir(), 'pine-progress-' + process.pid + '.mp4');
  try {
    await clipMux.encodeVideo(ffmpeg, encoder => ['-hide_banner', '-nostdin', '-y', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=10', '-t', '2', ...clipMux.encoderArgs(encoder), '-pix_fmt', 'yuv420p', out], { timeoutMs: 60000, onProgress: s => seen.push(s) });
  } finally { try { fs.unlinkSync(out); } catch (_) {} }
  assert.ok(seen.length >= 1, 'the clock was heard: ' + JSON.stringify(seen));
  assert.ok(seen.every((s, i) => i === 0 || s >= seen[i - 1]), 'it only rises');
  assert.ok(seen[seen.length - 1] >= 1.5, 'and reaches the end of the two seconds: ' + seen[seen.length - 1]);
});

test('[pip-export-bar] the export tells its window every step, and the tablet export sweeps', () => {
  const main = lf(read('desktop/main.js')), preload = lf(read('desktop/preload.js'));
  const teller = main.slice(main.indexOf('function replayProgressTeller(sender, want, view) {'), main.indexOf('ipcMain.handle("replay:export"'));
  assert.ok(teller.length > 100, 'the teller is defined before the export');
  const vm2 = require('node:vm');
  const sandbox = {}; vm2.runInNewContext(teller + '\nthis.replayProgressTeller = replayProgressTeller;', sandbox);
  const sent = [];
  const sender = { isDestroyed: () => false, send: (channel, note) => sent.push([channel, note]) };
  const told = sandbox.replayProgressTeller(sender, { view: 'pip', seconds: 60 });
  told.tell('flush', .02); told.tell('encode', .1); told.tell('encode', .101); told.tell('encode', .4); told.tell('done', 1, { seconds: 60 });
  assert.deepEqual(sent.map(([channel]) => channel), ['replay:progress', 'replay:progress', 'replay:progress', 'replay:progress'], 'a step of less than 1% within 400 ms is not repeated');
  assert.deepEqual(sent.map(([, note]) => [note.view, note.stage, note.ratio]), [['pip', 'flush', .02], ['pip', 'encode', .1], ['pip', 'encode', .4], ['pip', 'done', 1]]);
  assert.equal(sent[3][1].seconds, 60);
  const app = sandbox.replayProgressTeller(sender, { audio_only: true }); app.tell('failed', null, { detail: 'no' });
  assert.deepEqual([sent[4][1].view, sent[4][1].audio, sent[4][1].ratio, sent[4][1].detail], ['app', true, null, 'no']);
  sandbox.replayProgressTeller({ isDestroyed: () => true, send() { throw new Error('gone'); } }, {}).tell('flush', 0);   /* a window that has gone is no error */
  const handler = main.slice(main.indexOf('ipcMain.handle("replay:export"'), main.indexOf('/* THE SAME CUT, BUT INTO THE STATION\'S VIDEO EDITOR.'));
  for (const step of ["teller.tell('flush', .02)", "onProgress: share => teller.tell('encode', .05 + share * .85)", "teller.tell('save', .93)", "teller.tell('upload', .96)", "teller.tell('done', 1, { seconds: made.seconds, where })", "teller.tell('failed', null, { detail: error.message })", "teller.tell('failed', null, { detail: made.detail })"]) {
    assert.ok(handler.includes(step), 'the export says: ' + step);
  }
  const tablet = main.slice(main.indexOf("ipcMain.handle('tablet:replay-export'"), main.indexOf('ipcMain.handle("glass:clip"'));
  assert.match(tablet, /replayProgressTeller\(event\.sender, want, 'tablet'\)/); assert.match(tablet, /teller\.tell\('encode', null\)/); assert.match(tablet, /teller\.tell\('done', 1,/);
  assert.match(preload, /onReplayProgress: \(callback\) => ipcRenderer\.on\("replay:progress"/);
});

/* ------------------------------------------------------------------ the camera: pine-pip-camera-recovery.js */
test('[cam-words] the popup says what the station knows, with the networks it does see', () => {
  const { create } = require(path.join(ROOT, 'desktop', 'renderer', 'pine-pip-camera-recovery.js'));
  const words = (doctor, got) => {
    let clock = 1000000; const said = [];
    const controller = create({ now: () => clock, state: () => ({ active: true, cameraOverlay: true, cameraSource: 'pine' }),
      read: async () => got || { state: 'no-link', fresh: true, ssid: 'H88_5c8e8bddfab1', why: 'the join failed', source: {}, stream: { class: '' } },
      doctor: async () => doctor, post: async () => ({ ok: true }), display: async () => {}, picture: () => false, status: value => said.push(value.say) });
    return controller.tick().then(() => { clock += 10000; return controller.tick(); }).then(got => got.say);
  };
  return Promise.all([
    words({ camera: false, stale: false, nearby: 9 }),
    words({ camera: false, stale: false, nearby: 0 }),
    words({ camera: false, stale: false, nearby: 1 }),
    words({ camera: false, stale: false }),
  ]).then(([nine, none, one, unknown]) => {
    assert.match(nine, /^The camera's Wi-Fi \(H88_5c8e8bddfab1\) is not on the air for the Pine Box\. Its adapter sees 9 other networks but not the camera's\./);
    assert.match(nine, /The camera may be on with its Wi-Fi asleep/); assert.match(nine, /Press its Wi-Fi button and wait for the solid green light\./);
    assert.doesNotMatch(nine, /switched off/, 'it no longer declares the camera off');
    assert.match(none, /sees no networks at all right now/);
    assert.match(one, /sees 1 other network but not/);
    assert.doesNotMatch(unknown, /adapter sees/, 'no count, no claim about one');
  });
});

test('[cam-words] the title no longer sits on the text', () => {
  const css = lf(read('desktop/renderer/pine-pip.css'));
  assert.match(css, /\.pip-camera-status \{ position: absolute; left: 0; right: 0; top: 28px; bottom: 0; display: grid; place-content: center; padding: 4px 10px 8px;/);   /* [pip-rec] the later rule: below the title */
});

/* ------------------------------------------------------------------ the page: pine-pip.js */
test('[pip-panel-ready] only a main-frame navigation unreadies the panel; every load end and the entry re-sync it', () => {
  for (const copy of ['desktop/renderer/pine-pip.js', 'app/src/main/assets/pine-views/pine-pip.js']) {
    if (!fs.existsSync(path.join(ROOT, copy))) continue;
    const page = lf(read(copy));
    assert.doesNotMatch(page, /addEventListener\('did-start-loading'/, copy + ': the iframe-fired event is gone');
    assert.match(page, /frame\.addEventListener\('did-start-navigation', e => \{ if \(e\.isMainFrame && !e\.isInPlace\) panelReady = false; \}\);/);
    assert.match(page, /frame\.addEventListener\('did-stop-loading', \(\) => \{ if \(state\?\.active\) syncPanel\(\)/);
    assert.match(page, /if \(next\.active && !was\) confirmPanel\(\);/);
    assert.match(page, /try \{ await frame\.executeJavaScript\('document\.readyState'\); panelReady = true; \} catch \(_\) \{ return; \}/);
    assert.match(page, /art\.addEventListener\('error'/); assert.match(page, /musicArtOnly: !state\?\.musicArtOnly/); assert.match(page, /musicArtPress && now - musicArtPress\.at < 400/);
    assert.match(page, /'musicArtOnly','layout'\]/, 'the station shares the new preferences');
    assert.match(page, /type: 'pine-pip-time', time/); assert.match(page, /heardVideoTime\('panel', e\.args\[0\]\)/); assert.match(page, /heardVideoTime\('shell', e\.data\.time\)/);
    assert.match(page, /api\(\)\.onReplayProgress\?\.\(paintExport\);/);
    assert.ok(/[^\x00-\x7f]/.test(page) === false, copy + ' stays ASCII');
  }
  const relay = lf(read('desktop/renderer/webview-preload.js'));
  assert.match(relay, /ipcRenderer\.sendToHost\('pine-pip-time', t && typeof t === 'object' \? \{ at: Math\.max\(0, Number\(t\.at\) \|\| 0\), dur: Math\.max\(0, Number\(t\.dur\) \|\| 0\), playing: t\.playing === true \} : null\)/);
});
