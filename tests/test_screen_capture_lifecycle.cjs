const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/screen-ring.js'), 'utf8');
const settle = async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); };

// Virtual time, actual asynchronous stop/data delivery, and independently
// acknowledged IPC writes reproduce the races that made live exports drift.
function fixture(options = {}) {
  let clock = 0, wall = 1730000000000, sequence = 0, timerSequence = 0, selectedTarget = 'panel';
  const timers = new Map(), handlers = {}, captures = [], recorders = [], writes = [];
  const calls = { user: [], targets: [], sources: 0, contexts: [], notes: [] };
  const schedule = (fn, delay) => { const id = ++timerSequence; timers.set(id, { at: clock + delay, fn }); return id; };
  const makeTrack = (kind, settings = {}) => {
    const events = {};
    return { kind, readyState: 'live', muted: false, stops: 0,
      getSettings: () => ({ ...settings }),
      addEventListener: (name, fn) => { (events[name] ||= []).push(fn); },
      stop() { this.stops++; this.readyState = 'ended'; },
      end() { this.readyState = 'ended'; (events.ended || []).forEach(fn => fn()); }
    };
  };
  const makeStream = (kind, geometry = {}) => {
    const items = [makeTrack(kind === 'v' ? 'video' : 'audio', geometry)];
    const capture = { kind, items, getTracks: () => items,
      getVideoTracks: () => items.filter(t => t.kind === 'video'),
      getAudioTracks: () => items.filter(t => t.kind === 'audio') };
    captures.push(capture); return capture;
  };
  function MediaRecorder(capture, encoding) {
    const kind = capture.getVideoTracks().length ? 'v' : 'a';
    if (options.rejectCodec && encoding.mimeType === options.rejectCodec) throw new Error('encoder unavailable');
    this.id = ++sequence; this.stream = capture; this.kind = kind; this.encoding = encoding;
    this.mimeType = encoding.mimeType; this.state = 'inactive'; this.stops = 0;
    this.start = () => {
      if (options.startRejectCodec === this.mimeType) throw new Error('encoder start refused');
      this.state = 'recording'; this.startAt = clock;
    };
    this.stop = () => {
      assert.equal(this.state, 'recording', 'only an active recorder can be stopped');
      this.state = 'inactive'; this.stops++; this.stopAt = clock;
      schedule(() => {
        if (this.ondataavailable) this.ondataavailable({ data: { size: 1, token: this.id } });
        if (this.onstop) this.onstop();
      }, (options.stopDelay && options.stopDelay[kind]) || 0);
    };
    recorders.push(this);
  }
  MediaRecorder.isTypeSupported = mime => options.supported ? options.supported.includes(mime) : true;
  function Blob(parts) {
    this.size = parts.reduce((total, part) => total + part.size, 0);
    this.arrayBuffer = () => Promise.resolve(Uint8Array.from(parts.map(part => part.token)).buffer);
  }
  function AudioContext() {
    const resumeWaiters = [];
    this.state = options.resumeBlocked && options.resumeBlocked() ? 'suspended' : 'running'; this.speakerConnections = 0; this.sources = [];
    this.destination = { speaker: true }; calls.contexts.push(this);
    this.resume = () => {
      if (options.resumeBlocked && options.resumeBlocked()) return new Promise((resolve,reject)=>resumeWaiters.push({resolve,reject}));
      this.state = 'running'; resumeWaiters.splice(0).forEach(waiter=>waiter.resolve()); return Promise.resolve();
    };
    this.close = () => { this.state = 'closed'; resumeWaiters.splice(0).forEach(waiter=>waiter.reject(new Error('context closed'))); return Promise.resolve(); };
    this.createMediaStreamDestination = () => ({ stream: makeStream('a') });
    this.createMediaStreamSource = capture => {
      this.sources.push(capture);
      return { connect: target => { if (target.speaker) this.speakerConnections++; }, disconnect() {} };
    };
  }
  const root = { MediaRecorder, Blob, AudioContext, devicePixelRatio: 2, outerWidth: 960, outerHeight: 540,
    performance: { now: () => clock }, setTimeout: schedule, clearTimeout: id => timers.delete(id),
    console: { log: value => calls.notes.push(value) },
    addEventListener: (name, fn) => { (handlers[name] ||= []).push(fn); },
    document: { readyState: options.readyState || 'loading', body: { classList: { contains: () => root.pip || false } },
      addEventListener: (name, fn) => { (handlers[name] ||= []).push(fn); } },
    navigator: { mediaDevices: {
      getUserMedia: request => {
        calls.user.push(request);
        const c = request.video.mandatory;
        const capture = makeStream('v', { width: c.maxWidth, height: c.maxHeight, frameRate: options.actualFps || 60 });
        return options.videoGate ? options.videoGate.then(() => capture) : Promise.resolve(capture);
      },
      getDisplayMedia: request => {
        assert.equal(request.video, false);
        assert.equal(request.audio.autoGainControl, false); assert.equal(request.audio.echoCancellation, false);
        assert.equal(request.audio.noiseSuppression, false); assert.equal(request.audio.channelCount.ideal, 2);
        assert.equal(request.audio.sampleRate.ideal, 48000);
        if (options.soundRefused && options.soundRefused(selectedTarget)) return Promise.reject(new Error('audio not ready'));
        const capture = makeStream('a'); capture.target = selectedTarget;
        return options.soundGate ? Promise.resolve(options.soundGate(selectedTarget)).then(()=>capture) : Promise.resolve(capture);
      }
    } },
    pineDesktop: {
      replaySource: async () => { calls.sources++; return { ok: true, id: 'window:1',
        width: root.outerWidth * root.devicePixelRatio, height: root.outerHeight * root.devicePixelRatio }; },
      replayAudioTarget: async target => { selectedTarget = target; calls.targets.push(target); return { ok: true }; },
      replayBegin: async () => ({ ok: true, rings: 2 }), replayStop: async () => ({ ok: true }), onReplayFlush() {},
      replayPush: (buffer, metadata) => {
        const write = { metadata, tokens: [...new Uint8Array(buffer)] };
        writes.push(write);
        return options.heldWrites ? new Promise(resolve => { write.resolve = resolve; }) : Promise.resolve({ ok: true });
      }
    }
  };
  if (!options.legacy && !options.noCatalog) {
    root.pineDesktop.replayAudioSources = async () => ({ ok:true, targets:options.catalog ? options.catalog() : ['shell','panel'] });
    root.pineDesktop.onReplayAudioSourcesChanged = callback => { (handlers.catalog ||= []).push(callback); };
  }
  if (options.legacy) delete root.pineDesktop.replayAudioTarget;
  const DateClock = { now: () => wall };
  vm.runInNewContext(source, { window: root, globalThis: root, Date: DateClock, Promise, Set, ArrayBuffer });
  const advance = async duration => {
    const end = clock + duration;
    for (let count = 0; count < 1000; count++) {
      const due = [...timers.entries()].filter(([, timer]) => timer.at <= end).sort((a,b) => a[1].at - b[1].at)[0];
      if (!due) { wall += end - clock; clock = end; await settle(); return; }
      wall += due[1].at - clock; clock = due[1].at; timers.delete(due[0]); due[1].fn(); await settle();
    }
    throw new Error('timer loop did not converge');
  };
  return { root, api: root.PineScreenRing, calls, captures, recorders, writes, timers, advance,
    jumpWall: by => { wall += by; }, fire: name => (handlers[name] || []).forEach(fn => fn()),
    latest: kind => recorders.filter(rec => rec.kind === kind).at(-1), clock: () => clock };
}

