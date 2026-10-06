#!/usr/bin/env python3
"""[supercut-react] The booth reacts to the supercut, on the roulette. 2026-10-06.

"For supercut slots on the radio station, have the DJs respond to the supercut
that is played. I want them rolling a roulette to dictate how they respond,
where they say that they either love it or they do not, depending on where the
roulette wheel rolls. Every segment is node based because whatever happens in
that segment, there is some sort of co-host in the studio."

Measured: a supercut airs through the produced-spot transport, whose System 3
chapter (the replies after a spot) is skipped for source-only plans - so the
supercut was the one thing on the hour that nobody in the studio answered.

Built on the roads the station already has:
- system3_tables.py: REACT1, a table of stances (loves it, hates it, split,
  wants it as the jingle, baffled, moved, suspicious, reviews it like a critic)
  rolled per host turn; the road `supercut_react` in the register; its legs
  structure (first word / the other's stance / lands it), every leg rolling ES
  and REACT; DEFAULT_TABLES gains REACT1 (add_missing_default_tables puts it in
  the stored config once).
- system3.py: ROADS and FAMILIES know the road and the family; a REACT draw's
  words print on the running-order row ("the stance: ...").
- dynamic_segments_runtime.py: when a supercut is prepared, its reaction is
  written and banked with it (road supercut_react, the plan's clips as the
  subject); at dispatch the reaction airs straight after the supercut from the
  shelf, or live when the shelf has none.
- app.py: the shelf is round-shaped (ROUND_SHELF_KINDS), capped at six.

Usage:  supercut_react_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        supercut_react_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------- system3_tables.py
TABLE_OLD = '''DEFAULT_TABLES.append(IL1)                                                   # [s3-split]
'''
TABLE_NEW = '''DEFAULT_TABLES.append(IL1)                                                   # [s3-split]

# [supercut-react] HOW THE BOOTH TAKES THE SUPERCUT. Rolled per host turn on the
# supercut_react road: "they either love it or they do not, depending on where
# the roulette wheel rolls" (operator, 2026-10-06). Shades of both, every one a
# direction the host performs and never names.
REACT1 = {
    "id": "REACT1", "family": "REACT", "label": "Supercut stance (how the booth takes the supercut)",
    "version": 1, "enabled": True, "weight": 1.0,
    "description": "The stance a host takes on the supercut that just played, rolled once per turn on the "
                   "supercut_react road. Love it or not - the wheel decides, with its shades.",
    "categories": [
        {"id": "stance", "label": "Stance", "weight": 1.0,
         "items": _items([
             {"id": "loves_it", "label": "Loves it", "weight": 1.0,
              "text": "LOVES IT - out loud and specific: names the exact moment that got them and wants it played again"},
             {"id": "hates_it", "label": "Hates it", "weight": 1.0,
              "text": "HATES IT - flatly, with one reason: the cut, the timing, or the clips the SFX Guy chose"},
             {"id": "split", "label": "Split", "weight": 0.7,
              "text": "cannot decide - half of it worked and they say exactly which half, and why the rest did not"},
             {"id": "jingle", "label": "Wants it as the jingle", "weight": 0.5,
              "text": "wants it as the new station jingle, effective immediately, and says so over any objection"},
             {"id": "baffled", "label": "Baffled", "weight": 0.6,
              "text": "is baffled by it - asks what on earth it was selling and whether anyone else saw what they saw"},
             {"id": "moved", "label": "Moved", "weight": 0.5,
              "text": "is unexpectedly moved by it and tries, badly, to cover that up"},
             {"id": "suspicious", "label": "Suspicious", "weight": 0.5,
              "text": "suspects the SFX Guy of something - a hidden message, a private joke at the booth's expense"},
             {"id": "critic", "label": "Reviews it", "weight": 0.6,
              "text": "reviews it like a film critic - the edit, the pacing, the ending - and gives it a score out of ten"},
         ])},
    ],
}
DEFAULT_TABLES.append(REACT1)                                                # [supercut-react]
'''

REGISTER_OLD = '''    {"id": "ad_spot", "label": "Produced advert", "shape": "line",
'''
REGISTER_NEW = '''    # [supercut-react] the booth answers the supercut: each host's stance a REACT roll
    {"id": "supercut_react", "label": "Supercut reaction", "shape": "legs",
     "writer": "dynamic_segments_runtime.bank_reaction / react -> dj_banter", "hook": "system3_direct_banter",
     "what": "the booth reacts to the supercut that just played: the first word, the other's stance, the landing - "
             "each host's stance rolled on REACT1 (they love it, or they do not)"},
    {"id": "ad_spot", "label": "Produced advert", "shape": "line",
'''

STRUCTURE_OLD = '''    "track_talk": _line_structure("track_talk", "Record talk", [
'''
STRUCTURE_NEW = '''    "supercut_react": _legs_structure("supercut_react", "Supercut reaction", 3, 5, [   # [supercut-react]
        _leg("first", "First word on the supercut", "open", "A",
             "FIRST WORD ON THE SUPERCUT that just played: names one thing it showed or said, and takes the stance "
             "rolled - plainly, in one breath, to the other host.", "ES", "REACT"),
        _leg("answer", "The other's stance", "middle", "alternate",
             "answers with their own rolled stance on the same supercut - agrees, or does not - and names a "
             "different moment out of it than the one just named.", "ES", "RS", "REACT"),
        _leg("land", "Lands it", "close", "alternate",
             "LANDS IT: one line that settles whether the SFX Guy keeps his job this hour, then straight on with "
             "the show.", "ES", "FL2close"),
    ], "SUPERCUT REACTION"),
    "track_talk": _line_structure("track_talk", "Record talk", [
'''

# ---------------------------------------------------------------- system3.py
FAMILIES_OLD = '''FAMILIES = FAMILIES + system3_tables.CALLEND_FAMILIES                        # [s3-callend] RESOLVE, WRAP
'''
FAMILIES_NEW = '''FAMILIES = FAMILIES + system3_tables.CALLEND_FAMILIES                        # [s3-callend] RESOLVE, WRAP
FAMILIES = FAMILIES + ("REACT",)                                              # [supercut-react] the booth's stance
ROADS = ROADS + ("supercut_react",)                                           # [supercut-react] the road
'''

ROW_OLD = '''        flow = [x["text"] for x in t.get("directions") or [] if x["family"] == "FL"]
        if flow:
            add += "; and " + flow[-1]
'''
ROW_NEW = '''        flow = [x["text"] for x in t.get("directions") or [] if x["family"] == "FL"]
        if flow:
            add += "; and " + flow[-1]
        react = [x["text"] for x in t.get("directions") or [] if x["family"] == "REACT"]   # [supercut-react]
        if react:
            add += "; the stance: " + react[-1]
'''

# ---------------------------------------------------------------- dynamic_segments_runtime.py
PREPARED_OLD = '''            self.last[occurrence] = {'state': 'ready', 'coverage': coverage}
            return row
'''
PREPARED_NEW = '''            self.last[occurrence] = {'state': 'ready', 'coverage': coverage}
            self.bank_reaction_later(occurrence, row)                     # [supercut-react] the booth's answer, banked with it
            return row
'''

DISPATCH_OLD = '''            def accepted():
                self.call('_schedule_action_complete', kind, occurrence)
                row['dynamic_handed_off'] = True
            return bool(await self.g['_air_produced_ad'](row, on_handoff=accepted))
        return False
'''
DISPATCH_NEW = '''            def accepted():
                self.call('_schedule_action_complete', kind, occurrence)
                row['dynamic_handed_off'] = True
            aired = bool(await self.g['_air_produced_ad'](row, on_handoff=accepted))
            if aired:
                await self.react(key, row, track)                      # [supercut-react] the booth answers it
            return aired
        return False
'''

METHODS_OLD = '''    def status(self):
        upcoming = self.call('coord_upcoming', 7200, measure=False, default=[]) or []
'''
METHODS_NEW = '''    # --- [supercut-react] THE BOOTH ANSWERS THE SUPERCUT ----------------------------
    # "have the DJs respond to the supercut that is played ... rolling a roulette to
    # dictate how they respond" (operator, 2026-10-06). Written and banked when the
    # supercut is prepared (road supercut_react, legs + REACT1 stances), aired
    # straight after it from the shelf; live when the shelf holds none.
    REACT_ROAD = 'supercut_react'
    REACT_LINES = 4

    def react_angle(self, row):
        """What the supercut showed and said, as the subject the booth answers."""
        plan = row.get('source_plan') if isinstance(row.get('source_plan'), dict) else row
        clips = [c for c in (plan.get('clips') or []) if isinstance(c, dict)]
        bits = []
        for c in clips[:10]:
            said = str(c.get('said') or '').strip()
            name = str(c.get('name') or c.get('path') or '').rsplit('/', 1)[-1]
            role = str(c.get('role') or '').strip()
            piece = ("%s: '%s'" % (role, said) if said else "%s: %s" % (role, name)) if role else (said or name)
            if piece:
                bits.append(piece)
        product = str(row.get('product') or 'Pine Box FM')
        seconds = float(row.get('seconds') or 0)
        return ("THE SUPERCUT THAT JUST PLAYED - the SFX Guy's %d-second montage selling %s, cut from %d clip(s): %s. "
                "React to THAT - what it showed and what it said - not to the idea of a supercut." % (
                    int(round(seconds)), product, len(clips), '; '.join(bits)[:1400] or 'the clips are not named'))

    def react_rows(self, key):
        shelf = self.g.get('_SHELF') or {}
        out = []
        for r in list(shelf.get(self.REACT_ROAD) or []):
            e = r.get('entry') if isinstance(r.get('entry'), dict) else r
            if str(r.get('supercut_occurrence') or e.get('supercut_occurrence') or '') == str(key):
                out.append(r)
        return out

    def bank_reaction_later(self, occurrence, row):
        go = self.g.get('fire_and_forget')
        try:
            if callable(go):
                go(self.bank_reaction(occurrence, row))
        except Exception as exc:
            self.log('The supercut reaction could not be queued', exc)

    async def bank_reaction(self, occurrence, row):
        """Write the booth's reaction now, while the supercut is fresh, onto its own shelf."""
        if self.react_rows(occurrence):
            return False
        banter = self.g.get('dj_banter')
        shelve = self.g.get('shelf_put')
        if not callable(banter) or not callable(shelve):
            return False
        pile = []
        try:
            await banter(None, road=self.REACT_ROAD, bank=True, bank_to=pile, lines=self.REACT_LINES,
                         own_material=True, angle=self.react_angle(row))
        except Exception as exc:
            self.log('The supercut reaction could not be written', exc)
            return False
        put = 0
        for entry in pile:
            if not isinstance(entry, dict):
                continue
            entry['supercut_occurrence'] = str(occurrence)
            entry['prep_kind'] = self.REACT_ROAD
            try:
                shelve(self.REACT_ROAD, {'entry': entry, 'seconds': float(entry.get('seconds') or 0),
                                         'supercut_occurrence': str(occurrence)})
                put += 1
            except Exception as exc:
                self.log('The supercut reaction could not be shelved', exc)
        if put:
            self.call('_shelf_save')
            rec = self.last.setdefault(occurrence, {})
            rec['reaction'] = 'banked'
        return bool(put)

    async def react(self, key, row, track=None):
        """Straight after the supercut: the banked reaction from the shelf, else written live."""
        rows = self.react_rows(key)
        ready = self.g.get('dialogue_row_ready')
        air = self.g.get('_ready_shelf_air')
        for r in rows:
            try:
                if callable(ready) and not ready(self.REACT_ROAD, r):
                    continue
                if not callable(air):
                    break
                def handed(r=r):
                    r['supercut_handed_off'] = True
                said = await air(self.REACT_ROAD, track, rescue=True, pick=r, on_handoff=handed)
                if said:
                    self.last.setdefault(key, {})['reaction'] = 'aired from the shelf'
                    return True
            except Exception as exc:
                self.log('The banked supercut reaction would not air', exc)
        banter = self.g.get('dj_banter')
        if not callable(banter):
            return False
        try:
            said = await banter(track, road=self.REACT_ROAD, lines=self.REACT_LINES, own_material=True,
                                angle=self.react_angle(row))
            self.last.setdefault(key, {})['reaction'] = 'written live' if said else 'the writer gave nothing'
            return bool(said)
        except Exception as exc:
            self.log('The live supercut reaction failed', exc)
            return False

    def status(self):
        upcoming = self.call('coord_upcoming', 7200, measure=False, default=[]) or []
