#!/usr/bin/env python3
"""[book-opening] Book Time's opening may have both hosts welcome the listener. 2026-10-05, #1588.

"Investigate the book segments and why the dialogue isnt being made for them.
I need these made and generated hourly."

What was found on 10-05. Book Time is scheduled at :15 and :45 of every hour
and the dialogue for it IS written - 27 parts sat on the shelf. Every one of
them had been turned away, and each occurrence then stood "blocked: Book Time
phase failed after three bounded attempts", so nothing was ever recorded for
the road and the hour sheet read "nothing written for this road yet".

26 of the 27 were turned away by one count. The opening part is asked to have
"both hosts introduce themselves and welcome listeners to Book Time", and the
check on it demanded EXACTLY ONE "welcome ... Book Time" in the part. The
writers did what they were asked: the host welcomes, the co-host welcomes too.
Two welcomes, turned away. The retry was told to fix "one actual welcome",
wrote the same natural opening, and was turned away again - three times, then
blocked. The check contradicted its own brief.

Three changes, all in the place that owns the decision (phase_error and
prepare_book in dynamic_segments_runtime.py):

  the rule      an opening needs a welcome by title and station and must not
                close. How many hosts say the word "welcome" is not a fault.
                One welcome per EPISODE still holds: a second opening part is
                still turned away, as is a welcome inside a discussion.
  second look   a part the old rule turned away and the rule now accepts goes
                back on the shelf for its episode, and the other attempts at
                that phase are marked as answered by it - so an occurrence
                that stood blocked carries on from its own first opening
                instead of waiting for the next hour.
  the ledger    a part that IS turned away is written to the rejection ledger
                (gate round:book_phase), where every other refusal already is.

Usage:  book_time_opening_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        book_time_opening_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RULE_OLD = '''        if phase == 'opening':
            if intro != 1 or not evidence['intro']['written'] or outro:
                return 'Opening must contain one actual title/station welcome and no closing'
'''
RULE_NEW = '''        if phase == 'opening':
            # [book-opening] The brief asks BOTH hosts to welcome the listener, and
            # they do: host, then co-host. Counting that as a fault (intro != 1)
            # turned away 26 of 27 written openings on 10-05 and blocked every
            # episode. One welcome per episode is kept below, by `prior`.
            if intro < 1 or not evidence['intro']['written'] or outro:
                return 'Opening must welcome listeners to Book Time by title and station, and must not close'
'''

LOOK_OLD = '''            rows = kept
            rejected = [self.source_entry(row) for row in self.g.get('_LARDER', [])
                if self.source_entry(row).get('dynamic_occurrence') == occurrence
                and self.source_entry(row).get('dynamic_phase_rejected')]
'''
LOOK_NEW = '''            rows = kept
            if self.readmit_phases(occurrence, rows):      # [book-opening] a second look
                self.call('_larder_save')
                self.coverage_cache.clear()
                rows = self.book_rows(occurrence)
            rejected = [self.source_entry(row) for row in self.g.get('_LARDER', [])
                if self.source_entry(row).get('dynamic_occurrence') == occurrence
                and self.source_entry(row).get('dynamic_phase_rejected')]
'''

REJECT_OLD = '''    def reject_phase(self, row, why):
        entry = self.source_entry(row)
        entry.update(dynamic_superseded=True, dynamic_phase_rejected={'why': why,
            'phase': entry.get('book_phase'), 'at': time.time()},
            handoff_unavailable={'why': 'Book Time phase rejected: ' + why, 'at': time.time()})
        entry.setdefault('dynamic_rejection_id', str(entry.get('sid') or '') or uuid.uuid4().hex)
'''
REJECT_NEW = REJECT_OLD + '''        # [book-opening] every refusal is in the one ledger, where it can be seen
        ledger = self.g.get('FLOW_LEDGER')
        if ledger is not None:
            try:
                ledger.note('round:book_phase', str(entry.get('book_phase') or '') + ': ' + str(why), passed=False,
                            road='banter', text=str(entry.get('script') or entry.get('script_plain') or ''),
                            ref=str(entry.get('sid') or entry.get('dynamic_rejection_id') or ''))
            except Exception:   # noqa: BLE001 - a ledger that cannot write never stops the episode
                pass

    def readmit_phases(self, occurrence, rows):
        """[book-opening] A SECOND LOOK AT WHAT AN EARLIER RULE TURNED AWAY.

        A part stays on the shelf when it is turned away, and three of them
        block the occurrence. When the rule that turned them away changes,
        those parts are still there and still good, and the occurrence is
        still blocked - until the next hour writes a new one. So each retained
        part of this occurrence is read again under the rule as it stands. One
        that passes goes back into its episode; the other attempts at the same
        phase are marked as answered by it, which is what unblocks the
        occurrence. A part that still fails stays exactly as it was.
        Returns how many came back."""
        back = 0
        for row in list(self.g.get('_LARDER') or []):
            entry = self.source_entry(row)
            verdict = entry.get('dynamic_phase_rejected')
            if (entry.get('dynamic_kind') != 'book_time' or entry.get('dynamic_occurrence') != occurrence
                    or not isinstance(verdict, dict) or entry.get('phase_repaired_by')
                    or entry.get('dynamic_handed_off') or entry.get('dynamic_source_rejected')):
                continue
            if self.phase_error(row, rows):
                continue
            entry.pop('dynamic_phase_rejected', None)
            entry.pop('dynamic_superseded', None)
            held = entry.get('handoff_unavailable')
            if isinstance(held, dict) and str(held.get('why') or '').startswith('Book Time phase rejected:'):
                entry.pop('handoff_unavailable', None)
            entry['phase_readmitted'] = {'was': str(verdict.get('why') or ''), 'at': time.time()}
            rows.append(row)
            back += 1
            answered_by = str(entry.get('sid') or '') or str(entry.get('dynamic_rejection_id') or '') or uuid.uuid4().hex
            for other in list(self.g.get('_LARDER') or []):
                bad = self.source_entry(other)
                if (bad is not entry and bad.get('dynamic_occurrence') == occurrence
                        and isinstance(bad.get('dynamic_phase_rejected'), dict)
                        and bad.get('book_phase') == entry.get('book_phase') and not bad.get('phase_repaired_by')):
                    bad['phase_repaired_by'] = answered_by
            self.log('Book Time took back a part an earlier rule turned away',
                     str(entry.get('book_phase') or '') + ': ' + str(verdict.get('why') or ''))
        return back
'''

EDITS = {"dynamic_segments_runtime.py": [
    ("both hosts may welcome", RULE_OLD, RULE_NEW, "            if intro < 1 or not evidence['intro']['written'] or outro:", 1),
    ("a second look before it is blocked", LOOK_OLD, LOOK_NEW, "            if self.readmit_phases(occurrence, rows):", 1),
    ("a refusal is in the ledger; parts come back", REJECT_OLD, REJECT_NEW, "    def readmit_phases(self, occurrence, rows):", 1),
]}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        text = path.read_bytes().decode("utf-8")
        crlf = "\r\n" in text
        if crlf:
            if text.count("\r\n") != text.count("\n"):
                raise SystemExit("%s has mixed line endings; refusing to guess" % path)
            text = text.replace("\r\n", "\n")
        todo = []
        for edit in edits:
            label, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-30s %-44s %s" % (name, label, state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for label, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, label)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, label, "probe")
        if todo:
            tmp = path.with_name(path.name + ".bookopening.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
