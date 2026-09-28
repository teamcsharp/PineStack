"""[s3-es-dir] [s3-es-reel] The ES item reaches the writer and the voice.

2026-09-28, the operator: "the category is intended to be rouletted RNGd but
also the category weight option once won. By default have the writer told to
"write the message with this feeling reflecting the mood" for the actor" -
and: "when animating the RNG roulette indent the subcategory for the ES item.
The intention is for categories to be scrolled via RNG and then the
subcategories which is fed to the LLM for direction on how to write that
particular line ... and also is fed to the intonation engine".

- the roll: category (by the category's weight) THEN the item inside it;
- every ES item's default direction, and what the writer's row carries;
- the live config gains the direction once (ES_TEXT), only where absent;
- a line that says its direction aloud is marked;
- the item moves the voice's dims (a fury is not an annoyance);
- nothing drawn moves; the line card's two-stage reel is wired in.
"""
import copy
import shutil
import statistics
import tempfile
import unittest
from pathlib import Path

import system3
import system3_runtime
import system3_tables

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = "Write {name}'s message with {feeling}, reflecting the mood."


def table(config, tid):
    return next(t for t in config["tables"] if t["id"] == tid)


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def inputs(road="banter", **over):
    base = {"road": road, "seats": ["A", "B"], "turns": 10, "names": {"A": "Dill", "B": "Skip"},
            "subject": {"topic": "raccoon van", "keywords": ["raccoon"]},
            "availability": {"speakbox": True},
            "speakerbox_rates": {"prepend": 0.49, "append": 0.68}}
    base.update(over)
    return base


def banter(seed, config=None, **over):
    config = config or system3.default_config()
    return system3.plan_scene(inputs(**over), config, settings(seed), conversation_id="dir-" + seed)


def es_decisions(conv):
    return [(t, d) for t in conv["turns"] for d in t["decisions"] if d["family"] == "ES" and d.get("item")]


def events(conv):
    return {e["event_id"]: e for e in conv["decision_events"]}


def strip_text(config):
    out = copy.deepcopy(config)
    for t in out["tables"]:
        if t.get("family") == "ES":
            for c in t["categories"]:
                for it in c["items"]:
                    it.pop("text", None)
    return out


def draws(conv):
    out = []
    for e in conv["decision_events"]:
        sel = e.get("selected")
        out.append((e["family"], e.get("turn_index"), sel.get("id") if isinstance(sel, dict) else sel,
                    (e.get("rng") or {}).get("u"),
                    [(st.get("stage"), (st.get("draw") or {}).get("u"), st.get("selected"))
                     for st in e.get("stages") or [] if isinstance(st, dict)]))
    return out


class DrawOrderTests(unittest.TestCase):
    def test_the_roll_is_the_category_then_the_item_inside_it(self):
        conv = banter("order")
        evs = events(conv)
        seen = 0
        for t, d in es_decisions(conv):
            ev = evs[d["event_id"]]
            names = [st["stage"] for st in ev["stages"]]
            self.assertEqual(names[:3], ["table", "category", "item"], names)
            cat, item = ev["stages"][1], ev["stages"][2]
            self.assertTrue(cat["draw"] and item["draw"], "two recorded numbers: the category's, then the item's")
            self.assertEqual(cat["selected"], d["category"])
            self.assertEqual(item["selected"], d["item"])
            self.assertTrue(d["item"].startswith(d["category"] + "."), "the item is inside the won category")
            self.assertEqual([c["id"] for c in item["candidates"]],
                             [c["id"] for c in item["candidates"] if c["id"].startswith(d["category"] + ".")])
            # the category weighs its slider times the mean of its eligible items
            won = next(c for c in cat["candidates"] if c["id"] == cat["selected"])
            mean = statistics.mean(c["weight"] for c in item["candidates"])
            self.assertAlmostEqual(won["weight"], won["base"] * mean, places=3)
            seen += 1
        self.assertGreater(seen, 5)

    def test_the_category_slider_weighs_the_category_stage(self):
        def share(weight):
            config = system3.default_config()
            for c in table(config, "ES1")["categories"]:
                if c["id"] == "fear":
                    c["weight"] = weight
            got = [d["category"] for s in range(12) for _t, d in es_decisions(banter("slide%d" % s, config))]
            return got.count("fear") / float(len(got))
        low, high = share(1.0), share(12.0)
        self.assertGreater(high, low + 0.25, (low, high))


