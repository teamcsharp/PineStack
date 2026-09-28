// [s3-script-linear] the placement rule and the one-way mark, against the
// REAL code in desktop/renderer/script-page.js (pure function + stub DOM).
const assert = require('node:assert/strict');
const {test} = require('node:test');
const script = require('../desktop/renderer/script-page.js');
const place = script.linear.place;
const owner = script.linear.owner;

const up = (set) => (k) => set.includes(k);

test('no mark yet: the server order, untouched', () => {
  assert.deepEqual(place(['a', 'b'], ['b', 'a', 'c'], '').order, ['b', 'a', 'c']);
  assert.deepEqual(place([], ['x', 'y'], 'x').order, ['x', 'y'], 'a high that was never drawn freezes nothing');
});

test('(a) appended lines go below', () => {
  const got = place(['A', 'B', 'L', 'C'], ['A', 'B', 'L', 'C', 'D'], 'L');
  assert.deepEqual(got.order, ['A', 'B', 'L', 'C', 'D']);
  assert.equal(got.frozen, 3);
});

test('(b) a line re-ranked from below the mark to above it lands just below the mark', () => {
  const got = place(['A', 'B', 'L', 'C', 'D'], ['A', 'D', 'B', 'L', 'C'], 'L');
  assert.deepEqual(got.order, ['A', 'B', 'L', 'D', 'C']);
  assert.deepEqual(got.late, ['D']);
});

test('(c) a new line with an early key lands just below the mark, not above it', () => {
  const got = place(['A', 'B', 'L', 'C'], ['N', 'A', 'B', 'L', 'C'], 'L');
  assert.deepEqual(got.order, ['A', 'B', 'L', 'N', 'C']);
});

test('late rows: those already drawn under the mark first, then new ones', () => {
  const got = place(['A', 'L', 'X', 'C'], ['Y', 'X', 'A', 'L', 'C'], 'L');
  assert.deepEqual(got.order, ['A', 'L', 'X', 'Y', 'C']);
  const two = place(['A', 'L', 'C'], ['Q', 'P', 'A', 'L', 'C'], 'L');
  assert.deepEqual(two.order, ['A', 'L', 'Q', 'P', 'C'], 'new late rows keep server relative order');
});

test('(d) a row above the mark the server dropped stays (dimmed); below the mark it goes', () => {
  const got = place(['A', 'B', 'L', 'C', 'D'], ['B', 'L', 'D'], 'L', {keepDropped: true});
  assert.deepEqual(got.order, ['A', 'B', 'L', 'D']);
  assert.deepEqual(got.dropped, ['A']);
  assert.deepEqual(place(['A', 'B', 'L'], ['B', 'L'], 'L').order, ['B', 'L'], 'feed-style: not kept');
});

test('the mark row itself dropped: the nearest listed row above stands in', () => {
  const got = place(['A', 'B', 'L', 'C'], ['A', 'Z', 'B', 'C', 'X'], 'L', {keepDropped: true});
  assert.deepEqual(got.order, ['A', 'B', 'L', 'Z', 'C', 'X']);
  assert.deepEqual(got.dropped, ['L']);
  assert.deepEqual(got.late, ['Z']);
});

test('headings and cues travel with a relocated line', () => {
  const prev = ['ch-a', 'ln-a', 'ln-l'];
  const server = ['sc-x', 'sh-x', 'ch-x', 'pa-x', 'ln-x', 'ch-a', 'ln-a', 'ln-l', 'ln-c'];
  const got = place(prev, server, 'ln-l', {owner});
  assert.deepEqual(got.order, ['ch-a', 'ln-a', 'ln-l', 'sc-x', 'sh-x', 'ch-x', 'pa-x', 'ln-x', 'ln-c']);
});

test('a line drawn below the mark and a NEW scene heading for it stay together, heading first', () => {
  const prev = ['ln-a', 'ln-l', 'ch-x', 'ln-x'];
  const server = ['sc-x', 'sh-x', 'ch-x', 'ln-x', 'ln-a', 'ln-l'];
  const got = place(prev, server, 'ln-l', {owner});
  assert.deepEqual(got.order, ['ln-a', 'ln-l', 'sc-x', 'sh-x', 'ch-x', 'ln-x']);
});

