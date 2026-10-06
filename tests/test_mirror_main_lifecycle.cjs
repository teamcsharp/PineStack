/* Exercise shipped main-process mirror wiring without Electron, ADB or hardware. */
'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {EventEmitter} = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {MirrorLifecycle} = require('../desktop/mirror-lifecycle.cjs');
const main = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const turn = () => new Promise(resolve => setImmediate(resolve));
const piece = (start, end) => main.slice(main.indexOf(start), main.indexOf(end, main.indexOf(start)));

function fixture({loadFile} = {}) {
  const mirrors = [], windows = [], commands = [], writes = [];
  const config = {baseUrl:'http://station'};
  const discovery = deferred(), vitals = deferred();
  let serialReads = 0;
  class FakeMirror {
    constructor({serial, encoderOwner}) {
      this.encoderOwner = encoderOwner;
      this.serial = serial; this.real = {width:1340,height:800};
      this.running = false; this.paused = false; this.pauses = 0; this.resumes = 0;
      this.closes = 0; this.rebuilt = []; this.measurement = deferred(); this.clean = deferred();
      mirrors.push(this);
    }
    measure(run) { this.measureRun = run; return this.measurement.promise; }
    pause() { this.pauses++; this.paused = true; return Promise.resolve(); }
    resume() { this.resumes++; this.paused = false; }
    closeGently() { this.closes++; return this.clean.promise; }
    close() { this.closed = true; }
    rebuild(why) { this.rebuilt.push(why); }
    how() { return {paused:this.paused}; }
  }
  class FakeWindow extends EventEmitter {
    constructor(options) { super(); this.webContents = new EventEmitter(); this.webContents.isDestroyed=()=>this.destroyed;
      this.webContents.reload=()=>Promise.resolve(this.loadFile()).then(()=>this.webContents.emit('did-finish-load'),error=>this.webContents.emit('did-fail-load',null,-2,error.message,'',true)); this.options = options; this.destroyed = false;
      this.visible = true; this.minimized = false; this.focuses = 0; windows.push(this); }
    isDestroyed() { return this.destroyed; }
    isMinimized() { return this.minimized; }
    isVisible() { return this.visible; }
    isFullScreen() { return false; }
    restore() { this.minimized=false; this.emit('restore'); }
    focus() { this.focuses++; }
    setFullScreen() {}
    setMenuBarVisibility() {}
    setAspectRatio() {}
    getSize() { return [670,434]; }
    getContentSize() { return [670,434]; }
    getBounds() { return {width:670,height:434}; }
    setBounds() {}
    loadFile() { this.loaded = true; return loadFile ? loadFile(this) : Promise.resolve(); }
    destroy() { this.shut(); }
    shut() { this.emit('close'); this.destroyed = true; this.emit('closed'); }
  }
  const ctx = {
    mirror:null, mirrorWindow:null, poke:null, mirrorLifecycle:new MirrorLifecycle(),
    path, __dirname:path.join(__dirname,'../desktop'), BrowserWindow:FakeWindow,
    MIRROR_STRIP:34, AbortSignal, setTimeout, clearTimeout,
    terminalHost:{tools:()=>({adb:'adb'}), glassSerial:()=>{serialReads++;return discovery.promise;}},
    readConfig:()=>config, writeConfig:cfg=>{ writes.push(cfg); Object.assign(config,cfg); },
    clipMux:{findFfmpeg:()=>({path:'ffmpeg'})},
    fetchJson:()=>Promise.resolve({}), execFile:(file,args,options,done)=>{commands.push(args);done(null,'','');},
    tabletVitals:()=>vitals.promise, vitals:null,
    mirrorOpenBounds:()=>({width:670,height:434}), mirrorAspectBounds:()=>null,
    desktopFaults:{record(){return Promise.resolve(true);}},
    require:name=>{
      if (name==='./tablet-mirror.cjs') return {Mirror:FakeMirror};
      if (name==='./mirror-view-reload.cjs') return {reloadMirrorView:contents=>require('../desktop/mirror-view-reload.cjs').reloadMirrorView(contents,{delayMs:0,timeoutMs:1000})};
      if (name==='electron') return {screen:{}};
      if (name==='node:crypto') return require('node:crypto');
      throw new Error('unexpected require '+name);
    }
  };
  vm.createContext(ctx);
  vm.runInContext(piece('function mirrorEncoderOwner()', '// Cancel delayed discovery'),ctx);
  vm.runInContext(piece('function openTabletMirror(options)', '/* TOUCHING THE TABLET THROUGH THE PICTURE.'),ctx);
  return {ctx,mirrors,windows,commands,writes,config,discovery,vitals,serialReads:()=>serialReads};
}

