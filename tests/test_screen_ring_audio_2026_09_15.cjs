/* #1205: THE DESK'S SCREEN RECORDINGS CARRY THE BROADCAST.
 *
 * "Similar to the tablet, I always want to capture the broadcast audio of the
 *  recording. So any time that I go into the video editor, I need the audio of
 *  the broadcast."
 *
 * Every recording the desk made was silent, and the editor said so: "No audio
 * was captured in this recording." Two measured reasons, both verified before
 * any of this was written:
 *
 *   1. The after-the-fact road asked PineAir, and PineAir.start() has exactly
 *      ONE caller in the whole renderer (sampler.js:3247, inside the sampler's
 *      own mount). On a desk where the sampler is never opened there is no
 *      ring to ask.
 *   2. It would have been the wrong document anyway. PineAir hooks media
 *      elements in the document it RUNS in - the shell - and the broadcast
 *      plays in the panel, `<webview id="controlFrame">` (index.html:542), a
 *      separate document in a separate renderer process.
 *
 * The cure is the tablet's: capture the sound WITH the picture. Five things
 * are pinned here, because every one of them fails quietly:
 *
 *   1. A capture that has sound produces a cut with an audio track, and the
 *      provenance says captured / complete / coverage 1.
 *   2. A platform with no loopback - Electron offers it on Windows only -
 *      produces SILENCE WITH A REASON. The editor must print "No audio was
 *      captured in this recording", never "Audio has gaps", because a
 *      recording that claims audio it does not have is worse than one that
 *      admits it has none.
 *   3. Sound that comes and goes is reported as gaps with a coverage ratio,
 *      and never as completeness.
 *   4. THE SOUND IS NEVER IN THE FILE TWICE. When the ring carried it, the
 *      old PineAir mux must not run at all; when the ring did not, it may.
 *   5. The recorder never opens a microphone. The operator's own voice is a
 *      separate question and is not answered by asking for the broadcast.
 *
 * There is no Electron and no ffmpeg in a unit test, so clip-mux.cjs is
 * replaced in the require cache and the ffmpeg command line is read back out
 * of it - the command line IS the behaviour here. replayWithSound is lifted
 * out of main.js and run for real in a vm, because main.js cannot be required
 * without Electron.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');

/* ------------------------------------------------------------ the stand-in
 * ffmpeg. Records what it was asked to run and writes the output file, so
 * the ring's statSync finds something and the args can be inspected. */
const runs = [];
const clipPath = require.resolve('../desktop/clip-mux.cjs');
const muxes = [];
const fakeClipMux = {
  stash() {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ring-audio-test-'));
    return dir;
  },
  forget(dir) { try { fs.rmSync(dir, { recursive: true, force: true }); } catch (e) {} },
  findFfmpeg() { return { path: 'ffmpeg', found: true }; },
  async run(bin, args) {
    runs.push(args);
    if (fakeClipMux.refuse && args.includes('-map')) throw new Error('Invalid data found');
    const out = args[args.length - 1];
    fs.writeFileSync(out, 'not really an mp4, but it has a size');
    return { ok: true };
  },
  /* mux() writes nothing: replayWithSound only needs it to resolve, and a
   * stub that touched the disk would be testing the test's own temp paths. */
  async mux(plan) { muxes.push(plan); return { ok: true, path: plan.out }; },
  refuse: false
};
require.cache[clipPath] = { id: clipPath, filename: clipPath, loaded: true,
  exports: fakeClipMux, children: [], paths: [] };

const { ScreenRing, AUDIO_SOURCE } = require('../desktop/screen-ring.cjs');
const model = require('../desktop/renderer/video-edit-model.js');

function ringWith(sounds, said) {
  const ring = new ScreenRing();
  if (said) ring.noteAudio(said);
  const at = Date.now() - (sounds.length * 2000);
  sounds.forEach((hasSound, i) => {
    ring.take(Buffer.from('piece ' + i), { at: at + (i * 2000), ms: 2000,
      w: 1280, h: 800, a: hasSound });
  });
  return ring;
}
const argsOf = (list) => list.join(' ');

