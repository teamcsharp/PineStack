/* THE ORCHESTRATOR GLASS: THAT IT DRAWS THE REAL PAYLOAD, THAT A TRIANGLE
 * OPENS, AND THAT A CLOSED POP-UP ASKS FOR NOTHING. (#1191)
 *
 * "I want to be able to access a pop-up that gives me advanced information
 *  about how the orchestrator is behaving in the background... I want to be
 *  able to expand each element with a triangle and basically see additional
 *  information about that element that the orchestrator is working towards."
 *
 * Three things about this would fail SILENTLY, which is why they are tested
 * rather than commented:
 *
 * 1. THE PAYLOAD IS NOT DRAWN. Every pane in this pop-up is built by ONE
 *    painter, and a single throw in the middle of it leaves the panes after
 *    it blank with nothing anywhere reporting a fault - which is exactly how
 *    an undeclared `feedDrawn` once emptied five panes of the presentation
 *    view at once while the view's own budget line read "0 asking". So the
 *    test feeds it a payload shaped like the live one and asserts the words
 *    actually reach the DOM.
 *
 * 2. A TRIANGLE THAT DOES NOT OPEN. The fold body is built LAZILY, so a
 *    fold that never opens is a fold whose content was never built and never
 *    ran - a whole feature can be missing and the panel looks perfect. The
 *    test presses the triangle and asserts the arithmetic behind the number
 *    is now on the page, including the AT ITS CAP marking, which is the one
 *    thing the operator most needs to notice.
 *
 * 3. A CLOSED POP-UP THAT KEEPS POLLING. A timer left alive behind a removed
 *    node is a poll nobody can see and nobody can stop, and this panel has
 *    been starved before by exactly that shape of surface - on the tablet's
 *    400 kB/s link a 2.4 kB route was measured waiting 19 s behind six full
 *    sockets. The test counts the requests, closes the pop-up, lets several
 *    poll periods pass, and asserts the count did not move.
 *
 * There is no jsdom in this repo, so the DOM calls this module actually
 * makes are stubbed just far enough to run it for real.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');

function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

/* ---------------------------------------------------------- the stubs */

function makeNode(tag) {
  const self = {
    tag,
    id: '',
    className: '',
    textContent: '',
    hidden: false,
    parentNode: null,
    children: [],
    style: {},
    handlers: {},
    classes: new Set(),
    attrs: {},
    innerHTML_: '',
    classList: {
      add: (n) => self.classes.add(n),
      remove: (n) => self.classes.delete(n),
      contains: (n) => self.classes.has(n),
      toggle: (n, on) => { if (on) self.classes.add(n); else self.classes.delete(n); }
    },
    setAttribute: (k, v) => { self.attrs[k] = String(v); },
    getAttribute: (k) => (k in self.attrs ? self.attrs[k] : null),
    removeAttribute: (k) => { delete self.attrs[k]; },
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
    /* [#1186] reconcile() puts a node back in its place rather than rebuilding
       the list, so the fake DOM has to be able to hold an order. */
    insertBefore: (child, mark) => {
      self.children = self.children.filter((one) => one !== child);
      const at = mark ? self.children.indexOf(mark) : -1;
      if (at < 0) self.children.push(child); else self.children.splice(at, 0, child);
      child.parentNode = self;
      return child;
    },
    contains: (other) => {
      for (let walk = other; walk; walk = walk.parentNode) if (walk === self) return true;
      return false;
    },
    removeChild: (child) => {
      self.children = self.children.filter((one) => one !== child);
      child.parentNode = null;
      return child;
    },
    /* The module only ever assigns '' to innerHTML (to clear a pane) or a
       sprite string (for an icon). Clearing must really clear, or the test
       would see stale rows from the previous paint and pass for the wrong
       reason. */
    querySelector: (sel) => findByClass(self, String(sel).replace(/^\./, ''))[0] || null
  };
  /* [#1186] AN innerHTML THAT MEANS SOMETHING. refold() asks "is this body the
     same body" by comparing innerHTML, and the old getter handed back a stored
     string that is '' for every node built by appendChild - so every body would
     have compared equal and the reconcile cases below would have passed while
     doing nothing at all. This serialises what is actually there. */
  function shape(node) {
    return node.children.map((c) => '<' + c.tag
      + ' c="' + String(c.className || '') + '"'
      + ' f="' + String(c.getAttribute('data-fold') || '') + '"'
      + ' h="' + (c.hidden ? 1 : 0) + '"'
      + '>' + String(c.textContent || '') + shape(c) + '</' + c.tag + '>').join('');
  }
  Object.defineProperty(self, 'innerHTML', {
    get: () => (self.innerHTML_ ? self.innerHTML_ : shape(self)),
    set: (v) => {
      self.innerHTML_ = String(v);
      if (String(v) === '') { for (const c of self.children) c.parentNode = null; self.children = []; }
    }
  });
  Object.defineProperty(self, 'scrollTop', {get: () => 0, set: () => {}});
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

/* Every string of text anywhere under a node, joined. The assertions below
 * ask "is this fact on the screen at all", which is the question that
 * matters - not which particular element happens to carry it. */
function words(from, out = []) {
  if (from.textContent) out.push(String(from.textContent));
  for (const child of from.children) words(child, out);
  return out.join(' | ');
}

function world() {
  const store = new Map();
  const body = makeNode('body');
  globalThis.document = {createElement: makeNode, body, readyState: 'complete',
    addEventListener: () => {}};
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k)
  };
  globalThis.innerWidth = 1600;
  globalThis.innerHeight = 900;
  globalThis.addEventListener = () => {};
  globalThis.location = {protocol: 'file:'};
  /* No icons on this surface: pineIcon is deliberately absent so the test
     also proves the guard - a missing sprite must cost a blank span and
     never the panel. */
  delete globalThis.pineIcon;
  delete globalThis.PineDuck;
  delete globalThis.PineCorners;
  return {body, store};
}

