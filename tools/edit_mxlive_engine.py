"""[s3-live-event] Station events in the engine (system3.py).

What this adds, and nothing else:

  1. event_view(config, inputs): a table (or category) tagged with a
     station event is IN the wheels only while that event is on and in one
     of the row's stages - filtered BEFORE any weight is computed, at the
     head of every planner (the seven `inputs = ...` entry lines plus
     replan), so with no event on every draw is today's draw. The
     conversation's config_hash stays the stored config's own:
     new_conversation still hashes the config it was handed.
  2. The tag travels: _spec, weighted_decision's selected, _cts's
     decision, _event_rolls' meta and plan, _events_attach's turn rows all
     carry `event` when the table is tagged - the Rolodex says so, and
     event_claims(conv) collects "table:item" for every roll that landed
     on an event row.
  3. decide_blocks learns kind "claimed": kept only when a roll in the
     round landed on an event row (the event_facts block).
  4. The TRACK_TALK moment: while the record on air IS a live set
     (inputs.record_event), the comment's direction is drawn from the
     event's own TRACK_TALK table on its own stream
     (seed|round:TRACK_TALK:event) - the track_talk die itself untouched.
  5. validate_table accepts the two table families that exist for event
     rows alone: TRACK_TALK (the live record comment) and ANGLE (rows a
     station wheel such as banter.stock_angle borrows).

  python edit_mxlive_engine.py [--check|--apply] path/to/system3.py

Marker-idempotent (marker: [s3-live-event]). --check: 0 ready, 2 applied,
1 anchors missing. Keeps LF endings. No ENGINE_VERSION bump: with no
event on, every draw and every stream is byte-identical (the sweep in
tools/mxlive_seed_sweep.py proves it).
"""
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "[s3-live-event] THE EVENT VIEW"

