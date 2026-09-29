const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

/* [field-mic-paint] Each field paints its own mic (talk-dot.js); there is
 * no layer and no button. A press is a real pointer event at the window, in
 * the capture phase, on the square the field paints at the right of its
 * padding box. */
function field(left, top) {
  const attrs = {};
  const node = {
    tagName: 'INPUT', type: 'text', value: '', isConnected: true, nodeType: 1,
    disabled: false, readOnly: false, isContentEditable: false,
    parentElement: null, events: [], padding: '', micSize: '',
    /* 210 x 38 with a 1px border */
    offsetWidth: 210, offsetHeight: 38, clientLeft: 1, clientTop: 1,
    clientWidth: 208, clientHeight: 36,
    style: {
      setProperty(name, value) {
        if (name === 'padding-right') node.padding = value;
        if (name === '--pine-mic-size') node.micSize = value;
      },
      removeProperty() {}, getPropertyValue: () => '', getPropertyPriority: () => '',
    },
    closest: selector => selector === '[data-pine-mic="on"]' && attrs['data-pine-mic'] === 'on' ? node : null,
    hasAttribute: name => name in attrs,
    getAttribute: name => name in attrs ? attrs[name] : null,
    setAttribute(name, value) { attrs[name] = String(value); },
    removeAttribute(name) { delete attrs[name]; },
    addEventListener() {}, setPointerCapture() {},
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
  const dot = {id: 'pineTalkDot', setAttribute() {}};
  const listeners = {};
  let clock = 1000;
  function element() {
    return {
      style: {}, children: [], listeners: {}, attrs: {},
      classList: {contains() { return false; }},
      setAttribute(name, value) { this.attrs[name] = value; },
      addEventListener(name, fn) { this.listeners[name] = fn; },
      appendChild(child) { this.children.push(child); },
      setPointerCapture() {}, remove() {},
    };
  }
  let appended = 0;
  const document = {
    body: {appendChild() { appended += 1; }},
    createElement: element,
    getElementById: id => id === 'pineTalkDot' ? dot : null,
    querySelectorAll: () => fields,
    addEventListener() {},
  };
  const root = {
    document, navigator: {mediaDevices: {}}, innerWidth: 1000, innerHeight: 700,
    addEventListener(name, fn) { listeners[name] = fn; }, getComputedStyle: () => ({paddingRight: '8px'}),
    setInterval: () => 1, clearInterval() {},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, file), 'utf8'), {
    window: root, document, navigator: root.navigator,
    requestAnimationFrame: fn => { fn(); return 1; },
    setTimeout: () => 1, clearTimeout() {},
    Date: class extends Date { static now() { return clock; } },
    Event: class { constructor(type) { this.type = type; } },
  }, {filename: file});
  const takes = [];
  let finishes = 0;
  let swallowed = 0;
  root.PineTalkDot.captureNext = callback => { takes.push(callback); return Promise.resolve(); };
  root.PineTalkDot.state = () => 'listening';
  root.PineTalkDot.finish = () => { finishes += 1; };
  /* the middle of the painted square: 2px in from the padding box's right
     edge, 32px, centred - (left + 1 + 208 - 2 - 16, top + 1 + 18) */
  const pointer = (node, x, y) => ({pointerId: 1, button: 0, pointerType: 'touch', clientX: x, clientY: y,
    target: node, preventDefault() { swallowed += 1; }, stopImmediatePropagation() {}});
  const at = (node, x, y) => listeners.pointerdown(pointer(node, x, y));
  const press = node => at(node, node.getBoundingClientRect().left + 191, node.getBoundingClientRect().top + 19);
  const release = node => listeners.pointerup(pointer(node, 0, 0));
  return {fields, takes, press, release, at, now: value => { clock = value; },
    finishes: () => finishes, swallowed: () => swallowed, appended: () => appended};
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
    assert.deepEqual(h.fields.map(f => f.getAttribute('data-pine-mic')), ['on', 'on'],
      'each editable input gets a mic');
    assert.equal(h.appended(), 0, 'no layer, no button: the field is the mic');
    assert.equal(h.fields[0].padding, '44px', 'text makes room for its icon');
    assert.equal(h.fields[0].micSize, '32px', 'the plate is full size in a 38px field');
    h.at(h.fields[0], 60, 49);
    assert.equal(h.takes.length, 0, 'a press in the text belongs to the field');
    assert.equal(h.swallowed(), 0);
    h.at(h.fields[0], 188, 49);
    assert.equal(h.takes.length, 0, 'a press just left of the painted square is text');
    h.press(h.fields[0]);
    assert.equal(h.takes.length, 1, 'mic sits inside right edge');
    h.now(1100);
    h.release(h.fields[0]);
    assert.equal(h.finishes(), 0, 'a tap keeps recording');
    h.press(h.fields[0]);
    assert.equal(h.finishes(), 1, 'second tap stops');
    h.takes[0]('the station is listening');
    assert.equal(h.fields[0].value, 'the station is listening');
    assert.deepEqual(h.fields[0].events, ['input']);
    h.now(2000);
    h.press(h.fields[1]);
    h.now(2500);
    h.release(h.fields[1]);
    assert.equal(h.finishes(), 2, 'hold and release stops');
  }
  console.log('inline field dictation: per-field icons, tap, hold, insertion passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
