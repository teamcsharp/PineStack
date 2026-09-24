'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const M = require('../desktop/renderer/video-edit-model.js');

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'video-editor.js'), 'utf8');
const start = source.indexOf('  function createSfxSplitController(record)');
const end = source.indexOf('  function startParodyEditor()', start);
assert.ok(start >= 0 && end > start);

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.style = {};
    this.classList = {toggle() {}};
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this.readyState = 1;
    this.currentTime = 0;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, event = {}) {
    return Promise.all((this.listeners[type] || []).map(fn => fn.call(this, {
      target: this, preventDefault() {}, stopPropagation() {}, ...event
    })));
  }
  click() { return this.fire('click'); }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this[key] = value; }
  getAttribute(key) { return this[key] || null; }
  getBoundingClientRect() { return {left: 0, width: 300, height: 60}; }
  querySelector(tag) { return this.children.find(child => child.tagName === tag.toUpperCase()); }
  pause() { this.paused = true; }
  play() { this.paused = false; return Promise.resolve(); }
  load() {}
  getContext() { return {clearRect() {}, fillText() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}}; }
}

function harness() {
  const ids = new Map();
  const get = id => { if (!ids.has(id)) ids.set(id, new Element(id === 'splitMedia' ? 'video' : 'div')); return ids.get(id); };
  const keep = new Element('input'), replace = new Element('input');
  keep.value = 'keep'; keep.checked = true; replace.value = 'replace';
  get('splitEditor').hidden = true;
  const calls = [], events = [];
  const win = {addEventListener() {}, dispatchEvent(event) { events.push(event); }};
  win.parent = win;
  const doc = {
    getElementById: get,
    createElement(tag) { return new Element(tag); },
    querySelectorAll(selector) { return selector === 'input[name="splitOriginal"]' ? [keep, replace] : []; },
    querySelector(selector) { return selector === 'input[name="splitOriginal"]:checked' ? (keep.checked ? keep : replace) : null; },
    addEventListener() {},
  };
  const context = {
    M, $, document: doc, window: win, video: new Element('video'),
    bindMediaCover() { return {setPoster() {}, reset() {}}; },
    savePermit: 'permit', disposed: false, sfxSingleMode: false,
    permitTake(answer) { if (answer.save_token) context.savePermit = answer.save_token; },
    requestAnimationFrame() { return 1; }, cancelAnimationFrame() {},
    exportHold() { return Promise.resolve(); },
    CustomEvent: function (name, options) { this.type = name; this.detail = options.detail; },
    async api(method, url, body) {
      calls.push({method, url, body});
      if (url.startsWith('/api/video-editor/sources/')) return {save_token: 'permit'};
      return method === 'POST' ? {id: 'job-1', status: 'queued'}
        : {id: 'job-1', status: 'complete', outputs: [{name: 'Tail.wav', url: '/sfx/tail'}]};
    },
  };
  function $(id) { return get(id); }
  const create = vm.runInNewContext('(' + source.slice(start, end).trim() + ')', context);
  const editor = create({id: 'audio-1', duration: 12, url: '/source.mp4', status: 'ready',
    pine_sfx: {audio_only: true, name: 'Sting'}, waveform: [0, .2, .5, .1]});
  editor.open();
  return {get, keep, replace, calls, events};
}

test('audio split controls preserve order, names and original policy in export', async () => {
  const h = harness();
  assert.equal(h.get('recordingEditor').hidden, true);
  assert.equal(h.get('splitEditor').hidden, false);
  h.get('splitScrub').value = '5';
  await h.get('splitScrub').fire('input');
  await h.get('splitAtPlayhead').click();
  assert.equal(h.get('splitTimeline').children.length, 2);
  h.get('splitName').value = 'Tail';
  await h.get('splitName').fire('change');
  h.get('splitIn').value = '6';
  await h.get('splitIn').fire('change');
  await h.get('splitMoveLeft').click();
  await h.get('splitPieceMode').click();
  assert.equal(h.get('splitPosition').textContent, '0:00.00 / 0:06.00');
  await h.get('splitMedia').fire('seeked');
  await h.get('splitPlay').click();
  h.get('splitMedia').currentTime = 12;
  await h.get('splitMedia').fire('timeupdate');
  assert.equal(h.get('splitPlay').textContent, 'Play');
  h.keep.checked = false; h.replace.checked = true;
  await h.replace.fire('change');
  await h.get('splitExport').click();
  assert.deepEqual(JSON.parse(JSON.stringify(h.calls[1])), {
    method: 'POST', url: '/api/sfx/edit/split', body: {
      source_id: 'audio-1', clips: [
        {in_s: 6, out_s: 12, name: 'Tail'},
        {in_s: 0, out_s: 5, name: 'Sting'}
      ], keep_original: false, save_token: 'permit'
    }
  });
  assert.equal(h.calls[2].url, '/api/sfx/edit/split/job-1');
  assert.equal(h.get('splitResults').hidden, false);
  assert.equal(h.get('splitOutputList').children.length, 1);
  assert.equal(h.events[0].type, 'pine-sfx-edit-split');
});
