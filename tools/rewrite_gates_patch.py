"""The station's rewrite passes read System 3's TINT / REPAIR / ROOM rolls
([s3-rewrite], app.py side; the rolls are tools/system3_rewrite_rolls_patch.py).

  crystal_tint(only_turns=...)   the per-turn path tints the turns given and
                                 no others - System 3's rhyme dice - instead
                                 of "the first N eligible" for its coverage.
                                 Without the argument nothing changes.
  dj_banter's tint call          passes system3_tint_turns(_s3, script) on a
  (and its lesson retry)         System 3 round; None otherwise.
  ensure_entry_tinted            the larder / retint / recovery passes read
                                 the selection bound onto the entry.
  speak_turns' recording tint    the same selection off turn_dice[i].s3.tint.
  the richness rewrite           on a System 3 round the REPAIR roll decides:
                                 a round that rolled "stands" is not sent
                                 back whatever the checks say; one that rolled
                                 "goes back" is not cancelled by the review
                                 gate (which, with the content gates off,
                                 cancelled every repair - measured 2026-09-27).
  the Writers' Room              both tickets (structural, editorial) skip a
                                 round whose bound ROOM roll said no.

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes
app.py (LF, byte IO). ON THE HOST, from a fresh copy.
"""
import sys
from pathlib import Path

