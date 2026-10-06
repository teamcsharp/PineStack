// No animation frames run: late preview playback must stop through media events.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/pine-pip.js'), 'utf8');
const panel = source.slice(source.indexOf('  function pinePipPanel(w)'), source.indexOf('\n  let state, overlay'));
const listeners = {}, videos = [];
let closed = 0, reset = 0, viewerClosed = 0;
const lightbox = {style: {display: 'block'}};
class Element {
  constructor() { this.style = {setProperty() {}}; this.classList = {toggle() {}}; }
  append() {} appendChild() {} addEventListener() {} contains() { return false; }
}
const doc = {
  head: new Element(), body: new Element(), documentElement: new Element(),
  createElement: () => new Element(),
  getElementById: id => id === 'lightbox' ? lightbox : null,
  querySelectorAll: () => videos,
  addEventListener(type, fn, capture) { assert.equal(capture, true); listeners[type] = fn; }
};
const w = {document: doc, addEventListener() {}, requestAnimationFrame() {return 1;}, cancelAnimationFrame() {},
  PineAdViewer: {close() {viewerClosed++;}},
  closeLightbox() {closed++; lightbox.style.display = 'none';},
  lightboxDuckReset() {reset++;}};
vm.runInNewContext(panel + '\npinePipPanel(w);', {w});
w.PinePipPanel.set(true, '', true);
assert.equal(closed, 1, 'entering PiP closes the panel lightbox');
assert.equal(reset, 1, 'entering PiP releases its audio hold');
const preview = {paused: false, loop: true, autoplay: true, muted: false,
  matches: () => true, pause() {this.paused = true;}};
videos.push(preview);
lightbox.style.display = 'block';
listeners.play({target: preview});
assert.equal(preview.paused, true);
assert.equal(preview.loop, false);
assert.equal(preview.autoplay, false);
assert.equal(preview.muted, true);
assert.equal(closed, 2, 'a late preview closes without an animation frame');
assert.ok(viewerClosed >= 2);
const live = {paused: false, muted: false, matches: () => false};
listeners.play({target: live});
assert.equal(live.paused, false, 'live program continues');
assert.equal(live.muted, false);
w.PinePipPanel.set(false, '', true);
preview.paused = false;
listeners.play({target: preview});
assert.equal(preview.paused, false, 'expanded desktop permits previews');
// Opening H3 while PiP is active cannot create a hidden modal or audio hold.
const viewer = fs.readFileSync(path.join(__dirname, '../desktop/renderer/ad-viewer.js'), 'utf8');
const viewerRoot = {document: {body: {classList: {contains: () => true}}}};
vm.runInNewContext(viewer, {window: viewerRoot, document: viewerRoot.document});
viewerRoot.PineAdViewer.openGallery();
console.log('Pine Pip preview cleanup passed');
