/* #1198: A VIDEO ON A SAMPLER PAD - ITS THUMBNAIL, ITS HOLD, AND ITS FADE.
 *
 * "If I put the video on a sampler pad, I want the video on the sampler pad
 *  so I see the thumbnail of it and then whenever I tap and hold it I want
 *  the video to play until I let go of it on the sampler pad. Have the video
 *  on the sampler pad faded to 30% or whatever I said it to in the
 *  preferences."
 *
 * FOUR THINGS HERE WOULD FAIL SILENTLY, which is why they are tested rather
 * than described in a comment:
 *
 * 1. THE PAD PICKING THE WRONG PICTURE. A video pad wears a still from the
 *    station's poster road; an audio pad keeps the waveform it has always
 *    had. Get that backwards and the pad still plays, still lights, still
 *    reports its length - it simply shows the wrong thing, and nobody
 *    connects "that tile looks odd" to a branch in paintPadFaces.
 *
 * 2. THE RELEASE GOING MISSING. A hold that starts a film and a release
 *    that does not stop it is a video playing for ever on a pad the
 *    operator has already let go of - and it looks exactly like a pad that
 *    is still being held. The test presses and releases by all three of the
 *    shapes a real finger takes: a clean pointerup, a pointercancel, and a
 *    pointer LEAVING the pad, which is what a thumb sliding off a 92-pixel
 *    tile actually produces.
 *
 * 3. TWO PADS AT ONCE. The rule is the sampler's own choke rule (see the
 *    long note in sampler-face.js): every video pad is in one choke group,
 *    because there is one screen. The later hold takes the picture, the
 *    earlier one drops back to its still and does NOT get it back. A wrong
 *    answer here is two decoders running on a tablet and nobody noticing
 *    until the frame rate goes.
 *
 * 4. THE FADE NOT BEING HIS. 30% is the default and the dial is the
 *    preference; a fade hardcoded in a stylesheet would look right at 30
 *    and ignore every other setting he ever chose.
 *
 * There is no jsdom in this repo, so the DOM these two modules actually use
 * is stubbed just far enough to run them for real - the whole sampler is
 * mounted, the pads are pressed through their own pointer handlers, and
 * nothing here reaches inside a module to fake a result.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const path = require('path');

const RENDERER = path.join(__dirname, '..', 'desktop', 'renderer');

/* ---------------------------------------------------------- the stubs */

let registry = null;
let timers = [];