test('capture requests physical pixels at60fps and mixes two frames without speaker feedback', async () => {
  const f = fixture({ actualFps: 59.94 }); await f.api.start(); await settle();
  const c = f.calls.user[0].video.mandatory;
  assert.deepEqual([c.minWidth,c.maxWidth,c.minHeight,c.maxHeight], [1920,1920,1080,1080]);
  assert.equal(c.maxFrameRate,60); assert.deepEqual(f.calls.targets, ['shell','panel']);
  assert.equal(f.calls.contexts.length,1); assert.equal(f.calls.contexts[0].sources.length,2);
  assert.equal(f.calls.contexts[0].speakerConnections,0);
  assert.equal(f.api.state().encoding.fps,59.94); assert.ok(f.api.state().encoding.bitrate >= 14000000);
  assert.equal(f.api.state().audio.complete,true); f.api.stop(); await f.advance(0);
});

test('delayed stop callbacks and a wall-clock jump do not alter duration or original settings', async () => {
  const f = fixture({ stopDelay: { v:400, a:250 } }); await f.api.start(); await settle();
  await f.advance(700); const oldVideo = f.latest('v'), oldAudio = f.latest('a');
  const flushed = f.api.flush(); f.jumpWall(3600000); await f.advance(400);
  assert.equal(await flushed,true);
  assert.equal(f.writes.length,2);
  for (const write of f.writes) {
    assert.equal(write.metadata.ms,700); assert.equal(write.metadata.at,1730000000000);
    assert.deepEqual(write.tokens,[write.metadata.kind === 'v' ? oldVideo.id : oldAudio.id]);
  }
  assert.deepEqual([f.writes.find(w => w.metadata.kind === 'v').metadata.w,
    f.writes.find(w => w.metadata.kind === 'v').metadata.h],[1920,1080]);
  assert.equal(f.latest('v').startAt,700); assert.equal(f.latest('a').startAt,700);
  assert.equal(oldVideo.stopAt,f.latest('v').startAt); assert.equal(oldAudio.stopAt,f.latest('a').startAt);
  f.api.stop(); await f.advance(400);
});

