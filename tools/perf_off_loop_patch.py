#!/usr/bin/env python3
"""[perf-off-loop] [cut-anyway] Two faults found verifying the afternoon's work. 2026-10-05.

1. larder_prepare looked up each line's feeling on the event loop
   (system3_perf_voice / system3_perf_state: match the line to its turn, and
   read the conversation out of System 3's store when it is not in memory).
   For a round written days ago - the rounds the pen is now releasing - that
   read is cold. Measured: one call held the loop 24.7 s (app.py larder_prepare
   <- recording_sitting <- pantry_keeper); the host watchdog's limit is 8 s.
   Both lookups now run on a worker thread, as the runtime's own reads do.

2. The supercut's accuracy dial never reached the renderer: sfx_supercut.config()
   rebuilds the plan's `custom` block from three named keys and dropped the
   fourth, so the renderer read 100 and refused both retried jobs ("Every
   custom word cut needs verified trimmed source audio") although all sixteen
   words had been found. The dial rides the plan now. A retry also counts its
   matched words from nothing (it read "19 of 16").

Usage:  perf_off_loop_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        perf_off_loop_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PERF_OLD = r'''            fx = dict(voice_effect_pick())
            if vec_for := performance_vector(                  # [#1232]
                    who, voice,
                    es=(globals()["system3_perf_voice"](entry, None, text, who)   # [s3-es-voice]
                        if globals().get("system3_perf_voice") else None),
                    state=((globals()["system3_perf_state"](entry, None, text, who)
                            if globals().get("system3_perf_state") else None)
                           or weather_state_for(entry.get("weather"), who))):
                fx["perf"] = vec_for
            strip = str(dj.get(f"strip_{who}") or "")
'''
PERF_NEW = r'''            fx = dict(voice_effect_pick())
            # [perf-off-loop] THE LINE'S FEELING IS LOOKED UP OFF THE EVENT LOOP. Both
            # calls match the line to its turn and read the conversation out of
            # System 3's store when it is not in memory; for a round written days
            # ago that read is cold, and one held the loop 24.7 s here on
            # 2026-10-05 (the host watchdog's limit is 8).
            _pv, _ps = globals().get("system3_perf_voice"), globals().get("system3_perf_state")
            _es_voice = (await asyncio.to_thread(_pv, entry, None, text, who)) if _pv else None   # [s3-es-voice]
            _es_state = (await asyncio.to_thread(_ps, entry, None, text, who)) if _ps else None
            if vec_for := performance_vector(                  # [#1232]
                    who, voice, es=_es_voice,
                    state=(_es_state or weather_state_for(entry.get("weather"), who))):
                fx["perf"] = vec_for
            strip = str(dj.get(f"strip_{who}") or "")
'''

CONFIG_OLD = r'''            'max_seconds': max(.06, min(120., _number(custom.get('max_seconds'), 60.)))}
'''
CONFIG_NEW = r'''            'max_seconds': max(.06, min(120., _number(custom.get('max_seconds'), 60.))),
            'accuracy': max(0., min(100., _number(custom.get('accuracy'), 100.)))}   # [cut-anyway] the dial rides the plan
'''

RETRY_OLD = r'''            retry_at=0.,cursor=0,cuts=[],attempted=[],missing_words=[],missing_phrases=[])
'''
RETRY_NEW = r'''            retry_at=0.,cursor=0,cuts=[],attempted=[],missing_words=[],missing_phrases=[],
            matched_words=0,unverified_words=0)   # [cut-anyway] a retry counts from nothing
'''

EDITS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "app.py": [("the feeling is looked up off the loop", PERF_OLD, PERF_NEW,
                "# [perf-off-loop] THE LINE'S FEELING IS LOOKED UP OFF THE EVENT LOOP", 1)],
    "sfx_supercut.py": [("the dial rides the plan", CONFIG_OLD, CONFIG_NEW,
                         "# [cut-anyway] the dial rides the plan", 1)],
    "sfx_supercut_custom.py": [("a retry counts from nothing", RETRY_OLD, RETRY_NEW,
                                "# [cut-anyway] a retry counts from nothing", 1)],
}


def _read(path: Path) -> tuple[str, bool]:
    text = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    return text, crlf


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            _n, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-24s %-38s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for _n, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _n)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _n, "probe")
        if todo:
            tmp = path.with_name(path.name + ".perfloop.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
