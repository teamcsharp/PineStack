const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {repair} = require('../desktop/renderer/playback-recovery.js');
const wallModule = require('../desktop/renderer/video-wall.js');

const flush = async () => { for (let i = 0; i < 16; i += 1) await Promise.resolve(); };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };

function video(options = {}) {
  return {paused: false, autoplay: true, loop: true, muted: false, currentTime: 3,
    src: 'clip.mp4', isConnected: true, loads: 0, plays: 0, pauses: 0, cleared: false,
    matches() { return !!options.preview; }, closest() { return this.hidden || null; },
    querySelectorAll() { return []; },
    removeAttribute(name) { if (name === 'src') { this.src = ''; this.cleared = true; } },
    getAttribute(name) { return name === 'src' ? this.src : null; },
    pause() { this.pauses += 1; this.paused = true; if (options.pauseThrows) throw new Error('decoder failed'); },
    load() { this.loads += 1; },
    play() { this.plays += 1; this.paused = false; return options.playPromise || Promise.resolve(); },
    ...options};
}
function windowFor(nodes, extra = {}) {
  const events = {};
  return {setTimeout, clearTimeout, ...extra,
    document: {body: {classList: {contains() { return false; }}},
      querySelectorAll(selector) { return selector === 'video' ? nodes : nodes.filter(n => n.matches()); },
      addEventListener(name, callback) { events[name] = callback; }, events}};
}

test('repair stops H3, releases holds, resumes the intended wall and leaves camera/paused players alone', async () => {
  const preview = video({preview: true, pauseThrows: true});
  const wall = video({muted: true});
  const paused = video({paused: true, autoplay: false});
  const camera = video({srcObject: {camera: true}});
  const calls = [];
  const w = windowFor([preview, wall, paused, camera], {
    PineAdViewer: {recover() { calls.push('viewer'); throw new Error('orphaned viewer'); }},
    closeLightbox() { calls.push('lightbox'); }, lightboxDuckReset() { calls.push('lightbox hold'); },
    PineDuck: {release(name) { calls.push(name); }},
  });
  const result = await repair(w);
  assert.equal(result.stoppedPreviews, 1);
  assert.equal(result.restartedVideos, 1);
  assert.equal(result.ok, false);
  assert.deepEqual(calls, ['viewer', 'lightbox', 'lightbox hold', 'pine-box-gallery']);
  assert.equal(preview.src, '');
  assert.equal(preview.loads, 1);
  assert.equal(preview.loop, false);
  assert.equal(preview.autoplay, false);
  assert.equal(preview.muted, true);
  assert.equal(wall.plays, 1);
  assert.equal(wall.muted, true, 'mixer/solo decisions survive repair');
  assert.equal(paused.plays, 0);
  assert.equal(camera.loads, 0);
});

test('repair is bounded and concurrent clicks share one operation', async () => {
  const hung = video({playPromise: new Promise(() => {})});
  const w = windowFor([hung]);
  const first = repair(w, {timeoutMs: 100});
  assert.equal(repair(w), first);
  const result = await first;
  assert.equal(result.ok, false);
  assert.match(result.errors[0].error, /resume video: playback has not been verified/);
  assert.equal(hung.plays, 1);
  assert.equal(w.__pinePlaybackRecoveryPending, null);
});

test('closure-free injection works and catches late hidden H3 playback', async () => {
  const preview = video({preview: true});
  const w = windowFor([preview]);
  const context = vm.createContext({window: w, Promise, Array, Number, String});
  const result = await vm.runInContext(`(${repair.toString()})(window)`, context);
  assert.equal(result.stoppedPreviews, 1);
  preview.src = 'late.mp4'; preview.paused = false; preview.hidden = true;
  w.document.events.playing({target: preview});
  assert.equal(preview.src, '');
  assert.equal(preview.paused, true);
});