test('a cut carries the sound it was filmed with, and says so in the tablet shape', async () => {
  runs.length = 0;
  const ring = ringWith([true, true, true, true],
    { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true,
      detail: 'the desk mix, captured with the picture' });
  const made = await ring.cut({ seconds: 6, back: 0 }, {});
  assert.equal(made.ok, true);
  const line = argsOf(runs[0]);
  assert.match(line, /-map 0:v:0 -map 0:a:0/);
  assert.match(line, /-c:a aac/);
  assert.doesNotMatch(line, /-an/);
  assert.equal(made.audio.source, 'desk-loopback-mix');
  assert.equal(made.audio.present, true);
  assert.equal(made.audio.complete, true);
  assert.equal(made.audio.state, 'captured');
  assert.equal(made.audio.coverage_ratio, 1);
  assert.equal(made.audio.gaps, 0);
  /* The editor prints nothing at all when the audio is whole - no warning is
   * the right answer, and any other answer is a warning about a file that is
   * fine. */
  assert.equal(model.audioNotice({ has_audio: true, audio_signal: 'present',
    audio_capture: made.audio }), '');
  ring.forget();
});

test('a platform with no loopback gets silence WITH A REASON, never a claim', async () => {
  runs.length = 0;
  const ring = ringWith([false, false, false],
    { source: AUDIO_SOURCE, present: false, state: 'unavailable', supported: false,
      detail: 'this platform has no loopback capture, so the recording is '
        + 'silent (Electron offers it on Windows only)' });
  const made = await ring.cut({ seconds: 4, back: 0 }, {});
  assert.equal(made.ok, true);
  const line = argsOf(runs[0]);
  assert.match(line, /-an/);
  assert.doesNotMatch(line, /0:a:0/);
  assert.equal(made.audio.present, false);
  assert.equal(made.audio.complete, false);
  assert.equal(made.audio.state, 'unavailable');
  assert.equal(made.audio.coverage_ratio, 0);
  assert.match(made.audio.detail, /loopback/);
  assert.match(made.audio.detail, /Windows/);
  assert.equal(made.audio.supported, false);
  /* What a person actually reads. It must be the honest line, and it must
   * NOT be the one that says some of the sound is in there. */
  const notice = model.audioNotice({ has_audio: false, audio_capture: made.audio });
  assert.match(notice, /No audio was captured in this recording/);
  assert.doesNotMatch(notice, /gaps/);
  ring.forget();
});

test('sound that came and went is reported as gaps, with the coverage measured', async () => {
  runs.length = 0;
  const ring = ringWith([true, true, false, true, true, true],
    { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true, detail: '' });
  const made = await ring.cut({ seconds: 12, back: 0 }, {});
  assert.equal(made.audio.present, true);
  assert.equal(made.audio.complete, false);
  assert.equal(made.audio.state, 'partial');
  assert.equal(made.audio.gaps, 1);
  assert.equal(made.audio.gap_seconds, 2);
  assert.ok(Math.abs(made.audio.coverage_ratio - (5 / 6)) < 0.01,
    'coverage is measured over the pieces the cut used: ' + made.audio.coverage_ratio);
  assert.match(model.audioNotice({ has_audio: true, audio_capture: made.audio }),
    /Audio has gaps \(83% captured\)/);
  ring.forget();
});

test('an encoder that refuses the sound still returns the picture, and stops claiming audio', async () => {
  runs.length = 0;
  fakeClipMux.refuse = true;
  try {
    const ring = ringWith([true, true],
      { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true, detail: '' });
    const made = await ring.cut({ seconds: 4, back: 0 }, {});
    assert.equal(made.ok, true, 'the recording is the part that cannot be taken again');
    assert.equal(runs.length, 2, 'asked once with sound, once without');
    assert.match(argsOf(runs[1]), /-an/);
    assert.equal(made.audio.present, false);
    assert.equal(made.audio.state, 'unavailable');
    assert.match(made.audio.detail, /encoder refused/);
    /* Not "partial" - the file that came back has no audio track at all, and
     * "Audio has gaps" would be a claim that some of it is in there. */
    assert.notEqual(made.audio.state, 'partial');
    ring.forget();
  } finally { fakeClipMux.refuse = false; }
});