test('flush clears old timers so they cannot stop the replacement segments early', async () => {
  const f = fixture({ stopDelay: { v:400, a:250 } }); await f.api.start(); await settle();
  await f.advance(700); const flushed=f.api.flush(); await f.advance(400); await flushed;
  const picture=f.latest('v'), audio=f.latest('a');
  await f.advance(900); // Original segments'2000ms deadline.
  assert.equal(picture.state,'recording'); assert.equal(audio.state,'recording');
  assert.equal(picture.stops,0); assert.equal(audio.stops,0);
  f.api.stop(); await f.advance(400);
});

test('flush waits for both current pieces and a preceding pending disk write, after restarting capture', async () => {
  const f=fixture({ heldWrites:true }); await f.api.start(); await settle();
  await f.advance(300); f.latest('v').stop(); await f.advance(0); // Previous write still awaiting disk.
  await f.advance(200); const flushed=f.api.flush(); let settled=false; flushed.then(()=>{settled=true;});
  await f.advance(0); assert.equal(f.writes.length,3);
  assert.equal(f.latest('v').state,'recording'); assert.equal(f.latest('a').state,'recording');
  f.writes.slice(1).forEach(write=>write.resolve({ok:true})); await settle(); assert.equal(settled,false);
  f.writes[0].resolve({ok:true}); await settle(); assert.equal(await flushed,true);
  f.api.stop(); await f.advance(0); f.writes.slice(3).forEach(write=>write.resolve({ok:true})); await settle();
});

test('flush reports refused disk writes instead of claiming the newest frames reached cache', async () => {
  const f=fixture({heldWrites:true}); await f.api.start(); await settle(); await f.advance(100);
  const flushed=f.api.flush(); await f.advance(0);
  f.writes[0].resolve({ok:false,detail:'disk full'}); f.writes[1].resolve({ok:true});
  await settle(); assert.equal(await flushed,false); assert.match(f.api.state().said,/disk full/);
  f.api.stop(); await f.advance(0); f.writes.slice(2).forEach(write=>write.resolve({ok:true})); await settle();
});

test('resize opens native replacement before stopping old capture and leaves sound continuously running', async () => {
  const f=fixture({stopDelay:{v:300}}); await f.api.start(); await settle(); await f.advance(100);
  const old=f.latest('v'), audio=f.latest('a'); f.root.outerWidth=1200; f.root.outerHeight=700; f.fire('resize');
  await f.advance(180);
  const replacement=f.latest('v'); assert.notEqual(replacement,old);
  assert.equal(replacement.state,'recording'); assert.equal(old.stream.items[0].readyState,'live');
  assert.equal(f.latest('a'),audio); assert.equal(audio.state,'recording');
  await f.advance(300); assert.equal(old.stream.items[0].readyState,'ended');
  assert.equal(f.writes[0].metadata.w,1920); assert.equal(f.writes[0].metadata.h,1080);
  await f.advance(20); const flushed=f.api.flush(); await f.advance(300); assert.equal(await flushed,true);
  const last=f.writes.filter(w=>w.metadata.kind==='v').at(-1);
  assert.deepEqual([last.metadata.w,last.metadata.h],[2400,1400]);
  f.api.stop(); await f.advance(300);
});

