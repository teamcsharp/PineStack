/* Music - the station from the record library's side.
 *
 * Listen is the radio on the shelf. This is the crate beside it: what is
 * turning, what is queued, what has just been played, what the library
 * can be asked for, and what the running order intends to do with the
 * next hour. Same feed, same model, different arrangement - which is the
 * whole reason listen-model.js exists as its own file.
 *
 * THE SPEC FOR THIS VIEW WAS A DRAFT TOO. The plan gives one sentence:
 * "Music adds playlist, schedule, requests and the shelf", flagged
 * "inferred, not specified". Here is how each was read, so the operator
 * can push back on the reading rather than on the code:
 *
 *  1. PLAYLIST IS FREE, AND IT IS TWO LISTS. /api/dj already carries
 *     `upcoming` - the next twenty queued and requested tracks
 *     (app.py:25283) - and `played`, the last ten records newest-first
 *     (app.py:25368). Neither costs a request. So "playlist" is drawn as
 *     what is coming and what has just gone, off the feed this app is
 *     already subscribed to. /api/music/played would give sixty rows with
 *     vote state; ten is enough for a screen and the sixty are not worth
 *     a poll.
 *
 *  2. REORDER IS NOT OFFERED. The plan marks the music-queue reorder
 *     route as unconfirmed, and it is: /api/schedule/segment/priority and
 *     /pin move SEGMENTS, not records. Rather than fake a drag that
 *     silently does nothing, the queue is shown read-only and the thing
 *     that DOES move a record - asking for it - is a button.
 *
 *  3. REQUESTING NEVER CUTS THE RECORD. POST /api/dj/request takes
 *     {q, now}; `now` inserts at the head and calls dj_skip(), which cuts
 *     the song currently playing short. That is precisely the complaint
 *     behind #840 - "stop having the DJs change the track in the middle
 *     of the track" - so this view never sends it. Every request queues,
 *     and the pair acknowledge it on air, which is what dj_request does
 *     anyway (app.py, dj_request: "Queue it or cut to it, and have the DJ
 *     acknowledge either way").
 *
 *  4. THE SHELF IS A HANDFUL, AND SAYS SO. /api/music/browse
 *     (app.py:93073) is not a catalogue listing - 35,982 tracks are too
 *     many to list, so it returns a stable random sample seeded by the
 *     HOUR. Press for another and a fresh seed goes with it; without one
 *     the same handful comes back all hour, which would read as a broken
 *     refresh. The total is printed beside it so "the shelf" is never
 *     mistaken for the library.
 *
 *  5. THE SCHEDULE IS SHOWN, NOT EDITED. The hour sheet is a real
 *     instrument with pins, priorities, presets and per-entry prompts,
 *     and it already has a home in the Agent panel and in System2.
 *     Duplicating it here would be a second opinion about the running
 *     order; what this view needs is the answer to "what is on now and
 *     what is after it", which /api/schedule/hours gives directly. `past`
 *     and `state` are taken exactly as served - #963 is the record of
 *     what happens when a client recomputes "has this aired" from the
 *     wall clock instead of from the booth's own position.
 *
 *  6. EVERY RECORD OPENS. "Be able to tap on every song in the queue and
 *     be able to expand it and see the dialogue generated for it, see the
 *     analysis that's done for it, see what online research has been done
 *     for it, see what we've queued up for the host to say about this
 *     particular track." Tapping any row in the queue, the just-played or
 *     the shelf expands it in place. The five stores behind that panel,
 *     what each really holds and which two of them are expensive enough
 *     to need the operator's own press, are documented at length in
 *     listen-model.js under THE TRACK DETAIL - read that before changing
 *     anything here, because three of the obvious guesses about where
 *     this data lives turned out to be wrong.
 *
 *     THE TAP NO LONGER ASKS FOR THE RECORD. It used to: a tap on the
 *     shelf or on a just-played row fired /api/dj/request, which runs a
 *     library search AND a live render so the pair can acknowledge it. A
 *     gesture that expensive should not be the one a finger makes by
 *     accident while reading, so asking is now a button INSIDE the open
 *     panel and the tap only opens.
 *
 * THE SINGLE-POLLER RULE. Measured 2026-09-11: 38 concurrent requests in
 * flight to the station caused a 46-second media stall on the tablet.
 * This view adds NO poller. Everything live comes from
 * window.PineStationFeed (one /api/dj every 4 s, local 250 ms tick - the
 * station's own cadence, app.py:154692). The three things not on that
 * payload - the shelf, the running order and the request book - are
 * fetched ONCE at mount, IN SERIES rather than in parallel, and after
 * that only when the operator presses their own control. A view that
 * opens with a fan-out is how a terminal becomes part of the problem.
 *
 * AND THE DETAIL OBEYS THE SAME RULE, WHICH IS WHY IT IS SHAPED THE WAY
 * IT IS. There is no per-row fetch loop and no per-row timer. Three
 * whole-library reads happen ONCE, on the first tap, IN SERIES - the
 * SongSight crystals, the track-read library and the play history - and
 * every row afterwards is a lookup in a map. Only ONE call is per record,
 * /api/music/track/{id} at a measured 824 bytes, and it is cached by id
 * for the life of the session. A design that fetched five things per row
 * would have put thirty-odd requests in flight the first time somebody
 * scrolled the queue, which is the exact number that stalled the tablet.
 */
