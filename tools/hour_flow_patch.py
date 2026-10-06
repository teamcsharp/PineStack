#!/usr/bin/env python3
"""[hour-flow] One running-order entry's own structure, and micro-exchanges on a leg. 2026-10-06.

"convert 'the hour' view for a segment into a vertical flowchart ... back button
... same style as the script view flowchart ... add, remove, insert, adjust,
extend nodes ... select a node to give more inner conversational depth ...
micro exchanges."                                   - the operator, 2026-10-06
Edit scope, the operator's choice: "Both, with a toggle" - an edit applies to
THIS entry only, or to every entry of this kind.

Before: a road had ONE structure (plus weighted variants road~vN rolled on
VARIANT), so every entry of a kind in the hour ran the same legs; a leg was one
turn and nothing could hang a shorter exchange off it; the API had a PUT and a
DELETE for structures and no GET (the desk read them off the whole config).

Now:
  system3.py
    - entry_slot_clean / entry_key / entry_slot_of / entry_structure: a structure
      stored under "<road>@<slot_id>" is the one the road runs for conversations
      serving that running-order entry. The entry is read off the conversation's
      inputs: `slot_id` when the door names it, else the scheduled segment's
      `template` (segment_on_air's slot on the sheet = the hour view's slot.id).
    - road_structure(config, road, slot_id="") prefers the entry's own.
    - _structure_roll: the entry's own structure wins outright, recorded as a
      VARIANT pick with no die (_entry_structure_event); an entry structure never
      joins another entry's weighted draw. With no entry structure nothing changes.
    - plan_legs: a leg's `inner` rows ({seat, act, families}) each become one
      more turn right after the leg, in order (inner_rows, seated inside build()
      so the legs after them alternate off the exchange's voice and the parity
      fix sees them); they count against the turn budget (fewer middle passes)
      and the whole is held to max_turns (_inner_trim) - a leg is never dropped
      for an exchange. Such a turn names its leg (turn["leg"]) and carries
      turn["inner"] = {of, index, id}.
  system3_tables.py
    - INNER_FAMILIES, inner_problems(): validate_structure accepts `inner` and
      names a bad row. DEFAULT_ROAD_STRUCTURES and DEFAULT_TABLES are untouched
      (the default config hash 62e7c965e7fe2b0d stands).
  system3_runtime.py
    - _inputs (rounds and lines): inputs["slot_id"] = the door's slot_id, else
      the segment on air's template.
    - GET  /api/system3/structures/{road}?slot_id=  -> {road, slot_id, scope
      "entry"|"road", structure (the effective one), road_structure, default,
      variants, families, line_road}
    - PUT  /api/system3/structures/{road} with {scope:"entry", slot_id, structure}
      writes the entry's own (no scope: today's behaviour, unchanged)
    - DELETE /api/system3/structures/{road}?scope=entry&slot_id= drops it (no
      scope: today's variant delete, unchanged)

Usage:  hour_flow_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        hour_flow_patch.py --apply [ROOT]
"""
from __future__ import annotations

import sys
from pathlib import Path

# --------------------------------------------------------------------------- system3.py

