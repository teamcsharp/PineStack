'use strict';
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {PinetabUpdate}=require('../desktop/pinetab-update.cjs');
const {stamp}=require('../desktop/pinetab-stamp.cjs');
(async()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'pinetab-snapshot-test-'));
 function write(file,text){const p=path.join(tmp,'source',file);fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,text);}
 try {
  for(const f of ['build.gradle.kts','settings.gradle.kts','gradle.properties','deploy.sh','app/build.gradle.kts','app/proguard-rules.pro','gradle/libs.versions.toml','tools/pinetab-stamp.sh','tools/kiosk-preflight.sh'])write(f,'build input');
  write('app/src/main/AndroidManifest.xml','manifest');
  write('app/src/main/assets/pine-views/sfx-tv.js','old view');
  write('app/src/main/assets/pine-sampler/sfx-tv.js','old sampler');
  write('desktop/renderer/sfx-tv.js','canonical latest view');
  write('app/build/outputs/apk/debug/app-debug.apk','old build output');
  const pu=new PinetabUpdate({agentRoot:()=>path.join(tmp,'source')});
  const wanted=stamp(path.join(tmp,'source')).stamp;
  const result=await pu.snapshotSource(path.join(tmp,'snapshot'));
  assert.equal(result.stamp,wanted,'snapshot represents exactly the source after canonical asset sync');
  assert.equal(fs.readFileSync(path.join(result.root,'desktop/renderer/sfx-tv.js'),'utf8'),'canonical latest view');
  assert.ok(!fs.existsSync(path.join(result.root,'app/build')),'snapshot does not share generated outputs or locks');
  write('app/src/main/AndroidManifest.xml','edited after copying');
  assert.notEqual(stamp(path.join(tmp,'source')).stamp,result.stamp);
  assert.equal(fs.readFileSync(path.join(result.root,'app/src/main/AndroidManifest.xml'),'utf8'),'manifest','queued build snapshot stays fixed');
  console.log('PineTab isolated source snapshot: passed');
 }finally{assert.ok(tmp.startsWith(path.join(os.tmpdir(),'pinetab-snapshot-test-')));fs.rmSync(tmp,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
