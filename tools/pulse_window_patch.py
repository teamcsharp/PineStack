"""/api/pulse answers for a window of time, not only "the last N seconds".

The tapped line's Timing pane ([s3-timing], frontend/system3.js) shows what
the event loop was doing WHILE a line was made - from its plan to its air,
which can be an hour ago for a banked round. pulse_report() only knew "the
last `window` seconds", so the pane could only show the last ten minutes,
whatever the line. `since`/`until` (epoch seconds) select the stalls and
frames inside that span instead; without them the report is exactly as it
was. The ring keeps the last PULSE_KEEP (120) stalls, so an old window can
be empty for that reason, and the report says so (`ring_from`).

Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes app.py. ON THE HOST.
"""
import sys
from pathlib import Path

EDITS = [
    ('def pulse_report(window: float = 600.0) -> dict[str, Any]:\n'
     '    """What the loop has been stuck in lately, worst first. `ok` is\n'
     '    false once a stall reached the host watchdog\'s own probe timeout."""\n'
     '    now = time.time()\n'
     '    with _PULSE_LOCK:\n'
     '        recent = [r for r in (_PULSE.get("stalls") or [])\n'
     '                  if now - float(r.get("at") or 0) <= window]\n'
     '        by = {k: dict(v) for k, v in (_PULSE.get("by_frame") or {}).items()}\n',
     'def pulse_report(window: float = 600.0, since: float | None = None,\n'
     '                 until: float | None = None) -> dict[str, Any]:\n'
     '    """What the loop has been stuck in lately, worst first. `ok` is\n'
     '    false once a stall reached the host watchdog\'s own probe timeout.\n'
     '\n'
     '    [s3-timing] `since`/`until` (epoch seconds) answer for that span of\n'
     '    time instead of the last `window` seconds - the Timing pane asks for\n'
     '    the span a line was made in. The ring holds PULSE_KEEP stalls, so\n'
     '    `ring_from` says how far back it can see."""\n'
     '    now = time.time()\n'
     '    with _PULSE_LOCK:\n'
     '        ring = list(_PULSE.get("stalls") or [])\n'
     '        by = {k: dict(v) for k, v in (_PULSE.get("by_frame") or {}).items()}\n'
     '    spanned = since is not None or until is not None\n'
     '    lo, hi = 0.0, now\n'
     '    if spanned:\n'
     '        lo = float(since) if since is not None else 0.0\n'
     '        hi = float(until) if until is not None else now\n'
     '        window = max(1.0, hi - lo)\n'
     '        recent = [r for r in ring if lo <= float(r.get("at") or 0) <= hi]\n'
     '    else:\n'
     '        recent = [r for r in ring if now - float(r.get("at") or 0) <= window]\n'
     '    ring_from = min((float(r.get("at") or 0) for r in ring), default=0.0)\n'),
    ('    top = sorted(((k, v) for k, v in by.items()\n'
     '                  if now - float(v.get("at") or 0) <= window),\n'
     '                 key=lambda kv: -float(kv[1].get("seconds") or 0))[:6]\n',
     '    top = sorted(((k, v) for k, v in by.items()\n'
     '                  if ((lo <= float(v.get("at") or 0) <= hi) if spanned\n'
     '                      else (now - float(v.get("at") or 0) <= window))),\n'
     '                 key=lambda kv: -float(kv[1].get("seconds") or 0))[:6]\n'),
    ('    return {"window_s": window, "stalls": len(recent),\n'
     '            "gc": _gc_report(),                      # #1393\n',
     '    return {"window_s": window, "stalls": len(recent),\n'
     '            # [s3-timing] the span asked for, and how far back the ring reaches\n'
     '            **({"since": lo, "until": hi} if spanned else {}),\n'
     '            "ring_from": ring_from,\n'
     '            "gc": _gc_report(),                      # #1393\n'),
    ('@app.get("/api/pulse")\n'
     'async def pulse_api(\n'
     '    authorization: str | None = Header(default=None),\n'
     ') -> dict[str, Any]:\n'
     '    """#1156: what the event loop has been stuck in."""\n'
     '    require_read_auth(authorization)\n'
     '    return pulse_report(600)\n',
     '@app.get("/api/pulse")\n'
     'async def pulse_api(\n'
     '    authorization: str | None = Header(default=None),\n'
     '    since: float = 0.0,\n'
     '    until: float = 0.0,\n'
     ') -> dict[str, Any]:\n'
     '    """#1156: what the event loop has been stuck in. [s3-timing] `since`\n'
     '    and `until` (epoch seconds) ask for a span instead of the last 10 min."""\n'
     '    require_read_auth(authorization)\n'
     '    if since or until:\n'
     '        return pulse_report(600, since=since or None, until=until or None)\n'
     '    return pulse_report(600)\n'),
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
            print("MISSING (%d): %r" % (text.count(old), old[:80]))
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