test('a new cue for a line already drawn above the mark is not drawn', () => {
  const got = place(['ch-a', 'ln-a', 'ln-l'], ['ch-a', 'ln-a', 'ch-l', 'ln-l', 'ln-m'], 'ln-l', {owner});
  assert.deepEqual(got.order, ['ch-a', 'ln-a', 'ln-l', 'ln-m']);
  assert.deepEqual(got.skipped, ['ch-l']);
});

test('rule 5: a prepared row the server now places after the mark leaves the frozen block, cue and all', () => {
  const prev = ['ln-a', 'ch-p', 'ln-p', 'ch-l', 'ln-l'];
  const server = ['ln-a', 'ch-l', 'ln-l', 'ch-p', 'ln-p'];
  const got = place(prev, server, 'ln-l', {owner, upcoming: up(['ln-p'])});
  assert.deepEqual(got.order, ['ln-a', 'ch-l', 'ln-l', 'ch-p', 'ln-p']);
  assert.deepEqual(got.freed.sort(), ['ch-p', 'ln-p']);
});

test('rule 5 does not fire on a page that is merely behind the air', () => {
  const prev = ['ln-a', 'ln-b', 'ln-c'];
  const server = ['ln-a', 'ln-b', 'ln-c', 'ln-d'];     // b still `prepared`, before the mark
  const got = place(prev, server, 'ln-c', {owner, upcoming: up(['ln-b', 'ln-c', 'ln-d'])});
  assert.deepEqual(got.order, ['ln-a', 'ln-b', 'ln-c', 'ln-d']);
  assert.deepEqual(got.freed, []);
});

test('a new note on a line above the mark hangs beside it, after its older notes', () => {
  const hangs = (m) => (k) => m[k] || '';
  const one = place(['ln-a', 'ln-l'], ['ln-a', 'nt-1', 'ln-l'], 'ln-l', {hangs: hangs({'nt-1': 'ln-a'})});
  assert.deepEqual(one.order, ['ln-a', 'nt-1', 'ln-l']);
  const two = place(['ln-a', 'nt-0', 'ln-l'], ['ln-a', 'nt-0', 'nt-1', 'ln-l'], 'ln-l',
    {hangs: hangs({'nt-0': 'ln-a', 'nt-1': 'ln-a'})});
  assert.deepEqual(two.order, ['ln-a', 'nt-0', 'nt-1', 'ln-l']);
  assert.deepEqual(two.hung, ['nt-1']);
});

test('kept rows are bounded from the top', () => {
  const prev = ['d1', 'd2', 'd3', 'd4', 'L'];
  const got = place(prev, ['L', 'n'], 'L', {keepDropped: true, keepMost: 2});
  assert.deepEqual(got.order, ['d3', 'd4', 'L', 'n']);
  assert.equal(got.trimmed, 2);
});

test('an unchanged server answer is a fixed point', () => {
  const prev = ['A', 'B', 'L', 'C', 'D'];
  const server = ['A', 'D', 'N', 'B', 'L', 'C'];
  const first = place(prev, server, 'L', {keepDropped: true}).order;
  const second = place(first, server, 'L', {keepDropped: true}).order;
  assert.deepEqual(second, first);
});

test('owner keys', () => {
  assert.equal(owner('sc-abc'), 'ln-abc');
  assert.equal(owner('ch-abc'), 'ln-abc');
  assert.equal(owner('pa-abc'), 'ln-abc');
  assert.equal(owner('ich-7'), 'idl-7');
  assert.equal(owner('ln-abc'), '');
  assert.equal(owner('ac-x'), '');
});

