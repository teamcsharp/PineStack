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

/* A class LIST, not a string equal. #1308b added a second class to the
 * frame (`sfx-tv waiting`) and this finder stopped seeing the set at all
 * - so six tests began asserting against `undefined` and reported the
 * module broken when nothing about the module had changed. A stub that
 * models the browser loosely is a meter that fails for its own reasons. */
function findByClass(from, name, out = []) {
  for (const child of from.children) {
    const named = String(child.className || '').split(/\s+/);
    if (child.classes.has(name) || named.indexOf(name) >= 0) out.push(child);
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

/* #1308b: NOTHING IS SHOWN UNTIL THERE IS A PICTURE. The set is built
 * and positioned but stays `waiting` until the <video> has a frame, so
 * a test that wants the tube on has to give it one. The browser fires
 * this; the stub cannot know when to. */
function firstFrame(body) {
  const tube = findByClass(body, 'sfx-tv-tube')[0];
  if (!tube) return null;
  const video = tube.children[0];
  video.fire('loadeddata', {});
  return video;
}

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
  /* #1309b: THE WINDOW IS THE HANDLE. There is no title bar to grab any
   * more - "just a video box, just a video itself" - so the drag is on
   * the frame, and drag() tells a real drag from the press that opens
   * the hold sheet by movement. */
  win.fire('pointerdown', {button: 0, clientX: 500, clientY: 400,
                           pointerId: 1, target: {closest: () => null},
                           preventDefault() {}});
  win.fire('pointermove', {clientX: 560, clientY: 445});
  win.fire('pointerup', {});

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
  assert.ok(!tube.classes.has('on'),
            'the set came on before there was a picture in it');
  const video = firstFrame(body);
  assert.ok(tube.classes.has('on'), 'the set did not come on');

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

test('the picture carries no chrome, and its place is kept when it ends',
     async () => {
  const {body, store} = world({left: 60, top: 70, width: 300, height: 190});
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  /* #1309b: "No wasted space, no elements around it... just a video
   * box." The ✕ and the title bar this test used to press are gone on
   * purpose, so their absence is what is asserted - otherwise the next
   * person to add chrome finds nothing in the way. */
  assert.equal(findByClass(body, 'sfx-tv-head').length, 0,
               'the set grew a title bar again');
  const video = firstFrame(body);
  video.fire('ended', {});
  await wait(OFF_MS + 120);
  assert.equal(set(body), null, 'the window never went');
  assert.deepEqual(JSON.parse(store.get('pineSfxTvBox')),
                   {left: 60, top: 70, width: 300, height: 190});
  tv.stop();
});

test('the level the shell hands over reaches the picture through its short ramp', async () => {
  const {body} = world();
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const video = findByClass(body, 'sfx-tv-tube')[0].children[0];
  tv.level(0.4);
  await wait(180);
  assert.equal(video.volume, 0.4);
  tv.level(2);                       // clamped, like every other level here
  await wait(180);
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

/* ------------------------------------------------------- #1322 */

test('the set is lifted above the view layer, on EVERY surface', async () => {
  const {body} = world();
  station([aClip()]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  /* #1306e lifted the kiosk only, told apart by location.protocol - and
   * this world has no location at all, which is the shell's case. The
   * stylesheet's 900 is under the shell's own high bands (view-chrome
   * 2147483200, the hold sheets 2147483046, the SC pop-up 2147483010)
   * and under a <webview>'s layer, so a set at 900 there is the tablet's
   * "built, playing and completely buried" all over again. Nothing on
   * screen reports that, which is exactly why it is asserted. */
  assert.equal(set(body).style.zIndex, '2147483020');
  tv.stop();
});

test('a clip fired here is rung for the other sets, and shown once here',
     async () => {
  const {body} = world();
  const posts = [];
  /* What the station makes of it: its own stamp, which is NOT the one
   * the pad used - the two machines have no reason to agree - so the
   * mark the caller already set cannot cover it. */
  const rung = {ts: 990099, url: '/sfx/pad.mp4?t=sig', sting: 'pad',
                seconds: 2, video: true, picture_only: true,
                broadcast_ms: Date.now()};
  let serving = false;
  globalThis.pineDesktop = {
    get: async () => ({server_ms: Date.now(), cut_ms: 0,
                       clips: serving ? [rung] : []}),
    post: async (route, payload) => {
      posts.push({route, payload});
      return {ok: true, clip: rung};
    }
  };
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);

  tv.cut({url: '/sfx/pad.mp4?t=sig', sting: 'pad', id: 'pad.mp4',
          video: true, seconds: 2, ts: Date.now(), from: 0.5, to: 1.8},
         {ring: true});
  await wait(40);

  /* THE OTHER SURFACES ARE TOLD. Without this a pad pressed on the
   * tablet pops nothing on the app and vice versa - the clip is already
   * decoded on the pad, so the station never hears of it. */
  assert.equal(posts.length, 1, 'the clip was never rung');
  assert.equal(posts[0].route, '/api/sfx/video/cut');
  assert.equal(posts[0].payload.url, '/sfx/pad.mp4?t=sig');
  assert.equal(posts[0].payload.from, 0.5);
  assert.equal(posts[0].payload.to, 1.8);

  /* AND NOT TWICE HERE. The picture is already on this screen; the ring
   * coming back round must not play it again. */
  serving = true;
  const before = findByClass(body, 'sfx-tv').length;
  tv.offer({...rung, at: Date.now()});
  await wait(40);
  assert.equal(findByClass(body, 'sfx-tv').length, before,
               'the surface that fired it played it a second time');
  assert.equal(tv.waiting(), 0);
  tv.stop();
});

test('a clip that came FROM the station is not rung back at it', async () => {
  world();
  const posts = [];
  globalThis.pineDesktop = {
    get: async () => ({server_ms: Date.now(), cut_ms: 0, clips: []}),
    post: async (route, payload) => { posts.push({route, payload}); return {}; }
  };
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  /* The cue road (#1306) hands back a clip that is ALREADY in the ring.
   * Ringing it again would put a second copy in front of every other
   * set - so the ring is asked for, never assumed. */
  tv.cut(aClip());
  await wait(40);
  assert.equal(posts.length, 0, 'a clip already in the ring was rung again');
  tv.stop();
});

/* #1173 - "So even though the Pine tab is the default device, video seem to
 *  have a slight lag when it comes to playing out of the Pine tablet. its
 *  showing a different video on the spark agent than the tablet so they are
 *  getting out of sync."
 *
 * ONE DECISION, TWO SURFACES. The station already stamps every endless clip
 * with a start (broadcast_ms), and both surfaces are handed the same plan on
 * the same road. What made them disagree was what each did with a plan it
 * arrived at late: start the file from zero, and take the next clip when
 * THIS one ended - so the per-hand-over cost (the CRT collapse, the teardown
 * rest, the decode) was never given back and the error ratcheted at a rate
 * set by how fast the machine is. Measured on the tablet on 2026-09-15 that
 * was about +1.16 s a clip against the station's own stamp, until at eight
 * seconds the staleness test threw a clip away unplayed and the two surfaces
 * were on different pictures.
 *
 * Both halves of it are the two behaviours below, and both would fail
 * silently: a set that starts every clip at zero looks perfectly correct on
 * any one screen, and only the operator standing between two screens can
 * see it. */

test('#1173: a late endless clip is JOINED where the station is, not restarted',
     async () => {
  const {body} = world();
  /* Rung six seconds ago, with a twenty-second slot: the station is six
   * seconds into this picture and so is every other surface. */
  station([aClip({endless: true, seconds: 20,
                  broadcast_ms: Date.now() - 6000})]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const tube = findByClass(body, 'sfx-tv-tube')[0];
  assert.ok(tube, 'the late endless clip was never played');
  const video = tube.children[0];
  assert.equal(video.currentTime, 0, 'seeked before it had metadata');
  /* The browser fires this once it knows the duration; the stub cannot. */
  video.fire('loadedmetadata', {});
  assert.ok(video.currentTime > 5 && video.currentTime < 7,
            'the clip was started at ' + video.currentTime
            + 's instead of joined at the station\'s six');
  tv.stop();
});

test('#1173: a sting still belongs at its own first frame', async () => {
  const {body} = world();
  /* Not the endless set - a picture punctuating a line. Six seconds late
   * is within LATE, so it still plays, and it plays from the top: there is
   * no shared plan to join, and a sting that starts in the middle of
   * itself is a sting that was never worth ringing. */
  station([aClip({seconds: 20, broadcast_ms: Date.now() - 6000})]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  const video = findByClass(body, 'sfx-tv-tube')[0].children[0];
  video.fire('loadedmetadata', {});
  assert.equal(video.currentTime, 0, 'a sting was joined in the middle');
  tv.stop();
});

test('#1173: the endless set drops a clip when its SLOT is over, not at eight seconds',
     async () => {
  /* Twelve seconds into a twenty-second slot: still the picture the other
   * surfaces are showing, so it is joined. Dropping it here - which is what
   * the flat eight-second staleness test did - is precisely how the tablet
   * ended up on a different clip from the desk. */
  const late = world();
  station([aClip({endless: true, seconds: 20,
                  broadcast_ms: Date.now() - 12000})]);
  let tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  assert.ok(set(late.body), 'a clip still inside its slot was thrown away');
  tv.stop();

  /* And past the end of the slot it IS dropped: nothing is showing it any
   * more, so coming on with it now would be the fault the other way. */
  const gone = world();
  station([aClip({endless: true, seconds: 6,
                  broadcast_ms: Date.now() - 12000})]);
  tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  assert.equal(set(gone.body), null, 'a clip whose slot had run out came on');
  tv.stop();
});

test('#1173: the LISTEN wall can ask where the station is inside the clip',
     async () => {
  const {body} = world();
  station([aClip({endless: true, seconds: 20,
                  broadcast_ms: Date.now() - 6000})]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(60);
  assert.ok(set(body), 'no set opened');
  /* listen.js paints the same clip as the LISTEN view's wallpaper and has
   * its own <video>. It must not work the position out for itself - one
   * decision, read off one road. */
  assert.equal(typeof tv.airInto, 'function', 'the wall has nothing to ask');
  const into = tv.airInto();
  assert.ok(into > 5 && into < 7, 'airInto said ' + into);
  /* A sting carries no shared plan and the wall is told so, rather than
   * being handed a number it would seek to. */
  assert.equal(tv.airInto({at: Date.now() - 6000, seconds: 20}), 0);
  tv.stop();
});
