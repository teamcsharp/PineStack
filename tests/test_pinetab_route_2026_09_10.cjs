/* WHERE THE BROADCAST GOES - ONE PLACE, NEVER TWO.
 *
 * "My goal is to have the broadcast going to singularly the PineTab or the
 * Pine Box or the Nabu device, the app instance or the application loaded
 * on PC. Individually but never at the same time."
 *
 * That rule is stronger than the station's own model, and these tests exist
 * to pin the gap. The station routes each stream to box | here | both | off
 * | nabu (app.py:93361), and TWO of those five break the rule by
 * themselves: `both` is box AND a page by definition, and `here` means
 * every browser looking - the tablet, the Electron app and any web page on
 * the PC are all "here" clients.
 *
 * So a destination is two decisions - the route, and who holds the air
 * (#1008 /api/radio/solo) - and the tests below check that no combination
 * the picker can produce ever sounds in two rooms.
 *
 * The fixtures are copied from live calls, not imagined: the two players on
 * 10.89.1.13 really were the Electron app and a browser tab sharing one
 * address, which is the case that makes address-matching alone insufficient.
 */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const {
  destinations, currentDestination, planFor, tabShouldPlay, playerFor,
  STREAMS, APP_PREFIX
} = require('../desktop/pinetab-route.cjs');

const routed = (to) => ({music_to: to, voice_to: to, reply_to: to});

const SETTINGS = {
  terminals: {
    pinetab: {name: 'PineTab', addr: '10.89.1.154', play: true},
    desktop: {name: 'This app', addr: '10.89.1.13', play: false}
  },
  dj: {voice: 'caine'}
};

/* Three players, which is the state the operator actually had: the Electron
 * app and a browser tab on one machine, plus the tablet. */
const ROSTER = (owner) => ({
  audio_owner: owner || '',
  listeners: [
    {listener: 'desktop-lshe6j9c', addr: '10.89.1.13', seen: 0.8, what: 'a browser tab'},
    {listener: 'pb546ttu7r', addr: '10.89.1.13', seen: 0.8, what: 'a browser tab'},
    {listener: 'pbq8gj5qvq', addr: '10.89.1.154', seen: 0.3, what: 'a browser tab'}
  ]
});

/* ---- what is on offer ----------------------------------------------- */

test('every sink the operator named is offered, and Off', () => {
  const keys = destinations().map((entry) => entry.key);
  for (const key of ['pinetab', 'app', 'web', 'box', 'nabu', 'off']) {
    assert.ok(keys.includes(key), 'missing destination ' + key);
  }
});

test('NO destination routes to `both` - the one route that cannot be singular', () => {
  for (const entry of destinations()) {
    assert.notEqual(entry.route, 'both',
      entry.key + ' routes to both, which is the box AND a page at once');
  }
});

test('each destination says what it does', () => {
  for (const entry of destinations()) {
    assert.ok(entry.label, entry.key + ' has no label');
    assert.ok(entry.why && entry.why.length > 10, entry.key + ' does not say why');
  }
});

/* ---- picking one ---------------------------------------------------- */

test('the PineTab takes the air by name, and every other page is gagged', () => {
  const plan = planFor('pinetab', SETTINGS, ROSTER());
  assert.equal(plan.ok, true);
  for (const stream of STREAMS) assert.equal(plan.output[stream], 'here');
  /* The tablet's CURRENT listener id, resolved from the roster - never a
   * stored one, which would be a corpse after the next page load. */
  assert.deepEqual(plan.solo, {listener: 'pbq8gj5qvq'});
  assert.equal(plan.muteThisApp, true);
});

test('this app takes the air by its own id prefix, wherever it is running', () => {
  const plan = planFor('app', SETTINGS, ROSTER());
  assert.deepEqual(plan.solo, {listener: 'desktop-lshe6j9c'});
  assert.equal(plan.muteThisApp, false);
  assert.ok(plan.solo.listener.startsWith(APP_PREFIX));
});

test('a web page is the one that is neither the app nor the tablet', () => {
  /* All three share nothing but the roster: one id prefix and one address
   * are what separate them. */
  const plan = planFor('web', SETTINGS, ROSTER());
  assert.deepEqual(plan.solo, {listener: 'pb546ttu7r'});
});

test('the box and the Nabu RELEASE the air rather than leaving an owner behind', () => {
  /* A stale owner gags every page. When the show is on the box that is
   * invisible - until a page destination is picked and the wrong page has
   * it. */
  for (const key of ['box', 'nabu', 'off']) {
    const plan = planFor(key, SETTINGS, ROSTER('pbq8gj5qvq'));
    assert.equal(plan.ok, true, key);
    assert.deepEqual(plan.solo, {clear: true}, key + ' must clear the owner');
    assert.equal(plan.muteThisApp, true, key);
  }
  assert.equal(planFor('box', SETTINGS, ROSTER()).output.music, 'box');
  assert.equal(planFor('nabu', SETTINGS, ROSTER()).output.voice, 'nabu');
  assert.equal(planFor('off', SETTINGS, ROSTER()).output.reply, 'off');
});

