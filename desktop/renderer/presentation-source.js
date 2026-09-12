/* window.PinePresentationSource - ONE THROAT for a screen with six panes.
 *
 * THE MEASUREMENT THIS FILE EXISTS FOR. On 2026-09-11, 38 concurrent
 * requests in flight to the station produced a 46-SECOND MEDIA STALL on the
 * tablet - which is why the tablet currently plays no audio at all. The
 * station is a single-process FastAPI app that is also writing and
 * recording a live radio show; a client that asks it six questions at once
 * is not a client that gets six answers faster, it is a client that stops
 * the show.
 *
 * The Presentation view is the worst offender available: playlist,
 * schedule, script, feed, gallery and a video wall, all wanting different
 * routes. Six panes with six timers is exactly the shape that produced the
 * stall.
 *
 * So this file is the whole traffic budget for the view, and it is TWO
 * requests wide, never more:
 *
 *   1. PineStationFeed's /api/dj every 4s, interpolated locally at 250ms.
 *      That cadence is the station's own (app.py:154692: "the round clock
 *      every 250ms, speaking_now every 4s"), it already exists, and this
 *      file does not add a second copy of it - it subscribes.
 *
 *   2. ONE slow request at a time, through ask(), for everything else.
 *
 * ask() is a gate, not a cache with a fetch behind it:
 *   - a value younger than its maxAge is handed back with NO request;
 *   - two panes asking for the same route get the SAME promise;
 *   - anything else queues, and the queue drains one at a time.
 * So however many panes are painting, the station sees at most one of our
 * questions outstanding plus the shared poll. peak() is on the panel for
 * exactly this reason: a number the operator can look at rather than a
 * claim in a comment.
 *
 * NO PANE GETS A TIMER. Panes ask on the beat they are already being
 * painted on, and the age gate turns most of those asks into free reads
 * of memory.
 *
 * ---------------------------------------------------------------------
 * VOTES RIDE THE EXISTING EDITORIAL PATH. There are two, and which one a
 * feed row belongs to is a fact about the row, not a choice:
 *
 *   A CUT line carries `review_id` and `review_seq` (app.py:90046 stamps
 *   them on the row when the tint desk rejects a candidate). Those go to
 *   /api/orchestrator/rejections/{review_id} exactly as the LCD's Accept
 *   wording / Reject wording buttons do (lcd-review.js) - occurrence and
 *   revision checked first, because that store refuses a stale vote and
 *   is right to. That is the path whose decisions "become bounded examples
 *   in future writing/tint prompts" (docs/pine-box-lcd.md:5).
 *
 *   A line that AIRED has no review record to vote on - it was never cut.
 *   Its up/down goes to /api/feedback, the station's own vote store since
 *   #76 ("votes steer future generations", app.py:109942), read back by
 *   read_feedback() at app.py:81048.
 *
 * NO THIRD STORE IS CREATED HERE. A note rides in the field the chosen
 * store already has - `note` on a review decision, `text` on a feedback
 * row - and nothing is written anywhere else.
 */
