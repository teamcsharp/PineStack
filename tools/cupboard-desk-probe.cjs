/* #1260: DOES THE WHY-DRAWER ACTUALLY OPEN, AND DOES IT SAY ANYTHING?
 *
 * The desk is 17kB of template strings assembled by hand; `node --check`
 * proves it parses and proves nothing about whether render() throws on the
 * first real payload. This drives a headless Chrome at the live desk, waits
 * for the census to paint, clicks the first "why?" chevron on an unheard
 * row, and reports what came back — including any exception the page
 * swallowed on the way.
 *
 *   node desk-why-probe.cjs [base-url] [key]
 */
const {spawn} = require('node:child_process');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');

const BASE = process.argv[2] || 'http://10.89.1.246:8096';
const KEY = process.argv[3] || '';
const PORT = 9341;
const CHROMES = [
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium'
];

function chrome() {
  for (const c of CHROMES) if (fs.existsSync(c)) return c;
  throw new Error('no chrome found');
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

const READ = `(() => {
  const banner = document.querySelector("#unheard .banner");
  const rows = [...document.querySelectorAll("#inventory tr.unheard")];
  const chev = rows.length ? rows[0].querySelector("button[data-why]") : null;
  return JSON.stringify({
    errors: window.__probeErrors || [],
    banner: banner ? banner.innerText.replace(/\\s+/g, " ").slice(0, 320) : null,
    censusRows: document.querySelectorAll("#unheard table tr").length,
    invRows: document.querySelectorAll("#inventory tr").length,
    unheardRows: rows.length,
    firstUnheardId: chev ? chev.dataset.why : null,
    filters: !!document.getElementById("fUnheard")
  });
})()`;

const AFTER = `(() => {
  const d = document.querySelector("tr.drawer td");
  const acts = [...document.querySelectorAll("tr.drawer .drawer-acts button")]
    .map((b) => b.dataset.cact);
  return JSON.stringify({
    errors: window.__probeErrors || [],
    drawers: document.querySelectorAll("tr.drawer").length,
    reasons: [...document.querySelectorAll("tr.drawer .reason b")].map((e) => e.textContent),
    text: d ? d.innerText.replace(/\\s+/g, " ").slice(0, 700) : null,
    actions: acts
  });
})()`;

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'deskwhy-'));
  const proc = spawn(chrome(), [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + profile,
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
  if (!target) { proc.kill(); throw new Error('chrome did not open a debugging port'); }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((settle) => ws.addEventListener('open', settle, {once: true}));
  let id = 0;

  await send(ws, ++id, 'Page.enable');
  await send(ws, ++id, 'Page.addScriptToEvaluateOnNewDocument', {
    source: 'window.__probeErrors = [];'
      + 'window.addEventListener("error", (e) => window.__probeErrors.push(String(e.message)));'
      + 'window.addEventListener("unhandledrejection", (e) => window.__probeErrors.push("reject: " + String(e.reason)));'
  });
  await send(ws, ++id, 'Emulation.setDeviceMetricsOverride',
    {width: 1400, height: 1000, deviceScaleFactor: 1, mobile: false});
  await send(ws, ++id, 'Page.navigate',
    {url: BASE + '/cupboard/retire' + (KEY ? '?key=' + encodeURIComponent(KEY) : '')});
  await new Promise((r) => setTimeout(r, 7000));

  const first = JSON.parse((await send(ws, ++id, 'Runtime.evaluate',
    {expression: READ, returnByValue: true})).result.value);
  console.log('BANNER      :', first.banner);
  console.log('census rows :', first.censusRows, ' inventory rows:', first.invRows,
              ' unheard rows:', first.unheardRows);
  console.log('filter added:', first.filters);
  console.log('page errors :', first.errors.length ? first.errors : 'none');

  if (!first.firstUnheardId) {
    console.log('NO UNHEARD ROW TO CLICK');
  } else {
    await send(ws, ++id, 'Runtime.evaluate', {
      expression: 'document.querySelector(\'button[data-why="' + first.firstUnheardId
        + '"]\').click()', returnByValue: true});
    await new Promise((r) => setTimeout(r, 9000));
    const after = JSON.parse((await send(ws, ++id, 'Runtime.evaluate',
      {expression: AFTER, returnByValue: true})).result.value);
    console.log('\nclicked why? on', first.firstUnheardId);
    console.log('drawers open:', after.drawers);
    console.log('reason heads:', after.reasons);
    console.log('buttons     :', after.actions);
    console.log('drawer text :', after.text);
    console.log('page errors :', after.errors.length ? after.errors : 'none');
  }

  ws.close();
  proc.kill();
  try { fs.rmSync(profile, {recursive: true, force: true}); } catch (err) { /* windows */ }
})().catch((err) => { console.error(err.message); process.exit(2); });