EDITS: list[tuple[str, str, str, int]] = [
    ("families",
     '    if family not in ("CTS", "ES", "RS", "IRS", "FL", "TEMPER", "SHOCK", "INTERJECT", "FAV", "DIRECTIVE", "EVENT",\n'
     '                      "CHANCE", "POOL", "SPEAKERBOX", "RESOLVE", "WRAP", "IL"):             # [s3-sb-end] SBEND1\n'
     '        raise ValueError("table family must be one of CTS, ES, RS, IRS, FL, TEMPER, SHOCK, INTERJECT, FAV, DIRECTIVE, "\n'
     '                         "EVENT, CHANCE, POOL, SPEAKERBOX, RESOLVE, WRAP, IL")\n',
     '    if family not in ("CTS", "ES", "RS", "IRS", "FL", "TEMPER", "SHOCK", "INTERJECT", "FAV", "DIRECTIVE", "EVENT",\n'
     '                      "CHANCE", "POOL", "SPEAKERBOX", "RESOLVE", "WRAP", "IL",\n'
     '                      "TRACK_TALK", "ANGLE"):     # [s3-live-event] event-row families\n'
     '        raise ValueError("table family must be one of CTS, ES, RS, IRS, FL, TEMPER, SHOCK, INTERJECT, FAV, DIRECTIVE, "\n'
     '                         "EVENT, CHANCE, POOL, SPEAKERBOX, RESOLVE, WRAP, IL, TRACK_TALK, ANGLE")\n', 1),

    ("spec-tag",
     '    spec["table"], spec["category"] = table["id"], cat["id"]\n'
     '    spec["category_label"] = cat.get("label") or cat["id"]\n'
     '    spec["family"] = table["family"]\n',
     '    spec["table"], spec["category"] = table["id"], cat["id"]\n'
     '    spec["category_label"] = cat.get("label") or cat["id"]\n'
     '    spec["family"] = table["family"]\n'
     '    if table.get("event"):                                   # [s3-live-event]\n'
     '        spec["event"] = str(table["event"])\n', 2),

    ("selected-tag",
     '    selected = {"table": table["id"], "category": cat["id"], "category_label": cat["label"],\n'
     '                "id": spec["id"], "label": spec["label"], "text": spec.get("text", ""),\n'
     '                "index": k + 1, "of": len(cat["items"])}\n'
     '    meta = {}\n',
     '    selected = {"table": table["id"], "category": cat["id"], "category_label": cat["label"],\n'
     '                "id": spec["id"], "label": spec["label"], "text": spec.get("text", ""),\n'
     '                "index": k + 1, "of": len(cat["items"])}\n'
     '    if spec.get("event"):                                    # [s3-live-event]\n'
     '        selected["event"] = str(spec["event"])\n'
     '    meta = {}\n', 1),

    ("cts-tag",
     '           "resolver": spec.get("resolver", "direction"), "topic_change": True}\n'
     '    turn["decisions"].append(dec)\n',
     '           "resolver": spec.get("resolver", "direction"), "topic_change": True}\n'
     '    if spec.get("event"):                                    # [s3-live-event]\n'
     '        dec["event"] = str(spec["event"])\n'
     '    turn["decisions"].append(dec)\n', 1),

    ("event-rolls-meta",
     '            meta = {"table": table["id"], "kind": cat["id"], "odds": odds, "seat": cat.get("seat", "any"),\n'
     '                    "place": cat.get("place", "middle"), "ends": bool(cat.get("ends"))}\n',
     '            meta = {"table": table["id"], "kind": cat["id"], "odds": odds, "seat": cat.get("seat", "any"),\n'
     '                    "place": cat.get("place", "middle"), "ends": bool(cat.get("ends"))}\n'
     '            if table.get("event"):                            # [s3-live-event]\n'
     '                meta["event"] = str(table["event"])\n', 1),

    ("event-rolls-plan",
     '                    plan = {"table": table["id"], "kind": cat["id"], "kind_label": str(cat.get("label") or cat["id"]),\n'
     '                            "id": str(item.get("id")), "label": str(item.get("label") or item.get("id")),\n',
     '                    plan = {"table": table["id"], "kind": cat["id"], "kind_label": str(cat.get("label") or cat["id"]),\n'
     '                            "event": str(table.get("event") or ""),      # [s3-live-event]\n'
     '                            "id": str(item.get("id")), "label": str(item.get("label") or item.get("id")),\n', 1),

    ("events-attach-row",
     '        t.setdefault("events", []).append({k: plan.get(k) for k in ("table", "kind", "kind_label", "id", "label",\n'
     '                                                                    "text", "ends", "event_id")})\n',
     '        t.setdefault("events", []).append({k: plan.get(k) for k in ("table", "kind", "kind_label", "id", "label",\n'
     '                                                                    "text", "ends", "event_id",\n'
     '                                                                    "event")})   # [s3-live-event]\n', 1),

    ("events-attach-dec",
     '        t["decisions"].append({"family": "EVENT", "event_id": plan.get("event_id", ""), "item": plan.get("id"),\n'
     '                               "label": "%s - %s" % (plan.get("kind_label"), plan.get("label"))})\n',
     '        t["decisions"].append({"family": "EVENT", "event_id": plan.get("event_id", ""), "item": plan.get("id"),\n'
     '                               "table": plan.get("table"), "event": plan.get("event", ""),   # [s3-live-event]\n'
     '                               "label": "%s - %s" % (plan.get("kind_label"), plan.get("label"))})\n', 1),

    ("track-talk-event",
     '            conv["track_talk_plan"] = {"turn_index": slots[sp], "record": meta["record"], "done": False}\n',
     '            conv["track_talk_plan"] = {"turn_index": slots[sp], "record": meta["record"], "done": False}\n'
     '            # [s3-live-event] while the record on air IS a station event\'s\n'
     '            # live set, the comment\'s direction is one of the event\'s own\n'
     '            # rows, drawn on its own stream - the die above is untouched.\n'
     '            _ev_id = str(inputs.get("record_event") or "")\n'
     '            _erows = ([(t, c, i) for t in _tables_for(config, "TRACK_TALK")\n'
     '                       if str(t.get("event") or "") == _ev_id\n'
     '                       for c in t.get("categories") or [] if isinstance(c, dict) and c.get("enabled") is not False\n'
     '                       for i in c.get("items") or [] if isinstance(i, dict) and i.get("enabled") is not False\n'
     '                       and str(i.get("text") or "").strip() and float(i.get("weight", 1.0) or 0) > 0]\n'
     '                      if _ev_id else [])\n'
     '            if _erows:\n'
     '                _estream = DrawStream(str(conv["seed"]) + "|round:TRACK_TALK:event")\n'
     '                _ed = _estream.next("TRACK_TALK:event")\n'
     '                _ecands = [{"id": "%s:%s" % (c["id"], i.get("id")), "label": str(i.get("label") or i.get("id")),\n'
     '                            "base": float(i.get("weight", 1.0) or 0),\n'
     '                            "weight": float(i.get("weight", 1.0) or 0) * float(c.get("weight", 1.0) or 0),\n'
     '                            "why": []} for (t, c, i) in _erows]\n'
     '                _ek = pick_index([r["weight"] for r in _ecands], _ed["u"])\n'
     '                if _ek >= 0:\n'
     '                    _et, _ec, _ei = _erows[_ek]\n'
     '                    stages.append(_stage("event-row", _ecands, _ek, _ed))\n'
     '                    conv["track_talk_plan"]["record"] = dict(\n'
     '                        meta["record"], event=_ev_id, table=str(_et["id"]), category=str(_ec["id"]),\n'
     '                        item=str(_ei.get("id")), direction=str(_ei.get("text") or "")[:400])\n'
     '                    meta["event"] = _ev_id\n'
     '                    sel["event"] = _ev_id\n'
     '                    sel["label"] += " - about the live set (%s)" % _et["id"]\n', 1),

    ("track-talk-words",
     '    if turn.get("track_talk"):\n'
     '        record = turn["track_talk"]\n'
     '        add += (". Briefly connects the thought just exchanged to the record playing underneath, %s by %s. "\n'
     '                "This is one passing moment inside the conversation, not a separate introduction or send-off" %\n'
     '                (json.dumps(str(record.get("title") or "the record")),\n'
     '                 json.dumps(str(record.get("artist") or "the artist"))))\n',
     '    if turn.get("track_talk"):\n'
     '        record = turn["track_talk"]\n'
     '        if record.get("direction"):                                   # [s3-live-event]\n'
     '            add += (". Briefly connects the thought just exchanged to what is playing underneath - not a "\n'
     '                    "record but %s, LIVE: %s. One passing moment inside the conversation; never invent a "\n'
     '                    "title or an artist for a live set" %\n'
     '                    (json.dumps(str(record.get("title") or "the live set")),\n'
     '                     str(record["direction"]).strip().rstrip(".")))\n'
     '        else:\n'
     '            add += (". Briefly connects the thought just exchanged to the record playing underneath, %s by %s. "\n'
     '                    "This is one passing moment inside the conversation, not a separate introduction or send-off" %\n'
     '                    (json.dumps(str(record.get("title") or "the record")),\n'
     '                     json.dumps(str(record.get("artist") or "the artist"))))\n', 1),

    ("claimed-kind",
     '            elif kind == "roll":\n',
     '            elif kind == "claimed":                              # [s3-live-event]\n'
     '                _claims = event_claims(conv) if isinstance(conv, dict) else []\n'
     '                rec.update(keep=bool(_claims),\n'
     '                           why=("claimed by " + ", ".join(_claims[:4]) if _claims\n'
     '                                else "no roll in this round landed on a station event\'s row - never sent"))\n'
     '            elif kind == "roll":\n', 1),

    ("plan-entries",
     '    inputs = inputs if inputs is not None else conv["inputs"]\n',
     '    inputs = inputs if inputs is not None else conv["inputs"]\n'
     '    config = event_view(config, inputs)                          # [s3-live-event]\n', 7),

    ("replan-entry",
     '    recorded; decision replay re-applies the same observations."""\n'
     '    if from_index >= len(conv["turns"]):\n',
     '    recorded; decision replay re-applies the same observations."""\n'
     '    config = event_view(config, conv.get("inputs") or {})        # [s3-live-event]\n'
     '    if from_index >= len(conv["turns"]):\n', 1),
]

