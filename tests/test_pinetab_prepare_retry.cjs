'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {PinetabUpdate}=require('../desktop/pinetab-update.cjs');
(async()=>{
 for(const scenario of ['copy','build','always']){
  let source='aaaaaaaaaaaa',copies=0,builds=0;const dirs=[],events=[];
  const pu=new PinetabUpdate({send:(_,ev)=>events.push(ev)});
  pu.wanted=()=>({stamp:source});
  pu.snapshotSource=async dir=>{dirs.push(dir);copies++;const captured=source;if((scenario==='copy'&&copies===1)||scenario==='always')source=source==='aaaaaaaaaaaa'?'bbbbbbbbbbbb':'aaaaaaaaaaaa';return {root:dir,stamp:captured};};
  pu.deploy=async()=>{builds++;fs.writeFileSync(pu.ready.apk,'APK '+source);if(scenario==='build'&&builds===1)source='bbbbbbbbbbbb';return true;};
  try{
   const r=await pu.update('prepare');
   if(scenario==='always'){assert.equal(r.ok,false);assert.equal(copies,3);assert.equal(builds,0);assert.match(r.why,/still being edited/);}
   else{assert.ok(r.ready);assert.equal(r.wanted,source);assert.equal(copies,2);assert.equal(builds,scenario==='copy'?1:2);assert.ok(events.some(e=>e.step==='queue'));}
   assert.equal(pu.job.running,false);
  }finally{for(const dir of dirs){assert.ok(dir.startsWith(path.join(os.tmpdir(),'pinetab-ready-')));fs.rmSync(dir,{recursive:true,force:true});}}
 }
 console.log('PineTab retries copy/build source changes and bounds retries: passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
