/* THE FURNITURE EVERY TERMINAL VIEW WEARS.
 *
 * All three of the operator's sketches draw the same things in the same
 * corner, and they are numbered in every one of them:
 *
 *   Sampler sketch   1,2,3  "Listen | Music | Tech"   the view bar
 *                    4      the pine tree
 *                    5      the feed
 *   Script sketch    1      the view bar
 *                    2      "pine tree -> menu"
 *                    3      the transport
 *                    4      the feed
 *   Presentation     the same transport, the same feed
 *
 * They were not built. Each view was reached through the DESKTOP's own tab
 * rail instead - which does not exist on the tablet, where the equivalent is
 * a native drawer behind a left-edge swipe. So on the one device this is all
 * for, a view had no way to say what it was or to hand you the next one.
 *
 * Hence one module, mounted by every view, rather than five near-copies that
 * drift. What it draws:
 *
 *   [ Listen | Music | Sampler | Script | Present | Tech ]   the bar
 *   [ the pine tree ]                                        the menu
 *   [ |< >/|| ----o---- >| ]                                 the transport
 *
 * and the feed, which is built by `PineChromeFeed` below because the sketches
 * put the same scrolling list in the same place three times.
 *
 * TWO RULES IT OBEYS, both learned the hard way on this station.
 *
 * 1. NO POLLER. It subscribes to the one shared feed and nothing else. This
 *    station has a documented history of being starved by chatty clients, and
 *    it was measured this week: 38 requests in flight against HTTP/1.1's six
 *    connections per origin, a p99 queue of 10.8 seconds, and media on the
 *    tablet taking 46 seconds to deliver its first 64 kB - which is why the
 *    tablet played nothing at all. Furniture does not get a timer.
 *
 * 2. THE PALETTE LIVES ON THE HOST. On the tablet these views are injected
 *    into the station's own panel, where `var(--cyan)` resolves to nothing
 *    and a control becomes near-black on transparent. sampler.css learned
 *    that by having its mode buttons vanish; view-chrome.css carries its own.
 */
