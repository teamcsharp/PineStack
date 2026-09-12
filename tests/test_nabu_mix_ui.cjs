const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/renderer.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function harness() {
  const calls = [], notes = [], timers = new Map(), persisted = [];
  let timerId = 0, handler;
  let serverRouting;
  const sliders = Object.fromEntries(['music', 'voice', 'reply'].map(stream => ['vol_' + stream,
    {value: '100', dataset: {}, title: '', parentElement: {classList: {toggle() {}}}}]));
  const context = {
    lastRouting: {voice_device: 'nabu', music_to: 'box', voice_to: 'box', reply_to: 'box',
      box_talk: true, music_control: false, nabu_music_level: 1, nabu_voice_level: 1, nabu_reply_level: 1},
    appVolume: .72, physicalVolume: .84,
    $: id => sliders[id] || null,
    document: {activeElement: null},
    localStorage: {getItem() { return null; }, setItem(key, value) { persisted.push({key, value}); }},
    applyAppVolume() {}, desktopMusicGain() { return 1; },
    streamRoute: stream => context.lastRouting[stream + '_to'],
    noteRouteOk: message => notes.push({ok: message}),
    noteRouteError: message => notes.push({error: message}),
    paintStreamRoutes() {}, syncBroadcastFromServer() {}, rerouteAudioNow() {},
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, {fn, delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    api: {async post(url, body) {
      calls.push({url, body: plain(body)});
      if (handler) return handler(url, body);
      const routing = {...serverRouting};
      for (const stream of ['music', 'voice', 'reply']) {
        if (body[stream + '_level'] !== undefined) routing['nabu_' + stream + '_level'] = body[stream + '_level'];
      }
      serverRouting = routing;
      return {routing};
    }},
  };
  serverRouting = {...context.lastRouting};
  vm.createContext(context);
  const section = (start, end) => {
    const at = source.indexOf(start), to = source.indexOf(end, at);
    assert.ok(at >= 0 && to > at, `Actual renderer section ${start} exists`);
    vm.runInContext(source.slice(at, to), context);
  };
  section('const STREAM_VOL_IDS =', '/* #988/#984:');
  section('function initStreamVolumes(', '/* Paint the three pickers');
  section('function acceptRoutingResponse(', 'function initStreamRoutes(');
  context.initStreamVolumes();
  return {context, sliders, calls, notes, persisted,
    handler(fn) { handler = fn; },
    async flush() {
      const queued = [...timers.values()]; timers.clear();
      for (const timer of queued.sort((a, b) => a.delay - b.delay)) timer.fn();
      await new Promise(setImmediate);
    },
    input(stream, value) {
      const slider = sliders['vol_' + stream]; slider.value = String(value);
      slider.oninput({target: slider});
    },
    values() { return plain(vm.runInContext('streamVolumes', context)); },
  };
}

test('actual Music slider sends zero and no physical master or speech fields', async () => {
  const h = harness();
  h.input('music', 60); h.input('music', 30); h.input('music', 0);
  await h.flush();
  assert.deepEqual(h.calls, [{url: '/api/dj/output', body: {music_level: 0}}]);
  assert.equal(h.values().music, 0);
  assert.equal(h.context.appVolume, .72);
  assert.equal(h.context.physicalVolume, .84);
  assert.equal(h.context.lastRouting.music_control, false);
});

test('actual DJ and Reply sliders have independently debounced exact API fields', async () => {
  const h = harness();
  h.input('voice', 75); h.input('reply', 0); h.input('voice', 95);
  await h.flush();
  assert.deepEqual(h.calls.map(c => c.body), [{reply_level: 0}, {voice_level: .95}]);
  assert.ok(h.calls.every(c => !Object.hasOwn(c.body, 'music_level') && !Object.hasOwn(c.body, 'music_control')));
  assert.equal(h.context.lastRouting.nabu_voice_level, .95);
  assert.equal(h.context.lastRouting.nabu_reply_level, 0);
});

test('server painting restores all saved digital levels without POST or persistence', async () => {
  const h = harness();
  h.context.acceptRoutingResponse({routing: {voice_to: 'box', music_to: 'box', reply_to: 'both',
    voice_device: 'nabu', nabu_music_level: 0, nabu_voice_level: .9, nabu_reply_level: .4}});
  await h.flush();
  assert.deepEqual(h.values(), {music: 0, voice: .9, reply: .4});
  assert.deepEqual(h.calls, []);
  assert.deepEqual(h.persisted, []);
  assert.equal(h.context.appVolume, .72);
  assert.equal(h.context.physicalVolume, .84);
  assert.equal(h.context.lastRouting.music_control, false);
  assert.match(h.sliders.vol_music.title, /Zero gives you DJs only/);
  assert.match(h.sliders.vol_voice.title, /50% is the recorded level/);
});

test('painting does not move the focused slider or paint invalid/missing levels', async () => {
  const h = harness();
  h.context.document.activeElement = h.sliders.vol_voice;
  h.context.paintNabuMix({...h.context.lastRouting, nabu_voice_level: .2, nabu_reply_level: -1, nabu_music_level: undefined});
  await h.flush();
  assert.deepEqual(h.values(), {music: 1, voice: 1, reply: 1});
  assert.deepEqual(h.calls, []);
});

test('failed Music POST can retry the identical zero value', async () => {
  const h = harness();
  let attempt = 0;
  h.handler(() => { if (++attempt === 1) throw Error('Temporary failure'); return {routing: h.context.lastRouting}; });
  h.input('music', 0); await h.flush();
  assert.match(h.notes.at(-1).error, /Temporary failure/);
  h.input('music', 0); await h.flush();
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls[1].body, {music_level: 0});
});

