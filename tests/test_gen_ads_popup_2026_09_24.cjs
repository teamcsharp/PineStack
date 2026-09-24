const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'gen-ads.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'renderer', 'gen-ads.css'), 'utf8');

function harness(get, post, duck) {
  const stats = {textures: 0, disposed: 0, contexts: 0, cancelled: 0};
  const listeners = {};
  let document;

  class Node {
    constructor(tag) {
      this.tagName = tag.toUpperCase();
      this.children = [];
      this.attrs = {};
      this.handlers = {};
      this.parentNode = null;
      this.className = '';
      this.style = {};
      this.disabled = false;
      this.hidden = false;
      this._text = '';
      this._src = '';
      this.clientWidth = 800;
      this.clientHeight = 450;
      this.isConnected = true;
      this.classList = {
        add: (name) => { if (!this.className.split(' ').includes(name)) this.className += ' ' + name; },
        remove: (name) => { this.className = this.className.split(' ').filter((x) => x !== name).join(' '); },
        contains: (name) => this.className.split(' ').includes(name),
        toggle: (name, force) => {
          if (force === undefined ? !this.classList.contains(name) : force) this.classList.add(name);
          else this.classList.remove(name);
        }
      };
      if (tag === 'video') {
        this.paused = true;
        this.currentTime = 0;
        this.duration = 6;
        this.readyState = 0;
        this.videoWidth = 640;
        this.videoHeight = 360;
        this.volume = 1;
        this.muted = false;
        this.load = () => {};
        this.play = () => { this.paused = false; this.fire('play'); return Promise.resolve(); };
        this.pause = () => { this.paused = true; this.fire('pause'); };
      }
    }
    get textContent() { return this._text || this.children.map((x) => x.textContent).join(''); }
    set textContent(value) { this._text = String(value); this.children = []; }
    get src() { return this._src; }
    set src(value) { this._src = String(value); }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    getAttribute(name) { return this.attrs[name]; }
    removeAttribute(name) { delete this.attrs[name]; if (name === 'src') this._src = ''; }
    appendChild(node) { node.parentNode = this; this.children.push(node); return node; }
    insertBefore(node, before) {
      node.parentNode = this;
      this.children.splice(this.children.indexOf(before), 0, node);
      return node;
    }
    replaceChildren(...nodes) { this.children.forEach((x) => { x.parentNode = null; }); this.children = []; nodes.forEach((x) => this.appendChild(x)); }
    remove() { if (this.parentNode) this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; this.isConnected = false; }
    addEventListener(name, handler) { (this.handlers[name] ||= []).push(handler); }
    fire(name, details = {}) { (this.handlers[name] || []).forEach((fn) => fn({target: this, preventDefault() {}, ...details})); }
    click() { this.fire('click'); }
    focus() { document.activeElement = this; }
    scrollIntoView() {}
    querySelectorAll(selector) {
      const all = [];
      const visit = (node) => { node.children.forEach((child) => { all.push(child); visit(child); }); };
      visit(this);
      if (selector === '.pga-row') return all.filter((x) => x.className.split(' ').includes('pga-row'));
      if (selector === 'button:not(:disabled), input:not(:disabled)') return all.filter((x) => ['BUTTON', 'INPUT'].includes(x.tagName) && !x.disabled);
      throw new Error('unexpected selector: ' + selector);
    }
  }

  document = {body: new Node('body'), head: new Node('head'), activeElement: null,
    createElement: (tag) => new Node(tag)};
  const THREE = {
    WebGLRenderer: class {
      constructor() { this.domElement = new Node('canvas'); }
      setPixelRatio() {}
      setSize() {}
      render() {}
      getContext() { return {drawingBufferWidth: 800, drawingBufferHeight: 450, RGBA: 1,
        UNSIGNED_BYTE: 1, readPixels(x, y, w, h, format, type, pixel) { pixel[0] = 120; }}; }
      dispose() { stats.disposed += 1; }
      forceContextLoss() { stats.contexts += 1; }
    },
    VideoTexture: class {
      constructor(video) { assert.equal(video.tagName, 'VIDEO'); stats.textures += 1; this.repeat = {set() {}}; this.offset = {set() {}}; }
      dispose() { stats.disposed += 1; }
    },
    Scene: class { add() {} },
    OrthographicCamera: class { constructor() { this.position = {}; } },
    PlaneGeometry: class { dispose() { stats.disposed += 1; } },
    MeshBasicMaterial: class { dispose() { stats.disposed += 1; } },
    Mesh: class { constructor(geometry, material) { this.geometry = geometry; this.material = material; this.scale = {set() {}}; } },
    LinearFilter: 1
  };
  const root = {
    document, THREE, devicePixelRatio: 1,
    pineDesktop: {get, post}, PineDuck: duck,
    pineIcon: (ref) => '<svg data-ref="' + ref + '"></svg>',
    desktopMusicUrl: (url) => 'http://station' + url,
    ResizeObserver: class { observe() {} disconnect() {} },
    requestAnimationFrame: () => 1,
    cancelAnimationFrame: () => { stats.cancelled += 1; },
    addEventListener: (name, handler) => { (listeners[name] ||= []).push(handler); },
    removeEventListener: (name, handler) => { listeners[name] = (listeners[name] || []).filter((x) => x !== handler); }
  };
  root.window = root;
  vm.runInNewContext(source, {window: root, document, Promise, module: {exports: {}}, console});
  const find = (cls) => {
    const all = [];
    const visit = (node) => { node.children.forEach((child) => { all.push(child); visit(child); }); };
    visit(document.body);
    return all.find((node) => node.className.split(' ').includes(cls));
  };
  return {root, document, stats, find, key(name) {
    (listeners.keydown || []).forEach((fn) => fn({key: name, target: document.activeElement, preventDefault() {}}));
  }};
}

