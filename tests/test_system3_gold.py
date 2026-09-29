"""[s3-gold] Gold lines as a reply System 3 rolls for (system3_gold + the engine).

Pure (no app): the GOLD roll lands only on a host's reply turn, on its own
stream (seed|gold) so every other draw of the round is unchanged; relevance
and the table's weights shape the pick; the writer is told the exact words and
the direction still rides; replay holds; GOLD1 is a valid table that never
touches the pinned default config."""
import copy
import unittest

import system3
import system3_gold
import system3_tables

BANK = [{"id": "g%02d" % i, "text": "Filler line number %d about the weather over the harbour today." % i,
         "who": "cohost", "fired": i % 3} for i in range(20)]
BANK.append({"id": "raccoon", "text": "That raccoon van is the finest vehicle ever parked behind this station.",
             "who": "dj", "fired": 0})


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 10,
            "roles": {"A": "dj", "B": "cohost", "C": "caller"},
            "subject": {"topic": "the raccoon van", "keywords": ["raccoon", "van"]},
            "availability": {"speakbox": True},
            "speakerbox_rates": {"prepend": 0.49, "append": 0.68}}
    base.update(over)
    return base


def settings():
    return system3.normalise_settings({"mode": "active", "test_seed": "gold-1"})


def config(gold=100.0, own=0.0, most=1):
    cfg = system3.default_config()
    t = system3_gold.default_tables()[0]
    t["most"] = most
    for c in t["categories"]:
        if c["id"] == system3_gold.REPLY_KEY:
            for it in c["items"]:
                it["weight"] = gold if it["id"] == "gold" else own
    cfg["tables"].append(t)
    return cfg


def plan(cfg, seed="gold-1", **over):
    return system3.plan_scene(inputs(**over), cfg, settings(), seed=seed, conversation_id="goldtest")


def draws(conv, skip=("GOLD",)):
    return [(e["family"], str((e.get("selected") or {}).get("id")), (e.get("rng") or {}).get("u"))
            for e in conv["decision_events"] if e["family"] not in skip]


class GoldRoll(unittest.TestCase):
    def test_table_is_valid_and_the_default_config_is_untouched(self):
        system3.validate_table(copy.deepcopy(system3_gold.GOLD1))
        self.assertNotIn("GOLD1", [t["id"] for t in system3_tables.default_tables()])
        self.assertIn("GOLD", system3.FAMILIES)

    def test_no_bank_no_draw(self):
        a = plan(config())
        self.assertFalse([e for e in a["decision_events"] if e["family"] == "GOLD"])

    def test_a_hit_lands_on_one_reply_turn_and_moves_no_other_dice(self):
        without = plan(config())
        withg = plan(config(), gold_bank=BANK)
        golds = [e for e in withg["decision_events"] if e["family"] == "GOLD"]
        self.assertEqual(len(golds), 1)                          # most = 1 a round
        ev = golds[0]
        self.assertTrue(ev["selected"]["label"].startswith("rolled gold "))
        turn = next(t for t in withg["turns"] if t.get("gold"))
        self.assertGreater(turn["index"], 0)
        self.assertLess(turn["index"], len(withg["turns"]) - 1)
        self.assertEqual(turn["gold"]["event_id"], ev["event_id"])
        self.assertEqual(draws(without), draws(withg))           # its own stream: nothing else moved

    def test_relevance_wins(self):
        conv = plan(config(), gold_bank=BANK)
        ev = next(e for e in conv["decision_events"] if e["family"] == "GOLD")
        item = next(s for s in ev["stages"] if s["stage"] == "item")
        w = {c["id"]: c["weight"] for c in item["candidates"]}
        self.assertGreater(w["raccoon"], 3 * max(v for k, v in w.items() if k != "raccoon"))

    def test_the_writer_is_told_the_exact_words_and_keeps_the_direction(self):
        conv = plan(config(), gold_bank=BANK)
        turn = next(t for t in conv["turns"] if t.get("gold"))
        sheet = system3.render_sheet(conv)
        self.assertIn("a line the station kept", sheet)
        self.assertIn(turn["gold"]["text"], sheet)

    def test_the_own_words_weight_keeps_gold_off(self):
        conv = plan(config(gold=0.0, own=100.0), gold_bank=BANK)
        self.assertFalse([t for t in conv["turns"] if t.get("gold")])

    def test_never_a_caller_never_the_opener(self):
        conv = plan(config(most=5), gold_bank=BANK, seats=["A", "C"])
        for t in conv["turns"]:
            if t.get("gold"):
                self.assertEqual(t["speaker"], "A")
                self.assertGreater(t["index"], 0)

    def test_the_runtime_adds_gold1_once_and_hands_the_bank_in(self):
        import types
        import system3_runtime
        saved = []
        fake = types.SimpleNamespace(
            config=system3.default_config(),
            store=types.SimpleNamespace(save_config=lambda cfg, note: saved.append((cfg, note))),
            fail=lambda *a: None)
        added = system3_runtime.System3Runtime.add_missing_default_tables(fake)
        self.assertIn("GOLD1", added)
        self.assertIn("GOLD1", [t["id"] for t in fake.config["tables"]])
        self.assertIn("GOLD1", fake.config["defaults_added"])
        fake.config["tables"] = [t for t in fake.config["tables"] if t["id"] != "GOLD1"]
        again = system3_runtime.System3Runtime.add_missing_default_tables(fake)
        self.assertNotIn("GOLD1", again or [])                  # deleted on the desk = deleted for good
        host = types.SimpleNamespace(system3_gold_bank=lambda road, ctx: [dict(BANK[0])])
        rt = types.SimpleNamespace(host=host, fail=lambda *a: None)
        self.assertEqual(system3_runtime.System3Runtime._gold_bank(rt, {}, "banter")[0]["id"], "g00")

    def test_replay_holds(self):
        cfg = config()
        conv = plan(cfg, gold_bank=BANK)
        self.assertTrue(system3.replay(conv, cfg)["ok"])


if __name__ == "__main__":
    unittest.main()
