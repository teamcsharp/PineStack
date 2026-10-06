/* [pip-viz] The living background in a real (hidden, offscreen) shell: the PiP panel loads the bundle from the
 * station, mounts PineViz on its background, a click on it cycles the mode, the menu names one, telemetry
 * reaches it, and leaving PiP stops it. Then the standalone page: every one of the ten modes draws.
 *
 * Run with Electron, on local disk:   electron tests/test_pip_viz_browser_2026_10_05.cjs [SHOT_DIR]
 * Isolated configuration and a local fixture station; never touches the live backend.
 */
const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const desktop = path.join(root, 'desktop');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-pip-viz-'));
const shots = process.argv.find((arg, i) => i > 1 && !arg.startsWith('-') && !arg.endsWith('.cjs')) || '';
if (shots) fs.mkdirSync(shots, { recursive: true });
app.setPath('userData', temp);
app.on('window-all-closed', () => {});
app.commandLine.appendSwitch('use-angle', 'swiftshader'); app.commandLine.appendSwitch('enable-unsafe-swiftshader'); app.commandLine.appendSwitch('ignore-gpu-blocklist');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

let win, server, cfg = {};
const native = require('../desktop/pip-window.cjs');
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: next => (cfg = { ...cfg, ...next }) });
const failTimer = setTimeout(() => { console.error('PiP viz test timed out at step ' + step); process.exit(1); }, 240000);
let step = 'start'; const at = name => { step = name; console.log('.. ' + name); };
const shot = async name => { if (shots && win && !win.isDestroyed()) fs.writeFileSync(path.join(shots, name + '.png'), (await win.webContents.capturePage()).toPNG()); };
const page = code => win.webContents.executeJavaScript(code).catch(error => { console.error('the page script failed: ' + String(code).slice(0, 240)); throw error; });
const inFrame = code => page('document.getElementById("controlFrame").executeJavaScript(' + JSON.stringify(code) + ')');
const key = () => win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });

