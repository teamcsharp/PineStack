r"""[reply-gap:buildup] The Script view: pause, then the card's whole Rolodex, then the words.
[reply-gap:dual] one track, two thumbs; [reply-gap:square] square toolbar icons.

2026-09-30, the operator:
  "i want to be able to see every RNG rolodex roulette buildup for each card.
   The whole point of the timer was to allow these to play and be analyzed
   without them rushing or skipping animations" - "Pause, then buildup, then
   words".
  "I want these two bars shared together. So that way there's just two
   buttons can drag on it." - "make sure they're square icons."

  * THE TIMING CONTRACT (MV_BUILD) - the same numbers as reply_gap.py BUILD_*
    (tests/test_reply_gap_buildup_2026_09_30.cjs holds them equal). A card
    the station scheduled a buildup for (its clip's or row's `buildup_ms`)
    rolls every table at the contract's pace and is fitted to exactly that
    many ms: it starts buildup ms before its words, which start as its audio
    does. Its final height is reserved up front, and its tally stays in place
    under the words - nothing jumps.
  * The next card is known before its words: the page player's cue at the
    words' end ("pine-reply-gap": line id, buildup, the moment the next clip
    starts) between clips, the sounding clip's own next row inside a round.
  * The dice count down the PAUSE only; the buildup follows it; every message
    rolls when the roulette is on (a 120 ms watch, not the 250 ms-4 s feed).
  * One track, two thumbs (28 px targets, touch-action none): thumb A is the
    pause (and the whole pause with the roulette off), thumb B the roll's
    other end; the span between them is shaded; the same POST.
  * The seven toolbar icons are 34 px squares, centred in their row.

Usage: python3 tools/reply_gap_patch_ui3.py --check|--apply <script-page.js ...> <script-page.css ...>
--check: 0 ready, 2 applied, 1 broken."""
from __future__ import annotations

import os
import sys
from pathlib import Path

BLOCK_HEAD = "  /* [reply-gap] THE PAUSE BETWEEN REPLIES, ON THE TOOLBAR.\n"
BLOCK_END = "  function mount(node) {\n"
MARK = "[reply-gap:dual]"

