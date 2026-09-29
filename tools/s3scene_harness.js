#!/usr/bin/env node
/* s3scene_harness.js - the Sys3 scene: navigation + tap-to-inspect + an edit round trip.
 * Headless Edge (--mute-audio) over CDP, no dependencies. Two profiles:
 *   desk   1920x1080, mouse: wheel zoom, left-drag orbit, right-drag pan, space-drag pan, double-click frame, click-pick, Esc
 *   tablet 1340x800, touch (the scene in a left pane): pinch zoom, one-finger orbit, two-finger pan, double-tap frame,
 *          tap a road / the centre / a packet / an airplane, edit a table (review -> confirm -> undo) against the stub API
 * Every gesture also asserts the page and every scroll container under the canvas did not scroll.
 *   node s3scene_harness.js <tree-with-frontend/> [--profile desk|tablet]
 * Output: results table on stdout, proofs/results.json, proofs/<profile>-<step>.png */
'use strict';
const fs = require('fs'), path = require('path'), http = require('http'), os = require('os'), crypto = require('crypto');
const {spawn} = require('child_process');
const TREE = path.resolve(process.argv[2] || '.');
const HERE = path.resolve(__dirname, '..');
const OUT = path.join(HERE, 'proofs'); fs.mkdirSync(OUT, {recursive: true});
const argv = process.argv.slice(3);
const profArg = argv.includes('--profile') ? argv[argv.indexOf('--profile') + 1] : '';
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const VENDOR = path.join(HERE, '..', 'closex', 'vendor');
const S = n => JSON.parse(fs.readFileSync(path.join(HERE, 'samples', 's3s_' + n + '.json'), 'utf8'));

/* ------------------------------------------------------------ the stub station */
const store = {cfg: S('config'), settings: S('settings'), status: S('status'), writes: []};
const byHash = new Map([[store.cfg.hash, JSON.parse(JSON.stringify(store.cfg.config))]]);
function saveCfg(note) {
  const h = crypto.createHash('sha1').update(JSON.stringify(store.cfg.config)).digest('hex').slice(0, 16);
  byHash.set(h, JSON.parse(JSON.stringify(store.cfg.config)));
  store.cfg.hash = h; store.cfg.versions.unshift({hash: h, created: Date.now() / 1000, note}); store.status.config_hash = h;
  return h;
}
const NOW = {at: Date.now() / 1000, line: {id: '54e4ad7d02504e879d60dbe9f37bb4d7', who: 'cohost', name: 'Skip', kind: 'banter', text: 'Oh man, swapping out the entire wiring harness is just awful.'},
  system3: {road: 'caller', turns: 9, turn: {turn: 2, rolls: [{dice: 40}, {dice: 77}, {dice: 12}]}}, register: {roads: 23, directed: 23, mode: 'active'}};
