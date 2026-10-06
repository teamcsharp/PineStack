/* Run with Electron. Isolated configuration, generated silent video streams,
 * local fixture station; never connects to or writes to the live backend. */
const { app, BrowserWindow, ipcMain, Menu, nativeImage } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
const desktop = path.join(root, 'desktop');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-pip-test-'));
app.setPath('userData', temp);
app.on('window-all-closed', () => {}); // keep the test alive between fixture and full-shell windows
app.commandLine.appendSwitch('use-angle', 'swiftshader');
app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
let win, server, cfg = {}, posts = [];
let cameraLive = true, cameraMjpeg = false;
const cameraReading = () => ({ state: cameraLive ? 'live' : 'no-link', fresh: cameraLive, ts: cameraMjpeg ? { ok: true, port: server.address().port, url: cfg.baseUrl + '/live.ts' } : null });
const troubleRenderer = path.join(temp, 'troubleshooter'); fs.mkdirSync(troubleRenderer);
for (const name of ['station-troubleshooter.html', 'station-troubleshooter.css', 'station-troubleshooter.js']) fs.copyFileSync(path.join(desktop, 'renderer', name), path.join(troubleRenderer, name));
const stationTroubleshooter = require('../desktop/station-troubleshooter.cjs').install({ ipcMain, getWindow: () => win, rendererDir: troubleRenderer,
  request: async (route, body) => {
    if (route === '/api/pinelink/state') return cameraReading();
    if (route === '/api/pinelink/doctor') return { camera: 'fixture-camera', cure: 'connect', verdict: 'Reconnect the fixture camera', steps: ['Camera found'] };
    if (route === '/api/pinelink/connect' && body) { cameraLive = true; return { ok: true, say: 'Fixture camera reconnected' }; }
    if (route === '/api/tablet/look') return { fetching: true, adb_port_open: true, verdict: 'Fixture tablet connected' };
    return { ok: true, say: 'Fixture check passed' };
  } });
