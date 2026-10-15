"use strict";
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const clipMux = require('../desktop/clip-mux.cjs');
const { ScreenRing, HOLD_MAX_BYTES } = require('../desktop/screen-ring.cjs');

test('real oversized Chromium frames export at PiP geometry with their captured sound', {skip:!clipMux.findFfmpeg().found}, async()=>{
  const folder=clipMux.stash(), ring=new ScreenRing(), tool=clipMux.findFfmpeg().path;
  let made;
  try {
    const video=path.join(folder,'picture.webm'), audio=path.join(folder,'audio.webm');
    await clipMux.run(tool,['-v','error','-nostdin','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=30',
      '-t','2','-c:v','libvpx','-deadline','realtime',video]);
    await clipMux.run(tool,['-v','error','-nostdin','-y','-f','lavfi','-i','sine=frequency=1000:sample_rate=48000',
      '-t','2','-c:a','libopus',audio]);
    const at=Date.now()-2000;
    ring.take(fs.readFileSync(video),{at,ms:2000,w:320,h:180,fps:30,view:'pip'});
    ring.take(fs.readFileSync(audio),{at,ms:2000,kind:'a',a:true,audio_complete:true});
    made=await ring.cut({seconds:2,view:'pip',end_at:at+2000},{encoder:'cpu',onProgress:()=>{}});
    assert.equal(made.ok,true,made.detail); assert.equal(made.seconds,2);
    assert.equal(made.audio.present,true); assert.equal(made.w,320); assert.equal(made.h,180);
    const decoded=await clipMux.run(tool,['-hide_banner','-nostdin','-i',made.out,'-f','null','-']);
    assert.match(decoded,/Video: h264.*320x180/); assert.match(decoded,/Audio: aac/);
  } finally {if(made?.dir)clipMux.forget(made.dir);ring.forget();clipMux.forget(folder);}
});

function seeded({ sizes = [[321,181],[321,183],[321,181]], audioShift = 120 } = {}) {
  const ring = new ScreenRing();
  const at = Date.now() - sizes.length * 2000;
  for (let i = 0; i < sizes.length; i++) {
    ring.take(Buffer.from('video'), { at: at+i*2000, ms:2000, w:sizes[i][0], h:sizes[i][1], fps:60, view:'pip' });
    ring.take(Buffer.from('audio'), { at: at+i*2000+audioShift, ms:2000, a:true, kind:'a' });
  }
  return ring;
}
async function capture(ring, want, during) {
  const old = clipMux.encodeVideo;
  let args;
  clipMux.encodeVideo = async (bin, build) => {
    args = build('libx264');
    if (during) await during(args);
    fs.writeFileSync(args.at(-1), 'encoded');
    return { encoder:'libx264', hardware:false, fallback_detail:'' };
  };
  try { return { made:await ring.cut(want), args }; }
  finally { clipMux.encodeVideo = old; }
}

test('resizing PinePiP preserves the entire run and every native source pixel', async () => {
  const ring = seeded();
  let made;
  try {
    const result = await capture(ring, { seconds:6, view:'pip' }); made=result.made;
    assert.equal(made.ok,true, made.detail);
    assert.equal(made.seconds,6);
    assert.equal(made.w,322); assert.equal(made.h,184);
    assert.equal(made.video.pixel_scale,1); assert.equal(made.video.fps,60);
    const graph=result.args[result.args.indexOf('-filter_complex')+1];
    assert.match(graph,/concat=n=3:v=1:a=0/);
    assert.equal((graph.match(/pad=322:184:0:0/g)||[]).length,3);
    assert.match(graph,/scale=w='min\(iw,321\)'/);
    assert.doesNotMatch(graph,/minterpolate|hqdn3d/);
    assert.equal(result.args[result.args.indexOf('-r')+1],'60');
  } finally { if(made?.dir)clipMux.forget(made.dir); ring.forget(); }
});

