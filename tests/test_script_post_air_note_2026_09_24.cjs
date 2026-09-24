const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../desktop/renderer/script.js'), 'utf8');
const hour = '2026-09-24T14';
const lineId = 'a'.repeat(32);
const said = 'The old line.';
const line = {id: lineId, air_at: 1790272805, text: said};

function harness(options = {}) {
  const calls = [];
  const stored = [];
  const policy = [];
  const local = new Map();
  const api = {
    async get(route) {
      calls.push(['GET', route]);
      if (route === '/api/screenplay') {
        return {hours: options.hours || [{key: hour, since: 1790272800, until: 1790276400}]};
      }
      if (route.endsWith('/line/' + lineId)) {
        if (options.lookupError) throw new Error('station unavailable');
        if (!route.includes('/' + hour + '/')) throw new Error('No such line in that hour');
        return options.missingLine ? {line: 'other', hour_key: hour}
          : {line: lineId, hour_key: hour, provenance: {}};
      }
      if (route === '/api/screenplay/' + hour) return {notes: stored};
      if (route === '/api/orchestrator/notes') {
        return {notes: options.hidePolicyReads ? [] : policy};
      }
      throw new Error('Unexpected GET ' + route);
    },
    async post(route, body) {
      calls.push(['POST', route, body]);
      if (route === '/api/screenplay/' + hour + '/note') {
        const row = {...body, id: 'deadbeef'};
        stored.push(row);
        if (options.loseScreenplayAck && stored.length === 1) {
          throw new Error('screenplay response lost');
        }
        return {ok: true, hour_key: hour, note: row};
      }
      if (route === '/api/orchestrator/notes') {
        if (options.failPolicyOnce && !options.failed) {
          options.failed = true;
          throw new Error('writer room unavailable');
        }
        if (options.pausePolicy) await options.pausePolicy;
        policy.push({...body});
        return {ok: true};
      }
      throw new Error('Unexpected POST ' + route);
    }
  };
  const document = {readyState: 'loading', addEventListener() {}, getElementById() { return null; }};
  const window = {pineDesktop: api};
  vm.runInNewContext(script, {window, document, localStorage: {
    getItem(key) { return local.get(key) || null; },
    setItem(key, value) { local.set(key, value); }
  }}, {filename: 'script.js'});
  const notes = window.PineScript.notes();
  notes[lineId] = {note: 'Keep the reply direct.', edit: 'The clearer line.', said};
  return {view: window.PineScript, notes, calls, stored, policy, local, options};
}

test('joins the aired line to a screenplay note and a verified writer-room order', async () => {
  const h = harness();
  const result = await h.view.sendDraft(lineId, said, line);
  assert.equal(result.sent, true);
  assert.equal(h.stored.length, 1);
  assert.equal(h.stored[0].target_id, 'ln-' + lineId);
  assert.equal(h.stored[0].text,
    'Direction: Keep the reply direct.\nAired: The old line.\nEdit: The clearer line.');
  assert.equal(h.policy.length, 1);
  assert.equal(h.policy[0].text, 'Keep the reply direct.\nPrefer this wording: The clearer line.');
  assert.equal(h.policy[0].source, 's:26092414:deadbeef');
  assert.equal(h.notes[lineId].edit, 'The clearer line.');
  assert.equal(h.notes[lineId].delivery.sent, true);
  assert.match(h.local.get('pineScriptNotes'), /The clearer line/);
  assert.equal(h.calls.filter((call) => call[0] === 'POST').length, 2);
});

test('a line absent from the screenplay never creates a detached note or policy order', async () => {
  const h = harness({missingLine: true});
  await assert.rejects(h.view.sendDraft(lineId, said, line), /not found in the screenplay ledger/);
  assert.equal(h.calls.filter((call) => call[0] === 'POST').length, 0);
  assert.equal(h.notes[lineId].edit, 'The clearer line.');
});

test('a failed line lookup reports the station error and performs no writes', async () => {
  const h = harness({lookupError: true});
  await assert.rejects(h.view.sendDraft(lineId, said, line), /station unavailable/);
  assert.equal(h.calls.filter((call) => call[0] === 'POST').length, 0);
});

test('a prepared line uses its verified air hour, even when written in an older hour', async () => {
  const old = {key: '2026-09-23T14', since: 1790186400, until: 1790190000};
  const current = {key: hour, since: 1790272800, until: 1790276400};
  const h = harness({hours: [current, old]});
  await h.view.sendDraft(lineId, said, {id: lineId, ts: old.since + 5});
  assert.equal(h.notes[lineId].delivery.hour, hour);
  assert.equal(h.stored.length, 1);
  assert.ok(h.calls.some((call) => call[1].includes('/' + old.key + '/line/')));
});

test('retry resumes after a policy failure without duplicating the screenplay note', async () => {
  const h = harness({failPolicyOnce: true});
  await assert.rejects(h.view.sendDraft(lineId, said, line), /writer room unavailable/);
  assert.equal(h.notes[lineId].delivery.noteId, 'deadbeef');
  assert.equal(h.notes[lineId].delivery.sent, undefined);
  await h.view.sendDraft(lineId, said, line);
  assert.equal(h.stored.length, 1);
  assert.equal(h.policy.length, 1);
  assert.equal(h.notes[lineId].delivery.sent, true);
});

