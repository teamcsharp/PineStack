"""[s3-sb-end] The speakerbox prepend-or-append roulette (SBEND1).

"instead of both winning together, they now have a roulette that is part of
the system" (operator, 2026-09-28): when a line's prepend and append both win
their dice, SBEND1 picks the one that is read and the other is withdrawn."""
import unittest

import system3
import system3_tables


def inputs(**over):
    base = {"road": "banter", "seats": ["A", "B"], "turns": 10,
            "subject": {"topic": "raccoon van", "keywords": ["raccoon"]},
            "availability": {"speakbox": True},
            "speakerbox_rates": {"prepend": 1.0, "append": 1.0}}
    base.update(over)
    return base


def config(table=True, prepend=1.0, append=1.0, max_inline=8):
    cfg = system3.default_config()
    cfg["tables"] = [t for t in cfg["tables"] if table or t["id"] != "SBEND1"]
    for t in cfg["tables"]:
        if t["id"] == "SBEND1":
            for item in t["categories"][0]["items"]:
                item["weight"] = prepend if item["id"] == "prepend" else append
    cfg["speakerbox"] = dict(cfg.get("speakerbox") or system3.DEFAULT_SPEAKERBOX, max_inline=max_inline)
    return cfg


def plan(seed, cfg, **over):
    return system3.plan_scene(inputs(**over), cfg, system3.normalise_settings({"mode": "active", "test_seed": seed}),
                              conversation_id="sbend-" + seed)


def placed(turn, mark):
    return [x for x in turn.get("speakerbox") or [] if x.get("mark") == mark and x.get("mode") not in (None, "NONE")]


SEEDS = [str(n) for n in range(40)]


class SbEndTests(unittest.TestCase):
    def test_the_table_is_a_default(self):
        ids = [t["id"] for t in system3_tables.default_tables()]
        self.assertIn("SBEND1", ids)
        table = next(t for t in system3_tables.default_tables() if t["id"] == "SBEND1")
        self.assertEqual(table["family"], "SPEAKERBOX")
        self.assertEqual(sorted(i["id"] for i in table["categories"][0]["items"]), ["append", "prepend"])
        system3.validate_table(table)          # the desk can save it back

    def test_a_line_never_reads_both(self):
        chose = {"prepend": 0, "append": 0}
        for seed in SEEDS:
            conv = plan(seed, config())
            for t in conv["turns"]:
                self.assertFalse(placed(t, "prepend") and placed(t, "append"),
                                 "turn %d of seed %s reads a prepend AND an append" % (t["index"], seed))
                for rec in t.get("speakerbox") or []:
                    if rec.get("end"):
                        chose[rec["end"]["chose"]] += 1
        self.assertGreater(chose["prepend"], 0)
        self.assertGreater(chose["append"], 0)

    def test_the_loser_says_why_and_fetches_nothing(self):
        seen = 0
        for seed in SEEDS:
            conv = plan(seed, config())
            asked = {m["request_id"] for m in conv["material_requests"]}
            events = {e["event_id"]: e for e in conv["decision_events"]}
            for t in conv["turns"]:
                for rec in t.get("speakerbox") or []:
                    if not rec.get("lost_to"):
                        continue
                    seen += 1
                    self.assertEqual(rec["mode"], "NONE")
                    self.assertIn("roulette", rec["why"])
                    self.assertNotIn("request_id", rec)
                    ev = events[rec["event_id"]]
                    self.assertEqual(ev["selected"]["id"], "NONE")
                    self.assertTrue(ev["selected"]["label"].startswith("withdrawn"))
                    ends = [s for s in ev["stages"] if s["stage"] == "end"]
                    self.assertEqual(len(ends), 1)
                    if rec["mark"] == "prepend":
                        self.assertEqual(ev["selected"].get("was") in ("PREPEND", "REFERENCE", "CALLBACK_TO_PRIOR"), True)
                        self.assertTrue(ends[0].get("decided_in"), "a withdrawn prepend points at the append's event")
                for rec in t.get("speakerbox") or []:
                    if rec.get("mode") not in (None, "NONE") and rec.get("request_id"):
                        self.assertIn(rec["request_id"], asked)
            for m in conv["material_requests"]:
                owner = [r for t in conv["turns"] for r in t.get("speakerbox") or [] if r.get("request_id") == m["request_id"]]
                if m.get("kind") == "speakbox" and m.get("mode") in ("PREPEND", "APPEND", "REFERENCE"):
                    self.assertTrue(owner, "a material request with no passage left to own it")
        self.assertGreater(seen, 0)

    def test_the_roulette_stage_is_recorded_on_the_append(self):
        for seed in SEEDS:
            conv = plan(seed, config())
            for e in conv["decision_events"]:
                for st in e["stages"]:
                    if st["stage"] == "end" and st.get("candidates"):
                        self.assertEqual(e["family"], "SPEAKERBOX")
                        self.assertEqual(e["meta"]["mark"], "append")
                        self.assertEqual(sorted(c["id"] for c in st["candidates"]), ["append", "prepend"])
                        self.assertEqual(st["draw"]["label"], "SPEAKERBOX:end")
                        return
        self.fail("no roulette recorded in %d seeds" % len(SEEDS))

    def test_weights_rule_the_roulette(self):
        for seed in SEEDS[:20]:
            conv = plan(seed, config(prepend=0.0, append=1.0))
            for t in conv["turns"]:
                for rec in t.get("speakerbox") or []:
                    if rec.get("end"):
                        self.assertEqual(rec["end"]["chose"], "append")

    def test_without_the_table_both_are_read_as_before(self):
        both = 0
        for seed in SEEDS:
            conv = plan(seed, config(table=False))
            both += sum(1 for t in conv["turns"] if placed(t, "prepend") and placed(t, "append"))
            self.assertFalse(any(rec.get("end") for t in conv["turns"] for rec in t.get("speakerbox") or []))
        self.assertGreater(both, 0)

    def test_the_roulette_rolls_its_own_dice(self):
        """Its draw is on its own stream; a round where the two never both win
        plans exactly as it did without the table. (Where they do both win,
        the withdrawn passage's later draws are not made - a deliberate change
        of behaviour, recorded by the engine version.)"""
        def draws(conv):
            return [(e["family"], d["label"], d["n"], d["u"]) for e in conv["decision_events"]
                    for st in e["stages"] for d in [st.get("draw")] if d]
        untouched = 0
        for seed in SEEDS[:25]:
            a = plan(seed, config(), speakerbox_rates={"prepend": 0.49, "append": 0.68})
            b = plan(seed, config(table=False), speakerbox_rates={"prepend": 0.49, "append": 0.68})
            ends = [d for e in a["decision_events"] for st in e["stages"] for d in [st.get("draw")]
                    if d and d["label"] == "SPEAKERBOX:end"]
            for d in ends:
                self.assertTrue(d["seed"].endswith("|sbend"), d)
            if not ends:
                untouched += 1
                self.assertEqual(draws(a), draws(b))
        self.assertGreater(untouched, 0)

    def test_replay_holds(self):
        cfg = config()
        for seed in SEEDS[:10]:
            conv = plan(seed, cfg)
            got = system3.replay(conv, cfg)
            self.assertTrue(got["ok"], got.get("why") or got)

    def test_the_default_rates_still_plan(self):
        conv = system3.plan_scene(inputs(speakerbox_rates={"prepend": 0.49, "append": 0.68}), system3.default_config(),
                                  system3.normalise_settings({"mode": "active", "test_seed": "golden-1"}),
                                  conversation_id="sbend-default")
        self.assertTrue(conv["turns"])


if __name__ == "__main__":
    unittest.main()
