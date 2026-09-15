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
 *
 * ---------------------------------------------------------------------------
 * TWO RINGS (2026-09-15, #1207).
 *
 * The premise above - "capture the sound WITH the picture" - was measured and
 * is not available on this Electron. Every pairing of a window picture with
 * any audio source is refused outright, and the one pairing that IS accepted
 * films the panel's control page instead of the window. So the sound is a
 * SECOND, audio-only capture of the panel's frame, kept in a second ring, and
 * laid under the picture at the cut.
 *
 * Which moves where these tests have to bite. Five more things are pinned,
 * every one of them something that fails quietly:
 *
 *   6. THE TWO RINGS ARE PUT ON ONE TIMELINE, and the arithmetic that does it
 *      is in the ffmpeg command line: two concat inputs, a shift measured
 *      from the two rings' own stamps, and an explicit `duration` on every
 *      piece. Without the durations the picture's timeline is not wall clock
 *      at all - desktop capture emits no frames while the screen is still, so
 *      a still minute collapses - and sound laid under it drifts by seconds.
 *   7. A SHIFT THAT IS NOT BELIEVABLE IS REFUSED. Past ALIGN_MAX_MS the cut
 *      goes out silent and says so, because a track a second out of step is
 *      worse than none - the operator's own rule.
 *   8. EITHER RING MAY DIE ALONE. No picture is no recording, whatever the
 *      sound ring holds: a black rectangle with a broadcast on it is not a
 *      screen recording. No sound is a silent recording that still cuts, with
 *      the provenance saying why.
 *   9. THE PICTURE CAPTURE ASKS FOR NO SOUND, which is what lets main.js tell
 *      the two requests apart, and means nothing can attach audio to it
 *      behind the sound ring's back and put the broadcast in twice.
 *  10. enableLocalEcho IS SET ON THE FRAME ANSWER. Without it, capturing the
 *      panel MUTES the panel - the recorder silences the station while the
 *      operator is listening to it, which is the worst outcome available
 *      here. Measured by listening; pinned here so it cannot be dropped.
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

const { ScreenRing, AUDIO_SOURCE, ALIGN_MAX_MS } = require('../desktop/screen-ring.cjs');
const model = require('../desktop/renderer/video-edit-model.js');

/* #1207: `sounds` is still read one entry per two-second piece, and still
 * means "was there sound over this stretch" - but it now lays down a piece in
 * EACH ring, the sound one only where there was sound. The stamps match, so
 * the shift between the rings is zero and the coverage arithmetic is the same
 * arithmetic the old single-ring assertions were written against.
 *
 * `opts.soundShift` moves every sound piece by that many milliseconds, which
 * is how the two rings really arrive: started back to back, never together.
 * `opts.noSoundRing` leaves the second ring empty altogether - a desk where
 * the panel would not give up its audio. */
function ringWith(sounds, said, opts) {
  const o = opts || {};
  const ring = new ScreenRing();
  if (said) ring.noteAudio(said);
  const at = Date.now() - (sounds.length * 2000);
  sounds.forEach((hasSound, i) => {
    ring.take(Buffer.from('piece ' + i), { at: at + (i * 2000), ms: 2000,
      w: 1280, h: 800, a: false, kind: 'v' });
    if (hasSound && !o.noSoundRing) {
      ring.take(Buffer.from('sound ' + i),
        { at: at + (i * 2000) + (o.soundShift || 0), ms: 2000, a: true, kind: 'a' });
    }
  });
  return ring;
}
const argsOf = (list) => list.join(' ');
/* The concat lists are written to disk by the ring and are part of the
 * behaviour: without a `duration` on every piece the picture's timeline is
 * not wall clock and nothing can be laid under it. */
const listsIn = (line) => line.split(' ').filter((bit) => /\.txt$/.test(bit));
const readList = (line, which) => fs.readFileSync(listsIn(line)[which], 'utf8');

test('a cut carries the sound it was filmed with, and says so in the tablet shape', async () => {
  runs.length = 0;
  const ring = ringWith([true, true, true, true],
    { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true,
      detail: 'the desk mix, captured with the picture' });
  const made = await ring.cut({ seconds: 6, back: 0 }, {});
  assert.equal(made.ok, true);
  const line = argsOf(runs[0]);
  /* #1207: the sound is a SECOND input now, and it is mapped out of the
   * filter graph that put it on the picture's timeline - never straight off
   * input 0, which has no audio track on it at all. */
  assert.match(line, /-map 0:v:0 -map \[pinesound\]/);
  assert.doesNotMatch(line, /-map 0:a:0/);
  assert.equal(listsIn(line).length, 2, 'two concat lists: the picture and the sound');
  assert.match(line, /-c:a aac/);
  assert.doesNotMatch(line, /-an/);
  assert.equal(made.audio.source, 'desk-broadcast-frame');
  assert.equal(made.audio.present, true);
  assert.equal(made.audio.complete, true);
  assert.equal(made.audio.state, 'captured');
  assert.equal(made.audio.coverage_ratio, 1);
  assert.equal(made.audio.gaps, 0);
  assert.equal(made.audio.align_shift_ms, 0, 'the rings were stamped together');
  /* The editor prints nothing at all when the audio is whole - no warning is
   * the right answer, and any other answer is a warning about a file that is
   * fine. */
  assert.equal(model.audioNotice({ has_audio: true, audio_signal: 'present',
    audio_capture: made.audio }), '');
  ring.forget();
});

test('a desk whose panel gives no sound gets silence WITH A REASON, never a claim', async () => {
  runs.length = 0;
  const ring = ringWith([false, false, false],
    { source: AUDIO_SOURCE, present: false, state: 'unavailable', supported: false,
      detail: 'the panel would not give up its sound: Error starting capture '
        + '(this platform has no loopback capture either)' });
  const made = await ring.cut({ seconds: 4, back: 0 }, {});
  assert.equal(made.ok, true);
  const line = argsOf(runs[0]);
  assert.match(line, /-an/);
  assert.doesNotMatch(line, /pinesound/);
  assert.equal(listsIn(line).length, 1, 'one list: there is no sound to concat');
  assert.equal(made.audio.present, false);
  assert.equal(made.audio.complete, false);
  assert.equal(made.audio.state, 'unavailable');
  assert.equal(made.audio.coverage_ratio, 0);
  assert.match(made.audio.detail, /would not give up its sound/);
  assert.equal(made.audio.supported, false);
  assert.equal(made.audio.align_shift_ms, null, 'nothing was aligned, so nothing is claimed');
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
    'coverage is measured over the clock the cut covers: ' + made.audio.coverage_ratio);
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
    assert.equal(listsIn(argsOf(runs[1])).length, 1,
      'the retry drops the sound input as well as the mapping');
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
    supported: true, detail: 'the broadcast, captured from the panel' });
  const state = ring.state();
  /* hot-corners.js:1553 prints exactly these two into the export sheet. */
  assert.equal(state.audio.state, 'capturing');
  assert.match(state.audio.detail, /broadcast/);
  /* #1207: measured by laying the SOUND ring over the span the PICTURE ring
   * holds - three of the four two-second stretches have sound under them. */
  assert.equal(state.audio.held_ratio, 0.75);
  assert.equal(state.audio.pieces, 3, 'the sound ring is counted on its own');
  ring.forget();
});