test('retry reconciles a screenplay write whose response was lost', async () => {
  const h = harness({loseScreenplayAck: true});
  await assert.rejects(h.view.sendDraft(lineId, said, line), /screenplay response lost/);
  await h.view.sendDraft(lineId, said, line);
  assert.equal(h.stored.length, 1);
  assert.equal(h.policy.length, 1);
});

test('a policy POST without readback remains pending and retry finds the saved order', async () => {
  const h = harness({hidePolicyReads: true});
  await assert.rejects(h.view.sendDraft(lineId, said, line), /not visible in the writer-room policy book/);
  assert.equal(h.notes[lineId].delivery.sent, undefined);
  h.options.hidePolicyReads = false;
  await h.view.sendDraft(lineId, said, line);
  assert.equal(h.policy.length, 1);
  assert.equal(h.notes[lineId].delivery.sent, true);
});

test('an edit made during sending remains an unsent draft', async () => {
  let release;
  const pausePolicy = new Promise((resolve) => { release = resolve; });
  const h = harness({pausePolicy});
  const pending = h.view.sendDraft(lineId, said, line);
  for (let i = 0; i < 20 && !h.calls.some((call) => call[1] === '/api/orchestrator/notes'
      && call[0] === 'POST'); i++) await new Promise((resolve) => setImmediate(resolve));
  h.notes[lineId] = {...h.notes[lineId], edit: 'A newer edit.'};
  release();
  const result = await pending;
  assert.equal(result.stale, true);
  assert.equal(h.notes[lineId].edit, 'A newer edit.');
  assert.equal(h.notes[lineId].delivery.sent, undefined);
});

test('an overlong direction keeps the draft and performs no writes', async () => {
  const h = harness();
  h.notes[lineId].note = 'x'.repeat(161);
  await assert.rejects(h.view.sendDraft(lineId, said, line), /160 characters/);
  assert.equal(h.calls.length, 0);
  assert.equal(h.notes[lineId].note.length, 161);
});

test('typing and clicking the visible send button posts the edited line', async () => {
  const nodes = new Map();
  class Element {
    constructor(tag) {
      this.tag = tag;
      this.children = [];
      this.listeners = {};
      this.dataset = {};
      this.classList = {add() {}, toggle() {}};
      this.value = '';
      this.textContent = '';
    }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren(...children) { this.children = children; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    fire(name) { return this.listeners[name](); }
  }
  const document = {
    readyState: 'loading', addEventListener() {},
    getElementById(id) { return nodes.get(id) || null; },
    querySelectorAll() { return []; },
    createElement(tag) { return new Element(tag); },
    createDocumentFragment() { return new Element('fragment'); }
  };
  for (const id of ['scFeed', 'scTally', 'scNote']) {
    const node = new Element('div'); node.id = id;
  }
  const stored = [];
  const policy = [];
  const api = {
    async readConfig() { return {}; },
    async get(route) {
      if (route === '/api/dj/provenance/' + lineId) return {id: lineId, line};
      if (route === '/api/screenplay') {
        return {hours: [{key: hour, since: 1790272800, until: 1790276400}]};
      }
      if (route.endsWith('/line/' + lineId)) return {line: lineId, hour_key: hour};
      if (route === '/api/screenplay/' + hour) return {notes: stored};
      if (route === '/api/orchestrator/notes') return {notes: policy};
      throw new Error(route);
    },
    async post(route, body) {
      if (route.endsWith('/note')) {
        const row = {...body, id: 'deadbeef'};
        stored.push(row);
        return {ok: true, note: row};
      }
      if (route === '/api/orchestrator/notes') {
        policy.push(body);
        return {ok: true};
      }
      throw new Error(route);
    }
  };
  const window = {
    pineDesktop: api,
    PineScriptLineage: {
      RING_ROWS: 240,
      paperworkHint() { return {keeps: true, tappable: true}; },
      read(payload) { return {id: payload.id, line: payload.line, said: payload.line.text}; },
      page() { return []; }
    },
    PineScriptStage: {close() {}, preload() {}}
  };
  vm.runInNewContext(script, {window, document, localStorage: {
    getItem() { return null; }, setItem() {}
  }}, {filename: 'script.js'});
  const host = new Element('div');
  window.PineStationFeed = {subscribeView(_host, receive) {
    receive({rows: [line]}); return () => {};
  }};
  await window.PineScript.mount(host);
  window.PineScript.pick(lineId);
  await new Promise((resolve) => setImmediate(resolve));
  const walk = (node, predicate) => {
    if (predicate(node)) return node;
    for (const child of node.children) {
      const found = walk(child, predicate);
      if (found) return found;
    }
    return null;
  };
  const body = nodes.get('scBody');
  const fields = [];
  const visit = (node) => {
    if (node.tag === 'textarea') fields.push(node);
    node.children.forEach(visit);
  };
  visit(body);
  assert.equal(fields.length, 2);
  fields[0].value = 'Make it more direct.';
  fields[0].fire('input');
  fields[1].value = 'The revised line.';
  fields[1].fire('input');
  const send = walk(body, (node) => node.tag === 'button'
    && node.textContent === 'Send back to the writer room');
  assert.ok(send);
  assert.equal(send.disabled, false);
  await send.fire('click');
  assert.equal(send.disabled, true);
  assert.equal(stored[0].target_id, 'ln-' + lineId);
  assert.match(stored[0].text, /Edit: The revised line\./);
  assert.equal(policy[0].text, 'Make it more direct.\nPrefer this wording: The revised line.');
});