function makeNode(tag) {
  const self = {
    tag: String(tag || 'div'),
    _id: '',
    className: '',
    title: '',
    type: '',
    alt: '',
    textContent: '',
    innerHTML: '',
    value: '',
    min: '', max: '', step: '',
    src: '',
    preload: '',
    controls: false,
    hidden: false,
    muted: false,
    defaultMuted: false,
    playsInline: false,
    loop: false,
    paused: true,
    currentTime: 0,
    width: 0,
    height: 0,
    parentNode: null,
    children: [],
    dataset: {},
    /* A style object, not a bag: both files use setProperty and
       removeProperty as well as plain assignment. */
    style: (function () {
      const s = {};
      s.setProperty = (k, v) => { s[k] = String(v); };
      s.removeProperty = (k) => { delete s[k]; };
      s.getPropertyValue = (k) => (k in s ? s[k] : '');
      return s;
    }()),
    handlers: {},
    classes: new Set(),
    attrs: {},
    plays: 0,
    pauses: 0,
    classList: {
      add: (n) => self.classes.add(n),
      remove: (n) => self.classes.delete(n),
      contains: (n) => self.classes.has(n),
      toggle: (n, on) => {
        const want = on === undefined ? !self.classes.has(n) : !!on;
        if (want) self.classes.add(n); else self.classes.delete(n);
        return want;
      }
    },
    setAttribute: (k, v) => { self.attrs[k] = String(v); },
    getAttribute: (k) => (k in self.attrs ? self.attrs[k] : null),
    removeAttribute: (k) => { delete self.attrs[k]; },
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    /* A 100x100 tile at the origin, so velocityFrom has a box to read. */
    getBoundingClientRect: () => ({left: 0, top: 0, width: 100, height: 100}),
    getContext: () => ({
      clearRect() {}, fillRect() {}, fillStyle: '', strokeStyle: ''
    }),
    addEventListener: (type, fn) => {
      (self.handlers[type] = self.handlers[type] || []).push(fn);
    },
    removeEventListener: (type, fn) => {
      self.handlers[type] = (self.handlers[type] || []).filter((o) => o !== fn);
    },
    fire: (type, ev) => {
      for (const fn of [...(self.handlers[type] || [])]) fn(ev || {});
    },
    appendChild: (c) => { c.parentNode = self; self.children.push(c); return c; },
    insertBefore: (c, before) => {
      if (c.parentNode) c.parentNode.removeChild(c);
      c.parentNode = self;
      const at = before ? self.children.indexOf(before) : -1;
      if (at < 0) self.children.push(c); else self.children.splice(at, 0, c);
      return c;
    },
    removeChild: (c) => {
      self.children = self.children.filter((o) => o !== c);
      c.parentNode = null;
      return c;
    },
    remove: () => { if (self.parentNode) self.parentNode.removeChild(self); },
    play: () => { self.plays += 1; self.paused = false; return Promise.resolve(); },
    pause: () => { self.pauses += 1; self.paused = true; },
    load: () => {},
    querySelector: (sel) => query(self, sel)[0] || null,
    querySelectorAll: (sel) => query(self, sel)
  };
  /* An id assignment is how a node joins getElementById - which is exactly
     how sampler.js builds its pads (`pad.id = "pad-" + p`). */
  Object.defineProperty(self, 'id', {
    get: () => self._id,
    set: (v) => { self._id = String(v); if (registry) registry.set(self._id, self); }
  });
  Object.defineProperty(self, 'firstChild', {get: () => self.children[0] || null});
  Object.defineProperty(self, 'clientWidth', {get: () => 100});
  Object.defineProperty(self, 'clientHeight', {get: () => 100});
  Object.defineProperty(self, 'isConnected', {get: () => true});
  return self;
}

/* A class LIST, an id or a tag - the three shapes these two files use. */
function matches(node, sel) {
  const s = String(sel).trim();
  if (s.charAt(0) === '.') {
    const want = s.slice(1);
    return node.classes.has(want)
      || String(node.className || '').split(/\s+/).indexOf(want) >= 0;
  }
  if (s.charAt(0) === '#') return node._id === s.slice(1);
  return node.tag === s;
}

function query(from, sel, out) {
  out = out || [];
  for (const child of from.children) {
    if (matches(child, sel)) out.push(child);
    query(child, sel, out);
  }
  return out;
}

function world() {
  registry = new Map();
  timers = [];
  const body = makeNode('body');
  const host = makeNode('div');
  host.id = 'sampler';
  body.appendChild(host);
  const store = new Map();
  globalThis.document = {
    readyState: 'complete',
    hidden: false,
    body,
    createElement: makeNode,
    /* An id the page has not built yet answers with a throwaway rather than
       null. build() writes half its chrome through innerHTML, which this
       stub does not parse, and el("pbWhole").addEventListener must not
       throw over a detail this test is not about. */
    getElementById: (id) => {
      if (registry.has(id)) return registry.get(id);
      const node = makeNode('div');
      node.id = id;
      return node;
    },
    querySelector: (sel) => query(body, sel)[0] || null,
    querySelectorAll: (sel) => query(body, sel),
    addEventListener: () => {}
  };
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k)
  };
  globalThis.addEventListener = () => {};
  globalThis.location = {protocol: 'http:'};
  globalThis.innerWidth = 1280;
  globalThis.innerHeight = 800;
  globalThis.confirm = () => true;
  globalThis.prompt = () => '';
  globalThis.requestAnimationFrame = () => 0;
  globalThis.cancelAnimationFrame = () => {};
  /* The face keeps a once-a-minute wallpaper timer; the test must not leave
     the runner holding it. */
  const realInterval = globalThis.setInterval;
  globalThis.setInterval = (fn, ms) => {
    const handle = realInterval(fn, ms);
    if (handle && typeof handle.unref === 'function') handle.unref();
    timers.push(handle);
    return handle;
  };
  return {body, host, store};
}

function unworld() {
  for (const handle of timers) clearInterval(handle);
  timers = [];
}