test('SFX/native repair uses the controller and does not reload its replaced decoder', async () => {
  const sfx = video(); sfx.closest = selector => selector === '#sfxTv';
  const presentation = video({id: 'pvWall'});
  let native = false; const calls = [];
  const w = windowFor([sfx, presentation], {
    PineVideoWall: {recoverAll: async () => [{ready: false, state: 'loading'}]},
    PineSfxTv: {releaseHold() { calls.push('hold'); }, nativeWallActive: () => native,
      playing: () => ({url: 'sfx.mp4'}),
      repair: async clip => { calls.push(clip.url); return {ok: true}; },
      repairEndless: async () => { calls.push('native'); return {on: true}; }},
  });
  const result = await repair(w);
  assert.equal(result.walls, 1); assert.equal(result.sfx, 1);
  assert.deepEqual(calls, ['hold', 'sfx.mp4']);
  assert.equal(sfx.loads, 0); assert.equal(presentation.loads, 0);
  native = true;
  const nativeResult = await repair(w);
  assert.equal(nativeResult.sfx, 1);
  assert.deepEqual(calls, ['hold', 'sfx.mp4', 'hold', 'native']);
});

test('PiP verifies an advancing SFX source even while its original DOM host is hidden', async () => {
  const clip = {url: 'sfx.mp4'}, media = video({readyState: 4, videoWidth: 640});
  let frames = 3;
  media.getVideoPlaybackQuality = () => ({totalVideoFrames: frames});
  const w = windowFor([media], {PineSfxTv: {playing: () => clip,
    repair: () => new Promise(() => {}), nativeWallActive: () => false}});
  w.document.body.classList.contains = () => true;
  const query = w.document.querySelectorAll;
  w.document.querySelectorAll = selector => selector === '#sfxTv .sfx-tv-tube video' ? [media] : query(selector);
  w.setTimeout = (callback, ms) => setTimeout(() => {
    if (ms === 200) { media.currentTime += .2; frames += 4; }
    callback();
  }, ms === 200 ? 1 : ms);
  const result = await repair(w, {timeoutMs: 900});
  assert.equal(result.ok, true);
  assert.equal(result.sfx, 1);
});

test('PiP keeps missing SFX frame progress as attention while independently stopping H3', async () => {
  const clip = {url: 'sfx.mp4'}, media = video({readyState: 4, videoWidth: 640});
  const preview = video({preview: true});
  const w = windowFor([media, preview], {PineSfxTv: {playing: () => clip,
    repair: () => new Promise(() => {}), nativeWallActive: () => false}});
  w.document.body.classList.contains = () => true;
  const query = w.document.querySelectorAll;
  w.document.querySelectorAll = selector => selector === '#sfxTv .sfx-tv-tube video' ? [media] : query(selector);
  w.setTimeout = (callback, ms) => setTimeout(callback, ms === 200 ? 1 : ms);
  const result = await repair(w, {timeoutMs: 900});
  assert.equal(result.ok, false);
  assert.equal(result.sfx, 0);
  assert.match(result.errors[0].error, /has not produced advancing frames/);
  assert.equal(result.stoppedPreviews, 1);
  assert.equal(preview.src, '');
});

test('video wall discards late pre-repair bytes and destroyed controllers leave the recovery registry', async () => {
  const old = deferred();
  const released = [];
  let catalogue = [{files: ['old.mp4'], ts: 1}];
  let downloads = 0;
  const wall = wallModule.create({get: () => ({generations: catalogue}),
    fetchClip: () => ++downloads === 1 ? old.promise : {src: 'new-blob', bytes: 10},
    releaseClip: clip => released.push(clip.src)});
  try {
    wall.tick(); await flush();
    assert.equal(downloads, 1);
    catalogue = [{files: ['new.mp4'], ts: 2}];
    const recovering = wall.recover();
    assert.equal(wall.recover(), recovering);
    await recovering; await flush();
    assert.equal(wall.state().file, 'new.mp4');
    old.resolve({src: 'old-blob', bytes: 10}); await flush();
    assert.equal(wall.state().file, 'new.mp4');
    assert.deepEqual(released, ['old-blob']);
  } finally { wall.destroy(); }
  assert.deepEqual(await wallModule.recoverAll(), []);
  assert.deepEqual(released, ['old-blob', 'new-blob']);
});

test('video wall network timeout releases a late blob and can fetch again', async () => {
  const old = deferred(); const released = [];
  let now = 1000, downloads = 0;
  const wall = wallModule.create({get: () => ({generations: [{files: ['clip.mp4'], ts: 1}]}),
    fetchClip: () => ++downloads === 1 ? old.promise : {src: 'fresh-blob', bytes: 10},
    releaseClip: clip => released.push(clip.src), now: () => now, requestTimeoutMs: 30});
  try {
    wall.tick(); await flush();
    await new Promise(done => setTimeout(done, 50));
    assert.match(wall.state().note, /timed out/);
    now += 61000; wall.tick(); await flush();
    assert.equal(wall.state().file, 'clip.mp4');
    old.resolve({src: 'expired-blob', bytes: 10}); await flush();
    assert.deepEqual(released, ['expired-blob']);
    assert.equal(wall.state().clip.src, 'fresh-blob');
  } finally { wall.destroy(); }
});

