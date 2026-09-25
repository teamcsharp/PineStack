const assert = require('node:assert/strict');
const {test} = require('node:test');
const script = require('../desktop/renderer/script-page.js');

function node(item) {
  const attrs = new Map();
  const classes = new Set(['sp-el', 'sp-' + item.type]);
  const result = {
    pineItem: item, dataset: {seg: item.seg, line: item.line || '',
      at: String(item.at || ''), block: String(item.block || '')},
    textContent: item.text || '', hidden: false, parentNode: null,
    className: [...classes].join(' '),
    classList: {
      contains(name) { return classes.has(name); },
      add(...names) { names.forEach((name) => classes.add(name)); result.className = [...classes].join(' '); },
      remove(...names) { names.forEach((name) => classes.delete(name)); result.className = [...classes].join(' '); },
      toggle(name, force) {
        if (force === undefined) force = !classes.has(name);
        if (force) classes.add(name); else classes.delete(name);
        result.className = [...classes].join(' ');
      }
    },
    get isConnected() { return !!this.parentNode; },
    get nextSibling() {
      if (!this.parentNode) return null;
      return this.parentNode.children[this.parentNode.children.indexOf(this) + 1] || null;
    },
    get previousElementSibling() {
      if (!this.parentNode) return null;
      return this.parentNode.children[this.parentNode.children.indexOf(this) - 1] || null;
    },
    getAttribute(name) {
      if (name.startsWith('data-')) return this.dataset[name.slice(5)] || '';
      return attrs.get(name) || '';
    },
    setAttribute(name, value) { attrs.set(name, String(value)); },
    removeAttribute(name) { attrs.delete(name); },
    querySelector() { return null; },
    remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    getBoundingClientRect() {
      if (!this.parentNode || this.hidden) return {top: 0, bottom: 0, height: 0};
      const top = 20 + this.parentNode.children.indexOf(this) * 24 - this.parentNode.scrollTop;
      return {top, bottom: top + 20, height: 20};
    },
    scrollIntoView() { this.scrolled = true; }
  };
  return result;
}

function pane() {
  return {
    children: [], scrollTop: 0, clientHeight: 500, scrollHeight: 1000,
    writes: 0,
    get firstChild() { return this.children[0] || null; },
    removeChild(child) {
      const index = this.children.indexOf(child);
      if (index >= 0) this.children.splice(index, 1);
      child.parentNode = null;
      this.writes++;
    },
    insertBefore(child, before) {
      if (child.parentNode) child.parentNode.removeChild(child);
      const index = before ? this.children.indexOf(before) : this.children.length;
      assert.ok(index >= 0);
      this.children.splice(index, 0, child);
      child.parentNode = this;
      this.writes++;
    },
    appendChild(child) { this.insertBefore(child, null); },
    querySelectorAll(selector) {
      if (selector === '.sp-el') return this.children.filter((child) => child.classList.contains('sp-el'));
      if (selector === '.sp-el.sp-now') return this.children.filter((child) => child.classList.contains('sp-now'));
      return [];
    },
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; },
    getBoundingClientRect() { return {top: 0, bottom: 500, height: 500}; }
  };
}

