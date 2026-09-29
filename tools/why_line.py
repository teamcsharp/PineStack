#!/usr/bin/env python3
"""[msgid] Why this line? One message's life story, from its hex code.

Resolves the code (#3c4782, 3c4782, a full id, any hex prefix >= 6, or a
welded cue's 1a2b3c4d-p1) across every store and prints one chronological
story: planned (script ledger, System 3, origin) -> written/rendered ->
gates -> published (station_flow, air log, sfx_history `who`) -> heard ->
seen (display receipts) -> the operator's reactions, then the neighbours on
air within +/-5 s and a VERDICT. Read-only: the same reader as GET /api/why/{code}
(line_story.py), straight off the files, so it needs no key.

  docker exec spark-agent python3 tools/why_line.py 3c4782
  docker exec spark-agent python3 tools/why_line.py '#3c4782' --json
  docker exec spark-agent python3 tools/why_line.py 3c47 --all     # every message the code names
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
DATA = HERE / "data" if (HERE / "data" / "air_log.jsonl").exists() else Path("/app/data")

import line_story  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("code", help="the message's code, e.g. 3c4782 or #3c4782")
    ap.add_argument("--data", default=os.getenv("PINE_DATA_DIR", str(DATA)))
    ap.add_argument("--json", action="store_true", help="the story as JSON")
    ap.add_argument("--all", action="store_true", help="list every message the code names, then stop")
    a = ap.parse_args(argv)
    if not line_story.parse(a.code):
        print("not a message code: %r (6-32 hex, optional #)" % a.code)
        return 1
    if a.all:
        res = line_story.resolve(Path(a.data), a.code)
        if a.json:
            json.dump(res, sys.stdout, indent=1, default=str)
            print()
        else:
            for m in res["matches"]:
                print("#%-12s %s  %s  %s/%s  %s  [%s]" % (
                    m["code"], m["id"], line_story.when(m.get("at"), True), m.get("who"), m.get("kind"),
                    m.get("text", "")[:50], ", ".join(m.get("found_in") or [])))
            if not res["matches"]:
                print(res.get("why"))
        return 0 if res["matches"] else 1
    s = line_story.story(Path(a.data), a.code)
    if a.json:
        json.dump(s, sys.stdout, indent=1, default=str)
        print()
    else:
        print(line_story.format_text(s))
    return 0 if s.get("id") else 1


if __name__ == "__main__":
    if hasattr(os, "nice"):
        os.nice(10)
    raise SystemExit(main())
