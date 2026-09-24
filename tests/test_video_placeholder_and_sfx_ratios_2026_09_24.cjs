const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const view = require('../desktop/renderer/script-page.js').view;

class Node {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.style = {};
    this.listeners = {};
    this.hidden = false;
    this.textContent = '';
  }
  appendChild(node) { this.children.push(node); node.parent = this; return node; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  dispatch(name) { this.listeners[name](); }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); }
}

function withDocument(t) {
  const old = global.document;
  global.document = {
    createElement: (tag) => new Node(tag),
    createTextNode: (text) => Object.assign(new Node('#text'), {textContent: text})
  };
  t.after(() => { global.document = old; });
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

const turn = () => new Promise((resolve) => setImmediate(resolve));

test('folder ratios load, paint live values, save exact API keys and revert failures', async (t) => {
  withDocument(t);
  const get = deferred();
  const writes = [];
  let reads = 0;
  const top = new Node('div');
  const loading = view.folderRatioControls(top, {
    get(route) {
      assert.equal(route, '/api/sfx/ratios');
      return reads++ === 0 ? get.promise
        : Promise.resolve({ads_share: 37, video_share: 80});
    },
    post(route, body) {
      const pending = deferred();
      writes.push({route, body, pending});
      return pending.promise;
    }
  });
  const [adsRow, videoRow, status] = top.children;
  const ads = adsRow.children[1], adsValue = adsRow.children[2];
  const video = videoRow.children[1], videoValue = videoRow.children[2];
  assert.equal(ads.disabled, true);
  assert.equal(video.value, '80');
  get.resolve({ads_share: 15, video_share: 80, effective_video_share: 100});
  await loading;
  assert.equal(ads.value, '15');
  assert.equal(videoValue.textContent, '80%');
  assert.match(status.textContent, /overrides/);
  ads.value = '37'; ads.dispatch('input');
  assert.equal(adsValue.textContent, '37%');
  assert.equal(writes.length, 0, 'dragging does not POST every input tick');
  ads.dispatch('change');
  await turn();
  assert.equal(ads.disabled, false);
  assert.deepEqual(writes[0].body, {ads_share: 37, video_share: 80});
  video.value = '25'; video.dispatch('input'); video.dispatch('change');
  await turn();
  assert.equal(writes.length, 1, 'second save queues behind the first');
  assert.equal(videoValue.textContent, '25%', 'draft remains visible');
  writes[0].pending.resolve({ok: true, ads_share: 37, video_share: 80});
  await turn();
  assert.deepEqual(writes[1].body, {ads_share: 37, video_share: 25});
  writes[1].pending.reject(new Error('offline'));
  await turn();
  await turn();
  assert.equal(video.value, '80');
  assert.equal(ads.value, '37');
  assert.equal(videoValue.textContent, '80%');
  assert.match(status.textContent, /offline/);
  assert.equal(reads, 2, 'failed write refreshes station truth');
});

test('folder video preview waits for a presented frame, not loadeddata', (t) => {
  withDocument(t);
  const item = view.folderSample({video: true, name: 'spot', url: '/spot.mp4',
    poster_url: '/spot.jpg', seconds: 12});
  const frame = item.children[1];
  const [icon, poster, play, media] = frame.children;
  assert.equal(icon.src.endsWith('/spark/asset/pinebox.png'), true);
  assert.equal(poster.src.endsWith('/spot.jpg'), true);
  assert.match(media.style.cssText, /visibility:hidden/);
  assert.match(media.style.cssText, /object-fit:contain/);
  assert.equal(play.title, 'Play video preview');
  let presented;
  media.requestVideoFrameCallback = (callback) => { presented = callback; return 1; };
  media.videoWidth = 1920; media.videoHeight = 1080;
  media.currentTime = 0;
  media.readyState = 1; media.dispatch('loadeddata');
  assert.notEqual(media.style.visibility, 'visible');
  media.readyState = 2; media.dispatch('loadeddata');
  assert.equal(typeof presented, 'function');
  assert.notEqual(media.style.visibility, 'visible');
  assert.equal(poster.hidden, false);
  presented();
  assert.equal(media.style.visibility, 'visible');
  assert.equal(poster.hidden, true);
  assert.equal(play.style.display, 'none');
  media.dispatch('emptied');
  assert.equal(media.style.visibility, 'hidden');
  assert.equal(play.style.display, 'grid');
  presented();
  assert.equal(media.style.visibility, 'hidden', 'stale frame callbacks stay hidden');
});

test('older WebView reveals only after playback advances or a seek completes', (t) => {
  withDocument(t);
  const item = view.folderSample({video: true, name: 'old', url: '/old.mp4'});
  const frame = item.children[1];
  const media = frame.children.at(-1);
  media.videoWidth = 640; media.videoHeight = 480;
  media.readyState = 2; media.currentTime = 0;
  media.dispatch('loadeddata');
  assert.notEqual(media.style.visibility, 'visible');
  media.currentTime = 0.02; media.dispatch('timeupdate');
  assert.notEqual(media.style.visibility, 'visible');
  media.currentTime = 0.12; media.dispatch('timeupdate');
  assert.equal(media.style.visibility, 'visible');
  media.dispatch('emptied');
  assert.equal(media.style.visibility, 'hidden');
  media.readyState = 2; media.seeking = false;
  media.dispatch('seeked');
  assert.equal(media.style.visibility, 'visible');
  media.dispatch('emptied');
  media.videoWidth = 0; media.currentTime = 0;
  media.dispatch('loadeddata');
  assert.equal(media.style.visibility, 'hidden');
  media.videoWidth = 640; media.dispatch('playing');
  media.currentTime = 0.1; media.dispatch('timeupdate');
  assert.equal(media.style.visibility, 'visible', 'late dimensions do not strand older WebView');
});

test('other video surfaces gate native video behind frame-ready cover', () => {
  const source = (name) => fs.readFileSync(path.join(__dirname, '..',
    'desktop/renderer', name), 'utf8');
  const slideshow = source('slideshow.js');
  const presentation = source('presentation.js');
  const renderer = source('renderer.js');
  const listen = source('listen.js');
  assert.match(slideshow, /media\.style\.visibility = 'hidden'[\s\S]*media\.addEventListener\('loadeddata', armFrame\)/);
  assert.match(slideshow, /media\.requestVideoFrameCallback\(function \(\) \{/);
  assert.match(slideshow, /pinebox\.png/);
  assert.match(presentation, /screen\.style\.visibility = "hidden";[\s\S]*screen\.hidden = false;\s*screen\.src/);
  assert.match(presentation, /screen\.addEventListener\("loadeddata", armFrame\)/);
  assert.match(presentation, /screen\.requestVideoFrameCallback\(\(\) => \{/);
  assert.match(renderer, /media\.addEventListener\("loadeddata", armFrame\)/);
  assert.match(renderer, /media\.requestVideoFrameCallback\(\(\) => \{/);
  assert.match(renderer, /object-fit:contain;visibility:hidden/);
  assert.match(listen, /vid\.hidden = true;\s*showPlexus\(true\);[\s\S]*vid\.src = genUrl\(pick\)/);
});
