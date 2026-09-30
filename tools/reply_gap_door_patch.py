"""[reply-gap:door] The pause before EVERY message, and the dice that show it.

2026-09-30, the operator: "anytime a message plays, the moment the message
finishes, the dice rolls to determine how long to wait before the next
message begins playing", with a small bar counting down to the next reply.

Why the dice never moved on the tablet: 4240167 set the pause only at the
seams INSIDE a welded round (the burst mixer's beats). Most of the air is not
a welded round - of 261 files aired in three hours 222 were single clips
(callers, asides, station ids, ads, stings, dj_speak lines) - so in the
window the operator watched, with the roulette on, the burst road rolled
nothing (data/reply_gap_rolls.jsonl: two rolls, both on the punctuation join,
which has no dice). The square showed "2.2" only because the panel painted
the newest receipt, still, when it loaded.

  app.py   page_feed_append (#1147's one door, every road's clip passes it):
           each message is stamped to start the pause - or the System 3
           roll - after the last message's WORDS end, its measured silent
           tail given up to a shorter pause (gap_before, tail_s,
           air_seconds). The page cursor honours that overlap. The panel's
           and the tune page's players keep the pause even when running
           behind, hand over at the words' end when the next is due, and
           the panel tells the views ("pine-reply-gap") the moment a message
           ends and exactly when the next starts - the player's own timer.
  station_stream.py  the stream mixer hands over at the words' end too, so
           the car and every HLS listener hear the same pause.

Usage (ON THE HOST): python3 tools/reply_gap_door_patch.py --check|--apply app.py station_stream.py
--check exits 0 ready, 2 applied, 1 broken. Anchors asserted unique; LF; atomic."""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

PY_HELPERS_AT = '''            return float(_reply_gap.carry_seconds(notes, length, rows))
    except Exception:  # noqa: BLE001
        pass
    return 0.0
'''
PY_HELPERS = '''

# [reply-gap:door] THE PAUSE BEFORE EVERY MESSAGE (reply_gap.door): stamped in
# page_feed_append, the one door every road's clip passes.
def reply_gap_tail_of(clip: dict[str, Any]) -> float:
    """The measured silence on the end of a spoken clip (a /media/ wav: the
    mixer's own reading, memoised); 0 for anything else - a sting off the
    sample shelf carries none, and nothing on CIFS is touched from here."""
    try:
        url = str((clip or {}).get("url") or "").split("?", 1)[0]
        if not url.startswith("/media/") or not url.lower().endswith(".wav"):
            return 0.0
        path = _stream_clip_path(url)
        got = seg_tails_for([path])[0] if path else -1.0
        return max(0.0, float(got)) if got is not None and got >= 0 else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def reply_gap_door(clip: dict[str, Any], air_until: float, earliest: float) -> float | None:
    """[reply-gap:door] When this message starts, its pause stamped on it; None
    leaves the door's old rule (not a message, or the module is missing)."""
    if _reply_gap is None:
        return None
    try:
        return _reply_gap.door(clip, air_until, earliest, tail_of=reply_gap_tail_of)
    except Exception:  # noqa: BLE001
        return None


def reply_gap_booked(clip: dict[str, Any], until: float) -> None:
    if _reply_gap is not None:
        _reply_gap.booked(clip, until)


def reply_gap_overlap(clip: dict[str, Any]) -> float:
    try:
        return float(_reply_gap.overlap(clip)) if _reply_gap is not None else 0.0
    except Exception:  # noqa: BLE001
        return 0.0
'''

DOOR_OLD = '''        if str(clip.get("kind") or "") != "reply":
            clip["broadcast_ms"] = max(int(clip["broadcast_ms"]),
                                        int(float(_PAGE_AIR_UNTIL[0] or 0) * 1000))
            duration = page_clip_seconds(clip)
            _PAGE_AIR_UNTIL[0] = max(float(_PAGE_AIR_UNTIL[0] or 0),
                clip["broadcast_ms"] / 1000.0 + duration)
'''
DOOR_NEW = '''        if str(clip.get("kind") or "") != "reply":
            # [reply-gap:door] THE PAUSE BEFORE THIS MESSAGE: the operator's
            # gap, or a System 3 roll, after the last message's WORDS end -
            # into its measured silent tail when the pause is shorter. Every
            # road's clip passes here, so every message gets it; a quiet air
            # has no seam and rolls nothing.
            _rg_air = float(_PAGE_AIR_UNTIL[0] or 0)
            _rg_start = reply_gap_door(clip, _rg_air, time.time() + lead)
            clip["broadcast_ms"] = (int(_rg_start * 1000) if _rg_start is not None
                                    else max(int(clip["broadcast_ms"]),
                                             int(_rg_air * 1000)))
            duration = page_clip_seconds(clip)
            clip.setdefault("air_seconds", round(float(duration or 0), 3))
            _PAGE_AIR_UNTIL[0] = max(float(_PAGE_AIR_UNTIL[0] or 0),
                clip["broadcast_ms"] / 1000.0 + duration)
            reply_gap_booked(clip, clip["broadcast_ms"] / 1000.0 + duration)
'''

