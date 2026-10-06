#!/usr/bin/env python3
"""[tint-off] [flow-ledger] Tinting off means off; every rejection is seen and can be approved. 2026-10-05, #1584 #1585 #1570.

#1584/#1585 - "the tinting system is off ... make sure it is fully off and when
it is off, it is not in the dialogue or in calculations or systems" / "With
tinting off the paper doesn't need to reference tinting at all."
Checked on the live station: dialogue tinting was already off by three
switches (the content gate "tint", dj.crystal_tint_pass false, no crystal on;
/api/tint: offered 0, tinted 0). Three things still ran or showed:
  * the Gazette wrote a tint plan onto every story whether or not a crystal was
    on, and every story then printed "Crystal tint: 0/N eligible paragraphs; 0
    attempted; pending (target 82%)";
  * tint_recovery_step walked every shelf row every six seconds, because its
    stand-down asks "is the recovery queue empty" and the queue is a pen now;
  * the rhyme index (the tint's own tool) was still being warmed, eight
    embeddings a batch.
Now: no crystal, no plan and no tint line (stored editions too - the render
version moves to 14); the repair step stands down; the warm stands down.

#1570 - "I want to be able to see and approve each and every rejection."
The flow ledger already held every wedge that asks System 3. It now also takes
the three doors every other refusal goes through - note_drop (a line dropped
at the microphone), norepeat_refuse (heard inside the day) and
_radio_entry_rejected (a round withheld) - so one list holds them all, and
POST /api/flow-ledger/approve says a refused line now, in its seat's voice.
The Speech gates panel shows the list with an Approve button on each refusal.

Usage:  tint_off_ledger_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        tint_off_ledger_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ------------------------------------------------------------------ app.py: tint off
WARM_OLD = r'''    """At most one small embedding batch, outside every generation request."""
    if _RHYME_ASSISTANCE_EMBED_LOCK.locked():
        return False
'''
WARM_NEW = r'''    """At most one small embedding batch, outside every generation request."""
    # [tint-off] the rhyme index is the tint's own tool: while no tint is wanted
    # and no crystal is on, it is not warmed (#1584)
    if not dialogue_tint_wanted() and not crystal_active():
        _RHYME_ASSISTANCE_STATE["embedding_state"] = "standing down: tinting is off"
        return False
    if _RHYME_ASSISTANCE_EMBED_LOCK.locked():
        return False
'''

PLAN_OLD = r'''        for story in [lead] + stories + [apology]:
            paper_tint_plan(story)
        tinted_by = paper_tinted_by()
        if tinted_by:
'''
PLAN_NEW = r'''        tinted_by = paper_tinted_by()
        # [tint-off] NO TINT, NO TINT PAPERWORK. The plan was written onto every story
        # whether or not a crystal was on, and every story then printed "Crystal
        # tint: 0/N eligible paragraphs; 0 attempted; pending" (#1585).
        if tinted_by:
            for story in [lead] + stories + [apology]:
                paper_tint_plan(story)
        if tinted_by:
'''

STATUS_OLD = r'''    deferred = int(report.get("deferred") or 0)
    cut = int(report.get("cut") or 0)
    return (f"Crystal tint: {int(report.get('changed') or 0)}/"
'''
STATUS_NEW = r'''    deferred = int(report.get("deferred") or 0)
    cut = int(report.get("cut") or 0)
    # [tint-off] a tint that never ran is not a line in the paper: the editions
    # printed while tinting was off carry a plan nobody asked for (#1585)
    if not (int(report.get("attempted") or 0) or int(report.get("changed") or 0) or deferred or cut):
        return ""
    return (f"Crystal tint: {int(report.get('changed') or 0)}/"
'''

VERSION_OLD = r'''PAPER_RENDER_VERSION = 13          # #1158: set to publishing rules - see _paper_words
'''
VERSION_NEW = r'''PAPER_RENDER_VERSION = 14          # [tint-off] 14: an untinted story prints no tint line (13 was #1158: set to publishing rules - see _paper_words)
'''

STEP_OLD = r'''    if not _RADIO.get("on") or (not dialogue_tint_required() and not _DIALOGUE_RECOVERY):
        if not crystal_tint_holds():
'''
STEP_NEW = r'''    # [tint-off] with flow open the pen is not this step's work, so a station that
    # requires no tint has nothing here to walk every six seconds (#1584)
    if not _RADIO.get("on") or (not dialogue_tint_required()
                                and (not _DIALOGUE_RECOVERY or s3_flow_is_open())):
        if not crystal_tint_holds():
'''

# ------------------------------------------------------------------ app.py: the ledger sees every refusal
DROP_OLD = r'''    dropped.append({"ts": int(time.time()), "who": who,
                    "text": str(text)[:200], "why": why})
    del dropped[:-40]
'''
DROP_NEW = r'''    dropped.append({"ts": int(time.time()), "who": who,
                    "text": str(text)[:200], "why": why})
    del dropped[:-40]
    try:                            # [flow-ledger] every refusal is seen in one place (#1570)
        FLOW_LEDGER.note("dropped_line", str(why or ""), passed=False, who=str(who or ""),
                         road=str((context or {}).get("kind") or "") if isinstance(context, dict) else "",
                         text=str(text or ""))
    except Exception:  # noqa: BLE001
        pass
'''

NOREPEAT_OLD = r'''        row = NOREPEAT.refuse(kind, key, road, why, text, ref, stage)
    except Exception:  # noqa: BLE001
        row = {"why": why or "heard inside the day"}
    if say:
'''
NOREPEAT_NEW = r'''        row = NOREPEAT.refuse(kind, key, road, why, text, ref, stage)
    except Exception:  # noqa: BLE001
        row = {"why": why or "heard inside the day"}
    try:                            # [flow-ledger] and the no-repeat rule's refusals with them
        FLOW_LEDGER.note("norepeat_%s" % kind, "%s (%s)" % (row.get("why") or "heard inside the day", stage),
                         passed=False, road=str(road or ""), text=str(text or ref or ""))
    except Exception:  # noqa: BLE001
        pass
    if say:
'''

ROUND_OLD = r'''    script = str(entry.get("script") or "")
    kind = str(entry.get("prep_kind") or "banter")
    brief = entry.get("brief") or {}
    quality = (entry.get("call") or {}).get("quality") or {}
'''
ROUND_NEW = r'''    script = str(entry.get("script") or "")
    kind = str(entry.get("prep_kind") or "banter")
    try:                            # [flow-ledger] a withheld round is seen too (#1570)
        FLOW_LEDGER.note("round:" + str(stage), "the round was withheld at %s" % str(stage).replace("_", " "),
                         passed=False, road=kind, text=script,
                         ref=str((entry.get("system3") or {}).get("conversation_id") or entry.get("sid") or ""))
    except Exception:  # noqa: BLE001
        pass
    brief = entry.get("brief") or {}
    quality = (entry.get("call") or {}).get("quality") or {}
'''

ROUTE_OLD = r'''@app.post("/api/flow/release")
'''
ROUTE_NEW = r'''@app.post("/api/flow-ledger/approve")
async def api_flow_ledger_approve(request: Request,
                                  authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[flow-ledger] The operator approves a refusal: {n}. A refused LINE is said
    now, by hand, in its seat's voice - no gate is asked again. A withheld round
    is not said from here (it is a whole exchange): the answer says so."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    row = FLOW_LEDGER.find(int((body or {}).get("n") or 0)) if isinstance(body, dict) else None
    if row is None:
        raise HTTPException(status_code=404, detail="That row is no longer in the ledger")
    if row.get("passed"):
        return {"ok": True, "said": False, "say": "That one was let through and already went out."}
    if row.get("approved"):
        return {"ok": True, "said": False, "say": "That one was already approved."}
    text = str(row.get("text") or "").strip()
    if not text or str(row.get("gate") or "").startswith("round:"):
        return {"ok": False, "said": False,
                "say": "This row is a whole round, not one line. With flow open a withheld round is "
                       "released by the Unstick everything rung or goes back on its own."}
    who = str(row.get("who") or "dj")
    if who not in ("dj", "cohost", "third", "drop"):
        who = "dj"
    said = await dj_speak("aside", None, line=text, who=who, by_hand=True, sting=False)
    FLOW_LEDGER.mark(int(row["n"]), approved=bool(said), approved_at=round(time.time(), 3))
    note_action("you approved a refused line: " + text[:80])
    return {"ok": bool(said), "said": bool(said), "text": text,
            "say": "Approved: it is going out." if said else "The booth did not put it out."}


@app.post("/api/flow/release")
'''

GATES_OLD = r'''    out = _speech_gates.view(globals(), speech_gates_stats)
    out["content"] = content_gate_status()
    return out
'''
GATES_NEW = r'''    out = _speech_gates.view(globals(), speech_gates_stats)
    out["content"] = content_gate_status()
    try:                            # [flow-ledger] the panel's Rejections list rides the same read
        out["flow"] = {"open": bool(S3_FLOW_OPEN), "counts": FLOW_LEDGER.counts(),
                       "rows": FLOW_LEDGER.recent(60)}
    except Exception:  # noqa: BLE001
        out["flow"] = {"open": False, "counts": {}, "rows": []}
    return out
'''

# ------------------------------------------------------------------ the panel
JS_PAINT_OLD = r'''    ui.body.appendChild(contentSection());
'''
JS_PAINT_NEW = r'''    ui.body.appendChild(contentSection());
    ui.body.appendChild(ledgerSection());
'''

JS_SECTION_OLD = r'''  function paint() {
    if (!ui.body) return;
'''
JS_SECTION_NEW = r'''  /* [flow-ledger] EVERY REJECTION, IN ONE LIST (#1570). "If the rejection system
   * is off, why is there still rejection occurring? I want to be able to see
   * and approve each and every rejection." The editorial switches above never
   * covered the checks below them. Each row is one line or round a check
   * wanted to refuse: "let through" means System 3 was asked and it aired,
   * "refused" means it did not - and Approve says a refused line now. */
  function ledgerSection() {
    var f = (ui.data && ui.data.flow) || {};
    var rows = f.rows || [];
    var sec = make('section', 'sg-gate');
    sec.appendChild(make('b', '', 'Rejections'));
    var refused = rows.filter(function (r) { return !r.passed; }).length;
    sec.appendChild(make('p', 'sg-says', 'Every line or round a check wanted to refuse, newest first. Flow is '
      + (f.open ? 'open: a check asks System 3 instead of refusing.' : 'closed: every check refuses as before.')
      + ' Showing ' + rows.length + ', ' + refused + ' of them refused.'));
    if (!rows.length) sec.appendChild(make('p', 'sg-says', 'Nothing has been refused or let through since the station started.'));
    rows.forEach(function (r) {
      var row = make('div', 'sg-ledger-row');
      var when = new Date(Number(r.at || 0) * 1000).toLocaleTimeString();
      var state = r.passed ? 'let through' : (r.approved ? 'approved' : 'refused');
      row.appendChild(make('b', '', when + ' - ' + state + ' - ' + String(r.gate || '').replace(/_/g, ' ')
        + (r.road ? ' - ' + r.road : '') + (r.who ? ' - ' + r.who : '')));
      row.appendChild(make('p', 'sg-says', String(r.why || '')));
      if (r.text) row.appendChild(make('p', 'sg-says', '"' + String(r.text) + '"'));
      if (!r.passed && !r.approved && r.text && String(r.gate || '').indexOf('round:') !== 0) {
        var b = make('button', '', 'Approve: say it now');
        b.type = 'button';
        b.title = 'Says this refused line now, in its own voice. No check is asked again.';
        b.addEventListener('click', function () { post('/api/flow-ledger/approve', {n: r.n}, 'Approved: it is going out.'); });
        row.appendChild(b);
      }
      sec.appendChild(row);
    });
    return sec;
  }

  function paint() {
    if (!ui.body) return;
'''

APP = [
    ("rhyme warm stands down", WARM_OLD, WARM_NEW, "# [tint-off] the rhyme index is the tint's own tool", 1),
    ("no plan without a tint", PLAN_OLD, PLAN_NEW, "# [tint-off] NO TINT, NO TINT PAPERWORK", 1),
    ("no line for a tint that never ran", STATUS_OLD, STATUS_NEW, "# [tint-off] a tint that never ran is not a line in the paper", 1),
    ("stored editions re-render", VERSION_OLD, VERSION_NEW, "PAPER_RENDER_VERSION = 14", 1),
    ("repair step stands down", STEP_OLD, STEP_NEW, "# [tint-off] with flow open the pen is not this step's work", 1),
    ("a dropped line is seen", DROP_OLD, DROP_NEW, "# [flow-ledger] every refusal is seen in one place", 1),
    ("a no-repeat refusal is seen", NOREPEAT_OLD, NOREPEAT_NEW, "# [flow-ledger] and the no-repeat rule's refusals with them", 1),
    ("a withheld round is seen", ROUND_OLD, ROUND_NEW, "# [flow-ledger] a withheld round is seen too", 1),
    ("approve a refusal", ROUTE_OLD, ROUTE_NEW, '@app.post("/api/flow-ledger/approve")', 1),
    ("the panel reads the ledger", GATES_OLD, GATES_NEW, "# [flow-ledger] the panel's Rejections list rides the same read", 1),
]
JS = [
    ("the Rejections list", JS_SECTION_OLD, JS_SECTION_NEW, "function ledgerSection() {", 1),
    ("it is painted", JS_PAINT_OLD, JS_PAINT_NEW, "ui.body.appendChild(ledgerSection());", 1),
]
EDITS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "app.py": APP,
    "desktop/renderer/speech-gates.js": JS,
    "app/src/main/assets/pine-views/speech-gates.js": JS,
}


def _read(path: Path) -> tuple[str, bool]:
    text = path.read_bytes().decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    return text, crlf


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
            print("%-34s (not in this tree - skipped)" % name)
            continue
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            _n, old, _new, probe, count = edit
            have = text.count(probe)
            state = ("applied" if have == count else
                     "ready" if not have and text.count(old) == count else
                     "missing (anchor found %d, probe %d)" % (text.count(old), have))
            print("%-34s %-34s %s" % (name[-34:], edit[0], state))
            if state == "ready":
                todo.append(edit)
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, crlf, todo))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, crlf, todo in plans:
        for _n, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _n)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _n, "probe")
        if todo:
            tmp = path.with_name(path.name + ".tintoff.tmp")
            tmp.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
