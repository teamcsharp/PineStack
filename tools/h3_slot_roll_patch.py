"""[h3-slot-roll] a {slot} in an hourly H3 prompt is a roll, and it shows.

2026-09-30, the operator (a preset's brief ending "... begs for people to
tune in {speakerbox}"): "make sure that if i use the { } commands in a
prompt. It means to roll a rolodex for that to be chosen at random. For
example. I want to see a rolodex roll for the doc and then the sentence used
for this."

Before this a {speakerbox} was filled by no road - h3_speak_fill took it out
and logged it. Now, before the station's own slots are filled:
  {speakerbox}   System 3 rolls a Speakerbox document (h3.slot_doc, weighted
                 as the Speakerbox weighs its shelf), then one of its whole,
                 speakable sentences (h3.slot_sentence) - that sentence fills it;
  {a|b|c}        System 3 rolls one of the options written (h3.slot_choice).
Each slot is rolled once and held for the hour (every field and every retry
of the hour says the same thing). The rolls ride the hour's record with the
options they were drawn from, so the ad viewer can spin a rolodex through
them and stop on what landed - the document, then the sentence.

Usage (ON THE HOST): python3 tools/h3_slot_roll_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[h3-slot-roll]"

AT = '''def h3_speak_fill(template: Any, quiet: bool = False, **values: Any) -> str:
    """h3_prompts_fill, with {station} and {hour} always known; a {slot} no
    road fills is taken out (and logged) - never sent as written."""
    values.setdefault("station", h3_speak_station())
'''
NEW = '''# [h3-slot-roll] {speakerbox} and {a|b|c} in an hourly prompt are ROLLS
H3_SLOT_RX = re.compile(r"\\{(speakerbox|[^{}|\\n]+(?:\\|[^{}|\\n]+)+)\\}")
H3_SLOT_KEEP_S = 1800.0
H3_SLOT_OPTS = 40
_H3_SLOT_MEMO: dict[str, Any] = {"at": 0.0, "vals": {}}


def _h3_slot_last(key: str) -> dict[str, Any]:
    fn = globals().get("system3_last_roll")
    try:
        rec = fn(key) if fn else None
    except Exception:  # noqa: BLE001
        rec = None
    return rec if isinstance(rec, dict) else {}


def _h3_slot_note(name: str, key: str, opts: list[str], picked: str) -> None:
    """The roll onto the hour's record, with what it was drawn from."""
    h3_hourly_roll_note(name, key)
    got = _H3_HOURLY_ROLLS.get(name)
    if isinstance(got, dict):
        got["opts"] = [str(o)[:140] for o in opts[:H3_SLOT_OPTS]]
        got["picked"] = str(picked)[:300]


def _h3_slot_speakerbox() -> str:
    """A Speakerbox document, then one of its sentences - both System 3's."""
    try:
        files = speakbox_files()
        weights, uses = mind_weights(""), speakbox_uses("")
        shelf = [(p, speakbox_weight(p.name, weights, "", uses)) for p in files]
    except Exception:  # noqa: BLE001
        shelf = []
    shelf = [(p, w) for p, w in shelf if w > 0]
    for _attempt in range(H3_SPEAK_DOC_TRIES):
        if not shelf:
            break
        names = [p.name for p, _ in shelf]
        k = s3_weighted("h3.slot_doc", names, [float(w) for _, w in shelf],
                        "which Speakerbox document a {speakerbox} in an hourly H3 prompt rolls")
        k = k if isinstance(k, int) and 0 <= k < len(shelf) else 0
        path = shelf.pop(k)[0]
        said = []
        for _i, s in _h3_speak_doc_read(path):
            s = h3_speak_normalize(s)
            if s and not h3_speak.sentence_why(s) and s not in said:
                said.append(s)
            if len(said) >= 120:
                break
        if not said:
            continue
        # the document's roll, drawn from the shelf as it stood (it is listed from the picked one on)
        _h3_slot_note("slot_doc", "h3.slot_doc", names[max(0, k - H3_SLOT_OPTS // 2):][:H3_SLOT_OPTS]
                      if len(names) > H3_SLOT_OPTS else names, path.name)
        j = s3_weighted("h3.slot_sentence", [s[:80] for s in said], [1.0] * len(said),
                        "which sentence of the rolled Speakerbox document a {speakerbox} says")
        j = j if isinstance(j, int) and 0 <= j < len(said) else 0
        _h3_slot_note("slot_sentence", "h3.slot_sentence", said, said[j])
        pipeline_log("ads", "hourly H3 prompts: {speakerbox} rolled %s, then \\"%s\\" [h3-slot-roll]"
                     % (path.name, said[j][:80]))
        return said[j]
    pipeline_log("ads", "hourly H3 prompts: {speakerbox} - no Speakerbox document rolled had a speakable sentence")
    return ""


def _h3_slot_choice(tok: str) -> str:
    opts = [o.strip() for o in tok.split("|") if o.strip()]
    if not opts:
        return ""
    got = s3_choice("h3.slot_choice", opts, "which of the options written in an hourly H3 prompt's {a|b|c} is used")
    got = got if got in opts else opts[0]
    _h3_slot_note("slot_choice", "h3.slot_choice", opts, got)
    return got


def h3_slots_roll(template: Any) -> str:
    """[h3-slot-roll] every {speakerbox} and {a|b|c} rolled - once per hour."""
    text = str(template or "")
    if "{" not in text:
        return text
    now = time.time()
    if now - float(_H3_SLOT_MEMO["at"]) > H3_SLOT_KEEP_S:
        _H3_SLOT_MEMO.update(at=now, vals={})

    def one(m: Any) -> str:
        tok = m.group(1)
        vals = _H3_SLOT_MEMO["vals"]
        if tok not in vals:
            try:
                vals[tok] = _h3_slot_speakerbox() if tok == "speakerbox" else _h3_slot_choice(tok)
            except Exception as exc:  # noqa: BLE001
                pipeline_log("ads", "hourly H3 prompts: {%s} could not be rolled (%s)" % (tok[:40], type(exc).__name__))
                vals[tok] = ""
        return vals[tok]

    return H3_SLOT_RX.sub(one, text)


def h3_speak_fill(template: Any, quiet: bool = False, **values: Any) -> str:
    """h3_prompts_fill, with {station} and {hour} always known; a {slot} no
    road fills is taken out (and logged) - never sent as written."""
    template = h3_slots_roll(template)                                       # [h3-slot-roll]
    values.setdefault("station", h3_speak_station())
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(AT) == 1, "anchor"
    out = src.replace(AT, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-h3-slot-roll")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
