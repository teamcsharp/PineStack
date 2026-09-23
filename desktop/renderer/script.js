/* The Script view - a moment on the air, taken apart.
 *
 * "Tap a row in the live feed; the right pane reconstructs how that moment
 * came to be. Then note it, edit it, and send it back to the writer room."
 *
 * THIS IS STAGE 1, AND IT SAYS SO ON ITS FACE. Everything here is served
 * by GET /api/dj/provenance/{id} (app.py:95141) with no server change at
 * all: the prompt as sent, the script that came back, model/temp/context,
 * the render engine and what it fell back from, the crystal shards with
 * their in_prompt flags, the vector searches, the source documents, the
 * schedule slot, the armed system prompt, and shelf-vs-live. What stage 1
 * cannot do - the tint, the grader's verdict, the return path into the
 * writer room, and any line older than the booth ring - is drawn as a gap
 * with the reason in it, never as an empty box. See script-lineage.js,
 * which holds every one of those judgements and is where the tests are.
 *
 * THE ONE RULE THIS VIEW IS BUILT AROUND: IT DOES NOT POLL.
 *
 * The feed on the left is not this view's - it is window.PineStationFeed,
 * the single station poller (one /api/dj every 4 s for the whole app,
 * shared with the LCD and the Sampler). This view subscribes; it never
 * fetches the feed itself, and it unsubscribes with nothing left running.
 *
 * The right pane fetches ONCE, ON TAP, and caches the answer by line id.
 * Re-tapping a line you have already opened costs nothing. There is a
 * Refresh, and it is a button a hand presses, not a timer.
 *
 * That is not fussiness. This station has a documented history of being
 * starved by chatty clients, and 38 concurrent requests in flight was
 * measured causing 46-second media stalls. A provenance pane that polled
 * would be one more of those, for a picture that cannot change: the line
 * has already aired.
 *
 * Reads are open today (require_read_auth is a no-op unless
 * SPARK_AGENT_LOCK_READS is set, which it is not), but every request goes
 * through window.pineDesktop, which attaches the bearer in the main
 * process - so this survives reads being locked without a change here.
 *
 * BOTH PRODUCTS, ONE FILE. Electron gets window.pineDesktop from
 * preload.js; the Android terminal injects the same surface as
 * PineDesktopBridge. Nothing in this file knows which it is talking to.
 */
