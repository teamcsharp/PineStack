#!/usr/bin/env node
/* closex_harness.js - every popup has an X in its top-right corner, the X
 * closes it, and Escape closes it. Headless Edge (--mute-audio), driven over
 * CDP with no dependencies, on the desk (1920x1080) and tablet (1340x800).
 *
 *   node closex_harness.js <repo-root> [--only name,name] [--profile desk|tablet]
 *
 * Pages are served from <repo-root> by a small local server:
 *   /panel           the station panel (app.py CONTROL_PANEL_HTML)
 *   /shell           a page that loads desktop/renderer modules the shell loads
 *   /icons/*, /system3/*, ...   frontend/      /spark/asset/*, /r/*  desktop/renderer/
 *   /api/*           {}  (stubbed data; the code under test is the builder)
 * Output: a table on stdout, results.json and proofs/<profile>-<case>.png.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const http = require('http');
const {spawn} = require('child_process');
const os = require('os');

const ROOT = path.resolve(process.argv[2] || '.');
const OUT = path.resolve(__dirname, '..', 'proofs');
const argv = process.argv.slice(3);
const only = (argv.includes('--only') ? argv[argv.indexOf('--only') + 1] : '').split(',').filter(Boolean);
const profArg = argv.includes('--profile') ? argv[argv.indexOf('--profile') + 1] : '';
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const PROFILES = [{name: 'desk', w: 1920, h: 1080}, {name: 'tablet', w: 1340, h: 800}]
  .filter((p) => !profArg || p.name === profArg);
fs.mkdirSync(OUT, {recursive: true});

/* ---------------------------------------------------------------- server */
function panelHtml() {
  const src = fs.readFileSync(path.join(ROOT, 'app.py'), 'utf8').replace(/\r\n/g, '\n');
  const a = src.indexOf('CONTROL_PANEL_HTML = r"""') + 'CONTROL_PANEL_HTML = r"""'.length;
  const b = src.indexOf('\n"""', a);
  return src.slice(a, b).replace('__SERVER_KEY__', '""');
}
const CASES = require('./closex_cases.js');
/* The desktop shell itself (desktop/renderer/index.html), every module it
 * loads, with the Electron preload bridge stubbed: any call answers {}. */
function shellHtml() {
  const html = fs.readFileSync(path.join(ROOT, 'desktop', 'renderer', 'index.html'), 'utf8');
  const at = html.indexOf('<head>') + '<head>'.length;
  let out = html.slice(0, at) + '<base href="/r/"><script>' + CASES.SHELL_STUB + '</script>' + html.slice(at);
  for (const drop of (process.env.CLOSEX_DROP || '').split(',').filter(Boolean)) {
    out = out.replace(new RegExp('<script src="\./' + drop.replace(/[.]/g, '\.') + '"></script>'), '<!-- dropped ' + drop + ' -->');
  }
  return out;
}
const TYPES = {'.js': 'application/javascript', '.css': 'text/css', '.html': 'text/html',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.json': 'application/json', '.woff2': 'font/woff2'};
function sendFile(res, file) {
  fs.readFile(file, (err, body) => {
    if (err) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, {'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream'});
    res.end(body);
  });
}
const server = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0]);
  if (u === '/panel') { res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'}); res.end(panelHtml()); return; }
  if (u === '/shell') { res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'}); res.end(shellHtml()); return; }
  if (u.startsWith('/api/')) {
    if (/\/(events|stream|sse)\b/.test(u)) { res.writeHead(204); res.end(); return; }
    res.writeHead(200, {'Content-Type': 'application/json'}); res.end('{}'); return;
  }
  const m = u.match(/^\/(icons|system3|system2|word-cause|station-flow|comfy-workshop|rejection-review|tune-messenger)\/([\w.-]+)$/);
  if (m) { sendFile(res, path.join(ROOT, 'frontend', m[2])); return; }
  const v = u.match(/^\/vendor\/([\w.-]+)$/);
  if (v) { sendFile(res, path.join(__dirname, '..', 'vendor', v[1])); return; }
  const r = u.match(/^\/(spark\/asset|r)\/([\w.\/-]+)$/);
  if (r && !r[2].includes('..')) { sendFile(res, path.join(ROOT, 'desktop', 'renderer', r[2])); return; }
  res.writeHead(404); res.end();
});

