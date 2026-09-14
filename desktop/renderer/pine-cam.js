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
  var folded = false;
  var FOLD_KEY = 'pineCamFolded';
  var busy = false;
  var shown = false;
  var live = false;

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

  function drag(el, handle, key) {
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
      if (from) { remember(el, key); from = null; }
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
      + 'aria-label="Close the camera view" title="Close the camera view">×</button>'
      + '</div>'
      + '<img id="pineCamImg" alt="The Pine Cam, live">';
    document.body.appendChild(box);
    place(box);
    drag(box, box.querySelector('.pine-cam-bar'));
    box.querySelector('.pine-cam-x').addEventListener('click', close);
    return box;
  }

  /* 2026-09-14: THE CACHE-BUSTER WORE THE TOKEN'S NAME. `?t=` is the
   * frame route's viewer-token parameter (#1354), so every request from
   * the desk read as a guest holding the token '1789...' and got 403 -
   * 'the camera is not being shared with you' - measured from the PC.
   * The tablet never saw it only because its loopback door needs no
   * token. The buster is `?c=` now, on both pictures. */
  function paintFrame() {
    var img = document.getElementById('pineCamImg');
    if (!img || !shown) return;
    /* A cache-buster, because the frame is one URL that keeps changing and
     * every layer between here and the disk would happily hold on to it. */
    img.src = base() + '/api/pinelink/frame.jpg?c=' + Date.now();
  }

  function open() {
    build();
    shown = true;
    box.hidden = false;
    paintFrame();
    if (!frameTimer) frameTimer = setInterval(paintFrame, FRAME_MS);
    repaintPicture();                      /* #1118: the ladder's last rung is this box */
  }

  function close() {
    shown = false;
    if (box) box.hidden = true;
    if (frameTimer) { clearInterval(frameTimer); frameTimer = 0; }
    repaintPicture();
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
        why.textContent = live ? 'live'
          : (got.state === 'live' && !got.fresh) ? 'stale' : String(got.state || '');   /* #1387 */
      }
      paintRow(got, live);
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
    return prefsEl;
  }

  function openPrefs() {
    buildPrefs();
    prefsEl.hidden = false;
    psay('reading…');
    readPrefs().then(function (p) {
      if (!p) { psay('the station did not answer'); return; }
      paintPrefs(p);
      psay(p.say || '');
    });
  }

  function closePrefs() { if (prefsEl) prefsEl.hidden = true; }

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
    var lines = pre.textContent ? pre.textContent.split(nl()) : [];
    lines.push(line);
    if (lines.length > 200) lines = lines.slice(lines.length - 200);
    pre.textContent = lines.join(nl());
    pre.scrollTop = pre.scrollHeight;
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
  }

  /* The radio icon: tell the tablet, open the sheet, climb. */
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
    look();
    viewers();
    if (!timer) timer = setInterval(look, POLL_MS);
  }

  root.PineCam = {start: start, open: open, close: close,
    toggle: toggle, isLive: function () { return live; },
    /* #1118: the sheets, reachable from a console or another view. */
    ladder: openLadder, prefs: openPrefs, folder: showFolder,
    announce: function () { return post('/api/pinelink/announce', {}); }};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}(typeof window !== 'undefined' ? window : globalThis));
