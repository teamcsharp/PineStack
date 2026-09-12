/* DOES ANY READOUT OVERLAP ANOTHER, OR RUN OFF THE GLASS?
 *
 * "Make sure the accommodations are taken for the resolution and display
 *  size so the elements are fitting on screen and aren't overlapping and be
 *  trimmed off screen." / "I want it to be compatible in both landscape and
 *  portrait mode."
 *
 * That is a question about real geometry, and a screenshot only answers it
 * for the one size someone happened to look at. This drives a headless
 * Chrome through every size the overlays actually meet — the tablet both
 * ways, a desk, a phone — and MEASURES three things per size:
 *
 *   overlaps    any two widget rectangles sharing pixels
 *   clipped     any widget crossing the viewport edge with no scroller
 *               between it and the edge that could bring it back
 *   overflow    any widget whose own content is wider than itself
 *
 * And one thing that is not geometry at all:
 *
 *   sleeping    "only pulsing whenever we are in the tab... otherwise it
 *               needs to sleep and relax". The monitor must stop asking the
 *               station anything the moment the page is hidden, and start
 *               again when it comes back. Checked by hiding the page for
 *               real and watching whether the polling timer survives.
 *
 * A scroller counts as an answer: a column taller than the screen is fine
 * if it scrolls, and the probe checks for that rather than calling every
 * off-screen pixel a fault.
 *
 *   node tools/overlay-fit-probe.cjs [base-url]
 *
 * Needs Chrome and Node 22+ (for the built-in WebSocket). Exits non-zero if
 * anything fails, so it can gate a deploy.
 */
'use strict';
const {spawn} = require('node:child_process');
const os = require('node:os');
const path = require('node:path');
const fs = require('node:fs');

const BASE = process.argv[2] || 'http://10.89.1.246:8096';
const PORT = 9333;

const CHROMES = [
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium'
];

/* Every shape this thing is actually looked at in. */
const SIZES = [
  {name: 'tablet landscape', w: 1340, h: 800, url: '/spark?pictures=1'},
  {name: 'tablet portrait', w: 800, h: 1340, url: '/spark?pictures=1'},
  {name: 'tablet landscape (dash)', w: 1340, h: 800, url: '/spark'},
  {name: 'tablet portrait (dash)', w: 800, h: 1340, url: '/spark'},
  {name: 'desk 1080p', w: 1920, h: 1080, url: '/spark'},
  {name: 'phone portrait', w: 412, h: 915, url: '/spark'},
  {name: 'small window', w: 700, h: 600, url: '/spark'}
];

/* Runs INSIDE the page. Pure geometry — no assumptions about class names
 * beyond the one prefix the module owns. */
const PROBE = `(function () {
  var widgets = [].slice.call(document.querySelectorAll('.so-w'))
    .filter(function (n) {
      var s = getComputedStyle(n);
      return s.display !== 'none' && s.visibility !== 'hidden' && n.offsetParent !== null;
    });
  function rect(n) { var r = n.getBoundingClientRect(); return {
    l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; }

  var overlaps = [];
  for (var i = 0; i < widgets.length; i += 1) {
    for (var j = i + 1; j < widgets.length; j += 1) {
      var a = rect(widgets[i]), b = rect(widgets[j]);
      var x = Math.min(a.r, b.r) - Math.max(a.l, b.l);
      var y = Math.min(a.b, b.b) - Math.max(a.t, b.t);
      /* A pixel of rounding is not an overlap; four is. */
      if (x > 4 && y > 4) {
        overlaps.push({a: widgets[i].dataset.soId, b: widgets[j].dataset.soId,
                       x: Math.round(x), y: Math.round(y)});
      }
    }
  }

  /* Is there a scroller between this node and the viewport that could bring
   * an off-screen part of it back? If so, being off-screen is a scroll, not
   * a trim. */
  function rescuedBy(node) {
    for (var p = node.parentElement; p; p = p.parentElement) {
      var s = getComputedStyle(p);
      if (/auto|scroll/.test(s.overflowY) && p.scrollHeight > p.clientHeight + 4) return true;
      if (/auto|scroll/.test(s.overflowX) && p.scrollWidth > p.clientWidth + 4) return true;
    }
    var d = document.scrollingElement;
    return d && (d.scrollHeight > innerHeight + 4 || d.scrollWidth > innerWidth + 4);
  }

  var clipped = [];
  var overflowing = [];
  widgets.forEach(function (n) {
    var r = rect(n);
    var outside = (r.l < -4) || (r.t < -4) || (r.r > innerWidth + 4) || (r.b > innerHeight + 4);
    if (outside && !rescuedBy(n)) {
      clipped.push({id: n.dataset.soId,
        l: Math.round(r.l), t: Math.round(r.t),
        r: Math.round(r.r), b: Math.round(r.b)});
    }
    /* Content wider than its own box, with no scroller on the box itself:
       the figures are simply cut off. */
    var s = getComputedStyle(n);
    if (n.scrollWidth > n.clientWidth + 2 && !/auto|scroll/.test(s.overflowX)) {
      overflowing.push({id: n.dataset.soId,
        content: n.scrollWidth, box: n.clientWidth});
    }
  });

  return JSON.stringify({
    widgets: widgets.map(function (n) { return n.dataset.soId; }),
    viewport: {w: innerWidth, h: innerHeight},
    pageWiderThanViewport: document.scrollingElement
      ? document.scrollingElement.scrollWidth > innerWidth + 4 : false,
    overlaps: overlaps, clipped: clipped, overflowing: overflowing
  });
})()`;

