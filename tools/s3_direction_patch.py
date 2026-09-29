#!/usr/bin/env python3
"""[s3-direction] DIRECTION FOR THIS LINE - the rolls drive the writing.

THE OPERATOR, 2026-09-29: "the roulette results are used as direction for the
prompt when composing the dialogue for that character for that exchange ... the
characters lists then categories and grabbing advanced randomized direction that
is given to the prompt to tell it how to handle that line" and "I want the
emotional acting to be over the top and exaggerated ... people sounding and
acting emotional when the node result calls for it."

MEASURED (3 h of air, 770 aired seat lines, every one with an ES roll; the exact
prompts from data/prompt_history.sqlite3): the ES direction reached 493 of the
716 prompts found, but inside an ~800-character running-order row it came AFTER
the act, the legs, the graph's "Internally ..." and "Deliver this in a playful
intonation" (on a fury turn), and "Allow about 3 seconds"; the row's own feeling
word said "(plainly)" or "(mildly)". One '!' in 100 lines of the one-call
writer's raw output; 20% of high-arousal rolls left any mark in the words.

THE CURE, in system3.py (the one place a roll becomes the writer's words):
  1. es_acting()/acting_scale(): an ES row may carry `acting` ({act, blurts,
     says, wants}; category, then item over it) - stamped on the decision at
     plan time (dec["acting"]) so the words need no config later.
  2. direction_block(): the rolls on a turn, in roll order - the character, the
     ES family, the feeling and its intensity, how big to play it, the item's
     direction, the first words (blurts, quoted so the echo gate never cuts a
     line for saying one), the lexicon, what they want, the temper under it and
     the shock beat over it.
  3. _row_work: the block comes RIGHT AFTER what the turn does (its lead, act
     and flow - the row's first clause, which the #1386 grammar, the #1462
     first-clause check and the tests pin) and before the legs, the seconds, the
     passages and the round's adds: near the seat letter the model writes, in the
     running order that is the last thing in the one-call prompt. Measured in the
     sandbox: at the END of the row the model hung the block on the NEXT row's
     seat (a fury written by the wrong speaker); at the head it did not. The row's
     "feeling X (plainly) about it" goes (the block carries it, at its own
     strength); the graph node's "Deliver this in a X intonation" is not laid over
     a rolled feeling. A fixed-words row (opener, seeded passage, answer line) is
     as it was.
  4. _leg_row_add / annotate_protocol (calls, legs, single lines): the bracket
     keeps "[Say it in X, hard; while doing it, ..." and ends on the block where
     the ES sentence was.
  5. render_sheet's header says how to read the block and that the rolled feeling
     outranks any calm, dry or measured register above it; render_call_sheet's
     scenario register yields to a rolled feeling.
  6. scaffold_kit: DIRECTION FOR THIS LINE is a row label (an echo of it is cut).

Target: system3.py under the repo root given (default "."). --check exits 0
ready / 2 applied / 1 missing or partial; --apply is idempotent (markers),
atomic and keeps the file's own line endings. ON THE HOST.
"""
import sys

S3 = "system3.py"