test('video only means the sound is left out of the cut, not stripped afterwards', async () => {
  runs.length = 0;
  const ring = ringWith([true, true],
    { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true, detail: '' });
  const made = await ring.cut({ seconds: 4, back: 0, video_only: true }, {});
  assert.match(argsOf(runs[0]), /-an/);
  assert.equal(runs.length, 1, 'one encode, not a second one to remove what was just written');
  assert.equal(made.audio.present, false);
  assert.equal(made.audio.video_only_explicit, true);
  assert.match(model.audioNotice({ has_audio: false, audio_capture: made.audio }),
    /This recording was captured without audio/);
  ring.forget();
});

test('the ring says what its sound is before anything is cut', () => {
  const ring = ringWith([true, true, false, true], null);
  ring.noteAudio({ source: AUDIO_SOURCE, present: true, state: 'capturing',
    supported: true, detail: 'the desk mix, captured with the picture' });
  const state = ring.state();
  /* hot-corners.js:1553 prints exactly these two into the export sheet. */
  assert.equal(state.audio.state, 'capturing');
  assert.match(state.audio.detail, /desk mix/);
  assert.equal(state.audio.held_ratio, 0.75);
  ring.forget();
});

/* --------------------------------------------------------------------------
 * THE ONE FILE, ONE COPY RULE.
 *
 * replayWithSound is the junction: the ring's own sound on one side and the
 * old PineAir mux on the other. Both muxing into the same file would put the
 * broadcast in twice, a few hundred milliseconds apart, which is worse than
 * none. main.js cannot be required without Electron, so the function is
 * lifted out of it and run for real. */
function liftReplayWithSound() {
  const source = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
  const from = source.indexOf('async function replayWithSound(');
  const to = source.indexOf('ipcMain.handle("replay:edit"');
  assert.ok(from > 0 && to > from, 'replayWithSound must still be findable in main.js');
  return source.slice(from, to);
}

function junction(bridgeAnswer) {
  muxes.length = 0;
  const asked = [];
  const context = {
    AUDIO_SOURCE, Buffer, JSON, String, Number, console,
    clipMux: fakeClipMux,
    fs: { writeFileSync() {} },
    path: { join: (...bits) => bits.join('/') },
    readConfig: () => ({}),
    glassParts: { broadcastQuestion: (from, to) => { asked.push([from, to]); return 'ask'; } },
    win: { webContents: { executeJavaScript: async () => JSON.stringify(bridgeAnswer) } }
  };
  vm.createContext(context);
  vm.runInContext(liftReplayWithSound(), context);
  return { context, asked };
}

const cutWithSound = {
  out: '/tmp/cut/screen.mp4', dir: '/tmp/cut', seconds: 30, from: 30, to: 0,
  audio: { source: 'desk-loopback-mix', present: true, complete: true,
    state: 'captured', coverage_ratio: 1, gaps: 0,
    detail: 'the desk mix, captured with the picture' }
};
const cutWithoutSound = {
  out: '/tmp/cut/screen.mp4', dir: '/tmp/cut', seconds: 30, from: 30, to: 0,
  audio: { source: 'desk-loopback-mix', present: false, complete: false,
    state: 'unavailable', coverage_ratio: 0, gaps: 1,
    detail: 'this platform has no loopback capture, so the recording is silent' }
};

test('a cut that already has the broadcast is not dressed with it a second time', async () => {
  const { context, asked } = junction({ ok: true, b64: Buffer.from('x'.repeat(200)).toString('base64') });
  const dressed = await context.replayWithSound(cutWithSound, false);
  assert.equal(muxes.length, 0, 'the old road must not mux over sound that is already there');
  assert.equal(asked.length, 0, 'and it must not even ask the shell for it');
  assert.equal(dressed.path, cutWithSound.out, 'the cut is handed on as it is');
  assert.equal(dressed.audio.source, 'desk-loopback-mix');
  assert.equal(dressed.audio.present, true);
});

