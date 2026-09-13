/* pine-touch.js - make the station's panel behave like a touch app.
 *
 * Injected at DOCUMENT START (WebViewCompat.addDocumentStartJavaScript), so
 * the rules are in force before first paint. Nothing here changes what the
 * panel DOES; it only tells the WebView who owns a gesture.
 *
 * ---------------------------------------------------------------------------
 * 1. THE 3JS FIX, which is the one that mattered.
 *
 * Symptom: "the application appears to not have finger touch support for 3js
 * simulations".
 *
 * It was never the handlers. The panel's three.js views listen on POINTER
 * events - pointerdown / pointermove / pointerup / wheel / dblclick, around
 * app.py:138735 - and pointer events are fed by touch perfectly well. The
 * whole panel contains exactly FOUR touch-action declarations (app.py:130419,
 * 131199, 131860, 131879; three `none`, one `pan-y`) and not one of them
 * applies to a canvas, so every three.js canvas inherits `touch-action: auto`.
 *
 * With `auto` the WebView is entitled to claim the gesture for panning or
 * pinching, and the moment a drag is recognised as a scroll it fires
 * `pointercancel` at the page. The pointermove stream dies mid-drag and the
 * camera stops following the finger. On a desktop this can never appear,
 * because a mouse drag is not a scroll gesture - which is exactly why the
 * scenes work on Windows and failed on the tablet.
 *
 * `touch-action: none` on the canvas hands the gesture back to the page. Note
 * the deliberate tension with the WebView's own pinch-zoom (setSupportZoom /
 * builtInZoomControls in MainActivity, which the operator asked for): the page
 * pinches, the canvas rotates. That is the behaviour we want, and both halves
 * have to be checked on the real screen after any change here.
 *
 * 2. NO 300ms TAP DELAY. Chrome only drops the double-tap-zoom wait when the
 *    page is not zoomable - and this one deliberately IS (the terminal sets
 *    minimum-scale=0.25, maximum-scale=5). `touch-action: manipulation` on the
 *    things you actually tap disables double-tap zoom FOR THOSE ELEMENTS while
 *    leaving pinch alone, which buys the responsiveness without taking the
 *    zoom away.
 *
 * 3. NO SELECTION AT ALL, except where something is being typed.
 *
 *    This started as "chrome off, prose on", on the grounds that the log
 *    panes are read and copied. In use that is backwards. On a tablet a long
 *    press is not a rare deliberate act, it is how the terminal is operated:
 *    feed rows are DRAGGED onto sampler pads, script lines are HELD to open
 *    the line menu, entries are tapped and held all day. Every one of those
 *    gestures begins as a press on prose, so every one of them raced Chrome's
 *    own selection - and Chrome usually won, leaving selection handles and a
 *    floating Copy bar over the thing the operator was reaching for.
 *
 *    "I am tapping and tapping and holding entries. The copy text is getting
 *     in the way. Disable that behavior for the app."
 *
 *    Inputs, textareas and contenteditable keep selection, because that is
 *    the one place it is the point rather than the obstacle - without it
 *    there is no paste into the chat box.
 *
 * 4. FEEDBACK ON THE FRAME YOU TOUCHED. A tap highlight and an :active
 *    brightness step, both pure paint, so they land on the next frame with no
 *    animator and no layout.
 */
(function () {
  if (window.__pineTouch) return;
  window.__pineTouch = true;

  var CSS = [
    /* (1) THE 3JS FIX. !important because a scene that sets its own
       touch-action later would otherwise win, and the wrapper classes are
       the frames pineWinAdopt/pineWin put a scene into (app.py:134340,
       134360, 134447) - a scene that puts an overlay over its canvas must
       not hand the gesture back to the browser either. */
    "canvas, .pine-win-host, .pine-win-adopted, [data-pine-win] {" +
      " touch-action: none !important; }",

    /* THE KNOWN COST, stated rather than hidden: this is every canvas, not
       only the scene ones, so a finger that starts on a small sparkline or a
       spectrogram inside a scrolling pane no longer scrolls that pane - it is
       swallowed by an element that does nothing with it. CSS has no size
       selector, so telling the two apart would mean measuring canvases in
       JavaScript and re-measuring whenever a scene opens. Not worth it: the
       small canvases are a few pixels tall in panes with plenty of other
       surface to drag, and the scenes are the thing that was broken. */

    /* (2) No double-tap wait on anything you tap. */
    "a, button, input, select, textarea, label, summary, option," +
      " [role=button], [role=tab], [onclick], .tab, .chip, .btn, .cell {" +
      " touch-action: manipulation; }",

    /* (3) NOTHING IS SELECTABLE. `user-select` inherits, so saying it once
       at the root covers every element the panel has now and every one it
       grows later - which matters on a page this large, where naming the
       selectable shapes by hand is how the previous version of this rule
       ended up letting the whole feed through.

       `-webkit-touch-callout: none` is the other half and is easy to forget:
       it is what stops the long-press menu on links and images, which is a
       separate popup from the text one and just as unwelcome mid-drag. */
    ":root, body { -webkit-user-select: none; user-select: none;" +
      " -webkit-touch-callout: none; }",
    /* ...except where something is actually being typed. Last, and more
       specific, so it wins. The descendant selector is for contenteditable
       panes, whose children would otherwise inherit `none` from the root and
       be uneditable in practice. */
    "input, textarea, [contenteditable], [contenteditable] * {" +
      " -webkit-user-select: text; user-select: text;" +
      " -webkit-touch-callout: default; }",
    /* A drag that began before this landed can leave a selection painted on
       screen with no way to clear it, so it is made invisible too. Belt for
       the braces, and one paint rule. */
    "::selection { background: transparent; }",
    "input::selection, textarea::selection, [contenteditable] ::selection {" +
      " background: rgba(101,199,218,.35); }",

    /* (4) Feedback. tap-highlight-color is inherited, so :root is enough and
       a universal selector would only cost style recalculation. */
    ":root { -webkit-tap-highlight-color: rgba(227,179,65,0.28); }",
    "button:active, a:active, .tab:active, .chip:active, [role=button]:active {" +
      " filter: brightness(1.35); }",

    /* Momentum. Chrome scrolls with momentum by default; what it does NOT do
       by default is stop a pane's overscroll turning into the page bouncing
       under it, which on a kiosk reads as the whole panel coming loose. */
    "body { overscroll-behavior: contain; }"
  ].join("\n");

  function put() {
    try {
      if (document.getElementById("pine-touch-css")) return true;
      var host = document.head || document.documentElement;
      if (!host) return false;
      var style = document.createElement("style");
      style.id = "pine-touch-css";
      style.textContent = CSS;
      host.appendChild(style);
      return true;
    } catch (err) {
      return false;
    }
  }

  /* At document start there may be no <head> yet, so this runs three times
     and stops as soon as the node is in: now, at DOMContentLoaded, and once
     more on load for a panel that rebuilt its own head. Each call is an id
     lookup after the first, which is free. */
  if (!put()) {
    document.addEventListener("DOMContentLoaded", put);
  }
  window.addEventListener("load", put);
})();
