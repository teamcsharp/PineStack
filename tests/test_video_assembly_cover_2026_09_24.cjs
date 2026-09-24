const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

function node(tag) {
  return {
    tagName: tag, style: {}, parentNode: null, complete: true, naturalWidth: 256,
    setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name] || ''; },
    appendChild(child) { child.parentNode = this; },
    removeChild(child) { child.parentNode = null; }
  };
}

test('video assembly hides the native placeholder until a frame is painted', () => {
  const events = {};
  const parent = node('section');
  const video = node('video');
  video.parentNode = parent;
  video.readyState = 0;
  video.videoWidth = 0;
  video.duration = 16;
  video.currentTime = 0;
  video.paused = true;
  video.addEventListener = (name, fn) => { (events[name] ||= []).push(fn); };
  video.removeEventListener = (name, fn) => {
    events[name] = (events[name] || []).filter((one) => one !== fn);
  };
  video.requestVideoFrameCallback = (fn) => { video.frameReady = fn; return 3; };
  video.cancelVideoFrameCallback = () => {};
  const context = {document: {createElement: node, head: node('head')},
    location: {protocol: 'http:', host: 'station'},
    getComputedStyle: () => ({position: 'relative'}),
    desktopMusicUrl: (path) => 'http://station' + path,
    setTimeout: (fn) => { fn(); return 1; }, clearTimeout, console};
  context.window = context;
  vm.runInNewContext(fs.readFileSync(require.resolve('../desktop/renderer/wall-transition.js'), 'utf8'), context);
  const cover = context.PineWallTransition.cover(video, {container: parent});
  assert.equal(video.style.visibility, 'hidden');
  assert.equal(video.poster, 'http://station/spark/asset/pinebox.png');
  video.readyState = 2;
  video.videoWidth = 640;
  events.loadeddata.forEach((fn) => fn());
  assert.equal(video.style.visibility, 'hidden');
  assert.ok(video.currentTime > 0 && video.currentTime < 0.1);
  video.frameReady();
  assert.equal(video.style.visibility, 'visible');
  assert.equal(cover.isWaiting(), false);
  video.readyState = 0;
  events.loadstart.forEach((fn) => fn());
  assert.equal(video.style.visibility, 'hidden');
  cover.destroy();
  assert.equal(video.parentNode, parent);
});
