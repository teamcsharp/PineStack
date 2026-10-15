'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const start = source.indexOf('ipcMain.handle("replay:export"');
const end = source.indexOf('/* THE SAME CUT', start);
function fixture({audio = {present:true, complete:false}, uploadFails = false, saveFails = false} = {}) {
  let handler, clock = 1700000000000;
  const cuts = [], saved = [], events = [], forgotten = [];
  const made = {ok:true, out:'/cache/screen.mp4', dir:'/cache', seconds:298, clamped:true, audio};
  const context = {Date:{now:()=>clock}, Number, AbortSignal, path,
    ipcMain:{handle:(_name, fn)=>{handler=fn;}},
    replayProgressTeller:()=>({tell:(...args)=>events.push(args)}),
    replayFlush:async()=>{clock+=900;},
    screenRing:{cut:async want=>{cuts.push(want); return made;}},
    replayWithSound:async()=>({path:made.out,audio}),
    readConfig:()=>({baseUrl:'http://station'}), app:{getPath:()=>'/local'},
    replayFolder:()=>'/configured', replayName:()=> 'clip.mp4',
    authHeaders:()=>({}),
    fs:{statSync:()=>({size:123}), createReadStream:()=> 'stream', promises:{
      mkdir:async()=>{}, copyFile:async(_from,to)=>{
        if(saveFails && to.includes('configured')) throw Error('share offline'); saved.push(to);
      }}},
    clipMux:{forget:dir=>forgotten.push(dir)},
    fetch:async()=>{if(uploadFails)throw Error('station offline');return {ok:true,text:async()=>'{"name":"clip.mp4"}'};}
  };
  vm.runInNewContext(source.slice(start,end),context);
  return {run:want=>handler({}, {seconds:300, view:'pip', require_audio:false, ...want}),cuts,saved,events,forgotten};
}
test('a command preserves partial recorded audio and freezes the requested moment before flush', async()=>{
  const f=fixture(), endAt=1699999995000;
  const result=await f.run({upload:true,end_at:endAt});
  assert.equal(result.ok,true); assert.equal(f.cuts[0].end_at,endAt);
  assert.equal(f.cuts[0].view,'pip'); assert.equal(f.cuts[0].video_only,false);
  assert.equal(result.audio.present,true); assert.match(result.warning,/available mix was preserved/);
  assert.match(result.warning,/298.*300/); assert.match(result.where,/local.*recordings/);
  assert.equal(f.events.at(-1)[0],'done'); assert.match(f.events.at(-1)[2].say,/Saved 298/);
});
test('offline upload still returns a saved MP4 and reports its path',async()=>{
  const f=fixture({uploadFails:true}),result=await f.run({upload:true});
  assert.equal(result.ok,true); assert.equal(result.uploaded.ok,false);
  assert.equal(f.saved.length,1); assert.match(result.warning,/Station upload failed/);
  assert.equal(f.events.at(-1)[0],'done');
});
test('offline destination falls back locally without discarding the encoded picture',async()=>{
  const f=fixture({saveFails:true}),result=await f.run({});
  assert.equal(result.ok,true); assert.match(result.where,/local.*recordings/);
  assert.match(result.warning,/configured folder was unavailable/);
});
test('explicit strict audio requests still reject incomplete audio',async()=>{
  const f=fixture(), result=await f.run({require_audio:true});
  assert.equal(result.ok,false); assert.equal(f.saved.length,0);
});
test('a command with no captured audio saves the picture and identifies the missing sound',async()=>{
  const f=fixture({audio:{present:false,complete:false}}),result=await f.run({});
  assert.equal(result.ok,true); assert.match(result.warning,/No audio was captured/);
});

test('independent command poll works without station feed; lost completion is retried without re-encoding',async()=>{
  const elements=new Map();
  const document={getElementById:id=>elements.get(id),createElement:()=>({style:{},setAttribute(){},
    appendChild(child){elements.set(child.id,child);}}),body:{appendChild(child){elements.set(child.id,child);}}};
  let poll, cuts=0, attempts=0, fail=true;
  const window={document,setInterval:fn=>{poll=fn;},pineDesktop:{
    get:async()=>({ok:true,order:{id:'pip',target:'pip'}}),
    post:async(route)=>{
      if(route.endsWith('claim'))return {go:true,seconds:300,name:'pip.mp4',age_ms:2500};
      if(route.endsWith('done')){attempts++;if(fail)throw Error('offline');return {ok:true};}
      return {ok:true};
    },replayExport:async want=>{cuts++;assert.equal(want.require_audio,false);assert.ok(want.end_at<Date.now()-2400);
      return {ok:true,where:'local.mp4',uploaded:{ok:false}};}
  }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../desktop/renderer/screen-export.js'),'utf8'),{window,console:{error(){}}});
  await new Promise(setImmediate);assert.equal(cuts,1);assert.equal(attempts,1);
  fail=false;await poll();await new Promise(setImmediate);await poll();
  assert.equal(cuts,1);assert.equal(attempts,2);
});
