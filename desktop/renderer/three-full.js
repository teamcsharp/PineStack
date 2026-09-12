/* EVERY 3JS EXPERIENCE, FULL SCREEN, ON THE TABLET.
 *
 * "Make sure that every three JS experience in the sidebar I'm able to
 * access as a full screen interface that's fully interactive with an X in
 * the corner that is able to basically be an entire experience on the
 * screen instead of just a pop up so I'm able to use it more fluidly on the
 * tablet. Have a mobile capable version of each experience able to be used
 * full screen in addition to the popup."
 *
 * NOTHING IS REBUILT. The panel already keeps a register of its scenes -
 * `PINE_3JS` (app.py:138894), nineteen of them - and every entry carries
 * exactly what this needs:
 *
 *     {key, label, open(), frame:{shade(), card, close(), onResize()}}
 *
 * `open()` puts the scene up as the panel's own modal; `shade()` hands back
 * the element it lives in; `onResize()` is how a scene is told its canvas
 * changed. So full screen is not a second copy of nineteen experiences - it
 * is the panel's own modal, promoted, with the dialog chrome taken off and
 * the scene told to re-fit. A parallel set would be nineteen things to keep
 * in step and nineteen that drift.
 *
 * "IN ADDITION TO THE POPUP" is honoured literally: the popup road is
 * untouched. This adds a way to promote whatever is up, and a chooser that
 * opens straight into it.
 *
 * WHAT "MOBILE CAPABLE" HAD TO MEAN IN PRACTICE. These scenes were written
 * against a desktop panel, and three things break on a 9-inch glass:
 *   - the dialog is sized in pixels and centred, so it is a small box in
 *     the middle of a big screen. Promoting it means overriding that, and
 *     the override has to beat inline styles, hence the !important rules
 *     in the stylesheet rather than a class the scene can out-specify.
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
  var open = null;          /* the entry currently promoted */
  var shade = null;         /* the element we promoted */
  var exit = null;

  function list() {
    var reg = root.PINE_3JS;
    if (!Array.isArray(reg)) return [];
    return reg.filter(function (e) {
      return e && e.key && e.key !== 'off' && typeof e.open === 'function';
    }).map(function (e) {
      return {key: String(e.key), label: String(e.label || e.key),
        /* Declared OR findable by the id pineWin() gives it. */
        promotable: true};
    });
  }

  function entry(key) {
    var reg = root.PINE_3JS;
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

  /* ------------------------------------------------------------ promote */

  /* WHERE THE SCENE'S ELEMENT IS.
   *
   * Most entries name it - `frame.shade()` - but not all: several are just
   * `{key, label, open}` with no frame at all (`mind` is one), and those
   * were the five that reported "it cannot be made full screen" in the
   * sweep while eleven others promoted cleanly.
   *
   * They are not un-promotable, they are just undeclared: the panel builds
   * each one through pineWin(), which gives the element the id
   * `pineWin-<key>`. So when the entry does not say where its element is,
   * it is looked up by the id the panel would have given it. */
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
     * Six entries survived both roads above - crystal, shelf, slots, asks,
     * rejected, booth - because they build their own element with their own
     * id rather than going through pineWin(). Rather than learn six more
     * naming conventions that will become seven, the screen is photographed
     * before the scene is opened and whatever full-size fixed element is
     * NEW afterwards is the scene. It is the same reasoning the id lookup
     * used, one step more general.
     */
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

  /* What was on screen before the scene was asked for. */
  var before = null;

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

    /* The dialog inside it, if the entry names one: it carries the width
     * and the rounded corners that make it a card, and full screen wants
     * neither. */
    /* GUARDED. Not every entry has a frame at all - `manuals` threw
     * "Cannot read properties of undefined (reading 'card')" here, because
     * the element had been found by the generic fallback while e.frame was
     * still undefined. The lookup learned to cope with a missing frame and
     * this line had not. */
    if (e.frame && e.frame.card) {
      var card = node.querySelector(e.frame.card);
      if (card) card.classList.add('p3-full-card');
    }

    addExit(node, e);
    refit(e);
    return true;
  }

  function addExit(node, e) {
    if (exit && exit.parentNode) exit.remove();
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
     * re-render their own children after opening and took the button with
     * them. A way out that a scene can delete is not a way out - the same
     * lesson the lock screen taught when it covered the keyguard's own
     * unlock gesture. The body is the one parent none of them owns. */
    document.body.appendChild(exit);
  }

  /* TELL THE SCENE ITS CANVAS CHANGED, more than once.
   *
   * A WebGL scene sized while its container was a 700px dialog keeps that
   * size until something tells it otherwise, and the promotion happens in
   * the same frame as the resize. So: after a frame, after a beat, and on
   * every rotation for as long as it is up. */
  function refit(e) {
    var tell = function () {
      try {
        if (e.frame && typeof e.frame.onResize === 'function') e.frame.onResize();
      } catch (err) { /* a scene that will not re-fit still shows */ }
      /* Some scenes only listen to the window. */
      try { root.dispatchEvent(new Event('resize')); } catch (err) { /* old engine */ }
    };
    requestAnimationFrame(function () { requestAnimationFrame(tell); });
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
    if (exit && exit.parentNode) exit.remove();
    exit = null;
    document.body.classList.remove('p3-on');
    shade = null;
    open = null;
    if (e && e.frame && typeof e.frame.close === 'function') {
      try { e.frame.close(); } catch (err) { /* already gone */ }
    } else if (was && was.parentNode) {
      /* An entry with no frame has no close() either. The panel's windows
       * carry their own close control; press it if it is there, and take
       * the window out if it is not - leaving a promoted window behind
       * with its chrome stripped would be worse than either. */
      var own = was.querySelector('.pine-win-close, [data-close], .close');
      if (own && typeof own.click === 'function') own.click();
      else was.remove();
    }
  }

  /**
   * Open an experience and give it the whole screen.
   *
   * The panel's own `open()` is called first - it is what builds the scene
   * - and the result is promoted a beat later, because a modal that has
   * not been added to the document yet cannot be promoted.
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
         * only the promotion is in doubt, and the message says so. */
        return new Promise(function (done) {
          var tries = 0;
          (function attempt() {
            if (promote(e)) return done(e.key);
            tries += 1;
            if (tries > 16) {
              return done(e.label + ' opened, but it cannot be made full '
                + 'screen on this build - it is up as a window');
            }
            setTimeout(attempt, 250);
          })();
        });
            }, function (err) {
        return 'that experience would not open: ' + ((err && err.message) || err);
      });
  }

  /* ------------------------------------------------------- the chooser */

  var sheet = null;

  function chooser() {
    if (sheet) { sheet.remove(); sheet = null; return; }
    var rows = list();
    sheet = make('div', 'p3-sheet');
    var head = make('div', 'p3-head');
    head.appendChild(make('b', '', '3JS experiences'));
    head.appendChild(make('i', '', rows.length + ' on this station'));
    sheet.appendChild(head);

    if (!rows.length) {
      sheet.appendChild(make('p', 'p3-dim',
        'the panel has not registered any scenes yet — give it a moment '
        + 'after the terminal starts'));
    }

    var grid = make('div', 'p3-grid');
    rows.forEach(function (row) {
      var b = make('button', 'p3-pick');
      b.type = 'button';
      b.appendChild(make('b', '', row.label));
      if (!row.promotable) {
        b.appendChild(make('i', '', 'opens as a window'));
      }
      b.addEventListener('click', function (event) {
        event.stopPropagation();
        b.disabled = true;
        show(row.key).then(function (said) {
          b.disabled = false;
          if (said !== row.key) {
            var note = sheet && sheet.querySelector('.p3-note');
            if (note) note.textContent = String(said);
          } else if (sheet) { sheet.remove(); sheet = null; }
        });
      });
      grid.appendChild(b);
    });
    sheet.appendChild(grid);
    sheet.appendChild(make('p', 'p3-note', ''));

    var shutBtn = make('button', 'p3-close', 'Close');
    shutBtn.type = 'button';
    shutBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (sheet) { sheet.remove(); sheet = null; }
    });
    sheet.appendChild(shutBtn);

    document.body.appendChild(sheet);
    if (root.PineDismiss) {
      root.PineDismiss.watch(sheet, function () {
        if (sheet) { sheet.remove(); sheet = null; }
      }, []);
    }
  }

  var wired = false;
  function start() {
    if (wired) return;
    wired = true;
    root.addEventListener('resize', onTurn);
    if (root.screen && root.screen.orientation
      && typeof root.screen.orientation.addEventListener === 'function') {
      root.screen.orientation.addEventListener('change', onTurn);
    }
  }

  root.PineThreeFull = {
    start: start, list: list, show: show, close: shut, chooser: chooser,
    isFull: function () { return !!open; },
    HOST_ID: HOST_ID
  };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = root.PineThreeFull;
  }
})(typeof window !== 'undefined' ? window : globalThis);
