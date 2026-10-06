const { BrowserWindow, screen } = require('electron');
const path = require('node:path');

const LIMITS = { master: 1, voice: 2, music: 2, sfx: 2, video: 2, pads: 2 };
function install({ ipcMain, getWindow, isToolsSender }) {
  let popup;
  function owner(event, allowHost = false) {
    const host = getWindow();
    if (isToolsSender?.(event)) return;
    if (popup && !popup.isDestroyed() && event.sender === popup.webContents) return;
    if (allowHost && host && !host.isDestroyed() && event.sender === host.webContents) return;
    throw new Error('Audio mixer request refused.');
  }
  async function levels(values) {
    const host = getWindow();
    if (!host || host.isDestroyed()) throw new Error('The Pine desktop is closed.');
    return host.webContents.executeJavaScript(`(() => {
      const bus = window.pineLevels;
      if (!bus) throw new Error('Station levels are still loading.');
      ${values ? `bus.applyAll(${JSON.stringify(values)});` : ''}
      return bus.get();
    })()`, true);
  }
  function open() {
    if (popup && !popup.isDestroyed()) {
      if (popup.isMinimized()) popup.restore();
      popup.show(); popup.focus(); return { ok: true };
    }
    const host = getWindow();
    const area = screen.getDisplayMatching(host.getBounds()).workArea;
    popup = new BrowserWindow({ title: 'Pine audio mixer', parent: host,
      width: Math.min(440, area.width), height: Math.min(650, area.height),
      minWidth: Math.min(320, area.width), minHeight: Math.min(360, area.height),
      show: false, autoHideMenuBar: true, alwaysOnTop: true, backgroundColor: '#151e23',
      webPreferences: { preload: path.join(__dirname, 'audio-mixer-preload.cjs'),
        contextIsolation: true, sandbox: true, nodeIntegration: false } });
    const current = popup;
    current.setAlwaysOnTop(true, 'floating');
    current.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    current.webContents.on('will-navigate', event => event.preventDefault());
    current.once('ready-to-show', () => { if (!current.isDestroyed()) current.show(); });
    current.on('close',()=>{if(popup===current)popup=null;});
    current.on('closed', () => { if (popup === current) popup = null; });
    current.loadFile(path.join(__dirname, 'renderer', 'audio-mixer.html'));
    return { ok: true };
  }
  ipcMain.handle('audio-mixer:open', event => { owner(event, true); return open(); });
  ipcMain.handle('audio-mixer:get', event => { owner(event); return levels(); });
  ipcMain.handle('audio-mixer:set', (event, values) => {
    owner(event);
    if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error('Invalid levels.');
    for (const [key, value] of Object.entries(values)) {
      if (!Object.hasOwn(LIMITS, key) || !Number.isFinite(value) || value < 0 || value > LIMITS[key]) throw new Error('Invalid level.');
    }
    return levels(values);
  });
  ipcMain.handle('audio-mixer:close', event => { owner(event); popup.close(); });
  return { open };
}
module.exports = { install };
