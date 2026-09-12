/* Listen - the station, lean-back.
 *
 * Every other view in this app is an instrument: something is measured,
 * something is pressed, something happens. This one is a radio on a
 * shelf. It is the view most likely to be left on a tablet for eight
 * hours in a room nobody is sitting in, and everything below follows from
 * that one fact rather than from a feature list.
 *
 * THE SPEC FOR THIS VIEW WAS A DRAFT, AND SO THIS HEADER IS THE DESIGN.
 *
 * The plan says, in full: "Lean-back and music-centric arrangements of the
 * same components: big now-playing, station clock, what's next, gallery
 * behind, volume, sleep timer, one-tap grab to the next free pad", and
 * then flags itself - "Inferred from the station's capabilities rather
 * than from your description - treat these two as a first draft." So each
 * of those seven words has been read as a question, and the answers are
 * written here where the operator can disagree with them:
 *
 *  1. BIG NOW-PLAYING SHOWS THE VOICE, NOT THE RECORD, when a voice is
 *     on. A record sits for three minutes; a spoken line lasts seconds
 *     and is the thing that just changed. Leading with the record makes
 *     the screen look frozen through every round of banter - which is
 *     most of what this station does. The record stays named underneath,
 *     with its own progress bar, so nothing is lost.
 *
 *  2. THE STATION CLOCK IS THE STATION'S CLOCK. It is drawn from
 *     server_ms (app.py:21821) corrected against this machine, not from
 *     Date.now(), so two terminals in two rooms cannot show different
 *     times for the same broadcast. Hours and minutes only: a seconds
 *     field is motion without meaning at reading distance.
 *
 *  3. WHAT'S NEXT prefers `coming` over the queue head. `coming` is a
 *     record being introduced but not yet started (app.py:25252, #176) -
 *     it exists so a screen does not leave the last track up as though it
 *     were still on, and it is what the pair are talking about right now.
 *
 *  4. GALLERY BEHIND IS STILLS, and it changes when the RECORD changes,
 *     never on a timer. That ties the picture to the station rather than
 *     to a stopwatch, and it bounds the image traffic at one request per
 *     song. /api/generations/image (app.py:112044) serves video too and
 *     has no Range support; the video wall belongs to the Presentation
 *     view, where somebody is watching it.
 *
 *  5. VOLUME IS THIS TERMINAL'S VOLUME. There is no per-listener level on
 *     the station; what exists is a routing table and each page's own
 *     desk. So this drives seams that already exist - the shell's own
 *     master slider, or PineTerminalAudio's desk - and never a station
 *     route. Turning the tablet down must not turn the kitchen down.
 *
 *  6. THE SLEEP TIMER SILENCES THIS TERMINAL AND NOTHING ELSE. Not the
 *     air-pause, not /api/dj/stop. The station is shared - a Nabu, a Pine
 *     Box, a public listen link, another terminal - and a tablet going to
 *     sleep on a bedside table must not take the show off the air for the
 *     house. The last 45 seconds fade rather than cut, because a radio
 *     that stops mid-word wakes you up.
 *
 *  7. ONE-TAP GRAB TAKES THE VOICE, NOT THE RECORD. See grabTarget() in
 *     listen-model.js: a four-minute track decodes to roughly 45 MB of
 *     PCM, and it is not a moment - it is in the library forever and is
 *     one tap away in the Music view. What the thumb is reaching for is
 *     the thing that was just SAID.
 *
 * THE SINGLE-POLLER RULE, WHICH IS WHY THERE IS NO FETCH LOOP IN HERE.
 *
 * Measured 2026-09-11: 38 concurrent requests in flight to the station
 * produced a 46-second media stall on the tablet - it played no audio at
 * all. This view therefore subscribes to window.PineStationFeed and
 * fetches nothing else on a clock. The feed polls /api/dj once every four
 * seconds and ticks locally at 250 ms, which is the cadence written into
 * the station itself (app.py:154692). The now-playing block, the
 * playhead, the on-air line, the queue and what's next all come off that
 * one payload; the gallery is fetched once at mount and again only when
 * the operator presses for it.
 *
 * Audio never happens in here either. The shell owns the player - two
 * players of one track, started at different moments, is the divergence
 * the operator already heard between the app and the Nabu, and the
 * station's own follower comment says so (app.py:154643, "ONE
 * DESTINATION"). This view reads the clock and moves the level. It does
 * not open a stream.
 */
