'use strict';
/* [pip-shift] [pip-music] [pip-update] The three PiP changes of 2026-10-05, without a window.
 *
 *   the shell   - the page is told and covered BEFORE the window moves, and no page can hold the window;
 *                 the player's place and size are preferences; the menu offers the rebuild when one is owed
 *   the sheet   - covers, goes dark, lifts, and lifts by itself if nobody lifts it
 *   the page    - one road in and out of PiP; the player is free; the file reads cleanly
 *
 * Run on local disk, never from the share:  node --test tests/test_pip_desk_2026_10_05.cjs
 * The same changes in a real (hidden) shell window: tests/test_pip_desk_browser_2026_10_05.cjs, with Electron.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(ROOT, name), 'utf8');
const lf = text => text.replace(/\r\n/g, '\n');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

/* ------------------------------------------------------------------ the shell: pip-window.cjs */
function shell(options = {}) {
  const handlers = new Map(), listeners = new Map(), sent = [], calls = [];
  let template = null, cfg = options.cfg || { pip: {} };
  const webContents = { send: (...args) => { sent.push(args); calls.push('send:' + args[0]); }, on() {} };
  const bounds = { x: 100, y: 100, width: 1200, height: 800 };
  const window = {
    __pinePip: false, webContents, visible: options.visible !== false, destroyed: false,
    isDestroyed() { return this.destroyed; }, isVisible() { return this.visible; }, isMinimized() { return false; },
    getBounds: () => ({ ...bounds }), getContentBounds: () => ({ ...bounds }), getNormalBounds: () => ({ ...bounds }),
    setBounds(next) { calls.push('bounds'); Object.assign(bounds, next); },
    isMaximized: () => false, isFullScreen: () => false, isAlwaysOnTop: () => false, isMenuBarVisible: () => false, getTitle: () => 'Pine Box',
    isMaximizable: () => true, setMaximizable() {}, setMenuBarVisibility() {}, setMinimumSize() {}, setAspectRatio() {}, setAlwaysOnTop() {}, setTitle() {},
    setFullScreen() {}, unmaximize() {}, maximize() {}, on() {},
  };
  const area = { x: 0, y: 0, width: 1920, height: 1080 };
  const electron = { screen: { getDisplayNearestPoint: () => ({ workArea: area, bounds: area }), getDisplayMatching: () => ({ workArea: area, bounds: area }) },
    Menu: { buildFromTemplate(value) { template = value; return { popup() {} }; } } };
  const ipcMain = { handle: (channel, fn) => handlers.set(channel, fn),
    on: (channel, fn) => { listeners.set(channel, (listeners.get(channel) || []).concat(fn)); },
    removeListener: (channel, fn) => { listeners.set(channel, (listeners.get(channel) || []).filter(item => item !== fn)); } };
  if (options.noListen) { delete ipcMain.on; delete ipcMain.removeListener; }
  const module = { exports: {} };
  vm.runInNewContext(read('desktop/pip-window.cjs'), { module, exports: module.exports, require: name => { assert.equal(name, 'electron'); return electron; }, setTimeout, clearTimeout, console });
  module.exports.install({ ipcMain, getWindow: () => window, readConfig: () => cfg, writeConfig: next => { cfg = { ...cfg, ...next }; },
    updateOwed: options.updateOwed, rebuild: options.rebuild });
  const event = { sender: webContents };
  return { native: module.exports, window, sent, calls, bounds, cfg: () => cfg, template: () => template,
    invoke: (name, args) => handlers.get('pip:' + name)(event, args),
    emit: (channel, value, sender = webContents) => (listeners.get(channel) || []).slice().forEach(fn => fn({ sender }, value)),
    listening: channel => (listeners.get(channel) || []).length };
}
const asked = h => h.sent.filter(row => row[0] === 'pip:shift').map(row => row[1]);

