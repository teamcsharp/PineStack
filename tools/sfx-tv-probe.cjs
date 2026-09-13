/* DOES THE SET ACTUALLY CLOSE INTO A LINE?
 *
 * "I want it to close out like a CRT television where it just closes into
 *  a line and disappears. So it just opens up like a CRT TV and closes
 *  like a CRT TV."
 *
 * That is a claim about what a transform does over half a second, and no
 * unit test can answer it: the tests prove the `on` and `off` classes are
 * put on the right element at the right moment, which is true of a
 * stylesheet that animates nothing at all. A screenshot is no better - it
 * catches one instant of a 460ms animation, and the interesting instant is
 * the one nobody times correctly by hand.
 *
 * So this drives a real browser and SAMPLES getComputedStyle(tube) every
 * 30ms through the whole life of one clip, then reads the matrix:
 *
 *   opening    scaleY climbs from ~0 to 1        (a line pulled open)
 *   picture    scaleX and scaleY both at 1
 *   closing    scaleY collapses back towards 0   (a picture into a line)
 *   gone       scaleX collapses too, opacity 0   (a line into a dot)
 *
 * and it insists the WIDTH survives the height on the way out - which is
 * the difference between a CRT and a window that simply shrinks. It also
 * checks the frame's own left/top never move, because the frame's geometry
 * is the operator's saved position and an animation that touched it would
 * overwrite that fifty times a second.
 *
 *   node tools/sfx-tv-probe.cjs [base-url]
 *
 * Needs Chrome or Edge and Node 22+ (for the built-in WebSocket). Exits
 * non-zero if the set never came on, never went off, or went off the wrong
 * way, so it can gate a deploy.
 */
'use strict';
const {spawn} = require('node:child_process');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');

const BASE = process.argv[2] || 'http://10.89.1.246:8096';
const PORT = 9336;

const CHROMES = [
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium'
];

/* A two-second 320x240 test card with a 440Hz tone, so the probe owns its
 * own clip and does not need one to exist in the operator's library. Built
 * by tools/sfx-tv-probe-clip.py; embedded because a probe that depends on
 * a file somebody has to place first is a probe nobody runs. */
const CLIP = fs.readFileSync(path.join(__dirname, 'sfx-tv-probe-clip.b64'), 'utf8')
  .replace(/\s+/g, '');

/* Runs INSIDE the page. Opens the set with a clip of its own and samples
 * the tube's real computed transform all the way through. */
const PROBE = `(async function () {
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  if (typeof djVideoTv !== 'function') {
    return {ok: null, why: 'this page has no television (djVideoTv missing)'};
  }
  /* The panel yields to the desktop shell when it is inside the app; in a
   * plain browser it owns the set, which is what is being measured. */
  var frames = [];
  var moved = false;
  djVideoTv({ts: Date.now(), url: 'data:video/mp4;base64,' + CLIP_B64,
             sting: 'CRT probe', video: true, seconds: 2,
             broadcastAt: Date.now()});

  var box = null;
  for (var i = 0; i < 60 && !box; i += 1) {
    box = document.getElementById('pineWin-sfxTv');
    if (!box) await wait(30);
  }
  if (!box) return {ok: false, why: 'the set never opened'};
  var tube = box.querySelector('.sfx-tv-tube');
  if (!tube) return {ok: false, why: 'the window opened with no tube in it'};
  var anchor = {left: box.offsetLeft, top: box.offsetTop};

  function scale() {
    var s = getComputedStyle(tube);
    var m = new DOMMatrixReadOnly(s.transform === 'none' ? '' : s.transform);
    return {x: Math.abs(m.a), y: Math.abs(m.d),
            opacity: Number(s.opacity), at: performance.now()};
  }

  /* Sample the whole life of the clip: ~0.45s of opening, 2s of picture,
     ~0.5s of collapse, and enough beyond it to see the frame go. */
  var ended = false;
  var video = tube.querySelector('video');
  if (video) video.addEventListener('ended', function () { ended = true; });
  for (var n = 0; n < 130; n += 1) {
    if (box.isConnected) {
      frames.push(Object.assign(scale(), {ended: ended}));
      if (box.offsetLeft !== anchor.left || box.offsetTop !== anchor.top) moved = true;
    } else {
      frames.push({gone: true, at: performance.now(), ended: ended});
      break;
    }
    await wait(30);
  }

  var live = frames.filter(function (f) { return !f.gone; });
  var opening = live.slice(0, 8);
  var open = live.some(function (f) { return f.y > 0.9 && f.x > 0.9; });
  var afterEnd = live.filter(function (f) { return f.ended; });
  var line = afterEnd.some(function (f) { return f.y < 0.2 && f.x > 0.6; });
  var dot = afterEnd.some(function (f) { return f.y < 0.1 && f.x < 0.3; })
            || afterEnd.some(function (f) { return f.opacity < 0.2; });
  var gone = frames.some(function (f) { return f.gone; });

  return {
    ok: !!(open && line && gone && !moved),
    startedThin: opening.length ? opening[0].y < 0.5 : null,
    reachedPicture: open,
    collapsedToALine: line,
    thenToADot: dot,
    windowRemoved: gone,
    frameMoved: moved,
    samples: live.length,
    trace: live.filter(function (_, i) { return i % 4 === 0; })
      .map(function (f) {
        return f.at.toFixed(0) + ' x=' + f.x.toFixed(2) + ' y=' + f.y.toFixed(2)
          + (f.ended ? ' (ended)' : '');
      })
  };
})()`;

