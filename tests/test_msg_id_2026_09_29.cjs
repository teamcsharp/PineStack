// [msgid] msg-id.js: the code, the parser, the copy road, and where it is wired.
//   node --test tests/test_msg_id_2026_09_29.cjs
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const renderer = path.join(__dirname, '..', 'desktop', 'renderer');
const M = require(path.join(renderer, 'msg-id.js'));

test('the code is short and stable', () => {
  assert.equal(M.code('3c4782'), '3c4782');
  assert.equal(M.code('1a2b3c4d'), '1a2b3c4d');
  assert.equal(M.code('c69e1e19c3584596964a62047cc91aaa'), 'c69e1e19');
  assert.equal(M.code('c69e1e19c3584596964a62047cc91aaa-punct-2'), 'c69e1e19-p2');
  assert.equal(M.code('ln-3c4782'), '3c4782');
});

test('the find box: a code opens a message, a word stays a word', () => {
  assert.deepEqual(M.parse('#3c4782'), {prefix: '3c4782', punct: '', raw: '3c4782'});
  assert.equal(M.parse('3c4782').prefix, '3c4782');
  assert.equal(M.parse(' #C69E1E19 ').prefix, 'c69e1e19');
  assert.equal(M.parse('c69e1e19-p1').punct, '1');
  assert.equal(M.parse('facade'), null);           // all a-f letters, no #: a word
  assert.equal(M.parse('#facade').prefix, 'facade');
  assert.equal(M.parse('dental'), null);
  assert.equal(M.parse('3c47'), null);             // too short to name one message
  assert.ok(M.matches('c69e1e19c3584596964a62047cc91aaa', M.parse('c69e1e19')));
  assert.ok(!M.matches('c69e1e19c3584596964a62047cc91aaa-punct-1', M.parse('c69e1e19')));
  assert.ok(M.matches('c69e1e19c3584596964a62047cc91aaa-punct-1', M.parse('c69e1e19-p1')));
});

test('copy takes the kiosk bridge when the page has no navigator.clipboard', async () => {
  const got = [];
  globalThis.pineDesktop = {copyText: (t) => { got.push(t); return true; }};
  const nav = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {value: {}, configurable: true});
  try {
    assert.equal(await M.copy('#3c4782'), true);
    assert.deepEqual(got, ['#3c4782']);
  } finally {
    if (nav) Object.defineProperty(globalThis, 'navigator', nav);
    delete globalThis.pineDesktop;
  }
});

test('copy uses navigator.clipboard where it exists, and falls back to the bridge', async () => {
  const got = [];
  globalThis.pineDesktop = {copyText: (t) => { got.push('bridge:' + t); return true; }};
  const nav = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {value: {clipboard: {writeText: () => Promise.reject(new Error('denied'))}}, configurable: true});
  try {
    assert.equal(await M.copy('#e4c9cf'), true);
    assert.deepEqual(got, ['bridge:#e4c9cf']);
  } finally {
    if (nav) Object.defineProperty(globalThis, 'navigator', nav);
    delete globalThis.pineDesktop;
  }
});

test('Carbon glyphs only, a title on the chip, no emoji', () => {
  const src = fs.readFileSync(path.join(renderer, 'msg-id.js'), 'utf8');
  assert.match(src, /Message id (\\u2014|—) tap to copy/);
  assert.match(src, /c:copy--to-clipboard/);
  assert.ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(src), 'no emoji');
});
