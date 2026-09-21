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
function loadSegments() {
  const src = fs.readFileSync(
    path.join(__dirname, '../desktop/renderer/pine-segments.js'), 'utf8');
  const sandbox = {window: {}, globalThis: {}};
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
  ['pane', 'topics', 'acceptDrops', 'plotWindow', 'read', 'close']
    .forEach((name) => assert.equal(typeof S[name], 'function', name));
});

test('it never reaches for a DOM just to parse', () => {
  /* The sandbox above has no document at all. If read() touched one, every
     test in this file would have thrown before reaching here. */
  const S = loadSegments();
  assert.ok(S.read('# ok\n\n## a\nb', 'x.md').acts.length > 0);
});
