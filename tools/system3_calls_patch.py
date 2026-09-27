"""Calls are built by System 3: every leg a node, rolled through the Rolodex.

Operator, 2026-09-27: "calls should also go through system 3 and be
constructed through RNG and the rolodex system. Every segment should be
comprised of nodes going through the rolodex made in a way that can be
customized, expanded and altered. Nothing is outside of system 3. It takes
over everything."

Until now a call's running order was the STATION's (#1392 call_beat_sheet)
and System 3 only annotated it (plan_protocol / annotate_protocol). Now:

  system3_tables.py   DEFAULT_CALL_STRUCTURE - the call protocol as System 3
                      nodes: each leg its act (the contract's own words,
                      editable), its draws (ES on every leg, RS/FL where the
                      protocol leaves the turn open) and its place (open,
                      middle - repeated to the turn budget - or close).
  system3.py          config["structures"]["caller"]; plan_call() plans a
                      call from it, every leg rolled; render_call_sheet()
                      writes THE RUNNING ORDER OF THIS CALL from the plan -
                      the same legs call_flow_report reads, each row with
                      the delivery its dice chose.
  system3_runtime.py  the call's facts reach System 3 (who rings, the other
                      host, the call's own passage, story call-back, the
                      scenario direction); an ACTIVE call is planned by
                      plan_call and its sheet is System 3's.
                      PUT /api/system3/structures/{road} edits a road's
                      structure (legs added, removed, reworded, re-drawn).
  app.py              the direct hook hands System 3 the call_meta; a System
                      3 call whose write fails is dropped - never the
                      built-in template (#805), which ignores every roll -
                      and the next call is rolled fresh.

A story call-back (the hosts already know this person) has no protocol by
design (call_beat_sheet returns "") and keeps the old road. SHADOW calls are
planned and recorded but the station's sheet goes out.

Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes the files. ON THE HOST.
"""
import sys
from pathlib import Path