function engineStub() {
  return {
    warm: () => true,
    loaded: () => true,
    load: async () => true,
    unload: () => {},
    seconds: () => 3,
    peaks: () => [0.2, 0.9, 0.4, 0.6, 0.3, 0.8],
    get: () => ({gain: 1, pitch: 1, pan: 0, loop: false, reverse: false, trim: null}),
    set: () => {},
    fire: () => 'voice-' + Math.random().toString(36).slice(2, 8),
    release: () => {},
    stopAll: () => {},
    stopPad: () => {},
    setPolyphonic: () => {},
    isPolyphonic: () => false,
    playing: () => 0,
    footprint: () => ({pads: 0, bytes: 0}),
    stats: () => ({voices: 0, bytes: 0, pads: 0, seconds: 0})
  };
}

/* A pad's metadata as importRow writes it. `video` and `url` are #1310's
   two fields, taken off the response's Content-Type; `srcId` is the clip id
   every import has always carried. */
function videoMeta(over) {
  return Object.assign({
    label: 'the horn', who: 'the board', kind: 'sfx',
    srcId: 'a1b2c3d4e5f60718',
    url: '/sfx/a1b2c3d4e5f60718?t=sig123',
    exact: true, cut: '', at: Date.now(), seconds: 2.5,
    gain: 1, pitch: 1, loop: false, reverse: false, trim: null, choke: '',
    video: true
  }, over || {});
}

function audioMeta(over) {
  return Object.assign({
    label: 'a line of talk', who: 'Gee', kind: 'round',
    srcId: 'line-99', exact: true, cut: '', at: Date.now(), seconds: 4,
    gain: 1, pitch: 1, loop: false, reverse: false, trim: null, choke: ''
  }, over || {});
}

function load() {
  for (const name of ['sampler-face.js', 'sampler.js']) {
    delete require.cache[require.resolve(path.join(RENDERER, name))];
  }
  require(path.join(RENDERER, 'sampler-face.js'));
  require(path.join(RENDERER, 'sampler.js'));
  return {face: globalThis.PineSamplerFace, sampler: globalThis.PineSampler};
}

/* Mount the whole instrument with `pads` on bank 0, then hand back the
   handles the tests press. */
async function studio(pads, saved) {
  const {body, host, store} = world();
  if (saved) store.set('pineSamplerModes', JSON.stringify(saved));
  const banks = [];
  for (let b = 0; b < 5; b += 1) banks.push(new Array(16).fill(null));
  for (const key of Object.keys(pads || {})) banks[0][Number(key)] = pads[key];
  store.set('pineSamplerLayout', JSON.stringify(banks));
  globalThis.pineSampler = engineStub();
  globalThis.pineDesktop = {
    readConfig: async () => ({baseUrl: 'http://box:8096'}),
    /* The face asks the gallery for a wallpaper at build time; an empty
       answer is the shape of a station with no pictures, and this test is
       not about the backdrop. */
    get: async () => ({generations: []})
  };
  globalThis.PineStationFeed = {subscribe: () => () => {}, state: () => ({})};
  delete globalThis.PineAir;
  delete globalThis.PineSfxTv;
  delete globalThis.PineDismiss;
  delete globalThis.PineListenModel;
  delete globalThis.PineBusy;
  const mods = load();
  await mods.sampler.mount(host);
  return Object.assign({body, host, store}, mods);
}

function padCell(index) { return registry.get('pad-' + index) || null; }
function shotIn(cell) { return cell ? cell.querySelector('.pb-pad-shot') : null; }
function filmIn(cell) { return cell ? cell.querySelector('.pb-pad-film') : null; }
function waveIn(cell) { return cell ? cell.querySelector('.pb-pad-wave') : null; }

/* The poster is an <img> and the browser is what fires its load; the stub
   cannot know when to, so every test that wants a still on a pad fires it
   on the element the face made - reached through face.posterNode(), because
   a poster still in the queue is not in any cell yet. */
function press(cell, over) {
  cell.fire('pointerdown', Object.assign({
    clientX: 10, clientY: 10, pointerId: 1, button: 0,
    preventDefault() {}
  }, over || {}));
}

/* ------------------------------------------------------------ the tests */

