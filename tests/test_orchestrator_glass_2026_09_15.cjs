/* THE ORCHESTRATOR GLASS: THAT IT DRAWS THE REAL PAYLOAD, THAT A TRIANGLE
 * OPENS, AND THAT A CLOSED POP-UP STOPS ITS DETAIL POLL. (#1191)
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
 *    poll periods pass, and asserts the glass route count did not move. The
 *    mascot now keeps a separate recovery watch alive while mounted.
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
  delete globalThis.PineRevive;
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

test('a closed glass stops its detail poll while the mascot keeps recovery watch', async () => {
  const {body} = world();
  const asked = station(payload());
  const glass = load();

  /* The persistent face has a bounded recovery clock of its own. */
  glass.dot();
  await wait(60);
  assert.ok(asked.includes('/api/broadcast/watch'));
  assert.ok(asked.includes('/api/broadcast/health'));
  assert.ok(asked.includes('/api/broadcast/console'));
  assert.equal(asked.filter((route) => route === '/api/orchestrator/glass').length, 0);

  glass.open();
  await wait(30);
  const opened = asked.filter((route) => route === '/api/orchestrator/glass').length;
  assert.ok(opened >= 1, 'an open pop-up must ask at least once');

  glass.close();
  assert.equal(findByClass(body, 'og').length, 0, 'the pop-up was not removed');

  /* Several poll periods. A timer left alive behind a removed node is a
     poll nobody can see and nobody can stop. */
  await wait(glass.EVERY_MS * 2 + 200);
  assert.equal(asked.filter((route) => route === '/api/orchestrator/glass').length, opened,
    'a closed pop-up went on polling its detail route');
});

test('the persistent recovery mascot can be dragged from a corner and still opens recovery', async () => {
  const {body, store} = world();
  const opened = [];
  globalThis.PineRevive = {open: () => opened.push('recovery')};
  globalThis.pineDesktop = {get: async (route) => {
    if (route === '/api/broadcast/watch') return {
      on: true, paused: false, working: true, rung: 'flush the queue',
      say: 'Flushing the queued round now',
      ladder: [{step: 'check sound'}, {step: 'flush the queue'}, {step: 'restart show'}]
    };
    if (route === '/api/broadcast/health') return {stuck: true};
    if (route === '/api/broadcast/console') return {stuck: true, watch_working: true};
    return payload();
  }};
  const glass = load();
  const dot = glass.dot();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'working');
  assert.match(words(dot), /Recovering 2\/3/);
  assert.match(words(dot), /flush the queue/);
  /* It may begin inside a configured corner and still be moved. */
  const startLeft = parseInt(dot.style.left, 10);
  const startTop = parseInt(dot.style.top, 10);
  dot.fire('pointerdown', {clientX: 2, clientY: 898, pointerId: 1, preventDefault: () => {}});
  dot.fire('pointermove', {clientX: 2 + 278 - startLeft, clientY: 898 + 416 - startTop, pointerId: 1});
  dot.fire('pointerup', {pointerId: 1});
  assert.equal(dot.style.left, '278px');
  assert.equal(dot.style.top, '416px');
  assert.match(String(store.get('pineOrchDotAt')), /278/);

  dot.fire('pointerdown', {clientX: 280, clientY: 420, pointerId: 2, preventDefault: () => {}});
  dot.fire('pointerup', {pointerId: 2});
  assert.deepEqual(opened, ['recovery']);
  assert.equal(findByClass(body, 'og').length, 0, 'tap opened the glass instead of recovery');

  glass.open();
  await wait(40);
  const control = findByClass(body, 'og-recovery')[0];
  assert.match(words(control), /Recovering 2\/3/);
  assert.match(words(control), /flush the queue/);
  assert.match(words(control), /Flushing the queued round now/);
  control.fire('click', {stopPropagation: () => {}});
  assert.deepEqual(opened, ['recovery', 'recovery']);
  glass.close();
});