test('repeated wall recovery waits for replacement decoding and does not stack pending downloads', async () => {
  const download = deferred(); let downloads = 0;
  const wall = wallModule.create({get: () => ({generations: [{files: ['clip.mp4'], ts: 1}]}),
    fetchClip: () => { downloads += 1; return download.promise; }});
  try {
    const first = wall.recover(); await flush();
    assert.equal(wall.recover(), first);
    assert.equal(downloads, 1);
    download.resolve({src: 'recovered-blob', bytes: 10});
    const state = await first;
    assert.equal(state.ready, true);
    assert.equal(state.file, 'clip.mp4');
  } finally { wall.destroy(); }
});

test('switching video wall to stills drops a prefetched video and rejects late old pool results', async () => {
  const released = [];
  const wall = wallModule.create({get: () => ({generations: [
    {files: ['first.mp4', 'second.mp4', 'picture.png'], ts: 1}]}),
    fetchClip: url => ({src: url, bytes: 10}), releaseClip: clip => released.push(clip.src), random: () => 0});
  try {
    wall.tick(); await flush();
    assert.equal(wall.state().holding, 2);
    wall.setMode('stills'); wall.tick(); await flush();
    assert.equal(wall.state().kind, 'still');
    assert.equal(released.length, 2, 'both old video blobs released');
  } finally { wall.destroy(); }
});

test('ad viewer cleans failed decoder independently and failed hidden video pauses before retry', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'ad-viewer.js'), 'utf8');
  const stopSource = source.slice(source.indexOf('  function stopMedia'), source.indexOf('  function make'));
  const media = video({pauseThrows: true});
  vm.runInNewContext(stopSource + '\nstopMedia(media);', {media});
  assert.equal(media.src, ''); assert.equal(media.loads, 1);
  const failedSource = source.slice(source.indexOf('      function failed(words)'), source.indexOf('      function visibility()'));
  const status = {}; const play = {setAttribute() {}};
  const hidden = video(); hidden.style = {};
  vm.runInNewContext(failedSource + '\nfailed("No frame");', {
    gone: false, current: 1, revision: 1, isVideo: true, media: hidden,
    clearTimeout() {}, timer: 0, background() {}, play, status,
  });
  assert.equal(hidden.paused, true);
  assert.equal(hidden.style.visibility, 'hidden');
  assert.equal(status.textContent, 'No frame');
});

test('ad viewer releases audio immediately and finishes closing when its VCR transition never settles', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'ad-viewer.js'), 'utf8');
  const stopSource = source.slice(source.indexOf('  function stopMedia'), source.indexOf('  function make'));
  const closeSource = source.slice(source.indexOf('    function close(immediate)'), source.indexOf('    opened = close;'));
  const media = video({pauseThrows: true}); media.style = {visibility: 'visible'};
  let disposed = 0, removed = 0, released = 0;
  const timers = [];
  const context = vm.createContext({Promise, gone: false, revision: 0, crawl: 0, h3Timer: 0,
    pTimer: 0, exportTimer: 0, rollTag: null, posterObserver: null, posterQueue: [], opened: null,
    focusWas: null, pBackOff() {}, clearInterval() {}, clearTimeout() {},
    setTimeout(callback) { timers.push(callback); return 1; },
    stage: {querySelectorAll: () => [media], querySelector: () => media},
    root: {PineVcr: {out: () => new Promise(() => {})}},
    disposeMedia() { disposed += 1; }, veil: {remove() { removed += 1; }},
    duckApi: {release() { released += 1; }},
    document: {getElementById: () => null, removeEventListener() {}}, keys() {},
  });
  vm.runInContext(stopSource + closeSource + '\nclose(); close();', context);
  assert.equal(media.src, '');
  assert.equal(released, 1);
  assert.equal(removed, 0);
  timers[0](); timers[0]();
  assert.equal(disposed, 1);
  assert.equal(removed, 1);
});