test('folded bodies detach; heading, keyed lines, jump, live chase and anchor survive', async (t) => {
  const oldDocument = global.document;
  const oldAnimationFrame = global.requestAnimationFrame;
  const box = pane();
  const items = [
    {id: 'head-a', type: 'scene', seg: 'fold-test-a', text: 'Past', at: 100},
    {id: 'body-a', type: 'dialogue', seg: 'fold-test-a', line: 'line-a',
      text: 'Earlier words', block: 1, seconds: 12},
    {id: 'head-b', type: 'scene', seg: 'fold-test-b', text: 'Current', at: 200},
    {id: 'body-b', type: 'dialogue', seg: 'fold-test-b', line: 'line-b',
      text: 'Current words', block: 2, seconds: 15},
    {id: 'head-c', type: 'scene', seg: 'fold-test-c', text: 'Upcoming', at: 300},
    {id: 'body-c', type: 'dialogue', seg: 'fold-test-c', line: 'line-c',
      text: 'Next words', block: 3, seconds: 18}
  ];
  const nodes = items.map(node);
  global.requestAnimationFrame = (fn) => { fn(); return 1; };
  global.document = {
    getElementById(id) { return id === 'spScript' ? box : null; },
    querySelector(selector) {
      const match = selector.match(/^\.sp-el\[data-line="([^"]+)"\]$/);
      return match ? box.children.find((child) => child.dataset.line === match[1]) || null : null;
    },
    querySelectorAll(selector) {
      if (selector === '.sp-el.sp-now') return box.querySelectorAll(selector);
      return [];
    }
  };
  t.after(() => {
    script.view.placeMarks({mark: 'none'});
    script.marks.lines.clear();
    script.marks.reset();
    global.document = oldDocument;
    global.requestAnimationFrame = oldAnimationFrame;
  });

  script.folds.bind(nodes, items, 250);
  script.folds.apply(false);
  assert.deepEqual(box.children.map((child) => child.pineItem.id),
    ['head-a', 'head-b', 'body-b', 'head-c', 'body-c']);
  assert.equal(nodes[1].parentNode, null);
  assert.equal(script.marks.lines.get('line-a'), nodes[1]);
  assert.deepEqual(script.folds.count('fold-test-a'), {lines: 1, seconds: 12});
  assert.equal(script.segments.identity(nodes[0]).block, '1',
    'folded heading still resolves its block for inspect and export');

  box.scrollTop = 20;
  const anchor = script.marks.anchor(box);
  const writes = box.writes;
  script.folds.apply(false);
  script.marks.restore(box, anchor);
  assert.equal(box.writes, writes, 'unchanged folded pages do not restitch nodes');
  assert.equal(box.scrollTop, 20);

  script.folds.jump('line-a');
  assert.equal(nodes[1].parentNode, box);
  assert.equal(nodes[1].scrolled, true);
  assert.equal(box.children.indexOf(nodes[1]), box.children.indexOf(nodes[0]) + 1);
  script.folds.apply(false);
  assert.equal(nodes[1].parentNode, box, 'a reader-opened past segment stays open');

  script.folds.toggle('fold-test-a');
  await new Promise((resolve) => setTimeout(resolve, 350));
  assert.equal(nodes[1].parentNode, null, 'closed body detaches after its fold transition');
  script.folds.toggle('fold-test-a');
  assert.equal(nodes[1].parentNode, box, 'heading expansion remounts the keyed line immediately');
  await new Promise((resolve) => setTimeout(resolve, 350));
  script.folds.toggle('fold-test-a');
  await new Promise((resolve) => setTimeout(resolve, 350));
  assert.equal(nodes[1].parentNode, null);
  script.view.placeMarks({mark: 'air', line_id: 'line-a'});
  assert.equal(nodes[1].parentNode, box, 'live chase reopens the detached line immediately');
  assert.equal(nodes[1].classList.contains('sp-now'), true);
  assert.equal(box.querySelectorAll('.sp-el.sp-now').length, 1);
  assert.equal(nodes[5].parentNode, box, 'future preview remains mounted');
  await new Promise((resolve) => setTimeout(resolve, 350));
});

test('a long script mounts headings and the active scene, not thousands of past lines', (t) => {
  const oldDocument = global.document;
  const box = pane();
  const items = [];
  for (let segment = 0; segment < 50; segment++) {
    const seg = 'fold-scale-' + segment;
    items.push({id: 'head-' + segment, type: 'scene', seg,
      text: 'Scene ' + segment, at: 100 + segment});
    for (let line = 0; line < 70; line++) {
      items.push({id: 'body-' + segment + '-' + line, type: 'dialogue',
        seg, line: 'line-' + segment + '-' + line, text: 'Prepared line', seconds: 3});
    }
  }
  const nodes = items.map(node);
  global.document = {getElementById(id) { return id === 'spScript' ? box : null; }};
  t.after(() => { script.marks.lines.clear(); global.document = oldDocument; });

  script.folds.bind(nodes, items, 149);
  script.folds.apply(false);
  assert.equal(nodes.length, 3550);
  assert.equal(box.children.length, 120, '50 headings and 70 live-scene lines remain mounted');
  assert.equal(nodes.filter((child) => !child.isConnected).length, 3430);
  assert.equal(script.marks.lines.size, 3500, 'every detached line remains addressable');
  const writes = box.writes;
  script.folds.apply(false);
  assert.equal(box.writes, writes, 'an unchanged poll does not remount past lines');

  const reordered = nodes.slice();
  const last = reordered.length - 1;
  [reordered[last - 1], reordered[last]] = [reordered[last], reordered[last - 1]];
  script.folds.bind(reordered, items, 149);
  script.folds.apply(false);
  assert.equal(box.children.length, 120);
  assert.equal(box.children.at(-2), nodes[last]);
  assert.equal(box.children.at(-1), nodes[last - 1]);
  assert.equal(nodes[1].parentNode, null, 'a reindex does not remount folded history');
  assert.equal(script.marks.lines.get(nodes[last].dataset.line), nodes[last],
    'the line index still points to the keyed node');

  box.scrollTop = 110 * 24;
  const anchor = script.marks.anchor(box);
  assert.ok(anchor.node && anchor.node.pineItem.seg === 'fold-scale-49');
  const inserted = {id: 'new-live-line', type: 'dialogue', seg: 'fold-scale-49',
    line: 'new-live-line', text: 'Inserted before the reader', seconds: 3};
  const insertedNode = node(inserted);
  const expanded = reordered.slice();
  expanded.splice(3490, 0, insertedNode);
  script.folds.bind(expanded, items.concat(inserted), 149);
  script.folds.apply(false);
  script.marks.restore(box, anchor);
  assert.equal(anchor.node.parentNode, box);
  assert.equal(box.scrollTop, 110 * 24 + 24,
    'the same keyed reader line stays seated after an insertion above it');
  assert.equal(nodes[1].parentNode, null);
});
