"""[reply-gap:dice] The dice roll after EVERY message, and count down to the next.

"I wanna see the dice icon roll after each message to dictate how long before
 the next reply with a small loading bar that shows it counting down to
 playing the next reply."                               - the operator, 2026-09-30

Applied on top of tools/reply_gap_patch_ui.py's bar:
    python3 tools/reply_gap_patch_ui2.py --check|--apply script-page.js ... script-page.css ...
Two countdowns, both drained by the timing the air uses:
  * between two clips - the page player's "pine-reply-gap" cue, fired the
    moment the words end, carries the moment its own timer starts the next
    message (startsAt); the bars drain to it;
  * inside a welded round - the sounding clip's own row carries the pause
    (`gap`), and the bars drain on that clip's playhead.
Roulette off: the square and both bars stay idle. Nothing is kept per device:
the settings are the station's (/api/reply-gap), every listener hears them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

JS_EDITS: list[tuple[str, str, str]] = [
    ("tip: pause",
     """      + 'the running order budgets it into every segment.';
""",
     """      + 'the running order budgets it into every segment. Station-wide - every listener hears this.';
"""),
    ("tip: range",
     """      + 'inside 0.2 - 10 s (now ' + w[0].toFixed(1) + ' - ' + w[1].toFixed(1) + ' s).';
""",
     """      + 'inside 0.2 - 10 s (now ' + w[0].toFixed(1) + ' - ' + w[1].toFixed(1) + ' s). '
      + 'Station-wide - every listener hears this.';
"""),
    ("tip: switch",
     """      + gapFmt(s.gap)) + '. Tap to turn it ' + (s.roll ? 'off.' : 'on.');
""",
     """      + gapFmt(s.gap)) + '. Station-wide - every listener hears this. Tap to turn it '
      + (s.roll ? 'off.' : 'on.');
"""),
    ("no stale face",
     """    var recent = got.recent && got.recent.length ? got.recent[got.recent.length - 1] : null;
    if (recent && !gapLast) {
      gapLast = recent;
      gapFace(recent, true);
    }
    gapPaint(true);
""",
     """    /* [reply-gap:dice] the square lands only on a pause this panel saw roll -
       a receipt from another road, painted still, read as a dead die */
    if (!gapState.roll) { gapCountStop(); gapIdle(); }
    gapPaint(true);
"""),
    ("reel face height",
     """    reel.style.setProperty('--reel-end', (-(faces.length - 1) * 26) + 'px');
""",
     """    reel.style.setProperty('--reel-end', (-(faces.length - 1) * 22) + 'px');
"""),
    ("roll + countdown",
     """  function gapRoll(g) {
    gapLast = g;
    gapFace(g, false);
    gapPaint(false);
  }
""",
     """  function gapRoll(g) {
    gapLast = g;
    gapFace(g, false);
    gapPaint(false);
  }

  /* [reply-gap:dice] THE COUNTDOWN. Two bars - under the square, and along
   * the whole toolbar row - drain from full to empty over the pause, off
   * the air's own clock: the page player's timer target for the next clip,
   * or the sounding clip's playhead inside a welded round. */
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
  /* A message ended on this page's player: its pause, and when the next
     message starts - the moment the player's own timer will start it. */
  function gapOnCue(ev) {
    var d = ev && ev.detail;
    if (!gapUi || !gapState.roll || !d || !d.rolled) return;
    gapRoll({s: d.s, dice: d.dice, lo: d.lo, hi: d.hi, id: d.id, rolled: true});
    var to = gapNum(d.startsAt, 0);
    if (to - Date.now() > 30) {
      gapCount = {from: Date.now(), to: to};
      gapBars(1);
      gapCountKick();
    } else {
      gapCountStop();
    }
  }
