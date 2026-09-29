"""Read-only: the SFX candidate population under the patched filter, with the
live clip book and the live dial (LIVE_RATIOS = GET /api/sfx/ratios)."""
import ast
import collections
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

SRC = open(os.environ.get("PATCHED_APP", "/tmp/wmp4e_src/app.py"), encoding="utf-8").read()
T = ast.parse(SRC)
L = SRC.split("\n")
print("parsed the patched app.py", flush=True)


def grab(name):
    for n in T.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return "\n".join(L[n.lineno - 1:n.end_lineno])
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            ts = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(getattr(t, "id", "") == name for t in ts):
                return "\n".join(L[n.lineno - 1:n.end_lineno])
    raise SystemExit("missing " + name)


live = json.loads(os.environ["LIVE_RATIOS"])
ns = {"Any": object, "Path": Path, "re": re, "json": json, "time": time,
      "RLock": threading.RLock}
exec(grab("SFX_VIDEO_TYPES"), ns)
ns.update({"sfx_video_share": lambda: int(live["effective_video_share"]),
           "sfx_is_video": lambda p: Path(str(p)).suffix.lower() in ns["SFX_VIDEO_TYPES"],
           "sfx_id": lambda p: "0" * 16,
           "data_path": lambda *a: Path("/nonexistent", *a),
           "SFX_ROOT": Path("/samples"), "SFX_LOCAL_ROOT": Path("/app/data/samples")})
for c in ("_MP4ONLY", "_SFX_QUARANTINED", "_SFX_GONE_FOLDERS", "_SFX_QUARANTINE_LOADED",
          "_SFX_QUARANTINE_LOCK", "_SFX_RECEIPT_STRIKES", "_SFX_UNDECODABLE_RE"):
    exec(grab(c), ns)
for f in ("sfx_mp4_only", "_sfx_quarantine_path", "_sfx_quarantine_load",
          "sfx_quarantined", "sfx_clip_refusal"):
    exec(grab(f), ns)
VIDEO = ns["SFX_VIDEO_TYPES"]
con = sqlite3.connect("file:/app/data/sfx_clips.db?mode=ro", uri=True)
before, after, removed = collections.Counter(), collections.Counter(), collections.Counter()
for (p,) in con.execute("SELECT path FROM clips WHERE playable = 1"):
    ext = Path(p).suffix.lower() or "(none)"
    before[ext] += 1
    why = ns["sfx_clip_refusal"](p)
    if why:
        removed[why] += 1
    else:
        after[ext] += 1


def audio(c):
    return sum(v for k, v in c.items() if k not in VIDEO)


print("live dial:", live, "-> sfx_mp4_only():", ns["sfx_mp4_only"]())
print("book candidates today (playable=1):", sum(before.values()), "audio:", audio(before),
      dict(before.most_common(8)))
print("after the filter:", sum(after.values()), "audio:", audio(after), dict(after.most_common(8)))
print("removed by:", dict(removed))
