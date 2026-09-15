const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/hot-corners.js'), 'utf8');
const SOURCE_ID = '0123456789abcdef0123456789abcdef';

class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.listeners = {}; this.style = {}; this.attrs = {}; this.checked = false;
    this.classList = {add() {}, remove() {}, toggle() {}};
    if (tag === 'iframe') this.contentWindow = {};
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); child.parentNode = null; }
  replaceChildren() { this.children = []; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter(x => x !== fn); }
  fire(type, event = {}) { for (const fn of this.listeners[type] || []) fn(event); }
}
function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }
function setup(bridge) {
  const document = new Element('document'); document.body = new Element('body');
  document.createElement = tag => new Element(tag); document.getElementById = () => null;
  const root = new Element('window');
  Object.assign(root, {document, URL, location: {protocol: 'http:', href: 'http://127.0.0.1:8096/', origin: 'http://127.0.0.1:8096'},
    pineDesktop: bridge, PineDuck: {REPORT: .1, hold() { throw new Error('capture must not duck playback'); }}});
  const context = vm.createContext({window: root, URL, Promise, setTimeout: () => 1, clearTimeout() {}, console});
  vm.runInContext(source, context);
  return {root, document, api: root.PineHotCorners,
    find: predicate => descendants(document.body).find(predicate),
    all: predicate => descendants(document.body).filter(predicate)};
}
const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
const captureButton = h => h.find(n => n.tagName === 'button' && n.className.includes('hc-primary'));

test('registered source path and iframe messages reject foreign identities and senders', () => {
  const {api} = setup({}); const frame = {};
  assert.equal(api._editorPath(SOURCE_ID), '/video-editor/?source=' + SOURCE_ID);
  for (const id of ['', '../secret', 'https://evil.invalid/', SOURCE_ID + '&extra=1', SOURCE_ID.toUpperCase()]) {
    assert.throws(() => api._editorPath(id));
  }
  const event = {source: frame, origin: 'http://station', data: {type: 'pine-video-editor-close'}};
  assert.equal(api._editorMessage(event, frame, event.origin), 'pine-video-editor-close');
  assert.equal(api._editorMessage({...event, source: {}}, frame, event.origin), '');
  assert.equal(api._editorMessage({...event, origin: 'http://evil.invalid'}, frame, event.origin), '');
});

test('capture opens editor over the existing page without saving or ducking', async () => {
  const calls = []; let saves = 0;
  const h = setup({replayState: async () => ({running: true, seconds: 60, audio: {state: 'capturing'}}),
    replayEdit: async opts => { calls.push(opts); return {ok: true, source_id: SOURCE_ID}; },
    replayExport: () => { throw new Error('legacy save must not run'); }, replayKeepEdited: () => { saves++; }});
  const player = h.document.body.appendChild(new Element('audio'));
  h.api.act('export'); await flush(); captureButton(h).fire('click'); await flush();
  assert.equal(calls.length, 1); assert.equal(calls[0].seconds, 60); assert.equal(calls[0].video_only, false);
  const frame = h.find(n => n.tagName === 'iframe');
  assert.equal(frame.src, '/video-editor/?source=' + SOURCE_ID);
  assert.equal(player.parentNode, h.document.body);
  h.root.fire('message', {source: frame.contentWindow, origin: h.root.location.origin, data: {type: 'pine-video-editor-export'}});
  assert.equal(saves, 0);
  h.root.fire('message', {source: {}, origin: h.root.location.origin, data: {type: 'pine-video-editor-close'}});
  assert.ok(h.find(n => n.tagName === 'iframe'));
  h.root.fire('message', {source: frame.contentWindow, origin: h.root.location.origin, data: {type: 'pine-video-editor-close'}});
  assert.equal(h.find(n => n.tagName === 'iframe'), undefined);
  assert.equal(player.parentNode, h.document.body);
});

test('missing audio never silently enables video-only capture and errors stay in the sheet', async () => {
  const calls = [];
  const h = setup({replayState: async () => ({running: true, seconds: 20, audio: {state: 'unavailable', detail: 'permission refused'}}),
    replayEdit: async opts => { calls.push({...opts}); return {ok: false, detail: 'No captured audio', original_saved: true, where: 'Downloads/recordings/original.mp4'}; }});
  h.api.act('export'); await flush(); captureButton(h).fire('click'); await flush();
  assert.equal(calls[0].video_only, false);
  assert.ok(h.find(n => n.textContent && n.textContent.includes('original saved to Downloads/recordings/original.mp4')));
  assert.equal(h.find(n => n.tagName === 'iframe'), undefined);
  h.find(n => n.type === 'checkbox').checked = true;
  captureButton(h).fire('click'); await flush();
  assert.equal(calls[1].video_only, true);
});

test('older bridge retains save-to-recordings fallback', async () => {
  const calls = [];
  const h = setup({replayState: async () => ({running: true, seconds: 30}),
    replayExport: async opts => { calls.push(opts); return {ok: true, seconds: 30, where: 'Downloads/recordings'}; }});
  h.api.act('export'); await flush(); captureButton(h).fire('click'); await flush();
  assert.equal(calls.length, 1); assert.equal(calls[0].upload, true);
  assert.equal(h.find(n => n.tagName === 'iframe'), undefined);
});