test('audio and video select one absolute interval and retain timestamp offsets', async () => {
  const ring=seeded({sizes:[[320,180],[320,180],[320,180]],audioShift:120});
  let made;
  try {
    const shot=ring.window(3.25,1,'video','pip');
    const audio=ring.window(shot.seconds,0,'sound',undefined,shot);
    assert.equal(audio.clock,shot.clock);
    assert.equal(audio.end,shot.end);
    const result=await capture(ring,{seconds:3.25,back:1,view:'pip'});made=result.made;
    assert.equal(made.ok,true,made.detail);
    const graph=result.args[result.args.indexOf('-filter_complex')+1];
    const videoSeek=Number(graph.match(/trim=start=([\d.]+)/)[1]);
    const audioShift=Number(graph.match(/\[1:a\]asetpts=PTS-\(([\d.]+)\)\/TB/)[1]);
    assert.ok(Math.abs(videoSeek-audioShift-0.12)<1e-6);
    assert.doesNotMatch(graph,/\[1:a\].*PTS-STARTPTS/);
    assert.match(graph,/aresample=48000:async=1:min_hard_comp=0\.001:first_pts=0/);
    const lists=result.args.filter(value=>value.endsWith('.txt'));
    for(const list of lists) assert.match(fs.readFileSync(list,'utf8'),/inpoint 0/);
  } finally {if(made?.dir)clipMux.forget(made.dir);ring.forget();}
});

test('a missing leading picture file clamps the absolute start instead of shifting audio', async () => {
  const ring=seeded({sizes:[[320,180],[320,180],[320,180]],audioShift:0});
  fs.unlinkSync(ring.pieces[0].file);
  let made;
  try {
    const result=await capture(ring,{seconds:6,view:'pip'});made=result.made;
    assert.equal(made.ok,true,made.detail);assert.equal(made.clamped,true);assert.equal(made.seconds,4);
    const graph=result.args[result.args.indexOf('-filter_complex')+1];
    assert.match(graph,/\[1:a\]asetpts=PTS-\(2\.000000\)\/TB/);
  } finally {if(made?.dir)clipMux.forget(made.dir);ring.forget();}
});

test('forget during export defers deleting both pinned lanes until the reader finishes', async () => {
  const ring=seeded(); const files=[...ring.pieces,...ring.sound].map(piece=>piece.file);
  const ringDir=ring.dir, cachedBytes=ring.bytes();let made;
  try {
    const result=await capture(ring,{seconds:6,view:'pip'},async ()=>{
      ring.forget();
      assert.equal(ring.pieces.length,0);assert.equal(ring.sound.length,0);
      assert.equal(ring.state().bytes,0);
      assert.equal(ring.state().pinned_retired_bytes,cachedBytes);
      assert.equal(ring.state().disk_bytes,cachedBytes);
      for(const file of files)assert.equal(fs.existsSync(file),true,'pinned '+file);
      ring.begin();assert.notEqual(ring.dir,ringDir,'a resumed cache has a new directory');
    });made=result.made;
    assert.equal(made.ok,true,made.detail);
    for(const file of files)assert.equal(fs.existsSync(file),false);
    assert.equal(fs.existsSync(ringDir),false);
    assert.equal(ring.pins.size,0);
    assert.equal(ring.state().pinned_retired_bytes,0);
    assert.equal(ring.state().disk_bytes,ring.state().bytes);
  } finally {if(made?.dir)clipMux.forget(made.dir);ring.forget();}
});

test('the rolling byte ceiling counts audio and video and evicts the oldest lane',()=>{
  const ring=seeded({audioShift:120});
  try {
    const firstVideo=ring.pieces[0].file;
    ring.pieces[0].bytes=HOLD_MAX_BYTES-100;
    ring.sound[0].bytes=200;
    assert.ok(ring.bytes()>HOLD_MAX_BYTES);
    assert.equal(ring.state().byte_limit,4*1024*1024*1024);
    assert.equal(ring.bytes(),ring.state().video_bytes+ring.state().audio_bytes);
    ring.prune();
    assert.ok(ring.bytes()<=HOLD_MAX_BYTES);
    assert.equal(fs.existsSync(firstVideo),false);
  }finally{ring.forget();}
});

