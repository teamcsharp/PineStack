/* Every background mode on the live station page, in turn: shader errors, GL error, brightness.
   electron probe_mode_sweep.cjs DESKTOP_DIR STATION_URL   (theme from PINE_PROBE_THEME, default graphite) */
const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const [desktopArg, station] = process.argv.slice(2);
const desktop = path.resolve(desktopArg);
const THEME = process.env.PINE_PROBE_THEME || 'graphite';
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'pine-sweep-')));
app.commandLine.appendSwitch('use-angle', 'swiftshader'); app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(r => setTimeout(r, ms));
setTimeout(() => { console.error('timed out'); process.exit(1); }, 400000);
let win, cfg = {};
const native = require(path.join(desktop, 'pip-window.cjs'));
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: n => (cfg = { ...cfg, ...n }) });
app.whenReady().then(async () => {
  Menu.buildFromTemplate = () => ({ popup() {} });
  cfg = { baseUrl: station, pip: { widgets: { music: true, voices: true }, theme: THEME, transparency: 15, aspectMode: 'video', bounds: { x: 60, y: 50, width: 776, height: 430 } } };
  ipcMain.handle('config:read', () => cfg);
  for (const channel of new Set([...fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8').matchAll(/ipcRenderer[.]invoke[(]["']([^"']+)/g)].map(m => m[1]))) {
    try { ipcMain.handle(channel, () => channel === 'backend:log' ? [] : ({ ok: true, rows: [], lines: [], items: [], hosts: [] })); } catch (_) {}
  }
  win = new BrowserWindow({ show: false, frame: false, width: 776, height: 430, webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const frameLog = [];
  win.webContents.on('did-attach-webview', (_e, wc) => wc.on('console-message', e => { if (e.level >= 2) frameLog.push(String(e.message).slice(0, 160).replace(/\s+/g, ' ')); }));
  await win.loadFile(path.join(desktop, 'renderer', 'index.html')); await delay(9000);
  const inFrame = code => win.webContents.executeJavaScript('document.getElementById("controlFrame").executeJavaScript(' + JSON.stringify(code) + ')');
  win.isVisible = () => true;
  win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });
  for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50);
  await delay(4000);
  const modes = JSON.parse(await inFrame('JSON.stringify((window.PinePipPanel && window.PinePipPanel.background && window.PinePipPanel.background().modes) || [])'));
  console.log('modes:', modes.map(m => m.id || m).join(' '));
  for (const m of modes) {
    const id = m.id || m;
    const mark = frameLog.length;
    await inFrame('window.PinePipPanel.background(' + JSON.stringify(id) + ')');
    await delay(5000);
    const state = await inFrame(`JSON.stringify((() => { const v = window.PinePipPanel.viz(); const c = document.querySelector('#pine-pip-panel .pip-bg canvas'); let gl = null; try { const g = c && (c.getContext('webgl2') || c.getContext('webgl')); gl = g ? g.getError() : 'none'; } catch (e) { gl = 'err'; } return { active: v.activeId, incoming: v.incoming, fps: Math.round(v.fps || 0), gl }; })())`);
    const img = await win.webContents.capturePage(); const bmp = img.toBitmap();
    if (process.env.PINE_PROBE_OUT_DIR) { try { fs.writeFileSync(path.join(process.env.PINE_PROBE_OUT_DIR, 'mode_' + id + '.png'), img.toPNG()); } catch (_) {} }
    let sum = 0, n = 0, sat = 0; for (let i = 0; i < bmp.length; i += 16) { const b = bmp[i], g = bmp[i + 1], r = bmp[i + 2]; sum += 0.114 * b + 0.587 * g + 0.299 * r; sat += Math.max(r, g, b) - Math.min(r, g, b); n++; }
    const colour = (sat / n).toFixed(1);
    const errs = frameLog.slice(mark);
    const shader = errs.filter(l => /Shader Error|INVALID_OPERATION|not compiled/.test(l)).length;
    console.log(id.padEnd(16), state, 'luminance', (sum / n).toFixed(1), 'colour', colour, 'console errors', errs.length, 'shader', shader, errs.length ? '| ' + errs[0].slice(0, 100) : '');
  }
  win.destroy(); process.exit(0);
}).catch(e => { console.error(e); process.exit(1); });