test('a sound ring running beside no picture holds nothing a cut could use', () => {
  const ring = new ScreenRing();
  const at = Date.now() - 6000;
  for (let i = 0; i < 3; i += 1) {
    ring.take(Buffer.from('sound ' + i), { at: at + (i * 2000), ms: 2000, a: true, kind: 'a' });
  }
  /* The picture is what decides there is a recording at all. A ring that has
   * only ever been handed sound is not running and holds nothing. */
  assert.equal(ring.state().running, false);
  assert.equal(ring.state().seconds, 0);
  assert.equal(ring.state().audio.held_ratio, 0,
    'sound with no picture under it is 0, never 1');
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
 * it is a second capture pointed at the panel's own frame.
 *
 * #1207: the stand-in answers TWO getDisplayMedia calls and tells them apart
 * the way main.js does - by whether a picture was asked for. That is not a
 * convenience of the test; it is the contract. */
function shell(plan) {
  const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/screen-ring.js'), 'utf8');
  const calls = { display: [], sound: [], user: [], begin: [], pushes: [], notes: [] };
  const track = (kind, live) => ({ kind, readyState: live === false ? 'ended' : 'live',
    muted: false, stop() { this.readyState = 'ended'; }, addEventListener() {} });
  const streamOf = (withAudio) => {
    const video = [track('video')];
    const audio = withAudio ? [track('audio')] : [];
    return { getVideoTracks: () => video, getAudioTracks: () => audio,
      getTracks: () => video.concat(audio) };
  };
  /* A capture with no picture in it at all - which is the only shape the
   * sound ring is ever handed. */
  const soundOf = (withAudio) => {
    const audio = withAudio ? [track('audio')] : [];
    return { getVideoTracks: () => [], getAudioTracks: () => audio,
      getTracks: () => audio.slice() };
  };
  const recs = { v: null, a: null };
  function MediaRecorder(stream, options) {
    this.state = 'inactive'; this.stream = stream; this.options = options;
    this.start = () => { this.state = 'recording'; };
    this.stop = () => { this.state = 'inactive'; if (this.onstop) this.onstop(); };
    recs[stream.getVideoTracks().length ? 'v' : 'a'] = this;
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
      getDisplayMedia: (want) => {
        /* THE DISCRIMINATOR, and it is the real one. */
        if (want.video === false) {
          calls.sound.push(want);
          return plan.sound ? plan.sound(soundOf)
            : Promise.reject(new Error('no sound road in this plan'));
        }
        calls.display.push(want);
        return plan.display(streamOf);
      },
      getUserMedia: (want) => { calls.user.push(want); return plan.user ? plan.user(streamOf) : Promise.reject(new Error('no')); }
    } },
    pineDesktop: {
      replaySource: async () => plan.source || { ok: true, id: 'window:1', loopback: true },
      replayBegin: async (opts) => { calls.begin.push(opts);
        /* The handshake. `plan.rings` of 1 is an older main process - one
         * that would file the sound in with the picture. */
        const rings = plan.rings === undefined ? 2 : plan.rings;
        return rings ? { ok: true, rings } : { ok: true }; },
      replayStop: async () => ({ ok: true }),
      replayPush: async (buf, meta) => { calls.pushes.push(meta); return { ok: true }; },
      onReplayFlush: () => {}
    }
  };
  const context = vm.createContext({ window: root, globalThis: root, ArrayBuffer, Promise, Date, console });
  vm.runInContext(source, context);
  return { api: root.PineScreenRing, calls, recs,
    fire: (kind) => (listeners[kind] || []).forEach((fn) => fn({})),
    piece: (which) => {
      const rec = recs[which || 'v'];
      if (!rec) return false;
      if (rec.ondataavailable) rec.ondataavailable({ data: { size: 12 } });
      rec.stop();
      return true;
    } };
}
const settle = async () => { for (let i = 0; i < 24; i += 1) await Promise.resolve(); };
const pushesOf = (calls, kind) => calls.pushes.filter((m) => m.kind === kind);