class DirectionTests(unittest.TestCase):
    def test_every_es1_item_carries_the_default(self):
        self.assertEqual(system3_tables.ES_DIRECTION, DEFAULT)
        for c in table(system3.default_config(), "ES1")["categories"]:
            for it in c["items"]:
                self.assertEqual(it["text"], DEFAULT, it["id"])

    def test_the_direction_fills_in_the_feeling_and_the_speaker(self):
        config = system3.default_config()
        spec = {"table": "ES1", "category": "surprise", "id": "surprise.shock", "label": "shock"}
        self.assertEqual(system3.es_direction(config, spec, "Skip"), "Write Skip's message with shock, reflecting the mood.")
        self.assertEqual(system3.es_direction(config, spec, ""), "Write the speaker's message with shock, reflecting the mood.")
        shock = next(i for c in table(config, "ES1")["categories"] for i in c["items"] if i["id"] == "surprise.shock")
        shock["text"] = "   "                                               # blank: the default
        self.assertEqual(system3.es_direction(config, spec, "Skip"), "Write Skip's message with shock, reflecting the mood.")
        shock["text"] = "{name} can hardly get the words out - {feeling}, raw."
        self.assertEqual(system3.es_direction(config, spec, "Dill"), "Dill can hardly get the words out - shock, raw.")
        shock["text"] = "Stammer through it."                                # the operator's own, as written
        self.assertEqual(system3.es_direction(config, spec, "Dill"), "Stammer through it.")

    def test_every_planned_feeling_carries_its_direction(self):
        conv = banter("carry")
        evs = events(conv)
        for t, d in es_decisions(conv):
            want = "Write %s's message with %s, reflecting the mood." % (t["name"], d["label"])
            self.assertEqual(d["direction"], want)
            self.assertEqual(d["text"], want)
            self.assertEqual(evs[d["event_id"]]["selected"]["text"], want, "the Rolodex's command to the writer")

    def test_the_banter_row_tells_the_writer(self):
        conv = banter("rows")
        sheet = system3.render_sheet(conv)
        for t, d in es_decisions(conv):
            row = next(ln for ln in sheet.splitlines() if ln.startswith("%2d  %s  - " % (t["index"] + 1, t["speaker"])))
            self.assertIn(d["direction"].rstrip("."), row, row)
            self.assertIn(d["label"], row, "the feeling's own word still names the row")

    def test_a_line_whose_words_are_fixed_is_not_told_to_write(self):
        conv = banter("fixed", subject={"topic": "raccoon van", "keywords": ["raccoon"],
                                        "exchange": {"opener": "Who parked the van?", "reply": "The raccoons did."}})
        sheet = system3.render_sheet(conv)
        rows = [ln for ln in sheet.splitlines() if ln[:4].strip().isdigit()]
        self.assertIn("Who parked the van?", rows[0])
        self.assertNotIn("reflecting the mood", rows[0])
        self.assertIn("The raccoons did.", rows[1])
        self.assertNotIn("reflecting the mood", rows[1])
        self.assertIn("reflecting the mood", rows[2])

    def test_the_legs_and_protocol_rows_carry_it_in_their_bracket(self):
        config = system3.default_config()
        conv = system3.new_conversation(inputs("news", turns=6), config, settings("legs"), conversation_id="legs1")
        system3.plan_legs(conv, config, road="news")
        sheet = system3.render_legs_sheet(conv)
        rows = [ln for ln in sheet.splitlines() if ln[:4].strip().isdigit()]
        self.assertEqual(sum(ln.count("[Say it in") for ln in rows), len(rows))
        for t, d in es_decisions(conv):
            row = rows[t["index"]]
            said = row[row.index("[Say it in %s, " % d["label"]):]
            self.assertIn(". %s.]" % d["direction"].rstrip("."), said.split("]")[0] + "]", row)
        proto = ("\n 1  A  - ANSWER THE RINGING LINE.\n 2  C  - BETTY INTRODUCES THEMSELF.\n"
                 " 3  A  - keeps it going; every turn answers.\n")
        rowspec = [(1, "A", "ANSWER THE RINGING LINE."), (2, "C", "BETTY INTRODUCES THEMSELF."),
                   (3, "A", "keeps it going; every turn answers.")]
        call = system3.new_conversation(inputs("caller", seats=["A", "B", "C"], turns=3, availability={}),
                                        config, settings("proto"))
        system3.plan_protocol(call, config, rowspec)
        out = system3.annotate_protocol(call, proto)
        self.assertEqual(out.count("[Say it in"), 3)
        self.assertEqual(out.count("reflecting the mood.]"), 3)

    def test_a_drawn_stock_line_is_not_told_to_write(self):
        config = system3.default_config()
        conv = system3.new_conversation(inputs("interject", seats=["A"], turns=1,
                                               candidates=[{"id": "1", "text": "Oh, come on."}]),
                                        config, settings("stock"), conversation_id="stock1")
        system3.plan_line(conv, config)
        self.assertNotIn("reflecting the mood", system3.render_legs_sheet(conv))

    def test_a_turn_planned_before_renders_as_it_did(self):
        conv = banter("older")
        for _t, d in es_decisions(conv):
            d.pop("direction")
        self.assertNotIn("reflecting the mood", system3.render_sheet(conv))

    def test_a_line_that_says_its_direction_aloud_is_marked(self):
        conv = banter("echo", turns=4)
        final = [(t["speaker"], "no, that is wrong? %s" % t["turn_id"]) for t in conv["turns"]]
        t1, d1 = es_decisions(conv)[1]
        final[t1["index"]] = (t1["speaker"], "Okay. " + d1["direction"])
        val = system3.validate(conv, final)
        checks = {r["turn_id"]: [c["what"] for c in r["checks"] if c["result"] == "violated"] for r in val["turns"]}
        self.assertIn("echo:feeling direction", checks[t1["turn_id"]])
        self.assertFalse(any("echo:feeling direction" in v for k, v in checks.items() if k != t1["turn_id"]))


