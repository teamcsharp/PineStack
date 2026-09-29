#!/usr/bin/env python3
"""[sfxseen] Which script SFX played, and did their pictures reach a screen?

Read-only. Joins the script's SFX rows (data/air_log.jsonl, the rows the
screenplay prints as "A sting off the board: ...") with the players' display
receipts (data/sfx_display_receipts.jsonl) - the same join as
GET /api/sfx/display-audit, straight off the files, so it needs no key.

  docker exec -w /app spark-agent python3 tools/sfx_display_audit.py            # last hour
  docker exec -w /app spark-agent python3 tools/sfx_display_audit.py --hours 6
  docker exec -w /app spark-agent python3 tools/sfx_display_audit.py --line e78120
  docker exec -w /app spark-agent python3 tools/sfx_display_audit.py --json > audit.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import sfx_display  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--line", default="", help="one script row's line id")
    ap.add_argument("--data", default=os.getenv("PINE_DATA_DIR", str(HERE / "data")))
    ap.add_argument("--json", action="store_true", help="the endpoint's JSON instead of text")
    ap.add_argument("--rows", type=int, default=60, help="rows printed (text mode)")
    a = ap.parse_args(argv)
    data = Path(a.data)
    now = time.time()
    since = now - max(0.05, min(168.0, a.hours)) * 3600.0
    if a.line:
        since = now - sfx_display.KEEP_S
    rows = sfx_display.script_rows(data / "air_log.jsonl", since, now)
    if a.line:
        hit = [r for r in rows if str(r.get("id")) == a.line]
        if not hit:
            print("no script SFX row %r in the air log (kept two days)" % a.line)
            return 1
        at = float(hit[0].get("air_at") or hit[0].get("ts") or 0)
        since, now = at - 120, at + 600
    store = sfx_display.ReceiptStore(data / sfx_display.STORE_NAME)
    rep = sfx_display.audit(rows, store.read(since, now), since, now, line=a.line)
    if a.json:
        json.dump(rep, sys.stdout, indent=1, default=str)
        print()
    else:
        print(sfx_display.format_text(rep, a.rows))
        if not rep["players"]:
            print("\n(no display receipts yet: the players need the [sfxseen] build - sfx-seen.js)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
