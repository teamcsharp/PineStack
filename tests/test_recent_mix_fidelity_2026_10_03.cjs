'use strict';
// Electron integration: real frame capture, rolling recorder and final MP4 samples.
// Isolated hidden windows and profile; never connects to the station.
// The two-second rolling recorders and Opus/AAC encoding can create short
// packet seams. This verifies levels in stable windows, not bit-perfect PCM.
const {app,BrowserWindow,ipcMain,session}=require('electron');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const {ScreenRing}=require('../desktop/screen-ring.cjs');
const mux=require('../desktop/clip-mux.cjs');
const temporary=fs.mkdtempSync(path.join(os.tmpdir(),'pine-recent-mix-'));
app.setPath('userData',path.join(temporary,'profile'));
app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
const ring=new ScreenRing(),delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let shell,panel,selected='panel',exported,finished=false;
const stages=[];
const failTimer=setTimeout(()=>finish(new Error('Mix fidelity test timed out.')),55000);
function finish(error){
  if(finished)return;finished=true;clearTimeout(failTimer);
  try{ring.forget();}catch(_){}
  if(exported?.dir)mux.forget(exported.dir);
  if(error)console.error(error.stack||error);
  else console.log('PASS: recent video preserves historical media volume, boost, duck, mute and stereo in the exported MP4.');
  app.exit(error?1:0);
}
process.on('uncaughtException',finish);
// Distinct channel tones reveal accidental mono and wrong-frame audio.
const sourceCode=(left,right,amplitude)=>`(()=>{
  const sampleRate=48000,frames=sampleRate*24,bytes=new ArrayBuffer(44+frames*4);
  const view=new DataView(bytes),word=(at,s)=>{for(let i=0;i<s.length;i++)view.setUint8(at+i,s.charCodeAt(i));};
  word(0,'RIFF');view.setUint32(4,36+frames*4,true);word(8,'WAVE');word(12,'fmt ');
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,2,true);
  view.setUint32(24,sampleRate,true);view.setUint32(28,sampleRate*4,true);view.setUint16(32,4,true);view.setUint16(34,16,true);
  word(36,'data');view.setUint32(40,frames*4,true);
  for(let i=0;i<frames;i++){
    view.setInt16(44+i*4,Math.round(32767*${amplitude}*Math.sin(2*Math.PI*${left}*i/sampleRate)),true);
    view.setInt16(46+i*4,Math.round(32767*${amplitude}*Math.sin(2*Math.PI*${right}*i/sampleRate)),true);
  }
  window.sound=document.createElement('audio');sound.src=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
  document.body.appendChild(sound);window.context=new AudioContext({sampleRate});window.gain=context.createGain();
  gain.gain.value=1;context.createMediaElementSource(sound).connect(gain).connect(context.destination);
  sound.volume=1;return context.resume().then(()=>sound.play());
})()`;
function measure(pcm,seconds,channel,frequency){
  const rate=48000,start=Math.round(seconds*rate),frames=Math.round(.15*rate),binHz=rate/frames;
  let energy=0,strongest=0,peakFrequency=frequency;
  // Sum orthogonal DFT-bin energy (Parseval), rather than one peak bin:
  // async resampling and compressed packet seams spread a pure tone slightly.
  // Tone bands remain disjoint, so channel isolation is still verified.
  const spread=frequency*.05;
  for(let bin=Math.ceil((frequency-spread)/binHz);bin<=Math.floor((frequency+spread)/binHz);bin++){
    const probe=bin*binHz;let sine=0,cosine=0;
    for(let i=0;i<frames;i++){
      const value=pcm.readFloatLE(((start+i)*2+channel)*4),phase=2*Math.PI*probe*i/rate;
      sine+=value*Math.sin(phase);cosine+=value*Math.cos(phase);
    }
    const value=2*Math.hypot(sine,cosine)/frames;energy+=value*value;
    if(value>strongest){strongest=value;peakFrequency=probe;}
  }
  return {amplitude:Math.sqrt(energy),frequency:peakFrequency};
}
function amplitude(pcm,seconds,channel,frequency){return measure(pcm,seconds,channel,frequency).amplitude;}
app.whenReady().then(async()=>{
  const preferences={nodeIntegration:true,contextIsolation:false,backgroundThrottling:false};
  shell=new BrowserWindow({show:false,width:320,height:180,webPreferences:preferences});
  panel=new BrowserWindow({show:false,width:320,height:180,webPreferences:preferences});
  session.defaultSession.setPermissionRequestHandler((_contents,_permission,callback)=>callback(true));
  session.defaultSession.setPermissionCheckHandler(()=>true);
  session.defaultSession.setDisplayMediaRequestHandler((request,callback)=>{
    assert.equal(request.frame,shell.webContents.mainFrame);
    callback({audio:(selected==='shell'?shell:panel).webContents.mainFrame,enableLocalEcho:true});
  });
  ipcMain.handle('fixture:select',(_event,target)=>{selected=target;return {ok:true};});
  ipcMain.handle('fixture:begin',(_event,options)=>ring.begin(options));
  ipcMain.handle('fixture:push',(_event,bytes,metadata)=>ring.take(Buffer.from(bytes),metadata));
  const page=path.join(temporary,'fixture.html');fs.writeFileSync(page,'<!doctype html><body>Isolated mix fixture</body>');
  await shell.loadFile(page);await panel.loadFile(page);
  await panel.webContents.executeJavaScript(sourceCode(440,880,.16),true);
  await shell.webContents.executeJavaScript(sourceCode(660,1320,.04),true);
  // Only picture acquisition is replaced by a canvas; sound and export use production code.
  await shell.webContents.executeJavaScript(`(()=>{
    const ipc=require('electron').ipcRenderer;
    Object.defineProperty(window,'devicePixelRatio',{value:1});
    Object.defineProperty(window,'outerWidth',{value:320});Object.defineProperty(window,'outerHeight',{value:180});
    const supported=MediaRecorder.isTypeSupported.bind(MediaRecorder);
    MediaRecorder.isTypeSupported=type=>type.startsWith('video/')?type==='video/webm;codecs=vp8':supported(type);
    window.pineDesktop={replaySource:async()=>({ok:true,id:'fixture',width:320,height:180}),
      replayAudioSources:async()=>({ok:true,targets:['shell','panel']}),
      replayAudioTarget:target=>ipc.invoke('fixture:select',target),
      replayBegin:options=>ipc.invoke('fixture:begin',options),
      replayPush:(bytes,metadata)=>ipc.invoke('fixture:push',new Uint8Array(bytes),metadata),
      replayStop:async()=>({ok:true}),onReplayFlush(){},onReplayAudioSourcesChanged(){}};
    const canvas=document.createElement('canvas');canvas.width=320;canvas.height=180;
    const paint=canvas.getContext('2d');window.fixturePaint=setInterval(()=>{paint.fillStyle='#223344';paint.fillRect(0,0,320,180);paint.fillStyle='white';paint.fillText(String(performance.now()),10,30);},16);
    navigator.mediaDevices.getUserMedia=async()=>canvas.captureStream(60);
  })()`);
  const renderer=fs.readFileSync(path.join(__dirname,'../desktop/renderer/screen-ring.js'),'utf8');
  await shell.webContents.executeJavaScript(renderer,true);
  await shell.webContents.executeJavaScript('PineScreenRing.start()',true);
  for(let attempt=0;attempt<100;attempt++){
    const state=await shell.webContents.executeJavaScript('PineScreenRing.state()');
    if(state.audio.complete&&state.running)break;
    if(attempt===99)throw new Error('Complete application sound never became available: '+JSON.stringify(state));
    await delay(30);
  }
  for(let attempt=0;!ring.pieces.length;attempt++){
    if(attempt>150)throw new Error('The fixture picture recorder produced no complete segment.');
    await delay(40);
  }
  const stage=async(name,code,expected)=>{
    await panel.webContents.executeJavaScript(code,true);
    const at=Date.now();stages.push({name,at,expected});await delay(1200);
  };
  await stage('baseline','sound.volume=1;gain.gain.value=1;sound.muted=false',.16);
  await stage('media volume','sound.volume=.25',.04);
  await stage('boost','gain.gain.value=1.5',.06);
  await stage('duck','gain.gain.value=.15',.006);
  await stage('element mute','sound.muted=true',0);
  await stage('unmute','sound.muted=false;sound.volume=.5;gain.gain.value=1',.08);
  await shell.webContents.executeJavaScript('PineScreenRing.flush()',true);
  const stopped=Date.now();
  await shell.webContents.executeJavaScript('PineScreenRing.stop()',true);await delay(150);
  // Today's level is deliberately different when the historical cut is requested.
  await panel.webContents.executeJavaScript('sound.volume=.01;gain.gain.value=.1',true);
  const ffmpeg=mux.findFfmpeg().path;
  const want={seconds:Math.max(1,(stopped-stages[0].at)/1000),end_at:stopped,video_only:false};
  const interval=ring.window(want.seconds,0,undefined,undefined,{clock:stopped});
  exported=await ring.cut(want,{ffmpeg});
  assert.equal(exported.ok,true,exported.detail);assert.equal(exported.audio.complete,true);
  const pcm=execFileSync(ffmpeg,['-v','error','-i',exported.out,'-map','0:a:0','-f','f32le','-ac','2','-ar','48000','pipe:1'],{windowsHide:true,maxBuffer:16*1024*1024});
  const report=[];
  for(const stage of stages){
    // Short encoder seams are covered by lifecycle tests. Measure levels
    // in a stable packet using the independent constant shell reference.
    const base=(stage.at-interval.start)/1000;
    const time=[.25,.45,.65,.85].map(offset=>base+offset).sort((a,b)=>
      amplitude(pcm,b,0,660)+amplitude(pcm,b,1,1320)-amplitude(pcm,a,0,660)-amplitude(pcm,a,1,1320))[0];
    const left=amplitude(pcm,time,0,440),right=amplitude(pcm,time,1,880);
    const shellLeft=amplitude(pcm,time,0,660),shellRight=amplitude(pcm,time,1,1320);
    report.push({stage:stage.name,left,right,shellLeft,shellRight,expected:stage.expected,shellLeftTone:measure(pcm,time,0,660),shellRightTone:measure(pcm,time,1,1320)});
    const tolerance=Math.max(.003,stage.expected*.18);
    assert.ok(Math.abs(left-stage.expected)<tolerance,stage.name+' left '+left+' vs '+stage.expected);
    assert.ok(Math.abs(right-stage.expected)<tolerance,stage.name+' right '+right+' vs '+stage.expected);
    assert.ok(Math.abs(shellLeft-.04)<.006,stage.name+' shell left '+shellLeft);
    assert.ok(Math.abs(shellRight-.04)<.006,stage.name+' shell right '+shellRight);
    assert.ok(amplitude(pcm,time,1,440)<.003,stage.name+' stereo left leaked right');
    assert.ok(amplitude(pcm,time,0,880)<.003,stage.name+' stereo right leaked left');
  }
  console.log(JSON.stringify({seconds:exported.seconds,report}));finish();
}).catch(finish);










