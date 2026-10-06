const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const app = fs.readFileSync(path.join(__dirname, '../app.py'), 'utf8');
const radio = app.slice(app.indexOf('RADIO_PAGE_HTML ='), app.indexOf('/* System 3 (docs/system3_blueprint.md): THE FEED', app.indexOf('RADIO_PAGE_HTML =')));
const start = radio.indexOf('let tvNow = null;');
const source = radio.slice(start);

function shippedFunction(name) {
  const begin = app.indexOf('function ' + name + '(');
  assert.ok(begin >= 0, name);
  let cursor = app.indexOf('{', begin), depth = 0;
  for (; cursor < app.length; cursor++) {
    if (app[cursor] === '{') depth++;
    else if (app[cursor] === '}' && --depth === 0) return app.slice(begin, cursor + 1);
  }
  throw new Error('unclosed function ' + name);
}

function nativeUrlFunctions() {
  return ['signedListenToken', 'streamToken', 'streamUrl'].map(shippedFunction).join('\n');
}

test('the complete listener main script parses', () => {
  const open = radio.indexOf('<script>') + '<script>'.length;
  // The tv excerpt ends before </script>; use the full HTML literal here.
  const full = app.slice(app.indexOf('RADIO_PAGE_HTML ='));
  const end = full.indexOf('</script>', open);
  assert.ok(end > open);
  new vm.Script(full.slice(open, end));
});

class Classes {
  constructor() { this.items = new Set(); }
  add(...items) { items.forEach(x => this.items.add(x)); }
  remove(...items) { items.forEach(x => this.items.delete(x)); }
  contains(x) { return this.items.has(x); }
}

function harness(options = {}) {
  let clock = 100000, serial = 0;
  const timers = new Map(), elements = [], requests = [];
  class Video {
    constructor(id) {
      this.id = id; this.listeners = new Map(); this.classList = new Classes();
      this.style = {}; this.src = ''; this.loads = 0; this.plays = 0; this.paused = true;
      this.readyState = 0; this.duration = 60; this.videoWidth = 640; this.ended = false;
      this.position = 0; this.seeks = [];
    }
    get currentTime() { return this.position; }
    set currentTime(value) {
      assert.ok(this.readyState >= 1, 'seek requires metadata');
      this.position = value; this.seeks.push(value);
    }
    addEventListener(name, fn, opts) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push({fn, once: opts && opts.once});
    }
    removeEventListener(name, fn) {
      this.listeners.set(name, (this.listeners.get(name) || []).filter(x => x.fn !== fn));
    }
    emit(name) {
      for (const entry of [...(this.listeners.get(name) || [])]) {
        if (entry.once) this.removeEventListener(name, entry.fn);
        entry.fn();
      }
    }
    load() { this.loads++; }
    setAttribute() {}
    removeAttribute(name) { if (name === 'src') this.src = ''; }
    pause() { this.paused = true; }
    play() {
      this.plays++;
      if (options.playError) return Promise.reject(options.playError);
      this.paused = false;
      return Promise.resolve();
    }
  }
  function simple(id) {
    const el = {id, classList: new Classes(), style: {}, textContent: '', hidden: true,
      addEventListener() {}, removeEventListener() {}};
    elements.push(el); return el;
  }
  ['galleryStage', 'galleryImage', 'galleryCaption', 'tvState', 'tvRetry'].forEach(simple);
  elements.push(new Video('galleryVideo'), new Video('galleryVideoNext'));
  const document = {hidden: false, getElementById: id => elements.find(el => el.id === id)};
  const context = {document, window: {}, location: {href: 'http://station/radio?t=secret', origin: 'http://station'},
    URL, Date: {now: () => clock}, Math, Number, String, Map, Promise, isFinite,
    streamMode: false, radio: null, sfxLevel: .6, playing: true, wantsHls: () => false,
    setTimeout: (fn, ms) => { const id = ++serial; timers.set(id, {fn, at: clock + ms}); return id; },
    clearTimeout: id => timers.delete(id),
    api: async url => { requests.push(url); return options.feed || {server_ms: clock, clips: []}; }};
  vm.createContext(context);
  vm.runInContext(source, context);
  const run = code => vm.runInContext(code, context);
  async function flush() { await new Promise(resolve => setImmediate(resolve)); }
  async function advance(ms) {
    const until = clock + ms;
    for (;;) {
      const pending = [...timers].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!pending) break;
      clock = pending[1].at; timers.delete(pending[0]); pending[1].fn(); await flush();
    }
    clock = until; await flush();
  }
  return {context, document, elements, requests, run, flush, advance,
    video: () => document.getElementById('galleryVideo'),
    next: () => document.getElementById('galleryVideoNext'),
    cue: (at = 100000, seconds = 2, url = '/sfx/clip?t=secret') => ({url, name: 'test clip', broadcast_ms: at, seconds}),
    setClock: value => {clock = value;}, timers};
}