TABLES = [
    ("def default_tables():\n",
     r'''# [s3-calls] THE REQUEST-LINE CALL AS SYSTEM 3 NODES. Each leg is one leg of
# call_flow_report, in the order the checker reads them, written as the turn
# that satisfies it (the words #1392's call_beat_sheet gave the writer). A
# leg's `place` is open (the fixed opening), middle (repeated until the turn
# budget is met, seats alternating back from the landing so a host always
# speaks before it) or close. {FIRST}/{first} is the caller's first name.
# Every leg rolls ES; the legs the protocol leaves open roll RS and FL too.
DEFAULT_CALL_STRUCTURE = {
    "id": "call_protocol", "label": "[Request-line call]", "version": 1, "kind": "protocol",
    "min_turns": 9, "max_turns": 22, "caller_share": 0.38,
    "legs": [
        {"id": "answer", "label": "Answer the line", "place": "open", "seat": "A",
         "act": "ANSWER THE RINGING LINE. Say the word \"line\" or \"call\" out loud - \"the request line is "
                "ringing, you're live, go ahead\". You do NOT know who this is: do not say any name.",
         "draws": [{"family": "ES"}]},
        {"id": "introduce", "label": "The caller introduces themself", "place": "open", "seat": "C",
         "act": "{FIRST} INTRODUCES THEMSELF and nothing more. Say \"I'm {first}\" or \"{first} here\". "
                "Under thirty words. Do NOT start the story yet.",
         "draws": [{"family": "ES"}]},
        {"id": "greet", "label": "Greet them by name", "place": "open", "seat": "A",
         "act": "GREET THEM BY NAME. Say \"{first}\" out loud, then ask the first question.",
         "draws": [{"family": "ES"}]},
        {"id": "detail_1", "label": "The first detail", "place": "open", "seat": "C",
         "act": "answers, and gives one CONCRETE detail - a thing, a place, a number, a name.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "ask_1", "label": "Ask about it", "place": "open", "seat": "A",
         "act": "ASK ABOUT THAT EXACT DETAIL. Repeat the caller's own word back inside your question. "
                "This is the one the check counts; a general question does not count.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "detail_2", "label": "The second detail", "place": "open", "seat": "C",
         "act": "answers it, and gives a second concrete detail.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "ask_2", "label": "Ask about the second", "place": "open", "seat": "B",
         "act": "ASK ABOUT THAT SECOND DETAIL, using the caller's own word again. Two of these are required.",
         "draws": [{"family": "ES"}, {"family": "RS"}]},
        {"id": "keeps_going", "label": "Keeps it going", "place": "middle", "seat": "alternate",
         "act": "keeps it going; every turn answers the one before it and quotes a word from it.",
         "draws": [{"family": "ES"}, {"family": "RS"}, {"family": "FL", "tables": ["FL2"]}]},
        {"id": "lands", "label": "The caller lands it", "place": "close", "seat": "C",
         "act": "{FIRST} LANDS IT. The caller says the last word of their own story here. This must be "
                "the SECOND TO LAST turn of the whole call.",
         "draws": [{"family": "ES"}]},
        {"id": "sign_off", "label": "Sign off", "place": "close", "seat": "A",
         "act": "SIGN OFF. The final turn is a host, and it must contain one of these words out loud: "
                "thanks, thank you, goodbye, goodnight, take care, appreciate.",
         "draws": [{"family": "ES"}]},
    ],
    "head": "THE RUNNING ORDER OF THIS CALL. This is a request-line call and it has a protocol; write "
            "exactly these turns, in this order, one line each, nothing else. {first} has about "
            "{caller_turns} of the turns.",
    "material": "--  SOMEWHERE IN THE MIDDLE, one of you must bring up this, in your own words, and "
                "{first} must react to it: {passage}",
    "tail": "Every one of those is checked after you write it, and a call that misses one is thrown "
            "away unheard - so the two questions that repeat the caller's own words, the caller speaking "
            "second to last, and the spoken sign-off on the last turn are not style notes. They are the call.",
}
PLACES = ("open", "middle", "close")


def default_structures():
    """[s3-calls] One structure per road System 3 builds from its own nodes."""
    return {"caller": copy.deepcopy(DEFAULT_CALL_STRUCTURE)}


def validate_structure(road, st):
    """A road structure an operator may save: legs with ids, a place, a seat
    and draws of known families. Returns the list of problems."""
    out = []
    legs = st.get("legs") if isinstance(st, dict) else None
    if not isinstance(legs, list) or not legs:
        return ["the %s structure needs legs" % road]
    ids = set()
    for leg in legs:
        if not isinstance(leg, dict) or not str(leg.get("id") or "").strip():
            out.append("every leg needs an id")
            continue
        if leg["id"] in ids:
            out.append("leg %s appears twice" % leg["id"])
        ids.add(leg["id"])
        if leg.get("place") not in PLACES:
            out.append("leg %s: place must be one of %s" % (leg["id"], ", ".join(PLACES)))
        if str(leg.get("seat") or "") not in ("A", "B", "C", "D", "E", "alternate"):
            out.append("leg %s: seat must be A-E or alternate" % leg["id"])
        for d in leg.get("draws") or []:
            if not isinstance(d, dict) or d.get("family") not in ("ES", "RS", "IRS", "FL", "CTS"):
                out.append("leg %s: unknown draw %r" % (leg["id"], d))
    if not [leg for leg in legs if isinstance(leg, dict) and leg.get("place") == "close"]:
        out.append("the %s structure needs a closing leg" % road)
    return out


def default_tables():
'''),
]

