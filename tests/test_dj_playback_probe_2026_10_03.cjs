const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {probeDjSpeech} = require('../desktop/renderer/dj-playback-probe.js');

function fixture(options = {}) {
  let clock = 0, graphTime = 0;
  const voice = {id: 'djVoiceAudio0', dataset: {pineLive: 'voice'}, paused: false,
    ended: false, muted: false, volume: .6, currentTime: 0, currentSrc: 'line.mp3',
    readyState: 4, isConnected: true, ...options.player};
  const music = {id: 'musicPlayer', dataset: {pineLive: 'music'}, paused: false,
    muted: false, volume: 1, currentTime: 50, currentSrc: 'song.mp3', readyState: 4};
  const players = options.musicOnly ? [music] : [voice, music];
  const ctx = {state: options.graphState || 'running', get currentTime() { return graphTime; }};
  const w = {document: {querySelectorAll(selector) { assert.equal(selector, 'audio'); return players; }},
    Date: {now: () => clock}, pineAudioCtx: ctx,
    pineLevelGateState: () => ({open: options.gateOpen !== false}),
    __pineDesktopAudible: options.desktopAudible !== false,
    setTimeout(callback, ms) {
      clock += ms;
      if (!options.frozenGraph && ctx.state === 'running') graphTime += ms / 1000;
      music.currentTime += ms / 1000;
      if (!options.frozenPlayer && !voice.paused) voice.currentTime += ms / 1000;
      if (options.changeSource) voice.currentSrc = 'new-line-' + clock + '.mp3';
      if (options.startAfter && clock >= options.startAfter) voice.paused = false;
      Promise.resolve().then(callback);
      return 1;
    }};
  return {w, voice};
}

test('closure-free injected speech probe verifies actual voice/reply time and audio graph progress', async () => {
  const {w} = fixture({player: {dataset: {pineLive: 'reply'}}});
  const context = vm.createContext({window: w});
  const result = await vm.runInContext(`(${probeDjSpeech.toString()})(window,{timeoutMs:1000})`, context);
  assert.equal(result.verified, true);
  assert.equal(result.proof.kind, 'reply');
  assert.equal(result.proof.id, 'djVoiceAudio0');
  assert.ok(result.proof.advanced >= .08 && result.proof.graphAdvanced >= .08);
  assert.equal(result.proof.graph, 'running');
});

test('music output and a legitimate reply gap do not verify DJ speech', async () => {
  for (const options of [{musicOnly: true}, {player: {paused: true}}]) {
    const result = await probeDjSpeech(fixture(options).w, {timeoutMs: 1000});
    assert.equal(result.verified, false);
    assert.equal(result.reason, 'waiting');
    assert.match(result.say, /Waiting for the next line/);
    assert.equal(result.elapsedMs, 1000);
  }
});

test('suspended/frozen graph, stalled player and changing sources cannot produce speech proof', async () => {
  for (const options of [{graphState: 'suspended'}, {frozenGraph: true}, {frozenPlayer: true}, {changeSource: true}]) {
    const result = await probeDjSpeech(fixture(options).w, {timeoutMs: 1000});
    assert.equal(result.verified, false);
    assert.ok(['blocked', 'stalled'].includes(result.reason));
  }
});

test('muted, gagged, zero-volume and closed output-gate speech cannot verify', async () => {
  for (const options of [{player: {muted: true}}, {player: {volume: 0}},
    {player: {dataset: {pineLive: 'voice', pineGag: '1'}}},
    {player: {dataset: {pineLive: 'voice', pineShellMuted: '1'}}},
    {gateOpen: false}, {desktopAudible: false}]) {
    const result = await probeDjSpeech(fixture(options).w, {timeoutMs: 1000});
    assert.equal(result.verified, false);
    assert.equal(result.reason, 'blocked');
  }
});

test('SFX stingers, warmers and manual voice previews cannot impersonate live DJ speech', async () => {
  for (const data of [{pineLive: 'voice', pineSting: '1'}, {pineLive: 'voice', pineWarm: '1'},
    {pineLive: 'voice', pineDecor: '1'}, {}]) {
    const {w} = fixture({player: {id: 'voiceTestAudio', dataset: data}});
    assert.equal((await probeDjSpeech(w, {timeoutMs: 500})).verified, false);
  }
});

test('new speech arriving during the bounded sample can satisfy local proof', async () => {
  const result = await probeDjSpeech(fixture({player: {paused: true}, startAfter: 500}).w, {timeoutMs: 1000});
  assert.equal(result.verified, true);
  assert.ok(result.elapsedMs >= 750);
});
