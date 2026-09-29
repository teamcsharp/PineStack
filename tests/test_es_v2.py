"""[es-v2] ES1's second edition (emotion engine steps 3 + 7).

- The defaults a fresh station seeds from (ES1, default_config, its hash) are
  untouched; ES1_V2 is data beside them.
- Step 3, the plan's own measure computed from the mapping: the sign of F0 mean,
  rate and energy per category against the master table of emotional prosody
  (prosody_science.md section 1). v1: 6 of 9 categories right on all three;
  v2: 9 of 9, none opposite. The four confusable pairs carry the documented
  OPPOSITE F0 signs (panic/anxiety, elation/contentment, sorrow/despair,
  hot anger/contempt); no fear row swings wider (range <= 1.0).
  (Acoustic confirmation of the same table is es_probe's, at the bench window.)
- Step 7: every item's direction is an actor's - a playable verb in CAPS, the
  line's shape, what the end leaves open - one sentence, under the 400 cap, and
  never one the writer could say aloud as its first clause.
- The one-shot fill moves only rows still at their v1 default, keeps every row
  the operator made their own, saves one version, runs once, and never at boot.
- Nothing drawn moves: the same seeds plan the same turns under v1 and v2.
"""
import copy
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import system3
import system3_runtime
import system3_tables

GOLDEN_HASH = "d4458771c5395e72"

# The master table's direction per station category on (F0 mean, rate, energy):
# +1 up, -1 down, 0 neutral (|pitch| <= 0.3 st reads as neutral). The row each
# category is held to: surprise [C90]; anger = hot anger; fear = panic fear (the
# anxious items split below); sadness = quiet sorrow; joy = elation; disgust
# [BS96][MA93]; interest [BS96: F0 -0.17z, articulation -0.66z, energy +0.19z];
# social = shame/pride [BS96: F0 -0.49/-0.46z, energy -1.14/-0.13z, shame slower];
# low_arousal = boredom.
MASTER = {"surprise": (1, 1, 1), "anger": (1, 1, 1), "fear": (1, 1, 1), "sadness": (-1, -1, -1),
          "joy": (1, 1, 1), "disgust": (-1, -1, -1), "interest": (0, 1, 1), "social": (-1, -1, -1),
          "low_arousal": (-1, -1, -1)}


def signs(block):
    p, t, e = block.get("pitch", 0.0), block.get("tempo", 1.0) - 1.0, block.get("energy", 0.0)
    return (0 if abs(p) <= 0.3 else (1 if p > 0 else -1),
            0 if abs(t) < 0.005 else (1 if t > 0 else -1),
            0 if abs(e) < 0.005 else (1 if e > 0 else -1))


def agreement(voices):
    right, opposite = 0, 0
    for cid, want in MASTER.items():
        got = signs(voices[cid])
        right += got == want
        opposite += any(g * w < 0 for g, w in zip(got, want))
    return right, opposite


def config_with(table):
    cfg = system3.default_config()
    cfg["tables"] = [copy.deepcopy(table) if t["id"] == "ES1" else t for t in cfg["tables"]]
    return cfg


def voice_of(table, cid, word):
    item = next(i for c in table["categories"] if c["id"] == cid for i in c["items"] if i["label"] == word)
    return system3.es_voice({"tables": [table]}, {"table": "ES1", "category": cid, "id": item["id"]})


def table(config, tid):
    return next(t for t in config["tables"] if t["id"] == tid)


def item(config, tid, iid):
    return next(i for c in table(config, tid)["categories"] for i in c["items"] if i["id"] == iid)


def cat(config, tid, cid):
    return next(c for c in table(config, tid)["categories"] if c["id"] == cid)


class DefaultsTests(unittest.TestCase):
    def test_the_seeded_defaults_are_untouched(self):
        self.assertEqual(system3.config_hash(system3.default_config()), GOLDEN_HASH)
        self.assertNotIn("ES1_V2", [t["id"] for t in system3_tables.default_tables()])
        self.assertEqual([c["id"] for c in system3_tables.ES1_V2["categories"]],
                         [c["id"] for c in system3_tables.ES1["categories"]])
        self.assertEqual([i["id"] for c in system3_tables.ES1_V2["categories"] for i in c["items"]],
                         [i["id"] for c in system3_tables.ES1["categories"] for i in c["items"]])
        system3.validate_table(copy.deepcopy(system3_tables.ES1_V2))


