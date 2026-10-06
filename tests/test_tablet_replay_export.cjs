const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {createTabletReplayExporter,DURATIONS}=require('../desktop/tablet-replay-export.cjs');
const captured={source:'android-playback-mix',present:true,complete:true,channels:2,state:'captured',coverage_ratio:1};

test('all durations preserve the captured MP4 without replacing its stereo mix',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'pine-tablet-exports-'));let count=0,clean=0,asked=[];
 const video=Buffer.from('native video plus captured stereo playback');
 const exportClip=createTabletReplayExporter({glass:async()=>({clip_fromReplay:async(seconds,options)=>{asked.push(seconds);assert.equal(options.video_only,false);return {ok:true,mp4:video,seconds:43,notes:['short buffer'],audioMeta:captured,embeddedAudio:true,audio:{broadcast:{wav:Buffer.alloc(60),offset:10}}};}}),mux:{stash:()=>{const p=path.join(dir,'work-'+count);fs.mkdirSync(p);return p;},mux:async()=>{assert.fail('Captured playback must not be reconstructed or remixed');},forget:p=>{clean++;fs.rmSync(p,{recursive:true,force:true});}},folder:()=>path.join(dir,'recordings'),config:()=>({}),now:()=>++count});
 try{for(const seconds of DURATIONS){const got=await exportClip({seconds});assert.equal(got.ok,true);assert.equal(got.asked,seconds);assert.equal(got.seconds,43);assert.equal(got.clamped,true);assert.equal(got.audio,captured);assert.match(got.where,/\.mp4$/);assert.deepEqual(await fs.promises.readFile(got.where),video);}assert.deepEqual(asked,[60,120,180,300,600,900,1800,3600]);assert.equal(clean,8);assert.equal((await exportClip({seconds:7})).ok,false);}finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('incomplete or unknown recorded audio is refused without writing a substitute soundtrack',async()=>{
 for(const audioMeta of [undefined,{present:false,complete:false},{present:true,complete:false,detail:'A captured audio gap'}]){
  const exporter=createTabletReplayExporter({glass:async()=>({clip_fromReplay:async()=>({ok:true,mp4:Buffer.from('video'),seconds:30,audioMeta,audio:{broadcast:{wav:Buffer.alloc(60)}}})}),mux:{stash:()=>assert.fail('Unavailable audio must be refused before creating an export')},folder:()=>assert.fail('No recording should be written'),config:()=>({})});
  const got=await exporter({seconds:60});assert.equal(got.ok,false);assert.match(got.detail,/audio|gap/);
 }
});

test('an explicit picture-only request can export without audio coverage',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'pine-tablet-picture-'));let options;
 const exporter=createTabletReplayExporter({glass:async()=>({clip_fromReplay:async(_seconds,given)=>{options=given;return {ok:true,mp4:Buffer.from('video only'),seconds:30,audioMeta:{present:false,complete:false,video_only_explicit:true}};}}),mux:{stash:()=>dir,forget:()=>{}},folder:()=>path.join(dir,'recordings'),config:()=>({}),now:()=>1});
 try{const got=await exporter({seconds:60,video_only:true});assert.equal(got.ok,true);assert.equal(options.video_only,true);assert.equal(await fs.promises.readFile(got.where,'utf8'),'video only');}finally{fs.rmSync(dir,{recursive:true,force:true});}
});

test('concurrent exports are refused and a missing tablet creates no recording',async()=>{let release;const exporter=createTabletReplayExporter({glass:async()=>({clip_fromReplay:()=>new Promise(r=>release=r)}),mux:{},folder:()=>'',config:()=>({})});const pending=exporter({seconds:60});await new Promise(r=>setImmediate(r));assert.match((await exporter({seconds:120})).detail,/already/);release({ok:false,why:'tablet offline'});assert.match((await pending).detail,/offline/);});