function api(req, res, u, q, body) {
  const J = (o, code) => { res.writeHead(code || 200, {'Content-Type': 'application/json'}); res.end(JSON.stringify(o)); };
  const m = req.method;
  if (u === '/api/system3/status') return J(Object.assign({}, store.status, {config_hash: store.cfg.hash}));
  if (u === '/api/system3/config') {
    if (q.get('hash')) { const c = byHash.get(q.get('hash')); return c ? J({hash: q.get('hash'), config: c}) : J({detail: 'no config'}, 404); }
    return J(store.cfg);
  }
  if (u === '/api/system3/settings' && m === 'GET') return J(store.settings);
  if (u === '/api/system3/settings' && m === 'POST') { store.writes.push({m, u, body}); Object.assign(store.settings.settings, body); return J({settings: store.settings.settings}); }
  let t = u.match(/^\/api\/system3\/tables\/([\w.-]+)$/);
  if (t && m === 'PUT') {
    store.writes.push({m, u, body}); const tbls = store.cfg.config.tables; const i = tbls.findIndex(x => x.id === t[1]);
    body.id = t[1]; body.version = (i >= 0 ? (tbls[i].version || 1) : 0) + 1; if (i >= 0) tbls[i] = body; else tbls.push(body);
    return J({hash: saveCfg('table ' + t[1] + ' v' + body.version), table: body});
  }
  t = u.match(/^\/api\/system3\/config\/section\/(\w+)$/);
  if (t && m === 'PUT') { store.writes.push({m, u, body}); store.cfg.config[t[1]] = body; return J({hash: saveCfg(t[1] + ' section')}); }
  if (u === '/api/system3/events') return J(q.get('after') === '0' ? {events: [], cursor: 0, head: 1500114} : {events: [], cursor: +q.get('after'), head: 1500114});
  if (u === '/api/system3/now') return J(NOW);
  if (u === '/api/system3/conversations') { const c = S('convs'); const road = q.get('road'); c.conversations.forEach(x => { if (road) x.road = road; x.conversation_id = '2603e15ecd6049ad'; }); return J(c); }
  if (u.startsWith('/api/system3/conversation/')) return J(S('conv'));
  if (u.startsWith('/api/system3/origin/')) return J(S('origin'));
  if (u === '/api/system3/segments') return J(S('segments'));
  if (u === '/api/system3/lists') return J(S('lists'));
  if (u.startsWith('/api/system3/replay/')) return J(S('replay'));
  return J({});
}
const PAGE = prof => `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/system3/system3.css"><script src="/icons/pine-icons.js"></script><script src="/r/pine-dismiss.js"></script>
<style>body{margin:0;background:#101418;color:#ccc;font:13px sans-serif;min-height:3000px} #tall{height:2800px}
${prof === 'tablet' ? '.s3-backdrop{inset:56px auto 0 0 !important;width:780px;padding:0 !important}' : ''}</style></head>
<body><div id="tall">the page under the window (tall, so a scroll would show)</div>
<script type="module">
const request = async (p, o) => { const r = await fetch(p, Object.assign({headers: {'Content-Type': 'application/json'}}, o || {})); const j = await r.json(); if (!r.ok) throw new Error(j.detail || r.status); return j; };
window.confirm = () => true;
const mod = await import('/system3/system3.js');
window.__win = await mod.openSystem3({request, tab: 'sys3'});
</script></body></html>`;
const TYPES = {'.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.woff2': 'font/woff2', '.svg': 'image/svg+xml'};
let curProf = 'desk';
const server = http.createServer((req, res) => {
  const [p0, qs] = req.url.split('?'); const u = decodeURIComponent(p0); const q = new URLSearchParams(qs || '');
  let raw = ''; req.on('data', c => { raw += c; }); req.on('end', () => {
    if (u === '/') { res.writeHead(200, {'Content-Type': 'text/html'}); res.end(PAGE(curProf)); return; }
    if (u.startsWith('/api/')) { let body = null; try { body = raw ? JSON.parse(raw) : null; } catch (e) { body = raw; } return api(req, res, u, q, body); }
    let file = null; let m;
    if ((m = u.match(/^\/system3\/([\w.-]+)$/))) file = path.join(TREE, 'frontend', m[1]);
    else if ((m = u.match(/^\/icons\/([\w.-]+)$/))) file = path.join(HERE, 'base', 'frontend', m[1]);
    else if ((m = u.match(/^\/r\/([\w.-]+)$/))) file = path.join(HERE, 'base', 'desktop', 'renderer', m[1]);
    else if ((m = u.match(/^\/vendor\/([\w.-]+)$/))) file = path.join(VENDOR, m[1]);
    if (!file) { res.writeHead(404); res.end(); return; }
    fs.readFile(file, (err, b) => { if (err) { res.writeHead(404); res.end(); return; } res.writeHead(200, {'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream'}); res.end(b); });
  });
});

