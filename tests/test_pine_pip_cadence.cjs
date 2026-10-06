// Exercise the actual injected panel with controlled video/display clocks.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../desktop/renderer/pine-pip.js'), 'utf8');
const panel = source.slice(source.indexOf('  function pinePipPanel(w)'), source.indexOf('\n  let state, overlay'));

function fixture(callbacks = true) {
  let next = 0, paints = 0;
  const rafs = new Map(), decoded = new Map(), animations = [];
  class Element {
    constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.clientWidth = 440; this.clientHeight = 293; }
    append(...nodes) { nodes.forEach(n => { n.parentElement = this; this.children.push(n); }); }
    appendChild(n) { this.append(n); }
    contains(n) { return this.children.includes(n) || this.children.some(c => c.contains(n)); }
    addEventListener() {}
    getAttribute() { return null; }
    getAnimations() { return []; }
    animate(_, options) { animations.push(options.duration); return { finished: Promise.resolve() }; }
    remove() { this.parentElement.children = this.parentElement.children.filter(n => n !== this); }
    getContext() { return { drawImage: v => { if (v === video) paints++; } }; }
    toDataURL() { return 'data:image/jpeg;base64,fixture'; }
  }
  const body = new Element('body'), head = new Element('head'), video = new Element('video');
  Object.assign(video, { id: 'testVideo', className: '', isConnected: true, paused: false, ended: false, readyState: 4, videoWidth: 640, videoHeight: 360, currentSrc: 'first.mp4', dataset: {} });
  if (callbacks) {
    video.requestVideoFrameCallback = fn => { decoded.set(++next, fn); return next; };
    video.cancelVideoFrameCallback = id => decoded.delete(id);
  }
  video.matches = () => false;
  body.append(video);
  const w = {
    document: { body, head, documentElement: { classList: { toggle() {} } }, createElement: tag => new Element(tag), querySelectorAll: () => [video] },
    devicePixelRatio: 1, addEventListener() {}, postMessage() {},
    requestAnimationFrame: fn => { rafs.set(++next, fn); return next; },
    cancelAnimationFrame: id => rafs.delete(id),
    getComputedStyle: () => ({ display: 'block', visibility: 'visible', opacity: '1' }),
    matchMedia: () => ({ matches: true })
  };
  vm.runInNewContext(panel + '\npinePipPanel(w);', { w });
  const display = t => { const work = [...rafs.values()]; rafs.clear(); work.forEach(fn => fn(t)); };
  const decode = t => { const work = [...decoded.values()]; decoded.clear(); work.forEach(fn => fn(t, {})); };
  w.PinePipPanel.set(true, '', true);
  display(0);
  return { w, video, display, decode, animations, rafs, decoded, paints: () => paints,
    tiles: () => body.children.find(n => n.id === 'pine-pip-panel').children.filter(n => n.className === 'pip-tile') };
}

for (const fps of [24, 25, 30, 60]) {
  const f = fixture(), before = f.paints();
  for (let i = 1; i <= fps; i++) { f.decode(i * 1000 / fps); f.display(i * 1000 / fps); }
  assert.equal(f.paints() - before, fps, `${fps} fps source paints every decoded frame`);
  const count = f.paints();
  for (let i = 1; i <= 60; i++) f.display(1000 + i * 1000 / 60);
  assert.equal(f.paints(), count, 'display ticks do not recopy unchanged decoded frames');
  assert.equal(f.decoded.size, 1, 'one video callback per player');
  f.w.PinePipPanel.set(false, '', true);
  assert.equal(f.decoded.size, 0); assert.equal(f.rafs.size, 0); assert.equal(f.tiles().length, 0);
}

const f = fixture();
const tile = f.tiles()[0], before = f.paints();
f.video.readyState = 1; f.video.videoWidth = 0;
f.display(550); f.decode(560);
assert.equal(f.tiles()[0], tile, 'buffering retains the same visible tile');
assert.equal(f.paints(), before, 'buffering retains the last drawable frame');
f.video.currentSrc = 'replacement.mp4'; f.video.videoWidth = 640; f.video.readyState = 4;
f.decode(570);
assert.equal(f.paints(), before + 1, 'replacement paints on its first decoded frame');
assert.deepEqual(f.animations, [420], 'source cuts add no close/open animation');
f.w.PinePipPanel.set(false, '', true);
f.w.PinePipPanel.set(true, '', true); f.display(1000);
assert.equal(f.decoded.size, 1, 're-entry starts exactly one video callback');
const fallback = fixture(false), start = fallback.paints();
for (let i = 1; i <= 60; i++) fallback.display(i * 1000 / 60);
assert.equal(fallback.paints() - start, 60, 'older players paint at display cadence');
console.log('PiP cadence: 24/25/30/60 fps, buffering, source cuts, fallback and cleanup passed');
