const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),os=require('node:os'),assert=require('node:assert/strict');
const root=process.env.PINE_BOOK_TEST_ROOT||path.resolve(__dirname,'..');
const calls=[];const rows={book_time:{mode:'fixed:book-one',next:{id:'book-one'},says:'fixed on Book One',alternatives:[{id:'book-one',name:'Book One',text:'System {book}',generation_prompt:'Discuss {booksegment}',weight:1,on:true,config:{target_seconds:450,starts_at_minutes:[15,45]}},{id:'book-two',name:'Book Two',text:'Alternate system',generation_prompt:'Alternate discussion',weight:2,on:true,config:{target_seconds:360,starts_at_minutes:[14,44]}}]},sfx_supercut:{mode:'fixed:spot-one',next:{id:'spot-one'},alternatives:[{id:'spot-one',name:'Station Promo',text:'Existing sources only',generation_prompt:'Sell Pine Box FM',on:true,weight:1,config:{target_seconds:45,starts_at_minutes:[58],item:'Pine Box FM'}}]}};
const server=http.createServer((req,res)=>{
 const route=new URL(req.url,'http://localhost').pathname;
 const reply=value=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
 if(route==='/'){res.writeHead(200,{'Content-Type':'text/html'});res.end('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/style"></head><body style="background:#10171e;color:#dde;font-family:system-ui"><main style="max-width:600px;margin:auto" id="host"></main><script src="/script"></script><script>PineSegments.pane(document.getElementById("host"));</script></body></html>');return;}
 if(route==='/style'||route==='/script'){res.writeHead(200,{'Content-Type':route==='/style'?'text/css':'text/javascript'});res.end(fs.readFileSync(path.join(root,'desktop/renderer/pine-segments.'+(route==='/style'?'css':'js'))));return;}
 if(req.method==='GET'){
  if(route==='/api/schedule/prompts')return reply({banter:{active:0,variants:[{id:'legacy',name:'Banter',text:'Keep this prompt'}]}});
  if(route==='/api/dynamic-segments')return reply({kinds:rows});
  if(route==='/api/dj/topics')return reply({topics:[]});
  return reply({});
 }
 let data='';req.on('data',chunk=>data+=chunk);req.on('end',()=>{
  const body=JSON.parse(data||'{}');calls.push({route,body});
  if(route==='/api/dynamic-segments/book_time/preview')return reply({ok:true,system_prompt:'System The Title',generation_prompt:'Discuss the real section.',source:{title:'The Title',chapter:'Chapter One'},rolls:[{key:'book.source',picked:'The Title'}]});
  if(route==='/api/sfx/supercut/plan')return reply({ok:true,id:'sc-fixture',seconds:45,clips:[{at:0,role:'opening',transcript:'Listen to this!',from_s:0,until_s:2}],coverage:{playable:347178}});
  if(route==='/api/sfx/supercut/render')return reply({ok:true,clip:'fixture.wav',media:{path:'/media/fixture.wav',sig:'signed'},seconds:45});
  const m=route.match(/^\/api\/segment\/prompts\/([^/]+)\/alternative$/);
  if(m){const row=rows[m[1]],id=body.id||'new-fixture';const alt={...body,id};const index=row.alternatives.findIndex(a=>a.id===id);if(index<0)row.alternatives.push(alt);else row.alternatives[index]=alt;return reply({ok:true,alternative:alt,book:row});}
  if(route.endsWith('/mode'))return reply({ok:true,says:'weighted roulette'});
  if(route==='/api/dynamic-segments/activate')return reply({ok:true});
  reply({ok:true});
 });
});
app.disableHardwareAcceleration();app.setPath('userData',fs.mkdtempSync(path.join(os.tmpdir(),'pine-dynamic-test-')));
let win;
app.whenReady().then(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 win=new BrowserWindow({show:false,width:1154,height:690,webPreferences:{offscreen:true}});
 const evalIn=(fn,...args)=>win.webContents.executeJavaScript('('+fn.toString()+')('+JSON.stringify(args).slice(1,-1)+')');
 async function wait(fn,msg){for(let i=0;i<200;i++){if(await evalIn(fn))return;await new Promise(r=>setTimeout(r,25));}throw new Error('timeout: '+msg);}
 await win.loadURL('http://127.0.0.1:'+server.address().port+'/');
 await wait(()=>document.querySelectorAll('.pseg-dynamic').length===2,'dynamic cards');
 assert.equal(calls.length,0,'Opening editor does not write or start playback');
 await evalIn(()=>document.querySelector('.pseg-dynamic .pseg-kind-head').click());
 assert.equal(await evalIn(()=>document.querySelector('.pseg-dynamic textarea').value),'System {book}');
 await evalIn(()=>{const c=document.querySelector('.pseg-dynamic');c.querySelector('select').value='book-two';c.querySelector('select').dispatchEvent(new Event('change'));});
 assert.equal(await evalIn(()=>document.querySelector('.pseg-dynamic textarea').value),'Alternate system');
 await evalIn(()=>{const c=document.querySelector('.pseg-dynamic');const texts=c.querySelectorAll('textarea');texts[0].value='Revised system {book}';texts[1].value='Revised generation {booksentence}';Array.from(c.querySelectorAll('button')).find(b=>b.textContent==='Save').click();});
 await wait(()=>document.querySelector('.pseg-dynamic .pseg-note')?.textContent.startsWith('Saved.'),'save completed');
 const saved=calls.find(c=>c.route.endsWith('/book_time/alternative')).body;
 assert.equal(saved.id,'book-two');assert.equal(saved.text,'Revised system {book}');assert.equal(saved.generation_prompt,'Revised generation {booksentence}');assert.equal(saved.config.target_seconds,360);
 assert.equal(rows.book_time.alternatives.find(a=>a.id==='book-one').text,'System {book}','Saving retains other templates');
 await evalIn(()=>Array.from(document.querySelector('.pseg-dynamic').querySelectorAll('button')).find(b=>b.textContent==='Preview source and prompts').click());
 await wait(()=>!!document.querySelector('.pseg-dynamic-preview strong'),'source preview');
 assert.equal(await evalIn(()=>document.querySelector('.pseg-dynamic-preview strong').textContent),'The Title / Chapter One');
 assert.ok(!calls.some(c=>/books\/(?:start|select)|book-mode\/activate|dynamic-segments\/activate/.test(c.route)),'Preview does not activate station or change schedule');
 await evalIn(()=>{const c=document.querySelector('.pseg-dynamic');c.querySelectorAll('select')[1].value='random';Array.from(c.querySelectorAll('button')).find(b=>b.textContent==='Use this template').click();});
 await wait(()=>document.querySelector('.pseg-dynamic .pseg-note')?.textContent.includes('weighted roulette'),'mode saved');
 assert.equal(calls.find(c=>c.route.endsWith('/book_time/mode')).body.mode,'random');
 await evalIn(()=>{const c=document.querySelectorAll('.pseg-dynamic')[1];c.querySelector('.pseg-kind-head').click();Array.from(c.querySelectorAll('button')).find(b=>b.textContent==='Preview cut list').click();});
 await wait(()=>!!document.querySelector('.pseg-cuts'),'cut list');
 assert.match(await evalIn(()=>document.querySelector('.pseg-cuts').textContent),/Listen to this!/);
 for(const [width,height] of [[1154,690],[700,1000]]){
  win.setSize(width,height);await new Promise(r=>setTimeout(r,80));
  assert.ok(await evalIn(()=>document.documentElement.scrollWidth<=innerWidth+1),'Template editor fits '+width+'px viewport');
 }
 fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});fs.writeFileSync(path.join(root,'artifacts/dynamic-segments-editor.png'),(await win.webContents.capturePage()).toPNG());
 console.log('PASS dynamic templates: recall, independent prompts, narrow saves, source-only previews, weighted mode, tablet layouts');
 win.destroy();server.close();app.quit();
}).catch(err=>{console.error(err.stack);if(win)win.destroy();server.close();app.exit(1);});
