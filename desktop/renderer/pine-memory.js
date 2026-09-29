/* window.PineMemory - the page's decoder budget. [memdiet]
 *
 * The PineTab (3.9 GB, most of it spoken for) was killed by Android's
 * lowmemorykiller on 2026-09-29. The page's JS heap was small; what the page
 * costs the tablet lives OUTSIDE the heap - every <video> that has loaded a
 * frame holds a hardware decoder and its graphics buffers until its source is
 * let go, playing or not, on screen or not, even detached from the page.
 * Each surface already keeps its own "one video at a time" rule; this is the
 * floor under all of them, for the loops nobody is watching:
 *
 *   OFF SCREEN  a muted looping video (a thumbnail, a boomerang) out of view
 *               for OFF_MS is paused and its source let go (removeAttribute
 *               ('src') + load() - the only thing that frees the decoder);
 *               back in view, the source returns and it plays again.
 *   CAP         at most CAP muted loops play at once; the one that started
 *               longest ago (off-screen ones first) is let go. A video inside
 *               [data-pine-keep], the pinned Message-view bubble (.sp-mv-pinned)
 *               or the roll popup (.rt-pip) is never counted or touched.
 *   DETACHED    a video taken out of the page and not put back within
 *               DETACH_MS is let go (paused or muted ones only - an audible
 *               player is somebody's business).
 *   HIDDEN      the page hidden: every muted loop is let go; shown again,
 *               the ones in view come back.
 *   TRIM        PineMemory.trim(level) - the kiosk's onTrimMemory - lets go
 *               every muted loop that is not in view and not kept, and tells
 *               the page ('pine-memory-trim' on window) so views can drop
 *               their own caches.
 *
 * Audible playback is never paused by this file. Nothing here runs a timer
 * while nothing changes: an IntersectionObserver, a MutationObserver that
 * only looks at element nodes, and the media 'play' event (captured).
 *
 * PineMemory.stats() -> {video, withSrc, playing, parked, img, canvas,
 *                        canvasMpx, heapMb, counts}
 */