NEW_BLOCK = r"""  /* [reply-gap] THE PAUSE BETWEEN REPLIES, ON THE TOOLBAR.
   *
   * "put a slider here for adjusting the space between dj replies and the
   *  sfx guy replies ... 1 second ... up to possibly 10 seconds ... as low
   *  as .2 seconds ... a 2nd slider for a roulette RNG roll after each reply
   *  ... a toggle to enable roulette rolls ... Show the rolling dice here."
   *
   * [reply-gap:dual] "I want these two bars shared together ... just two
   * buttons can drag on it." ONE track, TWO thumbs: thumb A is the pause
   * after every reply (0.2 - 10 s, default 1; with the roulette off, every
   * pause is thumb A), thumb B the roll's other end - with the toggle on each
   * pause is a System 3 roll landing BETWEEN the two thumbs, either way round
   * [reply-gap:between]. The station keeps the setting (/api/reply-gap).
   *
   * [reply-gap:buildup] Pause, then the card's whole Rolodex, then the words:
   * the dice count down the pause; the next card starts building exactly its
   * scheduled buildup before its words (the cue, or the sounding round's next
   * row, says which card and when). */
  var GAP_MIN = 0.2, GAP_MAX = 10, GAP_RANGE_MIN = 0.2, GAP_RANGE_MAX = 10;   /* [reply-gap:between] */
  var gapState = {gap: 1, range: 1, roll: false};
  var gapUi = null;
  var gapLoadedAt = 0;
  var gapSendTimer = 0;
  var gapHeldUntil = 0;             /* a hand on a thumb: a poll does not move it */
  var gapFired = Object.create(null);
  var gapLast = null;               /* the last pause rolled on this panel */
  var gapCueWired = false;          /* [reply-gap:dice] the player's cue, heard once */
  var gapPumpOn = false;            /* [reply-gap:buildup] the 120 ms watch */
  var mvUpcoming = null;            /* [reply-gap:buildup] the next card, before its words */

  function gapNum(v, d) { v = Number(v); return isFinite(v) ? v : d; }
  function gapClamp(v, lo, hi, d) {
    v = Math.round(gapNum(v, d) * 10) / 10;
    return Math.min(hi, Math.max(lo, v));
  }
  function gapWindow(g, r) {
    /* [reply-gap:between] "the dice should only be rolling values between
       slider 1 and slider 2" - the two thumbs are the roll's two ends */
    return [Math.min(g, r), Math.max(g, r)];
  }
  function gapFmt(s) { return gapNum(s, 0).toFixed(1) + ' s'; }
  function gapPct(v) { return (gapClamp(v, GAP_MIN, GAP_MAX, 1) - GAP_MIN) / (GAP_MAX - GAP_MIN) * 100; }
  /* the value under a point of the track, on the 0.1 s step */
  function gapValAt(x, left, width) {
    var f = width > 0 ? (x - left) / width : 0;
    return gapClamp(GAP_MIN + Math.max(0, Math.min(1, f)) * (GAP_MAX - GAP_MIN), GAP_MIN, GAP_MAX, 1);
  }

  function gapPaint() {
    if (!gapUi) return;
    var s = gapState;
    var w = gapWindow(s.gap, s.range);
    var a = gapPct(s.gap), b = gapPct(s.range);
    gapUi.a.style.left = a.toFixed(2) + '%';
    gapUi.b.style.left = b.toFixed(2) + '%';
    gapUi.span.style.left = Math.min(a, b).toFixed(2) + '%';
    gapUi.span.style.width = Math.abs(b - a).toFixed(2) + '%';
    gapUi.val.textContent = s.gap.toFixed(1) + 's – ' + s.range.toFixed(1) + 's';
    var aTip = 'Thumb A - the pause between replies: ' + gapFmt(s.gap) + ' (0.2 - 10 s). The silence after '
      + 'every reply on air - DJ to DJ, DJ to the SFX Guy, the SFX Guy to a DJ; with the roulette off every '
      + 'pause is this one. Station-wide - every listener hears this.';
    var bTip = 'Thumb B - the roulette\'s other end: ' + gapFmt(s.range) + ' (0.2 - 10 s). With the roll on, '
      + 'each pause is a System 3 roll landing between the two thumbs (now ' + w[0].toFixed(1) + ' - '
      + w[1].toFixed(1) + ' s). Station-wide - every listener hears this.';
    gapUi.a.title = aTip;
    gapUi.a.setAttribute('aria-label', 'Pause between replies');
    gapUi.a.setAttribute('aria-valuenow', s.gap.toFixed(1));
    gapUi.a.setAttribute('aria-valuetext', gapFmt(s.gap));
    gapUi.b.title = bTip;
    gapUi.b.setAttribute('aria-label', 'Roulette range end');
    gapUi.b.setAttribute('aria-valuenow', s.range.toFixed(1));
    gapUi.b.setAttribute('aria-valuetext', gapFmt(s.range));
    gapUi.dual.title = 'Drag thumb A (the pause) or thumb B (the roulette\'s other end): now '
      + gapFmt(s.gap) + ' and ' + gapFmt(s.range) + '.';
    var swTip = 'Roulette after each reply: ' + (s.roll ? 'ON - a System 3 roll picks each pause in '
      + w[0].toFixed(1) + ' - ' + w[1].toFixed(1) + ' s' : 'OFF - every pause is the fixed '
      + gapFmt(s.gap)) + '. Station-wide - every listener hears this. Tap to turn it '
      + (s.roll ? 'off.' : 'on.');
    gapUi.sw.title = swTip;
    gapUi.sw.setAttribute('aria-label', swTip);
    gapUi.sw.setAttribute('aria-checked', s.roll ? 'true' : 'false');
    gapUi.wrap.classList.toggle('sp-gap-on', !!s.roll);
    var dieTip = !s.roll ? 'The dice: the roulette is off. Turn it on and each reply\'s pause is rolled here.'
      : gapLast ? 'Last roll: d100 ' + gapLast.dice + ' - ' + gapFmt(gapLast.s) + ' before the next reply (range '
        + gapNum(gapLast.lo, w[0]).toFixed(1) + ' - ' + gapNum(gapLast.hi, w[1]).toFixed(1) + ' s). Tap to see it roll again.'
      : 'The dice: each reply\'s pause is rolled here as the reply ends (' + w[0].toFixed(1) + ' - '
        + w[1].toFixed(1) + ' s).';
    gapUi.die.title = dieTip;
    gapUi.die.setAttribute('aria-label', dieTip);
    gapUi.die.setAttribute('aria-disabled', s.roll ? 'false' : 'true');
  }

  function gapTake(got) {
    if (!got || typeof got !== 'object' || got.gap === undefined) return;
    if (Date.now() < gapHeldUntil) return;               /* the hand wins */
    gapState = {gap: gapClamp(got.gap, GAP_MIN, GAP_MAX, 1),
      range: gapClamp(got.range, GAP_RANGE_MIN, GAP_RANGE_MAX, 1), roll: !!got.roll};
    /* [reply-gap:dice] the square lands only on a pause this panel saw roll -
       a receipt from another road, painted still, read as a dead die */
    if (!gapState.roll) { gapCountStop(); gapIdle(); }
    gapPaint();
  }

  function gapLoad(force) {
    if (!mounted && !force) return;
    if (!force && Date.now() - gapLoadedAt < 20000) return;
    gapLoadedAt = Date.now();
    if (!api().get) return;
    Promise.resolve(api().get('/api/reply-gap?recent=1')).then(gapTake).catch(function () {});
  }

  function gapSend(now) {
    clearTimeout(gapSendTimer);
    gapSendTimer = 0;
    var go = function () {
      gapSendTimer = 0;
      if (!api().post) return;
      var body = {gap: gapState.gap, range: gapState.range, roll: !!gapState.roll,
        by: root.__pineNative ? 'tablet' : 'desk'};
      Promise.resolve(api().post('/api/reply-gap', body)).then(function (got) {
        if (gapUi) gapUi.wrap.classList.remove('sp-gap-unsaved');
        gapHeldUntil = 0;
        gapTake(got);
      }).catch(function () {
        if (gapUi) gapUi.wrap.classList.add('sp-gap-unsaved');
      });
    };
    if (now) go(); else gapSendTimer = setTimeout(go, 450);
  }

  /* The square's face: a reel of pauses that ends on the one rolled. */
  function gapFace(g, still) {
    if (!gapUi) return;
    var die = gapUi.die, reel = gapUi.reel;
    try { if (root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches) still = true; } catch (e) { still = true; }
    if (document.visibilityState && document.visibilityState !== 'visible') still = true;
    reel.textContent = '';
    var faces = [];
    var lo = gapNum(g.lo, GAP_MIN), hi = gapNum(g.hi, GAP_MAX);
    if (!still) {
      for (var k = 0; k < 9; k += 1) {
        var u = ((gapNum(g.dice, 50) * 37 + k * 53) % 100) / 100;
        faces.push((lo + u * (hi - lo)).toFixed(1));
      }
    }
    faces.push(gapNum(g.s, 0).toFixed(1));
    faces.forEach(function (f) { reel.appendChild(make('span', '', f)); });
    reel.style.setProperty('--reel-end', (-(faces.length - 1) * 22) + 'px');
    die.classList.remove('rolling', 'landed', 'sp-gap-fresh');
    void die.offsetWidth;                                   /* restart the animation */
    if (still) { die.classList.add('landed'); return; }
    var ms = Math.round(Math.min(900, Math.max(450, gapNum(g.s, 1) * 600)));
    die.style.setProperty('--ms', ms + 'ms');
    die.style.setProperty('--delay', '0ms');
    die.classList.add('rolling');
    setTimeout(function () {
      die.classList.remove('rolling');
      die.classList.add('landed');
    }, ms);
  }

  function gapRoll(g) {
    gapLast = g;
    gapFace(g, false);
    gapPaint();
  }

  /* [reply-gap:dice] THE COUNTDOWN. Two bars - under the square, and along
   * the whole toolbar row - drain from full to empty over the PAUSE, off the
   * air's own clock: the page player's timer target for the next clip less
   * the next card's buildup, or the sounding clip's playhead inside a round. */
  var gapCount = null;
  var gapCountArmed = 0;
  function gapBars(frac) {
    if (!gapUi) return;
    var f = Math.max(0, Math.min(1, gapNum(frac, 0)));
    var tf = 'scaleX(' + f.toFixed(4) + ')';
    gapUi.count.style.transform = tf;
    gapUi.rowbar.style.transform = tf;
    gapUi.wrap.classList.toggle('sp-gap-counting', f > 0);
  }
  function gapCountStop() {
    gapCount = null;
    gapBars(0);
  }
  function gapIdle() {
    if (!gapUi) return;
    gapUi.die.classList.remove('rolling', 'landed');
    gapUi.die.classList.add('sp-gap-fresh');
    gapUi.reel.textContent = '';
  }
  function gapHere() {
    var p = soundingPlayer();
    var c = p && p.pineDeliveryClip;
    if (c) {
      return {key: 'd:' + String(c.delivery_id || c.url || ''), t: Number(p.currentTime) || 0,
        rows: (c.stream && c.stream.rows) || null};
    }
    if (liveStream && liveStream.rows) {
      var t = streamAt();
      if (t >= 0) return {key: 's:' + String(liveStream.at || ''), t: t, rows: liveStream.rows};
    }
    return null;
  }
  function gapCountTick() {
    gapCountArmed = 0;
    if (!gapCount || !gapState.roll || !gapUi) { gapCountStop(); return; }
    var frac;
    if (gapCount.file) {
      var here = gapHere();
      if (!here || here.key !== gapCount.file) { gapCountStop(); return; }
      frac = (gapCount.end - here.t) / Math.max(0.05, gapCount.total);
    } else {
      frac = (gapCount.to - Date.now()) / Math.max(1, gapCount.to - gapCount.from);
    }
    gapBars(frac);
    if (frac <= 0) { gapCount = null; return; }
    gapCountKick();
  }
  function gapCountKick() {
    if (gapCountArmed) return;
    var visible = !document.visibilityState || document.visibilityState === 'visible';
    if (visible && root.requestAnimationFrame) gapCountArmed = root.requestAnimationFrame(gapCountTick);
    else gapCountArmed = setTimeout(gapCountTick, 100);
  }
  /* [reply-gap:buildup] the next card, before its words: which line, and the
     window (audioAt - ms .. audioAt) its whole buildup plays in */
  function mvUpcomingSet(u) {
    if (!u || !u.lid || !(u.ms > 0) || !(u.audioAt > 0)) return;
    if (mvUpcoming && mvUpcoming.lid === u.lid && Math.abs(mvUpcoming.audioAt - u.audioAt) < 400) return;
    u.item = mvUpItem(u);
    mvUpcoming = u;
    try { mvAsk(u.item); } catch (e) { /* asked again when the card starts */ }   /* its rows, fetched during the pause */
  }
  function mvUpItem(u) {
    var row = {};
    try { row = mvFeedRow(u.lid) || {}; } catch (e) { row = {}; }
    var who = String(row.who || u.who || '').toLowerCase();
    var kind = String(row.kind || '').toLowerCase();
    var clip = !!u.sting || who === 'board' || /^(sfx|sting|clip|music)$/.test(kind);
    return {key: 'l:' + u.lid, kind: clip ? 'clip' : 'speech', lid: u.lid, row: row, who: who,
      name: clip ? 'CLIP' : String(u.name || row.name || who || 'ON AIR'),
      text: mvPlain(u.text || row.text || ''), round: String(row.round || ''), kindOf: kind};
  }
  function mvUpcomingNow(now) {
    var u = mvUpcoming;
    if (!u) return null;
    if (now > u.audioAt + 2500) { mvUpcoming = null; return null; }
    return now >= u.audioAt - u.ms ? u : null;
  }
  /* A message ended on this page's player: its pause, and when the next
     message starts - the moment the player's own timer will start it. The
     pause runs to that moment less the next card's buildup. */
  function gapOnCue(ev) {
    var d = ev && ev.detail;
    if (!d) return;
    var to = gapNum(d.startsAt, 0);
    var bms = Math.max(0, gapNum(d.buildup_ms, 0));
    if (bms > 0 && d.lid) {
      mvUpcomingSet({lid: String(d.lid), who: String(d.who || ''), name: String(d.name || ''),
        text: String(d.text || ''), sting: !!d.sting, audioAt: to, ms: bms});
    }
    if (!gapUi || !gapState.roll || !d.rolled) return;
    gapRoll({s: d.s, dice: d.dice, lo: d.lo, hi: d.hi, id: d.id, rolled: true});
    var pauseEnd = to - bms;
    if (pauseEnd - Date.now() > 30) {
      gapCount = {from: Date.now(), to: pauseEnd};
      gapBars(1);
      gapCountKick();
    } else {
      gapCountStop();
    }
  }

  /* Every 120 ms, and on every feed tick: when a reply ends inside the round
     this panel is hearing, the square rolls - once - and the next row's card
     is told when to start building. */
  function gapWatch() {
    gapLoad(false);
    if (!gapUi) return;
    /* [reply-gap:dice] the SOUNDING clip's rows first (this page's player,
       exact), the station's stream_now only when nothing here is sounding */
    var here = gapHere();
    if (!here || !here.rows) return;
    var t = here.t;
    var rows = here.rows;
    for (var i = 0; i < rows.length; i += 1) {
      var g = rows[i] && rows[i].gap;
      if (!g) continue;
      var inside = gapNum(g.inside, 0);
      if (!(inside > 0)) continue;
      var start = gapNum(rows[i].until, 0) - inside;
      var key = here.key + ':' + String(rows[i].id || i);
      if (gapFired[key]) continue;
      if (t >= start - 0.1 && t < start + Math.max(0.6, inside)) {
        gapFired[key] = 1;
        var bms = Math.max(0, gapNum(g.buildup_ms, 0));
        var pause = Math.max(0, inside - bms / 1000);
        var nx = rows[i + 1];
        if (bms > 0 && nx && nx.id) {
          mvUpcomingSet({lid: String(nx.id), who: String(nx.who || ''), name: String(nx.name || ''),
            text: String(nx.text || ''), sting: String(nx.who || '') === 'board',
            audioAt: Date.now() + (gapNum(nx.from, start + inside) - t) * 1000, ms: bms});
        }
        if (gapState.roll && g.rolled) {
          gapRoll(g);
          gapCount = {file: here.key, end: start + pause, total: pause};
          gapBars(1);
          gapCountKick();
        }
        break;
      }
    }
    var keys = Object.keys(gapFired);
    if (keys.length > 400) keys.slice(0, 200).forEach(function (k) { delete gapFired[k]; });
  }

  /* [reply-gap:dual] one track, two thumbs: a finger lands on the nearer
     thumb (or the one it touched) and drags it; the keys step it */
  function gapDualWire(track, a, b) {
    var drag = null;
    function set(which, v, final) {
      gapHeldUntil = Date.now() + 4000;
      if (which === 'a') gapState.gap = v; else gapState.range = v;
      gapPaint();
      gapSend(final);
    }
    track.addEventListener('pointerdown', function (ev) {
      var r = track.getBoundingClientRect();
      var v = gapValAt(ev.clientX, r.left, r.width);
      var which = ev.target === a ? 'a' : ev.target === b ? 'b'
        : (Math.abs(v - gapState.gap) <= Math.abs(v - gapState.range) ? 'a' : 'b');
      drag = {which: which, id: ev.pointerId};
      try { track.setPointerCapture(ev.pointerId); } catch (e) { /* the drag still follows */ }
      (which === 'a' ? a : b).classList.add('grab');
      set(which, v, false);
      if (ev.cancelable) ev.preventDefault();
    });
    track.addEventListener('pointermove', function (ev) {
      if (!drag || ev.pointerId !== drag.id) return;
      var r = track.getBoundingClientRect();
      set(drag.which, gapValAt(ev.clientX, r.left, r.width), false);
    });
    var end = function (ev) {
      if (!drag || (ev && ev.pointerId !== drag.id)) return;
      var w = drag.which;
      drag = null;
      a.classList.remove('grab');
      b.classList.remove('grab');
      set(w, w === 'a' ? gapState.gap : gapState.range, true);
    };
    track.addEventListener('pointerup', end);
    track.addEventListener('pointercancel', end);
    [a, b].forEach(function (th) {
      th.addEventListener('keydown', function (ev) {
        var which = th === a ? 'a' : 'b';
        var cur = which === 'a' ? gapState.gap : gapState.range;
        var step = {ArrowRight: 0.1, ArrowUp: 0.1, ArrowLeft: -0.1, ArrowDown: -0.1, PageUp: 1, PageDown: -1}[ev.key];
        if (ev.key === 'Home') step = GAP_MIN - cur;
        if (ev.key === 'End') step = GAP_MAX - cur;
        if (step === undefined) return;
        ev.preventDefault();
        set(which, gapClamp(cur + step, GAP_MIN, GAP_MAX, 1), true);
      });
    });
  }

  function gapBar() {
    var wrap = make('div', 'sp-gap sp-band-always');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'The pause between replies');
    /* the page's own taps (double-tap to read, the pane's hand) stay off it */
    ['click', 'dblclick', 'pointerdown', 'touchstart', 'wheel'].forEach(function (name) {
      wrap.addEventListener(name, function (ev) { ev.stopPropagation(); }, {passive: true});
    });
    /* [reply-gap:dual] the pause and the roulette's other end, on one track */
    var dual = make('div', 'sp-gap-dual');
    var ic = make('span', 'sp-gap-ic');
    ic.innerHTML = folderIcon('c:hourglass', '') || '';
    ic.setAttribute('aria-hidden', 'true');
    var track = make('div', 'sp-gap-track');
    var rail = make('span', 'sp-gap-rail');
    rail.setAttribute('aria-hidden', 'true');
    var span = make('span', 'sp-gap-span');
    span.setAttribute('aria-hidden', 'true');
    var thumb = function (cls, label) {
      var th = make('span', 'sp-gap-thumb ' + cls);
      th.setAttribute('role', 'slider');
      th.setAttribute('tabindex', '0');
      th.setAttribute('aria-label', label);
      th.setAttribute('aria-valuemin', String(GAP_MIN));
      th.setAttribute('aria-valuemax', String(GAP_MAX));
      return th;
    };
    var a = thumb('sp-gap-a', 'Pause between replies');
    var b = thumb('sp-gap-b', 'Roulette range end');
    track.appendChild(rail);
    track.appendChild(span);
    track.appendChild(a);
    track.appendChild(b);
    var val = make('span', 'sp-gap-val sp-gap-vals', '');
    val.setAttribute('aria-hidden', 'true');
    dual.appendChild(ic);
    dual.appendChild(track);
    dual.appendChild(val);
    var sw = make('button', 'sp-gap-switch');
    sw.type = 'button';
    sw.setAttribute('role', 'switch');
    sw.setAttribute('aria-checked', 'false');
    var die = make('button', 'sp-die sp-gap-die sp-gap-fresh');
    die.type = 'button';
    var idle = make('span', 'sp-gap-idle');
    idle.innerHTML = folderIcon('m:casino', '') || '';
    idle.setAttribute('aria-hidden', 'true');
    var reel = make('span', 'sp-die-reel');
    reel.setAttribute('aria-hidden', 'true');
    die.appendChild(idle);
    die.appendChild(reel);
    /* [reply-gap:dice] the square over its countdown, and the row's */
    var diebox = make('span', 'sp-gap-diebox');
    var well = make('span', 'sp-gap-countwell');
    well.setAttribute('aria-hidden', 'true');
    var count = make('span', 'sp-gap-count');
    well.appendChild(count);
    diebox.appendChild(die);
    diebox.appendChild(well);
    var rowbar = make('span', 'sp-gap-rowbar');
    rowbar.setAttribute('aria-hidden', 'true');
    wrap.appendChild(dual);
    wrap.appendChild(sw);
    wrap.appendChild(diebox);
    wrap.appendChild(rowbar);
    gapUi = {wrap: wrap, dual: dual, track: track, span: span, a: a, b: b, val: val,
      sw: sw, die: die, reel: reel, count: count, rowbar: rowbar};
    gapDualWire(track, a, b);
    if (!gapCueWired) {
      gapCueWired = true;
      root.addEventListener('pine-reply-gap', gapOnCue);
    }
    if (!gapPumpOn) {                                   /* [reply-gap:buildup] every seam, in time */
      gapPumpOn = true;
      setInterval(function () { if (mounted) gapWatch(); }, 120);
    }
    sw.addEventListener('click', function () {
      gapHeldUntil = Date.now() + 4000;
      gapState.roll = !gapState.roll;
      if (!gapState.roll) { gapCountStop(); gapIdle(); }
      gapPaint();
      gapSend(true);
    });
    die.addEventListener('click', function () {
      if (gapState.roll && gapLast) gapFace(gapLast, false);
    });
    gapPaint();
    return wrap;
  }

"""