ENGINE = [
    ('            "structure": system3_tables.default_structure(),\n',
     '            "structure": system3_tables.default_structure(),\n'
     '            # [s3-calls] one structure per road System 3 builds from its own nodes\n'
     '            "structures": system3_tables.default_structures(),\n'),
    ('def config_hash(config):\n'
     '    return digest({k: config.get(k) for k in\n'
     '                   ("schema", "tables", "structure", "speakerbox", "sfx", "personalities")})\n',
     'def config_hash(config):\n'
     '    keys = ("schema", "tables", "structure", "speakerbox", "sfx", "personalities")\n'
     '    # [s3-calls] a config saved before road structures keeps its hash\n'
     '    if "structures" in config:\n'
     '        keys += ("structures",)\n'
     # tools/system3_roads_patch.py (system3.py side): the SFX Guy's section
     '    if "sfxguy" in config:                       # [s3-roads]\n'
     '        keys += ("sfxguy",)\n'
     '    return digest({k: config.get(k) for k in keys})\n'),
    ('# --- the running order ----------------------------------------------------\n',
     r'''def road_structure(config, road):
    """[s3-calls] The structure System 3 builds `road` from: the config's own,
    else the default (a config saved before road structures has none)."""
    got = (config.get("structures") or {}).get(road)
    return got if isinstance(got, dict) and got.get("legs") else system3_tables.default_structures().get(road)


def _call_words(text, call, extra=None):
    first = str(call.get("first") or "the caller")
    values = {"first": first, "FIRST": first.upper(), "other": str(call.get("other") or "the co-host")}
    values.update(extra or {})
    out = str(text or "")
    for key, val in values.items():
        out = out.replace("{%s}" % key, str(val))
    return out


def plan_call(conv, config, inputs=None):
    """[s3-calls] A request-line call, planned from System 3's own call
    structure: the open legs in order, the middle leg repeated to the turn
    budget (seats alternating back from the landing, so a host speaks just
    before it), then the closing legs - every leg a turn with its own rolls.
    The TOPIC roll may raise something off the board on a middle leg."""
    inputs = inputs if inputs is not None else conv["inputs"]
    call = inputs.get("call") or {}
    st = road_structure(config, "caller") or {}
    legs = [dict(x) for x in st.get("legs") or [] if isinstance(x, dict)]
    opening = [x for x in legs if x.get("place") == "open"]
    middle = [x for x in legs if x.get("place") == "middle"]
    closing = [x for x in legs if x.get("place") == "close"]
    lo, hi = int(st.get("min_turns") or 9), int(st.get("max_turns") or 22)
    want = max(lo, min(int(inputs.get("turns") or 0) or 10, hi))
    fill_n = max(0, want - len(opening) - len(closing)) if middle else 0
    seq = [(leg, leg.get("seat")) for leg in opening]
    for k in range(fill_n):
        leg = middle[k % len(middle)]
        seat = leg.get("seat")
        if seat == "alternate":
            seat = "A" if (fill_n - 1 - k) % 2 == 0 else "C"
        seq.append((leg, seat))
    seq += [(leg, leg.get("seat")) for leg in closing]
    want = len(seq)
    conv["timing"]["turn_budget"] = want
    conv["call_structure"] = {"id": st.get("id"), "version": st.get("version"), "head": st.get("head", ""),
                              "tail": st.get("tail", ""), "material": st.get("material", ""),
                              "caller_share": st.get("caller_share", 0.38)}
    stream = DrawStream(conv["seed"], conv.get("draws", 0))
    _topic_decision(conv, conv["settings"], stream, inputs, want, replies=False,
                    open_turns=[i for i, (leg, _s) in enumerate(seq) if leg.get("place") == "middle"])
    seats = [p["actor_id"] for p in conv["participants"]]
    for leg, seat in seq:
        seat = str(seat or "A")
        if seat == "B" and "B" not in seats and not call.get("other"):
            seat = "A"
        if seat not in seats:
            conv["participants"].append(new_conversation({"seats": [seat]}, config, conv["settings"])["participants"][0])
            seats.append(seat)
        step = {"id": leg.get("id"), "label": leg.get("label") or leg.get("id"), "draws": leg.get("draws") or [{"family": "ES"}]}
        turn = _decide_turn(conv, config, conv["settings"], stream, step, seat, want, inputs)
        turn["protocol"] = _call_words(leg.get("act"), call)[:400]
        turn["leg"] = leg.get("id")
        turn["place"] = leg.get("place")
    conv["draws"] = stream.n
    return conv


def render_call_sheet(conv):
    """[s3-calls] THE RUNNING ORDER OF THIS CALL, from System 3's plan: the
    legs call_flow_report reads, each row with the delivery its dice chose,
    the call's own passage where the contract wants it, and the scenario."""
    call = (conv.get("inputs") or {}).get("call") or {}
    st = conv.get("call_structure") or {}
    turns = conv.get("turns") or []
    if not turns:
        return ""
    share = float(st.get("caller_share") or 0.38)
    rows = []
    material_at = max([i for i, t in enumerate(turns) if t.get("place") == "open"] or [0])
    for i, t in enumerate(turns):
        perf = t.get("performance") or {}
        add = ""
        if perf.get("emotion"):
            add = " [Say it in %s, %s" % (perf["emotion"], _intensity_word(float(perf.get("intensity") or 0)))
            acts = [x["text"] for x in t.get("directions") or [] if x["family"] in ("RS", "IRS")]
            if acts:
                add += "; while doing it, " + acts[0]
            flow = [x["text"] for x in t.get("directions") or [] if x["family"] == "FL"]
            if flow:
                add += "; and " + flow[-1]
            add += ".]"
        topic = t.get("bank_topic") or {}
        if topic.get("text"):
            add += (" [It puts them in mind of something off the operator's topics board, and they "
                    "bring it up in their own words: %s.]" % json.dumps(topic["text"][:300]))
        rows.append("%2d  %s  - %s%s" % (t["index"] + 1, t["speaker"], t.get("protocol") or "keeps it going.", add))
        if i == material_at and call.get("speakerbox") and st.get("material"):
            rows.append(_call_words(st["material"], call, {"passage": json.dumps(call["speakerbox"][:200])}))
    head = _call_words(st.get("head") or "", call, {"caller_turns": max(3, int(len(turns) * share))})
    text = "\n\n" + head + "\n" + "\n".join(rows) + "\n" + (st.get("tail") or "")
    if call.get("scenario_clause"):
        text += "\n" + str(call["scenario_clause"])
    return text


# --- the running order ----------------------------------------------------
'''),
]

