/* TAP AWAY AND IT GOES AWAY.
 *
 * "I still can't close this volume overlay. I want things to collapse from
 * me tapping away from them like an app."
 *
 * The desk popover DID have an outside-tap close. It listened for `click`
 * on `document`, in the bubble phase - which means any handler between the
 * tap and the document that calls stopPropagation() eats it, and this page
 * has several by design: the desk itself stops clicks so moving a slider
 * does not close it, the backdrop swallows taps to cycle stills and video,
 * the feed rows swallow taps to open a line. Tap one of those and the
 * overlay stayed open. From the operator's side it simply would not close.
 *
 * So dismissal is not left to each popover to remember. It is one rule,
 * registered here, and it holds three properties the per-popover version
 * did not:
 *
 *   CAPTURE PHASE. The listener runs on the way DOWN, before any node can
 *     stop it. Nothing downstream can make a panel unclosable.
 *   POINTERDOWN, not click. A drag that starts outside and ends inside
 *     never produces a click at all, and on a touch screen the 300ms click
 *     delay is the difference between "it closed" and "it ignored me".
 *   ONE STACK. The newest open panel closes first, so Escape and the back
 *     gesture unwind overlays in the order they were opened rather than
 *     shutting all of them at once.
 *
 * Registering is deliberately cheap, because the goal is that EVERY panel
 * on every view uses it:
 *
 *     PineDismiss.watch(node, () => { node.hidden = true; }, [openerButton])
 *
 * The opener is exempt so its own tap toggles rather than close-then-open.
 */
(function (root) {
  'use strict';

  var watched = [];

  function inside(node, target) {
    if (!node || !target) return false;
    if (node === target) return true;
    return typeof node.contains === 'function' && node.contains(target);
  }

  /* Open = actually on the screen. `hidden` is the usual switch, but a
   * panel can also be removed, detached or display:none'd by its view, and
   * a dismisser that fires at a panel nobody can see is noise. */
  function showing(entry) {
    var node = entry.node;
    if (!node || !node.isConnected) return false;
    if (node.hidden) return false;
    if (typeof entry.open === 'function') return !!entry.open();
    var box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  }

  function fire(entry) {
    try { entry.close(); } catch (err) { /* a stuck panel must not stop the rest */ }
  }

  function onDown(event) {
    var target = event.target;
    if (!target) return;
    for (var i = 0; i < watched.length; i += 1) {
      var entry = watched[i];
      if (!showing(entry)) continue;
      if (inside(entry.node, target)) continue;
      var spared = false;
      for (var k = 0; k < entry.spare.length; k += 1) {
        var keep = typeof entry.spare[k] === 'function' ? entry.spare[k]() : entry.spare[k];
        if (inside(keep, target)) { spared = true; break; }
      }
      if (!spared) fire(entry);
    }
  }

  /* Escape closes the newest one only - the same thing the back gesture
   * should do, and the same thing every desktop app does. */
  function onKey(event) {
    if (event.key !== 'Escape' && event.key !== 'Esc') return;
    for (var i = watched.length - 1; i >= 0; i -= 1) {
      if (showing(watched[i])) { fire(watched[i]); event.stopPropagation(); return; }
    }
  }

  var wired = false;
  function wire() {
    if (wired) return;
    wired = true;
    /* Capture, on all three, because a WebView that misses pointerdown
     * still delivers touchstart, and a mouse still delivers mousedown. */
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('touchstart', onDown, true);
    document.addEventListener('keydown', onKey, true);
  }

  /** Close `node` when a tap lands outside it. Returns an unwatch function. */
  function watch(node, close, spare, open) {
    if (!node || typeof close !== 'function') return function () {};
    wire();
    var entry = {
      node: node,
      close: close,
      open: typeof open === 'function' ? open : null,
      spare: [].concat(spare || [])
    };
    watched.push(entry);
    return function () {
      var at = watched.indexOf(entry);
      if (at >= 0) watched.splice(at, 1);
    };
  }

  /** Close every open panel - for a view switch, where nothing should linger. */
  function closeAll() {
    for (var i = watched.length - 1; i >= 0; i -= 1) {
      if (showing(watched[i])) fire(watched[i]);
    }
  }

  /* The common case in one line: a panel, the button that opens it, and
   * `hidden` as the switch. */
  function simple(node, opener) {
    return watch(node, function () {
      node.hidden = true;
      if (opener && opener.classList) opener.classList.remove('on');
    }, opener ? [opener] : []);
  }

  var api = {watch: watch, simple: simple, closeAll: closeAll,
    count: function () { return watched.length; }};
  root.PineDismiss = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
