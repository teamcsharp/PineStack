const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {fetchJson, waitForRetry, READ_TIMEOUT_MS} = require('../desktop/json-request.cjs');

function reset(message = 'fetch failed') {
  return Object.assign(new TypeError(message), {cause: {code: 'ECONNRESET'}});
}
function response(body = '{"ok":true}', status = 200) {
  return {ok: status >= 200 && status < 300, status, statusText: 'Unavailable',
    text: async () => body};
}

test('GET retries transient resets with bounded backoff and preserves request options', async () => {
  let calls = 0;
  const waits = [], options = {headers: {Authorization: 'Bearer test-key'}};
  const controller = new AbortController(); options.signal = controller.signal;
  const result = await fetchJson('/state', options, {
    fetch: async (_url, sent) => {
      assert.equal(sent.signal, controller.signal); assert.deepEqual(sent.headers, options.headers);
      if (++calls < 3) throw reset(); return response();
    }, wait: async (ms, signal) => { waits.push(ms); assert.equal(signal, controller.signal); }
  });
  assert.deepEqual(result, {ok: true}); assert.equal(calls, 3);
  assert.deepEqual(waits, [250, 750]);
});

test('GET retries a failed body transfer as well as a failed fetch', async () => {
  let calls = 0;
  const result = await fetchJson('/state', {}, {
    fetch: async () => ++calls === 1 ? {ok: true, text: async () => { throw reset('terminated'); }} : response(),
    wait: async () => {}
  });
  assert.deepEqual(result, {ok: true}); assert.equal(calls, 2);
});

test('GET gives up after three transport attempts', async () => {
  let calls = 0;
  await assert.rejects(fetchJson('/state', {}, {
    fetch: async () => { calls++; throw reset(); }, wait: async () => {}
  }), /fetch failed/);
  assert.equal(calls, 3);
});

test('POST, PUT, PATCH and DELETE failures are never retried', async () => {
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']) {
    let calls = 0, waits = 0;
    await assert.rejects(fetchJson('/change', {method, body: '{}'}, {
      fetch: async () => { calls++; throw reset(); }, wait: async () => { waits++; }
    }), /fetch failed/);
    assert.equal(calls, 1); assert.equal(waits, 0);
  }
});

test('HTTP failures and invalid URLs are not transport retries', async () => {
  for (const failure of [
    async () => response('{"detail":"Unauthorized"}', 401),
    async () => response('{"detail":"Unavailable"}', 503),
    async () => { throw new TypeError('Failed to parse URL from broken'); },
    async () => ({ok: false, status: 403, text: async () => { throw reset('terminated'); }})
  ]) {
    let calls = 0, waits = 0;
    await assert.rejects(fetchJson('/state', {}, {
      fetch: async () => { calls++; return failure(); }, wait: async () => { waits++; }
    }));
    assert.equal(calls, 1); assert.equal(waits, 0);
  }
});

test('aborted requests and body aborts do not retry', async () => {
  let calls = 0, waits = 0;
  const controller = new AbortController(); controller.abort(new Error('cancelled before fetch'));
  await assert.rejects(fetchJson('/state', {signal: controller.signal}, {
    fetch: async () => { calls++; return response(); }
  }), /cancelled before fetch/);
  assert.equal(calls, 0);
  await assert.rejects(fetchJson('/state', {}, {
    fetch: async () => { calls++; return {ok: true, text: async () => { throw Object.assign(new Error('cancelled'), {name: 'AbortError'}); }}; },
    wait: async () => { waits++; }
  }), error => error.name === 'AbortError');
  assert.equal(calls, 1); assert.equal(waits, 0);
});

test('caller abort during backoff stops before another attempt', async () => {
  const controller = new AbortController(); let calls = 0;
  const result = fetchJson('/state', {signal: controller.signal}, {
    fetch: async () => { calls++; throw reset(); }
  });
  await Promise.resolve(); await Promise.resolve();
  controller.abort(new Error('cancelled in backoff'));
  await assert.rejects(result, /cancelled in backoff/);
  assert.equal(calls, 1);
});

test('a single default deadline covers retries and supplied deadlines are preserved', async () => {
  const controller = new AbortController(); let deadlines = 0, calls = 0;
  await assert.rejects(fetchJson('/state', {}, {
    timeoutSignal: ms => { assert.equal(ms, READ_TIMEOUT_MS); deadlines++; return controller.signal; },
    fetch: async (_url, sent) => { assert.equal(sent.signal, controller.signal); calls++; throw reset(); },
    wait: async () => controller.abort(Object.assign(new Error('deadline'), {name: 'TimeoutError'}))
  }), error => error.name === 'TimeoutError');
  assert.equal(deadlines, 1); assert.equal(calls, 1);
  const supplied = new AbortController();
  await fetchJson('/state', {signal: supplied.signal}, {
    timeoutSignal: () => { throw new Error('must keep caller deadline'); },
    fetch: async (_url, sent) => { assert.equal(sent.signal, supplied.signal); return response(); }
  });
});

test('JSON and text response behavior remains compatible', async () => {
  assert.deepEqual(await fetchJson('/empty', {}, {fetch: async () => response('')}), {});
  assert.deepEqual(await fetchJson('/text', {}, {fetch: async () => response('plain text')}), {text: 'plain text'});
  const controller = new AbortController(); controller.abort();
  await assert.rejects(waitForRetry(1000, controller.signal), error => error.name === 'AbortError');
});

test('mutations keep their original timeout behavior', async () => {
  const controller = new AbortController();
  for (const signal of [undefined, controller.signal]) {
    await fetchJson('/change', {method: 'POST', body: '{}', signal}, {
      timeoutSignal: () => { throw new Error('Mutation must not get a new default deadline'); },
      fetch: async (_url, sent) => { assert.equal(sent.signal, signal); return response(); }
    });
  }
});

test('main fetchJson delegates with current auth, headers, body and caller signal', async () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'desktop', 'main.js'), 'utf8');
  const start = source.indexOf('async function fetchJson(url, options = {})');
  const end = source.indexOf('async function discoverAgentKey()', start);
  assert(start >= 0 && end > start);
  let seen;
  const context = vm.createContext({readConfig: () => ({apiKey: 'test-key'}),
    authHeaders: cfg => ({Authorization: 'Bearer ' + cfg.apiKey}),
    readStationJson: async (url, options) => { seen = {url, options}; return {ok: true}; }});
  vm.runInContext(source.slice(start, end), context);
  const controller = new AbortController();
  await context.fetchJson('http://station/change', {method: 'POST', body: '{"go":true}',
    signal: controller.signal, headers: {'X-Client': 'Pine'}});
  assert.equal(seen.url, 'http://station/change');
  assert.equal(seen.options.method, 'POST'); assert.equal(seen.options.body, '{"go":true}');
  assert.equal(seen.options.signal, controller.signal);
  assert.equal(seen.options.headers.Authorization, 'Bearer test-key');
  assert.equal(seen.options.headers['Content-Type'], 'application/json');
  assert.equal(seen.options.headers['X-Client'], 'Pine');
});
