// Explicit hardware test: electron tools/lcd-device-smoke.cjs --host=... --identity=...
// Reads the real station, sends its LCD canvas, and checks both firmware modes.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const {LcdAgent, deviceRequest} = require('../desktop/lcd-agent.cjs');
const {LcdSerial} = require('../desktop/lcd-serial.cjs');
const argument = (name) => process.argv.find((s) => s.startsWith('--' + name + '='))?.split('=').slice(1).join('=') || '';
const host = argument('host'), identity = argument('identity');
const output = path.join(os.tmpdir(), 'pine-lcd-device-smoke');
app.setPath('userData', path.join(output, 'profile'));
app.whenReady().then(async () => {
  let window; const serial = new LcdSerial(); let agent;
  try {
    if (!host || !identity) throw new Error('An explicit host and expected physical MAC are required.');
    const config = JSON.parse(fs.readFileSync(path.join(app.getPath('appData'), 'pinebox-desktop', 'pinebox-desktop.json'), 'utf8'));
    const get = async (route) => {
      const response = await fetch(config.baseUrl + route, {headers: config.apiKey ? {Authorization: 'Bearer ' + config.apiKey} : {}, signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error('Station HTTP ' + response.status);
      return response.json();
    };
    if (/^COM/.test(host)) await serial.open(host, identity);
    const lcdConfig = {lcd: {host, identity, mode: 'paper', speed: 12}};
    agent = new LcdAgent({read: () => lcdConfig, write: (next) => Object.assign(lcdConfig, next),
      request: (target, ...args) => /^COM/.test(target) ? serial.request(target, ...args) : deviceRequest(target, ...args)});
    const connected = await agent.connect(host, identity);
    assert.equal(connected.device.hostTouch, true);
    const [station, shelf] = await Promise.all([get('/api/dj'), get('/api/paper')]);
    const latest = shelf.latest || shelf.editions?.[0]?.id;
    const issue = latest ? await get('/api/paper/' + encodeURIComponent(latest)) : {articles: []};
    const fixtures = {'/api/dj': station, '/api/paper': shelf, ['/api/paper/' + latest]: issue};
    window = new BrowserWindow({show: false, width: 1060, height: 980, webPreferences: {offscreen: true, backgroundThrottling: false}});
    await window.loadURL('data:text/html,<html><body style="background:%2307121b"><button id="lcdBtn">LCD</button></body></html>');
    await window.webContents.executeJavaScript('window.lcdFixture=' + JSON.stringify(fixtures) + ';window.lcdFixtureState=' + JSON.stringify(connected) + ';true;');
    await window.webContents.executeJavaScript(`window.pineDesktop={lcdState:async()=>window.lcdFixtureState,
      get:async(route)=>window.lcdFixture[route]||{},lcdConfigure:async()=>window.lcdFixtureState};true;`);
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-dialogue.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-frame.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd.js'), 'utf8'));
    await window.webContents.executeJavaScript('document.getElementById("lcdBtn").click();true;');
    await new Promise((resolve) => setTimeout(resolve, 900));
    fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, 'live-preview.png'), (await window.webContents.capturePage()).toPNG());
    const jpeg = await window.webContents.executeJavaScript('PineLcdFrame.encode(document.querySelector("#pineLcdPanel canvas"),window.lcdFixtureState.device).jpeg');
    fs.writeFileSync(path.join(output, 'frame.jpg'), Buffer.from(jpeg.split(',')[1], 'base64'));
    await agent.start();
    for (let i = 0; i < 3; i++) { const sent = await agent.frame(jpeg); assert.equal(sent.ok, true, JSON.stringify(sent)); }
    await agent.displayMode('avatar');
    assert.equal((await agent.probe(host)).displayMode, 'avatar');
    const count = agent.frames;
    assert.equal((await agent.frame(jpeg)).avatar, true); assert.equal(agent.frames, count);
    await agent.displayMode('pine');
    assert.equal((await agent.probe(host)).displayMode, 'pine');
    assert.equal((await agent.frame(jpeg)).ok, true);
    const result = {ok: true, at: new Date().toISOString(), host, device: agent.device,
      drawnFrames: agent.frames, avatarModeVerified: true, pineModeVerified: true, latestPaper: latest,
      airedLines: (station.chat || []).filter((row) => ['box','stream','both'].includes(row.aired)).length};
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  } catch (error) {
    fs.mkdirSync(output, {recursive: true}); fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ok: false, error: error.stack, log: agent?.log}, null, 2));
    console.error(error); process.exitCode = 1;
  } finally { agent?.stop(); serial.close(); if (window) window.destroy(); app.exit(process.exitCode || 0); }
});