test('the page is told first; the window moves only once the page says it is covered', async () => {
  const h = shell();
  const going = h.invoke('enter');
  assert.equal(typeof going.then, 'function');
  const [note] = asked(h);
  assert.equal(note.to, 'pip'); assert.deepEqual(note.from, { x: 100, y: 100, width: 1200, height: 800 });
  assert.ok(note.target.width > 0 && note.target.height > 0, 'it says where the small window will sit');
  h.emit('pip:shift-heard', note.id);
  await delay(320);                                          // well past the "nobody is listening" bound
  assert.equal(h.window.__pinePip, false, 'heard: the window waits for the cover');
  assert.ok(!h.calls.includes('bounds'));
  h.emit('pip:shift-covered', note.id);
  const state = await going;
  assert.equal(state.active, true); assert.equal(h.window.__pinePip, true);
  assert.deepEqual(h.calls.filter(c => c === 'send:pip:shift' || c === 'bounds' || c === 'send:pip:state'), ['send:pip:shift', 'bounds', 'send:pip:state']);
  assert.equal(h.listening('pip:shift-heard') + h.listening('pip:shift-covered'), 0, 'nothing is left listening');
});

test('leaving PiP takes the same road, and says where the full window will be', async () => {
  const h = shell();
  const entering = h.invoke('enter'); h.emit('pip:shift-covered', asked(h)[0].id); await entering;
  const leaving = h.invoke('exit');
  const note = asked(h)[1];
  assert.equal(note.to, 'app'); assert.deepEqual(note.target, { x: 100, y: 100, width: 1200, height: 800 });
  assert.equal(h.window.__pinePip, true, 'still PiP while the page covers');
  h.emit('pip:shift-covered', note.id);
  assert.equal((await leaving).active, false);
  assert.deepEqual(h.bounds, { x: 100, y: 100, width: 1200, height: 800 });
});

test('no page can hold the window: nobody listening, a wrong sender, or one that never covers', async () => {
  const quiet = shell(); const began = Date.now();
  await quiet.invoke('enter');
  assert.equal(quiet.window.__pinePip, true);
  const waited = Date.now() - began;
  assert.ok(waited >= 150 && waited < 900, 'changed after the short bound, not the long one: ' + waited + ' ms');

  const stranger = shell(); const going = stranger.invoke('enter'); const note = asked(stranger)[0];
  stranger.emit('pip:shift-covered', note.id, { other: true });           // not this window's page
  stranger.emit('pip:shift-covered', note.id + 99);                       // not this change
  await delay(60); assert.equal(stranger.window.__pinePip, false);
  await going; assert.equal(stranger.window.__pinePip, true);

  const stuck = shell(); const slow = Date.now(); const pending = stuck.invoke('enter');
  stuck.emit('pip:shift-heard', asked(stuck)[0].id);                      // it heard, and then never answers
  await pending;
  const long = Date.now() - slow;
  assert.ok(long >= 1200 && long < 2600, 'the long bound: ' + long + ' ms');
  assert.equal(stuck.window.__pinePip, true);
});

test('a second press joins the change in flight; a window nobody can see changes at once', async () => {
  const h = shell();
  const first = h.invoke('enter'), second = h.invoke('enter'), third = h.invoke('exit');
  assert.equal(asked(h).length, 1, 'one change, asked once');
  h.emit('pip:shift-covered', asked(h)[0].id);
  await Promise.all([first, second, third]);
  assert.equal(h.window.__pinePip, true);

  const hidden = shell({ visible: false });
  assert.equal(hidden.invoke('enter').active, true, 'the answer is the state itself, not a promise');
  assert.equal(hidden.window.__pinePip, true); assert.equal(asked(hidden).length, 0);
  assert.equal(hidden.invoke('exit').active, false);

  const old = shell({ noListen: true });                                   // an ipc that cannot listen
  assert.equal(old.invoke('enter').active, true);

  const gone = shell(); const dying = gone.invoke('enter');
  gone.window.destroyed = true; gone.emit('pip:shift-covered', asked(gone)[0].id);
  await dying; assert.equal(gone.window.__pinePip, false, 'a destroyed window is left alone');
});

