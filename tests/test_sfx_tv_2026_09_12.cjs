/* THE SFX GUY'S TELEVISION: WHERE IT LIVES, AND WHERE IT STAYS PUT.
 *
 * "When popping up the picture in picture display on different views, I
 *  want it to pop up similar to this where it's basically just a little
 *  window that I'm able to click and drag around in position that's able
 *  to be saved to the preferences and be retained the next time that the
 *  picture in picture pops up in the view or in any view."
 *
 * Three things about that would fail SILENTLY, which is why they are
 * tested rather than commented:
 *
 * 1. WHERE IT IS MOUNTED. Every view in this window is a
 *    <section class="view"> that goes display:none the moment another tab
 *    is chosen, and three of them are <webview>s with their own documents.
 *    A set built inside one of those looks perfect in that view and does
 *    not exist in any other - and nothing anywhere reports it, because
 *    from the code's point of view the window opened fine. So the test
 *    asserts the PARENT is document.body.
 *
 * 2. THE PREFERENCE ACTUALLY SURVIVING. A drag that moves the box but
 *    writes nothing, or writes a shape the reader cannot use, is
 *    invisible until the next time the set comes on - by which time
 *    nobody connects the two. The test drags it for real and opens it
 *    again, which is the only way that round trip is proved.
 *
 * 3. THE TUBE COLLAPSING BEFORE THE WINDOW GOES. "it just closes into a
 *    line and disappears" - if the frame is removed on `ended` the
 *    animation never plays and the set simply vanishes, which looks like
 *    a working feature to everything except the operator.
 *
 * There is no jsdom in this repo, so the DOM calls this module actually
 * makes are stubbed just far enough to run it for real.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');

const OFF_MS = 520;            // must match sfx-tv.js
function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

/* ---------------------------------------------------------- the stubs */

function px(value) { return Math.round(Number(String(value).replace('px', '')) || 0); }

function makeNode(tag) {
  const self = {
    tag,
    id: '',
    className: '',
    title: '',
    type: '',
    textContent: '',
    src: '',
    volume: 1,
    muted: false,
    paused: true,
    currentTime: 0,
    parentNode: null,
    children: [],
    dataset: {},
    style: {},
    handlers: {},
    classes: new Set(),
    attrs: {},
    plays: 0,
    classList: {
      add: (n) => self.classes.add(n),
      remove: (n) => self.classes.delete(n),
      contains: (n) => self.classes.has(n)
    },
    setAttribute: (k, v) => { self.attrs[k] = v; },
    removeAttribute: (k) => { if (k === 'src') self.src = ''; delete self.attrs[k]; },
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    addEventListener: (type, fn) => {
      (self.handlers[type] = self.handlers[type] || []).push(fn);
    },
    removeEventListener: (type, fn) => {
      self.handlers[type] = (self.handlers[type] || []).filter((one) => one !== fn);
    },
    fire: (type, event) => {
      for (const fn of [...(self.handlers[type] || [])]) fn(event || {});
    },
    appendChild: (child) => { child.parentNode = self; self.children.push(child); return child; },
    removeChild: (child) => {
      self.children = self.children.filter((one) => one !== child);
      child.parentNode = null;
      return child;
    },
    /* The module never plays anything it did not ask for; record it. */
    play: () => { self.plays += 1; self.paused = false; return Promise.resolve(); },
    pause: () => { self.paused = true; },
    load: () => {}
  };
  /* Geometry off the style, which is exactly what the browser does for a
   * position:fixed box with explicit left/top/width/height. */
  Object.defineProperty(self, 'offsetLeft', {get: () => px(self.style.left)});
  Object.defineProperty(self, 'offsetTop', {get: () => px(self.style.top)});
  Object.defineProperty(self, 'offsetWidth', {get: () => px(self.style.width)});
  Object.defineProperty(self, 'offsetHeight', {get: () => px(self.style.height)});
  return self;
}

function findByClass(from, name, out = []) {
  for (const child of from.children) {
    if (child.classes.has(name) || child.className === name) out.push(child);
    findByClass(child, name, out);
  }
  return out;
}

function world(saved) {
  const store = new Map();
  if (saved) store.set('pineSfxTvBox', JSON.stringify(saved));
  const body = makeNode('body');
  globalThis.document = {createElement: makeNode, body};
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k)
  };
  globalThis.innerWidth = 1600;
  globalThis.innerHeight = 900;
  globalThis.addEventListener = () => {};
  return {body, store};
}

function station(clips) {
  const asked = [];
  globalThis.pineDesktop = {
    get: async (route) => {
      asked.push(route);
      return {server_ms: Date.now(), cut_ms: 0,
              clips: asked.length === 1 ? clips : []};
    }
  };
  return asked;
}

function load() {
  delete require.cache[require.resolve('../desktop/renderer/sfx-tv.js')];
  require('../desktop/renderer/sfx-tv.js');
  return globalThis.PineSfxTv;
}

