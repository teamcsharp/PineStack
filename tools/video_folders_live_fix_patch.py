#!/usr/bin/env python3
"""[video-folders-live] follow-up, 2026-10-14: the fresh list took 55 s and lost its tail.

1. The samples query let sqlite pick clips_pick (playable, video) over the path range, a full
   scan per folder; `+` keeps those two columns off the index so the path range is used.
2. Two levels under samples_grabbed is ~1,100 folders (viceP/yt-*, iasip/yt-*); the 1,000 cap
   cut the alphabet's tail (user among it). The cap is 5,000.

Usage:  video_folders_live_fix_patch.py --check|--apply [ROOT]   0 ready, 2 applied, 1 missing
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_folders_live_patch as base  # noqa: E402

base.EDITS = {"app.py": [
    ("samples use the path range",
     '''                    "SELECT sid, name, seconds FROM clips WHERE path >= ? AND path < ? AND playable = 1"
                    " AND video = ? LIMIT 3", (d + "/", d + "0", is_v)).fetchall()
''',
     '''                    "SELECT sid, name, seconds FROM clips WHERE path >= ? AND path < ? AND +playable = 1"
                    " AND +video = ? LIMIT 3", (d + "/", d + "0", is_v)).fetchall()   # + : the path range, not clips_pick
''',
     "# + : the path range, not clips_pick", 1),
    ("the list keeps its tail",
     '''    return sorted(out.values(), key=lambda f: f["path"])[:1000]
''',
     '''    return sorted(out.values(), key=lambda f: f["path"])[:5000]
''',
     'key=lambda f: f["path"])[:5000]', 1),
]}

if __name__ == "__main__":
    sys.exit(base.main(sys.argv))