test('parallel opens share discovery and create only one mirror/window', async () => {
  const f=fixture();
  const first=f.ctx.openTabletMirror({}), second=f.ctx.openTabletMirror({});
  assert.equal(first,second);
  await turn();
  assert.equal(f.serialReads(),1);
  f.discovery.resolve('tabletUSB');
  const result=await first;
  assert.equal(result.ok,true);
  assert.equal(f.mirrors.length,1); assert.equal(f.windows.length,1);
  assert.equal(f.windows[0].loaded,true);
  // Both diagnostics remain unresolved; opening is already complete and visible.
  assert.equal(f.mirrors[0].measurement.promise instanceof Promise,true);
  await f.ctx.openTabletMirror({});
  assert.equal(f.windows[0].focuses,1);
});

test('replacement waits for old remote cleanup; old callbacks cannot close new stream', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB');
  await f.ctx.openTabletMirror({});
  const old=f.mirrors[0], oldWindow=f.windows[0];
  oldWindow.shut();
  const next=f.ctx.openTabletMirror({});
  await turn();
  assert.equal(f.mirrors.length,1); assert.equal(old.closes,1);
  old.clean.resolve(); await next;
  const current=f.mirrors[1];
  oldWindow.emit('hide'); oldWindow.emit('closed');
  await turn();
  assert.equal(current.pauses,0); assert.equal(current.closes,0);
  assert.equal(old.closes,1);
  assert.equal(f.ctx.mirror,current);
});

test('shutdown cancels deferred discovery without creating window, shell or encoder', async () => {
  const f=fixture(); const pending=f.ctx.openTabletMirror({});
  await turn(); f.ctx.mirrorLifecycle.stop();
  f.discovery.resolve('10.0.0.1:5555');
  const result=await pending;
  assert.equal(result.cancelled,true);
  assert.equal(f.mirrors.length,0); assert.equal(f.windows.length,0);
  assert.equal(f.commands.length,0); assert.equal(f.writes.length,0);
});

test('closed view cancels delayed measurement and never rebuilds its pipe', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB');
  await f.ctx.openTabletMirror({});
  const old=f.mirrors[0]; old.running=true;
  f.windows[0].shut();
  old.real={width:800,height:1340};
  old.measurement.resolve();
  await turn();
  await old.measureRun(['shell','dumpsys display']);
  assert.deepEqual(old.rebuilt,[]); assert.equal(f.commands.length,0);
  old.clean.resolve();
});

test('minimize/restore controls the captured instance and only resumes visible views', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB');
  await f.ctx.openTabletMirror({});
  const mirror=f.mirrors[0], window=f.windows[0];
  window.minimized=true; window.emit('minimize');
  window.emit('show'); assert.equal(mirror.resumes,0);
  window.minimized=false; window.emit('restore');
  assert.equal(mirror.pauses,1); assert.equal(mirror.resumes,1);
});

test('quality answer for an older mirror cannot retune a replacement', async () => {
  const answer=deferred(); const before={running:true,paused:false,requality:()=>{throw Error('old retune');}};
  let changed=0; const after={running:true,paused:false,requality:()=>changed++};
  const ctx={mirror:before,mirrorQualityAsking:false,mirrorQualitySeen:'',MIRROR_QUALITY_ASK:'quality',
    terminalHost:{glass:async()=>({say:()=>answer.promise})}};
  vm.createContext(ctx);
  vm.runInContext(piece('async function mirrorQualityFromTablet()', 'function mirrorQualityWatch()'),ctx);
  const pending=ctx.mirrorQualityFromTablet(); await turn(); ctx.mirror=after;
  answer.resolve({ok:true,at:'tablet-new',q:0.8}); await pending;
  assert.equal(changed,0); assert.equal(ctx.mirrorQualitySeen,'');
  assert.equal(ctx.mirrorQualityAsking,false);
});