app.whenReady().then(async () => {
  let template = null; const buildMenu = Menu.buildFromTemplate;
  Menu.buildFromTemplate = t => { template = t; return { popup(options) { setTimeout(() => options.callback && options.callback(), 0); } }; };
  const bundle = fs.readFileSync(path.join(desktop, 'renderer', 'pipviz', 'dist', 'pineviz.bundle.js'));
  let bundleHits = 0;
  server = http.createServer((req, res) => {
    if (req.url.startsWith('/vendor/three.min.js')) { res.setHeader('Content-Type', 'application/javascript'); res.end(fs.readFileSync(path.join(desktop, 'vendor/three.min.js'))); return; }
    if (req.url.startsWith('/vendor/pineviz.bundle.js')) { bundleHits++; res.setHeader('Content-Type', 'application/javascript'); res.end(bundle); return; }
    if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); res.end('{}'); return; }
    res.setHeader('Content-Type', 'text/html');
    res.end('<html><body style="margin:0;background:#123;color:#9ab;font:14px system-ui"><h1 id="panelHead" style="margin:20px">the station panel</h1></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  cfg = { baseUrl: base, pip: { widgets: { dialogue: true }, bounds: { x: 60, y: 50, width: 640, height: 400 } } };
  ipcMain.handle('config:read', () => cfg);
  ipcMain.handle('replay:hold', (_e, seconds) => seconds);
  ipcMain.handle('agent:get', (_e, route) => route.startsWith('/api/voices') ? [] : ({}));
  ipcMain.handle('agent:post', () => ({ ok: true }));
  ipcMain.handle('camera:where', () => ({ ok: false })); ipcMain.handle('camera:pip', () => ({ ok: true }));
  const resource = name => pathToFileURL(path.join(desktop, 'renderer', name)).href;
  const file = path.join(temp, 'fixture.html');
  fs.writeFileSync(file, `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="${resource('pineicons.css')}"><link rel="stylesheet" href="${resource('pine-pip.css')}"></head><body style="margin:0;background:#0b1410;color:#dfe">
    <input id="appVolume" type="range" value="35"><aside id="pineViewRail"></aside>
    <main><h1 style="margin:40px">THE FULL APP</h1><section id="control"><webview id="controlFrame" preload="${resource('webview-preload.js')}" webpreferences="backgroundThrottling=no" src="${base}" style="width:100%;height:500px"></webview></section></main>
    <audio id="desktopRadioPlayer"></audio>
    <script>window.pineThreeUrl=()=>${JSON.stringify(base + '/vendor/three.min.js')};window.desktopMusicUrl=u=>u;window.PineStationFeed={refresh(){},subscribe(fn){window.receivePip=fn;return ()=>window.receivePip=null}};</script>
    <script src="${resource('pine-icons.js')}"></script><script src="${resource('pine-logo.js')}"></script><script src="${resource('pine-vcr.js')}"></script><script src="${resource('system3-message-tile.js')}"></script>
    <script src="${resource('pine-pip-shift.js')}"></script><script src="${resource('pine-pip.js')}"></script></body></html>`);
  win = new BrowserWindow({ show: false, frame: false, x: 40, y: 40, width: 1100, height: 760, minWidth: 520, minHeight: 420, webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const errors = [], frameErrors = [];
  win.webContents.on('console-message', e => { if (e.level === 'error' && !/favicon|ERR_|deprecated|Autofill/i.test(e.message)) errors.push(e.message + ' @' + e.lineNumber); });
  win.webContents.on('did-attach-webview', (_e, wc) => wc.on('console-message', e => { if (e.level === 'error' && !/favicon|ERR_|Autofill/i.test(e.message)) frameErrors.push(String(e.message).slice(0, 200) + ' @' + e.lineNumber); }));
  await win.loadFile(file); await delay(1500);
  win.isVisible = () => true;

  /* ---- 1. PiP: the panel mounts the living background ---- */
  at('enter PiP'); key(); for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50);
  for (let n = 0; n < 80 && (await inFrame('!!(window.PinePipPanel && window.PineViz && document.querySelector("#pine-pip-panel canvas.pineviz-canvas"))')) !== true; n++) await delay(150);
  at('read the mount'); const mounted = await inFrame(`(()=>{const c=document.querySelector('#pine-pip-panel canvas.pineviz-canvas'),r=c&&c.getBoundingClientRect();const got=window.PinePipPanel.background();return JSON.stringify({canvas:!!c,w:r&&Math.round(r.width),h:r&&Math.round(r.height),mode:got.mode,modes:got.modes.length,particles:!!document.querySelector('#pine-pip-panel .pip-bg canvas:not(.pineviz-canvas)')})})()`);
  const m = JSON.parse(mounted);
  assert.equal(m.canvas, true, '[pip-viz] the background canvas is in the panel: ' + mounted);
  assert.equal(m.modes, 11, 'eleven modes: the classic cloud and the ten'); assert.ok(m.mode, 'a mode is active: ' + m.mode);
  assert.ok(m.w >= 600 && m.h >= 380, 'it fills the panel: ' + mounted);
  assert.equal(m.particles, false, 'the old particle cloud gave way');
  assert.equal(bundleHits, 1, 'the bundle came from the station once');
  await delay(1500); await shot('1-pip-background');
  at('click'); /* ---- 2. [viz-dblclick] a double-click on the background cycles; a single click leaves the mode alone ---- */
  const before = JSON.parse(await inFrame('JSON.stringify(window.PinePipPanel.background())')).mode;
  await inFrame(`document.querySelector('#pine-pip-panel canvas.pineviz-canvas').dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 300, clientY: 200 }))`);
  await delay(900);
  assert.equal(JSON.parse(await inFrame('JSON.stringify(window.PinePipPanel.background())')).mode, before, '[viz-dblclick] a single click leaves the background alone');
  await inFrame(`document.querySelector('#pine-pip-panel canvas.pineviz-canvas').dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true, clientX: 300, clientY: 200 }))`);
  await delay(1500);   /* the crossfade takes a second */
  const after = JSON.parse(await inFrame('JSON.stringify(window.PinePipPanel.background())')).mode;
  assert.notEqual(after, before, '[viz-dblclick] a double-click cycles the background: ' + before + ' -> ' + after);
  const order = JSON.parse(await inFrame('JSON.stringify(window.PineViz.modes().map(x => x.id))'));
  assert.equal(after, order[(order.indexOf(before) + 1) % order.length], 'to the next in order');
  assert.equal(win.__pinePip, true, 'still in PiP: the double-click did not expand the window');
  assert.equal(await inFrame('localStorage.getItem("pinePipVizMode")'), after, 'the choice is kept');
  at('menu'); /* ---- 3. the menu names a mode; the shell's action road sets it ---- */
  await page('pineDesktop.pipMenu({})'); await delay(100);
  const bg = template.find(item => item.label === 'Background');
  assert.ok(bg, 'the menu has a Background submenu'); assert.equal(bg.submenu.length, 13, 'next, a separator, and the eleven');
  assert.equal(bg.submenu[0].label, 'Next background (click the background)');
  const sent = []; const send = win.webContents.send.bind(win.webContents); win.webContents.send = (...args) => { sent.push(args); return send(...args); };
  bg.submenu.find(item => /Retro Grid/.test(item.label)).click(); await delay(1600);
  assert.deepEqual(sent[0], ['pip:action', { type: 'background', mode: 'retro-grid' }]);
  assert.equal(JSON.parse(await inFrame('JSON.stringify(window.PinePipPanel.background())')).mode, 'retro-grid', '[pip-viz] the menu set the mode');
  await delay(1200); await shot('3-retro-grid-in-pip');
  /* ---- 4. telemetry from the shell reaches the panel; the external provider is fed ---- */
  at('telemetry'); const quiet = JSON.parse(await inFrame(`JSON.stringify({ speech: window.PinePipPanel.viz().processor.state.speechActivity, running: window.PinePipPanel.viz().running })`));
  assert.equal(quiet.running, true, 'the loop runs in PiP'); assert.ok(quiet.speech < .05, 'nothing said yet: ' + quiet.speech);
  await page(`receivePip({station:{now:{id:'t',title:'x',artist:'y',seconds:100},playing:true,paused:false,elapsed:10,remaining:90},rows:[{id:'l1',name:'Dill',text:'hello there',lcdStatus:'Playing'}],now:{id:'l1',name:'Dill',text:'hello there'}})`);
  await delay(1500);
  const told = JSON.parse(await inFrame(`JSON.stringify({ speech: window.PinePipPanel.viz().processor.state.speechActivity, activity: window.PinePipPanel.viz().processor.state.stationActivity, music: window.PinePipPanel.viz().processor.state.music })`));
  assert.ok(told.speech > .1 && told.activity > .1, '[pip-viz] the station telemetry breathes in the background with no audio at all: ' + JSON.stringify(told));
  at('leave and re-enter'); /* ---- 5. leaving PiP stops the loop; coming back starts it without a rebuild ---- */
  key(); for (let n = 0; n < 60 && win.__pinePip; n++) await delay(50); await delay(2300);
  assert.equal(await inFrame('document.documentElement.classList.contains("pine-pip")'), false);
  assert.equal(await inFrame('window.PinePipPanel.viz().running'), false, 'out of PiP the loop is stopped');
  key(); for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50); await delay(2600);
  assert.equal(bundleHits, 1, 'no second download of the bundle on re-entry');
  assert.equal(JSON.parse(await inFrame('JSON.stringify(window.PinePipPanel.background())')).mode, 'retro-grid', 'the mode survives re-entry');
  assert.equal(await inFrame(`document.querySelectorAll('#pine-pip-panel canvas.pineviz-canvas').length`), 1, 'one canvas, not two');
  assert.deepEqual(frameErrors, [], 'no errors inside the station page'); assert.deepEqual(errors, [], 'no errors in the shell');

  at('standalone page'); /* ---- 6. the standalone page: all ten modes draw, differently ---- */
  const look = new BrowserWindow({ show: false, width: 800, height: 450, webPreferences: { offscreen: true, sandbox: false, backgroundThrottling: false } });
  const lookErrors = []; look.webContents.on('console-message', e => { if (e.level >= 2) lookErrors.push(String(e.message).slice(0, 160)); });
  await look.loadFile(path.join(desktop, 'renderer', 'pipviz', 'index.html'), { query: { demo: 'music', quality: 'medium', bare: '1' } });
  for (let n = 0; n < 60 && (await look.webContents.executeJavaScript('!!(window.pineViz && pineViz.manager.frames > 2)')) !== true; n++) await delay(250);
  await delay(1500);
  const sigs = new Set();
  for (const id of order) {
    await look.webContents.executeJavaScript(`pineViz.manager.set(${JSON.stringify(id)}, { instant: true }); pineViz.manager.frames = 0;`);
    for (let n = 0; n < 40 && (await look.webContents.executeJavaScript('pineViz.manager.frames > 12')) !== true; n++) await delay(100);
    await delay(900);
    const img = await look.webContents.capturePage(); const bmp = img.toBitmap(); let lit = 0, n = 0; const hist = new Array(12).fill(0);
    for (let i = 0; i < bmp.length; i += 4 * 9) { const l = (bmp[i] + bmp[i + 1] + bmp[i + 2]) / 3; n++; if (l > 28) lit++; hist[Math.min(11, Math.floor(l / 22))]++; }
    sigs.add(hist.map(h => Math.round(h / n * 50)).join(','));
    assert.ok(lit / n > .01, id + ' draws something: lit ' + (lit / n * 100).toFixed(1) + '% (frames ' + (await look.webContents.executeJavaScript('pineViz.manager.frames')) + ')');
    if (shots) fs.writeFileSync(path.join(shots, 'mode-' + id + '.png'), img.toPNG());
  }
  assert.ok(sigs.size >= 9, 'the modes look different from one another: ' + sigs.size + ' distinct of 11');
  assert.deepEqual(lookErrors, [], 'no errors on the standalone page');
  look.destroy();

  Menu.buildFromTemplate = buildMenu; clearTimeout(failTimer);
  win.destroy(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  console.log('PinePiP viz: the panel background, click-to-cycle, the menu road, re-entry and the ten modes passed.');
  setImmediate(() => app.quit());
}).catch(error => { console.error('at step ' + step + ':', error); clearTimeout(failTimer); try { server?.close(); } catch (_) {} process.exit(1); });