/* ------------------------------------------------------------------- CDP */
const wait = ms => new Promise(r => setTimeout(r, ms));
async function getJSON(url) { for (let i = 0; i < 80; i += 1) { try { return await (await fetch(url)).json(); } catch (e) { await wait(250); } } throw new Error('no CDP'); }
class Tab {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.logs = [];
    ws.onmessage = m => { const d = JSON.parse(m.data);
      if (d.id && this.pending.has(d.id)) { const p = this.pending.get(d.id); this.pending.delete(d.id); d.error ? p.rej(new Error(d.error.message)) : p.res(d.result); }
      else if (d.method === 'Runtime.exceptionThrown') this.logs.push('EXC ' + JSON.stringify(d.params.exceptionDetails).slice(0, 300));
      else if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') this.logs.push('ERR ' + d.params.args.map(a => a.value || a.description).join(' ').slice(0, 300)); }; }
  send(method, params = {}) { const id = ++this.id; return new Promise((res, rej) => { this.pending.set(id, {res, rej}); this.ws.send(JSON.stringify({id, method, params})); }); }
  async eval(expr) { const r = await this.send('Runtime.evaluate', {expression: expr, awaitPromise: true, returnByValue: true});
    if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception || {}).description || r.exceptionDetails.text); return r.result.value; }
  async shot(name) { const r = await this.send('Page.captureScreenshot', {format: 'png'}); fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(r.data, 'base64')); }
  mouse(type, x, y, extra = {}) { return this.send('Input.dispatchMouseEvent', Object.assign({type, x, y, button: 'none', pointerType: 'mouse'}, extra)); }
  async drag(x0, y0, x1, y1, button = 'left', steps = 12) {
    const buttons = {left: 1, right: 2, middle: 4}[button];
    await this.mouse('mouseMoved', x0, y0); await this.mouse('mousePressed', x0, y0, {button, buttons, clickCount: 1});
    for (let i = 1; i <= steps; i += 1) { await this.mouse('mouseMoved', x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps, {button, buttons}); await wait(16); }
    await this.mouse('mouseReleased', x1, y1, {button, buttons: 0, clickCount: 1});
  }
  async click(x, y, count = 1) { await this.mouse('mouseMoved', x, y); await this.mouse('mousePressed', x, y, {button: 'left', buttons: 1, clickCount: count}); await this.mouse('mouseReleased', x, y, {button: 'left', buttons: 0, clickCount: count}); }
  touch(type, pts) { return this.send('Input.dispatchTouchEvent', {type, touchPoints: pts.map((p, i) => ({x: p[0], y: p[1], id: p[2] == null ? i : p[2], radiusX: 4, radiusY: 4, force: 1}))}); }
  async tap(x, y) { await this.touch('touchStart', [[x, y]]); await wait(40); await this.touch('touchEnd', []); }
  async swipe(from, to, steps = 12) {          /* from/to: arrays of [x,y] (one or two fingers) */
    await this.touch('touchStart', from);
    for (let i = 1; i <= steps; i += 1) { await this.touch('touchMove', from.map((p, k) => [p[0] + (to[k][0] - p[0]) * i / steps, p[1] + (to[k][1] - p[1]) * i / steps])); await wait(16); }
    await this.touch('touchEnd', []);
  }
  async key(key, code, vk, type) { await this.send('Input.dispatchKeyEvent', {type, key, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk}); }
}

