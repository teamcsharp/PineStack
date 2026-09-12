// Hidden, fixture-only UI exercise. No station requests, decisions or audio.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const out = path.join(os.tmpdir(), 'pine-rejection-workbench-smoke');
const base = process.env.PINE_REVIEW_SOURCE || path.join(__dirname, '..');
let checks = 0, network = 0;
const equal = (a,b) => {checks++;assert.deepEqual(a,b);};
const match = (a,b) => {checks++;assert.match(a,b);};
app.setPath('userData', path.join(out,'profile'));
app.commandLine.appendSwitch('no-sandbox');
app.whenReady().then(async () => {
  let win;
  try {
    fs.mkdirSync(out,{recursive:true});
    win = new BrowserWindow({show:false,width:1260,height:980,webPreferences:{contextIsolation:true,nodeIntegration:false,offscreen:true,backgroundThrottling:false}});
    win.webContents.on('console-message',(_event,_level,message)=>console.log('[fixture] '+message));
    win.webContents.session.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(_request,callback)=>{network++;callback({cancel:true});});
    await win.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<!doctype html><html><body style="background:#0c1410;color:#eee;font:16px system-ui"><button id="launch">Review fixture</button></body></html>'));
    const js = async code => {try{return await win.webContents.executeJavaScript(code);}catch(error){console.error('Failed fixture expression: '+code.slice(0,1000));throw error;}};
    const pause = ms => new Promise(resolve=>setTimeout(resolve,ms));
    const click = async selector => {await js(`document.querySelector(${JSON.stringify(selector)}).click();true`);await pause(55);};
    await js(`document.head.append(Object.assign(document.createElement('style'),{textContent:${JSON.stringify(fs.readFileSync(path.join(base,'frontend/rejection-review.css'),'utf8'))}}));true`);
    await js(String.raw`
      window.fixtureStorage=new Map();Object.defineProperty(window,'sessionStorage',{configurable:true,value:{getItem:k=>fixtureStorage.get(k)||null,setItem:(k,v)=>fixtureStorage.set(k,v),removeItem:k=>fixtureStorage.delete(k)}});
      window.fx={posts:[],gets:[],defer:false,lost:false,fail:false,ops:new Map(),count:0,policy:{enabled:true,revision:1,max_faults:0,disabled_gates:[]},settings:{enabled:true,revision:1,crystal_instruction:'Preserve meaning.'}};
      fx.row={id:'cut-one',seq:42,event_seq:42,revision:1,gate:'tint',review_status:'pending',occurrence_current:true,read_only:false,
        candidate:'The train crossed the city at midnight.',source:'A train crossed the city at midnight.',reasons:['Semantic preservation failed'],evaluation:{machine_ok:false,meaning_score:0.42},
        context:{kind:'gallery',marker:'A',turn:2},system_path:{stages:['Writing','Tint','Recording'],observed:{gate:'tint',stage:'turn_cut'},note:'Known path; only the observed gate is proven.'}};
      fx.data={ok:true,review_id:'cut-one',event_seq:42,revision:1,occurrence_current:true,read_only:false,
        trace_sources:[{id:'trial-trace',label:'Trial prompt and reply'}],
        messages:{items:[{id:'m1',seq:1,role:'assistant',content:'The retained meaning check failed. The recording queue is still making progress.'}],has_more:true,next_before:1},
        trace:{items:[{id:'tr2',seq:2,stage:'tint',attempt:2,prompt:'EXACT PROMPT '+('Retain every original fact. '.repeat(120))+'PROMPT END <img src=x onerror=alert(1)>',response:'EXACT RESPONSE END',provenance:{origin:'captured'}}],available:true,note:'Captured requests are exact; reconstructed context is labeled.',has_more:true,next_before:2},
        trials:{items:[],has_more:false},operations:[],diagnostics:{recording:{made:12,total:20,observed_at:1788820012}},
        capabilities:{discuss:true,try_wording:true,apply_wording:true}};
      fx.finish=(op)=>{
        op.status=fx.fail?'failed':'completed';op.error=fx.fail?'The model request failed.':null;
        if(op.status==='completed'&&op.kind==='discuss')fx.data.messages.items.push({id:'m'+op.id,seq:10+fx.count,role:'assistant',content:'Saved reply for '+op.body.message});
        if(op.status==='completed'&&op.kind==='try')fx.data.trials.items.unshift({id:'trial-'+op.id,seq:10+fx.count,candidate:op.body.candidate||'A train crossed the city at midnight.',baseline:{source:fx.row.source,candidate:fx.row.candidate,revision:fx.row.revision},evaluation:{ok:true,tint:{machine_ok:true,machine_faults:[]}},provenance:{origin:'new_trial',prompt:'ACTUAL TRIAL PROMPT'}});
        if(op.status==='completed'&&op.kind==='apply'){fx.row.revision++;fx.data.revision=fx.row.revision;op.result={effect:{status:'queued',say:'Revised wording queued for recording; no playback requested.'}};}
        return op;
      };
      window.fixtureRequest=async(route,options={})=>{
        const url=new URL(route,'http://fixture'),method=options.method||'GET';
        if(method==='GET')fx.gets.push(route);
        if(url.pathname==='/api/orchestrator/rejection-policy')return structuredClone(fx.policy);
        if(url.pathname==='/api/orchestrator/rejections')return {items:[fx.row],events:[],latest_cursor:42,next_after:42,total:1,unreviewed:1,policy:fx.policy};
        if(url.pathname==='/api/orchestrator/rejection-lab/settings'){
          const body=JSON.parse(options.body);fx.posts.push({route,body});
          if(body.expected_revision!==fx.settings.revision)throw Error('Settings revision conflict');
          fx.settings={...body,revision:fx.settings.revision+1};return {ok:true,settings:structuredClone(fx.settings)};
        }
        if(url.pathname==='/api/orchestrator/rejections/cut-one')return structuredClone(fx.row);
        if(url.pathname.endsWith('/workbench')){
          if(fx.failRead){fx.failRead=false;throw Error('Temporary workbench read failure');}
          const data=structuredClone({...fx.data,settings:fx.settings,operations:[...fx.ops.values()]});
          if(url.searchParams.get('trace_id')==='trial-trace')data.trace={items:[{seq:900,record:{stage:'model_request',prompt:'FULL TRIAL WIRE REQUEST',response:'FULL TRIAL RAW REPLY'}}],has_more:false,available:true};
          if(url.searchParams.has('trace_before'))data.trace={items:[{id:'tr1',seq:1,stage:'writing',prompt:'OLDER EXACT PROMPT END',provenance:{origin:'captured'}}],has_more:false};
          if(url.searchParams.has('messages_before'))data.messages={items:[{id:'m0',seq:0,role:'user',content:'OLDER SAVED DISCUSSION'}],has_more:false};
          return data;
        }
        if(method==='POST'){
          const kind=url.pathname.split('/').at(-1),body=JSON.parse(options.body);fx.posts.push({route,body});
          if(fx.rejectBefore)throw Error('Connection failed before acceptance');
          if(fx.ops.has(body.request_id))return {ok:true,operation:structuredClone(fx.ops.get(body.request_id))};
          if(body.expected_revision!==fx.row.revision)throw Error('Review revision conflict');
          if(body.event_seq!==42)throw Error('Wrong event');
          const op={id:body.request_id,request_id:body.request_id,kind,status:'running',body};fx.ops.set(op.id,op);fx.count++;
          if(kind==='discuss')fx.data.messages.items.push({id:'u'+op.id,seq:5+fx.count,role:'user',content:body.message});
          if(!fx.defer)fx.finish(op);
          if(fx.delayAck){fx.delayAck=false;await new Promise(resolve=>fx.releaseAck=resolve);}
          if(fx.lost){fx.lost=false;throw Error('Response lost after commit');}
          return {ok:true,operation:structuredClone(op)};
        }
        throw Error('Unexpected fixture route '+route);
      };true;
    `);
    const source=fs.readFileSync(path.join(base,'frontend/rejection-review.js'),'utf8');
    await js(`(async()=>{window.mod=await import('data:text/javascript;base64,${Buffer.from(source).toString('base64')}');window.review=mod.create({request:fixtureRequest,notifications:false});await review.open({id:'cut-one',event_seq:42});return true})()`);
    equal(await js('document.querySelector("[data-policy=master]").getAttribute("aria-checked")'),'true');
    equal(await js('!!document.querySelector("[data-review=approve-current]")'),true);
    equal(await js('fx.gets.includes("/api/orchestrator/rejections/cut-one?event_seq=42")'),true);
    await click('[data-lab-tab=trace]');
    match(await js('document.querySelector(".prr-workbench").textContent'),/PROMPT END/);
    await js('var pick=document.querySelector("[data-lab=trace-source]");pick.value="trial-trace";pick.dispatchEvent(new Event("change"));true');await pause(60);
    match(await js('document.querySelector(".prr-workbench").textContent'),/FULL TRIAL WIRE REQUEST/);
    match(await js('document.querySelector(".prr-workbench").textContent'),/FULL TRIAL RAW REPLY/);
    equal(await js('fx.gets.some(route=>route.includes("event_seq=42&trace_id=trial-trace"))'),true);
    await js('var pick=document.querySelector("[data-lab=trace-source]");pick.value="";pick.dispatchEvent(new Event("change"));true');await pause(60);
    match(await js('document.querySelector(".prr-workbench").textContent'),/EXACT RESPONSE END/);
    equal(await js('!!document.querySelector(".prr-workbench img")'),false);
    await click('[data-lab-more=trace]');
    match(await js('document.querySelector(".prr-workbench").textContent'),/OLDER EXACT PROMPT END/);
    match(await js('document.querySelector(".prr-workbench").textContent'),/PROMPT END/);
    await js('document.querySelector(".prr-lab-settings").open=true;const field=document.querySelector("[data-lab-field=future]");field.value="Keep natural metaphors and every factual claim.";field.dispatchEvent(new Event("input"));true');
    equal(await js('fx.posts.length'),0);
    await click('[data-lab=settings]');
    equal(await js('fx.posts.length'),1);
    equal(await js('fx.settings.crystal_instruction'),'Keep natural metaphors and every factual claim.');
    match(await js('document.querySelector(".prr-lab-result").textContent'),/Future crystal instruction saved/);
    await click('[data-lab-tab=discuss]');
    await click('[data-lab-more=messages]');
    match(await js('document.querySelector(".prr-chat-log").textContent'),/OLDER SAVED DISCUSSION/);
    await js('fx.defer=true;var f=document.querySelector("[data-lab-field=message]");f.value="Why did the meaning gate cut this?";f.dispatchEvent(new Event("input"));true');
    await click('[data-lab=discuss]');await click('[data-lab=discuss]');
    equal(await js('fx.posts.filter(p=>p.route.endsWith("/discuss")).length'),1);
    equal(await js('document.querySelector("[data-policy=master]").disabled'),true);
    equal(await js('document.querySelector("[data-review=approve-current]").disabled'),true);
    equal(await js('fx.posts.at(-1).body.event_seq'),42);
    equal(await js('fx.posts.at(-1).body.expected_revision'),1);
    await js('review.close();review.open({id:"cut-one",event_seq:42})');
    match(await js('document.querySelector(".prr-lab-result").textContent'),/working/);
    await js('fx.defer=false;fx.finish([...fx.ops.values()].at(-1));true');
    await click('[data-lab=refresh]');
    match(await js('document.querySelector(".prr-chat-log").textContent'),/Saved reply for Why did/);
    equal(await js('document.querySelector("[data-policy=master]").disabled'),false);
    equal(await js('fx.posts.filter(p=>p.route.includes("settings")).length'),1);
    await js('fx.lost=true;var f=document.querySelector("[data-lab-field=message]");f.value="Explain the recorded prompt.";f.dispatchEvent(new Event("input"));true');
    await click('[data-lab=discuss]');
    match(await js('document.querySelector(".prr-lab-result").textContent'),/not confirmed/);
    equal(await js('document.querySelector("[data-lab=retry]").disabled'),false);
    await click('[data-lab=retry]');
    equal(await js('fx.posts.at(-1).body.request_id===fx.posts.at(-2).body.request_id'),true);
    equal(await js('fx.ops.size'),2);
    await js('fx.rejectBefore=true;var f=document.querySelector("[data-lab-field=message]");f.value="Retain this unconfirmed request across a reload.";f.dispatchEvent(new Event("input"));true');
    await click('[data-lab=discuss]');
    await js('window.unconfirmed=fx.posts.at(-1).body.request_id;true');
    await click('[data-lab=refresh]');
    equal(await js('!!document.querySelector("[data-lab=retry]")'),true);
    await js('review.destroy();window.review=mod.create({request:fixtureRequest,notifications:false});review.open({id:"cut-one",event_seq:42})');
    await click('[data-lab-tab=discuss]');
    equal(await js('!!document.querySelector("[data-lab=retry]")'),true);
    await js('fx.rejectBefore=false;true');await click('[data-lab=retry]');
    equal(await js('fx.posts.at(-1).body.request_id'),await js('unconfirmed'));
    equal(await js('fx.ops.size'),3);
    await js('fx.delayAck=true;var f=document.querySelector("[data-lab-field=message]");f.value="First message with a delayed acknowledgment.";f.dispatchEvent(new Event("input"));true');
    await click('[data-lab=discuss]');
    await js('var f=document.querySelector("[data-lab-field=message]");f.value="Draft written while the earlier send was pending.";f.dispatchEvent(new Event("input"));true');
    await click('[data-lab=refresh]');
    equal(await js('document.querySelector("[data-policy=master]").disabled'),true);
    await js('fx.releaseAck();true');await pause(60);
    equal(await js('document.querySelector("[data-lab-field=message]").value'),'Draft written while the earlier send was pending.');
    equal(await js('document.querySelector("[data-policy=master]").disabled'),false);
    await js('fx.failRead=true;true');await click('[data-lab=discuss]');
    match(await js('document.querySelector(".prr-lab-result").textContent'),/read failure/);
    equal(await js('document.querySelector("[data-lab=retry]").disabled'),false);
    await click('[data-lab=retry]');
    equal(await js('fx.posts.at(-1).body.request_id===fx.posts.at(-2).body.request_id'),true);
    await click('[data-lab-tab=try]');
    await js('var f=document.querySelector("[data-lab-field=candidate]");f.value="A train crossed the city at midnight.";f.dispatchEvent(new Event("input"));true');
    equal(await js('fx.posts.filter(p=>p.route.endsWith("/try")).length'),0);
    await click('[data-lab=try]');
    equal(await js('document.querySelectorAll(".prr-trial").length'),1);
    match(await js('document.querySelector(".prr-trial").textContent'),/machine_ok[\s\S]*true/);
    await js('fx.data.trials.items.push({...structuredClone(fx.data.trials.items[0]),id:"failed-trial",evaluation:{ok:false,tint:{machine_ok:false,machine_faults:["meaning"]}}});true');
    await click('[data-lab=refresh]');
    equal(await js('document.querySelector("[data-trial-id=failed-trial] [data-lab=apply]").disabled'),true);
    match(await js('document.querySelector("[data-trial-id=failed-trial]").textContent'),/did not pass[\s\S]*machine_ok[\s\S]*false/);
    equal(await js('fx.posts.filter(p=>p.route.endsWith("/apply")).length'),0);
    await click('[data-lab=apply]');
    equal(await js('fx.posts.at(-1).body.trial_id'),await js('document.querySelector(".prr-trial").dataset.trialId'));
    match(await js('document.querySelector(".prr-lab-result").textContent'),/queued for recording/);
    equal(await js('fx.row.revision'),2);
    await js('fx.fail=true;true');await click('[data-lab=try]');
    match(await js('document.querySelector(".prr-lab-result").textContent'),/request failed/i);
    equal(await js('[...document.querySelectorAll(".prr-workbench button")].some(b=>b.textContent==="Start a new attempt")'),true);
    await js('window.failedId=fx.posts.at(-1).body.request_id;fx.fail=false;[...document.querySelectorAll(".prr-workbench button")].find(b=>b.textContent==="Start a new attempt").click();true');await pause(60);
    equal(await js('fx.posts.at(-1).body.request_id!==failedId'),true);
    equal(await js('fx.posts.at(-1).body.expected_revision'),2);
    await js('fx.data.read_only=true;fx.data.occurrence_current=false;fx.row.read_only=true;fx.row.occurrence_current=false;true');
    await click('[data-lab=refresh]');
    equal(await js('document.querySelector("[data-lab=try]").disabled'),true);
    equal(await js('document.querySelector("[data-lab=apply]").disabled'),true);
    await click('[data-lab-tab=discuss]');
    equal(await js('document.querySelector("[data-lab=discuss]").disabled'),false);
    await js('document.querySelector("[data-lab-tab=discuss]").focus();document.activeElement.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true}));true');
    equal(await js('document.activeElement.dataset.labTab'),'trace');
    equal(await js('document.querySelector("[data-lab-tab=trace]").getAttribute("aria-selected")'),'true');
    await js('fx.data.read_only=false;fx.data.occurrence_current=true;fx.row.read_only=false;fx.row.occurrence_current=true;true');
    await click('[data-lab=refresh]');
    await js('fx.ops.set("server-started",{id:"server-started",request_id:"server-started",kind:"discuss",status:"pending",body:{message:"A request started from another window."}});review.destroy();fixtureStorage.clear();window.review=mod.create({request:fixtureRequest,notifications:false});review.open({id:"cut-one",event_seq:42})');
    await click('[data-lab-tab=discuss]');
    match(await js('document.querySelector(".prr-lab-result").textContent'),/orchestrator is working on a saved discussion request/i);
    equal(await js('document.querySelector("[data-lab=discuss]").disabled'),true);
    equal(await js('document.querySelector("[data-policy=master]").disabled'),true);
    equal(await js('[...fixtureStorage.keys()].filter(key=>key.startsWith("pine-review-lab:")).length'),0);
    await js('fx.finish(fx.ops.get("server-started"));true');await click('[data-lab=refresh]');
    match(await js('document.querySelector(".prr-chat-log").textContent'),/Saved reply for A request started from another window/);
    equal(await js('document.querySelector("[data-lab=discuss]").disabled'),false);
    equal(await js('document.querySelector("[data-policy=master]").disabled'),false);
    for(const [tab,width] of [['discuss',800],['trace',800],['try',800],['discuss',390]]){
      win.setSize(width,940);await click('[data-lab-tab='+tab+']');
      await js('document.querySelector(".prr-dialog").scrollTop=0;document.querySelector(".prr-detail").scrollTop=0;true');await pause(80);
      equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);
      equal(await js('document.querySelector(".prr-dialog").scrollWidth<=document.querySelector(".prr-dialog").clientWidth+1'),true);
      if(tab==='discuss'&&width===800){
        equal(await js('document.querySelector("[data-lab-field=message]").getBoundingClientRect().bottom<innerHeight'),true);
        equal(await js('document.querySelector("[data-lab=discuss]").getBoundingClientRect().bottom<innerHeight'),true);
        equal(await js('document.querySelector("[data-lab=discuss]").getBoundingClientRect().bottom<document.querySelector(".prr-chat-log").getBoundingClientRect().top'),true);
      }
      fs.writeFileSync(path.join(out,tab+'-'+width+'.png'),(await win.webContents.capturePage()).toPNG());
    }
    equal(network,0);
    const posts=await js('fx.posts.map(p=>({route:p.route,event_seq:p.body.event_seq,request_id:p.body.request_id}))');
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:true,checks,networkRequests:network,fixturePosts:posts.length,posts},null,2));
    console.log(JSON.stringify({ok:true,checks,out,networkRequests:network}));
    await js('review.destroy();true');win.destroy();app.exit(0);
  }catch(error){fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'error.txt'),error.stack||String(error));if(win&&!win.isDestroyed())fs.writeFileSync(path.join(out,'failure.png'),(await win.webContents.capturePage()).toPNG());console.error(error);app.exit(1);}
});
