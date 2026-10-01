"""[owner-fair] a device cannot be judged deaf to silence.

2026-09-30, the operator: "And now they're quiet again." Measured: the PineTab
was present, switched on and sounding (heard 0.6 s before), the only audible
receiver - and nobody owned the air, so the DJs' lines went out unheard.
_owner_takes_nothing (#1332) drops an owner that confirmed no clip for 75 s and
bars its device for 300 s (#1332c/#1337) - without asking whether any clip was
SENT in those 75 s. When the DJs go quiet (a starved writer, a restart) the
owner has nothing to confirm, is dropped as deaf, and the next lines arrive
with no owner: a quiet patch turned into an unheard one, again and again.

Now an owner is judged only on what it was sent: no page delivery published in
the window (10 s allowed for it to start) means it is not deaf.

Usage (ON THE HOST): python3 tools/owner_fair_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[owner-fair]"

OLD = '''            return False          # it is sounding; leave it alone
        others = [w for w in (_listeners_live() or []) if w != who]
'''
NEW = '''            return False          # it is sounding; leave it alone
        # [owner-fair] nothing was sent to take: an owner cannot be deaf to silence
        try:
            sent = any(floor <= float((d or {}).get("at") or 0) <= now - 10
                       for d in list(_PAGE_DELIVERIES.values()))
        except Exception:  # noqa: BLE001
            sent = True
        if not sent:
            return False
        others = [w for w in (_listeners_live() or []) if w != who]
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor %d" % src.count(OLD)
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-owner-fair")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