test('the recorder opens a second, audio-only capture and the sound pieces carry it', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(false)),
                    sound: (soundOf) => Promise.resolve(soundOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  assert.equal(s.calls.display.length, 1, 'the window is filmed once');
  assert.equal(s.calls.display[0].audio, false,
    'and it asks for NO sound - that is what lets main.js tell the two apart');
  assert.equal(s.calls.sound.length, 1, 'and the broadcast is asked for separately');
  assert.equal(s.calls.sound[0].video, false,
    'video:false is load-bearing: asking with video:true fails the whole request');
  assert.equal(s.calls.sound[0].audio, true);
  const said = s.calls.begin[s.calls.begin.length - 1];
  assert.equal(said.audio.present, true);
  assert.equal(said.audio.state, 'capturing');
  assert.equal(said.audio.source, 'desk-broadcast-frame');
  /* Both streams named on the road that writes the diagnostic. */
  assert.equal(said.streams.picture.running, true);
  assert.equal(said.streams.sound.running, true);
  s.piece('v');
  s.piece('a');
  await settle();
  assert.equal(pushesOf(s.calls, 'v').length, 1);
  assert.equal(pushesOf(s.calls, 'a').length, 1);
  assert.equal(pushesOf(s.calls, 'v')[0].a, false,
    'a picture piece never claims sound it does not have');
  assert.equal(pushesOf(s.calls, 'a')[0].a, true);
  assert.equal(s.api.state().audio.present, true);
});

test('the sound capture never asks for a camera, a screen or a picture of any kind', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(false)),
                    sound: (soundOf) => Promise.resolve(soundOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  for (const want of s.calls.sound) {
    assert.equal(want.video, false);
    assert.equal(Object.keys(want).sort().join(','), 'audio,video',
      'nothing else is asked for, so nothing else can be answered');
  }
});

test('a sound capture that comes back with no track is silence with a reason, not sound', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(false)),
                    sound: (soundOf) => Promise.resolve(soundOf(false)) });
  await s.api.start({ gesture: true });
  await settle();
  const said = s.calls.begin[s.calls.begin.length - 1].audio;
  assert.equal(said.present, false);
  assert.equal(said.state, 'unavailable');
  assert.match(said.detail, /no audio track/);
  /* The picture is untouched by any of it. */
  assert.equal(s.api.state().running, true);
  s.piece('v');
  await settle();
  assert.equal(pushesOf(s.calls, 'v').length, 1);
});

test('the window is still filmed when the panel refuses its sound outright', async () => {
  const s = shell({
    display: (streamOf) => Promise.resolve(streamOf(false)),
    sound: () => Promise.reject(new Error('Error starting capture'))
  });
  const got = await s.api.start({ gesture: true });
  await settle();
  assert.equal(got.ok, true, 'the ring is never lost for want of sound');
  assert.equal(s.api.state().running, true);
  const said = s.calls.begin[s.calls.begin.length - 1].audio;
  assert.equal(said.present, false);
  assert.match(said.detail, /would not give up its sound/);
  assert.match(said.detail, /Error starting capture/);
});

