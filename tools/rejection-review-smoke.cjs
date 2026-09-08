// Hidden browser and desktop-shell checks. All API reads/writes use fixtures;
// this helper never contacts the station or starts media.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const strictAssert = require('node:assert/strict');
let checks = 0;
const assert = new Proxy(strictAssert, {get(target, key) {
  return typeof target[key] === 'function' ? (...args) => {checks++; return target[key](...args);} : target[key];
}});
const out = path.join(os.tmpdir(), 'pine-rejection-review-smoke');
const base = process.env.PINE_REVIEW_SOURCE || path.join(__dirname, '..');
app.setPath('userData', path.join(out, 'profile'));
app.commandLine.appendSwitch('no-sandbox');
app.whenReady().then(async () => {
  let win;
  try {
    fs.mkdirSync(out, {recursive: true});
    win = new BrowserWindow({show: false, width: 1260, height: 980,
      webPreferences: {contextIsolation: true, nodeIntegration: false, offscreen: true, backgroundThrottling: false}});
    win.webContents.on('console-message', (_event, _level, message) => console.log('[fixture renderer] ' + message));
    await win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<!doctype html><html><body style="background:#0c1410;color:#eee;font:16px system-ui"><h1>Pine Box fixture</h1><button id="before">Open review</button></body></html>'));
    const js = async code => {
      try { return await win.webContents.executeJavaScript(code); }
      catch (error) { console.error('Fixture script failed: ' + code.slice(0, 800)); throw error; }
    };
    const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
    const css = fs.readFileSync(path.join(base, 'frontend/rejection-review.css'), 'utf8');
    await js(`document.head.append(Object.assign(document.createElement('style'),{textContent:${JSON.stringify(css)}}));true;`);
    await js(String.raw`
      window.fixtureStorage=new Map();
      Object.defineProperty(window,'sessionStorage',{configurable:true,value:{
        getItem:key=>fixtureStorage.get(key)??null,
        setItem:(key,value)=>fixtureStorage.set(key,String(value)),
        removeItem:key=>fixtureStorage.delete(key)}});
      window.fixture = {calls:[], posts:[], total:125, conflict:false, failPolicy:false, deferred:null,
        batches:new Map(),deferBatch:false,failBatchOnce:false,batchSnapshots:0,deferPolicy:false,
        rows:new Map(), policy:{enabled:true,max_faults:1,disabled_gates:[],revision:1}, opened:[], playback:0};
      for(let n=1;n<=125;n++)fixture.rows.set('cut-'+n,{
        id:'cut-'+n,seq:n,at:1788820000+n,gate:n===124?'audio_duration':'crystal_grade',who:n%2?'Tony':'Skip',
        candidate_preview:'A complete line at the old railway station '+n,source_preview:'Full source summary '+n,
        review_status:'pending',technical:n===124,occurrences:n===125?3:1,
        source:n===125?'<img src=x onerror="window.badInjection=true">\n'+('Complete original source. '.repeat(500))+'SOURCE END':'Original line '+n,
        candidate:'Candidate wording '+n+' CANDIDATE END',reasons:['Metaphor flagged by evaluator'],
        context:{kind:'call',who:n%2?'Tony':'Skip',marker:'call-4',turn:3,trace_id:'trace-'+n,
          script:[{who:'caller',text:'What did you see at the railway?'},{who:'dj',text:'The whole answer stays here. SCRIPT END'}],
          writing:{status:'accepted',source_id:'speakerbox-12'},recording:{status:'held',clip_id:'take-4'}},
        evaluation:{faults:2,allowed:1,machine:'crystal'},revision:1,
        history:[{seq:n,source:'Current occurrence'}],history_has_more:n===125,history_next_before:n===125?120:null});
      window.fixtureRequest=async(path,options={})=>{
        fixture.calls.push({path,method:options.method||'GET'});
        const url=new URL(path,'http://fixture');
        if(options.signal?.aborted)throw new DOMException('Aborted','AbortError');
        if(path==='/api/orchestrator/rejection-policy'){
          if(options.method==='POST'){
            const body=JSON.parse(options.body);fixture.posts.push({path,body});
            if(fixture.failPolicy)throw new Error('Policy revision conflict');
            if(body.expected_revision!==fixture.policy.revision)throw new Error('Policy revision conflict');
            if(fixture.deferPolicy)await new Promise(resolve=>fixture.resolvePolicy=resolve);
            Object.assign(fixture.policy,body,{revision:fixture.policy.revision+1});
          }return structuredClone(fixture.policy);
        }
        if(path==='/api/orchestrator/rejections/context')return {
          writing:{active:[{kind:'call',script:'FULL WRITING ROOM SCRIPT'}]},recording:{active:[{who:'Tony',state:'waiting for engine'}]},tint:{pending:4},
          route:['Writing: retain every turn','Recording: prepare accepted words','On air: scheduled takes'],technical_note:'Missing audio requires repair.'};
        if(url.pathname==='/api/orchestrator/rejections'){
          const after=Number(url.searchParams.get('after'))||0,limit=Number(url.searchParams.get('limit'))||50;
          const before=Number(url.searchParams.get('before'))||Infinity,status=url.searchParams.get('status'),gate=url.searchParams.get('gate');
          const all=[...fixture.rows.values()].sort((a,b)=>b.seq-a.seq);
          const matches=all.filter(row=>row.seq<before&&(!gate||row.gate===gate)&&(status!=='pending'||row.review_status==='pending'));
          const items=matches.slice(0,limit).map(({source,candidate,context,evaluation,history,...summary})=>summary);
          const events=all.filter(row=>row.seq>after).sort((a,b)=>a.seq-b.seq).slice(0,limit).map(({id,seq,at,gate,who,candidate_preview,reasons,review_status,technical,occurrences})=>({id,seq,at,gate,who,candidate_preview,reasons,review_status,technical,occurrences}));
          return {items,events,latest_cursor:fixture.total,next_after:events.at(-1)?.seq||after,
            events_has_more:events.length>0&&events.at(-1).seq<fixture.total,total:matches.length,
            unreviewed:all.filter(row=>row.review_status==='pending').length,
            has_more:matches.length>limit,next_before:items.at(-1)?.seq,policy:structuredClone(fixture.policy)};
        }
        if(url.pathname==='/api/orchestrator/rejections/approve-current'&&options.method==='POST'){
          const body=JSON.parse(options.body);fixture.posts.push({path,body});
          if(Object.keys(body).join(',')!=='request_id'||!/^[\da-f]{8}-(?:[\da-f]{4}-){3}[\da-f]{12}$/i.test(body.request_id))throw new Error('The batch needs one UUID, without a client filter.');
          if(fixture.batches.has(body.request_id))return structuredClone(fixture.batches.get(body.request_id));
          const through=fixture.total,snapshot=[...fixture.rows.values()].filter(row=>row.seq<=through&&row.review_status==='pending');
          fixture.batchSnapshots++;
          if(fixture.deferBatch)await new Promise(resolve=>fixture.resolveBatch=resolve);
          const items=[],skip_reasons={};let approved=0,queued=0,awaiting_recovery=0,needs_context=0;
          for(const row of snapshot){
            let reason=row.technical?'technical':row.review_status!=='pending'?'review_changed':'';
            if(reason){skip_reasons[reason]=(skip_reasons[reason]||0)+1;items.push({id:row.id,status:'skipped',reason});continue;}
            row.review_status='allowed';row.revision++;row.decision={action:'allow',scope:'instance'};approved++;
            const effect=row.needs_context?'needs_context':row.awaiting_recovery?'awaiting_recovery':'queued';
            if(effect==='queued')queued++;else if(effect==='awaiting_recovery')awaiting_recovery++;else needs_context++;
            items.push({id:row.id,status:effect});
          }
          const result={ok:true,batch_id:body.request_id,through_cursor:through,snapshot_count:snapshot.length,
            approved,queued,awaiting_recovery,needs_context,skipped:snapshot.length-approved,skip_reasons,
            remaining_pending:[...fixture.rows.values()].filter(row=>row.review_status==='pending').length,
            policy:structuredClone(fixture.policy),items};
          fixture.batches.set(body.request_id,structuredClone(result));
          if(fixture.failBatchOnce){fixture.failBatchOnce=false;throw new Error('Reply lost after the batch was saved');}
          return result;
        }
        const id=decodeURIComponent(url.pathname.split('/').at(-1));const row=fixture.rows.get(id);
        if(!row)throw new Error('Missing fixture '+path);
        if(options.method==='POST'){
          const body=JSON.parse(options.body);fixture.posts.push({path,body});
          if(fixture.conflict)throw new Error('Revision conflict');
          if(body.expected_revision!==row.revision)throw new Error('Revision conflict');
          row.review_status=body.action==='allow'?'allowed':'kept';row.revision++;
          row.decision={action:body.action,note:body.note,by:'operator',at:1788820200};
          row.effect={status:'feedback_saved',say:'Feedback saved. The complete line remains held for scheduled recovery.'};
          return {ok:true,row:structuredClone(row),effect:row.effect};
        }
        if(url.searchParams.has('before'))return {...structuredClone(row),history:[{seq:5,source:'EARLIER FULL OCCURRENCE'}],history_has_more:false,history_next_before:null};
        if(fixture.deferred===id)return await new Promise(resolve=>fixture.resolveDeferred=()=>resolve(structuredClone(row)));
        return structuredClone(row);
      };
      HTMLMediaElement.prototype.play=function(){fixture.playback++;return Promise.resolve();};
      true;`);
    const code = fs.readFileSync(path.join(base, 'frontend/rejection-review.js'), 'utf8');
    await js(`(async()=>{window.reviewModule=await import('data:text/javascript;base64,${Buffer.from(code).toString('base64')}');
      window.review=reviewModule.create({request:fixtureRequest,notifications:true,onLogic:()=>fixture.opened.push('logic'),onFlow:()=>fixture.opened.push('flow')});return true;})()`);
    await js('review.poll()'); await wait(40);
    assert.equal(await js('document.querySelectorAll(".prr-notice").length'), 1);
    assert.equal(await js('document.querySelector(".prr-notice strong").textContent'), '125 rejection updates');
    assert.equal(await js('fixture.calls.filter(call=>call.path.includes("after=")).slice(0,3).map(call=>new URL(call.path,"http://fixture").searchParams.get("after")).join(",")'), '0,50,100');
    assert.equal(await js('reviewModule.eventCursor({next_after:0,events:[],latest_cursor:125,events_has_more:false},0)'), 125);
    assert.equal(await js('reviewModule.eventCursor({next_after:50,latest_cursor:125,events_has_more:true},0)'), 50);
    assert.equal(await js('reviewModule.eventCursor({next_after:null,events:[{seq:9}],latest_cursor:125},5)'), 9);
    fs.writeFileSync(path.join(out,'browser-notice.png'), (await win.webContents.capturePage()).toPNG());
    await js('document.querySelector(".prr-notice .prr-actions button:last-child").click();true;');
    assert.equal(await js('document.querySelectorAll(".prr-notice").length'), 0);
    await js(`fixture.total=126;fixture.rows.set('cut-126',{...structuredClone(fixture.rows.get('cut-125')),id:'cut-126',seq:126,occurrences:1});review.poll()`);
    assert.equal(await js('document.querySelector(".prr-notice strong").textContent'), 'A rejection needs review');
    await js('document.querySelector("#before").focus();review.open("cut-125")');
    assert.equal(await js('document.querySelector(".prr-dialog").open'), true);
    assert.equal(await js('document.querySelector(".prr-policy").open'), false);
    assert.equal(await js('document.querySelector("[role=switch][data-policy=master]").getAttribute("aria-checked")'), 'true');
    assert.equal(await js('document.querySelector("[data-policy=master]").getAttribute("aria-label")'), 'Rejection system');
    assert.equal(await js('!!document.querySelector("[data-review=approve-current]")'), true);
    assert.match(await js('document.querySelector(".prr-batch-help").textContent'), /current|waiting|pending/i);
    assert.match(await js('document.querySelector(".prr-batch-help").textContent'), /future|later/i);
    assert.equal(await js('document.querySelector(".prr-batch-result").getAttribute("role")'), 'status');
    assert.equal(await js('document.querySelector(".prr-master-result").getAttribute("role")'), 'status');
    assert.equal(await js('document.querySelectorAll(".prr-notice").length'), 0);
    assert.match(await js('document.querySelector(".prr-detail").textContent'), /SOURCE END/);
    assert.match(await js('document.querySelector(".prr-detail").textContent'), /CANDIDATE END/);
    assert.match(await js('document.querySelector(".prr-detail").textContent'), /SCRIPT END/);
    assert.equal(await js('!!window.badInjection || !!document.querySelector(".prr-detail img")'), false);
    assert.match(await js('document.querySelector(".prr-grades").textContent'), /Machine decision[\s\S]*Operator decision/);
    assert.equal(await js('document.querySelectorAll(".prr-row").length'), 50);
    assert.match(await js('document.querySelector(".prr-row-preview").textContent'), /old railway station/);
    await js('document.querySelector(".prr-more").click();true;'); await wait(30);
    assert.equal(await js('document.querySelectorAll(".prr-row").length'), 100);
    await js('document.querySelector(".prr-verdict textarea").value="Keep this unfinished note";review.poll()');
    assert.equal(await js('document.querySelector(".prr-verdict textarea").value'), 'Keep this unfinished note');
    assert.equal(await js('document.querySelectorAll(".prr-row").length'), 100);
    await js('document.querySelector(".prr-overview").open=true;true;'); await wait(40);
    assert.match(await js('document.querySelector(".prr-room").textContent'), /FULL WRITING ROOM SCRIPT/);
    assert.match(await js('document.querySelector(".prr-room").textContent'), /waiting for engine/);
    assert.match(await js('document.querySelector(".prr-room").textContent'), /On air: scheduled takes/);
    assert.match(await js('document.querySelector(".prr-room").textContent'), /Missing audio requires repair/);
    await js('document.querySelector(".prr-overview").open=false;document.querySelector(".prr-policy").open=true;true;');
    await js('const input=document.querySelector("[data-policy=max_faults]");input.value="5";input.dispatchEvent(new Event("input"));document.querySelector("[data-policy=save]").click();true;'); await wait(30);
    assert.equal(await js('fixture.policy.max_faults'), 5);
    assert.match(await js('document.querySelector(".prr-policy-caption").textContent'), /Allow up to 5 editorial flags/);
    await js('document.querySelector("[data-policy=master]").click();true;'); await wait(30);
    assert.equal(await js('fixture.policy.enabled'), false);
    assert.equal(await js('document.querySelector("[data-policy=master]").getAttribute("aria-checked")'), 'false');
    await js('document.querySelector("[data-policy=master]").click();true;'); await wait(30);
    assert.equal(await js('fixture.policy.enabled'), true);
    await js('document.querySelector("[data-policy=max_faults]").value="7";document.querySelector("[data-policy=max_faults]").dispatchEvent(new Event("input"));document.querySelector("[data-policy=master]").click();true;'); await wait(30);
    assert.equal(await js('document.querySelector("[data-policy=max_faults]").value'), '7');
    assert.equal(await js('fixture.policy.max_faults'), 5);
    await js('document.querySelector("[data-policy=master]").click();true;'); await wait(30);
    await js('fixture.failPolicy=true;document.querySelector("[data-policy=master]").click();true;'); await wait(30);
    assert.match(await js('document.querySelector(".prr-master-result").textContent'), /not saved/i);
    assert.equal(await js('fixture.policy.enabled'), true);
    await js('fixture.failPolicy=false;document.querySelector(".prr-policy").open=false;true;');
    await js('fixture.policy.revision++;fixture.policy.enabled=false;document.querySelector("[data-policy=master]").click();true;'); await wait(40);
    assert.match(await js('document.querySelector(".prr-master-result").textContent'), /not saved/i);
    assert.equal(await js('document.querySelector("[data-policy=master]").getAttribute("aria-checked")'), 'false');
    await js('document.querySelector("[data-policy=master]").click();true;'); await wait(40);
    assert.equal(await js('fixture.policy.enabled'), true);
    assert.equal(await js('document.querySelector("[data-policy=master]").getAttribute("aria-checked")'), 'true');
    await js('fixture.conflict=true;document.querySelector(".prr-verdict .prr-primary").click();true;'); await wait(30);
    assert.match(await js('document.querySelector(".prr-review-result").textContent'), /not confirmed[\s\S]*Revision conflict/);
    assert.equal(await js('document.querySelector(".prr-verdict textarea").value'), 'Keep this unfinished note');
    await js('fixture.conflict=false;document.querySelector(".prr-verdict .prr-primary").click();true;'); await wait(30);
    assert.equal(await js('fixture.rows.get("cut-125").review_status'), 'allowed');
    assert.equal(await js('fixture.posts.filter(p=>p.path.endsWith("cut-125")).at(-1).body.note'), 'Keep this unfinished note');
    assert.match(await js('document.querySelector(".prr-review-result").textContent'), /complete line remains held/);
    assert.match(await js('document.querySelector(".prr-grades").textContent'), /Review note: Keep this unfinished note/);
    assert.equal(await js('!!document.querySelector("[data-review-id=cut-125]")'), false);
    await js('review.open("cut-124")');
    assert.equal(await js('document.querySelector(".prr-verdict .prr-primary").disabled'), true);
    assert.match(await js('document.querySelector("#prr-technical-why").textContent'), /technical problem must be repaired/);
    assert.equal(await js('[...document.querySelectorAll(".prr-verdict button")].find(b=>b.textContent==="Rejection is correct").disabled'), false);
    await js('[...document.querySelectorAll(".prr-verdict button")].find(b=>b.textContent==="Rejection is correct").click();true;'); await wait(30);
    assert.equal(await js('fixture.rows.get("cut-124").review_status'), 'kept');
    await js('review.open("cut-125")');
    await js('[...document.querySelectorAll(".prr-detail button")].find(b=>b.textContent==="Load earlier occurrences").click();true;'); await wait(30);
    assert.match(await js('document.querySelector(".prr-detail").textContent'), /EARLIER FULL OCCURRENCE/);
    await js('fixture.deferred="cut-122";review.open("cut-122");true;'); await wait(5);
    await js('review.open("cut-123")');
    await js('fixture.resolveDeferred();true;'); await wait(20);
    assert.match(await js('document.querySelector(".prr-detail").textContent'), /cut-123/);
    assert.doesNotMatch(await js('document.querySelector(".prr-detail").textContent'), /cut-122/);
    fs.writeFileSync(path.join(out,'full-review.png'), (await win.webContents.capturePage()).toPNG());
    await js('document.querySelector("[data-filter=status]").value="all";document.querySelector("[data-filter=status]").dispatchEvent(new Event("change"));true;'); await wait(30);
    assert.equal(await js('!!document.querySelector("[data-review-id=cut-125]")'), true);
    await js('document.querySelector("[data-filter=gate]").value="audio_duration";document.querySelector("[data-filter=gate]").dispatchEvent(new Event("change"));true;'); await wait(30);
    assert.equal(await js('document.querySelectorAll(".prr-row").length'), 1);
    await js('document.querySelector("[data-policy=master]").focus();document.getElementById("before").focus();true;');
    assert.equal(await js('document.querySelector(".prr-dialog").contains(document.activeElement)'), true);
    await js('review.close();review.open("cut-124")');
    assert.equal(await js('document.querySelector("[data-filter=gate]").value'), 'audio_duration');
    await js('document.querySelector("[data-filter=gate]").value="";document.querySelector("[data-filter=gate]").dispatchEvent(new Event("change"));true;'); await wait(30);
    win.setSize(520, 860); await wait(80);
    assert.equal(await js('document.querySelector(".prr-dialog").scrollWidth<=document.querySelector(".prr-dialog").clientWidth'), true);
    fs.writeFileSync(path.join(out,'narrow-review.png'), (await win.webContents.capturePage()).toPNG());
    await js('[...document.querySelectorAll(".prr-header button")].find(b=>b.textContent==="Station flow").click();true;');
    assert.deepEqual(await js('fixture.opened'), ['flow']);
    assert.equal(await js('!!document.querySelector(".prr-dialog")'), false);
    assert.equal(await js('document.activeElement.id'), 'before');
    await js('review.open("cut-123")');
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'}); win.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'}); await wait(40);
    assert.equal(await js('!!document.querySelector(".prr-dialog")'), false);
    // Top-level controls act on a server snapshot, not the visible queue page.
    // Keep the legacy fixture intact for the desktop notification tests below.
    await js(`fixture.savedRows=fixture.rows;fixture.savedTotal=fixture.total;fixture.savedPolicy=structuredClone(fixture.policy);
      fixture.rows=new Map();fixture.total=365;
      for(let n=1;n<=65;n++)fixture.rows.set('batch-'+n,{...structuredClone(fixture.savedRows.get('cut-126')),
        id:'batch-'+n,seq:300+n,review_status:'pending',revision:1,technical:n===1,
        gate:n===1||n===65?'audio_duration':'crystal_grade',needs_context:n===2,awaiting_recovery:n===3});
      review.open('batch-2')`);
    for (const [width,height,name] of [[800,950,'master-800.png'],[390,844,'master-mobile.png']]) {
      win.setSize(width,height); await wait(80);
      assert.equal(await js('document.querySelector(".prr-policy").open'), false);
      assert.equal(await js('document.querySelector(".prr-dialog").scrollWidth<=document.querySelector(".prr-dialog").clientWidth'), true);
      assert.equal(await js(`['[data-policy=master]','[data-review=approve-current]','.prr-batch-help'].every(selector=>{
        const node=document.querySelector(selector),r=node.getBoundingClientRect();
        return r.width>0&&r.height>0&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&!node.closest('details');})`), true);
      fs.writeFileSync(path.join(out,name), (await win.webContents.capturePage()).toPNG());
    }
    await js('document.querySelector("[data-policy=master]").focus();true;');
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'Space'}); win.webContents.sendInputEvent({type:'keyUp',keyCode:'Space'}); await wait(40);
    assert.equal(await js('fixture.policy.enabled'), false);
    assert.equal(await js('document.querySelector("[data-policy=master]").getAttribute("aria-checked")'), 'false');
    await js('document.querySelector("[data-policy=master]").focus();true;');
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'Return'});
    win.webContents.sendInputEvent({type:'char',keyCode:'\r'});
    win.webContents.sendInputEvent({type:'keyUp',keyCode:'Return'}); await wait(40);
    assert.equal(await js('fixture.policy.enabled'), true);
    await js('fixture.deferPolicy=true;document.querySelector("[data-policy=master]").click();document.querySelector("[data-policy=master]").click();true;'); await wait(20);
    assert.equal(await js('document.querySelector("[data-policy=master]").disabled&&document.querySelector("[data-review=approve-current]").disabled'), true);
    await js('fixture.deferPolicy=false;fixture.resolvePolicy();true;'); await wait(35);
    assert.equal(await js('fixture.policy.enabled'), false);
    await js('document.querySelector("[data-policy=master]").click();true;'); await wait(35);
    await js('document.querySelector("[data-filter=gate]").value="audio_duration";document.querySelector("[data-filter=gate]").dispatchEvent(new Event("change"));true;'); await wait(30);
    assert.equal(await js('document.querySelectorAll(".prr-row").length'), 2);
    await js('fixture.policyBeforeBatch=JSON.stringify(fixture.policy);fixture.deferBatch=true;fixture.batchPostsBefore=fixture.posts.filter(p=>p.path.endsWith("approve-current")).length;document.querySelector("[data-review=approve-current]").click();document.querySelector("[data-review=approve-current]").click();true;'); await wait(20);
    assert.equal(await js('fixture.posts.filter(p=>p.path.endsWith("approve-current")).length-fixture.batchPostsBefore'), 1);
    assert.equal(await js('document.querySelector("[data-policy=master]").disabled&&document.querySelector("[data-review=approve-current]").disabled'), true);
    assert.equal(await js('[...document.querySelectorAll(".prr-verdict button")].every(button=>button.disabled)'), true);
    await js(`fixture.rows.get('batch-4').review_status='kept';
      fixture.rows.set('batch-new',{...structuredClone(fixture.rows.get('batch-5')),id:'batch-new',seq:366,review_status:'pending'});
      fixture.total=366;review.close();review.open('batch-2')`);
    assert.equal(await js('document.querySelector("[data-review=approve-current]").disabled'), true);
    assert.equal(await js('document.querySelector("[data-policy=master]").disabled'), true);
    await js('document.querySelector(".prr-verdict textarea").value="Note from the reopened review";true;');
    await js('fixture.deferBatch=false;fixture.resolveBatch();true;'); await wait(70);
    assert.equal(await js('fixture.batchSnapshots'), 1);
    assert.equal(await js('fixture.batches.values().next().value.snapshot_count'), 65);
    assert.equal(await js('fixture.batches.values().next().value.approved'), 63);
    assert.equal(await js('fixture.batches.values().next().value.skipped'), 2);
    assert.equal(await js('fixture.batches.values().next().value.awaiting_recovery'), 1);
    assert.equal(await js('fixture.rows.get("batch-new").review_status'), 'pending');
    assert.equal(await js('fixture.rows.get("batch-1").review_status'), 'pending');
    assert.equal(await js('fixture.rows.get("batch-65").review_status'), 'allowed');
    assert.equal(await js('JSON.stringify(fixture.policy)'), await js('fixture.policyBeforeBatch'));
    assert.match(await js('document.querySelector(".prr-batch-result").textContent'), /63/);
    assert.match(await js('document.querySelector(".prr-batch-result").textContent'), /2[^.]*skip|skip[^.]*2/i);
    assert.match(await js('document.querySelector(".prr-batch-result").textContent'), /1[^.]*recover|recover[^.]*1/i);
    assert.match(await js('document.querySelector(".prr-batch-result").textContent'), /technical/i);
    assert.equal(await js('document.querySelector("[data-review=approve-current]").disabled'), false);
    assert.match(await js('document.querySelector(".prr-grades").textContent'), /Approved once/);
    assert.equal(await js('document.querySelector(".prr-verdict textarea").value'), 'Note from the reopened review');
    assert.equal(await js('document.querySelector(".prr-policy").open'), false);
    win.setSize(800,950); await wait(40);
    fs.writeFileSync(path.join(out,'approve-current-result.png'), (await win.webContents.capturePage()).toPNG());
    // A lost success response must retry the same saved snapshot, even after
    // the dialog is reopened and another new line appears.
    await js(`fixture.failBatchOnce=true;fixture.batchPostsBefore=fixture.posts.filter(p=>p.path.endsWith('approve-current')).length;
      document.querySelector('[data-review=approve-current]').click();true;`); await wait(70);
    assert.match(await js('document.querySelector(".prr-batch-result").textContent'), /lost|confirm|retry/i);
    assert.match(await js('document.querySelector("[data-review=approve-current]").textContent'), /retry/i);
    await js(`fixture.retryId=fixture.posts.filter(p=>p.path.endsWith('approve-current')).at(-1).body.request_id;
      fixture.rows.set('batch-later',{...structuredClone(fixture.rows.get('batch-new')),id:'batch-later',seq:367,review_status:'pending'});
      fixture.total=367;review.destroy();review=reviewModule.create({request:fixtureRequest,notifications:true});review.open('batch-later')`);
    assert.match(await js('document.querySelector("[data-review=approve-current]").textContent'), /retry/i);
    await js('document.querySelector("[data-review=approve-current]").click();true;'); await wait(70);
    assert.equal(await js('fixture.posts.filter(p=>p.path.endsWith("approve-current")).at(-1).body.request_id'), await js('fixture.retryId'));
    assert.equal(await js('fixture.posts.filter(p=>p.path.endsWith("approve-current")).length-fixture.batchPostsBefore'), 2);
    assert.equal(await js('fixture.batchSnapshots'), 2);
    assert.equal(await js('fixture.rows.get("batch-later").review_status'), 'pending');
    assert.equal(await js('JSON.stringify(fixture.policy)'), await js('fixture.policyBeforeBatch'));
    await js('fixture.deferBatch=true;document.querySelector(".prr-verdict textarea").value="Keep this unsaved note";document.querySelector("[data-review=approve-current]").click();true;'); await wait(20);
    await js('document.querySelector(".prr-verdict textarea").value="Latest note during approval";fixture.deferBatch=false;fixture.resolveBatch();true;'); await wait(60);
    assert.equal(await js('fixture.rows.get("batch-later").review_status'), 'allowed');
    assert.match(await js('document.querySelector(".prr-grades").textContent'), /Approved once/);
    assert.equal(await js('document.querySelector(".prr-verdict textarea").value'), 'Latest note during approval');
    assert.equal(await js('fixture.batchSnapshots'), 3);
    await js('review.close();fixture.rows=fixture.savedRows;fixture.total=fixture.savedTotal;fixture.policy=fixture.savedPolicy;true;');
    assert.equal(await js('fixture.playback'), 0);
    assert.equal(await js('fixture.posts.every(p=>p.path.startsWith("/api/orchestrator/rejection"))'), true);
    await js('review.destroy();true;');
    assert.equal(await js('document.querySelectorAll(".prr-dialog,.prr-notice").length'), 0);
    // Embedded pages still have the full queue, while Electron shell owns alerts.
    await js('review=reviewModule.create({request:fixtureRequest});review.poll()');
    assert.equal(await js('document.querySelectorAll(".prr-notice").length'), 0);
    await js('review.destroy();true;');

    // Exercise the exact production desktop controller, including a 125-event
    // burst, Later/new-cut semantics and callbacks across arbitrary active tabs.
    const desktop = fs.readFileSync(path.join(base, 'desktop/renderer/renderer.js'), 'utf8');
    const noticeCode = desktop.slice(desktop.indexOf('function createDesktopRejectionNotices('), desktop.indexOf('// REJECTION NOTICE CONTROLLER END'));
    await js(noticeCode + ';true;');
    await js(`window.desktopStore=new Map();window.openedDesktop=[];window.activeFixtureTab='gallery';
      window.desktopController=createDesktopRejectionNotices({request:path=>fixtureRequest(path),openReview:async id=>{activeFixtureTab='radio';openedDesktop.push(id);},
        storage:{getItem:key=>desktopStore.get(key),setItem:(key,value)=>desktopStore.set(key,value)},key:'fixture',interval:60000});desktopController.poll()`);
    assert.equal(await js('document.querySelectorAll("#desktopRejectionNotices").length'), 1);
    assert.equal(await js('document.querySelector("#desktopRejectionNotices strong").textContent'), '124 rejection updates');
    assert.equal(await js('[...desktopStore.values()][0]'), '126');
    await js('document.querySelector("#desktopRejectionNotices aside button").click();true;'); await wait(10);
    assert.equal(await js('activeFixtureTab'), 'radio');
    assert.deepEqual(await js('openedDesktop'), [{id:'cut-126',event_seq:126}]);
    assert.equal(await js('document.querySelector("#desktopRejectionNotices aside").hidden'), true);
    await js('fixture.total=127;fixture.rows.set("cut-127",{...structuredClone(fixture.rows.get("cut-126")),id:"cut-127",seq:127});desktopController.poll()');
    assert.equal(await js('document.querySelector("#desktopRejectionNotices strong").textContent'), 'A rejection needs review');
    win.setSize(1040,700); await wait(40);
    fs.writeFileSync(path.join(out,'desktop-notice.png'), (await win.webContents.capturePage()).toPNG());
    await js('document.querySelector("#desktopRejectionNotices aside button:last-child").click();desktopController.poll()');
    assert.equal(await js('document.querySelector("#desktopRejectionNotices aside").hidden'), true);
    await js('activeFixtureTab="logs";document.querySelector("#desktopRejectionNotices>.badge").click();true;'); await wait(10);
    assert.equal(await js('activeFixtureTab'), 'radio');
    assert.deepEqual(await js('openedDesktop'), [{id:'cut-126',event_seq:126},null]);
    await js('for(let n=128;n<=252;n++)fixture.rows.set("cut-"+n,{...structuredClone(fixture.rows.get("cut-126")),id:"cut-"+n,seq:n});fixture.total=252;fixture.calls=[];desktopController.poll()');
    assert.equal(await js('document.querySelector("#desktopRejectionNotices strong").textContent'), '125 rejection updates');
    assert.equal(await js('fixture.calls.map(call=>new URL(call.path,"http://fixture").searchParams.get("after")).join(",")'), '127,177,227');
    assert.equal(await js('[...desktopStore.values()][0]'), '252');
    assert.equal(await js('fixture.playback'), 0);
    const clickGuard = desktop.slice(desktop.indexOf('// #802: the first real click'), desktop.indexOf('})();', desktop.indexOf('// #802: the first real click')));
    assert.match(clickGuard, /data-rejection-review/);
    assert.equal(await js('fixture.calls.some(call=>["/api/dj","/api/say","/api/speak"].some(prefix=>call.path.startsWith(prefix)))'), false);
    await js('desktopController.destroy();true;');
    assert.equal(await js('!!document.querySelector("#desktopRejectionNotices")'), false);
    // Cold startup can see no rows. Its first subsequent cut must notify in
    // both owners; returning events from after=0 is essential to that case.
    await js('window.firstCut=structuredClone(fixture.rows.get("cut-126"));fixture.rows.clear();fixture.total=0;fixture.calls=[];fixtureStorage.clear();review=reviewModule.create({request:fixtureRequest,notifications:true});review.poll()');
    assert.equal(await js('!!document.querySelector(".prr-notice")'), false);
    await js('fixture.rows.set("cut-1",{...firstCut,id:"cut-1",seq:1});fixture.total=1;review.poll()');
    assert.equal(await js('document.querySelector(".prr-notice strong").textContent'), 'A rejection needs review');
    assert.equal(await js('document.querySelectorAll(".prr-notice").length'), 1);
    await js('document.querySelector(".prr-notice button").click();true;'); await wait(25);
    assert.match(await js('document.querySelector(".prr-detail").textContent'), /cut-1/);
    await js('review.destroy();fixture.rows.clear();fixture.total=0;desktopStore.clear();openedDesktop=[];desktopController=createDesktopRejectionNotices({request:fixtureRequest,openReview:async id=>openedDesktop.push(id),storage:{getItem:key=>desktopStore.get(key),setItem:(key,value)=>desktopStore.set(key,value)},key:"cold-empty",interval:60000});desktopController.poll()');
    assert.equal(await js('document.querySelector("#desktopRejectionNotices aside").hidden'), true);
    assert.equal(await js('[...desktopStore.values()][0]'), '0');
    await js('fixture.rows.set("cut-1",{...firstCut,id:"cut-1",seq:1});fixture.total=1;desktopController.poll()');
    assert.equal(await js('document.querySelector("#desktopRejectionNotices strong").textContent'), 'A rejection needs review');
    assert.equal(await js('document.querySelector("#desktopRejectionNotices aside").hidden'), false);
    assert.equal(await js('[...desktopStore.values()][0]'), '1');
    await js('document.querySelector("#desktopRejectionNotices aside button").click();true;'); await wait(10);
    assert.deepEqual(await js('openedDesktop'), [{id:'cut-1',event_seq:1}]);
    assert.equal(await js('fixture.playback'), 0);
    await js('desktopController.destroy();true;');
    fs.writeFileSync(path.join(out,'result.json'), JSON.stringify({ok:true,checks,screenshots:['browser-notice.png','full-review.png','narrow-review.png','desktop-notice.png','master-800.png','master-mobile.png','approve-current-result.png'],realStationCalls:0,playback:0},null,2));
    console.log(JSON.stringify({ok:true,checks,out}));
    win.destroy(); app.exit(0);
  } catch (error) {
    fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({ok:false,checks,error:String(error.stack)},null,2));
    if(win&&!win.isDestroyed())fs.writeFileSync(path.join(out,'failure.png'),(await win.webContents.capturePage()).toPNG());
    console.error(error.stack);if(win&&!win.isDestroyed())win.destroy();app.exit(1);
  }
});