class VoiceTests(unittest.TestCase):
    def test_sign_agreement_with_the_master_table(self):
        v1 = {c["id"]: c["voice"] for c in system3_tables.ES1["categories"]}
        v2 = {c["id"]: c["voice"] for c in system3_tables.ES1_V2["categories"]}
        self.assertEqual(agreement(v1), (6, 1))   # v1: disgust brighter (opposite); social, interest off the band
        self.assertEqual(agreement(v2), (9, 0))
        for block in v2.values():
            self.assertEqual(system3.clean_es_voice(block), block, "inside the house bounds")

    def test_the_confusable_pairs_carry_opposite_f0(self):
        for es1, ok in ((system3_tables.ES1, False), (system3_tables.ES1_V2, True)):
            pairs = [(voice_of(es1, "fear", "panic"), voice_of(es1, "fear", "anxiety")),
                     (voice_of(es1, "joy", "excitement"), voice_of(es1, "joy", "satisfaction")),
                     (voice_of(es1, "sadness", "despair"), voice_of(es1, "sadness", "sadness")),
                     (voice_of(es1, "anger", "fury"), voice_of(es1, "anger", "contempt"))]
            opposite = [a["pitch"] > 0 > b["pitch"] for a, b in pairs]
            self.assertEqual(all(opposite), ok, opposite)
        v2 = system3_tables.ES1_V2
        self.assertLess(voice_of(v2, "fear", "anxiety")["energy"], 0, "anxious fear is quiet")
        self.assertGreater(voice_of(v2, "sadness", "despair")["energy"], 0, "despair is loud")
        self.assertLess(voice_of(v2, "joy", "satisfaction")["tempo"], voice_of(v2, "joy", "excitement")["tempo"])
        for c in v2["categories"]:
            if c["id"] == "fear":
                for i in c["items"]:
                    got = voice_of(v2, "fear", i["label"])
                    self.assertLessEqual(got["range"], 1.0, i["label"])
                    if got["pitch"] > 0:
                        self.assertGreater(got["pause"], 1.0, "fear's mixed model: fast, with breaks")


