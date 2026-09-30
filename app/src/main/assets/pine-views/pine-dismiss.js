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
    var w = null;
    for (var i = watched.length - 1; i >= 0; i -= 1) {
      if (showing(watched[i])) { w = watched[i]; break; }
    }
    /* [closex:esc] a popup with a corner X (pine-closex.js) answers Escape
     * too; the higher of the two on screen goes first. An editor inside it
     * (a textarea, contenteditable) keeps its own Escape. */
    var cx = closexTop(event);
    if (cx && (!w || cx.node === w.node || zOf(cx.node) > zOf(w.node))) {
      try { cx.close(); } catch (err) { /* its own road threw */ }
      event.stopPropagation();
      return;
    }
    if (w) { fire(w); event.stopPropagation(); }
  }

  function closexTop(event) {
    var cx = root.pineCloseX;
    if (!cx || typeof cx.top !== 'function') return null;
    if (event && typeof cx.editing === 'function' && cx.editing(event.target)) return null;
    try { return cx.top(); } catch (err) { return null; }
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

  /* [#1450c] BACK CLOSES THE TOPMOST OVERLAY - one at a time, the one on top.
   *
   * "I brought that pop up up. I can't even exit it now." #1450's rule: a
   * thing that covers a surface may never depend on that surface for its
   * way out. BACK is the way out that no surface can take away: the kiosk
   * evaluates window.pineBack() and walks history only when it answers
   * false. The candidates are every panel watched here (the hold sheet
   * among them), whatever a view registered with onBack(probe) - a probe
   * answers {node, close} or null (System 3's Messenger: its open
   * dropdown) - the SFX TV's menus, sheet, parody window and video window,
   * and System 3's cards and menus. Each is closed by ITS OWN road (its
   * close, releaseHold, a tap on its own backdrop), never by removing
   * nodes from here. The one on top is the one with the highest stacking
   * z-index; on a tie, the later one. */
  var backs = [];

  function onBack(probe) {
    if (typeof probe !== 'function') return function () {};
    backs.push(probe);
    return function () {
      var at = backs.indexOf(probe);
      if (at >= 0) backs.splice(at, 1);
    };
  }

  function zOf(node) {
    for (var n = node; n && n.nodeType === 1; n = n.parentElement) {
      var z = NaN;
      try { z = parseInt(root.getComputedStyle(n).zIndex, 10); } catch (err) { z = NaN; }
      if (isFinite(z)) return z;
    }
    return 0;
  }

  function onScreen(node) {
    if (!node || !node.isConnected) return false;
    try {
      var cs = root.getComputedStyle(node);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      var r = node.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    } catch (err) { return false; }
  }

  function overlays() {
    var out = [];
    var add = function (node, close) {
      if (typeof close === 'function' && onScreen(node)) out.push({node: node, close: close, n: out.length});
    };
    var one = function (sel) { try { return document.querySelector(sel); } catch (err) { return null; } };
    var all = function (sel) { try { return document.querySelectorAll(sel); } catch (err) { return []; } };
    var i;
    for (i = 0; i < watched.length; i += 1) {
      if (showing(watched[i])) add(watched[i].node, watched[i].close);
    }
    /* [closex:back] every popup with a corner X is a BACK candidate too */
    var cxs = [];
    try { cxs = root.pineCloseX && typeof root.pineCloseX.open === 'function' ? root.pineCloseX.open() : []; } catch (err) { cxs = []; }
    for (i = 0; i < cxs.length; i += 1) {
      var seen = false;
      for (var s = 0; s < out.length; s += 1) { if (out[s].node === cxs[i].node) { seen = true; break; } }
      if (!seen) add(cxs[i].node, cxs[i].close);
    }
    for (i = 0; i < backs.length; i += 1) {
      var got = null;
      try { got = backs[i](); } catch (err) { got = null; }
      if (got && got.node) add(got.node, got.close);
    }
    var tv = root.PineSfxTv;
    if (tv && typeof tv.releaseHold === 'function') {
      var held = one('.sfx-tv-radial-shade') || one('.sfx-tv-delete-shade') || one('.sfx-tv-sheet');
      if (held) add(held, function () { tv.releaseHold(); });
    }
    var parody = all('.sfx-tv-parody-shade');
    for (i = 0; i < parody.length; i += 1) {
      (function (shade) { add(shade, function () { shade.click(); }); })(parody[i]);
    }
    if (tv && typeof tv.closeWindow === 'function') {
      var frames = all('body > .sfx-tv');
      for (i = 0; i < frames.length; i += 1) {
        if (frames[i].querySelector('.sfx-tv-tube')) { add(frames[i], function () { tv.closeWindow(); }); break; }
      }
    }
    var cards = all('.s3-modal-back');
    for (i = 0; i < cards.length; i += 1) {
      (function (back) { add(back, function () { back.click(); }); })(cards[i]);
    }
    return out;
  }

  function back() {
    var list = overlays();
    var best = null, bestZ = 0;
    for (var i = 0; i < list.length; i += 1) {
      var z = zOf(list[i].node);
      if (!best || z >= bestZ) { best = list[i]; bestZ = z; }
    }
    if (!best) return false;
    try { best.close(); } catch (err) { return false; }
    return true;
  }

  var api = {watch: watch, simple: simple, closeAll: closeAll,
    count: function () { return watched.length; },
    onBack: onBack, back: back,
    /* [closex:aware] Escape for pineCloseX popups is answered here - once
       its key listener is wired (the first watch() wires it) */
    closexAware: true, keyWired: function () { return wired; }};                              /* [#1450c] */
  root.PineDismiss = api;
  root.pineBack = function () { try { return back(); } catch (err) { return false; } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);

/* 2026-09-14: EVERY POP-UP MOVES. "Tap and drag allow me to move any pop
 * up window by tap and drag. And also on the computer by click and drag."
 *
 * One delegated pointer listener for the sheets that had no drag of their
 * own: the line inspector, the word-search sheet, the line-actions sheet,
 * the clip doctor and the report pad (the camera box, the ladder, the
 * preference sheet and the SFX set already move). Each is dragged by its
 * header where it has one, so a finger inside its scrolling body still
 * scrolls; the report pad, which has no header, moves from anywhere that
 * is not a control. On the first real movement the box is FROZEN where it
 * stands - fixed, at its measured left/top and width, transform and
 * margins cleared - so a sheet centred by flex or by translate(-50%) can
 * leave its centre without jumping.
 */
(function (root) {
  'use strict';
  if (!root.document) return;
  var ROOTS = [
    {root: '.ld-box', handle: '.ld-head'},
    {root: '.sp-find-box', handle: '.sp-find-head'},
    {root: '.pseg-sheet', handle: '.pseg-sheet-top'},
    {root: '.ct-box', handle: '.ct-head'},
    {root: '.pine-console-list', handle: '.pine-console-list-head'},
    {root: '.la-sheet', handle: ':scope > :first-child'},
    {root: '.cd-back > *', handle: ':scope > :first-child'},
    {root: '#pineReportPad', handle: null},
    {root: '[data-pine-drag]', handle: '[data-pine-drag-handle]'}
  ];
  var CONTROLS = 'button, input, select, textarea, a, [contenteditable], label, summary, details';
  var live = null;
  var topZ = 2147483060;

  function raise(box) {
    if (!box || !box.style) return;
    topZ = Math.min(2147483078, topZ + 1);
    box.style.zIndex = String(topZ);
    try { if (root.PineSfxTv) root.PineSfxTv.viewChanged(); } catch (e) { /* no wall */ }
  }

  function findRoot(target) {
    for (var i = 0; i < ROOTS.length; i += 1) {
      var r = target.closest ? target.closest(ROOTS[i].root) : null;
      if (!r) continue;
      var h = null;
      if (ROOTS[i].handle) {
        try { h = r.querySelector(ROOTS[i].handle); } catch (e) { h = null; }
        if (!h) h = r;
        if (!h.contains(target)) return null;   /* not on the handle: scroll, select, type */
      }
      return {root: r, handle: h || r};
    }
    var generic = target.closest
      ? target.closest('[role="dialog"], [aria-modal="true"], .modal, .dialog, .popover') : null;
    if (generic) {
      var handle = null;
      try {
        handle = generic.querySelector('[data-pine-drag-handle], header, .modal-header, .dialog-header');
      } catch (e) { handle = null; }
      if (handle && handle.contains(target)) return {root: generic, handle: handle};
    }
    return null;
  }

  function freeze(box) {
    var r = box.getBoundingClientRect();
    box.style.position = 'fixed';
    box.style.left = Math.round(r.left) + 'px';
    box.style.top = Math.round(r.top) + 'px';
    box.style.right = 'auto';
    box.style.bottom = 'auto';
    box.style.margin = '0';
    box.style.transform = 'none';
    box.style.width = Math.round(r.width) + 'px';
    box.style.maxWidth = 'none';
    return {left: r.left, top: r.top};
  }

  root.document.addEventListener('pointerdown', function (ev) {
    if (live) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    var t = ev.target;
    if (!t || !t.closest) return;
    /* The System 3 director is a full-screen workspace. Its inner dialog
       has a header, but moving that dialog would strand the graph and its
       controls. Small windows above it keep their own drag handlers. */
    if (t.closest('.s3-backdrop')) return;
    var popup = t.closest('[data-pine-drag], [role="dialog"], [aria-modal="true"], .modal, .dialog, .popover');
    if (popup) raise(popup);
    if (t.closest(CONTROLS)) return;
    var got = findRoot(t);
    if (!got) return;
    raise(got.root);
    live = {box: got.root, handle: got.handle, id: ev.pointerId,
      x: ev.clientX, y: ev.clientY, from: null, moved: false};
    try { got.handle.setPointerCapture(ev.pointerId); } catch (e) { /* older engine */ }
  }, true);

  root.document.addEventListener('pointermove', function (ev) {
    if (!live || ev.pointerId !== live.id) return;
    var dx = ev.clientX - live.x, dy = ev.clientY - live.y;
    if (!live.moved) {
      if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
      live.moved = true;
      live.from = freeze(live.box);
    }
    var w = root.innerWidth || 1280, h = root.innerHeight || 800;
    live.box.style.left = Math.max(-live.box.offsetWidth + 60, Math.min(w - 60, live.from.left + dx)) + 'px';
    live.box.style.top = Math.max(0, Math.min(h - 40, live.from.top + dy)) + 'px';
    ev.preventDefault();
  }, true);

  function drop(ev) {
    if (!live || (ev && ev.pointerId !== live.id)) return;
    try { live.handle.releasePointerCapture(live.id); } catch (e) { /* not held */ }
    /* A press that never moved is left to whatever it was on - a tap
       on a header, a click on a card - untouched. */
    live = null;
  }
  root.document.addEventListener('pointerup', drop, true);
  root.document.addEventListener('pointercancel', drop, true);

  root.PineDrag = {roots: ROOTS, freeze: freeze};
})(typeof window !== 'undefined' ? window : globalThis);

/* [popback] 2026-09-30: A WAY BACK FROM EVERY POP-UP THAT CAME FROM ANOTHER.
 * "If I click on a option inside of a pop up to go to another pop up, always
 * offer a back button to go back to the original pop up so that way I don't
 * lose it. And that's just universal in the application in general. Anytime
 * I transition between pop-ups, offer a back button." (the operator)
 *
 * One rule, not a button per sheet. Every pop-up here carries a close X (the
 * [closex] rule), so a pop-up is: a fixed overlay at the top of the page that
 * holds a close control. When one appears while another is up - or just after
 * another went away, which is how a sheet HANDS OVER to the next - it gets a
 * back button beside its X. Back closes it through its own X (its own
 * teardown runs) and brings the one it came from back exactly as it was: the
 * node is kept, so a sheet that removed itself is put back where it stood.
 */
(function (root) {
  'use strict';
  var doc = root.document;
  if (!doc || !root.MutationObserver || root.PinePopBack) return;
  var CLOSE = '[aria-label^="close" i], [title^="close" i], .pcx-btn, .pcx, [data-pine-close]';
  /* windows that live on the screen rather than pop over it: the camera, the
     video set, the console strip - never a pop-up anyone came FROM */
  var SKIP = '#pineCamBox, .pine-cam-box, .sfx-tv, .pine-cam, .pine-cam-wall, #pineConsoleLine, '
    + '.s3-backdrop, .pine-rail, .hc-toast';
  var HANDOVER_MS = 2500;
  var up = [];          /* pop-ups on screen, oldest first: {el, label} */
  var gone = null;      /* the one that just went: {el, parent, next, hidden, label, at} */

  function visible(el) {
    if (!el || !el.isConnected || el.hidden) return false;
    var cs = root.getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    return el.getClientRects().length > 0;
  }
  function fixedBox(el) {
    var cs = root.getComputedStyle(el);
    if (cs.position === 'fixed') return true;
    var kid = el.firstElementChild;
    return !!(kid && root.getComputedStyle(kid).position === 'fixed');
  }
  function closer(el) {
    var list = el.querySelectorAll(CLOSE);
    for (var i = 0; i < list.length; i += 1) {
      var b = list[i];
      if (!b.classList.contains('pine-popback') && /^(BUTTON|A|SPAN|I|DIV)$/.test(b.tagName)) return b;
    }
    return null;
  }
  function isPopup(el) {
    if (!el || el.nodeType !== 1 || el.id === 'pinePopBackStyle') return false;
    if (/^(SCRIPT|STYLE|LINK|TEMPLATE|IFRAME|VIDEO|AUDIO|CANVAS)$/.test(el.tagName)) return false;
    try { if (el.matches(SKIP) || el.querySelector(SKIP)) return false; } catch (e) { return false; }
    return fixedBox(el) && !!closer(el);
  }
  function labelOf(el) {
    var d = el.matches('[role="dialog"]') ? el : el.querySelector('[role="dialog"]');
    var t = (d && d.getAttribute('aria-label')) || '';
    if (!t) {
      var h = el.querySelector('h1, h2, h3, h4, header b, [class*="head"] b, [class*="title"], b, strong');
      t = h ? h.textContent : '';
    }
    t = String(t || '').replace(/\s+/g, ' ').trim();
    if (t.length > 44) t = t.slice(0, 44).replace(/\s+\S*$/, '') + '…';
    return t || 'the last window';
  }
  function style() {
    if (doc.getElementById('pinePopBackStyle')) return;
    var s = doc.createElement('style');
    s.id = 'pinePopBackStyle';
    s.textContent = '.pine-popback{display:inline-grid;place-items:center;min-width:32px;min-height:32px;'
      + 'margin-right:6px;cursor:pointer}.pine-popback .pi-icon,.pine-popback svg{width:18px;height:18px}';
    doc.head.appendChild(s);
  }
  function giveBack(el, prev) {
    if (el.querySelector('.pine-popback')) return;
    var x = closer(el);
    if (!x || !x.parentNode) return;
    style();
    var b = doc.createElement('button');
    b.type = 'button';
    b.className = String(x.className || '') + ' pine-popback';
    var mark = '';
    try { mark = root.pineIcon ? root.pineIcon('c:arrow--left', '') : ''; } catch (e) { mark = ''; }
    if (mark) b.innerHTML = mark; else b.textContent = '‹';
    b.title = 'Back to ' + prev.label;
    b.setAttribute('aria-label', b.title);
    b.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      goBack(el, prev);
    });
    x.parentNode.insertBefore(b, x);
    beside(b, x);
  }
  /* [popback] NEVER ON TOP OF THE X. "These buttons are overlapping. I don't
     want any overlapping buttons." (the operator, twice: a corner-pinned X,
     then pineCloseX's sticky one.) The back button drops the X's own
     placement classes; if it still touches the X wherever it landed, it is
     set just left of the X in the same box - and set again when that box
     scrolls or the window changes size. */
  function hits(a, b) {
    var p = a.getBoundingClientRect(), q = b.getBoundingClientRect();
    return !(p.right <= q.left || p.left >= q.right || p.bottom <= q.top || p.top >= q.bottom);
  }
  function beside(b, x) {
    b.classList.remove('pcx-stick', 'pcx-flex', 'pcx-abs');
    var pinned = /^(absolute|fixed)$/.test(root.getComputedStyle(x).position);
    var place = function () {
      if (!b.isConnected || !x.isConnected) return;
      if (!b.__pineBeside && !hits(b, x)) return;
      b.__pineBeside = true;
      var gap = 6, w = b.offsetWidth || 32;
      b.style.position = 'absolute';
      b.style.margin = '0';
      b.style.right = 'auto';
      b.style.bottom = 'auto';
      b.style.float = 'none';
      b.style.zIndex = root.getComputedStyle(x).zIndex === 'auto' ? '' : root.getComputedStyle(x).zIndex;
      b.style.left = Math.round(x.offsetLeft - w - gap) + 'px';
      b.style.top = Math.round(x.offsetTop) + 'px';
      /* a heading beside a corner-pinned pair keeps clear of both */
      var head = x.parentNode;
      if (pinned && head && head.style) {
        var need = Math.round(head.getBoundingClientRect().right - b.getBoundingClientRect().left + gap);
        if ((parseFloat(root.getComputedStyle(head).paddingRight) || 0) < need) head.style.paddingRight = need + 'px';
      }
    };
    place();
    root.requestAnimationFrame(place);
    var host = b.closest('[role="dialog"]') || b.parentNode;
    var again = function () { if (b.__pineBeside) place(); };
    try { host.addEventListener('scroll', again, true); } catch (e) { /* nothing scrolls */ }
    root.addEventListener('resize', again);
  }
  function goBack(el, prev) {
    var x = closer(el);
    try { if (x) x.click(); } catch (e) { /* removed below */ }
    root.setTimeout(function () {
      if (visible(el)) { try { el.remove(); } catch (e) { /* gone */ } }
      var p = prev.el;
      if (!p.isConnected && prev.parent && prev.parent.isConnected) {
        var next = prev.next && prev.next.parentNode === prev.parent ? prev.next : null;
        prev.parent.insertBefore(p, next);
      }
      if (prev.hidden) p.hidden = false;
      if (p.style && p.style.display === 'none') p.style.display = '';
    }, 60);
  }
  /* [popback] a TRANSITION is a tap in the pop-up it came from. A pop-up that
     opens by itself ("Your Pine Box ad is ready") over another one did not
     come from it and gets no way back to it. */
  var tap = {target: null, at: 0};
  doc.addEventListener('pointerdown', function (ev) { tap = {target: ev.target, at: Date.now()}; }, true);
  doc.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter' || ev.key === ' ') tap = {target: ev.target, at: Date.now()};
  }, true);
  function tappedIn(node) {
    return !!(node && tap.target && Date.now() - tap.at <= HANDOVER_MS && node.contains(tap.target));
  }
  function appeared(el) {
    for (var k = 0; k < up.length; k += 1) if (up[k].el === el) return;   /* already known: a drag, a restyle */
    if (!isPopup(el) || !visible(el)) return;
    up = up.filter(function (r) { return visible(r.el); });
    var below = null;
    for (var j = up.length - 1; j >= 0; j -= 1) if (tappedIn(up[j].el)) { below = up[j]; break; }
    var prev = below ? {el: below.el, parent: null, next: null, hidden: false, label: below.label}
      : (gone && Date.now() - gone.at <= HANDOVER_MS && gone.el !== el && tappedIn(gone.el) ? gone : null);
    up.push({el: el, label: labelOf(el)});
    if (prev) giveBack(el, prev);
  }
  function left(el, parent, next, hidden) {
    var had = null;
    for (var i = 0; i < up.length; i += 1) if (up[i].el === el) had = up[i];
    if (!had) return;
    up = up.filter(function (r) { return r.el !== el; });
    gone = {el: el, parent: parent, next: next, hidden: hidden, label: had.label, at: Date.now()};
  }
  /* Only the page's top level is watched - each child on its own, for being
     shown or hidden - never the whole tree: the feed and the players restyle
     themselves many times a second. */
  var kidWatch = new root.MutationObserver(function (records) {
    records.forEach(function (m) {
      var el = m.target;
      if (visible(el)) appeared(el);
      else left(el, el.parentNode, el.nextSibling, true);
    });
  });
  function watchKid(el) {
    if (el.nodeType !== 1 || el.__pinePopWatch) return;
    el.__pinePopWatch = true;
    kidWatch.observe(el, {attributes: true, attributeFilter: ['hidden', 'style', 'class']});
  }
  function start() {
    var body = doc.body;
    if (!body) return;
    [].forEach.call(body.children, function (el) {
      watchKid(el);
      if (isPopup(el) && visible(el)) up.push({el: el, label: labelOf(el)});
    });
    new root.MutationObserver(function (records) {
      records.forEach(function (m) {
        [].forEach.call(m.removedNodes, function (n) { if (n.nodeType === 1) left(n, m.target, m.nextSibling, false); });
        [].forEach.call(m.addedNodes, function (n) {
          if (n.nodeType !== 1) return;
          watchKid(n);
          root.setTimeout(function () { appeared(n); }, 0);
        });
      });
    }).observe(body, {childList: true});
  }
  root.PinePopBack = {stack: function () { return up.slice(); }, isPopup: isPopup};
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', start); else start();
})(typeof window !== 'undefined' ? window : globalThis);
