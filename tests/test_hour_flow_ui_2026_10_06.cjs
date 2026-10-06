/* [hour-flow] The hour's entry as a vertical flowchart editor (2026-10-06).
   node --test tests/test_hour_flow_ui_2026_10_06.cjs
   The module parses, exports the global with open/close/mount, has the X with its
   tooltip, the scope toggle, the Back button, is ASCII only - and, mounted on a
   small fake DOM with a fixture, paints one node per leg plus the inner rows and
   never scrolls on its own. */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const HERE = path.resolve(__dirname, '..');
const candidates = [
  path.join(HERE, 'modules', 'hour-flow.js'),                       /* waveB, as delivered */
  path.join(HERE, 'desktop', 'renderer', 'hour-flow.js'),           /* the repo, once applied */
];
const JS = candidates.find((p) => fs.existsSync(p));
const CSS = JS && JS.replace(/hour-flow\.js$/, 'hour-flow.css');
assert.ok(JS, 'hour-flow.js is beside this test (modules/ or desktop/renderer/)');
const src = fs.readFileSync(JS, 'utf8');
const css = fs.existsSync(CSS) ? fs.readFileSync(CSS, 'utf8') : '';

test('the module parses as a script', () => {
  assert.doesNotThrow(() => new vm.Script(src, {filename: 'hour-flow.js'}));
});

test('it is ASCII only (no emoji, no typographic quotes), and so is the stylesheet', () => {
  const bad = (text) => [...text].filter((c) => c.charCodeAt(0) > 0x7e || (c.charCodeAt(0) < 0x20 && c !== '\n' && c !== '\t'));
  assert.deepEqual(bad(src), [], 'non-ASCII characters in hour-flow.js');
  assert.deepEqual(bad(css), [], 'non-ASCII characters in hour-flow.css');
});

test('it exports window.PineHourFlow with open, close and mount', () => {
  assert.match(src, /root\.PineHourFlow\s*=\s*\{open: open, close: close, mount: mount/);
  assert.match(src, /if \(root\.PineHourFlow\) return;/, 'loads once');
});

test('the words the operator asked for are on it: the X with a tooltip, the scope toggle, Back', () => {
  assert.match(src, /x\.title = 'Close'; x\.setAttribute\('aria-label', 'Close'\)/, 'a top-right X with its tooltip');
  assert.match(src, /'this entry only'/, 'the toggle: this entry only');
  assert.match(src, /'every ' \+ \(state\.kind \|\| 'such'\) \+ ' entry'/, 'the toggle: every <kind> entry');
  assert.match(src, /make\('button', 'hf-btn hf-back', 'Back'\)/, 'a Back button');
  assert.match(src, /back\.title = 'Back to the hour'/);
  for (const tool of ["'insert after'", "'extend'", "'up'", "'down'", "'remove'", "'deepen'", "'add an exchange'"]) {
    assert.ok(src.includes(tool), 'the node tool ' + tool);
  }
  assert.ok(src.includes("Back to the road's default"));
  assert.ok(src.includes("/api/system3/structures/"));
  assert.ok(src.includes("scope: 'entry', slot_id: state.slot, structure: body"), 'the PUT body for this entry only');
  assert.ok(src.includes("'?scope=entry&slot_id='"), 'the DELETE for the entry variant');
});

test('nothing in it scrolls the reader on its own', () => {
  assert.ok(!/scrollIntoView|scrollTo\(/.test(src), 'no scrollIntoView / scrollTo');
  assert.match(src, /var keep = body\.scrollTop;/, 'a repaint keeps the scroll where it was');
});

test('the stylesheet has the X, the scope toggle, the chart classes and a phone width', () => {
  for (const sel of ['.hf-x', '.hf-scope-btn', '.hf-node', '.hf-edge', '.hf-leg', '.hf-inner', '.hf-inspect', '.hf-back', '@media (max-width: 520px)']) {
    assert.ok(css.includes(sel), 'css has ' + sel);
  }
});

/* ---- a small fake DOM, enough to mount on ------------------------------------ */
function fakeDocument() {
  const byClass = [];
  function el(tag) {
    const node = {
      tagName: String(tag).toUpperCase(), children: [], _attrs: {}, _text: '', style: {}, dataset: {}, hidden: false,
      disabled: false, value: '', scrollTop: 0, isConnected: true, parentNode: null, type: '',
      _cls: new Set(),
      get className() { return [...this._cls].join(' '); },
      set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); },
      classList: null,
      get textContent() { return this._text || this.children.map((c) => c.textContent).join(''); },
      set textContent(v) { this._text = String(v); this.children = []; },
      appendChild(c) { this.children.push(c); c.parentNode = this; return c; },
      append(...cs) { cs.forEach((c) => this.appendChild(typeof c === 'string' ? el('#text') : c)); },
      removeChild(c) { this.children = this.children.filter((x) => x !== c); },
      remove() { if (this.parentNode) this.parentNode.removeChild(this); this.isConnected = false; },
      replaceChildren() { this.children = []; },
      setAttribute(k, v) { this._attrs[k] = String(v); },
      getAttribute(k) { return this._attrs[k] == null ? null : this._attrs[k]; },
      addEventListener(name, fn) { (this._handlers = this._handlers || {})[name] = fn; },
      removeEventListener() {},
      click() { if (this._handlers && this._handlers.click) this._handlers.click({stopPropagation() {}}); },
      querySelector() { return null; }, querySelectorAll() { return []; },
    };
    node.classList = {
      add: (...c) => c.forEach((x) => node._cls.add(x)), remove: (...c) => c.forEach((x) => node._cls.delete(x)),
      toggle: (c, on) => { if (on === undefined) on = !node._cls.has(c); if (on) node._cls.add(c); else node._cls.delete(c); return on; },
      contains: (c) => node._cls.has(c),
    };
    byClass.push(node);
    return node;
  }
  const body = el('body');
  return {
    body, createElement: el, createElementNS: (ns, tag) => el(tag), createDocumentFragment: () => el('#fragment'),
    addEventListener() {}, removeEventListener() {}, hidden: false,
    all: () => byClass,
  };
}
function walk(node, fn) { fn(node); (node.children || []).forEach((c) => walk(c, fn)); }
function withClass(root, cls) { const out = []; walk(root, (n) => { if (n._cls && n._cls.has(cls)) out.push(n); }); return out; }