test("the player's place and size are preferences, kept across an update of anything else", () => {
  const h = shell();
  assert.deepEqual({ ...h.native.preferences(null).musicPosition }, { x: .03, y: .6 });
  assert.equal(h.native.preferences(null).musicExpanded, false);
  assert.deepEqual({ ...h.native.preferences({ musicPosition: { x: 4, y: -1 } }).musicPosition }, { x: 1, y: 0 });
  assert.deepEqual({ ...h.native.preferences({ musicPosition: { x: 'left' } }).musicPosition }, { x: .03, y: .6 });
  assert.equal(h.native.preferences({ musicExpanded: 1 }).musicExpanded, false);
  h.invoke('update', { musicPosition: { x: .5, y: .25 }, musicExpanded: true });
  h.invoke('update', { theme: 'plum' });
  h.invoke('update', { musicPosition: { y: .75 } });
  const pip = h.cfg().pip;
  assert.deepEqual({ ...pip.musicPosition }, { x: .5, y: .75 }); assert.equal(pip.musicExpanded, true); assert.equal(pip.theme, 'plum');
});

test('the menu offers the rebuild first when one is owed, and never otherwise', () => {
  let rebuilt = 0;
  // the menu is modal: a second one cannot be built until the first closes, so each case gets its own shell
  const one = (state, withRebuild = true) => {
    const s = shell({ updateOwed: typeof state === 'function' ? state : () => state, rebuild: withRebuild ? () => { rebuilt++; } : undefined });
    s.window.__pinePip = true; s.invoke('menu', {}); return s.template();
  };
  assert.equal(one({ owed: false, relaunch: [], reload: [], stale: false })[0].label, 'Resolve playback + restore DJs', 'nothing owed, nothing offered');
  let t = one({ owed: true, relaunch: ['main.js', 'pip-window.cjs'], reload: ['pine-pip.js', 'main.js'], stale: true });
  assert.equal(t[0].label, 'Update and rebuild Pine (3 newer files)'); assert.equal(t[1].type, 'separator');
  assert.equal(t[2].label, 'Resolve playback + restore DJs');
  t[0].click();
  t = one({ owed: true, relaunch: ['preload.js'], reload: [], stale: false });
  assert.equal(t[0].label, 'Update and rebuild Pine (1 newer file)');
  t = one({ owed: true, relaunch: [], reload: [], stale: true });
  assert.equal(t[0].label, 'Update and rebuild Pine (this app is older than its source)');
  assert.equal(one({ owed: true, relaunch: ['main.js'] }, false)[0].label, 'Resolve playback + restore DJs', 'no rebuild to offer, none offered');
  assert.equal(one(() => { throw new Error('the watcher fell over'); })[0].label, 'Resolve playback + restore DJs', 'a broken meter is not an offer');
  return delay(20).then(() => assert.equal(rebuilt, 1));
});

test('the shell hands the menu what its watcher already knows', () => {
  const main = read('desktop/main.js');
  assert.match(main, /const hotOwed = new Set\(\);/);
  assert.match(main, /if \(hotSelf\.has\(key\) && hotSelf\.get\(key\) !== stamp\) \{ hotOwed\.add\(name\); hotSayRelaunch\(name\); \}/);
  assert.match(main, /\.then\(got=>\{desktopBuildLast=got;return got;\}\)/);
  assert.match(main, /updateOwed: \(\) => pineUpdateOwed\(\), rebuild: \(\) => reconstituteDesktop\(\)/);
  const body = main.slice(main.indexOf('function pineUpdateOwed() {'), main.indexOf('function hotSourceDir()'));
  const hotOwed = new Set(), hotPending = new Set(); let desktopBuildLast = null;
  const run = () => vm.runInNewContext(body + '; pineUpdateOwed()', { hotOwed, hotPending, desktopBuildLast, Array });
  assert.ok(body.length > 100 && body.length < 600, 'the function is found whole');
  assert.equal(run().owed, false);
  hotPending.add('pine-pip.js'); assert.equal(run().owed, true); assert.deepEqual(Array.from(run().reload), ['pine-pip.js']);
  hotPending.clear(); hotOwed.add('main.js'); assert.deepEqual(Array.from(run().relaunch), ['main.js']);
  hotOwed.clear(); desktopBuildLast = { stale: true }; assert.equal(run().owed, true); assert.equal(run().stale, true);
});

