/* Run with Electron. An isolated fixture; never connects to the station. */
const { app, BrowserWindow, ipcMain } = require('electron');
const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-mixer-test-'));
app.setPath('userData', temp);
let host;
require('../desktop/audio-mixer.cjs').install({ ipcMain, getWindow: () => host });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const timeout = setTimeout(() => { console.error('Mixer test timed out'); app.exit(1); }, 30000);
app.whenReady().then(async () => {
  host = new BrowserWindow({ show: false, width: 320, height: 180,
    webPreferences: { preload: path.resolve(__dirname, '../desktop/preload.js'), contextIsolation: true, sandbox: false } });
  await host.loadURL('data:text/html,<html><body>Fixture</body></html>');
  await host.webContents.executeJavaScript(`window.pineLevels = {
    values: {master:1,voice:1,music:.12,sfx:1,video:1,pads:1},
    get() { return {...this.values}; }, applyAll(v) { Object.assign(this.values, v); }
  }; window.pineDesktop.audioMixerOpen()`);
  const popup = BrowserWindow.getAllWindows().find(w => w !== host);
  assert.ok(popup, 'opens a separate window');
  if (popup.webContents.isLoading()) await new Promise(resolve => popup.webContents.once('did-finish-load', resolve));
  await delay(150);
  assert.equal(await popup.webContents.executeJavaScript(`document.querySelector('#music').value`), '12');
  assert.equal(await popup.webContents.executeJavaScript(`document.querySelectorAll('input[type=range]').length`), 6);
  await popup.webContents.executeJavaScript(`document.querySelector('#voice').value='163'; document.querySelector('#voice').dispatchEvent(new Event('input'));`);
  await delay(100);
  assert.equal(await host.webContents.executeJavaScript('window.pineLevels.get().voice'), 1.63);
  assert.equal(await host.webContents.executeJavaScript('window.pineLevels.get().music'), .12);
  await host.webContents.executeJavaScript('window.pineLevels.applyAll({music:.37})');
  await delay(1100);
  assert.equal(await popup.webContents.executeJavaScript(`document.querySelector('#music').value`), '37', 'follows changes elsewhere');
  assert.equal(await popup.webContents.executeJavaScript(`window.audioMixer.set({master:2}).then(() => false, () => true)`), true);
  await host.webContents.executeJavaScript('window.pineDesktop.audioMixerOpen()');
  assert.equal(BrowserWindow.getAllWindows().length, 2, 'reuses the mixer');
  await popup.webContents.executeJavaScript(`document.querySelector('#reset').click()`);
  await delay(100);
  assert.deepEqual(await host.webContents.executeJavaScript('window.pineLevels.get()'), {master:1,voice:1,music:1,sfx:1,video:1,pads:1});
  await host.webContents.executeJavaScript('window.pineLevels.applyAll({music:.12})');
  await delay(1100);
  fs.writeFileSync(path.join(temp, 'mixer.png'), (await popup.webContents.capturePage()).toPNG());
  console.log('Mixer preview: ' + path.join(temp, 'mixer.png'));
  const closed = new Promise(resolve=>popup.once('closed',resolve));popup.close();await closed;
  await host.webContents.executeJavaScript('window.pineDesktop.audioMixerOpen()');
  const reopened = BrowserWindow.getAllWindows().find(w => w !== host);
  assert.ok(reopened && reopened !== popup, 'reopens after close');
  console.log('PASS: mixer sliders, station sync, boost, reset, validation, reuse and reopen');
  clearTimeout(timeout); app.exit(0);
}).catch(error => { console.error(error); clearTimeout(timeout); app.exit(1); });