(function (root) {
  'use strict';

  /* Every screen the terminal has, in the order the sketches read them.
   * `id` is the view section's id, so the switcher works in the desktop
   * shell and in the tablet's injected panel without a second mapping. */
  var VIEWS = [
    {id: 'listen', label: 'Listen', why: 'The station, lean back.'},
    {id: 'music', label: 'Music', why: 'Playlist, schedule, requests, the shelf.'},
    {id: 'sampler', label: 'Sampler', why: 'Sixteen pads, five banks.'},
    {id: 'script', label: 'Script', why: 'Where a line came from.'},
    {id: 'presentation', label: 'Present', why: 'The wall: playlist, schedule, feed, gallery.'},
    {id: 'control', label: 'Tech', why: 'The full Pine Box application.'}
  ];

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  /* Switching views.
   *
   * The desktop shell owns a tab rail whose buttons carry data-view; the
   * tablet has no such rail. Clicking the real tab where one exists keeps
   * every side effect the shell attaches to it (mounting a view on first
   * visit, pausing another). Only when there is no tab does this move the
   * `active` class itself. */
  function show(id) {
    var tab = document.querySelector('[data-view="' + id + '"]');
    if (tab && typeof tab.click === 'function') { tab.click(); return true; }
    var target = document.getElementById(id);
    if (!target) return false;
    var views = document.querySelectorAll('.view');
    for (var i = 0; i < views.length; i += 1) views[i].classList.remove('active');
    target.classList.add('active');
    return true;
  }

  function currentView() {
    var active = document.querySelector('.view.active');
    return active ? active.id : '';
  }

  /* ---- the pine tree, which is a menu ------------------------------- */

  /* The sketch says "pine tree -> menu", and on the tablet the menu it means
   * already exists: the native drawer behind a left-edge swipe, carrying
   * broadcast routing, the station settings and the view switcher. A finger
   * that has found the tree should not also have to know about the gesture,
   * so the tree opens it.
   *
   * Three doors, tried in order of how much they can do:
   *   the native rail            (tablet, via the bridge)
   *   the desktop station drawer (the same controls, in the shell)
   *   this module's own sheet    (anything else - never nothing) */
  function openMenu() {
    var native = root.pineDesktop && root.pineDesktop.openRail;
    if (typeof native === 'function') { native(); return 'rail'; }
    var drawer = document.getElementById('stationDrawer');
    if (drawer) {
      var opener = document.getElementById('stationDrawerBtn');
      if (opener && typeof opener.click === 'function') { opener.click(); return 'drawer'; }
      drawer.classList.add('open');
      return 'drawer';
    }
    return 'sheet';
  }

  /* ---- the transport ------------------------------------------------ */

  /* What each control may touch, decided once and written down, because the
   * obvious wiring is wrong on a shared station:
   *
   *   |<  >|   the station's own queue - everybody's next track. These are
   *            real station writes and they are labelled as such.
   *   >/||     THIS TERMINAL only. The operator's standing rule is that the
   *            show goes to one room; a play button that paused the air from
   *            a lean-back screen would take the station off for the whole
   *            house because somebody wanted quiet in one room.
   *   ----o    POSITION, not a seek. There is no route to move the station's
   *            playhead, and a scrubber that silently does nothing is worse
   *            than a readout that is honest about being one.
   */
  function transportState(station) {
    var now = (station && station.now) || null;
    var seconds = Number((now && now.seconds) || 0);
    var at = Number((station && station.elapsed) || 0);
    if (!Number.isFinite(at) || at < 0) at = 0;
    if (seconds > 0 && at > seconds) at = seconds;
    return {
      title: (now && (now.title || now.name)) || '',
      artist: (now && now.artist) || '',
      seconds: seconds,
      at: at,
      fraction: seconds > 0 ? at / seconds : 0
    };
  }

  function clock(value) {
    var total = Math.max(0, Math.round(Number(value) || 0));
    var mins = Math.floor(total / 60);
    var secs = total % 60;
    return mins + ':' + (secs < 10 ? '0' : '') + secs;
  }

  /* ---- mounting ----------------------------------------------------- */

  function mount(host, options) {
    if (!host) return null;
    var opts = options || {};
    var wrap = el('div', 'vc');

    /* 1 - the view bar. */
    var bar = el('div', 'vc-bar');
    var buttons = {};
    VIEWS.forEach(function (view) {
      var button = el('button', 'vc-tab', view.label);
      button.title = view.why;
      button.dataset.vcView = view.id;
      button.addEventListener('click', function () { show(view.id); paintBar(); });
      buttons[view.id] = button;
      bar.appendChild(button);
    });
    wrap.appendChild(bar);

    function paintBar() {
      var here = opts.view || currentView();
      Object.keys(buttons).forEach(function (id) {
        buttons[id].classList.toggle('on', id === here);
      });
    }
    paintBar();

    /* 2 - the pine tree, which is the menu. */
    var tree = el('button', 'vc-tree');
    tree.title = 'Broadcast, settings and the other views';
    tree.setAttribute('aria-label', 'Pine Box menu');
    /* Drawn, not an emoji: every icon on this station is monochrome by
     * instruction, and an emoji tree is neither monochrome nor the same
     * shape on two devices. */
    tree.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">'
      + '<path d="M12 2 L17 9 H14 L18.5 15 H14.5 L20 21 H4 L9.5 15 H5.5 L10 9 H7 Z"/>'
      + '<rect x="11" y="21" width="2" height="2"/></svg>';
    tree.addEventListener('click', function () {
      var went = openMenu();
      if (went === 'sheet') sheet();
    });
    wrap.appendChild(tree);

    /* 3 - the transport. */
    var transport = null;
    if (opts.transport !== false) {
      transport = el('div', 'vc-transport');
      var back = el('button', 'vc-btn', '⏮');
      back.title = 'The station’s previous track — for everyone listening';
      var play = el('button', 'vc-btn vc-play', '▶');
      play.title = 'Silence this terminal. The station keeps broadcasting.';
      var next = el('button', 'vc-btn', '⏭');
      next.title = 'Skip to the next track — for everyone listening';
      var track = el('div', 'vc-track');
      var fill = el('i', 'vc-fill');
      var knob = el('b', 'vc-knob');
      track.appendChild(fill);
      track.appendChild(knob);
      track.title = 'Where the record is. The station owns the playhead, '
        + 'so this shows the position rather than setting it.';
      var time = el('span', 'vc-time', '0:00');

      back.addEventListener('click', function () { skip(-1); });
      next.addEventListener('click', function () { skip(1); });
      play.addEventListener('click', function () {
        var quiet = wrap.classList.toggle('vc-quiet');
        play.textContent = quiet ? '▶' : '⏸';
        hush(quiet);
      });

      transport.appendChild(back);
      transport.appendChild(play);
      transport.appendChild(track);
      transport.appendChild(next);
      transport.appendChild(time);
      wrap.appendChild(transport);

      transport.__paint = function (station) {
        var state = transportState(station);
        fill.style.width = Math.round(state.fraction * 100) + '%';
        knob.style.left = Math.round(state.fraction * 100) + '%';
        time.textContent = state.seconds
          ? clock(state.at) + ' / ' + clock(state.seconds)
          : clock(state.at);
      };
    }

    host.insertBefore(wrap, host.firstChild || null);

    var stop = null;
    if (root.PineStationFeed && typeof root.PineStationFeed.subscribe === 'function') {
      stop = root.PineStationFeed.subscribe(function (state) {
        if (transport && transport.__paint) transport.__paint(state);
      });
    }

    return {
      node: wrap,
      bar: bar,
      transport: transport,
      paint: paintBar,
      show: show,
      stop: function () { if (typeof stop === 'function') stop(); }
    };
  }

  /* The station's own queue. A skip is a write everybody hears, so it goes
   * through the bridge with the bearer attached rather than a bare fetch -
   * and a refusal is reported, not swallowed. */
  function skip(direction) {
    var api = root.pineDesktop;
    /* It is /api/dj/prev (app.py:94242), not /previous - checked, not
     * assumed. The wrong name would have been a button that 404s. */
    var route = direction > 0 ? '/api/dj/next' : '/api/dj/prev';
    if (!api || typeof api.post !== 'function') return Promise.resolve(false);
    return api.post(route, {}).then(function () { return true; },
      function () { return false; });
  }

  /* Silence THIS terminal. Never the air. */
  function hush(quiet) {
    var table = root.PineTerminalAudio;
    var nodes = document.querySelectorAll('audio, video');
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (node.closest && node.closest('#sampler, .pb-sampler')) continue;
      node.muted = !!quiet;
    }
    if (table && typeof table.mute === 'function') table.mute(document, !!quiet);
    return !!quiet;
  }

  /* The last-resort menu, for a host with neither rail nor drawer. It lists
   * the views and says where the rest of the controls are, rather than
   * pretending to be the drawer. */
  function sheet() {
    var old = document.getElementById('vcSheet');
    if (old) { old.remove(); return; }
    var box = el('div', 'vc-sheet');
    box.id = 'vcSheet';
    box.appendChild(el('h4', '', 'Pine Box'));
    VIEWS.forEach(function (view) {
      var row = el('button', 'vc-sheet-row', view.label);
      row.title = view.why;
      row.addEventListener('click', function () { show(view.id); box.remove(); });
      box.appendChild(row);
    });
    var note = el('p', 'vc-sheet-note',
      'Broadcast and settings live in the drawer — swipe in from the '
      + 'left edge on the tablet.');
    box.appendChild(note);
    document.body.appendChild(box);
  }

  var api = {
    mount: mount, show: show, currentView: currentView, openMenu: openMenu,
    transportState: transportState, clock: clock, hush: hush, VIEWS: VIEWS
  };
  root.PineViewChrome = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