REPAIR_OLD = '''        cursor = max(cursor, start) + duration
'''
REPAIR_NEW = '''        # [reply-gap:door] a clip stamped into the last one's silent tail
        # starts that much before the cursor; chaining the whole tail would
        # grow every later pause
        cursor = max(cursor - reply_gap_overlap(clip), start) + duration
'''

SNAP_OLD = '''                          "sfx": _u.startswith("/sfx/")})
'''
SNAP_NEW = '''                          "sfx": _u.startswith("/sfx/"),
                          # [reply-gap:door] the words' end, for the hand-over
                          "tail": float(clip.get("tail_s") or 0),
                          "seconds": float(clip.get("air_seconds") or 0)})
'''

JS_HELPERS = '''/* [reply-gap:door] THE PAUSE BETWEEN MESSAGES, ON THIS PAGE. The station
 * stamps every message with the pause before it (gap_before: the operator's
 * gap, or the System 3 roll) and with its own measured silent tail (tail_s).
 * The page keeps that pause even when it runs behind its stamps, hands over
 * at the words' end when the next message is due inside that tail, and
 * tells the views the moment a message ends and exactly when the next one
 * starts ("pine-reply-gap": the player's own timer, not a second clock). */
let pineReplyGapEndAt = 0;
function pineReplyGapFloor(clip) {
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
function pineReplyGapDue(next) {
  return Math.max(Number(next.broadcastAt || 0), Number(next.retryAt || 0),
                  pineReplyGapFloor(next));
}
/* The moment the words end - the clip's end less its silent tail - is the
 * moment the pause begins, and the moment the views are told. */
function pineReplyGapWordsEnded(clip, el, queue) {
  if (!clip || clip.pineWordsEnded) return;
  clip.pineWordsEnded = true;
  const tail = Math.max(0, Number(clip.tail_s || 0));
  let over = 0;
  if (el && isFinite(el.duration)) {
    over = Math.max(0, Number(el.currentTime || 0) - Math.max(0, el.duration - tail));
  } else {
    over = tail;
  }
  pineReplyGapEndAt = Date.now() - over * 1000;
  const next = queue && queue[0];
  if (next && next.gap_before) pineReplyGapCue(next, pineReplyGapDue(next) - Date.now());
}
function pineReplyGapEarly(clip, el, queue) {
  const tail = Number((clip && clip.tail_s) || 0);
  if (!(tail > 0.05) || !el || !isFinite(el.duration)) return false;
  if (Number(el.currentTime || 0) < el.duration - tail) return false;
  pineReplyGapWordsEnded(clip, el, queue);
  const next = queue && queue[0];
  if (!next || !next.gap_before) return false;
  return pineReplyGapDue(next) - Date.now() <= 120;
}
'''

