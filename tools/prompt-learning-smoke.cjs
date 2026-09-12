// Hidden fixture-only exercise: network is blocked and every mutation is fake.
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const base=process.env.PINE_REVIEW_SOURCE||path.join(__dirname,'..');
const out=process.env.PINE_LEARNING_SMOKE_OUT||path.join(os.tmpdir(),'pine-prompt-learning-smoke');
let checks=0,network=0;const equal=(a,b)=>{checks++;assert.deepEqual(a,b);};const match=(a,b)=>{checks++;assert.match(a,b);};
app.setPath('userData',path.join(out,'profile'));app.commandLine.appendSwitch('no-sandbox');
app.whenReady().then(async()=>{
 let win;
 try{
  fs.mkdirSync(out,{recursive:true});
  win=new BrowserWindow({show:false,width:1100,height:940,webPreferences:{contextIsolation:true,nodeIntegration:false,offscreen:true,backgroundThrottling:false}});
  win.webContents.session.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_r,cb)=>{network++;cb({cancel:true});});
  await win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<!doctype html><html><body style="background:#0c1410;color:#eee;font:16px system-ui"><button>Learning fixture</button></body></html>'));
  const js=code=>win.webContents.executeJavaScript(code),pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const click=async selector=>{await js(`document.querySelector(${JSON.stringify(selector)}).click();true`);await pause(60);};
  await js(`document.head.append(Object.assign(document.createElement('style'),{textContent:${JSON.stringify(fs.readFileSync(path.join(base,'frontend/rejection-review.css'),'utf8'))}}));true`);
  await js(String.raw`
   window.store=new Map();Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)}});
   window.fx={posts:[],gets:[],defer:false,lost:false,conflict:false};
   fx.policy={enabled:true,max_faults:0,disabled_gates:[],revision:2};
   fx.row={id:'cut-evidence',seq:42,event_seq:42,revision:1,gate:'tint',source:'Keep the copper plate.',candidate:'Keep the copper plate, do not wait.',reasons:['rhetoric was not materially transformed'],technical:false,review_status:'pending',occurrence_current:true,context:{kind:'gallery',marker:'A',turn:1},evaluation:{ok:false,machine_ok:false,machine_faults:['rhetoric was not materially transformed']}};
   fx.status={revision:3,enabled:false,mode:'strict',automation_paused:false,say:'Automatic prompt hints are disabled.',hints:[{id:'gallery:rhyme',kind:'gallery',pattern:'rhyme',text:'Keep the original facts while making the bar endings rhyme. <img src=x onerror=alert(1)>',sources:3,parents:2,operator_confirmed:1,evidence:[{review_id:'cut-evidence',event_seq:42}]}],patterns:[],excluded:{unknown_parent:2},observation_count:14,observation_limit:2000,basis:'Distinct source failures; batch approvals do not train.'};
   fx.history={items:[{revision:3,at:1788820012,reason:'distinct_failure_pattern',before:{revision:2},after:{revision:3},trigger:{review_id:'cut-evidence',event_seq:42}},{revision:1,at:1788820000,reason:'initialized_disabled',before:null,after:{revision:1,enabled:false,mode:'strict'}}],has_more:false,total:2};
   fx.snapshot=()=>structuredClone({ok:true,status:fx.status,history:fx.history,errors:[]});
   window.fixtureRequest=async(route,options={})=>{
    const url=new URL(route,'http://fixture'),method=options.method||'GET';
    if(method==='GET')fx.gets.push(route);
    if(url.pathname==='/api/orchestrator/prompt-learning'&&method==='GET')return fx.snapshot();
    if(url.pathname.startsWith('/api/orchestrator/prompt-learning')&&method==='POST'){
     const body=JSON.parse(options.body);fx.posts.push({route,body});
     if(fx.conflict){fx.conflict=false;fx.status.revision++;throw Error('Revision conflict');}
     if(body.expected_revision!==fx.status.revision)throw Error('Wrong fixture revision');
     if(fx.defer){fx.defer=false;await new Promise(resolve=>fx.release=resolve);}
     if(url.pathname.endsWith('/rollback'))Object.assign(fx.status,{enabled:false,mode:'strict',automation_paused:true,hints:[]});
     else if(body.resume)fx.status.automation_paused=false;
     else if(!url.pathname.endsWith('/refresh'))Object.assign(fx.status,{enabled:body.enabled,mode:body.mode});
     fx.status.revision++;fx.status.say=fx.status.automation_paused?'Automatic changes are paused after rollback.':'Saved learning controls.';
     if(fx.lost){fx.lost=false;throw Error('Lost reply after commit');}
     return {...fx.snapshot(),observed:17};
    }
    if(method==='POST')throw Error('Unexpected fixture mutation '+route);
    if(url.pathname==='/api/orchestrator/rejection-policy')return structuredClone(fx.policy);
    if(url.pathname==='/api/orchestrator/rejections')return {items:[fx.row],events:[],latest_cursor:42,next_after:42,total:1,unreviewed:1,policy:fx.policy};
    if(url.pathname==='/api/orchestrator/rejections/cut-evidence')return structuredClone(fx.row);
    if(url.pathname.endsWith('/workbench'))return {ok:true,review_id:'cut-evidence',event_seq:42,revision:1,occurrence_current:true,messages:{items:[]},trace:{items:[],available:false},operations:[],settings:{enabled:false,revision:1,crystal_instruction:''},diagnostics:{},capabilities:{discuss:true,try_wording:true,apply_wording:true},trials:{items:[{id:'fluid-preview',candidate:fx.row.candidate,evaluation:{ok:true,tint:{machine_ok:false,machine_faults:['rhetoric was not materially transformed'],editorial:{accepted_with_advisories:true,advisory_faults:['rhetoric was not materially transformed']}}},baseline:{revision:1}}]}};
    throw Error('Unexpected fixture read '+route);
   };true;
  `);
  const src=fs.readFileSync(path.join(base,'frontend/rejection-review.js'),'utf8');
  await js(`(async()=>{window.mod=await import('data:text/javascript;base64,${Buffer.from(src).toString('base64')}');window.review=mod.create({request:fixtureRequest,notifications:false});await review.open();return true})()`);
  equal(await js('fx.posts.length'),0);equal(await js('fx.gets.filter(x=>x==="/api/orchestrator/prompt-learning").length'),0);
  await js('document.querySelector("[data-learning-panel]").open=true;true');await pause(100);
  equal(await js('fx.gets.filter(x=>x==="/api/orchestrator/prompt-learning").length'),1);
  equal(await js('document.querySelector("[data-learning=enabled]").getAttribute("role")'),'switch');
  equal(await js('document.querySelector("[data-learning=mode]").value'),'strict');
  match(await js('document.querySelector(".prr-learning-outcomes").textContent'),/not available yet.*cannot show a pass rate/);
  await js('fx.status.outcomes={observations:0,cohorts:[],totals:{raw_passes:0,effective_passes:0}};fx.status.hints[0].recipe_version=2;fx.status.hints[0].phase="exploring";fx.status.hints[0].recipe_reason="Improvement is unproven. <img src=x onerror=alert(1)>";true');
  await click('[data-learning=reload]');
  match(await js('document.querySelector(".prr-learning-outcomes").textContent'),/0 measured production attempts/);
  match(await js('document.querySelector(".prr-learning-recipe").textContent'),/Recipe 2.*Exploring.*unproven/i);
  equal(await js('!!document.querySelector(".prr-learning-recipe img")'),false);
  await js('fx.status.outcomes.observations=26;fx.status.outcomes.measured_attempts={first:{attempts:16,raw_passes:6,effective_passes:8},repair:{attempts:10,raw_passes:3,effective_passes:5}};true');
  await click('[data-learning=reload]');
  match(await js('document.querySelector(".prr-learning-outcomes").textContent'),/26 measured production attempts.*repeated tries.*do not become extra source lines/);
  match(await js('document.querySelector(".prr-learning-outcomes").textContent'),/First attempts: 16 checked; 8 accepted.*6 passed all raw checks/);
  match(await js('document.querySelector(".prr-learning-outcomes").textContent'),/Repairs: 10 checked; 5 accepted.*3 passed all raw checks/);
  const draft=async(enabled,mode)=>js(`var e=document.querySelector('[data-learning=enabled]');e.checked=${enabled};e.dispatchEvent(new Event('change'));var s=document.querySelector('[data-learning=mode]');s.value=${JSON.stringify(mode)};s.dispatchEvent(new Event('change'));true`);
  await draft(true,'fluid');equal(await js('fx.posts.length'),0);
  await click('[data-learning=reload]');equal(await js('fx.posts.length'),0);equal(await js('document.querySelector("[data-learning=mode]").value'),'fluid');
  match(await js('document.querySelector(".prr-learning-result").textContent'),/unsaved.*retained/);
  await js('fx.defer=true;true');await click('[data-learning=save]');await click('[data-learning=save]');
  equal(await js('fx.posts.length'),1);equal(await js('fx.posts[0].body'),{expected_revision:3,enabled:true,mode:'fluid'});
  equal(await js('document.querySelector("[data-policy=master]").disabled'),true);equal(await js('document.querySelector("[data-review=approve-current]").disabled'),true);
  await js('review.close();review.open()');equal(await js('document.querySelector("[data-learning=save]").disabled'),true);
  await js('fx.release();true');await pause(100);
  match(await js('document.querySelector(".prr-learning-result").textContent'),/Saved revision 4/);
  equal(await js('document.querySelector("[data-policy=master]").disabled'),false);
  await draft(false,'strict');await js('fx.lost=true;true');await click('[data-learning=save]');
  equal(await js('fx.posts.length'),2);match(await js('document.querySelector(".prr-learning-result").textContent'),/not confirmed.*draft is retained/);
  equal(await js('document.querySelector("[data-learning=mode]").value'),'strict');match(await js('document.querySelector(".prr-learning-caption").textContent'),/revision 5/);
  await draft(true,'fluid');await js('fx.conflict=true;true');await click('[data-learning=save]');
  equal(await js('fx.posts.length'),3);equal(await js('document.querySelector("[data-learning=mode]").value'),'fluid');
  match(await js('document.querySelector(".prr-learning-caption").textContent'),/revision 6/);
  await click('[data-learning=save]');equal(await js('fx.posts.at(-1).body'),{expected_revision:6,enabled:true,mode:'fluid'});
  await click('[data-learning=refresh]');equal(await js('fx.posts.at(-1)'),{route:'/api/orchestrator/prompt-learning/refresh',body:{expected_revision:7}});
  match(await js('document.querySelector(".prr-learning-result").textContent'),/Reviewed 17/);
  equal(await js('!!document.querySelector(".prr-learning-hint img")'),false);
  const checkerSource=fs.readFileSync(path.join(base,'tools/rejection-review-live-smoke.cjs'),'utf8');
  const checkerBody=checkerSource.split('// LEARNING READ-ONLY CHECK BEGIN')[1]?.split('// LEARNING READ-ONLY CHECK END')[0];
  assert.ok(checkerBody,'The exact delivered-page learning checker is available');
  const countedAssert={equal:(...args)=>{checks++;assert.equal(...args);},deepEqual:(...args)=>{checks++;assert.deepEqual(...args);},ok:(...args)=>{checks++;assert.ok(...args);},match:(...args)=>{checks++;assert.match(...args);}};
  const inspectLearning=new Function('assert','sleep',checkerBody+';return inspectLearning;')(countedAssert,pause);
  const delivered={route:'/radio'},beforeInspectionPosts=await js('fx.posts.length');
  win.setSize(800,940);
  await inspectLearning({run:js,page:delivered,readReady:()=>true,readStatus:()=>js('fx.snapshot()'),capture:async filename=>{
   await js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');await pause(100);
   fs.writeFileSync(path.join(out,filename),(await win.webContents.capturePage()).toPNG());
  }});
  equal(await js('fx.posts.length'),beforeInspectionPosts);equal(delivered.learning.readOnly,true);
  equal(delivered.learning.enabled,true);equal(delivered.learning.mode,'fluid');equal(delivered.learning.hintCount,1);
  fs.copyFileSync(path.join(out,'radio-learning-hints.png'),path.join(out,'learning-active-hints.png'));
  await js('document.querySelector("[data-learning-panel]").open=true;true');
  await click('[data-learning-evidence="cut-evidence"]');
  equal(await js('fx.gets.includes("/api/orchestrator/rejections/cut-evidence?event_seq=42")'),true);
  await click('[data-lab-tab=try]');
  match(await js('document.querySelector(".prr-trial").textContent'),/Acceptance checks passed/);
  match(await js('document.querySelector(".prr-trial").textContent'),/Accepted in fluid mode with style advisories/);
  match(await js('document.querySelector(".prr-trial").textContent'),/machine_ok[\s\S]*false/);
  await js('document.querySelector(".prr-learning-history").open=true;true');await click('[data-learning-rollback="1"]');
  equal(await js('fx.posts.at(-1)'),{route:'/api/orchestrator/prompt-learning/rollback',body:{expected_revision:8,revision:1}});
  match(await js('document.querySelector(".prr-learning-result").textContent'),/paused until you resume/);
  match(await js('document.querySelector(".prr-learning-hints").textContent'),/This revision has no active reminders/);
  await click('[data-learning=resume]');equal(await js('fx.posts.at(-1).body'),{expected_revision:9,resume:true});
  equal(await js('!!document.querySelector("[data-learning=resume]")'),false);
  match(await js('document.querySelector(".prr-learning-result").textContent'),/Rollback pause cleared\. Automatic learning remains off/);
  match(await js('document.querySelector(".prr-learning-scope").textContent'),/Meaning, rhyme, speaker structure, copying and technical checks still apply/);
  match(await js('document.querySelector(".prr-learning-result").getAttribute("role")'),/^status$/);
  for(const width of [800,390]){
   win.setSize(width,940);await js('document.querySelector("[data-learning-panel]").open=true;document.querySelector(".prr-learning-history").open=false;document.querySelector("[data-learning-panel]").scrollIntoView({block:"start"});true');await pause(100);
   equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);equal(await js('document.querySelector(".prr-dialog").scrollWidth<=document.querySelector(".prr-dialog").clientWidth+1'),true);
   for(const field of ['enabled','mode','save'])equal(await js(`(()=>{const r=document.querySelector('[data-learning=${field}]').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.width>0})()`),true);
   fs.writeFileSync(path.join(out,'learning-'+width+'.png'),(await win.webContents.capturePage()).toPNG());
  }
  equal(network,0);equal(await js('fx.posts.every(p=>p.route.startsWith("/api/orchestrator/prompt-learning"))'),true);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:true,checks,networkRequests:network,fixturePosts:await js('fx.posts'),deliveredLearningCheck:delivered.learning,screenshots:['learning-800.png','learning-390.png','learning-active-hints.png',...delivered.learning.screenshots]},null,2));
  console.log(JSON.stringify({ok:true,checks,networkRequests:network,out}));await js('review.destroy();true');win.destroy();app.exit(0);
 }catch(error){fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'error.txt'),error.stack||String(error));if(win&&!win.isDestroyed())fs.writeFileSync(path.join(out,'failure.png'),(await win.webContents.capturePage()).toPNG());console.error(error);app.exit(1);}
});
