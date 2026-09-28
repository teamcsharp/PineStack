"""[s3-sfx-roll] The board's clip is two of System 3's rolls, and the node
shows what they landed on.

Operator: "Everything as nodes ... For SFX it would roll the roulette to the
SFX effect and then roll the roulette for the sfx that is to be played then
pop in the thumbnail for the result on the node." And: every random decision
on the station is a System 3 roll, tabled and recorded.

The punctuation clip between a round's turns was `random.choices` over the
drop folders' pool (_sfx_cadence_pick) and `random.choice` / `randrange` in
the clip book (sfx_db_pick_short_video) - the station's own dice, never on
the record. This walks all three pick roads through the dice door:

  _sfx_cadence_pick         the audio pool: the family (the clip's drop
                            folder, weighed as the sum of its clips' SFX
                            weights - so each clip's odds are exactly what
                            the one weighted draw gave it), then the clip in
                            it (its own weight). Filters first (bans,
                            weights, the sfx-cadence ring), the file check
                            after; a clip that fails it is rolled again among
                            the rest, at most 64 draws as before, each
                            recorded.
  sfx_db_pick_short_video   the clip book, when the cadence hands it a
                            `rolled` dict (System 3 live): the folder (fresh
                            folders first, even odds, as the book's own
                            rule), then the clip in it (even odds, the whole
                            family is the wheel). Every other caller draws
                            exactly as it did.
  _sfx_cadence_video_pick   hands the book that dict under System 3; a draw
                            the filters refuse (bans, weights, the sting
                            ring, the video cooldown) is rolled again, and
                            the draws stop at the two this road tries.
  sfx_match_sting_pick      a scored match: the matcher ranks, the tied peers
                            over its floor survive the filters, and WHICH of
                            them plays was the ring's random.choice - now a
                            recorded pick among those peers (_S3ClipDice).

Each road notes its rolls against the clip (_sfx_roll_note); the cadence
takes the note onto the board's addition row with the clip's picture
(_sfx_roll_carry: "sfx_roll", and "poster" for a video), and the round's
ledger stamp carries both (_s3_row_of) to the script ledger and, through
system3_observe_ledger, to the conversation's line. The dice are read back
off the runtime's record of the roll (system3_last_roll), never re-derived.

System 3 off: the door's own fallback - the same weighted draw off the
station's random, the same filters and bounds; the book is not asked to roll
at all. Needs system3_runtime.py with edit_sfx_roll_runtime.py applied (the
door passes `media` to system3_pick; system3_last_roll, system3_dice_live).

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

EDITS = [
    # --- the door: a pick carries the picture of what it lands on ------------
    ("dice-media",
     r'''    def __init__(self, key: str, label: str = "", weights: Any = None) -> None:
        self.key, self.label, self.weights = key, label, weights

    def pick(self, _label: str, candidates: list[Any]) -> int:
        fn = globals().get("system3_pick")
        if fn and candidates:
            try:
                got = fn(self.key, [str(c) for c in candidates], self.label, self.weights)
''',
     r'''    def __init__(self, key: str, label: str = "", weights: Any = None, media: Any = None) -> None:
        self.key, self.label, self.weights = key, label, weights
        self.media = media          # [s3-sfx-roll] the picture of what it lands on (a list, or a callable of the index)

    def pick(self, _label: str, candidates: list[Any]) -> int:
        fn = globals().get("system3_pick")
        if fn and candidates:
            try:
                got = fn(self.key, [str(c) for c in candidates], self.label, self.weights,
                         **({"media": self.media} if self.media is not None else {}))   # [s3-sfx-roll]
''', 1),
    ("weighted-media-and-helpers",
     r'''def s3_weighted(key: str, labels: list[str], weights: list[float], label: str = "") -> int:
    """A draw by weights the station keeps itself (the ending shelf, the
    behaviour deck): System 3's number, those weights, recorded."""
    return _S3Dice(key, label, list(weights)).pick(key, list(labels))
