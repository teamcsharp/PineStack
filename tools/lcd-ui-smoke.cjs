// Hidden Electron visual smoke with an in-memory station/device bridge.
// No real station request, network display operation or clipboard write.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const strictAssert = require('node:assert/strict');
let checks = 0;
const assert = new Proxy(strictAssert, {get(target, key) {
  return typeof target[key] === 'function' ? (...args) => {checks++;return target[key](...args);} : target[key];
}});
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
      window.lcdSmokeCalls = {frames: 0, controls: 0, favorites: 0, downloads: 0, papers: [], settings: [], modes: [], images: []};
      window.lcdGalleryPictures = ['#b33d37','#3877bb','#4a9e58','#b68a2d'].map((color,index)=>{
        const image=document.createElement('canvas');image.width=360+index*30;image.height=260+index*20;
        const paint=image.getContext('2d');paint.fillStyle=color;paint.fillRect(0,0,image.width,image.height);
        paint.fillStyle='#f8efdc';paint.fillRect(20+index*8,30,100,80);paint.font='bold 38px sans-serif';
        paint.fillText('IMAGE '+(index+1),25,190);return image.toDataURL('image/png');
      });
      window.lcdSmokeState = {config: {host: '', mode: 'paper', speed: 12, autoStart: false, galleryIntervalSeconds: 8}, running: false,
        connected: false, frames: 0, lastAck: 0,
        device: {width:320,height:240,hostTouch:true,pineProtocol:2,displayMode:'pine',board:'cyd_2432s028r',version:49,identity:'fixture'},
        log: [{at: Date.now(), kind: 'preview', detail: 'No physical display connected'}],
        firmware: {available: true, networkFlash: false, flashReady: false,
          reason: 'Build matching firmware. USB backs up the current display; Wi-Fi requires an OTA partition.'}};
      window.pineDesktop = {
        lcdState: async () => structuredClone(window.lcdSmokeState),
        lcdConfigure: async (cfg) => {window.lcdSmokeCalls.settings.push(cfg); Object.assign(window.lcdSmokeState.config, cfg); return structuredClone(window.lcdSmokeState)},
        lcdDisplayMode: async (mode) => { window.lcdSmokeCalls.modes.push(mode); window.lcdSmokeState.device = {...window.lcdSmokeState.device, displayMode: mode, screensaver: false}; return structuredClone(window.lcdSmokeState); },
        lcdControl: async (action, value) => { if (action !== 'screensaver') throw new Error('Unexpected control'); window.lcdSmokeState.device = {...window.lcdSmokeState.device, screensaver: !!value, displayMode: value ? 'avatar' : 'pine'}; return structuredClone(window.lcdSmokeState); },
        lcdFrame: async () => {window.lcdSmokeCalls.frames++; throw new Error('Unexpected physical frame')},
        lcdConnect: async () => {window.lcdSmokeCalls.controls++; throw new Error('Unexpected connect')},
        lcdStart: async () => {window.lcdSmokeCalls.controls++; throw new Error('Unexpected start')},
        lcdPaperImage: async (url) => {window.lcdSmokeCalls.images.push(url);const match=String(url).match(/gallery-smoke-(\d)\.png/);if(!match)throw new Error('Excluded image requested: '+url);return window.lcdGalleryPictures[Number(match[1])-1];},
        get: async (route) => { window.lcdSmokeCalls.papers.push(route); return route === '/api/generations?limit=1000' ? {generations: [
          ...window.lcdGalleryPictures.map((_,i)=>({id:'gallery-'+i,status:'done',files:['gallery-smoke-'+(i+1)+'.png'],model:'fixture',kind:'image'})),
          {status:'done',files:['gazette-paper.png'],model:'gazette',kind:'paper'},
          {status:'done',files:['scene.mp4'],model:'video',kind:'video'}
        ]} : route === '/api/dj' ? {chat: [
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
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-controls.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-gallery.js'), 'utf8'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, '../desktop/renderer/lcd-review.js'), 'utf8'));
    await window.webContents.executeJavaScript(code);
    await window.webContents.executeJavaScript("document.getElementById('lcdBtn').click()");
    await new Promise((resolve) => setTimeout(resolve, 1300));
    const first = await window.webContents.executeJavaScript(`({panel: !!document.getElementById('pineLcdPanel'),
      text: document.body.innerText, canvas: !!document.querySelector('#pineLcdPanel canvas'), calls: window.lcdSmokeCalls})`);
    assert.equal(first.panel, true); assert.equal(first.canvas, true);
    assert.match(first.text, /Pine Box LCD/); assert.match(first.text, /Connect \/ test/);
    assert.equal(first.calls.frames, 0); assert.equal(first.calls.controls, 0);
    assert.deepEqual(await window.webContents.executeJavaScript("[...document.querySelector('[aria-label=\"LCD content\"]').options].map(o=>o.value)"),
      ['newspaper','paper','tabloid','gallery','dialogue','cupboard']);
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
    // Top-edge swipe, eight touch controls, timer persistence and consumed wake.
    await window.webContents.executeJavaScript(String.raw`
      window.lcdClickAt = (x, y) => {const cv=document.querySelector('#pineLcdPanel canvas'),b=cv.getBoundingClientRect(); cv.dispatchEvent(new MouseEvent('click',{clientX:b.left+b.width*x/320,clientY:b.top+b.height*y/240}));};
      window.lcdSwipe = () => {const cv=document.querySelector('#pineLcdPanel canvas'),b=cv.getBoundingClientRect();
        for(const [type,y] of [['pointerdown',8],['pointerup',85]])cv.dispatchEvent(new PointerEvent(type,{pointerId:7,clientX:b.left+b.width*.4,clientY:b.top+b.height*y/240}));};
      window.lcdSwipe(); true;`);
    await new Promise(resolve => setTimeout(resolve, 550));
    assert.equal(await window.webContents.executeJavaScript("document.querySelector('#pineLcdPanel canvas').dataset.lcdDrawer"), 'open');
    await window.webContents.executeJavaScript('window.lcdClickAt(78,114); true;');
    await new Promise(resolve => setTimeout(resolve, 80));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.config.chatOverlay'), true);
    await window.webContents.executeJavaScript('window.lcdClickAt(78,150); true;');
    await new Promise(resolve => setTimeout(resolve, 80));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.config.chatOverlay'), false);
    await window.webContents.executeJavaScript('window.lcdClickAt(238,114); true;');
    await new Promise(resolve => setTimeout(resolve, 80));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.config.paperStyle'), 'tabloid');
    await window.webContents.executeJavaScript('window.lcdClickAt(238,186); true;');
    await new Promise(resolve => setTimeout(resolve, 80));
    await window.webContents.executeJavaScript('window.lcdClickAt(80,222); true;');
    await new Promise(resolve => setTimeout(resolve, 80));
    const settings = await window.webContents.executeJavaScript('window.lcdSmokeState.config');
    assert.equal(settings.screensaverEnabled, true); assert.equal(settings.screensaverSeconds, 900);
    fs.writeFileSync(path.join(out, 'quick-settings.png'), (await window.webContents.capturePage()).toPNG());
    // The drawer used to swallow this exact corner tap, and redraw its title
    // over the switch. It must remain visible and send just one mode command.
    assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdSwap"), 'AV');
    await window.webContents.executeJavaScript('window.lcdClickAt(32,28); true;');
    await new Promise(resolve => setTimeout(resolve, 240));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.device.displayMode'), 'avatar');
    assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdDrawer"), 'closed');
    assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdSwap"), 'PB');
    fs.writeFileSync(path.join(out, 'corner-avatar.png'), (await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript('window.lcdClickAt(32,28); true;');
    await new Promise(resolve => setTimeout(resolve, 240));
    assert.deepEqual(await window.webContents.executeJavaScript('window.lcdSmokeCalls.modes'), ['avatar','pine']);
    assert.equal(await window.webContents.executeJavaScript("document.querySelector('canvas').dataset.lcdSwap"), 'AV');
    await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.startsWith('Quick settings')).click();true;`);
    await new Promise(resolve => setTimeout(resolve, 80));
    await window.webContents.executeJavaScript('window.lcdClickAt(275,222); true;');
    await new Promise(resolve => setTimeout(resolve, 150));
    fs.writeFileSync(path.join(out, 'tabloid.png'), (await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript(`Array.from(document.querySelectorAll('#pineLcdPanel button')).find(b=>b.textContent==='Preview screensaver').click(); true;`);
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.device.screensaver'), true);
    await window.webContents.executeJavaScript('window.lcdClickAt(110,190); true;');
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.device.screensaver'), false);
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeCalls.favorites'), 1);
    await window.webContents.executeJavaScript(`const newsChoice=document.querySelector('[aria-label="LCD content"]');newsChoice.value='newspaper';newsChoice.dispatchEvent(new Event('change'));true;`);
    await new Promise(resolve => setTimeout(resolve, 150));
    fs.writeFileSync(path.join(out, 'newspaper.png'), (await window.webContents.capturePage()).toPNG());
    // Pure newspaper and picture gallery are separate views; cycling never
    // silently enables the live transcript over a picture.
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.config.chatOverlay'), false);
    const waitGallery = async () => {
      const until=Date.now()+6000;let observed;
      do {
        observed=await window.webContents.executeJavaScript("({...document.querySelector('#pineLcdPanel canvas').dataset})");
        if(observed.lcdGalleryImage && observed.lcdGalleryState==='ready')return observed;
        await new Promise(resolve=>setTimeout(resolve,80));
      } while(Date.now()<until);
      throw new Error('Gallery did not draw decoded images: '+JSON.stringify(observed));
    };
    await window.webContents.executeJavaScript(String.raw`
      window.lcdPainted=[];window.lcdImagePaints=0;
      const originalImagePaint=CanvasRenderingContext2D.prototype.drawImage;
      CanvasRenderingContext2D.prototype.drawImage=function(...args){window.lcdImagePaints++;return originalImagePaint.apply(this,args)};
      Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Cycle newspaper / gallery').click();true;`);
    let galleryFirst=await waitGallery();
    assert.equal(galleryFirst.lcdView,'gallery');
    const galleryImages=new Set([galleryFirst.lcdGalleryImage]),galleryTransitions=new Set();
    for(let i=0;i<2;i++) {
      await window.webContents.executeJavaScript("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Next gallery image').click();true;");
      await new Promise(resolve=>setTimeout(resolve,200));
      const moving=await window.webContents.executeJavaScript("({...document.querySelector('canvas').dataset})");
      if(moving.lcdGalleryTransition)galleryTransitions.add(moving.lcdGalleryTransition);
      await new Promise(resolve=>setTimeout(resolve,1300));
      const changed=await waitGallery();galleryImages.add(changed.lcdGalleryImage);
    }
    assert.ok(galleryImages.size>=3,JSON.stringify([...galleryImages]));
    assert.ok(galleryTransitions.size>=2,JSON.stringify([...galleryTransitions]));
    const galleryPaint=await window.webContents.executeJavaScript('({text:window.lcdPainted,images:window.lcdImagePaints,requests:window.lcdSmokeCalls.images})');
    assert.ok(galleryPaint.images>2);
    assert.equal(galleryPaint.text.some(text=>/Gazette|midnight market|Live tester|The turn is visible/.test(text)),false);
    assert.equal(galleryPaint.requests.some(url=>/gazette|\.mp4/i.test(url)),false);
    const duration=await window.webContents.executeJavaScript(`(()=>{const menu=document.querySelector('[aria-label="Gallery image duration"]');const before=menu.value;menu.value='3';menu.dispatchEvent(new Event('change'));return {before,values:[...menu.options].map(o=>o.value)};})()`);
    assert.equal(duration.before,'8');assert.deepEqual(duration.values,['3','5','8','15','30','60']);
    await new Promise(resolve=>setTimeout(resolve,100));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.config.galleryIntervalSeconds'),3);
    await window.webContents.executeJavaScript('window.lcdSmokeState.config.galleryIntervalSeconds=11;true;');
    await new Promise(resolve=>setTimeout(resolve,1300));
    assert.equal(await window.webContents.executeJavaScript("document.querySelector('[aria-label=\"Gallery image duration\"]').value"),'11');
    await window.webContents.executeJavaScript("const restoredDuration=document.querySelector('[aria-label=\"Gallery image duration\"]');restoredDuration.value='3';restoredDuration.dispatchEvent(new Event('change'));true;");
    await new Promise(resolve=>setTimeout(resolve,100));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.config.galleryIntervalSeconds'),3);
    assert.equal(await window.webContents.executeJavaScript("[...document.querySelectorAll('[data-lcd-paper-action]')].every(button=>button.hidden)"),true);
    fs.writeFileSync(path.join(out,'gallery.png'),(await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.startsWith('Quick settings')).click();true;");
    await new Promise(resolve=>setTimeout(resolve,150));
    const galleryDrawer=await window.webContents.executeJavaScript("({...document.querySelector('canvas').dataset})");
    assert.equal(galleryDrawer.lcdDrawer,'open');assert.equal(galleryDrawer.lcdSwap,'AV');
    await window.webContents.executeJavaScript('window.lcdClickAt(32,28);true;');
    await new Promise(resolve=>setTimeout(resolve,150));
    assert.equal(await window.webContents.executeJavaScript('window.lcdSmokeState.device.displayMode'),'avatar');
    await window.webContents.executeJavaScript('window.lcdClickAt(32,28);true;');
    await new Promise(resolve=>setTimeout(resolve,150));
    await window.webContents.executeJavaScript("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Cycle newspaper / gallery').click();true;");
    await new Promise(resolve=>setTimeout(resolve,200));
    const cycled=await window.webContents.executeJavaScript("({view:document.querySelector('canvas').dataset.lcdView,config:window.lcdSmokeState.config})");
    assert.equal(cycled.view,'newspaper');assert.equal(cycled.config.chatOverlay,false);
    assert.equal(await window.webContents.executeJavaScript("[...document.querySelectorAll('[data-lcd-paper-action]')].every(button=>!button.hidden)"),true);
    const rich = await window.webContents.executeJavaScript(`(() => {
      const canvas = document.createElement('canvas'); canvas.width = 320; canvas.height = 240;
      const ctx = canvas.getContext('2d'), pixels = ctx.createImageData(320, 240);
      let seed = 7; for (let n = 0; n < pixels.data.length; n += 4) {
        for (let c = 0; c < 3; c++) {seed = (Math.imul(seed, 1664525) + 1013904223) | 0; pixels.data[n+c] = seed >>> 24;}
        pixels.data[n+3] = 255;
      } ctx.putImageData(pixels, 0, 0);
      const ordinary = canvas.toDataURL('image/jpeg', .66), adapted = PineLcdFrame.encode(canvas, {board:'cyd_2432s028r',width:320,height:240});
      const next = PineLcdFrame.encode(canvas, {board:'cyd_2432s028r',width:320,height:240});
      return {...adapted, repeatedEncodes: next.encodes, ordinaryBytes: atob(ordinary.split(',')[1]).length, width:canvas.width, height:canvas.height};
    })()`);
    assert.ok(rich.ordinaryBytes > rich.budget); assert.ok(rich.bytes <= 12288);
    assert.equal(rich.width, 320); assert.equal(rich.height, 240);
    assert.equal(rich.repeatedEncodes, 1);
    fs.writeFileSync(path.join(out, 'rich-frame.jpg'), Buffer.from(rich.jpeg.split(',')[1], 'base64'));
    fs.writeFileSync(path.join(out, 'frame-budget.json'), JSON.stringify({...rich, jpeg: undefined}, null, 2));
    // A simulated 120ms draw ACK must not acquire the former extra 200ms sleep.
    await window.webContents.executeJavaScript(String.raw`
      window.lcdAckTimes=[];window.lcdInFlight=0;window.lcdMaxInFlight=0;
      Object.assign(window.lcdSmokeState,{running:true,connected:true,device:{width:320,height:240,pineProtocol:2,hostTouch:true,displayMode:'pine'}});
      window.pineDesktop.lcdEvents=async()=>({events:[]});
      window.pineDesktop.lcdFrame=async()=>{window.lcdInFlight++;window.lcdMaxInFlight=Math.max(window.lcdMaxInFlight,window.lcdInFlight);
        await new Promise(r=>setTimeout(r,120));window.lcdInFlight--;window.lcdAckTimes.push(performance.now());return {ok:true};};true;`);
    await new Promise(resolve => setTimeout(resolve, 2700));
    const pacing = await window.webContents.executeJavaScript(`(()=>{const times=window.lcdAckTimes;return {frames:times.length,maxInFlight:window.lcdMaxInFlight,averageMs:(times.at(-1)-times[0])/(times.length-1)};})()`);
    assert.ok(pacing.frames >= 9, JSON.stringify(pacing)); assert.equal(pacing.maxInFlight, 1); assert.ok(pacing.averageMs < 180, JSON.stringify(pacing));
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ok: true, checks, screenshots: ['paper-overlay.png', 'dialogue-only.png', 'live-dialogue.png', 'quick-settings.png', 'corner-avatar.png', 'tabloid.png', 'newspaper.png','gallery.png'], physicalWrites: 0, richFrameBytes: rich.bytes, frameBudget: rich.budget, pacing,
      gallery:{images:[...galleryImages],transitions:[...galleryTransitions],imageDraws:galleryPaint.images,overlayAbsent:true,cycling:true,drawerCorner:true}}, null, 2));
    console.log('LCD UI smoke passed: ' + out);
    window.destroy(); app.quit();
  } catch (error) {
    fs.mkdirSync(out, {recursive: true}); fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify({ok: false, error: error.stack}));
    console.error(error); if (window) window.destroy(); app.exit(1);
  }
});