/* in-page helpers */
const H = String.raw`(() => { if (window.__h) return true;
  window.__h = {
    host: () => document.querySelector('.s3-sys3'),
    api: () => { const h = document.querySelector('.s3-sys3'); return h && h.pineSys3; },
    scrolls() { const out = [window.scrollY, document.scrollingElement.scrollTop]; let n = document.querySelector('.s3-sys3 canvas');
      while (n) { out.push(n.scrollTop || 0, n.scrollLeft || 0); n = n.parentElement; } return out.join(','); },
    canvas() { const r = document.querySelector('.s3-sys3 canvas').getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; },
    inSide(n) { const s = document.querySelector('.s3-sys3-side'); if (!s || !s.contains(n)) { n.scrollIntoView({block: 'nearest'}); return; }
      const r = n.getBoundingClientRect(), q = s.getBoundingClientRect(); if (r.top < q.top + 60 || r.bottom > q.bottom - 10) s.scrollTop += r.top - q.top - q.height / 2; },
    rect(sel, text) { const n = [...document.querySelectorAll(sel)].find(x => !text || (x.textContent || '').includes(text)); if (!n) return null; this.inSide(n);
      const r = n.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; },
    side() { const s = document.querySelector('.s3-sys3-side'); if (!s || s.hidden) return null; const r = s.getBoundingClientRect();
      const x = s.querySelector('.s3-sys3-x'); const xr = x.getBoundingClientRect();
      return {kind: s.querySelector('.s3-pill').textContent, title: s.querySelector('h3').textContent, left: r.left, right: r.right,
        sections: [...s.querySelectorAll('.s3-sys3-sec h4')].map(h => h.textContent), text: s.textContent.slice(0, 40000),
        x: {title: x.title, aria: x.getAttribute('aria-label'), cx: xr.left + xr.width / 2, cy: xr.top + xr.height / 2, topRight: xr.right >= r.right - 6 && xr.top <= r.top + 12, hit: document.elementFromPoint(xr.left + xr.width / 2, xr.top + xr.height / 2) && x.contains(document.elementFromPoint(xr.left + xr.width / 2, xr.top + xr.height / 2))}}; },
  }; return true; })()`;

