/* EVERY 3JS EXPERIENCE, FULL SCREEN - ON THE TABLET *AND* ON THE DESK.
 *
 * "Make sure that every three JS experience in the sidebar I'm able to
 * access as a full screen interface that's fully interactive with an X in
 * the corner that is able to basically be an entire experience on the
 * screen instead of just a pop up so I'm able to use it more fluidly on the
 * tablet. Have a mobile capable version of each experience able to be used
 * full screen in addition to the popup."
 *
 * and, 2026-09-15, #1193:
 *
 * "also make sure the 3js scenes and tab works in the pinebox app"
 *
 * NOTHING IS REBUILT. The panel already keeps a register of its scenes -
 * `PINE_3JS`, published to its own window at app.py:164603, thirty-two
 * entries - and every entry carries exactly what this needs:
 *
 *     {key, label, open(), frame:{shade(), card, close(), onResize()}}
 *
 * `open()` puts the scene up as the panel's own modal; `shade()` hands back
 * the element it lives in; `onResize()` is how a scene is told its canvas
 * changed. So full screen is not a second copy of thirty-two experiences -
 * it is the panel's own modal, promoted, with the dialog chrome taken off
 * and the scene told to re-fit. A parallel set would be thirty-two things
 * to keep in step and thirty-two that drift.
 *
 * ----------------------------------------------------------------------
 * #1193: WHY THE DESK SAID "0 ON THIS STATION" AND WAITING NEVER HELPED.
 *
 * The operator's photograph: the 3JS tab open on the Pine Box desk, the
 * sheet reading "3JS experiences - 0 on this station" over "the panel has
 * not registered any scenes yet - give it a moment after the terminal
 * starts". It was never a timing problem. Measured, statically and
 * conclusively:
 *
 *   - this file reads the register off its OWN window: `root.PINE_3JS`.
 *   - the ONLY place in the entire tree that ever assigns that name is
 *     app.py:164603, `window.PINE_3JS = PINE_3JS;`, inside the station
 *     panel's own page. `grep -rn PINE_3JS desktop/renderer/` finds four
 *     hits and every one of them is a READ or a comment. Nothing in the
 *     desk shell writes it, ever.
 *   - on the desk the panel is NOT this document. index.html:542 embeds
 *     it as `<webview id="controlFrame">`, which is a separate renderer
 *     process with its own window object. index.html:846 loads THIS file
 *     into the shell, outside that webview.
 *
 * So `list()` asked the shell's window for a register that only ever
 * exists inside the webview, got undefined, and honestly reported zero. It
 * would have reported zero after an hour. This is the third fault of the
 * same family tonight - see pine-revive.js's note, "the broadcast this
 * application plays is NOT in this document" - and the cure is the same
 * one: prove things INSIDE the panel instead of guessing from the shell.
 *
 * ON THE TABLET the identical file works, and that is not luck: the kiosk
 * loads the panel itself and injects this bundle INTO it (ViewAssets.kt
 * line 70 lists three-full.js, line 124 evaluates the bundle in the panel's
 * WebView). Register and module share one window there. Same file, two
 * surfaces, and only one of them had the thing it reads.
 *
 * ----------------------------------------------------------------------
 * THE AWKWARD PART, AND THE SHAPE CHOSEN FOR IT.
 *
 * The register's entries carry FUNCTIONS - open(), shade(), close(),
 * onResize(). Functions cannot cross a webview boundary; only JSON can.
 * The shell can never hold an entry, so there is no version of this where
 * the shell "fetches the register and drives it".
 *
 * The shape chosen is THE MODULE GOES TO THE REGISTER, NOT THE REGISTER TO
 * THE MODULE. Everything that touches an entry lives in one self-contained
 * function, pineThreeCore(w) below, which closes over nothing outside
 * itself. It is used two ways:
 *
 *   - the register is in THIS window (tablet, or the panel opened direct):
 *     call it. Same document, same behaviour as before this change.
 *   - the register is not here (the desk shell): stringify it with
 *     Function.prototype.toString, evaluate it inside the controlFrame
 *     webview, and drive it by name - `window.__pineThreeCore.list()`
 *     comes back as an array of {key,label}, which IS JSON;
 *     `window.__pineThreeCore.show("booth")` does the whole open-and-
 *     promote inside the panel's own document and comes back as a STRING.
 *
 * Only JSON ever crosses. The scene is opened, promoted, re-fitted and
 * closed entirely inside the document that owns it. That is exactly the
 * road pine-revive.js already drives ("they are stringified and evaluated
 * INSIDE the panel; they must close over nothing in this file"), and this
 * file follows its rule to the letter.
 *
 * The chooser sheet stays in the SHELL, because the rail that opens it is
 * in the shell and a sheet inside the webview would sit under the desk's
 * own chrome. Only the sheet is here; every scene is over there.
 *
 * HOW THE SURFACE IS DETECTED, and why the test is trustworthy:
 *
 *     Array.isArray(root.PINE_3JS)
 *
 * evaluated at the moment of the call, not at load. It tests the exact
 * thing the direct road needs - the register, here, now - rather than a
 * proxy for it like the user agent, process.versions.electron or the
 * presence of a <webview> tag. Any surface that genuinely has the register
 * in its own window takes the direct road and is correct by construction;
 * anything else is asked over the bridge. A future build that loads the
 * panel directly in Electron would get the direct road with no edit here.
 * And because it is evaluated per call, the tablet cannot lose by asking
 * before the panel has published - see whyText('nowhere'), which says so
 * rather than silently taking the wrong road.
 *
 * WHAT "MOBILE CAPABLE" HAD TO MEAN IN PRACTICE. These scenes were written
 * against a desktop panel, and three things break on a 9-inch glass:
 *   - the dialog is sized in pixels and centred, so it is a small box in
 *     the middle of a big screen. Promoting it means overriding that, and
 *     the override has to beat inline styles, hence the !important rules
 *     rather than a class the scene can out-specify.
 *   - the canvas keeps the size it was first given. Every scene that can
 *     be told to re-fit is told, after a frame, and again on rotation -
 *     `onResize` exists on most entries for exactly this.
 *   - a modal with no visible way out is a trap on a device with no mouse
 *     and, in a kiosk, no Escape key. The X is added by this file rather
 *     than trusted to exist.
 */
