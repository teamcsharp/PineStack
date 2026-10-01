"""[dialogue-clock] only dialogue tells the station that dialogue happened.

2026-09-30, the operator: "right now, I'm still not hearing the DJs on the
station." Measured: the gallery segment ("Painting selling") took the air with
nothing prepared (225 bare arrivals); its fallback, banter, found no larder
round, and "live writing is refused while the reserve catches up". The
override for exactly that - dialogue_starved(): four minutes of no dialogue
and one live round is written anyway - never fired, because _DIALOGUE_AT was
reset by every line through dj_speak and every texted page clip: six stock
station IDs (the DJ, the co-host, the SFX Guy) in ten minutes kept the clock
"fresh" while real dialogue had stopped at 19:04:54. The guard became an off
switch.

A line resets the clock only when it is a person's dialogue: not a station ID,
the SFX Guy's drop, a board sting, a picture or song reading, a marker or a
chat note.

Usage (ON THE HOST): python3 tools/dialogue_clock_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[dialogue-clock]"

EDITS = [
    ("predicate",
     '''def dialogue_starved() -> tuple[bool, int]:
''',
     '''# [dialogue-clock] what may reset the quiet clock: a person's dialogue only
DIALOGUE_NOT_KINDS = frozenset({"station_id", "drop", "sfx", "sting", "sfxguy", "marker", "image_analysis",
                                "song_analysis", "chat", "record", "hangup"})
DIALOGUE_NOT_WHO = frozenset({"drop", "board", "analysis", "box", "deck", "outside", "sfxguy"})


def dialogue_counts(who: Any = "", kind: Any = "") -> bool:
    """[dialogue-clock] is this line dialogue - may it reset _DIALOGUE_AT?"""
    return (str(kind or "") not in DIALOGUE_NOT_KINDS
            and str(who or "") not in DIALOGUE_NOT_WHO)


def dialogue_starved() -> tuple[bool, int]:
'''),
    ("page clip",
     '''        if str(clip.get("text") or "").strip():
            _DIALOGUE_AT[0] = time.time()       # 2026-09-07: the page counts as air
''',
     '''        if str(clip.get("text") or "").strip() and dialogue_counts(clip.get("who"), clip.get("kind")):
            _DIALOGUE_AT[0] = time.time()       # 2026-09-07: the page counts as air [dialogue-clock]
'''),
    ("spoken line",
     '''    _RADIO["last_said"] = {**entry, "voice": forced or ""}
    _DIALOGUE_AT[0] = time.time()                                # 2026-09-07
''',
     '''    _RADIO["last_said"] = {**entry, "voice": forced or ""}
    if dialogue_counts(entry.get("who"), entry.get("kind")):          # [dialogue-clock]
        _DIALOGUE_AT[0] = time.time()                                # 2026-09-07
'''),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-dialogue-clock")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
