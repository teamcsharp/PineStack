const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/src/main/assets/pine-views/talk-dot.js'), 'utf8');

/* [field-mic-paint] The mic is painted by the field itself (talk-dot.js):
 * there is no button to press. A press is a real pointer event at the window,
 * in the capture phase, at the square the field paints at its right edge
 * (inside its padding box); a press anywhere else in the field is the
 * field's own. The assertions below are the button-era ones, unchanged. */
function harness() {
  const timers = new Map();
  let timerId = 0;
  const docHandlers = {};
  const winHandlers = {};
  const doc = {
    activeElement: null,
    addEventListener(type, fn) { docHandlers[type] = fn; },
    createElement() { return {style: {}, setAttribute() {}, addEventListener() {}}; },
    body: {appendChild() {}},
  };
  class Input {
    constructor() {
      this.tagName = 'INPUT';
      this.type = 'text';
      this.nodeType = 1;
      this.isConnected = true;
      this.nativeSets = 0;
      this.events = [];
      this.current = '';
      this.attrs = {};
      this.padding = '';
      /* a 280 x 40 box with a 2px border at (20, 20) */
      this.offsetWidth = 280; this.offsetHeight = 40;
      this.clientLeft = 2; this.clientTop = 2;
      this.clientWidth = 276; this.clientHeight = 36;
      const self = this;
      this.style = {
        setProperty(name, value) { if (name === 'padding-right') self.padding = value; },
        removeProperty() {}, getPropertyValue() { return ''; }, getPropertyPriority() { return ''; },
      };
    }
    get value() { return this.current; }
    hasAttribute(name) { return name in this.attrs; }
    getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
    setAttribute(name, value) { this.attrs[name] = String(value); }
    removeAttribute(name) { delete this.attrs[name]; }
    closest(selector) {
      return selector === '[data-pine-mic="on"]' && this.attrs['data-pine-mic'] === 'on' ? this : null;
    }
    addEventListener() {}
    setPointerCapture() {}
    set value(next) { this.nativeSets++; this.current = next; }
    getBoundingClientRect() { return {left: 20, top: 20, right: 300, bottom: 60, width: 280, height: 40}; }
    dispatchEvent(event) { this.events.push(event.type); }
    focus() { doc.activeElement = this; }
    setSelectionRange(start, end) { this.selection = [start, end]; }
  }
  const root = {
    document: doc,
    HTMLInputElement: Input,
    innerWidth: 800,
    innerHeight: 600,
    addEventListener(type, fn) { winHandlers[type] = fn; },
    setTimeout(fn) { const id = ++timerId; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval() { return ++timerId; },
    clearInterval() {},
  };
  vm.runInNewContext(source, {
    window: root,
    Event: class { constructor(type) { this.type = type; } },
  }, {filename: 'talk-dot.js'});
  let capture;
  let starts = 0;
  let stops = 0;
  let state = 'idle';
  let swallowed = 0;
  root.PineTalkDot.captureNext = fn => { capture = fn; starts++; state = 'listening'; return Promise.resolve(); };
  root.PineTalkDot.finish = () => { stops++; state = 'idle'; };
  root.PineTalkDot.state = () => state;
  const input = new Input();
  input.focus();
  docHandlers.focusin({target: input});
  const pointer = (x, y) => ({pointerId: 1, button: 0, pointerType: 'mouse', clientX: x, clientY: y,
    target: input, preventDefault() { swallowed++; }, stopImmediatePropagation() {}});
  /* the painted square: 32px, 2px in from the padding box's right edge,
     centred - its middle is (20 + 2 + 276 - 2 - 16, 20 + 2 + 18) */
  function downAt(x, y) { winHandlers.pointerdown(pointer(x, y)); }
  function down() { downAt(280, 40); }
  function up() { winHandlers.pointerup(pointer(280, 40)); }
  function fireHold() { for (const fn of timers.values()) fn(); timers.clear(); }
  return {input, doc, Input, down, downAt, up, fireHold, say: words => capture(words),
    get starts() { return starts; }, get stops() { return stops; },
    get swallowed() { return swallowed; }};
}

const tap = harness();
tap.down(); tap.up();
assert.equal(tap.starts, 1, 'first tap starts capture');
tap.down(); tap.up();
assert.equal(tap.stops, 1, 'second tap stops capture');
tap.say('first words');
assert.equal(tap.input.value, 'first words');
tap.down(); tap.up();
tap.say('more words');
assert.equal(tap.input.value, 'first words more words', 'takes append');
assert.equal(tap.input.nativeSets, 2, 'native value setter is used');
assert.deepEqual(tap.input.events, ['input', 'input']);
assert.equal(tap.doc.activeElement, tap.input, 'tap keeps field focus');

const hold = harness();
hold.down(); hold.fireHold();
assert.equal(hold.starts, 1, 'hold starts after threshold');
hold.up();
assert.equal(hold.stops, 1, 'release stops hold capture');
hold.say('held words');
assert.equal(hold.input.value, 'held words');

const moved = harness();
moved.down(); moved.up();
const other = new moved.Input();
other.focus();
moved.say('earlier field');
assert.equal(moved.input.value, 'earlier field');
assert.equal(moved.doc.activeElement, other, 'transcript does not steal focus from another field');

const paint = harness();
assert.equal(paint.input.getAttribute('data-pine-mic'), 'on', 'the field wears its own mic');
assert.equal(paint.input.padding, '36px', 'text makes room for the painted mic');
paint.downAt(100, 40);
assert.equal(paint.starts, 0, 'a press in the text belongs to the field');
assert.equal(paint.swallowed, 0, 'and reaches it untouched');
paint.down();
assert.equal(paint.starts, 1, 'a press on the painted mic starts capture');
assert.equal(paint.input.hasAttribute('data-pine-mic-live'), true, 'the live mic is marked on the field');
paint.up();
paint.say('painted');
assert.equal(paint.input.hasAttribute('data-pine-mic-live'), false, 'and cleared when the words land');

console.log('field dictation: tap, hold, append, focus passed');
