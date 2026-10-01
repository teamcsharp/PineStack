"""[h3-feature] {feature} and {releaselog}: "I need the technical overview prompt to
grab a feature randomly from the release log ... I'm expecting to see {feature}
and {releaselog} indicating a roulette roll" and "make sure we have a preset that
is utilizing every bracketed term" (the operator, 2026-10-01).

The pure builders (h3_slots.py), the one roll both slots share (app.py, compiled
out of the source against stubs - the station is never imported), the overview
keeping a preset's own words, the one-time reword of the untouched base preset,
and the Every slot preset holding every term the catalogue lists."""
import ast
import re
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import h3_overview  # noqa: E402
import h3_slots  # noqa: E402

APP_TEXT = (ROOT / "app.py").read_text(encoding="utf-8")
TREE = ast.parse(APP_TEXT)

ROWS = [
    {"short_commit": "60e37c0", "git": {"subject": "[tablet-update-ask] One press builds, signs and installs the PineTab",
                                        "body": "The desk button starts the update on click. Co-Authored-By: x\n",
                                        "committed_label": "Oct 1, 03:25"},
     "files": [{"path": "deploy.sh", "added": 12, "deleted": 3}], "insertions": 46, "deletions": 12},
    {"short_commit": "76f7d0c", "git": {"subject": "[talk-always] The DJs talk again", "body": "Measured over 12 h.",
                                        "committed_label": "Oct 1, 03:24"},
     "files": [], "insertions": 400, "deletions": 13},
]


def app_function(name, env):
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            exec(compile(ast.Module([node], []), "app.py:" + name, "exec"), env)  # noqa: S102
            return env[name]
    raise AssertionError("app.py has no function " + name)


def app_value(name):
    for node in TREE.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("app.py has no " + name)


class Builders(unittest.TestCase):
    def setUp(self):
        self.feats = h3_overview.features(ROWS)

    def test_both_are_named_slots(self):
        self.assertIn("feature", h3_slots.NAMED)
        self.assertIn("releaselog", h3_slots.NAMED)
        self.assertEqual(h3_slots.tokens("pitch {feature} from {releaselog} and {feature2}"),
                         ["feature", "releaselog", "feature2"])
        self.assertEqual(h3_slots.base("releaselog2"), "releaselog")
        names = {r["name"] for r in h3_slots.catalogue()}
        self.assertLessEqual({"feature", "releaselog"}, names)

    def test_the_words_they_become(self):
        f = self.feats["tablet-update-ask"]
        self.assertEqual(h3_slots.feature(f),
                         'the Pine Box feature "One press builds, signs and installs the PineTab" [tablet-update-ask]')
        log = h3_slots.releaselog(f)
        self.assertTrue(log.startswith("the release log of [tablet-update-ask] (1 commit, +46/-12 lines): 60e37c0"))
        self.assertIn("The desk button starts the update on click.", log)
        self.assertNotIn("Co-Authored", log)

    def test_the_app_pattern_names_them(self):
        m = re.search(r'^H3_SLOT_NAMES = r"\(\?:([a-z|]+)\)', APP_TEXT, re.M)
        self.assertEqual(tuple(m.group(1).split("|")), h3_slots.NAMED)


