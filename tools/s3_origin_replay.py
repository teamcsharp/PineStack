"""[s3-account] Replay real air through the origin ledger.

Reads data/air_log.jsonl (the last HOURS of aired items), data/script_ledger.jsonl
(their script rows and stamps) and data/system3.sqlite3 (read-only), builds every
item's origin record with system3_origin.build exactly as the live keeper does,
and prints the coverage report (by road: rolled / forced / rogue) and the
worst untraced code paths.

History has no ring frame chain, so a rogue row's producer is INFERRED from its
shape (infer_path below, marked "inferred:"); on the live station the ring
names the real function.

    python3 tools/s3_origin_replay.py [HOURS] [--db /tmp/x.sqlite3] [--into]

--into writes the records into the live data/system3_origin.sqlite3 (a backfill:
run it inside the container, where data/ is writable; ids the live keeper already
wrote are left alone). Default: a scratch db.
Read-only on every live file otherwise. Run niced.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import system3_origin as so  # noqa: E402

PUNCT = re.compile(r"^(.*)-punct-\d+$")


def infer_path(a):
    """Best guess at the producer of a historical row with no frame chain."""
    k, w, r = str(a.get("kind") or ""), str(a.get("who") or ""), str(a.get("round") or "")
    t = str(a.get("text") or "")
    lid = str(a.get("id") or "")
    if k == "ad" and t.startswith("\U0001f4e3 sponsor spot"):
        return "inferred:ad_booth_row<dj_service_ad|dj_engineering_ad"
    if k == "ad" and t.startswith("\U0001f4e3"):
        return "inferred:ad_booth_row<_air_produced_ad"
    if k == "ad":
        return "inferred:ad_booth_row<air_music_ad"
    if k == "manager":
        return "inferred:_dj_upstairs_page_floorless"
    if k == "emergency_host":
        return "inferred:continuity_air"
    if k == "sfx" and t.startswith("\U0001f50a") and len(lid) == 32:
        return "inferred:continuity_air|_dj_speak_floorless (cadence addition)"
    if k == "sfx" and len(lid) == 6 and a.get("aired") == "page":
        return "inferred:_sfx_cycle_note (the endless set)"
    if k == "sfx" and str(a.get("sfx_dir") or "") == "the desk":
        return "inferred:_desk_sound"
    if k == "sfx" and PUNCT.match(lid):
        return "inferred:_dj_speak_floorless (a cadence clip welded to a single line)"
    if k == "sfx":
        return "inferred:dj_sting"
    if w == "host":
        return "inferred:dj_caller|_news_once (desk marker)"
    return "inferred:%s/%s" % (k, r)


def main(argv):
    hours = float(next((a for a in argv if re.match(r"^\d+(\.\d+)?$", a)), "24"))
    into = "--into" in argv
    base = HERE / "data"
    dbp = (base / "system3_origin.sqlite3") if into else Path(
        argv[argv.index("--db") + 1] if "--db" in argv else "/tmp/s3account/origin_replay.sqlite3")
    if not into and dbp.exists():
        dbp.unlink()
    dbp.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cut = now - hours * 3600
    air = {}
    with open(base / "air_log.jsonl", encoding="utf-8") as f:
        for ln in f:
            try:
                a = json.loads(ln)
            except Exception:
                continue
            at = float(a.get("air_at") or a.get("ts") or 0)
            if cut <= at <= now and a.get("id"):
                air[a["id"]] = a
    rows = sorted((a for a in air.values() if so.eligible(a)),
                  key=lambda a: (1 if PUNCT.match(a["id"]) else 0, float(a.get("air_at") or 0)))
    # (labels are linked in air order here, then again in the second pass below)
    want = {a["id"] for a in rows} | {PUNCT.match(a["id"]).group(1) for a in rows if PUNCT.match(a["id"])}
    ledger = {}
    with open(base / "script_ledger.jsonl", encoding="utf-8") as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("line_id") in want:
                r.pop("system_prompts", None)
                ledger[r["line_id"]] = r
    led = so.OriginLedger(dbp, dbp.parent / "reports", base / "system3.sqlite3")
    led.ledger_cap = 10 ** 7
    led.marker_cap = 10 ** 6
    for lid, r in ledger.items():
        led.ledger_note(r.get("block"), r.get("at"), r.get("sid"), r.get("round"), r.get("segment"),
                        [dict(r, _ord=r.get("ord"))])
    s3 = led._s3db()
    s3lines = {}
    if s3 is not None:
        ids = list(want)
        for i in range(0, len(ids), 400):
            ch = ids[i:i + 400]
            for lid, cid, tid in s3.execute("SELECT line_id, conversation_id, turn_id FROM lines WHERE line_id IN (%s)"
                                            % ",".join("?" * len(ch)), ch):
                s3lines[lid] = {"conversation_id": cid, "turn_id": tid, "via": "System 3 lines table"}
    batch = []
    markers = []
    if into:        # a backfill never overwrites what the live keeper already wrote
        have = {r[0] for r in led.db.execute("SELECT line_id FROM origin")}
        rows = [a for a in rows if a["id"] not in have]
    for a in rows:
        if so.label_kind({"road": so.road_of(a), "kind": a.get("kind"), "text": a.get("text")}):
            markers.append(a)
        rec, _known = led.build_live(a, lambda lid: s3lines.get(lid))
        if not so.frame_chain(a) and rec["compact"]["verdict"] == "rogue":
            rec["compact"]["producer"] = infer_path(a)
            rec["compact"]["rogue"]["producer"] = rec["compact"]["producer"]
        if not so.frame_chain(a) and rec["compact"]["verdict"] != "rogue":
            rec["compact"]["producer"] = rec["compact"].get("producer") or infer_path(a)
        batch.append((rec, True))
        if len(batch) >= 500:
            led.upsert(batch)
            batch = []
    for a in markers:                     # a label links to the road it announces: second pass
        rec, _known = led.build_live(a, lambda lid: s3lines.get(lid))
        if rec["compact"]["verdict"] == "rogue":
            rec["compact"]["producer"] = rec["compact"]["rogue"]["producer"] = infer_path(a)
        batch.append((rec, True))
    if batch:
        led.upsert(batch)
    rep = led.coverage(cut, now + 1)
    rep["hours"] = hours
    rep["db"] = str(dbp)
    rep["ledger_metrics"] = dict(led.metrics)
    rep["untraced_sample"] = led.untraced(cut, 12)["items"]
    if "--since" in argv:                 # e.g. the last restart: what is still open
        since = float(argv[argv.index("--since") + 1])
        rep["since"] = {"at": since, **led.coverage(since, now + 1)}
    print(json.dumps(rep, indent=1, default=str))
    return 0


if __name__ == "__main__":
    os.nice(10) if hasattr(os, "nice") else None
    sys.exit(main(sys.argv[1:]))
