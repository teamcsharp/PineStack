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

/* H.264 4:2:0 requires even dimensions. Pad by at most one pixel so every
 * native source pixel survives; scaling or rounding down blurs/crops text. */
const EVEN = 'pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:color=black';

/* SAYING WHAT COLOUR THE FILE IS.
 *
 * An untagged h264 stream is read as BT.601 by ffmpeg and BT.709 by VLC, the
 * browsers, and most hardware decoders. Measured on a nine-patch chart, that
 * disagreement is 23 levels on green and 15 on red - plainly visible on skin.
 * Every check run from this side looked clean precisely because ffmpeg was
 * agreeing with itself.
 *
 * BT.709 limited is the right answer for HD and, better, it is what the
 * players that IGNORE tags already assume - so the file comes out correct
 * whether or not anything reads these. */
const SAY_COLOUR = ['-colorspace', 'bt709', '-color_primaries', 'bt709',
  '-color_trc', 'bt709', '-color_range', 'tv'];

/* AND CONVERTING TO IT, where the source is not already there.
 *
 * A canvas JPEG is FULL-RANGE BT.601. Handing that to libx264 as plain
 * yuv420p converts nothing, so the levels were being stretched by a player
 * that thought they were limited-range 709. This names both ends. */
const TO_709 = 'scale=in_color_matrix=bt601:out_color_matrix=bt709'
  + ':in_range=pc:out_range=tv';

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

/* [pip-export-bar] ffmpeg's -progress report, line by line, as seconds written so far.
 * out_time_us and out_time_ms are both microseconds (ffmpeg's own quirk); out_time is a clock. */
function progressFeed(onProgress) {
  let rest = '';
  return chunk => {
    rest += String(chunk);
    const lines = rest.split(/\r?\n/); rest = lines.pop();
    for (const line of lines) {
      const micro = /^out_time_(?:us|ms)=(\d+)\s*$/.exec(line);
      const clock = micro ? null : /^out_time=(\d+):(\d+):(\d+(?:\.\d+)?)\s*$/.exec(line);
      const seconds = micro ? Number(micro[1]) / 1e6 : clock ? Number(clock[1]) * 3600 + Number(clock[2]) * 60 + Number(clock[3]) : null;
      if (seconds !== null && Number.isFinite(seconds)) { try { onProgress(seconds); } catch (_) { /* a listener's slip never stops the encode */ } }
    }
  };
}

function run(exe, args, timeoutMs, onProgress) {
  const told = typeof onProgress === 'function' ? onProgress : null;
  /* [pip-export-bar] with a listener, ffmpeg writes its clock to stdout and nothing else goes there */
  const spawnArgs = told ? ['-progress', 'pipe:1', '-nostats', ...args] : args;
  return new Promise((resolve, reject) => {
    const worker = execFile(exe, spawnArgs, { windowsHide: true, maxBuffer: 32 * 1024 * 1024, timeout: timeoutMs || 300000 },
      (error, stdout, stderr) => {
        const said = String(stderr || '') + String(stdout || '');
        if (error) {
          /* ffmpeg says everything on stderr including why it refused, and
           * its exit code alone names nothing. */
          return reject(new Error(lastReal(said) || error.message));
        }
        resolve(said);
      });
    if (told && worker?.stdout) worker.stdout.on('data', progressFeed(told));
    // Exports yield CPU time to the live display/audio when the host is busy.
    // A driver/policy that refuses priority changes must not break an export.
    try {
      if (worker?.pid) os.setPriority(worker.pid, os.constants.priority.PRIORITY_BELOW_NORMAL);
    } catch (error) { /* best effort for a worker that may already have exited */ }
  });
}

/* The last line of ffmpeg's chatter that is not progress. A failure is
 * usually two lines above a wall of frame counters. */
function lastReal(text) {
  const lines = String(text || '').split('\n').map((l) => l.trim())
    .filter((l) => l && !/^(frame|size|video:|Press \[q\])/.test(l));
  /* SIX LINES, NOT TWO. ffmpeg's closing complaint is usually a symptom -
   * "at least one of its streams received no packets" - while the sentence
   * that says WHY sits several lines above it. Two lines was enough to know
   * that something had failed and never enough to know what. */
  const causes = lines.filter(line => /InitializeEncoder|Cannot load|No capable|unsupported|not supported|Unknown encoder|No such file|Permission denied|Frame Dimension|Error initializing|Error opening|Invalid data/i.test(line));
  const said = [...new Set([...causes.slice(0, 2), ...lines.slice(-6)])];
  const useful = said.filter(
    (l) => !/^(ffmpeg version|built with|configuration:)/.test(l));
  return (useful.length ? useful : said).join(' | ').slice(0, 900);
}

/* Probe a real frame, not just the encoder list: a compiled hardware encoder
 * can still lack a driver/device. Share probes across concurrent exports. */
