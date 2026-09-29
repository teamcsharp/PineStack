"""[s3-direction] DIRECTION FOR THIS LINE: the rolls drive the writing, over the top.

tools/s3_direction_patch.py (system3.py), tools/s3_direction_voice_patch.py
(app.py + system3_runtime.py), tools/s3_direction_app_patch.py (app.py) and the
ES1 v3 table payload (payloads/ES1.after.json, applied through
PUT /api/system3/tables/ES1).

- the ES pick's acting (category, item over it) is stamped on the decision;
- the running-order row CLOSES on the block (its work still opens it), in roll order (character, family,
  feeling + intensity, how big, direction, first words, lexicon, wants, temper,
  shock); no second intonation, no understated "feeling X (plainly)" left in it;
- a fixed-words row (the seeded opener) is as it was;
- calls/legs/single lines carry the block in their bracket;
- saying a quoted first word is never a direction's echo; the block's label and a
  feeling said as a label ("Suspicion: ...") are cut from the words;
- a graph reply's protocol never names a turn number;
- the payload validates, keeps every id and weight (the draws do not move), gives
  every item acting and a direction under the cap, and a louder voice in bounds;
- the voice road: a chapter row renders with its own stamp; a reworded chunk
  still finds its turn's voice.

app.py is read, never imported; nothing renders; no data dir is touched."""
import copy
import hashlib
import inspect
import json
import types
import unittest
from pathlib import Path

import system3
import system3_runtime
import system3_tables

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
PAYLOAD = next((p for p in (HERE / "fixtures_s3_direction_ES1.json", ROOT / "payloads" / "ES1.after.json")
                if p.is_file()), None)


def es_v3():
    if PAYLOAD is None:
        raise unittest.SkipTest("no ES1 v3 payload next to the tests")
    return json.loads(PAYLOAD.read_text(encoding="utf-8"))


def config_v3():
    config = system3.default_config()
    t = system3.validate_table(es_v3())
    config["tables"] = [t if x["id"] == "ES1" else x for x in config["tables"]]
    return config


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 10, "names": {"A": "Dill", "B": "Skip"},
            "subject": {"topic": "raccoon van", "keywords": ["raccoon"]},
            "availability": {"speakbox": True},
            "speakerbox_rates": {"prepend": 0.49, "append": 0.68}}
    base.update(over)
    return base


def plan(seed, config=None, **over):
    return system3.plan_scene(inputs(**over), config or config_v3(), settings(seed),
                              conversation_id="s3dir-" + seed)


def es_of(turn):
    return next((d for d in turn["decisions"] if d.get("family") == "ES" and d.get("item")), None)


def turn(**over):
    t = {"turn_id": "c:t01", "index": 1, "speaker": "B", "name": "Skip", "step": "reply_a", "phase": "reply",
         "decisions": [{"family": "ES", "table": "ES1", "category": "anger", "item": "anger.fury", "label": "fury",
                        "intensity": 0.9, "direction": "Skip processes this as fury: EXPLODE - slammed sentences.",
                        "acting": {"act": "EXPLODE - slammed sentences", "blurts": ["Oh, HELL no!", "Enough!"],
                                   "says": ["ridiculous", "garbage"], "wants": "to make them back down"}},
                       {"family": "RS", "item": "disagree", "text": "disagrees, plainly"}],
         "directions": [{"family": "RS", "text": "disagrees, plainly"}],
         "performance": {"emotion": "fury", "family": "anger", "intensity": 0.9},
         "speakerbox": [], "shock": {"text": "furious"}, "graph_intonation": "playful"}
    t.update(over)
    return t


def conv_of(*turns, **over):
    c = {"identity": {"conversation_id": "c", "revision": 1}, "subject": {"exchange": {}},
         "turns": [{"turn_id": "c:t00", "index": 0, "speaker": "A", "name": "Dill", "step": "start",
                    "phase": "open", "decisions": [], "directions": [], "performance": {}, "speakerbox": []}]
         + list(turns), "tempers": {"B": {"text": "smug, insufferably pleased with themselves"}},
         "participants": [{"actor_id": "A", "name": "Dill"}, {"actor_id": "B", "name": "Skip"}]}
    c.update(over)
    return c


