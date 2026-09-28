"""[s3-live-event] The stored-config test learns the event defaults
(tests/test_system3_rounds.py).

test_a_stored_config_gains_the_tables_it_predates_once pins the exact
list a predating config gains. The six MX Live tables now reach the live
config the same way (add_missing_default_tables offers
default_event_tables() too - they stay out of default_config(), whose
hash is pinned), and load() then writes the STATION_EVENTS marker; the
expectation grows by exactly that. Nothing else in the module changes.

  python edit_mxlive_rounds_test.py [--check|--apply] tests/test_system3_rounds.py

Marker-idempotent (marker: [s3-live-event]).
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = ('        added = [t["id"] for t in system3_tables.default_tables() if t["family"] not in ("CTS", "ES", "RS", "IRS", "FL")]\n'
       '        self.assertEqual(ids[-len(added):], added)\n'
       '        self.assertEqual(rt.config["defaults_added"], sorted(added))\n')
NEW = ('        added = [t["id"] for t in system3_tables.default_tables() if t["family"] not in ("CTS", "ES", "RS", "IRS", "FL")]\n'
       '        added = added + [t["id"] for t in system3_tables.default_event_tables()]   # [s3-live-event]\n'
       '        self.assertEqual(ids[-len(added):], added)\n'
       '        self.assertEqual(rt.config["defaults_added"],\n'
       '                         sorted(added + [rt.EVENTS_MARK]))          # [s3-live-event]\n')


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "tests/test_system3_rounds.py")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    if NEW in text:
        print("already applied")
        return 2
    if text.count(OLD) != 1:
        print("missing: the expectation block (found %d times)" % text.count(OLD))
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