/* A payload shaped exactly like /api/orchestrator/glass, carrying the real
 * caller-road numbers measured on the live station on 2026-09-15 - the ones
 * the operator asked to have explained. */
function payload(over) {
  return Object.assign({
    at: Date.now() / 1000,
    on: true,
    paused: false,
    boot_at: (Date.now() / 1000) - 15480,
    up_seconds: 15480,
    tail_depth: 3,
    tail_most: 240,
    oldest_at: (Date.now() / 1000) - 900,
    plan_why: 'last half hour lost 431s of air across 8 gap(s), longest 96s',
    face: {mood: 'thinking', say: 'Writing the next one.',
           why: 'the writing desk has a round on the go',
           brief: 'the shelf is short on callers', console: []},
    keepers: [
      {name: 'coordinator', turns: 1032, acted: 44, at: Date.now() / 1000,
       quiet_for: 3.2, per_minute: 4.0, say: 'closing the books',
       systems: [{system: 'the planner', calls: 44}]},
      {name: 'larder_keeper', turns: 5160, acted: 210, at: Date.now() / 1000,
       quiet_for: 1.1, per_minute: 20, say: 'keeping a written round ready',
       systems: [{system: 'the writing model', calls: 210}]}
    ],
    live: [
      {keeper: 'larder_keeper', turn: 5160, at: Date.now() / 1000, ms: 240,
       say: 'keeping a written round always ready', open: true,
       steps: [{kind: 'model', text: 'asked for a fresh banter round',
                has_extra: true, at: Date.now() / 1000}],
       systems: [{system: 'the writing model', calls: 1, note: 'qwen3:30b'}]}
    ],
    recent: [
      {keeper: 'coordinator', turn: 1031, at: (Date.now() / 1000) - 60, ms: 88,
       say: 'closing the books and writing the work order',
       steps: [{kind: 'lookahead',
                text: 'the coordinator closed 08:00 - last half hour lost '
                      + '431s of air across 8 gap(s)',
                has_extra: false, at: (Date.now() / 1000) - 60}],
       systems: [{system: 'the planner', calls: 1, note: 'coord_plan'},
                 {system: 'the commission desk', calls: 1, note: ''}]}
    ],
    roads: [{
      road: 'caller', label: 'Phone calls',
      asked_seconds: 45753.6, due_in: 480, bare: true,
      estimate_seconds: 1000.5,
      why: 'it is 3703s short of what the coming entries call for',
      learning: {factor: 3.0, hours: 187, miss_streak: 71,
                 success_streak: 0, attainment_ema: 0.3127},
      learning_factor: 3.0, judgment_factor: 2.0,
      chain: [
        {name: 'the shortfall', value: 3703.3, unit: 's',
         rule: 'owed over the horizon, minus what is held, plus any dead '
               + 'air this road bled',
         inputs: [{name: 'owed', value: 4320.0, unit: 's'},
                  {name: 'held', value: 616.7, unit: 's'},
                  {name: 'bled last half hour', value: 0.0, unit: 's'}]},
        {name: 'closed-hour miss premium', factor: 3.0, was: 7626.6,
         value: 22879.8, unit: 's', cap: 3.0, capped: true,
         rule: 'raised each closed hour this road missed its requirement, '
               + 'decayed 10% each hour it met it, bounded to 3.00',
         inputs: [{name: 'closed hours', value: 187},
                  {name: 'consecutive misses', value: 71},
                  {name: 'consecutive successes', value: 0},
                  {name: 'attainment (moving average)', value: 0.3127}]},
        {name: "the operator's standing judgment", factor: 2.0,
         was: 22879.8, value: 45759.6, unit: 's', cap: 2.0, floor: 0.5,
         capped: true,
         rule: 'the weight this road’s answers earned in the judgment '
               + 'book, bounded to 0.50-2.00',
         inputs: [{name: 'the lesson on the book', value: 'keep pushing it'},
                  {name: 'answered alone', value: true}]}
      ],
      granted: null,
      refused: {wanted_items: 308, want_seconds: 45753.6, each_seconds: 6379.3,
                odds: 0.157,
                why: 'one finished a phone call measures 6379s of room '
                     + '(1000s a try at 16% odds, measured) and 234s is left '
                     + 'of the 900s this half hour may spend'}
    }],
    commission: {mode: 'trace', budget_seconds: 900, asked_seconds: 50920,
                 asked_items: 308, items: 0, spent_seconds: 666,
                 left_seconds: 234, say: 'traced, nothing dispatched'},
    coverage: {
      loops_measured: 75, loops_seen: 15, ticks_seen: 4, persisted: false,
      say: 'This register is held in memory only and starts empty at every '
           + 'restart. It stamps 15 of the 75 timer loops in this station '
           + 'and 4 orchestration ticks; supporting systems are recorded at '
           + '7 named doors. Anything not named here is UNMEASURED, which '
           + 'is not the same as idle.',
      seen: [{name: 'coordinator', what: 'closes the half hour',
              when: 'every COORD_TICK'}],
      blind: [{group: 'the show’s own clocks',
               names: '_radio_loop, _dj_loop, dj_show, caller_clock'}],
      doors: [{system: 'the writing model', where: 'call_ollama'}]
    }
  }, over || {});
}

