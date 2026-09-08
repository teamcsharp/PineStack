// Explicit hardware test: electron tools/lcd-device-smoke.cjs --host=... --identity=...
// Reads the real station, sends its LCD canvas, and checks both firmware modes.
const {app, BrowserWindow, ipcMain} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const {LcdAgent, deviceRequest} = require('../desktop/lcd-agent.cjs');
const {LcdSerial} = require('../desktop/lcd-serial.cjs');
const argument = (name) => process.argv.find((s) => s.startsWith('--' + name + '='))?.split('=').slice(1).join('=') || '';
const host = argument('host'), identity = argument('identity');
const streamSeconds = Math.min(60, Math.max(0, Number(argument('stream-seconds')) || 0));
const output = path.join(os.tmpdir(), 'pine-lcd-device-smoke');
app.setPath('userData', path.join(output, 'profile'));
// Keep the helper alive until asynchronous device restoration is finished.
app.on('window-all-closed', () => {});
app.whenReady().then(async () => {
  let window; const serial = new LcdSerial(); let agent, originalDevice;
  try {
    if (!host || !identity) throw new Error('An explicit host and expected physical MAC are required.');
    const config = JSON.parse(fs.readFileSync(path.join(app.getPath('appData'), 'pinebox-desktop', 'pinebox-desktop.json'), 'utf8'));
    const get = async (route) => {
      const response = await fetch(config.baseUrl + route, {headers: config.apiKey ? {Authorization: 'Bearer ' + config.apiKey} : {}, signal: AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error('Station HTTP ' + response.status);
      return response.json();
    };
    if (/^COM/.test(host)) await serial.open(host, identity);
    const lcdConfig = {lcd: {host, identity, mode: 'paper', speed: 12,
      chatOverlay: !streamSeconds, pausedCupboard: !streamSeconds, paperStyle: 'broadsheet'}};
    agent = new LcdAgent({read: () => lcdConfig, write: (next) => Object.assign(lcdConfig, next),
      request: (target, ...args) => /^COM/.test(target) ? serial.request(target, ...args) : deviceRequest(target, ...args)});
    const connected = await agent.connect(host, identity);
    originalDevice = {...connected.device};
    assert.equal(connected.device.hostTouch, true);
    const [station, shelf, generations] = await Promise.all([get('/api/dj'), get('/api/paper'), get('/api/generations?limit=1000')]);
    const latest = shelf.latest || shelf.editions?.[0]?.id;
    const issue = latest ? await get('/api/paper/' + encodeURIComponent(latest)) : {articles: []};
    const fixtures = {'/api/dj': station, '/api/paper': shelf, ['/api/paper/' + latest]: issue,
      '/api/generations?limit=1000': generations};
    if (streamSeconds) ipcMain.handle('lcd-smoke', async (_event, name, ...args) => {
      if (name === 'get') return fixtures[args[0]] || {};
      if (name === 'lcdState') return agent.state();
      if (name === 'lcdConfigure') { agent.configure(args[0]); return agent.syncSettings(); }
      if (name === 'lcdFrame') return agent.frame(args[0]);
      if (name === 'lcdEvents') return agent.events();
      if (name === 'lcdControl') return agent.control(...args);
      if (name === 'lcdDisplayMode') return agent.displayMode(args[0]);
      if (name === 'lcdPaperImage') {
        const url = new URL(args[0], config.baseUrl);
        if (url.origin !== new URL(config.baseUrl).origin || !url.pathname.startsWith('/api/')) throw new Error('Unexpected paper image');
        const response = await fetch(url, {headers: config.apiKey ? {Authorization: 'Bearer ' + config.apiKey} : {}, signal: AbortSignal.timeout(10000)});
        if (!response.ok) throw new Error('Image HTTP ' + response.status);
        return 'data:' + response.headers.get('content-type').split(';')[0] + ';base64,' + Buffer.from(await response.arrayBuffer()).toString('base64');
      }
      throw new Error('Unexpected LCD test command');
    });
    window = new BrowserWindow({show: false, width: 1060, height: 980, webPreferences: {offscreen: true, backgroundThrottling: false,
      ...(streamSeconds ? {preload: path.join(__dirname, 'lcd-smoke-preload.cjs')} : {})}});
    await window.loadURL('data:text/html,<html><body style="background:%2307121b"><button id="lcdBtn">LCD</button></body></html>');
    await window.webContents.executeJavaScript('window.lcdFixture=' + JSON.stringify(fixtures) + ';window.lcdFixtureState=' + JSON.stringify(connected) + ';true;');
    if (!streamSeconds) await window.webContents.executeJavaScript(`window.pineDesktop={lcdState:async()=>window.lcdFixtureState,
      get:async(route)=>window.lcdFixture[route]||{},lcdConfigure:async()=>window.lcdFixtureState};true;`);
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-dialogue.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-frame.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-controls.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-gallery.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-review.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd.js'), 'utf8'));
    await window.webContents.executeJavaScript('document.getElementById("lcdBtn").click();true;');
    await new Promise((resolve) => setTimeout(resolve, 900));
    fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, 'live-preview.png'), (await window.webContents.capturePage()).toPNG());
    const jpeg = await window.webContents.executeJavaScript('PineLcdFrame.encode(document.querySelector("#pineLcdPanel canvas"),window.lcdFixtureState.device).jpeg');
    fs.writeFileSync(path.join(output, 'frame.jpg'), Buffer.from(jpeg.split(',')[1], 'base64'));
    await agent.start({automatic: true});
    // Automatic reconnect preserves a remembered avatar view; this explicit
    // hardware test starts in Pine before measuring its renderer.
    await agent.displayMode('pine');
    if (streamSeconds) {
      const until = Date.now() + 12000;
      while (agent.frames < 5 && Date.now() < until) await new Promise(resolve => setTimeout(resolve, 200));
      assert.ok(agent.frames >= 5, 'Renderer did not begin streaming: ' + agent.error);
      const startAt = Date.now(), startFrames = agent.frames, startFailed = agent.failed;
      await new Promise(resolve => setTimeout(resolve, streamSeconds * 1000));
      const seconds = (Date.now() - startAt) / 1000;
      const metrics = await window.webContents.executeJavaScript('window.PineLcdMetrics');
      const timings = agent.timings.slice(), frames = agent.frames - startFrames;
      const measured = {seconds, frames, failures: agent.failed - startFailed, fps: frames / seconds, metrics, timings};
      assert.ok(frames > streamSeconds * 2, 'Scrolling throughput regressed');
      fs.writeFileSync(path.join(output, 'newspaper-last-ack.jpg'), Buffer.from(agent.lastFrame, 'base64'));
      fs.writeFileSync(path.join(output, 'newspaper-stream.png'), (await window.webContents.capturePage()).toPNG());
      // Use real generation metadata and actual authenticated image bytes.
      // All settings here belong only to this temporary producer, never the
      // user's saved desktop configuration.
      const paperSettings = {...agent.config()};
      await window.webContents.executeJavaScript(`const galleryMode=document.querySelector('[aria-label="LCD content"]');galleryMode.value='gallery';galleryMode.dispatchEvent(new Event('change'));
        const galleryDuration=document.querySelector('[aria-label="Gallery image duration"]');galleryDuration.value='3';galleryDuration.dispatchEvent(new Event('change'));true;`);
      const galleryFrames=agent.frames,galleryFailed=agent.failed,galleryStart=Date.now();
      const galleryImages=new Set(),galleryTransitions=new Set();
      while(Date.now()-galleryStart<20000) {
        const frame=await window.webContents.executeJavaScript("({...document.querySelector('canvas').dataset})");
        if(frame.lcdView==='gallery' && frame.lcdGalleryImage)galleryImages.add(frame.lcdGalleryImage);
        if(frame.lcdGalleryTransition)galleryTransitions.add(frame.lcdGalleryTransition);
        await new Promise(resolve=>setTimeout(resolve,250));
      }
      const gallery={seconds:(Date.now()-galleryStart)/1000,frames:agent.frames-galleryFrames,
        failures:agent.failed-galleryFailed,images:[...galleryImages],transitions:[...galleryTransitions]};
      assert.ok(gallery.frames>=15,'Gallery frame streaming stalled: '+JSON.stringify(gallery));
      assert.ok(gallery.images.length>=3,'Real gallery did not rotate distinct images: '+JSON.stringify(gallery));
      assert.ok(gallery.transitions.length>=2,'Gallery did not vary its transitions: '+JSON.stringify(gallery));
      assert.equal(gallery.failures,0);
      fs.writeFileSync(path.join(output,'gallery-last-ack.jpg'),Buffer.from(agent.lastFrame,'base64'));
      fs.writeFileSync(path.join(output,'gallery-stream.png'),(await window.webContents.capturePage()).toPNG());
      agent.configure(paperSettings);
      await new Promise(resolve=>setTimeout(resolve,1400));
      assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdView"),'newspaper');
      const beforeDrawer = agent.frames;
      await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.startsWith('Quick settings')).click();true;`);
      await new Promise(resolve => setTimeout(resolve, 1200));
      assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdDrawer"), 'open');
      assert.ok(agent.frames >= beforeDrawer + 3, 'The drawer did not receive fresh draw acknowledgments');
      fs.writeFileSync(path.join(output, 'drawer-last-ack.jpg'), Buffer.from(agent.lastFrame, 'base64'));
      // The reported failure was the corner switch underneath an open drawer.
      await window.webContents.executeJavaScript(`var cornerCanvas=document.querySelector('canvas'),cornerBounds=cornerCanvas.getBoundingClientRect();cornerCanvas.dispatchEvent(new MouseEvent('click',{clientX:cornerBounds.left+cornerBounds.width*.1,clientY:cornerBounds.top+cornerBounds.height*.12}));true;`);
      await new Promise(resolve => setTimeout(resolve, 1200));
      assert.equal((await agent.probe(host)).displayMode, 'avatar');
      assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdSwap"), 'PB');
      assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdDrawer"), 'closed');
      fs.writeFileSync(path.join(output, 'corner-avatar.png'), (await window.webContents.capturePage()).toPNG());
      await window.webContents.executeJavaScript(`cornerCanvas.dispatchEvent(new MouseEvent('click',{clientX:cornerBounds.left+cornerBounds.width*.1,clientY:cornerBounds.top+cornerBounds.height*.12}));true;`);
      const beforeCornerResume = agent.frames;
      await new Promise(resolve => setTimeout(resolve, 1400));
      assert.equal((await agent.probe(host)).displayMode, 'pine');
      assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdSwap"), 'AV');
      assert.ok(agent.frames >= beforeCornerResume + 3, 'Pine did not resume drawing after the corner switch');
      await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.startsWith('Quick settings')).click();true;`);
      await new Promise(resolve => setTimeout(resolve, 400));
      const beforeTabloid = agent.frames;
      await window.webContents.executeJavaScript(`const mode=document.querySelector('[aria-label="LCD content"]');mode.value='tabloid';mode.dispatchEvent(new Event('change'));Array.from(document.querySelectorAll('button')).find(b=>b.textContent.startsWith('Quick settings')).click();true;`);
      await new Promise(resolve => setTimeout(resolve, 5000));
      assert.equal(agent.config().paperStyle, 'tabloid');
      assert.ok(agent.frames >= beforeTabloid + 3, 'The tabloid did not receive fresh draw acknowledgments');
      fs.writeFileSync(path.join(output, 'tabloid-last-ack.jpg'), Buffer.from(agent.lastFrame, 'base64'));
      await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Preview screensaver').click();true;`);
      await new Promise(resolve => setTimeout(resolve, 1400));
      assert.equal((await agent.probe(host)).screensaver, true);
      await window.webContents.executeJavaScript(`const cv=document.querySelector('canvas'),b=cv.getBoundingClientRect();cv.dispatchEvent(new MouseEvent('click',{clientX:b.left+b.width*.5,clientY:b.top+b.height*.5}));true;`);
      await new Promise(resolve => setTimeout(resolve, 1400));
      assert.equal((await agent.probe(host)).screensaver, false);
      assert.equal(agent.device.displayMode, 'pine');
      agent.configure(paperSettings);
      await new Promise(resolve=>setTimeout(resolve,1200));
      assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdView"),'newspaper');
      const result = {ok: true, at: new Date().toISOString(), host, identity, latestPaper: latest, measured, gallery,
        totalFrames: agent.frames, totalFailures: agent.failed, drawerDrawn: true, tabloidDrawn: true,
        screensaverPreviewAndWake: true, cornerSwitchWithDrawer: true, paperRestored: true, physicalGestureObserved: false};
      fs.writeFileSync(path.join(output, 'renderer-stream-result.json'), JSON.stringify(result, null, 2));
      console.log(JSON.stringify({...result, measured: {...measured, timings: undefined}}));
      return;
    }
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
  } finally {
    if (window) window.destroy();
    agent?.stop();
    if(agent?.device && originalDevice?.pineProtocol>=2) {
      try {
        await agent.control('idle',Number(originalDevice.idleSeconds)||0);
        await agent.displayMode(originalDevice.displayMode==='avatar'?'avatar':'pine');
        if(originalDevice.screensaver)await agent.control('screensaver',true);
        assert.equal(agent.device.displayMode,originalDevice.displayMode==='avatar'?'avatar':'pine');
        assert.equal(agent.device.screensaver,!!originalDevice.screensaver);
        assert.equal(agent.device.idleSeconds,Number(originalDevice.idleSeconds)||0);
        fs.mkdirSync(output,{recursive:true});
        fs.writeFileSync(path.join(output,'restored-device.json'),JSON.stringify({ok:true,
          displayMode:agent.device.displayMode,screensaver:agent.device.screensaver,idleSeconds:agent.device.idleSeconds},null,2));
      } catch(error) {
        process.exitCode=1;
        fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,'restored-device.json'),JSON.stringify({ok:false,error:error.message}));
      }
    } else if(originalDevice) {
      process.exitCode=1;
      fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(output,'restored-device.json'),JSON.stringify({ok:false,error:'Device disconnected before its original state could be restored.'}));
    }
    await serial.close(); app.exit(process.exitCode || 0);
  }
});