test('a retained runway starts every short clip between 2.5-second polls', async () => {
  const h = harness();
  const cues = [h.cue(100100, .8, '/sfx/a'), h.cue(100900, .8, '/sfx/b'), h.cue(101700, .8, '/sfx/c')];
  h.context.api = async () => ({server_ms: 100000, clips: cues});
  await h.context.tvPoll();
  assert.equal(h.run('tvNow'), null);
  await h.advance(200); assert.equal(h.run('tvActive.v.url'), '/sfx/a');
  await h.advance(800); assert.equal(h.run('tvActive.v.url'), '/sfx/b');
  await h.advance(800); assert.equal(h.run('tvActive.v.url'), '/sfx/c');
});

test('the same file aired twice gets two distinct playback lifecycles', async () => {
  const h = harness();
  const cues = [h.cue(100000, .8), h.cue(100800, .8)];
  h.context.api = async () => ({server_ms: 100000, clips: cues});
  await h.context.tvPoll(); const first = h.run('tvNow');
  await h.advance(800);
  assert.notEqual(h.run('tvNow'), first);
  assert.equal(h.run('tvActive.v.broadcast_ms'), 100800);
});

test('metadata arrives before initial seek and a cut preserves its media offset', async () => {
  const h = harness(); const cue = {...h.cue(98000, 10), seek: 4};
  h.context.tvShow(cue, 2);
  assert.deepEqual(h.video().seeks, []);
  h.video().readyState = 1; h.video().emit('loadedmetadata');
  assert.equal(h.video().currentTime, 6);
  h.video().readyState = 2; h.video().emit('playing'); await h.flush();
  assert.equal(h.video().style.visibility, '');
});

test('blank poll keeps an airing, and stream audio lag selects the audible clip', async () => {
  const h = harness(); const cue = h.cue(69000, 5);
  h.context.streamMode = true;
  h.context.radio = {paused: false, ended: false, currentTime: 1, buffered: {length: 0}};
  h.run('tvBurst=30; streamStartMs=100000;');
  h.context.api = async () => ({server_ms: 100000, burst_s: 30, clips: [cue]});
  await h.context.tvPoll();
  const active = h.run('tvNow'); assert.ok(active);
  assert.equal(h.video().muted, true); assert.equal(h.video().volume, 0);
  h.context.api = async () => ({server_ms: 100000, clips: []});
  await h.context.tvPoll(); assert.equal(h.run('tvNow'), active);
  assert.match(h.requests[0] || '/api/dj/video?lag=30', /lag=30/);
});

test('browser source preserves the access token and gain query', () => {
  const h = harness();
  assert.equal(h.context.tvSource(h.cue(100000, 2, '/sfx/clip?t=secret&gain=0.6')),
    '/sfx/clip?t=secret&gain=0.6&video=browser');
  assert.equal(h.context.tvSource(h.cue(100000, 2, 'https://external/clip.webm')), 'https://external/clip.webm');
});

for (const hls of [false, true]) {
  test(`private radio authenticates native ${hls ? 'HLS' : 'MP3'} without placing the operator key in its URL`, () => {
    const h = harness();
    Object.assign(h.context, {GUEST: false, KEY: 'operator-secret', MEDIA_TOKEN: '1800000000.aabb.ccdd',
      voiceRate: 96, wantsHls: () => hls, tuneTab: () => 'my-tab', personalMix: () => '20,100,60'});
    vm.runInContext(nativeUrlFunctions(), h.context);
    const url = new URL(h.context.streamUrl(), 'http://station');
    assert.equal(url.pathname, hls ? '/stream.m3u8' : '/stream.mp3');
    assert.equal(url.searchParams.get('t'), '1800000000.aabb.ccdd');
    assert.ok(!url.href.includes('operator-secret'));
    assert.equal(url.searchParams.get('br'), hls ? null : '96');
    assert.equal(url.searchParams.get('who'), hls ? 'my-tab' : null);
    assert.equal(url.searchParams.get('mix'), hls ? '20,100,60' : null);
  });

  test(`shared native ${hls ? 'HLS' : 'MP3'} preserves the guest's signed capability`, () => {
    const h = harness();
    Object.assign(h.context, {GUEST: true, KEY: '1800000000.1122.3344.full', MEDIA_TOKEN: '',
      voiceRate: 64, wantsHls: () => hls, tuneTab: () => 'guest-tab', personalMix: () => '30,80,20'});
    vm.runInContext(nativeUrlFunctions(), h.context);
    const url = new URL(h.context.streamUrl(), 'http://station');
    assert.equal(url.searchParams.get('t'), '1800000000.1122.3344.full');
    assert.equal(url.searchParams.get('br'), hls ? null : '64');
  });
}

