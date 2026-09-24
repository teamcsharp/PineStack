/* THE PRESENTATION VIEW - the station, on a wall.
 *
 * Six panes off ONE poll. Playlist, running order, the script following
 * itself, the feed at its fullest, the gallery, and the video wall, with
 * the transport across the top.
 *
 * THE ONE RULE THIS SCREEN IS BUILT AROUND. 38 concurrent requests in
 * flight to the station measured a 46-second media stall on the tablet on
 * 2026-09-11 - which is why the tablet plays no audio today. This view has
 * more panes than any other and would have been the thing that made it
 * worse. So: there is NOT ONE setInterval in this file. Everything hangs
 * off PineStationFeed's existing /api/dj poll - four seconds, interpolated
 * locally at 250ms, which is the station's own cadence (app.py:154692) -
 * and every other route goes through PinePresentationSource's gate, which
 * is one request wide. Two questions outstanding, total, whatever is on
 * screen. peak() is painted in the corner so that is checkable rather than
 * claimed.
 *
 * WHAT COMES FREE WITH THE POLL, and therefore costs nothing extra:
 *   now playing, art, remaining          station.now / station.remaining
 *   what is queued                       station.upcoming  (20 deep)
 *   what just played                     station.played    (10 deep)
 *   who is in the booth                  station.dj_names
 *   every line, aired or waiting         PineLcdDialogue.stationRows()
 *   which line is sounding right now     stream_now, worked out locally
 * The playlist and the script panes make no requests at all. That is not
 * an optimisation, it is the reason this screen is allowed to exist.
 *
 * THE PLAYLIST CAN REALLY BE REORDERED, and the plan said it could not.
 * It named /api/schedule/segment/priority and /api/schedule/segment/pin as
 * the only confirmed writes and marked the music queue unconfirmed. It is
 * confirmed: POST /api/dj/queue/move (app.py:94973, #671) takes
 * {id, to: "front" | "back" | <index>} and reorders exactly the list
 * /api/dj hands back as `upcoming` - requests first, then the queue, "one
 * list, in the order the panel shows it, so an index means what it looks
 * like it means". So the controls here move real records. Nothing on this
 * screen is a button that does nothing.
 *
 * THE MEDIA PLAYER IS NOT A NEW PLAYER. The shell already owns one -
 * <audio id="desktopRadioPlayer"> in index.html - and the operator's
 * standing rule is that the broadcast plays in exactly one room, never
 * two (docs/pine-box-lcd.md, the destination picker). A second <audio>
 * pointed at the same stream is the fault that rule exists to prevent: the
 * same show a few hundred milliseconds apart, which sounds like a broken
 * station rather than two copies of a working one. So the transport here
 * DRIVES THE SHELL'S ELEMENT and shows the station's own clock; where
 * there is no such element (the tablet, where native audio owns the
 * stream) it says so instead of making one.
 *
 * VOTES GO WHERE VOTES ALREADY GO. See presentation-source.js: a cut line
 * to /api/orchestrator/rejections/{id} with its occurrence and revision
 * checked, an aired line to /api/feedback. No third store.
 */
