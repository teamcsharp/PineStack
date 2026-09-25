const assert = require('node:assert/strict');
const {test} = require('node:test');
const script = require('../desktop/renderer/script-page.js');
const view = script.view;
const marks = script.marks;

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

test('a display reindex keeps the player-evidenced line identity', (t) => {
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
  let displayOrder = [FIRST, SECOND];
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
        return displayOrder.map((id) => nodes.get(id))
          .filter((node) => node.classList.contains('sp-now'));
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

  assert.equal(view.paintSaying(null), null);
  view.placeMarks({mark: 'none'}, {id: FIRST});
  assert.equal(strip.dataset.line, undefined);
  assert.equal(nodes.get(FIRST).classList.contains('sp-now'), false);

  nodes.get(FIRST).classList.add('sp-feed-now');
  view.paintSaying({id: FIRST, road: 'playout', speaker: 'HOST',
    text: 'First spoken line.'});
  view.placeMarks({mark: 'air', line_id: FIRST, road: 'playout'});
  assert.equal(nodes.get(FIRST).classList.contains('sp-now'), true);
  assert.equal(nodes.get(FIRST).classList.contains('sp-feed-now'), false);
  assert.equal(strip.dataset.line, FIRST);

  displayOrder = [SECOND, FIRST];
  nodes.get(FIRST).dataset.block = '99';
  nodes.get(FIRST).dataset.ord = '7';
  view.placeMarks({mark: 'air', line_id: FIRST, road: 'playout'});
  assert.equal(nodes.get(FIRST).classList.contains('sp-now'), true);
  assert.equal(nodes.get(SECOND).classList.contains('sp-now'), false);
  assert.equal(global.document.querySelectorAll('.sp-el.sp-now').length, 1);
  nodes.set(FIRST, element(FIRST, 'First spoken line.'));
  view.placeMarks({mark: 'air', line_id: FIRST, road: 'playout'});
  assert.equal(nodes.get(FIRST).classList.contains('sp-now'), true,
    'a reindexed replacement is marked by the same line id');
  assert.equal(global.document.querySelectorAll('.sp-el.sp-now').length, 1);

  current = SECOND;
  station.speaking_now = {id: SECOND};
  station.stream_now.rows = [{id: SECOND}];
  view.paintSaying({id: SECOND, road: 'playout', speaker: 'HOST',
    text: 'Second spoken line.'});
  view.placeMarks({mark: 'air', line_id: SECOND, road: 'playout'});
  assert.equal(strip.dataset.line, SECOND);
  assert.equal(nodes.get(FIRST).classList.contains('sp-now'), false);
  assert.equal(nodes.get(SECOND).classList.contains('sp-now'), true);
  assert.equal(global.document.querySelectorAll('.sp-el.sp-now').length, 1);

  current = FIRST;
  assert.equal(view.paintSaying({id: SECOND, road: 'playout', speaker: 'HOST',
    text: 'Second spoken line.'}).id, SECOND,
  'fresh feed text cannot replace a different player-evidenced line');
});

