/* #1193b - THE RAIL THAT NEVER MEASURED ANYTHING, AND THE FIVE-PIXEL FLOOR.
 *
 * "give these tabs a little more breathing room. At least give them five
 *  pixels of buffer room around each side so that way the tabs aren't so
 *  small and compressed in the pine box app."
 *
 * Two things came out of that photograph and only one of them was the
 * floor.
 *
 * THE FLOOR. PAD_MIN 2 -> 5, GAP_MIN 3 -> 5, the rail's own end padding
 * 4 -> 5, and the stylesheet fallbacks with them. Raising a floor changes
 * what happens when the column will not fit: the solver walks the padding
 * down and gives the corner reserve away first, so with a floor of five it
 * reaches the floor sooner and a short window SCROLLS where it used to
 * shrink. That is the trade he asked for, and the two things that must
 * survive it are pinned below - the cap is still applied, so the corner
 * band is never eaten, and an overflowing column still reports that it
 * scrolls.
 *
 * THE OTHER THING, which the floor alone would never have reached: fit()
 * had not been running at all. It walks every `.pine-view-tab` and bails
 * on any tab measuring zero, because a tab not yet laid out would make the
 * solver promise room it does not have - but pine-cam.js appends a CAM tab
 * at boot and sets display:none on it until the camera is live. A tab that
 * measures zero for ever. Every call returned null, `--pine-rail-max` came
 * off, and the rail has been sitting on the stylesheet's fallback padding
 * since those tabs landed. That is the cramped rail in the photograph.
 *
 * The arithmetic below is the real solver out of rail.js, not a copy of
 * it: fit() calls solve() and so does this.
 */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(
  path.join(__dirname, '../desktop/renderer/rail.js'), 'utf8');

function load(extra) {
  const win = Object.assign({
    addEventListener() {},
    getComputedStyle: () => ({paddingTop: '5px', paddingBottom: '5px'}),
    innerHeight: 900
  }, extra || {});
  const document = {
    getElementById: () => null,
    createElement: () => ({style: {}}),
    addEventListener() {},
    querySelectorAll: () => [],
    head: {appendChild() {}},
    body: {appendChild() {}}
  };
  win.document = document;
  const context = vm.createContext({
    window: win, document, console,
    setTimeout: (fn) => 1, clearTimeout() {}, Event: class {},
    Math, String, Number, Array, Object, JSON
  });
  context.globalThis = context;
  vm.runInContext(SOURCE, context);
  return win;
}

/* The twelve tabs the rail carries today, CAM hidden until the camera is
 * live: TECH SAMPLER SCRIPT LISTEN MUSIC PRESENT SLIDES 3JS SC CORNERS
 * FIND CAM ENDLESS. Word lengths are modelled from the figure rail.js
 * measured for itself - "thirteen tabs of 12px text are about 434px of
 * words alone" - which is 5.746px per character at 12px plus 2px of
 * border per tab. */
const LABELS = ['TECH', 'SAMPLER', 'SCRIPT', 'LISTEN', 'MUSIC', 'PRESENT',
  'SLIDES', '3JS', 'SC', 'CORNERS', 'FIND CAM', 'ENDLESS'];
const PER_CHAR_12 = (434 - 13 * 2) / 71;
const words = (fontPx) =>
  LABELS.map((l) => Math.round(2 + l.length * PER_CHAR_12 * (fontPx / 12)));
const OWN = 10;          /* the rail's own 5px top and 5px bottom */

test('the floor is five on every axis the operator can see', () => {
  const fit = load().PineRailFit;
  assert.equal(fit.PAD_MIN, 5);
  assert.equal(fit.GAP_MIN, 5);
  /* Nothing the solver can return is below the floor, however impossible
   * the column: padThatFits bottoms out AT PAD_MIN, it does not pass it. */
  for (const avail of [2000, 900, 400, 200, 10, 0, -50]) {
    const pad = fit._padThatFits(words(12), OWN, avail);
    assert.ok(pad >= 5, 'pad ' + pad + ' at avail ' + avail);
    assert.ok(fit._gapFor(pad) >= 5, 'gap at avail ' + avail);
  }
  /* And the stylesheet's own fallback, for the moment before any of this
   * has run, says five too. */
  assert.ok(SOURCE.includes("'padding:var(--pine-tab-pad,5px) 11px;'"));
  assert.ok(SOURCE.includes("'padding:5px 0;gap:var(--pine-rail-gap,5px);'"));
});