''',
     r'''def s3_weighted(key: str, labels: list[str], weights: list[float], label: str = "",
                media: Any = None) -> int:
    """A draw by weights the station keeps itself (the ending shelf, the
    behaviour deck): System 3's number, those weights, recorded.
    [s3-sfx-roll] `media`: the picture of what it lands on, for the record."""
    return _S3Dice(key, label, list(weights), media).pick(key, list(labels))


# --- [s3-sfx-roll] THE BOARD'S CLIP IS TWO OF SYSTEM 3'S ROLLS ----------------
# "For SFX it would roll the roulette to the SFX effect and then roll the
# roulette for the sfx that is to be played then pop in the thumbnail for the
# result on the node" (operator). The pick roads (_sfx_cadence_pick, the clip
# book's sfx_db_pick_short_video, the matcher's sfx_match_sting_pick) roll
# through the door above and note what they rolled against the clip; the
# cadence takes the note onto the board's addition row, whose stamp carries
# it to the script ledger and to the conversation's line - the node.
_SFX_ROLLED: dict[str, dict[str, Any]] = {}
_SFX_ROLLED_LOCK = RLock()


class _S3ClipDice(_S3Dice):
    """A director over clip paths (the matcher's tied peers): the roll is
    recorded by the clips' names, with the picture of the one it lands on."""

    def pick(self, _label: str, candidates: list[Any]) -> int:
        paths = [Path(str(c)) for c in candidates]
        self.media = lambda k: _sfx_roll_media(paths[k])
        return super().pick(_label, [p.stem for p in paths])


def _s3_dice_live() -> bool:
    """Whether System 3's dice answer the station's rolls right now (off, or
    not loaded yet: the station rolls its own)."""
    fn = globals().get("system3_dice_live")
    try:
        return bool(fn and fn())
    except Exception:  # noqa: BLE001
        return False


def _sfx_roll_media(path: Path) -> dict[str, Any]:
    """The picture a clip has, the way the history strip draws it (#1199): a
    video's own frame (/api/sfx/poster), an audio clip's spectrogram
    (/api/sfx/spec - the poster route answers 404 for audio, honestly)."""
    sid = sfx_id(path)
    sig = media_sign(sid)
    video = sfx_is_video(path)
    out = {"id": sid, "kind": "video" if video else "audio",
           "thumb": ("/api/sfx/poster/%s?t=%s" if video else "/api/sfx/spec/%s?t=%s") % (sid, sig),
           "thumb_kind": "frame" if video else "spectrogram"}
    if video:
        out["poster"] = out["thumb"]
    return out


def _s3_sfx_rolled(key: str, label: str, index: int | None = None) -> dict[str, Any]:
    """The roll System 3 just recorded for this draw, as the node shows it:
    what it landed on, the d100, of how many. Read back off the runtime's
    record, never re-derived - and only when it is this draw's ({} when the
    station rolled its own)."""
    fn = globals().get("system3_last_roll")
    try:
        rec = fn(key) if fn else None
    except Exception:  # noqa: BLE001
        rec = None
    if (not isinstance(rec, dict) or time.time() - float(rec.get("at") or 0) > 30
            or rec.get("picked") != " ".join(str(label).split())[:160]
            or (index is not None and rec.get("index") != index + 1)):
        return {}
    return {"label": str(label)[:160], "dice": rec.get("dice"), "u": rec.get("u"),
            "of": rec.get("of"), "index": rec.get("index")}


def _s3_sfx_roll(key: str, labels: list[str], weights: list[float], question: str,
                 media: Any = None) -> tuple[int, dict[str, Any]]:
    """One of the board's rolls through the door: the index, and its record."""
    k = s3_weighted(key, labels, weights, question, media=media)
    return k, _s3_sfx_rolled(key, labels[k], k)