const FIXTURE = {
  road: 'news', slot_id: 'hour-05', scope: 'road', key: 'news',
  structure: {id: 'news_legs', label: '[News]', kind: 'legs', min_turns: 4, max_turns: 10, legs: [
    {id: 'lead', label: 'The lead', place: 'open', seat: 'A', act: 'THE LEAD: the top story off the wire.', draws: [{family: 'ES'}],
     inner: [{seat: 'B', act: 'asks one question about the lead', families: ['ES', 'RS']}]},
    {id: 'react', label: 'Reacts to the lead', place: 'open', seat: 'B', act: 'reacts to the lead.', draws: [{family: 'ES'}, {family: 'RS'}]},
    {id: 'next', label: 'The next story', place: 'middle', seat: 'alternate', act: 'the next story off the page.', draws: [{family: 'ES'}, {family: 'RS'}, {family: 'FL', tables: ['FL2']}]},
    {id: 'back', label: 'Back to the music', place: 'close', seat: 'A', act: 'BACK TO THE MUSIC.', draws: [{family: 'ES'}, {family: 'FL', tables: ['FL2'], closes: true}]},
  ], head: 'H', tail: 'T'},
  road_structure: null, default: null, entry_held: false, variants: [], families: ['ES', 'RS', 'IRS', 'FL', 'CTS', 'REACT'], line_road: false,
};
FIXTURE.road_structure = FIXTURE.structure;
FIXTURE.default = FIXTURE.structure;

function load() {
  const document = fakeDocument();
  const window = {document, location: {protocol: 'file:'}, setTimeout, clearTimeout, fetch: () => Promise.reject(new Error('no network in the test')),
                  Promise, JSON, Object, Array, Math, Number, String, Date, Error, Set, Boolean};
  window.window = window;
  vm.runInNewContext(src, window, {filename: 'hour-flow.js'});
  return {window, document};
}