test('the poster url is the station\'s one poster road, signed off the clip',
  async () => {
    const shop = await studio({8: videoMeta()});
    const url = shop.face.posterUrlFor(videoMeta());
    assert.equal(url, '/api/sfx/poster/a1b2c3d4e5f60718?t=sig123');
    /* AN AUDIO PAD ASKS FOR NOTHING. The poster road answers 404 for
       anything that is not a video, on purpose, and a pad that knows it is
       not one must not go and find that out. */
    assert.equal(shop.face.posterUrlFor(audioMeta()), '');
    unworld();
  });

test('a video pad draws a poster and an audio pad still draws its waveform',
  async () => {
    const shop = await studio({8: videoMeta(), 3: audioMeta()});
    /* Before the frame lands, the video pad holds its waveform rather than
       going blank - the poster is a round trip with an ffmpeg at the end. */
    assert.ok(waveIn(padCell(8)), 'the video pad went blank while it waited');

    const img = shop.face.posterNode(0, 8);
    assert.ok(img, 'the video pad never asked for a poster');
    assert.equal(img.src, '/api/sfx/poster/a1b2c3d4e5f60718?t=sig123');
    img.fire('load', {});

    const shot = shotIn(padCell(8));
    assert.ok(shot, 'the frame arrived and the pad did not wear it');
    assert.equal(waveIn(padCell(8)), null,
      'the pad kept its waveform under the frame');

    /* AND THE AUDIO PAD IS UNTOUCHED, which is the other half of it. */
    assert.ok(waveIn(padCell(3)), 'the audio pad lost its waveform');
    assert.equal(shotIn(padCell(3)), null,
      'an audio pad asked the poster road for a frame');
    unworld();
  });

test('a poster the station will not draw leaves the pad its waveform',
  async () => {
    /* The poster road answers 404 for a clip it cannot render - an older
       mp4 ffmpeg will not seek, a pad whose video arrived by some road the
       sfx shelf never heard of. A blank tile would read as a broken pad;
       the waveform it always had reads as a pad. */
    const shop = await studio({8: videoMeta()});
    shop.face.posterNode(0, 8).fire('error', {});
    shop.face.paintPadFaces();
    assert.equal(shotIn(padCell(8)), null);
    assert.ok(waveIn(padCell(8)), 'a pad with no frame went blank');
    /* And it is not asked again on every repaint. */
    shop.face.paintPadFaces();
    assert.equal(shop.face.postersInFlight(), 0);
    assert.equal(shop.face.postersWaiting(), 0);
    /* The hold still works: the film needs the clip's url, not its frame. */
    press(padCell(8));
    assert.ok(filmIn(padCell(8)), 'a pad with no poster would not play');
    padCell(8).fire('pointerup', {});
    unworld();
  });

test('on the desktop shell both pictures are asked for at the station',
  async () => {
    /* #1348: the chrome is a file:// document, so a root-relative url
       resolves to file:///api/... and loads nothing at all - which is why
       the SC monitor drew and the slideshow stayed black. Neither the still
       nor the film may repeat that. */
    const shop = await studio({8: videoMeta()});
    globalThis.location = {protocol: 'file:'};
    globalThis.pineStationBase = () => 'http://127.0.0.1:8096';
    assert.equal(shop.face.posterUrlFor(videoMeta()),
      'http://127.0.0.1:8096/api/sfx/poster/a1b2c3d4e5f60718?t=sig123');
    press(padCell(8));
    assert.equal(filmIn(padCell(8)).src,
      'http://127.0.0.1:8096/sfx/a1b2c3d4e5f60718?t=sig123');
    padCell(8).fire('pointerup', {});
    delete globalThis.pineStationBase;
    unworld();
  });

test('a hold starts the video on the pad and a release stops it', async () => {
  const shop = await studio({8: videoMeta()});
  const cell = padCell(8);
  press(cell);
  const film = filmIn(cell);
  assert.ok(film, 'holding a video pad started nothing');
  assert.equal(film.tag, 'video');
  assert.equal(film.plays, 1, 'the film was put on the pad but never played');
  /* MUTED, ALWAYS: the engine is already playing the clip's audio track in
     the mix, and a film with sound would be the same clip twice. */
  assert.equal(film.muted, true, 'the pad film would have made a noise');
  assert.equal(film.src, '/sfx/a1b2c3d4e5f60718?t=sig123');

  cell.fire('pointerup', {});
  assert.equal(film.paused, true, 'letting go did not stop the video');
  assert.equal(filmIn(cell), null, 'the film stayed on the pad after release');
  unworld();
});

