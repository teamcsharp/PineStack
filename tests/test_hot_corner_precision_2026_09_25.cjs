const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const desktop = path.join(__dirname, '../desktop/renderer/hot-corners.js');
const tablet = path.join(__dirname, '../app/src/main/assets/pine-views/hot-corners.js');
const source = fs.readFileSync(desktop, 'utf8');

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.nodeType = 1;
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.attrs = {};
    this.className = '';
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); child.parentNode = null; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter(candidate => candidate !== fn);
  }
  fire(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name] || null; }
}

function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }

function setup() {
  const document = new Element('document');
  document.body = new Element('body');
  document.documentElement = new Element('html');
  document.createElement = tag => new Element(tag);
  document.getElementById = () => null;
  const root = new Element('window');
  Object.assign(root, {
    document,
    innerWidth: 1200,
    innerHeight: 800,
    location: {protocol: 'http:', href: 'http://127.0.0.1:8096/', origin: 'http://127.0.0.1:8096'},
    setTimeout: () => 1,
    clearTimeout() {},
  });
  const context = vm.createContext({window: root, Promise, console, setTimeout: () => 1, clearTimeout() {}});
  vm.runInContext(source, context);
  return {root, document, api: root.PineHotCorners};
}

test('tablet mirror is identical to the desktop hot-corner gesture', () => {
  assert.equal(fs.readFileSync(tablet, 'utf8'), source);
});

test('activation zone is narrow by default and bounded when configured', () => {
  const {api} = setup();
  assert.equal(api.config().activationZonePx, 42);
  assert.equal(api._cornerAt(42, 0, 1200, 800), 'tl');
  assert.equal(api._cornerAt(43, 0, 1200, 800), '');
  api.configure({activationZonePx: 1});
  assert.equal(api.config().activationZonePx, 20);
  api.configure({activationZonePx: 999});
  assert.equal(api.config().activationZonePx, 120);
});

test('sensitivity changes the gesture threshold instead of only changing its label', () => {
  const {api} = setup();
  api.configure({sensitivity: 0});
  assert.equal(api._judge('tl', 140, 140, 1000).state, 'going');
  api.configure({sensitivity: 100});
  assert.equal(api._judge('tl', 140, 140, 1000).state, 'commit');
  assert.equal(api.config().sensitivity, 100);
});

test('a pointer that begins on a button is never adopted as a corner gesture', () => {
  const {root, document} = setup();
  const button = document.body.appendChild(new Element('button'));
  root.fire('pointerdown', {
    pointerId: 1, isPrimary: true, pointerType: 'touch', clientX: 10, clientY: 10, target: button,
  });
  assert.equal(descendants(document.body).some(node => node.className === 'hc-glow on tl'), false);
});
