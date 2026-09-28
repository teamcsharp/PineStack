"""[s3-es-emoji] System 3's ES badge: an emoji per ES category and per item.

2026-09-28, the operator: "for messages that get an ES result from the
roulette, have them display relevant emojis for each category in the bottom
right of each message." Real colour emoji - the one exception to the
station's Carbon-icons-only rule, for this badge only.

- the defaults: ES1 carries one on every category, and one on an item only
  where it is more specific than its category's;
- the engine stamps [category, item] on the turn's ES decision at plan time
  and moves no draw: the same seed, planned with and without the emoji in
  the config, rolls the same numbers and lands on the same rows;
- validate_table keeps `emoji`, trimmed, and drops what is not a badge;
- the live config, saved before the badges, gains them once - only where
  the key is absent - and a badge the operator clears stays cleared.
"""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import system3
import system3_runtime
import system3_tables

# The category map is the contract the Messenger's fallback copies (a turn
# planned before the badges has no `emoji` on its ES decision): a change here
# is a change there.
CATEGORY_EMOJI = {"surprise": "\U0001F62E", "anger": "\U0001F620", "fear": "\U0001F628",
                  "sadness": "\U0001F622", "joy": "\U0001F604", "disgust": "\U0001F922",
                  "interest": "\U0001F914", "social": "\U0001F633", "low_arousal": "\U0001F610"}


def table(config, tid):
    return next(t for t in config["tables"] if t["id"] == tid)


def strip_emoji(config):
    """The config as saved before the badges existed."""
    out = copy.deepcopy(config)
    for t in out["tables"]:
        if t.get("family") != "ES":
            continue
        for c in t["categories"]:
            c.pop("emoji", None)
            for it in c["items"]:
                it.pop("emoji", None)
    return out


def settings(seed):
    return system3.normalise_settings({"mode": "active", "test_seed": seed})


def inputs(road="banter", **over):
    base = {"road": road, "seats": ["A", "B"], "turns": 10,
            "subject": {"topic": "raccoon van", "keywords": ["raccoon"]},
            "availability": {"speakbox": True},
            "speakerbox_rates": {"prepend": 0.49, "append": 0.68}}
    base.update(over)
    return base


def banter(seed, config):
    return system3.plan_scene(inputs(), config, settings(seed), conversation_id="es-" + seed)


def legs(road, seed, config):
    conv = system3.new_conversation(inputs(road, turns=6), config, settings(seed), conversation_id=road + "-" + seed)
    system3.plan_legs(conv, config, road=road)
    return conv


def line(seed, config):
    conv = system3.new_conversation(inputs("station_id", seats=["A"], turns=1), config, settings(seed),
                                    conversation_id="sid-" + seed)
    system3.plan_line(conv, config)
    return conv


def draws(conv):
    """Every event's draws: its family and turn, what it landed on, and every number it rolled."""
    out = []
    for e in conv["decision_events"]:
        sel = e.get("selected")
        out.append((e["family"], e.get("turn_index"), sel.get("id") if isinstance(sel, dict) else sel,
                    (e.get("rng") or {}).get("u"),
                    [(st.get("stage"), (st.get("draw") or {}).get("u"), st.get("selected"))
                     for st in e.get("stages") or [] if isinstance(st, dict)]))
    return out


def turns_without_badges(conv):
    out = []
    for t in conv["turns"]:
        decs = [{k: v for k, v in d.items() if k != "emoji"} for d in t["decisions"]]
        out.append((t["speaker"], t["step"], decs, t["directions"], t.get("performance")))
    return out


def es_decisions(conv):
    return [d for t in conv["turns"] for d in t["decisions"] if d["family"] == "ES" and d.get("item")]


