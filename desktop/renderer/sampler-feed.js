/* window.PineStationFeed - ONE poller for the station, shared by everything.
 *
 * The station's own comment (app.py:154692) sets the contract: "the round
 * clock every 250ms, speaking_now every 4s." So: /api/dj is fetched every
 * four seconds and the playhead INSIDE the current round is worked out
 * locally at 250ms from stream_now. Polling at 250ms would be four times
 * the traffic for the same answer, and this station has a documented
 * history of being starved by chatty clients.
 *
 * Any number of panels may subscribe. There is still exactly one interval
 * pair, and when the last subscriber leaves both stop. That is the whole
 * reason this module exists rather than each view calling api.get itself.
 */
(function (root) {
  "use strict";

  const POLL_MS = 4000;
  const TICK_MS = 250;

  const listeners = new Set();
  let pollTimer = null;
  let tickTimer = null;
  let station = null;
  let rows = [];
  let inFlight = false;

  /* server_ms lets us cancel the network trip and any clock drift between
   * this machine and the box. Without it a round's playhead is wrong by
   * however far apart the two clocks have wandered. */
  let skew = 0;

  function clock() { return Date.now() + skew; }

  function api() { return root.pineDesktop; }

  function computeRows() {
    const dialogue = root.PineLcdDialogue;
    if (!dialogue || !station) return [];
    try { return dialogue.stationRows(station, clock()); }
    catch (err) { return []; }
  }

  /* Which row is sounding right now, worked out locally between polls. */
  function speakingNow() {
    if (!station) return null;
    const stream = station.stream_now;
    if (stream && stream.at) {
      const offset = (clock() / 1000) - Number(stream.at);
      if (offset >= 0 && offset <= Number(stream.length || 0) + 4) {
        for (const row of stream.rows || []) {
          if (Number(row.from) <= offset && offset < Number(row.until)) return row;
        }
      }
    }
    return station.speaking_now || null;
  }

  /* A BAD SUBSCRIBER STILL NEVER STOPS THE FEED - BUT IT IS NO LONGER
   * SILENT. Six views hang off this one poll, and each of them paints
   * several panes from a single subscriber function. A throw part-way
   * through one of those subscribers leaves every pane after it unpainted,
   * so the cost of swallowing quietly is not one pane - it is the whole
   * lower half of a view, blank, with nothing anywhere to say why. */
  const moaned = new Set();

  function said(err) {
    const why = String((err && err.message) || err);
    if (moaned.has(why)) return;
    moaned.add(why);
    try { console.error("[station-feed] a subscriber threw: " + why, err); } catch (e) {}
  }

  function emit(kind, error) {
    const payload = { kind, station, rows, now: speakingNow(), at: clock(),
      error: error ? String((error && error.message) || error) : "" };
    for (const fn of [...listeners]) {
      try { fn(payload); } catch (err) { said(err); }
    }
  }

  async function poll() {
    if (inFlight || !api()) return;
    inFlight = true;
    try {
      /* No lean=1: it drops stream_now entirely and cuts chat to 20 rows,
       * so the playhead and the scrollback both go with it. */
      const got = await api().get("/api/dj");
      if (got && typeof got === "object") {
        if (Number(got.server_ms)) skew = Number(got.server_ms) - Date.now();
        station = got;
        rows = computeRows();
        emit("poll");
      }
    } catch (err) {
      emit("error", err);
    } finally {
      inFlight = false;
    }
  }

  function tick() {
    if (!station) return;
    rows = computeRows();
    emit("tick");
  }

  /* [#1386] THE TABLET SUSPENDS TIMERS AND KEEPS rAF.
   *
   * "I dont know why videos pop up on the pine tab and sit there not
   * playing frozen. why arent they closing and leaving the screen like
   * normal?"
   *
   * Because the thing that would close them is a setInterval. The PineTab's
   * WebView suspends JS timers while requestAnimationFrame keeps firing at
   * vsync, so both timers below stop together - and with the 250ms tick go
   * every consumer that hangs off it, including video-wall.js's MAX_CLIP_MS
   * backstop, the one thing that takes a clip off the wall when its own
   * `ended` never arrives. The wall is not stuck; it is never asked.
   *
   * So rAF paces them. It does NOT replace the intervals - on the desktop
   * they fire perfectly well and this sees no gap and does nothing. It only
   * notices that wall-clock time has passed without the beat arriving, and
   * runs it. Every decision is made from a fresh Date.now(), never a frame
   * count, because the frame rate on that glass is whatever it is (it tops
   * out at 12fps) and counting frames would drift.
   */
  let rafId = null;
  let lastTick = 0;
  let lastPoll = 0;

  function pace() {
    rafId = null;
    if (!pollTimer) return;            /* stopped */
    const now = Date.now();
    /* Generous margins: this is a backstop for a suspended timer, not a
     * second scheduler. A beat that is merely late is left alone. */
    if (now - lastTick >= TICK_MS * 4) {
      lastTick = now;
      try { tick(); } catch (err) { said(err); }
    }
    if (now - lastPoll >= POLL_MS * 2) {
      lastPoll = now;
      try { poll(); } catch (err) { said(err); }
    }
    arm();
  }

  function arm() {
    if (rafId !== null || !pollTimer) return;
    if (typeof root.requestAnimationFrame !== "function") return;
    try { rafId = root.requestAnimationFrame(pace); }
    catch (err) { rafId = null; }
  }

  function start() {
    if (pollTimer) return;
    lastTick = lastPoll = Date.now();
    poll();
    pollTimer = setInterval(() => { lastPoll = Date.now(); poll(); }, POLL_MS);
    tickTimer = setInterval(() => { lastTick = Date.now(); tick(); }, TICK_MS);
    arm();
  }

  function stop() {
    if (pollTimer) clearInterval(pollTimer);
    if (tickTimer) clearInterval(tickTimer);
    pollTimer = tickTimer = null;
    if (rafId !== null && typeof root.cancelAnimationFrame === "function") {
      try { root.cancelAnimationFrame(rafId); } catch (err) { /* gone */ }
    }
    rafId = null;
  }

  /* A mounted view remains in the document after the operator changes tabs.
   * Keeping its subscription is useful - it must not start another poll when
   * the tab comes back - but repainting a hidden screenplay, sampler and
   * presentation wall four times a second is pure main-thread work. Hold the
   * newest beat while the host is hidden, then deliver exactly that beat as
   * soon as the host becomes visible again. The ordinary subscribe() remains
   * available for hardware producers and overlays which really do work while
   * their panel is closed. */
  function hostIsActive(host) {
    if (!host) return true;
    const doc = root.document;
    if (doc && doc.hidden) return false;
    if (host.hidden) return false;
    if (host.classList && (host.classList.contains("active")
        || host.classList.contains("open"))) return true;
    /* offsetParent is the final authority for the desktop's display:none
     * views. It is absent in small DOM shims, where the class test above is
     * the only useful signal. */
    return typeof host.offsetParent !== "undefined" && host.offsetParent !== null;
  }

  function subscribeView(host, fn) {
    if (typeof fn !== "function") return () => {};
    let latest = null;
    let delivered = null;
    let observer = null;
    let gone = false;

    function deliver(payload) {
      latest = payload;
      if (gone || !hostIsActive(host)) return;
      delivered = payload;
      try { fn(payload); } catch (err) { said(err); }
    }

    function wake() {
      if (!latest || latest === delivered || !hostIsActive(host)) return;
      delivered = latest;
      try { fn(latest); } catch (err) { said(err); }
    }

    const leave = root.PineStationFeed.subscribe(deliver);
    const doc = root.document;
    if (doc && typeof doc.addEventListener === "function") {
      doc.addEventListener("visibilitychange", wake);
    }
    if (host && typeof root.MutationObserver === "function") {
      observer = new root.MutationObserver(wake);
      try { observer.observe(host, { attributes: true, attributeFilter: ["class", "hidden"] }); }
      catch (err) { observer = null; }
    }
    return () => {
      gone = true;
      leave();
      if (observer) observer.disconnect();
      if (doc && typeof doc.removeEventListener === "function") {
        doc.removeEventListener("visibilitychange", wake);
      }
    };
  }

  root.PineStationFeed = {
    subscribe(fn) {
      if (typeof fn !== "function") return () => {};
      listeners.add(fn);
      start();
      /* A late subscriber gets the current picture immediately rather than
       * staring at nothing for up to four seconds. */
      if (station) {
        try { fn({ kind: "join", station, rows, now: speakingNow(), at: clock() }); }
        catch (err) { said(err); }
      }
      return () => {
        listeners.delete(fn);
        if (!listeners.size) stop();
      };
    },
    subscribeView,
    refresh: poll,
    state() { return station; },
    rows() { return rows; },
    now() { return speakingNow(); },
    clock,
    subscribers() { return listeners.size; }
  };
})(typeof window !== "undefined" ? window : globalThis);