REGION = '''

# --- [s3-live-event] THE EVENT VIEW -----------------------------------------------
#
# A station event (MX Live) is a register entry the runtime keeps in
# config["events"]; its rows are ordinary table rows tagged "event". The
# planners see the config through event_view: while the event is off (or on a
# banked round, or the category's stage does not match) the tagged rows are
# taken out BEFORE any weight is computed, so no draw moves. inputs["events"]
# is {"<id>": {"stage": upcoming|live|fallback|after, ...}}, decided by the
# runtime at plan time and stored on the conversation's inputs - replay sees
# the same view the plan did.


def event_view(config, inputs):
    """The config as this plan may see it. The same object back when nothing
    is tagged (the common case costs one scan and no copy)."""
    tables = (config.get("tables") or []) if isinstance(config, dict) else []
    if not any(isinstance(t, dict) and t.get("event") for t in tables):
        return config
    events = (inputs or {}).get("events") or {}
    banked = bool((inputs or {}).get("bank"))
    out = []
    changed = False
    for t in tables:
        eid = t.get("event") if isinstance(t, dict) else None
        if not eid:
            out.append(t)
            continue
        ev = events.get(str(eid)) if isinstance(events, dict) else None
        stage = str((ev or {}).get("stage") or "")
        if not stage or (banked and not t.get("event_banked")):
            changed = True
            continue
        cats, cut = [], False
        for c in t.get("categories") or []:
            stages = [str(s) for s in ((c or {}).get("event_stages") or [])]
            if stages and stage not in stages:
                cut = True
                continue
            cats.append(c)
        if not cats:
            changed = True
            continue
        if cut:
            t = dict(t)
            t["categories"] = cats
            changed = True
        out.append(t)
    if not changed:
        return config
    view = dict(config)
    view["tables"] = out
    return view


def event_claims(conv):
    """The event rows this round's rolls landed on, as "table:item" - what
    claims the event_facts block (decide_blocks kind "claimed")."""
    out = []

    def _add(tag, tid, item):
        if tag:
            key = "%s:%s" % (tid, item)
            if key not in out:
                out.append(key)

    for p in conv.get("event_plans") or []:
        _add(p.get("event"), p.get("table"), p.get("id"))
    for t in conv.get("turns") or []:
        for d in t.get("decisions") or []:
            _add(d.get("event"), d.get("table"), d.get("item"))
        tt = t.get("track_talk") or {}
        _add(tt.get("event"), tt.get("table"), tt.get("item"))
    return out
'''


def state_of(text: str, old: str, new: str, count: int) -> str:
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def main(argv: list[str]) -> int:
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "system3.py")
    path = Path(target)
    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text, "system3.py is expected LF-only"
    applied, missing = 0, []
    for name, old, new, count in EDITS:
        st = state_of(text, old, new, count)
        if st == "applied":
            applied += 1
        elif st != "ready":
            missing.append("%s (%s)" % (name, st))
    region_in = MARKER in text
    total = len(EDITS) + 1
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied + (1 if region_in else 0), total))
        return 1
    if applied == len(EDITS) and region_in:
        print("already applied (%d edits + region)" % len(EDITS))
        return 2
    if not do_apply:
        print("ready: %d edits + region, %d already in" % (len(EDITS), applied + (1 if region_in else 0)))
        return 0
    for name, old, new, count in EDITS:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    if not region_in:
        text = text.rstrip("\n") + "\n" + REGION.rstrip("\n") + "\n"
    assert "\r" not in text
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