# --- the card engine: the contract, the preroll, the reserved height -------

CONTRACT_AT = "  function mvRrSheet(cur, rows, budgetMs) {\n"
CONTRACT = r"""  /* [reply-gap:buildup] THE TIMING CONTRACT - reply_gap.py BUILD_* (the
   * station schedules a card's buildup from these very numbers; the test
   * holds the two equal). A card with a scheduled buildup rolls at `per` and
   * is fitted to exactly the scheduled ms. */
  var MV_BUILD = {per: 1800, one: [0.08, 0.18, 0.60, 0.06], two: [0.08, 0.12, 0.27, 0.06, 0.12, 0.27, 0.06],
    rejEach: 260, rejBase: 140, rejCap: 0.4, rejMax: 6, fail: 420, between: 40, hold: 1500};
  /* the fresh tables (from `from` on) laid out again to end exactly `ms`
     after the first of them starts, the 1.5 s hold included */
  function mvBuildFit(tables, from, ms, at) {
    var fresh = tables.slice(from || 0);
    if (!fresh.length || !(ms > 0)) return at;
    var start = fresh[0].at;
    var gaps = MV_BUILD.between * fresh.length;
    var span = at - start - gaps;
    var want = ms - MV_BUILD.hold - gaps;
    if (!(span > 0) || !(want > 0)) return at;
    var k = want / span;
    if (Math.abs(k - 1) < 0.002) return at;
    var a = start;
    fresh.forEach(function (T) {
      ['dIn', 'dRej', 'dDie', 'dSpin', 'dPop', 'dRej2', 'dDie2', 'dSpin2', 'dPop2', 'dFail'].forEach(function (f) {
        T[f] = (T[f] || 0) * k;
      });
      T.at = a;
      T.end = a + T.dIn + T.dRej + T.dDie + T.dSpin + T.dPop + T.dRej2 + T.dDie2 + T.dSpin2 + T.dPop2 + T.dFail;
      a = T.end + MV_BUILD.between;
    });
    return a;
  }
  /* the card's final height, reserved before a table lands: a hidden copy
     of the sheet, measured as the results and as its last table rolling */
  function mvRrReserve(sheet) {
    try {
      var box = sheet && sheet.box;
      if (!box || !box.parentNode || !sheet.tables.length) return;
      var ghost = box.cloneNode(true);
      ghost.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none;left:0;top:0;min-height:0;width:'
        + Math.round(box.getBoundingClientRect().width || box.parentNode.getBoundingClientRect().width) + 'px';
      ghost.classList.add('results');
      var ts = ghost.querySelectorAll('.sp-rr-t');
      [].forEach.call(ts, function (t) { t.style.display = ''; t.style.opacity = '1'; t.classList.add('folded'); });
      box.parentNode.appendChild(ghost);
      var h2 = ghost.offsetHeight;
      ghost.classList.remove('results');
      var lastT = ts[ts.length - 1];
      if (lastT) {
        lastT.classList.remove('folded');
        [].forEach.call(lastT.children, function (c) { c.style.display = ''; });
      }
      var h1 = ghost.offsetHeight;
      ghost.parentNode.removeChild(ghost);
      var h = Math.max(h1, h2);
      if (h > 0) box.style.minHeight = Math.ceil(h) + 'px';
    } catch (e) { /* a card that cannot be measured still plays */ }
  }
"""

