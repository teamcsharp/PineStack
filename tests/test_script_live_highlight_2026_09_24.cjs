const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const view = require('../desktop/renderer/script-page.js').view;

const FIRST = 'de9f0b75d1d14063a0b0c7e3c3d680a8';
const SECOND = 'a29f0b75d1d14063a0b0c7e3c3d680a8';

function element(id, words) {
  const classes = new Set(['sp-el', 'sp-dialogue', 'sp-segment-past']);
  const attrs = new Map();
  return {
    dataset: {line: id}, className: 'sp-el sp-dialogue sp-segment-past', textContent: words,
    previousElementSibling: {className: 'sp-character', textContent: 'HOST'},
    classList: {
      contains(name) { return classes.has(name); },
      add(name) { classes.add(name); },
      remove(name) { classes.delete(name); },
      toggle(name, force) {
        if (force === undefined) force = !classes.has(name);
        if (force) classes.add(name);
        else classes.delete(name);
      }
    },
    getAttribute(name) { return attrs.get(name) || ''; },
    setAttribute(name, value) { attrs.set(name, String(value)); },
    removeAttribute(name) { attrs.delete(name); }
  };
}

test('a sounding feed line with no resolver mark follows section 1 into section 2', (t) => {
  const previous = {
    document: global.document, PineStationFeed: global.PineStationFeed,
    pinePlayhead: global.pinePlayhead
  };
  const nodes = new Map([
    [FIRST, element(FIRST, 'First spoken line.')],
    [SECOND, element(SECOND, 'Second spoken line.')]
  ]);
  const voice = {id: 'djVoiceAudio0', paused: false, ended: false,
    currentTime: 3.1, readyState: 4};
  const who = {textContent: ''};
  const words = {textContent: '', scrollTop: 0};
  const strip = {dataset: {}, classList: {toggle() {}}, title: ''};
  const station = {server_ms: Date.now(), paused: false,
    speaking_now: {id: FIRST}, stream_now: {rows: [{id: FIRST}]}};
  let current = FIRST;
  global.document = {
    getElementById(id) {
      return {spSayingWho: who, spSayingText: words, spSaying: strip}[id] || null;
    },
    querySelector(selector) {
      const match = selector.match(/^\.sp-el\[data-line="([^"]+)"\]$/);
      return match ? nodes.get(match[1]) || null : null;
    },
    querySelectorAll(selector) {
      if (selector === 'audio') return [voice];
      if (selector === '.sp-el.sp-now') {
        return [...nodes.values()].filter((node) => node.classList.contains('sp-now'));
      }
      return [];
    }
  };
  global.pinePlayhead = null;
  global.PineStationFeed = {
    now() { return {id: current, aired: 'airing', text: nodes.get(current).textContent}; },
    state() { return station; },
    clock() { return Date.now(); }
  };
  t.after(() => {
    view.placeMarks({mark: 'none'}, null);
    global.document = previous.document;
    global.PineStationFeed = previous.PineStationFeed;
    global.pinePlayhead = previous.pinePlayhead;
  });

  const firstShown = view.paintSaying(null);
  const firstMark = view.sayingFallbackMark(null, firstShown);
  assert.equal(firstMark.id, FIRST);
  view.placeMarks({mark: 'none'}, firstMark);
  assert.equal(strip.dataset.line, FIRST);
  assert.equal(nodes.get(FIRST).classList.contains('sp-now'), true);
  assert.equal(nodes.get(FIRST).classList.contains('sp-feed-now'), true);

  current = SECOND;
  station.speaking_now = {id: SECOND};
  station.stream_now.rows = [{id: SECOND}];
  const secondShown = view.paintSaying(null);
  view.placeMarks({mark: 'none'}, view.sayingFallbackMark(null, secondShown));
  assert.equal(strip.dataset.line, SECOND);
  assert.equal(nodes.get(FIRST).classList.contains('sp-now'), false);
  assert.equal(nodes.get(SECOND).classList.contains('sp-now'), true);
  assert.equal(global.document.querySelectorAll('.sp-el.sp-now').length, 1);

  assert.equal(view.paintSaying({id: FIRST, road: 'playout', speaker: 'HOST',
    text: 'First spoken line.'}).id, FIRST,
  'fresh feed text cannot replace a different playout line in section 1');
});

