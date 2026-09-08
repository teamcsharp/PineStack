// Hidden Electron, actual cold-ASGI page + production JS/CSS, local fixture APIs only.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), http = require('node:http');
const crypto = require('node:crypto'), strict = require('node:assert/strict');
const base = process.env.PINE_SYSTEM2_SOURCE || path.join(__dirname, '..');
const out = path.join(base, 'docs', 'system2-ui-images');
let checks = 0, server, win, threeAvailable = true;
const assert = new Proxy(strict, {get: (object, key) => typeof object[key] === 'function' ? (...args) => {checks++; return object[key](...args);} : object[key]});
const requests = [], errors = [], screenshots = [];
const now = Math.floor(Date.now() / 1000) - 30;
const candidate = (id, text) => ({id, kind:'news', seconds:18, script:'A: '+text, lines:[
  {id:'0',who:'dj',voice:'saved-voice',text,seconds:18,audio_hash:'a'.repeat(64),url:'/media/'+id+'.wav?t=fixture',name:id+'.wav'}]});
const performance = candidate('recorded-one', '<img src=x onerror="window.injected=true"> Exact spoken words. FULL LINE END');
const slot = (id, kind, allocation=[], start=now) => ({id,kind,label:kind==='news'?'News scene':'Caller still owed',start,deadline:start+240,
  target_seconds:240,ready_seconds:allocation.length?18:0,debt_seconds:allocation.length?222:240,heard_seconds:0,status:allocation.length?'partially_ready':'needs_preparation',
  prompt:'FULL PRIVATE CONFIGURED PROMPT END',allocations:allocation.map(candidate=>({candidate}))});
const state = {version:1,config:{engine:'legacy'},enabled:false,on:true,paused:true,inventory:{candidates:2,ready:1},work:{state:'waiting'},errors:[],jobs:[],events:[],event_plans:[],
  hours:[{id:'hour-one',start:now,ready_seconds:18,debt_seconds:462,slots:[slot('news-one','news',[performance]),slot('caller-one','caller',[],now+240)]},
         {id:'hour-two',start:now+3600,ready_seconds:0,debt_seconds:240,slots:[slot('later','news',[],now+3600)]}]};
const trace = {candidate_id:performance.id,lines:performance.lines,source:{script_plain:'COMPLETE ORIGINAL SOURCE END',script_tinted:performance.script,
  tint:{ok:true,full:'COMPLETE RAW GRADE END'},desk:{model:'actual-retained-model'}},calls:[{messages:[{role:'user',content:'FULL WIRE PROMPT END'}],response:'FULL WIRE RESPONSE END'}],limitations:['This fixture exercises retained evidence; no live model was called.']};