EDITS = [
    (S3, "acting-helpers",
     'def _es_base_arousal(config, spec):\n',
     '# --- [s3-direction] DIRECTION FOR THIS LINE ----------------------------------------\n'
     '# The operator, 2026-09-29: "the roulette results are used as direction for the\n'
     '# prompt ... the characters lists then categories and grabbing advanced randomized\n'
     '# direction" and "I want the emotional acting to be over the top and exaggerated".\n'
     '# An ES row may carry `acting` - act (the playable verb, in writing terms), blurts\n'
     '# (first words out, quoted), says (its lexicon), wants (intention and goal) - on\n'
     '# the category, with the item\'s own keys over it (the Tables tab).\n'
     'DIRECTION_LABEL = "DIRECTION FOR THIS LINE"\n'
     'ACTING_KEYS = ("act", "blurts", "says", "wants")\n'
     '\n'
     '\n'
     'def es_acting(config, spec):\n'
     '    """[s3-direction] The acting of an ES pick: the item\'s `acting` over its\n'
     '    category\'s, cleaned ({act, blurts, says, wants}); {} when neither row has\n'
     '    one. Nothing is drawn."""\n'
     '    cat, item = _es_row(config, spec)\n'
     '    out = {}\n'
     '    for row in (cat, item):\n'
     '        got = (row or {}).get("acting")\n'
     '        if not isinstance(got, dict):\n'
     '            continue\n'
     '        for k in ACTING_KEYS:\n'
     '            v = got.get(k)\n'
     '            if k in ("blurts", "says"):\n'
     '                v = [" ".join(str(x).split())[:60] for x in (v if isinstance(v, list) else [])\n'
     '                     if str(x).strip()][:5]\n'
     '                if v:\n'
     '                    out[k] = v\n'
     '            elif str(v or "").strip():\n'
     '                out[k] = " ".join(str(v).split())[:240]\n'
     '    return out\n'
     '\n'
     '\n'
     'def acting_scale(intensity):\n'
     '    """[s3-direction] How big a line is played, by its ES intensity."""\n'
     '    x = float(intensity or 0)\n'
     '    return ("ALL THE WAY UP, over the top and bigger than life" if x >= 0.72\n'
     '            else "BIG, broad and unmistakable" if x >= 0.4\n'
     '            else "OUT LOUD, it shows in every word")\n'
     '\n'
     '\n'
     'def _es_base_arousal(config, spec):\n',
     'DIRECTION_LABEL = "DIRECTION FOR THIS LINE"\n'),

    (S3, "acting-stamp",
     '            dec["direction"] = es_direction(config, spec, turn["name"])\n',
     '            dec["direction"] = es_direction(config, spec, turn["name"])\n'
     '            dec["acting"] = es_acting(config, spec)                           # [s3-direction] how it is played\n',
     '# [s3-direction] how it is played\n'),

    (S3, "direction-block",
     'def _row_work(turn, conv):\n',
     'def direction_block(turn, conv=None):\n'
     '    """[s3-direction] The rolls on this turn as the writer\'s DIRECTION FOR THIS\n'
     '    LINE, in roll order: the character, the ES family, the feeling and how hard,\n'
     '    how big to play it, the item\'s direction, then its acting - the first words\n'
     '    (quoted: saying one is never a direction\'s echo), the lexicon, what they\n'
     '    want - the temper under it and the shock beat over it. "" when no feeling\n'
     '    was rolled."""\n'
     '    es = next((d for d in turn.get("decisions") or [] if d.get("family") == "ES" and d.get("item")), None)\n'
     '    if not es:\n'
     '        return ""\n'
     '    name = " ".join(str(turn.get("name") or turn.get("speaker") or "the speaker").split())\n'
     '    perf = turn.get("performance") or {}\n'
     '    inten = float(perf.get("intensity") if perf.get("intensity") is not None else (es.get("intensity") or 0))\n'
     '    feeling = str(es.get("label") or perf.get("emotion") or es.get("item"))\n'
     '    fam = str(es.get("category") or perf.get("family") or "").replace("_", " ").upper()\n'
     '    turns = (conv or {}).get("turns") or []\n'
     '    i = int(turn.get("index") or 0)\n'
     '    prev = turns[i - 1] if 0 < i <= len(turns) else None\n'
     '    prev_name = str((prev or {}).get("name") or (prev or {}).get("speaker") or "")\n'
     '    out = "%s (%s): %sfeeling %s (%s)%s - PLAY IT %s." % (\n'
     '        DIRECTION_LABEL, name, (fam + " > ") if fam else "", feeling, _intensity_word(inten),\n'
     '        (" about %s\'s line" % prev_name) if prev_name else "", acting_scale(inten))\n'
     '    said = " ".join(str(es.get("direction") or "").split())\n'
     '    if said:\n'
     '        out += " " + (said if said.endswith((".", "!", "?")) else said + ".")\n'
     '    acting = es.get("acting") if isinstance(es.get("acting"), dict) else {}\n'
     '    if acting.get("act") and acting["act"].lower() not in said.lower():\n'
     '        out += " " + acting["act"].rstrip(".") + "."\n'
     '    if acting.get("blurts"):\n'
     '        out += (" First words out, something LIKE %s - a fresh one, never the same twice."\n'
     '                % " / ".join(json.dumps(x) for x in acting["blurts"]))\n'
     '    if acting.get("says"):\n'
     '        out += (" Words they reach for, inside their own sentences and never read out as a list: %s."\n'
     '                % ", ".join(json.dumps(x) for x in acting["says"][:3]))\n'
     '    if acting.get("wants"):\n'
     '        out += " What %s wants: %s." % (name, acting["wants"].rstrip("."))\n'
     '    temper = ((conv or {}).get("tempers") or {}).get(turn.get("speaker")) or {}\n'
     '    if temper.get("text"):\n'
     '        out += " Under it all tonight: %s." % str(temper["text"]).rstrip(".")\n'
     '    if (turn.get("shock") or {}).get("text"):\n'
     '        out += " Then it BOILS OVER: openly %s." % str(turn["shock"]["text"]).upper()\n'
     '    return out\n'
     '\n'
     '\n'
     'def _row_work(turn, conv):\n',
     'def direction_block(turn, conv=None):\n'),

    (S3, "row-direction",
     '    answer_line = replying and bool(answer_text)\n',
     '    answer_line = replying and bool(answer_text)\n'
     '    # [s3-direction] the rolls close the row; a line whose words are fixed keeps its feeling word only\n'
     '    _dir = "" if (answer_line or (turn["index"] == 0 and bool(exchange.get("opener") or conv["subject"].get("seeded")))) \\\n'
     '        else direction_block(turn, conv)\n'
     '    if _dir:\n'
     '        feel = ""\n',
     '# [s3-direction] the rolls close the row;'),

    (S3, "row-intonation",
     '    if turn.get("graph_intonation"):\n',
     '    if turn.get("graph_intonation") and not _dir:                            # [s3-direction] the roll is the intonation\n',
     '# [s3-direction] the roll is the intonation\n'),

    (S3, "row-es-sentence",
     '    _es = "" if _fixed else _es_line(turn)\n',
     '    _es = "" if (_fixed or _dir) else _es_line(turn)                        # [s3-direction] the block says it\n',
     '# [s3-direction] the block says it\n'),

    (S3, "row-after-work",
     '    body = " - ".join(x for x in (lead, desc) if x)\n',
     '    body = " - ".join(x for x in (lead, desc) if x)\n'
     '    if _dir:                                                                  # [s3-direction] right after what the turn does\n'
     '        body = (body.rstrip(".") + ". " if body else "") + _dir.rstrip(".")\n',
     '# [s3-direction] right after what the turn does\n'),

    (S3, "legs-es-sentence",
     '        _es = "" if any(x.get("family") == "LINE" for x in t.get("decisions") or []) else _es_line(t)\n',
     '        _es = "" if any(x.get("family") == "LINE" for x in t.get("decisions") or []) \\\n'
     '            else (direction_block(t) or _es_line(t))                          # [s3-direction] legs, calls, lines\n',
     '# [s3-direction] legs, calls, lines\n'),

    (S3, "protocol-bracket",
     '            if _es_line(t):                                                   # [s3-es-dir]\n'
     '                add += ". " + _es_line(t).rstrip(".")\n',
     '            _d = direction_block(t, conv) or _es_line(t)                      # [s3-direction] protocol sheets\n'
     '            if _d:                                                            # [s3-es-dir]\n'
     '                add += ". " + _d.rstrip(".")\n',
     '# [s3-direction] protocol sheets\n'),

    (S3, "sheet-header",
     '    return ("\\n\\nTHE RUNNING ORDER OF THIS EXCHANGE. Write exactly these turns, in this order, one line "\n'
     '            "each, and nothing else. Each line says the feeling to speak in and what the turn does - "\n'
     '            "perform both, never name them:" + _tempers_line(conv) + "\\n" + "\\n".join(rows) +\n',
     '    return ("\\n\\nTHE RUNNING ORDER OF THIS EXCHANGE. Write exactly these turns, in this order, one line "\n'
     '            "each, and nothing else. Each row says what the turn does, then gives its DIRECTION FOR THIS "\n'
     '            "LINE - who speaks, the feeling family, the feeling and how hard. ACT IT OVER THE TOP: the "\n'
     '            "feeling is in the first words out of their mouth, in every word they pick, in the punctuation "\n'
     '            "(! and ?! and one word in CAPS when it is big) and in what they are after; a rolled feeling "\n'
     '            "outranks anyone\'s usual manner and any calm, dry or measured register above. Perform both, "\n'
     '            "never name them and never read a direction out:"                  # [s3-direction]\n'
     '            + _tempers_line(conv) + "\\n" + "\\n".join(rows) +\n',
     '"never name them and never read a direction out:"                  # [s3-direction]\n'),

    (S3, "call-scenario",
     '        text += "\\n" + str(call["scenario_clause"])\n',
     '        text += "\\n" + str(call["scenario_clause"])\n'
     '        if any(direction_block(t) for t in turns):                           # [s3-direction] the roll outranks it\n'
     '            text += (" Where a turn\'s DIRECTION FOR THIS LINE rolls a feeling, that feeling outranks the "\n'
     '                     "register and the heat named here.")\n',
     '# [s3-direction] the roll outranks it\n'),

    (S3, "scaffold-label",
     '    rows = {SUBJECT_LABEL: set(), LEAD_LABEL: {LEAD_WHY}, EVENT_LABEL: set()}\n',
     '    rows = {SUBJECT_LABEL: set(), LEAD_LABEL: {LEAD_WHY}, EVENT_LABEL: set(),\n'
     '            DIRECTION_LABEL: set()}                                          # [s3-direction]\n',
     '            DIRECTION_LABEL: set()}                                          # [s3-direction]\n'),
    (S3, "graph-no-turn-numbers",
     '                        turn["protocol"] += (" Return to your point in turn %d and answer the initiator\'s"\n'
     '                                             " rebuttal in turn %d directly."\n'
     '                                             % (original["index"] + 1, rebuttal["index"] + 1))\n',
     '                        # [s3-direction] never a turn number: the writer said "the point I made in turn two"\n'
     '                        turn["protocol"] += (" Return to the point you made earlier and answer %s\'s rebuttal"\n'
     '                                             " directly." % str(rebuttal.get("name") or rebuttal.get("speaker")\n'
     '                                                                or "the initiator"))\n',
     '# [s3-direction] never a turn number:'),

    (S3, "feel-prefix-rx",
     'def strip_scaffold(text, kit=None):\n',
     '# [s3-direction] a rolled feeling said as a label - "Suspicion: ...", "Disbelief: ...",\n'
     '# "In fury, hard: ..." (aired 2026-09-29) - is the direction, not a word: the label goes.\n'
     '_FEEL_RX = []\n'
     '\n'
     '\n'
     'def _feel_prefix_rx():\n'
     '    """[s3-direction] A line (or a line of a turn) that opens on an ES label with a colon or a dash."""\n'
     '    if not _FEEL_RX:\n'
     '        labels = set()\n'
     '        for table in (getattr(system3_tables, "ES1", None), getattr(system3_tables, "ES1_V2", None)):\n'
     '            for cat in (table or {}).get("categories") or []:\n'
     '                labels.update((str(cat.get("id") or "").replace("_", " "), str(cat.get("label") or "")))\n'
     '                labels.update(str(i.get("label") or "") for i in cat.get("items") or [])\n'
     r'        alts = sorted({r"[ \t]+".join(re.escape(w) for w in x.split()) for x in labels if x.strip()},' '\n'
     '                      key=len, reverse=True)\n'
     '        _FEEL_RX.append(re.compile(\n'
     r'            r"(?im)^([ \t\x22\u201c' "']*)" r'(?:(?:in|feeling)[ \t]+)?(?:%s)"' '\n'
     r'            r"(?:[ \t]*\((?:mildly|plainly|hard)\)|,[ \t]*(?:mildly|plainly|hard))?"' '\n'
     r'            r"[ \t]*(?::|[ \t][-\u2013\u2014])[ \t]*" % "|".join(alts)))' '\n'
     '    return _FEEL_RX[0]\n'
     '\n'
     '\n'
     'def strip_scaffold(text, kit=None):\n',
     'def _feel_prefix_rx():\n'),

    (S3, "feel-prefix-strip",
     '    if cut:\n'
     '        # the row number that rode in with it is not a word either\n',
     '    _fs = _feel_prefix_rx().sub(lambda m: m.group(1), s)                      # [s3-direction] the label goes\n'
     '    if _fs != s:\n'
     r'        s = re.sub(r"(?m)^([ \t\x22\u201c' "']*)" r'([a-z])", lambda m: m.group(1) + m.group(2).upper(), _fs)' '\n'
     '        cut = True\n'
     '    if cut:\n'
     '        # the row number that rode in with it is not a word either\n',
     '# [s3-direction] the label goes\n'),
]