async function run(prof) {
  curProf = prof.name;
  const dbg = 9500 + Math.floor(Math.random() * 400); const udd = fs.mkdtempSync(path.join(os.tmpdir(), 's3scene-'));
  const edge = spawn(EDGE, ['--headless=new', '--mute-audio', '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--inprivate', '--disable-sync',
    '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--disable-extensions', '--remote-debugging-port=' + dbg, '--user-data-dir=' + udd,
    '--window-size=' + prof.w + ',' + prof.h, 'about:blank'], {stdio: 'ignore'});
  const results = [];
  const ok = (name, pass, detail) => { results.push({profile: prof.name, name, pass: !!pass, detail}); console.log((pass ? 'PASS ' : 'FAIL ') + prof.name + ' ' + name + (detail ? '  ' + JSON.stringify(detail).slice(0, 260) : '')); };
  try {
    const page = (await getJSON('http://127.0.0.1:' + dbg + '/json/list')).find(t => t.type === 'page');
    const ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise(r => { ws.onopen = r; });
    const tab = new Tab(ws);
    await tab.send('Runtime.enable'); await tab.send('Page.enable');
    await tab.send('Emulation.setDeviceMetricsOverride', {width: prof.w, height: prof.h, deviceScaleFactor: 1, mobile: false});
    if (prof.touch) await tab.send('Emulation.setTouchEmulationEnabled', {enabled: true, maxTouchPoints: 5});
    await tab.send('Page.navigate', {url: 'http://127.0.0.1:' + server.address().port + '/'});
    let ready = false; for (let i = 0; i < 80 && !ready; i += 1) { await wait(250); try { ready = await tab.eval(`!!(document.querySelector('.s3-sys3') && document.querySelector('.s3-sys3').pineSys3)`); } catch (e) { /* loading */ } }
    ok('scene mounted (three.js + controls)', ready, tab.logs.slice(0, 3));
    if (!ready) return results;
    await tab.eval(H); await wait(900);
    await tab.eval(`__h.api().freeze()`);                         /* packets hold still for a tap */
    const C = await tab.eval('__h.canvas()'); const cx = C.x + C.w * 0.45, cy = C.y + C.h * 0.55;
    ok('touch-action none on the canvas only', await tab.eval(`getComputedStyle(document.querySelector('.s3-sys3 canvas')).touchAction === 'none' && getComputedStyle(document.body).touchAction !== 'none'`));
    const scroll0 = await tab.eval('__h.scrolls()');
    const view = () => tab.eval('__h.api().view()');
    const settle = () => wait(450);
    await tab.shot(prof.name + '-0-start');
    const v0 = await view();
    if (!prof.touch) {
      /* wheel zoom about the pointer */
      await tab.mouse('mouseMoved', cx, cy); await tab.send('Input.dispatchMouseEvent', {type: 'mouseWheel', x: cx, y: cy, deltaX: 0, deltaY: -600, pointerType: 'mouse'}); await settle();
      const v1 = await view(); ok('wheel zooms in (radius down), page did not scroll', v1.r < v0.r * 0.75 && (await tab.eval('__h.scrolls()')) === scroll0, {r0: v0.r, r1: v1.r});
      await tab.shot(prof.name + '-1-wheel-zoom');
      await tab.drag(cx, cy, cx + 220, cy + 60); await settle();
      const v2 = await view(); ok('left-drag orbits (theta/phi move, target holds)', Math.abs(v2.theta - v1.theta) > 0.5 && Math.abs(v2.phi - v1.phi) > 0.05 && JSON.stringify(v2.target) === JSON.stringify(v1.target) && !v2.drift, {theta: v2.theta, phi: v2.phi});
      await tab.shot(prof.name + '-2-orbit');
      await tab.drag(cx, cy, cx - 200, cy - 40, 'right'); await settle();
      const v3 = await view(); ok('right-drag pans (target moves, radius holds)', Math.hypot(v3.target[0] - v2.target[0], v3.target[1] - v2.target[1], v3.target[2] - v2.target[2]) > 1 && Math.abs(v3.r - v2.r) < 0.01, {target: v3.target});
      await tab.key(' ', 'Space', 32, 'keyDown'); await tab.drag(cx, cy, cx + 150, cy); await tab.key(' ', 'Space', 32, 'keyUp'); await settle();
      const v4 = await view(); ok('space-drag pans', Math.hypot(v4.target[0] - v3.target[0], v4.target[2] - v3.target[2], v4.target[1] - v3.target[1]) > 1 && Math.abs(v4.theta - v3.theta) < 0.01, {target: v4.target});
      await tab.shot(prof.name + '-3-pan');
      ok('no page / container scroll through the gestures', (await tab.eval('__h.scrolls()')) === scroll0);
      await tab.click(C.x + 60, C.y + 70); await wait(60); await tab.click(C.x + 60, C.y + 70, 2); await settle(); await wait(400);
      const v5 = await view(); ok('double-click frames all (back to home)', Math.abs(v5.r - v5.home.r) < 0.05 && v5.drift, {r: v5.r, home: v5.home.r});
      /* limits: zoom far out and far in */
      for (let i = 0; i < 12; i += 1) await tab.send('Input.dispatchMouseEvent', {type: 'mouseWheel', x: cx, y: cy, deltaX: 0, deltaY: 1200, pointerType: 'mouse'});
      const vf = await view();
      for (let i = 0; i < 20; i += 1) await tab.send('Input.dispatchMouseEvent', {type: 'mouseWheel', x: cx, y: cy, deltaX: 0, deltaY: -1200, pointerType: 'mouse'});
      const vn = await view(); ok('zoom limits hold (3.5 .. 70)', vf.r <= 70.001 && vn.r >= 3.499, {out: vf.r, in: vn.r});
      await tab.key('0', 'Digit0', 48, 'keyDown'); await tab.key('0', 'Digit0', 48, 'keyUp'); await wait(900);
    }
    if (prof.touch) {
      /* pinch zoom (fingers apart) */
      await tab.swipe([[cx - 40, cy], [cx + 40, cy]], [[cx - 160, cy], [cx + 160, cy]]); await settle();
      const v1 = await view(); ok('pinch apart zooms in', v1.r < v0.r * 0.6, {r0: v0.r, r1: v1.r});
      await tab.shot(prof.name + '-1-pinch');
      await tab.swipe([[cx - 160, cy], [cx + 160, cy]], [[cx - 60, cy], [cx + 60, cy]]); await settle();
      const v1b = await view(); ok('pinch together zooms out', v1b.r > v1.r * 1.8, {r: v1b.r});
      await tab.swipe([[cx, cy]], [[cx + 200, cy + 80]]); await settle();
      const v2 = await view(); ok('one-finger drag orbits', Math.abs(v2.theta - v1b.theta) > 0.5 && JSON.stringify(v2.target) === JSON.stringify(v1b.target), {theta: v2.theta, phi: v2.phi});
      await tab.shot(prof.name + '-2-orbit');
      await tab.swipe([[cx - 50, cy], [cx + 50, cy]], [[cx - 50 - 150, cy - 90], [cx + 50 - 150, cy - 90]]); await settle();
      const v3 = await view(); ok('two-finger drag pans (radius holds)', Math.hypot(v3.target[0] - v2.target[0], v3.target[1] - v2.target[1], v3.target[2] - v2.target[2]) > 1 && Math.abs(v3.r - v2.r) / v2.r < 0.02, {target: v3.target});
      await tab.shot(prof.name + '-3-pan');
      ok('no page / container scroll through the gestures', (await tab.eval('__h.scrolls()')) === scroll0, {before: scroll0, after: await tab.eval('__h.scrolls()')});
      await tab.eval(`(() => { window.__pl = []; const c = document.querySelector('.s3-sys3 canvas'); ['pointerdown','pointerup'].forEach(t => c.addEventListener(t, e => __pl.push(t + ' ' + Math.round(e.timeStamp)), true)); return 1; })()`);
      const tq = Date.now(); await tab.tap(C.x + 60, C.y + 70); await wait(60); await tab.tap(C.x + 60, C.y + 70); const tapMs = Date.now() - tq; await settle(); await wait(400);
      if (argv.includes('--debug')) console.log('double-tap took', tapMs, 'ms over CDP', JSON.stringify(await tab.eval('__pl')));
      const v5 = await view(); ok('double-tap frames all (back to home)', Math.abs(v5.r - v5.home.r) < 0.05 && v5.drift, {r: v5.r, home: v5.home.r});
      await tab.shot(prof.name + '-4-reset');
      await wait(400);
    }
    /* ---- picking ---- */
    const at = async (kind, id) => tab.eval(`__h.api().screenOf(${JSON.stringify(kind)}, ${JSON.stringify(id)})`);
    const hit = async (p) => { if (prof.touch) await tab.tap(p.x, p.y); else await tab.click(p.x, p.y); await wait(500); };
    const road = await at('road', 'caller'); await hit(road);
    let sd = await tab.eval('__h.side()');
    ok('tap a road opens the inspector on it', sd && sd.kind === 'road' && sd.title === 'caller' && ['Register', 'Tables', 'Pools', 'Recent lines and their rolls', 'Rates and failures', 'Hour segments'].every(s => sd.sections.some(x => x.startsWith(s))), sd && {title: sd.title, sections: sd.sections});
    ok('the inspector has a top-right X with a title, hit-testable', sd && sd.x.topRight && sd.x.hit && /Close/.test(sd.x.title), sd && sd.x);
    ok('the view is untouched by a tap (no orbit)', (await view()).drift === true);
    await wait(1200); await tab.shot(prof.name + '-5-road');
    sd = await tab.eval('__h.side()'); ok('road inspector filled from the API (legs, rolls, rates, segments)', /Answer the line/.test(sd.text) && /rounds read/.test(sd.text) && /per hour/.test(sd.text) && /CALLEVENT1/.test(sd.text), {len: sd.text.length});
    /* the scene keeps working beside the inspector */
    const vb = await view();
    if (prof.touch) await tab.swipe([[C.x + 80, cy]], [[C.x + 200, cy + 40]]); else await tab.drag(C.x + 80, cy, C.x + 200, cy + 40);
    await settle(); ok('the scene still orbits beside the open inspector', Math.abs((await view()).theta - vb.theta) > 0.2 && !!(await tab.eval('__h.side()')));
    /* ---- the edit round trip (a table weight) ---- */
    const openT = await tab.eval(`(() => { const d = document.querySelector('.s3-sys3-side [data-table="CALLEVENT1"]'); d.open = true; const i = d.querySelector('.s3-sys3-num'); __h.inSide(i); return true; })()`);
    const inp = await tab.eval(`__h.rect('.s3-sys3-side [data-table="CALLEVENT1"] .s3-sys3-num')`);
    await hit(inp);
    await tab.eval(`(() => { const i = document.querySelector('.s3-sys3-side [data-table="CALLEVENT1"] .s3-sys3-num'); i.value = '2.5'; i.dispatchEvent(new Event('input', {bubbles: true})); return true; })()`);
    const rev = await tab.eval(`__h.rect('.s3-sys3-side [data-table="CALLEVENT1"] .s3-sys3-review')`); await hit(rev);
    const card = await tab.eval(`(() => { const c = document.querySelector('.s3-sys3-edit'); return c ? c.textContent : ''; })()`);
    ok('Review shows what will change before saving', openT && /weight/.test(card) && /2\.5/.test(card) && /Confirm/.test(card) && store.writes.length === 0, {card: card.slice(0, 160)});
    await tab.shot(prof.name + '-6-review');
    const hash0 = store.cfg.hash;
    await hit(await tab.eval(`__h.rect('.s3-sys3-confirm')`)); await wait(800);
    const w1 = store.writes[store.writes.length - 1];
    const saved = await tab.eval(`document.querySelector('.s3-sys3-edit').textContent`);
    ok('Confirm PUTs /api/system3/tables/CALLEVENT1 and reports the saved hash', w1 && w1.m === 'PUT' && /tables\/CALLEVENT1$/.test(w1.u) && w1.body.weight === 2.5 && saved.includes(store.cfg.hash) && saved.includes(hash0), {saved: saved.slice(0, 160), hash: store.cfg.hash});
    await tab.shot(prof.name + '-7-saved');
    const hash1 = store.cfg.hash;
    await hit(await tab.eval(`__h.rect('.s3-sys3-undo')`)); await wait(800);
    const w2 = store.writes[store.writes.length - 1]; const undone = await tab.eval(`document.querySelector('.s3-sys3-edit').textContent`);
    ok('Undo writes the previous version back (weight 1.0 from config ' + hash0 + ')', store.writes.length === 2 && w2.body.weight === 1 && /Undone/.test(undone) && store.cfg.hash !== hash1 && undone.includes(store.cfg.hash), {undone: undone.slice(0, 160)});
    await tab.shot(prof.name + '-8-undone');
    /* ---- the centre ---- */
    if (!prof.touch) { await tab.key('Escape', 'Escape', 27, 'keyDown'); await tab.key('Escape', 'Escape', 27, 'keyUp'); await wait(300);
      ok('Esc closes the inspector, not the System 3 window', !(await tab.eval('__h.side()')) && (await tab.eval(`!!document.querySelector('.s3-backdrop')`))); }
    else { const s = await tab.eval('__h.side()'); await tab.tap(s.x.cx, s.x.cy); await wait(300); ok('the X closes the inspector', !(await tab.eval('__h.side()'))); }
    await hit(await at('system3', 'system3')); await wait(700);
    sd = await tab.eval('__h.side()');
    ok('tap the centre opens System 3: config, active tables, the stats counts', sd && sd.kind === 'System 3' && /planned/.test(sd.text) && /ledger/.test(sd.text) && sd.sections.some(x => x.startsWith('Active tables')) && sd.sections.includes('Config sections') && sd.text.includes(store.cfg.hash), sd && sd.sections);
    await tab.shot(prof.name + '-9-centre');
    /* ---- a packet (frozen mid-circuit) ---- */
    const innerH = prof.h;
    const clear = async () => { const sd0 = await tab.eval('__h.side()'); const c0 = await tab.eval('__h.canvas()');
      return p => p.x > c0.x + 20 && p.y > c0.y + 50 && p.y < Math.min(c0.y + c0.h, innerH) - 30 && (!sd0 || p.x < sd0.left - 20); };
    const okAt = await clear(); const cands = (await tab.eval(`__h.api().screens('packet')`)).filter(p => okAt(p));
    const core = await at('system3', 'system3');
    cands.sort((a, b) => Math.hypot(b.x - core.x, b.y - core.y) - Math.hypot(a.x - core.x, a.y - core.y));
    const pk = cands[0]; if (argv.includes('--debug')) console.log('packet candidates', JSON.stringify(cands.slice(0, 4)));
    await hit(pk); await wait(2500);
    sd = await tab.eval('__h.side()'); if (argv.includes('--debug')) console.log('PACKET', sd && sd.text.slice(0, 1500));
    ok('tap a packet opens its circuit with its origin record and replay', sd && sd.kind === 'packet' && /Circuit/.test(sd.text) && /rolled/.test(sd.text) && /Replay the rolls/.test(sd.text), sd && {kind: sd.kind, sections: sd.sections});
    for (let i = 0; i < 40 && !(await tab.eval(`/origin record/.test((document.querySelector('.s3-sys3-side') || {}).textContent || '')`)); i += 1) await wait(150);
    await wait(300);
    await tab.eval(`__h.rect('.s3-sys3-replay')`); await wait(500);
    const rp = await tab.eval(`(() => { const r = document.querySelector('.s3-sys3-replay').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`); await hit(rp); await wait(900);
    if (argv.includes('--debug')) console.log('REPLAY', JSON.stringify(rp), await tab.eval(`(() => { const b = document.querySelector('.s3-sys3-replay'); const r = b.getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return b.disabled + ' ' + JSON.stringify(r) + ' ' + (e && e.className); })()`));
    ok('the roll replay answers', /every draw reproduced/.test((await tab.eval('__h.side()')).text));
    await tab.shot(prof.name + '-10-packet');
    /* ---- a paper airplane ---- */
    await tab.eval(`__h.api().fly({kind: 'observation', family: 'COMMIT', stage: 'script-ledger', round: 'manager', lines: ['54e4ad7d02504e879d60dbe9f37bb4d7'], conversation_id: '2603e15ecd6049ad', at: Date.now() / 1000, cursor: 1500121})`);
    await tab.eval(`__h.api().freeze()`); await wait(200);
    let pl = await at('plane', null); if (!(await clear())(pl)) { const s0 = await tab.eval('__h.side()'); if (s0) { await hit({x: s0.x.cx, y: s0.x.cy}); } pl = await at('plane', null); }
    await hit(pl); await wait(900);
    sd = await tab.eval('__h.side()');
    ok('tap a paper airplane opens the decision with its origin record', sd && sd.kind === 'paper airplane' && /COMMIT/.test(sd.text) && /rolled/.test(sd.text), sd && {kind: sd.kind, sections: sd.sections});
    await tab.shot(prof.name + '-11-airplane');
    ok('no page / container scroll overall', (await tab.eval('__h.scrolls()')) === scroll0);
    ok('no page errors', !tab.logs.length, tab.logs.slice(0, 4));
  } catch (e) { ok('harness', false, String(e && e.stack || e).slice(0, 400)); }
  finally { try { edge.kill(); } catch (e) { /* gone */ } }
  return results;
}

(async () => {
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const all = [];
  for (const prof of [{name: 'desk', w: 1920, h: 1080, touch: false}, {name: 'tablet', w: 1340, h: 800, touch: true}].filter(p => !profArg || p.name === profArg)) {
    store.writes = [];
    all.push(...await run(prof));
  }
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(all, null, 1));
  const bad = all.filter(r => !r.pass);
  console.log(`\n${all.length - bad.length}/${all.length} passed`);
  server.close(); process.exit(bad.length ? 1 : 0);
})();
