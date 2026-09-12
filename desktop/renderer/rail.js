/* THE VIEW TABS, ON THE TABLET.
 *
 * "So where are the tabs on the side of the pine tab view representing my
 * other views?"
 *
 * They were built and never wired in. All three of the operator's sketches
 * draw the same switcher - Listen | Music | Tech, with Sampler, Script and
 * Presentation beside them - and on the desktop it is the app's own tab
 * rail. The tablet has no such rail: its shell is a WebView showing the
 * station's panel, and the panel knows nothing about these views.
 *
 * So the rail is built here, the same way the sampler's tab already is
 * (pine-sampler/boot.js): fixed handles welded onto the page from a
 * document-start script, each opening a full-bleed host that a view mounts
 * into.
 *
 * THE RAIL IS ON THE RIGHT. The left edge belongs to the app's own native
 * drawer - broadcast routing, the station settings, the device list - and
 * two things fighting for one edge is worse than either alone. That is the
 * reason the sampler's handle sits where it does, and this keeps it.
 *
 * ONE VIEW AT A TIME. Each host is `position:fixed; inset:0`, so two open at
 * once would stack invisibly and the second would swallow every tap meant
 * for the first. Opening one closes the rest; TECH closes all of them and
 * gives the panel back.
 *
 * MOUNTED LAZILY, and that is not a micro-optimisation. This tablet was
 * measured at 148 MB free with a load average of 25, and the panel alone is
 * a 12,000-node document. Mounting five views at boot - two of them WebGL -
 * would cost that before the operator had asked for any of them. A view is
 * built the first time its tab is pressed, and kept after that.
 */
