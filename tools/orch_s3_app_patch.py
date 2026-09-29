"""[orch-s3] Wire the orchestrator's System 3 desk (orchestrator_s3.py) into app.py.

  python3 tools/orch_s3_app_patch.py --check app.py   exit 0 ready, 2 applied, 1 anchors missing (named)
  python3 tools/orch_s3_app_patch.py --apply app.py   idempotent, atomic; CRLF kept CRLF

Eight narrow inserts, each on one anchor line (the msgid_lib contract):
  install  - the desk installs beside the other System 3 doors
  kick     - orch_scan starts the desk's survey (worker thread) every tick,
             before the one-open-ask early return, so the memo stays fresh
  scan     - orch_scan asks the desk's worst un-asked finding (step 3b)
  verbs    - orch_apply learns s3note/s3file/s3fix/s3undo/s3hold (orch_verbs
             reads them off the source, so the policy door lists them too)
  cmd      - the command line: `why #code` and `s3 ...`
  help     - the command line's help rows
  judge    - cupboard_judge's prompt hears what System 3 says about the round
  glass    - GET /api/orchestrator/glass carries the desk's face

Patch app.py ON THE HOST (the share is too slow for the 10 MB file).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

MARKER = "[orch-s3]"

EDITS = [
    Edit("install",
         '    print("the decision tree did not install: %s: %s" % (type(_rtree_exc).__name__, _rtree_exc))\n',
         '# [orch-s3] THE ORCHESTRATOR\'S SYSTEM 3 DESK (orchestrator_s3.py): his read\n'
         '# faculties over every System 3 door, the triage playbook, and proposals\n'
         '# with review -> confirm -> undo. GET /api/orchestrator/system3.\n'
         'try:\n'
         '    import orchestrator_s3 as _orch_s3\n'
         '    _ORCH_S3_DESK = _orch_s3.install(app, globals())\n'
         'except Exception as _os3_exc:  # noqa: BLE001\n'
         '    _ORCH_S3_DESK = None\n'
         '    print("the orchestrator\'s System 3 desk did not install: %s: %s" % (type(_os3_exc).__name__, _os3_exc))\n'),
    Edit("kick",
         '        if orch_open():\n            orch_decide_alone()\n',
         '        # [orch-s3] his System 3 survey runs whatever the ask board says\n'
         '        # (a worker thread, at most every five minutes; never waited for).\n'
         '        _s3desk = globals().get("_ORCH_S3_DESK")\n'
         '        if _s3desk is not None:\n'
         '            try:\n'
         '                _s3desk.maybe_survey()\n'
         '            except Exception:  # noqa: BLE001\n'
         '                pass\n',
         where="before"),
    Edit("scan",
         '        # 4. NOTHING IS WRONG - but six hours is six hours.\n',
         '        # [orch-s3] 3b. SYSTEM 3. The worst finding on his System 3 desk\n'
         '        # (a rogue or untraced line, an MP3 leak, overlap, dead air, a\n'
         '        # stale script, an undecodable clip) not asked about in half a\n'
         '        # day. The desk surveys off the loop; this reads its memo. The\n'
         '        # first option is always one the station may take alone.\n'
         '        _s3ask = globals().get("orch_s3_ask")\n'
         '        if callable(_s3ask):\n'
         '            try:\n'
         '                out = _s3ask() or {}\n'
         '            except Exception:  # noqa: BLE001\n'
         '                out = {}\n'
         '            if out:\n'
         '                return out\n\n',
         where="before"),
    Edit("verbs",
         '        elif verb == "thin":\n',
         '        elif verb in ("s3note", "s3file", "s3fix", "s3undo", "s3hold"):\n'
         '            # [orch-s3] System 3\'s desk: note or file a finding; confirm,\n'
         '            # undo or hold a proposal. Answering alone, the station may\n'
         '            # confirm only what the desk marked station_may.\n'
         '            _s3v = globals().get("orch_s3_verb")\n'
         '            said = (_s3v(verb, arg, alone=bool(alone)) if callable(_s3v)\n'
         '                    else "the System 3 desk is not installed")\n',
         where="before"),
    Edit("cmd",
         '    elif head == "why" and arg:\n',
         '    elif (head == "why" and arg and callable(globals().get("orch_s3_command"))\n'
         '          and re.match(r"^#?[0-9a-f]{6,32}(-p\\d+)?$", arg.split(" ")[0].lower())):\n'
         '        # [orch-s3] a message code, not a road: its life story (/api/why)\n'
         '        ok, say, lines = await globals()["orch_s3_command"](\n'
         '            "why " + arg.split(" ")[0].lstrip("#"))\n'
         '    elif head in ("s3", "sys3", "system3"):\n'
         '        # [orch-s3] System 3\'s desk - read, propose, confirm, undo\n'
         '        _s3c = globals().get("orch_s3_command")\n'
         '        if callable(_s3c):\n'
         '            ok, say, lines = await _s3c(arg)\n'
         '        else:\n'
         '            ok, say = False, "the System 3 desk is not installed"\n',
         where="before"),
    Edit("help",
         '    ("why <road>", "why that road has nothing behind it"),\n',
         '    ("why #<code>", "one message\'s life story across every store"),   # [orch-s3]\n'
         '    ("s3 [know|playbook|survey|findings|untraced|coverage|mp4|display|receivers|tables|"\n'
         '     "cupboard|files|tree <segment>|proposals|faculties]",\n'
         '     "System 3\'s desk: what it is made of, what is wrong with it, where I may act"),\n'
         '    ("s3 table <ID> set <path>=<value> | s3 section <name> set <path>=<value> | "\n'
         '     "s3 cupboard <id> cue|uncue|finish|retire|remove",\n'
         '     "propose a System 3 change - it is shown, not made"),\n'
         '    ("s3 confirm <proposal> | s3 undo <proposal> | s3 hold <proposal>",\n'
         '     "make a proposal, take it back, or leave it waiting"),\n'),
    Edit("judge",
         '    said = ""\n    try:\n        said = await ask_model(prompt, limit=220, spice=0.1,\n'
         '                               mark={"kind": "cupboard_judge"})\n',
         '    # [orch-s3] what System 3 says about this round: scripted by it, or\n'
         '    # legacy stock that would air Untraced on a road it now directs.\n'
         '    try:\n'
         '        _s3j = globals().get("orch_s3_judge_note")\n'
         '        _s3say = _s3j(kind, row) if callable(_s3j) else ""\n'
         '        if _s3say:\n'
         '            prompt = prompt.replace(\n'
         '                "Judge it. Answer",\n'
         '                "WHAT SYSTEM 3 SAYS ABOUT IT:\\n%s\\n\\nJudge it. Answer" % _s3say, 1)\n'
         '    except Exception:  # noqa: BLE001\n'
         '        pass\n',
         where="before"),
    Edit("glass",
         '        state["commands"] = extra["commands"]\n    return state\n',
         None,
         replace='        state["commands"] = extra["commands"]\n'
                 '    try:  # [orch-s3] his System 3 desk, read off its memo\n'
                 '        _s3f = globals().get("orch_s3_face")\n'
                 '        if callable(_s3f):\n'
                 '            state["system3"] = _s3f()\n'
                 '    except Exception:  # noqa: BLE001\n'
                 '        pass\n'
                 '    return state\n'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, marker=MARKER))
