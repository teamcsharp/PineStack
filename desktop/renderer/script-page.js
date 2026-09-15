/* THE SCRIPT VIEW, BUILT TO THE SKETCH.
 *
 * The operator numbered seven regions and said what each one is. They are
 * marked 1..7 through this file so the code and the drawing can be read
 * against each other:
 *
 *   1  back to the ordinary view          top-left, three small buttons
 *   2  a menu of every view
 *   3  reload / re-fit this view
 *   4  the pine tree - taps open a Pine Box panel
 *   5  the media player: art, spectrum, meter, a playhead you can scrub,
 *      and back/forward across tracks
 *   6  the live feed, "like an instant message correspondence", endless and
 *      auto-scrolling
 *   7  the right HALF of the screen: a Hollywood script of the broadcast,
 *      generated live, scrollable, tappable, editable, sendable back to the
 *      recording room
 *
 * WHERE THE SCRIPT COMES FROM, and why this is not a rendering of the feed.
 * #1050 already writes a real screenplay: GET /api/screenplay/{hour} returns
 * typed elements - scene, subheader, character, dialogue, parenthetical,
 * action, transition - with each dialogue carrying the aired line id, its
 * engine, whether it was tinted and its clip. Measured on the live station:
 * 127 elements for one hour, 63 of them dialogue. So this view FORMATS a
 * script the station already generates, rather than inventing one out of
 * chat rows, and the tap targets are real line ids that the rest of the
 * machinery already understands.
 *
 * THE TRAFFIC RULE. One shared feed subscription for the live half (the
 * ticker, the player, the console line) and ONE fetch of the screenplay,
 * refreshed on a slow clock and on demand. Nothing here polls at speed.
 * That rule is not decorative: 38 concurrent requests were measured
 * starving this tablet's audio for 46 seconds.
 */
