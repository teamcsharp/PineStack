/* DOES A TAB KEEP ITS WORD, AT A HEIGHT THAT USED TO SQUASH IT?
 *
 * Reported as "too small and overlapping". Both are one fault: a flex
 * child shrinks before its parent scrolls, and vertical text that loses
 * height loses letters. A screenshot cannot tell a clipped label from a
 * short one - "SAM" and "SAMPLER" look equally deliberate - so this
 * measures instead. It builds the rail's own markup with the rail's own
 * stylesheet, lifted out of rail.js so the test cannot drift from the
 * source, at four viewport heights including ones that used to fail.
 *
 * Three assertions, and every one of them can fail:
 *   1. no tab is shorter than its own word needs   (nothing is clipped)
 *   2. no tab's top is above its neighbour's bottom (nothing overlaps)
 *   3. where nine will not fit, the RAIL scrolls    (the intended cure)
 *
 * Usage: node tools/rail-fit-probe.cjs [path/to/rail.js]
 */
const {spawn} = require('node:child_process');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');

const PORT = 9333;
const CHROMES = [
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium'
];
const LABELS = ['TECH', 'SAMPLER', 'SCRIPT', 'LISTEN', 'MUSIC',
  'PRESENT', 'SLIDES', '3JS', 'SC'];
const HEIGHTS = [1100, 900, 760, 640];

function chrome() {
  for (const c of CHROMES) if (fs.existsSync(c)) return c;
  throw new Error('no chrome or edge found');
}

/* The stylesheet as rail.js assembles it: the array of string fragments,
   joined. Reading it out of the source is the point - a copy pasted here
   would pass long after the real one stopped matching. */
function railCss(file) {
  const src = fs.readFileSync(file, 'utf8');
  const m = src.match(/var RAIL_CSS = \[([\s\S]*?)\]\.join\(''\);/);
  if (!m) throw new Error('RAIL_CSS not found in ' + file);
  return m[1].split('\n')
    .map((l) => l.trim())
    .filter((l) => l.startsWith("'"))
    .map((l) => l.replace(/^'/, '').replace(/',?$/, ''))
    .join('');
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

const PROBE = (labels) => `(() => {
  const rail = document.getElementById('pineViewRail');
  const tabs = [...document.querySelectorAll('.pine-view-tab')];
  const labels = ${JSON.stringify(labels)};
  const boxes = tabs.map((t, i) => {
    const r = t.getBoundingClientRect();
    return {
      label: labels[i],
      h: Math.round(r.height),
      top: Math.round(r.top),
      bottom: Math.round(r.bottom),
      /* scrollHeight past clientHeight IS the clipping - it is the
         browser saying the content did not fit the box it was given. */
      /* Vertical text that will not fit its box does not overflow - it
         WRAPS into a second column, which makes the tab wider and reads
         as two tabs running together. scrollHeight cannot see that, so
         the width is measured too: a tab wider than one column wrapped. */
      w: Math.round(r.width),
      clipped: t.scrollHeight > t.clientHeight + 1,
      needs: t.scrollHeight
    };
  });
  return {
    railH: Math.round(rail.getBoundingClientRect().height),
    needed: rail.scrollHeight,
    scrolls: rail.scrollHeight > rail.clientHeight + 1,
    boxes
  };
})()`;

(async () => {
  const file = process.argv[2]
    || path.join(__dirname, '..', 'desktop', 'renderer', 'rail.js');
  const css = railCss(file);
  const html = '<style>body{margin:0;background:#0b0f11}' + css + '</style>'
    + '<div id="pineViewRail">'
    + LABELS.map((l) => '<button class="pine-view-tab">' + l
      + '</button>').join('')
    + '</div>';

  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'railfit-'));
  const proc = spawn(chrome(), [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + profile,
    '--no-first-run', '--no-default-browser-check', 'about:blank'
  ], {stdio: 'ignore'});

  let target = null;
  for (let tries = 0; tries < 40 && !target; tries += 1) {
    await new Promise((r) => setTimeout(r, 400));
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      target = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch (err) { /* not up yet */ }
  }
  if (!target) { proc.kill(); throw new Error('no debugging port'); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((s) => ws.addEventListener('open', s, {once: true}));

  let id = 0;
  let bad = 0;
  for (const height of HEIGHTS) {
    await send(ws, ++id, 'Emulation.setDeviceMetricsOverride',
      {width: 1280, height, deviceScaleFactor: 1, mobile: false});
    await send(ws, ++id, 'Page.navigate',
      {url: 'data:text/html;charset=utf-8,' + encodeURIComponent(html)});
    await new Promise((r) => setTimeout(r, 700));
    const res = await send(ws, ++id, 'Runtime.evaluate',
      {expression: PROBE(LABELS), returnByValue: true});
    const got = res.result.value;

    let overlaps = 0;
    for (let i = 1; i < got.boxes.length; i += 1) {
      if (got.boxes[i].top < got.boxes[i - 1].bottom - 0.5) overlaps += 1;
    }
    /* The narrowest tab is one column by definition - nothing can be
       thinner than a single line of vertical text. Anything meaningfully
       wider than that has wrapped. */
    const oneCol = Math.min(...got.boxes.map((b) => b.w));
    const wrapped = got.boxes.filter((b) => b.w > oneCol + 3);
    const clipped = got.boxes.filter((b) => b.clipped).concat(wrapped);
    console.log('viewport %d  rail=%d needed=%d  scrolls=%s  clipped=%d  '
      + 'overlapping=%d', height, got.railH, got.needed,
    got.scrolls, clipped.length, overlaps);
    if (clipped.length) {
      console.log('    ' + clipped.map((b) => b.label + ' ' + b.h + '/'
        + b.needs + ' w' + b.w).join(', '));
    }
    if (clipped.length || overlaps) bad += 1;
  }

  ws.close();
  proc.kill();
  try { fs.rmSync(profile, {recursive: true, force: true}); } catch (e) {}
  console.log(bad
    ? '\nFAILED - a tab is still losing its word'
    : '\nevery tab keeps its word at every height, and none overlap');
  process.exit(bad ? 1 : 0);
})().catch((e) => { console.error(e.message); process.exit(2); });
