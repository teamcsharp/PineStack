"""[s3-live-event] The block-registry test learns the event blocks
(tests/test_system3_blocks2.py).

Every marked block must be a name a System 3 node claims. The
event_facts block's node lives in EVENT_BLOCKS (it reaches the live
config's blocks registry through the runtime, never DEFAULT_BLOCKS -
default_config()'s hash is pinned), so the registry this test checks
against is DEFAULT_BLOCKS plus EVENT_BLOCKS. Nothing else changes.

  python edit_mxlive_blocks2_test.py [--check|--apply] tests/test_system3_blocks2.py

Marker-idempotent (marker: [s3-live-event]).
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = ('        self.assertEqual(sorted(n for n in marked if n not in system3_tables.DEFAULT_BLOCKS), [],\n'
       '                         "a block the station marks with no node is stripped as a wedge")\n')
NEW = ('        _known = set(system3_tables.DEFAULT_BLOCKS) | set(system3_tables.EVENT_BLOCKS)   # [s3-live-event]\n'
       '        self.assertEqual(sorted(n for n in marked if n not in _known), [],\n'
       '                         "a block the station marks with no node is stripped as a wedge")\n')


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "tests/test_system3_blocks2.py")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    if NEW in text:
        print("already applied")
        return 2
    if text.count(OLD) != 1:
        print("missing: the wedge assertion (found %d times)" % text.count(OLD))
        return 1
    if not do_apply:
        print("ready")
        return 0
    text = text.replace(OLD, NEW)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
