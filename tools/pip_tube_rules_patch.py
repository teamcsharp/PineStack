#!/usr/bin/env python3
"""[pip-tube-rules] What the tube shows: every program picture, once per element, never a warm copy. 2026-10-06.

"I'm hearing the audio of videos but I'm not seeing the videos" and two copies of one clip on the
tube. The once-only rule of last night was too wide: the SFX guy cuts several stings from one
clip inside ten minutes, and each sting's picture is that clip again - legitimately - so the rule
hid the picture while the sound played. The rule is now only what the first complaint needed: a
video that LOOPS by its own attribute is never program. And the CRT set's warm copy of the next
clip (data-pine-warm, parked off screen) is never tiled, so a clip is one picture, not two.
Both copies of pine-pip.js.

Usage:  pip_tube_rules_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_tube_rules_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPEAT_OLD = r'''    function repeatOf(v) {
      if (v.loop) return 'loops';                                        /* a looping element is never program */
      const key = srcOf(v); if (!key || key === 'stream') return '';
      const seen = shownSrc.get(key);
      if (seen && seen.left && Date.now() - seen.left < SHOWN_ONCE_MS) return 'already shown';
      return '';
    }
'''
REPEAT_NEW = r'''    function repeatOf(v) {
      if (v.loop) return 'loops';                                        /* a looping element is never program */
      if (v.dataset && v.dataset.pineWarm === '1') return 'warm copy';   /* [pip-tube-rules] the set's next clip, warming off screen */
      if (v.classList && v.classList.contains('sp-mv-video')) return 'bubble copy';   /* the script page's thumbnail of the clip already on the tube; it replays itself while its line is newest */
      /* a source shown before is NOT a repeat: the SFX guy cuts several stings from one clip, and each
         sting's picture is that clip again, rightly - the ten-minute memory stays only as a record */
      return '';
    }
'''
ACTIVE_OLD = r'''      const it = tiles.get(video);
      if (!it && repeatOf(video)) return false;                           /* [pip-once] a source already shown is not tiled again */
      /* [pip-tube] a rewind counts only for the SAME source: the set's one element moves on to the next clip with its clock at zero */
      if (it && it.lastTime != null && it.srcKey === srcOf(video) && video.currentTime + 1 < it.lastTime && video.currentTime < 2) { it.rewound = true; }
      if (it && it.rewound) return false;
'''
ACTIVE_NEW = r'''      if (repeatOf(video)) return false;                                  /* [pip-tube-rules] a loop, a warm copy or a bubble copy is never program; a clock that jumps back is a player re-cueing its clip, which is */
'''
HEAD_OLD = r'''    /* [pip-once] every source the tube has shown: when, and whether it has left. A source that
       comes back inside SHOWN_ONCE_MS is a repeat and is not tiled; a jump back to the start is one too. */
'''
HEAD_NEW = r'''    /* [pip-once] every source the tube has shown: when, and whether it has left - kept as a record.
       [pip-tube-rules] it no longer refuses a source: the SFX guy cuts several stings from one clip, and each
       sting's picture is rightly that clip again (refusing it left the sound playing over an empty tube).
       What repeatOf() refuses: a `loop` element, the CRT set's warm copy of the next clip (data-pine-warm,
       parked in the tube at opacity 0) and the script page's bubble thumbnail (.sp-mv-video), which replays
       itself while its line is newest and is a second copy of the picture already on the tube. */
'''
PIPJS = [
    ("the record's header says what is refused", HEAD_OLD, HEAD_NEW, "[pip-tube-rules] it no longer refuses a source:", 1),
    ("a loop, a warm copy or a bubble copy is refused", REPEAT_OLD, REPEAT_NEW, "if (v.classList && v.classList.contains('sp-mv-video')) return 'bubble copy';", 1),
    ("a re-cue is not a loop", ACTIVE_OLD, ACTIVE_NEW, "/* [pip-tube-rules] a loop, a warm copy or a bubble copy is never program;", 1),
]
EDITS = {"desktop/renderer/pine-pip.js": PIPJS, "app/src/main/assets/pine-views/pine-pip.js": PIPJS}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            forms = [(old, new, probe)]
            if mode == "mixed":
                forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-46s %-48s %s" % (name[-46:], label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".piptuberules.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