EDITS_APP: list[tuple[str, str, str]] = [
    ("py helpers", PY_HELPERS_AT, PY_HELPERS_AT + PY_HELPERS),
    ("page door", DOOR_OLD, DOOR_NEW),
    ("page cursor", REPAIR_OLD, REPAIR_NEW),
    ("stream snapshot", SNAP_OLD, SNAP_NEW),
    # --- the panel's player (CONTROL_PANEL_HTML) ---
    ("panel helpers", '''function djVoiceNext() {
''', JS_HELPERS + '''function djVoiceNext() {
'''),
    ("panel wait",
     '''  const broadcastAt = Number(clip.broadcastAt || Date.now());
  const waitForAir = Math.max(broadcastAt, Number(clip.retryAt || 0)) - Date.now();
  if (waitForAir > 25) {
    /* #1147: one deduped timer, no queue mutation, no slot flip - and
''',
     '''  const broadcastAt = Number(clip.broadcastAt || Date.now());
  /* [reply-gap:door] ...and never sooner than the pause after the last words */
  const waitForAir = Math.max(broadcastAt, Number(clip.retryAt || 0),
                              pineReplyGapFloor(clip)) - Date.now();
  pineReplyGapCue(clip, waitForAir);
  if (waitForAir > 25) {
    /* #1147: one deduped timer, no queue mutation, no slot flip - and
'''),
    ("panel words end",
     '''  player.ontimeupdate = () => {
    if (started && !staleEpoch() && !player.paused) {
      djVoiceAck(clip, "playing", player);
''',
     '''  player.ontimeupdate = () => {
    if (started && !staleEpoch() && !player.paused) {
      djVoiceAck(clip, "playing", player);
      /* [reply-gap:door] the words are over and the next message is due
       * inside this clip's silent tail: silence it and hand over */
      if (pineReplyGapEarly(clip, player, djVoiceQueue)) {
        try { player.pause(); } catch (e) { /* it is silence either way */ }
        djVoiceAck(clip, "ended", player);
        done();
        return;
      }
'''),
    ("panel ended",
     '''  player.onended = () => { djVoiceAck(clip, "ended", player); done(); };
''',
     '''  player.onended = () => {
    pineReplyGapWordsEnded(clip, null, djVoiceQueue);   /* [reply-gap:door] */
    djVoiceAck(clip, "ended", player); done();
  };
'''),
    # --- the tune page's player (RADIO_PAGE_HTML) ---
    ("tune helpers", '''function voiceNext() {
''', JS_HELPERS + '''function voiceNext() {
'''),
    ("tune wait",
     '''  const broadcastAt = Number(clip.broadcastAt || Date.now());
  const waitForAir = Math.max(broadcastAt, Number(clip.retryAt || 0)) - Date.now();
  if (waitForAir > 25) {
    if (voiceTimer) clearTimeout(voiceTimer);
''',
     '''  const broadcastAt = Number(clip.broadcastAt || Date.now());
  /* [reply-gap:door] ...and never sooner than the pause after the last words */
  const waitForAir = Math.max(broadcastAt, Number(clip.retryAt || 0),
                              pineReplyGapFloor(clip)) - Date.now();
  pineReplyGapCue(clip, waitForAir);
  if (waitForAir > 25) {
    if (voiceTimer) clearTimeout(voiceTimer);
'''),
    ("tune words end",
     '''  voice.ontimeupdate = () => {
    if (!finished && !stale() && !voice.paused) {
      voiceAck(clip, "playing");
''',
     '''  voice.ontimeupdate = () => {
    if (!finished && !stale() && !voice.paused) {
      voiceAck(clip, "playing");
      /* [reply-gap:door] the words are over and the next message is due */
      if (pineReplyGapEarly(clip, voice, voiceQueue)) {
        try { voice.pause(); } catch (e) { /* it is silence either way */ }
        voiceAck(clip, "ended");
        finish();
        return;
      }
'''),
    # --- a paged round books its end from where the door started it ---
    ("py started helper",
     '''def reply_gap_overlap(clip: dict[str, Any]) -> float:
    try:
        return float(_reply_gap.overlap(clip)) if _reply_gap is not None else 0.0
    except Exception:  # noqa: BLE001
        return 0.0
''',
     '''def reply_gap_overlap(clip: dict[str, Any]) -> float:
    try:
        return float(_reply_gap.overlap(clip)) if _reply_gap is not None else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def reply_gap_started(rows: Any, default: float) -> float:
    """[reply-gap:door] where the door started the burst carrying `rows`."""
    try:
        return float(_reply_gap.started(rows, default)) if _reply_gap is not None else float(default)
    except Exception:  # noqa: BLE001
        return float(default)
'''),
    ("page started",
     '''                    _paged_until = (_pstart + max(0.0, float(length or 0))
                                    # [reply-gap] the pause into the next page
''',
     '''                    _paged_until = (reply_gap_started(rows, _pstart)   # [reply-gap:door] the door's start
                                    + max(0.0, float(length or 0))
                                    # [reply-gap] the pause into the next page
'''),
    ("tune ended",
     '''  voice.onended = () => { voiceAck(clip, "ended"); finish(); };
''',
     '''  voice.onended = () => {
    pineReplyGapWordsEnded(clip, null, voiceQueue);     /* [reply-gap:door] */
    voiceAck(clip, "ended"); finish();
  };
'''),
]