def _sfx_roll_note(path: Any, road: str, category: dict[str, Any],
                   clip: dict[str, Any], tries: int) -> None:
    """Keep the rolls that chose `path` for the line it is about to make: the
    pick roads return a path, and their caller writes the row."""
    if not clip:
        return                  # the station's own draw: no System 3 dice to show
    got = {"at": time.time(), "road": str(road),
           "category": dict(category or {}) or {"label": Path(str(path)).parent.name},
           "clip": dict(clip, tries=int(tries))}
    with _SFX_ROLLED_LOCK:
        _SFX_ROLLED.pop(str(path), None)
        _SFX_ROLLED[str(path)] = got
        while len(_SFX_ROLLED) > 32:
            _SFX_ROLLED.pop(next(iter(_SFX_ROLLED)))


def _sfx_roll_take(path: Any) -> dict[str, Any]:
    with _SFX_ROLLED_LOCK:
        got = _SFX_ROLLED.pop(str(path), None)
    if not got or time.time() - float(got.pop("at", 0) or 0) > 120:
        return {}
    return got


def _sfx_roll_carry(row: dict[str, Any], sample: Path) -> None:
    """The board's addition row takes its clip's picture and the rolls that
    chose it - the node's thumbnail and dice. Never costs the clip."""
    try:
        pic = _sfx_roll_media(sample)
        if pic.get("poster"):
            row["poster"] = pic["poster"]
        roll = _sfx_roll_take(sample)
        if roll:
            row["sfx_roll"] = dict(roll, thumb=pic["thumb"], thumb_kind=pic["thumb_kind"])
    except Exception:  # noqa: BLE001
        pass
''', 1),
    # --- the matcher: which of the tied peers plays is a recorded pick -------
    ("match-pick",
     r'''    got = unrepeated(survivors, "sting",
                     keep=sting_keep(len(set(survivors))))         # #1223
    if not got:
        _SFX_MATCH["fell_back"] = int(_SFX_MATCH.get("fell_back") or 0) + 1
        return None
    why, score = why_by_path.get(got, ("", 0.0))
''',
     r'''    got = unrepeated(survivors, "sting",
                     keep=sting_keep(len(set(survivors))),         # #1223
                     director=_S3ClipDice("sfx.match", "which of the clips matched to the line plays "
                                          "(the tied peers over the floor)"))   # [s3-sfx-roll]
    if not got:
        _SFX_MATCH["fell_back"] = int(_SFX_MATCH.get("fell_back") or 0) + 1
        return None
    why, score = why_by_path.get(got, ("", 0.0))
    # [s3-sfx-roll] the matcher's score chose the peers, not a roll; which
    # of them plays was System 3's - kept for the line the clip makes
    _sfx_roll_note(got, "match", {"label": Path(got).parent.name, "dice": None, "of": None,
                                  "by": "the matcher's score (#1251)"},
                   _s3_sfx_rolled("sfx.match", Path(got).stem), 1)
''', 1),
    # --- the drop folders' pool: the family, then the clip -------------------
    ("pool-two-rolls",
     r'''    # Never walk the share or probe its entire catalogue on the microphone.
    for _ in range(min(64, len(pool))):
        path = random.choices(pool, weights=[weights.get(sfx_id(p), 1.0) for p in pool], k=1)[0]
        pool.remove(path)
        if path.is_file() and 0 < sfx_seconds(path) <= min(12.0, sfx_cap_seconds()):
''',
     r'''    # Never walk the share or probe its entire catalogue on the microphone.
    # [s3-sfx-roll] THE FAMILY, THEN THE CLIP: each draw is two of System 3's
    # rolls among what the filters above left - the drop folder, weighed as
    # the sum of its clips' weights (so a clip's odds are exactly what the one
    # weighted draw gave it), then the clip in it. A clip that fails the file
    # check is rolled again among the rest, every roll recorded. System 3
    # off: the same two draws off the station's random.
    _fam: dict[str, list[tuple[Path, float]]] = {}
    for p in pool:
        _fam.setdefault(p.parent.name, []).append((p, weights.get(sfx_id(p), 1.0)))
    for _try in range(min(64, len(pool))):
        _names = [name for name, clips in _fam.items() if clips]
        _k, _cat = _s3_sfx_roll("sfx.category", _names, [sum(w for _p, w in _fam[n]) for n in _names],
                                "which effect family the board reaches into")
        _in = _fam[_names[_k]]
        _j, _clip = _s3_sfx_roll("sfx.clip", [p.stem for p, _w in _in], [w for _p, w in _in],
                                 "which clip in " + _names[_k],
                                 media=lambda j, _in=_in: _sfx_roll_media(_in[j][0]))
        path = _in.pop(_j)[0]
        if path.is_file() and 0 < sfx_seconds(path) <= min(12.0, sfx_cap_seconds()):
            _sfx_roll_note(path, "pool", _cat, _clip, _try + 1)              # [s3-sfx-roll]
