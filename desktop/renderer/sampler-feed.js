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

  function emit(kind) {
    const payload = { kind, station, rows, now: speakingNow(), at: clock() };
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
      emit("error");
    } finally {
      inFlight = false;
    }
  }

  function tick() {
    if (!station) return;
    rows = computeRows();
    emit("tick");
  }

  function start() {
    if (pollTimer) return;
    poll();
    pollTimer = setInterval(poll, POLL_MS);
    tickTimer = setInterval(tick, TICK_MS);
  }

  function stop() {
    if (pollTimer) clearInterval(pollTimer);
    if (tickTimer) clearInterval(tickTimer);
    pollTimer = tickTimer = null;
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
    refresh: poll,
    state() { return station; },
    rows() { return rows; },
    now() { return speakingNow(); },
    clock,
    subscribers() { return listeners.size; }
  };
})(typeof window !== "undefined" ? window : globalThis);
