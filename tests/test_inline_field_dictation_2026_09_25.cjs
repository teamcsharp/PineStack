const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function field(left, top) {
  const node = {
    tagName: 'INPUT', type: 'text', value: '', isConnected: true,
    disabled: false, readOnly: false, isContentEditable: false,
    parentElement: null, events: [], padding: '',
    style: {setProperty(name, value) { if (name === 'padding-right') node.padding = value; }},
    closest: () => null,
    contains: () => false,
    getBoundingClientRect: () => ({left, top, right: left + 210,
      bottom: top + 38, width: 210, height: 38}),
    dispatchEvent(event) { this.events.push(event.type); },
    focus() { this.focused = true; },
    setSelectionRange(start, end) { this.selection = [start, end]; },
  };
  return node;
}

function load(file) {
  const fields = [field(20, 30), field(20, 90)];
  const dot = {id: 'pineTalkDot'};
  let layer;
  let clock = 1000;
  function element() {
    return {
      style: {}, children: [], listeners: {}, attrs: {},
      setAttribute(name, value) { this.attrs[name] = value; },
      addEventListener(name, fn) { this.listeners[name] = fn; },
      appendChild(child) { this.children.push(child); },
      setPointerCapture() {}, remove() {},
    };
  }
  const document = {
    body: {appendChild(node) { if (node.className === 'pine-field-mics') layer = node; }},
    createElement: element,
    getElementById: id => id === 'pineTalkDot' ? dot : null,
    querySelectorAll: () => fields,
    addEventListener() {},
  };
  const root = {
    document, navigator: {mediaDevices: {}}, innerWidth: 1000, innerHeight: 700,
    addEventListener() {}, getComputedStyle: () => ({paddingRight: '8px'}),
    setInterval: () => 1, clearInterval() {},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), {
    window: root, document, navigator: root.navigator,
    requestAnimationFrame: fn => { fn(); return 1; },
    setTimeout: () => 1, clearTimeout() {},
    Date: class extends Date { static now() { return clock; } },
    Event: class { constructor(type) { this.type = type; } },
  }, {filename: file});
  const buttons = layer.children;
  const takes = [];
  let finishes = 0;
  root.PineTalkDot.captureNext = callback => { takes.push(callback); return Promise.resolve(); };
  root.PineTalkDot.state = () => 'listening';
  root.PineTalkDot.finish = () => { finishes += 1; };
  const press = button => button.listeners.pointerdown({preventDefault() {}, pointerId: 1});
  return {fields, buttons, takes, press, now: value => { clock = value; },
    finishes: () => finishes};
}

(async () => {
  for (const file of ['../desktop/renderer/talk-dot.js',
    '../app/src/main/assets/pine-views/talk-dot.js']) {
    const source = fs.readFileSync(path.join(__dirname, file), 'utf8');
    assert.match(source, /DOT_POSITION_KEY/, 'the floating dot persists its position');
    assert.match(source, /pointerdown/, 'the floating dot accepts a drag gesture');
    assert.match(source, /dot\.__pineDragged/, 'a drag cannot accidentally start dictation');
    assert.match(source, /dotKeepVisible/, 'rotation and expanded capture keep the moved dot on screen');
    const h = load(file);
    assert.equal(h.buttons.length, 2, 'each editable input gets a mic');
    assert.equal(h.fields[0].padding, '44px', 'text makes room for its icon');
    assert.equal(h.buttons[0].style.left, '195px', 'mic sits inside right edge');
    assert.equal(h.buttons[1].style.top, '93px');
    h.press(h.buttons[0]);
    h.now(1100);
    h.buttons[0].listeners.pointerup();
    assert.equal(h.finishes(), 0, 'a tap keeps recording');
    h.press(h.buttons[0]);
    assert.equal(h.finishes(), 1, 'second tap stops');
    h.takes[0]('the station is listening');
    assert.equal(h.fields[0].value, 'the station is listening');
    assert.deepEqual(h.fields[0].events, ['input']);
    h.now(2000);
    h.press(h.buttons[1]);
    h.now(2500);
    h.buttons[1].listeners.pointerup();
    assert.equal(h.finishes(), 2, 'hold and release stops');
  }
  console.log('inline field dictation: per-field icons, tap, hold, insertion passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