test('a silent cut may still be dressed by the old road, exactly once', async () => {
  const { context, asked } = junction({ ok: true, b64: Buffer.from('x'.repeat(200)).toString('base64') });
  const dressed = await context.replayWithSound(cutWithoutSound, false);
  assert.equal(asked.length, 1, 'PineAir is the fallback, and it is asked once');
  assert.equal(muxes.length, 1, 'one mux, one copy of the broadcast');
  assert.equal(muxes[0].mic, null, 'the microphone is never added on the desk');
  assert.equal(dressed.audio.source, 'pine-air-ring');
  assert.equal(dressed.audio.present, true);
  assert.equal(dressed.audio.coverage_ratio, 1);
});

test('when neither road has the sound, the answer names both reasons and claims nothing', async () => {
  const { context } = junction({ ok: false, why: 'the air tap is not running on this terminal' });
  const dressed = await context.replayWithSound(cutWithoutSound, false);
  assert.equal(muxes.length, 0);
  assert.equal(dressed.audio.present, false);
  assert.equal(dressed.audio.state, 'unavailable');
  assert.match(dressed.audio.detail, /loopback/);
  assert.match(dressed.audio.detail, /air tap is not running/);
  assert.match(model.audioNotice({ has_audio: false, audio_capture: dressed.audio }),
    /No audio was captured in this recording/);
});

test('video only asks nobody for sound and says it was asked for', async () => {
  const { context, asked } = junction({ ok: true, b64: 'AAAA' });
  const dressed = await context.replayWithSound(cutWithSound, true);
  assert.equal(asked.length, 0);
  assert.equal(muxes.length, 0);
  assert.equal(dressed.path, cutWithSound.out);
});

/* --------------------------------------------------------------------------
 * THE RECORDER ITSELF. It runs in the shell, which is where the argument has
 * to be settled: the broadcast is NOT in this document, so the only road to
 * it is the display-media handler's loopback. */
function shell(plan) {
  const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/screen-ring.js'), 'utf8');
  const calls = { display: [], user: [], begin: [], pushes: [], notes: [] };
  const track = (kind, live) => ({ kind, readyState: live === false ? 'ended' : 'live',
    muted: false, stop() { this.readyState = 'ended'; }, addEventListener() {} });
  const streamOf = (withAudio) => {
    const video = [track('video')];
    const audio = withAudio ? [track('audio')] : [];
    return { getVideoTracks: () => video, getAudioTracks: () => audio,
      getTracks: () => video.concat(audio) };
  };
  let rec = null;
  function MediaRecorder(stream, options) {
    this.state = 'inactive'; this.stream = stream; this.options = options;
    this.start = () => { this.state = 'recording'; };
    this.stop = () => { this.state = 'inactive'; if (this.onstop) this.onstop(); };
    rec = this;
  }
  MediaRecorder.isTypeSupported = () => true;
  function Blob() { this.size = 12; this.arrayBuffer = () => Promise.resolve(new ArrayBuffer(12)); }
  const listeners = {};
  const root = {
    MediaRecorder, Blob, Promise, Date,
    console: { log: (line) => calls.notes.push(String(line)) },
    setTimeout: () => 1,
    document: { readyState: 'loading',
      addEventListener: (kind, fn) => { (listeners[kind] ||= []).push(fn); },
      removeEventListener: (kind, fn) => { listeners[kind] = (listeners[kind] || []).filter((x) => x !== fn); } },
    navigator: { mediaDevices: {
      getDisplayMedia: (want) => { calls.display.push(want); return plan.display(streamOf); },
      getUserMedia: (want) => { calls.user.push(want); return plan.user ? plan.user(streamOf) : Promise.reject(new Error('no')); }
    } },
    pineDesktop: {
      replaySource: async () => plan.source || { ok: true, id: 'window:1', loopback: true },
      replayBegin: async (opts) => { calls.begin.push(opts); return { ok: true }; },
      replayStop: async () => ({ ok: true }),
      replayPush: async (buf, meta) => { calls.pushes.push(meta); return { ok: true }; },
      onReplayFlush: () => {}
    }
  };
  const context = vm.createContext({ window: root, globalThis: root, ArrayBuffer, Promise, Date, console });
  vm.runInContext(source, context);
  return { api: root.PineScreenRing, calls, fire: (kind) => (listeners[kind] || []).forEach((fn) => fn({})),
    piece: () => { if (rec) { if (rec.ondataavailable) rec.ondataavailable({ data: { size: 12 } }); rec.stop(); } } };
}
const settle = async () => { for (let i = 0; i < 12; i += 1) await Promise.resolve(); };

