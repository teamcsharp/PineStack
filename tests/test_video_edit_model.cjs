'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const M = require('../desktop/renderer/video-edit-model.js');
const source = {id:'clip1',width:1340,height:800,duration:30,has_audio:true};
test('all rotations round-trip drawing positions through a cropped preview',()=>{
  const crop={x:.2,y:.1,w:.5,h:.7}, points=[{x:.2,y:.1},{x:.7,y:.8},{x:.43,y:.56}];
  for(const rot of [0,90,180,270]) for(const p of points){const q=M.unproject(M.project(p,crop,rot),crop,rot);assert.ok(Math.abs(p.x-q.x)<1e-10);assert.ok(Math.abs(p.y-q.y)<1e-10);}
});
test('clockwise rotation has the same corner orientation as export',()=>{
  assert.deepEqual(M.project({x:0,y:0},M.crop(),90),{x:1,y:0});
  assert.deepEqual(M.project({x:1,y:0},M.crop(),90),{x:1,y:1});
  assert.deepEqual(M.outputSize(source,{crop:{x:0,y:0,w:.5,h:.5},rotation:90}),{width:400,height:670});
});
test('trim cannot cross handles, leave the clip, or mutate the prior edit',()=>{
  const edit=M.create(source), moved=M.trim(edit,'in',99,30);assert.equal(edit.in_s,0);assert.equal(moved.in_s,29.9);
  assert.equal(M.trim(moved,'out',-9,30).out_s,30);assert.equal(M.trim(edit,'out',500,30).out_s,30);
});
test('a shorter-than-minimum recording keeps its whole duration',()=>{
  const edit=M.create({...source,duration:.02});assert.deepEqual(M.trim(edit,'in',1,.02),edit);assert.equal(M.trim(edit,'out',0,.02).out_s,.02);
});
test('crop stays inside the original and retains a nonempty frame',()=>{
  assert.deepEqual(M.crop({x:.9,y:-.3,w:.4,h:.2}),{x:.6,y:0,w:.4,h:.2});
  const c=M.crop({x:3,y:3,w:0,h:0});assert.ok(c.w>0&&c.h>0);assert.ok(c.x+c.w<=1&&c.y+c.h<=1);
});
test('aspect crops yield the requested ratio without exceeding the source',()=>{
  for(const ratio of [1,16/9,9/16]){const c=M.aspectCrop(source,ratio);assert.ok(Math.abs(source.width*c.w/(source.height*c.h)-ratio)<1e-9);assert.ok(c.x>=0&&c.y>=0&&c.x+c.w<=1&&c.y+c.h<=1);}
});
test('silent source cannot acquire an audio stream by checking the box',()=>{
  const edit=M.create(source);edit.include_audio=true;const body=M.exportBody({...source,has_audio:false},edit,'');assert.equal(body.include_audio,false);
});
test('export carries trim, source crop, clockwise rotation, color, and original-space drawing',()=>{
  const edit={...M.create(source),in_s:2,out_s:7,crop:{x:.1,y:.2,w:.6,h:.5},rotation:450,brightness:1.2,contrast:.8,saturation:1.4};
  const body=M.exportBody(source,edit,'data:image/png;base64,TEST');
  assert.equal(body.source_id,'clip1');assert.equal(body.in_s,2);assert.equal(body.out_s,7);assert.deepEqual(body.crop,edit.crop);assert.equal(body.rotation,90);
  assert.equal(body.brightness,1.2);assert.equal(body.contrast,.8);assert.equal(body.saturation,1.4);assert.equal(body.overlay_png,'data:image/png;base64,TEST');assert.equal(edit.rotation,450);
});
test('preview color order matches the export processing contract',()=>{assert.equal(M.filter({brightness:1.2,contrast:.8,saturation:0}),'brightness(1.2) contrast(0.8) saturate(0)');});
test('fit letterboxes rather than stretching the picture',()=>{assert.deepEqual(M.fit(1000,500,1),{x:250,y:0,w:500,h:500});});

test('capture gaps remain visible even when a playable audio track exists',()=>{
  assert.match(M.audioNotice({...source,audio_capture:{state:'partial',complete:false,coverage_ratio:.73}}),/Audio has gaps \(73% captured\)/);
  assert.match(M.audioNotice({...source,audio_capture:{complete:false}}),/Audio has gaps/);
  assert.equal(M.audioNotice({...source,audio_signal:'present',audio_capture:{complete:true}}),'');
});

test('valid silence and explicitly audio-free capture are described accurately',()=>{
  assert.equal(M.audioNotice({...source,audio_signal:'silent'}),'The recorded audio is silent.');
  assert.equal(M.audioNotice({...source,has_audio:false,audio_capture:{video_only_explicit:true}}),'This recording was captured without audio.');
  assert.match(M.audioNotice({...source,has_audio:false}),/No audio was captured/);
});
