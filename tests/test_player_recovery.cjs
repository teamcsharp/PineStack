const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const app = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
const renderer = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'renderer.js'), 'utf8');
const revive = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'pine-revive.js'), 'utf8');
function section(source, first, next) {
  const start = source.indexOf(first);
  assert(start >= 0, first);
  const end = source.indexOf(next, start + first.length);
  assert(end > start, next);
  return source.slice(start, end);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function timers() {
  let id = 0;
  const tasks = new Map();
  return {
    setTimeout(fn, delay) { const key = ++id; tasks.set(key, {fn, delay}); return key; },
    clearTimeout(key) { tasks.delete(key); },
    run(delay) { const item = [...tasks.entries()].find(([, row]) => row.delay === delay); assert(item, `timer ${delay}`); tasks.delete(item[0]); item[1].fn(); },
    tasks
  };
}
function player() {
  const play = deferred();
  return {src: '', paused: true, ended: false, currentTime: 0, duration: 2,
    volume: 1, readyState: 1, dataset: {}, playJob: play,
    getAttribute(name) { return this[name] || ''; },
    removeAttribute(name) { this[name] = ''; },
    load() {}, pause() { this.paused = true; },
    play() { this.paused = false; return play.promise; }};
}
function voiceHarness() {
  const clock = {now: 100000};
  const jobs = timers();
  const players = [player(), player()];
  const context = vm.createContext({Date: {now: () => clock.now}, ...jobs,
    window: {cacheHold: false}, pineAirPaused: false,
    djVoiceBusy: false, djVoiceBusyUntil: 0, djVoiceQueue: [],
    djVoiceSlot: 0, djVoiceEls: players, djVoiceEpoch: 0, djVoiceCut: 0,
    djVoiceLive: 0, djVoiceNow: null, djSpeaking: false, djStreamNow: null,
    djStreamLiveId: '', djOverlapLead: 1, VOICE_LATE_PLAY_MS: 45000,
    VOICE_HEAD_TRIES: 6, VOICE_GIVE_UP_MS: 120000,
    djVoiceWarm() {}, djVoiceKeeps: () => true, djVoiceHoldLate() {},
    djLatePlay: () => true, djVoiceEl: slot => players[slot],
    djClipUrl: url => url, djApplyGain() {}, djTalkMarkLive() {},
    djVoiceAck() {}, djBoothTick() {}, pineReplyGapCue() {},
    pineReplyGapDue: clip => clip.broadcastAt,
    pineReplyGapEarly: () => false, pineReplyGapWordsEnded() {},
    djVoiceCompare: (a,b) => a.ts-b.ts
  });
  vm.runInContext(section(app, 'function djVoiceNext() {', '// A single "tap to enable audio"'), context);
  const clip = ts => ({ts, url: `/voice/${ts}.wav`, broadcastAt: clock.now,
    speech: true, keepWhole: true, stream: null});
  return {clock, jobs, players, context, clip};
}

test('overlapping DJ clips retire their live count on actual completion', () => {
  const h = voiceHarness();
  h.context.djVoiceQueue.push(h.clip(1), h.clip(2));
  h.context.djVoiceNext();
  h.players[0].onplaying();
  h.players[0].onloadedmetadata();
  h.jobs.run(1000); // first player gives the slot to the second
  assert.equal(h.context.djVoiceLive, 2);
  h.players[0].onended();
  assert.equal(h.context.djVoiceLive, 1);
  h.players[1].onplaying(); h.players[1].onended();
  assert.equal(h.context.djVoiceLive, 0);
  assert.equal(h.context.djSpeaking, false);
});

test('cancelled play promises and metadata cannot clobber the successor', async () => {
  const h = voiceHarness();
  const old = h.clip(1), next = h.clip(2);
  h.context.djVoiceQueue.push(old);
  h.context.djVoiceNext();
  const oldMetadata = h.players[0].onloadedmetadata;
  h.context.djVoiceEpoch += 1; h.context.djVoiceBusy = false; h.context.djVoiceLive = 0;
  h.context.djVoiceQueue.push(next); h.context.djVoiceNext();
  h.players[0].playJob.reject(Object.assign(new Error('cancelled'), {name: 'NotAllowedError'}));
  await Promise.resolve(); await Promise.resolve();
  oldMetadata();
  assert.equal(h.context.djVoiceBusy, true);
  assert.equal(h.context.djVoiceLive, 1);
  assert.equal(h.context.djVoiceQueue.length, 0);
  assert.equal(h.players[1].pineDeliveryClip, next);
});

test('a timed out old voice poll cannot apply a cut or release a newer request', async () => {
  const clock = {now: 1000};
  const requests = [];
  const context = vm.createContext({Date: {now: () => clock.now},
    djLastState: {voice_to: 'here'}, djVoiceMode: () => 'here',
    djVoicePollLive: 0, djVoicePollSerial: 0, djVoiceSeen: 0,
    djVoiceRate: 96, djVoiceCut: 0, djVoiceQueue: [], djVoiceNow: null,
    djVoicePrimed: false, djVoiceRetime() {},
    api: () => { const job = deferred(); requests.push(job); return job.promise; }});
  vm.runInContext(section(app, 'async function djVoicePoll(immediate)', 'async function djGo()'), context);
  const old = context.djVoicePoll();
  clock.now = 22000;
  const current = context.djVoicePoll();
  requests[0].resolve({clips: [], cut_ms: 9000}); await old;
  assert.equal(context.djVoiceCut, 0);
  assert.equal(context.djVoicePollLive, 22000);
  requests[1].resolve({clips: [], cut_ms: 0}); await current;
  assert.equal(context.djVoicePollLive, 0);
});

test('a frozen positive media position does not count as progressing audio', () => {
  const clock = {now: 1000};
  const context = vm.createContext({Date: {now: () => clock.now}, djVoiceProgress: new WeakMap()});
  vm.runInContext(section(app, 'function djVoiceAdvancing(player)', 'let djVoiceBusyUntil'), context);
  const media = {src: '/voice.wav', paused: false, ended: false, currentTime: 4};
  assert.equal(context.djVoiceAdvancing(media), true);
  clock.now += 12001;
  assert.equal(context.djVoiceAdvancing(media), false);
  media.currentTime += 0.5;
  assert.equal(context.djVoiceAdvancing(media), true);
});

test('local recovery preserves unfinished speech and resumes at its last position', () => {
  const h = voiceHarness();
  const owed = h.clip(1), pending = h.clip(2);
  h.players[0].pineDeliveryClip = owed;
  h.players[0].src = owed.url; h.players[0].currentTime = 7; h.players[0].paused = false;
  h.players[0].dataset.pineHeld = '1';
  h.context.djVoiceQueue.push(pending);
  h.context.djVoiceBusy = true; h.context.djVoiceLive = 1; h.context.djSpeaking = true;
  h.context.djVoiceTimer = 0;
  h.context.djVoiceProgress = new WeakMap(); h.context.VOICE_KEEP_MS = 600000;
  vm.runInContext(section(app, 'function djVoiceReset(reason)', '/* #1396:'), h.context);
  assert.equal(h.context.djVoiceReset('test recovery'), 1);
  assert.equal(h.context.djVoiceEpoch, 1);
  assert.equal(h.context.djVoiceBusy, false); assert.equal(h.context.djVoiceLive, 0);
  assert.equal(h.context.djSpeaking, false);
  assert.equal(h.context.djVoiceQueue[0], owed); assert.equal(h.context.djVoiceQueue[1], pending);
  assert.equal(owed.resumeAt, 6.8); assert.equal(owed.retry, 1);
  assert.equal(h.players[0].pineDeliveryClip, null);
  assert.equal(h.players[0].dataset.pineHeld, '');
  assert.equal(h.players[0].src, '');
});

test('listener obsolete poll cannot overwrite newer station state', async () => {
  const clock = {now: 1000}, requests = [], painted = [];
  const context = vm.createContext({Date: {now: () => clock.now}, window: {addEventListener() {}},
    pollSerial: 0, pollLive: 0, playing: false, ME: 'test', stateAt: 0,
    voiceUnstick() {}, sync: state => painted.push(state.id), paintMediaSession() {},
    renderGallery() {}, patter() {},
    api: () => { const job = deferred(); requests.push(job); return job.promise; }});
  vm.runInContext(section(app, 'async function poll() {', '// A poll can carry several clips'), context);
  const old = context.poll(); clock.now = 22000; const current = context.poll();
  requests[1].resolve({id: 'current'}); await current;
  requests[0].resolve({id: 'obsolete'}); await old;
  assert.deepEqual(painted, ['current']);
});

test('audio recovery probes and resumes the actual graph and its compatibility alias', () => {
  for (const name of ['pineAudioCtx', '__pineAudioCtx']) {
    let resumed = 0;
    const graph = {state: 'suspended', currentTime: 5, resume() { resumed++; return Promise.resolve(); }};
    const context = vm.createContext({window: {[name]: graph}, location: {href: 'http://station/'},
      sessionStorage: {}, document: {querySelectorAll: () => []}});
    vm.runInContext(section(revive, 'function panelProbeFn()', '/* --- evaluated inside the panel: back onto'), context);
    assert.equal(context.panelProbeFn().ctx.state, 'suspended');
    context.panelReviveFn(); assert.equal(resumed, 1);
  }
});

test('manual recovery resumes the shared graph before restarting owed DJ speech', () => {
  let resumed = 0, restarted = 0;
  const graph = {state: 'suspended', resume() { resumed++; return Promise.resolve(); }};
  const context = vm.createContext({window: {pineAudioCtx: graph},
    gains: {music: null, voice: null}, pineAirPaused: true, pineAudioUnlocked: true,
    djVoiceReset: () => 1, djVoiceNext() { assert.equal(resumed, 1); restarted++; },
    djVoicePoll() {}, djVoicePollSerial: 0, djVoicePollLive: 1,
    djVideoPollSerial: 0, djVideoPollLive: 1});
  vm.runInContext(section(app, 'function fixUngag()', 'window.pineRecoverPlayback = fixUngag'), context);
  context.fixUngag();
  assert.equal(resumed, 1); assert.equal(restarted, 1);
  assert.equal(context.pineAirPaused, false); assert.equal(context.pineAudioUnlocked, false);
});

test('webview reconnect backs off, ignores cancellation/subresources, and retires on success', () => {
  const jobs = timers(), handlers = {}, online = [];
  let reloads = 0;
  const frame = {src: 'http://station/', dataset: {},
    addEventListener(name, fn) { handlers[name] = fn; },
    reload() { reloads += 1; }};
  const context = vm.createContext({...jobs,
    window: {addEventListener(name, fn) { if (name === 'online') online.push(fn); }},
    applyAppVolumeToFrame() {}, setText() {}});
  vm.runInContext(section(renderer, 'function wireFrame(frame)', 'window.pineReconnectStationFrames'), context);
  context.wireFrame(frame); context.wireFrame(frame);
  handlers['did-fail-load']({errorCode: -3, isMainFrame: true});
  handlers['did-fail-load']({errorCode: -105, isMainFrame: false});
  assert.equal(jobs.tasks.size, 0);
  handlers['did-fail-load']({errorCode: -105, isMainFrame: true});
  jobs.run(1000); assert.equal(reloads, 1);
  handlers['did-fail-load']({errorCode: -105, isMainFrame: true});
  jobs.run(2000); assert.equal(reloads, 2);
  handlers['did-fail-load']({errorCode: -105, isMainFrame: true});
  handlers['did-finish-load'](); assert.equal(jobs.tasks.size, 0);
  assert.equal(frame.pineConnection.state().failed, false);
  assert.equal(online.length, 1);
});

test('webview reconnect persists at a capped interval, then retires on success and navigation', () => {
  const jobs = timers(), handlers = {}, online = [];
  let reloads = 0;
  const frame = {src: 'http://station/', dataset: {},
    addEventListener(name, fn) { handlers[name] = fn; }, reload() { reloads += 1; }};
  const context = vm.createContext({...jobs,
    window: {addEventListener(name, fn) { if (name === 'online') online.push(fn); }},
    applyAppVolumeToFrame() {}, setText() {}});
  vm.runInContext(section(renderer, 'function wireFrame(frame)', 'window.pineReconnectStationFrames'), context);
  context.wireFrame(frame);
  for (let n = 0; n < 12; n++) {
    handlers['did-fail-load']({errorCode: -105});
    handlers['did-fail-load']({errorCode: -105});
    assert.equal(jobs.tasks.size, 1);
    jobs.run(Math.min(30000, 1000 * (2 ** n)));
  }
  handlers['did-fail-load']({errorCode: -105});
  assert.equal(jobs.tasks.size, 1); assert.equal(reloads, 12);
  handlers['did-finish-load'](); assert.equal(jobs.tasks.size, 0);
  assert.equal(frame.pineConnection.state().failed, false);
  handlers['did-fail-load']({errorCode: -105});
  online[0](); jobs.run(0); assert.equal(reloads, 13);
  handlers['did-fail-load']({errorCode: -105});
  frame.src = 'http://new-station/';
  jobs.run(2000); assert.equal(reloads, 13);
});

test('webview reconnect retires detached media and a closing document', () => {
  const jobs = timers(), handlers = {}, events = {};
  let reloads = 0;
  const frame = {src: 'http://station/', dataset: {}, isConnected: true,
    addEventListener(name, fn) { handlers[name] = fn; }, reload() { reloads++; }};
  const context = vm.createContext({...jobs,
    window: {addEventListener(name, fn) { events[name] = fn; }},
    applyAppVolumeToFrame() {}, setText() {}});
  vm.runInContext(section(renderer, 'function wireFrame(frame)', 'window.pineReconnectStationFrames'), context);
  context.wireFrame(frame);
  handlers['did-fail-load']({errorCode: -105}); frame.isConnected = false;
  jobs.run(1000); assert.equal(reloads, 0); assert.equal(jobs.tasks.size, 0);
  assert.equal(frame.pineConnection.state().failed, false);
  handlers['did-fail-load']({errorCode: -105}); assert.equal(jobs.tasks.size, 0);
  frame.isConnected = true;
  handlers['did-fail-load']({errorCode: -105}); events.beforeunload();
  assert.equal(jobs.tasks.size, 0); events.online(); assert.equal(jobs.tasks.size, 0);
  assert.equal(reloads, 0);
});
