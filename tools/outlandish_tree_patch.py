#!/usr/bin/env python3
"""[outlandish] script_decision_tree.py: a cut-in is a diamond before its turn.

  T1 [outl-cutin-tree]    the CUTIN rolls that hit, by the turn they made
  T2 [outl-cutin-diamond] the chance diamond (CUTIN1) placed before that turn

usage: outlandish_tree_patch.py --check|--apply script_decision_tree.py   (0 ready, 2 applied, 1 missing)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlandish_patchlib import run  # noqa: E402

EDITS = [
    ("[outl-cutin-tree]", "after",
     '    interject_ev = next((e for e in events if e.get("family") == "INTERJECT"), None)\n',
     '    cutin_at = {str((e.get("meta") or {}).get("cutin_turn")): e for e in events       # [outl-cutin-tree]\n'
     '                if e.get("family") == "CUTIN" and (e.get("meta") or {}).get("cutin_turn")}\n'),
    ("[outl-cutin-diamond]", "replace",
     '        elements.append(stage_of(t))\n'
     '    while gi < len(gates):\n',
     '        if str(t.get("turn_id") or "") in cutin_at:                           # [outl-cutin-diamond]\n'
     '            d = diamond(cutin_at[str(t.get("turn_id"))], labels)\n'
     '            d.update({"kind": "chance", "node": "cutin", "node_label": "Cut-in", "table": "CUTIN1",\n'
     '                      "cycle": t.get("cycle")})\n'
     '            elements.append(d)\n'
     '        elements.append(stage_of(t))\n'
     '    while gi < len(gates):\n'),
]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))
