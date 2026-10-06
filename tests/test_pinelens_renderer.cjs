/* Offscreen Electron smoke test: real DOM/layout, stub desktop and relay. */
const {app, BrowserWindow} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const root = process.env.PINE_LENS_TEST_ROOT || path.resolve(__dirname, '..');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-lens-renderer-'));
  const fixture = new BrowserWindow({show: false, width: 1200, height: 800, webPreferences: {offscreen: true}});
  await fixture.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent('<body style="margin:0;background:#21413e;color:#effff4;font:28px system-ui"><div style="background:#101e21;padding:20px">Pine desktop · test display</div><div style="margin:55px;border:2px solid #70b696;padding:40px">Monitor this window<br><small>Pointer, keyboard and gestures reach the host.</small></div></body>'));
  const jpeg = (await fixture.webContents.capturePage()).toJPEG(80).toString('base64');
  const {LensRecording} = require(path.join(root, 'desktop', 'pinelens-recording.cjs'));
  const mux = require(path.join(root, 'desktop', 'clip-mux.cjs'));
  const ring = new LensRecording();
  try {
    const now = Date.now();
    for (let i = 0; i < 4; i++) ring.add({id: String(i), jpeg}, now - 1500 + i * 500);
    const clip = await ring.export(60, temp);
    assert.equal(clip.partial, true); assert.equal(clip.seconds, 1.5);
    assert.ok(fs.statSync(clip.path).size > 1000);
    await mux.run(mux.findFfmpeg().path, ['-v', 'error', '-i', clip.path, '-f', 'null', '-'], 30000);
    console.log('PineLens history encoded to MP4 and decoded successfully.');
  } finally { ring.close(); }
  fixture.close();
  const html = `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="${new URL('file:///' + root.replace(/\\/g, '/') + '/desktop/renderer/pinelens.css')}"><link rel="stylesheet" href="${new URL('file:///' + root.replace(/\\/g, '/') + '/desktop/renderer/listen-music.css')}"></head>
    <body style="margin:0"><section id="lens" class="pine-view-host pl-view open" style="position:fixed;inset:0"></section>
    <script>window.calls=[];window.views=0;window.pineDesktop={
      get:async function(route){if(route.endsWith('/hosts'))return {hosts:[{id:'test',name:'Test host'}]};window.views++;if(window.disconnected)throw Error('Offline');return {info:{control:true},frame:window.missing?null:{id:'f',revision:'r',jpeg:${JSON.stringify(jpeg)}}};},
      post:async function(route,body){window.calls.push(body);return {ok:true};},
      lensState:async function(){return {id:'test'};},
      lensPreview:async function(){return {jpeg:${JSON.stringify(jpeg)},display:4};},
      lensSave:async function(value){window.saved=value;return {ok:true};}
    };</script><script src="${new URL('file:///' + root.replace(/\\/g, '/') + '/app/src/main/assets/vendor/three.min.js')}"></script><script src="${new URL('file:///' + root.replace(/\\/g, '/') + '/desktop/renderer/pine-vcr.js')}"></script><script>window.vcrCalls=[];const vcrSet=PineVcr.set;PineVcr.set=function(el,on,opts){window.vcrCalls.push(on);return vcrSet(el,on,opts)};</script><script src="${new URL('file:///' + root.replace(/\\/g, '/') + '/desktop/renderer/pinelens.js')}"></script>
    <script>PineLens.mount(document.getElementById('lens'));</script></body></html>`;
  const file = path.join(temp, 'index.html'); fs.writeFileSync(file, html);
  const win = new BrowserWindow({show: false, width: 1340, height: 800, webPreferences: {offscreen: true}});
  await win.loadFile(file);
  await new Promise(resolve => setTimeout(resolve, 700));
  const result = await win.webContents.executeJavaScript(`(async function(){
    function press(text){Array.from(document.querySelectorAll('button')).find(b=>b.textContent===text).click();}
    const stage=document.querySelector('.pl-stage'), img=stage.querySelector(':scope > img'), rect=img.getBoundingClientRect();
    function point(type,x,y){stage.dispatchEvent(new PointerEvent(type,{pointerId:1,pointerType:'mouse',clientX:x,clientY:y,bubbles:true}));}
    // Call handlers directly: synthetic pointer IDs cannot acquire OS pointer capture.
    stage.setPointerCapture=function(){};
    point('pointerdown',rect.left+rect.width*.25,rect.top+rect.height*.75);
    point('pointerup',rect.left+rect.width*.25,rect.top+rect.height*.75);
    await new Promise(r=>setTimeout(r,30));
    document.querySelector('input').value='Hello desktop';press('Send text');
    await new Promise(r=>setTimeout(r,30));
    press('Zoom +');press('Zoom +');press('Zoom +');press('Zoom +');await new Promise(r=>setTimeout(r,20));
    press('Pan view');await new Promise(r=>setTimeout(r,20));
    const before=img.getBoundingClientRect(),center=stage.getBoundingClientRect();
    const count=window.calls.length;
    point('pointerdown',center.left+center.width/2,center.top+center.height/2);
    point('pointermove',center.left+center.width/2+60,center.top+center.height/2+30);
    point('pointerup',center.left+center.width/2+60,center.top+center.height/2+30);
    const after=img.getBoundingClientRect();
    await new Promise(r=>setTimeout(r,20));
    const panWorked=after.left>before.left+50&&after.top>before.top+20&&window.calls.length===count;
    press('Control desktop');await new Promise(r=>setTimeout(r,20));
    function touch(type,id,x,y){stage.dispatchEvent(new PointerEvent(type,{pointerId:id,pointerType:'touch',clientX:x,clientY:y,bubbles:true}));}
    const x=center.left+center.width/2,y=center.top+center.height/2;
    const gestureBefore=img.getBoundingClientRect();
    touch('pointerdown',2,x-60,y);touch('pointerdown',3,x+60,y);
    touch('pointermove',2,x-40,y+20);touch('pointermove',3,x+80,y+20);
    touch('pointerup',2,x-40,y+20);touch('pointerup',3,x+80,y+20);
    const gestureAfter=img.getBoundingClientRect();
    await new Promise(r=>setTimeout(r,20));
    const touchPanWorked=gestureAfter.left>gestureBefore.left+10&&window.calls.length===count;
    const pinchBefore=img.getBoundingClientRect();
    touch('pointerdown',2,x-60,y);touch('pointerdown',3,x+60,y);
    touch('pointermove',2,x-90,y);touch('pointermove',3,x+90,y);
    touch('pointerup',2,x-90,y);touch('pointerup',3,x+90,y);
    const pinchWorked=img.getBoundingClientRect().width>pinchBefore.width*1.4;
    press('Reset view');await new Promise(r=>setTimeout(r,20));
    const initialFrames=Number(document.querySelector('.pl-ambient').dataset.frames||0);
    window.missing=true;await new Promise(r=>setTimeout(r,750));
    const idleGraphic=!stage.classList.contains('pl-live')&&getComputedStyle(img).opacity==='0'&&getComputedStyle(stage).backgroundImage.includes('data:image/png;base64,');
    window.missing=false;await new Promise(r=>setTimeout(r,750));
    const animatedIdle=Number(document.querySelector('.pl-ambient').dataset.frames||0)>initialFrames;
    const recovered=stage.classList.contains('pl-live')&&getComputedStyle(img).opacity==='1';
    window.disconnected=true;await new Promise(r=>setTimeout(r,750));
    const disconnectedGraphic=!stage.classList.contains('pl-live')&&getComputedStyle(img).opacity==='0';
    window.disconnected=false;await new Promise(r=>setTimeout(r,750));
    press('Draw lens');await new Promise(r=>setTimeout(r,30));
    const r=img.getBoundingClientRect();point('pointerdown',r.left+r.width*.1,r.top+r.height*.2);point('pointerup',r.left+r.width*.6,r.top+r.height*.7);
    press('Save lens');await new Promise(r=>setTimeout(r,30));
    const stageHeight=stage.clientHeight;const seen=views;document.getElementById('lens').classList.remove('open');await new Promise(r=>setTimeout(r,450));
    const closedViews=views-seen;
    return {animatedIdle,vcrCalls:window.vcrCalls,panWorked,touchPanWorked,pinchWorked,idleGraphic,recovered,disconnectedGraphic,before:{x:before.left,y:before.top},after:{x:after.left,y:after.top},gestureBefore:{x:gestureBefore.left,y:gestureBefore.top},gestureAfter:{x:gestureAfter.left,y:gestureAfter.top},calls:window.calls,saved:window.saved,stageHeight,status:document.querySelector('.pl-status').textContent,closedViews,closedDisplay:getComputedStyle(document.getElementById('lens')).display};
  })()`);
  assert.equal(result.animatedIdle,true);assert.ok(result.vcrCalls.includes(true)&&result.vcrCalls.includes(false));
  assert.equal(result.panWorked,true);assert.equal(result.touchPanWorked,true);assert.equal(result.pinchWorked,true);assert.equal(result.idleGraphic,true);assert.equal(result.recovered,true);assert.equal(result.disconnectedGraphic,true);
  assert.equal(result.calls[0].type, 'pointer');
  assert.equal(result.calls[0].x, .25); assert.equal(result.calls[0].y, .75);
  assert.equal(result.calls[1].action, 'up');
  assert.equal(result.calls[2].text, 'Hello desktop');
  assert.equal(result.saved.display, 4);
  assert.ok(Math.abs(result.saved.crop.width - .5) < .001);
  assert.ok(result.stageHeight > 400); assert.equal(result.closedViews, 0); assert.equal(result.closedDisplay, 'none');
  const screenshot = path.join(root, 'artifacts', 'pinelens-renderer-smoke.png');
  fs.mkdirSync(path.dirname(screenshot), {recursive: true});
  fs.writeFileSync(screenshot, (await win.webContents.capturePage()).toPNG());
  console.log('PineLens renderer: pointer mapping, two-axis panning, touch panning, keyboard text, drawn crop, layout and hidden-view polling passed.');
  win.close(); app.quit();
}).catch(error => { console.error(error); app.exit(1); });
