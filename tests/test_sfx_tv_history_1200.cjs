/* #1200: THE STRIP PAGES BACKWARDS THROUGH THE STATION'S HISTORY.
 *
 * "Allow me to roll the wheel or scroll through the previous history of
 *  videos that's been loaded or thumbnails or MP4s. I wanna be able to
 *  scroll backwards in the history and just keep loading more and more of
 *  the history."
 *
 * Seven things here would fail SILENTLY, which is the whole reason they
 * are asserted rather than commented:
 *
 * 1. THE WHEEL GOING TO THE WRONG ELEMENT. A wheel handler that scrolls
 *    the strip but does not preventDefault looks perfect on a short strip
 *    and slides the sheet out from under the pointer on a long one - and
 *    the only person who ever sees it is the operator, mid-flick, with
 *    the menu he was reading gone. So the test asserts BOTH: the strip
 *    moved, and the gesture was stopped.
 *
 * 2. THE PAGE NEVER BEING ASKED FOR. The strip is at scrollLeft 0 the
 *    moment it is built, so a naive "at the old end -> fetch" fires on
 *    open and a naive "on scroll" never fires at all when the strip is
 *    too short to scroll. The test drives the real wheel handler and
 *    asserts the exact route, `before` and all.
 *
 * 3. A SECOND PAGE DUPLICATING THE FIRST. `before` is INCLUSIVE on
 *    purpose (a ts is whole seconds and two clips can share one), so the
 *    boundary row ALWAYS comes back and the dedupe is the only thing
 *    standing between the operator and a strip that repeats itself. A
 *    duplicate is not an error anywhere; it just looks like the station
 *    played the same clip twice.
 *
 * 4/5. THE END OF THE LEDGER AND A FAILED PAGE LOOKING THE SAME. Both
 *    stop the tiles arriving. If a failure reads as the end, the strip
 *    quietly teaches him there is no more history when there is - and it
 *    never asks again. So the two are asserted as DIFFERENT words, and a
 *    failure is asserted to leave `more` true.
 *
 * 6. THE POSTER QUEUE. The station's poster road renders behind a
 *    semaphore of TWO. Twenty-four tiles setting an <img src> at once is
 *    not twenty-four answers, it is a queue with an ffmpeg at the front,
 *    and nothing on screen reports it - the tiles simply stay dark for a
 *    long time. The thing to prove is a NEGATIVE, that more than two are
 *    never in flight, and a negative cannot be seen.
 *
 * 7. THE CEILING. "Do not let the strip become unbounded." #1312's note
 *    in sfx-tv.js is why: orphaned elements each held an HTTP connection,
 *    a WebView allows about six per host, and after a few taps every
 *    request on the page hung. A strip that grows for ever is fine for
 *    twenty minutes and then the station goes quiet.
 *
 * There is no jsdom in this repo, so the DOM is stubbed just far enough to
 * run the module for real - including a scroller that CLAMPS and fires its
 * own scroll events, because a stub that lets scrollLeft be 1e7 would
 * prove the opposite of what this file is for.
 */
const assert = require('node:assert/strict');
const {test, after} = require('node:test');

const HIST_PAGE = 24;            // must match sfx-tv.js
const HIST_MOST = 120;           // must match sfx-tv.js
const TILE_PX = 81;              // 76 px tile + 5 px gap, as the strip draws it
const VIEW_PX = 400;             // the sheet is 420 px wide on the tablet

function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

/* ---------------------------------------------------------- the stubs */

function px(value) { return Math.round(Number(String(value).replace('px', '')) || 0); }

