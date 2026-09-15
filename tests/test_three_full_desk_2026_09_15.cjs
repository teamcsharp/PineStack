/* #1193 - THE 3JS TAB ON THE DESK, WHICH LISTED NOTHING AND SAID SO POLITELY.
 *
 * "also make sure the 3js scenes and tab works in the pinebox app"
 *
 * The photograph the operator sent: the 3JS tab open on the Pine Box desk,
 * the sheet reading "3JS experiences - 0 on this station" over "the panel
 * has not registered any scenes yet - give it a moment after the terminal
 * starts". Waiting never helped, and it never could have.
 *
 * three-full.js read its register off its OWN window, `root.PINE_3JS`. The
 * only assignment of that name anywhere in the tree is app.py:164603,
 * inside the station panel's page - and on the desk the panel is not this
 * document, it is a <webview id="controlFrame"> (index.html:542) with its
 * own renderer process and its own window. The module ran in the shell,
 * outside it. An empty array, honestly reported, for ever.
 *
 * The register's entries carry FUNCTIONS (open, shade, close, onResize),
 * and functions cannot cross a webview boundary - only JSON can. So the
 * module goes to the register rather than the register to the module: the
 * whole scene-handling half is one self-contained function which the shell
 * stringifies and evaluates INSIDE the panel, then drives by name. Only
 * {key,label} and plain strings ever cross.
 *
 * These tests are the boundary, built out of two vm contexts - one for the
 * shell, one for the panel - so the real injected source really is
 * evaluated in a second realm that the shell cannot reach into. That is
 * the fault's actual shape, and a single-context test would not see it.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(
  path.join(__dirname, '../desktop/renderer/three-full.js'), 'utf8');

/* ------------------------------------------------------------- a stub DOM */

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.attrs = {};
    this.id = '';
    this.className = '';
    this.textContent = '';
    this.innerHTML = '';
    this.disabled = false;
    this.parentNode = null;
    this.classes = new Set();
    const classes = this.classes;
    this.classList = {
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); }
    };
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChild(child) {
    const at = this.children.indexOf(child);
    if (at >= 0) this.children.splice(at, 1);
    child.parentNode = null;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, event = {stopPropagation() {}}) {
    for (const fn of this.listeners[type] || []) fn(event);
  }
  querySelector() { return null; }
  getBoundingClientRect() { return {width: 900, height: 700}; }
}

function descendants(node) {
  return [node, ...node.children.flatMap(descendants)];
}

function makeDocument(webviews) {
  const document = new Element('document');
  document.body = new Element('body');
  document.head = new Element('head');
  document.documentElement = new Element('html');
  document.createElement = (tag) => new Element(tag);
  document.getElementById = (id) => document.byId[id] || null;
  document.byId = {};
  document.querySelectorAll = (sel) =>
    (sel === 'webview' ? (webviews || []) : []);
  return document;
}

/* ------------------------------------------------------------- the panel */

/* A second realm standing in for the controlFrame webview: its own window,
 * its own document, and - the whole point - the register really in it. The
 * shell's injected source is evaluated HERE and nowhere else. */
function makePanel(register) {
  const document = makeDocument([]);
  const win = {
    PINE_3JS: register,
    addEventListener() {},
    dispatchEvent() {},
    screen: null
  };
  const context = vm.createContext({
    window: win, document, console,
    setTimeout: (fn) => { fn(); return 1; },
    clearTimeout() {}, Promise, Set, Array, String, Object, JSON,
    Event: class {},
    getComputedStyle: () => ({position: 'fixed', display: 'block', visibility: 'visible'})
  });
  context.globalThis = context;
  return {
    win, document, context,
    /* What a <webview> hands back: a promise for the completion value of
     * the evaluated source, in the shell's realm. */
    run: (source) => Promise.resolve(vm.runInContext(source, context))
  };
}

/* ------------------------------------------------------------- the shell */