ROAD_STRUCTURE_OLD = '''def road_structure(config, road):
    """[s3-calls] The structure System 3 builds `road` from: the config's own,
    else the default (a config saved before road structures has none)."""
    got = (config.get("structures") or {}).get(road)
    return got if isinstance(got, dict) and got.get("legs") else system3_tables.default_structures().get(road)
'''
ROAD_STRUCTURE_NEW = '''# --- [hour-flow] ONE RUNNING-ORDER ENTRY'S OWN STRUCTURE ----------------------------
#
# "convert 'the hour' view for a segment into a vertical flowchart ... add, remove,
# insert, adjust, extend nodes ... select a node to give more inner conversational
# depth ... micro exchanges" (the operator, 2026-10-06), with the edit scope "Both,
# with a toggle": an edit applies to THIS entry only, or to every entry of this kind.
#
# A structure stored under the key "<road>@<slot_id>" is the one the road runs for
# the conversations serving THAT entry of the running order. The entry is read off
# the conversation's inputs: `slot_id` when the door names it, else the scheduled
# segment's `template` (segment_on_air: the sheet's slot id - what the hour view
# calls slot.id). With no entry, or no structure for it, nothing here changes a
# draw: the road's own structure and its weighted variants stand as before.
ENTRY_SEP = "@"


def entry_slot_clean(value):
    """A slot id as a structure key may carry it: ASCII letters, digits, _ . : -
    (80 at most); anything else is no entry at all ("")."""
    text = "".join(str(value or "").split())[:80]
    if not text or not text.isascii() or not all(c.isalnum() or c in "_.:-" for c in text):
        return ""
    return text


def entry_key(road, slot_id):
    """The structures key of one entry's own structure: road@slot_id."""
    return "%s%s%s" % (str(road or "").partition("~")[0], ENTRY_SEP, entry_slot_clean(slot_id))


def entry_slot_of(inputs):
    """The running-order entry a conversation serves, off its inputs: the door's
    `slot_id`, else the scheduled segment's template (its slot on the sheet)."""
    inputs = inputs if isinstance(inputs, dict) else {}
    seg = inputs.get("segment") if isinstance(inputs.get("segment"), dict) else {}
    return entry_slot_clean(inputs.get("slot_id") or seg.get("template") or "")


def entry_structure(config, road, slot_id):
    """The entry's own structure when it has one that is switched on, else None."""
    slot = entry_slot_clean(slot_id)
    if not slot or not isinstance(config, dict):
        return None
    mine = (config.get("structures") or {}).get(entry_key(road, slot))
    if isinstance(mine, dict) and mine.get("legs") and mine.get("enabled", True) is not False:
        return mine
    return None


def road_structure(config, road, slot_id=""):
    """[s3-calls] The structure System 3 builds `road` from: the config's own,
    else the default (a config saved before road structures has none).
    [hour-flow] With `slot_id`, that running-order entry's own structure first."""
    mine = entry_structure(config, road, slot_id) if slot_id else None
    if mine is not None:
        return mine
    got = (config.get("structures") or {}).get(road)
    return got if isinstance(got, dict) and got.get("legs") else system3_tables.default_structures().get(road)
'''

ROLL_DEF_OLD = '''def _structure_roll(conv, config, road):
    """[s3-window] WHICH STRUCTURE THIS ROAD RUNS: the road's own, or one of
'''
ROLL_DEF_NEW = '''def _entry_structure_event(conv, road, entry, st):
    """[hour-flow] THE ENTRY'S OWN STRUCTURE, on the record: a VARIANT pick with no
    die - the running-order entry this round serves has a structure of its own, so
    the road runs it, and its weighted variants are not drawn."""
    key = entry_key(road, entry)
    label = str(st.get("label") or key)
    rows = [{"id": key, "label": label, "base": 1.0, "weight": 1.0, "p": 1.0,
             "why": ["the %s entry %s has a structure of its own" % (road, entry)]}]
    before = _snapshot(conv, (conv.get("cursor") or {}).get("initiator"))
    ev = _event(conv, {"turn_id": "", "turn_index": -1}, "VARIANT",
                [{"stage": "item", "candidates": rows, "excluded": [], "total": 1.0, "selected": key,
                  "selected_index": 1, "of": 1, "draw": None}],
                {"table": "structures", "category": road, "category_label": road + " structures",
                 "id": key, "label": label, "index": 1, "of": 1, "entry": entry},
                before, meta={"why": "the %s road runs the structure of the running-order entry %s this round "
                                     "serves - no draw, the entry's own stands" % (road, entry),
                              "entry": entry, "structure": key})
    conv["variant_roll"] = {"structure": key, "event_id": ev["event_id"], "of": 1, "entry": entry}
    return ev


def _structure_roll(conv, config, road):
    """[s3-window] WHICH STRUCTURE THIS ROAD RUNS: the road's own, or one of
'''