test('tailnet mode never mistakes an operator key for a signed media capability', () => {
  const h = harness();
  Object.assign(h.context, {AWAY: true, GUEST: true, KEY: 'operator-secret', MEDIA_TOKEN: '1800000000.aabb.ccdd',
    voiceRate: 96, wantsHls: () => false});
  vm.runInContext(nativeUrlFunctions(), h.context);
  const url = new URL(h.context.streamUrl(), 'http://station');
  assert.equal(url.searchParams.get('t'), '1800000000.aabb.ccdd');
  assert.ok(!url.href.includes('operator-secret'));
});

test('guest authentication follows signed credentials on every road, including full links', () => {
  const expression = radio.match(/const GUEST = (.+);/)[1];
  for (const [key, guest] of [['operator-secret', false], ['1800000000.aabb.ccdd', true],
    ['1800000000.aabb.ccdd.full', true], ['', false]]) {
    const h = harness(); Object.assign(h.context, {KEY: key, AWAY: true});
    assert.equal(vm.runInContext(expression, h.context), guest);
  }
});

function nativeAuth(h, options = {}) {
  const el = {src: '', currentSrc: '', currentTime: 0, paused: true, plays: 0,
    getAttribute() {return this.src;}, pause() {this.paused=true;},
    play() {this.plays++; return Promise.resolve();}};
  const calls = [], plays = [];
  Object.assign(h.context, {GUEST: !!options.guest, KEY: options.key || 'operator-secret',
    MEDIA_TOKEN: options.token || '', streamMode: true, radio: el,
    streamPlaySerial: 0, streamSrcAt: 0, streamResumeAt: 0, streamAt: -1, streamAtSince: 0,
    voiceRate: 96, wantsHls: () => false, streamElement: () => el,
    requestStreamPlay: (_, why) => plays.push({url: el.src, why}), streamRecover: why => calls.push(why)});
  const begin = app.indexOf('function streamUrl('), end = app.indexOf('/* #1264: the driving layout', begin);
  vm.runInContext(app.slice(begin, end) + '\n' + shippedFunction('replaceStreamSource'), h.context);
  return {el, calls, plays};
}

test('operator capability renewal preserves the first gesture and coalesces repeated starts', async () => {
  const h = harness(), audio = nativeAuth(h); let answer, requests = 0;
  h.context.api = uri => {
    assert.equal(uri, '/api/listener/media-token'); requests++;
    return new Promise(resolve => {answer=resolve;});
  };
  h.context.replaceStreamSource('first gesture');
  assert.equal(audio.el.plays, 1, 'the same radio element is unlocked before awaiting authentication');
  assert.equal(audio.plays.length, 0, 'no unauthorized native URL is opened');
  h.context.replaceStreamSource('latest start');
  assert.equal(requests, 1);
  answer({token: '1800000000.aabb.ccdd'}); await h.flush();
  assert.equal(audio.plays.length, 1);
  assert.equal(audio.plays[0].why, 'latest start');
  assert.equal(new URL(audio.plays[0].url, 'http://station').searchParams.get('t'), '1800000000.aabb.ccdd');
  assert.ok(!audio.plays[0].url.includes('operator-secret'));
});

test('Stop cancels an in-flight operator media authorization', async () => {
  const h = harness(), audio = nativeAuth(h); let answer;
  h.context.api = () => new Promise(resolve => {answer=resolve;});
  h.context.replaceStreamSource('start');
  h.context.playing = false; h.context.streamPlaySerial++;
  answer({token: '1800000000.aabb.ccdd'}); await h.flush();
  assert.equal(audio.plays.length, 0);
  assert.equal(audio.el.src, '');
});