test('the ordinary mascot drags freely, collapses on tap, and restores in place', async () => {
  const {store} = world();
  station(payload());
  const glass = load();
  const dot = glass.dot();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'idle');

  const startLeft = parseInt(dot.style.left, 10);
  const startTop = parseInt(dot.style.top, 10);
  dot.fire('pointerdown', {clientX: 8, clientY: 8, pointerId: 1, preventDefault: () => {}});
  dot.fire('pointermove', {clientX: 8 + 380 - startLeft, clientY: 8 + 360 - startTop, pointerId: 1});
  dot.fire('pointerup', {pointerId: 1});
  assert.equal(dot.style.left, '380px');
  assert.equal(dot.style.top, '360px');
  assert.match(String(store.get('pineOrchDotAt')), /380/);

  dot.fire('pointerdown', {clientX: 380, clientY: 360, pointerId: 2, preventDefault: () => {}});
  dot.fire('pointerup', {pointerId: 2});
  assert.equal(glass.isDotHidden(), true);
  const restored = glass.undot();
  assert.ok(restored);
  assert.equal(glass.isDotHidden(), false);
  assert.equal(restored.style.left, '380px');
  assert.equal(restored.style.top, '360px');
});

test('fault, normal quiet, and unreachable station have distinct mascot states', async () => {
  world();
  let watch = {on: true, paused: false, working: false, rung: ''};
  let health = {stuck: true, say: 'Dialogue is not reaching air'};
  let consoleState = {stuck: false};
  globalThis.pineDesktop = {get: async (route) => route === '/api/broadcast/watch'
    ? watch : route === '/api/broadcast/health' ? health : consoleState};
  const glass = load();
  const dot = glass.dot();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'attention');
  assert.match(words(dot), /Recovery needed/);

  health = {stuck: false};
  glass.refreshRecovery();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'idle');
  assert.doesNotMatch(words(dot), /Recovery needed/);

  watch = null; health = null; consoleState = null;
  glass.refreshRecovery();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'unknown');
  assert.match(words(dot), /Station unreachable/);
});

test('console watch reports recovery when the watch route is unavailable', async () => {
  world();
  globalThis.pineDesktop = {get: async (route) => {
    if (route === '/api/broadcast/watch') throw new Error('watch unavailable');
    if (route === '/api/broadcast/health') return {stuck: true};
    return {on: true, paused: false, watch_working: true,
      watch_road: 'dialogue rescue', watch: 'Checking the DJ handoff'};
  }};
  const glass = load();
  const dot = glass.dot();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'working');
  assert.match(words(dot), /dialogue rescue/);
  assert.match(dot.getAttribute('title'), /Checking the DJ handoff/);
});

test('an operator pause is not a fault and only a tap resumes it', async () => {
  world();
  const posts = [];
  let paused = true;
  let repairs = 0;
  globalThis.PineRevive = {open: () => { repairs += 1; }};
  globalThis.pineDesktop = {
    get: async (route) => route === '/api/broadcast/watch'
      ? {on: true, paused: false, working: false}
      : route === '/api/broadcast/health'
        ? {stuck: true, paused, say: 'The station is paused'}
        : {on: true, paused, stuck: true},
    post: async (route, body) => {
      posts.push({route, body});
      if (route === '/api/radio/pause') paused = false;
      return {paused};
    }
  };
  const glass = load();
  const dot = glass.dot();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'paused');
  assert.match(words(dot), /Station paused/);
  assert.match(words(dot), /Tap to resume/);
  assert.deepEqual(posts, [], 'the status poll resumed an intentional pause');
  dot.fire('pointerdown', {clientX: 200, clientY: 200, pointerId: 1});
  dot.fire('pointerup', {pointerId: 1});
  await wait(40);
  assert.deepEqual(posts, [{route: '/api/radio/pause', body: {paused: false}}]);
  assert.equal(repairs, 0, 'a deliberate pause was sent into the repair ladder');
});