ROLL_BODY_OLD = '''    base = road_structure(config, road)
    cands = [(road, base)] if isinstance(base, dict) and base.get("legs") else []
    for key, st in sorted((config.get("structures") or {}).items()):
        if (isinstance(st, dict) and st.get("variant_of") == road and st.get("legs")
                and st.get("enabled", True) is not False):
            cands.append((key, st))
'''
ROLL_BODY_NEW = '''    entry = entry_slot_of(conv.get("inputs"))                                  # [hour-flow] this entry's own first
    mine = entry_structure(config, road, entry) if entry else None
    if mine is not None:
        return mine, _entry_structure_event(conv, road, entry, mine)
    base = road_structure(config, road)
    cands = [(road, base)] if isinstance(base, dict) and base.get("legs") else []
    for key, st in sorted((config.get("structures") or {}).items()):
        if (isinstance(st, dict) and st.get("variant_of") == road and st.get("legs")
                and st.get("enabled", True) is not False and not st.get("entry")):   # [hour-flow] an entry's own never joins the draw
            cands.append((key, st))
'''

PLAN_DEF_OLD = '''def plan_legs(conv, config, inputs=None, road=None, structure=None):
    """[s3-roads] A segment planned from its own structure: the open legs
'''
PLAN_DEF_NEW = '''# [hour-flow] MICRO-EXCHANGES: a leg may carry `inner` rows - {seat, act, families} -
# each one more turn planned right after the leg, in order, drawing from its
# families as a leg does (ES always, so the turn has a feeling). The structure's
# max_turns bounds the whole; a leg is never dropped for an exchange - the
# exchanges nearest the end go first. A leg without `inner` is the leg it was.
INNER_FAMILIES = ("ES", "RS", "IRS", "FL", "CTS", "REACT")


def inner_rows(leg):
    """A leg's micro-exchanges as planning legs: id <leg>.x<n>, the leg's place,
    the row's seat ("alternate" until it is seated), its act, its families as draws."""
    out = []
    if not isinstance(leg, dict) or not isinstance(leg.get("inner"), list):
        return out
    for k, row in enumerate(leg["inner"]):
        if not isinstance(row, dict):
            continue
        act = " ".join(str(row.get("act") or "").split())
        if not act:
            continue
        fams = []
        for f in row.get("families") or []:
            if str(f) in INNER_FAMILIES and str(f) not in fams:
                fams.append(str(f))
        if "ES" not in fams:
            fams.insert(0, "ES")
        out.append({"id": "%s.x%d" % (leg.get("id"), k + 1),
                    "label": (str(row.get("label") or "").strip()
                              or "Exchange %d inside %s" % (k + 1, leg.get("label") or leg.get("id"))),
                    "place": leg.get("place"), "seat": str(row.get("seat") or "alternate"), "act": act,
                    "draws": [{"family": f} for f in fams], "inner_of": leg.get("id"), "inner_index": k})
    return out


def _inner_trim(seq, hi):
    """[hour-flow] The planned sequence held to the structure's max_turns: the
    exchanges nearest the end go first; a leg is never dropped for an exchange."""
    out = list(seq)
    while len(out) > hi:
        drop = next((j for j in range(len(out) - 1, -1, -1) if out[j][0].get("inner_of")), -1)
        if drop < 0:
            break
        del out[drop]
    return out


def plan_legs(conv, config, inputs=None, road=None, structure=None):
    """[s3-roads] A segment planned from its own structure: the open legs
'''