(function (root) {
  "use strict";

  const api = () => root.pineDesktop;
  const model = () => root.PineListenModel;

  /* nothing here needs an absolute URL: every call goes through the
   * bridge, which already knows the base and carries the bearer. */
  let mounted = false;
  let unsubscribe = null;
  let busy = false;

  let shelf = [];
  let shelfCount = 0;
  let orders = [];
  let book = [];

  const el = (id) => document.getElementById(id);

  function put(id, text) {
    const node = el(id);
    if (!node) return;
    const value = text == null ? "" : String(text);
    if (node.textContent !== value) node.textContent = value;
  }

  function note(text, bad) {
    const node = el("muNote");
    if (!node) return;
    node.textContent = text || "";
    node.classList.toggle("bad", !!bad);
  }

  /* --------------------------------------------------------- the fetches */

  /* Every route here is open to reads (require_read_auth is a no-op
   * unless SPARK_AGENT_LOCK_READS is set, app.py:1632) and the bridge
   * sends the bearer regardless, which is the discipline the sampler
   * follows for the same reason: the day someone locks reads, this should
   * keep working rather than become the first thing to break. */

  async function loadShelf(fresh) {
    try {
      /* A new seed or the same handful all hour - see the header. */
      const seed = fresh ? Math.floor(Math.random() * 1e9) : 0;
      const got = await api().get("/api/music/browse?limit=24&seed=" + seed);
      shelf = model().shelfRows(got);
      shelfCount = model().shelfTotal(got);
      paintShelf();
    } catch (err) {
      note("the library would not answer", true);
    }
  }

  async function loadOrder() {
    try {
      /* Two hours: the one on air and the one after it. Six is the
       * route's default and four of them would be a screenful of an
       * evening nobody is looking at yet. */
      const got = await api().get("/api/schedule/hours?count=2");
      orders = model().scheduleRows(got, 24);
      paintOrder();
    } catch (err) {
      note("the running order would not answer", true);
    }
  }

  async function loadBook() {
    try {
      const got = await api().get("/api/dj/requested");
      book = model().requestRows(got);
      paintBook();
    } catch (err) {
      note("the request book would not answer", true);
    }
  }

  /* ---------------------------------------------- what the station knows */

  /* THE LIBRARY SIDE OF THE DETAIL: three reads, once, for every record on
   * screen and every record that will be. None of them is per row.
   *
   *   /api/song-crystals   22 crystals, 31 kB, ~2 s (app.py:93391)
   *   /api/track-reads     300 of 558 reads, 112 kB, ~0.8 s (app.py:99955)
   *   /api/music/played    200 spins with votes, ~59 kB (app.py:103559)
   *
   * Measured sizes and times, 2026-09-11. They are read IN SERIES for the
   * same reason mount's three are, and behind a single-flight promise so
   * that four fast taps on four rows cannot become twelve requests. */
  const HISTORY_WINDOW = 200;
  let libraryState = "cold";          /* cold | loading | ready | bad */
  let libraryWait = null;
  let crystals = {};
  let crystalsBuilt = 0;
  let reads = {};
  let readsHeld = 0;
  let readsServed = 0;
  let history = {};

  /* Per record, and nothing else is. Cached by id for the session: a
   * record's tag sheet does not change while the show is on. */
  const meta = new Map();             /* id -> payload | "bad" */
  const research = new Map();         /* id -> payload | "bad" */

  /* The writers' board. `undefined` until the operator presses for it -
   * see listen-model.js: the only route that carries it measured 773,386
   * bytes, so it is never opened by a tap. */
  let board = null;                   /* null = never read */
  let boardAhead = 0;
  let boardBusy = false;

  function libraryNote() {
    if (libraryState === "loading") return "reading what the station knows…";
    if (libraryState === "bad") return "the station would not say what it knows";
    if (libraryState !== "ready") return "";
    return crystalsBuilt + " analysed · " + readsHeld + " with a read"
      + (board ? " · board read" : "");
  }

  async function ensureLibrary() {
    if (libraryState === "ready") return;
    if (libraryWait) return libraryWait;
    libraryState = "loading";
    put("muLibNote", libraryNote());
    libraryWait = (async () => {
      try {
        const gotCrystals = await api().get("/api/song-crystals");
        crystals = model().crystalIndex(gotCrystals);
        crystalsBuilt = Math.max(0, Number((gotCrystals || {}).count || 0));

        const gotReads = await api().get("/api/track-reads");
        reads = model().readsIndex(gotReads);
        readsHeld = Math.max(0, Number((gotReads || {}).held || 0));
        readsServed = Object.keys(reads).length;

        const gotPlayed = await api().get(
          "/api/music/played?limit=" + HISTORY_WINDOW);
        history = model().playedIndex(gotPlayed);
        libraryState = "ready";
      } catch (err) {
        libraryState = "bad";
      } finally {
        libraryWait = null;
        put("muLibNote", libraryNote());
      }
    })();
    return libraryWait;
  }

  async function ensureMeta(id) {
    if (!id || meta.has(id)) return;
    try {
      meta.set(id, await api().get("/api/music/track/" + encodeURIComponent(id)));
    } catch (err) {
      meta.set(id, "bad");
    }
  }

  /* THE TWO EXPENSIVE DOORS, BOTH BEHIND A PRESS.
   *
   * The board is one read for the whole lookahead, so it is pressed once
   * and every queued record gains its prepared talk at the same moment.
   * The research door is per record AND is not a read at all on a record
   * the station has never looked up: track_notes (app.py:54703) runs the
   * web search and the model call there and then. Neither belongs on a
   * tap; both say what they cost on the button itself. */
  async function loadBoard() {
    if (boardBusy) return;
    boardBusy = true;
    note("reading the writers' board - one 773 kB read for every record…");
    try {
      const got = await api().get("/api/dj/pending");
      board = model().lookaheadIndex(got);
      boardAhead = Math.max(0, Number(
        ((got || {}).lookahead || {}).ahead || 0));
      const written = Object.keys(board).filter((id) => {
        const row = board[id];
        return String(row.intro_text || "") || String(row.outro_text || "");
      }).length;
      note("the writers' board: " + Object.keys(board).length
        + " records in the lookahead, " + written + " with words written");
      put("muLibNote", libraryNote());
      repaintOpen();
    } catch (err) {
      note("the writers' board would not answer", true);
    } finally {
      boardBusy = false;
    }
  }

  async function loadResearch(id) {
    if (!id || research.has(id)) return;
    note("asking the station what it found out about this record…");
    try {
      research.set(id, await api().get(
        "/api/music/notes/" + encodeURIComponent(id)));
      note("");
    } catch (err) {
      research.set(id, "bad");
      note("the research door would not answer", true);
    }
    repaintOpen();
  }

  /* ------------------------------------------------------------ the asks */

  /* One at a time, and the button says so while it waits. dj_request
   * runs a library search AND has the DJ acknowledge the request out
   * loud, which means a render - it is not a fast call, and firing three
   * of them because a finger bounced is exactly the traffic this view is
   * supposed to be careful about. */
  async function ask(query) {
    const wanted = String(query || "").trim();
    if (!wanted) { note("Name a song.", true); return; }
    if (busy) { note("still asking for the last one…"); return; }
    busy = true;
    note("asking for " + wanted + "…");
    try {
      const got = await api().post("/api/dj/request", {q: wanted});
      if (got && got.ok) {
        note("Queued: " + (got.title || wanted)
          + (got.artist ? " - " + got.artist : "")
          + (got.times_asked > 1 ? " (asked " + got.times_asked + " times)" : ""));
        /* The book changed because we changed it, so this refresh is
         * caused by the operator rather than by a clock. */
        loadBook();
      } else {
        note((got && (got.detail || got.error))
          || "the station did not take that request", true);
      }
    } catch (err) {
      note("the request did not reach the station: "
        + ((err && err.message) || err), true);
    } finally {
      busy = false;
    }
  }

  /* --------------------------------------------------------- the painting */

  function row(className, main, sub, tail) {
    const node = document.createElement("div");
    node.className = className;
    const b = document.createElement("b");
    b.textContent = main || "";
    node.appendChild(b);
    if (sub) {
      const em = document.createElement("em");
      em.textContent = sub;
      node.appendChild(em);
    }
    if (tail) {
      const i = document.createElement("i");
      i.textContent = tail;
      node.appendChild(i);
    }
    return node;
  }

  /* ------------------------------------------------------ the open record */

  /* ONE ROW OPEN AT A TIME, and that is a memory decision as much as a
   * layout one. This view is mounted on the same tablet Listen is, and a
   * panel per row would hold twenty detail trees against a queue that
   * rebuilds itself whenever the station moves on. One open row also means
   * one record's fetches can ever be in flight. */
  let openId = "";
  let openTrack = null;

  function detailHost(id) {
    /* Found by walking rather than by id, because the same record can be
     * in the queue AND in the shelf at once and two elements may not share
     * an id. The open one is whichever list actually holds it. */
    const hosts = document.querySelectorAll(".mu-item.open .mu-detail");
    for (const host of hosts) {
      if (host.dataset.id === String(id)) return host;
    }
    return null;
  }

  function repaintOpen() {
    if (!openId) return;
    const host = detailHost(openId);
    if (host) paintDetail(host, openId, openTrack);
  }

  async function toggle(track, item) {
    const id = String((track || {}).id || "");
    if (!id) return;
    /* A second tap on the open row closes it. */
    if (openId === id) { closeOpen(); return; }
    closeOpen();
    openId = id;
    openTrack = track;
    item.classList.add("open");
    const host = item.querySelector(".mu-detail");
    if (host) {
      host.hidden = false;
      paintDetail(host, id, track);
    }
    /* IN SERIES, and the library first: until it has answered, a "no
     * analysis" or "nothing written" would be a guess rather than a fact,
     * so paintDetail draws a waiting line instead of drawing five empty
     * sections that are not true yet. */
    await ensureLibrary();
    repaintOpen();
    await ensureMeta(id);
    repaintOpen();
  }

  function closeOpen() {
    if (!openId) return;
    for (const item of document.querySelectorAll(".mu-item.open")) {
      item.classList.remove("open");
      const host = item.querySelector(".mu-detail");
      if (host) { host.hidden = true; host.replaceChildren(); }
    }
    openId = "";
    openTrack = null;
  }

  function line(label, text, tail) {
    const node = document.createElement("div");
    node.className = "mu-line";
    const span = document.createElement("span");
    span.textContent = label || "";
    node.appendChild(span);
    const p = document.createElement("p");
    p.textContent = text || "";
    node.appendChild(p);
    if (tail) {
      const i = document.createElement("i");
      i.textContent = tail;
      node.appendChild(i);
    }
    return node;
  }

  function fact(label, value) {
    const node = document.createElement("div");
    node.className = "mu-fact";
    const span = document.createElement("span");
    span.textContent = label || "";
    node.appendChild(span);
    const i = document.createElement("i");
    i.textContent = value || "";
    node.appendChild(i);
    return node;
  }

  function press(label, title, onClick) {
    const button = document.createElement("button");
    button.className = "mu-btn small";
    button.textContent = label;
    button.title = title;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      onClick();
    });
    return button;
  }

  function sectionNode(section, id) {
    const box = document.createElement("div");
    box.className = "mu-sec";
    const head = document.createElement("b");
    head.textContent = section.title;
    box.appendChild(head);

    for (const row of (section.facts || [])) {
      box.appendChild(fact(row.label, row.value));
    }
    for (const row of (section.lines || [])) {
      box.appendChild(line(row.label, row.text, row.tail));
    }
    /* THE WHOLE POINT OF THIS BRANCH. An empty box cannot be told from a
     * broken one, so a section with nothing behind it says so in a
     * sentence and a section nobody has paid for says what it would cost. */
    if (section.empty || section.pending) {
      const p = document.createElement("p");
      p.className = section.pending ? "mu-empty pending" : "mu-empty";
      p.textContent = section.empty || section.pending;
      box.appendChild(p);
    }
    if (section.pending && section.key === "prepared") {
      box.appendChild(press("read the writers' board",
        "One read of /api/dj/pending - 773 kB measured - which fills this "
        + "section for every record in the lookahead at once. It is never "
        + "fetched by a tap and never polled.",
        () => loadBoard()));
    }
    if (section.pending && section.key === "research") {
      box.appendChild(press("look this one up",
        "The only route to the research cache returns the note alone, and "
        + "on a record the station has never looked up it runs a live web "
        + "search and a model call before it answers. That is why this is "
        + "a press and not a tap.",
        () => loadResearch(id)));
    }
    if (section.note) {
      const fine = document.createElement("p");
      fine.className = "mu-fine";
      fine.textContent = section.note;
      box.appendChild(fine);
    }
    return box;
  }

  function paintDetail(host, id, track) {
    host.dataset.id = String(id);
    const frame = document.createDocumentFragment();

    if (libraryState !== "ready") {
      const p = document.createElement("p");
      p.className = "mu-empty";
      p.textContent = libraryState === "bad"
        ? "the station would not say what it knows about its records"
        : "reading what the station knows about its records…";
      frame.appendChild(p);
      host.replaceChildren(frame);
      return;
    }

    const got = meta.get(id);
    const found = research.get(id);
    const detail = model().trackDetail({
      id,
      meta: got === undefined ? undefined : (got === "bad" ? null : got),
      crystal: crystals[id] || null,
      crystalsBuilt,
      libraryTotal: shelfCount,
      read: reads[id] || null,
      readsHeld, readsServed,
      board: board === null ? undefined : (board[id] || null),
      boardAhead,
      history: history[id] || null,
      historyWindow: HISTORY_WINDOW,
      research: found === undefined ? undefined
        : (found === "bad" ? null : found),
      at: Date.now()
    });

    for (const section of detail.sections) {
      frame.appendChild(sectionNode(section, id));
    }

    /* Asking lives HERE rather than on the row - see the header. The queue
     * is spared it: a record already coming does not need asking for. */
    if (track && track.title) {
      const feet = document.createElement("div");
      feet.className = "mu-feet";
      feet.appendChild(press("ask for this",
        "Queues it and the pair acknowledge it on air. It never cuts the "
        + "record that is playing (#840).",
        () => ask([track.title, track.artist].filter(Boolean).join(" "))));
      frame.appendChild(feet);
    }

    host.replaceChildren(frame);
  }

  /* An expandable record: the row as it always looked, plus a panel under
   * it that is empty until it is opened. */
  function item(track, className, tail) {
    const node = document.createElement("div");
    node.className = "mu-item";
    const head = row("mu-row take " + (className || ""), track.title,
      [track.artist, track.album].filter(Boolean).join(" · "), tail || "");
    head.title = "Tap to see everything the station knows and has prepared "
      + "about this record";
    node.appendChild(head);
    const host = document.createElement("div");
    host.className = "mu-detail";
    host.hidden = true;
    host.dataset.id = String(track.id || "");
    node.appendChild(host);
    head.addEventListener("click", () => toggle(track, node));
    if (openId && String(track.id || "") === openId) {
      node.classList.add("open");
      host.hidden = false;
      openTrack = track;
      paintDetail(host, openId, track);
    }
    return node;
  }

  function paintShelf() {
    const list = el("muShelf");
    if (!list) return;
    const frame = document.createDocumentFragment();
    for (const track of shelf) {
      frame.appendChild(item(track, "",
        track.seconds ? model().clockText(track.seconds) : ""));
    }
    list.replaceChildren(frame);
    put("muShelfCount", shelfCount
      ? shelf.length + " of " + shelfCount.toLocaleString() + " in the library"
      : "");
  }

  function paintOrder() {
    const list = el("muOrder");
    if (!list) return;
    const frame = document.createDocumentFragment();
    for (const entry of orders) {
      const node = row("mu-row order" + (entry.live ? " live" : "")
        + (entry.past ? " past" : "") + (entry.enabled ? "" : " off"),
        entry.label, entry.kind,
        (entry.at || "") + (entry.minutes ? " · " + entry.minutes + "m" : ""));
      node.title = entry.live ? "on air now"
        : entry.past ? "the booth has gone past this"
        : entry.enabled ? "coming" : "disabled - it costs the hour nothing";
      frame.appendChild(node);
    }
    list.replaceChildren(frame);
    put("muOrderHead", orders.length
      ? orders.length + (orders.length === 1 ? " entry" : " entries")
      : "no running order");
  }

  function paintBook() {
    const list = el("muBook");
    if (!list) return;
    const frame = document.createDocumentFragment();
    for (const entry of book.slice(0, 20)) {
      const node = row("mu-row take", entry.title, entry.artist,
        entry.count > 1 ? "×" + entry.count : "");
      node.title = "Ask for it again";
      node.addEventListener("click", () => ask(
        [entry.title, entry.artist].filter(Boolean).join(" ")));
      frame.appendChild(node);
    }
    list.replaceChildren(frame);
  }

  /* The live half. Called on every feed payload - four times a second -
   * so the two lists are rebuilt only when their contents actually
   * change, the same fingerprint trick the sampler's feed uses. Rebuilding
   * a list under a finger is how a tap lands on the wrong row - and since
   * #1166 it is also how an open record would slam shut while it was being
   * read, which is why item() reopens whatever openId still names. */
  let queuePrint = "";
  let playedPrint = "";

  function paint(payload) {
    const state = payload.station || {};
    const at = payload.at || Date.now();
    const m = model();
    const now = m.nowPlaying(state, payload.now, at);
    const next = m.whatsNext(state);

    put("muNowTitle", now.track ? now.track.title : "quiet");
    put("muNowBy", now.track
      ? [now.track.artist, now.track.album].filter(Boolean).join(" · ")
      : now.why);
    const fill = el("muFill");
    if (fill) fill.style.width = (now.bar.following ? now.bar.fraction * 100 : 0) + "%";
    put("muNowTime", now.bar.following && now.bar.length
      ? m.clockText(now.bar.position) + " / " + m.clockText(now.bar.length)
      : "");
    put("muNowVoice", now.voice
      ? now.voice.who + ": " + now.voice.text : "");

    put("muNextWhat", next.title
      ? (next.when === "introducing" ? "being introduced: " : "next: ")
        + next.title + (next.artist ? " - " + next.artist : "")
      : "nothing queued");

    const queue = m.queueRows(state);
    const qPrint = queue.map((t) => t.id).join(",");
    if (qPrint !== queuePrint) {
      queuePrint = qPrint;
      const list = el("muQueue");
      if (list) {
        const frame = document.createDocumentFragment();
        for (const track of queue) frame.appendChild(item(track, "", ""));
        list.replaceChildren(frame);
      }
      put("muQueueHead", queue.length
        ? queue.length + " queued"
          + (next.requests ? " · " + next.requests + " asked for" : "")
        : "nothing queued");
    }

    const played = m.playedRows(state);
    const pPrint = played.map((t) => t.id).join(",");
    if (pPrint !== playedPrint) {
      playedPrint = pPrint;
      const list = el("muPlayed");
      if (list) {
        const frame = document.createDocumentFragment();
        for (const track of played) frame.appendChild(item(track, "", ""));
        list.replaceChildren(frame);
      }
    }

    /* WHAT THE RUNNING ORDER PANE DELIBERATELY DOES NOT DO: re-fetch
     * itself when the segment changes. /api/schedule/hours is a walk of
     * the whole sheet with per-entry prep figures behind it, and a view
     * that pulled it every time the booth moved on would be a poller
     * wearing an event's clothes. The sheet is a plan; plans do not
     * change every four seconds. The desk the booth is actually on is
     * visible on the Agent panel's segment cell, which is on screen
     * whatever view is open, and the ↻ is there for the rest. */
  }

  /* --------------------------------------------------------------- build */

  function build(host) {
    host.innerHTML =
      '<section class="mu-col">'
      + '<div class="mu-head"><b>On air</b></div>'
      + '<div class="mu-now">'
      + '<p id="muNowTitle" class="mu-title">quiet</p>'
      + '<p id="muNowBy" class="mu-by"></p>'
      + '<div class="mu-bar"><u id="muFill"></u></div>'
      + '<i id="muNowTime" class="mu-time"></i>'
      + '<p id="muNowVoice" class="mu-voice"></p>'
      + '<p id="muNextWhat" class="mu-next"></p>'
      + '</div>'
      + '<div class="mu-head"><b>Queue</b>'
      + '<span id="muQueueHead" class="mu-sub"></span></div>'
      + '<div id="muQueue" class="mu-list"></div>'
      + '<div class="mu-head"><b>Just played</b>'
      + '<span class="mu-sub">tap any record to open it</span></div>'
      + '<div id="muPlayed" class="mu-list"></div>'
      + '<p id="muLibNote" class="mu-fine"></p>'
      + '</section>'

      + '<section class="mu-col">'
      + '<div class="mu-head"><b>The shelf</b>'
      + '<span id="muShelfCount" class="mu-sub"></span>'
      + '<button id="muShelfMore" class="mu-btn" title="A different '
      + 'handful. /api/music/browse returns a stable sample seeded by the '
      + 'hour, so this sends a fresh seed - without one the same tracks '
      + 'come back and the button would look broken.">another</button>'
      + '</div>'
      + '<div id="muShelf" class="mu-list grow"></div>'
      + '<div class="mu-ask">'
      + '<input id="muAsk" placeholder="ask for a song" spellcheck="false">'
      + '<button id="muAskBtn" class="mu-btn" title="Queues it and the '
      + 'pair acknowledge it on air. It never cuts the record that is '
      + 'playing (#840).">ask</button>'
      + '</div>'
      + '</section>'

      + '<section class="mu-col">'
      + '<div class="mu-head"><b>Running order</b>'
      + '<span id="muOrderHead" class="mu-sub"></span>'
      + '<button id="muOrderAgain" class="mu-btn" title="Read the hour '
      + 'sheet again. This view does not poll it.">↻</button></div>'
      + '<div id="muOrder" class="mu-list grow"></div>'
      + '<div class="mu-head"><b>Asked for</b>'
      + '<button id="muBookAgain" class="mu-btn" title="Read the request '
      + 'book again">↻</button></div>'
      + '<div id="muBook" class="mu-list"></div>'
      + '</section>'
      + '<p id="muNote" class="mu-note"></p>';
  }

  function wire() {
    const more = el("muShelfMore");
    if (more) more.addEventListener("click", () => loadShelf(true));
    const again = el("muOrderAgain");
    if (again) again.addEventListener("click", loadOrder);
    const bookAgain = el("muBookAgain");
    if (bookAgain) bookAgain.addEventListener("click", loadBook);
    const askBtn = el("muAskBtn");
    const askBox = el("muAsk");
    const fire = () => {
      if (!askBox) return;
      const wanted = askBox.value;
      askBox.value = "";
      ask(wanted);
    };
    if (askBtn) askBtn.addEventListener("click", fire);
    if (askBox) {
      askBox.addEventListener("keydown", (event) => {
        if (event.key === "Enter") fire();
      });
    }
  }

  /* --------------------------------------------------------------- mount */

  async function mount(host) {
    if (!host || mounted) return;
    /* No readConfig here: every call this view makes goes through the
     * bridge, which already holds the base URL and the bearer, and this
     * view renders no <img> that would need an absolute one. */
    build(host);
    wire();
    mounted = true;
    if (!unsubscribe) unsubscribe = root.PineStationFeed.subscribe(paint);
    /* IN SERIES. Three parallel opens is three more things in flight at
     * the moment the operator is most likely to also be asking the
     * station for a clip, and 38 in flight is a measured 46-second media
     * stall. Sequential costs a second of screen fill and nothing else.
     *
     * The detail's own three reads are NOT here: they are deferred to the
     * first tap, because an operator who only wants to see what is coming
     * up should not pay 200 kB for a panel they never open. */
    await loadShelf(false);
    await loadOrder();
    await loadBook();
  }

  function bootstrap() {
    const tab = document.getElementById("musicTabBtn");
    const host = document.getElementById("music");
    if (!tab || !host) return;
    tab.addEventListener("click", () => {
      mount(host).catch((err) => note(String((err && err.message) || err), true));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }

  root.PineMusic = {mount, isMounted: () => mounted, ask};
})(typeof window !== "undefined" ? window : globalThis);