test('Off Air is distinct from a fault and FM starts only after a tap', async () => {
  world();
  const posts = [];
  let on = false;
  globalThis.pineDesktop = {
    get: async (route) => route === '/api/broadcast/watch'
      ? {on, paused: false, working: false}
      : route === '/api/broadcast/health' ? {stuck: false}
        : {on, paused: false, stuck: false},
    post: async (route, body) => {
      posts.push({route, body});
      on = true;
      return {on: true};
    }
  };
  const glass = load();
  const dot = glass.dot();
  await wait(40);
  assert.equal(dot.getAttribute('data-recovery'), 'offair');
  assert.match(words(dot), /Off air/);
  assert.match(words(dot), /Tap to put FM on/);
  assert.deepEqual(posts, [], 'the watch silently resumed deliberate Off Air');
  dot.fire('pointerdown', {clientX: 200, clientY: 200, pointerId: 1});
  dot.fire('pointerup', {pointerId: 1});
  await wait(40);
  assert.deepEqual(posts, [{route: '/api/dj/start', body: {station: 'all'}}]);
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

/* ================================================================== #1211
 *
 * THE TWO PANES THAT SAID "COULD NOT BE COUNTED", AND THE THREE THINGS THE
 * PANEL COULD SHOW BUT NEVER DO.
 *
 * All three of these fail SILENTLY, which is why they are tested:
 *
 * 1. A PANE THAT DRAWS NOTHING BECAUSE THE SHAPE CHANGED. The rooms pane
 *    reads `in`/`out`/`stuck` through a list of accepted key names; a
 *    server that sends `entered` instead of `in` is drawn, and a server
 *    that sends a room with no counts at all must NOT be drawn as zeroes.
 *    Both are asserted, because "0 in / 0 out" for a busy room is the one
 *    reading that would send the operator hunting a fault that is not
 *    there.
 * 2. A BUTTON THAT POSTS NOTHING. Every action here is one POST to a road
 *    that already exists; a typo in the path is invisible on screen - the
 *    row just sits there - so the test asserts the exact route and body.
 * 3. A RESULT NOBODY SEES. #1186 holds the repaint while a hand is over
 *    the panel, which is right for the poll and wrong for a press: the
 *    answer to his own press would be held behind the press that asked
 *    for it. The test presses with the hold standing and asserts the
 *    station's own sentence reaches the foot anyway.
 */

/* The two keys the server half adds, shaped as orchestrator_rooms.py
   sends them - four rooms, a counted account, and one open ask. */
function withRooms(over) {
  return payload(Object.assign({
    rooms_window_seconds: 600,
    rooms_say: 'material only ever moves down this list.',
    rooms: [
      {key: 'writing', name: 'the writing desk', label: 'the writing desk',
       why: 'a model turns the brief into a script.',
       in: 12, out: 11, stuck: 1, window_seconds: 600,
       in_door: 'a model visit began', out_door: 'a visit came back',
       holding_door: 'visits in flight right now',
       oldest_seconds: 34.2},
      {key: 'reserve', name: 'the reserve', label: 'the reserve',
       why: 'scripts waiting for a slot.',
       in: 4, out: 2, stuck: 343, holding: 809, oldest_seconds: 238344,
       window_seconds: 600,
       in_door: 'a row was written onto a pile',
       out_door: 'a row aired, or was withdrawn',
       holding_door: 'every row standing on the larder or a shelf',
       top: [{name: 'an advert', count: 86}, {name: 'a painting round', count: 70}],
       blocked: [{name: 'never_handed', count: 61,
                  why: 'nothing about it is stopping it - no road asked.',
                  fix: 'hear it now, or let the sweep take it.'}]},
      {key: 'recording', name: 'the recording room', label: 'the recording room',
       why: 'one actor at a time.', in: 30, out: 28, stuck: 7,
       window_seconds: 600, window_truncated: true,
       window_covers_seconds: 210},
      /* A ROOM THAT COULD NOT BE READ. No counts at all, on purpose. */
      {key: 'broken', name: 'the pantry', label: 'the pantry',
       why: 'this room could not be read on this pass (RuntimeError).'}
    ],
    waste: {
      recorded: 1841, recorded_basis: 'lines sent to the microphone',
      played: 902, played_basis: 'deliveries a listener acknowledged',
      never_heard: 78, never_heard_what: 'finished round',
      never_heard_seconds: 956.0,
      covered: 14, executed: 2, unused: 12, scheduled: 9,
      classes: [{name: 'a station ID', count: 67, seconds: 490,
                 why: '67 have never aired.'}],
      rows_basis: 'the oldest never-heard rounds',
      rows: [{
        id: 'station_id-aa11bb22cc33dd44', road: 'station_id',
        label: 'a station ID', name: 'the top of the hour',
        text: 'You are listening to Pine Box FM.',
        written_ago_seconds: 238344, seconds: 7.3,
        blocked: false, ready: true,
        why: 'it is finished radio and no road has asked for it.',
        why_code: 'never_handed', reasons: [],
        actions: ['hear', 'retire', 'fork']
      }]
    },
    asks: [{
      id: 'ask0011', at: (Date.now() / 1000) - 120, topic: 'offline_stock',
      urgency: 'routine', decides_alone_in: 1800,
      why: 'Phone calls is furthest behind the three-hour goal.',
      questions: [{ask: 'What should I do?', options: [
        {face: 'Build phone calls first until covered', does: 'drive:caller',
         note: 'the preparer stays on that shelf'},
        {face: 'Leave it short', does: 'noop', note: ''}
      ]}],
      answer_url: '/api/orchestrator/asks/ask0011'
    }]
  }, over || {}));
}

/* Both doors, counted: the GET the poll uses and the POSTs a press uses. */
function stationRW(answer) {
  const got = [], sent = [];
  globalThis.pineDesktop = {
    get: async (route) => { got.push(route); return answer; },
    post: async (route, body) => {
      sent.push({route, body});
      return {ok: true, say: 'the station took it', lines: ['a line of proof']};
    }
  };
  return {got, sent};
}

test('[#1211] the rooms pane counts what it was sent and refuses to zero what it was not', async () => {
  const {body} = world();
  stationRW(withRooms());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];

  const rooms = foldNamed(node, 'the four rooms');
  assert.ok(rooms, 'the rooms pane was not drawn at all');
  const summary = findByClass(rooms, 'og-tri-sum')[0];
  assert.match(String(summary.textContent), /4 rooms/,
    'the pane did not count the rooms it was sent: ' + summary.textContent);
  assert.doesNotMatch(String(summary.textContent), /could not be counted/,
    'the pane still says it cannot count a payload that carries rooms');

  press(rooms);
  const said = words(rooms);
  assert.match(said, /the writing desk/, 'the first room is missing');
  assert.match(said, /12 in/, 'what went in was not drawn');
  assert.match(said, /343 stuck/, 'what is stuck was not drawn');
  assert.match(said, /came out are counted over the last 10[.]0 min/,
    'the caption did not name the ten-minute window: ' + said.slice(0, 400));

  /* THE ROOM THAT COULD NOT BE READ IS NOT DRAWN AS ZERO. */
  const pantry = foldNamed(rooms, 'the pantry');
  assert.ok(pantry, 'the unreadable room was dropped instead of reported');
  assert.match(String(findByClass(pantry, 'og-tri-sum')[0].textContent),
    /could not be counted/,
    'a room with no counts was summarised as something other than uncounted');
  press(pantry);
  assert.match(words(pantry), /went in|looked for/,
    'the unreadable room did not name the keys it looked for');

  /* The doors, the names and the blocked reason all reach the screen. */
  const reserve = foldNamed(rooms, 'the reserve');
  press(reserve);
  const inside = words(reserve);
  assert.match(inside, /a row was written onto a pile/,
    'the in-door was not named');
  assert.match(inside, /an advert/, 'the top few by name were not drawn');
  assert.match(inside, /never_handed/, 'the blocked reason was not drawn');

  /* A COUNT OFF A RING THAT HAS ROTATED IS A FLOOR AND SAYS SO. Only the
     recording room carries `window_truncated` in this payload, so only it
     may print the warning - and it must. */
  const rec = foldNamed(rooms, 'the recording room');
  press(rec);
  assert.match(words(rec), /FLOORS, not totals/,
    'a truncated window was printed as though it were a total');
  assert.doesNotMatch(inside, /FLOORS, not totals/,
    'a complete window was wrongly marked as a floor');
  glass.close();
});

test('[#1211] a never-heard round can be heard, retired or edited, and the POST lands', async () => {
  const {body} = world();
  const doors = stationRW(withRooms());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];

  const waste = foldNamed(node, 'made and never heard');
  assert.ok(waste, 'the waste pane was not drawn');
  assert.match(String(findByClass(waste, 'og-tri-sum')[0].textContent),
    /never heard/, 'the headline did not reach the summary');
  press(waste);
  /* THE NOUN IS THE STATION'S. It counted rounds; the line used to say
     "lines", which is a label quietly meaning something else. */
  assert.match(words(waste), /78 finished rounds recorded and never played/,
    'the headline used the wrong noun: ' + words(waste).slice(0, 300));

  const round = foldNamed(waste, 'the top of the hour');
  assert.ok(round, 'the never-heard round itself was not listed');
  press(round);
  const buttons = findByClass(round, 'og-offer-b');
  assert.equal(buttons.length, 3,
    'a row without three actions: ' + buttons.length);

  buttons[0].fire('click', {});
  await wait(20);
  assert.equal(doors.sent.length, 1, 'pressing hear it now posted nothing');
  assert.equal(doors.sent[0].route, '/api/cupboard/act',
    'hear it now went to the wrong road: ' + doors.sent[0].route);
  assert.deepEqual(doors.sent[0].body,
    {id: 'station_id-aa11bb22cc33dd44', action: 'play'},
    'the body was not the one the cupboard road understands');

  /* AND THE ANSWER LANDS WHERE HE CAN SEE IT - in the footer, which the
     reconcile never touches, so it survives every poll after this. */
  const out = findByClass(node, 'og-cmd-out')[0];
  assert.ok(out && !out.hidden, 'the foot never spoke');
  assert.match(String(out.textContent), /the station took it/,
    'the foot did not carry the station\'s own sentence');
  glass.close();
});

