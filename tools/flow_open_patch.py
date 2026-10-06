#!/usr/bin/env python3
"""[s3-flow-open] Dialogue flows; System 3 decides. 2026-10-05.

The operator: "remove all restrictive measures that are stopping dialogue from
going through the various channels ... roulettes handle everything, keeping
everything flowing no matter what ... only System 3 is handling and resolving
any of the issues that come up with dialogue being stale, repeated ..."

Measured that morning on the live station:
  * 879 finished rounds held in the final-handoff recovery queue
    (data/dialogue_recovery.json, 40.6 MB, rewritten back to back);
  * 7 phone calls written in an hour, 0 aired;
  * worker threads held the interpreter lock in 22 of 25 samples - the
    recovery queue's writer (deep copy + encode of the 40 MB queue) and
    manifest_store.pins() (71,146 files read once per stored take) were over
    half of them; the event loop stalled 31 times in ten minutes.

What this tool changes (every edit is marked and can be checked):
  app.py
    - s3_flow()/s3_flow_is_open(): a wedge asks System 3 (STATION1 "flow.<gate>",
      odds 1.0) instead of refusing; every answer is a row in the flow ledger.
    - a final handoff that fails no longer withholds the round, at the writer,
      at the mouth, or for a single line: the round stands as written.
    - finished stock is no longer pulled back into the recovery queue or retired
      as a "handoff candidate"; the flags those passes left stop being wedges.
    - the booth asks System 3 about an "incomplete conversation" instead of
      withholding it.
    - the recovery queue's held rounds go back to their shelves (a clock, and
      POST /api/flow/release); its writer runs once per 20 s at most.
    - GET /api/flow-ledger; POST /api/pine-requests/{id}/resolve honours
      "speak": false.
    - the Gazette pop-up paints the frame it opened (#1572); the gallery opens
      rather than toggles; the endless press's host has a height of its own.
  system3_runtime.py
    - handoff_exchange(recover=False): no rewrite passes, the refusal is
      answered at once; flow_bind_entry() binds a released draft to its plan.
  manifest_store.py
    - _guard_overwrite reads the pins only when it must.
  speech_gates.py
    - the "flow" gate: one switch that puts every wedge back.

Usage:  flow_open_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        flow_open_patch.py --apply [ROOT]   idempotent; writes each file atomically,
                                            keeping its line endings
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# app.py
# ---------------------------------------------------------------------------
A_HELPERS_OLD = r'''S3_COVERAGE = 0.66     # [s3-coverage] two thirds of the plan a round must bring to the booth
'''
A_HELPERS_NEW = r'''# --- [s3-flow-open] DIALOGUE FLOWS; SYSTEM 3 DECIDES ---------------------------
# "remove all restrictive measures that are stopping dialogue from going through
# the various channels ... roulettes handle everything, keeping everything
# flowing no matter what ... only System 3 is handling and resolving any of the
# issues that come up with dialogue being stale, repeated ..." (the operator,
# 2026-10-05). Measured that morning: 879 finished rounds held in the final-
# handoff recovery queue, 7 calls written in an hour and none aired. A wedge on
# the dialogue path now ASKS instead of refusing: s3_flow(gate, why) is a System
# 3 chance on the desk (STATION1 "flow.<gate>", odds 1.0 - walk a row down and
# that wedge refuses again at those odds), and every answer is a row in the flow
# ledger (GET /api/flow-ledger) - the one place every would-be rejection can be
# seen. The speech gate "flow.open" at 0 puts every wedge back as it was.
# s3_flow_is_open() is the cheap read for the readiness predicates, which run
# per row per poll and must neither roll nor write.
import flow_ledger as _flow_ledger

S3_FLOW_OPEN = 1
FLOW_LEDGER = _flow_ledger.Ledger(data_path("flow_ledger.jsonl"))


def s3_flow_is_open() -> bool:
    return bool(S3_FLOW_OPEN)


def s3_flow(gate: str, why: Any = "", *, odds: float = 1.0, road: str = "",
            text: Any = "", ref: Any = "") -> bool:
    """A wedge asks System 3 instead of refusing. True: the dialogue goes
    through. False: the wedge stands (flow is closed, or the desk's odds for
    this wedge said no). Either answer is recorded in the flow ledger."""
    if not S3_FLOW_OPEN:
        return False
    passed = True
    try:
        passed = bool(globals()["s3_chance"](
            "flow." + str(gate), float(odds),
            "a %s wedge lets the dialogue through instead of refusing it"
            % str(gate).replace("_", " ")))
    except Exception:  # noqa: BLE001 - a desk that cannot roll does not stop the air
        passed = True
    try:
        FLOW_LEDGER.note(str(gate), str(why or ""), passed=passed, road=str(road or ""),
                         text=str(text or ""), ref=str(ref or ""))
    except Exception:  # noqa: BLE001
        pass
    return passed


S3_COVERAGE = 0.66     # [s3-coverage] two thirds of the plan a round must bring to the booth
'''

A_WITHHELD_FLAG_OLD = r'''        if entry.get("handoff_unavailable"):
            return str((entry.get("handoff_unavailable") or {}).get("why") or "the final handoff candidate was retired")
        _active = globals().get("_s3_active")
'''
A_WITHHELD_FLAG_NEW = r'''        if entry.get("handoff_unavailable") and not s3_flow_is_open():   # [s3-flow-open] a retired handoff candidate is stock again
            return str((entry.get("handoff_unavailable") or {}).get("why") or "the final handoff candidate was retired")
        _active = globals().get("_s3_active")
'''

A_WITHHELD_SIG_OLD = r'''               id(dice_raw), len(dice_raw) if isinstance(dice_raw, dict) else -1)
        held = _S3_BIND_MEMO.get(id(entry))
'''
A_WITHHELD_SIG_NEW = r'''               id(dice_raw), len(dice_raw) if isinstance(dice_raw, dict) else -1,
               bool(S3_FLOW_OPEN))                      # [s3-flow-open] the switch re-asks every row
        held = _S3_BIND_MEMO.get(id(entry))
'''

A_WITHHELD_SHORT_OLD = r'''            if (planned < 3 or not s3_coverage_ok(len(positions), planned) or limit < len(positions)
                    or len({str(turns[i][0]) for i in positions}) < 2):
'''
A_WITHHELD_SHORT_NEW = r'''            if (limit < len(positions)
                    or (not s3_flow_is_open()            # [s3-flow-open] the booth asks System 3 about a short round
                        and (planned < 3 or not s3_coverage_ok(len(positions), planned)
                             or len({str(turns[i][0]) for i in positions}) < 2))):
'''

A_ROWFLAG_OLD = r'''        if row.get("handoff_unavailable") or (dialogue_entry(row) or {}).get("handoff_unavailable"):
            return False
'''
A_ROWFLAG_NEW = r'''        if (not s3_flow_is_open()                        # [s3-flow-open] the flag is a wedge only while flow is closed
                and (row.get("handoff_unavailable") or (dialogue_entry(row) or {}).get("handoff_unavailable"))):
            return False
'''

A_BOOTH_OLD = r'''        if ((not _native_single and (_s3_planned < 3 or not s3_coverage_ok(len(_s3_positions), _s3_planned)
                or len({str(turns[i][0]) for i in _s3_positions}) < 2))
                or limit < len(_s3_positions)):
'''
A_BOOTH_NEW = r'''        _s3_short = bool(not _native_single
                         and (_s3_planned < 3 or not s3_coverage_ok(len(_s3_positions), _s3_planned)
                              or len({str(turns[i][0]) for i in _s3_positions}) < 2))
        if (limit < len(_s3_positions)
                or (_s3_short and not s3_flow(             # [s3-flow-open] System 3 is asked; a short round airs what it has
                    "incomplete_conversation",
                    "%d of %d planned turns are bound" % (len(_s3_positions), _s3_planned),
                    road=str(ready_meta.get("prep_kind") or "banter"),
                    text=" / ".join(str(turns[i][1])[:90] for i in _s3_positions[:3]),
                    ref=str(_round_s3.get("conversation_id") or "")))):
'''

A_PREPARE_OLD = r'''    result = await prepare(
        handle, rows, writer, dj=dj_settings(), kind=kind, away=seat_away_who(),
        protected=hp.protected_rows(source, rows), assembly_trace={
            **dict(source.get("length_assembly") or {}),
            "tint_cuts": hp.tint_cut_receipt(source, globals().get("banter_turns"))})
'''
A_PREPARE_NEW = r'''    result = await prepare(
        handle, rows, writer, dj=dj_settings(), kind=kind, away=seat_away_who(),
        protected=hp.protected_rows(source, rows), assembly_trace={
            **dict(source.get("length_assembly") or {}),
            "tint_cuts": hp.tint_cut_receipt(source, globals().get("banter_turns"))},
        recover=not s3_flow_is_open())   # [s3-flow-open] no rewrite passes while flow is open: a refusal is answered at once
'''

A_HANDOFF_ENTRY_OLD = r'''    except WritingDeferred as exc:
        _dialogue_recovery_enqueue(entry, handle, str(exc), failed=False)
        raise
    except Exception as exc:
        _dialogue_recovery_enqueue(entry, handle, str(exc))
        raise
    hp.apply_script_result(entry, result, _dialogue_audio_drop)
'''
A_HANDOFF_ENTRY_NEW = r'''    except Exception as exc:
        # [s3-flow-open] A FINAL PASS THAT CANNOT SHAPE THE ROUND DOES NOT TAKE IT
        # OFF THE AIR. The round stands as it was written and goes on to its
        # bind; System 3 is asked (flow.final_handoff) and the answer is a row
        # in the flow ledger. Measured 2026-10-05: 879 rounds held here, the
        # oldest 48 hours, and every phone call of the hour among them.
        if s3_flow("final_handoff", "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                   road=str(entry.get("road") or entry.get("prep_kind") or "banter"),
                   text=str(rows[0][1] if rows else ""),
                   ref=str((entry.get("dialogue_recovery_handle") or entry.get("system3") or {})
                           .get("conversation_id") or "")):
            entry["handoff_flow"] = {"at": time.time(), "why": str(exc)[:240]}
            entry.pop("dialogue_recovery_pending", None)
            return False
        _dialogue_recovery_enqueue(entry, handle, str(exc),
                                   failed=not isinstance(exc, WritingDeferred))
        raise
    hp.apply_script_result(entry, result, _dialogue_audio_drop)
'''

A_BANTER_AIR_OLD = r'''    if entry.get("handoff_unavailable"):
        return _banter_no(str((entry.get("handoff_unavailable") or {}).get("why") or "the final handoff candidate was retired"))
    if isinstance(stamp, dict) and stamp.get("mode") == "active" and not hp.receipt_matches_script(entry):
'''
A_BANTER_AIR_NEW = r'''    if entry.get("handoff_unavailable") and not s3_flow_is_open():   # [s3-flow-open] no wedge at the mouth
        return _banter_no(str((entry.get("handoff_unavailable") or {}).get("why") or "the final handoff candidate was retired"))
    if (isinstance(stamp, dict) and stamp.get("mode") == "active" and not hp.receipt_matches_script(entry)
            and not s3_flow_is_open()):      # [s3-flow-open] the round airs as it was bound; no second review here
'''

A_RECOVER_SWEEP_OLD = r'''    eligibility = globals().get("system3_handoff_candidate_status")
    if not callable(eligibility):
        return 0
    retired = 0
'''
A_RECOVER_SWEEP_NEW = r'''    eligibility = globals().get("system3_handoff_candidate_status")
    if not callable(eligibility):
        return 0
    if s3_flow_is_open():            # [s3-flow-open] finished stock is not pulled back for review or retired
        return 0
    retired = 0
'''

A_CALL_AFTER_OLD = r'''            _after_handoff = call_entry_regrade(entry)
            if not _after_handoff.get("ok"):
                _radio_entry_rejected(entry, "handoff_call_contract_rejected")
'''
A_CALL_AFTER_NEW = r'''            _after_handoff = call_entry_regrade(entry)
            if not _after_handoff.get("ok") and not s3_flow_is_open():   # [s3-flow-open] the call banks either way
                _radio_entry_rejected(entry, "handoff_call_contract_rejected")
'''

A_LINE_OLD = r'''        except Exception as exc:
            pipeline_log("system3", "standalone line withheld: final handoff preparation failed",
                         extra=str(exc)[:300])
            return ""
'''
A_LINE_NEW = r'''        except Exception as exc:
            if not s3_flow("line_handoff", "%s: %s" % (type(exc).__name__, str(exc)[:200]),
                           road=str(kind), text=spoken):    # [s3-flow-open] the line goes out whole
                pipeline_log("system3", "standalone line withheld: final handoff preparation failed",
                             extra=str(exc)[:300])
                return ""
            _s3_split = None
'''

A_SAVE_OLD = r'''        try:
            while True:
                with _DIALOGUE_RECOVERY_LOCK:
                    if not _DIALOGUE_RECOVERY_DIRTY[0]:
                        break
'''
A_SAVE_NEW = r'''        try:
            while True:
                # [s3-flow-open] ONE WRITE PER 20 s AT MOST. Each write deep-copies
                # and encodes the whole queue under the interpreter lock (40 MB on
                # 2026-10-05, back to back: 7 of that morning's 25 lock samples).
                time.sleep(20.0)
                with _DIALOGUE_RECOVERY_LOCK:
                    if not _DIALOGUE_RECOVERY_DIRTY[0]:
                        break
'''

A_RELEASE_OLD = r'''def tint_recovery_rows() -> list[tuple[str, dict[str, Any]]]:
'''
A_RELEASE_NEW = r'''DIALOGUE_RECOVERY_PARKED_PATH = data_path("dialogue_recovery_parked.jsonl")


async def dialogue_recovery_release(limit: int = 0) -> dict[str, Any]:
    """[s3-flow-open] THE HELD ROUNDS GO BACK TO THEIR SHELVES.

    Every row of the recovery queue is a finished, written round that a final
    handoff pass refused; none of them could be recorded or aired while it sat
    here. With flow open a round stands as written, so the queue is emptied:
    a row that never aired is bound to its saved System 3 plan when it has no
    binding yet, loses the two flags that held it, and goes back where its
    kind lives - the larder for banter, its shelf for everything else - to be
    recorded and chosen like any other stock. A row that already aired, or
    has no words, simply leaves the queue. A row whose plan System 3 no longer
    holds cannot be explained by a roulette, so it is parked, never deleted
    (data/dialogue_recovery_parked.jsonl). `limit` > 0 takes that many rows."""
    out: dict[str, Any] = {"released": 0, "aired": 0, "empty": 0, "unbound": 0,
                           "busy": 0, "held": 0, "by_kind": {}, "errors": []}
    with _DIALOGUE_RECOVERY_LOCK:
        items = [it for it in _DIALOGUE_RECOVERY
                 if str(it.get("id") or "") not in _DIALOGUE_RECOVERY_ACTIVE]
    if limit and int(limit) > 0:
        items = items[:int(limit)]
    if not items:
        out["left"] = len(_DIALOGUE_RECOVERY)
        return out
    if not s3_flow("recovery_release", "%d held round(s) go back to their shelves" % len(items),
                   road="recovery", ref="queue"):
        out["held"] = len(items)
        out["left"] = len(_DIALOGUE_RECOVERY)
        return out
    bind = globals().get("system3_flow_bind_entry")
    done: set[str] = set()
    parked: list[dict[str, Any]] = []
    for n, item in enumerate(items):
        identifier = str(item.get("id") or "")
        entry = item.get("entry") if isinstance(item.get("entry"), dict) else None
        kind = str(item.get("kind") or (entry or {}).get("prep_kind") or "banter")
        try:
            if identifier in _DIALOGUE_RECOVERY_ACTIVE:
                out["busy"] += 1            # a repair pass took it since the list was read
                continue
            if entry is None or not str(entry.get("script") or "").strip():
                out["empty"] += 1
                done.add(identifier)
                continue
            if not row_unaired(entry):
                out["aired"] += 1
                done.add(identifier)
                continue
            if entry.get("preparing") or entry.get("tinting"):
                out["busy"] += 1
                continue
            stamp = entry.get("dialogue_recovery_handle") or {}
            s3 = entry.get("system3")
            if not (isinstance(s3, dict) and s3.get("mode") == "active" and s3.get("turns")):
                bound = False
                if callable(bind):
                    try:
                        bound = bool(await bind(entry, stamp))
                    except Exception:  # noqa: BLE001
                        bound = False
                if not bound:
                    out["unbound"] += 1
                    parked.append({"id": identifier, "kind": kind, "at": time.time(),
                                   "why": "System 3 no longer holds a plan this draft can bind to",
                                   "entry": entry})
                    done.add(identifier)
                    continue
            entry.pop("dialogue_recovery_pending", None)
            entry.pop("handoff_unavailable", None)
            entry["handoff_flow"] = {"at": time.time(), "why": "released from the recovery queue"}
            entry["prep_kind"] = str(entry.get("prep_kind") or kind)
            if kind == "banter":
                existing = next((i for i, row in enumerate(_LARDER)
                                 if (row.get("system3") or {}).get("conversation_id") == identifier), None)
                entry["expires_at"] = stock_expires_at(kind, entry)
                if existing is None:
                    _LARDER.append(entry)
                else:
                    _LARDER[existing] = entry
            else:
                existing_row = next((row for row in _SHELF.get(kind, [])
                                     if ((dialogue_entry(row) or {}).get("system3") or {})
                                     .get("conversation_id") == identifier), None)
                if existing_row is not None:
                    fresh = {**dict(item.get("shelf_row") or {}), **dict(existing_row), "entry": entry}
                    fresh.pop("dialogue_recovery_pending", None)
                    fresh.pop("handoff_unavailable", None)
                    _dialogue_audio_drop(fresh)
                    fresh["seconds"] = 0.0
                    existing_row.clear()
                    existing_row.update(fresh)
                else:
                    shelf_put(kind, {**dict(item.get("shelf_row") or {}), "entry": entry, "seconds": 0.0})
            out["released"] += 1
            out["by_kind"][kind] = int(out["by_kind"].get(kind) or 0) + 1
            done.add(identifier)
        except Exception as exc:  # noqa: BLE001 - one bad row does not stop the rest
            if len(out["errors"]) < 5:
                out["errors"].append("%s %s: %s: %s" % (kind, identifier[:12], type(exc).__name__, str(exc)[:120]))
        if n % 5 == 4:
            await asyncio.sleep(0)          # the air comes first
    with _DIALOGUE_RECOVERY_LOCK:
        _DIALOGUE_RECOVERY[:] = [row for row in _DIALOGUE_RECOVERY
                                 if str(row.get("id") or "") not in done]
        out["left"] = len(_DIALOGUE_RECOVERY)
    if not out["left"]:
        # The queue owned every row that carries its flag. With the queue empty,
        # a flag left on a larder or shelf copy would hold that copy for ever.
        stray = 0
        for row in list(_LARDER) + [r for rows in list(_SHELF.values()) for r in list(rows)]:
            for holder in (row, dialogue_entry(row)):
                if isinstance(holder, dict) and holder.pop("dialogue_recovery_pending", None):
                    stray += 1
        if stray:
            out["stray_flags"] = stray
    if parked:
        def _park() -> None:
            DIALOGUE_RECOVERY_PARKED_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(DIALOGUE_RECOVERY_PARKED_PATH, "a", encoding="utf-8") as fh:
                for row in parked:
                    fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        try:
            await asyncio.to_thread(_park)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append("parking failed: %s" % type(exc).__name__)
    try:
        _UNHEARD_MEMO.update(at=0.0, value=None)
        _INVENTORY_PLAN["at"] = 0.0
        _COMMITS["at"] = 0.0
    except Exception:  # noqa: BLE001
        pass
    _larder_save()
    _pantry_save(True)
    _dialogue_recovery_save()
    pipeline_log("system3", ("[s3-flow-open] %d held round(s) went back to their shelves; %d had aired, "
                             "%d parked without a plan, %d left in the queue"
                             % (out["released"], out["aired"], out["unbound"], out["left"]))[:200],
                 extra=json.dumps(out["by_kind"]))
    return out


async def flow_release_clock() -> None:
    """[s3-flow-open] Empty the recovery queue in small batches, the air first."""
    await asyncio.sleep(60)
    while True:
        pause = 30.0
        try:
            if s3_flow_is_open() and _DIALOGUE_RECOVERY and _s3_active():
                got = await dialogue_recovery_release(limit=20)
                if not (got.get("released") or got.get("aired") or got.get("empty") or got.get("unbound")):
                    pause = 300.0           # what is left is in use, or the desk said hold
            else:
                pause = 120.0
        except Exception as exc:  # noqa: BLE001
            pipeline_log("system3", "[s3-flow-open] the release pass failed",
                         extra=("%s: %s" % (type(exc).__name__, exc))[:200])
            pause = 120.0
        await asyncio.sleep(pause)


def tint_recovery_rows() -> list[tuple[str, dict[str, Any]]]:
'''

A_STEP_OLD = r'''    for item in list(_DIALOGUE_RECOVERY):
        entry = item["entry"]
        dialogue_recovery.recovery_state(entry)
'''
A_STEP_NEW = r'''    for item in ([] if s3_flow_is_open() else list(_DIALOGUE_RECOVERY)):   # [s3-flow-open] the queue is being emptied, not worked
        entry = item["entry"]
        dialogue_recovery.recovery_state(entry)
'''

A_NOREPEAT_OLD = r'''    if not seen:
        return ""
    return str(norepeat_refuse("line", str(seen.get("key") or ""), road or kind or who,
                               text=text).get("why") or "heard inside the day")
'''
A_NOREPEAT_NEW = r'''    if not seen:
        return ""
    # [s3-flow-open] A LINE HEARD INSIDE THE DAY ASKS SYSTEM 3 AT THE MOUTH. The
    # selectors still strike heard candidates before they roll, so a fresh
    # line is always preferred; this is the last gate, where a refusal leaves
    # nothing in the line's place - 390 holes in a day on 2026-10-05, most of
    # them station IDs, adverts and interjections drawn from pools too small
    # to stay fresh for 24 hours.
    if s3_flow("norepeat_line", "already on air %d min ago (%s)"
               % (int(float(seen.get("age") or 0) / 60), seen.get("road") or "?"),
               road=str(road or kind or who), text=text):
        return ""
    return str(norepeat_refuse("line", str(seen.get("key") or ""), road or kind or who,
                               text=text).get("why") or "heard inside the day")
'''

A_WORKER_OLD = r'''    radio_worker_start("page_recovery", page_recovery_start, persistent=False)
'''
A_WORKER_NEW = r'''    radio_worker_start("flow_release", flow_release_clock)      # [s3-flow-open] the held rounds go back
    radio_worker_start("page_recovery", page_recovery_start, persistent=False)
'''

A_ROUTES_OLD = r'''@app.patch("/api/orchestrator/content-gates")
'''
A_ROUTES_NEW = r'''@app.get("/api/flow-ledger")
async def api_flow_ledger(limit: int = 100, gate: str = "", held: int = -1,
                          authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[s3-flow-open] Every wedge that asked System 3 instead of refusing: the
    counts by wedge since the station started, and the latest rows (held=1 only
    the ones System 3 refused, held=0 only the ones that went through)."""
    require_read_auth(authorization)
    passed = None if int(held) < 0 else (int(held) == 0)
    queue = globals().get("_DIALOGUE_RECOVERY")
    return {"open": bool(S3_FLOW_OPEN), "counts": FLOW_LEDGER.counts(),
            "rows": FLOW_LEDGER.recent(max(1, min(500, int(limit))), gate=str(gate or ""), passed=passed),
            "recovery_queue": len(queue) if isinstance(queue, list) else 0}


