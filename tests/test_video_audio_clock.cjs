const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/sfx-tv.js'), 'utf8');
function fn(text, name) {
  const start = text.indexOf('function ' + name + '(');
  assert.ok(start >= 0, name);
  let i = text.indexOf('{', start), depth = 0;
  for (; i < text.length; i++) {
    if (text[i] === '{') depth++;
    if (text[i] === '}' && --depth === 0) return text.slice(start, i + 1);
  }
  throw Error(name);
}
function clock(audio = [], pending = [], bridge = null) {
  const env = {document: {querySelectorAll: () => audio}, djVoiceQueue: pending,
    root: {pinePlayhead: () => bridge}, now: () => 10000, AVSYNC_PREROLL_MS: 1100,
    LATE: 8, SILENT_TAIL: 0.6};
  vm.createContext(env);
  vm.runInContext(['soundClock','airInto','missed'].map(n => fn(source,n)).join('\n'), env);
  return env;
}
const cue = {line: 'picture', silent_picture: true, at: 1000, seconds: 5};
test('a late audio start places the picture on its actual audible cue', () => {
  const c = clock([{paused:false, ended:false, currentTime:12,
    pineDeliveryClip:{stream:{rows:[{id:'picture',from:10}]}}}]);
  assert.equal(c.airInto(cue), 2);
  assert.equal(c.missed(cue), false, 'old reservation must not discard audible video');
});
test('desktop bridge interpolates only a fresh audio playhead', () => {
  const c = clock([], [], {at:9750,t:12,rows:[{id:'picture',from:10}]});
  assert.equal(c.airInto(cue), 2.25);
});
test('queued audio keeps its picture warm even after the reservation expires', () => {
  const c = clock([], [{stream:{rows:[{id:'picture',from:10}]}}]);
  assert.equal(c.soundClock(cue).pending, true);
  assert.equal(c.missed(cue), false);
  assert.equal(c.airInto(cue), 0);
});
test('a short picture still has a playback window', () => {
  const c=clock([{paused:false,currentTime:.1,pineDeliveryClip:{stream:{rows:[{id:'picture',from:0}]}}}]);
  assert.equal(c.missed({...cue,seconds:.54}),false);
});
test('unrelated or paused audio leaves station video timing intact', () => {
  const c = clock([{paused:true,currentTime:12,pineDeliveryClip:{stream:{rows:[{id:'picture',from:10}]}}}]);
  assert.equal(c.soundClock(cue), null);
  assert.equal(c.missed(cue), true);
  assert.equal(c.soundClock({...cue,silent_picture:false}), null);
});

test('a seek-induced playing event cannot restart initial sound synchronization', () => {
  const start = source.indexOf('var firstSoundSync = false;');
  const end = source.indexOf('/* AND IT IS HELD THERE.', start);
  assert.ok(start >= 0 && end > start);
  let seeks = 0, position = 0, playing;
  const screen = {duration: 20, addEventListener: (_, cb) => { playing = cb; },
    get currentTime() { return position; },
    set currentTime(v) { position = v; seeks++; }};
  const env = {screen, video:screen, clip:cue, done:false, JOIN_TAIL:0.6,
    airInto:()=>5};
  vm.createContext(env); vm.runInContext(source.slice(start,end),env);
  playing(); assert.equal(seeks,1);
  position=4; playing(); assert.equal(seeks,1,'seek completion must let decoder settle');
});
test('preloading never replaces an audio element that is still sounding', () => {
  const app = fs.readFileSync(path.join(__dirname,'../app.py'),'utf8');
  let loads=0, src='old';
  const audio={paused:false,ended:false,dataset:{},getAttribute:()=>src,load:()=>loads++,set src(v){src=v}};
  const env={djVoiceQueue:[{url:'/next',stream:{rows:[{id:'next-cue',from:3}]}}],
    djVoiceSlot:1,djVoiceEl:()=>audio,djClipUrl:u=>u};
  vm.createContext(env); vm.runInContext(fn(app,'djVoiceWarm'),env);
  env.djVoiceWarm(); assert.equal(src,'old'); assert.equal(loads,0);
  audio.paused=true; env.djVoiceWarm(); assert.equal(src,'/next'); assert.equal(loads,1);
  env.djVoiceWarm(); assert.equal(loads,1,'ready source must be reused');
});

test('the next picture decodes muted in place and promotion is never paused', async () => {
  for (const promoted of [false, true]) {
    let parked=false, paused=0, resolve;
    const el={load(){},pause(){paused++},play(){
      assert.equal(this.muted,true);assert.ok(parked);
      return new Promise(r=>{resolve=r});}};
    const env={mounted:true,warm:null,nativeCueCapable:false,document:{createElement:()=>el},
      warmDrop(){},heldSrc:()=>'/clip',levelSet(){},level:1,warmPark(){parked=true}};
    vm.createContext(env);vm.runInContext(fn(source,'warmElement'),env);
    env.warmElement({url:'/clip'});
    if(promoted)env.warm=null;
    resolve();await new Promise(r=>setImmediate(r));
    assert.equal(paused,promoted?0:1);
  }
});