JS_EDITS: list[tuple[str, str, str]] = [
    ("contract", CONTRACT_AT, CONTRACT + CONTRACT_AT),
    ("sheet pace",
     """    var per = Math.max(1100, Math.min(2400, budgetMs / n));
""",
     """    var per = Math.max(1100, Math.min(2400, budgetMs / n));
    var fit = cur && cur.buildFit;                  /* [reply-gap:buildup] the contract's pace */
    if (fit && fit.ms > 0) per = MV_BUILD.per;
"""),
    ("sheet fitted",
     """    return {box: box, tables: tables, rolled: at, total: at + 1500, now: ''};
""",
     """    if (fit && fit.ms > 0) at = mvBuildFit(tables, fit.from || 0, fit.ms, at);   /* [reply-gap:buildup] */
    return {box: box, tables: tables, rolled: at, total: at + 1500, now: ''};
"""),
    ("preroll start",
     """  function mvBubbleStart(item, redraw) {
""",
     """  function mvBubbleStart(item, redraw, pre) {        /* [reply-gap:buildup] pre: its buildup window */
"""),
    ("preroll clock",
     """    node.__mvCur = cur;                        /* [onecard-moment]""",
     """    if (pre && pre.ms > 0) {                   /* [reply-gap:buildup] it builds, then its words play */
      cur.preroll = {audioAt: pre.audioAt, ms: pre.ms};
      cur.buildFit = {ms: pre.ms, from: 0};
      cur.t0 = pre.audioAt - pre.ms;
      cur.keepRolls = true;                    /* the tally stays under the words: nothing jumps */
      node.classList.add('sp-mv-preroll');
    }
    node.__mvCur = cur;                        /* [onecard-moment]"""),
    ("reserve the height",
     """    if (cur.sheet) cur.rolls.appendChild(cur.sheet.box);
""",
     """    if (cur.sheet) cur.rolls.appendChild(cur.sheet.box);
    if (cur.sheet) mvRrReserve(cur.sheet);          /* [reply-gap:buildup] no jump as tables land */
"""),
    ("words wait for the audio",
     """    cur.plan = plan;
""",
     """    if (cur.preroll) {                              /* [reply-gap:buildup] the words start with the audio */
      cur.rollEnd = Math.max(cur.rollEnd, cur.preroll.ms);
      cur.collapseEnd = Math.max(cur.collapseEnd, cur.preroll.ms);
      cur.accEnd = Math.max(cur.accEnd, cur.preroll.ms);
    }
    cur.plan = plan;
"""),
    ("a joined card's fresh tables fit its buildup",
     """    var sheet = mvRrSheet(host, m.rows, Math.max(1100, 3000 / fresh.length) * m.rows.length);
""",
     """    var hostFit = host.buildFit;                    /* [reply-gap:buildup] */
    host.buildFit = cur.preroll ? {ms: cur.preroll.ms, from: from} : null;
    var sheet = mvRrSheet(host, m.rows, Math.max(1100, 3000 / fresh.length) * m.rows.length);
    host.buildFit = hostFit;
"""),
    ("a joined card's clock",
     """    var t0 = Date.now();
""",
     """    var t0 = cur.preroll ? cur.preroll.audioAt - cur.preroll.ms : Date.now();   /* [reply-gap:buildup] */
    mvRrReserve(sheet);
"""),
    ("the loop starts the next card",
     """    if (now - mv.detectAt > 200) {
""",
     """    var mvUp = mvUpcomingNow(now);                  /* [reply-gap:buildup] the next card builds first */
    if (mvUp) {
      if (!mv.cur || mv.cur.item.key !== mvUp.item.key) mvBubbleStart(mvUp.item, false, mvUp);
    } else if (now - mv.detectAt > 200) {
"""),
]