function flush() { return new Promise((resolve) => setImmediate(resolve)); }

test('feed selection drives video texture, history, send, and disposes on close', async () => {
  const rows = [
    {id: 'a/1', name: 'Morning spot', url: '/a.mp4', duration: 12, created_at: '2026-09-24T08:00:00Z', air_count: 1, history: [{aired_at: '2026-09-24T09:00:00Z', program: 'Morning'}]},
    {id: 'b', name: 'Night spot', url: '/b.mp4', duration: 9, air_count: 0, history: []}
  ];
  const calls = [];
  const h = harness(() => Promise.resolve({rows}), (route) => { calls.push(route); return Promise.resolve({ok: true}); });
  h.root.PineGenAds.open();
  assert.match(h.find('pga-feed-state').textContent, /Loading/);
  await flush();
  assert.equal(h.find('pga-feed').querySelectorAll('.pga-row').length, 2);
  assert.equal(h.find('pga-video').src, 'http://station/a.mp4');
  assert.equal(h.find('pga-history').children.length, 1);
  assert.equal(h.stats.textures, 1);
  h.key('ArrowDown');
  assert.equal(h.find('pga-video').src, 'http://station/b.mp4');
  assert.equal(h.find('pga-history-count'), undefined);
  assert.equal(h.stats.contexts, 1);
  h.find('pga-send').click();
  await flush();
  assert.deepEqual(calls, ['/api/gen-ads/b/send']);
  assert.equal(h.find('pga-notice').textContent, 'Queued for booth.');
  h.root.PineGenAds.close();
  assert.equal(h.find('pga-back'), undefined);
  assert.equal(h.stats.contexts, 2);
  assert.equal(h.stats.disposed, 8);
});

test('empty, failed refresh, and booth rejection stay recoverable', async () => {
  let answer = {rows: []};
  let rejectSend = false;
  const h = harness(() => answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer),
    () => rejectSend ? Promise.reject(new Error('Booth offline')) : Promise.resolve({ok: true}));
  h.root.PineGenAds.open();
  await flush();
  assert.match(h.find('pga-empty').textContent, /No generated/);
  answer = new Error('Network offline');
  h.find('pga-header-actions').children[0].click();
  await flush();
  assert.match(h.find('pga-feed-state').textContent, /Network offline/);
  answer = {rows: [{id: 7, name: 'Returned', url: '/returned.mp4', history: []}]};
  h.find('pga-header-actions').children[0].click();
  await flush();
  assert.equal(h.find('pga-video').src, 'http://station/returned.mp4');
  rejectSend = true;
  h.find('pga-send').click();
  await flush();
  assert.match(h.find('pga-notice').textContent, /Booth offline/);
  assert.equal(h.find('pga-send').disabled, false);
  h.key('Escape');
  assert.equal(h.find('pga-back'), undefined);
});

