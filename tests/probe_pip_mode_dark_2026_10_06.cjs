/* Does a saved background mode come out dark? Loads the live station with the runner's files, saves MODE in the
   station origin's storage the way the panel does, applies THEME and TRANSPARENCY from the desk's own config,
   enters PiP, then reports the viz state, every console line from the station frame, and the picture's brightness.
   electron probe_mode_dark.cjs DESKTOP_DIR STATION_URL MODE THEME TRANSPARENCY OUT_PNG */
const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const [desktopArg, station] = process.argv.slice(2); const MODE = process.env.PINE_PROBE_MODE || "", THEME = process.env.PINE_PROBE_THEME || "graphite", TRANSPARENCY = process.env.PINE_PROBE_TRANSPARENCY || "0", OUT = process.env.PINE_PROBE_OUT || "";
const desktop = path.resolve(desktopArg);
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'pine-modedark-')));
app.commandLine.appendSwitch('use-angle', 'swiftshader'); app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(r => setTimeout(r, ms));
setTimeout(() => { console.error('timed out'); process.exit(1); }, 170000);
let win, cfg = {};
const native = require(path.join(desktop, 'pip-window.cjs'));
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: n => (cfg = { ...cfg, ...n }) });
app.whenReady().then(async () => {
  Menu.buildFromTemplate = () => ({ popup() {} });
  cfg = { baseUrl: station, pip: { widgets: { music: true, messages: true, voices: true }, musicArtOnly: true, theme: THEME || 'graphite', transparency: Number(TRANSPARENCY) || 0, aspectMode: 'video', bounds: { x: 60, y: 50, width: 776, height: 430 } } };
  ipcMain.handle('config:read', () => cfg);
  for (const channel of new Set([...fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8').matchAll(/ipcRenderer[.]invoke[(]["']([^"']+)/g)].map(m => m[1]))) {
    try { ipcMain.handle(channel, () => channel === 'backend:log' ? [] : ({ ok: true, rows: [], lines: [], items: [], hosts: [] })); } catch (_) {}
  }
  win = new BrowserWindow({ show: false, frame: false, width: 776, height: 430, webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const frameLog = [];
  win.webContents.on('did-attach-webview', (_e, wc) => wc.on('console-message', e => { frameLog.push('[' + e.level + '] ' + String(e.message).slice(0, 220) + ' @' + String(e.sourceId).split('/').pop().slice(0, 40) + ':' + e.lineNumber); }));
  await win.loadFile(path.join(desktop, 'renderer', 'index.html')); await delay(9000);
  const inFrame = code => win.webContents.executeJavaScript('document.getElementById("controlFrame").executeJavaScript(' + JSON.stringify(code) + ')');
  if (MODE) { console.log('saved mode:', await inFrame('(() => { try { localStorage.setItem("pinePipVizMode", ' + JSON.stringify(MODE) + '); return localStorage.getItem("pinePipVizMode"); } catch (e) { return "no storage: " + e.message; } })()')); }
  win.isVisible = () => true;
  const mark = frameLog.length;
  win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });
  for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50);
  const Q = `JSON.stringify((() => { const h = document.getElementById('pine-pip-panel'); const v = window.PinePipPanel && window.PinePipPanel.viz && window.PinePipPanel.viz(); const bg = h && h.querySelector('.pip-bg'); const c = bg && bg.querySelector('canvas'); return { host: h ? getComputedStyle(h).display : 'none-host', hostBg: h ? getComputedStyle(h).backgroundColor : '', bgDisplay: bg ? bg.style.display : 'none-bg', bgOpacity: bg ? getComputedStyle(bg).opacity : '', canvas: c ? [c.width, c.height, getComputedStyle(c).opacity, getComputedStyle(c).display] : null, viz: !!v, running: v ? v.running : null, mode: v ? v.activeId : null, incoming: v ? v.incoming : null, fps: v ? Math.round(v.fps || 0) : null, quality: v && v.renderer ? v.renderer.quality : null, palette: v && v.palette && v.palette.current ? v.palette.current : null, gl: (() => { try { const g = c && (c.getContext('webgl2') || c.getContext('webgl')); return g ? { err: g.getError(), lost: g.isContextLost() } : 'no gl on canvas'; } catch (e) { return 'err ' + e.message; } })() }; })())`;
  for (let round = 0; round < 3; round++) { await delay(round === 0 ? 3000 : 5000); console.log('t+' + (3 + round * 5) + 's', await inFrame(Q)); }
  const img = await win.webContents.capturePage();
  const bmp = img.toBitmap(), size = img.getSize();
  let sum = 0, bright = 0, n = 0;
  for (let i = 0; i < bmp.length; i += 16) { const l = 0.114 * bmp[i] + 0.587 * bmp[i + 1] + 0.299 * bmp[i + 2]; sum += l; n++; if (l > 40) bright++; }
  console.log('picture', size.width + 'x' + size.height, 'mean luminance', (sum / n).toFixed(1), 'of 255; pixels brighter than 40:', (100 * bright / n).toFixed(1) + '%');
  if (OUT) { fs.writeFileSync(OUT, img.toPNG()); console.log('saved', OUT); }
  console.log('frame console since PiP (' + (frameLog.length - mark) + '):'); frameLog.slice(mark).slice(0, 30).forEach(l => console.log('  ' + l));
  win.destroy(); process.exit(0);
}).catch(e => { console.error(e); process.exit(1); });
