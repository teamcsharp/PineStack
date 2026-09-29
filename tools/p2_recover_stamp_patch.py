"""[s3-account-recover] app.py: boot recovery republishes a line WITH its origin.

Measured 2026-09-29: all 24 rogue items of the last 6 h came down
page_recovery_chat_rows < page_recovery_start. The preserved page delivery
(data/page_delivery_recovery.json) is rebuilt into a ring row from the clip's
row fields (id, who, kind, text) - the System 3 stamp the original ring row
carried is not among them, so the republished line aired as "no System 3
stamp". The upstairs page is the sharpest case: it is the opening of its
chapter (made["system3"] = the chapter's stamp) but the only copy of that
stamp was the ring row the restart dropped, and the page's audio line is not
in System 3's line register.

Fix, on the recovery road itself:
  - the manager page's delivery clip keeps the page's stamp (the ring row
    already carries it; the clip now does too, so what survives a restart
    names its node);
  - page_recovery_chat_rows puts that stamp back on the republished row, and
    a replay of an already-heard line (page_recovery_prepare_row gives it a
    NEW id) names the line it replays (`recovered_from`), which the origin
    ledger's [s3-account-p2] reads back.

  python tools/p2_recover_stamp_patch.py --check app.py   (0 ready, 2 applied, 1 anchor missing)
  python tools/p2_recover_stamp_patch.py --apply app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s3_account_p2_lib import Edit, run  # noqa: E402

MARKER = "[s3-account-recover]"

EDITS = [
    Edit("page-clip-stamp",
         '            "row_id": line_id, "who": "manager", "kind": "manager",\n',
         '            **({"system3": dict(made["system3"])}              # [s3-account-recover] survives a restart\n'
         '               if isinstance(made.get("system3"), dict) else {}),\n'),
    Edit("recovered-row-origin",
         "        row = dict(old or source)\n",
         "        if clip.get(\"recovered_from_row_id\"):        # [s3-account-recover] the heard line it replays\n"
         "            row[\"recovered_from\"] = str(clip.get(\"recovered_from_row_id\"))\n"
         "        if plain and not isinstance(row.get(\"system3\"), dict) and isinstance(clip.get(\"system3\"), dict):\n"
         "            row[\"system3\"] = dict(clip[\"system3\"])   # [s3-account-recover] the stamp the delivery kept\n"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, MARKER))