BUILD_OLD = '''    def build(fill_n):
        seq = [(leg, str(leg.get("seat") or "A")) for leg in opening]
        last = seq[-1][1] if seq else ""
        for k in range(fill_n):
            leg = middle[k % len(middle)]
            seat = str(leg.get("seat") or "alternate")
            if seat == "alternate":
                i = alt.index(last) if last in alt else -1
                seat = alt[(i + 1) % len(alt)]
            seq.append((leg, seat))
            last = seat
        for leg in closing:
            seat = str(leg.get("seat") or "alternate")
            if seat == "alternate":
                i = alt.index(last) if last in alt else -1
                seat = alt[(i + 1) % len(alt)]
            seq.append((leg, seat))
            last = seat
        return seq

    fill_n = max(0, want - len(opening) - len(closing)) if middle else 0
'''
BUILD_NEW = '''    def build(fill_n):
        seq = []
        state = {"last": ""}

        def put(leg, seat):
            # [hour-flow] the leg, then its micro-exchanges in order: an exchange seated
            # "alternate" (or on the voice just heard) takes the next voice, and the
            # legs after it alternate off the exchange's speaker, not the leg's
            seq.append((leg, seat))
            state["last"] = seat
            for row in inner_rows(leg):
                s = str(row.get("seat") or "alternate")
                if s == "alternate" or s == state["last"]:
                    i = alt.index(state["last"]) if state["last"] in alt else -1
                    s = alt[(i + 1) % len(alt)]
                seq.append((dict(row, seat=s), s))
                state["last"] = s

        for leg in opening:
            put(leg, str(leg.get("seat") or "A"))
        for k in range(fill_n):
            leg = middle[k % len(middle)]
            seat = str(leg.get("seat") or "alternate")
            if seat == "alternate":
                i = alt.index(state["last"]) if state["last"] in alt else -1
                seat = alt[(i + 1) % len(alt)]
            put(leg, seat)
        for leg in closing:
            seat = str(leg.get("seat") or "alternate")
            if seat == "alternate":
                i = alt.index(state["last"]) if state["last"] in alt else -1
                seat = alt[(i + 1) % len(alt)]
            put(leg, seat)
        return seq

    fill_n = max(0, want - len(opening) - len(closing)) if middle else 0
    # [hour-flow] the exchanges count against the turn budget: fewer middle passes
    # while the whole still runs over it and the floor holds
    while fill_n > 0 and len(build(fill_n)) > want and len(build(fill_n - 1)) >= lo:
        fill_n -= 1
'''

PLAN_SEQ_OLD = '''    if middle and collides(seq):
        if fill_n > 0 and len(seq) - 1 >= lo:
            seq = build(fill_n - 1)
        elif len(seq) + 1 <= hi:
            seq = build(fill_n + 1)
    # [s3-events] what happens in this segment, before its turns
'''
PLAN_SEQ_NEW = '''    if middle and collides(seq):
        if fill_n > 0 and len(seq) - 1 >= lo:
            seq = build(fill_n - 1)
        elif len(seq) + 1 <= hi:
            seq = build(fill_n + 1)
    seq = _inner_trim(seq, hi)                                                  # [hour-flow] held to max_turns
    # [s3-events] what happens in this segment, before its turns
'''

PLAN_TURN_OLD = '''        turn["leg"] = leg.get("id")
        turn["place"] = leg.get("place")
    conv["draws"] = stream.n
    _events_attach(conv)                                                        # [s3-events]
'''
PLAN_TURN_NEW = '''        turn["leg"] = leg.get("inner_of") or leg.get("id")                       # [hour-flow] an inner turn names its leg
        turn["place"] = leg.get("place")
        if leg.get("inner_of"):
            turn["inner"] = {"of": leg["inner_of"], "index": int(leg.get("inner_index") or 0), "id": leg.get("id")}
    conv["draws"] = stream.n
    _events_attach(conv)                                                        # [s3-events]
'''

# --------------------------------------------------------------------------- system3_tables.py

