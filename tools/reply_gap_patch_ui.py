"""[reply-gap] The Script view's half: two sliders, a toggle, the dice square.

Loaded by tools/reply_gap_patch.py (--check-js/--apply-js, --check-css/--apply-css).
The toolbar under THE SCRIPT (timer, script, waveform, calendar, clock, dice,
chat) gains, to the right of the chat icon and across the rest of the row:

  [hourglass] ====o====== 1.0s   the pause between replies, 0.2 - 10 s
  [shuffle]   ===o=== 1.0s       the roulette range (gap +/- range)
  (o  )                          the roulette toggle (a switch)
  [ 1.7 ]                        the dice square: a reel that rolls when each
                                 reply's pause is rolled and lands on it

Station-wide: GET/POST /api/reply-gap, so the desk and the tablet agree. The
dice play off the stream_now rows' `gap` (app.py stamps each reply's pause on
its row) at the moment the reply ends in the audio the panel is hearing.
"""

JS_FUNCS_AT = '''  function mount(node) {
'''
JS_FUNCS = r'''  /* [reply-gap] THE PAUSE BETWEEN REPLIES, ON THE TOOLBAR.
   *
   * "put a slider here for adjusting the space between dj replies and the
   *  sfx guy replies ... 1 second ... up to possibly 10 seconds ... as low
   *  as .2 seconds ... a 2nd slider for a roulette RNG roll after each reply
   *  ... a toggle to enable roulette rolls ... Show the rolling dice here."
   *
   * Slider one is the pause after every reply on air (0.2 - 10 s, default
   * 1). Slider two is how far a roll may move it: with the toggle on, each
   * pause is a System 3 roll, uniform in [gap - range, gap + range] kept
   * inside 0.2 - 10 s. The station keeps the setting (/api/reply-gap), rolls
   * at the seam, and stamps each reply's pause on its stream_now row; the
   * square rolls when that reply ends in the audio this panel is hearing. */
  var GAP_MIN = 0.2, GAP_MAX = 10, GAP_RANGE_MIN = 0.1, GAP_RANGE_MAX = 10;
  var gapState = {gap: 1, range: 1, roll: false};
  var gapUi = null;
  var gapLoadedAt = 0;
  var gapSendTimer = 0;
  var gapHeldUntil = 0;             /* a hand on a slider: a poll does not move it */
  var gapFired = Object.create(null);
  var gapLast = null;               /* the last pause rolled on this panel */

  function gapNum(v, d) { v = Number(v); return isFinite(v) ? v : d; }
  function gapClamp(v, lo, hi, d) {
    v = Math.round(gapNum(v, d) * 10) / 10;
    return Math.min(hi, Math.max(lo, v));
  }
  function gapWindow(g, r) {
    var lo = Math.max(GAP_MIN, Math.round((g - r) * 10) / 10);
    var hi = Math.min(GAP_MAX, Math.round((g + r) * 10) / 10);
    return [lo, Math.max(lo, hi)];
  }
  function gapFmt(s) { return gapNum(s, 0).toFixed(1) + ' s'; }

  function gapPaint(moveSliders) {
    if (!gapUi) return;
    var s = gapState;
    var w = gapWindow(s.gap, s.range);
    if (moveSliders) {
      gapUi.one.value = String(s.gap);
      gapUi.two.value = String(s.range);
    }
    gapUi.oneVal.textContent = s.gap.toFixed(1) + 's';
    gapUi.twoVal.textContent = s.range.toFixed(1) + 's';
    var oneTip = 'Pause between replies: ' + gapFmt(s.gap) + ' (0.2 - 10 s). The silence after '
      + 'every reply on air - DJ to DJ, DJ to the SFX Guy, the SFX Guy to a DJ. Station-wide; '
      + 'the running order budgets it into every segment.';
    var twoTip = 'Roulette range: ' + gapFmt(s.range) + '. With the roll on, each pause is a '
      + 'System 3 roll, uniform between the pause minus this and the pause plus this, kept '
      + 'inside 0.2 - 10 s (now ' + w[0].toFixed(1) + ' - ' + w[1].toFixed(1) + ' s).';
    gapUi.oneBox.title = oneTip;
    gapUi.one.setAttribute('aria-valuetext', gapFmt(s.gap));
    gapUi.twoBox.title = twoTip;
    gapUi.two.setAttribute('aria-valuetext', gapFmt(s.range));
    var swTip = 'Roulette after each reply: ' + (s.roll ? 'ON - a System 3 roll picks each pause in '
      + w[0].toFixed(1) + ' - ' + w[1].toFixed(1) + ' s' : 'OFF - every pause is the fixed '
      + gapFmt(s.gap)) + '. Tap to turn it ' + (s.roll ? 'off.' : 'on.');
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
    var recent = got.recent && got.recent.length ? got.recent[got.recent.length - 1] : null;
    if (recent && !gapLast) {
      gapLast = recent;
      gapFace(recent, true);
    }
    gapPaint(true);
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
    reel.style.setProperty('--reel-end', (-(faces.length - 1) * 26) + 'px');
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
    gapPaint(false);
  }

  /* Called on every feed tick: when the reply a rolled pause follows ends
     in the audio this panel is hearing, the square rolls - once. */
  function gapWatch() {
    gapLoad(false);
    if (!gapUi || !gapState.roll || !liveStream || !liveStream.rows) return;
    var t = streamAt();
    if (!(t >= 0)) return;
    var rows = liveStream.rows;
    for (var i = 0; i < rows.length; i += 1) {
      var g = rows[i] && rows[i].gap;
      if (!g || !g.rolled) continue;
      var start = gapNum(rows[i].until, 0) - gapNum(g.inside, 0);
      var key = String(liveStream.at || '') + ':' + String(rows[i].id || i);
      if (gapFired[key]) continue;
      if (t >= start - 0.1 && t < start + Math.max(1.2, gapNum(g.s, 1))) {
        gapFired[key] = 1;
        gapRoll(g);
        break;
      }
    }
    var keys = Object.keys(gapFired);
    if (keys.length > 400) keys.slice(0, 200).forEach(function (k) { delete gapFired[k]; });
  }

  function gapBar() {
    var wrap = make('div', 'sp-gap sp-band-always');
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'The pause between replies');
    /* the page's own taps (double-tap to read, the pane's hand) stay off it */
    ['click', 'dblclick', 'pointerdown', 'touchstart', 'wheel'].forEach(function (name) {
      wrap.addEventListener(name, function (ev) { ev.stopPropagation(); }, {passive: true});
    });
    function slider(cls, icon, label, min, max, value) {
      var box = make('label', 'sp-gap-slider ' + cls);
      var ic = make('span', 'sp-gap-ic');
      ic.innerHTML = folderIcon(icon, '') || '';
      ic.setAttribute('aria-hidden', 'true');
      var input = document.createElement('input');
      input.type = 'range';
      input.min = String(min);
      input.max = String(max);
      input.step = '0.1';
      input.value = String(value);
      input.setAttribute('aria-label', label);
      var val = make('span', 'sp-gap-val', value.toFixed(1) + 's');
      val.setAttribute('aria-hidden', 'true');
      box.appendChild(ic);
      box.appendChild(input);
      box.appendChild(val);
      return {box: box, input: input, val: val};
    }
    var one = slider('sp-gap-one', 'c:hourglass', 'Pause between replies', GAP_MIN, GAP_MAX, gapState.gap);
    var two = slider('sp-gap-two', 'c:shuffle', 'Roulette range', GAP_RANGE_MIN, GAP_RANGE_MAX, gapState.range);
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
    wrap.appendChild(one.box);
    wrap.appendChild(two.box);
    wrap.appendChild(sw);
    wrap.appendChild(die);
    gapUi = {wrap: wrap, oneBox: one.box, one: one.input, oneVal: one.val,
      twoBox: two.box, two: two.input, twoVal: two.val, sw: sw, die: die, reel: reel};
    var moved = function (which, final) {
      return function () {
        gapHeldUntil = Date.now() + 4000;
        if (which === 'gap') gapState.gap = gapClamp(one.input.value, GAP_MIN, GAP_MAX, 1);
        else gapState.range = gapClamp(two.input.value, GAP_RANGE_MIN, GAP_RANGE_MAX, 1);
        gapPaint(false);
        gapSend(final);
      };
    };
    one.input.addEventListener('input', moved('gap', false));
    one.input.addEventListener('change', moved('gap', true));
    two.input.addEventListener('input', moved('range', false));
    two.input.addEventListener('change', moved('range', true));
    sw.addEventListener('click', function () {
      gapHeldUntil = Date.now() + 4000;
      gapState.roll = !gapState.roll;
      gapPaint(false);
      gapSend(true);
    });
    die.addEventListener('click', function () {
      if (gapState.roll && gapLast) gapFace(gapLast, false);
    });
    gapPaint(true);
    return wrap;
  }

'''