function aClip(over) {
  return Object.assign({
    ts: Date.now(), broadcast_ms: Date.now(), seconds: 2,
    url: '/sfx/abc?t=sig', sting: 'Gee', video: true
  }, over || {});
}

function set(body) { return findByClass(body, 'sfx-tv')[0] || null; }

/* --------------------------------------------------------- the tests */

test('the set is a child of the body, never of a view', async () => {
  const {body} = world();
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const win = set(body);
  assert.ok(win, 'no set opened');
  /* THE WHOLE POINT: a sibling of <main>, so a tab change cannot hide it. */
  assert.equal(win.parentNode, body);
  tv.stop();
});

test('the saved preference is where the set comes back', async () => {
  const {body} = world({left: 140, top: 96, width: 360, height: 240});
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const win = set(body);
  assert.equal(win.style.left, '140px');
  assert.equal(win.style.top, '96px');
  assert.equal(win.style.width, '360px');
  assert.equal(win.style.height, '240px');
  tv.stop();
});

test('a drag writes the preference, and the next set opens there', async () => {
  const {body, store} = world({left: 100, top: 100, width: 320, height: 200});
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const win = set(body);
  const head = findByClass(body, 'sfx-tv-head')[0];

  head.fire('pointerdown', {button: 0, clientX: 500, clientY: 400,
                            pointerId: 1, target: {closest: () => null},
                            preventDefault() {}});
  head.fire('pointermove', {clientX: 560, clientY: 445});
  head.fire('pointerup', {});

  assert.equal(win.style.left, '160px');
  assert.equal(win.style.top, '145px');
  const kept = JSON.parse(store.get('pineSfxTvBox'));
  assert.deepEqual(kept, {left: 160, top: 145, width: 320, height: 200});

  /* ...and the round trip, which is the half a write-only test misses. */
  assert.deepEqual(tv.box(), {left: 160, top: 145, width: 320, height: 200});
  tv.stop();
});

test('a box left off the edge of a bigger monitor is brought back', () => {
  world({left: 3400, top: 2000, width: 420, height: 268});
  const tv = load();
  const box = tv.box();
  assert.ok(box.left <= 1600 - 80, 'left off the screen: ' + box.left);
  assert.ok(box.top <= 900 - 40, 'top off the screen: ' + box.top);
});

test('the tube comes on, then collapses before the window is removed',
     async () => {
  const {body} = world();
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const tube = findByClass(body, 'sfx-tv-tube')[0];
  assert.ok(tube.classes.has('on'), 'the set did not come on');

  const video = tube.children[0];
  assert.equal(video.tag, 'video');
  assert.equal(video.src, 'http://box:8096/sfx/abc?t=sig');
  /* #789/#981: the booth monitor switch governs anything tagged. */
  assert.equal(video.dataset.pineLive, 'voice');
  assert.equal(video.plays, 1);

  video.fire('ended', {});
  assert.ok(tube.classes.has('off'), 'the tube did not collapse');
  assert.ok(set(body), 'the window went before the collapse could be seen');

  await wait(OFF_MS + 120);
  assert.equal(set(body), null, 'the window never went');
  tv.stop();
});

test('a clip that will not play still takes the set away', async () => {
  const {body} = world();
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const video = findByClass(body, 'sfx-tv-tube')[0].children[0];
  video.fire('error', {});
  await wait(OFF_MS + 120);
  assert.equal(set(body), null, 'a dead clip left the set on for ever');
  assert.equal(tv.on(), false);
  tv.stop();
});

test('a clip whose moment has gone never opens the set', async () => {
  const {body} = world();
  station([aClip({ts: Date.now() - 60000, broadcast_ms: Date.now() - 60000})]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  assert.equal(set(body), null);
  tv.stop();
});

test('the same clip twice is one set', async () => {
  const {body} = world();
  station([]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  const clip = aClip();
  clip.at = Date.now();
  tv.offer(clip);
  tv.offer(clip);
  await wait(40);
  assert.equal(findByClass(body, 'sfx-tv').length, 1);
  assert.equal(tv.waiting(), 0);
  tv.stop();
});

test('the shut button takes it away at once and keeps the position',
     async () => {
  const {body, store} = world({left: 60, top: 70, width: 300, height: 190});
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const shut = findByClass(body, 'sfx-tv-head')[0].children[1];
  shut.fire('click', {});
  assert.equal(set(body), null, 'the operator asked for it gone now');
  assert.deepEqual(JSON.parse(store.get('pineSfxTvBox')),
                   {left: 60, top: 70, width: 300, height: 190});
  tv.stop();
});

test('the level the shell hands over reaches the picture', async () => {
  const {body} = world();
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const video = findByClass(body, 'sfx-tv-tube')[0].children[0];
  tv.level(0.4);
  assert.equal(video.volume, 0.4);
  tv.level(2);                       // clamped, like every other level here
  assert.equal(video.volume, 1);
  tv.stop();
});

test('the route it asks is the station video door, with a marker',
     async () => {
  world();
  const asked = station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  assert.equal(asked[0], '/api/dj/video?since=0');
  tv.stop();
});