class ActingTests(unittest.TestCase):
    def test_item_acting_over_the_category(self):
        cfg = {"tables": [{"id": "ES9", "categories": [
            {"id": "anger", "acting": {"act": "BLOW UP", "blurts": ["No!"], "says": ["enough"], "wants": "win"},
             "items": [{"id": "anger.fury", "label": "fury", "acting": {"act": "EXPLODE", "blurts": ["HELL no!"]}},
                       {"id": "anger.plain", "label": "plain"}]}]}]}
        got = system3.es_acting(cfg, {"table": "ES9", "category": "anger", "id": "anger.fury"})
        self.assertEqual(got, {"act": "EXPLODE", "blurts": ["HELL no!"], "says": ["enough"], "wants": "win"})
        got = system3.es_acting(cfg, {"table": "ES9", "category": "anger", "id": "anger.plain"})
        self.assertEqual(got["act"], "BLOW UP")
        self.assertEqual(system3.es_acting({"tables": []}, {"table": "ES1", "category": "x", "id": "y"}), {})

    def test_scale_rises_with_intensity(self):
        self.assertIn("ALL THE WAY UP", system3.acting_scale(0.8))
        self.assertIn("BIG", system3.acting_scale(0.5))
        self.assertIn("OUT LOUD", system3.acting_scale(0.2))

    def test_the_plan_stamps_the_acting(self):
        conv = plan("a1")
        stamped = [es_of(t) for t in conv["turns"] if es_of(t)]
        self.assertTrue(stamped)
        for d in stamped:
            self.assertTrue(d["acting"].get("act"), d["item"])
            self.assertTrue(d["acting"].get("blurts"), d["item"])

    def test_the_draws_do_not_move(self):
        a = plan("same", config=system3.default_config())
        b = plan("same")
        self.assertEqual([(t["speaker"], (es_of(t) or {}).get("item")) for t in a["turns"]],
                         [(t["speaker"], (es_of(t) or {}).get("item")) for t in b["turns"]])


