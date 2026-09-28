"""[s3-material] The manager's last words, a gallery piece and what people
online are saying, for the System 3 rows that name them.

"Manager Message" (CTS1), the gallery pitches in "Ad Pitch" and the RS
"online search" rebuttal were switched off for good (availability False)
because each reached the writer as a bare direction and the writer invented
the thing. system3_cts_material hands the runtime the real material; the
engine names it in the direction and records it on the roll (system3.py and
system3_runtime.py [s3-material]).

(Inserted before image_analysis_identity: the section header it used to sit
before is the last line of system3_dice_patch's stored text.)

--check exits 0 ready / 2 applied / 1 missing; --apply writes LF atomically.
ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

HOST = '# --- [s3-material] what the manager / gallery / research rows bring up -------\n#\n# System 3\'s "Manager Message" (CTS1), the gallery pitches in "Ad Pitch" and\n# the "online search" rebuttal (RS) were switched off for good - availability\n# False in the runtime - because each reached the writer as a bare direction\n# ("brings up the last thing the manager said from upstairs") and the writer\n# made the thing up. The runtime asks here for the real thing instead; a row\n# that needs it is eligible exactly when it is here, and the writer is handed\n# it word for word.\nS3_MANAGER_FRESH_S = 3 * 3600.0\nS3_RESEARCH_KEEP_S = 3600.0\n_S3_RESEARCH: dict[str, dict[str, Any]] = {}\n_S3_RESEARCH_BUSY: set[str] = set()\n\n\ndef _s3_research_key(topic: str) -> str:\n    return " ".join(re.findall(r"[a-z0-9]+", str(topic or "").lower()))[:120]\n\n\nasync def _s3_research_fetch(key: str, query: str) -> None:\n    """What people online are saying about a subject: searched once, in the\n    background - never on the planner\'s clock - and kept for the next round\n    on the same subject."""\n    got: list[dict[str, str]] = []\n    try:\n        got = await asyncio.wait_for(search_searxng(query), timeout=20.0)\n    except Exception:  # noqa: BLE001\n        got = []\n    finally:\n        _S3_RESEARCH_BUSY.discard(key)\n    lines = []\n    for row in got or []:\n        said = " ".join(str(row.get("snippet") or row.get("title") or "").split())\n        if said:\n            lines.append(said[:260])\n        if len(lines) >= 3:\n            break\n    _S3_RESEARCH[key] = {"at": time.time(), "text": " / ".join(lines),\n                         "ref": str((got[0] if got else {}).get("url") or "")[:160]}\n    while len(_S3_RESEARCH) > 200:\n        _S3_RESEARCH.pop(next(iter(_S3_RESEARCH)))\n\n\ndef system3_cts_material(road: str, ctx: dict[str, Any], topic: str = "") -> dict[str, Any]:\n    """The material System 3\'s material rows can name, each {text, label, ref}:\n    the manager\'s last words from upstairs while they are still news, a gallery\n    piece the station has actually looked at (which one is System 3\'s roll),\n    and what people online are saying about the subject (from the cache; a\n    subject not searched yet is searched in the background for next time)."""\n    out: dict[str, Any] = {}\n    now = time.time()\n    try:\n        for row in reversed(list(_RADIO.get("chat") or [])):\n            if str(row.get("who") or "") != "manager" or not str(row.get("text") or "").strip():\n                continue\n            if now - float(row.get("air_at") or row.get("ts") or 0) <= S3_MANAGER_FRESH_S:\n                out["manager"] = {"text": " ".join(str(row["text"]).split())[:600],\n                                  "label": "what the manager said from upstairs",\n                                  "ref": str(row.get("id") or "")}\n            break\n    except Exception:  # noqa: BLE001\n        pass\n    try:\n        seen = dict(_RADIO.get("image_analysis_by_image") or {})\n        names = [n for n, v in seen.items() if str((v or {}).get("analysis") or "").strip()]\n        if names:\n            name = s3_choice("s3.gallery_piece", names[-40:], "which gallery piece a pitch is about",\n                             tabled=False)\n            out["gallery"] = {"text": "%s - %s" % (name, " ".join(str(seen[name]["analysis"]).split())[:500]),\n                              "label": "the piece, as the station saw it", "ref": str(name)}\n    except Exception:  # noqa: BLE001\n        pass\n    try:\n        key = _s3_research_key(topic)\n        if key and settings_web_search():\n            held = _S3_RESEARCH.get(key)\n            if held and now - float(held.get("at") or 0) <= S3_RESEARCH_KEEP_S:\n                if held.get("text"):\n                    out["research"] = {"text": held["text"], "label": "what people online are saying",\n                                       "ref": str(held.get("ref") or "")}\n            elif key not in _S3_RESEARCH_BUSY:\n                _S3_RESEARCH_BUSY.add(key)\n                fire_and_forget(_s3_research_fetch(key, clean_search_query(str(topic))[:200]))\n    except Exception:  # noqa: BLE001\n        pass\n    return out\n\n\n'

EDITS = [
    ("host-material",
     'def image_analysis_identity(name: str, analysis: str = "") -> str:\n',
     HOST + 'def image_analysis_identity(name: str, analysis: str = "") -> str:\n', 1),
]

def plan(text):
    return list(EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
