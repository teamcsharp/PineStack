const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
const start = source.indexOf('ipcMain.handle("replay:export"');
const end = source.indexOf('\n});', start) + 4;
const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-export-test-'));
const input = path.join(folder, 'input.bin'); fs.writeFileSync(input, 'recording bytes');
let handler, cuts = [], complete = true, flushes = 0;
const cut = async (kind, want) => { cuts.push({ kind, want }); return { ok: true, out: input, dir: folder, seconds: 17, held: 17, clamped: true, audio: { present: complete, complete } }; };
vm.runInNewContext(source.slice(start, end), {
  ipcMain: { handle: (_key, fn) => (handler = fn) }, screenRing: { cut: want => cut('video', want), cutAudio: want => cut('audio', want) },
  replayFlush: async () => { flushes++; }, replayWithSound: async made => ({ path: made.out, audio: made.audio }),
  readConfig: () => ({}), replayFolder: () => folder, replayName: () => 'pinebox-screen-fixture.mp4',
  clipMux: { forget() {} }, fs, path
});
(async () => {
  const mix = await handler({}, { seconds: 30, audio_only: true, require_audio: true });
  assert.equal(mix.ok, true); assert.equal(cuts[0].kind, 'audio'); assert.match(mix.where, /pinebox-mix-fixture\.wav$/);
  assert.equal(path.dirname(mix.where), folder); assert.equal(mix.seconds, 17); assert.equal(mix.clamped, true);
  assert.equal(fs.readFileSync(mix.where, 'utf8'), 'recording bytes');
  const video = await handler({}, { seconds: 1200, require_audio: true });
  assert.equal(video.ok, true); assert.equal(cuts[1].kind, 'video'); assert.equal(cuts[1].want.seconds, 1200);
  assert.equal(cuts[1].want.video_only, false); assert.match(video.where, /\.mp4$/);
  const pip = await handler({}, { seconds: 60, view: 'pip', name: 'pinepip-last-1min.mp4', require_audio: true });
  assert.equal(pip.ok, true); assert.equal(cuts[2].want.view, 'pip');
  assert.equal(path.basename(pip.where), 'pinepip-last-1min.mp4');
  complete = false;
  const missing = await handler({}, { seconds: 60, require_audio: true });
  assert.equal(missing.ok, false); assert.match(missing.detail, /Restore DJ audio/);
  assert.equal(flushes, 4, 'all output types flush the live buffer before cutting');
  console.log('PiP recordings: broadcast WAV, MP4 with required audio, recordings destination and honest buffer coverage passed');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => {
  // Only the explicit temporary directory created above is removed.
  fs.rmSync(folder, { recursive: true, force: true });
});
