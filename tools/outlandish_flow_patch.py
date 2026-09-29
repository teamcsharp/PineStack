#!/usr/bin/env python3
"""[outlandish] station_flow.py: the meter is a node of the station flow, so its
audit rows read OUTLANDISH on the AUDIT line (not "reflection").

  F1 [outl-flow] NODE_SPEC gains ("outlandish", "OUTLANDISH meter", ...)

usage: outlandish_flow_patch.py --check|--apply station_flow.py   (0 ready, 2 applied, 1 missing)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outlandish_patchlib import run  # noqa: E402

EDITS = [
    ("[outl-flow]", "before",
     '    ("gazette", "Gazette desks",',
     '    ("outlandish", "OUTLANDISH meter", "gauge", "judge", "Measures every aired line for outlandish, appalling or '
     'inappropriate content and never filters it: a high score goes to the audit log, raises the next seat\'s dispute '
     'odds and wakes the SFX Guy\'s reaction."),  # [outl-flow]\n'),
]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))