test('same-clock pieces and export snapshots never overwrite one another',()=>{
  const ring=new ScreenRing(); const dirs=[];
  try{
    const at=Date.now()-2000;
    ring.take(Buffer.from('one'),{at,ms:1000,w:320,h:180});
    ring.take(Buffer.from('two'),{at,ms:1000,w:320,h:180});
    assert.notEqual(ring.pieces[0].file,ring.pieces[1].file);
    assert.equal(fs.readFileSync(ring.pieces[0].file,'utf8'),'one');
    for(let i=0;i<25;i++)dirs.push(clipMux.stash());
    assert.equal(new Set(dirs).size,dirs.length);
  }finally{dirs.forEach(clipMux.forget);ring.forget();}
});


test('partial application audio remains playable but cannot claim full capture',async()=>{
  const ring=seeded({audioShift:0});let made;
  try{
    ring.noteAudio({source:'desk-application-audio',present:true,complete:false,detail:'Panel audio only; shell audio is missing.'});
    ring.sound.forEach(piece=>piece.audio_complete=false);
    const result=await capture(ring,{seconds:6,view:'pip'});made=result.made;
    assert.equal(made.ok,true,made.detail);assert.equal(made.audio.present,true);
    assert.equal(made.audio.complete,false);assert.equal(made.audio.state,'partial');
    assert.equal(made.audio.application_audio_complete,false);
    assert.equal(made.audio.source,'desk-application-audio');
    assert.match(made.audio.detail,/shell audio/);
    assert.ok(result.args.includes('[pinesound]'));
    assert.equal(result.args.includes('-an'),false);
  }finally{if(made?.dir)clipMux.forget(made.dir);ring.forget();}
});


test('codec changes get independent decoder inputs even when dimensions stay the same',async()=>{
  const ring=seeded({sizes:[[320,180],[320,180],[320,180]],audioShift:0});let made;
  ring.pieces[0].mime='video/webm;codecs=vp8';
  ring.pieces[1].mime=ring.pieces[2].mime='video/webm;codecs=h264';
  try{
    const result=await capture(ring,{seconds:6,view:'pip'});made=result.made;
    assert.equal(made.ok,true,made.detail);
    const graph=result.args[result.args.indexOf('-filter_complex')+1];
    assert.match(graph,/concat=n=2:v=1:a=0/);
  }finally{if(made?.dir)clipMux.forget(made.dir);ring.forget();}
});

test('many resize runs use a graph file instead of exceeding the Windows argument limit',async()=>{
  const ring=new ScreenRing(); ring.holdSeconds=3600;let made;
  const at=Date.now()-60000;
  for(let i=0;i<30;i++)ring.take(Buffer.from('video'),{at:at+i*2000,ms:2000,w:320,h:180+i%2,view:'pip',fps:60});
  try{
    const result=await capture(ring,{seconds:60,view:'pip',video_only:true});made=result.made;
    assert.equal(made.ok,true,made.detail);
    assert.ok(result.args.includes('-filter_complex_script'));
    const file=result.args[result.args.indexOf('-filter_complex_script')+1];
    assert.match(fs.readFileSync(file,'utf8'),/concat=n=30:v=1:a=0/);
    assert.ok(result.args.join(' ').length<10000);
  }finally{if(made?.dir)clipMux.forget(made.dir);ring.forget();}
});


test('a current capture failure does not invalidate complete audio already buffered',async()=>{
  const ring=seeded({audioShift:0});let made;
  try{
    assert.ok(ring.sound.every(piece=>piece.audio_complete===true));
    ring.noteAudio({source:'desk-application-audio',present:false,complete:false,state:'unavailable',detail:'The current capture was disconnected.'});
    const result=await capture(ring,{seconds:6,view:'pip'});made=result.made;
    assert.equal(made.ok,true,made.detail);assert.equal(made.audio.present,true);
    assert.equal(made.audio.complete,true);assert.equal(made.audio.state,'captured');
  }finally{if(made?.dir)clipMux.forget(made.dir);ring.forget();}
});
