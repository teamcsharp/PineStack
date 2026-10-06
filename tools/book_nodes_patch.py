#!/usr/bin/env python3
"""[book-nodes] Book Time is System 3 nodes, not gates: three roads, a BOOK family, no refusals. 2026-10-06.

"When it comes to handling the booktime discussion I dont want wedges or gates. I want the
node configuration altered to have them able to do more book work. Basically the point of
system 3 is to perfect and refine the roulette system to give us the intended results by
creating nodes and offerings rolling randomly through the options we need to roll between
to create a rich and robust experience."

Before: every Book Time part was a plain banter round (road 'banter') with the phase's
wishes in the brief, then a regex gate decided whether the welcome, the names, the title or
the sign-off were there - and this afternoon's [book-reads-on] mended what the gate would
have refused. The hosts never had nodes that SAID "read the next passage word for word".

Now the nodes do the book work:
  - three roads with their own legs (system3_tables.DEFAULT_ROAD_STRUCTURES): book_open
    (the welcome with the names, the other host, the first reading, the first take),
    book_read (a reading, the take, the errand, reading on, the turn), book_close (the last
    line, the takeaway, the sign-off that hands back to the music). The reading legs carry
    the passage itself - {booksentences} / {booksentence} - which the book prompt stage
    fills at the model wire, as it fills the brief.
  - a BOOK family of offerings the roulette rolls per turn: BK1 the manner a passage is
    read in, BK2 the angle the other host takes on it, BK3 the errand done with the book in
    hand. Printed on the running-order row like the supercut stance ("the book work: ...").
  - the phase checks (phase_error) are observations now: noted on the part and in the flow
    ledger (round:book_phase_note, passed), never a refusal, never a block, never a mend;
    repair_phase is gone; the three-bounded-attempts block is gone; which phase comes next
    is the node's identity (book_phase), not a regex reading of the words.
  - prepare_book writes each phase on its own road (BOOK_ROADS), so the writer plans the
    legs instead of guessing from the brief.

The default config's hash moves (new tables and structures); the two System 3 tests that pin
it are updated by book_nodes_hash_patch.py once the hash is read from the container.

Usage:  book_nodes_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_patch.py --apply [ROOT]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ----------------------------------------------------------------- system3_tables.py
TABLES_OLD = '''DEFAULT_TABLES.append(REACT1)                                                # [supercut-react]
'''
TABLES_NEW = '''DEFAULT_TABLES.append(REACT1)                                                # [supercut-react]

# --- [book-nodes] THE BOOK WORK: what a host does with the book in hand, rolled per turn ---
# "the node configuration altered to have them able to do more book work" - three offerings
# the Book Time roads roll: how a passage is read (BK1), the angle the other host takes on it
# (BK2), and the errand done with the book (BK3). Rolled, never gated: whatever comes up is read.
BK1 = {
    "id": "BK1", "family": "BOOK", "label": "Reading manner (how the passage is read)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "The manner a host reads the next passage of the book in, rolled on the reading legs of the "
                   "book_open, book_read and book_close roads. The words are the book's; the manner is the wheel's.",
    "categories": [
        {"id": "manner", "label": "Manner", "weight": 1.0,
         "items": _items([
             {"id": "plain", "label": "Plain", "weight": 1.0,
              "text": "reads it plain - every word as written, no flourish, and stops where the passage stops"},
             {"id": "slow", "label": "Slowly", "weight": 0.9,
              "text": "reads it slowly, savouring the words, a breath between the sentences"},
             {"id": "narrator", "label": "As the narrator", "weight": 0.8,
              "text": "reads it as the book's own narrator would, in the book's voice, not the host's"},
             {"id": "warning", "label": "As a warning", "weight": 0.7,
              "text": "reads it as a warning to the city - every sentence pointed at somebody listening"},
             {"id": "comedy", "label": "As the joke the author missed", "weight": 0.7,
              "text": "reads it as if the author meant it as a joke and only the reader has noticed"},
             {"id": "twice", "label": "Twice", "weight": 0.6,
              "text": "reads it once, then reads the one sentence that matters a second time, slower"},
             {"id": "dare", "label": "As a dare", "weight": 0.6,
              "text": "reads it as a dare, as though the listener will not believe a word of it"},
         ])},
    ],
}
BK2 = {
    "id": "BK2", "family": "BOOK", "label": "The listener's angle (what the other host takes from it)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "What the other host pulls out of the passage just read, rolled on the take legs of the book "
                   "roads: one angle per turn, so no two takes on the same page come out the same.",
    "categories": [
        {"id": "angle", "label": "Angle", "weight": 1.0,
         "items": _items([
             {"id": "word", "label": "The one word", "weight": 1.0,
              "text": "names the one word in the passage that matters and says why it is that word"},
             {"id": "street", "label": "This street tonight", "weight": 1.0,
              "text": "says what the passage would mean on this street tonight, to somebody listening"},
             {"id": "who", "label": "Who it is about", "weight": 0.9,
              "text": "says who in the city the passage is really about, by name or by job"},
             {"id": "unsaid", "label": "The unsaid thing", "weight": 0.8,
              "text": "names the thing the author is not saying out loud in that passage"},
             {"id": "lasttime", "label": "Last time", "weight": 0.7,
              "text": "says how the passage fits what was read last time Book Time was on"},
             {"id": "callin", "label": "A question for the listener", "weight": 0.8,
              "text": "puts one question from the passage to the listener, to ring in and answer"},
             {"id": "wrong", "label": "Where the author is wrong", "weight": 0.7,
              "text": "says flatly where the author has it wrong, and what the page should have said"},
             {"id": "personal", "label": "The true thing", "weight": 0.6,
              "text": "names the one thing in the passage that is true of them, and admits it"},
         ])},
    ],
}
BK3 = {
    "id": "BK3", "family": "BOOK", "label": "The errand (what is done with the book in hand)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "The errand a host runs with the book in hand on the errand leg of the book_read road - the "
                   "thing that keeps a reading round moving through the pages rather than circling one line.",
    "categories": [
        {"id": "errand", "label": "Errand", "weight": 1.0,
         "items": _items([
             {"id": "next", "label": "Reads the next sentences", "weight": 1.2,
              "text": "reads the next sentences of the book word for word and says where they are on the page"},
             {"id": "page", "label": "Names the page", "weight": 0.7,
              "text": "names the page and the chapter they are on and why they stopped there"},
             {"id": "ask", "label": "Hands the book over", "weight": 0.9,
              "text": "hands the book to the other host and asks them to read the next bit out loud"},
             {"id": "disagree", "label": "Disagrees", "weight": 0.8,
              "text": "disagrees with the author in one breath, quoting the words they disagree with"},
             {"id": "funniest", "label": "The funniest line", "weight": 0.8,
              "text": "finds the funniest line on the page and reads it, deadpan"},
             {"id": "sumup", "label": "Sums the chapter up", "weight": 0.7,
              "text": "sums the chapter up in one breath for anybody who just tuned in"},
             {"id": "reread", "label": "Re-reads it differently", "weight": 0.6,
              "text": "re-reads the sentence that was just read, in a different voice, to hear it again"},
             {"id": "predict", "label": "Predicts the page", "weight": 0.6,
              "text": "predicts what the next page says, then reads it to check"},
         ])},
    ],
}
DEFAULT_TABLES.append(BK1)                                                   # [book-nodes]
DEFAULT_TABLES.append(BK2)                                                   # [book-nodes]
DEFAULT_TABLES.append(BK3)                                                   # [book-nodes]
'''

REGISTER_OLD = '''    {"id": "ad_spot", "label": "Produced advert", "shape": "line",
'''
REGISTER_NEW = '''    # [book-nodes] Book Time is three roads of its own: the nodes do the book work, nothing gates it
    {"id": "book_open", "label": "Book Time: the opening", "shape": "legs",
     "writer": "dynamic_segments_runtime.prepare_book (phase opening) -> dj_banter", "hook": "system3_direct_banter",
     "what": "both hosts welcome the listener to Book Time on the station by name, name the book and the chapter, "
             "and the first passage is read word for word - the manner a BK1 roll, the first take a BK2 roll"},
    {"id": "book_read", "label": "Book Time: a reading", "shape": "legs",
     "writer": "dynamic_segments_runtime.prepare_book (phase discussion) -> dj_banter", "hook": "system3_direct_banter",
     "what": "a reading round: the next passages read word for word (BK1), the takes from the angle rolled (BK2), "
             "the errand rolled with the book in hand (BK3), reading on"},
    {"id": "book_close", "label": "Book Time: the close", "shape": "legs",
     "writer": "dynamic_segments_runtime.prepare_book (phase closing) -> dj_banter", "hook": "system3_direct_banter",
     "what": "the last sentence of the book read, each host's takeaway, and the sign-off that thanks the listener "
             "for Book Time and hands back to the music"},
    {"id": "ad_spot", "label": "Produced advert", "shape": "line",
'''

STRUCT_OLD = '''    "supercut_react": _legs_structure("supercut_react", "Supercut reaction", 3, 5, [   # [supercut-react]
'''
STRUCT_NEW = '''    # [book-nodes] BOOK TIME, AS NODES. The reading legs carry the passage itself ({booksentences},
    # {booksentence}), filled at the model wire by the book prompt stage like the brief; the manner, the
    # angle and the errand are BOOK rolls. Nothing here is checked afterwards: what the wheel and the
    # writer make is what airs.
    "book_open": _legs_structure("book_open", "Book Time: the opening", 4, 6, [
        _leg("hello_a", "The welcome", "open", "A",
             "WELCOMES the listener to Book Time on {stationname} and says their own name - I'm, and the name - "
             "then names the book, {book}, and the chapter being read tonight, {bookchapter}", "ES"),
        _leg("hello_b", "The other host", "middle", "B",
             "says their own name the same way, welcomes the listener too, and says in one line what pulled "
             "them into this book tonight", "ES", "RS"),
        _leg("first_read", "The first reading", "middle", "A",
             "READS the first passage word for word, exactly as the book has it - {booksentences} - in the "
             "manner rolled, and stops where it stops", "ES", "BOOK"),
        _leg("first_take", "The first take", "close", "B",
             "answers what was just read from the angle rolled: one line on the passage, then what they want "
             "read next", "ES", "RS", "BOOK"),
    ], "BOOK TIME OPENING"),
    "book_read": _legs_structure("book_read", "Book Time: a reading", 6, 10, [
        _leg("read", "A reading", "open", "A",
             "READS the next passage of {book} word for word - {booksentences} - in the manner rolled, naming "
             "the page or the chapter once, and stops where it stops", "ES", "BOOK"),
        _leg("take", "The take", "middle", "alternate",
             "answers the passage from the angle rolled: one line about what it said, then a question or a "
             "dare to the other host about it", "ES", "RS", "BOOK"),
        _leg("errand", "The errand", "middle", "alternate",
             "does the errand rolled with the book in hand, in the feeling rolled", "ES", "BOOK"),
        _leg("read_on", "Reading on", "middle", "alternate",
             "reads on: the next sentences of the book, word for word - {booksentence} - in the manner rolled",
             "ES", "BOOK"),
        _leg("turn", "The turn", "close", "alternate",
             "says what the reading leaves them with, in the feeling rolled, and which part they want read "
             "when Book Time comes back", "ES", "RS"),
    ], "BOOK TIME READING"),
    "book_close": _legs_structure("book_close", "Book Time: the close", 3, 5, [
        _leg("last_read", "The last line", "open", "A",
             "reads one last sentence of {book} word for word - {booksentence} - and says what it leaves "
             "them with", "ES", "BOOK"),
        _leg("takeaway", "The takeaway", "middle", "B",
             "their takeaway from tonight's reading, in the feeling rolled, in two lines at most", "ES", "RS"),
        _leg("signoff", "The sign-off", "close", "alternate",
             "THANKS the listener for Book Time on {stationname}, names {book} once more, and hands back to "
             "the music", "ES", "FL2close"),
    ], "BOOK TIME CLOSE"),
    "supercut_react": _legs_structure("supercut_react", "Supercut reaction", 3, 5, [   # [supercut-react]
'''

VALID_OLD = '''            if not isinstance(d, dict) or d.get("family") not in ("ES", "RS", "IRS", "FL", "CTS", "REACT"):   # [supercut-react]
'''
VALID_NEW = '''            if not isinstance(d, dict) or d.get("family") not in ("ES", "RS", "IRS", "FL", "CTS", "REACT", "BOOK"):   # [supercut-react] [book-nodes]
'''

# ----------------------------------------------------------------- system3.py
FAM_OLD = '''FAMILIES = FAMILIES + ("REACT",)                                              # [supercut-react] the booth's stance
ROADS = ROADS + ("supercut_react",)                                           # [supercut-react] the road
'''
FAM_NEW = '''FAMILIES = FAMILIES + ("REACT",)                                              # [supercut-react] the booth's stance
ROADS = ROADS + ("supercut_react",)                                           # [supercut-react] the road
FAMILIES = FAMILIES + ("BOOK",)                                               # [book-nodes] the book work: manner, angle, errand
ROADS = ROADS + ("book_open", "book_read", "book_close")                      # [book-nodes] Book Time's own roads
'''

DIR_OLD = '''        react = [x["text"] for x in t.get("directions") or [] if x["family"] == "REACT"]   # [supercut-react]
        if react:
            add += "; the stance: " + react[-1]
'''
DIR_NEW = '''        react = [x["text"] for x in t.get("directions") or [] if x["family"] == "REACT"]   # [supercut-react]
        if react:
            add += "; the stance: " + react[-1]
        book = [x["text"] for x in t.get("directions") or [] if x["family"] == "BOOK"]     # [book-nodes]
        if book:
            add += "; the book work: " + book[-1]
'''

# ----------------------------------------------------------------- frontend/system3.js
WHAT_OLD = '''  REACT: ['Supercut stance (REACT1)',
'''
WHAT_NEW = '''  BOOK: ['Book work (BK1 manner, BK2 angle, BK3 errand)',
    'What a host does with the book in hand on the Book Time roads (book_open, book_read, book_close): the manner the next passage is read in, the angle the other host takes on it, and the errand run with the book - rolled per turn, never gated.'],
  REACT: ['Supercut stance (REACT1)',
'''
TF_OLD = '''    'MGRTOPIC', 'MGRSUB', 'REACT'];   /* [s3-sb-end] SBEND1 - [s3-mgrtopics] the manager's topics and sub messages - [supercut-react] REACT1 */
'''
TF_NEW = '''    'MGRTOPIC', 'MGRSUB', 'REACT', 'BOOK'];   /* [s3-sb-end] SBEND1 - [s3-mgrtopics] the manager's topics and sub messages - [supercut-react] REACT1 - [book-nodes] BK1-BK3 */
'''

# ----------------------------------------------------------------- dynamic_segments_runtime.py
ROADS_OLD = '''from segment_contract import (book_time_bookends, book_title_said, build_segment_contract,
                              evaluate_segment_contract, estimated_speech_seconds)
'''
ROADS_NEW = '''from segment_contract import (book_time_bookends, book_title_said, build_segment_contract,
                              evaluate_segment_contract, estimated_speech_seconds)

# [book-nodes] each phase is written on its own System 3 road, whose legs do the book work
BOOK_ROADS = {'opening': 'book_open', 'discussion': 'book_read', 'closing': 'book_close'}
'''

ROAD_OLD = '''                angle=brief, own_material=True, road='banter', lines=max(8, math.ceil(chunk / 15)))
'''
ROAD_NEW = '''                angle=brief, own_material=True, road=BOOK_ROADS.get(phase, 'book_read'),   # [book-nodes]
                lines=max(8, math.ceil(chunk / 15)))
'''

ACCEPT_OLD = '''                why = self.phase_error(row, rows + accepted)
                if why and self.repair_phase(row, rows + accepted):             # [book-reads-on] mend before refusing
                    why = self.phase_error(row, rows + accepted)
                if why:
                    self.reject_phase(row, why)
                else:
                    accepted.append(row)
                    if phase_retry:
                        row['phase_replaces'] = phase_retry['dynamic_rejection_id']
                        for bad in rejected:
                            if bad.get('book_phase') == phase_retry.get('book_phase') and not bad.get('phase_repaired_by'):
                                bad['phase_repaired_by'] = str(row.get('sid') or '') or uuid.uuid4().hex
'''
ACCEPT_NEW = '''                why = self.phase_error(row, rows + accepted)
                if why:
                    self.note_phase(row, why)                      # [book-nodes] an observation; the part stands
                accepted.append(row)
                if phase_retry:
                    row['phase_replaces'] = phase_retry['dynamic_rejection_id']
                    for bad in rejected:
                        if bad.get('book_phase') == phase_retry.get('book_phase') and not bad.get('phase_repaired_by'):
                            bad['phase_repaired_by'] = str(row.get('sid') or '') or uuid.uuid4().hex
'''

BLOCK_OLD = '''            phase_retry = next((row for row in rejected if not row.get('phase_repaired_by')), None)
            if phase_retry and sum(row.get('book_phase') == phase_retry.get('book_phase') for row in rejected) >= 3:
                self.last[occurrence] = {'state': 'blocked', 'why': 'Book Time phase failed after three bounded attempts',
                    'phase': phase_retry.get('book_phase'), 'coverage': self.book_coverage(due, rows)}
                return False
'''
BLOCK_NEW = '''            phase_retry = next((row for row in rejected if not row.get('phase_repaired_by')), None)
            # [book-nodes] no gate: a written part is never refused now, so nothing blocks an episode; a
            # refusal from before this change is re-asked once through the retry below and then left alone.
'''

INTRO_OLD = '''            has_intro = any(self.supply(row)['bookends']['intro']['written'] for row in rows)
            has_outro = any(self.supply(row)['bookends']['outro']['written'] for row in rows)
'''
INTRO_NEW = '''            has_intro = any(row.get('book_phase') == 'opening' for row in rows)     # [book-nodes] the node is the fact
            has_outro = any(row.get('book_phase') == 'closing' for row in rows)
'''

TINT_OLD = '''                why = runtime.phase_error(entry)
                if why and runtime.repair_phase(entry):                     # [book-reads-on] the tint may have cut the welcome
                    why = runtime.phase_error(entry)
                if why:
                    runtime.reject_phase(entry, why)
                    runtime.coverage_cache.clear()
                    runtime.call('_larder_save')
                    return False
'''
TINT_NEW = '''                why = runtime.phase_error(entry)
                if why:
                    runtime.note_phase(entry, why)                         # [book-nodes] observed, never refused
'''

STRUCTURE_OLD = '''    def book_structure(self, rows):
        valid, errors = [], []
        for row in rows:
            why = self.phase_error(row, valid)
            if why:
                errors.append({'id': str(self.source_entry(row).get('sid') or ''), 'why': why})
            else:
                valid.append(row)
        opening = sum(self.source_entry(row).get('book_phase') == 'opening' for row in valid)
        closing = sum(self.source_entry(row).get('book_phase') == 'closing' for row in valid)
        return valid, {'valid': not errors, 'complete': not errors and opening == 1 and closing == 1,
                       'opening_count': opening, 'closing_count': closing, 'errors': errors}
'''
STRUCTURE_NEW = '''    def note_phase(self, row, why):
        """[book-nodes] What the old gate would have said, kept as a NOTE on the part and in the ledger.
        The part stands and airs; the note is for the reader of the episode, not for a door."""
        entry = self.source_entry(row)
        entry['book_phase_note'] = {'why': str(why)[:300], 'phase': entry.get('book_phase'), 'at': time.time()}
        ledger = self.g.get('FLOW_LEDGER')
        if ledger is not None:
            try:
                ledger.note('round:book_phase_note', str(entry.get('book_phase') or '') + ': ' + str(why), passed=True,
                            road='banter', text=str(entry.get('script') or entry.get('script_plain') or ''),
                            ref=str(entry.get('sid') or ''))
            except Exception:   # noqa: BLE001 - a ledger that cannot write never stops the episode
                pass

    def book_structure(self, rows):
        # [book-nodes] every written part stands; what the old gate would have said is kept beside it
        valid, notes = list(rows), []
        for row in rows:
            why = self.phase_error(row, [r for r in rows if r is not row])
            if why:
                notes.append({'id': str(self.source_entry(row).get('sid') or ''), 'why': why})
        opening = sum(self.source_entry(row).get('book_phase') == 'opening' for row in valid)
        closing = sum(self.source_entry(row).get('book_phase') == 'closing' for row in valid)
        return valid, {'valid': True, 'complete': opening >= 1 and closing >= 1,
                       'opening_count': opening, 'closing_count': closing, 'errors': notes}
'''


def repair_span(text: str) -> str:
    """The whole repair_phase method as it stands (from [book-reads-on]), to take it out."""
    start = text.find("    def repair_phase(self, row, prior=()):")
    if start < 0:
        return ""
    end = text.find("\n    def book_structure(self, rows):", start)
    if end < 0:
        return ""
    return text[start:end + 1]


EDITS = {
    "system3_tables.py": [
        ("the BOOK tables: manner, angle, errand", TABLES_OLD, TABLES_NEW, 1),
        ("three roads in the register", REGISTER_OLD, REGISTER_NEW, 1),
        ("three structures: book_open, book_read, book_close", STRUCT_OLD, STRUCT_NEW, 1),
        ("the validator knows BOOK", VALID_OLD, VALID_NEW, 1),
    ],
    "system3.py": [
        ("the BOOK family and the three roads", FAM_OLD, FAM_NEW, 1),
        ("the book work prints on the running-order row", DIR_OLD, DIR_NEW, 1),
    ],
    "frontend/system3.js": [
        ("the family's words in the window", WHAT_OLD, WHAT_NEW, 1),
        ("BOOK keeps tables", TF_OLD, TF_NEW, 1),
    ],
    "dynamic_segments_runtime.py": [
        ("repair_phase is gone", repair_span, "", 1),      # first: its span ends at book_structure
        ("BOOK_ROADS", ROADS_OLD, ROADS_NEW, 1),
        ("each phase on its own road", ROAD_OLD, ROAD_NEW, 1),
        ("a written part stands; the old gate is a note", ACCEPT_OLD, ACCEPT_NEW, 1),
        ("nothing blocks an episode", BLOCK_OLD, BLOCK_NEW, 1),
        ("the next phase is the node's identity", INTRO_OLD, INTRO_NEW, 1),
        ("the tint room notes, never refuses", TINT_OLD, TINT_NEW, 1),
        ("note_phase; book_structure keeps every part", STRUCTURE_OLD, STRUCTURE_NEW, 1),
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
            if callable(old):
                span = old(text)
                if not span:
                    if "def repair_phase" not in text:
                        print("%-72s applied" % label[:72])
                        continue
                    print("%-72s MISSING (span not found)" % label[:72])
                    missing = True
                    continue
                print("%-72s ready" % label[:72])
                ready = True
                text = text.replace(span, new)
                changed = True
                continue
            if text.count(new) >= want and (new not in old):
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
        tmp = path.with_suffix(path.suffix + ".booknodes.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
