"""[s3-blocks] Every block of a writer prompt is a System 3 node.

Operator, 2026-09-27 (multiple choice, answered): "Every block is a node:
every block in every prompt is either a roll with odds or a recorded
obligation. Nothing goes into a prompt unless System 3 put it there, and the
Prompt tab labels each block with the node that put it there." Fixed context
(persona, day, schedule, show memory, avoid-reruns) is an OBLIGATION, always
sent, each switchable; the station's randoms are ROLLS; a block no node claims
is STRIPPED and logged. And, finding THE BATTLE (#1090) in a prompt: "this
needs to be delegated to when the crystal is enabled and tinting is present"
(its block is kind "tint").

How: each prompt builder marks its blocks with the helper that made them
(_pb(name, text) - private-use sentinels, never sent). At the writer's door
(ask_model) System 3 decides every marked block (system3_blocks: obligation /
roll / tint / off / wedge), the prompt is rebuilt from what it kept, the
decisions are recorded on the round being written (BLOCK events) and noted
under the digest of the words sent (the Prompt tab reads them back). A road
that calls call_ollama directly never sends a marker: they are removed there.
System 3 off: every block is sent, markers removed - the station as it was.

This tool: the door (helpers, ask_model, call_ollama) and the marks in the
writer prompts (dj_line, dj_banter one-call and beats, dj_deep_round, the
schedule clause's own parts).

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

HELPERS = r'''# --- [s3-blocks] EVERY BLOCK OF A WRITER PROMPT IS A SYSTEM 3 NODE -----------------
# The builders mark each block with the helper that made it; ask_model's door
# asks System 3 about every marked block and sends only what it kept. The
# markers are private-use characters and never leave the station.
_PB_OPEN, _PB_MID, _PB_CLOSE = "", "", ""
_PB_TOKEN = re.compile("([a-z0-9_]{1,40}|)")
_PB_NAME = re.compile("([a-z0-9_]{1,40})")


def _pb(name: str, text: Any) -> str:
    """One block of a writer prompt, marked with its node's name."""
    t = str(text or "")
    if not t.strip():
        return t
    return _PB_OPEN + str(name) + _PB_MID + t + _PB_CLOSE


def _pb_unmark(text: Any) -> str:
    return _PB_TOKEN.sub("", str(text or ""))


