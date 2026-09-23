const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const RENDERER = path.join(__dirname, '..', 'desktop', 'renderer');
const read = (name) => fs.readFileSync(path.join(RENDERER, name), 'utf8');
const settle = () => new Promise((resolve) => setImmediate(resolve));

function feedHarness() {
  const observers = [];
  const documentListeners = new Map();
  const document = {
    hidden: false,
    addEventListener(name, fn) { documentListeners.set(name, fn); },
    removeEventListener(name, fn) {
      if (documentListeners.get(name) === fn) documentListeners.delete(name);
    }
  };
  class MutationObserver {
    constructor(fn) { this.fn = fn; observers.push(this); }
    observe() {}
    disconnect() { this.disconnected = true; }
  }
  let requests = 0;
  const root = {
    document,
    MutationObserver,
    PineLcdDialogue: {stationRows: (station) => station.chat || []},
    pineDesktop: {get: async (route) => {
      assert.equal(route, '/api/dj');
      requests += 1;
      return {server_ms: Date.now(), chat: [{id: String(requests)}]};
    }},
    requestAnimationFrame: () => 1,
    cancelAnimationFrame() {}
  };
  let timer = 0;
  const context = {
    window: root,
    globalThis: root,
    console,
    Date,
    Promise,
    Set,
    setInterval: () => ++timer,
    clearInterval() {}
  };
  vm.runInNewContext(read('sampler-feed.js'), context,
    {filename: 'sampler-feed.js'});
  return {
    root,
    observers,
    document,
    documentListeners,
    get requests() { return requests; }
  };
}

function host(active) {
  const classes = new Set(active ? ['active'] : []);
  return {
    hidden: false,
    offsetParent: active ? {} : null,
    classList: {contains: (name) => classes.has(name)},
    activate(on) {
      if (on) classes.add('active');
      else classes.delete('active');
      this.offsetParent = on ? {} : null;
    }
  };
}

test('one shared request feeds hardware while inactive views skip repainting', async () => {
  const h = feedHarness();
  const pane = host(false);
  const hardware = [];
  const paints = [];
  const leaveHardware = h.root.PineStationFeed.subscribe(
    (payload) => hardware.push(payload));
  const leavePane = h.root.PineStationFeed.subscribeView(
    pane, (payload) => paints.push(payload));

  await settle();
  await settle();
  assert.equal(h.requests, 1, 'both consumers share the initial /api/dj read');
  assert.equal(hardware.length, 1, 'the always-on producer receives the beat');
  assert.equal(paints.length, 0, 'the hidden view does no DOM work');

  await h.root.PineStationFeed.refresh();
  assert.equal(h.requests, 2);
  assert.equal(hardware.length, 2);
  assert.equal(paints.length, 0);

  pane.activate(true);
  h.observers[0].fn();
  assert.equal(paints.length, 1, 'showing the view paints the retained newest beat');
  assert.equal(paints[0].station.chat[0].id, '2');

  await h.root.PineStationFeed.refresh();
  assert.equal(paints.length, 2, 'an active view follows subsequent beats');

  pane.activate(false);
  h.observers[0].fn();
  await h.root.PineStationFeed.refresh();
  assert.equal(h.requests, 4);
  assert.equal(hardware.length, 4, 'hardware remains current while the tab is away');
  assert.equal(paints.length, 2, 'the hidden view returns to zero repaint work');

  leavePane();
  leaveHardware();
  assert.equal(h.observers[0].disconnected, true);
});

test('document visibility also holds and resumes a mounted active view', async () => {
  const h = feedHarness();
  const pane = host(true);
  const paints = [];
  const leave = h.root.PineStationFeed.subscribeView(
    pane, (payload) => paints.push(payload));
  await settle();
  await settle();
  assert.equal(paints.length, 1);

  h.document.hidden = true;
  await h.root.PineStationFeed.refresh();
  assert.equal(paints.length, 1);
  h.document.hidden = false;
  h.documentListeners.get('visibilitychange')();
  assert.equal(paints.length, 2);
  leave();
});

test('LCD and mounted views use the shared feed without losing full payloads', () => {
  const lcd = read('lcd.js');
  assert.ok(lcd.includes('PineStationFeed.subscribe(stationBeat)'));
  assert.doesNotMatch(lcd, /bridge\.get\(['"]\/api\/dj['"]\)/,
    'the LCD must not run a second full station poll');

  for (const file of ['listen.js', 'music.js', 'script.js', 'sampler.js']) {
    assert.ok(read(file).includes('PineStationFeed.subscribeView'),
      file + ' should hold paint work while its host is inactive');
  }
  assert.ok(read('presentation.js').includes('PineStationFeed.subscribeView'));

  const stage = read('script-stage.js');
  assert.match(stage, /!document\.hidden\s*&&\s*host\.offsetParent\s*!==\s*null/,
    'the Script WebGL stage must not render behind an inactive view');

  const feed = read('sampler-feed.js');
  assert.ok(feed.includes('api().get("/api/dj")'));
  assert.doesNotMatch(feed, /[?&]lean=/,
    'the shared request keeps stream_now and the full diagnostic chat ring');
});