test('the pad shows one picture at a time: the still steps aside for the film',
  async () => {
    /* Both sit in the same box at the same fade. Left showing together, the
       frozen frame reads THROUGH the moving one at 30% - a clip playing
       over a stopped copy of itself. */
    const shop = await studio({8: videoMeta()});
    const img = shop.face.posterNode(0, 8);
    img.fire('load', {});
    assert.notEqual(img.style.visibility, 'hidden');
    press(padCell(8));
    assert.equal(img.style.visibility, 'hidden',
      'the still stayed under the film');
    /* And a repaint mid-hold - a selection, a bank paint - must not put it
       back while the film is still running. */
    shop.face.paintPadFaces();
    assert.equal(img.style.visibility, 'hidden');
    padCell(8).fire('pointerup', {});
    assert.notEqual(img.style.visibility, 'hidden',
      'letting go left the pad with no picture at all');
    unworld();
  });

test('a release that arrives as the pointer leaving the pad still stops it',
  async () => {
    const shop = await studio({8: videoMeta()});
    const cell = padCell(8);
    press(cell);
    assert.ok(filmIn(cell), 'holding a video pad started nothing');
    /* A THUMB SLIDING OFF A 92-PIXEL TILE. No pointerup ever arrives at the
       pad in this shape; pointerleave is the whole of the release. */
    cell.fire('pointerleave', {});
    assert.equal(filmIn(cell), null,
      'the finger left the pad and the video played on');
    unworld();
  });

test('a pointercancel stops it too, and so does the window losing focus',
  async () => {
    const shop = await studio({8: videoMeta()});
    const cell = padCell(8);

    press(cell);
    cell.fire('pointercancel', {});
    assert.equal(filmIn(cell), null, 'a cancelled gesture left the video running');

    /* THE PATH A FINGER NEVER TAKES. Chromium fires no pointerup at all when
       the window goes behind something; the sweep is the only release. */
    press(cell);
    assert.ok(filmIn(cell), 'the second hold started nothing');
    shop.face.filmStopAll();
    assert.equal(filmIn(cell), null, 'the sweep left the video running');
    unworld();
  });

test('two video pads at once: the later hold takes the one screen',
  async () => {
    const shop = await studio({8: videoMeta(), 12: videoMeta({
      label: 'the siren', srcId: 'ffee0011223344aa',
      url: '/sfx/ffee0011223344aa?t=sig999'
    })});
    press(padCell(8));
    assert.deepEqual(shop.face.filmAt(), {bank: 0, pad: 8});

    /* A second finger while the first is still down. */
    press(padCell(12));
    assert.deepEqual(shop.face.filmAt(), {bank: 0, pad: 12},
      'the later hold did not take the screen');
    assert.equal(filmIn(padCell(8)), null,
      'both pads were running a film at once');

    /* LIFTING THE CHOKED PAD TAKES NOTHING DOWN. This is the whole of the
       rule: pad 8 lost the picture when 12 took it, and 8's release must
       not reach across and stop 12. */
    padCell(8).fire('pointerup', {});
    assert.deepEqual(shop.face.filmAt(), {bank: 0, pad: 12},
      'releasing the choked pad stopped the pad that had the screen');

    /* And when the pad that HAS it is let go, it stops - it does not hand
       back to 8, exactly as a choked voice never comes back. */
    padCell(12).fire('pointerup', {});
    assert.equal(shop.face.filmAt(), null);
    assert.equal(filmIn(padCell(8)), null, 'the picture handed back to pad 8');
    unworld();
  });

