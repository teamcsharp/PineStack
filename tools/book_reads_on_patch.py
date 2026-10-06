#!/usr/bin/env python3
"""[book-reads-on] Book Time reads on through its book instead of repeating its welcome. 2026-10-06.

"For book time the segment is looping as in the dialogue and the videos played for it are
the exact same thing that's happening twice. Find out why that's happening and why they
aren't reading more lines out of the book that they're reading from."

Measured on the live station (the air log, the larder, /api/dynamic-segments):
  - 74 of the larder's 76 rows were Book Time parts; 32 of them turned away by the phase
    gates: 13 openings ("must welcome listeners to Book Time by title and station"), 9
    openings where a host did not say "I'm Dill" / "I'm Skip" in the gate's exact words, 8
    closings without the sign-off the gate recognises, 2 discussions that welcomed. Three
    refusals of one phase block the episode ("Book Time phase failed after three bounded
    attempts"), so an episode seldom got past its opening - that is why the hosts never read
    on: the discussion parts were refused or written long after the window (the 13:15
    episode's discussion came at 13:49-14:11).
  - In the window the ordinary banter road and the segment's own door share one admission
    (the running order's slot), so the live banter road took the episode's recorded opening
    off the larder as a plain round (13:06:50, kind banter) and the segment handed the same
    opening over again (13:15:56): the same welcome, the same title, the same first passage,
    the same clips, twice. Then nothing, because nothing else was ready.
  - The window waited for the whole episode to be ready ("the entire segment must be ready
    before the first part claims it"), which it seldom was.

Now:
  - The gates MEND before they refuse (repair_phase): an opening without the welcome gets
    "Welcome to Book Time on <station>."; one that does not name the book gets "We are
    reading <title>."; a host who did not introduce themself gets "I'm <name>." at the head
    of their first turn; a sign-off in an opening, or a welcome in a discussion or closing,
    is struck; a closing without its sign-off gets "That is Book Time on <station>. Thank you
    for listening, and now back to the music." The gate is asked again; only a part that
    still fails is refused. The tint room's own check mends the same way.
  - Only the segment's door (dispatch -> _ready_shelf_air with a pick) may take an episode's
    parts; the live banter road in the same window no longer can (admission `dispatch`).
  - NEVER NOTHING at the window: the episode airs what it has, in order - the recorded
    opening first, then every recorded part as it lands - and an earlier episode's recorded
    parts that never aired go out before a new book is opened (book_carry), so the hosts
    read on through the book they were reading.
  - [bank-first-3] the out-of-turn larder paths (the sweep's pick and transport, the dead-air
    rescue, the lifecycle's out-of-turn rule) never take a segment's part.

Usage:  book_reads_on_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_reads_on_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# ----------------------------------------------------------------- dynamic_segments_runtime.py
IMPORT_OLD = '''import re
import uuid
import shutil
import time
'''
IMPORT_NEW = '''import re
import unicodedata
import uuid
import shutil
import time
'''

FROM_OLD = '''from segment_contract import (book_time_bookends, build_segment_contract,
                              evaluate_segment_contract, estimated_speech_seconds)
'''
FROM_NEW = '''from segment_contract import (book_time_bookends, book_title_said, build_segment_contract,
                              evaluate_segment_contract, estimated_speech_seconds)
'''

ADMIT_OLD = '''        if request.get('kind') == 'book_time':
            return stored == 'book_time' and str(entry.get('dynamic_occurrence') or '') == self.occurrence(request)
        return not stored
'''
ADMIT_NEW = '''        if request.get('kind') == 'book_time':
            # [book-reads-on] only the segment's own door (dispatch -> _ready_shelf_air with a pick) may take
            # an episode's parts. The live banter road in the same window shared this admission, took the
            # recorded opening as a plain round, and the dispatch handed it over again: one welcome, twice.
            if not request.get('dispatch'):
                return False
            mine = {self.occurrence(request), str(getattr(self, 'carry_from', '') or '')}
            return stored == 'book_time' and str(entry.get('dynamic_occurrence') or '') in mine
        return not stored
'''

WRAP_OLD = '''        def wrap(original):
            async def air(*a, **kw):
                if kw.get('bank'):
                    return await original(*a, **kw)
                request = runtime.active()
                request['named'] = bool(kw.get('named'))
                token = runtime.admission.set(request)
'''
WRAP_NEW = '''        def wrap(original, door=name):
            async def air(*a, **kw):
                if kw.get('bank'):
                    return await original(*a, **kw)
                request = runtime.active()
                request['named'] = bool(kw.get('named'))
                request['dispatch'] = door == '_ready_shelf_air' and kw.get('pick') is not None   # [book-reads-on]
                token = runtime.admission.set(request)
'''

DISPATCH_OLD = '''        if kind == 'book_time':
            rows = self.book_rows(key)
            # The entire segment must be ready before the first part claims it.
            # Once accepted, remaining parts carry their frozen source and order.
            if not self.book_coverage(due, rows)['ready'] and not self.last.get(key, {}).get('started'):
                return False
            candidates = [row for row in rows if not row.get('dynamic_handed_off')]
            candidates.sort(key=lambda row: ({'opening': 0, 'discussion': 1, 'closing': 2}.get(row.get('book_phase'), 1),
                int(row.get('chain_order') or 0), float(row.get('at') or 0)))
            if not candidates:
                return True
            def accepted():
                candidates[0]['dynamic_handed_off'] = True
                self.last.setdefault(key, {})['started'] = True
            said = await self.g['_ready_shelf_air']('banter', track, pick=candidates[0], on_handoff=accepted)
            return bool(said)
'''
DISPATCH_NEW = '''        if kind == 'book_time':
            rows = self.book_rows(key)
            started = bool(self.last.get(key, {}).get('started'))
            # [book-reads-on] NEVER NOTHING. The window waited for the whole episode to be ready, which it
            # seldom was (the gates turned most parts away; the writer ran past the window), so the window
            # aired the opening the banter road had leaked and nothing more. Now the episode airs what it HAS,
            # in order - the recorded opening first, then every recorded part as it lands - and an earlier
            # episode's recorded parts nobody heard go out before a new book is opened: the hosts read ON.
            ready = self.original.get('dialogue_row_ready') or (lambda kind, row: True)
            candidates = [row for row in rows if not row.get('dynamic_handed_off') and ready('banter', row)]
            candidates.sort(key=self.book_order)
            carry_from, carry = '', []
            if not candidates or (not started and candidates[0].get('book_phase') != 'opening'):
                carry_from, carry = self.book_carry(key)
                if carry:
                    candidates = carry
                elif not candidates:
                    return False
                else:
                    return False                             # an episode opens with its welcome
            self.carry_from = carry_from
            def accepted():
                candidates[0]['dynamic_handed_off'] = True
                self.last.setdefault(key, {})['started'] = True
                if carry_from:
                    self.last.setdefault(key, {})['carried_from'] = carry_from
            try:
                said = await self.g['_ready_shelf_air']('banter', track, pick=candidates[0], on_handoff=accepted)
            finally:
                self.carry_from = ''
            return bool(said)
'''

STRUCT_OLD = '''    def book_structure(self, rows):
        valid, errors = [], []
'''
STRUCT_NEW = '''    WELCOME_RX = re.compile(r"\\bwelcome\\b.{0,80}\\bbook time\\b")
    SIGNOFF_RX = re.compile(r"(?:\\b(?:thank|thanks|thank you)\\b.{0,100}\\bbook time\\b|"
                            r"\\b(?:that ends|that wraps|that's|that is|end of)\\b.{0,70}\\bbook time\\b)")

    @staticmethod
    def _plain(text):
        return ' '.join(unicodedata.normalize('NFKC', str(text or '')).replace('\\u2019', "'").casefold().split())

    @staticmethod
    def book_order(row):
        return ({'opening': 0, 'discussion': 1, 'closing': 2}.get(row.get('book_phase'), 1),
                int(row.get('chain_order') or 0), float(row.get('at') or 0))

    def book_carry(self, key):
        """[book-reads-on] The latest other episode that still holds recorded parts nobody heard: its
        occurrence and those parts, in order - so a window with nothing of its own reads on."""
        ready = self.original.get('dialogue_row_ready') or (lambda kind, row: True)
        best, best_at, best_rows = '', -1.0, []
        seen = set()
        for row in list(self.g.get('_LARDER') or []):
            entry = self.source_entry(row)
            occurrence = str(entry.get('dynamic_occurrence') or '')
            if entry.get('dynamic_kind') != 'book_time' or not occurrence or occurrence == key or occurrence in seen:
                continue
            seen.add(occurrence)
            try:
                at = float(occurrence.rsplit('@', 1)[-1])
            except (TypeError, ValueError):
                at = 0.0
            if at <= best_at:
                continue
            rows = [r for r in self.book_rows(occurrence) if not r.get('dynamic_handed_off') and ready('banter', r)]
            if rows:
                best, best_at, best_rows = occurrence, at, sorted(rows, key=self.book_order)
        return best, best_rows

    def repair_phase(self, row, prior=()):
        """[book-reads-on] MEND BEFORE REFUSING. The gates turned away 32 of 74 parts in a morning for
        wording - a welcome without the station's name, a host who said "here's Dill" instead of "I'm
        Dill", a closing whose sign-off the regex did not know - and three refusals block the episode.
        What the gate wants is said by construction: the welcome, the title, each host's name, the
        sign-off; what it forbids is struck. The gate is asked again afterwards; a part that still
        fails is refused as before. Returns what was mended, or '' when nothing was."""
        entry = self.source_entry(row)
        phase = str(entry.get('book_phase') or '')
        script = str(entry.get('script') or entry.get('script_plain') or '')
        turns = [[str(seat), ' '.join(str(text).split())]
                 for seat, text in (self.call('banter_turns', script, default=[]) or [])]
        if not turns or phase not in ('opening', 'discussion', 'closing'):
            return ''
        station = str(entry.get('book_station') or self.station() or '').strip()
        title = str((entry.get('book_source') or {}).get('title') or '')
        lead = re.split(r"\\s+--\\s+|\\s+-\\s+|:\\s+|;\\s+|\\s+[(\\[]", title.strip(), maxsplit=1)[0].strip(' .,;:-') if title else ''
        fixes = []

        def strike(pattern, label):
            for turn in turns:
                pieces = [s for s in re.split(r'(?<=[.!?])\\s+', turn[1]) if s]
                kept = [s for s in pieces if not pattern.search(self._plain(s))]
                if len(kept) != len(pieces):
                    turn[1] = ' '.join(kept)
                    if label not in fixes:
                        fixes.append(label)

        if phase == 'opening':
            strike(self.SIGNOFF_RX, 'a sign-off struck from the opening')
            words = self._plain(' '.join(t[1] for t in turns))
            if not self.WELCOME_RX.search(words) or (station and self._plain(station) not in words):
                turns[0][1] = ('Welcome to Book Time on %s. ' % station if station else 'Welcome to Book Time. ') + turns[0][1]
                fixes.append('the welcome')
            words = self._plain(' '.join(t[1] for t in turns))
            if lead and not book_title_said(title, words):
                turns[0][1] = turns[0][1].rstrip() + ' We are reading %s.' % lead
                fixes.append('the title')
            cast = self.host_cast(row)
            for seat in ('A', 'B'):
                name = str(cast.get(seat) or '').strip()
                own = next((t for t in turns if t[0] == seat), None)
                if not name or own is None:
                    continue
                said = re.compile(r"\\b(?:i(?:'m| am)|my name is|this is|it(?:'s| is))\\s+" + re.escape(name.casefold())
                                  + r"(?!\\w)|(?<!\\w)" + re.escape(name.casefold()) + r"\\s+(?:here|at the mic|speaking)\\b")
                if not any(t[0] == seat and said.search(self._plain(t[1])) for t in turns):
                    own[1] = ("I'm %s. " % name if seat == 'A' else "And I'm %s. " % name) + own[1]
                    fixes.append('%s introduces %s' % (seat, name))
        elif phase == 'discussion':
            strike(self.WELCOME_RX, 'a welcome struck from the discussion')
            strike(self.SIGNOFF_RX, 'a sign-off struck from the discussion')
        else:
            strike(self.WELCOME_RX, 'a welcome struck from the closing')
            evidence = book_time_bookends('\\n'.join(t[1] for t in turns), station=station)
            if not evidence['outro']['written']:
                turns[-1][1] = turns[-1][1].rstrip() + (
                    ' That is Book Time on %s. Thank you for listening, and now back to the music.' % station
                    if station else ' That is Book Time. Thank you for listening, and now back to the music.')
                fixes.append('the sign-off')
        if not fixes:
            return ''
        mended = '\\n'.join('%s: %s' % (seat, text) for seat, text in turns if text.strip())
        for holder in (row, entry):
            for field in ('script', 'script_plain', 'script_tinted'):
                if isinstance(holder, dict) and holder.get(field):
                    holder[field] = mended
        entry['book_phase_repaired'] = {'fixes': list(fixes), 'phase': phase, 'at': time.time()}
        ledger = self.g.get('FLOW_LEDGER')
        if ledger is not None:
            try:
                ledger.note('round:book_phase_repair', phase + ': ' + ', '.join(fixes), passed=True,
                            road='banter', text=mended, ref=str(entry.get('sid') or ''))
            except Exception:   # noqa: BLE001 - a ledger that cannot write never stops the episode
                pass
        return ', '.join(fixes)

    def book_structure(self, rows):
        valid, errors = [], []
'''

ACCEPT_OLD = '''            accepted = []
            for row in new:
                self.tag(row, contract)
                why = self.phase_error(row, rows + accepted)
                if why:
                    self.reject_phase(row, why)
                else:
'''
ACCEPT_NEW = '''            accepted = []
            for row in new:
                self.tag(row, contract)
                why = self.phase_error(row, rows + accepted)
                if why and self.repair_phase(row, rows + accepted):             # [book-reads-on] mend before refusing
                    why = self.phase_error(row, rows + accepted)
                if why:
                    self.reject_phase(row, why)
                else:
'''

TINT_OLD = '''            if result and runtime.source_entry(entry).get('dynamic_kind') == 'book_time':
                why = runtime.phase_error(entry)
                if why:
'''
TINT_NEW = '''            if result and runtime.source_entry(entry).get('dynamic_kind') == 'book_time':
                why = runtime.phase_error(entry)
                if why and runtime.repair_phase(entry):                     # [book-reads-on] the tint may have cut the welcome
                    why = runtime.phase_error(entry)
                if why:
'''

# ----------------------------------------------------------------- app.py  [bank-first-3]
OLDEST_OLD = '''    for e in _LARDER:
        if not isinstance(e, dict) or id(e) in _READY_SHELF_BUSY or not row_unaired(e):
            continue
        if not dialogue_row_ready("banter", e):
            continue
        waited = now - float(e.get("at") or now)
'''
OLDEST_NEW = '''    for e in _LARDER:
        if not isinstance(e, dict) or id(e) in _READY_SHELF_BUSY or not row_unaired(e):
            continue
        if (dialogue_entry(e) or e).get("dynamic_kind"):                  # [bank-first-3] a segment's part airs through its segment
            continue
        if not dialogue_row_ready("banter", e):
            continue
        waited = now - float(e.get("at") or now)
'''

PICK_OLD = '''            for row in road_source(kind):                      # [bank-first] the larder is banter's shelf
                if not isinstance(row, dict) or not row_unaired(row):
                    continue
'''
PICK_NEW = '''            for row in road_source(kind):                      # [bank-first] the larder is banter's shelf
                if not isinstance(row, dict) or not row_unaired(row):
                    continue
                if (dialogue_entry(row) or row).get("dynamic_kind"):      # [bank-first-3] never a segment's part
                    continue
'''

AIR_OLD = '''    try:
        at = next(i for i, e in enumerate(_LARDER) if e is entry)
    except StopIteration:
        return _banter_no("the larder round left the shelf before it could air")
'''
AIR_NEW = '''    try:
        at = next(i for i, e in enumerate(_LARDER) if e is entry)
    except StopIteration:
        return _banter_no("the larder round left the shelf before it could air")
    if (dialogue_entry(entry) or entry).get("dynamic_kind"):              # [bank-first-3]
        return _banter_no("a segment's part airs only through its segment")
'''

STOCK_OLD = '''            rows = [r for r in road_source(kind)
                    if id(r) not in _READY_SHELF_BUSY
                    and _ready_round_takes(kind, r)]
'''
STOCK_NEW = '''            rows = [r for r in road_source(kind)
                    if id(r) not in _READY_SHELF_BUSY
                    and not (dialogue_entry(r) or r).get("dynamic_kind")   # [bank-first-3]
                    and _ready_round_takes(kind, r)]
'''

# ----------------------------------------------------------------- pantry_lifecycle.py
LIFE_OLD = '''            if int(row.get("aired") or 0) > 0 or float(row.get("aired_at") or 0) > 0: return False
            after = float(self.call("cupboard_unheard_after", default=7200) or 7200)
'''
LIFE_NEW = '''            if int(row.get("aired") or 0) > 0 or float(row.get("aired_at") or 0) > 0: return False
            if entry_of(row).get("dynamic_kind"): return False          # [bank-first-3] a segment's part airs through its segment
            after = float(self.call("cupboard_unheard_after", default=7200) or 7200)
'''

EDITS = {
    "dynamic_segments_runtime.py": [
        ("import unicodedata", IMPORT_OLD, IMPORT_NEW, 1),
        ("book_title_said joins the imports", FROM_OLD, FROM_NEW, 1),
        ("only the segment's door takes its parts", ADMIT_OLD, ADMIT_NEW, 1),
        ("the door says it is the dispatch", WRAP_OLD, WRAP_NEW, 1),
        ("the window airs what it has, in order, and reads on", DISPATCH_OLD, DISPATCH_NEW, 1),
        ("book_order, book_carry, repair_phase", STRUCT_OLD, STRUCT_NEW, 1),
        ("mend before refusing (the writer's parts)", ACCEPT_OLD, ACCEPT_NEW, 1),
        ("mend before refusing (after the tint)", TINT_OLD, TINT_NEW, 1),
    ],
    "app.py": [
        ("the rescue's oldest larder round is never a segment's part", OLDEST_OLD, OLDEST_NEW, 1),
        ("the sweep's pick is never a segment's part", PICK_OLD, PICK_NEW, 1),
        ("the larder transport refuses a segment's part", AIR_OLD, AIR_NEW, 1),
        ("dead_air_stock counts no segment part", STOCK_OLD, STOCK_NEW, 1),
    ],
    "pantry_lifecycle.py": [
        ("the lifecycle's out-of-turn rule skips a segment's part", LIFE_OLD, LIFE_NEW, 1),
    ],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s MISSING FILE" % name)
            missing = True
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, want in edits:
            if text.count(new) >= want:
                print("%-72s applied" % label[:72])
                continue
            n = text.count(old)
            if n == want:
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-72s MISSING (anchor count %d, wanted %d)" % (label[:72], n, want))
                missing = True
        if changed:
            plans.append((path, text, mode, bom))
    if missing:
        print("anchors missing - nothing applied")
        return 1
    if not ready:
        print("every edit reads applied")
        return 2
    if argv[1] == "--check":
        print("ready to apply")
        return 0
    for path, text, mode, bom in plans:
        out = text.replace("\n", "\r\n") if mode == "crlf" else text
        data = out.encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = path.with_suffix(path.suffix + ".bookreads.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