const encoderProbes = new Map();
const HARDWARE_ENCODERS = ['h264_nvenc', 'h264_qsv', 'h264_amf'];
function encoderArgs(encoder) {
  if (encoder === 'h264_nvenc') return ['-c:v', encoder, '-preset', 'p5', '-tune', 'hq', '-rc', 'vbr', '-cq', '18', '-b:v', '0'];
  if (encoder === 'h264_qsv') return ['-c:v', encoder, '-preset', 'medium', '-global_quality', '18'];
  if (encoder === 'h264_amf') return ['-c:v', encoder, '-quality', 'quality', '-rc', 'cqp', '-qp_i', '18', '-qp_p', '18', '-qp_b', '20'];
  return ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18'];
}
async function availableEncoders(exe, options) {
  const mode = String((options || {}).encoder || 'auto');
  if (mode === 'cpu' || mode === 'libx264') return { encoders: ['libx264'], failures: [] };
  const key = exe + ':' + mode;
  if (!encoderProbes.has(key)) encoderProbes.set(key, (async () => {
    const encoders = [], failures = [];
    const candidates = HARDWARE_ENCODERS.includes(mode) ? [mode] : HARDWARE_ENCODERS;
    for (const encoder of candidates) {
      try {
        await run(exe, ['-hide_banner', '-nostdin', '-v', 'error', '-f', 'lavfi',
          '-i', 'color=c=black:s=640x360:r=60', '-frames:v', '1', '-an',
          ...encoderArgs(encoder), '-pix_fmt', 'yuv420p', '-f', 'null', '-'], 15000);
        encoders.push(encoder);
        break; // One working GPU plus the CPU fallback is enough; do not probe idle vendors.
      } catch (error) { failures.push(encoder + ': ' + error.message); }
    }
    return { encoders: [...encoders, 'libx264'], failures };
  })());
  return encoderProbes.get(key);
}
async function encodeVideo(exe, build, options) {
  const available = await availableEncoders(exe, options);
  const failures = [];
  for (const encoder of available.encoders) {
    try {
      await run(exe, build(encoder), (options || {}).timeoutMs || 600000, (options || {}).onProgress);
      return { encoder, hardware: encoder !== 'libx264',
        fallback_detail: [...(encoder === 'libx264' ? available.failures : []), ...failures].join(' | '), probe_failures: available.failures };
    } catch (error) {
      failures.push(encoder + ': ' + error.message);
      // Retry the SAME inputs and audio graph with the next encoder.
    }
  }
  throw new Error('The recording could not be encoded: ' + failures.join(' | '));
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
 * @param plan.video        path to the mp4
 * @param plan.embeddedAudio keep the captured playback track from this mp4
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

  if (plan.embeddedAudio) {
    const chain = ['atrim=start=' + inAt.toFixed(3) + ':end=' + outAt.toFixed(3), 'asetpts=PTS-(' + inAt.toFixed(3) + ')/TB'];
    const gain = dbToLinear((plan.gains || {}).broadcast);
    if (gain !== 1) chain.push('volume=' + gain.toFixed(4));
    if (plan.mono) chain.push('aformat=channel_layouts=mono');
    parts.push('[0:a]' + chain.join(',') + '[broadcast]');
    sources.push('broadcast');
  }

  for (const [name, track] of [['broadcast', plan.broadcast], ['mic', plan.mic]]) {
    if (!track || !track.path || (plan.embeddedAudio && name === 'broadcast')) continue;
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

  /* EVEN DIMENSIONS, ALWAYS. libx264 with yuv420p cannot encode an odd width
   * or height, and it does not say so: it fails with "Could not open encoder
   * before EOF" and a generic library error, which reads as though the frames
   * were the problem. The desktop window this may be recording is whatever
   * size the operator dragged it to - measured at 1983x1234 on the run that
   * found this - so roughly half of all window sizes would have failed. The
   * tablet is 1340x800 and would never have shown it. */
  /* Crop first, then pad only the missing even edge. The source pixels
   * retain their size and the last native row/column survives. */
  const cut = [];
  const crop = plan.crop;
  if (crop && Number(crop.w) > 0 && Number(crop.h) > 0) {
    cut.push('crop=' + Math.round(crop.w) + ':' + Math.round(crop.h)
      + ':' + Math.round(crop.x) + ':' + Math.round(crop.y));
  }

  /* THE ENHANCEMENT CHAIN, IN THE ONLY ORDER THAT MAKES SENSE.
   *
   *   denoise first - motion estimation FOLLOWS noise and will invent
   *     motion that is not there, so cleaning before interpolating is the
   *     difference between smoothing and smearing.
   *   interpolate second - mi_mode=mci with aobmc is real motion
   *     compensation, optical flow doing the work, rather than frames being
   *     duplicated. This is "fill in the frames", and it is what makes a
   *     12 fps screen recording watchable.
   *   upres last - enlarging first would make every filter above it pay
   *     four times the pixels for no more information. */
  const fix = plan.enhance || {};

  if (fix.denoise) {
    /* hqdn3d and not nlmeans: nlmeans is better and is MINUTES per clip,
     * which is the wrong trade for something somebody wants to paste. The
     * numbers are luma/chroma, spatial then temporal - gentle, because a
     * screen recording's "noise" is compression mush and over-denoising it
     * turns text into wax. */
    cut.push(fix.denoise === 'strong'
      ? 'hqdn3d=4:3:6:4.5' : 'hqdn3d=2:1.5:3:2.5');
  }

  const toFps = Number(fix.fps) || 0;
  if (toFps > 0) {
    /* mci = motion-compensated interpolation. aobmc = adaptive overlapped
     * block motion compensation, which is what stops the block edges from
     * showing. vsbmc lets the block size vary, which matters on a screen
     * where a cursor moves against a still background. */
    cut.push('minterpolate=fps=' + toFps
      + ':mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1');
  }

  const bigger = Number(fix.times) || 1;
  if (bigger > 1) {
    cut.push('scale=iw*' + bigger + ':ih*' + bigger + ':flags=lanczos');
    cut.push('unsharp=5:5:0.8:5:5:0.0');
  }
  parts.push('[0:v]trim=start=' + inAt.toFixed(3) + ':end=' + outAt.toFixed(3)
    + ',' + (plan.embeddedAudio ? 'setpts=PTS-(' + inAt.toFixed(3) + ')/TB' : 'setpts=PTS-STARTPTS')
    + ',' + (cut.length ? cut.join(',') + ',' : '')
    + EVEN + '[v]');

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
    if (plan.mono || (sources.length === 1 && !plan.embeddedAudio)) args.push('-ac', '1');
  } else {
    args.push('-an');
  }
  /* The tablet's own recording arrives tagged BT.709 limited, so here this
   * is the tag and not a conversion - but without it the tag was being
   * dropped on the way out and the file became a guess again. */
  args.push(...SAY_COLOUR);
  args.push(...encoderArgs(plan.encoder),
    /* yuv420p or the file will not play in half the things it is sent to,
     * including Windows' own preview. */
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart');
  args.push(plan.out);
  return args;
}

async function mux(plan, options) {
  const tool = findFfmpeg((options || {}).ffmpeg);
  let encoding;
  try {
    encoding = await encodeVideo(tool.path, encoder => planArgs({ ...plan, encoder }), options);
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
  return { ok: true, path: plan.out, bytes, ffmpeg: tool.path, encoding };
}

/* A place to park the three pieces of one recording while the operator
 * decides what to do with them. One folder per recording so a second
 * recording cannot half-overwrite the first. */
function stash() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pinebox-clip-'));
  return dir;
}

function forget(dir) {
  try { fs.rmSync(dir, { recursive: true, force: true }); } catch (error) { /* temp */ }
}

/* FRAMES INTO A VIDEO. The local recorder has no encoder of its own - it
 * takes stills off the window on a timer - so ffmpeg is handed the sequence
 * and told how fast it was taken.
 *
 * `-framerate` BEFORE the input, which is the rate the stills were TAKEN at;
 * `-r 30` after it, which is the rate the file plays at. Giving only the
 * first produces a file whose timebase is 10fps, and several players will
 * show that as a slideshow or refuse to scrub it. */
async function fromFrames({ dir, pattern, fps, out }, options) {
  const tool = findFfmpeg((options || {}).ffmpeg);
  const args = ['-y', '-framerate', String(fps || 10),
    /* THE NUMBERING STARTS AT ONE. Without this the image2 demuxer looks for
     * frame zero, finds nothing, and ffmpeg exits with "at least one of its
     * streams received no packets" - which reads like the frames are missing
     * when every one of them is sitting right there. */
    '-start_number', '1',
    '-i', path.join(dir, pattern || 'f%06d.jpg'),
    /* The frames are canvas JPEGs - full-range BT.601 - and the file is read
     * as limited-range BT.709. Both ends named, then declared. */
    '-r', '30', '-vf', EVEN + ',' + TO_709,
    ...SAY_COLOUR,
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out];
  await run(tool.path, args, 600000);
  let bytes = 0;
  try { bytes = fs.statSync(out).size; } catch (error) { bytes = 0; }
  if (!bytes) throw new Error('the frames would not encode');
  return { ok: true, path: out, bytes };
}

module.exports = { planArgs, mux, findFfmpeg, dbToLinear, stash, forget, lastReal, progressFeed,
  /* #1182: the screen ring runs its own concat and its own frame pull, and
   * it must use THIS runner - the one that turns ffmpeg's wall of chatter
   * into the one line that says why it refused. A second execFile beside it
   * would report exit codes, which name nothing. */
  run, encoderArgs, availableEncoders, encodeVideo,
  fromFrames };
