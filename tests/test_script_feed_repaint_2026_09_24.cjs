const assert = require('node:assert/strict');
const {test} = require('node:test');
const crawl = require('../desktop/renderer/script-page.js').feedCrawl;

function classes() {
  const names = new Set();
  return {
    contains(name) { return names.has(name); },
    toggle(name, force) {
      if (force) names.add(name);
      else names.delete(name);
    }
  };
}

function viewport(width = 100) {
  let reads = 0;
  const track = {children: [], style: {setProperty() {}},
    get firstElementChild() { return this.children[0] || null; },
    appendChild(child) {
      child.scrollWidth = child.textContent.length * 8;
      this.children.push(child);
    },
    replaceChildren() { this.children = []; }};
  return {
    classList: classes(), dataset: {}, clientWidth: width,
    isConnected: true, track,
    querySelector(selector) {
      assert.equal(selector, '.sp-msg-marquee-track');
      reads++;
      return track;
    },
    setAttribute() {},
    get reads() { return reads; },
    setWidth(value) { this.clientWidth = value; }
  };
}

test('unchanged feed words keep the same children and schedule no width read', (t) => {
  const oldDocument = global.document;
  const oldFrame = global.requestAnimationFrame;
  let frames = 0;
  global.document = {createElement() {
    return {textContent: '', setAttribute() {}};
  }};
  global.requestAnimationFrame = (callback) => { frames++; callback(); };
  t.after(() => {
    global.document = oldDocument;
    global.requestAnimationFrame = oldFrame;
  });

  const body = viewport();
  const words = 'This is a long line that should move across the feed.';
  crawl.dress(body, words);
  assert.equal(frames, 1);
  assert.equal(body.classList.contains('is-moving'), true);
  const first = body.track.firstElementChild;
  const reads = body.reads;
  for (let i = 0; i < 10; i++) crawl.dress(body, words);
  assert.equal(frames, 1);
  assert.equal(body.reads, reads);
  assert.equal(body.track.firstElementChild, first);
  crawl.dress(body, 'Short line');
  assert.equal(frames, 2);
  assert.equal(body.classList.contains('is-moving'), false);
});

test('feed width changes still remeasure unchanged lines', (t) => {
  const oldResize = global.ResizeObserver;
  let observer;
  global.ResizeObserver = class {
    constructor(callback) { this.callback = callback; observer = this; }
    observe(target) { this.target = target; }
    disconnect() { this.disconnected = true; }
  };
  t.after(() => { crawl.stop(); global.ResizeObserver = oldResize; });

  const body = viewport();
  body.track.appendChild({textContent: 'A long sentence that needs room'});
  let scans = 0;
  const box = {clientWidth: 100, querySelectorAll(selector) {
    assert.equal(selector, '.sp-msg-marquee');
    scans++;
    return [body];
  }};
  crawl.start(box);
  assert.equal(observer.target, box);
  observer.callback();
  assert.equal(body.classList.contains('is-moving'), true);
  observer.callback();
  assert.equal(scans, 1, 'height-only observations do not scan every feed row');
  body.setWidth(300);
  box.clientWidth = 300;
  observer.callback();
  assert.equal(body.classList.contains('is-moving'), false);
  assert.equal(scans, 2);
  crawl.stop();
  assert.equal(observer.disconnected, true);
});

test('cached feed row parts avoid descendant queries on station repaints', (t) => {
  const oldDocument = global.document;
  const oldFrame = global.requestAnimationFrame;
  let frames = 0;
  global.document = {createElement() {
    return {textContent: '', setAttribute() {}};
  }};
  global.requestAnimationFrame = (callback) => { frames++; callback(); };
  t.after(() => {
    global.document = oldDocument;
    global.requestAnimationFrame = oldFrame;
  });

  const body = viewport();
  const operation = {textContent: ''};
  const purposeText = {textContent: ''};
  const purpose = {appendChild() {}, querySelector() { throw new Error('purpose queried'); }};
  const line = {pineFeedNodes: {operation, purpose, purposeText, body, badge: null},
    classList: classes(), querySelector() { throw new Error('line queried'); }};
  const row = {id: 'line-1', kind: 'banter', name: 'Host',
    text: 'A prepared line that will sound on the station soon.', aired: 'prepared'};
  crawl.row(line, row);
  assert.equal(frames, 1);
  assert.equal(body.dataset.words, row.text);
  assert.equal(operation.textContent, 'Studio Banter');
  for (let i = 0; i < 10; i++) crawl.row(line, row);
  assert.equal(frames, 1, 'unchanged station snapshots do not remeasure 10 times');
  assert.equal(body.track.children.length, 2);
  crawl.row(line, {...row, text: 'A revised line for the station.'});
  assert.equal(frames, 2);
});
