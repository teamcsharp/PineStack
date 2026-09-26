/* window.PineSfxTv - the SFX guy's television, floating over every view.
 *
 * "If the SFX guy plays an MP4 clip, I wanna see a pop up of that in a
 *  little pop up window ... And then I want it to close out like a CRT
 *  television where it just closes into a line and disappears."
 *
 * "When popping up the picture in picture display on different views, I
 *  want it to pop up similar to this where it's basically just a little
 *  window that I'm able to click and drag around in position that's able
 *  to be saved to the preferences and be retained the next time that the
 *  picture in picture pops up in the view or in any view."
 *
 * WHY IT LIVES IN THE SHELL AND NOT IN A VIEW. Every view in this window
 * is a <section class="view"> that is display:none the moment another
 * tab is chosen, and three of them are <webview>s with their own
 * documents entirely. A set built inside any one of those exists in one
 * view only - which is precisely the arrangement the operator asked
 * against. This mounts at BODY level, a sibling of <main>, so it is over
 * the Script view, the Sampler, the Agent frame, and anything added
 * later, without those views knowing it exists.
 *
 * WHY IT POLLS ITS OWN ROUTE. A video sting never goes to the satellite -
 * the Nabu has no screen - and in the ordinary arrangement here the DJs
 * talk out of the box, which is exactly when the station panel stops
 * polling the voice feed at all. /api/dj/video (#1263) is the station's
 * own small door for the clips that have a picture: same ring, same feed
 * epoch, same staleness rule, filtered to video.
 *
 * THE GEOMETRY IS THE PREFERENCE. Where the operator drags it and what
 * size they leave it at are written to localStorage on pointerup - the
 * same store the rail width and the app volume use - and read back the
 * next time the set comes on, in whatever view happens to be showing.
 * It is clamped to the window on the way in, so a box left at the edge
 * of a big monitor is still on screen on a small one.
 */
