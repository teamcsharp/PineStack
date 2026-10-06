#!/usr/bin/env python3
"""[cam-why] The Pine Cam popup says why, and keeps saying it while it waits. 2026-10-05, #1582.

The operator's screenshot: "Pine Cam recovery is waiting before retrying." The
camera's own Wi-Fi network was not on the air (the station's doctor: "the
radio is fine - it can see 11 other network(s) - so the camera is out of range
or asleep"), which nothing on the station can cure - the camera's Wi-Fi button
has to be pressed. The popup did say "Camera not detected" once, and three
seconds later its next tick replaced that with the waiting line, which is what
stayed on the glass for the other forty-two seconds of every cycle.

What this changes in desktop/renderer/pine-pip-camera-recovery.js:
  - when there is nothing to reconnect to, the popup gives the station's own
    reading: the camera's network (by name) is not on the air, and what to do;
  - while it waits for the next look, that reason stays up with the seconds
    left, instead of "recovery is waiting before retrying".

Usage:  cam_why_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        cam_why_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

TARGET = "desktop/renderer/pine-pip-camera-recovery.js"

EDITS = [
    ("the reason is kept",
     "    let status={phase:'idle',say:'',attempts:0};\n",
     "    let status={phase:'idle',say:'',attempts:0};\n"
     "    let reason='';   // [cam-why] why there is nothing to reconnect to, kept while the next look waits\n"
     "    function sentence(text){const t=String(text||'').trim();if(!t)return '';const s=t[0].toUpperCase()+t.slice(1);return /[.!?]$/.test(s)?s:s+'.';}\n"
     "    function why(got,doctor,tablet){\n"
     "      if(tablet)return 'Waiting for the PineTab camera link. Check camera power and Wi-Fi.';\n"
     "      if(doctor&&!doctor.stale&&doctor.camera===false){\n"
     "        const name=got&&got.ssid?' ('+got.ssid+')':'';\n"
     "        return 'The camera\\'s Wi-Fi'+name+' is not on the air: the camera is asleep, switched off or out of range. Press its Wi-Fi button and wait for the solid green light.';\n"
     "      }\n"
     "      return sentence(got&&got.why)||'Camera not detected. Check camera power and Wi-Fi.';\n"
     "    }\n",
     "// [cam-why] why there is nothing to reconnect to"),
    ("cancel forgets it",
     "    function cancel(){epoch++;faultSince=null;lastReading=null;lastSource='';return report('idle','');}\n",
     "    function cancel(){epoch++;faultSince=null;lastReading=null;lastSource='';reason='';return report('idle','');}\n",
     "lastSource='';reason='';return report('idle','');"),
    ("a live picture forgets it",
     "          faultSince=null;attempts=0;report('live','Live Pine Cam picture restored.');\n",
     "          faultSince=null;attempts=0;reason='';report('live','Live Pine Cam picture restored.');\n",
     "attempts=0;reason='';report('live'"),
    ("the wait keeps the reason",
     "          report('waiting','Pine Cam recovery is waiting before retrying.'+hint);\n",
     "          // [cam-why] the reason stays on the glass while it waits, with the seconds left\n"
     "          report('waiting',reason?reason+' Checking again in '+Math.max(1,Math.ceil((nextTry-now())/1000))+' s.'+hint:'Pine Cam recovery is waiting before retrying.'+hint);\n",
     "// [cam-why] the reason stays on the glass while it waits"),
    ("the doctor is remembered",
     "          const doctor=await deps.doctor();\n",
     "          const doctor=await deps.doctor();\n"
     "          seen=doctor;\n",
     "          seen=doctor;\n"),
    ("a place to remember it",
     "        let route='';\n",
     "        let route='',seen=null;\n",
     "let route='',seen=null;"),
    ("nothing to reconnect to says why",
     "          const say=tablet?'Waiting for the PineTab camera link. Check camera power and Wi-Fi.':'Camera not detected. Check camera power and Wi-Fi.';\n"
     "          report('attention',say);return {ok:false,say};\n",
     "          const say=why(got,seen,tablet);   // [cam-why] the station's own reading, not a shrug\n"
     "          reason=say;report('attention',say);return {ok:false,say};\n",
     "// [cam-why] the station's own reading, not a shrug"),
]


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    path = root / TARGET
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
    # This file's line endings are mixed (CRLF and LF), so nothing is normalised:
    # each edit is matched in whichever ending its own lines carry, and written
    # back in that ending. Every other byte of the file is left as it was.
    todo, missing = [], False
    for name, old, new, probe in EDITS:
        variants = [(old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")),
                    (old, new, probe)]
        done = any(p in text for _o, _n, p in variants)
        fit = next(((o, n, p) for o, n, p in variants if text.count(o) == 1), None)
        state = "applied" if done else "ready" if fit else "missing (anchor found %d)" % text.count(old)
        print("%-34s %s" % (name, state))
        if state == "ready":
            todo.append(fit)
        elif state != "applied":
            missing = True
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not todo:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for old, new, probe in todo:
        assert text.count(old) == 1
        text = text.replace(old, new)
        assert probe in text
    tmp = path.with_name(path.name + ".camwhy.tmp")
    tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    os.replace(tmp, path)
    print("wrote %s (%d edit(s), line endings as found%s)" % (path.name, len(todo), ", BOM kept" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
