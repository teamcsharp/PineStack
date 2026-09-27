#!/usr/bin/env python3
"""[listener-uploads] The courier: carries listener uploads from the station's
outbox to QuickSwap\\samples_grabbed\\user.

The station runs in a container whose view of the QuickSwap share is
read-only, on purpose. It stages each upload in data/uploads/outbox (whole
files only - a hidden .part is renamed into place when it is complete). This
runs ON THE HOST as the pinebox-uploads service and carries each file through
a read-write mount of that ONE folder (/home/ehm_eckx/quickswap-user, in
fstab, kept mounted by pinebox-mounts.sh), then writes a receipt the
station's status door reads:

  data/uploads/receipts/<name>.json  {"state": "delivered" | "waiting" | "failed", ...}

Never writes into an unmounted mountpoint (that would land the file on the
box's own disk under the mountpoint and look delivered). A file that fails
twenty times is moved to data/uploads/failed with its reason.

  python3 tools/uploads_courier.py --loop     # the service
  python3 tools/uploads_courier.py --once     # one pass, for a hand
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data", "uploads")
OUTBOX = os.path.join(DATA, "outbox")
RECEIPTS = os.path.join(DATA, "receipts")
FAILED = os.path.join(DATA, "failed")
DEST = os.environ.get("UPLOADS_DEST", "/home/ehm_eckx/quickswap-user")
DEST_UNC = "\\\\10.89.1.125\\QuickSwap\\samples_grabbed\\user"
PAUSE_S = 3.0
TRIES = 20
_tries: dict[str, int] = {}
_waiting_said = [0.0]


def say(text: str) -> None:
    print(time.strftime("%H:%M:%S ") + text, flush=True)


def write_receipt(name: str, body: dict) -> None:
    os.makedirs(RECEIPTS, exist_ok=True)
    body = dict(body, name=name, at=time.time())
    tmp = os.path.join(RECEIPTS, "." + name + ".json.part")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=1)
    os.replace(tmp, os.path.join(RECEIPTS, name + ".json"))


def free_name(folder: str, name: str) -> str:
    stem, ext = os.path.splitext(name)
    out, n = name, 1
    while os.path.exists(os.path.join(folder, out)):
        out = "%s-%d%s" % (stem, n, ext)
        n += 1
    return out


def carry(name: str) -> bool:
    """One file to the share. True when it is there, whole."""
    src = os.path.join(OUTBOX, name)
    size = os.path.getsize(src)
    final = free_name(DEST, name)
    part = os.path.join(DEST, "." + final + ".part")
    with open(src, "rb") as fin, open(part, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)
        fout.flush()
        os.fsync(fout.fileno())
    os.replace(part, os.path.join(DEST, final))
    got = os.path.getsize(os.path.join(DEST, final))
    if got != size:
        raise OSError("the share holds %d bytes of %d" % (got, size))
    os.remove(src)
    write_receipt(name, {"state": "delivered", "file": final, "bytes": size,
                         "dest": DEST_UNC + "\\" + final,
                         "why": "on the share; samples_grabbed is a drop folder, so a playable clip is in the SFX draw within minutes"})
    _tries.pop(name, None)
    say("delivered %s (%d bytes) as %s" % (name, size, final))
    return True


def one_pass() -> int:
    try:
        names = sorted(n for n in os.listdir(OUTBOX)
                       if not n.startswith(".") and not n.endswith(".part"))
    except FileNotFoundError:
        return 0
    if not names:
        return 0
    if not os.path.ismount(DEST):
        if time.time() - _waiting_said[0] > 300:
            say("%d waiting: %s is not mounted (pinebox-mounts remounts it)" % (len(names), DEST))
            _waiting_said[0] = time.time()
        for name in names:
            write_receipt(name, {"state": "waiting", "why": "the share is not mounted on the box yet - it goes as soon as it is"})
        return 0
    done = 0
    for name in names:
        src = os.path.join(OUTBOX, name)
        try:
            if time.time() - os.path.getmtime(src) < 1.0:
                continue                                  # just renamed in; next pass
            if carry(name):
                done += 1
        except Exception as exc:  # noqa: BLE001
            n = _tries[name] = _tries.get(name, 0) + 1
            why = "%s: %s" % (type(exc).__name__, exc)
            if n >= TRIES:
                os.makedirs(FAILED, exist_ok=True)
                try:
                    os.replace(src, os.path.join(FAILED, name))
                except OSError:
                    pass
                write_receipt(name, {"state": "failed", "why": why, "tries": n})
                say("gave up on %s after %d tries: %s" % (name, n, why))
            else:
                write_receipt(name, {"state": "waiting", "why": "the share refused it (%s) - trying again" % why, "tries": n})
                say("could not carry %s (try %d): %s" % (name, n, why))
    return done


def main(argv: list[str]) -> int:
    os.makedirs(OUTBOX, exist_ok=True)
    if "--once" in argv:
        print(one_pass())
        return 0
    say("courier up: %s -> %s" % (OUTBOX, DEST))
    while True:
        try:
            one_pass()
        except Exception as exc:  # noqa: BLE001
            say("pass failed: %s: %s" % (type(exc).__name__, exc))
        time.sleep(PAUSE_S)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