test('the bridge lets the page hear the shell and answer it', () => {
  const preload = read('desktop/preload.js');
  assert.match(preload, /onPipShift: \(callback\) => ipcRenderer\.on\('pip:shift', \(_event, value\) => callback\(value\)\),/);
  assert.match(preload, /pipShiftHeard: \(id\) => ipcRenderer\.send\('pip:shift-heard', id\),/);
  assert.match(preload, /pipShiftCovered: \(id\) => ipcRenderer\.send\('pip:shift-covered', id\),/);
});

/* ------------------------------------------------------------------ the sheet: pine-pip-shift.js */
function sheet({ still = true } = {}) {
  const made = [];
  const node = tag => { const set = new Set(), style = {}; const n = { tagName: String(tag).toUpperCase(), children: [], hidden: false, attrs: {},
    classList: { add: (...c) => c.forEach(x => set.add(x)), remove: (...c) => c.forEach(x => set.delete(x)), contains: c => set.has(c) },
    style: { setProperty: (k, v) => { style[k] = v; } }, vars: style, setAttribute(k, v) { this.attrs[k] = v; }, appendChild(c) { this.children.push(c); c.parent = this; if (c.tagName === 'SCRIPT') setTimeout(() => c.onerror && c.onerror(), 0); return c; },
    insertBefore(c) { return this.appendChild(c); }, getAttribute(k) { return this.attrs[k]; }, remove() {}, get offsetWidth() { return 100; },
    get className() { return [...set].join(' '); }, set className(v) { set.clear(); String(v).split(/\s+/).filter(Boolean).forEach(x => set.add(x)); } }; made.push(n); return n; };
  const html = node('html'), head = node('head');
  const document = { documentElement: html, head, createElement: node };
  const window = { document, innerWidth: 1200, innerHeight: 800, screenX: 100, screenY: 100, devicePixelRatio: 1,
    performance: { now: () => Date.now() }, matchMedia: () => ({ matches: still }), getComputedStyle: () => ({ getPropertyValue: () => '' }),
    requestAnimationFrame: fn => setTimeout(() => fn(Date.now()), 8), cancelAnimationFrame: id => clearTimeout(id), setTimeout, clearTimeout };
  vm.runInNewContext(read('desktop/renderer/pine-pip-shift.js'), { window, document, setTimeout, clearTimeout, Promise, Math, Date, Number, String, Error, isFinite });
  return { api: window.PinePipShift, html, host: () => html.children.find(n => n.attrs && n.id === 'pinePipShift'), window,
    mark: () => made.find(n => n.tagName === 'IMG' && n.classList.contains('pip-shift-logo')) };
}

test('the sheet covers, goes dark, and lifts once the new layout is in', async () => {
  const s = sheet();
  assert.equal(s.api.phase(), 'idle'); assert.equal(s.api.covering(), false);
  const covered = s.api.begin('pip');
  const host = s.host();
  assert.ok(host, 'the sheet hangs on <html>, beside <body>'); assert.equal(host.parent, s.html);
  assert.equal(host.hidden, false); assert.ok(host.classList.contains('on')); assert.ok(!host.classList.contains('instant'));
  assert.equal(s.api.phase(), 'gather'); assert.equal(s.api.covering(), true);
  assert.equal(await covered, true); assert.equal(s.api.phase(), 'dark');
  const mark = s.mark();
  assert.ok(mark && mark.parent === host, 'the Pine Box mark is on the sheet');
  assert.equal(mark.style.opacity, '1.000', 'and it is what the dark sheet shows while the window changes');
  assert.match(mark.style.transform, /^translate\(5\d\d\.\dpx,3\d\d\.\dpx\)$/, 'in the middle when the shell gave no numbers: ' + mark.style.transform);
  const gone = s.api.landed('pip', Promise.resolve());
  assert.equal(await gone, true);
  assert.equal(s.api.phase(), 'idle'); assert.equal(host.hidden, true); assert.equal(host.className, '');
  assert.equal(mark.style.opacity, '0', 'the mark goes with the sheet');
});