''', 1),
    # --- the clip book: the folder, then the clip, when the cadence asks -----
    ("book-signature",
     r'''def sfx_db_pick_short_video(max_seconds: float) -> tuple[Path, float] | None:
    """Draw an unspent short video, balancing folders before clips."""
''',
     r'''def sfx_db_pick_short_video(max_seconds: float,
                            rolled: dict | None = None) -> tuple[Path, float] | None:
    """Draw an unspent short video, balancing folders before clips.

    [s3-sfx-roll] Handed a `rolled` dict (the cadence, under System 3), both
    draws are System 3's rolls - the folder (the family), then the clip in
    it, each at even odds as the station's own - and what they landed on is
    written into it ("category", "clip") for the line the clip makes."""
''', 1),
    ("book-two-rolls",
     r'''        fresh = [row for row in folders if str(row[0] or "") not in recent]
        folder, count = random.choice(fresh or folders)
        where += " AND folder = ?"
        args += (folder,)
''',
     '        fresh = [row for row in folders if str(row[0] or "") not in recent]\n'
     '        if rolled is None:\n'
     '            _fl = fresh or folders   # [s3-dice-door]\n'
     '            folder, count = _fl[_S3Dice("sfxtv.short_folder", "which folder a short SFX video comes from (unspent folders first)").pick(   # [s3-dice-door]\n'
     '                "folder", [str(r[0] or "") for r in _fl])]   # [s3-dice-door]\n'
     '        else:                                                               # [s3-sfx-roll]\n'
     '            _fams = fresh or folders\n'
     '            _k, rolled["category"] = _s3_sfx_roll(\n'
     '                "sfx.category", [str(r[0] or "") for r in _fams], [1.0] * len(_fams),\n'
     '                "which effect family the board reaches into (the clip book)")\n'
     '            folder, count = _fams[_k]\n'
     '        where += " AND folder = ?"\n'
     '        args += (folder,)\n'
     '        if rolled is not None:                                              # [s3-sfx-roll]\n'
     '            # the whole family is the wheel (one indexed read, ~18k names in\n'
     '            # the biggest today), so the roll lands on a name, not an offset\n'
     '            rows = con.execute("SELECT path, seconds FROM clips WHERE " + where, args).fetchall()\n'
     '            if not rows:\n'
     '                return None\n'
     '            _k, rolled["clip"] = _s3_sfx_roll(\n'
     '                "sfx.clip", [str(r[0]).rsplit("/", 1)[-1].rsplit(".", 1)[0] for r in rows],\n'
     '                [1.0] * len(rows), "which clip in " + str(folder),\n'
     '                media=lambda k: _sfx_roll_media(Path(str(rows[k][0]))))\n'
     '            return Path(str(rows[_k][0])), float(rows[_k][1])\n', 1),
    # --- the cadence's picture road hands the book its dice ------------------
    ("video-rolls",
     r'''    banned, weights = sfx_bans(), sfx_weights()
    for _ in range(min(6, SFX_CADENCE_TRIES)):
        row = sfx_db_pick_short_video(min(12.0, sfx_cap_seconds()))
        if not row:
            break
        path, seconds = row
        key = sfx_id(path)
        if (key in banned or weights.get(key, 1.0) <= 0.05
                or sting_recent(str(path)) or sfx_video_on_cooldown(key)):
            continue
        candidates.append((path, float(seconds), ""))
