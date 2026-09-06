// Hidden Electron visual smoke with an in-memory station/device bridge.
// No real station request, network display operation or clipboard write.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const out = path.join(os.tmpdir(), 'pine-lcd-ui-smoke');
app.setPath('userData', path.join(out, 'profile'));
app.commandLine.appendSwitch('no-sandbox');
app.whenReady().then(async () => {
  let window;
  try {
    window = new BrowserWindow({show: false, width: 1040, height: 900,
      webPreferences: {contextIsolation: true, nodeIntegration: false, offscreen: true, backgroundThrottling: false}});
    await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<!doctype html><html><body style="margin:0;background:#101419"><button id="lcdBtn">LCD</button></body></html>'));
    await window.webContents.executeJavaScript(String.raw`
      window.lcdSmokeCalls = {frames: 0, controls: 0, favorites: 0, downloads: 0, papers: []};
      window.lcdSmokeState = {config: {host: '', mode: 'paper', speed: 12, autoStart: false}, running: false,
        connected: false, frames: 0, lastAck: 0, log: [{at: Date.now(), kind: 'preview', detail: 'No physical display connected'}],
        firmware: {available: true, networkFlash: false, flashReady: false,
          reason: 'Build matching firmware. USB backs up the current display; Wi-Fi requires an OTA partition.'}};
      window.pineDesktop = {
        lcdState: async () => structuredClone(window.lcdSmokeState),
        lcdConfigure: async (cfg) => {Object.assign(window.lcdSmokeState.config, cfg); return structuredClone(window.lcdSmokeState)},
        lcdFrame: async () => {window.lcdSmokeCalls.frames++; throw new Error('Unexpected physical frame')},
        lcdConnect: async () => {window.lcdSmokeCalls.controls++; throw new Error('Unexpected connect')},
        lcdStart: async () => {window.lcdSmokeCalls.controls++; throw new Error('Unexpected start')},
        get: async (route) => { window.lcdSmokeCalls.papers.push(route); return route === '/api/dj' ? {chat: [
          {id: 'a1', aired: 'stream', who: 'dj', name: 'Tony', text: 'The Gazette says the midnight market has opened beside the old clock tower.'},
          {id: 'a2', aired: 'stream', who: 'cohost', name: 'Skip', text: 'A quiet stall, a copper call — I heard the vendors arguing about the bell.'}
        ]} : route === '/api/paper' ? {latest: '2026-09-06-09', editions: [{id: '2026-09-06-09'}, {id: '2026-09-06-08'}]} : {
          id: '2026-09-06-09', masthead: 'The Pine Box Gazette', articles: [
            {meta: {headline: 'The midnight market finds its voice', deck: 'Residents gather by the clock tower.'},
             body: 'A copper bell sounded across the square as the new stalls opened. The clockmaker told our reporter that every vendor had brought a different story.\n\nA small bakery offered fresh rolls while musicians gathered on the steps. The newspaper will follow the conversations throughout the next hour.'}
          ]}; },
        post: async (route, body) => { if (route !== '/api/dj/saved' || !body.text) throw new Error('Bad favorite request'); window.lcdSmokeCalls.favorites++; return {ok: true}; },
        lcdDownload: async (id) => { if (!id) throw new Error('Missing dialogue ID'); window.lcdSmokeCalls.downloads++; return {ok: true, exact: true, directory: 'C:/Samples'}; },
      }; true;`);
    const code = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'lcd.js'), 'utf8');
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-dialogue.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-frame.js'), 'utf8'));
    await window.webContents.executeJavaScript(code);
    await window.webContents.executeJavaScript("document.getElementById('lcdBtn').click()");
    await new Promise((resolve) => setTimeout(resolve, 1300));
    const first = await window.webContents.executeJavaScript(`({panel: !!document.getElementById('pineLcdPanel'),
      text: document.body.innerText, canvas: !!document.querySelector('#pineLcdPanel canvas'), calls: window.lcdSmokeCalls})`);
    assert.equal(first.panel, true); assert.equal(first.canvas, true);
    assert.match(first.text, /Pine Box LCD/); assert.match(first.text, /Connect \/ test/);
    assert.equal(first.calls.frames, 0); assert.equal(first.calls.controls, 0);
    fs.mkdirSync(out, {recursive: true});
    fs.writeFileSync(path.join(out, 'paper-overlay.png'), (await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript(`const choice = document.querySelector('[aria-label="LCD content"]');
      choice.value = 'dialogue'; choice.dispatchEvent(new Event('change'));`);
    await new Promise((resolve) => setTimeout(resolve, 500));
    fs.writeFileSync(path.join(out, 'dialogue-only.png'), (await window.webContents.capturePage()).toPNG());
    const second = await window.webContents.executeJavaScript('({mode: window.lcdSmokeState.config.mode, calls: window.lcdSmokeCalls})');
    assert.equal(second.mode, 'dialogue'); assert.equal(second.calls.frames, 0);
    await window.webContents.executeJavaScript(`const cv = document.querySelector('#pineLcdPanel canvas'), box = cv.getBoundingClientRect();
      cv.dispatchEvent(new MouseEvent('click', {clientX: box.left + box.width * .5, clientY: box.top + box.height * .35})); true;`);
    await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('#pineLcdPanel button')).find(b => b.textContent === '★ Favorite').click(); true;`);
    await new Promise((resolve) => setTimeout(resolve, 150));
    await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('#pineLcdPanel button')).find(b => b.textContent === '↓ Download').click(); true;`);
    await new Promise((resolve) => setTimeout(resolve, 150));
    await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('#pineLcdPanel button')).find(b => b.textContent.includes('Older issue')).click(); true;`);
    await new Promise((resolve) => setTimeout(resolve, 150));
    const interactions = await window.webContents.executeJavaScript('window.lcdSmokeCalls');
    assert.equal(interactions.favorites, 1); assert.equal(interactions.downloads, 1);
    assert.ok(interactions.papers.includes('/api/paper/2026-09-06-08')); assert.equal(interactions.controls, 0);
    await window.webContents.executeJavaScript(String.raw`
      window.lcdPainted=[];
      const previousPaint=CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.lcdPainted.push(String(text));window.lcdPainted=window.lcdPainted.slice(-500);return previousPaint.call(this,text,...args)};
      const previousGet=window.pineDesktop.get;
      window.pineDesktop.get=async(route)=>route==='/api/dj'?{chat:[],speaking_now:{id:'live-now',name:'Live tester',who:'dj',text:'The turn is visible before the finished transcript exists.',aired:'airing'}}:previousGet(route);
      const liveCanvas=document.querySelector('#pineLcdPanel canvas'),liveRect=liveCanvas.getBoundingClientRect();
      liveCanvas.dispatchEvent(new MouseEvent('click',{clientX:liveRect.left+liveRect.width*.6,clientY:liveRect.top+liveRect.height*.03}));true;`);
    await new Promise((resolve) => setTimeout(resolve, 1400));
    const live = await window.webContents.executeJavaScript('window.lcdPainted');
    assert.ok(live.some((text) => text.includes('Live tester') && text.includes('Playing')));
    assert.ok(live.some((text) => text.includes('The turn is visible')));
    fs.writeFileSync(path.join(out, 'live-dialogue.png'), (await window.webContents.capturePage()).toPNG());
    const rich = await window.webContents.executeJavaScript(`(() => {
      const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 240;
      const ctx = canvas.getContext('2d'), pixels = ctx.createImageData(320, 240);
      let seed = 7; for (let n = 0; n < pixels.data.length; n += 4) {
        for (let c = 0; c < 3; c++) {seed = (Math.imul(seed, 1664525) + 1013904223) | 0; pixels.data[n+c] = seed >>> 24;}
        pixels.data[n+3] = 255;
      } ctx.putImageData(pixels, 0, 0);
      const ordinary = canvas.toDataURL('image/jpeg', .66), adapted = PineLcdFrame.encode(canvas, {board:'cyd_2432s028r',width:320,height:240});
      return {...adapted, ordinaryBytes: atob(ordinary.split(',')[1]).length, width:canvas.width, height:canvas.height};
    })()`);
    assert.ok(rich.ordinaryBytes > rich.budget); assert.ok(rich.bytes <= 12288);
    assert.equal(rich.width, 320); assert.equal(rich.height, 240);
    fs.writeFileSync(path.join(out, 'rich-frame.jpg'), Buffer.from(rich.jpeg.split(',')[1], 'base64'));
    fs.writeFileSync(path.join(out, 'frame-budget.json'), JSON.stringify({...rich, jpeg: undefined}, null, 2));
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ok: true, checks: 18, screenshots: ['paper-overlay.png', 'dialogue-only.png', 'live-dialogue.png'], physicalWrites: 0, richFrameBytes: rich.bytes, frameBudget: rich.budget}, null, 2));
    console.log('LCD UI smoke passed: ' + out);
    window.destroy(); app.quit();
  } catch (error) {
    fs.mkdirSync(out, {recursive: true}); fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ok: false, error: error.stack}));
    console.error(error); if (window) window.destroy(); app.exit(1);
  }
});
