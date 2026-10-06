/* [pip-panel-ready] [pip-art] [pip-free] [pip-playbar] [pip-export-bar] The second PiP wave, in a real (hidden, offscreen) shell window.
 *
 * Run with Electron, on local disk:   electron tests/test_pip_widgets_browser_2026_10_05.cjs [SHOT_DIR]
 * Isolated configuration and a local fixture station whose page opens an iframe after it loads -
 * the very thing that left PiP showing the raw page until F5. Never touches the live backend.
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
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-pip-widgets-'));
const shots = process.argv.find((arg, i) => i > 1 && !arg.startsWith('-') && !arg.endsWith('.cjs')) || '';
if (shots) fs.mkdirSync(shots, { recursive: true });
app.setPath('userData', temp);
app.on('window-all-closed', () => {});
app.commandLine.appendSwitch('use-angle', 'swiftshader');
app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFklEQVR42mP8z8Dwn4EIwDiqkL4KAbgWCAH3Bq0cAAAAAElFTkSuQmCC', 'base64');

let win, server, cfg = {};
const native = require('../desktop/pip-window.cjs');
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: next => (cfg = { ...cfg, ...next }) });
const failTimer = setTimeout(() => { console.error('PiP widgets test timed out'); app.exit(1); }, 240000);
const shot = async name => { if (shots && win && !win.isDestroyed()) fs.writeFileSync(path.join(shots, name + '.png'), (await win.webContents.capturePage()).toPNG()); };
const page = code => win.webContents.executeJavaScript(code).catch(error => { console.error('the page script failed: ' + String(code).slice(0, 240)); throw error; });
const inFrame = code => page('document.getElementById("controlFrame").executeJavaScript(' + JSON.stringify(code) + ')');
const key = () => win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });
const mouse = async (type, x, y, extra = {}) => { win.webContents.sendInputEvent({ type, x: Math.round(x), y: Math.round(y), button: 'left', clickCount: 1, ...extra }); await delay(30); };
const drag = async (from, to, steps = 6, modifiers = []) => {
  await mouse('mouseDown', from.x, from.y, { modifiers });
  for (let i = 1; i <= steps; i++) await mouse('mouseMove', from.x + (to.x - from.x) * i / steps, from.y + (to.y - from.y) * i / steps, { modifiers: ['leftButtonDown', ...modifiers] });
  await mouse('mouseUp', to.x, to.y, { modifiers });
  await delay(250);
};
const rect = selector => page(`(()=>{const n=document.querySelector(${JSON.stringify(selector)});if(!n)return null;const r=n.getBoundingClientRect();return {x:r.left,y:r.top,w:r.width,h:r.height,cx:r.left+r.width/2,cy:r.top+r.height/2};})()`);
const layout = () => JSON.parse(JSON.stringify((cfg.pip || {}).layout || {}));

app.whenReady().then(async () => {
  const buildMenu = Menu.buildFromTemplate;
  Menu.buildFromTemplate = template => ({ popup(options) { setTimeout(() => options.callback && options.callback(), 0); } });

  server = http.createServer((req, res) => {
    if (req.url.startsWith('/art-missing')) { res.statusCode = 404; res.end(); return; }
    if (req.url.startsWith('/art')) { res.setHeader('Content-Type', 'image/png'); res.end(PNG); return; }
    if (req.url === '/vendor/three.min.js') { res.setHeader('Content-Type', 'application/javascript'); res.end(fs.readFileSync(path.join(desktop, 'vendor/three.min.js'))); return; }
    if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); res.end('{}'); return; }
    if (req.url.startsWith('/press')) { res.setHeader('Content-Type', 'text/html'); res.end('<html><body style="background:#ece5d4">the endless press, in a frame</body></html>'); return; }
    res.setHeader('Content-Type', 'text/html');
    /* the station page opens an iframe a moment after it has loaded, as the Gazette press and a book preview do */
    res.end('<html><body style="margin:0;background:#123;color:#9ab;font:14px system-ui"><h1 id="panelHead" style="margin:20px">the station panel</h1>'
      + '<script>setTimeout(()=>{const f=document.createElement("iframe");f.id="pineSlidesFrame";f.src="/press";f.style.cssText="width:300px;height:120px";document.body.appendChild(f);window.frameOpened=true;},700);</script></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  cfg = { baseUrl: base, pip: { widgets: { dialogue: true, music: true, cast: true }, bounds: { x: 60, y: 50, width: 640, height: 400 } } };
  ipcMain.handle('config:read', () => cfg);
  ipcMain.handle('replay:hold', (_e, seconds) => seconds);
  const library = [{ id: 'a1', title: 'Marsh Pipe', artist: 'Lorna Shore', album: 'Pains', seconds: 201 }, { id: 'a2', title: 'Marshmallow World', artist: 'Dean Martin', album: 'Christmas', seconds: 150 }, { id: 'a3', title: 'Danny The Dog (feat. Lorna Marshall)', artist: 'Massive Attack', album: 'Collected', seconds: 362 }];
  const posts = [];
  ipcMain.handle('agent:get', (_e, route) => {
    if (route.startsWith('/api/music/search')) { const q = decodeURIComponent(route.split('q=')[1] || '').toLowerCase(); return { query: q, results: library.filter(hit => (hit.title + ' ' + hit.artist).toLowerCase().includes(q.split(' ')[0])) }; }
    return route.startsWith('/api/voices') ? [] : ({});
  });
  ipcMain.handle('agent:post', (_e, route, body) => { posts.push({ route, body }); return { ok: true, title: body?.q || '', artist: '' }; });
  ipcMain.handle('camera:where', () => ({ ok: false }));
  ipcMain.handle('camera:pip', () => ({ ok: true }));

  const resource = name => pathToFileURL(path.join(desktop, 'renderer', name)).href;
  const file = path.join(temp, 'fixture.html');
  fs.writeFileSync(file, `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="${resource('pineicons.css')}"><link rel="stylesheet" href="${resource('pine-pip.css')}"></head><body style="margin:0;background:#0b1410;color:#dfe">
    <input id="appVolume" type="range" value="35"><aside id="pineViewRail"></aside>
    <main><h1 style="margin:40px">THE FULL APP</h1>
    <section id="control"><webview id="controlFrame" preload="${resource('webview-preload.js')}" webpreferences="backgroundThrottling=no" src="${base}" style="width:100%;height:500px"></webview></section></main>
    <audio id="desktopRadioPlayer"></audio>
    <script>window.pineThreeUrl=()=>${JSON.stringify(base + '/vendor/three.min.js')};window.desktopMusicUrl=u=>u;window.PineStationFeed={refresh(){},subscribe(fn){window.receivePip=fn;return ()=>window.receivePip=null}};
    window.__levels={master:1,voice:1.2,music:.31,sfx:1,video:.8,pads:1};window.__applied=[];window.pineLevels={get(){return {...window.__levels}},apply(k,v){window.__levels[k]=v;window.__applied.push([k,v]);}};</script>
    <script src="${resource('pine-icons.js')}"></script><script src="${resource('pine-logo.js')}"></script><script src="${resource('pine-vcr.js')}"></script><script src="${resource('system3-message-tile.js')}"></script>
    <script src="${resource('pine-pip-shift.js')}"></script><script src="${resource('pine-pip.js')}"></script></body></html>`);
  win = new BrowserWindow({ show: false, frame: false, x: 40, y: 40, width: 1100, height: 760, minWidth: 520, minHeight: 420,
    webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const errors = [];
  win.webContents.on('console-message', event => { if (event.level === 'error' && !/favicon|ERR_|deprecated|Autofill|art-missing/i.test(event.message)) errors.push(event.message + ' @' + event.lineNumber); });
  await win.loadFile(file); await delay(1200);
  assert.equal(await page('typeof PinePip.enter'), 'function');
  win.isVisible = () => true;

  /* ---- 1. [pip-panel-ready] the page opened an iframe after it loaded; PiP still switches the page ---- */
  for (let n = 0; n < 60 && (await inFrame('!!window.frameOpened && !!document.getElementById("pineSlidesFrame")')) !== true; n++) await delay(100);
  await delay(600);   /* the iframe's own load has started and ended by now */
  assert.equal(await inFrame('document.documentElement.classList.contains("pine-pip")'), false);
  key(); for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50);
  await delay(2600);
  const switched = await inFrame('document.documentElement.classList.contains("pine-pip")+":"+(document.getElementById("pine-pip-panel")?getComputedStyle(document.getElementById("pine-pip-panel")).display:"none")');
  assert.equal(switched, 'true:block', '[pip-panel-ready] the station page shows its PiP panel although an iframe loaded after the page (was: raw page until F5)');
  assert.equal(await page(`document.body.classList.contains('pine-pip')`), true);
  await shot('1-pip-after-iframe');

  /* ---- 2. [pip-art] a record without artwork, then one with; a double-click reduces the player to the art ---- */
  const feed = art => page(`receivePip({station:{now:{id:'t',title:'Steamed Shrimp Break',artist:'The Polish Ambassador',album:'Diplomatic Immunity',seconds:111.8,art:${JSON.stringify(art)}},playing:true,paused:false,elapsed:10,remaining:101},rows:[],now:null})`);
  await feed(base + '/art-missing.jpg'); await delay(700);
  const shown = () => page(`(()=>{const b=document.querySelector('.pip-music'),v=s=>{const n=b.querySelector(s);return !!n&&!n.hidden&&getComputedStyle(n).display!=='none'&&n.getBoundingClientRect().width>0;};return {art:v('.pip-music-art'),blank:v('.pip-music-blank'),artOnly:b.classList.contains('art-only'),info:v('.pip-music-info'),keys:v('.pip-music-keys'),w:Math.round(b.getBoundingClientRect().width)};})()`);
  let m = await shown();
  assert.deepEqual({ art: m.art, blank: m.blank }, { art: false, blank: true }, '[pip-art] a 404 artwork gives way to the placeholder, no broken picture: ' + JSON.stringify(m));
  await feed(base + '/art.png'); await delay(700);
  m = await shown(); assert.deepEqual({ art: m.art, blank: m.blank }, { art: true, blank: false }, 'real artwork shows: ' + JSON.stringify(m));
  await feed(base + '/art-missing.jpg'); await delay(700);
  m = await shown(); assert.deepEqual({ art: m.art, blank: m.blank }, { art: false, blank: true }, 'and the next record without art is a placeholder again');
  await feed(base + '/art.png'); await delay(700);
  const art = await rect('.pip-music-art'); const wide = (await shown()).w;
  await mouse('mouseDown', art.cx, art.cy); await mouse('mouseUp', art.cx, art.cy); await mouse('mouseDown', art.cx, art.cy, { clickCount: 2 }); await mouse('mouseUp', art.cx, art.cy, { clickCount: 2 });
  await delay(500); m = await shown();
  assert.equal(cfg.pip.musicArtOnly, true, '[pip-art] the double-click is a preference');
  assert.deepEqual({ artOnly: m.artOnly, art: m.art, keys: m.keys }, { artOnly: true, art: true, keys: false }, 'only the artwork remains: ' + JSON.stringify(m));
  assert.ok(m.w < wide, 'the player shrank to the picture: ' + m.w + ' < ' + wide);
  await shot('2-art-only');
  const art2 = await rect('.pip-music-art');
  await mouse('mouseDown', art2.cx, art2.cy); await mouse('mouseUp', art2.cx, art2.cy); await mouse('mouseDown', art2.cx, art2.cy, { clickCount: 2 }); await mouse('mouseUp', art2.cx, art2.cy, { clickCount: 2 }); await delay(500);
  m = await shown(); assert.equal(cfg.pip.musicArtOnly, false); assert.deepEqual({ artOnly: m.artOnly, keys: m.keys }, { artOnly: false, keys: true }, 'a second double-click brings the player back (the compact player shows its keys, not its info row)');

  /* ---- 3. [pip-free] a docked widget is dragged free, nudged, scaled, resized, trimmed, adjusted, and docked again ---- */
  const dialogue = () => page(`(()=>{const w=document.querySelector('[data-widget=dialogue]'),r=w.getBoundingClientRect();return {parent:w.parentElement.className||w.parentElement.id,free:w.classList.contains('pip-free'),x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height),transform:w.style.transform,clip:w.style.clipPath,opacity:w.style.opacity,grips:w.querySelectorAll('.pip-free-edge').length};})()`);
  let d = await dialogue();
  assert.equal(d.free, false); assert.match(d.parent, /pip-dock-bottom/, 'it starts docked at the bottom');
  let grip = await rect('[data-widget=dialogue] .pip-grip');
  await drag({ x: grip.cx, y: grip.cy }, { x: 140, y: 150 });
  d = await dialogue();
  assert.equal(d.free, true, '[pip-free] dropped mid-window, the widget is placed freely: ' + JSON.stringify(d));
  assert.equal(d.parent, 'pinePipWidgets', 'it left the dock');
  assert.ok(Math.abs(d.y - 150 + (grip.cy - grip.y)) < 30, 'it sits where it was dropped: ' + JSON.stringify(d));
  let l = layout(); assert.ok(l.dialogue && Number.isFinite(l.dialogue.x) && Number.isFinite(l.dialogue.y), 'the place is a preference: ' + JSON.stringify(l));
  assert.equal(d.grips, 8, 'eight edge grips appeared');
  await shot('3-dragged-free');
  /* Ctrl+wheel scales */
  const body = await rect('[data-widget=dialogue]');
  win.webContents.sendInputEvent({ type: 'mouseWheel', x: Math.round(body.cx), y: Math.round(body.cy), deltaY: 120, modifiers: ['control'] });
  win.webContents.sendInputEvent({ type: 'mouseWheel', x: Math.round(body.cx), y: Math.round(body.cy), deltaY: 120, modifiers: ['control'] });
  await delay(900); d = await dialogue(); l = layout();
  assert.ok(l.dialogue.s > 1.05 && l.dialogue.s < 1.2, 'two notches up scale it: ' + JSON.stringify(l.dialogue));
  assert.match(d.transform, /scale\(1\.1/, 'the scale is drawn: ' + d.transform);
  /* the south-east grip resizes */
  const before = await dialogue();
  let se = await rect('[data-widget=dialogue] .pip-free-edge.se');
  await drag({ x: se.cx, y: se.cy }, { x: se.cx + 80, y: se.cy + 30 });
  d = await dialogue(); l = layout();
  assert.ok(l.dialogue.w > 0 && l.dialogue.h > 0, 'the size is a preference: ' + JSON.stringify(l.dialogue));
  assert.ok(d.w > before.w + 40, 'and it grew: ' + before.w + ' -> ' + d.w);
  /* Shift + the west grip trims the left side */
  const wg = await rect('[data-widget=dialogue] .pip-free-edge.w');
  await drag({ x: wg.cx, y: wg.cy }, { x: wg.cx + 60, y: wg.cy }, 6, ['shift']);
  d = await dialogue(); l = layout();
  assert.ok(Array.isArray(l.dialogue.t) && l.dialogue.t[3] > 5, 'the left trim is a preference: ' + JSON.stringify(l.dialogue.t));
  assert.match(d.clip, /^inset\(0% 0% 0% [0-9.]+%\)$/, 'the trim is drawn as a clip: ' + d.clip);
  await shot('3-scaled-resized-trimmed');
  /* the adjust popover. The left trim has clipped the handle away (a clip clips the hit test too), so the
     other road is used: Alt + right-click on the widget itself. Then "Reset trim", and the handle's own
     right-click toggles the popover. */
  const trimmedGrip = await rect('[data-widget=dialogue] .pip-grip');
  assert.notEqual(await page(`document.elementFromPoint(${trimmedGrip.cx},${trimmedGrip.cy})?.className`), 'pip-grip', 'the trimmed handle is not under the pointer');
  const mid = await rect('[data-widget=dialogue] .pip-marquee');
  const rightClick = async (x, y, modifiers = []) => { win.webContents.sendInputEvent({ type: 'mouseDown', x: Math.round(x), y: Math.round(y), button: 'right', clickCount: 1, modifiers }); win.webContents.sendInputEvent({ type: 'mouseUp', x: Math.round(x), y: Math.round(y), button: 'right', clickCount: 1, modifiers }); await delay(400); };
  await rightClick(mid.cx + 40, mid.cy, ['alt']);
  const pop = await page(`(()=>{const p=document.querySelector('.pip-adjust');if(!p)return null;const r=p.getBoundingClientRect();return {title:p.querySelector('header').textContent,x:!!p.querySelector('.pip-adjust-x'),sliders:p.querySelectorAll('input[type=range]').length,keys:[...p.querySelectorAll('.pip-adjust-keys button')].map(b=>b.textContent),inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight};})()`);
  assert.ok(pop, '[pip-free] right-click on the handle opens the layout options');
  assert.match(pop.title, /Dialogue/); assert.equal(pop.x, true, 'it has an X'); assert.equal(pop.sliders, 6, 'scale, opacity and four trims'); assert.equal(pop.inside, true, 'it is inside the window');
  assert.deepEqual(pop.keys, ['Dock top', 'Dock bottom', 'Reset size', 'Reset trim', 'Reset all', 'Hide widget']);
  await shot('3-adjust-popover');
  await page(`(()=>{const i=document.querySelector('.pip-adjust input[aria-label=Opacity]');i.value='0.5';i.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await delay(700); d = await dialogue(); l = layout();
  assert.equal(l.dialogue.o, .5, 'opacity is a preference'); assert.equal(d.opacity, '0.5');
  await page(`[...document.querySelectorAll('.pip-adjust-keys button')].find(b=>b.textContent==='Reset trim').click()`);
  await delay(600); d = await dialogue(); l = layout();
  assert.equal(l.dialogue.t, undefined, 'reset trim removes the trims'); assert.equal(d.clip, '');
  await page(`document.querySelector('.pip-adjust-x').click()`); await delay(200);
  assert.equal(await page(`!!document.querySelector('.pip-adjust')`), false, 'the X closes the popover');
  grip = await rect('[data-widget=dialogue] .pip-grip');
  assert.equal(await page(`document.elementFromPoint(${grip.cx},${grip.cy})?.className`), 'pip-grip', 'the handle is back under the pointer');
  await rightClick(grip.cx, grip.cy); assert.equal(await page(`!!document.querySelector('.pip-adjust')`), true, 'the handle\'s right-click opens the popover');
  await rightClick(grip.cx, grip.cy); assert.equal(await page(`!!document.querySelector('.pip-adjust')`), false, 'and a second one closes it');
  await rightClick(grip.cx, grip.cy); assert.equal(await page(`!!document.querySelector('.pip-adjust')`), true);
  await page(`[...document.querySelectorAll('.pip-adjust-keys button')].find(b=>b.textContent==='Reset all').click()`);
  await delay(600); d = await dialogue(); l = layout();
  assert.equal(l.dialogue, undefined, 'reset all removes the entry'); assert.equal(d.free, false); assert.match(d.parent, /pip-dock-bottom/, 'and the widget is back in its dock');
  assert.equal(await page(`!!document.querySelector('.pip-adjust')`), false, 'a reset closes the popover');
  assert.deepEqual([d.transform, d.clip, d.opacity], ['', '', ''], 'with nothing drawn on it');
  /* drag free again, then drop at the top edge: it docks at the top */
  grip = await rect('[data-widget=dialogue] .pip-grip');
  await drag({ x: grip.cx, y: grip.cy }, { x: 300, y: 12 });
  d = await dialogue(); l = layout();
  assert.equal(d.free, false); assert.match(d.parent, /pip-dock-top/, 'dropped at the top edge, it docks there: ' + JSON.stringify(d));
  assert.equal(cfg.pip.docks.dialogue, 'top'); assert.equal(l.dialogue, undefined);
  /* the cast portraits and the voices region have handles too; the chat's handle moves the chat box */
  assert.equal(await page(`!!document.querySelector('.pip-cast .pip-grip') && !!document.querySelector('.pip-voices .pip-grip')`), true, 'every widget has a handle');

  /* ---- 3b. [pip-levels] the volume popover carries every level of the mixer, the music first ---- */
  await page(`document.querySelector('.pip-music-vol').click()`); await delay(300);
  const levels = await page(`(()=>{const p=document.querySelector('.pip-music-pop');return {title:p.querySelector('header').textContent,rows:[...p.querySelectorAll('.pip-music-level')].map(r=>[r.querySelector('.pip-music-level-name').textContent,r.querySelector('input').value,r.querySelector('input').max,r.querySelector('output').textContent]),musicFirst:p.querySelector('.pip-music-level').classList.contains('pip-music-level-music'),x:!!p.querySelector('.pip-music-pop-x')};})()`);
  assert.deepEqual(levels.rows.map(r => r[0]), ['Music', 'Master', 'The DJs', 'Clips / SFX', 'Videos', 'Pads', 'Application'], JSON.stringify(levels));
  assert.deepEqual(levels.rows[0], ['Music', '31', '200', '31%'], 'the music row reads the bus: ' + JSON.stringify(levels.rows[0]));
  assert.deepEqual(levels.rows[2].slice(1), ['120', '200', '120%']); assert.deepEqual(levels.rows[1].slice(1), ['100', '100', '100%']);
  assert.equal(levels.musicFirst, true); assert.equal(levels.x, true, 'the popover has its X');
  await page(`(()=>{const i=document.querySelector('.pip-music-level input[data-level=music]');i.value='85';i.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await delay(100);
  assert.deepEqual(await page('JSON.stringify(window.__applied)'), JSON.stringify([['music', .85]]), '[pip-levels] the music level is written through the bus');
  await page(`(()=>{const i=document.querySelector('.pip-music-level input[data-level=sfx]');i.value='140';i.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  assert.deepEqual(await page('JSON.stringify(window.__applied)'), JSON.stringify([['music', .85], ['sfx', 1.4]]), 'so is every other item of the mixer');
  await page(`window.__levels.video=.5`); await delay(1300);
  assert.equal(await page(`document.querySelector('.pip-music-level input[data-level=video]').value`), '50', 'a level set elsewhere shows up within a second');
  await shot('3b-volume-levels');
  await page(`document.querySelector('.pip-music-pop-x').click()`); await delay(200);

  /* ---- 3c. [pip-find] records are suggested as the words are typed; a click asks for that record ---- */
  await page(`document.querySelector('.pip-music-find').click()`); await delay(300);
  const type = async text => { for (const ch of text) { win.webContents.sendInputEvent({ type: 'char', keyCode: ch }); await delay(20); } };
  assert.equal(await page(`document.activeElement === document.querySelector('.pip-music-pop input[type=search]')`), true, 'the field has focus');
  await type('marsh'); await delay(600);
  const hintsOf = () => page(`(()=>{const o=document.querySelector('.pip-music-hints');return {hidden:o.hidden,items:[...o.querySelectorAll('li')].map(li=>[li.querySelector('b').textContent,li.querySelector('span').textContent,li.classList.contains('chosen')]),inside:o.getBoundingClientRect().bottom<=innerHeight};})()`);
  let h = await hintsOf();
  assert.equal(h.hidden, false, '[pip-find] suggestions appear as the words are typed');
  assert.deepEqual(h.items.map(i => i[0]), ['Marsh Pipe', 'Marshmallow World', 'Danny The Dog (feat. Lorna Marshall)'], JSON.stringify(h.items));
  assert.equal(h.items[0][1], 'Lorna Shore \u00b7 Pains'); assert.equal(h.inside, true, 'the list stays inside the window');
  await shot('3c-record-hints');
  await type(' pipe'); await delay(600); h = await hintsOf();
  assert.deepEqual(h.items.map(i => i[0]), ['Marsh Pipe', 'Marshmallow World', 'Danny The Dog (feat. Lorna Marshall)'].filter(x => x.toLowerCase().includes('marsh')), 'the list follows the field');
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Down' }); await delay(150); h = await hintsOf();
  assert.deepEqual(h.items.map(i => i[2]), [true, false, false], 'the arrow keys choose');
  await page(`document.querySelectorAll('.pip-music-hints li button')[1].click()`); await delay(400);
  const requests = posts.filter(post => post.route === '/api/dj/request');
  assert.equal(requests.length, 1, 'one request was posted');
  assert.deepEqual(requests[0].body, { q: 'Marshmallow World Dean Martin', id: 'a2' }, 'the clicked record is asked for, by its words and its id: ' + JSON.stringify(requests[0].body));
  assert.equal(await page(`!!document.querySelector('.pip-music-pop:not([hidden])')`), false, 'a queued request closes the popover');

  /* ---- 4. [pip-playbar] the playing video's clock draws a 3 px bar along the foot ---- */
  const bar = () => page(`(()=>{const b=document.querySelector('.pip-playbar');if(!b)return null;const r=b.getBoundingClientRect(),cs=getComputedStyle(b);return {hidden:b.hidden,h:Math.round(r.height),bottom:Math.round(innerHeight-r.bottom),w:Math.round(r.width),played:b.style.getPropertyValue('--pip-played'),paused:b.classList.contains('paused'),clip:cs.clipPath,bg:cs.backgroundImage,now:b.getAttribute('aria-valuenow'),title:b.title};})()`);
  let p = await bar(); assert.ok(p, 'the bar exists'); assert.equal(p.hidden, true, 'and is hidden while nothing plays');
  await inFrame(`window.postMessage({type:'pine-pip-time',time:{at:30,dur:120,playing:true}},'*')`);   /* what the panel reports for a playing video */
  await delay(500); p = await bar();
  assert.equal(p.hidden, false, '[pip-playbar] the bar shows when the page reports a playing video');
  assert.equal(p.h, 3, 'it is 3 px'); assert.equal(p.bottom, 0, 'along the foot'); assert.equal(p.w, win.getContentBounds().width, 'across the display');
  assert.equal(p.played, '25.00%'); assert.equal(p.now, '25'); assert.equal(p.paused, false);
  assert.match(p.bg, /linear-gradient\(90deg, rgb\(34, 197, 94\) 0%, rgb\(59, 130, 246\) 55%, rgb\(255, 255, 255\) 100%\)/, 'green to blue to white: ' + p.bg);
  assert.match(p.title, /0:30 of 2:00 \(1:30 left\)/, p.title);
  await shot('4-playbar');
  await inFrame(`window.postMessage({type:'pine-pip-time',time:{at:90,dur:120,playing:false}},'*')`); await delay(500); p = await bar();
  assert.equal(p.played, '75.00%'); assert.equal(p.paused, true, 'a paused video dims the bar');
  await inFrame(`window.postMessage({type:'pine-pip-time',time:null},'*')`); await delay(500); p = await bar();
  assert.equal(p.hidden, true, 'no video, no bar');
  await page(`window.postMessage({type:'pine-pip-time',time:{at:6,dur:12,playing:true}},'*')`); await delay(400); p = await bar();
  assert.equal(p.played, '50.00%', 'the shell\'s own videos report the same way');
  await page(`window.postMessage({type:'pine-pip-time',time:null},'*')`); await delay(300);

  /* ---- 5. [pip-export-bar] an export draws the same bar with the words over it ---- */
  const ex = () => page(`(()=>{const b=document.querySelector('.pip-exportbar');if(!b)return null;const r=b.getBoundingClientRect();return {hidden:b.hidden,parent:b.parentElement.tagName,h:Math.round(r.height),bottom:Math.round(innerHeight-r.bottom),done:b.style.getPropertyValue('--pip-done'),busy:b.classList.contains('busy'),failed:b.classList.contains('failed'),text:b.querySelector('span').textContent,textBottom:Math.round(innerHeight-b.querySelector('span').getBoundingClientRect().bottom)};})()`);
  let x = await ex(); assert.ok(x, 'the export bar exists'); assert.equal(x.hidden, true); assert.equal(x.parent, 'BODY', 'it belongs to the window, not only to PiP');
  win.webContents.send('replay:progress', { view: 'pip', stage: 'encode', ratio: .42, at: Date.now() }); await delay(300); x = await ex();
  assert.equal(x.hidden, false); assert.equal(x.h, 3); assert.equal(x.bottom, 0); assert.equal(x.done, '42.0%'); assert.equal(x.busy, false);
  assert.equal(x.text, 'Exporting Pine PiP video - 42% - encoding'); assert.ok(x.textBottom >= 4 && x.textBottom < 40, 'the words sit just over the bar: ' + x.textBottom);
  await shot('5-export-bar');
  win.webContents.send('replay:progress', { view: 'app', audio: true, stage: 'save', ratio: .93, at: Date.now() }); await delay(300); x = await ex();
  assert.equal(x.text, 'Exporting Pine app broadcast mix - 93% - saving');
  win.webContents.send('replay:progress', { view: 'tablet', stage: 'encode', ratio: null, at: Date.now() }); await delay(300); x = await ex();
  assert.equal(x.busy, true, 'no clock to read: the bar sweeps'); assert.equal(x.text, 'Exporting PineTab recording... - encoding');
  win.webContents.send('replay:progress', { view: 'pip', stage: 'done', ratio: 1, seconds: 60, at: Date.now() }); await delay(300); x = await ex();
  assert.equal(x.text, 'Saved Pine PiP video - 60 s'); assert.equal(x.done, '100%'); assert.equal(x.busy, false);
  win.webContents.send('replay:progress', { view: 'app', stage: 'failed', ratio: null, detail: 'no ffmpeg', at: Date.now() }); await delay(300); x = await ex();
  assert.equal(x.text, 'Pine app video export failed: no ffmpeg'); assert.equal(x.failed, true);

  /* ---- 6. out of PiP: the bar is for the app too, the playbar is not ---- */
  key(); for (let n = 0; n < 60 && win.__pinePip; n++) await delay(50);
  await delay(2300);
  assert.equal(await page(`document.body.classList.contains('pine-pip')`), false);
  assert.equal(await inFrame('document.documentElement.classList.contains("pine-pip")'), false, 'the page is back to its full layout');
  win.webContents.send('replay:progress', { view: 'app', stage: 'encode', ratio: .5, at: Date.now() }); await delay(300); x = await ex();
  assert.equal(x.hidden, false, '[pip-export-bar] the full app shows its exports too'); assert.equal(x.text, 'Exporting Pine app video - 50% - encoding');
  await shot('6-app-export-bar');
  win.webContents.send('replay:progress', { view: 'app', stage: 'done', ratio: 1, seconds: 30, at: Date.now() });
  assert.deepEqual(errors, [], 'no errors from the PiP scripts');

  Menu.buildFromTemplate = buildMenu; clearTimeout(failTimer);
  win.destroy(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  console.log('PinePiP widgets: the panel after an iframe, the art fallback and art-only player, free widgets, the playback bar and the export bar passed.');
  setImmediate(() => app.quit());
}).catch(error => { console.error(error); clearTimeout(failTimer); try { server?.close(); } catch (_) {} app.exit(1); });