"""),
    ("watch: every seam of the sounding clip",
     """  function gapWatch() {
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
""",
     """  function gapWatch() {
    gapLoad(false);
    if (!gapUi || !gapState.roll) return;
    /* [reply-gap:dice] the SOUNDING clip's rows first (this page's player,
       exact), the station's stream_now only when nothing here is sounding */
    var here = gapHere();
    if (!here || !here.rows) return;
    var t = here.t;
    var rows = here.rows;
    for (var i = 0; i < rows.length; i += 1) {
      var g = rows[i] && rows[i].gap;
      if (!g || !g.rolled) continue;
      var inside = gapNum(g.inside, 0);
      if (!(inside > 0)) continue;
      var start = gapNum(rows[i].until, 0) - inside;
      var key = here.key + ':' + String(rows[i].id || i);
      if (gapFired[key]) continue;
      if (t >= start - 0.1 && t < start + Math.max(0.6, inside)) {
        gapFired[key] = 1;
        gapRoll(g);
        gapCount = {file: here.key, end: start + inside, total: inside};
        gapBars(1);
        gapCountKick();
        break;
      }
    }
"""),
    ("bars in the bar",
     """    die.appendChild(idle);
    die.appendChild(reel);
    wrap.appendChild(one.box);
    wrap.appendChild(two.box);
    wrap.appendChild(sw);
    wrap.appendChild(die);
    gapUi = {wrap: wrap, oneBox: one.box, one: one.input, oneVal: one.val,
      twoBox: two.box, two: two.input, twoVal: two.val, sw: sw, die: die, reel: reel};
""",
     """    die.appendChild(idle);
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
    wrap.appendChild(one.box);
    wrap.appendChild(two.box);
    wrap.appendChild(sw);
    wrap.appendChild(diebox);
    wrap.appendChild(rowbar);
    gapUi = {wrap: wrap, oneBox: one.box, one: one.input, oneVal: one.val,
      twoBox: two.box, two: two.input, twoVal: two.val, sw: sw, die: die, reel: reel,
      count: count, rowbar: rowbar};
    if (!gapCueWired) {
      gapCueWired = true;
      root.addEventListener('pine-reply-gap', gapOnCue);
    }
"""),
    ("switch off goes idle",
     """      gapState.roll = !gapState.roll;
      gapPaint(false);
      gapSend(true);
""",
     """      gapState.roll = !gapState.roll;
      if (!gapState.roll) { gapCountStop(); gapIdle(); }
      gapPaint(false);
      gapSend(true);
"""),
    ("cue wired flag",
     """  var gapLast = null;               /* the last pause rolled on this panel */
""",
     """  var gapLast = null;               /* the last pause rolled on this panel */
  var gapCueWired = false;          /* [reply-gap:dice] the player's cue, heard once */
"""),
]

CSS_AT = """@media (prefers-reduced-motion: reduce) {
  .sp-gap-switch::after { transition: none; }
}
"""
CSS = """
/* [reply-gap:dice] the countdown: a 3 px bar under the square and a 2 px bar
   along the whole toolbar row, both drained by the air's own clock. The
   square gives the row 4 px for its bar. Idle (roulette off): no bars. */
.sp-band-restore { position: relative; }
.sp-gap-diebox { flex: none; display: flex; flex-direction: column; justify-content: space-between;
  width: 30px; height: 28px; }
.sp-gap .sp-gap-diebox .sp-gap-die { height: 24px; min-height: 24px; max-height: 24px; line-height: 22px; }
.sp-gap .sp-gap-diebox .sp-gap-die .sp-die-reel > span { height: 22px; line-height: 22px; }
.sp-gap-countwell { display: block; height: 3px; border-radius: 2px; overflow: hidden; background: #1b262b; }
.sp-gap-count, .sp-gap-rowbar {
  display: block; transform-origin: left center; transform: scaleX(0);
  background: var(--sp-on, #68ced9); pointer-events: none;
}
.sp-gap-count { height: 100%; }
.sp-gap-rowbar { position: absolute; left: 0; right: 0; bottom: -4px; height: 2px; border-radius: 1px; opacity: .85; }
.sp-gap:not(.sp-gap-on) .sp-gap-countwell { opacity: .35; }
.sp-gap:not(.sp-gap-on) .sp-gap-count, .sp-gap:not(.sp-gap-on) .sp-gap-rowbar { display: none; }
"""

CSS_EDITS = [("countdown css", CSS_AT, CSS_AT + CSS)]


def _state(text, edits):
    applied, missing, ready = [], [], []
    for name, old, new in edits:
        n_old, n_new = text.count(old), text.count(new)
        if n_new == 1 and (n_old == 0 or (new.find(old) >= 0 and n_old == 1)):
            applied.append(name)
        elif n_old == 1:
            ready.append(name)
        else:
            missing.append("%s (anchor x%d)" % (name, n_old))
    if missing:
        return 1, missing
    if applied and not ready:
        return 2, []
    if applied and ready:
        return 1, ["half applied: " + ", ".join(applied)]
    return 0, []


def main(argv):
    if len(argv) < 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    codes = []
    for raw in argv[2:]:
        path = Path(raw)
        edits = CSS_EDITS if path.suffix == ".css" else JS_EDITS
        text = path.read_bytes().decode("utf-8")
        if "\r\n" in text:
            raise SystemExit("%s has CRLF" % path)
        code, why = _state(text, edits)
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
        for name, old, new in edits:
            if text.count(old) != 1:
                raise SystemExit("anchor %s: found %d times" % (name, text.count(old)))
            text = text.replace(old, new, 1)
        tmp = path.with_name(path.name + ".rgtmp")
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
        print("%s: applied %d edits" % (path, len(edits)))
    if argv[1] == "--check":
        return 1 if 1 in codes else 2 if all(c == 2 for c in codes) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
