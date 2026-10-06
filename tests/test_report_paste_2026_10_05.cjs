'use strict';
/* [report-paste] Images can be pasted into the report pad (#1575, 2026-10-05).
 * The pad is driven with a small stand-in document: open it, paste, remove, send.
 * Run on local disk, never from the share:  node --test tests/test_report_paste_2026_10_05.cjs */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'talk-dot.js'), 'utf8');

function node(tag) {
  const n = { tagName: String(tag).toUpperCase(), children: [], listeners: {}, style: {}, attrs: {}, textContent: '', value: '',
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); },
    removeEventListener() {}, remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); },
    focus() {}, click() { (this.listeners.click || []).forEach(fn => fn({ stopPropagation() {}, preventDefault() {} })); },
    querySelector() { return null }, querySelectorAll() { return []; }, contains() { return false; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } } };
  Object.defineProperty(n, 'textContent', { get() { return this._t || ''; }, set(v) { this._t = String(v); if (v === '') this.children = []; } });
  return n;
}

function rig() {
  const posts = [];
  const body = node('body');
  const document = { body, createElement: node, createTextNode: (t) => ({ text: t }), getElementById: () => node('div'),
    addEventListener() {}, removeEventListener() {}, querySelector: () => null, querySelectorAll: () => [], readyState: 'complete' };
  const window = { document, pineDesktop: { post: (route, payload) => { posts.push([route, payload]); return Promise.resolve({ submitted: { id: 7 } }); },
                                              get: () => Promise.resolve({}) },
    addEventListener() {}, removeEventListener() {}, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    localStorage: { getItem: () => null, setItem() {} }, navigator: { mediaDevices: {} }, location: { href: 'file:///x' } };
  window.window = window; window.globalThis = window;
  function FileReader() { this.readAsDataURL = (file) => { this.result = file.dataUrl; if (file.bad) this.onerror(); else this.onload(); }; }
  const context = vm.createContext({ window, document, localStorage: window.localStorage, navigator: window.navigator, FileReader,
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {}, console, Promise, Array, String, Number, Math, JSON, Date, RegExp, Error });
  vm.runInContext(SOURCE, context);
  return { window, body, posts };
}

function paste(pad, files, text) {
  const items = files.map(f => ({ kind: 'file', type: f.type, getAsFile: () => f }));
  if (text) items.push({ kind: 'string', type: 'text/plain', getAsFile: () => null });
  let prevented = false;
  (pad.listeners.paste || []).forEach(fn => fn({ clipboardData: { items }, preventDefault() { prevented = true; } }));
  return prevented;
}
const png = (n) => ({ type: 'image/png', dataUrl: 'data:image/png;base64,AAA' + n });
const find = (root, pred) => { const out = []; (function walk(n) { if (pred(n)) out.push(n); (n.children || []).forEach(walk); })(root); return out; };

test('the report tool is published and opens a pad that listens for paste', () => {
  const r = rig();
  assert.equal(typeof r.window.PineReport.open, 'function');
  r.window.PineReport.open();
  const pad = r.body.children.find(c => c.id === 'pineReportPad');
  assert.ok(pad, 'the pad is on the page');
  assert.equal((pad.listeners.paste || []).length, 1);
  assert.match(find(pad, n => /paste any images/.test(n.textContent || ''))[0].textContent, /Send it to the inbox/);
});

test('a pasted image is attached, shown, removable, and sent with the report', async () => {
  const r = rig();
  r.window.PineReport.open();
  const pad = r.body.children.find(c => c.id === 'pineReportPad');
  assert.equal(paste(pad, [], 'just words'), false);                 // text is left to the box
  assert.equal(paste(pad, [png(1), png(2)]), true);
  const strip = find(pad, n => n.id === 'pineReportPasted')[0];
  assert.equal(strip.children.length, 2);
  find(strip.children[0], n => n.tagName === 'BUTTON')[0].click();   // remove the first
  assert.equal(strip.children.length, 1);
  find(pad, n => n.tagName === 'TEXTAREA')[0].value = 'the popup is blank';
  find(pad, n => n.tagName === 'BUTTON' && n.textContent === 'Send to the inbox')[0].click();
  await Promise.resolve();
  assert.equal(r.posts.length, 1);
  assert.equal(r.posts[0][0], '/api/pine-requests');
  assert.equal(JSON.stringify(r.posts[0][1].images), JSON.stringify(['data:image/png;base64,AAA2']));   // the removed one is gone
  assert.equal(r.posts[0][1].text, 'the popup is blank');
});

test('six images is the most, and a file that is not an image is ignored', () => {
  const r = rig();
  r.window.PineReport.open();
  const pad = r.body.children.find(c => c.id === 'pineReportPad');
  paste(pad, [1, 2, 3, 4, 5, 6, 7, 8].map(png));
  assert.equal(find(pad, n => n.id === 'pineReportPasted')[0].children.length, 6);
  assert.equal(paste(pad, [{ type: 'application/pdf', dataUrl: 'data:application/pdf;base64,AA' }]), false);
});