(function (root) {
  "use strict";

  const api = () => root.pineDesktop;
  const model = () => root.PineListenModel;
  const sampler = () => root.PineSampler;

  /* A new backdrop at most this often, and only when the record changed.
   * A record is three to five minutes, so in practice this ceiling never
   * binds; it exists so a run of one-second tracks (a tape, a sting
   * sequence) cannot turn the gallery into a poller by accident. */
  /* "Cycle through the images in the background every three seconds, also
   * showing videos as a background element occasionally." Three seconds is
   * the operator's number; the paint already runs at 250ms, so this is a
   * clock check rather than a timer of its own. */
  const BACKDROP_REST_MS = 3000;
  /* One in five, so a clip is a punctuation rather than the medium. Videos
   * are decoded, not just painted: on a 4 GB tablet at 148 MB free, one at
   * a time and never two. */
  const CLIP_EVERY = 5;
  let backdropTurn = 0;
  let clips = [];

  let config = null;
  let mounted = false;
  let unsubscribe = null;

  let stills = [];
  let stillAt = 0;
  let stillTrack = "";
  let stillIndex = -1;

  let sleep = null;             /* the plan from model.sleepPlan(), or null */
  let volume = 1;
  let fadedTo = -1;             /* the last level the fade actually set */
  let lastGrab = "";
  let lastSpeakId = "";
  let grabBusy = false;

  const el = (id) => document.getElementById(id);

  /* Writing the same string into the DOM four times a second is work the
   * tablet does not need to do, and it also kills text selection and any
   * CSS transition mid-flight. Every paint goes through here. */
  function put(id, text) {
    const node = el(id);
    if (!node) return;
    const value = text == null ? "" : String(text);
    if (node.textContent !== value) node.textContent = value;
  }

  function absolute(path) {
    const url = String(path || "");
    if (/^https?:/i.test(url)) return url;
    const base = String((config && config.baseUrl) || "").replace(/\/+$/, "");
    return base + url;
  }

  /* ------------------------------------------------------------ the level */

  /* WHERE THE VOLUME KNOB ACTUALLY GOES.
   *
   * Three candidates, in order, and all three already exist - this adds
   * no audio path of its own:
   *
   *   1. #appVolume, the desktop shell's master slider. renderer.js
   *      listens for its `input` event and applies the level to the
   *      player and to every panel webview, so dispatching one is exactly
   *      what a hand on the slider does.
   *   2. PineTerminalAudio.setDesk, which drives the station panel's own
   *      djGainMusic / djGainVoice sliders. That is the road inside the
   *      tablet's WebView, where #appVolume does not exist.
   *   3. Nothing: no desk here. Say so rather than pretend the knob works.
   */
  function applyVolume(level) {
    const want = Math.max(0, Math.min(1, Number(level) || 0));
    const slider = el("appVolume");
    if (slider) {
      slider.value = String(Math.round(want * 100));
      slider.dispatchEvent(new Event("input", {bubbles: true}));
      return "app";
    }
    /* THE LAW OWNS THIS TOO. VOL is this terminal's own level - what the
     * drawer calls "Heard in this app" - and naming it the same way in both
     * places is the point of having one module. */
    const law = root.PineAudioLaw;
    if (law && law.setLocalVolume(want)) return "here";
    /* 3. THE PANEL'S OWN DESK, DIRECTLY.
     *
     * Inside the tablet's WebView there is no #appVolume and
     * PineTerminalAudio is not loaded, so both roads above miss and the
     * knob reported "there is no audio desk in this window to turn" while
     * sitting on a screen that was plainly playing music.
     *
     * But the desk IS there: djGainMusic is the panel's own music level
     * (djLevels, app.py:149377), and djApplyGain listens for its input
     * event - so moving it here is exactly what a hand on the panel's
     * slider does. This is the MUSIC level specifically, which is what was
     * asked for. */
    if (setPanelLevel("music", want)) return "panel";
    /* 4. The element itself. Always available, and it is this terminal's
     * music volume by definition. */
    const player = el("musicPlayer");
    if (player) {
      player.volume = want;
      try { localStorage.setItem("pineMusicVolume", String(want)); }
      catch (err) { /* a locked store must not stop the radio */ }
      return "player";
    }
    return "";
  }

  /* Move one of the panel's own desk sliders, the way a finger would.
   * Percentages: djLevels() divides by 100. */
  function setPanelLevel(stream, level) {
    const id = stream === "voice" ? "djGainVoice" : "djGainMusic";
    const input = el(id);
    if (!input) return false;
    input.value = String(Math.round(Math.max(0, Math.min(1, level)) * 100));
    input.dispatchEvent(new Event("input", {bubbles: true}));
    input.dispatchEvent(new Event("change", {bubbles: true}));
    return true;
  }

  function panelLevel(stream) {
    const input = el(stream === "voice" ? "djGainVoice" : "djGainMusic");
    if (!input) return null;
    const v = Number(input.value) / 100;
    return Number.isFinite(v) ? v : null;
  }

  /* Local silence. PineTerminalAudio.mute is the station's own rule for
   * this and deliberately spares the sampler - the operator's hands on a
   * pad are not the broadcast. Where that file is not loaded (the desktop
   * shell does not carry it), the same walk is done here rather than
   * inventing a different rule. */
  function silence(quiet) {
    const desk = root.PineTerminalAudio;
    if (desk && typeof desk.mute === "function") return desk.mute(document, quiet);
    let touched = 0;
    for (const node of document.querySelectorAll("audio, video")) {
      if (node.closest && node.closest("#sampler, .pb-sampler")) continue;
      if (node.muted !== quiet) { node.muted = quiet; touched += 1; }
    }
    return touched;
  }

  /* ---------------------------------------------------------- the backdrop */

  async function loadGallery(force) {
    try {
      /* 200 records, once. read_generations (app.py:5185) returns a
       * newest-first slice, so this is already weighted towards what the
       * station is making now without asking for the whole log. */
      const got = await api().get("/api/generations?limit=200");
      stills = model().galleryStills(got);
      /* The same log, kept for the moving ones. galleryStills drops these
       * deliberately - the LCD gallery excludes video and this view reuses
       * its rule - so they are picked out here rather than by changing a
       * helper two other screens depend on. */
      clips = [];
      for (const row of (got && got.generations) || []) {
        for (const file of (row && row.files) || []) {
          if (/\.(mp4|webm)$/i.test(String(file))) clips.push(String(file));
        }
      }
      if (force) { stillTrack = ""; stillAt = 0; }
      note(stills.length
        ? stills.length + " pictures behind the show"
        : "the gallery is empty");
    } catch (err) {
      stills = [];
      note("the gallery could not be read - the show is unaffected");
    }
  }

  /* One <img>, replaced. Not a stack, not a crossfade of decoded frames:
   * this screen runs for hours on a 4 GB tablet and the LCD gallery's own
   * discipline (hold the current and at most one more) is the reason it
   * survives. The CSS fades opacity on the single element instead. */
  function paintBackdrop(state, at) {
    if (!stills.length) return;
    /* Cycles on its own clock now, not on the track: a record sits for
     * three minutes and the backdrop should not. */
    if (at - stillAt < BACKDROP_REST_MS) return;
    stillTrack = String((state.now || {}).id || "");
    stillAt = at;
    backdropTurn += 1;

    const still = el("plBack");
    const vid = el("plBackVid");

    /* Occasionally, a moving one. */
    if (clips.length && vid && backdropTurn % CLIP_EVERY === 0) {
      const pick = clips[Math.floor(Math.random() * clips.length)];
      vid.src = absolute("/api/generations/image/" + encodeURIComponent(pick));
      /* HIDDEN UNTIL IT HAS A FRAME. The plexus covers the download, which
       * is a real wait: that route has no Range support, so the clip comes
       * whole before a single frame exists. */
      vid.hidden = true;
      showPlexus(true);
      vid.onloadeddata = () => {
        vid.hidden = false;
        showPlexus(false);
        if (still) still.style.opacity = "0";
      };
      vid.play().catch(() => {
        /* Autoplay refused, or the clip will not decode. Fall back to a
         * still rather than leaving a black rectangle behind the show. */
        vid.hidden = true;
        showPlexus(false);
        if (still) still.style.opacity = "";
      });
      return;
    }

    showPlexus(false);
    if (vid && !vid.hidden) {
      vid.pause();
      vid.hidden = true;
      vid.removeAttribute("src");
      /* Let go of the decoded frames; this screen runs for hours. */
      try { vid.load(); } catch (err) { /* nothing to release */ }
    }
    if (still) still.style.opacity = "";
    stillIndex = (stillIndex + 1) % stills.length;
    if (!still) return;
    /* An <img> cannot carry an Authorization header - the same reason the
     * station signs its media URLs (app.py:12213) - and this route is
     * open to reads. If SPARK_AGENT_LOCK_READS is ever set this backdrop
     * goes dark, which is cosmetic and deliberate: nothing else on this
     * screen depends on it. */
    swapStill(absolute("/api/generations/image/"
      + encodeURIComponent(stills[stillIndex])));
  }

  /* A GRACEFUL CHANGE, NOT A CUT.
   *
   * "I want the transitions to be smooth... graceful and gradual. In fact,
   * whenever it transitions to the other image, I want that image to be
   * slowly panning and moving on the screen, scaling in or zooming out."
   *
   * This was a bare `node.src = ...` on ONE element - no fade, no
   * preload, nothing. The picture changed between two frames, which is
   * precisely what reads as a flash, and a gallery still here is over a
   * megabyte so the element had nothing to show while it arrived.
   *
   * Two layers instead: decode the next picture completely, fade it in
   * over the one already there, then swap which is which. The screen is
   * never without a picture, so there is nothing to flash. Each arrival
   * also gets a slow drift, alternating direction, so the backdrop is
   * always gently moving rather than sitting still between cuts - the
   * animation is CSS, on the compositor, where it costs this tablet
   * nothing.
   */
  let backLayers = [];
  let backFront = 0;
  let backDrift = 0;

  function swapStill(src) {
    const first = el("plBack");
    if (!first) return;
    if (!backLayers.length) {
      /* IDEMPOTENT. Measured: four .pl-back layers where there should be
       * two, because a remount resets this module's `backLayers` while the
       * element it cloned last time is still in the document. Look for the
       * partner by id rather than trusting a variable that does not
       * survive what the DOM does. */
      let second = document.getElementById("plBack2");
      if (!second) {
        second = first.cloneNode(false);
        second.id = "plBack2";
        second.style.opacity = "0";
        first.parentNode.insertBefore(second, first.nextSibling);
      }
      backLayers = [first, second];
    }
    const under = backLayers[1 - backFront];
    const over = backLayers[backFront];

    const pre = new Image();
    pre.onload = () => {
      under.src = src;
      backDrift = (backDrift + 1) % 4;
      under.className = first.className.replace(/ *pl-drift-[0-9]/g, "")
        + " pl-drift-" + backDrift;
      under.style.opacity = "1";
      over.style.opacity = "0";
      backFront = 1 - backFront;
    };
    /* A still that will not load is skipped rather than shown as a hole. */
    pre.onerror = () => { /* the next turn will try another */ };
    pre.src = src;
  }

  /* --------------------------------------------------------------- paint */

  function note(text, bad) {
    const node = el("plNote");
    if (!node) return;
    node.textContent = text || "";
    node.classList.toggle("bad", !!bad);
  }

  /* MAKE THE HEADLINE FIT THE SPACE IT HAS.
   *
   * "Make sure this header text is scaled appropriately to be big enough
   * to show all of the text. As you can see, it's cut off... dynamically
   * rescale that element to have it encompass all the text it intends to
   * say."
   *
   * CSS cannot do this. `font-size: clamp(22px, 4.4vw, 64px)` scales with
   * the VIEWPORT, which knows nothing about how long this particular title
   * is, and `-webkit-line-clamp` then hides the overflow - so
   * "The Prince That Was Promised (from \"House of the Dragon\")" was cut
   * through the middle of its second line. A short title and a long one
   * were being given the same type size and the long one lost.
   *
   * So the size is measured down until the text fits its box: start at the
   * size the stylesheet asked for, step down, stop as soon as it fits. A
   * floor, because a title shrunk to nothing is no more readable than one
   * cut in half - below it the text wraps to more lines instead, which the
   * box can absorb.
   *
   * Cheap enough to run on every headline change: the loop is bounded at
   * ~14 steps and only touches one element's font-size. */
  let fitFrame = 0;
  function fitHead() {
  cancelAnimationFrame(fitFrame);
  /* After layout, or every measurement is of the PREVIOUS headline. */
  fitFrame = requestAnimationFrame(() => {
    const head = el("plHead");
    if (!head || !head.textContent) return;
    head.style.fontSize = "";
    const want = parseFloat(getComputedStyle(head).fontSize) || 32;
    const floor = Math.max(15, want * 0.42);
    const box = head.parentElement;
    if (!box) return;
    /* The room the headline may use: its own box, less whatever else is
     * already in there. Measured rather than assumed, because the row
     * beneath it appears and disappears with the kind of thing on air. */
    const room = box.clientHeight
      - Array.from(box.children).reduce(
        (sum, node) => sum + (node === head ? 0 : node.offsetHeight), 0);
    if (!(room > 0)) return;
    let size = want;
    head.style.fontSize = size + "px";
    let guard = 0;
    while (head.scrollHeight > room && size > floor && guard < 24) {
      size = Math.max(floor, size * 0.92);
      head.style.fontSize = size + "px";
      guard += 1;
    }
    /* At the floor it still may not fit, and that is the case where
     * more lines beat smaller type - the clamp is lifted rather than
     * the title being cut. */
    head.style.webkitLineClamp = head.scrollHeight > room ? "unset" : "";
  });
  }

  function paint(payload) {
    const state = payload.station || {};
    const at = payload.at || Date.now();
    const m = model();
    const now = m.nowPlaying(state, payload.now, at);
    const next = m.whatsNext(state);

    put("plStation", state.station_name || state.station || "Pine Box FM");
    put("plClock", m.wallClock(at));

    const host = el("plNow");
    if (host) {
      host.classList.toggle("voice", now.kind === "voice");
      host.classList.toggle("quiet", now.kind === "quiet");
    }
    put("plHead", now.headline);
    fitHead();
    const rec = state.now || {};
    votedTrack = {id: rec.id || "", title: rec.track || rec.title || ""};
    put("plSub", now.sub || now.why);

  /* The record underneath. When a voice has the headline this is the
     * only place the track is named, so it is never hidden - it goes
     * dim, not away. */
    const under = el("plUnder");
    if (under) under.hidden = !now.track;
    /* The cover. Only swapped when the TRACK changes - assigning src on
     * every paint would refetch the image four times a second. */
    const art = el("plArt");
    if (art) {
      const want = (now.track && now.track.art) || "";
      if (art.dataset.want !== want) {
        art.dataset.want = want;
        if (want) { art.src = want; art.hidden = false; }
        else { art.removeAttribute("src"); art.hidden = true; }
      }
      /* A cover that 404s should leave no broken-image box behind. */
      art.onerror = function () { art.hidden = true; };
    }

    if (now.track) {
      put("plTrack", now.track.title);
      put("plArtist", [now.track.artist, now.track.album]
        .filter(Boolean).join(" · "));
    }

    const bar = now.bar;
    const fill = el("plFill");
    if (fill) fill.style.width = (bar.following ? bar.fraction * 100 : 0) + "%";
    put("plTime", bar.following && bar.length
      ? m.clockText(bar.position) + " / " + m.clockText(bar.length)
      : "");
    const bars = el("plBar");
    if (bars) bars.classList.toggle("paused", !!bar.paused);

    put("plNextWhen", next.when === "introducing" ? "being introduced"
      : next.when === "queued" ? "next" : "nothing queued");
    put("plNextWhat", next.title
      ? next.title + (next.artist ? " - " + next.artist : "")
      : "the pair choose as they go");
    put("plNextTally", next.queued
      ? next.queued + " queued" + (next.requests
        ? " · " + next.requests + " asked for" : "")
      : "");

    paintSleep(at);
    paintGrab(payload);
    paintBackdrop(state, at);
  }

  function paintSleep(at) {
    const m = model();
    const tick = m.sleepTick(sleep, at);
    const node = el("plSleepLeft");
    if (tick.state === "off") {
      if (node) node.textContent = "";
      return;
    }
    if (node) {
      const mins = Math.floor(tick.left / 60);
      const secs = Math.floor(tick.left % 60);
      node.textContent = mins > 0
        ? mins + " min" + (tick.state === "fading" ? " · fading" : "")
        : secs + "s · fading";
    }
    /* IN STEPS, NOT ON EVERY TICK. applyVolume() dispatches an `input` on
     * the shell's master slider, and renderer.js answers that by writing
     * localStorage AND running executeJavaScript in every panel webview.
     * Four of those a second for forty-five seconds is a few hundred
     * round trips to make a radio quieter. Five percent at a time is
     * about twenty, and no ear can hear the difference. */
    if (tick.state === "fading") {
      const step = Math.round(volume * tick.gain * 20) / 20;
      if (step !== fadedTo) { fadedTo = step; applyVolume(step); }
    }
    if (tick.state === "done") {
      sleep = null;
      fadedTo = -1;
      /* Silence by MUTING, then put the level back where the operator had
       * it. Leaving the master at zero would be a quiet booby trap: every
       * other view in the app would also be silent in the morning, with
       * nothing on screen to say why. Mute is a lever with an obvious
       * opposite; a zeroed slider looks like a setting. */
      silence(true);
      applyVolume(volume);
      document.querySelectorAll(".pl-sleep button")
        .forEach((b) => b.classList.remove("on"));
      note("Asleep. The station is still on air - this terminal is not. "
        + "Press off to wake it.");
    }
  }

  /* Greyed with the sampler's OWN answer, not a guess. takeable() is
   * published from sampler.js for exactly this; reading `aired` instead
   * is the mistake that once offered 7 of ~220 takeable moments. */
  function paintGrab(payload) {
    const button = el("plGrab");
    if (!button) return;
    if (grabBusy) return;
    /* grabTarget() walks the whole 240-row ring and asks sampler.js's
     * sourceFor() about each row. Doing that four times a second on a
     * 4 GB tablet is work nobody asked for, and the answer changes for
     * only two reasons: a new poll brought new rows, or the local 250 ms
     * interpolation moved on to the next turn of the round. Anything
     * else is a repeat of the same scan. */
    const speakId = String((payload.now || {}).id || "");
    if (payload.kind === "tick" && speakId === lastSpeakId) return;
    lastSpeakId = speakId;
    const s = sampler();
    const target = model().grabTarget(payload.rows || [], payload.now,
      s ? s.takeable : null, payload.at);
    button.disabled = !target.row;
    button.title = target.row
      ? "Keep " + target.why + " - it lands on the next free sampler pad"
      : target.why;
    put("plGrabWhy", lastGrab || (target.row ? target.why : ""));
  }

  async function doGrab(payload, say) {
    const tell = typeof say === "function" ? say : note;
    const s = sampler();
    if (!s || typeof s.grab !== "function") {
      tell("The sampler is not loaded in this window.", true);
      return;
    }
    const target = model().grabTarget(payload.rows || [], payload.now,
      s.takeable, payload.at);
    if (!target.row) { tell(target.why, true); return; }
    grabBusy = true;
    lastGrab = "";
    const button = el("plGrab");
    if (button) { button.disabled = true; button.classList.add("working"); }
    tell("taking " + target.why + "…");
    try {
      const result = await s.grab(target.row);
      lastGrab = result.why;
      tell(result.ok
        ? "Kept on " + result.why + " - open the Sampler to play it."
        : result.why, !result.ok);
    } finally {
      grabBusy = false;
      if (button) { button.disabled = false; button.classList.remove("working"); }
    }
  }

  /* --------------------------------------------------------------- build */

  function build(host) {
    host.innerHTML = "";
    host.innerHTML =
      '<img id="plBack" class="pl-back" alt="">'
      /* A video layer behind the show, used occasionally. Muted and
       * playsinline: this is wallpaper, and a backdrop that made noise
       * would be a second voice over the station. */
      + '<video id="plBackVid" class="pl-back pl-back-vid" muted playsinline loop hidden></video>'
      /* The plexus stands in whenever the clip has no frame. An empty
       * <video> is painted by the browser with its own play badge stretched
       * across the box - the thing the operator asked never to see again -
       * and object-fit cannot touch it. */
      + '<canvas id="plBackFx" class="pl-back pl-back-fx"></canvas>'
      + '<div class="pl-shade"></div>'
      + '<div class="pl-face">'
      + '<div class="pl-top"><b id="plStation">Pine Box FM</b>'
      /* THE GRAB PAD LIVES UP HERE, beside the clock, which is where the
       * operator pointed at it. Not in the transport row: it does not change
       * what is playing, it keeps it - and the top right is the one corner
       * of this view that is never covered by the artwork or the headline. */
      + '<button id="plPad" class="pl-pad" title="Tap: keep the whole of '
      + 'what is playing. Double tap: the last twenty seconds.">'
      + '<i></i><b>grab</b><span id="plPadSay"></span></button>'
      + '<i id="plClock" class="pl-clock">--:--</i></div>'

      + '<div id="plNow" class="pl-now">'
      + '<p id="plHead" class="pl-head"></p>'
      + '<p id="plSub" class="pl-sub"></p>'
      + '</div>'

      /* There is no separate "on air" strip. The line being spoken IS
       * the headline (see design note 1), and a second copy of it
       * underneath was the first draft of this markup - it read as the
       * station saying everything twice. The speaker's name goes in the
       * subtitle instead, which is where nowPlaying() already puts it. */
      /* 1 - THE ALBUM ART. The record's own cover, from the station's
       * /music/<id>/art. It sits beside the headline rather than behind it:
       * the backdrop is already the gallery, and a cover competing with a
       * gallery still is two pictures and no subject. */
      + '<img id="plArt" class="pl-art" alt="" hidden>'

      /* 2 and 3 - THE METERS. Real levels off the real audio (PineMeters),
       * music and voices on their own row each, because the operator asked
       * to see the two separately - which is also the quickest way to see
       * that the DJs are arriving at all. */
      + '<div class="pl-meters">'
      + '<div class="pl-meter"><span>music</span>'
      + '<canvas id="plMeterMusic"></canvas></div>'
      + '<div class="pl-meter"><span>djs</span>'
      + '<canvas id="plMeterVoice"></canvas></div>'
      + '<i id="plMeterNote" class="pl-meter-note"></i></div>'

      + '<div id="plUnder" class="pl-under" hidden>'
      + '<div class="pl-underline"><b id="plTrack"></b>'
      + '<em id="plArtist"></em></div>'
      + '<div id="plBar" class="pl-bar"><u id="plFill"></u></div>'
      + '<i id="plTime" class="pl-time"></i></div>'

      + '<div class="pl-next"><span id="plNextWhen">next</span>'
      + '<b id="plNextWhat"></b><em id="plNextTally"></em></div>'

      + '<div class="pl-controls">'
      /* THE REQUEST BOX.
       *
       * "Search for any of my songs... auto suggesting searches based on
       * what I'm searching for and keeps a history of it. I'm able to tap it
       * and instantly begin playing that song so that way I can use this as
       * a request box."
       *
       * Two routes that already exist: GET /api/music/search?q= over 35,982
       * tracks, and POST /api/dj/request {q, now}. `now` inserts at the head
       * and cuts the current record - which is what "instantly" means, and
       * is why it is only ever sent from a deliberate tap on a result. */
      + '<div class="pl-searchwrap">'
      + '<input id="plSearch" class="pl-search" type="search" '
      + 'placeholder="search the library and request it" '
      + 'autocomplete="off" spellcheck="false">'
      + '<div id="plHits" class="pl-hits" hidden></div></div>'
      + '<span id="plVote"></span>'
      + '<button id="plDeskBtn" class="pl-deskbtn" title="Levels and meters">'
      + '<svg viewBox="0 0 24 24" aria-hidden="true">'
      + '<path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h13"/>'
      + '<circle cx="15" cy="7" r="2"/><circle cx="9" cy="12" r="2"/>'
      + '<circle cx="19" cy="17" r="2"/></svg></button>'
      + '<label class="pl-vol" title="This terminal\'s level. The station '
      + 'has no per-listener volume - this moves the desk this device '
      + 'already has, and changes nothing in any other room.">'
      + '<span>vol</span>'
      + '<input id="plVol" type="range" min="0" max="100" step="1" value="100">'
      + '</label>'
      + '<div class="pl-sleep" title="Silences THIS terminal when it '
      + 'expires - the station stays on air for everyone else. The last '
      + '45 seconds fade rather than cut.">'
      + '<span>sleep</span>'
      + '<button data-mins="15">15</button>'
      + '<button data-mins="30">30</button>'
      + '<button data-mins="60">60</button>'
      + '<button data-mins="0">off</button>'
      + '<i id="plSleepLeft"></i></div>'
      + '<button id="plGrab" class="pl-grab" title="Keep this moment">'
      + 'keep this</button>'
      + '<i id="plGrabWhy" class="pl-grabwhy"></i>'
      + '<button id="plPics" class="pl-pics" title="Fetch the gallery '
      + 'again. Not a poller: this view asks for pictures once at mount '
      + 'and then only when you press this.">pictures</button>'
      + '</div>'
      /* HOLD THE KNOB TO SEE THE WHOLE DESK.
       * "If I tap and hold it, expand it out showing all the slider for the
       * audio, allowing me to adjust the levels of the DJs, the just the
       * levels of the music." Hidden until asked for: one knob is the right
       * answer nine times out of ten, and three is the right answer when it
       * is not. */
      + '<div id="plDesk" class="pl-desk" hidden>'
      /* 0-200%, not 0-100. These drive the panel's own gains, whose unity
       * is 100 and whose voice bus sits at 160 by default - a 0-100 knob
       * could not even represent where the desk already was, let alone
       * reach it. */
      + '<label class="pl-deskrow"><span>music</span>'
      + '<input id="plDeskMusic" type="range" min="0" max="200" step="1">'
      + '<i id="plDeskMusicVal"></i></label>'
      + '<label class="pl-deskrow"><span>djs</span>'
      + '<input id="plDeskVoice" type="range" min="0" max="200" step="1">'
      + '<i id="plDeskVoiceVal"></i></label>'
      + '<label class="pl-deskrow" title="How far the music dips while a '
      + 'voice is talking. This is the one that decides whether you can '
      + 'hear them over a record."><span>duck</span>'
      + '<input id="plDeskReply" type="range" min="0" max="90" step="1">'
      + '<i id="plDeskReplyVal"></i></label>'
      + '<label class="pl-deskrow"><span>here</span>'
      + '<input id="plDeskLocal" type="range" min="0" max="100" step="1">'
      + '<i id="plDeskLocalVal"></i></label>'
      + '<i class="pl-deskwhy">This terminal only. The station has no '
      + 'per-listener level; these are the desk this panel already has.</i>'
      + '</div>'
      + '<p id="plNote" class="pl-note"></p>'
      + '</div>';
  }

  function wire() {
    const vol = el("plVol");
    if (vol) {
      try {
        const saved = Number(localStorage.getItem("pineListenVolume"));
        if (Number.isFinite(saved) && saved > 0) volume = Math.min(1, saved);
      } catch (err) { /* a locked store must not stop the radio */ }
      vol.value = String(Math.round(volume * 100));
      vol.addEventListener("input", () => {
        volume = Number(vol.value) / 100;
        try { localStorage.setItem("pineListenVolume", String(volume)); }
        catch (err) { /* as above */ }
        const where = applyVolume(volume);
        note(where ? "" : "there is no audio desk in this window to turn.",
          !where);
      });
    }

    document.querySelectorAll(".pl-sleep button").forEach((button) => {
      button.addEventListener("click", () => {
        const mins = Number(button.dataset.mins);
        document.querySelectorAll(".pl-sleep button")
          .forEach((b) => b.classList.remove("on"));
        if (!mins) {
          sleep = null;
          fadedTo = -1;
          /* Coming back from a finished timer has to undo BOTH halves -
           * the mute AND the faded level - or the radio stays silent and
           * looks broken with a full slider. */
          silence(false);
          applyVolume(volume);
          note("Sleep timer off.");
          return;
        }
        button.classList.add("on");
        fadedTo = -1;
        silence(false);
        applyVolume(volume);
        sleep = model().sleepPlan(mins, Date.now());
        note("Asleep in " + mins + " minutes - this terminal only.");
      });
    });

    const grab = el("plGrab");
    if (grab) {
      grab.addEventListener("click", () => {
        const feed = root.PineStationFeed;
        doGrab({rows: feed.rows(), now: feed.now(), at: feed.clock()});
      });
    }
    const pics = el("plPics");
    if (pics) pics.addEventListener("click", () => loadGallery(true));
    wireDesk();
    wireVotes();
    wireSearch();
    startMeters();
  }

  /* HOLD TO OPEN THE DESK.
   *
   * 420ms, and pointer events rather than touch: the same gesture has to
   * work under a finger and a mouse, and the sampler learned the hard way
   * that touch-only handlers leave the desktop inert. A drag of the knob
   * cancels the hold, or adjusting the volume would keep opening a panel
   * nobody asked for. */
  /* WHAT IS ON, for the vote arrows. Kept up to date by paint(); the
   * arrows read it through a function so they always vote on the record
   * that is actually playing rather than the one that was. */
  let votedTrack = {};

  function wireVotes() {
    const seat = el("plVote");
    if (!seat || !root.PineVote) return;
    root.PineVote.mount(seat, () => votedTrack, (text, bad) => note(text, bad));
  }

  function wireDesk() {
    const vol = el("plVol");
    const desk = el("plDesk");
    if (!vol || !desk) return;
    /* THE ICON OPENS IT; A TAP ANYWHERE ELSE CLOSES IT.
     * Holding the volume knob still works - it was the first way in and
     * costs nothing to keep - but the button is the one that is findable. */
    const open = (want) => {
      desk.hidden = want === undefined ? !desk.hidden : !want;
      if (!desk.hidden) paintDesk();
      const btn = el("plDeskBtn");
      if (btn) btn.classList.toggle("on", !desk.hidden);
    };

    const btn = el("plDeskBtn");
    if (btn) btn.addEventListener("click", (event) => {
      event.stopPropagation();
      open();
    });
    /* TAP AWAY CLOSES IT - through PineDismiss, not a document click.
     *
     * This used to be a bubble-phase `click` on document, and it did not
     * work: the backdrop swallows taps to cycle stills and video, the feed
     * rows swallow taps to open a line, and the desk itself swallows them
     * so moving a slider does not close the panel. Tap any of those and
     * the close never ran. PineDismiss listens in the CAPTURE phase, so
     * nothing downstream can make the overlay unclosable. */
    if (root.PineDismiss) {
      root.PineDismiss.watch(desk, () => open(false), [() => el("plDeskBtn")]);
    } else {
      desk.addEventListener("click", (event) => event.stopPropagation());
      document.addEventListener("click", () => { if (!desk.hidden) open(false); });
    }

    let timer = 0;
    const cancel = () => { clearTimeout(timer); timer = 0; };
    vol.addEventListener("pointerdown", () => {
      cancel();
      timer = setTimeout(() => open(true), 420);
    });
    ["pointerup", "pointercancel", "pointerleave", "input"]
      .forEach((name) => vol.addEventListener(name, cancel));

    /* ---- the grab pad -------------------------------------------------
     *
     * "Offer a sampler pad on the listen view that if I tap on it, it places
     *  the currently playing sound on a pad. And if I double tap it, it
     *  places the last twenty seconds on a pad. And anytime I tap it, it
     *  places that currently playing audio in full, the full clip, on a pad.
     *  And then if it is full, it increments over to the next series of pads."
     *
     * ONE TAP AND TWO TAPS ARE DIFFERENT RECORDINGS, not two ways to the
     * same one: the full thing is a FILE off the station, the twenty seconds
     * is the ring in this page. So a tap has to wait long enough to know
     * which it is. 260 ms is the usual double-tap window and it is short
     * enough that the single tap still feels immediate.
     */
    const pad = el("plPad");
    if (pad) {
      let taps = 0;
      let tapTimer = 0;
      const say = (words, bad) => {
        const out = el("plPadSay");
        if (out) {
          out.textContent = words || "";
          out.classList.toggle("bad", !!bad);
        }
        if (words) setTimeout(() => { if (out && out.textContent === words) out.textContent = ""; }, 6000);
      };
      pad.addEventListener("click", (event) => {
        event.stopPropagation();
        taps += 1;
        if (tapTimer) return;
        tapTimer = setTimeout(async () => {
          const many = taps;
          taps = 0;
          tapTimer = 0;
          pad.classList.add("busy");
          try {
            if (many >= 2) await grabLastSeconds(say);
            else await grabWholeOfNow(say);
          } finally {
            pad.classList.remove("busy");
          }
        }, 260);
      });
    }

    /* Talk only: a STATION route, not a level. */
    const talk = el("plTalkOnly");
    if (talk) talk.addEventListener("click", async () => {
      const was = talk.textContent;
      talk.textContent = "...";
      try {
        const law = root.PineAudioLaw;
        const state = root.PineStationFeed && root.PineStationFeed.state
      ? (root.PineStationFeed.state() || {}) : {};
        await law.talkOnly(!law.isTalkOnly(state), state);
        paintDesk();
      } catch (err) {
        talk.textContent = String(err.message || err).slice(0, 26);
        setTimeout(() => { talk.textContent = was; }, 2000);
      }
    });

    /* THE DRAWER IS THE LAW, and these are the same controls.
     *
     * They used to move the PANEL's djGainMusic / djGainVoice - this
     * browser's own gain - while the drawer wrote the STATION's
     * <stream>_level for every listener. Two desks over two different
     * numbers, which is why a level set in one place appeared to do nothing
     * in the other. PineAudioLaw is now the only door to both, and it is
     * explicit about which is which. */
    const rows = [
      ["plDeskMusic", "music", "plDeskMusicVal"],
      ["plDeskVoice", "voice", "plDeskVoiceVal"],
      ["plDeskReply", "duck", "plDeskReplyVal"]
    ];
    for (const [id, stream, out] of rows) {
      const input = el(id);
      if (!input) continue;
      /* ON `input`, AND IT MOVES THE SOUND AS IT MOVES.
       *
       * This used to write the STATION's level on `change` - a broadcast
       * decision for every listener - while wearing a label that said "this
       * terminal only". On a tablet the station never publishes those levels
       * back, so the knob read "not set", sat at 50, and appeared dead.
       *
       * A monitoring balance has to answer under the thumb, so it is driven
       * live. There is no per-pixel cost to pay: this writes a gain node in
       * this page, not a request. */
      input.addEventListener("input", () => {
        const law = root.PineAudioLaw;
        const label = el(out);
        const moved = law && law.setLocalMix
          ? law.setLocalMix(stream, Number(input.value)) : false;
        if (label) {
          label.textContent = input.value + "%" + (moved ? "" : " (no desk here)");
        }
      });
      /* The desktop renderer has no panel gains of its own, so there the
       * knob still means the station - which is the only desk it can reach.
       * Kept on `change` there for the reason it always was: a drag would
       * post one write per pixel. */
      input.addEventListener("change", async () => {
        const law = root.PineAudioLaw;
        if (!law) return;
        if (law.localMix && law.localMix(stream) !== null) return;
        if (stream === "duck") return;
        try {
          await law.setLevel(stream, Number(input.value) / 100);
          note("");
        } catch (err) {
          note(String((err && err.message) || err), true);
        }
      });
    }

    /* ...and the one that is genuinely this terminal's own. */
    const local = el("plDeskLocal");
    if (local) {
      local.addEventListener("input", () => {
        const law = root.PineAudioLaw;
        const want = Number(local.value) / 100;
        if (law) law.setLocalVolume(want);
        volume = want;
        const label = el("plDeskLocalVal");
        if (label) label.textContent = local.value + "%";
        const vol = el("plVol");
        if (vol) vol.value = local.value;
      });
    }
  }

  /* THE WHOLE OF WHAT IS PLAYING.
   *
   * Whatever is actually making a sound: a voice if one is on air, otherwise
   * the record. The voice wins because if someone is talking over a record,
   * the thing worth keeping is what they said.
   *
   * A RECORD IS BIG AND THAT IS SAID OUT LOUD. listen-model.js refuses to
   * put a record on a pad through "keep this", for a good reason it writes
   * down: a four-minute track decodes to roughly 45 MB of PCM. But this
   * button was asked for explicitly and in those words - "the full clip" -
   * so it does it, and tells the operator what it just cost rather than
   * quietly declining or quietly filling the bank.
   */
  async function grabWholeOfNow(say) {
    const sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== "function") {
      say("no sampler here", true);
      return;
    }
    const feed = root.PineStationFeed;
    const state = feed && feed.state ? (feed.state() || {}) : {};
    const speaking = feed && feed.now ? feed.now() : null;
    const rows = feed && feed.rows ? feed.rows() : [];

    /* A line on air first - the model already knows how to choose one and
     * how to refuse a row whose media has been swept. */
    let row = null;
    if (root.PineListenModel && root.PineListenModel.grabTarget) {
      const pick = root.PineListenModel.grabTarget(
        rows, speaking, sampler.takeable, Date.now());
      row = pick.row;
    }
    /* Otherwise the record. `{url}` with no text is what sourceFor calls
     * "media" and takes whole. */
    let whatFor = "the line on air";
    if (!row) {
      const now = state.now || {};
      if (!now.url) { say("nothing is playing to keep", true); return; }
      row = {id: "now:" + (now.id || now.title || ""), url: now.url,
             name: now.title || "the record"};
      whatFor = now.title || "the record";
    }
    say("keeping it…");
    const got = await sampler.grab(row);
    say(got.ok
      ? "bank " + (got.bank + 1) + ", pad " + (got.pad + 1) + " · " + whatFor
      : got.why, !got.ok);
  }

  /* THE LAST TWENTY SECONDS, off the ring rather than off a file - so it is
   * the mix as it sounded, and it can catch a moment that was never a file
   * at all. */
  const PAD_SECONDS = 20;

  async function grabLastSeconds(say) {
    const air = root.PineAir;
    const sampler = root.PineSampler;
    if (!air || !air.ready()) {
      say(air ? air.why() : "no air tap here", true);
      return;
    }
    if (!sampler || typeof sampler.putBytes !== "function") {
      say("no sampler here", true);
      return;
    }
    const take = Math.min(PAD_SECONDS, air.seconds());
    if (take < 0.4) { say("nothing held yet", true); return; }
    if (air.quiet && air.quiet(take, 0)) {
      say("those seconds were silent", true);
      return;
    }
    const bytes = air.sliceWav(take, 0);
    if (!bytes) { say("the buffer would not give it up", true); return; }
    const placed = await sampler.putBytes(bytes, {
      label: "air · " + take.toFixed(1) + "s",
      who: "broadcast", kind: "air",
      cut: "the last " + take.toFixed(1) + " seconds as it played",
      air: {from: take, to: 0, at: Date.now()}
    });
    say(placed
      ? "bank " + (placed.bank + 1) + ", pad " + (placed.pad + 1)
        + " · last " + take.toFixed(0) + "s"
      : "every pad is full", !placed);
  }

  /* Read the desk back rather than remembering it: the panel's own sliders
   * are the truth, and the drawer or the desktop may have moved them. */
  function paintDesk() {
    const law = root.PineAudioLaw;
    if (!law) return;
    /* `.state()`, NOT `.station()`. PineStationFeed publishes subscribe,
     * refresh, state, rows, now, clock and subscribers - there has never
     * been a `station`. So this line threw a TypeError on EVERY call, which
     * is why the desk could never paint itself: every knob sat at its
     * default with a blank label beside it, and the operator read that as
     * "the sliders do not work".
     *
     * It threw silently because the panel serves this file cross-origin to
     * the page that hosts it, so window.onerror reports only "Script
     * error." with no line - the failure was invisible from both sides. */
    const state = root.PineStationFeed && root.PineStationFeed.state
      ? (root.PineStationFeed.state() || {}) : {};
    for (const [id, stream, out] of [["plDeskMusic", "music", "plDeskMusicVal"],
      ["plDeskVoice", "voice", "plDeskVoiceVal"],
      ["plDeskReply", "duck", "plDeskReplyVal"]]) {
      const input = el(id);
      const label = el(out);
      if (!input) continue;
      /* THIS TERMINAL'S MIX FIRST, because that is what these knobs move.
       * Reading the station's level here is what put every knob at 50 with
       * "not set" beside it while the real mix was 100 / 160 / 70. */
      const mine = law.localMix ? law.localMix(stream) : null;
      if (mine !== null) {
        const range = law.localMixRange(stream);
        input.min = String(range.min);
        input.max = String(Math.min(range.max, stream === "duck" ? 90 : 200));
        input.value = String(Math.round(mine));
        if (label) label.textContent = Math.round(mine) + "%";
        continue;
      }
      const read = law.levelOf(state, stream);
      if (read.level === null) {
        /* Not sent from here and not published by the station. Leave the
         * knob where it is and say so, rather than showing a zero that was
         * never chosen. */
        input.value = "50";
        if (label) label.textContent = "not set";
        continue;
      }
      input.value = String(Math.round(read.level * 100));
      /* Marked when the number is the last thing THIS terminal sent rather
       * than something the station confirmed - it only publishes levels
       * when the broadcast device is the Nabu. */
      if (label) {
        label.textContent = Math.round(read.level * 100) + "%"
          + (read.from === "this terminal" ? "*" : "");
      }
    }
    const local = el("plDeskLocal");
    if (local) {
      const here = Math.round(law.localVolume() * 100);
      local.value = String(here);
      const label = el("plDeskLocalVal");
      if (label) label.textContent = here + "%";
    }
    /* And the talk-only switch reads the route, not a remembered flag. */
    const talk = el("plTalkOnly");
    if (talk) {
      const off = law.isTalkOnly(state);
      talk.textContent = off ? "Music back on" : "Talk only";
      talk.classList.toggle("on", off);
    }
  }

  /* The loading simulation behind the show. Built once, on first need -
   * two of this panel's scenes are WebGL already and the tablet was
   * measured at 148 MB free. */
  let plexus = null;
  let plexusWanted = false;
  function showPlexus(want) {
    plexusWanted = !!want;
    const canvas = el("plBackFx");
    if (!canvas || !root.PinePlexus) return;
    if (!plexus) {
      root.PinePlexus.create(canvas).then((made) => {
        plexus = made;
        if (plexusWanted) plexus.start(); else plexus.stop();
      });
      return;
    }
    if (plexusWanted) plexus.start(); else plexus.stop();
  }

  /* ------------------------------------------------------------- search
   *
   * DEBOUNCED, because every keystroke would otherwise be a request against
   * a 35,982-track index - and this station has a documented history of
   * being starved by chatty clients. 220ms is under the threshold where a
   * suggestion list feels laggy and well above a fast typist's gaps.
   *
   * The history is this terminal's own, in localStorage: the station keeps
   * a request tally (/api/dj/requests) but that is what the WHOLE house
   * asked for, which is a different list from what this operator keeps
   * reaching for. */
  const SEARCH_REST_MS = 220;
  const HISTORY_MAX = 12;
  let searchTimer = 0;
  let searchSeq = 0;

  function history() {
    try { return JSON.parse(localStorage.getItem("pineRequests") || "[]"); }
    catch (err) { return []; }
  }
  function remember(title) {
    if (!title) return;
    const was = history().filter((t) => t !== title);
    was.unshift(title);
    try { localStorage.setItem("pineRequests",
      JSON.stringify(was.slice(0, HISTORY_MAX))); } catch (err) { /* locked */ }
  }

  function wireSearch() {
    const box = el("plSearch");
    const hits = el("plHits");
    if (!box || !hits) return;

    const close = () => { hits.hidden = true; };
    const show = (rows, heading) => {
      hits.replaceChildren();
      if (heading) {
        const h = document.createElement("i");
        h.className = "pl-hitshead";
        h.textContent = heading;
        hits.appendChild(h);
      }
      if (!rows.length) {
        const none = document.createElement("div");
        none.className = "pl-hit pl-hit-none";
        none.textContent = "nothing in the library matches that";
        hits.appendChild(none);
      }
      for (const row of rows.slice(0, 10)) {
        const item = document.createElement("button");
        item.className = "pl-hit";
        const title = document.createElement("b");
        title.textContent = row.title || row.q || "";
        const who = document.createElement("span");
        who.textContent = [row.artist, row.album].filter(Boolean).join(" · ");
        item.appendChild(title);
        item.appendChild(who);
        item.addEventListener("click", (event) => {
          event.stopPropagation();
          request(row.title || row.q || box.value, item);
        });
        hits.appendChild(item);
      }
      hits.hidden = false;
    };

    box.addEventListener("focus", () => {
      const past = history();
      if (!box.value.trim() && past.length) {
        show(past.map((q) => ({title: q, artist: "asked for before"})),
          "what you have asked for");
      }
    });

    box.addEventListener("input", () => {
      clearTimeout(searchTimer);
      const q = box.value.trim();
      if (!q) { close(); return; }
      searchTimer = setTimeout(async () => {
        const mine = ++searchSeq;
        try {
          const got = await api().get(
            "/api/music/search?limit=10&q=" + encodeURIComponent(q));
          /* A slow answer to an old keystroke must not overwrite a fast
           * answer to a new one. */
          if (mine !== searchSeq) return;
          show((got && got.results) || [], null);
        } catch (err) {
          if (mine !== searchSeq) return;
          show([], "the library could not be searched");
        }
      }, SEARCH_REST_MS);
    });

    hits.addEventListener("click", (event) => event.stopPropagation());
    if (root.PineDismiss) root.PineDismiss.watch(hits, close, [() => el("plSearch")]);
    else document.addEventListener("click", close);
  }

  async function request(title, button) {
    const was = button ? button.textContent : "";
    if (button) button.classList.add("asking");
    try {
      /* now:true - the operator tapped a specific track and expects to hear
       * it. It inserts at the head and cuts the current record, which is a
       * real interruption, so it is never sent on a guess. */
      await api().post("/api/dj/request", {q: title, now: true});
      remember(title);
      note("Requested " + title + " - it is coming up now.");
      const hits = el("plHits");
      if (hits) hits.hidden = true;
      const box = el("plSearch");
      if (box) box.value = "";
    } catch (err) {
      note(String((err && err.message) || err), true);
      if (button) { button.classList.remove("asking"); button.textContent = was; }
    }
  }

  /* ------------------------------------------------------------- meters
   *
   * "An audio meter that goes up and down showing the notes."
   *
   * Driven by requestAnimationFrame, NOT by a timer and NOT by the station
   * poll. It reads numbers already in the browser - no request is made, so
   * this adds nothing at all to the traffic the single-poller rule exists
   * to protect. rAF also stops on its own when the view is not on screen,
   * which a setInterval would not.
   *
   * The DJ meter watches BOTH voice players: the panel alternates between
   * them so one line can start while the last is finishing, and only the
   * louder of the two is ever the one speaking. */
  const VOICE_IDS = ["djVoiceAudio0", "djVoiceAudio1"];
  let meterFrame = 0;

  function startMeters() {
    const meters = root.PineMeters;
    const music = el("plMeterMusic");
    const voice = el("plMeterVoice");
    const note = el("plMeterNote");
    if (!meters || !music || !voice) return;

    const tick = () => {
      meterFrame = requestAnimationFrame(tick);
      /* A hidden view must not burn a frame drawing nothing. */
      const host = el("plMeterMusic");
      if (!host || !host.isConnected || !host.clientWidth) return;

      /* Re-attach every frame is cheap (it returns early once tapped) and
       * it is how the DJ players get picked up: the panel creates them
       * lazily, long after this view was built. */
      meters.attach(["musicPlayer"].concat(VOICE_IDS));

      meters.draw(music, meters.read("musicPlayer", "music"), "#54d18b");
      meters.draw(voice, meters.readLoudest(VOICE_IDS, "voice"), "#e3be63");

      /* Say plainly when there is nothing to read, rather than showing a
       * flat line that could equally mean silence or a broken meter. */
      if (note) {
        const tapped = meters.tapped().length;
        note.textContent = tapped
          ? ""
          : "no level yet - the meters read the audio this terminal is playing";
      }
    };
    cancelAnimationFrame(meterFrame);
    meterFrame = requestAnimationFrame(tick);

    /* The audio context starts suspended until a gesture; any touch on the
     * view is a good enough excuse to wake it. */
    document.addEventListener("pointerdown", () => meters.wake(), {once: false});
  }

  /* --------------------------------------------------------------- mount */

  async function mount(host) {
    if (!host || mounted) return;
    config = await api().readConfig();
    build(host);
    wire();
    mounted = true;
    /* Subscribe first, paint second: a late subscriber is handed the
     * current picture immediately by PineStationFeed rather than staring
     * at an empty screen for up to four seconds. */
    if (!unsubscribe) unsubscribe = root.PineStationFeed.subscribe(paint);
    await loadGallery(false);
  }

  /* Built on first visit, like the Sampler. An unopened Listen view costs
   * the station nothing at all - no subscription, no gallery fetch. */
  function bootstrap() {
    const tab = document.getElementById("listenTabBtn");
    const host = document.getElementById("listen");
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

  /* REFIT WHEN THE BOX CHANGES. A rotation gives the headline a different
   * amount of room, and a size measured against the old box is wrong in
   * whichever direction the screen just turned. */
  if (typeof root.addEventListener === "function") {
    root.addEventListener("resize", () => fitHead());
    if (root.screen && root.screen.orientation
      && typeof root.screen.orientation.addEventListener === "function") {
      root.screen.orientation.addEventListener("change", () => fitHead());
    }
  }

  root.PineListen = {
    /* Exposed so anything that changes the headline's box can ask for a
     * refit - and so the fit can be measured rather than eyeballed. */
    fit: fitHead,
    mount,
    isMounted: () => mounted,
    /* Published so a future view wanting "keep this" reuses this one
     * rather than growing a second grab that drifts from it. Its
     * messages land in #plNote, which exists only once Listen has been
     * mounted; a caller elsewhere should pass its own reporter. */
    grab: doGrab,
    applyVolume,
    silence
  };
})(typeof window !== "undefined" ? window : globalThis);
