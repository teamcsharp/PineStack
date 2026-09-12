/* LAYING THE SOUND UNDER THE PICTURE.
 *
 * "Offer a popup where I choose what channels are used for the export and if
 *  the channels are mixed into mono and if I need to gain one of the
 *  channels."
 * "Also when extracting a video allow me to set the in and out points of the
 *  video that's being exported."
 *
 * The recorder brings back three separate things - a silent mp4 from
 * screenrecord, the broadcast as a 48 kHz mono WAV out of PineAir's ring, and
 * the tablet's ear as a 16 kHz mono WAV - and this is what turns the
 * operator's choices into one file.
 *
 * THE VIDEO IS RE-ENCODED, not copied. `-c copy` can only cut on a keyframe,
 * and screenrecord puts them seconds apart on a screen that mostly does not
 * move - so a stream copy would silently round the in-point to somewhere
 * other than where the handle was left. In and out points that are not the
 * ones you set are worse than no trimming at all. At a few seconds of
 * veryfast x264 for a thirty-second tablet screen, exactness is cheap.
 *
 * THE MIC LEADS THE CAMERA, always, because it is started first on purpose.
 * Its offset is therefore negative and the head is trimmed; guessing that the
 * two began together would put the sound out by however long AudioRecord took
 * to open, which was measured at a third of a second and is not constant.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');

/* Where ffmpeg tends to be. The configured path wins, then the ones this
 * machine actually has, then whatever is on PATH - the same shape as
 * terminal-host's tool discovery, for the same reason. */
const FFMPEG_LIKELY = [
  'C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe',
  'C:\\_tools\\ffmpeg\\bin\\ffmpeg.exe',
  path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312',
    'Lib', 'site-packages', 'imageio_ffmpeg', 'binaries'),
  '/usr/bin/ffmpeg',
  '/usr/local/bin/ffmpeg'
];

function findFfmpeg(configured) {
  const tried = [];
  for (const guess of [configured, ...FFMPEG_LIKELY].filter(Boolean)) {
    try {
      const stat = fs.statSync(guess);
      if (stat.isFile()) return { path: guess, found: true, tried };
      if (stat.isDirectory()) {
        /* imageio-ffmpeg names its binary after the version, so the folder
         * is searched rather than a filename being guessed. */
        for (const name of fs.readdirSync(guess)) {
          if (/^ffmpeg.*\.exe$/i.test(name) || name === 'ffmpeg') {
            return { path: path.join(guess, name), found: true, tried };
          }
        }
      }
    } catch (error) { tried.push(guess); }
  }
  return { path: process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg',
    found: false, tried };
}

function run(exe, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    execFile(exe, args, { maxBuffer: 32 * 1024 * 1024, timeout: timeoutMs || 300000 },
      (error, stdout, stderr) => {
        const said = String(stderr || '') + String(stdout || '');
        if (error) {
          /* ffmpeg says everything on stderr including why it refused, and
           * its exit code alone names nothing. */
          return reject(new Error(lastReal(said) || error.message));
        }
        resolve(said);
      });
  });
}

/* The last line of ffmpeg's chatter that is not progress. A failure is
 * usually two lines above a wall of frame counters. */
function lastReal(text) {
  const lines = String(text || '').split('\n').map((l) => l.trim())
    .filter((l) => l && !/^(frame|size|video:|Press \[q\])/.test(l));
  return lines.slice(-2).join(' ').slice(0, 300);
}

function dbToLinear(db) {
  const value = Number(db);
  if (!isFinite(value) || value === 0) return 1;
  return Math.pow(10, value / 20);
}

/* --------------------------------------------------------------------- */

/**
 * Build the ffmpeg arguments for one export.
 *
 * Split out and exported so the filter graph can be read - and tested -
 * without a tablet, a recording, or ffmpeg itself.
 *
 * @param plan.video        path to the silent mp4
 * @param plan.broadcast    {path, offset} or null
 * @param plan.mic          {path, offset} or null
 * @param plan.inPoint      seconds into the video
 * @param plan.outPoint     seconds into the video
 * @param plan.gains        {broadcast, mic} in dB
 * @param plan.mono         true to sum to one channel
 * @param plan.out          where to write
 */
