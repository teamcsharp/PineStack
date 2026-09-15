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
      mount: ['PinePresentation', 'PinePresentationView']},
    /* THE BOX'S OWN GLASS. A port of ~/bin/media-slideshow, the 25,000-line
     * PySide6 application that has been the slideshow on the Spark since
     * May. Not a second gallery: it plays the SAME /comfy-output folder,
     * writes the SAME favorites.md, and reads the same settings file when
     * the ~/bin mount is present. See slideshow.js. */
    /* `sl-host`, NOT `sl`. The view's own wrapper inside it is `.sl`, and
     * two elements answering one selector is not a tidiness point here: the
     * stylesheet's `.sl{padding-right:0}` would land on the HOST, which is
     * the element reserving the strip this rail sits in. It is only saved
     * by RAIL_CSS being concatenated after the views' CSS - source order,
     * which is not something a stylesheet should depend on. */
    {id: 'slideshow', cls: 'sl-host', label: 'SLIDES',
      mount: ['PineSlideshow']}
  ];

  var RAIL_CSS = [
    '#pineViewRail{position:fixed;right:0;top:50%;transform:translateY(-50%);',
    'z-index:2147483001;display:flex;flex-direction:column;gap:7px;',
    /* THE RAIL MUST NOT RUN OFF THE GLASS. Eight tabs of vertical text
     * measure about 780px; this tablet is 800px tall in landscape, so the
     * ninth one added would have put a tab somewhere no thumb can reach -
     * silently, because a rail centred with translateY overflows equally
     * at both ends. It scrolls instead, with no visible scrollbar. */
    /* #1345: and it must be able to scroll to its own ends. A rail
     * centred with translateY overflows equally top and bottom, so a
     * few px of padding keep the first and last tab off the edge once
     * scrolling is real rather than theoretical. */
    /* 2026-09-15 (#1181): the two numbers the fit() below writes. The
     * fallbacks are what the rail looks like before it has measured
     * anything, and before a display that cannot be measured. */
    'max-height:var(--pine-rail-max,100vh);overflow-y:auto;overscroll-behavior:contain;',
    'padding:4px 0;gap:var(--pine-rail-gap,4px);',
    'scrollbar-width:none;',
    'font-family:Inter,Segoe UI,system-ui,sans-serif}',
    '#pineViewRail::-webkit-scrollbar{display:none}',
    /* #1345: A FLEX CHILD SQUASHES BEFORE ITS PARENT SCROLLS.
     *
     * The rail is a flex column with max-height:100vh and
     * overflow-y:auto, and the note above assumes that a rail too tall
     * for the glass will scroll. It will not. Flex items default to
     * flex-shrink:1, so nine tabs in a container that cannot hold them
     * SHRINK - each one giving up height until they fit - and the
     * overflow the scroll depends on never happens.
     *
     * Because the text is vertical, losing height means losing letters:
     * measured on a resized desktop window the labels read TEC, SAM,
     * SCRI, LIST, MUS, PRES, SLID. And a squashed tab keeps its 1px
     * border and its 10px radius, so the corners of neighbours run
     * together and the rail reads as overlapping rather than as too
     * small - which is what it was reported as.
     *
     * flex-shrink:0 is the whole fix: a tab is now the size of its own
     * word, and when nine of them will not fit the rail finally does
     * the scrolling it was already written to do.
     *
     * The padding went UP, not down. The first cut of this reduced it,
     * which is the opposite of what was asked for - the complaint was
     * that the tabs are TOO SMALL beside the tablet's. Nine tabs at
     * 16px measure 758px, which the desktop window clears comfortably;
     * measured at 1100, 900, 760 and 640px, nothing clips and nothing
     * overlaps. The gap went 4px to 7px for the same reason: at 4px two
     * rounded borders an inch long read as one shape.
     *
     * The old note measured eight tabs
     * at ~780px against an 800px tablet - already at the edge before SC
     * and 3JS were added; the tablet is the tighter surface, not this one.
     */
    /* 2026-09-15 (#1174): "These tabs are too big. They're taking up all
     * the screen." Thirteen of them now - the rail has grown a tab a
     * night this week - and at 16px of padding and 11px text the column
     * ran the height of the glass. The padding is halved down the long
     * axis and the text set a point smaller; the tap target keeps its
     * width, because a rail you cannot hit is worse than a rail that is
     * tall. Measured against the tablet's 690px of CSS height: the column
     * was overflowing and scrolling, and now it does not. */
    '.pine-view-tab{background:#1c242c;color:#edf3f5;border:1px solid #35414c;',
    'border-right:none;border-radius:12px 0 0 12px;',
    /* 2026-09-15 (#1181): the vertical padding is the tab's HEIGHT -
     * the text runs down the tab, so padding-top and padding-bottom
     * are the two ends of the word and the horizontal padding is its
     * thickness. fit() writes the first and never touches the second,
     * because the second is the tap target. */
    'padding:var(--pine-tab-pad,4px) 11px;',
    /* The text cannot go below 12px: measured on the tablet, this rule
     * says font-size:10px and the WebView computes 12 - it enforces a
     * minimum font size and no stylesheet argues with that. So the height
     * comes out of the padding instead. Thirteen tabs at 50px overflowed
     * a 690px glass; at 42px with a 4px gap the column is 594px and fits
     * with room to spare. The horizontal padding is untouched, because
     * the width is the tap target. */
    /* #1345b: AND IT MUST SAY ITS OWN HEIGHT.
     *
     * This is the whole fault, and it is not flex at all. The desktop
     * shell's styles.css carries a bare element rule -
     *
     *     button { height: 36px; padding: 0 12px; }
     *
     * - and this rule never declared a height, so there was nothing to
     * override: specificity does not enter into it when only one rule
     * declares the property. Every tab was pinned to a 36px square, and
     * vertical text in a 36px box loses its word. Measured on the real
     * document: all nine tabs exactly 40x36, seven of them clipped -
     * SAMPLER needed 69px and was given 36.
     *
     * The tablet has no such element rule, which is precisely why the
     * rail looks right there and cramped here off the same stylesheet.
     * A rail that can be dropped into any document has to state the
     * dimensions it depends on rather than inherit them.
     */
    'height:auto;width:auto;min-height:0;min-width:0;',
    'flex:0 0 auto;white-space:nowrap;',
    'font-size:10px;letter-spacing:.06em;writing-mode:vertical-rl;',
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

  /* ------------------------------------------------- THE RAIL MEASURES
   * THE RAIL MEASURES THE GLASS IT IS ON (2026-09-15, #1181).
   *
   * The operator: "These tabs should be scale appropriate according to
   * the display that they're on. For example here they have room to be a
   * little bit bigger, but when they were on the tablet, they were just a
   * little bit too big. All they needed was to be scaled down by maybe
   * like ten percent. I want these tabs to be scaled appropriately to fit
   * the screen, but I just don't want them scaled so big that they also
   * encompass the corners where we have the hot corners at."
   *
   * Every size in this file up to tonight was a constant argued out
   * against one screen and then found wrong on the other - #1345 raised
   * the padding for the desktop, #1174 halved it for the tablet, and each
   * one made the other surface worse. The rail has grown a tab a night
   * this week, so the constant would have been wrong again by Thursday.
   * It measures instead.
   *
   * WHAT IS MEASURED. Each tab is laid out once at a known padding, and
   * the height that is left after subtracting that padding is the word
   * itself - a fixed length, because the text cannot shrink: the tablet's
   * WebView enforces a minimum font size of 12px and no stylesheet argues
   * with it (#1174). So the column is
   *
   *     sum(words) + 2 * pad * tabs + gap * (tabs - 1) + the rail's own
   *
   * and the only free number is the padding. It is solved for arithmetic-
   * ally from one layout pass rather than by setting-and-remeasuring,
   * which would reflow fifteen times on a tablet that cannot afford one.
   *
   * THE CORNERS. A tab sitting in a corner square swallows the swipe that
   * starts there - the rail is exempted from corner activation (#1166),
   * which is exactly why a tab in the corner kills the gesture rather
   * than passing it on. So the column is capped to the glass MINUS a
   * corner square at each end, and it is centred, so what is left is
   * symmetric and both corners stay clear.
   *
   * AND WHEN IT WILL NOT FIT. Thirteen tabs of 12px text are about 434px
   * of words alone; a 690px tablet less two 110px squares leaves 470,
   * and the rail would be scrolling before the padding reached zero. He
   * asked for ten percent smaller, not for a scrollbar. So the reserve
   * gives way before the tabs do: it steps down toward RESERVE_MIN, which
   * is still a band at the very corner wide enough to start a swipe in -
   * the gesture only needs its first touch inside the square and then
   * JUDGE_PX of travel. On the real tablet this lands at pad 3 and a
   * 556px column, which is the ten percent he asked for, with 56px of
   * corner left at each end. On the desk it lands near the top of the
   * range instead, which is the "room to be a little bit bigger".
   *
   * If even RESERVE_MIN will not hold it, the cap stays and the rail
   * scrolls, which is the one honest answer left: better a reachable
   * corner and a rail you scroll than a corner that does nothing.
   */

  var PAD_MIN = 2;          /* below this the border swallows the word */
  var PAD_MAX = 16;         /* #1345's desktop size, the biggest asked for */
  var GAP_MIN = 3;          /* under 3, two rounded borders read as one shape */
  var GAP_MAX = 8;
  var RESERVE_MIN = 56;     /* the corner band that must survive regardless */
  var PROBE_PAD = 4;        /* the padding the measuring pass is taken at */

  function cornerPx() {
    try {
      var n = root.PineHotCorners && root.PineHotCorners.CORNER_PX;
      if (typeof n === 'number' && n > 0) return n;
    } catch (err) { /* the rail does not depend on the corners existing */ }
    return 110;
  }

  function gapFor(pad) {
    return Math.max(GAP_MIN, Math.min(GAP_MAX, pad));
  }

  /* Pure, so it can be checked without a browser: the tallest padding at
   * which the column still fits, or PAD_MIN if none does. */
  function padThatFits(words, own, avail) {
    var n = words.length, i, sum = 0, pad, total;
    for (i = 0; i < n; i += 1) sum += words[i];
    for (pad = PAD_MAX; pad > PAD_MIN; pad -= 1) {
      total = sum + (2 * pad * n) + (gapFor(pad) * (n - 1)) + own;
      if (total <= avail) return pad;
    }
    return PAD_MIN;
  }

  function fit() {
    var rail = document.getElementById('pineViewRail');
    if (!rail) return null;
    var tabs = rail.querySelectorAll('.pine-view-tab');
    var n = tabs.length;
    if (!n) return null;

    /* One layout pass, at a known padding, with no cap in the way. */
    rail.style.setProperty('--pine-tab-pad', PROBE_PAD + 'px');
    rail.style.setProperty('--pine-rail-gap', PROBE_PAD + 'px');
    rail.style.setProperty('--pine-rail-max', 'none');

    var words = [], i, h;
    for (i = 0; i < n; i += 1) {
      h = tabs[i].offsetHeight || 0;
      /* A tab that has not been laid out yet measures 0, and a zero-length
       * word would make the solver promise room it does not have. Skip the
       * whole pass and let the observer below call again. */
      if (h <= 2 * PROBE_PAD) {
        rail.style.removeProperty('--pine-rail-max');
        return null;
      }
      words.push(h - (2 * PROBE_PAD));
    }

    /* The rail's own padding, from the stylesheet rather than a copy of
     * it - this file is not the only thing that has ever styled it. */
    var own = 8;
    try {
      var cs = root.getComputedStyle(rail);
      own = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    } catch (err) { own = 8; }

    var glass = root.innerHeight || 800;
    var corner = cornerPx();
    var reserve = corner, pad = PAD_MIN, avail = 0, step;

    /* Give the reserve away before the tabs, down to RESERVE_MIN. */
    for (step = 0; step < 40; step += 1) {
      avail = glass - (2 * reserve);
      pad = padThatFits(words, own, avail);
      if (pad > PAD_MIN || reserve <= RESERVE_MIN) break;
      reserve = Math.max(RESERVE_MIN, reserve - 6);
    }
    avail = Math.max(120, glass - (2 * reserve));

    rail.style.setProperty('--pine-tab-pad', pad + 'px');
    rail.style.setProperty('--pine-rail-gap', gapFor(pad) + 'px');
    rail.style.setProperty('--pine-rail-max', avail + 'px');

    var said = {tabs: n, glass: glass, reserve: reserve, pad: pad,
                gap: gapFor(pad), cap: avail,
                column: rail.scrollHeight, scrolls: rail.scrollHeight > avail + 1};
    rail.setAttribute('data-fit', pad + '/' + reserve + '/' + n);
    return said;
  }

  /* Refit when the glass changes, when the rail grows a tab, and once
   * after the first paint - the hot-corners and SC tabs are appended by
   * their own modules, whose evaluation order is not this file's to
   * decide (the kiosk injects them in its own order). */
  var fitSoon = null;
  function scheduleFit() {
    if (fitSoon) return;
    fitSoon = root.setTimeout(function () { fitSoon = null; try { fit(); } catch (err) {} }, 60);
  }

  function watchRail() {
    var rail = document.getElementById('pineViewRail');
    if (!rail) return;
    try {
      root.addEventListener('resize', scheduleFit);
      root.addEventListener('orientationchange', scheduleFit);
    } catch (err) { /* not fatal */ }
    try {
      if (root.MutationObserver) {
        new root.MutationObserver(scheduleFit).observe(rail, {childList: true});
      }
    } catch (err) { /* not fatal */ }
    /* Web fonts land after the first paint and change every word length. */
    try {
      if (document.fonts && document.fonts.ready && document.fonts.ready.then) {
        document.fonts.ready.then(scheduleFit);
      }
    } catch (err) { /* not fatal */ }
    scheduleFit();
  }

  root.PineRailFit = {fit: fit, _padThatFits: padThatFits, _gapFor: gapFor,
                      PAD_MIN: PAD_MIN, PAD_MAX: PAD_MAX,
                      RESERVE_MIN: RESERVE_MIN};

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

  /* #1193: A NAMED WAY TO TAKE THE VIEWS DOWN.
   *
   * closeAll() has existed since the rail did, and five call sites inside
   * this file use it. It had no name outside because nothing outside
   * needed one - until the desk's 3JS tab.
   *
   * MEASURED: on the desk a 3JS scene is promoted to full screen INSIDE
   * the controlFrame <webview>, and the rail's view hosts (#sampler,
   * #script, #slideshow and the rest) are siblings of that webview in the
   * SHELL document, sitting at z-index 2147483000. A scene that is
   * genuinely full screen in the panel is still completely covered if the
   * operator had SLIDES open when he pressed 3JS - the same "nothing was
   * broken, one number was three million too small" fault the z-index lift
   * in three-full.css was written for, arriving from the other side of the
   * boundary this time.
   *
   * On the tablet this cannot happen: there the scene and the view hosts
   * share one document and .p3-full sits at 2147483030, above them. So
   * this is called only on the desk road, and it is exported rather than
   * duplicated. */
  root.PineViewRail = {closeAll: closeAll};

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
      /* 2026-09-15 (#1175): "I have to press control R to get this tab to
       * work."
       *
       * Closing the rail's overlay is only half of the way back. On the
       * desktop this rail ADOPTS the shell's own <section class="view">
       * elements (#1344), and once `.open` comes off, what shows is
       * whatever the SHELL thinks is active - which is the view he last
       * chose from the shell's own nav, not the deck. So the glass did
       * not change and the only way home was a reload. TECH now asks the
       * shell for its main view as well; on the tablet there is no such
       * nav and this finds nothing, which is correct there. */
      try {
        var main = document.querySelector('nav.tabs .tab[data-view="control"]')
          || document.querySelector('.tab[data-view="control"]');
        if (main && !main.classList.contains('active')) main.click();
      } catch (err) { /* the rail is more important than the courtesy */ }
      tech.classList.add('on');
      setTimeout(function () { tech.classList.remove('on'); }, 400);
    });
    rail.appendChild(tech);

    for (var i = 0; i < VIEWS.length; i += 1) {
      (function (view) {
        /* The sampler already built its own host and handle before this
         * ran. Adopt it rather than building a second one. */
        if (!view.external) {
          /* #1344: ADOPT A HOST THAT IS ALREADY THERE.
           *
           * The desktop shell owns #script, #listen, #music,
           * #presentation and #sampler as its own <section class="view">
           * elements. Building a second element with the same id gives
           * getElementById the DESKTOP one - first in document order -
           * which has no `pine-view-host` class, so `.open` matches
           * nothing and the tab looks broken rather than missing.
           *
           * On the tablet nothing owns these ids, so this still builds
           * exactly what it always did. */
          var host = document.getElementById(view.id);
          if (host) {
            host.classList.add('pine-view-host');
            var bits = String(view.cls || '').split(/\s+/);
            for (var c = 0; c < bits.length; c += 1) {
              if (bits[c]) host.classList.add(bits[c]);
            }
          } else {
            host = make('section', view.id, 'pine-view-host ' + view.cls);
            document.body.appendChild(host);
          }
        }
        var tab = make('button', 'pineViewTab-' + view.id, 'pine-view-tab');
        tab.textContent = view.label;
        tab.addEventListener('click', function () {
          if (view.external) {
            /* Hand the sampler's own handle the press, so its repaint and
             * its `on` state keep working exactly as they did. */
            /* #1344: the tablet builds #pineSamplerTab; the desktop has
             * its own nav button instead. Either is a handle. */
            var handle = document.getElementById('pineSamplerTab')
              || document.getElementById('samplerTabBtn');
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

    /* 2026-09-15: THE DESK'S OWN TABS MUST BE ABLE TO COME BACK.
     *
     * "whenever I click the main tab, it doesn't take me back to the main
     *  tab anymore. It just stays where I am."
     *
     * On the desktop this rail ADOPTS the shell's own <section class="view">
     * elements (#1344) and shows one by adding `.open` - which is
     * position:fixed;inset:0 at z-index 2147483000, the whole glass. The
     * shell's own nav (renderer.js selectView) only toggles `.active` on
     * those same sections; it has never heard of `.open`, so a view opened
     * from the rail stayed over the deck and the Agent tab looked dead.
     *
     * Bound in the CAPTURE phase on the document so it runs before the
     * shell's own handler, and it only ever CLOSES - whatever the shell
     * then decides to show is its business. The rail's own tabs carry
     * `pine-view-tab`, so they are not this. */
    document.addEventListener('click', function (ev) {
      var node = ev.target;
      while (node && node !== document) {
        if (node.classList && node.classList.contains('pine-view-tab')) return;
        if (node.classList && node.classList.contains('tab')
            && node.getAttribute && node.getAttribute('data-view')) {
          closeAll();
          return;
        }
        node = node.parentNode;
      }
    }, true);

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

    /* THE SC STACK, AS A POP-UP.
     *
     * "...while also being able to access it as a pop up inside of Pinebox
     *  tab."
     *
     * A tab rather than a view host: pressing it opens a floating window
     * over whatever is already on screen, so the deck does not have to be
     * left to glance at the GPU. The same readouts live full-bleed on the
     * SLIDES tab and as their own application (SparkActivity / /spark);
     * this is the third door and the least disruptive one. */
    if (root.SparkOverlays && typeof root.SparkOverlays.popup === 'function') {
      try {
        var stack = make('button', 'pineViewTab-stack', 'pine-view-tab');
        stack.textContent = 'SC';
        stack.title = 'The SC stack, in a window over this';
        stack.addEventListener('click', function () {
          try {
            root.SparkOverlays.popup();
            stack.classList.toggle('on', root.SparkOverlays.isPopupOpen());
          } catch (err) { /* never take the rail down with it */ }
        });
        rail.appendChild(stack);
      } catch (err) { /* the rail is more important than the handle */ }
    }

    /* HOT CORNERS (2026-09-14). "I also want preferences ... for each of
     * the hot corners ... change these and set these and disable these."
     *
     * A tab on the same edge, opening the preference sheet as a pop-up
     * over whatever is showing: a master switch and one select per corner
     * (hot-corners.js). Built through the module's own railTab() so the
     * kiosk, whose injection order is its own, gets the same tab whether
     * this file or that one is evaluated first - both check the id. */
    if (root.PineHotCorners && typeof root.PineHotCorners.railTab === 'function') {
      try { root.PineHotCorners.railTab(); } catch (err) { /* the rail is more important than the handle */ }
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

    /* 2026-09-15 (#1181): and now it measures the glass it landed on. */
    try { watchRail(); } catch (err) { /* the rail is more important */ }

    return 'rail up with ' + (VIEWS.length + 1) + ' tabs';
  };
})(typeof window !== 'undefined' ? window : globalThis);