VALIDATE_DEF_OLD = '''def validate_structure(road, st):
    """A road structure an operator may save: legs with ids, a place, a seat
    and draws of known families. Returns the list of problems."""
'''
VALIDATE_DEF_NEW = '''# [hour-flow] MICRO-EXCHANGES on a leg: `inner` is a list of rows, each one more
# turn planned right after the leg - {seat, act, families} (seat A-E or
# "alternate"; families among INNER_FAMILIES, ES when none). A leg without
# `inner` is exactly the leg it was; DEFAULT_ROAD_STRUCTURES carry none.
INNER_FAMILIES = ("ES", "RS", "IRS", "FL", "CTS", "REACT")
INNER_MAX = 6


def inner_problems(leg, where):
    """[hour-flow] What is wrong with a leg's micro-exchanges, as a list."""
    out = []
    if not isinstance(leg, dict) or leg.get("inner") is None:
        return out
    rows = leg.get("inner")
    if not isinstance(rows, list):
        return ["%s: inner must be a list of exchanges" % where]
    if len(rows) > INNER_MAX:
        out.append("%s: at most %d inner exchanges" % (where, INNER_MAX))
    for i, row in enumerate(rows):
        tag = "%s inner %d" % (where, i + 1)
        if not isinstance(row, dict):
            out.append("%s: an exchange is an object with seat, act and families" % tag)
            continue
        if str(row.get("seat") or "alternate") not in ("A", "B", "C", "D", "E", "alternate"):
            out.append("%s: seat must be A-E or alternate" % tag)
        if not str(row.get("act") or "").strip():
            out.append("%s: needs an act (what the turn does)" % tag)
        fams = row.get("families")
        if fams is not None and (not isinstance(fams, list) or any(str(f) not in INNER_FAMILIES for f in fams)):
            out.append("%s: families must be among %s" % (tag, ", ".join(INNER_FAMILIES)))
    return out


def validate_structure(road, st):
    """A road structure an operator may save: legs with ids, a place, a seat
    and draws of known families. Returns the list of problems."""
'''

VALIDATE_CALL_OLD = '''        out.extend(split_problems(leg, "leg %s" % leg["id"]))                  # [s3-split]
'''
VALIDATE_CALL_NEW = '''        out.extend(split_problems(leg, "leg %s" % leg["id"]))                  # [s3-split]
        out.extend(inner_problems(leg, "leg %s" % leg["id"]))                  # [hour-flow] micro-exchanges
'''

# --------------------------------------------------------------------------- system3_runtime.py

INPUTS_ROUND_OLD = '''            "segment": segment,
            "subject": {"topic": topic, "category": category, "seeded": bool(seed_text),
'''
INPUTS_ROUND_NEW = '''            "segment": segment,
            # [hour-flow] the running-order entry this round serves: the door's own word
            # (slot_id) else the sheet's slot on air; an entry's own structure keys on it
            "slot_id": system3.entry_slot_clean(ctx.get("slot_id") or segment.get("template") or ""),
            "subject": {"topic": topic, "category": category, "seeded": bool(seed_text),
'''

INPUTS_LINE_OLD = '''                "segment": segment,
                "subject": {"topic": system3.whole_cut(context, 400), "category": "own_material", "seeded": False,
'''
INPUTS_LINE_NEW = '''                "segment": segment,
                "slot_id": system3.entry_slot_clean(ctx.get("slot_id") or segment.get("template") or ""),   # [hour-flow]
                "subject": {"topic": system3.whole_cut(context, 400), "category": "own_material", "seeded": False,
'''

