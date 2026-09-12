/* THE SLIDESHOW'S TRAFFIC BUDGET, AND THE TWO SCREENS NOT DRIFTING APART.
 *
 * #1240 puts ~/bin/media-slideshow on the tablet. Two things about that are
 * worth a test rather than a comment, and they are the two that would fail
 * silently:
 *
 * 1. THE ONE-REQUEST GATE. The station is a single-process FastAPI app that
 *    is also recording a live radio show, and this glass has a measured
 *    history of stalling it: 38 concurrent requests produced a 46-second
 *    media stall on 2026-09-11. A slideshow wants a picture every ten
 *    seconds, a filmstrip and a telemetry panel, so the gate in
 *    slideshow-source.js is the whole reason the view is safe to leave
 *    open. A regression there costs nothing on a desk and takes the station
 *    off air on the tablet - which is exactly the kind of fault that is
 *    found by an operator and not by a developer.
 *
 * 2. THE TRANSITION LISTS AGREEING. The client cycles a list of twenty and
 *    the station refuses a `transition` that is not in ITS list. Those two
 *    lists are in different languages in different repositories-worth of
 *    file, and the moment they disagree the tablet writes a setting the box
 *    rejects - or worse, accepts a name it cannot draw. So the test reads
 *    app.py and compares, rather than trusting that both were edited.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

/* Both files are plain IIFEs that publish on globalThis and module.exports,
 * so they load under node with no DOM. slideshow.js only builds its view
 * inside mount(), which is why its list is reachable here. */
const source = require('../desktop/renderer/slideshow-source.js');
const view = require('../desktop/renderer/slideshow.js');

/* A bridge that records every call, standing in for pineDesktop. */
function fakeBridge(delayMs) {
  const calls = [];
  globalThis.pineDesktop = {
    get(route) {
      calls.push(route);
      return new Promise((settle) => setTimeout(
        () => settle({route, rows: [], n: calls.length}), delayMs || 1));
    },
    post(route, body) {
      calls.push('POST ' + route);
      return Promise.resolve({ok: true, route, body});
    }
  };
  return calls;
}

test('two callers asking for one route share a single request', async () => {
  const calls = fakeBridge(20);
  source.forget();
  const both = await Promise.all([
    source.ask('/api/slideshow/stack'),
    source.ask('/api/slideshow/stack')
  ]);
  assert.equal(calls.length, 1, 'the station should have been asked once');
  assert.equal(both[0], both[1], 'both callers get the same answer object');
});

test('an answer inside its maxAge costs no request at all', async () => {
  const calls = fakeBridge(1);
  source.forget();
  await source.ask('/api/slideshow/favorites');
  await source.ask('/api/slideshow/favorites');
  assert.equal(calls.length, 1);
  /* And a zero maxAge is an explicit "ask anyway", which the hot-load poll
   * depends on - a cached answer to "what is new" is a contradiction. */
  await source.ask('/api/slideshow/favorites', 0);
  assert.equal(calls.length, 2);
});

test('the queue drains one at a time, never in parallel', async () => {
  fakeBridge(15);
  source.forget();
  let open = 0;
  let most = 0;
  const watched = globalThis.pineDesktop.get;
  globalThis.pineDesktop.get = function (route) {
    open += 1;
    if (open > most) most = open;
    return watched(route).then((value) => { open -= 1; return value; });
  };
  await Promise.all([
    source.ask('/a'), source.ask('/b'), source.ask('/c'), source.ask('/d')
  ]);
  assert.equal(most, 1,
    'the station must never see two of this view’s questions at once');
});

test('a runaway caller is refused with a sentence, not silently queued', async () => {
  fakeBridge(500);
  source.forget();
  const asks = [];
  for (let i = 0; i < 40; i += 1) asks.push(source.ask('/route-' + i).catch((e) => e));
  const answers = await Promise.all(asks);
  const refusals = answers.filter((a) => a instanceof Error);
  assert.ok(refusals.length > 0, 'the ceiling should have refused some');
  assert.match(refusals[0].message, /waiting for the station/,
    'a refusal has to say what happened');
});

test('the hot-load question is never answered from cache', async () => {
  const calls = fakeBridge(1);
  source.forget();
  await source.since(1000);
  await source.since(1000);
  assert.equal(calls.length, 2,
    '"anything newer than this stamp" has to be asked every time');
  assert.match(calls[0], /since=1000/);
});

test('the bytes doors are built here, not by each caller', () => {
  assert.equal(source.url('a b.png'), '/api/slideshow/media/a%20b.png');
  assert.equal(source.thumb('a b.png', 128),
    '/api/slideshow/media/a%20b.png?w=128');
  /* A filmstrip cell that forgot the width would pull 1.3 MB to draw 64
   * pixels - the exact shape of the measured stall. */
  assert.match(source.thumb('x.png'), /\?w=128$/);
});

test('page() asks only for what was actually set', async () => {
  const calls = fakeBridge(1);
  source.forget();
  await source.page({limit: 300, kind: 'all', favorites: 0, order: 'shuffle', seed: 7});
  /* kind=all and favorites=0 are the defaults; sending them would make two
   * identical questions look like different routes and defeat the cache. */
  assert.equal(calls[0], '/api/slideshow/playlist?limit=300&order=shuffle&seed=7');
});

test('the client and the station agree on all twenty transitions', () => {
  const app = fs.readFileSync(
    path.join(__dirname, '..', 'app.py'), 'utf8');
  const block = app.match(/SLIDESHOW_TRANSITIONS = \[([\s\S]*?)\]/);
  assert.ok(block, 'app.py should still declare SLIDESHOW_TRANSITIONS');
  const server = (block[1].match(/"([a-z]+)"/g) || [])
    .map((s) => s.replace(/"/g, ''));
  assert.deepEqual(view.TRANSITIONS, server,
    'the tablet cycles a transition the station would refuse, or vice versa');
  assert.equal(server.length, 20);
  assert.equal(server[0], 'all', '"all" stays first: it is the default');
});

test('the view exposes a mount, which is what rail.js looks for', () => {
  assert.equal(typeof view.mount, 'function');
  /* rail.js tries api.mount || api.open || api.start and shows a readable
   * note if none answers. A renamed export is a blank screen. */
});