function planArgs(plan) {
  const inAt = Math.max(0, Number(plan.inPoint) || 0);
  const outAt = Math.max(inAt + 0.05, Number(plan.outPoint) || 0);
  const span = outAt - inAt;

  const args = ['-y', '-i', plan.video];
  const parts = [];
  const sources = [];
  let index = 1;

  for (const [name, track] of [['broadcast', plan.broadcast], ['mic', plan.mic]]) {
    if (!track || !track.path) continue;
    const offset = Number(track.offset) || 0;
    args.push('-i', track.path);
    const gain = dbToLinear((plan.gains || {})[name]);
    /* THE TRACK IS PUT ON THE VIDEO'S CLOCK FIRST, then cut with it.
     *
     * `adelay` can only push a track later, so a track that starts EARLY -
     * which the microphone always does - is handled by trimming its head
     * instead. Doing both through one signed number here keeps the two
     * cases from drifting apart as this grows. */
    const lead = offset < 0 ? (-offset) : 0;      /* track began before the video */
    const late = offset > 0 ? offset : 0;         /* track began after it */
    const chain = [];
    if (late > 0) chain.push('adelay=' + Math.round(late * 1000) + ':all=1');
    const from = lead + inAt;
    chain.push('atrim=start=' + from.toFixed(3) + ':end=' + (from + span).toFixed(3));
    chain.push('asetpts=PTS-STARTPTS');
    if (gain !== 1) chain.push('volume=' + gain.toFixed(4));
    /* Every source is made mono here so the mixing below has one shape to
     * deal with rather than four. */
    chain.push('aformat=channel_layouts=mono');
    parts.push('[' + index + ':a]' + chain.join(',') + '[' + name + ']');
    sources.push(name);
    index += 1;
  }

  parts.push('[0:v]trim=start=' + inAt.toFixed(3) + ':end=' + outAt.toFixed(3)
    + ',setpts=PTS-STARTPTS[v]');

  let audioOut = '';
  if (sources.length === 2) {
    if (plan.mono) {
      /* normalize=0 or amix halves everything it touches, and a gain the
       * operator set would be quietly undone by the mixer. */
      parts.push('[' + sources[0] + '][' + sources[1]
        + ']amix=inputs=2:duration=longest:normalize=0[a]');
    } else {
      /* Not mono: the two are kept apart, broadcast left and ear right, so
       * they can still be separated after the fact. */
      parts.push('[' + sources[0] + '][' + sources[1]
        + ']join=inputs=2:channel_layout=stereo[a]');
    }
    audioOut = '[a]';
  } else if (sources.length === 1) {
    audioOut = '[' + sources[0] + ']';
  }

  args.push('-filter_complex', parts.join(';'));
  args.push('-map', '[v]');
  if (audioOut) {
    args.push('-map', audioOut);
    args.push('-c:a', 'aac', '-b:a', '192k');
    if (plan.mono || sources.length === 1) args.push('-ac', '1');
  } else {
    args.push('-an');
  }
  args.push('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
    /* yuv420p or the file will not play in half the things it is sent to,
     * including Windows' own preview. */
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart');
  args.push(plan.out);
  return args;
}

async function mux(plan, options) {
  const tool = findFfmpeg((options || {}).ffmpeg);
  const args = planArgs(plan);
  try {
    await run(tool.path, args, 600000);
  } catch (error) {
    if (!tool.found) {
      throw new Error('ffmpeg was not found on this machine, so the sound '
        + 'could not be laid under the picture (' + error.message + ')');
    }
    throw error;
  }
  let bytes = 0;
  try { bytes = fs.statSync(plan.out).size; } catch (error) { bytes = 0; }
  if (!bytes) throw new Error('ffmpeg finished but wrote nothing');
  return { ok: true, path: plan.out, bytes, ffmpeg: tool.path };
}

/* A place to park the three pieces of one recording while the operator
 * decides what to do with them. One folder per recording so a second
 * recording cannot half-overwrite the first. */
function stash() {
  const dir = path.join(os.tmpdir(), 'pinebox-clip-' + Date.now());
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function forget(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (error) { /* temp */ }
}

module.exports = { planArgs, mux, findFfmpeg, dbToLinear, stash, forget, lastReal };
