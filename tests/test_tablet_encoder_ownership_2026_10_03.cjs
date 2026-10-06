'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {EventEmitter} = require('node:events');
const {PassThrough} = require('node:stream');
const {Mirror} = require('../desktop/tablet-mirror.cjs');
function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
}
function fixture(overrides = {}) {
  const calls = [];
  const owner = 'mirror_test_owner';
  const confirmed = {ok:true,held:true,owner,video_running:false,video_released:true};
  const lease = {owner,acquire:async()=>confirmed,renew:async()=>confirmed,
    release:async()=>{ calls.push('release'); return {ok:true,held:false}; },...overrides};
  const mirror = new Mirror({
    serial:'10.89.1.154:5555',encoderLease:lease,
    execFile(file,args,options,done) { done(null,'already connected to 10.89.1.154:5555',''); },
    spawn(file,args) {
      calls.push(file);
      const child = new EventEmitter();
      Object.assign(child,{stdout:new PassThrough(),stdin:new PassThrough(),stderr:new PassThrough(),exitCode:null});
      child.kill = () => { child.exitCode = 0; child.stdout.destroy(); child.stdin.destroy(); child.stderr.destroy(); };
      return child;
    }
  });
  mirror.stopRemote = async () => { calls.push('stop'); };
  mirror.running = true;
  return {mirror,calls,confirmed,lease};
}
test('capture waits for acknowledged exclusive encoder ownership', async () => {
  const acquire = deferred();
  const {mirror,calls,confirmed} = fixture({acquire:()=>acquire.promise});
  const piping = mirror.pipe();
  await Promise.resolve();
  assert.equal(mirror.record,null);
  assert.deepEqual(calls,[]);
  acquire.resolve(confirmed);
  await piping;
  assert.equal(mirror.leaseHeld,true);
  assert.deepEqual(calls,['adb','ffmpeg']);
  await mirror.closeGently();
  assert.deepEqual(calls.slice(-2),['stop','release']);
});
test('a refused lease cannot spawn either encoder', async () => {
  const {mirror,calls} = fixture({acquire:async()=>({ok:false,detail:'replay codec is not released'})});
  let why = '';
  mirror.rebuild = value => { why = value; };
  await mirror.pipe();
  assert.deepEqual(calls,[]);
  assert.match(why,/encoder protection: replay codec is not released/);
  assert.equal(mirror.leaseHeld,false);
  mirror.close();
});
test('closing during native acquisition cannot start capture or leave an owned hold', async () => {
  const acquire = deferred();
  const {mirror,calls,confirmed} = fixture({acquire:()=>acquire.promise});
  const piping = mirror.pipe();
  await Promise.resolve();
  const closing = mirror.closeGently();
  acquire.resolve(confirmed);
  await Promise.all([piping,closing]);
  assert.deepEqual(calls,['stop','release']);
  assert.equal(mirror.running,false);
  assert.equal(mirror.leaseHeld,false);
  assert.equal(mirror.leaseTimer,null);
});
test('refused heartbeat triggers producer recovery before lease expiration', async () => {
  const {mirror} = fixture({renew:async()=>({ok:false,detail:'connection unavailable'})});
  await mirror.pipe();
  let why = '';
  mirror.rebuild = value => { why = value; };
  await mirror.renewEncoderLease();
  assert.match(why,/encoder protection was lost: connection unavailable/);
  await mirror.closeGently();
});
test('a stale heartbeat reply cannot restart a closing mirror', async () => {
  const renew = deferred();
  const {mirror} = fixture({renew:()=>renew.promise});
  await mirror.pipe();
  let rebuilt = false;
  mirror.rebuild = () => { rebuilt = true; };
  const renewing = mirror.renewEncoderLease();
  const closing = mirror.closeGently();
  renew.resolve({ok:false,detail:'connection unavailable'});
  await Promise.all([renewing,closing]);
  assert.equal(rebuilt,false);
  assert.equal(mirror.leaseTimer,null);
});
test('failed lease release still closes local streams and reports the native hold', async () => {
  const {mirror} = fixture({release:async()=>({ok:false,detail:'waiting for screenrecord shutdown'})});
  await mirror.pipe();
  await mirror.closeGently();
  assert.equal(mirror.record,null);
  assert.equal(mirror.convert,null);
  assert.equal(mirror.running,false);
  assert.match(mirror.lastError,/waiting for screenrecord shutdown/);
});

test('cleanup cannot signal a recorder owned by another mirror', async () => {
  let signals = 0;
  const lease = {owner:'mirror_test_owner',status:async()=>({ok:true,held:true,owner:'different_owner'})};
  const mirror = new Mirror({encoderLease:lease,execFile(){ signals++; }});
  mirror.leaseHeld = true;
  await mirror.stopRemote();
  assert.equal(signals,0);
  assert.match(mirror.lastError,/owner could not be verified/);
});
test('a refused acquisition never sends a remote stop signal', async () => {
  let calls = 0;
  const mirror = new Mirror({encoderLease:{status(){ calls++; }},execFile(){ calls++; }});
  await mirror.stopRemote();
  assert.equal(calls,0);
});
test('owned recorder cleanup waits for process exit and exposes a failed stop', async () => {
  const lease = {owner:'mirror_test_owner',status:async()=>({ok:true,held:true,owner:'mirror_test_owner'})};
  let command = '';
  const mirror = new Mirror({serial:'10.89.1.154:5555',encoderLease:lease,
    execFile(file,args,options,done){
      command = args.at(-1);
      done(new Error('still running'));
    }});
  mirror.leaseHeld = true;
  await mirror.stopRemote();
  assert.match(command,/pkill -INT/);
  assert.match(command,/while pidof screenrecord/);
  assert.match(mirror.lastError,/still stopping/);
});

test('a desktop restart recovers its own orphan before starting another encoder', async () => {
  let acquires = 0;
  const {mirror,calls,confirmed,lease} = fixture();
  lease.acquire = async () => ++acquires === 1
    ? {ok:false,held:true,owner:lease.owner,detail:'previous recorder is still running'}
    : confirmed;
  await mirror.pipe();
  assert.equal(acquires,2);
  assert.deepEqual(calls,['stop','adb','ffmpeg']);
  await mirror.closeGently();
});
test('an orphan belonging to a different desktop is never stopped or replaced', async () => {
  const {mirror,calls} = fixture({acquire:async()=>({ok:false,held:true,owner:'another_desktop',
    detail:'another desktop owns the encoder'})});
  mirror.rebuild = () => {};
  await mirror.pipe();
  assert.deepEqual(calls,[]);
  assert.equal(mirror.leaseHeld,false);
  mirror.close();
});

test('a transient failed orphan stop is retried until native ownership is reacquired', async () => {
  let stops = 0;
  const {mirror,calls,confirmed,lease} = fixture();
  lease.acquire = async () => stops >= 2 ? confirmed
    : {ok:false,held:true,owner:lease.owner,detail:'old recorder still present'};
  mirror.stopRemote = async () => { stops++; calls.push('stop'); };
  mirror.rebuild = () => {};
  await mirror.pipe();
  assert.equal(mirror.record,null);
  assert.equal(mirror.orphanChecked,false);
  await mirror.pipe();
  assert.equal(stops,2);
  assert.equal(mirror.orphanChecked,true);
  assert.deepEqual(calls,['stop','stop','adb','ffmpeg']);
  await mirror.closeGently();
});
