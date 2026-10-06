'use strict';
// Actual codecs, decoded flash/pulse content, independent recorder boundaries,
// resize seams and a nonzero seek. Requires installed ffmpeg/ffprobe.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { ScreenRing } = require('../desktop/screen-ring.cjs');
const mux = require('../desktop/clip-mux.cjs');
const { verifyRecording } = require('../tools/verify_pip_recording.cjs');
const ffmpeg = mux.findFfmpeg().path;
const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-pip-sync-media-'));
const originalNow = Date.now, reports = [];
function run(args, binary = false) {
  const got = spawnSync(ffmpeg, ['-hide_banner', '-nostdin', '-y', ...args], {
    windowsHide: true, encoding: binary ? undefined : 'utf8',
    timeout: 120000, maxBuffer: 64 * 1024 * 1024 });
  if (got.error) throw got.error;
  assert.equal(got.status, 0, String(got.stderr));
  return got.stdout;
}
function signal(offset) {
  return 'between(mod(t+' + offset.toFixed(6) + '+100,1),0.4,0.5)';
}
function onsets(values, sampleRate, threshold, minGap) {
  const starts = [];
  let on = false, last = -Infinity;
  for (let i = 0; i < values.length; i++) {
    const active = values[i] > threshold;
    if (active && !on && i / sampleRate - last > minGap) {
      starts.push(i / sampleRate); last = i / sampleRate;
    }
    on = active;
  }
  return starts;
}
function measureMarks(file) {
  const gray = run(['-i', file, '-an', '-vf', 'crop=8:8:0:0,scale=1:1:flags=area,format=gray',
    '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], true);
  const pcm = run(['-i', file, '-vn', '-ac', '1', '-ar', '48000', '-c:a', 'pcm_f32le', '-f', 'f32le', '-'], true);
  const energy = [];
  const block = 48; // One millisecond RMS, avoiding every sine zero crossing.
  for (let start = 0; start + block * 4 <= pcm.length; start += block * 4) {
    let sum = 0;
    for (let j = 0; j < block; j++) { const x = pcm.readFloatLE(start + j * 4); sum += x * x; }
    energy.push(Math.sqrt(sum / block));
  }
  return { video: onsets([...gray], 60, 180, .3), audio: onsets(energy, 1000, .1, .3) };
}
async function scenario(audioOffset) {
  const ring = new ScreenRing();
  const made = [];
  ring.setHold(60);
  ring.noteAudio({ present: true, supported: true });
  const base = originalNow() - 20000;
  Date.now = () => base + 8000; // One exact common interval, independent of encoder runtime.
  try {
    for (let i = 0; i < 4; i++) {
      const height = i < 2 ? 181 : 183;
      const video = path.join(folder, 'v' + i + '.webm');
      // Odd native pixel dimensions deliberately exercise padding rather than resizing.
      run(['-f', 'lavfi', '-i', 'testsrc=size=321x' + height + ':rate=60:duration=1.97',
        '-vf', "drawbox=color=black:t=fill,drawbox=color=white:t=fill:enable='" + signal(i * 2) + "'",
        '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8', '-b:v', '1M', '-an', video]);
      const accepted = ring.take(fs.readFileSync(video), { at: base + i * 2000, ms: 2000,
        w: 321, h: height, fps: 60, requested_fps: 60, kind: 'v', view: 'pip' });
      assert.equal(accepted.ok, true);
    }
    for (let i = 0; i < 5; i++) {
      const offset = i * 2 + audioOffset;
      const audio = path.join(folder, 'a' + i + '.webm');
      run(['-f', 'lavfi', '-i', 'aevalsrc=if(' + signal(offset).replace(/,/g, '\\,') +
        '\\,0.65*sin(2*PI*1500*t)\\,0):s=48000:d=1.97',
        '-c:a', 'libopus', '-b:a', '128k', '-ac', '2', audio]);
      assert.equal(ring.take(fs.readFileSync(audio), { at: base + Math.round(offset * 1000),
        ms: 2000, a: true, kind: 'a' }).ok, true);
    }
    const cut = await ring.cut({ seconds: 5.6, back: 1.15, view: 'pip' }, { encoder: 'cpu' });
    made.push(cut);
    assert.equal(cut.ok, true, cut.detail);
    assert.equal(cut.audio.present, true, cut.audio.detail);
    assert.equal(cut.audio.complete, true, cut.audio.detail);
    assert.equal(cut.w, 322); assert.equal(cut.h, 184);
    const report = verifyRecording(cut.out, { fps: 60, width: 322, height: 184,
      requireAudio: true, videoCodec: 'h264', audioCodec: 'aac', requireFastStart: true, maxSkewMs: 30 });
    assert.equal(report.ok, true, JSON.stringify(report.problems));
    assert.equal(report.streams.find(s => s.type === 'video').decodedFrames, 336);
    assert.ok(Math.abs(report.durationSeconds - 5.6) <= .03);
    const marks = measureMarks(cut.out);
    const expected = [.15, 1.15, 2.15, 3.15, 4.15, 5.15];
    assert.equal(marks.video.length, expected.length, JSON.stringify(marks));
    assert.equal(marks.audio.length, expected.length, JSON.stringify(marks));
    const skews = [];
    for (let i = 0; i < expected.length; i++) {
      assert.ok(Math.abs(marks.video[i] - expected[i]) < .025, 'Video mark moved across seam: ' + JSON.stringify(marks));
      assert.ok(Math.abs(marks.audio[i] - expected[i]) < .025, 'Audio mark moved across seam: ' + JSON.stringify(marks));
      skews.push((marks.audio[i] - marks.video[i]) * 1000);
    }
    assert.ok(Math.max(...skews) - Math.min(...skews) < 10, 'Growing A/V drift: ' + JSON.stringify(skews));
    // Native content remains at the same pixel position through the resize.
    const border = run(['-i', cut.out, '-an', '-vf', 'crop=2:2:100:180,scale=1:1:flags=area,format=gray',
      '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], true);
    assert.ok(border[Math.round(marks.video[0] * 60)] < 200, 'Small source must retain black padding at bottom.');
    assert.ok(border[Math.round(marks.video[3] * 60)] > 220, 'Larger source must retain its bottom native pixels: ' + JSON.stringify({marks, value: border[Math.round(marks.video[3]*60)], values: [...border.slice(Math.round(marks.video[3]*60),Math.round(marks.video[3]*60)+8)]}));
    const audioCut = await ring.cutAudio({ seconds: 5.6, back: 1.15 });
    made.push(audioCut);
    assert.equal(audioCut.ok, true, audioCut.detail);
    const wavReport = verifyRecording(audioCut.out, { requireVideo: false, requireAudio: true, audioCodec: 'pcm_s16le' });
    assert.equal(wavReport.ok, true, JSON.stringify(wavReport.problems));
    assert.ok(Math.abs(wavReport.durationSeconds - 5.6) < .001);
    reports.push({ audioOffset, duration: report.durationSeconds, fps: 60, dimensions: [cut.w, cut.h],
      encoder: cut.video?.encoder, marks, skewMs: skews, streamBoundarySkew: report.streamBoundarySkew });
  } finally {
    Date.now = originalNow;
    for (const clip of made) if (clip?.dir) mux.forget(clip.dir);
    ring.forget();
  }
}
async function colors() {
  const ring = new ScreenRing(), made = [];
  const base = originalNow() - 4000;
  Date.now = () => base + 2000;
  try {
    const source = path.join(folder, 'colors.webm');
    run(['-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=60:duration=2',
      '-vf', 'drawbox=x=0:y=0:w=106:h=180:color=red:t=fill,drawbox=x=106:y=0:w=106:h=180:color=lime:t=fill,drawbox=x=212:y=0:w=108:h=180:color=blue:t=fill',
      '-c:v', 'libvpx', '-deadline', 'realtime', '-cpu-used', '8', '-b:v', '1M', '-an', source]);
    ring.take(fs.readFileSync(source), { at: base, ms: 2000, w: 320, h: 180, fps: 60, view: 'pip' });
    const cut = await ring.cut({ seconds: 1, back: .5, view: 'pip', video_only: true }, { encoder: 'cpu' });
    made.push(cut);
    assert.equal(cut.ok, true, cut.detail);
    const patches = [];
    for (const x of [32, 138, 244]) {
      const decode = file => [...run(['-i', file, '-an', '-vf',
        'crop=16:16:' + x + ':20,scale=1:1:flags=area,format=rgb24',
        '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], true)];
      const before = decode(source), after = decode(cut.out);
      assert.equal(before.length, 3); assert.equal(after.length, 3);
      const maximumError = Math.max(...before.map((v, i) => Math.abs(v - after[i])));
      assert.ok(maximumError <= 8, 'Color matrix changed source colors: ' + JSON.stringify({ before, after, maximumError }));
      patches.push({ before, after, maximumError });
    }
    reports.push({ colors: patches });
  } finally {
    Date.now = originalNow;
    for (const clip of made) if (clip?.dir) mux.forget(clip.dir);
    ring.forget();
  }
}
(async () => {
  await scenario(-.2);
  await scenario(.2);
  await colors();
  console.log(JSON.stringify({ ok: true, scenarios: reports }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => {
  Date.now = originalNow;
  fs.rmSync(folder, { recursive: true, force: true });
});