test('an expired operator capability renews while signed guests never extend their link', async () => {
  for (const guest of [false, true]) {
    const h = harness(), audio = nativeAuth(h, {guest, token: '1.aabb.ccdd',
      key: guest ? '1.1122.3344.full' : 'operator-secret'});
    let requests = 0;
    h.context.api = async () => {requests++; return {token: '1800000000.aabb.ccdd'};};
    h.context.replaceStreamSource('retry'); await h.flush();
    assert.equal(requests, guest ? 0 : 1);
    assert.equal(audio.plays.length, 1);
  }
});

test('an open-auth page with no operator key starts without requesting empty credentials', () => {
  const h = harness(), audio = nativeAuth(h);
  h.context.KEY = '';
  h.context.api = () => {throw new Error('empty credentials must not request a capability');};
  h.context.replaceStreamSource('open station');
  assert.equal(audio.plays.length, 1);
  assert.equal(new URL(audio.plays[0].url, 'http://station').searchParams.get('t'), null);
});

test('an unsigned private page never leaks its operator key through native media', () => {
  const h = harness();
  Object.assign(h.context, {GUEST: false, KEY: 'operator-secret', MEDIA_TOKEN: '', voiceRate: 96,
    wantsHls: () => false});
  vm.runInContext(nativeUrlFunctions(), h.context);
  const url = new URL(h.context.streamUrl(), 'http://station');
  assert.equal(url.searchParams.get('t'), null);
  assert.ok(!url.href.includes('operator-secret'));
});

test('autoplay rejection is visible and a user gesture retries the same airing', async () => {
  const options = {playError: Object.assign(new Error('blocked'), {name: 'NotAllowedError'})};
  const h = harness(options); h.context.tvShow(h.cue(), 0); await h.flush();
  assert.equal(h.run('tvActive.blocked'), true);
  assert.equal(h.document.getElementById('tvRetry').hidden, false);
  assert.match(h.document.getElementById('tvState').textContent, /tap Play video/);
  options.playError = null; h.video().readyState = 2;
  h.context.tvUserPlay(); await h.flush();
  assert.equal(h.video().paused, false);
  assert.equal(h.document.getElementById('tvRetry').hidden, true);
});

test('a decoded first frame cannot claim playback after autoplay was refused', async () => {
  const options = {playError: Object.assign(new Error('blocked'), {name: 'NotAllowedError'})};
  const h = harness(options); h.context.tvShow(h.cue(), 0); await h.flush();
  h.video().readyState = 2; h.video().emit('loadeddata');
  assert.match(h.document.getElementById('tvState').textContent, /tap Play video/);
  assert.equal(h.video().style.visibility, 'hidden');
});

test('the decoder watchdog recovers even when synchronization seeks move its playhead', async () => {
  const h = harness();
  h.context.api = async () => ({server_ms: 100000, clips: [h.cue(100000, 20)]});
  await h.context.tvPoll();
  h.video().readyState = 3;
  h.video().getVideoPlaybackQuality = () => ({totalVideoFrames: 1});
  h.video().emit('loadedmetadata'); h.video().emit('playing'); await h.flush();
  const before = h.video().loads;
  await h.advance(4900);
  assert.ok(h.video().loads > before, 'stuck decoded frames trigger a reload');
});

test('withdrawal and a queue cut remove retained schedules before they can play', async () => {
  const h = harness(); const a = {...h.cue(101000, 2, '/sfx/a'), sfx_id: 'dead', ts: 90000};
  const b = {...h.cue(105000, 2, '/sfx/b'), sfx_id: 'alive', ts: 91000};
  h.context.api = async () => ({server_ms: 100000, clips: [a, b]});
  await h.context.tvPoll(); assert.equal(h.run('tvQueue.size'), 2);
  h.context.api = async () => ({server_ms: 100000, clips: [a], withdrawn: ['dead']});
  await h.context.tvPoll(); assert.equal(h.run('tvQueue.size'), 1);
  h.context.api = async () => ({server_ms: 100000, clips: [], cut_ms: 91000});
  await h.context.tvPoll(); assert.equal(h.run('tvQueue.size'), 0);
  await h.advance(6000); assert.equal(h.run('tvActive'), null);
});

