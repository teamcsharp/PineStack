/* THE PINE CAM, WHEN IT IS THERE AND ONLY THEN.
 *
 * "Whenever I turn on the camera and it's being detected by the DGX Spark
 *  or the Pine tab, I want to see a notification tab on the display that
 *  I'm able to tap that basically makes the camera start show up as a
 *  display on the screen as a picture in picture."
 *
 * So the button does not sit there greyed out. It is absent until the
 * station says the link is live, and it goes again when the camera does -
 * a control for something that is not connected is a control that teaches
 * you to ignore it.
 *
 * WHY A PICTURE AND NOT A VIDEO. The live feed is HLS, and Chromium plays
 * no HLS without a library this project does not vendor - and the tablet's
 * WebView is the same engine, so a library would have to be vendored twice
 * and shipped in the APK. `/api/pinelink/frame.jpg` is the camera four
 * times a second in an <img>, which needs nothing, works identically on
 * the desktop and the tablet, and for a corner-of-the-screen preview is
 * indistinguishable. The recordings keep the full stream.
 *
 * #1470: ...FOR A PREVIEW. Watched as a monitor it was four stills a
 * second in a page that paints six frames a second, with one still in
 * five thrown away because the next request cancelled it. On the tablet
 * the picture now leaves the page: the kiosk plays the supervisor's
 * MPEG-TS door natively on a SurfaceView (pineDesktop.pineCam), and this
 * file only tells it where the box is. See "the native picture" below.
 *
 * It is deliberately the same shape as the SFX TV set (#1263): body-level,
 * draggable, remembers where you left it.
 */