(function (root) {
  'use strict';

  /* id       the host element's id, which the view's own code looks for
   * cls      the class its stylesheet keys off
   * label    what the tab says, vertically
   * mount    how that view is told to start, tried in order
   * needs    scripts that must have been evaluated for it to work */
  var VIEWS = [
    {id: 'sampler', cls: 'pb-sampler', label: 'SAMPLER', external: true},
    /* PineScriptPage is the one built to the operator's numbered sketch -
     * the three buttons, the tree, the player, the live feed and the
     * Hollywood script. PineScript (the earlier provenance view) is kept as
     * the fallback so a bundle missing the new file still opens something. */
    {id: 'script', cls: 'sc-view', label: 'SCRIPT',
      mount: ['PineScriptPage', 'PineScript']},
    {id: 'listen', cls: 'pb-listen', label: 'LISTEN',
      mount: ['PineListenView', 'PineListen']},
    {id: 'music', cls: 'pb-music', label: 'MUSIC',
      mount: ['PineMusicView', 'PineMusic']},
    {id: 'presentation', cls: 'pv-view', label: 'PRESENT',
      mount: ['PinePresentation', 'PinePresentationView']}
  ];

  var RAIL_CSS = [
    '#pineViewRail{position:fixed;right:0;top:50%;transform:translateY(-50%);',
    'z-index:2147483001;display:flex;flex-direction:column;gap:4px;',
    'font-family:Inter,Segoe UI,system-ui,sans-serif}',
    '.pine-view-tab{background:#1c242c;color:#edf3f5;border:1px solid #35414c;',
    'border-right:none;border-radius:10px 0 0 10px;padding:14px 9px;',
    'font-size:11px;letter-spacing:.09em;writing-mode:vertical-rl;',
    'cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent}',
    '.pine-view-tab.on{background:#65c7da;color:#05131a;border-color:#65c7da}',
    /* TECH is the panel itself - no host, it just closes whatever is open. */
    '.pine-view-tab.tech{background:#222b35}',
    '.pine-view-tab.tech.on{background:#54d18b;color:#05131a;border-color:#54d18b}',
    /* Every view host. display:none until opened, so a view that is mounted
     * but not on screen costs no layout at all. */
    '.pine-view-host{position:fixed;inset:0;z-index:2147483000;display:none;',
    'background:#101419;color:#edf3f5;overflow:hidden;',
    'font-family:Inter,Segoe UI,system-ui,sans-serif}',
    '.pine-view-host.open{display:block}',
    /* The rail must stay reachable over an open view. */
    '.pine-view-host{padding-right:34px}',
    '.pine-view-note{padding:22px;font-size:13px;line-height:1.6;color:#8fa0ad}'
  ].join('');

  function make(tag, id, cls) {
    var node = document.createElement(tag);
    if (id) node.id = id;
    if (cls) node.className = cls;
    return node;
  }

  function hostOf(view) {
    return document.getElementById(view.id);
  }

  /* Close everything, including the sampler, whose host predates this rail
   * and uses its own `open` class on the same element id. */
  function closeAll() {
    for (var i = 0; i < VIEWS.length; i += 1) {
      var host = hostOf(VIEWS[i]);
      if (host) host.classList.remove('open');
      var tab = document.getElementById('pineViewTab-' + VIEWS[i].id);
      if (tab) tab.classList.remove('on');
    }
    var samplerHandle = document.getElementById('pineSamplerTab');
    if (samplerHandle) samplerHandle.classList.remove('on');
  }

  /* Ask a view to build itself. Views were written for the desktop shell,
   * where each publishes a global with a mount(host). The names are tried
   * rather than assumed because these files are maintained separately and a
   * renamed global should degrade to a readable note, not a blank screen. */
  function mount(view, host) {
    if (host.dataset.pineMounted === '1') return 'already';
    for (var i = 0; i < (view.mount || []).length; i += 1) {
      var api = root[view.mount[i]];
      if (!api) continue;
      var fn = api.mount || api.open || api.start;
      if (typeof fn !== 'function') continue;
      try {
        fn.call(api, host);
        host.dataset.pineMounted = '1';
        return 'mounted via ' + view.mount[i];
      } catch (err) {
        host.innerHTML = '';
        host.appendChild(note(view.label + ' could not start: ' + err.message));
        return 'failed: ' + err.message;
      }
    }
    host.appendChild(note(view.label + ' has not been loaded on this terminal '
      + 'yet. Its code is bundled but no global answered to '
      + (view.mount || []).join(' or ') + '.'));
    return 'no global';
  }

  function note(text) {
    var box = make('div', '', 'pine-view-note');
    box.textContent = text;
    return box;
  }

  /* WHICH VIEW HE LEFT IT ON.
   *
   * "Remember what view that I had it on and reopen the app to that view
   * whenever it reopens."
   *
   * localStorage, not the terminal's config: this is a per-glass
   * preference, it must survive a reload as well as a restart, and it must
   * not cost a bridge round trip on a boot that is already fetching a two
   * megabyte panel. Wrapped, because storage throws outright in some
   * contexts and a remembered tab is not worth a broken rail. */
  var MEMORY = 'pineLastView';

  function remember(id) {
    try { localStorage.setItem(MEMORY, String(id || '')); } catch (err) { /* fine */ }
  }

  function remembered() {
    try { return localStorage.getItem(MEMORY) || ''; } catch (err) { return ''; }
  }

  function open(view) {
    var host = hostOf(view);
    if (!host) return;
    var already = host.classList.contains('open');
    closeAll();
    if (already) {
      /* A second press closes it, and closing IS the state to remember -
       * otherwise a terminal deliberately left on the panel reopens onto
       * a view he shut. */
      remember('');
      return;
    }
    host.classList.add('open');
    remember(view.id);
    var tab = document.getElementById('pineViewTab-' + view.id);
    if (tab) tab.classList.add('on');
    mount(view, host);
    /* Anything sized by a grid has no real geometry until it is visible. */
    try { root.dispatchEvent(new Event('resize')); } catch (err) { /* old engine */ }
  }

  root.__pineViewRail = function () {
    if (document.getElementById('pineViewRail')) return 'already';

    var style = make('style');
    style.textContent = (root.__pineViewsCss || '') + RAIL_CSS;
    document.head.appendChild(style);

    var rail = make('div', 'pineViewRail');

    /* TECH first, because it is the way back. */
    var tech = make('button', 'pineViewTab-tech', 'pine-view-tab tech');
    tech.textContent = 'TECH';
    tech.title = 'The full Pine Box application';
    tech.addEventListener('click', function () {
      closeAll();
      tech.classList.add('on');
      setTimeout(function () { tech.classList.remove('on'); }, 400);
    });
    rail.appendChild(tech);

    for (var i = 0; i < VIEWS.length; i += 1) {
      (function (view) {
        /* The sampler already built its own host and handle before this
         * ran. Adopt it rather than building a second one. */
        if (!view.external) {
          var host = make('section', view.id, 'pine-view-host ' + view.cls);
          document.body.appendChild(host);
        }
        var tab = make('button', 'pineViewTab-' + view.id, 'pine-view-tab');
        tab.textContent = view.label;
        tab.addEventListener('click', function () {
          if (view.external) {
            /* Hand the sampler's own handle the press, so its repaint and
             * its `on` state keep working exactly as they did. */
            var handle = document.getElementById('pineSamplerTab');
            var wasOpen = handle && handle.classList.contains('on');
            closeAll();
            if (handle && !wasOpen) handle.click();
            tab.classList.toggle('on', !wasOpen);
            return;
          }
          open(view);
        });
        rail.appendChild(tab);
      })(VIEWS[i]);
    }

    document.body.appendChild(rail);

    /* THE STARTUP ASSEMBLY. Shown once, over whatever the panel is doing,
     * and it removes itself - the station is already on air behind it, so
     * nothing waits on this. The mark is a data URI (pine-logo.js) because
     * the page and the bundled assets are on different origins and the
     * WebView refuses a reference across them. */
    if (root.PineBootSplash && root.__pineLogo && !root.__pineSplashShown) {
      root.__pineSplashShown = true;
      try {
        root.PineBootSplash.show({src: root.__pineLogo});
      } catch (err) { /* decoration must never stop the boot */ }
    }

    /* One line along the bottom of EVERY screen, including the panel behind
     * the rail. It rides the shared feed, so it costs nothing. */
    if (root.PineConsoleLine) {
      try { root.PineConsoleLine.start(); } catch (err) { /* not fatal */ }
    }

    /* REOPEN WHERE HE LEFT OFF.
     *
     * After the rail exists and the views are registered, not before: the
     * host elements are built in this same function. Deferred a beat so
     * the panel behind it has finished its own first paint - a view that
     * mounts into a still-settling document measures the wrong size, which
     * is the fault the portrait pass spent a day on. */
    var last = remembered();
    if (last) {
      setTimeout(function () {
        for (var i = 0; i < VIEWS.length; i += 1) {
          if (VIEWS[i].id !== last) continue;
          try { open(VIEWS[i]); } catch (err) { /* never block the boot */ }
          break;
        }
      }, 1200);
    }

    /* HOLD ANY LINE OF DIALOGUE, ANYWHERE. Bound once, on the document, so
     * every view that marks its lines with `data-line` gets it - including
     * views written after this one. */
    if (root.PineLineActions) {
      try { root.PineLineActions.start(); } catch (err) { /* not fatal */ }
    }

    /* The 3JS scenes: lifted above the views, and promotable to the whole
     * glass. See three-full.js - the windows were opening all along and
     * sitting three million z-indexes below whatever view was open. */
    if (root.PineThreeFull) {
      try { root.PineThreeFull.start(); } catch (err) { /* not fatal */ }

      /* A HANDLE FOR THE SCENES, on the same edge as the views.
       * Thirty-one of them, so it opens a chooser rather than becoming
       * thirty-one more tabs on a nine-inch screen. */
      try {
        /* A button with the same class as its neighbours, not a div: the
         * rail's tabs are buttons, and a div is not focusable and does not
         * take a tap the same way. */
        var tab = make('button', 'pineViewTab-3js', 'pine-view-tab');
        tab.textContent = '3JS';
        tab.title = 'Every 3JS experience, full screen';
        tab.addEventListener('click', function () {
          try { root.PineThreeFull.chooser(); } catch (err) { /* not fatal */ }
        });
        rail.appendChild(tab);
      } catch (err) { /* the rail is more important than the handle */ }
    }

    /* The talk dot, on every screen - the operator asked for it on all of
     * them, not only the one it was designed against. */
    if (root.PineTalkDot) {
      try { root.PineTalkDot.mount(); } catch (err) { /* not fatal */ }
    }

    /* The sampler's own edge handle is now redundant - it is in the rail -
     * and two handles on one edge overlap. Hide it, keep it working. */
    var old = document.getElementById('pineSamplerTab');
    if (old) old.style.display = 'none';

    return 'rail up with ' + (VIEWS.length + 1) + ' tabs';
  };
})(typeof window !== 'undefined' ? window : globalThis);