test('withdrawal pauses the active picture and releases the warmed next decoder', async () => {
  const h = harness();
  const a = {...h.cue(100000, 2, '/sfx/a'), sfx_id: 'dead'};
  const b = {...h.cue(102000, 2, '/sfx/b'), sfx_id: 'also-dead'};
  h.context.api = async () => ({server_ms: 100000, clips: [a, b]});
  await h.context.tvPoll(); await h.flush();
  assert.ok(h.run('tvActive')); assert.ok(h.run('tvWarm'));
  const before = h.video();
  h.context.api = async () => ({server_ms: 100000, clips: [], withdrawn: ['dead', 'also-dead']});
  await h.context.tvPoll();
  assert.equal(before.paused, true); assert.equal(h.run('tvActive'), null);
  assert.equal(h.run('tvWarm'), null); assert.equal(h.next().src, '');
});

test('a response from before Stop or a mode change cannot replace the new queue', async () => {
  const h = harness(); let answer;
  h.context.api = () => new Promise(resolve => {answer = resolve;});
  const old = h.context.tvPoll(); h.context.tvStop();
  h.context.api = async () => ({server_ms: 100000, burst_s: 30, clips: [h.cue(100000, 10, '/sfx/new')]});
  await h.context.tvPoll();
  answer({server_ms: 80000, burst_s: 90, clips: [h.cue(100000, 10, '/sfx/old')]});
  await old;
  assert.equal(h.run('tvBurst'), 30);
  assert.equal(h.run('tvSkew'), 0);
  assert.equal(h.run('tvActive.v.url'), '/sfx/new');
  assert.equal(h.run('tvQueue.size'), 1);
});

test('audio-only decoded media never claims that the picture is showing', async () => {
  const h = harness(); h.context.tvShow(h.cue(100000, 20), 0);
  h.video().readyState = 2; h.video().videoWidth = 0; h.video().emit('loadeddata'); await h.flush();
  assert.equal(h.video().style.visibility, 'hidden');
  assert.match(h.document.getElementById('tvState').textContent, /retrying video/);
});

test('network/decode retries are bounded and the next cue still starts', async () => {
  const h = harness(); const a = h.cue(100000, 10, '/sfx/a');
  h.context.api = async () => ({server_ms: 100000, clips: [a, h.cue(110000, 5, '/sfx/b')]});
  await h.context.tvPoll();
  for (let i = 0; i < 4; i++) { h.video().emit('error'); await h.advance(1100); }
  assert.equal(h.run('tvActive.failed'), true);
  assert.equal(h.run('tvActive.retries'), 3);
  assert.match(h.document.getElementById('tvState').textContent, /video unavailable/);
  await h.advance(6000);
  assert.equal(h.run('tvActive.v.url'), '/sfx/b');
  assert.equal(h.run('tvActive.failed || false'), false);
});

test('promotion and stop remove stale listeners, pending retries and sources', async () => {
  const h = harness(); h.context.tvShow(h.cue(100000, 20, '/sfx/a'), 0);
  const previous = h.video(); previous.emit('error');
  h.context.tvShow(h.cue(100000, 20, '/sfx/b'), 0);
  assert.equal([...previous.listeners.values()].reduce((sum, items) => sum + items.length, 0), 9);
  const key = h.run('tvNow'); await h.advance(1200);
  assert.equal(h.run('tvNow'), key);
  assert.match(h.video().src, /\/sfx\/b/);
  h.context.tvStop();
  assert.equal(h.run('tvNow'), null); assert.equal(h.run('tvQueue.size'), 0);
  assert.equal(h.run('tvActive'), null); assert.equal(h.run('tvWarm'), null);
  assert.equal([...h.video().listeners.values()].reduce((sum, items) => sum + items.length, 0), 0);
  assert.equal(h.video().src, '');
});

test('warming a future cue keeps the sounding video intact and swaps decoders', async () => {
  const h = harness(); h.context.tvShow(h.cue(100000, 10, '/sfx/a'), 0);
  const active = h.video(); h.context.tvWarmNext(h.cue(110000, 10, '/sfx/b')); await h.flush();
  assert.equal(h.video(), active); assert.equal(active.paused, false);
  const warm = h.next(); warm.readyState = 2;
  h.setClock(110000); h.context.tvShow(h.cue(110000, 10, '/sfx/b'), 0); await h.flush();
  assert.equal(h.video(), warm); assert.equal(h.next(), active);
  assert.equal(active.src, ''); assert.equal(warm.paused, false);
  assert.equal([...active.listeners.values()].reduce((sum, items) => sum + items.length, 0), 0);
});