EDITS = [
    # crystal_tint: the argument
    ('async def crystal_tint(script: str, kind: str = "",\n'
     '                       verbatim: Any = None,\n'
     '                       whole_only: bool = False,\n'
     '                       progress: Any = None,\n'
     '                       critical: bool = False,\n'
     '                       lesson: str = "") -> dict[str, Any]:\n',
     'async def crystal_tint(script: str, kind: str = "",\n'
     '                       verbatim: Any = None,\n'
     '                       whole_only: bool = False,\n'
     '                       progress: Any = None,\n'
     '                       critical: bool = False,\n'
     '                       lesson: str = "",\n'
     '                       only_turns: Any = None) -> dict[str, Any]:   # [s3-rewrite]\n'),
    # crystal_tint: the selection
    ('        required = ((len(eligible_ix) * coverage_target + 99) // 100\n'
     '                    if eligible_ix and coverage_target else 0)\n'
     '        # Coverage is exact and deterministic for a given script. Strength\n'
     '        # never gets to make this decision. At 100 every eligible line is in.\n'
     '        selected_ix = set(eligible_ix if coverage_target >= 100\n'
     '                          else eligible_ix[:required])\n'
     '        out["coverage"] = {\n'
     '            "target": coverage_target, "eligible": len(eligible_ix),\n',
     '        required = ((len(eligible_ix) * coverage_target + 99) // 100\n'
     '                    if eligible_ix and coverage_target else 0)\n'
     '        # Coverage is exact and deterministic for a given script. Strength\n'
     '        # never gets to make this decision. At 100 every eligible line is in.\n'
     '        selected_ix = set(eligible_ix if coverage_target >= 100\n'
     '                          else eligible_ix[:required])\n'
     '        if only_turns is not None:\n'
     '            # [s3-rewrite] SYSTEM 3\'S RHYME DICE CHOOSE THE LINES. "the first N\n'
     '            # eligible" was the station\'s own selection; a System 3 round\n'
     '            # rolled TINT on every turn, and the turns that rolled it are the\n'
     '            # selection - all of them, however many, and no other.\n'
     '            _only = {int(i) for i in only_turns}\n'
     '            selected_ix = {i for i in eligible_ix if i in _only}\n'
     '            required = len(selected_ix)\n'
     '        out["coverage"] = {\n'
     '            "target": coverage_target, "eligible": len(eligible_ix),\n'
     '            **({"system3": sorted(selected_ix)} if only_turns is not None else {}),\n'),
    # dj_banter: the tint call and its lesson retry
    ('                                       whole_only=False,\n'
     '                                       critical=bool(bank)),\n',
     '                                       whole_only=False,\n'
     '                                       critical=bool(bank),\n'
     '                                       # [s3-rewrite] the lines System 3 rolled a rhyme on\n'
     '                                       only_turns=(globals()["system3_tint_turns"](_s3, script)\n'
     '                                                   if globals().get("system3_tint_turns") else None)),\n'),
    ('                    critical=bool(bank), lesson=_lesson),\n',
     '                    critical=bool(bank), lesson=_lesson,\n'
     '                    only_turns=(globals()["system3_tint_turns"](_s3, script)     # [s3-rewrite]\n'
     '                                if globals().get("system3_tint_turns") else None)),\n'),
    # the passes after the bind read the entry
    ('                critical=critical,\n'
     '                # #1146: a struck attempt\'s graded faults ride the retry.\n'
     '                lesson=str(entry.get("tint_lesson") or "")),\n',
     '                critical=critical,\n'
     '                # #1146: a struck attempt\'s graded faults ride the retry.\n'
     '                lesson=str(entry.get("tint_lesson") or ""),\n'
     '                # [s3-rewrite] the selection System 3 bound onto this entry\n'
     '                only_turns=(globals()["system3_tint_turns_entry"](entry)\n'
     '                            if globals().get("system3_tint_turns_entry") else None)),\n'),
    # speak_turns: the recording tint
    ('    tint_selected = (set(tint_eligible[:tint_required])\n'
     '                     if tint_needed and not recorded else set())\n',
     '    tint_selected = (set(tint_eligible[:tint_required])\n'
     '                     if tint_needed and not recorded else set())\n'
     '    # [s3-rewrite] a System 3 round carries its rhyme dice on turn_dice:\n'
     '    # the turns that rolled it are the selection, no other\n'
     '    try:\n'
     '        _s3_tint = {int(k): bool((((d or {}).get("s3") or {}).get("tint") or {}).get("rhyme"))\n'
     '                    for k, d in (turn_dice or {}).items()\n'
     '                    if ((((d or {}).get("s3") or {}).get("tint") or {}).get("rhyme")) is not None}\n'
     '    except Exception:  # noqa: BLE001\n'
     '        _s3_tint = {}\n'
     '    if _s3_tint and tint_needed and not recorded:\n'
     '        tint_selected = {i for i in tint_eligible if _s3_tint.get(i)}\n'),
    # the richness rewrite: the REPAIR roll decides on a System 3 round
    ('    if (not _needs_rewrite and not caller_name\n'
     '            and globals().get("system3_repair_wanted")\n'
     '            and globals()["system3_repair_wanted"](_s3, script)):\n'
     '        _needs_rewrite = True\n',
     '    if (not _needs_rewrite and not caller_name\n'
     '            and globals().get("system3_repair_wanted")\n'
     '            and globals()["system3_repair_wanted"](_s3, script)):\n'
     '        _needs_rewrite = True\n'
     '    # [s3-rewrite] ON A SYSTEM 3 ROUND THE REPAIR ROLL DECIDES. True: a round\n'
     '    # that missed goes back, and the review gate below does not cancel it\n'
     '    # (with the content gates off it cancelled every repair). False: it\n'
     '    # stands as written, whatever the checks found. None: the old rules.\n'
     '    _s3_repair = (globals()["system3_repair_roll"](_s3) if globals().get("system3_repair_roll") else None)\n'
     '    if _needs_rewrite and _s3_repair is False:\n'
     '        pipeline_log("system3", "the round missed its target, and its REPAIR roll said it stands "\n'
     '                                "as written - no rewrite")\n'
     '        _needs_rewrite = False\n'),
    ('    if _needs_rewrite and _radio_draft_review(_draft_entry,\n'
     '            _call_report or {"ok": False, "faults": ["the draft missed its conversational richness target"]},\n'
     '            "draft_rewrite", record=True):\n'
     '        _needs_rewrite = False\n',
     '    if _needs_rewrite and _s3_repair is not True and _radio_draft_review(_draft_entry,   # [s3-rewrite]\n'
     '            _call_report or {"ok": False, "faults": ["the draft missed its conversational richness target"]},\n'
     '            "draft_rewrite", record=True):\n'
     '        _needs_rewrite = False\n'),
    # the Writers' Room: both tickets ask the ROOM roll first
    ('            or not dialogue_row_ready(road, row)):\n'
     '        return None\n'
     '    return slot, row\n',
     '            or not dialogue_row_ready(road, row)):\n'
     '        return None\n'
     '    # [s3-rewrite] a round whose ROOM roll said no is left alone\n'
     '    if globals().get("system3_room_allowed") and not globals()["system3_room_allowed"](dialogue_entry(row)):\n'
     '        pipeline_log("system3", "the Writers\' Room left a %s round alone - its ROOM roll said no" % road)\n'
     '        return None\n'
     '    return slot, row\n'),
    ('                row = live[1]\n'
     '                repair = row.get("director_repair") or {}\n',
     '                row = live[1]\n'
     '                # [s3-rewrite] a round whose ROOM roll said no is left alone\n'
     '                if globals().get("system3_room_allowed") and not globals()["system3_room_allowed"](dialogue_entry(row)):\n'
     '                    continue\n'
     '                repair = row.get("director_repair") or {}\n'),
]


def main(argv):
    apply = "--apply" in argv
    path = Path("app.py")
    text = path.read_bytes().decode("utf-8")
    assert "\r\n" not in text[:100000], "app.py is CRLF - stop"
    todo = 0
    for old, new in EDITS:
        if new in text:
            continue
        if text.count(old) != 1:
            print("MISSING (%d): %r" % (text.count(old), old[:90]))
            return 1
        text = text.replace(old, new)
        todo += 1
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    path.write_bytes(text.encode("utf-8"))
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
