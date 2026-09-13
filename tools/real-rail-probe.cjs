/* Measure the rail in the REAL index.html, not a rebuild of it.
 *
 * The reconstruction measured clean at every height while the shipped app
 * was visibly clipping its labels, which means the fault lives in
 * something the rebuild does not carry - another stylesheet, a global
 * rule, a container. So this loads the actual document.
 */
const {spawn} = require('node:child_process');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');

const PORT = 9341;
const CHROMES = [
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
];

function chrome() {
  for (const c of CHROMES) if (fs.existsSync(c)) return c;
  throw new Error('no chrome or edge found');
}

async function send(ws, id, method, params) {
  return new Promise((ok, no) => {
    const h = (e) => {
      const m = JSON.parse(e.data);
      if (m.id !== id) return;
      ws.removeEventListener('message', h);
      if (m.error) no(new Error(method + ': ' + m.error.message));
      else ok(m.result);
    };
    ws.addEventListener('message', h);
    ws.send(JSON.stringify({id, method, params: params || {}}));
  });
}

const PROBE = process.argv[4] ? process.argv[4] : `(() => {
  const rail = document.getElementById('pineViewRail');
  if (!rail) return {ok:false, why:'no rail'};
  return {ok:true, count:document.querySelectorAll('.pine-view-tab').length};
})()`;

(async () => {
  const file = process.argv[2];
  const height = Number(process.argv[3] || 900);
  const url = 'file:///' + file.split('\\').join('/');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'realrail-'));
  const proc = spawn(chrome(), [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--allow-file-access-from-files',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + profile,
    '--no-first-run', '--no-default-browser-check', 'about:blank'
  ], {stdio: 'ignore'});

  let target = null;
  for (let i = 0; i < 40 && !target; i += 1) {
    await new Promise((r) => setTimeout(r, 400));
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      target = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
    } catch (e) { /* not up yet */ }
  }
  if (!target) { proc.kill(); throw new Error('no debugging port'); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((s) => ws.addEventListener('open', s, {once: true}));

  let id = 0;
  await send(ws, ++id, 'Emulation.setDeviceMetricsOverride',
    {width: 1280, height, deviceScaleFactor: 1, mobile: false});
  await send(ws, ++id, 'Page.navigate', {url});
  await new Promise((r) => setTimeout(r, 8000));
  const res = await send(ws, ++id, 'Runtime.evaluate',
    {expression: PROBE, returnByValue: true});
  const got = res.result.value;

  if (process.argv[4]) {
    console.log(JSON.stringify(got, null, 1));
  } else if (!got || !got.ok) {
    console.log('viewport ' + height + ': ' + ((got && got.why) || 'no answer'));
  } else {
    console.log('viewport %d  vh=%d  rail=%d needed=%d client=%d  '
      + 'max-height=%s overflow-y=%s display=%s gap=%s',
    height, got.vh, got.railH, got.needed, got.clientH,
    got.maxH, got.overflowY, got.disp, got.gap);
    for (const b of got.boxes) {
      console.log('  %-9s %3dx%-4d shrink=%-4s wrap=%-8s pad=%-10s %s',
        b.label, b.w, b.h, b.shrink, b.ws, b.pad,
        b.clipped ? 'CLIPPED needs ' + b.needs : 'ok');
    }
  }
  ws.close();
  proc.kill();
  try { fs.rmSync(profile, {recursive: true, force: true}); } catch (e) {}
})().catch((e) => { console.error(e.message); process.exit(2); });
