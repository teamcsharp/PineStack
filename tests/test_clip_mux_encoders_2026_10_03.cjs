"use strict";
const { test }=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {createRequire}=require('node:module');

function isolatedMux(handle, settings = {}) {
  const file=path.resolve(__dirname,'../desktop/clip-mux.cjs');
  const localRequire=createRequire(file), calls=[], priorities=[];
  const module={exports:{}};
  const fakeProcess={execFile(exe,args,options,callback){
    const call={exe,args:[...args],options};calls.push(call);
    queueMicrotask(()=>{
      try{
        const result=handle(call)||{};
        callback(result.error||null,result.stdout||'',result.stderr||'');
      }catch(error){callback(error,'',error.message);}
    });
    return {pid:settings.childPid};
  }};
  const context=vm.createContext({process,Buffer});
  const factory=vm.runInContext('(function(require,module,exports,__filename,__dirname){'+fs.readFileSync(file,'utf8')+'\n})',context);
  const fakeOs={...localRequire('node:os'),setPriority(pid,priority){
    priorities.push({pid,priority});if(settings.priorityError)throw new Error('Priority denied');
  }};
  factory(name=>name==='node:child_process'?fakeProcess:name==='node:os'?fakeOs:localRequire(name),module,module.exports,file,path.dirname(file));
  return {mux:module.exports,calls,priorities};
}
const probe=call=>call.args.includes('lavfi');
const codec=call=>call.args[call.args.indexOf('-c:v')+1];
const graph='[0:v]null[v];[1:a]asetpts=PTS-(0.125)/TB,aresample=48000:first_pts=0[a]';
function plan(mux,encoder,out='screen.mp4'){
  return ['-y','-i','picture.webm','-i','sound.webm','-filter_complex',graph,
    '-map','[v]','-map','[a]','-c:a','aac','-b:a','192k',...mux.encoderArgs(encoder),'-movflags','+faststart',out];
}

test('a GPU render failure retries on CPU with the exact same audio inputs and timing graph',async()=>{
  const {mux,calls}=isolatedMux(call=>{
    if(!probe(call)&&codec(call)==='h264_nvenc')return {error:new Error('Device lost'),stderr:'NVENC device lost during encoding'};
  });
  const result=await mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder));
  assert.equal(result.encoder,'libx264');assert.equal(result.hardware,false);
  assert.match(result.fallback_detail,/device lost/);
  assert.equal(calls.filter(probe).length,1,'a working NVIDIA probe avoids idle vendor probes');
  const image=calls.find(probe).args.find(value=>value.startsWith('color='));
  assert.match(image,/s=640x360:/,'hardware probe must exceed driver minimum frame dimensions');
  const renders=calls.filter(call=>!probe(call));assert.equal(renders.length,2);
  for(const call of renders){
    assert.equal(call.args[call.args.indexOf('-filter_complex')+1],graph);
    assert.ok(call.args.includes('sound.webm'));assert.ok(call.args.includes('[a]'));
    assert.equal(call.args.includes('-an'),false);
    assert.equal(call.options.windowsHide,true);
  }
  assert.equal(JSON.stringify(renders[0].args.slice(0,renders[0].args.indexOf('-c:v'))),
    JSON.stringify(renders[1].args.slice(0,renders[1].args.indexOf('-c:v'))));
});

test('concurrent exports share one real device probe and each encode their own snapshot',async()=>{
  const {mux,calls}=isolatedMux(()=>{});
  const results=await Promise.all([
    mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder,'first.mp4')),
    mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder,'second.mp4'))
  ]);
  assert.equal(calls.filter(probe).length,1);
  assert.ok(results.every(result=>result.encoder==='h264_nvenc'&&result.hardware));
  assert.deepEqual(calls.filter(call=>!probe(call)).map(call=>call.args.at(-1)).sort(),['first.mp4','second.mp4']);
});

test('explicit CPU exports never spend time probing GPU devices',async()=>{
  const {mux,calls}=isolatedMux(()=>{});
  const result=await mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder),{encoder:'cpu'});
  assert.equal(result.encoder,'libx264');assert.equal(result.hardware,false);
  assert.equal(calls.length,1);assert.equal(probe(calls[0]),false);
});

test('hardware discovery advances after a refused device and stops at the first usable vendor',async()=>{
  const {mux,calls}=isolatedMux(call=>{
    if(probe(call)&&codec(call)==='h264_nvenc')return {error:new Error('No NVIDIA device'),stderr:'Cannot load nvEncodeAPI64.dll'};
  });
  const result=await mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder));
  assert.equal(result.encoder,'h264_qsv');assert.equal(result.hardware,true);
  assert.deepEqual(calls.filter(probe).map(codec),['h264_nvenc','h264_qsv']);
  assert.equal(calls.some(call=>codec(call)==='h264_amf'),false);
});

test('all unavailable devices fall back to CPU with reasons and keep audio mapped',async()=>{
  const {mux,calls}=isolatedMux(call=>probe(call)?{error:new Error('No hardware'),stderr:'No available hardware device'}:{});
  const result=await mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder));
  assert.equal(result.encoder,'libx264');assert.equal(result.hardware,false);
  assert.match(result.fallback_detail,/h264_nvenc/);assert.match(result.fallback_detail,/h264_qsv/);assert.match(result.fallback_detail,/h264_amf/);
  assert.equal(calls.filter(probe).length,3);
  assert.ok(calls.at(-1).args.includes('[a]'));
});

test('a refusal by both encoders raises the error without producing a silent retry',async()=>{
  const {mux,calls}=isolatedMux(call=>probe(call)?{}:{error:new Error('Invalid source audio'),stderr:'Invalid source audio'});
  await assert.rejects(mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder)),/recording could not be encoded.*Invalid source audio/);
  const renders=calls.filter(call=>!probe(call));assert.equal(renders.length,2);
  assert.ok(renders.every(call=>call.args.includes('[a]')&&!call.args.includes('-an')));
});


test('export workers yield CPU priority without changing encoding arguments',async()=>{
  const {mux,calls,priorities}=isolatedMux(()=>{},{childPid:4242});
  await mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder),{encoder:'cpu'});
  assert.deepEqual(priorities,[{pid:4242,priority:require('node:os').constants.priority.PRIORITY_BELOW_NORMAL}]);
  assert.equal(calls.at(-1).args[calls.at(-1).args.indexOf('-filter_complex')+1],graph);
});

test('a refused priority change never fails an otherwise successful export',async()=>{
  const {mux,priorities}=isolatedMux(()=>{},{childPid:4242,priorityError:true});
  const result=await mux.encodeVideo('ffmpeg',encoder=>plan(mux,encoder),{encoder:'cpu'});
  assert.equal(result.encoder,'libx264');assert.equal(priorities.length,1);
});

test('an actual spawned worker observes below-normal CPU priority',async()=>{
  const realMux=require('../desktop/clip-mux.cjs');
  const reported=await realMux.run(process.execPath,
    ['-e','process.stdout.write(String(require("node:os").getPriority()))'],10000);
  assert.equal(Number(reported),require('node:os').constants.priority.PRIORITY_BELOW_NORMAL);
});


test('encoder failures retain the specific driver reason above generic EOF chatter',()=>{
  const {mux}=isolatedMux(()=>{});
  const diagnostic=mux.lastReal('[h264_nvenc] InitializeEncoder failed: Frame Dimension less than the minimum supported value.\n'+
    Array.from({length:10},()=> '[output] Task finished with error code: -22').join('\n'));
  assert.match(diagnostic,/Frame Dimension less than the minimum/);
});