// A seeded fuzz: the invariants hold for arbitrary re-rankings.
function rng(seed) { return () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648); }
test('fuzz: nothing at or above the mark moves; nothing is lost or doubled', () => {
  const r = rng(1234);
  for (let round = 0; round < 3000; round++) {
    const n = 3 + Math.floor(r() * 25);
    const prev = Array.from({length: n}, (_, i) => 'k' + i);
    const hi = Math.floor(r() * n);
    const high = prev[hi];
    let server = prev.filter(() => r() > 0.15);
    for (let j = 0; j < 4; j++) if (r() < 0.5) server.splice(Math.floor(r() * (server.length + 1)), 0, 'new' + round + '_' + j);
    server = server.sort(() => r() - 0.5);
    const got = place(prev, server, high, {keepDropped: true});
    const out = got.order;
    assert.equal(new Set(out).size, out.length, 'no duplicates');
    const frozen = prev.slice(0, hi + 1);
    assert.deepEqual(out.slice(0, got.frozen), frozen, 'the block at/above the mark is exactly what was drawn there');
    for (const k of server) assert.ok(out.includes(k), 'every listed key is drawn: ' + k);
    const below = out.slice(got.frozen);
    const inServer = below.filter((k) => server.includes(k));
    // below the block: late rows first, then the rest in server order
    const rest = inServer.slice(got.late.length);
    const sorted = rest.slice().sort((a, b) => server.indexOf(a) - server.indexOf(b));
    assert.deepEqual(rest, sorted, 'below the late rows, the server order');
  }
});

// ---------------------------------------------------------------- the mark
function stubNode(line) {
  const classes = new Set(['sp-el', 'sp-dialogue']);
  const attrs = new Map();
  return {
    dataset: {line}, pineItem: {type: 'dialogue', line, id: 'ln-' + line}, isConnected: true, hidden: false,
    className: 'sp-el sp-dialogue',
    classList: {
      contains: (n) => classes.has(n), add: (...n) => n.forEach((x) => classes.add(x)),
      remove: (...n) => n.forEach((x) => classes.delete(x)),
      toggle: (n, f) => { if (f === undefined) f = !classes.has(n); if (f) classes.add(n); else classes.delete(n); }
    },
    getAttribute: (n) => (n.startsWith('data-') ? node_ds(n) : attrs.get(n)) ?? null,
    setAttribute: (n, v) => attrs.set(n, String(v)), removeAttribute: (n) => attrs.delete(n),
    getBoundingClientRect: () => ({top: 10, bottom: 30, height: 20}),
    attrs
  };
  function node_ds() { return null; }
}

test('the mark only moves down; a licence lets it go back up', (t) => {
  const oldDoc = global.document;
  const nodes = ['l1', 'l2', 'l3', 'l4'].map(stubNode);
  global.document = {
    getElementById: () => null,
    querySelector: (sel) => {
      const m = sel.match(/data-line="([^"]+)"/);
      return m ? nodes.find((n) => n.dataset.line === m[1]) || null : null;
    },
    querySelectorAll: (sel) => sel === '.sp-el.sp-now' ? nodes.filter((n) => n.classList.contains('sp-now')) : []
  };
  t.after(() => { script.marks.lines.clear(); script.marks.reset(); global.document = oldDoc; });
  script.marks.reset();
  script.folds.bind(nodes, nodes.map((n) => n.pineItem), 0);   // seats 0..3
  const lit = () => nodes.filter((n) => n.classList.contains('sp-now')).map((n) => n.dataset.line);

  script.view.placeMarks({mark: 'air', line_id: 'l2'});
  assert.deepEqual(lit(), ['l2']);
  script.view.placeMarks({mark: 'air', line_id: 'l3'});
  assert.deepEqual(lit(), ['l3'], 'down is allowed');
  script.view.placeMarks({mark: 'air', line_id: 'l1'});
  assert.deepEqual(lit(), ['l3'], 'up is refused: the mark holds');
  assert.equal(script.linear.snapshot().refused.id, 'l1');
  assert.equal(script.linear.snapshot().refusals, 1);
  script.view.placeMarks({mark: 'none'});
  assert.deepEqual(lit(), [], 'nothing sounding clears the mark');
  script.view.placeMarks({mark: 'air', line_id: 'l2'});
  assert.deepEqual(lit(), [], 'a quiet spell is not a door back up the page');
  script.view.placeMarks({mark: 'air', line_id: 'l4'});
  assert.deepEqual(lit(), ['l4']);
  script.linear.allowUp('seek', 5000);
  script.view.placeMarks({mark: 'air', line_id: 'l1'});
  assert.deepEqual(lit(), ['l1'], 'an explicit seek may move it up');
  assert.equal(script.linear.snapshot().high, 'l4', 'the high-water stays where the reading got to');
  script.linear.allowUp('replay', 5000, 'l2');
  script.view.placeMarks({mark: 'air', line_id: 'l3'});
  script.view.placeMarks({mark: 'air', line_id: 'l2'});
  assert.deepEqual(lit(), ['l2'], 'a replay licence covers its own line');
  script.linear.allowUp('replay', 5000, 'l3');
  script.view.placeMarks({mark: 'air', line_id: 'l4'});
  script.view.placeMarks({mark: 'air', line_id: 'l1'});
  assert.deepEqual(lit(), ['l4'], '...and no other');
});