const SLEEP_PROBE = `(async function () {
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  /* Wait for the handle rather than reporting its absence as a result: the
     page mounts it on load and this probe has occasionally arrived first,
     which read as a missing feature rather than a race in the probe. */
  var live = null;
  for (var i = 0; i < 20 && !live; i += 1) {
    live = window.__sparkMonitor;
    if (!live || typeof live.polling !== 'function') { live = null; await wait(300); }
  }
  if (!live) return {ok: null, verdict: 'no monitor handle on this page'};

  var whileWatched = live.polling();

  var real = Object.getOwnPropertyDescriptor(Document.prototype, 'hidden');
  Object.defineProperty(document, 'hidden', {configurable: true, get: function () { return true; }});
  document.dispatchEvent(new Event('visibilitychange'));
  await wait(1200);
  var whileHidden = live.polling();

  delete document.hidden;
  if (real) Object.defineProperty(Document.prototype, 'hidden', real);
  document.dispatchEvent(new Event('visibilitychange'));
  await wait(1200);
  var whenBack = live.polling();

  var ok = whileWatched === true && whileHidden === false && whenBack === true;
  return {ok: ok, whileWatched: whileWatched, whileHidden: whileHidden,
    whenBack: whenBack,
    verdict: ok ? 'polls when watched, stops when hidden, resumes when back'
      : ('watched=' + whileWatched + ' hidden=' + whileHidden + ' back=' + whenBack)};
})()`;

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

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'overlayfit-'));
  const proc = spawn(chrome(), [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
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
  let bad = 0;
  for (const size of SIZES) {
    await send(ws, ++id, 'Emulation.setDeviceMetricsOverride',
      {width: size.w, height: size.h, deviceScaleFactor: 1, mobile: false});
    /* about:blank first, and a cache-buster on the way back. Navigating to
     * a URL the tab is ALREADY on is not a reload, and the 1920x1080 pass
     * measured a page still laid out for 800px — reporting zero widgets and
     * looking like an application fault. */
    await send(ws, ++id, 'Page.navigate', {url: 'about:blank'});
    await new Promise((r) => setTimeout(r, 300));
    const bust = (size.url.indexOf('?') >= 0 ? '&' : '?') + 'fit=' + Date.now();
    await send(ws, ++id, 'Page.navigate', {url: BASE + size.url + bust});
    /* Long enough for the first poll to answer and the widgets to paint
       real numbers — an empty widget is trivially the right size. */
    await new Promise((r) => setTimeout(r, 6000));
    const res = await send(ws, ++id, 'Runtime.evaluate',
      {expression: PROBE, returnByValue: true, awaitPromise: false});
    const out = JSON.parse(res.result.value);

    /* THE SLEEPING CHECK. document.hidden is read-only, so it is overridden
       for the length of the test and the event the browser would have sent
       is dispatched by hand — which is exactly what the page listens for. */
    const sleepRes = await send(ws, ++id, 'Runtime.evaluate', {
      expression: SLEEP_PROBE, returnByValue: true, awaitPromise: true});
    out.sleep = (sleepRes.result && sleepRes.result.value) || null;

    const faults = out.overlaps.length + out.clipped.length + out.overflowing.length
      + (out.pageWiderThanViewport ? 1 : 0)
      + (out.sleep && out.sleep.ok === false ? 1 : 0);
    if (faults) bad += 1;
    console.log(`\n${size.name}  ${size.w}x${size.h}  ${size.url}`);
    console.log(`  widgets drawn : ${out.widgets.length} (${out.widgets.join(', ')})`);
    console.log(`  overlaps      : ${out.overlaps.length ? JSON.stringify(out.overlaps) : 'none'}`);
    console.log(`  trimmed       : ${out.clipped.length ? JSON.stringify(out.clipped) : 'none'}`);
    console.log(`  content cut   : ${out.overflowing.length ? JSON.stringify(out.overflowing) : 'none'}`);
    console.log(`  page sideways : ${out.pageWiderThanViewport ? 'YES' : 'no'}`);
    if (out.sleep) {
      console.log(`  sleeps hidden : ${out.sleep.verdict}`);
    }
  }

  ws.close();
  proc.kill();
  try { fs.rmSync(profile, {recursive: true, force: true}); } catch (err) { /* windows */ }
  console.log(bad ? `\n${bad} size(s) with faults` : '\nevery size clean');
  process.exit(bad ? 1 : 0);
})().catch((err) => { console.error(err.message); process.exit(2); });
