const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app/src/main/assets/pine-views/talk-dot.js'), 'utf8');

function harness() {
  const timers = new Map();
  let timerId = 0;
  const docHandlers = {};
  const buttonHandlers = {};
  const doc = {
    activeElement: null,
    addEventListener(type, fn) { docHandlers[type] = fn; },
    createElement() {
      return {
        style: {}, isConnected: true,
        setAttribute() {},
        addEventListener(type, fn) { buttonHandlers[type] = fn; },
        setPointerCapture() {},
      };
    },
    body: {appendChild(button) { this.button = button; }},
  };
  class Input {
    constructor() {
      this.tagName = 'INPUT';
      this.type = 'text';
      this.isConnected = true;
      this.nativeSets = 0;
      this.events = [];
      this.current = '';
    }
    get value() { return this.current; }
    set value(next) { this.nativeSets++; this.current = next; }
    getBoundingClientRect() { return {top: 20, right: 300, bottom: 60}; }
    dispatchEvent(event) { this.events.push(event.type); }
    focus() { doc.activeElement = this; }
    setSelectionRange(start, end) { this.selection = [start, end]; }
  }
  const root = {
    document: doc,
    HTMLInputElement: Input,
    innerWidth: 800,
    innerHeight: 600,
    addEventListener() {},
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
  root.PineTalkDot.captureNext = fn => { capture = fn; starts++; state = 'listening'; return Promise.resolve(); };
  root.PineTalkDot.finish = () => { stops++; state = 'idle'; };
  root.PineTalkDot.state = () => state;
  const input = new Input();
  input.focus();
  docHandlers.focusin({target: input});
  function down() { buttonHandlers.pointerdown({pointerId: 1, preventDefault() {}}); }
  function up() { buttonHandlers.pointerup({}); }
  function fireHold() { for (const fn of timers.values()) fn(); timers.clear(); }
  return {input, doc, Input, down, up, fireHold, say: words => capture(words),
    get starts() { return starts; }, get stops() { return stops; }};
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

console.log('field dictation: tap, hold, append, focus passed');