test('a change nobody announced is covered at once, with nothing to fade from', async () => {
  const s = sheet();
  const gone = s.api.landed('app', Promise.resolve());
  const host = s.host();
  assert.ok(host.classList.contains('instant') && host.classList.contains('on')); assert.equal(host.hidden, false);
  assert.equal(s.api.phase(), 'dark');
  assert.equal(await gone, true); assert.equal(s.api.phase(), 'idle');
});

test('a sheet nobody lifts lifts itself; a layout that never settles does not hold it either', async () => {
  const s = sheet();
  s.api.timings.hold = 180;
  assert.equal(await s.api.begin('pip', { instant: true }), true);
  await delay(120); assert.equal(s.api.phase(), 'dark');
  await delay(600); assert.equal(s.api.phase(), 'idle', 'covered and never told to reveal: it reveals');

  const t = sheet();
  await t.api.begin('pip', { instant: true });
  const began = Date.now(); await t.api.landed('pip', new Promise(() => {}));     // the panel never answers
  assert.ok(Date.now() - began < 2600); assert.equal(t.api.phase(), 'idle');
});

test('a second change starts clean, and its times can be read and slowed', async () => {
  const s = sheet();
  const first = s.api.begin('pip'); const second = s.api.begin('app');
  assert.equal(await first, false, 'the first cover was overtaken'); assert.equal(await second, true);
  await s.api.reveal(); assert.equal(s.api.phase(), 'idle');
  for (const key of ['gather', 'burst', 'fadeIn', 'fadeOut', 'quick', 'hold']) assert.ok(s.api.timings[key] > 0, key);
  assert.ok(s.api.timings.gather + s.api.timings.burst <= 1600, 'the whole change stays under about a second and a half');
  assert.ok(s.api.timings.hold <= 5000);
});

