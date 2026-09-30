"""[radio-tap] POST /api/air/receivers {"id", "audible": true, "radio": true}:
switch a receiver on AND make it the radio - the exclusive comes to it when
another page holds it, and nothing else is switched off. The tablet's row tap
sends this; before, the row was the audible TOGGLE, so the operator's "make
the PineTab the radio" tap on a tablet that was already on switched it OFF."""
import ast
import sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "app.py")
a = p.read_text()
if "[radio-tap]" in a:
    raise SystemExit("already patched")
old = '''    elif only:
        _AUDIO_OWNER.clear()
    routed = []
'''
new = '''    elif only:
        _AUDIO_OWNER.clear()
    # [radio-tap] the tablet's row tap: this receiver on AND the radio. The
    # exclusive comes to it only when ANOTHER page holds it - with nobody
    # holding it every receiver switched on already sounds - and nothing
    # else is switched off (that is what "only" is for).
    if (not only and rid in ("pinetab", "desktop", "web")
            and body.get("radio") is True and body.get("audible") is True):
        ids = air_present().get(rid) or []
        best = max(ids, default="", key=lambda w: float(
            (_LISTENER_SEEN.get(w) or {}).get("at") or 0))
        held = str(_AUDIO_OWNER.get("who") or "")
        if best and held and held not in ids and not _owner_resting(best):
            _AUDIO_OWNER.clear()
            _AUDIO_OWNER.update({"who": best, "at": time.time()})
    routed = []
'''
if a.count(old) != 1:
    raise SystemExit("anchor: found %d" % a.count(old))
a = a.replace(old, new)
old2 = '''    """[airplayers] {"id": "<receiver>", "audible": true|false} switches one;
'''
new2 = '''    """[airplayers] {"id": "<receiver>", "audible": true|false} switches one
    ([radio-tap] with "radio": true a switch-on also hands it the air);
'''
if a.count(old2) != 1:
    raise SystemExit("anchor2: found %d" % a.count(old2))
a = a.replace(old2, new2)
ast.parse(a)
p.write_text(a)
print("patched", p)
