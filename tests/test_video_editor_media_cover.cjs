'use strict';
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..', 'desktop', 'renderer');
const source = fs.readFileSync(path.join(root, 'video-editor.js'), 'utf8');
const markup = fs.readFileSync(path.join(root, 'video-editor.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'video-editor.css'), 'utf8');
const start = source.indexOf('  function coverPoster(');
const end = source.indexOf('  var M = window.PineVideoEditModel', start);
assert.ok(start >= 0 && end > start);
const timers = [];
const helpers = vm.runInNewContext(source.slice(start, end) + '\n({coverPoster, bindMediaCover})', {
  setTimeout(fn) { timers.push(fn); return timers.length; },
  clearTimeout(id) { timers[id - 1] = null; },
});

function classes() {
  const values = new Set();
  return {add(name) { values.add(name); }, remove(name) { values.delete(name); },
    toggle(name, on) { if (on) values.add(name); else values.delete(name); },
    contains(name) { return values.has(name); }};
}

function harness(withCallback = true) {
  const events = {}, callbacks = [];
  const image = {src: '', classList: classes()};
  const cover = {hidden: false, querySelector(tag) { assert.equal(tag, 'img'); return image; }};
  const buttonEvents = {};
  const button = {disabled: true, textContent: 'Play original',
    addEventListener(name, fn) { buttonEvents[name] = fn; }};
  const media = {src: '', readyState: 0, videoWidth: 0, videoHeight: 0, classList: classes(), plays: 0,
    addEventListener(name, fn) { (events[name] ||= []).push(fn); },
    getAttribute(name) { return name === 'src' ? this.src : null; },
    play() { this.plays += 1; return Promise.resolve(); }};
  if (withCallback) media.requestVideoFrameCallback = fn => { callbacks.push(fn); };
  const bound = helpers.bindMediaCover(media, cover, button);
  function fire(name) { (events[name] || []).forEach(fn => fn()); }
  return {media, cover, image, button, callbacks, bound, fire,
    click() { buttonEvents.click(); }};
}

test('cover remains until data and a decoded frame, and resets before another source', () => {
  const h = harness();
  h.bound.setPoster({poster_url: '/real-first-frame.jpg'});
  assert.equal(h.image.src, '/real-first-frame.jpg');
  assert.equal(h.image.classList.contains('ve-real-poster'), true);
  h.image.onerror();
  assert.equal(h.image.src, '/spark/asset/pinebox.png');
  assert.equal(h.image.classList.contains('ve-real-poster'), false);
  h.bound.setPoster({poster_url: '/spark/asset/pinebox.png'});
  assert.equal(h.image.classList.contains('ve-real-poster'), false);
  h.media.src = '/source.mp4'; h.fire('loadstart');
  assert.equal(h.button.disabled, false);
  h.media.readyState = 1; h.media.videoWidth = 640; h.media.videoHeight = 384;
  h.fire('loadeddata');
  assert.equal(h.cover.hidden, false);
  h.media.readyState = 2; h.fire('loadeddata');
  assert.equal(h.cover.hidden, false);
  h.callbacks.shift()();
  assert.equal(h.cover.hidden, true);
  assert.equal(h.media.classList.contains('ve-frame-ready'), true);
  h.fire('canplay');
  h.bound.reset();
  h.callbacks.shift()();
  assert.equal(h.cover.hidden, false);
  assert.equal(h.media.classList.contains('ve-frame-ready'), false);
});

test('source cover can start playback while native controls are hidden', async () => {
  const h = harness(false);
  h.media.src = '/source.mp4'; h.fire('loadstart');
  h.click();
  assert.equal(h.media.plays, 1);
  assert.equal(h.cover.hidden, false);
  h.media.readyState = 2; h.media.videoWidth = 320; h.media.videoHeight = 180;
  h.fire('loadeddata');
  assert.equal(h.cover.hidden, true);
  assert.equal(h.media.classList.contains('ve-frame-ready'), true);
  assert.match(css, /video:not\(\.ve-frame-ready\)\{visibility:hidden/);
});

test('a paused WebView can reveal decoded data when its frame callback stalls', () => {
  const h = harness();
  h.media.src = '/source.mp4'; h.fire('loadstart');
  h.media.readyState = 2; h.media.videoWidth = 320; h.media.videoHeight = 180;
  h.fire('loadeddata');
  assert.equal(h.cover.hidden, false);
  timers.filter(Boolean).at(-1)();
  assert.equal(h.cover.hidden, true);
});

test('every visible editor video has an aspect-preserving cover or native poster', () => {
  for (const id of ['recordingCover', 'splitCover', 'parodyCover']) {
    assert.match(markup, new RegExp('id="' + id + '"[^>]*class="ve-media-cover"'));
  }
  assert.match(css, /\.ve-media-cover img\.ve-real-poster\{[^}]*object-fit:contain/);
  assert.match(markup, /id="parodySourcePreview"[^>]*controls[^>]*poster="\/spark\/asset\/pinebox\.png"/);
  assert.match(markup, /id="parodyVideo"[^>]*playsinline/);
  assert.match(markup, /id="parodyPlay"[^>]*aria-label="Play sequence"/);
  assert.match(source, /el\('parodyPlay'\)\.addEventListener\('click', play/);
});