let deferStatus = false, statusWaiters = [], failEventOnce = false;
const fixturePrelude = `<script>
localStorage.setItem('sparkAgentKey','isolated-ui-key');
window.uiFixture={blobs:[],downloads:[],revoked:[],intervals:new Map(),rafs:new Set(),playback:0};
const originalInterval=window.setInterval,originalClear=window.clearInterval;
window.setInterval=(fn,ms)=>{const id=originalInterval(fn,ms);uiFixture.intervals.set(id,{fn,ms});return id;};
window.clearInterval=id=>{uiFixture.intervals.delete(id);originalClear(id);};
const originalFrame=requestAnimationFrame,originalCancel=cancelAnimationFrame;
window.requestAnimationFrame=fn=>{let id=originalFrame(at=>{uiFixture.rafs.delete(id);fn(at);});uiFixture.rafs.add(id);return id;};
window.cancelAnimationFrame=id=>{uiFixture.rafs.delete(id);originalCancel(id);};
URL.createObjectURL=blob=>{const id='blob:fixture-'+uiFixture.blobs.length;const row={id,type:blob.type,text:null};uiFixture.blobs.push(row);blob.text().then(text=>row.text=text);return id;};
URL.revokeObjectURL=id=>uiFixture.revoked.push(id);
HTMLAnchorElement.prototype.click=function(){uiFixture.downloads.push({name:this.download,href:this.href});};
HTMLMediaElement.prototype.play=function(){uiFixture.playback++;return Promise.resolve();};
window.addEventListener('error',event=>{window.lastFixtureError=event.message;});
</script>`;
function response(res, value, code=200) { res.writeHead(code, {'Content-Type':'application/json'});res.end(JSON.stringify(value)); }
async function serve(req,res) {
  const url = new URL(req.url,'http://local');
  let raw='';for await(const chunk of req)raw+=chunk;
  let body;try{body=raw?JSON.parse(raw):null;}catch{return response(res,{detail:'Invalid JSON'},400);}
  if(url.pathname.startsWith('/api/')) {
    requests.push({path:url.pathname,query:url.search,method:req.method,body,authenticated:req.headers.authorization==='Bearer isolated-ui-key'});
    if(req.headers.authorization!=='Bearer isolated-ui-key')return response(res,{detail:'Unauthenticated'},401);
    if(url.pathname==='/api/system2/status') {
      if(deferStatus) await new Promise(resolve=>statusWaiters.push(resolve));
      return response(res,state);
    }
    if(url.pathname==='/api/dj/guests')return response(res,{guests:[{id:'real-guest-id',name:'Saved guest <safe>'}]});
    if(url.pathname==='/api/system2/script') {
      const hour=state.hours.find(x=>x.id===url.searchParams.get('hour'));
      return response(res,{hour_id:hour.id,slots:hour.slots.map(x=>({slot_id:x.id,kind:x.kind,start:x.start,performances:x.allocations.map(a=>a.candidate)}))});
    }
    if(url.pathname==='/api/system2/line')return response(res,trace);
    if(url.pathname==='/api/system2/settings'&&req.method==='POST') {
      state.config.engine=body.engine;state.enabled=body.engine==='system2';return response(res,{ok:true});
    }
    if(url.pathname==='/api/system2/events'&&req.method==='POST') {
      if(failEventOnce){failEventOnce=false;return response(res,{detail:'Reply lost after fixture receipt'},503);}
      return response(res,{id:'event-fixture',state:'pending'});
    }
    return response(res,{detail:'Unlisted fixture API'},404);
  }
  if(url.pathname==='/system2/system2.js'||url.pathname==='/system2/system2.css') {
    const name=url.pathname.split('/').at(-1);res.writeHead(200,{'Content-Type':name.endsWith('.js')?'text/javascript':'text/css'});
    return res.end(fs.readFileSync(path.join(base,'frontend',name)));
  }
  if(url.pathname.startsWith('/vendor/')) {
    const name=url.pathname.split('/').at(-1);
    if(!threeAvailable||!['three.module.js','three.core.js'].includes(name)){res.writeHead(404);return res.end();}
    res.writeHead(200,{'Content-Type':'text/javascript'});return res.end(fs.readFileSync(path.join(base,'data/vendor',name)));
  }
  if(url.pathname==='/system2') {
    const html=fs.readFileSync(path.join(base,'docs/system2-ui-page-fixture.html'),'utf8');
    res.writeHead(200,{'Content-Type':'text/html'});return res.end(html.replace('<body>',fixturePrelude+'<body>'));
  }
  res.writeHead(404);res.end();
}
app.setPath('userData',path.join(os.tmpdir(),'pine-system2-ui-smoke-profile'));
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('enable-unsafe-swiftshader');
app.whenReady().then(async()=>{
 try{
  fs.mkdirSync(out,{recursive:true});
  server=http.createServer((req,res)=>serve(req,res).catch(error=>{errors.push(String(error));response(res,{detail:'Fixture error'},500);}));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  win=new BrowserWindow({show:false,width:1280,height:960,webPreferences:{contextIsolation:true,nodeIntegration:false,offscreen:true,backgroundThrottling:false}});
  win.webContents.session.webRequest.onBeforeRequest((details,callback)=>callback({cancel:!details.url.startsWith(origin)&&!details.url.startsWith('blob:')&& !details.url.startsWith('data:')}));
  win.webContents.on('console-message',(_event,level,message)=>{if(level>=2)console.error('Renderer: '+message);});
  const js=async code=>{try{return await win.webContents.executeJavaScript(code);}catch(error){console.error('Fixture expression: '+code.slice(0,1600));throw error;}};
  const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const until=async(expression,timeout=8000)=>{const end=Date.now()+timeout;while(Date.now()<end){if(await js(expression))return;await wait(35);}throw Error('UI condition timed out: '+expression);};
  const click=async text=>{await js(`[...document.querySelectorAll('button')].find(b=>b.textContent===${JSON.stringify(text)}).click();true;`);await wait(80);};
  const capture=async name=>{const file=path.join(out,name);fs.writeFileSync(file,(await win.webContents.capturePage()).toPNG());screenshots.push(path.relative(base,file).replaceAll('\\','/'));};
  await win.loadURL(origin+'/system2');await until(`document.querySelectorAll('.s2-board>.s2-slot').length===2`);
  assert.equal(requests.filter(x=>x.method==='POST').length,0);
  assert.ok(requests.every(x=>x.authenticated));
  assert.match(await js(`document.querySelector('.s2-summary').textContent`),/1 \/ 2/);
  assert.match(await js(`document.querySelector('.s2-summary').textContent`),/Broadcast paused/);
  assert.equal(await js(`document.querySelectorAll('.s2-paper .s2-line').length`),1);
  assert.equal(await js(`!!document.querySelector('.s2-paper img')||!!window.injected`),false);
  assert.doesNotMatch(await js(`document.querySelector('.s2-paper').textContent`),/FULL WIRE PROMPT/);
  await capture('system2-plan.png');
  await js(`document.querySelector('[aria-label="Broadcast hour"]').value='hour-two';document.querySelector('[aria-label="Broadcast hour"]').dispatchEvent(new Event('change'));true;`);
  assert.match(await js(`document.querySelector('.s2-paper').textContent`),/No complete performance/);
  await js(`document.querySelector('[aria-label="Broadcast hour"]').value='hour-one';document.querySelector('[aria-label="Broadcast hour"]').dispatchEvent(new Event('change'));true;`);
  await js(`document.querySelector('.s2-trace').open=true;true;`);
  await until(`document.querySelector('.s2-trace').textContent.includes('FULL WIRE RESPONSE END')`);
  await until(`!!document.querySelector('.s2-canvas canvas')||document.querySelector('.s2-trace').textContent.includes('3D rendering is unavailable')`);
  const rendered3D=await js(`!!document.querySelector('.s2-canvas canvas')`);
  assert.match(await js(`document.querySelector('.s2-trace').textContent`),/COMPLETE ORIGINAL SOURCE END/);
  await click('Writing');assert.match(await js(`document.querySelector('.s2-trace').textContent`),/FULL WIRE PROMPT END/);
  const priorLineCalls=requests.filter(x=>x.path==='/api/system2/line').length;
  await js(`uiFixture.intervals.forEach(value=>value.fn());true;`);await wait(120);
  assert.equal(await js(`document.querySelector('.s2-trace').open`),true);
  assert.equal(requests.filter(x=>x.path==='/api/system2/line').length,priorLineCalls);
  await js(`document.querySelector('.s2-trace').scrollIntoView({block:'start'});true;`);await wait(120);
  await capture('system2-line-evidence.png');
  await click('Download line');await click('Download line diagnostics');
  await click('Download segment');await click('Download segment diagnostics');
  await click('Download hour script');await click('Download hour diagnostics');
  await until(`uiFixture.blobs.length===6&&uiFixture.blobs.every(b=>b.text!==null)`);
  const blobs=await js(`uiFixture.blobs`);
  assert.equal(blobs.filter(x=>x.type==='application/json').length,3);
  assert.equal(blobs.filter(x=>x.type==='text/plain').length,3);
  assert.match(blobs[0].text,/FULL LINE END/);
  assert.doesNotMatch(blobs[0].text,/FULL WIRE/);
  assert.equal(JSON.parse(blobs[1].text).candidate_id,performance.id);
  assert.equal(JSON.parse(blobs[5].text).slots.length,2);
  assert.match(blobs[4].text,/No complete performance/);
  assert.equal(await js(`uiFixture.playback`),0);
  await js(`document.querySelector('.s2-trace').open=false;true;`);await wait(100);
  assert.equal(await js(`document.querySelectorAll('.s2-trace canvas').length`),0);
  assert.equal(await js(`uiFixture.rafs.size`),0);
  await js(`document.querySelector('[aria-label="Scheduler"]').value='system2';document.querySelector('[aria-label="Scheduler"]').dispatchEvent(new Event('change'));true;`);
  await until(`document.querySelector('.s2-status').textContent.includes('owns preparation')`);
  assert.deepEqual(requests.filter(x=>x.path==='/api/system2/settings').map(x=>x.body),[{engine:'system2'}]);
  await js(`document.querySelector('.s2-event-form').parentElement.open=true;document.querySelector('[aria-label="Event type"]').value='guest';document.querySelector('[aria-label="Event type"]').dispatchEvent(new Event('change'));const labels=[...document.querySelectorAll('.s2-event-form label')];labels.find(x=>x.firstChild.textContent==='Saved guest').querySelector('select').value='real-guest-id';labels.find(x=>x.firstChild.textContent.startsWith('Scene brief')).querySelector('textarea').value='A trusted exact guest brief';true;`);
  await click('Schedule event');
  const event=requests.filter(x=>x.path==='/api/system2/events').at(-1).body;
  assert.equal(event.kind,'guest');assert.equal(event.guest_id,'real-guest-id');
  assert.equal(event.brief,'A trusted exact guest brief');assert.match(event.request_id,/^[a-f\d-]{36}$/);
  assert.equal(event.source,undefined);assert.equal(event.ready,undefined);assert.equal(event.voice,undefined);
  failEventOnce=true;await click('Schedule event');
  const uncertain=requests.filter(x=>x.path==='/api/system2/events').at(-1).body.request_id;
  assert.match(await js(`document.querySelector('.s2-status').textContent`),/Reply lost/);
  await click('Schedule event');assert.equal(requests.filter(x=>x.path==='/api/system2/events').at(-1).body.request_id,uncertain);
  const baselineIntervals=await js(`uiFixture.intervals.size`);
  await js(`(async()=>{window.s2module=await import('/system2/system2.js');window.overlay=await s2module.openSystem2();return true;})()`);
  assert.equal(await js(`document.querySelectorAll('.s2-backdrop').length`),1);
  assert.equal(await js(`uiFixture.intervals.size`),baselineIntervals+1);
  await js(`overlay.close();true;`);await wait(80);
  assert.equal(await js(`document.querySelectorAll('.s2-backdrop').length`),0);
  assert.equal(await js(`uiFixture.intervals.size`),baselineIntervals);
  // A close while the first GET is pending must dispose the eventual mounted view.
  deferStatus=true;
  await js(`window.lateOpen=s2module.openSystem2();true;`);await until(`document.querySelector('.s2-backdrop')!==null`);
  await js(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));true;`);
  deferStatus=false;statusWaiters.splice(0).forEach(resolve=>resolve());await js(`lateOpen.then(()=>true)`);await wait(80);
  const remainingIntervals=await js(`uiFixture.intervals.size`);
  if(remainingIntervals!==baselineIntervals)errors.push('Closing beforeinitialGET completion leaked '+(remainingIntervals-baselineIntervals)+' polling timer(s).');
  assert.equal(await js(`document.querySelectorAll('.s2-backdrop').length`),0);
  // Fresh navigation forces the genuine missing-Three fallback path.
  threeAvailable=false;await win.webContents.session.clearCache();await win.loadURL(origin+'/system2');
  await until(`document.querySelector('.s2-trace')!==null`);await js(`document.querySelector('.s2-trace').open=true;true;`);
  await until(`document.querySelector('.s2-trace').textContent.includes('3D rendering is unavailable')`);
  await click('Source');assert.match(await js(`document.querySelector('.s2-trace').textContent`),/COMPLETE ORIGINAL SOURCE END/);
  await win.setSize(390,844);await wait(150);await capture('system2-mobile.png');
  assert.equal(await js(`document.documentElement.scrollWidth<=window.innerWidth+1`),true);
  assert.equal(errors.length,0,errors.join('\n'));
  const result={ok:true,checks,at:new Date().toISOString(),actualHostPage:'docs/system2-ui-page-fixture.html',rendered3D,
    fallbackVerified:true,screenshots,fixtureRequests:requests.length,fixturePosts:requests.filter(x=>x.method==='POST').length,
    liveStationRequests:0,livePlayback:0,errors,
    source_sha256:Object.fromEntries(['frontend/system2.js','frontend/system2.css'].map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(base,name))).digest('hex')]))};
  fs.writeFileSync(path.join(base,'docs/system2-ui-check.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result));
  win.destroy();server.close();app.exit(0);
 }catch(error){
  fs.mkdirSync(out,{recursive:true});
  if(win&&!win.isDestroyed())fs.writeFileSync(path.join(out,'failure.png'),(await win.webContents.capturePage()).toPNG());
  fs.writeFileSync(path.join(base,'docs/system2-ui-check.json'),JSON.stringify({ok:false,checks,error:String(error.stack),screenshots,liveStationRequests:0},null,2)+'\n');
  console.error(error.stack);win?.destroy();server?.close();app.exit(1);
 }
});