test('fuzz with cues, notes and prepared rows: groups stay whole, nothing is lost', () => {
  const r = rng(98765);
  for (let round = 0; round < 3000; round++) {
    // prev: a drawn page of groups [ch-i?] ln-i [nt-i?], in order
    const groups = [];
    const n = 3 + Math.floor(r() * 14);
    for (let i = 0; i < n; i++) groups.push({i, cue: r() < 0.6, note: r() < 0.15, up: r() < 0.2});
    const keysOf = (g) => [].concat(g.cue ? ['ch-' + g.i] : [], ['ln-' + g.i], g.note ? ['nt-' + g.i] : []);
    const prev = groups.flatMap(keysOf);
    const lines = groups.map((g) => 'ln-' + g.i);
    const high = lines[Math.floor(r() * lines.length)];
    // server: groups re-ranked, some dropped, some new, cues toggled
    let sg = groups.filter(() => r() > 0.1).map((g) => ({...g, cue: r() < 0.2 ? !g.cue : g.cue}));
    for (let j = 0; j < 3; j++) if (r() < 0.5) sg.push({i: 100 + j, cue: r() < 0.6, note: r() < 0.2, up: r() < 0.3});
    sg = sg.sort(() => r() - 0.5);
    const server = sg.flatMap(keysOf);
    const hangMap = {};
    sg.forEach((g) => { if (g.note) hangMap['nt-' + g.i] = 'ln-' + g.i; });
    const upSet = new Set(sg.filter((g) => g.up).map((g) => 'ln-' + g.i));
    const got = place(prev, server, high, {owner, hangs: (k) => hangMap[k] || '',
      upcoming: (k) => upSet.has(k), keepDropped: true});
    const out = got.order;
    assert.equal(new Set(out).size, out.length, 'no duplicates');
    for (const k of server) {
      assert.ok(out.includes(k) || got.skipped.includes(k), 'listed key drawn or knowingly skipped: ' + k);
    }
    for (const k of got.skipped) {
      const line = owner(k);
      assert.ok(out.indexOf(line) >= 0 && out.indexOf(line) < got.frozen, 'a skipped cue belongs to a line above the mark');
    }
    // the frozen block: prev's keys, same relative order; only hung notes are new
    const block = out.slice(0, got.frozen);
    const fromPrev = block.filter((k) => prev.includes(k));
    const prevOrder = prev.filter((k) => fromPrev.includes(k));
    assert.deepEqual(fromPrev, prevOrder, 'nothing above the mark changes order');
    for (const k of block) assert.ok(prev.includes(k) || got.hung.includes(k), 'nothing new above the mark but a note: ' + k);
    assert.ok(block.includes(high), 'the mark row itself stays in the block');
    // every drawn cue sits above its drawn line
    for (const k of out) {
      if (!k.startsWith('ch-')) continue;
      const line = owner(k);
      if (out.includes(line)) assert.ok(out.indexOf(k) < out.indexOf(line), 'cue above its line: ' + k);
    }
    // a note is drawn after its line
    for (const k of out) {
      if (!k.startsWith('nt-') || !hangMap[k]) continue;
      if (out.includes(hangMap[k])) assert.ok(out.indexOf(k) > out.indexOf(hangMap[k]), 'note after its line: ' + k);
    }
  }
});
