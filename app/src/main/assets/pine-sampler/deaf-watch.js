/* window.PineDeafWatch - the terminal noticing its own deafness.
 *
 * 2026-09-13: the station dispatched for hours and the tablet was silent.
 * The panel looked perfectly alive, because the feed and every API call go
 * through the NATIVE BRIDGE. What had died was Chromium's network stack
 * inside this WebView, and with it every fetch, every <audio> and every
 * <video> - the only three things the broadcast needs.
 *
 * The operator had to notice, say so, and wait while it was found. That is
 * the thing this removes.
 *
 * WHAT IT TESTS, AND WHY IT IS NOT ABOUT AUDIO.
 *
 * The obvious watchdog - "no sound for a while, so reload" - cannot tell
 * deafness from an ordinary quiet stretch, and this station has real ones:
 * a record playing under nobody talking is not a fault. So the test is the
 * FAULT ITSELF, directly, and it is unambiguous:
 *
 *     the bridge answers          (the app's own HTTP client is fine)
 *     a plain fetch does not      (Chromium's stack is gone)
 *
 * Both roads go to the same station over the same Wi-Fi. When one works
 * and the other does not, the difference is the WebView, and no amount of
 * dead air or silence can produce that pattern.
 *
 * TWICE, NEVER ONCE. A single failed fetch is ordinary - a stalling
 * station, a dropped packet, a request cancelled by a repaint. It takes
 * two consecutive rounds, a full interval apart, with the bridge answering
 * in both, before this will end a process the operator is watching.
 *
 * AND THE APP DECIDES, NOT THIS FILE. It asks the bridge to revive; the
 * bridge holds the rest period (five minutes) and can refuse. A page that
 * has gone wrong cannot put the terminal into a restart loop.
 */
(function (root) {
  'use strict';

  var EVERY_MS = 30000;      /* how often the pair of roads are compared */
  /* #1317b: LONGER THAN THE STATION'S WORST STALL, or this watch cannot
   * tell a slow station from a dead stack. The first build used eight
   * seconds and the station routinely blocks its event loop for ten to
   * fifteen - measured, 180s of stall in a 600s window - so the bridge
   * (which waits) answered while this fetch timed out, and the watch
   * read "deaf" and restarted a perfectly healthy terminal seventy
   * seconds after it started. */
  var PROBE_MS = 25000;
  var STRIKES = 3;           /* consecutive rounds before anything happens */

  var timer = null;
  var strikes = 0;
  var last = {at: 0, bridge: null, web: null, say: 'not looked yet'};
  var reviving = false;

  function api() { return root.pineDesktop; }

  /* The cheapest true thing the station will say, down each road. */
  var PROBE = '/api/dj/sections';

  /* Both roads are timed, because the COMPARISON is the evidence and a
     bridge that took longer than the web probe was allowed proves
     nothing at all. */
  function viaBridge() {
    var bridge = api();
    if (!bridge || !bridge.get) return Promise.resolve({ok: null, ms: 0});
    var t0 = Date.now();
    return bridge.get(PROBE).then(
      function () { return {ok: true, ms: Date.now() - t0}; },
      function () { return {ok: false, ms: Date.now() - t0}; });
  }

  function viaWeb() {
    /* No cache, so a stored answer cannot stand in for a working stack.
     * The timeout matters as much as the failure: a stack that has died
     * often hangs rather than refusing. */
    var done = false;
    return new Promise(function (settle) {
      var give = function (ok) { if (!done) { done = true; settle(ok); } };
      setTimeout(function () { give(false); }, PROBE_MS);
      try {
        root.fetch(PROBE, {cache: 'no-store'}).then(
          function (r) { give(!!r && r.status > 0); },
          function () { give(false); });
      } catch (err) { give(false); }
    });
  }

  function look() {
    if (reviving) return;
    Promise.all([viaBridge(), viaWeb()]).then(function (got) {
      var bridge = got[0].ok;
      var bridgeMs = got[0].ms;
      var web = got[1];
      last = {at: Date.now(), bridge: bridge, bridgeMs: bridgeMs,
              web: web, say: ''};

      /* The bridge being down too means the station or the network is
         away, which is not this fault and not ours to fix. */
      if (bridge !== true) {
        strikes = 0;
        last.say = 'the bridge is not answering either - not deafness';
        return;
      }
      if (web) {
        strikes = 0;
        last.say = 'both roads answer';
        return;
      }
      /* #1317b: the bridge only counts as evidence if it was QUICK. A
         bridge that took as long as the web probe was given describes a
         slow station, not a dead stack, and the station is slow often. */
      if (bridgeMs >= PROBE_MS * 0.6) {
        strikes = 0;
        last.say = 'the station is slow (bridge took ' + bridgeMs
          + 'ms) - that is not deafness';
        return;
      }

      strikes += 1;
      last.say = 'the bridge answers and the web does not - strike '
        + strikes + ' of ' + STRIKES;
      if (strikes < STRIKES) return;

      var bridgeApi = api();
      /* The shim hangs one function off the bridge per method name, so
         `revive` is a function here or the app is too old to have it. */
      if (!bridgeApi || typeof bridgeApi.revive !== 'function') {
        last.say += ' (this build has no way to revive itself)';
        return;
      }
      reviving = true;
      last.say = 'deaf on ' + STRIKES + ' rounds - asking to be revived';
      try {
        Promise.resolve(bridgeApi.revive({
          now: true,
          why: 'the WebView network is dead: the bridge answers ' + PROBE
             + ' and fetch does not'
        })).then(function (said) {
          /* An answer at all means it declined - a revival does not
             return, because the process is gone. */
          reviving = false;
          strikes = 0;
          last.say = 'the app declined: '
            + ((said && said.say) || 'no reason given');
        }, function () {
          reviving = false;
        });
      } catch (err) {
        reviving = false;
      }
    }, function () { /* a broken round is not evidence of anything */ });
  }

  root.PineDeafWatch = {
    start: function () {
      if (timer) return;
      /* Not immediately: a page that has just loaded is still opening
         its own connections, and a probe in that crowd proves nothing. */
      setTimeout(look, 20000);
      timer = setInterval(look, EVERY_MS);
    },
    stop: function () {
      if (timer) clearInterval(timer);
      timer = null;
    },
    /* Numbers the operator can look at rather than a claim in a comment. */
    state: function () {
      return {at: last.at, bridge: last.bridge, bridgeMs: last.bridgeMs,
              web: last.web, strikes: strikes, say: last.say};
    },
    /* For proving it works without waiting for the fault. */
    look: look
  };

  try { root.PineDeafWatch.start(); } catch (err) { /* no watch, no harm */ }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineDeafWatch;
  }
})(typeof window !== 'undefined' ? window : globalThis);
