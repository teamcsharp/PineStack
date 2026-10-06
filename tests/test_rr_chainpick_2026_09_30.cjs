// [rr-chainpick] in the roulette popup, a roll under "What led up to it" or "What
// came after it" opens that roll's own table of entries.
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const rawSrc = fs.readFileSync(path.join(root, 'desktop/renderer/script-page.js'), 'utf8');
const src = rawSrc.replace(/\r\n/g, '\n');
const grab = name => {
  const m = src.match(new RegExp('\\n  function ' + name + '\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}\\n'));
  assert(m, 'missing ' + name);
  return m[0];
};

class El {
  constructor(tag, cls, text) {
    this.tagName = tag.toUpperCase(); this.className = cls || ''; this.textContent = text || '';
    this.children = []; this.on = {}; this.parentNode = null; this.attrs = {};
  }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(n, fn) { (this.on[n] = this.on[n] || []).push(fn); }
  remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(x => x !== this); this.parentNode = null; }
  all() { return this.children.reduce((a, c) => a.concat([c], c.all()), []); }
  querySelectorAll(sel) {
    const [tag, cls] = sel.split('.');
    return this.all().filter(e => e.tagName === tag.toUpperCase() && (!cls || e.className.split(/\s+/).includes(cls)));
  }
  text() { return this.textContent + ' ' + this.children.map(c => c.text()).join(' '); }
  click() { (this.on.click || []).forEach(fn => fn({stopPropagation() {}, preventDefault() {}, target: this})); }
}
const body = new El('body');
const document = {body, getElementById: id => body.all().find(e => e.id === id) || null,
  addEventListener() {}, removeEventListener() {}};
const make = (t, c, x) => new El(t, c, x);
// eslint-disable-next-line no-new-func
const f = new Function('document', 'make',
  grab('mvRrStepName') + grab('mvRrChain') + grab('mvRrPopTable') + grab('mvRrPromptShare') + grab('mvRrPopOpen') + 'return {mvRrPopOpen};')(document, make);

const rows = [
  {fam: 'ES', table: 'ES1', main: {stage: 'category', label: 'ANGER', dice: 26, hit: 1, of: 9, opts: ['JOY', 'ANGER'], weights: [1, 1]},
    sub: {stage: 'item', label: 'disgust', dice: 97, hit: 9, of: 10, opts: ['a', 'disgust'], weights: [1, 1]}},
  {fam: 'SFXGUY', table: 'SFXGUY', main: {stage: 'item', label: 'a saying off his shelf', dice: 48, hit: 2, of: 3,
    opts: ['a clip', 'a quip', 'a saying off his shelf'], weights: [1, 1, 1]}},
  {fam: 'MEMORY', table: 'MEMORY1', main: {stage: 'category', label: 'The segment is nearly up', dice: 5, hit: 0, of: 1,
    opts: ['The segment is nearly up'], weights: [1]}},
];
f.mvRrPopOpen(rows, 2, 'main');                                       // the MEMORY1 popup, as in the screenshot
let pop = document.getElementById('spRrPop');
const go = pop.querySelectorAll('tr.sp-rrp-go');
assert.strictEqual(go.length, 3, 'ES1 category, ES1 item and SFXGUY item are tappable');
go[2].click();                                                        // SFXGUY - item
pop = document.getElementById('spRrPop');
assert(/SFXGUY - item/.test(pop.text()), 'the SFXGUY roll opened');
assert(/a saying off his shelf/.test(pop.text()) && /a quip/.test(pop.text()), 'with every entry it held');
assert.strictEqual(body.querySelectorAll('section.sp-rrp').length, 1, 'one popup at a time');
console.log('rr-chainpick ok');
