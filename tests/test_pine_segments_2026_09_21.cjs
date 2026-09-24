/* #1226: a dropped story becomes a plotline the station can actually take.
 *
 * The operator dropped "the-long-delay.md" - 33 transmissions across 58 years,
 * an H1 title and a long run of H2 sections - and asked for it to play out
 * "over the next 5-10 hours as a plotline".
 *
 * The parse is the part that can silently be wrong: the API caps acts at 24
 * and each at 600 characters, so a document that reads as one act, or as 33,
 * or whose acts arrive empty, would be accepted by the server and be wrong on
 * the air. These pin the shape rather than the prose.
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* The module attaches itself to whatever it is given as `window`. It needs no
   DOM for the parser, which is the half worth testing here. */
function loadSegments(window) {
  const src = fs.readFileSync(
    path.join(__dirname, '../desktop/renderer/pine-segments.js'), 'utf8');
  const sandbox = {window: window || {}, globalThis: {}};
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  return sandbox.window.PineSegments;
}

const LONG_DELAY = [
  '# THE LONG DELAY',
  '',
  '### 33 transmissions across 58 years',
  '',
  '## 001 - Age 25',
  'Automated relay, this is Korrin, Elias, survey technician second class.',
  'Bearing two-seven-one mark four.',
  '',
  '## 002 - Age 25',
  'I ran the propagation math. The relay chain is broken at three points.',
  '',
  '## 003 - Age 25',
  'I live in the aft hull section.',
].join('\n');

test('the title comes off the H1, not the filename', () => {
  const S = loadSegments();
  const got = S.read(LONG_DELAY, 'the-long-delay.md');
  assert.equal(got.title, 'THE LONG DELAY');
});

test('each heading becomes one act, carrying its own text', () => {
  const S = loadSegments();
  const got = S.read(LONG_DELAY, 'x.md');
  /* The H3 subtitle counts too - it is a heading and it is part of the piece. */
  assert.ok(got.acts.length >= 3, 'got ' + got.acts.length + ' acts');
  const first = got.acts.find((a) => a.indexOf('001') === 0);
  assert.ok(first, 'the first transmission is an act of its own');
  assert.match(first, /Korrin, Elias, survey technician second class/,
    'and it carries its body, not just its heading');
});

test('the acts are capped the way the station caps them', () => {
  const S = loadSegments();
  /* 40 sections: more than the API's 24. */
  let doc = '# Big\n';
  for (let i = 1; i <= 40; i += 1) doc += '\n## Act ' + i + '\nSomething happens.\n';
  const got = S.read(doc, 'big.md');
  assert.equal(got.acts.length, 24,
    'the API takes 24; sending more would be silently truncated by the server');
  got.acts.forEach((a) => assert.ok(a.length <= 600, 'each act is within 600 chars'));
});

test('a long section is trimmed rather than allowed to run away', () => {
  const S = loadSegments();
  const doc = '# T\n\n## One\n' + ('word '.repeat(400));
  const got = S.read(doc, 'long.md');
  assert.ok(got.acts[0].length <= 600);
});

test('a document with no headings still yields acts, from its paragraphs', () => {
  const S = loadSegments();
  const doc = 'A thing happens.\n\nThen another thing.\n\nThen it ends.';
  const got = S.read(doc, 'plain.md');
  assert.equal(got.acts.length, 3);
  assert.equal(got.title, 'A thing happens.');
});

test('a document with nothing usable still names itself from the file', () => {
  const S = loadSegments();
  const got = S.read('', 'a-quiet-night.md');
  assert.equal(got.title, 'a-quiet-night.md');
  assert.equal(got.acts.length, 0,
    'and offers no acts, so the sheet cannot start an empty plot');
});

test('the module exposes what the glass and the drop road need', () => {
  const S = loadSegments();
  ['pane', 'topics', 'topicWindow', 'acceptDrops', 'plotWindow', 'read', 'close']
    .forEach((name) => assert.equal(typeof S[name], 'function', name));
});