CSS_AT = """.sp-band-reopen { flex: 0 0 28px; }
"""
CSS = r"""
/* [reply-gap:square] the seven toolbar icons are squares: the row is
   stretched (46 px on the PineTab) and the buttons stretched with it -
   28 x 46 measured. Centred, 34 x 34, pinned against the touch-target rule. */
.sp-band-restore { align-items: center; }
.sp-band-restore > .sp-band-reopen {
  flex: 0 0 34px; width: 34px; min-width: 34px; height: 34px; min-height: 34px; max-height: 34px;
  box-sizing: border-box;
}
.sp-band-restore > .sp-band-reopen svg { width: 18px; height: 18px; }

/* [reply-gap:dual] one track, two thumbs, the span between them shaded */
.sp-gap-dual {
  flex: 1 1 0; min-width: 0; height: 34px; box-sizing: border-box;
  display: flex; align-items: center; gap: 4px; padding: 0 6px;
  border: 1px solid var(--sp-line); border-radius: 4px; background: var(--sp-panel); color: var(--sp-muted);
}
.sp-gap-dual .sp-gap-ic { flex: none; }
.sp-gap-track {
  position: relative; flex: 1 1 auto; min-width: 60px; height: 30px; margin: 0 14px;
  touch-action: none; cursor: pointer; -webkit-user-select: none; user-select: none;
}
.sp-gap-rail {
  position: absolute; left: 0; right: 0; top: 50%; height: 4px; margin-top: -2px;
  border-radius: 2px; background: #2b3a42; pointer-events: none;
}
.sp-gap-span {
  position: absolute; top: 50%; height: 6px; margin-top: -3px; border-radius: 3px;
  background: var(--sp-on, #68ced9); opacity: .55; pointer-events: none;
}
.sp-gap:not(.sp-gap-on) .sp-gap-span { opacity: .18; }
.sp-gap-thumb {
  position: absolute; top: 50%; width: 30px; height: 30px; margin: -15px 0 0 -15px;
  border-radius: 50%; touch-action: none; cursor: grab; outline: none; z-index: 1;
}
.sp-gap-thumb::after {
  content: ""; position: absolute; left: 7px; top: 7px; width: 16px; height: 16px; box-sizing: border-box;
  border-radius: 50%; background: var(--sp-on, #68ced9); border: 2px solid #0b1215;
  box-shadow: 0 0 0 1px var(--sp-on, #68ced9);
}
.sp-gap-thumb.sp-gap-b::after { background: #0b1215; border-color: var(--sp-on, #68ced9); }
.sp-gap:not(.sp-gap-on) .sp-gap-thumb.sp-gap-b::after { opacity: .45; }
.sp-gap-thumb.grab { cursor: grabbing; z-index: 2; }
.sp-gap-thumb.grab::after { transform: scale(1.15); }
.sp-gap-thumb:focus-visible::after { box-shadow: 0 0 0 3px var(--sp-on, #68ced9); }
.sp-gap-vals { min-width: 9.5ch; }
.sp-gap .sp-gap-diebox { height: 34px; }
.sp-gap .sp-gap-diebox .sp-gap-die { height: 30px; min-height: 30px; max-height: 30px; line-height: 28px; }
.sp-gap .sp-gap-diebox .sp-gap-die .sp-die-reel > span { height: 28px; line-height: 28px; }
@media (prefers-reduced-motion: reduce) {
  .sp-gap-thumb.grab::after { transform: none; }
}
"""
CSS_EDITS = [("dual + square css", CSS_AT, CSS_AT + CSS)]