(function (root) {
  'use strict';

  var HOST_ID = 'pineThreeFull';
  var CORE_KEY = '__pineThreeCore';
  var CORE_VERSION = 1193;

  /* ====================================================================
     THE CORE.

     EVALUATED IN WHICHEVER DOCUMENT OWNS THE REGISTER - this one on the
     tablet, the controlFrame webview's on the desk. It is sent across the
     boundary as its own source text, so the rules are absolute:

       * it must close over NOTHING outside itself. Not a constant, not a
         helper, not a stylesheet. Everything it needs is inside it.
       * it may only use globals that exist in a browser page.
       * it must be idempotent. The desk re-sends it before every ask,
         because the panel may have reloaded since the last one, and a
         re-install that dropped the open scene's bookkeeping would make
         the X stop working.

     Its whole outside surface is JSON in, JSON or a string out.
     ==================================================================== */
  function pineThreeCore(w) {
    'use strict';

    var VERSION = 1193;

    /* IDEMPOTENT, AND THE VERSION IS THE TEST. A bare `if (already)` would
     * leave a stale build installed in a panel that had been running since
     * before an update; comparing the version means a newer shell replaces
     * an older core and an equal one leaves the live scene alone. */
    if (w.__pineThreeCore && w.__pineThreeCore.VERSION === VERSION) {
      return 'already here';
    }

    /* THE PROMOTION RULES TRAVEL WITH THE CODE THAT USES THEM.
     *
     * #1193: these used to live in three-full.css. On the desk that
     * stylesheet is loaded into the SHELL (index.html:32) and the scene
     * being promoted is inside the webview, so every one of those rules
     * landed in a document with nothing to style - the scene would have
     * "opened full screen" and stayed a 700px dialog. Putting them in the
     * core means they arrive in the same document as the class names they
     * match, on both surfaces, and there is exactly one copy of them.
     *
     * (The `.pine-win` z-index lift stays in three-full.css. It is for the
     * TABLET, where the panel and the rail's view hosts share one document
     * and the panel's windows sat three million z-indexes below whatever
     * view was open. Inside the webview there are no view hosts to be
     * covered by, so the lift has nothing to do there.) */
    var CSS = [
      '.p3-full{position:fixed!important;inset:0!important;',
      'left:0!important;top:0!important;right:0!important;bottom:0!important;',
      'width:100vw!important;height:100vh!important;',
      'max-width:none!important;max-height:none!important;margin:0!important;',
      'border-radius:0!important;z-index:2147483030!important;',
      'background:#0b0f14!important;display:block!important;',
      'overflow:hidden!important;touch-action:none}',
      '.p3-full-card,.p3-full > .pine-win-body,.p3-full > .panel{',
      'position:absolute!important;inset:0!important;',
      'width:100%!important;height:100%!important;',
      'max-width:none!important;max-height:none!important;margin:0!important;',
      'border:0!important;border-radius:0!important;box-shadow:none!important;',
      'transform:none!important}',
      '.p3-full canvas{width:100%!important;height:100%!important}',
      'body.p3-on #pineViewRail,body.p3-on #pineConsoleLine,',
      'body.p3-on #pineSamplerTab{display:none!important}',
      'body.p3-on .pine-talk-dot{z-index:2147483090!important}',
      /* THE X. Thumb-sized, always the same corner, above the scene it
       * closes - the lesson from the lock screen, which covered its own
       * way out. FIXED, not absolute: it is a child of <body>, not of the
       * scene, for the eleven scenes that deleted it when it was not. */
      '.p3-exit{position:fixed;top:max(10px,env(safe-area-inset-top));',
      'right:max(12px,env(safe-area-inset-right));width:48px;height:48px;',
      'border:1px solid rgba(255,255,255,.3);border-radius:50%;',
      'background:rgba(0,0,0,.62);color:#edf3f5;font-size:18px;line-height:1;',
      'cursor:pointer;z-index:2147483035;',
      '-webkit-tap-highlight-color:transparent}'
    ].join('');

    try {
      if (!document.getElementById('p3CoreStyle')) {
        var style = document.createElement('style');
        style.id = 'p3CoreStyle';
        style.textContent = CSS;
        (document.head || document.documentElement).appendChild(style);
      }
    } catch (eStyle) { /* a scene with no styling still opens */ }

    var open = null;          /* the entry currently promoted */
    var shade = null;         /* the element we promoted */
    var exit = null;
    var before = null;        /* what was on screen before we asked */

    /* NO EMOJI ICONS - CARBON ONLY, and the panel's labels are full of
     * them: the register reads "\u{1F9E0} Dialogue Mind", "\u{1FA90} Mind
     * Topology", "\u{1F4BF} Album Stage". That is the panel's own styling
     * and this file is not going to edit thirty-two lines of app.py to
     * change it, but nothing here has to REPEAT it - the chooser carries
     * one Carbon cube beside its title and plain words on every tile.
     *
     * Only a LEADING run is taken, and only of characters that cannot
     * start a real label: pictographs, variation selectors, zero-width
     * joiners and the spaces after them. A label with nothing left after
     * the strip keeps its original, because a blank tile is worse than an
     * emoji one. Every label in the register today survives - "Station
     * flow" and "Rejected lines" never enter the loop at all. */
    function plain(label) {
      var s = String(label);
      var i = 0;
      while (i < s.length) {
        var c = (typeof s.codePointAt === 'function')
          ? s.codePointAt(i) : s.charCodeAt(i);
        var pictograph = (c >= 0x2000 && c <= 0x3300) || c >= 0x1F000;
        var joiner = (c === 0xFE0F || c === 0x200D);
        var space = (c === 32 || c === 9 || c === 160);
        if (!pictograph && !joiner && !space) break;
        i += (c > 0xFFFF ? 2 : 1);
      }
      var out = s.slice(i);
      return out || s;
    }

    /* ONLY {key,label} EVER LEAVES. The entries hold functions; this is
     * the JSON projection of them, and it is all the shell ever sees. */
    function list() {
      var reg = w.PINE_3JS;
      if (!Array.isArray(reg)) return [];
      var out = [];
      for (var i = 0; i < reg.length; i += 1) {
        var e = reg[i];
        if (!e || !e.key || e.key === 'off') continue;
        if (typeof e.open !== 'function') continue;
        out.push({key: String(e.key), label: plain(e.label || e.key)});
      }
      return out;
    }

    function entry(key) {
      var reg = w.PINE_3JS;
      if (!Array.isArray(reg)) return null;
      for (var i = 0; i < reg.length; i += 1) {
        if (reg[i] && String(reg[i].key) === String(key)) return reg[i];
      }
      return null;
    }

    function make(tag, cls, text) {
      var n = document.createElement(tag);
      if (cls) n.className = cls;
      if (text !== undefined && text !== null) n.textContent = text;
      return n;
    }

    /* WHERE THE SCENE'S ELEMENT IS.
     *
     * Most entries name it - `frame.shade()` - but not all: several are
     * just {key,label,open} with no frame at all (`mind` is one), and
     * those were the five that reported "it cannot be made full screen" in
     * the sweep while eleven others promoted cleanly.
     *
     * They are not un-promotable, they are just undeclared: the panel
     * builds each one through pineWin(), which gives the element the id
     * `pineWin-<key>`. So when the entry does not say where its element
     * is, it is looked up by the id the panel would have given it. */
    function elementFor(e) {
      if (e && e.frame && typeof e.frame.shade === 'function') {
        try {
          var named = e.frame.shade();
          if (named && named.classList) return named;
        } catch (err) { /* fall through to the id */ }
      }
      var byId = document.getElementById('pineWin-' + e.key);
      if (byId && byId.classList) return byId;

      /* LAST RESORT: WHATEVER JUST APPEARED.
       *
       * Six entries survived both roads above - crystal, shelf, slots,
       * asks, rejected, booth - because they build their own element with
       * their own id rather than going through pineWin(). Rather than
       * learn six more naming conventions that will become seven, the
       * screen is photographed before the scene is opened and whatever
       * full-size fixed element is NEW afterwards is the scene. It is the
       * same reasoning the id lookup used, one step more general. */
      if (before) {
        var candidates = document.querySelectorAll('div,section,dialog,aside');
        var best = null;
        for (var i = 0; i < candidates.length; i += 1) {
          var node = candidates[i];
          if (before.has(node)) continue;
          var cs = getComputedStyle(node);
          if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
          if (cs.display === 'none' || cs.visibility === 'hidden') continue;
          var box = node.getBoundingClientRect();
          /* Big enough to be a scene, not a tooltip or a toast. */
          if (box.width < 260 || box.height < 200) continue;
          if (!best || box.width * box.height >
            best.getBoundingClientRect().width * best.getBoundingClientRect().height) {
            best = node;
          }
        }
        if (best) return best;
      }
      return null;
    }

    function photograph() {
      before = new Set();
      var all = document.querySelectorAll('div,section,dialog,aside');
      for (var i = 0; i < all.length; i += 1) before.add(all[i]);
    }

    function promote(e) {
      if (!e) return false;
      var node = elementFor(e);
      if (!node || !node.classList) return false;

      shade = node;
      open = e;
      node.classList.add('p3-full');
      document.body.classList.add('p3-on');

      /* GUARDED. Not every entry has a frame at all - `manuals` threw
       * "Cannot read properties of undefined (reading 'card')" here,
       * because the element had been found by the generic fallback while
       * e.frame was still undefined. The lookup learned to cope with a
       * missing frame and this line had not. */
      if (e.frame && e.frame.card) {
        var card = node.querySelector(e.frame.card);
        if (card) card.classList.add('p3-full-card');
      }

      addExit(node, e);
      refit(e);
      return true;
    }

    function addExit(node, e) {
      if (exit && exit.parentNode) exit.parentNode.removeChild(exit);
      exit = make('button', 'p3-exit', '✕');
      exit.type = 'button';
      exit.title = 'Close this experience';
      exit.setAttribute('aria-label', 'Close this experience');
      exit.addEventListener('click', function (event) {
        event.stopPropagation();
        shut();
      });
      /* ON THE BODY, NOT INSIDE THE SCENE.
       *
       * It was appended to the promoted element, and measured across the
       * sweep it was MISSING from eleven of the thirty-one: those scenes
       * re-render their own children after opening and took the button
       * with them. A way out that a scene can delete is not a way out -
       * the same lesson the lock screen taught when it covered the
       * keyguard's own unlock gesture. The body is the one parent none of
       * them owns.
       *
       * #1193: on the desk this is also the only way out that is inside
       * the scene's own document. The shell's rail is deliberately left
       * showing over the webview as a second door, but this is the first. */
      document.body.appendChild(exit);
    }

    /* TELL THE SCENE ITS CANVAS CHANGED, more than once.
     *
     * A WebGL scene sized while its container was a 700px dialog keeps
     * that size until something tells it otherwise, and the promotion
     * happens in the same frame as the resize. So: after a frame, after a
     * beat, and on every rotation for as long as it is up. */
    function refit(e) {
      var tell = function () {
        try {
          if (e.frame && typeof e.frame.onResize === 'function') e.frame.onResize();
        } catch (err) { /* a scene that will not re-fit still shows */ }
        /* Some scenes only listen to the window. */
        try { w.dispatchEvent(new Event('resize')); } catch (err2) { /* old engine */ }
      };
      try {
        requestAnimationFrame(function () { requestAnimationFrame(tell); });
      } catch (err3) { /* no frames here; the timers below still fire */ }
      setTimeout(tell, 260);
      setTimeout(tell, 900);
    }

    function onTurn() {
      if (open) refit(open);
    }

    function shut() {
      var e = open;
      var was = shade;
      if (shade && shade.classList) {
        shade.classList.remove('p3-full');
        var card = shade.querySelector('.p3-full-card');
        if (card) card.classList.remove('p3-full-card');
      }
      if (exit && exit.parentNode) exit.parentNode.removeChild(exit);
      exit = null;
      document.body.classList.remove('p3-on');
      shade = null;
      open = null;
      if (e && e.frame && typeof e.frame.close === 'function') {
        try { e.frame.close(); } catch (err) { /* already gone */ }
      } else if (was && was.parentNode) {
        /* An entry with no frame has no close() either. The panel's
         * windows carry their own close control; press it if it is there,
         * and take the window out if it is not - leaving a promoted window
         * behind with its chrome stripped would be worse than either. */
        var own = was.querySelector('.pine-win-close, [data-close], .close');
        if (own && typeof own.click === 'function') own.click();
        else was.parentNode.removeChild(was);
      }
      return 'closed';
    }

    /* WHAT IS UP, AS JSON. The desk polls this across the bridge while it
     * believes a scene is open - it is how the shell learns that the
     * operator pressed the X over there. See watch() in the shell half. */
    function state() {
      return {full: !!open, key: open ? String(open.key) : '', VERSION: VERSION};
    }

    /**
     * Open an experience and give it the whole screen.
     *
     * The panel's own `open()` is called first - it is what builds the
     * scene - and the result is promoted a beat later, because a modal
     * that has not been added to the document yet cannot be promoted.
     *
     * Always resolves, never rejects, and always with a STRING: the key
     * when it worked, a sentence when it did not. That is not politeness,
     * it is the bridge contract - a rejected promise inside a webview
     * reaches the shell as an opaque failure with no sentence in it.
     */
    function show(key) {
      var e = entry(key);
      if (!e) return Promise.resolve('no such experience: ' + key);
      if (open && open.key !== e.key) shut();
      photograph();
      return Promise.resolve()
        .then(function () { return e.open(); })
        .then(function () {
          /* WAIT FOR THE SCENE TO EXIST BEFORE PROMOTING IT.
           *
           * A single retry at 500 ms was not enough: measured, `phone`
           * promoted first time and `rapassembly` reported "it cannot be
           * made full screen" because its modal had not been built yet -
           * several of these fetch three.js on first open, which is a
           * network round trip before there is any element to promote.
           *
           * So it asks repeatedly for a few seconds and gives up with a
           * sentence rather than a silence. The scene is OPEN either way;
           * only the promotion is in doubt, and the message says so.
           *
           * #1193: this patience is now also what the desk waits on.
           * Sixteen tries at 250ms is four seconds INSIDE the panel, so
           * the shell's own deadline on the ask has to be comfortably
           * longer than that or it would call a slow three.js fetch a
           * dead panel. It is set to thirty seconds - see ask(). */
          return new Promise(function (done) {
            var tries = 0;
            (function attempt() {
              if (promote(e)) return done(String(e.key));
              tries += 1;
              if (tries > 16) {
                return done(plain(e.label || e.key) + ' opened, but it cannot be made '
                  + 'full screen on this build - it is up as a window');
              }
              setTimeout(attempt, 250);
            })();
          });
        }, function (err) {
          return 'that experience would not open: ' + ((err && err.message) || err);
        });
    }

    try {
      w.addEventListener('resize', onTurn);
      if (w.screen && w.screen.orientation
        && typeof w.screen.orientation.addEventListener === 'function') {
        w.screen.orientation.addEventListener('change', onTurn);
      }
    } catch (eWire) { /* a page with no window events still promotes */ }

    w.__pineThreeCore = {
      VERSION: VERSION,
      list: list,
      show: show,
      close: shut,
      state: state
    };
    return 'installed';
  }

  /* The core's own source, ready to be evaluated in another document. No
   * build step: this project ships its renderer files raw, so toString()
   * gives back real source with the comments the operator reads in it. */
  var CORE_SOURCE = '(' + pineThreeCore.toString() + ')(window);';

  /* ====================================================================
     WHICH WORLD AM I IN.
     ==================================================================== */

  /* THE ONE TEST, taken fresh every time it is asked.
   *
   * Not the user agent, not process.versions.electron, not "is there a
   * <webview> here" - all of those are proxies that can be right about the
   * device and wrong about the document. This asks the only question that
   * decides anything: is the register in reach of a plain function call?
   * On the tablet the kiosk injected this file INTO the panel, so it is.
   * In the desk shell it never can be, because nothing outside the panel's
   * own page ever assigns that name. */
  function registerIsHere() {
    return Array.isArray(root.PINE_3JS);
  }

  function localCore() {
    var have = root[CORE_KEY];
    if (have && have.VERSION === CORE_VERSION) return have;
    try { pineThreeCore(root); } catch (err) { return null; }
    var made = root[CORE_KEY];
    return (made && made.VERSION === CORE_VERSION) ? made : null;
  }

  /* THE PANEL FRAME.
   *
   * controlFrame by name first - it is the one that carries the station
   * panel, and renderer.js has always driven it by that id - then any
   * other loaded webview, so a rearranged shell still finds a panel rather
   * than reporting none. A <webview> with no src has loaded nothing and is
   * not worth asking. */
  function panelFrame() {
    var d = root.document;
    if (!d || typeof d.querySelectorAll !== 'function') return null;
    var all;
    try { all = d.querySelectorAll('webview'); } catch (err) { return null; }
    var spare = null;
    for (var i = 0; i < all.length; i += 1) {
      var f = all[i];
      if (!f || typeof f.executeJavaScript !== 'function') continue;
      if (String(f.id || '') === 'controlFrame') return f;
      if (!spare && f.src) spare = f;
    }
    return spare;
  }

  /* ====================================================================
     THE BRIDGE.

     executeJavaScript is asynchronous and returns a promise, and a webview
     that is mid-navigation can leave that promise outstanding for ever.
     Every ask therefore carries a deadline and always settles - "the panel
     did not answer" is an answer; "the button never came back" is not.
     ==================================================================== */

  /* WITH the core: use this for anything that needs the module to be there
   * - it installs it first, idempotently, so a panel that reloaded five
   * seconds ago is cured by the next press rather than by a restart. */
  function wrapInstalling(expr) {
    return '(function(){"use strict";try{' + CORE_SOURCE + '}catch(e){'
      + 'return {p3err:"the station panel would not take the 3JS module: "'
      + '+String((e&&e.message)||e)};}'
      + 'try{return ' + expr + ';}catch(e2){'
      + 'return {p3err:String((e2&&e2.message)||e2)};}})()';
  }

  /* WITHOUT the core: use this when the ABSENCE of the core is the fact
   * being measured. The watcher below depends on this distinction - if it
   * re-installed before looking, a panel that had reloaded and dropped the
   * scene would answer "nothing is up" and be indistinguishable from the
   * operator having pressed the X. */
  function wrapBare(expr) {
    return '(function(){"use strict";try{return ' + expr + ';}catch(e){'
      + 'return {p3err:String((e&&e.message)||e)};}})()';
  }

  function ask(expr, ms, bare) {
    var frame = panelFrame();
    if (!frame) return Promise.resolve({ok: false, why: 'no-frame'});
    var going;
    try {
      going = frame.executeJavaScript(bare ? wrapBare(expr) : wrapInstalling(expr));
    } catch (err) {
      return Promise.resolve({ok: false, why: 'threw',
        detail: String((err && err.message) || err)});
    }
    if (!going || typeof going.then !== 'function') {
      return Promise.resolve({ok: true, value: going});
    }
    return new Promise(function (done) {
      var settled = false;
      var timer = setTimeout(function () {
        if (settled) return;
        settled = true;
        done({ok: false, why: 'slow'});
      }, ms || 8000);
      going.then(function (value) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (value && typeof value === 'object' && typeof value.p3err === 'string') {
          done({ok: false, why: 'threw', detail: value.p3err});
          return;
        }
        done({ok: true, value: value});
      }, function (err) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        done({ok: false, why: 'rejected',
          detail: String((err && err.message) || err)});
      });
    });
  }

  /* DEGRADE HONESTLY, AND SAY WHICH THING HAPPENED.
   *
   * "A silent empty grid is what sent the operator here." Each of these is
   * a different fault with a different cure, so each gets its own sentence
   * rather than one shrug covering all of them. */
  function whyText(res) {
    if (res.why === 'nowhere') {
      return 'the 3JS register is not in this page and there is no station '
        + 'panel frame to ask - if the terminal has only just started, the '
        + 'panel publishes it a moment after it loads';
    }
    if (res.why === 'no-frame') {
      return 'this window has no station panel frame - the 3JS scenes live '
        + 'in the panel, and the desk shows the panel in a frame it could '
        + 'not find here';
    }
    if (res.why === 'slow') {
      return 'the station panel did not answer in time - it is there but '
        + 'busy or still loading; try again in a moment';
    }
    if (res.why === 'rejected') {
      return 'the station panel could not be reached'
        + (res.detail ? ' (' + res.detail + ')' : '');
    }
    return 'the station panel refused the ask'
      + (res.detail ? ' (' + res.detail + ')' : '');
  }

  /* ====================================================================
     THE FRAME CARRIER, LIFTED OVER WHATEVER TAB HE IS ON.

     #1193b: "The 3JS pop-up should be able to pop up on any of these tabs
     in the application instead of just going to the main tab."

     The first cut of #1193 called PineViewRail.closeAll() before
     promoting. That is a correct cure for "the scene is invisible" and the
     wrong one for "I was in the middle of something": it took him off
     SCRIPT or SLIDES and left him on the panel when the scene closed.

     WHAT IS ACTUALLY IN THE WAY, measured rather than assumed, and it is
     two different things depending on which tab he is on:

       * ON A RAIL PANE (SAMPLER, SCRIPT, LISTEN, MUSIC, PRESENT, SLIDES):
         the control section is still `.active`, so it is DISPLAYED and
         merely COVERED. rail.js gives the pane `.pine-view-host`, which is
         position:fixed;inset:0;z-index:2147483000 - the whole glass over
         the top of it.

       * ON ONE OF THE SHELL'S OWN NAV TABS (Radio, System2, Overview,
         Logs, Settings, Guide, Terminal): the control section is HIDDEN
         outright. styles.css:1069 is `.view{display:none}` and :1070 is
         `.view.active{display:block}`, and renderer.js selectView (881)
         toggles that class. No amount of z-index reaches a display:none
         element.

     So stacking alone is half the job, and the other half is making the
     carrier visible and full-bleed for the duration.

     WHAT IS *NOT* TOUCHED, deliberately: the `active` class, and therefore
     the shell's `currentView`. Everything here is written as INLINE style,
     which beats the stylesheet's class rules without lying to the shell
     about which view it is on. renderer.js keeps its own bookkeeping, its
     nav keeps working, and when this puts the styles back the DOM is
     exactly what it was.

     AND EVERY PROPERTY IS RECORDED BEFORE IT IS WRITTEN, individually,
     and restored from that record - never from a guess about what it
     "should" have been, and never by clearing the whole style attribute,
     which would throw away the rail's own --pine-tab-pad and whatever else
     another module had put there. That rule is not invented here: it is
     the one the mute taught, when a value was assumed rather than
     remembered and ended up written onto the wrong element.
     ==================================================================== */

  /* Above the rail's view hosts (2147483000), below everything that was
   * already above the rail - the chooser sheet at 2147483040, the talk dot
   * and the trace popup. The rail goes one higher than the carrier so it
   * stays pressable over the scene: a way out he can always see. */
  var LIFT_CARRIER = 2147483002;
  var LIFT_RAIL = 2147483003;
  /* The strip the rail occupies. .pine-view-host reserves exactly this
   * (rail.js: `padding-right:34px`) so an open pane does not run under the
   * tabs; a lifted carrier must reserve it too, or the rail would sit on
   * top of the panel's own X, which lives at the top right of the scene. */
  var RAIL_STRIP = '34px';

  var CARRIER_PROPS = ['display', 'position', 'left', 'top', 'right',
    'bottom', 'width', 'height', 'margin', 'padding', 'overflow', 'zIndex'];
  var FRAME_PROPS = ['display', 'width', 'height'];
  var RAIL_PROPS = ['zIndex'];

  var lifted = null;

  function stash(el, props) {
    var rec = {el: el, was: {}}, i, had;
    for (i = 0; i < props.length; i += 1) {
      had = el.style[props[i]];
      /* A real CSSStyleDeclaration reads an unset property as the empty
       * string, and assigning the empty string back removes it - so the
       * record says "there was nothing here" as faithfully as it says a
       * value. The coercion is for anything that is not a real one:
       * assigning undefined to a style property writes the literal word
       * "undefined" into the declaration, which would be a restore that
       * broke the thing it was restoring. */
      rec.was[props[i]] = (typeof had === 'string') ? had : '';
    }
    return rec;
  }

  function putBack(rec) {
    var k;
    if (!rec) return;
    for (k in rec.was) {
      if (!Object.prototype.hasOwnProperty.call(rec.was, k)) continue;
      /* '' is what an absent inline property reads as, and assigning ''
       * removes the declaration. So this restores "there was nothing here"
       * as faithfully as it restores a value. */
      try { rec.el.style[k] = rec.was[k]; } catch (err) { /* keep going */ }
    }
  }

  /* The element the shell shows and hides - the <section class="view">
   * the webview sits in - found by walking up from the frame rather than
   * by hard-coding #control, so a rearranged shell lifts the right thing.
   * If nothing up the tree is a view, the frame is its own carrier. */
  function carrierOf(frame) {
    var node = frame ? frame.parentNode : null;
    while (node && node.classList) {
      if (node.classList.contains('view')) return node;
      node = node.parentNode;
    }
    return frame;
  }

  function railEl() {
    try {
      if (root.PineViewRail && typeof root.PineViewRail.railEl === 'function') {
        return root.PineViewRail.railEl();
      }
    } catch (err) { /* fall through */ }
    return document.getElementById('pineViewRail');
  }

  function lift(frame) {
    if (lifted) return lifted;
    var carrier = carrierOf(frame);
    var rail = railEl();
    var tab = document.getElementById('pineViewTab-3js');

    lifted = {
      carrier: carrier ? stash(carrier, CARRIER_PROPS) : null,
      frame: frame ? stash(frame, FRAME_PROPS) : null,
      rail: rail ? stash(rail, RAIL_PROPS) : null,
      tab: tab,
      tabWasOn: !!(tab && tab.classList && tab.classList.contains('on'))
    };

    if (carrier) {
      carrier.style.display = 'block';
      carrier.style.position = 'fixed';
      carrier.style.left = '0px';
      carrier.style.top = '0px';
      /* Only when there IS a rail to keep clear of. A shell without one
       * would otherwise get a 34px strip of nothing down the right. */
      carrier.style.right = rail ? RAIL_STRIP : '0px';
      carrier.style.bottom = '0px';
      /* auto, not 100%: the four insets are what size it, and a width of
       * 100% would put it back under the rail strip reserved above. */
      carrier.style.width = 'auto';
      carrier.style.height = 'auto';
      carrier.style.margin = '0px';
      carrier.style.padding = '0px';
      carrier.style.overflow = 'hidden';
      carrier.style.zIndex = String(LIFT_CARRIER);
    }
    if (frame && frame.style) {
      /* .frame-view.active is what normally gives the webview its height,
       * and that rule needs the class this deliberately does not touch. */
      frame.style.display = 'flex';
      frame.style.width = '100%';
      frame.style.height = '100%';
    }
    if (rail) rail.style.zIndex = String(LIFT_RAIL);
    if (tab && tab.classList) tab.classList.add('on');
    return lifted;
  }

  function drop() {
    var rec = lifted;
    if (!rec) return false;
    lifted = null;
    putBack(rec.carrier);
    putBack(rec.frame);
    putBack(rec.rail);
    if (rec.tab && rec.tab.classList && !rec.tabWasOn) {
      rec.tab.classList.remove('on');
    }
    return true;
  }

  /* ====================================================================
     THE ONE API, THE SAME SHAPE ON BOTH SURFACES.

     list() and show() are asynchronous on BOTH roads, even though the
     local road could answer synchronously. One shape means the chooser
     below has no idea which surface it is painting, which is the only way
     this stays honest when a third surface arrives.
     ==================================================================== */

  var inflight = '';        /* the key currently being opened, '' if none */
  var believeOpen = '';     /* what the shell believes is up in the panel */
  var lastNote = '';        /* the last honest sentence, for the next sheet */
  var watcher = 0;

  function list() {
    if (registerIsHere()) {
      var core = localCore();
      if (!core) {
        return Promise.resolve({ok: false, where: 'here', rows: [],
          why: 'the 3JS module would not install in this page'});
      }
      return Promise.resolve({ok: true, where: 'here', rows: core.list()});
    }
    if (!panelFrame()) {
      return Promise.resolve({ok: false, where: 'nowhere', rows: [],
        why: whyText({why: 'nowhere'})});
    }
    return ask('window.__pineThreeCore.list()', 9000).then(function (res) {
      if (!res.ok) {
        return {ok: false, where: 'panel', rows: [], why: whyText(res)};
      }
      var rows = Array.isArray(res.value) ? res.value : [];
      return {ok: true, where: 'panel', rows: rows};
    });
  }

  /* THE DOUBLE PRESS.
   *
   * executeJavaScript is asynchronous, and the slowest scenes here take
   * four seconds inside the panel before they even report. Two presses in
   * that window used to mean two opens racing, and the panel's own show()
   * closes whatever is up before opening the next - so the second press
   * could tear down the scene the first one was still trying to promote,
   * and the retry loop would then promote an element that had been
   * removed.
   *
   * One at a time, and say so. The chooser also disables every tile while
   * one is in flight, but the guard is here and not only there because the
   * rail and the hot corners can both call show() directly. */
  function show(key) {
    key = String(key);
    if (inflight) {
      return Promise.resolve(inflight === key
        ? 'still opening that one - give it a moment'
        : 'one at a time - the last one is still opening');
    }
    inflight = key;
    var settle = function (said) {
      inflight = '';
      return said;
    };

    if (registerIsHere()) {
      var core = localCore();
      if (!core) {
        inflight = '';
        return Promise.resolve('the 3JS module would not install in this page');
      }
      return core.show(key).then(function (said) {
        believeOpen = (String(said) === key) ? key : '';
        lastNote = (String(said) === key) ? '' : String(said);
        return settle(String(said));
      }, function (err) {
        return settle('that experience would not open: '
          + String((err && err.message) || err));
      });
    }

    var frame = panelFrame();
    if (!frame) {
      inflight = '';
      lastNote = whyText({why: 'nowhere'});
      return Promise.resolve(lastNote);
    }

    /* A CARRIER WITH NO src HAS NOTHING TO LIFT. loadFrames() only gives
     * a webview its src when its view is the current one (renderer.js
     * 958-978); the control frame gets one at boot because currentView
     * starts at "control" (renderer.js:23), but a shell that never loaded
     * it would otherwise be lifted blank over his tab. */
    if (!frame.src) {
      inflight = '';
      lastNote = 'the station panel has not loaded in this window yet - '
        + 'open the Pine Box tab once and it will be there';
      return Promise.resolve(lastNote);
    }

    /* OVER THE TAB HE IS ON, NOT INSTEAD OF IT. See the lift block above:
     * nothing is closed, the carrier is brought forward and made
     * full-bleed, and everything written is recorded first. */
    lift(frame);

    return ask('window.__pineThreeCore.show(' + JSON.stringify(key) + ')', 30000)
      .then(function (res) {
        if (!res.ok) {
          drop();
          lastNote = whyText(res);
          return settle(lastNote);
        }
        var said = String(res.value === null || res.value === undefined
          ? '' : res.value);
        if (said === key) {
          believeOpen = key;
          lastNote = '';
          watch();
        } else {
          /* ANYTHING SHORT OF A PROMOTION PUTS HIM BACK. The scene may
           * genuinely be up over there as a window - that is what "it is
           * up as a window" means - but the lift is for a FULL SCREEN
           * scene, and holding his tab hostage for a window he cannot see
           * full is the outcome that is worse than doing nothing. The note
           * tells him it is up; the Pine Box tab is one press away. */
          believeOpen = '';
          drop();
          lastNote = said;
        }
        return settle(said);
      });
  }

  /* THE PANEL RELOADING UNDERNEATH AN OPEN SCENE.
   *
   * The shell cannot see into the webview, so after a successful open it
   * holds nothing but a belief. Three things can end a scene over there
   * and the shell must tell them apart:
   *
   *   1. the operator pressed the X in the panel  -> the core answers and
   *      `full` is false. Ordinary. No note.
   *   2. the panel navigated or reloaded          -> the core is GONE,
   *      because a new document has none. The scene went with it, and the
   *      sheet says so the next time it opens.
   *   3. the panel stopped answering at all       -> a deadline or a
   *      rejection, which is a different sentence again.
   *
   * This is deliberately a BARE ask: wrapInstalling would put the core
   * back before looking, and a freshly installed core reports "nothing is
   * up", which is case 1's answer given for case 2's reason. The
   * distinction is the whole reason there are two wrappers.
   *
   * #1193b: ALL THREE PATHS CALL drop(). The carrier is lifted over
   * whatever tab he was on, so a scene that ends without the stacking
   * being put back leaves him looking at the panel over the top of the
   * Script view - which is worse than the fault this replaced. There is no
   * branch out of this watcher that does not restore.
   *
   * The poll is 900ms rather than the 2s it started at, for the same
   * reason: the X is pressed inside the panel and the shell learns about
   * it only here, so the interval is how long his tab stays covered after
   * he has closed the scene. */
  function watch() {
    if (watcher) return;
    watcher = setInterval(function () {
      if (!believeOpen) {
        drop();
        clearInterval(watcher);
        watcher = 0;
        return;
      }
      ask('window.__pineThreeCore ? window.__pineThreeCore.state() : null',
        6000, true).then(function (res) {
        if (!believeOpen) return;
        if (!res.ok) {
          /* 3. unreachable. */
          believeOpen = '';
          drop();
          lastNote = 'the station panel stopped answering while a scene was '
            + 'up - ' + whyText(res);
          clearInterval(watcher);
          watcher = 0;
          return;
        }
        if (!res.value) {
          /* 2. reloaded: the core went with the old document. */
          believeOpen = '';
          drop();
          lastNote = 'the station panel reloaded and took the scene with it - '
            + 'pick it again and it will open in the new page';
          clearInterval(watcher);
          watcher = 0;
          return;
        }
        if (!res.value.full) {
          /* 1. the X, pressed over there. Ordinary, and no note. */
          believeOpen = '';
          drop();
          lastNote = '';
          clearInterval(watcher);
          watcher = 0;
        }
      });
    }, 900);
  }

  function shutScene() {
    if (registerIsHere()) {
      /* The tablet lifts nothing, so drop() has nothing to put back - it
       * returns false and this is a no-op there, by construction rather
       * than by a surface test. */
      var core = localCore();
      believeOpen = '';
      drop();
      if (core) { try { core.close(); } catch (err) { /* already gone */ } }
      return Promise.resolve('closed');
    }
    believeOpen = '';
    /* The stacking goes back BEFORE the ask, not after it: if the panel
     * has stopped answering, the ask will take nine seconds to say so and
     * his tab must not be covered for those nine seconds. */
    drop();
    return ask('window.__pineThreeCore ? window.__pineThreeCore.close() '
      + ': "nothing was up"', 9000, true).then(function (res) {
      return res.ok ? String(res.value) : whyText(res);
    });
  }

  /* Kept synchronous: rail.js and the hot corners have always been able to
   * ask this without waiting. On the desk it is the shell's belief, which
   * watch() keeps within two seconds of the truth. */
  function isFull() {
    if (registerIsHere()) {
      var core = root[CORE_KEY];
      if (!core) return false;
      try { return !!core.state().full; } catch (err) { return false; }
    }
    return !!believeOpen;
  }

  /* ====================================================================
     THE CHOOSER - the only part that stays in this document on the desk.
     ==================================================================== */

  var sheet = null;

  function make(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  /* One Carbon glyph, or nothing - never a character standing in for one.
   * The same guard hot-corners.js uses: a bundle without pine-icons.js
   * loses the picture and keeps the words. */
  function glyph(name) {
    var out = '';
    try {
      if (typeof root.pineIcon === 'function') out = root.pineIcon(name);
    } catch (err) { out = ''; }
    return out || '';
  }

  function paint(into, got) {
    var head = make('div', 'p3-head');
    var title = make('b', '');
    var mark = glyph('c:cube');
    if (mark) {
      var holder = make('span', 'p3-mark');
      holder.innerHTML = mark;
      title.appendChild(holder);
    }
    title.appendChild(make('span', '', '3JS experiences'));
    head.appendChild(title);

    /* THE COUNT MUST BE THE TRUE ONE. It read "0 on this station" for a
     * station with thirty-two of them, because the shell was counting its
     * own window. When the count cannot be known it now says THAT instead
     * of saying zero - a number nobody can stand behind is worse than
     * none, and zero is the number that sent the operator here. */
    head.appendChild(make('i', '', got.ok
      ? (got.rows.length + ' on this station'
        + (got.where === 'panel' ? ', in the panel' : ''))
      : 'could not be counted'));
    into.appendChild(head);

    if (!got.ok) {
      into.appendChild(make('p', 'p3-dim', String(got.why || 'unknown')));
    } else if (!got.rows.length) {
      into.appendChild(make('p', 'p3-dim',
        got.where === 'panel'
          ? 'the station panel answered, and it has registered no scenes '
            + 'yet - it publishes them a moment after it loads'
          : 'the panel has not registered any scenes yet - give it a moment '
            + 'after the terminal starts'));
    }

    var note = make('p', 'p3-note', lastNote || '');
    var grid = make('div', 'p3-grid');
    var tiles = [];

    var pick = function (row) {
      var b = make('button', 'p3-pick');
      b.type = 'button';
      b.appendChild(make('b', '', row.label));
      b.addEventListener('click', function (event) {
        event.stopPropagation();
        /* EVERY tile goes down, not just this one: the guard in show()
         * refuses a second key while one is in flight, and a tile that
         * looks pressable but is not is exactly what makes an operator
         * press it again. */
        var i;
        for (i = 0; i < tiles.length; i += 1) tiles[i].disabled = true;
        note.textContent = 'opening ' + row.label + '...';
        show(row.key).then(function (said) {
          var j;
          for (j = 0; j < tiles.length; j += 1) tiles[j].disabled = false;
          if (String(said) === String(row.key)) {
            if (sheet === into) { into.remove(); sheet = null; }
            return;
          }
          note.textContent = String(said);
        });
      });
      tiles.push(b);
      grid.appendChild(b);
    };

    for (var i = 0; i < got.rows.length; i += 1) pick(got.rows[i]);
    into.appendChild(grid);
    into.appendChild(note);

    /* A SECOND WAY OUT, FROM THIS SIDE. The X lives in the panel's own
     * document; if a scene ever re-renders over it, the rail is still here
     * and this closes what is up from the shell. */
    if (isFull()) {
      var drop = make('button', 'p3-close', 'Close what is up');
      drop.type = 'button';
      drop.addEventListener('click', function (event) {
        event.stopPropagation();
        drop.disabled = true;
        shutScene().then(function (said) {
          drop.disabled = false;
          note.textContent = String(said);
        });
      });
      into.appendChild(drop);
    }

    var shutBtn = make('button', 'p3-close', 'Close');
    shutBtn.type = 'button';
    shutBtn.addEventListener('click', function (event) {
      event.stopPropagation();
      if (sheet === into) { into.remove(); sheet = null; }
    });
    into.appendChild(shutBtn);
  }

  function chooser() {
    if (sheet) { sheet.remove(); sheet = null; return; }
    var mine = make('div', 'p3-sheet');
    sheet = mine;

    /* SOMETHING WHILE IT ASKS. The list is a round trip into another
     * renderer process now; an empty box for half a second reads exactly
     * like the empty box this whole change is about. */
    var waiting = make('div', 'p3-head');
    waiting.appendChild(make('b', '', '3JS experiences'));
    waiting.appendChild(make('i', '', 'asking the panel...'));
    mine.appendChild(waiting);

    document.body.appendChild(mine);
    if (root.PineDismiss) {
      root.PineDismiss.watch(mine, function () {
        if (sheet === mine) { mine.remove(); sheet = null; }
      }, []);
    }

    list().then(function (got) {
      /* The operator may have closed it, or pressed the tab twice, while
       * we were asking. The sheet that comes back is only allowed to paint
       * itself if it is still the one on screen. */
      if (sheet !== mine) return;
      if (typeof mine.replaceChildren === 'function') mine.replaceChildren();
      else mine.innerHTML = '';
      paint(mine, got);
    });
  }

  var wired = false;
  function start() {
    if (wired) return;
    wired = true;
    /* On a surface that owns the register, install the core now so the
     * promotion stylesheet and the rotation listener are in place before
     * the first press. On the desk there is nothing to install here - the
     * core goes across the bridge on the first ask, and goes again after
     * every panel reload. */
    if (registerIsHere()) { localCore(); }
  }

  root.PineThreeFull = {
    start: start,
    list: list,          /* -> Promise<{ok, where, rows:[{key,label}], why}> */
    show: show,          /* -> Promise<string> */
    close: shutScene,    /* -> Promise<string> */
    chooser: chooser,
    isFull: isFull,
    HOST_ID: HOST_ID,
    /* For the tests and for a console: the core itself, and the exact
     * source that is evaluated inside the panel. */
    _core: pineThreeCore,
    _source: function () { return CORE_SOURCE; },
    _registerIsHere: registerIsHere,
    _frame: panelFrame,
    _lift: lift,
    _drop: drop,
    _lifted: function () { return !!lifted; }
  };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineThreeFull;
  }
})(typeof window !== 'undefined' ? window : globalThis);
