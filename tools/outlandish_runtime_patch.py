#!/usr/bin/env python3
"""[outlandish] system3_runtime.py: the meter's tables, the mini-round, the one-liners, the tiles.

  R1 [outl-oneline] direct_line: a board clip (a sound) and a line the road marks one_line
                    (an ad's out-bumper, a holding line) plan no exchange - the interject
                    road's graph had planned a 4-7 turn "round" on every board clip
  R2 [outl-mini]    direct_line: an interjection's exchange is a mini-round - its length is
                    MINIROUND1's exit roll (reply, rebuttal, how it ends)
  R3 [outl-tables]  add_missing_default_tables: the six tables, once (a deleted one stays deleted)
  R4 [outl-tile]    /api/system3/line: the line's MEASURE / SFXREACT / HOLD records ride
                    its decisions, so the Roll tab (PineRollTag) rolls them with the others
  R5 [outl-feed]    feed_lines: the same records on the Digital feed's dice

usage: outlandish_runtime_patch.py --check|--apply system3_runtime.py   (0 ready, 2 applied, 1 missing)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlandish_patchlib import run  # noqa: E402

EDITS = [
    ("[outl-oneline]", "after",
     '            _chapter = bool(_graph.get("enabled") and _graph.get("nodes")\n'
     '                            and not any(n.get("type") == "protocol" for n in _graph["nodes"]))\n',
     '            if _chapter and (who == "board" or ctx.get("one_line")):             # [outl-oneline]\n'
     '                # a board clip is a sound and a bumper or a holding line is a one-liner:\n'
     '                # no exchange is planned on it (the one-turn interject "rounds" were these)\n'
     '                _chapter = False\n'
     '                inputs["one_line"] = ("a board clip is a sound, not a line" if who == "board"\n'
     '                                      else str(ctx.get("one_line")))\n'),
    ("[outl-mini]", "replace",
     '                system3.plan_graph(conv, config, _graph, inputs=inputs, road=road)   # [nodeplan]\n',
     '                _mini = None\n'
     '                if road == "interject":                                     # [outl-mini] reply, rebuttal, exit roll\n'
     '                    try:\n'
     '                        import outlandish as _outl\n'
     '                        _mini = _outl.miniround_until(conv, config)\n'
     '                    except Exception as _mexc:  # noqa: BLE001\n'
     '                        self.fail("mini-round", _mexc)\n'
     '                system3.plan_graph(conv, config, _graph, inputs=inputs, road=road, until=_mini)   # [nodeplan]\n'),
    ("[outl-tables]", "after",
     '        if system3_gold is not None:                                        # [s3-gold:tables] GOLD1, once\n'
     '            missing += [t for t in system3_gold.default_tables() if t["id"] not in have and t["id"] not in seen]\n',
     '        try:                                                                # [outl-tables] the meter\'s six, once\n'
     '            import outlandish as _outl\n'
     '            missing += [t for t in _outl.default_tables() if t["id"] not in have and t["id"] not in seen]\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            self.fail("outlandish tables", exc)\n'),
    ("[outl-tile]", "replace",
     '                "decisions": [e for e in conv["decision_events"] if e["event_id"] in ids],\n',
     '                "decisions": [e for e in conv["decision_events"] if e["event_id"] in ids]\n'
     '                + [o for o in conv.get("observations_air") or []                  # [outl-tile]\n'
     '                   if o.get("family") in ("MEASURE", "SFXREACT", "HOLD") and o.get("stages")\n'
     '                   and (got["line_id"] in (o.get("lines") or [])\n'
     '                        or (turn is not None and not o.get("lines") and o.get("turn_id") == turn.get("turn_id")))\n'
     '                   and not (o.get("family") == "MEASURE" and any(\n'
     '                       e.get("family") == "MEASURE" and e["event_id"] in ids for e in conv["decision_events"]))],\n'),
    ("[outl-feed]", "before",
     '            out[lid] = {"system3": True, "conversation_id": cid, "turn_id": tid, "who": who,\n',
     '            if conv is not None:                                             # [outl-feed] the meter, the reaction\n'
     '                for o in conv.get("observations_air") or []:\n'
     '                    if o.get("family") in ("MEASURE", "SFXREACT", "HOLD") and lid in (o.get("lines") or []):\n'
     '                        air.append(self._compact_roll(o))\n'),
]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))