GET_OLD = '''    @app.put("/api/system3/structures/{road}")
    async def put_road_structure(road: str, request: Request, authorization: str | None = Header(default=None)):
'''
GET_NEW = '''    # --- [hour-flow] ONE ENTRY'S OWN STRUCTURE: GET the effective one, PUT / DELETE it ---------
    ENTRY_FIELDS = ("legs", "label", "head", "tail", "material", "min_turns", "max_turns", "caller_share",
                    "alternate_seats", "topics")

    def entry_variants_of(held, base):
        """Every structure standing beside the road's own: its weighted variants
        (road~vN) and its entries' own (road@slot_id)."""
        rows = []
        for key, st in sorted(held.items()):
            if not isinstance(st, dict) or not st.get("legs"):
                continue
            if st.get("variant_of") == base or st.get("entry_of") == base:
                rows.append({"key": key, "label": str(st.get("label") or key),
                             "scope": "entry" if st.get("entry") else "variant", "entry": str(st.get("entry") or ""),
                             "weight": st.get("weight", 1.0), "enabled": st.get("enabled", True) is not False,
                             "version": st.get("version"), "legs": len(st.get("legs") or []),
                             "inner": sum(len(x.get("inner") or []) for x in st.get("legs") or [] if isinstance(x, dict))})
        return rows

    @app.get("/api/system3/structures/{road}")
    async def get_road_structure(road: str, slot_id: str = "", authorization: str | None = Header(default=None)):
        """[hour-flow] The structure in force for a road - and, with ?slot_id=, for ONE
        running-order entry of it: the entry's own (scope "entry") when it has one,
        else the road's (scope "road"). The road's own and the default ride beside it
        (the hour view's "back to the road's default"), with every variant and entry
        structure the road has."""
        host.require_read_auth(authorization)
        base = str(road or "").partition("~")[0]
        config = rt.config
        held = config.get("structures") or {}
        default = system3_tables.default_structures().get(base)
        own = held.get(road) if "~" in road and isinstance(held.get(road), dict) else system3.road_structure(config, base)
        if not isinstance(own, dict) or not own.get("legs"):
            raise HTTPException(404, "no road called %s has a structure" % road)
        slot = system3.entry_slot_clean(slot_id)
        mine = system3.entry_structure(config, base, slot) if slot else None
        key = system3.entry_key(base, slot) if slot else ""
        return {"road": base, "slot_id": slot, "scope": "entry" if mine is not None else "road",
                "key": key if mine is not None else road,
                "structure": mine if mine is not None else own, "road_structure": own, "default": default,
                "entry_held": isinstance(held.get(key), dict) if key else False,
                "variants": entry_variants_of(held, base),
                "families": list(system3_tables.INNER_FAMILIES), "line_road": base in system3_tables.LINE_ROADS}

    async def put_entry_structure(road, raw):
        """[hour-flow] Save ONE running-order entry's own structure (road@slot_id): the
        body's legs (with their micro-exchanges), label, head, tail and turn bounds over
        the entry's current structure, else the road's. The legs ARE the entry's shape:
        a road graph copied off the base would plan instead of them, so none is copied
        (a body may still carry its own)."""
        base = str(road or "").partition("~")[0]
        slot = system3.entry_slot_clean(raw.get("slot_id"))
        if not slot:
            raise HTTPException(400, "an entry structure is named by its slot_id (letters, digits, _ . : -)")
        body = raw.get("structure") if isinstance(raw.get("structure"), dict) else raw
        problems = system3_tables.validate_structure(base, body)
        if problems:
            raise HTTPException(400, "; ".join(problems[:6]))
        config = copy.deepcopy(rt.config)
        held = config.setdefault("structures", system3_tables.default_structures())
        if base not in held and base not in system3.ROADS:
            raise HTTPException(400, "no road called %s to shape an entry of" % base)
        key = system3.entry_key(base, slot)
        fresh = not isinstance(held.get(key), dict)
        mine = dict(held.get(key) or system3.road_structure(config, base) or {})
        if fresh:
            for drop in ("graph", "weight", "variant_of"):
                mine.pop(drop, None)
        mine.update({k: body[k] for k in ENTRY_FIELDS if k in body})
        if "graph" in body:
            import conversation_graph
            mine["graph"] = conversation_graph.normalize(body["graph"])
            graph_problems = conversation_graph.validate(mine["graph"])
            if graph_problems:
                raise HTTPException(400, "; ".join(graph_problems))
        if "enabled" in raw or "enabled" in body:
            mine["enabled"] = bool(raw.get("enabled", body.get("enabled", True)))
        mine.update({"id": key, "kind": str(mine.get("kind") or "legs"), "entry_of": base, "entry": slot, "scope": "entry"})
        mine["version"] = int(mine.get("version") or 1) + 1
        held[key] = mine
        return {"hash": await save_config(config, "%s entry structure v%d" % (key, mine["version"])),
                "structure": mine, "road": base, "slot_id": slot, "scope": "entry", "key": key}

    @app.put("/api/system3/structures/{road}")
    async def put_road_structure(road: str, request: Request, authorization: str | None = Header(default=None)):
'''