class DefaultsTests(unittest.TestCase):
    def test_every_es1_category_has_one_and_an_item_only_a_more_specific_one(self):
        es1 = table(system3.default_config(), "ES1")
        self.assertEqual({c["id"]: c.get("emoji") for c in es1["categories"]}, CATEGORY_EMOJI)
        self.assertEqual(system3_tables._ES_EMOJI, CATEGORY_EMOJI)
        own = {}
        for c in es1["categories"]:
            self.assertEqual(system3.clean_emoji(c["emoji"]), c["emoji"], "a category's is a valid badge")
            for it in c["items"]:
                own[it["id"]] = it.get("emoji")
                if "emoji" in it:
                    self.assertNotEqual(it["emoji"], c["emoji"], "an item carries one only where it is more specific")
                    self.assertEqual(system3.clean_emoji(it["emoji"]), it["emoji"], it["id"])
        for iid in ("surprise.bewilderment", "anger.fury", "fear.panic", "sadness.grief", "joy.delight",
                    "low_arousal.boredom", "disgust.moral_disgust", "anger.disgust"):
            self.assertTrue(own[iid], iid)
        for iid in ("anger.anger", "disgust.disgust", "joy.happiness", "social.embarrassment"):
            self.assertIsNone(own[iid], "%s wears its category's" % iid)
        # the same word is the same badge wherever it sits
        self.assertEqual(own["surprise.curiosity"], own["interest.curiosity"])
        self.assertEqual(own["anger.disgust"], CATEGORY_EMOJI["disgust"])

    def test_the_defaults_survive_validation_badge_for_badge(self):
        es1 = table(system3.default_config(), "ES1")

        def badges(t):
            return [(c["id"], c.get("emoji"), [i.get("emoji") for i in c["items"]]) for c in t["categories"]]
        self.assertEqual(badges(system3.validate_table(es1)), badges(es1))
        for t in system3_tables.default_tables():
            if t["family"] == "ES":                       # (other families may have validators of their own)
                system3.validate_table(t)


class ValidateTests(unittest.TestCase):
    def test_validate_table_keeps_the_badge_trimmed_and_drops_what_is_not_one(self):
        got = system3.validate_table({"id": "ES9", "family": "ES", "categories": [
            {"id": "a", "emoji": "  \U0001F620 ", "items": [
                {"id": "a.1", "emoji": "\U0001F621\n"},
                {"id": "a.2", "emoji": "\U0001F635\U0000200D\U0001F4AB"},     # a ZWJ sequence is one badge
                {"id": "a.3", "emoji": "not an emoji at all"},                 # too long: dropped
                {"id": "a.4", "emoji": 7},                                     # not a string: dropped
                {"id": "a.5", "emoji": ""},                                    # cleared stays cleared
                {"id": "a.6"}]}]})                                             # none stays absent
        cat = got["categories"][0]
        items = {it["id"]: it for it in cat["items"]}
        self.assertEqual(cat["emoji"], "\U0001F620")
        self.assertEqual(items["a.1"]["emoji"], "\U0001F621")
        self.assertEqual(items["a.2"]["emoji"], "\U0001F635\U0000200D\U0001F4AB")
        self.assertEqual(items["a.3"]["emoji"], "")
        self.assertEqual(items["a.4"]["emoji"], "")
        self.assertEqual(items["a.5"]["emoji"], "")
        self.assertNotIn("emoji", items["a.6"])

    def test_the_limit_is_eight_code_points(self):
        self.assertEqual(system3.clean_emoji("\U0001F600" * 8), "\U0001F600" * 8)    # 8 points, 16 UTF-16 units
        self.assertEqual(system3.clean_emoji("\U0001F600" * 9), "")
        self.assertEqual(system3.clean_emoji("abcdefgh"), "abcdefgh")
        self.assertEqual(system3.clean_emoji("abcdefghi"), "")
        self.assertEqual(system3.clean_emoji(None), "")