test('what the twelve tabs land on, desk and tablet', () => {
  const fit = load().PineRailFit;
  const desk = words(10);
  const tablet = words(12);

  /* THE DESK, at the window heights it is actually used at. The tabs get
   * the room he asked for at the top of the range - pad 15 at 1040 - and
   * the reserve is never touched, so both hot corners stay clear. */
  const at = (w, glass) => fit._solve(w, OWN, glass, fit.CORNER_FALLBACK);

  let got = at(desk, 1040);
  assert.deepEqual([got.pad, got.gap, got.reserve, got.cap, got.column, got.scrolls],
    [15, 8, 110, 820, 810, false]);

  got = at(desk, 900);
  assert.deepEqual([got.pad, got.gap, got.reserve, got.cap, got.column, got.scrolls],
    [9, 8, 110, 680, 666, false]);

  got = at(desk, 800);
  assert.deepEqual([got.pad, got.gap, got.reserve, got.cap, got.column, got.scrolls],
    [6, 6, 110, 580, 572, false]);

  /* THE TABLET'S 690px LANDSCAPE GLASS, where the trade lands. The text is
   * 12px there whatever the stylesheet says - the WebView enforces a
   * minimum and no stylesheet argues with it - so the words are longer and
   * the floor is reached. The reserve has been spent all the way down to
   * RESERVE_MIN first, the cap is still applied, and the column overflows
   * it by 19px and scrolls. Before the floor it would have shrunk to pad 3
   * instead, which is what he asked us to stop doing. */
  got = at(tablet, 690);
  assert.deepEqual([got.pad, got.gap, got.reserve, got.cap, got.column, got.scrolls],
    [5, 5, 56, 578, 597, true]);
  assert.equal(got.reserve, fit.RESERVE_MIN,
    'the corner band survives the overflow - it is the last thing given up');
  assert.ok(got.cap < 690,
    'the cap is still applied when it scrolls, or a tab lands in a corner');

  /* Portrait on the same tablet has room to spare. */
  got = at(tablet, 1230);
  assert.deepEqual([got.pad, got.gap, got.reserve, got.scrolls],
    [16, 8, 110, false]);
});

test('a deliberately hidden tab is skipped, not a reason to give up', () => {
  /* THE BUG, pinned. pine-cam.js appends a CAM tab and hides it until the
   * camera is live; fit() bailed on it every time, so nothing was ever
   * measured. Both kinds of zero are exercised here: hidden on purpose,
   * which is skipped, and displayed but unmeasured, which still bails. */
  const railStyle = {};
  const props = {};
  const rail = {
    style: {
      setProperty(k, v) { props[k] = v; },
      removeProperty(k) { delete props[k]; }
    },
    querySelectorAll: () => rail.tabs,
    setAttribute(k, v) { railStyle[k] = v; },
    scrollHeight: 597,
    tabs: []
  };
  const tab = (h, display) => ({offsetHeight: h, style: {display: display || ''}});

  const win = load({
    innerHeight: 800,
    getComputedStyle: (el) => (el === rail
      ? {paddingTop: '5px', paddingBottom: '5px'}
      : {display: (el && el.style && el.style.display) || 'block'})
  });
  win.document.getElementById = (id) => (id === 'pineViewRail' ? rail : null);

  /* Eleven real tabs and one hidden CAM. */
  rail.tabs = LABELS.map((l) => tab(2 * 4 + Math.round(l.length * PER_CHAR_12) + 2));
  rail.tabs.push(tab(0, 'none'));
  const said = win.PineRailFit.fit();
  assert.ok(said, 'a hidden tab must not stop the whole pass');
  assert.equal(said.tabs, 13);
  assert.equal(said.shown, 12, 'the hidden one takes no room in the column');
  assert.ok(said.pad >= 5);
  assert.ok(props['--pine-rail-max'], 'the cap is written, so the corners stay clear');

  /* A tab that IS displayed and still measures zero has not been laid out.
   * That is the case the bail was written for and it still bails. */
  rail.tabs.push(tab(0, ''));
  assert.equal(win.PineRailFit.fit(), null);
  assert.equal(props['--pine-rail-max'], undefined,
    'and it takes the cap off, so the observer can try again with no stale number');
});

test('closing the rail closes a 3JS scene with it, once, without recursing',
  () => {
    /* The answer to "what does pressing another rail tab do while a scene
     * is up": the same thing pressing a rail tab has always done - it
     * closes what is open and goes where it was asked. The rail has never
     * refused a tab and this is not the place to start. closeAll() is the
     * one funnel every road goes through - TECH, every rail tab via
     * open(), and the capture handler on the shell's own nav. */
    let closes = 0;
    const win = load();
    const panes = {};
    win.PineThreeFull = {
      close() {
        closes += 1;
        /* A scene closing must not be able to drive the rail round again. */
        win.PineViewRail.closeAll();
        return Promise.resolve('closed');
      }
    };
    win.document.getElementById = (id) => {
      if (!panes[id]) {
        panes[id] = {classList: {
          removed: [],
          remove(c) { panes[id].classList.removed.push(c); },
          contains: () => false
        }};
      }
      return panes[id];
    };
    win.PineViewRail.closeAll();
    assert.equal(closes, 1, 'once, not once per nested call');
    assert.ok(panes.script.classList.removed.includes('open'),
      'and the panes really came down');
  });
