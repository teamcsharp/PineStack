"""[reply-gap:buildup] Pause, then the card's whole Rolodex, then the words.

2026-09-30, the operator: "i want to be able to see every RNG rolodex roulette
buildup for each card. The whole point of the timer was to allow these to play
and be analyzed without them rushing or skipping animations" - and chose
"Pause, then buildup, then words": the message ends, the dice roll and count
down the pause, the next card plays its WHOLE buildup, then its words play.

reply_gap.py holds the timing contract (BUILD_*), computes each message's
buildup from the System 3 record its card is drawn from, and puts it in the
schedule (the page door, the burst's seams). This patch:

  app.py  the planners' seam is the pause AND the expected buildup
          (reply_gap.planner_seam): segment budget, fit checks, stock price,
          the director's runtime estimate; the page players keep pause +
          buildup when late, and their cue ("pine-reply-gap") carries the
          next message's buildup and line id so the view starts its card
          exactly buildup ms before the words.

Usage (ON THE HOST): python3 tools/reply_gap_buildup_patch.py --check|--apply app.py
--check: 0 ready, 2 applied, 1 broken. Anchors asserted (an anchor that is in
both served pages is asserted twice); LF; atomic; incremental."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

CUE_OLD = '''function pineReplyGapFloor(clip) {
  const g = clip && clip.gap_before;
  if (!g || !pineReplyGapEndAt) return 0;
  const s = Number(g.s);
  return (isFinite(s) && s >= 0) ? pineReplyGapEndAt + s * 1000 : 0;
}
function pineReplyGapCue(clip, waitMs) {
  const g = clip && clip.gap_before;
  if (!g || clip.pineGapCued) return;
  clip.pineGapCued = true;
  try {
    window.dispatchEvent(new CustomEvent("pine-reply-gap", {detail: {
      s: Number(g.s) || 0, rolled: !!g.rolled, dice: g.dice, lo: g.lo, hi: g.hi,
      id: String(g.id || ""), at: Date.now(),
      startsAt: Date.now() + Math.max(0, Number(waitMs) || 0),
      text: String(clip.text || "").slice(0, 80)}}));
  } catch (e) { /* a view that cannot hear it never costs the air */ }
}
'''
CUE_NEW = '''/* [reply-gap:buildup] the pause, then the next card's whole Rolodex
 * (buildup_ms, in the station's schedule), then the words */
function pineReplyGapBuild(clip) {
  const b = Number(clip && clip.buildup_ms);
  return (isFinite(b) && b > 0) ? b : 0;
}
function pineReplyGapFloor(clip) {
  const g = clip && clip.gap_before;
  if (!g || !pineReplyGapEndAt) return 0;
  const s = Number(g.s);
  return (isFinite(s) && s >= 0) ? pineReplyGapEndAt + s * 1000 + pineReplyGapBuild(clip) : 0;
}
function pineReplyGapCue(clip, waitMs) {
  const g = (clip && clip.gap_before) || null;
  if ((!g && !pineReplyGapBuild(clip)) || clip.pineGapCued) return;
  clip.pineGapCued = true;
  const head = ((clip.stream && clip.stream.rows) || [])[0] || {};
  try {
    window.dispatchEvent(new CustomEvent("pine-reply-gap", {detail: {
      s: g ? (Number(g.s) || 0) : 0, rolled: !!(g && g.rolled), dice: g ? g.dice : null,
      lo: g ? g.lo : null, hi: g ? g.hi : null,
      id: String((g && g.id) || ""), at: Date.now(),
      startsAt: Date.now() + Math.max(0, Number(waitMs) || 0),
      buildup_ms: pineReplyGapBuild(clip),
      lid: String(clip.row_id || clip.line || head.id || ""),
      who: String(clip.who || head.who || ""),
      name: String(head.name || ""),
      sting: !!clip.sting || String(clip.url || "").indexOf("/sfx/") === 0,
      text: String(head.text || clip.text || "").slice(0, 400)}}));
  } catch (e) { /* a view that cannot hear it never costs the air */ }
}
'''

WORDS_OLD = '''  if (next && next.gap_before) pineReplyGapCue(next, pineReplyGapDue(next) - Date.now());
'''
WORDS_NEW = '''  if (next && (next.gap_before || pineReplyGapBuild(next))) {      /* [reply-gap:buildup] */
    pineReplyGapCue(next, pineReplyGapDue(next) - Date.now());
  }
'''

EDITS: list[tuple[str, str, str, int]] = [
    ("planner seam",
     '''            return max(max(CONCAT_BEAT), float(_reply_gap.expected_gap()))
''',
     '''            # [reply-gap:buildup] the pause AND the next card's buildup
            return max(max(CONCAT_BEAT), float(_reply_gap.planner_seam()))
''', 1),
    ("cue carries the buildup", CUE_OLD, CUE_NEW, 2),
    ("words end cues a buildup", WORDS_OLD, WORDS_NEW, 2),
]


def _state(text: str) -> tuple[int, list[str]]:
    applied, missing, ready = [], [], []
    sim = text
    for name, old, new, n in EDITS:
        if sim.count(new) == n and sim.count(old) == (n if new.find(old) >= 0 else 0):
            applied.append(name)
        elif sim.count(old) == n:
            ready.append(name)
            sim = sim.replace(old, new)
        else:
            missing.append("%s (anchor x%d, want %d)" % (name, sim.count(old), n))
    if missing:
        return 1, missing
    if applied and not ready:
        return 2, []
    return 0, (["still to go: " + ", ".join(ready)] if applied else [])


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    path = Path(argv[2])
    text = path.read_bytes().decode("utf-8")
    if "\r\n" in text:
        raise SystemExit("CRLF in %s" % path)
    code, why = _state(text)
    if argv[1] == "--check":
        print("%s: %s%s" % (path, {0: "READY", 2: "APPLIED", 1: "BROKEN"}[code],
                            (" - " + "; ".join(why)) if why else ""))
        return code
    if code == 2:
        print("%s: already applied" % path)
        return 0
    if code == 1:
        print("%s: BROKEN - %s" % (path, "; ".join(why)))
        return 1
    done = 0
    for name, old, new, n in EDITS:
        if text.count(new) == n and text.count(old) == (n if new.find(old) >= 0 else 0):
            continue
        if text.count(old) != n:
            raise SystemExit("anchor %s: found %d times, want %d" % (name, text.count(old), n))
        text = text.replace(old, new)
        done += 1
    ast.parse(text)
    tmp = path.with_name(path.name + ".rgtmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)
    print("%s: applied %d edits" % (path, done))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
