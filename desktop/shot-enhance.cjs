/* THE TABLET'S SCREEN, ENLARGED AND SHARPENED.
 *
 * "When I capture an image from the tablet, capture it at 2x resolution with
 *  up sampling. I want that image better than it shows on a tablet. I want it
 *  enhanced."
 *
 * The tablet's panel is 1340x800, which is a small picture to paste into a
 * conversation and a smaller one to draw arrows on. Doubling it does not add
 * information - nothing can - but it does stop the viewer's own scaler from
 * being the one that decides how the text looks, and it gives the mark-up
 * window four times the room to work in.
 *
 * THE FILTER CHAIN WAS CHOSEN BY LOOKING AT TEXT, not by reputation. Four
 * ways were run against a real screenshot of the script pane and compared at
 * 1:1 on a strip of body text:
 *
 *   nearest            blocky - every pixel becomes a hard 2x2 square, which
 *                      scores well on any edge measure and reads badly
 *   lanczos            clean but soft; the softest of the four
 *   lanczos + unsharp  the pick: as clean as lanczos with the crispness back
 *   spline + unsharp   near-identical, marginally softer
 *
 * An edge-energy number alone could not separate these - `nearest` measured
 * 8.48 against lanczos+unsharp's 8.42 while looking obviously worse - which
 * is why the decision was made by reading the text.
 *
 * THE SHARPENING IS LUMA ONLY. The chroma amount is deliberately zero:
 * sharpening colour on a screenshot full of coloured text on dark panels
 * produces fringing, and there is no detail in the chroma planes to recover.
 *
 * IT FAILS SOFT. If ffmpeg is not on the machine, or refuses, the ORIGINAL
 * picture is returned rather than nothing - a smaller screenshot is a great
 * deal better than an error where a screenshot should be.
 */
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');

const { findFfmpeg } = require('./clip-mux.cjs');

/* Measured on a 1340x800 screenshot of the script pane - see the note above.
 * unsharp's arguments are luma x, luma y, luma amount, chroma x, chroma y,
 * chroma amount; the trailing zero is what keeps colour out of it. */
const SHARPEN = 'unsharp=5:5:0.8:5:5:0.0';

/* THE WAYS WORTH OFFERING, not every flag ffmpeg accepts.
 *
 * `id` is what travels; `name` is what the operator reads. The order is the
 * order of the dropdown, sharpest-and-cleanest first. */
const WAYS = [
  { id: 'lanczos-sharp', name: 'Lanczos + sharpen',
    note: 'The default. Clean, with the crispness put back.',
    flags: 'lanczos', sharpen: true },
  { id: 'lanczos', name: 'Lanczos',
    note: 'Clean and slightly soft. No sharpening at all.',
    flags: 'lanczos', sharpen: false },
  { id: 'spline-sharp', name: 'Spline + sharpen',
    note: 'Marginally softer than lanczos, and gentler on noise.',
    flags: 'spline', sharpen: true },
  { id: 'bicubic', name: 'Bicubic',
    note: 'The old standby. Softer than lanczos.',
    flags: 'bicubic', sharpen: false },
  { id: 'area', name: 'Area',
    note: 'Smooth and flat. Good for solid panels, poor for text.',
    flags: 'area', sharpen: false },
  { id: 'neighbor', name: 'Nearest (exact pixels)',
    note: 'No blending at all - every pixel becomes a hard square. '
      + 'Honest about what was really captured.',
    flags: 'neighbor', sharpen: false }
];

function wayFor(id) {
  return WAYS.find((way) => way.id === id) || WAYS[0];
}

function scaler(times, id) {
  const way = wayFor(id);
  return 'scale=iw*' + times + ':ih*' + times + ':flags=' + way.flags
    + (way.sharpen ? ',' + SHARPEN : '');
}

function run(exe, args, timeoutMs) {
  return new Promise((resolve, reject) => {
    execFile(exe, args, { maxBuffer: 64 * 1024 * 1024, timeout: timeoutMs || 60000 },
      (error, stdout, stderr) => {
        if (error) return reject(new Error(String(stderr || '') || error.message));
        resolve(String(stdout || '') + String(stderr || ''));
      });
  });
}

/**
 * Return [png] enlarged [times] over, sharpened.
 *
 * Always resolves. The shape carries what actually happened so the caller can
 * say so rather than quietly claiming a size it did not get.
 */
async function enlarge(png, options) {
  /* Eight is the operator's ceiling. Whether it is REACHABLE from this
   * particular picture is the caller's business - see the note at the top on
   * the canvas area limit. */
  const times = Math.max(1, Math.min(8, Math.round((options || {}).times || 2)));
  const out = { png, times: 1, how: wayFor((options || {}).how).id, why: '' };
  if (!png || !png.length || times === 1) return out;

  const tool = findFfmpeg((options || {}).ffmpeg);
  /* Its own folder, so two captures in the same second cannot collide and
   * the clean-up can take the whole thing. */
  const room = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-shot-'));
  const from = path.join(room, 'in.png');
  const to = path.join(room, 'out.png');
  try {
    fs.writeFileSync(from, png);
    await run(tool.path, ['-v', 'error', '-y', '-i', from,
      '-vf', scaler(times, (options || {}).how), to],
      /* Eight times a screenshot is a real amount of work; the one-minute
       * default was written for a double. */
      240000);
    const bigger = fs.readFileSync(to);
    if (bigger && bigger.length > 0) {
      out.png = bigger;
      out.times = times;
    } else {
      out.why = 'the enlarged picture came back empty';
    }
  } catch (error) {
    /* SOFT. A smaller screenshot beats an error where a screenshot should
     * be, and the reason travels with it so the status line can say so. */
    out.why = tool.found
      ? 'it could not be enlarged: ' + error.message
      : 'ffmpeg was not found, so it is at the tablet’s own size';
  } finally {
    try { fs.rmSync(room, { recursive: true, force: true }); }
    catch (error) { /* the temp folder outlives us at worst */ }
  }
  return out;
}

module.exports = { enlarge, SHARPEN, WAYS };