test('vitals cache and concurrent callers include discovery in their shared flight', async () => {
  const discovery=deferred(), sample=deferred(); let discoveries=0, sweeps=0;
  class Vitals { constructor({serial}){this.serial=serial;} read(){sweeps++;return sample.promise;} }
  const ctx={vitals:null,vitalsAt:0,vitalsHeld:null,vitalsGoing:null,VITALS_HOLD:2500,
    Date,terminalHost:{glassSerial:()=>{discoveries++;return discovery.promise;},tools:()=>({adb:'adb'})},
    require:()=>({Vitals})};
  vm.createContext(ctx);
  vm.runInContext(piece('function tabletVitals(serialHint', 'ipcMain.handle("tablet:vitals"'),ctx);
  const first=ctx.tabletVitals(), second=ctx.tabletVitals();
  assert.equal(first,second); assert.equal(discoveries,1);
  discovery.resolve('tabletUSB'); await turn(); assert.equal(sweeps,1);
  sample.resolve({ok:true}); await first;
  await ctx.tabletVitals();
  assert.equal(discoveries,1); assert.equal(sweeps,1);
});

test('closing a lease twice shares cleanup and future opens wait for it', async () => {
  const life=new MirrorLifecycle(), stop=deferred(); let cleanup=0, created=0;
  await life.open(async()=>{created++;return {ok:true};});
  const lease=life.current;
  const first=life.close(lease,()=>{cleanup++;return stop.promise;});
  assert.equal(life.close(lease,()=>{throw Error('double cleanup');}),first);
  const next=life.open(async()=>{created++;return {ok:true};});
  await turn(); assert.equal(created,1); assert.equal(cleanup,1);
  assert.equal(life.cleaning.has(lease),true);
  stop.resolve(); await next;
  assert.equal(created,2); assert.equal(life.cleaning.size,0);
});


test('persisted desktop encoder owner survives replacement without changing audio preferences', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB');
  Object.assign(f.config,{appVolume:0.34,windowsVolume:0.06});
  await f.ctx.openTabletMirror({});
  const owner=f.mirrors[0].encoderOwner;
  assert.match(owner,/^mirror_[a-f0-9]{32}$/);
  assert.equal(f.config.mirrorEncoderOwner,owner);
  f.windows[0].shut(); f.mirrors[0].clean.resolve();
  await f.ctx.openTabletMirror({});
  assert.equal(f.mirrors[1].encoderOwner,owner);
  assert.equal(f.writes.filter(cfg=>'mirrorEncoderOwner' in cfg).length,1);
  assert.equal(f.config.appVolume,0.34); assert.equal(f.config.windowsVolume,0.06);
  const next=fixture(); next.config.mirrorEncoderOwner=owner;
  next.discovery.resolve('tabletUSB'); await next.ctx.openTabletMirror({});
  assert.equal(next.mirrors[0].encoderOwner,owner);
  assert.equal(next.writes.filter(cfg=>'mirrorEncoderOwner' in cfg).length,0);
});

test('invalid stored owner is replaced before starting a mirror', async () => {
  const f=fixture(); f.config.mirrorEncoderOwner='bad owner; shell';
  f.discovery.resolve('tabletUSB'); await f.ctx.openTabletMirror({});
  assert.match(f.mirrors[0].encoderOwner,/^mirror_[a-f0-9]{32}$/);
  assert.equal(f.config.mirrorEncoderOwner,f.mirrors[0].encoderOwner);
});