test('ended picture and initially unavailable sound recover automatically without reopening a healthy lane', async () => {
  let refused=true; const f=fixture({soundRefused:()=>refused}); await f.api.start(); await settle();
  assert.equal(f.api.state().audio.running,false); refused=false; await f.advance(1000);
  assert.equal(f.api.state().audio.running,true); assert.equal(f.calls.user.length,1);
  const audio=f.latest('a'); f.latest('v').stream.items[0].end(); await f.advance(1000);
  assert.equal(f.api.state().running,true); assert.equal(f.calls.user.length,2);
  assert.equal(f.latest('a'),audio); f.api.stop(); await f.advance(0); const opened=f.calls.user.length;
  await f.advance(10000); assert.equal(f.calls.user.length,opened); assert.equal(f.api.state().enabled,false);
});

test('stop while opening cleans returned captures and never resurrects recording', async () => {
  let release; const gate=new Promise(resolve=>{release=resolve;}); const f=fixture({videoGate:gate});
  const one=f.api.start(), two=f.api.start(); await settle(); assert.equal(f.calls.user.length,1);
  f.api.stop(); release(); await settle(); await one; await two;
  assert.equal(f.api.state().running,false);
  assert.ok(f.captures.every(capture=>capture.items.every(track=>track.readyState==='ended')));
  await f.advance(10000); assert.equal(f.calls.user.length,1);
});

test('an explicit stop before startup backstop prevents later auto-start', async () => {
  const f=fixture({readyState:'complete'}); f.api.stop(); await f.advance(6000);
  assert.equal(f.calls.user.length,0); assert.equal(f.api.state().enabled,false);
});

test('unsupported hardware-friendly encoders fall back to a runnable codec and report the actual codec', async () => {
  const f=fixture({rejectCodec:'video/webm;codecs=h264',startRejectCodec:'video/mp4;codecs=avc1.42E01E'});
  await f.api.start(); await settle(); assert.equal(f.api.state().running,true);
  assert.equal(f.api.state().encoding.mime,'video/webm;codecs=vp8');
  await f.advance(100); const flushed=f.api.flush(); await f.advance(0); assert.equal(await flushed,true);
  assert.equal(f.writes.find(write=>write.metadata.kind==='v').metadata.mime,'video/webm;codecs=vp8');
  f.api.stop(); await f.advance(0);
});

test('legacy panel audio is retained while full application audio coverage is explicitly incomplete', async () => {
  const f=fixture({legacy:true}); await f.api.start(); await settle(); assert.equal(f.api.state().audio.live,true);
  assert.equal(f.api.state().audio.complete,false); await f.advance(100);
  const flushed=f.api.flush(); await f.advance(0); assert.equal(await flushed,true);
  const audio=f.writes.find(write=>write.metadata.kind==='a').metadata;
  assert.equal(audio.a,true); assert.equal(audio.audio_complete,false); assert.match(audio.mime,/opus/);
  f.api.stop(); await f.advance(0);
});


test('a late error from a replaced recorder cannot stop or reconfigure the healthy replacement', async () => {
  const f=fixture({stopDelay:{v:500}}); await f.api.start(); await settle(); await f.advance(100);
  const old=f.latest('v'); f.root.outerWidth=1200; f.fire('resize'); await f.advance(180);
  const current=f.latest('v'); old.onerror({error:{message:'retired encoder failed'}}); await settle();
  assert.equal(f.api.state().running,true); assert.equal(current.state,'recording');
  assert.equal(current.stream.items[0].readyState,'live');
  await f.advance(500); assert.equal(f.writes.filter(write=>write.metadata.kind==='v').length,0);
  assert.equal(f.api.state().encoding.mime,current.mimeType);
  f.api.stop(); await f.advance(500);
});

test('an asynchronous encoder failure switches codec and resumes capture automatically', async () => {
  const f=fixture(); await f.api.start(); await settle(); await f.advance(100);
  const failed=f.latest('v'); failed.onerror({error:{message:'hardware encode failed'}}); await f.advance(1900);
  assert.equal(f.api.state().running,true); assert.notEqual(f.api.state().encoding.mime,failed.mimeType);
  assert.equal(f.writes.some(write=>write.metadata.kind==='v'&&write.tokens.includes(failed.id)),false);
  f.api.stop(); await f.advance(0);
});