class EngineTests(unittest.TestCase):
    def test_every_es_decision_wears_its_badge(self):
        config = system3.default_config()
        cats = {c["id"]: c for c in table(config, "ES1")["categories"]}
        seen = 0
        for seed in ("badge-1", "badge-2", "badge-3"):
            conv = banter(seed, config)
            for d in es_decisions(conv):
                cat = cats[d["category"]]
                item = next(i for i in cat["items"] if i["id"] == d["item"])
                want = [cat["emoji"]] + ([item["emoji"]] if item.get("emoji") else [])
                self.assertEqual(d["emoji"], want, d["item"])
                seen += 1
            # only the ES decision carries it: not the events, not the directions, not the voice
            for e in conv["decision_events"]:
                self.assertNotIn("emoji", e.get("selected") or {})
            for t in conv["turns"]:
                self.assertFalse(any("emoji" in x for x in t["directions"]))
                self.assertNotIn("emoji", t.get("performance") or {})
                self.assertFalse(any("emoji" in d for d in t["decisions"] if d["family"] != "ES"))
        self.assertGreater(seen, 20)

    def test_a_pinned_row_wears_its_badge_too(self):
        config = system3.default_config()
        config["structure"]["steps"][0]["draws"] = [{"family": "CTS"}, {"family": "ES", "fixed": "anger.fury"}]
        conv = banter("pinned", config)
        es = next(d for d in conv["turns"][0]["decisions"] if d["family"] == "ES")
        self.assertEqual(es["item"], "anger.fury")
        self.assertEqual(es["emoji"], [CATEGORY_EMOJI["anger"], "\U0001F621"])

    def test_the_pair_follows_the_table(self):
        default = system3.default_config()
        self.assertEqual(system3.es_emoji(default, {"table": "ES1", "category": "anger"}), ["\U0001F620"])
        self.assertEqual(system3.es_emoji(default, {"table": "ES1", "category": "anger", "emoji": "\U0001F621"}),
                         ["\U0001F620", "\U0001F621"])
        self.assertEqual(system3.es_emoji(default, {"table": "ES1", "category": "anger", "emoji": "\U0001F620"}),
                         ["\U0001F620"], "the same as its category's: shown once")
        cleared = copy.deepcopy(default)
        for c in table(cleared, "ES1")["categories"]:
            c["emoji"] = ""
        self.assertEqual(system3.es_emoji(cleared, {"table": "ES1", "category": "anger", "emoji": "\U0001F621"}),
                         ["\U0001F621"], "a cleared category: only the item's own")
        self.assertEqual(system3.es_emoji(cleared, {"table": "ES1", "category": "anger"}), [])
        self.assertEqual(system3.es_emoji(strip_emoji(default), {"table": "ES1", "category": "joy"}), [])

    def test_the_badge_moves_no_draw(self):
        badged = system3.default_config()
        bare = strip_emoji(badged)
        self.assertNotEqual(system3.config_hash(badged), system3.config_hash(bare))
        pairs = [(banter(seed, badged), banter(seed, bare)) for seed in ["golden-1"] + ["s%d" % i for i in range(12)]]
        pairs += [(legs(road, "L", badged), legs(road, "L", bare)) for road in ("news", "recap", "ad", "memo")]
        pairs += [(line("sid", badged), line("sid", bare))]
        for a, b in pairs:
            cid = a["identity"]["conversation_id"]
            self.assertEqual(draws(a), draws(b), cid)
            self.assertEqual(a["draws"], b["draws"], cid)
            self.assertEqual(turns_without_badges(a), turns_without_badges(b), cid)
            self.assertTrue(es_decisions(a), cid)
            self.assertTrue(all(d["emoji"] for d in es_decisions(a)), cid)
            self.assertTrue(all(d["emoji"] == [] for d in es_decisions(b)), "no badges in the table: an empty list")
        # a round planned with the badges replays, draw for draw
        conv = banter("replay", badged)
        self.assertTrue(system3.replay(conv, badged)["ok"])


class _Host:
    """What System3Runtime.load() needs of the station: a data dir and a log."""

    def __init__(self, root):
        self.root = Path(root)
        self.logs = []

    def data_path(self, name):
        return str(self.root / name)

    def pipeline_log(self, kind, text, extra=""):
        self.logs.append(str(text))


class FillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="s3-es-emoji-")
        self.host = _Host(self.tmp)
        self.rt = system3_runtime.System3Runtime(self.host)

    def tearDown(self):
        try:
            self.rt.store.db.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def live_like():
        """The config the station holds: saved before the badges, plus a
        supplemental ES2 made from ES1 with a feeling of its own, one badge
        the operator already cleared and one they set themselves."""
        cfg = strip_emoji(system3.default_config())
        es2 = copy.deepcopy(table(cfg, "ES1"))
        es2.update(id="ES2", label="Emotional Set 2")
        es2["categories"] = es2["categories"][:2] + [{"id": "giddy", "label": "GIDDY", "weight": 1.0,
                                                       "items": [{"id": "giddy.hysterical", "label": "hysterical"}]}]
        es2["categories"][0]["emoji"] = ""                         # surprise: cleared by the operator
        es2["categories"][1]["items"][6]["emoji"] = "!"            # anger.fury: the operator's own
        cfg["tables"].append(system3.validate_table(es2))
        cfg["defaults_added"] = ["FAV1"]
        return cfg

    def test_the_stored_config_gains_the_badges_once(self):
        rt = self.rt
        rt.store.save_config(self.live_like(), "as saved before the badges")
        rt.load()
        # ES1 is the defaults again, badge for badge
        self.assertEqual(table(rt.config, "ES1")["categories"], table(system3.default_config(), "ES1")["categories"])
        # ES2: the matching ids filled, the operator's own kept, the cleared one left clear
        es2 = table(rt.config, "ES2")
        surprise, anger, giddy = es2["categories"]
        self.assertEqual(surprise["emoji"], "")
        self.assertEqual(surprise["items"][1]["emoji"], "\U000026A1", "surprise.shock still gets its own")
        self.assertEqual(anger["emoji"], CATEGORY_EMOJI["anger"])
        self.assertEqual(anger["items"][6]["emoji"], "!")
        self.assertNotIn("emoji", anger["items"][4], "anger.anger wears its category's")
        self.assertNotIn("emoji", giddy)
        self.assertNotIn("emoji", giddy["items"][0])
        # no other family touched
        self.assertEqual([t for t in rt.config["tables"] if t["family"] != "ES"],
                         [t for t in self.live_like()["tables"] if t["family"] != "ES"])
        # remembered; ONE version for the badges, with a note; the store holds what the runtime holds
        # (another once-only fill may add its own marker and version beside it)
        self.assertIn("ES_EMOJI", rt.config["defaults_added"])
        self.assertIn("FAV1", rt.config["defaults_added"])
        noted = [v for v in rt.store.config_versions() if "ES emoji" in v["note"]]
        self.assertEqual(len(noted), 1)
        self.assertEqual(system3.config_hash(rt.store.config()), system3.config_hash(rt.config))
        self.assertIn("ES_EMOJI", rt.store.config()["defaults_added"])
        self.assertTrue(any("emoji badges" in x for x in self.host.logs))
        # once: nothing more to do...
        self.assertEqual(rt.add_missing_es_emoji(), [])
        # ...and a badge the operator clears stays cleared - even a key gone altogether
        edited = copy.deepcopy(rt.config)
        table(edited, "ES1")["categories"][1]["items"][6]["emoji"] = ""       # anger.fury cleared
        table(edited, "ES1")["categories"][2].pop("emoji")                    # fear's key gone
        rt.store.save_config(edited, "the operator cleared two badges")
        n = len(rt.store.config_versions())
        rt.load()
        self.assertEqual(table(rt.config, "ES1")["categories"][1]["items"][6]["emoji"], "")
        self.assertNotIn("emoji", table(rt.config, "ES1")["categories"][2])
        self.assertEqual(len(rt.store.config_versions()), n, "the second load saves nothing")
        self.assertEqual(len([v for v in rt.store.config_versions() if "ES emoji" in v["note"]]), 1)

    def test_a_config_that_already_wears_them_saves_nothing(self):
        rt = self.rt
        rt.load()                            # a fresh store: the defaults, which carry the badges
        n = len(rt.store.config_versions())
        self.assertEqual(rt.add_missing_es_emoji(), [])
        self.assertEqual(len(rt.store.config_versions()), n)
        self.assertNotIn("ES_EMOJI", rt.config.get("defaults_added") or [])


if __name__ == "__main__":
    unittest.main()
