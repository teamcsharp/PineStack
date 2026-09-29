"""[contd-mark] The screenplay says (CONT'D) when one turn is cut by a sting.

The disease (2026-09-28 15:51, hour-18 "Message from upstairs", sid
dcef8ca292f3): ONE airing turn of conversation 04cbacf906fa4445 - "Told my
friend stick it up his fucking head! ... The box men are watching the
dealers ..." - went out as two ledger rows with a sting between them
(block 35646, ord 0 / 1 / 2). screenplay_compose() re-slugs a speaker after
every action, so the page printed

    DILL / Told my friend ... / A sting off the board ... / DILL / The box men ...

- a bare second DILL that reads as a new turn. The operator could not tell a
split from a second turn by the same voice.

Now the re-slug after a sting reads "DILL (CONT'D)" when the line continues
the SAME turn as the dialogue before the sting, and the element carries it
for every surface (`contd: true`, `cont_of: <the line it continues>`); the
page, the markdown, the text and the PDF all print the element's text.
Same turn means:
  - both lines carry a System 3 turn stamp in the script ledger
    (system3.turn_id) and the two are equal - a different turn by the same
    voice (an expansion) is NOT marked; or
  - either line has no stamp: both sit in the same scripted ledger block
    (the screenplay convention: the same character resumes after the
    interruption inside one written exchange).
Never across a scene, a cut-in, another character, or a pause longer than
SCREENPLAY_GAP_BLOCK.

The stamp map rides the ledger order the page already builds
(script_ledger_order(), memoised rows - no new disk read).

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. Usage: python contd_mark_patch.py [--apply] [app.py]
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ("stamp-map-local",
     '    by_round_text: dict[tuple[str, str], tuple[int, int, bool]] = {}\n',
     '    by_round_text: dict[tuple[str, str], tuple[int, int, bool]] = {}\n'
     '    s3_turn: dict[str, str] = {}             # [contd-mark] line -> its System 3 turn\n',
     1),
    ("stamp-map-fill",
     '        if sid and r.get("kind") == "sfx":\n',
     '        _s3m = r.get("system3")                  # [contd-mark]\n'
     '        if lid and isinstance(_s3m, dict) and _s3m.get("turn_id"):\n'
     '            s3_turn[lid] = str(_s3m.get("turn_id"))\n'
     '        if sid and r.get("kind") == "sfx":\n',
     1),
    ("stamp-map-publish",
     '    _LEDGER_ROUND_TEXT.clear()\n',
     '    _LEDGER_S3_TURN.clear()                   # [contd-mark]\n'
     '    _LEDGER_S3_TURN.update(s3_turn)\n'
     '    _LEDGER_ROUND_TEXT.clear()\n',
     1),
    ("stamp-map-global",
     '_LEDGER_ROUND_TEXT: dict[tuple[str, str], tuple[int, int, bool]] = {}\n',
     '_LEDGER_ROUND_TEXT: dict[tuple[str, str], tuple[int, int, bool]] = {}\n'
     '# [contd-mark] line_id -> the System 3 turn stamped on it in the script\n'
     '# ledger (system3.turn_id), rebuilt with every script_ledger_order().\n'
     '_LEDGER_S3_TURN: dict[str, str] = {}\n',
     1),
    ("contd-helper",
     'def screenplay_compose(since: float, until: float, d: dict[str, Any],\n',
     '''def screenplay_contd(elements: list[dict[str, Any]], line_id: str,
                     name: str, pos: Any, cut_in: bool, gap: float) -> str:
    """[contd-mark] The line this one CONTINUES when its speaker is being
    named again only because a sting (an action) came between - one turn
    cut in pieces - else "". The character cue then reads NAME (CONT'D).

    Same turn: both lines' System 3 turn stamps (script ledger
    system3.turn_id) are equal; with a stamp missing on either, both sit in
    the same scripted ledger block. Never across a scene, another
    character, a cut-in or a long pause."""
    try:
        if cut_in or (gap and gap > SCREENPLAY_GAP_BLOCK):
            return ""
        if not elements or elements[-1].get("type") != "action":
            return ""
        prev = None
        for e in reversed(elements):
            kind = e.get("type")
            if kind == "dialogue":
                prev = e
                break
            if kind in ("action", "parenthetical", "note"):
                continue
            return ""
        if not prev or str(prev.get("name") or "") != str(name or ""):
            return ""
        a, b = str(prev.get("line") or ""), str(line_id or "")
        if not a or not b:
            return ""
        ta, tb = _LEDGER_S3_TURN.get(a, ""), _LEDGER_S3_TURN.get(b, "")
        if ta and tb:
            return a if ta == tb else ""
        order = pos if isinstance(pos, dict) else {}
        pa, pb = order.get(a), order.get(b)
        if (pa and pb and int(pa[0]) == int(pb[0])
                and (len(pa) < 3 or pa[2]) and (len(pb) < 3 or pb[2])):
            return a
    except Exception:  # noqa: BLE001 - a cue is never worth the script
        return ""
    return ""


def screenplay_compose(since: float, until: float, d: dict[str, Any],
''',
     1),
    ("contd-cue",
     '            push("character", name.upper(), f"ch-{line_id}", at=at,\n',
     '            _contd = screenplay_contd(elements, line_id, name,   # [contd-mark]\n'
     '                                      _script_pos, cut_in, gap)\n'
     '            push("character", name.upper() + (" (CONT\'D)" if _contd else ""),\n'
     '                 f"ch-{line_id}", at=at,\n'
     '                 **({"contd": True, "cont_of": _contd} if _contd else {}),\n',
     1),
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
