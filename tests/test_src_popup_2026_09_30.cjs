// [src-popup] a tap on the card's source badge opens a window: every source and
// what fed it, how the main one was chosen (the subject's seed and the claim that
// won), what was selected, and the card's rolls in order - each opening its own
// roulette. [whole-words] the topic reaches it whole.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const rawSrc = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
const src = rawSrc.replace(/\r\n/g, '\n');
const kiosk = path.join(root, 'app/src/main/assets/pine-views/script-page.js');
if (fs.existsSync(kiosk)) assert.strictEqual(fs.readFileSync(kiosk, 'utf8'), rawSrc, 'the kiosk copy is the renderer, byte for byte');

const grab = name => {
  const m = src.match(new RegExp('\\n  function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n'));
  assert(m, 'missing ' + name);
  return m[0];
};
const decl = name => {
  const m = src.match(new RegExp('\\n  var ' + name + ' = [\\s\\S]*?;\\n'));
  assert(m, 'missing ' + name);
  return m[0];
};

class El {
  constructor(tag, cls, text) {
    this.tagName = tag.toUpperCase(); this.className = cls || ''; this.textContent = text || '';
    this.children = []; this.attrs = {}; this.on = {}; this.title = ''; this.parentNode = null;
    const self = this;
    this.classList = {add(c) { self.className = (self.className + ' ' + c).trim(); },
      contains(c) { return self.className.split(/\s+/).indexOf(c) >= 0; }};
  }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(n, fn) { (this.on[n] = this.on[n] || []).push(fn); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); this.parentNode = null; }
  all() { return this.children.reduce((a, c) => a.concat([c], c.all()), []); }
  querySelectorAll(sel) {
    const [tag, cls] = sel.split('.');
    return this.all().filter(e => e.tagName === tag.toUpperCase() && (!cls || e.classList.contains(cls)));
  }
  text() { return this.textContent + this.children.map(c => c.text()).join(' '); }
  click() { (this.on.click || []).forEach(fn => fn({stopPropagation() {}, preventDefault() {}, target: this})); }
}
const body = new El('body');
const document = {
  body, getElementById: id => body.all().find(e => e.id === id) || null,
  addEventListener() {}, removeEventListener() {},
};
const make = (tag, cls, text) => new El(tag, cls, text);

const code = decl('MV_SRC') + decl('MV_SRC_ORDER') + decl('MV_SRC_RULE') + decl('MV_CAT_SAY')
  + grab('mvSources') + grab('mvRrStepName') + grab('mvRrChain') + grab('mvRrPopTable')
  + grab('mvSrcPopWire') + grab('mvSrcPopOpen')
  + 'return {mvSources: mvSources, mvSrcPopWire: mvSrcPopWire};';
let rrOpened = null;
// eslint-disable-next-line no-new-func
const f = new Function('document', 'make', 'mvState', 'mvRrPopOpen', code)(
  document, make, () => ({}), (rows, i, which) => { rrOpened = {i, which}; });

const TOPIC = 'So I was having an emergency and I ran into restroom to use the bathroom and took a seat '
  + 'and sat down on the manager and he didn\'t say anything. He let me sit there and do my business on his lap.';

// the source, read off the record, with its rule
const turn = {state_before: {subject: {category: 'internet_news', topic: 'Headlines of the hour'}}};
const decisions = [{family: 'TOPIC', selected: {label: TOPIC}}];
const s = f.mvSources({row: {}, kind: 'line'}, {conversation: {road: 'banter'}}, turn, decisions);
assert.strictEqual(s.main, 'internet');
assert.strictEqual(s.cat, 'internet_news');
assert(/news wire/.test(s.rule), s.rule);
assert.strictEqual(s.why.topic, TOPIC, 'the topic reaches the badge whole');

// the window
const rows = [
  {fam: 'ES', table: 'ES1', main: {stage: 'category', label: 'SOCIAL / SELF-CONSCIOUS', dice: 93, hit: 7, of: 9},
    sub: {stage: 'item', label: 'embarrassment', dice: 10, hit: 0, of: 9}},
  {fam: 'TOPIC', table: 'TOPIC', main: {stage: 'item', label: TOPIC, dice: 75, hit: 43, of: 60}},
];
const acc = new El('div', 'sp-mv-acc');
f.mvSrcPopWire(acc, s, rows);
assert(acc.classList.contains('sp-rr-pickable'), 'the badge is tappable');
acc.click();
const pop = document.getElementById('spRrPop');
assert(pop, 'the window opened');
const words = pop.text();
['Every source this line could have come from (8)', 'How it came to this one', 'What was selected',
  'The rolls on this card, in order', 'news headlines seeded it', 'It is not rolled'].forEach(w =>
  assert(words.indexOf(w) >= 0, 'says: ' + w));
assert(words.indexOf(TOPIC) >= 0, 'the topic is in the window whole');
const trs = pop.querySelectorAll('tr.sp-rrp-go');
assert.strictEqual(trs.length, 3, 'one row per roll: ES1 category, ES1 item, TOPIC item');
trs[2].click();
assert.deepStrictEqual(rrOpened, {i: 1, which: 'main'}, 'a roll row opens that roulette');
assert.strictEqual(document.getElementById('spRrPop'), null, 'and the source window gives way to it');

// rewired on a redraw: the latest record wins, no second listener
const s2 = Object.assign({}, s, {main: 'topic'});
f.mvSrcPopWire(acc, s2, rows);
assert.strictEqual(acc.on.click.length, 1);
acc.click();
assert(/landed on Topic/.test(document.getElementById('spRrPop').text()));

console.log('src-popup ok');
