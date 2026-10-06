/* What burns while the PiP is up: a CPU profile of the station page and of the shell, in PiP mode, on the LIVE
   station with the runner's own files.   electron profile_pip.cjs DESKTOP_DIR STATION_URL [SECONDS] [--before]
   --before profiles the ordinary desk first (same seconds) so the two can be laid side by side. */
const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const desktop = path.resolve(process.argv[2]), station = process.argv[3];
const SECONDS = Number(process.env.PINE_PROFILE_SECONDS) || 20, BEFORE = process.env.PINE_PROFILE_BEFORE === '1';
app.setPath('userData', fs.mkdtempSync(path.join(os.tmpdir(), 'pine-perf-')));
app.commandLine.appendSwitch('use-angle', 'swiftshader'); app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(r => setTimeout(r, ms));
setTimeout(() => { console.error('timed out'); process.exit(1); }, 420000);
let win, cfg = {}, frameWc = null;
const native = require(path.join(desktop, 'pip-window.cjs'));
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: n => (cfg = { ...cfg, ...n }) });

function aggregate(profile, seconds) {
  const nodes = new Map(profile.nodes.map(n => [n.id, n]));
  const self = new Map(); let total = 0;
  const dts = profile.timeDeltas || [];
  (profile.samples || []).forEach((id, i) => {
    const n = nodes.get(id); if (!n) return;
    const cf = n.callFrame || {}; const dt = dts[i] || 0; total += dt;
    const name = cf.functionName || '(anonymous)';
    const url = (cf.url || '').split('/').slice(-1)[0].split('?')[0] || '(native)';
    if (name === '(idle)' || name === '(program)' || name === '(garbage collector)') { self.set(name, (self.get(name) || 0) + dt); return; }
    const key = url + ' ' + name + ':' + (cf.lineNumber + 1);
    self.set(key, (self.get(key) || 0) + dt);
  });
  const rows = [...self.entries()].sort((a, b) => b[1] - a[1]);
  const idle = self.get('(idle)') || 0;
  const busy = total - idle;
  const out = ['  busy ' + (busy / 1e6).toFixed(2) + ' s of ' + (total / 1e6).toFixed(1) + ' s sampled = ' + (100 * busy / Math.max(1, total)).toFixed(1) + '% of one core'];
  rows.filter(r => r[0] !== '(idle)').slice(0, 28).forEach(([k, us]) => out.push('  ' + (us / 1e3).toFixed(0).padStart(6) + ' ms  ' + k.slice(0, 120)));
  // by file
  const byFile = new Map();
  rows.forEach(([k, us]) => { if (k.startsWith('(')) return; const f = k.split(' ')[0]; byFile.set(f, (byFile.get(f) || 0) + us); });
  out.push('  by file:'); [...byFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).forEach(([f, us]) => out.push('    ' + (us / 1e3).toFixed(0).padStart(6) + ' ms  ' + f));
  return out.join('\n');
}

async function profile(wc, label, seconds) {
  const dbg = wc.debugger;
  try { dbg.attach('1.3'); } catch (e) { console.log(label, 'debugger attach failed:', e.message); return; }
  try {
    await dbg.sendCommand('Performance.enable');
    const m0 = (await dbg.sendCommand('Performance.getMetrics')).metrics;
    await dbg.sendCommand('Profiler.enable');
    await dbg.sendCommand('Profiler.setSamplingInterval', { interval: 1000 });
    await dbg.sendCommand('Profiler.start');
    await delay(seconds * 1000);
    const { profile: prof } = await dbg.sendCommand('Profiler.stop');
    const m1 = (await dbg.sendCommand('Performance.getMetrics')).metrics;
    const pick = (ms, k) => { const r = ms.find(x => x.name === k); return r ? r.value : 0; };
    const d = k => pick(m1, k) - pick(m0, k);
    console.log('== ' + label + ' (' + seconds + ' s) ==');
    console.log('  metrics delta: tasks ' + d('TaskDuration').toFixed(2) + ' s, script ' + d('ScriptDuration').toFixed(2) + ' s, layout ' + d('LayoutDuration').toFixed(2) + ' s (' + d('LayoutCount') + ' layouts), style ' + d('RecalcStyleDuration').toFixed(2) + ' s (' + d('RecalcStyleCount') + ' recalcs); heap ' + (pick(m1, 'JSHeapUsedSize') / 1048576).toFixed(0) + ' MB; DOM nodes ' + pick(m1, 'Nodes') + '; listeners ' + pick(m1, 'JSEventListeners') + '; media ' + pick(m1, 'MediaKeySessions'));
    console.log(aggregate(prof, seconds));
  } catch (e) { console.log(label, 'profile failed:', e.message); }
  try { dbg.detach(); } catch (_) {}
}

