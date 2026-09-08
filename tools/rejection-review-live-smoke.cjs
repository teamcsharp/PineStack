// Read-only delivered-page smoke. Run only after the deployment owner says the
// backend is ready. Credentials stay in memory; no station writes or media.
const {app, BrowserWindow, session} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const out = path.join(os.tmpdir(), 'pine-rejection-review-live-smoke');
const pipelineCheck = process.argv.includes('--pipeline');
const workbenchCheck = process.argv.includes('--workbench');
const learningCheck = process.argv.includes('--learning');
const configFile = process.env.PINE_REVIEW_CONFIG || path.join(process.env.APPDATA, 'pinebox-desktop', 'pinebox-desktop.json');
const config = JSON.parse(fs.readFileSync(configFile, 'utf8'));
const origin = new URL(config.baseUrl).origin;
const secret = String(config.apiKey || '');
if (!secret) throw new Error('The existing desktop configuration has no API credential.');
const safe = value => String(value || '').split(secret).join('[redacted]');
app.setPath('userData', path.join(out, 'profile'));
app.commandLine.appendSwitch('no-sandbox');
app.commandLine.appendSwitch('autoplay-policy', 'document-user-activation-required');
app.on('window-all-closed', () => {}); // Keep the helper alive between pages.
fs.mkdirSync(out, {recursive: true});
const preload = path.join(out, 'readonly-preload.cjs');
fs.writeFileSync(preload, String.raw`
  window.__reviewLiveProbe = {playAttempts:0, errors:[]};
  HTMLMediaElement.prototype.play = function(){window.__reviewLiveProbe.playAttempts++;this.muted=true;return Promise.reject(new DOMException('Media disabled for read-only verification','NotAllowedError'));};
  window.addEventListener('error',e=>window.__reviewLiveProbe.errors.push({message:String(e.message||''),file:String(e.filename||'')}));
  window.addEventListener('unhandledrejection',e=>{if(e.reason?.name!=='NotAllowedError')window.__reviewLiveProbe.errors.push({message:String(e.reason?.message||e.reason||''),file:''});});
  if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Microphone disabled for read-only verification','NotAllowedError');};
  for(const name of ['AudioContext','webkitAudioContext'])if(window[name])window[name].prototype.resume=async()=>{throw new DOMException('Audio disabled for read-only verification','NotAllowedError');};
`);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
// WORKBENCH READ-ONLY CHECK BEGIN
async function inspectWorkbench({run,capture,page,readReady}) {
  const waitFor = async (predicate, message) => {
    for (let attempt=0;attempt<80;attempt++) { if (await predicate()) return; await sleep(150); }
    throw new Error(message);
  };
  const tabs = await run('[...document.querySelectorAll("[data-lab-tab]")].map(node=>node.dataset.labTab)');
  for (const name of ['review','discuss','trace','try']) assert.ok(tabs.includes(name),'Missing delivered workbench tab: '+name);
  const prefix=page.route==='/radio'?'radio':'control';
  page.workbench={tabs,readOnly:true,screenshots:[]};
  await run('document.querySelector("[data-lab-tab=discuss]").click();true;');
  await waitFor(readReady,'No successful event-pinned workbench GET was observed');
  await waitFor(()=>run('!!document.querySelector("[data-lab-field=message]")'),'Discussion composer did not load');
  // Show the correspondence controls, without focusing or submitting a form.
  await run('document.querySelector("[data-lab-field=message]").scrollIntoView({block:"center"});true;');
  const discuss=await run(`(function(){const input=document.querySelector('[data-lab-field=message]'),send=document.querySelector('[data-lab=discuss]'),log=document.querySelector('.prr-chat-log');
    const visible=node=>{if(!node?.getClientRects().length)return false;const rect=node.getBoundingClientRect();return rect.top>=0&&rect.bottom<=innerHeight;};
    return {composer:visible(input),send:visible(send),
      beforeHistory:!!input&&!!log&&input.getBoundingClientRect().top<log.getBoundingClientRect().top,
      requestError:/Workbench unavailable:/.test(document.querySelector('.prr-lab-result')?.textContent||'')};})()`);
  assert.equal(discuss.composer,true);assert.equal(discuss.send,true);assert.equal(discuss.beforeHistory,true);
  assert.equal(discuss.requestError,false,'Workbench GET failed in the delivered UI');
  page.workbench.discussion=discuss;
  const discussionFile=prefix+'-workbench-discuss.png';await capture(discussionFile);page.workbench.screenshots.push(discussionFile);

  await run('document.querySelector("[data-lab-tab=trace]").click();true;');
  await waitFor(()=>run('document.querySelector("[data-lab=settings]")?.dataset.unavailable === "false"'), 'Trace did not receive the saved workbench settings and diagnostics');
  const trace=await run(`(function(){const panel=document.querySelector('.prr-workbench'),text=panel.textContent;
    const diagnostic=[...panel.querySelectorAll('details')].find(node=>node.querySelector('summary')?.textContent==='Observed pipeline diagnostics');
    const evidence=[...panel.querySelectorAll('details')].filter(node=>!['Recorded workflow and gate','Observed pipeline diagnostics','Future crystal instruction','Last operation result'].includes(node.querySelector('summary')?.textContent));
    return {diagnostics:!!diagnostic&&diagnostic.querySelector('pre')?.textContent!=='Unavailable',
      captured:/Exact captured requests, raw replies|captured requests are exact/i.test(text),
      older:/predates exact prompt capture|No original prompt trace was captured/i.test(text),
      evidenceSections:evidence.length,traceSelector:!!panel.querySelector('[data-lab=trace-source]')};})()`);
  assert.equal(trace.diagnostics,true,'The delivered trace has no observed pipeline diagnostics');
  assert.ok(trace.older||(trace.captured&&trace.evidenceSections>0),'Trace lacks exact evidence or an honest missing-capture explanation');
  page.workbench.trace=trace;
  await run('document.querySelector(".prr-detail").scrollTop=0;document.querySelector("[data-lab-tab=trace]").scrollIntoView({block:"start"});true;');
  const traceFile=prefix+'-workbench-trace.png';await capture(traceFile);page.workbench.screenshots.push(traceFile);

  await run('document.querySelector("[data-lab-tab=try]").click();true;');
  const trial=await run(`(function(){const panel=document.querySelector('.prr-workbench'),preview=panel.querySelector('[data-lab=try]');
    return {candidate:!!panel.querySelector('[data-lab-field=candidate]'),instruction:!!panel.querySelector('[data-lab-field=instruction]'),
      preview:!!preview,previewBlocked:!!preview?.disabled,supported:preview?.dataset.unavailable!=='true',
      explanation:/Discussion is available|not supported|requires|need a retained|Historical evidence|read-only|working|current rules/i.test(panel.textContent)};})()`);
  assert.equal(trial.candidate,true);assert.equal(trial.instruction,true);assert.equal(trial.preview,true);
  if(trial.previewBlocked&&!trial.supported)assert.equal(trial.explanation,true,'Blocked trial has no visible support or current-state explanation');
  page.workbench.trial=trial;
  await run('document.querySelector("[data-lab-field=candidate]").scrollIntoView({block:"center"});true;');
  const trialFile=prefix+'-workbench-try.png';await capture(trialFile);page.workbench.screenshots.push(trialFile);
  await run('document.querySelector("[data-lab-tab=review]").click();true;');
}
// WORKBENCH READ-ONLY CHECK END
// LEARNING READ-ONLY CHECK BEGIN
async function inspectLearning({run,capture,page,readReady,readStatus}) {
  const waitFor=async(predicate,message)=>{
    for(let attempt=0;attempt<80;attempt++){if(await predicate())return;await sleep(150);}
    throw new Error(message);
  };
  assert.equal(await run('!!document.querySelector("[data-learning-panel]")'),true,'Delivered page has no Learn and improve controls');
  await run('document.querySelector(".prr-overview").open=false;document.querySelector("[data-learning-panel]").open=true;true;');
  await waitFor(readReady,'No successful read-only learning status GET was observed');
  await waitFor(()=>run('document.querySelector("[data-learning=mode]")?.dataset.unavailable === "false"'),'Saved learning controls did not finish loading');
  const current=await readStatus();
  assert.equal(current.ok,true,'Learning status endpoint did not return success');
  const saved=current.status;
  assert.ok(Number.isSafeInteger(saved.revision)&&saved.revision>0,'Learning revision is missing');
  assert.ok(['strict','fluid'].includes(saved.mode),'Unknown delivered acceptance mode');
  const visible=await run(`(()=>{const area=document.querySelector('[data-learning-panel]');return {
    enabled:area.querySelector('[data-learning=enabled]').checked,
    mode:area.querySelector('[data-learning=mode]').value,
    revision:Number(area.querySelector('.prr-learning-caption').textContent.match(/revision (\\d+)/)?.[1]),
    hints:area.querySelectorAll('.prr-learning-hint').length,
    save:!!area.querySelector('[data-learning=save]'),refresh:!!area.querySelector('[data-learning=refresh]'),
    scope:area.querySelector('.prr-learning-scope').textContent,
    error:area.querySelector('.prr-learning-result').classList.contains('prr-error'),
    horizontalOverflow:document.querySelector('.prr-dialog').scrollWidth>document.querySelector('.prr-dialog').clientWidth+1};})()`);
  assert.equal(visible.enabled,saved.enabled);assert.equal(visible.mode,saved.mode);assert.equal(visible.revision,saved.revision);
  assert.equal(visible.hints,(saved.hints||[]).length);assert.equal(visible.save,true);assert.equal(visible.refresh,true);
  assert.match(visible.scope,/Meaning, rhyme, speaker structure, copying and technical checks still apply/);
  assert.equal(visible.error,false);assert.equal(visible.horizontalOverflow,false);
  const prefix=page.route==='/radio'?'radio':'control';
  page.learning={readOnly:true,enabled:saved.enabled,mode:saved.mode,revision:saved.revision,
    hintCount:visible.hints,hintIds:(saved.hints||[]).map(hint=>hint.id),automationPaused:!!saved.automation_paused,screenshots:[]};
  await run('document.querySelector("[data-learning-panel]").scrollIntoView({block:"start"});true;');
  const controlsFile=prefix+'-learning-controls.png';await capture(controlsFile);page.learning.screenshots.push(controlsFile);
  await run('document.querySelector(".prr-learning-hints").scrollIntoView({block:"start"});true;');
  const hintsFile=prefix+'-learning-hints.png';await capture(hintsFile);page.learning.screenshots.push(hintsFile);
  await run('document.querySelector(".prr-learning-history").open=true;document.querySelector(".prr-learning-history").scrollIntoView({block:"start"});true;');
  const history=await run(`(()=>{const box=document.querySelector('.prr-learning-history');return {
    entries:box.querySelectorAll('.prr-learning-revision').length,
    rollbacks:[...box.querySelectorAll('[data-learning-rollback]')].map(node=>Number(node.dataset.learningRollback)),
    pauseExplained:/Automatic changes then pause until you explicitly resume/.test(box.textContent),
    playing:[...document.querySelectorAll('audio,video')].filter(node=>!node.paused&&!node.ended).length};})()`);
  const prior=(current.history?.items||[]).filter(entry=>entry.revision!==saved.revision).map(entry=>entry.revision);
  assert.deepEqual(history.rollbacks,prior);assert.equal(history.pauseExplained,true);assert.equal(history.playing,0);
  page.learning.historyEntries=history.entries;page.learning.rollbackRevisions=history.rollbacks;
  const historyFile=prefix+'-learning-history.png';await capture(historyFile);page.learning.screenshots.push(historyFile);
  await run('document.querySelector("[data-learning-panel]").open=false;true;');
}
// LEARNING READ-ONLY CHECK END
app.whenReady().then(async () => {
  let win;
  const report = {ok:false,realPages:true,writesSent:0,blockedWrites:[],blockedMedia:0,externalBlocked:0,workbenchReads:[],learningReads:[],pages:[]};
  try {
    const partition = session.fromPartition('review-live-' + Date.now());
    partition.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
    partition.webRequest.onBeforeRequest((details,callback)=>{
      let url;try{url=new URL(details.url);}catch(_){callback({cancel:true});return;}
      if(!['GET','HEAD'].includes(details.method)){
        report.blockedWrites.push({method:details.method,path:url.pathname});callback({cancel:true});return;
      }
      if(details.resourceType==='media'||/^wss?:/.test(url.protocol)||/\.(?:mp3|wav|ogg|m4a|aac|flac|mp4|webm)(?:$|\/)/i.test(url.pathname)||/\/(?:audio|stream)(?:\/|$)/i.test(url.pathname)){
        report.blockedMedia++;callback({cancel:true});return;
      }
      if(!['data:','blob:','about:'].includes(url.protocol)&&url.origin!==origin){report.externalBlocked++;callback({cancel:true});return;}
      callback({cancel:false});
    });
    partition.webRequest.onBeforeSendHeaders((details,callback)=>{
      const headers={...details.requestHeaders};
      if(new URL(details.url).origin===origin)headers.Authorization='Bearer '+secret;
      callback({requestHeaders:headers});
    });
    partition.webRequest.onCompleted(details=>{
      const url=new URL(details.url);
      if(url.origin===origin&&details.method==='GET'&&/^\/api\/orchestrator\/rejections\/[^/]+\/workbench$/.test(url.pathname)){
        report.workbenchReads.push({path:url.pathname,event_seq:Number(url.searchParams.get('event_seq'))||null,status:details.statusCode});
      }
      if(url.origin===origin&&details.method==='GET'&&url.pathname==='/api/orchestrator/prompt-learning'){
        report.learningReads.push({path:url.pathname,status:details.statusCode});
      }
    });
    for(const route of ['/radio','/']){
      win=new BrowserWindow({show:false,width:1320,height:1020,webPreferences:{session:partition,preload,
        contextIsolation:false,nodeIntegration:false,offscreen:true,backgroundThrottling:false}});
      win.webContents.setAudioMuted(true);
      const run=code=>win.webContents.executeJavaScript(code,false);
      const capture=async filename=>{
        await run('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
        await sleep(350); // Hidden capturePage otherwise may return the prior compositor frame.
        fs.writeFileSync(path.join(out,filename),(await win.webContents.capturePage()).toPNG());
      };
      await win.loadURL(origin+route);
      await win.webContents.insertCSS('#apiKey,[name="apiKey"],input[type="password"]{visibility:hidden!important}');
      let ready=false;
      for(let attempt=0;attempt<80;attempt++){
        ready=await run('!!(window.PineRejectionReview && typeof window.PineRejectionReview.open==="function")');
        if(ready)break;await sleep(250);
      }
      assert.equal(ready,true,'Delivered '+route+' did not automatically boot the review module');
      const page={route,automaticBoot:true,buttonFound:false,dialog:false};
      if(route==='/radio'){
        page.buttonFound=await run('(function(){const b=[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="Rejected lines");if(!b)return false;b.click();return true;})()');
      }else{
        await run('orchOpen();true;');await sleep(250);
        page.buttonFound=await run('(function(){const b=[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="Rejected lines");if(!b)return false;b.click();return true;})()');
      }
      assert.equal(page.buttonFound,true,'Delivered '+route+' has no usable Rejected lines button');
      for(let attempt=0;attempt<60;attempt++){
        page.dialog=await run('!!document.querySelector(".prr-dialog[open]")');
        if(page.dialog)break;await sleep(200);
      }
      assert.equal(page.dialog,true,'Review button did not open the dialog');
      await run('window.PineRejectionReview.poll()');
      await run('document.querySelector(".prr-overview").open=true;true;');
      for(let attempt=0;attempt<60;attempt++){
        const done=await run('document.querySelector(".prr-room").textContent.includes("Writing room")');
        if(done)break;await sleep(200);
      }
      const state=await run(`({rows:document.querySelectorAll('.prr-row').length,
        pendingLabel:document.querySelector('.prr-header p').textContent,
        roomText:document.querySelector('.prr-room').textContent,
        dialogWidth:document.querySelector('.prr-dialog').clientWidth,
        dialogScrollWidth:document.querySelector('.prr-dialog').scrollWidth,
        connection:document.querySelector('.prr-connection').textContent,
        hasPolicy:!!document.querySelector('[data-policy=max_faults]'),
        masterVisible:!!document.querySelector('[role=switch][data-policy=master]')?.getClientRects().length,
        masterState:document.querySelector('[role=switch][data-policy=master]')?.getAttribute('aria-checked'),
        batchVisible:!!document.querySelector('[data-review=approve-current]')?.getClientRects().length,
        advancedClosed:!document.querySelector('.prr-policy').open,
        moduleErrors:window.__reviewLiveProbe.errors.filter(e=>e.file.includes('/orchestrator-review/')||/PineRejectionReview|radioReviewBoot|lineReviewBoot/.test(e.message)),
        playAttempts:window.__reviewLiveProbe.playAttempts,
        playing:[...document.querySelectorAll('audio,video')].filter(m=>!m.paused&&!m.ended).length})`);
      assert.match(state.roomText,/Writing room/);assert.match(state.roomText,/Recording room/);
      if(pipelineCheck){
        assert.match(state.roomText,/current editorial contract and every required audio take/);
        assert.match(state.roomText,/bottleneck/);
        page.pipelineRoom=true;
      }
      assert.match(state.roomText,/Writing.*on-air path/);assert.equal(state.hasPolicy,true);
      assert.equal(state.masterVisible,true,'Master switch is visible without expanding controls');
      assert.equal(state.batchVisible,true,'Approve all is visible without expanding controls');
      assert.equal(state.advancedClosed,true);
      assert.ok(['true','false'].includes(state.masterState));
      assert.equal(state.dialogScrollWidth<=state.dialogWidth,true,'Horizontal review overflow');
      assert.equal(state.playing,0,'A media element started during read-only verification');
      assert.deepEqual(state.moduleErrors,[],'Delivered rejection module emitted errors');
      Object.assign(page,{rows:state.rows,pendingLabel:safe(state.pendingLabel),roomLoaded:true,policyPresent:true,
        masterVisible:state.masterVisible,masterState:state.masterState,batchVisible:state.batchVisible,
        moduleErrors:state.moduleErrors,playAttempts:state.playAttempts,playing:state.playing,connection:safe(state.connection)});
      page.roomScreenshot=route==='/radio'?'radio-room.png':'control-room.png';
      await capture(page.roomScreenshot);
      if(workbenchCheck&&!state.rows){
        await run('const filter=document.querySelector("[data-filter=status]");filter.value="all";filter.dispatchEvent(new Event("change"));true;');
        for(let attempt=0;attempt<60;attempt++){
          state.rows=await run('document.querySelectorAll(".prr-row").length');
          if(state.rows)break;await sleep(150);
        }
        assert.ok(state.rows>0,'No retained rejection is available for the requested workbench check');
        page.workbenchUsedAllDecisions=true;
      }
      if(state.rows){
        await run('document.querySelector(".prr-overview").open=false;document.querySelector(".prr-row").click();true;');
        for(let attempt=0;attempt<60;attempt++){
          if(await run('!!document.querySelector(".prr-verdict")'))break;await sleep(200);
        }
        page.fullRecord=await run('!!document.querySelector(".prr-verdict") && document.querySelector(".prr-detail").textContent.includes("Original source")');
        assert.equal(page.fullRecord,true,'A real rejection row did not load full evidence');
        if(workbenchCheck){
          const before=report.workbenchReads.length;
          await inspectWorkbench({run,capture,page,readReady:()=>report.workbenchReads.slice(before).some(item=>item.status===200&&item.event_seq>0)});
        }
      }
      if(learningCheck){
        const before=report.learningReads.length;
        await inspectLearning({run,capture,page,
          readReady:()=>report.learningReads.slice(before).some(item=>item.status===200),
          readStatus:()=>run('fetch("/api/orchestrator/prompt-learning").then(response=>{if(!response.ok)throw new Error("Learning status HTTP "+response.status);return response.json();})')});
        assert.equal(report.blockedWrites.filter(item=>item.path.startsWith('/api/orchestrator/prompt-learning')).length,0,'Read-only learning inspection attempted a mutation');
      }
      const filename=route==='/radio'?'radio-review.png':'control-review.png';
      await capture(filename);page.screenshot=filename;
      if(pipelineCheck && route==='/'){
        await run('window.PineRejectionReview.close();orchLogicPanel();true;');
        let visible=false;
        for(let attempt=0;attempt<80;attempt++){
          visible=await run('[...document.querySelectorAll("b")].some(e=>e.textContent==="Work moving through the rooms" && e.getClientRects().length)');
          if(visible)break;await sleep(200);
        }
        assert.equal(visible,true,'Orchestrator did not show the actual pipeline status');
        await capture('orchestrator-pipeline.png');
        const opened=await run('(function(){const b=[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="Inspect rejected lines");if(!b)return false;b.click();return true;})()');
        assert.equal(opened,true,'Pipeline view has no rejection inspection control');
        for(let attempt=0;attempt<60;attempt++){
          if(await run('!!document.querySelector(".prr-dialog[open]")'))break;await sleep(100);
        }
        assert.equal(await run('!!document.querySelector(".prr-dialog[open]")'),true,'Pipeline inspection control did not open reviews');
        page.pipelineGraph=true;
        page.pipelineScreenshot='orchestrator-pipeline.png';
      }
      report.pages.push(page);
      await run('window.PineRejectionReview.destroy();true;');
      win.destroy();win=null;
    }
    report.ok=true;fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({ok:true,pages:report.pages,writesSent:0,blockedWrites:report.blockedWrites.length,blockedMedia:report.blockedMedia,out}));
    app.exit(0);
  }catch(error){
    report.error=safe(error.message);
    if(win&&!win.isDestroyed()){
      try{await win.webContents.insertCSS('#apiKey,[name="apiKey"],input[type="password"]{visibility:hidden!important}');fs.writeFileSync(path.join(out,'failure.png'),(await win.webContents.capturePage()).toPNG());}catch(_){}
      win.destroy();
    }
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));console.error(report.error);app.exit(1);
  }
});