test('a fresh activation resumes the same pending mixer rather than leaving sound opening forever', async () => {
  let blocked=true; const f=fixture({resumeBlocked:()=>blocked}); await f.api.start(); await settle();
  assert.equal(f.api.state().audio.running,false); assert.equal(f.calls.contexts[0].state,'suspended');
  blocked=false; const result=await f.api.startSound({gesture:true}); await settle();
  assert.equal(result.ok,true); assert.equal(f.api.state().audio.complete,true);
  assert.equal(f.calls.contexts.length,1); assert.deepEqual(f.calls.targets,['shell','panel']);
  f.api.stop(); await f.advance(0);
});

test('stop and immediate restart clean a pending mixer and complete a fresh lifecycle promptly', async () => {
  let blocked=true; const f=fixture({resumeBlocked:()=>blocked}); await f.api.start(); await settle();
  const oldContext=f.calls.contexts[0], oldCaptures=f.captures.slice();
  f.api.stop(); blocked=false; const restarted=await f.api.start(); await settle();
  assert.equal(restarted.ok,true); assert.equal(f.api.state().audio.complete,true);
  assert.equal(oldContext.state,'closed'); assert.ok(oldCaptures.every(c=>c.items.every(t=>t.readyState==='ended')));
  assert.equal(f.calls.contexts.length,2); assert.deepEqual(f.calls.targets,['shell','panel','shell','panel']);
  f.api.stop(); await f.advance(0);
});

test('stop and immediate restart during picture negotiation serialize and replace stale capture', async () => {
  let release; const gate=new Promise(resolve=>{release=resolve;}); const f=fixture({videoGate:gate});
  const stale=f.api.start(); await settle(); f.api.stop(); const restarted=f.api.start(); await settle();
  assert.equal(f.calls.user.length,1); release(); await stale; const result=await restarted; await settle();
  assert.equal(result.ok,true); assert.equal(f.calls.user.length,2);
  assert.equal(f.captures.find(c=>c.kind==='v').items[0].readyState,'ended');
  assert.equal(f.latest('v').state,'recording'); f.api.stop(); await f.advance(0);
});


test('owned guest catalog adds a third frame exactly once and records its capture provenance', async () => {
  const targets=['shell','panel','guest:17','guest:17']; const f=fixture({catalog:()=>targets});
  await f.api.start(); await settle(); assert.equal(f.api.state().audio.complete,true);
  assert.deepEqual(f.calls.targets,['shell','panel','guest:17']);
  assert.equal(f.calls.contexts[0].sources.length,3); assert.equal(f.calls.contexts[0].speakerConnections,0);
  assert.deepEqual(Array.from(f.api.state().audio.targets),['shell','panel','guest:17']);
  await f.advance(100); const flushed=f.api.flush(); await f.advance(0); assert.equal(await flushed,true);
  const audio=f.writes.find(write=>write.metadata.kind==='a').metadata;
  assert.deepEqual(Array.from(audio.source_targets),['shell','panel','guest:17']); assert.equal(audio.audio_complete,true);
  f.api.stop(); await f.advance(0);
});

test('adding an audible guest keeps the existing mix live until replacement and marks interim coverage incomplete', async () => {
  const targets=['shell','panel']; let holdExtra=false, release;
  const held=new Promise(resolve=>{release=resolve;});
  const f=fixture({catalog:()=>targets,stopDelay:{a:300},soundGate:target=>holdExtra&&target==='guest:29'?held:null});
  await f.api.start(); await settle(); await f.advance(100); const oldContext=f.calls.contexts[0], oldCapture=f.latest('a').stream;
  targets.push('guest:29'); holdExtra=true; f.fire('catalog'); await settle();
  assert.equal(f.api.state().audio.live,true); assert.equal(f.api.state().audio.complete,false);
  assert.equal(oldContext.state,'running'); assert.equal(f.latest('a').stream,oldCapture);
  release(); await settle(); assert.equal(f.api.state().audio.complete,true);
  assert.notEqual(f.latest('a').stream,oldCapture); assert.equal(f.calls.contexts[1].sources.length,3);
  assert.equal(oldContext.state,'running'); await f.advance(300); assert.equal(oldContext.state,'closed');
  const previous=f.writes.filter(write=>write.metadata.kind==='a');
  assert.equal(previous.length,2); assert.equal(previous[0].metadata.audio_complete,true);
  assert.equal(previous[1].metadata.audio_complete,false);
  assert.deepEqual(Array.from(previous[1].metadata.source_targets),['shell','panel']);
  f.api.stop(); await f.advance(300);
});

