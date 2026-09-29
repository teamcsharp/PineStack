/* pine-closex.js - EVERY POP-UP HAS AN X IN ITS CORNER.
 *
 * "Put an X in the corner of this pop up and make sure that every pop up
 * has an X in the corner of it in order to close it ... I'm not able to
 * close this pop up because there's no X in a corner and I don't know which
 * icon to click because there's no tool tips on hover for them."
 *                                                   - the operator, 09-29
 *
 * The booth's own Close was the LAST button in a bar that does not wrap,
 * inside a window that clips: shrink the window and it slid off the edge.
 * A way out that the layout can take away is the #1450 trap again (see
 * pine-dismiss.js, "a modal needs its own way out"), so the way out is not
 * left to each pop-up's header any more. It is one control, drawn one way:
 *
 *     pineCloseX(popup, close)          -> the button
 *     pineCloseX(popup, close, {label: 'Close the booth', reserve: 'top'})
 *
 *   - Carbon close--filled from the sprite (never an emoji), 40 px target,
 *     pinned to the popup's top-right corner, title AND aria-label.
 *   - It calls the popup's OWN close road - the function that already
 *     tears it down, stops its timers and puts its opener back. It never
 *     removes nodes itself.
 *   - A popup that scrolls gets it sticky, so it stays in the corner while
 *     the body scrolls under it; one that does not gets it absolute.
 *   - A builder that repaints its popup with innerHTML cannot wipe it: the
 *     X puts itself back.
 *   - Escape and the kiosk's BACK close the topmost popup that carries one.
 *     Where pine-dismiss.js is loaded it owns those keys and asks here for
 *     the list (PineDismiss is closex-aware); where it is not - the station
 *     panel on the desktop - this file answers Escape itself.
 *
 * Loaded twice on the kiosk (the panel serves it at /icons/pine-closex.js
 * and pine-views injects it): the first copy wins, the second is a no-op.
 * The copies live at desktop/renderer (canonical), frontend (served) and
 * app/src/main/assets/pine-views (the kiosk), and must stay identical.
 */