class BlockTests(unittest.TestCase):
    def test_roll_order(self):
        t = turn()
        block = system3.direction_block(t, conv_of(t))
        order = ["DIRECTION FOR THIS LINE (Skip):", "ANGER > feeling fury (hard) about Dill's line",
                 "PLAY IT ALL THE WAY UP", "Skip processes this as fury", "First words out", '"Oh, HELL no!"',
                 'Words they reach for, inside their own sentences and never read out as a list: "ridiculous"', "What Skip wants: to make them back down",
                 "Under it all tonight: smug", "Then it BOILS OVER: openly FURIOUS"]
        at = [block.find(x) for x in order]
        self.assertNotIn(-1, at, block)
        self.assertEqual(at, sorted(at), block)
        self.assertNotIn("EXPLODE - slammed sentences. EXPLODE", block)      # the act is not said twice

    def test_no_feeling_no_block(self):
        self.assertEqual(system3.direction_block(turn(decisions=[])), "")

    def test_the_row_closes_on_it_and_nothing_contradicts_it(self):
        t = turn()
        row = system3._row_work(t, conv_of(t))
        self.assertTrue(row.startswith("answers what Dill just said"), row)          # the #1386 grammar holds
        at = row.index("DIRECTION FOR THIS LINE (Skip):")
        self.assertLess(at, row.index("HERE Skip IS OPENLY FURIOUS"), row)           # before the adds
        self.assertTrue(row.startswith("answers what Dill just said: disagrees, plainly. DIRECTION FOR THIS LINE (Skip):"), row)
        self.assertNotIn("intonation", row)
        self.assertNotIn("(hard) about it:", row)
        self.assertEqual(row.count("processes this as fury"), 1, row)

    def test_a_row_without_a_feeling_keeps_its_intonation(self):
        t = turn(decisions=[], performance={})
        row = system3._row_work(t, conv_of(t))
        self.assertIn("Deliver this in a playful intonation", row)

    def test_a_seeded_opener_is_as_it_was(self):
        t0 = turn(index=0, turn_id="c:t00", step="start")
        c = conv_of(subject={"exchange": {}, "seeded": True})
        c["turns"] = [t0]
        row = system3._row_work(t0, c)
        self.assertNotIn(system3.DIRECTION_LABEL, row)
        self.assertIn("word for word", row)

    def test_calls_and_legs_carry_it_in_the_bracket(self):
        add = system3._leg_row_add(turn())
        self.assertTrue(add.startswith(" [Say it in fury, hard; while doing it, disagrees, plainly. "
                                       "DIRECTION FOR THIS LINE (Skip):"), add)
        self.assertEqual(add.count("processes this as fury"), 1, add)

    def test_a_stock_line_keeps_the_old_bracket(self):
        t = turn()
        t["decisions"].append({"family": "LINE", "item": "x"})
        add = system3._leg_row_add(t)
        self.assertIn("[Say it in fury, hard", add)
        self.assertNotIn(system3.DIRECTION_LABEL + " (", add)

    def test_the_sheet_header_asks_for_it_over_the_top(self):
        conv = plan("h1")
        sheet = system3.render_sheet(conv)
        self.assertIn("DIRECTION FOR THIS LINE", sheet.split("\n")[2])
        self.assertIn("OVER THE TOP", sheet)
        self.assertIn("never name them", sheet)
        rows = [r for r in sheet.split("\n") if r[:4].strip().isdigit()]
        with_es = [r for r, t in zip(rows, conv["turns"]) if es_of(t) and t["step"] not in ("interject", "carry_on")
                   and not t.get("split_of") and not (t["index"] == 0 and conv["subject"].get("seeded"))]
        self.assertTrue(with_es)
        for r in with_es:
            self.assertIn(". DIRECTION FOR THIS LINE (", r)
            self.assertNotIn("  - DIRECTION FOR THIS LINE (", r)


class GateTests(unittest.TestCase):
    def test_a_blurt_is_not_an_echo_but_the_direction_is(self):
        t = turn()
        kit = system3.direction_kit("%2d  %s  - %s" % (2, "B", system3._row_work(t, conv_of(t))))
        self.assertEqual(system3.direction_echo("Oh, HELL no! That is ridiculous garbage, Dill!", kit), "")
        self.assertNotEqual(system3.direction_echo("To make them back down, that is what I want.", kit), "")

    def test_labels_are_cut(self):
        for said, want in (("Suspicion: mandated thermal regulators?", "Mandated thermal regulators?"),
                           ("Disbelief: that is hilarious!", "That is hilarious!"),
                           ("In fury, hard: get out.", "Get out."),
                           ("Moral disgust - that is wrong.", "That is wrong."),
                           ("DIRECTION FOR THIS LINE (Skip): Oh, come on!", "Oh, come on!"),
                           ("Pride comes before a fall.", "Pride comes before a fall."),
                           ("Calm down: nobody is hurt.", "Calm down: nobody is hurt.")):
            self.assertEqual(system3.strip_scaffold(said), want, said)

    def test_no_turn_numbers_in_a_protocol(self):
        src = inspect.getsource(system3)
        self.assertNotIn("Return to your point in turn %d", src)
        self.assertIn("Return to the point you made earlier", src)

    def test_the_call_scenario_yields(self):
        src = inspect.getsource(system3.render_call_sheet)
        self.assertIn("that feeling outranks the", src)