test('promotion preserves an offset seek still decoding the first short frame', async () => {
  const h = harness(); const cue = {...h.cue(100700, .8), from: .3};
  h.context.tvWarmNext(cue); const warm = h.next();
  warm.readyState = 1; warm.emit('loadedmetadata');
  assert.equal(warm.currentTime, .3); assert.equal(warm.seeks.length, 1);
  warm.seeking = true;
  warm.emit('loadeddata'); await h.flush();
  assert.equal(warm.paused, false, 'an unfinished warm seek must keep decoding');
  h.setClock(100850); h.context.tvShow(cue, .15);
  assert.equal(h.video(), warm); assert.equal(warm.seeks.length, 1);
  h.context.tvSeek(h.run('tvActive'), true);
  assert.equal(warm.seeks.length, 1, 'promotion must not replace the pending seek');
  warm.readyState = 3; warm.seeking = false; warm.emit('seeked'); await h.flush();
  assert.equal(warm.style.visibility, '');
  assert.equal(warm.seeks.length, 1, 'the primed offset survives first-frame readiness');
});

test('duplicate metadata and ready events do not submit the initial seek twice', () => {
  const h = harness(); h.context.tvShow({...h.cue(98000, 10), from: .6}, 2);
  const el = h.video(); el.readyState = 1; el.emit('loadedmetadata');
  const count = el.seeks.length; assert.equal(count, 1);
  el.emit('loadedmetadata'); el.readyState = 3; el.emit('loadeddata'); el.emit('canplay');
  assert.equal(el.seeks.length, count);
});

test('a held stream freezes its picture and resumes when the audio moves', async () => {
  const h = harness(); h.context.streamMode = true;
  h.context.radio = {paused: true, ended: false, currentTime: 0, buffered: {length: 0}};
  h.context.api = async () => ({server_ms: 100000, clips: [h.cue(100000, 10)]});
  await h.context.tvPoll(); await h.flush();
  assert.equal(h.video().paused, true);
  h.context.radio.paused = false; h.context.radio.currentTime = .2;
  await h.advance(200);
  assert.equal(h.video().paused, false);
});

test('HLS starts at a nonzero timeline and retained pauses add to its video lag', () => {
  const h = harness(); h.context.streamMode = true;
  h.context.radio = {currentTime: 600, buffered: {length: 1, end: () => 607}};
  h.run('tvBurst=45; streamStartMs=100000; streamStartPosition=600;');
  assert.equal(h.context.tvLagSeconds(), 45);
  h.setClock(110000); h.context.radio.currentTime = 605;
  assert.equal(h.context.tvLagSeconds(), 50, 'five stalled seconds stay with the socket');
  h.context.radio.currentTime = 625;
  assert.equal(h.context.tvLagSeconds(), 30, 'a live-edge catchup seek reduces audio lag');
});

test('replacing a stream source clears its clock and first playing seeds the new timeline', () => {
  const h = harness();
  function extract(name) {
    const begin = app.indexOf('function ' + name + '(');
    const next = app.indexOf('\nfunction ', begin + 1);
    return app.slice(begin, next);
  }
  const el = {currentTime: 800, paused: false, src: '', pause() {this.paused=true;},
    preload: '', dataset: {}, style: {}, setAttribute() {}};
  h.context.streamMode = true; h.context.radio = null;
  h.context.Audio = function() {return el;}; h.document.body = {appendChild() {}};
  Object.assign(h.context, {streamTries: 0, streamTimer: null, streamAt: -1, streamAtSince: 0,
    streamPlaySerial: 0, streamSrcAt: 0, streamResumeAt: 0, streamRecover() {},
    streamUrl: () => '/api/stream/hls.m3u8', streamTokenNeedsRefresh: () => false, requestStreamPlay() {}});
  vm.runInContext(extract('streamElement') + '\n' + extract('replaceStreamSource'), h.context);
  h.run('streamStartMs=90000; streamStartPosition=100;');
  h.context.replaceStreamSource('reconnect');
  assert.equal(h.run('streamStartMs'), 0); assert.equal(h.run('streamStartPosition'), 0);
  el.paused = false; el.onplaying();
  assert.equal(h.run('streamStartMs'), 100000); assert.equal(h.run('streamStartPosition'), 800);
  h.setClock(105000); el.currentTime = 801; el.onplaying();
  assert.equal(h.run('streamStartMs'), 100000, 'resume preserves the original wall clock');
  assert.equal(h.run('streamStartPosition'), 800);
});
