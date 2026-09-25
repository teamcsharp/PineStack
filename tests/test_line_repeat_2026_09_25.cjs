const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {}; this._text = ''; }
  set textContent(text) { this._text = String(text); this.children = []; }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  appendChild(node) { this.children.push(node); node.parentNode = this; return node; }
  replaceChildren(...nodes) { this.children = []; this._text = ''; nodes.forEach(n => this.appendChild(n)); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(n => n !== this); }
  setAttribute(key, value) { this.attrs[key] = value; }
  addEventListener(event, fn) { this.listeners[event] = fn; }
  click() { if (!this.disabled) this.listeners.click?.({}); }
  focus() { document.activeElement = this; }
  querySelector(selector) {
    if (selector === 'span:last-child') return this.children.filter(n => n.tagName === 'span').at(-1);
    return null;
  }
}
const doc = {body: new Element('body'), head: new Element('head'), currentScript: null,
  createElement: tag => new Element(tag), querySelector: () => null,
  addEventListener() {}, removeEventListener() {}};
globalThis.document = doc;
const modal = require('../desktop/renderer/line-repeat.js');
const flatten = node => [node, ...node.children.flatMap(flatten)];
const button = title => flatten(doc.body).find(n => n.tagName === 'button' && n.title === title);
const flush = () => new Promise(resolve => setImmediate(resolve));
const report = () => ({ok: true, line_id: 'server-id', text: 'Exact words.', played_24h: 3,
  occurrences_24h: 5, writing_iterations: 2, coverage: 'Receipts only', causes: ['Same audio reused.'],
  carriers: [], iterations: [], history: [], current_inputs: [], current_prompt: {}, can_generate: true});

test('opening is read-only and block requires a second explicit confirmation', async () => {
  const posts = [];
  globalThis.pineDesktop = {get: async () => report(), post: async (url, data) => {
    posts.push({url, data}); return {ok: true, say: 'Blocked permanently'};
  }};
  modal.open({id: 'dom-id', said: 'Label from DOM'}); await flush();
  assert.equal(posts.length, 0);
  assert.match(doc.body.textContent, /3Confirmed plays/);
  button('Never play this line again').click();
  assert.equal(posts.length, 0);
  button('Cancel').click(); assert.equal(posts.length, 0);
  button('Never play this line again').click(); button('Block line').click(); await flush();
  assert.deepEqual(posts, [{url: '/api/said/forget', data: {line_id: 'server-id', text: 'Exact words.'}}]);
  assert.equal(button('Never play this line again').disabled, true);
  modal.close();
});

test('failed repair remains visible and can be retried', async () => {
  globalThis.pineDesktop = {get: async () => report(), post: async () => { throw new Error('writer offline'); }};
  modal.open({id: 'id', said: 'Words'}); await flush();
  button('Generate fresh material').click(); await flush();
  assert.match(doc.body.textContent, /writer offline/);
  assert.equal(button('Generate fresh material').disabled, false);
  modal.close();
});

test('late read from an older selection cannot replace the current line', async () => {
  let finish;
  globalThis.pineDesktop = {get: () => new Promise(resolve => { finish = resolve; })};
  modal.open({id: 'old', said: 'Old'});
  await Promise.resolve();
  const old = finish;
  modal.open({id: 'new', said: 'New'});
  await Promise.resolve();
  finish({...report(), text: 'Current line'}); await flush();
  old({...report(), text: 'Stale line'}); await flush();
  assert.match(doc.body.textContent, /Current line/);
  assert.doesNotMatch(doc.body.textContent, /Stale line/);
  modal.close();
});

test('read failures offer Retry; unknown source disables generation', async () => {
  globalThis.pineDesktop = {get: async () => { throw new Error('offline'); }};
  modal.open({id: 'id', said: 'Words'}); await flush();
  assert.match(doc.body.textContent, /Diagnostics unavailable: offline/);
  globalThis.pineDesktop.get = async () => ({...report(), can_generate: false, generation_why: 'Source unknown'});
  button('Retry').click(); await flush();
  assert.equal(button('Generate fresh material')?.disabled, undefined);
  const generate = flatten(doc.body).find(n => n.attrs['aria-label'] === 'Generate fresh material');
  assert.equal(generate.disabled, true);
  assert.match(doc.body.textContent, /Source unknown/);
  modal.close();
});

test('recycle precedes the graph and tablet assets include script and stylesheet', () => {
  const root = path.join(__dirname, '..');
  const actions = fs.readFileSync(path.join(root, 'desktop/renderer/line-actions.js'), 'utf8');
  assert.ok(actions.indexOf("icon('c:recycle')") < actions.indexOf("icon('c:chart--network')"));
  for (const ext of ['js', 'css']) assert.equal(
    fs.readFileSync(path.join(root, 'desktop/renderer/line-repeat.' + ext), 'utf8'),
    fs.readFileSync(path.join(root, 'app/src/main/assets/pine-views/line-repeat.' + ext), 'utf8'));
  const assets = fs.readFileSync(path.join(root, 'app/src/main/java/com/pinebox/kiosk/bridge/ViewAssets.kt'), 'utf8');
  assert.match(assets, /"line-repeat\.js"/); assert.match(assets, /"line-repeat\.css"/);
});
