"""[h3-overview] The technical overview: a tagged changelog feature, rolled,
pitched by the model at a whiteboard - its pure half (h3_overview.py) and the
door's flow (exec'd out of app.py with stubs: no station, no model, no GPU)."""
import __future__
import asyncio
import json
import re
import sys
import time
import types
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import h3_overview  # noqa: E402
import h3_speak  # noqa: E402

APP_TEXT = (ROOT / "app.py").read_text(encoding="utf-8")
FLAGS = __future__.annotations.compiler_flag


def row(commit, subject, body="", files=(), ins=10, dele=2):
    return {"commit": commit * 5, "short_commit": commit, "insertions": ins, "deletions": dele,
            "files": [{"path": p, "added": 5, "deleted": 1} for p in files],
            "git": {"subject": subject, "body": body, "committed_label": "Oct 1"}}


ROWS = [
    row("aaa111", "[s3-callarc] Calls roll an arc", "Each call rolls resolution or escalation.", ["system3.py"]),
    row("bbb222", "[flowchart] Any conversation as a flowchart", "GET /api/flow/{key}.", ["flow_chart.py"]),
    row("ccc333", "[s3-callarc] The manager cuts in", "Seat E.", ["system3.py", "app.py"]),
    row("ddd444", "Handoff notes", ""),
    row("eee555", "[handoff] the deploy note"),
    row("fff666", "Merge branch x"),
]


class Pure(unittest.TestCase):
    def test_features_group_by_first_tag(self):
        feats = h3_overview.features(ROWS)
        self.assertEqual(list(feats), ["s3-callarc", "flowchart"], "untagged and handoff rows are not features")
        arc = feats["s3-callarc"]
        self.assertEqual([c["commit"] for c in arc["commits"]], ["aaa111", "ccc333"])
        self.assertEqual(arc["subject"] if "subject" in arc else arc["commits"][0]["subject"], "Calls roll an arc")
        self.assertEqual(arc["insertions"], 20)
        self.assertIn("system3.py", arc["files"])

    def test_brief_carries_the_git(self):
        text = h3_overview.brief(h3_overview.features(ROWS)["s3-callarc"])
        for bit in ("FEATURE TAG: [s3-callarc]", "2 commit(s)", "system3.py", "COMMIT aaa111", "Seat E."):
            self.assertIn(bit, text)

    def test_parse_json_and_cap(self):
        got = h3_overview.parse('<think>hm</think> {"say": "One. Two words. Three more words here.", "do": "points"}', 4)
        self.assertEqual(got, {"say": "One. Two words.", "do": "points"})
        self.assertEqual(h3_overview.parse("nothing useful", 10), {})
        loose = h3_overview.parse('say: "It flows like water."', 10)
        self.assertEqual(loose["say"], "It flows like water.")

    def test_fill_action_props(self):
        self.assertEqual(h3_overview.fill_action(h3_overview.ACTIONS[6], {"gitlog": "aaa111 arcs"}),
                         "carries in a billboard of the git log reading: aaa111 arcs")
        self.assertEqual(h3_overview.fill_action(h3_overview.ACTIONS[5], {}),
                         "carries in a framed picture from the Pine Box gallery")

    def test_oversized_or_unfinished_sentence_is_not_clipped_into_speech(self):
        long = "When the station pauses the mixer switches to the endless set so listeners continue hearing music."
        self.assertEqual(h3_overview.parse(json.dumps({"say": long, "do": "draws an arrow"}), 10), {})
        self.assertEqual(h3_overview.cut_words("The mixer switches to", 19), "")
        self.assertEqual(h3_overview.cut_words("Listeners keep hearing music. The mixer switches to", 19),
                         "Listeners keep hearing music.")

    def test_saved_styles_receive_explanation_requirements_without_reseeding(self):
        msgs = h3_overview.messages("My saved dramatic delivery.", "FEATURE TAG: [pause-bed]", "an engineer", [], 19)
        self.assertTrue(msgs[0]["content"].startswith("My saved dramatic delivery."))
        self.assertIn(h3_overview.EXPLANATION_CONTRACT, msgs[0]["content"])
        self.assertIn("at most 19 words", msgs[1]["content"])
        self.assertEqual(msgs[0]["content"].count(h3_overview.EXPLANATION_CONTRACT), 1)
        self.assertIn("at most 19 words TOTAL", msgs[0]["content"])
        again = h3_overview.messages(msgs[0]["content"], "history", "an engineer", [], 19)
        self.assertEqual(again[0]["content"], msgs[0]["content"])

    def test_operator_s_list_is_the_starting_pool(self):
        joined = " ".join(h3_overview.ACTIONS)
        for bit in ("swinging", "salute", "whistles", "punches", "kittens", "gallery", "git log", "dialogue"):
            self.assertIn(bit, joined)
        self.assertEqual(h3_overview.ACTION_COUNTS, ("1", "2", "3"))
        self.assertGreaterEqual(len(h3_overview.SYSTEM_PROMPTS), 2)