class OneRoll(unittest.TestCase):
    def setUp(self):
        self.rolls = []
        feats = h3_overview.features(ROWS)

        def weighted(key, labels, weights, label=""):
            self.rolls.append(key)
            return len(self.rolls) % len(labels)      # each roll lands somewhere new

        self.env = {"time": time, "Any": object, "h3_overview": h3_overview, "h3_slots": h3_slots,
                    "_H3_SLOT_MEMO": {"at": time.time(), "vals": {}}, "H3_SLOT_KEEP_S": 1800.0,
                    "H3_SLOT_LABELS": {"feature": "which feature"}, "s3_weighted": weighted,
                    "_h3_slot_note": lambda *a: None, "pipeline_log": lambda *a: None,
                    "h3_feature_pool": lambda page=None: feats}
        app_function("h3_feature_take", self.env)
        self.slot = app_function("h3_slot_feature", self.env)

    def test_feature_and_releaselog_share_the_roll(self):
        name = self.slot("feature")
        log = self.slot("releaselog")
        self.assertEqual(self.rolls, ["h3.overview_feature"], "one roll for both")
        tag = re.search(r"\[([\w-]+)\]$", name).group(1)
        self.assertIn("[%s]" % tag, log)
        self.slot("feature2")
        self.assertEqual(len(self.rolls), 2, "a digit is its own roll")
        self.assertIs(self.env["h3_feature_take"](None, ""), self.env["_H3_SLOT_MEMO"]["features"][""])

    def test_the_overview_pitches_the_same_feature(self):
        self.assertIn('_take = globals().get("h3_feature_take")', APP_TEXT)
        self.assertIn('feature = _take(feats, "") if _take else None', APP_TEXT)


class PresetWords(unittest.TestCase):
    def base(self):
        return {b["id"]: b for b in app_value("H3_PROMPTS_BASE")}

    def test_the_overview_keeps_words_that_name_the_feature(self):
        self.assertIn(r'if re.search(r"\{(?:feature|releaselog)\d?\}", fields.get("goal") or ""):', APP_TEXT)
        self.assertIn('out["direction"] = h3_overview.direction(', APP_TEXT)
        d = h3_overview.direction("a stern drill sergeant", "draws an arrow.", ["snaps a crisp salute"])
        self.assertEqual(d, "The presenter is a stern drill sergeant. draws an arrow. "
                            "During it the presenter snaps a crisp salute.")

    def test_the_base_overview_rolls_both(self):
        goal = self.base()["base-overview"]["goal"]
        self.assertIn("{feature}", goal)
        self.assertIn("{releaselog}", goal)

    def test_every_slot_uses_every_term(self):
        p = self.base()["base-every-slot"]
        words = " ".join(str(p.get(f) or "") for f in ("goal", "speech", "host", "clip", "gallery"))
        for row in h3_slots.catalogue():
            name = row["name"]
            if name == "a|b|c":
                self.assertRegex(words, r"\{[^{}|]+(\|[^{}|]+)+\}")
            else:
                self.assertIn("{%s}" % name, words, name)
        self.assertIn("{arena2}", words)
        limits = app_value("H3_PROMPTS_LIMITS")
        for f in ("goal", "speech", "host"):
            self.assertLessEqual(len(p[f]), limits[f], f)

    def test_the_untouched_overview_is_reworded_once(self):
        base = app_value("H3_PROMPTS_BASE")
        env = {"time": time, "Any": object, "H3_PROMPTS_BASE": base, "H3_PROMPTS_MOST": 60,
               "H3_PROMPTS_LIMITS": app_value("H3_PROMPTS_LIMITS"),
               "H3_PROMPTS_BASE_REWORD": app_value("H3_PROMPTS_BASE_REWORD"),
               "_h3_prompts_text": lambda v, f: " ".join(str(v or "").split()),
               "_h3_prompts_preset": lambda raw, pid: dict(raw, id=pid)}
        seed = app_function("h3_prompts_seed_base", env)
        old = env["H3_PROMPTS_BASE_REWORD"]["base-overview"]["goal"]
        store = {"presets": [{"id": "base-overview", "name": "Technical overview", "goal": old}],
                 "seeded": [b["id"] for b in base]}
        seed(store)
        self.assertIn("{releaselog}", store["presets"][0]["goal"])
        self.assertEqual(store["reworded"], ["base-overview"])
        edited = {"presets": [{"id": "base-overview", "goal": "my own words"}], "seeded": [b["id"] for b in base]}
        seed(edited)
        self.assertEqual(edited["presets"][0]["goal"], "my own words", "an edit is never overwritten")
        store["presets"][0]["goal"] = old
        seed(store)
        self.assertEqual(store["presets"][0]["goal"], old, "once only")


if __name__ == "__main__":
    unittest.main()