function makeNode(tag) {
  let scroll = 0;
  const self = {
    tag,
    id: '',
    className: '',
    title: '',
    type: '',
    alt: '',
    textContent: '',
    innerHTML: '',
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
    appendChild: (child) => {
      if (child.parentNode) child.parentNode.removeChild(child);
      child.parentNode = self;
      self.children.push(child);
      return child;
    },
    insertBefore: (child, ref) => {
      if (child.parentNode) child.parentNode.removeChild(child);
      child.parentNode = self;
      const at = ref ? self.children.indexOf(ref) : -1;
      if (at < 0) self.children.push(child);
      else self.children.splice(at, 0, child);
      return child;
    },
    removeChild: (child) => {
      self.children = self.children.filter((one) => one !== child);
      child.parentNode = null;
      return child;
    },
    play: () => { self.plays += 1; self.paused = false; return Promise.resolve(); },
    pause: () => { self.paused = true; },
    load: () => {}
  };
  Object.defineProperty(self, 'offsetLeft', {get: () => px(self.style.left)});
  Object.defineProperty(self, 'offsetTop', {get: () => px(self.style.top)});
  Object.defineProperty(self, 'offsetWidth', {get: () => px(self.style.width)});
  Object.defineProperty(self, 'offsetHeight', {get: () => px(self.style.height)});
  /* A REAL SCROLLER, not a number that accepts anything. The whole of
     "keeps his place when a page lands at the left" is arithmetic against
     a clamped scrollLeft, and a stub that stored 1e7 would let a broken
     correction pass. Every child is one tile wide; that is close enough to
     the flex row the strip actually is, and it is the same number the
     module measures rather than assumes. */
  Object.defineProperty(self, 'clientWidth', {get: () => VIEW_PX});
  Object.defineProperty(self, 'scrollWidth',
                        {get: () => self.children.length * TILE_PX});
  Object.defineProperty(self, 'scrollLeft', {
    get: () => scroll,
    set: (v) => {
      const most = Math.max(0, self.scrollWidth - self.clientWidth);
      const next = Math.max(0, Math.min(most, Number(v) || 0));
      if (next === scroll) return;
      scroll = next;
      self.fire('scroll', {});           // the browser's own answer to a move
    }
  });
  return self;
}

function findByClass(from, name, out = []) {
  for (const child of from.children) {
    const named = String(child.className || '').split(/\s+/);
    if (child.classes.has(name) || named.indexOf(name) >= 0) out.push(child);
    findByClass(child, name, out);
  }
  return out;
}

function world() {
  const store = new Map();
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
  delete globalThis.pineIcon;
  return {body, store};
}

/* The station, answering both roads this module asks: the cycle's own
   /api/dj/video, and #1200's history. `pages` is a list of answers handed
   out in order, so a test says exactly what the second ask gets. */
function station(pages, opts) {
  const asked = [];
  let turn = 0;
  globalThis.pineDesktop = {
    get: async (route) => {
      asked.push(route);
      if (String(route).indexOf('/api/sfx/history') === 0) {
        if (opts && opts.fail) throw new Error(String(opts.fail));
        const page = pages[Math.min(turn, pages.length - 1)];
        turn += 1;
        if (page && page.throw) throw new Error(page.throw);
        return page || {rows: [], more: false};
      }
      return {server_ms: Date.now(), cut_ms: 0, clips: []};
    },
    post: async () => ({ok: true})
  };
  return {asked, turn: () => turn};
}

/* EVERY SET THIS FILE HAS EVER MOUNTED, so that all of them are stopped
 * at the end however a test ended. mount() starts a setInterval(poll), and
 * an assertion that fires before its own tv.stop() leaves that interval
 * running on a module instance nobody holds any more - node then waits for
 * an event loop that will never empty, and the whole suite hangs with the
 * failure already printed. Measured exactly that way while writing this
 * file: one failing assertion, eleven passing tests, and a run that never
 * returned. A test file that can hang the suite is worse than no test. */
const mounted = [];
after(() => {
  for (const one of mounted) {
    try { one.stop(); } catch (err) { /* already down */ }
  }
});

function load() {
  delete require.cache[require.resolve('../desktop/renderer/sfx-tv.js')];
  require('../desktop/renderer/sfx-tv.js');
  mounted.push(globalThis.PineSfxTv);
  return globalThis.PineSfxTv;
}

/* A page of the ledger, newest first, exactly as the station sends it:
   whole-second ts, a name with its real suffix on it, and #1200's `video`
   flag beside it. */
function ledger(from, many, over) {
  const rows = [];
  for (let i = 0; i < many; i += 1) {
    const n = from - i;
    rows.push(Object.assign({
      ts: n,
      id: 'id' + n,
      name: 'clip-' + n + '.mp4',
      who: 'gap',
      plays: 1,
      weight: 1.0,
      banned: false,
      video: true,
      url: '/sfx/id' + n + '?t=sig' + n
    }, over || {}));
  }
  return rows;
}

function page(from, many, more, over) {
  return {rows: ledger(from, many, over), more: !!more,
          oldest: from - many + 1, newest: from};
}