function reviveFixture(f,{relaunchFailure=false}={}) {
  const calls=[],handlers=new Map();
  Object.assign(f.ctx,{
    app:{on(){},relaunch(){calls.push('relaunch');if(relaunchFailure)throw Error('spawn refused');},
      releaseSingleInstanceLock(){calls.push('unlock');},exit(){calls.push('exit');},quit(){calls.push('quit');}},
    ipcMain:{handle(name,handler){handlers.set(name,handler);}},
    console:{log(){}},Date,
  });
  vm.runInContext(piece('let mirrorQuitReady = false;', '/* [mirror-pip] THE WINDOW IS THE ZOOM.'),f.ctx);
  vm.runInContext(piece('const REVIVE_REST_MS', '/* ---------------------------------------------------------------------- */\n/* #1183: THE MPC'),f.ctx);
  return {calls,revive:opts=>handlers.get('app:revive')(null,opts)};
}

test('revival waits for mirror shutdown before releasing the lock and exiting', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB'); await f.ctx.openTabletMirror({});
  const r=reviveFixture(f),reviving=r.revive({now:true,why:'test'});
  await turn();
  assert.deepEqual(r.calls,['relaunch']); assert.equal(f.mirrors[0].closes,1);
  assert.equal(f.ctx.mirrorLifecycle.stopped,true);
  f.mirrors[0].clean.resolve(); await reviving;
  assert.deepEqual(r.calls,['relaunch','unlock','exit']);
  assert.equal(f.mirrors[0].closed,true);
});

test('revival waits for an already closing mirror even when no current lease remains', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB'); await f.ctx.openTabletMirror({});
  f.windows[0].shut();
  const r=reviveFixture(f),reviving=r.revive({now:true,why:'test'});
  await turn(); assert.deepEqual(r.calls,['relaunch']);
  f.mirrors[0].clean.resolve(); await reviving;
  assert.deepEqual(r.calls,['relaunch','unlock','exit']);
});

test('revival cancellation prevents delayed discovery from spawning another mirror', async () => {
  const f=fixture(),opening=f.ctx.openTabletMirror({}); await turn();
  const r=reviveFixture(f); await r.revive({now:true,why:'test'});
  f.discovery.resolve('tabletUSB'); assert.equal((await opening).cancelled,true);
  assert.equal(f.mirrors.length,0); assert.equal(f.commands.length,0);
});

test('failed relaunch and status requests preserve the current mirror and app lock', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB'); await f.ctx.openTabletMirror({});
  const r=reviveFixture(f,{relaunchFailure:true});
  assert.equal((await r.revive()).ok,true); assert.deepEqual(r.calls,[]);
  assert.equal((await r.revive({now:true})).ok,false);
  assert.deepEqual(r.calls,['relaunch']); assert.equal(f.mirrors[0].closes,0);
  assert.equal(f.ctx.mirrorLifecycle.stopped,false);
});

test('a forced exit remains bounded if remote mirror cleanup cannot settle', async () => {
  const f=fixture(); f.discovery.resolve('tabletUSB'); await f.ctx.openTabletMirror({});
  reviveFixture(f);
  await f.ctx.prepareTabletMirrorExit(15);
  assert.equal(f.mirrors[0].closes,1); assert.equal(f.mirrors[0].closed,true);
  assert.equal(f.ctx.mirrorLifecycle.stopped,true);
  f.mirrors[0].clean.resolve(); await turn();
});

test('failed mirror-page load cleans the old lease before retry instead of escaping to a main error dialog', async () => {
  let loads=0;
  const f=fixture({loadFile:()=>{if(++loads!==1)return Promise.resolve();const p=Promise.reject(Error('ERR_FILE_NOT_FOUND'));p.catch(()=>{});return p;}});
  f.discovery.resolve('tabletUSB');
  const opening=f.ctx.openTabletMirror({});
  await turn();
  assert.equal(f.mirrors[0].closes,1);
  f.mirrors[0].clean.resolve();
  const answer=await opening;
  assert.equal(answer.ok,false);
  assert.match(answer.why,/ERR_FILE_NOT_FOUND/);
  assert.equal(f.windows[0].destroyed,true);
  assert.equal(f.ctx.mirror,null);
  assert.equal(f.ctx.mirrorWindow,null);
  assert.equal(f.ctx.mirrorLifecycle.current,null);
  assert.equal((await f.ctx.openTabletMirror({})).ok,true);
  assert.equal(f.mirrors.length,2);
});
test('closing the mirror while its page loads cancels the open result and late diagnostics', async () => {
  const loading=deferred();
  const f=fixture({loadFile:()=>loading.promise});
  f.discovery.resolve('tabletUSB');
  const opening=f.ctx.openTabletMirror({});
  await turn();
  f.windows[0].shut();
  loading.resolve();
  const answer=await opening;
  assert.equal(answer.ok,false);
  assert.equal(answer.cancelled,true);
  assert.equal(f.mirrors[0].measureRun,undefined);
  f.mirrors[0].clean.resolve();
  await f.ctx.mirrorLifecycle.closing;
});

