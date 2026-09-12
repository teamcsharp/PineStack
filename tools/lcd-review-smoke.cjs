// Hidden, fixture-only 320x240 LCD review smoke. Never connects to a display,
// station, serial port, media player or live decision endpoint.
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const root = process.env.PINE_LCD_REVIEW_ROOT || path.resolve(__dirname, '..');
const out = path.join(os.tmpdir(), 'pine-lcd-review-smoke');
app.setPath('userData', path.join(out, 'profile'));
app.commandLine.appendSwitch('no-sandbox');
let window;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

app.whenReady().then(async () => {
  try {
    fs.mkdirSync(out, {recursive: true});
    window = new BrowserWindow({show: false, width: 320, height: 240,
      webPreferences: {contextIsolation: true, nodeIntegration: false, offscreen: true, backgroundThrottling: false}});
    let blockedRequests = 0;
    window.webContents.session.webRequest.onBeforeRequest({urls: ['http://*/*', 'https://*/*']}, (_request, callback) => {
      blockedRequests++; callback({cancel: true});
    });
    const errors = [];
    window.webContents.on('console-message', (_event, level, message) => {if (level >= 3) errors.push(message);});
    await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<!doctype html><html><body style="margin:0;background:#07121b"><canvas id="lcd" width="320" height="240" style="display:block"></canvas></body></html>'));
    await window.webContents.executeJavaScript(fs.readFileSync(path.join(root, 'desktop/renderer/lcd-review.js'), 'utf8'));
    await window.webContents.executeJavaScript(String.raw`
      window.fixturePosts=[]; window.fixtureReads=[];
      window.fixtureDetail={id:'fixture-cut-a',event_seq:21,revision:4,gate:'tint',review_status:'pending',technical:false,
        source:'The station clock stopped at midnight. The caretaker checked the brass gears and kept every loose screw in a labelled tin. '+Array.from({length:12},(_,i)=>'Original detail '+(i+1)+': the caller described the repair without changing speakers.').join(' '),
        candidate:'The midnight clock grew quiet; the caretaker kept each brass screw in its tin.',
        reasons:['The rewrite changed the original meaning.','The voice should retain every original detail.'],
        context:{kind:'banter',marker:'A',turn:2,script:'A: A full retained opening.\nB: A full retained reply.'}};
      window.fixtureStale=false;
      window.reviewCanvas=document.getElementById('lcd'); window.reviewInk=reviewCanvas.getContext('2d');
      window.reviewController=PineLcdReview.create({
        get:async route=>{fixtureReads.push(route);return structuredClone(fixtureDetail)},
        post:async(route,body)=>{fixturePosts.push({route,body});if(fixtureStale){const error=new Error('This cut changed');error.status=409;throw error;}
          fixtureDetail={...fixtureDetail,revision:fixtureDetail.revision+1,review_status:body.action==='allow'?'allowed':'kept'};
          return {ok:true,row:structuredClone(fixtureDetail),effect:{status:body.action==='allow'?'awaiting_recovery':'kept'}};},
        onChange:()=>{},onClose:()=>{window.fixtureClosed=(window.fixtureClosed||0)+1;}});
      window.paintReview=()=>{
        reviewInk.fillStyle='#18394c';reviewInk.fillRect(0,0,320,240);
        reviewInk.fillStyle='#eed37b';reviewInk.fillRect(4,4,56,48);
        reviewInk.font='bold 17px sans-serif';reviewInk.fillStyle='#102532';reviewInk.fillText('AV',20,34);
        reviewController.draw(reviewInk,320,240);
      };
      reviewCanvas.addEventListener('click',event=>{const rect=reviewCanvas.getBoundingClientRect();reviewController.tap((event.clientX-rect.left)*320/rect.width,(event.clientY-rect.top)*240/rect.height,320,240);paintReview();});
      window.touchReview=(name)=>{const rect=PineLcdReview.geometry(320,240)[name];reviewCanvas.dispatchEvent(new MouseEvent('click',{clientX:rect.x+rect.w/2,clientY:rect.y+rect.h/2}));};
      true;`);
    const execute = source => window.webContents.executeJavaScript(source);
    const snapshot = () => execute('reviewController.snapshot()');
    const draw = () => execute('paintReview(); true');
    async function capture(name) {
      await draw();
      const data = await execute('reviewCanvas.toDataURL("image/png")');
      fs.writeFileSync(path.join(out, name + '.png'), Buffer.from(data.split(',')[1], 'base64'));
    }
    await execute("Object.assign(fixtureDetail,{evaluation:{machine_ok:false,fault_count:2,fidelity:'Original detail changed'},system_path:'Writing -> tint -> recording',effect:{status:'held',say:'Waiting for an editorial decision; no audio is played by this popup.'}});reviewController.open({review_id:'fixture-cut-a',review_seq:21,text:'Visible row preview'});");
    await draw(); await execute("touchReview('accept');touchReview('accept');true"); await wait(30);
    assert.equal((await execute('fixturePosts')).length, 0, 'Opening contacts must never approve the cut');
    await wait(370); await draw();
    assert.equal((await snapshot()).armed, true);
    await capture('review-320x240');
    await execute("touchReview('why');true"); await capture('why-320x240');
    assert.equal((await snapshot()).section,'why');
    await execute("touchReview('system');true"); await capture('system-320x240');
    assert.equal((await snapshot()).section,'system');
    await execute("touchReview('words');true"); await draw();
    const firstOffset = (await snapshot()).offset;
    await execute("touchReview('next');true"); await draw();
    assert.ok((await snapshot()).offset > firstOffset);
    await capture('detail-scrolled-320x240');
    await execute("touchReview('previous');true"); await draw();
    assert.equal((await snapshot()).offset, firstOffset);
    await execute("reviewController.tap(200,58,320,240);true");
    assert.equal((await snapshot()).open, false);
    assert.equal((await execute('fixturePosts')).length, 0);

    await execute("fixtureDetail={...fixtureDetail,id:'fixture-technical',event_seq:22,revision:5,technical:true,reasons:['The recording file is missing.']};reviewController.open({review_id:'fixture-technical',review_seq:22});");
    await draw(); await wait(370); await draw();
    assert.equal((await snapshot()).canAccept, false); assert.equal((await snapshot()).canReject, true);
    await capture('technical-320x240');
    await execute("touchReview('accept');true"); await wait(25);
    assert.equal((await execute('fixturePosts')).length, 0);
    await execute("touchReview('reject');true"); await wait(35); await draw();
    let posts = await execute('fixturePosts');
    assert.equal(posts.length, 1); assert.equal(posts[0].route, '/api/orchestrator/rejections/fixture-technical');
    assert.deepEqual(posts[0].body, {action:'keep',expected_revision:5,expected_event_seq:22,note:'LCD review'});

    await execute("fixtureStale=true;fixtureDetail={...fixtureDetail,id:'fixture-stale',event_seq:23,revision:7,technical:false,review_status:'pending'};reviewController.open({review_id:'fixture-stale',review_seq:23});");
    await draw(); await wait(370); await draw();
    await execute("touchReview('accept');true"); await wait(40); await draw();
    assert.equal((await snapshot()).canAccept, false); assert.equal((await snapshot()).canReject, false);
    await capture('changed-cut-320x240');
    await execute("touchReview('accept');touchReview('reject');true"); await wait(25);
    posts = await execute('fixturePosts'); assert.equal(posts.length, 2, 'A stale cut requires a new explicit selection');

    // Exercise actual cupboard hit testing and its physical-input poll with
    // in-memory events and JPEG acknowledgments, never a connected device.
    window.setContentSize(1040,900);
    await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<!doctype html><html><body style="margin:0;background:#101419"><button id="lcdBtn">LCD</button></body></html>'));
    await execute(String.raw`
      window.integrationCalls={reads:[],posts:[],frames:0,otherActions:0,modes:[]};window.integrationEvents=[];
      window.integrationState={config:{host:'fixture-only',mode:'cupboard',autoStart:false,pausedCupboard:true,speed:50,scrollEnabled:true},
        running:true,connected:true,frames:0,lastAck:0,log:[],firmware:{available:false},
        device:{identity:'fixture',board:'cyd_2432s028r',width:320,height:240,version:49,hostTouch:true,pineProtocol:2,displayMode:'pine',streamPort:3233,maxJpeg:24576}};
      window.integrationDetail={id:'fixture-live-row',event_seq:91,revision:8,technical:false,gate:'tint',review_status:'pending',
        source:'An exact original statement from the station caller. '.repeat(15),candidate:'Open this rejected station line.',
        reasons:['The meaning differs from its original.'],context:{kind:'gallery',stage:'tint'},system_path:'Writing -> tint -> recording'};
      window.pineDesktop={
        lcdState:async()=>structuredClone(integrationState),
        lcdFrame:async()=>{integrationCalls.frames++;integrationState.frames++;integrationState.lastAck=Date.now();return{ok:true}},
        lcdEvents:async()=>({events:integrationEvents.splice(0),device:structuredClone(integrationState.device)}),
        lcdConfigure:async value=>{integrationCalls.otherActions++;Object.assign(integrationState.config,value);return structuredClone(integrationState)},
        lcdDisplayMode:async mode=>{integrationCalls.otherActions++;integrationCalls.modes.push(mode);integrationState.device.displayMode=mode;return structuredClone(integrationState)},
        lcdControl:async()=>{integrationCalls.otherActions++;throw new Error('Unexpected physical control')},
        get:async route=>{integrationCalls.reads.push(route);
          if(route==='/api/dj')return{paused:true,chat:[]};
          if(route==='/api/paper')return{latest:'',editions:[]};
          if(route==='/api/generations?limit=1000')return{generations:[]};
          if(route==='/api/cupboard')return{rounds:[{kind:'gallery',state:'READY',cut:1,lines:[{who:'A',text:'Open this rejected station line.',mark:'cut',review_id:'fixture-live-row',review_seq:91}]}]};
          if(route==='/api/orchestrator/rejections/fixture-live-row?event_seq=91')return structuredClone(integrationDetail);
          throw new Error('Unexpected fixture GET '+route);},
        post:async(route,body)=>{integrationCalls.posts.push({route,body});
          if(route!=='/api/orchestrator/rejections/fixture-live-row')throw new Error('Unexpected fixture mutation');
          integrationDetail={...integrationDetail,revision:9,review_status:'allowed'};
          return{ok:true,row:structuredClone(integrationDetail),effect:{status:'awaiting_recovery'}};}
      };true;`);
    for(const name of ['lcd-dialogue.js','lcd-frame.js','lcd-controls.js','lcd-gallery.js','lcd-review.js','lcd.js'])
      await execute(fs.readFileSync(path.join(root,'desktop/renderer',name),'utf8'));
    await execute("document.getElementById('lcdBtn').click();true");
    let hit;
    for(let i=0;i<50;i++){
      hit=await execute("(window.PineLcdReviewHits||[]).find(row=>row.review_id==='fixture-live-row'&&row.y2>row.y1)");
      if(hit)break;await wait(80);
    }
    assert.ok(hit,'The actual cupboard must expose a visible rejected-line hit target');
    await execute(`integrationEvents.push({kind:'touch',x:${(hit.x1+hit.x2)/2},y:${(hit.y1+hit.y2)/2}});true`);
    await wait(220);
    assert.equal(await execute('PineLcdReviewController.snapshot().selectedId'),'fixture-live-row');
    assert.equal(await execute("document.querySelector('#pineLcdPanel canvas').dataset.lcdReviewOpen"),'true');
    await wait(370);
    const bitmap=await execute("document.querySelector('#pineLcdPanel canvas').toDataURL('image/png')");
    fs.writeFileSync(path.join(out,'cupboard-touch-review-320x240.png'),Buffer.from(bitmap.split(',')[1],'base64'));
    await execute("integrationEvents.push({kind:'swipe',direction:'up'});true");await wait(130);
    assert.ok(await execute('PineLcdReviewController.snapshot().offset>0'));
    await execute("integrationEvents.push({kind:'touch',x:200,y:58});true");await wait(130);
    assert.equal(await execute('PineLcdReviewController.snapshot().open'),false);
    assert.equal((await execute('integrationCalls.posts')).length,0);
    await execute("PineLcdReviewController.open({review_id:'fixture-live-row',review_seq:91});");await wait(450);
    await execute("const accept=PineLcdReview.geometry().accept;integrationEvents.push({kind:'touch',x:accept.x+accept.w/2,y:accept.y+accept.h/2},{kind:'touch',x:accept.x+accept.w/2,y:accept.y+accept.h/2});true");
    await wait(180);
    const integration=await execute('integrationCalls');
    assert.equal(integration.posts.length,1);assert.equal(integration.otherActions,0);assert.ok(integration.frames>4);
    assert.deepEqual(integration.posts[0],{route:'/api/orchestrator/rejections/fixture-live-row',body:{action:'allow',expected_revision:8,expected_event_seq:91,note:'LCD review'}});
    await execute("const preview=document.querySelector('#pineLcdPanel canvas'),bounds=preview.getBoundingClientRect();preview.dispatchEvent(new MouseEvent('click',{clientX:bounds.left+bounds.width*.1,clientY:bounds.top+bounds.height*28/240}));true");
    await wait(130);
    assert.equal(await execute('PineLcdReviewController.snapshot().open'),false);
    assert.deepEqual(await execute('integrationCalls.modes'),['avatar']);
    assert.equal((await execute('integrationCalls.posts')).length,1,'Native corner exception never submits a review');
    assert.equal(blockedRequests, 0); assert.deepEqual(errors, []);
    const result = {ok:true,width:320,height:240,fixtureOnly:true,networkRequests:blockedRequests,
      fixtureVotes:posts.length+integration.posts.length,fixtureFrames:integration.frames,
      scenarios:['opening double tap','native corner preservation','Why and System tabs','full-detail page controls','outside close','technical accept disabled','exact reject identity','stale vote locked','actual cupboard hit and input polling','native corner closes and switches once'],
      captures:['review-320x240.png','why-320x240.png','system-320x240.png','detail-scrolled-320x240.png','technical-320x240.png','changed-cut-320x240.png','cupboard-touch-review-320x240.png']};
    fs.writeFileSync(path.join(out, 'result.json'), JSON.stringify(result, null, 2));
    process.stdout.write(JSON.stringify(result) + '\n');
    app.exit(0);
  } catch (error) {
    fs.mkdirSync(out, {recursive:true});fs.writeFileSync(path.join(out, 'error.txt'), String(error.stack || error));
    process.stderr.write(String(error.stack || error)+'\n');app.exit(1);
  }
});
