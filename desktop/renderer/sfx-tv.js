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

  var KEY = 'pineSfxTvBox';       // the preference: left, top, width, height
  var POLL_MS = 2500;
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

  var playing = null;              // #1306b: the clip in the tube now
  var host = null;                 // the window, while a clip is in it
  var video = null;
  var tube = null;
  var timer = null;                // the poll
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
  var FULL_KEY = 'pineSfxTvFull';  // #1122: '1' when the next set opens full
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
  var HEARD_MOST = 6;              // bounded, and small - the strip shows two
  var STRIP_EACH = 2;              // "the last 2 ... and the next 2"
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
    if (!wasOnWall) return;        // it goes with the set being swept
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err) { /* already gone */ }
  }

  /* #1112: THE ONE DOOR OUT OF THE SHEET. Close, the second hold, Stop,
   * a delete or a ban that is done - every one of them comes through
   * here, because a road that removed the sheet by hand would leave an
   * owed finish owed for ever: a set on its last frame that nothing
   * ever takes down. */
  function sheetClose() {
    var wrap = sheetWrap;
    sheetWrap = null;
    sheetOnWall = false;                                 /* #1184 */
    panel = null;                                        /* #1184 */
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err) { /* already gone */ }
    var due = owed;
    owed = false;
    if (due && curtain) {
      try { curtain(); } catch (err) { /* the set is already going */ }
    }
  }

  function now() { return Date.now(); }

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

  /* #1121: THE HOLD BUBBLE. "If I tap and hold on the video, then show
   * a pop-up asking me if I would like to assign it to the sampler."
   * A small question over the picture, two answers, and it goes away
   * by itself after six seconds so a hold that was a fumble leaves
   * nothing behind. The hold used to open the sheet (#1306b); that is
   * the tap's job now. */
  function ask(screen) {
    if (!screen || !playing) return;
    askDrop();
    var wrap = document.createElement('div');
    wrap.className = 'sfx-tv-ask';
    var s = wrap.style;
    s.position = 'absolute'; s.left = '50%'; s.top = '50%';
    s.transform = 'translate(-50%, -50%)';
    s.zIndex = '5'; s.maxWidth = '88%'; s.boxSizing = 'border-box';
    s.padding = '10px 12px'; s.borderRadius = '8px';
    s.border = '1px solid #65c7da'; s.background = '#0b1116';
    s.color = '#dfe7ee'; s.font = 'inherit'; s.fontSize = '12px';
    s.textAlign = 'center';
    var q = document.createElement('div');
    q.textContent = 'Put this clip on a sampler pad?';
    q.style.marginBottom = '8px';
    var row = document.createElement('div');
    row.style.display = 'flex'; row.style.gap = '8px';
    row.style.justifyContent = 'center';
    var say = function (text) {
      q.textContent = String(text || '');
      setTimeout(function () { if (askWrap === wrap) askDrop(); }, 2400);
    };
    var answer = function (label, go) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      var bs = b.style;
      bs.minHeight = '32px'; bs.minWidth = '32px'; bs.padding = '6px 12px';
      bs.font = 'inherit'; bs.fontSize = '12px'; bs.borderRadius = '6px';
      bs.border = '1px solid #65c7da'; bs.background = '#0b1116';
      bs.color = '#dfe7ee'; bs.cursor = 'pointer';
      b.addEventListener('click', function (ev) {
        ev.stopPropagation();
        go();
      });
      row.appendChild(b);
      return b;
    };
    var yes = answer('Yes, to a pad', function () {
      row.style.display = 'none';
      toPad(playing, say);
    });
    yes.style.background = '#65c7da'; yes.style.color = '#0b1116';
    answer('No', function () { askDrop(); });
    wrap.appendChild(q);
    wrap.appendChild(row);
    /* A press on the bubble is not a press on the picture. */
    wrap.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    screen.appendChild(wrap);
    askWrap = wrap;
    setTimeout(function () { if (askWrap === wrap) askDrop(); }, 6000);
  }

  function askDrop() {
    var wrap = askWrap;
    askWrap = null;
    try { if (wrap && wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    catch (err) { /* already gone */ }
  }

  function build(name, ready) {      /* #1411: `ready` is a warmed <video> */
    /* #1312: one set at a time, always. A stray from an earlier cut
       would otherwise sit here holding a connection for ever. */
    try {
      var old = document.querySelectorAll('.sfx-tv');
      for (var i = 0; i < old.length; i += 1) {
        var v = old[i].querySelector('video');
        try { if (v) { v.pause(); v.removeAttribute('src'); v.load(); } }
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
    /* #789/#981: the shell owns live element volume, and the booth monitor
     * switch governs anything tagged pine-live. A sting that skipped the
     * tag would be the one sound in this window nobody could turn down. */
    video.dataset.pineLive = 'voice';
    video.volume = level;
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
        press = null;
        if (tapTimer) { clearTimeout(tapTimer); tapTimer = 0; }
        if (playing) ask(screen);
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
    return {shut: shut, flash: flash};
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
    var going = mine || video;
    /* Removing a <video> from the document does NOT stop it, so the src
     * goes first and the node second. */
    try { if (going) { going.pause(); going.removeAttribute('src'); going.load(); } }
    catch (err) {}
    try { if (host && host.parentNode) host.parentNode.removeChild(host); }
    catch (err) {}
    /* #1312: and anything an earlier tangle left attached. */
    try {
      var stray = document.querySelectorAll('.sfx-tv');
      for (var i = 0; i < stray.length; i += 1) {
        var v = stray[i].querySelector('video');
        try { if (v) { v.pause(); v.removeAttribute('src'); v.load(); } }
        catch (e2) { /* already gone */ }
        if (stray[i].parentNode) stray[i].parentNode.removeChild(stray[i]);
      }
    } catch (err) { /* nothing stray */ }
    host = video = tube = null;
    sheetForget(); curtain = null; owed = false;        /* #1112 / #1184 */
    rewind = null; badge = null; askWrap = null;        /* #1121 */
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
    var all = document.querySelectorAll('.sfx-tv');
    for (var i = 0; i < all.length; i += 1) {
      var v = all[i].querySelector('video');
      try { if (v) { v.pause(); v.removeAttribute('src'); v.load(); } }
      catch (err) { /* already gone */ }
      try { if (all[i].parentNode) all[i].parentNode.removeChild(all[i]); }
      catch (err) { /* already gone */ }
    }
    host = video = tube = null;
    sheetForget(); curtain = null; owed = false;        /* #1112 / #1184 */
    rewind = null; badge = null; askWrap = null;        /* #1121 */
    showing = false;
  }

  /* ---- one clip ------------------------------------------------------ */

  function play(clip) {
    /* #1184: whatever was in the tube is now the past, whichever road
       took it out - the clip ending, a seamless hand-over, the operator
       cutting, a run stepping on. One line here covers every one of
       them, which is why the strip cannot end up with a hole in it. */
    remember(playing);
    playing = clip;                                        /* #1306b */
    var tries = Number(clip.__tries) || 0;                 /* #1311d */
    var ready = warmTake(clip);                            /* #1411 */
    var parts = build(clip.sting || clip.text || 'SFX', ready);
    /* Held locally, because every handler and timer below can fire after
     * the module's own references have moved on. */
    var screen = video;
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
    if (!ready) screen.src = srcOf(clip);
    screen.addEventListener('canplaythrough', function () { warmUp(); });
    screen.volume = level;
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
      if (!isFinite(off) || Math.abs(off) < SLIP_MAX) return;
      if (now() - fixedAt < SLIP_REST) return;
      var span = Number(screen.duration);
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
    var back = heard.slice(-STRIP_EACH);
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
    for (i = 0; i < ahead.length && rows.length < (STRIP_EACH * 2) + 1; i += 1) {
      if (mine && String(ahead[i].id) === mine) continue;
      rows.push({id: ahead[i].id, url: ahead[i].url, sting: ahead[i].sting,
                 video: !!ahead[i].video,                    /* #1199 */
                 seconds: ahead[i].seconds, at: ahead[i].at, when: 'next'});
      if (rows.length >= STRIP_EACH + 1 + STRIP_EACH) break;
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

  function step(clip, dir, say) {
    var id = clipId(clip);
    if (!id) { say('no id on this clip'); return; }
    say(dir === 'prev' ? 'the one before...' : 'the next one...');
    neighbour(id, dir).then(function (got) {
      if (got && got.ok && got.clip && got.clip.url) {
        /* #1124: a run in progress carries on from the clip stepped to. */
        if (runLeft > 0) runFrom = clipId(got.clip);
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
    var s = b.style;
    s.flex = '0 0 auto'; s.width = '76px'; s.padding = '0';
    s.display = 'flex'; s.flexDirection = 'column'; s.gap = '2px';
    s.alignItems = 'stretch'; s.overflow = 'hidden';
    s.borderRadius = '6px'; s.cursor = 'pointer';
    s.background = 'rgba(159, 216, 255, .06)';
    s.border = mine ? '1px solid #65c7da'
                    : '1px solid rgba(159, 216, 255, .24)';
    var shot = document.createElement('div');
    shot.style.height = '44px'; shot.style.background = '#05080b';
    shot.style.overflow = 'hidden'; shot.style.position = 'relative';
    if (row.id) {
      var img = document.createElement('img');
      img.alt = '';
      img.style.width = '100%'; img.style.height = '100%';
      img.style.objectFit = 'cover'; img.style.display = 'block';
      /* Signed the way every other media url on this station is, and
         through the same base the clip itself is fetched through, so it
         works on the tablet (relative) and in the shell (absolute). */
      img.onerror = function () {
        try { if (img.parentNode) img.parentNode.removeChild(img); }
        catch (err) { /* already gone */ }
      };
      img.src = base.replace(/\/+$/, '') + posterOf(row);
      shot.appendChild(img);
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
      : (row.when === 'next' ? ('next' + soon) : 'played');
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
      + String(row.sting || 'clip') + ' - tap to open its menu';
    b.addEventListener('click', function (ev) {
      ev.stopPropagation();
      if (mine) { say('that is the one on the tube'); return; }
      /* The tile is a handle onto the SAME sheet, opened for that clip:
         "tap them to jump to them and play / examine / manage them as
         well". So it re-opens here rather than playing at once, and the
         sheet it opens carries a Play it of its own - examining a clip
         and jumping to it are two different intentions and a single tap
         must not guess between them. */
      var at = sheetAt;
      sheetClose();
      sheet({id: row.id, url: row.url, sting: row.sting,
             seconds: row.seconds}, at);
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

  function stripBuild(clip, say) {
    var rows = stripRows();
    var strip = document.createElement('div');
    strip.className = 'sfx-tv-strip';
    strip.style.display = 'flex'; strip.style.gap = '5px';
    strip.style.overflowX = 'auto'; strip.style.overflowY = 'hidden';
    strip.style.margin = '0 0 6px 0'; strip.style.paddingBottom = '2px';
    if (!rows.length) {
      var none = document.createElement('i');
      none.className = 'sfx-tv-note';
      none.textContent = 'nothing else in the cycle yet';
      strip.appendChild(none);
      return strip;
    }
    var here = clipId(clip);
    for (var i = 0; i < rows.length; i += 1) {
      strip.appendChild(stripTile(rows[i], rows[i].id === here, say));
    }
    return strip;
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
                 seconds: Number(row.seconds) || 0};
    say('putting it on...');
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
  var sheetAt = null;
  function sheet(clip, at) {
    if (!host) return;
    /* #1112: a second hold shuts it - through the one door, so a clip
       that ended under the sheet is finished now, not left standing. */
    if (sheetHeld()) { sheetClose(); return; }
    sheetAt = at || null;                                  /* #1184 */
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
    var rowB = document.createElement('div');
    rowB.className = 'sfx-tv-sheetrow';
    /* #1112: a third row for the two that take the picture away, so
       the labels stay short enough for a 420 px set on the tablet. */
    var rowC = document.createElement('div');
    rowC.className = 'sfx-tv-sheetrow';

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
    button(rowA, 'Inspect', 'What the station knows about this clip',
           function () { inspect(clip, say, wrap); });     /* #1184 */
    button(rowA, 'Where is it', 'Show where this clip lives',
           function () { locate(clip, say); });
    button(rowA, '\u25b2 More', 'Play it more often',
           function () { weigh(clip, true, say); });
    button(rowA, '\u25bc Less', 'Play it less often',
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

    /* #1122/#1123: A FOURTH ROW - the clip beside this one either way,
       and the window filled or put back. Three short labels, so a
       420 px set on the tablet still fits them; and 32 px tall inline,
       because the stylesheet's sheet buttons are sized for a mouse. */
    var rowD = document.createElement('div');
    rowD.className = 'sfx-tv-sheetrow';
    var tall = function (b) { b.style.minHeight = '32px'; return b; };
    tall(button(rowD, 'Prev', 'The clip before this one in its folder',
                function () { step(clip, 'prev', say); }));
    tall(button(rowD, 'Next', 'The clip after this one in its folder',
                function () { step(clip, 'next', say); }));
    var fill = tall(button(rowD, full ? 'Windowed' : 'Full screen',
      'Fill the window with the picture, or put it back in its box',
      function () {
        setFull(!full);
        fill.textContent = full ? 'Windowed' : 'Full screen';
        say(full ? 'full screen, until it is turned off'
                 : 'back in its window');
      }));

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

    wrap.appendChild(name);
    /* #1184: the cycle's own picture, directly under the clip's name and
       above every button - "show thumbnails of the last 2 videos played
       and the next 2 videos planned for play". It is what he is looking
       at, so it goes where the eye lands first. */
    wrap.appendChild(stripBuild(clip, say));
    wrap.appendChild(rowA);
    wrap.appendChild(rowF);                                /* #1184 */
    wrap.appendChild(rowB);
    wrap.appendChild(rowD);
    wrap.appendChild(rowE);
    wrap.appendChild(rowC);
    wrap.appendChild(note);
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
    home.appendChild(wrap);
    sheetOnWall = true;                                    /* #1184 */
    sheetWrap = wrap;                                      /* #1112 */
    /* Placed only once it has a height: above the finger where there is
       room for it, below it where there is not, and never off either
       edge. Measured after the append because a sheet whose rows depend
       on `mine` is not always the same height. */
    var tall = wrap.offsetHeight || 260;
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

  function warmDrop() {
    if (!warm) return;
    var el = warm.el;
    warm = null;
    try { el.pause(); el.removeAttribute('src'); el.load(); }
    catch (err) { /* already gone */ }
  }

  function warmUp() {
    if (!mounted) return;
    var head = queue[0];
    if (!head || !head.url) return;
    if (warm && warm.clip === head) return;
    warmDrop();
    var el;
    try {
      el = document.createElement('video');
      el.preload = 'auto';
      el.playsInline = true;
      el.controls = false;
      el.src = srcOf(head);
      el.load();
    } catch (err) { return; }
    warm = {clip: head, el: el};
  }

  /* The warm element for this clip, if it is the one that was warmed
     and it has not already failed - a failed one is thrown away here so
     play() builds a fresh element and hears the error itself. */
  function warmTake(clip) {
    if (!warm || warm.clip !== clip) return null;
    var el = warm.el;
    warm = null;
    if (el.error) {
      try { el.removeAttribute('src'); el.load(); } catch (err) {}
      return null;
    }
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

  function offer(clip) {
    if (!clip || !clip.url) return;
    if (marks[String(clip.ts || '') + '|' + String(clip.url)]) return;
    markOf(clip);
    queue.push(clip);
    if (queue.length > 4) queue.splice(0, queue.length - 4);
    comingKeep(clip);                                       /* #1195 */
    /* #1411b: a clip that arrives while one is on screen is warmed at
       once if the one on screen already has what it needs. */
    if (!showing || (video && (video.readyState >= 4
                               || Number(video.currentTime) > 1.5))) warmUp();
    next();
  }

  async function poll() {
    wireDuck();                                            /* #1167 */
    wireWall();                                            /* #1184 */
    if (busy || !api() || !api().get) return;
    busy = true;
    try {
      var got = await api().get('/api/dj/video?since=' + seen);
      var serverMs = Number((got && got.server_ms) || now());
      /* #1184: the hand-over style, on the poll this set already makes -
       * no second request, and both surfaces read the one answer so the
       * desk and the tablet cannot disagree about it. A station that has
       * not been patched yet simply never sends the key, `seamOn` stays
       * false, and every changeover is the CRT collapse it is today. */
      if (got && typeof got.seamless === 'boolean') seamOn = !!got.seamless;
      if (got && typeof got.endless === 'boolean') {
        endlessPaint(got.endless);
        if (!got.endless) {
          /* 2026-09-14: off means off - the rung-ahead copies go */
          for (var qi = queue.length - 1; qi >= 0; qi -= 1) { if (queue[qi].endless) queue.splice(qi, 1); }
          coming.length = 0;                                 /* #1195 */
          if (warm && warm.clip && warm.clip.endless) warmDrop();
        }
      }
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
        if (sheetHeld()) { sheetClose(); return; }
        sheet(playing, was);
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
  function endlessSheet() {
    if (sheetEl && sheetEl.parentNode) { sheetEl.parentNode.removeChild(sheetEl); sheetEl = null; return; }
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
    var paintSeam = function (on) {
      var word = on ? (endlessOn ? 'SEAMLESS on' : 'SEAMLESS armed')
                    : 'SEAMLESS off';
      seam.innerHTML = ((typeof root.pineIcon === 'function'
        ? root.pineIcon('c:repeat', 'Seamless') : '') || '') + ' ' + word;
      seam.style.background = on ? '#1d5a3a' : '#1d4d5a';
      seam.style.opacity = (on && !endlessOn) ? '.78' : '1';
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
    swRow.appendChild(sw);
    swRow.appendChild(seam);
    var close = document.createElement('button');
    close.type = 'button';
    close.textContent = 'Close';
    close.setAttribute('style', 'min-height:36px;border-radius:8px;border:1px solid #2a3a44;background:#111922;color:#dfe7ee;cursor:pointer');
    close.addEventListener('click', function (ev) { ev.stopPropagation(); endlessSheet(); });
    box.appendChild(head);
    box.appendChild(swRow);                                /* #1184 */
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
    /* 2026-09-14: for the LISTEN view's backdrop - is the set on, and
       hide the floating set while the view shows the clip as wallpaper. */
    endless: function () { return !!endlessOn; },
    veil: function (on) {
      veiled = !!on;
      try { if (host) host.style.visibility = veiled ? 'hidden' : ''; } catch (err) { /* no set up */ }
    },
    mount: function (opts) {
      if (mounted) return;
      mounted = true;
      base = String((opts && opts.baseUrl) || '');
      wireDuck();                                          /* #1167 */
      wireWall();                                          /* #1184 */
      poll();
      timer = setInterval(poll, POLL_MS);
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
    /* The shell's master volume times the booth's share, handed over by
     * applyAppVolume - this window has no mixer of its own. */
    level: function (value) {
      level = Math.max(0, Math.min(1, Number(value)));
      if (video) {
        video.volume = level;
        if (level > 0 && video.muted) video.muted = false;
      }
    },
    stop: function () {
      if (timer) clearInterval(timer);
      if (hold) clearTimeout(hold);
      timer = hold = null;
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
         is the answer to the tap, not the animation. */
      try { teardownNow(); } catch (err) { /* nothing was up */ }
      showing = true;
      try { play(clip); return true; }
      catch (err) { showing = false; return false; }
    },
    playing: function () { return playing; },
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
