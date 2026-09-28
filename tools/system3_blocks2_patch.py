"""[s3-blocks] The rest of the writer's blocks: every block System 3's table
names is marked where its words enter a writer prompt.

tools/system3_blocks_patch.py built the door (ask_model decides every marked
block by System 3's `blocks` rules; call_ollama strips any marker left) and
marked the first blocks. DEFAULT_BLOCKS (system3_tables.py) also names
aside, avoid_reruns, battle, context, heat, modifiers, perf, playing,
review_guidance, sheet, system_prompt, theme, topic_contract and turn_rules,
and no site marked them - so they were sent and never decided, recorded or
switchable. This tool marks them:

  avoid_reruns, perf   the helper is renamed _<name>_raw and a marking
                       wrapper takes its name (both reach writer prompts only)
  context, aside,      marked where the builder makes them (dj_line, dj_banter,
  playing, sheet,      the advert road, the single-line road, the deep round,
  turn_rules,          the call rewrite)
  topic_contract,
  battle, system_prompt
  modifiers            its line belongs to patch_modifiers_1169, so its words
                       are found in the host layer and marked where they sit
  theme, heat, aside,  they ride INSIDE the round's angle, and the angle also
  topic_contract       reaches System 3's director, the call gates and the
  (in the angle)       fallback call script - so they are marked on the
                       prompt's copy only (_pb_within), never in `angle`
  review_guidance      the operator's wording examples are the system message
                       of ask_model: decided at the door beside the prompt's
                       own blocks and noted with them

With every block ON the words sent are byte for byte what was sent before -
the markers are removed at the door. Every anchor is unique in app.py and
none lies inside the stored text of another tool (see REPORT.md).

Idempotent: --check exits 0 ready / 2 applied / 1 missing; --apply writes LF
atomically. ON THE HOST.
"""
import os
import sys
import tempfile
from pathlib import Path

HELPERS = r'''# --- [s3-blocks] THE REST OF THE WRITER'S BLOCKS (system3_blocks2_patch) ------------
# Every block System 3's table names is marked somewhere. _pb_within marks a
# block whose words ride inside a string that also travels elsewhere (the
# round's angle, the host layer), on the prompt's copy only.
def _pb_within(name: str, text: Any, part: Any, after: str = "") -> str:
    """[s3-blocks] `text` with the last occurrence of `part` (just after
    `after`, when given) marked as block `name`. Unchanged when `part` is
    empty or not in it - the words still go, unmarked."""
    t, p, lead = str(text or ""), str(part or ""), str(after or "")
    if not p.strip():
        return t
    i = t.rfind(lead + p)
    if i < 0:
        return t
    i += len(lead)
    return t[:i] + _pb(name, p) + t[i + len(p):]


def avoid_reruns(*a: Any, **k: Any) -> str:
    return _pb("avoid_reruns", _avoid_reruns_raw(*a, **k))


def perf_directive(*a: Any, **k: Any) -> str:
    return _pb("perf", _perf_directive_raw(*a, **k))


def radio_prompt_instruction(slot: str) -> str:
'''

REVIEW_DOOR = r'''    # [s3-blocks] the operator's wording examples ride as the system message:
    # a node too (review_guidance), decided beside this prompt's own blocks
    # and noted with them under the digest of the words sent
    if _review_guidance:
        _rg_text, _rg_blocks = prompt_blocks_resolve(_pb("review_guidance", _review_guidance), mark)
        if _rg_blocks:
            _review_messages = ([{"role": "system", "content": _rg_text}] if _rg_text.strip() else []) \
                + [_m for _m in _review_messages if _m.get("role") != "system"]
            prompt_blocks_note(prompt, list(_s3_blocks or []) + list(_rg_blocks), mark)
    _learning_wire = _CRYSTAL_LEARNING_WIRE.get()
    if _learning_wire is not None:
'''