test('a removed guest refreshes to remaining owned sources without stopping picture or losing healthy inputs', async () => {
  const targets=['shell','panel','guest:41']; const f=fixture({catalog:()=>targets});
  await f.api.start(); await settle(); await f.advance(100); const picture=f.latest('v');
  const removed=f.calls.contexts[0].sources[2]; targets.pop(); removed.items[0].end(); await settle(); await f.advance(0);
  assert.equal(f.latest('v'),picture); assert.equal(picture.state,'recording');
  assert.equal(f.api.state().audio.complete,true); assert.deepEqual(Array.from(f.api.state().audio.targets),['shell','panel']);
  assert.deepEqual(f.calls.targets,['shell','panel','guest:41','shell','panel']);
  assert.equal(f.calls.contexts[0].state,'closed'); assert.equal(f.calls.contexts[1].state,'running');
  f.api.stop(); await f.advance(0);
});

test('a failed new guest tap retains available audio and retries into a complete replacement', async () => {
  const targets=['shell','panel']; let refused=false;
  const f=fixture({catalog:()=>targets,soundRefused:target=>refused&&target==='guest:51'});
  await f.api.start(); await settle(); await f.advance(100); const oldContext=f.calls.contexts[0];
  targets.push('guest:51'); refused=true; f.fire('catalog'); await settle();
  assert.equal(f.api.state().audio.running,true); assert.equal(f.api.state().audio.live,true);
  assert.equal(f.api.state().audio.complete,false); assert.equal(f.api.state().audio.state,'partial');
  assert.equal(oldContext.state,'running'); refused=false; await f.advance(1900);
  assert.equal(f.api.state().audio.complete,true); assert.deepEqual(Array.from(f.api.state().audio.targets),targets);
  f.api.stop(); await f.advance(0);
});

test('an unrecognized catalog target cannot widen capture beyond application frames', async () => {
  const f=fixture({catalog:()=>['shell','panel','screen:0']}); await f.api.start(); await settle();
  assert.equal(f.api.state().running,true); assert.equal(f.api.state().audio.complete,false);
  assert.equal(f.calls.targets.length,0); assert.match(f.api.state().audio.detail,/invalid frame/);
  f.api.stop(); await f.advance(0);
});


test('an authoritative shell-only catalog captures complete startup audio without waiting for a panel', async () => {
  const f=fixture({catalog:()=>['shell']}); await f.api.start(); await settle();
  assert.equal(f.api.state().audio.complete,true); assert.deepEqual(f.calls.targets,['shell']);
  assert.equal(f.calls.contexts.length,0); assert.equal(f.api.state().audio.road,'desk-application-frames');
  await f.advance(100); const flushed=f.api.flush(); await f.advance(0); assert.equal(await flushed,true);
  assert.equal(f.writes.find(write=>write.metadata.kind==='a').metadata.audio_complete,true);
  f.api.stop(); await f.advance(0);
});

test('a source revision refreshes capture even when shell and panel target IDs do not change', async () => {
  const f=fixture({catalog:()=>['shell','panel']}); await f.api.start(); await settle(); await f.advance(100);
  const oldContext=f.calls.contexts[0], oldStream=f.latest('a').stream; f.fire('catalog'); await settle(); await f.advance(0);
  assert.equal(f.api.state().audio.complete,true); assert.notEqual(f.latest('a').stream,oldStream);
  assert.equal(oldContext.state,'closed'); assert.equal(f.calls.contexts.length,2);
  assert.deepEqual(f.calls.targets,['shell','panel','shell','panel']);
  f.api.stop(); await f.advance(0);
});


test('a legacy two-frame bridge keeps shell and panel sound but cannot claim coverage of all app guests', async () => {
  const f=fixture({noCatalog:true}); await f.api.start(); await settle();
  assert.equal(f.api.state().audio.live,true); assert.equal(f.api.state().audio.complete,false);
  assert.equal(f.api.state().audio.state,'partial'); assert.match(f.api.state().audio.detail,/other application frames/);
  await f.advance(100); const flushed=f.api.flush(); await f.advance(0); assert.equal(await flushed,true);
  const audio=f.writes.find(write=>write.metadata.kind==='a').metadata;
  assert.equal(audio.a,true); assert.equal(audio.audio_complete,false);
  assert.deepEqual(Array.from(audio.source_targets),['shell','panel']); f.api.stop(); await f.advance(0);
});