class VoiceTests(unittest.TestCase):
    def spec(self, item_id):
        es = table(system3.default_config(), "ES1")
        cat = next(c for c in es["categories"] if any(i["id"] == item_id for i in c["items"]))
        return system3._spec(es, cat, next(i for i in cat["items"] if i["id"] == item_id)), cat

    def test_a_fury_is_not_an_annoyance(self):
        fury, anger = self.spec("anger.fury")
        annoy, _ = self.spec("anger.annoyance")
        base = anger["arousal"]
        f = system3.performance_intent(fury, 0.8, {"tension": 0.5}, base_arousal=base)["dims"]
        a = system3.performance_intent(annoy, 0.8, {"tension": 0.5}, base_arousal=base)["dims"]
        self.assertGreater(f["excitement"], a["excitement"])
        self.assertGreater(a["fatigue"], f["fatigue"])
        # the old reading, without the category's arousal: the same dims for both
        self.assertEqual(system3.performance_intent(fury, 0.8, {"tension": 0.5})["dims"],
                         system3.performance_intent(annoy, 0.8, {"tension": 0.5})["dims"])

    def test_an_item_at_its_categorys_arousal_keeps_the_categorys_dims(self):
        rage, anger = self.spec("anger.anger")
        with_base = system3.performance_intent(rage, 0.6, {}, base_arousal=anger["arousal"])
        self.assertEqual(with_base["dims"], system3.performance_intent(rage, 0.6, {})["dims"])
        self.assertEqual(with_base["item_shift"], 0.0)

    def test_the_planned_turn_carries_the_items_voice(self):
        for seed in map(str, range(40)):
            conv = banter("voice" + seed)
            for t, d in es_decisions(conv):
                if d["item"] != "anger.fury":
                    continue
                perf = t["performance"]
                s = 0.35 + 0.65 * perf["intensity"]
                self.assertAlmostEqual(perf["item_shift"], 0.98 - 0.85, places=3)
                self.assertAlmostEqual(perf["dims"]["excitement"], round(min(1.0, 0.3 * s + 0.13 * s), 3), places=2)
                return
        self.skipTest("no fury in forty rounds")


