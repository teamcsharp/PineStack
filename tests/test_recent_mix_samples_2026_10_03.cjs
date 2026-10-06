'use strict';
// Decode an actual exported MP4 to prove historical levels and stereo survive.
// Exact PCM inputs isolate export fidelity from browser recorder startup/seams.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { ScreenRing } = require('../desktop/screen-ring.cjs');
const mux = require('../desktop/clip-mux.cjs');
const RATE = 48000, SEGMENT_SECONDS = 2, SHELL_LEVEL = 0.04;
const MUSIC_LEVELS = [0.12, 0.03, 0.06, 0, 0.08];
const ffmpeg = mux.findFfmpeg().path;
const probe = spawnSync(ffmpeg, ['-version'], { windowsHide: true, encoding: 'utf8', timeout: 10000 });
const missing = probe.error?.code === 'ENOENT';
if (!missing) {
  assert.equal(probe.error, undefined, 'FFmpeg must be callable: ' + String(probe.error));
  assert.equal(probe.status, 0, probe.stderr);
}
function run(args, binary = false) {
  const result = spawnSync(ffmpeg, ['-hide_banner', '-nostdin', '-y', ...args], {
    windowsHide: true, encoding: binary ? undefined : 'utf8', timeout: 120000,
    maxBuffer: 16 * 1024 * 1024 });
  assert.equal(result.error, undefined, String(result.error));
  assert.equal(result.status, 0, String(result.stderr));
  return result.stdout;
}
function stereoWav(music) {
  const frames = RATE * SEGMENT_SECONDS, bytes = frames * 4;
  const wav = Buffer.alloc(44 + bytes);
  wav.write('RIFF', 0); wav.writeUInt32LE(36 + bytes, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(2, 22);
  wav.writeUInt32LE(RATE, 24); wav.writeUInt32LE(RATE * 4, 28);
  wav.writeUInt16LE(4, 32); wav.writeUInt16LE(16, 34);
  wav.write('data', 36); wav.writeUInt32LE(bytes, 40);
  for (let frame = 0; frame < frames; frame++) {
    const time = frame / RATE;
    for (let channel = 0; channel < 2; channel++) {
      const musicHz = channel ? 880 : 440, shellHz = channel ? 1320 : 660;
      const sample = music * Math.sin(2 * Math.PI * musicHz * time)
        + SHELL_LEVEL * Math.sin(2 * Math.PI * shellHz * time);
      wav.writeInt16LE(Math.round(sample * 32767), 44 + frame * 4 + channel * 2);
    }
  }
  return wav;
}
function measure(pcm, channel, startSeconds, durationSeconds = 0.4) {
  const start = Math.round(startSeconds * RATE), frames = Math.round(durationSeconds * RATE);
  assert.ok((start + frames) * 8 <= pcm.length, 'export must contain the selected measurement interval');
  const frequencies = [440, 660, 880, 1320];
  const sums = frequencies.map(() => [0, 0]);
  let energy = 0;
  for (let frame = 0; frame < frames; frame++) {
    const value = pcm.readFloatLE((start + frame) * 8 + channel * 4);
    energy += value * value;
    for (let i = 0; i < frequencies.length; i++) {
      const phase = 2 * Math.PI * frequencies[i] * frame / RATE;
      sums[i][0] += value * Math.cos(phase); sums[i][1] += value * Math.sin(phase);
    }
  }
  return { rms: Math.sqrt(energy / frames),
    amplitudes: Object.fromEntries(frequencies.map((frequency, i) =>
      [frequency, 2 * Math.hypot(...sums[i]) / frames])) };
}
function close(actual, expected, label, tolerance = Math.max(0.001, expected * 0.05)) {
  assert.ok(Math.abs(actual - expected) <= tolerance,
    label + ': expected ' + expected.toFixed(5) + ', decoded ' + actual.toFixed(5)
      + ', tolerance ' + tolerance.toFixed(5));
}
function inside(parent, candidate) {
  const relative = path.relative(path.resolve(parent), path.resolve(candidate));
  assert.ok(relative && !relative.startsWith('..') && !path.isAbsolute(relative),
    'temporary path must stay under its created parent: ' + candidate);
}

test('recent video preserves each historical stereo mix level and music mute', { skip: missing ? 'FFmpeg is not installed' : false }, async t => {
  const tempParent = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-recent-mix-samples-'));
  inside(os.tmpdir(), tempParent);
  const ring = new ScreenRing(), originalStash = mux.stash;
  let cut;
  try {
    // Place every cache/export artifact inside this test's created temp parent.
    ring.dir = fs.mkdtempSync(path.join(tempParent, 'ring-')); inside(tempParent, ring.dir);
    mux.stash = () => { const dir = fs.mkdtempSync(path.join(tempParent, 'export-')); inside(tempParent, dir); return dir; };
    ring.setHold(60);
    ring.noteAudio({ source: 'desk-application-frames', present: true, complete: true, supported: true });
    const videoFile = path.join(tempParent, 'picture.webm');
    run(['-f', 'lavfi', '-i', 'color=c=navy:s=320x180:r=30:d=2',
      '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8', '-b:v', '300k', '-an', videoFile]);
    const picture = fs.readFileSync(videoFile);
    const endAt = Date.now() - 1000, base = endAt - MUSIC_LEVELS.length * SEGMENT_SECONDS * 1000;
    for (let segment = 0; segment < MUSIC_LEVELS.length; segment++) {
      const at = base + segment * SEGMENT_SECONDS * 1000;
      assert.equal(ring.take(picture, { at, ms: 2000, kind: 'v', w: 320, h: 180,
        fps: 30, requested_fps: 30, mime: 'video/webm;codecs=vp8' }).ok, true);
      assert.equal(ring.take(stereoWav(MUSIC_LEVELS[segment]), { at, ms: 2000, kind: 'a',
        a: true, audio_complete: true, mime: 'audio/wav' }).ok, true);
    }
    // Live capture status can change afterward; the requested mix is already saved.
    ring.noteAudio({ source: 'desk-application-frames', present: false, complete: false,
      state: 'unavailable', detail: 'Monitor settings changed after this captured interval.' });
    cut = await ring.cut({ seconds: 10, end_at: endAt }, { encoder: 'cpu', ffmpeg });
    assert.equal(cut.ok, true, cut.detail); inside(tempParent, cut.dir); inside(cut.dir, cut.out);
    assert.equal(cut.seconds, 10); assert.equal(cut.audio.present, true); assert.equal(cut.audio.complete, true);
    assert.equal(cut.video.encoder, 'libx264'); assert.equal(cut.video.hardware, false);
    const pcm = run(['-i', cut.out, '-vn', '-ar', String(RATE), '-ac', '2',
      '-c:a', 'pcm_f32le', '-f', 'f32le', '-'], true);
    assert.ok(Math.abs(pcm.length / (RATE * 8) - 10) < 0.05, 'decoded duration must match the selected ten seconds');
    const reports = [];
    for (let segment = 0; segment < MUSIC_LEVELS.length; segment++) {
      const expected = MUSIC_LEVELS[segment], at = segment * SEGMENT_SECONDS + 0.8;
      const left = measure(pcm, 0, at), right = measure(pcm, 1, at);
      for (const [name, channel, musicHz, shellHz, oppositeMusicHz, oppositeShellHz] of [
        ['left', left, 440, 660, 880, 1320], ['right', right, 880, 1320, 440, 660]
      ]) {
        const label = 'segment ' + segment + ' ' + name;
        close(channel.amplitudes[musicHz], expected, label + ' historical music level');
        close(channel.amplitudes[shellHz], SHELL_LEVEL, label + ' simultaneous shell level');
        close(channel.rms, Math.hypot(expected, SHELL_LEVEL) / Math.sqrt(2), label + ' combined mix RMS');
        close(channel.amplitudes[oppositeMusicHz], 0, label + ' opposite music channel leakage');
        close(channel.amplitudes[oppositeShellHz], 0, label + ' opposite shell channel leakage');
      }
      reports.push({ segment, music: expected,
        leftMusic: Number(left.amplitudes[440].toFixed(5)), rightMusic: Number(right.amplitudes[880].toFixed(5)),
        leftShell: Number(left.amplitudes[660].toFixed(5)), rightShell: Number(right.amplitudes[1320].toFixed(5)) });
    }
    t.diagnostic(JSON.stringify(reports));
  } finally {
    mux.stash = originalStash;
    if (cut?.dir) { inside(tempParent, cut.dir); mux.forget(cut.dir); }
    if (ring.dir) inside(tempParent, ring.dir);
    ring.forget();
    inside(os.tmpdir(), tempParent);
    fs.rmSync(tempParent, { recursive: true, force: true });
  }
});
