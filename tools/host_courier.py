#!/usr/bin/env python3
"""[host-courier] carry the station's exports into PineBoxRecordings from the HOST.

"Allow me to be able to export video directly to
\\\\10.89.1.125\\QuickSwap\\PineBoxRecordings instead of going through the app if
its not present and detected."

Runs on the host (systemd: pinebox-host-courier.service) beside the read-write
mount of //exbox.local/quickswap/PineBoxRecordings at MOUNT. Every POLL_S it
reads the station's courier ledger (data/export_courier.json, read only), and
for each pending file owed to the PineBoxRecordings share it copies the file
(the station's /app/... path is the host's STATION_ROOT/...) to the share as
<name>.part, renames it, and appends a receipt to data/export_courier_host.jsonl.
The station folds receipts into its own ledger (courier_fold_host) - this
script never writes the ledger.

It stands back while the desk is present: the station stamps
data/export_courier_desk_seen.json on every desk poll (every 20 s), and a stamp
younger than DESK_FRESH_S means the desk will carry it itself.
"""
import json
import os
import shutil
import time
from pathlib import Path

STATION_ROOT = Path("/home/ehm_eckx/pinevoice-stack/spark-agent")
DATA = STATION_ROOT / "data"
MOUNT = Path("/home/ehm_eckx/pinebox-recordings")
SHARE_PREFIXES = ("\\\\10.89.1.125\\quickswap\\pineboxrecordings",
                  "\\\\exbox.local\\quickswap\\pineboxrecordings",
                  "\\\\exbox\\quickswap\\pineboxrecordings")
POLL_S = 5.0
DESK_FRESH_S = 45.0
MIN_AGE_S = 3.0          # the upload has finished writing


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def desk_present() -> bool:
    try:
        at = float(json.loads((DATA / "export_courier_desk_seen.json").read_text()).get("at") or 0)
    except Exception:  # noqa: BLE001
        return False
    return time.time() - at < DESK_FRESH_S


def done_ids() -> set:
    out = set()
    try:
        for line in (DATA / "export_courier_host.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                out.add(str(json.loads(line).get("id")))
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return out


def share_sub(dest: str) -> Path | None:
    """The folder under MOUNT a Windows destination names, or None."""
    d = str(dest or "").replace("/", "\\").rstrip("\\")
    low = d.lower()
    for pre in SHARE_PREFIXES:
        if low == pre or low.startswith(pre + "\\"):
            rest = d[len(pre):].strip("\\")
            parts = [p for p in rest.split("\\") if p and p not in (".", "..")]
            return MOUNT.joinpath(*parts) if parts else MOUNT
    return None


def host_path(p: str) -> Path | None:
    s = str(p or "")
    if s.startswith("/app/"):
        return STATION_ROOT / s[len("/app/"):]
    if s.startswith(str(STATION_ROOT)):
        return Path(s)
    return None


def carry(row: dict, done: set) -> None:
    rid = str(row.get("id") or "")
    if not rid or rid in done or row.get("state") != "pending" or row.get("what") == "delete":
        return
    folder = share_sub(str(row.get("dest") or ""))
    src = host_path(str(row.get("path") or ""))
    if folder is None or src is None or not src.is_file():
        return
    if time.time() - src.stat().st_mtime < MIN_AGE_S:
        return
    name = os.path.basename(str(row.get("name") or src.name)) or src.name
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / name
    part = folder / (name + ".part")
    shutil.copyfile(src, part)
    os.replace(part, final)
    receipt = {"id": rid, "ok": True, "path": str(final), "name": name,
               "share": "\\\\10.89.1.125\\QuickSwap\\PineBoxRecordings", "at": time.time(),
               "bytes": final.stat().st_size}
    with open(DATA / "export_courier_host.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(receipt) + "\n")
    done.add(rid)
    log("placed %s (%d bytes) in %s" % (name, receipt["bytes"], folder))


def once() -> None:
    if not os.path.ismount(MOUNT):
        return
    if desk_present():
        return
    try:
        rows = json.loads((DATA / "export_courier.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    rows = rows.get("rows") if isinstance(rows, dict) else rows
    done = done_ids()
    for row in rows or []:
        if isinstance(row, dict):
            try:
                carry(row, done)
            except Exception as exc:  # noqa: BLE001
                log("could not place %s: %s" % (row.get("name"), exc))


def main() -> None:
    log("host courier up: %s -> %s" % (DATA, MOUNT))
    while True:
        once()
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
