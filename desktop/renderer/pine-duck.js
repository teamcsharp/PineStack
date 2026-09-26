/* PineDuck - the broadcast steps back while the operator deals with a report.
 *
 * 2026-09-14: "Whenever I'm filing a report or I'm doing anything involving
 * a report, lower the broadcast to 10%. Like basically I want you to duck
 * the audio when I'm dealing with the report. So if I'm interacting with
 * one of the systems that's a diagnostic, then duck the broadcast audio.
 * And any time that I'm dealing with dictation, always duck the audio
 * completely or to 2%."
 *
 * One road for every surface, because there were two before and neither
 * fitted: talk-dot ducked to 0.12 for exactly as long as it listened, and
 * PineAir (the sampler's) MUTES - a boolean, no level, and off by a
 * preference. This one is levelled and reference counted:
 *
 *   PineDuck.hold(name, level, el)   the broadcast goes to `level` (0..1)
 *                                    while the hold stands; the lowest
 *                                    standing level wins
 *   PineDuck.release(name)           the hold ends; the last one out puts
 *                                    the sound back
 *
 * A HOLD IS TIED TO WHAT OPENED IT. Every sheet, pad and fold hands over
 * its element; a sweep twice a second releases any hold whose element has
 * left the document, so a route that closes a sheet without telling us
 * (the panel tearing a view down, the kiosk relaunching) cannot leave the
 * radio quiet. A hold without an element gets a ceiling instead - 90 s,
 * the same figure PineAir chose, longer than any dictation.
 *
 * WHAT IS DUCKED: every <audio> and <video> on the page except the
 * sampler's own (a pad the operator is auditioning is not the broadcast),
 * which is the set talk-dot ducked and the set the panel plays the show
 * through. New elements that appear while a hold stands (the SFX set's
 * next clip) are caught by the same sweep. The level is applied as
 * min(the element's own volume, level) and the element's own volume is
 * remembered; on release it goes back ONLY if nobody moved it in between
 * (the terminals table or the operator may have), so a stale number is
 * never written over a fresh one.
 *
 * ES5, one IIFE, no dependencies. Loaded before talk-dot.js.
 */
