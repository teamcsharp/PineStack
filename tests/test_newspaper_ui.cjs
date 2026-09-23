/* Run: node tests/test_newspaper_ui.cjs
 * Exercise the existing paper capture and clipboard functions against small
 * fake sheets; no station mutation or clipboard write is needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
function section(from, to) {
  const start = source.indexOf(from);
  assert.ok(start >= 0, from);
  const end = source.indexOf(to, start + from.length);
  assert.ok(end > start, to);
  return source.slice(start, end);
}

async function captureTest(fail) {
  const pages = [
    {id: 1, offsetWidth: 200, offsetHeight: 110, hidden: false, style: {display: '', visibility: ''}},
    {id: 2, offsetWidth: 200, offsetHeight: 220, hidden: true, style: {display: 'none', visibility: 'hidden'}},
  ];
  const original = structuredClone(pages);
  const captured = [];
  const canvas = () => ({width: 0, height: 0,
    getContext: () => ({fillRect() {}, drawImage() {}})});
  const context = vm.createContext({
    document: {createElement: () => canvas()},
    paperFrame: {
      contentDocument: {querySelectorAll: () => pages, body: {}},
      contentWindow: {getComputedStyle: (node) => ({
        display: node.style?.display || 'block',
        visibility: node.style?.visibility || 'visible', backgroundColor: '#ffffff'})},
    },
    paperImagesSettled: async () => {}, paperInlineSvg() {},
    paperH2I: async () => ({toCanvas: async (page, options) => {
      assert.equal(page.hidden, false, 'each hidden sheet must be made visible for capture');
      assert.notEqual(page.style.display, 'none');
      captured.push(page.id);
      if (fail && page.id === 2) throw new Error('capture failed');
      return {width: page.offsetWidth * options.pixelRatio, height: page.offsetHeight * options.pixelRatio};
    }}),
  });
  vm.runInContext(section('async function paperEditionCanvas(say)', 'function paperShrink('), context);
  if (fail) {
    await assert.rejects(context.paperEditionCanvas(), /capture failed/);
  } else {
    const result = await context.paperEditionCanvas();
    assert.equal(result.pages, 2);
    assert.ok(result.canvas.height >= 660, 'one output image must contain both complete pages');
  }
  assert.deepEqual(captured, [1, 2], 'capture includes all sheets, not only the selected sheet');
  assert.deepEqual(pages, original, 'visibility is restored even when a later page fails');
}

async function clipboardTest(nativeRefuses = false) {
  const messages = [], copied = [], saved = [];
  const ctx = vm.createContext({
    paperCur: 'edition-1', paperStyle: 'broadsheet', paperFrame: {}, paperSnapBusy: false,
    window: {pineDesktop: {copyImage: (data) => {copied.push(data); return !nativeRefuses;}}},
    navigator: {}, setTimeout() {},
    setStatus: (message) => messages.push(message),
    paperEditionPlatePng: async () => ({pages: 3, blob: 'all-three-pages', png: 'all-three-pages'}),
    paperBlobUrl: async (blob) => 'data:image/png;base64,' + blob,
    paperCopyText: () => true,
    paperSaveBlob: (blob) => { saved.push(blob); return true; },
  });
  vm.runInContext(section('function paperCopy(btn, ev)', '/* #1029 #1020 #1047:'), ctx);
  ctx.paperCopy({textContent: 'Copy'});
  await new Promise(setImmediate);
  assert.deepEqual(copied, ['data:image/png;base64,all-three-pages']);
  if (nativeRefuses) {
    assert.deepEqual(saved, ['all-three-pages']);
    assert.ok(messages.some((m) => m.includes('downloaded instead')));
    assert.ok(!messages.some((m) => m.includes('are on the clipboard as one image')));
  } else {
    assert.ok(messages.some((m) => m.includes('All 3 pages')));
    assert.deepEqual(saved, []);
  }
}

function notificationTest() {
  const rings = [];
  let seen = '';
  const ctx = vm.createContext({
    paperBellObserved: false, paperBellCard: null, paperBox: null,
    paperBellRead: () => seen, paperBellMark: (id) => {seen = id;},
    paperBellRing: (id) => {rings.push(id); ctx.paperBellCard = {dataset: {}};},
    document: {getElementById: () => null},
  });
  vm.runInContext(section('function paperWatch(state)', '/* #1037: Newspaper | Tabloid.'), ctx);
  ctx.paperWatch({paper: {latest: '', running: false}});
  ctx.paperWatch({paper: {latest: 'first', running: true}});
  assert.deepEqual(rings, []);
  ctx.paperWatch({paper: {latest: 'first', running: false}});
  ctx.paperWatch({paper: {latest: 'first', running: false}});
  assert.deepEqual(rings, ['first'], 'first publication after an empty shelf rings once');
  seen = 'first'; ctx.paperBellCard = null;
  ctx.paperWatch({paper: {latest: 'next-hour', running: false}});
  assert.deepEqual(rings, ['first', 'next-hour']);
}

function readerNoticeTest() {
  const col = {innerHTML: '', scrollTop: 100};
  const top = {querySelector: () => ({textContent: ''})};
  const ctx = vm.createContext({callerDossierEsc: (s) => String(s).replaceAll('<', '&lt;'),
    paperReadWhen: () => '', paperReadHost: () => 'example.org'});
  vm.runInContext(section('function paperReadPaint(col, top, row, url)', 'function paperReadOpen(url, label)'), ctx);
  ctx.paperReadPaint(col, top, {title: 'Original report', paragraphs: ['Yes.'],
    blocks: [{k: 'p', t: 'Yes.'}], notice: 'Open the original for the rest.'}, 'https://example.org/story');
  assert.match(col.innerHTML, /role="status"/);
  assert.match(col.innerHTML, /Open the original for the rest/);
  assert.match(col.innerHTML, /<p>Yes\.<\/p>/);
}

(async () => {
  await captureTest(false);
  await captureTest(true);
  await clipboardTest(false);
  await clipboardTest(true);
  notificationTest();
  readerNoticeTest();
  console.log('6 newspaper UI behavior checks passed');
})().catch((error) => { console.error(error); process.exitCode = 1; });