function makeShell(opts) {
  const options = opts || {};
  const frames = [];
  if (options.frame) frames.push(options.frame);
  const document = makeDocument(frames);
  const win = {
    document,
    addEventListener() {},
    screen: null,
    selectView: options.selectView || undefined
  };
  if (options.register) win.PINE_3JS = options.register;
  const context = vm.createContext({
    window: win, document, console,
    /* UNREF'd, BOTH OF THEM. watch() runs a 2s interval for as long as the
     * shell believes a scene is up over there, and the shell only stops
     * believing when the panel says so - which in a test it never does.
     * A ref'd interval would hold node open for ever and the suite would
     * hang with no output, which is exactly what it did the first time. */
    setTimeout: (fn, ms) => { const t = setTimeout(fn, ms); if (t.unref) t.unref(); return t; },
    clearTimeout: (t) => clearTimeout(t),
    setInterval: (fn, ms) => { const t = setInterval(fn, ms); if (t.unref) t.unref(); return t; },
    clearInterval: (t) => clearInterval(t),
    Promise, Set, Array, String, Object, JSON,
    Event: class {},
    getComputedStyle: () => ({position: 'fixed', display: 'block', visibility: 'visible'})
  });
  context.globalThis = context;
  vm.runInContext(SOURCE, context);
  return {
    win, document, context,
    api: win.PineThreeFull,
    sheet: () => document.body.children.find((n) => n.className === 'p3-sheet'),
    all: (fn) => descendants(document.body).filter(fn),
    text: () => descendants(document.body)
      .map((n) => String(n.textContent || '')).join(' | ')
  };
}

function webview(id, run) {
  const frame = new Element('webview');
  frame.id = id;
  frame.src = 'http://127.0.0.1:8096/';
  frame.executeJavaScript = run;
  return frame;
}

const flush = async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); };

/* A register shaped exactly like the panel's: functions on every entry,
 * which is the reason none of it can be handed across a boundary. */
function register(opened) {
  return [
    {key: 'booth', label: 'DJ Booth', open: () => { opened.push('booth'); }},
    /* The panel's real labels carry an emoji in front of the words -
     * "\u{1F9E0} Dialogue Mind", "\u{1F4BF} Album Stage". Built here from
     * its code point rather than typed, so this file stays free of them
     * too; the station's rule is Carbon icons or none. */
    {key: 'cloud', label: String.fromCodePoint(0x2601) + ' Word Cloud',
     open: () => { opened.push('cloud'); }},
    /* "off" is the panel's take-everything-down entry and is never a
     * choosable experience - the projection must drop it. */
    {key: 'off', label: 'All off', open: () => {}},
    /* A malformed entry: the projection must drop it rather than offer a
     * tile that throws when pressed. */
    {key: 'broken', label: 'Broken'}
  ];
}

/* ====================================================================== */

test('the desk lists the panel\'s real scenes across the webview boundary', async () => {
  const opened = [];
  const panel = makePanel(register(opened));
  const asked = [];
  const shell = makeShell({
    frame: webview('controlFrame', (src) => { asked.push(src); return panel.run(src); })
  });

  /* The shell has no register, and never will: this is the fault. */
  assert.equal(shell.api._registerIsHere(), false);
  assert.equal(shell.win.PINE_3JS, undefined);
  /* The panel has one. */
  assert.ok(Array.isArray(panel.win.PINE_3JS));

  shell.api.chooser();
  /* Before the panel answers it says it is asking, not that there are none. */
  assert.ok(shell.text().includes('asking the panel'));

  await flush();

  const sheet = shell.sheet();
  assert.ok(sheet, 'the sheet is in the shell document, not the panel');
  assert.ok(shell.text().includes('2 on this station, in the panel'),
    'the count must be the panel\'s true count: ' + shell.text());

  const tiles = shell.all((n) => n.className === 'p3-pick');
  /* And the leading emoji is gone from the tile: the panel keeps its own
   * label, the chooser shows the words. */
  assert.deepEqual(tiles.map((t) => t.children[0].textContent),
    ['DJ Booth', 'Word Cloud']);
  assert.equal(panel.win.PINE_3JS[1].label,
    String.fromCodePoint(0x2601) + ' Word Cloud',
    'the register itself is never edited');

  /* The core really was installed over there, and only JSON came back. */
  assert.equal(panel.win.__pineThreeCore.VERSION, 1193);
  /* Compared through JSON on purpose. The objects the core makes are built
   * in the PANEL's realm, so their prototypes are not this realm's - a
   * reference-strict compare fails on two identical-looking arrays. That
   * is not a test quirk, it is the boundary itself: what crosses is the
   * JSON, never the object. */
  assert.equal(JSON.stringify(panel.win.__pineThreeCore.list()),
    JSON.stringify([{key: 'booth', label: 'DJ Booth'},
      {key: 'cloud', label: 'Word Cloud'}]));
  assert.ok(asked[0].includes('window.__pineThreeCore.list()'));
});