(function (root) {
  "use strict";

  const api = () => root.pineDesktop;

  const GENERATIONS = "/api/generations?limit=1000";
  const HOURS = "/api/schedule/hours?count=3";
  const BROWSE = "/api/music/browse?limit=24";

  /* The script pane follows the air. It shows a window around the line
   * that is sounding rather than the whole ring, because a wall that has
   * to be scrolled is a wall nobody reads. */
  const SCRIPT_BEFORE = 6;
  const SCRIPT_AFTER = 10;

  let host = null;
  let mounted = false;
  let config = null;
  let source = null;
  let wall = null;
  let leave = null;
  let station = null;
  let rows = [];
  let speaking = null;
  let popup = null;
  let noteFor = "";                /* the feed row with its note box open */
  let busy = "";
  let beatAt = 0;                  /* the shared feed's skew-corrected clock */
  let remainingAt = 0;             /* when `station.remaining` was last true */

  const el = (id) => document.getElementById(id);

  function say(text, bad) {
    const line = el("pvNote");
    if (!line) return;
    line.textContent = text || "";
    line.classList.toggle("bad", !!bad);
  }

  function absolute(url) {
    const path = String(url || "");
    if (/^https?:/i.test(path)) return path;
    /* The page's own origin first - see the long note in sampler.js's
     * absolute(). The terminal may have reached the station by a different
     * road than the configured one, and this station has no CORS. */
    if (/^https?:$/i.test(location.protocol)) return location.origin + path;
    return String((config && config.baseUrl) || "").replace(/\/+$/, "") + path;
  }

  /* Reads are open on this station today (SPARK_AGENT_LOCK_READS unset),
   * so these answer with no header. The bearer goes on anyway - the day
   * someone locks reads, every pane here goes dark at once and the cause
   * would be a header nobody remembered to send. */
  function headers() {
    return (config && config.apiKey)
      ? { Authorization: "Bearer " + config.apiKey } : {};
  }

  async function bytesOf(url) {
    const response = await fetch(absolute(url), { headers: headers() });
    if (!response.ok) {
      throw new Error("The station could not provide that (HTTP "
        + response.status + ").");
    }
    return response.blob();
  }

  function seconds(value) {
    const total = Math.max(0, Math.round(Number(value) || 0));
    return Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0");
  }

  function clockOf(epoch) {
    const at = Number(epoch);
    if (!Number.isFinite(at) || at <= 0) return "";
    const when = new Date(at * 1000);
    return String(when.getHours()).padStart(2, "0") + ":"
      + String(when.getMinutes()).padStart(2, "0");
  }

  /* ------------------------------------------------------------- player */

  /* The shell's element, if this build has one. Never created here. */
  function shellAudio() { return document.getElementById("desktopRadioPlayer"); }

  function paintPlayer() {
    const now = (station && station.now) || null;
    const art = el("pvArt");
    if (art) {
      const want = now && now.art ? absolute(now.art) : "";
      if (art.getAttribute("data-src") !== want) {
        art.setAttribute("data-src", want);
        if (want) { art.src = want; art.style.visibility = "visible"; }
        else { art.removeAttribute("src"); art.style.visibility = "hidden"; }
      }
    }
    const title = el("pvTitle");
    if (title) title.textContent = now ? (now.title || now.id || "") : "nothing on the deck";
    const by = el("pvBy");
    if (by) {
      by.textContent = now
        ? [now.artist, now.album].filter(Boolean).join(" - ")
        : (station && station.on ? "the booth has the floor" : "off air");
    }

    /* THE ONE PIECE OF ARITHMETIC ON THIS SCREEN, and it is the reason
     * the poll can stay at four seconds. `remaining` is a number the
     * station worked out at the moment it answered (app.py:25284); read
     * straight, the bar would jump once every four seconds and sit still
     * in between. So the last polled value is stamped, and the time since
     * that stamp is subtracted on every 250ms tick. Polling faster to get
     * a moving bar would be four times the traffic for a subtraction this
     * machine can do itself - which is exactly the trade the station's own
     * comment makes at app.py:154692. */
    const since = Math.max(0, (beatAt - remainingAt) / 1000);
    const left = Math.max(0, Number((station && station.remaining) || 0) - since);
    const length = Number((now && now.seconds) || 0);
    const bar = el("pvBar");
    if (bar) {
      const done = length > 0 ? Math.min(1, Math.max(0, (length - left) / length)) : 0;
      bar.style.width = (done * 100).toFixed(2) + "%";
    }
    const clock = el("pvClock");
    if (clock) clock.textContent = length > 0 ? seconds(length - left) + " / " + seconds(length) : "";

    const monitor = el("pvHear");
    const audio = shellAudio();
    if (monitor) {
      monitor.disabled = !audio;
      monitor.textContent = !audio ? "no player in this shell"
        : audio.paused ? "Hear it here" : "Quiet here";
      monitor.classList.toggle("on", !!audio && !audio.paused);
      monitor.title = audio
        ? "Play or pause THIS machine's copy of the broadcast. The station "
          + "keeps going either way."
        : "This build has no page-side player - audio is owned natively.";
    }

    const cast = el("pvCast");
    if (cast) {
      const names = (station && station.dj_names) || {};
      cast.textContent = [names.host, names.cohost, names.guest || names.third]
        .filter(Boolean).join(" · ");
    }
    const budget = el("pvBudget");
    if (budget && source) {
      budget.textContent = "1 poll · " + source.inFlight() + " asking (peak "
        + source.peak() + ")";
    }
  }

  /* ----------------------------------------------------------- playlist */

  let playlistPrint = "";

  async function move(id, to) {
    if (busy) return;
    busy = "move";
    try {
      await api().post("/api/dj/queue/move", { id, to });
      say("Moved.");
      /* The next poll is up to four seconds away and the operator just
       * pressed something - ask the shared feed to go now rather than
       * starting a timer of our own. */
      if (root.PineStationFeed) root.PineStationFeed.refresh();
    } catch (error) {
      say(String(error.message || error), true);
    } finally { busy = ""; }
  }

  function trackRow(track, kind, index) {
    const item = document.createElement("div");
    item.className = "pv-track " + kind;
    const art = document.createElement("i");
    if (track.art) art.style.backgroundImage = "url('" + absolute(track.art) + "')";
    const body = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = track.title || track.id || "";
    const by = document.createElement("span");
    by.textContent = track.artist || "";
    body.appendChild(title);
    body.appendChild(by);
    item.appendChild(art);
    item.appendChild(body);

    /* Real controls against a real route (app.py:94973). The plan marked
     * this unconfirmed; it is confirmed, so these move records. */
    if (kind === "queued" && track.id) {
      const up = document.createElement("button");
      up.className = "pv-mini";
      up.textContent = "^";
      up.title = "Play this next";
      up.onclick = () => move(track.id, "front");
      const down = document.createElement("button");
      down.className = "pv-mini";
      down.textContent = "v";
      down.title = "Send this to the back of the line";
      down.onclick = () => move(track.id, "back");
      item.appendChild(up);
      item.appendChild(down);
      if (index === 0) item.classList.add("next");
    }
    return item;
  }

  function paintPlaylist() {
    const list = el("pvQueue");
    if (!list || !station) return;
    const queued = (station.upcoming || []).slice(0, 12);
    const played = (station.played || []).slice(0, 6);
    const print = queued.map((t) => t.id).join(",") + "|" + played.map((t) => t.id).join(",");
    if (print === playlistPrint) return;
    playlistPrint = print;

    const fragment = document.createDocumentFragment();
    const head = (text) => {
      const mark = document.createElement("div");
      mark.className = "pv-sub";
      mark.textContent = text;
      fragment.appendChild(mark);
    };
    head("Up next" + (station.requests ? " (" + station.requests + " requested)" : ""));
    if (!queued.length) {
      const empty = document.createElement("p");
      empty.className = "pv-empty";
      empty.textContent = "The line is empty; the rotation picks the next record.";
      fragment.appendChild(empty);
    }
    queued.forEach((track, at) => fragment.appendChild(trackRow(track, "queued", at)));
    head("Just played");
    played.forEach((track) => fragment.appendChild(trackRow(track, "played")));
    list.replaceChildren(fragment);
  }

  /* A dip into the library, read-only on purpose: 35,000 tracks are too
   * many to list, so /api/music/browse is a stable random sample
   * (app.py:93073) and this is a look around, not a control surface. It
   * is asked for at most once every five minutes. */
  function paintLibrary(payload) {
    const box = el("pvLibrary");
    if (!box) return;
    const results = (payload && payload.results) || [];
    box.replaceChildren();
    for (const track of results.slice(0, 12)) {
      const chip = document.createElement("span");
      chip.className = "pv-chip";
      chip.textContent = (track.artist ? track.artist + " - " : "") + (track.title || "");
      chip.title = track.album || "";
      box.appendChild(chip);
    }
    const total = el("pvLibraryTotal");
    if (total) {
      total.textContent = payload && payload.total
        ? Number(payload.total).toLocaleString() + " tracks" : "";
    }
  }

  /* ----------------------------------------------------------- schedule */

  let hoursPrint = "";

  function paintSchedule(payload) {
    const box = el("pvHours");
    if (!box) return;
    const hours = (payload && payload.hours) || [];
    const print = JSON.stringify(hours.map((h) => [h.key,
      (h.slots || []).map((s) => [s.id, s.state, s.past]).join("|")]));
    if (print === hoursPrint) return;
    hoursPrint = print;

    box.replaceChildren();
    for (const hour of hours) {
      const block = document.createElement("div");
      block.className = "pv-hour" + (hour.is_now ? " now" : "") + (hour.is_past ? " past" : "");
      const head = document.createElement("div");
      head.className = "pv-hour-head";
      const label = document.createElement("b");
      label.textContent = hour.label;
      const preset = document.createElement("span");
      preset.textContent = (hour.preset || "") + (hour.overridden ? " (its own orders)" : "");
      head.appendChild(label);
      head.appendChild(preset);
      block.appendChild(head);

      for (const slot of hour.slots || []) {
        const tile = document.createElement("button");
        tile.className = "pv-slot " + String(slot.state || "coming").replace(" ", "-")
          + (slot.past ? " inert" : "") + (slot.enabled === false ? " off" : "");
        const when = document.createElement("i");
        when.textContent = slot.starts_at || clockOf(slot.starts_epoch);
        const name = document.createElement("b");
        name.textContent = slot.label || slot.kind || slot.id;
        tile.appendChild(when);
        tile.appendChild(name);

        /* #965/#966: prefer slot_prep, which is what THIS entry is
         * holding, over prep, which is per KIND and makes three
         * identical entries all read as stocked off one shelf. */
        const prep = slot.slot_prep || null;
        if (prep) {
          const fill = document.createElement("u");
          fill.style.width = Math.min(100, Math.round((prep.share || 0) * 100)) + "%";
          fill.className = prep.covered ? "covered" : prep.bare ? "bare" : "";
          tile.appendChild(fill);
        }
        tile.onclick = () => openSegment(hour, slot);
        block.appendChild(tile);
      }
      box.appendChild(block);
    }
  }

  /* The detail popup. Built on a tap and torn down on close, so nothing
   * here is ever rebuilt underneath the operator (the same discipline as
   * the panel's provenance window, #904). */
  async function openSegment(hour, slot) {
    closePopup();
    const frame = document.createElement("div");
    frame.className = "pv-popup";
    frame.innerHTML = '<div class="pv-popup-head"><b></b>'
      + '<button class="pv-mini" data-close="1">close</button></div>'
      + '<div class="pv-popup-body">reading the shelf...</div>';
    frame.querySelector("b").textContent =
      (slot.label || slot.kind || slot.id) + " - " + hour.label;
    frame.querySelector("[data-close]").onclick = closePopup;
    document.body.appendChild(frame);
    popup = frame;

    const body = frame.querySelector(".pv-popup-body");
    const route = "/api/schedule/segment?hour=" + encodeURIComponent(hour.key)
      + "&slot=" + encodeURIComponent(slot.id);
    try {
      const detail = await source.ask(route, { force: true });
      if (popup !== frame) return;
      body.replaceChildren();

      const summary = document.createElement("p");
      summary.className = "pv-hint";
      summary.textContent = detail.preparable
        ? ((detail.counts && detail.counts.candidates) || 0) + " prepared, "
          + ((detail.counts && detail.counts.ready) || 0) + " ready, "
          + Math.round(((detail.counts && detail.counts.seconds) || 0) / 60) + " min of audio"
        : (detail.why || "Nothing is prepared ahead for this kind of entry.");
      body.appendChild(summary);

      if (detail.pin_stale) {
        const warn = document.createElement("p");
        warn.className = "pv-blocker";
        warn.textContent = "The pinned candidate is gone - it aired, burned "
          + "or was discarded. The ordinary take will run.";
        body.appendChild(warn);
      }

      for (const card of (detail.candidates || []).slice(0, 12)) {
        const line = document.createElement("div");
        line.className = "pv-cand" + (card.pinned ? " pinned" : "")
          + (card.ready ? " ready" : "");
        const text = document.createElement("span");
        text.textContent = String(card.preview || card.label || card.id || "").slice(0, 220);
        const facts = document.createElement("em");
        facts.textContent = [card.lines ? card.lines + " lines" : "",
          card.seconds ? Math.round(card.seconds) + "s" : "",
          card.priority ? "priority " + card.priority : ""]
          .filter(Boolean).join(" · ");
        line.appendChild(text);
        line.appendChild(facts);

        const pin = document.createElement("button");
        pin.className = "pv-mini" + (card.pinned ? " on" : "");
        pin.textContent = card.pinned ? "unpin" : "pin";
        pin.title = "A pin is a PREFERENCE: if this has burned by the time "
          + "the entry comes round, the ordinary take airs anyway.";
        pin.onclick = () => segmentWrite("/api/schedule/segment/pin",
          { hour: hour.key, slot: slot.id, shelf_id: card.pinned ? null : card.id },
          hour, slot);
        line.appendChild(pin);

        const bump = document.createElement("button");
        bump.className = "pv-mini";
        bump.textContent = "that one next";
        bump.title = "Raise this candidate's priority without nailing it to an hour.";
        bump.onclick = () => segmentWrite("/api/schedule/segment/priority",
          { shelf_id: card.id, priority: 3 }, hour, slot);
        line.appendChild(bump);

        body.appendChild(line);
      }

      /* A past entry can hand over what actually went out in it, for two
       * hours (#920). probe=1 asks WITHOUT building anything, which is
       * the only honest way to offer the button. */
      if (slot.past) {
        const probe = await source.ask("/api/schedule/aired?probe=1&hour="
          + encodeURIComponent(hour.key) + "&slot=" + encodeURIComponent(slot.id),
          { force: true }).catch((error) => ({ ready: false, why: String(error.message || error) }));
        if (popup !== frame) return;
        const tape = document.createElement("p");
        tape.className = "pv-hint";
        tape.textContent = probe && probe.ready
          ? "A recording of this entry is kept for another "
            + Math.round((probe.keep_for || 0) / 60) + " min."
          : (probe && probe.why) || "No recording of this entry.";
        body.appendChild(tape);
      }
    } catch (error) {
      if (popup === frame) body.textContent = String(error.message || error);
    }
  }

  async function segmentWrite(route, body, hour, slot) {
    try {
      await api().post(route, body);
      source.forget("/api/schedule/segment?hour=" + encodeURIComponent(hour.key)
        + "&slot=" + encodeURIComponent(slot.id));
      source.forget(HOURS);
      hoursPrint = "";
      say("Saved.");
      openSegment(hour, slot);
    } catch (error) {
      say(String(error.message || error), true);
    }
  }

  function closePopup() {
    if (popup && popup.parentNode) popup.parentNode.removeChild(popup);
    popup = null;
  }

  /* ------------------------------------------------------------- script */

  let scriptPrint = "";

  function paintScript() {
    const box = el("pvScript");
    if (!box) return;
    const at = speaking && speaking.id
      ? rows.findIndex((row) => String(row.id) === String(speaking.id)) : -1;
    const from = at >= 0 ? Math.max(0, at - SCRIPT_BEFORE) : Math.max(0, rows.length - SCRIPT_AFTER);
    const shown = rows.slice(from, from + SCRIPT_BEFORE + SCRIPT_AFTER);
    const print = (speaking ? speaking.id : "") + "/" + shown.map((r) => r.id).join(",");
    if (print === scriptPrint) return;
    scriptPrint = print;

    box.replaceChildren();
    for (const row of shown) {
      const line = document.createElement("p");
      const live = speaking && String(row.id) === String(speaking.id);
      line.className = "pv-line" + (live ? " live" : "")
        + (row.lcdStatus === "Recorded / waiting" ? " waiting" : "");
      /* THE HOLD WORKS ON ANYTHING WEARING THIS. line-actions.js binds one
       * handler on the document and finds its target with
       * closest('[data-line]'), so a screen joins in by labelling its lines
       * and not by wiring anything. This pane never did, which is why a hold
       * on the Present view's script did nothing at all. */
      if (row.id) line.dataset.line = String(row.id);
      const who = document.createElement("b");
      who.textContent = (row.name || row.who || "booth") + ":";
      const text = document.createElement("span");
      text.textContent = row.text || "";
      line.appendChild(who);
      line.appendChild(text);
      box.appendChild(line);
      if (live) line.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  /* --------------------------------------------------------------- feed */

  /* WHICH ROWS ARE ALREADY ON SCREEN, for the life of this mount.
   *
   * The feed is append-only, and this is the thing that makes "a row never
   * moves once it is written" true ACROSS beats rather than only within
   * one. It was read at the top of paintFeed and never declared, so every
   * beat threw a ReferenceError out of paintFeed - and because the shared
   * feed swallows a subscriber's exception so that "a bad pane never stops
   * the beat", the throw also took the four things that run after it: the
   * wall, the running order, the gallery and the library. Five empty panes
   * off one undeclared name, with nothing on screen to say so.
   *
   * Reset by unmount(): a remount gets a fresh, empty list, and rows the
   * station is still carrying must be allowed to draw again. */
  let feedDrawn = Object.create(null);

  /* The station caps its own dialogue ring at 240 (app.py:25061). The list
   * is trimmed from the TOP to match, because the end is where the
   * conversation is. */
  const FEED_MOST = 240;

  /* Download the moment. /api/booth/clip cuts THIS turn out of the welded
   * round it aired in, which is closer than handing over the whole round
   * (app.py:102997), and the station caches the cut. The bytes come back
   * here rather than through a plain link because the link would carry no
   * bearer and, on the desktop, the page is file:// - so an <a href> to
   * the station is not a download, it is a navigation. */
  async function download(row) {
    say("cutting that moment...");
    try {
      const blob = await bytesOf("/api/booth/clip?line=" + encodeURIComponent(row.id));
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      /* The extension comes off what the station actually sent. Naming a
       * wav .mp3 because that is what the booth usually hands over is the
       * kind of small lie that only surfaces in somebody's editor. */
      const kind = String(blob.type || "").split("/")[1] || "mp3";
      link.download = "pinebox-" + String(row.id).replace(/[^\w.-]+/g, "-")
        + "." + kind.split(";")[0].replace("mpeg", "mp3");
      document.body.appendChild(link);
      link.click();
      link.remove();
      /* Revoked on the next beat, not immediately: revoking before the
       * browser has started reading it cancels the save. */
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      say("Saved.");
    } catch (error) {
      say(String(error.message || error), true);
    }
  }

  async function castVote(row, direction, note) {
    try {
      const done = await source.vote(row, direction, note);
      say(done.why);
      noteFor = "";
      /* In place. A voted row is already drawn, so it will never come back
       * through the fresh path - repainting the whole list would be the
       * "replacing the first entry" this pane was built to stop. */
      redrawFeedRow(row);
    } catch (error) {
      say(String(error.message || error), true);
    }
  }

  /* "Show me where this came from." Everything shown here is already on
   * the row - the writing model, the road it came off, the render and
   * whether it was ever cut. Nothing is asked of the station for it. */
  function provenance(row) {
    const trace = row.trace || {};
    const render = trace.render || {};
    return [
      row.lcdStatus,
      row.road_source ? "road: " + row.road_source : "",
      trace.model || (station && station.model) ? "written by "
        + (trace.model || station.model) : "",
      render.voice ? "voice " + render.voice : "",
      row.review_id ? "this wording was CUT once - review " + row.review_id : "",
      row.kind ? "kind " + row.kind : ""
    ].filter(Boolean).join("\n");
  }

  function paintFeed() {
    const list = el("pvFeed");
    if (!list) return;
    /* CHRONOLOGICAL, AND APPEND-ONLY.
     *
     * "I want each and every entry that's taking place to be happening in a
     * list that I'm able to scroll through... currently it's replacing the
     * first entry, which I don't want."
     *
     * It was newest-FIRST and rebuilt whole on every change, so each new
     * line landed on top and shoved the one being read downward - which is
     * exactly "replacing the first entry" from the other side of the glass.
     * An instant-message correspondence is the opposite on both counts:
     * oldest at the top, newest at the bottom, and a row never moves once
     * it is written.
     *
     * So rows are appended in the order they aired and the ones already on
     * screen are left alone. The station caps its own ring at 240
     * (app.py:25061), and the list is trimmed from the TOP to match - the
     * end is where the conversation is. */
    const atEnd = list.scrollTop + list.clientHeight >= list.scrollHeight - 40;
    const drawn = feedDrawn;
    const fresh = rows.filter((row) => row && row.id && !drawn[row.id]);
    /* A status can change on a row already drawn - "Recorded / waiting"
     * becoming "Playing". Repaint just that row's tag rather than the list. */
    for (const row of rows) {
      if (!row || !row.id || !drawn[row.id]) continue;
      const node = list.querySelector('[data-row="' + row.id + '"] em');
      if (node && node.textContent !== (row.lcdStatus || "")) {
        node.textContent = row.lcdStatus || "";
      }
      const owner = list.querySelector('[data-row="' + row.id + '"]');
      if (owner) owner.classList.toggle("playing", row.lcdStatus === "Playing");
    }
    /* The tally counts what the station is carrying, which moves even on a
     * beat that brings no new rows - so it is updated before the early
     * return, not after it. */
    paintFeedTally();
    if (!fresh.length) return;

    const fragment = document.createDocumentFragment();
    for (const row of fresh) {
      drawn[row.id] = true;
      fragment.appendChild(feedRow(row));
    }
    /* APPEND, not replace.
     *
     * This was list.replaceChildren(fragment), which kept the new rows and
     * threw away every row already on screen - which is "it's replacing the
     * first entry" exactly, from the other side of the glass, in the pane
     * whose own comment records that complaint as fixed. It was invisible
     * because paintFeed threw before ever reaching this line. */
    list.appendChild(fragment);
    while (list.childElementCount > FEED_MOST && list.firstElementChild) {
      list.removeChild(list.firstElementChild);
    }
    /* Follow the conversation only for a reader who was already at the end.
     * Someone who scrolled up to read something is not dragged back down. */
    if (atEnd) list.scrollTop = list.scrollHeight;
  }

  function paintFeedTally() {
    const tally = el("pvTally");
    if (!tally) return;
    const cut = rows.filter((row) => row.review_id).length;
    tally.textContent = rows.length + " lines"
      + (cut ? " · " + cut + " were cut once" : "");
  }

  /* Re-draw ONE row where it stands. The feed is append-only, so a row that
   * is already drawn never comes back through the fresh path; opening a
   * note box, or clearing one after a vote, has to replace the node in
   * place rather than wait for a beat that will never redraw it. */
  function redrawFeedRow(row) {
    const list = el("pvFeed");
    if (!list || !row || !row.id) return;
    const old = list.querySelector('[data-row="' + row.id + '"]');
    if (old) list.replaceChild(feedRow(row), old);
  }

  /* ONE row, built the same way wherever it is needed: appended by
   * paintFeed, or swapped in place by redrawFeedRow. */
  function feedRow(row) {
    const item = document.createElement("div");
    item.dataset.row = String(row.id || "");
    /* The feed rows too - they are lines that were said, same as the script
     * pane's, and the hold should not care which pane you reached for. */
    if (row.id) item.dataset.line = String(row.id);
    item.className = "pv-row" + (row.lcdStatus === "Playing" ? " playing" : "")
      + (row.review_id ? " cut" : "");
    const who = document.createElement("b");
    who.textContent = row.name || row.who || row.kind || "booth";
    const text = document.createElement("span");
    text.textContent = row.text || "";
    const tag = document.createElement("em");
    tag.textContent = row.lcdStatus || "";
    item.appendChild(who);
    item.appendChild(text);
    item.appendChild(tag);

    const tools = document.createElement("div");
    tools.className = "pv-tools";

    const grab = document.createElement("button");
    grab.className = "pv-mini";
    grab.textContent = "save";
    grab.title = "Download this moment, cut out of the round it aired in";
    grab.onclick = () => download(row);
    tools.appendChild(grab);

    const up = document.createElement("button");
    up.className = "pv-mini good";
    up.textContent = "^";
    up.title = row.review_id
      ? "Accept this wording - it goes to the review store the LCD uses, "
        + "and becomes a bounded example in future writing prompts."
      : "Up-vote. Filed where the station's votes already go (#76).";
    up.onclick = () => castVote(row, "up", "");
    tools.appendChild(up);

    const down = document.createElement("button");
    down.className = "pv-mini bad";
    down.textContent = "v";
    down.title = row.review_id
      ? "Keep this wording rejected."
      : "Down-vote. Filed where the station's votes already go (#76).";
    down.onclick = () => castVote(row, "down", "");
    tools.appendChild(down);

    const note = document.createElement("button");
    note.className = "pv-mini" + (noteFor === String(row.id) ? " on" : "");
    note.textContent = "note";
    note.title = "Say why, in the same breath as the vote";
    note.onclick = () => {
      const was = noteFor;
      noteFor = noteFor === String(row.id) ? "" : String(row.id);
      /* Close whichever box was open, then open this one - both in place,
       * so neither row moves. */
      if (was && was !== String(row.id)) {
        const other = rows.find((one) => one && String(one.id) === was);
        if (other) redrawFeedRow(other);
      }
      redrawFeedRow(row);
    };
    tools.appendChild(note);

    const why = document.createElement("button");
    why.className = "pv-mini";
    why.textContent = "?";
    why.title = "Show me where this came from";
    why.onclick = () => say(provenance(row));
    tools.appendChild(why);

    item.appendChild(tools);

    if (noteFor === String(row.id)) {
      const box = document.createElement("div");
      box.className = "pv-notebox";
      const field = document.createElement("input");
      field.placeholder = "why - this rides with the vote, not to a new store";
      const keep = document.createElement("button");
      keep.className = "pv-mini good";
      keep.textContent = "^ with note";
      keep.onclick = () => castVote(row, "up", field.value);
      const drop = document.createElement("button");
      drop.className = "pv-mini bad";
      drop.textContent = "v with note";
      drop.onclick = () => castVote(row, "down", field.value);
      box.appendChild(field);
      box.appendChild(keep);
      box.appendChild(drop);
      item.appendChild(box);
    }
    return item;
  }

  /* ------------------------------------------------------- gallery/wall */

  let galleryPrint = "";

  function paintGallery(payload) {
    const strip = el("pvGallery");
    if (!strip) return;
    const files = [];
    for (const row of (payload && payload.generations) || []) {
      if (!row || !Array.isArray(row.files)) continue;
      if (row.kind === "paper" || row.model === "gazette") continue;
      for (const name of row.files) {
        if (typeof name === "string" && /\.(png|jpe?g|webp)$/i.test(name)
          && !name.includes("..") && files.indexOf(name) < 0) files.push(name);
      }
      if (files.length >= 18) break;
    }
    const print = files.join(",");
    if (print === galleryPrint) return;
    galleryPrint = print;

    strip.replaceChildren();
    for (const name of files.slice(0, 18)) {
      const shot = document.createElement("img");
      shot.loading = "lazy";
      shot.src = absolute("/api/generations/image/" + encodeURIComponent(name));
      shot.alt = name;
      shot.title = name;
      strip.appendChild(shot);
    }
  }

  /* The wall's own bytes. pineDesktop.get parses JSON, so it cannot carry
   * a video; this is the same authenticated blob road the sampler uses for
   * audio, and it is what makes a clip seekable on a route with no Range
   * support. */
  async function fetchClip(url) {
    const blob = await bytesOf(url);
    return { src: URL.createObjectURL(blob), bytes: blob.size };
  }

  function releaseClip(clip) {
    if (clip && clip.src) URL.revokeObjectURL(clip.src);
  }

  let wallPrint = "";

  function paintWall(stamp) {
    const screen = el("pvWall");
    if (!screen || !wall) return;
    const state = wall.tick(stamp);
    const caption = el("pvWallSay");
    if (caption) {
      caption.textContent = state.ready
        ? state.label + " · " + state.file
        : state.error || state.note
          || (state.total ? "loading..."
            : "nothing in the gallery yet");
      caption.classList.toggle("bad", !!(state.error || state.note));
    }
    const count = el("pvWallCount");
    if (count) {
      /* Say what the shelf actually holds. "0 clips" over a picture is
       * confusing; "12 stills" explains why there is no motion. */
      const parts = [];
      if (state.clips) parts.push(state.clips + " clip" + (state.clips === 1 ? "" : "s"));
      if (state.stills) parts.push(state.stills + " still" + (state.stills === 1 ? "" : "s"));
      count.textContent = parts.length
        ? parts.join(" · ") + " · holding " + state.holding : "";
    }
    const still = el("pvWallStill");
    const print = state.file + ":" + state.revision;
    if (print === wallPrint) return;
    wallPrint = print;
    if (screen.pineResetFrame) screen.pineResetFrame();
    if (!state.ready) {
      screen.style.visibility = "hidden";
      screen.hidden = false;
      screen.removeAttribute("src");
      if (still) { still.removeAttribute("src"); still.hidden = true; }
      const poster = el("pvWallPoster");
      poster.classList.remove("actual");
      poster.src = absolute("/spark/asset/pinebox.png");
      poster.hidden = false;
      return;
    }
    if (state.still) {
      /* Stop the video first, or its last frame stays under the image and
       * its audio - if a clip ever has any - keeps running. */
      screen.pause();
      screen.removeAttribute("src");
      screen.hidden = true;
      el("pvWallPoster").hidden = true;
      if (still) { still.src = state.clip.src; still.hidden = false; }
      return;
    }
    if (still) { still.removeAttribute("src"); still.hidden = true; }
    screen.style.visibility = "hidden";
    const poster = el("pvWallPoster");
    poster.hidden = false;
    const posterUrl = state.poster_url || (state.clip && state.clip.poster_url);
    poster.classList.toggle("actual", !!posterUrl);
    poster.src = absolute(posterUrl || "/spark/asset/pinebox.png");
    screen.hidden = false;
    screen.src = state.clip.src;
    screen.play().catch(() => { /* an autoplay refusal is not a fault here */ });
  }

  /* --------------------------------------------------------------- beat */

  /* ONE handler, for every pane. Called ~4 times a second by the shared
   * feed's interpolation tick and once every four seconds with fresh
   * station state. The slow panes only ASK on a real poll, and the gate
   * turns most of those asks into a read of memory. */
  /* ONE PANE FAILING IS ONE PANE.
   *
   * The shared feed swallows a subscriber throw so that "a bad pane never
   * stops the beat" - but every pane on this view is the SAME subscriber,
   * so a throw in the fourth of them took the fifth, the cast, and all
   * three station asks with it. That is how one undeclared name emptied
   * the feed, the wall, the running order, the gallery and the library at
   * once, with nothing on screen and nothing in the log to say why: the
   * swallow sits upstream of everything it was hiding.
   *
   * So each pane runs on its own, and the first fault in each is said out
   * loud instead of discarded. Repeats are held down - a pane that is
   * broken is broken four times a second. */
  const paneFault = Object.create(null);

  function pane(name, run) {
    try {
      run();
    } catch (error) {
      const why = String((error && error.message) || error);
      if (paneFault[name] === why) return;
      paneFault[name] = why;
      try { console.error("[presentation] " + name + " pane: " + why, error); } catch (err) {}
      say(name + " pane stopped: " + why, true);
    }
  }

  function beat(payload) {
    const fresh = payload.kind === "poll" || payload.kind === "join";
    station = payload.station;
    rows = payload.rows || [];
    speaking = payload.now || null;
    beatAt = Number(payload.at) || Date.now();
    if (fresh) remainingAt = beatAt;

    pane("player", paintPlayer);
    pane("playlist", paintPlaylist);
    pane("script", paintScript);
    pane("feed", paintFeed);
    pane("wall", () => paintWall(payload.at));

    if (!fresh) return;

    pane("cast", () => { if (wall && station) wall.cast(station.dj_names || {}); });

    /* The asks are last and each is independent, so a running order the
     * station cannot answer for does not cost the gallery and the library
     * their content. */
    source.ask(HOURS).then((got) => pane("schedule", () => paintSchedule(got))).catch(() => {
      const box = el("pvHours");
      if (box && !box.childNodes.length) box.textContent = source.trouble(HOURS);
    });
    source.ask(GENERATIONS).then((got) => pane("gallery", () => paintGallery(got))).catch(() => {});
    source.ask(BROWSE).then((got) => pane("library", () => paintLibrary(got))).catch(() => {});
  }

  /* -------------------------------------------------------------- build */

  function build(target) {
    target.innerHTML =
      '<div class="pv-grid">'

      + '<section class="pv-player">'
      + '<img id="pvArt" class="pv-art" alt="">'
      + '<div class="pv-nowbox">'
      + '<b id="pvTitle"></b><span id="pvBy"></span>'
      + '<div class="pv-barwrap"><u id="pvBar"></u></div>'
      + '<div class="pv-transport">'
      + '<button id="pvPrev" class="pv-mini" title="Put the last record back and cut to it" aria-label="Put the last record back and cut to it">|&lt;</button>'
      + '<button id="pvNext" class="pv-mini" title="Skip to the next record now" aria-label="Skip to the next record now">&gt;|</button>'
      + '<button id="pvHear" class="pv-mini"></button>'
      + '<span id="pvClock" class="pv-clock"></span>'
      + '<span id="pvCast" class="pv-cast"></span>'
      + '<span id="pvBudget" class="pv-budget" title="The whole traffic '
      + 'budget for this screen: one shared poll, and at most one other '
      + 'question outstanding. 38 at once stalled the tablet for 46 seconds."></span>'
      + '</div></div></section>'

      + '<section class="pv-pane pv-playlist"><h3>Playlist</h3>'
      + '<div id="pvQueue" class="pv-queue"></div>'
      + '<div class="pv-libhead"><span>From the library</span>'
      + '<span id="pvLibraryTotal" class="pv-dim"></span></div>'
      + '<div id="pvLibrary" class="pv-library"></div></section>'

      + '<section class="pv-pane pv-schedule"><h3>Schedule</h3>'
      + '<div id="pvHours" class="pv-hours"></div></section>'

      + '<section class="pv-pane pv-scriptpane"><h3>Script</h3>'
      + '<div id="pvScript" class="pv-script"></div></section>'

      + '<section class="pv-pane pv-feedpane"><h3>Feed '
      + '<span id="pvTally" class="pv-dim"></span></h3>'
      + '<div id="pvFeed" class="pv-feed"></div></section>'

      + '<section class="pv-pane pv-wallpane"><h3>The wall '
      + '<span id="pvWallCount" class="pv-dim"></span></h3>'
      + '<div class="pv-wallbox">'
      + '<video id="pvWall" class="pv-video" muted playsinline></video>'
      + '<img id="pvWallPoster" class="pv-wallposter" alt="">'
      /* THE STILL SHARES THE BOX. The wall falls back to stills whenever
       * the station has no clips - measured: 40 gallery entries, zero of
       * them video - and a <video> cannot show a .png. Two elements, one
       * visible at a time, so neither has to pretend to be the other. */
      + '<img id="pvWallStill" class="pv-video" alt="" hidden>'
      /* THE TRANSITION SITS OVER THE ELEMENT WHILE IT HAS NO FRAME.
       * An empty <video> is painted by the browser with its own round play
       * badge, stretched to fill the box - the "oblong circle". No CSS the
       * page writes can touch that, so the element is hidden until it holds
       * a frame and this canvas covers the gap. */
      + '<canvas id="pvWallFx" class="pv-wallfx"></canvas>'
      + '<span id="pvWallSay" class="pv-wallsay"></span>'
      + '<button id="pvWallMode" class="pv-wallmode" '
      + 'title="Tap the picture to change what the wall shows">clips</button>'
      + '</div>'
      + '<div id="pvGallery" class="pv-gallery"></div></section>'

      + '</div><div id="pvNote" class="pv-note"></div>';

    const screen = el("pvWall");
    const wallPoster = el("pvWallPoster");
    wallPoster.src = absolute("/spark/asset/pinebox.png");
    wallPoster.addEventListener("error", () => {
      const fallback = absolute("/spark/asset/pinebox.png");
      wallPoster.classList.remove("actual");
      if (wallPoster.getAttribute("src") !== fallback) wallPoster.src = fallback;
    });
    /* The clip ENDS and the wall moves on. This is an element event, not
     * a timer - the module's own cap is only the backstop for a file that
     * never finishes. */
    screen.addEventListener("ended", () => { if (wall) wall.advance(); });
    screen.addEventListener("error", () => { if (wall) wall.advance(); });

    /* NEVER SHOW AN EMPTY VIDEO ELEMENT.
     *
     * The browser paints its own placeholder into an element with no
     * decodable frame - a round play badge scaled to fill the box, which is
     * the stretched circle that was on screen. It ignores object-fit
     * entirely, so the only cure is to keep the element hidden until it
     * genuinely holds a frame. The wall downloads each clip whole before
     * playing (that route has no Range support), so this gap is real and
     * worth filling with something deliberate. */
    const fx = el("pvWallFx");
    let transition = null;
    if (fx && root.PineWallTransition) {
      root.PineWallTransition.create(fx).then((made) => {
        transition = made;
        if (screen.readyState < 2) transition.start();
      });
    }
    let frameGeneration = 0;
    let firstTime = NaN;
    let framePending = false;
    let frameShown = false;
    const frameReady = () => screen.readyState >= 2
      && screen.videoWidth > 0 && screen.videoHeight > 0;
    const hideFrame = () => {
      frameGeneration += 1;
      firstTime = NaN;
      framePending = false;
      frameShown = false;
      screen.style.visibility = "hidden";
    };
    screen.pineResetFrame = hideFrame;
    const showWaiting = () => {
      hideFrame();
      if (screen.hidden) {
        wallPoster.hidden = true;
        if (transition) transition.stop();
        return;
      }
      wallPoster.hidden = false;
      if (transition) transition.start();
    };
    const showClip = () => {
      if (frameShown || !frameReady()) return;
      frameShown = true;
      screen.style.visibility = "visible";
      wallPoster.hidden = true;
      if (transition) transition.stop();
    };
    const armFrame = () => {
      if (!frameReady()) return;
      if (!Number.isFinite(firstTime)) firstTime = Number(screen.currentTime) || 0;
      if (typeof screen.requestVideoFrameCallback !== "function" || framePending) return;
      framePending = true;
      const token = frameGeneration;
      try {
        screen.requestVideoFrameCallback(() => {
          if (token !== frameGeneration) return;
          framePending = false;
          showClip();
        });
      } catch (err) { framePending = false; /* playback progress remains the fallback */ }
    };
    screen.addEventListener("loadstart", showWaiting);
    screen.addEventListener("emptied", showWaiting);
    screen.addEventListener("waiting", showWaiting);
    screen.addEventListener("loadeddata", armFrame);
    screen.addEventListener("playing", armFrame);
    screen.addEventListener("seeked", () => { if (!screen.seeking) showClip(); });
    screen.addEventListener("timeupdate", () => {
      if (!Number.isFinite(firstTime)) { armFrame(); return; }
      if (Number.isFinite(firstTime)
        && Number(screen.currentTime) > firstTime + 0.04) showClip();
    });
    showWaiting();

    /* TAP THE PICTURE TO CHANGE WHAT IT SHOWS.
     * "If I tap on the picture, allow me to cycle between it being a
     * slideshow of just videos or videos and images." Tapping the picture
     * itself, as asked - the little label only reports which it is. */
    const MODES = ["clips", "both", "stills"];
    const SAYS = {clips: "clips", both: "clips + stills", stills: "stills"};
    let mode = "clips";
    try { mode = localStorage.getItem("pineWallMode") || "clips"; }
    catch (err) { /* a locked store must not stop the wall */ }
    if (MODES.indexOf(mode) < 0) mode = "clips";

    const applyMode = () => {
      const label = el("pvWallMode");
      if (label) label.textContent = SAYS[mode];
      try { localStorage.setItem("pineWallMode", mode); } catch (err) { /* as above */ }
      if (wall && typeof wall.setMode === "function") wall.setMode(mode);
      /* Stills are drawn by the gallery strip under the wall, which is
       * already on screen; in stills-only the video element stands down
       * rather than holding a decoded clip nobody is watching. */
      if (mode === "stills") {
        try { screen.pause(); } catch (err) { /* not playing */ }
        showWaiting();
      } else if (wall) {
        wall.advance();
      }
    };

    screen.addEventListener("click", () => {
      mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
      applyMode();
      say("The wall is showing " + SAYS[mode] + ".");
    });
    const modeBtn = el("pvWallMode");
    if (modeBtn) modeBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      screen.click();
    });
    applyMode();

    el("pvPrev").onclick = async () => {
      try { await api().post("/api/dj/prev", {}); say("Back one."); }
      catch (error) { say(String(error.message || error), true); }
    };
    el("pvNext").onclick = async () => {
      try { await api().post("/api/dj/next", {}); say("Next record."); }
      catch (error) { say(String(error.message || error), true); }
    };
    el("pvHear").onclick = () => {
      const audio = shellAudio();
      if (!audio) return;
      if (audio.paused) audio.play().catch(() => say("This machine refused to play.", true));
      else audio.pause();
      paintPlayer();
    };
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closePopup();
    });
  }

  /* -------------------------------------------------------------- mount */

  async function mount(target) {
    if (!target || mounted) return;
    config = await api().readConfig();
    source = root.PinePresentationSource.create({
      get: (route) => api().get(route),
      post: (route, body) => api().post(route, body),
      subscribe: root.PineStationFeed ? (fn) => {
        return root.PineStationFeed.subscribeView
          ? root.PineStationFeed.subscribeView(target, fn)
          : root.PineStationFeed.subscribe(fn);
      } : null
    });
    wall = root.PineVideoWall.create({
      /* Through the gate, not around it - so the wall and the gallery
       * strip below it are ONE read of a log measured in hundreds of
       * records, not two. */
      get: (route) => source.ask(route),
      fetchClip,
      releaseClip,
      /* The SAME clock the beat runs on. The shared feed corrects for
       * network trip and for however far this machine's clock has wandered
       * from the box's (server_ms); a wall timing its clips off a second,
       * uncorrected clock would drift against everything else on screen. */
      now: () => (root.PineStationFeed ? root.PineStationFeed.clock() : Date.now())
    });
    host = target;
    build(target);
    leave = source.on(beat);
    source.start();
    mounted = true;
  }

  function unmount() {
    if (leave) leave();
    if (source) source.stop();
    if (wall) wall.destroy();
    closePopup();
    leave = null; wall = null; source = null; mounted = false;
    /* The drawn list belongs to the list that is about to be emptied. Carry
     * it into the next mount and every row the station is still holding
     * would be refused as "already drawn", and the feed would come back
     * blank until 240 new lines had aired. */
    feedDrawn = Object.create(null);
    noteFor = "";
    if (host) host.replaceChildren();
  }

  /* Built on first visit, not at boot. An unopened Presentation view
   * subscribes to nothing, decodes nothing and asks the station nothing -
   * which is the same bargain the Sampler makes. */
  function bootstrap() {
    const tab = document.getElementById("presentationTabBtn");
    const target = document.getElementById("presentation");
    if (!tab || !target) return;
    tab.addEventListener("click", () => {
      mount(target).catch((error) => {
        target.textContent = String(error.message || error);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap);
  } else {
    bootstrap();
  }

  root.PinePresentation = {
    mount,
    unmount,
    isMounted: () => mounted,
    source: () => source,
    wall: () => wall
  };
})(typeof window !== "undefined" ? window : globalThis);