(function (root) {
  'use strict';
  var doc = root.document;
  var holds = Object.create(null);      /* name -> {level, el, until} */
  var lowered = [];                     /* [{node, was, set}] */
  var current = 1;                      /* the level in force; 1 = none */
  var sweeper = null;
  var CEILING_MS = 90000;
  var SWEEP_MS = 500;

  function isOurs(node) {
    if (!node || typeof node.volume !== 'number') return false;
    if (node.closest && node.closest('#sampler, .pb-sampler')) return false;
    // A gallery preview is the foreground source the operator is trying to
    // hear. Its hold lowers the station beneath it, never the preview itself.
    if (node.closest && node.closest('.pine-voice-ad-popup')) return false;
    return true;
  }

  function level() {
    var low = 1;
    for (var k in holds) {
      if (!holds[k]) continue;
      if (holds[k].level < low) low = holds[k].level;
    }
    return low;
  }

  function nodes() {
    var out = [];
    try {
      var all = doc.querySelectorAll('audio, video');
      for (var i = 0; i < all.length; i += 1) if (isOurs(all[i])) out.push(all[i]);
    } catch (err) { /* no document */ }
    return out;
  }

  function findLowered(node) {
    for (var i = 0; i < lowered.length; i += 1) if (lowered[i].node === node) return lowered[i];
    return null;
  }

  /* Bring every element to `lvl`. An element already on the list keeps
   * its remembered `was`; a new one is remembered now. */
  function apply(lvl) {
    var list = nodes();
    for (var i = 0; i < list.length; i += 1) {
      var node = list[i];
      var got = findLowered(node);
      try {
        if (!got) {
          got = {node: node, was: node.volume, set: 0};
          lowered.push(got);
        } else if (Math.abs(node.volume - got.set) > 0.001) {
          /* Somebody moved the canonical level while this hold stood. Both
             raises and cuts are authoritative; release must restore the new
             value, never the number captured when the sheet opened. */
          got.was = node.volume;
        }
        got.set = Math.min(got.was, lvl);
        node.volume = got.set;
      } catch (err) { /* a detached element */ }
    }
  }

  function restore() {
    for (var i = 0; i < lowered.length; i += 1) {
      var got = lowered[i];
      try {
        if (Math.abs(got.node.volume - got.set) <= 0.001) got.node.volume = got.was;
      } catch (err) { /* gone */ }
    }
    lowered = [];
  }

  function settle() {
    var lvl = level();
    if (lvl >= 1) {
      current = 1;
      restore();
      if (sweeper) { clearInterval(sweeper); sweeper = null; }
      try {
        if (root.pineLevels && typeof root.pineLevels.refresh === 'function') {
          root.pineLevels.refresh('video');
        }
      } catch (err) { /* no native wall on this surface */ }
      return;
    }
    current = lvl;
    apply(lvl);
    if (!sweeper) sweeper = setInterval(sweep, SWEEP_MS);
    try {
      if (root.pineLevels && typeof root.pineLevels.refresh === 'function') {
        root.pineLevels.refresh('video');
      }
    } catch (err) { /* no native wall on this surface */ }
  }

  /* Twice a second while anything is held: drop holds whose element has
   * left the page or whose ceiling has passed, and catch elements that
   * appeared since. */
  function sweep() {
    var now = Date.now();
    var wasReporting = reporting();
    var changed = false;
    for (var k in holds) {
      var h = holds[k];
      if (!h) continue;
      if (h.el && !h.el.isConnected) { delete holds[k]; changed = true; continue; }
      if (!h.el && h.until && now > h.until) {
        delete holds[k];
        changed = true;
        try { root.console.warn('pine duck: "' + k + '" held the broadcast for 90s and never let go - giving it back'); } catch (err) { /* quiet */ }
      }
    }
    if (changed) settle();
    else if (current < 1) apply(current);
    if (changed && wasReporting !== reporting()) tell();   /* 2026-09-15 (#1167) */
  }

  /* 2026-09-15 (#1167): WHO ELSE NEEDS TO KNOW THE OPERATOR IS FILING.
   *
   * "If I'm in endless video mode and I bring up the file report screen or
   *  any report screen, remove the video from displaying and mute the audio
   *  for a moment while I narrate to the dictation system. Don't have the
   *  audio playing and don't have videos popping up during the process of
   *  filing tickets. Resume everything after the ticket following screen
   *  has been closed or sent."
   *
   * Ducking the volume was only half of it: a clip still playing behind a
   * report pad is still moving, still starting the next one, and still
   * asking for his eye while he is dictating. Every surface that raises a
   * report already tells this module so; it now tells anyone who asks
   * back, so the video roads can stand down and come back on the same
   * signal rather than each inventing its own idea of "a report is open". */
  var watchers = [];

  function reporting() {
    for (var k in holds) if (holds[k]) return true;
    return false;
  }

  function tell() {
    var on = reporting();
    for (var i = 0; i < watchers.length; i += 1) {
      try { watchers[i](on, current); } catch (err) { /* a watcher must not stop the duck */ }
    }
  }

  function watch(fn) {
    if (typeof fn !== 'function') return function () { /* nothing to undo */ };
    watchers.push(fn);
    try { fn(reporting(), current); } catch (err) { /* fine */ }
    return function () {
      for (var i = 0; i < watchers.length; i += 1) {
        if (watchers[i] === fn) { watchers.splice(i, 1); return; }
      }
    };
  }

  function hold(name, lvl, el) {
    var key = String(name || 'hold');
    var value = Number(lvl);
    if (!(value >= 0 && value <= 1)) value = 0.1;
    var was = reporting();
    holds[key] = {level: value, el: el || null, until: el ? 0 : Date.now() + CEILING_MS};
    settle();
    if (!was) tell();
    return current;
  }

  function release(name) {
    var key = String(name || 'hold');
    if (!holds[key]) return current;
    delete holds[key];
    settle();
    if (!reporting()) tell();
    return current;
  }

  function releaseAll() {
    var was = reporting();
    holds = Object.create(null);
    settle();
    if (was) tell();
  }

  /* Anything a previous life of this page left lowered, put back. A
   * reload does not un-duck what a crash left, and talk-dot's old 0.12
   * had the same tell. Only the two levels this module sets are touched. */
  function unstick() {
    var list = nodes();
    for (var i = 0; i < list.length; i += 1) {
      var v = list[i].volume;
      if ((v > 0.09 && v < 0.11) || (v > 0.015 && v < 0.025)) {
        try { list[i].volume = 1; } catch (err) { /* fine */ }
      }
    }
  }
  try { unstick(); } catch (err) { /* no document yet */ }

  root.PineDuck = {
    hold: hold,
    release: release,
    releaseAll: releaseAll,
    level: function () { return current; },
    holds: function () { var out = []; for (var k in holds) if (holds[k]) out.push({name: k, level: holds[k].level}); return out; },
    /* 2026-09-15 (#1167): is a report surface open right now, and tell me
       when that changes. The sweep that drops a hold whose element has left
       the page calls settle(), which calls this, so a sheet torn out
       without closing still ends the quiet. */
    reporting: reporting,
    watch: watch,
    refresh: function () { if (current < 1) apply(current); return current; },
    REPORT: 0.10,       /* a report, an inbox, a diagnostic: the broadcast at 10% */
    DICTATION: 0        /* dictation owns the microphone: complete silence */
  };
})(typeof window !== 'undefined' ? window : globalThis);