test('every device row follows the one destination, so none is left switched on', () => {
  const plan = planFor('pinetab', SETTINGS, ROSTER());
  assert.equal(plan.settings.terminals.pinetab.play, true);
  assert.equal(plan.settings.terminals.desktop.play, false);

  const back = planFor('app', SETTINGS, ROSTER());
  assert.equal(back.settings.terminals.pinetab.play, false);
  assert.equal(back.settings.terminals.desktop.play, true);
});

test('the settings write carries the WHOLE document, because the PUT replaces it', () => {
  const plan = planFor('pinetab', SETTINGS, ROSTER());
  assert.deepEqual(plan.settings.dj, {voice: 'caine'}, 'unrelated keys survive');
  assert.equal(plan.settings.broadcast_to, 'pinetab');
  assert.equal(SETTINGS.terminals.pinetab.play, true, 'the input is not mutated');
});

test('a destination that is not looking at the station is REFUSED, not routed to', () => {
  /* Routing to `here` with nobody holding the air is the exact state where
   * every page sounds at once - the thing this whole file exists to stop.
   * Refusing is the only safe answer. */
  const gone = {audio_owner: '', listeners: [
    {listener: 'desktop-lshe6j9c', addr: '10.89.1.13', seen: 0.8}
  ]};
  const plan = planFor('pinetab', SETTINGS, gone);
  assert.equal(plan.ok, false);
  assert.match(plan.blockers[0], /not looking at the station/);
});

test('a stale player is not a player - it cannot be handed the air', () => {
  const stale = {audio_owner: '', listeners: [
    {listener: 'pbq8gj5qvq', addr: '10.89.1.154', seen: 400}
  ]};
  assert.equal(playerFor('pinetab', stale, SETTINGS), '');
  assert.equal(planFor('pinetab', SETTINGS, stale).ok, false);
});

test('an unknown destination is refused rather than guessed', () => {
  const plan = planFor('speakers', SETTINGS, ROSTER());
  assert.equal(plan.ok, false);
  assert.match(plan.blockers[0], /Unknown destination/);
});

/* ---- reading where it is going -------------------------------------- */

test('where it is going now is read from the station, not remembered', () => {
  const now = currentDestination(routed('box'), SETTINGS, ROSTER());
  assert.equal(now.key, 'box');
  assert.equal(now.singular, true);
});

test('routed to a page WITH an owner names that exact page', () => {
  const now = currentDestination(routed('here'), SETTINGS, ROSTER('pbq8gj5qvq'));
  assert.equal(now.key, 'pinetab');
  assert.equal(now.singular, true);
});

test('routed to a page with NO owner and several looking is NOT singular', () => {
  /* This is the fault condition, and it must be reported as one rather
   * than quietly labelled. */
  const now = currentDestination(routed('here'), SETTINGS, ROSTER());
  assert.equal(now.singular, false);
  assert.match(now.why, /3 pages are sounding at once/);
});

test('routed to a page with one page looking is singular by circumstance', () => {
  const alone = {audio_owner: '', listeners: [
    {listener: 'pbq8gj5qvq', addr: '10.89.1.154', seen: 0.3}
  ]};
  assert.equal(currentDestination(routed('here'), SETTINGS, alone).singular, true);
});

test('`both` is named as the two-room state it is', () => {
  const now = currentDestination(routed('both'), SETTINGS, ROSTER('pbq8gj5qvq'));
  assert.equal(now.singular, false);
  assert.match(now.label, /Pine Box \+ a page/);
});

test('streams pointing different ways is called mixed, and flagged as not singular', () => {
  const now = currentDestination(
    {music_to: 'box', voice_to: 'here', reply_to: 'off'}, SETTINGS, ROSTER());
  assert.equal(now.label, 'Mixed');
  assert.equal(now.singular, false);
});

/* ---- the tablet asks the same question ------------------------------ */

test('the tablet plays only when it IS the destination', () => {
  assert.equal(
    tabShouldPlay(routed('here'), SETTINGS, ROSTER('pbq8gj5qvq')).play, true);
  assert.equal(
    tabShouldPlay(routed('here'), SETTINGS, ROSTER('desktop-lshe6j9c')).play, false);
  assert.equal(tabShouldPlay(routed('box'), SETTINGS, ROSTER()).play, false);
  assert.equal(tabShouldPlay(routed('off'), SETTINGS, ROSTER()).play, false);
});

test('missing state or settings never makes the tablet play by accident', () => {
  assert.equal(tabShouldPlay(null, null, null).play, false);
  assert.equal(tabShouldPlay({}, {}, {}).play, false);
});

test('the desktop and the tablet cannot disagree about who the sink is', () => {
  /* Both ends call the same function against the same two documents, which
   * is the only thing that makes "one room" enforceable rather than hoped
   * for. */
  const state = routed('here');
  const roster = ROSTER('pbq8gj5qvq');
  const desktopView = currentDestination(state, SETTINGS, roster);
  const tabletView = tabShouldPlay(state, SETTINGS, roster);
  assert.equal(desktopView.key === 'pinetab', tabletView.play);
});
