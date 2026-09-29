"""[s3-reair-copy] reair_gate.py: a stored round drawn for re-air passes the SAME
copy gate a new round passes (system3.gate_check), or it never airs again.

Measured 2026-09-29 (the [s3-slash] investigation): rounds banked before the
copy gate went live (bcc018c) still re-air with copied sentences - memo bank
c33d5f0988e4 (conversation 90b75136) aired whole three times, 13:51Z / 16:51Z
/ 04:18Z. The re-air gate's own copy rule compares WHOLE turns at 90% alike,
so a sentence copied inside a longer turn, or said twice inside one turn,
passed it.

  1. copy-gate-helper  copy_gate_refusal(turns): every turn against the turns
                       before it, and every sentence (8 words or more) of a
                       turn against the turns and sentences before it,
                       through system3.gate_check (its "copy" rule: word for
                       word, nearly word for word, 12 words in a row, or a
                       run that is most of the line). A four-word shingle
                       picks the pairs worth asking, so a shelf walk stays
                       cheap. No engine: refuses nothing.
  2. content-check     content_refusal asks it last (after the verdict, the
                       flags, the echo loop and the copied turns); memoised by
                       the round's words like the rest.
  3. restore           refusal(): a mark whose value carries "allow": true is
                       the operator's restore - the round goes back to the
                       roulette (the content rules are not asked). Every other
                       mark retires the round as before.

Retirement is recorded by the station (tools/reair_copy_gate_app_patch.py) as
a mark in data/reair_ineligible.json - the round itself is never touched, so
setting the mark's "allow" restores it.

--check exits 0 ready / 2 applied / 1 anchors missing; --apply idempotent,
atomic, LF.
TARGET: reair_gate.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("copy-gate-helper",
     'def _words_key(row: Any) -> tuple:\n',
     '''# [s3-reair-copy] the copy gate new rounds pass, asked of a stored round
COPY_GATE_UNIT_MIN = 8      # words: a sentence shorter than this is not weighed alone
RETIRE_HOOK = None          # the station's recorder: (mark keys, why), called once per refused round
COPY_GATE_SHINGLE = 4       # a pair is asked only when it shares a run of this many words
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\\s+")


def _shingles(words: list[str]) -> set:
    n = COPY_GATE_SHINGLE
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def copy_gate_refusal(turns: list[tuple[str, str]]) -> str:
    """Why the round fails System 3's copy gate (system3.gate_check), or "".
    Every turn is weighed against the turns before it, and every sentence of a
    turn against the turns and sentences before it - a sentence copied inside a
    longer turn, or said twice in one turn, is a copy as surely as a turn."""
    try:
        import system3                                  # the gate new rounds pass
        check, words_of = system3.gate_check, system3.gate_words
    except Exception:  # noqa: BLE001 - no engine, no verdict
        return ""
    units: list[tuple[str, str, set, int]] = []          # (label, text, shingles, turn)
    for i, (_who, text) in enumerate(turns):
        said = str(text or "")
        pieces = [s for s in _SENTENCE_SPLIT.split(said) if s.strip()]
        asked = [("turn %d" % (i + 1), said, True)]
        if len(pieces) > 1:
            asked += [("a sentence of turn %d" % (i + 1), s, False) for s in pieces]
        mine: list[tuple[str, str, set, int]] = []
        for label, piece, whole in asked:
            w = words_of(piece)
            if len(w) < COPY_GATE_UNIT_MIN:
                continue
            sh = _shingles(w)
            earlier = [(lab, txt) for lab, txt, osh, turn in units if sh & osh]
            if not whole:
                earlier += [(lab, txt) for lab, txt, osh, _t in mine if sh & osh]
            if earlier:
                got = check({}, None, piece, earlier=earlier, sources=[])
                if got and got.get("rule") == "copy":
                    return "the copy gate: %s %s" % (label, got.get("why") or "repeats an earlier line")
            if not whole:
                mine.append((label, piece, sh, i))
        units.extend(mine)
        w = words_of(said)
        if len(w) >= COPY_GATE_UNIT_MIN:
            units.append(("turn %d" % (i + 1), said, _shingles(w), i))
    return ""


def _words_key(row: Any) -> tuple:
''', 1),
    ("content-check",
     '''            why = "copied turns - %d of its %d turns copy an earlier turn (%s)" % (
                len(copies), len(turns),
                ", ".join("turn %d = turn %d" % (i + 1, j + 1) for i, j in copies[:4]))
''',
     '''            why = "copied turns - %d of its %d turns copy an earlier turn (%s)" % (
                len(copies), len(turns),
                ", ".join("turn %d = turn %d" % (i + 1, j + 1) for i, j in copies[:4]))
    if not why and turns:
        why = copy_gate_refusal(turns)                          # [s3-reair-copy]
        if why and callable(RETIRE_HOOK):                       # the station records the retirement
            try:
                RETIRE_HOOK(mark_keys(row), why)
            except Exception:  # noqa: BLE001
                pass
''', 1),
    ("restore",
     '''    got = mark_of(row, marks, cid)
    if got:
        why = got.get("why") if isinstance(got, dict) else got
''',
     '''    got = mark_of(row, marks, cid)
    if isinstance(got, dict) and got.get("allow"):
        return ""                        # [s3-reair-copy] the operator restored it: the roulette decides
    if got:
        why = got.get("why") if isinstance(got, dict) else got
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
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "reair_gate.py")
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
