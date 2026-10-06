/* Why is PineViz not in the page? Loads the live station in PiP with the runner's files and reports the bundle
   script tags, every console message in the station frame (unfiltered), and the panel's state over time.
   electron probe_viz_load.cjs DESKTOP_DIR STATION_URL */
const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const desktop = path.resolve(process.argv[2]), station = process.argv[3];
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'pine-vizload-')));
app.commandLine.appendSwitch('use-angle', 'swiftshader'); app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(r => setTimeout(r, ms));
setTimeout(() => { console.error('timed out'); process.exit(1); }, 150000);
let win, cfg = {};
const native = require(path.join(desktop, 'pip-window.cjs'));
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: n => (cfg = { ...cfg, ...n }) });
app.whenReady().then(async () => {
  Menu.buildFromTemplate = () => ({ popup() {} });
  cfg = { baseUrl: station, pip: { widgets: { dialogue: true }, bounds: { x: 60, y: 50, width: 776, height: 430 } } };
  ipcMain.handle('config:read', () => cfg);
  for (const channel of new Set([...fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8').matchAll(/ipcRenderer[.]invoke[(]["']([^"']+)/g)].map(m => m[1]))) {
    try { ipcMain.handle(channel, () => channel === 'backend:log' ? [] : ({ ok: true, rows: [], lines: [], items: [], hosts: [] })); } catch (_) {}
  }
  win = new BrowserWindow({ show: false, frame: false, width: 1400, height: 900, webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const frameLog = [];
  win.webContents.on('did-attach-webview', (_e, wc) => wc.on('console-message', e => { frameLog.push('[' + e.level + '] ' + String(e.message).slice(0, 200) + ' @' + String(e.sourceId).split('/').pop().slice(0, 40) + ':' + e.lineNumber); }));
  await win.loadFile(path.join(desktop, 'renderer', 'index.html')); await delay(9000);
  win.isVisible = () => true;
  const mark = frameLog.length;
  win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });
  for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50);
  const inFrame = code => win.webContents.executeJavaScript('document.getElementById("controlFrame").executeJavaScript(' + JSON.stringify(code) + ')');
  const Q = `JSON.stringify((() => { const h = document.getElementById('pine-pip-panel'); const v = window.PinePipPanel && window.PinePipPanel.viz && window.PinePipPanel.viz(); return { host: h ? getComputedStyle(h).display : 'none-host', pinePip: document.documentElement.classList.contains('pine-pip'), scripts: [...document.scripts].filter(s => /pineviz|three/.test(s.src)).map(s => s.src.split('/').slice(-1)[0].slice(0, 44)), PineViz: !!window.PineViz, THREE: !!window.THREE, viz: !!v, running: v ? v.running : null, mode: v ? v.activeId : null, bgCanvases: h ? h.querySelectorAll('.pip-bg canvas').length : -1, fail: h ? ((h.querySelector('.pip-failure') || {}).textContent || '') : '' }; })())`;
  for (let round = 0; round < 5; round++) {
    await delay(round === 0 ? 2000 : 5000);
    console.log('t+' + (2 + round * 5) + 's', await inFrame(Q));
  }
  console.log('manual mount:', await inFrame(`(() => { try { const P = window.PineViz; if (!P) return 'no PineViz'; const el = document.createElement('div'); el.style.cssText = 'position:fixed;left:0;top:0;width:320px;height:180px;'; document.body.appendChild(el); const v = P.mount(el, { palette: 'pinepip', quality: 'low', keys: false, click: false }); return 'ok mode=' + v.activeId + ' running=' + v.running; } catch (e) { return 'THROW ' + e.message + ' | ' + String(e.stack || '').split('\\n').slice(0, 4).join(' / ').slice(0, 500); } })()`));
  console.log('frame console since PiP (' + (frameLog.length - mark) + '):');
  frameLog.slice(mark).slice(0, 40).forEach(l => console.log('  ' + l));
  win.destroy(); process.exit(0);
}).catch(e => { console.error(e); process.exit(1); });