(function (root) {
  "use strict";

  const NOTES_KEY = "pineScriptNotes";
  const MODES = [
    ["script", "Script", "The prompt as sent, the script that came back, and every system that fed them"],
    ["transcript", "Transcript", "The welded round this line was spoken inside, turn by turn"],
    ["3d", "3D", "The same lineage on the RapAssembly stage - ten stations, and the gaps lit"]
  ];

  const api = () => root.pineDesktop;
  const lineage = () => root.PineScriptLineage;
  const stage = () => root.PineScriptStage;

  let config = null;
  let mounted = false;
  let unsubscribe = null;
  let feedRows = [];
  let feedPrint = "";
  let picked = "";              /* the line id whose paperwork is on screen */
  let mode = "script";
  let inFlight = "";            /* the id being fetched, so a double tap is one fetch */
  let notes = {};

  /* id -> {lineage} | {failure}. The answer to "how did this line come to
   * be" cannot change after the line aired, so it is cached for the life
   * of the session. The one exception is a failure, which is re-askable:
   * an unreachable station may come back. */
  const answers = new Map();

  const el = (id) => document.getElementById(id);

  /* ---------------------------------------------------------- the notes */

  /* KEPT ON THIS TERMINAL, AND LABELLED AS SUCH.
   *
   * The station has two excellent return paths and stage 1 can reach
   * neither of them from an AIRED line:
   *
   *   POST /api/orchestrator/rejections/{review_id}/accept
   *     (rejection_workbench.py:315) - takes {candidate, instruction},
   *     grades it for the record only, whitelists the fingerprint, and
   *     triggers the recovery loop to re-write AND re-record. It needs a
   *     review_id, which exists only if the line was CUT before air.
   *
   *   POST /api/director/script/{sid}/revise (app.py) - literally "send it
   *     back to the writer room", the operator's note outranking the
   *     script, standing by default so every future round of that road
   *     carries it. It needs an sid, which exists only while the round is
   *     on the shelf.
   *
   * A line tapped in the live feed has aired, so it has neither.
   *
   * TODO(stage 2), in the order that unblocks the most:
   *   1. Stamp the round's sid and turn index onto the chat entry in
   *      speak_turns / _speak_turns_floorless, and onto airlog_row_from.
   *      Everything else here depends on it. It is a field stamp, not
   *      logic - but it is the live air path, so it lands alone.
   *   2. A line_id -> review_id lookup (a ?line_id= filter on
   *      /api/orchestrator/rejections, built on line_review.find_occurrence)
   *      so an aired line can reach /accept.
   *   3. Then this box posts instead of remembering, and this comment goes.
   *
   * Also worth knowing before stage 2 is designed: an operator annotation
   * store keyed by line id ALREADY EXISTS -
   * POST /api/screenplay/{hour_key}/note takes {kind, target_id, text, who}
   * and the notes feed script_lessons() into learning. It needs an hour
   * key, which /api/screenplay hands out. That is a much shorter road than
   * a new store. */
  function loadNotes() {
    try {
      const raw = localStorage.getItem(NOTES_KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      if (parsed && typeof parsed === "object") return parsed;
    } catch (err) { /* a full or blocked store must not stop the view */ }
    return {};
  }

  function saveNotes() {
    try { localStorage.setItem(NOTES_KEY, JSON.stringify(notes)); }
    catch (err) { note("That note could not be saved on this terminal.", true); }
  }

  function noteFor(id) {
    return notes[id] || {note: "", edit: "", at: 0};
  }

  /* --------------------------------------------------------- the fetch */

  /* ONE route, ONE call, on a tap. See the header. */
  async function ask(id) {
    if (!id || inFlight === id) return;
    inFlight = id;
    paintPane();
    try {
      const got = await api().get("/api/dj/provenance/" + encodeURIComponent(id));
      answers.set(id, {lineage: lineage().read(got), at: Date.now()});
    } catch (err) {
      /* The bridge throws away the status code and hands over the FastAPI
       * detail string - see the long note at the top of script-lineage.js.
       * readFailure turns that sentence back into a cause. */
      answers.set(id, {failure: lineage().readFailure(err), at: Date.now()});
    } finally {
      if (inFlight === id) inFlight = "";
      paintPane();
    }
  }

  function pick(id) {
    if (!id) return;
    picked = id;
    paintFeedSelection();
    const have = answers.get(id);
    /* A cached failure is re-asked; a cached answer is not. An expired
     * line will never come back, but an unreachable station might. */
    if (!have || (have.failure && have.failure.kind !== "gone")) ask(id);
    else paintPane();
  }

  /* --------------------------------------------------------- the paint */

  function note(text, bad) {
    const element = el("scNote");
    if (!element) return;
    element.textContent = text || "";
    element.classList.toggle("bad", !!bad);
  }

  function paintFeedSelection() {
    document.querySelectorAll(".sc-row").forEach((row) => {
      row.classList.toggle("picked", row.dataset.rowId === picked);
    });
  }

  function paintFeed(rows) {
    const list = el("scFeed");
    if (!list) return;
    feedRows = rows || [];

    /* The shared feed emits every 250 ms so the playhead can move between
     * polls. Rebuilding the list that often throws away scroll position
     * and the operator's selection for no gain, so it is rebuilt only when
     * the rows actually changed - the same discipline sampler.js uses. */
    const print = feedRows.length + ":" + feedRows.map(
      (row) => row.id + (row.lcdStatus === "Playing" ? "*" : "")).join(",");
    if (print === feedPrint) return;
    feedPrint = print;

    const fragment = document.createDocumentFragment();
    /* Newest first: the moment worth asking about almost always just
     * happened, and the whole ring is shown because the station already
     * caps itself at 240 rows - which is also exactly the window in which
     * provenance can still answer. */
    for (const row of feedRows.slice().reverse()) {
      const hint = lineage().paperworkHint(row);
      const item = document.createElement("div");
      item.className = "sc-row" + (hint.keeps ? "" : " thin")
        + (hint.tappable ? "" : " dead");
      item.dataset.rowId = row.id || "";
      if (row.lcdStatus === "Playing") item.classList.add("playing");
      if (row.id === picked) item.classList.add("picked");

      const who = document.createElement("b");
      who.textContent = row.name || row.who || row.kind || "booth";
      const text = document.createElement("span");
      text.textContent = row.text || "";
      const tag = document.createElement("em");
      /* A note that has been written against a line is visible from the
       * list, or it may as well not exist. */
      tag.textContent = (notes[row.id] && notes[row.id].note ? "✎ " : "")
        + (row.lcdStatus || "");
      item.appendChild(who);
      item.appendChild(text);
      item.appendChild(tag);
      item.title = hint.keeps
        ? "Show how this line came to be"
        : hint.why + " - the pane will say so";
      if (hint.tappable) {
        item.addEventListener("click", () => pick(row.id));
      }
      fragment.appendChild(item);
    }
    list.replaceChildren(fragment);

    const tally = el("scTally");
    if (tally) {
      tally.textContent = feedRows.length
        ? feedRows.length + " of " + lineage().RING_ROWS + " in the booth ring"
        : "";
    }
  }

  function block(title, body, className) {
    const wrap = document.createElement("div");
    wrap.className = "sc-block " + (className || "");
    const head = document.createElement("h4");
    head.textContent = title;
    wrap.appendChild(head);
    if (body != null) {
      const pre = document.createElement("pre");
      pre.textContent = String(body);
      wrap.appendChild(pre);
    }
    return wrap;
  }

  function stationCard(station) {
    const card = document.createElement("div");
    card.className = "sc-station"
      + (station.stage2 ? " pending" : (station.filled ? " lit" : " dark"));

    const head = document.createElement("div");
    head.className = "sc-station-head";
    head.innerHTML = '<span class="sc-n">' + station.n + "</span>";
    const label = document.createElement("b");
    label.textContent = station.label;
    const what = document.createElement("i");
    what.textContent = station.what;
    head.appendChild(label);
    head.appendChild(what);
    card.appendChild(head);

    if (station.head) {
      const lead = document.createElement("p");
      lead.className = "sc-lead";
      lead.textContent = station.head;
      card.appendChild(lead);
    }
    const rows = (station.rows || []).filter(Boolean);
    if (rows.length) {
      const list = document.createElement("ul");
      for (const row of rows) {
        const li = document.createElement("li");
        li.textContent = row;
        list.appendChild(li);
      }
      card.appendChild(list);
    }
    if ((station.leaves || []).length) {
      const list = document.createElement("ul");
      list.className = "sc-leaves";
      for (const leaf of station.leaves) {
        const li = document.createElement("li");
        li.className = leaf.on ? "on" : "off";
        li.textContent = leaf.text;
        li.title = leaf.why;
        list.appendChild(li);
      }
      card.appendChild(list);
    }
    if (station.stage2) {
      /* The gap, with its reason, in the operator's own pane. This is the
       * difference between "the tint box is empty" and "the tint is not
       * answerable from here yet, and this is the join that would fix
       * it". */
      const why = document.createElement("p");
      why.className = "sc-pending";
      why.textContent = "Stage 2 — " + station.note;
      card.appendChild(why);
    }
    if (!station.filled && !station.stage2 && !station.head && !rows.length) {
      const why = document.createElement("p");
      why.className = "sc-empty";
      why.textContent = "nothing was recorded here for this line";
      card.appendChild(why);
    }
    return card;
  }

  function paintScript(body, got) {
    for (const section of lineage().page(got)) {
      if (section.kind === "station") {
        body.appendChild(stationCard(section.station));
        continue;
      }
      if (!section.body) {
        body.appendChild(block(section.title,
          section.key === "prompt"
            ? "The prompt was not kept for this row. Older rows and the "
              + "analysis desk carry their paperwork elsewhere "
              + "(app.py:95180)."
            : "nothing was recorded", "quiet"));
        continue;
      }
      const wrap = block(section.title, section.body, "sc-" + section.key);
      if (section.note) {
        const foot = document.createElement("p");
        foot.className = "sc-foot"
          + (got.diverged && section.key === "answered" && !got.diverged.verbatim
            ? " warn" : "");
        foot.textContent = section.note;
        wrap.appendChild(foot);
      }
      body.appendChild(wrap);
    }
  }

  function paintTranscript(body, got) {
    const round = lineage().roundOf(feedRows, got.id);
    if (!round.found) {
      body.appendChild(block("The round",
        "That line has rolled out of the live feed, so the turns around it "
        + "cannot be rebuilt from here. The paperwork above is what was "
        + "fetched while it was still in the ring.", "quiet"));
      return;
    }
    const head = document.createElement("p");
    head.className = "sc-lead";
    head.textContent = round.welded
      ? round.rows.length + " turns were welded into one file (" + round.key
        + "), so this is the round as the audience heard it."
      : "This line has its own take - it was not welded into a round.";
    body.appendChild(head);

    const list = document.createElement("div");
    list.className = "sc-transcript";
    for (const row of round.rows) {
      const turn = document.createElement("div");
      turn.className = "sc-turn" + (row.here ? " here" : "");
      const who = document.createElement("b");
      who.textContent = row.who;
      const when = document.createElement("em");
      when.textContent = row.until
        ? row.from.toFixed(1) + "–" + row.until.toFixed(1) + "s" : "";
      const said = document.createElement("span");
      said.textContent = row.text;
      turn.appendChild(who);
      turn.appendChild(when);
      turn.appendChild(said);
      if (row.id !== got.id) {
        turn.title = "Show how this turn came to be";
        turn.addEventListener("click", () => pick(row.id));
      }
      list.appendChild(turn);
    }
    body.appendChild(list);

    /* Being straight about what this transcript is. */
    const foot = document.createElement("p");
    foot.className = "sc-foot";
    foot.textContent = "Rebuilt from the feed: the turns sharing this "
      + "line's clip_media, ordered by their spans. That recovers what was "
      + "welded into one audio file, which is narrower than the round the "
      + "writer wrote - the round's own id (its sid) does not reach an "
      + "aired line, and that join is stage 2.";
    body.appendChild(foot);
  }

  async function paint3d(body, got) {
    const host = document.createElement("div");
    host.className = "sc-stage";
    body.appendChild(host);
    const foot = document.createElement("p");
    foot.className = "sc-foot";
    foot.textContent = "The RapAssembly spine, for one line. Amber plates "
      + "with a broken edge are the stations stage 1 cannot answer.";
    body.appendChild(foot);
    try {
      await stage().open(host, got, config && config.baseUrl);
    } catch (err) {
      host.remove();
      body.insertBefore(block("The stage did not open",
        String(err && err.message || err), "quiet"), foot);
    }
  }

  function paintNoteBox(body, got) {
    const id = got.id;
    const kept = noteFor(id);

    const box = document.createElement("div");
    box.className = "sc-notebox";

    const head = document.createElement("h4");
    head.textContent = "Note and edit";
    box.appendChild(head);

    const noteField = document.createElement("textarea");
    noteField.className = "sc-field";
    noteField.rows = 3;
    noteField.placeholder = "What is wrong with it, or right about it — "
      + "written as a direction the writer room could act on.";
    noteField.value = kept.note || "";

    const editField = document.createElement("textarea");
    editField.className = "sc-field";
    editField.rows = 3;
    editField.placeholder = "The line as it should have been.";
    editField.value = kept.edit || got.said || "";

    const keep = () => {
      notes[id] = {note: noteField.value, edit: editField.value,
        at: Date.now(), said: got.said,
        who: String((got.line || {}).name || (got.line || {}).who || "")};
      if (!noteField.value && !editField.value) delete notes[id];
      saveNotes();
      feedPrint = "";                 /* so the ✎ mark appears on the row */
      paintFeed(feedRows);
      paintFeedSelection();
    };
    noteField.addEventListener("change", keep);
    editField.addEventListener("change", keep);

    box.appendChild(noteField);
    box.appendChild(editField);

    const bar = document.createElement("div");
    bar.className = "sc-notebar";

    const copy = document.createElement("button");
    copy.className = "sc-btn";
    copy.textContent = "Copy for the writer room";
    copy.title = "The line, the note and the edit, on the clipboard";
    copy.addEventListener("click", () => {
      keep();
      const carry = [
        "line " + id + (got.line && got.line.name ? " · " + got.line.name : ""),
        "aired: " + got.said,
        "edit:  " + editField.value,
        "note:  " + noteField.value
      ].join("\n");
      try { api().copyText(carry); note("Copied."); }
      catch (err) { note("The clipboard refused that.", true); }
    });
    bar.appendChild(copy);

    /* Present, visibly disabled, and honest about why. Hiding it would
     * leave the operator wondering whether he had missed the button; a
     * live button that silently did nothing would be worse still. */
    const send = document.createElement("button");
    send.className = "sc-btn off";
    send.textContent = "Send back to the writer room";
    send.disabled = true;
    send.title = "Stage 2. The return paths exist and are good — "
      + "/api/orchestrator/rejections/{review_id}/accept re-writes AND "
      + "re-records, and /api/director/script/{sid}/revise makes the note "
      + "standing for that road — but both are pre-air: one needs a "
      + "review_id (which exists only if the line was cut) and the other "
      + "an sid (which exists only while the round is on the shelf). An "
      + "aired line has neither until the sid join is stamped onto the "
      + "chat entry.";
    bar.appendChild(send);

    const why = document.createElement("span");
    why.className = "sc-foot";
    why.textContent = "Notes are kept on this terminal only.";
    bar.appendChild(why);

    box.appendChild(bar);
    body.appendChild(box);
  }

  function paintPane() {
    const body = el("scBody");
    const head = el("scHead");
    if (!body || !head) return;
    stage().close();
    body.replaceChildren();

    if (!picked) {
      head.textContent = "";
      body.appendChild(block("Nothing picked",
        "Tap a line in the feed. The station is asked once, on the tap, and "
        + "the answer is kept — this pane never polls.", "quiet"));
      return;
    }

    const row = feedRows.find((one) => one.id === picked) || {};
    head.textContent = (row.name || row.who || "booth") + " — "
      + String(row.text || "").slice(0, 140);

    if (inFlight === picked) {
      body.appendChild(block("Asking the booth…",
        "One request, on this tap. The box is a live radio station writing "
        + "and recording audio, so an answer can queue behind that work.",
        "quiet"));
      return;
    }

    const have = answers.get(picked);
    if (!have) {
      body.appendChild(block("Not asked yet", null, "quiet"));
      return;
    }

    if (have.failure) {
      /* THE POINT OF THE WHOLE FAILURE PATH: the operator must never be
       * left wondering whether this pane is broken. */
      const fail = have.failure;
      const wrap = block(fail.title, fail.say, "sc-fail " + fail.kind);
      if (fail.stage2) {
        const foot = document.createElement("p");
        foot.className = "sc-foot";
        foot.textContent = fail.stage2;
        wrap.appendChild(foot);
      }
      if (fail.kind !== "gone") {
        const again = document.createElement("button");
        again.className = "sc-btn";
        again.textContent = "Ask again";
        again.addEventListener("click", () => { answers.delete(picked); ask(picked); });
        wrap.appendChild(again);
      }
      body.appendChild(wrap);
      /* A line whose paperwork has expired can still be noted. The note is
       * about the line, not about the paperwork. */
      paintNoteBox(body, {id: picked, said: String(row.text || ""), line: row});
      return;
    }

    const got = have.lineage;
    if (mode === "3d") paint3d(body, got);
    else if (mode === "transcript") paintTranscript(body, got);
    else paintScript(body, got);
    paintNoteBox(body, got);
  }

  function paintModes() {
    for (const spec of MODES) {
      const button = el("scMode-" + spec[0]);
      if (button) button.classList.toggle("on", mode === spec[0]);
    }
  }

  /* --------------------------------------------------------------- build */

  function build(host) {
    host.innerHTML = "";

    const left = document.createElement("div");
    left.className = "sc-left";
    left.innerHTML =
      '<div class="sc-feed-head"><b>Feed</b>'
      + '<span id="scTally" class="sc-tally" title="Provenance is answered '
      + 'off the live booth ring. Past it the paperwork is gone, and the '
      + 'pane says so."></span></div>'
      + '<div id="scFeed" class="sc-feed"></div>';

    const right = document.createElement("div");
    right.className = "sc-right";

    const bar = document.createElement("div");
    bar.className = "sc-bar";
    const title = document.createElement("div");
    title.id = "scHead";
    title.className = "sc-head";
    bar.appendChild(title);

    const modes = document.createElement("div");
    modes.className = "sc-modes";
    for (const spec of MODES) {
      const button = document.createElement("button");
      button.id = "scMode-" + spec[0];
      button.className = "sc-mode";
      button.textContent = spec[1];
      button.title = spec[2];
      button.addEventListener("click", () => {
        mode = spec[0];
        paintModes();
        paintPane();
      });
      modes.appendChild(button);
    }
    const refresh = document.createElement("button");
    refresh.className = "sc-mode sc-act";
    refresh.textContent = "Refresh";
    refresh.title = "Ask the booth again for this line. A button, not a timer.";
    refresh.addEventListener("click", () => {
      if (!picked) return;
      answers.delete(picked);
      ask(picked);
    });
    modes.appendChild(refresh);
    bar.appendChild(modes);
    right.appendChild(bar);

    const body = document.createElement("div");
    body.id = "scBody";
    body.className = "sc-body";
    right.appendChild(body);

    const foot = document.createElement("div");
    foot.className = "sc-note-bar";
    foot.innerHTML = '<span id="scNote" class="sc-note"></span>'
      + '<span class="sc-stagelabel" title="Stage 1: provenance for lines '
      + 'still in the booth ring, with no server change. Stage 2 is the sid '
      + 'join, durable provenance, the tint and the verdict, and the '
      + 'aired-line return path.">stage 1 — lines still in the booth</span>';
    right.appendChild(foot);

    host.appendChild(left);
    host.appendChild(right);
    paintModes();
  }

  /* --------------------------------------------------------------- mount */

  async function mount(host) {
    if (!host || mounted) return;
    notes = loadNotes();
    config = await api().readConfig();
    build(host);
    paintPane();

    /* three.js is 608 kB and there is no CDN out here. Start it now, on
     * the view's first open, so pressing 3D shows a scene instead of a
     * download - and do not start it at boot, because an operator who
     * never opens this view should not pay for it. Failure here is
     * deliberately swallowed: the 3D button reports it if it is pressed,
     * and the other two presentations do not need it. */
    try { stage().preload(config && config.baseUrl); } catch (err) { /* on demand */ }

    if (!unsubscribe) {
      const receive = (payload) => {
        paintFeed(payload.rows);
        paintFeedSelection();
      };
      unsubscribe = root.PineStationFeed.subscribeView
        ? root.PineStationFeed.subscribeView(host, receive)
        : root.PineStationFeed.subscribe(receive);
    }
    mounted = true;
  }

  function unmount() {
    stage().close();
    if (unsubscribe) { unsubscribe(); unsubscribe = null; }
    mounted = false;
  }

  /* Mounted on first visit, not at boot - the same rule the Sampler
   * follows. An unopened Script view costs the station nothing: no
   * subscription to the shared feed, no three.js, no requests. */
  function bootstrap() {
    const tab = document.getElementById("scriptTabBtn");
    const host = document.getElementById("script");
    if (!tab || !host) return;
    tab.addEventListener("click", () => {
      mount(host).catch((err) => {
        const target = document.getElementById("scNote");
        if (target) {
          target.textContent = String(err && err.message || err);
          target.classList.add("bad");
        }
      });
      /* The stage owns a WebGL context and a rAF loop; leaving it running
       * behind another view is exactly how a 3js panel becomes a battery
       * complaint on a tablet. */
      if (stage().isOpen()) stage().resize();
    });
    document.querySelectorAll(".tab").forEach((other) => {
      if (other.id === "scriptTabBtn") return;
      other.addEventListener("click", () => { if (mounted) stage().close(); });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }

  root.PineScript = {
    mount,
    unmount,
    isMounted: () => mounted,
    pick,
    mode: () => mode,
    setMode: (next) => { mode = next; paintModes(); paintPane(); },
    notes: () => notes,
    /* The cache, for anything that wants to know what has been asked
     * without asking again. */
    asked: () => [...answers.keys()]
  };
})(typeof window !== "undefined" ? window : globalThis);