(function (root) {
  'use strict';
  if (!root || !root.document) return;
  if (root.pineCloseX && root.pineCloseX.version) return;

  var CLS = 'pine-closex';
  var ICON = 'c:close--filled';
  var entries = [];

  function style() {
    var doc = root.document;
    if (doc.getElementById('pineCloseXStyle')) return;
    var s = doc.createElement('style');
    s.id = 'pineCloseXStyle';
    s.textContent = [
      '.' + CLS + '{box-sizing:border-box;width:40px;height:40px;min-width:40px;min-height:40px;',
      'margin:0;padding:0;display:inline-flex;align-items:center;justify-content:center;',
      'border-radius:10px;border:1px solid rgba(255,255,255,.16);background:rgba(10,14,20,.78);',
      'color:#e6eef4;cursor:pointer;line-height:1;font:600 18px/1 system-ui,sans-serif;',
      'box-shadow:0 2px 10px rgba(0,0,0,.35);z-index:2147483600;flex:none;',
      '-webkit-tap-highlight-color:transparent;touch-action:manipulation}',
      '.' + CLS + '.pcx-abs{position:absolute;top:4px;right:4px}',
      '.' + CLS + '.pcx-stick{position:sticky;top:4px;float:right;margin:0 0 4px 8px}',
      '.' + CLS + '.pcx-stick.pcx-flex{float:none;align-self:flex-end;justify-self:end;order:-1;margin:0 0 -40px 0}',
      '.' + CLS + ':hover{background:#a8323a;border-color:#e0676a;color:#fff}',
      '.' + CLS + ':focus-visible{outline:2px solid #6cc4ff;outline-offset:1px}',
      '.' + CLS + ' svg{width:22px;height:22px;fill:currentColor;pointer-events:none}',
      /* no sprite (a page without pine-icons.js): two bars, still no emoji */
      '.' + CLS + ' .pcx-bars{position:relative;width:18px;height:18px;pointer-events:none}',
      '.' + CLS + ' .pcx-bars::before,.' + CLS + ' .pcx-bars::after{content:"";position:absolute;',
      'left:8px;top:0;width:2px;height:18px;border-radius:1px;background:currentColor}',
      '.' + CLS + ' .pcx-bars::before{transform:rotate(45deg)}',
      '.' + CLS + ' .pcx-bars::after{transform:rotate(-45deg)}'
    ].join('');
    (doc.head || doc.documentElement).appendChild(s);
  }

  function art(button) {
    var svg = '';
    try { if (typeof root.pineIcon === 'function') svg = root.pineIcon(ICON); } catch (e) { svg = ''; }
    button.innerHTML = svg || '<span class="pcx-bars" aria-hidden="true"></span>';
  }

  function shown(node) {
    if (!node || !node.isConnected || node.hidden) return false;
    try {
      var cs = root.getComputedStyle(node);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      var r = node.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    } catch (e) { return false; }
  }

  function zOf(node) {
    for (var n = node; n && n.nodeType === 1; n = n.parentElement) {
      var z = NaN;
      try { z = parseInt(root.getComputedStyle(n).zIndex, 10); } catch (e) { z = NaN; }
      if (isFinite(z)) return z;
    }
    return 0;
  }

  /* Where the X sits depends on the popup, and is decided once the popup
   * is in the document (a stylesheet class may be what makes it fixed, so
   * an inline guess before it is attached would be wrong). */
  function place(entry) {
    var pop = entry.node, x = entry.button;
    if (!pop.isConnected) return false;
    var cs;
    try { cs = root.getComputedStyle(pop); } catch (e) { return false; }
    var scrolls = /(auto|scroll)/.test(cs.overflowY || '') && pop.scrollHeight > pop.clientHeight + 1;
    var flexy = /(flex|grid)/.test(cs.display || '');
    x.classList.remove('pcx-abs', 'pcx-stick', 'pcx-flex');
    if (scrolls || entry.opts.sticky) {
      x.classList.add('pcx-stick');
      if (flexy) x.classList.add('pcx-flex');
      if (pop.firstChild !== x) pop.insertBefore(x, pop.firstChild);
    } else {
      if (cs.position === 'static') pop.style.position = 'relative';
      x.classList.add('pcx-abs');
      if (x.parentNode !== pop) pop.appendChild(x);
    }
    return true;
  }

  function reserve(pop, side) {
    if (side === 'top') pop.style.paddingTop = 'max(44px, ' + (pop.style.paddingTop || '0px') + ')';
    else if (side === 'right') pop.style.paddingRight = 'max(48px, ' + (pop.style.paddingRight || '0px') + ')';
  }

  /* A popup that has left the document is forgotten - unless it is only
   * hidden, or was built and not yet attached (it gets ten seconds). */
  function prune() {
    var now = Date.now();
    for (var i = entries.length - 1; i >= 0; i -= 1) {
      if (!entries[i].node.isConnected && now - entries[i].born > 10000) {
        try { entries[i].mo.disconnect(); } catch (e) { /* gone */ }
        entries.splice(i, 1);
      }
    }
  }

  function pineCloseX(popup, onClose, opts) {
    if (!popup || popup.nodeType !== 1 || typeof onClose !== 'function') return null;
    opts = opts || {};
    style();
    prune();
    for (var i = 0; i < entries.length; i += 1) {
      if (entries[i].node === popup) {          /* built again: rewire, same X */
        entries[i].close = onClose;
        return entries[i].button;
      }
    }
    var label = opts.label || 'Close';
    var x = root.document.createElement('button');
    x.type = 'button';
    x.className = CLS + ' pcx-abs';
    x.title = label;
    x.setAttribute('aria-label', label);
    x.setAttribute('data-pine-closex', '');
    art(x);
    var entry = {node: popup, button: x, close: onClose, opts: opts, mo: null, born: Date.now()};
    function fire(ev) {
      if (ev) { ev.preventDefault(); ev.stopPropagation(); }
      try { entry.close(ev); } catch (err) { /* the popup's own road threw: say so, never strand it */
        try { console.error('pineCloseX: close failed', err); } catch (e) { /* no console */ }
      }
    }
    x.addEventListener('click', fire);
    /* a drag handle or a tap-away rule must never see this press */
    x.addEventListener('pointerdown', function (ev) { ev.stopPropagation(); });
    popup.appendChild(x);
    if (opts.reserve) reserve(popup, opts.reserve);
    entries.push(entry);
    /* a repaint by innerHTML / replaceChildren takes the X with it: put it back */
    try {
      entry.mo = new root.MutationObserver(function () {
        if (x.parentNode !== popup && popup.isConnected) place(entry) || popup.appendChild(x);
      });
      entry.mo.observe(popup, {childList: true});
    } catch (e) { entry.mo = null; }
    if (!place(entry)) {
      /* Not in the document yet (built first, attached after an await):
       * try again as soon as it can be, for up to ten seconds. */
      var tries = 0;
      var later = function () {
        if (place(entry) || !entries.length || (tries += 1) > 40) return;
        root.setTimeout(later, tries < 10 ? 16 : 250);
      };
      if (typeof root.queueMicrotask === 'function') root.queueMicrotask(later); else root.setTimeout(later, 0);
    }
    wire();
    return x;
  }

  /* The popups with an X that are on the screen now, oldest first. */
  function open() {
    prune();
    var out = [];
    for (var i = 0; i < entries.length; i += 1) {
      if (shown(entries[i].node)) {
        (function (e) { out.push({node: e.node, close: function () { e.close(); }, button: e.button}); })(entries[i]);
      }
    }
    return out;
  }

  /* The one on top: highest stacking z-index, the later one on a tie. */
  function top() {
    var list = open(), best = null, bestZ = 0;
    for (var i = 0; i < list.length; i += 1) {
      var z = zOf(list[i].node);
      if (!best || z >= bestZ) { best = list[i]; bestZ = z; }
    }
    return best;
  }

  function closeTop() {
    var t = top();
    if (!t) return false;
    t.close();
    return true;
  }

  function editing(target) {
    if (!target || target.nodeType !== 1) return false;
    if (target.isContentEditable) return true;
    return /^(TEXTAREA|SELECT)$/.test(target.tagName);
  }

  var wired = false;
  function wire() {
    if (wired) return;
    wired = true;
    /* Bubble phase on the window: an editor inside the popup that answers
     * Escape itself (cancel this edit) gets it first and keeps it. */
    root.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Escape' && ev.key !== 'Esc') return;
      if (ev.defaultPrevented) return;
      var pd = root.PineDismiss;                                      /* it answers, once it listens */
      if (pd && pd.closexAware && typeof pd.keyWired === 'function' && pd.keyWired()) return;
      if (editing(ev.target)) return;
      if (closeTop()) { ev.preventDefault(); ev.stopPropagation(); }
    });
  }

  pineCloseX.version = 1;
  pineCloseX.open = open;
  pineCloseX.top = top;
  pineCloseX.closeTop = closeTop;
  pineCloseX.editing = editing;
  pineCloseX.count = function () { prune(); return entries.length; };
  root.pineCloseX = pineCloseX;
  if (typeof module !== 'undefined' && module.exports) module.exports = pineCloseX;
})(typeof window !== 'undefined' ? window : globalThis);
