const assert = require('node:assert/strict');
const {test} = require('node:test');
const view = require('../desktop/renderer/script-page.js').view;

function node(tag) {
  return {
    tag, className: '', textContent: '', children: [], dataset: {},
    attributes: {}, events: {}, scrollTop: 0, hidden: false,
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren(...children) { this.children = children; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { this.events[name] = callback; }
  };
}

function find(root, predicate) {
  if (predicate(root)) return root;
  for (const child of root.children) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}

function all(root, predicate) {
  return [root, ...root.children.flatMap(child => all(child, predicate))]
    .filter(predicate);
}

function words(root) {
  return all(root, () => true).map(item => item.textContent).join(' ');
}

const flush = () => new Promise(resolve => setImmediate(resolve));

function fixture(t, slotId, bridge) {
  const oldDocument = global.document;
  const oldBridge = global.pineDesktop;
  t.after(() => {
    global.document = oldDocument;
    global.pineDesktop = oldBridge;
  });
  const detail = node('div');
  global.document = {
    createElement: node,
    getElementById: id => id === 'spReadinessDetail' ? detail : null
  };
  global.pineDesktop = bridge;
  const model = view.readinessOf({slot_id: slotId, kind: 'news',
    occurrence: 'occ-' + slotId, label: 'News', script: {turns: []}},
  null, Date.now() / 1000);
  return {detail, model};
}

test('news detail loads radio options and commits only an explicit new choice', async t => {
  const calls = [];
  const first = 'https://news.example/first';
  const second = 'https://news.example/second';
  const bridge = {
    get(url) {
      calls.push(['get', url]);
      if (url.startsWith('/api/news/options')) return Promise.resolve({
        options: [
          {title: 'First story', url: first, source: 'Wire',
            availability: 'publisher', excerpt: 'A verified first account.'},
          {title: 'Second story', url: second, source: 'Public feed',
            availability: 'RSS', excerpt: 'An alternate dossier.'}
        ], selected_url: first
      });
      return new Promise(() => {});
    },
    post(url, body) { calls.push(['post', url, body]); return Promise.resolve({ok: true}); }
  };
  const {detail, model} = fixture(t, 'news / 1', bridge);
  view.paintReadinessDetail(model);
  assert.match(words(detail), /Loading story choices/);
  await flush();
  await flush();
  assert.deepEqual(calls[0], ['get', '/api/news/options?slot_id=news%20%2F%201']);
  const group = find(detail, item => item.tag === 'fieldset');
  assert.ok(group);
  assert.match(words(group), /Choose a story for this segment/);
  assert.match(words(group), /Wire \/ publisher/);
  assert.match(words(group), /Public feed \/ RSS/);
  assert.match(words(group), /An alternate dossier/);
  assert.match(words(group), /Selected: First story/);
  const radios = all(group, item => item.tag === 'input' && item.type === 'radio');
  assert.equal(radios.length, 2);
  assert.equal(radios[0].checked, true);
  const choose = find(detail, item => item.className.includes('sp-ready-news-choose'));
  assert.equal(choose.disabled, true);
  assert.equal(calls.filter(call => call[0] === 'post').length, 0);
  radios[1].checked = true;
  radios[1].events.change();
  assert.equal(choose.disabled, false);
  choose.events.click();
  await flush();
  await flush();
  assert.deepEqual(calls.find(call => call[0] === 'post'),
    ['post', '/api/news/choice', {slot_id: 'news / 1', url: second}]);
  assert.match(words(detail), /Selected: Second story/);
  assert.equal(find(detail, item => item.className.includes('sp-ready-news-choose')).disabled, true);
  assert.ok(calls.some(call => call[1] === '/api/director?hour=0'));
  assert.ok(calls.some(call => call[1] === '/api/screenplay'));
});

test('news choices expose fetch and save errors without claiming selection', async t => {
  let reads = 0;
  const bridge = {
    get(url) {
      if (url.startsWith('/api/news/options')) {
        reads += 1;
        if (reads === 1) return Promise.reject(new Error('Feed unavailable'));
        return Promise.resolve({options: [{title: 'New lead',
          url: 'https://news.example/lead', source: 'Wire',
          availability: 'excerpt', excerpt: 'Known facts only.'}], selected_url: ''});
      }
      return new Promise(() => {});
    },
    post() { return Promise.resolve({ok: false, detail: 'Choice rejected'}); }
  };
  const {detail, model} = fixture(t, 'news-errors', bridge);
  view.paintReadinessDetail(model);
  await flush();
  await flush();
  assert.match(words(detail), /Feed unavailable/);
  assert.equal(find(detail, item => item.className === 'sp-ready-news-error').attributes.role, 'alert');
  find(detail, item => item.textContent === 'Retry stories').events.click();
  await flush();
  await flush();
  assert.equal(reads, 2);
  const radio = find(detail, item => item.tag === 'input' && item.type === 'radio');
  radio.checked = true;
  radio.events.change();
  find(detail, item => item.className.includes('sp-ready-news-choose')).events.click();
  await flush();
  await flush();
  assert.match(words(detail), /Choice rejected/);
  assert.match(words(detail), /No story selected/);
});

test('non-news readiness detail does not request news', t => {
  const calls = [];
  const {detail, model} = fixture(t, 'banter-1', {
    get(url) { calls.push(url); return Promise.resolve({}); }
  });
  model.kind = 'banter';
  view.paintReadinessDetail(model);
  assert.equal(find(detail, item => item.className === 'sp-ready-news'), null);
  assert.deepEqual(calls, []);
});

test('malformed options response stays in an actionable error state', async t => {
  const {detail, model} = fixture(t, 'news-invalid', {
    get() { return Promise.resolve({options: null}); }
  });
  view.paintReadinessDetail(model);
  await flush();
  await flush();
  assert.match(words(detail), /News choices are unavailable/);
  assert.ok(find(detail, item => item.textContent === 'Retry stories'));
});
