'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const main = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const from = main.indexOf('ipcMain.handle("replay:frames"');
const to = main.indexOf('/* THE EDITED VIDEO, KEPT.', from);
assert.ok(from > 0 && to > from, 'recent replay IPC handlers must be present');
const handlersSource = main.slice(from, to);

function fixture(audio = { source: 'desk-application-frames', present: true, complete: true,
  state: 'captured', channels: 2, coverage_ratio: 1, gaps: 0 }) {
  let clock = 1700000000000;
  const requestAt = clock;
  const original = Buffer.from('original video with the stereo playback mix and its heard levels');
  const made = { ok: true, out: '/cache/recorded.mp4', dir: '/cache',
    seconds: 180, held: 600, clamped: false, audio };
  const handlers = new Map(), cuts = [], copies = [], uploads = [], forgotten = [], reconstructions = [];
  const context = {
    Buffer, console, HOLD_MAX_S: 3600, AUDIO_SOURCE: 'desk-application-frames',
    Date: { now: () => clock },
    ipcMain: { handle: (channel, fn) => handlers.set(channel, fn) },
    replayFlush: async () => { clock += 850; return true; },
    readConfig: () => ({ baseUrl: 'http://station', ffmpeg: 'ffmpeg' }),
    authHeaders: () => ({}), replayFolder: () => '/recordings',
    replayName: seconds => 'screen-' + seconds + '.mp4',
    screenRing: {
      state: () => ({ seconds: 600 }),
      frames: async want => { cuts.push(want); return { ok: true, frames: [] }; },
      cut: async want => { cuts.push(want); return { ...made }; },
      cutAudio: async want => { cuts.push(want); return { ...made }; }
    },
    clipMux: { forget: dir => forgotten.push(dir),
      mux: async () => { reconstructions.push('mux'); throw new Error('must keep the recorded mix'); } },
    glassParts: { broadcastQuestion: () => { reconstructions.push('sampler'); return 'wrong mix'; } },
    win: { webContents: { executeJavaScript: async () => { reconstructions.push('shell'); return ''; } } },
    path,
    fs: { statSync: () => ({ size: original.length }), existsSync: () => true,
      readFileSync: () => original,
      promises: { copyFile: async (input, output) => copies.push({ input, output, bytes: original }) },
      copyFileSync: (input, output) => copies.push({ input, output, bytes: original }) },
    fetch: async (url, options) => {
      uploads.push({ url, ...options });
      return { ok: true, text: async () => JSON.stringify({ id: 'a'.repeat(32), where: '/exports' }) };
    }
  };
  vm.createContext(context);
  vm.runInContext(handlersSource, context);
  return { original, made, requestAt, handlers, cuts, copies, uploads, forgotten, reconstructions };
}

for (const channel of ['replay:export', 'replay:edit']) {
  test(channel + ' rejects missing or partial captured audio by default', async () => {
    for (const audio of [
      { source: 'desk-application-frames', present: false, complete: false, state: 'unavailable' },
      { source: 'desk-application-frames', present: true, complete: false, state: 'partial', coverage_ratio: 0.75 }
    ]) {
      const f = fixture(audio);
      const result = await f.handlers.get(channel)({}, { seconds: 180, upload: true });
      assert.equal(result.ok, false);
      assert.match(result.detail, /complete audio mix heard/);
      assert.equal(result.audio, audio, 'actual capture provenance remains available');
      assert.equal(f.copies.length, 0, 'no incomplete default export is saved as success');
      assert.equal(f.uploads.length, 0, 'no incomplete default export is uploaded');
      assert.deepEqual(f.forgotten, ['/cache']);
      assert.equal(f.reconstructions.length, 0);
    }
  });

  test(channel + ' preserves a complete recorded stereo mix without another audio pass', async () => {
    const f = fixture();
    const result = await f.handlers.get(channel)({}, { seconds: 180, upload: true });
    assert.equal(result.ok, true, result.detail);
    assert.equal(result.audio, f.made.audio);
    assert.equal(result.audio.channels, 2);
    assert.equal(f.reconstructions.length, 0);
    if (channel === 'replay:export') {
      assert.equal(f.copies[0].input, f.made.out);
      assert.equal(f.copies[0].bytes, f.original);
      assert.equal(f.uploads[0].body, f.original);
    } else {
      assert.equal(f.uploads[0].body, f.original);
      assert.deepEqual(JSON.parse(f.uploads[0].headers['X-Capture-Audio']), f.made.audio);
    }
  });

  test(channel + ' accepts explicitly requested picture-only and incomplete audio exports', async () => {
    for (const options of [{ video_only: true }, { require_audio: false }]) {
      const audio = { source: 'desk-application-frames', present: !options.video_only,
        complete: false, state: options.video_only ? 'unavailable' : 'partial', channels: 2 };
      const f = fixture(audio);
      const result = await f.handlers.get(channel)({}, { seconds: 180, ...options });
      assert.equal(result.ok, true, result.detail);
      assert.equal(result.audio, audio);
      assert.equal(f.cuts[0].video_only, !!options.video_only);
      assert.equal(f.reconstructions.length, 0);
    }
  });

  test(channel + ' freezes the recent interval before flushing the active recording', async () => {
    const f = fixture();
    const result = await f.handlers.get(channel)({}, { seconds: 180, back: 2, end_at: Number.MAX_SAFE_INTEGER });
    assert.equal(result.ok, true, result.detail);
    assert.equal(f.cuts[0].end_at, f.requestAt, 'flush latency and caller timestamps do not move the requested moment');
    assert.equal(f.cuts[0].back, 2);
    assert.equal(f.cuts[0].seconds, 180);
  });
}

test('recent audio-only export freezes the heard interval before flushing', async () => {
  const f = fixture();
  const result = await f.handlers.get('replay:export')({}, { seconds: 180, audio_only: true });
  assert.equal(result.ok, true, result.detail);
  assert.equal(f.cuts[0].end_at, f.requestAt);
  assert.equal(result.audio, f.made.audio);
  assert.equal(f.reconstructions.length, 0);
});

test('recent scrub frames freeze their interval before flushing', async () => {
  const f = fixture();
  const result = await f.handlers.get('replay:frames')({}, { seconds: 5, count: 4 });
  assert.equal(result.ok, true, result.detail);
  assert.equal(f.cuts[0].end_at, f.requestAt);
});