(function (root) {
  'use strict';

  var POLL_MS = 5000;          /* is the camera there */
  var FRAME_MS = 250;          /* four a second, which is what is written */
  var KEY = 'pineCamBox';

  var timer = 0;
  var frameTimer = 0;
  var box = null;
  var folded = false;
  var FOLD_KEY = 'pineCamFolded';
  var busy = false;
  var shown = false;
  var live = false;

  /* #1470: THE NATIVE PICTURE. On the tablet the kiosk offers
   * pineDesktop.pineCam(verb, arg): an ExoPlayer on a SurfaceView above
   * the WebView, playing the supervisor's MPEG-TS door (state.ts) at the
   * camera's full 30 fps about half a second behind live. The WebView
   * itself paints at 6 fps whatever it holds - measured 2026-09-27 with
   * this box open and closed alike - so no <img> or <video> in this page
   * can ever be smooth; the picture has to leave the page. The <img>
   * stays underneath as the poster and the fallback, slowed to one a
   * second while the surface is up. The desktop has no pineCam and keeps
   * the JPEG road exactly as it was. */
  var NATIVE_POSTER_MS = 1000;
  var tsInfo = null;           /* state.ts while the door is up, else null */
  var nativeOn = false;
  var nativeFull = false;
  var nativeAsked = false;     /* an 'on' is in flight */
  var boxMoveRaf = 0;
  var lastBoxKey = '';

  /* 2026-09-27: "put a small arrow that if I tap it it collapses the
   * header ... making the pop-up just a window. And then if I double tap
   * the PineCam video, then show the header again ... and by default hide
   * the header because I don't need it anymore." The bar folds away (the
   * arrow, or a double tap on the picture) and comes back on a double tap;
   * every open starts bare. A single tap keeps its meaning (full screen on
   * the native picture) and waits a third of a second first, so a double
   * tap is never read as two of them. */
  var BARE_DEFAULT = true;
  var bare = false;
  var tapAt = 0;
  var tapTimer = 0;

  /* [pincrop] THE CROP: hold -> radial -> draw -> the station -> the
   * supervisor's encode (tools/pinelink.py). This page never cuts a pixel:
   * it draws the box and posts fractions, and every road - the TS door,
   * the HLS, the stills, the clips - shows only what the encode kept. */
  var HOLD_MS = 550;           /* the SFX wall's hold: same finger, same wait */
  var HOLD_SLOP = 8;
  var CROP_RAW_MS = 500;       /* frame_raw.jpg is written twice a second */
  var holdMute = 0;            /* a hold happened: its release is not a tap */
  var cropOn = false;          /* state.json's crop.on, as last polled */
  var cropShade = null;        /* the radial */
  var cropEl = null;           /* the draw overlay */
  var cropRawTimer = 0;
  var cropUnwatch = null;      /* PineDismiss registrations, undone on close */
  var cropDrawUnwatch = null;
  var cropView = null;         /* GET /api/pinelink/crop as last read */
  var cropWatch = 0;           /* the after-apply poll */

  /* #1358: AND IT HAD NO ANSWER AT ALL OFF THE DESKTOP.
   *
   * pineStationBase is defined by the Electron renderer. Anywhere else -
   * the tablet's panel, a browser pointed at the station - it is
   * undefined, this function fell off its own end, and every URL built
   * from it began with the four letters `undefined`. The frame road, the
   * look road and the doctor all failed the same way and all failed
   * silently, because each caller catches.
   *
   * Where the document IS served by the station a bare path is not just
   * acceptable, it is correct: it follows the host the panel was opened
   * on, which on the tablet is the loopback door.
   */
  function base() {
    try {
      if (root.location && /^https?:$/.test(root.location.protocol)) {
        return '';
      }
      if (root.pineStationBase) return root.pineStationBase();
    } catch (e) { /* fall through to the last resort */ }
    return 'http://10.89.1.246:8096';
  }

  function ask(path) {
    /* The chrome is a file:// document, so a bare relative fetch resolves
     * to file:///api/... and fails. Everything here goes through the
     * station's address. */
    try {
      if (root.pineDesktop && root.pineDesktop.get) {
        return root.pineDesktop.get(path);
      }
    } catch (e) { /* fall through to fetch */ }
    return fetch(base() + path, {cache: 'no-store'})
      .then(function (r) { return r.ok ? r.json() : null; });
  }

  /* ------------------------------------------------------- the button */

  /* #1358: THE BUTTON, WHERE THERE IS A BAR TO PUT IT IN - AND WHERE
   * THERE IS NOT.
   *
   * glassPineCam lives in the Electron chrome's glass bar. The tablet
   * has no such bar: its shell is a WebView showing the station's panel
   * with the views welded on, and nothing in that page has ever heard
   * of this one. So showButton found nothing, did nothing, and the
   * camera could not be opened on the surface the operator actually
   * carries around.
   *
   * It builds its own rather than asking the panel to carry a button
   * for a device that is usually not there. Same rule as the chrome's:
   * absent until the link is live, gone when the camera goes.
   */
  function button() {
    var own = document.getElementById('glassPineCam');
    if (own) return own;
    own = document.getElementById('pineCamFlag');
    if (own) return own;
    if (!document.body) return null;
    own = document.createElement('button');
    own.id = 'pineCamFlag';
    own.type = 'button';
    own.className = 'pine-cam-flag';
    own.hidden = true;
    own.title = 'The Pine Cam is live - tap to watch it';
    own.innerHTML = '<i class="pine-cam-flag-dot"></i><span>CAM</span>';
    own.addEventListener('click', toggle);
    own.__pineCamWired = true;
    document.body.appendChild(own);
    return own;
  }

  function showButton(on) {
    var b = button();
    if (!b) return;
    if (b.hidden === !on) return;          /* no needless writes */
    b.hidden = !on;
    /* Say it arrived. A tab that simply appears is easy to miss on a
     * screen this busy. */
    if (on) {
      b.classList.add('pine-cam-new');
      setTimeout(function () {
        try { b.classList.remove('pine-cam-new'); } catch (e) {}
      }, 6000);
    }
  }

  /* ---------------------------------------------------------- the box */

  /* #1118: `key` and `def` let the ladder sheet keep its own place under
   * its own name; without them every draggable here would write over
   * the box's saved position. The original callers pass neither. */
  function place(el, key, def) {
    var at = null;
    try { at = JSON.parse(localStorage.getItem(key || KEY) || 'null'); }
    catch (e) { at = null; }
    /* Off-screen is a real possibility: the window may be smaller than it
     * was when this was saved. */
    var w = Math.max(240, Math.min(640, (at && at.w) || (def && def.w) || 360));
    var left = (at && typeof at.x === 'number') ? at.x
      : (def && typeof def.x === 'number') ? def.x
        : Math.max(12, window.innerWidth - w - 28);
    var top = (at && typeof at.y === 'number') ? at.y
      : (def && typeof def.y === 'number') ? def.y : 96;
    left = Math.min(Math.max(0, left), Math.max(0, window.innerWidth - 120));
    top = Math.min(Math.max(0, top), Math.max(0, window.innerHeight - 90));
    el.style.width = w + 'px';
    el.style.left = left + 'px';
    el.style.top = top + 'px';
  }

  function remember(el, key) {
    if (key === false) return;             /* #1118: a sheet that never remembers */
    try {
      localStorage.setItem(key || KEY, JSON.stringify({
        x: parseInt(el.style.left, 10) || 0,
        y: parseInt(el.style.top, 10) || 0,
        w: parseInt(el.style.width, 10) || 360
      }));
    } catch (e) { /* a forgotten position is not worth an error */ }
  }

  /* 2026-09-14: "tap the window and drag it around to reposition it."
   * This listened for mouse events only, so on the tablet a finger on
   * the box scrolled the page instead. Pointer events with capture cover
   * a finger and a mouse alike; presses on buttons are left to the
   * buttons; and a press that never moved more than eight pixels is
   * reported as a TAP through `onTap`, which is how the collapsed circle
   * opens back up. */
  function drag(el, handle, key, onTap) {
    var from = null;
    var moved = false;
    handle.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0 && ev.pointerType === 'mouse') return;
      if (ev.target && ev.target.closest && ev.target.closest('button, input, select, textarea, a')) return;
      from = {x: ev.clientX, y: ev.clientY, id: ev.pointerId,
        left: parseInt(el.style.left, 10) || 0,
        top: parseInt(el.style.top, 10) || 0};
      moved = false;
      try { handle.setPointerCapture(ev.pointerId); } catch (e) { /* older engine */ }
      ev.preventDefault();
    });
    handle.addEventListener('pointermove', function (ev) {
      if (!from || ev.pointerId !== from.id) return;
      var dx = ev.clientX - from.x, dy = ev.clientY - from.y;
      if (!moved && Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
      moved = true;
      el.style.left = Math.max(0, Math.min(window.innerWidth - 60, from.left + dx)) + 'px';
      el.style.top = Math.max(0, Math.min(window.innerHeight - 40, from.top + dy)) + 'px';
      if (el === box) nativeBoxSoon();     /* #1470: the surface follows the finger */
    });
    var drop = function (ev) {
      if (!from || (ev && ev.pointerId !== from.id)) return;
      try { handle.releasePointerCapture(from.id); } catch (e) { /* not held */ }
      if (moved) remember(el, key);
      else if (onTap) { try { onTap(ev); } catch (e) { /* a tap is a courtesy */ } }
      from = null;
    };
    handle.addEventListener('pointerup', drop);
    handle.addEventListener('pointercancel', drop);
  }

  function build() {
    if (box) return box;
    box = document.createElement('div');
    box.id = 'pineCamBox';
    box.className = 'pine-cam-box';
    box.innerHTML =
      '<div class="pine-cam-bar">'
      + '<b>PINE CAM</b>'
      + '<i id="pineCamWhy"></i>'
      /* 2026-09-14: record from the box itself, into the record location;
       * fold the box to a live circle; close. Carbon through pineIcon with
       * a word behind each, never an emoji. */
      + '<button type="button" class="pine-cam-fold pine-cam-hdr" id="pineCamHdr" '
      + 'aria-label="Hide the header" title="Fold the header away - double-tap the picture to bring it back">'
      + icon('c:arrow--up', 'Hide header', '^') + '</button>'
      + '<button type="button" class="pine-cam-rec" id="pineCamBoxRec" '
      + 'aria-label="Record" title="Record: mark the start, press again to end the clip and keep it in the record location">'
      + icon('c:recording--filled', 'Record', 'REC') + '</button>'
      + '<button type="button" class="pine-cam-fold" id="pineCamFold" '
      + 'aria-label="Collapse to a circle" title="Collapse the picture to a small live circle - tap the circle to open it again">'
      + icon('c:circle--filled', 'Collapse', 'o') + '</button>'
      + '<button type="button" class="pine-cam-x" '
      + 'aria-label="Close the camera view" title="Close the camera view">×</button>'
      + '</div>'
      + '<img id="pineCamImg" alt="The Pine Cam, live">'
      /* [cambattery] the camera's battery, over the picture's top-left */
      + '<div class="pine-cam-batt" id="pineCamBatt" hidden></div>'
      /* [tabrelay] the camera's road, over the picture's bottom-left */
      + '<div class="pine-cam-path" id="pineCamPath" hidden></div>';
    document.body.appendChild(box);
    place(box);
    /* The whole box is the handle; a tap on the folded circle unfolds it. */
    drag(box, box, null, function () {
      if (box.classList.contains('pine-cam-round')) { setRound(false); return; }
      pictureTapped(null);                 /* a double tap toggles the header */
    });
    box.querySelector('.pine-cam-x').addEventListener('click', function (ev) { ev.stopPropagation(); close(); });
    box.querySelector('#pineCamFold').addEventListener('click', function (ev) { ev.stopPropagation(); setRound(true); });
    box.querySelector('#pineCamHdr').addEventListener('click', function (ev) { ev.stopPropagation(); setBare(true); });
    box.querySelector('#pineCamBoxRec').addEventListener('click', function (ev) { ev.stopPropagation(); boxRecord(); });
    /* #1470: the first JPEG sets the picture's height, and only then is
     * there a rectangle to hand the surface; a resize or a drag moves it. */
    var img0 = box.querySelector('#pineCamImg');
    if (img0) {
      img0.addEventListener('load', function () { if (nativeOn) nativeBoxSoon(); else nativeStart(); });
      try {
        if (root.ResizeObserver) new ResizeObserver(function () { nativeBoxSoon(); }).observe(img0);
      } catch (e) { /* no observer: the load hook and the drag still send it */ }
    }
    root.addEventListener('resize', nativeBoxSoon);
    /* [pincrop] a HOLD on the page's own picture - the desktop, or the
     * tablet's JPEG road - opens the radial; the native surface catches
     * its own hold and calls PineCam.holdPicture in device pixels. A
     * right-click is the desktop's second road, like the SFX TV's. */
    wireHold(box);
    box.addEventListener('contextmenu', function (ev) {
      if (box.classList.contains('pine-cam-round')) return;
      ev.preventDefault();
      ev.stopPropagation();
      holdAt(ev.clientX, ev.clientY);
    });
    try { if (localStorage.getItem(ROUND_KEY) === '1') setRound(true); } catch (e) { /* stays open */ }
    return box;
  }

  /* 2026-09-14: "collapse the camera picture in picture into an icon that's
   * also able to be dragged around inside of a circle ... I want the stream
   * of the camera to still be showing across the circle." The same <img>
   * keeps painting at four a second; the CSS makes it a round 84px window
   * with the picture covering it. The choice is remembered. */
  var ROUND_KEY = 'pineCamRound';
  function setRound(on) {
    if (!box) return;
    box.classList.toggle('pine-cam-round', !!on);
    try { localStorage.setItem(ROUND_KEY, on ? '1' : '0'); } catch (e) { /* forgotten */ }
    if (!on) place(box);                   /* back to the remembered size */
    /* #1470: the circle is a CSS clip, which a SurfaceView cannot follow.
     * The round window stays on the JPEG road; the rectangle brings the
     * surface back. */
    if (on) nativeStop(); else nativeStart();
  }

  /* 2026-09-14: THE RECORD BUTTON ON THE BOX. "offer a recording button
   * that records footage ... and save it to the record location." The
   * link records continuously (#1356), so this marks a start, marks an
   * end, asks the station to cut that span, and then asks it to KEEP the
   * cut in the record location - the clips folder the folder icon opens,
   * which the desk carries to the export folder when that is switched
   * on. No Save As: the tablet has none, and the record location is the
   * point. */
  var boxRecFrom = 0;
  var boxRecTick = 0;
  function boxRecPaint() {
    var b = document.getElementById('pineCamBoxRec');
    if (!b) return;
    var why = document.getElementById('pineCamWhy');
    if (!boxRecFrom) { b.classList.remove('on'); return; }
    var sec = Math.max(0, Math.round(Date.now() / 1000 - boxRecFrom));
    b.classList.add('on');
    if (why) why.textContent = 'recording ' + Math.floor(sec / 60) + ':' + (sec % 60 < 10 ? '0' : '') + (sec % 60);
  }
  function boxRecord() {
    var why = document.getElementById('pineCamWhy');
    var tell = function (t) { if (why) why.textContent = String(t || ''); };
    if (!boxRecFrom) {
      boxRecFrom = Date.now() / 1000;
      boxRecPaint();
      if (!boxRecTick) boxRecTick = setInterval(boxRecPaint, 500);
      return;
    }
    var from = boxRecFrom, to = Date.now() / 1000;
    boxRecFrom = 0;
    if (boxRecTick) { clearInterval(boxRecTick); boxRecTick = 0; }
    boxRecPaint();
    if (to - from < 1) { tell('too short to cut'); return; }
    tell('cutting ' + Math.round(to - from) + 's...');
    Promise.resolve(post('/api/pinelink/cut', {from: from, to: to})).then(function (r) {
      if (!r || !r.ok) { tell((r && r.say) || 'the cut did not come back'); return; }
      tell('keeping it...');
      return Promise.resolve(post('/api/pinelink/keep', {name: r.name})).then(function (k) {
        if (!k || !k.ok) { tell((k && k.say) || 'the station kept only the cut'); return; }
        tell('kept: ' + (k.name || 'the clip'));
        readPrefs();
        setTimeout(function () { if (why && why.textContent.indexOf('kept:') === 0) why.textContent = live ? 'live' : ''; }, 8000);
      });
    }).catch(function () { tell('the station did not answer'); });
  }

  /* 2026-09-14: THE CACHE-BUSTER WORE THE TOKEN'S NAME. `?t=` is the
   * frame route's viewer-token parameter (#1354), so every request from
   * the desk read as a guest holding the token '1789...' and got 403 -
   * 'the camera is not being shared with you' - measured from the PC.
   * The tablet never saw it only because its loopback door needs no
   * token. The buster is `?c=` now, on both pictures. */
  /* [cam-mjpeg] "I want it also high FPS like the tablet": a page with no
     native surface (the desk) plays the door's multipart JPEG stream in the
     same <img>, once - it paints itself at the stream's rate. The JPEG poll
     stands in when the door is down or the stream fails (retried after 5 s). */
  var mjpegFailedAt = 0;
  function mjpegUrl() {
    if (nativeOn || !tsInfo) return '';
    var u = String(tsInfo.url || '');
    if (/\/live\.ts/.test(u)) return u.replace(/\/live\.ts.*$/, '/live.mjpg');
    try {
      var host = new URL(base() || root.location.href).hostname;
      return host ? 'http://' + host + ':' + tsInfo.port + '/live.mjpg' : '';
    } catch (e) { return ''; }
  }
  function mjpegStop(img) {
    if (img && img.__mjpeg) { img.__mjpeg = ''; try { img.removeAttribute('src'); } catch (e) { /* gone */ } }
  }
  function paintFrame() {
    var img = document.getElementById('pineCamImg');
    if (!img || !shown) return;
    var m = mjpegUrl();
    if (m && Date.now() - mjpegFailedAt > 5000) {
      if (img.__mjpeg !== m) {
        img.__mjpeg = m;
        img.onerror = function () { mjpegFailedAt = Date.now(); img.__mjpeg = ''; };
        img.src = m + '?c=' + Date.now();
      }
      return;                                /* the stream paints itself */
    }
    img.__mjpeg = '';
    /* A cache-buster, because the frame is one URL that keeps changing and
     * every layer between here and the disk would happily hold on to it. */
    img.src = base() + '/api/pinelink/frame.jpg?c=' + Date.now();
  }

  /* [cam-restore] the window's own state survives a reload: out or not, and
     expanded or bare. Written on every open, close and header toggle; read
     once, on the first live reading after the page starts. */
  var VIEW_KEY = 'pineCamView';
  var viewRestored = false;
  var viewRestoring = false;
  function viewSave() {
    if (viewRestoring) return;
    try { localStorage.setItem(VIEW_KEY, JSON.stringify({open: !!shown, bare: !!bare, at: Date.now()})); }
    catch (e) { /* private mode: it opens as it always did */ }
  }
  function viewRestore() {
    if (viewRestored || !live) return;
    viewRestored = true;
    var v = null;
    try { v = JSON.parse(localStorage.getItem(VIEW_KEY) || 'null'); } catch (e) { v = null; }
    if (!v || !v.open || shown) return;
    viewRestoring = true;
    try { open(); if (v.bare === false) setBare(false); }
    finally { viewRestoring = false; }
  }

  function open() {
    build();
    shown = true;
    box.hidden = false;
    vcrBox(true);                          /* [vcrfx] dot -> line -> picture */
    setBare(BARE_DEFAULT);                 /* just the window, until asked */
    paintFrame();
    if (!frameTimer) frameTimer = setInterval(paintFrame, FRAME_MS);
    nativeStart();                         /* #1470: the surface, where there is one */
    repaintPicture();                      /* #1118: the ladder's last rung is this box */
    viewSave();                            /* [cam-restore] */
  }

  function close() {
    cropRadialClose(false);                /* [pincrop] no menu over a closed box */
    cropDrawClose(false);
    nativeStop();                          /* #1470: before the box goes */
    shown = false;
    mjpegStop(document.getElementById('pineCamImg'));   /* [cam-mjpeg] the stream goes with the box */
    if (box) vcrBox(false);                /* [vcrfx] picture -> line -> dot, then hidden */
    if (frameTimer) { clearInterval(frameTimer); frameTimer = 0; }
    repaintPicture();
    viewSave();                            /* [cam-restore] */
  }

  function toggle() { if (shown) { close(); } else { open(); } }

  /* [vcrfx] THE BOX COMES ON LIKE THE SFX TV. PineVcr.set is a state
   * machine - the newest wish wins and an open during a close starts from
   * the dot again - so the box is only ever hidden by an out that nobody
   * overtook. Without pine-vcr.js on the page it is hidden at once. */
  function vcrBox(on) {
    if (!box) return;
    var V = root.PineVcr;
    if (!V || typeof V.set !== 'function') { box.hidden = !on; return; }
    V.set(box, on, {
      show: function (el) { el.hidden = false; },
      hide: function (el) { if (!shown) el.hidden = true; }
    });
  }

  /* ------------------------------------------------ the native picture */

  function nativeBridge() {
    try {
      var b = root.pineDesktop;
      return (b && typeof b.pineCam === 'function') ? b : null;
    } catch (e) { return null; }
  }

  function nativeAsk(verb, arg) {
    var b = nativeBridge();
    if (!b) return Promise.resolve(null);
    try { return Promise.resolve(b.pineCam(verb, arg || {})); }
    catch (e) { return Promise.resolve(null); }
  }

  /* The picture's rectangle in DEVICE pixels - the SurfaceView is laid
   * out by Android, not by CSS. NOT devicePixelRatio: on this tablet that
   * reads 1.25 while the glass is 1340 px across a 1154 px viewport, so
   * the true factor is 1.161 and the ratio put the surface 41 px right
   * and 16 px low, clamped into the corner (measured 2026-09-27; the same
   * trap the tap notes record). `screen.width` is the glass in CSS px at
   * scale 1, so glass = screen.width x ratio, and the factor is glass
   * over viewport - one for each axis. */
  function camScale() {
    var d = Number(root.devicePixelRatio) || 1;
    var sx = d, sy = d;
    try {
      var gw = Number(root.screen && root.screen.width) * d;
      var gh = Number(root.screen && root.screen.height) * d;
      if (gw > 0 && root.innerWidth > 0) sx = gw / root.innerWidth;
      if (gh > 0 && root.innerHeight > 0) sy = gh / root.innerHeight;
      if (!(sx > 0.2 && sx < 8)) sx = d;
      if (!(sy > 0.2 && sy < 8)) sy = d;
    } catch (e) { sx = d; sy = d; }
    return {x: sx, y: sy};
  }

  function camRect() {
    var img = document.getElementById('pineCamImg');
    if (!img || !box || box.hidden) return null;
    var r = img.getBoundingClientRect();
    if (!(r.width > 0) || !(r.height > 0)) return null;
    var s = camScale();
    return {x: Math.round(r.left * s.x), y: Math.round(r.top * s.y),
            w: Math.round(r.width * s.x), h: Math.round(r.height * s.y)};
  }

  function nativeWanted() {
    return !!(nativeBridge() && tsInfo && shown && box
              && !box.classList.contains('pine-cam-round'));
  }

  function setFrameTimer(ms) {
    if (frameTimer) { clearInterval(frameTimer); frameTimer = 0; }
    if (shown) frameTimer = setInterval(paintFrame, ms);
  }

  /* While the surface is up the poster underneath is blanked, not just
   * covered: the two are laid out by different engines, and any moment
   * they disagree - a drag in flight, a scale off by a few px - would
   * otherwise show the camera twice. It comes back for a sheet (`menu`)
   * and when the surface goes. The <img> keeps loading at one a second
   * so what comes back is recent. */
  function posterShown(on) {
    var img = document.getElementById('pineCamImg');
    if (!img) return;
    img.style.opacity = on ? '' : '0';
  }

  /* The header, folded away or back. The picture moves up or down by one
   * bar, so the surface is told again. */
  function setBare(on) {
    if (!box) return;
    bare = !!on;
    box.classList.toggle('pine-cam-bare', bare);
    battPlace();                           /* [cambattery] */
    var b = document.getElementById('pineCamHdr');
    if (b) b.setAttribute('aria-expanded', bare ? 'false' : 'true');
    lastBoxKey = '';
    nativeBoxSoon();
    if (shown) viewSave();                 /* [cam-restore] */
  }

  /* One tap or two. A second tap inside 350 ms is a double tap and toggles
   * the header; a lone tap does `single` once the window has passed. Both
   * the native surface (tapPicture) and the page's own box (the drag
   * handle's tap) arrive here, so the two roads behave the same. */
  function pictureTapped(single) {
    var now = Date.now();
    if (now < holdMute) return;    /* [pincrop] that press was a hold */
    if (tapAt && now - tapAt < 350) {
      tapAt = 0;
      if (tapTimer) { clearTimeout(tapTimer); tapTimer = 0; }
      setBare(!bare);
      return;
    }
    tapAt = now;
    if (tapTimer) clearTimeout(tapTimer);
    tapTimer = setTimeout(function () {
      tapTimer = 0;
      tapAt = 0;
      if (single) { try { single(); } catch (e) { /* a tap is a courtesy */ } }
    }, 350);
  }

  function nativeStart() {
    if (nativeOn || nativeAsked || !nativeWanted()) return;
    var r = camRect();
    if (!r) return;                        /* the first JPEG sets the height; the load hook retries */
    nativeAsked = true;
    lastBoxKey = '';
    nativeAsk('on', {port: tsInfo.port, path: tsInfo.path, url: tsInfo.url,
                     x: r.x, y: r.y, w: r.w, h: r.h}).then(function (st) {
      nativeAsked = false;
      if (!st || st.ok === false) return;  /* the JPEG road stands */
      if (!shown || !nativeWanted()) { nativeAsk('off'); return; }
      nativeOn = true;
      nativeFull = !!st.full;
      if (box) box.classList.add('pine-cam-native');
      setFrameTimer(NATIVE_POSTER_MS);
      posterShown(false);
      nativeBox();                         /* the box may have moved while asked */
      battNativeKey = '';                  /* [cambattery] a new surface: tell it again */
      paintBatteryNative(battModel(batt));
    }, function () { nativeAsked = false; });
  }

  function nativeStop() {
    nativeFull = false;
    posterShown(true);
    if (box) box.classList.remove('pine-cam-native', 'pine-cam-sliding');
    if (!nativeOn && !nativeAsked) return;
    nativeOn = false;
    lastBoxKey = '';
    nativeAsk('off');
    if (shown) setFrameTimer(FRAME_MS);
  }

  /* Native -> page: the finger is sliding the surface. The frame this page
   * draws around the picture would otherwise stand where the box WAS until
   * the release - a ghost of the window - so it goes with the drag and
   * comes back where the surface settles (wallBoxChanged lands first). */
  function dragPicture(on) {
    if (!box) return;
    box.classList.toggle('pine-cam-sliding', !!on);
  }

  function nativeBox() {
    if (!nativeOn || nativeFull) return;
    var r = camRect();
    if (!r) return;
    var key = r.x + ',' + r.y + ',' + r.w + ',' + r.h;
    if (key === lastBoxKey) return;        /* the poster's load fires every second */
    lastBoxKey = key;
    nativeAsk('box', r);
  }

  function nativeBoxSoon() {
    if (!nativeOn || boxMoveRaf) return;
    boxMoveRaf = requestAnimationFrame(function () { boxMoveRaf = 0; nativeBox(); });
  }

  /* Sheets cannot paint over a SurfaceView, so while one is up the
   * surface is retired (`menu`) and the poster underneath, one a second,
   * stands in; `free` puts it back. Same contract as the SFX set's wall. */
  function nativeMenu(on) {
    if (!nativeOn) return;
    posterShown(!!on);
    nativeAsk(on ? 'menu' : 'free');
  }

  /* Native -> page. A tap on the picture toggles full screen; a drag on
   * the surface moves the box here to match, so the two never disagree
   * about where the camera is. Both arrive in device pixels. */
  function tapPicture() {
    if (!nativeOn) return;
    pictureTapped(toggleFull);
  }

  function toggleFull() {
    if (!nativeOn) return;
    if (nativeFull) {
      nativeFull = false;
      lastBoxKey = '';
      nativeAsk('window').then(function () { nativeBox(); });
    } else {
      nativeFull = true;
      nativeAsk('full');
    }
  }

  function wallBoxChanged(x, y, w, h) {
    if (!nativeOn || nativeFull || !box) return;
    var img = document.getElementById('pineCamImg');
    if (!img) return;
    var s = camScale();
    var br = box.getBoundingClientRect();
    var ir = img.getBoundingClientRect();
    var left = Number(x) / s.x - (ir.left - br.left);
    var top = Number(y) / s.y - (ir.top - br.top);
    box.style.left = Math.max(0, Math.round(left)) + 'px';
    box.style.top = Math.max(0, Math.round(top)) + 'px';
    if (Number(w) > 0) box.style.width = Math.max(240, Math.round(Number(w) / s.x)) + 'px';
    lastBoxKey = [x, y, w, h].map(function (v) { return Math.round(Number(v) || 0); }).join(',');
    remember(box);
  }

  /* The lock screen and a hidden document must cover the camera too, and
   * no z-index reaches a SurfaceView - so it is hidden by name. */
  function nativeCover() {
    if (!nativeOn) return;
    var locked = !!(document.body && document.body.classList.contains('pine-locked'));
    var hidden = document.visibilityState === 'hidden';
    nativeAsk((locked || hidden) ? 'hide' : 'show');
  }

  /* ============================================================ [pincrop]
   * THE CROP. "tap and drag to draw a crop window that basically reduces
   * the webcam to be that size of window Cropping out everything around
   * it ... if I tap and hold, it shows a radio pod menu and from there
   * there's a crop option ... and then it allows me to tap and draw a box
   * that determines my crop area for the camera."
   *
   * The box is CUT AT THE CAMERA - tools/pinelink.py re-encodes with the
   * crop, so the TS door, the HLS, the stills, the clips and anything
   * leaving full screen all carry only the box; nothing here is a mask.
   * This page owns three things:
   *
   *   THE HOLD. 550 ms without moving, on the picture. The desktop's is
   *   wired in build() (wireHold, plus right-click); the tablet's native
   *   surface swallows touches, so PineCamWall catches the hold itself
   *   and calls PineCam.holdPicture(x, y) in DEVICE pixels - divided here
   *   by camScale(), the true glass factor, never devicePixelRatio.
   *
   *   THE RADIAL, in the SFX TV's shape (its classes are this page's own,
   *   pine-cam-radial-*, so the two skins can drift apart on purpose):
   *   Crop draws a new box, Adjust redraws from the current one, Reset
   *   puts the whole picture back. The shade closes it; so do Escape and
   *   the kiosk's BACK, through PineDismiss.
   *
   *   THE DRAW. A full-screen overlay over /api/pinelink/crop/frame.jpg -
   *   the WHOLE frame, 2 fps, house-only - because a new box must be
   *   aimed at everything the camera sees, not at the already-cropped
   *   stream. A drag is the rubber band; the box is kept as FRACTIONS of
   *   the picture, so a resize or the next frame repaints it in place.
   *   Confirm posts the fractions and the supervisor restarts only its
   *   ffmpeg (a few seconds, said in so many words); Cancel and BACK
   *   leave the crop as it was. While the overlay or the radial is up the
   *   native surface is retired (nativeMenu), so the same HTML works the
   *   desktop and the tablet - and the surface comes back cropped.
   * ==================================================================== */

  function cropAsk() {
    return Promise.resolve(ask('/api/pinelink/crop')).then(function (v) {
      if (v) cropView = v;
      return v;
    }, function () { return null; });
  }

  function cropSay(text) {
    var why = document.getElementById('pineCamWhy');
    if (why) why.textContent = String(text || '');
  }

  /* After an apply: relay the station's sentence - "starting again with
   * the new box", then "cropped: only the box goes out" - until settled. */
  function cropFollow() {
    var tries = 10;
    if (cropWatch) { clearTimeout(cropWatch); cropWatch = 0; }
    (function again() {
      cropWatch = setTimeout(function () {
        cropWatch = 0;
        cropAsk().then(function (v) {
          if (!v) return;
          cropSay(v.say || '');
          if (v.pending && (tries -= 1) > 0) again();
        });
      }, 2000);
    }());
  }

  /* The page road's hold: a press that stays put for HOLD_MS. A press on
   * a control is the control's; a move is a drag of the box. */
  function wireHold(el) {
    var held = null;
    var timer = 0;
    var forget = function () {
      if (timer) { clearTimeout(timer); timer = 0; }
      held = null;
    };
    el.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0 && ev.pointerType === 'mouse') return;
      if (ev.target && ev.target.closest && ev.target.closest('button, input, select, textarea, a')) return;
      if (el.classList.contains('pine-cam-round')) return;
      held = {x: ev.clientX || 0, y: ev.clientY || 0};
      timer = setTimeout(function () {
        timer = 0;
        var at = held;
        held = null;
        holdMute = Date.now() + 900;   /* the release is not a tap */
        holdAt(at.x, at.y);
      }, HOLD_MS);
    });
    el.addEventListener('pointermove', function (ev) {
      if (!held) return;
      if (Math.abs((ev.clientX || 0) - held.x) > HOLD_SLOP
          || Math.abs((ev.clientY || 0) - held.y) > HOLD_SLOP) forget();
    });
    el.addEventListener('pointerup', forget);
    el.addEventListener('pointercancel', forget);
  }

  /* Native -> page: the surface's hold, in device pixels (the same trap
   * as camRect, the other way: divide by the true factor). */
  function holdPicture(x, y) {
    var s = camScale();
    holdAt((Number(x) || 0) / s.x, (Number(y) || 0) / s.y);
  }

  function holdAt(cx, cy) {
    if (!shown) return;                  /* no picture, no crop menu */
    cropRadial(cx, cy);
  }

  function cropRadialClose(free) {
    var shade = cropShade;
    cropShade = null;
    if (cropUnwatch) { try { cropUnwatch(); } catch (e) { } cropUnwatch = null; }
    if (shade && shade.parentNode) shade.parentNode.removeChild(shade);
    if (free !== false && !cropEl) nativeMenu(false);
  }

  function cropRadial(cx, cy) {
    cropRadialClose(false);
    nativeMenu(true);                    /* HTML must own the glass while a menu is up */
    var shade = document.createElement('div');
    shade.className = 'pine-cam-radial-shade';
    var menu = document.createElement('div');
    menu.className = 'pine-cam-radial';
    menu.setAttribute('role', 'menu');
    var W = root.innerWidth || 800;
    var H = root.innerHeight || 600;
    menu.style.left = Math.max(112, Math.min(W - 112, Number(cx) || W / 2)) + 'px';
    menu.style.top = Math.max(112, Math.min(H - 112, Number(cy) || H / 2)) + 'px';
    var note = document.createElement('span');
    note.className = 'pine-cam-radial-note';
    note.textContent = 'PINE CAM';
    menu.appendChild(note);
    var item = function (label, ref, cls, word, go) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pine-cam-radial-item ' + cls;
      b.title = label;
      b.setAttribute('aria-label', label);
      b.innerHTML = icon(ref, label, word);
      b.addEventListener('click', function (ev) { ev.stopPropagation(); go(); });
      menu.appendChild(b);
      return b;
    };
    item('Crop: draw the box the stream keeps', 'c:cut', 'crop', 'crop', function () {
      cropRadialClose(false);
      cropDrawOpen(false);
    });
    var adj = item('Adjust the crop: redraw it from the whole picture', 'c:edit', 'adjust', 'adjust', function () {
      cropRadialClose(false);
      cropDrawOpen(true);
    });
    var res = item('Reset: the whole picture goes out again', 'c:maximize', 'reset', 'reset', function () {
      if (!(cropView && (cropView.want || cropView.applied))) {
        note.textContent = 'no crop is set - the whole picture already goes out';
        return;
      }
      note.textContent = 'resetting…';
      Promise.resolve(post('/api/pinelink/crop', {reset: true})).then(function (r) {
        cropRadialClose();
        cropSay((r && r.say) || 'the station did not answer');
        if (r && r.ok) cropFollow();
      }, function () {
        cropRadialClose();
        cropSay('the station did not answer');
      });
    });
    adj.classList.add('off');
    res.classList.add('off');
    shade.appendChild(menu);
    shade.addEventListener('click', function (ev) {
      if (ev.target === shade) cropRadialClose();
    });
    document.body.appendChild(shade);
    cropShade = shade;
    /* Escape and the kiosk's BACK close it - its own ways out, never the
     * surface underneath (#1450). */
    if (root.PineDismiss && root.PineDismiss.watch) {
      cropUnwatch = root.PineDismiss.watch(shade, function () { cropRadialClose(); });
    }
    cropAsk().then(function (v) {
      if (!v || cropShade !== shade) return;
      var have = !!(v.want || v.applied);
      adj.classList.toggle('off', !have);
      res.classList.toggle('off', !have);
      if (v.say) note.textContent = String(v.say);
    });
  }

  function cropDrawClose(free) {
    var el = cropEl;
    cropEl = null;
    if (cropRawTimer) { clearInterval(cropRawTimer); cropRawTimer = 0; }
    if (cropDrawUnwatch) { try { cropDrawUnwatch(); } catch (e) { } cropDrawUnwatch = null; }
    if (el) {
      if (el.__pincropResize) root.removeEventListener('resize', el.__pincropResize);
      if (el.parentNode) el.parentNode.removeChild(el);
    }
    if (free !== false && !cropShade) nativeMenu(false);
  }

  function cropDrawOpen(adjust) {
    cropDrawClose(false);
    nativeMenu(true);
    var el = document.createElement('div');
    el.id = 'pineCamCrop';
    el.className = 'pine-cam-crop';
    el.innerHTML =
      '<div class="pine-cam-crop-stage">'
      + '<img class="pine-cam-crop-img" alt="The whole Pine Cam picture" draggable="false">'
      + '<div class="pine-cam-crop-band" hidden></div>'
      + '</div>'
      + '<div class="pine-cam-crop-bar">'
      + '<b>CROP THE PINE CAM</b>'
      + '<span class="pine-cam-crop-note">this is the WHOLE picture - drag a box over '
      + 'what the stream may show; everything outside it is cut at the camera</span>'
      + '<button type="button" class="pine-cam-crop-ok" disabled '
      + 'title="Keep only the box: every road shows just this from now on">'
      + icon('c:checkmark--filled', '', '') + '<span>Keep only the box</span></button>'
      + '<button type="button" class="pine-cam-crop-no" '
      + 'title="Leave the crop exactly as it is">'
      + icon('c:close--filled', '', '') + '<span>Cancel</span></button>'
      + '</div>';
    document.body.appendChild(el);
    cropEl = el;
    var stage = el.querySelector('.pine-cam-crop-stage');
    var img = el.querySelector('.pine-cam-crop-img');
    var band = el.querySelector('.pine-cam-crop-band');
    var tell = el.querySelector('.pine-cam-crop-note');
    var keep = el.querySelector('.pine-cam-crop-ok');
    var frac = null;                     /* the drawn box, fractions of the picture */
    var pen = null;                      /* the drag in flight, client px */

    /* Where the picture actually is: the img sits contain-fit in the
     * stage, so the letterbox is derived from its natural size. Before
     * the first frame the camera's own 848x480 stands in. */
    function pictureRect() {
      var r = stage.getBoundingClientRect();
      var nw = img.naturalWidth || 848;
      var nh = img.naturalHeight || 480;
      var k = Math.min(r.width / Math.max(1, nw), r.height / Math.max(1, nh));
      var w = Math.max(1, nw * k);
      var h = Math.max(1, nh * k);
      return {x: r.left + (r.width - w) / 2, y: r.top + (r.height - h) / 2, w: w, h: h};
    }

    function paintBand(b) {
      if (!b) {
        band.hidden = true;
        keep.disabled = true;
        return;
      }
      var s = stage.getBoundingClientRect();
      band.hidden = false;
      band.style.left = Math.round(b.x - s.left) + 'px';
      band.style.top = Math.round(b.y - s.top) + 'px';
      band.style.width = Math.round(b.w) + 'px';
      band.style.height = Math.round(b.h) + 'px';
      keep.disabled = false;
    }

    /* The committed box is FRACTIONS, so the next frame, a rotation or a
     * resize repaints it on the same part of the picture. */
    function bandFromFrac() {
      if (pen) return;                   /* a drag in flight owns the band */
      if (!frac) { paintBand(null); return; }
      var p = pictureRect();
      paintBand({x: p.x + frac.x * p.w, y: p.y + frac.y * p.h,
        w: frac.w * p.w, h: frac.h * p.h});
    }
    el.__pincropResize = bandFromFrac;
    root.addEventListener('resize', bandFromFrac);

    function pin(ev, p) {
      return {x: Math.max(p.x, Math.min(p.x + p.w, Number(ev.clientX) || 0)),
        y: Math.max(p.y, Math.min(p.y + p.h, Number(ev.clientY) || 0))};
    }
    stage.addEventListener('pointerdown', function (ev) {
      if (ev.button !== 0 && ev.pointerType === 'mouse') return;
      var at = pin(ev, pictureRect());
      pen = {id: ev.pointerId, x: at.x, y: at.y};
      paintBand({x: at.x, y: at.y, w: 0, h: 0});
      keep.disabled = true;
      try { stage.setPointerCapture(ev.pointerId); } catch (e) { /* older engine */ }
      ev.preventDefault();
    });
    stage.addEventListener('pointermove', function (ev) {
      if (!pen || ev.pointerId !== pen.id) return;
      var at = pin(ev, pictureRect());
      paintBand({x: Math.min(pen.x, at.x), y: Math.min(pen.y, at.y),
        w: Math.abs(at.x - pen.x), h: Math.abs(at.y - pen.y)});
      keep.disabled = true;
      ev.preventDefault();
    });
    stage.addEventListener('pointerup', function (ev) {
      if (!pen || ev.pointerId !== pen.id) return;
      try { stage.releasePointerCapture(pen.id); } catch (e) { /* not held */ }
      var p = pictureRect();
      var at = pin(ev, p);
      var b = {x: Math.min(pen.x, at.x), y: Math.min(pen.y, at.y),
        w: Math.abs(at.x - pen.x), h: Math.abs(at.y - pen.y)};
      pen = null;
      if (b.w < 6 || b.h < 6) {
        frac = null;
        paintBand(null);
        tell.textContent = 'a tap is not a box - drag corner to corner over what may be seen';
        return;
      }
      frac = {x: (b.x - p.x) / p.w, y: (b.y - p.y) / p.h,
        w: b.w / p.w, h: b.h / p.h};
      bandFromFrac();
      tell.textContent = Math.round(frac.w * 100) + '% × '
        + Math.round(frac.h * 100)
        + '% of the picture - press "Keep only the box", or drag again';
    });
    stage.addEventListener('pointercancel', function () { pen = null; bandFromFrac(); });

    keep.addEventListener('click', function () {
      if (!frac) return;
      keep.disabled = true;
      tell.textContent = 'sending the box to the camera…';
      Promise.resolve(post('/api/pinelink/crop', {crop: frac})).then(function (r) {
        if (!r) { keep.disabled = false; tell.textContent = 'the station did not answer'; return; }
        if (!r.ok) {
          /* Refused with a sentence - a slip of a box, a station that
           * cannot write - and the overlay stays for another drag. */
          keep.disabled = false;
          tell.textContent = String(r.say || 'the station did not keep it');
          return;
        }
        cropDrawClose();
        cropSay(r.say || 'cropped - the camera starts again with only the box');
        cropFollow();
      }, function () {
        keep.disabled = false;
        tell.textContent = 'the station did not answer';
      });
    });
    el.querySelector('.pine-cam-crop-no').addEventListener('click', function () {
      cropDrawClose();
    });

    /* Adjusting: the box being kept is drawn first, so "adjust" reads as
     * move-this, not start-from-nothing. */
    function primeAdjust() {
      if (frac || pen || cropEl !== el) return;
      var b = cropView && (cropView.want || cropView.applied);
      if (b && typeof b.x === 'number') {
        frac = {x: b.x, y: b.y, w: b.w, h: b.h};
        bandFromFrac();
        tell.textContent = 'this is the box being kept - drag a new one, '
          + 'keep this one, or Cancel';
      }
    }

    var seen = false;
    img.addEventListener('load', function () {
      if (!seen) {
        seen = true;
        if (adjust) primeAdjust();
      }
      bandFromFrac();                    /* the letterbox moves with the frame size */
    });
    img.addEventListener('error', function () {
      tell.textContent = 'the camera is not sending the whole picture right '
        + 'now - it joins again in a moment';
    });
    function paintRaw() {
      img.src = base() + '/api/pinelink/crop/frame.jpg?c=' + Date.now();
    }
    paintRaw();
    cropRawTimer = setInterval(paintRaw, CROP_RAW_MS);
    if (adjust) cropAsk().then(function () { primeAdjust(); });

    /* Cancel is on the bar; Escape and BACK are PineDismiss's - the
     * overlay covers everything, so an outside tap cannot exist. */
    if (root.PineDismiss && root.PineDismiss.watch) {
      cropDrawUnwatch = root.PineDismiss.watch(el, function () { cropDrawClose(); });
    }
  }

  /* ---------------------------------------------------------- the ask */

  /* [cambattery] THE CAMERA'S BATTERY, TOP-LEFT OF EVERY PICTURE.
   *
   * "display a battery meter indicating the battery amount in the top left
   * corner of the pine cam ... so I can see how much battery's in the
   * camera at all times and know how long I have left in the stream."
   *
   * The station asks the camera (Novatek cmd 3019) every 45 s while the
   * link is live and hands the reading on as /api/pinelink/state
   * `battery`. The camera reports a LEVEL - full, half, low, last bar,
   * empty, or charging - never a percentage, so the meter fills bars of
   * four and says the word; the time left appears only once the station
   * has watched a whole level go by, and is never guessed before that.
   * Amber at low (~30%), red on the last bar (~15%), a gentle pulse at
   * empty (10% and under). Older than three minutes it greys and says
   * "stale". The title carries the exact reading and its age.
   *
   * Three pictures carry it: the box (an element over the <img>'s top-
   * left), the card's pip on the desktop, and the tablet's NATIVE surface
   * - which no page element can paint over (the media-overlay SurfaceView
   * is composited ABOVE the WebView), so the same reading is handed to
   * the kiosk as pineCam('battery', ...) and PineCamWall draws it in the
   * surface's own top-left. A kiosk without the verb answers "no such
   * pineCam verb" and nothing else happens. Carbon has no battery glyph
   * in the vendored set, so the gauge is drawn (like the signal bars) and
   * charging wears c:lightning. */
  var BATT_STALE_S = 180;
  var batt = null;             /* the last reading, stamped with this page's clock */
  var battNativeKey = '';

  function battAge(b) {
    if (!b || !b.ok) return Infinity;
    var since = b._got ? Math.max(0, (Date.now() - b._got) / 1000) : 0;
    return Number(b.age_s || 0) + since;
  }

  function battAgeSay(s) {
    if (!isFinite(s)) return 'never';
    if (s < 90) return Math.round(s) + ' s';
    if (s < 5400) return Math.round(s / 60) + ' min';
    return (s / 3600).toFixed(1) + ' h';
  }

  function battModel(b) {
    if (!b || !b.ok) return null;
    var age = battAge(b);
    var stale = age > BATT_STALE_S;
    /* [cambattery2] TIME LEFT LEADS. "Instead of saying last bar, I would
     * like a time estimate of how much time is left in the battery." The
     * station words it (`label`); the level word is in the title. */
    var dark = !!b.dark;
    var text = String(b.label || (b.charging ? 'charging' : (b.word || '?')));
    if (stale && !dark) text += ' · stale';
    /* [camcharge-icon] "whenever it's charging, just show the logo for charging,
       don't show the text" - the bolt alone (the title still says it) */
    if (b.charging && !stale && !dark) text = '';
    var title = String(b.what || b.say || 'Pine Cam battery')
      + '. Read ' + battAgeSay(age) + ' ago'
      + (stale ? ' - STALE: the camera has not answered since' + (b.error ? ' (' + b.error + ')' : '') : '')
      + '.';
    return {text: text, title: title,
            bars: b.charging ? -1 : Math.max(0, Math.min(4, Number(b.bars) || 0)),
            tone: (stale || dark) ? 'stale' : String(b.tone || 'ok'),   /* [cambattery2] */
            pulse: !!b.pulse && !stale && !dark, stale: stale || dark,
            charging: !!b.charging, dark: dark};
  }

  function battHtml(m) {
    var cells = '';
    for (var i = 0; i < 4; i++) cells += '<i' + (i < m.bars ? ' class="on"' : '') + '></i>';
    return '<span class="pine-cam-batt-cell" aria-hidden="true">'
      + (m.charging ? icon('c:lightning', 'Charging', '') : cells) + '</span>'
      + '<span class="pine-cam-batt-text">' + esc(m.text) + '</span>';
  }

  function battPaintInto(el, m) {
    if (!el) return;
    if (!m) { el.hidden = true; return; }
    var key = m.text + '|' + m.bars + '|' + m.tone + '|' + m.pulse;
    if (el.__battKey !== key) {
      el.__battKey = key;
      el.innerHTML = battHtml(m);
      el.className = 'pine-cam-batt pine-cam-batt--' + m.tone
        + (m.pulse ? ' pine-cam-batt--pulse' : '')
        + (m.charging ? ' pine-cam-batt--charging' : '');
    }
    el.title = m.title;
    el.setAttribute('aria-label', m.title);
    el.hidden = false;
  }

  /* The picture's top-left moves when the header folds; the meter goes
   * with it. */
  function battPlace() {
    var el = document.getElementById('pineCamBatt');
    var img = document.getElementById('pineCamImg');
    if (!el || !img) return;
    el.style.left = (img.offsetLeft + 6) + 'px';
    el.style.top = (img.offsetTop + 6) + 'px';
  }

  /* [cambattery2] THE DESK'S ROW, AND THE CARD WHEN THE CAMERA GOES DARK.
   * The box closes when the link goes (#1387: no still of a gone camera),
   * so a flat battery is said where it can still be seen: the row reads
   * it with the last estimate and its age, and one card says it on the
   * poll that first sees it (never on a page load onto an old one). */
  var battDarkSeen = null;

  function battRowSay(b) {
    if (!b || !b.ok) return '—';
    if (b.dark) {
      return 'camera went dark – battery likely flat'
        + (b.dark_was ? ' · was ' + b.dark_was : '')
        + ', ' + battAgeSay(Number(b.dark_age_s || 0)) + ' ago';
    }
    var age = battAge(b);
    return String(b.label || b.word || '')
      + (b.charging ? '' : ' (' + String(b.word || '') + ')')
      + (age > BATT_STALE_S ? ' · stale, read ' + battAgeSay(age) + ' ago' : '');
  }

  function battDarkTell(b) {
    var at = (b && b.dark) ? Number(b.dark_at || 0) : 0;
    if (battDarkSeen === null) { battDarkSeen = at; return; }
    if (!at) { battDarkSeen = 0; return; }
    if (at === battDarkSeen) return;
    battDarkSeen = at;
    if (!document.body) return;
    hideToast();
    toast = document.createElement('div');
    toast.id = 'pineCamToast';
    toast.className = 'pine-cam-toast pine-cam-toast--dark';
    toast.setAttribute('role', 'status');
    toast.title = String(b.what || '');
    toast.innerHTML =
      '<i class="pine-cam-flag-dot"></i>'
      + '<div class="pine-cam-toast-text"><b>The Pine Cam went dark</b><span>'
      + 'battery likely flat' + (b.dark_was ? ' · the last estimate was ' + esc(b.dark_was) : '')
      + '</span></div>'
      + '<button type="button" class="pine-cam-x" aria-label="Dismiss" title="Dismiss">×</button>';
    toast.addEventListener('click', function (ev) { ev.stopPropagation(); hideToast(); });
    document.body.appendChild(toast);
    toastTimer = setTimeout(hideToast, TOAST_MS);
  }

  function paintBatteryNative(m) {
    if (!nativeOn) return;
    var arg = m ? {on: true, text: m.text, bars: m.bars, tone: m.tone,
                   pulse: m.pulse, stale: m.stale, charging: m.charging}
                : {on: false};
    var key = JSON.stringify(arg);
    if (key === battNativeKey) return;
    battNativeKey = key;
    nativeAsk('battery', arg);
  }

  function paintBattery(b, isLive) {
    if (b && b.ok && !b._got) b._got = Date.now();
    batt = b || null;
    /* [cambattery2] a camera that went dark keeps its greyed meter */
    var m = (isLive === false && !(batt && batt.dark)) ? null : battModel(batt);
    battDarkTell(batt);
    battPaintInto(document.getElementById('pineCamBatt'), m);
    battPlace();
    if (pip) {
      var pe = pip.querySelector('.pine-cam-batt');
      if (!pe && m) { pe = document.createElement('div'); pip.appendChild(pe); }
      battPaintInto(pe, m);
    }
    paintBatteryNative(m);
    return m;
  }

  function look() {
    Promise.resolve(ask('/api/pinelink/state')).then(function (got) {
      var was = live;
      /* `fresh` is the supervisor's own heartbeat: a state file is a file,
       * and a stale one claiming "live" is exactly the lie this has to
       * avoid. Both, or it is not there. */
      live = !!(got && got.state === 'live' && got.fresh);
      if (live && !viewRestored) setTimeout(viewRestore, 0);   /* [cam-restore] */
      cropOn = !!(got && got.crop && got.crop.on);    /* [pincrop] */
      pathPaint(got);                                 /* [tabrelay] */
      showButton(live);
      /* #1470: the supervisor's TS door, when it is up. `ok` is its own
       * heartbeat (a datagram in the last five seconds); a door that has
       * gone quiet takes the surface down and the JPEG road stands in. */
      tsInfo = (live && got && got.ts && got.ts.ok && got.ts.port) ? got.ts : null;
      if (shown) {
        if (tsInfo) nativeStart(); else nativeStop();
      }
      if (nativeOn) {
        nativeAsk('state').then(function (st) {
          var why = document.getElementById('pineCamWhy');
          if (!st || !why || !live || boxRecFrom) return;
          if (st.on === false) { nativeOn = false; lastBoxKey = ''; nativeStart(); return; }
          var lag = Number(st.lag_ms || 0);
          why.textContent = 'live · native' + (cropOn ? ' · cropped' : '')   /* [pincrop] */
            + (lag > 0 ? ' · ' + (lag / 1000).toFixed(1) + 's' : '')
            + (Number(st.reconnects) ? ' · ' + st.reconnects + ' rejoin' : '');
        });
      }
      /* #1118: THE CARD IN THE MIDDLE OF THE TABLET'S SCREEN.
       *
       * Two things put it up: the link coming live (false -> true, and
       * only after the first answer, or a page opened onto an already
       * live camera would greet every reload with it), and the operator
       * pressing the radio icon on the desktop, which the station stamps
       * as `announce_at`. The stamp is remembered from the first answer
       * so an old one cannot fire on load - the tablet reboots more often
       * than the camera is switched on.
       *
       * The two are ordered on purpose: a fresh announce says 'being
       * switched on' when the camera is not there yet, and the tap on
       * that card asks for the box the moment `live` turns - which is
       * the third branch below, and it outranks a second card. */
      var ann = Number((got && got.announce_at) || 0) || 0;
      var waiting = toastWaitUntil > Date.now();
      if (!polled) {
        announceSeen = ann;
      } else if (ann > announceSeen) {
        announceSeen = ann;
        showToast(live);
      } else if (!was && live && !waiting) {
        showToast(true);
      }
      if (got) polled = true;
      if (live && waiting) { toastWaitUntil = 0; hideToast(); open(); }
      /* #1356: both save buttons follow the link, for the same reason
       * the watch button does - a control that can only fail is worse
       * than no control. */
      var shotBtn = document.getElementById('pineCamShot');
      var recBtn = document.getElementById('pineCamRec');
      if (shotBtn) shotBtn.hidden = !live;
      if (recBtn) recBtn.hidden = !live;
      if (!live && recFrom) {
        /* The camera went mid-clip. Cut what was actually recorded
         * rather than dropping the mark on the floor. */
        record();
      }
      var why = document.getElementById('pineCamWhy');
      if (why && got) {
        why.textContent = live ? ('live' + (cropOn ? ' · cropped' : ''))   /* [pincrop] */
          : (got.state === 'live' && !got.fresh) ? 'stale' : String(got.state || '');   /* #1387 */
      }
      paintRow(got, live);
      paintBattery(got && got.battery, live);   /* [cambattery] after the pip exists */
      railTabs();                          /* 2026-09-14: the rail entries */
      /* If it goes while the view is open, say so rather than freezing on
       * the last frame - a still picture of a camera that has gone is the
       * worst of both. */
      if (was && !live && shown) { close(); }
    }).catch(function () { /* the station will be asked again in 5s */ });
  }

  /* ------------------------------------------------- the sidebar row */

  /* The Pine Cam reads the way the tablet does: what it is, whether it
   * is reachable, and what it is costing. It is ALWAYS listed, unlike
   * the button - a device that only appears when it is working cannot
   * tell you that it is not working, and 'no camera on the network' is
   * the answer to the question most often being asked. */
  function paintRow(got, isLive) {
    var brief = document.getElementById('pineCamBrief');
    var stats = document.getElementById('pineCamStats');
    if (!brief) return;
    if (!got) { brief.textContent = 'the station did not answer'; return; }
    var state = String(got.state || '');
    var seen = !!got.seen;
    /* #1387: A STALE CLAIM IS NOT A STATE. The supervisor writes
     * `state` on transitions and `at` on every pass; when it stops
     * passing - measured: state=live, at 13 hours old, frame.jpg from
     * the night before, the radio seeing no camera - the file still
     * says 'live', and this fell through to printing that word. The
     * row read 'live' over a dead link for a whole morning. `fresh` is
     * the supervisor's heartbeat and it outranks the word. */
    var stale = (state === 'live' && got && !got.fresh);
    var silentFor = (got && got.at) ? Math.max(0, Math.round(Date.now() / 1000 - Number(got.at))) : 0;
    var silentSay = silentFor >= 3600 ? Math.round(silentFor / 3600) + 'h' : Math.round(silentFor / 60) + 'm';
    brief.textContent = isLive ? 'live'
      : stale ? 'link stale - supervisor silent ' + silentSay
      : seen ? 'on the network - joining'
        : state === 'no-link' ? 'not on the network' : (state || 'looking…');
    if (!isLive && got.battery && got.battery.dark) {       /* [cambattery2] */
      brief.textContent = 'camera went dark – battery likely flat';
    }
    paintBars(isLive, seen, stale, Number(got.signal || 0));
    if (!stats) return;
    var mb = Math.round(Number(got.kept_bytes || 0) / 1048576);
    var rows = [
      ['where', String(got.ssid || '') + ' · ' + String(got.camera || '')],
      ['signal', got.signal ? got.signal + '%' : (seen ? 'seen' : '—')],
      ['link', isLive ? 'joined, recording'
        : stale ? 'the supervisor stopped reporting ' + silentSay + ' ago - press Reconnect'
        : state || 'not joined'],
      ['kept', (got.clips || 0) + ' clip(s) · ' + mb + ' MB'],
      ['newest', String(got.newest || '—')]
    ];
    if (got.battery && got.battery.ok) rows.splice(3, 0, ['battery', battRowSay(got.battery)]);   /* [cambattery2] */
    stats.innerHTML = rows.map(function (r) {
      /* #1120: "Right here put a folder icon that whenever I click it
       * it opens up a file explorer showing me the location where all
       * the clips are being saved and then next to it offer a sprocket
       * where I can set the preferences for where these files are
       * being saved at." - on the KEPT row, beside the count. The
       * same two doors the header icons open (#1118), so there is one
       * folder and one preference sheet however they are reached. */
      var tools = r[0] === 'kept'
        ? '<button type="button" class="pine-cam-rowbtn" data-act="folder" '
          + 'title="Open the folder where the clips are kept">'
          + icon('c:folder', 'Open the clips folder', 'clips') + '</button>'
          + '<button type="button" class="pine-cam-rowbtn" data-act="prefs" '
          + 'title="Where the clips are kept, and where they are exported to">'
          + icon('c:settings', 'Clip folder preferences', 'prefs') + '</button>'
        : '';
      return '<div class="pv-row' + (tools ? ' pine-cam-keptrow' : '') + '"><span>'
        + r[0] + '</span><b>' + String(r[1]).replace(/[&<>]/g, '') + '</b>'
        + tools + '</div>';
    }).join('');
    if (!stats.__pineCamRowWired) {
      stats.__pineCamRowWired = true;
      stats.addEventListener('click', function (ev) {
        var b = ev.target && ev.target.closest
          ? ev.target.closest('.pine-cam-rowbtn') : null;
        if (!b) return;
        ev.preventDefault();
        ev.stopPropagation();
        if (b.getAttribute('data-act') === 'folder') showFolder();
        else openPrefs();
      });
    }
    paintPip(stats, isLive);
  }

  /* #1119: "Put a picture in picture display of what the pine cam shows
   * when it's enabled here." - INSIDE the card, under the rows, whenever
   * the link is live. The same frame.jpg road the floating box uses
   * (four a second, cache-busted); the <img> is one node kept across
   * repaints, re-appended after the rows are rebuilt so it never
   * reloads from black, and it is removed - not hidden - the moment the
   * camera goes, because a still of a camera that has gone is the lie
   * #1387 was about. */
  var pip = null;
  var pipTimer = 0;

  function paintPipFrame() {
    if (!pip || !pip.isConnected || !live) return;
    var img = pip.querySelector('img');
    if (img) img.src = base() + '/api/pinelink/frame.jpg?c=' + Date.now();
  }

  function paintPip(stats, isLive) {
    if (!isLive) {
      if (pip && pip.parentNode) pip.parentNode.removeChild(pip);
      pip = null;
      if (pipTimer) { clearInterval(pipTimer); pipTimer = 0; }
      return;
    }
    if (!pip) {
      pip = document.createElement('div');
      pip.className = 'pine-cam-pip';
      pip.title = 'The Pine Cam, live - click for the floating picture';
      var img = document.createElement('img');
      img.alt = 'The Pine Cam, live';
      pip.appendChild(img);
      pip.addEventListener('click', function (ev) {
        ev.stopPropagation();
        open();
      });
    }
    if (pip.parentNode !== stats) stats.appendChild(pip);
    if (!pipTimer) { paintPipFrame(); pipTimer = setInterval(paintPipFrame, FRAME_MS); }
  }

  /* 2026-09-14: "I want to see signal bars growing on this whenever it's
   * searching for an element on the network and I want to be able to
   * click it and be able to bring up a pop-up that allows me to find out
   * more detailed information." Five bars on the card header: sweeping
   * while the radio is looking, lit to the signal once the camera is
   * seen, all lit and still once the link is live. A click opens the
   * ladder (#1118) - the detailed account - without folding the row. */
  function paintBars(isLive, seen, stale, signal) {
    var row = document.getElementById('pineCamRow');
    if (!row) return;
    var bars = document.getElementById('pineCamBars');
    if (!bars) {
      bars = document.createElement('span');
      bars.id = 'pineCamBars';
      bars.className = 'pine-cam-bars';
      bars.title = 'The radio, the scan, the link - click for the whole ladder';
      bars.setAttribute('role', 'button');
      for (var i = 0; i < 5; i += 1) {
        var b = document.createElement('i');
        b.style.height = (4 + i * 2) + 'px';
        b.style.animationDelay = (i * 0.15) + 's';
        bars.appendChild(b);
      }
      bars.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        try { openLadder(); } catch (e) { /* the row still folds by itself */ }
      });
      var brief = document.getElementById('pineCamBrief');
      if (brief && brief.parentNode === row) row.insertBefore(bars, brief);
      else row.appendChild(bars);
    }
    var lit = isLive ? 5 : (seen ? Math.max(1, Math.min(5, Math.ceil(signal / 20))) : 0);
    bars.classList.toggle('searching', !isLive && !seen && !stale);
    bars.classList.toggle('live', !!isLive);
    bars.classList.toggle('stale', !!stale);
    for (var k = 0; k < bars.children.length; k += 1) {
      bars.children[k].classList.toggle('lit', k < lit);
    }
  }

  /* --------------------------------------------------- the viewers */

  /* #1354: WHICH LISTENERS MAY SEE THE CAMERA.
   *
   * The roster needed no inventing: every tune-in link was already
   * minted with a label against a tag that is signed into the token.
   * So "which users" is a tick beside a link, and the permission
   * travels with the link rather than beside it - revoke the link and
   * the camera goes with it.
   *
   * The station decides; this only draws what it said and posts back
   * what was clicked. Nothing here is trusted by the frame road.
   */
  var viewMode = '';

  function post(path, body) {
    try {
      if (root.pineDesktop && root.pineDesktop.post) {
        return root.pineDesktop.post(path, body);
      }
    } catch (e) { /* fall through to fetch */ }
    return fetch(base() + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.ok ? r.json() : null; });
  }

  function say(text) {
    var el = document.getElementById('pineCamShareSay');
    if (el) el.textContent = String(text || '');
  }

  function paintViewers(got) {
    var modes = document.getElementById('pineCamModes');
    var list = document.getElementById('pineCamViewers');
    if (!modes || !list || !got) return;
    viewMode = String(got.mode || 'off');
    Array.prototype.forEach.call(modes.children, function (b) {
      b.classList.toggle('on', b.getAttribute('data-mode') === viewMode);
    });
    /* The list is only a question when the mode is asking it. Shown
     * under 'anyone' it would read as a restriction that is not being
     * applied, which is the kind of half-true control that gets a
     * camera pointed at the wrong room. */
    list.classList.toggle('show', viewMode === 'picked');
    if (viewMode !== 'picked') { say(got.say || ''); return; }
    var rows = got.viewers || [];
    list.innerHTML = '';
    if (!rows.length) {
      say('no tune-in links exist yet, so there is nobody to pick - '
        + 'mint one on the Share panel first');
      return;
    }
    rows.forEach(function (v) {
      var line = document.createElement('label');
      line.className = 'pine-cam-viewer';
      var tick = document.createElement('input');
      tick.type = 'checkbox';
      tick.checked = !!v.camera;
      var name = document.createElement('span');
      name.textContent = v.label || 'a listener';
      var left = document.createElement('em');
      left.textContent = v.hours_left >= 48
        ? Math.round(v.hours_left / 24) + 'd left'
        : Math.round(v.hours_left) + 'h left';
      tick.addEventListener('change', function () {
        tick.disabled = true;
        Promise.resolve(post('/api/share/camera',
          {tag: v.tag, camera: tick.checked})).then(function (r) {
          tick.disabled = false;
          if (r && r.say) say(r.say);
          if (!r || !r.ok) { tick.checked = !tick.checked; }
          viewers();
        }).catch(function () {
          tick.disabled = false;
          tick.checked = !tick.checked;
          say('the station did not answer');
        });
      });
      line.appendChild(tick);
      line.appendChild(name);
      line.appendChild(left);
      list.appendChild(line);
    });
    say(got.say || '');
  }

  function viewers() {
    Promise.resolve(ask('/api/pinelink/viewers'))
      .then(paintViewers)
      .catch(function () { /* asked again on the next sweep */ });
  }

  function setMode(mode) {
    say('…');
    Promise.resolve(post('/api/pinelink/public', {mode: mode}))
      .then(function (r) {
        if (r && r.say) say(r.say);
        viewers();
      }).catch(function () { say('the station did not answer'); });
  }

  /* ------------------------------------- a still, and a clip (#1356) */

  /* WHY RECORDING IS A CUT, NOT A CAPTURE.
   *
   * The link records continuously in five-minute segments whenever the
   * camera is joined, so pressing Record does not have to ask the
   * camera for anything. It marks a moment; pressing it again marks
   * another; the station cuts exactly that span out of what is already
   * on disk.
   *
   * Three things that buys, each of which a fresh capture loses:
   * nothing is missed at the head while a stream opens, stopping is
   * instant rather than waiting for a flush, and the camera is never
   * asked for a second client - these access-point cameras commonly
   * allow exactly one, and the second one costs you the first.
   */
  var recFrom = 0;
  var recTick = 0;

  function save(opts) {
    try {
      if (root.pineDesktop && root.pineDesktop.camSave) {
        return root.pineDesktop.camSave(opts);
      }
    } catch (e) { /* fall through */ }
    return Promise.resolve({ok: false,
      why: 'saving to disk needs the desktop app'});
  }

  function stamp() {
    var d = new Date();
    function two(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-'
      + two(d.getDate()) + '_' + two(d.getHours()) + '-'
      + two(d.getMinutes()) + '-' + two(d.getSeconds());
  }

  function snapshot() {
    say('saving the picture…');
    Promise.resolve(save({url: '/api/pinelink/frame.jpg',
      name: 'pinecam-' + stamp() + '.jpg'})).then(function (r) {
      if (!r) { say('the app did not answer'); return; }
      if (r.canceled) { say(''); return; }
      say(r.ok ? ('saved to ' + r.path) : ('could not save: ' + r.why));
    });
  }

  function recPaint() {
    var b = document.getElementById('pineCamRec');
    if (!b) return;
    if (!recFrom) { b.textContent = 'Record'; b.classList.remove('on'); return; }
    var s = Math.max(0, Math.round(Date.now() / 1000 - recFrom));
    b.classList.add('on');
    b.textContent = 'Stop ' + Math.floor(s / 60) + ':'
      + (s % 60 < 10 ? '0' : '') + (s % 60);
  }

  function record() {
    if (!recFrom) {
      recFrom = Date.now() / 1000;
      recPaint();
      if (!recTick) recTick = setInterval(recPaint, 500);
      say('marking - press again to end the clip and save it');
      return;
    }
    var from = recFrom;
    var to = Date.now() / 1000;
    recFrom = 0;
    if (recTick) { clearInterval(recTick); recTick = 0; }
    recPaint();
    if (to - from < 1) { say('that was too short to cut'); return; }
    say('cutting ' + Math.round(to - from) + 's out of the recording…');
    Promise.resolve(post('/api/pinelink/cut', {from: from, to: to}))
      .then(function (r) {
        if (!r || !r.ok) {
          say((r && r.say) || 'the cut did not come back');
          return;
        }
        say('saving the clip…');
        /* #1118: the Save As opens on the folder the preference sheet
         * names, when it names one. The desktop honours `dir`; the
         * tablet's save() answers 'needs the desktop app' either way. */
        var opts = {url: r.url, kind: 'video',
          name: 'pinecam-' + stamp() + '.mp4'};
        if (prefs && prefs.export_dir) opts.dir = String(prefs.export_dir);
        return save(opts).then(function (s) {
          readPrefs();                     /* the sheet may have moved under us */
          if (!s) { say('the app did not answer'); return; }
          if (s.canceled) {
            /* The cut is kept on the station either way, so a cancelled
             * Save As is not a lost recording - say so, or it reads
             * like one. */
            say('not saved here - the cut is still on the station');
            return;
          }
          say(s.ok ? ('saved to ' + s.path)
            : ('could not save: ' + s.why));
        });
      }).catch(function () { say('the station did not answer'); });
  }

  /* #1361b: THE WHOLE LADDER, FROM ONE PRESS.
   *
   * "Earlier I clicked it and it wasn't able to show the picture in
   *  picture window." The row folds; the Look button watches; the
   * troubleshooter describes; Reset radio and Reconnect each do one
   * thing. Four controls for one intent. This is the intent: get the
   * picture up, doing whatever the doctor says is needed on the way.
   *
   * It asks the doctor, presses the cure the doctor names (reset-radio
   * or reconnect), waits for the link, and opens the box - and if the
   * link is already live it just opens the box, because the operator
   * pressed a button that says 'show me the picture'. */
  var healing = false;

  function heal() {
    if (healing) return;
    healing = true;
    var doc = document.getElementById('pineCamDoc');
    var tools = document.getElementById('pineCamTools');
    if (tools) tools.hidden = false;
    var stats = document.getElementById('pineCamStats');
    if (stats) stats.hidden = false;
    function tell(t) { if (doc) { doc.hidden = false; doc.textContent = t; } }
    function finish(t) { healing = false; tell(t); look(); }
    if (live) { healing = false; open(); return; }
    tell('asking the link doctor…');
    Promise.resolve(ask('/api/pinelink/doctor')).then(function (d) {
      if (!d) { finish('the station did not answer'); return; }
      var lines = [d.verdict || 'no verdict'].concat((d.steps || []).map(
        function (t, i) { return (i + 1) + '. ' + t; }));
      var cure = String(d.cure || '');
      var road = cure === 'reset' ? '/api/pinelink/reset-radio'
        : (d.camera ? '/api/pinelink/connect' : '');
      if (!road) {
        /* Nothing this side can press: the camera itself is not on
         * the air. Say so plainly - the next move is a button on the
         * camera, not one here. */
        finish(lines.concat(['', 'nothing here can fix that - the camera '
          + 'has to be on the air first']).join(String.fromCharCode(10)));
        return;
      }
      lines.push('', 'pressing ' + (cure === 'reset' ? 'Reset radio' : 'Reconnect') + '…');
      tell(lines.join(String.fromCharCode(10)));
      return Promise.resolve(post(road, {})).then(function (r) {
        lines.push((r && r.say) || 'no answer');
        tell(lines.join(String.fromCharCode(10)));
        /* The link joins in its own time - up to fifteen seconds after
         * a reset. Poll rather than guess, and open the picture the
         * moment it is there. */
        var left = 8;
        (function wait() {
          Promise.resolve(ask('/api/pinelink/state')).then(function (got) {
            var up = !!(got && got.state === 'live' && got.fresh);
            if (up) { live = true; showButton(true); healing = false; tell(lines.concat(['linked - opening the picture']).join(String.fromCharCode(10))); open(); look(); return; }
            if (left -= 1) { setTimeout(wait, 3000); return; }
            finish(lines.concat(['still not linked after the cure - press Troubleshoot for the current reading']).join(String.fromCharCode(10)));
          }, function () { finish('the station did not answer'); });
        }());
      });
    }).catch(function () { finish('the station did not answer'); });
  }

  /* #1359: the cure the troubleshooter can only describe. */
  function resetRadio() {
    var out = document.getElementById('pineCamDoc');
    if (out) { out.hidden = false; out.textContent = 'resetting the radio…'; }
    Promise.resolve(post('/api/pinelink/reset-radio', {}))
      .then(function (r) {
        if (out) {
          out.textContent = (r && r.say)
            || 'the station did not answer';
        }
        /* The re-bind and the service restart together take about
         * fifteen seconds, so asking sooner would only show the
         * outage it is curing. */
        setTimeout(troubleshoot, 16000);
      }).catch(function () {
        if (out) out.textContent = 'the station did not answer';
      });
  }

  /* ------------------------------------------------ the troubleshooter */

  /* 'Not on the network' covers three faults with different cures - a
   * dead radio, a camera out of range, a camera that has slept its Wi-Fi
   * to save battery - and they look identical from here. The station
   * cannot tell them apart either; the link supervisor can, because it
   * owns the radio, so this just asks it and prints what it said. */
  function troubleshoot() {
    var out = document.getElementById('pineCamDoc');
    if (!out || busy) return;
    busy = true;
    out.hidden = false;
    out.textContent = 'looking…';
    Promise.resolve(ask('/api/pinelink/doctor')).then(function (d) {
      busy = false;
      if (!d) { out.textContent = 'the station did not answer'; return; }
      var lines = [d.verdict || 'no verdict'];
      if (d.stale) lines.push('(this reading is ' + d.age + 's old)');
      if (d.nearby) {
        lines.push('the radio can see ' + d.nearby + ' network(s)');
      }
      (d.steps || []).forEach(function (t, i) {
        lines.push((i + 1) + '. ' + t);
      });
      out.textContent = lines.join(String.fromCharCode(10));
      look();
    }).catch(function () {
      busy = false;
      out.textContent = 'the station did not answer';
    });
  }

  /* ==================================================================
   * #1118: THE RADIO, THE FOLDER, THE TRIANGLE - AND THE TABLET'S CARD.
   *
   * "Put a radio icon here that whenever I click it, it just goes through
   *  the process of attempting to locate and connect to and display the
   *  pine cam. Showing an interactive flow chart tree that I'm able to
   *  click on each and every step to go through interactively one by one
   *  or examine each step and expand each triangle to see additional
   *  information on the inside with an interactive console showing me
   *  additional information on how each step is doing when it comes to
   *  scanning it, locating it, and giving ... detailed troubleshooting
   *  information as far as what I need to do on my side."
   *
   * The wrench (#1361b) already makes the whole climb from one press, but
   * it reports in a paragraph. This is the same climb drawn as the ladder
   * it is. The station's /api/pinelink/ladder names the rungs - radio,
   * scan, join, stream, frames, record - each with a state, what it
   * measured, what to do on the operator's side, and the one fix this
   * side can press. A seventh rung, `picture`, is this page's own: the
   * box is open here or it is not, and the station cannot know that.
   *
   * Three ways up. RUN ALL presses each fix in order and stops at the
   * first rung that stays red, so a fault reads as WHERE the climb
   * stopped rather than as 'not linked'. NEXT STEP presses one and
   * stops. READ AGAIN presses nothing. Every rung keeps its own console
   * - what was asked, what came back, the re-read after - because 'it
   * did not work' is only useful with the transcript beside it.
   *
   * "Also I need an icon of a folder that whenever I click it, it brings
   *  up a folder and file explorer showing me the location where all of
   *  the clips are being kept and I want to have the ability to choose
   *  where those clips are being kept at ... put a triangle next to the
   *  folder that whenever I click it, it offers me a preference to go in
   *  and specify the folder where these PineCam videos are being
   *  exported to."
   *
   * The folder opens the kept clips in Explorer through the desktop
   * bridge; on a surface without one it prints the path instead of
   * failing quietly. The triangle is the preference sheet: where the
   * station keeps clips (inside its own data folder - the container can
   * write nowhere else, and the station refuses anything outside it with
   * a `say`), where the desktop exports them, and whether every kept
   * clip is carried there unasked.
   *
   * "Also I want the ability to stream from the pine cam to the pine tab.
   *  So whenever I activate the pine camera, I want the pine tablet to
   *  show a display notification in the middle of the screen. I'm able
   *  to tap on it and it shows a picture in picture window of what the
   *  pine cam is able to see."
   *
   * Pressing the radio also POSTs /api/pinelink/announce; the tablet
   * sees `announce_at` move on its next state poll (look(), above) and
   * puts a card in the middle of its screen. The card is honest about
   * time: the camera usually joins some seconds after the operator
   * reaches for it, so a card that arrives first says 'being switched
   * on' and, once tapped, opens the box the moment the link is live.
   *
   * Everything here is built from JS at start(), never from the card's
   * markup, because the tablet has no card and must still get the toast
   * - and one body of code serving both surfaces is the only way the two
   * stay the same thing. Icons come through pineIcon (Carbon) with a
   * word behind each in case the sprite is not on the page.
   * ================================================================== */

  var LADDER_KEY = 'pineCamLadderBox';
  var LADDER_MS = 5000;        /* re-read while the sheet is open */
  var SETTLE_MS = 3000;        /* a fix, then this, then the re-read */
  var SETTLE_TRIES = 5;        /* 'wait' is re-read this many more times */
  var TOAST_MS = 25000;
  var WAIT_FOR_JOIN_MS = 180000;

  var prefs = null;            /* /api/pinelink/prefs - read at start, after a save */
  var prefsEl = null;
  var ladderEl = null;
  var ladderOpen = false;
  var ladderTimer = 0;
  var ladderRunning = false;
  var ladderLast = null;       /* the rungs as last read, picture rung localised */
  var ladderNodes = {};        /* rung id -> its <details>; the console lives in it */
  var framesWereOk = false;
  var toast = null;
  var toastTimer = 0;
  var toastWaitUntil = 0;      /* the card was tapped before the link was live */
  var announceSeen = -1;       /* announce_at as last seen; -1 until the first answer */
  var polled = false;

  var STATES = {ok: 1, bad: 1, wait: 1, unknown: 1};

  function nl() { return String.fromCharCode(10); }

  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  /* Carbon through pineIcon where the sprite is loaded; a word where it
   * is not. A button with nothing in it is a button nobody finds. */
  function icon(ref, label, word) {
    var m = '';
    try {
      if (typeof root.pineIcon === 'function') m = root.pineIcon(ref, label);
    } catch (e) { m = ''; }
    return m || (word ? '<span class="pine-cam-word">' + esc(word) + '</span>' : '');
  }

  function clock() {
    var d = new Date();
    function two(n) { return (n < 10 ? '0' : '') + n; }
    return two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
  }

  function later(ms) {
    return new Promise(function (res) { setTimeout(res, ms); });
  }

  function brief(v) {
    var s;
    try { s = JSON.stringify(v); } catch (e) { s = String(v); }
    s = String(s);
    return s.length > 240 ? s.slice(0, 240) + '…' : s;
  }

  /* ------------------------------------------------ the desktop bridge */

  /* Both may be absent - the tablet's bridge is the smaller one - and
   * an absent method degrades to 'no-bridge', which the callers turn
   * into printing the path. */
  function openFolder(path) {
    try {
      if (root.pineDesktop && root.pineDesktop.openFolder) {
        return Promise.resolve(root.pineDesktop.openFolder(path));
      }
    } catch (e) { /* fall through */ }
    return Promise.resolve({ok: false, why: 'no-bridge'});
  }

  function pickFolder(opts) {
    try {
      if (root.pineDesktop && root.pineDesktop.pickFolder) {
        return Promise.resolve(root.pineDesktop.pickFolder(opts));
      }
    } catch (e) { /* fall through */ }
    return Promise.resolve({ok: false, why: 'no-bridge'});
  }

  function unfold() {
    var tools = document.getElementById('pineCamTools');
    var stats = document.getElementById('pineCamStats');
    if (tools) tools.hidden = false;
    if (stats) stats.hidden = false;
  }

  function tellDoc(t) {
    var doc = document.getElementById('pineCamDoc');
    if (doc) { doc.hidden = false; doc.textContent = t; }
  }

  /* ------------------------------------------------------ the folder */

  function readPrefs() {
    return Promise.resolve(ask('/api/pinelink/prefs')).then(function (p) {
      if (p) prefs = p;
      return prefs;
    }).catch(function () { return prefs; });
  }

  function showFolder() {
    unfold();
    tellDoc('asking where the clips are kept…');
    readPrefs().then(function (p) {
      if (!p) { tellDoc('the station did not answer'); return; }
      var path = String(p.clips_host || p.clips_dir || '');
      return openFolder(path).then(function (r) {
        if (r && r.ok) { tellDoc('opened ' + path); return; }
        var lines = ['the clips are kept at', path];
        if (p.clips_container) lines.push('(inside the container: ' + p.clips_container + ')');
        if (p.export_dir) lines.push('exported to: ' + p.export_dir);
        lines.push('', (r && r.why && r.why !== 'no-bridge')
          ? 'could not open it from here: ' + r.why
          : 'this surface cannot open a folder - the path is above');
        tellDoc(lines.join(nl()));
      });
    });
  }

  /* ---------------------------------------------- the preference sheet */

  function psay(t) {
    var el = document.getElementById('pineCamPrefSay');
    if (el) el.textContent = String(t || '');
  }

  function paintPrefs(p) {
    if (!prefsEl || !p) return;
    var keep = document.getElementById('pineCamPrefKeep');
    var host = document.getElementById('pineCamPrefKeepHost');
    var exp = document.getElementById('pineCamPrefExport');
    var carry = document.getElementById('pineCamPrefCarry');
    if (keep) keep.value = String(p.clips_dir || '');
    if (host) {
      host.textContent = String(p.clips_host || '')
        + (p.clips_container ? '  (container: ' + p.clips_container + ')' : '');
    }
    if (exp) exp.value = String(p.export_dir || '');
    if (carry) carry.checked = !!p.carry;
  }

  function savePrefs() {
    var keep = document.getElementById('pineCamPrefKeep');
    var exp = document.getElementById('pineCamPrefExport');
    var carry = document.getElementById('pineCamPrefCarry');
    var body = {
      clips_dir: keep ? keep.value.trim() : '',
      export_dir: exp ? exp.value.trim() : '',
      carry: !!(carry && carry.checked)
    };
    psay('saving…');
    Promise.resolve(post('/api/pinelink/prefs', body)).then(function (p) {
      if (!p) { psay('the station did not answer'); return; }
      /* The answer is the sheet as the station now holds it - a refused
       * clips_dir comes back as the old one with the refusal in `say`,
       * so painting the answer shows the truth, not the wish. */
      if (p.clips_dir !== undefined) prefs = p;
      paintPrefs(p);
      psay(p.say || (p.ok ? 'saved' : 'not saved'));
    }).catch(function () { psay('the station did not answer'); });
  }

  function choosePrefFolder() {
    var exp = document.getElementById('pineCamPrefExport');
    pickFolder({title: 'Where PineCam videos are exported to',
      defaultPath: exp ? exp.value : ''}).then(function (r) {
      if (!r) { psay('the app did not answer'); return; }
      if (r.canceled) return;
      if (r.ok && r.path) {
        if (exp) exp.value = String(r.path);
        psay('chosen - press Save to keep it');
        return;
      }
      psay(r.why === 'no-bridge'
        ? 'this surface has no folder picker - type the path'
        : ('could not choose: ' + (r.why || 'no reason given')));
    });
  }

  function buildPrefs() {
    if (prefsEl) return prefsEl;
    prefsEl = document.createElement('div');
    prefsEl.id = 'pineCamPrefs';
    prefsEl.className = 'pine-cam-prefs';
    prefsEl.innerHTML =
      '<div class="pine-cam-bar"><b>PINE CAM - WHERE THE CLIPS GO</b><i></i>'
      + '<button type="button" class="pine-cam-x" aria-label="Close" title="Close">×</button></div>'
      + '<div class="pcp-body">'
      + '<label class="pcp-h" for="pineCamPrefKeep">Kept at</label>'
      + '<input id="pineCamPrefKeep" type="text" spellcheck="false" '
      + 'placeholder="data/pinelink/clips">'
      + '<div class="pcp-path" id="pineCamPrefKeepHost"></div>'
      + '<div class="pcp-hint">must be inside the station\'s data folder '
      + '(the station can write nowhere else)</div>'
      + '<label class="pcp-h" for="pineCamPrefExport">Exported to</label>'
      + '<div class="pcp-row"><input id="pineCamPrefExport" type="text" '
      + 'spellcheck="false" placeholder="a folder on this computer">'
      + '<button type="button" id="pineCamPrefPick" '
      + 'title="Pick the folder with the desktop\'s folder chooser">'
      + icon('c:folder', '', '') + '<span>Choose…</span></button></div>'
      + '<label class="pine-cam-pref pcp-carry" for="pineCamPrefCarry">'
      + '<input id="pineCamPrefCarry" type="checkbox">'
      + '<span>Carry every kept clip there automatically</span></label>'
      /* [tabrelay] which road reaches the camera */
      + '<div class="pcp-h pcp-relay-h">' + icon('c:network--4', '', '')
      + '<span>Relay through the PineTab</span></div>'
      + '<div class="pcp-row pcp-relay" id="pineCamRelay" role="radiogroup" '
      + 'aria-label="Relay through the PineTab" title="Relay through the PineTab: the tablet '
      + 'joins the camera as a second, local-only Wi-Fi link and passes the picture on">'
      + relayBtn('auto', 'Auto: the PineTab carries the camera when it can join it; otherwise the Spark\'s dongle')
      + relayBtn('always', 'Always: read the camera through the PineTab only - the dongle stays off')
      + relayBtn('never', 'Never: the Spark\'s dongle only, as before')
      + '</div>'
      + '<div class="pcp-hint" id="pineCamRelaySay"></div>'
      + '<div class="pcp-row pcp-foot"><button type="button" id="pineCamPrefSave">'
      + icon('c:checkmark--filled', '', '') + '<span>Save</span></button>'
      + '<span id="pineCamPrefSay" class="pcp-say"></span></div>'
      + '</div>';
    document.body.appendChild(prefsEl);
    prefsEl.style.left = Math.max(8, Math.round((window.innerWidth - 380) / 2)) + 'px';
    prefsEl.style.top = Math.max(8, Math.min(120, window.innerHeight - 320)) + 'px';
    drag(prefsEl, prefsEl.querySelector('.pine-cam-bar'), false);
    prefsEl.querySelector('.pine-cam-x').addEventListener('click', closePrefs);
    document.getElementById('pineCamPrefPick').addEventListener('click', choosePrefFolder);
    document.getElementById('pineCamPrefSave').addEventListener('click', savePrefs);
    [].forEach.call(prefsEl.querySelectorAll('.pcp-relay button'), function (b) {   /* [tabrelay] */
      b.addEventListener('click', function (ev) { ev.stopPropagation(); relaySet(b.getAttribute('data-pref')); });
    });
    return prefsEl;
  }

  /* [tabrelay] THE CAMERA'S ROAD, IN ONE LINE. tools/pinelink.py reads the
   * camera through the Spark's dongle or through the PineTab (a local-only
   * second Wi-Fi link, relayed on TacoNet) and says which in state.json
   * `source`; this line says it back over the picture. No `source` (a
   * supervisor without the relay) draws nothing, exactly as before. */
  function pathSay(src) {
    if (!src || !src.use) return '';
    if (src.use === 'tablet') {
      var sig = Number(src.tablet_signal) || 0;
      return 'via PineTab' + (sig > 0 ? ' · camera signal ' + Math.round(sig) + '%' : '');
    }
    if (src.use === 'wait') return 'switching to the PineTab…';
    return 'via the Spark’s dongle';
  }

  function pathPaint(got) {
    var el = document.getElementById('pineCamPath');
    if (!el) return;
    var src = got && got.source;
    var text = live ? pathSay(src) : '';
    el.hidden = !text;
    el.textContent = text;
    el.title = text ? String((src && src.why) || text) : '';
  }

  /* [tabrelay] "Relay through the PineTab: auto / always / never". */
  function relayBtn(pref, tip) {
    return '<button type="button" role="radio" aria-checked="false" data-pref="'
      + pref + '" title="' + esc(tip) + '"><span>' + pref + '</span></button>';
  }

  function relayPaint(v) {
    var row = document.getElementById('pineCamRelay');
    if (!row || !v) return;
    [].forEach.call(row.querySelectorAll('button'), function (b) {
      var on = b.getAttribute('data-pref') === v.pref;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    var say = document.getElementById('pineCamRelaySay');
    if (!say) return;
    var bits = [];
    if (v.say) bits.push(String(v.say));
    if (v.source && v.source.why) bits.push('now: ' + String(v.source.why));
    else if (!v.report || !v.report.at) bits.push('the PineTab has not reported');
    say.textContent = bits.join(' - ');
  }

  function relayRead() {
    return Promise.resolve(ask('/api/pinelink/relay'))
      .then(function (v) { relayPaint(v); return v; }, function () { return null; });
  }

  function relaySet(pref) {
    var say = document.getElementById('pineCamRelaySay');
    if (say) say.textContent = 'saving…';
    Promise.resolve(post('/api/pinelink/relay', {pref: pref})).then(function (v) {
      if (!v) { if (say) say.textContent = 'the station did not answer'; return; }
      relayPaint(v);
    }, function () { if (say) say.textContent = 'the station did not answer'; });
  }

  function openPrefs() {
    buildPrefs();
    prefsEl.hidden = false;
    nativeMenu(true);                      /* #1470: a sheet over the surface */
    psay('reading…');
    relayRead();                           /* [tabrelay] */
    readPrefs().then(function (p) {
      if (!p) { psay('the station did not answer'); return; }
      paintPrefs(p);
      psay(p.say || '');
    });
  }

  function closePrefs() { if (prefsEl) prefsEl.hidden = true; nativeMenu(false); }

  /* ------------------------------------------------ the ladder sheet */

  function findRung(rungs, id) {
    for (var i = 0; rungs && i < rungs.length; i++) {
      if (rungs[i] && rungs[i].id === id) return rungs[i];
    }
    return null;
  }

  function rungOk(rungs, id) {
    var r = findRung(rungs, id);
    return !!(r && r.state === 'ok');
  }

  function firstNotOk(rungs) {
    for (var i = 0; rungs && i < rungs.length; i++) {
      if (rungs[i] && rungs[i].state !== 'ok') return rungs[i];
    }
    return null;
  }

  /* The picture rung is this page's, whatever the station sent for it:
   * the box is open here (`shown`) or it is not. Its fix is open(). */
  function pictureRung(r, framesOk) {
    var p = {};
    var k;
    for (k in (r || {})) {
      if (Object.prototype.hasOwnProperty.call(r, k)) p[k] = r[k];
    }
    p.id = 'picture';
    p.label = p.label || 'Picture';
    p.state = shown ? 'ok' : (framesOk ? 'wait' : 'unknown');
    p.detail = shown ? 'the box is open here'
      : framesOk ? 'frames are arriving but the box is not open here yet'
        : 'waits for frames';
    p.data = (p.data && typeof p.data === 'object') ? p.data : {};
    p.data.shown_here = shown;
    p.data.surface = (root.pineDesktop && root.pineDesktop.camSave) ? 'desktop' : 'served page';
    p.fix = {label: 'Open the picture', route: '', method: 'LOCAL', body: null};
    if (!p.help || !p.help.length) {
      p.help = ['press Open the picture here, the CAM flag, or the Pine Cam row\'s Look button'];
    }
    return p;
  }

  function localise(rungs) {
    var out = [];
    var had = false;
    var framesOk = findRung(rungs, 'frames')
      ? rungOk(rungs, 'frames') : rungOk(rungs, 'stream');
    (rungs || []).forEach(function (r) {
      if (!r || !r.id) return;
      if (r.id === 'picture') { had = true; out.push(pictureRung(r, framesOk)); }
      else out.push(r);
    });
    if (!had) out.push(pictureRung(null, framesOk));
    return out;
  }

  function nodeFor(r) {
    var node = ladderNodes[r.id];
    if (node) return node;
    node = document.createElement('details');
    node.className = 'pcl-step';
    node.setAttribute('data-rung', r.id);
    node.innerHTML =
      '<summary><i class="pcl-dot unknown"></i>'
      + '<b class="pcl-label"></b><span class="pcl-detail"></span></summary>'
      + '<div class="pcl-in">'
      + '<div class="pcl-h">what the station measured</div>'
      + '<div class="pcl-data"></div>'
      + '<div class="pcl-h">on your side</div>'
      + '<ul class="pcl-help"></ul>'
      + '<div class="pcl-act"><button type="button" class="pcl-run" hidden></button></div>'
      + '<div class="pcl-h">console</div>'
      + '<pre class="pcl-console"></pre>'
      + '</div>';
    node.querySelector('.pcl-run').addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      var cur = findRung(ladderLast, r.id);
      if (cur) runOne(cur);
    });
    ladderNodes[r.id] = node;
    return node;
  }

  /* Repaints a rung in place. The <details> and its console are never
   * rebuilt, so an open triangle stays open across the 5s re-read. */
  function paintNode(node, r) {
    var state = STATES[r.state] ? r.state : 'unknown';
    node.querySelector('.pcl-dot').className = 'pcl-dot ' + state;
    node.setAttribute('data-state', state);
    node.querySelector('.pcl-label').textContent = r.label || r.id;
    node.querySelector('.pcl-detail').textContent = r.detail || '';
    var d = (r.data && typeof r.data === 'object') ? r.data : {};
    var rows = Object.keys(d).map(function (k) {
      var v = d[k];
      var shown_ = (v !== null && typeof v === 'object') ? brief(v) : String(v);
      return '<div class="pcl-kv"><span>' + esc(k) + '</span><b>' + esc(shown_) + '</b></div>';
    });
    node.querySelector('.pcl-data').innerHTML = rows.length
      ? rows.join('') : '<div class="pcl-none">nothing measured</div>';
    var help = (r.help && r.help.length) ? r.help : [];
    node.querySelector('.pcl-help').innerHTML = help.length
      ? help.map(function (h) { return '<li>' + esc(h) + '</li>'; }).join('')
      : '<li class="pcl-none">nothing to do on your side for this one</li>';
    var run = node.querySelector('.pcl-run');
    if (r.fix) {
      run.hidden = false;
      run.textContent = r.fix.label || 'Run this step';
      run.disabled = ladderRunning;
    } else {
      run.hidden = true;
    }
  }

  function con(id, text) {
    var node = nodeFor({id: id});
    var pre = node.querySelector('.pcl-console');
    var line = '[' + clock() + '] ' + String(text || '');
    /* [autoscroll-rule] followed, and trimmed, only while the reader is at
       the tail; one scrolled back keeps the line they were reading */
    var stick = root.pineStick ? root.pineStick(pre, {edge: 'bottom'}) : null;
    var atTail = stick ? stick.following() : true;
    var lines = pre.textContent ? pre.textContent.split(nl()) : [];
    lines.push(line);
    if (atTail && lines.length > 200) lines = lines.slice(lines.length - 200);
    pre.textContent = lines.join(nl());
    if (stick) stick.follow();
    node.classList.add('pcl-spoke');
  }

  function openNode(id) {
    var node = ladderNodes[id];
    if (node) node.open = true;
  }

  function setLadderState(text) {
    var st = document.getElementById('pineCamLadderState');
    if (st && text !== undefined) st.textContent = String(text || '');
  }

  function setBusy(on, text) {
    ladderRunning = on;
    if (ladderEl) {
      Array.prototype.forEach.call(
        ladderEl.querySelectorAll('.pcl-bar button, .pcl-run'),
        function (b) { b.disabled = on; });
      ladderEl.classList.toggle('pcl-running', on);
    }
    setLadderState(text);
  }

  function paintLadder(got, rungs) {
    if (!ladderEl) return;
    var tree = ladderEl.querySelector('.pcl-tree');
    rungs.forEach(function (r, i) {
      var node = nodeFor(r);
      paintNode(node, r);
      if (tree.children[i] !== node) tree.insertBefore(node, tree.children[i] || null);
    });
    var say = document.getElementById('pineCamLadderSay');
    if (say) {
      say.textContent = String(got.verdict || '')
        + (got.say ? (got.verdict ? ' - ' : '') + got.say : '');
    }
    var lv = document.getElementById('pineCamLadderLive');
    if (lv) lv.textContent = got.live ? 'live' : 'not linked';
  }

  function repaintPicture() {
    if (!ladderEl || !ladderLast) return;
    for (var i = 0; i < ladderLast.length; i++) {
      if (ladderLast[i] && ladderLast[i].id === 'picture') {
        ladderLast[i] = pictureRung(ladderLast[i], framesWereOk);
        paintNode(nodeFor(ladderLast[i]), ladderLast[i]);
      }
    }
  }

  function readLadder() {
    return Promise.resolve(ask('/api/pinelink/ladder')).then(function (got) {
      if (!got) { setLadderState('the station did not answer'); return null; }
      var rungs = localise(got.rungs);
      ladderLast = rungs;
      paintLadder(got, rungs);
      /* "display the pine cam": the moment frames arrive the box opens
       * by itself - on the transition only, so closing the box while
       * the sheet is open does not have it reopened five seconds later. */
      var fOk = findRung(rungs, 'frames') ? rungOk(rungs, 'frames') : rungOk(rungs, 'stream');
      if (fOk && !framesWereOk && !shown && ladderOpen) {
        con('picture', 'stream and frames turned green - opening the picture');
        open();
      }
      framesWereOk = fOk;
      return ladderLast;
    }).catch(function () { setLadderState('the station did not answer'); return null; });
  }

  /* Press a rung's fix and print the exchange into its console. Resolves
   * to the answer, or null when nothing came back. */
  function pressFix(r) {
    var id = r.id;
    if (id === 'picture') {
      con(id, 'opening the picture box');
      open();
      return Promise.resolve({ok: true, say: 'opened here'});
    }
    var f = r.fix;
    if (!f || !f.route) {
      con(id, 'this rung has no fix this side can press');
      return Promise.resolve(null);
    }
    var method = String(f.method || 'POST').toUpperCase();
    var body = f.body || {};
    con(id, method + ' ' + f.route
      + (method === 'POST' && Object.keys(body).length ? ' ' + brief(body) : ''));
    var p = method === 'GET' ? ask(f.route) : post(f.route, body);
    return Promise.resolve(p).then(function (a) {
      if (!a) { con(id, 'no answer'); return null; }
      var said = false;
      if (a.say) { con(id, 'say: ' + a.say); said = true; }
      if (a.verdict) { con(id, 'verdict: ' + a.verdict); said = true; }
      (a.steps || []).forEach(function (t, i) {
        con(id, '  ' + (i + 1) + '. ' + t);
        said = true;
      });
      if (!said) con(id, 'answer: ' + brief(a));
      if (a.ok === false) con(id, 'the station said it did not do it');
      return a;
    }, function () { con(id, 'the station did not answer'); return null; });
  }

  /* One rung: press, give the link time, read again, say what changed. */
  function climb(r) {
    return pressFix(r).then(function () {
      con(r.id, 'waiting ' + (SETTLE_MS / 1000) + 's for it to settle');
      return later(SETTLE_MS);
    }).then(readLadder).then(function (again) {
      var now = again ? findRung(again, r.id) : null;
      if (!now) { con(r.id, 'could not read the ladder again'); return null; }
      con(r.id, 'now ' + now.state + ' - ' + (now.detail || ''));
      return now;
    });
  }

  /* 'wait' is a fix still working - a reset radio takes about fifteen
   * seconds to come back - so it is read again a few times before it is
   * called. */
  function settle(id, tries) {
    return later(SETTLE_MS).then(readLadder).then(function (rungs) {
      var now = rungs ? findRung(rungs, id) : null;
      if (!now) return null;
      if (now.state !== 'wait' || tries <= 0) {
        con(id, 'now ' + now.state + ' - ' + (now.detail || ''));
        return now;
      }
      con(id, 'still waiting - ' + (now.detail || '') + ' (' + tries + ' more look(s))');
      return settle(id, tries - 1);
    });
  }

  function runOne(r) {
    if (ladderRunning) return;
    setBusy(true, 'running ' + (r.label || r.id) + '…');
    openNode(r.id);
    climb(r).then(function (now) {
      setBusy(false, now ? ((now.label || r.id) + ' is now ' + now.state)
        : 'the station did not answer');
    }).catch(function () { setBusy(false, 'the station did not answer'); });
  }

  /* The climb. onlyOne is the 'one by one' mode: the first rung that is
   * not green, and stop. */
  function runAll(onlyOne) {
    if (ladderRunning) return;
    setBusy(true, onlyOne ? 'one step…' : 'running…');
    var cap = 12;
    function done(text) { setBusy(false, text || ''); }
    function stepOn(rungs) {
      if (!rungs) { done('the station did not answer'); return; }
      var r = firstNotOk(rungs);
      if (!r) {
        done('every rung is green');
        if (!shown) open();
        return;
      }
      if (cap <= 0) { done('stopped: the rungs keep changing under the climb - read again'); return; }
      cap -= 1;
      if (!r.fix) {
        /* Nothing this side can press: the next move is on the
         * operator's side - a button on the camera, a battery, a room.
         * Open the rung so "on your side" is in view. */
        con(r.id, 'nothing here can press this one - read "on your side"');
        openNode(r.id);
        done('stopped at ' + (r.label || r.id) + ': ' + (r.detail || 'nothing this side can press'));
        return;
      }
      return climb(r).then(function (now) {
        if (now && now.state === 'wait') return settle(r.id, SETTLE_TRIES);
        return now;
      }).then(function (now) {
        if (!now) { done('the station did not answer'); return; }
        if (now.state !== 'ok') {
          con(r.id, 'still ' + now.state + ' after its fix - stopping here');
          openNode(r.id);
          done('stopped at ' + (now.label || r.id) + ': ' + (now.detail || ''));
          return;
        }
        if (onlyOne) {
          done((now.label || r.id) + ' is green - press Next step for the next rung');
          return;
        }
        return stepOn(ladderLast);
      });
    }
    readLadder().then(stepOn).catch(function () { done('the climb failed - read again'); });
  }

  function buildLadder() {
    if (ladderEl) return ladderEl;
    ladderEl = document.createElement('div');
    ladderEl.id = 'pineCamLadder';
    ladderEl.className = 'pcl-sheet';
    ladderEl.innerHTML =
      '<div class="pine-cam-bar pcl-head"><b>PINE CAM - THE LADDER</b>'
      + '<i id="pineCamLadderLive"></i>'
      + '<button type="button" class="pine-cam-x" aria-label="Close the ladder" title="Close the ladder">×</button></div>'
      + '<div class="pcl-bar">'
      + '<button type="button" id="pineCamLadderAll" '
      + 'title="Read the ladder and press each rung\'s fix in order, stopping at the first that stays red">'
      + icon('c:renew', '', '') + '<span>Run all</span></button>'
      + '<button type="button" id="pineCamLadderNext" '
      + 'title="Press only the first rung that is not green, then stop">'
      + icon('c:caret--right', '', '') + '<span>Next step</span></button>'
      + '<button type="button" id="pineCamLadderRead" '
      + 'title="Read the ladder again without pressing anything">'
      + icon('c:view', '', '') + '<span>Read again</span></button>'
      + '<span id="pineCamLadderState" class="pcl-state"></span>'
      + '</div>'
      + '<div id="pineCamLadderSay" class="pcl-say"></div>'
      + '<div class="pcl-tree"></div>';
    document.body.appendChild(ladderEl);
    place(ladderEl, LADDER_KEY, {w: 400, x: 24, y: 72});
    drag(ladderEl, ladderEl.querySelector('.pcl-head'), LADDER_KEY);
    ladderEl.querySelector('.pine-cam-x').addEventListener('click', closeLadder);
    document.getElementById('pineCamLadderAll').addEventListener('click', function () { runAll(false); });
    document.getElementById('pineCamLadderNext').addEventListener('click', function () { runAll(true); });
    document.getElementById('pineCamLadderRead').addEventListener('click', function () {
      if (ladderRunning) return;
      setLadderState('reading…');
      readLadder().then(function (r) { if (r) setLadderState('read at ' + clock()); });
    });
    return ladderEl;
  }

  function openLadder() {
    buildLadder();
    ladderEl.hidden = false;
    ladderOpen = true;
    nativeMenu(true);                      /* #1470: a sheet over the surface */
    readLadder();
    if (!ladderTimer) {
      ladderTimer = setInterval(function () {
        /* A climb does its own reads; a second reader would only
         * interleave its lines with the climb's. */
        if (ladderOpen && !ladderRunning) readLadder();
      }, LADDER_MS);
    }
  }

  function closeLadder() {
    ladderOpen = false;
    if (ladderEl) ladderEl.hidden = true;
    if (ladderTimer) { clearInterval(ladderTimer); ladderTimer = 0; }
    nativeMenu(false);
  }

  /* The radio icon: tell the tablet, open the sheet, climb. */
  /* 2026-09-14: THE TABLET'S SIDE RAIL. "an option in the sidebar on the
   * pine tab to view the pine cam whenever it is present ... and a button
   * in the sidebar to scan for, locate, and connect to the pine cam and
   * go through troubleshooting." The rail (#pineViewRail, rail.js) is
   * built at boot from VIEWS[]; these are not views, so they are appended
   * as two more tabs in the rail's own class. CAM is shown only while the
   * link is live and opens the picture; FIND CAM runs the ladder with its
   * console, whatever the state. The rail scrolls, so a tenth tab is
   * reachable. Re-tried from look() until the rail exists. */
  function railTabs() {
    var rail = document.getElementById('pineViewRail');
    if (!rail) return;
    var cam = document.getElementById('pineViewTab-cam');
    if (!cam) {
      cam = document.createElement('button');
      cam.id = 'pineViewTab-cam';
      cam.type = 'button';
      cam.className = 'pine-view-tab pine-view-tab-cam';
      cam.textContent = 'CAM';
      cam.title = 'The Pine Cam is here - tap for the picture';
      cam.addEventListener('click', function (ev) { ev.stopPropagation(); toggle(); });
      rail.appendChild(cam);
      var find = document.createElement('button');
      find.id = 'pineViewTab-camfind';
      find.type = 'button';
      find.className = 'pine-view-tab pine-view-tab-camfind';
      find.textContent = 'FIND CAM';
      find.title = 'Scan for the Pine Cam, connect to it, and put its picture up - step by step';
      find.addEventListener('click', function (ev) { ev.stopPropagation(); radio(); });
      rail.appendChild(find);
    }
    cam.style.display = live ? '' : 'none';
    cam.classList.toggle('on', !!shown);
  }

  function radio() {
    openLadder();
    con('radio', 'the radio icon was pressed - telling the tablet the camera is being switched on');
    Promise.resolve(post('/api/pinelink/announce', {})).then(function (a) {
      con('radio', (a && a.ok)
        ? 'the tablet has been told (announce_at ' + (a.at || '?') + ')'
        : 'announce: ' + (a ? brief(a) : 'no answer'));
    }, function () { con('radio', 'announce: the station did not answer'); });
    runAll(false);
  }

  /* ------------------------------------------- the card on the tablet */

  function hideToast() {
    if (toastTimer) { clearTimeout(toastTimer); toastTimer = 0; }
    if (toast && toast.parentNode) toast.parentNode.removeChild(toast);
    toast = null;
  }

  function showToast(isLive) {
    if (!document.body) return;
    hideToast();
    toast = document.createElement('div');
    toast.id = 'pineCamToast';
    toast.className = 'pine-cam-toast';
    toast.setAttribute('role', 'button');
    toast.innerHTML =
      '<i class="pine-cam-flag-dot"></i>'
      + '<div class="pine-cam-toast-text"><b>'
      + (isLive ? 'The Pine Cam is live' : 'The Pine Cam is being switched on…')
      + '</b><span>'
      + (isLive ? 'tap to watch it' : 'tap to watch when it joins')
      + '</span></div>'
      + '<button type="button" class="pine-cam-x" aria-label="Dismiss" title="Dismiss">×</button>';
    toast.querySelector('.pine-cam-x').addEventListener('click', function (ev) {
      ev.stopPropagation();
      toastWaitUntil = 0;
      hideToast();
    });
    toast.addEventListener('click', function () {
      if (live) { hideToast(); open(); return; }
      /* Tapped before the link is there: the intent is kept, and
       * look() opens the box on the poll that first sees `live`. The
       * card itself still goes at 25s; the intent outlives it a while. */
      toastWaitUntil = Date.now() + WAIT_FOR_JOIN_MS;
      var t = toast ? toast.querySelector('.pine-cam-toast-text') : null;
      if (t) {
        t.innerHTML = '<b>Waiting for the Pine Cam to join…</b>'
          + '<span>the picture opens by itself when it does</span>';
      }
      look();
    });
    document.body.appendChild(toast);
    toastTimer = setTimeout(hideToast, TOAST_MS);
  }

  /* ---------------------------------- the three controls on the card */

  /* Only where the card is: the tablet has no #pineCamHeal and gets the
   * toast instead. They stack leftwards from the wrench (see the CSS):
   * radio, folder, then the small caret against the folder. */
  function buildTools(after) {
    var parent = after.parentNode;
    if (!parent) return;
    function mk(id, ref, word, title, onClick) {
      var b = document.createElement('button');
      b.id = id;
      b.type = 'button';
      b.className = 'vitals-tool pine-cam-tool';
      b.title = title;
      b.innerHTML = icon(ref, '', word);
      b.addEventListener('click', function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        onClick();
      });
      parent.insertBefore(b, after.nextSibling);
      return b;
    }
    mk('pineCamRadio', 'm:radio', 'find',
      'Find, connect and show the Pine Cam - step by step', radio);
    mk('pineCamFolder', 'c:folder', 'clips',
      'Open the folder where the clips are kept', showFolder);
    mk('pineCamFolderPref', 'c:caret--right', '▸',
      'Choose where the clips are kept and where they are exported to', openPrefs);
  }

  function start() {
    try { railTabs(); } catch (e) { /* no rail on this surface */ }
    try { folded = localStorage.getItem(FOLD_KEY) === '1'; }
    catch (e) { folded = false; }
    /* #1118: the three icons beside the wrench, and the export folder
     * the Record button needs before its first save. */
    var heal0 = document.getElementById('pineCamHeal');
    if (heal0 && !document.getElementById('pineCamRadio')) buildTools(heal0);
    readPrefs();
    var stats0 = document.getElementById('pineCamStats');
    var tools0 = document.getElementById('pineCamTools');
    if (stats0) stats0.hidden = folded;
    if (tools0) tools0.hidden = folded;
    var lookBtn = document.getElementById('pineCamLook');
    if (lookBtn && !lookBtn.__wired) {
      lookBtn.__wired = true;
      lookBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        if (live) { toggle(); } else { troubleshoot(); }
      });
    }
    var modes = document.getElementById('pineCamModes');
    if (modes && !modes.__wired) {
      modes.__wired = true;
      modes.addEventListener('click', function (ev) {
        var b = ev.target && ev.target.closest
          ? ev.target.closest('[data-mode]') : null;
        if (!b) return;
        ev.stopPropagation();
        setMode(b.getAttribute('data-mode'));
      });
    }
    /* No fold wiring of its own: the picker lives INSIDE
     * #pineCamTools, which the header already hides and shows. A
     * second hidden flag, set once at startup, would strand the list
     * shut the first time the panel was opened. */
    var fixBtn = document.getElementById('pineCamFix');
    if (fixBtn && !fixBtn.__wired) {
      fixBtn.__wired = true;
      fixBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        troubleshoot();
      });
    }
    var shotBtn = document.getElementById('pineCamShot');
    if (shotBtn && !shotBtn.__wired) {
      shotBtn.__wired = true;
      shotBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        snapshot();
      });
    }
    var recBtn = document.getElementById('pineCamRec');
    if (recBtn && !recBtn.__wired) {
      recBtn.__wired = true;
      recBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        record();
      });
    }
    var healBtn = document.getElementById('pineCamHeal');
    if (healBtn && !healBtn.__wired) {
      healBtn.__wired = true;
      healBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        heal();
      });
    }
    var resetBtn = document.getElementById('pineCamReset');
    if (resetBtn && !resetBtn.__wired) {
      resetBtn.__wired = true;
      resetBtn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        resetRadio();
      });
    }
    var row = document.getElementById('pineCamRow');
    if (row && !row.__pineCamWired) {
      row.__pineCamWired = true;
      row.addEventListener('click', function () {
        /* #1349: THE HEADER FOLDS, like every other panel in this
         * sidebar. Watching it is the LOOK button's job; a header that
         * opens a video is a header that behaves unlike its neighbours. */
        folded = !folded;
        var stats = document.getElementById('pineCamStats');
        var tools = document.getElementById('pineCamTools');
        if (stats) stats.hidden = folded;
        if (tools) tools.hidden = folded;
        row.setAttribute('aria-expanded', folded ? 'false' : 'true');
        try { localStorage.setItem(FOLD_KEY, folded ? '1' : '0'); }
        catch (e) { /* a forgotten fold is not worth an error */ }
      });
    }
    var b = button();
    if (b && !b.__pineCamWired) {
      b.__pineCamWired = true;
      b.addEventListener('click', toggle);
    }
    /* #1470: the lock screen and a backgrounded document must cover the
     * native picture, which no z-index can reach. */
    document.addEventListener('visibilitychange', nativeCover);
    try {
      if (document.body && root.MutationObserver) {
        new MutationObserver(nativeCover).observe(document.body, {attributes: true, attributeFilter: ['class']});
      }
    } catch (e) { /* no observer: the surface simply stays */ }
    look();
    viewers();
    if (!timer) timer = setInterval(look, POLL_MS);
  }

  root.PineCam = {start: start, open: open, close: close,
    toggle: toggle, isLive: function () { return live; },
    /* #1470: the native picture's callbacks and a reading of it. */
    tapPicture: tapPicture, wallBoxChanged: wallBoxChanged, bare: setBare,
    dragPicture: dragPicture, holdPicture: holdPicture,   /* [pincrop] */
    native: function () { return {on: nativeOn, full: nativeFull, bare: bare, ts: tsInfo}; },
    /* #1118: the sheets, reachable from a console or another view. */
    ladder: openLadder, prefs: openPrefs, folder: showFolder,
    crop: cropDrawOpen, cropMenu: holdAt,                 /* [pincrop] */
    announce: function () { return post('/api/pinelink/announce', {}); },
    /* [cambattery] paint a reading (a /api/pinelink/state `battery`), or read the last */
    battery: function (b, isLive) { return b === undefined ? batt : paintBattery(b, isLive); }};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}(typeof window !== 'undefined' ? window : globalThis));
