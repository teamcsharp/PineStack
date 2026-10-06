"use strict";
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),vm=require('node:vm');
const {Glass}=require('../desktop/terminal-glass.cjs');
const {planArgs}=require('../desktop/clip-mux.cjs');
const captured={source:'android-playback-mix',present:true,complete:true,channels:2,coverage_ratio:1,state:'captured'};

async function pullReplay(audio,options){
 const oldFetch=global.fetch,oldWebSocket=global.WebSocket;
 const savedOptions=[],calls=[];let downloaded=0,clock=1000,lateSoundCalls=0;
 const mp4=Buffer.from('the already recorded video and stereo mix');
 const bridge={
  replayState:async()=>({ok:true,seconds:70}),
  replaySave:async opts=>{savedOptions.push(opts);return {ok:true,bytes:mp4.length,seconds:60,audio};},
  replayChunk:async opts=>{downloaded++;clock+=120000;return {ok:true,at:opts.at,sent:mp4.length,done:true,b64:mp4.toString('base64')};}
 };
 class Socket{
  constructor(){this.handlers=new Map();queueMicrotask(()=>this.emit('open',{}));}
  addEventListener(kind,fn){const list=this.handlers.get(kind)||[];list.push(fn);this.handlers.set(kind,list);}
  removeEventListener(kind,fn){this.handlers.set(kind,(this.handlers.get(kind)||[]).filter(one=>one!==fn));}
  emit(kind,event){for(const fn of [...(this.handlers.get(kind)||[])])fn(event);}
  close(){}
  send(text){const request=JSON.parse(text);calls.push(request.params.expression);
   Promise.resolve(vm.runInNewContext(request.params.expression,{window:{pineDesktop:bridge,PineAir:{seconds:()=>60,sliceWav:()=>{lateSoundCalls++;throw Error('This later mix must not replace the recording');}}}}))
    .then(value=>this.emit('message',{data:JSON.stringify({id:request.id,result:{result:{value}}})}));
  }
 }
 global.fetch=async()=>({json:async()=>[{type:'page',webSocketDebuggerUrl:'ws://tablet/'}]});
 global.WebSocket=Socket;
 try{
  const glass=new Glass({run:async args=>args.includes('shell')?'456':'',now:()=>clock});
  const made=await glass.clip_fromReplay(60,options);
  return {made,savedOptions,calls,downloaded,lateSoundCalls,mp4};
 }finally{global.fetch=oldFetch;global.WebSocket=oldWebSocket;}
}

test('tablet replay retains the earlier recorded stereo mix even when downloading advances time',async()=>{
 const result=await pullReplay(captured);
 assert.equal(result.made.ok,true);assert.deepEqual(result.made.mp4,result.mp4);
 assert.deepEqual(result.made.audioMeta,captured);assert.equal(result.made.embeddedAudio,true);
 assert.equal(result.made.at,121000);assert.equal(result.lateSoundCalls,0);
 assert.equal(result.made.audio.broadcast,null);assert.equal(result.savedOptions[0].video_only,false);
});

test('tablet replay refuses incomplete and unknown audio before fetching a recording',async()=>{
 for(const audio of [undefined,{present:false,complete:false},{present:true,complete:false,detail:'Recorded audio has a gap'}]){
  const result=await pullReplay(audio);
  assert.equal(result.made.ok,false);assert.match(result.made.why,/audio|gap/);
  assert.equal(result.downloaded,0);assert.equal(result.lateSoundCalls,0);
 }
});

test('explicit picture-only exports and internal still inspection bypass audio coverage',async()=>{
 for(const options of [{video_only:true},{silent:true}]){
  const result=await pullReplay({present:false,complete:false},options);
  assert.equal(result.made.ok,true);assert.equal(result.savedOptions[0].video_only,true);
  assert.equal(result.made.embeddedAudio,false);assert.equal(result.lateSoundCalls,0);
 }
});

test('the tablet editor trims the embedded stereo samples on the video clock at unity gain',()=>{
 const args=planArgs({video:'captured.mp4',embeddedAudio:true,broadcast:{path:'later.wav'},inPoint:2,outPoint:8,mono:false,gains:{broadcast:0},out:'edited.mp4'});
 const graph=args[args.indexOf('-filter_complex')+1];
 assert.match(graph,/\[0:a\]atrim=start=2[.]000:end=8[.]000,asetpts=PTS-\(2[.]000\)\/TB\[broadcast\]/);
 assert.match(graph,/\[0:v\]trim=start=2[.]000:end=8[.]000,setpts=PTS-\(2[.]000\)\/TB/);
 assert.equal(args.includes('later.wav'),false);assert.equal(args.includes('-an'),false);
 assert.equal(args.includes('-ac'),false);assert.doesNotMatch(graph,/channel_layouts=mono|volume=|amix|join=/);
 assert.ok(args.includes('[broadcast]'));
 const legacy=planArgs({video:'silent.mp4',broadcast:{path:'broadcast.wav'},inPoint:0,outPoint:8,mono:false,out:'legacy.mp4'});
 assert.equal(legacy[legacy.indexOf('-ac')+1],'1');
 assert.match(legacy[legacy.indexOf('-filter_complex')+1],/channel_layouts=mono/);
});

