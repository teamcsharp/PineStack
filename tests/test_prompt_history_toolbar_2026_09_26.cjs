const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(
  path.join(root, 'desktop/renderer/prompt-history.js'), 'utf8');
const css = fs.readFileSync(
  path.join(root, 'desktop/renderer/prompt-history.css'), 'utf8');

class FakeClassList {
  constructor(node) { this.node = node; this.names = new Set(); }
  toggle(name, force) {
    const on = force === undefined ? !this.names.has(name) : !!force;
    if (on) this.names.add(name); else this.names.delete(name);
    return on;
  }
  contains(name) { return this.names.has(name); }
}

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag || '').toUpperCase();
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.className = '';
    this.classList = new FakeClassList(this);
    this.hidden = false;
    this.isConnected = true;
    this.value = '';
  }
  appendChild(node) { this.children.push(node); node.parentNode = this; return node; }
  insertBefore(node, before) {
    if (node.parentNode) node.parentNode.children = node.parentNode.children.filter(child => child !== node);
    const at = this.children.indexOf(before);
    this.children.splice(at < 0 ? 0 : at, 0, node); node.parentNode = this; return node;
  }
  get firstChild() { return this.children[0] || null; }
  replaceChildren(...nodes) { this.children = []; nodes.forEach(node => this.appendChild(node)); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, run) { (this.listeners[name] ||= []).push(run); }
  querySelector(selector) {
    const wanted = selector.startsWith('.') ? selector.slice(1) : selector;
    if (String(this.className).split(/\s+/).includes(wanted)) return this;
    for (const child of this.children) {
      const found = child.querySelector && child.querySelector(selector);
      if (found) return found;
    }
    return null;
  }
}

function click(node) {
  const event = {preventDefault() {}, stopPropagation() {}};
  (node.listeners.click || []).forEach(run => run(event));
}

function fixture() {
  const document = {
    createElement: tag => new FakeNode(tag),
    execCommand: () => true,
    body: new FakeNode('body'),
  };
  const pineDesktop = {
    get: path => Promise.resolve(path.includes('/config')
      ? {nodes: [], roles: []}
      : {rows: [], models: [], coverage: 'ready', next: 0}),
    post: () => Promise.resolve({value: '', say: 'saved'}),
  };
  const window = {pineDesktop, pineIcon: icon => '<i>' + icon + '</i>', setTimeout, clearTimeout};
  vm.runInNewContext(source, {window, document, navigator: {}});
  return {api: window.PinePromptHistory, host: new FakeNode('div'),
    trigger: new FakeNode('button'), toolbar: new FakeNode('div')};
}

test('prompt controls stay in the Script top bar and expose a fullscreen exit', () => {
  const f = fixture();
  f.api.toggle(f.host, f.trigger, f.toolbar);
  const panel = f.host.querySelector('.ph-panel');
  const bar = f.toolbar.querySelector('.ph-bar');
  const enter = bar.children[1].children.find(node =>
    node.attributes['aria-label'] === 'Fullscreen system prompt history');
  const exit = bar.querySelector('.ph-exit-fullscreen');

  assert.ok(panel && bar && enter && exit);
  assert.equal(panel.hidden, false);
  click(enter);
  assert.equal(panel.classList.contains('ph-fullscreen'), true);
  assert.equal(bar.parentNode, panel, 'the top bar travels above the fullscreen panel');
  assert.equal(enter.hidden, true);
  assert.equal(exit.hidden, false);
  click(exit);
  assert.equal(panel.classList.contains('ph-fullscreen'), false);
  assert.equal(bar.parentNode, f.toolbar, 'the top bar returns to the Script header');
  assert.equal(enter.hidden, false);
  assert.equal(exit.hidden, true);
  assert.match(css, /\.ph-exit-fullscreen/);
});

test('closing prompt history hides its docked top bar', () => {
  const f = fixture();
  f.api.toggle(f.host, f.trigger, f.toolbar);
  const bar = f.toolbar.querySelector('.ph-bar');
  f.api.toggle(f.host, f.trigger, f.toolbar);
  assert.equal(f.host.querySelector('.ph-panel').hidden, true);
  assert.equal(bar.hidden, true);
  assert.equal(f.trigger.attributes['aria-pressed'], 'false');
});

test('prompt copy uses the Windows desktop clipboard bridge', () => {
  assert.match(source, /root\.pineDesktop\.copyText\(text\)/);
  assert.match(source, /System prompt copied to the Windows clipboard/);
  assert.match(source, /The Windows clipboard refused the system prompt/);
  assert.match(source, /copied = !!document\.execCommand\('copy'\)/);
});
