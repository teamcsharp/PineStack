"""[s3-live-event] MX Live rows for the wheels (system3_tables.py).

Appends the station-events region - the DEFAULT_EVENTS register, the six
MX Live tables (EVENT / CTS / TRACK_TALK / ANGLE) and the event_facts
block rule - at the end of system3_tables.py. Nothing existing changes:
DEFAULT_TABLES and DEFAULT_BLOCKS are untouched, so default_config()'s
pinned hash (tests/test_system3.py) does not move. The rows reach the
LIVE config once, through the runtime (edit_mxlive_runtime.py).

  python edit_mxlive_tables.py [--check|--apply] path/to/system3_tables.py

Marker-idempotent (marker: [s3-live-event]). --check: 0 ready, 2 applied,
1 the file is not what this script knows. Keeps LF endings.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGION = (HERE / "src" / "mxlive_tables_region.py").read_text(encoding="utf-8")

MARKER = "# --- [s3-live-event] STATION EVENTS, FIRST-CLASS IN THE WHEELS"
TAIL = "def _items(rows, **common):"


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "system3_tables.py")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text, "system3_tables.py is expected LF-only"
    if MARKER in text:
        print("already applied")
        return 2
    if TAIL not in text:
        print("missing: the _items helper the region uses")
        return 1
    if not do_apply:
        print("ready")
        return 0
    out = text.rstrip("\n") + "\n\n" + REGION.strip("\n") + "\n"
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(out.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