test('feed-only highlighting needs current dialogue and actual voice playback', (t) => {
  const previous = {document: global.document, PineStationFeed: global.PineStationFeed,
    pinePlayhead: global.pinePlayhead};
  const node = element(FIRST, 'A spoken line.');
  const voice = {id: 'djVoiceAudio0', paused: false, ended: false,
    currentTime: 2, readyState: 4};
  const station = {server_ms: Date.now(), paused: false,
    speaking_now: {id: FIRST}, stream_now: {rows: [{id: FIRST}]}};
  global.document = {
    querySelector() { return node; },
    querySelectorAll(selector) { return selector === 'audio' ? [voice] : []; }
  };
  global.pinePlayhead = null;
  global.PineStationFeed = {state() { return station; }, clock() { return Date.now(); }};
  t.after(() => {
    global.document = previous.document;
    global.PineStationFeed = previous.PineStationFeed;
    global.pinePlayhead = previous.pinePlayhead;
  });
  const shown = {id: FIRST, aired: 'airing'};
  assert.equal(view.sayingFallbackMark(null, shown).id, FIRST);
  assert.equal(view.sayingFallbackMark({id: FIRST}, shown), null,
    'a resolved line never needs the inferred display mark');
  voice.paused = true;
  assert.equal(view.sayingFallbackMark(null, shown), null);
  voice.paused = false;
  station.paused = true;
  assert.equal(view.sayingFallbackMark(null, shown), null);
  station.paused = false;
  station.server_ms = Date.now() - 20000;
  assert.equal(view.sayingFallbackMark(null, shown), null);
  station.server_ms = Date.now();
  node.classList.remove('sp-dialogue');
  assert.equal(view.sayingFallbackMark(null, shown), null);
  assert.equal(view.sayingFallbackMark(null, {id: FIRST, aired: 'prepared'}), null);
});

test('the live strip and inferred mark release an expired or paused stream line', (t) => {
  const previous = {document: global.document, PineStationFeed: global.PineStationFeed,
    pinePlayhead: global.pinePlayhead};
  const node = element(FIRST, 'A spoken line.');
  const who = {textContent: ''};
  const words = {textContent: '', scrollTop: 0};
  const strip = {dataset: {}, classList: {toggle() {}}, title: ''};
  const voice = {id: 'djVoiceAudio0', paused: false, ended: false,
    currentTime: 2, readyState: 4};
  const station = {server_ms: Date.now(), paused: false,
    speaking_now: {id: FIRST}, stream_now: {at: Date.now() / 1000 - 2,
      length: 8, rows: [{id: FIRST, from: 0, until: 8}]}};
  global.document = {
    getElementById(id) {
      return {spSayingWho: who, spSayingText: words, spSaying: strip}[id] || null;
    },
    querySelector() { return node; },
    querySelectorAll(selector) { return selector === 'audio' ? [voice] : []; }
  };
  global.pinePlayhead = null;
  global.PineStationFeed = {state() { return station; }, clock() { return Date.now(); },
    now() { return {id: FIRST, aired: 'airing', text: 'A spoken line.'}; }};
  t.after(() => {
    global.document = previous.document;
    global.PineStationFeed = previous.PineStationFeed;
    global.pinePlayhead = previous.pinePlayhead;
  });
  const shown = view.paintSaying(null);
  assert.equal(shown.id, FIRST);
  assert.equal(view.sayingFallbackMark(null, shown).id, FIRST);
  station.paused = true;
  assert.equal(view.paintSaying(null), null);
  assert.equal(strip.dataset.line, undefined);
  assert.equal(view.sayingFallbackMark(null, shown), null);
  station.paused = false;
  station.stream_now.at = Date.now() / 1000 - 30;
  assert.equal(view.paintSaying(null), null);
  assert.equal(view.sayingFallbackMark(null, shown), null);
});

test('the inferred mark is visibly distinguished from a cue-sheet read', () => {
  const css = readFileSync(join(__dirname, '../desktop/renderer/script-page.css'), 'utf8');
  const js = readFileSync(join(__dirname, '../desktop/renderer/script-page.js'), 'utf8');
  assert.match(css, /\.sp-el\.sp-now\.sp-feed-now::before\s*\{\s*content: "LIVE FEED"/);
  assert.match(js, /highlight_basis: feedMark \? 'feed-voice'/);
});
