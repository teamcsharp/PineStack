"""[orch-s3b] The operator's answers to the System 3 desk's five questions (2026-09-29).

  python3 tools/orch_s3_wave2_patch.py --check orchestrator_s3.py   exit 0 ready, 2 applied, 1 missing (named)
  python3 tools/orch_s3_wave2_patch.py --apply orchestrator_s3.py

1. Overlap: "a web page sounding at the same time as the PineTab is NORMAL".
   Only EXCLUSIVE_RECEIVERS (pinetab, desktop, box) count; web, car, nabu never.
2. Dead air: the "page join" cause is ignored (IGNORED_GAP_CAUSES).
3/4. Decide-alone and table undo stay as built.
5. Quarantine RELEASE: a `release` door (operator-confirm only; the station
   re-checks the clip before it airs), `s3 release <sid|folder>`, and a
   finding when a quarantined folder is back on the share, which proposes
   its release.
Needs tools/qrelease_app_patch.py applied to app.py (sfx_quarantine_release).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

MARKER = "[orch-s3b]"

FOLDERS_BACK = (
    '    back = list(q.get("folders_back") or [])   # [orch-s3b]\n'
    '    if back:\n'
    '        out.append(_finding("undecodable", "medium",\n'
    '                            "%d quarantined folder(s) are back on the share: %s" % (len(back), ", ".join(back)[:200]),\n'
    '                            "folders_back|" + ",".join(sorted(back)), identify=["s3 mp4"],\n'
    '                            evidence={"folders_back": back, "list": q.get("list")}))\n')

R = lambda name, old, new: Edit(name, old, None, replace=new)  # noqa: E731

EDITS = [
    Edit("consts", 'SECTIONS = ("speakerbox", "sfx", "personalities", "sfxguy", "blocks", "split")\n',
         '# [orch-s3b] OVERLAP IS ONLY AMONG THE EXCLUSIVE RECEIVERS (the operator,\n'
         '# 2026-09-29: "a web page sounding at the same time as the PineTab is\n'
         '# NORMAL"). Still overlap - any two of these sounding at once: PineTab +\n'
         '# this app, PineTab + the Pine Box speaker, this app + the Pine Box speaker.\n'
         '# Never overlap: web pages, the car (its own switch, #1253), Nabu.\n'
         'EXCLUSIVE_RECEIVERS = ("pinetab", "desktop", "box")\n'
         '# [orch-s3b] "page join" is not dead air for the station to fix (the operator).\n'
         'IGNORED_GAP_CAUSES = ("page join",)\n'),
    R("mp4-act", '"act": "quarantine is ONE-WAY (the book row goes playable=0) - operator only"',
      '"act": "quarantine, and its RELEASE (POST /api/sfx/quarantine/release: the clip is re-checked - on the "\n'
      '            "share, decodes with ffmpeg - before it airs) - both operator-confirm only; `s3 release <sid|folder>`"'),
    R("overlap-signal", '"signal": "more than one house receiver sounding at once",',
      '"signal": "two of the exclusive receivers (PineTab, this app, the Pine Box speaker) sounding at once; "\n'
      '                  "web pages, the car and Nabu never count",'),
    R("dead-signal", '"signal": "heard gaps of 30 s or more in the last hour (data/gap_log.jsonl, by cause), or no receiver sounding on air",',
      '"signal": "heard gaps of 30 s or more in the last hour (data/gap_log.jsonl, by cause; \'page join\' is "\n'
      '                  "not dead air), or no receiver sounding on air",'),
    R("undecodable-resolve", '"quarantine a named clip only with the operator\'s confirm (one-way)"],',
      '"quarantine a named clip only with the operator\'s confirm",\n'
      '                    "a folder back on the share: propose its release (operator confirm; every clip "\n'
      '                    "re-checked before it airs, a failed check stays quarantined with its reason)"],'),
    Edit("folders-back", "    return out\n\n\ndef sense_receivers(", FOLDERS_BACK, where="before"),
    R("overlap-house", '    house = [r for r in rows if r.get("id") != "car" and r.get("sounding")]\n',
      '    house = [r for r in rows if str(r.get("id")) in EXCLUSIVE_RECEIVERS and r.get("sounding")]\n'),
    R("gaps", '    recent = [r for r in rows or [] if _f(r.get("until")) >= now - DEAD_WINDOW_S\n',
      '    recent = [r for r in rows or [] if str(r.get("cause") or "") not in IGNORED_GAP_CAUSES\n'
      '              and _f(r.get("until")) >= now - DEAD_WINDOW_S\n'),
    Edit("read-back", '        out["quarantine_recent"] = recent[-20:]\n',
         '        back = []                           # [orch-s3b] a gone folder that has come back\n'
         '        for f in out["quarantine"].get("folders_gone") or []:\n'
         '            try:\n'
         '                if Path(f).is_dir():\n'
         '                    back.append(f)\n'
         '            except OSError:\n'
         '                pass\n'
         '        out["quarantine"]["folders_back"] = back\n'),
    Edit("propose-back", '        if f["class"] in ("dead_air", "stale_script"):\n',
         '        if f["class"] == "undecodable":      # [orch-s3b] propose, never release\n'
         '            for folder in (f.get("evidence") or {}).get("folders_back") or []:\n'
         '                p = self.propose_release(folder=folder, why="the folder is back on the share",\n'
         '                                         by="orchestrator")\n'
         '                out.append(p["id"])\n',
         where="before"),
    Edit("propose-release", '    def _live_hash(self) -> str:\n',
         '    def propose_release(self, sid: str = "", folder: str = "", why: str = "",\n'
         '                        by: str = "operator") -> dict[str, Any]:\n'
         '        """[orch-s3b] A release from the SFX quarantine is the operator\'s to\n'
         '        confirm; he may only propose it. The station re-checks the clip (on\n'
         '        the share, decodes with ffmpeg) before it may air again."""\n'
         '        target = str(sid or folder or "").strip()\n'
         '        if not target:\n'
         '            raise ValueError("name a clip (sid) or a folder")\n'
         '        return self._proposal("release", target, "release %s %s from the SFX quarantine (re-checked before "\n'
         '                              "it airs)" % ("clip" if sid else "folder", target), before="quarantined",\n'
         '                              after="released if it passes the check",\n'
         '                              extra={"sid": str(sid or ""), "folder": str(folder or ""), "why": why},\n'
         '                              reversible=False, needs_operator=True, by=by)\n\n',
         where="before"),
    Edit("confirm-release", '            elif door == "rung":\n',
         '            elif door == "release":         # [orch-s3b] operator only (needs_operator)\n'
         '                got = self._get("sfx_quarantine_release")(\n'
         '                    str(p.get("sid") or ""), str(p.get("folder") or ""),\n'
         '                    "the orchestrator (%s, operator confirmed)" % p["id"], str(p.get("why") or ""))\n'
         '                say = str(got.get("say") or "")\n'
         '                if not got.get("ok"):\n'
         '                    p.update(state="kept", result=say)\n'
         '                    self.mark("act:release", False, error=say)\n'
         '                    self.save()\n'
         '                    return {"ok": False, "say": say, "results": got.get("results")}\n',
         where="before"),
    R("verb-thread", '            if p.get("door") in ("table", "section"):\n',
      '            if p.get("door") in ("table", "section", "release"):\n'),
    Edit("cmd-release", '            if head == "files":\n',
         '            if head == "release" and rest:  # [orch-s3b] a proposal; the operator confirms\n'
         '                t = " ".join(rest)\n'
         '                p = self.propose_release(folder=t) if "/" in t else self.propose_release(sid=t)\n'
         '                return True, "proposal %s: %s" % (p["id"], p["title"]), [\n'
         '                    "confirm: s3 confirm %s   (operator only; it is re-checked first)" % p["id"]]\n',
         where="before"),
    R("cmd-help", 'cue|uncue|finish|retire|remove], files, tree <segment>',
      'cue|uncue|finish|retire|remove], release <sid|folder>, files, tree <segment>'),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, marker=MARKER))