RUNTIME = [
    ('import system3\nfrom system3_store import System3Store\n',
     'import system3\nimport system3_tables                     # [s3-calls] road structures\n'
     'from system3_store import System3Store\n'),
    ('            "topic_bank": topic_bank,\n'
     '        }\n',
     '            "topic_bank": topic_bank,\n'
     '            # [s3-calls] what a call needs to be built from System 3\'s structure\n'
     '            "call": self._call_of(ctx),\n'
     # tools/system3_roads_patch.py (runtime side): a memo is a round; his dials
     '            # [s3-roads] a message, not a conversation (never cut on the air)\n'
     '            "whole": bool(ctx.get("whole")),\n'
     '            # [s3-roads] the SFX Guy\'s dials, for his node on every host turn\n'
     '            "sfxguy": {"rate": _num(dj.get("sfxguy_rate")), "warp": _num(dj.get("sfxguy_warp")),\n'
     '                       "voice": bool(dj.get("drop_voice")), "every_units": _num(dj.get("sfxguy_every_units"))},\n'
     '        }\n'
     '\n'
     '    def _call_of(self, ctx):\n'
     '        """[s3-calls] Who is ringing (first name), who else is in the booth,\n'
     '        the call\'s own passage (the one call_speakerbox_report looks for),\n'
     '        whether it is a story call-back, and the scenario direction."""\n'
     '        name = " ".join(str(ctx.get("caller_name") or "").split())\n'
     '        if not name:\n'
     '            return {}\n'
     '        meta = ctx.get("call_meta") if isinstance(ctx.get("call_meta"), dict) else {}\n'
     '        dj = ctx.get("dj") or {}\n'
     '        clause = ""\n'
     '        if isinstance(meta.get("scenario"), dict):\n'
     '            try:\n'
     '                clause = str(self.host.call_scenario_clause(meta["scenario"]) or "")\n'
     '            except Exception:  # noqa: BLE001\n'
     '                clause = ""\n'
     '        return {"name": name, "first": name.split()[0], "other": str(dj.get("cohost_name") or ""),\n'
     '                "topic": str(meta.get("topic") or "")[:400],\n'
     '                "speakerbox": " ".join(str(meta.get("speakerbox_text") or ctx.get("seed_text") or "").split())[:600],\n'
     '                "story": bool(meta.get("story")), "scenario_clause": clause[:1500]}\n'),
    ('            if road == "caller":\n'
     '                rows = [(int(n), seat, work) for n, seat, work in\n',
     '            call = inputs.get("call") or {}\n'
     '            if road == "caller" and call.get("first") and not call.get("story"):\n'
     '                # [s3-calls] the call is built by System 3\'s own call structure\n'
     '                system3.plan_call(conv, config, inputs)\n'
     '                handle.sheet = system3.render_call_sheet(conv) if handle.active else ""\n'
     '            elif road == "caller":\n'
     '                rows = [(int(n), seat, work) for n, seat, work in\n'),
    ('    @app.put("/api/system3/config/section/{name}")\n',
     '    @app.put("/api/system3/structures/{road}")\n'
     '    async def put_road_structure(road: str, request: Request, authorization: str | None = Header(default=None)):\n'
     '        """[s3-calls] A road\'s structure - its legs, their acts, places, seats and\n'
     '        draws - customised, expanded or altered from the desk."""\n'
     '        host.require_auth(authorization)\n'
     '        raw = body_json(await request.body())\n'
     '        problems = system3_tables.validate_structure(road, raw)\n'
     '        if problems:\n'
     '            raise HTTPException(400, "; ".join(problems[:6]))\n'
     '        config = copy.deepcopy(rt.config)\n'
     '        mine = dict(system3.road_structure(config, road) or {})\n'
     '        mine.update({k: raw[k] for k in ("legs", "label", "head", "tail", "material",\n'
     '                                         "min_turns", "max_turns", "caller_share") if k in raw})\n'
     '        mine["version"] = int(mine.get("version") or 1) + 1\n'
     '        config.setdefault("structures", system3_tables.default_structures())[road] = mine\n'
     '        return {"hash": await save_config(config, "%s structure v%d" % (road, mine["version"])),\n'
     '                "structure": mine}\n'
     '\n'
     '    @app.put("/api/system3/config/section/{name}")\n'),
]