JS_EDITS = [
    ("gap functions", JS_FUNCS_AT, JS_FUNCS + JS_FUNCS_AT),
    ("gap bar on the toolbar",
     '''      s3Buttons[mode] = b;
      restore.appendChild(b);
    });
''',
     '''      s3Buttons[mode] = b;
      restore.appendChild(b);
    });
    /* [reply-gap] the pause between replies, its roulette and its dice:
       right of the chat icon, across the rest of the row. */
    restore.appendChild(gapBar());
'''),
    ("gap watch on the feed",
     '''        tick();
      };
      stop = typeof feed.subscribeView === 'function'
''',
     '''        tick();
        gapWatch();                                   /* [reply-gap] the dice */
      };
      stop = typeof feed.subscribeView === 'function'
'''),
]

CSS_AT = '''.sp-band-reopen { flex: 0 0 28px; }
'''
CSS = '''
/* [reply-gap] THE PAUSE BETWEEN REPLIES on the toolbar, right of the chat
   icon: two sliders, the roulette switch and the dice square. Every size is
   pinned: the page's touch-target rule (button min-height) blows buttons up
   to 38 px, which this 28 px row cannot hold. Fits the PineTab's ~1154 CSS px
   (the right column is ~560 px; the seven icons take 226). */
.sp-gap { flex: 1 1 250px; min-width: 0; display: flex; align-items: center; gap: 4px; margin-left: 3px; }
.sp-gap-slider {
  flex: 1.4 1 0; min-width: 0; height: 28px; box-sizing: border-box;
  display: flex; align-items: center; gap: 3px; padding: 0 5px;
  border: 1px solid var(--sp-line); border-radius: 4px; background: var(--sp-panel);
  color: var(--sp-muted); cursor: pointer;
}
.sp-gap-slider.sp-gap-two { flex: 1 1 0; }
.sp-gap-slider:focus-within { border-color: var(--sp-on); color: var(--sp-on); }
.sp-gap-ic { flex: none; display: inline-flex; width: 14px; height: 14px; }
.sp-gap-ic svg { width: 14px; height: 14px; }
.sp-gap-slider input[type="range"] {
  flex: 1 1 auto; min-width: 24px; width: 100%; height: 18px; min-height: 18px;
  margin: 0; padding: 0; background: transparent; accent-color: var(--sp-on, #68ced9);
}
.sp-gap-val {
  flex: none; min-width: 3.4ch; text-align: right; color: #dfe6e4;
  font: 600 10.5px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
}
.sp-gap:not(.sp-gap-on) .sp-gap-two { opacity: .55; }
.sp-gap.sp-gap-unsaved .sp-gap-slider { border-style: dashed; }
.sp-gap-switch {
  flex: none; position: relative; box-sizing: border-box;
  width: 32px; min-width: 32px; height: 18px; min-height: 18px; max-height: 18px;
  padding: 0; margin: 0; border-radius: 9px; cursor: pointer;
  border: 1px solid var(--sp-line); background: #0b1215;
}
.sp-gap-switch::after {
  content: ""; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px;
  border-radius: 50%; background: var(--sp-muted); transition: transform .15s ease, background .15s ease;
}
.sp-gap-switch[aria-checked="true"] { border-color: var(--sp-on); background: #16302a; }
.sp-gap-switch[aria-checked="true"]::after { transform: translateX(14px); background: var(--sp-on); }
.sp-gap-switch:focus-visible, .sp-gap-die:focus-visible { outline: 2px solid var(--sp-on); outline-offset: 1px; }
.sp-gap .sp-gap-die {
  flex: none; box-sizing: border-box; width: 30px; min-width: 30px; height: 28px;
  min-height: 28px; max-height: 28px; border-radius: 5px; --fam: #68ced9;
  font: 700 11px/26px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.sp-gap .sp-gap-die .sp-die-reel > span { height: 26px; line-height: 26px; }
.sp-gap-idle { position: absolute; inset: 0; display: none; place-items: center; color: var(--sp-muted); }
.sp-gap-idle svg { width: 15px; height: 15px; }
.sp-gap .sp-gap-die.sp-gap-fresh .sp-die-reel, .sp-gap:not(.sp-gap-on) .sp-gap-die .sp-die-reel { display: none; }
.sp-gap .sp-gap-die.sp-gap-fresh .sp-gap-idle, .sp-gap:not(.sp-gap-on) .sp-gap-die .sp-gap-idle { display: grid; }
.sp-gap:not(.sp-gap-on) .sp-gap-die { opacity: .5; cursor: default; box-shadow: none; }
@media (prefers-reduced-motion: reduce) {
  .sp-gap-switch::after { transition: none; }
}
'''

CSS_EDITS = [
    ("gap css", CSS_AT, CSS_AT + CSS),
]