(function (root) {
  'use strict';

  var HOST_CLASS = 'sp-page';
  var SCREENPLAY_REST_MS = 20000;   /* the script is minutes-scale news */
  var FEED_MAX = 240;               /* the booth ring's own size */

  var mounted = false;
  var host = null;
  var stop = null;
  var elements = [];
  var hourKey = '';
  var scriptNodes = new Map();      /* #1273: element id -> its live node */
  var paintedIn = null;             /* #1273: the box those nodes hang in */
  var chasedAt = 0;                 /* #1271: last re-read chased by a mark */
  var beforeKey = '';               /* #1276: the closed hour we hold */
  var beforePage = null;            /*         and its page, fetched once */
  /* #1269: the join between an element's id and its text. A character no
     id or text can contain, written as an ESCAPE - an earlier patch put a
     real NUL byte in this file, which every text tool then read as binary. */
  var SEP = '\u0000';
  var fetchedAt = 0;
  var fetching = false;
  var pinned = null;                /* the element the operator tapped */
  var stick = true;                 /* keep the script scrolled to the end */
  var feedStick = true;
  var seen = Object.create(null);   /* feed rows already drawn */
  var feedNodes = Object.create(null);  /* #1279: id -> its live row */
  var feedLive = '';                    /* #1279: the row marked airing */

  /* FOLLOWING THE LINE THAT IS ACTUALLY BEING SAID.
   *
   * "I need the currently spoken line that is being said to be the line
   * being highlighted... It is highlighting 20 lines."
   *
   * It was highlighting 71, and for a reason that had nothing to do with
   * speech: the amber marker went on any element whose `aired` was not the
   * string 'stream', and the screenplay's three values are 'published'
   * (59), 'stream' (43) and 'prepared' (12). 'published' means it ALREADY
   * AIRED. So the mark was on most of the hour.
   *
   * The live position is not in the screenplay at all - it is in the
   * station's `stream_now`: the epoch second the burst began, its length,
   * and every row's from/until offset inside it. That is enough to know
   * which line is in the room RIGHT NOW without asking, so the highlight
   * moves on a local 250 ms tick against a 4 s poll - the cadence the
   * codebase already prescribes ("the round clock every 250 ms,
   * speaking_now every 4 s"), and no extra traffic for a station with a
   * documented history of being starved by chatty clients. */
  var liveStream = null;            /* stream_now, as last polled */
  var speakingNow = null;           /* the 4 s fallback */
  var flow = null;                  /* dialogue_flow: why it is waiting */
  var stationPaused = false;
  var skewMs = 0;                   /* server clock minus ours */
  var lastOffMs = 0;                /* #1267: watched, no longer applied */
  var nowLineId = '';               /* the one line being said */
  var follow = true;                /* keep it on screen */
  var selfScrollUntil = 0;          /* a scroll WE started, not the operator */
  var adrift = 0;                   /* #1282: consecutive off-screen reads */
  var folded = Object.create(null);   /* #1285: seg id -> folded? */
  var byHand = Object.create(null);   /* #1285: the operator said so */
  var liveSeg = '';                   /* #1285: the segment on air */
  var planHours = [];                 /* #1289: the director's entries */
  var planAt = 0;                     /* when we last read them */
  var planning = false;
  var planWay = 'below';              /* #1289: 'below' | 'beside' */
  var PLAN_REST_MS = 30000;           /* a running order is not news */
  var beat = 0;

  /* ------------------------------------------- THE ADMITTED CUE MAP
   *
   * "Render the committed sequence directly. Keep existing positions
   *  stable as new material is appended. Use the selected player's
   *  actual file and offset, mapped through its cue sheet, to identify
   *  the active occurrence."
   *
   * `admitMap` is the station's committed sequence as last polled - the
   * playout controller's own record, not a reconstruction from feed rows
   * and not the server's wall clock. `lastGood` is the last position this
   * view could TRUST, kept so a gap in the evidence shows the last true
   * mark rather than a guess or a blank.
   *
   * And `syncState` is published, because the audit is explicit that
   * hiding this would be the wrong cure: "Merely preventing a backward
   * visual movement would hide an audio fault; it would not enforce
   * playback order." */
  var admitMap = null;
  var lastGood = null;
  var syncState = 'held';
  var syncWhy = 'no playback evidence yet';
  var syncSince = 0;
  var syncRing = [];                  /* bounded: what the mark did, and why */
  var SYNC_RING_MAX = 240;
  var headWas = -1;                   /* the last READ position */
  var headMovedAt = 0;                /* and when it last actually moved */
  var STALL_MS = 8000;                /* read but motionless for this long */

  /* #1115: THE LAST ERRORS THIS PAGE SAW.
   *
   * A report about "the highlighted line is wrong" is worth little
   * without the throw that may have stranded the highlight - and by the
   * time the operator taps, the console that printed it is long gone
   * (on the tablet it was never visible at all: the WebView hides a
   * cross-origin throw behind "Script error."). So the page keeps its
   * own short ring, twelve entries, and ships it with every report. */
  var caught = [];

  function caughtNote(kind, what) {
    var msg = '';
    try {
      if (what && what.message) msg = String(what.message);
      else if (what && what.reason) {
        msg = String((what.reason && what.reason.message) || what.reason);
      } else msg = String(what);
    } catch (err) { msg = '(unprintable)'; }
    caught.push({at: Date.now(), kind: kind, msg: msg.slice(0, 200)});
    if (caught.length > 12) caught.splice(0, caught.length - 12);
  }
  try {
    if (typeof root.addEventListener === 'function') {
      root.addEventListener('error', function (ev) {
        caughtNote('error', (ev && ev.error && ev.error.message) ? ev.error : ev);
      });
      root.addEventListener('unhandledrejection', function (ev) {
        caughtNote('rejection', (ev && ev.reason) || ev);
      });
    }
  } catch (err) { /* an engine without listeners has no errors to keep */ }

  function api() { return root.pineDesktop || {get: function () { return Promise.reject(new Error('no bridge')); }}; }
  function el(id) { return document.getElementById(id); }
  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  /* ------------------------------------------------------------ 1, 2, 3 */

  function buildBar() {
    var bar = make('div', 'sp-bar');

    /* 1 - back to the ordinary view. */
    var back = make('button', 'sp-btn', '←');
    back.title = 'Back to the full Pine Box application';
    back.addEventListener('click', function () {
      if (root.PineViewChrome) root.PineViewChrome.show('control');
      var tech = el('pineViewTab-tech');
      if (tech) tech.click();
    });

    /* 2 - every view, as a menu. A <select> on purpose: the platform's own
     * picker is reachable with a thumb and needs no popup of my own. */
    var pick = make('select', 'sp-pick');
    var views = (root.PineViewChrome && root.PineViewChrome.VIEWS) || [];
    var head = make('option', '', 'views');
    head.value = '';
    pick.appendChild(head);
    for (var i = 0; i < views.length; i += 1) {
      var opt = make('option', '', views[i].label);
      opt.value = views[i].id;
      pick.appendChild(opt);
    }
    pick.addEventListener('change', function () {
      if (!pick.value) return;
      var tab = el('pineViewTab-' + pick.value);
      if (tab) tab.click();
      else if (root.PineViewChrome) root.PineViewChrome.show(pick.value);
      pick.value = '';
    });

    /* 3 - reload / re-fit. Re-reads the script and re-measures the layout,
     * which is the honest meaning of "adjust the view": anything sized by a
     * grid has no geometry until it is visible. */
    var again = make('button', 'sp-btn', '↻');
    again.title = 'Re-read the script and re-fit the view';
    again.addEventListener('click', function () {
      fetchedAt = 0;
      loadScreenplay(true);
      try { root.dispatchEvent(new Event('resize')); } catch (err) { /* old engine */ }
    });

    /* #1303: THE SFX GUY, ON A PICTURE, ON THE OPERATOR'S THUMB.
     *
     * Carbon out of the vendored set through pineIcon() - the house
     * rule is monochromatic Carbon and never an emoji, and the set is
     * checked before choosing. It posts the `video` road #1303 built
     * and reports what the air actually did with it: a button that
     * cues the broadcast must not be silent about whether it took. */
    var reel = make('button', 'sp-btn sp-reel', '');
    reel.title = 'Cue the SFX guy to play a random video on the broadcast';
    reel.setAttribute('aria-label', 'Play a random video clip');
    try {
      if (typeof root.pineIcon === 'function') {
        reel.innerHTML = root.pineIcon('m:video_library',
                                       'Play a random video clip');
      }
    } catch (err) { /* the title still names it */ }
    if (!reel.innerHTML) reel.textContent = 'video';
    /* #1311b: RAPID FIRE MEANS EVERY TAP COUNTS.
     *
     * This disabled the button for the length of the request, so at
     * anything faster than one tap a second the second, third and
     * fourth taps were simply swallowed - measured, five taps and the
     * picture never changed after the first. The operator asked to
     * "tap on the button, rapid fire, and have it cycle between
     * videos", so nothing is refused; a sequence number keeps a slow
     * answer from landing on top of a faster one that came after it. */
    reel.addEventListener('click', function () {
      if (reel.pineHeld) return;  /* 2026-09-14: the hold opened the folder sheet */
      reel.classList.add('sp-firing');
      fireVideo(reel);
    });
    /* 2026-09-14: HOLD IT (or right-click it) for where the clips come
     * from - the folder sheet, holdOpen() below. */
    holdOpen(reel, folderOpen);

    /* #1385 (#1108): THE PLAY BUTTON NEXT TO THE VIDEO BUTTON.
     *
     * "Put a play button next to the video button that ... puts the SFX
     *  guy into video play mode where the videos are being played one
     *  after another chosen from random from the collection."
     *
     * The mode is the station's (#1366, /api/sfx/video/mode) and it is
     * a held setting, so this button only reports and flips it; the set
     * keeps running through a restart and this view coming and going. */
    var loop = make('button', 'sp-btn sp-loop', '');
    loop.title = 'Endless video: the SFX guy plays clips one after another, at random';
    loop.setAttribute('aria-label', 'Endless video on or off');
    try {
      if (typeof root.pineIcon === 'function') {
        loop.innerHTML = root.pineIcon('c:renew', 'Endless video');
      }
    } catch (err) { /* the title still names it */ }
    if (!loop.innerHTML) loop.textContent = 'loop';
    loop.addEventListener('click', function () { loopToggle(loop); });
    setTimeout(function () { loopRead(loop); }, 900);

    /* #1385 (#1110): find a word that was said on the air. */
    var find = make('input', 'sp-find', '');
    find.type = 'search';
    find.placeholder = 'find a word said on air';
    find.title = 'Every time this word was said on the air in the last two days, and why it keeps being said';
    find.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') { ev.preventDefault(); findOpen(find.value); }
    });

    /* #1115: THE SCRIPT ICON THAT FILES A REPORT.
     *
     * "place an icon here of a script that I can tap whenever the
     *  script view is not displaying the active line being said
     *  correctly. Whenever I tap the icon, place a report in the Pine
     *  inbox, along with capturing advanced diagnostic information of
     *  the script, the placement of the cursor, the activity happening
     *  with the server, and why the script display isn't displaying
     *  the active line being spoken ... capture yourself an image of a
     *  screenshot of the display of the script or the display that I'm
     *  looking at so you can see what I'm seeing."
     *
     * Everything the page knows about the highlight - the lit node and
     * whether it is even in the pane, what activeRow() and the read
     * playhead say, the scroll geometry, the errors it caught - goes to
     * /api/script/report with a picture where the chrome can take one
     * and a plain-text print of the visible script where it cannot.
     * The station adds its own reading and files the inbox report. */
    var report = make('button', 'sp-btn sp-report', '');
    report.title = 'The highlighted line is wrong? Tap: a picture of this view and everything the page knows goes to the Pine inbox';
    report.setAttribute('aria-label', 'Report the script view');
    try {
      if (typeof root.pineIcon === 'function') {
        report.innerHTML = root.pineIcon('c:script', 'Report the script view');
      }
    } catch (err) { /* the title still names it */ }
    if (!report.innerHTML) report.textContent = 'report';
    report.addEventListener('click', function () {
      if (report.pineHeld) return;  /* 2026-09-14: the hold opened the inbox */
      reportFire(report);
    });
    /* 2026-09-14: HOLD IT (or right-click it) for the Pine inbox itself -
     * what has been filed, read here, and deleted here. */
    holdOpen(report, inboxOpen);

    bar.appendChild(back);
    bar.appendChild(pick);
    bar.appendChild(reel);                                   /* #1303 */
    bar.appendChild(loop);                                   /* #1385 */
    bar.appendChild(find);                                   /* #1385 */
    bar.appendChild(report);                                 /* #1115 */
    bar.appendChild(again);
    return bar;
  }

  /* #1298: WHAT IS BEING SAID, BESIDE THE TREE.
   *
   * The words come from activeRow() - the same answer the highlight
   * uses, so the strip and the script can never disagree. The speaker
   * is the nearest preceding character heading, which is how the
   * screenplay says it; a clip has no heading, because it is an action
   * line, so it is named as a clip instead of being given a voice it
   * does not have. */
  function buildSaying() {
    var box = make('div', 'sp-saying');
    box.id = 'spSaying';
    var body = make('div', 'sp-saying-body');
    var who = make('div', 'sp-saying-who', '');
    who.id = 'spSayingWho';
    var text = make('div', 'sp-saying-text', '');
    text.id = 'spSayingText';
    body.appendChild(who);
    body.appendChild(text);
    var scope = document.createElement('canvas');
    scope.className = 'sp-saying-scope';
    scope.id = 'spSayingScope';
    box.appendChild(body);
    box.appendChild(scope);
    /* #1303b: TAP JUMPS, HOLD OPENS.
     *
     * A tap takes the reader to the line the strip is quoting; a hold
     * opens that line's own detail panel - the same one the script's
     * elements open, so "manage this clip, inspect it" is the surface
     * that already exists rather than a second one that would drift
     * from it.
     *
     * Told apart by time AND by movement, because on a tablet every
     * tap begins as a touch that might become a scroll: 500ms without
     * wandering more than a few pixels is a hold, a drag cancels
     * both, and the click that follows a fired hold is swallowed. */
    var holdTimer = 0;
    var heldAt = null;
    var holdFired = false;

    function holdOff() {
      if (holdTimer) { clearTimeout(holdTimer); holdTimer = 0; }
      heldAt = null;
    }

    box.addEventListener('pointerdown', function (ev) {
      holdFired = false;
      heldAt = {x: ev.clientX, y: ev.clientY};
      if (holdTimer) clearTimeout(holdTimer);
      holdTimer = setTimeout(function () {
        holdTimer = 0;
        holdFired = true;
        openSaying();
      }, 500);
    });
    box.addEventListener('pointermove', function (ev) {
      if (!heldAt) return;
      if (Math.abs(ev.clientX - heldAt.x) > 8
          || Math.abs(ev.clientY - heldAt.y) > 8) holdOff();
    });
    box.addEventListener('pointerup', holdOff);
    box.addEventListener('pointercancel', function () {
      holdOff(); holdFired = false;
    });
    box.addEventListener('click', function (ev) {
      if (holdFired) {                 /* the hold already answered */
        holdFired = false;
        ev.preventDefault();
        ev.stopPropagation();
        return;
      }
      if (nowLineId) jumpToLine(nowLineId);
    });
    return box;
  }

  /* #1303b: the live line's own detail panel, off the strip.
   *
   * The node carries the current item (see paintScript), so this opens
   * what the line says NOW rather than what it said when its node was
   * first built. */
  function openSaying() {
    if (!nowLineId) return;
    var node = document.querySelector('.sp-el[data-line="' + nowLineId + '"]');
    if (!node || !node.pineItem) return;
    jumpToLine(nowLineId);
    openLine(node.pineItem, node);
  }

  /* Who says this line, the way the screenplay says it: the nearest
     character heading above it. */
  function sayingWho(node) {
    var walk = node;
    while (walk) {
      if (/sp-character/.test(walk.className || '')) {
        return String(walk.textContent || '').trim();
      }
      walk = walk.previousElementSibling;
    }
    return '';
  }

  var sayingSaid = '';

  function paintSaying(row) {
    var who = el('spSayingWho');
    var text = el('spSayingText');
    if (!who || !text) return;
    /* #1311: an answer the operator asked for outranks the line for a
       few seconds - see say(). */
    if (sayUntil && Date.now() < sayUntil) return;
    var node = (row && row.id)
      ? document.querySelector('.sp-el[data-line="' + row.id + '"]')
      : null;
    var body = node ? String(node.textContent || '').trim() : '';
    var name = '';
    if (node && /sp-dialogue/.test(node.className)) {
      name = sayingWho(node);
    } else if (node) {
      /* An action line IS the clip - "A sting off the board: 344 clip
         (0:35)" - so it is labelled as one rather than attributed. */
      name = 'CLIP';
    }
    if (!body) {
      name = '';
      body = soundingPlayer() ? 'sounding' : 'the room is quiet';
    }
    var print = name + '\u0001' + body;
    if (print === sayingSaid) return;         /* no needless repaint */
    sayingSaid = print;
    who.textContent = name;
    text.textContent = body;
    host.classList.toggle('sp-saying-idle', !node);
  }

  /* THE SPECTRUM, OFF THE PANEL'S OWN ANALYSER.
   *
   * window.audioScope memoises one analyser per element and adopts
   * window.pineAudioCtx; sampler-air.js wraps that same function
   * because a second createMediaElementSource on one element throws.
   * So this never builds a context or a source - it asks for the one
   * that exists.
   *
   * On rAF rather than a timer: this tablet's WebView suspends JS
   * timers and keeps firing rAF (#1241), so rAF is the only clock here
   * that does not freeze. */
  var scopeFrame = 0;
  var scopeWide = 0;
  var scopeHigh = 0;

  /* #1413: THE SCOPE AT A TABLET'S PACE. Profiled on the PineTab
     2026-09-14 over the WebView's devtools socket: this loop and the
     panel's drawScope were a quarter of the page's main thread, at
     60 fps, and the clientWidth/offsetParent reads here forced a layout
     of a document the feed keeps dirty - Chromium's own "(program)"
     was 43% on top. The kiosk sat at 250% CPU with the video set OFF,
     and the native audio engine shares those cores; that is the
     stutter. Every 4th frame on Android, every 2nd elsewhere, and the
     layout reads once a second. */
  /* #1413d: the panel paces requestAnimationFrame itself on the tablet
     (window.PINE_PACE > 1), so the view draws on every paced frame there
     and on every second frame elsewhere. */
  var SCOPE_EVERY = (Number(root.PINE_PACE) > 1) ? 1 : 2;
  var scopeTick = 0;
  var scopeSizeAt = 0;
  var scopeSeen = false;
  function paintScope() {
    scopeFrame = root.requestAnimationFrame(paintScope);
    scopeTick = (scopeTick + 1) % SCOPE_EVERY;
    if (scopeTick) return;
    var canvas = el('spSayingScope');
    if (!canvas) return;
    var dpr = root.devicePixelRatio || 1;
    var nowMs = Date.now();
    if (nowMs - scopeSizeAt > 1000) {
      scopeSizeAt = nowMs;
      /* #745's lesson, on our own canvas: it costs nothing while it
         cannot be seen. */
      scopeSeen = !!canvas.offsetParent;
      if (scopeSeen) {
        var wide = Math.round(canvas.clientWidth * dpr);
        var high = Math.round(canvas.clientHeight * dpr);
        /* #745 again: writing canvas.width resets the whole 2D context, so
           it is measured and compared, never assigned every frame. */
        if (wide && high && (wide !== scopeWide || high !== scopeHigh)) {
          canvas.width = wide; canvas.height = high;
          scopeWide = wide; scopeHigh = high;
        }
      }
    }
    if (!scopeSeen) return;
    var player = soundingPlayer();
    var ctx2d = null;
    try { ctx2d = canvas.getContext('2d'); } catch (err) { return; }
    if (!ctx2d) return;
    if (!scopeWide || !scopeHigh) return;
    ctx2d.clearRect(0, 0, scopeWide, scopeHigh);
    var scope = null;
    if (player && typeof root.audioScope === 'function') {
      try { scope = root.audioScope(player); } catch (err) { scope = null; }
    }
    var bins = scope && scope.bins;
    if (!scope || !bins) {
      /* A flat line is the honest picture of silence. */
      ctx2d.fillStyle = 'rgba(101, 199, 218, .22)';
      ctx2d.fillRect(0, Math.floor(scopeHigh / 2), scopeWide, Math.max(1, dpr));
      return;
    }
    try { scope.analyser.getByteFrequencyData(bins); } catch (err) { return; }
    var bars = 22;
    var step = Math.max(1, Math.floor(bins.length / bars));
    var gap = Math.max(1, Math.round(dpr));
    var span = scopeWide / bars;
    ctx2d.fillStyle = 'rgba(101, 199, 218, .85)';
    for (var b = 0; b < bars; b += 1) {
      var sum = 0;
      for (var k = 0; k < step; k += 1) sum += bins[(b * step) + k] || 0;
      var level = (sum / step) / 255;
      var tall = Math.max(dpr, level * scopeHigh);
      ctx2d.fillRect(Math.round(b * span), Math.round(scopeHigh - tall),
        Math.max(1, Math.round(span) - gap), Math.round(tall));
    }
  }

  /* #1303: cue a video, and say what came back.
   *
   * Through the bridge's own post(), the way sendNote and sendBack
   * already talk to the station - not a hand-rolled fetch that would
   * have to re-derive the base URL and the key for itself. The answer
   * lands on the strip, because a button that cues the air should
   * never be silent about whether the air took it. */
  var reelTurn = 0;

  /* ---- #1385: the endless set ----------------------------------- */
  var loopOn = false;

  function loopPaint(btn) {
    if (!btn) return;
    btn.classList.toggle('on', !!loopOn);
    btn.title = loopOn
      ? 'Endless video is ON - tap to stop after the clip on the tube'
      : 'Endless video: the SFX guy plays clips one after another, at random';
  }

  function loopRead(btn) {
    if (!api() || !api().get) return;
    Promise.resolve(api().get('/api/sfx/video/mode')).then(function (got) {
      loopOn = !!(got && got.on);
      loopPaint(btn);
    }, function () { /* asked again next time */ });
  }

  function loopToggle(btn) {
    if (!api() || !api().post) return;
    var want = !loopOn;
    loopOn = want;
    loopPaint(btn);
    Promise.resolve(api().post('/api/sfx/video/mode', {on: want})).then(function (got) {
      loopOn = !!(got && got.on !== undefined ? got.on : want);
      loopPaint(btn);
      say(loopOn ? 'endless video is on - one clip after another'
                 : 'endless video is off - back to the dial');
    }, function (err) {
      loopOn = !want;
      loopPaint(btn);
      say('the station did not answer: ' + String((err && err.message) || err).slice(0, 60));
    });
  }

  /* ---- 2026-09-14: the folder sheet ------------------------------ */

  /* WHERE THE CLIPS COME FROM, ON A HOLD OF THE VIDEO BUTTON.
   *
   * "If I tap and hold on this button, show a dialogue window that
   *  allows me to specify what folder out of all the folders in the
   *  SFX collection clips are being taken out of for the next hour. At
   *  the top of the window, offer a slider for how many hours we're
   *  sticking with the same folder ... scan all the folders and list
   *  all of the folders, allowing me to expand it with a tri and
   *  preview any of the clips inside of it just to see what the folder
   *  contains. And then I want to be able to check a folder and
   *  basically have that folder and subfolders possibly be the active
   *  folder that all clips are used from by the SFX guy for the next
   *  hour or hours. Also the same thing for videos ... endless video
   *  ... that is the same folder that they'll refer to."
   *
   * The station keeps the pin: GET /api/sfx/folders lists every folder
   * of the collection, sorted by path, each with its counts and a
   * handful of samples, plus the pin in force; POST /api/sfx/folder-pin
   * sets one (its subfolders included) for so many hours, or clears
   * it. The SFX guy - the random sting, the cue button and the endless
   * set alike - draws from the pinned folder until the pin runs out.
   * This sheet only draws what the station said and posts what the
   * operator chose; nothing about the choice lives in the page, so the
   * tablet and the desk always show the same pin.
   *
   * THE HOLD. A short tap still cues a video exactly as before - the
   * operator taps that button rapid fire and every tap must count
   * (#1311b). The sheet opens on a hold of half a second with the
   * finger still (eight pixels of travel is a scroll, not a hold), or
   * on a right-click at the desk. The click the platform fires after a
   * hold is swallowed, once, so the sheet never opens with a clip cued
   * underneath it; the next pointerdown starts a fresh gesture. The
   * same hold (holdOpen) serves the caution button and the report icon
   * below: the held flag rides the button, and the click handler of
   * each checks it first.
   *
   * THE PREVIEWS. A folder's samples are built when its caret opens
   * and torn down when it closes, and one folder is open at a time -
   * six media elements at most on a tablet whose WebView has gone deaf
   * under far less. Media is released (paused, src dropped, load()),
   * not merely detached: a detached <video> can hold its decoder. */
  var FOLDER_HOLD_MS = 500;
  var FOLDER_HOLD_PX = 8;
  var FOLDER_CAP = 300;             /* rows drawn at once; filter for the rest */
  var FOLDER_SAMPLES = 6;           /* previews per open folder */
  var folderData = null;            /* the station's last answer */
  var folderPin = null;             /* the pin in force, as last told */
  var folderSayTimer = 0;

  function holdOpen(btn, open) {
    var timer = 0, x0 = 0, y0 = 0;
    function cancel() { if (timer) clearTimeout(timer); timer = 0; }
    btn.addEventListener('pointerdown', function (ev) {
      btn.pineHeld = false;         /* a new gesture; the last hold is spent */
      if (ev.button !== undefined && ev.button !== 0) return;   /* the right button has its own road below */
      cancel();
      x0 = ev.clientX; y0 = ev.clientY;
      timer = setTimeout(function () {
        timer = 0;
        btn.pineHeld = true;
        open();
      }, FOLDER_HOLD_MS);
    });
    btn.addEventListener('pointermove', function (ev) {
      if (!timer) return;
      if (Math.abs(ev.clientX - x0) > FOLDER_HOLD_PX || Math.abs(ev.clientY - y0) > FOLDER_HOLD_PX) cancel();
    });
    btn.addEventListener('pointerup', cancel);
    btn.addEventListener('pointercancel', cancel);
    btn.addEventListener('pointerleave', cancel);
    /* The desk's right-click, and the tablet's own long-press menu,
       which the WebView raises at about the same half second: either
       way the sheet is the answer and the platform's menu is not. */
    btn.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      cancel();
      if (btn.pineHeld) return;     /* the hold got there first */
      btn.pineHeld = true;
      open();
    });
  }

  function folderClose() {
    var old = el('spFolderSheet');
    if (!old) return;
    folderMediaDrop(old);
    old.remove();
  }

  function folderMediaDrop(node) {
    var media = node.querySelectorAll('audio, video');
    for (var i = 0; i < media.length; i += 1) {
      try { media[i].pause(); media[i].removeAttribute('src'); media[i].load(); } catch (err) { /* already gone */ }
    }
  }

  /* The set's rule (#1399): served by the station - the kiosk's
     loopback door, or any http page - the path is already right; at
     the desk, in a file: page, the chrome knows the station's base and
     the loopback is the same fallback the set uses. */
  function stationUrl(u) {
    u = String(u || '');
    if (!u || /^https?:\/\//.test(u)) return u;
    var proto = '';
    try { proto = String(root.location && root.location.protocol); } catch (err) { proto = ''; }
    if (/^https?:$/.test(proto)) return u;
    var b = '';
    try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; } catch (err) { b = ''; }
    return (b || 'http://127.0.0.1:8096').replace(/\/$/, '') + u;
  }

  function folderIcon(name, label) {
    var out = '';
    try { if (typeof root.pineIcon === 'function') out = root.pineIcon(name, label); } catch (err) { out = ''; }
    return out || '';
  }

  function folderNum(n) {
    n = Number(n) || 0;
    try { return n.toLocaleString('en-US'); } catch (err) { return String(n); }
  }

  function folderLen(s) {
    s = Math.max(0, Math.round(Number(s) || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return (h ? h + ':' + (m < 10 ? '0' : '') : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }

  function folderLeft(pin) {
    var mins = 0;
    if (pin && typeof pin.hours_left === 'number') mins = pin.hours_left * 60;
    else if (pin && pin.until) mins = (Number(pin.until) * 1000 - (Date.now() + skewMs)) / 60000;
    mins = Math.max(0, Math.round(mins));
    if (mins < 90) return mins + ' min';
    var h = Math.floor(mins / 60), m = mins % 60;
    return h + ' h' + (m ? ' ' + m + ' min' : '');
  }

  function folderHoursLabel(n) {
    n = Number(n) || 1;
    return 'for the next ' + (n === 1 ? 'hour' : n + ' hours');
  }

  function folderOpen() {
    if (!api() || !api().get) return;
    folderClose();
    var back = make('div', 'sp-find-back sp-folder-back');
    back.id = 'spFolderSheet';
    var box = make('div', 'sp-find-box sp-folder-box');
    var head = make('div', 'sp-find-head');
    head.appendChild(make('b', null, 'Where the clips come from'));
    var x = make('button', 'sp-find-x', '\u00d7');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    x.addEventListener('click', folderClose);
    head.appendChild(x);
    box.appendChild(head);
    var sayLine = make('div', 'sp-folder-say', '');
    sayLine.id = 'spFolderSay';
    sayLine.hidden = true;
    box.appendChild(sayLine);

    /* The top: how long a pin holds, what is pinned now, a way out of
       it, and a filter for a collection with hundreds of folders. */
    var top = make('div', 'sp-folder-top');
    var hoursRow = make('label', 'sp-folder-hours-row');
    var hoursLabel = make('span', 'sp-folder-hours-label', folderHoursLabel(1));
    var hours = make('input', 'sp-folder-hours');
    hours.type = 'range'; hours.min = '1'; hours.max = '12'; hours.step = '1'; hours.value = '1';
    hours.id = 'spFolderHours';
    hours.setAttribute('aria-label', 'How many hours a pinned folder holds');
    hours.addEventListener('input', function () { hoursLabel.textContent = folderHoursLabel(hours.value); });
    hoursRow.appendChild(hoursLabel);
    hoursRow.appendChild(hours);
    top.appendChild(hoursRow);
    var pinRow = make('div', 'sp-folder-pin-row');
    var pinLine = make('div', 'sp-folder-pin', 'asking the station\u2026');
    pinLine.id = 'spFolderPin';
    pinRow.appendChild(pinLine);
    var clear = make('button', 'sp-folder-clear', 'Clear the pin');
    clear.type = 'button';
    clear.id = 'spFolderClear';
    clear.hidden = true;
    clear.addEventListener('click', function () { folderPost({clear: true, path: ''}); });
    pinRow.appendChild(clear);
    top.appendChild(pinRow);
    var filter = make('input', 'sp-folder-filter');
    filter.type = 'search';
    filter.id = 'spFolderFilter';
    filter.placeholder = 'filter folders by name';
    filter.setAttribute('aria-label', 'Filter folders by name');
    var filterTimer = 0;
    filter.addEventListener('input', function () {
      if (filterTimer) clearTimeout(filterTimer);
      filterTimer = setTimeout(function () { filterTimer = 0; folderPaint(); }, 150);
    });
    top.appendChild(filter);
    box.appendChild(top);

    var list = make('div', 'sp-folder-list');
    list.id = 'spFolderList';
    list.appendChild(make('div', 'sp-folder-note', 'scanning the collection\u2026'));
    box.appendChild(list);
    back.appendChild(box);
    back.addEventListener('click', function (ev) { if (ev.target === back) folderClose(); });
    document.body.appendChild(back);

    Promise.resolve(api().get('/api/sfx/folders')).then(function (d) {
      if (!el('spFolderSheet')) return;       /* closed before the answer */
      if (!d || d.ok === false) {
        folderData = null;
        list.textContent = '';
        list.appendChild(make('div', 'sp-folder-note', 'the station did not answer: ' + String((d && d.say) || 'no folders').slice(0, 120)));
        folderPinPaint(null);
        return;
      }
      folderData = d;
      folderPinPaint(d.pin || null);
      folderPaint();
    }, function (err) {
      if (!el('spFolderSheet')) return;
      list.textContent = '';
      list.appendChild(make('div', 'sp-folder-note', 'the station did not answer: ' + String((err && err.message) || err).slice(0, 80)));
    });
  }

  function folderPinPaint(pin) {
    folderPin = pin && pin.path ? pin : null;
    var line = el('spFolderPin'), clear = el('spFolderClear');
    if (line) {
      line.textContent = folderPin
        ? 'all clips come from ' + (folderPin.name || folderPin.path) + ' for another ' + folderLeft(folderPin)
          + (folderPin.subfolders === false ? '' : ' (subfolders too)')
        : 'every folder - no pin';
      line.classList.toggle('on', !!folderPin);
    }
    if (clear) clear.hidden = !folderPin;
    /* The check marks, without redrawing the list: an open folder
       stays open with its previews. */
    var list = el('spFolderList');
    if (!list) return;
    var rows = list.querySelectorAll('.sp-folder-row');
    for (var i = 0; i < rows.length; i += 1) folderCheckPaint(rows[i]);
  }

  function folderCheckPaint(row) {
    var path = row.pineFolderPath || '';
    var check = row.querySelector('.sp-folder-check');
    if (!check) return;
    var exact = !!(folderPin && folderPin.path === path);
    var under = !exact && !!(folderPin && folderPin.subfolders !== false && path.indexOf(folderPin.path + '/') === 0);
    var hours = el('spFolderHours');
    check.innerHTML = folderIcon(exact ? 'c:checkbox--checked' : 'c:checkbox', exact ? 'Pinned - tap to clear' : 'Pin this folder');
    if (!check.innerHTML) check.textContent = exact ? '[x]' : '[ ]';
    check.setAttribute('aria-pressed', exact ? 'true' : 'false');
    check.title = exact ? 'Pinned - tap to clear the pin'
      : under ? 'Inside the pinned folder - tap to pin this one instead'
      : 'Pin this folder ' + folderHoursLabel(hours && hours.value);
    row.classList.toggle('pinned', exact);
    row.classList.toggle('under', under);
  }

  function folderPaint() {
    var list = el('spFolderList');
    if (!list || !folderData) return;
    folderMediaDrop(list);
    list.textContent = '';
    var all = folderData.folders || [];
    var filter = el('spFolderFilter');
    var q = filter ? String(filter.value || '').trim().toLowerCase() : '';
    /* Depth is the count of "/" beyond the shallowest folder listed. */
    var base = -1, i, f, slashes;
    for (i = 0; i < all.length; i += 1) {
      slashes = String(all[i].path || '').split('/').length;
      if (base < 0 || slashes < base) base = slashes;
    }
    var shown = 0, matched = 0;
    for (i = 0; i < all.length; i += 1) {
      f = all[i] || {};
      var path = String(f.path || '');
      var name = String(f.name || path);
      if (q && name.toLowerCase().indexOf(q) < 0 && path.toLowerCase().indexOf(q) < 0) continue;
      matched += 1;
      if (shown >= FOLDER_CAP) continue;
      shown += 1;
      /* Sorted by path, so a folder with children is followed by one. */
      var hasKids = (i + 1 < all.length) && String(all[i + 1].path || '').indexOf(path + '/') === 0;
      list.appendChild(folderRow(f, path.split('/').length - base, hasKids));
    }
    if (!all.length) list.appendChild(make('div', 'sp-folder-note', 'the station listed no folders'));
    else if (!matched) list.appendChild(make('div', 'sp-folder-note', 'no folder is named like that'));
    else if (matched > shown) list.appendChild(make('div', 'sp-folder-note', 'showing ' + folderNum(shown) + ' of ' + folderNum(matched) + ' folders - filter by name for the rest'));
  }

  function folderRow(f, depth, hasKids) {
    var row = make('div', 'sp-folder-row');
    row.pineFolderPath = String(f.path || '');
    row.pineDepth = depth;
    var line = make('div', 'sp-folder-line');
    line.style.paddingLeft = (6 + depth * 18) + 'px';
    var samples = f.samples || [];
    var tri = make('button', 'sp-folder-tri', '');
    tri.type = 'button';
    tri.setAttribute('aria-expanded', 'false');
    tri.innerHTML = folderIcon('c:caret--right', 'Show what is inside');
    if (!tri.innerHTML) tri.textContent = '>';
    if (!samples.length) {
      tri.disabled = true;
      tri.title = 'nothing to preview';
    } else {
      tri.title = 'Preview a few clips from this folder';
      tri.addEventListener('click', function (ev) { ev.stopPropagation(); folderToggle(row, samples); });
    }
    /* The box pins the folder for the slider's hours; on the folder
       already pinned it clears the pin, so one row is the whole switch. */
    var check = make('button', 'sp-folder-check', '');
    check.type = 'button';
    check.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var hours = el('spFolderHours');
      if (folderPin && folderPin.path === row.pineFolderPath) folderPost({clear: true, path: ''});
      else folderPost({path: row.pineFolderPath, hours: Math.min(12, Math.max(1, Number(hours && hours.value) || 1))});
    });
    var ico = make('span', 'sp-folder-ico', '');
    ico.innerHTML = folderIcon(hasKids ? 'c:folders' : 'c:folder', '');
    var name = make('span', 'sp-folder-name', String(f.name || f.path || ''));
    name.title = String(f.path || '');
    if (samples.length) name.addEventListener('click', function () { folderToggle(row, samples); });
    var bits = [];
    if (f.audio) bits.push(folderNum(f.audio) + (Number(f.audio) === 1 ? ' sound' : ' sounds'));
    if (f.video) bits.push(folderNum(f.video) + (Number(f.video) === 1 ? ' video' : ' videos'));
    var n = make('span', 'sp-folder-n', bits.join(' \u00b7 ') || 'empty');
    line.appendChild(tri);
    line.appendChild(check);
    line.appendChild(ico);
    line.appendChild(name);
    line.appendChild(n);
    row.appendChild(line);
    folderCheckPaint(row);
    return row;
  }

  function folderToggle(row, samples) {
    var tri = row.querySelector('.sp-folder-tri');
    var panel = row.querySelector('.sp-folder-samples');
    if (row.classList.contains('open')) {
      if (panel) { folderMediaDrop(panel); panel.remove(); }
      row.classList.remove('open');
      if (tri) tri.setAttribute('aria-expanded', 'false');
      return;
    }
    /* One folder open at a time: however many the operator looks
       into, the page holds one folder's previews. */
    var list = el('spFolderList');
    if (list) {
      var opened = list.querySelectorAll('.sp-folder-row.open');
      for (var i = 0; i < opened.length; i += 1) folderToggle(opened[i], []);
    }
    panel = make('div', 'sp-folder-samples');
    panel.style.paddingLeft = (52 + (row.pineDepth || 0) * 18) + 'px';
    for (var j = 0; j < samples.length && j < FOLDER_SAMPLES; j += 1) panel.appendChild(folderSample(samples[j]));
    row.appendChild(panel);
    row.classList.add('open');
    if (tri) tri.setAttribute('aria-expanded', 'true');
  }

  function folderSample(s) {
    s = s || {};
    var item = make('div', 'sp-folder-sample');
    var top = make('div', 'sp-folder-sample-line');
    var kind = make('span', 'sp-folder-kind', '');
    if (s.video) kind.textContent = 'video';
    else {
      kind.innerHTML = folderIcon('c:music', 'sound');
      if (!kind.innerHTML) kind.textContent = 'sound';
    }
    top.appendChild(kind);
    top.appendChild(make('span', 'sp-folder-sample-name', String(s.name || s.id || '')));
    var len = make('span', 'sp-folder-sample-len', '');
    len.innerHTML = folderIcon('c:time', '');
    len.appendChild(document.createTextNode(folderLen(s.seconds)));
    top.appendChild(len);
    item.appendChild(top);
    var media;
    if (s.video) {
      media = document.createElement('video');
      media.setAttribute('playsinline', '');
      media.muted = true;
      media.setAttribute('muted', '');
      media.style.maxHeight = '120px';
    } else {
      media = document.createElement('audio');
    }
    media.controls = true;
    media.preload = 'none';
    media.className = 'sp-folder-media';
    media.src = stationUrl(s.url);
    item.appendChild(media);
    return item;
  }

  function folderPost(body) {
    if (!api() || !api().post) { folderSay('no bridge to the station'); return; }
    folderSay('asking the station\u2026', true);
    Promise.resolve(api().post('/api/sfx/folder-pin', body)).then(function (got) {
      if (!el('spFolderSheet')) return;
      if (!got || got.ok === false) { folderSay(String((got && got.say) || 'the station refused')); return; }
      folderPinPaint(got.pin || null);
      folderSay(String(got.say || (got.pin && got.pin.path ? 'pinned ' + (got.pin.name || got.pin.path) : 'the pin is cleared')));
    }, function (err) {
      folderSay('the station did not answer: ' + String((err && err.message) || err).slice(0, 80));
    });
  }

  /* `say` from the station, under the header, for four seconds. */
  function folderSay(text, hold) {
    var line = el('spFolderSay');
    if (!line) return;
    if (folderSayTimer) clearTimeout(folderSayTimer);
    folderSayTimer = 0;
    line.textContent = String(text || '');
    line.hidden = !line.textContent;
    if (!hold) folderSayTimer = setTimeout(function () { folderSayTimer = 0; line.hidden = true; }, 4000);
  }

  /* ---- 2026-09-14: the reason sheet and the inbox sheet ------------ */

  /* One shell for every sheet this page opens over the view: the
     backdrop that closes on a tap beside the box, the box, the header
     with its title and its x, and a line under the header for what the
     station said (four seconds, unless held). The word search drew the
     first one and the folder sheet above wears the same classes; the
     two sheets below are built from this. */
  function sheetShell(id, cls, title) {
    var old = el(id);
    if (old) old.remove();
    var back = make('div', 'sp-find-back ' + cls + '-back');
    back.id = id;
    /* 2026-09-14: "if I'm interacting with one of the systems that's a
       diagnostic, then duck the broadcast audio" - the reason sheet and
       the inbox are; the SFX folder sheet is a preference and is not. */
    if (root.PineDuck && (id === 'spReasonSheet' || id === 'spInboxSheet')) {
      root.PineDuck.hold('sp-' + id, root.PineDuck.REPORT, back);
    }
    var box = make('div', 'sp-find-box ' + cls + '-box');
    var head = make('div', 'sp-find-head');
    head.appendChild(make('b', null, title));
    var x = make('button', 'sp-find-x', '\u00d7');
    x.type = 'button';
    x.setAttribute('aria-label', 'Close');
    head.appendChild(x);
    box.appendChild(head);
    var sayLine = make('div', 'sp-sheet-say', '');
    sayLine.hidden = true;
    box.appendChild(sayLine);
    back.appendChild(box);
    document.body.appendChild(back);
    function close() { var n = el(id); if (n) n.remove(); }
    x.addEventListener('click', close);
    back.addEventListener('click', function (ev) { if (ev.target === back) close(); });
    var sayTimer = 0;
    return {
      back: back, box: box, head: head, x: x, close: close,
      say: function (text, hold) {
        if (sayTimer) clearTimeout(sayTimer);
        sayTimer = 0;
        sayLine.textContent = String(text || '');
        sayLine.hidden = !sayLine.textContent;
        if (!hold && sayLine.textContent) {
          sayTimer = setTimeout(function () { sayTimer = 0; sayLine.hidden = true; }, 4000);
        }
      }
    };
  }

  /* A. WHY ARE YOU FILING THIS?  A hold (or a right-click) on the
   * caution button. A short tap still files the report on the spot,
   * as it did; the hold first asks what the operator saw, in the
   * operator's own list of complaints, with a place to write or say
   * more. The choices toggle and several may be on; the sentence they
   * make ("The lines are out of order; This is not sequential; custom:
   * ...") rides the same report road as `reason`, and the station
   * leads the inbox summary with it. Dictation borrows the dot's ear
   * (PineTalkDot.captureNext): the dot shows that it is listening, the
   * words land in the box, and a surface without a microphone says so
   * rather than pretending. */
  var REASON_CHOICES = [
    'This was unnatural',
    'Why was the script this way?',
    'This didn\'t flow correctly',
    'The lines are out of order',
    'Why did this jump like this?',
    'This is not sequential'
  ];

  function reasonClose() { var n = el('spReasonSheet'); if (n) n.remove(); }

  function reasonOpen(btn) {
    var sheet = sheetShell('spReasonSheet', 'sp-reason', 'Why are you filing this?');
    var list = make('div', 'sp-reason-list');
    function choice(text) {
      var b = make('button', 'sp-reason-choice', '');
      b.type = 'button';
      b.pineText = text;
      var mark = make('span', 'sp-reason-mark', '');
      b.appendChild(mark);
      b.appendChild(make('span', 'sp-reason-text', text));
      function paint(on) {
        mark.innerHTML = folderIcon(on ? 'c:checkbox--checked' : 'c:checkbox', '');
        if (!mark.innerHTML) mark.textContent = on ? '[x]' : '[ ]';
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.classList.toggle('on', on);
      }
      paint(false);
      b.addEventListener('click', function () { paint(b.getAttribute('aria-pressed') !== 'true'); });
      return b;
    }
    for (var i = 0; i < REASON_CHOICES.length; i += 1) list.appendChild(choice(REASON_CHOICES[i]));

    /* Custom: a row like the others, which reveals the writing box. */
    var custom = choice('Custom');
    var customBox = make('div', 'sp-reason-custom');
    customBox.hidden = true;
    var ta = make('textarea', 'sp-reason-ta', '');
    ta.placeholder = 'in your own words';
    ta.rows = 3;
    ta.setAttribute('aria-label', 'Your own reason');
    var dictate = make('button', 'sp-reason-dictate', '');
    dictate.type = 'button';
    dictate.innerHTML = folderIcon('c:microphone', '');
    dictate.appendChild(document.createTextNode('Dictate'));
    dictate.title = 'Say it: the dot lends its ear and the words land in the box';
    dictate.addEventListener('click', function () {
      var dot = root.PineTalkDot;
      if (!dot || typeof dot.captureNext !== 'function') { sheet.say('no microphone on this surface'); return; }
      try {
        dot.captureNext(function (words) {
          words = String(words || '').trim();
          if (!words) { sheet.say('nothing was heard'); return; }
          ta.value = (ta.value ? String(ta.value).replace(/\s+$/, '') + ' ' : '') + words;
          sheet.say('heard: ' + words.slice(0, 80));
        });
        sheet.say('listening\u2026', true);
      } catch (err) {
        sheet.say('the dot could not listen: ' + String((err && err.message) || err).slice(0, 80));
      }
    });
    customBox.appendChild(ta);
    customBox.appendChild(dictate);
    custom.addEventListener('click', function () {
      customBox.hidden = custom.getAttribute('aria-pressed') !== 'true';
      if (!customBox.hidden) { try { ta.focus(); } catch (err) { /* no focus on this surface */ } }
    });
    list.appendChild(custom);
    list.appendChild(customBox);
    sheet.box.appendChild(list);

    var file = make('button', 'sp-reason-file', 'File the report');
    file.type = 'button';
    file.addEventListener('click', function () {
      var parts = [];
      var rows = list.querySelectorAll('.sp-reason-choice');
      for (var j = 0; j < rows.length; j += 1) {
        if (rows[j] === custom || rows[j].getAttribute('aria-pressed') !== 'true') continue;
        parts.push(rows[j].pineText);
      }
      var own = String(ta.value || '').replace(/\s+/g, ' ').trim();
      if (own && !customBox.hidden) parts.push('custom: ' + own);
      if (!parts.length) { sheet.say('choose a reason, or write one'); return; }
      sheet.close();
      reportKind = 'caution';
      try { reportFire(btn, parts.join('; ')); }
      finally { setTimeout(function () { reportKind = 'report'; }, 100); }
    });
    sheet.box.appendChild(file);
  }

  /* B. THE PINE INBOX, ON A HOLD OF THE REPORT ICON. The requests the
   * station holds (GET /api/pine-requests), newest first, one card
   * each: the header, the first line, and under the caret the whole
   * text - with the "### Station at the time" block folded away as
   * debug information, every data/script_reports/script_*.md the text
   * names folded under its own name and read from the station only
   * when opened (GET /api/script-reports/<name>), and a pasted picture
   * ([img:<name>]) shown from /api/pine-uploads/<name>. A card's x
   * arms first and deletes on the second tap within three seconds:
   * an inbox is not a place for a stray thumb to lose a report. The
   * delete goes through the bridge's del() where it has one, else a
   * DELETE with the station key the way talk-dot's serverKey() finds
   * it - and says so when no key is reachable. */
  function inboxClose() { var n = el('spInboxSheet'); if (n) n.remove(); }

  function inboxOpen() {
    if (!api() || !api().get) return;
    var sheet = sheetShell('spInboxSheet', 'sp-inbox', 'The Pine inbox');
    var again = make('button', 'sp-inbox-refresh', '');
    again.type = 'button';
    again.innerHTML = folderIcon('c:renew', 'Refresh');
    if (!again.innerHTML) again.textContent = 'refresh';
    again.title = 'Read the inbox again';
    again.setAttribute('aria-label', 'Refresh the inbox');
    sheet.head.insertBefore(again, sheet.x);
    var list = make('div', 'sp-inbox-list');
    sheet.box.appendChild(list);
    again.addEventListener('click', function () { inboxLoad(sheet, list); });
    inboxLoad(sheet, list);
  }

  /* Newest first: by id where the ids count, else by date. */
  function inboxOrder(r) {
    var n = Number(r && r.id);
    if (r && String(r.id).trim() !== '' && isFinite(n)) return n;
    var t = Date.parse(String((r && r.when) || ''));
    return isFinite(t) ? t / 1000 : 0;
  }

  function inboxLoad(sheet, list) {
    list.textContent = '';
    list.appendChild(make('div', 'sp-folder-note', 'reading the inbox\u2026'));
    Promise.resolve(api().get('/api/pine-requests')).then(function (d) {
      if (!el('spInboxSheet')) return;
      list.textContent = '';
      var rows = ((d && d.requests) || []).slice();
      if (!rows.length) { list.appendChild(make('div', 'sp-folder-note', 'Inbox empty')); return; }
      rows.sort(function (a, b) { return inboxOrder(b) - inboxOrder(a); });
      for (var i = 0; i < rows.length; i += 1) list.appendChild(inboxCard(sheet, list, rows[i]));
    }, function (err) {
      if (!el('spInboxSheet')) return;
      list.textContent = '';
      list.appendChild(make('div', 'sp-folder-note', 'the station did not answer: ' + String((err && err.message) || err).slice(0, 80)));
    });
  }

  function inboxFirstLine(text) {
    var lines = String(text || '').split('\n');
    for (var i = 0; i < lines.length; i += 1) {
      var t = lines[i].replace(/^#+\s*/, '').trim();
      if (t) return t.length > 140 ? t.slice(0, 139) + '\u2026' : t;
    }
    return '(empty)';
  }

  function inboxCard(sheet, list, r) {
    var card = make('div', 'sp-inbox-card');
    var id = String((r && r.id) || '');
    var text = String((r && r.text) || '');
    card.pineReports = {};                 /* name -> text, read once */
    /* #1140: the card carries its own id and text, so a kept picture can
       re-render it from the station's `edited` row (inboxRepaint). */
    card.pineId = id;
    card.pineText = text;
    var line = make('div', 'sp-inbox-line');
    var tri = make('button', 'sp-folder-tri sp-inbox-tri', '');
    tri.type = 'button';
    tri.setAttribute('aria-expanded', 'false');
    tri.innerHTML = folderIcon('c:caret--right', 'Open');
    if (!tri.innerHTML) tri.textContent = '>';
    var main = make('div', 'sp-inbox-main');
    var head = make('b', 'sp-inbox-head', '#' + id + ' \u00b7 ' + String((r && r.when) || ''));
    if (r && r.status) head.appendChild(make('span', 'sp-inbox-status', ' \u00b7 ' + String(r.status)));
    main.appendChild(head);
    main.appendChild(make('span', 'sp-inbox-first', inboxFirstLine(text)));
    function toggle() {
      var open = card.classList.contains('open');
      var body = card.querySelector('.sp-inbox-body');
      if (open) {
        if (body) body.remove();
        card.classList.remove('open');
        tri.setAttribute('aria-expanded', 'false');
        return;
      }
      card.appendChild(inboxBody(card, card.pineText));
      card.classList.add('open');
      tri.setAttribute('aria-expanded', 'true');
    }
    tri.addEventListener('click', function (ev) { ev.stopPropagation(); toggle(); });
    main.addEventListener('click', toggle);

    var x = make('button', 'sp-inbox-x', '\u00d7');
    x.type = 'button';
    x.title = 'Delete this request (tap twice)';
    x.setAttribute('aria-label', 'Delete request ' + id);
    var armTimer = 0;
    x.addEventListener('click', function (ev) {
      ev.stopPropagation();
      if (!x.classList.contains('armed')) {
        x.classList.add('armed');
        sheet.say('tap again to delete #' + id);
        armTimer = setTimeout(function () { armTimer = 0; x.classList.remove('armed'); }, 3000);
        return;
      }
      if (armTimer) clearTimeout(armTimer);
      armTimer = 0;
      x.classList.remove('armed');
      x.disabled = true;
      inboxDelete(id).then(function (got) {
        if (got && got.ok === false) { x.disabled = false; sheet.say(String(got.say || 'the station refused')); return; }
        card.remove();
        sheet.say('#' + id + ' deleted');
        if (!list.querySelector('.sp-inbox-card')) list.appendChild(make('div', 'sp-folder-note', 'Inbox empty'));
      }, function (err) {
        x.disabled = false;
        sheet.say('not deleted: ' + String((err && err.message) || err).slice(0, 80));
      });
    });
    line.appendChild(tri);
    line.appendChild(main);
    line.appendChild(x);
    card.appendChild(line);
    return card;
  }

  /* The "### Station at the time" block, from that heading to the next
     heading of its level or shallower (deeper ones are its own). */
  function inboxSplit(text) {
    var at = text.indexOf('### Station at the time');
    if (at < 0) return {main: text, debug: ''};
    var rest = text.slice(at);
    var next = rest.search(/\n#{1,3} /);
    if (next < 0) return {main: text.slice(0, at), debug: rest};
    return {main: text.slice(0, at) + rest.slice(next + 1), debug: rest.slice(0, next)};
  }

  function inboxReportNames(text) {
    var re = /data\/script_reports\/(script_[\w.-]+\.md)/g, m, seen = {}, out = [];
    while ((m = re.exec(text))) {
      if (!seen[m[1]]) { seen[m[1]] = true; out.push(m[1]); }
    }
    return out;
  }

  /* Text as <pre> that wraps; a [img:<name>] token becomes the picture.
   *
   * #1140: "When following reports allow me to tap the image to full
   * screen it and basically use my finger as a cursor to draw on it in
   * red and then go back." A tap on the picture opens the hot corners'
   * red-ink annotator (PineHotCorners.annotate) full screen on THAT
   * picture, with Undo / Clear / Back / Keep. Back changes nothing; Keep
   * PUTs the drawn-on copy to the station (inboxKeep), which saves it as
   * a new upload, rewrites the card's [img:] token to it, and answers the
   * edited row - the card is repainted from that. */
  function inboxRender(into, text, card) {
    var re = /\[img:([^\]\s]+)\]/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) into.appendChild(make('pre', 'sp-inbox-pre', text.slice(last, m.index)));
      var img = document.createElement('img');
      img.className = 'sp-inbox-img';
      img.alt = m[1];
      img.loading = 'lazy';
      img.src = stationUrl('/api/pine-uploads/' + encodeURIComponent(m[1]));
      if (card) inboxInk(img, m[1], card);
      into.appendChild(img);
      last = m.index + m[0].length;
    }
    if (last < text.length) into.appendChild(make('pre', 'sp-inbox-pre', text.slice(last)));
  }

  function inboxInk(img, name, card) {
    img.title = 'Tap to draw on this picture';
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var hc = root.PineHotCorners;
      if (!hc || typeof hc.annotate !== 'function') {
        inboxSay('the annotator is not loaded on this surface');
        return;
      }
      hc.annotate('/api/pine-uploads/' + encodeURIComponent(name), {
        fileLabel: 'Keep', fileIcon: 'c:save', busyLabel: 'keeping…',
        backLabel: 'Back', cancelSay: 'nothing changed',
        note: 'draw on the picture in red, then Keep it - or go Back',
        onDone: function (png) {
          return inboxKeep(card.pineId, png, name).then(function (got) {
            if (!got || got.ok === false) throw new Error(String((got && (got.say || got.detail)) || 'the station refused'));
            inboxRepaint(card, got, img);
            inboxSay('picture kept');
          });
        }
      });
    });
  }

  /* The inbox sheet's own say-line (sheetShell's .sp-sheet-say), for a
     word after the annotator has closed. Nothing if the sheet is gone. */
  function inboxSay(words) {
    var sheet = el('spInboxSheet');
    var say = sheet && sheet.querySelector('.sp-sheet-say');
    if (!say) return;
    words = String(words || '');
    say.textContent = words;
    say.hidden = !words;
    if (words) setTimeout(function () { if (say.textContent === words) say.hidden = true; }, 4000);
  }

  /* After Keep: the <img> in the card goes to the new upload and the
     card's text is re-rendered from the station's `edited` row - the
     [img:] token now names the drawn-on copy. */
  function inboxRepaint(card, got, img) {
    var edited = (got && got.edited) || {};
    var url = String((got && got.url) || '');
    if (url && img) img.src = stationUrl(url) + (url.indexOf('?') < 0 ? '?v=' + Date.now() : '');
    if (edited && typeof edited.text === 'string') {
      card.pineText = String(edited.text);
      var first = card.querySelector('.sp-inbox-first');
      if (first) first.textContent = inboxFirstLine(card.pineText);
      var body = card.querySelector('.sp-inbox-body');
      if (body) {
        body.remove();
        card.appendChild(inboxBody(card, card.pineText));
      }
    }
  }

  function inboxBody(card, text) {
    var body = make('div', 'sp-inbox-body');
    var cut = inboxSplit(text);
    inboxRender(body, cut.main, card);
    if (cut.debug) {
      var dbg = make('details', 'sp-inbox-details');
      dbg.appendChild(make('summary', null, 'debug information'));
      dbg.appendChild(make('pre', 'sp-inbox-pre', cut.debug));
      body.appendChild(dbg);
    }
    var names = inboxReportNames(text);
    for (var i = 0; i < names.length; i += 1) body.appendChild(inboxReport(card, names[i]));
    return body;
  }

  function inboxReport(card, name) {
    var d = make('details', 'sp-inbox-details sp-inbox-report');
    d.appendChild(make('summary', null, name));
    var pre = make('pre', 'sp-inbox-pre', '');
    d.appendChild(pre);
    d.addEventListener('toggle', function () {
      if (!d.open) return;
      if (card.pineReports[name] !== undefined) { pre.textContent = card.pineReports[name]; return; }
      if (d.pineAsking) return;
      d.pineAsking = true;
      pre.textContent = 'reading\u2026';
      Promise.resolve(api().get('/api/script-reports/' + encodeURIComponent(name))).then(function (got) {
        d.pineAsking = false;
        var t = String((got && got.text) || (got && got.say) || '(empty)');
        if (!got || got.status !== 'awaiting_post') card.pineReports[name] = t;
        pre.textContent = t;
      }, function (err) {
        d.pineAsking = false;             /* asked again on the next open */
        pre.textContent = 'not read: ' + String((err && err.message) || err).slice(0, 80);
      });
    });
    return d;
  }

  /* The station key the way talk-dot's serverKey() finds it: the page's
     SERVER_KEY, else the bridge's config. */
  function inboxKey() {
    try { if (typeof root.SERVER_KEY === 'string' && root.SERVER_KEY) return Promise.resolve(root.SERVER_KEY); }
    catch (err) { /* no such global */ }
    var bridge = api();
    if (!bridge || typeof bridge.readConfig !== 'function') return Promise.resolve('');
    return Promise.resolve(bridge.readConfig()).then(function (cfg) {
      return String((cfg && (cfg.apiKey || cfg.api_key)) || '');
    }, function () { return ''; });
  }

  function inboxDelete(id) {
    var path = '/api/pine-requests/' + encodeURIComponent(id);
    var bridge = api();
    if (bridge && typeof bridge.del === 'function') return Promise.resolve(bridge.del(path));
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to delete through'));
    return inboxKey().then(function (key) {
      if (!key) throw new Error('no station key reachable on this surface');
      return root.fetch(stationUrl(path), {method: 'DELETE', headers: {Authorization: 'Bearer ' + key}}).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json().then(null, function () { return {ok: true}; });
      });
    });
  }

  /* #1140: the drawn-on copy goes back to the station. PUT
     /api/pine-requests/<id> with {image: <png data url>, replace: <the
     tapped picture's file name>}; the station saves the image as a new
     upload, rewrites the [img:] token, and answers {ok, edited, image,
     url}. Through the bridge's put() where it has one (the Electron
     preload and the kiosk both do), else a PUT with the station key the
     way inboxDelete does. */
  function inboxKeep(id, png, replaceName) {
    var path = '/api/pine-requests/' + encodeURIComponent(id);
    var body = {image: String(png || ''), replace: String(replaceName || '')};
    var bridge = api();
    if (bridge && typeof bridge.put === 'function') return Promise.resolve(bridge.put(path, body));
    if (typeof root.fetch !== 'function') return Promise.reject(new Error('no road to keep it through'));
    return inboxKey().then(function (key) {
      if (!key) throw new Error('no station key reachable on this surface');
      return root.fetch(stationUrl(path), {
        method: 'PUT',
        headers: {Authorization: 'Bearer ' + key, 'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      }).then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      });
    });
  }

  /* ---- #1164: the drop-down under the script's name --------------- */

  /* C. HOLD THE NAME OF THE SCRIPT AND SAY WHAT IS WRONG WITH IT.
   *
   * Inbox #1164, in the operator's own words:
   *
   *   "I want to be able to tap and hold on the name of the script as
   *    being run for that particular session and I want a drop-down menu
   *    that comes down that lets me pick options like complain, mark
   *    issue and report missing segment. I am noticing some of the
   *    scripts missing entire segments, for example the manager is
   *    supposed to call during the manager's segment."
   *
   * THE GESTURE IS THE ONE THIS FILE ALREADY HAS. holdOpen() above -
   * half a second, eight pixels of travel cancels it, the trailing
   * synthetic click is swallowed by `pineHeld`, and the desk's
   * right-click and the WebView's own long-press menu are both turned
   * into the same answer. The SFX button, the caution button and the
   * report icon are already on it; the heading is the fourth, and it
   * cannot fight the other three because none of them is inside it -
   * the caution button lives in #spScript and the report icon in the
   * bar on the other half of the screen.
   *
   * IT COMES DOWN, it does not arrive. sheetShell() builds a modal with
   * a backdrop in the middle of the glass, which is right for the reason
   * sheet and the inbox and wrong here: the operator asked for "a
   * drop-down menu that comes down", so this hangs off the heading
   * inside .sp-right (already position: relative) and is placed from the
   * heading's own offsets. Its `say` line copies sheetShell's four-second
   * rule so a message on this surface behaves like a message on that one.
   *
   * WHAT IT FILES, AND WHERE THAT LANDS. Every choice goes down the
   * caution button's road and no other: reportGather() for the window,
   * the motion ring and the view snapshot, then POST /api/script/report
   * through reportFire(), then the ten-second post-capture and the
   * picture. Nothing new is invented and nothing is asked of the station
   * that it does not already answer.
   *
   * AND THE CONTEXT IS WRITTEN INTO `reason`, DELIBERATELY. It would
   * read better as its own field on the view - it is structured, and a
   * field is easier to query than a sentence. It would also be thrown
   * away: normalize_view() in script_diagnostics.py says so in its own
   * docstring - "Unknown fields are excluded by schema" - and the report
   * store encodes only what that function returns, so a new key stamped
   * on the view or on its snapshot never reaches the .json or the .md.
   * `reason` is the one thing that survives whole: app.py leads the
   * inbox item with it ("Script diagnostic capture: " + reason) and
   * render_report() prints it under "## Operator report". A field that
   * is silently discarded looks, from in here, exactly like one that
   * arrived - so the hour, the script's name, the two scene headings and
   * the visible block.ord range are written where they will be read.
   * 1200 characters is the store's cap on it; the sentence below runs to
   * about three hundred.
   */
  var HEADER_MENU_ID = 'spHeadMenu';
  var HEADER_TEXT_CAP = 160;        /* a scene heading, not a scene */
  var headerUnwatch = null;         /* PineDismiss's handle on the open menu */

  /* The three the operator named, and Cancel. `ask` is the one that
     stops to let him say WHAT is missing before anything is filed -
     "the manager is supposed to call during the manager's segment" is a
     fact no diagnostic on this page could work out for itself.
     Icons are Carbon out of the vendored set through folderIcon(), and
     all four are in pine-icons.js: that is the house rule, and the set
     is checked before choosing rather than after. */
  var HEADER_CHOICES = [
    {kind: 'complain', label: 'Complain', icon: 'c:bullhorn',
     why: 'Something about this hour is wrong and you want it on the record'},
    {kind: 'mark issue', label: 'Mark issue', icon: 'c:warning--alt',
     why: 'Mark this moment: keep the ledger around it for the station to read'},
    {kind: 'report missing segment', label: 'Report missing segment', icon: 'c:misuse',
     why: 'A whole segment never happened - say which one', ask: true}
  ];

  function headerClose() {
    var menu = el(HEADER_MENU_ID);
    if (menu) menu.remove();
    if (headerUnwatch) {
      try { headerUnwatch(); } catch (err) { /* already gone */ }
      headerUnwatch = null;
    }
    var name = el('spScriptName');
    if (name) name.setAttribute('aria-expanded', 'false');
  }

  /* One heading, on one line. */
  function headerText(node) {
    return String((node && node.textContent) || '')
      .replace(/\s+/g, ' ').trim().slice(0, HEADER_TEXT_CAP);
  }

  /* Where the SCRIPT put this element, as the node already carries it -
     #1330 writes data-block and data-ord onto every one. Absent on a
     plan row or a spacer, and absent is said as absent. */
  function headerOrd(node) {
    if (!node || !node.getAttribute) return '';
    var block = node.getAttribute('data-block');
    var ord = node.getAttribute('data-ord');
    if (!block && !ord) return '';
    return String(block || '?') + '.' + String(ord || '?');
  }

  function headerSeat(node) {
    try { return node.getBoundingClientRect(); }
    catch (err) { return {top: 0, bottom: 0, height: 0}; }
  }

  /* WHICH SEGMENT THE VIEW IS SHOWING, by the segment's own words.
   *
   * Two answers, because they are two different questions and on this
   * page they disagree all the time: the reader scrolls away from the
   * air (follow stands down, #1282) and then the top of the pane and the
   * lit line are in different segments. A report that named only one of
   * them would be answering the wrong one half the time.
   *
   *   top_scene   the scene heading the READER is under - the last one
   *               walked past before the first element the pane is
   *               actually showing, so a heading scrolled off the top
   *               still names the segment on screen
   *   mark_scene  the scene heading above the line that is SOUNDING
   *               (.sp-now), or nothing when nothing is lit
   *
   * DOM order is script order here - the reconciler (#1273) stitches the
   * canonical list flat - so one walk down the pane answers both, and
   * the first and last visible block.ord are the range without sorting
   * anything.
   */
  function headerWhere() {
    var out = {title: '', hour: hourKey, before: beforeKey, top_scene: '',
      mark_scene: '', block_from: '', block_to: '', visible: 0};
    var line = el('spScriptHead');
    if (line) out.title = headerText(line);
    var pane = el('spScript');
    if (!pane || !pane.querySelectorAll) return out;
    var lip = headerSeat(pane);
    var all = pane.querySelectorAll('.sp-el');
    var scene = '';
    for (var i = 0; i < all.length; i += 1) {
      var node = all[i];
      var cls = String(node.className || '');
      if (/(^|\s)sp-scene(\s|$)/.test(cls)) scene = headerText(node);
      var seat = headerSeat(node);
      var shown = seat.height > 0 && seat.bottom > lip.top && seat.top < lip.bottom;
      if (/(^|\s)sp-now(\s|$)/.test(cls)) out.mark_scene = scene;
      if (!shown) continue;
      if (!out.top_scene) out.top_scene = scene || '(no scene heading above it)';
      out.visible += 1;
      var at = headerOrd(node);
      if (at) {
        if (!out.block_from) out.block_from = at;
        out.block_to = at;
      }
    }
    return out;
  }

  /* The sentence the inbox leads with. The operator's chosen kind comes
     FIRST and alone, so "Script diagnostic capture: complain" reads as
     what it is before anything else is said; his own words about what is
     missing come second; the evidence follows, semicolon-separated the
     way the reason sheet already writes its list. */
  function headerReason(kind, note) {
    var where = headerWhere();
    var parts = [String(kind || 'complain')];
    if (note) parts.push('missing: ' + String(note).slice(0, 400));
    if (where.title) parts.push('the script: ' + where.title);
    if (where.hour) {
      parts.push('hour: ' + where.hour
        + (where.before ? ' (with ' + where.before + ' before it on the page)' : ''));
    }
    parts.push('at the top of the pane: ' + (where.top_scene || 'nothing on screen'));
    parts.push('at the mark: ' + (where.mark_scene || 'nothing is lit'));
    parts.push('visible: ' + (where.block_from
      ? 'block.ord ' + where.block_from + ' to ' + where.block_to
        + ', ' + where.visible + ' elements'
      : where.visible + ' elements, none carrying a block.ord'));
    return parts.join('; ');
  }

  function headerOpen(name) {
    var into = name && name.parentNode;
    if (!into) return null;
    headerClose();

    var menu = make('div', 'sp-headmenu');
    menu.id = HEADER_MENU_ID;
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'File a report about this script');

    /* sheetShell's say line: same four seconds, same hold. */
    var sayLine = make('div', 'sp-headmenu-say', '');
    sayLine.hidden = true;
    menu.appendChild(sayLine);
    var sayTimer = 0;
    function menuSay(text, hold) {
      if (sayTimer) clearTimeout(sayTimer);
      sayTimer = 0;
      sayLine.textContent = String(text || '');
      sayLine.hidden = !sayLine.textContent;
      if (!hold && sayLine.textContent) {
        sayTimer = setTimeout(function () { sayTimer = 0; sayLine.hidden = true; }, 4000);
      }
    }

    /* The context is read BEFORE the menu goes, so the report describes
       the view the operator was looking at when he chose - not the one
       left behind once the drop-down was taken off it. */
    function fire(kind, note) {
      var reason = headerReason(kind, note);
      headerClose();
      reportFire(name, reason);
    }

    function row(cls, icon, label, why) {
      var b = make('button', 'sp-headmenu-item' + (cls ? ' ' + cls : ''), '');
      b.type = 'button';
      b.setAttribute('role', 'menuitem');
      var mark = make('span', 'sp-headmenu-mark', '');
      mark.innerHTML = folderIcon(icon, '');
      if (!mark.innerHTML) mark.textContent = '\u00b7';
      b.appendChild(mark);
      b.appendChild(make('span', 'sp-headmenu-text', label));
      if (why) b.title = why;
      return b;
    }

    /* SAY WHAT IS MISSING. The reason sheet's custom row, in the same
       shape: a box that is revealed rather than always open, a Dictate
       button that borrows the dot's ear (PineTalkDot.captureNext), and
       an honest answer on a surface that has no microphone instead of a
       button that pretends. Nothing is prefilled - the words have to be
       his, because "the manager is supposed to call during the manager's
       segment" is not a thing this page could have guessed. */
    var ask = make('div', 'sp-headmenu-ask');
    ask.hidden = true;
    var ta = make('textarea', 'sp-headmenu-ta', '');
    ta.placeholder = 'what is missing from this hour?';
    ta.rows = 3;
    ta.setAttribute('aria-label', 'What is missing from this script');
    var tools = make('div', 'sp-headmenu-row');
    var dictate = make('button', 'sp-headmenu-dictate', '');
    dictate.type = 'button';
    dictate.innerHTML = folderIcon('c:microphone', '');
    dictate.appendChild(document.createTextNode('Dictate'));
    dictate.title = 'Say it: the dot lends its ear and the words land in the box';
    dictate.addEventListener('click', function () {
      var dot = root.PineTalkDot;
      if (!dot || typeof dot.captureNext !== 'function') { menuSay('no microphone on this surface'); return; }
      try {
        dot.captureNext(function (words) {
          words = String(words || '').trim();
          if (!words) { menuSay('nothing was heard'); return; }
          ta.value = (ta.value ? String(ta.value).replace(/\s+$/, '') + ' ' : '') + words;
          menuSay('heard: ' + words.slice(0, 80));
        });
        menuSay('listening\u2026', true);
      } catch (err) {
        menuSay('the dot could not listen: ' + String((err && err.message) || err).slice(0, 80));
      }
    });
    var file = make('button', 'sp-headmenu-file', 'File the report');
    file.type = 'button';
    file.addEventListener('click', function () {
      var own = String(ta.value || '').replace(/\s+/g, ' ').trim();
      if (!own) { menuSay('say what is missing, or dictate it'); return; }
      fire('report missing segment', own);
    });
    tools.appendChild(dictate);
    tools.appendChild(file);
    ask.appendChild(ta);
    ask.appendChild(tools);

    for (var i = 0; i < HEADER_CHOICES.length; i += 1) {
      (function (choice) {
        var b = row('', choice.icon, choice.label, choice.why);
        b.addEventListener('click', function () {
          if (!choice.ask) { fire(choice.kind, ''); return; }
          var open = ask.hidden;
          ask.hidden = !open;
          b.setAttribute('aria-expanded', open ? 'true' : 'false');
          b.classList.toggle('on', open);
          if (open) { try { ta.focus(); } catch (err) { /* no focus on this surface */ } }
        });
        menu.appendChild(b);
        if (choice.ask) menu.appendChild(ask);
      })(HEADER_CHOICES[i]);
    }

    var cancel = row('sp-headmenu-cancel', 'c:close--filled', 'Cancel',
                     'Close this menu and file nothing');
    cancel.addEventListener('click', headerClose);
    menu.appendChild(cancel);

    into.appendChild(menu);
    /* Under the name, from the name's own offsets: .sp-right is the
       positioned ancestor, and the heading's height moves with the type
       setting (#1272's paper and big-type looks both change it). */
    try {
      menu.style.top = ((name.offsetTop || 0) + (name.offsetHeight || 0) + 2) + 'px';
      menu.style.left = (name.offsetLeft || 0) + 'px';
    } catch (err) { /* no geometry on this surface; the CSS stands */ }
    name.setAttribute('aria-expanded', 'true');

    /* "if I'm interacting with one of the systems that's a diagnostic,
       then duck the broadcast audio" - this menu files reports, so it is
       one. The hold is tied to the menu element, so PineDuck's sweep
       gives the radio back by itself the moment the menu leaves the
       page: no close path in here, and no route that tears this view
       down from outside, can leave the station quiet. */
    if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
      root.PineDuck.hold('sp-' + HEADER_MENU_ID, root.PineDuck.REPORT, menu);
    }
    /* Tap away and Escape, through the one rule every other pop-up on
       this page is on. The heading is spared so its own hold re-opens
       rather than close-then-open, and `open` is answered by the menu's
       presence rather than by its measured box - a drop-down that has
       not been laid out yet is still open. */
    if (root.PineDismiss && typeof root.PineDismiss.watch === 'function') {
      headerUnwatch = root.PineDismiss.watch(menu, headerClose, [name], function () {
        return !!el(HEADER_MENU_ID);
      });
    }
    return menu;
  }

  /* ---- #1385: the word search ------------------------------------ */

  /* The station does the counting (/api/said/search, #1380); this only
   * draws what it said. A sheet over the view, tap away to close, the
   * same shape as the clip doctor's - the operator asked for it on the
   * tablet, so every control is a thumb's size. */
  function findClose() {
    var old = el('spFindSheet');
    if (old) old.remove();
  }

  function findOpen(q) {
    q = String(q || '').trim();
    if (q.length < 2 || !api() || !api().get) return;
    findClose();
    var back = make('div', 'sp-find-back');
    back.id = 'spFindSheet';
    var box = make('div', 'sp-find-box');
    var head = make('div', 'sp-find-head');
    head.appendChild(make('b', null, '\u201c' + q + '\u201d on the air'));
    var x = make('button', 'sp-find-x', '\u00d7');
    x.type = 'button';
    x.addEventListener('click', findClose);
    head.appendChild(x);
    box.appendChild(head);
    var why = make('div', 'sp-find-why', 'asking the station\u2026');
    box.appendChild(why);
    var facts = make('div', 'sp-find-facts');
    box.appendChild(facts);
    var list = make('div', 'sp-find-list');
    box.appendChild(list);
    back.appendChild(box);
    back.addEventListener('click', function (ev) { if (ev.target === back) findClose(); });
    document.body.appendChild(back);
    Promise.resolve(api().get('/api/said/search?q=' + encodeURIComponent(q) + '&hours=48&limit=120')).then(function (d) {
      if (!d) { why.textContent = 'the station did not answer'; return; }
      why.textContent = d.why || d.say || '';
      var bits = [String(d.total || 0) + ' airing(s) in ' + (d.hours || 48) + 'h, ' + String(d.distinct || 0) + ' distinct line(s)'];
      (d.by_round || []).slice(0, 4).forEach(function (r) { bits.push(r.name + ' \u00d7' + r.n); });
      (d.by_who || []).slice(0, 3).forEach(function (r) { bits.push(r.name + ' \u00d7' + r.n); });
      facts.textContent = bits.join('  \u00b7  ');
      var dated = d.rows || [];
      /* #1117: a repeated row is a tally, not a line, so it has no id
         of its own. It borrows the first dated row that says the same
         words - the station's paperwork is per line, and any one of
         the airings is the same line. */
      function idFor(text) {
        var want = findNorm(text);
        if (!want) return '';
        var i, have;
        for (i = 0; i < dated.length; i += 1) {
          if (dated[i] && dated[i].id && findNorm(dated[i].text) === want) return String(dated[i].id);
        }
        /* The tally may quote a cut of the line; a prefix either way
           is still the same line. */
        for (i = 0; i < dated.length; i += 1) {
          have = dated[i] && dated[i].id ? findNorm(dated[i].text) : '';
          if (have && (have.indexOf(want) === 0 || want.indexOf(have) === 0)) return String(dated[i].id);
        }
        return '';
      }
      (d.repeated || []).slice(0, 5).forEach(function (t) {
        if (t.n < 2) return;
        var row = make('div', 'sp-find-rep');
        var line = make('div', 'sp-find-line');
        line.appendChild(findTri(row, idFor(t.text)));               /* #1117 */
        var main = make('span', 'sp-find-main');
        main.appendChild(make('b', null, '\u00d7' + t.n + ' '));
        main.appendChild(make('span', null, (t.who ? t.who + ': ' : '') + t.text));
        line.appendChild(main);
        row.appendChild(line);
        list.appendChild(row);
      });
      dated.forEach(function (r) {
        var row = make('div', 'sp-find-row');
        var line = make('div', 'sp-find-line');
        line.appendChild(findTri(row, r.id ? String(r.id) : ''));    /* #1117 */
        var main = make('div', 'sp-find-main');
        var ago = r.ago >= 3600 ? Math.round(r.ago / 3600) + 'h ago' : Math.round(r.ago / 60) + 'm ago';
        main.appendChild(make('span', 'sp-find-when', ago + ' \u00b7 ' + (r.who || '?') + ' \u00b7 ' + (r.round || r.kind || '')));
        main.appendChild(make('span', 'sp-find-text', r.text || ''));
        line.appendChild(main);
        row.appendChild(line);
        list.appendChild(row);
      });
      if (!(d.rows || []).length) list.appendChild(make('div', 'sp-find-row', 'not said on the air in the last two days'));
    }, function (err) {
      why.textContent = 'the station did not answer: ' + String((err && err.message) || err).slice(0, 80);
    });
  }

  /* ---- #1117: the triangle at the front of every row ------------- */

  /* "I want an expandable triangle at the beginning of all of these
   *  that allows me to see what property set this and allow me to
   *  change or manage those or adjust them in the system prompt or see
   *  what systems contributed to making them the way that they are,
   *  whatever I search for them."
   *
   * The station answers GET /api/said/why/{id} with three lists: what
   * SET the line (only the properties in force), the per-road system
   * prompt (saved back through POST /api/said/prompt, in force from
   * the next round), and what contributed, on or off. This draws them
   * under the row and nothing more. The answer is cached on the row
   * node, so a second tap costs the station nothing. */
  function findNorm(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function findTri(row, id) {
    var tri = make('button', 'sp-find-tri', '');
    tri.type = 'button';
    tri.setAttribute('aria-expanded', 'false');
    try {
      if (typeof root.pineIcon === 'function') {
        tri.innerHTML = root.pineIcon('c:caret--right', 'What set this line');
      }
    } catch (err) { /* the text below stands in */ }
    if (!tri.innerHTML) tri.textContent = '>';
    if (!id) {
      tri.disabled = true;
      tri.title = 'no line id to ask about';
      return tri;
    }
    tri.title = 'What set this line, the system prompt for its road, and what contributed';
    tri.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var open = tri.getAttribute('aria-expanded') === 'true';
      tri.setAttribute('aria-expanded', open ? 'false' : 'true');
      row.classList.toggle('open', !open);
      var panel = row.querySelector('.sp-find-why-panel');
      if (open) { if (panel) panel.hidden = true; return; }
      if (!panel) {
        panel = make('div', 'sp-find-why-panel', 'asking the station…');
        row.appendChild(panel);
      }
      panel.hidden = false;
      if (row.pineWhy || row.pineWhyAsking) return;   /* held, or in flight */
      if (!api() || !api().get) { panel.textContent = 'no bridge to ask through'; return; }
      row.pineWhyAsking = true;
      Promise.resolve(api().get('/api/said/why/' + encodeURIComponent(id))).then(function (d) {
        row.pineWhyAsking = false;
        if (!d || d.ok === false) {
          panel.textContent = 'the station did not answer'
            + (d && d.say ? ': ' + String(d.say).slice(0, 120) : '');
          return;
        }
        row.pineWhy = d;
        findWhyPaint(panel, d);
      }, function (err) {
        row.pineWhyAsking = false;
        panel.textContent = 'the station did not answer: '
          + String((err && err.message) || err).slice(0, 80);
      });
    });
    return tri;
  }

  function findWhyPaint(panel, d) {
    panel.replaceChildren();
    var i;

    /* (1) what set this - the properties in force, name -> value, and
       the desk each one lives on in a dim aside. */
    panel.appendChild(make('div', 'sp-why-h', 'what set this'));
    var props = d.properties || [];
    if (!props.length) {
      panel.appendChild(make('div', 'sp-why-dim', 'nothing on record set this line'));
    } else {
      var dl = make('dl', 'sp-why-dl');
      for (i = 0; i < props.length; i += 1) {
        var p = props[i] || {};
        dl.appendChild(make('dt', null, String(p.name || '')));
        var dd = make('dd', null, (p.value === undefined || p.value === null) ? '' : String(p.value));
        if (p.where) {
          dd.appendChild(document.createTextNode(' '));
          dd.appendChild(make('i', null, String(p.where)));
        }
        dl.appendChild(dd);
      }
      panel.appendChild(dl);
    }

    /* (2) the system prompt for this road - folded, because it is the
       long one; editable where the station says so. */
    var prompt = d.prompt || {};
    var det = make('details', 'sp-why-prompt');
    det.appendChild(make('summary', null, 'the system prompt for this road'
      + (prompt.kind ? ' (' + String(prompt.kind) + ')' : '')));
    var ta = make('textarea', 'sp-why-ta', '');
    ta.rows = 6;
    ta.spellcheck = false;
    ta.value = String(prompt.text || '');
    ta.readOnly = !prompt.editable;
    det.appendChild(ta);
    if (prompt.editable) {
      var saveRow = make('div', 'sp-why-save');
      var save = make('button', 'sp-btn sp-why-savebtn', 'Save to the prompt book');
      save.type = 'button';
      var said = make('span', 'sp-why-dim', '');
      save.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if (!api() || !api().post) { said.textContent = 'no bridge to save through'; return; }
        save.disabled = true;
        said.textContent = 'saving…';
        Promise.resolve(api().post('/api/said/prompt', {kind: prompt.kind, text: ta.value})).then(function (got) {
          save.disabled = false;
          if (got && got.ok === false) {
            said.textContent = 'not saved' + (got.say ? ': ' + String(got.say).slice(0, 120) : '');
            return;
          }
          said.textContent = String((got && got.say)
            || 'saved - it takes effect on the next round');
        }, function (err) {
          save.disabled = false;
          said.textContent = 'not saved: ' + String((err && err.message) || err).slice(0, 80);
        });
      });
      saveRow.appendChild(save);
      saveRow.appendChild(said);
      det.appendChild(saveRow);
    } else {
      det.appendChild(make('div', 'sp-why-dim',
        String(prompt.why || prompt.say || 'this prompt cannot be changed from here')
        + (prompt.where ? ' - it lives in ' + String(prompt.where) : '')));
    }
    panel.appendChild(det);

    /* (3) what contributed - each system on or off, with its note;
       the ones that stood aside are dimmed, not hidden, because "the
       crystal was off" is itself part of the answer. */
    panel.appendChild(make('div', 'sp-why-h', 'what contributed'));
    var systems = d.systems || [];
    if (!systems.length) {
      panel.appendChild(make('div', 'sp-why-dim', 'no system is on record for this line'));
    } else {
      var ul = make('ul', 'sp-why-sys');
      for (i = 0; i < systems.length; i += 1) {
        var s = systems[i] || {};
        var li = make('li', s.on ? 'on' : 'off');
        li.appendChild(make('b', null, String(s.name || '')));
        li.appendChild(make('span', 'sp-why-onoff', s.on ? 'on' : 'off'));
        if (s.note) li.appendChild(make('span', 'sp-why-note', String(s.note)));
        ul.appendChild(li);
      }
      panel.appendChild(ul);
    }

    /* (4) the honesty line: without the booth's ring the properties
       above are the air log's word alone. */
    if (d.provenance_ok === false) {
      panel.appendChild(make('div', 'sp-why-dim sp-why-noprov',
        'the booth no longer holds this line’s paperwork - only the air log speaks for it'));
    }
    if (d.say) panel.appendChild(make('div', 'sp-why-say', String(d.say)));
  }

  /* ---- #1115: the report of a wrong highlight -------------------- */

  /* Everything is gathered BEFORE the picture is asked for, so the
   * numbers describe the moment of the tap and not the moment the
   * chrome got round to it. Every reading is guarded: a report about
   * a fault must not be the thing the fault breaks. */
  var reportTurn = 0;

  function jsonSafe(v) {
    try { return JSON.parse(JSON.stringify(v === undefined ? null : v)); }
    catch (err) { try { return String(v); } catch (e2) { return null; } }
  }

  function attempt(fn) {
    try { return jsonSafe(fn()); }
    catch (err) { return {error: String((err && err.message) || err).slice(0, 200)}; }
  }

  /* Passive rolling diagnostics: the previous minute of observed changes,
   * full line identities and audio coordinates. The tap submits immediately;
   * a screenshot and ten seconds of subsequent evidence finish the report.
   * Recording never scrolls the view or changes playback. */
  var MOTION_MS = 250;
  var motionTimer = 0;
  var diagnosticRecorder = null;
  var diagnosticNodes = [];
  var diagnosticIndices = new Map();
  var diagnosticLines = Object.create(null);
  var diagnosticRevision = '';
  var diagnosticSnapshot = null;
  function recorder() {
    if (!diagnosticRecorder && root.PineScriptDiagnostics) diagnosticRecorder = root.PineScriptDiagnostics.createRecorder();
    return diagnosticRecorder;
  }
  function diagnosticDocument(box) {
    diagnosticNodes = Array.prototype.slice.call(box.querySelectorAll('.sp-el'));
    diagnosticIndices = new Map();
    diagnosticLines = Object.create(null);
    diagnosticNodes.forEach(function (n, i) {
      diagnosticIndices.set(n, i);
      if (n.pineItem && n.pineItem.line) diagnosticLines[String(n.pineItem.line)] = {item: n.pineItem, index: i};
    });
    if (root.PineScriptDiagnostics) diagnosticRevision = root.PineScriptDiagnostics.revision(elements);
  }

  /* The references, resolved against the admitted map. `available: false`
     with a reason is a legitimate answer and the only honest one when the
     station has not been patched to carry the field yet. */
  function admissionReferences() {
    var out = {available: false, why: 'the station is not sending an admitted cue map',
      generation: null, mode: '', reader_position: null,
      playback_occurrence_id: null, position: null, media: null,
      script_revision: null, performer_session: null, assembly_id: null,
      cue_map_revision: null, take_id: null, audio_hash: null,
      accepted_cuts: null, origin: null};
    if (!admitMap || !admitMap.ok) return out;
    out.generation = admitMap.generation;
    out.mode = admitMap.mode;
    out.reader_position = admitMap.reader;
    var want = (lastGood && lastGood.occurrence_id)
      || (admitMap.current && admitMap.current.occurrence_id) || '';
    var found = null;
    for (var i = 0; i < admitMap.order.length; i += 1) {
      if (admitMap.order[i].occurrence_id === want) { found = admitMap.order[i]; break; }
    }
    if (!found) {
      out.why = want
        ? 'the admitted map no longer carries occurrence ' + want
        : 'no occurrence has been dispatched yet';
      return out;
    }
    out.available = true;
    out.why = '';
    out.playback_occurrence_id = found.occurrence_id;
    out.position = found.position;
    out.media = found.media;
    out.origin = found.origin;
    /* Absent, not blank: an empty string from the server means the record
       exists and the field is unset, and saying `null` says exactly that. */
    out.script_revision = found.script_revision || null;
    out.performer_session = found.performer_session || null;
    out.assembly_id = found.assembly_id || null;
    out.cue_map_revision = found.cue_map_revision || null;
    out.take_id = found.take_id || null;
    out.audio_hash = found.hash || null;
    var cuts = [];
    for (var c = 0; c < found.cues.length; c += 1) {
      if (found.cues[c].cut_id) cuts.push(found.cues[c].cut_id);
    }
    out.accepted_cuts = cuts.length ? cuts.slice(0, 24) : null;
    return out;
  }

  function sampleMotion() {
    var pane = el('spScript');
    var rec = recorder();
    if (!pane || !rec) return;
    var lit = pane.querySelector('.sp-el.sp-now');
    var idx = diagnosticIndices.has(lit) ? diagnosticIndices.get(lit) : -1;
    var audio = root.PineScriptDiagnostics.readAudio(bridgeHead(), soundingPlayer(), streamAt());
    var active = attempt(activeRow) || {};
    var feed = [];
    try { feed = root.PineStationFeed.rows() || []; } catch (e) { /* no feed */ }
    var records = [], nearby = [], mapping = [], byId = Object.create(null);
    feed.forEach(function (r) { if (r.id) byId[String(r.id)] = r; });
    var rect = pane.getBoundingClientRect(), visible = -1;
    var knownActive = diagnosticLines[String(active.id || '')];
    if (idx < 0 && !knownActive) {
      for (var v = 0; v < diagnosticNodes.length; v += 1) {
        var box = diagnosticNodes[v].getBoundingClientRect();
        if (box.height > 0 && box.bottom > rect.top && box.top < rect.bottom) { visible = v; break; }
      }
    }
    var contextAt = root.PineScriptDiagnostics.contextIndex(idx, knownActive ? knownActive.index : -1, visible, diagnosticNodes.length);
    var from = contextAt < 0 ? 0 : Math.max(0, contextAt - 20);
    var to = contextAt < 0 ? -1 : Math.min(diagnosticNodes.length - 1, contextAt + 10);
    for (var i = from; i <= to; i += 1) {
      var n = diagnosticNodes[i], item = n.pineItem || {};
      var id = String(item.line || (item.id ? 'element:' + item.id : ''));
      nearby.push({id: id, element_id: String(item.id || ''), index: i, block: item.block, ord: item.ord});
      if (id) {
        var source = byId[id] || {};
        records.push({id: id, element_id: item.id, block: item.block, ord: item.ord,
          kind: item.type, who: source.who || source.name || '', text: item.text,
          media: rowFile(source), from_s: rowFrom(source), until_s: rowUntil(source), document_index: i});
      }
    }
    // Keep a small cue neighborhood and both claimed identities. Copying the
    // whole file can evict the very rows needed to explain a long burst.
    var candidates = root.PineScriptDiagnostics.selectMappings(feed, audio, String(active.id || ''), lit ? String(lit.dataset.line || '') : '');
    candidates.rows.forEach(function (r) {
        mapping.push(String(r.id || ''));
        if (!records.some(function (held) { return held.id === String(r.id || ''); })) {
          var known = diagnosticLines[String(r.id || '')] || {}, item = known.item || {};
          records.push({id: r.id, kind: r.kind, who: r.who || r.name, text: r.text,
            media: rowFile(r), from_s: rowFrom(r), until_s: rowUntil(r),
            element_id: item.id, block: item.block, ord: item.ord, document_index: known.index});
        }
    });
    var top = lit ? Math.round(lit.getBoundingClientRect().top - rect.top) : null;
    diagnosticSnapshot = {
      recorder_version: 2, capture_source: 'script-page',
      highlight_id: lit ? String(lit.dataset.line || '') : '', active_id: String(active.id || ''),
      document_revision: diagnosticRevision, script_age_ms: fetchedAt ? Date.now() - fetchedAt : null,
      speaking_id: String((speakingNow && speakingNow.id) || ''), audio: audio,
      nearby: nearby, context_index: contextAt,
      context_source: idx >= 0 ? 'highlight' : knownActive ? 'active' : visible >= 0 ? 'viewport' : 'unavailable',
      mapping_rows: mapping, mapping_rows_total: candidates.total,
      mapping_rows_omitted: candidates.omitted, matching_file_rows_total: candidates.matching_file_total,
      stream: liveStream ? {at: liveStream.at, length: liveStream.length, row_count: (liveStream.rows || []).length,
        rows: (liveStream.rows || []).filter(function (r) { return String(r.id || '') === String(active.id || '') || String(r.id || '') === nowLineId; }).map(function (r) { return {id: r.id, from: r.from, until: r.until}; })} : null,
      viewport: {scroll_top_px: Math.round(pane.scrollTop), height_px: pane.clientHeight, width_px: pane.clientWidth, content_height_px: pane.scrollHeight, lit_top_px: top},
      paused: stationPaused, follow: follow, visibility: String(document.visibilityState || ''),
      /* THE INCIDENT REFERENCES section 5 of the recording note asks
         for: script revision, performer session, accepted cut, assembly
         and playback occurrence. Every one of them is taken from what the
         STATION actually returned. A reference the station does not carry
         is absent here; it is never filled in with something plausible. */
      admission: admissionReferences(),
      sync: {state: syncState, why: syncWhy, since_ms: syncSince,
        motion: syncRing.slice(-60),
        last_trustworthy: lastGood ? {line_id: lastGood.line_id,
          occurrence_id: lastGood.occurrence_id, position: lastGood.position,
          media: lastGood.media, at_ms: lastGood.at} : null},
      scroll: {owner: scrollOwner, at_ms: scrollAt, moves: scrollLog.slice(-12)},
      errors: caught.slice(-6)
    };
    rec.observe({at_ms: Date.now(), highlight_id: diagnosticSnapshot.highlight_id, active_id: diagnosticSnapshot.active_id,
      document_revision: diagnosticRevision, element_index: idx, block: lit && lit.dataset.block,
      ord: lit && lit.dataset.ord, scroll_top_px: Math.round(pane.scrollTop), lit_top_px: top,
      audio: audio, follow: follow, paused: stationPaused, snapshot: diagnosticSnapshot}, records);
  }
  var reportKind = 'report';
  function ensureCaution() {
    var pane = el('spScript');
    if (!pane) return;
    var wrap = document.getElementById('spCautionWrap');
    if (wrap && wrap.parentNode === pane && pane.firstChild === wrap) return;
    if (!wrap) {
      wrap = make('div', 'sp-caution-wrap', '');
      wrap.id = 'spCautionWrap';
      var b = make('button', 'sp-caution', '');
      b.type = 'button';
      b.title = 'Report a script jump: keep the previous minute, this moment, and the next 10 seconds in the Pine inbox';
      b.setAttribute('aria-label', 'Report the script as erratic');
      try { if (typeof root.pineIcon === 'function') b.innerHTML = root.pineIcon('c:warning--alt', 'Report the script as erratic'); } catch (e) { /* text */ }
      if (!b.innerHTML) b.textContent = '!';
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        ev.preventDefault();
        if (b.pineHeld) return;   /* 2026-09-14: the hold opened the reason sheet */
        reportKind = 'caution';
        b.classList.add('sp-firing');
        try { reportFire(b); } finally { setTimeout(function () { reportKind = 'report'; }, 100); }
      });
      /* 2026-09-14: HOLD IT (or right-click it) to say why first -
         the reason sheet, reasonOpen(). A tap still files at once. */
      holdOpen(b, function () { reasonOpen(b); });
      wrap.appendChild(b);
    }
    pane.insertBefore(wrap, pane.firstChild);
  }

  function reportGather(phase, incident, since) {
    sampleMotion();
    var rec = recorder();
    if (!rec) throw new Error('script diagnostics did not load');
    return rec.capture(Date.now(), phase || 'tap', incident || '', since, diagnosticSnapshot);
  }

  /* The picture. On the desktop the chrome can take one
     (pineDesktop.shotView); on the tablet the kiosk may offer
     screenshot(); either may be missing, slow or broken, and none of
     that may hold the report - five seconds and it goes without. */
  function reportImage() {
    var bridge = api(), ask = null, source = 'unavailable', requested = Date.now();
    try {
      if (bridge && typeof bridge.shotView === 'function') { source = 'shotView'; ask = bridge.shotView(); }
      else if (bridge && typeof bridge.screenshot === 'function') { source = 'screenshot'; ask = bridge.screenshot(); }
    } catch (err) { return Promise.resolve({image: null, screenshot_source: source, screenshot_at_ms: requested, screenshot_error: String(err.message || err).slice(0, 160)}); }
    if (!ask) return Promise.resolve({image: null, screenshot_source: source, screenshot_at_ms: requested, screenshot_error: 'screenshot unavailable'});
    return new Promise(function (resolve) {
      var settled = false;
      function finish(image, error) {
        if (settled) return;
        settled = true; clearTimeout(late);
        resolve({image: image, screenshot_source: source, screenshot_at_ms: Date.now(),
          screenshot_requested_at_ms: requested, screenshot_error: error || null});
      }
      var late = setTimeout(function () { finish(null, 'screenshot timed out after 5 seconds'); }, 5000);
      Promise.resolve(ask).then(function (got) {
        var url = (got && typeof got === 'object') ? (got.dataUrl || got.data_url || got.image || got.png || '') : got;
        if (typeof url === 'string' && /^data:image\//.test(url)) { finish(url); return; }
        if (typeof url === 'string' && /^[A-Za-z0-9+\/=\s]+$/.test(url) && url.length > 64) {
          finish('data:image/png;base64,' + url.replace(/\s+/g, '')); return;
        }
        finish(null, 'screenshot returned no image');
      }, function (err) { finish(null, String((err && err.message) || err).slice(0, 160)); });
    });
  }

  /* THE PHOTOGRAPHY EFFECT. A white flash over the whole view, the
     word "captured" on the strip. It fires AFTER the picture has been
     asked for - a real shutter is heard after the exposure, and a
     flash painted before the chrome grabbed the frame would put a
     white sheet in the report - with a 400 ms cap so a slow capture
     never leaves the tap feeling dead. */
  function reportShutter() {
    var into = host || document.body;
    var flash = make('div', 'sp-shutter');
    into.appendChild(flash);
    setTimeout(function () { try { flash.remove(); } catch (err) { /* gone */ } }, 520);
  }

  /* 2026-09-14: `reason` is the operator's own why, from the reason
     sheet (a hold on the caution button); a plain tap files without
     one. The station stores it and leads the inbox summary with it. */
  var REPORT_PENDING_KEY = 'pine-script-report-finishes-v2';
  function pendingReports() {
    try { return JSON.parse(root.localStorage.getItem(REPORT_PENDING_KEY) || '[]').slice(-3); }
    catch (e) { return []; }
  }
  function keepPending(name, body) {
    try {
      var saved = pendingReports().filter(function (r) { return r.name !== name; });
      if (body) {
        var small = Object.assign({}, body, {image: null});
        if (body.image) small.screenshot_error = 'image was not retained for retry; original upload failed';
        saved.push({name: name, body: small});
      }
      root.localStorage.setItem(REPORT_PENDING_KEY, JSON.stringify(saved.slice(-3)));
    } catch (e) { caughtNote('report-persistence', e); }
  }
  function finishReport(name, body) {
    keepPending(name, body);
    return Promise.resolve(api().post('/api/script/report/' + encodeURIComponent(name) + '/finish', body)).then(function (got) {
      if (got && got.ok === false) throw new Error(got.say || 'the station refused the attachment');
      keepPending(name, null);
      return got;
    });
  }
  function retryReports() {
    pendingReports().forEach(function (held) {
      if (!/^script_[A-Za-z0-9_-]+\.md$/.test(held.name || '')) return;
      finishReport(held.name, held.body).catch(function (err) { caughtNote('report-retry', err); });
    });
  }
  function reportFire(btn, reason) {
    var mine = (reportTurn += 1), tapped = Date.now();
    if (!api() || !api().post) { say('no bridge to file the report through'); return; }
    btn.classList.add('sp-firing');
    function done(text, bad) {
      if (mine !== reportTurn) return;
      btn.classList.remove('sp-firing'); btn.classList.toggle('sp-fired-bad', !!bad); say(text);
      setTimeout(function () { btn.classList.remove('sp-fired-bad'); }, 2600);
    }
    var incident = (root.crypto && root.crypto.randomUUID) ? root.crypto.randomUUID()
      : ('script-' + tapped + '-' + Math.random().toString(16).slice(2));
    var view;
    try { view = reportGather('tap', incident); }
    catch (err) { done('not filed: ' + String(err.message || err).slice(0, 80), true); return; }
    tapped = view.captured_at_ms;
    // Submit the tap immediately. Screenshot latency cannot move the server's
    // initial observation or erase the evidence already collected.
    var initial;
    try { initial = Promise.resolve(api().post('/api/script/report', {view: view,
      reason: reason ? String(reason).slice(0, 1200) : null, incident_id: incident})); }
    catch (err) { done('not filed: ' + String(err.message || err).slice(0, 80), true); return; }
    var shot = reportImage(), flashed = false;
    function flash() { if (flashed) return; flashed = true; reportShutter(); }
    setTimeout(flash, 400); shot.then(flash, flash);
    var after = new Promise(function (resolve) {
      setTimeout(function () {
        try { resolve(reportGather('post', incident, tapped + 1)); }
        catch (err) { resolve({schema_version: 2, phase: 'post', incident_id: incident,
          captured_at_ms: Date.now(), events: [], rows: {}, snapshot: {errors: [{at: Date.now(),
            kind: 'post-capture', msg: String(err.message || err).slice(0, 200)}]}}); }
      }, 10000);
    });
    initial = initial.then(function (got) {
      if (!got || got.ok === false || !got.file) throw new Error((got && got.say) || 'the report was not acknowledged');
      if (mine === reportTurn) say('filed as #' + got.id + ' - capturing 10 seconds after the tap');
      return got;
    });
    Promise.all([initial, after, shot]).then(function (all) {
      var got = all[0], name = String(got.file).split('/').pop();
      var body = Object.assign({view: all[1], incident_id: incident}, all[2]);
      return finishReport(name, body).then(function () {
        done('filed as #' + got.id + ' - capture complete' + (body.screenshot_error ? ' (without a picture)' : ''));
      }, function (err) { done('report #' + got.id + ' kept; attachment pending: ' + String(err.message || err).slice(0, 65), true); });
    }).catch(function (err) { done('not filed: ' + String((err && err.message) || err).slice(0, 80), true); });
  }

  function fireVideo(btn) {
    var mine = (reelTurn += 1);
    function done(text, bad) {
      if (mine !== reelTurn) return;  /* a newer tap owns the screen */
      btn.classList.remove('sp-firing');
      btn.classList.toggle('sp-fired-bad', !!bad);
      say(text);
      setTimeout(function () { btn.classList.remove('sp-fired-bad'); }, 2600);
    }
    /* #1306: the CUE road, not the fill road. dj_sting's path cost
       4.6-5.7s warm, none of it the pick - the chat row, the history
       write, the length probe and the whole satellite/announce
       decision a video never uses. This rings the clip and hands it
       straight back, and the set cuts to it here rather than waiting
       out its own 2.5s poll. Rapid taps therefore cycle. */
    api().post('/api/sfx/video/cue', {who: 'operator'}).then(function (got) {
      var clip = got && got.clip;
      if (!clip) {
        done(String((got && got.say) || 'no clip'), true);
        /* #1361b: A MISS IS A QUESTION, NOT A VERDICT. Four different
           faults have printed the same four words on this strip, and
           only one of them is cured by tapping again. The doctor
           names which one this is and puts the cure under a thumb. */
        try {
          if (root.PineClipDoctor) root.PineClipDoctor.open(String((got && got.say) || ''));
        } catch (err) { /* the strip already said it */ }
        return;
      }
      /* #1311b: an answer that has been overtaken is dropped rather
         than cutting the picture backwards. */
      if (mine !== reelTurn) return;
      try {
        if (root.PineSfxTv && root.PineSfxTv.cut) root.PineSfxTv.cut(clip);
      } catch (err) { /* the clip is in the ring either way */ }
      /* Not an error if the set is not on this surface - the clip is in
         the ring either way and whatever is watching will show it. */
      done(String(clip.sting || 'on the set'));
    }, function (err) {
      done(String((err && err.message) || err).slice(0, 60), true);
    });
  }

  /* #1311: A SHORT WORD ON THE STRIP, AND IT STAYS LONG ENOUGH TO READ.
   *
   * This set the text and then cleared sayingSaid so the next tick
   * would repaint - which it did, 250ms later, over the top of the
   * message. So a tap that answered "the clip library is still
   * warming" showed nothing at all, and a button that was working
   * and refusing looked like a button that was dead. That is how the
   * operator came to report the video icon as unresponsive.
   *
   * The message now holds the strip for a few seconds; paintSaying
   * stands off until it expires. */
  var sayUntil = 0;

  function say(text) {
    var line = el('spSayingText');
    if (!line) return;
    sayUntil = Date.now() + 4000;
    sayingSaid = ' said';        /* never equal to a real print */
    line.textContent = String(text || '');
  }

  /* ---------------------------------------------------------------- 4 */

  /* The tree opens the Pine Box panel. On the tablet that panel already
   * exists as the native drawer - broadcast, routing, the device list - so
   * the tree hands it over rather than building a second one that would
   * drift from it. Where there is no drawer, a small sheet stands in. */
  function buildTree() {
    var tree = make('button', 'sp-tree');
    tree.title = 'Pine Box - broadcast, levels and settings';
    tree.setAttribute('aria-label', 'Pine Box');
    tree.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">'
      + '<path d="M12 2 L17 9 H14 L18.5 15 H14.5 L20 21 H4 L9.5 15 H5.5 L10 9 H7 Z"/>'
      + '<rect x="11" y="21" width="2" height="2"/></svg>';
    tree.addEventListener('click', function () {
      if (root.PineViewChrome && root.PineViewChrome.openMenu() !== 'sheet') return;
      togglePanel();
    });
    return tree;
  }

  function togglePanel() {
    var box = el('spPanel');
    if (!box) return;
    box.hidden = !box.hidden;
  }

  function buildPanel() {
    var box = make('div', 'sp-panel');
    box.id = 'spPanel';
    box.hidden = true;
    box.appendChild(make('h4', '', 'Pine Box'));
    var rows = [
      ['Give this terminal the air', 'solo'],
      ['Let every page sound', 'clear'],
      ['Re-read the script', 'reload']
    ];
    for (var i = 0; i < rows.length; i += 1) {
      (function (label, action) {
        var b = make('button', 'sp-panel-row', label);
        b.addEventListener('click', function () { panelAction(action, b); });
        box.appendChild(b);
      })(rows[i][0], rows[i][1]);
    }
    box.appendChild(make('p', 'sp-panel-why',
      'The full desk - broadcast routing, levels and settings - is in the '
      + 'drawer: swipe in from the left edge.'));
    return box;
  }

  function panelAction(action, button) {
    var was = button.textContent;
    if (action === 'reload') { fetchedAt = 0; loadScreenplay(true); return; }
    button.textContent = 'working...';
    var body = action === 'solo'
      ? {listener: (typeof root.pineListenerId === 'function') ? root.pineListenerId() : ''}
      : {clear: true};
    api().post('/api/radio/solo', body).then(function () {
      button.textContent = was;
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 40);
    });
  }

  /* ---------------------------------------------------------------- 5 */

  function buildPlayer() {
    var box = make('div', 'sp-player');
    box.innerHTML =
      '<img id="spArt" class="sp-art" alt="">'
      + '<div class="sp-playmid">'
      + '<div id="spTitle" class="sp-title"></div>'
      + '<div id="spWho" class="sp-who"></div>'
      + '<canvas id="spSpectrum" class="sp-spectrum"></canvas>'
      + '<canvas id="spVoice" class="sp-voicemeter"></canvas>'
      + '<div class="sp-seekrow">'
      + '<i id="spAt" class="sp-time"></i>'
      + '<input id="spSeek" class="sp-seek" type="range" min="0" max="1000" value="0">'
      + '<i id="spLen" class="sp-time"></i>'
      + '</div></div>'
      + '<button id="spMixDot" class="sp-mixdot" type="button" '
      + 'title="Levels: voices, music, SFX, videos" aria-label="Levels"></button>'
      + '<div class="sp-transport">'
      + '<button id="spPrev" class="sp-tbtn" title="The station’s previous track" aria-label="The station’s previous track">⏮</button>'
      + '<button id="spNext" class="sp-tbtn" title="Skip to the next track" aria-label="Skip to the next track">⏭</button>'
      + '</div>';
    return box;
  }

  /* THE PLAYHEAD IS A REAL SCRUB, and it moves THIS terminal's player.
   *
   * The station owns the broadcast clock; there is no route to move it, and
   * inventing one would desync every other listener. What this scrubs is the
   * element playing here - which is what a hand on a playhead means on the
   * device in front of you - and the labels say the position honestly. Back
   * and forward DO move the station's queue, because those routes exist
   * (/api/dj/prev, /api/dj/next) and skipping is a thing the whole house
   * hears by design. */
  function wirePlayer() {
    var seek = el('spSeek');
    var player = function () { return el('musicPlayer'); };
    var dragging = false;
    if (seek) {
      seek.addEventListener('pointerdown', function () { dragging = true; });
      var release = function () { dragging = false; };
      ['pointerup', 'pointercancel'].forEach(function (n) {
        seek.addEventListener(n, release);
      });
      seek.addEventListener('input', function () {
        var p = player();
        if (!p || !isFinite(p.duration) || !p.duration) return;
        p.currentTime = (Number(seek.value) / 1000) * p.duration;
      });
    }
    seek && (seek.dataset.dragging = '');
    var dot = el('spMixDot');                                    /* #1419 */
    if (dot) dot.addEventListener('click', function (ev) { ev.stopPropagation(); mixerOpen(); });
    var prev = el('spPrev');
    var next = el('spNext');
    if (prev) prev.addEventListener('click', function () { api().post('/api/dj/prev', {}); });
    if (next) next.addEventListener('click', function () { api().post('/api/dj/next', {}); });

    /* The meters and the playhead ride requestAnimationFrame - numbers the
     * browser already has, no request of any kind. */
    var frame = 0;
    var tickN = 0;                    /* #1413c: the meters at the scope's pace */
    var specAt = 0;
    var specOk = false;
    var tick = function () {
      frame = requestAnimationFrame(tick);
      tickN = (tickN + 1) % SCOPE_EVERY;
      if (tickN) return;
      var spectrum = el('spSpectrum');
      /* #1413c: the layout read once a second - clientWidth forces a
         layout of a document the feed keeps dirty, every frame. */
      var nowMs = Date.now();
      if (nowMs - specAt > 1000) {
        specAt = nowMs;
        specOk = !!(spectrum && spectrum.isConnected && spectrum.clientWidth);
      }
      if (!spectrum || !specOk) return;
      var meters = root.PineMeters;
      if (meters) {
        meters.attach(['musicPlayer', 'djVoiceAudio0', 'djVoiceAudio1']);
        meters.draw(spectrum, meters.read('musicPlayer', 'music'), '#54d18b');
        meters.draw(el('spVoice'),
          meters.readLoudest(['djVoiceAudio0', 'djVoiceAudio1'], 'voice'), '#e3be63');
      }
      var p = player();
      if (p && isFinite(p.duration) && p.duration) {
        if (seek && !dragging) seek.value = String(Math.round((p.currentTime / p.duration) * 1000));
        var at = el('spAt'); var len = el('spLen');
        if (at) at.textContent = clock(p.currentTime);
        if (len) len.textContent = clock(p.duration);
      }
    };
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(tick);
    document.addEventListener('pointerdown', function () {
      if (root.PineMeters) root.PineMeters.wake();
    });
  }

  /* #1419: THE MIXER DOT.
   *
   * "Put a dot here that whenever I click it or tap it it brings up a
   *  pop-up that shows volume sliders for the voices, the music, the SFX,
   *  and the videos, and it allows me to adjust the volume levels of each
   *  of them individually and have it retain these settings and remember
   *  it next time."
   *
   * The levels are multipliers (0-100%) on top of whatever the station and
   * the shell already set, kept in this device's localStorage under
   * `pineMixer` and applied through window.pineMixer - the panel's on the
   * tablet (the view is injected into that page), the shell's on the
   * desktop (the view runs in the shell there and the panel is a webview
   * the shell levels). Either way one call, one name. */
  var MIXER_ROWS = [
    ['voice', 'Voices'], ['music', 'Music'], ['sfx', 'SFX'], ['video', 'Videos']
  ];
  function mixerRead() {
    var m = null;
    try { if (root.pineMixer && root.pineMixer.get) m = root.pineMixer.get(); } catch (err) { m = null; }
    if (!m) { try { m = JSON.parse(root.localStorage.getItem('pineMixer') || '{}'); } catch (err) { m = {}; } }
    var out = {};
    MIXER_ROWS.forEach(function (row) {
      var v = Number(m && m[row[0]]);
      out[row[0]] = isFinite(v) ? Math.max(0, Math.min(1.5, v)) : 1;
    });
    return out;
  }
  function mixerWrite(values) {
    try { root.localStorage.setItem('pineMixer', JSON.stringify(values)); } catch (err) { /* private mode */ }
    try { if (root.pineMixer && root.pineMixer.set) root.pineMixer.set(values); } catch (err) { /* applied next time */ }
  }
  function mixerOpen() {
    var old = document.getElementById('spMixBack');
    if (old) { old.remove(); return; }
    var levels = mixerRead();
    var back = make('div', 'sp-mix-back');
    back.id = 'spMixBack';
    var box = make('div', 'sp-mix-box');
    var head = make('div', 'sp-mix-head');
    head.appendChild(make('b', '', 'Levels'));
    var reset = make('button', 'sp-mix-reset', 'Reset');
    reset.type = 'button';
    var shut = make('button', 'sp-mix-shut', '\u2715');
    shut.type = 'button';
    head.appendChild(reset);
    head.appendChild(shut);
    box.appendChild(head);
    var inputs = {};
    MIXER_ROWS.forEach(function (row) {
      var line = make('label', 'sp-mix-row');
      line.appendChild(make('span', 'sp-mix-name', row[1]));
      var range = document.createElement('input');
      range.type = 'range'; range.min = '0'; range.max = '100'; range.step = '1';
      range.value = String(Math.round(levels[row[0]] * 100));
      range.className = 'sp-mix-range';
      var val = make('span', 'sp-mix-val', range.value + '%');
      range.addEventListener('input', function () {
        val.textContent = range.value + '%';
        levels[row[0]] = Number(range.value) / 100;
        mixerWrite(levels);
      });
      inputs[row[0]] = {range: range, val: val};
      line.appendChild(range);
      line.appendChild(val);
      box.appendChild(line);
    });
    box.appendChild(make('div', 'sp-mix-note',
      'Remembered on this device. On top of the station\u2019s own levels.'));
    reset.addEventListener('click', function () {
      MIXER_ROWS.forEach(function (row) {
        levels[row[0]] = 1;
        inputs[row[0]].range.value = '100';
        inputs[row[0]].val.textContent = '100%';
      });
      mixerWrite(levels);
    });
    shut.addEventListener('click', function () { back.remove(); });
    back.addEventListener('click', function (ev) { if (ev.target === back) back.remove(); });
    box.addEventListener('click', function (ev) { ev.stopPropagation(); });
    back.appendChild(box);
    document.body.appendChild(back);
  }
  /* Applied once at load too, so a remembered level is heard before the
     dot is ever touched. */
  try { if (root.pineMixer && root.pineMixer.apply) root.pineMixer.apply(); } catch (err) { /* later */ }

  function clock(v) {
    var t = Math.max(0, Math.round(Number(v) || 0));
    var m = Math.floor(t / 60);
    var s = t % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function paintPlayer(state) {
    var now = (state && state.now) || {};
    var art = el('spArt');
    if (art) {
      var want = now.art || '';
      if (art.dataset.want !== want) {
        art.dataset.want = want;
        if (want) { art.src = want; art.hidden = false; }
        else { art.removeAttribute('src'); art.hidden = true; }
      }
      art.onerror = function () { art.hidden = true; };
    }
    var title = el('spTitle');
    if (title) title.textContent = now.title || 'the station';
    var who = el('spWho');
    if (who) {
      who.textContent = [now.artist, now.album].filter(Boolean).join(' · ');
    }
  }

  /* ---------------------------------------------------------------- 6 */

  /* "Like an instant message correspondence" - newest at the bottom,
   * endless, auto-scrolling. APPEND ONLY: the whole reason this reads as a
   * conversation rather than a table is that rows never move once written.
   * Rebuilding the list each tick would also throw away the operator's
   * scroll position, which is the one thing an endless feed must not do. */
  function paintFeed(state) {
    var box = el('spFeed');
    if (!box) return;
    /* #1279: KEPT AND RE-SEATED, NOT APPENDED AND FROZEN.
     *
     * This drew each id once, in first-appearance order, and never
     * moved or refreshed it. That would be fine if rows arrived in the
     * order they sound - but a burst is published up to 58.8 SECONDS
     * before any of it is audible (measured; mean 5.7 future-stamped
     * rows per poll). Replayed against a real 16-poll sequence this
     * function's order came out 104 of 253 pairs discordant - 41.1% -
     * with interjections that sound 13-40s EARLIER parked underneath
     * lines nobody had said yet, for the life of the pane.
     *
     * Rows are held by id now and put back in `air_at` order on every
     * paint. That key is itself a moving target, but re-seating lets
     * the feed CORRECT ITSELF when a stamp moves instead of being
     * frozen wrong. Their words and state are refreshed too: a row
     * drawn while `prepared` used to still read `prepared` long after
     * it had aired. */
    var rows = (state && state.chat) || [];
    var added = 0;
    var want = [];
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      var id = String((row && row.id) || '');
      if (!id) continue;
      var node = feedNodes[id];
      if (!node) {
        node = feedRow(row);
        feedNodes[id] = node;
        seen[id] = true;
        added += 1;
      } else {
        feedDress(node, row);
      }
      node.pineAt = Number(row.air_at || row.ts || 0);
      want.push(node);
    }
    if (want.length) {
      want.sort(function (a, b) { return a.pineAt - b.pineAt; });
      /* #1287: an insertBefore on an attached node is a detach and an
         attach, so stitching an already-correct list still takes every
         row out of the document for an instant. Check first: with the
         treadmill above gone, the order matches on nearly every paint
         and this loop does nothing at all. */
      var settled = true;
      var walk = box.firstChild;
      for (var c2 = 0; c2 < want.length; c2 += 1) {
        while (walk && /sp-msg-ev/.test(walk.className)) walk = walk.nextSibling;
        if (walk !== want[c2]) { settled = false; break; }
        walk = walk.nextSibling;
      }
      if (!settled) {
        var cursor = box.firstChild;
        for (var w = 0; w < want.length; w += 1) {
          if (want[w] === cursor) { cursor = cursor.nextSibling; continue; }
          box.insertBefore(want[w], cursor);
        }
      }
    }
    /* The station also does things that are not speech. */
    var log = (state && state.activity_log) || [];
    for (var k = 0; k < log.length; k += 1) {
      var ev = log[k];
      var key = 'ev' + (ev && ev.at) + String((ev && ev.stage) || '');
      if (!ev || seen[key]) continue;
      seen[key] = true;
      box.appendChild(eventRow(ev));
      added += 1;
    }
    /* #1287: THE TRIM STOPS EVICTING ROWS IT STILL WANTS.
     *
     * #1279 trimmed on `box.children.length > FEED_MAX`, and the pane
     * holds activity rows and orphans as well as chat rows - so
     * several WANTED rows never fit inside the 240. The trim evicted
     * them from the front, forgot them, and the next paint recreated
     * them, re-inserted them at the front, and the trim evicted six
     * again. Measured: 65,023 detach/re-attach events in 9.2 minutes,
     * 7,055 a minute, at 3.67 paints a second - the largest single
     * reason a row moves under the operator's finger, and my own.
     *
     * Orphans go first, the cap counts only what is wanted, and a row
     * still in `want` is never evicted. */
    var keep = Object.create(null);
    for (var w2 = 0; w2 < want.length; w2 += 1) {
      var wid = want[w2].getAttribute('data-line');
      if (wid) keep[wid] = 1;
    }
    var kids = [].slice.call(box.children);
    for (var k2 = 0; k2 < kids.length; k2 += 1) {
      var kid = kids[k2];
      var kidId = kid.getAttribute && kid.getAttribute('data-line');
      if (!kidId || keep[kidId]) continue;
      if (/sp-msg-ev/.test(kid.className)) continue;   /* an event row */
      box.removeChild(kid);                            /* an orphan */
      delete feedNodes[kidId];
      if (feedLive === kidId) feedLive = '';
    }
    var over = want.length - FEED_MAX;
    for (var t2 = 0; t2 < over; t2 += 1) {
      var old = want[t2];
      var oldId = old && old.getAttribute && old.getAttribute('data-line');
      if (old && old.parentNode === box) box.removeChild(old);
      if (oldId) {
        delete feedNodes[oldId];
        if (feedLive === oldId) feedLive = '';
      }
    }
    if (!added && over <= 0) return;
    if (feedStick) box.scrollTop = box.scrollHeight;
  }

  function feedRow(row) {
    var who = String(row.who || 'dj');
    /* #1279: NOT from `row.aired === "airing"`. That is spelled right
       and is unreachable - `airing` is attached only to speaking_now /
       stream_now, never to a chat row (measured: 0 of 317 across 16
       polls), so this pane has never once marked the line being said.
       markFeedLive() does it from the live pointer, every tick. */
    var line = make('div', 'sp-msg');
    line.dataset.line = String(row.id || '');
    line.appendChild(make('b', 'sp-msg-who', row.name || who));
    line.appendChild(make('span', 'sp-msg-text', ''));
    feedDress(line, row);
    line.addEventListener('click', function () { jumpToLine(String(row.id || '')); });
    return line;
  }

  /* #1279: a row's words and state as they are NOW. A row used to be
     drawn once and never touched again, so one drawn while it was
     `prepared` still read `prepared` long after it had aired. */
  function feedDress(line, row) {
    var head = line.firstChild;
    var body = line.lastChild;
    var name = String(row.name || row.who || 'dj');
    var text = String(row.text || '').trim();
    if (head && head.textContent !== name) head.textContent = name;
    if (body && body.textContent !== text) body.textContent = text;
    var state = String(row.aired || '');
    if (line.pineState !== state) {
      line.pineState = state;
      line.classList.toggle('pending', state === 'prepared');
    }
  }

  /* #1279: THE LINE THAT IS SOUNDING, marked from the live pointer and
     re-asserted on every tick, so it cannot be stranded by a row that
     was drawn before it started. */
  function markFeedLive(id) {
    var want = String(id || '');
    if (want === feedLive) return;
    var was = feedLive && feedNodes[feedLive];
    if (was) was.classList.remove('airing');
    feedLive = want;
    var node = want && feedNodes[want];
    if (node) node.classList.add('airing');
  }

  function eventRow(ev) {
    var line = make('div', 'sp-msg sp-msg-ev');
    line.appendChild(make('b', 'sp-msg-who', String(ev.stage || 'station')));
    line.appendChild(make('span', 'sp-msg-text', String(ev.detail || '')));
    return line;
  }

  /* ---------------------------------------------------------------- 7 */

  function loadScreenplay(force) {
    var now = Date.now();
    if (fetching) return;
    if (!force && now - fetchedAt < SCREENPLAY_REST_MS) return;
    /* #1273b: a FORCED read is one the page asked for because the line
       it needs is missing (#1271). Asking for the cached copy would
       hand back the very page that just failed to contain it - measured
       16.1s old, against 2.1s with `fresh`. The rest poll stays cached,
       and so does the hour before: it is closed, 238 kB, and the server
       holds it for fifteen minutes. */
    var live = force ? '?fresh=1' : '';
    fetching = true;
    api().get('/api/screenplay').then(function (index) {
      var hours = (index && index.hours) || [];
      if (!hours.length) throw new Error('no hours written yet');
      hourKey = String(hours[0].key || '');
      /* #1268: THE READING DOES NOT END BECAUSE THE HOUR DID.
       *
       * "I want to put on my reading glasses and watch the pine box go
       *  through an endless reading that is endlessly streamed."
       *
       * This asked for hours[0] and nothing else, so at the top of
       * every hour the whole script was replaced by a nearly empty
       * page - measured at the 3 PM turn, 350 entries down to 0 - and
       * the reader's place went with it. Worse, a burst that straddles
       * the turn is still SOUNDING while the lines it is saying have
       * just left the page, so the highlight has nothing to land on.
       *
       * The hour before is carried too, above it and in order. The
       * window stays bounded: as the clock rolls, hours[1] becomes the
       * hour that just ended and the one before it drops off the top,
       * so this is always one to two hours of script and never grows.
       */
      var before = hours[1] && Number(hours[1].lines || 0) > 0
        ? String(hours[1].key || '') : '';
      /* #1276: THE HOUR THAT IS OVER IS FETCHED ONCE.
       *
       * This asked for both hours on every poll AND every chase. The
       * earlier hour is 238 kB, it is closed, and the server holds it
       * for fifteen minutes - the answer cannot change. Worse,
       * `fetching` is one latch across the whole Promise.all, so while
       * that 238 kB was in flight the #1271 chase returned at
       * `if (fetching) return;` and the live line could not be
       * collected. Measured on the tablet: thirty seconds after opening
       * the view, script rendered, nothing lit, because the sounding
       * line was not on the page yet.
       *
       * It is kept until the clock rolls and a different hour becomes
       * the one before. */
      var want = [api().get('/api/screenplay/'
        + encodeURIComponent(hourKey) + live)];
      if (before && before === beforeKey && beforePage) {
        want.push(Promise.resolve(beforePage));        /* already held */
      } else if (before) {
        want.push(api().get('/api/screenplay/' + encodeURIComponent(before))
          .then(function (page) {
            beforeKey = before; beforePage = page; return page;
          }, function () { return null; }));   /* its loss is survivable */
      } else {
        beforeKey = ''; beforePage = null;
      }
      return Promise.all(want).then(function (got) {
        return {now: got[0] || {}, was: got[1] || null,
          nowKey: hourKey, wasKey: before};
      });
    }).then(function (both) {
      var page = both.now;
      /* Each element remembers WHICH HOUR it belongs to, so a note put
         on a line from the earlier hour is filed against that hour and
         not against the one on screen. */
      function stamp(list, key) {
        var out = [];
        for (var i = 0; i < (list || []).length; i += 1) {
          var it = list[i];
          if (it && typeof it === 'object') { it.hour = key; out.push(it); }
        }
        return out;
      }
      elements = stamp(both.was && both.was.elements, both.wasKey)
        .concat(stamp(page.elements, both.nowKey));
      fetchedAt = Date.now();
      fetching = false;
      paintScript(page, both.was);
    }, function (err) {
      fetching = false;
      var box = el('spScript');
      if (box && !box.children.length) {
        box.appendChild(make('p', 'sp-empty',
          'The script could not be read: ' + ((err && err.message) || err)));
      }
    });
  }

  /* Hollywood layout: each element type is its own block, and the CSS does
   * the indenting the way a script does - character centred over dialogue,
   * parentheticals tucked inside it, action full width. */
  function paintScript(page, before) {
    var box = el('spScript');
    if (!box) return;
    var head = el('spScriptHead');
    if (head && page) {
      /* #1268: the count is of what is ON THE PAGE, both hours of it,
         because that is what the reader can scroll through. */
      var lines = (page.counts && page.counts.lines) || 0;
      var back = (before && before.counts && before.counts.lines) || 0;
      head.textContent = (page.title || 'the broadcast')
        + '  ·  ' + (lines + back) + ' lines'
        + (back ? '  (with the hour before)' : '')
        + (page.live ? '  ·  live' : '');
    }
    var atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    /* #1269: REBUILD ONLY WHAT CHANGED.
     *
     * "keep an eye on how it is jumping around"
     *
     * This used to replaceChildren() and re-append EVERY element on
     * every poll - twenty seconds, a few hundred nodes, and with the
     * hour before it now carried too (#1268) a few hundred more. Every
     * node the reader was looking at was destroyed and rebuilt, which
     * throws the scroll offset and drops the highlight (nowLineId was
     * cleared just below, unconditionally), so the page re-seated
     * itself three times a minute whether anything had changed or not.
     *
     * #1269 answered that with a longest-common-PREFIX compare, on the
     * reasoning that a script only ever grows at the end. It does not,
     * and #1273 below replaces it - see there for what moves the page
     * and what it measured. This note is kept only because the fault it
     * describes is still the right one to have been chasing.
     */
    /* #1273: KEPT, NOT REBUILT. The prefix match this replaces assumed
     * the script only grows at the end; measured on air it destroyed 240
     * nodes over eight polls, 238 of them identical content that had
     * merely moved. See the patch note for the three things that move
     * it. Nodes are keyed by the server's element id and kept. */
    if (paintedIn !== box) { scriptNodes.clear(); paintedIn = box; }
    var anchor = scriptAnchor(box);
    var order = [];
    var wanted = Object.create(null);
    for (var i = 0; i < elements.length; i += 1) {
      var item = elements[i];
      var key = String(item.id || '') || ('ix:' + i);
      wanted[key] = 1;
      /* Everything the node's APPEARANCE depends on, so a line revised
         in place is re-dressed rather than rebuilt. */
      var print = String(item.text || '') + SEP + String(item.type || '')
        + SEP + String(item.aired || '') + SEP + (item.tinted ? '1' : '0');
      var node = scriptNodes.get(key);
      if (node && node.pinePrint !== print) {
        var lit = node.classList.contains('sp-now');
        var picked = node.classList.contains('picked');
        node.textContent = String(item.text || '');
        node.className = 'sp-el sp-' + String(item.type || 'action')
          + ((item.aired === 'prepared' || item.aired === 'withdrawn')   /* 2026-09-14: refused at hand-over - never aired */ ? ' pending' : '')
          + (item.tinted ? ' tinted' : '')
          + (lit ? ' sp-now' : '') + (picked ? ' picked' : '');
        node.pinePrint = print;
      }
      if (!node) {
        node = scriptBlock(item);
        node.pinePrint = print;
        scriptNodes.set(key, node);
      }
      /* #1303b: THE NODE CARRIES THE CURRENT ITEM.
         The click handler scriptBlock attaches closes over the item the
         node was BUILT with, and a re-dress does not refresh it. Anything
         reading the node later - the strip's hold, for one - should get
         what this line says now. */
      node.pineItem = item;
      // Keep evidence attributes in step with a keyed node's current item.
      ['line', 'seg', 'block', 'ord'].forEach(function (field) {
        if (item[field] !== undefined && item[field] !== null) node.dataset[field] = String(item[field]);
        else delete node.dataset[field];
      });
      order.push(node);
    }
    scriptNodes.forEach(function (held, key) {
      if (wanted[key]) return;
      if (held.parentNode === box) held.remove();
      scriptNodes.delete(key);
    });
    stitchScript(box, order);
    scriptRestore(box, anchor);
    diagnosticDocument(box);
    ensureCaution();
    /* FOLLOWING BEATS STICKING TO THE END.
     * The live line sits wherever the conversation has got to, and the end
     * of the hour is usually well past it; scrolling to the bottom after
     * every repaint would drag the operator away from the line being said
     * twenty seconds after it arrived. */
    if (stick && atEnd && !(follow && nowLineId)) {
      moveScript('end', function (pane) { pane.scrollTop = pane.scrollHeight; });
    }
    /* #1273: THE MARK IS RE-ASSERTED, NOT MERELY REMEMBERED.
       #1269 asked whether a node with this id existed - not whether it
       still CARRIED the mark. A rebuilt node exists without .sp-now, so
       nowLineId stayed set, markNow returned at `id === nowLineId`, and
       the page showed no highlight at all until the station moved on.
       That is the operator's "highlighting incorrect segments". Keyed
       nodes make it rare; asking the right question makes it
       impossible. */
    if (nowLineId) {
      var held = box.querySelector('.sp-el[data-line="' + nowLineId + '"]');
      if (!held) nowLineId = '';
      else if (!held.classList.contains('sp-now')) held.classList.add('sp-now');
    }
    /* #1285: re-assert the folds, so a line arriving into a folded
       segment arrives folded rather than springing it open. */
    segApply();
    tick();
  }

  /* ONE SCROLL CONTROLLER.
   *
   * "Use one scroll controller."
   *
   * There were four movers of this pane and only one of them declared
   * itself: the follow scroll in markNow stamped `selfScrollUntil`, while
   * the stick-to-end after a repaint, the reader's-place restore and the
   * tap-to-line jump all moved the box silently. Each of those fires the
   * pane's own scroll handler, which reads "the operator has scrolled by
   * hand" and switches following OFF - the page cancelling its own
   * following, which is the exact fault #1282 was fixed for once already.
   *
   * So every movement goes through here, declares a reason, and is
   * recorded for the incident report. A follow may not overrule a restore
   * in the same frame: the operator's place beats an automatic move. */
  var scrollOwner = '';
  var scrollAt = 0;
  var scrollLog = [];

  function moveScript(reason, apply) {
    var box = el('spScript');
    if (!box) return false;
    var now = Date.now();
    if (reason === 'follow' && scrollOwner === 'restore' && now - scrollAt < 80) {
      return false;
    }
    scrollOwner = reason;
    scrollAt = now;
    scrollLog.push({at: now, why: reason, top: Math.round(box.scrollTop)});
    if (scrollLog.length > 40) scrollLog.shift();
    selfScrollUntil = now + 2400;          /* backstop only */
    /* #1330: on the box that actually scrolls - `scrollend` clears the
       backstop early, and the backstop governs when it is unavailable. */
    try {
      if ('onscrollend' in box) {
        box.addEventListener('scrollend', function done() {
          box.removeEventListener('scrollend', done);
          selfScrollUntil = 0;
        }, {once: true});
      }
    } catch (err) { /* the backstop still covers it */ }
    try { apply(box); } catch (err) { caughtNote('scroll:' + reason, err); }
    return true;
  }

  /* #1273: HOLD THE READER'S PLACE ACROSS A REPAINT. Measure one row
     that is actually on screen before, find the SAME element after, and
     move the scroll by the difference - so an element inserted above the
     reader does not drag the page out from under them. Deliberately not
     derived from offsetTop; the sampler's commit records why that
     failed. */
  function scriptAnchor(box) {
    if (!box || box.scrollTop <= 4) return {pinned: true};
    var lip = box.getBoundingClientRect();
    for (var i = 0; i < box.children.length; i += 1) {
      if (!box.children[i].classList.contains('sp-el')) continue;
      var seat = box.children[i].getBoundingClientRect();
      if (seat.height <= 0) continue;
      if (seat.bottom <= lip.top + 1) continue;      /* scrolled off the top */
      return {node: box.children[i], was: seat.top};
    }
    return {pinned: true};
  }

  function scriptRestore(box, anchor) {
    if (!box || !anchor || anchor.pinned) return;
    var node = anchor.node;
    /* It left the page while it was being read. Leave the scroll alone:
       the browser's own anchoring has already chosen a neighbour. */
    if (!node || node.parentNode !== box) return;
    var drift = node.getBoundingClientRect().top - anchor.was;
    if (Math.abs(drift) > 0.5) {
      moveScript('restore', function (pane) {
        pane.scrollTop = Math.max(0, pane.scrollTop + drift);
      });
    }
  }

  /* Put `order` into `box`, in that order, moving as little as possible.
     A node already in the right place costs one comparison; anything
     else is one insertBefore. */
  function stitchScript(box, order) {
    var cursor = box.firstChild;
    if (cursor && cursor.id === 'spCautionWrap') cursor = cursor.nextSibling;
    for (var i = 0; i < order.length; i += 1) {
      if (order[i] === cursor) { cursor = cursor.nextSibling; continue; }
      box.insertBefore(order[i], cursor);
    }
    /* #1289: the plan is not an element of the screenplay and must
       survive the stitch. It is kept, and kept last. */
    var plan = null;
    while (cursor) {
      var next = cursor.nextSibling;
      if (cursor.id === 'spPlan') { plan = cursor; }
      else if (cursor.id === 'spCautionWrap') { /* retained control */ }
      else { cursor.remove(); }
      cursor = next;
    }
    if (plan) box.appendChild(plan);
  }

  /* #1285: fold a finished segment, leave the one on air open.
   *
   * Done by hiding members rather than nesting them: the reconciler
   * (#1273) stitches a FLAT list, and that is the fix that stopped this
   * page destroying a few hundred nodes a poll and losing the highlight
   * with them. A tree would undo it. */
  /* #1300: what each segment was last left as, so a repaint that
     re-asserts the same folds does not replay their motion. */
  var segWas = Object.create(null);
  var segFxTimer = 0;
  var FOLD_FX_MOST = 140;        /* beyond this a segment snaps */
  var FOLD_FX_MS = 260;

  function segApply(motion) {
    var box = el('spScript');
    if (!box) return;
    var all = box.querySelectorAll('.sp-el');
    var moving = [], shutting = [], opening = [];      /* #1300 */
    /* #1294: EVERYTHING BEHIND THE AIR IS SHUT, NOT ONLY THE SEGMENT
     * IT JUST LEFT.
     *
     * segFollow folds the one the air walks out of, and `folded`
     * starts empty - so every segment that had already finished when
     * the page painted stayed open for ever. Measured: 0 to 3 shut of
     * 51-57 scenes, ~2,100 elements and ~62,000 px of scroll. The fold
     * worked; it was just never reached.
     *
     * DOM order is script order (the reconciler stitches the canonical
     * list), so "behind" is "before the first element of the live
     * segment". A hand still outranks this, and with nothing on air
     * nothing is folded. */
    if (liveSeg) {
      var seen = Object.create(null);
      var reached = false;
      for (var p = 0; p < all.length; p += 1) {
        var mark = all[p].getAttribute('data-seg') || '';
        if (!mark) continue;                     /* plan rows, spacers */
        if (mark === liveSeg) { reached = true; break; }
        seen[mark] = 1;
      }
      if (reached) {
        for (var key in seen) {
          if (!byHand[key]) folded[key] = true;
        }
      }
    }
    /* #1300b: WHICH SEGMENTS CHANGED, SETTLED BEFORE ANYTHING IS
     * WRITTEN.
     *
     * This used to be decided inside the loop below, against segWas,
     * which the same loop also updated - and a segment's SCENE HEADING
     * is its first element in DOM order. The heading is excluded from
     * the motion by `!head`, so it fell through and wrote segWas for
     * the whole segment; by the time the members were reached the
     * value they needed to compare against was already the new one,
     * and not one of them ever animated. Measured on the tablet: a
     * fold opening 51 members, `sp-fx` on zero of them.
     *
     * A loop must not both read and write the memo it is deciding by. */
    var segsNow = Object.create(null);
    var changed = Object.create(null);
    for (var q = 0; q < all.length; q += 1) {
      var qseg = all[q].getAttribute('data-seg') || '';
      if (!qseg || segsNow[qseg] !== undefined) continue;
      var qshut = !!(folded[qseg] && qseg !== liveSeg);
      segsNow[qseg] = qshut;
      if (segWas[qseg] !== undefined && segWas[qseg] !== qshut) {
        changed[qseg] = 1;
      }
    }

    for (var i = 0; i < all.length; i += 1) {
      var node = all[i];
      var seg = node.getAttribute('data-seg') || '';
      var head = /sp-scene/.test(node.className);
      var shut = !!(seg && folded[seg] && seg !== liveSeg);
      /* The heading is how a folded segment is reopened, so it is the
         one thing that must never be hidden by its own fold. */
      /* #1300: and when this segment has just CHANGED state, it is
         shown changing rather than simply being different. */
      if (seg && motion && changed[seg] && !head
          && (moving.length < FOLD_FX_MOST)) {
        moving.push(node);
        if (shut) {
          /* Stays in layout while it collapses; hidden at the end. */
          node.hidden = false;
          node.classList.add('sp-fx');
          shutting.push(node);
        } else {
          node.hidden = false;
          node.classList.add('sp-fx', 'sp-gone');
          opening.push(node);
        }
        continue;                 /* segWas is settled after the loop */
      }
      node.hidden = shut && !head;
      if (head) {
        node.classList.toggle('sp-shut', shut);
        /* #1285b: what is inside, so a closed segment can be chosen
           without opening it. On an attribute and shown through
           ::after - the reconciler re-dresses a changed element with
           textContent and would wipe a child span every repaint. */
        if (shut) {
          var got = segCount(seg);
          node.setAttribute('data-inside', got
            ? ('  ▸ ' + got.lines + (got.lines === 1 ? ' line' : ' lines')
               + (got.seconds >= 1
                  ? '  ·  ' + Math.round(got.seconds) + 's' : ''))
            : '  ▸');
        } else {
          node.setAttribute('data-inside', '');
        }
      }
    }
    /* #1300b: and only now, once every element has been able to read
       the old value. */
    for (var done in segsNow) segWas[done] = segsNow[done];
    segSettle(shutting, opening);                            /* #1300 */
  }

  /* #1300: THE BATCH, FINISHED TOGETHER.
   *
   * One timer for the whole pass rather than one per node - a few
   * hundred timers is the kind of thing that makes a tablet stutter,
   * and they would all land in the same frame anyway.
   *
   * The close is only committed to `hidden` at the end, so a folded
   * segment still costs nothing in layout once it has gone; the open
   * only has to drop the class it started from. */
  function segSettle(shutting, opening) {
    if (!shutting.length && !opening.length) return;
    if (opening.length) {
      /* A frame with the start value on the node, or there is nothing
         for the transition to run FROM and it arrives instantly. */
      root.requestAnimationFrame(function () {
        for (var i = 0; i < opening.length; i += 1) {
          opening[i].classList.remove('sp-gone');
        }
      });
    }
    if (shutting.length) {
      root.requestAnimationFrame(function () {
        for (var i = 0; i < shutting.length; i += 1) {
          shutting[i].classList.add('sp-gone');
        }
      });
    }
    if (segFxTimer) root.clearTimeout(segFxTimer);
    segFxTimer = root.setTimeout(function () {
      segFxTimer = 0;
      for (var i = 0; i < shutting.length; i += 1) {
        shutting[i].hidden = true;
        shutting[i].classList.remove('sp-fx', 'sp-gone');
      }
      for (var k = 0; k < opening.length; k += 1) {
        opening[k].classList.remove('sp-fx', 'sp-gone');
      }
    }, FOLD_FX_MS + 40);
  }

  /* What is inside a fold, so it can be chosen without opening it. */
  function segCount(seg) {
    var box = el('spScript');
    if (!box || !seg) return null;
    var all = box.querySelectorAll('.sp-el[data-seg="' + seg + '"]');
    var lines = 0, secs = 0;
    for (var i = 0; i < all.length; i += 1) {
      if (!/sp-dialogue/.test(all[i].className)) continue;
      lines += 1;
      secs += Number(all[i].getAttribute('data-secs') || 0) || 0;
    }
    return {lines: lines, seconds: secs};
  }

  function segToggle(seg) {
    if (!seg) return;
    folded[seg] = !folded[seg];
    byHand[seg] = true;              /* the operator's choice outranks */
    segApply(true);                                          /* #1300 */
    foldSave();                                              /* #1294 */
  }

  /* #1294: THE READER'S PLACE OUTLIVES THE VIEW.
   *
   * The kiosk Activity is recreated roughly every five minutes - the
   * gallery writes the device wallpaper, systemui regenerates the
   * Material You overlays, and the resulting CONFIG_ASSETS_PATHS
   * (0x80000000) is not in MainActivity's configChanges mask, so the
   * WebView reloads. Seven relaunches in 33 minutes, each taking every
   * fold and the scroll position with it.
   *
   * localStorage, NOT sessionStorage: a relaunch is a new session and
   * would take session storage with it. Every read and write is
   * guarded - the accessor itself throws in some contexts - and a page
   * with nothing stored must render correctly, which here means the
   * folds simply start closed-behind-the-air as they now do anyway. */
  var FOLD_KEY = 'pine.script.folds.v1';

  function foldSave() {
    try {
      var box = el('spScript');
      root.localStorage.setItem(FOLD_KEY, JSON.stringify({
        folded: folded, byHand: byHand, liveSeg: liveSeg,
        top: box ? Math.round(box.scrollTop) : 0, at: Date.now()}));
    } catch (err) { /* storage blocked: the view still works */ }
  }

  var foldTop = -1;                  /* the scroll to restore, once */

  function foldLoad() {
    var held = null;
    try {
      held = JSON.parse(root.localStorage.getItem(FOLD_KEY) || 'null');
    } catch (err) { held = null; }
    if (!held || typeof held !== 'object') return;
    /* Stale beyond an hour is not this show any more. */
    if (Date.now() - Number(held.at || 0) > 3600000) return;
    if (held.folded && typeof held.folded === 'object') {
      for (var a in held.folded) folded[a] = !!held.folded[a];
    }
    if (held.byHand && typeof held.byHand === 'object') {
      for (var b in held.byHand) byHand[b] = !!held.byHand[b];
    }
    if (Number(held.top) > 0) foldTop = Number(held.top);
  }

  /* The air moved on: fold what it left, unless a hand opened it. */
  function segFollow(seg) {
    if (!seg || seg === liveSeg) return;
    var was = liveSeg;
    liveSeg = seg;
    if (was && !byHand[was]) folded[was] = true;
    folded[seg] = false;
    /* #1300: the hand-off the operator asked to SEE - the finished
       script shutting and the next one opening out. */
    segApply(true);
    foldSave();                                              /* #1294 */
  }

  /* #1289: THE HOUR AHEAD. /api/director?hour=N is already the hour
     as ordered entries, and a planned one carries its written turns. */
  function loadPlan(force) {
    if (planning) return;
    if (!force && Date.now() - planAt < PLAN_REST_MS) return;
    planning = true;
    var want = [api().get('/api/director?hour=0')
      .then(null, function () { return null; })];
    want.push(api().get('/api/director?hour=1')
      .then(null, function () { return null; }));
    Promise.all(want).then(function (got) {
      var fresh = got.filter(Boolean);
      planning = false;
      /* #1289b: a failed read must not WIPE the running order. Both
         fetches swallow their own errors and return null, so a blip
         used to hand back an empty list, paintPlan cleared the node,
         and the hour ahead vanished until the next poll. Keep what we
         have unless something better arrived. */
      if (!fresh.length) return;
      planHours = fresh;
      planAt = Date.now();
      paintPlan();
    }, function () { planning = false; });
  }

  function planRow(cls, text) {
    return make('div', 'sp-el ' + cls, String(text || ''));
  }

  /* #1294: the plan's own keyed nodes. paintPlan called
     box.replaceChildren() on a thirty-second timer - 509 nodes
     destroyed in one batch, ~1,012 a minute, and in one round of
     sixteen it wiped every visible plan row. This is the stitch
     paintScript has had since #1273, on the one pane that never got
     it. */
  var planNodes = new Map();
  var planIn = null;

  function planKeep(key, cls, text) {
    var print = cls + '\u0001' + text;
    var node = planNodes.get(key);
    if (node && node.pinePrint !== print) {
      node.className = cls;
      node.textContent = text;
      node.pinePrint = print;
    }
    if (!node) {
      node = make('div', cls, text);
      node.pinePrint = print;
      planNodes.set(key, node);
    }
    return node;
  }

  function paintPlan() {
    var box = el('spPlan');
    if (!box) return;
    if (planIn !== box) { planNodes.clear(); planIn = box; }
    if (!planHours.length) {
      if (planNodes.size) { box.replaceChildren(); planNodes.clear(); }
      return;
    }
    var order = [];
    var wanted = Object.create(null);
    for (var h = 0; h < planHours.length; h += 1) {
      var page = planHours[h] || {};
      var rows = page.entries || [];
      var ahead = [];
      for (var i = 0; i < rows.length; i += 1) {
        /* What has already been said is the screenplay's job; this pane
           is only what is still to come. */
        var st = String(rows[i].state || '');
        if (st === 'aired' || st.indexOf('went by') === 0) continue;
        ahead.push(rows[i]);
      }
      if (!ahead.length) continue;
      var hourKey = 'h:' + h;
      var when = planKeep(hourKey, 'sp-el sp-planhour sp-planjump',
        (h === 0 ? 'STILL TO COME THIS HOUR' : 'THE HOUR AFTER')
        + '  ·  ' + ahead.length
        + (ahead.length === 1 ? ' segment' : ' segments'));
      wanted[hourKey] = 1;
      /* #1294: in `below` the plan sits 60,242 px down a 62,386 px
         scroll - the whole night away from the line being said. The
         heading is the handle back. Attached once, because planKeep
         hands back the SAME node every repaint. */
      if (!when.__jump) {
        when.__jump = 1;
        when.addEventListener('click', function () {
          if (nowLineId) jumpToLine(nowLineId);
        });
      }
      order.push(when);
      for (var k = 0; k < ahead.length; k += 1) {
        var e = ahead[k];
        var sc = e.script || {};
        var turns = sc.turns || [];
        var mark = String(e.state || '');
        var clock = e.start
          ? new Date(Number(e.start) * 1000).toTimeString().slice(0, 5) : '';
        var segKey = 'p:' + h + ':' + String(e.slot_id || e.ordinal || k);
        var head = planKeep(segKey, 'sp-el sp-planseg'
          + (mark === 'on air' ? ' sp-planlive' : '')
          + (turns.length ? '' : ' sp-planbare'),
          (clock ? clock + '  ' : '')
          + String(e.label || e.kind || 'segment').toUpperCase()
          + '   ' + (e.minutes ? e.minutes + ' MIN' : ''));
        head.setAttribute('data-plan', String(e.slot_id || e.ordinal || k));
        head.setAttribute('data-state', mark);
        wanted[segKey] = 1;
        order.push(head);
        if (!turns.length) {
          /* A hole is shown, not hidden: an operator who sees it before
             the slot arrives can still do something about it. */
          var bare = planKeep(segKey + ':why', 'sp-el sp-planwhy',
            mark || 'nothing behind it');
          wanted[segKey + ':why'] = 1;
          order.push(bare);
          continue;
        }
        for (var t2 = 0; t2 < turns.length; t2 += 1) {
          var turn = turns[t2];
          var cueKey = segKey + ':c' + t2;
          var lineKey = segKey + ':l' + t2;
          order.push(planKeep(cueKey, 'sp-el sp-character sp-plancue',
            String(turn.who || turn.seat || '').toUpperCase()));
          order.push(planKeep(lineKey, 'sp-el sp-dialogue sp-planline',
            String(turn.text || '')));
          wanted[cueKey] = 1;
          wanted[lineKey] = 1;
        }
      }
    }
    planNodes.forEach(function (held, key) {
      if (wanted[key]) return;
      if (held.parentNode === box) held.remove();
      planNodes.delete(key);
    });
    stitchScript(box, order);
  }

  /* #1289: the two layouts differ only in where the plan hangs. */
  function planLayout(way) {
    planWay = (way === 'beside') ? 'beside' : 'below';
    var box = el('spPlan');
    var script = el('spScript');
    if (!box || !script || !script.parentNode) return;
    host.classList.toggle('sp-beside', planWay === 'beside');
    if (planWay === 'below') {
      script.appendChild(box);                 /* one continuous scroll */
    } else {
      script.parentNode.insertBefore(box, script.nextSibling);
    }
  }

  function scriptBlock(item) {
    var type = String(item.type || 'action');
    var node = make('div', 'sp-el sp-' + type);
    node.textContent = String(item.text || '');
    if (item.id) node.dataset.el = String(item.id);
    if (item.line) node.dataset.line = String(item.line);
    if (item.seg) node.dataset.seg = String(item.seg);        /* #1285 */
    if (item.seconds) node.dataset.secs = String(item.seconds);
    if (type === 'scene') {
      /* #1285: the heading is the fold's handle. */
      node.classList.add('sp-fold');
      node.addEventListener('click', function (ev) {
        ev.stopPropagation();        /* not a pane gesture (#1272) */
        segToggle(String(item.seg || item.id || ''));
      });
    }
    /* A line that has not aired yet is the interesting one - it can still
     * be changed before the room hears it. ONLY 'prepared' is that line;
     * 'published' and 'stream' have both already been heard. */
    if ((item.aired === 'prepared' || item.aired === 'withdrawn')   /* 2026-09-14: refused at hand-over - never aired */) node.classList.add('pending');
    if (item.tinted) node.classList.add('tinted');
    /* #1330: the record that is on the deck RIGHT NOW, not one that
     * finished an hour ago. The two read identically before this, so a
     * script that had just caught up with a track change looked exactly
     * like one that had skipped it - which is how "the script jumped
     * over changing the track" is what a forty second lag looks like
     * from the outside. The server says which; this shows it. */
    if (item.playing) node.classList.add('sp-spinning');
    /* #1330: where the SCRIPT put this line. Carried so a reader can
     * follow the running order without re-deriving it, and so the mark
     * can tell a scripted line from one nothing wrote. */
    if (item.block) node.dataset.block = String(item.block);
    if (item.ord !== undefined && item.ord !== null) {
      node.dataset.ord = String(item.ord);
    }
    if (type === 'dialogue' || type === 'action') {
      node.addEventListener('click', function () { openLine(item, node); });
    }
    return node;
  }

  /* ---------------------------------------------------- the live line */

  /* Where the burst has got to, in its own seconds. Uses the server's clock
   * rather than ours: `server_ms` is stamped in every poll, so the offset
   * between the two machines cancels instead of accumulating. */
  /* #1278: THE PLAYER THAT IS SOUNDING, or null when none is.
   *
   * The DJ voice rides one of a small set of <audio> elements. The one
   * that matters is the one that is actually playing - unpaused, not
   * ended, and past its first frame. */
  /* #1330: THE PANEL'S PLAYHEAD, ACROSS THE WEBVIEW BOUNDARY.
   *
   * soundingPlayer() below scans THIS document. On the desktop chrome
   * that document holds one <audio> (desktopRadioPlayer); djVoiceAudio0/1
   * are created by the panel, which runs inside <webview id="radioFrame">
   * and is a DOM this one cannot reach. So on the chrome the scan
   * returned null every single time - not intermittently - and #1278's
   * read position, #1287's file guard and #1294's named-row preference
   * were all silently dead there, leaving the view on the clock estimate
   * the whole lot was written to replace.
   *
   * webview-preload.js posts the position out; renderer.js stamps it on
   * arrival and hands back null once it is stale. Stale has to mean
   * absent: a frozen mark reads as a working one, which is worse than
   * falling back to the clock and is how this fault survived so long. */
  /* ============================================ THE CUE MAP, PURELY
   *
   * Handed the admission payload and one reading, this says which
   * occurrence and which line the room is in - or says, by name, that it
   * cannot tell. No DOM, no clock, no fetch, so the cases the audit named
   * can be held to it in node without a browser.
   *
   * The eight answers it can give are the synchronization state. Seven of
   * them are not "on air", and the view SHOWS each of them rather than
   * smoothing them into a stationary cursor. */
  var PineScriptCues = (function () {
    var SYNC = {
      READ: 'read',                /* read off the sound and mapped to a cue */
      GAP: 'read-gap',             /* read, inside the file, between cues */
      UNMAPPED: 'read-unmapped',   /* read, but nothing admitted this file */
      OUTSIDE: 'read-outside',     /* read, admitted file, offset off its map */
      ESTIMATED: 'estimated',      /* a clock, not a playhead */
      HELD: 'held',                /* no evidence; the last trustworthy mark */
      PAUSED: 'paused',
      STALL: 'stalled'             /* read, mapped, and no longer moving */
    };
    var TRUSTED = {};
    TRUSTED[SYNC.READ] = true;
    TRUSTED[SYNC.GAP] = true;

    function key(url) {
      var raw = String(url || '').split('?')[0].replace(/\\/g, '/');
      var parts = raw.split('/');
      return parts[parts.length - 1] || '';
    }

    /* NULL IS NOT ZERO, and this is where that matters most.
     *
     * `Number(null)` is 0 and `isFinite(0)` is true, so an absent playhead
     * arrived here as an offset of exactly zero seconds - which lands
     * inside the first cue of whatever file was named and lights its first
     * line with no evidence whatever behind it. A cue whose window the
     * assembler could not supply did the same in reverse: it became the
     * window 0..0 and sat in the sheet as a line that can never be
     * reached. Absent means absent. */
    function num(value) {
      if (value === null || value === undefined || value === '') return null;
      var got = Number(value);
      return isFinite(got) ? got : null;
    }

    /* The station's payload, turned into something that can be searched by
       the one thing the player can tell us: the name of the file it is
       sounding. Occurrences keep their COMMITTED order; nothing here sorts
       by arrival, by air time or by anything that can be rewritten. */
    function read(payload) {
      var out = {ok: false, generation: null, mode: '', enforceOrder: false,
        reader: null, current: null, order: [], byMedia: {}, count: 0,
        why: 'the station is not sending an admitted cue map'};
      if (!payload || typeof payload !== 'object') return out;
      out.ok = true;
      out.generation = num(payload.generation);
      out.mode = String(payload.mode || '');
      out.enforceOrder = !!payload.enforce_order;
      out.reader = num(payload.reader_position);
      var rows = payload.occurrences;
      if (!rows || !rows.length) {
        out.why = 'the admitted sequence is empty';
        return out;
      }
      var kept = [];
      for (var i = 0; i < rows.length; i += 1) {
        var row = rows[i];
        if (!row || !row.occurrence_id) continue;
        var audio = row.audio || {};
        var occurrence = {
          occurrence_id: String(row.occurrence_id),
          position: num(row.position),
          state: String(row.state || ''),
          outcome: String(row.outcome || ''),
          lane: String(row.lane || ''),
          producer: String(row.producer || ''),
          origin: String(row.origin || ''),
          media: key(audio.media || audio.path || ''),
          sig: String(audio.sig || ''),
          seconds: num(audio.seconds),
          hash: String(audio.hash || ''),
          dispatched_at: num(row.dispatched_at),
          script_revision: String(row.script_revision || ''),
          assembly_id: String(row.assembly_id || ''),
          cue_map_revision: String(row.cue_map_revision || ''),
          performer_session: String(row.performer_session || ''),
          take_id: String(row.take_id || ''),
          cues: []
        };
        var cues = row.cues || [];
        for (var c = 0; c < cues.length; c += 1) {
          var cue = cues[c];
          if (!cue) continue;
          var from = num(cue.start_s), until = num(cue.end_s);
          if (from === null || until === null) continue;
          occurrence.cues.push({
            line_id: String(cue.line_id || cue.occurrence_id || ''),
            position: num(cue.position),
            ordinal: num(cue.ordinal),
            from: from, until: until,
            speechEnd: num(cue.speech_end_s) === null ? until : num(cue.speech_end_s),
            who: String(cue.who || ''), name: String(cue.name || ''),
            kind: String(cue.kind || ''), text: String(cue.text || '')
          });
        }
        kept.push(occurrence);
      }
      kept.sort(function (a, b) {
        return (a.position === null ? 0 : a.position)
          - (b.position === null ? 0 : b.position);
      });
      out.order = kept;
      out.count = kept.length;
      for (var k = 0; k < kept.length; k += 1) {
        var name = kept[k].media;
        if (!name) continue;
        if (!out.byMedia[name]) out.byMedia[name] = [];
        out.byMedia[name].push(kept[k]);
      }
      var now = payload.current;
      if (now && now.occurrence_id) {
        out.current = {occurrence_id: String(now.occurrence_id),
          position: num(now.position), media: key(now.media || ''),
          started_at: num(now.started_at), seconds: num(now.seconds)};
      }
      if (!out.why || out.count) out.why = '';
      return out;
    }

    /* WHICH ONE OF SEVERAL PLAYS OF THE SAME FILE.
     *
     * "A reusable sample's content ID is not its playback occurrence ID.
     *  Playing the same sting twice produces two distinct occurrences in
     *  the script."
     *
     * So a file name alone does not settle it. The occurrence the
     * controller says is in flight wins; failing that, the most recently
     * dispatched; failing that, the first still waiting. Picking the last
     * in the list unconditionally is exactly the bug that lit an old
     * burst's line while a new file was playing. */
    function choose(list, current) {
      if (!list || !list.length) return null;
      var i;
      if (current && current.occurrence_id) {
        for (i = 0; i < list.length; i += 1) {
          if (list[i].occurrence_id === current.occurrence_id) return list[i];
        }
      }
      var best = null;
      for (i = 0; i < list.length; i += 1) {
        if (list[i].state !== 'dispatching') continue;
        if (!best || (list[i].position || 0) > (best.position || 0)) best = list[i];
      }
      if (best) return best;
      for (i = list.length - 1; i >= 0; i -= 1) {
        if (list[i].dispatched_at !== null) return list[i];
      }
      return list[0];
    }

    function blank(sync, why, last) {
      var out = {sync: sync, why: why, trustworthy: !!TRUSTED[sync],
        line_id: '', occurrence_id: '', position: null, from: null,
        until: null, speechEnd: null, index: -1, of: 0, media: '',
        origin: '', carried: false};
      if (last && last.line_id) {
        /* PRESERVE THE LAST TRUSTWORTHY POSITION - and say it is being
           preserved. A mark with no evidence behind it that looks exactly
           like a mark with evidence behind it is the fault, not the cure. */
        out.line_id = last.line_id;
        out.occurrence_id = last.occurrence_id || '';
        out.position = last.position === undefined ? null : last.position;
        out.media = last.media || '';
        out.origin = last.origin || '';
        out.carried = true;
      }
      return out;
    }

    /* `look`:
         file          what the player says it is sounding
         position_s    its OWN offset into that file, never a wall clock
         source        'bridge' | 'local' | 'estimated' | 'unavailable'
         paused        the air is paused
         stalledMs     how long the read position has been motionless
         stallLimitMs  beyond which motionless is a fault (default 8000)
         last          the last trustworthy answer, to carry */
    function locate(map, look) {
      look = look || {};
      var last = look.last || null;
      if (look.paused) return blank(SYNC.PAUSED, 'the air is paused', last);
      var source = String(look.source || 'unavailable');
      var at = num(look.position_s);
      if (source === 'unavailable' || at === null || at < 0) {
        return blank(SYNC.HELD, 'no playback evidence is available', last);
      }
      if (source === 'estimated') {
        return blank(SYNC.ESTIMATED,
          'the position is the station clock, not a playhead', last);
      }
      var file = key(look.file);
      if (!file) {
        return blank(SYNC.UNMAPPED, 'the player did not name its file', last);
      }
      if (!map || !map.ok || !map.count) {
        return blank(SYNC.UNMAPPED,
          'no admitted cue map to read ' + file + ' against', last);
      }
      var list = map.byMedia[file];
      if (!list || !list.length) {
        return blank(SYNC.UNMAPPED,
          'nothing admitted names ' + file, last);
      }
      var occurrence = choose(list, map.current);
      var got = {sync: SYNC.READ, why: '', trustworthy: true, line_id: '',
        occurrence_id: occurrence.occurrence_id, position: occurrence.position,
        from: null, until: null, speechEnd: null, index: -1,
        of: occurrence.cues.length, media: file, origin: occurrence.origin,
        carried: false, at: at};
      for (var i = 0; i < occurrence.cues.length; i += 1) {
        var cue = occurrence.cues[i];
        if (at >= cue.from && at < cue.until) {
          got.line_id = cue.line_id;
          got.position = cue.position === null ? occurrence.position : cue.position;
          got.from = cue.from; got.until = cue.until;
          got.speechEnd = cue.speechEnd;
          got.index = i;
          var stall = num(look.stalledMs);
          var limit = num(look.stallLimitMs);
          if (limit === null) limit = 8000;
          if (stall !== null && stall > limit) {
            got.sync = SYNC.STALL;
            got.trustworthy = false;
            got.why = 'the playhead has not moved for '
              + Math.round(stall / 1000) + 's';
          }
          return got;
        }
      }
      var span = occurrence.seconds;
      if (span !== null && at > span + 1.5) {
        got.sync = SYNC.OUTSIDE;
        got.trustworthy = false;
        got.why = 'the player is past the end of the cue sheet for ' + file;
        return got;
      }
      got.sync = SYNC.GAP;
      got.why = 'inside ' + file + ', between two committed lines';
      return got;
    }

    /* One short sentence for the operator, per state. */
    function say(got) {
      if (!got) return '';
      if (got.sync === SYNC.READ) return 'in step with the sound';
      if (got.sync === SYNC.GAP) return 'in step - a pause between lines';
      if (got.sync === SYNC.PAUSED) return 'air paused';
      if (got.sync === SYNC.STALL) return 'the sound stopped moving';
      if (got.sync === SYNC.OUTSIDE) return 'the sound is off the cue sheet';
      if (got.sync === SYNC.UNMAPPED) return 'sounding something unadmitted';
      if (got.sync === SYNC.ESTIMATED) return 'estimated - no playhead';
      return 'holding the last known line';
    }

    return {SYNC: SYNC, read: read, locate: locate, choose: choose,
            key: key, say: say};
  }());

  function bridgeHead() {
    try { return (root.pinePlayhead && root.pinePlayhead()) || null; }
    catch (e) { return null; }
  }

  /* True when the position is READ off the sound, false when it is
   * estimated. The searches below are only trustworthy in the first
   * case, and they had no way to ask. */
  function headIsRead() {
    return !!(bridgeHead() || soundingPlayer());
  }

  function soundingPlayer() {
    var all = document.querySelectorAll('audio');
    for (var i = 0; i < all.length; i += 1) {
      var a = all[i];
      if (!a || a.paused || a.ended) continue;
      if (!/djVoice/i.test(String(a.id || ''))) continue;
      if (!(Number(a.currentTime) > 0)) continue;
      return a;
    }
    return null;
  }

  /* Where the burst has got to, in its own seconds.
   *
   * #1278: READ, NOT ESTIMATED. This used to be
   * `(Date.now() + skewMs)/1000 - liveStream.at`, and `skewMs` is
   * re-read from `server_ms` on every poll, so it carried the whole
   * delivery latency and all its jitter. Measured against the audio
   * over 308 samples: behind the sound in 81.3% of them, off by more
   * than three seconds in 58.5%, median -2.99s; skewMs spread 16.7s and
   * moved a median of 1.79s between polls; the clock stalled in 61.3%
   * of intervals and then lurched. Against six-second lines that is
   * precisely a mark that skips forward and snaps back - 29.8% of moves
   * were skips and 20.5% were backward, 26 of those 31 with the
   * document completely unchanged.
   *
   * The audio element's currentTime is the SAME coordinate as the rows'
   * from/until - both are offsets into the same welded file - so the
   * position does not have to be estimated. Verified: a burst's maximum
   * `until` 86.86s against the player's own duration 87.76s.
   *
   * The clock remains for the one case with nothing to read: no player
   * sounding. */
  function streamAt() {
    var head = bridgeHead();                              /* #1330 */
    if (head) return Number(head.t) || 0;
    var player = soundingPlayer();
    if (player) return Number(player.currentTime) || 0;
    if (!liveStream || !liveStream.at) return -1;
    return ((Date.now() + skewMs) / 1000) - Number(liveStream.at || 0);
  }

  /* The row the room is hearing. stream_now first - it is exact to the
   * quarter second - and speaking_now only as a fallback, since it is
   * refreshed every four seconds and a four second lag on a four second
   * line points at the wrong one. */
  /* #1287: the basename of the file the player is actually sounding,
     so a row can be asked whether it belongs to it. `from`/`until` are
     offsets into a row's OWN file, and matching them without checking
     the file is how a row 99 seconds away wins - 23 of the 24
     wrong-line samples were exactly that. */
  function soundingFile() {
    var head = bridgeHead();                              /* #1330 */
    if (head) return String(head.file || '');
    var a = soundingPlayer();
    if (!a) return '';
    var src = String(a.currentSrc || a.src || '').split('?')[0];
    return src.split('/').pop() || '';
  }

  function rowFile(row) {
    return String(row.clip_media || row.media || '');
  }

  /* #1294: a row's window under EITHER name.
   *
   * The burst table calls them from/until; the feed calls them
   * clip_from/clip_until, and 168 of 171 feed rows carry only the
   * second pair. within() read only the first, so on the feed every
   * multi-row file collapsed into the lone-row branch and the last row
   * of the file won the whole file. */
  function rowFrom(row) {
    var v = Number(row.from);
    return isFinite(v) ? v : Number(row.clip_from);
  }

  function rowUntil(row) {
    var v = Number(row.until);
    return isFinite(v) ? v : Number(row.clip_until);
  }

  /* THE ADMITTED OCCURRENCE, from the player's own file and offset.
   *
   * This runs BEFORE every reconstruction below it. Where the station has
   * committed a cue sheet for the file that is actually sounding, there is
   * nothing left to infer: the answer is read, not searched for.
   *
   * Where it cannot, it returns null and the older roads have their go -
   * and `syncState` already says which of the eight answers this was, so
   * a fallback is visible rather than silent. */
  function admittedRow() {
    /* NO MAP AT ALL IS NOT A FAULT IN THE SOUND.
     *
     * A station that has not been patched to carry `admission` sends
     * nothing, and treating that as "the player is sounding something
     * unadmitted" would dash an outline round every line of the script,
     * all day, for ever. The file already knows what that costs: "A
     * readout that says the same worried thing all day teaches the
     * operator to ignore it."
     *
     * So this is reported as ESTIMATED - which is exactly what the older
     * roads below are doing - with the reason said once, and the per-line
     * mark is left alone. */
    if (!admitMap || !admitMap.ok || !admitMap.count) {
      if (syncState !== 'estimated') {
        syncState = 'estimated';
        syncSince = Date.now();
      }
      syncWhy = (admitMap && admitMap.why)
        || 'the station is not sending an admitted cue map';
      return null;
    }
    var head = bridgeHead();
    var player = head ? null : soundingPlayer();
    var source = head ? 'bridge' : (player ? 'local' : 'unavailable');
    var at = null, file = '';
    if (head) { at = Number(head.t); file = String(head.file || ''); }
    else if (player) {
      at = Number(player.currentTime);
      file = String(player.currentSrc || player.src || '');
    } else if (liveStream && liveStream.at) {
      source = 'estimated';
      at = ((Date.now() + skewMs) / 1000) - Number(liveStream.at || 0);
    }
    var moved = 0;
    if (source === 'bridge' || source === 'local') {
      var now = Date.now();
      if (headWas < 0 || Math.abs(Number(at) - headWas) > 0.05) {
        headWas = Number(at); headMovedAt = now;
      }
      moved = headMovedAt ? now - headMovedAt : 0;
    } else { headWas = -1; headMovedAt = 0; }
    var got = PineScriptCues.locate(admitMap, {
      file: file, position_s: at, source: source, paused: stationPaused,
      stalledMs: moved, stallLimitMs: STALL_MS, last: lastGood});
    if (syncState !== got.sync) { syncState = got.sync; syncSince = Date.now(); }
    syncWhy = got.why || PineScriptCues.say(got);
    if (got.trustworthy && got.line_id) {
      lastGood = {line_id: got.line_id, occurrence_id: got.occurrence_id,
        position: got.position, media: got.media, origin: got.origin,
        at: Date.now()};
    }
    if (!got.line_id) return null;
    return {id: got.line_id,
      from: got.carried ? 0 : Number(got.from || 0),
      until: got.carried ? 0 : Number(got.until || 0),
      at: got.carried ? 0 : Number(got.at || 0),
      index: got.index, of: got.of,
      occurrence_id: got.occurrence_id, position: got.position,
      sync: got.sync, carried: !!got.carried, admitted: true};
  }

  function activeRow() {
    /* #1336 / the sequential-playout audit: the ADMITTED map first. Every
       road below this line reconstructs a position from something that can
       be rewritten - estimates, feed rows, a four-second poll. The cue
       sheet the controller committed cannot be. */
    var admitted = admittedRow();
    if (admitted) return admitted;
    var t = streamAt();    var rows = (liveStream && liveStream.rows) || [];
    var file = soundingFile();
    /* #1330: A BURST THAT HAS RUN OUT IS NOT A TABLE TO SEARCH.
     *
     * With an estimated position there is no filename to hold a row to,
     * so #1287's guard cannot fire and a finished burst's windows still
     * bracket the estimate - lighting a row that stopped sounding some
     * time ago and holding it lit. #1294 measured that shape: 12 of 19
     * wrong samples were more than two seconds in.
     *
     * The station's own reader already refuses this - it accepts an
     * offset only inside [0, length + 4] before falling back to
     * speaking_now - and the view should refuse it on the same terms.
     * Where the position is READ this cannot arise, because the file
     * guard settles it; this is only for where we are guessing. */
    if (!headIsRead() && liveStream && liveStream.at) {
      var span = Number(liveStream.length || 0) + 4;
      if (!(t >= 0 && t <= span)) {
        return (speakingNow && speakingNow.id)
          ? {id: String(speakingNow.id), from: 0, until: 0, at: t,
             index: -1, of: rows.length}
          : null;
      }
    }
    function within(list, of) {
      var lone = null, loneAt = -1;
      for (var i = 0; i < list.length; i += 1) {
        var row = list[i];
        var mine = rowFile(row);
        /* #1287: only rows of the file that is sounding. */
        if (file && mine && mine !== file) continue;
        var from = rowFrom(row), until = rowUntil(row);
        if (!isFinite(from) || !isFinite(until)) {
          /* #1287: A ROW THAT IS THE WHOLE FILE HAS NO WINDOW.
           * Measured: 0 of 25 `interject` rows carry from/until - they
           * are a clip of one line, so there is nothing to offset
           * into - and interject was lit correctly 0 of 37 times. My
           * #1278 note claimed the wider search would catch them; it
           * could not, because the field its loop needs does not
           * exist on them. If the sounding file IS this row's file,
           * this row is the line. */
          if (file && mine === file) { lone = row; loneAt = i; }
          continue;
        }
        if (t >= from && t < until) {
          return {id: String(row.id || ''), from: from, until: until,
            at: t, index: i, of: of};
        }
      }
      if (lone) {
        return {id: String(lone.id || ''), from: 0,
          until: Number(lone.seconds) || 0, at: t, index: loneAt, of: of};
      }
      return null;
    }
    if (t >= 0) {
      /* #1294: WHICHEVER TABLE CAN BE CHECKED AGAINST THE SOUND.
       *
       * liveStream.rows carry {id, from, until} and no media - probed
       * on the tablet, that is the whole of streamKeys - so #1287's
       * file guard above can never fire for them. When the sounding
       * file moves on and stream_now has not, the old burst's window
       * brackets the new file's currentTime and lights a row that is
       * not being said, for the length of the clip: 12 of the 19 wrong
       * samples measured were more than two seconds in, which is what
       * separates this from the mark merely lagging.
       *
       * The feed's rows carry clip_media, so when we know the name of
       * what is sounding they are the table that can be held to it.
       * Where the two describe the same file they agree to three
       * decimals, so this is a change of ORDER, not of arithmetic. */
      var fed = [];
      try { fed = (root.PineStationFeed.rows() || []); } catch (e1) { fed = []; }
      if (file && fed.length) {
        var named = within(fed, fed.length);
        if (named) return named;
      }
      var seat = within(rows, rows.length);
      if (seat) return seat;
      /* #1278: A CLIP OF ITS OWN IS STILL A LINE OF THE SCRIPT.
       *
       * This searched `liveStream.rows` and nothing else - one burst.
       * Anything that airs as its own single-row clip is not in that
       * list, so no window contained the position and the mark was
       * cleared. Measured over 827 sounding samples, the split was
       * perfect: `interject` lit correctly 0 times of 151, and
       * `station_id` 0 of 17, while every kind riding the welded burst
       * was lit sometimes. That is 20% of sounding samples guaranteed
       * wrong - and in 77% of the dark samples the line was already on
       * the page, so it was never the screenplay being stale.
       *
       * The feed's full row list is where those clips live. */
      var all = fed;
      if (!file && all.length && all !== rows) {
        var loose = within(all, all.length);
        if (loose) return loose;
      }
    }
    if (speakingNow && speakingNow.id) {
      return {id: String(speakingNow.id), from: 0, until: 0, at: t,
        index: -1, of: rows.length};
    }
    return null;
  }

  /* PULL THE ARITHMETIC BACK ONTO THE STATION'S TRUTH.
   *
   * Measured over 30 samples: the interpolation agreed with the station on
   * 28 and disagreed on 2, both at a burst boundary, by a second or so.
   * That is drift - our clock and the station's playout are not the same
   * clock, and `at` is the moment the burst was HANDED to the player, not
   * the moment sound left it.
   *
   * So `speaking_now` is used as a reference mark rather than a fallback.
   * When the poll says a different row is in the room, the offset is
   * nudged - not snapped - until the two agree. Nudging matters: a snap on
   * a four-second-old reading would jerk the highlight backwards every
   * poll, which looks worse than the drift it fixes. */
  function correct() {
    if (!speakingNow || !speakingNow.id || !liveStream) return;
    var rows = liveStream.rows || [];
    var want = String(speakingNow.id);
    var seat = -1;
    for (var i = 0; i < rows.length; i += 1) {
      if (String(rows[i].id || '') === want) { seat = i; break; }
    }
    if (seat < 0) return;
    var row = rows[seat];
    var t = streamAt();
    if (t < 0) return;
    if (t >= Number(row.from || 0) && t < Number(row.until || 0)) return;  /* agreed */
    /* How far off we are from the middle of the row the station names. */
    var aim = (Number(row.from || 0) + Number(row.until || 0)) / 2;
    var off = (aim - t) * 1000;
    if (Math.abs(off) > 30000) return;   /* a different burst entirely */
    /* Held SEPARATELY from the clock skew, which is re-read from
     * `server_ms` on every poll and would otherwise wipe this out four
     * seconds after it was learned. */
    /* #1267: AND IT IS NO LONGER CARRIED. Measured on the tablet
     * against the station, 21 samples where the room was saying a
     * named line: the highlight was the right line in 16, and in the
     * other 5 it was BEHIND - one entry twice, two once, three twice -
     * and never once ahead. A one-directional error is a bias, not
     * drift.
     *
     * This is why. `driftMs` starts at 0 on every new burst (the
     * subscriber resets it whenever `liveStream.at` moves), is only
     * touched when the interpolated position falls OUTSIDE the row the
     * station names, and then closes just HALF the gap. So each burst
     * began with the error back at zero and converged in halves, which
     * on lines of five to seven seconds means it is still catching up
     * when the burst ends.
     *
     * The comment above justified it by 2 disagreements in 30 samples
     * at burst boundaries. It is now costing 5 in 21 across the whole
     * line - the cure was worse than the fault.
     *
     * The station's own feed has no such term: sampler-feed.js reads
     * `Date.now() + skew` and picks the row whose window contains it,
     * full stop. With this gone the two arithmetics are identical, and
     * the page agrees with the feed by construction rather than by
     * chasing it. `off` is still measured and reported below, because a
     * number worth fixing is worth watching.
     */
    lastOffMs = off;
  }

  /* ONE line carries the mark. The class is removed from whatever had it
   * before rather than from everything, so a 283-element script does not
   * get walked four times a second. */
  function markNow(id) {
    if (id === nowLineId) return;
    /* #1263: CLEAR EVERY MARK, not the one we remember.
     *
     * "it's highlighting multiple lines at the same time when it's
     *  broadcasting. When really I need it to highlight a single line."
     *
     * This used to un-mark only the node matching `nowLineId`, so any
     * path that cleared that variable WITHOUT repainting left its line
     * lit for ever and the next tick lit another beside it. There are
     * three such paths - the live chip, and the two view gestures added
     * in #1260 - and each tap stranded one more highlight.
     *
     * Only one line is ever being said, so only one may ever be marked.
     * Asking the document rather than trusting a remembered id makes
     * that true by construction, whatever else clears what. */
    var lit = document.querySelectorAll('.sp-el.sp-now');
    for (var i = 0; i < lit.length; i += 1) lit[i].classList.remove('sp-now');
    /* #1270: A MARK THAT DID NOT HAPPEN IS NOT REMEMBERED.
     *
     * This used to write `nowLineId = id` and only THEN look for the
     * node, returning quietly when the line was not on the page yet -
     * which happens constantly, because the station moves to a line
     * the moment it airs and the screenplay is only re-read every
     * twenty seconds. The id was now recorded as marked when nothing
     * had been marked, so every later tick hit `id === nowLineId` at
     * the top and returned. The highlight then sat on the PREVIOUS
     * line until the station moved again - which is the one-to-three
     * entry lag measured on the tablet, always behind and never ahead.
     *
     * It was masked until now: paintScript cleared nowLineId on every
     * repaint, so the mark was forced to re-seat three times a minute.
     * #1269 stopped rebuilding the page and the mask went with it.
     *
     * So the node is found FIRST. If the line has not arrived yet the
     * id is left unset and the next tick - a quarter of a second - has
     * another go, which is also what makes the view seat itself on
     * mount instead of sitting at the top of a 72,000px script.
     */
    var node = id
      ? document.querySelector('.sp-el[data-line="' + id + '"]')
      : null;
    if (id && !node) {
      /* #1271: AND THE PAGE GOES AND GETS IT.
       *
       * The line the room is saying can only be marked if it is ON the
       * page, and the script is re-read every twenty seconds - so a
       * line that aired since the last read waits, and the highlight
       * sits on the one before it. Measured on the tablet: correct
       * within 3 seconds at some changes and 7 at others, always one
       * line behind, always catching up in the end. The wait was the
       * whole of it.
       *
       * Being unable to find the line IS the signal that the script is
       * stale, so it asks for a fresh one there and then, at most once
       * every three seconds. Nothing else in the view has to know. */
      nowLineId = '';
      var t = Date.now();
      if (t - chasedAt > 3000) { chasedAt = t; loadScreenplay(true); }
      return;
    }
    nowLineId = id || '';
    if (!node) return;
    node.classList.add('sp-now');
    segFollow(node.getAttribute('data-seg') || '');          /* #1285 */
    if (follow) {
      /* Centred, not merely visible: the operator is reading the
       * conversation, and the next line wants to be under it.
       *
       * THE GUARD IS THE WHOLE FIX. Measured: the highlight was on screen
       * in 0 of 7 talking samples, because a smooth scroll fires scroll
       * events all the way down, the handler below read "the line is not
       * visible yet" from one of them and switched following OFF - the
       * auto-scroll cancelled itself on its first frame, every time. */
      /* #1282: MOVE ONLY IF IT HAS TO, AND DO NOT CANCEL YOURSELF.
       *
       * `block:'center'` re-centred on every line change - about ten
       * full animations a minute at a 6.4s median dwell, each one a
       * chance for the page to move under a finger. `nearest` moves
       * only when the line is actually outside the pane, and
       * `.sp-now`'s scroll-margin keeps it off the edge when it does.
       *
       * And the 900ms guard was a fixed window against a scroll whose
       * duration grows with distance - 21.9% of movements were still
       * running two samples later. When it expired mid-flight the
       * animation's own scroll events reached the handler, which read
       * geometry that had not settled and switched following off. The
       * scroll cancelled itself, which is the very fault the guard
       * exists to prevent. `scrollend` says when it is really over. */
      /* #1330 lives in moveScript() now, with the other three movers of
         this pane: the backstop, the `scrollend` early clear and the box
         that actually scrolls are declared in ONE place. */
      moveScript('follow', function () {
        try { node.scrollIntoView({block: 'nearest', behavior: 'smooth'}); }
        catch (err) { node.scrollIntoView(false); }
      });
    }
  }

  function seconds(v) {
    if (!isFinite(v)) return '—';
    return (v < 10 ? v.toFixed(1) : String(Math.round(v))) + 's';
  }

  /* WHY IT IS NOT SPEAKING YET, in one line.
   *
   * "I want to be able to see what is causing it to delay or what is
   * happening with its processing."
   *
   * Everything below already rides in the feed poll this view subscribes
   * to, so the readout costs no request. The order is deliberate: what the
   * room can hear beats what the desk is doing, and a named blocker beats
   * a count. */
  function status() {
    var row = activeRow();
    if (stationPaused) return {state: 'paused', text: 'air paused — nothing is going out'};

    /* A CARRIED MARK IS NOT "ON AIR". It is the last line this view could
       prove, held up while the evidence is missing, and saying "4.2s left"
       over it would be inventing a countdown for audio nobody can see. */
    if (row && row.carried) {
      return {state: 'wait', text: 'holding the last read line — ' + syncWhy};
    }

    if (row && row.until > row.from) {
      var left = row.until - row.at;
      var node = document.querySelector('.sp-el[data-line="' + row.id + '"]');
      var who = '';
      if (node) {
        var prev = node.previousElementSibling;
        if (prev && prev.classList.contains('sp-character')) who = prev.textContent + ' · ';
      }
      var tail = '';
      if (row.index >= 0 && row.of) {
        var rest = row.of - row.index - 1;
        tail = rest > 0 ? ' · ' + rest + ' more in this burst' : ' · last of the burst';
      }
      return {state: 'air', text: who + 'on air · ' + seconds(Math.max(0, left))
        + ' left of ' + seconds(row.until - row.from) + tail};
    }

    if (row && row.id) return {state: 'air', text: 'on air'};

    /* Nothing in the room. Say what the booth is doing about it. */
    var f = flow || {};
    if (f.render_waiting) {
      return {state: 'work', text: 'written, waiting on the voice — '
        + f.render_waiting + ' line' + (f.render_waiting === 1 ? '' : 's')
        + ' in the render queue'};
    }
    if (f.delivery_waiting) {
      return {state: 'work', text: 'voiced, waiting to be handed to air — '
        + f.delivery_waiting + ' waiting'};
    }
    if (f.writing) return {state: 'work', text: 'the room is writing the next round'};
    if (f.ad_cover) return {state: 'work', text: 'an ad is covering the gap'};

    /* A BLOCKER IS ONLY A BLOCKER IF IT BLOCKS.
     *
     * `blockers` carries all-clears too - measured live, the only entry was
     * "continuity reserve is healthy" - and `tint_hold` is TRUE at rest, so
     * an earlier draft of this line read "holding for the tint lane to
     * finish a pass" permanently, over ordinary music. A readout that says
     * the same worried thing all day teaches the operator to ignore it. */
    var blockers = (f.blockers || []).filter(function (b) {
      var t = String(b || '').toLowerCase();
      return t && t.indexOf('healthy') < 0 && t.indexOf('is fine') < 0
        && t.indexOf('no shortage') < 0 && t.indexOf(' ok') < 0;
    });
    if (blockers.length) return {state: 'wait', text: 'held: ' + blockers[0]};

    /* Nothing is wrong: it is a music bed, and the only question worth
     * answering is when the pair are back. */
    var rest = 'music';
    if (typeof f.talk_next_in === 'number' && f.talk_next_in > 0) {
      rest += ' — the pair are back in ' + seconds(f.talk_next_in);
    } else if (typeof f.ready === 'number' && typeof f.target === 'number') {
      rest += ' — ' + f.ready + ' rounds banked against a target of ' + f.target;
    }
    return {state: 'idle', text: rest};
  }

  /* WHAT THE MARK IS STANDING ON, in two words and a reason.
   *
   * The audit's warning, kept literally: "Preserve the last trustworthy
   * position when playback evidence is unavailable and expose the
   * synchronization state. Merely preventing a backward visual movement
   * would hide an audio fault." So a carried mark is drawn differently
   * from a live one and says how old it is. */
  function paintSync(row) {
    var node = el('spSync');
    if (!node) return;
    var carried = !!(row && row.carried);
    var state = String(syncState || 'held');
    var name = PineScriptCues.say({sync: state});
    var why = String(syncWhy || '');
    if (carried && lastGood && lastGood.at) {
      var age = Math.max(0, Math.round((Date.now() - lastGood.at) / 1000));
      why = (why ? why + ' - ' : '') + 'holding the last read line for ' + age + 's';
    }
    if (admitMap && admitMap.ok && !admitMap.count && state !== 'paused') {
      why = why || admitMap.why;
    }
    if (node.dataset.sync !== state) node.dataset.sync = state;
    node.classList.toggle('sp-sync-carried', carried);
    /* AND ON THE MARK ITSELF. A highlight held up without evidence must
       not be drawn identically to one the sound is standing behind - that
       is precisely the "hide an audio fault" the audit refuses. */
    try {
      var mapped = !!(admitMap && admitMap.ok && admitMap.count);
      if (host) {
        host.classList.toggle('sp-unsynced',
          mapped && !(state === 'read' || state === 'read-gap'));
      }
    } catch (err) { /* the strip still says it */ }
    var b = node.firstChild, i = node.lastChild;
    if (b && b.__text !== name) { b.__text = name; b.textContent = name; }
    if (i && i.__text !== why) { i.__text = why; i.textContent = why; }
  }

  function paintStatus() {
    var line = el('spNow');
    if (!line) return;
    var got = status();
    if (line.dataset.state !== got.state) line.dataset.state = got.state;
    if (line.__text !== got.text) { line.__text = got.text; line.textContent = got.text; }
  }

  /* The 250 ms heartbeat: move the mark, move the readout. Nothing here
   * touches the network. */
  /* #1295: HOW MUCH OF THIS CLIP IS LEFT, drawn on the line itself.
   *
   * Set as a custom property and an attribute, never as a child node:
   * the reconciler re-dresses a changed line with textContent, so a
   * child span would be wiped every repaint. The CSS paints the bar
   * off --sp-run and the countdown off data-left.
   *
   * A row with no usable window (an interject is a clip of one line
   * and carries neither end) gets no bar rather than a wrong one. */
  var runNode = null;

  function markRun(row) {
    var node = (row && row.id)
      ? document.querySelector('.sp-el[data-line="' + row.id + '"]')
      : null;
    if (runNode && runNode !== node) {
      runNode.style.removeProperty('--sp-run');
      runNode.removeAttribute('data-left');
    }
    runNode = node;
    if (!node || !row) return;
    var span = Number(row.until) - Number(row.from);
    var gone = Number(row.at) - Number(row.from);
    if (!isFinite(span) || span <= 0 || !isFinite(gone)) {
      node.style.removeProperty('--sp-run');
      node.removeAttribute('data-left');
      return;
    }
    var run = Math.max(0, Math.min(1, gone / span));
    node.style.setProperty('--sp-run', (run * 100).toFixed(1) + '%');
    var left = Math.max(0, Math.round(span - gone));
    node.setAttribute('data-left', left >= 60
      ? (Math.floor(left / 60) + ':' + ('0' + (left % 60)).slice(-2))
      : (left + 's'));
  }

  function tick() {
    var row = activeRow();
    /* The bounded ring of what the mark did and why - the incident report
       carries it, so a backward movement can be told apart from a document
       reflow and from a gap in the evidence. */
    var seen = syncRing[syncRing.length - 1];
    var mine = {at: Date.now(), sync: syncState,
      line: row ? String(row.id || '') : '',
      occurrence: row ? String(row.occurrence_id || '') : '',
      position: row && row.position !== undefined ? row.position : null,
      carried: !!(row && row.carried)};
    if (!seen || seen.sync !== mine.sync || seen.line !== mine.line
        || seen.occurrence !== mine.occurrence) {
      syncRing.push(mine);
      if (syncRing.length > SYNC_RING_MAX) syncRing.shift();
    }
    markNow(row ? row.id : '');
    markRun(row);                                            /* #1295 */
    paintSaying(row);                                        /* #1298 */
    markFeedLive(row ? row.id : '');            /* #1279 */
    /* #1286: say when the room is quiet, instead of leaving a page full
       of `pending` and `tinted` marks to be read as though one of them
       were live. */
    try {
      /* #1294: the PLAYER, not the row. This read activeRow(), which
         falls back to speaking_now, so quiet stayed off for a second
         or two after a clip ended - 22 of 348 silent samples. What
         "quiet" means is that nothing is sounding, and there is an
         element that knows. */
      host.classList.toggle('sp-quiet', !soundingPlayer() && !(row && row.id));
    } catch (err) { /* the mark still stands on its own */ }
    paintStatus();
    paintSync(row);
  }

  /* #1303b: the row the sampler's own sourceFor() expects. A clip line
     carries its url and is taken exactly; a spoken line carries its id
     and the clip route cuts it out of the welded round. */
  function samplerRow(item) {
    if (!item) return null;
    var id = String(item.line || item.id || '');
    var url = String(item.clip || '');
    if (!id && !url) return null;
    var row = {id: id, text: String(item.text || ''),
               who: String(item.name || item.who || '')};
    if (url) { row.url = url; row.sfx = true; }
    return row;
  }

  function padRow(item) {
    var row = samplerRow(item);
    if (!row) return null;
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== 'function') return null;
    try {
      if (typeof sampler.takeable === 'function' && !sampler.takeable(row)) {
        return null;                 /* nothing behind it: no button */
      }
    } catch (err) { return null; }
    var btn = make('button', 'sp-btn wide', 'Send to a sampler pad');
    btn.title = 'Put this on the first free pad of the sampler';
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = 'taking it...';
      Promise.resolve(sampler.grab(row)).then(function (got) {
        var ok = got && got.ok;
        btn.textContent = ok ? 'on a pad' : ((got && got.why) || 'it refused');
        btn.disabled = !!ok;
        if (!ok) setTimeout(function () {
          btn.textContent = 'Send to a sampler pad';
          btn.disabled = false;
        }, 2600);
      }).catch(function (err) {
        btn.textContent = 'it refused: ' + (err && err.message);
        setTimeout(function () {
          btn.textContent = 'Send to a sampler pad';
          btn.disabled = false;
        }, 2600);
      });
    });
    return btn;
  }

  function jumpToLine(id) {
    if (!id) return;
    var node = document.querySelector('.sp-el[data-line="' + id + '"]');
    if (!node) return;
    moveScript('jump', function () {
      node.scrollIntoView({block: 'center'});
    });
    node.classList.add('flash');
    setTimeout(function () { node.classList.remove('flash'); }, 1200);
  }

  /* Tap a line: what it is, and what can be done with it. */
  function openLine(item, node) {
    pinned = item;
    document.querySelectorAll('.sp-el.picked').forEach(function (n) {
      n.classList.remove('picked');
    });
    node.classList.add('picked');
    var box = el('spDetail');
    if (!box) return;
    box.hidden = false;
    box.replaceChildren();

    box.appendChild(make('b', 'sp-detail-who', item.name || item.who || item.tag || 'the station'));
    box.appendChild(make('p', 'sp-detail-text', item.text || ''));

    var facts = [];
    if (item.round) facts.push(item.round);
    if (item.kind) facts.push(item.kind);
    if (item.engine) facts.push(item.engine);
    if (item.seconds) facts.push(Number(item.seconds).toFixed(1) + 's');
    if (item.tinted) facts.push('tinted');
    if (item.aired) facts.push(item.aired === 'stream' ? 'aired' : item.aired);
    box.appendChild(make('i', 'sp-detail-facts', facts.join('  ·  ')));

    var note = make('textarea', 'sp-note');
    note.placeholder = 'A note, or how this should have been said...';
    box.appendChild(note);

    var row = make('div', 'sp-detail-row');

    var keep = make('button', 'sp-btn wide', 'Keep the note');
    keep.addEventListener('click', function () {
      sendNote(item, note.value, keep);
    });
    row.appendChild(keep);

    /* #1303b: ASSIGN IT TO A PAD.
     *
     * Through PineSampler.grab, the published seam - whose own comment
     * says it exists so "another view can GREY ITS OWN BUTTON with the
     * same answer this one uses, rather than guessing from `aired` -
     * which is the exact mistake that once offered 7 of ~220 takeable
     * moments". So this asks takeable() and simply is not there when
     * there is nothing behind the line. */
    var take = padRow(item);
    if (take) row.appendChild(take);

    var back = make('button', 'sp-btn wide', 'Send to the recording room');
    /* Honest about the limit rather than failing in the operator's hand:
     * the return path needs a round that is still on the shelf. */
    back.title = 'Asks the writers to do this line again, with your note '
      + 'above it. Only possible while the round it belongs to is still on '
      + 'the shelf.';
    back.addEventListener('click', function () { sendBack(item, note.value, back); });
    row.appendChild(back);

    var clip = make('button', 'sp-btn wide', 'Hear it');
    clip.disabled = !item.clip;
    clip.addEventListener('click', function () { hear(item, clip); });
    row.appendChild(clip);

    box.appendChild(row);
    var close = make('button', 'sp-detail-close', '✕');
    close.addEventListener('click', function () { box.hidden = true; });
    box.appendChild(close);
  }

  function sendNote(item, text, button) {
    if (!text.trim()) { button.textContent = 'write something first'; return; }
    var was = button.textContent;
    button.textContent = 'keeping...';
    api().post('/api/screenplay/'                      /* #1268 */
      + encodeURIComponent((item && item.hour) || hourKey) + '/note', {
      kind: 'line', target_id: item.line || item.id, text: text,
      who: 'operator'
    }).then(function () {
      button.textContent = 'kept';
      setTimeout(function () { button.textContent = was; }, 1600);
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 36);
    });
  }

  function sendBack(item, text, button) {
    var was = button.textContent;
    button.textContent = 'sending...';
    /* The note first, so the request and the reason are stored together
     * even if the rewrite is refused. */
    api().post('/api/screenplay/'                      /* #1268 */
      + encodeURIComponent((item && item.hour) || hourKey) + '/note', {
      kind: 'rework', target_id: item.line || item.id,
      text: text || 'Do this one again.', who: 'operator'
    }).then(function () {
      button.textContent = 'asked';
      setTimeout(function () { button.textContent = was; }, 1800);
    }, function (err) {
      button.textContent = String((err && err.message) || err).slice(0, 36);
    });
  }

  function hear(item, button) {
    if (!item.clip) return;
    var was = button.textContent;
    button.textContent = 'fetching...';
    var audio = new Audio(item.clip);
    audio.play().then(function () { button.textContent = was; },
      function () { button.textContent = 'would not play'; });
  }

  /* ------------------------------------------------------------- build */

  function build(node) {
    host = node;
    host.classList.add(HOST_CLASS);
    host.replaceChildren();

    var left = make('div', 'sp-left');
    left.appendChild(buildBar());            /* 1 2 3 */
    var treeRow = make('div', 'sp-treerow');
    treeRow.appendChild(buildTree());        /* 4 */
    treeRow.appendChild(buildSaying());      /* #1298 */
    left.appendChild(treeRow);
    left.appendChild(buildPanel());
    left.appendChild(buildPlayer());         /* 5 */
    var feedHead = make('div', 'sp-feedhead');
    feedHead.appendChild(make('b', '', 'Feed'));
    feedHead.appendChild(make('i', 'sp-feedwhy', 'everything the station is doing'));
    left.appendChild(feedHead);
    var feed = make('div', 'sp-feed');       /* 6 */
    feed.id = 'spFeed';
    feed.addEventListener('scroll', function () {
      feedStick = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 30;
    });
    left.appendChild(feed);

    var right = make('div', 'sp-right');     /* 7 */
    var head = make('div', 'sp-scripthead');
    head.id = 'spScriptName';
    head.appendChild(make('b', '', 'The script'));
    head.appendChild(make('i', 'sp-scriptwhy', ''));
    head.lastChild.id = 'spScriptHead';
    /* #1164: "I want to be able to tap and hold on the name of the
       script as being run for that particular session and I want a
       drop-down menu that comes down". The same holdOpen() the SFX
       button, the caution button and the report icon are already on -
       one hold gesture in this file, not four of them drifting apart.
       A short tap never opens it; a short tap while it IS open puts it
       away, which is the toggle a menu on a name ought to have. */
    head.setAttribute('role', 'button');
    head.setAttribute('tabindex', '0');
    head.setAttribute('aria-haspopup', 'menu');
    head.setAttribute('aria-expanded', 'false');
    head.title = 'Hold this name (or right-click it): complain, mark an issue, report a missing segment';
    holdOpen(head, function () { headerOpen(head); });
    head.addEventListener('click', function () {
      if (head.pineHeld) return;              /* the hold has just answered */
      if (el(HEADER_MENU_ID)) headerClose();
    });
    /* At the desk there is a keyboard, and a role="button" that cannot
       be worked from it is a button in name only. */
    head.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
      ev.preventDefault();
      if (el(HEADER_MENU_ID)) headerClose();
      else headerOpen(head);
    });
    right.appendChild(head);
    /* One line, console-shaped, directly under the heading: what is
       happening with the line that is being said. */
    var now = make('div', 'sp-now-line');
    now.id = 'spNow';
    now.dataset.state = 'idle';
    right.appendChild(now);
    /* THE SYNCHRONIZATION STATE, said out loud.
       A held mark and a live mark must not look the same. */
    var sync = make('div', 'sp-sync');
    sync.id = 'spSync';
    sync.dataset.sync = 'held';
    sync.appendChild(make('b', 'sp-sync-name', ''));
    sync.appendChild(make('i', 'sp-sync-why', ''));
    right.appendChild(sync);

    var script = make('div', 'sp-script');
    script.id = 'spScript';
    script.addEventListener('scroll', function () {
      if (Date.now() < selfScrollUntil) return;   /* our own scroll, in flight */
      stick = script.scrollTop + script.clientHeight >= script.scrollHeight - 40;
      /* Scrolling by hand means "let me read"; following would yank the
         page back every quarter second. Tapping the readout resumes it. */
      /* #1282: TWICE, NOT ONCE. Following used to end the first time
         the lit node looked off-screen, which a long smooth scroll
         guarantees mid-flight. Two consecutive readings means a single
         unsettled frame cannot end it - but a real hand-scroll, which
         produces many, still does. */
      var node = nowLineId
        && document.querySelector('.sp-el[data-line="' + nowLineId + '"]');
      if (node) {
        var box = script.getBoundingClientRect();
        var seat = node.getBoundingClientRect();
        var here = seat.bottom > box.top && seat.top < box.bottom;
        if (here) { adrift = 0; follow = true; }
        else if ((adrift += 1) >= 2) { follow = false; }
      } else if (nowLineId === '') {
        /* #1270 leaves this empty while the line has not arrived. The
           old code reconsidered nothing here, so scrolling away during
           that window did not count as "let me read" and the page
           yanked back the moment the line landed. */
        if ((adrift += 1) >= 2) { follow = false; }
      }
      var chip = el('spNow');
      if (chip) chip.classList.toggle('adrift', !follow);
    });
    right.appendChild(script);

    /* #1260: DOUBLE-TAP THE SCRIPT TO READ IT PROPERLY.
     *
     * "If I double tap the script page, I want to also have the script
     *  show up in this view." - the full-page screenplay the desktop
     *  shows, on the glass, instead of a column beside the player.
     *
     * A class on the host, so the layout is CSS's business and nothing
     * here has to know about the other six regions. dblclick fires on
     * this WebView; the manual two-tap timer underneath it is for the
     * cases where a fast double touch is delivered as two taps and the
     * synthetic dblclick never arrives. */
    /* #1272: A SINGLE TAP DOES NOTHING, AND THAT IS THE POINT.
     *
     * "script view should only go fullscreen if i double tap the blank
     *  area of the script view. If i tripple tap it, show it with the
     *  colorings and display style of a script document so it can be
     *  easier on the eyes."
     *
     * The operator works this view with a thumb while the station is
     * playing - listening, reading, and grabbing clips onto sampler
     * pads - so a single stray tap on the margin must not throw the
     * pane into full screen underneath them. Nothing happens until a
     * second tap says it was meant.
     *
     *     two taps    full screen, on and off
     *     three taps  the script-document setting, on and off
     *
     * The count is held for one window after the LAST tap rather than
     * the first, so a deliberate triple is never cut short by the
     * double firing on its way past. */
    var tapTimer = null;
    var taps = 0;
    var TAP_WINDOW = 300;
    var PAPER = 'sp-look-paper';

    function reseat() {
      /* The pane changed shape, so the line that was centred no longer
         is. Re-seat rather than leave the reader stranded. */
      follow = true;
      nowLineId = '';
      try { tick(); } catch (e) { /* the change matters more */ }
    }
    function bigToggle() { host.classList.toggle('sp-big'); reseat(); }
    /* #1272: the script-document setting - paper, Courier, the standard
       measures, and each element coloured for what it IS. One setting
       that goes on and off, not a cycle: the operator asked for a look,
       not a carousel. */
    function paperToggle() { host.classList.toggle(PAPER); reseat(); }

    /* A tap on a LINE still opens that line - that is what the detail
     * panel is for and it predates this. These gestures belong to the
     * PANE: the margins, the gutters, the space between the speeches. */
    function onTap(ev) {
      var t = ev && ev.target;
      if (t && t.closest && t.closest('button, input, a, .sp-detail')) return;
      /* THE BLANK AREA ONLY. A tap on a line belongs to that line - it
         opens the detail panel, which is how a clip is inspected and
         sent to a pad - and must never be read as part of a gesture. */
      if (t && t !== script && t.closest && t.closest('.sp-el')) return;
      taps += 1;
      if (tapTimer) clearTimeout(tapTimer);
      tapTimer = setTimeout(function () {
        var count = taps;
        tapTimer = null;
        taps = 0;
        if (count === 2) bigToggle();
        else if (count >= 3) paperToggle();
        /* one tap: nothing at all */
      }, TAP_WINDOW);
    }
    script.addEventListener('click', onTap);

    /* --- THE CRAWL -------------------------------------------------
     *
     * "I want an icon that allows me to start it auto scrolling, but by
     *  default I want it to automatically be on the area that's actively
     *  airing. However, I do want a slider that allows me to choose the
     *  speed."
     *
     * Two different ways to move, and they must not fight: FOLLOW keeps
     * the live line in view and is the default; CRAWL walks the page at
     * a chosen rate for reading ahead. Starting the crawl stands follow
     * down, and tapping the live chip (which already exists) stands the
     * crawl down and goes back to the air. */
    var crawl = false;
    var crawlPx = 18;            /* pixels per second at the middle */
    var crawlLast = 0;
    var crawlOwed = 0;

    var tools = make('div', 'sp-crawl');
    var run = make('button', 'sp-crawl-go');
    run.type = 'button';
    run.textContent = '▶';           /* play; becomes pause when on */
    run.title = 'Auto-scroll the script';
    var rate = document.createElement('input');
    rate.type = 'range';
    rate.min = '1'; rate.max = '100'; rate.value = '30';
    rate.className = 'sp-crawl-rate';
    rate.title = 'How fast it scrolls';
    tools.appendChild(run);
    tools.appendChild(rate);
    /* #1289: the hour ahead, and which way to show it. */
    var ahead = make('button', 'sp-crawl-go sp-planway');
    ahead.type = 'button';
    ahead.textContent = '⎘';
    ahead.title = 'The hour ahead: below the script, or beside it';
    ahead.addEventListener('click', function (ev) {
      ev.stopPropagation();
      planLayout(planWay === 'below' ? 'beside' : 'below');
      ahead.classList.toggle('on', planWay === 'beside');
      loadPlan(true);
    });
    tools.appendChild(ahead);
    right.appendChild(tools);

    var plan = make('div', 'sp-plan');
    plan.id = 'spPlan';
    script.appendChild(plan);          /* 'below' is the default */

    function crawlRate() {
      /* 1..100 on the slider, about 2 to 220 px a second, curved so the
         slow half of the travel has real resolution - that is the half
         anybody reading along actually uses. */
      var v = Math.max(1, Math.min(100, Number(rate.value) || 30)) / 100;
      return 2 + 218 * v * v;
    }
    function crawlSet(on) {
      crawl = !!on;
      run.textContent = crawl ? '⏸' : '▶';
      run.classList.toggle('on', crawl);
      tools.classList.toggle('on', crawl);
      if (crawl) {
        follow = false;             /* the two cannot both drive */
        var chip = el('spNow');
        if (chip) chip.classList.add('adrift');
        crawlLast = 0;
        crawlOwed = 0;
        requestAnimationFrame(crawlStep);
      }
    }
    function crawlStep(ts) {
      if (!crawl) return;
      var box = el('spScript');
      if (!box) { crawl = false; return; }
      if (crawlLast) {
        crawlOwed += crawlRate() * ((ts - crawlLast) / 1000);
        var whole = Math.floor(crawlOwed);
        if (whole >= 1) {
          crawlOwed -= whole;
          selfScrollUntil = Date.now() + 400;   /* our own scroll (#the guard) */
          box.scrollTop += whole;
          if (box.scrollTop + box.clientHeight >= box.scrollHeight - 2) {
            crawlSet(false);                    /* the end of the script */
          }
        }
      }
      crawlLast = ts;
      if (crawl) requestAnimationFrame(crawlStep);
    }
    run.addEventListener('click', function (ev) {
      ev.stopPropagation();                     /* not a pane tap */
      crawlSet(!crawl);
    });
    rate.addEventListener('click', function (ev) { ev.stopPropagation(); });
    rate.addEventListener('input', function () {
      if (crawl) { crawlLast = 0; }             /* take the new rate now */
    });

    now.addEventListener('click', function () {
      crawlSet(false);       /* back to the air stands the crawl down */
      follow = true;
      now.classList.remove('adrift');
      nowLineId = '';        /* force markNow to re-seat and scroll */
      tick();
    });

    var detail = make('div', 'sp-detail');
    detail.id = 'spDetail';
    detail.hidden = true;
    right.appendChild(detail);

    host.appendChild(left);
    host.appendChild(right);
  }

  function mount(node) {
    if (!motionTimer) motionTimer = setInterval(function () { try { sampleMotion(); } catch (e) { /* the ring is a courtesy */ } }, MOTION_MS);   /* 2026-09-14 */
    if (mounted) return Promise.resolve(true);
    build(node);
    retryReports();
    wirePlayer();
    mounted = true;
    foldLoad();                                              /* #1294 */
    if (!scopeFrame) paintScope();                           /* #1298 */

    var feed = root.PineStationFeed;
    if (feed && typeof feed.subscribe === 'function') {
      stop = feed.subscribe(function (payload) {
        var state = (payload && payload.station) || payload || {};
        var wasAt = liveStream && liveStream.at;
        liveStream = state.stream_now || null;
        if (!liveStream || liveStream.at !== wasAt) lastOffMs = 0;
        speakingNow = state.speaking_now || null;
        flow = state.dialogue_flow || null;
        /* talk_next_in rides at the top of the payload, not inside
           dialogue_flow; fold it in so status() has one place to read. */
        if (flow && typeof state.talk_next_in === 'number') {
          flow.talk_next_in = state.talk_next_in;
        }
        stationPaused = !!state.paused;
        /* #1336: THE COMMITTED SEQUENCE. `admission` is the playout
           controller's own record of what it admitted, in the order it
           admitted it. Absent on a station that has not been patched yet,
           in which case admitMap.ok stays false and every road below
           falls back exactly as before. */
        admitMap = PineScriptCues.read(state.admission);
        /* Cancel the clock difference between this tablet and the station
           rather than assuming they agree; four seconds of drift would
           point the highlight at the wrong line. */
        if (state.server_ms) skewMs = Number(state.server_ms) - Date.now();
        correct();
        paintPlayer(state);
        paintFeed(state);
        loadScreenplay(false);
        loadPlan(false);                              /* #1289 */
        tick();
      });
    } else {
      loadScreenplay(true);
    }
    if (root.PineConsoleLine) root.PineConsoleLine.start();
    /* #1276: the read the operator is actually waiting on when they
       switch to this view. Forced, so it cannot be answered out of a
       twenty-second cache that predates the line now sounding. */
    loadScreenplay(true);
    loadPlan(true);                                   /* #1289 */
    if (!beat) beat = setInterval(tick, 250);
    return Promise.resolve(true);
  }

  root.PineScriptPage = {
    mount: mount,
    /* The cue-map arithmetic, exported for
       tests/test_script_admission_view_2026_09_15.cjs. It is pure, so the
       test holds the real code rather than a copy of it. */
    cues: PineScriptCues,
    isMounted: function () { return mounted; },
    close: function () {
      folderClose();                                  /* 2026-09-14 */
      reasonClose();
      inboxClose();
      headerClose();                                  /* #1164 */
      if (stop) stop();
      stop = null;
      if (beat) clearInterval(beat);
      beat = 0;
    }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.PineScriptPage;
})(typeof window !== 'undefined' ? window : globalThis);