test('preview takes a temporary duck hold only while playing', async () => {
  const events = [];
  const duck = {REPORT: 0.1,
    hold: (name, level, node) => events.push(['hold', name, level, node.isConnected]),
    release: (name) => events.push(['release', name])};
  const h = harness(() => Promise.resolve({rows: [
    {id: 1, url: '/one.mp4'}, {id: 2, url: '/two.mp4'}
  ]}), () => Promise.resolve({ok: true}), duck);
  h.root.PineGenAds.open();
  await flush();
  const video = h.find('pga-video');
  assert.ok(video.classList.contains('pb-sampler'));
  assert.equal(video.muted, false);
  video.play();
  assert.deepEqual(events[0].slice(0, 3), ['hold', 'gen-ads-preview', 0.1]);
  assert.equal(video.volume, 1);
  video.pause();
  assert.deepEqual(events[1], ['release', 'gen-ads-preview']);
  video.play();
  h.find('pga-feed').querySelectorAll('.pga-row')[1].click();
  assert.deepEqual(events.slice(2, 4).map((event) => event[0]), ['hold', 'release']);
  video.play();
  video.fire('ended');
  assert.deepEqual(events.slice(4, 6).map((event) => event[0]), ['hold', 'release']);
  video.play();
  h.root.PineGenAds.close();
  assert.deepEqual(events.slice(6, 8).map((event) => event[0]), ['hold', 'release']);
});

test('epoch seconds and ISO timestamps display as real production dates', async () => {
  const h = harness(() => Promise.resolve({rows: [
    {id: 1, name: 'Epoch', url: '/one.mp4', created_at: 1790236800,
      history: [{aired_at: '2026-09-24T10:00:00Z'}]}
  ]}), () => Promise.resolve({ok: true}));
  h.root.PineGenAds.open();
  await flush();
  assert.match(h.find('pga-meta').textContent, /2026/);
  assert.doesNotMatch(h.find('pga-meta').textContent, /1970/);
  assert.match(h.find('pga-history').textContent, /2026/);
  h.root.PineGenAds.close();
});

test('ad poster and square icon cover native video until a decoded frame', async () => {
  const h = harness(() => Promise.resolve({rows: [
    {id: 1, url: '/one.mp4', poster_url: '/one-poster.png'},
    {id: 2, url: '/two.mp4'}
  ]}), () => Promise.resolve({ok: true}));
  h.root.PineGenAds.open();
  await flush();
  const stage = h.find('pga-stage');
  const poster = h.find('pga-poster');
  const video = h.find('pga-video');
  assert.equal(poster.src, 'http://station/one-poster.png');
  assert.equal(stage.classList.contains('pga-webgl'), false);
  assert.equal(stage.classList.contains('pga-native-ready'), false);
  poster.fire('error');
  assert.equal(poster.src, 'http://station/spark/asset/pinebox.png');
  assert.equal(poster.classList.contains('pga-poster-icon'), true);
  video.readyState = 2;
  video.fire('loadeddata');
  assert.equal(stage.classList.contains('pga-webgl'), true);
  h.find('pga-feed').querySelectorAll('.pga-row')[1].click();
  assert.equal(poster.src, 'http://station/spark/asset/pinebox.png');
  assert.equal(poster.classList.contains('pga-poster-icon'), true);
  assert.equal(stage.classList.contains('pga-webgl'), false);
  h.root.PineGenAds.close();
});

test('responsive viewer reserves real media and mobile feed space', () => {
  assert.match(css, /\.pga-stage[\s\S]*aspect-ratio: 16 \/ 9/);
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /\.pga-feed \{ display: flex; overflow: auto hidden/);
  assert.match(css, /\.pga-video \{ object-fit: contain; visibility: hidden/);
  assert.match(source, /new THREE\.VideoTexture\(view\.video\)/);
});

test('panel-injected authorized request handles listing and send, then releases launcher', async () => {
  const calls = [];
  let closed = 0;
  const h = harness(() => { throw new Error('wrong bridge'); },
    () => { throw new Error('wrong bridge'); });
  h.root.PineGenAds.open({
    request: (path, options) => {
      calls.push([path, options.method || 'GET']);
      return path === '/api/gen-ads'
        ? {rows: [{id: 'ad1', name: 'One', url: '/one.mp4'}]}
        : {sent: true};
    },
    onClose: () => { closed += 1; }
  });
  await flush();
  h.find('pga-send').click();
  await flush();
  assert.deepEqual(calls, [
    ['/api/gen-ads', 'GET'], ['/api/gen-ads/ad1/send', 'POST'],
    ['/api/gen-ads', 'GET']
  ]);
  h.root.PineGenAds.close();
  assert.equal(closed, 1);
});
