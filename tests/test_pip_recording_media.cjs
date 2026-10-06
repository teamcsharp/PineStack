// Run with an installed ffmpeg/ffprobe to verify playable files and real audio.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { execFileSync } = require('node:child_process');
const { ScreenRing } = require('../desktop/screen-ring.cjs');
const mux = require('../desktop/clip-mux.cjs');
const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-media-check-'));
const ffmpeg = mux.findFfmpeg().path;
const ring = new ScreenRing();
let audio, video;
const run = args => execFileSync(ffmpeg, ['-hide_banner', '-nostdin', '-y', ...args], { windowsHide: true, stdio: 'pipe', timeout: 60000 });
(async () => {
  const picture = path.join(folder, 'picture.webm'), sound = path.join(folder, 'sound.webm');
  run(['-f', 'lavfi', '-i', 'color=c=green:s=160x90:r=25:d=2', '-c:v', 'libvpx', '-an', picture]);
  run(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2',
    '-f', 'lavfi', '-i', 'sine=frequency=660:sample_rate=48000:duration=2',
    '-filter_complex', 'amix=inputs=2', '-c:a', 'libopus', '-ac', '2', sound]);
  ring.noteAudio({ present: true, supported: true });
  const at = Date.now() - 4000;
  for (let i = 0; i < 2; i++) {
    ring.take(fs.readFileSync(picture), { at: at + i * 2000, ms: 2000, w: 160, h: 90, a: false, kind: 'v' });
    ring.take(fs.readFileSync(sound), { at: at + i * 2000, ms: 2000, a: true, kind: 'a' });
  }
  const windowEnd = at + 4000;
  audio = await ring.cutAudio({ seconds: 4, back: (Date.now() - windowEnd) / 1000 });
  video = await ring.cut({ seconds: 4, back: (Date.now() - windowEnd) / 1000 });
  assert.equal(audio.ok, true, audio.detail); assert.equal(video.ok, true, video.detail);
  for (const made of [audio, video]) {
    assert.equal(made.audio.complete, true);
    const info = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', made.out], { windowsHide: true, encoding: 'utf8' }));
    const track = info.streams.find(stream => stream.codec_type === 'audio');
    assert.ok(track, 'export must contain a decodable audio track'); assert.equal(track.channels, 2);
    assert.ok(Number(info.format.duration) >= 3.5);
    assert.equal(track.codec_name, made === audio ? 'pcm_s16le' : 'aac');
    if (made === video) assert.equal(info.streams.find(stream => stream.codec_type === 'video').codec_name, 'h264');
    const measured = require('node:child_process').spawnSync(ffmpeg, ['-hide_banner', '-i', made.out, '-vn', '-af', 'volumedetect', '-f', 'null', '-'], { windowsHide: true, encoding: 'utf8' });
    assert.equal(measured.status, 0); assert.match(measured.stderr, /mean_volume: -\d+(?:\.\d+)? dB/);
  }
  ring.pieces[0].view = 'pip'; ring.pieces[1].view = 'app';
  const pip = await ring.cut({seconds:4,view:'pip'});
  try {
    assert.equal(pip.ok,true,pip.detail);assert.equal(pip.audio.complete,true);
    const info=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-show_format','-of','json',pip.out],{windowsHide:true,encoding:'utf8'}));
    assert.ok(info.streams.some(s=>s.codec_type==='video'&&s.codec_name==='h264'));
    assert.ok(info.streams.some(s=>s.codec_type==='audio'&&s.codec_name==='aac'));
    assert.ok(Number(info.format.duration)>1.7&&Number(info.format.duration)<2.3,'historical PiP retains its synchronized audio, excluding the later app piece');
  } finally {if(pip.dir)mux.forget(pip.dir);}
  console.log('Real media: broadcast WAV and H.264/AAC MP4 decoded with stereo audio, measured nonzero sound and correct duration');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => {
  if (audio?.dir) mux.forget(audio.dir); if (video?.dir) mux.forget(video.dir); ring.forget();
  fs.rmSync(folder, { recursive: true, force: true });
});