function chrome() {
  for (const c of CHROMES) if (fs.existsSync(c)) return c;
  throw new Error('no chrome or edge found');
}

async function send(ws, id, method, params) {
  return new Promise((settle, fail) => {
    const onMessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id !== id) return;
      ws.removeEventListener('message', onMessage);
      if (msg.error) fail(new Error(method + ': ' + msg.error.message));
      else settle(msg.result);
    };
    ws.addEventListener('message', onMessage);
    ws.send(JSON.stringify({id, method, params: params || {}}));
  });
}

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'sfxtv-'));
  const proc = spawn(chrome(), [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    /* The set carries sound. Without this the clip never starts and the
       probe measures a tube that was refused rather than one that works. */
    '--autoplay-policy=no-user-gesture-required',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + profile,
    '--no-first-run', '--no-default-browser-check',
    'about:blank'
  ], {stdio: 'ignore'});

  let target = null;
  for (let tries = 0; tries < 40 && !target; tries += 1) {
    await new Promise((r) => setTimeout(r, 400));
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      target = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch (err) { /* not up yet */ }
  }
  if (!target) { proc.kill(); throw new Error('chrome did not open a debugging port'); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((settle) => ws.addEventListener('open', settle, {once: true}));

  let id = 0;
  await send(ws, ++id, 'Emulation.setDeviceMetricsOverride',
    {width: 1440, height: 900, deviceScaleFactor: 1, mobile: false});
  await send(ws, ++id, 'Page.navigate', {url: BASE + '/?sfxtv=' + Date.now()});
  /* The panel builds itself off several polls; the set needs pineWin and
     the stylesheet, both of which are in the document from the start, but
     an early call lands before the script block has finished evaluating. */
  await new Promise((r) => setTimeout(r, 6000));

  await send(ws, ++id, 'Runtime.evaluate',
    {expression: 'window.CLIP_B64 = ' + JSON.stringify(CLIP) + '; 1'});
  const res = await send(ws, ++id, 'Runtime.evaluate',
    {expression: PROBE, returnByValue: true, awaitPromise: true});
  const out = (res.result && res.result.value) || {ok: false, why: 'no answer'};

  ws.close();
  proc.kill();
  try { fs.rmSync(profile, {recursive: true, force: true}); } catch (err) { /* windows */ }

  console.log('\nthe SFX guy\'s television, measured at ' + BASE);
  if (out.why) console.log('  ' + out.why);
  console.log('  opened thin (a line) : ' + out.startedThin);
  console.log('  reached a picture    : ' + out.reachedPicture);
  console.log('  collapsed to a line  : ' + out.collapsedToALine);
  console.log('  then to a dot        : ' + out.thenToADot);
  console.log('  window removed after : ' + out.windowRemoved);
  console.log('  frame stayed put     : ' + (out.frameMoved === false));
  console.log('  samples              : ' + out.samples);
  if (out.trace) console.log('  trace:\n    ' + out.trace.join('\n    '));
  console.log(out.ok ? '\nit comes on and goes off like a tube'
                     : '\nthe set did not behave like a tube');
  process.exit(out.ok ? 0 : 1);
})().catch((err) => { console.error(err.message); process.exit(2); });
