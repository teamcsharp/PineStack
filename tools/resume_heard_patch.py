"""[resume-heard] a clip the tablet was part-way through resumes where the ear left it.

2026-09-30, the operator: "right now im not seeing videos pop up on the tablet".
Measured: the PineTab was 9 minutes into a 10-minute conversation clip when a
kiosk install relaunched it. The fresh page took the clip again (#1184: owed
air is replayed, never dropped) and played it FROM ZERO - nine minutes of
lines already heard, aired again; no new heard rows; the feed's bubbles
replaying the same stings 9.5 minutes late; and no tube pictures at all,
because a delivery's pictures were rung once, for the page that died.

Every relaunch and every tablet reboot (four kernel panics today) does this.

  1. Every audible `playing` acknowledgement writes how far the ear has got
     onto the clip itself (`resume_at`), which /api/dj/voice serves.
  2. Both page players take `resume_at` as the clip's resumeAt - the seek
     they already make when resuming their own pause - so a fresh page
     starts where the last one stopped, not at the top.
  3. The sting pictures are rung once PER PAGE that plays the delivery (the
     rows still ahead of the position), not once per delivery.

Usage (ON THE HOST): python3 tools/resume_heard_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[resume-heard]"

EDITS = [
    ("stamp",
     '''        if audible > 0 and progressed and delivery.get("speech"):
            try:
                stream = clip.get("stream") or {}
''',
     '''        if audible > 0 and progressed and delivery.get("speech"):
            try:                                     # [resume-heard] how far the ear got
                clip["resume_at"] = round(max(float(clip.get("resume_at") or 0),
                                              float(position) - 0.3), 2)
            except Exception:  # noqa: BLE001
                pass
            try:
                stream = clip.get("stream") or {}
''', 1),
    ("pictures",
     '''                    if not delivery.get("sfx_pictures_rung"):
                        pending = [row for row in stream["rows"]
                                   if float(row.get("until") or 0) > position]
                        _sfx_cadence_pictures(pending, now - position)
                        delivery["sfx_pictures_rung"] = True
''',
     '''                    if delivery.get("sfx_pictures_rung") != listener:   # [resume-heard] per page
                        pending = [row for row in stream["rows"]
                                   if float(row.get("until") or 0) > position]
                        _sfx_cadence_pictures(pending, now - position)
                        delivery["sfx_pictures_rung"] = listener
''', 1),
    ("panel-intake",
     '''      clip.broadcastAt = Date.now() + Number(clip.broadcast_ms || clip.ts) - serverMs;
      // History can expire at join;''',
     '''      clip.broadcastAt = Date.now() + Number(clip.broadcast_ms || clip.ts) - serverMs;
      if (Number(clip.resume_at) > 0 && !clip.resumeAt) clip.resumeAt = Number(clip.resume_at);   // [resume-heard]
      // History can expire at join;''', 1),
    ("listen-intake",
     '''      clip.broadcastAt = Date.now() + Number(clip.broadcast_ms || clip.ts) - serverMs;
      clip.keepWhole = !!(clip.speech || clip.stream) && (voicePrimed''',
     '''      clip.broadcastAt = Date.now() + Number(clip.broadcast_ms || clip.ts) - serverMs;
      if (Number(clip.resume_at) > 0 && !clip.resumeAt) clip.resumeAt = Number(clip.resume_at);   // [resume-heard]
      clip.keepWhole = !!(clip.speech || clip.stream) && (voicePrimed''', 1),
]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    out = src
    for name, old, new, count in EDITS:
        assert out.count(old) == count, "%s: anchor found %d times" % (name, out.count(old))
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-resume-heard")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