/* ------------------------------------------------------------------ the page: pine-pip.js, index.html, the sheet's styles */
test('every way in and out of PiP takes the one road, and the sheet lifts on the new layout', () => {
  const js = lf(read('desktop/renderer/pine-pip.js'));
  assert.equal((js.match(/api\(\)\.pipExit\(\)/g) || []).length, 1, 'pipExit is called in one place');
  assert.equal((js.match(/api\(\)\.pipEnter\(\)/g) || []).length, 1, 'and pipEnter in the same one');
  const road = js.slice(js.indexOf('  async function shiftTo(to) {'), js.indexOf('  function expand() {'));
  assert.match(road, /const sheet = root\.PinePipShift, led = !!sheet && !api\(\)\.onPipShift, before = !!state\?\.active;/);
  assert.ok(road.indexOf('await sheet.begin(to)') < road.indexOf("api().pipEnter() : api().pipExit()"), 'an older shell: cover first, then ask');
  assert.match(road, /finally \{ if \(led && !!state\?\.active === before\) sheet\.reveal\(\); \}/);
  assert.match(js, /if \(was !== undefined && !!was !== !!next\.active\) root\.PinePipShift\?\.landed\(next\.active \? 'pip' : 'app', synced\);/);
  assert.match(js, /api\(\)\.onPipShift\?\.\(note => \{/);
  assert.match(js, /sheet\.begin\(note\?\.to, \{ from: note\?\.from, target: note\?\.target \}\)\.then\(\(\) => api\(\)\.pipShiftCovered\?\.\(id\)\);/);
  for (const use of ["if (e.args[0] === 'expand') expand();", "if (e.data.action === 'expand') expand();", 'state?.active ? expand() : enter(); } });', "exit: () => shiftTo('app'),"]) assert.ok(js.includes(use), use);
  const html = lf(read('desktop/renderer/index.html'));
  assert.ok(html.indexOf('<script src="./pine-pip-shift.js"></script>') > 0);
  assert.ok(html.indexOf('<script src="./pine-pip-shift.js"></script>') < html.indexOf('<script src="./pine-pip.js"></script>'), 'the sheet is loaded before PiP');
});

test('the music player is its own free player, and the file reads cleanly', () => {
  const js = lf(read('desktop/renderer/pine-pip.js'));
  assert.ok(!/[^\x00-\x7f]/.test(js), 'no character outside ASCII: every glyph is an escape');
  assert.ok(!/\\u00c2|\\u00e2\\u20ac|\\u00e2\\u2013/.test(js), 'and none of the escapes is a mis-read byte');
  for (const glyph of ["'\\u283f'", "'\\u2014'", "' \\u00b7 '", "'   \\u2022   '", "' \\u2192 '"]) assert.ok(js.includes(glyph), glyph);
  assert.ok(js.includes("buildMusic();   /* [pip-music]") && !js.includes("grip(music, 'music')"), 'no grip into a dock');
  assert.ok(js.includes("if (!['chat', 'voices', 'roulette', 'messages', 'music', 'rec'].includes(name) && !placedFreely(name))"), 'apply does not dock it');   /* [pip-free] nor any placed widget; [pip-rec] nor the recorder */
  assert.ok(js.includes('placeSlate(); syncMusic(); syncMessages();'));
  assert.ok(js.includes(".pip-camera, .pip-messages, .pip-music')) expand(); });"), 'a double click on the player is not one on the picture');
  assert.ok(js.includes("'voiceStyles','musicPosition','musicExpanded','musicArtOnly','layout']) out[key] = value[key];"), 'its place travels with the shared settings');   /* [pip-free] and every layout */
  const player = js.slice(js.indexOf('  function buildMusic() {'), js.indexOf('  function build() {'));
  for (const [ref, title] of [['c:close--filled', 'Hide the music player'], ['c:maximize', 'Open out to the artwork view'], ['c:caret--right', 'Up next'], ['m:fast_rewind', 'Back to the last record'],
    ['c:play--filled--alt', 'Play / pause this device\\u2019s broadcast'], ['m:fast_forward', 'Skip to the next record'], ['c:thumbs-up', 'Play this track more'],
    ['c:thumbs-down', 'Never play this track again'], ['c:volume--up--filled', 'Volume'], ['c:search', 'Ask for a record']]) {
    assert.ok(player.includes("'" + ref + "', '" + title + "'"), 'a named icon: ' + title);
  }
  assert.ok(player.includes("turn('/api/dj/prev'") && player.includes("turn('/api/dj/next'"));
  assert.ok(player.includes("e.target.closest('button, input, .pip-music-pop')"), 'a control is not a handle');
  assert.ok(player.includes("api().pipUpdate({ musicPosition: musicSpot })"), 'where it is dropped is kept');
  const icons = new Set(Object.keys(JSON.parse(lf(read('desktop/renderer/pine-icons.js')).match(/var ART = (\{.*?\});\n/s)[1])));
  for (const ref of (js.match(/'[cm]:[a-z0-9_-]+'/g) || []).map(s => s.slice(1, -1))) assert.ok(icons.has(ref), ref + ' is in the vendored set');
  assert.equal(read('desktop/renderer/pine-pip.js'), read('app/src/main/assets/pine-views/pine-pip.js'), 'the tablet copy is the same file');
});

test("the styles: the sheet is over everything; the player's rules cannot touch the old strip", () => {
  const css = lf(read('desktop/renderer/pine-pip.css'));
  assert.match(css, /#pinePipShift \{ position: fixed; inset: 0; z-index: 2147483647;/);
  assert.ok(css.indexOf('#pinePipShift.on {') < css.indexOf('#pinePipShift.leaving {'), 'leaving wins over on');
  const block = css.slice(css.indexOf('/* [pip-music] The music player is a mini player'), css.indexOf('/* [pip-free] placed widgets'));   /* up to the second wave's rules */
  const selectors = block.replace(/\/\*[\s\S]*?\*\//g, '').split('}').map(rule => rule.split('{')[0].trim()).filter(Boolean).flatMap(s => s.split(',').map(x => x.trim()));
  assert.ok(selectors.length > 40);
  for (const selector of selectors) assert.ok(/^\.pip-music(\.|:| |$)/.test(selector), 'scoped under the player: ' + selector);
  assert.match(css, /\.pip-music \{ position: absolute;/);
  assert.match(css, /\.pip-music\.expanded \{/);
  assert.equal(read('desktop/renderer/pine-pip.css'), read('app/src/main/assets/pine-views/pine-pip.css'), 'the tablet copy is the same file');
});