/* The station, counted. Every request this module makes lands here. */
function station(answer) {
  const asked = [];
  globalThis.pineDesktop = {
    get: async (route) => { asked.push(route); return answer; }
  };
  return asked;
}

function load() {
  delete require.cache[require.resolve('../desktop/renderer/orchestrator-glass.js')];
  require('../desktop/renderer/orchestrator-glass.js');
  return globalThis.PineOrchGlass;
}

function foldNamed(body, title) {
  for (const fold of findByClass(body, 'og-fold')) {
    const head = findByClass(fold, 'og-tri-title')[0];
    if (head && String(head.textContent).indexOf(title) >= 0) return fold;
  }
  return null;
}

function press(fold) {
  const head = findByClass(fold, 'og-tri')[0] || fold.children[0];
  head.fire('click', {});
}

/* --------------------------------------------------------- the tests */

test('the pop-up is a child of the body, never of a view', async () => {
  const {body} = world();
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];
  assert.ok(node, 'the pop-up did not open');
  /* THE WHOLE POINT: a sibling of <main>. Every view in that window goes
     display:none the moment another tab is chosen, and three of them are
     webviews with documents of their own. */
  assert.equal(node.parentNode, body);
  glass.close();
});

test('it draws a real payload - the task list, in order, and what it summoned', async () => {
  const {body} = world();
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];
  const said = words(node);

  /* Glyphy is on the head as a real button, and he is SAYING something the
     server measured rather than a decoration. */
  const avatar = findByClass(node, 'og-avatar')[0];
  assert.ok(avatar, 'Glyphy is not on the pop-up');
  assert.equal(avatar.tag, 'button', 'Glyphy must be a control, not a picture');
  assert.match(said, /Writing the next one\./);

  /* The five panes are all present. An absent pane is the failure this
     whole test file exists for. */
  assert.ok(foldNamed(body, 'being pursued right now'), 'no "now" pane');
  assert.ok(foldNamed(body, 'what it has been doing, in order'), 'no order pane');
  assert.ok(foldNamed(body, 'what it is asking the station for'), 'no roads pane');
  assert.ok(foldNamed(body, 'the keepers'), 'no keepers pane');
  assert.ok(foldNamed(body, 'what this panel cannot see'), 'no blind-spot pane');

  glass.close();
});

