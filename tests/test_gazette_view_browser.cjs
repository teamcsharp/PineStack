/* Electron real Script-pane integration, local fixtures only. No station writes. */
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http');
const root=path.resolve(__dirname,'..'),dir=fs.mkdtempSync(path.join(os.tmpdir(),'pine-gazette-view-'));
app.setPath('userData',dir); app.disableHardwareAcceleration();
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let win,server; const deadline=setTimeout(()=>app.exit(1),55000);
const html=`<!doctype html><html><head><meta charset="utf-8"><style>html,body{height:100%;margin:0}button{color:#dbe7eb;background:#212c35;border:1px solid #35414c;border-radius:5px}select{color:#dbe7eb;background:#212c35}#script{height:100%;width:100%}</style><link rel="stylesheet" href="/script-page.css"><link rel="stylesheet" href="/gazette-view.css"></head><body><section id="script" class="pine-view-host open"></section>
<script>
window.requests=[];window.pending={};window.failed=false;window.fixtureIssues=[{id:'older',at:1791000000,headline:'Mayor faces the committee'},{id:'middle',at:1791003600,headline:'Residents demand a reply'},{id:'newest',at:1791007200,headline:'The city doubles down'}];
window.htmlFor=(id,style)=>'<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{background:#fff8e8;margin:0;padding:20px;font:16px Georgia}h1{overflow-wrap:anywhere}</style></head><body><h1>'+id+' '+style+'</h1><p>Fictional Pinebox city news</p><div style="height:1200px"></div></body></html>';
window.pineDesktop={get:async(path)=>{requests.push(path);if(path==='/api/paper'){if(failed)throw new Error('Archive unavailable');return {latest:'newest',editions:fixtureIssues.slice().reverse()};}if(path.includes('/view?')){const id=decodeURIComponent(path.split('/')[3]),style=new URL(path,location.href).searchParams.get('style');if(pending[id])return await new Promise(resolve=>pending[id].push(()=>resolve({id,style,html:htmlFor(id,style)})));return {id,style,html:htmlFor(id,style)};}if(path==='/api/screenplay')return {hours:[{key:'fixture',lines:1}]};if(path.startsWith('/api/screenplay/'))return {title:'Local verification',elements:[{id:'fixture-scene',type:'scene',text:'IN THE BOOTH'},{id:'fixture-dialogue',type:'dialogue',text:'The original script remains mounted.',line:'line-1'}],counts:{lines:1}};if(path.includes('/rejections'))return {items:[]};return {};},put:async()=>({}),post:async()=>({}),readConfig:async()=>({baseUrl:location.origin})};
window.PineStationFeed={subscribe:()=>()=>{},subscribeView:()=>()=>{}};
window.errors=[];window.addEventListener('error',e=>errors.push(e.message));window.addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
</script><script src="/pine-icons.js"></script><script src="/gazette-view.js"></script><script src="/system3-message-tile.js"></script><script src="/script-page.js"></script>
<script>PineScriptPage.mount(document.getElementById('script'));</script></body></html>`;
async function evalJS(code){try{return await win.webContents.executeJavaScript(code,true);}catch(error){throw new Error('Browser expression failed: '+code+'; '+error+'; errors: '+JSON.stringify(await win.webContents.executeJavaScript('errors')));}}
async function until(code){for(let i=0;i<100;i++){if(await evalJS(code))return;await delay(30);}throw new Error('Timed out: '+code+'; browser errors: '+JSON.stringify(await evalJS('errors')));}
async function measure(){return evalJS(`(()=>{const p=document.getElementById('spGazette'),f=p.querySelector('iframe'),r=p.getBoundingClientRect(),b=f.getBoundingClientRect(),t=document.getElementById('spGazetteToggle').getBoundingClientRect();return {pane:{x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom},frame:{w:b.width,h:b.height,bottom:b.bottom},width:innerWidth,height:innerHeight,toggle:{w:t.width,h:t.height,right:t.right},head:document.querySelector('.sp-gazette-title').textContent,original:!!document.getElementById('fixture-dialogue'),src:f.srcdoc,pressed:document.getElementById('spGazetteToggle').getAttribute('aria-pressed')}})()`);}
app.whenReady().then(async()=>{
 server=http.createServer((request,response)=>{const filename=new URL(request.url,'http://fixture').pathname;if(filename==='/'){response.writeHead(200,{'Content-Type':'text/html'});response.end(html);return;}const file=path.join(root,'desktop/renderer',path.basename(filename));if(fs.existsSync(file)){response.writeHead(200,{'Content-Type':filename.endsWith('.css')?'text/css':'application/javascript'});response.end(fs.readFileSync(file));}else{response.writeHead(404);response.end();}});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 win=new BrowserWindow({show:false,width:1340,height:800,webPreferences:{offscreen:true,sandbox:false}});
 await win.loadURL('http://127.0.0.1:'+server.address().port+'/');
 await until("!!document.getElementById('spGazetteToggle')");
 assert.equal(await evalJS("requests.filter(p=>p.startsWith('/api/paper')).length"),0,'closed reader does not fetch');
 await evalJS("window.savedScript=document.getElementById('spScript');window.savedContents=savedScript.innerHTML;document.getElementById('spGazetteToggle').click();true");
 await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('newest broadsheet')");
 let m=await measure();assert.equal(m.pressed,'true');assert(m.head.includes('city doubles down'));assert(m.src.includes('<base href="http://127.0.0.1:'));assert(m.frame.h>100);
 await evalJS("document.querySelector('.sp-gazette-title').click();true");
 await until("!document.getElementById('spGazetteShelf').hidden");
 assert.equal(await evalJS("document.querySelector('.sp-gazette-issues').options.length"),3,'top-bar tap exposes every retained issue');
 await evalJS("var s=document.querySelector('.sp-gazette-issues');s.value='older';s.dispatchEvent(new Event('change'));true");
 await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('older broadsheet')");
 // Range input previews an issue without any render request, and commits once released.
 let before=await evalJS("requests.filter(p=>p.includes('/view?')).length");
 await evalJS("var s=document.querySelector('.sp-gazette-scrub');s.value='1';s.dispatchEvent(new Event('input'));true");
 assert.equal(await evalJS("requests.filter(p=>p.includes('/view?')).length"),before);
 assert((await measure()).head.includes('Residents demand'));
 await evalJS("document.querySelector('.sp-gazette-scrub').dispatchEvent(new Event('change'));true");
 await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('middle broadsheet')");
 await evalJS("document.querySelector('.sp-gazette-styles button:nth-child(2)').click();true");
 await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('middle tabloid')");
 // Genuine pointer events exercise the title's capture/release scrub.
 let box=await evalJS("(()=>{const b=document.querySelector('.sp-gazette-title').getBoundingClientRect();return{x:b.x,y:b.y,w:b.width,h:b.height}})()");
 win.webContents.sendInputEvent({type:'mouseMove',x:Math.round(box.x+box.w/2),y:Math.round(box.y+box.h/2)});
 win.webContents.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,x:Math.round(box.x+box.w/2),y:Math.round(box.y+box.h/2)});
 win.webContents.sendInputEvent({type:'mouseMove',x:Math.round(box.x+1),y:Math.round(box.y+box.h/2)});
 await delay(30);
 win.webContents.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,x:Math.round(box.x+1),y:Math.round(box.y+box.h/2)});
 await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('older tabloid')");
 assert.equal(await evalJS("document.getElementById('spGazetteShelf').hidden"),true,'drag commits without opening picker');
 // An older slow render must not replace the issue chosen afterwards.
 await evalJS("pending.middle=[];var s=document.querySelector('.sp-gazette-scrub');s.value='1';s.dispatchEvent(new Event('change'));s.value='2';s.dispatchEvent(new Event('change'));true");
 await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('newest tabloid')");
 await evalJS("pending.middle.forEach(done=>done());delete pending.middle;true");await delay(50);
 assert((await measure()).src.includes('newest tabloid'));
 // Keyboard navigation, endpoints and return restore the mounted script.
 await evalJS("document.querySelector('.sp-gazette-title').dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));true");
 await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('older tabloid')");
 const layouts=[];
 for(const [width,height] of [[1340,800],[1024,768],[800,1280],[500,800]]){
  win.setSize(width,height);await delay(80);m=await measure();
  assert(m.frame.w>50&&m.frame.h>80,'reader fills useful pane at '+width+'x'+height+': '+JSON.stringify(m));
  assert(m.pane.right<=m.width+1&&m.pane.bottom<=m.height+1,'reader stays in pane');
  assert(m.frame.bottom<=m.pane.bottom+1,'frame fits its pane');layouts.push({width,height,pane:m.pane,frame:m.frame,toggle:m.toggle});
 }
 await evalJS("document.querySelector('.sp-gazette-title').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));true");
 assert.equal(await evalJS("document.getElementById('spGazetteToggle').getAttribute('aria-pressed')"),'false');
 assert.equal(await evalJS("document.getElementById('spScript')===savedScript"),true,'script node and state remain');
 assert.equal(await evalJS("document.querySelector('.sp-gazette-frame').srcdoc"),'','closing releases newspaper audio/video');
 const total=await evalJS("requests.filter(p=>p.startsWith('/api/paper')).length");await delay(1200);
 assert.equal(await evalJS("requests.filter(p=>p.startsWith('/api/paper')).length"),total,'hidden Gazette adds no poller');
 await evalJS("document.getElementById('spGazetteToggle').click();true");await until("document.querySelector('.sp-gazette-frame').srcdoc.includes('older tabloid')");
 await evalJS("PineScriptPage.close();true");assert.equal(await evalJS("!!document.getElementById('spGazetteToggle')"),false,'Script close disposes reader');
 assert.deepEqual(await evalJS('errors'),[],'real Script mount and reader actions produce no errors');
 fs.writeFileSync(path.join(root,'work','gazette-script-view-browser-report.json'),JSON.stringify({ok:true,layouts,checks:['on-demand auth view','top-bar issue picker','range preview/commit','pointer scrub','stale render protection','style switch','keyboard','script preserved','decoder cleanup','no Gazette timer','dispose']},null,2));
 console.log('Gazette Script reader: real pane, 4 layouts, 11 interaction/race/cleanup checks passed.');
 win.destroy();server.close();clearTimeout(deadline);app.exit(0);
}).catch(error=>{fs.writeFileSync(path.join(root,'work','gazette-script-view-browser-report.json'),JSON.stringify({ok:false,error:String(error.stack||error)},null,2));console.error(error);if(server)server.close();clearTimeout(deadline);app.exit(1);});