function openStrip(tv) {
  const say = [];
  const strip = tv.strip(null, (word) => say.push(String(word)));
  return {strip, say};
}

/* A wheel, as a browser sends one. Negative deltaY is "away from me",
   which on a horizontal strip is backwards into the past. */
function wheel(strip, deltaY, deltaX) {
  let stopped = 0;
  let prevented = 0;
  strip.fire('wheel', {
    deltaY: deltaY || 0,
    deltaX: deltaX || 0,
    deltaMode: 0,
    preventDefault() { prevented += 1; },
    stopPropagation() { stopped += 1; }
  });
  return {prevented, stopped};
}

function note(strip) {
  return findByClass(strip, 'sfx-tv-oldend')[0] || null;
}

function noteWords(strip) {
  const box = note(strip);
  if (!box) return '';
  const word = findByClass(box, 'sfx-tv-oldword')[0];
  return String((word && word.textContent) || '');
}

function tiles(strip) { return findByClass(strip, 'sfx-tv-hist'); }

/* --------------------------------------------------------- the tests */

test('#1200: the wheel scrolls the strip, and never the sheet under it',
     async () => {
  world();
  station([page(9000, HIST_PAGE, true)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);

  /* Something to scroll: one page in, drawn. */
  wheel(strip, -400);
  await wait(40);
  assert.ok(tiles(strip).length >= HIST_PAGE - 1,
            'the first page never drew: ' + tiles(strip).length + ' tiles');

  strip.scrollLeft = 300;
  const was = strip.scrollLeft;
  const rolled = wheel(strip, 240);
  assert.ok(strip.scrollLeft > was,
            'the wheel did not move the strip: ' + was + ' -> ' + strip.scrollLeft);
  /* THE HALF THAT FAILS SILENTLY. Without these the sheet - which is
     overflow-y:auto where it opens over the LISTEN wall - or the page
     underneath takes the gesture instead. */
  assert.equal(rolled.prevented, 1, 'the wheel was handed to the page underneath');
  assert.equal(rolled.stopped, 1, 'the wheel was handed to the sheet underneath');

  /* A trackpad's SIDEWAYS gesture is deltaX and must work the same. */
  const sideways = strip.scrollLeft;
  wheel(strip, 0, 160);
  assert.ok(strip.scrollLeft > sideways, 'a trackpad gesture did nothing');
  tv.stop();
});

test('#1200: reaching the old end asks the station for a page and appends it',
     async () => {
  world();
  const box = station([page(9000, HIST_PAGE, true)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);
  assert.equal(tiles(strip).length, 0, 'the strip fetched before he touched it');

  wheel(strip, -400);
  await wait(40);

  const asks = box.asked.filter((r) => String(r).indexOf('/api/sfx/history') === 0);
  assert.equal(asks.length, 1, 'asked ' + asks.length + ' times for one reach');
  /* The exact road, because the wrong one answers 200 with the wrong rows. */
  assert.equal(asks[0], '/api/sfx/history?limit=' + HIST_PAGE);
  assert.equal(tiles(strip).length, HIST_PAGE,
               'the page was fetched and not drawn');
  assert.equal(tv.history().length, HIST_PAGE);

  /* OLDEST ON THE LEFT. The station sends newest first; the strip runs
     the other way, and a page inserted in wire order would read
     backwards without anything reporting it. */
  const drawn = tiles(strip);
  const first = tv.history()[0];
  assert.equal(first.id, 'id' + (9000 - HIST_PAGE + 1),
               'the oldest row is not at the left of the strip');
  assert.ok(String(drawn[0].title).indexOf('clip-' + (9000 - HIST_PAGE + 1)) >= 0,
            'the leftmost tile is not the oldest one: ' + drawn[0].title);

  /* AND THE NEXT ASK CARRIES THE CURSOR. Without `before` the station can
     only answer the same page again, which is what #1200 was for. */
  strip.scrollLeft = 0;
  wheel(strip, -400);
  await wait(40);
  const next = box.asked.filter((r) => String(r).indexOf('/api/sfx/history') === 0);
  assert.equal(next[1],
               '/api/sfx/history?limit=' + HIST_PAGE + '&before=' + (9000 - HIST_PAGE + 1));
  tv.stop();
});

test('#1200: a second page keeps the tiles already drawn and adds no duplicates',
     async () => {
  world();
  /* `before` is INCLUSIVE, so the station ALWAYS hands the boundary row
     back - and here it hands back four of them, which is what a second
     that carried four airings looks like. Not one of them may appear
     twice in the strip. */
  const first = page(9000, HIST_PAGE, true);
  const second = {rows: ledger(9000 - HIST_PAGE + 4, HIST_PAGE, {}), more: true};
  world();
  const box = station([first, second]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);

  wheel(strip, -400);
  await wait(40);
  const after1 = tiles(strip).length;
  const ids1 = tv.history().map((r) => r.id);

  strip.scrollLeft = 0;
  wheel(strip, -400);
  await wait(40);

  const rows = tv.history();
  const ids = rows.map((r) => r.key);
  assert.equal(new Set(ids).size, ids.length,
               'the second page repeated rows the first had already drawn');
  assert.equal(rows.length, HIST_PAGE + (HIST_PAGE - 4),
               'expected ' + (HIST_PAGE * 2 - 4) + ' rows, got ' + rows.length);
  assert.equal(tiles(strip).length, rows.length,
               'the tiles and the rows disagree');
  assert.ok(tiles(strip).length > after1, 'the second page drew nothing');

  /* KEPT, not rebuilt: every id from the first page is still there. */
  const now = new Set(rows.map((r) => r.id));
  for (const id of ids1) {
    assert.ok(now.has(id), 'the second page threw away ' + id);
  }
  assert.ok(box.turn() >= 2);
  tv.stop();
});

test('#1200: the strip keeps his place when a page lands at the left',
     async () => {
  world();
  station([page(9000, HIST_PAGE, true), page(8000, HIST_PAGE, true)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);
  wheel(strip, -400);
  await wait(40);

  strip.scrollLeft = 0;
  const wide = strip.scrollWidth;
  wheel(strip, -400);
  await wait(40);
  const grew = strip.scrollWidth - wide;
  assert.ok(grew > 0, 'nothing was prepended');
  /* PREPENDING MOVES THE VIEW. Tiles put in at the left push what he is
     looking at to the right by exactly their width; scrollLeft is measured
     from the left, so without the correction the strip jumps and he loses
     his place mid-flick. Nothing on screen reports that. */
  assert.equal(strip.scrollLeft, grew,
               'the strip jumped: scrollLeft ' + strip.scrollLeft + ' for ' + grew + 'px of new tiles');
  tv.stop();
});

test('#1200: the end of the history says so, and stops asking', async () => {
  world();
  const box = station([page(9000, 5, false)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);

  assert.equal(noteWords(strip), 'scroll back for more',
               'the strip did not offer the history at all');

  wheel(strip, -400);
  await wait(40);
  assert.equal(tv.histState().more, false);
  assert.equal(noteWords(strip), 'that is the whole history - nothing older');

  /* AND IT DOES NOT SPIN. Rolling again asks nothing, because there is
     nothing to ask for - a strip that keeps firing at the end of the
     ledger is a request every frame at a road that reads a file. */
  const before = box.asked.length;
  strip.scrollLeft = 0;
  wheel(strip, -400);
  await wait(40);
  assert.equal(box.asked.length, before, 'it kept asking past the end');
  tv.stop();
});

test('#1200: a page that fails says so, and does NOT look like the end',
     async () => {
  world();
  const box = station([{throw: 'the station would not answer'},
                       page(9000, HIST_PAGE, true)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);

  wheel(strip, -400);
  await wait(60);

  const said = noteWords(strip);
  assert.ok(said.indexOf('did not arrive') >= 0,
            'a failed page said: ' + JSON.stringify(said));
  assert.notEqual(said, 'that is the whole history - nothing older');
  assert.equal(tv.histState().bad, true);
  /* THE HALF THAT MATTERS. A failure that set `more` false would teach
     him there is no more history when there is - and would never ask
     again for the rest of the night. */
  assert.equal(tv.histState().more, true,
               'a failed page was recorded as the end of the ledger');

  /* So the next reach tries again, and this time it lands. */
  const before = box.asked.length;
  strip.scrollLeft = 0;
  wheel(strip, -400);
  await wait(60);
  assert.ok(box.asked.length > before, 'it never tried again after a failure');
  assert.equal(tiles(strip).length, HIST_PAGE);
  assert.equal(tv.histState().bad, false);
  tv.stop();
});

test('#1200: no more than two posters are ever in flight', async () => {
  world();
  station([page(9000, HIST_PAGE, true)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);
  wheel(strip, -400);
  await wait(40);

  /* The station's poster road renders behind a semaphore of two. A page
     of twenty-four tiles that set their src together is a queue
     twenty-two deep with an ffmpeg at the front of it, and nothing on
     screen says so - the tiles are simply dark for a long time. */
  assert.equal(tv.shotsInFlight(), 2,
               'in flight: ' + tv.shotsInFlight() + ' (the station serves two)');
  assert.ok(tv.shotsWaiting() > 0, 'nothing is waiting its turn');
  assert.equal(tv.shotsInFlight() + tv.shotsWaiting(), HIST_PAGE,
               'a tile went missing between the queue and the wire');

  /* And it DRAINS - two more take their place as each lands, and it never
     climbs above two on the way through. */
  const shot = [];
  for (const tile of tiles(strip)) {
    for (const kid of tile.children) {
      for (const g of kid.children) if (g.tag === 'img') shot.push(g);
    }
  }
  assert.equal(shot.length, HIST_PAGE, 'a tile has no picture element');
  let live = 0;
  for (const img of shot) {
    if (!img.src) continue;
    img.fire('load', {});
    live = Math.max(live, tv.shotsInFlight());
    assert.ok(tv.shotsInFlight() <= 2,
              'the queue let ' + tv.shotsInFlight() + ' through at once');
  }
  assert.equal(live, 2, 'the queue never ran two at a time');

  /* THE PICTURE IS A FRAME, NOT THE SOUNDTRACK (#1199, which #1200 must
     not undo). Every one of these went to the poster road; a single
     /api/sfx/spec/ here is a spectrogram of an mp4 - a drawing of its
     audio - which is exactly what the operator was shown before #1199. */
  for (const img of shot) {
    assert.ok(String(img.src).indexOf('/api/sfx/poster/') > 0,
              'a history tile asked ' + img.src);
  }
  tv.stop();
});

test('#1200: the video flag comes off the STATION, and falls back to the name',
     async () => {
  world();
  /* An older station that has not taken the server half of #1200 sends no
     flag at all. The fallback reads the row's NAME - which
     sfx_history_add() records as `path.name`, a real filename with a real
     suffix - and NEVER the url, which has none and never could answer.
     That is #1199's whole lesson and this asserts it did not come back. */
  station([{rows: [
    {ts: 9000, id: 'vid', name: 'a clip.mp4', url: '/sfx/vid?t=s1'},
    {ts: 8999, id: 'snd', name: 'a horn.mp3', url: '/sfx/snd?t=s2'},
    {ts: 8998, id: 'said', name: 'told.wav', url: '/sfx/said?t=s3', video: true}
  ], more: false}]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);
  wheel(strip, -400);
  await wait(40);

  const by = {};
  for (const row of tv.history()) by[row.id] = row;
  assert.equal(by.vid.video, true, 'an .mp4 was read as audio');
  assert.equal(by.snd.video, false, 'an .mp3 was read as a picture');
  /* And where the station DOES say, the station wins - even against the
     name, because it owns the list of what counts as a picture. */
  assert.equal(by.said.video, true, 'the station was overruled by a suffix');
  tv.stop();
});

test('#1200: the ceiling holds, and says where it cut', async () => {
  world();
  /* Six pages of twenty-four is a hundred and forty-four rows against a
     ceiling of a hundred and twenty. #1312's note in sfx-tv.js is why
     there is a ceiling at all: a strip that grows for ever is fine for
     twenty minutes and then every request on the page hangs. */
  const pages = [];
  for (let i = 0; i < 8; i += 1) {
    pages.push(page(9000 - (i * HIST_PAGE), HIST_PAGE, true));
  }
  station(pages);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip, say} = openStrip(tv);

  for (let i = 0; i < 6; i += 1) {
    strip.scrollLeft = 0;
    wheel(strip, -400);
    await wait(40);
  }

  const held = tv.history().length;
  assert.equal(held, HIST_MOST,
               'the strip holds ' + held + ' rows against a ceiling of ' + HIST_MOST);
  assert.equal(tiles(strip).length, HIST_MOST,
               'the rows were cut but the tiles were not: ' + tiles(strip).length);
  assert.ok(tv.histState().lost > 0, 'nothing was let go and yet it fits');

  /* IT IS NOT DONE QUIETLY. A gap nobody is told about is the kind of
     thing this station treats as a fault in its own right. */
  const seam = findByClass(strip, 'sfx-tv-seam')[0];
  assert.ok(seam, 'the ceiling cut and said nothing');
  const word = findByClass(seam, 'sfx-tv-oldword')[0];
  assert.ok(String(word.textContent).indexOf('newer let go') > 0,
            'the seam reads: ' + word.textContent);
  assert.ok(String(seam.title).indexOf('back to now') > 0
            || String(seam.title).indexOf('start again from now') > 0,
            'the seam does not say what pressing it does');

  /* AND THE POSTER CACHE IS BOUND TO THE ROWS. There is no other road
     that grows it, so a row let go takes its picture with it.
     MEASURED HERE, and it was not true when this line was first written:
     the `shots` map held the hundred and twenty rows it should, and the
     LINE held a hundred and forty-two - every row the ceiling had let go
     was still standing in it, marked dropped, waiting for the pump to
     walk past it. Nothing on screen would ever have said so, because the
     line drains by itself as pictures land and only grows without bound
     when pages arrive faster than the station renders them - which is
     exactly what a flick does. shotSweep() is the cure and this is the
     meter for it.
     The two it is allowed over the ceiling are the two IN FLIGHT: a
     request the station has already begun is left to land rather than
     cancelled, because cancelling it wastes an ffmpeg that is already
     running - so the true bound is the ceiling plus the semaphore, and
     saying that out loud is better than a round number that happens to
     hold. */
  assert.ok(tv.shotsInFlight() + tv.shotsWaiting() <= HIST_MOST + 2,
            'the queue outlived the rows it was for: '
            + (tv.shotsInFlight() + tv.shotsWaiting()) + ' for ' + held + ' rows');

  /* Pressing it puts the strip back at now, which is the way out. */
  seam.fire('click', {stopPropagation() {}});
  assert.equal(tv.history().length, 0, 'back to now kept the history');
  assert.equal(tv.histState().lost, 0);
  assert.equal(findByClass(strip, 'sfx-tv-seam').length, 0,
               'the seam stayed after it had been used');
  assert.ok(say.join(' ').indexOf('back at now') >= 0,
            'nothing was said when the strip was reset');
  tv.stop();
});

test('#1200: opening the strip asks for nothing, and shows now', async () => {
  world();
  const box = station([page(9000, HIST_PAGE, true)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);
  await wait(40);
  /* The strip is at scrollLeft 0 the moment it is built, so a naive
     "at the old end -> fetch" would ask the station for twenty-four
     ffmpeg renders every single time he right-clicks the picture. The
     gesture is what asks. */
  const asks = box.asked.filter((r) => String(r).indexOf('/api/sfx/history') === 0);
  assert.equal(asks.length, 0, 'opening the sheet fetched a page nobody wanted');
  assert.ok(note(strip), 'there is no note at the old end');
  assert.equal(strip.children[0], note(strip),
               'the note is not at the old end of the strip');
  tv.stop();
});

test('#1200: a history tile opens the same sheet a played tile does',
     async () => {
  world();
  station([page(9000, 3, false)]);
  const tv = load();
  tv.mount({baseUrl: 'http://box:8096'});
  await wait(40);
  const {strip} = openStrip(tv);
  wheel(strip, -400);
  await wait(40);

  const tile = tiles(strip)[0];
  assert.equal(tile.tag, 'button',
               'a tile must be a real button: hot-corners.js walks up from the '
               + 'press and finds the tag, so a tap in a corner is never also '
               + 'a corner gesture');
  /* A clip out of the ledger is a clip that has already gone out, which
     is exactly what a `heard` tile is - so the tap is the same tap, and
     the sheet it opens already grows a Play it for a clip that is not on
     the tube. Nothing had to be added and a second behaviour would have
     been the fault. */
  assert.ok(String(tile.title).indexOf('tap to open its menu') > 0,
            'a history tile offers something else: ' + tile.title);
  /* And it says WHEN, because "played" on a hundred and twenty tiles
     tells him nothing he could not see from where the tile sits. */
  const when = tile.children[0].children.filter((k) => k.tag === 'i')[0];
  assert.ok(/ago$/.test(String(when.textContent)),
            'the tile says ' + JSON.stringify(when.textContent));
  tv.stop();
});