''',
     r'''    banned, weights = sfx_bans(), sfx_weights()
    # [s3-sfx-roll] under System 3 each draw from the book is two of its
    # rolls (the folder, then the clip in it), recorded; one the filters
    # refuse is rolled again, and the draws stop at the two this road tries -
    # a roll nobody would try is not one to put on the record.
    _live, _rolls = _s3_dice_live(), {}
    for _draw in range(min(6, SFX_CADENCE_TRIES)):
        _rolled: dict[str, Any] | None = {} if _live else None
        row = (sfx_db_pick_short_video(min(12.0, sfx_cap_seconds())) if _rolled is None
               else sfx_db_pick_short_video(min(12.0, sfx_cap_seconds()), rolled=_rolled))
        if not row:
            break
        path, seconds = row
        key = sfx_id(path)
        if (key in banned or weights.get(key, 1.0) <= 0.05
                or sting_recent(str(path)) or sfx_video_on_cooldown(key)):
            continue
        candidates.append((path, float(seconds), ""))
        if _rolled:                                                         # [s3-sfx-roll]
            _rolls[str(path)] = (_rolled, _draw + 1)
        if _live and len(candidates) >= 2:
            break
''', 1),
    ("video-note",
     r'''        if audio.suffix.lower() == ".wav" and audio.is_file():
            _sfx_video_rotation_mark_clip(sfx_id(path), path.parent.name)
''',
     r'''        if audio.suffix.lower() == ".wav" and audio.is_file():
            _sfx_video_rotation_mark_clip(sfx_id(path), path.parent.name)
            if str(path) in _rolls:                                         # [s3-sfx-roll]
                _r, _n = _rolls[str(path)]
                _sfx_roll_note(path, "book", _r.get("category") or {}, _r.get("clip") or {}, _n)
''', 1),
    # --- the board's addition row carries its rolls and its picture ----------
    ("carry",
     r'''                additions[-1].update({"sfx_video_id": sfx_id(sample),
                                      "sfx_video_seconds": duration,
                                      "sfx_match_why": why})
            if not _s3_active() and complaint_due():
''',
     r'''                additions[-1].update({"sfx_video_id": sfx_id(sample),
                                      "sfx_video_seconds": duration,
                                      "sfx_match_why": why})
            _sfx_roll_carry(additions[-1], sample)                              # [s3-sfx-roll]
            if not _s3_active() and complaint_due():
''', 1),
    # --- ...and the round's ledger stamp carries them to the node ------------
    ("stamp-rename",
     r'''                def _s3_row_of(_row_at: int) -> dict[str, Any]:
                    # System 3 (docs/SYSTEM3_EVENT_SCHEMA.md): the
''',
     r'''                def _s3_row_bare(_row_at: int) -> dict[str, Any]:
                    # System 3 (docs/SYSTEM3_EVENT_SCHEMA.md): the
''', 1),
    ("stamp-media",
     r'''                    return {"conversation_id": str(_s3m.get("conversation_id") or ""),
                            "mode": str(_s3m.get("mode") or ""),
                            "turn_id": _tid}
                _script_rows = [
''',
     r'''                    return {"conversation_id": str(_s3m.get("conversation_id") or ""),
                            "mode": str(_s3m.get("mode") or ""),
                            "turn_id": _tid}

                def _s3_row_of(_row_at: int) -> dict[str, Any]:
                    # [s3-sfx-roll] the board's clip: the rolls that chose it
                    # and its picture ride its stamp, to the ledger and the node
                    _st = _s3_row_bare(_row_at)
                    _mx = _sfx_meta.get(_row_at)
                    if _st and isinstance(_mx, dict) and (_mx.get("sfx_roll") or _mx.get("poster")):
                        _st = dict(_st, **{k: _mx[k] for k in ("sfx_roll", "poster") if _mx.get(k)})
                    return _st
                _script_rows = [
''', 1),
]


def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