EDITS = [
    ("helpers",
     r'''def radio_prompt_instruction(slot: str) -> str:
''', HELPERS, 1),
    # --- the prompt-only helpers: renamed _raw, their marked wrappers above ---
    ("raw-avoid-reruns", r'''def avoid_reruns() -> str:
    out = banned_words_clause()
''', r'''def _avoid_reruns_raw() -> str:         # [s3-blocks] avoid_reruns() marks it
    out = banned_words_clause()
''', 1),
    ("raw-perf", r'''def perf_directive(vec: dict[str, float]) -> str:
''', r'''def _perf_directive_raw(vec: dict[str, float]) -> str:   # [s3-blocks] perf_directive() marks it
''', 1),
    # --- the host layer: #1169's modifiers, found where they sit ---
    ("mark-modifiers", r'''        # #1162: and, one round in five, the manager cutting into it. On
''', r'''        # [s3-blocks] #1169's standing modifiers, marked as their node where
        # they sit in `lead` (the line above is patch_modifiers_1169's own)
        try:
            lead = _pb_within("modifiers", lead, modifiers_clause())
        except Exception:  # noqa: BLE001
            pass
        # #1162: and, one round in five, the manager cutting into it. On
''', 1),
    # --- the schedule's clause: THE BATTLE, a tint node inside "schedule" ---
    ("mark-battle", r'''            + "\n" + rap_battle_clause()
''', r'''            + "\n" + _pb("battle", rap_battle_clause())   # [s3-blocks] a tint node
''', 1),
    # --- the station's own system prompt (#983), inside the disposition ---
    ("mark-system-prompt", r'''    return (
        "\n\nThe station is running under these standing instructions "
        "tonight. Let them colour your mood and your opinions — you are "
        f"still a radio DJ and this is still a music show:\n{text}"
    )
''', r'''    return _pb("system_prompt", (   # [s3-blocks] the station's system prompt (#983)
        "\n\nThe station is running under these standing instructions "
        "tonight. Let them colour your mood and your opinions — you are "
        f"still a radio DJ and this is still a music show:\n{text}"
    ))
''', 1),
    # --- dj_line: the record's facts and the speakerbox line ---
    ("mark-line-context", r'''    if kind == "intro" and extra:
        context += (
            f"\nWhat listeners say about it: {extra}\n"
            "Mention that reception naturally, as something people say, not "
            "as fact."
        )

    # An advert, a track intro, a passing remark — all of them get built
''', r'''    if kind == "intro" and extra:
        context += (
            f"\nWhat listeners say about it: {extra}\n"
            "Mention that reception naturally, as something people say, not "
            "as fact."
        )
    context = _pb("context", context)   # [s3-blocks] the record's facts

    # An advert, a track intro, a passing remark — all of them get built
''', 1),
    ("mark-line-aside", r'''        aside = speakbox_aside(seed, pair=False) if seed else ""
''', r'''        aside = _pb("aside", speakbox_aside(seed, pair=False)) if seed else ""   # [s3-blocks]
''', 1),
    # --- the advert road hands its swath to dj_line as `direct` ---
    ("mark-ad-aside", r'''            direct += speakbox_aside(seed, pair=False)
''', r'''            direct += _pb("aside", speakbox_aside(seed, pair=False))   # [s3-blocks]
''', 1),
    # --- the single-line road: System 3's running-order row(s) ---
    ("mark-line-sheet", r'''    _s3_sheet = (_s3_spoken_handle.sheet if _s3_spoken_handle is not None else "")
''', r'''    _s3_sheet = _pb("sheet", _s3_spoken_handle.sheet if _s3_spoken_handle is not None else "")   # [s3-blocks]
''', 1),
    # --- dj_deep_round: what is playing (its avoid_reruns is the wrapper) ---
    ("mark-deep-playing", r'''        + crystal_tint_note())
    try:
        script = await ask_model(
            prompt,
            # #786: 5200 truncated every deep round's tail — the prompt asks
''', r'''        + crystal_tint_note())
    prompt = _pb_within("playing", prompt, playing, after="THE ROOM RIGHT NOW: ")   # [s3-blocks]
    try:
        script = await ask_model(
            prompt,
            # #786: 5200 truncated every deep round's tail — the prompt asks
''', 1),
    # --- dj_banter: the parts that ride inside the angle, kept apart ---
    ("banter-angle-parts", r'''    comeback: dict[str, Any] = {}
    jab: dict[str, Any] = {}
    if angle and seed and str(seed.get("text") or ""):
''', r'''    comeback: dict[str, Any] = {}
    jab: dict[str, Any] = {}
    _angle_aside = _theme_said = _hot_said = ""   # [s3-blocks] blocks riding inside the angle
    if angle and seed and str(seed.get("text") or ""):
''', 1),
    ("banter-angle-aside", r'''        try:
            angle = str(angle) + speakbox_aside(seed, pair=True)
        except Exception:  # noqa: BLE001
            pass
''', r'''        try:
            _angle_aside = speakbox_aside(seed, pair=True)   # [s3-blocks] marked on the prompt's copy
            angle = str(angle) + _angle_aside
        except Exception:  # noqa: BLE001
            pass
''', 1),
    ("banter-theme", r'''    if _air_theme and not caller_name:
        angle += theme_air_clause(_air_theme, own_material=own_material)
''', r'''    if _air_theme and not caller_name:
        _theme_said = theme_air_clause(_air_theme, own_material=own_material)   # [s3-blocks]
        angle += _theme_said
''', 1),
    ("banter-heat", r'''        _hot = heat_reference()
        if _hot:
            angle += (" BURIED, IN PASSING: somewhere mid-conversation one of "
                      "you lets slip, as a throwaway aside and NOT the topic, a "
                      f"reference to how hot the machine is running — \"{_hot}\" "
                      "— a single glancing mention, then straight on.")
''', r'''        _hot = heat_reference()
        if _hot:
            _hot_said = (" BURIED, IN PASSING: somewhere mid-conversation one of "   # [s3-blocks]
                         "you lets slip, as a throwaway aside and NOT the topic, a "
                         f"reference to how hot the machine is running — \"{_hot}\" "
                         "— a single glancing mention, then straight on.")
            angle += _hot_said
''', 1),
    # --- dj_banter: what is playing and the speakerbox line worked in ---
    ("banter-playing-aside", r'''            lines = max(lines, min(3, dj["banter_max_lines"]))

    # Now and then the pair go LOOKING for approval (#322) — and the SFX
''', r'''            lines = max(lines, min(3, dj["banter_max_lines"]))
    # [s3-blocks] what is playing (the record; the only records that may be
    # named) and the speakerbox line worked in - each marked as its node;
    # they reach nothing but this round's writer prompts (one call, beats)
    playing, only_song = _pb("playing", playing), _pb("playing", only_song)
    aside = _pb("aside", aside)

    # Now and then the pair go LOOKING for approval (#322) — and the SFX
''', 1),
    # --- dj_banter's one call: how long a turn is, the running order ---
    ("banter-turn-rules", r'''            + (system2_turn_instruction(_system2_budget) if _system2_budget else
               "Each primary turn must be a developed four-to-seven-sentence "
               "thought, usually 60 to 100 words: specific, surprising, and "
               "responsive, never a one-sentence quip. ")
''', r'''            + _pb("turn_rules", system2_turn_instruction(_system2_budget) if _system2_budget else   # [s3-blocks]
                  "Each primary turn must be a developed four-to-seven-sentence "
                  "thought, usually 60 to 100 words: specific, surprising, and "
                  "responsive, never a one-sentence quip. ")
''', 1),
    ("banter-sheet-and-angle", r'''            + ("\n\n" + _beat_sheet if _beat_sheet else "")
        )
''', r'''            + (_pb("sheet", "\n\n" + _beat_sheet) if _beat_sheet else "")   # [s3-blocks]
        )
        # [s3-blocks] the blocks that ride INSIDE the round's angle - the
        # speakerbox passage worked into it, the operator's theme, the
        # machine-heat aside, a call's theme and topic contract - marked as
        # their own nodes on this prompt's copy only: `angle` travels on
        # unmarked (System 3's director, the call gates, the fallback script)
        _angle_parts: list[tuple[str, str]] = [("aside", _angle_aside), ("theme", _theme_said),
                                               ("heat", _hot_said)]
        try:
            if caller_name:
                _angle_parts.append(("theme", theme_air_clause(active_theme())))
                _angle_parts.append(("topic_contract", topic_contract_clause(
                    str((call_meta or {}).get("topic") or ""), caller_name)))
        except Exception:  # noqa: BLE001
            pass
        for _pb_name, _pb_part in _angle_parts:
            _one_call_prompt = _pb_within(_pb_name, _one_call_prompt, _pb_part)
''', 1),
    # --- dj_banter's rewrite: System 2's turn length, the topic contract ---
    ("rewrite-turn-rules", r'''                + (f"Write {lines} alternating turns. " + system2_turn_instruction(_system2_budget)
''', r'''                + (f"Write {lines} alternating turns. " + _pb("turn_rules", system2_turn_instruction(_system2_budget))   # [s3-blocks]
''', 1),
    ("rewrite-topic-contract", r'''                    + topic_contract_clause(                          # [#1249]
                        str((call_meta or {}).get("topic") or ""), caller_name)
''', r'''                    + _pb("topic_contract", topic_contract_clause(    # [#1249] [s3-blocks]
                        str((call_meta or {}).get("topic") or ""), caller_name))
''', 1),
    # --- ask_model's door: the wording examples (the system message) ---
    ("review-door", r'''    _learning_wire = _CRYSTAL_LEARNING_WIRE.get()
    if _learning_wire is not None:
''', REVIEW_DOOR, 1),
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