PUT_OLD = '''        host.require_auth(authorization)
        raw = body_json(await request.body())
        # [s3-window] a variant is "<road>~v<n>": a copy of the road's segment with
'''
PUT_NEW = '''        host.require_auth(authorization)
        raw = body_json(await request.body())
        if isinstance(raw, dict) and str(raw.get("scope") or "") == "entry":   # [hour-flow] this entry only
            return await put_entry_structure(road, raw)
        # [s3-window] a variant is "<road>~v<n>": a copy of the road's segment with
'''

DELETE_OLD = '''    @app.delete("/api/system3/structures/{road}")
    async def delete_road_structure(road: str, authorization: str | None = Header(default=None)):
        """[s3-window] Drop a variant. A road's own structure cannot be deleted
        (reset it from the defaults instead)."""
        host.require_auth(authorization)
        if "~" not in road:
'''
DELETE_NEW = '''    @app.delete("/api/system3/structures/{road}")
    async def delete_road_structure(road: str, scope: str = "", slot_id: str = "",
                                    authorization: str | None = Header(default=None)):
        """[s3-window] Drop a variant. A road's own structure cannot be deleted
        (reset it from the defaults instead). [hour-flow] ?scope=entry&slot_id=<id>
        drops ONE running-order entry's own structure (road@slot_id): that entry
        goes back to the road's own."""
        host.require_auth(authorization)
        if str(scope or "") == "entry":
            slot = system3.entry_slot_clean(slot_id)
            if not slot:
                raise HTTPException(400, "an entry structure is named by its slot_id")
            base = str(road or "").partition("~")[0]
            key = system3.entry_key(base, slot)
            config = copy.deepcopy(rt.config)
            held = config.get("structures") or {}
            if key not in held:
                raise HTTPException(404, "the %s entry %s has no structure of its own" % (base, slot))
            held.pop(key)
            return {"hash": await save_config(config, "%s entry structure dropped" % key), "deleted": key,
                    "road": base, "slot_id": slot, "scope": "entry"}
        if "~" not in road:
'''

EDITS = {
    "system3.py": [
        ("entry_slot_clean / entry_key / entry_slot_of / entry_structure; road_structure(slot_id=)", ROAD_STRUCTURE_OLD, ROAD_STRUCTURE_NEW, 1),
        ("_entry_structure_event: the entry's own, a VARIANT pick with no die", ROLL_DEF_OLD, ROLL_DEF_NEW, 1),
        ("_structure_roll: the entry's own structure wins; never joins another draw", ROLL_BODY_OLD, ROLL_BODY_NEW, 1),
        ("INNER_FAMILIES, inner_rows, _inner_trim", PLAN_DEF_OLD, PLAN_DEF_NEW, 1),
        ("build() seats each leg's micro-exchanges after it; fill_n respects the budget", BUILD_OLD, BUILD_NEW, 1),
        ("plan_legs holds the whole to max_turns, exchanges first", PLAN_SEQ_OLD, PLAN_SEQ_NEW, 1),
        ("an inner turn names its leg and carries turn[inner]", PLAN_TURN_OLD, PLAN_TURN_NEW, 1),
    ],
    "system3_tables.py": [
        ("INNER_FAMILIES, INNER_MAX, inner_problems()", VALIDATE_DEF_OLD, VALIDATE_DEF_NEW, 1),
        ("validate_structure accepts inner and names a bad row", VALIDATE_CALL_OLD, VALIDATE_CALL_NEW, 1),
    ],
    "system3_runtime.py": [
        ("_inputs (rounds): slot_id off the door or the segment on air", INPUTS_ROUND_OLD, INPUTS_ROUND_NEW, 1),
        ("_inputs (lines): slot_id off the door or the segment on air", INPUTS_LINE_OLD, INPUTS_LINE_NEW, 1),
        ("GET /api/system3/structures/{road}?slot_id= and put_entry_structure", GET_OLD, GET_NEW, 1),
        ("PUT scope=entry writes the entry's own; no scope is today's PUT", PUT_OLD, PUT_NEW, 1),
        ("DELETE ?scope=entry&slot_id= drops it; no scope is today's DELETE", DELETE_OLD, DELETE_NEW, 1),
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
        tmp = path.with_suffix(path.suffix + ".hourflow.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        print("wrote %s (%s)" % (path, mode))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
