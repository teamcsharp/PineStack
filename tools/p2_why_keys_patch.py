"""[s3-account-keys] line_story.py: why_line / GET /api/why answer for EVERY aired
item the origin ledger keys, not only the hex-coded lines.

Measured 2026-09-29: 79 of 3,129 items in 6 h were record spins, keyed in the
origin ledger as "rec:<track>:<at>" (the endless set's clips are
"wall:<clip>:<at>", a live set "live:<event>:..."). `why_line.py rec:...`
answered "not a message code (6-32 hex, optional #)" - the one item class the
story could not be told for, although the ledger holds its origin.

Fix: parse() also takes an origin key (rec:/wall:/live:, exact, case kept);
matches() compares such a key exactly. Everything else - the stores it reads,
the story, the verdict - is unchanged; the origin ledger is already one of
resolve()'s stores.

  python tools/p2_why_keys_patch.py --check line_story.py   (0 ready, 2 applied, 1 anchor missing)
  python tools/p2_why_keys_patch.py --apply line_story.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s3_account_p2_lib import Edit, run  # noqa: E402

MARKER = "[s3-account-keys]"

EDITS = [
    Edit("origin-key-re",
         'PUNCT = re.compile(r"^(.*)-punct-(\\d+)$")\n',
         '# [s3-account-keys] an aired item with no hex id: its origin-ledger key, exact\n'
         'ORIGIN_KEY = re.compile(r"^(?:rec|wall|live):[0-9A-Za-z_.\\-]+(?::[0-9A-Za-z_.\\-]+)*$")\n'),
    Edit("parse-origin-key",
         "    m = CODE.match(q)\n    if not m:\n        return None\n",
         replace=("    m = CODE.match(q)\n"
                  "    if not m:\n"
                  "        k = str(query or \"\").strip()   # [s3-account-keys] a record / wall clip / live set\n"
                  "        return {\"prefix\": k, \"punct\": \"\", \"exact\": True} if ORIGIN_KEY.match(k) else None\n")),
    Edit("matches-exact",
         "def matches(line_id: str, want: dict[str, Any]) -> bool:\n",
         "    if want.get(\"exact\"):                 # [s3-account-keys] an origin key names one item\n"
         "        return str(line_id or \"\") == want[\"prefix\"]\n"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, MARKER))