APP = [
    ('                    call_sheet=call_sheet, exchange=exchange)   # [topic-exchange]\n',
     '                    call_sheet=call_sheet, exchange=exchange,   # [topic-exchange]\n'
     '                    call_meta=(call_meta if isinstance(call_meta, dict) else {}))   # [s3-calls]\n'),
    ('        if not caller_name:\n'
     '            return []\n'
     '        script = _fallback_call_script(\n',
     '        if not caller_name:\n'
     '            return []\n'
     '        if _s3 is not None and getattr(_s3, "active", False):   # [s3-calls]\n'
     '            pipeline_log("call", "System 3\'s call for %s was not written - dropped, not replaced "\n'
     '                         "by the built-in template; the next call is rolled fresh" % caller_name)\n'
     '            return []\n'
     '        script = _fallback_call_script(\n'),
    ('    if caller_name and not spoken_text(script or ""):\n'
     '        pipeline_log("call", f"fragment-binned call write — built-in "\n',
     '    if caller_name and not spoken_text(script or "") and _s3 is not None and getattr(_s3, "active", False):\n'
     '        pipeline_log("call", "System 3\'s call for %s came back empty - dropped, not replaced by "\n'
     '                     "the built-in template; the next call is rolled fresh (#805)" % caller_name)   # [s3-calls]\n'
     '        return []\n'
     '    if caller_name and not spoken_text(script or ""):\n'
     '        pipeline_log("call", f"fragment-binned call write — built-in "\n'),
    ('                if caller_name:\n'
     '                    # A phone call is not salvageable as unrelated/thin\n',
     '                if caller_name and _s3 is not None and getattr(_s3, "active", False):   # [s3-calls]\n'
     '                    pipeline_log("call", "System 3\'s call for %s missed the call contract twice - "\n'
     '                                 "dropped, not replaced by the built-in template" % caller_name)\n'
     '                    return []\n'
     '                if caller_name:\n'
     '                    # A phone call is not salvageable as unrelated/thin\n'),
]

WIRING = [
    ('     "                    call_sheet=call_sheet, exchange=exchange)   # [topic-exchange]\\n"\n',
     '     "                    call_sheet=call_sheet, exchange=exchange,   # [topic-exchange]\\n"\n'
     '     # tools/system3_calls_patch.py hands System 3 the call\'s own facts.\n'
     '     "                    call_meta=(call_meta if isinstance(call_meta, dict) else {}))   # [s3-calls]\\n"\n'),
]


def patch(path, edits):
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    todo = 0
    for old, new in edits:
        if new in text:
            continue
        if text.count(old) != 1:
            print("MISSING (%d) in %s: %r" % (text.count(old), path, old[:90]))
            return None
        text = text.replace(old, new)
        todo += 1
    return text, todo


def main(argv):
    apply = "--apply" in argv
    out = {}
    for path, edits in (("system3_tables.py", TABLES), ("system3.py", ENGINE),
                        ("system3_runtime.py", RUNTIME), ("app.py", APP),
                        ("tools/system3_patch_app.py", WIRING)):
        got = patch(path, edits)
        if got is None:
            return 1
        out[path] = got
    todo = sum(n for _, n in out.values())
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for path, (text, n) in out.items():
        if n:
            Path(path).write_text(text, encoding="utf-8", newline="\n")
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
