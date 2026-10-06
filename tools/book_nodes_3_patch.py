#!/usr/bin/env python3
"""[book-nodes-3] The welcome and the sign-off are wheels, and a part with a take gone is re-made at the door.

Measured at the 14:45 CST Book Time window (2026-10-06): the opening had 7 of its 8 takes. Its welcome -
"Welcome to Book Time on <station>. I am Dill." - was the same words as three earlier openings (12:20,
12:45, 13:06, 13:15 on the air log), so one pantry key served them all and was spent when they aired; the
part read "not every planned line has durable audio", the door refused it, nothing of the window aired.
The leg said WELCOMES the listener and names the station, so every episode wrote the same sentence.

Edits:
  system3_tables.py   BK4 (family WELCOME: the shape of the welcome, 10 wheels) and BK5 (family SIGNOFF: the
                      shape of the sign-off, 10 wheels); book_open hello_a / hello_b draw WELCOME, book_close
                      signoff draws SIGNOFF; validate_structure knows the two families.
  system3.py          FAMILIES += WELCOME, SIGNOFF; the running-order row prints the welcome / the sign-off.
  frontend/system3.js FAMILY_WHAT + TABLE_FAMILIES know them.
  dynamic_segments_runtime.py
                      dispatch: before the door is asked, the part the window wants next is re-made when a
                      take of it is gone (the kitchen's larder_prepare renders only what is missing), bounded
                      by BOOK_REMAKE_SECONDS.

Usage:  book_nodes_3_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        book_nodes_3_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

TABLES_OLD = '''DEFAULT_TABLES.append(BK3)                                                   # [book-nodes]
'''
TABLES_NEW = '''DEFAULT_TABLES.append(BK3)                                                   # [book-nodes]

# [book-nodes-3] THE WELCOME AND THE SIGN-OFF ARE WHEELS. A leg that says "welcomes the listener and names the
# station" writes the same sentence every episode; the pantry keys a take on its words, so one take served four
# openings and was spent when they aired - and the fifth opening could not go out. The shape is rolled now.
BK4 = {
    "id": "BK4", "family": "WELCOME", "label": "The welcome (the shape the opening takes)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "How Book Time is opened tonight, rolled on the two welcome legs of the book_open road. The station "
                   "and the book are always named; the shape, the first words and the order are the wheel's - never "
                   "the same welcome twice.",
    "categories": [
        {"id": "shape", "label": "Shape", "weight": 1.0,
         "items": _items([
             {"id": "book_first", "label": "The book first", "weight": 1.0,
              "text": "opens on the book itself - its title, said like a secret - and only then says hello and who is reading"},
             {"id": "walked_in", "label": "As if they just walked in", "weight": 0.9,
              "text": "welcomes the listener as if they had just walked into the room mid-sentence, and catches them up"},
             {"id": "one_word", "label": "One word, then the book", "weight": 0.8,
              "text": "one word of greeting, a pause, then straight into what tonight's book is and why it is on the desk"},
             {"id": "weather", "label": "The hour first", "weight": 0.8,
              "text": "names the hour and the mood of the station first, then that it is Book Time, then the book"},
             {"id": "question", "label": "A question to the listener", "weight": 0.8,
              "text": "opens with a question to the listener about the book's subject, then the welcome, then the title"},
             {"id": "confession", "label": "A confession", "weight": 0.7,
              "text": "confesses something about how tonight's book was chosen, then welcomes the listener properly"},
             {"id": "formal", "label": "Formally", "weight": 0.7,
              "text": "a formal, old-radio welcome - the station, the programme, the readers, the book - in that order, no jokes"},
             {"id": "midread", "label": "Already reading", "weight": 0.7,
              "text": "is already reading a line of the book aloud when the welcome starts, breaks off, and welcomes the listener"},
             {"id": "argument", "label": "Mid-argument", "weight": 0.6,
              "text": "is in the middle of an argument with the other host about the book when the welcome starts, and lets the listener in on it"},
             {"id": "promise", "label": "A promise", "weight": 0.6,
              "text": "promises the listener one thing they will know by the end of tonight's reading, then says who is reading and what"},
         ])},
    ],
}
BK5 = {
    "id": "BK5", "family": "SIGNOFF", "label": "The sign-off (the shape the close takes)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "How Book Time is closed tonight, rolled on the sign-off leg of the book_close road. The book is "
                   "named and the music is handed back every time; the shape and the last words are the wheel's.",
    "categories": [
        {"id": "shape", "label": "Shape", "weight": 1.0,
         "items": _items([
             {"id": "last_line", "label": "The book's last words", "weight": 1.0,
              "text": "lets the book have the last word - one more sentence of it - then names it and hands back to the music"},
             {"id": "next_time", "label": "A promise for next time", "weight": 0.9,
              "text": "says what will be read next time, names the book, and hands back to the music"},
             {"id": "thanks_plain", "label": "Plain thanks", "weight": 0.8,
              "text": "thanks the listener plainly for sitting through the reading, names the book once more, and hands back to the music"},
             {"id": "verdict", "label": "A verdict", "weight": 0.8,
              "text": "gives a one-line verdict on the book as it stands tonight, then hands back to the music"},
             {"id": "question_back", "label": "A question left open", "weight": 0.8,
              "text": "leaves the listener one question the reading raised, names the book, and hands back to the music"},
             {"id": "abrupt", "label": "Abruptly", "weight": 0.7,
              "text": "closes abruptly - the book shut mid-thought, the title said once, and the music back before anyone objects"},
             {"id": "dedication", "label": "A dedication", "weight": 0.7,
              "text": "dedicates tonight's reading of the book to somebody listening, and hands back to the music"},
             {"id": "argument_close", "label": "The argument unsettled", "weight": 0.6,
              "text": "hands back to the music with the argument about the book still unsettled, and says so"},
             {"id": "whisper", "label": "Quietly", "weight": 0.6,
              "text": "closes quietly, almost a whisper - the book, the station, goodnight - and the music comes up under it"},
             {"id": "recommend", "label": "A recommendation", "weight": 0.6,
              "text": "tells the listener whether to pick the book up themselves and why, then hands back to the music"},
         ])},
    ],
}
DEFAULT_TABLES.append(BK4)                                                   # [book-nodes-3]
DEFAULT_TABLES.append(BK5)                                                   # [book-nodes-3]
'''

OPEN_OLD = '''        _leg("hello_a", "The welcome", "open", "A",
             "WELCOMES the listener to Book Time on {stationname} and says their own name - I'm, and the name - "
             "then names the book, {book}, and the chapter being read tonight, {bookchapter}", "ES"),
        _leg("hello_b", "The other host", "middle", "B",
             "says their own name the same way, welcomes the listener too, and says in one line what pulled "
             "them into this book tonight", "ES", "RS"),
'''
OPEN_NEW = '''        _leg("hello_a", "The welcome", "open", "A",
             "opens Book Time on {stationname} in the shape rolled - the station, their own name, the book {book} "
             "and the chapter being read tonight, {bookchapter}, all get said, but in fresh words and in that "
             "shape's order: never the station's stock welcome sentence, never the same welcome as another night",
             "ES", "WELCOME"),
        _leg("hello_b", "The other host", "middle", "B",
             "says their own name, takes up the welcome in the shape rolled for them - in their own words, not "
             "an echo of the first host's - and says in one line what pulled them into this book tonight",
             "ES", "RS", "WELCOME"),
'''
CLOSE_OLD = '''        _leg("signoff", "The sign-off", "close", "alternate",
             "THANKS the listener for Book Time on {stationname}, names {book} once more, and hands back to "
             "the music", "ES", "FL2close"),
'''
CLOSE_NEW = '''        _leg("signoff", "The sign-off", "close", "alternate",
             "closes Book Time on {stationname} in the shape rolled - {book} is named and the music is handed "
             "back, in fresh words, never the same sign-off as another night", "ES", "FL2close", "SIGNOFF"),
'''
VALIDATE_OLD = '''("ES", "RS", "IRS", "FL", "CTS", "REACT", "BOOK")'''
VALIDATE_NEW = '''("ES", "RS", "IRS", "FL", "CTS", "REACT", "BOOK", "WELCOME", "SIGNOFF")'''

FAMILIES_OLD = '''FAMILIES = FAMILIES + ("BOOK",)                                               # [book-nodes] the book work: manner, angle, errand
'''
FAMILIES_NEW = '''FAMILIES = FAMILIES + ("BOOK",)                                               # [book-nodes] the book work: manner, angle, errand
FAMILIES = FAMILIES + ("WELCOME", "SIGNOFF")                                  # [book-nodes-3] the shape of the welcome and the sign-off
'''
ROW_OLD = '''        book = [x["text"] for x in t.get("directions") or [] if x["family"] == "BOOK"]     # [book-nodes]
        if book:
            add += "; the book work: " + book[-1]
'''
ROW_NEW = '''        book = [x["text"] for x in t.get("directions") or [] if x["family"] == "BOOK"]     # [book-nodes]
        if book:
            add += "; the book work: " + book[-1]
        welcome = [x["text"] for x in t.get("directions") or [] if x["family"] == "WELCOME"]   # [book-nodes-3]
        if welcome:
            add += "; the welcome: " + welcome[-1]
        signoff = [x["text"] for x in t.get("directions") or [] if x["family"] == "SIGNOFF"]   # [book-nodes-3]
        if signoff:
            add += "; the sign-off: " + signoff[-1]
'''

JS_WHAT_OLD = '''  REACT: ['Supercut stance (REACT1)',
'''
JS_WHAT_NEW = '''  WELCOME: ['The welcome (BK4)',
    'The shape Book Time opens in tonight, rolled on the two welcome legs of the book_open road: the book first, as if the listener just walked in, one word then the book, a question, a confession, formally, already reading, mid-argument, a promise. The station and the book are always named; the words are never the same welcome twice.'],
  SIGNOFF: ['The sign-off (BK5)',
    'The shape Book Time closes in tonight, rolled on the sign-off leg of the book_close road: the book has the last word, a promise for next time, plain thanks, a verdict, a question left open, abruptly, a dedication, the argument unsettled, quietly, a recommendation. The book is named and the music handed back every time.'],
  REACT: ['Supercut stance (REACT1)',
'''
JS_FAM_OLD = '''\'REACT\', \'BOOK\'];'''
JS_FAM_NEW = '''\'REACT\', \'BOOK\', \'WELCOME\', \'SIGNOFF\'];'''

REMAKE_CONST_OLD = '''    REACT_ROAD = 'supercut_react'
'''
REMAKE_CONST_NEW = '''    BOOK_REMAKE_SECONDS = 45.0          # [book-nodes-3] the door's wait for a part's missing takes to be re-made
    REACT_ROAD = 'supercut_react'
'''
REMAKE_OLD = '''            ready = self.original.get('dialogue_row_ready') or (lambda kind, row: True)
            candidates = [row for row in rows if not row.get('dynamic_handed_off') and ready('banter', row)]
            candidates.sort(key=self.book_order)
'''
REMAKE_NEW = '''            ready = self.original.get('dialogue_row_ready') or (lambda kind, row: True)
            # [book-nodes-3] A PART WITH A TAKE GONE IS RE-MADE AT THE DOOR, NOT REFUSED. The 14:45 opening on
            # 10-06 had 7 of its 8 takes: its welcome was the same words as three earlier openings, one key in
            # the pantry, spent when they aired - and the window went out as music. The kitchen's own re-make
            # (larder_prepare renders only what is missing) runs here for the part the window wants next,
            # bounded, before the door is asked.
            remake = self.g.get('larder_prepare')
            waiting = sorted([row for row in rows if not row.get('dynamic_handed_off')], key=self.book_order)
            if waiting and callable(remake) and not ready('banter', waiting[0]) and not waiting[0].get('preparing'):
                try:
                    await asyncio.wait_for(remake(waiting[0]), timeout=self.BOOK_REMAKE_SECONDS)
                except Exception:   # noqa: BLE001 - a re-make that fails or runs long leaves the door its choice
                    pass
            candidates = [row for row in rows if not row.get('dynamic_handed_off') and ready('banter', row)]
            candidates.sort(key=self.book_order)
'''

EDITS = {
    "system3_tables.py": [
        ("BK4 the welcome and BK5 the sign-off, two wheels", TABLES_OLD, TABLES_NEW, 1),
        ("book_open: the welcome legs roll their shape", OPEN_OLD, OPEN_NEW, 1),
        ("book_close: the sign-off rolls its shape", CLOSE_OLD, CLOSE_NEW, 1),
        ("validate_structure knows WELCOME and SIGNOFF", VALIDATE_OLD, VALIDATE_NEW, 1),
    ],
    "system3.py": [
        ("FAMILIES += WELCOME, SIGNOFF", FAMILIES_OLD, FAMILIES_NEW, 1),
        ("the running-order row prints the welcome and the sign-off", ROW_OLD, ROW_NEW, 1),
    ],
    "frontend/system3.js": [
        ("FAMILY_WHAT knows WELCOME and SIGNOFF", JS_WHAT_OLD, JS_WHAT_NEW, 1),
        ("TABLE_FAMILIES lists them", JS_FAM_OLD, JS_FAM_NEW, 1),
    ],
    "dynamic_segments_runtime.py": [
        ("BOOK_REMAKE_SECONDS", REMAKE_CONST_OLD, REMAKE_CONST_NEW, 1),
        ("dispatch re-makes the next part's missing takes before the door", REMAKE_OLD, REMAKE_NEW, 1),
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
                print("%-78s applied" % label[:78])
                continue
            n = text.count(old)
            if n == want:
                print("%-78s ready" % label[:78])
                ready = True
                text = text.replace(old, new)
                changed = True
            else:
                print("%-78s MISSING (anchor count %d, wanted %d)" % (label[:78], n, want))
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
        tmp = path.with_suffix(path.suffix + ".booknodes3.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