EDITS_STREAM: list[tuple[str, str, str]] = [
    ("voice slots",
     '''    __slots__ = ("key", "air_at", "path", "length", "sfx", "decoder", "started")

    def __init__(self, key: str, air_at: float, path: str,
                 length: float, sfx: bool = False) -> None:
        self.key = key
        self.air_at = float(air_at)
        self.path = path
        self.length = float(length or 0)
        self.sfx = bool(sfx)
        self.decoder: _Decoder | None = None
        self.started = False
''',
     '''    __slots__ = ("key", "air_at", "path", "length", "sfx", "decoder", "started",
                 "tail", "seconds", "played")

    def __init__(self, key: str, air_at: float, path: str,
                 length: float, sfx: bool = False, tail: float = 0.0,
                 seconds: float = 0.0) -> None:
        self.key = key
        self.air_at = float(air_at)
        self.path = path
        self.length = float(length or 0)
        self.sfx = bool(sfx)
        self.decoder: _Decoder | None = None
        self.started = False
        # [reply-gap:door] the clip's measured silent tail and its length:
        # once `played` reaches the words' end and the next message is due,
        # the tail gives way (the operator's pause may be shorter than it)
        self.tail = max(0.0, float(tail or 0))
        self.seconds = max(0.0, float(seconds or 0))
        self.played = 0.0
'''),
    ("voice from row",
     '''                        voice = _Voice(key, air_at, path,
                                       float(row.get("length") or 0),
                                       bool(row.get("sfx")))
''',
     '''                        voice = _Voice(key, air_at, path,
                                       float(row.get("length") or 0),
                                       bool(row.get("sfx")),
                                       float(row.get("tail") or 0),     # [reply-gap:door]
                                       float(row.get("seconds") or 0))
'''),
    ("hand over at the words' end",
     '''                if airing is None and on_air and pending:
''',
     '''                # [reply-gap:door] the words are over, the rest is the clip's
                # silent tail, and the next message is due: it gives way.
                if (airing is not None and pending and airing.tail > 0.05
                        and airing.seconds > 0 and now >= pending[0].air_at
                        and airing.played >= airing.seconds - airing.tail):
                    if airing.decoder is not None:
                        airing.decoder.close()
                    airing = None
                if airing is None and on_air and pending:
'''),
    ("count what played",
     '''                        raw, live = airing.decoder.read_frame()
                        if live:
                            voice_pcm = _centered_pcm(raw)
''',
     '''                        raw, live = airing.decoder.read_frame()
                        if live:
                            voice_pcm = _centered_pcm(raw)
                            airing.played += FRAME_MS / 1000.0   # [reply-gap:door]
'''),
]


def _read(path: Path) -> str:
    raw = path.read_bytes().decode("utf-8")
    if "\r\n" in raw:
        raise SystemExit("%s has CRLF line endings - normalise to LF first" % path)
    return raw


# An insertion a later patch rewrites in place ([reply-gap:buildup] rewrites
# the page helpers) is recognised by its header: never inserted twice.
HELPER_HEAD = "/* [reply-gap:door] THE PAUSE BETWEEN MESSAGES, ON THIS PAGE."
SENTINELS = {"panel helpers": (HELPER_HEAD, 1), "tune helpers": (HELPER_HEAD, 2)}


def _sentinel(text: str, name: str) -> bool:
    got = SENTINELS.get(name)
    return bool(got) and text.count(got[0]) >= got[1]


def _state(text: str, edits) -> tuple[int, list[str]]:
    # In order, as --apply would: a later edit may anchor on text an earlier
    # one inserts (the burst's start helper sits beside the door helpers).
    applied, missing, ready = [], [], []
    sim = text
    for name, old, new in edits:
        n_old, n_new = sim.count(old), sim.count(new)
        if _sentinel(sim, name):
            applied.append(name)
        elif n_new == 1 and (n_old == 0 or (new.find(old) >= 0 and n_old == 1)):
            applied.append(name)
        elif n_old == 1:
            ready.append(name)
            sim = sim.replace(old, new, 1)
        else:
            missing.append("%s (anchor x%d)" % (name, n_old))
    if missing:
        return 1, missing
    if applied and not ready:
        return 2, []
    if applied and ready:
        # a later edit added to this tool: the ones already in are kept,
        # the new ones go in (each is still asserted unique)
        return 0, ["partly applied, still to go: " + ", ".join(ready)]
    return 0, []


def _is_applied(text: str, old: str, new: str) -> bool:
    n_old, n_new = text.count(old), text.count(new)
    return n_new == 1 and (n_old == 0 or (new.find(old) >= 0 and n_old == 1))


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    codes = []
    for raw in argv[2:]:
        path = Path(raw)
        edits = EDITS_STREAM if path.name.startswith("station_stream") else EDITS_APP
        text = _read(path)
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
        done = 0
        for name, old, new in edits:
            if _sentinel(text, name) or _is_applied(text, old, new):
                continue
            if text.count(old) != 1:
                raise SystemExit("anchor %s: found %d times" % (name, text.count(old)))
            text = text.replace(old, new, 1)
            done += 1
        ast.parse(text)
        tmp = path.with_name(path.name + ".rgtmp")
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
        print("%s: applied %d edits" % (path, done))
    if argv[1] == "--check":
        return 1 if 1 in codes else 2 if all(c == 2 for c in codes) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