@app.post("/api/flow/release")
async def api_flow_release(request: Request,
                           authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """[s3-flow-open] Send held recovery drafts back to their shelves now: {limit}."""
    require_auth(authorization)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    limit = int((body or {}).get("limit") or 0) if isinstance(body, dict) else 0
    return await dialogue_recovery_release(limit=limit)


@app.patch("/api/orchestrator/content-gates")
'''

A_RESOLVE_OLD = r'''        if phrase and _ha_creds()[0]:
            fire_and_forget_speech(
                speak(phrase, event="complete"))
'''
A_RESOLVE_NEW = r'''        if phrase and _ha_creds()[0] and payload.get("speak") is not False:   # [resolve-quiet] a bulk settle says nothing aloud
            fire_and_forget_speech(
                speak(phrase, event="complete"))
'''

A_PAPER_HEAD_OLD = r'''async function paperShow(id) {
  if (!paperFrame || !id) return;
  paperCur = id;
'''
A_PAPER_HEAD_NEW = r'''async function paperShow(id) {
  if (!paperFrame || !id) return;
  /* [paper-open-race] THE FRAME THIS CALL PAINTS. The window can be closed, or
     closed and opened again, while the edition is still on its way; the shared
     variable is then null or another frame, and writing to it threw "Cannot
     set properties of null (setting 'onload')" out of the opener (#1572). */
  const frame = paperFrame;
  paperCur = id;
'''

A_PAPER_BODY_OLD = r'''    const html = await r.text();
    if (paperCur !== id) return;
    paperFrame.onload = () => {
      if (paperCur !== id) return;
      paperPaintPages();
      paperTrackScroll();
      paperSnapAuto(id);
    };
    paperFrame.srcdoc = html;
  } catch (err) {
    paperFrame.onload = null;
    paperFrame.srcdoc = "<p style='font:14px Georgia;padding:20px'>" + String(err.message || err) + "</p>";
'''
A_PAPER_BODY_NEW = r'''    const html = await r.text();
    if (paperCur !== id || paperFrame !== frame) return;
    frame.onload = () => {
      if (paperCur !== id || paperFrame !== frame) return;
      paperPaintPages();
      paperTrackScroll();
      paperSnapAuto(id);
    };
    frame.srcdoc = html;
  } catch (err) {
    if (paperFrame !== frame) return;
    frame.onload = null;
    frame.srcdoc = "<p style='font:14px Georgia;padding:20px'>" + String(err.message || err) + "</p>";
'''

A_PAPER_REG_OLD = r'''open: () => paperOpen(),
   frame: {shade: () => paperBox, close: () => paperClose(),
'''
A_PAPER_REG_NEW = r'''open: () => (paperBox ? paperRefresh(true) : paperOpen()),   /* [paper-open-race] the gallery OPENS; only the bar button toggles */
   frame: {shade: () => paperBox, close: () => paperClose(),
'''

A_SLIDES_OLD = r'''  frame.src = "/api/paper/slideshow";
  win.host.appendChild(frame);
'''
A_SLIDES_NEW = r'''  frame.src = "/api/paper/slideshow";
  /* [press-popup] the frame fills its host, so the host needs a height of its
     own: laid out as a plain block (the desktop's tools window) it had none,
     and the pop-up was up and empty (#1572). */
  win.host.style.minHeight = "360px";
  win.host.appendChild(frame);
'''

# ---------------------------------------------------------------------------
# system3_runtime.py
# ---------------------------------------------------------------------------
R_BIND_OLD = r'''        return bool((entry.get("system3") or {}).get("conversation_id") == current["conversation_id"])

'''
R_BIND_NEW = r'''        return bool((entry.get("system3") or {}).get("conversation_id") == current["conversation_id"])

    async def flow_bind_entry(self, entry, stamp):
        """[s3-flow-open] Bind a released draft to its saved plan, as written.

        A round the final pass refused was never bound. With flow open it
        stands as written, so it is aligned with its plan the way every round
        was before the final pass existed: bind_entry's own alignment decides
        which turns bind. No receipt is required; a conversation that already
        has ledger lines is never bound again."""
        conv = await self._handoff_conversation(stamp)
        if not conv or conv.get("mode") != "active":
            return False
        if await self._handoff_committed(conv):
            return False
        config = await self._handoff_config(conv, stamp)
        self.bind_entry(entry, Handle(self, conv, config, True))
        bound = entry.get("system3") or {}
        return bool(bound.get("conversation_id") and bound.get("turns"))

'''

R_SIG_OLD = r'''    async def handoff_exchange(self, handle_or_stamp, rows, writer, dj=None, kind="", away="",
                               protected=None, assembly_trace=None):
'''
R_SIG_NEW = r'''    async def handoff_exchange(self, handle_or_stamp, rows, writer, dj=None, kind="", away="",
                               protected=None, assembly_trace=None, recover=True):   # [s3-flow-open]
'''

R_DEBT_OLD = r'''            debt = dialogue_recovery.recovery_state(cloned)
            recovering = bool(debt.get("active"))
            if recovering:
                now = time.time()
'''
R_DEBT_NEW = r'''            debt = dialogue_recovery.recovery_state(cloned)
            recovering = bool(debt.get("active"))
            if recovering and not recover:
                # [s3-flow-open] no recovery debt is paid while flow is open: the
                # caller is told at once and the round stands as written
                raise ValueError(str(debt.get("last_reason") or "the final pass refused this exchange earlier"))
            if recovering:
                now = time.time()
'''

R_GATE_OLD = r'''            except ValueError as exc:
                cloned = recovery_base
                cloned["dialogue_recovery_gate_reason"] = str(exc)
'''
R_GATE_NEW = r'''            except ValueError as exc:
                if not recover:
                    raise                       # [s3-flow-open] no rewrite passes: the caller decides
                cloned = recovery_base
                cloned["dialogue_recovery_gate_reason"] = str(exc)
'''

R_CALL_OLD = r'''            cloned, result = await self._finalize_handoff_recovery(
                cloned, config, source_rows, studio, writer, kind)
'''
R_CALL_NEW = r'''            cloned, result = await self._finalize_handoff_recovery(
                cloned, config, source_rows, studio, writer, kind, recover=recover)
'''

R_FIN_SIG_OLD = r'''    async def _finalize_handoff_recovery(self, base, config, source_rows, studio, writer, kind):
'''
R_FIN_SIG_NEW = r'''    async def _finalize_handoff_recovery(self, base, config, source_rows, studio, writer, kind, recover=True):
'''

R_FIN_RAISE_OLD = r'''            except ValueError as exc:
                if not state.get("policy", {}).get("enabled", True):
                    raise
'''
R_FIN_RAISE_NEW = r'''            except ValueError as exc:
                if not recover or not state.get("policy", {}).get("enabled", True):   # [s3-flow-open]
                    raise
'''

R_LOG_OLD = r'''            self.log("System 3 held the final exchange: " + why)
'''
R_LOG_NEW = r'''            self.log(("System 3 held the final exchange: " if recover else
                      "[s3-flow-open] the final pass did not shape the exchange; it stands as written: ") + why)
'''

R_NS_OLD = r'''    namespace["system3_recovery_bind_entry"] = rt.recovery_bind_entry
'''
R_NS_NEW = r'''    namespace["system3_recovery_bind_entry"] = rt.recovery_bind_entry
    namespace["system3_flow_bind_entry"] = rt.flow_bind_entry          # [s3-flow-open]
'''

# ---------------------------------------------------------------------------
# manifest_store.py
# ---------------------------------------------------------------------------
M_GUARD_OLD = r'''        existing = self.load_script(revision) if kind == "script" \
            else self.load(kind, revision, identifier)
        pins = self.pins()
        if kind == "script":
'''
M_GUARD_NEW = r'''        existing = self.load_script(revision) if kind == "script" \
            else self.load(kind, revision, identifier)
        # [pins-lazy] check_overwrite reads the pins in ONE case only: a
        # different record already stands at this id, under a kind that can be
        # pinned. Every other write - a new master, an identical rewrite, a
        # session, an admission - never looks at them, and pins() opens every
        # admission, assembly and cut of every revision (71,146 files on
        # 2026-10-05), under the interpreter lock, once per stored take.
        if (existing is None or not sm._PIN_BUCKET.get(str(kind), "")
                or sm._stable(existing) == sm._stable(replacement)):
            pins = {}
        else:
            pins = self.pins()
        if kind == "script":
'''

# ---------------------------------------------------------------------------
# speech_gates.py
# ---------------------------------------------------------------------------
G_GATE_OLD = r'''GATES: tuple[dict[str, Any], ...] = (
    {"id": "h3_sentence", "road": "Hourly H3 video dialogue",
'''
G_GATE_NEW = r'''GATES: tuple[dict[str, Any], ...] = (
    {"id": "flow", "road": "Every road",
     "name": "Dialogue flows; System 3 decides",
     "says": "A wedge on the dialogue path - a final handoff that fails, a conversation the booth calls "
             "incomplete, a draft held for recovery - asks System 3 instead of refusing. Each answer is a row "
             "in the flow ledger; the odds per wedge are the desk's STATION1 rows flow.*.",
     "params": (
         ("open", "Flow open (1) or every wedge refuses as before (0)", "At 1 a round airs as written when its "
          "final pass fails and held recovery drafts go back to their shelves.", "int", 1, 0, 1,
          "app.S3_FLOW_OPEN"),
     )},
    {"id": "h3_sentence", "road": "Hourly H3 video dialogue",
'''

# file -> [(name, old, new, probe, count)]
EDITS: dict[str, list[tuple[str, str, str, str, int]]] = {
    "app.py": [
        ("flow helpers", A_HELPERS_OLD, A_HELPERS_NEW, "FLOW_LEDGER = _flow_ledger.Ledger(", 1),
        ("binding: retired flag", A_WITHHELD_FLAG_OLD, A_WITHHELD_FLAG_NEW,
         "# [s3-flow-open] a retired handoff candidate is stock again", 1),
        ("binding: memo signature", A_WITHHELD_SIG_OLD, A_WITHHELD_SIG_NEW,
         "# [s3-flow-open] the switch re-asks every row", 1),
        ("binding: short round", A_WITHHELD_SHORT_OLD, A_WITHHELD_SHORT_NEW,
         "# [s3-flow-open] the booth asks System 3 about a short round", 1),
        ("ready/viable: retired flag", A_ROWFLAG_OLD, A_ROWFLAG_NEW,
         "# [s3-flow-open] the flag is a wedge only while flow is closed", 2),
        ("booth: incomplete conversation", A_BOOTH_OLD, A_BOOTH_NEW,
         "# [s3-flow-open] System 3 is asked; a short round airs what it has", 1),
        ("handoff rows: no rewrite passes", A_PREPARE_OLD, A_PREPARE_NEW,
         "# [s3-flow-open] no rewrite passes while flow is open", 1),
        ("handoff entry: the round stands", A_HANDOFF_ENTRY_OLD, A_HANDOFF_ENTRY_NEW,
         "# [s3-flow-open] A FINAL PASS THAT CANNOT SHAPE THE ROUND", 1),
        ("banter air: no review at the mouth", A_BANTER_AIR_OLD, A_BANTER_AIR_NEW,
         "# [s3-flow-open] no wedge at the mouth", 1),
        ("larder sweep stands down", A_RECOVER_SWEEP_OLD, A_RECOVER_SWEEP_NEW,
         "# [s3-flow-open] finished stock is not pulled back for review or retired", 1),
        ("call contract after handoff", A_CALL_AFTER_OLD, A_CALL_AFTER_NEW,
         "# [s3-flow-open] the call banks either way", 1),
        ("single line goes whole", A_LINE_OLD, A_LINE_NEW,
         "# [s3-flow-open] the line goes out whole", 1),
        ("recovery writer throttle", A_SAVE_OLD, A_SAVE_NEW,
         "# [s3-flow-open] ONE WRITE PER 20 s AT MOST", 1),
        ("release + clock", A_RELEASE_OLD, A_RELEASE_NEW, "async def dialogue_recovery_release(", 1),
        ("repair step leaves the queue", A_STEP_OLD, A_STEP_NEW,
         "# [s3-flow-open] the queue is being emptied, not worked", 1),
        ("no-repeat at the mouth asks", A_NOREPEAT_OLD, A_NOREPEAT_NEW,
         "# [s3-flow-open] A LINE HEARD INSIDE THE DAY ASKS SYSTEM 3 AT THE MOUTH", 1),
        ("release worker", A_WORKER_OLD, A_WORKER_NEW, 'radio_worker_start("flow_release"', 1),
        ("ledger routes", A_ROUTES_OLD, A_ROUTES_NEW, '@app.get("/api/flow-ledger")', 1),
        ("quiet resolve", A_RESOLVE_OLD, A_RESOLVE_NEW, "# [resolve-quiet]", 1),
        ("gazette: own frame", A_PAPER_HEAD_OLD, A_PAPER_HEAD_NEW, "[paper-open-race] THE FRAME THIS CALL PAINTS", 1),
        ("gazette: paint own frame", A_PAPER_BODY_OLD, A_PAPER_BODY_NEW,
         "if (paperCur !== id || paperFrame !== frame) return;\n    frame.onload", 1),
        ("gazette: gallery opens", A_PAPER_REG_OLD, A_PAPER_REG_NEW,
         "[paper-open-race] the gallery OPENS", 1),
        ("press: host height", A_SLIDES_OLD, A_SLIDES_NEW, "[press-popup] the frame fills its host", 1),
    ],
    "system3_runtime.py": [
        ("flow_bind_entry", R_BIND_OLD, R_BIND_NEW, "    async def flow_bind_entry(self, entry, stamp):", 1),
        ("handoff_exchange signature", R_SIG_OLD, R_SIG_NEW, "assembly_trace=None, recover=True):", 1),
        ("no debt paid", R_DEBT_OLD, R_DEBT_NEW,
         "# [s3-flow-open] no recovery debt is paid while flow is open", 1),
        ("no rewrite passes", R_GATE_OLD, R_GATE_NEW,
         "# [s3-flow-open] no rewrite passes: the caller decides", 1),
        ("finalize call", R_CALL_OLD, R_CALL_NEW, "studio, writer, kind, recover=recover)", 1),
        ("finalize signature", R_FIN_SIG_OLD, R_FIN_SIG_NEW, "studio, writer, kind, recover=True):", 1),
        ("finalize raise", R_FIN_RAISE_OLD, R_FIN_RAISE_NEW,
         'if not recover or not state.get("policy", {}).get("enabled", True):', 1),
        ("log line", R_LOG_OLD, R_LOG_NEW,
         '"[s3-flow-open] the final pass did not shape the exchange', 1),
        ("namespace", R_NS_OLD, R_NS_NEW, 'namespace["system3_flow_bind_entry"]', 1),
    ],
    "manifest_store.py": [
        ("lazy pins", M_GUARD_OLD, M_GUARD_NEW, "# [pins-lazy]", 1),
    ],
    "speech_gates.py": [
        ("flow gate", G_GATE_OLD, G_GATE_NEW, '{"id": "flow", "road": "Every road",', 1),
    ],
}


def _read(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    crlf = "\r\n" in text
    if crlf:
        if text.count("\r\n") != text.count("\n"):
            raise SystemExit("%s has mixed line endings; refusing to guess" % path)
        text = text.replace("\r\n", "\n")
    if "\r" in text:
        raise SystemExit("%s has bare carriage returns; refusing to guess" % path)
    return text, crlf


def _state(text: str, edit: tuple[str, str, str, str, int]) -> str:
    _name, old, _new, probe, count = edit
    have = text.count(probe)
    if have == count:
        return "applied"
    if have:
        return "partial (%d of %d probes)" % (have, count)
    found = text.count(old)
    return "ready" if found == count else "missing (anchor found %d, expected %d)" % (found, count)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    apply = argv[1] == "--apply"
    worst = 2                       # 2 = everything already applied
    plans: list[tuple[Path, str, bool, list[tuple[str, str, str, str, int]]]] = []
    for name, edits in EDITS.items():
        path = root / name
        text, crlf = _read(path)
        todo = []
        for edit in edits:
            state = _state(text, edit)
            print("%-22s %-38s %s" % (name, edit[0], state))
            if state == "ready":
                todo.append(edit)
                worst = min(worst, 0) if worst != 1 else 1
            elif state != "applied":
                worst = 1
        plans.append((path, text, crlf, todo))
    if worst == 1:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not apply:
        print("ready" if worst == 0 else "already applied")
        return worst
    for path, text, crlf, todo in plans:
        if not todo:
            continue
        for _name, old, new, probe, count in todo:
            assert text.count(old) == count, (path.name, _name)
            text = text.replace(old, new)
            assert text.count(probe) == count, (path.name, _name, "probe")
        out = text.replace("\n", "\r\n") if crlf else text
        tmp = path.with_name(path.name + ".flowopen.tmp")
        tmp.write_bytes(out.encode("utf-8"))
        os.replace(tmp, path)
        print("wrote %s (%d edit(s), %s)" % (path.name, len(todo), "CRLF" if crlf else "LF"))
    print("applied" if worst == 0 else "already applied")
    return 0 if worst == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