class DirectionTests(unittest.TestCase):
    def test_every_direction_is_an_actors(self):
        cfg = config_with(system3_tables.ES1_V2)
        for c in system3_tables.ES1_V2["categories"]:
            for i in c["items"]:
                spec = {"table": "ES1", "category": c["id"], "id": i["id"], "label": i["label"]}
                said = system3.es_direction(cfg, spec, "Skip")
                self.assertTrue(said.startswith("Skip processes this as %s: play it to " % i["label"]), said)
                self.assertRegex(said, r"to [A-Z]{4,}")
                self.assertLessEqual(len(said), 300)
                self.assertEqual(said.count("."), 1, "one sentence")
                self.assertNotRegex(said.lower(), r"\bugh\b|\bhah\b|\[|\*")
                self.assertFalse(system3._speaks_direction("Honestly Skip, the van again? " + i["label"], said))
                self.assertTrue(system3._speaks_direction("Well. " + said, said), "the guard still bites")

    def test_the_v1_default_still_reads_as_before(self):
        spec = {"table": "ES1", "category": "anger", "id": "anger.annoyance", "label": "annoyance"}
        self.assertEqual(system3.es_direction(system3.default_config(), spec, "Skip"),
                         "Write Skip's message with annoyance, reflecting the mood.")


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
        self.tmp = tempfile.mkdtemp(prefix="es-v2-")
        self.host = _Host(self.tmp)
        self.rt = system3_runtime.System3Runtime(self.host)

    def tearDown(self):
        try:
            self.rt.store.db.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def live_like(self):
        cfg = system3.default_config()
        cat(cfg, "ES1", "anger")["voice"]["pitch"] = 0.3                      # the operator's own anger
        item(cfg, "ES1", "fear.panic").pop("voice")                           # a voice removed
        item(cfg, "ES1", "joy.pleasure")["text"] = "Grin first."              # a direction of their own
        item(cfg, "ES1", "surprise.shock")["text"] = ""                       # a direction cleared
        es2 = copy.deepcopy(table(cfg, "ES1"))
        es2.update(id="ES2", label="Emotional Set 2")
        es2["categories"] = es2["categories"][:3] + [{"id": "giddy", "label": "GIDDY", "weight": 1.0,
                                                       "items": [{"id": "giddy.hysterical", "label": "hysterical"}]}]
        cfg["tables"].append(system3.validate_table(es2))
        cfg["defaults_added"] = ["ES_EMOJI", "ES_TEXT", "ES_VOICE", "FAV1"]   # the live station: v1 fills done
        return cfg

    def test_boot_leaves_the_tables_as_stored(self):
        self.rt.store.save_config(self.live_like(), "as the operator left it")
        self.rt.load()
        self.assertEqual(table(self.rt.config, "ES1")["categories"][1]["voice"]["pitch"], 0.3)
        self.assertEqual(cat(self.rt.config, "ES1", "sadness")["voice"], system3_tables.ES1["categories"][3]["voice"])
        self.assertNotIn("ES_V2", self.rt.config.get("defaults_added") or [])

    def test_the_second_edition_moves_only_the_defaults_once(self):
        rt = self.rt
        rt.store.save_config(self.live_like(), "as the operator left it")
        rt.load()
        n = len(rt.store.config_versions())
        before = copy.deepcopy(rt.config)
        dry = rt.upgrade_es_v2(apply=False)
        self.assertEqual(len(rt.store.config_versions()), n, "a dry run saves nothing")
        self.assertFalse(dry["done"])
        self.assertIn("ES1:anger voice", dry["kept"])
        self.assertIn("ES1:fear.panic voice", dry["kept"])
        self.assertIn("ES1:joy.pleasure direction", dry["kept"])
        self.assertIn("ES1:surprise.shock direction", dry["kept"])
        self.assertIn("ES1:fear voice", dry["moved"])
        self.assertIn("ES1:fear.anxiety voice", dry["moved"])
        self.assertIn("ES1:joy.happiness voice", dry["moved"], "an item v1 left to its category gains its own")
        self.assertIn("ES2:fear.anxiety voice", dry["moved"])
        self.assertNotIn("ES1:surprise voice", dry["moved"], "a block v2 did not change does not move")
        got = rt.upgrade_es_v2()
        self.assertTrue(got["done"])
        self.assertEqual(got["moved"], dry["moved"])
        cfg = rt.config
        self.assertEqual(cat(cfg, "ES1", "anger")["voice"]["pitch"], 0.3)
        self.assertNotIn("voice", item(cfg, "ES1", "fear.panic"))
        self.assertEqual(item(cfg, "ES1", "joy.pleasure")["text"], "Grin first.")
        self.assertEqual(item(cfg, "ES1", "surprise.shock")["text"], "")
        self.assertEqual(cat(cfg, "ES1", "fear")["voice"], system3_tables.ES_V2_VOICE["fear"])
        self.assertEqual(item(cfg, "ES2", "fear.anxiety")["voice"], system3_tables.ES_V2_ITEM_VOICE["anxiety"])
        self.assertNotIn("voice", table(cfg, "ES2")["categories"][3], "an operator's category gets none")
        self.assertEqual([t for t in cfg["tables"] if t["family"] != "ES"],
                         [t for t in before["tables"] if t["family"] != "ES"])
        self.assertIn("ES_V2", cfg["defaults_added"])
        self.assertIn("FAV1", cfg["defaults_added"])
        self.assertEqual(system3.config_hash(rt.store.config()), system3.config_hash(cfg))
        self.assertEqual(len([v for v in rt.store.config_versions() if "es-v2" in v["note"]]), 1)
        spec = {"table": "ES1", "category": "fear", "id": "fear.anxiety", "label": "anxiety"}
        self.assertIn("play it to WORRY aloud", system3.es_direction(cfg, spec, "Dill"))
        # once: a second call and a reload change nothing
        m = len(rt.store.config_versions())
        again = rt.upgrade_es_v2()
        self.assertTrue(again["done"])
        rt.load()
        self.assertEqual(len(rt.store.config_versions()), m)
        self.assertEqual(system3.config_hash(rt.config), system3.config_hash(cfg))
        self.assertTrue(any("second edition" in x for x in self.host.logs))

    def test_the_door_is_wired(self):
        src = (Path(system3_runtime.__file__)).read_text(encoding="utf-8")
        self.assertIn('@app.post("/api/system3/es-v2")', src)
        self.assertNotIn("upgrade_es_v2", src[src.index("    def load(self):"):src.index("    def add_missing_conversation_graphs")])


class NoDrawMovesTests(unittest.TestCase):
    def test_the_same_seeds_plan_the_same_turns(self):
        v1, v2 = system3.default_config(), config_with(system3_tables.ES1_V2)
        moved_voice = 0
        for seed in ["golden-1"] + ["v2-%d" % i for i in range(24)]:
            s = system3.normalise_settings({"mode": "active", "test_seed": seed})
            ins = {"road": "banter", "seats": ["A", "B"], "turns": 10, "names": {"A": "Dill", "B": "Skip"},
                   "subject": {"topic": "raccoon van", "keywords": ["raccoon"]}, "availability": {"speakbox": True},
                   "speakerbox_rates": {"prepend": 0.49, "append": 0.68}}
            a = system3.plan_scene(copy.deepcopy(ins), v1, s, conversation_id="v2-" + seed)
            b = system3.plan_scene(copy.deepcopy(ins), v2, s, conversation_id="v2-" + seed)
            path = lambda c: [[t["speaker"], t["step"]] + [(d.get("item"), d.get("intensity")) for d in t["decisions"]]
                              for t in c["turns"]]
            self.assertEqual(path(a), path(b), seed)
            self.assertEqual(a["draws"], b["draws"], seed)
            moved_voice += sum((ta.get("performance") or {}).get("voice") != (tb.get("performance") or {}).get("voice")
                               for ta, tb in zip(a["turns"], b["turns"]))
        self.assertGreater(moved_voice, 0, "the voices did move")


if __name__ == "__main__":
    unittest.main()
