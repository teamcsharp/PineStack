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
 * THREE ROUNDS, NEVER ONCE. A single failed fetch is ordinary - a stalling
 * station, a dropped packet, a request cancelled by a repaint. It takes
 * three consecutive rounds, a full interval apart, with the bridge answering
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
  var warmup = null;
  var looking = false;
  var generation = 0;
  var strikes = 0;
  var last = {at: 0, bridge: null, web: null, say: 'not looked yet'};
  var reviving = false;

  function api() { return root.pineDesktop; }

  /* The cheapest true thing the station will say, down each road. */
  var PROBE = '/api/dj/sections';

  function probeUrl() {
    // A desktop document is file://; its relative /api path is a disk URL.
    // Served station panels keep their own origin for the same-road comparison.
    if (root.location && root.location.protocol === 'file:') {
      try {
        if (typeof root.pineStationBase !== 'function') return null;
        var base = String(root.pineStationBase() || '').replace(/\/$/, '');
        return /^https?:\/\//i.test(base) ? base + PROBE : null;
      } catch (err) { return null; }
    }
    return PROBE;
  }

  /* Both roads are timed, because the COMPARISON is the evidence and a
     bridge that took longer than the web probe was allowed proves
     nothing at all. */
  function viaBridge() {
    var bridge = api();
    if (!bridge || !bridge.get) return Promise.resolve({ok: null, ms: 0});
    var t0 = Date.now();
    return new Promise(function (settle) {
      var done = false;
      var timeout;
      var give = function (ok) {
        if (done) return;
        done = true; clearTimeout(timeout);
        settle({ok: ok, ms: Date.now() - t0});
      };
      timeout = setTimeout(function () { give(false); }, PROBE_MS);
      try { Promise.resolve(bridge.get(PROBE)).then(function () { give(true); }, function () { give(false); }); }
      catch (err) { give(false); }
    });
  }

  function viaWeb() {
    /* No cache, so a stored answer cannot stand in for a working stack.
     * The timeout matters as much as the failure: a stack that has died
     * often hangs rather than refusing. */
    var url = probeUrl();
    if (!url) return Promise.resolve(null);
    var done = false;
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    return new Promise(function (settle) {
      var timeout;
      var give = function (ok) {
        if (!done) { done = true; clearTimeout(timeout); settle(ok); }
      };
      timeout = setTimeout(function () {
        try { if (ctl) ctl.abort(); } catch (err) {}
        give(false);
      }, PROBE_MS);
      try {
        var fileDocument = root.location && root.location.protocol === 'file:';
        root.fetch(url, {cache: 'no-store', mode: fileDocument ? 'no-cors' : 'same-origin',
          signal: ctl ? ctl.signal : undefined}).then(
          // The station API does not expose CORS headers. An opaque response
          // from a file document still proves Chromium reached the station.
          function (r) { give(!!r && (r.status > 0 || (fileDocument && r.type === 'opaque'))); },
          function () { give(false); });
      } catch (err) { give(false); }
    });
  }

  /* #1470: THE OTHER SHAPE OF DEAFNESS. On 2026-09-13 the signature was
   * not a failed fetch at all - it was `musicPlayer net=2 ready=0`, an
   * <audio> stuck LOADING with nothing arriving, for hours, while the
   * bridge and even a probe fetch could still answer. A media element
   * that has been asking for bytes for a whole round and has not got as
   * far as its own metadata is dead, whatever the probe says: metadata is
   * the first few kilobytes, and a station that is merely slow still
   * hands those over in seconds. Counted per element across rounds, so a
   * clip that is simply big and still opening does not count, and an
   * error the engine itself reports as a network fault counts at once.
   * Only elements with a source: an empty player is idle, not deaf. */
  var stuckRounds = (typeof WeakMap === 'function') ? new WeakMap() : null;
  var MEDIA_STUCK_ROUNDS = 2;

  function mediaStuck() {
    var out = {stuck: 0, errors: 0, ids: []};
    var els;
    try { els = document.querySelectorAll('audio, video'); }
    catch (err) { return out; }
    for (var i = 0; i < els.length; i += 1) {
      var el = els[i];
      var src = '';
      try { src = el.currentSrc || el.getAttribute('src') || ''; } catch (err) { src = ''; }
      if (!src) { if (stuckRounds) stuckRounds.delete(el); continue; }
      var err = null;
      try { err = el.error; } catch (e2) { err = null; }
      if (err && (err.code === 2 /* MEDIA_ERR_NETWORK */)) {
        out.errors += 1;
        out.ids.push((el.id || el.tagName.toLowerCase()) + ':err' + err.code);
        continue;
      }
      /* NETWORK_LOADING with nothing decoded yet, round after round. */
      var loading = el.networkState === 2 && el.readyState < 1;
      var previous = stuckRounds ? stuckRounds.get(el) : null;
      var n = loading ? (previous && previous.src === src ? previous.rounds + 1 : 1) : 0;
      // A new cue loading in the same reusable element starts a new observation.
      if (stuckRounds) { if (loading) stuckRounds.set(el, {src: src, rounds: n}); else stuckRounds.delete(el); }
      if (n >= MEDIA_STUCK_ROUNDS) {
        out.stuck += 1;
        out.ids.push((el.id || el.tagName.toLowerCase()) + ':loading×' + n);
      }
    }
    return out;
  }

  function look() {
    if (reviving || looking) return;
    looking = true;
    var mine = generation;
    return Promise.all([viaBridge(), viaWeb()]).then(function (got) {
      if (mine !== generation) return;
      var bridge = got[0].ok;
      var bridgeMs = got[0].ms;
      var web = got[1];
      var media = mediaStuck();
      last = {at: Date.now(), bridge: bridge, bridgeMs: bridgeMs,
              web: web, media: media, say: ''};

      /* The bridge being down too means the station or the network is
         away, which is not this fault and not ours to fix. */
      if (bridge !== true) {
        strikes = 0;
        last.say = 'the bridge is not answering either - not deafness';
        return;
      }
      if (web === null) {
        strikes = 0;
        last.say = 'the desktop has no station URL to compare - not evidence of deafness';
        return;
      }
      var mediaDead = (media.stuck + media.errors) > 0;
      if (web && !mediaDead) {
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
      last.say = (web
        ? 'the bridge answers and the media is dead (' + media.ids.join(', ') + ')'
        : 'the bridge answers and the web does not')
        + ' - strike ' + strikes + ' of ' + STRIKES;
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
          why: web
            ? ('the WebView media is dead: the bridge answers ' + PROBE
               + ' and ' + media.ids.join(', ') + ' never loads')
            : ('the WebView network is dead: the bridge answers ' + PROBE
               + ' and fetch does not')
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
    }, function () { /* a broken round is not evidence of anything */ }).then(function () {
      looking = false;
    }, function () { looking = false; });
  }

  root.PineDeafWatch = {
    start: function () {
      if (timer) return;
      /* Not immediately: a page that has just loaded is still opening
         its own connections, and a probe in that crowd proves nothing. */
      warmup = setTimeout(function () { warmup = null; look(); }, 20000);
      timer = setInterval(look, EVERY_MS);
    },
    stop: function () {
      if (timer) clearInterval(timer);
      if (warmup) clearTimeout(warmup);
      timer = null;
      warmup = null;
      generation += 1;
      strikes = 0;
    },
    /* Numbers the operator can look at rather than a claim in a comment. */
    state: function () {
      return {at: last.at, bridge: last.bridge, bridgeMs: last.bridgeMs,
              web: last.web, media: last.media || null, strikes: strikes,
              say: last.say};
    },
    /* #1470: the media test on its own, for a console or a doctor. */
    media: mediaStuck,
    /* For proving it works without waiting for the fault. */
    look: look
  };

  try { root.PineDeafWatch.start(); } catch (err) { /* no watch, no harm */ }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineDeafWatch;
  }
})(typeof window !== 'undefined' ? window : globalThis);