test('a triangle expands into the arithmetic, and names the input at its cap', async () => {
  const {body} = world();
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);

  /* Nothing under a closed triangle has been BUILT yet - that is the point
     of the lazy body, and it is also how a whole feature can be missing
     while the panel looks perfect. */
  const roads = foldNamed(body, 'what it is asking the station for');
  assert.equal(words(roads).indexOf('6379'), -1,
    'the arithmetic was drawn before its triangle was pressed');

  press(roads);
  const caller = foldNamed(roads, 'Phone calls');
  assert.ok(caller, 'the caller road is not listed');
  press(caller);

  const shown = words(caller);

  /* THE WORKING, with every input named and its own value shown. */
  assert.match(shown, /the shortfall/);
  assert.match(shown, /owed/);
  assert.match(shown, /4,320/, 'the owed seconds are not on the screen');
  assert.match(shown, /616\.7|617/, 'the held seconds are not on the screen');
  assert.match(shown, /closed-hour miss premium/);
  assert.match(shown, /consecutive misses/);
  assert.match(shown, /71/, 'the 71-miss streak is not on the screen');

  /* AND THE THING THAT MATTERS MOST: a multiplier pinned at its ceiling
     carries no information, and the screen has to SAY so. */
  assert.match(shown, /AT ITS CAP/,
    'a multiplier is sitting on its ceiling and the screen does not say so');
  const capped = findByClass(caller, 'og-capped');
  assert.ok(capped.length >= 2,
    'both saturated links should be marked, saw ' + capped.length);

  /* ASKED AGAINST GRANTED, side by side, and the sentence that refused it. */
  assert.match(shown, /asked/);
  assert.match(shown, /granted/);
  assert.match(shown, /nothing/, 'a refused road must say nothing was granted');
  assert.match(shown, /234s is left of the 900s/,
    'the refusal sentence is not on the screen');

  glass.close();
});

test('the blind spots are printed, not implied', async () => {
  const {body} = world();
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);
  const blind = foldNamed(body, 'what this panel cannot see');
  /* The summary is visible without opening anything: a person must not have
     to go looking to find out how much of the station this cannot see. */
  const sum = findByClass(blind, 'og-tri-sum')[0];
  assert.match(String(sum.textContent), /15 of 75/);

  press(blind);
  const shown = words(blind);
  assert.match(shown, /UNMEASURED/);
  assert.match(shown, /memory only|lost at restart/);
  assert.match(shown, /_dj_loop/, 'the unseen loops are not named');
  glass.close();
});

test('an empty register says why it is empty instead of looking idle', async () => {
  const {body} = world();
  station(payload({recent: [], live: [], roads: [], keepers: [],
                   tail_depth: 0, oldest_at: 0}));
  const glass = load();
  glass.open();
  await wait(30);
  const order = foldNamed(body, 'what it has been doing, in order');
  press(order);
  assert.match(words(order), /starts empty at every restart/,
    'an empty list must explain itself, not be left to be misread');
  glass.close();
});

test('the SAYING line steps through what he is saying and why', async () => {
  /* [#1213] the stepping moved off the face when the face became the fold. */
  const {body} = world();
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];
  const say = findByClass(node, 'og-say')[0];
  const text = findByClass(node, 'og-say-text')[0];
  assert.equal(String(text.textContent), 'Writing the next one.');
  say.fire('click', {});
  assert.equal(String(text.textContent), 'the writing desk has a round on the go',
    'pressing the line must show the MEASUREMENT that put him in this mood');
  say.fire('click', {});
  assert.equal(String(text.textContent), 'the shelf is short on callers');
  glass.close();
});

