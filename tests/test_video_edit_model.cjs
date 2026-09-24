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

test('splice timeline locates source time across independent segments',()=>{
  const clips=[{source_id:'original',in_s:2,out_s:5},{source_id:'generated',in_s:7,out_s:9}];
  assert.equal(M.spliceLength(clips),5);
  assert.deepEqual(M.spliceLocate(clips,0),{index:0,source_id:'original',source_s:2,start_s:0});
  assert.deepEqual(M.spliceLocate(clips,3.5),{index:1,source_id:'generated',source_s:7.5,start_s:3});
  assert.equal(M.spliceLocate(clips,5).source_s,9);
  assert.equal(M.spliceLocate([],0),null);
});

test('splice split, trim, move and delete leave source ranges and prior states intact',()=>{
  const sources={original:{id:'original',duration:10},generated:{id:'generated',duration:12}};
  const first=[M.spliceClip(sources.original,1,6),M.spliceClip(sources.generated,2,8)];
  const split=M.spliceSplit(first,0,3);
  assert.deepEqual(split.slice(0,2),[{source_id:'original',in_s:1,out_s:3},{source_id:'original',in_s:3,out_s:6}]);
  assert.deepEqual(first[0],{source_id:'original',in_s:1,out_s:6});
  assert.deepEqual(M.spliceSplit(split,0,1.05),split);
  const trimmed=M.spliceTrim(split,1,'in',100,sources);
  assert.ok(Math.abs(trimmed[1].out_s-trimmed[1].in_s-.1)<1e-9);
  assert.equal(split[1].in_s,3);
  assert.deepEqual(M.spliceMove(split,2,0).map(c=>c.source_id),['generated','original','original']);
  assert.deepEqual(M.spliceMove(split,0,9),split);
});

test('splice export contains ordered sources and complete editable clip decisions',()=>{
  const sources={original:{id:'original',duration:10},generated:{id:'generated',duration:12}};
  const clips=[M.spliceClip(sources.generated,4,5),M.spliceClip(sources.original,1,2)];
  const body=M.spliceBody(['original','generated'],clips,'  Parody  ','permit',sources);
  assert.deepEqual(body.source_ids,['original','generated']);
  assert.equal(body.name,'Parody');assert.equal(body.save_token,'permit');
  assert.deepEqual(body.clips.map(c=>[c.source_id,c.in_s,c.out_s,c.track,c.start_s]),[
    ['generated',4,5,'base',0],['original',1,2,'base',1]
  ]);
  for(const clip of body.clips){assert.equal(clip.volume,1);assert.equal(clip.transition,'cut');assert.deepEqual(clip.mask,{closed:false,feather:0,invert:false,keyframes:[]});}
  assert.throws(()=>M.spliceBody(['original','generated'],[{source_id:'other',in_s:0,out_s:1}],'x','',sources),/outside/);
  assert.throws(()=>M.spliceBody(['original','generated'],[{source_id:'original',in_s:9,out_s:11}],'x','',sources),/outside/);
  assert.throws(()=>M.spliceBody(['original','original'],clips,'x','',sources),/distinct/);
  assert.throws(()=>M.spliceBody(['original','generated'],Array(41).fill(clips[0]),'x','',sources),/40 segments/);
  const longSources={...sources,original:{id:'original',duration:20}};
  assert.throws(()=>M.spliceBody(['original','generated'],Array(40).fill(M.spliceClip(longSources.original,0,20)),'x','',longSources),/ten minutes/);
});

test('audio split keeps independent named ranges through split, trim and reorder',()=>{
  const audio={id:'sfx-a',duration:12,pine_sfx:{name:'Station sting'}};
  const original=[M.audioSplitCreate(audio)];
  assert.deepEqual(original,[{source_id:'sfx-a',in_s:0,out_s:12,name:'Station sting'}]);
  const split=M.audioSplitAt(original,0,5);
  assert.deepEqual(split,[{source_id:'sfx-a',in_s:0,out_s:5,name:'Station sting'},
    {source_id:'sfx-a',in_s:5,out_s:12,name:'Part 2'}]);
  assert.deepEqual(original,[{source_id:'sfx-a',in_s:0,out_s:12,name:'Station sting'}]);
  assert.deepEqual(M.audioSplitAt(split,1,5.15),split);
  const trimmed=M.audioSplitTrim(split,1,'in',6,audio);
  assert.equal(trimmed[1].name,'Part 2');
  assert.equal(trimmed[1].in_s,6);
  const shortest=M.audioSplitTrim(split,1,'in',99,audio);
  assert.ok(Math.abs(shortest[1].out_s-shortest[1].in_s-.2)<1e-9);
  assert.deepEqual(M.spliceMove(trimmed,1,0).map(c=>c.name),['Part 2','Station sting']);
});

test('audio split export matches the single-source API and validates each piece',()=>{
  const audio={id:'sfx-a',duration:12};
  const clips=[{source_id:'sfx-a',in_s:5,out_s:8,name:'  Tail  '},
    {source_id:'sfx-a',in_s:0,out_s:2,name:'Head'}];
  assert.deepEqual(M.audioSplitBody(audio,clips,true,'permit'),{
    source_id:'sfx-a',clips:[{in_s:5,out_s:8,name:'Tail'},{in_s:0,out_s:2,name:'Head'}],
    keep_original:true,save_token:'permit'
  });
  assert.equal(M.audioSplitBody(audio,clips,false,'').keep_original,false);
  assert.equal(clips[0].name,'  Tail  ');
  assert.throws(()=>M.audioSplitBody(audio,[],true,''),/2 and 20/);
  assert.throws(()=>M.audioSplitBody(audio,[clips[0]],true,''),/2 and 20/);
  assert.throws(()=>M.audioSplitBody(audio,Array(21).fill(clips[0]),true,''),/2 and 20/);
  assert.throws(()=>M.audioSplitBody(audio,[{...clips[0],name:' '},clips[1]],true,''),/Name every/);
  assert.throws(()=>M.audioSplitBody(audio,[{...clips[0],out_s:13},clips[1]],true,''),/outside/);
  assert.throws(()=>M.audioSplitBody(audio,[{...clips[0],source_id:'other'},clips[1]],true,''),/outside/);
  assert.throws(()=>M.audioSplitBody(audio,[{...clips[0],out_s:5.1},clips[1]],true,''),/outside/);
});
