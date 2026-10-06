/* Real-browser System3 Messenger validation. Serves only workspace assets on
 * an isolated local port; never connects to the station or listener backend. */
'use strict';
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'system3-messenger-test-'));
app.setPath('userData',temp);app.on('window-all-closed',()=>{});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));let win,server;const viewportFailures=[];
const timer=setTimeout(()=>{console.error('System3 Messenger fixture timeout');app.exit(1)},90000);
const emotion={event_id:'C:emotion',family:'ES',turn_id:'T',selected:{table:'ES1',label:'uncertainty'},stages:[
  {stage:'category',selected:'interest',draw:{dice:80},candidates:[{id:'joy',label:'JOY',weight:1},{id:'interest',label:'INTEREST',weight:3}]},
  {stage:'item',selected:'uncertain',draw:{dice:95},candidates:[{id:'certain',label:'certainty'},{id:'uncertain',label:'uncertainty'}]}
]};
const response={event_id:'C:response',family:'RS',turn_id:'T',selected:{table:'RS1',label:'Opposite'},stages:[
  {stage:'item',selected:'opposite',draw:{dice:13},candidates:[{id:'agree',label:'Agree'},{id:'opposite',label:'Opposite'}]}
]};
const conversation={schema:'system3.conversation/1',identity:{conversation_id:'C',trace_id:'s3-C',road_kind:'banter',revision:1},
  mode:'turn',generation_mode:'turn',created:1,status:'generated',subject:{},settings:{controls:{}},inputs:{},plan:{},prompts:[],
  turns:[{turn_id:'T',index:0,speaker:'dj',name:'Host',seat:'A',text:'The on-air words stay below their original roulette rows.',
    decisions:[{event_id:emotion.event_id},{event_id:response.event_id}],speakerbox:[],sfx:null,sfxguy:null},
    {turn_id:'NEXT',index:1,speaker:'cohost',name:'Co-host',seat:'B',text:'Future message must wait.',decisions:[],speakerbox:[],sfx:null,sfxguy:null}],
  lines:[{line_id:'L',turn_id:'T',block:1,ord:0,sid:'s',who:'dj',text:'The on-air words stay below their original roulette rows.',at:1},
    {line_id:'L-next',turn_id:'NEXT',block:1,ord:1,sid:'s',who:'cohost',text:'Future message must wait.',at:1}],
  decision_events:[emotion,response],observations_air:[],observations:[]};
