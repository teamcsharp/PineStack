#!/usr/bin/env python3
"""[lone-line-now] A LINE THAT PLAYS ON ITS OWN GIVES THE SCRIPT VIEW ITS PLACE.

TARGET: app.py

Measured 09-29 by tools/script_watch.py: the manager's memo 5457ba26 was HEARD
(heard_ack_by page, 09:54:38) and for the 20 s it played /api/dj said
stream_now = null and speaking_now = null. The Script view places its ON AIR
mark from stream_now (PineStationFeed interpolates `now` from it), so the view
stood still while the memo played. 6 of 143 heard lines in the first 25 min
never had a position at all (the memo 1 of 1, an interject, an advert, stings).

Cause: page_playback_ack publishes stream_now only for a clip with a
`stream.rows` timeline (a coalesced round). A single-media line - the memo,
a lone interject or advert, a sting - carries `line` instead and only takes
the heard receipt (_sting_heard). Nothing told the view where the air was.

Now a lone line's audible "playing" ack publishes a one-row stream_now for it
(start = now - position, length from the clip / ack / ring row, else the words
at 14 chars a second), unless a round's timeline is still sounding - a sting
laid under a round never takes the round's place. Its "ended" ack clears it.

    python3 sw_lone_line_now_patch.py --check [ROOT]   0 ready, 2 applied, 1 missing
    python3 sw_lone_line_now_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

TARGET = "app.py"
MARKER = "[lone-line-now]"
NL = chr(10)

HELPERS = '''def _lone_line_now(line_id: str, clip: dict[str, Any], started: float,
                   body: Any = None) -> bool:
    """[lone-line-now] A single-media line (a memo, a lone interject or advert,
    a sting) is audibly playing: publish it as a one-row stream_now so the
    Script view's ON AIR mark has a place. Never over a round's timeline that
    is still sounding. True when published."""
    if not line_id:
        return False
    now = time.time()
    held = _STREAM_NOW.get("rows") or []
    if held and _STREAM_NOW.get("lone") != line_id and now < (
            float(_STREAM_NOW.get("at") or 0) + float(_STREAM_NOW.get("length") or 0)):
        return False
    row = next((r for r in reversed(_RADIO.get("chat") or [])
                if str(r.get("id") or "") == line_id), None)
    if not isinstance(row, dict):
        return False
    secs = 0.0
    for got in ((clip or {}).get("seconds"), (clip or {}).get("duration"),
                (body or {}).get("duration") if isinstance(body, dict) else None,
                row.get("seconds")):
        try:
            secs = float(got or 0)
        except (TypeError, ValueError):
            secs = 0.0
        if secs > 0:
            break
    if secs <= 0:
        secs = max(2.0, len(str(row.get("text") or "")) / 14.0)
    _stream_now_set([{"id": line_id, "from": 0.0, "until": secs,
                      "text": str(row.get("text") or ""), "who": str(row.get("who") or ""),
                      "name": str(row.get("name") or ""), "kind": str(row.get("kind") or ""),
                      "voice": str(row.get("voice") or ""), "aired": "airing"}],
                    secs, stamp=False)
    _STREAM_NOW["at"] = float(started or now)
    _STREAM_NOW["lone"] = line_id
    return True


def _lone_line_end(line_id: str) -> None:
    """[lone-line-now] its player said ended: the place it held is given back."""
    if line_id and _STREAM_NOW.get("lone") == line_id:
        _stream_now_clear()


def page_playback_ack(payload: Any, addr: str = "",'''

EDITS = [
    ("helpers", 'def page_playback_ack(payload: Any, addr: str = "",', HELPERS),
    ("playing",
     '                _sting_heard(str(clip.get("line")), delivery_id, now - position)' + NL
     + '            except Exception:  # noqa: BLE001' + NL
     + '                pass' + NL,
     '                _sting_heard(str(clip.get("line")), delivery_id, now - position)' + NL
     + '            except Exception:  # noqa: BLE001' + NL
     + '                pass' + NL
     + '            if event == "playing":                       # [lone-line-now]' + NL
     + '                try:' + NL
     + '                    _lone_line_now(str(clip.get("line")), clip, now - position, body)' + NL
     + '                except Exception:  # noqa: BLE001' + NL
     + '                    pass' + NL),
    ("ended",
     '    if event == "ended":' + NL + '        delivery["state"] = ("playing" if any(' + NL,
     '    if event == "ended":' + NL
     + '        try:                                             # [lone-line-now]' + NL
     + '            _lone_line_end(str((delivery.get("clip") or {}).get("line") or ""))' + NL
     + '        except Exception:  # noqa: BLE001' + NL
     + '            pass' + NL
     + '        delivery["state"] = ("playing" if any(' + NL),
]


def load(root: Path):
    path = root / TARGET
    raw = path.read_bytes().decode("utf-8")
    return path, raw.replace("\r\n", NL), "\r\n" in raw


def check(root: Path):
    try:
        _p, text, _c = load(root)
    except OSError as exc:
        return 1, ["cannot read %s: %s" % (TARGET, exc)]
    if MARKER in text:
        return 2, ["already applied"]
    bad = ["anchor %s: found %d" % (n, text.count(a)) for n, a, _ in EDITS if text.count(a) != 1]
    return (1, bad) if bad else (0, [])


def apply(root: Path) -> int:
    code, _why = check(root)
    if code != 0:
        return code
    path, text, crlf = load(root)
    for _n, anchor, new in EDITS:
        text = text.replace(anchor, new, 1)
    if crlf:
        text = text.replace(NL, "\r\n")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".lone_line.")
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print("usage: %s --check|--apply [ROOT]" % argv[0])
        return 1
    root = Path(argv[2] if len(argv) > 2 else ".").resolve()
    if argv[1] == "--check":
        code, why = check(root)
        print({0: "READY", 2: "APPLIED", 1: "MISSING"}[code], "; ".join(why))
        return code
    code = apply(root)
    print({0: "APPLIED", 2: "ALREADY APPLIED"}.get(code, "NOT APPLIED: " + "; ".join(check(root)[1])))
    return 0 if code in (0, 2) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
