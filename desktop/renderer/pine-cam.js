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
        why.textContent = live ? 'live' : String(got.state || '');
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
    brief.textContent = isLive ? 'live'
      : seen ? 'on the network - joining'
        : state === 'no-link' ? 'not on the network' : (state || 'looking…');
    if (!stats) return;
    var mb = Math.round(Number(got.kept_bytes || 0) / 1048576);
    var rows = [
      ['where', String(got.ssid || '') + ' · ' + String(got.camera || '')],
      ['signal', got.signal ? got.signal + '%' : (seen ? 'seen' : '—')],
      ['link', isLive ? 'joined, recording' : state || 'not joined'],
      ['kept', (got.clips || 0) + ' clip(s) · ' + mb + ' MB'],
      ['newest', String(got.newest || '—')]
    ];
    stats.innerHTML = rows.map(function (r) {
      return '<div class="pv-row"><span>' + r[0] + '</span><b>'
        + String(r[1]).replace(/[&<>]/g, '') + '</b></div>';
    }).join('');
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
        return save({url: r.url, kind: 'video',
          name: 'pinecam-' + stamp() + '.mp4'}).then(function (s) {
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

  function start() {
    try { folded = localStorage.getItem(FOLD_KEY) === '1'; }
    catch (e) { folded = false; }
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
    toggle: toggle, isLive: function () { return live; }};

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
}(typeof window !== 'undefined' ? window : globalThis));