test('a crashed tablet renderer reloads the existing view without restarting capture', async () => {
  let loads=0;const f=fixture({loadFile:()=>{loads++;return Promise.resolve();}});
  f.discovery.resolve('tabletUSB');await f.ctx.openTabletMirror({});
  const instance=f.mirrors[0],window=f.windows[0];instance.running=true;
  window.webContents.emit('render-process-gone',null,{reason:'crashed',exitCode:9});
  await new Promise(r=>setTimeout(r,25));
  assert.equal(loads,2);assert.equal(f.mirrors.length,1);
  assert.equal(instance.closes,0);assert.equal(instance.pauses,0);
  assert.equal(f.ctx.mirror,instance);
});
test('renderer recovery is single-flight and repeated crashes stop after two retries', async () => {
  let loads=0;const pending=deferred();
  const f=fixture({loadFile:()=>++loads===2?pending.promise:Promise.resolve()});
  f.discovery.resolve('tabletUSB');await f.ctx.openTabletMirror({});
  const window=f.windows[0],gone=()=>window.webContents.emit('render-process-gone',null,{reason:'crashed',exitCode:9});
  gone();gone();await new Promise(r=>setTimeout(r,25));assert.equal(loads,2);
  pending.resolve();await new Promise(r=>setTimeout(r,25));gone();await new Promise(r=>setTimeout(r,25));assert.equal(loads,3);
  gone();await new Promise(r=>setTimeout(r,25));assert.equal(loads,3);assert.equal(window.destroyed,true);
  assert.equal(f.mirrors[0].closes,1);f.mirrors[0].clean.resolve();await f.ctx.mirrorLifecycle.closing;
});
test('a failed crashed-view reload cleans its capture before a fresh mirror can open', async () => {
  let loads=0;const f=fixture({loadFile:()=>{if(++loads!==2&&loads!==3)return Promise.resolve();const p=Promise.reject(Error('ERR_FAILED'));p.catch(()=>{});return p;}});
  f.discovery.resolve('tabletUSB');await f.ctx.openTabletMirror({});
  f.windows[0].webContents.emit('render-process-gone',null,{reason:'crashed',exitCode:9});
  await new Promise(r=>setTimeout(r,25));assert.equal(f.mirrors[0].closes,1);
  const replacement=f.ctx.openTabletMirror({});await new Promise(r=>setTimeout(r,25));assert.equal(f.mirrors.length,1);
  f.mirrors[0].clean.resolve();assert.equal((await replacement).ok,true);await new Promise(r=>setTimeout(r,25));
  assert.equal(f.windows[0].destroyed,true);assert.equal(f.mirrors.length,2);
});
test('closing during a crashed-view reload prevents late recovery from opening another window', async () => {
  let loads=0;const pending=deferred();
  const f=fixture({loadFile:()=>++loads===2?pending.promise:Promise.resolve()});
  f.discovery.resolve('tabletUSB');await f.ctx.openTabletMirror({});
  const window=f.windows[0];window.webContents.emit('render-process-gone',null,{reason:'crashed',exitCode:9});
  await new Promise(r=>setTimeout(r,25));window.shut();pending.resolve();await new Promise(r=>setTimeout(r,25));
  assert.equal(f.mirrors.length,1);assert.equal(f.ctx.mirror,null);assert.equal(f.windows.length,1);
  f.mirrors[0].clean.resolve();await f.ctx.mirrorLifecycle.closing;
});