'''

# ---------------------------------------------------------------- app.py
KINDS_OLD = '''ROUND_SHELF_KINDS = ("manager", "caller", "gallery", "news", "gazette_review", "mixtape")
'''
KINDS_NEW = '''ROUND_SHELF_KINDS = ("manager", "caller", "gallery", "news", "gazette_review", "mixtape",
                     "supercut_react")                                   # [supercut-react]
'''

CAPS_OLD = '''SHELF_CAPS = {"ad": 8, "station_id": 12, "manager": 8, "caller": 8,
'''
CAPS_NEW = '''SHELF_CAPS = {"ad": 8, "station_id": 12, "manager": 8, "caller": 8,
              "supercut_react": 6,   # [supercut-react] one reaction per supercut, a few ahead
'''

VALIDATE_OLD = '''            if not isinstance(d, dict) or d.get("family") not in ("ES", "RS", "IRS", "FL", "CTS"):
                out.append("leg %s: unknown draw %r" % (leg["id"], d))
'''
VALIDATE_NEW = '''            if not isinstance(d, dict) or d.get("family") not in ("ES", "RS", "IRS", "FL", "CTS", "REACT"):   # [supercut-react]
                out.append("leg %s: unknown draw %r" % (leg["id"], d))
'''

# ---------------------------------------------------------------- frontend/system3.js
JS_WHAT_OLD = '''Object.assign(FAMILY_WHAT, {   /* [s3-split] */
'''
JS_WHAT_NEW = '''Object.assign(FAMILY_WHAT, {   /* [supercut-react] the booth's stance on the supercut */
  REACT: ['Supercut stance (REACT1)',
    'How a host takes the supercut that just played, rolled once per turn on the supercut_react road: loves it, hates it, split, wants it as the jingle, baffled, moved, suspicious, reviews it - each item a direction the host performs and never names. The wheel decides whether they love it or not.'],
});
Object.assign(FAMILY_WHAT, {   /* [s3-split] */
'''
JS_FAM_OLD = '''    'MGRTOPIC', 'MGRSUB'];   /* [s3-sb-end] SBEND1 - [s3-mgrtopics] the manager's topics and sub messages */
'''
JS_FAM_NEW = '''    'MGRTOPIC', 'MGRSUB', 'REACT'];   /* [s3-sb-end] SBEND1 - [s3-mgrtopics] the manager's topics and sub messages - [supercut-react] REACT1 */
'''

EDITS = {
    "system3_tables.py": [
        ("REACT1 joins the default tables", TABLE_OLD, TABLE_NEW, 1),
        ("the road is registered", REGISTER_OLD, REGISTER_NEW, 1),
        ("the road's legs structure", STRUCTURE_OLD, STRUCTURE_NEW, 1),
        ("the validator knows the draw", VALIDATE_OLD, VALIDATE_NEW, 1),
    ],
    "frontend/system3.js": [
        ("the editor names the family", JS_WHAT_OLD, JS_WHAT_NEW, 1),
        ("...and lists its table", JS_FAM_OLD, JS_FAM_NEW, 1),
    ],
    "system3.py": [
        ("the engine knows the family and the road", FAMILIES_OLD, FAMILIES_NEW, 1),
        ("the stance prints on the running-order row", ROW_OLD, ROW_NEW, 1),
    ],
    "dynamic_segments_runtime.py": [
        ("a prepared supercut banks its reaction", PREPARED_OLD, PREPARED_NEW, 1),
        ("dispatch airs the reaction after the supercut", DISPATCH_OLD, DISPATCH_NEW, 1),
        ("the reaction methods", METHODS_OLD, METHODS_NEW, 1),
    ],
    "app.py": [
        ("the reaction shelf is round-shaped", KINDS_OLD, KINDS_NEW, 1),
        ("...and capped", CAPS_OLD, CAPS_NEW, 1),
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
            print("%-46s (not in this tree - skipped)" % name[-46:])
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
        tmp = path.with_suffix(path.suffix + ".screact.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
