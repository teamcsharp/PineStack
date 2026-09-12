// Explicit physical LCD verification. Stop the normal desktop producer first.
// Station reads only; accept/reject, playback and configuration writes are blocked.
const {app, BrowserWindow, ipcMain} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {LcdAgent} = require('../desktop/lcd-agent.cjs');
const arg = name => process.argv.find(s => s.startsWith('--' + name + '='))?.slice(name.length + 3) || '';
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const host = arg('host'), identity = arg('identity');
const out = path.join(app.getPath('temp'), 'pine-lcd-review-device-smoke');
app.setPath('userData', path.join(out, 'profile'));
app.on('window-all-closed', () => {});
app.whenReady().then(async () => {
  let win, agent, original, secret = '';
  const report = {ok:false, stationWrites:0, physicalGestureObserved:false, pages:[], restored:false};
  fs.mkdirSync(out, {recursive:true});
  try {
    if (!host || !identity) throw new Error('Supply the explicit LCD host and expected MAC.');
    const config = JSON.parse(fs.readFileSync(path.join(app.getPath('appData'), 'pinebox-desktop', 'pinebox-desktop.json'), 'utf8'));
    secret = String(config.apiKey || '');
    const get = async route => {
      if (!/^\/api\/(?:dj$|(?:tint\/)?cupboard$|orchestrator\/rejections(?:\/[^/]+)?(?:\?.*)?$)/.test(route)) throw new Error('Unexpected station read route.');
      const response = await fetch(config.baseUrl + route, {headers:{Authorization:'Bearer ' + secret}, signal:AbortSignal.timeout(15000)});
      if (!response.ok) throw new Error('Read-only station request returned HTTP ' + response.status);
      return response.json();
    };
    const [station, cupboard] = await Promise.all([get('/api/dj'), get('/api/cupboard')]);
    let cutRound = (cupboard.rounds || []).find(row => (row.lines || []).some(line => line.review_id && line.review_seq));
    let cut = cutRound?.lines.find(line => line.review_id && line.review_seq);
    report.previewOrigin = 'linked_current_cupboard_cut';
    if (!cut) {
      // Historical cupboard rows can lack their old event identity. Never guess
      // that link or write a replacement into the station. For display-only QA,
      // inspect a retained real cut in an explicitly isolated preview shelf.
      const queue = await get('/api/orchestrator/rejections?status=all&gate=tint&limit=200');
      for (const item of queue.items || []) {
        const row = await get('/api/orchestrator/rejections/' + encodeURIComponent(item.id)
          + '?event_seq=' + encodeURIComponent(item.event_seq));
        if (row.context?.stage !== 'turn_cut') continue;
        cut = {mark:'cut',who:row.context.marker || '',text:'(cut before the studio)',review_id:row.id,review_seq:row.event_seq};
        cutRound = {kind:row.context.kind || 'retained cut',label:'Retained evidence preview',state:'cut',lines:[cut]};
        report.previewOrigin = 'retained_cut_in_isolated_preview_not_linked_to_legacy_shelf';
        break;
      }
    }
    if (!cut) throw new Error('No retained real cut is available to inspect.');
    report.review = {id:cut.review_id,event_seq:cut.review_seq};
    const evidence = await get('/api/orchestrator/rejections/' + encodeURIComponent(cut.review_id) + '?event_seq=' + encodeURIComponent(cut.review_seq));
    report.evidence = {sourceChars:String(evidence.source || '').length,candidateChars:String(evidence.candidate || '').length,reasonCount:(evidence.reasons || []).length};
    // Bound only the preview shelf, using an actual row and actual cut. Full
    // original evidence is fetched by the unchanged review controller itself.
    const previewCupboard = {...cupboard,judgements:[],feed:[],rounds:[{...cutRound,lines:[cut]}]};
    const local = {lcd:{...config.lcd,host,identity,mode:'cupboard',speed:12,
      autoStart:false,screensaverEnabled:false,pausedCupboard:true}};
    agent = new LcdAgent({read:()=>local,write:next=>Object.assign(local,next)});
    const connected = await agent.connect(host,identity);
    original = {...connected.device};
    await agent.start({automatic:true});
    await agent.displayMode('pine');
    report.device = {board:agent.device.board,identity:agent.device.identity,width:agent.device.width,height:agent.device.height,protocol:agent.device.pineProtocol};
    assert.equal(agent.device.identity, identity);
    ipcMain.handle('lcd-smoke', async (_event,name,...args) => {
      if (name === 'get') {
        if (args[0] === '/api/dj') return station;
        if (args[0] === '/api/cupboard' || args[0] === '/api/tint/cupboard') return previewCupboard;
        if (args[0] === '/api/paper') return {editions:[]};
        return get(args[0]);
      }
      if (name === 'lcdState') return agent.state();
      if (name === 'lcdFrame') return agent.frame(args[0]);
      if (name === 'lcdEvents') return agent.events();
      throw new Error('This LCD inspection permits only reads and display frames.');
    });
    win = new BrowserWindow({show:false,width:1040,height:920,webPreferences:{
      offscreen:true,backgroundThrottling:false,preload:path.join(__dirname,'lcd-smoke-preload.cjs')}});
    win.webContents.setAudioMuted(true);
    win.webContents.session.webRequest.onBeforeRequest((details,callback)=>{
      callback({cancel:!['data:','file:','about:'].some(prefix=>details.url.startsWith(prefix))});
    });
    await win.loadURL('data:text/html,<html><body style="background:%2307121b"><button id="lcdBtn">LCD</button></body></html>');
    const run = code => win.webContents.executeJavaScript(code);
    for (const name of ['lcd-dialogue.js','lcd-frame.js','lcd-controls.js','lcd-gallery.js','lcd-review.js','lcd.js']) {
      await run(fs.readFileSync(path.join(__dirname,'../desktop/renderer',name),'utf8'));
    }
    await run('document.getElementById("lcdBtn").click();true;');
    const until = Date.now()+15000;
    while (Date.now()<until && !(await run('!!window.PineLcdReviewController'))) await wait(200);
    assert.equal(await run('!!window.PineLcdReviewController'),true);
    // Establish the frame/input connection and drain the initial mode event
    // before opening the modal. A mode event correctly dismisses any modal.
    const startupFrames = agent.frames;
    while (Date.now()<until && agent.frames<startupFrames+3) await wait(200);
    await agent.events();
    await wait(250);
    await run('window.PineLcdReviewController.open(' + JSON.stringify(cut) + ')');
    const before = agent.frames;
    const loadedUntil = Date.now()+15000;
    while (Date.now()<loadedUntil && (agent.frames<before+3 || !(await run('!!window.PineLcdReviewController.snapshot().detail')))) await wait(200);
    assert.ok(agent.frames>=before+3,'The popup must receive draw acknowledgments.');
    const shown = await run('window.PineLcdReviewController.snapshot()');
    report.popup = {open:shown.open,error:shown.error,message:shown.message,
      selectedId:shown.selectedId,eventSeq:shown.eventSeq,loadedId:shown.detail?.id};
    assert.equal(shown.detail?.id,cut.review_id,'Full stored evidence must load.');
    assert.equal(shown.detail?.event_seq,cut.review_seq,'The exact event must load.');
    const capture = async name => {
      const prior = agent.frames;
      for (let n=0;n<40 && agent.frames<prior+2;n++) await wait(100);
      assert.ok(agent.frames>=prior+2,'Popup drawing stopped.');
      fs.writeFileSync(path.join(out,name+'.jpg'),Buffer.from(agent.lastFrame,'base64'));
      fs.writeFileSync(path.join(out,name+'.png'),(await win.webContents.capturePage()).toPNG());
      report.pages.push({name,frames:agent.frames,bytes:agent.lastFrameBytes});
    };
    await capture('cut-details');
    const tab = async name => run(`(() => {const b=window.PineLcdReview.geometry()[${JSON.stringify(name)}];return window.PineLcdReviewController.tap(b.x+b.w/2,b.y+b.h/2);})()`);
    await tab('why');
    await capture('cut-reasons');
    await tab('system');
    await capture('cut-system');
    const tap = async (x,y) => run(`(() => {const cv=document.querySelector('canvas'),b=cv.getBoundingClientRect();cv.dispatchEvent(new MouseEvent('click',{clientX:b.left+b.width*${x}/320,clientY:b.top+b.height*${y}/240}));return true;})()`);
    await tap(318,130);
    await capture('dismissed');
    assert.equal(await run('document.querySelector("canvas").dataset.lcdReviewOpen'), 'false');
    report.dismissed = true;
    report.frames = agent.frames;
    report.failures = agent.failed;
    report.ok = true;
  } catch (error) {
    report.error = String(error.stack || error).split(secret || '\0').join('[redacted]');
  } finally {
    if (win && !win.isDestroyed()) win.destroy();
    agent?.stop();
    if (agent?.device && original) {
      try {
        await agent.control('idle',Number(original.idleSeconds)||0);
        await agent.displayMode(original.displayMode === 'avatar' ? 'avatar' : 'pine');
        if (original.screensaver) await agent.control('screensaver',true);
        report.restored = agent.device.displayMode === original.displayMode && agent.device.screensaver === !!original.screensaver;
      } catch (error) {report.restoreError=String(error.message);}
    }
    report.ok = report.ok && report.restored;
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
    app.exit(report.ok?0:1);
  }
});
