// [changelog-cache] A station that does not answer never blanks the changelog:
// the panel keeps the last history it received, notes it, and asks again.
const assert = require('node:assert/strict');
const test = require('node:test');

class Node {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.className = ''; this.textContent = '';
    this.hidden = false; this.title = ''; this.attrs = {}; this.isConnected = true;
  }
  appendChild(child) { this.children.push(child); return child; }
  insertBefore(child) { this.children.unshift(child); return child; }
  replaceChildren(...kids) { this.children = kids; }
  setAttribute(name, value) { this.attrs[name] = value; }
  addEventListener() {}
  contains() { return false; }
  closest() { return null; }
  querySelectorAll() { return []; }
  querySelector(selector) {
    const cls = selector.replace(/^\./, '');
    const walk = (node) => {
      if (String(node.className).split(' ').includes(cls)) return node;
      for (const kid of node.children) { const hit = walk(kid); if (hit) return hit; }
      return null;
    };
    return walk(this);
  }
  text() { return [this.textContent].concat(this.children.map((kid) => kid.text())).join(' '); }
}

global.window = global;
global.document = {createElement: (tag) => new Node(tag), body: new Node('body'), head: new Node('head')};
const timers = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
global.clearTimeout = () => {};

let answer = null;
global.fetch = () => (answer instanceof Error ? Promise.reject(answer) : Promise.resolve({
  ok: true, json: () => Promise.resolve(answer)}));

const changelog = require('../desktop/renderer/changelog.js');
const settle = () => new Promise((resolve) => setImmediate(resolve));
const panel = () => document.body.children[0];

test('no answer, then history, then no answer again', async () => {
  answer = new Error('changelog 502');
  changelog.open();
  await settle();
  let shown = panel().text();
  assert.match(shown, /The history will appear when the station answers\./);
  assert.doesNotMatch(shown, /unavailable/i);
  assert.equal(timers.length, 1);                      // it asks again

  answer = {entries: [{commit: 'a'.repeat(40), short_commit: 'aaaaaaaaaaaa', task_name: 'Saved task',
    completed_label: '09-28-26 / 2:10 AM CST', file_count: 2, files: [], tokens: {}}],
    total: 839, has_more: false, as_of_label: '09-28-26 / 2:15 AM CST', stale: false};
  changelog.close();
  changelog.open();
  await settle();
  shown = panel().text();
  assert.match(shown, /Saved task/);
  assert.match(shown, /839 committed changes · as of 09-28-26 \/ 2:15 AM CST/);

  answer = new Error('changelog 502');
  changelog.close();
  changelog.open();                                   // reopens on the last history
  await settle();
  shown = panel().text();
  assert.match(shown, /Saved task/);
  assert.match(shown, /the station has not answered yet/);
  assert.doesNotMatch(shown, /unavailable/i);
});