test('with no display capture at all the window is still filmed the legacy way', async () => {
  const s = shell({
    display: () => Promise.reject(new Error('Permission denied by system')),
    user: (streamOf) => Promise.resolve(streamOf(false)),
    sound: (soundOf) => Promise.resolve(soundOf(true))
  });
  await s.api.start();
  await settle();
  assert.equal(s.calls.user.length, 1, 'the window is filmed through the legacy road');
  assert.equal(s.calls.user[0].audio, false);
  /* And the sound still arrives - it never depended on the picture's road. */
  assert.equal(s.api.state().audio.present, true);
});

test('a later press retries the sound and never reopens the picture', async () => {
  let ready = false;
  const s = shell({
    display: (streamOf) => Promise.resolve(streamOf(false)),
    sound: (soundOf) => (ready ? Promise.resolve(soundOf(true))
      : Promise.reject(new Error('no transient activation')))
  });
  await s.api.start({ gesture: true });
  await settle();
  assert.equal(s.api.state().audio.present, false);
  const filmedOnce = s.calls.display.length;
  ready = true;
  s.fire('pointerdown');
  await settle();
  assert.equal(s.api.state().audio.present, true, 'the first press adds the sound');
  assert.equal(s.calls.display.length, filmedOnce,
    'and the window capture is not reopened - the picture is opened once and left alone');
  s.piece('a');
  await settle();
  const sound = pushesOf(s.calls, 'a');
  assert.equal(sound[sound.length - 1].a, true);
});

test('stopping the ring stops the sound capture too, so the panel is let go', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(false)),
                    sound: (soundOf) => Promise.resolve(soundOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  const held = s.calls.sound.length && s.recs.a;
  assert.ok(held, 'the sound recorder was running');
  s.api.stop();
  await settle();
  assert.equal(s.api.state().audio.running, false);
  assert.equal(s.api.state().running, false);
});

test('a flush closes BOTH rings, so the newest seconds are not silent', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(false)),
                    sound: (soundOf) => Promise.resolve(soundOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  assert.equal(s.recs.v.state, 'recording');
  assert.equal(s.recs.a.state, 'recording');
  assert.equal(s.api.flush(), true);
  await settle();
  /* Both handed a piece down. A flush that closed only the picture would make
   * exactly the stretch the operator reached for the silent one. */
  assert.equal(pushesOf(s.calls, 'v').length, 1);
  assert.equal(pushesOf(s.calls, 'a').length, 1);
});

test('an older main process is told no, and the window is filmed silently', async () => {
  /* THE PAIRING THAT DOES REAL DAMAGE, and it is the normal state of this
   * desk for minutes at a time: this file is re-evaluated whenever the share
   * changes, while main.js and screen-ring.cjs only come back on a restart.
   * An older ring has never heard of `kind`, so it files every piece of sound
   * in with the picture - and a cut then concatenates opus pieces with video
   * ones and is refused outright. Measured on the live desk while this was
   * being written: 32 kB opus pieces sitting in the picture list.
   *
   * So the second capture is never opened at all against a ring that cannot
   * answer for two lanes. */
  let opened = 0;
  const s = shell({
    rings: 1,
    display: (streamOf) => Promise.resolve(streamOf(false)),
    sound: (soundOf) => { opened += 1; return Promise.resolve(soundOf(true)); }
  });
  const got = await s.api.start({ gesture: true });
  await settle();
  assert.equal(got.ok, true, 'the window is filmed exactly as it was before');
  assert.equal(s.api.state().running, true);
  assert.equal(opened, 0, 'the panel is never captured against a ring that cannot keep it');
  assert.equal(s.calls.sound.length, 0);
  const said = s.calls.begin[s.calls.begin.length - 1].audio;
  assert.equal(said.present, false);
  assert.equal(said.state, 'unavailable');
  assert.match(said.detail, /restart Pine Box/,
    'and the reason says what to do about it, not just that it failed');
  /* No sound pieces are pushed, so nothing can land in the picture list. */
  s.piece('v');
  await settle();
  assert.equal(pushesOf(s.calls, 'a').length, 0);
  assert.equal(pushesOf(s.calls, 'v').length, 1);
});

