'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const main = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const from = main.indexOf('ipcMain.handle("replay:local-edit"');
const to = main.indexOf('/* #1114 / #1118: THE COURIER.', from);
assert.ok(from > 0 && to > from);

function fixture(audio) {
  let clock = 1700000000000;
  const requestAt = clock, mp4 = Buffer.from('original MP4 with stereo audio at playback levels');
  const made = { ok: true, out: '/cache/original.mp4', dir: '/cache',
    seconds: 120, held: 600, to: 0, from: 120, clamped: false, audio };
  const cuts = [], opened = [], forgotten = [], laterSources = [];
  let handler;
  const context = {
    Date: { now: () => clock },
    ipcMain: { handle: (channel, fn) => { assert.equal(channel, 'replay:local-edit'); handler = fn; } },
    replayFlush: async () => { clock += 850; return true; },
    screenRing: { cut: async want => { cuts.push(want); return made; } },
    readConfig: () => ({ ffmpeg: 'ffmpeg' }),
    fs: { readFileSync: file => { assert.equal(file, made.out); return mp4; } },
    clipMux: { forget: dir => forgotten.push(dir),
      run: async () => { laterSources.push('extracted'); throw new Error('must preserve original MP4'); } },
    glassParts: { broadcastQuestion: () => { laterSources.push('sampler'); return ''; } },
    win: { webContents: { executeJavaScript: async () => { laterSources.push('later source'); return ''; } } },
    openClipExport: value => opened.push(value)
  };
  vm.createContext(context); vm.runInContext(main.slice(from, to), context);
  return { run: options => handler({}, { seconds: 120, ...options }),
    made, mp4, cuts, opened, forgotten, laterSources, requestAt };
}

test('local recent editor refuses missing or partial audio unless explicitly allowed', async () => {
  for (const audio of [{ present: false, complete: false }, { present: true, complete: false, state: 'partial' }]) {
    const f = fixture(audio), result = await f.run({});
    assert.equal(result.ok, false); assert.match(result.detail, /complete audio mix heard/);
    assert.equal(result.audio, audio); assert.equal(f.opened.length, 0);
    assert.deepEqual(f.forgotten, ['/cache']); assert.equal(f.laterSources.length, 0);
  }
});

test('local recent editor keeps the original embedded stereo mix and playback levels', async () => {
  const audio = { source: 'desk-application-frames', present: true, complete: true, channels: 2 };
  const f = fixture(audio), result = await f.run({});
  assert.equal(result.ok, true, result.detail); assert.equal(result.audio, audio);
  assert.equal(result.broadcast, true); assert.equal(result.mic, false);
  const saved = f.opened[0];
  assert.equal(saved.mp4, f.mp4); assert.equal(saved.audioMeta, audio); assert.equal(saved.embeddedAudio, true);
  assert.equal(saved.audio.broadcast, null); assert.equal(saved.audio.mic, null);
  assert.equal(f.laterSources.length, 0); assert.deepEqual(f.forgotten, ['/cache']);
});

test('local recent editor preserves explicit incomplete-audio and picture-only choices', async () => {
  for (const options of [{ require_audio: false }, { video_only: true }]) {
    const audio = { present: !options.video_only, complete: false, state: 'partial' };
    const f = fixture(audio), result = await f.run(options);
    assert.equal(result.ok, true, result.detail); assert.equal(result.audio, audio);
    assert.equal(f.opened[0].embeddedAudio, !options.video_only);
    assert.equal(f.opened[0].mp4, f.mp4); assert.equal(f.laterSources.length, 0);
    assert.equal(f.cuts[0].video_only, !!options.video_only);
  }
});

test('local recent editor freezes the requested moment before flushing both lanes', async () => {
  const f = fixture({ present: true, complete: true }), result = await f.run({ back: 2 });
  assert.equal(result.ok, true, result.detail);
  assert.equal(f.cuts[0].end_at, f.requestAt); assert.equal(f.cuts[0].back, 2);
  assert.equal(f.opened[0].at, f.requestAt);
});
