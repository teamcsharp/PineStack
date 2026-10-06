'use strict';
// Native Pine tools, real DOM and shared feed; no station writes or playback.
const {app,BrowserWindow,ipcMain}=require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.disableHardwareAcceleration();
app.setPath('userData',fs.mkdtempSync(path.join(os.tmpdir(),'pine-flow-live-test-')));
const ids=['11111111','22222222','33333333'];
const flowKey='1234567890abcdef',otherKey='fedcba0987654321';
const routeReads=[],pending=new Map();let delayIds=new Set();
function flowFor(id){
 const current=ids.indexOf(id);
 const nodes=[{id:'start:'+flowKey,type:'start',label:'Fixture conversation'},
 {id:'global',type:'decision',family:'STATION',turn_index:-1,seq:0,dice:5,stages:[]}];
 ids.forEach((line,index)=>{
  for(let j=0;j<4;j++)nodes.push({id:'d:'+index+':'+j,type:'decision',family:'RS',turn_index:index,seq:index*4+j+1,at:10+index*10+j,dice:20+j,stages:[],label:'Action '+index+' '+j});
  nodes.push({id:'t:'+index,type:'turn',turn_id:'turn'+index,index,who:['Dill','Skip','Sam'][index],said:'Reply '+index,codes:[line],now:index===current,aired_at:index<=current?1:null});
  nodes.push({id:'g:'+index,type:'gate',label:'Recorded gate',text:'turn '+(index+1),at:15+index*10});
 });
 nodes.push({id:'end:'+flowKey,type:'end',label:'planned'});
 return {key:flowKey,revision:1,road:'Fixture conversation',now_turn:current>=0?'turn'+current:'',nodes,edges:[],counts:{turns:3,decisions:13}};
}
function payload(id,elapsed=0,paused=false){return {at:Date.now(),station:{paused,stream_now:{at:Date.now()/1000-elapsed,rows:[{id,from:0,until:10}]}},now:{id,text:'Speaking '+id,from:0,until:10},rows:ids.map(id=>({id,text:'Speaking '+id}))};}
const deadline=setTimeout(()=>{console.error('Flow live test timed out');app.exit(1);},60000);
app.whenReady().then(async()=>{
 ipcMain.handle('agent:get',(_event,route)=>{
  routeReads.push(route);
  if(route.startsWith('/api/flow/recent'))return {conversations:[{conversation_id:otherKey,topic:'Unrelated newest plan'}]};
  if(route==='/api/flow/now')return {live:true,flow:{key:otherKey,road:'Wrong stale snapshot',nodes:[{id:'wrong',type:'start',label:'Wrong prepared conversation'}],counts:{}}};
  const id=route.split('/').pop();
  if(route.startsWith('/api/flow/')){
   if(delayIds.has(id))return new Promise(resolve=>{pending.set(id,resolve);});
   if(id==='eeeeeeee')throw Error('No recorded System 3 conversation yet');
   return flowFor(id);
  }
  return {ok:true,items:[],rows:[],events:[]};
 });
 ipcMain.handle('agent:post',()=>{throw Error('No station writes');});
 class HiddenWindow extends BrowserWindow{constructor(options){super({...options,show:false,webPreferences:{...options.webPreferences,offscreen:true,backgroundThrottling:false}});}}
 const config={baseUrl:'http://127.0.0.1:8096',pip:{}};
 const manager=require('../desktop/pip-tools-window.cjs').install({BrowserWindow:HiddenWindow,ipcMain,getWindow:()=>null,rendererDir:path.resolve(__dirname,'../desktop/renderer'),preload:path.resolve(__dirname,'../desktop/preload.js'),readConfig:()=>config,writeConfig:()=>{throw Error('No preference writes');}});
 manager.open();const win=manager.getWindow();
 await new Promise(resolve=>win.webContents.once('did-finish-load',resolve));
 const evaluate=code=>win.webContents.executeJavaScript(code);
 await evaluate('pineToolsReady');await wait(80);
 const send=async(id,elapsed=0,paused=false)=>{win.webContents.send('pip:tools-feed',payload(id,elapsed,paused));await wait(70);};
 await send(ids[0]);
 await evaluate("PinePipPopups.select('module:PineFlowChart')");await wait(140);
 assert(routeReads.includes('/api/flow/'+ids[0]),'native Live resolves the actual playback line');
 assert(!routeReads.includes('/api/flow/now'),'stale /now cannot override the shared playback feed');
 const visible=()=>evaluate("[...document.querySelectorAll('.fc-row:not([hidden])')].map(n=>n.dataset.nodeId)");
 const active=()=>evaluate("document.querySelector('.fc-active-step')?.dataset.nodeId");
 let shown=await visible();
 assert(shown.includes('global'));assert.equal(await active(),'global','round-wide planning unfolds with its first reply');assert(!shown.includes('d:1:0'),'future reply actions stay hidden');
 assert(shown.length<8,'active reply unfolds instead of showing all actions at once');
 await evaluate("window.firstAction=document.querySelector('[data-node-id=\"global\"]');window.firstContent=firstAction.querySelector('.fc-decision')");
 await send(ids[0],5);await wait(180);
 assert((await visible()).includes('g:0'));assert.equal(await active(),'g:0');
 assert.equal(await evaluate("document.querySelector('[data-node-id=\"global\"]')===firstAction&&firstAction.querySelector('.fc-decision')===firstContent"),true,'landed action nodes survive unfolding and clock updates');
 const before=routeReads.length;for(let i=0;i<4;i++)await send(ids[0],5+i*.1);
 assert.equal(routeReads.length,before,'clock ticks do not refetch the conversation');
 await send(ids[1]);await wait(120);
 assert(routeReads.includes('/api/flow/'+ids[1]),'the next reply is selected without waiting for the poll');
 assert.equal(await active(),'d:1:0');assert(!(await visible()).includes('d:2:0'));
 assert.equal(await evaluate("document.querySelector('[data-node-id=\"global\"]')===firstAction"),true,'previous reply rows stay landed');
 await send(ids[1],0,true);const frozen=await visible();await wait(700);assert.deepEqual(await visible(),frozen,'paused playback stops unfolding');
 await send(ids[1],0,false);await wait(500);assert((await visible()).length>frozen.length,'resuming playback continues unfolding');
 // A slower previous reply request cannot repaint after a newer reply arrives.
 delayIds=new Set([ids[0]]);await send(ids[0]);assert(pending.has(ids[0]));
 await send(ids[2],5);await wait(100);const latest=await active();
 pending.get(ids[0])(flowFor(ids[0]));await wait(150);
 assert.equal(await active(),latest);assert.match(await evaluate("document.querySelector('.fc-status').textContent"),/speaking: Sam/);
 assert.equal(await evaluate("document.querySelectorAll('.fc-turn.now').length"),1,'only the speaking turn is marked live');
 // Manual history stays manual until Live is pressed, which also restores follow.
 await evaluate("PineFlowChart.open('1234567890abcdef')");await wait(120);
 await send(ids[1],5);assert.equal(await evaluate("document.querySelector('.fc-bar button').getAttribute('aria-pressed')"),'false');
 await evaluate("document.querySelector('.fc-bar button').click()");await wait(120);
 assert.match(await evaluate("document.querySelector('.fc-status').textContent"),/speaking: Skip/);
 assert.equal(await evaluate("document.querySelector('.fc-follow').hidden"),true);
 // A silent clock gap must not fall back to the stale station snapshot.
 const nowReads=routeReads.filter(route=>route==='/api/flow/now').length;
 win.webContents.send('pip:tools-feed',{at:Date.now(),station:{},now:null,rows:[]});await wait(130);
 assert.equal(routeReads.filter(route=>route==='/api/flow/now').length,nowReads);
 assert.equal(await evaluate("document.querySelectorAll('.fc-active-step,.fc-turn.now').length"),0);
 // Missing records retry; they do not bring up an unrelated recent conversation.
 await send('eeeeeeee');await wait(100);
 assert.match(await evaluate("document.querySelector('.fc-status').textContent"),/Waiting for recorded actions for #eeeeeeee/);
 assert(!routeReads.includes('/api/flow/'+otherKey));
 assert.equal(await evaluate("document.querySelectorAll('.fc-active-step,.fc-turn.now').length"),0);
 delayIds=new Set([ids[0]]);await send(ids[0]);
 const reads=routeReads.length;await evaluate('PinePipPopups.clear()');
 pending.get(ids[0])(flowFor(ids[0]));await wait(2200);
 assert.equal(routeReads.length,reads,'closing unsubscribes and stops polling/unfolding');
 assert.equal(await evaluate('PineStationFeed.subscribers()'),0);
 await send(ids[2],5);await evaluate("PinePipPopups.select('module:PineFlowChart')");await wait(1100);
 assert.match(await evaluate("document.querySelector('.fc-status').textContent"),/speaking: Sam/);
 assert((await visible()).includes('t:2'),'reopening mounts the current flow into the new panel');
 assert.equal(await evaluate("(()=>{const b=document.querySelector('.fc-body').getBoundingClientRect(),a=document.querySelector('.fc-active-step').getBoundingClientRect();return a.top<b.bottom&&a.bottom>b.top})()"),true,'opening Live scrolls to the speaking reply actions');
 const wheel=await evaluate("(()=>{const b=document.querySelector('.fc-body').getBoundingClientRect();return {x:Math.round(b.left+30),y:Math.round(b.top+50)}})()");
 win.webContents.sendInputEvent({type:'mouseMove',...wheel});win.webContents.sendInputEvent({type:'mouseWheel',...wheel,deltaY:1500,deltaX:0,canScroll:true});await wait(200);
 assert.equal(await evaluate("document.querySelector('.fc-follow').hidden"),false,'a manual scroll away suspends follow');
 await evaluate("document.querySelector('.fc-bar button').click()");await wait(150);
 assert.equal(await evaluate("document.querySelector('.fc-follow').hidden"),true,'Live explicitly restores follow');
 fs.writeFileSync(path.resolve(__dirname,'../work/flow-live-fixture.png'),(await win.webContents.capturePage()).toPNG());
 console.log('Live flowchart: exact playback reply, sequential actions, retained DOM, pause/resume, no clock polling, stale request rejection, manual history/Live, missing data and cleanup passed.');
 win.destroy();clearTimeout(deadline);app.exit(0);
}).catch(error=>{console.error(error);clearTimeout(deadline);app.exit(1);});
