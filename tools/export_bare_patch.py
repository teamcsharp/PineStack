#!/usr/bin/env python3
"""[export-bare] "Export the broadcast" means the audio; "export the <device> broadcast" means that screen. 2026-10-06.

"If I say export the broadcast then I mean audio and if I say export the audio, I also
mean audio. If I say export <device/app> broadcast, I mean the video of the screen
recording."

Measured through the live grammar (parse_export_command): every order that names a
window already lands right - "export the last 5 minutes of the broadcast" -> 300 s of
talk audio, "... of the pine pip broadcast" -> the PiP's screen - but the bare orders
the operator actually says return None: "export the broadcast", "export the audio",
"export the pine tab broadcast". The dispatcher asks parse_export_command before
parse_broadcast_command (app.py ~125516), so an export never becomes a re-route.

Now a bare order with no window named takes EXPORT_BARE_SECONDS (300, env
PINE_EXPORT_BARE_SECONDS): broadcast / audio / radio / show / tape / recording ->
{"seconds": 300, "kind": "talk"}; "<device> broadcast" (pine tab, pine app, pine pip,
pine lens, the cam - export_screen_target's own words) -> {"seconds": 300, "screen":
<that>}. The #1154 residue rule still holds: the order is the sentence.

Usage:  export_bare_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        export_bare_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

DEF_OLD = '''def parse_export_command(text: str) -> dict[str, Any] | None:
'''
DEF_NEW = '''EXPORT_BARE_SECONDS = int(os.getenv("PINE_EXPORT_BARE_SECONDS", "300"))   # [export-bare] "export the broadcast", no window named


def parse_export_command(text: str) -> dict[str, Any] | None:
'''

BARE_OLD = '''        if this:
            residue = lowered[:this.start()] + " " + lowered[this.end():]
            residue = re.sub(r"[^a-z ]+", " ", residue)
            if len([w for w in residue.split()
                    if w not in _EXPORT_FILLER]) <= 3:
                return {"sentences": 6}
        return None
'''
BARE_NEW = '''        if this:
            residue = lowered[:this.start()] + " " + lowered[this.end():]
            residue = re.sub(r"[^a-z ]+", " ", residue)
            if len([w for w in residue.split()
                    if w not in _EXPORT_FILLER]) <= 3:
                return {"sentences": 6}
        # [export-bare] "export the broadcast", "export the audio", "export the pine tab broadcast":
        # no window named. The operator's own meaning - broadcast or audio is the AUDIO of the last
        # EXPORT_BARE_SECONDS; "<device> broadcast" is that screen's recording of the same span.
        bare = re.search(
            _EXPORT_VERB_RX + r"\\s+(?:the\\s+|my\\s+|this\\s+|tonight'?s\\s+|today'?s\\s+)?"
            r"(?:(?P<device>[a-z][a-z\\s-]{0,18}?)\\s+)?"
            r"(?P<subject>broadcast|audio|radio|show|tape|recording|programme|program|"
            r"rhetoric|dialogue|dialog)\\b", lowered)
        if bare:
            residue = lowered[:bare.start()] + " " + lowered[bare.end():]
            residue = re.sub(r"[^a-z ]+", " ", residue)
            if len([w for w in residue.split()
                    if w not in _EXPORT_FILLER]) <= 3:
                device = str(bare.group("device") or "").strip()
                screen = export_screen_target("of " + device + " " + bare.group("subject")) if device else ""
                if screen:
                    return {"seconds": EXPORT_BARE_SECONDS, "screen": screen}
                if not device or device in ("whole", "full", "entire", "live", "current"):
                    return {"seconds": EXPORT_BARE_SECONDS, "kind": "talk"}
        return None
'''

EDITS = {
    "app.py": [
        ("the bare span", DEF_OLD, DEF_NEW, 1),
        ("a bare order takes the default span and the named screen", BARE_OLD, BARE_NEW, 1),
    ],
}


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
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".exportbare.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