(function (root) {
  "use strict";

  const REVIEWS = "/api/orchestrator/rejections/";
  const FEEDBACK = "/api/feedback";

  /* How stale an answer may be before a pane's ask actually costs a
   * request. Chosen against how fast each thing can really change: the
   * running order is edited by hand and by the hour; the gallery log
   * grows when a render finishes, and a render on this box measured
   * 84-102s; the library is 35,000 tracks that do not move. */
  const AGES = {
    "/api/schedule/hours": 20000,
    "/api/schedule/segment": 10000,
    "/api/schedule/aired": 10000,
    "/api/generations": 60000,
    "/api/music/browse": 300000
  };
  const DEFAULT_AGE = 30000;

  /* The queue only ever holds one entry per distinct route, and this view
   * asks about five. A ceiling well above that means a runaway caller is
   * refused with a sentence instead of quietly filling memory. */
  const QUEUE_MOST = 12;

  function ageFor(route) {
    const path = String(route || "").split("?")[0];
    return Object.prototype.hasOwnProperty.call(AGES, path) ? AGES[path] : DEFAULT_AGE;
  }

  /* WHICH EDITORIAL DOOR THIS ROW BELONGS TO. Pure, so the decision can
   * be pinned by a test rather than discovered on a live station. */
  function voteRoad(row) {
    const id = String((row && row.review_id) || "").trim();
    const seq = Number((row && row.review_seq) || 0);
    if (id && seq > 0) {
      return { road: "review", review_id: id, review_seq: seq,
        route: REVIEWS + encodeURIComponent(id) };
    }
    return { road: "feedback", route: FEEDBACK };
  }

  /* What a vote MEANS on each road. The review store speaks in wording:
   * `allow` keeps the rejected wording and sends it back through the
   * orchestrator's recovery checks, `keep` keeps the cut. The feedback
   * store speaks in up/down. Neither is a rating of the audio. */
  function voteWord(road, direction) {
    const up = String(direction) === "up";
    if (road === "review") return up ? "allow" : "keep";
    return up ? "up" : "down";
  }

  function create(options) {
    const settings = options || {};
    const get = settings.get;
    const post = settings.post;
    if (typeof get !== "function") throw new Error("The view needs the station's bridge.");
    const subscribe = settings.subscribe;
    const clock = typeof settings.now === "function" ? settings.now : Date.now;

    const cache = new Map();        /* route -> {at, value, error} */
    const pending = new Map();      /* route -> promise */
    const queue = [];
    let running = false;
    let inFlight = 0;
    let peak = 0;
    let asked = 0;
    let leave = null;
    const listeners = new Set();

    const at = () => {
      const value = Number(clock());
      return Number.isFinite(value) ? value : Date.now();
    };

    /* The gate itself. Everything that touches the network - reads and
     * writes both - goes through here, so the ceiling is real rather
     * than a convention the next pane can forget. */
    function run(work) {
      return new Promise((resolve, reject) => {
        if (queue.length >= QUEUE_MOST) {
          reject(new Error("Too many station questions are already waiting; "
            + "this one was dropped rather than piled on."));
          return;
        }
        queue.push({ work, resolve, reject });
        drain();
      });
    }

    function drain() {
      if (running || !queue.length) return;
      const job = queue.shift();
      running = true;
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      asked += 1;
      Promise.resolve()
        .then(() => job.work())
        .then(job.resolve, job.reject)
        .finally(() => {
          running = false;
          inFlight -= 1;
          drain();
        });
    }

    function ask(route, opts) {
      const key = String(route || "");
      const maxAge = Number((opts || {}).maxAge);
      const limit = Number.isFinite(maxAge) ? maxAge : ageFor(key);
      const held = cache.get(key);
      if (held && !(opts || {}).force && at() - held.at < limit) {
        return Promise.resolve(held.value);
      }
      /* Two panes asking the same question ask it once. This is the whole
       * reason the gallery and the video wall can both read
       * /api/generations?limit=1000 without it being two reads of a log
       * that is measured in hundreds of records. */
      if (pending.has(key)) return pending.get(key);
      const trip = run(() => get(key))
        .then((value) => {
          cache.set(key, { at: at(), value, error: "" });
          return value;
        })
        .catch((reason) => {
          const why = String((reason && reason.message) || reason);
          /* A failure does NOT wipe what we had. A station that is busy
           * for four seconds should not blank six panes. */
          const previous = cache.get(key);
          cache.set(key, {
            at: at(),
            value: previous ? previous.value : null,
            error: why
          });
          throw reason;
        })
        .finally(() => { pending.delete(key); });
      pending.set(key, trip);
      return trip;
    }

    /* What a pane can paint RIGHT NOW without waiting on anything. */
    function held(route) {
      const row = cache.get(String(route || ""));
      return row ? row.value : null;
    }

    function trouble(route) {
      const row = cache.get(String(route || ""));
      return row ? row.error : "";
    }

    /* THE VOTE. Both roads, and no third one. */
    async function vote(row, direction, note) {
      if (typeof post !== "function") {
        throw new Error("This build cannot write to the station.");
      }
      const road = voteRoad(row);
      const word = voteWord(road.road, direction);
      const said = String((row && row.text) || "").slice(0, 300);

      if (road.road === "feedback") {
        const text = note
          ? said + "  -- " + String(note).slice(0, 200)
          : said;
        const stored = await run(() => post(FEEDBACK, { vote: word, text: text.slice(0, 400) }));
        return { ok: true, road: "feedback", route: FEEDBACK, action: word,
          why: word === "up"
            ? "Filed as an up-vote; votes steer future generations."
            : "Filed as a down-vote; votes steer future generations.",
          stored };
      }

      /* The review store refuses a vote that has gone stale, and it is
       * right to: a newer occurrence of the same cut is a different piece
       * of evidence. Read it first and carry its revision, exactly as
       * lcd-review.js does - this is the same door, not a copy of it. */
      const record = await run(() => get(road.route
        + "?event_seq=" + encodeURIComponent(road.review_seq)));
      if (!record || String(record.id || "") !== road.review_id) {
        throw new Error("The station answered about a different cut.");
      }
      const seq = record.event_seq == null ? record.review_seq : record.event_seq;
      if (seq == null || Number(seq) !== Number(road.review_seq)) {
        throw new Error("This cut changed. Reopen the row before deciding.");
      }
      if (record.revision == null || !Number.isInteger(Number(record.revision))) {
        throw new Error("This cut has no current review revision.");
      }
      if (record.occurrence_current === false || record.read_only) {
        throw new Error("A newer occurrence exists; this evidence is read-only.");
      }
      const result = await run(() => post(road.route, {
        action: word,
        expected_revision: Number(record.revision),
        expected_event_seq: Number(road.review_seq),
        note: note ? String(note).slice(0, 200) : "Presentation feed"
      }));
      if (result && result.ok === false) {
        throw new Error(String(result.error || result.detail
          || "The decision was not confirmed."));
      }
      return { ok: true, road: "review", route: road.route, action: word,
        why: (result && result.effect && result.effect.say)
          || (word === "allow"
            ? "Wording accepted; recovery will check its recording."
            : "Wording stays rejected."),
        stored: result };
    }

    const moaned = new Set();

    /* A bad pane still never stops the beat, but it says so once. Silence
     * here is what made five empty panes look like an empty station. */
    function emit(payload) {
      for (const fn of [...listeners]) {
        try {
          fn(payload);
        } catch (err) {
          const why = String((err && err.message) || err);
          if (moaned.has(why)) continue;
          moaned.add(why);
          try { console.error("[presentation] a pane threw: " + why, err); } catch (e) {}
        }
      }
    }

    return {
      /* Subscribes to the SHARED station feed. The view has no poller of
       * its own and this does not start one. */
      start() {
        if (leave || typeof subscribe !== "function") return;
        leave = subscribe((payload) => emit(payload));
      },
      stop() {
        if (leave) { try { leave(); } catch (err) {} }
        leave = null;
      },
      on(fn) {
        if (typeof fn !== "function") return () => {};
        listeners.add(fn);
        return () => listeners.delete(fn);
      },
      ask,
      held,
      trouble,
      vote,
      voteRoad,
      /* Used after a write that changes what a read would say, so the
       * next ask() is a real question rather than a stale answer. */
      forget(route) { cache.delete(String(route || "")); },
      /* The traffic budget, visible. */
      inFlight() { return inFlight; },
      waiting() { return queue.length; },
      peak() { return peak; },
      asked() { return asked; },
      listeners() { return listeners.size; }
    };
  }

  const api = { create, voteRoad, voteWord, ageFor, AGES, QUEUE_MOST };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PinePresentationSource = api;
})(typeof window !== "undefined" ? window : globalThis);