(function (root) {
  'use strict';
  if (!root || !root.document || root.PineMemory) return;
  var doc = root.document;
  var CAP = (function () {   /* [memprefs] the operator's loop limit, default 2 */
    try { var v = parseInt(root.localStorage.getItem('pine.mem.loops'), 10); return v >= 1 && v <= 6 ? v : 2; }
    catch (e) { return 2; }
  })(), OFF_MS = 1500, DETACH_MS = 2000;
  var KEEP = '[data-pine-keep], .sp-mv-pinned, .rt-pip';
  var counts = {parked: 0, restored: 0, capped: 0, detached: 0, hidden: 0, trims: 0};
  var order = [];          /* muted loops in the order they started playing */
  var io = null, mo = null;

  function isVideo(v) { return !!(v && v.tagName === 'VIDEO'); }
  function isLoop(v) { return isVideo(v) && v.muted && v.loop; }
  function kept(v) {
    try { return !!(v.closest && v.closest(KEEP)); } catch (e) { return false; }
  }
  function inView(v) { return v.__pmIn !== false && !doc.hidden; }

  /* let go: the decoder and its buffers are freed only when the source is */
  function park(v, why) {
    if (!isVideo(v) || v.__pmParked) return false;
    var src = v.getAttribute('src');
    if (!src) return false;                  /* <source> children or empty: leave it */
    v.__pmParked = {src: src, play: !v.paused || v.autoplay, t: v.currentTime || 0, why: why};
    try { v.pause(); } catch (e) { /* gone */ }
    try { v.removeAttribute('src'); v.load(); } catch (e) { /* gone */ }
    var k = order.indexOf(v);
    if (k >= 0) order.splice(k, 1);
    counts.parked += 1;
    if (counts[why] !== undefined) counts[why] += 1;
    return true;
  }

  function restore(v) {
    var p = v && v.__pmParked;
    if (!p) return;
    v.__pmParked = null;
    if (v.getAttribute('src')) return;       /* the page gave it a new source meanwhile */
    try {
      v.setAttribute('src', p.src);
      if (p.t) { try { v.currentTime = p.t; } catch (e) { /* not seekable yet */ } }
      if (p.play) { var pr = v.play(); if (pr && pr.catch) pr.catch(function () { /* muted autoplay refused */ }); }
    } catch (e) { /* gone */ }
    counts.restored += 1;
  }

  function enforceCap() {
    var live = order.filter(function (v) { return v.isConnected && !v.paused && isLoop(v) && !kept(v); });
    order = order.filter(function (v) { return v.isConnected; });
    if (live.length <= CAP) return;
    live.sort(function (a, b) { return (inView(a) ? 1 : 0) - (inView(b) ? 1 : 0); });   /* off-screen first, then oldest */
    for (var i = 0; i < live.length - CAP; i += 1) park(live[i], 'capped');
  }

  function watch(v) {
    if (!isVideo(v) || v.__pmSeen) return;
    v.__pmSeen = true;
    if (io) { try { io.observe(v); } catch (e) { /* gone */ } }
  }

  function scan(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.tagName === 'VIDEO') { watch(node); if (node.__pmParked && inView(node)) restore(node); return; }
    if (!node.firstElementChild) return;
    var list = node.getElementsByTagName('video');
    for (var i = 0; i < list.length; i += 1) {
      watch(list[i]);
      if (list[i].__pmParked && inView(list[i])) restore(list[i]);
    }
  }

  function removed(node) {
    if (!node || node.nodeType !== 1) return;
    var list = node.tagName === 'VIDEO' ? [node]
      : (node.firstElementChild ? [].slice.call(node.getElementsByTagName('video')) : []);
    if (!list.length) return;
    setTimeout(function () {
      list.forEach(function (v) {
        if (v.isConnected) return;
        if (!v.paused && !v.muted) return;   /* an audible player is somebody's business */
        park(v, 'detached');
      });
    }, DETACH_MS);
  }

  function onIntersect(entries) {
    entries.forEach(function (e) {
      var v = e.target;
      v.__pmIn = e.isIntersecting;
      clearTimeout(v.__pmOff);
      if (e.isIntersecting) { if (v.__pmParked && !doc.hidden) restore(v); return; }
      v.__pmOff = setTimeout(function () {
        if (v.__pmIn === false && isLoop(v) && !kept(v)) park(v, 'offscreen');
      }, OFF_MS);
    });
  }

  function onPlay(ev) {
    var v = ev.target;
    if (!isLoop(v)) return;
    var k = order.indexOf(v);
    if (k >= 0) order.splice(k, 1);
    order.push(v);
    enforceCap();
  }

  function each(fn) {
    var list = doc.getElementsByTagName('video');
    for (var i = list.length - 1; i >= 0; i -= 1) fn(list[i]);
  }

  function onVisibility() {
    if (doc.hidden) {
      each(function (v) { if (isLoop(v) && !kept(v)) park(v, 'hidden'); });
    } else {
      each(function (v) { if (v.__pmParked && v.__pmIn !== false) restore(v); });
    }
  }

  function trim(level) {
    counts.trims += 1;
    var n = 0;
    each(function (v) {
      if (isLoop(v) && !kept(v) && (v.__pmIn === false || doc.hidden || Number(level) >= 15)) {
        if (park(v, 'trim')) n += 1;
      }
    });
    try {
      var ev = doc.createEvent('CustomEvent');
      ev.initCustomEvent('pine-memory-trim', false, false, {level: Number(level) || 0});
      root.dispatchEvent(ev);
    } catch (e) { /* no listeners */ }
    return n;
  }

  function stats() {
    var vids = doc.getElementsByTagName('video'), withSrc = 0, playing = 0, parked = 0;
    for (var i = 0; i < vids.length; i += 1) {
      if (vids[i].getAttribute('src') || vids[i].currentSrc) withSrc += 1;
      if (!vids[i].paused) playing += 1;
      if (vids[i].__pmParked) parked += 1;
    }
    var cvs = doc.getElementsByTagName('canvas'), px = 0;
    for (var j = 0; j < cvs.length; j += 1) px += (cvs[j].width || 0) * (cvs[j].height || 0);
    var mem = root.performance && root.performance.memory;
    return {video: vids.length, withSrc: withSrc, playing: playing, parked: parked,
      img: doc.images.length, canvas: cvs.length, canvasMpx: Math.round(px / 1e5) / 10,
      heapMb: mem ? Math.round(mem.usedJSHeapSize / 1048576 * 10) / 10 : null,
      counts: JSON.parse(JSON.stringify(counts))};
  }

  function start() {
    if (typeof root.IntersectionObserver === 'function') {
      io = new root.IntersectionObserver(onIntersect, {threshold: 0});
    }
    if (typeof root.MutationObserver === 'function') {
      mo = new root.MutationObserver(function (list) {
        for (var i = 0; i < list.length; i += 1) {
          var m = list[i], k;
          for (k = 0; k < m.addedNodes.length; k += 1) scan(m.addedNodes[k]);
          for (k = 0; k < m.removedNodes.length; k += 1) removed(m.removedNodes[k]);
        }
      });
      mo.observe(doc.documentElement, {childList: true, subtree: true});
    }
    doc.addEventListener('play', onPlay, true);
    doc.addEventListener('visibilitychange', onVisibility);
    each(watch);
  }

  root.PineMemory = {stats: stats, trim: trim, park: park, restore: restore,
    CAP: CAP, OFF_MS: OFF_MS, DETACH_MS: DETACH_MS};
  if (doc.documentElement) start();
  else doc.addEventListener('DOMContentLoaded', start);
}(typeof window !== 'undefined' ? window : this));