app.whenReady().then(async()=>{
  const assets={'system3.js':path.join(root,'frontend/system3.js'),'system3.css':path.join(root,'frontend/system3.css'),
    'system3-message-tile.js':path.join(root,'desktop/renderer/system3-message-tile.js'),'system3-message-tile.css':path.join(root,'desktop/renderer/system3-message-tile.css')};
  server=http.createServer((req,res)=>{
    const name=decodeURIComponent(req.url.split('?')[0]).split('/').pop();
    if(assets[name]){res.setHeader('Content-Type',name.endsWith('.js')?'application/javascript':'text/css');res.end(fs.readFileSync(assets[name]));return;}
    res.setHeader('Content-Type','text/html');res.end('<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/system3/system3.css"><style>html,body{margin:0;background:#0b1117}#fixture{width:520px;height:640px;overflow:auto}.s3-director .s3-pane[aria-label="Conversation view"]{max-height:240px}</style><main id="fixture"></main>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,width:700,height:720,webPreferences:{offscreen:true,sandbox:false,backgroundThrottling:false}});
  const errors=[];win.webContents.on('console-message',event=>{if(event.level==='error'&&!/favicon/.test(event.message))errors.push(event.message);});
  await win.loadURL('http://127.0.0.1:'+server.address().port+'/fixture');
  await win.webContents.executeJavaScript('window.fixtureConversation='+JSON.stringify(conversation));
  await win.webContents.executeJavaScript('('+ (async function(){
    const mod=await import('/system3/system3.js');window.fixtureModule=mod;
    const clone=x=>JSON.parse(JSON.stringify(x));
    window.requestedRoutes=[];window.directorLoads=0;window.directorEvent=0;
    const request=async route=>{requestedRoutes.push(route);if(route.startsWith('/api/system3/conversation/C')){directorLoads++;return clone(fixtureConversation);}
      if(route.startsWith('/api/system3/conversations'))return {items:[],conversations:window.directorTestActive?[{conversation_id:'C',mode:'active',road:'banter',created:1,turns:2,events:fixtureConversation.decision_events.length,status:'generated'}]:[],cursor:0};
      if(route.includes('/api/system3/events')){
        if(route.includes('limit=1'))return {events:[],head:directorEvent,cursor:directorEvent};
        const after=Number(new URL(route,'http://fixture').searchParams.get('after'));
        return {events:window.directorTestActive&&after<directorEvent?[{event_id:'refresh-'+directorEvent,conversation_id:'C'}]:[],observations:[],cursor:directorEvent};
      }
      if(route.includes('/api/system3/status'))return {settings:{mode:'active',roads:[]},metrics:{},store:{}};
      if(route.includes('/api/system3/config'))return {config:{},versions:[],hash:'fixture'};
      if(route.includes('/api/system3/settings'))return {settings:{mode:'active',controls:{}}};
      if(route.includes('/api/system3/line'))return {line:fixtureConversation.lines[0],conversation:fixtureConversation.identity,turn:fixtureConversation.turns.find(t=>t.turn_id==='T')};
      return {};};window.fixtureRequest=request;
    window.messenger=await mod.mountEmbedded(document.getElementById('fixture'),{request,details:false});
    await messenger.show({conversationId:'C',turnId:'T'});
  }).toString()+')()');
  for(let n=0;n<30&&!await win.webContents.executeJavaScript("!!document.querySelector('.s3-msg[data-turn=T]')");n++)await delay(100);
  const initial=await win.webContents.executeJavaScript('('+ (function(){
    const node=document.querySelector('.s3-msg[data-turn=T]');if(!node)return {html:document.getElementById('fixture').textContent,routes:requestedRoutes};
    window.messageNode=node;window.messageSheet=node.s3Tile?.sheet;window.messageReels=Array.from(node.querySelectorAll('.sp-rr-step'));
    return {canonical:!!node.s3Tile,rows:node.querySelectorAll('.sp-rr-t').length,sub:node.querySelectorAll('.sp-rr-sub').length,summary:node.querySelectorAll('.sp-rr-line,.s3-rl-dice').length};
  }).toString()+')()');
  assert.equal(initial.canonical,true,JSON.stringify(initial));assert.equal(initial.rows,2);assert.equal(initial.sub,1);assert.equal(initial.summary,0);
  await win.webContents.executeJavaScript("messenger.live('L');messenger.clock('L',0,10)");
  // Record geometry only after each real category/subcategory becomes visible.
  await win.webContents.executeJavaScript('('+ (function(){
    window.messageCheck={saved:new Map(),failures:[],running:true,samples:0};
    const host=document.getElementById('fixture'),check=messageCheck;
    function frame(){
      if(!check.running)return;
      const node=document.querySelector('.s3-msg[data-turn=T]');
      if(node!==messageNode)check.failures.push('message article replaced');
      if(node?.s3Tile?.sheet!==messageSheet)check.failures.push('roulette sheet replaced');
      const sr=host.getBoundingClientRect();
      for(const step of messageReels){
        if(!node?.contains(step)){check.failures.push('original reel removed');continue;}
        if(getComputedStyle(step).display==='none')continue;
        for(const element of [step,step.querySelector('.sp-rr-wheel'),step.querySelector('.sp-rr-die'),step.querySelector('.sp-rr-of')]){
          const r=element.getBoundingClientRect(),c=getComputedStyle(element),now={left:r.left-sr.left,top:r.top-sr.top+host.scrollTop,width:r.width,height:r.height,font:c.fontSize};
          const old=check.saved.get(element);if(old){for(const key of ['left','top','width','height'])if(Math.abs(now[key]-old[key])>1.1)check.failures.push(element.className+' '+key+' changed');if(now.font!==old.font)check.failures.push('font changed');}
          else check.saved.set(element,now);
        }
      }
      check.samples++;requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }).toString()+')()');
  for(let n=0;n<130;n++){
    await win.webContents.executeJavaScript("messenger.clock('L',4,10)");
    if(await win.webContents.executeJavaScript("messageNode.querySelector('.s3-words')?.textContent.length>0"))break;
    await delay(80);
  }
  const prefix=await win.webContents.executeJavaScript("messageNode.querySelector('.s3-words').textContent");
  assert.ok(prefix.length>0&&prefix.length<conversation.lines[0].text.length,'on-air reveal follows the playback prefix after rolling');
  await win.webContents.executeJavaScript('('+ (async function(){
    const event={event_id:'C:late',turn_id:'T',family:'IRS',selected:{table:'IRS1',label:'Acknowledge'},
      stages:[{stage:'item',selected:'ack',draw:{dice:42},candidates:[{id:'ack',label:'Acknowledge'},{id:'opp',label:'Opposite'}]}]};
    fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});fixtureConversation.identity.revision=2;
    window.refreshPrefix=messageNode.querySelector('.s3-words').textContent;
    await messenger.show({conversationId:'C',turnId:'T',refresh:true});
  }).toString()+')()');
  for(let n=0;n<90&&await win.webContents.executeJavaScript("messageNode.s3Tile.sheet.tables.length")<3;n++)await delay(80);
  const refreshed=await win.webContents.executeJavaScript("({rows:messageNode.s3Tile.sheet.tables.length,prefix:messageNode.querySelector('.s3-words').textContent,same:messageNode===document.querySelector('.s3-msg[data-turn=T]')&&messageNode.s3Tile.sheet===messageSheet,old:messageReels.every(n=>messageNode.contains(n)),rolling:!!messageNode.s3Tile.seq})");
  assert.equal(refreshed.rows,3,'a live refreshed conversation appends the new recorded decision');
  assert.equal(refreshed.same,true);assert.equal(refreshed.old,true);assert.ok(refreshed.prefix.startsWith(prefix),'late material retains the visible playback prefix');
  assert.equal(refreshed.rolling,true,'late live decisions roll in place before typing resumes');
  await win.webContents.executeJavaScript("messageNode.s3Tile.seq.hurry()");
  await delay(100);
  await win.webContents.executeJavaScript("messenger.clock('L',10,10)");
  for(let n=0;n<30&&await win.webContents.executeJavaScript("messageNode.querySelector('.s3-words').textContent.length")<conversation.lines[0].text.length;n++)await delay(50);
  assert.equal(await win.webContents.executeJavaScript("messageNode.querySelector('.s3-words').textContent"),conversation.lines[0].text);
  await win.webContents.executeJavaScript("messenger.live('L-next');messenger.clock('L-next',0,10)");
  await delay(100);
  const stable=await win.webContents.executeJavaScript("messageCheck.running=false;({failures:[...new Set(messageCheck.failures)],nodes:messageCheck.saved.size,samples:messageCheck.samples,prior:messageNode.isConnected,visible:Array.from(messageReels).every(n=>getComputedStyle(n).display!=='none')})");
  assert.deepEqual(stable.failures,[]);assert.equal(stable.nodes,12);assert.ok(stable.samples>5);assert.equal(stable.prior,true);assert.equal(stable.visible,true,'retiring a message retains its completed reels');
  await win.webContents.executeJavaScript("messageNode.querySelector('.s3-assemble-btn').click()");
  await delay(80);
  const replayStart=await win.webContents.executeJavaScript("({busy:messageNode.dataset.replaying==='1',same:messageNode.s3Tile.sheet===messageSheet,old:messageReels.every(n=>messageNode.contains(n)),seq:!!messageNode.s3Tile.seq})");
  assert.equal(replayStart.busy,true);assert.equal(replayStart.same,true);assert.equal(replayStart.old,true);assert.equal(replayStart.seq,true);
  await win.webContents.executeJavaScript("messageNode.s3Tile.seq.hurry()");
  for(let n=0;n<60&&await win.webContents.executeJavaScript("messageNode.dataset.replaying==='1'");n++)await delay(50);
  const replayDone=await win.webContents.executeJavaScript("({same:messageNode===document.querySelector('.s3-msg[data-turn=T]')&&messageNode.s3Tile.sheet===messageSheet,old:messageReels.every(n=>messageNode.contains(n)),busy:messageNode.dataset.replaying==='1',text:messageNode.querySelector('.s3-words').textContent})");
  assert.equal(replayDone.busy,false);assert.equal(replayDone.same,true);assert.equal(replayDone.old,true);assert.equal(replayDone.text,conversation.lines[0].text);
  fs.writeFileSync(path.join(root,'work/system3-messenger-stable-preview.png'),(await win.webContents.capturePage()).toPNG());
  assert.deepEqual(errors,[],'Messenger browser reports no renderer errors');
  // A replay that becomes the on-air item hands typing back to playback safely.
  await win.webContents.executeJavaScript("messageNode.querySelector('.s3-assemble-btn').click()");
  await delay(40);
  assert.equal(await win.webContents.executeJavaScript("messageNode.dataset.replaying==='1'"),true);
  await win.webContents.executeJavaScript("messenger.live('L');messenger.clock('L',3,10)");
  for(let n=0;n<45&&await win.webContents.executeJavaScript("messageNode.s3Tile.stage")!=='live';n++)await delay(40);
  assert.equal(await win.webContents.executeJavaScript("messageNode.s3Tile.stage"),'live','the active replay receives its changed playback stage after the feed entrance grace');
  await win.webContents.executeJavaScript("messageNode.s3Tile.seq?.hurry()");
  for(let n=0;n<40&&await win.webContents.executeJavaScript("messageNode.dataset.replaying==='1'");n++)await delay(30);
  await delay(70);
  const handedBack=await win.webContents.executeJavaScript("({busy:messageNode.dataset.replaying==='1',stage:messageNode.dataset.stage,same:messageNode.s3Tile.sheet===messageSheet,old:messageReels.every(n=>messageNode.contains(n)),prefix:messageNode.querySelector('.s3-words').textContent,typing:messageNode.querySelector('.s3-words').classList.contains('typing')})");
  assert.equal(handedBack.busy,false);assert.equal(handedBack.stage,'live');assert.equal(handedBack.same,true);assert.equal(handedBack.old,true);
  assert.ok(handedBack.prefix.length>0&&handedBack.prefix.length<=conversation.lines[0].text.length,JSON.stringify(handedBack));
  assert.ok(conversation.lines[0].text.startsWith(handedBack.prefix));
  // Playback itself uses the .typing indicator, so completion verifies the handoff.
  await win.webContents.executeJavaScript("messenger.clock('L',10,10)");
  for(let n=0;n<30&&await win.webContents.executeJavaScript("messageNode.querySelector('.s3-words').textContent.length")<conversation.lines[0].text.length;n++)await delay(30);
  assert.equal(await win.webContents.executeJavaScript("messageNode.querySelector('.s3-words').textContent"),conversation.lines[0].text);
  await win.webContents.executeJavaScript("messenger.live('L-next');messenger.clock('L-next',0,10)");
  for(let n=0;n<30&&await win.webContents.executeJavaScript("messageNode.dataset.stage")!=='past';n++)await delay(30);
  assert.equal(await win.webContents.executeJavaScript("messageNode.dataset.stage"),'past','public embedded Replay targets the retired item');
  // Embedded Replay keeps the distributed run that already owns each item.
  await win.webContents.executeJavaScript("window.messageParent=messageNode.parentElement;document.querySelector('[aria-label=\"Play the build again: the newest round, message by message\"]').click()");
  let embeddedReplayObserved=false;
  for(let n=0;n<80;n++){
    const step=await win.webContents.executeJavaScript("(()=>{const node=document.querySelector('.s3-msg[data-turn=T]'),seq=node?.s3Tile?.seq;const state={same:node===messageNode&&node?.s3Tile?.sheet===messageSheet,parent:node?.parentElement===messageParent,old:messageReels.every(n=>node?.contains(n)),rolling:!!seq,busy:document.querySelector('[aria-label=\"Play the build again: the newest round, message by message\"]').disabled};for(const n of document.querySelectorAll('.s3-msg'))n.s3Tile?.seq?.hurry();return state})()");
    assert.equal(step.same,true,'embedded public Replay retains the article and shared sheet');
    assert.equal(step.parent,true,'embedded public Replay retains the existing distributed run');
    assert.equal(step.old,true,'embedded public Replay retains every original reel');
    embeddedReplayObserved ||= step.rolling;
    if(embeddedReplayObserved&&!step.busy)break;
    await delay(50);
  }
  assert.equal(embeddedReplayObserved,true,'the embedded public Replay rolls the retained target sheet');
  assert.equal(await win.webContents.executeJavaScript("messageNode.querySelector('.s3-words').textContent"),conversation.lines[0].text);
  // A bounded Messenger follows its new row and text tail without resizing old reels.
  await win.webContents.executeJavaScript('('+ (async function(){
    messenger.dispose();window.shortConversation=JSON.parse(JSON.stringify(fixtureConversation));
    const host=document.getElementById('fixture');host.style.height='240px';host.style.width='430px';
    const text='A long recorded message remains below all of its retained roulette rows. '.repeat(35);
    fixtureConversation.turns.find(t=>t.turn_id==='T').text=text;fixtureConversation.lines[0].text=text;
    for(let i=0;i<18;i++){const event={event_id:'C:long-'+i,turn_id:'T',family:'RS',selected:{table:'RS'+(i+2),label:'Recorded '+i},
      stages:[{stage:'item',selected:'recorded',draw:{dice:i+20},candidates:[{id:'recorded',label:'Recorded '+i},{id:'other',label:'Other'}]}]};
      fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});}
    window.messenger=await fixtureModule.mountEmbedded(host,{request:fixtureRequest,details:false});
    await messenger.show({conversationId:'C',turnId:'T'});
  }).toString()+')()');
  for(let n=0;n<40&&!await win.webContents.executeJavaScript("!!document.querySelector('.s3-msg[data-turn=T]')?.s3Tile");n++)await delay(50);
  await win.webContents.executeJavaScript("window.longNode=document.querySelector('.s3-msg[data-turn=T]');window.longSheet=longNode.s3Tile.sheet;window.longReels=Array.from(longNode.querySelectorAll('.sp-rr-step'));window.longWidth=longNode.getBoundingClientRect().width;window.longFont=getComputedStyle(longReels[0]).fontSize;window.longCount=longSheet.tables.length;messenger.live('L');messenger.clock('L',0,10)");
  for(let n=0;n<50&&!await win.webContents.executeJavaScript("!!longNode.s3Tile.seq");n++)await delay(40);
  await win.webContents.executeJavaScript("longNode.s3Tile.seq?.hurry()");await delay(100);
  await win.webContents.executeJavaScript("messenger.clock('L',6,10)");
  for(let n=0;n<40&&!await win.webContents.executeJavaScript("longNode.querySelector('.s3-words').getBoundingClientRect().height>240");n++)await delay(40);
  assert.ok(await win.webContents.executeJavaScript("longNode.querySelector('.s3-words').getBoundingClientRect().height>240"),'an already-typed prefix is taller than the bounded viewport');
  await win.webContents.executeJavaScript("window.beforeLatePrefix=longNode.querySelector('.s3-words').textContent");
  await win.webContents.executeJavaScript('('+ (async function(){
    const event={event_id:'C:viewport-late',turn_id:'T',family:'ES',selected:{table:'ES2',label:'focused'},
      stages:[{stage:'category',selected:'flow',draw:{dice:61},candidates:[{id:'flow',label:'FLOW'},{id:'break',label:'BREAK'}]},
        {stage:'item',selected:'focus',draw:{dice:83},candidates:[{id:'focus',label:'focused'},{id:'wander',label:'wandering'}]}]};
    fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});fixtureConversation.identity.revision++;
    await messenger.show({conversationId:'C',turnId:'T',refresh:true});
  }).toString()+')()');
  for(let n=0;n<90&&await win.webContents.executeJavaScript("longSheet.tables.length")===await win.webContents.executeJavaScript("longCount");n++)await delay(70);
  const heldLongPrefix=await win.webContents.executeJavaScript("longNode.querySelector('.s3-words').textContent");
  assert.ok(heldLongPrefix.startsWith(await win.webContents.executeJavaScript("beforeLatePrefix")));
  const viewportPhases=new Set();let phaseAt=0,lastPhase='';
  for(let n=0;n<100;n++){
    const view=await win.webContents.executeJavaScript("(()=>{const host=document.getElementById('fixture'),table=longSheet.tables.at(-1),part=longSheet.now.includes('sub-')?'sub':'cat',active=table[part].el,a=active.getBoundingClientRect(),b=host.getBoundingClientRect();return {same:longNode===document.querySelector('.s3-msg[data-turn=T]')&&longNode.s3Tile.sheet===longSheet,prefix:longNode.querySelector('.s3-words').textContent,old:longReels.every(r=>longNode.contains(r)),width:longNode.getBoundingClientRect().width,font:getComputedStyle(longReels[0]).fontSize,transform:getComputedStyle(longNode).transform,part,now:longSheet.now,rolling:!!longNode.s3Tile.seq,top:a.top,bottom:a.bottom,viewTop:b.top,viewBottom:b.bottom,scrollTop:host.scrollTop,visible:getComputedStyle(active).display!=='none'}})()");
    assert.equal(view.same,true);assert.equal(view.old,true);if(view.rolling)assert.equal(view.prefix,heldLongPrefix,'late rows keep the entire long typed prefix in place');assert.ok(Math.abs(view.width-await win.webContents.executeJavaScript("longWidth"))<1.1);
    assert.equal(view.font,await win.webContents.executeJavaScript("longFont"));assert.equal(view.transform,'none');
    const phase=view.now.startsWith((await win.webContents.executeJavaScript("longCount"))+':')?view.part:'';
    if(phase!==lastPhase){phaseAt=Date.now();lastPhase=phase;}
    if(phase&&view.visible&&Date.now()-phaseAt>=600){
      assert.ok(view.bottom<=view.viewBottom+2&&view.top>=view.viewTop+2,JSON.stringify({...view,prefixLength:view.prefix.length,prefix:undefined}));
      assert.ok(view.scrollTop>0,'the existing bounded host scrolls preceding rows above');viewportPhases.add(phase);
    }
    if(!view.rolling)break;
    await delay(70);
  }
  assert.deepEqual([...viewportPhases].sort(),['cat','sub'],'the fresh category and indented sub-entry both remain in the viewport');
  await win.webContents.executeJavaScript("messenger.clock('L',10,10)");
  for(let n=0;n<50&&await win.webContents.executeJavaScript("longNode.querySelector('.s3-words').textContent.length")<await win.webContents.executeJavaScript("fixtureConversation.lines[0].text.length");n++)await delay(50);
  await delay(400);
  const tail=await win.webContents.executeJavaScript("(()=>{const host=document.getElementById('fixture'),words=longNode.querySelector('.s3-words'),range=document.createRange();range.selectNodeContents(words);const t=Array.from(range.getClientRects()).at(-1),b=host.getBoundingClientRect();return {text:words.textContent,expected:fixtureConversation.lines[0].text,top:t.top,bottom:t.bottom,left:t.left,right:t.right,viewTop:b.top,viewBottom:b.bottom,viewLeft:b.left,viewRight:b.right,scrollTop:host.scrollTop,same:longNode.s3Tile.sheet===longSheet,old:longReels.every(n=>longNode.contains(n))}})()");
  assert.equal(tail.text,tail.expected);assert.equal(tail.same,true);assert.equal(tail.old,true);
  assert.ok(tail.top>=tail.viewTop&&tail.bottom<=tail.viewBottom+2,JSON.stringify(tail));
  assert.ok(tail.left>=tail.viewLeft&&tail.right<=tail.viewRight+2);assert.ok(tail.scrollTop>0);
  // Manual replay uses the same bounded host and follows its category/sub-entry.
  await win.webContents.executeJavaScript("messenger.live('L-next');messenger.clock('L-next',0,10)");
  for(let n=0;n<60&&!await win.webContents.executeJavaScript("longNode.dataset.stage==='past'&&document.querySelector('.s3-msg[data-turn=NEXT]').dataset.stage==='live'");n++)await delay(40);
  assert.equal(await win.webContents.executeJavaScript("document.querySelector('.s3-msg[data-turn=NEXT]').dataset.stage"),'live','manual past replay waits for the next on-air handoff to finish');
  assert.equal(await win.webContents.executeJavaScript("longNode.dataset.stage"),'past');
  await win.webContents.executeJavaScript("longNode.querySelector('.s3-assemble-btn').click()");
  const manualPhases=new Set();let manualPhase='',manualAt=0;
  for(let n=0;n<70;n++){
    const focus=await win.webContents.executeJavaScript("(()=>{const part=longSheet.now.includes('sub-')?'sub':'cat',r=longSheet.tables[0][part].el.getBoundingClientRect(),v=document.getElementById('fixture').getBoundingClientRect();return {part,now:longSheet.now,busy:longNode.dataset.replaying==='1',rolling:!!longNode.s3Tile.seq,top:r.top,bottom:r.bottom,viewTop:v.top,viewBottom:v.bottom,old:longReels.every(n=>longNode.contains(n))}})()");
    assert.equal(focus.old,true);
    const phase=focus.now.startsWith('0:')?focus.part:'';
    if(phase!==manualPhase){manualPhase=phase;manualAt=Date.now();}
    if(phase&&Date.now()-manualAt>=250){
      assert.ok(focus.top>=focus.viewTop&&focus.bottom<=focus.viewBottom+2,JSON.stringify(focus));manualPhases.add(phase);
    }
    if(manualPhases.size===2||!focus.rolling)break;
    await delay(60);
  }
  assert.deepEqual([...manualPhases].sort(),['cat','sub'],'manual Messenger replay follows both original reel levels');
  await win.webContents.executeJavaScript("longNode.s3Tile.seq?.hurry()");
  for(let n=0;n<70&&await win.webContents.executeJavaScript("longNode.dataset.replaying==='1'");n++)await delay(50);
  const manualTail=await win.webContents.executeJavaScript("(()=>{const host=document.getElementById('fixture'),words=longNode.querySelector('.s3-words'),range=document.createRange();range.selectNodeContents(words);const r=Array.from(range.getClientRects()).at(-1),v=host.getBoundingClientRect();return {same:longNode.s3Tile.sheet===longSheet,old:longReels.every(n=>longNode.contains(n)),busy:longNode.dataset.replaying==='1',stage:longNode.dataset.stage,tileStage:longNode.s3Tile.stage,typing:words.classList.contains('typing'),rolling:!!longNode.s3Tile.seq,hidden:words.hidden,scrollTop:host.scrollTop,sync:document.querySelector('.s3-embed-air')?.getAttribute('aria-pressed'),text:words.textContent,expected:fixtureConversation.lines[0].text,top:r.top,bottom:r.bottom,viewTop:v.top,viewBottom:v.bottom}})()");
  assert.equal(manualTail.same,true);assert.equal(manualTail.old,true);assert.equal(manualTail.text,manualTail.expected);
  if(!(manualTail.top>=manualTail.viewTop&&manualTail.bottom<=manualTail.viewBottom+2)){
    const failure={...manualTail,textLength:manualTail.text.length};delete failure.text;delete failure.expected;
    viewportFailures.push(failure);console.log('Manual bounded viewport failure: '+JSON.stringify(failure));
  }
  await win.webContents.executeJavaScript('('+ (async function(){
    messenger.dispose();window.fixtureConversation=shortConversation;
    // The long target is the final built turn, so its own tail is the final focus.
    const last=fixtureConversation.turns.find(t=>t.turn_id==='T'),first=fixtureConversation.turns.find(t=>t.turn_id==='NEXT');
    first.index=0;last.index=1;fixtureConversation.turns=[first,last];
    fixtureConversation.lines.find(l=>l.line_id==='L-next').ord=0;fixtureConversation.lines.find(l=>l.line_id==='L').ord=1;
    const directorHost=document.createElement('main');directorHost.id='fixture';
    document.getElementById('fixture').replaceWith(directorHost);
    directorHost.style.height='640px';directorHost.style.width='520px';
    window.directorTestActive=true;
    // The hidden isolated Electron fixture exercises the normal two-second poll.
    Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});
    window.director=await fixtureModule.mount(document.getElementById('fixture'),{request:fixtureRequest,tab:'director',details:false});
  }).toString()+')()');
  for(let n=0;n<60&&!await win.webContents.executeJavaScript("!!document.querySelector('.s3-director .s3-chat .s3-msg[data-turn=T]')");n++)await delay(80);
  const directorInitial=await win.webContents.executeJavaScript('('+ (function(){
    const node=document.querySelector('.s3-director .s3-chat .s3-msg[data-turn=T]');
    if(!node)return {error:document.getElementById('fixture').textContent};
    window.directorNode=node;window.directorSheet=node.s3Tile.sheet;
    window.directorChat=node.parentElement;window.directorReels=Array.from(node.querySelectorAll('.sp-rr-step'));
    window.directorPositions=new Map();
    for(const step of directorReels)if(getComputedStyle(step).display!=='none'){
      const a=node.getBoundingClientRect(),r=step.getBoundingClientRect();
      directorPositions.set(step,{left:r.left-a.left,top:r.top-a.top,width:r.width,height:r.height,font:getComputedStyle(step).fontSize});
    }
    return {rows:directorSheet.tables.length,reels:directorReels.length,positions:directorPositions.size,loads:directorLoads};
  }).toString()+')()');
  assert.equal(directorInitial.rows,3,JSON.stringify(directorInitial));assert.equal(directorInitial.reels,4);
  const assertDirectorStable=async expectedRows=>{
    const state=await win.webContents.executeJavaScript('('+ (function(){
      const node=document.querySelector('.s3-director .s3-chat .s3-msg[data-turn=T]'),changed=[];
      for(const [step,old] of directorPositions){
        if(!node.contains(step)){changed.push('original reel removed');continue;}
        if(getComputedStyle(step).display==='none'){changed.push('completed reel hidden');continue;}
        const a=node.getBoundingClientRect(),r=step.getBoundingClientRect(),now={left:r.left-a.left,top:r.top-a.top,width:r.width,height:r.height,font:getComputedStyle(step).fontSize};
        for(const key of ['left','top','width','height'])if(Math.abs(now[key]-old[key])>1.1)changed.push(key+' changed');
        if(now.font!==old.font)changed.push('font changed');
      }
      return {same:node===directorNode&&node?.s3Tile?.sheet===directorSheet,chat:node?.parentElement===directorChat,old:directorReels.every(n=>node?.contains(n)),rows:node?.s3Tile?.sheet.tables.length,changed,loads:directorLoads};
    }).toString()+')()');
    assert.equal(state.same,true,'routine Director refresh retains the article and roulette sheet');
    assert.equal(state.chat,true,'routine Director refresh retains the conversation chat');
    assert.equal(state.old,true,'routine Director refresh retains every original reel');
    assert.equal(state.rows,expectedRows);assert.deepEqual(state.changed,[]);
    return state;
  };
  // Exercise actual public mount polling twice with unchanged recorded decisions.
  for(let cycle=1;cycle<=2;cycle++){
    const before=await win.webContents.executeJavaScript("directorLoads");
    await win.webContents.executeJavaScript("directorEvent++");
    for(let n=0;n<50&&await win.webContents.executeJavaScript("directorLoads")===before;n++)await delay(80);
    assert.ok((await assertDirectorStable(3)).loads>before,'the actual Director event poll reloads its selected conversation');
  }
  const beforeLate=await win.webContents.executeJavaScript("directorLoads");
  await win.webContents.executeJavaScript('('+ (function(){
    const event={event_id:'C:director-late',turn_id:'T',family:'FL',selected:{table:'FL1',label:'Friendly'},
      stages:[{stage:'item',selected:'friendly',draw:{dice:57},candidates:[{id:'friendly',label:'Friendly'},{id:'cool',label:'Cool'}]}]};
    fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});fixtureConversation.identity.revision++;
    directorEvent++;
  }).toString()+')()');
  for(let n=0;n<50&&await win.webContents.executeJavaScript("directorLoads")===beforeLate;n++)await delay(80);
  await assertDirectorStable(4);
  // Public Play the build replays retained nodes instead of rebuilding the chat.
  await win.webContents.executeJavaScript("Array.from(document.querySelectorAll('.s3-director button')).find(n=>n.textContent==='Play the build').click()");
  let observedReplay=false;
  for(let n=0;n<80;n++){
    const replay=await win.webContents.executeJavaScript("(()=>{let busy=false;for(const n of directorChat.querySelectorAll('.s3-msg')){if(n.s3Tile?.seq){busy=true;n.s3Tile.seq.hurry()}}return {busy,building:Array.from(document.querySelectorAll('.s3-director button')).some(n=>n.textContent.startsWith('Building'))}})()");
    observedReplay ||= replay.busy;
    if(observedReplay&&!replay.building)break;
    await delay(80);
  }
  assert.equal(observedReplay,true,'Play the build starts a real canonical roulette replay');
  await assertDirectorStable(4);
  // A normal event poll during manual replay updates the active sheet immediately.
  await win.webContents.executeJavaScript("directorNode.querySelector('.s3-assemble-btn').click()");
  await delay(60);
  const beforeAssemblyRefresh=await win.webContents.executeJavaScript("directorLoads");
  await win.webContents.executeJavaScript('('+ (function(){
    window.assemblySequence=directorNode.s3Tile.seq;
    const event={event_id:'C:assembly-late',turn_id:'T',family:'TEMPER',selected:{table:'TEMPER1',label:'Warm'},
      stages:[{stage:'item',selected:'warm',draw:{dice:69},candidates:[{id:'warm',label:'Warm'},{id:'cold',label:'Cold'}]}]};
    fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});
    fixtureConversation.lines[0].text+=' New words arrived during the same recorded assembly.'.repeat(6);
    fixtureConversation.turns.find(t=>t.turn_id==='T').text=fixtureConversation.lines[0].text;fixtureConversation.identity.revision++;directorEvent++;
  }).toString()+')()');
  for(let n=0;n<50&&await win.webContents.executeJavaScript("directorLoads")===beforeAssemblyRefresh;n++)await delay(80);
  const duringAssembly=await win.webContents.executeJavaScript("({busy:directorNode.dataset.replaying==='1',same:directorNode===document.querySelector('.s3-director .s3-chat .s3-msg[data-turn=T]')&&directorNode.s3Tile.sheet===directorSheet,old:directorReels.every(n=>directorNode.contains(n)),sameSequence:directorNode.s3Tile.seq===assemblySequence,rows:directorNode.s3Tile.sheet.tables.length,text:directorNode.s3Tile.text})");
  assert.equal(duringAssembly.busy,true);assert.equal(duringAssembly.same,true);assert.equal(duringAssembly.old,true);
  assert.equal(duringAssembly.sameSequence,true,'late roll extends the active recorded sequence once');
  assert.equal(duringAssembly.rows,5,'a refresh consumed during manual assembly immediately appends its recorded row');
  assert.match(duringAssembly.text,/New words arrived/);
  await win.webContents.executeJavaScript("directorNode.s3Tile.seq.hurry()");
  for(let n=0;n<30&&!await win.webContents.executeJavaScript("directorNode.querySelector('.s3-words').classList.contains('typing')&&directorNode.querySelector('.s3-words').textContent.length>0");n++)await delay(30);
  const beforeTypingRefresh=await win.webContents.executeJavaScript("directorLoads");
  const activePrefix=await win.webContents.executeJavaScript("directorNode.querySelector('.s3-words').textContent");
  assert.ok(activePrefix.length>0&&activePrefix.length<duringAssembly.text.length,'manual replay is genuinely typing a partial message');
  await win.webContents.executeJavaScript('('+ (function(){
    const event={event_id:'C:typing-late',turn_id:'T',family:'SHOCK',selected:{table:'SHOCK1',label:'Unexpected'},
      stages:[{stage:'item',selected:'new',draw:{dice:77},candidates:[{id:'new',label:'Unexpected'},{id:'old',label:'Expected'}]}]};
    fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});
    fixtureConversation.lines[0].text+=' The final revision arrived during typing.';
    fixtureConversation.turns.find(t=>t.turn_id==='T').text=fixtureConversation.lines[0].text;fixtureConversation.identity.revision++;directorEvent++;
  }).toString()+')()');
  for(let n=0;n<50&&await win.webContents.executeJavaScript("directorLoads")===beforeTypingRefresh;n++)await delay(50);
  const typingRefresh=await win.webContents.executeJavaScript("({busy:directorNode.dataset.replaying==='1',same:directorNode.s3Tile.sheet===directorSheet,old:directorReels.every(n=>directorNode.contains(n)),rows:directorNode.s3Tile.sheet.tables.length,rolling:!!directorNode.s3Tile.seq,prefix:directorNode.querySelector('.s3-words').textContent,text:directorNode.s3Tile.text})");
  assert.equal(typingRefresh.busy,true,'late event reaches the still active typewriter');
  assert.equal(typingRefresh.same,true);assert.equal(typingRefresh.old,true);assert.equal(typingRefresh.rows,6);
  assert.equal(typingRefresh.rolling,true,'new material rolls before the existing typewriter resumes');
  assert.ok(typingRefresh.prefix.startsWith(activePrefix));assert.ok(typingRefresh.prefix.length<typingRefresh.text.length);
  await delay(140);
  assert.equal(await win.webContents.executeJavaScript("directorNode.querySelector('.s3-words').textContent"),typingRefresh.prefix,'rolling late decisions pauses typing without erasing its prefix');
  await win.webContents.executeJavaScript("directorNode.s3Tile.seq.hurry()");
  for(let n=0;n<70&&await win.webContents.executeJavaScript("directorNode.dataset.replaying==='1'");n++)await delay(50);
  await assertDirectorStable(6);
  assert.equal(await win.webContents.executeJavaScript("directorNode.querySelector('.s3-words').textContent"),typingRefresh.text,'the resumed typewriter renders the latest recorded message');
  const beforeRepeat=await win.webContents.executeJavaScript("directorLoads");
  await win.webContents.executeJavaScript("directorEvent++");
  for(let n=0;n<50&&await win.webContents.executeJavaScript("directorLoads")===beforeRepeat;n++)await delay(60);
  await assertDirectorStable(6);
  assert.equal(await win.webContents.executeJavaScript("!!directorNode.s3Tile.seq"),false,'unchanged refreshed decisions do not replay or append twice');
  // Full-round Play the build keeps accepting same-CID material while globally busy.
  await win.webContents.executeJavaScript("Array.from(document.querySelectorAll('.s3-director button')).find(n=>n.textContent==='Play the build').click()");
  for(let n=0;n<60&&!await win.webContents.executeJavaScript("!!directorNode.s3Tile.seq");n++){
    await win.webContents.executeJavaScript("for(const n of directorChat.querySelectorAll('.s3-msg'))if(n!==directorNode)n.s3Tile?.seq?.hurry()");
    await delay(40);
  }
  assert.equal(await win.webContents.executeJavaScript("!!directorNode.s3Tile.seq"),true,'the full-round build reaches the real target roulette');
  const beforeBuildRefresh=await win.webContents.executeJavaScript("directorLoads");
  await win.webContents.executeJavaScript('('+ (function(){
    window.fullBuildSequence=directorNode.s3Tile.seq;
    const event={event_id:'C:build-late',turn_id:'T',family:'RW',selected:{table:'RW1',label:'Next'},
      stages:[{stage:'item',selected:'next',draw:{dice:22},candidates:[{id:'next',label:'Next'},{id:'stay',label:'Stay'}]}]};
    fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});
    fixtureConversation.lines[0].text+=' Full-round building also consumes the latest revision.';
    fixtureConversation.turns.find(t=>t.turn_id==='T').text=fixtureConversation.lines[0].text;fixtureConversation.identity.revision++;directorEvent++;
  }).toString()+')()');
  for(let n=0;n<50&&await win.webContents.executeJavaScript("directorLoads")===beforeBuildRefresh;n++)await delay(60);
  const duringBuild=await win.webContents.executeJavaScript("({loads:directorLoads,busy:Array.from(document.querySelectorAll('.s3-director button')).some(n=>n.textContent.startsWith('Building')),same:directorNode===document.querySelector('.s3-director .s3-chat .s3-msg[data-turn=T]')&&directorNode.s3Tile.sheet===directorSheet,old:directorReels.every(n=>directorNode.contains(n)),sequence:directorNode.s3Tile.seq===fullBuildSequence,rows:directorNode.s3Tile.sheet.tables.length,text:directorNode.s3Tile.text})");
  assert.ok(duringBuild.loads>beforeBuildRefresh,'event polling refreshes the selected conversation during a full-round build '+JSON.stringify(duringBuild));
  assert.equal(duringBuild.busy,true,'same-conversation refresh preserves the active full-round build');
  assert.equal(duringBuild.same,true);assert.equal(duringBuild.old,true);assert.equal(duringBuild.sequence,true);assert.equal(duringBuild.rows,7);
  await win.webContents.executeJavaScript("directorNode.s3Tile.seq.hurry()");
  for(let n=0;n<80&&await win.webContents.executeJavaScript("Array.from(document.querySelectorAll('.s3-director button')).some(n=>n.textContent.startsWith('Building'))");n++)await delay(50);
  await assertDirectorStable(7);
  assert.equal(await win.webContents.executeJavaScript("directorNode.querySelector('.s3-words').textContent"),duringBuild.text,'full-round build finishes with its refreshed words and retained decisions');
  const directorTail=await win.webContents.executeJavaScript("(()=>{const pane=directorNode.closest('.s3-pane'),host=document.getElementById('fixture'),words=directorNode.querySelector('.s3-words'),range=document.createRange();range.selectNodeContents(words);const r=Array.from(range.getClientRects()).at(-1),p=pane.getBoundingClientRect(),v=host.getBoundingClientRect();return {top:r.top,bottom:r.bottom,viewTop:Math.max(p.top,v.top),viewBottom:Math.min(p.bottom,v.bottom,innerHeight),scroll:pane.scrollTop,paneTop:p.top,paneBottom:p.bottom,overflow:getComputedStyle(pane).overflowY,maxHeight:getComputedStyle(pane).maxHeight,client:pane.clientHeight,height:pane.scrollHeight,rootScroll:host.scrollTop,stage:directorNode.dataset.stage,tileStage:directorNode.s3Tile.stage,busy:directorNode.dataset.replaying==='1',hidden:words.hidden,typing:words.classList.contains('typing'),parents:Array.from((function*(el){while(el){yield el;el=el.parentElement}})(pane)).map(el=>({tag:el.tagName,class:el.className,overflow:getComputedStyle(el).overflowY,height:el.clientHeight,scroll:el.scrollTop}))}})()");
  if(!(directorTail.top>=directorTail.viewTop&&directorTail.bottom<=directorTail.viewBottom+2)){viewportFailures.push(directorTail);console.log('Full Director bounded tail failure: '+JSON.stringify(directorTail));}
  // A full Director pane also exposes late category/sub-entry reels above a tall prefix.
  const beforeViewportRefresh=await win.webContents.executeJavaScript("directorLoads");
  await win.webContents.executeJavaScript('('+ (function(){
    const event={event_id:'C:director-viewport',turn_id:'T',family:'ES',selected:{table:'ES3',label:'focused'},
      stages:[{stage:'category',selected:'flow',draw:{dice:62},candidates:[{id:'flow',label:'FLOW'},{id:'break',label:'BREAK'}]},
        {stage:'item',selected:'focus',draw:{dice:84},candidates:[{id:'focus',label:'focused'},{id:'wander',label:'wandering'}]}]};
    fixtureConversation.decision_events.push(event);fixtureConversation.turns.find(t=>t.turn_id==='T').decisions.push({event_id:event.event_id});fixtureConversation.identity.revision++;directorEvent++;
  }).toString()+')()');
  for(let n=0;n<50&&await win.webContents.executeJavaScript("directorLoads")===beforeViewportRefresh;n++)await delay(60);
  assert.equal(await win.webContents.executeJavaScript("directorSheet.tables.length"),8);
  const directorPhases=new Set();let directorPhase='',directorAt=0;
  for(let n=0;n<100;n++){
    const focus=await win.webContents.executeJavaScript("(()=>{const pane=directorNode.closest('.s3-pane'),host=document.getElementById('fixture'),part=directorSheet.now.includes('sub-')?'sub':'cat',r=directorSheet.tables.at(-1)[part].el.getBoundingClientRect(),p=pane.getBoundingClientRect(),v=host.getBoundingClientRect();return {part,now:directorSheet.now,rolling:!!directorNode.s3Tile.seq,top:r.top,bottom:r.bottom,viewTop:Math.max(p.top,v.top),viewBottom:Math.min(p.bottom,v.bottom,innerHeight),same:directorNode.s3Tile.sheet===directorSheet,old:directorReels.every(n=>directorNode.contains(n)),scroll:pane.scrollTop,overflow:getComputedStyle(pane).overflowY,client:pane.clientHeight,height:pane.scrollHeight}})()");
    assert.equal(focus.same,true);assert.equal(focus.old,true);
    const phase=focus.now.startsWith('7:')?focus.part:'';
    if(phase!==directorPhase){directorPhase=phase;directorAt=Date.now();}
    if(phase&&Date.now()-directorAt>=300){
      assert.ok(focus.top>=focus.viewTop&&focus.bottom<=focus.viewBottom+2,JSON.stringify(focus));assert.ok(focus.scroll>0);directorPhases.add(phase);
    }
    if(!focus.rolling)break;
    await delay(60);
  }
  assert.deepEqual([...directorPhases].sort(),['cat','sub'],'the bounded full Director follows both levels of the late reel');
  await assertDirectorStable(8);
  assert.deepEqual(viewportFailures,[],'the bounded manual replay keeps its typed tail in view');
  assert.deepEqual(errors,[],'System3 embedded Messenger and full Director report no renderer errors');
  await win.webContents.executeJavaScript('director.dispose()');await win.loadURL('about:blank');await delay(100);win.destroy();
  server.closeAllConnections();await new Promise(resolve=>server.close(resolve));clearTimeout(timer);
  console.log('System3 Messenger: shared roulettes, original DOM and row geometry through playback typing, late material, retirement, explicit replay and full Director polling/build identity, active replay/typing refresh, replay-to-live handoff and late full-round build refresh and embedded distributed Replay identity and bounded active row/text following passed.');
  setImmediate(()=>app.quit());
}).catch(error=>{console.error(error);clearTimeout(timer);server?.closeAllConnections();server?.close();app.exit(1);});
