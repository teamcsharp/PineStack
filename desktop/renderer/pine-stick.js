/* [autoscroll-rule] ONE RULE FOR EVERY SCROLLER THAT FOLLOWS.
 *
 * "do not move the page for me as far as scrolling it unless I am already
 *  looking at the latest message. If I'm looking at the latest message,
 *  then move to the next message in line when that message comes in, just
 *  like it would with an instant message. But if I'm scrolling around the
 *  page looking at different elements, then don't move the page that I'm
 *  already looking at, 'cause I'm already looking at something else and
 *  examining it. And that's just in the program in general."
 *                                                 - the operator, 2026-09-28
 *
 * So an UNREQUESTED scroll - rows arriving, a refresh, a timer, a live line
 * moving, a list re-render - may move a scroller only while
 *
 *   1. the operator is at its LATEST position, the end new items arrive at
 *      (the bottom; the top of a newest-first list), and
 *   2. is not EXAMINING something in it: text selected, a pointer held
 *      down, a field being typed in, or whatever the caller says is open
 *      (a detail panel, a hover card, an expanded row).
 *
 * Once they scroll away it stays where they put it. Nothing on a timer
 * brings it back: they come back to the latest position themselves, or
 * press the small jump button this puts over the scroller's latest edge.
 * A re-render that cannot help moving content above them puts the row they
 * were reading back where it was on the glass.
 *
 *   var st = pineStick(box, {edge: 'bottom'});  // cached: call it per paint
 *   box.appendChild(row);
 *   st.follow();              // to the latest edge - or one more on the button
 *
 *   st.keep(function () { rebuild(box); }, true);   // reader held in place
 *
 * Where it comes from. The desktop loads this file from disk (index.html,
 * before renderer.js); the station's panel loads the same file from
 * /spark/asset/pine-stick.js, and the tablet's views run inside that panel.
 * A caller that finds no pineStick simply does not auto-scroll, which is
 * the rule's safe side.
 *
 * Nothing here polls. It listens to the scroller it was given, a pointer
 * release anywhere, and - only while its button is showing - resize and
 * scroll, to keep the button over the scroller.
 */