class NoDrawMovesTests(unittest.TestCase):
    def test_the_directions_move_no_draw(self):
        told = system3.default_config()
        bare = strip_text(told)
        for seed in ["golden-1"] + ["d%d" % i for i in range(8)]:
            a, b = banter(seed, told), banter(seed, bare)
            self.assertEqual(draws(a), draws(b), seed)
            self.assertEqual(a["draws"], b["draws"])
            self.assertEqual([d["direction"] for _t, d in es_decisions(a)],
                             [d["direction"] for _t, d in es_decisions(b)], "a blank text reads as the default")
        conv = banter("replay", told)
        self.assertTrue(system3.replay(conv, told)["ok"])


class _Host:
    def __init__(self, root):
        self.root = Path(root)
        self.logs = []

    def data_path(self, name):
        return str(self.root / name)

    def pipeline_log(self, kind, text, extra=""):
        self.logs.append(str(text))


class FillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="s3-es-dir-")
        self.host = _Host(self.tmp)
        self.rt = system3_runtime.System3Runtime(self.host)

    def tearDown(self):
        try:
            self.rt.store.db.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_live_items_gain_the_direction_once(self):
        rt = self.rt
        cfg = strip_text(system3.default_config())
        es1 = table(cfg, "ES1")
        es1["categories"][0]["items"][1]["text"] = ""                       # surprise.shock: cleared
        es1["categories"][0]["items"][2]["text"] = "Gasp first."             # the operator's own
        es2 = {"id": "ES2", "family": "ES", "label": "Emotional Set 2", "weight": 1.0, "categories": [
            {"id": "giddy", "label": "GIDDY", "weight": 1.0, "items": [{"id": "giddy.hysterical", "label": "hysterical"}]}]}
        cfg["tables"].append(system3.validate_table(es2))
        cfg["defaults_added"] = ["FAV1"]
        rt.store.save_config(cfg, "as saved before the directions")
        rt.load()
        es1 = table(rt.config, "ES1")
        self.assertEqual(es1["categories"][0]["items"][0]["text"], DEFAULT)
        self.assertEqual(es1["categories"][0]["items"][1]["text"], "", "a cleared direction stays cleared")
        self.assertEqual(es1["categories"][0]["items"][2]["text"], "Gasp first.")
        self.assertEqual(table(rt.config, "ES2")["categories"][0]["items"][0]["text"], DEFAULT, "an item of the operator's own")
        self.assertEqual([t for t in rt.config["tables"] if t["family"] != "ES"],
                         [t for t in cfg["tables"] if t["family"] != "ES"])
        self.assertIn("ES_TEXT", rt.config["defaults_added"])
        noted = [v for v in rt.store.config_versions() if "ES writer directions" in v["note"]]
        self.assertEqual(len(noted), 1)
        self.assertEqual(system3.config_hash(rt.store.config()), system3.config_hash(rt.config))
        self.assertEqual(rt.add_missing_es_text(), [])
        edited = copy.deepcopy(rt.config)
        table(edited, "ES1")["categories"][1]["items"][0].pop("text")           # a key gone altogether
        rt.store.save_config(edited, "a direction removed")
        rt.load()
        self.assertNotIn("text", table(rt.config, "ES1")["categories"][1]["items"][0], "the fill ran once")
        # ...and it still reads as the default when the turn is planned
        spec = {"table": "ES1", "category": "anger", "id": table(rt.config, "ES1")["categories"][1]["items"][0]["id"],
                "label": "annoyance"}
        self.assertEqual(system3.es_direction(rt.config, spec, "Skip"), "Write Skip's message with annoyance, reflecting the mood.")

    def test_a_config_that_already_carries_them_saves_nothing(self):
        rt = self.rt
        rt.load()
        n = len(rt.store.config_versions())
        self.assertEqual(rt.add_missing_es_text(), [])
        self.assertEqual(len(rt.store.config_versions()), n)


class WiringTests(unittest.TestCase):
    def test_the_line_card_rolls_the_es_draw_in_two_stages(self):
        src = (ROOT / "frontend" / "system3.js").read_text(encoding="utf-8")
        self.assertIn("function esTwoStageReel(ev, conv)", src)
        self.assertIn("function esStagesText(ev)", src)
        self.assertEqual(src.count("esTwoStageReel(ev, conv);"), 3, "the line card's Rolodex, its tile, the decision card")
        self.assertIn('"%s"' % DEFAULT, src, "the Tables tab's placeholder is the default direction")


if __name__ == "__main__":
    unittest.main()