/* ------------------------------------------------------------------ CDP */
function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function getJSON(url) {
  for (let i = 0; i < 160; i += 1) {   /* a second Edge can take a while */
    try { const r = await fetch(url); return await r.json(); } catch (e) { await wait(250); }
  }
  throw new Error('no CDP at ' + url);
}
class Tab {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = [];
    ws.onmessage = (m) => { const d = JSON.parse(m.data);
      if (d.id && this.pending.has(d.id)) { const p = this.pending.get(d.id); this.pending.delete(d.id);
        d.error ? p.rej(new Error(d.error.message)) : p.res(d.result); }
      else if (d.method) {
        this.events.push(d);
        /* an alert()/confirm() left up blocks every input event: answer it */
        if (d.method === 'Page.javascriptDialogOpening') {
          console.log('DIALOG', d.params.type, String(d.params.message).slice(0, 80));
          this.send('Page.handleJavaScriptDialog', {accept: true});
        }
      } }; }
  send(method, params = {}) { const id = ++this.id;
    return new Promise((res, rej) => { this.pending.set(id, {res, rej}); this.ws.send(JSON.stringify({id, method, params})); }); }
  async eval(expr, timeout = 8000) {
    const r = await Promise.race([
      this.send('Runtime.evaluate', {expression: expr, awaitPromise: true, returnByValue: true}),
      wait(timeout).then(() => ({result: {value: {error: 'timeout'}}}))]);
    if (r.exceptionDetails) return {error: (r.exceptionDetails.exception || {}).description || r.exceptionDetails.text};
    return r.result.value;
  }
  async quiet() {
    if (!this.dbg) return;
    try {
      for (const t of await getJSON('http://127.0.0.1:' + this.dbg + '/json/list')) {
        if (t.type === 'page' && /^edge:|^chrome:/.test(t.url)) { await fetch('http://127.0.0.1:' + this.dbg + '/json/close/' + t.id); console.log('closed', t.url); }
      }
    } catch (e) { /* none */ }
  }
  async click(x, y) {
    await this.quiet();
    for (const type of ['mouseMoved', 'mousePressed', 'mouseReleased']) {
      await this.send('Input.dispatchMouseEvent', {type, x, y, button: 'left', clickCount: 1, pointerType: 'mouse'});
    }
  }
  async esc() {
    await this.quiet();
    await this.send('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27});
    await this.send('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27});
  }
  async shot(file, clip) {
    const p = {format: 'png'};
    if (clip) p.clip = Object.assign({scale: 1}, clip);
    const r = await this.send('Page.captureScreenshot', p);
    fs.writeFileSync(file, Buffer.from(r.data, 'base64'));
  }
}

/* The probe that runs in the page: find the popup an opener made, the X in
 * its corner, and whether that X is the thing a finger would hit. */
const PROBE = String.raw`(() => {
  if (window.__cx) return;
  const vis = (n) => { if (!n || !n.isConnected) return false; const cs = getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
    const r = n.getBoundingClientRect(); return r.width > 2 && r.height > 2; };
  const CLOSEY = /^(\u2715|\u00d7|\u2716|x|X|close|Close|\u2715 Close|\u00d7 Close|Done|done)$/;
  const isX = (n) => {
    if (n.classList && n.classList.contains('pine-closex')) return true;
    const t = (n.textContent || '').trim();
    const lab = (n.getAttribute('aria-label') || n.getAttribute('title') || '');
    if (/^close/i.test(lab) || /^(not now|dismiss)/i.test(lab)) return true;
    if (CLOSEY.test(t)) return true;
    const use = n.querySelector && n.querySelector('use');
    if (use && /close/.test(use.getAttribute('href') || '')) return true;
    return false;
  };
  window.__cx = {
    before: null,
    mark() { this.before = new Map([...document.body.querySelectorAll('*')].filter((n) => {
      const cs = getComputedStyle(n); return cs.position === 'fixed'; }).map((n) => [n, vis(n)]));
      this.kids = new Set([...document.body.children]); },
    find(sel) {
      if (sel) { const n = [...document.querySelectorAll(sel)].filter(vis).pop(); if (n) return n; }
      const fresh = [...document.body.children].filter((n) => !this.kids.has(n) && vis(n)
        && /fixed|absolute/.test(getComputedStyle(n).position));
      /* the biggest new thing is the popup; a status chip or a bubble that
         came up with it is smaller */
      const area = (n) => { const r = n.getBoundingClientRect(); return r.width * r.height; };
      if (fresh.length) return fresh.sort((a, b) => area(b) - area(a))[0];
      const woke = [...document.body.querySelectorAll('*')].filter((n) => getComputedStyle(n).position === 'fixed'
        && vis(n) && this.before && this.before.get(n) === false);
      return woke[0] || null;
    },
    box(root) {
      const W = innerWidth, H = innerHeight; let r = root.getBoundingClientRect();
      if (r.width >= W * 0.9 && r.height >= H * 0.9) {
        let best = null, area = 0;
        const walk = (n, d) => { for (const c of n.children) { if (!vis(c)) continue; const q = c.getBoundingClientRect();
          if (q.width < W * 0.9 || q.height < H * 0.9) { const a = q.width * q.height; if (a > area) { area = a; best = c; } }
          else if (d < 3) walk(c, d + 1); } };
        walk(root, 0);
        if (best) return best;
      }
      return root;
    },
    probe(sel) {
      const root = this.find(sel);
      if (!root) return {opened: false};
      this.root = root;
      const card = this.box(root);
      const b = card.getBoundingClientRect();
      const W = innerWidth, H = innerHeight;
      /* the corner that can be SEEN: a box taller than the glass is cut at it */
      const top = Math.max(0, b.top), right = Math.min(W, b.right);
      /* a full-screen view's corner is the screen's corner */
      const rb = root.getBoundingClientRect();
      const rtop = Math.max(0, rb.top), rright = Math.min(W, rb.right);
      const inCorner = (cx, cy) => (cx >= right - 64 && cx <= right + 4 && cy >= top - 4 && cy <= top + 64)
        || (root !== card && cx >= rright - 64 && cx <= rright + 4 && cy >= rtop - 4 && cy <= rtop + 64);
      const xs = [...new Set([...root.querySelectorAll('button,[role=button],span,a,div,i,b,svg,use')].filter((n) => vis(n) && isX(n))
        .map((n) => (n.closest && n.closest('button,[role=button]')) || n))];
      if (root !== card && isX(root)) xs.push(root);
      /* the button itself, not a row that only holds it */
      for (let i = xs.length - 1; i >= 0; i -= 1) if (xs.some((o) => o !== xs[i] && xs[i].contains(o))) xs.splice(i, 1);
      const rows = xs.map((n) => { const q = n.getBoundingClientRect(); const cx = q.left + q.width / 2, cy = q.top + q.height / 2;
        const hit = document.elementFromPoint(cx, cy);
        /* the helper's X belongs to the element it was given: its corner counts */
        let own = false;
        if (n.classList.contains('pine-closex') && n.parentElement) {
          const pr = n.parentElement.getBoundingClientRect();
          const ptop = Math.max(0, pr.top), pright = Math.min(W, pr.right);
          own = cx >= pright - 64 && cx <= pright + 4 && cy >= ptop - 4 && cy <= ptop + 64;
        }
        return {n, cx, cy, w: q.width, h: q.height, corner: inCorner(cx, cy) || own,
          hit: !!hit && (hit === n || n.contains(hit)), helper: n.classList.contains('pine-closex'),
          title: n.getAttribute('title') || '', aria: n.getAttribute('aria-label') || '', text: (n.textContent || '').trim().slice(0, 20)}; });
      rows.sort((p, q) => (q.corner + q.hit) - (p.corner + p.hit));
      const x = rows[0] || null;
      this.x = x && x.n;
      return {opened: true, id: root.id || '', cls: String(root.className || '').slice(0, 40),
        box: {left: Math.round(b.left), top: Math.round(b.top), width: Math.round(b.width), height: Math.round(b.height)},
        x: x ? {cx: Math.round(x.cx), cy: Math.round(x.cy), w: Math.round(x.w), h: Math.round(x.h), corner: x.corner, hit: x.hit,
          helper: x.helper, title: x.title, aria: x.aria, text: x.text} : null, candidates: rows.length};
    },
    /* icon-only controls with no tooltip: visible buttons whose visible
       text carries no letter or digit, and no title */
    tips(scopeSel) {
      const scope = scopeSel ? document.querySelector(scopeSel) : document.body;
      if (!scope) return [];
      const out = [];
      for (const b of scope.querySelectorAll('button, [role=button], a.btn, .tbtn')) {
        if (!vis(b)) continue;
        const text = (b.innerText || b.textContent || '').replace(/\s+/g, '');
        if (/[\p{L}\p{N}]/u.test(text)) continue;
        const title = b.getAttribute('title') || '';
        if (title.trim()) continue;
        out.push({id: b.id, cls: String(b.className || '').slice(0, 40), text: text.slice(0, 8),
          aria: b.getAttribute('aria-label') || '', parent: b.parentElement ? (b.parentElement.id || String(b.parentElement.className || '').slice(0, 30)) : ''});
      }
      return out;
    },
    closed() { const r = this.root; return !r || !r.isConnected || !vis(r); },
    cleanup() { const r = this.root; if (r && r.isConnected && vis(r)) { try { r.remove(); } catch (e) {} } this.root = null; },
  };
})()`;

/* --------------------------------------------------------------- runner */
async function run() {
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const base = 'http://127.0.0.1:' + port;
  const results = [];
  for (const prof of PROFILES) {
    const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'closex-edge-'));
    const dbg = 9300 + Math.floor(Math.random() * 500);
    const edge = spawn(EDGE, ['--headless=new', '--mute-audio', '--disable-gpu', '--no-first-run',
      '--no-default-browser-check', '--hide-scrollbars', '--inprivate', '--disable-sync', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
      '--autoplay-policy=no-user-gesture-required', '--disable-popup-blocking', '--disable-extensions',
      '--disable-features=msEdgeSyncConsent,msImplicitSignin,msEdgeSignInPrompt,EdgeSyncConfirmationDialog', '--remote-debugging-port=' + dbg,
      '--user-data-dir=' + udd, '--window-size=' + prof.w + ',' + prof.h, 'about:blank'], {stdio: 'ignore'});
    try {
      const list = await getJSON('http://127.0.0.1:' + dbg + '/json/list');
      const page = list.find((t) => t.type === 'page');
      const ws = new WebSocket(page.webSocketDebuggerUrl);
      await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
      const tab = new Tab(ws);
      tab.dbg = dbg;
      await tab.send('Page.enable'); await tab.send('Runtime.enable');
      try { await tab.send('Page.setInterceptFileChooserDialog', {enabled: true}); } catch (e) { /* older */ }
      await tab.send('Emulation.setDeviceMetricsOverride', {width: prof.w, height: prof.h, deviceScaleFactor: 1, mobile: false});
      let loaded = '';
      for (const c of CASES.CASES) {
        if (only.length && !only.includes(c.name)) continue;
        /* Edge's own sync-confirmation dialog is window-modal: every input
           event goes to it while it is up. Close any edge:// page. */
        try {
          for (const t of await getJSON('http://127.0.0.1:' + dbg + '/json/list')) {
            if (t.type === 'page' && /^edge:|^chrome:/.test(t.url)) await fetch('http://127.0.0.1:' + dbg + '/json/close/' + t.id);
          }
        } catch (e) { /* none */ }
        const want = c.page || 'panel';
        if (loaded !== want || c.fresh) {
          await tab.send('Page.navigate', {url: base + '/' + want});
          await wait(want === 'panel' ? 6000 : 6000);
          loaded = want;
          await tab.shot(path.join(OUT, prof.name + '-page-' + want + '.png'));
          if (argv.includes('--trace')) {
            await tab.eval("window.__t2 = []; ['pointerdown','mousedown','click','keydown'].forEach((t) => window.addEventListener(t, (e) => __t2.push(t), true))");
            await tab.click(100, 100); await tab.esc(); await wait(300);
            console.log('PAGE-INPUT', want, JSON.stringify(await tab.eval('window.__t2')));
          }
          if (argv.includes('--tips')) {
            await tab.eval(PROBE);
            const t = await tab.eval('__cx.tips()');
            console.log('TIPS', prof.name, want, (t || []).length);
            for (const r of (t || [])) console.log('  TIP', want, JSON.stringify(r));
          }
          if (want === 'shell') console.log('SHELL-TOP', JSON.stringify(await tab.eval(`(() => { const out = []; for (const [x, y] of [[960, 540], [300, 300], [1500, 200]]) { const e = document.elementFromPoint(x, y); out.push(e ? e.tagName + '#' + e.id + '.' + String(e.className).slice(0, 40) : null); } return out; })()`)));
        }
        await tab.eval(PROBE);
        const row = {profile: prof.name, name: c.name, page: want};
        const open = async () => {
          await tab.eval('__cx.mark()');
          const got = await tab.eval('(async () => { ' + (c.pre || '') + '; try { await Promise.race([Promise.resolve((' + c.open + ')), new Promise(r => setTimeout(r, 3000))]); return "ok"; } catch (e) { return "threw: " + (e && e.message); } })()', 9000);
          await wait(c.settle || 700);
          const p = await tab.eval('__cx.probe(' + JSON.stringify(c.root || '') + ')');
          if (process.env.CLOSEX_EVAL) console.log('EVAL', c.name, JSON.stringify(await tab.eval(process.env.CLOSEX_EVAL)));
          return {got, p};
        };
        try {
          const first = await open();
          row.opener = typeof first.got === 'string' ? first.got : JSON.stringify(first.got);
          Object.assign(row, first.p || {});
          if (!row.opened) { row.verdict = 'NOT-OPENED'; results.push(row); await tab.eval('__cx.cleanup()');
            console.log([prof.name.padEnd(6), 'NOT-OPENED'.padEnd(10), c.name.padEnd(26), String(row.opener || '').slice(0, 90)].join('  ')); continue; }
          const b = row.box;
          const pad = 8;
          await tab.shot(path.join(OUT, prof.name + '-' + c.name + '.png'), {
            x: Math.max(0, b.left - pad), y: Math.max(0, b.top - pad),
            width: Math.min(prof.w - Math.max(0, b.left - pad), b.width + 2 * pad),
            height: Math.min(prof.h - Math.max(0, b.top - pad), Math.min(b.height, 700) + 2 * pad)});
          if (row.x && row.x.hit) {
            if (argv.includes('--trace')) await tab.eval(`(() => { window.__trace = []; const x = __cx.x;
              ['pointerdown','mousedown','pointerup','mouseup','click'].forEach((t) => {
                window.addEventListener(t, (e) => __trace.push('win:' + t + ':' + (e.target && (e.target.className || e.target.tagName))), true);
                x.addEventListener(t, (e) => __trace.push('x:' + t + (e.defaultPrevented ? ':prevented' : '')));
              }); })()`);
            await tab.click(row.x.cx, row.x.cy); await wait(500);
            if (argv.includes('--trace')) {
              await tab.eval("window.__t2 = []");
              await tab.click(100, 100); await tab.esc(); await wait(300);
              console.log('AFTER-OPEN-INPUT', JSON.stringify(await tab.eval('window.__t2')),
                JSON.stringify((await getJSON('http://127.0.0.1:' + dbg + '/json/list')).map((t) => t.type + ':' + t.url.slice(0, 50))),
                JSON.stringify(await tab.eval('[document.hasFocus(), document.visibilityState, document.body.inert, !!document.pointerLockElement, document.fullscreenElement && document.fullscreenElement.tagName]')));
            }
            if (argv.includes('--trace')) console.log('TRACE', c.name, JSON.stringify(await tab.eval('window.__trace')));
            row.clickCloses = await tab.eval('__cx.closed()');
            if (!row.clickCloses) {   /* tell a lost click from a close road that did nothing */
              row.jsClick = await tab.eval('(() => { try { __cx.x.click(); } catch (e) { return "threw " + e.message; } return "sent"; })()');
              await wait(400);
              row.jsClickCloses = await tab.eval('__cx.closed()');
              row.at = await tab.eval('(() => { const e = document.elementFromPoint(' + row.x.cx + ',' + row.x.cy + '); return e ? e.tagName + "." + String(e.className).slice(0, 30) : null; })()');
            }
          } else row.clickCloses = false;
          await tab.eval('__cx.cleanup()');
          await wait(200);
          const again = await open();
          if (again.p && again.p.opened) {
            await tab.eval('document.activeElement && document.activeElement.blur && document.activeElement.blur()');
            await tab.esc(); await wait(500);
            row.escCloses = await tab.eval('__cx.closed()');
          } else row.escCloses = null;
          await tab.eval('__cx.cleanup()');
          row.verdict = row.x && row.x.corner && row.x.hit && row.clickCloses ? (row.escCloses ? 'PASS' : 'PASS-noEsc') : 'FAIL';
        } catch (e) { row.verdict = 'ERROR'; row.error = String(e && e.message || e); }
        results.push(row);
        const x = row.x || {};
        console.log([prof.name.padEnd(6), row.verdict.padEnd(10), c.name.padEnd(26),
          'x:' + (row.x ? (x.corner ? 'corner' : 'off') + '/' + (x.hit ? 'hit' : 'covered') + (x.helper ? '/helper' : '') : 'none'),
          'click:' + row.clickCloses + (row.jsClick ? '(js:' + row.jsClickCloses + ' at ' + row.at + ')' : ''), 'esc:' + row.escCloses, row.opener && row.opener !== 'ok' ? row.opener.slice(0, 60) : ''].join('  '));
      }
      ws.close();
    } finally {
      edge.kill();
      await wait(500);
      try { fs.rmSync(udd, {recursive: true, force: true}); } catch (e) { /* edge still holds it */ }
    }
  }
  server.close();
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
  const bad = results.filter((r) => !/^PASS/.test(r.verdict));
  console.log('TOTAL', results.length, 'PASS', results.filter((r) => r.verdict === 'PASS').length,
    'PASS-noEsc', results.filter((r) => r.verdict === 'PASS-noEsc').length, 'other', bad.length);
  process.exit(bad.length ? 1 : 0);
}
run().catch((e) => { console.error(e); process.exit(2); });
