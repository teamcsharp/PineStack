const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

class Node {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.parentNode = null;
    this.className = '';
    this.attributes = {};
    this.listeners = {};
    this._text = '';
    this.classList = {
      add: name => { this.className += ' ' + name; },
      remove: name => { this.className = this.className.split(' ').filter(x => x !== name).join(' '); },
      contains: name => this.className.split(' ').includes(name),
      toggle: (name, on) => {
        if (on) this.classList.add(name);
        else this.classList.remove(name);
      }
    };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  set innerHTML(value) {
    this._html = value;
    if (!this.classList.contains('ld-box')) return;
    const head = this.appendChild(new Node('div'));
    head.className = 'ld-head';
    head.appendChild(Object.assign(new Node('button'), {className: 'ld-forget'}));
    head.appendChild(Object.assign(new Node('button'), {className: 'ld-close'}));
    for (const name of ['ld-forget-feedback', 'ld-said', 'ld-body']) {
      this.appendChild(Object.assign(new Node('div'), {className: name}));
    }
  }
  get innerHTML() { return this._html || ''; }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  insertAdjacentElement(_where, child) {
    const at = this.parentNode.children.indexOf(this);
    this.parentNode.children.splice(at + 1, 0, child);
    child.parentNode = this.parentNode;
  }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this);
    this.parentNode = null;
  }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key] || null; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  click() { for (const fn of this.listeners.click || []) fn({stopPropagation() {}}); }
  querySelector(selector) {
    const cls = /^\.([\w-]+)$/.exec(selector);
    if (!cls) return null;
    for (const child of this.children) {
      if (child.classList.contains(cls[1])) return child;
      const found = child.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
}

const doc = {
  body: new Node('body'), head: new Node('head'), activeElement: null,
  currentScript: {src: 'file:///renderer/line-deep.js'},
  createElement: tag => new Node(tag),
  querySelector: selector => selector === 'link[data-pine-line-deep]'
    ? doc.head.children.find(x => x.attributes['data-pine-line-deep'] !== undefined) || null
    : null
};
globalThis.document = doc;
globalThis.location = {reload() {}};
const deep = require('../desktop/renderer/line-deep.js');
const flush = () => new Promise(resolve => setImmediate(resolve));

test('trash action needs identity and spoken text; confirmation posts exact values', async () => {
  let sent;
  let reloaded = 0;
  const later = [];
  const oldTimer = globalThis.setTimeout;
  globalThis.setTimeout = fn => { later.push(fn); return later.length; };
  globalThis.location.reload = () => { reloaded++; };
  globalThis.pineDesktop = {
    get: () => new Promise(() => {}),
    post: async (url, body) => { sent = {url, body}; return {ok: true, say: 'Forgotten.'}; }
  };
  try {
    deep.open({id: '', said: 'Words'});
    assert.equal(doc.body.querySelector('.ld-forget').disabled, true);
    deep.open({id: 'line-1', said: '   '});
    assert.equal(doc.body.querySelector('.ld-forget').disabled, true);
    deep.open({id: 'line-1', said: '  Exact words.  '});
    const trash = doc.body.querySelector('.ld-forget');
    assert.equal(trash.disabled, false);
    assert.equal(trash.attributes['data-pine-icon'], 'c:trash-can');
    trash.click();
    assert.equal(sent, undefined);
    doc.body.querySelector('.ld-forget-no').click();
    assert.equal(doc.body.querySelector('.ld-forget-confirm'), null);
    trash.click();
    doc.body.querySelector('.ld-forget-yes').click();
    await flush();
    assert.deepEqual(sent, {url: '/api/said/forget',
      body: {line_id: 'line-1', text: '  Exact words.  '}});
    assert.match(doc.body.querySelector('.ld-forget-feedback').textContent, /Forgotten.*Refreshing/);
    assert.equal(reloaded, 0);
    later.forEach(fn => fn());
    assert.equal(reloaded, 1);
    assert.equal(doc.body.querySelector('.ld-box'), null);
  } finally {
    deep.close();
    globalThis.setTimeout = oldTimer;
    delete globalThis.pineDesktop;
  }
});

test('server refusal stays in modal and can be retried', async () => {
  globalThis.pineDesktop = {
    get: () => new Promise(() => {}),
    post: async () => ({ok: false, detail: 'line not found'})
  };
  try {
    deep.open({id: 'line-2', said: 'Words'});
    doc.body.querySelector('.ld-forget').click();
    doc.body.querySelector('.ld-forget-yes').click();
    await flush();
    assert.match(doc.body.querySelector('.ld-forget-feedback').textContent,
      /Could not forget this line: line not found/);
    assert.equal(doc.body.querySelector('.ld-forget-yes').disabled, false);
  } finally {
    deep.close();
    delete globalThis.pineDesktop;
  }
});

test('crystal rows disclose full records, passage grade, and editable retained text', () => {
  const docRow = {file: 'ms3.md', how: 'speakbox lookup', text: 'Whole swath',
    passage_grade: 'written', passage_how: 'closest historical passage', at: 17};
  const vector = {query: 'old weather', file: 'kt1.md', score: 0.7, ms: 28};
  const all = {prov: {documents: [docRow], vectors: [vector]},
    why: {ok: true, systems: [{name: 'the vector index', note: 'ready'},
      {name: 'the speakbox', note: 'ready'}]}};
  const crystal = deep._test.stageFacts({id: 'line-3', said: 'Words'}, all)
    .find(x => x.key === 'crystal');
  const host = new Node('div');
  deep._test.factsInto(host, crystal.facts);
  const folds = host.children.filter(x => x.tagName === 'details');
  assert.deepEqual(folds.map(x => x.children[0].children[0].textContent),
    ['ms3.md', 'it searched for', 'the vector index', 'the speakbox']);
  const passage = folds[0].querySelector('.ld-crystal-evidence');
  assert.match(passage.textContent, /Written: closest historical passage/);
  assert.match(passage.textContent, /closest historical passage/);
  assert.match(passage.textContent, /"how": "speakbox lookup"/);
  assert.match(passage.textContent, /"at": 17/);
  assert.equal(passage.querySelector('.ld-tap').textContent, 'Whole swath');
  assert.match(folds[1].textContent, /Passage not retained for this search/);
  assert.match(folds[1].textContent, /"ms": 28/);
  const found = deep._test.crystalEvidence({query: 'old weather', file: 'kt1.md',
    text: 'Vector swath', score: 0.7, ms: 28}, 'vector');
  assert.equal(found.querySelector('.ld-tap').textContent, 'Vector swath');
  assert.match(found.textContent, /"query": "old weather"/);
  const current = deep._test.crystalEvidence({file: 'kt1.md', text: 'New opening',
    snippet: 'Legacy excerpt', passage_grade: 'current',
    passage_how: 'read from disk now'}, 'document');
  assert.match(current.textContent, /not the historical prompt/);
  assert.match(current.textContent, /read from disk now/);
  assert.match(current.textContent, /Legacy excerpt/);
  const absent = deep._test.crystalEvidence({passage_grade: 'absent',
    snippet: 'Older fallback'}, 'document');
  assert.match(absent.textContent, /Passage not retained for this source/);
  assert.doesNotMatch(absent.textContent, /Older fallback/);
  assert.equal(absent.querySelector('.ld-tap'), null);
});

test('desktop and tablet trace assets stay mirrored', () => {
  const base = path.join(__dirname, '..');
  for (const ext of ['js', 'css']) {
    assert.equal(fs.readFileSync(path.join(base, 'desktop/renderer/line-deep.' + ext), 'utf8'),
      fs.readFileSync(path.join(base, 'app/src/main/assets/pine-views/line-deep.' + ext), 'utf8'));
  }
});
