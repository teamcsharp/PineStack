/* [pip-rec] The album recorder in a real (hidden, offscreen) shell: it mounts free, record starts the set, the
 * clock and the size grow, next track counts, stop ends it, the notch folds it, the wrench lists the station's
 * checks, the art picker offers renders and clips and sets the cover; the Video menu pins a folder.
 *
 * Run with Electron, on local disk:   electron tests/test_pip_recorder_browser_2026_10_05.cjs [SHOT_DIR]
 * Isolated configuration; the station is a small in-memory model behind the desk's own ipc roads.
 */
const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const { pathToFileURL } = require('node:url');

const root = path.resolve(__dirname, '..');
const desktop = path.join(root, 'desktop');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-pip-rec-'));
const shots = process.argv.find((arg, i) => i > 1 && !arg.startsWith('-') && !arg.endsWith('.cjs')) || '';
if (shots) fs.mkdirSync(shots, { recursive: true });
app.setPath('userData', temp);
app.on('window-all-closed', () => {});
app.commandLine.appendSwitch('use-angle', 'swiftshader'); app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFklEQVR42mP8z8Dwn4EIwDiqkL4KAbgWCAH3Bq0cAAAAAElFTkSuQmCC', 'base64');

let win, server, cfg = {}, step = 'start';
const at = name => { step = name; console.log('.. ' + name); };
const native = require('../desktop/pip-window.cjs');
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: next => (cfg = { ...cfg, ...next }) });
const failTimer = setTimeout(() => { console.error('PiP recorder test timed out at ' + step); process.exit(1); }, 200000);
const shot = async name => { if (shots && win && !win.isDestroyed()) fs.writeFileSync(path.join(shots, name + '.png'), (await win.webContents.capturePage()).toPNG()); };
const page = code => win.webContents.executeJavaScript(code).catch(error => { console.error('the page script failed: ' + String(code).slice(0, 240)); throw error; });
const key = () => win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });
const rect = selector => page(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});if(!n)return null;const r=n.getBoundingClientRect();return {x:r.left,y:r.top,w:r.width,h:r.height,cx:r.left+r.width/2,cy:r.top+r.height/2};})()`);

/* ---- the station, in memory ---- */
const live = { armed: false, track: 1, startedAt: 0, cutStart: 0, cover: null, pin: null, posts: [] };
const liveState = () => {
  const el = live.armed ? (Date.now() - live.cutStart) / 1000 : 0;
  return { v: 2, enabled: true, phase: live.armed ? 'live' : 'idle', live: live.armed, armed: live.armed,
    event: live.armed ? { id: 'ev-1', name: 'MX Live', track: live.track, started_at: live.startedAt / 1000, live_seconds: (Date.now() - live.startedAt) / 1000, folder: 'set-1' } : null,
    source: { kind: 'usb', device: 'hw:CARD=EP136,DEV=0', label: 'EP-136 K.O. Sidekick', connected: live.armed, level_db: live.armed ? -18 : -70, peak_db: live.armed ? -6 : -60, clipping: false },
    recording: { on: live.armed, album: true, cut_seconds: 600, format: 'mp3', cut_index: live.track, cut_elapsed: Math.round(el * 10) / 10, cuts: live.track - 1, why: '', split: live.armed ? { track: live.track } : null },
    host: { up: true, age: .2, version: '1', why: '' }, art_url: live.armed ? '/art-live.png' : '', cover_override: live.cover ? { set: true, name: live.cover } : { set: false, name: '' }, errors: [] };
};

app.whenReady().then(async () => {
  let template = null; const buildMenu = Menu.buildFromTemplate;
  Menu.buildFromTemplate = t => { template = t; return { popup(options) { setTimeout(() => options.callback && options.callback(), 0); } }; };
  server = http.createServer((req, res) => {
    if (req.url.startsWith('/art') || req.url.startsWith('/api/sfx/poster') || req.url.startsWith('/api/generations/image')) { res.setHeader('Content-Type', 'image/png'); res.end(PNG); return; }
    if (req.url === '/vendor/three.min.js') { res.setHeader('Content-Type', 'application/javascript'); res.end(fs.readFileSync(path.join(desktop, 'vendor/three.min.js'))); return; }
    if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); res.end('{}'); return; }
    res.setHeader('Content-Type', 'text/html'); res.end('<html><body style="margin:0;background:#123"><h1>panel</h1></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  cfg = { baseUrl: base, pip: { widgets: { dialogue: true, rec: true }, bounds: { x: 60, y: 50, width: 700, height: 420 } } };
  ipcMain.handle('config:read', () => cfg);
  ipcMain.handle('replay:hold', (_e, seconds) => seconds);
  ipcMain.handle('agent:get', (_e, route) => {
    if (route.startsWith('/api/pinelive/state')) return liveState();
    if (route.startsWith('/api/pinelive/settings')) return { settings: { device: 'hw:CARD=EP136,DEV=0', enabled: true } };
    if (route.startsWith('/api/pinelive/troubleshoot')) return { checks: [{ result: 'pass', label: 'PineLive host service running', evidence: 'host_state.json 0.2 s old' }, { result: 'pass', label: 'USB device enumerated', evidence: 'USB 2367:9420 Teenage Engineering EP-136' }, { result: 'fail', label: 'Level healthy (not too low, not clipping)', evidence: 'very quiet (peak -90.3 dBFS)', fix: 'turn the K.O. Sidekick up' }], say: 'very quiet (peak -90.3 dBFS)' };
    if (route.startsWith('/api/pinelive/devices')) return { usb: [{ id: 'hw:CARD=EP136,DEV=0' }] };
    if (route.startsWith('/api/sfx/folders')) return { folders: [{ path: 'sfx/clips/madv', name: 'madv', video: 120, audio: 3, samples: [{ id: 'abcdefabcdefabcd', name: 'the corridor', video: true, url: '/sfx/abcdefabcdefabcd?t=sig1', seconds: 8 }] }, { path: 'sfx/clips/consp', name: 'consp', video: 40, audio: 0, samples: [] }], pin: live.pin };
    if (route.startsWith('/api/generations?')) return { generations: [{ kind: 'image', request: 'a pine box poster', files: ['poster_001.png'], status: 'done' }, { kind: 'video', request: 'queued one', files: [], status: 'queued' }] };
    if (route.startsWith('/api/sfx/video/mode')) return { on: false };
    return route.startsWith('/api/voices') ? [] : ({});
  });
  ipcMain.handle('agent:post', (_e, route, body) => {
    live.posts.push({ route, body });
    if (route === '/api/pinelive/start') { live.armed = true; live.track = 1; live.startedAt = live.cutStart = Date.now() - 2500; return { ok: true, say: 'live', state: liveState() }; }
    if (route === '/api/pinelive/stop') { live.armed = false; return { ok: true, say: 'stopped', state: liveState() }; }
    if (route === '/api/dj/next') { if (live.armed) { live.track++; live.cutStart = Date.now(); } return { ok: true }; }
    if (route === '/api/pinelive/cover') { live.cover = body.clear ? null : (body.generation || body.clip_id); return { ok: true, cover: { set: !!live.cover, name: live.cover || '' } }; }
    if (route === '/api/sfx/folder-pin') { live.pin = body.clear ? null : { path: body.path, name: body.path.split('/').pop(), minutes_left: 60 }; return { ok: true, say: body.clear ? 'every folder again' : 'pinned ' + body.path + ' for ' + body.hours + ' hour(s)' }; }
    return { ok: true };
  });
  ipcMain.handle('camera:where', () => ({ ok: false })); ipcMain.handle('camera:pip', () => ({ ok: true }));
  const resource = name => pathToFileURL(path.join(desktop, 'renderer', name)).href;
  const file = path.join(temp, 'fixture.html');
  fs.writeFileSync(file, `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="${resource('pineicons.css')}"><link rel="stylesheet" href="${resource('pine-pip.css')}"></head><body style="margin:0;background:#0b1410;color:#dfe">
    <input id="appVolume" type="range" value="35"><aside id="pineViewRail"></aside>
    <main><h1 style="margin:40px">THE FULL APP</h1><section id="control"><webview id="controlFrame" src="${base}" style="width:100%;height:500px"></webview></section></main>
    <audio id="desktopRadioPlayer"></audio>
    <script>window.pineThreeUrl=()=>${JSON.stringify(base + '/vendor/three.min.js')};window.desktopMusicUrl=u=>String(u).startsWith('/')?${JSON.stringify(base)}+u:u;window.pineStationBase=()=>${JSON.stringify(base)};window.PineStationFeed={refresh(){},subscribe(fn){window.receivePip=fn;return ()=>window.receivePip=null}};</script>
    <script src="${resource('pine-icons.js')}"></script><script src="${resource('pine-logo.js')}"></script><script src="${resource('pine-vcr.js')}"></script><script src="${resource('system3-message-tile.js')}"></script>
    <script src="${resource('pine-pip-shift.js')}"></script><script src="${resource('pine-pip.js')}"></script></body></html>`);
  win = new BrowserWindow({ show: false, frame: false, x: 40, y: 40, width: 1100, height: 760, minWidth: 520, minHeight: 420, webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const errors = [];
  win.webContents.on('console-message', e => { if (e.level === 'error' && !/favicon|ERR_|deprecated|Autofill/i.test(e.message)) errors.push(e.message + ' @' + e.lineNumber); });
  await win.loadFile(file); await delay(1500); win.isVisible = () => true;

  at('enter PiP'); key(); for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50); await delay(2600);
  const read = () => page(`(()=>{const b=document.querySelector('.pip-rec');if(!b)return null;const r=b.getBoundingClientRect();const q=s=>b.querySelector(s);return {parent:b.parentElement.id,free:b.classList.contains('pip-free'),x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),mini:b.classList.contains('mini'),armed:b.classList.contains('armed'),recording:b.classList.contains('recording'),track:q('.pip-rec-track').textContent,time:q('.pip-rec-time').textContent,size:q('.pip-rec-size').textContent,total:q('.pip-rec-total').textContent,range:q('.pip-rec-range').textContent,bar:q('.pip-rec-bar i').style.width,line:q('.pip-rec-line').textContent,recordTitle:q('.pip-rec-record').title,nextHidden:q('.pip-rec-next').hidden,art:!q('.pip-rec-art img').hidden,pop:!q('.pip-rec-pop').hidden,untitled:[...b.querySelectorAll('button')].filter(n=>!n.title&&!n.getAttribute('aria-label')).length};})()`);
  let r = await read();
  assert.ok(r, '[pip-rec] the recorder is on the overlay');
  assert.equal(r.parent, 'pinePipWidgets'); assert.equal(r.free, true, 'placed freely, not docked'); assert.ok(r.x > 100 && r.y > 100, 'at its home: ' + JSON.stringify([r.x, r.y]));
  assert.equal(r.armed, false); assert.equal(r.track, '1'); assert.equal(r.time, '00:00:00:00'); assert.equal(r.size, '0 KB'); assert.equal(r.range, '6:00');
  assert.match(r.line, /EP-136 K.O. Sidekick/); assert.match(r.line, /USB/); assert.match(r.recordTitle, /^Record/); assert.equal(r.untitled, 0, 'every button has a title');
  await shot('1-recorder-idle');

  at('record'); await page(`document.querySelector('.pip-rec-record').click()`); await delay(1800);
  r = await read();
  assert.deepEqual(live.posts.filter(p => p.route === '/api/pinelive/start').map(p => p.body), [{ source: 'usb', device: 'hw:CARD=EP136,DEV=0' }], 'record starts the set on the chosen USB interface');
  assert.equal(r.armed, true); assert.equal(r.recording, true); assert.match(r.recordTitle, /^Stop/); assert.equal(r.track, '1');
  assert.match(r.time, /^00:00:0[3-6]:\d\d$/, 'the clock runs from the station\'s cut_elapsed: ' + r.time);
  assert.match(r.size, /^\d{3} KB$/, 'the size grows at 320 kb/s: ' + r.size); assert.ok(parseFloat(r.bar) > 0.5, 'the bar fills: ' + r.bar);
  assert.match(r.total, /^TOTAL 0:0[3-7]$/, 'total session time: ' + r.total); assert.equal(r.art, true, 'the set\'s art shows'); assert.equal(r.nextHidden, false);
  const t1 = r.time; await delay(1200); r = await read(); assert.notEqual(r.time, t1, 'and keeps running');
  await shot('2-recording');

  at('next track'); await page(`document.querySelector('.pip-rec-next').click()`); await delay(1500);
  r = await read();
  assert.equal(live.posts.filter(p => p.route === '/api/dj/next').length, 1, 'next track goes down the DJ next road, which the live set owns');
  assert.equal(r.track, '2', 'the track number counts'); assert.match(r.time, /^00:00:0[0-3]:\d\d$/, 'the clock restarted: ' + r.time);

  at('mini'); const notch = await rect('.pip-rec-notch');
  win.webContents.sendInputEvent({ type: 'mouseDown', x: Math.round(notch.cx), y: Math.round(notch.cy), button: 'left', clickCount: 1 }); await delay(40);
  win.webContents.sendInputEvent({ type: 'mouseUp', x: Math.round(notch.cx), y: Math.round(notch.cy), button: 'left', clickCount: 1 }); await delay(400);
  r = await read(); assert.equal(r.mini, true, 'a tap on the notch folds the recorder'); assert.ok(r.w < 160, 'the mini form is narrow: ' + r.w); assert.equal(r.nextHidden, false, 'next shows while recording');
  await shot('3-mini');
  const before = await rect('.pip-rec');
  const n2 = await rect('.pip-rec-notch');
  win.webContents.sendInputEvent({ type: 'mouseDown', x: Math.round(n2.cx), y: Math.round(n2.cy), button: 'left', clickCount: 1 });
  for (let i = 1; i <= 6; i++) { win.webContents.sendInputEvent({ type: 'mouseMove', x: Math.round(n2.cx + 20 * i), y: Math.round(n2.cy + 10 * i), button: 'left', modifiers: ['leftButtonDown'] }); await delay(30); }
  win.webContents.sendInputEvent({ type: 'mouseUp', x: Math.round(n2.cx + 120), y: Math.round(n2.cy + 60), button: 'left', clickCount: 1 }); await delay(500);
  const after = await rect('.pip-rec'); r = await read();
  assert.ok(after.x > before.x + 60 && after.y > before.y + 30, 'the notch drags the recorder: ' + JSON.stringify([before.x, before.y, after.x, after.y]));
  assert.equal(r.mini, true, 'a drag is not a tap');
  assert.ok(cfg.pip.layout && cfg.pip.layout.rec && cfg.pip.layout.rec.x > .3, 'its place is a preference: ' + JSON.stringify(cfg.pip.layout));
  const n3 = await rect('.pip-rec-notch');
  win.webContents.sendInputEvent({ type: 'mouseDown', x: Math.round(n3.cx), y: Math.round(n3.cy), button: 'left', clickCount: 1 }); await delay(40);
  win.webContents.sendInputEvent({ type: 'mouseUp', x: Math.round(n3.cx), y: Math.round(n3.cy), button: 'left', clickCount: 1 }); await delay(400);
  r = await read(); assert.equal(r.mini, false, 'a second tap unfolds it');

  at('wrench'); await page(`document.querySelector('.pip-rec-tools').click()`); await delay(600);
  const checks = await page(`[...document.querySelectorAll('.pip-rec-checks li')].map(li => li.className + '|' + li.textContent)`);
  assert.equal(checks.length, 4, 'three checks and the verdict: ' + JSON.stringify(checks));
  assert.match(checks[0], /^pass\|PineLive host service running/); assert.match(checks[2], /^fail\|Level healthy.*very quiet.*turn the K.O. Sidekick up/); assert.match(checks[3], /^say\|very quiet/);
  assert.equal(await page(`!!document.querySelector('.pip-rec-pop-x')`), true, 'the popover has an X');
  await shot('4-troubleshoot');
  await page(`document.querySelector('.pip-rec-pop-x').click()`); await delay(200); r = await read(); assert.equal(r.pop, false);

  at('cover'); await page(`document.querySelector('.pip-rec-art').click()`); await delay(900);
  const tiles = await page(`[...document.querySelectorAll('.pip-rec-tile')].map(b => b.title)`);
  assert.ok(tiles.some(t => /^Image: a pine box poster/.test(t)), 'the finished render is offered: ' + JSON.stringify(tiles));
  assert.ok(tiles.some(t => /^Clip: the corridor \(madv\)/.test(t)), 'the clip\'s picture is offered');
  assert.ok(!tiles.some(t => /queued one/.test(t)), 'an unfinished render is not');
  await shot('5-cover-picker');
  await page(`[...document.querySelectorAll('.pip-rec-tile')].find(b => /^Clip:/.test(b.title)).click()`); await delay(900);
  assert.deepEqual(live.posts.filter(p => p.route === '/api/pinelive/cover').map(p => p.body), [{ clip_id: 'abcdefabcdefabcd' }], 'the clip becomes the cover');
  r = await read(); assert.equal(r.pop, false, 'the picker closes'); assert.match(r.line, /cover: abcdefabcdefabcd/);

  at('stop'); await page(`document.querySelector('.pip-rec-record').click()`); await delay(1500);
  r = await read(); assert.equal(live.posts.filter(p => p.route === '/api/pinelive/stop').length, 1); assert.equal(r.armed, false); assert.match(r.recordTitle, /^Record/); assert.equal(r.art, false, 'no set, no art');
  assert.match(r.total, /^TOTAL 0:\d\d$/, 'the session total keeps the set\'s time: ' + r.total);

  at('video menu'); const openMenu = () => page(`document.getElementById('pinePipWidgets').dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 200, clientY: 200 }))`);
  await openMenu(); await delay(1500); await openMenu(); await delay(600);   /* the first opening fetches the folders; the second lists them */
  const video = template.find(item => item.label === 'Video');
  assert.ok(video, 'the Video submenu'); const names = video.submenu.map(i => i.label || i.type);
  assert.ok(names.includes('madv  (120 video, 3 audio)') && names.includes('consp  (40 video, 0 audio)'), 'the station\'s folders are listed: ' + JSON.stringify(names));
  const sent = []; const send = win.webContents.send.bind(win.webContents); win.webContents.send = (...a) => { sent.push(a); return send(...a); };
  video.submenu.find(i => /^madv/.test(i.label)).click(); await delay(900);
  assert.deepEqual(live.posts.filter(p => p.route === '/api/sfx/folder-pin').map(p => p.body), [{ path: 'sfx/clips/madv', hours: 1 }], '[pip-video-folder] the folder is pinned for an hour');
  assert.deepEqual(errors, [], 'no errors in the shell');

  Menu.buildFromTemplate = buildMenu; clearTimeout(failTimer);
  win.destroy(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  console.log('PinePiP recorder: mount, record, clock and size, next track, mini, drag, wrench, cover and the Video menu passed.');
  setImmediate(() => app.quit());
}).catch(error => { console.error('at step ' + step + ':', error); clearTimeout(failTimer); try { server?.close(); } catch (_) {} process.exit(1); });