test('[#1213] pressing his face folds the panel to the pill, and it is remembered', async () => {
  const {body, store} = world();
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];
  const avatar = findByClass(node, 'og-avatar')[0];
  const list = findByClass(node, 'og-main')[0];

  assert.equal(glass.isFolded(), false, 'it must open out, not folded');
  assert.ok(list.children.length > 0, 'the list should be drawn before it folds');

  avatar.fire('click', {});
  assert.equal(glass.isFolded(), true, 'pressing his face must fold the panel');
  assert.ok(node.classes.has('og-min'), 'the pill needs its class');
  assert.equal(list.hidden, true, 'a folded panel must not show the list');
  assert.equal(store.get('pineOrchGlassMin'), '1', 'the fold must be remembered');
  /* The face, the badges and the one line he is saying all stay. */
  assert.equal(findByClass(node, 'og-say-text').length, 1);
  assert.equal(findByClass(node, 'og-face').length, 1);

  avatar.fire('click', {});
  assert.equal(glass.isFolded(), false, 'pressing again must open him out');
  assert.equal(list.hidden, false);
  assert.equal(store.get('pineOrchGlassMin'), '0');
  glass.close();
});

test('[#1186] a newer pass above an open one does not close it or replace it', async () => {
  const {body} = world();
  const first = payload();
  station(first);
  const glass = load();
  glass.open();
  await wait(30);

  const order = foldNamed(body, 'what it has been doing, in order');
  press(order);
  const row = findByClass(order, 'og-fold')[0];
  const key = row.getAttribute('data-fold');
  press(row);
  assert.ok(row.classes.has('open'), 'the pass should be open before the poll');

  /* A newer pass arrives at the TOP of the list, which is what `recent`
     always does. Under the old index-keyed id every row below it changed
     key and closed. */
  const next = payload();
  next.recent = [
    {keeper: 'sfx_guy_watch', turn: 2001, at: (Date.now() / 1000) - 1, ms: 12,
     say: 'a newer pass, above the one he was reading', steps: [], systems: []}
  ].concat(first.recent);
  station(next);
  /* the triangle he just pressed holds the panel for five seconds; the rest
     timer lets the update in as soon as that is up. */
  await wait(glass.EVERY_MS + 2600);

  const again = foldNamed(body, 'what it has been doing, in order');
  const rows = findByClass(again, 'og-fold');
  assert.equal(rows.length, 2, 'both passes should be listed, saw ' + rows.length);
  const kept = rows.filter((one) => one.getAttribute('data-fold') === key)[0];
  assert.ok(kept, 'the pass he was reading lost its identity when one arrived above it');
  assert.ok(kept.classes.has('open'),
    'the pass he had open closed itself when a newer one arrived above it');
  assert.equal(kept, row, 'the open pass was rebuilt rather than kept');
  glass.close();
});

test('[#1186] a hand inside the panel holds the update, and the panel says so', async () => {
  const {body} = world();
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];
  const held = findByClass(node, 'og-held')[0];
  assert.ok(held, 'there must be a line that can admit the panel is behind');
  assert.equal(held.hidden, true, 'nothing is waiting yet');

  /* The pointer comes to rest inside the box. */
  node.fire('pointerenter', {});
  assert.equal(glass._held().inside, true, 'the panel did not notice the hand');

  const moved = payload();
  moved.face = Object.assign({}, moved.face, {say: 'something else entirely'});
  moved.recent = [];
  station(moved);
  await wait(glass.EVERY_MS + 400);

  assert.equal(glass._held().waiting, true, 'the payload should be held, not drawn');
  assert.ok(glass._held().pending >= 1, 'the held payloads should be counted');
  assert.equal(held.hidden, false, 'the panel must say it is holding something');
  assert.match(String(held.textContent), /paused while you read/);
  /* ...and the list he is reading is untouched: the register still has the
     pass in it, although the newest payload has none. */
  const order = foldNamed(body, 'what it has been doing, in order');
  assert.match(String(findByClass(order, 'og-tri-sum')[0].textContent), /passes/,
    'the list was rebuilt under his hand');

  /* The hand leaves, and the diff goes in. */
  node.fire('pointerleave', {});
  await wait(300);
  assert.equal(glass._held().waiting, false, 'the held update never arrived');
  assert.equal(held.hidden, true);
  glass.close();
});