def _state(text, edits):
    applied, missing, ready = [], [], []
    sim = text
    for name, old, new in edits:
        n_old, n_new = sim.count(old), sim.count(new)
        if n_new == 1 and (n_old == 0 or (new.find(old) >= 0 and n_old == 1)):
            applied.append(name)
        elif n_old == 1:
            ready.append(name)
            sim = sim.replace(old, new, 1)
        else:
            missing.append("%s (anchor x%d)" % (name, n_old))
    return applied, ready, missing


def _block(text):
    """The reply-gap block (header to mount), or None."""
    a = text.find(BLOCK_HEAD)
    b = text.find(BLOCK_END, a + 1) if a >= 0 else -1
    if a < 0 or b < 0 or text.count(BLOCK_HEAD) != 1:
        return None
    return a, b


def check(text, css):
    if css:
        applied, ready, missing = _state(text, CSS_EDITS)
        if missing:
            return 1, missing
        return (2, []) if not ready else (0, [])
    span = _block(text)
    if span is None:
        return 1, ["the reply-gap block was not found once"]
    block_done = MARK in text[span[0]:span[1]] and text[span[0]:span[1]] == NEW_BLOCK
    applied, ready, missing = _state(text, JS_EDITS)
    if missing:
        return 1, missing
    if block_done and not ready:
        return 2, []
    return 0, ([] if not applied else ["partly applied: still to go " + ", ".join(ready)])


