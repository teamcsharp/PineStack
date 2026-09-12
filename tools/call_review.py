"""2026-09-09: read the phone calls back, as scripts.

The operator: "make sure that each of the phone calls are being broadcasted in
a complete fashion where they take place and actually have a plot and a
resolution and a degree of hilarity due to the randomness of speaker box chunks
and then the tinting of the crystal."

Reviewing that needed a way to READ a call, and there wasn't one: the air log
is one row per line, calls are interleaved with everything else, and the row's
`kind` is "call" for every turn of every coalesced round - banter included -
so the obvious filter returns mostly not-calls. The road is in `round`.

    python tools/call_review.py [hours] [--full] [--n N]

Segmentation: a call OPENS on the station's own ring line and CLOSES on the
next one. Grouping by time gaps bleeds one call's opener into the previous
call's tail, which is how a first reading of this made the engine look far
worse than it is.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
# The station's own openers. A ring, or the re-air announce.
OPENER = re.compile(r"(request line ringing|on line [\d,]+:)", re.I)
# What a resolution sounds like here. The sign-off is written by the station,
# so this is matching its own words rather than guessing at English.
SIGNOFF = re.compile(r"(thanks for calling|stay with pine box|taking that detail"
                     r"|we're taking that|before you (?:walk away|go))", re.I)


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).split())


def load(hours, now):
    rows = []
    for line in (DATA / "air_log.jsonl").read_text(
            encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        at = float(row.get("air_at") or row.get("ts") or 0)
        if now - at <= hours * 3600:
            row["_t"] = at
            rows.append(row)
    rows.sort(key=lambda r: r["_t"])
    return rows


def calls(rows):
    """Caller-road rows, cut into calls on the station's own ring."""
    out, cur = [], []
    for row in rows:
        road = str(row.get("round") or "")
        if road != "caller" and str(row.get("kind")) != "hangup":
            continue
        if OPENER.search(str(row.get("text") or "")) and cur:
            out.append(cur)
            cur = []
        cur.append(row)
    if cur:
        out.append(cur)
    return out


def verdict(call):
    spoken = [t for t in call if str(t.get("text") or "").strip()]
    texts = [str(t.get("text") or "") for t in spoken]
    seats = {str(t.get("who") or "") for t in spoken}
    return {
        "turns": len(spoken),
        "caller_spoke": "caller" in seats or "caller2" in seats,
        "hosts_spoke": bool(seats & {"dj", "cohost", "third"}),
        "resolved": any(SIGNOFF.search(t) for t in texts[-6:]),
        "hung_up": any(str(t.get("kind")) == "hangup" for t in call),
        "seeded": sorted({str(t.get("source")) for t in call if t.get("source")}),
        "unique": (len({norm(t) for t in texts if norm(t)}) / max(1, len(texts))),
        "stub": len(spoken) <= 2,
    }


def main():
    args = sys.argv[1:]
    hours = 8.0
    show = 3
    skip = set()
    for i, a in enumerate(args):
        if i in skip:
            continue
        if a == "--n" and i + 1 < len(args):
            show = int(args[i + 1])
            skip.add(i + 1)   # the count is not the hours
        elif not a.startswith("-"):
            try:
                hours = float(a)
            except ValueError:
                pass
    now = time.time()
    rows = load(hours, now)
    if rows:
        now = max(r["_t"] for r in rows) + 1     # the station's clock, not ours
        rows = load(hours, now)
    found = calls(rows)
    if not found:
        print("no calls in that window")
        return
    marks = [verdict(c) for c in found]
    real = [m for m in marks if not m["stub"]]
    print(f"{len(found)} calls in the last {hours:g} hours "
          f"({len(marks) - len(real)} stubs)")
    if real:
        def share(key):
            return sum(1 for m in real if m[key]) / len(real)
        print(f"  the caller actually spoke : {share('caller_spoke'):.0%}")
        print(f"  reached a spoken sign-off : {share('resolved'):.0%}")
        print(f"  played the receiver down  : {share('hung_up'):.0%}")
        print(f"  carried a speakbox source : {share('seeded'):.0%}")
        print(f"  turns per call            : "
              f"{min(m['turns'] for m in real)}-{max(m['turns'] for m in real)}")
        print(f"  unique lines within a call: "
              f"{sum(m['unique'] for m in real) / len(real):.0%}")
    if "--full" in args:
        for call, mark in list(zip(found, marks))[-show:]:
            print("\n" + "=" * 72)
            print(f"{mark['turns']} turns · "
                  f"{'resolved' if mark['resolved'] else 'NO SIGN-OFF'} · "
                  f"{'hung up' if mark['hung_up'] else 'no receiver-down'} · "
                  f"seeded by {', '.join(mark['seeded']) or 'nothing'}")
            print("=" * 72)
            for turn in call:
                text = str(turn.get("text") or turn.get("sfx") or "")
                if not text.strip():
                    continue
                who = str(turn.get("name") or turn.get("who") or "?")
                print(f"  {who[:14]:>14}: {text}")


if __name__ == "__main__":
    main()