test('reported application failure allows identical DJ level retry without music writes', async () => {
  const h = harness();
  let attempt = 0;
  h.handler(() => ++attempt === 1 ? {mix_applied: {voice: {ok: false, why: 'Clip gain unavailable'}}}
    : {routing: {...h.context.lastRouting, nabu_voice_level: .8}});
  h.input('voice', 80); await h.flush();
  assert.match(h.notes.at(-1).error, /Clip gain unavailable/);
  h.input('voice', 80); await h.flush();
  assert.deepEqual(h.calls.map(c => c.body), [{voice_level: .8}, {voice_level: .8}]);
});

test('App-only routes and non-Nabu replies do not send hardware levels', async () => {
  const h = harness();
  h.context.lastRouting.music_to = 'here';
  h.context.lastRouting.voice_to = 'off';
  h.context.lastRouting.voice_device = 'pine';
  h.input('music', 0); h.input('voice', 50); h.input('reply', 80);
  await h.flush();
  assert.deepEqual(h.calls, []);
});

test('Nabu music zero clears old playback even after routing to App', async () => {
  const h = harness();
  h.context.lastRouting.music_to = 'here';
  h.input('music', 50);
  await h.flush();
  assert.deepEqual(h.calls, []);
  h.input('music', 0);
  await h.flush();
  assert.deepEqual(h.calls, [{url: '/api/dj/output', body: {music_level: 0}}]);
  assert.equal(h.context.appVolume, .72);
  assert.equal(h.context.physicalVolume, .84);
});

test('route and device changes cancel delayed nonzero music writes', async () => {
  const h = harness();
  h.input('music', 50);
  h.context.lastRouting.music_to = 'here';
  await h.flush();
  assert.deepEqual(h.calls, []);
  h.context.lastRouting.music_to = 'box';
  h.input('music', 0);
  h.context.lastRouting.voice_device = 'pine';
  await h.flush();
  assert.deepEqual(h.calls, []);
});

test('speech zero reaches owned Nabu audio on App routes and reports active silence', async () => {
  const h = harness();
  h.context.lastRouting.voice_to = 'here';
  h.context.lastRouting.reply_to = 'here';
  h.handler((_url, body) => ({routing: h.context.lastRouting,
    mix_applied: {[Object.hasOwn(body, 'voice_level') ? 'voice' : 'reply']:
      {ok: true, applies: 'active spoken clip'}}}));
  h.input('voice', 0); h.input('reply', 0);
  await h.flush();
  assert.deepEqual(h.calls.map(c => c.body), [{voice_level: 0}, {reply_level: 0}]);
  assert.match(h.notes.at(-1).ok, /active clip silenced/);
  assert.equal(h.context.physicalVolume, .84);
});

test('a level used earlier can be requested again after another client changes it', async () => {
  const h = harness();
  h.input('music', 20); h.input('voice', 70); await h.flush();
  h.context.acceptRoutingResponse({routing: {...h.context.lastRouting, nabu_music_level: .6, nabu_voice_level: .3}});
  h.input('music', 20); h.input('voice', 70); await h.flush();
  assert.equal(h.calls.filter(c => c.body.music_level === .2).length, 2);
  assert.equal(h.calls.filter(c => c.body.voice_level === .7).length, 2);
});