test('the recorder asks for the application audio, and the pieces carry it', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  assert.equal(s.calls.display.length, 1, 'display capture is the FIRST road, because it is the only one with sound');
  assert.equal(s.calls.display[0].audio, true, 'and it must ask for audio or the handler is never consulted');
  assert.equal(s.calls.user.length, 0, 'the silent road is not taken when the sound road worked');
  const said = s.calls.begin[0].audio;
  assert.equal(said.present, true);
  assert.equal(said.state, 'capturing');
  assert.equal(said.source, 'desk-loopback-mix');
  s.piece();
  await settle();
  assert.equal(s.calls.pushes.length, 1);
  assert.equal(s.calls.pushes[0].a, true, 'the piece records that it had sound');
  assert.equal(s.api.state().audio.present, true);
});

test('a capture with no audio track is reported as silence with a reason, not as sound', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(false)) });
  await s.api.start({ gesture: true });
  await settle();
  const said = s.calls.begin[0].audio;
  assert.equal(said.present, false);
  assert.equal(said.state, 'unavailable');
  assert.equal(said.supported, false, 'the handler answered and answered without audio: that is the platform');
  assert.match(said.detail, /Windows/);
  s.piece();
  await settle();
  assert.equal(s.calls.pushes[0].a, false, 'a silent piece must never be marked as carrying sound');
});

test('with no gesture to spend the window is still filmed, and the silence is explained', async () => {
  const s = shell({
    display: () => Promise.reject(new Error('Permission denied by system')),
    user: (streamOf) => Promise.resolve(streamOf(false))
  });
  await s.api.start();
  await settle();
  assert.equal(s.calls.user.length, 1, 'the ring is never lost for want of sound');
  assert.equal(s.calls.user[0].audio, false);
  const said = s.calls.begin[0].audio;
  assert.equal(said.present, false);
  assert.match(said.detail, /gesture/);
});

test('a later press upgrades a silent capture to one with the broadcast on it', async () => {
  let withAudio = false;
  const s = shell({
    display: (streamOf) => (withAudio ? Promise.resolve(streamOf(true))
      : Promise.reject(new Error('no transient activation'))),
    user: (streamOf) => Promise.resolve(streamOf(false))
  });
  await s.api.start();
  await settle();
  assert.equal(s.api.state().audio.present, false);
  withAudio = true;
  s.fire('pointerdown');
  await settle();
  assert.equal(s.api.state().audio.present, true, 'the first press adds the sound');
  const last = s.calls.begin[s.calls.begin.length - 1].audio;
  assert.equal(last.present, true);
  s.piece();
  await settle();
  assert.equal(s.calls.pushes[s.calls.pushes.length - 1].a, true);
});

test('nothing here ever opens a microphone', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  for (const want of s.calls.display) {
    assert.notEqual(want.audio, 'microphone');
    assert.equal(typeof want.video, 'object');
  }
  for (const want of s.calls.user) assert.equal(want.audio, false);
  /* The operator's own voice is a separate question: the desk's clip window
   * only offers a mic channel for a recording that arrived from the tablet
   * with one (main.js clip:export, held.mic), and localClip() has always
   * handed it `mic: null`. Asking for the broadcast must not change that. */
  const main = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
  const local = main.slice(main.indexOf('ipcMain.handle("replay:local-edit"'),
    main.indexOf('ipcMain.handle("replay:local-edit"') + 3000);
  assert.match(local, /mic: null/);
});
