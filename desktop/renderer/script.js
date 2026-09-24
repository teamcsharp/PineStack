/* The Script view - a moment on the air, taken apart.
 *
 * "Tap a row in the live feed; the right pane reconstructs how that moment
 * came to be. Then note it, edit it, and send it back to the writer room."
 *
 * Provenance is stage 1. Everything in that pane is served
 * by GET /api/dj/provenance/{id} (app.py:95141) with no server change at
 * all: the prompt as sent, the script that came back, model/temp/context,
 * the render engine and what it fell back from, the crystal shards with
 * their in_prompt flags, the vector searches, the source documents, the
 * schedule slot, the armed system prompt, and shelf-vs-live. What provenance
 * cannot do - the tint, the grader's verdict, and any line older than the
 * booth ring - is drawn as a gap
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
  const POLICY_NOTE_CAP = 160;    /* operator_lesson_clause keeps 160 per road */
  const SCREENPLAY_NOTE_CAP = 4000;
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

  /* The screenplay stores a note against ln-{aired line id}. Its notes do
   * not feed script_lessons() or the writer prompt. The orchestrator's
   * operator_notes policy does. Source "s:YYMMDDHH:noteid" joins its
   * directive to the screenplay note without needing a pre-air sid. */
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

  function directionFor(draft, said) {
    const noteText = String(draft.note || "").trim();
    const edit = String(draft.edit || "").trim();
    const aired = String(said || "").trim();
    const changed = !!edit && edit !== aired;
    if (!noteText && !changed) throw new Error("Write a direction or change the line first.");
    const policy = [noteText, changed ? "Prefer this wording: " + edit : ""]
      .filter(Boolean).join("\n");
    if (policy.length > POLICY_NOTE_CAP) {
      throw new Error("The writer prompt can carry 160 characters for this direction. Shorten the note or edit; your draft is kept.");
    }
    const screenplay = [noteText ? "Direction: " + noteText : "",
      "Aired: " + aired, changed ? "Edit: " + edit : ""].filter(Boolean).join("\n");
    if (screenplay.length > SCREENPLAY_NOTE_CAP) {
      throw new Error("The line note exceeds 4000 characters. Shorten it; your draft is kept.");
    }
    return {policy, screenplay};
  }

  async function screenplayHourFor(id, line) {
    const index = await api().get("/api/screenplay");
    const hours = Array.isArray(index && index.hours) ? index.hours : [];
    const at = Number(line.air_at || line.ts || 0);
    const near = hours.filter((h) => at >= Number(h.since) - 3600
      && at < Number(h.until) + 3600);
    const candidates = [...new Map([...near.slice(0, 5), ...hours.slice(0, 5)]
      .filter((h) => h && h.key).map((h) => [h.key, h])).values()].slice(0, 10);
    for (const hour of candidates) {
      if (!hour.key) continue;
      try {
        const found = await api().get("/api/screenplay/"
          + encodeURIComponent(hour.key) + "/line/" + encodeURIComponent(id));
        if (found && found.line === id && found.hour_key === hour.key) return hour.key;
      } catch (err) {
        if (!/No such line in that hour|404 Not Found/.test(String(err && err.message || err))) {
          throw err;
        }
      }
    }
    throw new Error("The aired line was not found in the screenplay ledger. The draft is still on this terminal; retry when the ledger catches up.");
  }

  function saveDelivery(id, draftKey, delivery) {
    const current = notes[id];
    if (!current || JSON.stringify([current.note, current.edit, current.said]) !== draftKey) return false;
    current.delivery = {...delivery};
    saveNotes();
    return true;
  }

  async function sendDraft(id, said, line) {
    const current = notes[id] || {};
    const draftKey = JSON.stringify([current.note, current.edit, current.said]);
    const words = directionFor(current, said);
    const delivery = current.delivery && current.delivery.key === draftKey
      ? {...current.delivery}
      : {key: draftKey, who: "Script view " + Math.random().toString(36).slice(2, 14),
         screenplay: words.screenplay, policy: words.policy};
    if (delivery.sent) return {sent: true, already: true};
    saveDelivery(id, draftKey, delivery);

    if (!delivery.hour) {
      delivery.hour = await screenplayHourFor(id, line || {});
      saveDelivery(id, draftKey, delivery);
    }
    const route = "/api/screenplay/" + encodeURIComponent(delivery.hour);
    const target = "ln-" + id;
    if (!delivery.noteId) {
      const page = await api().get(route);
      const saved = (page.notes || []).find((row) => row.target_id === target
        && row.who === delivery.who && row.text === delivery.screenplay);
      if (saved) delivery.noteId = saved.id;
      else {
        const out = await api().post(route + "/note", {
          kind: "note", target_id: target, text: delivery.screenplay,
          who: delivery.who});
        const row = out && out.note;
        if (!out || out.ok !== true || !row || !row.id
            || row.target_id !== target || row.text !== delivery.screenplay) {
          throw new Error("The screenplay did not acknowledge this line note. Retry to check before sending again.");
        }
        delivery.noteId = row.id;
      }
      saveDelivery(id, draftKey, delivery);
    }

    const source = "s:" + delivery.hour.slice(2).replace(/[^0-9]/g, "")
      + ":" + delivery.noteId;
    if (source.length > 20) throw new Error("The writer-room link is too long. Draft kept.");
    const accepted = (book) => Array.isArray(book && book.notes)
      && book.notes.some((row) => row.source === source
        && row.text === delivery.policy);
    let book = await api().get("/api/orchestrator/notes");
    if (!accepted(book)) {
      const out = await api().post("/api/orchestrator/notes", {
        text: delivery.policy, road: "", source});
      if (!out || out.ok !== true) {
        throw new Error("The writer room did not acknowledge the direction. Retry to check again.");
      }
      book = await api().get("/api/orchestrator/notes");
      if (!accepted(book)) {
        throw new Error("The direction is not visible in the writer-room policy book yet. Retry to check again.");
      }
    }
    delivery.sent = true;
    saveDelivery(id, draftKey, delivery);
    return {sent: true, stale: JSON.stringify([
      (notes[id] || {}).note, (notes[id] || {}).edit, (notes[id] || {}).said]) !== draftKey};
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
      const previous = notes[id] || {};
      notes[id] = {note: noteField.value, edit: editField.value,
        at: Date.now(), said: got.said,
        who: String((got.line || {}).name || (got.line || {}).who || ""),
        delivery: previous.delivery};
      if (!noteField.value && !editField.value) delete notes[id];
      saveNotes();
      feedPrint = "";                 /* so the ✎ mark appears on the row */
      paintFeed(feedRows);
      paintFeedSelection();
      updateSend();
    };
    noteField.addEventListener("input", keep);
    editField.addEventListener("input", keep);

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

    const send = document.createElement("button");
    send.className = "sc-btn";
    send.textContent = "Send back to the writer room";
    send.title = "Save this aired line on the screenplay and direct future writing";
    bar.appendChild(send);

    const why = document.createElement("span");
    why.className = "sc-foot";
    let busy = false;
    const updateSend = () => {
      const draft = noteFor(id);
      const key = JSON.stringify([draft.note, draft.edit, draft.said]);
      const delivery = draft.delivery && draft.delivery.key === key
        ? draft.delivery : null;
      send.disabled = busy || !!(delivery && delivery.sent);
      send.textContent = busy ? "Sending..." : delivery && delivery.sent
        ? "Sent to the writer room" : delivery && delivery.noteId
          ? "Retry sending" : "Send back to the writer room";
      why.textContent = delivery && delivery.sent
        ? "Sent to the script and writer room. Draft kept here."
        : delivery && delivery.noteId
          ? "Line note saved on the script; writer-room direction pending. Retry."
          : "Draft kept on this terminal until the writer room acknowledges it.";
    };
    updateSend();
    send.addEventListener("click", async () => {
      keep();
      busy = true;
      updateSend();
      try {
        const result = await sendDraft(id, got.said,
          feedRows.find((row) => row.id === id) || got.line || {});
        note(result.stale
          ? "Earlier version sent; your newer edits are still a draft."
          : "Direction acknowledged by the writer room.");
      } catch (err) {
        note(String(err && err.message || err), true);
      } finally {
        busy = false;
        updateSend();
      }
    });
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
      + '<span class="sc-stagelabel" title="Provenance reads the booth ring. '
      + 'Post-air notes reach the screenplay and writer-room policy book; '
      + 'tint and verdict still need their own lineage.">booth-ring provenance</span>';
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
    sendDraft,
    /* The cache, for anything that wants to know what has been asked
     * without asking again. */
    asked: () => [...answers.keys()]
  };
})(typeof window !== "undefined" ? window : globalThis);