def apply(text, css):
    if css:
        for name, old, new in CSS_EDITS:
            if text.count(new) == 1:
                continue
            assert text.count(old) == 1, name
            text = text.replace(old, new, 1)
        return text
    a, b = _block(text)
    text = text[:a] + NEW_BLOCK + text[b:]
    for name, old, new in JS_EDITS:
        n_old, n_new = text.count(old), text.count(new)
        if n_new == 1 and (n_old == 0 or (new.find(old) >= 0 and n_old == 1)):
            continue
        if n_old != 1:
            raise SystemExit("anchor %s: found %d times" % (name, n_old))
        text = text.replace(old, new, 1)
    return text


def main(argv):
    if len(argv) < 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    codes = []
    for raw in argv[2:]:
        path = Path(raw)
        css = path.suffix == ".css"
        text = path.read_bytes().decode("utf-8")
        if "\r\n" in text:
            raise SystemExit("%s has CRLF" % path)
        code, why = check(text, css)
        codes.append(code)
        if argv[1] == "--check":
            print("%s: %s%s" % (path, {0: "READY", 2: "APPLIED", 1: "BROKEN"}[code],
                                (" - " + "; ".join(why)) if why else ""))
            continue
        if code == 2:
            print("%s: already applied" % path)
            continue
        if code == 1:
            print("%s: BROKEN - %s" % (path, "; ".join(why)))
            return 1
        out = apply(text, css)
        tmp = path.with_name(path.name + ".rgtmp")
        tmp.write_bytes(out.encode("utf-8"))
        os.replace(tmp, path)
        print("%s: applied" % path)
    if argv[1] == "--check":
        return 1 if 1 in codes else 2 if all(c == 2 for c in codes) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