(function (root) {
  'use strict';

  /* The kiosk carries this controller in both of its legacy asset bundles.
   * Only the first canonical copy may mount timers and document handlers. */
  if (root.PineSfxTv && root.PineSfxTv.__pineCanonicalSfxTv
      && root.PineSfxTv.__pineSfxTvDocument === document) {
    if (typeof module !== 'undefined' && module.exports) module.exports = root.PineSfxTv;
    return;
  }

  var KEY = 'pineSfxTvBox';       // the preference: left, top, width, height
  var POLL_MS = 2500;
  var WALL_FOLLOW_MS = 750;       // local native state, independent of the server poll
  var MIN = {w: 180, h: 120};
  var DEFAULT = {width: 420, height: 268};
  /* Longer than the .off animation in sfx-tv.css, so the last frame of the
   * collapse is seen rather than cut off by the removal. */
  var OFF_MS = 520;
  /* Past this many seconds late, the set would be coming on over whatever
   * is airing NOW - which is worse than the clip being missed. */
  var LATE = 8;

  /* #1173 - "So even though the Pine tab is the default device, video seem
   *  to have a slight lag when it comes to playing out of the Pine tablet.
   *  its showing a different video on the spark agent than the tablet so
   *  they are getting out of sync."
   *
   * THE CLIP IS JOINED WHERE THE STATION IS, NOT AT ITS START.
   *
   * The station already decides which picture is current and when: the
   * endless cycle stamps every clip with a start, it comes out of
   * /api/dj/video as broadcast_ms, and poll() below turns it into this
   * machine's clock as clip.at. Both surfaces are handed the same plan.
   *
   * What each surface DID with it was start the file from zero whenever it
   * got round to it, and then take its next clip when THIS one ended -
   * so every hand-over spent OFF_MS of CRT collapse, the 120 ms teardown
   * rest and however long that surface needs to put up a first frame, and
   * none of it was ever given back. The error ratcheted, at a rate set by
   * how fast the machine is, and the two machines are not the same speed.
   *
   * Measured on the tablet, 2026-09-15, twelve consecutive clips off the
   * endless set, each one's slip against the station's own stamp:
   *
   *   +1.23 +2.44 +3.38 +4.72 +5.71 +7.01 | +4.62 +6.21 +7.66 +7.88 ...
   *
   * about +1.16 s a clip - and at the bar, eight seconds of slip, the LATE
   * test above threw a clip away UNPLAYED and the tablet was on a picture
   * the desk had already finished. That is both halves of the report in
   * one mechanism. The desk ratchets the same way and slower: the fixed
   * 640 ms is identical on both, but src-to-first-frame measured 463-540
   * ms on the tablet against 90-145 ms for the whole 350 kB file on the
   * desk's own machine. The DIFFERENCE between the two rates is the drift
   * he sees. No poll interval, no cache, no token, and /sfx does answer a
   * Range request (206, accept-ranges: bytes), so a clip is not waiting to
   * arrive whole before a frame exists.
   *
   * So a clip's position becomes a function of the station's clock and
   * nothing else - the way the two rooms' audio already is. A surface that
   * arrives late joins the picture in progress instead of running its own
   * copy of the schedule a second and a half behind, and the error cannot
   * accumulate because every clip is anchored afresh. */
  var JOIN_MIN = 0.35;             // below this a seek costs more than it buys
  var JOIN_TAIL = 0.6;             // this near the end, let it be
  var SLIP_MAX = 0.75;             // a jump smaller than this is worse than the slip
  var SLIP_REST = 4000;            // and never two jumps closer than this
  /* #1421: ...AND NEVER MORE OF THE CLIP THAN THIS.
   *
   * The three numbers above ask only "is this drift big enough to be
   * worth correcting". On the wallpaper clip the rule was written
   * against - tens of seconds long - that is the whole question. The
   * endless set does not play those: its clips are 2-3.5 s (see #1422),
   * and on a 2 s clip an 0.8 s correction, which is simply how late a
   * clip starts once it has been fetched and decoded, threw away forty
   * per cent of the clip and flushed the decoder to do it - every
   * SLIP_REST, on every clip. That is the choking.
   *
   * So a jump must also be small AGAINST THE CLIP IT LANDS IN. A quarter
   * of it, at most. Long wallpaper keeps its correction (a quarter of a
   * minute is fifteen seconds of allowance, so #1173's woke-from-sleep
   * case still fires); a short clip is left to play, because there is no
   * position inside it worth a decode flush. */
  var SLIP_SHARE = 0.25;

  /* Is this jump worth making, in a clip THIS long? A clip whose
     duration is not known yet is never seeked - not knowing is a reason
     to leave the decoder alone, not a reason to guess. */
  function worthSeeking(off, span, floor) {
    var drift = Math.abs(Number(off));
    if (!isFinite(drift) || drift < floor) return false;
    if (!isFinite(span) || span <= 0) return false;
    return drift <= span * SLIP_SHARE;
  }

  var playing = null;              // #1306b: the clip in the tube now
  var host = null;                 // the window, while a clip is in it
  var video = null;
  var tube = null;
  var assembly = null;             // the plexus covering a decoder with no frame
  var timer = null;                // the poll
  var wallFollowTimer = null;      // lightweight native-wall follower
  var hold = null;                 // the "not due yet" timer
  var queue = [];
  /* #1195: WHAT THE STATION HAS RUNG AHEAD, which `queue` above is not.
   *
   * `queue` is a holding array: offer() pushes a clip into it and calls
   * next() in the same breath, so it is empty or holds one almost all the
   * time. The strip was built from it and therefore drew no "next" tiles at
   * all - the operator boxed the empty space where they should have been.
   *
   * This keeps what is coming, with the moment each is due on THIS
   * machine's clock (poll() already computes that, because the box and this
   * machine have no reason to agree). Plain objects, never elements: the
   * notes in this file record what a spare video element cost here. */
  var coming = [];                 // {id, url, sting, seconds, at}
  var COMING_MOST = 6;
  var seen = 0;
  var busy = false;                // a poll in flight
  var showing = false;
  var base = '';
  var level = 1;
  var marks = Object.create(null);
  var mounted = false;
  var warm = null;                 // #1411: the next clip, already fetching
  /* #1112: THE SHEET HOLDS THE SET.
   *
   * "When this menu is up, keep the video pop-up window on screen so I
   *  can finish using the dialogue pop-up. I want to be able to use this
   *  to basically permanently delete videos from the repository or
   *  choose to have videos not play anymore or even inspect the location
   *  and find out where videos are located."
   *
   * A clip is a few seconds long and the sheet is opened by a half-second
   * hold, so the operator was routinely still reading the sheet when
   * `ended` fired, the CRT collapsed and teardown() took the host - and
   * the sheet with it, mid-decision. So while the sheet is up, a finish
   * is OWED rather than run: the picture sits on its last frame and the
   * finish happens when the sheet goes, by whichever road it goes.
   *
   * `sheetWrap` is the open sheet (null when none), `curtain` is the
   * finish of the set on screen, `owed` says the clip ended under a
   * sheet. All three are module-level because the sheet lives outside
   * play()'s closure, and every road that closes the sheet goes through
   * sheetClose() so the owed finish cannot be missed. */
  var sheetWrap = null;
  /* [#1450] The wall sheet's shade: full-screen, transparent, and the
     thing a tap lands on when the operator means "away". Held here
     rather than looked up, so sheetClose() cannot miss it. */
  var sheetShade = null;
  var curtain = null;
  var owed = false;
  /* #1121-#1124: THE COUNTERS LIVE HERE, NOT IN play()'s CLOSURE.
   *
   * "Allow me to double tap a video that's playing on tablet to replay
   *  the video. And if I continue double tapping it, I want to play it
   *  X amount of times." (#1121)
   * "offer a slider for playing the next sequential clips ... if I
   *  expand it to say seven, it plays that clip and the next seven
   *  clips in a row sequentially." (#1124)
   *
   * Next, Prev and the run all go through cut(), and cut() runs
   * teardownNow() - every reference play() holds is gone with the set.
   * A counter kept in the closure would be zero again on the very
   * clip it was meant to govern. So the replays owed and the clips
   * left in the run are module state; play() reads them on `ended`
   * and the only things that clear them are the operator's own Stop,
   * the slider at 0, a folder with nothing more, and stop().
   *
   * `rewind` is this set's own "back to the start and play", installed
   * by play() the way `curtain` is, because the double tap lands on a
   * closure it cannot otherwise reach. `full` is #1122's toggle, with
   * `fullBox` the windowed geometry it goes back to; `badge` and
   * `askWrap` are the two small things drawn over the picture. */
  var replays = 0;                 // #1121: plays still owed after this one
  var lastDouble = 0;              // #1121: when the last double tap landed
  var rewind = null;               // #1121: play()'s own replay, or null
  var runLeft = 0;                 // #1124: clips still to play after this one
  var runFrom = '';                // #1124: the clip the run was set from
  var full = false;                // #1122: the set fills the window
  var fullBox = null;              // #1122: the box to go back to
  var badge = null;                // the "x3" / "7 to go" over the picture
  var askWrap = null;              // #1121's hold bubble, while it is up
  var parodyWrap = null;           // H3 prompt and source-history picker
  var parodyVideo = null;
  var parodyCover = null;
  var parodyDictationRelease = null;
  var parodyOwnsSurface = false;
  var parodyPolling = Object.create(null);
  var parodyQueueTimer = 0;
  var radialWrap = null;            // the shared hold menu for every video surface
  var radialMedia = null;
  var radialMediaWasPlaying = false;
  var deleteWrap = null;
  var tl = null;                   // [#1219] the timeline along the bottom of the picture
  var tlFill = null;               // [#1219] its fill
  var tlClock = null;              // [#1219] its m:ss corner
  var tlFrame = 0;                 // [#1219] the rAF driving it
  var tlSecond = -1;               // [#1219] the second last printed
  var FULL_KEY = 'pineSfxTvFull';  // #1122: '1' when the next set opens full

  function assemblyDrop() {
    var old = assembly;
    assembly = null;
    try { if (old && old.destroy) old.destroy(); } catch (err) { /* gone */ }
  }

  function assemblyBind(media, screen, name) {
    assemblyDrop();
    if (!media || !screen || !root.PineWallTransition
        || typeof root.PineWallTransition.cover !== 'function') return;
    assembly = root.PineWallTransition.cover(media, {
      container: screen,
      className: 'sfx-tv-assembly',
      label: String(name || 'VIDEO') + ' ASSEMBLING',
      zIndex: 2
    });
  }
  /* #1184: THE RIGHT-CLICK SHEET ON THE LISTEN TAB, AND WHAT IT CARRIES.
   *
   * "If I right click a video in the listen tab while it's in endless
   *  video mode, offer a right click option where I can examine the
   *  video, see the path, delete the video, trace its location, and also
   *  picture its neighbours."
   * "i want it to come up on right click for video"
   * "i want the popup to show thumbnails of the last 2 videos played and
   *  the next 2 videos planned for play and i want to be able to tap them
   *  to jump to them and play / examine / manage them as well."
   *
   * THE THING THAT MADE THIS DO NOTHING, MEASURED BEFORE A LINE WAS
   * WRITTEN. On the LISTEN tab the picture he is right-clicking is NOT
   * this set. listen.js paintEndless paints the endless clip onto its own
   * wallpaper element (#plBackVid) and then calls veil(true), which sets
   * this set's host to visibility:hidden - and a hidden element receives
   * no pointer events at all, so the contextmenu handler build() installs
   * on the host can never fire on that tab. The wallpaper cannot fire it
   * either: .pl-back carries pointer-events:none in listen-music.css, so
   * the right-click passes straight through the video to whatever is
   * behind it. Two elements, and neither of them could hear him.
   *
   * So the gesture is taken at DOCUMENT level and answered geometrically:
   * is the endless wall up, and did the press land inside the rectangle
   * that wallpaper occupies. That is the only test that is true in every
   * state the LISTEN view has - windowed, bare/full-bleed, and during the
   * second or two per clip where the wallpaper is hidden behind the
   * plexus while the next file arrives.
   *
   * `sheetOnWall` says the sheet is mounted on the body rather than
   * inside the set, because on that tab the set it would live in is
   * invisible. Everything that used to clear `sheetWrap` by hand now goes
   * through sheetForget(), which also REMOVES a body-mounted sheet - one
   * left behind would be a menu floating over the show with nothing
   * underneath it and no road that could take it down.
   *
   * `heard` is the cycle's own short memory. Nothing in this file kept
   * what had already played - `playing` is now, `queue` is next, and the
   * past was simply gone - so the strip could not have shown the last two
   * without it. It holds ids, urls and names ONLY. #1312 is the reason
   * that is written down: this file has been bitten by holding <video>
   * elements that would not let go, six of them exhausted the WebView's
   * connections and every fetch on the page hung. A ring of plain objects
   * cannot do that. */
  var sheetOnWall = false;         // the sheet is on the body, not in the set
  var panel = null;                // the Inspect / Path detail panel, if open
  var heard = [];                  // {id, url, sting} of clips already played
  var HEARD_MOST = 8;              // bounded plain rows; never media elements
  var STRIP_PAST = 3;              // the last three clips shown in the popup
  var STRIP_NEXT = 2;              // enough future context without crowding it
  /* #1200: SCROLLING BACKWARDS THROUGH EVERYTHING THAT HAS GONE OUT.
   *
   * "Allow me to roll the wheel or scroll through the previous history of
   *  videos that's been loaded or thumbnails or MP4s. I wanna be able to
   *  scroll backwards in the history and just keep loading more and more
   *  of the history."
   *
   * `heard` above is the CYCLE'S memory and the strip draws its last three.
   * Earlier entries arrive two at a time when the operator asks for more.
   * the page, they lived only as long as the tab, and there was next to
   * nothing to scroll through at all.
   *
   * The station has kept one all along. data/sfx_history.json is appended
   * by sfx_history_add() on every airing and trimmed to the last 2,000
   * rows, and GET /api/sfx/history has served it since #862. MEASURED
   * before a line of this was written: that road took only `limit`,
   * clamped it to 1..1000 and answered `rows[-limit:]` reversed - so a
   * second page meant asking for a BIGGER first page, everything already
   * held came back down the wire again, and at a thousand rows it stopped.
   * It could not page. #1200's server half adds `before` (a ts), and
   * moves the whole read - a 2,000-row json.loads, the bans, the weights,
   * the folder walk and a media_sign per row - off the event loop into a
   * worker thread, because this station goes deaf when its loop stalls
   * and that has been the single largest source of dead air on it.
   *
   * WHAT IS HELD HERE, AND WHY IT IS BOUNDED. `hist` is plain objects and
   * nothing else, for the reason #1312 wrote down in this same file:
   * orphaned <video> elements each held an HTTP connection, a WebView
   * allows about six per host, and after a few taps every request on the
   * page hung - a fetch of /api/pulse that never returned while the same
   * url answered the desk in 0.02 s.
   *
   *   HIST_PAGE = 2. The popup begins with the last three items and every
   *   explicit reach reveals exactly two older airings. The wire asks for
   *   one extra row after the first page because the timestamp cursor is
   *   inclusive; that boundary row is deduped here, not shown twice.
   *
   *   HIST_MOST = 120, five pages. 120 tiles is roughly 9,100 px of row -
   *   some twenty screenfuls at that width - far more than a browse, and
   *   it is also what bounds the poster cache, because there is exactly
   *   one cached <img> per row and no other road that grows it. Past the
   *   ceiling the window SLIDES: the newest fetched rows are let go and
   *   the seam where they were says so out loud. An <img> is not the #1312
   *   hazard - it releases its connection once it has loaded - but
   *   unbounded is unbounded. */
  var HIST_PAGE = 2;               // each explicit reach reveals two older tiles
  var HIST_MOST = 120;             // the ceiling: five pages held at once
  var HIST_NEAR = 72;              // "against the old end", in px
  var hist = [];                   // plain rows, OLDEST FIRST
  var histSeen = Object.create(null);  // ts|id -> 1, so a page cannot repeat
  var histAt = 0;                  // the `before` cursor for the next page
  var histMore = true;             // the station says there is older still
  var histBusy = false;            // a page is in flight
  var histBad = false;             // the last page FAILED (not the end)
  var histSay = '';                // what the note at the old end reads
  var histLost = 0;                // rows the ceiling let go of
  var stripEl = null;              // the open sheet's strip, for prepending
  var stripClip = null;            // the clip that sheet was opened for
  var stripSay = null;             // that sheet's note line
  var stripOwedLeft = null;        // one programmatic scroll event to ignore
  var histNoteEl = null;           // the note tile at the old end
  var wallWired = false;           // the document-level gesture road is on
  var wallPress = null;            // a touch hold in progress on the wall
  var wallTimer = 0;
  var WALL_HOLD_MS = 550;          // the tablet's stand-in for a right button
  /* #1184: the station's seamless switch, learned on the poll (see poll()).
   * Null until the station has answered once, so a surface that has not
   * heard yet behaves exactly as it did before this change. */
  var seamOn = false;
  var DOUBLE_MS = 350;             // two taps closer than this are one gesture
  var DOUBLE_RUN_MS = 2500;        // a double tap within this ADDS a replay
  var HOLD_MS = 500;
  var TAP_MS = 300;
  var SLOP_PX = 8;

  function api() { return root.pineDesktop; }

  /* [#1216] A LEVEL CHANGE IS A RAMP, NOT A STEP - and only one at a time.
   *
   * Eight steps over 120 ms. Short enough that the operator's thumb owns
   * it and long enough that it is not a click. A second change while one
   * is running replaces it rather than racing it, and a ramp against an
   * element that has left the tube stops on its own. */
  var LEVEL_RAMP_MS = 120;
  var LEVEL_RAMP_STEPS = 8;
  var levelRun = null;
  var levelContext = null;

  /* HTMLMediaElement.volume stops at unity. The set's gain stage carries
   * the upper half of the public 0-200 range and is disconnected with the
   * short-lived clip element. */
  function levelStage(el, want) {
    if (!el) return null;
    if (el.__pineSfxLevelStage) return el.__pineSfxLevelStage;
    if (!(want > 1)) return null;
    var Ctor = root.AudioContext || root.webkitAudioContext;
    if (!Ctor) return null;
    try {
      levelContext = levelContext || new Ctor();
      if (levelContext.state !== 'running') {
        var waking = levelContext.resume();
        if (waking && typeof waking.then === 'function') {
          waking.then(function () {
            if (el && el.isConnected) levelRamp(el, level);
          }, function () { /* native volume remains at unity */ });
        }
        return null;
      }
      var source = levelContext.createMediaElementSource(el);
      var gain = levelContext.createGain();
      gain.gain.value = Math.max(0, Math.min(1, Number(el.volume) || 0));
      source.connect(gain);
      gain.connect(levelContext.destination);
      el.__pineSfxLevelStage = {source: source, gain: gain};
      return el.__pineSfxLevelStage;
    } catch (err) { return null; }
  }

  function levelDrop(el) {
    var stage = el && el.__pineSfxLevelStage;
    if (!stage) return;
    try { stage.source.disconnect(); } catch (err) { /* gone */ }
    try { stage.gain.disconnect(); } catch (err2) { /* gone */ }
    try { delete el.__pineSfxLevelStage; } catch (err3) { /* weak ownership */ }
  }

  function levelSet(el, want, smooth) {
    if (!el) return;
    if (el.dataset && el.dataset.pineSilentPicture === '1') {
      el.muted = true;
      want = 0;
    }
    var value = Math.max(0, Math.min(2, Number(want)));
    if (!isFinite(value)) return;
    var stage = levelStage(el, value);
    if (!stage) {
      try { el.volume = Math.min(1, value); } catch (err) { /* gone */ }
      return;
    }
    try { el.volume = 1; } catch (err2) { /* gain still owns it */ }
    try {
      if (smooth) stage.gain.gain.setTargetAtTime(value, levelContext.currentTime, 0.03);
      else stage.gain.gain.setValueAtTime(value, levelContext.currentTime);
    } catch (err3) { try { stage.gain.gain.value = value; } catch (err4) { /* gone */ } }
  }

  function levelRamp(el, want) {
    if (levelRun) { clearInterval(levelRun.timer); levelRun = null; }
    if (!el) return;
    if (want > 1 || el.__pineSfxLevelStage) {
      levelSet(el, want, true);
      return;
    }
    var from = Number(el.volume);
    if (!isFinite(from)) from = want;
    if (Math.abs(from - want) < 0.005) {
      try { el.volume = want; } catch (err) { /* gone */ }
      return;
    }
    var started = Date.now();
    var run = {el: el, timer: 0};
    run.timer = setInterval(function () {
      if (levelRun !== run || el !== video) {
        clearInterval(run.timer);
        if (levelRun === run) levelRun = null;
        return;
      }
      /* A busy renderer can delay interval callbacks while video or another
       * view paints. Elapsed time keeps this a 120 ms ramp even when fewer
       * than eight callbacks get CPU time. */
      var share = Math.min(1, Math.max(0, (Date.now() - started) / LEVEL_RAMP_MS));
      var at = from + (want - from) * share;
      try { el.volume = Math.max(0, Math.min(1, share >= 1 ? want : at)); }
      catch (err) { /* the element went */ }
      if (share >= 1) {
        clearInterval(run.timer);
        if (levelRun === run) levelRun = null;
      }
    }, Math.max(8, Math.round(LEVEL_RAMP_MS / LEVEL_RAMP_STEPS)));
    levelRun = run;
  }

  /* #1112: is the hold sheet up on the set that is on screen? Checked
   * by parentage rather than a DOM query so a set that was swept by
   * build() or teardownNow() no longer counts as held. */
  function sheetHeld() {
    if (!sheetWrap || !host) return false;
    /* #1184: a sheet opened over the LISTEN wall is mounted on the body,
       because the set it belongs to is veiled there and a child of a
       visibility:hidden element cannot be seen or touched. It still
       counts as held - the clip on the tube is still the one the
       operator has open - so the owed-finish rule covers it too. */
    if (sheetOnWall) return !!sheetWrap.parentNode;
    return sheetWrap.parentNode === host;
  }

  /* #1184: FORGET THE SHEET, AND TAKE IT WITH YOU IF IT IS NOT THE SET'S.
   *
   * build(), teardown() and teardownNow() each used to write
   * `sheetWrap = null` and rely on the set being removed to take the
   * sheet with it, which was true while the sheet was always a child of
   * the host. A body-mounted sheet is not a child of anything that is
   * being removed, so the same line would leave a menu on screen that
   * nothing could ever close: sheetClose() had lost its reference to it.
   * Every one of those three roads calls this instead. */
  function sheetForget() {
    var wrap = sheetWrap;
    var wasOnWall = sheetOnWall;
    sheetWrap = null;
    sheetOnWall = false;
    panel = null;                  // it was inside the sheet
    /* #1200: the strip was inside it too. The ROWS are kept - closing the
       sheet and opening it again must not re-ask the station for pictures
       it has already handed over - but the element handles go, because a
       page landing after this would otherwise insert tiles into a strip
       that is no longer in any document. */
    stripEl = null;
    histNoteEl = null;
    if (!wasOnWall) return;        // it goes with the set being swept
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err) { /* already gone */ }
  }

  /* #1112: THE ONE DOOR OUT OF THE SHEET. Close, the second hold, Stop,
   * a delete or a ban that is done - every one of them comes through
   * here, because a road that removed the sheet by hand would leave an
   * owed finish owed for ever: a set on its last frame that nothing
   * ever takes down. */
  /* [#1386c] THE PICTURE STAYS UP AND STOPS MOVING.
   *
   * "if i bring up the menu. Keep the video up so i can decide what to do
   *  with it. Dont cycle to the next video while the popup is active. I
   *  need to make decisions on that element"
   *
   * The first cut of this HID the picture, which was wrong for the obvious
   * reason: the operator is deciding what to do with the clip he is
   * looking at, and taking it off the glass takes away the thing the
   * decision is about.
   *
   * So: hold, never hide. The clip freezes where it is, the playlist keeps
   * its place, and the menu is moved clear of the picture rather than laid
   * over it - because on this glass it CANNOT be laid over it. Measured on
   * the tablet: `document.querySelectorAll('.sfx-tv')` is EMPTY while a
   * picture-in-picture clip is up, so there is no web frame at all; the
   * picture is PineVideoWall's own SurfaceView, composited by
   * SurfaceFlinger above an opaque WebView (setZOrderMediaOverlay(true),
   * PineVideoWall.kt:93). No z-index, no promoted layer and no amount of
   * CSS reaches across that, and the first two attempts here were both
   * arguing in the wrong layer.
   */
  var wallBox = null;

  function wallAsk(cmd, arg) {
    try {
      var bridge = root.pineDesktop;
      if (!bridge || typeof bridge.videoWall !== 'function') return null;
      return bridge.videoWall(cmd, arg);        /* a Promise on this build */
    } catch (err) { return null; }
  }

  /* Where the picture actually is, so the sheet can stand beside it. */
  function wallWhere() {
    var got = wallAsk('state');
    if (!got || typeof got.then !== 'function') return Promise.resolve(null);
    return got.then(function (raw) {
      try { return typeof raw === 'string' ? JSON.parse(raw) : raw; }
      catch (err) { return null; }
    }).catch(function () { return null; });
  }

  function surfaceDown(on) {
    /* The web frame, when there is one (the desktop shell has one; the
       tablet, as measured, usually does not). Held rather than hidden. */
    try {
      var frames = document.querySelectorAll('.sfx-tv');
      for (var i = 0; i < frames.length; i += 1) {
        if (frames[i].classList.contains('sfx-tv-sheet')) continue;
        var v = frames[i].querySelector('video');
        if (v) { if (on) { try { v.pause(); } catch (e) { /* gone */ } }
                 else { try { v.play(); } catch (e) { /* gone */ } } }
      }
    } catch (err) { /* no frame on screen */ }
    /* The native wall is a SurfaceView above the WebView. While its menu is
       open it must be held AND retired from composition, otherwise no HTML
       can occupy the picture's rectangle. `menu` preserves the wall's
       logical veil and `free` restores it, so Listen still owns its backdrop
       after an inspection closes. */
    wallAsk(on ? 'menu' : 'free');
    if (!on) wallBox = null;
  }

  function wallCssRect(st) {
    if (!st) return null;
    var d = Number(root.devicePixelRatio) || 1;
    var box = {x: Number(st.x || st.left || 0) / d,
               y: Number(st.y || st.top || 0) / d,
               w: Number(st.w || st.width || 0) / d,
               h: Number(st.h || st.height || 0) / d};
    return box.w > 0 && box.h > 0 ? box : null;
  }

  /* The native menu now retires the SurfaceView while it is held, so the
     sheet can stand IN the picture's rectangle instead of appearing as an
     unrelated panel at the top of the page. The wall reports DEVICE pixels;
     every value is converted before it is used in WebView layout. */
  function sheetClear(wrap) {
    if (!wrap) return;
    wallWhere().then(function (st) {
      if (!st || !wrap.parentNode) return;
      var raw = {x: Number(st.x || 0), y: Number(st.y || 0),
                 w: Number(st.w || st.width || 0),
                 h: Number(st.h || st.height || 0)};
      var box = wallCssRect(st);
      if (!box) return;                            /* no measured wall */
      wallBox = raw;                               /* bridge wants device px */
      var W = root.innerWidth || 1280;
      var H = root.innerHeight || 800;
      var wide = Math.max(260, Math.min(box.w, W - 16));
      var tall = Math.max(150, Math.min(box.h, H - 16));
      var left = Math.max(8, Math.min(W - wide - 8, box.x));
      var top = Math.max(8, Math.min(H - tall - 8, box.y));
      wrap.style.position = 'fixed';
      wrap.style.left = Math.round(left) + 'px';
      wrap.style.right = 'auto';
      wrap.style.bottom = 'auto';
      wrap.style.top = Math.round(top) + 'px';
      wrap.style.width = Math.round(wide) + 'px';
      wrap.style.maxHeight = Math.round(tall) + 'px';
      wrap.style.boxSizing = 'border-box';
    });
  }

  function sheetClose() {
    surfaceDown(false);                                  /* [#1386b] */
    var wrap = sheetWrap;
    sheetWrap = null;
    sheetOnWall = false;                                 /* #1184 */
    panel = null;                                        /* #1184 */
    stripEl = null;                                      /* #1200 */
    histNoteEl = null;                                   /* #1200 */
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err) { /* already gone */ }
    /* [#1450] and the shade with it. Every road that closes the sheet
       comes through here - a delete, a ban, a glue landing on its new
       clip, the editor coming back - so none of them can leave an
       invisible full-screen div behind swallowing taps. */
    var shade = sheetShade;
    sheetShade = null;
    try { if (shade && shade.parentNode) shade.parentNode.removeChild(shade); }
    catch (err) { /* already gone */ }
    var due = owed;
    owed = false;
    if (due && curtain) {
      try { curtain(); } catch (err) { /* the set is already going */ }
    }
  }

  function now() { return Date.now(); }

  /* [#1219] THE TIMELINE'S OWN CLOCK. rAF and not a timer: this WebView
     suspends JS timers and keeps firing rAF (the note beside `fixedAt`
     in play() has the measurement), and a strip that froze would read
     as a stalled clip. `screen` is held the way every handler in play()
     holds it - a set torn down and rebuilt under the loop simply stops
     it, because `video` no longer is `screen`. Elapsed is floored,
     the total rounded, so "0:04" is the same 0:04 the screenplay prints. */
  function tlText(v, whole) {
    var t = Math.max(0, whole ? Math.round(Number(v) || 0) : Math.floor(Number(v) || 0));
    var m = Math.floor(t / 60), s = t % 60;
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  function tlStop() {
    if (tlFrame && typeof root.cancelAnimationFrame === 'function') {
      try { root.cancelAnimationFrame(tlFrame); } catch (err) { /* gone */ }
    }
    tlFrame = 0;
  }
  function tlStart(screen) {
    tlStop();
    tlSecond = -1;
    if (typeof root.requestAnimationFrame !== 'function') return;
    var step = function () {
      if (video !== screen || !tl || !tlFill || !tlClock) { tlFrame = 0; return; }
      tlFrame = root.requestAnimationFrame(step);
      var span = Number(screen.duration), at = Number(screen.currentTime);
      if (!isFinite(span) || span <= 0 || !isFinite(at)) return;
      tlFill.style.width = (Math.max(0, Math.min(1, at / span)) * 100).toFixed(2) + '%';
      var sec = Math.floor(at);
      if (sec !== tlSecond) {
        tlSecond = sec;
        tlClock.textContent = tlText(at, false) + ' / ' + tlText(span, true);
      }
    };
    tlFrame = root.requestAnimationFrame(step);
  }
  /* [#1219] What the strip reads now, for the CDP probe in the D4-timeline
     verification sheet. Reads, never paints. */
  function tlRead() {
    if (!tl || !tlFill || !video) return {on: false};
    var wide = 0, of = 0;
    try {
      of = tl.clientWidth || 0;
      wide = tlFill.getBoundingClientRect().width || 0;
    } catch (err) { wide = 0; of = 0; }
    return {on: true, at: Number(video.currentTime) || 0,
      total: Number(video.duration) || 0, width: wide, of: of,
      fraction: of ? (wide / of) : 0,
      clock: (tlClock && tlClock.textContent) || ''};
  }

  /* ---- the preference ------------------------------------------------ */

  function readBox() {
    var saved = null;
    try { saved = JSON.parse(root.localStorage.getItem(KEY) || 'null'); }
    catch (err) { saved = null; }
    var w = Number(saved && saved.width) || DEFAULT.width;
    var h = Number(saved && saved.height) || DEFAULT.height;
    w = Math.max(MIN.w, Math.min(w, (root.innerWidth || 1280) - 16));
    h = Math.max(MIN.h, Math.min(h, (root.innerHeight || 800) - 16));
    /* No saved position yet: the lower right, out of the way of a rail on
     * the left and a reading column in the middle. */
    var left = saved && Number.isFinite(Number(saved.left))
      ? Number(saved.left) : (root.innerWidth || 1280) - w - 32;
    var top = saved && Number.isFinite(Number(saved.top))
      ? Number(saved.top) : (root.innerHeight || 800) - h - 72;
    /* Clamped, always: a box left at the edge of a big monitor has to
     * still be reachable on a small one, and a title bar off the top of
     * the screen is a window that can never be dragged back. */
    left = Math.max(0, Math.min(left, (root.innerWidth || 1280) - 80));
    top = Math.max(0, Math.min(top, (root.innerHeight || 800) - 40));
    return {left: left, top: top, width: w, height: h};
  }

  function writeBox() {
    if (!host) return;
    /* #1122: NEVER THE FULL-SCREEN GEOMETRY. The set fills the window
       while `full` is on, and a finish or a drop writing 0,0 x the whole
       screen would make that the windowed size for ever after - the
       toggle off would have nowhere to go back to. */
    if (full) return;
    var box = {left: host.offsetLeft, top: host.offsetTop,
               width: host.offsetWidth, height: host.offsetHeight};
    if (box.width < MIN.w || box.height < MIN.h) return;
    try { root.localStorage.setItem(KEY, JSON.stringify(box)); }
    catch (err) { /* a locked store is not a reason to stop the show */ }
  }

  /* A drag/resize of the native SurfaceView runs on Android's UI thread so
     it follows the finger even while this WebView is busy. Android calls
     this ONCE on release to persist the final DEVICE-pixel rectangle. */
  function rememberWallBox(x, y, w, h) {
    var d = Number(root.devicePixelRatio) || 1;
    var W = root.innerWidth || 1280;
    var H = root.innerHeight || 800;
    var box = {left: Number(x) / d, top: Number(y) / d,
               width: Number(w) / d, height: Number(h) / d};
    if (!(box.width > 0 && box.height > 0)) return null;
    box.width = Math.max(MIN.w, Math.min(box.width, W - 8));
    box.height = Math.max(MIN.h, Math.min(box.height, H - 8));
    box.left = Math.max(0, Math.min(box.left, W - 80));
    box.top = Math.max(0, Math.min(box.top, H - 40));
    try { root.localStorage.setItem(KEY, JSON.stringify(box)); }
    catch (err) { /* the live move still succeeded */ }
    if (host && !full) {
      host.style.left = Math.round(box.left) + 'px';
      host.style.top = Math.round(box.top) + 'px';
      host.style.width = Math.round(box.width) + 'px';
      host.style.height = Math.round(box.height) + 'px';
    }
    return box;
  }

  /* ---- the frame ----------------------------------------------------- */

  function drag(node, handle) {
    handle.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) return;
      if (event.target.closest('button')) return;
      if (full) return;              /* #1122: a full screen has nowhere to go */
      var from = {x: event.clientX, y: event.clientY,
                  left: node.offsetLeft, top: node.offsetTop};
      try { handle.setPointerCapture(event.pointerId); } catch (err) {}
      var move = function (e) {
        /* Clamped so the title bar can never leave the window: a set
         * dragged off the top edge is one nothing can bring back. */
        node.style.left = Math.max(0, Math.min((root.innerWidth || 0) - 60,
          from.left + e.clientX - from.x)) + 'px';
        node.style.top = Math.max(0, Math.min((root.innerHeight || 0) - 30,
          from.top + e.clientY - from.y)) + 'px';
      };
      var drop = function () {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', drop);
        handle.removeEventListener('pointercancel', drop);
        writeBox();                  // the preference is written on release
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', drop);
      handle.addEventListener('pointercancel', drop);
      event.preventDefault();
    });
  }

  function grip(node) {
    var handle = document.createElement('div');
    handle.className = 'sfx-tv-grip';
    handle.title = 'Drag to resize';
    handle.addEventListener('pointerdown', function (event) {
      if (event.button !== 0) return;
      if (full) return;              /* #1122 */
      var from = {x: event.clientX, y: event.clientY,
                  w: node.offsetWidth, h: node.offsetHeight};
      try { handle.setPointerCapture(event.pointerId); } catch (err) {}
      var move = function (e) {
        node.style.width = Math.max(MIN.w, Math.min(
          (root.innerWidth || 0) - node.offsetLeft - 4,
          from.w + e.clientX - from.x)) + 'px';
        node.style.height = Math.max(MIN.h, Math.min(
          (root.innerHeight || 0) - node.offsetTop - 4,
          from.h + e.clientY - from.y)) + 'px';
      };
      var drop = function () {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', drop);
        handle.removeEventListener('pointercancel', drop);
        writeBox();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', drop);
      handle.addEventListener('pointercancel', drop);
      event.preventDefault();
      event.stopPropagation();
    });
    node.appendChild(handle);
  }

  /* #1122: FULL SCREEN, AND BACK.
   *
   * "the video menu on tablet also offer an option to full screen the
   *  video pop-up window. So that way I could just view the video
   *  window full screen whenever it pops up. Allow me to toggle it off
   *  and on."
   *
   * Nothing here asks the browser for its fullscreen API - the kiosk
   * WebView would refuse it without a user gesture it can see, and the
   * shell has chrome of its own the set must stay under. The host is
   * simply told to fill the window, inline, over the stylesheet. The
   * windowed box is remembered FIRST so the toggle off lands where the
   * set was; and the choice is written to localStorage so the next set
   * comes on the same way - "whenever it pops up" - until it is turned
   * off again. `writeBox()` refuses to record the filled geometry. */
  function setFull(on) {
    on = !!on;
    try { root.localStorage.setItem(FULL_KEY, on ? '1' : '0'); }
    catch (err) { /* the toggle still works for this set */ }
    if (!host) { full = on; return; }
    if (on && !full) {
      fullBox = {left: host.offsetLeft, top: host.offsetTop,
                 width: host.offsetWidth, height: host.offsetHeight};
    }
    full = on;
    if (on) {
      host.classList.add('sfx-tv-full');
      host.style.left = '0px';
      host.style.top = '0px';
      host.style.width = '100vw';
      host.style.height = '100vh';
      host.style.borderRadius = '0';
      return;
    }
    host.classList.remove('sfx-tv-full');
    host.style.borderRadius = '';
    var box = fullBox || readBox();
    host.style.left = Math.round(box.left) + 'px';
    host.style.top = Math.round(box.top) + 'px';
    host.style.width = Math.round(box.width) + 'px';
    host.style.height = Math.round(box.height) + 'px';
    writeBox();
  }

  function fullWanted() {
    try { return String(root.localStorage.getItem(FULL_KEY) || '') === '1'; }
    catch (err) { return false; }
  }

  /* #1121/#1124: THE BADGE, top left of the picture (the pad icon has
   * the top right). "x3" while replays are owed, "7 to go" while a run
   * is on, both when both; and a line of its own for a moment when the
   * run stops - "nothing more in that folder". Hidden when there is
   * nothing to say. Styled inline: sfx-tv.css is not this change's to
   * edit. */
  var badgeTimer = 0;
  function paintBadge(text, forMs) {
    if (!badge) return;
    if (badgeTimer) { clearTimeout(badgeTimer); badgeTimer = 0; }
    var bits = [];
    if (text) {
      bits.push(String(text));
      badgeTimer = setTimeout(function () {
        badgeTimer = 0; paintBadge();
      }, forMs || 3000);
    } else {
      if (replays > 0) bits.push('×' + replays);
      if (runLeft > 0) bits.push(runLeft + ' to go');
    }
    badge.textContent = bits.join('  ');
    badge.hidden = !bits.length;
    badge.style.display = bits.length ? 'inline-block' : 'none';
  }

  /* A HOLD IS THE SHORT, HUMAN MENU. The full management sheet remains a
   * tap/right-click; holding the picture asks only what to do with the media
   * itself. This stays deliberately short enough to fit over the small tube. */
  function ask(screen) {
    if (!screen || !playing) return;
    askDrop();
    var clip = playing;
    var wrap = document.createElement('div');
    wrap.className = 'sfx-tv-ask sfx-tv';
    var q = document.createElement('div');
    q.className = 'sfx-tv-ask-title';
    q.textContent = 'What would you like to do with this video?';
    var summary = document.createElement('div');
    summary.className = 'sfx-tv-ask-summary';
    summary.textContent = String(clip.sting || clip.text || 'this clip');
    var list = document.createElement('div');
    list.className = 'sfx-tv-ask-list';
    var say = function (text) {
      summary.textContent = String(text || '');
    };
    var answer = function (label, detail, ref, go) {
      var b = document.createElement('button');
      b.type = 'button';
      var mark = document.createElement('span');
      mark.className = 'sfx-tv-ask-icon';
      mark.innerHTML = (typeof root.pineIcon === 'function'
        ? (root.pineIcon(ref, label) || '') : '');
      var words = document.createElement('span');
      words.className = 'sfx-tv-ask-words';
      var strong = document.createElement('b'); strong.textContent = label;
      var small = document.createElement('small'); small.textContent = detail;
      words.appendChild(strong); words.appendChild(small);
      b.appendChild(mark); b.appendChild(words);
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        go();
      });
      list.appendChild(b);
      return b;
    };
    answer('Generate parody', 'Dictate and edit an H3 Pine Box FM stinger',
      'c:microphone', function () {
        askDrop();
        parodyOpen(clip);
      });
    answer('Examine in depth', 'See its source, dimensions, history, and draw state',
      'c:data--view--alt', function () {
        askDrop();
        sheet(clip);
        var open = sheetWrap;
        var notes = open ? open.querySelectorAll('.sfx-tv-note') : [];
        var note = notes.length ? notes[notes.length - 1] : null;
        inspect(clip, function (text) {
          if (note) note.textContent = String(text || '');
        }, open);
      });
    answer('Like', 'Raise this clip in the station\'s selection weight',
      'c:thumbs-up', function () {
        weigh(clip, true, say);
      });
    answer('Add to sampler', 'Put it on the next free sampler pad',
      'c:music--add', function () {
        toPad(clip, say);
      });
    var close = document.createElement('button');
    close.type = 'button'; close.className = 'sfx-tv-ask-close';
    close.textContent = 'Close';
    close.addEventListener('click', function (ev) {
      ev.stopPropagation(); askDrop();
    });
    wrap.appendChild(q);
    wrap.appendChild(summary);
    wrap.appendChild(list);
    wrap.appendChild(close);
    /* A press on the bubble is not a press on the picture. */
    wrap.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    document.body.appendChild(wrap);
    askWrap = wrap;
  }

  function askDrop() {
    var wrap = askWrap;
    askWrap = null;
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err) { /* already gone */ }
  }

  function parodySourceUrl(clip) {
    var url = String((clip && clip.url) || '');
    if (/^(https?:|blob:|data:)/i.test(url)) return url;
    return base.replace(/\/+$/, '') + url;
  }

  function parodyCandidates(seed, older) {
    var source = [];
    var seenIds = Object.create(null);
    var add = function (row) {
      var id = clipId(row);
      if (!id || seenIds[id] || !histVideo(row)) return;
      seenIds[id] = 1;
      source.push({id: id, url: String(row.url || ''), video: true,
        sting: String(row.sting || row.name || row.text || id),
        seconds: Number(row.seconds) || 0, ts: Number(row.ts) || 0,
        source_type: String(row.source_type || 'recent'),
        source_generation: String(row.source_generation || '')});
    };
    (older || []).forEach(add);
    hist.forEach(add);
    heard.forEach(add);
    stripRows().forEach(add);
    add(seed);
    return source;
  }

  function parodyClose() {
    var wrap = parodyWrap;
    parodyWrap = null;
    if (parodyQueueTimer) root.clearInterval(parodyQueueTimer);
    parodyQueueTimer = 0;
    try {
      if (root.PineTalkDot && typeof root.PineTalkDot.cancelCapture === 'function') {
        root.PineTalkDot.cancelCapture();
      }
    } catch (err) { /* the microphone is already closed */ }
    try { if (parodyDictationRelease) parodyDictationRelease(); }
    catch (err1) { /* the audio restore is best effort during teardown */ }
    parodyDictationRelease = null;
    try { if (parodyVideo) { parodyVideo.pause(); parodyVideo.removeAttribute('src'); parodyVideo.load(); } }
    catch (err2) { /* already gone */ }
    parodyVideo = null;
    try { if (parodyCover && parodyCover.destroy) parodyCover.destroy(); }
    catch (err3) { /* already gone */ }
    parodyCover = null;
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err4) { /* already gone */ }
    if (parodyOwnsSurface) {
      parodyOwnsSurface = false;
      surfaceDown(false);
    }
  }

  function parodyQuoted(value) {
    var out = [], re = /"([^"\n]+)"|\u201c([^\u201d\n]+)\u201d/g, match;
    while ((match = re.exec(String(value || ''))) !== null) {
      var line = String(match[1] || match[2] || '').replace(/\s+/g, ' ').trim();
      if (line) out.push(line);
    }
    return out.join(' ').slice(0, 800);
  }

  function parodyGenerationNotice(got, signatures) {
    if (!got || !(got.files || []).length) return;
    if (typeof root.pineGenerationNotice === 'function') {
      root.pineGenerationNotice(got);
      return;
    }
    var file = got.files[0];
    var token = signatures && signatures[file];
    var url = base.replace(/\/+$/, '') + '/api/generations/image/'
      + encodeURIComponent(file) + (token ? '?t=' + encodeURIComponent(token) : '');
    var toast = document.createElement('button');
    toast.type = 'button'; toast.className = 'sfx-tv-render-toast sfx-tv';
    var thumb = document.createElement(/\.(mp4|m4v|webm|mov|mkv|ogv)$/i.test(file)
      ? 'video' : 'img');
    thumb.className = 'sfx-tv-render-thumb';
    if (thumb.tagName === 'VIDEO') {
      thumb.muted = true; thumb.playsInline = true; thumb.preload = 'metadata';
    }
    thumb.src = url;
    var words = document.createElement('span');
    var title = document.createElement('b'); title.textContent = 'Pine Box stinger ready';
    var detail = document.createElement('small');
    detail.textContent = String(got.request || got.tags || file).slice(0, 120);
    words.appendChild(title); words.appendChild(detail);
    toast.appendChild(thumb); toast.appendChild(words);
    toast.addEventListener('click', function () {
      toast.remove(); parodyResultOpen(got, url);
    });
    document.body.appendChild(toast);
    setTimeout(function () { if (toast.parentNode) toast.remove(); }, 20000);
    try {
      post('/api/notifications', {kind: 'video', title: 'Pine Box stinger ready',
        subtitle: detail.textContent, ref: {file: file, gen: got}});
    } catch (err) { /* the visible notification still works */ }
  }

  function parodyWatch(promptId, status) {
    if (!promptId || parodyPolling[promptId]) return;
    parodyPolling[promptId] = true;
    var tries = 0;
    var look = function () {
      tries += 1;
      var bridge = api();
      if (!bridge || !bridge.get) { delete parodyPolling[promptId]; return; }
      bridge.get('/api/generations?limit=120').then(function (book) {
        var rows = (book && book.generations) || [];
        var row = null;
        for (var i = 0; i < rows.length; i += 1) {
          if (String(rows[i].prompt_id || '') === String(promptId)) { row = rows[i]; break; }
        }
        if (row && row.status === 'done' && (row.files || []).length) {
          delete parodyPolling[promptId];
          if (status && status.isConnected) status.textContent = 'Stinger ready.';
          parodyGenerationNotice(row, book.sig || {});
          return;
        }
        if (row && /^(failed|error|cancelled)$/i.test(String(row.status || ''))) {
          delete parodyPolling[promptId];
          if (status && status.isConnected) status.textContent = 'Generation failed: '
            + String(row.error || row.status);
          return;
        }
        if (tries >= 240) {
          delete parodyPolling[promptId];
          if (status && status.isConnected) status.textContent = 'Still rendering; the notification will appear in the gallery.';
          return;
        }
        setTimeout(look, 5000);
      }, function () {
        if (tries < 240) setTimeout(look, 7000);
        else delete parodyPolling[promptId];
      });
    };
    setTimeout(look, 3500);
  }

  function parodyResultOpen(generation, url) {
    parodyClose();
    var shade = document.createElement('div');
    shade.className = 'sfx-tv-parody-shade sfx-tv';
    var box = document.createElement('section');
    box.className = 'sfx-tv-parody sfx-tv-result';
    var head = document.createElement('header');
    var title = document.createElement('b'); title.textContent = 'Generated Pine Box FM stinger';
    var close = document.createElement('button'); close.type = 'button'; close.textContent = 'Close';
    head.appendChild(title); head.appendChild(close);
    var media = document.createElement('video');
    media.controls = true; media.playsInline = true; media.src = url;
    var prompt = document.createElement('textarea');
    prompt.value = String(generation.tags || generation.request || '');
    var status = document.createElement('div'); status.className = 'sfx-tv-parody-status';
    var actions = document.createElement('div'); actions.className = 'sfx-tv-parody-actions';
    var action = function (label, go) {
      var b = document.createElement('button'); b.type = 'button'; b.textContent = label;
      b.addEventListener('click', go); actions.appendChild(b); return b;
    };
    action('Analyze', function () {
      status.textContent = 'Examining the generated media...';
      post('/api/comfy/workshop/analyze/' + encodeURIComponent(generation.prompt_id), {})
        .then(function (got) { status.textContent = String(got.analysis || 'No analysis returned.'); },
          function (err) { status.textContent = String((err && err.message) || err); });
    });
    action('Regenerate', function () {
      status.textContent = 'Submitting another take...';
      post('/api/comfy/workshop/variant', {prompt_id: generation.prompt_id,
        prompt: prompt.value.trim(), use_result: false}).then(function (got) {
          status.textContent = 'Variant queued.'; parodyWatch(got.prompt_id, status);
        }, function (err) { status.textContent = String((err && err.message) || err); });
    });
    action('Add to DJ topic', function () {
      var text = 'Discuss this Pine Box FM stinger: ' + prompt.value.trim()
        + ' Generated media: ' + String((generation.files || [])[0] || '');
      post('/api/dj/topics', {text: text, kind: 'media', next: false}).then(
        function () { status.textContent = 'Added to the DJs\' topic bank.'; },
        function (err) { status.textContent = String((err && err.message) || err); });
    });
    var del = action('Delete', function () {
      if (del.dataset.sure !== '1') {
        del.dataset.sure = '1'; del.textContent = 'Delete for good?'; return;
      }
      var bridge = api();
      if (!bridge || !bridge.del) { status.textContent = 'No delete road from this screen.'; return; }
      bridge.del('/api/generations/image/'
        + encodeURIComponent(String((generation.files || [])[0] || ''))).then(
          function () { shade.remove(); },
          function (err) { status.textContent = String((err && err.message) || err); });
    });
    del.className = 'bad';
    close.addEventListener('click', function () { shade.remove(); });
    box.appendChild(head); box.appendChild(media); box.appendChild(prompt);
    box.appendChild(actions); box.appendChild(status); shade.appendChild(box);
    shade.addEventListener('click', function (ev) { if (ev.target === shade) shade.remove(); });
    document.body.appendChild(shade);
  }

  function parodyOpen(seed, keepSurfaceDown) {
    parodyClose();
    if (keepSurfaceDown) {
      surfaceDown(true);
      parodyOwnsSurface = true;
    }
    var shade = document.createElement('div');
    shade.className = 'sfx-tv-parody-shade sfx-tv';
    var box = document.createElement('section');
    box.className = 'sfx-tv-parody';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Generate a Pine Box FM parody stinger');
    var head = document.createElement('header');
    var title = document.createElement('b'); title.textContent = 'Generate parody stinger';
    var close = document.createElement('button'); close.type = 'button'; close.textContent = 'Close';
    head.appendChild(title); head.appendChild(close);
    var stage = document.createElement('div');
    stage.className = 'sfx-tv-parody-stage is-loading';
    var source = document.createElement('video');
    source.controls = true; source.playsInline = true; source.preload = 'metadata';
    stage.appendChild(source); parodyVideo = source;
    var nav = document.createElement('div'); nav.className = 'sfx-tv-parody-nav';
    var prev = document.createElement('button'); prev.type = 'button'; prev.textContent = 'Previous';
    var label = document.createElement('span');
    var next = document.createElement('button'); next.type = 'button'; next.textContent = 'Next';
    nav.appendChild(prev); nav.appendChild(label); nav.appendChild(next);
    var trim = document.createElement('div'); trim.className = 'sfx-tv-parody-trim';
    trim.hidden = true;
    var trimSpan = document.createElement('div'); trimSpan.className = 'sfx-tv-parody-trim-span';
    var trimRow = function (name) {
      var row = document.createElement('label'); row.className = 'sfx-tv-parody-trim-row';
      var title = document.createElement('span'); title.textContent = name;
      var slider = document.createElement('input'); slider.type = 'range';
      slider.min = '0'; slider.step = '1';
      slider.setAttribute('aria-label', 'Trim ' + name.toLowerCase() + ' point');
      var value = document.createElement('output'); value.textContent = '0:00.0';
      row.appendChild(title); row.appendChild(slider); row.appendChild(value);
      trim.appendChild(row);
      return {slider: slider, value: value};
    };
    var inControl = trimRow('In');
    var outControl = trimRow('Out');
    trim.appendChild(trimSpan);
    var field = document.createElement('textarea');
    field.placeholder = 'Describe the Pine Box FM parody or dictate it with the microphone...';
    var controls = document.createElement('div'); controls.className = 'sfx-tv-parody-actions';
    var mic = document.createElement('button'); mic.type = 'button'; mic.className = 'sfx-tv-parody-mic';
    mic.title = 'Dictate the H3 prompt'; mic.setAttribute('aria-label', mic.title);
    mic.innerHTML = (typeof root.pineIcon === 'function'
      ? (root.pineIcon('c:microphone', 'Dictate prompt') || '') : '') || 'MIC';
    var send = document.createElement('button'); send.type = 'button';
    send.className = 'primary'; send.textContent = 'Send to H3';
    var listening = document.createElement('div');
    listening.className = 'sfx-tv-parody-listening';
    listening.hidden = true; listening.setAttribute('role', 'status');
    listening.setAttribute('aria-live', 'polite');
    var listeningPulse = document.createElement('i');
    listeningPulse.setAttribute('aria-hidden', 'true');
    var listeningWords = document.createElement('span');
    listeningWords.textContent = 'Listening to your dictation. Device audio is muted.';
    listening.appendChild(listeningPulse); listening.appendChild(listeningWords);
    controls.appendChild(mic); controls.appendChild(listening); controls.appendChild(send);
    var status = document.createElement('div'); status.className = 'sfx-tv-parody-status';
    status.setAttribute('role', 'status');
    var queuePanel = document.createElement('div'); queuePanel.className = 'sfx-tv-parody-queue';
    var queueTitle = document.createElement('b'); queueTitle.textContent = 'Stinger queue';
    var queueCurrent = document.createElement('div');
    queueCurrent.className = 'sfx-tv-parody-queue-current';
    var queueCause = document.createElement('div');
    queueCause.className = 'sfx-tv-parody-queue-cause';
    var queueActions = document.createElement('div');
    queueActions.className = 'sfx-tv-parody-queue-actions';
    var freeIdle = document.createElement('button'); freeIdle.type = 'button';
    freeIdle.textContent = 'Free idle Comfy cache';
    freeIdle.title = 'Only unloads when ComfyUI is not rendering';
    var relieveOne = document.createElement('button'); relieveOne.type = 'button';
    relieveOne.textContent = 'Host cache relief';
    relieveOne.title = 'Run pressure relief tier 1; never tier 3 or active voice engines';
    queueActions.appendChild(freeIdle); queueActions.appendChild(relieveOne);
    var queueHistory = document.createElement('details');
    queueHistory.className = 'sfx-tv-parody-queue-history';
    var historySummary = document.createElement('summary');
    historySummary.textContent = 'Prior stingers';
    var historyRows = document.createElement('div');
    queueHistory.appendChild(historySummary); queueHistory.appendChild(historyRows);
    queuePanel.appendChild(queueTitle); queuePanel.appendChild(queueCurrent);
    queuePanel.appendChild(queueCause); queuePanel.appendChild(queueActions);
    queuePanel.appendChild(queueHistory);
    box.appendChild(head); box.appendChild(stage); box.appendChild(nav); box.appendChild(trim);
    box.appendChild(field); box.appendChild(controls); box.appendChild(status);
    box.appendChild(queuePanel);
    shade.appendChild(box); document.body.appendChild(shade); parodyWrap = shade;

    var queueReading = false;
    var refreshQueue = function () {
      var bridge = api();
      if (queueReading || !bridge || !bridge.get) return;
      queueReading = true;
      bridge.get('/api/comfy/workshop/parody-queue').then(function (state) {
        if (parodyWrap !== shade) return;
        var jobs = (state && state.jobs) || [];
        var active = jobs.find(function (job) { return job.status === 'running'; });
        var pending = jobs.filter(function (job) { return job.status === 'queued'; });
        var current = active || pending[pending.length - 1];
        var admission = (state && state.admission) || {};
        var free = Number(admission.available_gb);
        var needed = Number(admission.required_gb);
        var memory = admission.available_gb != null && isFinite(free)
          && isFinite(needed) && needed > 0;
        queueCause.textContent = (memory ? free.toFixed(1) + ' GB free / '
          + needed.toFixed(0) + ' GB needed. ' : '') + String(admission.why || '');
        queueActions.hidden = !memory || free >= needed;
        freeIdle.disabled = !!(state && state.live && state.live.busy);
        relieveOne.disabled = freeIdle.disabled;
        if (current) {
          var elapsed = current.started ? Math.max(0, Math.floor(Date.now() / 1000
            - Number(current.started))) : 0;
          queueCurrent.textContent = current.status === 'running'
            ? 'H3 rendering / ' + Math.floor(elapsed / 60) + 'm '
              + String(elapsed % 60).padStart(2, '0') + 's / progress indeterminate'
              + (pending.length ? ' / ' + pending.length + ' waiting' : '')
            : 'Waiting / position ' + String(current.position || 1)
              + ' / ' + pending.length + ' queued';
        } else queueCurrent.textContent = 'No stinger waiting';
        historySummary.textContent = 'Prior stingers (' + jobs.length + ')';
        historyRows.replaceChildren();
        jobs.forEach(function (job) {
          var row = document.createElement('div');
          row.className = 'sfx-tv-parody-queue-row';
          var title = document.createElement('b');
          title.textContent = String(job.direction || 'Parody stinger').slice(0, 110);
          var detail = document.createElement('span');
          var stats = (job.render && job.render.stats) || {};
          var duration = Number(stats.duration_s || (job.finished && job.started
            ? job.finished - job.started : 0));
          detail.textContent = String(job.status) + (job.position ? ' / #' + job.position : '')
            + (job.model ? ' / ' + job.model : '')
            + (job.frames ? ' / ' + job.frames + ' frames' : '')
            + (duration > 0 ? ' / ' + Math.round(duration) + 's' : '')
            + (job.reason ? ' / ' + job.reason : '');
          row.appendChild(title); row.appendChild(detail); historyRows.appendChild(row);
          if (job.status === 'running' && job.prompt_id) parodyWatch(job.prompt_id, status);
        });
      }, function (err) {
        if (parodyWrap === shade) queueCause.textContent = 'Queue status unavailable: '
          + String((err && err.message) || err);
      }).then(function () { queueReading = false; });
    };
    var relief = function (button, path, body) {
      button.disabled = true;
      status.textContent = 'Asking the host to free idle resources...';
      post(path, body).then(function (got) {
        status.textContent = String((got && (got.say || got.why)) ||
          (got && got.done ? 'Idle cache freed.' : 'No resources were freed.'));
        refreshQueue();
      }, function (err) { status.textContent = String((err && err.message) || err); })
        .then(function () { button.disabled = false; });
    };
    freeIdle.addEventListener('click', function () {
      relief(freeIdle, '/api/comfy/idle/now', {mode: 'free'});
    });
    relieveOne.addEventListener('click', function () {
      relief(relieveOne, '/api/orchestrator/pressure/relieve?tier=1', {});
    });
    refreshQueue();
    parodyQueueTimer = root.setInterval(refreshQueue, 5000);

    var rows = parodyCandidates(seed, []);
    var index = Math.max(0, rows.length - 1);
    var trimById = Object.create(null);
    var trimStart = 0, trimEnd = 0, trimDuration = 0;
    var trimReady = false, trimUsable = false, submitting = false;
    var trimTime = function (tenths) {
      return Math.floor(tenths / 600) + ':'
        + String(Math.floor(tenths / 10) % 60).padStart(2, '0')
        + '.' + (tenths % 10);
    };
    var showTrim = function () {
      inControl.slider.value = String(trimStart);
      outControl.slider.value = String(trimEnd);
      inControl.value.textContent = trimTime(trimStart);
      outControl.value.textContent = trimTime(trimEnd);
      trimSpan.textContent = trimUsable
        ? trimTime(trimEnd - trimStart) + ' selected'
        : 'Short source uses the full clip';
      if (trimUsable && rows[index]) {
        trimById[rows[index].id] = {start: trimStart, end: trimEnd};
      }
    };
    var setTrim = function () {
      var seconds = Number(source.duration);
      if (!isFinite(seconds) || seconds <= 0) {
        status.textContent = 'The source duration could not be read.';
        return;
      }
      trimDuration = Math.floor(seconds * 10);
      trimUsable = trimDuration >= 22;
      var saved = rows[index] && trimById[rows[index].id];
      trimStart = trimUsable && saved ? Math.max(0, Math.min(saved.start, trimDuration - 22)) : 0;
      trimEnd = trimUsable && saved
        ? Math.max(trimStart + 22, Math.min(saved.end, trimDuration, trimStart + 150))
        : Math.min(trimDuration, 150);
      inControl.slider.max = String(trimDuration);
      outControl.slider.max = String(trimDuration);
      inControl.slider.disabled = !trimUsable;
      outControl.slider.disabled = !trimUsable;
      trim.hidden = false;
      trimReady = true;
      send.disabled = submitting;
      showTrim();
      if (trimUsable) source.currentTime = trimStart / 10;
    };
    var wanted = clipId(seed);
    for (var i = 0; i < rows.length; i += 1) if (rows[i].id === wanted) index = i;
    wireVideoRadial(source, function () { return rows[index] || seed; });
    /* The browser's empty-video badge is itself the stretched graphic the
       assembly cover replaces. Keep an independent CSS gate as well as the
       Three.js cover: if the cover script is late or a source errors before
       it can build, the native badge still never receives one painted frame. */
    var previewWaiting = function () { stage.classList.add('is-loading'); };
    var previewReady = function () {
      if (source.readyState >= 2 && source.videoWidth > 0) {
        stage.classList.remove('is-loading');
      } else previewWaiting();
    };
    ['loadstart', 'emptied', 'waiting', 'stalled', 'error', 'abort']
      .forEach(function (name) { source.addEventListener(name, previewWaiting); });
    ['loadeddata', 'playing']
      .forEach(function (name) { source.addEventListener(name, previewReady); });
    source.addEventListener('loadedmetadata', setTrim);
    inControl.slider.addEventListener('input', function () {
      if (!trimUsable) return;
      trimStart = Math.max(0, Math.min(Number(inControl.slider.value), trimDuration - 22));
      trimEnd = Math.max(trimStart + 22, Math.min(trimEnd, trimStart + 150, trimDuration));
      showTrim(); source.currentTime = trimStart / 10;
    });
    outControl.slider.addEventListener('input', function () {
      if (!trimUsable) return;
      trimEnd = Math.max(trimStart + 22,
        Math.min(Number(outControl.slider.value), trimStart + 150, trimDuration));
      showTrim(); source.currentTime = Math.max(trimStart, trimEnd - 1) / 10;
    });
    source.addEventListener('play', function () {
      if (trimUsable && (source.currentTime < trimStart / 10 ||
          source.currentTime >= trimEnd / 10)) source.currentTime = trimStart / 10;
    });
    source.addEventListener('timeupdate', function () {
      if (trimUsable && !source.paused && source.currentTime >= trimEnd / 10 - 0.03) {
        source.pause(); source.currentTime = trimStart / 10;
      }
    });
    var paint = function () {
      if (!rows.length) { label.textContent = 'No video source'; send.disabled = true; return; }
      index = Math.max(0, Math.min(rows.length - 1, index));
      var row = rows[index];
      label.textContent = (index + 1) + ' of ' + rows.length + ' - ' + row.sting;
      prev.disabled = index <= 0; next.disabled = index >= rows.length - 1;
      trimReady = false; trimUsable = false; trim.hidden = true;
      send.disabled = true;
      previewWaiting();
      try { source.pause(); } catch (err) { /* changing source */ }
      try { if (parodyCover && parodyCover.destroy) parodyCover.destroy(); } catch (err2) {}
      parodyCover = null;
      if (root.PineWallTransition && typeof root.PineWallTransition.cover === 'function') {
        parodyCover = root.PineWallTransition.cover(source, {container: stage,
          className: 'pine-video-assembly', label: 'SOURCE VIDEO ASSEMBLING', zIndex: 3});
      }
      source.removeAttribute('poster');
      source.src = parodySourceUrl(row); source.load();
    };
    prev.addEventListener('click', function () { if (index > 0) { index -= 1; paint(); } });
    next.addEventListener('click', function () { if (index + 1 < rows.length) { index += 1; paint(); } });
    close.addEventListener('click', parodyClose);
    shade.addEventListener('click', function (ev) { if (ev.target === shade) parodyClose(); });
    var dictating = false;
    var finishWhenReady = false;
    var pressStartedAt = 0;
    var pressWasListening = false;
    var sourceWasMuted = false;
    var wallState = null;
    var parseWall = function (raw) {
      try { return typeof raw === 'string' ? JSON.parse(raw) : raw; }
      catch (err) { return null; }
    };
    var dictationUi = function (mode) {
      var on = mode === 'listening' || mode === 'processing';
      mic.classList.toggle('listening', on);
      mic.classList.toggle('processing', mode === 'processing');
      mic.setAttribute('aria-pressed', on ? 'true' : 'false');
      listening.hidden = !on;
      listening.classList.toggle('processing', mode === 'processing');
      listeningWords.textContent = mode === 'processing'
        ? 'Finishing your dictation. Device audio is still muted.'
        : 'Listening to your dictation. Device audio is muted.';
      box.classList.toggle('is-dictating', on);
    };
    var releaseDictation = function () {
      if (!dictating) { dictationUi('idle'); return; }
      dictating = false;
      dictationUi('idle');
      try {
        if (root.PineDuck && typeof root.PineDuck.release === 'function') {
          root.PineDuck.release('sfx-parody-dictation');
        }
      } catch (err) { /* the level bus may have left with the view */ }
      try { source.muted = sourceWasMuted; } catch (err2) { /* source gone */ }
      if (root.pineLevels && typeof root.pineLevels.refresh === 'function') {
        try { root.pineLevels.refresh('video'); } catch (err3) { /* no wall */ }
      } else if (wallState && typeof wallState.then === 'function') {
        wallState.then(function (raw) {
          var old = parseWall(raw);
          if (old && isFinite(Number(old.level))) {
            wallAsk('level', {level: Number(old.level)});
          }
        })['catch'](function () { /* no native wall to restore */ });
      }
    };
    parodyDictationRelease = releaseDictation;
    var stopDictation = function () {
      if (!dictating) return;
      var dot = root.PineTalkDot;
      dictationUi('processing');
      if (dot && typeof dot.state === 'function' && dot.state() === 'listening') {
        if (typeof dot.finish === 'function') dot.finish();
      } else finishWhenReady = true;
    };
    var startDictation = function () {
      var dot = root.PineTalkDot;
      if (!dot || typeof dot.captureNext !== 'function') {
        status.textContent = 'The microphone is not available on this screen.'; return;
      }
      dictating = true;
      finishWhenReady = false;
      sourceWasMuted = !!source.muted;
      source.muted = true;
      if (root.PineDuck && typeof root.PineDuck.hold === 'function') {
        root.PineDuck.hold('sfx-parody-dictation', 0, box);
      }
      wallState = wallAsk('state');
      wallAsk('level', {level: 0});
      dictationUi('listening');
      status.textContent = 'Listening - tap the microphone when finished.';
      try {
        var started = dot.captureNext(function (text) {
          releaseDictation();
          if (parodyWrap !== shade) return;
          var words = String(text || '').trim();
          if (words) {
            field.value = [field.value.trimEnd(), words].filter(Boolean).join(' ');
            field.dispatchEvent(new Event('input', {bubbles: true}));
            field.focus({preventScroll: true});
            if (field.setSelectionRange) field.setSelectionRange(field.value.length, field.value.length);
          }
          status.textContent = words ? 'Transcript added to prompt.' : 'Nothing was heard.';
        });
        if (started && started['then']) started.then(function () {
          if (finishWhenReady) {
            finishWhenReady = false;
            if (dot.state && dot.state() === 'listening' && dot.finish) dot.finish();
          }
          setTimeout(function () {
            if (!dictating || !dot.state || dot.state() === 'listening') return;
            releaseDictation();
            status.textContent = 'The microphone did not begin listening.';
          }, 0);
        });
        if (started && started['catch']) started['catch'](function (err) {
          releaseDictation(); status.textContent = String((err && err.message) || err);
        });
      } catch (err) {
        releaseDictation(); status.textContent = String(err.message || err);
      }
    };
    mic.addEventListener('pointerdown', function (event) {
      event.preventDefault();
      pressStartedAt = Date.now();
      pressWasListening = dictating;
      if (dictating) stopDictation(); else startDictation();
      try { if (mic.setPointerCapture) mic.setPointerCapture(event.pointerId); }
      catch (err) { /* the take may have started already */ }
    });
    mic.addEventListener('pointerup', function () {
      if (pressStartedAt && !pressWasListening && Date.now() - pressStartedAt >= 450) {
        stopDictation();
      }
      pressStartedAt = 0;
    });
    mic.addEventListener('pointercancel', function () {
      if (pressStartedAt && !pressWasListening && Date.now() - pressStartedAt >= 450) {
        stopDictation();
      }
      pressStartedAt = 0;
    });
    mic.addEventListener('click', function (event) {
      if (event.detail !== 0) return;
      if (dictating) stopDictation(); else startDictation();
    });
    send.addEventListener('click', function () {
      if (!rows.length) return;
      if (!trimReady) { status.textContent = 'Wait for the reference video to load.'; return; }
      var direction = field.value.trim();
      if (!direction) { status.textContent = 'Dictate or type the parody direction first.'; field.focus(); return; }
      var chosen = rows[index];
      submitting = true;
      send.disabled = true; status.textContent = 'Preparing ' + chosen.sting + ' for H3...';
      var prompt = 'Create a short Pine Box FM radio stinger as a parody of the reference video. '
        + 'Keep its recognizable composition and performance while making it feel native to Pine Box FM. '
        + 'Follow this direction: ' + direction;
      var body = {mode: 'reference', purpose: 'parody_stinger',
        source: chosen.id, source_type: chosen.source_type || 'recent',
        source_generation: chosen.source_generation || '', prompt: prompt,
        speech: parodyQuoted(direction), frames: 73, steps: 4, air_it: false};
      if (trimUsable) {
        body.trim_in_s = trimStart / 10;
        body.trim_out_s = trimEnd / 10;
      }
      post('/api/comfy/workshop', body)
        .then(function (got) {
          status.textContent = got && got.queue_id
            ? 'Stinger saved in the server queue. You can close this window.'
            : 'Submitted to H3.';
          if (got && got.prompt_id) parodyWatch(got.prompt_id, status);
          refreshQueue(); submitting = false; send.disabled = !trimReady;
        }, function (err) {
          submitting = false; send.disabled = !trimReady;
          status.textContent = String((err && err.message) || err);
        });
    });
    paint();

    var bridge = api();
    if (bridge && bridge.get) bridge.get('/api/sfx/history?limit=120').then(function (got) {
      if (parodyWrap !== shade) return;
      var old = ((got && got.rows) || []).slice().reverse().map(function (row) {
        return {id: String(row.id || ''), url: String(row.url || ''),
          name: String(row.name || ''), sting: String(row.name || row.id || ''),
          video: histVideo(row), ts: Number(row.ts) || 0,
          source_type: 'recent'};
      });
      var selected = rows[index] && rows[index].id;
      rows = parodyCandidates(seed, old);
      index = Math.max(0, rows.length - 1);
      for (var n = 0; n < rows.length; n += 1) if (rows[n].id === selected) index = n;
      paint();
    }, function () { /* the current and in-memory history remain usable */ });
  }

  function radialClose(releaseWall, resumeMedia) {
    var wrap = radialWrap;
    radialWrap = null;
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err) { /* already gone */ }
    var media = radialMedia;
    var shouldResume = radialMediaWasPlaying && resumeMedia !== false;
    radialMedia = null; radialMediaWasPlaying = false;
    if (media && shouldResume) {
      try {
        var started = media.play();
        if (started && started['catch']) started['catch'](function () {});
      } catch (err2) { /* the popup may have closed */ }
    }
    if (releaseWall !== false) surfaceDown(false);
  }

  function deleteConfirmClose(releaseWall) {
    var wrap = deleteWrap;
    deleteWrap = null;
    if (wrap) {
      var media = wrap.querySelector('video');
      try {
        if (media && media.__pineVideoAssembly) media.__pineVideoAssembly.destroy();
      } catch (coverErr) { /* the transition may already have retired */ }
      try { if (media) { media.pause(); media.removeAttribute('src'); media.load(); } }
      catch (err) { /* already gone */ }
      try { if (wrap.parentNode) wrap.parentNode.removeChild(wrap); }
      catch (err2) { /* already gone */ }
    }
    if (releaseWall !== false) surfaceDown(false);
  }

  function deleteConfirm(clip) {
    radialClose(false, false);
    deleteConfirmClose(false);
    var shade = document.createElement('div');
    shade.className = 'sfx-tv-delete-shade sfx-tv';
    var box = document.createElement('section');
    box.className = 'sfx-tv-delete-confirm';
    box.setAttribute('role', 'alertdialog');
    box.setAttribute('aria-label', 'Confirm permanent video deletion');
    var title = document.createElement('b');
    title.textContent = 'Delete this video permanently?';
    var stage = document.createElement('div');
    stage.className = 'sfx-tv-delete-stage';
    var media = document.createElement('video');
    media.controls = true; media.loop = true; media.muted = true;
    media.playsInline = true; media.preload = 'auto';
    stage.appendChild(media);
    var help = document.createElement('div');
    help.className = 'sfx-tv-delete-help';
    help.textContent = 'Drag left or right across the video to scrub it before deciding.';
    var status = document.createElement('div');
    status.className = 'sfx-tv-parody-status';
    status.textContent = String(clip.sting || clip.text || clipId(clip));
    var actions = document.createElement('div');
    actions.className = 'sfx-tv-parody-actions';
    var cancel = document.createElement('button');
    cancel.type = 'button'; cancel.textContent = 'Cancel';
    var remove = document.createElement('button');
    remove.type = 'button'; remove.className = 'bad';
    remove.textContent = 'Delete permanently';
    actions.appendChild(cancel); actions.appendChild(remove);
    box.appendChild(title); box.appendChild(stage); box.appendChild(help);
    box.appendChild(status); box.appendChild(actions); shade.appendChild(box);
    document.body.appendChild(shade); deleteWrap = shade;
    if (root.PineWallTransition
        && typeof root.PineWallTransition.cover === 'function') {
      root.PineWallTransition.cover(media, {container: stage,
        className: 'sfx-tv-assembly', label: 'VIDEO ASSEMBLING', zIndex: 2});
    }
    media.src = parodySourceUrl(clip);
    try { media.load(); } catch (loadErr) { /* assigning src is sufficient */ }
    var drag = null;
    media.addEventListener('pointerdown', function (ev) {
      if (!isFinite(Number(media.duration)) || Number(media.duration) <= 0) return;
      drag = {x: Number(ev.clientX) || 0, at: Number(media.currentTime) || 0};
      try { media.setPointerCapture(ev.pointerId); } catch (err) {}
    });
    media.addEventListener('pointermove', function (ev) {
      if (!drag || !isFinite(Number(media.duration))) return;
      ev.preventDefault();
      var width = Math.max(80, media.getBoundingClientRect().width || 0);
      var at = drag.at + ((Number(ev.clientX) || 0) - drag.x) / width * media.duration;
      try { media.currentTime = Math.max(0, Math.min(media.duration, at)); }
      catch (err) { /* metadata changed underneath the gesture */ }
    });
    var release = function (ev) {
      if (!drag) return; drag = null;
      try { media.releasePointerCapture(ev.pointerId); } catch (err) {}
    };
    media.addEventListener('pointerup', release);
    media.addEventListener('pointercancel', release);
    cancel.addEventListener('click', function () { deleteConfirmClose(true); });
    shade.addEventListener('click', function (ev) {
      if (ev.target === shade) deleteConfirmClose(true);
    });
    remove.addEventListener('click', function () {
      remove.disabled = true; status.textContent = 'Deleting permanently...';
      var actions = clip && clip.__pineActions;
      if (actions && typeof actions.remove === 'function') {
        try {
          var custom = actions.remove(clip);
          Promise.resolve(custom).then(function () {
            status.textContent = 'Deleted permanently.';
            setTimeout(function () { deleteConfirmClose(true); }, 350);
          }, function (err) {
            remove.disabled = false;
            status.textContent = String((err && err.message) || err);
          });
        } catch (err) {
          remove.disabled = false;
          status.textContent = String((err && err.message) || err);
        }
        return;
      }
      scrap(clip, function (text) { status.textContent = String(text || ''); }, function () {
        withdrawClip(clipId(clip));
        setTimeout(function () { deleteConfirmClose(true); }, 650);
      });
    });
    var started = media.play();
    if (started && started['catch']) started['catch'](function () {});
  }

  function radialOpen(clip, at) {
    if (!clip) return;
    radialClose(false);
    surfaceDown(true);
    radialMedia = clip.__pineVideo || null;
    radialMediaWasPlaying = !!(radialMedia && !radialMedia.paused);
    try { if (radialMedia) radialMedia.pause(); } catch (err) {}
    var shade = document.createElement('div');
    shade.className = 'sfx-tv-radial-shade sfx-tv';
    var menu = document.createElement('div');
    menu.className = 'sfx-tv-radial';
    menu.setAttribute('role', 'menu');
    var W = root.innerWidth || 800, H = root.innerHeight || 600;
    var x = Math.max(112, Math.min(W - 112, Number(at && at.x) || W / 2));
    var y = Math.max(112, Math.min(H - 112, Number(at && at.y) || H / 2));
    menu.style.left = x + 'px'; menu.style.top = y + 'px';
    var note = document.createElement('span');
    note.className = 'sfx-tv-radial-note';
    note.textContent = String(clip.sting || clip.text || 'video');
    menu.appendChild(note);
    var actions = clip.__pineActions || {};
    var item = function (label, iconRef, cls, go) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'sfx-tv-radial-item ' + cls;
      b.title = label; b.setAttribute('aria-label', label);
      b.innerHTML = (typeof root.pineIcon === 'function'
        ? (root.pineIcon(iconRef, label) || '') : '') || label;
      b.addEventListener('click', function (ev) { ev.stopPropagation(); go(); });
      menu.appendChild(b);
    };
    item('Send video to sampler', 'c:audio-console', 'sampler', function () {
      if (typeof actions.sampler === 'function') {
        Promise.resolve(actions.sampler(clip)).then(function (text) {
          note.textContent = String(text || 'Sent to sampler.');
        }, function (err) { note.textContent = String((err && err.message) || err); });
        return;
      }
      toPad(clip, function (text) { note.textContent = String(text || ''); });
    });
    item('Make parody with H3', 'c:microphone', 'parody', function () {
      if (typeof actions.parody === 'function') {
        radialClose(true); actions.parody(clip); return;
      }
      radialClose(false, false); parodyOpen(clip, true);
    });
    item('Examine in depth', 'c:microscope', 'examine', function () {
      if (typeof actions.examine === 'function') {
        radialClose(true); actions.examine(clip); return;
      }
      radialClose(false, false);
      sheet(clip, at || null);
      var open = sheetWrap;
      var notes = open ? open.querySelectorAll('.sfx-tv-note') : [];
      var detail = notes.length ? notes[notes.length - 1] : null;
      inspect(clip, function (text) {
        if (detail) detail.textContent = String(text || '');
      }, open);
    });
    item('Make favorite', 'c:favorite--filled', 'favorite', function () {
      if (typeof actions.favorite === 'function') {
        Promise.resolve(actions.favorite(clip)).then(function (text) {
          note.textContent = String(text || 'Marked as a favorite.');
        }, function (err) { note.textContent = String((err && err.message) || err); });
        return;
      }
      weigh(clip, true, function (text) { note.textContent = String(text || ''); });
    });
    item('Replay clip', 'c:renew', 'replay', function () {
      if (typeof actions.replay === 'function') {
        radialClose(true); actions.replay(clip); return;
      }
      var nativeReplay = wallAsk('replay');
      if (nativeReplay && typeof nativeReplay.then === 'function') {
        radialClose(false);
        nativeReplay.catch(function () { surfaceDown(false); });
        return;
      }
      radialClose(true);
      try {
        var media = clip.__pineVideo || video;
        if (media && isFinite(Number(media.duration))) {
          media.currentTime = 0;
          var started = media.play();
          if (started && started['catch']) started['catch'](function () {});
        } else if (rewind) rewind();
      } catch (err) { if (rewind) rewind(); }
    });
    if (actions.remove !== false) {
      item('Delete permanently', 'c:close--filled', 'delete', function () {
        deleteConfirm(clip);
      });
    }
    shade.appendChild(menu);
    shade.addEventListener('click', function (ev) {
      if (ev.target === shade) radialClose(true);
    });
    document.body.appendChild(shade); radialWrap = shade;
  }

  function wireVideoRadial(media, getClip) {
    if (!media || media.__pineRadialWired) return;
    media.__pineRadialWired = true;
    var held = null, timer = 0;
    var forget = function () {
      if (timer) { clearTimeout(timer); timer = 0; }
      held = null;
    };
    media.addEventListener('pointerdown', function (ev) {
      if (ev.button !== undefined && ev.button !== 0) return;
      held = {x: Number(ev.clientX) || 0, y: Number(ev.clientY) || 0};
      timer = setTimeout(function () {
        timer = 0;
        var at = held; held = null;
        var clip = typeof getClip === 'function' ? getClip() : getClip;
        if (!clip) return;
        clip.__pineVideo = media;
        radialOpen(clip, at);
      }, HOLD_MS);
    });
    media.addEventListener('pointermove', function (ev) {
      if (!held) return;
      if (Math.abs((Number(ev.clientX) || 0) - held.x) > SLOP_PX
          || Math.abs((Number(ev.clientY) || 0) - held.y) > SLOP_PX) forget();
    });
    media.addEventListener('pointerup', forget);
    media.addEventListener('pointercancel', forget);
    media.addEventListener('contextmenu', function (ev) {
      var clip = typeof getClip === 'function' ? getClip() : getClip;
      if (!clip) return;
      ev.preventDefault(); ev.stopPropagation();
      clip.__pineVideo = media;
      radialOpen(clip, {x: ev.clientX, y: ev.clientY});
    });
  }

  function build(name, ready) {      /* #1411: `ready` is a warmed <video> */
    /* #1312: one set at a time, always. A stray from an earlier cut
       would otherwise sit here holding a connection for ever. */
    assemblyDrop();
    try {
      var old = document.querySelectorAll('.sfx-tv');
      for (var i = 0; i < old.length; i += 1) {
        var v = old[i].querySelector('video');
        try { if (v) { v.pause(); levelDrop(v); v.removeAttribute('src'); v.load(); } }
        catch (e2) { /* already gone */ }
        if (old[i].parentNode) old[i].parentNode.removeChild(old[i]);
      }
    } catch (err) { /* nothing to sweep */ }
    /* #1112: a sheet on a swept set is gone with it, and so is any
       finish it was holding. play() installs the new curtain.
       #1184: unless it was on the body, in which case sheetForget()
       takes it down rather than orphaning it. */
    sheetForget(); curtain = null; owed = false;
    var box = readBox();
    host = document.createElement('div');
    /* #1308b: `waiting` until the first frame - see play(). */
    host.className = 'sfx-tv waiting';
    host.id = 'sfxTv';
    host.style.left = Math.round(box.left) + 'px';
    host.style.top = Math.round(box.top) + 'px';
    host.style.width = Math.round(box.width) + 'px';
    host.style.height = Math.round(box.height) + 'px';
    /* #1122: "whenever it pops up" - the toggle the operator left on
       is the way the next set comes on too. The windowed box just laid
       out is what Windowed goes back to. */
    full = false;
    fullBox = null;
    if (fullWanted()) {
      fullBox = {left: box.left, top: box.top, width: box.width, height: box.height};
      full = true;
      host.classList.add('sfx-tv-full');
      host.style.left = '0px';
      host.style.top = '0px';
      host.style.width = '100vw';
      host.style.height = '100vh';
      host.style.borderRadius = '0';
    }
    /* #1306e/#1322: HIGH ENOUGH TO BE SEEN, ON EVERY SURFACE.
     *
     * The stylesheet puts the set at 900. On the kiosk that buried it
     * outright - every injected view floats at z-index 2147483000 - so
     * the set was built, playing and completely invisible. Measured on
     * the tablet: the set on screen at 702,350 with elementFromPoint at
     * its own centre returning `sp-el sp-character`.
     *
     * #1306e lifted the KIOSK only, reasoning that 900 was right in the
     * desktop shell because that shell's top chrome sits at 1000. That
     * reasoning has not held. The shell now carries the same high bands
     * the kiosk does - view-chrome at 2147483200, the hold sheets at
     * 2147483046, the trace console at 2147483004, the SC pop-up at
     * 2147483010, the panel's own 3JS windows at 2147483020 - and the
     * Agent tab is a <webview> with a compositing layer of its own. A
     * set at 900 behind any of those is #1306e's fault again, on the
     * other surface, with nothing on screen to say so.
     *
     * So it climbs on BOTH, and stays UNDER the things that are meant
     * to cover it: the sampler's overlays (2147483030+), the hold
     * sheets (2147483046), the lock screen (2147483050) and the boot
     * splash (2147483100). A locked tablet must never be showing a
     * video through the lock.
     *
     * The stylesheet's 900 is now only the fallback for a surface where
     * an inline style is refused. */
    try {
      host.style.zIndex = '2147483020';
    } catch (err) { /* the stylesheet's own 900 stands */ }

    /* #1309b: NO CHROME. "The video pop-up needs to be just a video.
     * No wasted space, no elements around it... I just want it to pop
     * up as just a video box. Just a video itself."
     *
     * So there is no title bar and no close button. The set closes
     * itself when the clip ends, and the hold sheet carries a Close
     * for a clip somebody wants gone early. `shut` is still handed
     * back so play()'s own wiring is unchanged - it is simply a
     * button nothing ever shows. */
    var shut = document.createElement('button');
    shut.type = 'button';
    shut.hidden = true;

    var screen = document.createElement('div');
    screen.className = 'sfx-tv-screen';
    tube = document.createElement('div');
    tube.className = 'sfx-tv-tube';
    video = ready || document.createElement('video');   /* #1411 */
    video.playsInline = true;
    video.preload = 'auto';
    video.controls = false;
    video.crossOrigin = 'anonymous';
    /* #789/#981: the shell owns live element volume, and the booth monitor
     * switch governs anything tagged pine-live. A sting that skipped the
     * tag would be the one sound in this window nobody could turn down. */
    video.dataset.pineLive = 'voice';
    levelSet(video, level, false);
    tube.appendChild(video);
    var glass = document.createElement('div');
    glass.className = 'sfx-tv-glass';
    var vignette = document.createElement('div');
    vignette.className = 'sfx-tv-vignette';
    var flash = document.createElement('div');
    flash.className = 'sfx-tv-flash';
    screen.appendChild(tube);
    screen.appendChild(glass);
    screen.appendChild(vignette);
    screen.appendChild(flash);
    assemblyBind(video, screen, name);

    /* #1306b: THE PAD ICON, top right of the PICTURE.
     * "an icon to the top right of the video of a small box that if I
     *  tap it, it basically assigns that video that's playing to the
     *  sampler on a available pad." */
    var pad = document.createElement('button');
    pad.type = 'button';
    pad.className = 'sfx-tv-pad';
    pad.title = 'Send this clip to a sampler pad';
    pad.setAttribute('aria-label', 'Send to a sampler pad');
    pad.innerHTML = (typeof root.pineIcon === 'function'
      ? root.pineIcon('c:box', 'Send to a sampler pad') : '') || '\u25a3';
    pad.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var was = pad.getAttribute('data-say') || '';
      toPad(playing, function (text) {
        pad.setAttribute('data-say', String(text || was));
        pad.classList.add('said');
        setTimeout(function () {
          if (pad.isConnected) { pad.classList.remove('said'); }
        }, 2400);
      });
    });
    screen.appendChild(pad);

    /* #1121/#1124: the badge, top left, opposite the pad icon. */
    badge = document.createElement('i');
    badge.className = 'sfx-tv-badge';
    var bs = badge.style;
    bs.position = 'absolute'; bs.left = '8px'; bs.top = '8px'; bs.zIndex = '4';
    bs.display = 'none'; bs.padding = '3px 8px'; bs.borderRadius = '6px';
    bs.border = '1px solid #65c7da'; bs.background = '#0b1116';
    bs.color = '#dfe7ee'; bs.font = 'inherit'; bs.fontSize = '12px';
    bs.fontStyle = 'normal'; bs.lineHeight = '18px'; bs.pointerEvents = 'none';
    badge.hidden = true;
    screen.appendChild(badge);

    /* [#1219] "Show a timeline at the bottom while the animation ... is
       playing." A 4px band along the bottom edge of the picture and a
       small clock in its corner, driven by the tube's own currentTime on
       requestAnimationFrame (tlStart, from the first frame). Inside the
       picture, not around it - #1309b's rule stands. Built with
       createElement, never innerHTML, so the stub DOM the tests run
       this file in sees the same tree a browser does. */
    tl = document.createElement('div');
    tl.className = 'sfx-tv-time';
    tlFill = document.createElement('i');
    tlFill.className = 'sfx-tv-time-fill';
    tlClock = document.createElement('b');
    tlClock.className = 'sfx-tv-time-clock';
    tl.appendChild(tlFill);
    tl.appendChild(tlClock);
    screen.appendChild(tl);

    /* #1121-#1124: THREE GESTURES ON THE PICTURE, TOLD APART.
     *
     *   a TAP        - down and up inside 300 ms, under 8 px of travel -
     *                  opens the sheet, or closes the one that is up.
     *                  "Whenever I tap on the pop-up and it shows the
     *                  menu" (#1124).
     *   a DOUBLE TAP - two taps inside 350 ms - replays the clip from
     *                  its start; each further double tap within a
     *                  couple of seconds adds one more replay (#1121).
     *   a HOLD       - 500 ms down without moving - asks whether the
     *                  clip should go on a sampler pad (#1121). This
     *                  used to open the sheet (#1306b).
     *
     * A single tap's action is DELAYED by the double-tap window and
     * cancelled by a second tap, so a replay never also opens the
     * sheet. The drag is untouched: drag() moves the set on any travel
     * and the press below forgets itself past 8 px, so a real drag is
     * never read as a tap or a hold.
     *
     * WHY THE LISTENERS ARE ON THE HOST AND NOT THE SCREEN. drag()
     * takes pointer capture on the host at pointerdown, and from then
     * the pointer's move, up and cancel are delivered to the host,
     * never to the screen under it. The old hold code listened on the
     * screen and so never heard the release; it only ever worked
     * because a hold does not need one. A tap does. So the host hears
     * everything and asks whether the press began on the picture. */
    var press = null, pressTimer = 0, tapTimer = 0, lastTap = 0;
    var onScreen = function (ev) {
      var t = ev && ev.target;
      if (!t || typeof t.closest !== 'function') return false;
      if (t.closest('button')) return false;
      return !!t.closest('.sfx-tv-screen');
    };
    var forget = function () {
      if (pressTimer) { clearTimeout(pressTimer); pressTimer = 0; }
      press = null;
    };
    var tapped = function () {
      /* One tap, and no second one came: the sheet. */
      if (!host) return;
      if (sheetHeld()) { sheetClose(); return; }
      askDrop();
      if (playing) sheet(playing);
    };
    var doubled = function () {
      /* #1121: the first double tap replays now; the next ones, while
         they keep coming, each owe one more play after this one. */
      askDrop();
      var t = now();
      var soon = lastDouble && (t - lastDouble) < DOUBLE_RUN_MS;
      lastDouble = t;
      if (soon) {
        replays += 1;
        paintBadge();
        return;
      }
      if (rewind) { try { rewind(); } catch (err) { /* it is going */ } }
      paintBadge();
    };
    host.addEventListener('pointerdown', function (ev) {
      if (!onScreen(ev)) { forget(); return; }
      if (ev.button !== undefined && ev.button !== 0) return;
      press = {x: Number(ev.clientX) || 0, y: Number(ev.clientY) || 0, t: now()};
      if (pressTimer) clearTimeout(pressTimer);
      pressTimer = setTimeout(function () {
        pressTimer = 0;
        /* A hold: still down, never moved. Not a tap on release. */
        var heldAt = press;
        press = null;
        if (tapTimer) { clearTimeout(tapTimer); tapTimer = 0; }
        if (playing) radialOpen(playing, heldAt);
      }, HOLD_MS);
    });
    host.addEventListener('pointermove', function (ev) {
      if (!press) return;
      if (Math.abs((Number(ev.clientX) || 0) - press.x) > SLOP_PX
          || Math.abs((Number(ev.clientY) || 0) - press.y) > SLOP_PX) {
        forget();
      }
    });
    host.addEventListener('pointerup', function () {
      var was = press;
      forget();
      if (!was || now() - was.t >= TAP_MS) return;
      var t = now();
      if (tapTimer && (t - lastTap) < DOUBLE_MS) {
        clearTimeout(tapTimer); tapTimer = 0;
        lastTap = 0;
        doubled();
        return;
      }
      lastTap = t;
      if (tapTimer) clearTimeout(tapTimer);
      tapTimer = setTimeout(function () { tapTimer = 0; tapped(); }, DOUBLE_MS);
    });
    host.addEventListener('pointercancel', forget);

    /* 2026-09-14: "I'm not able to right click it and have an option to
     * full screen it." On the desk a right-click is the menu gesture, so
     * it opens the same sheet a tap opens (and closes an open one). */
    host.addEventListener('contextmenu', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (sheetHeld()) { sheetClose(); return; }
      if (playing) sheet(playing);
    });

    if (veiled) host.style.visibility = 'hidden';   /* 2026-09-14: the listen view has it */
    host.appendChild(screen);
    grip(host);
    /* A sibling of <main>, never inside a view: that is the whole reason
     * it survives a tab change. */
    document.body.appendChild(host);
    /* #1309b: the head WAS the drag handle, so the window itself is
       now the handle. drag() already ignores a pointerdown on a
       button, and the hold that opens the sheet cancels itself the
       moment the pointer wanders - so a small press opens the sheet
       and a real drag moves the set. */
    drag(host, host);
    /* [#1212] The slot needs them again on the next seam, and building a
       second set to get at them is the whole thing being avoided. */
    host.__parts = {shut: shut, flash: flash};
    return host.__parts;
  }

  /* [#1212] THE HAND-OVER THAT MOVES NOTHING.
   *
   * The warm element (#1411) is already inside the tube on screen, hidden
   * at opacity 0 (see warmPark). A seam promotes it where it stands: the
   * outgoing element is silenced, stripped and removed, the incoming one
   * loses its hiding style, and the host, the glass, the vignette, the
   * badge, the pad icon and every gesture wired in build() are untouched
   * because nothing about them changed.
   *
   * Measured against the alternatives: rebuilding the host cost 187-264 ms
   * on two joins in thirteen; moving the element between parents cost ~40
   * ms on every join; this costs 4-23 ms (median 18) and has no tail. A
   * <video> whose parent does not change keeps its decoder.
   *
   * A FRESH `shut`, because play() adds a click listener to it on every
   * clip and the real one is a hidden button nothing ever presses - one
   * per clip for the life of an endless set is a leak. `flash` is handed
   * back as it is: it is only touched on the NON-seam reveal. */
  function slotSwap(ready) {
    var old = video;
    try {
      ready.removeAttribute('data-pine-warm');
      ready.removeAttribute('style');
    } catch (err) { /* it is still the picture */ }
    video = ready;
    assemblyBind(video, host && host.querySelector('.sfx-tv-screen'),
      playing && (playing.sting || playing.text));
    try { host.classList.remove('waiting'); } catch (err) { /* already off */ }
    try {
      if (old && old !== ready) {
        old.pause(); levelDrop(old); old.removeAttribute('src'); old.load();
        if (old.parentNode) old.parentNode.removeChild(old);
      }
    } catch (err) { /* #1147: src first, node second - both tried */ }
    return {shut: document.createElement('button'), flash: host.__parts.flash};
  }

  /* `mine` is the <video> the caller believes is on screen. Every timer
   * below outlives the clip that armed it - the watchdog by twelve
   * seconds - so a teardown that trusted the module's own reference
   * would either throw on a set already gone or tear down the NEXT
   * clip's set on behalf of a dead one. Measured as a TypeError every
   * twelve seconds after the first clip, in a renderer with no console
   * anybody was reading. */
  function teardown(mine) {
    if (mine && video && video !== mine) return;   // a newer set owns the screen
    floorRelease('tube');                          // [#1214] the mouth is free
    assemblyDrop();
    var going = mine || video;
    if (going && going.__pineReceiptClose) going.__pineReceiptClose();
    /* Removing a <video> from the document does NOT stop it, so the src
     * goes first and the node second. */
    try { if (going) { going.pause(); levelDrop(going); going.removeAttribute('src'); going.load(); } }
    catch (err) {}
    try { if (host && host.parentNode) host.parentNode.removeChild(host); }
    catch (err) {}
    /* #1312: and anything an earlier tangle left attached. */
    try {
      var stray = document.querySelectorAll('.sfx-tv');
      for (var i = 0; i < stray.length; i += 1) {
        var v = stray[i].querySelector('video');
        try { if (v) { v.pause(); levelDrop(v); v.removeAttribute('src'); v.load(); } }
        catch (e2) { /* already gone */ }
        if (stray[i].parentNode) stray[i].parentNode.removeChild(stray[i]);
      }
    } catch (err) { /* nothing stray */ }
    /* [#1212] the warm tube lives INSIDE the host now, so a host that has
       gone takes it with it - a detached element has no decoder and must be
       warmed again in the next tube rather than handed over dead. Both
       teardown() and teardownNow() need it, which is why this is one edit
       asserted against both of them. */
    try { if (warm && warm.el && !document.contains(warm.el)) warmDrop(); }
    catch (err) { /* it will be replaced on the next warmUp */ }
    host = video = tube = null;
    sheetForget(); curtain = null; owed = false;        /* #1112 / #1184 */
    rewind = null; badge = null; askWrap = null;        /* #1121 */
    tlStop(); tl = tlFill = tlClock = null;             /* [#1219] */
    showing = false;
    setTimeout(next, 120);
  }

  /* #1306b: down NOW, for a cut. teardown() is the polite version and
   * schedules next(); this one leaves the queue alone because its
   * caller is about to put something in the tube itself. */
  /* #1312: EVERY SET IN THE DOCUMENT, NOT THE ONE WE THINK IS OURS.
   *
   * This released `video` and `host` - the module's own references -
   * which is precisely the mistake teardown(mine) was written to
   * avoid, and under rapid cutting it orphans sets: cut() tears down,
   * play() installs new references, and a host from a moment ago is
   * left ATTACHED with a <video> still in NETWORK_LOADING.
   *
   * Each orphan holds an HTTP connection open. A WebView allows about
   * six per host, and this page already spends several on the music
   * player and the voice elements - so after a few taps there were
   * none left and EVERY request hung. Measured on the tablet: two
   * orphaned videos at net=2 ready=0, and from inside the page a
   * fetch of /api/pulse never returning, while the same URL answered
   * the desk in 0.02s. That is the whole of "I tap the icon and no
   * video pops up": the picture could not be fetched because the
   * pictures before it had never let go.
   *
   * Sweeping the document by class cannot orphan anything, however
   * the references got tangled. Removing a <video> does not stop it,
   * so the src goes first and the node second - #1147's rule. */
  function teardownNow() {
    if (video && video.__pineReceiptClose) video.__pineReceiptClose();
    assemblyDrop();
    var all = document.querySelectorAll('.sfx-tv');
    for (var i = 0; i < all.length; i += 1) {
      var v = all[i].querySelector('video');
      try { if (v) { v.pause(); levelDrop(v); v.removeAttribute('src'); v.load(); } }
      catch (err) { /* already gone */ }
      try { if (all[i].parentNode) all[i].parentNode.removeChild(all[i]); }
      catch (err) { /* already gone */ }
    }
    /* [#1212] the warm tube lives INSIDE the host now, so a host that has
       gone takes it with it - a detached element has no decoder and must be
       warmed again in the next tube rather than handed over dead. Both
       teardown() and teardownNow() need it, which is why this is one edit
       asserted against both of them. */
    try { if (warm && warm.el && !document.contains(warm.el)) warmDrop(); }
    catch (err) { /* it will be replaced on the next warmUp */ }
    host = video = tube = null;
    sheetForget(); curtain = null; owed = false;        /* #1112 / #1184 */
    rewind = null; badge = null; askWrap = null;        /* #1121 */
    tlStop(); tl = tlFill = tlClock = null;             /* [#1219] */
    showing = false;
  }

  /* [#1214] THE ARBITER: one SFX clip sounds at a time on a page.
   *
   * Every road that can put an SFX picture on a page has its own tube -
   * this set, the panel's twin (djVideoTv) in the same document on the
   * tablet, the tune-in page's gallery stage, a sampler pad - and each
   * stops only what it started. build() sweeps '.sfx-tv' hosts and
   * teardown() the one it believes is on screen; a <video> that left the
   * document is still playing (#1147's rule), and a page that loaded two
   * roads had two soundtracks with nothing on it that could hear both.
   *
   * So there is ONE floor and every road claims it. Claiming hushes
   * everything else that is an SFX picture AND audible - paused and
   * muted, src left alone so its own road can resume it - and counts it,
   * so the number is on the desk rather than in a comment. A muted
   * element is a picture, not a sound, and is left alone: the listen
   * wallpaper (#plBackVid) is muted by design (#1184). The warm element
   * (#1411) has never been played and is skipped by identity.
   *
   * The floor never deadlocks: the last claimant wins and everybody else
   * is silenced. The single refusal is a page road claiming while the
   * NATIVE wall is showing, because a page cannot pause a native
   * surface - there the page road yields and says nothing.
   */
  var SLOT_GRACE_MS = 750;         // the slot end, this long after the station's own moment
  var SFX_SOUNDERS = 'video[data-pine-live="voice"], .sfx-tv video, .sfx-tv-tube video, ' +
                     '#galleryStage video, video[data-pine-sfx], audio[data-pine-sfx]';
  var hushed = {count: 0, at: 0, last: ''};
  var floorHeld = {who: '', at: 0};

  function audible(el) {
    if (!el || el.paused) return false;
    if (el.muted) return false;
    var v = Number(el.volume);
    return !(isFinite(v) && v <= 0);
  }

  function hushOthers(keep) {
    var doc = root.document;
    if (!doc || typeof doc.querySelectorAll !== 'function') return 0;
    var all;
    try { all = doc.querySelectorAll(SFX_SOUNDERS); } catch (err) { return 0; }
    var n = 0;
    for (var i = 0; i < all.length; i += 1) {
      var el = all[i];
      if (!el || el === keep) continue;
      if (warm && el === warm.el) continue;
      if (!audible(el)) continue;
      try { el.muted = true; } catch (err) { /* a read-only stub */ }
      try { el.pause(); } catch (err) { /* already still */ }
      n += 1;
      hushed.last = String(el.id || el.className || el.tagName || '?').slice(0, 40);
    }
    if (n) { hushed.count += n; hushed.at = now(); }
    return n;
  }

  /* The native wall is showing AND therefore sounding: it is on, and the
     page has not veiled it (veil() hides the wall through the bridge as
     well, #1434). No page road may sound over it. */
  function wallSounding() {
    try { return !!(wallRunning() && !veiled); } catch (err) { return false; }
  }

  function floorClaim(who) {
    who = String(who || 'unnamed');
    if (who !== 'wall' && wallSounding()) return false;
    hushOthers(who === 'tube' ? video : null);
    floorHeld.who = who;
    floorHeld.at = now();
    return true;
  }

  function floorRelease(who) {
    if (!who || floorHeld.who === String(who)) { floorHeld.who = ''; floorHeld.at = 0; }
  }

  root.PineSfxFloor = {
    claim: floorClaim,
    release: floorRelease,
    owner: function () {
      return {who: floorHeld.who, at: floorHeld.at, wall: wallSounding(),
              hushed: hushed.count};
    },
    /* stop every other SFX sound now (keep = the element that may go on;
       default the tube), and the count so far - a number, not a claim. */
    hush: function (keep) { return hushOthers(keep || video); },
    hushed: function () { return {count: hushed.count, at: hushed.at, last: hushed.last}; }
  };

  /* ---- one clip ------------------------------------------------------ */

  var receiptSequence = 0;
  var receiptListener = 'sfx-tv-' + Math.random().toString(36).slice(2);
  function videoReceipt(clip, event, screen, error) {
    if (!clip || !clip.delivery_id || clip.silent_picture) return;
    var bridge = api();
    if (!bridge || !bridge.post) return;
    var volume = screen ? Math.min(1, Number(screen.volume) || 0) : 0;
    Promise.resolve(bridge.post('/api/dj/voice/ack', {
      delivery_id: clip.delivery_id, listener_id: receiptListener, event: event,
      sequence: ++receiptSequence, current_time: screen ? Number(screen.currentTime) || 0 : 0,
      volume: volume, audible_volume: screen && !screen.muted ? Math.min(volume, level) : 0,
      muted: !!(screen && screen.muted), error: String(error || '')
    })).catch(function () { /* the next playback heartbeat retries */ });
  }

  function play(clip) {
    /* #1426: an endless clip belongs to the native surface while it is
       running. Checked here as well as at the poll because a clip can
       reach this through cut() and the replay road too. */
    if (clip && clip.endless && wallRunning()) return;
    /* [#1214] AND NEITHER DOES ANYTHING ELSE while that surface is
       showing. #1426 covered only the endless clips; a station sting
       with a picture went out over the wall's own soundtrack, which is
       two clips at once on the one machine. Claiming the floor also
       hushes every other page road that is sounding. */
    if (!floorClaim('tube')) {
      showing = false;
      videoReceipt(clip, 'error', null, 'Another SFX surface owns playback');
      return;
    }
    /* #1184: whatever was in the tube is now the past, whichever road
       took it out - the clip ending, a seamless hand-over, the operator
       cutting, a run stepping on. One line here covers every one of
       them, which is why the strip cannot end up with a hole in it. */
    remember(playing);
    playing = clip;                                        /* #1306b */
    var tries = Number(clip.__tries) || 0;                 /* #1311d */
    var ready = warmTake(clip);                            /* #1411 */
    /* [#1212] the seam promotes the warm tube in place; everything else
       builds a set, exactly as before. `host.__parts` is the tell that
       this host was built by this version of build(). */
    var slot = !!(clip.__seam && ready && host && tube && video
                  && ready.parentNode === tube && host.__parts);
    var parts = slot ? slotSwap(ready)
                     : build(clip.sting || clip.text || 'SFX', ready);
    /* Held locally, because every handler and timer below can fire after
     * the module's own references have moved on. */
    var screen = video;
    screen.dataset.pineSilentPicture = clip.silent_picture ? '1' : '0';
    screen.muted = !!clip.silent_picture;
    var receiptAt = 0, receiptClosed = false;
    function reportVideo(event, error) {
      if (receiptClosed) return;
      if (event === 'ended' || event === 'error') receiptClosed = true;
      videoReceipt(clip, event, screen, error);
    }
    screen.addEventListener('canplay', function () { reportVideo('canplay'); });
    screen.addEventListener('playing', function () { reportVideo('playing'); });
    screen.addEventListener('timeupdate', function () {
      if (!screen.paused && now() - receiptAt > 2000) {
        receiptAt = now(); reportVideo('playing');
      }
    });
    screen.addEventListener('ended', function () { reportVideo('ended'); });
    screen.addEventListener('error', function () { reportVideo('error', 'Video decode or fetch failed'); });
    screen.__pineReceiptClose = function () { reportVideo('error', 'Video player closed before completion'); };
    var glass = tube;
    var done = false;
    var finish = function () {
      if (done) return;
      /* #1112: NOT WHILE THE SHEET IS UP. The clip has ended (or hit
       * its out, or the watchdog found it stopped) under the operator's
       * open sheet, so the picture stays on its last frame and the
       * finish is owed to sheetClose(). Only the set on screen can be
       * held - a finish arriving for an older set runs as before. */
      if (video === screen && sheetHeld()) {
        try { screen.pause(); } catch (err) { /* it has ended anyway */ }
        owed = true;
        return;
      }
      done = true;
      writeBox();                    // wherever it ended up is the preference
      /* #1184: SEAMLESS - "Offer an option to enable seamless video as
       * well." The seam the operator can see is not a cut between two
       * pictures, it is the deliberate gap between them: OFF_MS of CRT
       * collapse (520 ms), the 120 ms rest inside teardown, and then a
       * set built hidden and expanded when a frame turns up. The note
       * beside JOIN_MIN at the top of this file already measured that
       * hand-over and named all three.
       *
       * With the switch on, and only when the next clip is genuinely
       * warmed (seamReady), none of that runs: the warmed element goes
       * into the tube on this frame, through cut() with {seam: true} -
       * the same road Next, Prev and the run take, per the note above
       * `replays`, because a second play pipeline is exactly the thing
       * this file must not grow.
       *
       * A HARD CUT, NOT A CROSSFADE, and the reason is #1312 in this
       * same file. A fade needs both clips decoded and painted at once;
       * two live <video> elements each hold a connection, a WebView
       * allows about six per host, and the last time this tube held on
       * to a spare the page could not fetch anything at all. The cut
       * costs nothing over today - the same single warm element, held
       * for the same time, simply not thrown away. */
      if (seamReady()) {
        var nextUp = queue.shift();
        if (nextUp && root.PineSfxTv.cut(nextUp, {seam: true})) return;
        /* It would not open: fall through to the collapse rather than
           leave a dark tube. The clip is already off the queue, which is
           right - it is the one that failed. */
      }
      try {
        glass.classList.remove('on');
        void glass.offsetWidth;      // restart the animation, never resume it
        glass.classList.add('off');
      } catch (err) {}
      setTimeout(function () { teardown(screen); }, OFF_MS);
    };
    var close = function () {
      /* The operator's own ✕ wants the picture gone now, not in half a
       * second - but the geometry is still worth keeping. */
      if (done) return;
      done = true;
      writeBox();
      teardown(screen);
    };
    /* #1112: the sheet's roads reach this set's finish through here. */
    curtain = finish;
    /* #1121/#1124: THE END OF THE CLIP IS NOT ALWAYS THE END.
     *
     * Before the finish - and before #1112's owed/held rule, because a
     * replay is not a finish and neither is the next clip of a run -
     * `ended` asks two module-level counters. Replays owed: back to
     * the start and play again. Clips left in the run: the station is
     * asked for the next one in the folder and cut() puts it up (that
     * takes this set down with it - the operator asked for the next
     * picture, not this one). Only when both are spent does the CRT
     * collapse. A trimmed clip (#1310) reaches its `to` the same way,
     * through `passed`, so the out point cannot fire the counter down
     * on every timeupdate before the seek lands. */
    var from = Number(clip.from);
    var to = Number(clip.to);
    var over = false;              // the run's next clip is being fetched
    var passed = false;            // the out point has been met this pass
    var restart = function () {
      passed = false;
      owed = false;                /* #1112: it is playing again */
      try { screen.currentTime = (isFinite(from) && from > 0) ? from : 0; }
      catch (err) { /* it plays on from where it is */ }
      var again = screen.play();
      if (again && again.catch) again.catch(function () {});
    };
    rewind = function () {
      if (done || over || video !== screen) return;
      restart();
    };
    var ended = function () {
      if (done) return;
      if (video !== screen) { finish(); return; }
      if (replays > 0) {
        replays -= 1;
        paintBadge();
        restart();
        return;
      }
      if (runLeft > 0) {
        runLeft -= 1;
        paintBadge();
        over = true;
        try { screen.pause(); } catch (err) { /* it has ended anyway */ }
        var stopRun = function (why) {
          if (done || video !== screen) return;
          over = false;
          runLeft = 0;
          runFrom = '';
          paintBadge(why, 4000);
          /* Long enough for the reason to be read before the collapse. */
          setTimeout(function () { if (video === screen) finish(); }, 1600);
        };
        neighbour(clipId(clip), 'next').then(function (got) {
          if (done || video !== screen) return;
          if (got && got.ok && got.clip && got.clip.url) {
            runFrom = clipId(got.clip);
            if (!root.PineSfxTv.cut(got.clip, {ring: true})) {
              stopRun('the next one would not open');
            }
            return;
          }
          stopRun(String((got && got.say) || 'nothing more in that folder'));
        }, function (err) {
          stopRun(String((err && err.message) || err || 'no answer').slice(0, 40));
        });
        return;
      }
      finish();
    };
    paintBadge();                  // a run or replays owed show on this set too

    parts.shut.addEventListener('click', close);

    /* #1308b: NOTHING IS SHOWN UNTIL THERE IS A PICTURE.
     *
     * "I don't want to see the video icon. I just want to see the crt
     *  effect then expand out becoming the video window. Do not show
     *  the preview video box first. That image isn't even scaled
     *  properly to be a box, so it's like skewed."
     *
     * That icon is not ours and it is not the clip: it is the Android
     * WebView's own placeholder for a <video> with no frames yet, and
     * being a fixed bitmap it ignores the object-fit: contain this
     * stylesheet sets, which is why it came out stretched. The set
     * used to open the moment play() was called, and the clip takes a
     * couple of seconds to arrive over the LAN - so the CRT expanded
     * onto the placeholder and the picture appeared inside it later.
     *
     * So the whole window waits. It is built and positioned, but
     * hidden, until the first real frame exists; then the CRT runs and
     * expands into the picture itself. A clip that never arrives is
     * torn down by the watchdog below and was never seen at all,
     * which is better than an empty box that sat there. */
    var shown = false;
    /* #1184: a clip arriving through the seamless hand-over must not run
       the CRT expand either - half a seam is still a seam. `waiting` is
       lifted (that is the visibility:hidden the stylesheet puts on a set
       with no frame yet) and nothing is animated: the picture is simply
       there, which is what "no seam" means. */
    var seam = false;
    try { seam = !!clip.__seam; } catch (err) { seam = false; }
    var reveal = function () {
      if (shown || done) return;
      shown = true;
      tlStart(screen);                                     /* [#1219] */
      try {
        host.classList.remove('waiting');
        if (!seam) {
          glass.classList.add('on');   // dot -> line -> picture
          parts.flash.classList.add('pop');
        }
      } catch (err) { /* the picture is there either way */ }
      /* #1184: on a seam the NEXT clip has to be warming already - the
         clip on screen has its whole length to fetch the one after it,
         and waiting the usual beat after a first frame that arrived
         instantly would leave the following hand-over unwarmed and the
         set would blink once every other clip. */
      setTimeout(warmUp, seam ? 0 : WARM_AFTER_MS);       /* #1411 */
    };
    /* loadeddata is the first frame; playing covers a clip that was
       already buffered. Both are harmless twice - reveal guards. */
    screen.addEventListener('loadeddata', reveal);
    screen.addEventListener('playing', reveal);
    /* #1184: A WARMED ELEMENT HAS ALREADY FIRED loadeddata, on nobody.
     * The warm (#1411) is a detached <video> that has been fetching for
     * seconds, so by the time it reaches the tube its first frame event
     * is long gone and only `playing` is left to lift the veil. That is
     * usually enough - but a hidden tube is precisely the failure the
     * seam cannot afford, and the readyState is already there to be
     * asked. Asked once, here, rather than trusted to an event that has
     * already happened. */
    if (ready && screen.readyState >= 2) reveal();

    /* #1311d: A CLIP THIS BUILD CANNOT DECODE IS NOT THE END OF THE TAP.
     *
     * The library is 400 grabbed mp4s and they are not all the same
     * inside - measured on the tablet, a clip that the station served
     * perfectly (200 OK, video/mp4, 415 kB in 0.11s) came back
     * MEDIA_ERR_SRC_NOT_SUPPORTED, because this WebView has no
     * decoder for what is in that particular container.
     *
     * The operator tapped a button and is owed a picture, so a clip
     * that will not open is SKIPPED rather than mourned: the set asks
     * the cue road for another and tries that instead. Only a cut the
     * operator asked for retries - the station's own stings keep the
     * old behaviour, because there the clip is punctuating a line and
     * a substitute would land after the moment it was for. */
    var failed = function () {
      if (done) return;
      /* #1112: a clip that has shown a frame and is now sitting under
       * the operator's sheet is not a failure - the watchdog sees it
       * `paused` after it ended, and `error` can fire late on a file
       * the operator has just deleted. The finish below is owed, not
       * run, while the sheet is up; nothing here tears down through
       * it. A clip that never showed a frame is still skipped. */
      if (shown && sheetHeld()) { finish(); return; }
      if (!shown && clip.__cut && tries < 3 && api() && api().post) {
        done = true;                 /* this attempt is over */
        try { teardownNow(); } catch (err) { /* nothing up */ }
        api().post('/api/sfx/video/cue', {who: 'retry'}).then(
          function (got) {
            var next = got && got.clip;
            if (!next) { showing = false; return; }
            next.__cut = true;
            next.__tries = tries + 1;
            showing = true;
            try { play(next); } catch (err) { showing = false; }
          },
          function () { showing = false; });
        return;
      }
      finish();
    };
    screen.addEventListener('ended', ended);               /* #1121/#1124 */
    screen.addEventListener('error', failed);
    /* #1411: a warmed tube already has its source; assigning the same
       src again runs the load algorithm from scratch and throws the
       buffer away, which is the whole thing being avoided. */
    /* #1421: the held bytes if we have them, the station if we do not. */
    if (!ready) screen.src = heldSrc(clip);
    screen.addEventListener('canplaythrough', function () { warmUp(); });
    levelSet(screen, level, false);
    /* #1310: THE PAD'S IN AND OUT, ON THE PICTURE TOO.
     *
     * The same {start, end} the engine clips the audio to, so a video
     * pad's trim edits both halves of it from the one editor. Seeking
     * waits for metadata - currentTime cannot be set before the
     * duration is known - and the out is watched on timeupdate rather
     * than with a timer, because a clip that stalls should stop where
     * the operator said, not where a clock guessed. (`from` and `to`
     * are read above, where the replay needs them too.) */
    if (isFinite(from) && from > 0) {
      screen.addEventListener('loadedmetadata', function () {
        try { screen.currentTime = from; } catch (err) { /* whole clip */ }
      });
      /* #1411: a warmed element may have had its metadata for a while. */
      if (ready && screen.readyState >= 1) {
        try { screen.currentTime = from; } catch (err) { /* whole clip */ }
      }
    }
    /* #1173: JOIN THE STATION'S POSITION. The long note beside JOIN_MIN at
     * the top of this file carries the measurements; this is the handful
     * of lines it asks for. A trimmed clip (#1310 - a sampler pad's own in
     * and out) is not the station's picture and is left exactly alone. */
    var joined = false;
    var joinNow = function () {
      if (joined || done || video !== screen) return;
      if (isFinite(from) && from > 0) { joined = true; return; }
      joined = true;
      var into = airJoin(clip);
      if (into <= 0) return;
      var len = Number(screen.duration);
      /* Nothing of it left worth a decode - the next clip's moment is
       * already near and the set takes it on its own. */
      if (isFinite(len) && len > 0 && into > len - JOIN_TAIL) return;
      /* #1421b: NO share bound here. This seek happens once, before a
         frame has been shown, and it is the whole of #1173 - see the
         measurements beside JOIN_MIN. The bound belongs on the HOLD
         below, which is the one that flushes a decoder mid-picture. */
      try { screen.currentTime = into; } catch (err) { /* it plays from 0 */ }
    };
    screen.addEventListener('loadedmetadata', joinNow);
    if (screen.readyState >= 1) joinNow();
    /* AND IT IS HELD THERE. This WebView suspends its JS timers when the
     * screen sleeps and the decode stalls with them; it comes back where
     * it left off, with no way to notice it is now behind. The check that
     * put the picture in the right place puts it back - rested, and never
     * for a jump smaller than a jump is worth, because a wallpaper that
     * twitches every two seconds is worse than one a third of a second
     * out. */
    var fixedAt = 0;
    screen.addEventListener('timeupdate', function () {
      if (done || video !== screen) return;
      if (isFinite(from) && from > 0) return;
      var into = airInto(clip);
      if (into <= 0) return;
      var off = Number(screen.currentTime) - into;
      var span = Number(screen.duration);
      if (!worthSeeking(off, span, SLIP_MAX)) return;          /* #1421 */
      if (now() - fixedAt < SLIP_REST) return;
      if (isFinite(span) && span > 0 && into > span - JOIN_TAIL) return;
      fixedAt = now();
      try { screen.currentTime = into; } catch (err) { /* it plays on */ }
    });
    if (isFinite(to) && to > 0) {
      screen.addEventListener('timeupdate', function () {
        if (passed || Number(screen.currentTime) < to) return;
        passed = true;
        ended();                   /* #1121/#1124: the out is an end too */
      });
    }
    /* THE WATCHDOG. `error` does not fire for every way a clip can fail
     * to begin - a stalled range request, a container this build cannot
     * decode, a zero-byte download off the drop share - and a set left on
     * with a black tube holds every clip behind it. */
    setTimeout(function () {
      if (done || video !== screen) return;
      /* #1112: a set the operator is holding open with the sheet is
         never the watchdog's business once it has shown a picture. */
      if (shown && sheetHeld()) return;
      /* #1124: nor is a set waiting on the next clip of its run. */
      if (over) return;
      /* #1311d: a clip that never started is skipped the same way one
         that errored is - a stalled range request and a missing
         decoder look identical from here and deserve the same answer. */
      if (screen.paused || !Number(screen.currentTime)) failed();
    }, 12000);
    /* [#1214] ONE SFX SOUND AT A TIME ON THIS PAGE - this is the moment
       sound actually starts, so the hush is repeated here (the claim at
       the top of play() can be seconds older on a slow decode). A
       seamless hand-over is the same cut with the frame kept. */
    hushOthers(screen);
    /* [#1214] THE SLOT IS THE CLIP'S TIME, ON EVERY SURFACE. The station
       rings the endless set as slots (clip.seconds); the tune-in stage
       (tvPoll) and the tablet's wall move on at the slot end, and this
       set played the FILE to its end - so a ten-minute clip rung into a
       six-second slot held this tube for ten minutes while every other
       surface cycled: "playing multiple clips at the same time",
       measured 2026-09-16 11:03 as a frame nine and a half minutes old.
       The slot end is an out point like `to`: ended() runs, and with the
       switch on the seam hands over to the clip already warmed. A clip
       the operator cut carries no `at` and is left to its own length. */
    var slotEnd = null;
    if (clip.endless && !(isFinite(to) && to > 0)) {
      var slotMs = Number(clip.seconds) * 1000;
      var atMs = Number(clip.at);
      if (isFinite(slotMs) && slotMs > 0 && isFinite(atMs) && atMs > 0) {
        slotEnd = setTimeout(function () {
          slotEnd = null;
          if (done || video !== screen || passed || over) return;
          passed = true;
          ended();
        }, Math.max(0, atMs + slotMs + SLOT_GRACE_MS - now()));
      }
    }
    var started = screen.play();
    if (started && started.catch) {
      started.catch(function () {
        /* The picture is still worth having without the sound. */
        try { screen.muted = true; screen.play().catch(function () {}); }
        catch (err) { finish(); }
      });
    }
  }

  /* #1306b: THE FOUR THINGS THE OPERATOR WANTS TO DO TO A CLIP.
   *
   * Every one of these already has a door and the clip already
   * carries the handle they want - its sfx id. Nothing here invents
   * an endpoint.
   *
   * #1112: and two more - "never again" (the ban switch) and "where is
   * it" (the info route's paths) - on the same rule.
   */
  function clipId(clip) {
    if (!clip) return '';
    if (clip.id) return String(clip.id);
    /* Older rings carry only the url: /sfx/<id>?t=<sig> */
    var m = /\/sfx\/([^?#/]+)/.exec(String(clip.url || ''));
    return m ? m[1] : '';
  }

  function post(path, body) {
    var bridge = api();
    if (!bridge || !bridge.post) return Promise.reject(new Error('no bridge'));
    return bridge.post(path, body || {});
  }

  /* #1184: THE CYCLE'S SHORT MEMORY, AND THE STRIP IT FEEDS.
   *
   * "show thumbnails of the last 2 videos played and the next 2 videos
   *  planned for play"
   *
   * Nothing in this file kept what had already played. `playing` is the
   * clip in the tube, `queue` is what the station has rung ahead, and the
   * past went out with teardown - so the two halves of what he asked for
   * were one half available. `marks` looked like a history and is not: it
   * is a dedupe set keyed on ts|url with no order and no names in it.
   *
   * PLAIN OBJECTS, NEVER ELEMENTS. #1312's note in this same file is the
   * reason that is spelled out: orphaned <video> elements each held an
   * HTTP connection, a WebView allows about six per host, and after a few
   * taps every request on the page hung - a fetch of /api/pulse that
   * never returned while the same URL answered the desk in 0.02s. A ring
   * of six small objects cannot do that to anything.
   *
   * Only the endless cycle is remembered. A sting is punctuation for a
   * line that was spoken; it is not part of a set the operator is
   * browsing, and putting it in the strip would offer him a jump back to
   * a clip that only made sense against a sentence that has finished. */
  function remember(clip) {
    if (!clip || !clip.url || !clip.endless) return;
    var id = clipId(clip);
    var row = {id: id, url: String(clip.url),
               video: !!clip.video,                          /* #1199 */
               sting: String(clip.sting || clip.text || ''),
               seconds: Number(clip.seconds) || 0};
    /* The same clip round again is the newest entry, not a second one. */
    for (var i = heard.length - 1; i >= 0; i -= 1) {
      if (heard[i].url === row.url) heard.splice(i, 1);
    }
    heard.push(row);
    if (heard.length > HEARD_MOST) heard.splice(0, heard.length - HEARD_MOST);
  }

  /* The strip, newest-last: the last two heard, the one on the tube, the
   * next two the station has rung ahead. Short of either is simply short
   * - a set that has just come on has nothing behind it and says so by
   * showing fewer tiles rather than by drawing empty boxes. */
  /* #1195: hold one clip in `coming`, and drop what is no longer coming.
   *
   * A clip leaves three ways: it reached the tube, it was withdrawn, or its
   * moment passed by more than its own length - which is the case that
   * matters, because a plan that silently failed to arrive must not sit in
   * the strip for ever calling itself next. */
  function comingKeep(clip) {
    if (!clip || !clip.url) return;
    var key = String(clip.id || clip.url);
    var i;
    for (i = coming.length - 1; i >= 0; i -= 1) {
      if (String(coming[i].id || coming[i].url) === key) coming.splice(i, 1);
    }
    coming.push({id: clipId(clip), url: String(clip.url),
                 video: !!clip.video,                        /* #1199 */
                 sting: String(clip.sting || clip.text || ''),
                 seconds: Number(clip.seconds) || 0,
                 at: Number(clip.at) || 0});
    coming.sort(function (a, b) { return (a.at || 0) - (b.at || 0); });
    if (coming.length > COMING_MOST) {
      coming.splice(0, coming.length - COMING_MOST);
    }
  }

  function comingDrop(key) {
    var k = String(key || '');
    if (!k) return;
    for (var i = coming.length - 1; i >= 0; i -= 1) {
      if (String(coming[i].id || coming[i].url) === k) coming.splice(i, 1);
    }
  }

  /* What is still ahead of us, soonest first. A clip whose moment has gone
   * by more than its own length never arrived, and saying so by leaving it
   * out is better than drawing it as next for the rest of the night. */
  function comingRows() {
    var t = now();
    var here = playing ? clipId(playing) : '';
    var out = [];
    for (var i = 0; i < coming.length; i += 1) {
      var row = coming[i];
      if (!row || !row.url) continue;
      if (here && String(row.id) === here) continue;
      var late = t - (row.at || 0);
      if (row.at && late > ((row.seconds || 0) * 1000) + 4000) continue;
      out.push(row);
    }
    return out;
  }

  function stripRows() {
    var rows = [];
    var i;
    var back = heard.slice(-STRIP_PAST);
    for (i = 0; i < back.length; i += 1) {
      rows.push({id: back[i].id, url: back[i].url, sting: back[i].sting,
                 video: !!back[i].video,                     /* #1199 */
                 seconds: back[i].seconds, when: 'played'});
    }
    if (playing && playing.url) {
      rows.push({id: clipId(playing), url: String(playing.url),
                 video: !!playing.video,                     /* #1199 */
                 sting: String(playing.sting || playing.text || ''),
                 seconds: Number(playing.seconds) || 0, when: 'now'});
      comingDrop(clipId(playing));                           /* #1195 */
    }
    /* #1195: from what the station has RUNG AHEAD, not from the holding
     * array. `queue` is drained by next() in the same breath offer() fills
     * it, so building the next tiles from it drew nothing at all - which is
     * exactly what the operator photographed. `queue` is still read as a
     * fallback, so a build that has one and not the other still shows
     * something rather than going blank. */
    var ahead = comingRows();
    if (!ahead.length) {
      for (i = 0; i < queue.length; i += 1) {
        if (!queue[i] || !queue[i].url) continue;
        ahead.push({id: clipId(queue[i]), url: String(queue[i].url),
                    video: !!queue[i].video,                 /* #1199 */
                    sting: String(queue[i].sting || queue[i].text || ''),
                    seconds: Number(queue[i].seconds) || 0,
                    at: Number(queue[i].at) || 0});
      }
    }
    var mine = playing ? clipId(playing) : '';
    var aheadAdded = 0;
    for (i = 0; i < ahead.length && aheadAdded < STRIP_NEXT; i += 1) {
      if (mine && String(ahead[i].id) === mine) continue;
      rows.push({id: ahead[i].id, url: ahead[i].url, sting: ahead[i].sting,
                 video: !!ahead[i].video,                    /* #1199 */
                 seconds: ahead[i].seconds, at: ahead[i].at, when: 'next'});
      aheadAdded += 1;
    }
    return rows;
  }

  /* #1184: IS THE NEXT CLIP READY TO GO IN ON THIS FRAME?
   *
   * Seamless is not a promise that can always be kept, and pretending
   * otherwise would give the operator a switch that works on long clips
   * and blinks on short ones with nothing to say about it. It is true
   * only when the station's switch is on, the cycle has a next clip, and
   * the WARMED element (#1411) is that clip's and has not failed. The
   * warm is started WARM_AFTER_MS (1.5 s) after the tube's first frame,
   * so on a clip of more than about two seconds it has the rest of the
   * clip to arrive; below that the answer here is false and the set does
   * the CRT collapse it has always done. */
  function seamReady() {
    if (!seamOn) return false;
    var head = queue[0];
    if (!head || !head.url || !head.endless) return false;
    if (!warm || warm.clip !== head) return false;
    try { if (warm.el && warm.el.error) return false; }
    catch (err) { return false; }
    return true;
  }

  /* #1123/#1124: THE CLIP BESIDE THIS ONE IN ITS FOLDER.
   *
   * "allow me to go to the next video or the previous video and it goes
   *  to the next video in that folder to the next clip. Or the previous
   *  clip."
   *
   * /api/sfx/video/neighbour is the station's own answer: {ok, clip,
   * index, count, folder, say}, with ok:false and a `say` when the
   * folder has nothing more that way. The clip it hands back is played
   * through cut() with {ring: true}, the way a sampler pad's clip is -
   * so the other surfaces' sets show it too. */
  function neighbour(id, dir) {
    var bridge = api();
    if (!id) return Promise.reject(new Error('no id on this clip'));
    if (!bridge || !bridge.get) return Promise.reject(new Error('no bridge'));
    return bridge.get('/api/sfx/video/neighbour?id=' + encodeURIComponent(id)
                      + '&dir=' + (dir === 'prev' ? 'prev' : 'next'));
  }

  /* The native wall owns its ExoPlayer runway. An operator-selected clip
     must be inserted directly after the current item, not left behind the
     three already warmed entries where "Next" appears to do nothing. */
  function wallSelect(clip) {
    if (!clip || !clip.url || !wallRunning()) return false;
    try { markOf(clip); } catch (err) { /* it can still be selected */ }
    ring(clip);                         /* every other surface sees the cut */
    wallAsk('play', {id: clipId(clip), url: String(clip.url),
                     seconds: Number(clip.seconds || clip.length) || 0});
    sheetClose();                       /* releases the held endless player */
    return true;
  }

  function step(clip, dir, say) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    say(dir === 'prev' ? 'the one before...' : 'the next one...');
    neighbour(id, dir).then(function (got) {
      if (got && got.ok && got.clip && got.clip.url) {
        /* #1124: a run in progress carries on from the clip stepped to. */
        if (runLeft > 0) runFrom = clipId(got.clip);
        if (wallSelect(got.clip)) return;
        if (!root.PineSfxTv.cut(got.clip, {ring: true})) say('it would not open');
        return;
      }
      say(String((got && got.say) || 'nothing else in that folder'));
    }, function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  function weigh(clip, up, say) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    /* The station's own draw weight - the same dial the SFX desk
       writes - so a thumb here really does change how often it comes
       round. 0.05 is the floor the draw already reads as "marked all
       the way down". */
    post('/api/sfx/weight', {id: id, weight: up ? 2 : 0.05}).then(
      function () { say(up ? 'more often' : 'less often'); },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  function scrap(clip, say, done) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    post('/api/sfx/delete', {id: id}).then(
      /* 2026-09-14: the station says HOW it was deleted - unlinked here,
         or handed to the desk because the share is read-only to it. */
      function (got) { say(String((got && got.say) || 'deleted')); if (done) done(); },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  /* #1112: "choose to have videos not play anymore" - the file stays
   * on the station, the draw stops picking it. /api/sfx/ban is the
   * station's own switch for that; nothing is unlinked. */
  function ban(clip, say, done) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    post('/api/sfx/ban', {id: id, banned: true}).then(
      function () { say('never again'); if (done) done(); },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  /* #1112: "inspect the location and find out where videos are
   * located." /api/sfx/info answers with `where` (the station's label,
   * samples/mwc/clip-6.mp4), `path` (inside the container) and
   * `host_path` (a Windows or UNC path when the folder is on a share,
   * else ''). The most reachable of the three is printed; and where the
   * desktop bridge can reveal a file in Explorer, the folder is opened
   * on the host path too. */
  function locate(clip, say) {
    var id = clipId(clip);
    var bridge = api();
    if (!id || !bridge || !bridge.get) { say('no id on this clip'); return; }
    bridge.get('/api/sfx/info?id=' + encodeURIComponent(id)).then(
      function (got) {
        var hostPath = String((got && got.host_path) || '');
        var where = hostPath || String((got && (got.path || got.where)) || '');
        if (!where) { say('the station does not know where it lives'); return; }
        var desk = root.pineDesktop;
        if (hostPath && desk && typeof desk.showInFolder === 'function') {
          try {
            Promise.resolve(desk.showInFolder(hostPath)).then(
              function () { say('opened the folder  -  ' + where); },
              function () { say(where); });
            return;
          } catch (err) { /* the path is still worth printing */ }
        }
        say(where);
      },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  function toPad(clip, say) {
    var id = clipId(clip);
    var sampler = root.PineSampler;
    if (!sampler || typeof sampler.grab !== 'function') {
      say('the sampler is not on this page'); return;
    }
    var row = {id: id, url: String(clip.url || ''), sfx: true,
               text: String(clip.sting || ''), who: 'the board'};
    say('taking it...');
    Promise.resolve(sampler.grab(row)).then(function (got) {
      say(got && got.ok ? 'on a pad' : ((got && got.why) || 'it refused'));
    }, function (err) {
      say(String((err && err.message) || err).slice(0, 40));
    });
  }

  /* #1184: `wrap` is the open sheet, so the full detail can go in the
     panel underneath the one-line note. Absent - an older caller - and
     the line is all that is written, exactly as before. */
  function inspect(clip, say, wrap) {
    var id = clipId(clip);
    var bridge = api();
    if (!id || !bridge || !bridge.get) { say('no id on this clip'); return; }
    bridge.get('/api/sfx/info?id=' + encodeURIComponent(id)).then(
      function (got) {
        var bits = [];
        if (got && got.name) bits.push(got.name);
        if (got && got.seconds) bits.push(Number(got.seconds).toFixed(1) + 's');
        /* #1112: this read `got.folder`, and the route's field is
           `where` - so the location never printed, on any surface,
           and nothing said so. The container and host paths follow it
           when the station knows them. */
        if (got && got.where) bits.push(got.where);
        if (got && got.path && got.path !== got.where) bits.push(got.path);
        if (got && got.host_path) bits.push(got.host_path);
        if (got && got.plays !== undefined) bits.push(got.plays + ' plays');
        if (got && got.weight !== undefined) bits.push('weight ' + got.weight);
        say(bits.join('  -  ') || 'nothing known about it');
        /* #1184: "examine the video - how long, how big, its dimensions,
         * when it was made, how often it has aired, its weight or ban
         * state." That is more than one ellipsised row of note can hold,
         * so the line above stays exactly what it has always been and
         * the rest goes in the panel underneath, one fact per row. */
        if (wrap) inspectPanel(clip, wrap, got);
      },
      function (err) { say(String((err && err.message) || err).slice(0, 40)); });
  }

  /* Bytes, as something a person reads. */
  function weighWord(bytes) {
    var n = Number(bytes) || 0;
    if (n <= 0) return '';
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' kB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  function madeWord(epoch) {
    var at = Number(epoch) || 0;
    if (at <= 0) return '';
    try { return new Date(at * 1000).toLocaleString(); }
    catch (err) { return ''; }
  }

  /* #1184: THE DIMENSIONS COME OFF THE ELEMENT, NOT OFF THE STATION.
   *
   * The clip is decoded in a <video> on this very page, and videoWidth
   * and videoHeight are exact and free there. Asking the station for
   * them would mean a second ffprobe subprocess per clip for a number
   * already on screen - and this station has a long ledger of being
   * starved by work it did not need to do. Either copy will answer: the
   * tube when the clip is in it, the LISTEN wallpaper when it is not. A
   * clip that is not on screen at all simply has no dimensions to give,
   * and the row says so rather than guessing. */
  function sizeWord(clip) {
    var wide = 0, tall = 0, el = null;
    try {
      if (playing && clipId(clip) === clipId(playing) && video) el = video;
      if (!el || !el.videoWidth) {
        var wv = wallNode();
        if (wv && wv.videoWidth) el = wv;
      }
      if (el) { wide = Number(el.videoWidth) || 0; tall = Number(el.videoHeight) || 0; }
    } catch (err) { return ''; }
    return (wide > 0 && tall > 0) ? (wide + ' x ' + tall) : '';
  }

  function inspectPanel(clip, wrap, got) {
    var box = panelOpen(wrap);
    panelRow(box, 'Name', String((got && got.name) || ''), '');
    panelRow(box, 'Length', (got && got.seconds)
      ? (Number(got.seconds).toFixed(2) + ' seconds') : '',
      'the station could not read a length off it');
    panelRow(box, 'Size on disk', weighWord(got && got.bytes),
      'the folder would not say - an older station does not report it');
    panelRow(box, 'Dimensions', sizeWord(clip),
      'not decoded on this screen just now, so there is nothing exact '
      + 'to read');
    panelRow(box, 'Made', madeWord(got && got.made),
      'the folder would not say - an older station does not report it');
    panelRow(box, 'Times on air', String((got && got.plays) !== undefined
      ? (got.plays + ' (' + (got.today || 0) + ' today)') : ''), '');
    panelRow(box, 'Draw weight', String((got && got.weight) !== undefined
      ? got.weight : ''), '');
    panelRow(box, 'Ban', (got && got.banned)
      ? 'banned - it is kept but never drawn'
      : 'not banned - it is in the draw', '');
  }

  /* #1184: THE DETAIL PANEL - one surface, three readers.
   *
   * Inspect and Path both answer with more than a single line of note
   * can hold: a Windows path on this station is routinely eighty
   * characters and the note is one ellipsised row inside a 420 px set.
   * Rather than two pop-ups, both write into one panel that lives at the
   * bottom of the sheet and is replaced by whichever was asked for last.
   * It goes when the sheet goes - sheetClose() and sheetForget() both
   * drop the reference, and the node is a child of the sheet so it is
   * removed with it either way. */
  function panelOpen(wrap) {
    panelShut();
    var box = document.createElement('div');
    box.className = 'sfx-tv-panel';
    var s = box.style;
    s.marginTop = '6px'; s.paddingTop = '6px';
    s.borderTop = '1px solid rgba(159, 216, 255, .22)';
    s.maxHeight = '30vh'; s.overflowY = 'auto'; s.overflowX = 'hidden';
    s.fontSize = '11px'; s.lineHeight = '1.45'; s.color = '#dcecf6';
    wrap.appendChild(box);
    panel = box;
    return box;
  }

  function panelShut() {
    var box = panel;
    panel = null;
    try { if (box && box.parentNode) box.parentNode.removeChild(box); }
    catch (err) { /* already gone */ }
  }

  /* One labelled row in the panel. `absent` is what to print when the
   * station has nothing for it - because a blank line is how #1112's
   * `where`/`folder` mix-up hid for two days: the location never printed
   * on any surface and nothing anywhere said so. */
  function panelRow(box, label, value, absent) {
    var row = document.createElement('div');
    row.style.margin = '0 0 5px 0';
    var tag = document.createElement('i');
    tag.textContent = String(label) + ' ';
    tag.style.fontStyle = 'normal'; tag.style.opacity = '.62';
    tag.style.textTransform = 'uppercase';
    tag.style.fontSize = '9.5px'; tag.style.letterSpacing = '.06em';
    var body = document.createElement('div');
    var text = String(value || '');
    body.textContent = text || String(absent || 'the station does not say');
    if (!text) body.style.opacity = '.62';
    body.style.wordBreak = 'break-all';
    body.style.userSelect = 'text';
    row.appendChild(tag);
    row.appendChild(body);
    if (text) row.appendChild(copyButton(text));
    box.appendChild(row);
    return row;
  }

  /* #1184: "see the path" means a path he can DO something with, so it
   * can be copied. Two roads, and the desk's one first: preload.js has
   * its own copyText because navigator.clipboard is undefined on a
   * file:// page - #990 records two copy sites that failed silently for
   * exactly that reason. Where neither exists the button says so instead
   * of sitting there doing nothing; the text is selectable either way. */
  function copyButton(text) {
    var b = document.createElement('button');
    b.type = 'button';
    b.style.marginTop = '3px';
    b.style.minHeight = '26px';
    b.style.flex = '0 0 auto';
    var mark = (typeof root.pineIcon === 'function'
      ? root.pineIcon('c:copy--to-clipboard', 'Copy') : '') || '';
    var desk = root.pineDesktop;
    var road = null;
    if (desk && typeof desk.copyText === 'function') {
      road = function () { return Promise.resolve(desk.copyText(text)); };
    } else if (root.navigator && root.navigator.clipboard
               && root.navigator.clipboard.writeText) {
      road = function () { return root.navigator.clipboard.writeText(text); };
    }
    var paint = function (word) { b.innerHTML = mark + ' ' + word; };
    if (!road) {
      paint('no clipboard here');
      b.disabled = true;
      b.title = 'This surface has no clipboard - select the line by hand';
      b.style.opacity = '.55';
      return b;
    }
    paint('Copy');
    b.title = 'Copy this line';
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      try {
        Promise.resolve(road()).then(function () { paint('copied'); },
                                     function () { paint('it refused'); });
      } catch (err) { paint('it refused'); }
    });
    return b;
  }

  /* #1184: "see the path" - the three spellings the station knows, each
   * on its own line and each copyable. They are genuinely different
   * things and which one is useful depends on where he is standing: the
   * Windows path opens in Explorer, the station path is what the
   * container sees, and the library label is how the SFX desk names it.
   * An empty Windows path is not a failure, it means this folder is not
   * on a share the desk can reach, and it says that. */
  function showPath(clip, wrap, say) {
    var id = clipId(clip);
    var bridge = api();
    if (!id) { say('no id on this clip'); return; }
    if (!bridge || !bridge.get) {
      say('this surface has no road to the station');
      return;
    }
    var box = panelOpen(wrap);
    box.textContent = 'asking the station where it lives...';
    bridge.get('/api/sfx/info?id=' + encodeURIComponent(id)).then(
      function (got) {
        if (panel !== box) return;          // he asked for something else
        box.textContent = '';
        panelRow(box, 'On this Windows machine',
                 String((got && got.host_path) || ''),
                 'not on a share the desk can open - it lives inside the '
                 + 'station');
        panelRow(box, 'On the station', String((got && got.path) || ''), '');
        panelRow(box, 'In the library', String((got && got.where) || ''), '');
        say('');
      },
      function (err) {
        if (panel !== box) return;
        box.textContent = 'the station would not answer: '
          + String((err && err.message) || err).slice(0, 60);
      });
  }

  /* #1184: THE PICTURE OF THE CYCLE - the last two and the next two.
   *
   * A tile is a real <button> on purpose. It reads as a control to a
   * screen reader, it takes a tap on glass without any gesture code of
   * its own, and hot-corners.js's _overControl walks up from the press
   * and finds the tag, so a tap on a tile in a corner of the screen is
   * never also a corner gesture.
   *
   * The poster comes from the station's poster road (#1184 server side),
   * which renders one frame per clip and keeps it. A clip with no frame
   * - or an older station with no poster road at all - simply shows its
   * name on a dark tile; an onerror that hid the broken-image glyph is
   * the whole of the degrading here. */
  function stripTile(row, mine, say) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'sfx-tv-tile';
    /* #1200: a tile the HISTORY put there, told apart from the cycle's own
       so that the ceiling can cut the right ones off the end of the run
       without anything having to keep a list of elements. */
    if (row && row.when === 'past') b.className += ' sfx-tv-hist';
    var s = b.style;
    s.flex = '0 0 auto'; s.width = '76px'; s.padding = '0';
    s.display = 'flex'; s.flexDirection = 'column'; s.gap = '2px';
    s.alignItems = 'stretch'; s.overflow = 'hidden';
    s.borderRadius = '6px'; s.cursor = 'pointer';
    s.background = 'rgba(159, 216, 255, .06)';
    s.border = mine ? '1px solid #65c7da'
                    : '1px solid rgba(159, 216, 255, .24)';
    var shot = document.createElement('div');
    shot.className = 'sfx-tv-shot';                        /* [#1256b] */
    shot.style.height = '44px'; shot.style.background = '#05080b';
    shot.style.overflow = 'hidden'; shot.style.position = 'relative';
    if (row.id) {
      /* #1200: THROUGH THE QUEUE, never straight to an <img src>.
         The url is still signed the way every other media url on this
         station is and still built on the same base the clip itself is
         fetched through, so it works on the tablet (relative) and in the
         shell (absolute) - shotFor does both. What changed is WHEN the src
         is set: at most two are in flight at a time, so a page of
         twenty-four tiles is a line that drains rather than twenty-four
         requests landing on an ffmpeg behind a semaphore of two. */
      shot.appendChild(shotFor(row).img);
    }
    var when = document.createElement('i');
    /* #1195: a "next" tile says HOW SOON, because "next" on four tiles in a
     * row tells him nothing about the order he is looking at. */
    var soon = '';
    if (row.when === 'next' && Number(row.at) > 0) {
      var wait = Math.round((Number(row.at) - now()) / 1000);
      if (wait > 0) soon = ' ' + (wait > 99 ? '99+' : String(wait)) + 's';
    }
    when.textContent = row.when === 'now' ? 'on now'
      : (row.when === 'next' ? ('next' + soon)
      : (row.when === 'past' ? agoOf(row.ts) : 'played'));  /* #1200 */
    var ws = when.style;
    ws.position = 'absolute'; ws.left = '0'; ws.right = '0'; ws.bottom = '0';
    ws.fontStyle = 'normal'; ws.fontSize = '8.5px'; ws.lineHeight = '12px';
    ws.textAlign = 'center'; ws.background = 'rgba(5, 8, 11, .74)';
    ws.color = row.when === 'now' ? '#65c7da' : '#dcecf6';
    shot.appendChild(when);
    var name = document.createElement('i');
    name.textContent = String(row.sting || 'clip');
    name.style.fontStyle = 'normal'; name.style.fontSize = '9.5px';
    name.style.lineHeight = '13px'; name.style.padding = '0 3px 3px';
    name.style.overflow = 'hidden'; name.style.whiteSpace = 'nowrap';
    name.style.textOverflow = 'ellipsis'; name.style.display = 'block';
    b.appendChild(shot);
    b.appendChild(name);
    b.title = (row.when === 'now' ? 'This one - ' : '')
      + String(row.sting || 'clip')
      /* #1200: the station counts every airing of a clip, and on a strip a
         hundred tiles long the same name coming round four times is worth
         saying out loud rather than leaving him to notice. */
      + (row.when === 'past' && Number(row.plays) > 1
         ? ' - ' + row.plays + ' airings' : '')
      + ' - tap to play it';
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      /* A queue tile is a transport control. Inspection remains available
         from the video hold menu; the unmodified tap now does the immediate
         thing its position in the queue promises and starts that item. */
      jump({id: row.id, url: row.url, sting: row.sting,
            seconds: row.seconds, video: !!row.video}, say);
    });
    return b;
  }

  /* Which of the station's two pictures this clip has. A video gets a
     real frame from the poster road; anything else has only the
     spectrogram, which is the picture the hover card has used since
     #335. One rule, written once, because two spellings of it is how a
     tile ends up asking a route that answers 404 for it on purpose. */
  function posterOf(row) {
    var id = String(row && row.id || '');
    var url = String(row && row.url || '');
    /* The signature is already on the clip's own url - the same media
       sign both routes check - so it is lifted from there rather than
       asked for a second time. */
    var m = /[?&]t=([^&#]+)/.exec(url);
    var sign = m ? m[1] : '';
    /* #1199: THE URL CANNOT ANSWER THIS, and it never could.
     *
     * This used to sniff a file extension. An sfx url has none - the
     * station builds them as /sfx/<hex>?t=<signature> in eight places -
     * so the test answered false for every clip in the cycle, every tile
     * took the spectrogram road, and a spectrogram of an mp4 draws its
     * SOUNDTRACK. The waveform-looking thumbnails the operator was shown
     * were pictures of the audio, not frames of the film.
     *
     * The clip has always known. /api/dj/video carries "video": true on
     * every cycle clip. The flag rides on the row now; the sniff stays
     * underneath as a fallback, so a clip handed in from somewhere that
     * sets no flag behaves exactly as it does today. */
    var looksVideo = (row && typeof row.video === 'boolean')
      ? row.video
      : /\.(mp4|m4v|webm|mov|mkv|ogv)(\?|#|$)/i.test(url);
    var road = looksVideo ? '/api/sfx/poster/' : '/api/sfx/spec/';
    return road + encodeURIComponent(id) + (sign ? '?t=' + sign : '');
  }

  /* #1200: TWENTY-FOUR TILES MUST NOT ALL ASK AT ONCE.
   *
   * The station's poster road renders one frame per clip in a worker
   * thread behind a SEMAPHORE OF TWO. So a page of twenty-four tiles each
   * setting an <img src> at once is not twenty-four answers, it is a queue
   * twenty-two deep with an ffmpeg at the front of it - and the next page
   * is another twenty-four behind those. The pattern sampler-face.js
   * settled on for its sixteen pads is followed here rather than a second
   * one being invented: AT MOST TWO IN FLIGHT, the same two the station
   * will serve, ONE CACHED ELEMENT PER SLOT, re-used rather than rebuilt.
   *
   * The element is created at once and handed to the tile straight away -
   * an <img> with no src draws nothing - and only its `src` waits its
   * turn. That is what keeps the record free of any reference to the tile
   * it sits in: when a picture lands it is already where it belongs, so
   * nothing has to remember where to put it. Re-used, not rebuilt: an
   * <img> that has loaded and is moved to another parent does not fetch
   * again, so a clip is asked for exactly ONCE per session however many
   * times the sheet is opened and closed over it.
   *
   * The key is the ROW, not the clip: a clip that aired four times is four
   * rows in the ledger and wants four tiles, and one element cannot be in
   * four places. Four records asking one url is four cache hits at the
   * browser, which costs the station nothing. */
  var SHOT_AT_ONCE = 2;            /* the station's own semaphore is two */
  var shots = Object.create(null); /* row key -> {key, url, state, img} */
  var shotQueue = [];
  var shotLive = 0;

  function shotKey(row) {
    return String((row && row.key) || (row && row.id) || (row && row.url) || '');
  }

  function shotUrl(row) {
    return base.replace(/\/+$/, '') + posterOf(row);
  }

  function shotPump() {
    while (shotLive < SHOT_AT_ONCE && shotQueue.length) {
      var rec = shotQueue.shift();
      if (!rec || rec.dropped || shots[rec.key] !== rec) continue;
      shotLive += 1;
      rec.state = 'flight';
      rec.img.src = rec.url;
    }
  }

  function shotLanded(rec, how) {
    return function () {
      if (rec.state !== 'flight') return;   /* load and error both fired */
      rec.state = how;
      shotLive = shotLive > 0 ? shotLive - 1 : 0;
      /* A 404 is the station's honest answer for a clip it cannot draw -
         an older mp4 ffmpeg will not seek, or a clip the poster road has
         never heard of. The tile keeps its name on a dark box and nothing
         is said about it, which is what the onerror here did before the
         queue existed. */
      if (how === 'bad') {
        try { rec.img.style.display = 'none'; } catch (err) { /* gone */ }
      }
      shotPump();
    };
  }

  function shotFor(row) {
    var key = shotKey(row);
    var url = shotUrl(row);
    var rec = shots[key];
    if (rec && rec.url === url) return rec;
    if (rec) rec.dropped = true;          /* the slot changed clip */
    var img = document.createElement('img');
    img.alt = '';
    img.style.width = '100%'; img.style.height = '100%';
    img.style.objectFit = 'cover'; img.style.display = 'block';
    rec = {key: key, url: url, state: 'queued', img: img, dropped: false};
    shots[key] = rec;
    img.addEventListener('load', shotLanded(rec, 'ok'));
    img.addEventListener('error', shotLanded(rec, 'bad'));
    shotQueue.push(rec);
    shotPump();
    return rec;
  }

  /* #1200: AND THE LINE IS BOUNDED TOO, not just the cache.
   *
   * MEASURED while writing the ceiling test rather than read out of the
   * code: after six pages the `shots` map held the hundred and twenty rows
   * it should, and shotQueue held a hundred and FORTY-TWO records - every
   * row the ceiling had let go was still standing in the line, marked
   * dropped, waiting for shotPump to walk past it one day.
   *
   * Nothing would ever have reported that. The line drains on its own as
   * pictures land, so it only grows without bound when pages arrive faster
   * than the station renders them - which is precisely the case the
   * operator creates by flicking. So it is swept where rows go away, in
   * one pass, at the one moment there is anything to sweep. */
  function shotSweep() {
    if (!shotQueue.length) return;
    var kept = [];
    for (var i = 0; i < shotQueue.length; i += 1) {
      var rec = shotQueue[i];
      if (rec && !rec.dropped && shots[rec.key] === rec) kept.push(rec);
    }
    shotQueue = kept;
  }

  /* A row the ceiling let go of takes its picture with it - that is what
     binds the poster cache to the rows, and there is no other road that
     grows it. A record still standing in the line is marked dropped so
     shotPump steps over it; one already in flight is left to land,
     because cancelling it would waste the ffmpeg the station has already
     started. */
  function shotForget(row) {
    var key = shotKey(row);
    var rec = shots[key];
    if (!rec) return;
    rec.dropped = true;
    delete shots[key];
    try {
      if (rec.img && rec.img.parentNode) rec.img.parentNode.removeChild(rec.img);
    } catch (err) { /* already gone */ }
  }

  /* #1200: HOW LONG AGO, in one short word. "played" on a hundred and
     twenty tiles tells him nothing he did not already know from where the
     tile sits; the ts the station sends with every history row does. */
  function agoOf(ts) {
    var when = Number(ts) || 0;
    if (when <= 0) return 'played';
    var secs = Math.round((now() / 1000) - when);
    if (secs < 0) return 'played';
    if (secs < 90) return secs + 's ago';
    var mins = Math.round(secs / 60);
    if (mins < 90) return mins + 'm ago';
    var hours = Math.round(mins / 60);
    if (hours < 36) return hours + 'h ago';
    return Math.round(hours / 24) + 'd ago';
  }

  /* #1200: THE VIDEO FLAG ON A HISTORY ROW, AND WHO IS ENTITLED TO SAY.
   *
   * #1199's cure in this same file must not be undone. posterOf used to
   * decide video-or-not by sniffing a file extension off the CLIP'S URL;
   * an sfx url has none - the station builds them as /sfx/<hex>?t=<sig> -
   * so every tile took the spectrogram road and drew a picture of the
   * clip's SOUNDTRACK instead of a frame. The flag rides on the row now
   * and the sniff is only a fallback.
   *
   * History rows did not carry that flag, so one had to be found for them.
   * THE STATION ANSWERS IT: the server half of #1200 puts
   * "video": sfx_is_video(name) on every history row, out of the same
   * SFX_VIDEO_TYPES table the sample draw itself uses. That was chosen
   * over deciding it here for two reasons - the station owns the list of
   * what counts as a picture (six suffixes today, and it has grown
   * before), and a renderer that decides for itself is a second answer to
   * one question that will disagree the day a seventh is added.
   *
   * Underneath it the fallback reads the row's NAME, never its url. That
   * is not #1199's guess coming back through the window: sfx_history_add()
   * records `path.name`, so the name genuinely IS the file's own name with
   * its own suffix on it, while the url genuinely cannot answer. It is
   * here only so an older station that has not taken the server half still
   * draws frames rather than soundtracks. */
  function histVideo(r) {
    if (r && typeof r.video === 'boolean') return r.video;
    return /\.(mp4|m4v|webm|mov|mkv|ogv)$/i.test(String((r && r.name) || ''));
  }

  /* Every clip the CYCLE is already showing a tile for. A history row for
     one of those is dropped on arrival rather than at draw time, so the
     rows and the tiles stay one for one - which is what lets the ceiling
     cut the right number of tiles off the end without counting them. */
  function liveIds() {
    var out = Object.create(null);
    var rows = stripRows();
    for (var i = 0; i < rows.length; i += 1) {
      out[String(rows[i].id)] = 1;
    }
    return out;
  }

  /* #1200: ONE PAGE OLDER, AND WHAT EVERY ANSWER MEANS.
   *
   * `before` is the ts of the oldest row already held and the station
   * answers rows at or before it - INCLUSIVE on purpose. A ts is whole
   * seconds and two clips can air inside one, so an exclusive boundary
   * would quietly drop whatever else went out in that second; an inclusive
   * one hands the boundary row back and `histSeen` throws it away here,
   * where it costs nothing. That is why the dedupe is not optional.
   *
   * A page that adds NO new rows at all is the end of the road however the
   * station described itself. Without that rule an inclusive cursor
   * sitting on a second that holds a whole page of clips would ask the
   * same question for ever. */
  function histFetch(most) {
    if (histBusy || !histMore) return;
    var wanted = Math.max(1, Math.min(3, Number(most) || HIST_PAGE));
    var asked = Math.min(3, wanted + (histAt > 0 ? 1 : 0));
    var bridge = api();
    if (!bridge || !bridge.get) {
      histMore = false;
      histBad = true;
      histSay = 'no road to the station from here';
      histPaint();
      return;
    }
    histBusy = true;
    histBad = false;
    histSay = 'looking further back...';
    histPaint();
    var path = '/api/sfx/history?limit=' + asked
      + (histAt > 0 ? '&before=' + histAt : '');
    bridge.get(path).then(function (got) {
      histBusy = false;
      try { histLand(got, asked); }
      catch (err) {
        histBad = true;
        histSay = 'that page would not draw: '
          + String((err && err.message) || err).slice(0, 40);
        histPaint();
      }
    }, function (err) {
      /* #1200: A PAGE THAT NEVER ARRIVED IS NOT THE END OF THE LIST, and
         it must never read like one. `histMore` is left TRUE, the note
         says what went wrong and says to try again, and the next reach at
         the old end asks again. A failure that looked like the end would
         quietly teach him there is no more history when there is. */
      histBusy = false;
      histBad = true;
      histSay = 'that page did not arrive: '
        + String((err && err.message) || err).slice(0, 34) + ' - scroll again';
      histPaint();
    });
  }

  function histLand(got, asked) {
    var rows = (got && got.rows) || [];
    var fresh = [];
    var oldest = 0;
    var i;
    for (i = 0; i < rows.length; i += 1) {
      var r = rows[i] || {};
      var id = String(r.id || '');
      var ts = Number(r.ts) || 0;
      if (ts > 0 && (!oldest || ts < oldest)) oldest = ts;
      if (!id) continue;
      var key = ts + '|' + id;
      if (histSeen[key]) continue;
      histSeen[key] = 1;
      /* A history row is an airing, not another live queue entry. Keep it
       * even when the same id is currently on the strip: a clip that really
       * recurred must remain visible in the operator's last-three history. */
      fresh.push({key: key, id: id, ts: ts,
                  url: String(r.url || ''),
                  sting: String(r.name || id),
                  video: histVideo(r),                    /* #1199/#1200 */
                  plays: Number(r.plays) || 0,
                  seconds: 0, when: 'past'});
    }
    /* The cursor moves on what the STATION sent, not on what survived the
       dedupe - a page that was entirely repeats must still walk backwards
       or the next ask is the same ask. */
    if (oldest > 0) histAt = oldest;
    fresh.reverse();                   /* newest-first on the wire; the
                                          strip runs oldest-left */
    if (!fresh.length) {
      histMore = false;
      histSay = rows.length
        ? 'that is as far back as the ledger goes'
        : 'that is the whole history - nothing older';
      histPaint();
      return;
    }
    histMore = (got && typeof got.more === 'boolean')
      ? !!got.more
      : rows.length >= (Number(asked) || HIST_PAGE); /* an older station */
    histSay = histMore ? '' : 'that is the whole history - nothing older';
    hist = fresh.concat(hist);
    histDraw(fresh.length);
  }

  /* #1200: PUT THE NEW TILES IN AND KEEP HIS PLACE.
   *
   * "keeps the tiles already drawn" - so nothing already in the strip is
   * rebuilt. Only the new rows are built, and they go in AHEAD of
   * everything, just after the note that always sits at the old end.
   *
   * PREPENDING MOVES THE VIEW. Tiles inserted at the left push what he is
   * looking at to the right by exactly the width they took, and scrollLeft
   * is measured from the left - so without the correction below the strip
   * jumps and he loses his place mid-flick. It is MEASURED as the change
   * in scrollWidth rather than computed from a tile width, because the
   * gap, the borders and the note all count and none of them are the
   * number a guess would use. */
  function histDraw(count) {
    var strip = stripEl;
    /* A page that landed after the sheet was closed still counts against
       the ceiling: the rows are held, so they must be bounded, and there
       is no strip to cut tiles out of. */
    if (!strip) { histCeiling(); histPaint(); return; }
    var wide = Number(strip.scrollWidth) || 0;
    var ref = (strip.children && strip.children.length > 1)
      ? strip.children[1] : null;
    var say = stripSay || function () {};
    for (var i = 0; i < count; i += 1) {
      if (!hist[i]) continue;
      strip.insertBefore(stripTile(hist[i], false, say), ref);
    }
    var grew = (Number(strip.scrollWidth) || 0) - wide;
    if (grew > 0) {
      try { stripPlace(strip, (Number(strip.scrollLeft) || 0) + grew); }
      catch (err) { /* nothing scrolls here */ }
    }
    histCeiling();
    histPaint();
  }

  /* #1200: THE CEILING, AND WHAT HAPPENS WHEN HE KEEPS GOING PAST IT.
   *
   * Past HIST_MOST rows the window SLIDES rather than the strip growing
   * without end: the NEWEST fetched rows are let go - the ones nearest the
   * live tiles, which he has already scrolled past - and their cached
   * pictures go with them, which is what binds the poster cache to the
   * rows. The cycle's own tiles are never touched by this; they are the
   * last heard, the one on the tube and what is rung ahead, they are
   * rebuilt from the rings every time, and they are his place in the
   * night.
   *
   * IT IS NOT DONE QUIETLY. A seam tile sits where the let-go rows were,
   * saying how many went, and it is a real button that puts the strip back
   * to now. A gap nobody is told about is the kind of thing this station
   * treats as a fault in its own right. */
  function histCeiling() {
    if (hist.length <= HIST_MOST) return;
    var over = hist.length - HIST_MOST;
    var gone = hist.splice(hist.length - over, over);
    histCut(gone.length);
    for (var i = 0; i < gone.length; i += 1) shotForget(gone[i]);
    shotSweep();                                           /* #1200 */
    histLost += gone.length;
    if (!stripEl) return;
    var seam = histSeamEl();
    if (seam) { histSeamWord(seam); return; }
    stripEl.insertBefore(histSeam(), seamBefore());
  }

  /* The last N tiles of the HISTORY run, taken out of the strip. Found by
     walking the children and reading the class rather than by holding the
     elements in a list - #1312's rule in this file is that nothing keeps a
     list of elements, and a walk of a hundred and twenty nodes once every
     five pages is not a cost worth breaking it for. */
  function histCut(many) {
    var strip = stripEl;
    if (!strip || !many || !strip.children) return;
    var left = many;
    for (var i = strip.children.length - 1; i >= 0 && left > 0; i -= 1) {
      var el = strip.children[i];
      var cls = String((el && el.className) || '');
      if (cls.indexOf('sfx-tv-hist') < 0) continue;
      strip.removeChild(el);
      left -= 1;
    }
  }

  function histSeamEl() {
    var strip = stripEl;
    if (!strip || !strip.children) return null;
    for (var i = 0; i < strip.children.length; i += 1) {
      var el = strip.children[i];
      if (String((el && el.className) || '').indexOf('sfx-tv-seam') >= 0) {
        return el;
      }
    }
    return null;
  }

  /* Where the seam belongs: immediately after the last history tile. */
  function seamBefore() {
    var strip = stripEl;
    if (!strip || !strip.children) return null;
    var last = -1;
    for (var i = 0; i < strip.children.length; i += 1) {
      var cls = String((strip.children[i] && strip.children[i].className) || '');
      if (cls.indexOf('sfx-tv-hist') >= 0) last = i;
    }
    return (last >= 0 && strip.children[last + 1]) ? strip.children[last + 1] : null;
  }

  /* The Carbon mark, and only ever a Carbon mark: pineIcon('c:name'),
     guarded, because a surface with no icon sheet loaded must still read.
     The children are taken out by hand before the markup goes in - a real
     DOM would drop them with the innerHTML write, and saying it out loud
     costs one line and makes the function true everywhere. */
  function markOn(box, ref) {
    if (!box) return;
    while (box.children && box.children.length) {
      box.removeChild(box.children[box.children.length - 1]);
    }
    var mark = '';
    try {
      if (typeof root.pineIcon === 'function') mark = root.pineIcon(ref, '') || '';
    } catch (err) { mark = ''; }
    box.innerHTML = mark;
  }

  function histSeamWord(seam) {
    if (!seam) return;
    markOn(seam, 'c:renew');
    var word = document.createElement('i');
    word.className = 'sfx-tv-oldword';
    word.textContent = histLost + ' newer let go';
    seam.appendChild(word);
    seam.title = histLost + ' newer history tiles were let go to keep the '
      + 'strip small. Tap to forget the history and start again from now.';
  }

  function histSeam() {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'sfx-tv-seam';
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      histReset();
      stripFill();
      if (stripSay) stripSay('the strip is back at now');
    });
    histSeamWord(b);
    return b;
  }

  /* #1200: THE CONTROL AT THE OLD END - three states that must never look
     alike. A page in flight, the end of the ledger and a page that FAILED
     are one spinning tile if nobody writes them down, and the third of
     those silently teaches him there is no more history when there is.
     A real button: a sideways drag or wheel can reach it, and tapping it
     explicitly pulls the next two older entries. */
  function histNote() {
    var box = document.createElement('button');
    box.type = 'button';
    box.className = 'sfx-tv-oldend';
    box.addEventListener('click', function (ev) {
      ev.preventDefault(); ev.stopPropagation();
      histFetch(HIST_PAGE);
    });
    histWord(box);
    return box;
  }

  function histWord(box) {
    if (!box) return;
    var text = histSay;
    if (!text) text = histMore ? 'scroll back for more' : 'no more history';
    var ref = histBad ? 'c:warning--alt'
      : (histBusy ? 'c:hourglass' : (histMore ? 'c:time' : 'c:checkmark'));
    markOn(box, ref);
    var word = document.createElement('i');
    word.className = 'sfx-tv-oldword';
    word.textContent = text;
    box.appendChild(word);
    box.title = text;
  }

  function histPaint() { histWord(histNoteEl); }

  function histReset() {
    for (var i = 0; i < hist.length; i += 1) shotForget(hist[i]);
    hist = [];
    histSeen = Object.create(null);
    histAt = 0;
    histMore = true;
    histBusy = false;
    histBad = false;
    histSay = '';
    histLost = 0;
  }

  /* #1200: THE WHEEL OVER THE STRIP SCROLLS THE STRIP, AND NOTHING ELSE.
   *
   * A mouse wheel reports deltaY; a trackpad's sideways gesture reports
   * deltaX. Whichever of the two is larger is the one he meant, so both
   * roll the strip and neither has to be configured.
   *
   * preventDefault is UNCONDITIONAL and that is the whole point of it.
   * Without it a wheel at either end of the strip hands the gesture on,
   * and what takes it is the sheet - which is overflow-y:auto where it is
   * opened over the LISTEN wall - or the page underneath. "It must not
   * scroll the sheet or the page underneath" is not a preference; a strip
   * that slides the menu out from under the pointer is unusable.
   *
   * deltaMode 1 is LINES and 2 is PAGES, not pixels. Firefox and several
   * mice send 1, and treating a delta of 3 as three pixels is what makes a
   * wheel handler look dead to everyone who tests it on the wrong mouse. */
  function stripWheel(ev) {
    var strip = stripEl;
    try { if (ev && ev.preventDefault) ev.preventDefault(); }
    catch (err) { /* a passive listener somewhere up the tree */ }
    try { if (ev && ev.stopPropagation) ev.stopPropagation(); }
    catch (err) { /* nothing above us cares */ }
    if (!strip) return;
    var dx = Number(ev && ev.deltaX) || 0;
    var dy = Number(ev && ev.deltaY) || 0;
    var by = Math.abs(dx) > Math.abs(dy) ? dx : dy;
    var mode = Number(ev && ev.deltaMode) || 0;
    if (mode === 1) by *= 16;
    else if (mode === 2) by *= 320;
    if (!by) return;
    var want = (Number(strip.scrollLeft) || 0) + by;
    if (want < 0) want = 0;
    try { strip.scrollLeft = want; } catch (err) { /* nothing scrolls here */ }
    /* Toward the past AND already against the old end: that is the reach
       the operator asked to keep loading on. It is asked on the GESTURE
       and not only on a scroll event, because a strip holding five tiles
       cannot scroll at all - there a wheel would fire no scroll event and
       the history would never arrive however long he rolled. */
    if (by < 0 && (Number(strip.scrollLeft) || 0) <= HIST_NEAR) histFetch();
  }

  /* #1200: AND THE TABLET, WHICH HAS NO WHEEL. The touch gesture there is
     a plain sideways drag along the strip: `touch-action: pan-x` (set both
     inline and in sfx-tv.css) hands it to the WebView's own scroller, with
     its own momentum, so there is no touch code here to go wrong and the
     drag can never become the sheet's vertical scroll or a drag of the
     set. It cannot fight the hot corners either - hot-corners.js's
     _overControl walks up from the press, every tile is a real <button>
     and every ancestor of this strip carries the `sfx-tv` class that its
     OWNED list names, so a finger landing in one of the four 110 px corner
     squares over this strip scrolls and never gestures. This is the road
     that page arrives on there. */
  function stripScrolled() {
    var strip = stripEl;
    if (!strip) return;
    var at = Number(strip.scrollLeft) || 0;
    /* Positioning the popup at NOW and preserving the viewed tile after a
       prepend both produce real browser scroll events. They are not a
       request for another page. Remember the exact clamped position owed by
       that assignment and consume only that event; a finger that moves to a
       different position remains an ordinary history gesture. */
    if (stripOwedLeft !== null && Math.abs(at - stripOwedLeft) <= 1) {
      stripOwedLeft = null;
      return;
    }
    stripOwedLeft = null;
    if (at <= HIST_NEAR) histFetch();
  }

  function stripPlace(strip, wanted) {
    var most = Math.max(0, (Number(strip.scrollWidth) || 0)
      - (Number(strip.clientWidth) || 0));
    stripOwedLeft = Math.max(0, Math.min(most, Number(wanted) || 0));
    strip.scrollLeft = wanted;
  }

  function stripBuild(clip, say) {
    var strip = document.createElement('div');
    strip.className = 'sfx-tv-strip';
    strip.style.display = 'flex'; strip.style.gap = '5px';
    strip.style.overflowX = 'auto'; strip.style.overflowY = 'hidden';
    strip.style.margin = '0 0 6px 0'; strip.style.paddingBottom = '2px';
    strip.style.touchAction = 'pan-x';                     /* #1200 */
    strip.style.overscrollBehaviorX = 'contain';           /* #1200 */
    strip.addEventListener('wheel', stripWheel, {passive: false});
    strip.addEventListener('scroll', stripScrolled);
    stripEl = strip;
    stripOwedLeft = null;
    stripClip = clip || null;
    stripSay = (typeof say === 'function') ? say : function () {};
    stripFill();
    if (!hist.length && histMore && !histBusy) histFetch(STRIP_PAST);
    return strip;
  }

  /* The strip's contents, oldest on the left: the note at the old end, the
     history already fetched, the seam if the ceiling has cut, then the
     cycle's own tiles - the last heard, the one on the tube, what is rung
     ahead. Called on a build and again when the seam puts him back at now;
     a page does NOT come through here, because a page must keep every tile
     already drawn. */
  function stripFill() {
    var strip = stripEl;
    if (!strip) return;
    while (strip.children && strip.children.length) {
      strip.removeChild(strip.children[strip.children.length - 1]);
    }
    var rows = stripRows();
    var here = stripClip ? clipId(stripClip) : '';
    var say = stripSay || function () {};
    var i;
    histNoteEl = histNote();
    strip.appendChild(histNoteEl);
    for (i = 0; i < hist.length; i += 1) {
      strip.appendChild(stripTile(hist[i], false, say));
    }
    if (histLost > 0) strip.appendChild(histSeam());
    if (!rows.length && !hist.length) {
      var none = document.createElement('i');
      none.className = 'sfx-tv-note';
      none.textContent = 'nothing else in the cycle yet';
      strip.appendChild(none);
      return;
    }
    for (i = 0; i < rows.length; i += 1) {
      strip.appendChild(stripTile(rows[i], rows[i].id === here, say));
    }
    /* The live tiles are at the RIGHT end, because history grows leftwards
       - so the sheet opens showing NOW rather than wherever he had
       scrolled back to the last time he opened it. The browser clamps
       this to the real width; a strip that does not overflow stays at 0
       and fires no scroll event, which is why opening the sheet does not
       quietly ask the station for a page nobody wanted. */
    try { stripPlace(strip, 1e7); } catch (err) { /* nothing scrolls here */ }
  }

  /* #1184: JUMPING, FORWARD AND BACK, AND WHAT EACH MEANS TO THE CYCLE.
   *
   * Both go through cut(), which is the road Next, Prev and the run
   * already take - the note above `replays` says why there must not be a
   * second one. What differs is what happens to the PLAN around them:
   *
   *   FORWARD, to a clip the station has rung ahead: he is bringing its
   *   moment closer. It is taken OUT of the queue (it is about to play)
   *   and the rest of the plan is put back afterwards, so the cycle
   *   carries on with what is still to come instead of being emptied.
   *
   *   BACK, to a clip already played: that clip's slot is in the past
   *   and the station has no plan for it. It is a replay ALONGSIDE the
   *   cycle, not a rewind of it - the queue is untouched entirely and
   *   the set rejoins the plan when this one ends.
   *
   * Either way the clip is handed over as a PLAIN object with no `at`
   * and no `endless` flag. That is deliberate: airInto() reads `at` to
   * put an endless clip where the station is, and a stamp minutes old
   * would compute a seek far past the end of the file - guarded when the
   * duration is known and NOT guarded in the moment before it is. A clip
   * he asked for by name belongs at its own first frame. */
  function jump(row, say) {
    if (!row || !row.url) { say('nothing to jump to'); return; }
    var rest = queue.slice();
    var i;
    for (i = rest.length - 1; i >= 0; i -= 1) {
      if (rest[i] && String(rest[i].url) === String(row.url)) rest.splice(i, 1);
    }
    var fresh = {id: row.id, url: row.url, sting: row.sting,
                 seconds: Number(row.seconds) || 0, video: !!row.video};
    say('putting it on...');
    if (wallSelect(fresh)) return;
    if (!root.PineSfxTv.cut(fresh, {})) { say('it would not open'); return; }
    /* cut() emptied the queue; the rest of the plan goes back behind it
       so the cycle resumes rather than waiting for the next ring-ahead.
       A clip whose slot has passed while this one plays is dropped by
       next()'s own missed() test, which is the right answer and not
       this function's business. */
    for (i = 0; i < rest.length; i += 1) queue.push(rest[i]);
  }

  /* The sheet itself: a tap on the picture opens it (a hold did, until
   * #1121 gave the hold to the sampler question).
   *
   * #1184: `at` is {x, y} when it was opened by a right-click or a hold
   * over the LISTEN view's wallpaper, where this set is veiled and a
   * sheet inside it could be neither seen nor touched. Null means the
   * old road - inside the set, where it has always lived. */
  /* ============ [#1243] GLUE, and [#1223] EDIT ====================== */

  /* One join at a time. The station runs it on a thread and will happily
     take a second; two joins of overlapping clips would race each other
     to supersede the same original, and the second answer would win for
     no reason anybody could name. */
  var glueBusy = false;
  var editorBox = null;
  var editorGone = null;

  function glueIcon(ref, label) {
    return (typeof root.pineIcon === 'function'
      ? root.pineIcon(ref, label) : '') || '';
  }

  /* The same road srcOf() takes: `base` is empty on the panel and on the
     tune page, where the document IS the station, and set by the desktop
     shell where it is not. */
  function glueUrl(path) {
    return base.replace(/\/+$/, '') + String(path || '');
  }

  function glueState(id) {
    var bridge = api();
    if (!id) return Promise.reject(new Error('no id on this clip'));
    if (!bridge || !bridge.get) return Promise.reject(new Error('no bridge'));
    return bridge.get('/api/sfx/glue/state?id=' + encodeURIComponent(id));
  }

  /* [#1243] The join runs at the station on its own thread, so this reads
     its job rather than holding a request open across the tablet bridge -
     which gives up at twenty seconds, and a re-encode of two clips took
     eleven. `say` carries the station's own words the whole way. */
  function glueWatch(jobId, say, land) {
    var bridge = api();
    var tries = 0;
    if (!jobId || !bridge || !bridge.get) { say('the join has no job to watch'); return; }
    var tick = function () {
      tries += 1;
      if (tries > 400) {
        glueBusy = false;
        say('the join is still running at the station - reopen this in a moment');
        return;
      }
      bridge.get('/api/sfx/glue/job?id=' + encodeURIComponent(jobId)).then(
        function (job) {
          var state = String((job && job.state) || '');
          say(String((job && job.say) || 'joining...'));
          if (state === 'done') { land(job && job.clip); return; }
          if (state === 'failed') { glueBusy = false; return; }
          setTimeout(tick, 900);
        },
        function (err) {
          glueBusy = false;
          say(String((err && err.message) || err).slice(0, 48));
        });
    };
    setTimeout(tick, 700);
  }

  function glueGo(clip, side, say, at, rail) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    if (glueBusy) { say('one join at a time - the last one is still running'); return; }
    glueBusy = true;
    if (rail) rail.classList.add('working');
    say(side === 'prev' ? 'gluing it to the one before...'
                        : 'gluing it to the next one...');
    var land = function (made) {
      glueBusy = false;
      if (!made || !made.id) {
        say('the join finished but the station did not name the clip');
        return;
      }
      /* "the popup then shows the glued clip" - the same door a strip
         tile takes: through sheetClose() first, then open for the new
         clip at the same place on the screen. */
      sheetClose();
      sheet({id: made.id, url: made.url, sting: made.sting,
             seconds: made.seconds, video: true}, at);
    };
    post('/api/sfx/glue', {clip: id, direction: side}).then(function (got) {
      if (!got || !got.ok) {
        glueBusy = false;
        if (rail) rail.classList.remove('working');
        say(String((got && got.say) || 'it would not glue'));
        return;
      }
      /* Idempotent at the station: the same pair pressed twice hands back
         the clip that is already there instead of making a second one. */
      if (got.clip) { land(got.clip); return; }
      glueWatch(String(got.job || ''), say, land);
    }, function (err) {
      glueBusy = false;
      if (rail) rail.classList.remove('working');
      say(String((err && err.message) || err).slice(0, 48));
    });
  }

  /* [#1243] The two rails. Pinned to the sheet's left and right edges,
     which is where the operator drew them, and the sheet is given side
     padding so they sit beside the button rows rather than over them. */
  function glueRails(wrap, clip, say, at) {
    var made = {};
    ['prev', 'next'].forEach(function (side) {
      var rail = document.createElement('button');
      rail.type = 'button';
      rail.className = 'sfx-tv-glue sfx-tv-glue-' + side;
      rail.setAttribute('aria-disabled', 'true');
      rail.dataset.ready = '';
      rail.dataset.why = 'asking the station what is next door...';
      rail.innerHTML = glueIcon(side === 'prev' ? 'c:caret--left' : 'c:caret--right',
                                'Glue') + '<i>GLUE</i>';
      rail.title = rail.dataset.why;
      rail.addEventListener('click', function (ev) {
        ev.stopPropagation();
        /* Not `disabled`: a disabled button on a touch screen swallows the
           tap AND its own title, so the reason never reaches the operator.
           This one always answers. */
        if (rail.dataset.ready !== '1') {
          say(rail.dataset.why || 'nothing next door to glue to');
          return;
        }
        glueGo(clip, side, say, at, rail);
      });
      wrap.appendChild(rail);
      made[side] = rail;
    });
    wrap.classList.add('sfx-tv-hasglue');
    var fail = function (why) {
      ['prev', 'next'].forEach(function (side) {
        made[side].dataset.why = why;
        made[side].title = why;
      });
    };
    glueState(clipId(clip)).then(function (got) {
      if (!got || !got.ok) { fail(String((got && got.say) || 'the station would not say')); return; }
      ['prev', 'next'].forEach(function (side) {
        var rail = made[side];
        var one = got[side] || {};
        if (!one.ok) {
          rail.dataset.ready = '';
          rail.dataset.why = String(one.why || 'nothing that way in this folder');
          rail.title = rail.dataset.why;
          rail.classList.add('off');
          rail.innerHTML = glueIcon('c:misuse', 'No clip that way') + '<i>NONE</i>';
          return;
        }
        rail.dataset.ready = '1';
        rail.setAttribute('aria-disabled', 'false');
        rail.title = 'Glue this clip to ' + String(one.name || 'the clip that way')
          + (one.seconds ? ' (' + Number(one.seconds).toFixed(1) + 's)' : '')
          + ' - one longer clip. Neither original is deleted.'
          + (one.done ? ' Those two are already glued; this opens it.' : '');
        rail.innerHTML = glueIcon(side === 'prev' ? 'c:caret--left' : 'c:caret--right',
                                  'Glue') + '<i>' + (one.done ? 'GLUED' : 'GLUE') + '</i>';
      });
      if (got.superseded) {
        say('a longer clip already stands in front of this one');
      }
    }, function (err) {
      fail(String((err && err.message) || err).slice(0, 60));
    });
    return made;
  }

  /* ---------------- [#1223] the editor over the set ------------------ */

  function editorClose() {
    if (editorGone) { try { editorGone(); } catch (err) { /* going */ } editorGone = null; }
    if (editorBox && editorBox.parentNode) editorBox.parentNode.removeChild(editorBox);
    editorBox = null;
  }

  function editorWindow(path, say, clip, after) {
    editorClose();
    var box = document.createElement('div');
    box.className = 'sfx-tv-editor sfx-tv';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Edit this clip');
    var bar = document.createElement('div');
    bar.className = 'sfx-tv-editorbar';
    var title = document.createElement('b');
    title.textContent = String((clip && (clip.sting || clip.text)) || 'this clip');
    var shut = document.createElement('button');
    shut.type = 'button';
    shut.textContent = 'Close editor';
    shut.addEventListener('click', function (ev) {
      ev.stopPropagation(); editorClose();
    });
    bar.appendChild(title);
    bar.appendChild(shut);
    var frame = document.createElement('iframe');
    frame.className = 'sfx-tv-editorframe';
    frame.title = 'Edit this clip';
    frame.setAttribute('allow', 'autoplay; fullscreen');
    frame.src = glueUrl(path);
    box.appendChild(bar);
    box.appendChild(frame);
    box.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    document.body.appendChild(box);
    editorBox = box;
    /* The standing rule: 10% while an editing surface is open. #1172 is in
       this station's history because this very editor was the one surface
       that did not take the hold, and a clip played behind the window the
       operator was editing a clip in. */
    try {
      var duck = root.PineDuck;
      if (duck && typeof duck.hold === 'function') {
        var off = duck.hold('sfx-clip-editor', 0.1, box);
        editorGone = (typeof off === 'function') ? off : null;
      }
    } catch (err) { /* the editor still opens */ }
    var heard = function (ev) {
      if (!editorBox || ev.source !== frame.contentWindow) return;
      var kind = ev.data && ev.data.type;
      if (kind === 'pine-video-editor-close') { editorClose(); return; }
      if (kind === 'pine-sfx-edit-saved') {
        var detail = ev.data.detail || {};
        say(String(detail.say || 'saved'));
        editorClose();
        if (after) after(detail);
      }
    };
    root.addEventListener('message', heard);
    var older = editorGone;
    editorGone = function () {
      root.removeEventListener('message', heard);
      if (older) older();
    };
  }

  /* [#1223] "an option for edit that brings up a pop-up window where I can
     adjust the in and out points of the clip". The station adopts the clip
     into its own video editor - the one mounted at /video-editor/ - and
     answers with the sentence about where a save will land, which is the
     honest part: most of these clips are on a share this container has
     mounted read-only and cannot write to at all. */
  function editClip(clip, say, at) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    say('opening the editor on this clip...');
    post('/api/sfx/edit/open', {clip: id}).then(function (got) {
      if (!got || !got.ok || !got.editor_url) {
        say(String((got && got.say) || 'the editor would not take this clip'));
        return;
      }
      say(String(got.say || 'opening...'));
      editorWindow(String(got.editor_url), say, clip, function (detail) {
        var made = detail && detail.clip;
        if (!made || !made.id) return;
        /* An edit that landed BESIDE the original is a different clip, so
           the sheet reopens on the one that will go out from now on. An
           in-place save keeps the same id and the sheet simply stays. */
        if (String(made.id) === String(id)) return;
        sheetClose();
        sheet({id: made.id, url: made.url, sting: made.sting,
               seconds: made.seconds, video: made.video}, at);
      });
    }, function (err) {
      say(String((err && err.message) || err).slice(0, 60));
    });
  }

  var shuffleFlight = null;
  function shuffleRecentIds() {
    var out = [];
    var have = Object.create(null);
    var add = function (value) {
      var id = typeof value === 'string' ? value : clipId(value || {});
      id = String(id || '');
      if (!id || have[id]) return;
      have[id] = true;
      out.push(id);
    };
    add(playing);
    for (var key in marks) if (Object.prototype.hasOwnProperty.call(marks, key)) add(key);
    for (var i = hist.length - 1; i >= 0 && out.length < 400; i -= 1) add(hist[i]);
    for (i = coming.length - 1; i >= 0 && out.length < 400; i -= 1) add(coming[i]);
    for (i = queue.length - 1; i >= 0 && out.length < 400; i -= 1) add(queue[i]);
    return out.slice(0, 400);
  }

  /* The dice is a pool rebuild, not Next wearing another label. The server
     rescans/indexes behind an immediate fresh batch; both renderers throw
     away their warmed runway while retaining recent-play exclusions. */
  function shuffleSet(say) {
    if (shuffleFlight) { say('the new clip pool is already being built...'); return shuffleFlight; }
    if (!api() || typeof api().post !== 'function') {
      say('the station is not connected');
      return null;
    }
    var recent = shuffleRecentIds();
    say('reshuffling the full FFX deck without repeating spent clips...');
    shuffleFlight = api().post('/api/sfx/video/shuffle', {
      exclude: recent,
      most: 8,
      who: 'operator dice'
    }).then(function (got) {
      var clips = (got && got.clips) || [];
      if (!clips.length) {
        say(String((got && got.say) || 'no fresh clips cleared the recent-play guard'));
        return got;
      }
      queue.length = 0;
      coming.length = 0;
      warmDrop();
      runLeft = 0; runFrom = ''; replays = 0;
      var first = clips[0];
      var reset = wallAsk('shuffle', {exclude: recent, clips: clips});
      Promise.resolve(reset).then(function () {
        if (wallRunning()) {
          sheetClose();
          return;
        }
        for (var i = 1; i < clips.length; i += 1) queue.push(clips[i]);
        sheetClose();
        if (root.PineSfxTv && root.PineSfxTv.cut) root.PineSfxTv.cut(first);
      });
      return got;
    }, function (err) {
      say('the library rebuild failed: ' + String((err && err.message) || err).slice(0, 80));
      throw err;
    });
    shuffleFlight.then(function () { shuffleFlight = null; }, function () { shuffleFlight = null; });
    return shuffleFlight;
  }

  var sheetAt = null;
  function sheet(clip, at) {
    /* [#1441] A WALL SHEET DOES NOT HANG OFF THE SET'S FRAME. When `at`
       is given this is the #1184 sheet, mounted on the BODY further down
       precisely because the set it belongs to may be veiled - or, since
       the picture went native, may never have been built at all. Guarding
       both kinds on `host` meant a tap on the native picture opened
       nothing, which is exactly what was reported. */
    if (!host && !at) return;
    /* #1112: a second hold shuts it - through the one door, so a clip
       that ended under the sheet is finished now, not left standing. */
    if (sheetHeld()) { sheetClose(); return; }
    sheetAt = at || null;                                  /* #1184 */
    surfaceDown(true);                                   /* [#1386b] */
    var onWall = !!at;
    /* #1184: is this sheet about the clip that is actually on the tube?
       A tile in the strip opens this same sheet for a NEIGHBOUR, and the
       two roads that take the picture down - a delete and a ban - must
       not do that on behalf of a clip that is not on screen. */
    var mine = !!(playing && clipId(clip) === clipId(playing));
    var wrap = document.createElement('div');
    /* The `sfx-tv` token is not decoration. hot-corners.js's _overControl
       treats that class as a surface with gestures of its own, so a tap
       anywhere on this sheet - including in one of the four 110 px corner
       squares - is never also a corner gesture. The alternative was
       editing the exemption list in that file for a menu it has no other
       reason to know about. */
    wrap.className = onWall ? 'sfx-tv-sheet sfx-tv sfx-tv-wall'
                            : 'sfx-tv-sheet';
    var name = document.createElement('b');
    name.textContent = String(clip.sting || clip.text || 'this clip')
      + (mine ? '' : '  -  not the one on the tube');
    var note = document.createElement('i');
    note.className = 'sfx-tv-note';
    note.textContent = '';
    var say = function (text) { note.textContent = String(text || ''); };
    var rowA = document.createElement('div');
    rowA.className = 'sfx-tv-sheetrow';
    /* FULL SCREEN IS ONE COMMAND. The old sheet built a native-wall button
       here and a second web-frame button beside Prev/Next. Their state could
       disagree, which is how one menu showed both "full screen" and
       "Windowed" at once. This button owns the preference, both renderers,
       and the release of the held playlist. */
    var fullBtn = document.createElement('button');
    fullBtn.className = 'sfx-tv-full-toggle';
    var wentFull = fullWanted();
    function fullLabel() { fullBtn.textContent = wentFull ? 'Windowed' : 'Full screen'; }
    function closeAfter(going) {
      if (going && typeof going.then === 'function') {
        going.then(function () { sheetClose(); }, function () { sheetClose(); });
      } else {
        sheetClose();
      }
    }
    fullBtn.onclick = function (ev) {
      if (ev && ev.stopPropagation) ev.stopPropagation();
      wentFull = !wentFull;
      setFull(wentFull);
      fullLabel();
      say(wentFull ? 'full screen - the endless set is running'
                   : 'back to the size you dragged it to');
      /* `full` and `window` atomically release the native menu hold. Closing
         the HTML sheet afterwards also frees older builds and the web set. */
      closeAfter(wallAsk(wentFull ? 'full' : 'window',
                         wentFull ? null : nativeWallRect()));
    };
    fullLabel();
    rowA.appendChild(fullBtn);
    var rowB = document.createElement('div');
    rowB.className = 'sfx-tv-sheetrow';
    /* #1112: a third row for the two that take the picture away, so
       the labels stay short enough for a 420 px set on the tablet. */
    var rowC = document.createElement('div');
    rowC.className = 'sfx-tv-sheetrow sfx-tv-sheet-close';

    /* #1112: a delete or a ban is the end of this clip's time on the
       set: the note is left long enough to read, then the sheet goes
       through the one door and the picture is brought down - whether
       the clip had already ended under the sheet or is still running
       off its buffer. Nothing happens if the operator closed the sheet
       by hand in the meantime. */
    function finishUp() {
      setTimeout(function () {
        if (sheetWrap !== wrap) return;
        sheetClose();
        /* #1184: only for the clip that is on the tube. Deleting a
           NEIGHBOUR from its tile's sheet must not take down the picture
           of a different clip that is playing perfectly well. */
        if (!mine) return;
        if (curtain) { try { curtain(); } catch (err) { /* going */ } }
      }, 900);
    }


  /* [#1256] MAKE THE SHEET FIT THE PICTURE IT IS IN.
   *
   * He asked for it "scaled down so I'm able to get to the elements at the
   * top". A transform scale was the wrong tool - it blurs this panel's text
   * and leaves the touch targets where the unscaled layout put them. So the
   * sheet takes a step down in font, padding and gap instead, and only when
   * the room it has actually calls for it.
   *
   * Two passes, because one is not enough: `tight` may itself be enough, and
   * if it is not the body keeps its scroll and nothing is ever unreachable.
   * Both passes run off rAF so they measure a laid-out sheet rather than an
   * empty one. */
  function sheetFit(wrap, body) {
    var look = function () {
      if (!wrap || !wrap.parentNode) return;
      /* [#1256c] ROOM IS WHAT CAN BE SEEN, not what the host measures.
         offsetParent is ALWAYS null for a fixed element, so the wall's
         own sheet fell through to the body - 9969px tall on the kiosk
         page against a 690px screen - and never went tight at all. */
      var seen = 0;
      try { seen = root.innerHeight || 0; } catch (err) { seen = 0; }
      if (!seen) {
        seen = (document.documentElement
                && document.documentElement.clientHeight) || 0;
      }
      var fixed = false;
      try {
        fixed = getComputedStyle(wrap).position === 'fixed';
      } catch (err) { fixed = false; }
      var room = 0;
      if (fixed) {
        room = seen;
        /* the wall path pins its own ceiling inline; honour the smaller. */
        var cap = parseFloat(wrap.style.maxHeight || '') || 0;
        if (cap > 0 && cap < room) room = cap;
      } else {
        var host = wrap.offsetParent || wrap.parentNode;
        try {
          room = (host && host.getBoundingClientRect
                  ? host.getBoundingClientRect().height : 0) || 0;
        } catch (err) { room = 0; }
        /* a host taller than the screen is not room either. */
        if (seen > 0 && room > seen) room = seen;
      }
      if (room <= 0) return;
      /* 16px is the sheet's own top+bottom inset against the frame. */
      var allowed = Math.max(0, room - 16);
      var wanted = wrap.scrollHeight;
      /* Tightening changes scrollHeight. Removing the class as soon as the
         tightened sheet fits creates a ResizeObserver loop: wide, tight,
         wide, tight - visibly pulsing under the operator's finger. Fit is a
         one-way decision for this short-lived sheet. A fresh open measures
         again from the normal layout. */
      if (wanted > allowed) wrap.classList.add('sfx-tv-tight');
      /* Say so rather than leaving a silent scrollbar to be discovered. */
      try {
        var over = body.scrollHeight - body.clientHeight > 4;
        wrap.classList.toggle('sfx-tv-scrolls', !!over);
      } catch (err) { /* nothing to say */ }
    };
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(function () { look(); requestAnimationFrame(look); });
    } else {
      look();
    }
    /* The strip loads its pictures late and the glue rails answer the
     * station before they can say whether there is a neighbour, so the
     * sheet's height is not final at build. Watch it while it is open. */
    try {
      if (typeof ResizeObserver === 'function') {
        var ro = new ResizeObserver(look);
        ro.observe(wrap);
        if (body) ro.observe(body);
      }
    } catch (err) { /* the two passes above still ran */ }
  }

    function button(into, label, title, go) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.title = title;
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        go();
      });
      into.appendChild(b);
      return b;
    }

    /* #1184: THE TWO ITEMS THAT HAD NO BUTTON.
     *
     * Of the five things he asked for, three were already here: Inspect
     * is "examine the video", Where is it is "trace its location", and
     * Delete is "delete the video". What had no road was "see the path"
     * and "picture its neighbours" - so one new row of two, kept short
     * for the same reason the note above rowC gives: a 420 px set on the
     * tablet is what these labels have to fit inside.
     *
     * Play it is the third thing a tile must do - "tap them to jump to
     * them and play / examine / manage them as well" - and it appears
     * ONLY on a sheet opened for a clip that is not the one on the tube.
     * On the clip that is already playing it would be a button that does
     * nothing, which is the kind of thing this station treats as a
     * fault in its own right. */
    var rowF = document.createElement('div');
    rowF.className = 'sfx-tv-sheetrow';
    var icon = function (ref, label) {
      return (typeof root.pineIcon === 'function'
        ? root.pineIcon(ref, label) : '') || '';
    };
    var marked = function (b, ref, label) {
      b.innerHTML = icon(ref, label) + ' ' + b.textContent;
      return b;
    };
    /* [#1223] THE EMPTY SLOT LEFT OF PATH, which is where he drew the
       circle. Trim the in and out points and save it back: over the file
       itself when the station owns it, beside it under the station's own
       folder when the clip is on the read-only share - and the editor
       says which BEFORE the save, rather than failing at it. */
    marked(button(rowF, 'Edit', 'Trim the in and out points of this clip '
                  + 'and save it back',
                  function () { editClip(clip, say, at); }),
           'c:edit', 'Edit');
    marked(button(rowF, 'Shuffle', 'Rescan the FFX library and replace the '
                  + 'entire upcoming queue from the persistent no-repeat deck',
                  function () { shuffleSet(say); }),
           'm:casino', 'Shuffle clips');
    marked(button(rowF, 'Path', 'The real file path, in every spelling '
                  + 'the station knows, ready to copy',
                  function () { showPath(clip, wrap, say); }),
           'c:document', 'Path');
    if (!mine) {
      marked(button(rowF, 'Play it', 'Put this clip on the tube now',
                    function () {
                      jump({id: clipId(clip), url: String(clip.url || ''),
                            sting: String(clip.sting || ''),
                            seconds: Number(clip.seconds) || 0}, say);
                    }),
             'c:skip--forward--filled', 'Play it');
    }
    /* Fullscreen keeps a row of its own. Five controls shared this row on
       the tablet, compressing the primary action until the operator could
       not reliably hit it while the fit observer was settling. */
    var rowTools = document.createElement('div');
    rowTools.className = 'sfx-tv-sheetrow';
    button(rowTools, 'Inspect', 'What the station knows about this clip',
           function () { inspect(clip, say, wrap); });     /* #1184 */
    button(rowTools, 'Where is it', 'Show where this clip lives',
           function () { locate(clip, say); });
    var parodyButton = button(rowTools, '',
      'Dictate a Pine Box FM parody prompt for H3',
      function () { sheetClose(); parodyOpen(clip); });
    parodyButton.className = 'sfx-tv-parody-button';
    parodyButton.setAttribute('aria-label', 'Generate parody');
    parodyButton.innerHTML = (typeof root.pineIcon === 'function'
      ? (root.pineIcon('c:microphone', 'Generate parody') || '') : '') || 'MIC';
    button(rowTools, '\u25b2 More', 'Play it more often',
           function () { weigh(clip, true, say); });
    button(rowTools, '\u25bc Less', 'Play it less often',
           function () { weigh(clip, false, say); });
    button(rowB, 'Send to a pad', 'Put it on the first free sampler pad',
           function () { toPad(clip, say); });
    button(rowB, 'Never again', 'Keep the file but never play it on the air again',
           function () { ban(clip, say, finishUp); });
    var kill = button(rowB, 'Delete', 'Remove the file permanently',
      function () {
        /* The one action here that cannot be taken back, so it asks. */
        if (kill.dataset.sure !== '1') {
          kill.dataset.sure = '1';
          kill.textContent = 'Delete for good?';
          setTimeout(function () {
            if (!kill.isConnected) return;
            kill.dataset.sure = '';
            kill.textContent = 'Delete';
          }, 3000);
          return;
        }
        scrap(clip, say, finishUp);
      });
    kill.className = 'bad';
    var shut = button(rowC, 'Close', 'Put this away',
                      function () { sheetClose(); });      /* #1112 */
    shut.className = 'quiet';
    /* Android does not owe a synthetic click when a SurfaceView transition
       changes the composition tree under the finger. Pointer-up is the
       earliest complete tap and sheetClose() is deliberately idempotent. */
    shut.addEventListener('pointerup', function (ev) {
      ev.preventDefault(); ev.stopPropagation(); sheetClose();
    });
    /* #1309b: and the only way left to dismiss the picture itself,
       now that the title bar with its ✕ is gone. #1112: the sheet goes
       through the one door first; the set comes down at once after,
       which is what Stop has always meant. */
    var away = button(rowC, 'Stop', 'Take the picture off the screen',
      function () {
        /* #1121/#1124: Stop is the operator's own end of the run and of
           any replays owed - the one road, besides the slider at 0,
           that clears them. cut() never does. */
        runLeft = 0; runFrom = ''; replays = 0;
        sheetClose();
        try { teardownNow(); } catch (err) { /* already gone */ }
      });
    away.className = 'quiet';

    /* The clip beside this one either way. Fullscreen lives in row A now;
       there is deliberately no second stateful button here. */
    var rowD = document.createElement('div');
    rowD.className = 'sfx-tv-sheetrow';
    var tall = function (b) { b.style.minHeight = '32px'; return b; };
    tall(button(rowD, 'Prev', 'The clip before this one in its folder',
                function () { step(clip, 'prev', say); }));
    tall(button(rowD, 'Next', 'The clip after this one in its folder',
                function () { step(clip, 'next', say); }));

    /* #1124: THE RUN. "offer a slider for playing the next sequential
       clips. So I can basically expand it. So if I expand it to say
       seven, it plays that clip and the next seven clips in a row
       sequentially." The value is the module's `runLeft`, so a sheet
       opened on the third clip of a run shows what is still to come,
       and dragging it changes the run from here. */
    var rowE = document.createElement('div');
    rowE.className = 'sfx-tv-sheetrow';
    rowE.style.alignItems = 'center';
    var range = document.createElement('input');
    range.type = 'range';
    range.min = '0'; range.max = '12'; range.step = '1';
    range.value = String(runLeft > 0 ? runLeft : 0);
    range.setAttribute('aria-label', 'Play the next clips in the folder');
    range.style.flex = '1 1 52%'; range.style.minWidth = '0';
    range.style.minHeight = '32px'; range.style.margin = '0';
    range.style.accentColor = '#65c7da'; range.style.cursor = 'pointer';
    var count = document.createElement('i');
    count.className = 'sfx-tv-note';
    count.style.flex = '1 1 48%'; count.style.minHeight = '0';
    count.style.textAlign = 'right'; count.style.whiteSpace = 'nowrap';
    count.style.overflow = 'hidden'; count.style.textOverflow = 'ellipsis';
    count.style.color = '#dfe7ee'; count.style.fontSize = '11px';
    var wordFor = function (n) {
      return n > 0 ? 'then the next ' + n + ' in the folder' : 'just this one';
    };
    count.textContent = wordFor(Number(range.value) || 0);
    var chose = function () {
      var n = Math.max(0, Math.min(12, Math.round(Number(range.value) || 0)));
      count.textContent = wordFor(n);
      runLeft = n;
      runFrom = n > 0 ? clipId(clip) : '';
      paintBadge();
    };
    range.addEventListener('input', chose);
    range.addEventListener('change', chose);
    rowE.appendChild(range);
    rowE.appendChild(count);

    /* [#1243] the two glue rails, on the left and right edges of the
       sheet. Added before the name so they are underneath every row in
       paint order; the stylesheet pins them and pads the sheet aside. */
    glueRails(wrap, clip, say, at);
    /* [#1256] EVERYTHING BELOW THE RAILS GOES IN A BODY THAT CAN SCROLL.
       The sheet is pinned to the bottom of the frame and used to grow
       upward out of it once it held more than the frame is tall - which
       is how the rails' heads and the strip ended up off screen. The
       rails stay children of the sheet so they are pinned against the
       BOUNDED sheet; only this body scrolls. */
    var body = document.createElement('div');
    body.className = 'sfx-tv-sheetbody';
    body.appendChild(name);
    /* #1184: the cycle's own picture, directly under the clip's name and
       above every button - "show thumbnails of the last 2 videos played
       and the next 2 videos planned for play". It is what he is looking
       at, so it goes where the eye lands first. */
    body.appendChild(stripBuild(clip, say));
    body.appendChild(rowA);
    body.appendChild(rowTools);
    body.appendChild(rowF);                                /* #1184 */
    body.appendChild(rowB);
    body.appendChild(rowD);
    body.appendChild(rowE);
    body.appendChild(rowC);
    body.appendChild(note);
    wrap.appendChild(body);
    /* [#1256] ...and it tries to be small enough not to need the scroll.
       Measured after layout against the frame this sheet is actually in,
       because the same sheet is drawn on the desk, in the panel, on the
       tune page and on the tablet at four different sizes. */
    sheetFit(wrap, body);
    wrap.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    /* A right-click on the sheet itself is not a right-click on the
       video: the browser's own menu must not open over it either. */
    wrap.addEventListener('contextmenu', function (ev) {
      ev.preventDefault(); ev.stopPropagation();
    });
    if (!onWall) {
      host.appendChild(wrap);
      sheetOnWall = false;                                 /* #1184 */
      sheetWrap = wrap;                                    /* #1112 */
      sheetClear(wrap);                                    /* [#1386c] */
      return;
    }
    /* #1184: OVER THE WALL, AND OVER A FULL-BLEED PICTURE.
     *
     * VERIFIED RATHER THAN ASSUMED, because the trap here is real: an
     * element outside a genuine fullscreen element does not paint over
     * it at all, whatever its z-index. There is no genuine fullscreen
     * element on this station. Neither "full screen" road asks the
     * browser for one - setFull() above says so in its own note (the
     * kiosk WebView would refuse it without a gesture it can see) and
     * simply writes 100vw/100vh inline, and the LISTEN view's bare mode
     * is a class, `pl-bare`, that hides the panel over the wallpaper.
     * A grep of the whole renderer for requestFullscreen finds nothing.
     * So the body is a safe home today - and the line below asks for the
     * fullscreen element anyway, so it stays safe on the day somebody
     * does reach for the real API.
     *
     * The z-index is the hold-sheet band this file's own build() note
     * lists (2147483046): above every injected view on the kiosk, above
     * this set, and still under the lock screen and the boot splash. */
    var s = wrap.style;
    var W = root.innerWidth || 1280;
    var H = root.innerHeight || 800;
    var wide = Math.max(260, Math.min(420, W - 16));
    s.position = 'fixed';
    s.right = 'auto'; s.bottom = 'auto';
    s.width = wide + 'px';
    s.maxHeight = (H - 16) + 'px';
    s.overflowY = 'auto';
    s.zIndex = '2147483046';
    s.left = Math.max(8, Math.min(W - wide - 8,
                                  Math.round(Number(at.x) - wide / 2))) + 'px';
    s.top = '0px';
    var home = document.body;
    try { home = document.fullscreenElement || document.body; }
    catch (err) { home = document.body; }
    /* [#1450] THE WAY OUT GOES DOWN FIRST.
     *
     * The wall sheet used to be dismissed by a second tap on the
     * picture, and #1442 takes the picture away for exactly as long as
     * the sheet is up - so that tap could never arrive and the operator
     * was shut in. This shade is the page, not the surface, so it is
     * there whether or not the wall is. One z below the sheet, so the
     * sheet's own rows and rails still take their taps first. */
    var shade = document.createElement('div');
    shade.className = 'sfx-tv-shade sfx-tv';
    var ss = shade.style;
    ss.position = 'fixed';
    ss.left = '0px'; ss.top = '0px';
    ss.right = '0px'; ss.bottom = '0px';
    ss.background = 'transparent';
    ss.zIndex = '2147483045';
    shade.addEventListener('click', function (ev) {
      ev.stopPropagation();
      sheetClose();
    });
    home.appendChild(shade);
    sheetShade = shade;

    home.appendChild(wrap);
    sheetOnWall = true;                                    /* #1184 */
    sheetWrap = wrap;                                      /* #1112 */
    sheetClear(wrap);                                      /* [#1386c] */

    /* [#1450] and a visible way out, because "tap somewhere else" is a
       convention and this is a tablet. Carbon only (c:close--filled);
       see the icon rule. */
    var quit = document.createElement('button');
    quit.type = 'button';
    quit.className = 'sfx-tv-quit';
    quit.title = 'Close this menu';
    quit.setAttribute('aria-label', 'Close this menu');
    quit.innerHTML = (typeof root.pineIcon === 'function'
      ? (root.pineIcon('c:close--filled', 'Close') || '') : '') || 'x';
    var qs = quit.style;
    qs.position = 'absolute';
    qs.top = '4px';
    /* The app reserves 110 physical pixels in each corner for hot-corner
       gestures. Keep this visible escape outside that native claim so a tap
       reaches the menu instead of changing views. */
    qs.right = Math.ceil(128 / (Number(root.devicePixelRatio) || 1)) + 'px';
    qs.minWidth = '34px'; qs.minHeight = '34px';
    qs.display = 'flex'; qs.alignItems = 'center';
    qs.justifyContent = 'center';
    qs.background = 'transparent'; qs.border = '0';
    qs.color = '#dfe7ee'; qs.cursor = 'pointer';
    qs.zIndex = '3';
    quit.addEventListener('click', function (ev) {
      ev.stopPropagation();
      sheetClose();
    });
    quit.addEventListener('pointerup', function (ev) {
      ev.preventDefault(); ev.stopPropagation(); sheetClose();
    });
    wrap.appendChild(quit);
    /* Placed only once it has a height: above the finger where there is
       room for it, below it where there is not, and never off either
       edge. Measured after the append because a sheet whose rows depend
       on `mine` is not always the same height. */
    var tall = wrap.offsetHeight || 260;
    /* [#1444] A PRESS THAT IS THE PICTURE OPENS ON THE PICTURE.
     *
     * Above-the-finger is the right manner for a fingertip on a small
     * tube - the hand must not cover what it just opened. It is the
     * wrong manner when the press came from the native wall, where
     * there is no finger on the glass over that box: measured, a press
     * in the middle of a box at y 286..624 put a 353-tall sheet at y 87,
     * the top of the screen and clear of the window it describes.
     *
     * It may cover the picture because #1442 takes the picture away
     * whenever anything is laid across it, which is the whole reason
     * centring is available here and was not before. */
    var box = at.box;
    if (box && Number(box.width) > 0 && Number(box.height) > 0) {
      s.left = Math.max(8, Math.min(W - wide - 8, Math.round(
        Number(box.left) + Number(box.width) / 2 - wide / 2))) + 'px';
      s.top = Math.max(8, Math.min(H - tall - 8, Math.round(
        Number(box.top) + (Number(box.height) - tall) / 2))) + 'px';
      return;
    }
    var top = Math.round(Number(at.y) - tall - 14);
    if (top < 8) top = Math.round(Number(at.y) + 14);
    s.top = Math.max(8, Math.min(H - tall - 8, top)) + 'px';
  }

  /* #1411: THE NEXT CLIP IS FETCHED BEFORE ITS MOMENT.
   *
   * "Make sure the endless video icon is endless ... clip after clip
   *  after clip. It should ... cache a list and execute it fluidly in
   *  the background."
   *
   * The station now rings the list ahead (#1395) - three clips, each
   * stamped to start when the last one ends - and this set held them
   * as URLs only. At the moment, it built a <video>, set the src, and
   * waited for tens of megabytes to come over the link; on the desktop
   * that was measured as 24 of 39 seconds NOT playing, one dark run of
   * eleven seconds, between clips the station had handed over half a
   * minute earlier.
   *
   * So the head of the queue is warmed: a detached <video> with
   * preload=auto starts fetching it as soon as the tube reports
   * canplaythrough for the clip on screen (or a few seconds after its
   * first frame - a clip that never says canplaythrough must not hold
   * the next one back), and play() puts THAT element in the tube. One
   * warm element at a time, released when the clip is played, cut,
   * dropped as late or the set stops - #1312's rule about orphans that
   * hold connections stands, this just holds one on purpose. */
  /* #1411b: 1.5 s, not 4 - measured on the desktop, a six-second clip
     left the next one four seconds to arrive and it did not. */
  var WARM_AFTER_MS = 1500;

  function srcOf(clip) {
    return base.replace(/\/+$/, '') + String((clip && clip.url) || '');
  }

  /* #1421: THE CLIP IS IN MEMORY BEFORE IT IS ON THE TUBE.
   *
   * Measured: median clip 0.60 MB, largest 5.35 MB of 3,626. The whole
   * file is smaller than what a browser will buffer ahead on a stream,
   * so there is nothing for streaming to buy and a range request per
   * buffer to lose. Fetched whole, once, held as a blob; the element
   * plays an object URL and never touches the network again.
   *
   * Every part of this is an optimisation that is allowed to fail: on no
   * fetch, a refused fetch, a cross-origin shell without CORS or a clip
   * too big to hold, srcOf() is handed back and the set behaves exactly
   * as it did before. An optimisation that can fail the picture is not
   * one. */
  var CACHE_MOST = 10;                  // clips held at once
  var CACHE_BYTES_MOST = 48 * 1048576;  // and never more memory than this
  var CACHE_FILE_MOST = 24 * 1048576;   // a clip past this streams, as before
  var cache = [];                       // [{url, href, bytes, at}]
  var fetching = Object.create(null);   // url -> promise; asked once only

  function cacheFind(url) {
    var i;
    for (i = 0; i < cache.length; i += 1) {
      if (cache[i].url === url) { cache[i].at = now(); return cache[i]; }
    }
    return null;
  }

  /* The clip in the tube and the one warmed behind it are never let go,
     whatever the budget says - revoking either is a black tube. */
  function cacheHeld() {
    var keep = Object.create(null);
    try { if (video && video.src) keep[video.src] = 1; } catch (err) {}
    try { if (warm && warm.el && warm.el.src) keep[warm.el.src] = 1; }
    catch (err) {}
    return keep;
  }

  function cacheTrim() {
    var keep = cacheHeld();
    var bytes = 0, i;
    for (i = 0; i < cache.length; i += 1) bytes += cache[i].bytes;
    cache.sort(function (a, b) { return a.at - b.at; });   // oldest first
    i = 0;
    while (i < cache.length
           && (cache.length - i > CACHE_MOST || bytes > CACHE_BYTES_MOST)) {
      if (keep[cache[i].href]) { i += 1; continue; }
      bytes -= cache[i].bytes;
      try { URL.revokeObjectURL(cache[i].href); } catch (err) {}
      cache.splice(i, 1);
    }
  }

  function canHold() {
    return (typeof fetch === 'function' && typeof URL !== 'undefined'
            && !!URL.createObjectURL && !!URL.revokeObjectURL);
  }

  /* Pull the whole clip down. Resolves either way - the value is an
     object URL, or null meaning "play it off the station". */
  function preFetch(clip) {
    var url = srcOf(clip);
    if (!url || !canHold()) return null;
    var got = cacheFind(url);
    if (got) return Promise.resolve(got.href);
    if (fetching[url]) return fetching[url];
    var job = fetch(url, {credentials: 'omit'}).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var len = Number(res.headers.get('content-length'));
      if (isFinite(len) && len > CACHE_FILE_MOST) throw new Error('too big');
      return res.blob();
    }).then(function (blob) {
      if (!blob || !blob.size) throw new Error('empty');
      if (blob.size > CACHE_FILE_MOST) throw new Error('too big');
      var href = URL.createObjectURL(blob);
      cache.push({url: url, href: href, bytes: blob.size, at: now()});
      cacheTrim();
      delete fetching[url];
      return href;
    })['catch'](function () {
      delete fetching[url];
      return null;                      /* the station's URL still works */
    });
    fetching[url] = job;
    return job;
  }

  /* What to point an element at: the bytes we are holding, or the
     station, and never a stale object URL. */
  function heldSrc(clip) {
    var url = srcOf(clip);
    var got = cacheFind(url);
    return (got && got.href) || url;
  }


  /* [#1200] A CLIP DELETED FROM THE LIBRARY leaves every place this set
   * holds it: the queue, the strip, the warm slot - and the tube, if it is
   * the one showing, through the same curtain the sheet's Close pulls. */
  function withdrawClip(id) {
    var key = String(id || '');
    if (!key) return;
    for (var i = queue.length - 1; i >= 0; i -= 1) {
      if (clipId(queue[i]) === key) queue.splice(i, 1);
    }
    comingDrop(key);
    if (warm && warm.clip && clipId(warm.clip) === key) warmDrop();
    if (playing && clipId(playing) === key && curtain) {
      try { curtain(); } catch (err) { /* the set is already going */ }
    }
  }
  /* [#1212] A WARM ELEMENT THAT HAS TO MOVE IS NOT WARM.
   *
   * #1411's warm tube was a detached <video> with preload=auto. It has the
   * bytes; it has no decoder, because Chromium stands one up for an
   * element that is IN a document. Measured: two joins in thirteen sat at
   * 187 and 264 ms with `playing` already fired and currentTime refusing
   * to move. Parking it off screen in the document steadied that (max
   * 132) and cost 40 ms at EVERY join instead, because re-parenting a
   * <video> rebuilds its frame sink.
   *
   * So it is created INSIDE the tube that is on screen, hidden at opacity
   * 0 behind the picture, and on the seam it is promoted where it stands
   * (slotSwap). With no tube yet - the first clip of a set - it falls back
   * to an off-screen holder, which is strictly better than detached and is
   * the only case the operator can see a CRT expand on anyway.
   *
   * `data-pine-warm` marks it so nothing reading ".sfx-tv-tube video"
   * mistakes the hidden one for the picture, and it is NOT inside a
   * separate .sfx-tv, so teardownNow's sweep cannot take it on its own. */
  var warmHost = null;

  function warmHolder() {
    if (warmHost && warmHost.parentNode) return warmHost;
    try {
      warmHost = document.createElement('div');
      warmHost.className = 'sfx-tv-warm';
      warmHost.setAttribute('style', 'position:fixed;left:-9999px;top:0;'
        + 'width:2px;height:2px;overflow:hidden;opacity:0;pointer-events:none');
      document.body.appendChild(warmHost);
    } catch (err) { warmHost = null; }
    return warmHost;
  }

  function warmPark(el) {
    try {
      el.setAttribute('data-pine-warm', '1');
      if (tube) {
        el.setAttribute('style', 'position:absolute;left:0;top:0;width:100%;'
          + 'height:100%;object-fit:contain;opacity:0;pointer-events:none');
        tube.appendChild(el);
        return;
      }
    } catch (err) { /* the holder below */ }
    var box = warmHolder();
    try { if (box && el.parentNode !== box) box.appendChild(el); }
    catch (err) { /* it warms detached, exactly as it did before */ }
  }

  function warmUnpark(el) {
    try { if (el && el.parentNode) el.parentNode.removeChild(el); }
    catch (err) { /* build() is about to move it anyway */ }
  }

  function warmDrop() {
    if (!warm) return;
    var el = warm.el;
    warm = null;
    warmUnpark(el);                                        /* [#1212] */
    try { el.pause(); levelDrop(el); el.removeAttribute('src'); el.load(); }
    catch (err) { /* already gone */ }
  }

  function warmElement(head) {
    if (!mounted || !head || !head.url) return;
    if (warm && warm.clip === head) return;
    warmDrop();
    var el;
    try {
      el = document.createElement('video');
      el.preload = 'auto';
      el.playsInline = true;
      el.controls = false;
      el.crossOrigin = 'anonymous';
      /* [#1216] THE LEVEL BEFORE THE FIRST FRAME. This element becomes the
         picture on the next seam; giving it the level here is what makes
         the clip start at the right loudness instead of being corrected
         once somebody's poll gets round to it. Muted as well, so a
         decoder waking up early can never be heard. */
      el.muted = true;                                     /* [#1212] */
      levelSet(el, level, false);                          /* [#1216] */
      el.src = heldSrc(head);                              /* #1421 */
      el.load();
    } catch (err) { return; }
    warm = {clip: head, el: el};
    warmPark(el);                                          /* [#1212] */
  }

  function warmUp() {
    if (!mounted) return;
    var head = queue[0];
    if (!head || !head.url) return;
    if (warm && warm.clip === head) return;
    /* #1421: THE BYTES FIRST, THEN THE ELEMENT. A warm element pointed
       at the station is still an element that can stall halfway through
       a clip; one pointed at a blob cannot. The element is built when
       the bytes are here - or straight away if we cannot hold them, in
       which case this is exactly the old behaviour. */
    var job = preFetch(head);
    if (job && job.then) {
      job.then(function () {
        if (mounted && queue[0] === head) warmElement(head);
      });
      /* And the one after it, so a seam never waits on a fetch. */
      if (queue[1]) preFetch(queue[1]);
      return;
    }
    warmElement(head);
  }

  /* The warm element for this clip, if it is the one that was warmed
     and it has not already failed - a failed one is thrown away here so
     play() builds a fresh element and hears the error itself. */
  function warmTake(clip) {
    if (!warm || warm.clip !== clip) return null;
    var el = warm.el;
    warm = null;
    /* [#1212] An element already in the tube on screen must NOT be moved -
       that is the whole of the slot. Anything else is unparked so build()
       can put it where it belongs. */
    if (!(tube && el.parentNode === tube)) warmUnpark(el);
    if (el.error) {
      try { el.removeAttribute('src'); el.load(); } catch (err) {}
      return null;
    }
    /* [#1212] it was muted for the warm and nothing else; [#1216] the
       level is the one that is set NOW, not the one that was set when it
       was warmed, and it is written before the element has been heard. */
    try { el.muted = false; levelSet(el, level, false); } catch (err) { /* it plays */ }
    return el;
  }

  /* A warm element for a clip that is no longer the next one - dropped
     as late, or cut past - is let go. */
  function warmSync(clip) {
    if (warm && warm.clip !== clip && queue.indexOf(warm.clip) < 0) warmDrop();
  }

  /* #1173: how far into the clip on the tube the STATION is, in seconds,
   * on this machine's clock. Zero for anything that is not the endless
   * set's - a sting is punctuation for a line that was spoken, and it
   * belongs at its own first frame or nowhere. */
  function airInto(clip) {
    if (!clip || !clip.endless) return 0;
    var at = Number(clip.at);
    if (!isFinite(at) || at <= 0) return 0;
    var into = (now() - at) / 1000;
    return (isFinite(into) && into > 0) ? into : 0;
  }

  /* The same number, but only when it is worth a decode. */
  function airJoin(clip) {
    var into = airInto(clip);
    return into > JOIN_MIN ? into : 0;
  }

  /* #1173: "TOO LATE" IS NOT THE SAME QUESTION FOR THE TWO KINDS OF CLIP.
   *
   * For a sting it is LATE seconds and the comment beside LATE says why: a
   * picture meant to punctuate a line spoken four minutes ago must not
   * fire now. An endless clip punctuates nothing - it is wallpaper on a
   * plan every surface holds - so the only thing that can make it wrong is
   * that its slot has run out, and until then it is JOINED rather than
   * skipped. Skipping was how the two surfaces ended up on different
   * pictures in the first place: the tablet, eight seconds behind, dropped
   * a clip the desk was in the middle of. */
  function missed(clip) {
    if (!clip) return false;
    var late = (now() - Number(clip.at || now())) / 1000;
    if (!clip.endless) return late > LATE;
    var slot = Number(clip.seconds);
    if (!isFinite(slot) || slot <= 0) slot = LATE;
    return late >= slot;
  }

  function next() {
    if (showing || !mounted) return;
    /* #1167: nothing new comes out of the tube while a report is up. The
     * clip stays in the queue; whether it is still worth playing when he
     * is finished is decided by the LATE test two lines down, which is the
     * right answer either way - a sting that was meant to punctuate a line
     * spoken four minutes ago should not fire now.
     *
     * The live read rather than the flag, so this holds even in the case
     * where the watch never attached. */
    /* #1184: ...UNLESS THE SET IS THE SFX TRACK. While endless is on this
     * is station audio, not a pop-up, and the reason above does not
     * apply to it: nothing is popping up, because the picture is already
     * on screen and has been for minutes. Stopping the cycle for the
     * length of a report would leave a hole in the SFX track and then
     * resume it several clips behind the station's own plan. The
     * broadcast is already at 10% through PineDuck while he reads, which
     * is the rule this station actually holds. */
    if ((reportUp || reportNow()) && !endlessOn) return;
    var clip = queue.shift();
    while (clip && missed(clip)) {                         /* #1173 */
      videoReceipt(clip, 'error', null, 'Video missed its playback window');
      clip = queue.shift();
    }
    if (!clip) return;
    warmSync(clip);                                        /* #1411 */
    var wait = Number(clip.at || 0) - now();
    if (wait > 250) {
      /* Early is not late: the station stamps an air moment a lead ahead
       * of delivery, and a picture that jumps the gun lands over the line
       * it was meant to punctuate. */
      queue.unshift(clip);
      warmUp();                                            /* #1411 */
      if (hold) clearTimeout(hold);
      hold = setTimeout(function () { hold = null; next(); }, wait);
      return;
    }
    showing = true;
    try { play(clip); }
    catch (err) { showing = false; }
  }

  /* The one shape of "this clip has been dealt with here". Written in
   * one place because two spellings of it is a picture that plays
   * twice. */
  function markOf(clip) {
    if (!clip || !clip.url) return '';
    var mark = String(clip.ts || '') + '|' + String(clip.url);
    marks[mark] = 1;
    return mark;
  }

  /* #1322: TELL THE OTHER SETS.
   *
   * A clip fired locally - a sampler pad holding an mp4 (#1310) - never
   * touches the station, so the app's set and the tablet's set each
   * only ever show the clips that happen to have been fired on them.
   * "When a video clip is played, show a PiP overlay on the application
   * as well."
   *
   * So a local cut also RINGS the clip: /api/sfx/video/cut puts it in
   * the same ring /api/dj/video serves, with no claim on the air (see
   * page_picture_append). The stamped clip comes back and is marked
   * here, which is what stops this surface playing its own picture a
   * second time when the poll comes round to it.
   *
   * Silent about failure throughout: the picture is already on THIS
   * screen, and a station that refused the ring is not a reason to take
   * it down. */
  function ring(clip) {
    if (!clip || !clip.url) return;
    if (!api() || !api().post) return;
    var body = {
      url: String(clip.url), sting: String(clip.sting || ''),
      id: String(clip.id || ''), seconds: Number(clip.seconds) || 0
    };
    if (Number(clip.from) > 0) body.from = Number(clip.from);
    if (Number(clip.to) > 0) body.to = Number(clip.to);
    try {
      api().post('/api/sfx/video/cut', body).then(function (got) {
        if (got && got.clip) markOf(got.clip);
      }, function () { /* the picture is up here either way */ });
    } catch (err) { /* likewise */ }
  }

  /* [#1212] THE RUNWAY IS SECONDS, NOT ROWS.
   *
   * `if (queue.length > 4)` was written when a clip was a six-second
   * sting. #1422 let the cycle hand out its clips at their own length and
   * the library's shortest are 1.1 s, so four rows became four seconds of
   * runway against a 2.5 s poll - and a seam needs the NEXT clip warmed
   * before this one ends. The station already counts its own ring in
   * seconds (SFX_CYCLE_AHEAD = 28 in app.py); this counts the same way,
   * with a row cap left only so a library of quarter-second clips cannot
   * grow the queue without bound. */
  var QUEUE_AHEAD_S = 30;
  var QUEUE_ROWS_MOST = 24;

  function queueTrim() {
    while (queue.length > QUEUE_ROWS_MOST) queue.shift();
    var held = 0, i;
    for (i = 0; i < queue.length; i += 1) {
      held += Math.max(0.8, Number(queue[i].seconds) || 6);
    }
    /* Dropped from the FRONT, as it always was: the oldest rung clip is
       the one whose moment has most nearly gone. Never below two rows, or
       a seam has nothing to hand over to. */
    while (queue.length > 2 && held > QUEUE_AHEAD_S) {
      held -= Math.max(0.8, Number(queue[0].seconds) || 6);
      queue.shift();
    }
  }

  function offer(clip) {
    if (!clip || !clip.url) return;
    if (marks[String(clip.ts || '') + '|' + String(clip.url)]) return;
    markOf(clip);
    videoReceipt(clip, 'received');
    queue.push(clip);
    queueTrim();                                           /* [#1212] */
    comingKeep(clip);                                       /* #1195 */
    /* #1411b: a clip that arrives while one is on screen is warmed at
       once if the one on screen already has what it needs. */
    if (!showing || (video && (video.readyState >= 4
                               || Number(video.currentTime) > 1.5))) warmUp();
    next();
  }

  /* #1426: ON THIS DEVICE THE PICTURE IS NOT THE PAGE'S.
   *
   * Measured on the tablet, with #1421's pre-fetch already deployed and
   * the bytes arriving 9.5 SECONDS early: the picture still dropped
   * 21-40% of its frames. The delivery was never the fault. This WebView
   * renders at 8-12 fps WHATEVER IS IN IT - with the entire panel hidden,
   * 28 top-level elements gone, every decorative decoder released and one
   * 427x240 video alone on the document, it was still 12 - so no
   * arrangement of HTML gets a smooth picture out of it.
   *
   * PineVideoWall plays the same ring on a SurfaceView that
   * SurfaceFlinger composites directly from its own buffer queue, which
   * the page's compositor cannot slow down. The page's job becomes only
   * to say WHETHER it should be running.
   *
   * The yield is the shape this module already uses for the desktop
   * shell: no bridge, an older build with no wall, or a refusal, and
   * nothing at all changes - the page keeps its tube and behaves exactly
   * as it did. A picture that depends on a new native class existing is
   * a picture that disappears on the first tablet that has not updated. */
  var wallWant = null;               /* what we last asked for; null = never */
  var wallHas = false;               /* what the wall says it is doing */

  function wallState(got) {
    if (!got) return null;
    if (typeof got === 'string') {
      try { return JSON.parse(got); } catch (err) { return null; }
    }
    return got;
  }

  /* #1435: THE ROWS THE RING HAS HANDED US, BY ID.
   *
   * The wall answers with an id and nothing else, and an id is not enough
   * to paint with - the listen backdrop needs the url, and its signature
   * cannot be invented here. The wall may also be showing a clip out of
   * its own larder that has since fallen off the ring, so this remembers
   * rows for longer than the ring holds them. Bounded: an endless set
   * runs for days. */
  var ringSeen = Object.create(null);
  var ringOrder = [];
  var ringAsk = Object.create(null);
  var wallShowing = '';
  var wallFlight = null;
  var wallUiObserver = null;

  function wallSignal(id) {
    /* The native-wall follower runs independently of the station feed. Tell
       Listen as soon as its source row is usable; otherwise `playing` is
       current here while the backdrop waits for its next one-second paint. */
    try {
      if (typeof root.dispatchEvent === 'function'
          && typeof root.CustomEvent === 'function') {
        root.dispatchEvent(new root.CustomEvent('pine-wall-clip',
          {detail: {id: id}}));
      }
    } catch (err) { /* the next ordinary paint sees the same row */ }
  }

  function ringRemember(rows) {
    if (!rows || !rows.length) return;
    for (var i = 0; i < rows.length; i += 1) {
      var row = rows[i];
      var id = row && row.id;
      if (!id || ringSeen[id]) continue;
      ringSeen[id] = row;
      ringOrder.push(id);
    }
    while (ringOrder.length > 400) {
      var gone = ringOrder.shift();
      delete ringSeen[gone];
    }
  }

  /* [#1442] THE PICTURE GOES UNDER ANYTHING THE OPERATOR OPENS.
   *
   * SurfaceFlinger composites the wall's surface ABOVE the WebView, so no
   * z-index in this document can put an element over it - the hold sheet
   * opened UNDERNEATH the picture and half its buttons could not be
   * reached. The only way the page gets above the picture is for the
   * picture to go.
   *
   * It is the OVERLAP that matters, not that something is open. Measured
   * on the device: real pop-ups are body children at or above
   * UI_Z_FLOOR, which is where the view hosts sit, and ordinary content
   * is under 200 - but PERSISTENT chrome is up there too (the
   * orchestrator dot is z 2147483004 and never leaves), so hiding on
   * "anything open" would hide the picture for ever. A sheet across the
   * box takes it away; a dot in the far corner does not.
   *
   * Walks document.body.children only - a handful of nodes - and runs on
   * the poll this module already makes. */
  /* [#1448b] the one line of dress the hand-back needs */
  try {
    if (!document.getElementById('plNativeVeilCss')) {
      var st1 = document.createElement('style');
      st1.id = 'plNativeVeilCss';
      st1.textContent = '.pl-natively-veiled{display:none !important}';
      document.head.appendChild(st1);
    }
  } catch (err) { /* no head yet: the class simply does nothing */ }

  var UI_Z_FLOOR = 2147483000;
  var UI_AREA_MIN = 20000;          /* a panel, not a button */

  function uiOverPicture() {
    var box;
    try { box = readBox(); } catch (err) { return false; }
    if (!box || !(box.width > 0) || !(box.height > 0)) return false;
    var x1 = box.left, y1 = box.top;
    var x2 = box.left + box.width, y2 = box.top + box.height;
    var kids;
    try { kids = document.body.children; } catch (err) { return false; }
    for (var i = 0; i < kids.length; i += 1) {
      var el = kids[i];
      var cs;
      try { cs = getComputedStyle(el); } catch (err) { continue; }
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      if (Number(cs.opacity) === 0) continue;
      var z = parseInt(cs.zIndex, 10);
      var popup = false;
      try {
        popup = !!(el.matches && el.matches(
          '[data-pine-drag], [role="dialog"], [aria-modal="true"], .modal, .dialog, .popover'));
      } catch (err) { popup = false; }
      /* View hosts sit AT the floor. Pop-ups historically did too, so only
         the known full-screen hosts are excluded at that exact layer. */
      if (!popup && (!isFinite(z) || z < UI_Z_FLOOR)) continue;
      if (z === UI_Z_FLOOR && (el.id === 'sampler'
          || /(^|\s)pine-view-host(\s|$)/.test(String(el.className || '')))) continue;
      var r;
      try { r = el.getBoundingClientRect(); } catch (err) { continue; }
      if (r.width * r.height < UI_AREA_MIN) continue;
      /* The wall's own WebView fallback is not a pop-up over the wall.
         During the native hand-off it can survive for one poll with its
         final frame still mounted. Treating that exact host as chrome hides
         the new native picture while its audio continues, which looks like
         the old video froze and the next video's soundtrack started. Real
         SFX dialogs (the editor and inspector) are different nodes and must
         still retire the native surface. */
      if (el === host
          || /sfx-tv-frame|sfx-tv-host/.test(String(el.className || ''))) continue;
      if (r.right > x1 && r.left < x2 && r.bottom > y1 && r.top < y2) return true;
    }
    return false;
  }

  /* One decision about whether the surface is up, and every reason for
     taking it down goes through it.
     [#1442b] IT IS RECONCILED AGAINST THE WALL, not against what we last
     said to it. The first cut cached its own answer and refused to
     repeat itself, so one call from anywhere else - the bridge directly,
     another road, a rebuild - left the page certain of something that
     was no longer true, and it never spoke again. `st` is the wall's own
     state, which wallFollow() already fetches every poll; when it is not
     to hand the change is simply sent. */
  /* [#1445] THE LISTEN VIEW IS THE PICTURE, so there is no window on it.
   *
   * "The popup shouldnt be there since its the bg." On that view the
   * endless clip is the WALLPAPER (#1184 paintEndless, in #plBackVid) and
   * a floating box of the same clip over the top of it is the same
   * picture twice - which is what #1434 set out to stop and only half
   * did, because it depended on listen.js getting round to calling
   * veil(). This asks the view itself, on the same test listen.js uses
   * for the question (`#plNow` connected and laid out), so the answer
   * does not wait on anybody's clock.
   *
   * It is deliberately not "is the endless set on": the view owns the
   * picture whenever it is up - EXCEPT bare, see below. */
  function listenUp() {
    try {
      var view = document.getElementById('listen');
      var face = document.getElementById('plNow');
      /* Injected views remain connected and laid out after their rail tab
         closes. Geometry alone therefore kept the wall veiled on Script.
         The rail and shell already publish the ownership truth as open or
         active; use that same contract as listen.js. */
      var cls = view && view.classList;
      var open = !!(cls && (cls.contains('open') || cls.contains('active')));
      return !!(open && face && face.isConnected && face.clientWidth > 0);
    } catch (err) { return false; }
  }

  /* [#1448] BARE is the listen view's own full-screen wallpaper mode -
     it hides the panel over the picture. With nothing above the video
     there is nothing for the surface to get in the way of, so the
     surface takes the whole view and is as smooth there as anywhere.
     Measured on the page's own backdrop before this: 13.6% of frames
     dropped, 26.3 fps of a 30 fps clip. */
  function listenBare() {
    try {
      var host = document.getElementById('listen');
      return !!(host && /(^|\s)pl-bare(\s|$)/.test(String(host.className || '')));
    } catch (err) { return false; }
  }

  /* The page owns the picture on the listen view only while the panel is
     over it. Bare, the surface owns it. */
  function listenOwnsPicture() { return listenUp() && !listenBare(); }

  var wallWide = null;                 /* [#1448] what shape it was left in */

  /* [#1448b] THE PAGE'S OWN BACKDROP STANDS DOWN UNDER A FULL-BLEED
   * SURFACE, and is handed straight back when it stops.
   *
   * Measured after #1448: #plBackVid was laid out at 0x0 and still
   * `paused:false` - decoding a second copy of the same clip underneath
   * an opaque surface. That decode is the workload that made the page
   * road judder in the first place (13.6% of frames dropped, 26.3 fps of
   * a 30 fps clip), and invisible is the worst way to spend it.
   *
   * HANDED BACK, NOT TAKEN. Only a class and a pause, both undone the
   * moment bare ends, so listen.js's paintEndless (#1184) arms it again
   * on its next slot exactly as before. And it cannot fire off the
   * tablet: `on` is false unless there is a bridge with a wall behind
   * it, so the listen page in a plain browser is untouched. */
  var backdropDown = null;

  function pageBackdrop(on) {
    on = !!on;
    /* [#1448c] THE HOLD IS RE-ASSERTED, NOT REMEMBERED. listen.js's
       paintEndless (#1184) arms this element on its own poll and knows
       nothing about the surface, so an edge-triggered pause is undone
       within the second - measured, `handedBack:true` with
       `paused:false`. Remembering a state owned by another module is the
       fault #1442b and #1434b both removed; so while the surface has the
       screen the requirement is simply stated again every pass. One
       `.paused` read, and a pause() only when listen.js has restarted it. */
    if (!on) {
      var live;
      try { live = document.getElementById('plBackVid'); } catch (err) { return; }
      if (!live) return;
      try {
        if (!live.classList.contains('pl-natively-veiled')) {
          live.classList.add('pl-natively-veiled');
        }
        if (!live.paused) live.pause();
      } catch (err) { /* the next poll says it again */ }
      backdropDown = true;
      return;
    }
    if (!backdropDown) return;             /* never taken: nothing to give back */
    var el;
    try { el = document.getElementById('plBackVid'); } catch (err) { return; }
    if (!el) return;
    backdropDown = false;
    try {
      el.classList.remove('pl-natively-veiled');
      if (el.paused && el.getAttribute('src')) {
        var q = el.play();
        if (q && q['catch']) q['catch'](function () {});
      }
    } catch (err) { backdropDown = null; }   /* ask again next poll */
  }

  function wallReconcile(st) {
    var bridge = api();
    if (!bridge || typeof bridge.videoWall !== 'function') return;
    var want, wide, panelOwns;
    try {
      panelOwns = listenOwnsPicture();
      /* [#1448] full-bleed while the listen view is bare - there is no
         panel over the picture there, so the surface may have all of it.
         An ordinary Listen view is the opposite: its HTML backdrop owns
         the picture even when the floating set remembered fullscreen.
         Letting that unrelated preference win hid both renderers. */
      wide = !panelOwns && (fullWanted() || (listenUp() && listenBare()));
      /* [#1448b] AND BARE OUTRANKS THE VEIL. listen.js veils this module
         so the endless clip is not on screen twice (#1184/#1434), which
         is right while the PAGE draws the wallpaper. Bare, the page is
         not meant to draw it at all, so the veil is answering a question
         nobody is asking - measured, the surface stayed
         `{"on":true,"veiled":true}` on a bare view. The "twice" it guards
         against is honoured by pageBackdrop(false) below instead. */
      want = (!!veiled && !wide) || panelOwns || uiOverPicture();
    } catch (err) { return; }
    pageBackdrop(!wide);
    var shapeChanged = (wallWide !== wide);
    if (!shapeChanged && st && typeof st.veiled === 'boolean'
        && !!st.veiled === want) return;
    wallWide = wide;
    /* Full-bleed is {w:0,h:0}, NOT null. Checked in the two places that
       decide it rather than assumed: the bridge only forwards a box that
       `has("w")||has("h")`, so a null box leaves the old one standing,
       and setBox reads width<=0 as MATCH_PARENT. The bridge reads the box
       out of argument two whatever the verb, so this rides the same call. */
    bridge.videoWall(want ? 'hide' : 'show',
                     wide ? {x: 0, y: 0, w: 0, h: 0} : nativeWallRect())['catch'](function () {
      wallWide = null;                 /* ask again next poll */
    });
  }

  function wallVisibility() { wallReconcile(null); }

  function wireWallUi() {
    if (wallUiObserver || !root.MutationObserver || !document.body) return;
    wallUiObserver = new root.MutationObserver(function (changes) {
      for (var i = 0; i < changes.length; i += 1) {
        var change = changes[i];
        var candidates = [];
        if (change.target) candidates.push(change.target);
        if (change.addedNodes) candidates = candidates.concat(Array.prototype.slice.call(change.addedNodes));
        if (change.removedNodes) candidates = candidates.concat(Array.prototype.slice.call(change.removedNodes));
        for (var j = 0; j < candidates.length; j += 1) {
          var node = candidates[j];
          try {
            if (node && node.matches && node.matches(
              '[data-pine-drag], [role="dialog"], [aria-modal="true"], .modal, .dialog, .popover')) {
              wallFollow();
              return;
            }
          } catch (err) { /* the fallback poll owns it */ }
        }
      }
    });
    wallUiObserver.observe(document.body,
      {childList: true, attributes: true, attributeFilter: ['hidden', 'class', 'style']});
  }

  function leaveListen() {
    /* Listen fullscreen is view-scoped. Closing the view always returns the
       endless set to its movable window, even if an older fullscreen choice
       was still persisted from the floating controller. */
    veiled = false;
    try { if (host) host.style.visibility = ''; } catch (err) { /* no set up */ }
    try { setFull(false); } catch (err) { full = false; }
    wallWide = null;
    try { pageBackdrop(true); } catch (err) { /* the view is already closing */ }
    try { wallVisibility(); return true; }
    catch (err) { return false; }
  }

  /* #1435: what the WALL says is on screen, as a clip this page can use.
     Silent when the wall is not running, so a browser with no bridge -
     a Tailscale viewer on the listen page - is untouched. */
  function wallFollow() {
    var bridge = api();
    if (!wallHas || !bridge || typeof bridge.videoWall !== 'function') return;
    if (wallFlight) return wallFlight;
    var flight = bridge.videoWall('state').then(function (got) {
      var st = wallState(got);
      var id = st && st.playing;
      /* [#1442b] BEFORE the veiled early-return below: a wall that is
         hidden must still be told when it may come back. */
      wallReconcile(st);
      /* [#1446] VEILED IS NOT STOPPED, and this line used to treat it as
         though it were. A veiled wall is still playing - that is the
         whole meaning of veil (#1434) - and the LISTEN view is precisely
         the place that needs to know what it is playing, because the
         clip is that view's WALLPAPER and the wall is veiled there by
         definition (#1445). Returning here froze `playing`, so
         paintEndless kept re-arming on a clip that had long finished and
         the backdrop sat on one frame: measured, the element was armed
         for ...ece41c45f7 while the wall was on 1cd53fb0. Only a wall
         with nothing to say is skipped now. */
      if (!id) return;
      wallClip(id);
    })['catch'](function () { /* the wall will be asked again shortly */ });
    wallFlight = flight;
    flight.then(function () {
      if (wallFlight === flight) wallFlight = null;
    }, function () {
      if (wallFlight === flight) wallFlight = null;
    });
    return flight;
  }

  /* A native transition is pushed here immediately. The state follower also
     calls this, so losing either callback or one bridge request cannot strand
     Listen on the previous picture. URL resolution is deliberately outside
     `wallFlight`: a slow server lookup must not block local state checks. */
  function wallClip(id) {
    id = String(id || '');
    if (!id) return Promise.resolve(null);
    wallShowing = id;
    var row = ringSeen[id];
    if (row) {
      if (!playing || playing.id !== id) {
        playing = row;
        wallSignal(id);
      }
      return Promise.resolve(row);
    }
    var bridge = api();
    var asked = Number(ringAsk[id]) || 0;
    if (!bridge || typeof bridge.get !== 'function' || now() - asked < 30000) {
      return Promise.resolve(null);
    }
    ringAsk[id] = now();
    return bridge.get('/api/sfx/url?id=' + encodeURIComponent(id)).then(function (info) {
      if (!info || !info.url) return null;
      info.id = info.id || id;
      info.video = true;
      ringRemember([info]);
      if (wallShowing === id) {
        playing = info;
        wallSignal(id);
      }
      return info;
    })['catch'](function () { return null; });
  }

  /* The endless clips the page has queued are the wall's now - playing
     them here as well is the same picture twice, out of step with itself. */
  function wallTakesOver() {
    for (var i = queue.length - 1; i >= 0; i -= 1) {
      if (queue[i].endless) queue.splice(i, 1);
    }
    coming.length = 0;
    if (warm && warm.clip && warm.clip.endless) warmDrop();
    /* The native wall owns picture AND sound once it has answered `on`.
       Clearing only the runway left a clip that was already in the WebView
       mounted until its delayed `ended` teardown happened. If that timer was
       throttled, the browser held its last frame indefinitely while the
       native playlist continued audibly underneath it. Retire the fallback
       immediately. An open inspector/editor keeps its deliberate hold and
       closes through sheetClose/editorClose instead. */
    if (host && video && !sheetHeld() && !editorBox) teardown(video);
  }

  /* #1426b: WHERE the picture goes. The geometry the operator dragged the
     set to, which readBox() knows whether or not a tube is built right
     now, converted to DEVICE pixels because a native view has never heard
     of a CSS pixel (devicePixelRatio is 1.25 on this tablet).

     NOT called wallBox(): that name is taken, by the listen wall's
     hit-test rectangle a few hundred lines below, and a second one would
     simply have won. */
  function nativeWallRect() {
    try {
      var b = readBox();
      var d = Number(root.devicePixelRatio) || 1;
      if (!b || !(b.width > 0) || !(b.height > 0)) return null;
      return {x: Math.round(b.left * d), y: Math.round(b.top * d),
              w: Math.round(b.width * d), h: Math.round(b.height * d)};
    } catch (err) { return null; }   /* full screen beats no picture */
  }

  function nativeWall(want) {
    var bridge = api();
    if (!bridge || typeof bridge.videoWall !== 'function') return false;
    want = !!want;
    if (wallWant === want) return wallHas;
    wallWant = want;
    bridge.videoWall(want ? 'on' : 'off', nativeWallRect()).then(function (got) {
      var state = wallState(got);
      wallHas = !!(state && state.on);
      if (wallHas) wallTakesOver();
    })['catch'](function () {
      /* The bridge refused or the method is not on this build. Forget the
         ask so a later poll tries again, and keep the page's own tube. */
      wallWant = null;
      wallHas = false;
    });
    return wallHas;
  }

  function wallRunning() { return wallHas; }

  async function poll() {
    wireDuck();                                            /* #1167 */
    wireWall();                                            /* #1184 */
    if (busy || !api() || !api().get) return;
    busy = true;
    try {
      var got = await api().get('/api/dj/video?since=' + seen);
      var serverMs = Number((got && got.server_ms) || now());
      var updates = (got && got.reservation_updates) || {};
      queue.forEach(function (clip) {
        if (updates[clip.delivery_id]) {
          clip.broadcast_ms = updates[clip.delivery_id];
          clip.at = now() + Number(clip.broadcast_ms) - serverMs;
        }
      });
      if (hold) { clearTimeout(hold); hold = null; }
      next();
      /* #1184: the hand-over style, on the poll this set already makes -
       * no second request, and both surfaces read the one answer so the
       * desk and the tablet cannot disagree about it. A station that has
       * not been patched yet simply never sends the key, `seamOn` stays
       * false, and every changeover is the CRT collapse it is today. */
      if (got && typeof got.seamless === 'boolean') seamOn = !!got.seamless;
      /* [#1212] THE SWITCH FOLLOWS THE STATION, NOT THE OTHER WAY ROUND.
       * `seamless` and `endless` have just been read off the answer this
       * set already asks for; an open sheet is repainted from them, and
       * the mode LINE is refreshed from /api/sfx/video/mode - only while
       * the sheet is open, so a closed sheet costs no traffic at all.
       * The screenshot behind this request shows the set ON and the
       * switch reading SEAMLESS off: it had been painted once, when the
       * sheet was built, and never again. */
      if (sheetPaint) {
        sheetPaint(null);
        if (now() - sheetAsk > 2000) {
          sheetAsk = now();
          api().get('/api/sfx/video/mode').then(function (st) {
            if (sheetPaint) sheetPaint(st);
          }, function () { /* the switch still says what the ring said */ });
        }
      }
      if (got && typeof got.endless === 'boolean') {
        endlessPaint(got.endless);
        /* #1426: hand the set to the native surface where there is one. */
        if (nativeWall(got.endless) && got.endless) wallTakesOver();
        /* #1435: and follow what it is showing, so the listen backdrop and
           everything else downstream reads the picture that is on screen
           rather than the last one this page played itself. */
        ringRemember(got.clips);
        wallFollow();
        if (!got.endless) {
          /* 2026-09-14: off means off - the rung-ahead copies go */
          for (var qi = queue.length - 1; qi >= 0; qi -= 1) { if (queue[qi].endless) queue.splice(qi, 1); }
          coming.length = 0;                                 /* #1195 */
          if (warm && warm.clip && warm.clip.endless) warmDrop();
        }
      }
      /* [#1200] deleted from the library: gone from here as well */
      ((got && got.withdrawn) || []).forEach(withdrawClip);
      ((got && got.clips) || []).forEach(function (clip) {
        seen = Math.max(seen, Number(clip.ts || 0));
        /* The station's clock, carried onto this one - the box and this
         * machine have no reason to agree. */
        clip.at = now() + Number(clip.broadcast_ms || clip.ts) - serverMs;
        offer(clip);
      });
    } catch (err) { /* the show goes on */
    } finally { busy = false; }
  }

  /* 2026-09-14: "whenever I turn off endless video mode ... it turns
   * off." The station withdraws what it rang ahead; this drops the copies
   * this set already holds (queue and warm), and the clip on the tube
   * simply finishes. And the switch is SHOWN: a line in the desk's
   * sidebar and an ENDLESS tab on the tablet's rail, each a toggle. */
  var endlessOn = null;
  var veiled = false;
  /* #1167 - "Don't have the audio playing and don't have videos popping up
   * during the process of filing tickets. Resume everything after the
   * ticket following screen has been closed or sent."
   *
   * THIS SET IS THE ONE THAT MAKES THE NOISE. The LISTEN view's backdrop
   * is muted wallpaper; the sound of a sting is this window's <video>.
   * And this is also the thing that literally pops up: the set opens
   * itself whenever the station rings one through, which during a report
   * is a picture and a noise arriving in the middle of a sentence.
   *
   * IT IS ALREADY COVERED, AND THAT IS NOT ENOUGH. The report pad is at
   * z-index 2147483040 and this set at 2147483020, so the pad is over it
   * and nothing here needs to move a layer. A covered set is still an
   * audible set, still runs its cycle, still tears down and starts the
   * next one. So its visibility is deliberately left alone - the pad
   * already handles that - and what changes is that it goes silent, stops,
   * and takes nothing new out of the queue until he is done.
   *
   * THE MUTE IS RECORDED, NOT ASSUMED. `level()` will clear muted on its
   * own when the master volume is up, so this element's mute is somebody
   * else's state as often as it is nobody's; what was found is what goes
   * back. Keyed to the ELEMENT, because a set that tore down and built
   * another while a report was up must not have the old one's mute
   * written onto the new one. */
  var reportUp = false;
  var reportWas = null;
  var unduck = null;

  function reportNow() {
    var d = root.PineDuck;
    return !!(d && typeof d.reporting === 'function' && d.reporting());
  }

  /* #1184: WHO MAKES THE SOUND ONCE THE ENDLESS SET IS THE SFX TRACK.
   *
   * "when the endless video is enabled, have that take over for the SFX
   *  guy using SFX effects. Have the video be the singular SFX track when
   *  enabled."
   *
   * WHICH ELEMENT SOUNDS - and the answer is the one that already does.
   * On the LISTEN tab there are two copies of the same clip: this set's
   * <video>, veiled but audible, and listen.js's wallpaper (#plBackVid),
   * visible but muted. It reads backwards - he is watching a silent
   * picture while a hidden one makes the noise - and it is nonetheless
   * correct, for three measured reasons.
   *
   *   1. THE WALLPAPER EXISTS ON ONE TAB. This set is a sibling of
   *      <main> and survives every tab change; #plBackVid is inside the
   *      LISTEN view and is torn down with it. Move the sound there and
   *      the station's SFX track goes silent the moment he opens the
   *      Script tab, which is not a track.
   *   2. EVERY VOLUME ROAD ALREADY REACHES THIS ONE. It carries
   *      data-pine-live="voice" (#789/#981), so the shell's master
   *      volume and the booth monitor switch find it, and PineDuck ducks
   *      it by the plain `audio, video` sweep its own header describes.
   *      The wallpaper is deliberately outside all of that.
   *   3. THEY ARE NOT FRAME-LOCKED AND MUST NOT BOTH SOUND. #1173's
   *      anchor holds the two within SLIP_MAX, 0.75 s, of each other -
   *      close enough for two pictures, and a doubled sting three
   *      quarters of a second apart is worse than either alone. So
   *      exactly one is audible, and it stays this one.
   *
   * WHAT DOES CHANGE IS WHAT A REPORT DOES TO IT. #1167's rule above was
   * written when this tube was punctuation: a sting popping up mid-ticket
   * is an interruption, so the set went silent, stopped, and took nothing
   * new. Once the endless set IS the SFX track that rule mutes a channel
   * of the broadcast and stalls the cycle for the length of a report -
   * and a hole in the air is the one thing this station treats as a
   * fault. Station audio does not stop for a diagnostic; it DUCKS with
   * the broadcast, and PineDuck is already holding this element at 10%
   * through that same report without being asked.
   *
   * So the hard stop is now conditional, and only in the state the
   * operator switched on himself. With endless OFF, every line below
   * behaves exactly as it did yesterday - that is the safe state and it
   * is untouched. The recording stays keyed to the ELEMENT for the same
   * reason it always was: a set that tore down and built another while a
   * report was up must not have the old one's mute written onto the new
   * one. */
  function reportSettle() {
    reportQuiet(reportUp && !endlessOn);
  }

  function reportQuiet(on) {
    if (on) {
      if (!reportWas && video) {
        reportWas = {el: video, muted: !!video.muted, playing: !video.paused};
      }
      if (video) {
        try { video.muted = true; } catch (err) { /* gone */ }
        try { video.pause(); } catch (err) { /* already still */ }
      }
      return;
    }
    var was = reportWas;
    reportWas = null;
    if (video && was && was.el === video) {
      try { if (video.muted !== was.muted) video.muted = was.muted; }
      catch (err) { /* gone */ }
      /* Only resume what was actually running. A clip that was already
       * paused - on its last frame under a hold sheet, say - stays where
       * the operator left it. */
      if (was.playing) {
        try { video.play().catch(function () { /* the frame is a picture */ }); }
        catch (err) { /* gone */ }
      }
    }
    /* And the queue starts moving again. */
    next();
  }

  /* Wired lazily and idempotently: pine-duck.js is loaded before this file
   * on the desk, but the kiosk injects these in its own order and a set
   * that silently never subscribed would be a set that talks over every
   * report. poll() calls this again every 2.5s until it takes. */
  function wireDuck() {
    if (unduck) return;
    var d = root.PineDuck;
    if (!d || typeof d.watch !== 'function') return;
    unduck = d.watch(function (on) {
      var was = reportUp;
      reportUp = !!on;
      if (was === reportUp) return;
      reportSettle();                                      /* #1184 */
    });
  }

  /* #1184: THE GESTURE ON THE LISTEN WALL.
   *
   * "i need to be able to bring it up in fullscreen on right click for
   *  the listen tab in endless / seamless video mode so i can manage the
   *  video played and delete it if necessary or inspect it."
   *
   * Taken at DOCUMENT level, because neither of the two elements
   * involved can hear it: the wallpaper carries pointer-events:none and
   * this set is visibility:hidden on that tab (the long note beside
   * `sheetOnWall` at the top of this file has the whole measurement).
   *
   * And answered GEOMETRICALLY rather than by walking the DOM. "Is the
   * press inside the rectangle the wallpaper occupies" is true in every
   * state the LISTEN view has - windowed with the panel over it, bare
   * and full-bleed, and during the second or so per clip where the
   * wallpaper is hidden behind the plexus while the next file arrives -
   * and it needs to know nothing about that view's markup, which is in
   * another file and changes on its own schedule. */
  function wallNode() {
    var vid = null;
    try { vid = document.getElementById('plBackVid'); }
    catch (err) { return null; }
    if (!vid) return null;
    var slot = '';
    /* listen.js stamps this while the endless clip owns the wall and
       deletes it when it hands the wall back to the gallery. It is the
       view's own answer to "am I showing the set", so it is the one
       asked rather than a second guess at the same question. */
    try { slot = String((vid.dataset && vid.dataset.endless) || ''); }
    catch (err) { slot = ''; }
    return slot ? vid : null;
  }

  /* The rectangle the wall occupies. While the clip is arriving the
     element is hidden and measures zero, so the box it sits in answers
     instead - the picture is still what he is pressing on, it is just
     the plexus standing in for the frame. */
  function wallBox() {
    var vid = wallNode();
    if (!vid) return null;
    var box = null;
    try { box = vid.getBoundingClientRect(); } catch (err) { return null; }
    if (box && box.width > 8 && box.height > 8) return box;
    try { box = vid.parentNode && vid.parentNode.getBoundingClientRect(); }
    catch (err) { return null; }
    return (box && box.width > 8 && box.height > 8) ? box : null;
  }

  /* Is this press one the menu should answer? Not on a control, and
     inside the picture. */
  function onWallAt(ev) {
    if (!playing || !ev) return false;
    var box = wallBox();
    if (!box) return false;
    var x = Number(ev.clientX), y = Number(ev.clientY);
    if (!isFinite(x) || !isFinite(y)) return false;
    if (x < box.left || x > box.right || y < box.top || y > box.bottom) {
      return false;
    }
    return !overControl(ev.target);
  }

  /* #1166's answer to "whose press is this", borrowed rather than
     rewritten. hot-corners.js exports _overControl for exactly this -
     its own note says it is exported "so the rail exemption can be
     checked against the real page rather than argued about" - and it
     already honours buttons, links, inputs, ARIA roles, contenteditable
     and the surfaces that own their own gestures. A second opinion on
     that question is how two surfaces end up disagreeing about which
     presses belong to them. The short walk below is only for a surface
     where hot-corners.js was never loaded. */
  function overControl(node) {
    var hc = root.PineHotCorners;
    if (hc && typeof hc._overControl === 'function') {
      try { return !!hc._overControl(node); }
      catch (err) { /* ours, below */ }
    }
    var el = node, hops = 0, tag;
    while (el && el.nodeType === 1 && hops < 40) {
      tag = String(el.tagName || '').toLowerCase();
      if (tag === 'button' || tag === 'a' || tag === 'input'
          || tag === 'select' || tag === 'textarea' || tag === 'label') {
        return true;
      }
      el = el.parentNode;
      hops += 1;
    }
    return false;
  }

  /* #1184: and the menu does not open where the hot corners are armed.
   *
   * Only the HOLD needs this. hot-corners.js takes its gestures at
   * pointerdown with a mouse button test of 0, so a right-click is
   * already invisible to it; and a press held past its TAP_MS (500 ms)
   * is dropped by that file anyway. What this prevents is the other
   * collision - the operator beginning a corner SWIPE inside the
   * picture and this set opening a menu under his finger on the way
   * out. CORNER_PX is exported by that file for precisely this, so the
   * square is read from it rather than written down twice. */
  function inCorner(x, y) {
    var hc = root.PineHotCorners;
    if (!hc || typeof hc._cornerAt !== 'function'
        || typeof hc.config !== 'function') {
      return false;
    }
    var where = '', cfg = null;
    try {
      where = String(hc._cornerAt(x, y, root.innerWidth || 0,
                                 root.innerHeight || 0) || '');
      cfg = hc.config() || {};
    } catch (err) { return false; }
    if (!where) return false;
    return cfg.enabled !== false && String(cfg[where] || 'off') !== 'off';
  }

  function wallForget() {
    if (wallTimer) { clearTimeout(wallTimer); wallTimer = 0; }
    wallPress = null;
  }

  /* Wired lazily and idempotently, the way wireDuck() is and for the
     same reason: the kiosk injects these files in an order of its own
     and a set that silently never subscribed is a feature that silently
     does nothing. poll() calls this again every 2.5 s until it takes. */
  function wireWall() {
    if (wallWired) return;
    if (!document || !document.addEventListener) return;
    wallWired = true;

    /* THE RIGHT-CLICK. The primary road, and the one he asked for by
       name. The browser's own menu is suppressed so his is the only
       thing that appears. */
    document.addEventListener('contextmenu', function (ev) {
      /* Listen owns its background. It has one gesture there - double tap
         to enter or leave its screen-only mode - and never exposes clip
         deletion or management controls on that display surface. */
      if (listenUp()) { ev.preventDefault(); return; }
      /* Over the open sheet: swallow the browser menu and leave the
         sheet alone. Checked first, because _overControl will call the
         sheet a control (it carries the sfx-tv token by design) and we
         would otherwise fall through to no handling at all. */
      if (sheetOnWall && sheetWrap && sheetWrap.contains
          && sheetWrap.contains(ev.target)) {
        ev.preventDefault();
        return;
      }
      if (!onWallAt(ev)) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (sheetHeld()) { sheetClose(); return; }
      sheet(playing, {x: ev.clientX, y: ev.clientY});
    });

    /* THE HOLD, WHICH IS THE TABLET'S RIGHT BUTTON. A touch surface has
       no second button, so the same menu is owed to a press held on the
       picture.
     *
     * IT DOES NOT TOUCH #1121. That hold - the "put this clip on a
     * sampler pad?" question - lives on this set's own host and fires
     * only for a press that lands on .sfx-tv-screen. On the LISTEN tab
     * the host is veiled and receives no pointer events at all, so
     * #1121's hold is not reachable there and nothing here takes it
     * away from it: on every other tab, where the set is visible, a hold
     * still asks about the sampler exactly as it does today.
     *
     * A mouse is excluded deliberately. It has a right button, that is
     * the gesture he asked for, and a mouse resting on the picture while
     * he thinks should not open a menu at him. */
    document.addEventListener('pointerdown', function (ev) {
      wallForget();
      if (ev.button !== undefined && ev.button !== 0) return;
      if (String(ev.pointerType || '') === 'mouse') return;
      if (!onWallAt(ev)) return;
      if (inCorner(ev.clientX, ev.clientY)) return;
      wallPress = {x: Number(ev.clientX) || 0, y: Number(ev.clientY) || 0};
      wallTimer = setTimeout(function () {
        wallTimer = 0;
        var was = wallPress;
        wallPress = null;
        if (!was || !playing) return;
        if (radialWrap) { radialClose(true); return; }
        if (sheetHeld()) { sheetClose(); return; }
        radialOpen(playing, was);
      }, WALL_HOLD_MS);
    });
    document.addEventListener('pointermove', function (ev) {
      if (!wallPress) return;
      if (Math.abs((Number(ev.clientX) || 0) - wallPress.x) > SLOP_PX
          || Math.abs((Number(ev.clientY) || 0) - wallPress.y) > SLOP_PX) {
        wallForget();                 /* a drag, or the start of a swipe */
      }
    });
    document.addEventListener('pointerup', wallForget);
    document.addEventListener('pointercancel', wallForget);
  }

  function endlessPaint(on) {
    on = !!on;
    if (on === endlessOn) return;
    endlessOn = on;
    /* #1184: the switch can be flipped while a report is open, and which
       rule this set is under depends on it - so the report rule is
       decided again here rather than only when the report itself
       changes. Without this, a set switched to endless mid-report would
       stay muted and stopped until the report closed. */
    if (reportUp) reportSettle();
    var line = document.getElementById('endlessLine');
    if (line) {
      line.hidden = false;
      line.textContent = on ? 'endless video: on - click for the dials'
                            : 'endless video: off - click for the dials';
      line.classList.toggle('on', on);
      if (!line.__wired) {
        line.__wired = true;
        line.addEventListener('click', function (ev) { ev.stopPropagation(); endlessSheet(); });
      }
    }
    var rail = document.getElementById('pineViewRail');
    if (rail) {
      var tab = document.getElementById('pineViewTab-endless');
      if (!tab) {
        tab = document.createElement('button');
        tab.id = 'pineViewTab-endless';
        tab.type = 'button';
        tab.className = 'pine-view-tab pine-view-tab-endless';
        tab.textContent = 'ENDLESS';
        tab.title = 'Endless video - the clips one after another. Tap to switch it on or off.';
        tab.addEventListener('click', function (ev) { ev.stopPropagation(); endlessSheet(); });
        rail.appendChild(tab);
      }
      tab.classList.toggle('on', on);
      tab.style.color = on ? '#54d18b' : '';
    }
  }

  /* 2026-09-14: "tap it and have parameters for adjusting the frequency
   * in which MP4 videos are played on general broadcast compared to MP3s.
   * And also the average length of video that is grabbed when using
   * endless video." The indicator opens this sheet: the switch, the
   * picture share (#1366's dial - what share of the SFX guy's clips carry
   * a picture) and the clip length the book aims for (0 = any). Every
   * change posts to /api/sfx/video/mode, which is the station's held
   * setting, so it survives restarts and reaches every surface. */
  var sheetEl = null;
  /* [#1212] set while the sheet is open; poll() calls it with the station's
     own mode answer so the two switches and the line under them stay live. */
  var sheetPaint = null;
  var sheetAsk = 0;
  var matchState = null;                              /* [#1251] */
  function endlessSheet() {
    if (sheetEl && sheetEl.parentNode) {
      sheetEl.parentNode.removeChild(sheetEl); sheetEl = null;
      sheetPaint = null;                                   /* [#1212] */
      return;
    }
    if (!api() || !api().get) return;
    var box = document.createElement('div');
    box.id = 'sfxEndlessSheet';
    box.setAttribute('style', 'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);'
      + 'width:min(92vw,420px);padding:14px 16px;border:1px solid #2a3a44;border-radius:12px;'
      + 'background:#0b1116;color:#dfe7ee;font:14px/1.4 system-ui,sans-serif;z-index:2147483040;'
      + 'box-shadow:0 18px 60px rgba(0,0,0,.6);display:flex;flex-direction:column;gap:10px');
    box.setAttribute('data-pine-drag', '1');
    var head = document.createElement('b');
    head.textContent = 'Endless video';
    head.setAttribute('data-pine-drag-handle', '1');
    head.style.cursor = 'move';
    var note = document.createElement('div');
    note.setAttribute('style', 'color:#9fb3c0;font-size:12px;min-height:16px');
    function row(label, min, max, step, val, fmt, key) {
      var wrap = document.createElement('label');
      wrap.setAttribute('style', 'display:flex;flex-direction:column;gap:4px;font-size:12px;color:#9fb3c0');
      var top = document.createElement('span');
      var out = document.createElement('b');
      out.style.color = '#dfe7ee';
      top.textContent = label + ': ';
      top.appendChild(out);
      var r = document.createElement('input');
      r.type = 'range'; r.min = String(min); r.max = String(max); r.step = String(step); r.value = String(val);
      r.style.width = '100%';
      var paint = function () { out.textContent = fmt(Number(r.value)); };
      paint();
      r.addEventListener('input', paint);
      r.addEventListener('change', function () {
        var body = {}; body[key] = Number(r.value);
        note.textContent = 'saving...';
        api().post('/api/sfx/video/mode', body).then(function (got) {
          note.textContent = String((got && got.say) || 'saved');
        }, function (err) { note.textContent = String((err && err.message) || err).slice(0, 80); });
      });
      wrap.appendChild(top); wrap.appendChild(r);
      return wrap;
    }
    /* #1184: TWO SWITCHES SIDE BY SIDE, in the gap he drew a box around.
     *
     * "Offer an option to enable seamless video as well." He has twice
     * called the thing he is in "endless / seamless video mode", so
     * seamless rides ALONGSIDE endless rather than being a second state
     * of the same button - which is why it is its own control with its
     * own label and its own colour, and not a third caption on the one
     * above. The row is the space to the right of the ON button in his
     * screenshot.
     *
     * IT PERSISTS THE WAY THE SLIDERS DO. Not localStorage: the picture
     * share and the clip length are held settings on the station, posted
     * to /api/sfx/video/mode, and this goes to the same door on the same
     * road so it survives a restart and the desk and the tablet cannot
     * disagree about it.
     *
     * AND IT IS HONEST WHEN ENDLESS IS OFF. The seam it removes is the
     * one between clips of the endless cycle, so with the set off there
     * is nothing for it to do - and rather than sit there looking live,
     * it says "armed" and the status line under the sliders says it will
     * take effect when the set is on. */
    var swRow = document.createElement('div');
    swRow.setAttribute('style', 'display:flex;gap:8px;align-items:stretch');
    var sw = document.createElement('button');
    sw.type = 'button';
    sw.setAttribute('style', 'flex:1 1 58%;min-width:0;min-height:40px;border-radius:8px;border:1px solid #2c7a8c;background:#1d4d5a;color:#dfe7ee;font-size:14px;cursor:pointer');
    var paintSw = function (on) { sw.textContent = on ? 'ON - tap to stop the set' : 'OFF - tap to start the set'; sw.style.background = on ? '#1d5a3a' : '#1d4d5a'; };
    sw.addEventListener('click', function (ev) { ev.stopPropagation(); endlessFlip(); setTimeout(function () { paintSw(!!endlessOn); }, 800); });
    var seam = document.createElement('button');
    seam.type = 'button';
    seam.setAttribute('style', 'flex:1 1 42%;min-width:0;min-height:40px;border-radius:8px;border:1px solid #2c7a8c;background:#1d4d5a;color:#dfe7ee;font-size:12px;line-height:1.25;cursor:pointer');
    seam.title = 'Seamless: the next clip goes in on the frame this one '
      + 'ends, with no collapse and no gap. It needs the next clip to have '
      + 'finished arriving, so a very short clip still collapses.';
    /* [#1212] "When seamless video is on, make the button say that seamless
     * video is on. In fact, change the color to make it go from blue to
     * green, indicating that seamless video is on."
     *
     * In those words, and in that colour, and painted from the STATION's
     * answer rather than this browser's guess - poll() drives sheetPaint
     * below every 2.5 s while the sheet is open. */
    var paintSeam = function (on) {
      var word = on ? 'SEAMLESS VIDEO IS ON' : 'SEAMLESS VIDEO IS OFF';
      seam.innerHTML = ((typeof root.pineIcon === 'function'
        ? root.pineIcon('c:repeat', 'Seamless') : '') || '') + ' ' + word;
      seam.style.background = on ? '#1d5a3a' : '#1d4d5a';
      seam.style.borderColor = on ? '#3fae6a' : '#2c7a8c';
      seam.style.color = on ? '#dff3e6' : '#dfe7ee';
      /* On with the set off is still ON, because the station says on; the
         mode line under the sliders is where "it takes effect when the
         set is on" belongs, and it says exactly that. */
      seam.style.opacity = (on && !endlessOn) ? '.82' : '1';
    };
    seam.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var want = !seamOn;
      note.textContent = 'saving...';
      api().post('/api/sfx/video/mode', {seamless: want}).then(
        function (got) {
          seamOn = !!(got && typeof got.seamless === 'boolean'
            ? got.seamless : want);
          paintSeam(seamOn);
          note.textContent = String((got && got.say) || 'saved');
        },
        function (err) {
          /* The station is the one that holds this, so a refusal means
             it did NOT change - say so rather than paint a switch that
             only this browser believes in. */
          note.textContent = 'the station would not take it: '
            + String((err && err.message) || err).slice(0, 60);
        });
    });
    /* Painted from what the poll already knows, before the station is
       asked - so a sheet opened while the station is slow shows a real
       switch rather than an empty button, and a station that never
       answers leaves a readable one behind. */
    paintSeam(seamOn);
    /* [#1212] and from here on the STATION paints it. */
    sheetPaint = function (st) {
      try {
        paintSw(!!endlessOn);
        paintSeam(!!seamOn);
        if (st && st.say) note.textContent = String(st.say);
      } catch (err) { /* the sheet went */ }
    };
    swRow.appendChild(sw);
    swRow.appendChild(seam);
    /* [#1251] THE THIRD ROW: MATCH THE SET TO THE DIALOGUE.
     *
     * "i want to add a special mode to the sfx guy and endless video
     *  mode to have him play clips appropriate to the statements being
     *  said on the radio ... I want this to be something I can toggle
     *  off and on."
     *
     * Its own row under #1184's pair, because it is a third thing the
     * set can be doing and not a third caption on either of them. The
     * SFX guy's STINGS have their own switch in "Where the clips come
     * from" (script-page.js); this one is the endless set's.
     *
     * IT SAYS WHAT IT IS DOING. The station re-ranks only the clip it
     * has not rung yet, and only when something in the library clears
     * the strength floor - so the honest caption is not "on/off" but
     * how many of the last picks were actually matched, which is what
     * the line underneath reports. */
    var matchRow = document.createElement('div');
    matchRow.id = 'pineSfxMatchRow';
    matchRow.setAttribute('style', 'display:flex;gap:8px;align-items:center;flex-wrap:wrap');
    var matchBtn = document.createElement('button');
    matchBtn.type = 'button';
    matchBtn.id = 'pineSfxMatchBtn';
    matchBtn.setAttribute('style', 'flex:1 1 58%;min-width:0;min-height:40px;border-radius:8px;'
      + 'border:1px solid #2c7a8c;background:#1d4d5a;color:#dfe7ee;font-size:12px;'
      + 'line-height:1.25;cursor:pointer');
    matchBtn.title = 'The next clip - the one nothing has warmed yet - is chosen '
      + 'to fit the line that will be sounding when it lights: loosely, by a noun, '
      + 'a verb, or what its folder is about. Nothing already queued or on the tube '
      + 'is touched, and when no clip fits the ordinary random draw runs, so the '
      + 'set never stalls waiting for a match.';
    var matchDial = document.createElement('input');
    matchDial.type = 'range';
    matchDial.id = 'pineSfxMatchDial';
    matchDial.min = '0'; matchDial.max = '100'; matchDial.step = '5'; matchDial.value = '35';
    matchDial.setAttribute('aria-label', 'How close a match has to be');
    matchDial.setAttribute('style', 'flex:1 1 38%;min-width:90px');
    var matchSay = document.createElement('div');
    matchSay.id = 'pineSfxMatchSay';
    matchSay.setAttribute('style', 'flex:1 1 100%;color:#9fb3c0;font-size:11px;min-height:14px');
    var matchWord = function (n) {
      n = Number(n) || 0;
      if (n <= 10) return 'any loose connection';
      if (n <= 40) return 'one uncommon word out of the line';
      if (n <= 70) return 'two words, or one rare one';
      return 'only a strong match';
    };
    var paintMatch = function (m) {
      if (m) matchState = m;
      var s = matchState || {};
      var on = !!s.video;
      var icon = '';
      try {
        if (typeof root.pineIcon === 'function') {
          icon = root.pineIcon(on ? 'c:magic-wand--filled' : 'c:search',
                               on ? 'Matching' : 'Not matching') || '';
        }
      } catch (err) { icon = ''; }
      matchBtn.innerHTML = icon + ' ' + (on ? 'MATCHING the dialogue' : 'MATCH the dialogue');
      matchBtn.style.background = on ? '#1d5a3a' : '#1d4d5a';
      matchBtn.style.opacity = (on && !endlessOn) ? '.78' : '1';
      matchBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (s.video_strength != null) matchDial.value = String(Number(s.video_strength));
      matchSay.textContent = 'strength ' + matchDial.value + ' - '
        + matchWord(matchDial.value) + '. '
        + (s.available === false ? 'the matcher is not on this station.'
           : !s.ready ? (s.building ? 'reading the clip names…'
                         : 'the clip names are not indexed yet.')
           : (String(s.clips || 0) + ' clip name(s) indexed, '
              + String(s.wordy || 0) + ' of them carrying words; '
              + String(s.picks || 0) + ' matched, '
              + String(s.fell_back || 0) + ' fell back to the ordinary draw.'))
        + (on && !endlessOn ? ' Armed - it takes effect when the set is on.' : '');
    };
    matchDial.addEventListener('input', function () {
      matchSay.textContent = 'strength ' + matchDial.value + ' - '
        + matchWord(matchDial.value) + '.';
    });
    matchDial.addEventListener('change', function (ev) {
      ev.stopPropagation();
      note.textContent = 'saving...';
      api().post('/api/sfx/match', {video_strength: Number(matchDial.value)}).then(
        function (got) { paintMatch(got || null); note.textContent = String((got && got.say) || 'saved'); },
        function (err) { note.textContent = 'the station would not take it: '
          + String((err && err.message) || err).slice(0, 60); });
    });
    matchBtn.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var want = !(matchState && matchState.video);
      note.textContent = 'saving...';
      api().post('/api/sfx/match', {video: want}).then(
        function (got) { paintMatch(got || null); note.textContent = String((got && got.say) || 'saved'); },
        function (err) {
          /* The station holds it, so a refusal means it did NOT change. */
          note.textContent = 'the station would not take it: '
            + String((err && err.message) || err).slice(0, 60);
        });
    });
    matchRow.appendChild(matchBtn);
    matchRow.appendChild(matchDial);
    matchRow.appendChild(matchSay);
    paintMatch(null);
    var close = document.createElement('button');
    close.type = 'button';
    close.textContent = 'Close';
    close.setAttribute('style', 'min-height:36px;border-radius:8px;border:1px solid #2a3a44;background:#111922;color:#dfe7ee;cursor:pointer');
    close.addEventListener('click', function (ev) { ev.stopPropagation(); endlessSheet(); });
    box.appendChild(head);
    box.appendChild(swRow);                                /* #1184 */
    box.appendChild(matchRow);                             /* [#1251] */
    box.appendChild(note);
    document.body.appendChild(box);
    sheetEl = box;
    api().get('/api/sfx/video/mode').then(function (st) {
      paintSw(!!(st && st.on));
      /* #1184: the station's held answer, not this browser's guess. An
         older station has no `seamless` key at all, and then the switch
         paints off and posting to it is what tells the operator so. */
      seamOn = !!(st && st.seamless);
      paintSeam(seamOn);
      /* [#1251] sfx_video_mode_state carries the matcher, so the row
         paints off the request the sheet already makes. */
      paintMatch((st && st.match) || null);
      box.insertBefore(row('Pictures among the SFX guy\'s clips', 0, 100, 1, Number((st && st.dial) || 0),
        function (v) { return v + '% of his clips carry a picture (mp4 vs mp3)'; }, 'share'), note);
      box.insertBefore(row('Clip length the endless set aims for', 0, 60, 1, Number((st && st.length) || 0),
        function (v) { return v ? ('about ' + v + ' seconds (draws between ' + Math.round(v * 0.6) + ' and ' + Math.round(v * 1.6) + ')') : 'any length in the library'; }, 'length'), note);
      box.appendChild(close);
      note.textContent = String((st && st.say) || '');
    }, function (err) { note.textContent = 'the station did not answer: ' + String((err && err.message) || err).slice(0, 60); box.appendChild(close); });
  }

  function endlessFlip() {
    if (!api() || !api().post) return;
    var want = !endlessOn;
    endlessOn = null;                               /* repaint on the next answer */
    api().post('/api/sfx/video/mode', {on: want}).then(function (got) {
      endlessPaint(!!(got && got.on));
      if (!want) { queue.length = 0; warmDrop(); if (hold) { clearTimeout(hold); hold = null; } }
    }, function () { /* the next poll paints the truth */ });
  }

  root.PineSfxTv = {
    __pineCanonicalSfxTv: true,
    __pineSfxTvDocument: document,
    /* 2026-09-14: for the LISTEN view's backdrop - is the set on, and
       hide the floating set while the view shows the clip as wallpaper. */
    timeline: function () { return tlRead(); },   /* [#1219] */
    endless: function () { return !!endlessOn; },
    veil: function (on) {
      veiled = !!on;
      try { if (host) host.style.visibility = veiled ? 'hidden' : ''; } catch (err) { /* no set up */ }
      /* #1434: AND THE NATIVE SURFACE, which has no `host` to hide - the
         listen view veils whoever is showing the endless clip so it is
         not on screen twice (#1184). [#1442] folds this into the one
         decision, because being veiled and being covered are two reasons
         for the same thing and two writers would fight over it. */
      try { wallVisibility(); } catch (err) { /* no bridge, no wall */ }
    },
    viewChanged: function () {
      /* Listen calls this on its class transition so leaving the view hands
         the native wall back immediately, rather than after the video poll. */
      try { wallVisibility(); return true; }
      catch (err) { return false; }
    },
    syncWall: function () { return wallFollow(); },
    wallClip: wallClip,
    shuffle: shuffleSet,
    openRadial: radialOpen,
    openParody: parodyOpen,
    openEditor: function (path, name) {
      if (!/^\/video-editor\/\?source=[0-9a-f]{32}&sfx=1$/.test(String(path || ''))) {
        throw new Error('The station did not return a clip editor URL');
      }
      editorWindow(path, function () {}, {sting: String(name || 'Sound effect')});
    },
    wireRadial: wireVideoRadial,
    leaveListen: leaveListen,
    mount: function (opts) {
      if (mounted) return;
      mounted = true;
      base = String((opts && opts.baseUrl) || '');
      wireDuck();                                          /* #1167 */
      wireWall();                                          /* #1184 */
      wireWallUi();
      poll();
      timer = setInterval(poll, POLL_MS);
      /* The server poll carries the whole clip ring and station policy. The
         native wall's current id is a tiny local bridge read, so follow it
         separately: Listen should not display the old clip for another
         server-poll interval after native playback has already advanced. */
      wallFollowTimer = setInterval(wallFollow, WALL_FOLLOW_MS);
      /* In browser runtimes this is a numeric handle. In Node-backed
         diagnostics it is a Timer, and the television must not own the
         process after every surface and assertion has finished. */
      if (timer && typeof timer.unref === 'function') timer.unref();
      if (wallFollowTimer && typeof wallFollowTimer.unref === 'function') wallFollowTimer.unref();
      /* A window that shrank under a set left near the edge would strand
       * it off screen; the clamp is the same one the opener uses. */
      root.addEventListener('resize', function () {
        if (!host || full) return;   /* #1122: 100vw follows by itself */
        host.style.left = Math.max(0, Math.min((root.innerWidth || 0) - 60,
          host.offsetLeft)) + 'px';
        host.style.top = Math.max(0, Math.min((root.innerHeight || 0) - 30,
          host.offsetTop)) + 'px';
      });
    },
    rebase: function (url) { base = String(url || ''); },
    repair: function (clip) {
      if (!mounted) root.PineSfxTv.mount({baseUrl: base});
      veiled = false;
      if (hold) { clearTimeout(hold); hold = null; }
      if (!clip || !clip.url) { next(); return Promise.resolve({ok: false, detail: 'No recovery clip was returned'}); }
      if (!root.PineSfxTv.cut(clip)) return Promise.resolve({ok: false, detail: 'Video surface refused the clip'});
      return new Promise(function (resolve) {
        var began = now();
        var check = setInterval(function () {
          var seenFrame = video && playing === clip && video.videoWidth > 0
            && !video.paused && video.currentTime > 0 && host && host.getBoundingClientRect().height > 0;
          if (seenFrame || now() - began > 12000) {
            clearInterval(check);
            resolve({ok: !!seenFrame, detail: seenFrame ? 'MP4 playing on this device' : 'MP4 did not start on this device'});
          }
        }, 150);
      });
    },
    /* The shell's master volume times the booth's share, handed over by
     * applyAppVolume - this window has no mixer of its own.
     *
     * [#1216] "The audio volume of a video should be set before the video
     * begins playing. I'm having the audio of the videos edited in the
     * middle of the videos playing, so the audio just jumps sporadically."
     *
     * THIS was the editing. renderer.js calls applyAppVolume() on every
     * view change, every route poll, every webview dom-ready and every
     * did-finish-load, and each of those wrote `video.volume` on whatever
     * clip happened to be on the tube - a step change, mid-picture,
     * however many times it was asked, and with the same number every
     * time. The panel's own pineMixerApply reaches the element from the
     * other side.
     *
     * So this is the one door and it does three things it did not:
     *
     *   - A LEVEL THAT HAS NOT CHANGED WRITES NOTHING. Not the element,
     *     not the warm tube, not the mute. That alone removes every
     *     sporadic jump, because nothing was ever asking for a different
     *     number - it was asking for the same one again.
     *   - A CHANGE THAT IS REAL WALKS THERE, over 120 ms, because a step
     *     in element volume is a click and the operator is dragging a
     *     slider.
     *   - THE WARM TUBE IS LEVELLED TOO, so the NEXT clip begins at the
     *     level that is set now rather than the one set when it warmed.
     *
     * pineLevels (audio-law.js, #1187) is the bus that calls this. */
    level: function (value) {
      var want = Math.max(0, Math.min(2, Number(value)));
      if (!isFinite(want)) return;
      if (Math.abs(want - level) < 0.001) {               /* [#1216] */
        level = want;
        return;                                /* nothing has changed */
      }
      level = want;
      /* The clip warming behind this one takes it at once: it is not
         sounding, so there is nothing to ramp and nothing to hear. */
      try { if (warm && warm.el) levelSet(warm.el, level, false); } catch (err) { /* gone */ }
      if (!video) return;
      var el = video;
      if (level > 0 && el.muted && el.dataset.pineSilentPicture !== '1') el.muted = false;
      levelRamp(el, level);                                /* [#1216] */
    },
    stop: function () {
      if (timer) clearInterval(timer);
      if (wallFollowTimer) clearInterval(wallFollowTimer);
      if (hold) clearTimeout(hold);
      timer = wallFollowTimer = hold = null;
      mounted = false;
      warmDrop();                                          /* #1411 */
      replays = 0; runLeft = 0; runFrom = ''; lastDouble = 0;  /* #1121/#1124 */
      teardown();
    },
    /* Numbers the operator can look at rather than a claim in a comment. */
    box: readBox,
    waiting: function () { return queue.length; },
    on: function () { return showing; },
    offer: offer,
    /* [#1214] the arbiter, on the desk. The same object as
       window.PineSfxFloor - reachable from the set the operator already
       has a handle on. */
    floor: function () { return root.PineSfxFloor; },
    hush: function (keep) { return hushOthers(keep || video); },
    hushed: function () { return {count: hushed.count, at: hushed.at, last: hushed.last}; },
    /* #1322: "this clip has been dealt with here", for a caller that
       rang the station by some other road and does not want its own
       picture back. */
    mark: markOf,
    /* #1306b: CUT TO THIS ONE, NOW.
     *
     * offer() queues and next() refuses while `showing`, which is
     * right for the station's own stings - two pictures at once is
     * the fault there. It is exactly wrong for the operator's thumb:
     * a second tap means "not that one, this one". So rapid fire
     * reads as cycling instead of as a queue draining, and the
     * station's own road is untouched.
     *
     * The mark is set the way offer() sets it, so the poll that later
     * sees this same clip in the ring does not play it a second
     * time.
     *
     * #1322: `{ring: true}` says the caller fired this clip LOCALLY and
     * the station has never heard of it - a sampler pad, not the cue
     * road - so it is also published for the other surfaces' sets. A
     * clip that came back FROM the station is already in the ring and
     * must not be rung again.
     *
     * #1121/#1124: `replays` and `runLeft` are NOT touched here. Next,
     * Prev and the run itself all arrive through this door, and a
     * fresh tap on the video button mid-run is "and also this one",
     * not "and stop the run" - the operator's Stop and the slider at 0
     * are the roads that end it. */
    cut: function (clip, opts) {
      if (!clip || !clip.url) return false;
      /* Before the mount check, deliberately: a surface with no set of
         its own still owes the other surfaces the picture. */
      if (opts && opts.ring) ring(clip);
      if (!mounted) return false;
      try { markOf(clip); }
      catch (err) { /* the play below still stands */ }
      /* #1184: A SEAMLESS HAND-OVER IS THE PLAN ARRIVING, NOT A CUT AWAY
       * FROM IT. Every other caller here means "not that one, this one",
       * so clearing the queue and dropping the warm element is right for
       * them. For the seam both would be wrong in the same breath: the
       * queue IS the rest of the cycle the operator asked to keep
       * running, and the warm element is the very thing being put in the
       * tube - warmDrop() would pause it, strip its src and load() it,
       * and then play() would take a dead element. `__cut` is left alone
       * too, because that flag arms the #1311d "the operator tapped and
       * is owed a picture" retry, and this is the station's own plan
       * turning over, not a tap. */
      var seam = !!(opts && opts.seam);
      if (!seam) {
        queue.length = 0;
        warmDrop();                                        /* #1411 */
      }
      if (hold) { clearTimeout(hold); hold = null; }
      try { clip.__seam = seam; } catch (err) { /* frozen: it animates */ }
      if (!seam) {
        try { clip.__cut = true; } catch (err) { /* frozen: no retry */ }
      }
      /* Down without waiting out the CRT collapse - the next picture
         is the answer to the tap, not the animation.
         [#1212] ...UNLESS THE SEAM CAN USE THE SLOT. This line was the
         whole of the 187-264 ms outliers: teardownNow() sweeps every
         .sfx-tv out of the document, which detaches the warm element the
         seam is about to play and throws away the decoder it had stood
         up. On a seam whose warm tube is already inside the tube on
         screen the host stays and play() promotes it where it stands. */
      if (!(seam && host && tube && video && warm && warm.clip === clip
            && warm.el && warm.el.parentNode === tube)) {
        try { teardownNow(); } catch (err) { /* nothing was up */ }
      }
      showing = true;
      try { play(clip); return true; }
      catch (err) { showing = false; return false; }
    },
    playing: function () { return playing; },

    /* [#1441] THE PICTURE IS NATIVE, SO THE TAP ON IT ARRIVES HERE.
     *
     * The wall consumes the press (it IS the picture; nothing behind it
     * wanted that tap) and hands over the SCREEN point in DEVICE pixels.
     * The ratio lives here, so the conversion does too - carrying 1.25
     * in two places is how the two drift apart.
     *
     * It opens the same hold sheet a press on the old tube opened, on
     * whatever PineSfxTv.playing() says is up - which #1435 keeps
     * pointed at the clip the wall is actually showing. */
    tapPicture: function (x, y) {
      if (!playing) return false;
      var d = Number(root.devicePixelRatio) || 1;
      var px = Number(x) / d;
      var py = Number(y) / d;
      if (!isFinite(px) || !isFinite(py)) return false;
      /* A bare Listen screen uses the native surface, so its taps arrive
         here instead of at listen.js's DOM host. They still belong to
         Listen: one tap does nothing destructive; two toggle its chrome. */
      if (listenUp()) {
        try {
          var listen = root.PineListen;
          if (listen && typeof listen.nativeTap === 'function') {
            return !!listen.nativeTap(px, py);
          }
        } catch (err) { /* consuming it is still safer than an inspector */ }
        return true;
      }
      /* [#1444] and WHICH WINDOW it came from. A sheet that knows its box
         is centred on it rather than opened above the finger - there is
         no finger here, and the operator means "on the video". */
      var over = null;
      try { over = readBox(); } catch (err) { over = null; }
      try { sheet(playing, {x: px, y: py, box: over}); }
      catch (err) { return false; }
      return true;
    },
    /* The native SurfaceView owns fullscreen Listen input. Its long-press
       callback lands here so the same radial menu appears over that surface
       and over the ordinary web video window. */
    holdPicture: function (x, y) {
      if (!playing) return false;
      var d = Number(root.devicePixelRatio) || 1;
      var px = Number(x) / d;
      var py = Number(y) / d;
      if (!isFinite(px) || !isFinite(py)) return false;
      if (radialWrap) { radialClose(true); return true; }
      radialOpen(playing, {x: px, y: py});
      return true;
    },
    /* Android moves/resizes the SurfaceView at touch rate and reports only
       the final rectangle. Keeping that hot path out of evaluateJavascript
       is what makes a drag stay under the finger on a busy Script view. */
    wallBoxChanged: function (x, y, w, h) {
      return rememberWallBox(x, y, w, h);
    },
    /* The native hold watchdog uses this if a menu was abandoned. One door
       out means the shade, owed finish and playback hold are all released. */
    releaseHold: function () {
      if (radialWrap) { radialClose(false); return true; }
      if (deleteWrap) { deleteConfirmClose(false); return true; }
      if (!sheetHeld()) return false;
      sheetClose();
      return true;
    },
    /* #1200: NUMBERS RATHER THAN A CLAIM IN A COMMENT. The one thing that
       has to be PROVED about the poster queue is a negative - that more
       than two are never in flight - and a negative cannot be seen on
       screen. Same reason sampler-face.js exports its own two. */
    shotsInFlight: function () { return shotLive; },
    shotsWaiting: function () { return shotQueue.length; },
    history: function () { return hist.slice(); },
    histState: function () {
      return {rows: hist.length, more: histMore, busy: histBusy,
              bad: histBad, say: histSay, lost: histLost, at: histAt};
    },
    /* #1200: THE STRIP ON ITS OWN. The sheet it normally lives in wants a
       pointer, a set that is already up and a clip on the tube; the paging
       in it wants none of those. This door builds the same element the
       sheet builds, through the same road, so a test drives the real wheel
       handler, the real fetch and the real ceiling rather than a copy of
       them that could agree with itself while the strip was broken. */
    strip: function (clip, say) {
      return stripBuild(clip || null,
                        typeof say === 'function' ? say : function () {});
    },
    /* #1173: how far into the clip on the tube the station is, in seconds
     * on this machine's clock - so the LISTEN view's wallpaper (listen.js,
     * paintEndless) joins the SAME frame as this set rather than starting
     * the file from zero up to a second after the set moved on. Measured
     * before this existed: the wall ran 0.85 s behind the floating set on
     * the SAME device (median of 419 samples), and was on a different clip
     * entirely in 6% of them. Takes the clip it is asked about, or the one
     * in the tube. */
    airInto: function (clip) { return airInto(clip || playing); }
  };

  /* #1306b: AND IT COMES ON BY ITSELF WHERE NOBODY MOUNTS IT.
   *
   * The desktop shell mounts this explicitly, with a baseUrl, because
   * its renderer is not served from the station. The tablet's view
   * bundle has no such step - every view there is injected and left to
   * find its own feet - so the set existed on one surface only, while
   * the operator taps the video button on the other.
   *
   * Deferred rather than immediate: the shell's own mount runs during
   * its startup and `if (mounted) return` makes this a no-op there.
   * Where nothing has claimed it after a few seconds, this is the
   * tablet, the page is served from the station, and a relative base
   * is the right one.
   */
  try {
    if (root.document && root.setTimeout) {
      root.setTimeout(function () {
        try {
          if (mounted) return;
          /* [#1214] A PAGE WITH A GALLERY STAGE (the tune-in page, tvPoll)
             already plays the ring on the stage; a second, floating set
             here was the same clip twice, out of step, both audible. */
          try {
            if (root.document.getElementById && root.document.getElementById('galleryStage')) return;
          } catch (err) { /* no such door: mount as before */ }
          if (mounted) return;
          if (/^https?:$/.test(String(root.location.protocol))) {
            root.PineSfxTv.mount({baseUrl: ''});
          } else if (root.pineDesktop) {
            /* #1399: AND ON THE DESKTOP, WHERE THE SHELL'S OWN MOUNT CAN
             * RUN TOO EARLY. renderer.js mounts this inside loadConfig,
             * and loadConfig runs before this file has been evaluated -
             * so window.PineSfxTv was undefined at that instant and the
             * mount was skipped. Measured: with the endless set ringing
             * three clips ahead and the tablet playing them, the desktop's
             * tube stayed dark until mount() was called by hand, after
             * which it lit within twelve seconds. The base is the one the
             * chrome already knows (#1348). */
            var b = '';
            try { b = root.pineStationBase ? String(root.pineStationBase() || '') : ''; }
            catch (err) { b = ''; }
            root.PineSfxTv.mount({baseUrl: b || 'http://127.0.0.1:8096'});
          }
        } catch (err) { /* no set is better than a broken view */ }
      }, 3000);
    }
  } catch (err) { /* not a browser */ }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineSfxTv;
  }
})(typeof window !== 'undefined' ? window : globalThis);