const native = require('../desktop/pip-window.cjs');
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: next => (cfg = { ...cfg, ...next }), troubleshoot: () => stationTroubleshooter.open() });
app.on('web-contents-created', (_event, contents) => contents.on('console-message', event => {
  if (event.level === 'error') console.error('Renderer: ' + event.message + ' @ ' + event.sourceId + ':' + event.lineNumber);
}));
const failTimer = setTimeout(() => { console.error('PiP test timed out'); app.exit(1); }, 240000);
app.whenReady().then(async () => {
  let menuTemplate, menuClosed, menuBuilds = 0; const buildMenu = Menu.buildFromTemplate;
  Menu.buildFromTemplate = template => { menuBuilds++; menuTemplate = template; return { popup(options) { menuClosed = options.callback; } }; };
  const defaults = native.preferences(null);
  assert.equal(defaults.aspectMode, 'video'); assert.equal(defaults.widgets.voices, false); assert.equal(defaults.widgets.dialogue, true); assert.equal(defaults.alwaysOnTop, true);
  assert.equal(defaults.theme, 'pine'); assert.equal(defaults.transparency, 15);
  assert.deepEqual(defaults.messageTile,{mode:'hold',fontSize:12,opacity:.85,rollSpeed:1,typingSpeed:1,followPlayback:true,fadeDelay:4});
  assert.equal(native.preferences({widgets:{roulette:true}}).widgets.messages,true,'legacy roulette migrates to shared tile');
  assert.equal(native.preferences({widgets:{roulette:true}}).widgets.roulette,false);
  assert.equal(native.preferences({messageTile:{fontSize:99,opacity:-1,mode:'bad'}}).messageTile.fontSize,28);
  assert.equal(native.preferences({messageTile:{opacity:-1}}).messageTile.opacity,0);
  assert.equal(native.preferences({ theme: 'invalid', transparency: Infinity }).theme, 'pine');
  assert.equal(native.preferences({ transparency: -20 }).transparency, 0);
  assert.equal(native.preferences({ transparency: 120 }).transparency, 90);
  assert.equal(native.preferences({ widgets: { music: 'invalid' }, docks: { audit: 'left' } }).widgets.music, false);
  const fit = native.fitBounds({ x: 99999, y: -900, side: 800 }, { x: 0, y: 0, width: 1000, height: 700 }, [16, 39]);
  assert.equal(fit.width, 816); assert.equal(fit.height, 700); assert.ok(fit.y >= 0 && fit.x + fit.width <= 1000);
  const wide = native.fitBounds({ width: 800, height: 450 }, { x: 0, y: 0, width: 1000, height: 700 }, [0, 0]);
  assert.ok(Math.abs(wide.width / wide.height - 16 / 9) < .01);
  const tiny = native.fitBounds({ side: 800 }, { x: 0, y: 0, width: 120, height: 70 }); assert.ok(tiny.width <= 120 && tiny.height <= 70);
  server = http.createServer((req, res) => {
    if (req.url.startsWith('/live.mjpg')) {
      const frame = nativeImage.createFromBitmap(Buffer.from([30, 100, 50, 255, 30, 100, 50, 255, 30, 100, 50, 255, 30, 100, 50, 255]), { width: 2, height: 2 }).toJPEG(80);
      res.setHeader('Content-Type', 'multipart/x-mixed-replace; boundary=pineframe');
      const paint = () => { res.write('--pineframe\r\nContent-Type: image/jpeg\r\nContent-Length: ' + frame.length + '\r\n\r\n'); res.write(frame); res.write('\r\n'); };
      paint(); const timer = setInterval(paint, 40); res.on('close', () => clearInterval(timer)); return;
    }
    if (req.url.startsWith('/api/pinelink/frame.jpg') || req.url.startsWith('/api/generations/image/')) { res.setHeader('Content-Type', 'image/png'); res.end(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1sAAAAASUVORK5CYII=', 'base64')); return; }
    if (req.url === '/vendor/three.min.js') { res.setHeader('Content-Type', 'application/javascript'); res.end(fs.readFileSync(path.join(root, 'app/src/main/assets/vendor/three.min.js'))); return; }
    if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); res.end('{}'); return; }
    res.setHeader('Content-Type', 'text/html');
    res.end('<html><body style="margin:0;background:#123"><video id="panelVideo" muted playsinline style="width:240px;height:160px"></video><script>window.startVideo=async function(id,color,width=240,height=160){const c=document.createElement("canvas");c.width=width;c.height=height;const ctx=c.getContext("2d");ctx.fillStyle=color;ctx.fillRect(0,0,width,height);const v=document.getElementById(id);v.srcObject=c.captureStream(30);v.muted=true;await v.play();window.videoPaint=setInterval(()=>{ctx.fillStyle=color;ctx.fillRect(0,0,width,height)},33);return true;};</script></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  cfg = { baseUrl: base, pip: { widgets: { dialogue: true, music: true, chat: true, audit: true, production: true, task: true } } };
  ipcMain.handle('config:read', () => cfg);
  ipcMain.handle('replay:hold', (_e, seconds) => { cfg.replayHoldSeconds = seconds; return seconds; });
  ipcMain.handle('replay:export', (_e, want) => { posts.push({ route: 'replay:export', want }); return { ok: true, seconds: want.seconds, where: '/recordings/test.' + (want.audio_only ? 'wav' : 'mp4'), audio: { present: true, complete: true } }; });
  let tabletFacing = 'rear', tabletCameraOpen = false;
  const tabletCameraReading = () => ({ ok: tabletCameraOpen, running: tabletCameraOpen, facing: tabletFacing, frames: 100, sinceFrameMs: 50, stream: base + '/live.mjpg', still: base + '/api/pinelink/frame.jpg' });
  ipcMain.handle('camera:pip', (_e, want) => { posts.push({ route: 'camera:pip', want }); if (want.off) { tabletCameraOpen = false; return { ok: true }; } tabletCameraOpen = true; tabletFacing = want.facing; return tabletCameraReading(); });
  ipcMain.handle('camera:where', tabletCameraReading);
  ipcMain.handle('mirror:show', () => { posts.push({ route: 'mirror:show' }); return { ok: true }; });
  ipcMain.handle('glass:clip', (_e, seconds, options) => { posts.push({ route: 'glass:clip', seconds, options }); return { ok: true }; });
  let holdVideoMode=true, releaseVideoMode;
  ipcMain.handle('agent:get', (_e, route) => {
    if(route==='/api/sfx/video/mode' && holdVideoMode)return new Promise(resolve=>{releaseVideoMode=resolve;});
    if (route === '/api/pinelink/state') return cameraReading();
    if (route.startsWith('/api/voices')) return [];
    if (route.startsWith('/api/system3/line')) return {decisions:[
      {family:'GRAPH',event_id:'reply',selected:{table:'Reply target',label:'Host'},stages:[{stage:'item',selected:'host',draw:{dice:64},candidates:[{id:'host',label:'Host'},{id:'skip',label:'Skip'}]}]},
      {family:'ES',event_id:'emotion',selected:{table:'ES1',label:'uncertainty'},stages:[
        {stage:'category',selected:'interest',draw:{dice:80},candidates:[{id:'joy',label:'JOY',weight:1},{id:'interest',label:'INTEREST',weight:3}]},
        {stage:'item',selected:'uncertain',draw:{dice:95},candidates:[{id:'certain',label:'certainty'},{id:'uncertain',label:'uncertainty'}]}]},
      {family:'RS',event_id:'response',selected:{table:'RS1',label:'Opposite'},stages:[{stage:'item',selected:'opposite',draw:{dice:13},candidates:[{id:'agree',label:'Agree'},{id:'opposite',label:'Opposite'}]}]}
    ]};
    if (route.startsWith('/api/production/feed')) return { cursor: { s3: 1, n: 1, t: 1 }, items: [
      { id: 'roll-one', at: 1, type: 'roll', rows: [{ table: 'Speaker', main: { dice: 88, label: 'Skip', opts: ['Host', 'Skip'], hit: 1 }, losers: [{ label: 'Host' }] }] },
      { id: 'bank-one', at: 2, type: 'stage', stage: 'banked', text: 'Dialogue recorded and banked', shelf: 3 },
      { id: 'emotion-one', at: 3, type: 'emote', speaker: 'Host', shaped: true, text: 'Emotion engine shaped this line' }
    ] };
    if (route.startsWith('/api/dj/flow')) return { events: [{ at: 1, node: 'recording', summary: 'Host line recorded' }] };
    return {};
  });
  ipcMain.handle('agent:post', (_e, route, body) => { posts.push({ route, body }); return { ok: true }; });
  const file = path.join(temp, 'fixture.html');
  const resource = name => pathToFileURL(path.join(desktop, 'renderer', name)).href;
  fs.writeFileSync(file, `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="${resource('script-page.css')}"><link rel="stylesheet" href="${resource('pine-pip.css')}"></head><body style="margin:0;background:#07140f">
    <input id="appVolume" type="range" value="35" oninput="window.testVolume=this.value"><aside id="techRail"></aside><aside id="pineViewRail"></aside><main><section id="control"><webview id="controlFrame" webpreferences="backgroundThrottling=no" src="${base}" preload="${pathToFileURL(path.join(desktop, 'renderer/webview-preload.js')).href}" style="width:100%;height:800px"></webview></section></main>
    <video id="shellVideo" muted playsinline></video><audio id="desktopRadioPlayer"></audio>
    <script>window.pineThreeUrl=()=>${JSON.stringify(base + '/vendor/three.min.js')};window.desktopMusicUrl=u=>u;window.fixtureClock=Date.now();window.PineStationFeed={clock:()=>window.fixtureClock,subscribe(fn){window.receivePip=fn;return ()=>window.receivePip=null}};</script>
    <link rel="stylesheet" href="${resource('pine-levels.css')}"><script>window.testLevels={master:1,music:1,voice:1,sfx:1,video:1,pads:1};window.pineLevels={get:()=>testLevels,apply:(k,v)=>testLevels[k]=v};</script>
    <script src="${resource('pine-levels.js')}"></script><script src="${resource('pine-logo.js')}"></script><script src="${resource('pine-vcr.js')}"></script><script src="${resource('system3-message-tile.js')}"></script><script src="${resource('script-page.js')}"></script><script src="${resource('pine-pip.js')}"></script><script src="${resource('pine-pip-camera-recovery.js')}"></script></body></html>`);
  win = new BrowserWindow({ show: false, frame: false, width: 1100, height: 800, minWidth: 520, minHeight: 420,
    webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const errors = [];
  win.webContents.on('console-message', event => { if (event.level === 'error' && !/favicon|ERR|deprecated/i.test(event.message)) errors.push(event.message); });
  await win.loadFile(file); await delay(1000);
  console.log('Fixture loaded');
  const full = win.getBounds();
  await win.webContents.executeJavaScript('PinePip.enter()'); await delay(1200);
  for(let n=0;n<30&&!win.isAlwaysOnTop();n++)await delay(100);
  console.log('PiP entered'); assert.equal(win.isAlwaysOnTop(), true);
  assert.equal(cfg.pip.enabled, true, 'PiP survives a repair or application relaunch');
  const mixer = await win.webContents.executeJavaScript(`(()=>{const s=PineLevels.open(),r=s.getBoundingClientRect(),input=s.querySelector('input[aria-label="Master"]');input.value=25;input.dispatchEvent(new Event('input'));document.body.classList.add('pine-pip-ui-hidden');const top=document.elementFromPoint(r.left+20,r.top+20),out={fits:r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth,onTop:s.contains(top),visible:getComputedStyle(s).display!=='none',master:testLevels.master};document.body.classList.remove('pine-pip-ui-hidden');PineLevels.close();return out})()`);
  assert.deepEqual(mixer,{fits:true,onTop:true,visible:true,master:.25},'mixer remains visible, usable and inside compact bounds with overlays hidden');

  const menuStarted=performance.now();
  await win.webContents.executeJavaScript("document.getElementById('pinePipWidgets').dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,cancelable:true}))");
  for(let n=0;n<20&&!menuBuilds;n++)await delay(10);
  const menuMs=performance.now()-menuStarted;
  assert.equal(menuBuilds,1,'right-click opens even while the station settings request is stalled');
  assert.ok(menuMs<500,'right-click response stays under 500 ms');
  console.log('Right-click with stalled backend: '+Math.round(menuMs)+' ms');
  menuClosed();menuBuilds=0;holdVideoMode=false;releaseVideoMode?.({on:true,seamless:true});
  await win.webContents.executeJavaScript('pineDesktop.pipMenu()');
  await win.webContents.executeJavaScript('pineDesktop.pipMenu()');
  assert.equal(menuBuilds, 1, 'duplicate menu requests leave the open native menu intact');
  menuClosed();
  await win.webContents.executeJavaScript('pineDesktop.pipMenu()');
  assert.equal(menuBuilds, 2, 'menu can reopen after dismissal'); menuClosed();
  assert.ok(!menuTemplate.some(item => /Match video aspect|crop to fill/.test(item.label))); 
  assert.ok(menuTemplate.some(item => /tablet recording time range/.test(item.label)));
  assert.ok(menuTemplate.some(item => item.label === 'Voice bubbles + falling peaks'));

  const tileToggle=menuTemplate.find(item=>item.label==='System3 message tile');assert.ok(tileToggle);tileToggle.click();await delay(100);
  assert.ok(menuTemplate.some(item=>item.label==='System3 message tile options'));
  assert.deepEqual(menuTemplate.find(item=>item.label==='System3 message tile options').submenu.filter(item=>item.type==='radio').map(item=>[item.label,item.checked]),[['Hold until the next message',true],['Fade after a delay',false],['Keep a scrolling history',false]]);
  await win.webContents.executeJavaScript("pineDesktop.pipUpdate({messageTile:{rollSpeed:4,typingSpeed:3,fontSize:13},messageBounds:{width:.56,height:.78},widgets:{music:false}})");await delay(100);   /* [pip-music] the free player steps off the enlarged tile (its text and votes are still checked below) */
  assert.equal(cfg.pip.messageTile.followPlayback,true,'partial settings retain playback pause behavior');
  await win.webContents.executeJavaScript("pineDesktop.pipUpdate({messageTile:{opacity:.9}})");await delay(100);
  assert.equal(cfg.pip.messageTile.fontSize,13,'partial updates retain configured text size');

  const stableCore=await win.webContents.executeJavaScript('('+ (function(){
    const host=document.createElement('div');Object.assign(host.style,{position:'fixed',left:'0px',top:'0px',width:'480px',height:'650px',overflow:'auto',visibility:'hidden'});document.querySelector('#pinePipWidgets').appendChild(host);
    const core=PineSystem3MessageTile.createRenderer(),rows=[
      {fam:'ES',table:'ES1',main:{dice:80,label:'INTEREST',opts:['JOY','INTEREST'],hit:1},sub:{dice:95,label:'uncertainty',opts:['certainty','uncertainty'],hit:1}},
      {fam:'RS',table:'RS1',main:{dice:13,label:'Opposite',opts:['Agree','Opposite'],hit:1}}
    ],sheet=core.sheet({},rows,6000);host.appendChild(sheet.box);
    const first=sheet.tables[0],next=sheet.tables[1],failures=[],saved=new Map();
    function geometry(element){const a=host.getBoundingClientRect(),b=element.getBoundingClientRect(),c=getComputedStyle(element);return {left:b.left-a.left,top:b.top-a.top+host.scrollTop,width:b.width,height:b.height,font:c.fontSize,transform:c.transform};}
    function remember(step){for(const element of [step.el,step.die,step.wheel,step.of])saved.set(element,geometry(element));}
    function compare(label){for(const [element,old] of saved){const now=geometry(element);for(const key of ['left','top','width','height'])if(Math.abs(now[key]-old[key])>1.1)failures.push(label+': '+element.className+' '+key+' '+old[key]+' -> '+now[key]);if(now.font!==old.font)failures.push(label+': font changed');if(!sheet.box.contains(element))failures.push(label+': original node removed');}}
    core.at(sheet,first.dIn+first.dDie+1);remember(first.cat);
    core.at(sheet,first.dIn+first.dDie+first.dSpin+1);compare('category lands');
    const subStart=first.dIn+first.dDie+first.dSpin+first.dPop;
    core.at(sheet,subStart+first.dDie2+1);remember(first.sub);compare('subcategory rolls');
    core.at(sheet,first.end);compare('subcategory lands');
    core.at(sheet,next.at+next.dIn+next.dDie+1);compare('next category');
    core.at(sheet,sheet.rolled);compare('results');
    const tables=[...sheet.tables],schedule=tables.map(t=>[t.at,t.end]),appendAt=sheet.total+200;
    core.append(sheet,[{fam:'SFX',table:'book',main:{dice:60,label:'sample',opts:['other','sample'],hit:1}}],{appendAt},3000);
    core.at(sheet,appendAt+1);compare('late moment append');
    const same=tables.every((t,i)=>sheet.tables[i]===t)&&schedule.every((v,i)=>v[0]===sheet.tables[i].at&&v[1]===sheet.tables[i].end);
    core.at(sheet,sheet.rolled);compare('appended result');
    const summary=sheet.box.querySelectorAll('.sp-rr-line,.folded').length,subIndent=first.sub.el.getBoundingClientRect().left-first.cat.el.getBoundingClientRect().left;
    host.remove();return {failures,same,summary,subIndent,count:saved.size};
  }).toString()+')()');
  assert.deepEqual(stableCore.failures,[],'styled category and subcategory keep their exact reel boxes and positions');
  assert.equal(stableCore.same,true,'late moment append keeps the existing table objects and timing');
  assert.equal(stableCore.summary,0);assert.ok(stableCore.subIndent>=18);assert.equal(stableCore.count,8);
  await win.webContents.executeJavaScript("window.tilePayload={station:{},rows:[{id:'digital-a',who:'host',name:'Dill',text:'A complete Digital message with its own bubble. '.repeat(16)},{id:'digital-b',who:'cohost',name:'Billy Badass',text:'Each item unfolds as a separate message.'}],now:{}};receivePip(tilePayload);receivePip(tilePayload)");
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.pip-system3-message').length"),0,'history and production events do not create on-air tiles');
  await win.webContents.executeJavaScript("window.tileNow=tilePayload.rows[0];tileNow.from=0;tileNow.until=8;window.tileEpoch=fixtureClock/1000;tilePayload={...tilePayload,now:tileNow,station:{stream_now:{at:tileEpoch,rows:[tileNow]}}};receivePip(tilePayload);receivePip(tilePayload);window.initialTyped=PinePip.messageTile().typed");
  assert.equal(await win.webContents.executeJavaScript("initialTyped"),1,'the first character appears immediately even at zero clip progress');

  await win.webContents.executeJavaScript('('+ (function(){
    const box=document.querySelector('.pip-messages'),stage=box.querySelector('.pip-system3-stage');
    window.stableTileCheck={failures:[],saved:new Map(),samples:0,baseline:null,running:true};
    const check=stableTileCheck;
    function frame(){
      if(!check.running)return;
      const state=PinePip.messageTile(),r=box.getBoundingClientRect(),s=stage.getBoundingClientRect(),rolls=box.querySelector('.pip-system3-rolls'),rollRect=rolls.getBoundingClientRect(),scale=Number(getComputedStyle(stage).getPropertyValue('--pip-message-scale'))||1,g=state.geometry;
      if(g&&state.current==='digital-a'&&state.phase!=='loading'){
        if(!check.baseline)check.baseline={left:r.left,top:r.top,width:r.width,wrapWidth:g.wrapWidth,font:getComputedStyle(box).fontSize};
        for(const k of ['left','top','width'])if(Math.abs(r[k]-check.baseline[k])>1.1)check.failures.push('host '+k+' changed while content grew');
        if(g.scale!==1||getComputedStyle(stage).transform!=='none')check.failures.push('host automatically scaled the item');
        for(const step of box.querySelectorAll('.sp-rr-step')){
          if(getComputedStyle(step).display==='none')continue;
          for(const element of [step,...step.children]){
            if(!element.matches('.sp-rr-step,.sp-rr-die,.sp-rr-wheel,.sp-rr-of'))continue;
            const e=element.getBoundingClientRect(),style=getComputedStyle(element);
            const now={left:e.left-s.left,top:e.top-rollRect.top+rolls.scrollTop*scale,width:e.width,height:e.height,font:style.fontSize,transform:style.transform};
            const old=check.saved.get(element);
            if(old){for(const k of ['left','top','width','height'])if(Math.abs(now[k]-old[k])>1.1)check.failures.push(element.className+' '+k+' changed '+old[k]+' -> '+now[k]);if(now.font!==old.font||now.transform!==old.transform)check.failures.push(element.className+' font/transform changed');if(!box.contains(element))check.failures.push('original row removed');}
            else check.saved.set(element,now);
          }
        }
        for(const element of check.saved.keys())if(!box.contains(element))check.failures.push('prior row replaced');
        check.samples++;
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }).toString()+')()');
  for(let n=0;n<90;n++){if(await win.webContents.executeJavaScript("PinePip.messageTile().phase!=='loading'&&PinePip.messageTile().typed>1"))break;await delay(60);}
  const tile=await win.webContents.executeJavaScript("(()=>{const box=document.querySelector('.pip-messages'),r=box.getBoundingClientRect();return {state:PinePip.messageTile(),cards:box.querySelectorAll('.pip-system3-message').length,tables:box.querySelectorAll('.sp-rr-t').length,subentries:box.querySelectorAll('.sp-rr-sub').length,visible:getComputedStyle(box).display,contained:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,webviews:document.querySelectorAll('webview').length,scriptMounted:!!document.querySelector('.sp-page')};})()");
  assert.notEqual(tile.visible,'none');assert.equal(tile.cards,1);assert.equal(tile.tables,3);assert.equal(tile.subentries,1);assert.ok(tile.state.typed>0,'typing proceeds while clip progress remains zero');assert.equal(tile.contained,true);assert.equal(tile.webviews,1);assert.equal(tile.scriptMounted,false);
  const assertBareTile=async()=>{
    const geometry=await win.webContents.executeJavaScript('('+ (function(){
      const box=document.querySelector('.pip-messages'),stage=box.querySelector('.pip-system3-stage');
      const item=stage.querySelector('.pip-system3-message'),words=item.querySelector('.pip-system3-words'),rolls=item.querySelector('.pip-system3-rolls');
      const rect=element=>{const r=element.getBoundingClientRect();return {left:r.left,top:r.top,right:r.right,bottom:r.bottom,width:r.width,height:r.height};};
      const pane=element=>({...rect(element),scrollTop:element.scrollTop,scrollHeight:element.scrollHeight,clientHeight:element.clientHeight,overflowY:getComputedStyle(element).overflowY});
      const r=rect(box),style=getComputedStyle(box),scroll=getComputedStyle(stage),bar=getComputedStyle(stage,'::-webkit-scrollbar');
      const range=document.createRange();range.selectNodeContents(words);
      return {box:r,item:rect(item),stage:rect(stage),words:pane(words),rolls:pane(rolls),
        scrollTop:stage.scrollTop,scrollHeight:stage.scrollHeight,clientHeight:stage.clientHeight,natural:PinePip.messageTile().geometry,
        controls:box.querySelectorAll('header,.pip-messages-body,button:not(.pip-system3-previous):not(.pip-system3-next)').length,
        navigation:Array.from(box.querySelectorAll('.pip-system3-navigation button')).map(button=>button.getAttribute('aria-label')),
        headerFirst:item.firstElementChild===words,
        edges:Array.from(box.querySelectorAll('.pip-messages-edge')).map(e=>({tag:e.tagName,text:e.textContent,background:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderWidth,after:getComputedStyle(e,'::after').content})),
        padding:style.padding,border:style.borderWidth,background:style.backgroundColor,scrollbar:scroll.scrollbarWidth,barDisplay:bar.display,barWidth:bar.width,clipY:scroll.overflowY,
        wordRects:Array.from(range.getClientRects()).map(t=>({left:t.left,top:t.top,right:t.right,bottom:t.bottom})),
        inside:r.left>=-1&&r.top>=-1&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1};
    }).toString()+')()');
    assert.equal(geometry.controls,0,'bare feed item has no unrelated header, buttons, body frame, or wrapper controls');
    assert.deepEqual(geometry.navigation,['Previous message','Next message'],'the existing history arrows remain the only tile controls');
    assert.equal(geometry.headerFirst,true,'the typewriter header precedes recorded roulette results');
    assert.equal(geometry.edges.length,8,'resize targets are invisible spans at the edges and corners');
    assert.ok(geometry.edges.every(e=>e.tag==='SPAN'&&!e.text&&e.background==='rgba(0, 0, 0, 0)'&&e.border==='0px'&&(!e.after||e.after==='none'||e.after==='normal')),'edge targets draw no visible chrome');
    assert.equal(geometry.padding,'0px');assert.equal(geometry.border,'0px');assert.equal(geometry.background,'rgba(0, 0, 0, 0)');
    for(const edge of ['left','right'])assert.ok(Math.abs(geometry.box[edge]-geometry.item[edge])<=1.1,'wrapper '+edge+' follows the actual message width');
    for(const edge of ['left','top','right','bottom'])assert.ok(Math.abs(geometry.box[edge]-geometry.stage[edge])<=1.1,'stage '+edge+' adds no empty frame space');
    assert.equal(geometry.natural.scale,1,'content growth never changes configured scale');
    if(!geometry.natural.scrolling)for(const edge of ['top','bottom'])assert.ok(Math.abs(geometry.box[edge]-geometry.item[edge])<=1.1,'uncapped wrapper follows the actual item '+edge);
    assert.equal(geometry.scrollbar,'none','active tile has no native scrollbar');assert.ok(geometry.barDisplay==='none'||geometry.barWidth==='0px','active tile has no WebKit scrollbar');
    assert.ok(geometry.inside,'the growth viewport stays inside the existing PiP window');
    assert.equal(geometry.clipY,'hidden','the live stage never scrolls the message as a whole');
    assert.equal(geometry.scrollTop,0,'independent pane scrolling leaves the stage at its anchored position');
    assert.equal(geometry.words.overflowY,'auto');assert.equal(geometry.rolls.overflowY,'auto');
    assert.ok(geometry.words.bottom<=geometry.rolls.top+1,'the text viewport stays above the roulette viewport');
    assert.ok(geometry.wordRects.every(r=>r.left>=geometry.box.left-1&&r.right<=geometry.box.right+1),'configured width wraps all typed text');
    if(geometry.wordRects.length){const tail=geometry.wordRects.at(-1);assert.ok(tail.top>=geometry.words.top-1&&tail.bottom<=geometry.words.bottom+1,'the newest typed line stays inside its independent text viewport');}
    return geometry;
  };
  await assertBareTile();
  const beforeClockJump=await win.webContents.executeJavaScript("PinePip.messageTile().typed");
  await win.webContents.executeJavaScript("fixtureClock=(tileEpoch+4)*1000;receivePip(tilePayload)");await delay(450);
  const afterClockJump=await win.webContents.executeJavaScript("PinePip.messageTile().typed");
  assert.ok(afterClockJump>beforeClockJump,'typing advances with elapsed time');
  assert.ok(afterClockJump-beforeClockJump<150,'jumping the clip clock never jumps the typed prefix');
  await delay(300);assert.ok(await win.webContents.executeJavaScript("PinePip.messageTile().typed")>afterClockJump,'typing continues at the configured speed while the clip clock is frozen');
  const unfolding=await win.webContents.executeJavaScript("document.querySelector('.pip-system3-rolls').textContent");assert.match(unfolding,/Reply target.*Host/);assert.match(unfolding,/ES1.*INTEREST.*uncertainty/);assert.match(unfolding,/RS1.*Opposite/);
  const halfwayGeometry=await assertBareTile();
  const tileCrop={x:Math.floor(halfwayGeometry.box.left),y:Math.floor(halfwayGeometry.box.top),width:Math.ceil(halfwayGeometry.box.width),height:Math.ceil(halfwayGeometry.box.height)};
  fs.writeFileSync(path.join(root,'work/system3-message-tile-preview.png'),(await win.webContents.capturePage()).toPNG());
  await win.webContents.executeJavaScript("document.querySelectorAll('#pinePipWidgets > *').forEach(n=>{if(!n.classList.contains('pip-messages'))n.style.visibility='hidden'})");
  fs.writeFileSync(path.join(root,'work/system3-message-tile-bare-preview.png'),(await win.webContents.capturePage(tileCrop)).toPNG());
  await win.webContents.executeJavaScript("document.querySelectorAll('#pinePipWidgets > *').forEach(n=>n.style.visibility='')");
  console.log('Bare System3 tile preview: '+path.join(root,'work/system3-message-tile-bare-preview.png'));
  menuTemplate.find(item=>item.label==='System3 message tile options').submenu.find(item=>item.label==='Configure text, opacity and animation...').click();await delay(100);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-message-settings input[name=typingSpeed]').disabled"),false,'typing speed remains available when playback pause is enabled');
  await win.webContents.executeJavaScript("document.querySelector('.pip-message-settings button').click()");

  await win.webContents.executeJavaScript("receivePip({...tilePayload,station:{...tilePayload.station,paused:true}})");await delay(100);
  const pausedTyped=await win.webContents.executeJavaScript("PinePip.messageTile().typed");
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().raf"),false,'pause cancels the frame loop');
  await delay(150);assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().typed"),pausedTyped,'playback pause still stops constant-speed typing');
  await win.webContents.executeJavaScript("fixtureClock=(tileEpoch+6)*1000;receivePip(tilePayload)");await delay(450);
  assert.ok(await win.webContents.executeJavaScript("PinePip.messageTile().typed")>pausedTyped);
  await win.webContents.executeJavaScript("fixtureClock=(tileEpoch+9)*1000;receivePip(tilePayload)");
  for(let n=0;n<90&&await win.webContents.executeJavaScript("PinePip.messageTile().phase")!=='done';n++)await delay(60);
  const settledGeometry=await assertBareTile();
  const listing=await win.webContents.executeJavaScript("document.querySelector('.pip-system3-rolls').textContent");assert.match(listing,/Reply target.*64.*Host/);assert.match(listing,/ES1.*80.*INTEREST.*95.*uncertainty/);assert.match(listing,/RS1.*13.*Opposite/);
  const favoriteStrip=await win.webContents.executeJavaScript("(()=>{const bar=document.createElement('nav');bar.id='pinePipFavorites';bar.className='pip-popup-favorites';const b=document.createElement('button');b.textContent='? Live';b.dataset.popup='module:PineLive';bar.appendChild(b);document.body.appendChild(bar);const hidden=getComputedStyle(bar).display==='none';document.body.classList.add('pine-native-tools');const nativeVisible=getComputedStyle(bar).display==='flex';document.body.classList.remove('pine-native-tools');return {hidden,nativeVisible,retained:bar.querySelector('[data-popup]').dataset.popup};})()");
  assert.deepEqual(favoriteStrip,{hidden:true,nativeVisible:true,retained:'module:PineLive'},'broadcast PiP hides the populated favorite strip while retaining native tools shortcuts');
  const clickPoint=await win.webContents.executeJavaScript("(()=>{const r=Array.from(document.querySelectorAll('.pip-messages .sp-rr-t')).find(n=>n.querySelector('.sp-rr-head').textContent.includes('Reply target')).querySelector('.sp-rr-cat').getBoundingClientRect();return {x:Math.round(r.left+r.width*.65),y:Math.round(r.top+r.height/2)}})()");
  win.webContents.sendInputEvent({type:'mouseMove',...clickPoint});win.webContents.sendInputEvent({type:'mouseDown',...clickPoint,button:'left',clickCount:1});win.webContents.sendInputEvent({type:'mouseUp',...clickPoint,button:'left',clickCount:1});await delay(150);
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.sp-rrp').length"),1,'clicking a roulette entry opens its inspector without initiating a drag');
  assert.match(await win.webContents.executeJavaScript("document.querySelector('.sp-rrp').textContent"),/Host.*Skip/);
  const clickInspector=async point=>{win.webContents.sendInputEvent({type:'mouseMove',...point});win.webContents.sendInputEvent({type:'mouseDown',...point,button:'left',clickCount:1});win.webContents.sendInputEvent({type:'mouseUp',...point,button:'left',clickCount:1});await delay(150);};
  const inspectorInside=await win.webContents.executeJavaScript("(()=>{const r=document.querySelector('.sp-rrp-head b').getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})()");
  await clickInspector(inspectorInside);
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.sp-rrp').length"),1,'clicking inside the roulette inspector keeps it open');
  assert.equal(await win.webContents.executeJavaScript("[document.querySelector('.sp-rrp-back'),...document.querySelectorAll('.sp-rrp-back *')].every(n=>getComputedStyle(n).getPropertyValue('-webkit-app-region')==='no-drag')"),true,'the complete inspector backdrop and its contents exclude native PiP drag regions');
  const inspectorOutside=await win.webContents.executeJavaScript("(()=>{const drag=document.querySelector('.pip-drag-surface').getBoundingClientRect(),box=document.querySelector('.sp-rrp').getBoundingClientRect();for(const y of [Math.ceil(drag.top+1),Math.floor(drag.bottom-1),Math.round(drag.top+drag.height/2)])for(const x of [Math.ceil(drag.left+1),Math.floor(drag.right-1),Math.round(drag.left+drag.width/2)]){const p={x,y};if((p.x<box.left||p.x>box.right||p.y<box.top||p.y>box.bottom)&&document.elementFromPoint(p.x,p.y)===document.querySelector('.sp-rrp-back'))return p;}throw new Error('No blank PiP drag-surface point outside the inspector: '+JSON.stringify({drag:drag.toJSON(),box:box.toJSON(),viewport:[innerWidth,innerHeight]}));})()");
  await clickInspector(inspectorOutside);
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.sp-rrp').length"),0,'clicking outside the roulette inspector over the blank PiP drag surface dismisses it');
  await clickInspector(clickPoint);
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.sp-rrp').length"),1,'the inspector reopens after click-away dismissal');
  win.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});win.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});await delay(100);
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.sp-rrp').length"),0,'Escape still dismisses the reopened roulette inspector');
  await clickInspector(clickPoint);
  const inspectorClose=await win.webContents.executeJavaScript("(()=>{document.querySelector('.sp-rrp-back').style.alignItems='flex-start';document.querySelector('.sp-rrp').style.marginTop='18px';const close=document.querySelector('.sp-rrp-x'),r=close.getBoundingClientRect(),p={x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};if(p.y<26||p.y>68||document.elementFromPoint(p.x,p.y)?.closest('.sp-rrp-x')!==close)throw new Error('Removed favorite strip still intercepts the real close button: '+JSON.stringify(p));return p;})()");
  await clickInspector(inspectorClose);
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.sp-rrp').length"),0,'the close button still dismisses the roulette inspector');
  await win.webContents.executeJavaScript("document.getElementById('pinePipFavorites').remove()");
  await win.webContents.executeJavaScript("tilePayload={...tilePayload,now:{...tileNow,text:'The full message stays visible while the content element grows and wraps. '.repeat(36)}};receivePip(tilePayload)");
  await delay(100);
  const longBeforeTyping=await win.webContents.executeJavaScript("(()=>{const r=document.querySelector('.pip-system3-words').getBoundingClientRect();return {top:r.top,height:r.height}})()");
  for(let n=0;n<260&&await win.webContents.executeJavaScript("PinePip.messageTile().phase")!=='done';n++)await delay(60);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-words').textContent"),await win.webContents.executeJavaScript("tilePayload.now.text"),'the full long message remains inside the independent text pane');
  const longGeometry=await assertBareTile();
  for(const pane of ['box','item','words'])for(const key of ['left','top','width'])assert.ok(Math.abs(longGeometry[pane][key]-settledGeometry[pane][key])<=1.1,'long text preserves '+pane+' '+key);
  assert.ok(Math.abs(longGeometry.words.top-longBeforeTyping.top)<=1.1&&Math.abs(longGeometry.words.height-longBeforeTyping.height)<=1.1,'the full reply reserves its capped text viewport before typing continues');
  assert.equal(longGeometry.natural.textScrolling,true);assert.equal(longGeometry.natural.scrolling,true);
  assert.ok(longGeometry.words.scrollTop>0,'older text lines scroll within their own fixed viewport');
  assert.equal(longGeometry.scrollTop,0,'long text never scrolls the whole message');
  const readingPoint=await win.webContents.executeJavaScript("(()=>{const r=document.querySelector('.pip-messages .pip-system3-words').getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+Math.min(30,r.height/2))}})()");
  win.webContents.sendInputEvent({type:'mouseMove',...readingPoint});await delay(60);
  const beforeWheel=await win.webContents.executeJavaScript("({words:document.querySelector('.pip-system3-words').scrollTop,rolls:document.querySelector('.pip-system3-rolls').scrollTop})");
  win.webContents.sendInputEvent({type:'mouseWheel',...readingPoint,deltaY:220,deltaX:0,canScroll:true});await delay(150);
  const readUp=await win.webContents.executeJavaScript("({top:document.querySelector('.pip-system3-words').scrollTop,rolls:document.querySelector('.pip-system3-rolls').scrollTop,stage:document.querySelector('.pip-system3-stage').scrollTop,held:PinePip.messageTile().held})");
  assert.equal(readUp.held,true);assert.ok(readUp.top<beforeWheel.words,'wheel scrolls earlier words inside the text pane');
  assert.equal(readUp.rolls,beforeWheel.rolls,'reading earlier words leaves the roulette pane alone');assert.equal(readUp.stage,0);
  await win.webContents.executeJavaScript("receivePip(tilePayload)");await delay(180);
  assert.ok(Math.abs(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-words').scrollTop")-readUp.top)<2,'live feed updates do not pull the reader back down');
  win.webContents.sendInputEvent({type:'mouseWheel',...readingPoint,deltaY:-100,deltaX:0,canScroll:true});await delay(150);
  assert.ok(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-words').scrollTop")>readUp.top,'wheel can scroll the text pane back down too');
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-stage').scrollTop"),0);
  // A finger pan belongs to the words pane; mouse dragging and edge resizing stay available below.
  const touchBefore=await win.webContents.executeJavaScript("(()=>{const box=document.querySelector('.pip-messages'),words=box.querySelector('.pip-system3-words'),r=box.getBoundingClientRect(),w=words.getBoundingClientRect();return {left:r.left,top:r.top,words:words.scrollTop,rolls:box.querySelector('.pip-system3-rolls').scrollTop,x:Math.round(w.left+w.width/2),y:Math.round(w.top+w.height/2),touch:getComputedStyle(box).touchAction,paneTouch:getComputedStyle(words).touchAction}})()");
  assert.equal(touchBefore.touch,'pan-y');assert.equal(touchBefore.paneTouch,'pan-y');
  win.webContents.debugger.attach('1.3');
  try{
    await win.webContents.debugger.sendCommand('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:touchBefore.x,y:touchBefore.y,id:1}]});
    await win.webContents.debugger.sendCommand('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:touchBefore.x,y:touchBefore.y+20,id:1}]});
    await delay(100);
    await win.webContents.debugger.sendCommand('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    await delay(150);
  }finally{win.webContents.debugger.detach();}
  const touchAfter=await win.webContents.executeJavaScript("(()=>{const box=document.querySelector('.pip-messages'),r=box.getBoundingClientRect();return {left:r.left,top:r.top,words:box.querySelector('.pip-system3-words').scrollTop,rolls:box.querySelector('.pip-system3-rolls').scrollTop,stage:box.querySelector('.pip-system3-stage').scrollTop}})()");
  assert.ok(Math.abs(touchAfter.left-touchBefore.left)<1.1&&Math.abs(touchAfter.top-touchBefore.top)<1.1,'touching the text scroll pane never drags the tile');
  assert.ok(touchAfter.words<touchBefore.words,'a native finger pan scrolls earlier words');
  assert.equal(touchAfter.rolls,touchBefore.rolls);assert.equal(touchAfter.stage,0);
  win.webContents.sendInputEvent({type:'mouseMove',x:win.getContentSize()[0]-12,y:12});await delay(100);
  await win.webContents.executeJavaScript("tilePayload={...tilePayload,now:{...tileNow,text:'Hi.'}};receivePip(tilePayload)");await delay(150);
  const shortGeometry=await assertBareTile();
  for(const pane of ['box','item','words'])for(const key of ['left','top','width'])assert.ok(Math.abs(shortGeometry[pane][key]-longGeometry[pane][key])<=1.1,'short text preserves '+pane+' '+key);
  assert.ok(shortGeometry.words.height<longGeometry.words.height/2,'a short reply uses a compact text pane instead of blank reserved lines');
  assert.equal(shortGeometry.words.scrollTop,0,'a corrected short message resets only the text pane scroll');
  assert.equal(shortGeometry.natural.textScrolling,false);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-words').textContent"),'Hi.');
  const stableLive=await win.webContents.executeJavaScript("stableTileCheck.running=false;({failures:[...new Set(stableTileCheck.failures)],samples:stableTileCheck.samples,nodes:stableTileCheck.saved.size})");
  assert.deepEqual(stableLive.failures,[],'real PiP rows retain their DOM, indentation, width, font and positions within the roulette container through typing');assert.ok(stableLive.samples>10);assert.equal(stableLive.nodes,16);
  const sampleSfxTyping=async until=>{
    const start=await win.webContents.executeJavaScript('('+ (function(until){
      const row={id:'sfx-rate-'+until,who:'SFX',name:'SFX 17',text:'17 with the earr... '.repeat(30),from:0,until};
      receivePip({...tilePayload,now:row,rows:tilePayload.rows.concat(row),station:{stream_now:{at:fixtureClock/1000,rows:[row]}}});
      return {at:performance.now(),typed:PinePip.messageTile().typed,rate:PinePip.messageTile().typingRate};
    }).toString()+')('+until+')');
    await delay(400);
    const end=await win.webContents.executeJavaScript('({at:performance.now(),typed:PinePip.messageTile().typed,rate:PinePip.messageTile().typingRate})');
    const delta=end.typed-start.typed,elapsed=end.at-start.at;
    assert.equal(start.rate,180);assert.equal(end.rate,start.rate);
    assert.ok(Math.abs(delta-start.rate*elapsed/1000)<18,'an SFX label types at the configured rate for a '+until+' second clip');
    return {clipSeconds:until,delta,elapsed,rate:end.rate};
  };
  const sfxRates=[await sampleSfxTyping(.5),await sampleSfxTyping(60)];
  console.log('SFX constant typing rates: '+JSON.stringify(sfxRates));
  await win.webContents.executeJavaScript("receivePip({...tilePayload,now:tilePayload.rows[1]})");
  const replaced=await win.webContents.executeJavaScript("({state:PinePip.messageTile(),cards:document.querySelectorAll('.pip-system3-message').length,line:document.querySelector('.pip-system3-message').dataset.line})");
  assert.equal(replaced.state.typed,1,'the next reply starts typing immediately');assert.equal(replaced.state.current,'digital-b');assert.equal(replaced.cards,1);assert.equal(replaced.line,'digital-b','new on-air message cancels the preceding animation');
  for(let n=0;n<70&&await win.webContents.executeJavaScript("PinePip.messageTile().phase")!=='done';n++)await delay(60);
  await assertBareTile();
  // Real hover holds selection while the broadcast keeps delivering newer messages.
  const hoverPoint=await win.webContents.executeJavaScript("(()=>{const r=document.querySelector('.pip-messages').getBoundingClientRect();window.hoverItem=document.querySelector('.pip-system3-message');return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+Math.min(r.height/2,30))}})()");
  win.webContents.sendInputEvent({type:'mouseMove',...hoverPoint});await delay(100);
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().held"),true,'moving the real mouse over the tile holds selection');
  await win.webContents.executeJavaScript("receivePip({...tilePayload,now:{...tilePayload.rows[0],text:'First queued version'}});receivePip({...tilePayload,now:{...tilePayload.rows[0],text:'Latest queued version'}})");await delay(150);
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().current"),'digital-b','new on-air messages cannot replace the hovered roller');
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-message')===hoverItem"),true,'hover preserves the original message DOM');
  const heldEntry=await win.webContents.executeJavaScript("(()=>{const r=document.querySelector('.pip-messages .sp-rr-pickable').getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})()");
  await clickInspector(heldEntry);
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().inspecting"),true,'opening details retains ownership of this tile');
  win.webContents.sendInputEvent({type:'mouseMove',x:win.getContentSize()[0]-12,y:win.getContentSize()[1]-12});await delay(100);
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().current"),'digital-b','leaving the tile for its inspector does not cycle the message');
  const chainPoint=await win.webContents.executeJavaScript("(()=>{const row=document.querySelector('.sp-rrp-go');if(!row)throw Error('No inspector chain entry');row.scrollIntoView({block:'center'});const r=row.getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})()");
  await clickInspector(chainPoint);
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().current"),'digital-b','following another roll in the popup chain retains the same message');
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().inspecting"),true);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-message')===hoverItem"),true);
  win.webContents.sendInputEvent({type:'mouseMove',x:win.getContentSize()[0]-12,y:win.getContentSize()[1]-12});
  win.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});win.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});await delay(150);
  assert.equal(await win.webContents.executeJavaScript("document.querySelectorAll('.sp-rrp').length"),0);
  win.webContents.sendInputEvent({type:'mouseMove',x:win.getContentSize()[0]-12,y:win.getContentSize()[1]-12});await delay(150);
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().held"),false,'mouse exit releases the temporary lock');
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().current"),'digital-a','mouse exit resumes the latest on-air message');
  for(let n=0;n<100&&await win.webContents.executeJavaScript("PinePip.messageTile().phase")!=='done';n++)await delay(60);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-words').textContent"),'Latest queued version','resumption uses the newest buffered message text');
  console.log('System3 hover inspection: real wheel up/down, stable scroll, held popup chains and resume-to-live passed.');
  const dragTile=async(selector,dx,dy)=>{
    const point=await win.webContents.executeJavaScript("(()=>{const r=document.querySelector("+JSON.stringify(selector)+").getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})()");
    win.webContents.sendInputEvent({type:'mouseMove',...point});await delay(30);
    win.webContents.sendInputEvent({type:'mouseDown',...point,button:'left',clickCount:1});
    win.webContents.sendInputEvent({type:'mouseMove',x:point.x+dx,y:point.y+dy});
    win.webContents.sendInputEvent({type:'mouseUp',x:point.x+dx,y:point.y+dy,button:'left',clickCount:1});await delay(150);
  };
  const pointerPosition=cfg.pip.messageBounds.x;await dragTile('.pip-messages',10,10);
  assert.ok(cfg.pip.messageBounds.x>pointerPosition,'pointer dragging persists tile position');
  const pointerWidth=cfg.pip.messageBounds.width;await dragTile('.pip-messages-edge[data-edge=se]',-25,-15);
  assert.ok(cfg.pip.messageBounds.width<pointerWidth,'pointer resizing persists tile dimensions');
  const beforeBounds=cfg.pip.messageBounds.width;await win.webContents.executeJavaScript("document.querySelector('.pip-messages').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',shiftKey:true,bubbles:true}))");await delay(100);assert.ok(cfg.pip.messageBounds.width<beforeBounds,'tile size persists');
  const beforePosition=cfg.pip.messageBounds.x;await win.webContents.executeJavaScript("document.querySelector('.pip-messages').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))");await delay(100);assert.ok(cfg.pip.messageBounds.x>beforePosition,'tile position persists');
  await win.webContents.executeJavaScript("pineDesktop.pipUpdate({ui:false})");await delay(100);assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().raf"),false);
  await win.webContents.executeJavaScript("pineDesktop.pipUpdate({ui:true})");await delay(100);await win.webContents.executeJavaScript("pineDesktop.pipUpdate({widgets:{messages:false}})");await delay(100);assert.equal(cfg.pip.widgets.messages,false);assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().active"),false);



  // Exercise the actual Digital feed consumer, including its frame planner and retirement CSS.
  await win.webContents.executeJavaScript('('+ (function(){
    const host=document.createElement('div');Object.assign(host.style,{position:'fixed',left:'0px',top:'0px',width:'480px',height:'650px',display:'flex',flexDirection:'column',visibility:'hidden'});document.querySelector('#pinePipWidgets').appendChild(host);
    const player=PineMessageView.overlay(host);
    player.event('stable-consumer','System3','The message continues below its completed roll.', 'speech',{rows:[
      {fam:'ES',table:'ES1',main:{dice:80,label:'INTEREST',opts:['JOY','INTEREST'],hit:1},sub:{dice:95,label:'uncertainty',opts:['certainty','uncertainty'],hit:1}},
      {fam:'RS',table:'RS1',main:{dice:13,label:'Opposite',opts:['Agree','Opposite'],hit:1}}
    ]});
    const cur=host.querySelector('.pip-digital-card').__digitalCard.cur;
    window.stableDigital={host,player,cur,saved:new Map(),failures:[]};
    stableDigital.advance=function(ms){cur.t0=Date.now()-ms;cur.began=cur.t0;};
    stableDigital.check=function(remember){
      const stage=host.querySelector('.sp-mv-stage'),sr=stage.getBoundingClientRect();
      for(const step of host.querySelectorAll('.sp-rr-step')){
        if(getComputedStyle(step).display==='none')continue;
        for(const element of [step,...step.children].filter(n=>n.matches('.sp-rr-step,.sp-rr-die,.sp-rr-wheel,.sp-rr-of'))){
          const r=element.getBoundingClientRect(),c=getComputedStyle(element),now={left:r.left-sr.left,top:r.top-sr.top+stage.scrollTop,width:r.width,height:r.height,font:c.fontSize};
          const old=this.saved.get(element);if(old){for(const key of ['left','top','width','height'])if(Math.abs(now[key]-old[key])>1.1)this.failures.push(element.className+' '+key+' changed');if(now.font!==old.font)this.failures.push('font changed');if(!host.contains(element))this.failures.push('prior reel replaced');}
          else if(remember)this.saved.set(element,now);
        }
      }
    };
    stableDigital.advance(cur.sheet.tables[0].dIn+cur.sheet.tables[0].dDie+20);
  }).toString()+')()');
  await delay(120);
  await win.webContents.executeJavaScript("stableDigital.check(true);stableDigital.advance(stableDigital.cur.sheet.tables[0].end+20)");
  await delay(120);
  await win.webContents.executeJavaScript("stableDigital.check(true);stableDigital.advance(stableDigital.cur.sheet.rolled+20)");
  await delay(120);
  await win.webContents.executeJavaScript("stableDigital.check(true);stableDigital.advance(stableDigital.cur.accEnd+700)");
  await delay(120);
  const stableDigital=await win.webContents.executeJavaScript("(()=>{stableDigital.check(true);const c=stableDigital.cur,was=getComputedStyle(c.rolls).display,typed=c.text.textContent;c.node.classList.add('sp-mv-past');stableDigital.check(false);return {failures:stableDigital.failures,nodes:stableDigital.saved.size,summary:c.node.querySelectorAll('.sp-rr-line,.folded').length,typed,rolls:getComputedStyle(c.rolls).display,was,font:getComputedStyle(c.text.parentNode).fontSize};})()");
  assert.deepEqual(stableDigital.failures,[],'the Digital feed consumer retains reel geometry into typed text and retirement');
  assert.equal(stableDigital.nodes,12);assert.equal(stableDigital.summary,0);assert.notEqual(stableDigital.rolls,'none');assert.notEqual(stableDigital.was,'none');assert.ok(stableDigital.typed.length>0);
  await win.webContents.executeJavaScript("stableDigital.player.dispose();stableDigital.host.remove()");
  assert.equal(menuTemplate[0].label, 'Resolve playback + restore DJs');
  assert.equal(menuTemplate[1].label, 'Troubleshoot station...');
  assert.ok(menuTemplate.some(item => item.label === 'Pine Cam overlay'));
  assert.ok(menuTemplate.some(item => item.label === 'Pine Cam only'));
  assert.equal(cfg.replayHoldSeconds, 3600, 'PiP requests one hour while the storage cap remains bounded');
  assert.equal(menuTemplate.find(item => item.label === 'Camera source').submenu.length, 3);
  const exportsMenu = menuTemplate.find(item => item.label === 'Export last...').submenu;
  assert.deepEqual(exportsMenu.map(item => item.label), ['1 minute','2 minutes','3 minutes','5 minutes','10 minutes','15 minutes','30 minutes','1 hour']);
  assert.equal(menuTemplate.find(item => item.label === 'Voice indicator styles').submenu[0].submenu.length, 16);
  const dragRegion = await win.webContents.executeJavaScript(`getComputedStyle(document.querySelector('.pip-drag-surface')).getPropertyValue('-webkit-app-region')`);
  assert.equal(dragRegion, 'drag');
  const noDrag = await win.webContents.executeJavaScript(`['.pip-grip','.pip-volume-dot','.pip-volume-panel input'].map(s=>getComputedStyle(document.querySelector(s)).getPropertyValue('-webkit-app-region'))`);
  assert.deepEqual(noDrag, ['no-drag', 'no-drag', 'no-drag']);
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({ui:false})`);
  assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.querySelector('.pip-audio')).display`), 'none');
  assert.notEqual(await win.webContents.executeJavaScript(`getComputedStyle(document.querySelector('.pip-drag-surface')).display`), 'none');
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({ui:true})`);
  await win.webContents.executeJavaScript(`document.querySelector('.pip-volume-dot').click();const slider=document.querySelector('.pip-volume-panel input');slider.value=23;slider.dispatchEvent(new Event('input'));`);
  assert.equal(await win.webContents.executeJavaScript('window.testVolume'), '23');
  const volumePoint = await win.webContents.executeJavaScript(`(()=>{const r=document.querySelector('.pip-volume-panel input').getBoundingClientRect();return {x:Math.round(r.left+r.width*.8),y:Math.round(r.top+r.height/2)}})()`);
  win.webContents.sendInputEvent({ type: 'mouseDown', ...volumePoint, button: 'left', clickCount: 1 });
  win.webContents.sendInputEvent({ type: 'mouseUp', ...volumePoint, button: 'left', clickCount: 1 });
  await delay(100);
  assert.ok(Number(await win.webContents.executeJavaScript('window.testVolume')) > 60, 'pointer input reaches the volume slider');
  menuTemplate.find(item => item.label === 'Color theme').submenu.find(item => item.label === 'Midnight blue').click();
  menuTemplate.find(item => item.label === 'Overlay transparency...').click(); await delay(100);
  await win.webContents.executeJavaScript(`const appearance=document.querySelector('.pip-appearance');const transparency=appearance.querySelector('input');transparency.value=60;transparency.dispatchEvent(new Event('input'));transparency.dispatchEvent(new Event('change'));`);
  await delay(100);
  assert.equal(cfg.pip.theme, 'midnight'); assert.equal(cfg.pip.transparency, 60);
  const themed = await win.webContents.executeJavaScript(`(async()=>({camera:getComputedStyle(document.querySelector('.pip-camera')).borderColor,painting:getComputedStyle(document.querySelector('.pip-painting')).borderColor,outline:getComputedStyle(document.querySelector('.pip-chat-list article.roll') || document.querySelector('.pip-camera')).borderLeftColor,panel:await document.getElementById('controlFrame').executeJavaScript('({surface:getComputedStyle(document.getElementById("pine-pip-panel")).backgroundColor,accent:document.getElementById("pine-pip-panel").style.getPropertyValue("--pip-accent"),gradient:getComputedStyle(document.querySelector(".pip-bg")).backgroundImage})') }))()`);
  assert.equal(themed.camera,'rgb(138, 197, 255)'); assert.equal(themed.panel.surface,'rgb(10, 20, 38)'); assert.equal(themed.panel.accent,'#8ac5ff'); assert.match(themed.panel.gradient,/28, 53, 89/);

  assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.querySelector('.pip-audio')).opacity`), '0.4');
  assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.querySelector('.pip-appearance input')).getPropertyValue('-webkit-app-region')`), 'no-drag');
  await win.webContents.executeJavaScript(`document.querySelector('.pip-appearance input').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));document.querySelector('.pip-appearance button').click()`);
  assert.equal(win.__pinePip, true, 'double-clicking a settings slider does not expand Pine');
  menuTemplate.find(item => item.label === 'Open tablet display').click();
  menuTemplate.find(item => /Export tablet recording/.test(item.label)).click();
  await delay(200);
  assert.equal(posts[0].route, 'mirror:show'); assert.deepEqual(posts[1], { route: 'glass:clip', seconds: 0, options: { target: 'tablet', replay: true } }); posts = [];
  exportsMenu[0].submenu[0].click(); await delay(100);
  assert.deepEqual(posts.pop(), { route: 'replay:export', want: { seconds: 60, audio_only: true, require_audio: true, view: 'pip' } });
  exportsMenu[7].submenu[1].click(); await delay(100);
  assert.deepEqual(posts.pop(), { route: 'replay:export', want: { seconds: 3600, audio_only: false, require_audio: true, view: 'pip' } });

  assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.querySelector('.pine-window-bar')).display`), 'none');
  assert.equal(win.getTitle(), 'PinePiP'); assert.equal(cfg.pip.alwaysOnTop, true);
  assert.equal(win.isMaximizable(), false);
  win.setContentSize(510, 330); await delay(650);
  const chosenBounds = win.getBounds();
  assert.equal(cfg.pip.bounds.width, 510); assert.equal(cfg.pip.bounds.height, 330);
  for (const ratio of [16 / 9, 9 / 16, 1, 3]) {
    await win.webContents.executeJavaScript(`pineDesktop.pipSource({ratio:${ratio}})`);
    assert.deepEqual(win.getBounds(), chosenBounds, 'source reports preserve all window bounds');
  }
  let preventedResize = false;
  win.emit('will-resize', { preventDefault: () => (preventedResize = true) }, { ...chosenBounds, width: 600, height: 250 }, { edge: 'right' });
  assert.equal(preventedResize, false, 'native edge drags are unconstrained');
  win.emit('resized');
  assert.deepEqual(win.getBounds(), chosenBounds, 'resize completion never corrects the window to a media ratio');
  const idle = await win.webContents.executeJavaScript(`(async()=>{const w=document.getElementById('controlFrame');return await w.executeJavaScript('(async()=>{for(let i=0;i<60&&!document.querySelector(".pip-bg canvas");i++)await new Promise(r=>setTimeout(r,100));return {logo:!!document.querySelector(".pip-logo")?.getAttribute("src")?.startsWith("data:image"),canvas:!!document.querySelector(".pip-bg canvas"),visible:document.getElementById("pine-pip-panel")?getComputedStyle(document.getElementById("pine-pip-panel")).display:"missing"}})()')})()`);
  console.log('Idle: ' + JSON.stringify(idle));
  assert.equal(idle.logo, true); assert.equal(idle.canvas, true); assert.equal(idle.visible, 'block');
  const idleLogo = await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('(()=>{const logo=document.querySelector(".pip-logo"),panel=document.getElementById("pine-pip-panel");return logo.getBoundingClientRect().width/panel.getBoundingClientRect().width})()')`);
  assert.ok(Math.abs(idleLogo - .084) < .002, 'logo occupies 30% of its previous 28% width');
  const h3Stopped = await win.webContents.executeJavaScript(`(async()=>{const c=document.createElement('canvas');c.width=64;c.height=64;const v=document.createElement('video');v.className='pav-media';v.muted=true;v.loop=true;v.autoplay=true;v.srcObject=c.captureStream(10);document.body.appendChild(v);v.play().catch(()=>{});await new Promise(r=>setTimeout(r,700));const paused=v.paused,loop=v.loop;v.srcObject.getTracks().forEach(t=>t.stop());v.remove();return {paused,loop}})()`);
  assert.deepEqual(h3Stopped,{paused:true,loop:false},'late H3 autoplay is stopped in PiP');
  const scrollbars = await win.webContents.executeJavaScript(`(async()=>{const inspect=()=>({root:getComputedStyle(document.documentElement).overflow,bars:[document.documentElement,...document.querySelectorAll('*')].every(n=>getComputedStyle(n).scrollbarWidth==='none')});return {shell:inspect(),panel:await document.getElementById('controlFrame').executeJavaScript('('+inspect.toString()+')()')};})()`);
  assert.deepEqual(scrollbars, { shell: { root: 'hidden', bars: true }, panel: { root: 'hidden', bars: true } }, 'both documents suppress all PiP scrollbars');
  await win.webContents.executeJavaScript(`receivePip({station:{now:{id:'track-1',title:'Pine Song',artist:'Pine Artist',album:'Pine Album'},playing:true},now:{id:'line-1',name:'Host',text:'This is active dialogue'},rows:[{id:'line-1',name:'Host',text:'This is active dialogue'},{id:'sfx-one',who:'SFX',text:'Clip one'}]});`);
  await delay(2700);
  await win.webContents.executeJavaScript("pineDesktop.pipUpdate({widgets:{messages:true}})");await delay(100);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-slate').hidden"),true,'the previous bespoke slate stays retired');
  await win.webContents.executeJavaScript(`receivePip({station:{selling_now:{image:'test.png',title:'Active painting',at:1}},now:{id:'line-1',name:'Host',text:'This is active dialogue'},rows:[]});const img=document.querySelector('.pip-painting img');img.dispatchEvent(new Event('load'));`);
  const painting = await win.webContents.executeJavaScript(`({show:document.querySelector('.pip-painting').classList.contains('show'),seconds:Number(document.querySelector('.pip-painting').dataset.seconds),src:document.querySelector('.pip-painting img').src})`);
  assert.equal(painting.show,true); assert.ok(painting.seconds >= 5 && painting.seconds <= 10); assert.match(painting.src,/api\/generations\/image\/test.png/);
  await delay(painting.seconds * 1000 + 550);
  assert.equal(await win.webContents.executeJavaScript(`document.querySelector('.pip-painting').classList.contains('show')`),false,'thumbnail slides away after rolled duration');
  await win.webContents.executeJavaScript(`receivePip({station:{now:{id:'track-1',title:'Pine Song',artist:'Pine Artist',album:'Pine Album'},playing:true},now:{id:'line-2',name:'Host',text:'Next spoken line'},rows:[]});`);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.pip-system3-words').textContent"),'N','new message immediately types its first character');
  await win.webContents.executeJavaScript("pineDesktop.pipUpdate({widgets:{messages:false}})");await delay(100);
  assert.equal(await win.webContents.executeJavaScript("PinePip.messageTile().active"),false);
  await win.webContents.executeJavaScript(`receivePip({station:{now:{id:'track-1',title:'Pine Song',artist:'Pine Artist',album:'Pine Album'},playing:true},now:{id:'line-1',name:'Host',text:'This is active dialogue'},rows:[]});`); await delay(2700);
  const feeds = await win.webContents.executeJavaScript(`({dice:document.querySelector('.pip-dice output').textContent,chat:document.querySelector('.pip-chat-list').textContent,music:document.querySelector('.pip-music-info').textContent,audit:document.querySelector('[data-widget="audit"] .pip-marquee').textContent})`);
  assert.ok(['64','80','95','13'].includes(feeds.dice), 'dice belongs to recorded active dialogue decisions, not background production roll 88');
  assert.match(feeds.chat, /Roulette selection.*alternatives: Host/); assert.match(feeds.chat, /SFX/); assert.match(feeds.chat, /banked/); assert.match(feeds.chat, /emotion shaping applied/); assert.match(feeds.music, /Pine Song.*Pine Album/); assert.match(feeds.audit, /Host line recorded/);
  fs.writeFileSync(path.join(temp, 'pine-pip-preview.png'), (await win.webContents.capturePage()).toPNG());
  console.log('Preview: ' + path.join(temp, 'pine-pip-preview.png'));
  await win.webContents.executeJavaScript(`document.querySelector('[aria-label="Play this track more"]').click()`); await delay(100);
  assert.deepEqual(posts[0], { route: '/api/music/vote', body: { id: 'track-1', vote: 1 } });
  await win.webContents.executeJavaScript(`(async()=>{const frame=document.getElementById('controlFrame');await frame.executeJavaScript('startVideo("panelVideo","#9c331a")');const c=document.createElement('canvas');c.width=240;c.height=160;c.getContext('2d').fillRect(0,0,240,160);window.synthetic=c;const v=document.getElementById('shellVideo');v.srcObject=c.captureStream(30);await v.play();})()`);
  await delay(1800);
  assert.deepEqual(win.getBounds(), chosenBounds, 'adding videos preserves the chosen width, height and position');
  assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.querySelector('#pine-pip-panel .pip-tile canvas')).objectFit`), 'contain');
  assert.equal(await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('getComputedStyle(document.querySelector(".pip-tile canvas")).objectFit')`), 'contain');
  await win.webContents.executeJavaScript(`document.querySelector('.pip-volume-panel').hidden=true;Object.defineProperty(document,'hidden',{configurable:true,value:false});pineDesktop.pipUpdate({widgets:{cast:true,voices:true,dialogue:false,task:false,audit:false,production:false,music:false,chat:false}})`);
  await delay(300);
  await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('window.PinePipPanel.meters(false);window.postMessage({type:"pine-pip-voices",readings:[{who:"host",level:.8},{who:"cohost",level:.4},{who:"sfx",level:.6},{who:"caller",level:.2}]},"*")')`);
  await delay(150);
  fs.writeFileSync(path.join(temp, 'pine-pip-waveforms.png'), (await win.webContents.capturePage()).toPNG()); console.log('Waveform preview: ' + path.join(temp, 'pine-pip-waveforms.png'));
  const meters = await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('.pip-voice')).map(n=>Number(n.getAttribute('aria-valuenow')))`);
  assert.ok(meters.every(n => n > 0), 'validated panel meter readings reach all four cast bubbles');
  const peaks = await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('.pip-voice')).map(n=>Number(n.style.getPropertyValue('--voice-peak')))`);
  await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('window.postMessage({type:"pine-pip-voices",readings:[]},"*")')`);
  await delay(400);
  const falling = await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('.pip-voice')).map(n=>Number(n.style.getPropertyValue('--voice-peak')))`);
  assert.ok(falling.every((n,i) => n < peaks[i]), 'peaks fall after speech stops');
  assert.ok(await win.webContents.executeJavaScript(`document.querySelectorAll('.pip-cast-member img').length > 0`), 'cast portraits borrow video thumbnails');
  const videos = await win.webContents.executeJavaScript(`(async()=>{const f=document.getElementById('controlFrame');return {shell:document.querySelectorAll('#pine-pip-panel .pip-tile').length,shellLeft:document.querySelector('#pine-pip-panel .pip-tile').style.left,panel:await f.executeJavaScript('({tiles:document.querySelectorAll(".pip-tile").length,width:document.querySelector(".pip-tile").style.width,playing:!document.getElementById("panelVideo").paused})')};})()`);
  assert.equal(videos.shell, 1); assert.equal(videos.panel.tiles, 1); assert.equal(videos.panel.playing, true); assert.equal(videos.panel.width, '50%'); assert.equal(videos.shellLeft, '50%');
  cameraMjpeg = true;
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({cameraOverlay:true,ui:false})`); await delay(800);
  const cam = await win.webContents.executeJavaScript(`(()=>{const box=document.querySelector('.pip-camera'),img=box.querySelector('img'),r=box.getBoundingClientRect();return {shown:getComputedStyle(box).display!=='none',image:!img.hidden&&img.naturalWidth>0,width:r.width,height:r.height,noDrag:getComputedStyle(box).getPropertyValue('-webkit-app-region')}})()`);
  assert.equal(cam.shown, true, 'camera remains visible with widgets hidden'); assert.equal(cam.image, true); assert.equal(cam.noDrag, 'no-drag');
  assert.equal(await win.webContents.executeJavaScript(`document.querySelector('.pip-camera img').src.includes('/live.mjpg')`), true, 'camera uses the live MJPEG stream');
  fs.writeFileSync(path.join(temp, 'pine-pip-camera-preview.png'), (await win.webContents.capturePage()).toPNG()); console.log('Camera preview: ' + path.join(temp, 'pine-pip-camera-preview.png'));
  const dragCamera = async (selector, dx, dy) => {
    const point = await win.webContents.executeJavaScript(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})()`);
    win.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, ...point });
    win.webContents.sendInputEvent({ type: 'mouseMove', x: point.x + dx, y: point.y + dy });
    win.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, x: point.x + dx, y: point.y + dy }); await delay(150);
  };
  const cameraRect = () => win.webContents.executeJavaScript(`(()=>{const r=document.querySelector('.pip-camera').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()`);
  const beforeDrag = await cameraRect(); await dragCamera('.pip-camera-move', -60, 40); const moved = await cameraRect();
  assert.ok(Math.abs(moved.x - (beforeDrag.x - 60)) < 2); assert.ok(Math.abs(moved.y - (beforeDrag.y + 40)) < 2);
  await dragCamera('.pip-camera-resize.se', 30, 15); const resized = await cameraRect();
  assert.ok(Math.abs(resized.width - moved.width - 30) < 2); assert.ok(Math.abs(resized.height - moved.height - 15) < 2, 'camera resizes independently on both axes');
  assert.ok(Math.abs(cfg.pip.cameraBounds.width * win.getContentBounds().width - resized.width) < 2, 'camera geometry is saved');
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({cameraOnly:true})`); await delay(200);
  const mainCamera = await win.webContents.executeJavaScript(`({hiddenVideo:getComputedStyle(document.getElementById('controlFrame')).visibility,hiddenShell:getComputedStyle(document.getElementById('pine-pip-panel')).visibility,full:document.querySelector('.pip-camera').getBoundingClientRect().width===innerWidth,image:!document.querySelector('.pip-camera img').hidden})`);
  assert.deepEqual(mainCamera, { hiddenVideo: 'hidden', hiddenShell: 'hidden', full: true, image: true }, 'camera-only mode hides both video surfaces and the particle background');
  cameraLive = false; await delay(3200);
  assert.equal(await win.webContents.executeJavaScript(`!document.querySelector('.pip-camera-status').hidden && getComputedStyle(document.getElementById('controlFrame')).visibility==='hidden'`), true, 'offline camera-only stays on the camera instead of falling back to video');
  cameraLive = true; await delay(3200);
  assert.equal(await win.webContents.executeJavaScript(`!document.querySelector('.pip-camera img').hidden`), true, 'camera reconnects automatically');
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({cameraOnly:false})`); await delay(150);
  const restoredCamera = await cameraRect(); assert.ok(Math.abs(restoredCamera.width - resized.width) < 2);
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({cameraSource:'tab-front'})`); await delay(700);
  assert.equal(tabletFacing, 'front'); assert.equal(tabletCameraOpen, true);
  assert.equal(await win.webContents.executeJavaScript(`!document.querySelector('.pip-camera img').hidden && document.querySelector('.pip-camera img').alt==='Live PineTab front camera'`), true);
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({cameraSource:'tab-rear',cameraOnly:true})`); await delay(700);
  assert.equal(tabletFacing, 'rear');
  assert.equal(await win.webContents.executeJavaScript(`getComputedStyle(document.getElementById('controlFrame')).visibility==='hidden' && !document.querySelector('.pip-camera img').hidden`), true);
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({cameraSource:'pine',cameraOnly:false})`); await delay(600);
  assert.equal(tabletCameraOpen, false, 'switching to Pine Cam releases the tablet camera');
  posts = [];
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({cameraOverlay:false,ui:true})`);
  cameraMjpeg = false;
  assert.equal(await win.webContents.executeJavaScript(`document.querySelector('.pip-camera').hidden && !document.querySelector('.pip-camera img').hasAttribute('src')`), true, 'camera cleanup stops the feed');
  const switchFx = await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('(async()=>{const samples=[];const playback=startVideo("panelVideo","#447e39",160,240);for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,20));document.querySelectorAll(".pip-tile").forEach(tile=>samples.push(...tile.getAnimations().map(a=>a.effect.getTiming().duration)));}await playback;return samples})()')`);
  assert.ok(!switchFx.includes(460), 'PiP source replacement keeps the picture instead of collapsing the tile');
  await delay(800);
  const afterSwitch = await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('({playing:!document.getElementById("panelVideo").paused,tiles:document.querySelectorAll(".pip-tile").length})')`);
  assert.deepEqual(afterSwitch, { playing: true, tiles: 1 });
  assert.deepEqual(win.getBounds(), chosenBounds, 'portrait source replacements preserve window geometry');
  const cadence = await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('(async()=>{const video=document.getElementById("panelVideo"),canvas=document.querySelector(".pip-tile canvas"),ctx=canvas.getContext("2d"),draw=ctx.drawImage;let paints=0,frames=0,callback=0,running=true;ctx.drawImage=function(...args){if(args[0]===video)paints++;return draw.apply(this,args)};const count=()=>{frames++;if(running)callback=video.requestVideoFrameCallback(count)};callback=video.requestVideoFrameCallback(count);await new Promise(r=>setTimeout(r,2000));running=false;video.cancelVideoFrameCallback(callback);ctx.drawImage=draw;return {paints,frames}})()')`);
  assert.ok(cadence.frames > 40, 'fixture produces moving video during cadence measurement');
  assert.ok(cadence.paints >= cadence.frames * .9, 'PiP paints at least 90% of delivered video frames');
  console.log('Measured PiP cadence: ' + JSON.stringify(cadence));
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({alwaysOnTop:false,docks:{music:'bottom'},order:{music:-1},widgets:{task:false}})`);
  assert.equal(win.isAlwaysOnTop(), false);
  const dock = await win.webContents.executeJavaScript(`document.querySelector('.pip-music').parentElement.id`); assert.equal(dock, 'pinePipWidgets', '[pip-music] the player is placed freely, not held in a dock');
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({aspectMode:'square'})`);
  win.setContentSize(510, 330); win.setPosition(90, 80); await delay(650);
  assert.equal(cfg.pip.bounds.side, 510);
  assert.equal(cfg.pip.bounds.x, 90); assert.equal(cfg.pip.bounds.y, 80);
  await win.webContents.executeJavaScript(`document.getElementById('shellVideo').pause();document.getElementById('controlFrame').executeJavaScript('document.getElementById("panelVideo").pause()')`);
  // Allow the 500 ms discovery beat and 460 ms close animation to finish,
  // including scheduling delays on the software-rendered test window.
  for (let i = 0; i < 30; i++) {
    if (!await win.webContents.executeJavaScript(`document.querySelectorAll('#pine-pip-panel .pip-tile').length`)) break;
    await delay(100);
  }
  assert.equal(await win.webContents.executeJavaScript(`document.querySelectorAll('#pine-pip-panel .pip-tile').length`), 0);
  await win.webContents.executeJavaScript('PinePip.exit()'); await delay(200);
  assert.equal(cfg.pip.enabled, false, 'explicit expansion cancels PiP restoration');
  assert.deepEqual(win.getBounds(), full); assert.equal(win.isAlwaysOnTop(), false);
  assert.equal(win.isMaximizable(), true);
  const stopped = await win.webContents.executeJavaScript(`({subscription:receivePip===null,dice:document.querySelector('.pip-dice canvas')===null})`);
  assert.deepEqual(stopped, { subscription: true, dice: true });
  await win.webContents.executeJavaScript('PinePip.enter()'); await delay(500);
  assert.equal(await win.webContents.executeJavaScript('PinePip.state().theme'), 'midnight');
  assert.equal(await win.webContents.executeJavaScript('PinePip.state().transparency'), 60);
  assert.equal(win.getContentBounds().width, 510); assert.equal(win.getContentBounds().height, 330); assert.equal(win.isAlwaysOnTop(), false);
  assert.equal(win.getBounds().x, 90); assert.equal(win.getBounds().y, 80);
  await win.webContents.executeJavaScript(`document.getElementById('controlFrame').executeJavaScript('document.getElementById("pine-pip-panel").dispatchEvent(new MouseEvent("dblclick",{bubbles:true}))')`); await delay(300);
  assert.equal(win.__pinePip, false, 'double click in remote panel restores the desktop');
  assert.equal(errors.length, 0, errors.join('\n'));
  await win.webContents.executeJavaScript(`pineDesktop.troubleshootStation()`); await delay(600);
  const troubleshootingWindow = BrowserWindow.getAllWindows().find(window => window.getTitle() === 'Pine station troubleshooting');
  assert.ok(troubleshootingWindow); assert.equal(troubleshootingWindow.isAlwaysOnTop(), true);
  await win.webContents.executeJavaScript(`pineDesktop.troubleshootStation()`);
  assert.equal(BrowserWindow.getAllWindows().filter(window => window.getTitle() === 'Pine station troubleshooting').length, 1, 'troubleshooting reuses its OS window');
  const checked = await troubleshootingWindow.webContents.executeJavaScript(`stationTroubleshooter.run('check')`);
  assert.ok(checked.entries.some(entry => entry.label === 'Audio in this app')); assert.equal(checked.busy, false);
  await win.webContents.executeJavaScript(`window.PineRevive={run:async opts=>{opts.onProgress({lines:[{label:'Resume audio graph',state:'changed',did:['Graph resumed']}]});return {lines:[{label:'Resume audio graph',state:'proved',did:['Graph resumed']}],verdict:{good:true,say:'Fixture audio measured'}}}};void 0`);
  const repairedAudio = await troubleshootingWindow.webContents.executeJavaScript(`stationTroubleshooter.run('audio')`);
  assert.ok(repairedAudio.entries.some(entry => entry.status === 'verified' && /Fixture audio/.test(entry.detail))); assert.equal(repairedAudio.audioSteps[0].label, 'Resume audio graph');
  cameraLive = false;
  const repairedCamera = await troubleshootingWindow.webContents.executeJavaScript(`stationTroubleshooter.run('camera')`);
  assert.ok(repairedCamera.entries.some(entry => entry.label === 'Camera picture' && entry.status === 'verified'), JSON.stringify(repairedCamera));
  await assert.rejects(troubleshootingWindow.webContents.executeJavaScript(`stationTroubleshooter.run('invalid')`));
  assert.equal(await troubleshootingWindow.webContents.executeJavaScript(`document.querySelectorAll('article').length>0`), true, 'popup displays measured results');
  fs.writeFileSync(path.join(temp, 'pine-troubleshooter-preview.png'), (await troubleshootingWindow.webContents.capturePage()).toPNG()); console.log('Troubleshooter preview: ' + path.join(temp, 'pine-troubleshooter-preview.png'));
  await win.webContents.executeJavaScript(`PinePip.exit()`); troubleshootingWindow.close();
  // Check the actual desktop HTML/CSS, including its overlay rail and views.
  win.destroy();
  const existingChannels = new Set(['config:read', 'agent:get', 'agent:post', 'pip:state', 'pip:enter', 'pip:exit', 'pip:update', 'pip:menu', 'pip:source', 'pip:windowControl', 'pip:position', 'mirror:show', 'glass:clip', 'station-troubleshooter:open', 'station-troubleshooter:state', 'station-troubleshooter:run', 'replay:hold', 'replay:export', 'camera:pip', 'camera:where']);
  const channels = [...fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8').matchAll(/ipcRenderer.invoke\(["']([^"']+)/g)].map(m => m[1]);
  for (const channel of new Set(channels)) if (!existingChannels.has(channel)) ipcMain.handle(channel, () => channel === 'backend:log' ? [] : ({ ok: true, rows: [], lines: [], items: [], hosts: [] }));
  win = new BrowserWindow({ show: false, frame: false, width: 1100, height: 800, minWidth: 520, minHeight: 420,
    webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  // Electron on Windows refuses an SMB document URL. The real launcher also
  // runs a local mirror, so exercise the same complete renderer tree locally.
  let localDesktop = desktop;
  if (desktop.startsWith('\\\\')) { localDesktop = path.join(temp, 'desktop'); fs.cpSync(path.join(desktop, 'renderer'), path.join(localDesktop, 'renderer'), { recursive: true }); fs.cpSync(path.join(desktop, 'assets'), path.join(localDesktop, 'assets'), { recursive: true }); }
  console.log('Loading complete desktop renderer');
  await win.loadFile(path.join(localDesktop, 'renderer/index.html')); await delay(1200);
  await win.webContents.executeJavaScript('PinePip.enter()'); await delay(800);
  const actual = await win.webContents.executeJavaScript(`({button:!!document.querySelector('#pineViewRail #pinePipBtn'),frameWidth:document.getElementById('controlFrame').getBoundingClientRect().width,frameHeight:document.getElementById('controlFrame').getBoundingClientRect().height,width:innerWidth,height:innerHeight,widgets:getComputedStyle(document.getElementById('pinePipWidgets')).display})`);
  assert.equal(actual.button, true); assert.equal(actual.frameWidth, actual.width); assert.equal(actual.frameHeight, actual.height); assert.equal(actual.width, 510); assert.equal(actual.height, 330); assert.equal(actual.widgets, 'block');
  const savedVoices = cfg.pip.widgets.voices;
  for (const voices of [false, true]) {
    await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({widgets:{voices:${voices}}})`); await delay(100);
    const docks = await win.webContents.executeJavaScript(`Array.from(document.querySelectorAll('#pinePipWidgets > .pip-dock')).map(dock=>{const style=getComputedStyle(dock);return [style.borderTopWidth,style.borderRightWidth,style.borderBottomWidth,style.borderLeftWidth]})`);
    assert.deepEqual(docks, [['0px','0px','0px','0px'],['0px','0px','0px','0px']], `full desktop styles add no PiP dock border in the narrow window with voices ${voices ? 'on' : 'off'}`);
  }
  await win.webContents.executeJavaScript(`pineDesktop.pipUpdate({widgets:{voices:${savedVoices}}})`);
  let prevented = false;
  win.webContents.emit('before-input-event', { preventDefault: () => (prevented = true) }, { type: 'keyDown', key: 'P', control: true, shift: true });
  assert.equal(prevented, true); assert.equal(win.__pinePip, false);
  assert.deepEqual(cfg.bounds, win.getNormalBounds(), 'full-size bounds stay separate from the saved PiP rectangle');
  Menu.buildFromTemplate = buildMenu; clearTimeout(failTimer);
  await win.loadURL('about:blank');await delay(150);win.destroy();
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  console.log('PinePiP: camera overlay dragging/free resizing, saved camera geometry, camera-only lock/offline/reconnect, OS troubleshooting window/audio progress/camera repair, scrollbars, video cadence, widget feeds, preferences and cleanup passed.');
  setImmediate(()=>app.quit());
}).catch(error => { console.error(error); clearTimeout(failTimer); server?.close(); app.exit(1); });
