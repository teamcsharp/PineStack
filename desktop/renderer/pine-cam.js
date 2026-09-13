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
  var shown = false;
  var live = false;

  function base() {
    try {
      var cfg = root.pineDesktopConfig || {};
      return String(cfg.baseUrl || '').replace(/\/$/, '')
        || 'http://10.89.1.246:8096';
    } catch (e) { return 'http://10.89.1.246:8096'; }
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

  function button() {
    return document.getElementById('glassPineCam');
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

  function place(el) {
    var at = null;
    try { at = JSON.parse(localStorage.getItem(KEY) || 'null'); }
    catch (e) { at = null; }
    /* Off-screen is a real possibility: the window may be smaller than it
     * was when this was saved. */
    var w = Math.max(240, Math.min(640, (at && at.w) || 360));
    var left = (at && typeof at.x === 'number') ? at.x
      : Math.max(12, window.innerWidth - w - 28);
    var top = (at && typeof at.y === 'number') ? at.y : 96;
    left = Math.min(Math.max(0, left), Math.max(0, window.innerWidth - 120));
    top = Math.min(Math.max(0, top), Math.max(0, window.innerHeight - 90));
    el.style.width = w + 'px';
    el.style.left = left + 'px';
    el.style.top = top + 'px';
  }

  function remember(el) {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        x: parseInt(el.style.left, 10) || 0,
        y: parseInt(el.style.top, 10) || 0,
        w: parseInt(el.style.width, 10) || 360
      }));
    } catch (e) { /* a forgotten position is not worth an error */ }
  }

  function drag(el, handle) {
    var from = null;
    handle.addEventListener('mousedown', function (ev) {
      if (ev.button !== 0) return;
      from = {x: ev.clientX, y: ev.clientY,
        left: parseInt(el.style.left, 10) || 0,
        top: parseInt(el.style.top, 10) || 0};
      ev.preventDefault();
    });
    document.addEventListener('mousemove', function (ev) {
      if (!from) return;
      el.style.left = Math.max(0, Math.min(window.innerWidth - 80,
        from.left + (ev.clientX - from.x))) + 'px';
      el.style.top = Math.max(0, Math.min(window.innerHeight - 60,
        from.top + (ev.clientY - from.y))) + 'px';
    });
    document.addEventListener('mouseup', function () {
      if (from) { remember(el); from = null; }
    });
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
      + '<button type="button" class="pine-cam-x" '
      + 'aria-label="Close the camera view">×</button>'
      + '</div>'
      + '<img id="pineCamImg" alt="The Pine Cam, live">';
    document.body.appendChild(box);
    place(box);
    drag(box, box.querySelector('.pine-cam-bar'));
    box.querySelector('.pine-cam-x').addEventListener('click', close);
    return box;
  }

  function paintFrame() {
    var img = document.getElementById('pineCamImg');
    if (!img || !shown) return;
    /* A cache-buster, because the frame is one URL that keeps changing and
     * every layer between here and the disk would happily hold on to it. */
    img.src = base() + '/api/pinelink/frame.jpg?t=' + Date.now();
  }

  function open() {
    build();
    shown = true;
    box.hidden = false;
    paintFrame();
    if (!frameTimer) frameTimer = setInterval(paintFrame, FRAME_MS);
  }

  function close() {
    shown = false;
    if (box) box.hidden = true;
    if (frameTimer) { clearInterval(frameTimer); frameTimer = 0; }
  }

  function toggle() { if (shown) { close(); } else { open(); } }

  /* ---------------------------------------------------------- the ask */

  function look() {
    Promise.resolve(ask('/api/pinelink/state')).then(function (got) {
      var was = live;
      /* `fresh` is the supervisor's own heartbeat: a state file is a file,
       * and a stale one claiming "live" is exactly the lie this has to
       * avoid. Both, or it is not there. */
      live = !!(got && got.state === 'live' && got.fresh);
      showButton(live);
      var why = document.getElementById('pineCamWhy');
      if (why && got) {
        why.textContent = live ? 'live' : String(got.state || '');
      }
      /* If it goes while the view is open, say so rather than freezing on
       * the last frame - a still picture of a camera that has gone is the
       * worst of both. */
      if (was && !live && shown) { close(); }
    }).catch(function () { /* the station will be asked again in 5s */ });
  }

  function start() {
    var b = button();
    if (b && !b.__pineCamWired) {
      b.__pineCamWired = true;
      b.addEventListener('click', toggle);
    }
    look();
    if (!timer) timer = setInterval(look, POLL_MS);
  }

  root.PineCam = {start: start, open: open, close: close,
    toggle: toggle, isLive: function () { return live; }};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}(typeof window !== 'undefined' ? window : globalThis));