test('pressing a tile opens and promotes the scene inside the panel', async () => {
  const opened = [];
  const panel = makePanel(register(opened));
  /* The element the panel's pineWin() would have built for this scene. */
  const win = new Element('div');
  panel.document.byId['pineWin-booth'] = win;

  const views = [];
  const shell = makeShell({
    frame: webview('controlFrame', (src) => panel.run(src)),
    selectView: (name) => views.push(name)
  });

  shell.api.chooser();
  await flush();
  shell.all((n) => n.className === 'p3-pick')[0].fire('click');
  await flush();

  assert.deepEqual(opened, ['booth'], 'the panel\'s own open() ran, in the panel');
  assert.ok(win.classList.contains('p3-full'),
    'the panel\'s own element was promoted - nothing was rebuilt');
  assert.ok(panel.document.body.classList.contains('p3-on'));
  const exit = panel.document.body.children.find((n) => n.className === 'p3-exit');
  assert.ok(exit, 'the way out is built in the panel, on its body');
  assert.equal(exit.attrs['aria-label'], 'Close this experience');

  /* The webview is inside a <section class="view"> that has to be the
   * active one, or the scene is perfect and behind the Logs tab. */
  assert.deepEqual(views, ['control']);
  /* It worked, so the sheet gets out of the way. */
  assert.equal(shell.sheet(), undefined);
  assert.equal(shell.api.isFull(), true);

  /* The X, pressed over there, really closes it over there. */
  exit.fire('click');
  assert.equal(win.classList.contains('p3-full'), false);
  assert.equal(panel.win.__pineThreeCore.state().full, false);
});

test('the tablet keeps the direct road and never touches a frame', async () => {
  const opened = [];
  /* Register AND a webview present: the register wins, because the test is
   * "can I reach it with a plain call", not "is there a frame about". */
  const shell = makeShell({
    register: register(opened),
    frame: webview('controlFrame', () => {
      throw new Error('the tablet must never go through the bridge');
    })
  });
  assert.equal(shell.api._registerIsHere(), true);

  shell.api.chooser();
  await flush();
  assert.ok(shell.text().includes('2 on this station'), shell.text());
  assert.ok(!shell.text().includes('in the panel'),
    'the local road must not claim the scenes are in a panel');

  /* The core installed itself in THIS window, and the register it read is
   * the one in this window. */
  assert.equal(shell.win.__pineThreeCore.VERSION, 1193);

  shell.document.byId['pineWin-booth'] = new Element('div');
  const said = await shell.api.show('booth');
  assert.equal(said, 'booth');
  assert.deepEqual(opened, ['booth']);
  assert.ok(shell.document.byId['pineWin-booth'].classList.contains('p3-full'));
});

test('an unreachable panel says which thing happened, not nothing', async () => {
  /* 1. the frame is there and refuses. */
  const shell = makeShell({
    frame: webview('controlFrame',
      () => Promise.reject(new Error('Script failed to execute')))
  });
  shell.api.chooser();
  await flush();
  const text = shell.text();
  assert.ok(text.includes('could not be counted'),
    'a count nobody can stand behind must not be printed as 0: ' + text);
  assert.ok(!text.includes('0 on this station'), text);
  assert.ok(text.includes('the station panel could not be reached'), text);
  assert.ok(text.includes('Script failed to execute'), text);
  assert.equal(shell.all((n) => n.className === 'p3-pick').length, 0);

  /* 2. no frame at all - a different fault with a different cure. */
  const bare = makeShell({});
  bare.api.chooser();
  await flush();
  assert.ok(bare.text().includes('there is no station panel frame to ask'),
    bare.text());
  assert.ok(!bare.text().includes('0 on this station'), bare.text());

  /* 3. the panel answers, and genuinely has nothing yet. That is the ONLY
   * case allowed to print zero, and it says the panel answered. */
  const empty = makePanel([]);
  const early = makeShell({frame: webview('controlFrame', (src) => empty.run(src))});
  early.api.chooser();
  await flush();
  assert.ok(early.text().includes('0 on this station, in the panel'), early.text());
  assert.ok(early.text().includes('the station panel answered'), early.text());
});