test('it never reaches for a DOM just to parse', () => {
  /* The sandbox above has no document at all. If read() touched one, every
     test in this file would have thrown before reaching here. */
  const S = loadSegments();
  assert.ok(S.read('# ok\n\n## a\nb', 'x.md').acts.length > 0);
});

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.className = '';
    this.textContent = '';
    this.value = '';
    this.attributes = {};
    const names = new Set();
    this.classList = {
      add: name => names.add(name), remove: name => names.delete(name),
      contains: name => names.has(name)
    };
  }
  appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
  removeChild(node) {
    this.children = this.children.filter((child) => child !== node);
    node.parentNode = null;
  }
  replaceChildren(...nodes) {
    this.children.forEach(child => { child.parentNode = null; });
    this.children = [];
    nodes.forEach(node => this.appendChild(node));
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, fn) {
    if (!this.listeners[name]) this.listeners[name] = [];
    this.listeners[name].push(fn);
  }
  querySelector(selector) {
    const cls = selector.charAt(0) === '.' ? selector.slice(1) : '';
    if (cls && String(this.className).split(/\s+/).includes(cls)) return this;
    for (const child of this.children) {
      const found = child.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
  focus() { this.focused = true; }
  fire(name, event) {
    for (const fn of this.listeners[name] || []) fn(event || {});
  }
}

function fakeDocument() {
  return {body: new FakeNode('body'), createElement: tag => new FakeNode(tag)};
}

test('the script topic window is singular and queues the scenario next', async () => {
  const document = fakeDocument(), posts = [];
  const root = {
    document,
    pineDesktop: {
      get: () => Promise.resolve({topics: []}),
      post: (route, body) => {
        posts.push({route, body});
        return Promise.resolve({id: 'topic-1', queued: true, queue_position: 1});
      }
    }
  };
  const S = loadSegments(root);
  const first = S.topicWindow();
  assert.equal(S.topicWindow(), first, 'opening twice returns the standing sheet');
  assert.equal(document.body.children.length, 1);
  const input = first.querySelector('.pseg-topic-in');
  const queue = first.querySelector('.pseg-next');
  queue.fire('click');
  assert.equal(posts.length, 0, 'empty scenarios are not sent');
  input.value = 'the station manager is secretly in the studio';
  queue.fire('click');
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(posts, [{route: '/api/dj/topics', body: {
    text: 'the station manager is secretly in the studio', kind: 'topic', next: true
  }}]);
  assert.equal(input.value, '');
  assert.match(first.querySelector('.pseg-note').textContent, /saved and queued/);
});

test('the Script toolbar puts the scenario control between views and video', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '../desktop/renderer/script-page.js'), 'utf8');
  const bar = src.slice(src.indexOf('  function buildBar()'),
    src.indexOf('  function buildSaying()', src.indexOf('  function buildBar()')));
  assert.match(bar, /pineIcon\('c:add'/);
  assert.match(bar, /PineSegments[\s\S]{0,100}topicWindow/);
  assert.ok(bar.indexOf('bar.appendChild(pick)') < bar.indexOf('bar.appendChild(topic)'));
  assert.ok(bar.indexOf('bar.appendChild(topic)') < bar.indexOf('bar.appendChild(reel)'));
});

test('the tablet scenario sheet mutes dictation and exposes saved topic actions', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '../desktop/renderer/pine-segments.js'), 'utf8');
  assert.match(src, /PineDuck\.hold\('pseg-topic-dictation', 0, wrap\)/);
  assert.match(src, /addEventListener\('pointerdown', dictationTap, true\)/);
  assert.match(src, /dot\.finish\(\)/);
  assert.match(src, /history: true, microphone: true/);
  assert.match(src, /'\/api\/dj\/topics\/' \+ encodeURIComponent\(saved\.id\)/);
  assert.match(src, /actOn\(saved, 'queue'/);
  assert.match(src, /actOn\(saved, 'drop'/);
});