function editorHarness(){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'pine-tablet-editor-')),handlers=new Map(),plans=[];
 const source=fs.readFileSync(path.join(__dirname,'../desktop/main.js'),'utf8');
 const start=source.indexOf('const clipWaiting = new Map();'),end=source.indexOf('/* THE LOCAL RECORDING,',start);
 assert.ok(start>=0&&end>start);
 class Window{
  constructor(){this.webContents={id:1};}setMenuBarVisibility(){}on(){}loadFile(){}close(){}isDestroyed(){return false;}
  static fromWebContents(){return null;}
 }
 const context={fs,path,__dirname:path.join(__dirname,'../desktop'),BrowserWindow:Window,
  clipMux:{stash:()=>dir,forget:()=>{},mux:async plan=>{plans.push(plan);return {ok:true,path:plan.out};}},
  ipcMain:{handle:(name,fn)=>handlers.set(name,fn)},app:{getPath:()=>dir},readConfig:()=>({}),shell:{showItemInFolder:()=>{}},
  require:()=>({dialog:{showSaveDialog:async()=>({filePath:path.join(dir,'export.mp4')})}})};
 const open=vm.runInNewContext(source.slice(start,end)+';openClipExport',context);
 return {dir,handlers,plans,open};
}

test('the tablet editor carries embedded playback through preview and export; legacy WAV takes still work',async()=>{
 const harness=editorHarness(),event={sender:{id:1}};
 const choices={inPoint:1,outPoint:4,mono:false,use:{broadcast:true,mic:false},gains:{broadcast:0}};
 try{
  harness.open({mp4:Buffer.from('native stereo video'),seconds:5,audioMeta:captured,embeddedAudio:true,audio:{broadcast:{wav:Buffer.alloc(60)}}});
  const pending=await harness.handlers.get('clip:pending')(event);
  assert.equal(pending.embeddedAudio,true);assert.equal(pending.broadcastUrl,null);
  await harness.handlers.get('clip:export')(event,choices);
  assert.equal(harness.plans[0].embeddedAudio,true);assert.equal(harness.plans[0].broadcast,null);assert.equal(harness.plans[0].mono,false);
  await harness.handlers.get('clip:export')(event,{...choices,use:{broadcast:false}});
  assert.equal(harness.plans[1].embeddedAudio,false,'The editor can explicitly remove recorded sound');
  harness.open({mp4:Buffer.from('legacy silent video'),seconds:5,audio:{broadcast:{wav:Buffer.alloc(60)}}});
  await harness.handlers.get('clip:export')(event,choices);
  assert.equal(harness.plans[2].embeddedAudio,false);assert.match(harness.plans[2].broadcast.path,/broadcast[.]wav$/);
 }finally{fs.rmSync(harness.dir,{recursive:true,force:true});}
});

test('embedded preview uses the video soundtrack once and retains its stereo channels and gain',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../desktop/renderer/clip-export.js'),'utf8');
 const start=source.indexOf('function gainOf('),end=source.indexOf('function bothIn()',start);
 let sources=0,gains=0;
 const gain={gain:{value:0},connect:()=>audio.destination},film={muted:true};
 const audio={destination:{},createMediaElementSource:element=>{assert.equal(element,film);sources++;return {connect:node=>node};},createGain:()=>{gains++;return gain;},createBufferSource:()=>assert.fail('Do not decode and replay a second soundtrack'),createStereoPanner:()=>assert.fail('Do not pan the captured mix to one side')};
 const tracks={broadcast:{db:0,use:true,there:true},mic:{db:0,use:false,there:false}};
 const context={clip:{embeddedAudio:true},film,tracks,ensureContext:()=>audio,stopVoices:()=>{},embeddedSource:null,embeddedGain:null,voices:[]};
 vm.runInNewContext(source.slice(start,end)+';start();start();applyGains();',context);
 assert.equal(sources,1);assert.equal(gains,1);assert.equal(gain.gain.value,1);assert.equal(film.muted,false);
 tracks.broadcast.db=-6;vm.runInNewContext('applyGains()',context);assert.ok(Math.abs(gain.gain.value-Math.pow(10,-6/20))<1e-9);
 tracks.broadcast.use=false;vm.runInNewContext('start()',context);assert.equal(gain.gain.value,0);assert.equal(sources,1);
});
