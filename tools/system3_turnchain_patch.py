"""[s3-turnchain] Every message answers the one before it, and a copy never airs.

The operator, 2026-09-28: "the dialogue is duplicate ... they're not responding
to each other" and "in my eyes every message is rolling dice against the next
message." A request-line call (cc672e24) aired the caller's subject sentence
four times and the host's question five: the writer ran past the running order
and looped (43 turns for 15 rows); validate() saw it and nothing stopped it.

The station's half of System 3's copy gate (system3.gate_*, the runtime's
system3_turn_gate* doors - edit_turnchain_engine.py / edit_turnchain_runtime.py):

  1. AT THE BIND (dj_banter, every road it writes - banter, calls, recap, ad,
     news, the manager, the memo, the gallery, the mixtape, the open, fan
     mail, the guest - one-call writer and beat chain alike), after the
     writer and its rewrite and after the booth's cleaning (banter_turns):
     _s3_copy_gate walks the written turns in order. A turn that copies a line
     already said in the round, reads the subject / theme / a topic row back
     word for word, reads a speaker-box passage off its door, or is empty once
     cleaned is caught; a caught turn System 3 rolled is written again - one
     line, one model visit ("turn rewrite"), told the line it answers and its
     own dice - once or twice (prepared rounds; the round's visits are capped,
     protocol legs first); what still copies is dropped with the round's shape
     kept, and a round whose protocol leg cannot be written is WITHHELD.
  2. MODE B (_banter_beats): each line the beat chain is about to seat is
     checked (system3_beat_gate); a catch - or a line empty once cleaned - ends
     the beat there, so the retry writes that turn again, told what its draft
     repeated. An empty line no longer slides the rows a seat.
  3. AT THE MICROPHONE, ON EVERY ROAD: while System 3 is active a line that
     copies one said in the last few minutes is not said - dj_speak (every
     single-line road: the open, station IDs, record talk, interjections,
     requests, asides, spots, the manager's page) and speak_turns' turn loop
     (every unrecorded round) - recorded as a GATE observation on its node.
     2026-09-28 07:04: two "open" nodes aired "Lines are open at the station.
     Waiting on our first caller." back to back; #494's ring saw it and asked
     air_gate, which the (switched off) content gates answer.

Anchors: dj_banter just after the plot_label_scrub try (before the #1249 topic
contract); _banter_beats' signature, its write() (the correction, the empty
line, the clean.append/return pair) and its call site's director kwarg;
dj_speak's _floor_stage "(written)" line; speak_turns' rerun_check line; before
_s3_line_remember. None sits inside another tool's stored text (checked against
the booth's system3_booth_patch / turns_rownum_patch, forced1's banks roll).

--check exits 0 ready / 2 applied / 1 missing. --apply is idempotent and
atomic, LF only. ON THE HOST.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

SAID_OLD = r'''def _s3_line_remember(line_id: Any, stamp: Any, who: str = "", text: str = "") -> None:
'''
SAID_NEW = r'''# [s3-turnchain] THE LINE JUST SAID IS NOT SAID AGAIN, ON ANY ROAD. 2026-09-28 07:04:
# a TURNTABLE segment aired Dill's "Lines are open at the station. Waiting on our
# first caller." twice in a row - two single-line "open" nodes (b3e7f516, e331d73e)
# that each fell back to the stock phrase and drew the same one of its two, ten
# seconds apart. #494's near-duplicate ring saw it and asked air_gate, which the
# content-gate switch answers, and the switch is off. This is System 3's rule, not
# an editorial gate: while System 3 is active, a line that copies one said in the
# last few minutes at the station's mouths (dj_speak's single lines, speak_turns'
# unrecorded turns) is not said, and the refusal is a GATE observation on its node.
# Recorded rounds are gated before they are recorded (the copy gate at the bind).
S3_SAID_KEEP = 4                # the lines just said that a line may not copy
S3_SAID_WINDOW = 240.0          # ...said within this many seconds (a segment)
_S3_SAID: list[dict[str, Any]] = []


def _s3_said_copy(text: str, who: str = "", kind: str = "", ref: Any = None) -> str:
    """"" when `text` is a new line (it is then remembered as said); else why it
    copies a line just said - the caller does not say it."""
    copies = globals().get("system3_line_copies")
    if not callable(copies) or not str(text or "").strip() or not _s3_active():
        return ""
    now = time.time()
    recent = [r for r in _S3_SAID if now - float(r.get("at") or 0) <= S3_SAID_WINDOW][-S3_SAID_KEEP:]
    try:
        got = copies(str(text), [str(r.get("text") or "") for r in recent]) if recent else None
    except Exception:  # noqa: BLE001
        got = None
    if got:
        prev = recent[int(got.get("of") or 0)]
        why = ("it repeats the line %s said %d s ago (%s)"
               % (prev.get("who") or "the last voice", int(now - float(prev.get("at") or now)),
                  got.get("how") or "word for word"))
        note_drop(who, text, "System 3 copy gate: " + why)
        gate = globals().get("system3_line_gate")
        if callable(gate) and ref is not None:
            try:
                gate(ref, text, dict(got, why=why, kind=str(kind or "")))
            except Exception:  # noqa: BLE001
                pass
        return why
    _S3_SAID.append({"at": now, "text": str(text)[:600], "who": str(who or ""), "kind": str(kind or "")})
    del _S3_SAID[:-16]
    return ""


def _s3_line_remember(line_id: Any, stamp: Any, who: str = "", text: str = "") -> None:
'''

MOUTH_OLD = r'''    _floor_stage(f"a {kind} line from {who} (written)")
'''
MOUTH_NEW = r'''    _floor_stage(f"a {kind} line from {who} (written)")
    # [s3-turnchain] not a line just said, on any road (a round's own chunks come in
    # `checked`: speak_turns gated the whole turn upstream)
    if not by_hand and not checked and kind != "reply" and _s3_said_copy(
            spoken, who, kind, _s3_spoken_handle if _s3_spoken_handle is not None else system3):
        return ""
'''

TURNS_OLD = r'''        _rerun = rerun_check(text, who,
'''
TURNS_NEW = r'''        # [s3-turnchain] not a line just said - this round's or the one before it
        _s3_td = (turn_dice or {}).get(turn_index) or (turn_dice or {}).get(str(turn_index)) or {}
        if not by_hand and not allow_repeat and _s3_said_copy(
                text, who, "turn", _s3_td.get("s3") if isinstance(_s3_td, dict) else None):
            continue
        _rerun = rerun_check(text, who,
'''

BIND_OLD = r'''    try:
        script = plot_label_scrub(script)
    except Exception:  # noqa: BLE001
        pass
'''
BIND_NEW = r'''    try:
        script = plot_label_scrub(script)
    except Exception:  # noqa: BLE001
        pass
    # [s3-turnchain] THE COPY GATE, where the written lines are bound to the plan's
    # turns: every road written here, the one-call writer and the beat chain alike,
    # after the booth's cleaning (banter_turns). A copied turn is written again -
    # told the line it answers and its own dice - or dropped with the round's shape
    # kept; a round whose protocol leg cannot be written without copying is held.
    if _s3 is not None and getattr(_s3, "active", False):
        script, _s3_held = await _s3_copy_gate(script, _s3, caller_name, caller2_name,
                                               bool(bank) or bool(_system2_job))
        if _s3_held:
            if globals().get("system3_withhold"):
                globals()["system3_withhold"](_s3, "the copy gate held it: " + _s3_held[:200], "gate")
            pipeline_log("system3", "round withheld by the copy gate - " + _s3_held[:200],
                         extra=str(road or ("caller" if caller_name else "banter")))
            return []
'''

BEATS_SIG_OLD = r'''async def _banter_beats(context: str, sheet: str, lines: int,
                        seats: list[str], seed_text: str = "",
                        trace: list[dict[str, Any]] | None = None,
                        director: Any = None) -> str:
'''
BEATS_SIG_NEW = r'''async def _s3_copy_gate(script: str, handle: Any, caller_name: str = "",
                        caller2_name: str = "", prepared: bool = False) -> tuple[str, str]:
    """[s3-turnchain] System 3's copy gate over a written round: (the round as it
    airs, why it is held or ""). Each caught turn System 3 rolled is written again -
    one line, one model visit, told the line it answers and its own dice - while its
    tries and the round's visits last (prepared rounds only); what still copies is
    dropped with the round's shape kept. Any fault: the round goes on as written,
    and the log says so."""
    begin = globals().get("system3_turn_gate")
    if handle is None or not callable(begin) or not str(script or "").strip():
        return script, ""
    try:
        turns = banter_turns(script, caller_name, caller2_name)
        if not turns or not begin(handle, turns, [spoken_text(t) for _m, t in turns], bool(prepared)):
            return script, ""
        ask_next = globals()["system3_turn_gate_next"]
        reply = globals()["system3_turn_gate_reply"]
        clean = globals().get("writer_turn_clean")          # the booth's cleaner, when it is in
        for _visit in range(64):
            ask = ask_next(handle)
            if not ask:
                break
            raw = ""
            try:
                raw = await ask_model(
                    str(ask["prompt"]), limit=int(ask.get("limit") or 700), spice=0.5,
                    mark={"kind": "turn rewrite", "live": not prepared,
                          "turn": ask.get("turn"), "attempt": ask.get("attempt")})
            except Exception as exc:  # noqa: BLE001 - a full lane is a failed try, not a wait
                pipeline_log("system3", "a copied turn's re-write was not written: "
                             + type(exc).__name__, extra=str(exc)[:200])
            got = banter_turns(raw or "", caller_name, caller2_name)
            mine = [t for m, t in got if m == str(ask.get("seat") or "")]
            said = str((mine or [t for _m, t in got] or [raw or ""])[0])
            if callable(clean):
                said = str(clean(said))
            reply(handle, said, spoken_text(said))
        done = globals()["system3_turn_gate_done"](handle) or {}
    except Exception as exc:  # noqa: BLE001
        pipeline_log("system3", "the copy gate failed - the round goes on as written",
                     extra=("%s: %s" % (type(exc).__name__, exc))[:300])
        return script, ""
    if not done:
        return script, ""
    c = done.get("counts") or {}
    if done.get("changed") or done.get("held"):
        pipeline_log("system3", "copy gate: %d caught, %d re-written, %d dropped%s%s" % (
            int(c.get("caught") or 0), int(c.get("rewritten") or 0), int(c.get("dropped") or 0),
            (", %d written past the end" % int(c.get("trimmed") or 0)) if c.get("trimmed") else "",
            (" - HELD: " + str(done.get("held"))[:160]) if done.get("held") else ""))
    out = (str(done.get("script") or "") or script) if done.get("changed") else script
    return out, str(done.get("held") or "")


async def _banter_beats(context: str, sheet: str, lines: int,
                        seats: list[str], seed_text: str = "",
                        trace: list[dict[str, Any]] | None = None,
                        director: Any = None, gate: Any = None) -> str:
'''

BEATS_LIST_OLD = r'''    async def write(rows: list[dict[str, Any]], retry: bool = False
                    ) -> tuple[str, list[tuple[str, str]], bool]:
'''
BEATS_LIST_NEW = r'''    # [s3-turnchain] Mode B: what each caught draft repeated, for the retry to be told
    _beat_repeated: list[str] = []

    async def write(rows: list[dict[str, Any]], retry: bool = False
                    ) -> tuple[str, list[tuple[str, str]], bool]:
'''

BEATS_CORR_OLD = r'''            "completed transcript; every listed turn is a NEW line."
            if retry else "")
'''
BEATS_CORR_NEW = r'''            "completed transcript; every listed turn is a NEW line."
            if retry else "")
        if retry and _beat_repeated:                                          # [s3-turnchain]
            correction += ("\nIts draft of the first listed turn repeated " + _beat_repeated[-1]
                           + ". Write that turn as a NEW line that answers the line immediately above it.")
'''

BEATS_EMPTY_OLD = r'''        for row, candidate in zip(rows, parsed):
            text = spoken_text(candidate[1]).strip()
            if not text:
                continue
'''
BEATS_EMPTY_NEW = r'''        for row, candidate in zip(rows, parsed):
            text = spoken_text(candidate[1]).strip()
            if not text:
                if gate is not None:
                    # [s3-turnchain] empty once cleaned: the prefix ends here and the
                    # turn is written again - skipping it slid every row after it a seat
                    _beat_repeated.append("nothing (it was empty once cleaned)")
                    spoke_direction = True
                    break
                continue
'''

BEATS_CHECK_OLD = r'''            clean.append((str(row["seat"]), text))
        return raw, clean, (not spoke_direction) and _beat_sequence_answers(
'''
BEATS_CHECK_NEW = r'''            if gate is not None:
                # [s3-turnchain] a copy of a line already said (or the subject, a topic
                # row, a passage read back) ends the prefix too: the plan stays seated
                # and the retry - or the next beat - writes this turn again
                _copied = gate(made + clean, row, text)
                if _copied:
                    _beat_repeated.append(_copied)
                    spoke_direction = True
                    break
            clean.append((str(row["seat"]), text))
        return raw, clean, (not spoke_direction) and _beat_sequence_answers(
'''

BEATS_CALL_OLD = r'''                director=(globals()["system3_director"](_s3)
                          if globals().get("system3_director") else None))
'''
BEATS_CALL_NEW = r'''                director=(globals()["system3_director"](_s3)
                          if globals().get("system3_director") else None),
                gate=(globals()["system3_beat_gate"](_s3)                     # [s3-turnchain]
                      if globals().get("system3_beat_gate") else None))
'''

EDITS = [
    ("turnchain-said-ring", SAID_OLD, SAID_NEW, 1),
    ("turnchain-mouth-single", MOUTH_OLD, MOUTH_NEW, 1),
    ("turnchain-mouth-turns", TURNS_OLD, TURNS_NEW, 1),
    ("turnchain-bind-gate", BIND_OLD, BIND_NEW, 1),
    ("turnchain-beats-signature", BEATS_SIG_OLD, BEATS_SIG_NEW, 1),
    ("turnchain-beats-repeated", BEATS_LIST_OLD, BEATS_LIST_NEW, 1),
    ("turnchain-beats-correction", BEATS_CORR_OLD, BEATS_CORR_NEW, 1),
    ("turnchain-beats-empty", BEATS_EMPTY_OLD, BEATS_EMPTY_NEW, 1),
    ("turnchain-beats-check", BEATS_CHECK_OLD, BEATS_CHECK_NEW, 1),
    ("turnchain-beats-call", BEATS_CALL_OLD, BEATS_CALL_NEW, 1),
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
        if name == "turnchain-beats-signature" and state != "applied":
            # The live exchange gate extends this already-applied signature
            # with a verbatim opening for fixed source material.
            extended = new.replace("gate: Any = None) -> str:",
                                   "gate: Any = None,\n                        verbatim_seed: bool = False) -> str:")
            if extended != new and text.count(extended) == 1:
                state = "applied"
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
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
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
