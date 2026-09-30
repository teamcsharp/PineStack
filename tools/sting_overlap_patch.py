"""[reply-gap:sting-overlap] the next dialogue card builds DURING an MP4 sting.

"During the play of an MP4 tag ... is allowed to play the roulette and RNG
buildup of the next tab if it's a conversation tab in order to give it more
time. It's important that I see the build-up of the conversation path for each
piece of dialogue. So if the next one is a piece of dialogue, you could just
jump to it while the MP4 is playing in order to give it more time if needed."

Station (reply_gap.py): booked() remembers that the air ends on a sting and
when that sting began; door() lets a dialogue message's buildup run inside it -
the words start after the sting's words, the rolled pause, and only what is
LEFT of the buildup - and stamps the part it hid as gap_before.overlap_build_ms.
Page (both players, app.py): the floor subtracts that overlap; while the sting
plays, the next card is announced EARLY (pine-reply-gap {early: true}) so the
view starts its whole buildup during the MP4; the dice still roll when the
sting's words end. View (script-page.js): an early announcement is kept (the
card is never restarted by the words-end cue) and the countdown runs the pause
only.

Usage (ON THE HOST): python3 tools/sting_overlap_patch.py --check|--apply
  (patches reply_gap.py and app.py in the repo root)
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RG = [
    ('''            _BOOKED["tail"] = float((clip or {}).get("tail_s") or 0) if isinstance(clip, dict) else 0.0
''',
     '''            _BOOKED["tail"] = float((clip or {}).get("tail_s") or 0) if isinstance(clip, dict) else 0.0
            # [reply-gap:sting-overlap] does the air end on a sting, and when did it begin
            c = clip if isinstance(clip, dict) else {}
            _BOOKED["sting"] = 1.0 if is_sting(c) else 0.0
            secs = _num(c.get("seconds") or c.get("length"), 0.0)
            _BOOKED["from"] = float(until) - secs if secs > 0 else float(until)
''', 1),
    ('''def overlap(clip: Any) -> float:
''',
     '''def is_sting(clip: Any) -> bool:
    """[reply-gap:sting-overlap] a clip off the board (an MP4 sting / SFX)."""
    c = clip if isinstance(clip, dict) else {}
    who = str(c.get("who") or "")
    return bool(who in ("board", "drop") or c.get("sting") or c.get("video")
                or str(c.get("url") or "").startswith("/sfx/"))


def sting_overlap_ms(clip: Any, build: int, words_end: float) -> int:
    """How much of a dialogue card's buildup can run inside the sting the air
    ends on: all of it when the sting is long enough, the sting's length when
    it is not; 0 when the air does not end on a sting or this is not a line."""
    try:
        if build <= 0 or not float(_BOOKED.get("sting") or 0):
            return 0
        if is_sting(clip) or str((clip or {}).get("who") or "") not in HOST_SEATS:
            return 0
        began = float(_BOOKED.get("from") or words_end)
        return int(max(0.0, min(build / 1000.0, words_end - began)) * 1000)
    except Exception:  # noqa: BLE001
        return 0


def overlap(clip: Any) -> float:
''', 1),
    ('''        floor = words_end + float(note["s"]) + build / 1000.0
''',
     '''        over_ms = sting_overlap_ms(clip, build, words_end) if mine else 0   # [reply-gap:sting-overlap]
        floor = words_end + float(note["s"]) + (build - over_ms) / 1000.0
''', 1),
    ('''                                  buildup_ms=build,
                                  overlap=round(max(0.0, air - start), 3))
''',
     '''                                  buildup_ms=build, overlap_build_ms=over_ms,
                                  overlap=round(max(0.0, air - start), 3))
''', 1),
]

APP = [
    ('''  return (isFinite(s) && s >= 0) ? pineReplyGapEndAt + s * 1000 + pineReplyGapBuild(clip) : 0;
}
''',
     '''  return (isFinite(s) && s >= 0)
    ? pineReplyGapEndAt + s * 1000 + pineReplyGapBuild(clip) - pineReplyGapOverlap(clip) : 0;
}
/* [reply-gap:sting-overlap] the part of this card's buildup that runs during
 * the sting before it (the station stamped it; the words do not wait for it) */
function pineReplyGapOverlap(clip) {
  const o = Number(clip && clip.gap_before && clip.gap_before.overlap_build_ms);
  return (isFinite(o) && o > 0) ? Math.min(o, pineReplyGapBuild(clip)) : 0;
}
/* While a sting plays, the next card is announced at once, so the view builds
 * its whole Rolodex during the MP4; the dice still wait for the words' end. */
function pineReplyGapBuildAhead(clip, el, queue) {
  const next = queue && queue[0];
  if (!next || next.pineBuildAhead || !pineReplyGapOverlap(next)) return;
  if (!el || !isFinite(el.duration)) return;
  next.pineBuildAhead = true;
  const tail = Math.max(0, Number((clip && clip.tail_s) || 0));
  const wordsIn = Math.max(0, (el.duration - tail - Number(el.currentTime || 0)) * 1000);
  const g = next.gap_before || {};
  const wait = wordsIn + (Number(g.s) || 0) * 1000 + pineReplyGapBuild(next) - pineReplyGapOverlap(next);
  pineReplyGapCue(next, wait, true);
}
''', 2),
    ('''function pineReplyGapCue(clip, waitMs) {
  const g = (clip && clip.gap_before) || null;
  if ((!g && !pineReplyGapBuild(clip)) || clip.pineGapCued) return;
  clip.pineGapCued = true;
''',
     '''function pineReplyGapCue(clip, waitMs, early) {
  const g = (clip && clip.gap_before) || null;
  if (!g && !pineReplyGapBuild(clip)) return;
  if (early) { if (clip.pineGapEarly) return; clip.pineGapEarly = true; }   /* [reply-gap:sting-overlap] */
  else { if (clip.pineGapCued) return; clip.pineGapCued = true; }
''', 2),
    ('''      s: g ? (Number(g.s) || 0) : 0, rolled: !!(g && g.rolled), dice: g ? g.dice : null,
''',
     '''      early: !!early, overlap_ms: pineReplyGapOverlap(clip),
      s: g ? (Number(g.s) || 0) : 0, rolled: !early && !!(g && g.rolled), dice: g ? g.dice : null,
''', 2),
    ('''function pineReplyGapEarly(clip, el, queue) {
  const tail = Number((clip && clip.tail_s) || 0);
''',
     '''function pineReplyGapEarly(clip, el, queue) {
  try { pineReplyGapBuildAhead(clip, el, queue); } catch (e) { /* [reply-gap:sting-overlap] */ }
  const tail = Number((clip && clip.tail_s) || 0);
''', 2),
]


def run(path, edits, mode):
    src = open(path, encoding="utf-8").read()
    if "[reply-gap:sting-overlap]" in src:
        print(path + ": APPLIED")
        return
    out = src
    for old, new, n in edits:
        got = out.count(old)
        assert got == n, "%s: anchor %r found %d times, want %d" % (path, old[:60], got, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/%s.bak-sting-overlap" % os.path.basename(path))
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, path + " changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    mode = sys.argv[1]
    run(os.path.join(ROOT, "reply_gap.py"), RG, mode)
    run(os.path.join(ROOT, "app.py"), APP, mode)