# --- the edit engine (shared by the s3_direction_* tools) ---
import os
import tempfile
from pathlib import Path


def _load(root, rel):
    raw = (Path(root) / rel).read_bytes().decode("utf-8")
    crlf = raw.count("\r\n") > raw.count("\n") // 2 and "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def _state(text, anchor, marker):
    m = text.count(marker)
    if m == 1:
        return "applied", ""
    a = text.count(anchor)
    if m == 0 and a == 1:
        return "ready", ""
    return "missing", "marker %d time(s), anchor %d time(s) (want 1)" % (m, a)


def check(root, edits, quiet=False):
    files = {}
    for e in edits:
        if e[0] not in files:
            files[e[0]] = _load(root, e[0])
    states = []
    for rel, name, anchor, new, marker in edits:
        st, why = _state(files[rel][0], anchor, marker)
        states.append((rel, name, st, why))
        if not quiet:
            print("%-8s %s: %s %s" % (st, rel, name, why))
    return states, files


def verdict(states):
    kinds = {s[2] for s in states}
    if kinds == {"ready"}:
        return 0
    if kinds == {"applied"}:
        return 2
    return 1


def apply(root, edits):
    states, files = check(root, edits, quiet=True)
    if verdict(states) == 2:
        print("already applied (%d edits)" % len(states))
        return 2
    if any(s[2] == "missing" for s in states):
        for s in states:
            print("%-8s %s: %s %s" % (s[2], s[0], s[1], s[3]))
        return 1
    texts = {rel: files[rel][0] for rel in files}
    for (rel, name, anchor, new, marker), (_r, _n, st, _w) in zip(edits, states):
        if st == "applied":
            continue
        assert texts[rel].count(anchor) == 1, name
        texts[rel] = texts[rel].replace(anchor, new, 1)
        assert texts[rel].count(marker) == 1, "%s: marker not unique after the edit" % name
    for rel, text in texts.items():
        path = Path(root) / rel
        out = text.replace("\n", "\r\n") if files[rel][1] else text
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "wb") as fh:
            fh.write(out.encode("utf-8"))
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, path)
    states, _f = check(root, edits, quiet=True)
    if verdict(states) != 2:
        print("apply did not leave every edit applied")
        return 1
    print("applied %d edits" % len(edits))
    return 0


def main(argv, edits, doc):
    args = [a for a in argv if not a.startswith("--")]
    root = args[0] if args else "."
    if "--apply" in argv:
        return apply(root, edits)
    if "--check" in argv:
        states, _f = check(root, edits)
        return verdict(states)
    print(doc)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], EDITS, __doc__))