def section():
    start = APP_TEXT.index("# --- [h3-overview] THE TECHNICAL OVERVIEW")
    end = APP_TEXT.index("# --- [h3-prompts] THE HOURLY PROMPTS", start)
    return APP_TEXT[start:end]


class FakeBook:
    def __init__(self):
        self.kinds = {}
        self.modes = {}

    def entry(self, kind):
        alts = self.kinds.get(kind)
        return {"alternatives": alts, "mode": self.modes.get(kind, "")} if alts else None

    def put_alternative(self, kind, raw):
        alts = self.kinds.setdefault(kind, [])
        alts.append(dict(raw, id="a%d" % len(alts)))
        self.modes.setdefault(kind, "fixed:a0")
        return raw

    def set_mode(self, kind, mode):
        self.modes[kind] = mode


class Door(unittest.TestCase):
    def setUp(self):
        self.rolls = []
        self.notes = {}
        self.logs = []
        self.asked = []
        self.book = FakeBook()
        self.reply = '{"say": "Meet the call arc. Every caller now gets a story. Buy it today!", "do": "draws a big arc"}'

        def weighted(key, labels, weights, label="", media=None):
            self.rolls.append(key)
            return len(labels) - 1

        def choice(key, options, label="", tabled=True):
            self.rolls.append(key)
            return list(options)[-1]

        def sample(key, options, k, label="", tabled=True):
            self.rolls.append(key)
            return list(options)[-k:]

        async def ollama(**kw):
            self.asked.append(kw)
            return {"message": {"content": self.reply}}

        page = {"entries": ROWS}
        self.ns = {"Any": Any, "asyncio": asyncio, "re": re, "time": time, "Path": Path, "h3_speak": h3_speak,
                   "segment_prompts": self.book, "s3_weighted": weighted, "s3_choice": choice, "s3_sample": sample,
                   "h3_hourly_roll_note": lambda name, key, rec=None: self.notes.setdefault(name, key),
                   "_CHANGELOG": types.SimpleNamespace(memory_page=lambda n: page, page=lambda n: page),
                   "call_ollama": ollama, "dj_settings": lambda: {"model": "m"}, "model_ctx": lambda: 4096,
                   "h3_speak_station": lambda: "Pine Box FM", "pipeline_log": lambda lane, text: self.logs.append(text),
                   "gallery_files": lambda n: [Path("a_cat.png"), Path("paper.png")],
                   "gallery_paper_file": lambda name: name == "paper.png",
                   "_RADIO": {"chat": [{"who": "a", "name": "Ash", "kind": "banter", "text": "This station never sleeps, folks."}]}}
        exec(compile(section(), "app.py", "exec", flags=FLAGS, dont_inherit=True), self.ns)  # noqa: S102

    def prepare(self):
        return asyncio.run(self.ns["h3_overview_prepare"]({"kind": "overview"}))

    def test_every_choice_is_a_dice_door(self):
        got = self.prepare()
        for key in ("h3.overview_feature", "h3.overview_presenter", "h3.overview_action_count",
                    "h3.overview_action", "h3.overview_system"):
            self.assertIn(key, self.rolls)
        self.assertEqual(got["tag"], "flowchart", "the feature the dice landed on")
        self.assertEqual(got["presenter"], h3_overview.PRESENTERS[-1])
        self.assertEqual(len(got["actions"]), 3, "the count die landed on 3")
        self.assertIn("ov_feature", self.notes)
        # the last three actions: the gallery picture, the git log and the dialogue billboard, props filled
        self.assertIn("a cat", got["actions"][0])
        self.assertIn("bbb222", got["actions"][1])
        self.assertIn("This station never sleeps", got["actions"][2])
        self.assertIn("ov_gallery", self.notes)

    def test_the_system_prompts_live_in_the_book(self):
        got = self.prepare()
        alts = self.book.kinds[h3_overview.PROMPT_KIND]
        self.assertEqual([a["name"] for a in alts], [n for n, _t in h3_overview.SYSTEM_PROMPTS])
        self.assertEqual(self.book.modes[h3_overview.PROMPT_KIND], "random")
        self.assertEqual(got["system"], h3_overview.SYSTEM_PROMPTS[-1][0])
        msgs = self.asked[0]["messages"]
        self.assertTrue(msgs[0]["content"].startswith(h3_overview.SYSTEM_PROMPTS[-1][1]))
        self.assertIn(h3_overview.EXPLANATION_CONTRACT, msgs[0]["content"])
        self.assertIn("FEATURE TAG: [flowchart]", msgs[1]["content"])
        # [h3-overview-model] a live ask: it waits for a writer slot instead of an empty deferral
        self.assertEqual(self.asked[0]["purpose"], "h3:overview live")
        # and the model is the station's setting: dj_settings() has no "model" (every pitch was a KeyError)
        self.assertNotIn('call_ollama(model=dj_settings()["model"]', APP_TEXT)
        # a fixed choice in the book is honoured, no roll
        self.book.modes[h3_overview.PROMPT_KIND] = "fixed:a0"
        self.rolls.clear()
        self.assertEqual(self.ns["h3_overview_system"]()[0], h3_overview.SYSTEM_PROMPTS[0][0])
        self.assertNotIn("h3.overview_system", self.rolls)

    def test_pitch_and_scene_are_taken_once(self):
        got = self.prepare()
        cap = h3_speak.word_cap(10)
        self.assertLessEqual(len(got["say"].split()), cap)
        self.assertEqual(h3_speak.speech_why(got["say"]), "")
        self.assertIn("whiteboard", got["scene"])
        self.assertIn("draws a big arc", got["scene"])
        self.assertEqual(got["by"], "model")
        self.assertIs(self.ns["h3_overview_take"]()["say"], got["say"])
        self.assertIsNone(self.ns["h3_overview_take"](), "taken once")

    def test_no_model_falls_back_to_the_feature(self):
        self.reply = "I cannot help with that"
        got = self.prepare()
        self.assertEqual(got["by"], "fallback")
        self.assertTrue(got["say"].startswith("Pine Box FM just got better."))
        self.assertEqual(h3_speak.speech_why(got["say"]), "")

    def test_no_features_no_overview(self):
        self.ns["_CHANGELOG"] = types.SimpleNamespace(memory_page=lambda n: {"entries": []},
                                                      page=lambda n: {"entries": []})
        self.assertIsNone(self.prepare())
        self.assertIsNone(self.ns["h3_overview_take"]())


class Wiring(unittest.TestCase):
    def test_the_hour_and_the_door_use_it(self):
        for bit in ('"kind")', 'out["kind"] = "overview" if "overview"', "await h3_overview_prepare(",
                    "picked = h3_prompts_picked_take() or h3_prompts_pick()", 'entry["overview"] =',
                    '"id": "base-overview", "name": "Technical overview", "kind": "overview"'):
            self.assertIn(bit, APP_TEXT)
        js = (ROOT / "desktop" / "renderer" / "ad-viewer.js").read_text(encoding="utf-8")
        self.assertIn("['ov_feature', 'feature presented']", js)
        self.assertIn("['kind', 'Kind', 'input'", js)
        self.assertEqual(js, (ROOT / "app" / "src" / "main" / "assets" / "pine-views" / "ad-viewer.js").read_text(
            encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
