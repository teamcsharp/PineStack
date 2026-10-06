'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {reloadMirrorView}=require('../desktop/mirror-view-reload.cjs');
function fixture(){const contents=new EventEmitter(),tasks=new Map();let id=0,reloads=0;
 contents.reload=()=>reloads++;contents.isDestroyed=()=>false;
 const timers={setTimeout(fn,ms){tasks.set(++id,{fn,ms});return id},clearTimeout(id){tasks.delete(id)}};
 return {contents,timers,tasks,reloads:()=>reloads,fire(ms){const entry=[...tasks].find(([,t])=>t.ms===ms);tasks.delete(entry[0]);entry[1].fn();}};}
test('crash recovery waits for process teardown, then uses an actual reload and load acknowledgement',async()=>{
 const f=fixture(),pending=reloadMirrorView(f.contents,{timers:f.timers});
 assert.equal(f.reloads(),0);f.fire(750);assert.equal(f.reloads(),1);
 f.contents.emit('did-finish-load');await pending;assert.equal(f.tasks.size,0);assert.equal(f.contents.listenerCount('did-fail-load'),0);
});
test('a failed main-frame reload rejects and leaves no recovery listeners or timers',async()=>{
 const f=fixture(),pending=reloadMirrorView(f.contents,{timers:f.timers});f.fire(750);
 f.contents.emit('did-fail-load',null,-2,'ERR_FAILED','',true);
 await assert.rejects(pending,/ERR_FAILED/);assert.equal(f.tasks.size,0);assert.equal(f.contents.listenerCount('render-process-gone'),0);
});
test('subframe failures and aborted navigation do not report a failed main view',async()=>{
 const f=fixture(),pending=reloadMirrorView(f.contents,{timers:f.timers});f.fire(750);
 f.contents.emit('did-fail-load',null,-2,'iframe failed','',false);
 f.contents.emit('did-fail-load',null,-3,'aborted','',true);f.contents.emit('did-finish-load');await pending;
});
test('another renderer exit during reload is bounded and reported',async()=>{
 const f=fixture(),pending=reloadMirrorView(f.contents,{timers:f.timers});f.fire(750);f.contents.emit('render-process-gone');
 await assert.rejects(pending,/exited during recovery/);assert.equal(f.tasks.size,0);
});
test('a closed view cannot be reloaded after its settle delay',async()=>{
 const f=fixture();f.contents.isDestroyed=()=>true;
 const pending=reloadMirrorView(f.contents,{timers:f.timers});f.fire(750);
 await assert.rejects(pending,/was closed/);assert.equal(f.reloads(),0);assert.equal(f.tasks.size,0);
});
test('a missing load acknowledgement times out and removes event listeners',async()=>{
 const f=fixture(),pending=reloadMirrorView(f.contents,{timers:f.timers});f.fire(750);f.fire(10000);
 await assert.rejects(pending,/timed out/);assert.equal(f.contents.listenerCount('did-finish-load'),0);assert.equal(f.tasks.size,0);
});