def prompt_blocks_resolve(prompt: Any, mark: dict[str, Any] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """[s3-blocks] The words to send, and System 3's decision on each marked
    block (in order). A stripped block takes everything nested inside it;
    its words are kept on its decision (for the Prompt tab), never sent."""
    text = str(prompt or "")
    if _PB_OPEN not in text:
        return text, []
    names = _PB_NAME.findall(text)
    decisions = None
    fn = globals().get("system3_blocks")
    if fn and names:
        try:
            decisions = fn(names, dict(mark or {}), bool(dialogue_tint_wanted()),
                           {"personality": float(dj_settings().get("personality") or 0.7)})
        except Exception:  # noqa: BLE001
            decisions = None
    if not decisions:
        return _pb_unmark(text), []
    out: list[str] = []
    stack: list[dict[str, Any]] = []
    pos, k = 0, 0
    for m in _PB_TOKEN.finditer(text):
        seg = text[pos:m.start()]
        if seg:
            gone = next((e for e in stack if not e["d"].get("keep")), None)
            if gone is not None:
                gone["buf"].append(seg)
            else:
                out.append(seg)
        tok = m.group(0)
        if tok == _PB_CLOSE:
            if stack:
                e = stack.pop()
                if not e["d"].get("keep"):
                    e["d"]["text"] = " ".join("".join(e["buf"]).split())[:400]
        else:
            d = decisions[k] if k < len(decisions) else {"name": tok[1:-1], "keep": True, "kind": "unknown"}
            k += 1
            stack.append({"d": d, "buf": []})
        pos = m.end()
    tail = text[pos:]
    if tail and not any(not e["d"].get("keep") for e in stack):
        out.append(tail)
    return "".join(out), decisions


def prompt_blocks_note(prompt: Any, decisions: list[dict[str, Any]], mark: dict[str, Any] | None = None) -> None:
    """Keep System 3's decisions under the digest of the words actually sent."""
    if not decisions:
        return
    fn = globals().get("system3_note_prompt")
    if fn:
        try:
            fn(hashlib.sha1(str(prompt).encode("utf-8")).hexdigest()[:16], decisions, dict(mark or {}))
        except Exception:  # noqa: BLE001
            pass


# The prompt-only helpers return their text marked with their node's name (the
# helper itself is now _<name>_raw). A helper whose words also reach an API or
# a stored angle is marked where a writer prompt is assembled instead.
def day_context(*a: Any, **k: Any) -> str:
    return _pb("day", _day_context_raw(*a, **k))


def accent_directive(*a: Any, **k: Any) -> str:
    return _pb("accent", _accent_directive_raw(*a, **k))


def dj_disposition(*a: Any, **k: Any) -> str:
    return _pb("disposition", _dj_disposition_raw(*a, **k))


async def speakbox_flavor(*a: Any, **k: Any) -> str:
    return _pb("flavor", await _speakbox_flavor_raw(*a, **k))


def approach_clause(*a: Any, **k: Any) -> str:
    return _pb("approach", _approach_clause_raw(*a, **k))


def weather_clause(*a: Any, **k: Any) -> str:
    return _pb("weather", _weather_clause_raw(*a, **k))


def seat_away_clause(*a: Any, **k: Any) -> str:
    return _pb("seat_away", _seat_away_clause_raw(*a, **k))


def tail_lists_clause(*a: Any, **k: Any) -> str:
    return _pb("tail_lists", _tail_lists_clause_raw(*a, **k))


def brief_lesson_clause(*a: Any, **k: Any) -> str:
    return _pb("brief_lesson", _brief_lesson_clause_raw(*a, **k))


def call_novelty_prompt(*a: Any, **k: Any) -> str:
    return _pb("call_flow", _call_novelty_prompt_raw(*a, **k))


def crystal_tint_note(*a: Any, **k: Any) -> str:
    return _pb("crystal", _crystal_tint_note_raw(*a, **k))


def show_memory(own_material: bool = False, system3: bool = False) -> str:   # [s3-blocks] the marked door
    """Tonight so far - marked as its node only on a System 3 writer prompt."""
    text = _show_memory_raw(own_material=own_material, system3=system3)
    return _pb("show_memory", text) if system3 else text


def settings_web_search() -> bool:'''

EDITS = [
    ("helpers",
     r'''def settings_web_search() -> bool:''', HELPERS, 1),
    ("door",
     r'''        raise ValueError("Unknown model result contract")
    settings = load_settings()
''',
     r'''        raise ValueError("Unknown model result contract")
    # [s3-blocks] System 3 decides every marked block; only what it kept is sent
    prompt, _s3_blocks = prompt_blocks_resolve(prompt, mark)
    settings = load_settings()
''', 1),
    ("door-note",
     r'''    _review_messages.append({"role": "user", "content": prompt})
''',
     r'''    _review_messages.append({"role": "user", "content": prompt})
    prompt_blocks_note(prompt, _s3_blocks, mark)                              # [s3-blocks]
''', 1),
    ("never-marked",
     r'''    # #no-repeats: the options here carried temperature, top_p, num_predict and
''',
     r'''    # [s3-blocks] a marked block never reaches a model: a road that calls here
    # directly (not through ask_model's door) sends its words, markers removed
    messages = [dict(_m, content=_pb_unmark(_m["content"]))
                if isinstance(_m, dict) and isinstance(_m.get("content"), str) and _PB_OPEN in _m["content"] else _m
                for _m in (messages or [])]
    # #no-repeats: the options here carried temperature, top_p, num_predict and
''', 1),
    # --- the prompt-only helpers: renamed _raw, their marked wrappers above ---
    ("raw-day", r'''def day_context() -> str:
''', r'''def _day_context_raw() -> str:          # [s3-blocks] day_context() marks it
''', 1),
    ("raw-accent", r'''def accent_directive() -> str:
''', r'''def _accent_directive_raw() -> str:     # [s3-blocks] accent_directive() marks it
''', 1),
    ("raw-disposition", r'''def dj_disposition() -> str:
''', r'''def _dj_disposition_raw() -> str:       # [s3-blocks] dj_disposition() marks it
''', 1),
    ("raw-flavor", r'''async def speakbox_flavor() -> str:
''', r'''async def _speakbox_flavor_raw() -> str:   # [s3-blocks] speakbox_flavor() marks it
''', 1),
    ("raw-approach", r'''def approach_clause(rule: dict[str, Any]) -> str:
''', r'''def _approach_clause_raw(rule: dict[str, Any]) -> str:   # [s3-blocks] approach_clause() marks it
''', 1),
    ("raw-weather", r'''def weather_clause(rec: dict[str, Any] | None, caller_seat: str = "caller",
''', r'''def _weather_clause_raw(rec: dict[str, Any] | None, caller_seat: str = "caller",   # [s3-blocks]
''', 1),
    ("raw-seat-away", r'''def seat_away_clause() -> str:
''', r'''def _seat_away_clause_raw() -> str:     # [s3-blocks] seat_away_clause() marks it
''', 1),
    ("raw-tail-lists", r'''def tail_lists_clause(material: Any, pictures: Any,
''', r'''def _tail_lists_clause_raw(material: Any, pictures: Any,   # [s3-blocks]
''', 1),
    ("raw-brief-lesson", r'''def brief_lesson_clause() -> str:
''', r'''def _brief_lesson_clause_raw() -> str:  # [s3-blocks] brief_lesson_clause() marks it
''', 1),
    ("raw-call-novelty", r'''def call_novelty_prompt(exclude_plot: str = "") -> str:
''', r'''def _call_novelty_prompt_raw(exclude_plot: str = "") -> str:   # [s3-blocks]
''', 1),
    ("raw-crystal-note", r'''def crystal_tint_note(crystal: dict[str, Any] | None = None,
''', r'''def _crystal_tint_note_raw(crystal: dict[str, Any] | None = None,   # [s3-blocks]
''', 1),
    ("raw-show-memory", r'''def show_memory(own_material: bool = False, system3: bool = False) -> str:
''', r'''def _show_memory_raw(own_material: bool = False, system3: bool = False) -> str:   # [s3-blocks]
''', 1),
    # --- the persona and the desk's layer, marked in place ---
    ("mark-persona", r'''    return str(text or "") if radio_prompt_enabled(slot) else ""
''', r'''    return (_pb({"cohost": "cohost", "third": "third"}.get(str(slot), "persona"), str(text or ""))   # [s3-blocks]
            if radio_prompt_enabled(slot) else "")
''', 1),
    ("mark-schedule", r'''        lead = _schedule_prompt_clause() if slot == "host" else ""
''', r'''        lead = _pb("schedule", _schedule_prompt_clause()) if slot == "host" else ""   # [s3-blocks]
''', 1),
    ("mark-cut-in", r'''            lead += manager_cut_in_clause()
''', r'''            lead += _pb("manager_cut_in", manager_cut_in_clause())   # [s3-blocks]
''', 1),
    ("mark-lessons", r'''        lead += operator_lesson_clause(slot)
''', r'''        lead += _pb("lessons", operator_lesson_clause(slot))   # [s3-blocks]
''', 1),
    ("mark-desk", r'''    return lead + ("\n\nOPERATOR RADIO INSTRUCTION FOR THIS TURN: " + text
                   if text else "")
''', r'''    return lead + (_pb("desk_instruction", "\n\nOPERATOR RADIO INSTRUCTION FOR THIS TURN: " + text)   # [s3-blocks]
                   if text else "")
''', 1),
    # --- where dj_banter and dj_deep_round assemble their prompts ---
    ("mark-paper", r'''            + str(_paper_context.get("prompt") or "")
''', r'''            + _pb("paper", str(_paper_context.get("prompt") or ""))   # [s3-blocks]
''', 1),
    ("mark-pace", r'''            + f"{banter_pace(0 if caller_name else dj['overlap'])}\n"
''', r'''            + f"{_pb('pace', banter_pace(0 if caller_name else dj['overlap']))}\n"   # [s3-blocks]
''', 1),
    ("mark-angle", r'''            f"{angle}. Name the actual thing you are talking about. Play it "
''', r'''            f"{_pb('angle', angle)}. Name the actual thing you are talking about. Play it "   # [s3-blocks]
''', 1),
    ("mark-deep-plot", r'''        f"{day_context()}{accent_directive()}{plot_clause()}"
''', r'''        f"{day_context()}{accent_directive()}{_pb('plot', plot_clause())}"   # [s3-blocks]
''', 1),
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


# [wiring-reconcile 2026-10-06] later patches edited inside these blocks; the
# records below are the blocks as app.py holds them now (regenerated by a difflib
# alignment of each record against app.py - see tests/test_system3_wiring.py).
# The anchors are unchanged, so a fresh file is patched exactly as before.
_RECONCILED_2026_10_06 = {
    'door': '        raise ValueError("Unknown model result contract")\n    if result_schema is not None and result_contract != "json":\n        raise ValueError("A result schema requires the JSON contract")\n    if gazette_prompt.TOKEN.search(prompt):\n        prompt = (await gazette_prompt_messages([{"role": "user", "content": prompt}]))[0]["content"]\n    # [s3-blocks] System 3 decides every marked block; only what it kept is sent\n    prompt, _s3_blocks = prompt_blocks_resolve(prompt, mark)\n    settings = load_settings()\n',
    'never-marked': '    # [s3-blocks] a marked block never reaches a model: a road that calls here\n    # directly (not through ask_model\'s door) sends its words, markers removed\n    messages = [dict(_m, content=_pb_unmark(_m["content"]))\n                if isinstance(_m, dict) and isinstance(_m.get("content"), str) and _PB_OPEN in _m["content"] else _m\n                for _m in (messages or [])]\n    messages = await book_prompt_messages(messages)  # Source-bound books expand after other prompt controls.\n    # #no-repeats: the options here carried temperature, top_p, num_predict and\n',
}
EDITS = [(e[0], e[1], _RECONCILED_2026_10_06[e[0]], e[3]) if e[0] in _RECONCILED_2026_10_06 else e
         for e in EDITS]
