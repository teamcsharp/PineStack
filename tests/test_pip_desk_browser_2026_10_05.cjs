/* [pip-shift] [pip-music] [pip-update] The three PiP changes, in a real (hidden, offscreen) shell window.
 *
 * Run with Electron, on local disk:   electron tests/test_pip_desk_browser_2026_10_05.cjs [SHOT_DIR]
 * Isolated configuration and a local fixture station; never touches the live backend.
 * With SHOT_DIR the frames of the change and the player are saved there as PNG.
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
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'pine-pip-desk-'));
const shots = process.argv.find((arg, i) => i > 1 && !arg.startsWith('-') && !arg.endsWith('.cjs')) || '';
if (shots) fs.mkdirSync(shots, { recursive: true });
app.setPath('userData', temp);
app.on('window-all-closed', () => {});
app.commandLine.appendSwitch('use-angle', 'swiftshader');
app.commandLine.appendSwitch('enable-unsafe-swiftshader');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFklEQVR42mP8z8Dwn4EIwDiqkL4KAbgWCAH3Bq0cAAAAAElFTkSuQmCC', 'base64');

let win, server, cfg = {}, posts = [], rebuilt = 0;
let owed = { owed: false, relaunch: [], reload: [], stale: false };
const native = require('../desktop/pip-window.cjs');
const manager = native.install({ ipcMain, getWindow: () => win, readConfig: () => cfg, writeConfig: next => (cfg = { ...cfg, ...next }),
  updateOwed: () => owed, rebuild: () => { rebuilt++; return { ok: true }; } });
const failTimer = setTimeout(() => { console.error('PiP desk test timed out'); app.exit(1); }, 200000);
const shot = async name => { if (shots && win && !win.isDestroyed()) fs.writeFileSync(path.join(shots, name + '.png'), (await win.webContents.capturePage()).toPNG()); };
const page = code => win.webContents.executeJavaScript(code).catch(error => { console.error('the page script failed: ' + String(code).slice(0, 240)); throw error; });
const key = () => win.webContents.emit('before-input-event', { preventDefault() {} }, { type: 'keyDown', key: 'P', control: true, shift: true });

app.whenReady().then(async () => {
  let menuTemplate = null; const buildMenu = Menu.buildFromTemplate;
  Menu.buildFromTemplate = template => { menuTemplate = template; return { popup(options) { setTimeout(() => options.callback && options.callback(), 0); } }; };

  /* the preferences the player needs, before any window */
  const defaults = native.preferences(null);
  assert.deepEqual(defaults.musicPosition, { x: .03, y: .6 }); assert.equal(defaults.musicExpanded, false);
  assert.deepEqual(native.preferences({ musicPosition: { x: 7, y: -3 }, musicExpanded: 'yes' }).musicPosition, { x: 1, y: 0 });
  assert.equal(native.preferences({ musicExpanded: true }).musicExpanded, true);

  server = http.createServer((req, res) => {
    if (req.url.startsWith('/art')) { res.setHeader('Content-Type', 'image/png'); res.end(PNG); return; }
    if (req.url === '/vendor/three.min.js') { res.setHeader('Content-Type', 'application/javascript'); res.end(fs.readFileSync(path.join(desktop, 'vendor/three.min.js'))); return; }
    if (req.url.startsWith('/api/')) { res.setHeader('Content-Type', 'application/json'); res.end('{}'); return; }
    res.setHeader('Content-Type', 'text/html');
    res.end('<html><body style="margin:0;background:#123;color:#9ab;font:14px system-ui"><h1 style="margin:20px">the station panel</h1></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = 'http://127.0.0.1:' + server.address().port;
  cfg = { baseUrl: base, pip: { widgets: { dialogue: true, music: true }, bounds: { x: 60, y: 50, width: 520, height: 300 } } };
  ipcMain.handle('config:read', () => cfg);
  ipcMain.handle('replay:hold', (_e, seconds) => seconds);
  ipcMain.handle('agent:get', (_e, route) => route.startsWith('/api/voices') ? [] : ({}));
  ipcMain.handle('agent:post', (_e, route, body) => { posts.push({ route, body }); return { ok: true, title: 'Reset', artist: 'Mute Math' }; });
  ipcMain.handle('camera:where', () => ({ ok: false }));
  ipcMain.handle('camera:pip', () => ({ ok: true }));

  const resource = name => pathToFileURL(path.join(desktop, 'renderer', name)).href;
  const file = path.join(temp, 'fixture.html');
  fs.writeFileSync(file, `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="${resource('pineicons.css')}"><link rel="stylesheet" href="${resource('pine-pip.css')}"></head><body style="margin:0;background:#101419;color:#dfe7ee;font:14px system-ui">
    <input id="appVolume" type="range" value="35" oninput="window.testVolume=this.value"><aside id="pineViewRail"></aside>
    <main><h1 style="margin:40px">THE FULL APP</h1><p style="margin:40px;max-width:60ch">Every view, rail and drawer of the desk stands here while the window is large.</p>
    <section id="control"><webview id="controlFrame" webpreferences="backgroundThrottling=no" src="${base}" style="width:100%;height:500px"></webview></section></main>
    <audio id="desktopRadioPlayer"></audio>
    <script>window.pineThreeUrl=()=>${JSON.stringify(base + '/vendor/three.min.js')};window.desktopMusicUrl=u=>u;window.PineStationFeed={refreshed:0,refresh(){this.refreshed++;},subscribe(fn){window.receivePip=fn;return ()=>window.receivePip=null}};</script>
    <script src="${resource('pine-icons.js')}"></script><script src="${resource('pine-logo.js')}"></script><script src="${resource('pine-vcr.js')}"></script><script src="${resource('system3-message-tile.js')}"></script>
    <script src="${resource('pine-pip-shift.js')}"></script><script src="${resource('pine-pip.js')}"></script></body></html>`);
  win = new BrowserWindow({ show: false, frame: false, x: 40, y: 40, width: 1100, height: 760, minWidth: 520, minHeight: 420,
    webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const errors = [];
  win.webContents.on('console-message', event => { if (event.level === 'error' && !/favicon|ERR_|deprecated|Autofill/i.test(event.message)) errors.push(event.message + ' @' + event.lineNumber); });
  await win.loadFile(file); await delay(1200);
  assert.equal(await page('typeof PinePipShift.begin + typeof PinePip.enter'), 'functionfunction');
  assert.equal(await page('PinePipShift.warm()'), true, 'three.js comes from the app folder');
  const full = win.getBounds();

  /* ---- 1. the announced change: covered FIRST, the window moves SECOND ---- */
  win.isVisible = () => true;                         /* this window is hidden; stand in for one that is shown */
  const log = []; const mark = what => log.push([what, Date.now()]);
  const setBounds = win.setBounds.bind(win); win.setBounds = (...args) => { mark('bounds'); return setBounds(...args); };
  ipcMain.on('pip:shift-heard', () => mark('heard')); ipcMain.on('pip:shift-covered', () => mark('covered'));
  const unmoved = () => { if (!log.some(row => row[0] === 'covered')) assert.deepEqual(win.getBounds(), full, 'the window does not move while the page is still covering itself'); };
  mark('asked'); key();
  await delay(170); unmoved();
  const early = await page(`({cls:document.getElementById('pinePipShift').className,parent:document.getElementById('pinePipShift').parentElement.tagName,phase:PinePipShift.phase(),active:document.body.classList.contains('pine-pip'),canvas:!!document.querySelector('#pinePipShift canvas')})`);
  assert.equal(early.parent, 'HTML', 'the sheet is beside <body>, so neither layout can hide it');
  assert.match(early.cls, /\bon\b/); assert.equal(early.phase, 'gather'); assert.equal(early.active, false);
  assert.equal(early.canvas, true, 'the particles are on the sheet');
  const logoNow = await page(`(()=>{const m=document.querySelector('#pinePipShift .pip-shift-logo'),r=m.getBoundingClientRect();return {src:m.src.startsWith('data:image/png'),shown:Number(m.style.opacity)>0,w:Math.round(r.width),inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,over:m.compareDocumentPosition(document.querySelector('#pinePipShift canvas'))===Node.DOCUMENT_POSITION_PRECEDING};})()`);
  assert.deepEqual({ src: logoNow.src, shown: logoNow.shown, inside: logoNow.inside, over: logoNow.over }, { src: true, shown: true, inside: true, over: true }, 'the Pine Box mark is on the sheet, over the particles: ' + JSON.stringify(logoNow));
  unmoved(); await shot('1-enter-gather-a'); unmoved();
  await delay(150); unmoved(); await shot('1-enter-gather-b'); unmoved();
  for (let n = 0; n < 40 && !win.__pinePip; n++) await delay(50);
  assert.equal(win.__pinePip, true, 'PiP is entered');
  const order = log.map(row => row[0]).join(' ');
  assert.match(order, /^asked heard covered bounds/, 'heard, covered, and only then the window: ' + order);
  const took = Object.fromEntries(log.map(([what, at]) => [what, at - log[0][1]]));
  assert.ok(took.covered >= 450 && took.covered <= 1200, 'covered after the fly-in, not before: ' + JSON.stringify(took));
  assert.equal(win.getContentBounds().width, 520); assert.equal(win.getContentBounds().height, 300);
  await delay(60); await shot('2-enter-dark');
  await delay(260); await shot('2-enter-burst-a');
  await delay(220); await shot('2-enter-burst-b');
  await delay(1500);
  const settled = await page(`({phase:PinePipShift.phase(),hidden:document.getElementById('pinePipShift').hidden,canvas:!!document.querySelector('#pinePipShift canvas'),active:document.body.classList.contains('pine-pip')})`);
  assert.deepEqual(settled, { phase: 'idle', hidden: true, canvas: false, active: true }, 'the sheet is gone and its WebGL context is given back');

  /* ---- 2. the mini player ---- */
  await page(`receivePip({station:{now:{id:'track-1',title:'Le Mal Du Pays',artist:'Eric Christian',album:'Scenes from Paris',seconds:223,art:${JSON.stringify(base + '/art.png')}},playing:true,paused:false,elapsed:19,remaining:204,
    upcoming:[{title:'Reset',artist:'Mute Math',seconds:325.8},{title:'Typical',artist:'Mute Math',seconds:254}]},rows:[],now:null})`);
  await delay(400); await shot('3-music-compact');
  const read = () => page(`(()=>{const b=document.querySelector('.pip-music'),r=b.getBoundingClientRect(),v=s=>{const n=b.querySelector(s);return !!n&&getComputedStyle(n).display!=='none'&&n.getBoundingClientRect().width>0;};
    return {parent:b.parentElement.id,position:getComputedStyle(b).position,x:Math.round(r.left),y:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height),inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
      expanded:b.classList.contains('expanded'),info:b.querySelector('.pip-music-info').textContent,infoShown:v('.pip-music-info'),art:v('.pip-music-art'),votes:v('.pip-music-up'),queue:v('.pip-music-queue'),left:v('.pip-music-left'),
      at:b.querySelector('.pip-music-at').textContent,remaining:b.querySelector('.pip-music-left').textContent,bar:parseFloat(b.querySelector('.pip-music-bar i').style.width),
      icons:b.querySelectorAll('button svg').length,buttons:b.querySelectorAll('button').length,untitled:[...b.querySelectorAll('button')].filter(n=>!n.title||!n.getAttribute('aria-label')).length,
      play:b.querySelector('.pip-music-play').dataset.icon,ascii:!/[^\\x20-\\x7e\\u00b7\\u2014\\u2019]/.test(b.textContent+b.title)};})()`);
  const compact = await read();
  assert.equal(compact.parent, 'pinePipWidgets'); assert.equal(compact.position, 'absolute'); assert.equal(compact.inside, true);
  assert.equal(compact.expanded, false); assert.equal(compact.infoShown, false); assert.equal(compact.art, true); assert.equal(compact.votes, false); assert.equal(compact.queue, true);
  assert.ok(compact.h <= 76 && compact.w >= 280, 'a bar, not a block: ' + JSON.stringify(compact));
  assert.match(compact.info, /Le Mal Du Pays.*Eric Christian.*Scenes from Paris/); assert.match(compact.at, /^0:(19|2\d)$/); assert.ok(compact.bar > 7 && compact.bar < 12);
  assert.equal(compact.icons, compact.buttons, 'every control is an icon'); assert.equal(compact.untitled, 0, 'and every one is named'); assert.equal(compact.play, 'c:pause--filled');
  assert.equal(compact.ascii, true, 'no mis-encoded glyphs');
  assert.equal(await page(`[...document.querySelectorAll('#pinePipWidgets .pip-grip, #pinePipWidgets header, .pip-dice output')].every(n=>!/[\\u00c2\\u00e2]/.test(n.textContent))`), true, 'the other widgets read cleanly too');

  /* drag it by its body */
  const grab = await page(`(()=>{const r=document.querySelector('.pip-music .pip-music-seek').getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()`);
  win.webContents.sendInputEvent({ type: 'mouseDown', x: grab.x, y: grab.y, button: 'left', clickCount: 1 });
  for (let step = 1; step <= 6; step++) { win.webContents.sendInputEvent({ type: 'mouseMove', x: grab.x + step * 20, y: grab.y + step * 10, button: 'left', modifiers: ['leftButtonDown'] }); await delay(30); }
  win.webContents.sendInputEvent({ type: 'mouseUp', x: grab.x + 120, y: grab.y + 60, button: 'left', clickCount: 1 });
  await delay(350);
  const moved = await read();
  assert.ok(Math.abs(moved.x - (compact.x + 120)) <= 3 && Math.abs(moved.y - (compact.y + 60)) <= 3, 'dragged 120 by 60: ' + JSON.stringify([compact.x, compact.y, moved.x, moved.y]));
  assert.ok(Math.abs(cfg.pip.musicPosition.x - moved.x / 520) < .01 && Math.abs(cfg.pip.musicPosition.y - moved.y / 300) < .01, 'and the place is kept: ' + JSON.stringify(cfg.pip.musicPosition));
  assert.equal(win.__pinePip, true, 'dragging the player does not leave PiP');
  await shot('3-music-moved');

  /* open it out, and fold it back */
  await page(`document.querySelector('.pip-music-size').click()`); await delay(350); await shot('4-music-expanded');
  const big = await read();
  assert.equal(big.expanded, true); assert.equal(cfg.pip.musicExpanded, true); assert.equal(big.infoShown, true); assert.equal(big.votes, true); assert.equal(big.queue, false); assert.equal(big.left, true);
  assert.equal(big.inside, true, 'still inside the small window: ' + JSON.stringify(big)); assert.ok(big.h > compact.h + 60); assert.match(big.remaining, /^-3:\d\d$/);
  await page(`document.querySelector('[aria-label="Play this track more"]').click()`); await delay(120);
  assert.deepEqual(posts.at(-1), { route: '/api/music/vote', body: { id: 'track-1', vote: 1 } });
  await page(`document.querySelector('.pip-music-skip').click()`); await delay(120);
  assert.deepEqual(posts.at(-1), { route: '/api/dj/next', body: {} });
  await page(`document.querySelector('.pip-music-back').click()`); await delay(120);
  assert.deepEqual(posts.at(-1), { route: '/api/dj/prev', body: {} });
  await page(`document.querySelector('.pip-music-size').click()`); await delay(300);
  assert.equal((await read()).expanded, false); assert.equal(cfg.pip.musicExpanded, false);
  await page(`document.querySelector('.pip-music-queue').click()`); await delay(200); await shot('5-music-up-next');
  assert.equal((await read()).inside, true, 'the list opens inside the window, wherever the player was put');
  assert.match(await page(`document.querySelector('.pip-music-pop').textContent`), /Up next.*Reset.*Mute Math.*5:26.*Typical/);
  assert.equal(await page(`!!document.querySelector('.pip-music-pop .pip-music-pop-x')`), true, 'the list has its own X');
  await page(`document.querySelector('.pip-music-pop-x').click()`); await delay(100);
  assert.equal(await page(`document.querySelector('.pip-music-pop').hidden`), true);
  await page(`document.querySelector('.pip-music-vol').click()`); await delay(150);
  await page(`(()=>{const s=document.querySelector('.pip-music-pop input[type=range]');s.value=62;s.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  assert.equal(await page('window.testVolume'), '62', 'the volume is the application volume');
  await page(`document.querySelector('.pip-music-find').click()`); await delay(150);
  await page(`(()=>{const f=document.querySelector('.pip-music-pop form');f.querySelector('input').value='reset';f.requestSubmit();})()`); await delay(250);
  assert.deepEqual(posts.at(-1), { route: '/api/dj/request', body: { q: 'reset' } }, 'asking queues a record, it does not cut one');
  await page(`document.querySelector('.pip-music').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}))`); await delay(250);
  assert.equal(win.__pinePip, true, 'a double click on the player is not a double click on the picture');

  /* ---- 3. the menu offers the rebuild when the app is out of date, and only then ---- */
  await page('pineDesktop.pipMenu({})'); await delay(120);
  assert.equal(menuTemplate[0].label, 'Resolve playback + restore DJs', 'nothing owed, nothing offered');
  owed = { owed: true, relaunch: ['pip-window.cjs', 'main.js'], reload: ['pine-pip.js'], stale: true };
  await page('pineDesktop.pipMenu({})'); await delay(120);
  assert.equal(menuTemplate[0].label, 'Update and rebuild Pine (3 newer files)'); assert.equal(menuTemplate[1].type, 'separator');
  assert.equal(menuTemplate[2].label, 'Resolve playback + restore DJs');
  menuTemplate[0].click(); await delay(50); assert.equal(rebuilt, 1, 'the entry runs the rebuild');
  owed = { owed: true, relaunch: [], reload: [], stale: true };
  await page('pineDesktop.pipMenu({})'); await delay(120);
  assert.equal(menuTemplate[0].label, 'Update and rebuild Pine (this app is older than its source)');
  owed = { owed: false, relaunch: [], reload: [], stale: false };

  /* ---- 4. back to the app, the same way ---- */
  log.length = 0; mark('asked'); key();
  await delay(260); await shot('6-exit-gather');
  assert.equal(win.__pinePip, true); assert.equal(win.getContentBounds().width, 520, 'still the small window while it covers');
  for (let n = 0; n < 40 && win.__pinePip; n++) await delay(50);
  assert.match(log.map(row => row[0]).join(' '), /^asked heard covered bounds/);
  assert.deepEqual(win.getBounds(), full, 'the full window is back where it was');
  await delay(330); await shot('7-exit-burst');
  await delay(1500); await shot('8-app-again');
  assert.equal(await page(`PinePipShift.phase()+':'+document.body.classList.contains('pine-pip')`), 'idle:false');

  /* ---- 5. a change nobody announced (a shell from before this) is covered the moment it is known ---- */
  win.isVisible = () => false;
  key(); assert.equal(win.__pinePip, true, 'a window nobody can see changes at once, as it always did');
  await delay(60);
  const late = await page(`({cls:document.getElementById('pinePipShift').className,hidden:document.getElementById('pinePipShift').hidden,phase:PinePipShift.phase()})`);
  assert.match(late.cls, /\bon\b/); assert.equal(late.hidden, false); assert.notEqual(late.phase, 'idle');
  await delay(2200);
  assert.equal(await page('PinePipShift.phase()'), 'idle');
  key(); await delay(2200); assert.equal(win.__pinePip, false);

  /* ---- 6. a sheet nobody lifts lifts itself ---- */
  const hold = await page('PinePipShift.timings.hold');
  assert.ok(hold > 0 && hold <= 5000);
  await page(`PinePipShift.begin('pip',{instant:true})`); await delay(hold + 1400);
  assert.equal(await page('PinePipShift.phase()'), 'idle', 'covered and never told to reveal: it reveals');

  assert.deepEqual(errors, [], 'no errors in the page');

  /* ---- 7. the app's own page: index.html and every script it loads, with the sheet among them ---- */
  win.destroy();
  for (const channel of new Set([...fs.readFileSync(path.join(desktop, 'preload.js'), 'utf8').matchAll(/ipcRenderer\.invoke\(["']([^"']+)/g)].map(m => m[1]))) {
    try { ipcMain.handle(channel, () => channel === 'backend:log' ? [] : ({ ok: true, rows: [], lines: [], items: [], hosts: [] })); } catch (_) { /* already answered above */ }
  }
  cfg = { baseUrl: base, pip: { widgets: { dialogue: true, music: true }, bounds: { x: 60, y: 50, width: 520, height: 300 } } };
  win = new BrowserWindow({ show: false, frame: false, x: 40, y: 40, width: 1100, height: 760, minWidth: 520, minHeight: 420,
    webPreferences: { offscreen: true, webviewTag: true, sandbox: false, preload: path.join(desktop, 'preload.js'), backgroundThrottling: false } });
  manager.attach(win);
  const shellErrors = [];
  win.webContents.on('console-message', event => { if (event.level === 'error' && /pine-pip/.test(String(event.sourceId))) shellErrors.push(event.message + ' @' + String(event.sourceId).split('/').pop() + ':' + event.lineNumber); });
  await win.loadFile(path.join(desktop, 'renderer', 'index.html')); await delay(2500);
  const shell = await page(`(async()=>({sheet:typeof PinePipShift?.begin,pip:typeof PinePip?.enter,order:[...document.scripts].map(s=>s.src.split('/').pop()).filter(n=>/^pine-pip/.test(n)),three:await PinePipShift.warm(),local:[...document.scripts].some(s=>s.src.endsWith('/vendor/three.min.js')&&s.src.startsWith('file:'))}))()`);
  assert.equal(shell.sheet + ':' + shell.pip, 'function:function', 'the real page has the sheet and PiP');
  assert.ok(shell.order.indexOf('pine-pip-shift.js') >= 0 && shell.order.indexOf('pine-pip-shift.js') < shell.order.indexOf('pine-pip.js'), 'loaded in order: ' + shell.order.join(' '));
  assert.equal(shell.three, true); assert.equal(shell.local, true, 'three.js came from the app folder, not from the station');
  win.isVisible = () => true;
  key(); for (let n = 0; n < 60 && !win.__pinePip; n++) await delay(50);
  assert.equal(win.__pinePip, true, 'the real page covers itself and lets the window go');
  await delay(2300);
  const inPip = await page(`({active:document.body.classList.contains('pine-pip'),phase:PinePipShift.phase(),player:document.querySelector('.pip-music')?.parentElement.id,playerShown:!document.querySelector('.pip-music').hidden,width:innerWidth,height:innerHeight})`);
  assert.deepEqual(inPip, { active: true, phase: 'idle', player: 'pinePipWidgets', playerShown: true, width: 520, height: 300 });
  await shot('9-real-shell-pip');
  key(); for (let n = 0; n < 60 && win.__pinePip; n++) await delay(50);
  await delay(2300);
  assert.equal(await page(`PinePipShift.phase()+':'+document.body.classList.contains('pine-pip')`), 'idle:false');
  assert.deepEqual(shellErrors, [], 'no errors from the PiP scripts in the real page');
  Menu.buildFromTemplate = buildMenu; clearTimeout(failTimer);
  console.log('timings: ' + JSON.stringify(took));
  console.log('player: compact ' + JSON.stringify([compact.w, compact.h]) + ' expanded ' + JSON.stringify([big.w, big.h]));
  win.destroy(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  console.log('PinePiP desk: the covered change, the placed and opened mini player, the rebuild entry, and the real page passed.');
  setImmediate(() => app.quit());
}).catch(error => { console.error(error); clearTimeout(failTimer); try { server?.close(); } catch (_) {} app.exit(1); });
