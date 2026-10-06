'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {DesktopHealth,install}=require('../desktop/desktop-health.cjs');
const turn=()=>new Promise(r=>setImmediate(r));
function memoryIO(){
  const files=new Map(),calls=[];
  return {files,calls,io:{
    async mkdir(){},
    async stat(file){if(!files.has(file))throw Error('missing');return {size:Buffer.byteLength(files.get(file))};},
    async rename(from,to){calls.push(['rotate',from,to]);files.set(to,files.get(from));files.delete(from);},
    async writeFile(file,text){files.set(file,text);},
    async appendFile(file,text){calls.push(['append',file]);await turn();files.set(file,(files.get(file)||'')+text);}
  }};
}
test('overlapping diagnostic writes preserve complete ordered records',async()=>{
  const m=memoryIO(),h=new DesktopHealth({file:'/logs/pine-health.jsonl',io:m.io});
  assert.deepEqual(await Promise.all([h.record('first'),h.record('second'),h.record('third')]),[true,true,true]);
  assert.deepEqual(m.files.get('/logs/pine-health.jsonl').trim().split('\n').map(s=>JSON.parse(s).kind),['first','second','third']);
});
test('diagnostics rotate before exceeding the bounded local log',async()=>{
  const m=memoryIO(),h=new DesktopHealth({file:'/logs/pine-health.jsonl',io:m.io,maxBytes:125});
  await h.record('one');await h.record('two');await h.record('three');
  assert.ok(m.calls.some(c=>c[0]==='rotate'));
  assert.ok(Buffer.byteLength(m.files.get('/logs/pine-health.jsonl'))<=125);
  assert.ok(Buffer.byteLength(m.files.get('/logs/pine-health.jsonl.previous'))<=125);
});
test('a failed diagnostic write neither throws nor poisons later writes',async()=>{
  const m=memoryIO(),append=m.io.appendFile;let fail=true;
  m.io.appendFile=async(...args)=>{if(fail){fail=false;throw Error('disk unavailable');}return append(...args);};
  const h=new DesktopHealth({file:'/logs/pine-health.jsonl',io:m.io});
  assert.equal(await h.record('failed'),false);assert.equal(await h.record('recovered'),true);
});
test('cyclic details and oversized details cannot break recording',async()=>{
  const m=memoryIO(),h=new DesktopHealth({file:'/logs/pine-health.jsonl',io:m.io});
  const cyclic={};cyclic.self=cyclic;
  assert.equal(await h.record('cyclic',cyclic),false);
  assert.equal(await h.record('large',{error:'x'.repeat(20000)}),true);
  const line=m.files.get('/logs/pine-health.jsonl');assert.ok(Buffer.byteLength(line)<8192);assert.equal(JSON.parse(line).kind,'large');
});
test('renderer exit and a main-loop delay leave distinct useful local evidence',async()=>{
  const app=new EventEmitter(),processEvents=new EventEmitter(),m=memoryIO();let at=1000;
  app.whenReady=()=>Promise.resolve();
  const h=install({app,getFile:()=>'/logs/pine-health.jsonl',processEvents,now:()=>at,everyMs:10,gapMs:50});
  h.io=m.io;
  const c=new EventEmitter();c.getTitle=()=> 'The tablet, live';
  app.emit('web-contents-created',null,c);
  app.emit('render-process-gone',null,c,{reason:'crashed',exitCode:9});
  c.emit('unresponsive');processEvents.emit('uncaughtExceptionMonitor',Error('remote load failed'));
  at+=100;await new Promise(r=>setTimeout(r,25));h.stop();await h.pending;
  const events=m.files.get('/logs/pine-health.jsonl').trim().split('\n').map(s=>JSON.parse(s));
  assert.ok(events.some(e=>e.kind==='renderer-gone'&&e.reason==='crashed'&&e.title==='The tablet, live'));
  assert.ok(events.some(e=>e.kind==='window-unresponsive'));
  assert.ok(events.some(e=>e.kind==='main-exception'&&/remote load failed/.test(e.error)));
  assert.ok(events.some(e=>e.kind==='main-loop-gap'&&e.elapsedMs===100));
});
