"""[sfxseen] tools/filemgr_groups.json: name data/sfx_display_receipts.jsonl in
the keep.telemetry group, so the file manager and the clean-slate wipe list it
as KEEP (an unlisted file is already never touched - this makes it visible).
JSON carries no comments, so the store's own name is the marker. CRLF-aware."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sfxseen_lib import Edit, run  # noqa: E402

EDITS = [Edit("keep.telemetry", '    "air_fixes.jsonl",\n', '    "sfx_display_receipts.jsonl",\n', where="before")]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, marker='"sfx_display_receipts.jsonl"'))
