"""[reply-gap:buildup-real] a dialogue line's buildup is never silently 0.

Measured 2026-09-30 on /api/dj stream_now: every seam INTO a sting carried
buildup_ms 3304 (its one clip table) and every seam INTO a host line carried 0,
so the dialogue cards - the ones the operator watches - were given no time for
their Rolodex. buildup_of_line / buildup_of_clip return 0 on any miss (no
conversation for the round, no turn id for the words, no tables left because a
first pass already CLAIMED them). Now:
  * a line's buildup is worked out once and remembered (_BUILD_MEMO, keyed by
    conversation + turn + seat), so a second pass never meets its own claim;
  * while System 3 is making the lines, a miss falls back to the contract's
    measured mean (or BUILD_DEFAULT_TABLES plain tables) instead of 0 - the
    page fits the real card to it (buildFit), every stage shown;
  * every miss is counted by its reason and GET /api/reply-gap says so
    (buildup_misses), so the real cause can be read off the live station.
Usage (ON THE HOST): python3 tools/buildup_fix_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITS = [
    ('''def buildup_of_line(meta: Any, who: str, text: str) -> int:
    """A burst row's buildup: a sting off the board is its clip's table; a
    line is its turn's fresh tables. 0 when System 3 did not make it."""
    try:
        if str(who or "") == "board":
            return buildup_ms([CLIP_TABLE])
        fn = _door("bank_s3_of")
        s3 = fn(meta) if fn else {}
        cid = str((s3 or {}).get("conversation_id") or "")
        conv = _conv(cid)
        if conv is None:
            return 0
        find = _door("system3_turn_id_for")
        tid = str(find(meta, str(text or ""), str(who or "")) or "") if find and text else ""
        ms = buildup_ms(turn_spec(conv, tid, who))
        _measured(ms)
        return ms
    except Exception:  # noqa: BLE001
        return 0
''', '''# [reply-gap:buildup-real] remembered buildups, and why a line had none
_BUILD_MEMO: dict[str, int] = {}
BUILD_MISSES: dict[str, int] = {}


def _build_miss(why: str) -> int:
    """A line System 3 made but whose tables could not be read: the contract's
    own estimate, never 0 (the page fits the real card to it)."""
    BUILD_MISSES[why] = BUILD_MISSES.get(why, 0) + 1
    try:
        return int(round(expected_buildup_s() * 1000))
    except Exception:  # noqa: BLE001
        return 0


def _build_memo(key: str, ms: int | None = None) -> int | None:
    if ms is None:
        return _BUILD_MEMO.get(key)
    _BUILD_MEMO[key] = int(ms)
    while len(_BUILD_MEMO) > 600:
        _BUILD_MEMO.pop(next(iter(_BUILD_MEMO)))
    return int(ms)


def buildup_of_line(meta: Any, who: str, text: str) -> int:
    """A burst row's buildup: a sting off the board is its clip's table; a
    line is its turn's fresh tables; 0 only when System 3 is not making lines."""
    try:
        if str(who or "") == "board":
            return buildup_ms([CLIP_TABLE])
        fn = _door("bank_s3_of")
        s3 = fn(meta) if fn else {}
        cid = str((s3 or {}).get("conversation_id") or "")
        conv = _conv(cid)
        if conv is None:
            return _build_miss("no conversation for the round" if cid else "the round has no System 3 id")
        find = _door("system3_turn_id_for")
        tid = str(find(meta, str(text or ""), str(who or "")) or "") if find and text else ""
        if not tid:
            return _build_miss("no turn for the words" if find else "system3_turn_id_for is missing")
        key = "%s|%s|%s" % (cid, tid, who)
        got = _build_memo(key)
        if got is not None:
            return got
        ms = buildup_ms(turn_spec(conv, tid, who))
        if ms <= 0:
            return _build_memo(key, _build_miss("the turn had no tables"))
        _measured(ms)
        return _build_memo(key, ms)
    except Exception:  # noqa: BLE001
        return _build_miss("the lookup raised")
''', 1),
    ('''        if not isinstance(stamp, dict) or not stamp.get("conversation_id"):
            return 0
        conv = _conv(str(stamp["conversation_id"]))
        if conv is None:
            return 0
        tid = str(stamp.get("turn_id") or "")
        if not tid:
            turns = conv.get("turns") or []
            tid = str((turns[0] or {}).get("turn_id") or "") if len(turns) == 1 else ""
        ms = buildup_ms(turn_spec(conv, tid, str(clip.get("who") or "")))
        _measured(ms)
        return ms
    except Exception:  # noqa: BLE001
        return 0
''', '''        if not isinstance(stamp, dict) or not stamp.get("conversation_id"):
            return 0
        conv = _conv(str(stamp["conversation_id"]))
        if conv is None:
            return _build_miss("no conversation for the line")
        tid = str(stamp.get("turn_id") or "")
        if not tid:
            turns = conv.get("turns") or []
            tid = str((turns[0] or {}).get("turn_id") or "") if len(turns) == 1 else ""
        if not tid:
            return _build_miss("no turn for the line")
        key = "%s|%s|%s" % (stamp["conversation_id"], tid, clip.get("who") or "")
        got = _build_memo(key)
        if got is not None:
            return got
        ms = buildup_ms(turn_spec(conv, tid, str(clip.get("who") or "")))
        if ms <= 0:
            return _build_memo(key, _build_miss("the turn had no tables"))
        _measured(ms)
        return _build_memo(key, ms)
    except Exception:  # noqa: BLE001
        return _build_miss("the lookup raised")
''', 1),
    ('''            "buildup": contract(),                                  # [reply-gap:buildup]
''', '''            "buildup": contract(),                                  # [reply-gap:buildup]
            "buildup_misses": dict(BUILD_MISSES),                   # [reply-gap:buildup-real]
''', 1),
]


def main() -> None:
    mode = sys.argv[1]
    path = os.path.join(ROOT, "reply_gap.py")
    src = open(path, encoding="utf-8").read()
    if "[reply-gap:buildup-real]" in src:
        print(path + ": APPLIED")
        return
    out = src
    for old, new, n in EDITS:
        got = out.count(old)
        assert got == n, "anchor %r found %d times" % (old[:50], got)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        return
    shutil.copy(path, "/tmp/reply_gap.py.bak-buildup-real")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