test('mounted on a fixture, it paints one node per leg, the inner rows, the toggle and the tools', async () => {
  const {window, document} = load();
  assert.equal(typeof window.PineHourFlow.open, 'function');
  assert.equal(typeof window.PineHourFlow.close, 'function');
  assert.equal(typeof window.PineHourFlow.mount, 'function');
  const calls = [];
  const host = document.createElement('div');
  let backs = 0;
  const ctl = window.PineHourFlow.mount(host, {
    road: 'news', kind: 'news', slot_id: 'hour-05', label: 'News at five past', hour: '2026-10-06T14',
    get: (p) => { calls.push(['GET', p]); return Promise.resolve(JSON.parse(JSON.stringify(FIXTURE))); },
    put: (p, b) => { calls.push(['PUT', p, b]); return Promise.resolve({structure: {version: 2}}); },
    del: (p) => { calls.push(['DELETE', p]); return Promise.resolve({deleted: 'news@hour-05'}); },
    onBack: () => { backs += 1; },
  });
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(calls[0], ['GET', '/api/system3/structures/news?slot_id=hour-05']);
  assert.equal(withClass(host, 'hf-leg').length, 4, 'one node per leg');
  assert.equal(withClass(host, 'hf-inner').length, 1, 'the inner row is drawn under its leg');
  assert.equal(withClass(host, 'hf-start').length, 1);
  assert.equal(withClass(host, 'hf-end').length, 1);
  assert.equal(withClass(host, 'hf-edge').length, 5, 'a connector before every leg and every inner row');
  const scope = withClass(host, 'hf-scope-btn');
  assert.deepEqual(scope.map((b) => b.textContent), ['this entry only', 'every news entry']);
  assert.equal(ctl.state().scope, 'entry', 'opened on an entry it edits that entry first');
  assert.equal(scope[0].getAttribute('aria-pressed'), 'true');
  const x = withClass(host, 'hf-x')[0];
  assert.equal(x.title, 'Close');
  assert.equal(x.getAttribute('aria-label'), 'Close');
  const back = withClass(host, 'hf-back')[0];
  assert.equal(back.textContent, 'Back');
  back.click();
  assert.equal(backs, 1, 'Back calls onBack');
  /* the tools on the first node */
  const tools = withClass(withClass(host, 'hf-leg')[0], 'hf-tool').map((b) => b.textContent);
  assert.deepEqual(tools, ['exchanges (1)', 'insert after', 'extend', 'up', 'down', 'remove']);
  /* insert after the first leg: five nodes, the new one selected and its inspector open */
  withClass(withClass(host, 'hf-leg')[0], 'hf-tool')[1].click();
  assert.equal(withClass(host, 'hf-leg').length, 5);
  assert.equal(ctl.state().drafts.entry.legs.length, 5);
  assert.equal(ctl.state().drafts.entry.legs[1].label, 'New turn');
  assert.equal(withClass(host, 'hf-inspect')[0].hidden, false, 'the new turn is selected');
  /* extend the closing leg: a continuation follows it */
  const legs = ctl.state().drafts.entry.legs;
  withClass(withClass(host, 'hf-leg')[4], 'hf-tool')[1 + 1].click();
  assert.equal(legs.length, 6);
  assert.equal(legs[5].id, 'back_on');
  assert.match(legs[5].act, /^Carries straight on from the turn before: /);
  /* the scope toggle swaps drafts: the road's is untouched */
  scope[1].click();
  assert.equal(ctl.state().scope, 'road');
  assert.equal(ctl.state().drafts.road.legs.length, 4);
  scope[0].click();
  /* save for this entry only: the PUT carries scope entry and the slot */
  withClass(host, 'hf-save')[0].click();
  await new Promise((r) => setTimeout(r, 20));
  const put = calls.find((c) => c[0] === 'PUT');
  assert.ok(put, 'a PUT went out');
  assert.equal(put[1], '/api/system3/structures/news');
  assert.equal(put[2].scope, 'entry');
  assert.equal(put[2].slot_id, 'hour-05');
  assert.equal(put[2].structure.legs.length, 6);
  assert.deepEqual(put[2].structure.legs[0].inner, [{seat: 'B', act: 'asks one question about the lead', families: ['ES', 'RS']}]);
  ctl.close();
});

test('with no entry at all it edits the road (the toggle to the entry is off)', async () => {
  const {window, document} = load();
  const host = document.createElement('div');
  const ctl = window.PineHourFlow.mount(host, {road: 'news', kind: 'news', get: () => Promise.resolve(JSON.parse(JSON.stringify(FIXTURE)))});
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(ctl.state().scope, 'road');
  assert.equal(withClass(host, 'hf-scope-btn')[0].disabled, true);
  ctl.close();
});

test('a road without a structure says so instead of a blank sheet', async () => {
  const {window, document} = load();
  const host = document.createElement('div');
  const ctl = window.PineHourFlow.mount(host, {road: 'banter', kind: 'banter', slot_id: 'hour-01',
    get: () => Promise.reject(new Error('no road called banter has a structure'))});
  await new Promise((r) => setTimeout(r, 20));
  const empty = withClass(host, 'hf-empty');
  assert.equal(empty.length, 1);
  assert.match(empty[0].textContent, /Banter runs the cycle/);
  ctl.close();
});