test('steady live ticks bound full mark audits and follow geometry checks', (t) => {
  const previous = {document: global.document, now: Date.now};
  const nodes = [element(FIRST, 'First spoken line.'), element(SECOND, 'Other line.')];
  nodes.forEach((node) => { node.isConnected = true; node.hidden = false; });
  let time = 1000000;
  let audits = 0;
  let geometry = 0;
  const rect = {top: 0, bottom: 500, height: 500};
  const box = {scrollTop: 0, clientHeight: 500, scrollHeight: 1000,
    getBoundingClientRect() { geometry++; return rect; }};
  nodes.forEach((node) => {
    node.getBoundingClientRect = () => { geometry++; return {top: 100, bottom: 120, height: 20}; };
  });
  Date.now = () => time;
  global.document = {
    getElementById(id) { return id === 'spScript' ? box : null; },
    querySelector(selector) {
      const match = selector.match(/^\.sp-el\[data-line="([^"]+)"\]$/);
      return match ? nodes.find((node) => node.isConnected && node.dataset.line === match[1]) || null : null;
    },
    querySelectorAll(selector) {
      if (selector === '.sp-el.sp-now') {
        audits++;
        return nodes.filter((node) => node.classList.contains('sp-now'));
      }
      return [];
    }
  };
  marks.reset();
  marks.lines.set(FIRST, nodes[0]);
  t.after(() => {
    view.placeMarks({mark: 'none'});
    marks.lines.clear();
    marks.reset();
    Date.now = previous.now;
    global.document = previous.document;
  });

  view.placeMarks({mark: 'air', line_id: FIRST});
  const initialAudits = audits;
  const initialGeometry = geometry;
  for (let i = 1; i <= 20; i++) {
    time += 250;
    view.placeMarks({mark: 'air', line_id: FIRST});
    marks.keepLitInView('tick');
  }
  assert.equal(audits - initialAudits, 5, '20 steady ticks need five full audits');
  assert.equal(geometry - initialGeometry, 10, '20 steady ticks need five geometry checks');
  assert.equal(nodes[0].classList.contains('sp-now'), true);

  const beforePaint = geometry;
  time += 50;
  marks.keepLitInView('paint');
  assert.equal(geometry - beforePaint, 2, 'repaint checks the line immediately');

  nodes[1].classList.add('sp-now');
  time += 1000;
  view.placeMarks({mark: 'air', line_id: FIRST});
  assert.equal(nodes[1].classList.contains('sp-now'), false, 'periodic audit clears stray marks');
  const replacement = element(FIRST, 'Reindexed line.');
  replacement.isConnected = true;
  replacement.hidden = false;
  nodes[0].isConnected = false;
  nodes.push(replacement);
  marks.lines.set(FIRST, replacement);
  time += 250;
  view.placeMarks({mark: 'air', line_id: FIRST});
  assert.equal(replacement.classList.contains('sp-now'), true,
    'replacement is marked on the very next tick');
  assert.equal(nodes.filter((node) => node.classList.contains('sp-now')).length, 1);
});

test('feed timing cannot highlight a line even while voice audio is playing', (t) => {
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
  assert.equal(view.sayingFallbackMark(null, shown), null);
  assert.equal(view.sayingFallbackMark({id: FIRST}, shown), null,
    'a resolved line never needs a fallback mark');
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

test('the live strip never claims a clock-selected stream line', (t) => {
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
  assert.equal(shown, null);
  assert.equal(strip.dataset.line, undefined);
  assert.equal(view.sayingFallbackMark(null, shown), null);
  station.paused = true;
  assert.equal(view.paintSaying(null), null);
  assert.equal(strip.dataset.line, undefined);
  assert.equal(view.sayingFallbackMark(null, shown), null);
  station.paused = false;
  station.stream_now.at = Date.now() / 1000 - 30;
  assert.equal(view.paintSaying(null), null);
  assert.equal(view.sayingFallbackMark(null, shown), null);
});

test('playout override requires a fresh listener receipt consistent with the player', () => {
  const now = Date.now();
  const read = {source: 'local', file: 'round.mp3', position_s: 3};
  const receipt = view.playoutRead({verdict: 'sounding', sounding: {
    line_id: FIRST, file: 'round.mp3', position_s: 3,
    line_from: 2, line_until: 5, position_basis: 'listener',
    last_heard_at: now / 1000 - 1
  }});
  assert.equal(view.playoutEvidence(receipt, read, false, now), true);
  assert.equal(view.playoutEvidence(receipt, {...read, source: 'estimated'},
    false, now), false);
  assert.equal(view.playoutEvidence(receipt, {...read, position_s: null},
    false, now), false);
  assert.equal(view.playoutEvidence(receipt, {...read, stalledMs: 9000},
    false, now), false);
  assert.equal(view.playoutEvidence({...receipt, position_basis: 'estimate'},
    read, false, now), false);
  assert.equal(view.playoutEvidence({...receipt, last_heard_at: now / 1000 - 12},
    read, false, now), false);
  assert.equal(view.playoutEvidence({...receipt, last_heard_at: now / 1000 - 4},
    read, false, now), false);
  assert.equal(view.playoutEvidence(receipt, {...read, file: 'other.mp3'},
    false, now), false);
  assert.equal(view.playoutEvidence(receipt, {...read, position_s: 6},
    false, now), false);
  assert.equal(view.playoutEvidence(receipt, read, true, now), false);
});