(function (root) {
  'use strict';
  if (!root || !root.document) return;
  if (typeof root.pineStick === 'function' && root.pineStick.version >= 1) return;

  var doc = root.document;
  var VERSION = 1;
  var SLACK = 32;                  /* px from the edge that still counts as "at it" */
  var live = [];                   /* instances with a pointer on them or a button up */

  function css() {
    if (doc.getElementById('pineStickStyle')) return;
    var s = doc.createElement('style');
    s.id = 'pineStickStyle';
    s.textContent = [
      '.pine-stick-jump{position:fixed;z-index:2147482000;display:none;',
      'align-items:center;gap:5px;height:28px;min-width:28px;margin:0;',
      'padding:0 9px;box-sizing:border-box;border-radius:14px;',
      'border:1px solid rgba(101,199,218,.7);background:rgba(8,16,24,.93);',
      'color:#d4eef6;font:600 11px/1 system-ui,-apple-system,"Segoe UI",sans-serif;',
      'letter-spacing:.02em;cursor:pointer;box-shadow:0 2px 10px rgba(0,0,0,.5);',
      'pointer-events:auto;-webkit-tap-highlight-color:transparent}',
      '.pine-stick-jump.on{display:inline-flex}',
      '.pine-stick-jump:hover{background:rgba(18,40,52,.96)}',
      '.pine-stick-jump:focus-visible{outline:2px solid #65c7da;outline-offset:2px}',
      '.pine-stick-ico{display:inline-flex;width:14px;height:14px;',
      'align-items:center;justify-content:center}',
      '.pine-stick-ico svg{width:14px;height:14px;fill:currentColor}',
      '.pine-stick-ico.down svg{transform:rotate(180deg)}',
      '.pine-stick-chev{display:inline-block;width:7px;height:7px;',
      'border-left:2px solid currentColor;border-top:2px solid currentColor;',
      'transform:translateY(2px) rotate(45deg)}',
      '.pine-stick-ico.down .pine-stick-chev{transform:translateY(-2px) rotate(225deg)}',
      '.pine-stick-n:empty{display:none}'
    ].join('');
    (doc.head || doc.documentElement).appendChild(s);
  }

  function isEditable(node) {
    if (!node || node.nodeType !== 1) return false;
    if (node.isContentEditable) return true;
    var tag = node.tagName;
    if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (tag !== 'INPUT') return false;
    var type = String(node.type || 'text').toLowerCase();
    return !/^(button|submit|reset|checkbox|radio|range|color|file|image)$/.test(type);
  }

  /* A pointer released ANYWHERE ends every hold - the finger may leave the
     scroller before it lifts. Capture, so a handler that stops propagation
     cannot strand a hold; and a mouse that comes back with no button down
     (released outside the window) ends it too. */
  var anyDown = false;
  function released() {
    if (!anyDown) return;
    anyDown = false;
    for (var i = live.length - 1; i >= 0; i -= 1) {
      live[i]._down = false;
      if (!live[i]._shown) live.splice(i, 1);
    }
  }
  root.addEventListener('pointerup', released, true);
  root.addEventListener('pointercancel', released, true);
  root.addEventListener('touchend', released, true);
  root.addEventListener('touchcancel', released, true);
  root.addEventListener('dragend', released, true);
  root.addEventListener('blur', released);
  root.addEventListener('pointermove', function (ev) {
    if (anyDown && ev && ev.buttons === 0 && ev.pointerType === 'mouse') released();
  }, true);

  var placing = 0;
  function placeAll() {
    if (placing) return;
    var any = false;
    for (var k = 0; k < live.length; k += 1) { if (live[k]._shown) { any = true; break; } }
    if (!any) return;
    var raf = root.requestAnimationFrame || function (fn) { return root.setTimeout(fn, 16); };
    placing = raf(function () {
      placing = 0;
      for (var i = 0; i < live.length; i += 1) {
        if (live[i]._shown) live[i]._place();
      }
    });
  }
  root.addEventListener('resize', placeAll);
  doc.addEventListener('scroll', placeAll, true);   /* any scroller may carry this one */

  function enlist(st) { if (live.indexOf(st) < 0) live.push(st); }
  function unlist(st) {
    var at = live.indexOf(st);
    if (at >= 0) live.splice(at, 1);
  }

  function Stick(box, opts) {
    var st = this;
    opts = opts || {};
    st.box = box;
    st.edge = opts.edge === 'top' ? 'top' : 'bottom';
    st.slack = Number(opts.slack) >= 0 ? Number(opts.slack) : SLACK;
    st.opts = opts;
    st.count = 0;
    st._down = false;
    st._btn = null;
    st._shown = false;
    st._owed = null;               /* the scrollTop a restore of ours just set */
    st._stuck = st.atLatest();

    st._onScroll = function () {
      /* Every scroll decides it, the operator's and ours alike - except the
         one a restore of ours just made: a reader who was at the latest
         edge and paused there to examine a row is still at it, although
         holding their row still has taken the scroll off the edge. */
      if (st._owed !== null && Math.abs(box.scrollTop - st._owed) <= 1) {
        st._owed = null;
        return;
      }
      st._owed = null;
      st._stuck = st.atLatest();
      if (st._stuck && opts.autoHide !== false) st.clear();
      else if (st._shown) st._place();
    };
    st._onDown = function (ev) {
      if (ev && ev.button > 0) return;            /* a right-click is not a hold */
      st._down = true;
      anyDown = true;
      enlist(st);
    };
    box.addEventListener('scroll', st._onScroll, {passive: true});
    /* Capture: a row that stops its own pointerdown still counts as a hand
       on this scroller. */
    box.addEventListener('pointerdown', st._onDown, {passive: true, capture: true});
    box.addEventListener('touchstart', st._onDown, {passive: true, capture: true});
    if (typeof root.IntersectionObserver === 'function') {
      /* A view switched away (display:none) must take its button with it,
         and bring it back when it returns. */
      try {
        st._seen = new root.IntersectionObserver(function (list) {
          var on = list.length && list[list.length - 1].isIntersecting;
          if (!on) st._hide(true);
          else if (st.count > 0 && !st._stuck) st._show();
        });
        st._seen.observe(box);
      } catch (err) { st._seen = null; }
    }
  }

  Stick.prototype.atLatest = function () {
    var b = this.box;
    if (!b) return true;
    if (this.edge === 'top') return b.scrollTop <= this.slack;
    return b.scrollHeight - b.scrollTop - b.clientHeight <= this.slack;
  };

  /* Looking at something: nothing moves under it. */
  Stick.prototype.examining = function () {
    var b = this.box;
    if (!b) return false;
    if (this._down) return true;
    try {
      var sel = root.getSelection ? root.getSelection() : null;
      if (sel && sel.rangeCount && !sel.isCollapsed
          && ((sel.anchorNode && b.contains(sel.anchorNode))
              || (sel.focusNode && b.contains(sel.focusNode)))) return true;
    } catch (err) { /* no selection API here */ }
    var active = doc.activeElement;
    if (active && active !== b && b.contains(active) && isEditable(active)) return true;
    if (typeof this.opts.examining === 'function') {
      try { if (this.opts.examining(b)) return true; } catch (err) { /* ask again next time */ }
    }
    return false;
  };

  Stick.prototype.following = function () {
    return !!this._stuck && !this.examining();
  };

  Stick.prototype._toLatest = function () {
    var b = this.box;
    b.scrollTop = this.edge === 'top' ? 0 : b.scrollHeight;
    this._stuck = true;
  };

  /* New content arrived at the latest edge: go to it if the operator is
     there, otherwise count it on the button and leave the page alone. */
  Stick.prototype.follow = function () {
    if (!this.box) return false;
    if (this.following()) {
      this._toLatest();
      this.clear();
      return true;
    }
    this.note(1);
    return false;
  };

  /* A live row moved: bring it into view INSIDE this scroller - never an
     ancestor, never the page - and only for an operator who is following. */
  Stick.prototype.reveal = function (node, how) {
    var b = this.box;
    if (!b || !node || !b.contains(node)) return false;
    if (!this.following()) { this.note(1); return false; }
    var lip = b.getBoundingClientRect();
    var seat = node.getBoundingClientRect();
    if (!(seat.height > 0) || !(lip.height > 0)) return false;
    var delta = 0;
    if (how === 'center') {
      delta = (seat.top + seat.height / 2) - (lip.top + lip.height / 2);
    } else if (seat.top < lip.top) {
      delta = seat.top - lip.top;
    } else if (seat.bottom > lip.bottom) {
      delta = Math.min(seat.bottom - lip.bottom, seat.top - lip.top);
    }
    if (Math.abs(delta) < 1) return false;
    b.scrollTop = Math.max(0, b.scrollTop + delta);
    return true;
  };

  /* Something new, while the operator is elsewhere: the button says so. */
  Stick.prototype.note = function (n) {
    this.count += Math.max(1, Number(n) || 1);
    if (this.opts.button === false) return;
    this._show();
  };

  /* The explicit way back. */
  Stick.prototype.jump = function () {
    var b = this.box;
    if (!b) return;
    this._down = false;
    if (typeof this.opts.jump === 'function') {
      try { this.opts.jump(b); } catch (err) { /* the button still goes */ }
    } else {
      this._toLatest();
    }
    this._stuck = true;
    this.clear();
    if (typeof this.opts.onJump === 'function') {
      try { this.opts.onJump(b); } catch (err) { /* the jump happened */ }
    }
  };

  Stick.prototype.clear = function () {
    this.count = 0;
    var n = this._btn && this._btn.querySelector('.pine-stick-n');
    if (n && n.textContent) n.textContent = '';
    this._hide(false);
  };

  /* The reader's place: the first row that is on the glass, how far down
     the scroller it sits, and enough to find it again after a rebuild. */
  /* `force`: measure the place even for a reader at the latest edge - for
     a caller whose "latest" is a live row rather than an edge. */
  Stick.prototype.anchor = function (force) {
    var b = this.box;
    var hold = {top: b ? b.scrollTop : 0, following: !force && this.following(),
                stuck: !!this._stuck, forced: !!force, node: null, row: null};
    if (!b || hold.following) return hold;
    var rows = this.opts.rows ? b.querySelectorAll(this.opts.rows) : b.children;
    var lip = b.getBoundingClientRect();
    for (var i = 0; i < rows.length; i += 1) {
      var r = rows[i].getBoundingClientRect();
      if (!(r.height > 0) || r.bottom <= lip.top + 1) continue;
      hold.row = rows[i];
      hold.index = i;
      hold.rowAt = r.top - lip.top;
      hold.key = this.opts.key ? rows[i].getAttribute(this.opts.key) : null;
      hold.text = String(rows[i].textContent || '').slice(0, 96);
      break;
    }
    /* A scroller whose children are a few tall sections: the place is the
       element under the reader's eye inside the section, not the section -
       rows added inside it above the eye must count as "above". */
    var node = hold.row;
    if (node && !this.opts.rows && !this.opts.key) {
      for (var depth = 0; depth < 12 && node.children && node.children.length
           && node.getBoundingClientRect().height > Math.max(120, lip.height / 2); depth += 1) {
        var inner = null;
        for (var j = 0; j < node.children.length; j += 1) {
          var q = node.children[j].getBoundingClientRect();
          if (q.height > 0 && q.bottom > lip.top + 1) { inner = node.children[j]; break; }
        }
        if (!inner) break;
        node = inner;
      }
    }
    if (node) {
      hold.node = node;
      hold.at = node.getBoundingClientRect().top - lip.top;
    }
    return hold;
  };

  /* The held element, or its row, or - after a rebuild - the row with the
     same key, or the same words nearest the same place. */
  Stick.prototype._find = function (hold) {
    var b = this.box;
    if (hold.node && hold.node.isConnected && b.contains(hold.node)) {
      return {node: hold.node, at: hold.at};
    }
    if (hold.row && hold.row.isConnected && b.contains(hold.row)) {
      return {node: hold.row, at: hold.rowAt};
    }
    var rows = this.opts.rows ? b.querySelectorAll(this.opts.rows) : b.children;
    var i;
    if (hold.key) {
      for (i = 0; i < rows.length; i += 1) {
        if (rows[i].getAttribute(this.opts.key) === hold.key) return {node: rows[i], at: hold.rowAt};
      }
    }
    if (hold.text) {
      var best = null, bestGap = Infinity;
      for (i = 0; i < rows.length; i += 1) {
        if (String(rows[i].textContent || '').slice(0, 96) !== hold.text) continue;
        var gap = Math.abs(i - hold.index);
        if (gap < bestGap) { best = rows[i]; bestGap = gap; }
      }
      if (best) return {node: best, at: hold.rowAt};
    }
    return null;
  };

  /* Back to that place - or to the latest edge for a reader who was
     following. `fresh` says new rows came in (true, or how many), for the
     button's count. */
  Stick.prototype.restore = function (hold, fresh) {
    var b = this.box;
    if (!b || !hold) return;
    if (hold.following) {
      if (this.following()) { this._toLatest(); this.clear(); }
      else if (fresh) this.note(fresh);
      return;
    }
    var got = this._find(hold);
    if (got) {
      var drift = (got.node.getBoundingClientRect().top - b.getBoundingClientRect().top) - got.at;
      if (Math.abs(drift) > 0.5) b.scrollTop = Math.max(0, b.scrollTop + drift);
    } else if (b.scrollTop !== hold.top) {
      b.scrollTop = hold.top;
    }
    /* Whatever moved the scroll to hold the reader still - this, or the
       browser's own scroll anchoring during the layout just forced - the
       scroll event it raises is not the operator's. A reader who was at
       the latest edge (pausing there to examine) is still at it. */
    var st = this;
    st._owed = b.scrollTop;
    if (!hold.forced) st._stuck = !!hold.stuck;
    var raf = root.requestAnimationFrame || function (fn) { return root.setTimeout(fn, 16); };
    raf(function () { st._owed = null; });
    if (fresh) this.note(fresh);
  };

  Stick.prototype.keep = function (fn, fresh) {
    var hold = this.anchor();
    try { if (typeof fn === 'function') fn(); }
    finally { this.restore(hold, fresh); }
  };

  Stick.prototype._button = function () {
    if (this._btn) return this._btn;
    css();
    var st = this;
    var down = st.edge === 'bottom';
    var label = st.opts.label || (down ? 'Jump to the latest' : 'Jump to the newest');
    var b = doc.createElement('button');
    b.type = 'button';
    b.className = 'pine-stick-jump';
    b.title = label;
    b.setAttribute('aria-label', label);
    var icon = typeof root.pineIcon === 'function' ? root.pineIcon(st.opts.icon || 'c:arrow--up') : '';
    b.innerHTML = '<span class="pine-stick-ico' + (down && !st.opts.icon ? ' down' : '') + '">'
      + (icon || '<i class="pine-stick-chev"></i>') + '</span><span class="pine-stick-n"></span>';
    b.addEventListener('click', function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      st.jump();
    });
    st._btn = b;
    return b;
  };

  Stick.prototype._show = function () {
    if (!this.box || !this.box.isConnected) { this.dispose(); return; }
    var b = this._button();
    if (!b.isConnected) (doc.body || doc.documentElement).appendChild(b);
    var n = b.querySelector('.pine-stick-n');
    var words = this.count > 0 ? this.count + ' new' : '';
    if (n && n.textContent !== words) n.textContent = words;
    this._shown = true;
    enlist(this);
    this._place();
  };

  Stick.prototype._hide = function (keepCount) {
    if (this._btn) this._btn.classList.remove('on');
    if (!keepCount) this._shown = false;
    if (!this._down && !this._shown) unlist(this);
  };

  /* Over the scroller's latest edge, inside what is actually visible of it -
     and not at all when something else is on top of it there. */
  Stick.prototype._place = function () {
    var box = this.box, b = this._btn;
    if (!b) return;
    if (!box || !box.isConnected) { this.dispose(); return; }
    var r = box.getBoundingClientRect();
    var vw = root.innerWidth || doc.documentElement.clientWidth;
    var vh = root.innerHeight || doc.documentElement.clientHeight;
    var top = Math.max(r.top, 0), bottom = Math.min(r.bottom, vh);
    var right = Math.min(r.right, vw), left = Math.max(r.left, 0);
    if (bottom - top < 40 || right - left < 60) { b.classList.remove('on'); return; }
    b.classList.add('on');
    var w = b.offsetWidth || 64, h = b.offsetHeight || 28;
    var y = this.edge === 'top' ? top + 8 : bottom - h - 10;
    /* The right-hand corner first; a scroller that keeps its own tools
       there (the Script view's crawl) gets the button at its middle, or
       its left, instead - whichever spot the scroller itself is showing. */
    var spots = [Math.max(left + 4, right - w - 14),
                 left + (right - left - w) / 2,
                 left + 10];
    var seen = false;
    b.style.pointerEvents = 'none';
    for (var i = 0; i < spots.length && !seen; i += 1) {
      var hit = null;
      try { hit = doc.elementFromPoint(spots[i] + w / 2, y + h / 2); } catch (err) { hit = null; }
      if (!hit || hit === box || box.contains(hit)) {
        b.style.left = Math.round(spots[i]) + 'px';
        b.style.top = Math.round(y) + 'px';
        seen = true;
      }
    }
    b.style.pointerEvents = '';
    if (!seen) b.classList.remove('on');
  };

  Stick.prototype.dispose = function () {
    var box = this.box;
    if (box) {
      box.removeEventListener('scroll', this._onScroll);
      box.removeEventListener('pointerdown', this._onDown, true);
      box.removeEventListener('touchstart', this._onDown, true);
      if (box.__pineStick === this) box.__pineStick = null;
    }
    if (this._seen) { try { this._seen.disconnect(); } catch (err) { /* gone */ } }
    if (this._btn && this._btn.parentNode) this._btn.parentNode.removeChild(this._btn);
    this._btn = null;
    this._shown = false;
    unlist(this);
    this.box = null;
  };

  function pineStick(box, opts) {
    if (!box || box.nodeType !== 1) return null;
    var st = box.__pineStick;
    if (st && st.box === box) return st;
    st = new Stick(box, opts);
    box.__pineStick = st;
    return st;
  }

  /* For a scroller that is rebuilt as a NEW element each paint: take the
     place from the old one, put it on the new one. */
  pineStick.hold = function (el, opts) {
    var st = pineStick(el, opts);
    return st ? st.anchor() : null;
  };
  pineStick.put = function (el, hold, opts, fresh) {
    var st = pineStick(el, opts);
    if (!st || !hold) return st;
    st._stuck = !!hold.following;
    st.restore(hold, fresh);
    return st;
  };
  pineStick.examining = function (el, opts) {
    var st = pineStick(el, opts);
    return st ? st.examining() : false;
  };
  pineStick.version = VERSION;

  root.pineStick = pineStick;
  if (typeof module !== 'undefined' && module.exports) module.exports = pineStick;
})(typeof window !== 'undefined' ? window : this);
