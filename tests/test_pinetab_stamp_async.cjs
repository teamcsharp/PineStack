/* A slow source hash cannot own Electron's main event loop. */
'use strict';
const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {EventEmitter}=require('node:events');
const {StampSampler}=require('../desktop/pinetab-stamp-async.cjs');
const {stamp}=require('../desktop/pinetab-stamp.cjs');
const {PinetabUpdate}=require('../desktop/pinetab-update.cjs');
const turn=()=>new Promise(resolve=>setImmediate(resolve));
function fixtureWorker(t) {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'stamp-worker-test-'));
  const workerPath=path.join(dir,'worker.cjs');
  fs.writeFileSync(workerPath,`const {parentPort}=require('node:worker_threads');let sequence=0;
parentPort.on('message',({id,root})=>{
 if(root==='slow'){parentPort.postMessage({entered:true});Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,250);}
 if(root==='failure'){parentPort.postMessage({id,error:'source read failed'});return;}
 parentPort.postMessage({id,value:{stamp:root+'.'+(++sequence),files:3}});
});`);
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  return workerPath;
}
test('a synchronously stalled worker leaves parent timers and IPC work responsive',async t=>{
  const client=new StampSampler({workerPath:fixtureWorker(t),timeoutMs:2000});
  t.after(()=>client.close());
  const pending=client.read('slow');
  await new Promise(resolve=>client.worker.on('message',m=>{if(m.entered)resolve();}));
  let finished=false;pending.then(()=>{finished=true;});
  await new Promise(resolve=>setTimeout(resolve,20));
  assert.equal(finished,false,'source hash remains blocked while parent timer executes');
  const unrelated=await Promise.resolve('IPC answered');
  assert.equal(unrelated,'IPC answered');
  assert.equal((await pending).stamp,'slow.1');
});
test('duplicate scans share one flight; cache expiry and fresh requests resample',async t=>{
  let clock=1000;
  const client=new StampSampler({workerPath:fixtureWorker(t),cacheMs:100,now:()=>clock});
  t.after(()=>client.close());
  const first=client.read('source'),second=client.read('source');
  assert.equal(first,second);
  const result=await first;
  assert.equal((await client.read('source')).stamp,result.stamp);
  assert.equal(client.sequence,1);
  assert.equal((await client.read('source',undefined,{fresh:true})).stamp,'source.2');
  clock+=101;
  assert.equal((await client.read('source')).stamp,'source.3');
});
test('worker errors fail the sample without poisoning another source result',async t=>{
  const client=new StampSampler({workerPath:fixtureWorker(t)});
  t.after(()=>client.close());
  await assert.rejects(client.read('failure'),/source read failed/);
  assert.equal((await client.read('healthy')).stamp,'healthy.1');
  assert.equal(client.pending.size,0);assert.equal(client.inFlight.size,0);
});
test('deadline rejects asynchronously and never starts overlapping replacement workers',async()=>{
  let workers=0,terminated=0;
  class StuckWorker extends EventEmitter {
    constructor(){super();workers++;}
    postMessage(){} unref(){}
    terminate(){terminated++;return new Promise(()=>{});}
  }
  const client=new StampSampler({WorkerClass:StuckWorker,timeoutMs:20});
  const pending=client.read('offline share');
  await assert.rejects(pending,/did not finish within/);
  assert.equal(terminated,1);assert.equal(workers,1);
  await assert.rejects(client.read('offline share'),/still stopping/);
  assert.equal(workers,1,'a native read that has not terminated cannot accumulate worker threads');
  client.worker.emit('exit',1);
  const retry=client.read('offline share');
  assert.equal(workers,2);
  client.worker.emit('message',{id:client.sequence,value:{stamp:'recovered',files:1}});
  assert.equal((await retry).stamp,'recovered');
  client.worker.emit('exit',0);
});
test('shipped worker preserves canonical APK hash inputs and detects fresh source edits',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'stamp-source-test-'));
  const write=(name,body)=>{const file=path.join(root,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,body);};
  write('app/src/main/java/Main.kt','initial source');
  write('app/src/main/assets/pine-views/view.js','old bundled asset');
  write('desktop/renderer/view.js','canonical renderer');
  write('app/build.gradle.kts','test build');
  const client=new StampSampler();
  t.after(async()=>{await client.close();fs.rmSync(root,{recursive:true,force:true});});
  const expected=stamp(root);
  assert.deepEqual(await client.read(root),expected);
  write('app/src/main/java/Main.kt','changed source with different size');
  assert.deepEqual(await client.read(root),expected,'ordinary callers use the recent completed sample');
  const fresh=await client.read(root,undefined,{fresh:true});
  assert.deepEqual(fresh,stamp(root));assert.notEqual(fresh.stamp,expected.stamp);
});
test('tablet check awaits source proof without blocking unrelated parent work',async()=>{
  let resolve,calls=0,looked=0;
  const sample=new Promise(done=>{resolve=done;});
  const updater=new PinetabUpdate({agentRoot:()=>'/source',sampleStamp:()=>{calls++;return sample;},
    getJson:async()=>{looked++;return {seen:{agent:'PineBoxKiosk/1.0.0+aaaaaaaaaaaa'}};}});
  const pending=updater.check({});
  await turn();assert.equal(calls,1);assert.equal(looked,0);
  resolve({stamp:'aaaaaaaaaaaa',files:7});
  const result=await pending;
  assert.equal(result.stale,false);assert.equal(result.files,7);assert.equal(looked,1);
});
test('explicit version validation forces a fresh source proof',async()=>{
  const options=[];
  const updater=new PinetabUpdate({agentRoot:()=>'/source',sampleStamp:async(_root,_canon,want)=>{
    options.push(want);return {stamp:'bbbbbbbbbbbb',files:1};}});
  updater.locate=async()=> 'tablet';updater.installedByAdb=async()=>({stamp:'aaaaaaaaaaaa'});
  const result=await updater.action('version');
  assert.equal(result.wanted,'bbbbbbbbbbbb');assert.equal(options[0].fresh,true);
});


test('fresh validations run after an older automatic scan and share their new proof',async t=>{
  const client=new StampSampler({workerPath:fixtureWorker(t),timeoutMs:2000});
  t.after(()=>client.close());
  const automatic=client.read('slow');
  const fresh=client.read('slow',undefined,{fresh:true});
  const duplicate=client.read('slow',undefined,{fresh:true});
  assert.equal(fresh,duplicate);assert.notEqual(fresh,automatic);
  const values=await Promise.all([automatic,fresh,duplicate]);
  assert.equal(values[0].stamp,'slow.1');assert.equal(values[1].stamp,'slow.2');
  assert.equal(values[2].stamp,'slow.2');assert.equal(client.sequence,2);
});
