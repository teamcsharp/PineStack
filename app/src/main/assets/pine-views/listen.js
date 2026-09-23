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

  /* THE ENDLESS SET BEHIND THE SHOW.
   *
   * "In endless video mode replace the background of the page instead of
   * it being comfy UI wallpapers replace it with the video ... just have
   * the background be the video's loading in endless video mode for the
   * listen tab."
   *
   * The floating SFX set (PineSfxTv) already decodes one clip after
   * another when its endless switch is on. This view does not decode a
   * second copy: it asks the set what is in its tube and puts THAT clip
   * in #plBackVid, then veils the floating set so the same picture is not
   * on screen twice. While `endlessBackdrop` is true the gallery road
   * (paintBackdrop / swapStill) skips - it is not fought, it is paused -
   * and when the set goes quiet or off the veil lifts and the gallery
   * paints as it always did.
   *
   * Checked once a second - as a clock check inside the feed's paint, not
   * a timer of its own: the single-poller rule in the header is enforced
   * by a test that refuses any setInterval in this file, and the feed
   * already ticks at 250 ms. */
  const ENDLESS_CHECK_MS = 1000;
  let endlessBackdrop = false;
  let endlessAt = 0;
  /* #1167 - "If I'm in endless video mode and I bring up the file report
   * screen or any report screen, remove the video from displaying and mute
   * the audio for a moment while I narrate to the dictation system. Don't
   * have the audio playing and don't have videos popping up during the
   * process of filing tickets. Resume everything after the ticket
   * following screen has been closed or sent."
   *
   * DUCKING THE LEVEL WAS ONLY HALF OF IT, and the half that does not
   * matter here. A clip behind a report pad is still MOVING - it is still
   * running its cycle, still tearing down and starting the next one, and
   * still asking for the eye of a man who is trying to describe a fault
   * out loud. He said "remove the video from displaying", and that is the
   * literal instruction: off the glass, not dimmed behind a sheet.
   *
   * PAUSED AND HIDDEN, NOT COVERED. A <video> that is merely painted over
   * goes on decoding, goes on reaching its end, and goes on handing the
   * wall to the clip after it. The existing hand-back road in
   * paintEndless already does the right thing - pause, hide, drop the src,
   * load() to let the frames go - so this does not invent a second way to
   * put a clip down; it makes the set look OFF for as long as a report is
   * up, and lets the road that already exists carry it.
   *
   * WHAT THE STILLS DO. "The backdrop falls back to whatever the view
   * shows when there is no clip" - which is the gallery, and the gallery
   * stays. He objected to VIDEO popping up, not to a photograph fading
   * gently behind him, and a screen that goes black while he talks is a
   * screen that looks like it crashed at the worst possible moment.
   *
   * THE SIGNAL IS PineDuck's. pine-duck.js knows about every report and
   * diagnostic surface on both machines - the report pad, the inbox, the
   * reason sheet, the ink overlay, a hot-corner sheet, the line inspector,
   * the tablet doctor, the script-name menu and dictation itself - and its
   * own sweep drops a hold whose element has left the page, so a sheet
   * torn out without closing still ends the quiet. Reproducing any part of
   * that list here would be a second answer to one question. */
  let reporting = false;
  let reportWas = null;         /* the mute state found when quiet began */
  let unwatchDuck = null;

  /* #1147: true while a clip has been asked for and has no frame yet -
   * the window in which the WebView would otherwise paint its own play
   * badge, and the window the plexus covers. */
  let endlessWaiting = false;

  let config = null;
  let mounted = false;
  let unsubscribe = null;

  let stills = [];

  /* 2026-09-15 (#1151): THE PICTURE CARRIES ITS OWN CREDENTIAL.
   *
   * An <img> cannot send an Authorization header, and on the desk this
   * page is a file: URL on another machine, so every one of the 138
   * stills came back 401 and the strip was a white bar with a broken
   * icon. The station now hands out one signature per FILE with the
   * gallery list (app.py list_generations, `sig`), which is the same
   * "the URL is the access control" contract its media has always used.
   * On the tablet the panel is same-origin and the signature is simply
   * redundant. */
  var stillSig = {};

  function genUrl(name) {
    var got = absolute("/api/generations/image/" + encodeURIComponent(name));
    var s = stillSig[name];
    return s ? got + (got.indexOf("?") < 0 ? "?t=" : "&t=") + encodeURIComponent(s) : got;
  }

  let stillAt = 0;
  let stillTrack = "";
  let stillIndex = -1;

  /* THE SCREEN ALONE - #1152 and #1150. See theScreenAlone() below for
   * what each of these is for; they live up here with the rest of the
   * view's state because paint() reads them on the feed's tick. */
  const IDLE_REST_MS = 10000;   /* #1150: "idle after 10 seconds" */
  const DOUBLE_TAP_MS = 320;    /* two taps further apart than this are two */
  const DOUBLE_TAP_PX = 48;     /* ...or further apart than a thumb is wide */
  const TOGGLE_REST_MS = 400;   /* one gesture, one toggle */
  /* #1163 - "If I set the video to full screen, then reload it in full
   * screen as well on the next video open. Retain the scale settings on
   * reload in the web client."
   *
   * THIS OVERTURNS A DECISION MADE IN THIS FILE, AND THE REASON IT WAS
   * MADE IS STILL TRUE. #1152's note said, in as many words: "SESSION
   * ONLY, AND NEVER STUCK. Nothing here is written to localStorage: the
   * operator asked for a gesture, not a setting, and a remembered bare
   * screen is a tablet that looks dead on the shelf the next morning."
   * He has now asked for the opposite, explicitly, and the reason is
   * plain: this kiosk relaunches every few minutes behind the gallery
   * wallpaper, so a session-only full screen is a full screen he keeps
   * losing to something that is not his doing. His ask wins.
   *
   * THE CONCERN BEHIND THE OLD NOTE IS ANSWERED, NOT DISCARDED. A tablet
   * that looks dead on the shelf is a tablet whose operator was told
   * nothing. A restored bare screen therefore says what it is and how to
   * leave it - one quiet line, for six seconds, then it fades and the
   * glass is the picture and the dot. A gesture does NOT raise the line:
   * a man who has just double tapped the screen knows what he did.
   *
   * SIX SECONDS, on the same clock check inside paint() that everything
   * else in here uses. Long enough to read eleven words at reading
   * distance, short enough that it is not still sitting on the picture
   * when he looks up.
   */
  const BARE_KEY = "pineListenBare";
  const NOTE_SHOW_MS = 6000;
  let barePending = false;      /* stored bare, waiting for a clip */
  let noteAt = 0;               /* when the restored-state line went up */
  let viewHost = null;          /* the section this view was mounted into */
  let bare = false;             /* #1152: the chrome is hidden on purpose */
  let idleDim = false;          /* #1150: the chrome is faded, nobody is here */
  let idleAt = 0;
  let bareAt = 0;
  let tapAt = 0;
  let tapX = 0;
  let tapY = 0;
  let chromeWatch = null;

  let sleep = null;             /* the plan from model.sleepPlan(), or null */
  let volume = 1;
  let fadedTo = -1;             /* the last level the fade actually set */
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
    /* The page's own origin first - see sampler.js's absolute(). A URL built
     * against the configured address while the page came in by another road
     * is cross-origin, and this station has no CORS to allow it. */
    const base = /^https?:$/i.test(location.protocol)
      ? location.origin
      : String((config && config.baseUrl) || "").replace(/\/+$/, "");
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
      stillSig = (got && got.sig) || {};   /* 2026-09-15 (#1151) */
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
    /* The endless set owns the backdrop while it is on - see paintEndless.
     * Skipping here rather than inside each branch keeps the gallery's own
     * swap logic exactly as it was. */
    if (endlessBackdrop) return;
    if (!stills.length) return;
    /* Cycles on its own clock now, not on the track: a record sits for
     * three minutes and the backdrop should not. */
    if (at - stillAt < BACKDROP_REST_MS) return;
    stillTrack = String((state.now || {}).id || "");
    stillAt = at;
    backdropTurn += 1;

    const still = el("plBack");
    const vid = el("plBackVid");

    /* Occasionally, a moving one - but never while a report is up.
     * #1167: "don't have videos popping up during the process of filing
     * tickets" is not only about the endless set. The gallery road puts a
     * clip on this same element every fifth turn, and one of those
     * arriving mid-sentence is the same interruption by another door. The
     * stills go on cycling; only the moving ones wait. */
    if (!reporting && clips.length && vid && backdropTurn % CLIP_EVERY === 0) {
      const pick = clips[Math.floor(Math.random() * clips.length)];
      vid.src = genUrl(pick);   /* 2026-09-15 (#1151) */
      /* HIDDEN UNTIL IT HAS A FRAME. The plexus covers the download, which
       * is a real wait: that route has no Range support, so the clip comes
       * whole before a single frame exists. */
      vid.hidden = true;
      showPlexus(true);
      vid.onloadeddata = () => {
        /* The endless set may have taken the element while this clip was
         * still arriving; its frame is not ours to reveal. */
        if (endlessBackdrop) return;
        vid.hidden = false;
        showPlexus(false);
        if (still) still.style.opacity = "0";
      };
      vid.play().catch(() => {
        /* Autoplay refused, or the clip will not decode. Fall back to a
         * still rather than leaving a black rectangle behind the show.
         * A play() interrupted by the endless set changing src rejects
         * too (AbortError), and that one must not hide the set's clip. */
        if (endlessBackdrop) return;
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
    swapStill(genUrl(stills[stillIndex]));   /* 2026-09-15 (#1151) */
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
  let stillMiss = 0;            /* #1151: stills refused in a row */

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
      stillMiss = 0;
      /* A still decoded during the wait must not fade in over the endless
       * set's video; the next gallery turn will pick another. */
      if (endlessBackdrop) return;
      under.src = src;
      backDrift = (backDrift + 1) % 4;
      under.className = first.className.replace(/ *pl-drift-[0-9]/g, "")
        + " pl-drift-" + backDrift;
      under.style.opacity = "1";
      over.style.opacity = "0";
      backFront = 1 - backFront;
    };
    /* A still that will not load is skipped rather than shown as a hole -
     * the picture is only ever swapped in AFTER it has decoded, so there
     * is never a broken-image box on this wall.
     *
     * #1151, and this is the honest half of it: skipping silently means a
     * gallery that can never paint looks exactly like a view that simply
     * has no wallpaper, while #plNote underneath goes on saying "138
     * pictures behind the show". MEASURED 2026-09-15 against the station:
     * GET /api/generations?limit=200 answers 200 with no credential at
     * all, but GET /api/generations/image/<name> answers 401 to anything
     * that is not the station's own loopback - require_listen_auth
     * (app.py:13206) wants a ?t= tune-in token or an Authorization header,
     * and an <img> can carry neither. So on the TABLET, where the panel is
     * served from 127.0.0.1:8096 and the pictures are same-origin, every
     * still decodes (measured: naturalWidth 768); on the DESK, where the
     * page is file: and the station is another machine, all 138 of them
     * are refused. Three in a row is not a bad file, it is a shut door,
     * and the view says so instead of pretending. */
    pre.onerror = () => {
      stillMiss += 1;
      if (stillMiss === 3) {
        note("the gallery pictures are being refused - " + stills.length
          + " known, none of them reachable from here", true);
      }
    };
    pre.src = src;
  }

  /* Is this view actually on a screen somebody can see? The section is
   * display:none behind another tab, and a hidden document (the tablet
   * asleep, the app minimised) paints nothing. Both the endless veil and
   * the spectrogram must let go in either case: a veiled floating set on
   * a tab that is not showing is a set that has simply vanished. */
  function onScreen() {
    if (document.hidden) return false;
    const face = el("plNow");
    return !!(face && face.isConnected && face.clientWidth > 0);
  }

  /* THE SET'S CLIP AS THE BACKDROP. Called from paint() on the feed's
   * tick; does its own work at most once a second.
   *
   * The contract with sfx-tv.js: endless() says whether the endless
   * switch is on, playing() is the clip in the tube ({url, sting, id,
   * seconds, ...}; url station-relative like /sfx/<id>?t=<sig>, resolved
   * here the same way a gallery still is), veil(true|false) hides or shows
   * the floating set. `src` is written only when the clip changes -
   * assigning it on every check would restart the decode once a second -
   * and the element does not loop: when a clip ends its last frame stays
   * up until the set moves on to the next one. */
  /* #1173 - "So even though the Pine tab is the default device, video seem
   *  to have a slight lag when it comes to playing out of the Pine tablet.
   *  its showing a different video on the spark agent than the tablet so
   *  they are getting out of sync."
   *
   * THIS WALL IS A THIRD SURFACE SHOWING THE SAME ENDLESS SET, and it was
   * out of step with the floating set standing a few inches away on the
   * SAME device. Measured on the tablet, 2026-09-15, 465 samples over two
   * minutes: the wall ran a median 0.85 s behind the set (max 1.28 s), and
   * in 6% of the samples the two were on DIFFERENT clips altogether.
   *
   * Nothing exotic in it. paintEndless does its work at most once a second
   * (ENDLESS_CHECK_MS), so it learns that the set moved on up to a second
   * after the set did, and then it started the file from zero - and then
   * spent its own decode on top of that.
   *
   * sfx-tv.js now anchors a clip to the station's own stamp instead of to
   * the file's first frame (airInto: how far into the clip the station is,
   * from broadcast_ms, carried onto this machine's clock), and this wall
   * takes the same number off the same road. A poll interval then costs
   * nothing: however late the wall finds out, it arrives at the frame the
   * set is already showing.
   *
   * IT DEGRADES. Where an older sfx-tv.js is loaded there is no airInto to
   * call and both helpers below return without touching anything, which is
   * the behaviour of the day before - the file from zero, a second behind.
   */
  var ENDLESS_JOIN_MIN = 0.35;   // below this a seek costs more than it buys
  var ENDLESS_JOIN_TAIL = 0.6;   // this near the end, let it be
  var ENDLESS_SLIP_MAX = 0.75;   // a jump smaller than this is worse than the slip
  var ENDLESS_FIX_MS = 4000;     // and never two jumps closer than this
  var endlessFixAt = 0;

  /* #1173: put a freshly-sourced clip where the station is. Called on
   * loadedmetadata, which is before any frame has been committed, so the
   * first thing this wall shows is already the right one. */
  function endlessJoin(vid, clip) {
    var tv = root.PineSfxTv;
    if (!vid || !tv || typeof tv.airInto !== "function") return;
    var into = 0;
    try { into = Number(tv.airInto(clip)) || 0; } catch (err) { return; }
    if (!(into > ENDLESS_JOIN_MIN)) return;
    var len = Number(vid.duration);
    if (isFinite(len) && len > 0 && into > len - ENDLESS_JOIN_TAIL) return;
    try { vid.currentTime = into; } catch (err) { /* it plays from its start */ }
  }

  /* #1173: and hold it there, on the once-a-second clock everything else
   * in here already runs on. The tablet's WebView suspends its JS timers
   * when the screen sleeps and the decode stalls with them; it comes back
   * where it left off with no way to notice. Rested, and never for a jump
   * smaller than a jump is worth. */
  function endlessHold(vid, clip, at) {
    var tv = root.PineSfxTv;
    if (!vid || !tv || typeof tv.airInto !== "function") return;
    if (at - endlessFixAt < ENDLESS_FIX_MS) return;
    var into = 0;
    try { into = Number(tv.airInto(clip)) || 0; } catch (err) { return; }
    if (!(into > 0)) return;
    var off = Number(vid.currentTime) - into;
    if (!isFinite(off) || Math.abs(off) < ENDLESS_SLIP_MAX) return;
    var len = Number(vid.duration);
    if (isFinite(len) && len > 0 && into > len - ENDLESS_JOIN_TAIL) return;
    endlessFixAt = at;
    try { vid.currentTime = into; } catch (err) { /* it plays on */ }
  }

  function paintEndless(at, force) {
    if (!force && at - endlessAt < ENDLESS_CHECK_MS) return;
    endlessAt = at;
    const tv = root.PineSfxTv;
    const vid = el("plBackVid");
    const still = el("plBack");
    /* #1167: a report is up, so the set is OFF as far as this wall is
     * concerned. Folding it into `on` rather than adding a branch means
     * the hand-back below - pause, hide, drop the src, let the frames go,
     * give the wall back to the gallery - is the same road a set being
     * switched off takes, and there is only ever one way a clip comes
     * down off this screen. */
    const on = !reporting
      && !!(tv && typeof tv.endless === "function" && tv.endless()
      && typeof tv.playing === "function" && onScreen());
    const clip = on ? tv.playing() : null;
    const want = clip && clip.url ? absolute(String(clip.url)) : "";
    /* #1173: the SLOT, not the file. The station's plan can hand the same
     * clip out twice, and two turns of it are two different pictures with
     * two different start stamps - which matters now that the seek below
     * reads that stamp. Keyed on the url as before, plus the moment. */
    var slot = want ? want + "#" + String((clip && clip.at) || 0) : "";

    if (want && vid) {
      if (!endlessBackdrop) {
        endlessBackdrop = true;
        vid.classList.add("pl-endless");
        /* Both gallery layers go, not just the first: swapStill keeps the
         * picture on whichever of the two it faded in last. */
        if (still) still.style.opacity = "0";
        /* By id, as swapStill finds it: the layer is cloned, not built. */
        const second = document.getElementById("plBack2");
        if (second) second.style.opacity = "0";
      }
      if (vid.dataset.endless !== slot) {
        vid.dataset.endless = slot;                        /* #1173 */
        /* The gallery's own handler is dropped: it would reveal the frame
         * and dim the still on its own terms, and it belongs to a clip
         * that is no longer in the element. */
        vid.onloadeddata = null;
        vid.loop = false;
        vid.muted = true;
        /* #1147 - "So I don't want this logo to show every time the video
         * changes. Like this play button doesn't look good. I instead want
         * plexus graphics in the background undulating."
         *
         * THE LOGO AND THE PLAY BUTTON ARE NOT DRAWN BY THIS APP. They are
         * the WebView's own poster for a <video> that has a src and no
         * frame yet - a play badge stretched across the box over Android's
         * media glyph - and object-fit cannot touch it, because it is
         * chrome and not content. build() already says so above #plBackFx,
         * and the GALLERY road already covers that wait with the plexus.
         * The ENDLESS road never did, and endless mode is the one that
         * changes clip every ten to thirty seconds - which is exactly
         * "every time the video changes".
         *
         * So the element is emptied of anything the browser could hang a
         * badge on before the new clip is asked for: hidden first, plexus
         * up, and revealed only once there is a real frame behind it.
         *
         * The plexus is PinePlexus (wall-transition.js) - the same
         * drifting points and short lines between the near ones that the
         * boot splash and the talk dot already run, already in the
         * station's #65c7da, already one canvas, already stopped the
         * moment it is not wanted. A second particle canvas on a 4 GB
         * tablet would be the wrong answer to a question about a play
         * button. */
        endlessWaiting = true;
        vid.hidden = true;
        showPlexus(true);
        /* #1173: the station's position, before the first frame is
         * committed - see the note above paintEndless. */
        vid.onloadedmetadata = function () {
          if (!endlessBackdrop || vid.dataset.endless !== slot) return;
          endlessJoin(vid, clip);
        };
        vid.onloadeddata = function () {
          /* A newer clip may have taken the element while this one was
           * still arriving; its frame is not ours to reveal. */
          if (!endlessBackdrop || vid.dataset.endless !== slot) return;
          endlessWaiting = false;
          vid.hidden = false;
          showPlexus(false);
        };
        /* A clip that will not arrive must not leave this waiting for
         * ever. The set moves on by itself and the next check takes the
         * element; until then the wall stays the plexus, which is a better
         * picture than a black rectangle anyway. */
        vid.onerror = function () { endlessWaiting = false; };
        vid.src = want;
        vid.play().catch(() => { /* the plexus is holding the wall */ });
      }
      /* A belt for that event's braces. loadeddata is a one-shot, and a
       * frame that lands while this document is in the background can
       * arrive with nobody listening - on the tablet that is every screen
       * sleep mid-clip. Checked on the same once-a-second clock as
       * everything else in here, never on a timer of its own. */
      if (endlessWaiting && vid.readyState >= 2) {
        endlessWaiting = false;
        vid.hidden = false;
        showPlexus(false);
      }
      /* #1173: and while it is running, keep it on the station's clock. */
      if (!endlessWaiting && !vid.paused && vid.readyState >= 1) {
        endlessHold(vid, clip, at);
      }
      if (typeof tv.veil === "function") tv.veil(true);
      return;
    }

    if (!endlessBackdrop) return;
    /* Off, quiet, or off screen: hand the wall back to the gallery. */
    endlessBackdrop = false;
    /* #1147: the plexus was standing in for a clip that is not coming.
     * The gallery paints a still over this within the moment. */
    endlessWaiting = false;
    showPlexus(false);
    if (tv && typeof tv.veil === "function") tv.veil(false);
    if (vid) {
      vid.classList.remove("pl-endless");
      delete vid.dataset.endless;
      vid.onloadedmetadata = null;                         /* #1173 */
      vid.pause();
      vid.hidden = true;
      vid.removeAttribute("src");
      vid.loop = true;
      /* Let go of the decoded frames; this screen runs for hours. */
      try { vid.load(); } catch (err) { /* nothing to release */ }
    }
    /* Show the layer the gallery was showing, and let it take its next
     * turn at once rather than waiting out the rest it had already
     * served before the set took over. */
    if (backLayers.length) backLayers[backFront].style.opacity = "1";
    else if (still) still.style.opacity = "";
    stillAt = 0;
  }

  /* ======================================================================
   * THE SCREEN ALONE - #1152 and #1150
   *
   * #1152 - "When under the Listen tab, in endless video mode, allow me to
   * double tap the background in order to go full screen and hide all of
   * the UI except for the dot."
   *
   * #1150 - "Whenever this screen is idle after 10 seconds, fade the UI to
   * 20% until I tap the screen to show it again. In endless video mode."
   *
   * TWO THINGS THAT LOOK ALIKE AND MUST NOT BE CONFUSED. The double tap is
   * a DECISION: the operator said hide it, and it stays hidden until he
   * says otherwise - a clip ending, a record changing, ten quiet minutes,
   * none of them put it back. The idle fade is a COURTESY: the room went
   * quiet, so the furniture steps back to a fifth of itself, and the first
   * sign of a hand restores it in full. They cannot both be in force, and
   * the decision outranks the courtesy - while the chrome is deliberately
   * hidden there is nothing left for the fade to fade, so it does not run.
   *
   * BOTH ARE ONE CLASS ON ONE ELEMENT. Everything the request lists - the
   * station name and clock, the headline, the cover, the two meters, the
   * track and its progress bar, NEXT, the search box, the marquee, the
   * spectrogram, the notes - is inside .pl-face. The backdrop layers, the
   * clip, the plexus and the shade are its SIBLINGS, and the talk dot is
   * not in this view at all. So neither of these walks the DOM and neither
   * hides nine things one at a time: it is a single opacity the compositor
   * owns. That is not tidiness, it is the tablet - a fade built out of
   * nine style writes is nine invalidations in every frame of it, on the
   * one screen whose frame pipeline has already had to be measured twice.
   *
   * THE DOT IS NEVER TOUCHED. #pineTalkDot is talk-dot.js's own fixed
   * element on the body, outside this view's host entirely, so "hide all
   * of the UI except for the dot" is satisfied by hiding nothing but
   * .pl-face. This file does not reach for it and does not need to.
   *
   * SESSION ONLY, AND NEVER STUCK. Nothing here is written to
   * localStorage: the operator asked for a gesture, not a setting, and a
   * remembered bare screen is a tablet that looks dead on the shelf the
   * next morning. The chrome comes back on a second double tap, on
   * Escape, when the document goes hidden, and the moment the view stops
   * being the open one - .open is the tablet rail's word for that and
   * .active is the desktop shell's, and losing either is enough.
   *
   * NO TIMER, AND THE TEN SECONDS ARE STILL HONEST. The header's
   * single-poller rule is enforced by a test that refuses any setInterval
   * in this file, so the ten seconds are a clock check inside paint() on
   * the shared feed's tick - the same shape the endless backdrop already
   * uses one screen up. It suits the tablet better than a timer would
   * have anyway: a WebView suspends JS timers when its view is not
   * showing, so a setTimeout here would have fired late or not at all and
   * the fade would have been a promise the file could not keep. What
   * cannot wait for a tick is the RESTORE - #1150 asks for full strength
   * instantly - so that happens in the event itself, and only the
   * decision to fade is left to the clock.
   * ================================================================== */

  /* THE STORE, AND WHAT IS AND IS NOT IN IT.
   *
   * #1163 also says "retain the scale settings on reload in the web
   * client", and the honest answer for THIS view is that it has none to
   * retain. Nothing on this screen is scaled by hand: fitHead() derives a
   * headline size from the box it is given and nothing else here has a
   * zoom, a size or a pinch. The two numbers the operator does choose -
   * the volume and his request history - have been in localStorage since
   * the view was written (pineListenVolume, pineRequests). The scale half
   * of #1163 belongs to the SFX set's pop-up, which has carried its own
   * geometry since #1122 and is not this file's to touch. So what is
   * added here is the one thing that was missing: the full screen itself.
   *
   * A JSON object rather than a bare flag, so a number this view does not
   * have yet has somewhere to go without a second key and a second
   * migration. Read defensively in both directions: a locked store, a
   * store that throws on access - which it does on this stack, in a
   * private window and under a thumbnail capture - or a corrupt value all
   * mean the same thing, and the safe direction is NOT bare. A screen
   * that wrongly comes up with its panel showing is a nuisance; one that
   * wrongly comes up blank is a tablet somebody thinks is broken. */
  function readBare() {
    let saved = null;
    try { saved = JSON.parse(root.localStorage.getItem(BARE_KEY) || "null"); }
    catch (err) { saved = null; }
    return !!(saved && saved.bare === true);
  }

  /* Written ONLY from a deliberate act - the double tap and Escape. The
   * automatic restores (the view being closed, the document going hidden)
   * are this file keeping its "never stuck" promise, not the operator
   * changing his mind, and recording them would mean his full screen was
   * cancelled every time he glanced at another view. That distinction is
   * the whole of "reload it in full screen as well on the next video
   * open": leaving the view is not a decision, coming back is. */
  function writeBare(on) {
    try {
      root.localStorage.setItem(BARE_KEY, JSON.stringify({bare: !!on}));
    } catch (err) { /* a locked store must not stop the radio */ }
  }

  /* #1167: go quiet, and come back exactly as found.
   *
   * THE MUTE IS RECORDED RATHER THAN ASSUMED. In endless mode paintEndless
   * sets this element muted every time, because it is wallpaper and a
   * backdrop that made noise would be a second voice over the station - so
   * nine times in ten writing `true` here changes nothing and writing
   * `true` back afterwards would be right by luck. It is not written back
   * by luck. What was found is what is restored, so an element some other
   * road deliberately left UNMUTED is handed back unmuted, and this
   * function cannot be the reason a picture goes silent for good.
   *
   * Only the mute is carried across. Paused and hidden are not restored
   * from here because they are not this function's to restore: when the
   * report closes, paintEndless is asked to decide the wall again from
   * scratch and puts a fresh clip up through the road that always builds
   * one. Recording a `paused` this file would never write back would be a
   * comment pretending to be code. */
  function reportQuiet(on) {
    const vid = el("plBackVid");
    if (on) {
      if (!reportWas && vid) reportWas = {el: vid, muted: !!vid.muted};
      if (vid) {
        if (!vid.muted) vid.muted = true;
        try { vid.pause(); } catch (err) { /* it was not going anyway */ }
        vid.hidden = true;
      }
      /* #1147's stand-in is a requestAnimationFrame loop and a picture in
       * its own right. Neither belongs on the glass while he is talking. */
      endlessWaiting = false;
      showPlexus(false);
      return;
    }
    const was = reportWas;
    reportWas = null;
    if (vid && was && was.el === vid && vid.muted !== was.muted) {
      vid.muted = was.muted;
    }
  }

  /* Is this view the one on the glass? Either host class missing means the
   * operator has gone somewhere else and the chrome must come back. */
  function viewOpen() {
    if (!viewHost || !viewHost.isConnected) return false;
    const cls = viewHost.classList;
    return cls.contains("open") || cls.contains("active");
  }

  function paintChrome() {
    /* #1156 - "When I am in full screen, fade the tabs down to 5%."
     *
     * THE TABS ARE NOT IN THIS VIEW. #pineViewRail is rail.js's own fixed
     * element on the BODY, a sibling of this view's host and above it
     * (z-index 2147483001 against the host's 2147483000), which is why it
     * was still at full strength over the clip when everything inside
     * .pl-face had gone. No selector rooted at the host can reach it.
     *
     * So the bare state is published where anything in the document can
     * see it: one class on <html>. listen-music.css writes the opacity
     * against #pineViewRail from there, and rail.js is not touched - it
     * has another pair of hands in it tonight, and a view is not entitled
     * to reach into the furniture anyway.
     *
     * WRITTEN BEFORE THE HOST GUARD, DELIBERATELY. This is a class on an
     * element outside this view, so it must come off even in the case
     * where the host has gone - a rail left at five percent with no view
     * to explain it is furniture the operator cannot find, and this
     * function is the only writer of it. */
    const doc = document.documentElement;
    const saying = bare && !!noteAt;
    if (doc && doc.classList) {
      doc.classList.toggle("pine-listen-bare", bare);
      /* #1163: while the line is up the rail comes back to full strength
       * too. #1156 puts the tabs at five percent in full screen, which is
       * right for a screen the operator just chose - and wrong for the
       * first six seconds after a relaunch, when the one thing he must be
       * able to find is the way out of a view he did not ask to be in. */
      doc.classList.toggle("pine-listen-bare-said", saying);
    }
    /* The line lives OUTSIDE .pl-face, with the backdrop layers, because
     * .pl-face is the thing being hidden - a note inside it would be a
     * note at opacity zero. */
    const said = el("plBareNote");
    if (said) said.classList.toggle("on", saying);
    if (!viewHost) return;
    viewHost.classList.toggle("pl-bare", bare);
    viewHost.classList.toggle("pl-idle", idleDim && !bare);
  }

  /* Everything comes back. Every road out of this view runs through here.
   *
   * #1163: `deliberate` says whether this was the operator leaving full
   * screen or this file keeping him out of a corner. Only the first is
   * written down - see writeBare(). */
  function showChrome(deliberate) {
    if (deliberate) { barePending = false; writeBare(false); }
    if (!bare && !idleDim && !noteAt) return;
    /* #1163: AND IT RE-ARMS. barePending is spent the first time a stored
     * full screen is applied, so without this the promise made two
     * paragraphs up - that leaving the view is not him cancelling it -
     * would only hold across a RELAUNCH, and not across the far commoner
     * case of stepping over to MUSIC and back inside one page load. The
     * store is consulted rather than the flag trusted, so a deliberate
     * exit that has just written false re-arms to false, which is the
     * same answer by a shorter road. At most one read per trip out of
     * full screen. */
    if (!deliberate && bare) barePending = readBare();
    bare = false;
    idleDim = false;
    noteAt = 0;
    paintChrome();
  }

  /* A hand, a key, a wheel: the room is not idle any more. */
  function stir() {
    idleAt = Date.now();
    if (!idleDim) return;
    idleDim = false;
    paintChrome();
  }

  /* #1150's clock check. Called from paint() on the feed's 250ms tick. */
  /* #1163's half of the tick: bring a stored full screen back, and take
   * the line that explains it down again six seconds later.
   *
   * IT WAITS FOR A CLIP. "Reload it in full screen as well on the NEXT
   * VIDEO OPEN" - so the stored flag is pending, not applied, until the
   * endless set actually has something on the wall. That is his sentence
   * read literally, and it is also the safe reading: a bare screen over a
   * gallery still is a view that has hidden itself for no reason, and a
   * relaunch that lands while the set is off would have produced exactly
   * that. paint() calls paintEndless before this, so the flag it reads is
   * this tick's, not the last one's. */
  function paintBare(at) {
    if (noteAt && at - noteAt >= NOTE_SHOW_MS) {
      noteAt = 0;
      paintChrome();
    }
    if (!barePending) return;
    if (!endlessBackdrop || !viewOpen() || !onScreen()) return;
    barePending = false;
    bare = true;
    idleDim = false;
    idleAt = at;
    bareAt = at;
    noteAt = at;
    paintChrome();
  }

  function paintIdle(at) {
    if (!viewHost) return;
    if (!viewOpen() || !onScreen()) {
      /* Left, closed, or behind another app: nothing is hidden and
       * nothing is faded on a screen the operator is not looking at, or
       * he comes back to a black rectangle and no way out of it. */
      showChrome(false);
      idleAt = at;
      return;
    }
    if (bare || !endlessBackdrop) {
      if (idleDim) { idleDim = false; paintChrome(); }
      idleAt = at;
      return;
    }
    if (idleDim) return;
    if (at - idleAt < IDLE_REST_MS) return;
    idleDim = true;
    paintChrome();
  }

  /* #1152's toggle. The HIDE is gated on endless video mode, which is what
   * was asked for. The SHOW never is: a gate on the way out is how an
   * operator ends up looking at a video he cannot get the screen back
   * from, and the set can go quiet while the chrome is down. */
  function toggleBare() {
    const at = Date.now();
    if (at - bareAt < TOGGLE_REST_MS) return;
    if (!bare && !endlessBackdrop) return;
    bareAt = at;
    bare = !bare;
    idleDim = false;
    idleAt = at;
    /* #1163: a gesture never raises the line - he has just done it and
     * knows what he did - and a gesture is always written down. */
    barePending = false;
    noteAt = 0;
    paintChrome();
    writeBare(bare);
  }

  /* Does this tap belong to the backdrop rather than to a control? While
   * the chrome is bare .pl-face is pointer-events:none, so the tap that
   * brings it back lands on the host itself; while it is up, a double tap
   * on a button or a search box is that control's business and not this. */
  function onBackdrop(target) {
    if (!target || !viewHost) return false;
    if (target === viewHost) return true;
    const cls = target.classList;
    if (!cls) return false;
    return cls.contains("pl-back") || cls.contains("pl-shade")
      || cls.contains("pl-face") || cls.contains("pl-now");
  }

  function wireScreenAlone(host) {
    if (!host) return;
    viewHost = host;
    idleAt = Date.now();
    /* #1163: whatever he left it at. Pending until a clip is on the wall -
     * see paintBare. */
    barePending = readBare();

    /* #1167: told the moment a report opens or closes, rather than found
     * out a second later on the endless check's own rest. A second is a
     * long time to have a clip moving behind a man who has started
     * talking, and the resume has to be just as prompt or the picture he
     * was promised back does not come back until he wonders whether it
     * will. The dot is never touched - it is the thing he is dictating
     * into. */
    const duck = root.PineDuck;
    if (!unwatchDuck && duck && typeof duck.watch === "function") {
      unwatchDuck = duck.watch(function (on) {
        const was = reporting;
        reporting = !!on;
        if (was === reporting) return;
        reportQuiet(reporting);
        /* Decide the wall again at once. On the way in this takes the clip
         * down; on the way out it puts a fresh one up, with the plexus
         * covering the load exactly as #1147 asks. Bare mode is not
         * touched by any of it, so a screen he left full screen comes back
         * full screen (#1163). */
        if (mounted) paintEndless(Date.now(), true);
      });
    }

    /* THE DOUBLE TAP IS COUNTED HERE RATHER THAN LEFT TO `dblclick`.
     * A WebView synthesises dblclick from two taps only when it feels like
     * it - a page doing its own pointer handling routinely gets two
     * pointerups and no dblclick at all - and this gesture is a TAP, on
     * glass, on a tablet. So two pointerups inside 320ms and 48px are the
     * gesture. `dblclick` is taken as well for the mouse on the desk, and
     * TOGGLE_REST_MS is what stops one physical gesture counting twice
     * where a WebView sends both. */
    host.addEventListener("pointerup", function (event) {
      const at = Date.now();
      const x = event.clientX || 0;
      const y = event.clientY || 0;
      const near = Math.abs(x - tapX) <= DOUBLE_TAP_PX
        && Math.abs(y - tapY) <= DOUBLE_TAP_PX;
      if (at - tapAt <= DOUBLE_TAP_MS && near && onBackdrop(event.target)) {
        toggleBare();
      }
      tapAt = at;
      tapX = x;
      tapY = y;
    });
    host.addEventListener("dblclick", function (event) {
      if (onBackdrop(event.target)) toggleBare();
    });

    /* #1150: a tap, a pointermove, a wheel - a hand in the room. Passive
     * and doing nothing but writing a timestamp, because this runs under
     * a finger dragging the volume knob. */
    ["pointerdown", "pointermove", "pointerup", "wheel", "touchstart"]
      .forEach(function (name) {
        host.addEventListener(name, stir, {passive: true});
      });

    /* Keys are the document's, not the host's: the rail and the search box
     * both take focus, and a key pressed anywhere is still a hand. */
    document.addEventListener("keydown", function (event) {
      if (!viewOpen()) return;
      /* #1152: "Also restore on Escape." */
      if (event.key === "Escape") { showChrome(true); return; }
      stir();
    });

    /* LEAVING THE VIEW PUTS IT BACK. rail.js takes .open off this host on
     * the tablet and the desktop shell takes .active off it; watching the
     * attribute costs nothing and is not a timer, which matters on the one
     * screen where timers stop. paintChrome's own class writes retrigger
     * this, and that is harmless - the view is still open, so it is a
     * read of two classList flags and nothing else. */
    if (!chromeWatch && typeof root.MutationObserver === "function") {
      chromeWatch = new root.MutationObserver(function () {
        if (viewOpen()) return;
        /* NOT deliberate: leaving the view is not the operator cancelling
         * his full screen, so #1163 keeps it for the next time round. */
        showChrome(false);
        /* #1147: and the plexus is a requestAnimationFrame loop. A closed
         * view must not keep one running behind another screen. */
        showPlexus(false);
      });
      chromeWatch.observe(host, {attributes: true, attributeFilter: ["class"]});
    }
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
      /* 2026-09-15 (#1206): the green "somebody is speaking" colour belongs
       * to a headline that IS the spoken line. While a record holds the
       * headline the kind is still "voice" - the name and the marquee want
       * to know - but the title is a title and must not be painted as
       * speech. */
      host.classList.toggle("voice",
        now.kind === "voice" && !now.track);
      host.classList.toggle("speaking", now.kind === "voice" && !!now.track);
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
    paintSaid(payload);
    /* The set first, so the gallery sees the flag before it paints. */
    paintEndless(at, false);
    paintBackdrop(state, at);
    /* #1163 then #1150, both reading the flag paintEndless just set. */
    paintBare(at);
    paintIdle(at);
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
    /* target.why used to be printed beside the button as well. That was
     * the "dialogue appearing in the section randomly" the operator
     * asked to lose; the box is the marquee now (paintSaid) and the
     * reason lives in the button's title, where it always also was. */
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
    const button = el("plGrab");
    if (button) { button.disabled = true; button.classList.add("working"); }
    tell("taking " + target.why + "…");
    try {
      const result = await s.grab(target.row);
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
      /* #1163: the line a RESTORED full screen puts on the glass. Outside
       * .pl-face on purpose - that is the element bare mode hides - and
       * pointer-events:none so the double tap it is describing goes
       * straight through it to the backdrop underneath. */
      + '<p id="plBareNote" class="pl-barenote">full screen - double tap '
      + 'to show the panel</p>'
      + '<div class="pl-face">'
      + '<div class="pl-top"><b id="plStation">Pine Box FM</b>'
      /* THE GRAB PAD LIVES UP HERE, beside the clock, which is where the
       * operator pointed at it. Not in the transport row: it does not change
       * what is playing, it keeps it - and the top right is the one corner
       * of this view that is never covered by the artwork or the headline. */
      + '<button id="plPad" class="pl-pad" title="Tap: keep the whole of '
      + 'what is playing. Double tap: the last twenty seconds. '
      + 'Triple tap: the last two lines said.">'
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
      + '<button id="plDeskBtn" class="pl-deskbtn" title="Levels and meters" aria-label="Levels and meters">'
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
      /* THE LINE ON AIR, and the voice under it - see paintSaid() and
       * drawSpectrogram(). Ordered last in the row by CSS so it takes the
       * full width beneath the buttons rather than splitting them. */
      + '<div id="plSaid" class="pl-said dim">'
      + '<div class="pl-marquee"><div id="plSaidTrack" class="pl-marquee-track"></div></div>'
      + '<canvas id="plSaidSpec" class="pl-said-spec"></canvas>'
      + '<i id="plSaidNote" class="pl-said-note"></i></div>'
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
      /* The canonical listener bus carries the cut and boost stages together.
       * 600% matches the panel gain controls and the Levels sheet. */
      + '<label class="pl-deskrow"><span>music</span>'
      + '<input id="plDeskMusic" type="range" min="0" max="600" step="1">'
      + '<i id="plDeskMusicVal"></i></label>'
      + '<label class="pl-deskrow"><span>djs</span>'
      + '<input id="plDeskVoice" type="range" min="0" max="600" step="1">'
      + '<i id="plDeskVoiceVal"></i></label>'
      /* #1194: THE DUCK ROW IS THE PANEL'S djDuck AND NOTHING ELSE.
       * It sets how far the music dips while a DJ is talking - the depth
       * djApplyGain multiplies into the music gain while djSpeaking. It is
       * NOT PineDuck, which is the automatic 10%-while-a-report-is-open /
       * 2%-while-dictation-listens hold; that one is reference counted,
       * transient, and not a depth anybody dials. The title says so, so
       * the two are never read as one control again. */
      + '<label class="pl-deskrow" title="How far the music dips while a '
      + 'voice is talking, on this terminal. This is the one that decides '
      + 'whether you can hear them over a record. It is the duck depth '
      + 'this panel already has - not the automatic duck that steps the broadcast back '
      + 'to 10% while a report is open, which sets itself."><span>duck</span>'
      + '<input id="plDeskReply" type="range" min="0" max="90" step="1">'
      + '<i id="plDeskReplyVal"></i></label>'
      + '<label class="pl-deskrow" title="What this terminal is playing at '
      + 'overall - the master, above the three balances. In the desk app '
      + 'this is the application volume; on the tablet it is the level of '
      + 'the player itself."><span>here</span>'
      + '<input id="plDeskLocal" type="range" min="0" max="100" step="1">'
      + '<i id="plDeskLocalVal"></i></label>'
      + '<label class="pl-deskrow" title="How loud clips and sound effects play on this terminal."><span>clips / sfx</span>'
      + '<input id="plDeskSfx" type="range" min="0" max="100" step="1">'
      + '<i id="plDeskSfxVal"></i></label>'
      /* [#1187]: "Offer a slider for setting the volume of videos that play
       * as well."  Everything with a picture and a soundtrack on this glass:
       * the SFX guy's set, the panel's little CRT tube, and - on the tablet -
       * the NATIVE endless wall, which is an ExoPlayer on a SurfaceView and
       * is reached through the bridge rather than through the DOM.
       *
       * 0-100 and no further, deliberately.  This lands on a real
       * <video>.volume (and on ExoPlayer's own volume), which cannot exceed
       * 1; a knob that said 150% would have dead travel on it, which is the
       * lie #1222 exists to remove. */
      + '<label class="pl-deskrow" title="How loud videos play on this '
      + 'terminal - the SFX set, the little CRT tube, and the endless set. '
      + 'A video cannot play louder than itself, so this one stops at 100%. '
      + 'Remembered on this device."><span>videos</span>'
      + '<input id="plDeskVideo" type="range" min="0" max="100" step="1">'
      + '<i id="plDeskVideoVal"></i></label>'
      + '<i class="pl-deskwhy">This terminal only. The station has no '
      + 'per-listener level; these are the desk this panel already has. '
      + '<span id="plDeskWhere"></span></i>'
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
    wireScreenAlone(viewHost);
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
            /* One, two or three taps are three different takes:
             *   1  the whole of what is playing now
             *   2  the last twenty seconds off the ring
             *   3  the last two things SAID, each onto its own pad */
            if (many >= 3) await grabLastTwoClips(say);
            else if (many === 2) await grabLastSeconds(say);
            else await grabWholeOfNow(say);
          } finally {
            pad.classList.remove("busy");
          }
        }, 260);
      });
    }

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
    /* #1194: WHAT THE LABEL IS ALLOWED TO SAY.
     *
     * The number is written from the slider SYNCHRONOUSLY - the thumb never
     * waits on anything - and the honest failure is kept exactly as it was:
     * "(no desk here)" when there is genuinely no road. What must never
     * happen again is that phrase appearing on a screen that is plainly
     * playing music, so it is now driven by a PROVEN answer: the road that
     * setMix took, and, once a crossing has come back, whether the panel
     * actually had the control (law.mixReached). Anything else - a road
     * taken and not yet answered - shows the number alone, because a write
     * in flight is not a failure. */
    const deskSay = (stream, out, value, road) => {
      const law = root.PineAudioLaw;
      const label = el(out);
      if (!label) return;
      const reached = law && law.mixReached ? law.mixReached(stream) : null;
      const gone = !road || reached === false;
      label.textContent = Math.round(Number(value) || 0) + "%"
        + (gone ? " (no desk here)" : "");
      label.classList.toggle("gone", gone);
    };

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
       * live. On the tablet there is no per-pixel cost to pay: this writes a
       * gain node in this page, not a request.
       *
       * ON THE DESK THERE IS A COST, AND IT IS PAID ONCE PER FRAME.
       * "Honor the sliders that I'm setting in the Pine box application,
       *  these are intended to be mixing the signal that I'm listening to."
       * The gain nodes are inside the controlFrame webview - another
       * document - and the only road there is executeJavaScript, one IPC
       * round trip that returns a Promise. So PineAudioLaw.setMix coalesces:
       * a move drops its value into a pending map and books ONE flush on the
       * next animation frame, and while a crossing is in the air later moves
       * only overwrite the map. A 200-pixel drag is therefore a handful of
       * crossings carrying the value that was under the thumb at the time,
       * never one per pixel and never a tail of stale writes landing after
       * the finger stopped. Two rows moved together ride the same crossing. */
      input.addEventListener("input", () => {
        const law = root.PineAudioLaw;
        deskTouched[stream] = Date.now();   /* a read-back must not fight the thumb */
        const bus = videoBus();
        const road = stream !== "duck" && bus
          ? (bus.apply(stream, Number(input.value) / 100) || "bus")
          : law && law.setMix
            ? law.setMix(stream, Number(input.value))
            : (law && law.setLocalMix && law.setLocalMix(stream, Number(input.value)) ? "local" : "");
        deskSay(stream, out, input.value, road);
      });
      /* THE STATION IS ONLY WRITTEN WHERE THERE IS NO LOCAL DESK AT ALL.
       *
       * This branch used to fire on the desk, because localMix() looked for
       * the panel's sliders in THIS document and never found them - so a row
       * labelled "this terminal only" posted a level for every listener on
       * the station the moment the thumb came off it. With the webview road
       * in place mixRoad names a real road there, and this stays what it was
       * meant to be: the last resort, on `change` rather than per pixel
       * because it is a request. */
      input.addEventListener("change", async () => {
        const law = root.PineAudioLaw;
        if (!law) return;
        if (stream !== "duck" && videoBus()) return;
        if (law.mixRoad && law.mixRoad(stream)) return;
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

    /* A crossing that came back unreachable - the panel reloaded under the
     * drawer, or this build has no controlFrame - repaints the labels it
     * touched. Without this the row would sit there reading 120% while
     * nothing had moved, which is the failure this whole change is about,
     * only quieter. */
    const law0 = root.PineAudioLaw;
    if (law0 && law0.onMixReach) {
      law0.onMixReach((reach) => {
        for (const [id2, stream2, out2] of rows) {
          if (!(stream2 in reach)) continue;
          const input2 = el(id2);
          if (!input2) continue;
          deskSay(stream2, out2, input2.value,
            reach[stream2] ? (law0.mixRoad ? law0.mixRoad(stream2) : "panel") : "");
        }
      });
    }
    const shared = videoBus();
    if (shared && typeof shared.onApply === "function" && !desk.dataset.levelWatch) {
      desk.dataset.levelWatch = "1";
      shared.onApply((levels) => {
        for (const [kind, id, out] of [["music", "plDeskMusic", "plDeskMusicVal"],
          ["voice", "plDeskVoice", "plDeskVoiceVal"],
          ["sfx", "plDeskSfx", "plDeskSfxVal"],
          ["video", "plDeskVideo", "plDeskVideoVal"]]) {
          const input = el(id);
          if (!input || document.activeElement === input) continue;
          const pct = Math.round(Number(levels[kind] == null ? 1 : levels[kind]) * 100);
          input.value = String(pct);
          const label = el(out);
          if (label) { label.textContent = pct + "%"; label.classList.remove("gone"); }
        }
      });
    }

    /* ...and the one that is genuinely this terminal's own.
     *
     * #1194: HERE READ 0% ON A SCREEN PLAYING MUSIC, AND 0 WAS NOT TRUE.
     *
     * It wrote law.setLocalVolume, which walks THIS document for
     * #musicPlayer - the station panel's player, which on the desk is
     * inside the controlFrame webview and therefore not in this document at
     * all. Nothing was touched. It then read itself back through
     * law.localVolume, which fell to localStorage.pineMusicVolume; the
     * shell has never written that key (the injected appVolumeScript writes
     * it INSIDE the panel, a different origin and a different store), and
     * Number(null) is 0 with Number.isFinite(0) true, so the "or 1"
     * fallback was unreachable and the row printed 0%. Unread, not silent.
     *
     * So this row now goes through applyVolume, the ladder a few hundred
     * lines above that already knows where this terminal's level lives:
     * #appVolume (the desk's master, which renderer.js carries into every
     * webview), then the law's own local volume, then the panel's music
     * slider, then the element itself. One ladder, one answer, and an
     * honest label when every rung misses. */
    const local = el("plDeskLocal");
    if (local) {
      local.addEventListener("input", () => {
        const want = Number(local.value) / 100;
        /* ONE FRAME, NOT ONE PIXEL, HERE TOO. applyVolume's first rung
         * dispatches `input` on the shell's #appVolume, and renderer.js
         * answers that by injecting its levelling script into three
         * webviews - so a drag down this row would be three IPC crossings
         * per pixel. The label is written from a road PROBE (which rung
         * exists, not which rung fired), so it is still honest in the same
         * frame without waiting for anything. */
        const where = hereApply(want);
        volume = want;
        try { localStorage.setItem("pineListenVolume", String(volume)); }
        catch (err) { /* a locked store must not stop the radio */ }
        const label = el("plDeskLocalVal");
        if (label) {
          label.textContent = local.value + "%" + (where ? "" : " (no desk here)");
          label.classList.toggle("gone", !where);
        }
        const vol = el("plVol");
        if (vol) vol.value = local.value;
      });
    }
    wireLevelRow("sfx", "plDeskSfx", "plDeskSfxVal");
    wireLevelRow("video", "plDeskVideo", "plDeskVideoVal");
  }

  /* [#1187]: THE VIDEOS ROW, ON ITS OWN ROAD.
   *
   * window.pineLevels (audio-law.js, #1192) is the one bus for the four
   * listener levels. It persists to `pineListenerLevels`, moves
   * everything this document owns synchronously, and coalesces the two
   * things that cost a crossing - the shell's injection into its webviews
   * and the tablet's native video wall - onto one animation frame.
   *
   * So this handler is free to fire per pixel: the label and the sound in
   * this window move under the thumb, and nothing queues a tail of stale
   * writes behind the finger. */
  function videoBus() {
    return (root.pineLevels && typeof root.pineLevels.apply === "function")
      ? root.pineLevels : null;
  }

  function listenerLevelNow(kind) {
    const bus = videoBus();
    if (bus) {
      const got = Number((bus.get() || {})[kind]);
      const top = Number((bus.CEIL || {})[kind]) || 1;
      if (Number.isFinite(got)) return Math.max(0, Math.min(top, got));
    }
    try {
      const m = JSON.parse(localStorage.getItem("pineListenerLevels") || "{}") || {};
      const v = Number(m[kind]);
      if (Number.isFinite(v)) return Math.max(0, Math.min(1, v));
    } catch (err) { /* first run */ }
    return 1;
  }

  function wireLevelRow(kind, id, out) {
    const row = el(id);
    if (!row || row.dataset.wired) return;
    row.dataset.wired = "1";
    const label = el(out);
    const paint = (pct, road) => {
      if (!label) return;
      label.textContent = pct + "%" + (road ? "" : " (no video here)");
      label.classList.toggle("gone", !road);
    };
    row.value = String(Math.round(listenerLevelNow(kind) * 100));
    paint(row.value, videoBus() ? "bus" : "");
    row.addEventListener("input", () => {
      deskTouched[kind] = Date.now();     /* a read-back must not fight the thumb */
      const want = Number(row.value) / 100;
      const bus = videoBus();
      let road = "";
      if (bus) {
        road = bus.apply(kind, want) || "bus";
      } else {
        /* No bus in this host: keep the honest old road rather than a dead
         * knob - the store plus whatever mixer this document has. */
        try {
          const m = JSON.parse(localStorage.getItem("pineListenerLevels") || "{}") || {};
          m[kind] = want;
          localStorage.setItem("pineListenerLevels", JSON.stringify(m));
          road = "store";
        } catch (err) { /* private mode */ }
        try {
          if (root.pineMixer && root.pineMixer.set) {
            const patch = {}; patch[kind] = want; root.pineMixer.set(patch);
            road = "mixer";
          }
        } catch (err) { /* the store still moved */ }
      }
      paint(row.value, road);
    });
  }

  /* Read back, but never over a thumb that is still on it. */
  function paintLevelRow(kind, id, out) {
    const row = el(id);
    if (!row) return;
    if (document.activeElement === row) return;
    if (Date.now() - (deskTouched[kind] || 0) < 1200) return;
    const pct = String(Math.round(listenerLevelNow(kind) * 100));
    if (row.value === pct) return;
    row.value = pct;
    const label = el(out);
    if (label) {
      label.textContent = pct + "%";
      label.classList.toggle("gone", !videoBus());
    }
  }

  /* The HERE row's writer and its road probe. The probe is applyVolume's
   * own ladder asked as a question rather than pressed: #appVolume, then
   * the panel's own player, then the panel's music slider. If every rung
   * misses the row says "no desk here", which is the one thing about the
   * old behaviour worth keeping. */
  let hereWant = null;
  let hereBooked = false;
  function hereRoad() {
    if (el("appVolume")) return "app";
    if (el("musicPlayer")) return "player";
    if (el("djGainMusic")) return "panel";
    return "";
  }
  function hereApply(want) {
    hereWant = want;
    if (!hereBooked) {
      hereBooked = true;
      const go = () => {
        hereBooked = false;
        const send = hereWant;
        hereWant = null;
        if (send !== null) applyVolume(send);
      };
      if (typeof root.requestAnimationFrame === "function") root.requestAnimationFrame(go);
      else setTimeout(go, 16);
    }
    return hereRoad();
  }

  /* WHAT THIS TERMINAL IS ACTUALLY PLAYING AT, read from the same ladder
   * applyVolume writes down. #appVolume first because on the desk it is the
   * master every webview is levelled from; then the law, which now returns
   * null rather than 0 for a store that was never written; then whatever
   * this view last set. Never a bare 0 that nobody chose. */
  function hereLevel() {
    const slider = el("appVolume");
    if (slider) {
      const n = Number(slider.value) / 100;
      if (Number.isFinite(n)) return Math.max(0, Math.min(1, n));
    }
    const law = root.PineAudioLaw;
    const mine = law && law.localVolume ? law.localVolume() : null;
    if (mine !== null && mine !== undefined && Number.isFinite(Number(mine))) {
      return Math.max(0, Math.min(1, Number(mine)));
    }
    return Math.max(0, Math.min(1, Number(volume) || 0));
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

  /* THE LAST TWO THINGS SAID, each onto its own pad.
   *
   * "If I tap the sampler dot on the listen tab three times, grab the last
   *  two clips and put those on a sample pad."
   *
   * Two SEPARATE takes, not one welded pair: they are two moments, they get
   * two pads, and the roll across banks puts them wherever there is room.
   * Oldest first, so they land in the order they were said - a pair read
   * back off the pads in the other order is a conversation running
   * backwards.
   *
   * Serialised on purpose. sampler.grab() refuses a second call while one is
   * in flight ("still fetching the last one"), and the measured fetch for a
   * single clip has run from 1.1 s to 13.5 s against a busy station - fired
   * together they would race for the same free pad and one would be lost. */
  async function grabLastTwoClips(say) {
    const sampler = root.PineSampler;
    const feed = root.PineStationFeed;
    if (!sampler || typeof sampler.grab !== "function") {
      say("no sampler here", true);
      return;
    }
    const rows = (feed && feed.rows ? feed.rows() : []) || [];
    const want = [];
    for (let i = rows.length - 1; i >= 0 && want.length < 2; i -= 1) {
      const row = rows[i];
      if (!row || !sampler.takeable(row)) continue;
      if (root.PineListenModel && root.PineListenModel.mediaStale
        && root.PineListenModel.mediaStale(row, Date.now())) continue;
      want.push(row);
    }
    if (!want.length) { say("nothing said has audio behind it", true); return; }
    want.reverse();                       /* oldest first */
    const landed = [];
    for (let i = 0; i < want.length; i += 1) {
      say("keeping " + (i + 1) + " of " + want.length + "…");
      const got = await sampler.grab(want[i]);
      if (got.ok) landed.push("b" + (got.bank + 1) + "p" + (got.pad + 1));
      else { say(got.why, true); return; }
    }
    say(landed.length === 2
      ? "two lines kept · " + landed.join(" and ")
      : "one line kept · " + landed[0]);
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
      const bus = videoBus();
      if (stream !== "duck" && bus) {
        const levels = bus.get() || {};
        const value = Number(levels[stream]);
        const top = Number((bus.CEIL || {})[stream]) || 1;
        input.min = "0";
        input.max = String(Math.round(top * 100));
        input.value = String(Math.round((Number.isFinite(value) ? value : 1) * 100));
        if (label) { label.textContent = input.value + "%"; label.classList.remove("gone"); }
        continue;
      }
      /* THIS TERMINAL'S MIX FIRST, because that is what these knobs move.
       * Reading the station's level here is what put every knob at 50 with
       * "not set" beside it while the real mix was 100 / 160 / 70. */
      const mine = law.localMix ? law.localMix(stream) : null;
      if (mine !== null) {
        const range = law.localMixRange(stream);
        input.min = String(range.min);
        input.max = String(Math.min(range.max, stream === "duck" ? 90 : 200));
        input.value = String(Math.round(mine));
        if (label) { label.textContent = Math.round(mine) + "%"; label.classList.remove("gone"); }
        continue;
      }
      /* #1194: THE PANEL'S OWN DESK, FROM THE OTHER SIDE OF THE WEBVIEW.
       *
       * On the desk localMix() is null for all three - the sliders are in
       * the controlFrame document - and the code below then asked the
       * STATION for a level it only publishes when the broadcast device is
       * a Nabu. That is how every row came to read "not set" or a station
       * number while the real mix sat at 100 / 160 / 70 inside the panel.
       * The true values are fetched across the boundary by deskFromPanel()
       * below; what is drawn here first is the last answer it got, so an
       * open drawer always has something true on it rather than a default
       * while one round trip completes. */
      const road = law.mixRoad ? law.mixRoad(stream) : "";
      if (road) {
        const seen = law.mixNow ? law.mixNow() : null;
        const top = law.mixMax ? law.mixMax(stream) : (stream === "duck" ? 90 : 200);
        input.min = "0";
        input.max = String(top);
        const value = seen && typeof seen[stream] === "number" ? seen[stream] : null;
        if (value !== null) {
          input.value = String(Math.min(top, Math.round(value)));
          if (label) { label.textContent = input.value + "%"; label.classList.remove("gone"); }
        }
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
      const here = Math.round(hereLevel() * 100);
      local.value = String(here);
      const label = el("plDeskLocalVal");
      if (label) { label.textContent = here + "%"; label.classList.remove("gone"); }
    }
    paintLevelRow("sfx", "plDeskSfx", "plDeskSfxVal");
    paintLevelRow("video", "plDeskVideo", "plDeskVideoVal");
    /* WHERE THESE KNOBS LAND, SAID ON THE FACE OF THE DRAWER.
     * The operator asked for the sliders to mix what he is hearing; when
     * the desk they reach is in another document he should be able to see
     * that without reading the code. */
    const where = el("plDeskWhere");
    if (where && law.mixRoad) {
      const road = law.mixRoad("music");
      where.textContent = road === "local"
        ? "The mix is this page's own gain."
        : road === "panel"
          ? "Music and duck are the station panel's own gain, reached in "
            + "the control frame; DJs ride this application's voice mix."
          : "";
    }
    /* ...and then the crossing, which fills in what only the panel knows. */
    deskFromPanel();
  }

  /* #1194: ONE CROSSING, AND ONLY WHEN THE DRAWER IS OPEN.
   *
   * paintDesk is called when the drawer opens, not on a timer, so this is
   * not a poller - it is the read half
   * of the same road setMix writes down. It refuses to move a row the
   * operator is holding: a value that landed 200 ms ago and a thumb that is
   * still dragging would fight each other, and the thumb must win. Rows the
   * panel could not show (it reloaded, or this build has no controlFrame)
   * keep the honest label rather than a number nobody set. */
  let deskTouched = {};
  function deskFromPanel() {
    const law = root.PineAudioLaw;
    const desk = el("plDesk");
    if (!law || !law.readMix || !desk || desk.hidden) return;
    law.readMix().then((got) => {
      if (!got) return;
      const open = el("plDesk");
      if (!open || open.hidden) return;
      for (const [id, stream, out] of [["plDeskMusic", "music", "plDeskMusicVal"],
        ["plDeskVoice", "voice", "plDeskVoiceVal"],
        ["plDeskReply", "duck", "plDeskReplyVal"]]) {
        const input = el(id);
        const label = el(out);
        if (!input) continue;
        if (stream !== "duck" && videoBus()) continue;
        if (Date.now() - (deskTouched[stream] || 0) < 1200) continue;   /* the thumb wins */
        const road = stream === "voice" ? (got.voiceRoad || "") : (got.road || "");
        const top = law.mixMax ? law.mixMax(stream) : (stream === "duck" ? 90 : 200);
        input.min = "0";
        input.max = String(top);
        const value = typeof got[stream] === "number" ? got[stream] : null;
        if (value === null || !road) {
          if (label) {
            label.textContent = (input.value || "0") + "% (no desk here)";
            label.classList.add("gone");
          }
          continue;
        }
        input.value = String(Math.min(top, Math.max(0, Math.round(value))));
        if (label) { label.textContent = input.value + "%"; label.classList.remove("gone"); }
      }
    }, () => { /* a panel mid-navigation answers on the next open */ });
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
      /* A hidden view must not burn a frame drawing nothing. document.hidden
       * as well as the box: on the tablet rAF keeps firing with the screen
       * off, and the spectrogram below would scroll for nobody. */
      const host = el("plMeterMusic");
      if (document.hidden) return;
      if (!host || !host.isConnected || !host.clientWidth) return;

      /* Re-attach every frame is cheap (it returns early once tapped) and
       * it is how the DJ players get picked up: the panel creates them
       * lazily, long after this view was built. */
      meters.attach(["musicPlayer"].concat(VOICE_IDS));

      meters.draw(music, meters.read("musicPlayer", "music"), "#54d18b");
      meters.draw(voice, meters.readLoudest(VOICE_IDS, "voice"), "#e3be63");
      drawSpectrogram(meters);

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

  /* ------------------------------------------------------ the line on air
   *
   * "Instead of having the dialogue of the station ... appear in the
   * section ... randomly, let's have a display of a scrolling marquee that
   * is showing the currently playing dialogue that's being spoken
   * scrolling through in an endless marquee ... with an audio spectrogram
   * for the voice dialogue."
   *
   * What sat in this box was #plGrabWhy: grabTarget()'s reason for the
   * "keep this" button - "the line on air", "the last thing said" - which
   * read as a fragment of dialogue turning up at random. It is gone. The
   * box carries the line being SPOKEN, off the very payload.now the grab
   * reads (sampler-feed.js speakingNow(): the stream_now row under the
   * station clock, or speaking_now), and under it a spectrogram of the
   * voice audio this terminal is playing.
   *
   * THE MARQUEE is one CSS animation on a track holding the text twice,
   * translated by exactly one copy per cycle, so the loop has no seam.
   * Its duration is the measured width at ~90 px/s: a long line takes
   * longer to pass, it does not go faster. The track is rebuilt - and so
   * the animation restarted - only when the text changes; checked once a
   * second on the feed's tick, never on a timer of its own (see the
   * single-poller rule in the header). When nothing is being said the
   * last line stays up, dimmed. */
  const MARQUEE_PX_PER_S = 90;
  const SAID_CHECK_MS = 1000;
  let saidAt = 0;
  let saidKey = "";
  let saidWidth = 0;

  function paintSaid(payload) {
    const at = payload.at || Date.now();
    if (at - saidAt < SAID_CHECK_MS) return;
    saidAt = at;
    const box = el("plSaid");
    const track = el("plSaidTrack");
    if (!box || !track) return;
    const now = payload.now;
    const text = now ? String(now.text || "").trim() : "";
    const who = now ? String(now.name || now.who || "") : "";
    box.classList.toggle("dim", !text);
    if (!text) return;
    /* Not measurable while the view is behind another tab; the next check
     * on screen catches both a changed line and a changed width. */
    const width = box.clientWidth;
    if (!width) return;
    const key = who + "\n" + text;
    if (key === saidKey && width === saidWidth) return;
    saidKey = key;
    saidWidth = width;
    buildMarquee(track, who, text, width);
  }

  function buildMarquee(track, who, text, width) {
    track.replaceChildren();
    for (let i = 0; i < 2; i += 1) {
      const copy = document.createElement("span");
      copy.className = "pl-said-copy";
      /* The twin is there for the eye, not the screen reader. */
      if (i) copy.setAttribute("aria-hidden", "true");
      if (who) {
        const name = document.createElement("b");
        name.textContent = who;
        copy.appendChild(name);
      }
      copy.appendChild(document.createTextNode(text));
      /* Never narrower than the box, so a short line still leaves by the
       * left before its twin arrives from the right. */
      copy.style.minWidth = width + "px";
      track.appendChild(copy);
    }
    /* RESTART, DELIBERATELY. Removing the animation, forcing a layout, and
     * putting it back is the one way to make CSS start it again; the
     * width read in between is the measurement the duration needs. The
     * shorthand clears the duration, so it is written after. */
    track.style.animation = "none";
    const one = track.firstElementChild
      ? track.firstElementChild.offsetWidth : width;
    track.style.animation = "";
    track.style.animationDuration =
      Math.max(4, one / MARQUEE_PX_PER_S).toFixed(2) + "s";
  }

  /* THE VOICE SPECTROGRAM. Time runs left to right, frequency bottom to
   * top, loudness as colour on a dark palette. Each frame the picture is
   * shifted one device pixel left by drawing the canvas onto itself, and
   * one new column is written at the right edge - one blit and one
   * 1-px ImageData per frame, whatever the width. It runs inside the
   * meters' requestAnimationFrame tick, so it stops with them: hidden
   * tab, hidden document, or the box gone.
   *
   * WHERE THE NUMBERS COME FROM. The DJS meter reads the louder of the two
   * voice players (VOICE_IDS) through PineMeters, and this reads exactly
   * the same elements. PineMeters.tap(el) hands back the AnalyserNode
   * itself where the bridge publishes it; where it does not (the module
   * as shipped keeps its taps private and publishes read / readLoudest)
   * the folded bars of readLoudest are used - 64 bins of the same
   * fftSize-256 analyser, which is all a 48 px canvas can show. A
   * borrowed analyser (the panel's own audioScope, #1305) is never
   * reconfigured: its fftSize belongs to the panel. When neither road
   * yields a reading nothing is drawn and the box says so once. */
  const SPEC_PALETTE = [
    [0x05, 0x08, 0x0a], [0x1d, 0x4d, 0x5a], [0x65, 0xc7, 0xda], [0xdf, 0xe7, 0xee]
  ];
  let specLut = null;
  let specColumn = null;
  let specBins = null;
  let specSaid = "";

  function specColour(v) {
    if (!specLut) {
      specLut = new Array(256);
      for (let i = 0; i < 256; i += 1) {
        const t = (i / 255) * (SPEC_PALETTE.length - 1);
        const k = Math.min(SPEC_PALETTE.length - 2, Math.floor(t));
        const f = t - k;
        const a = SPEC_PALETTE[k];
        const b = SPEC_PALETTE[k + 1];
        specLut[i] = [
          Math.round(a[0] + (b[0] - a[0]) * f),
          Math.round(a[1] + (b[1] - a[1]) * f),
          Math.round(a[2] + (b[2] - a[2]) * f)
        ];
      }
    }
    return specLut[Math.max(0, Math.min(255, Math.round(v * 255)))];
  }

  /* One column of magnitudes, 0..1, lowest frequency first - or null when
   * nothing can be read. */
  function voiceSpectrum(meters) {
    if (typeof meters.tap === "function") {
      let best = null;
      let bestSum = -1;
      for (const id of VOICE_IDS) {
        const node = document.getElementById(id);
        if (!node || node.paused || node.muted) continue;
        let analyser = null;
        try { analyser = meters.tap(node); } catch (err) { analyser = null; }
        if (!analyser) continue;
        if (!specBins || specBins.length !== analyser.frequencyBinCount) {
          specBins = new Uint8Array(analyser.frequencyBinCount);
        }
        analyser.getByteFrequencyData(specBins);
        let sum = 0;
        for (let i = 0; i < specBins.length; i += 1) sum += specBins[i];
        /* The louder of the two - the rule readLoudest applies. */
        if (sum > bestSum) {
          bestSum = sum;
          best = Array.from(specBins, (b) => b / 255);
        }
      }
      if (best) return best;
    }
    const read = meters.readLoudest(VOICE_IDS, "voice");
    return read ? read.bars : null;
  }

  /* #1151 - "This bar at the bottom isn't working."
   *
   * IT WAS WORKING. It was drawing thirty thousand pixels off the right
   * hand edge of a screen eleven hundred pixels wide. Measured on the
   * tablet with the view up: canvas.width 41120, canvas.height 60, the
   * element's CSS box 32896px inside a .pl-face of 1120px. Every column
   * this function paints goes in at W-1, which by then was x=41119 - so
   * the bar the operator was looking at was the far LEFT of a picture
   * whose only content sat at the far right.
   *
   * IT IS A FEEDBACK LOOP, and it is the oldest one canvas has. A canvas
   * has an intrinsic size - its width and height attributes - and that
   * size is a real input to layout. `.pl-said-spec` is `width:100%`, its
   * parent `.pl-said` is `flex: 1 1 100%` of `.pl-controls`, and
   * `.pl-controls` was a grid item of `.pl-face` with the default
   * `min-width:auto`, so the grid column sized itself to the canvas's
   * intrinsic width rather than to the box it was in. Frame n wrote
   * `canvas.width = clientWidth * dpr`; that made the intrinsic width dpr
   * times bigger; the column grew to match; frame n+1 measured the bigger
   * box. The multiplier is exactly devicePixelRatio, so:
   *
   *   dpr 1    - stable, which is why a plain desk monitor never showed it
   *   dpr 1.25 - the tablet: x1.25 a frame, past 32000px in ~15 frames
   *   dpr 2    - a retina desk: past Chromium's maximum canvas dimension
   *              in six, and a canvas over that limit stops being a canvas
   *              at all. The browser paints it as a BROKEN-IMAGE ICON on a
   *              white box, which is the operator's photograph exactly.
   *
   * It took the rest of the view with it. The grid column was 32896px
   * wide, so the progress bar, the NEXT row and the search box were all
   * stretched thirty thousand pixels off the side of the glass - which is
   * why the vol, sleep, keep and pictures controls were nowhere on the
   * screen either.
   *
   * CUT IN TWO PLACES ON PURPOSE. The stylesheet cuts it properly
   * (`grid-template-columns: minmax(0,1fr)` on .pl-face and `min-width:0`
   * on .pl-controls, listen-music.css), and it is cut AGAIN here, because
   * a stylesheet is one careless edit away from putting it back and the
   * failure mode is a canvas that eats the layout of an entire view.
   * .pl-face is the grid CONTAINER, so its width is a ruler nothing the
   * canvas does can bend. */
  /* CAN THIS TERMINAL HEAR THE DJs AT ALL?
   *
   * #1151, the half of it that is not a layout bug. Measured on the tablet
   * with the show plainly on air: both DJ players existed and both were
   * MUTED - which is the audio law doing its job, because the broadcast
   * was coming out of somewhere else and this panel is not allowed to play
   * a second copy of it. voiceSpectrum skips a muted element and falls
   * back to readLoudest, which answers with sixty-four zeroes rather than
   * with nothing, so the bar drew sixty-four black columns a second and
   * said not one word about why. A bar that is black because the room is
   * quiet and a bar that is black because this window has been gagged look
   * exactly the same, and only one of them is working.
   *
   * Three states, and each gets its own sentence in the strip's own place:
   * no player in the window yet, a player that is muted here, or a live
   * one - in which case the bar speaks for itself and the line stays
   * empty. */
  function voiceReach() {
    let found = 0;
    let live = 0;
    for (const id of VOICE_IDS) {
      const node = document.getElementById(id);
      if (!node) continue;
      found += 1;
      if (!node.muted) live += 1;
    }
    if (!found) return "none";
    return live ? "live" : "muted";
  }

  function drawSpectrogram(meters) {
    const canvas = el("plSaidSpec");
    if (!canvas) return;
    const face = typeof canvas.closest === "function"
      ? canvas.closest(".pl-face") : null;
    const room = (face && face.clientWidth) || root.innerWidth || 0;
    let w = canvas.clientWidth;
    if (room && w > room) w = room;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    const g = canvas.getContext("2d");
    if (!g) return;
    const dpr = Math.min(2, root.devicePixelRatio || 1);
    const W = Math.round(w * dpr);
    const H = Math.round(h * dpr);
    if (canvas.width !== W || canvas.height !== H) {
      canvas.width = W;
      canvas.height = H;
      g.fillStyle = "#05080a";
      g.fillRect(0, 0, W, H);
      specColumn = null;
    }
    const bars = voiceSpectrum(meters);
    const say = el("plSaidNote");
    const reach = bars ? voiceReach() : "";
    const word = !bars
      ? "no voice to draw - this terminal has not been lent an analyser "
        + "for the DJs"
      : reach === "none"
        ? "no DJ player in this window yet - the bar fills the moment the "
          + "pair are given one"
        : reach === "muted"
          ? "the DJ voices are muted in this window, so there is nothing "
            + "here to draw - the show is on air somewhere else"
          : "";
    if (specSaid !== word) {
      specSaid = word;
      if (say) say.textContent = word;
    }
    if (!bars) return;
    /* Shift left by one device pixel. Drawing a canvas onto itself is
     * defined: the source is snapshotted before the write. */
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.drawImage(canvas, -1, 0);
    if (!specColumn || specColumn.height !== H) specColumn = g.createImageData(1, H);
    const px = specColumn.data;
    const n = bars.length;
    for (let y = 0; y < H; y += 1) {
      /* Bottom row is the lowest bin. A gentle curve gives the voice band
       * - the bottom fifth of a 256-point spectrum at 48 kHz - more rows
       * than a straight line would. */
      const frac = 1 - (y + 0.5) / H;
      const bin = Math.min(n - 1, Math.floor(Math.pow(frac, 1.5) * n));
      const c = specColour(bars[bin]);
      const o = y * 4;
      px[o] = c[0]; px[o + 1] = c[1]; px[o + 2] = c[2]; px[o + 3] = 255;
    }
    g.putImageData(specColumn, W - 1, 0);
  }

  /* --------------------------------------------------------------- mount */

  async function mount(host) {
    if (!host || mounted) return;
    config = await api().readConfig();
    /* #1152 / #1150: the host is the element both of those hang a class
     * on, and wire() needs it a moment from now. */
    viewHost = host;
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

  /* THE VEIL LIFTS THE MOMENT THE VIEW GOES. The feed's tick would catch
   * it within a second, but on the tablet timers stop with the screen and
   * a floating set left veiled is a set that has vanished. */
  document.addEventListener("visibilitychange", () => {
    if (!mounted) return;
    paintEndless(Date.now(), true);
    if (!document.hidden) { stir(); return; }
    /* #1152 / #1150: a screen nobody is in front of gets its chrome back,
     * so returning to this view is never returning to a black rectangle
     * with no visible way out. #1147: and the plexus stops - it is a
     * requestAnimationFrame loop, and on the tablet rAF keeps firing with
     * the screen off. */
    /* NOT deliberate, for the same reason the closed view is not: the
     * screen going away is not him changing his mind (#1163). */
    showChrome(false);
    showPlexus(false);
  });

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