const CENSUS = `JSON.stringify((() => {
  const res = performance.getEntriesByType('resource');
  const now = performance.now();
  const recent = res.filter(r => now - r.startTime < 60000);
  const byPath = {};
  recent.forEach(r => { const p = (r.name.split('?')[0].split('/').slice(3).join('/') || '/').slice(0, 60); byPath[p] = (byPath[p] || 0) + 1; });
  const top = Object.entries(byPath).sort((a, b) => b[1] - a[1]).slice(0, 14);
  const media = [...document.querySelectorAll('video,audio')].map(m => ({ t: m.tagName[0], id: (m.id || m.className || '').slice(0, 24), playing: !m.paused && !m.ended, muted: m.muted, vol: Math.round(m.volume * 100) / 100, loop: m.loop, hidden: !m.offsetParent, w: m.videoWidth || 0, src: (m.currentSrc || '').split('/').slice(-1)[0].slice(0, 28) }));
  const pinePip = document.documentElement.classList.contains('pine-pip') || (document.body && document.body.classList.contains('pine-pip'));
  return { url: location.pathname, pinePip, nodes: document.querySelectorAll('*').length, hiddenTop: [...(document.body ? document.body.children : [])].filter(e => getComputedStyle(e).display === 'none').length, topChildren: document.body ? document.body.children.length : 0, animations: document.getAnimations ? document.getAnimations().length : -1, fetchPerMin: recent.length, topFetches: top, media, heapMB: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : -1 };
})())`;

app.whenReady().then(async () => {
  Menu.buildFromTemplate = () => ({ popup() {} });
  cfg = { baseUrl: station, pip: { widgets: { dialogue: true }, bounds: { x: 60, y: 50, width: 776, height: 430 } } };
  ipcMain.handle('config:read', () => cfg);
  for (const channel of new Set([...fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8').matchAll(/ipcRenderer[.]invoke[(]["']([^"']+)/g)].map(m => m[1]))) {
    try { ipcMain.handle(channel, () => channel === 'backend:log' ? [] : ({ ok: true, rows: [], lines: [], items: [], hosts: [] })); } catch (_) {}
  }
  win = new BrowserWindow({ show: false, frame: false, width: 1400, height: 900, webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  win.webContents.on('did-attach-webview', (_e, wc) => { if (!frameWc) frameWc = wc; });
  await win.loadFile(path.join(desktop, 'renderer', 'index.html')); await delay(12000);
  win.isVisible = () => true;
  const inFrame = code => win.webContents.executeJavaScript('document.getElementById("controlFrame").executeJavaScript(' + JSON.stringify(code) + ')');
  if (BEFORE) {
    console.log('-- ordinary desk --');
    console.log('station census:', await inFrame(CENSUS));
    console.log('shell census:', await win.webContents.executeJavaScript(CENSUS));
    if (frameWc) await profile(frameWc, 'station page, ordinary desk', SECONDS);
    await profile(win.webContents, 'shell, ordinary desk', SECONDS);
  }
  win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });
  for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50);
  await delay(8000);
  console.log('-- PiP --');
  console.log('station census:', await inFrame(CENSUS));
  console.log('shell census:', await win.webContents.executeJavaScript(CENSUS));
  if (frameWc) await profile(frameWc, 'station page, PiP', SECONDS); else console.log('no webview webContents seen');
  await profile(win.webContents, 'shell, PiP', SECONDS);
  win.destroy(); process.exit(0);
}).catch(e => { console.error(e); process.exit(1); });
