"""[host-courier] the PineTab's exports reach PineBoxRecordings with or without the desk.

2026-09-30, the operator: "with the pinetab. Allow me to be able to export video
directly to \\\\10.89.1.125\\QuickSwap\\PineBoxRecordings instead of going
through the app if its not present and detected. I need it to be able to directly
place things there".

The container cannot write the share (#1114), but the HOST now mounts
//exbox.local/quickswap/PineBoxRecordings read-write at
/home/ehm_eckx/pinebox-recordings (fstab, the same credentials as the existing
rw samples_grabbed/user mount). tools/host_courier.py runs on the host, reads
this ledger, and carries what the desk has not: it writes a receipt line to
data/export_courier_host.jsonl, which courier_pending folds in here (under the
ledger's lock - the host never writes the ledger itself). The desk is
"present" while it polls GET /api/export/courier (every 20 s); each poll stamps
data/export_courier_desk_seen.json, and the host courier stands back while
that stamp is fresh.

Usage (ON THE HOST): python3 tools/host_courier_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

PENDING_OLD = '''    with _COURIER_LOCK:
        rows = [r for r in courier_read() if r.get("state") == "pending"]
    out: list[dict[str, Any]] = []
'''
PENDING_NEW = '''    courier_fold_host()                                      # [host-courier]
    with _COURIER_LOCK:
        rows = [r for r in courier_read() if r.get("state") == "pending"]
    out: list[dict[str, Any]] = []
'''

HELPERS_AT = "def courier_pending() -> list[dict[str, Any]]:\n"
HELPERS_NEW = '''# [host-courier] the host carries what the desk has not (tools/host_courier.py):
# its receipts land in this file and are folded into the ledger here, so only
# the station ever writes the ledger.
COURIER_HOST_RECEIPTS = "export_courier_host.jsonl"
COURIER_DESK_SEEN = "export_courier_desk_seen.json"
_COURIER_DESK_SEEN_AT = [0.0]


def courier_desk_seen() -> None:
    """The desk polled: stamp it (at most every 10 s) for the host courier."""
    now = time.time()
    if now - _COURIER_DESK_SEEN_AT[0] < 10:
        return
    _COURIER_DESK_SEEN_AT[0] = now
    try:
        p = data_path(COURIER_DESK_SEEN)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": now}), encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001
        pass


def courier_fold_host() -> int:
    """Rows the host courier carried become done, with where they went."""
    p = data_path(COURIER_HOST_RECEIPTS)
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return 0
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return 0
    got: dict[str, dict[str, Any]] = {}
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(r, dict) and r.get("id") and r.get("ok"):
            got[str(r["id"])] = r
    if not got:
        return 0
    n = 0
    with _COURIER_LOCK:
        rows = courier_read()
        for row in rows:
            r = got.get(str(row.get("id")))
            if r and row.get("state") == "pending":
                row["state"] = "done"
                row["done_at"] = float(r.get("at") or time.time())
                row["where"] = str(r.get("path") or "")[:400]
                row["carried_by"] = "host"
                n += 1
        if n:
            courier_write(rows)
    if n:
        pipeline_log("air", "courier: the host placed %d export(s) in PineBoxRecordings "
                            "directly [host-courier]" % n)
        for r in got.values():
            try:
                note_action("placed %s in %s directly - the desk was not there to carry it"
                            % (r.get("name") or "an export", r.get("share") or "PineBoxRecordings"))
            except Exception:  # noqa: BLE001
                pass
    try:   # keep only receipts the ledger has not taken yet
        keep = [ln for ln in lines if (json.loads(ln) or {}).get("id") not in
                {str(row.get("id")) for row in courier_read() if row.get("state") == "done"}]
        p.write_text("\\n".join(keep) + ("\\n" if keep else ""), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return n


'''

API_OLD = '''    require_read_auth(authorization)
    pending = await asyncio.to_thread(courier_pending)
    prefs = pinelink_prefs_read()
'''
API_NEW = '''    require_read_auth(authorization)
    courier_desk_seen()                                      # [host-courier] the desk is here
    pending = await asyncio.to_thread(courier_pending)
    prefs = pinelink_prefs_read()
'''

EDITS = [("helpers", HELPERS_AT, HELPERS_NEW + HELPERS_AT),
         ("pending folds", PENDING_OLD, PENDING_NEW),
         ("desk seen", API_OLD, API_NEW)]


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if "[host-courier]" in src:
        print(path + ": APPLIED")
        return
    out = src
    for label, old, new in EDITS:
        n = out.count(old)
        assert n == 1, "%s: anchor found %d times" % (label, n)
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (%d edits)" % len(EDITS))
        return
    shutil.copy(path, "/tmp/app.py.bak-host-courier")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