test('[#1211] an ask is answered in place, and the command line runs a verb', async () => {
  const {body} = world();
  const doors = stationRW(withRooms());
  const glass = load();
  glass.open();
  await wait(30);
  const node = findByClass(body, 'og')[0];

  const roads = foldNamed(node, 'what it is asking the station for');
  assert.ok(roads, 'the roads pane was not drawn');
  assert.match(String(findByClass(roads, 'og-tri-sum')[0].textContent),
    /1 waiting on you/, 'the open ask was not counted on the pane');
  press(roads);
  const ask = foldNamed(roads, 'offline_stock');
  assert.ok(ask, 'the open ask was not drawn inside the pane');
  press(ask);
  const options = findByClass(ask, 'og-offer-b');
  assert.equal(options.length, 2, 'the options did not reach the screen');
  options[0].fire('click', {});
  await wait(20);
  assert.equal(doors.sent[0].route, '/api/orchestrator/asks/ask0011',
    'the answer went to the wrong road: ' + doors.sent[0].route);
  assert.deepEqual(doors.sent[0].body, {picks: {'0': 'drive:caller'}},
    'the pick was not shaped the way orch_answer reads it');

  /* THE COMMAND LINE. One line, one POST, and the verb is carried
     verbatim - the station owns the vocabulary, not this file. */
  const input = findByClass(node, 'og-cmd-in')[0];
  assert.ok(input, 'there is no command line at the foot of the panel');
  input.value = 'more banter';
  findByClass(node, 'og-cmd-go')[0].fire('click', {});
  await wait(20);
  assert.equal(doors.sent[1].route, '/api/orchestrator/command',
    'the command went to the wrong road: ' + doors.sent[1].route);
  assert.deepEqual(doors.sent[1].body, {text: 'more banter'},
    'the typed line was not sent as it was typed');
  const more = findByClass(node, 'og-cmd-more')[0];
  assert.match(words(more), /a line of proof/,
    'the station\'s own lines were not echoed at the foot');
  glass.close();
});