test('the fade is thirty per cent by default and is his to change',
  async () => {
    const shop = await studio({8: videoMeta()});
    /* HIS NUMBER, AND IT IS THE DEFAULT. "faded to 30% or whatever I said
       it to in the preferences." */
    assert.equal(shop.sampler.padVideoFade(), 0.3);
    const img = shop.face.posterNode(0, 8);
    img.fire('load', {});
    assert.equal(shotIn(padCell(8)).style.opacity, '0.3');
    press(padCell(8));
    assert.equal(filmIn(padCell(8)).style.opacity, '0.3',
      'the film ignored the fade the still obeyed');
    padCell(8).fire('pointerup', {});

    /* THE DIAL IS THE PREFERENCE, and it reaches both pictures. */
    const dial = registry.get('pbPadVid');
    assert.ok(dial, 'there is no fade control under the pads');
    assert.equal(dial.value, '30');
    dial.value = '70';
    dial.fire('input', {});
    assert.equal(shop.sampler.padVideoFade(), 0.7);
    assert.equal(shotIn(padCell(8)).style.opacity, '0.7',
      'the still did not follow the dial');
    press(padCell(8));
    assert.equal(filmIn(padCell(8)).style.opacity, '0.7',
      'the film did not follow the dial');
    padCell(8).fire('pointerup', {});
    unworld();
  });

test('the fade he set is still set when he comes back', async () => {
  /* It lives with every other thing this page remembers - "remember what
     settings I have on on this page and have them on by default when I go
     back to this page" - so a reload has to find it there. */
  const shop = await studio({8: videoMeta()}, {poly: false, padVideo: 45});
  assert.equal(shop.sampler.padVideoFade(), 0.45);
  const img = shop.face.posterNode(0, 8);
  img.fire('load', {});
  assert.equal(shotIn(padCell(8)).style.opacity, '0.45');
  unworld();
});

test('sixteen pads do not ask the station for sixteen posters at once',
  async () => {
    /* The poster road renders behind a semaphore of TWO. A full bank asking
       together is a queue with an ffmpeg at the front of it, so the face
       holds the line at two and everything else waits where it can still be
       thrown away. */
    const full = {};
    for (let p = 0; p < 16; p += 1) {
      const hex = ('0000000000000000' + p.toString(16)).slice(-16);
      full[p] = videoMeta({srcId: hex, url: '/sfx/' + hex + '?t=s' + p});
    }
    const shop = await studio(full);
    assert.equal(shop.face.postersInFlight(), 2,
      'the whole bank went at the station at once');

    /* One lands, the next goes - never more than two on the wire. */
    shop.face.posterNode(0, 0).fire('load', {});
    assert.equal(shop.face.postersInFlight(), 2);
    unworld();
  });

test('a bank change drops the queue and keeps what already arrived',
  async () => {
    const full = {};
    for (let p = 0; p < 16; p += 1) {
      const hex = ('0000000000000000' + p.toString(16)).slice(-16);
      full[p] = videoMeta({srcId: hex, url: '/sfx/' + hex + '?t=s' + p});
    }
    const shop = await studio(full);
    shop.face.posterNode(0, 0).fire('load', {});
    assert.equal(shop.face.postersWaiting() > 0, true,
      'nothing was queued, so there is nothing to prove about dropping it');

    /* The operator moves to bank 2. Nobody is looking at bank 1 any more. */
    registry.get('pbBank-1').fire('click', {});
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(shop.face.postersWaiting(), 0,
      'the station is still being asked for pictures of a bank nobody sees');

    /* And coming back does not re-ask for the one that already landed: the
       <img> is kept and re-parented, never rebuilt. */
    registry.get('pbBank-0').fire('click', {});
    await new Promise((r) => setTimeout(r, 10));
    const back = shop.face.posterNode(0, 0);
    assert.ok(back, 'the poster that had arrived was thrown away');
    assert.equal(back.parentNode, padCell(0),
      'the kept poster was not put back on its pad');
    unworld();
  });

test('changing banks under a held pad takes the film with it', async () => {
  /* A film is layered into a CELL, and the cells are shared by every bank,
     so a film left running through a bank change would be bank 1's video
     sitting on bank 2's clip. */
  const shop = await studio({8: videoMeta()});
  press(padCell(8));
  assert.deepEqual(shop.face.filmAt(), {bank: 0, pad: 8});
  registry.get('pbBank-2').fire('click', {});
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(shop.face.filmAt(), null, 'the film outlived its bank');
  assert.equal(filmIn(padCell(8)), null);
  unworld();
});