test('A CLOSED POP-UP ASKS FOR NOTHING AT ALL', async () => {
  const {body} = world();
  const asked = station(payload());
  const glass = load();

  /* The face that opens it has no clock of its own either. */
  glass.dot();
  await wait(60);
  assert.equal(asked.length, 0,
    'the launcher asked the station ' + asked.length + ' time(s) before '
    + 'anything was opened');

  glass.open();
  await wait(30);
  const opened = asked.length;
  assert.ok(opened >= 1, 'an open pop-up must ask at least once');

  glass.close();
  assert.equal(findByClass(body, 'og').length, 0, 'the pop-up was not removed');

  /* Several poll periods. A timer left alive behind a removed node is a
     poll nobody can see and nobody can stop. */
  await wait(glass.EVERY_MS * 2 + 200);
  assert.equal(asked.length, opened,
    'a closed pop-up went on polling: ' + (asked.length - opened)
    + ' further request(s) after it was shut');
});

test('a reply that arrives after the close is dropped, not drawn', async () => {
  const {body} = world();
  let release = null;
  globalThis.pineDesktop = {
    get: () => new Promise((r) => { release = () => r(payload()); })
  };
  const glass = load();
  glass.open();
  glass.close();
  /* The station answers a question asked by a pop-up that no longer
     exists. Painting into a detached tree is how a surface leaks. */
  if (release) release();
  await wait(40);
  assert.equal(findByClass(body, 'og').length, 0);
});

test('the duck is tied to READING, not to the window being open', async () => {
  const {body} = world();
  const held = [];
  const freed = [];
  globalThis.PineDuck = {
    REPORT: 0.10, DICTATION: 0.02,
    hold: (name, level) => { held.push({name, level}); return level; },
    release: (name) => { freed.push(name); return 1; }
  };
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);

  /* NOTHING IS DUCKED BY MERELY LOOKING. Measured on 2026-09-15: any
     PineDuck hold makes listen.js tear the endless video wallpaper off the
     screen entirely, because it reads PineDuck.reporting() to decide
     whether the wallpaper may show at all. Holding for the whole time this
     window is up would quiet the station the operator opened it to watch,
     and blank his wallpaper for as long as he watched. */
  assert.equal(held.length, 0,
    'the broadcast was ducked by the pop-up merely being open');

  const roads = foldNamed(body, 'what it is asking the station for');
  press(roads);
  assert.equal(held.length, 1, 'opening a detail did not duck the broadcast');
  assert.equal(held[0].level, 0.10, 'a diagnostic surface ducks to 10%');

  press(roads);                     /* collapsed again */
  assert.equal(freed.length, 1, 'collapsing every detail did not give the sound back');
  glass.close();
});

test('a press on a hot corner is left to the hot corner', async () => {
  const {body} = world();
  const asked = [];
  globalThis.PineCorners = {
    _cornerAt: (x, y) => { asked.push([x, y]); return (x < 24 && y < 24) ? 'tl' : ''; },
    _overControl: () => false
  };
  station(payload());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];
  const head = findByClass(node, 'og-head')[0];
  const was = node.style.left;

  /* A press that begins inside the window's top-left corner box belongs to
     the corner gesture, not to this box's drag - and the test is hot-corners'
     OWN _cornerAt, asked rather than reimplemented. */
  head.fire('pointerdown', {clientX: 5, clientY: 5, target: head, pointerId: 1});
  head.fire('pointermove', {clientX: 200, clientY: 200, pointerId: 1});
  assert.equal(node.style.left, was,
    'the box was dragged by a press that belonged to a hot corner');
  head.fire('pointerup', {pointerId: 1});

  /* And an ordinary press still drags it. */
  head.fire('pointerdown', {clientX: 600, clientY: 400, target: head, pointerId: 2});
  head.fire('pointermove', {clientX: 640, clientY: 430, pointerId: 2});
  assert.notEqual(node.style.left, was, 'the box would not drag at all');
  head.fire('pointerup', {pointerId: 2});
  assert.ok(asked.length > 0, '_cornerAt was never consulted');
  glass.close();
});