class PayloadTests(unittest.TestCase):
    def test_it_validates_and_keeps_every_draw(self):
        after = system3.validate_table(es_v3())
        before = next(t for t in system3.default_config()["tables"] if t["id"] == "ES1")
        self.assertEqual(after["family"], "ES")
        key = lambda t: [(c["id"], c.get("weight", 1.0), [(i["id"], i["label"], i.get("weight", 1.0), i.get("arousal"))
                                                 for i in c["items"]]) for c in t["categories"]]
        self.assertEqual(key(after), key(before))

    def test_every_item_is_directed_and_acted(self):
        cfg = {"tables": [system3.validate_table(es_v3())]}
        for cat in cfg["tables"][0]["categories"]:
            self.assertTrue((cat.get("acting") or {}).get("act"), cat["id"])
            for item in cat["items"]:
                spec = {"table": "ES1", "category": cat["id"], "id": item["id"], "label": item["label"]}
                text = system3.es_direction(cfg, spec, "Skip")
                self.assertTrue(text.startswith("Skip processes this as %s: " % item["label"]), text)
                self.assertLess(len(text), 400)
                acting = system3.es_acting(cfg, spec)
                self.assertEqual(set(acting), {"act", "blurts", "says", "wants"}, item["id"])
                for b in acting["blurts"]:
                    self.assertNotRegex(b.lower(), r"^\W*(ugh|hmm|mm|uh|um)\b")   # no noises (#598)

    def test_the_voice_is_louder_and_in_bounds(self):
        after = es_v3()
        n = system3.ES_VOICE_NEUTRAL
        v2 = getattr(system3_tables, "ES_V2_VOICE", {})
        for cat in after["categories"]:
            v1 = cat["voice"]
            self.assertEqual(system3.clean_es_voice(v1), v1, cat["id"])
            for k, was in (v2.get(cat["id"]) or {}).items():
                self.assertGreaterEqual(abs(v1[k] - n[k]) + 1e-9, abs(was - n[k]), (cat["id"], k))


class VoiceRoadTests(unittest.TestCase):
    def test_a_chapter_row_renders_with_its_stamp(self):
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        i = text.index("async def _s3_chapter_voice(")
        body = text[i:text.index("\nasync def ", i + 10)]
        self.assertIn('stamp=row.get("stamp")', body)

    def test_perf_directive_yields_to_a_rolled_feeling(self):
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        i = text.index("def _perf_directive_raw(")
        self.assertIn('if not vec or vec.get("es"):', text[i:i + 600])

    def test_play_it_straight_is_not_laid_over_a_roll(self):
        text = (ROOT / "app.py").read_text(encoding="utf-8")
        i = text.index("as BIG as each line's DIRECTION FOR THIS LINE says")
        self.assertIn("if _s3_owns else", text[i:i + 300])
        # the [s3-blocks] angle mark (tools/system3_blocks_patch.py mark-angle) is untouched
        self.assertIn('f"{_pb(\'angle\', angle)}. Name the actual thing you are talking about. Play it "   # [s3-blocks]\n',
                      text)

    def test_a_reworded_chunk_finds_its_turn(self):
        script = "A: The raccoon took the van again tonight.\nB: Oh, HELL no! That raccoon is a menace to the whole street!"
        turns = [("A", "The raccoon took the van again tonight."),
                 ("B", "Oh, HELL no! That raccoon is a menace to the whole street!")]
        meta = {"system3": {"conversation_id": "c9"}, "script": script}
        fake = types.SimpleNamespace(
            turns_cache={"c9:" + hashlib.md5(script.encode("utf-8")).hexdigest()[:10]: turns},
            fail=lambda *a: None, _turn_of=lambda *a: ("c9", None))
        loose = system3_runtime.System3Runtime._turn_of_loose
        self.assertEqual(loose(fake, meta, "Oh HELL no, that raccoon is a menace to the street!", "cohost"), 1)
        self.assertIsNone(loose(fake, meta, "Something else entirely about the weather.", "cohost"))
        self.assertIsNone(loose(fake, meta, "Oh HELL no, that raccoon is a menace to the street!", "dj"))


if __name__ == "__main__":
    unittest.main()