test('a ring that answers for two lanes gets the second capture', async () => {
  const s = shell({ rings: 2,
    display: (streamOf) => Promise.resolve(streamOf(false)),
    sound: (soundOf) => Promise.resolve(soundOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  assert.equal(s.calls.sound.length, 1);
  assert.equal(s.api.state().audio.present, true);
  /* And the ring really does answer it - this is not a property of the
   * stand-in. */
  const ring = new ScreenRing();
  assert.equal(ring.state().rings, 2,
    'screen-ring.cjs must keep answering the handshake the renderer asks');
  ring.forget();
});

test('the sound is asked for TWICE and still opens only one capture', async () => {
  /* start() asks for the sound, and main.js asks again a moment later with a
   * user activation of its own, so two calls can be in the air before either
   * has resolved. Two captures of the same frame ARE allowed by Electron -
   * measured - which is exactly why this has to be held back here: the second
   * would overwrite the first and leave an encoder running on the panel that
   * nothing would ever stop. */
  let opened = 0;
  let release = null;
  const held = new Promise((r) => { release = r; });
  const s = shell({
    display: (streamOf) => Promise.resolve(streamOf(false)),
    sound: (soundOf) => { opened += 1; return held.then(() => soundOf(true)); }
  });
  s.api.start({ gesture: true });
  await settle();
  s.api.startSound({ gesture: true });
  s.api.startSound({ gesture: true });
  await settle();
  assert.equal(opened, 1, 'one capture of the panel, however many times it is asked for');
  release();
  await settle();
  assert.equal(s.api.state().audio.present, true);
  /* And once it is up, asking again changes nothing. */
  await s.api.startSound({ gesture: true });
  await settle();
  assert.equal(opened, 1);
});

test('a sound road that throws where it stands never costs the picture', async () => {
  /* getDisplayMedia can throw rather than reject - no transient activation is
   * one way. start() is what is filming the window, so a throw on the sound
   * road must not come up through it and turn a running capture into a
   * rejected start. */
  const s = shell({
    display: (streamOf) => Promise.resolve(streamOf(false)),
    sound: () => { throw new Error('InvalidStateError'); }
  });
  const got = await s.api.start({ gesture: true });
  await settle();
  assert.equal(got.ok, true, 'the window is filmed regardless');
  assert.equal(s.api.state().running, true);
  assert.equal(s.api.state().audio.present, false);
  s.piece('v');
  await settle();
  assert.equal(pushesOf(s.calls, 'v').length, 1, 'and the pieces keep coming');
});

test('nothing here ever opens a microphone', async () => {
  const s = shell({ display: (streamOf) => Promise.resolve(streamOf(false)),
                    sound: (soundOf) => Promise.resolve(soundOf(true)) });
  await s.api.start({ gesture: true });
  await settle();
  for (const want of s.calls.display) {
    assert.notEqual(want.audio, 'microphone');
    assert.equal(typeof want.video, 'object');
  }
  for (const want of s.calls.user) assert.equal(want.audio, false);
  /* getDisplayMedia's `audio: true` means "the thing being captured", never
   * an input device, and main.js answers it with a WebFrameMain - a page, not
   * a microphone. Pinned so a later hand cannot quietly widen it. */
  for (const want of s.calls.sound) assert.equal(want.audio, true);
  const renderer = fs.readFileSync(
    path.join(__dirname, '../desktop/renderer/screen-ring.js'), 'utf8');
  assert.doesNotMatch(renderer, /getUserMedia\(\s*\{\s*audio:\s*true/,
    'no road here opens an input device');
  assert.doesNotMatch(renderer, /audio:\s*\{\s*deviceId/);
  /* The operator's own voice is a separate question: the desk's clip window
   * only offers a mic channel for a recording that arrived from the tablet
   * with one (main.js clip:export, held.mic), and localClip() has always
   * handed it `mic: null`. Asking for the broadcast must not change that. */
  const main = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
  const local = main.slice(main.indexOf('ipcMain.handle("replay:local-edit"'),
    main.indexOf('ipcMain.handle("replay:local-edit"') + 3000);
  assert.match(local, /mic: null/);
});

/* --------------------------------------------------------------------------
 * ALIGNMENT.
 *
 * The two recorders cannot be started on the same millisecond and never will
 * be, so the cut measures the difference and compensates it. What is pinned
 * here is the arithmetic and, more importantly, the thing that makes the
 * arithmetic valid at all: an explicit `duration` on every piece in both
 * lists. Without those the picture's concat timeline is not wall clock -
 * measured at 43.26 s of timeline for 70.01 s of recording, because desktop
 * capture emits no frames while the screen is still - and no amount of
 * shifting can lay sound under a timeline like that. */

test('every piece in both lists declares the wall clock it was stamped with', async () => {
  runs.length = 0;
  const ring = ringWith([true, true, true],
    { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true, detail: '' });
  const made = await ring.cut({ seconds: 6, back: 0 }, {});
  assert.equal(made.ok, true);
  const line = argsOf(runs[0]);
  for (const which of [0, 1]) {
    const list = readList(line, which);
    const files = list.split('\n').filter((l) => l.startsWith('file '));
    const durations = list.split('\n').filter((l) => l.startsWith('duration '));
    assert.equal(files.length, durations.length,
      'list ' + which + ': every file carries a duration, or the timeline is the container\'s');
    assert.ok(files.length >= 3);
    /* The duration written is the interval to the NEXT piece's stamp, so the
     * stop-and-start seam never accumulates: three pieces two seconds apart
     * must declare two seconds each, not the 1.98 s they actually hold. */
    assert.equal(durations[0], 'duration 2.000');
    assert.equal(durations[1], 'duration 2.000');
  }
  ring.forget();
});

test('the sound is shifted onto the picture timeline, and which way is measured', async () => {
  for (const shift of [0, 700, -700]) {
    runs.length = 0;
    /* soundShift moves the sound ring later, so the picture's first stamp
     * minus the sound's is NEGATIVE - the sound began after the picture and
     * has to be held back. */
    const ring = ringWith([true, true, true, true],
      { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true, detail: '' },
      { soundShift: shift });
    const made = await ring.cut({ seconds: 8, back: 0 }, {});
    assert.equal(made.ok, true, 'shift ' + shift);
    assert.equal(made.audio.present, true, 'shift ' + shift);
    assert.equal(made.audio.align_shift_ms, -shift || 0,
      'the shift is the picture\'s first stamp minus the sound\'s');
    const line = argsOf(runs[0]);
    if (shift === 0) {
      assert.doesNotMatch(line, /atrim/);
      assert.doesNotMatch(line, /adelay/);
    } else if (shift < 0) {
      /* the sound ring began FIRST, so its front is trimmed off */
      assert.match(line, /atrim=start=0\.700,asetpts=PTS-STARTPTS/);
      assert.doesNotMatch(line, /adelay/);
    } else {
      /* the sound ring began LATER, so it is held back - and asetpts must
       * come BEFORE adelay or it would reset the delay it just applied */
      assert.match(line, /asetpts=PTS-STARTPTS,adelay=700:all=1/);
      assert.doesNotMatch(line, /atrim/);
    }
    assert.match(line, /aresample=async=1:first_pts=0/,
      'the seams are filled with silence rather than pulling the rest earlier');
    ring.forget();
  }
});

test('the drift that is left is bounded and reported, not hidden', async () => {
  runs.length = 0;
  const ring = ringWith([true, true, true],
    { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true, detail: '' },
    { soundShift: 120 });
  const made = await ring.cut({ seconds: 6, back: 0 }, {});
  assert.equal(made.audio.align_shift_ms, -120);
  /* What is left after the shift is the difference between how long each
   * recorder takes to produce its first sample, and the picture's is the
   * larger: up to one capture interval at 12 frames a second. It is stated
   * so that somebody reading the provenance can tell a bounded offset from
   * an unbounded one. */
  assert.equal(made.audio.align_bound_ms, 83);
  assert.ok(made.audio.align_bound_ms < 125,
    'inside what broadcast practice allows for sound behind picture');
  ring.forget();
});

test('a sound ring that came up LATE is delayed into place, never thrown away', async () => {
  runs.length = 0;
  /* The picture has been rolling for twenty seconds before the sound ring
   * comes up at all - a panel that was slow, or a capture retried on the
   * operator's first click. The shift is huge and it is entirely correct:
   * delaying the sound by that much puts it exactly where it belongs, and
   * refusing it would throw away ten seconds of real broadcast. An earlier
   * draft of this refused it on magnitude alone. */
  const ring = new ScreenRing();
  ring.noteAudio({ source: AUDIO_SOURCE, present: true, state: 'capturing',
    supported: true, detail: '' });
  const at = Date.now() - 30000;
  for (let i = 0; i < 15; i += 1) {
    ring.take(Buffer.from('p' + i), { at: at + (i * 2000), ms: 2000,
      w: 1280, h: 800, a: false, kind: 'v' });
  }
  for (let i = 10; i < 15; i += 1) {
    ring.take(Buffer.from('a' + i), { at: at + (i * 2000), ms: 2000, a: true, kind: 'a' });
  }
  const made = await ring.cut({ seconds: 30, back: 0 }, {});
  assert.equal(made.ok, true);
  assert.equal(made.audio.present, true, 'ten seconds of broadcast is worth keeping');
  assert.equal(made.audio.state, 'partial');
  assert.equal(made.audio.align_shift_ms, -20000, 'the whole twenty seconds of it');
  assert.match(argsOf(runs[0]), /adelay=20000:all=1/,
    'held back by exactly the gap between the two rings\' first stamps');
  assert.ok(Math.abs(made.audio.coverage_ratio - (10 / 30)) < 0.03,
    'coverage ' + made.audio.coverage_ratio);
  ring.forget();
});

test('a stamp further out than the ring can hold is refused, and the cut goes out SILENT', async () => {
  runs.length = 0;
  const ring = ringWith([true, true, true, true],
    { source: AUDIO_SOURCE, present: true, state: 'capturing', supported: true, detail: '' });
  const shot = ring.window(8, 0);
  const heard = ring.window(8, 0, 'sound');
  assert.equal(shot.ok, true);
  assert.equal(heard.ok, true);
  /* Asked directly, because the ring cannot produce this on its own: both
   * windows are pruned to the same wall clock, so a gap larger than the hold
   * means the system clock moved under the recorder and one of these stamps
   * is a fiction. */
  const ceiling = Math.max(ALIGN_MAX_MS, (ring.holdSeconds * 1000) + 2000);
  const audio = ring.soundFor(shot, false, heard, ceiling + 1);
  assert.equal(audio.present, false);
  assert.equal(audio.state, 'unavailable');
  assert.match(audio.detail, /further than the ring can hold/);
  assert.equal(audio.align_shift_ms, null, 'nothing was aligned, so nothing is claimed');
  /* Not "partial". There is no sound in the file at all, and "Audio has gaps"
   * would be a claim that some of it is in there. */
  assert.match(model.audioNotice({ has_audio: false, audio_capture: audio }),
    /No audio was captured in this recording/);
  /* And a shift that is not a number at all is refused the same way, rather
   * than reaching ffmpeg as "atrim=start=NaN". */
  assert.equal(ring.soundFor(shot, false, heard, NaN).present, false);
  ring.forget();
});

/* --------------------------------------------------------------------------
 * WHEN ONE RING DIES ALONE. */

test('a picture ring with no sound ring still cuts, silently, and the provenance says why', async () => {
  runs.length = 0;
  const ring = ringWith([true, true, true],
    { source: AUDIO_SOURCE, present: false, state: 'unavailable', supported: false,
      detail: 'the panel would not give up its sound: Error starting capture' },
    { noSoundRing: true });
  const made = await ring.cut({ seconds: 6, back: 0 }, {});
  assert.equal(made.ok, true, 'the recording is not lost because the sound was');
  assert.ok(made.bytes > 0);
  assert.match(argsOf(runs[0]), /-an/);
  assert.equal(made.audio.present, false);
  assert.equal(made.audio.state, 'unavailable');
  assert.match(made.audio.detail, /would not give up its sound/);
  ring.forget();
});

test('a sound ring with no picture ring produces NOTHING, not a black rectangle', async () => {
  runs.length = 0;
  const ring = new ScreenRing();
  ring.noteAudio({ source: AUDIO_SOURCE, present: true, state: 'capturing',
    supported: true, detail: '' });
  const at = Date.now() - 8000;
  for (let i = 0; i < 4; i += 1) {
    ring.take(Buffer.from('sound ' + i), { at: at + (i * 2000), ms: 2000, a: true, kind: 'a' });
  }
  const made = await ring.cut({ seconds: 8, back: 0 }, {});
  assert.equal(made.ok, false, 'no picture is no recording, whatever the sound ring holds');
  assert.equal(runs.length, 0, 'and the encoder is never even asked');
  assert.match(made.detail, /ring is empty/);
  ring.forget();
});

test('a sound ring that dies half way through is reported as gaps, and the cut still lands', async () => {
  runs.length = 0;
  /* The sound stops after the third piece and never comes back - a panel
   * that reloaded, or a capture that ended underneath the recorder. */
  const ring = ringWith([true, true, true, false, false, false],
    { source: AUDIO_SOURCE, present: false, state: 'unavailable', supported: true,
      detail: 'the broadcast capture ended' });
  const made = await ring.cut({ seconds: 12, back: 0 }, {});
  assert.equal(made.ok, true);
  assert.equal(made.audio.present, true, 'half a broadcast is still a broadcast');
  assert.equal(made.audio.complete, false);
  assert.equal(made.audio.state, 'partial');
  assert.equal(made.audio.gaps, 1);
  assert.ok(Math.abs(made.audio.coverage_ratio - 0.5) < 0.02,
    'coverage ' + made.audio.coverage_ratio);
  assert.match(model.audioNotice({ has_audio: true, audio_capture: made.audio }),
    /Audio has gaps/);
  ring.forget();
});

test('the recorder seams between sound pieces are not reported as gaps', async () => {
  runs.length = 0;
  const ring = new ScreenRing();
  ring.noteAudio({ source: AUDIO_SOURCE, present: true, state: 'capturing',
    supported: true, detail: '' });
  const at = Date.now() - 10000;
  for (let i = 0; i < 5; i += 1) {
    ring.take(Buffer.from('p' + i), { at: at + (i * 2000), ms: 2000,
      w: 1280, h: 800, a: false, kind: 'v' });
    /* Each piece measured 1.97 s of a 2 s stretch: the stop-and-start seam,
     * about 32 ms, which is real and is not a hole in the broadcast. */
    ring.take(Buffer.from('a' + i), { at: at + (i * 2000), ms: 1968, a: true, kind: 'a' });
  }
  const made = await ring.cut({ seconds: 10, back: 0 }, {});
  assert.equal(made.audio.state, 'captured', 'five seams must not read as four gaps');
  assert.equal(made.audio.gaps, 0);
  assert.equal(made.audio.complete, true);
  ring.forget();
});

/* --------------------------------------------------------------------------
 * THE HANDLER'S TWO ANSWERS.
 *
 * main.js cannot be required without Electron, so the request handler is
 * lifted out of it and run for real against fake requests. This is the one
 * place enableLocalEcho can be pinned: it is a single word, it cannot be
 * tested by looking at a recording, and leaving it out silences the
 * operator's station while he is listening to it. */
function liftHandler() {
  const src = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
  const open = src.indexOf('setDisplayMediaRequestHandler((request, callback) => {');
  assert.ok(open > 0, 'the display-media handler must still be findable in main.js');
  const close = src.indexOf('}, { useSystemPicker: false });', open);
  assert.ok(close > open, 'the handler must still close the way it always has');
  const body = src.slice(src.indexOf('{', open + 50) + 1, close);
  return 'function handle(request, callback) {' + body + '}';
}

function handlerWith(frame) {
  const answers = [];
  const logged = [];
  const context = {
    win: { isDestroyed: () => false },
    panelFrameNow: () => frame,
    ringSound: (line) => logged.push(String(line)),
    String, Boolean
  };
  vm.createContext(context);
  vm.runInContext(liftHandler(), context);
  return {
    ask: (videoRequested, audioRequested) => {
      context.handle({ videoRequested, audioRequested },
        (answer) => answers.push(answer));
      return answers[answers.length - 1];
    },
    answers, logged
  };
}

test('an audio-only request is answered with the panel frame AND enableLocalEcho', () => {
  const frame = { url: 'http://10.89.1.246:8096/' };
  const h = handlerWith(frame);
  const got = h.ask(false, true);
  assert.equal(got.audio, frame, 'the panel frame, chosen here and not by the page');
  assert.equal(got.enableLocalEcho, true,
    'WITHOUT THIS the capture MUTES the panel, which is the broadcast the '
    + 'operator is listening to while it records');
  assert.equal(got.video, undefined, 'and no picture, which is what makes it legal');
});

test('a picture request is answered with the window and never with sound', () => {
  const h = handlerWith({ url: 'http://10.89.1.246:8096/' });
  const got = h.ask(true, true);
  assert.ok(got.video, 'the window');
  assert.equal(got.audio, false,
    'said out loud, so nothing can attach sound here behind the sound ring\'s '
    + 'back and put the broadcast in the file twice');
  assert.equal(got.enableLocalEcho, undefined);
});

test('an audio request with no panel to record is refused rather than answered wrongly', () => {
  const h = handlerWith(null);
  const got = h.ask(false, true);
  /* An empty answer is how Electron is told to cancel. Checked by its keys
   * rather than by deepEqual: the handler is run in a vm, so its `{}` is a
   * different realm's Object and would never be deep-strict-equal to ours. */
  assert.equal(Object.keys(got).length, 0, 'better nothing than the wrong room');
  assert.equal(got.audio, undefined);
  assert.equal(got.video, undefined);
  assert.match(h.logged.join(' '), /frame=no/);
});

test('the diagnostic names which stream every negotiation was for', () => {
  const h = handlerWith({ url: 'http://10.89.1.246:8096/' });
  h.ask(false, true);
  h.ask(true, false);
  assert.equal(h.logged.length, 2);
  assert.match(h.logged[0], /^HANDLER sound /);
  assert.match(h.logged[0], /panel=http:\/\/10\.89\.1\.246:8096\//);
  assert.match(h.logged[1], /^HANDLER picture /);
  /* This file is how the fault was finally caught, after every meter in the
   * app said the sound was fine. It has to keep naming both. */
  const main = fs.readFileSync(path.join(__dirname, '../desktop/main.js'), 'utf8');
  assert.match(main, /pinebox-ring-sound\.log/);
  assert.match(main, /BEGIN audio=/);
  assert.match(main, /streams=/);
});
