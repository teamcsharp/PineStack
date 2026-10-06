/* [works-portable] [tools-view] The Works as a portable module and the tablet's TOOLS view. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const ROOT = path.join(__dirname, '..');
const DESK = path.join(ROOT, 'desktop', 'renderer');
const TAB = path.join(ROOT, 'app', 'src', 'main', 'assets', 'pine-views');
const ASCII_ONLY = new RegExp('^[\\x00-\\x7f]*$');

function load(name) {
  const src = fs.readFileSync(path.join(DESK, name), 'utf8');
  assert.match(src, ASCII_ONLY, name + ' is ASCII');
  const win = { document: { createElement: () => ({ append() {}, appendChild() {}, classList: { toggle() {}, add() {} }, setAttribute() {}, addEventListener() {}, style: {} }), getElementById: () => null, body: { appendChild() {} } },
    localStorage: { getItem: () => null, setItem() {} }, setInterval: () => 1, clearInterval() {}, location: { protocol: 'file:' }, fetch: () => Promise.reject(new Error('no net')), Date, Promise, Number, String, Object, Array, JSON, Math };
  win.window = win;
  vm.runInNewContext(src, win, { filename: name });
  return { src, win };
}

test('[works-portable] the module parses, is mirrored, and exposes mount/open/close with a close X', () => {
  for (const name of ['the-works.js', 'the-works.css', 'pine-tools-view.js', 'pine-tools-view.css']) {
    const desk = fs.readFileSync(path.join(DESK, name), 'utf8');
    assert.equal(desk, fs.readFileSync(path.join(TAB, name), 'utf8'), name + ' is mirrored to the tablet');
  }
  const works = load('the-works.js');
  assert.equal(typeof works.win.PineTheWorks.mount, 'function');
  assert.equal(typeof works.win.PineTheWorks.open, 'function');
  assert.equal(typeof works.win.PineTheWorks.close, 'function');
  assert.ok(works.src.includes("x.title = 'Close'"), 'the popup has its X with a tooltip');
  assert.ok(works.src.includes("'/api/cupboard'") && works.src.includes("'/api/dj'") && works.src.includes('/api/blocked?limit=1'), 'reads the cupboard, the flow and the blocked count');
  assert.ok(works.src.includes('PineBlockedBook.mount(bookHost'), 'the blocked book is the second tab');
  assert.ok(!/scrollTop|scrollIntoView/.test(works.src), 'the reader is never moved');
  const tools = load('pine-tools-view.js');
  assert.equal(typeof tools.win.PineToolsView.mount, 'function');
  assert.equal(typeof tools.win.PineToolsView.open, 'function');
  assert.ok(tools.src.includes("'PineTheWorks'") && tools.src.includes("'PineLlmCommands'") && tools.src.includes("'PineHourFlow'"), 'the three new tools are on the list');
  assert.ok(tools.src.includes("el('button', 'ptv-back', 'Back')"), 'a Back bar returns to the list');
});

test('[tools-view] the tablet rail and the desk page carry the new modules', () => {
  const rail = fs.readFileSync(path.join(DESK, 'rail.js'), 'utf8');
  assert.ok(rail.includes("{id: 'tools', cls: 'ptv-view', label: 'TOOLS', mount: ['PineToolsView']}"), 'the rail has a TOOLS tab');
  assert.equal(rail, fs.readFileSync(path.join(TAB, 'rail.js'), 'utf8'), 'rail.js is mirrored');
  const page = fs.readFileSync(path.join(DESK, 'index.html'), 'utf8');
  for (const part of ['./the-works.css', './the-works.js', './pine-tools-view.css', './pine-tools-view.js']) assert.ok(page.includes(part), 'index.html loads ' + part);
});