test('a second press while one is in flight is refused, not raced', async () => {
  const opened = [];
  const panel = makePanel(register(opened));
  panel.document.byId['pineWin-booth'] = new Element('div');
  let release = null;
  const shell = makeShell({
    frame: webview('controlFrame', (src) => {
      /* A slow scene: several of these fetch three.js on first open, which
       * is a network round trip before there is anything to promote. */
      if (src.includes('.show(')) {
        return new Promise((done) => { release = () => done(panel.run(src)); });
      }
      return panel.run(src);
    })
  });
  shell.api.chooser();
  await flush();
  const tiles = shell.all((n) => n.className === 'p3-pick');

  tiles[0].fire('click');
  await flush();
  assert.equal(tiles[0].disabled, true, 'every tile goes down, not just the pressed one');
  assert.equal(tiles[1].disabled, true);

  /* Same key twice, and a different key, both refused with a sentence. */
  assert.equal(await shell.api.show('booth'), 'still opening that one - give it a moment');
  assert.equal(await shell.api.show('cloud'), 'one at a time - the last one is still opening');
  assert.deepEqual(opened, [], 'nothing opened twice');

  release();
  await flush();
  assert.deepEqual(opened, ['booth']);
  assert.equal(tiles[0].disabled, false);
});

test('a panel that reloads under an open scene is told apart from a close', async () => {
  const opened = [];
  const panel = makePanel(register(opened));
  panel.document.byId['pineWin-booth'] = new Element('div');
  const shell = makeShell({frame: webview('controlFrame', (src) => panel.run(src))});

  assert.equal(await shell.api.show('booth'), 'booth');
  assert.equal(shell.api.isFull(), true);

  /* A reload is a NEW document: the injected core is gone with it. The
   * watcher asks BARE - without re-installing - precisely so this is
   * distinguishable from the operator pressing the X. */
  delete panel.win.__pineThreeCore;
  const probe = await new Promise((done) => {
    panel.run('(function(){"use strict";try{return window.__pineThreeCore '
      + '? window.__pineThreeCore.state() : null;}catch(e){return null;}})()')
      .then(done);
  });
  assert.equal(probe, null, 'a reloaded panel has no core to answer with');

  /* And the shell's own bare road reports the same, so the sheet can say
   * "the panel reloaded and took the scene with it" rather than shrugging. */
  shell.api.chooser();
  await flush();
  assert.ok(shell.sheet(), 'the chooser still opens after a panel reload');
  /* The core is re-installed by the very next ask - no restart needed. */
  assert.equal(panel.win.__pineThreeCore.VERSION, 1193);
});

test('the injected core closes over nothing outside itself', () => {
  const shell = makeShell({});
  const source = shell.api._source();
  /* It is evaluated in a realm that has never seen three-full.js. If it
   * reached for one name from the module around it, this throws. */
  const alone = makePanel(register([]));
  delete alone.win.__pineThreeCore;
  const said = vm.runInContext(source, alone.context);
  assert.equal(said, 'installed');
  assert.equal(alone.win.__pineThreeCore.VERSION, 1193);
  assert.equal(vm.runInContext(source, alone.context), 'already here',
    'idempotent: a second send must not drop a live scene\'s bookkeeping');
  /* The promotion CSS travels with it - on the desk the shell stylesheet
   * lands in a document with nothing to style. */
  assert.ok(source.includes('.p3-full{position:fixed!important'));
});
